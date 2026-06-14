#!/usr/bin/env python3
"""Historical (backfill) YouTube insight extraction — JSON-only, NO publish.

Mirrors the DAILY extraction's quality EXACTLY (same routine_youtube.md STEP 2
rubric, same per-transcript Opus extraction, same entity-presence guard +
quarantine, same deterministic timestamp + quote-verification postprocess) but
differs ONLY in I/O paths and the publish step:

  * reads backfill transcripts from   youtube-history/<slug>/<video_id>.json
  * writes knowledge cards to          youtube-history/_processed/<slug>/<video_id>.json
  * quarantines topic-mismatch cards   youtube-history/_quarantine/<slug>/<video_id>.json
  * writes a run summary to            youtube-history/_runlog/extract_<YYYY-MM-DD>.md
  * NEVER renders HTML, rebuilds the dashboard, or touches git.

The quality logic is REUSED (imported) from youtube_extract.py — not forked:
  build_prompt(), postprocess_record(), entity_presence(), tier_for(), and the
  ENTITY_PRESENCE_* thresholds. The card schema is the daily knowledge-card
  schema (routines/routine_youtube.md STEP 2 OUTPUT FORMAT).

Subcommands:
  worklist [--limit N] [--order newest|oldest|longest]
        List backfill transcripts that have NO card yet in _processed/ OR
        _quarantine/ (dedup by output-file existence). Default order = newest
        upload_date first (most valuable first). --limit N caps the run so you
        can process quota-bounded batches and resume next run. TSV columns:
            slug  video_id  tier  mins  seg|noseg  channel  title

  prompt <slug> <video_id>
        Emit the extraction prompt for ONE transcript — IDENTICAL to the daily
        rubric+metadata+transcript prompt (youtube_extract.build_prompt).

  finalize <slug>/<video_id> ...   (run ONCE, AFTER every extraction agent done)
        For each just-written card: run postprocess_record (timestamps +
        quote_verified), then the entity-presence guard. Cards that fail the
        guard are MOVED to _quarantine/<slug>/. Then write/append the run
        summary to _runlog/extract_<date>.md. No HTML, no dashboard, NO git.
        Run this only after ALL spawned extraction agents for the batch have
        completed, so a late agent can't overwrite a postprocessed card.

NO network, NO API key, NO git, NO HTML/dashboard. Pure local file work.
"""
import argparse
import datetime
import glob
import json
import os
import sys
from pathlib import Path

# Reuse the daily quality logic — do NOT fork it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import youtube_extract as yx  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _default_history_root():
    """youtube-history/ lives OUTSIDE the git repo and MUST resolve to the EXACT
    same absolute path the collector (scripts/backfill_youtube_history.py) writes
    to — otherwise the worklist sees an empty/nonexistent dir. Single-source it
    from the collector when that module is importable (co-located in scripts/);
    otherwise fall back to the identical literal the collector defines."""
    try:
        from backfill_youtube_history import DEFAULT_HISTORY_ROOT as _R
        return Path(_R)
    except Exception:
        return (Path.home() / "Dropbox (Personal)" / "Business" / "InvestTool"
                / "market-intelligence" / "youtube-history")


# Resolved at import; overridable via $YOUTUBE_HISTORY_ROOT or --history-root.
HIST_DIR = Path(os.environ.get("YOUTUBE_HISTORY_ROOT") or _default_history_root()).expanduser()
PROC_DIR = HIST_DIR / "_processed"
QUAR_DIR = HIST_DIR / "_quarantine"
RUNLOG_DIR = HIST_DIR / "_runlog"

# Reserved top-level names under youtube-history/ (outputs/state, not channel slugs).
_RESERVED = {"_processed", "_quarantine", "_runlog", "_state"}


def _set_history_root(root):
    """Repoint all history paths (used by the --history-root override)."""
    global HIST_DIR, PROC_DIR, QUAR_DIR, RUNLOG_DIR
    HIST_DIR = Path(root).expanduser()
    PROC_DIR = HIST_DIR / "_processed"
    QUAR_DIR = HIST_DIR / "_quarantine"
    RUNLOG_DIR = HIST_DIR / "_runlog"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _err(*a):
    """Progress/summary output goes to STDERR so `worklist` stdout stays pure TSV
    (the orchestrator parses it) even when worklist self-heals first."""
    print(*a, file=sys.stderr)


def _hist_records():
    """All backfill transcript records: youtube-history/<slug>/<id>.json
    (excluding the reserved _processed/_quarantine/_runlog output dirs)."""
    out = []
    for f in sorted(glob.glob(str(HIST_DIR / "*" / "*.json"))):
        slug = Path(f).parent.name
        if slug in _RESERVED:
            continue
        try:
            d = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue
        d["_slug"] = slug
        d["_path"] = f
        out.append(d)
    return out


def _hist_record(slug, vid):
    f = HIST_DIR / slug / f"{vid}.json"
    if not f.exists():
        return None
    try:
        d = json.load(open(f))
    except (json.JSONDecodeError, OSError):
        return None
    d["_slug"] = slug
    d["_path"] = str(f)
    return d


def _is_finalized(card):
    """A card is FINALIZED only once the postprocess step has stamped
    `quote_verified` on its quoted insights (and mapped their timestamps). A RAW
    agent card has quotes but no `quote_verified` — it must NOT count as done,
    else an interrupted wave leaves a silent dedup trap. A card with zero quotes
    is trivially finalized (postprocess has nothing to verify)."""
    quoted = qv = 0
    for t in card.get("themes", []):
        for ins in t.get("insights", []):
            if ins.get("quote"):
                quoted += 1
            if "quote_verified" in ins:
                qv += 1
    return quoted == 0 or qv >= quoted


def _card_status(slug, vid):
    """'finalized' | 'raw' | 'quarantined' | None for a transcript's output card.
    'done' for dedup == finalized or quarantined; 'raw' still needs finalize."""
    if (QUAR_DIR / slug / f"{vid}.json").exists():
        return "quarantined"
    pf = PROC_DIR / slug / f"{vid}.json"
    if not pf.exists():
        return None
    try:
        card = json.load(open(pf))
    except (json.JSONDecodeError, OSError):
        return "raw"   # unreadable/corrupt -> not done; heal/finalize will re-handle
    return "finalized" if _is_finalized(card) else "raw"


def _raw_cards():
    """Every card already in _processed/ that is NOT yet finalized (interrupted-wave
    leftovers). Returns [(slug, vid), ...]. These need finalize, NOT re-extraction."""
    out = []
    for f in sorted(glob.glob(str(PROC_DIR / "*" / "*.json"))):
        slug = Path(f).parent.name
        vid = Path(f).name[:-5]
        try:
            card = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            out.append((slug, vid)); continue
        if not _is_finalized(card):
            out.append((slug, vid))
    return out


def _global_done_vids():
    """Set of video_ids that are DONE *anywhere* in the corpus: a FINALIZED card
    under ANY slug in _processed/, OR any card in _quarantine/. A YouTube video_id
    is globally unique, so one finalized card means the whole video is done — even
    if a second channel slug re-hosts the same episode (cross-posted shows). This
    is the global-video_id dedup: one video = one card, regardless of which slug
    the collector filed the transcript under. Built once per worklist call."""
    done = set()
    for f in glob.glob(str(PROC_DIR / "*" / "*.json")):
        try:
            card = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue   # unreadable/raw -> not done (heal/finalize will re-handle)
        if _is_finalized(card):
            done.add(Path(f).name[:-5])
    for f in glob.glob(str(QUAR_DIR / "*" / "*.json")):
        done.add(Path(f).name[:-5])
    return done


def worklist(order="newest", limit=None):
    """Backfill transcripts that still need EXTRACTION: a transcript is present and
    its video_id has NO FINALIZED (or quarantined) card under ANY slug. Dedup is
    by FINALIZED status AND GLOBAL video_id (one video = one card; a cross-posted
    episode already done under another slug is not re-extracted) — not mere
    file presence. Callers should self-heal first (see cmd_worklist / `heal`) so
    raw leftovers become finalized rather than re-extracted."""
    done_vids = _global_done_vids()
    elig = []
    for d in _hist_records():
        if not (d.get("transcript") or d.get("transcript_available")):
            continue
        if d["video_id"] in done_vids:   # finalized/quarantined under ANY slug
            continue
        elig.append(d)

    if order == "oldest":
        elig.sort(key=lambda d: (d.get("upload_date") or "", d["video_id"]))
    elif order == "longest":
        elig.sort(key=lambda d: -(d.get("duration_seconds") or 0))
    else:  # newest (default) — most valuable first
        elig.sort(key=lambda d: (d.get("upload_date") or "", d["video_id"]), reverse=True)

    if limit is not None:
        elig = elig[:limit]
    return elig


def cmd_worklist(args):
    # SELF-HEAL FIRST: finalize any raw leftovers from an interrupted wave so they
    # count as done and are never re-extracted — THEN list the truly-missing. This
    # is what makes an interrupted wave self-heal on the next run instead of leaving
    # a silent dedup trap. (--no-heal for a pure read-only listing.) Heal output is
    # on stderr; only the TSV worklist goes to stdout.
    if not getattr(args, "no_heal", False):
        heal(date=getattr(args, "date", None))
    rows = worklist(order=args.order, limit=args.limit)
    for d in rows:
        print("\t".join([
            d["_slug"], d["video_id"], yx.tier_for(d),
            str(round((d.get("duration_seconds") or 0) / 60)),
            "seg" if d.get("transcript_segments") else "noseg",
            (d.get("channel_name") or "")[:28], (d.get("video_title") or "")[:60],
        ]))


def cmd_prompt(args):
    d = _hist_record(args.slug, args.video_id)
    if not d:
        sys.exit(f"history transcript not found: youtube-history/{args.slug}/{args.video_id}.json")
    # Identical prompt to the daily path — same rubric, metadata, transcript.
    print(yx.build_prompt(d))


def _parse_items(items):
    """Accept 'slug/video_id' (or 'slug:video_id') tokens -> [(slug, vid), ...]."""
    out = []
    for it in items:
        it = it.strip()
        if not it:
            continue
        sep = "/" if "/" in it else (":" if ":" in it else None)
        if not sep:
            sys.exit(f"bad item '{it}' — expected slug/video_id")
        slug, vid = it.rsplit(sep, 1)
        out.append((slug.strip(), vid.strip()))
    return out


def _count_insights(card):
    return sum(len(t.get("insights", [])) for t in card.get("themes", []))


def _finalize_one(slug, vid):
    """Finalize ONE already-written card in place: postprocess (timestamps +
    quote_verified) then the entity-presence guard. Cards below the guard are MOVED
    to _quarantine/. No extraction. Returns (status, info):
      ('kept', {...stats}) | ('quarantined', {...}) | ('missing', None) | ('badjson', None)
    Shared by `finalize` (per-wave) and `heal` (self-heal of raw leftovers)."""
    pf = PROC_DIR / slug / f"{vid}.json"
    if not pf.exists():
        return ("missing", None)
    try:
        card = json.load(open(pf))
    except (json.JSONDecodeError, OSError):
        return ("badjson", None)
    raw = _hist_record(slug, vid) or {}

    # 1) deterministic postprocess (timestamps + quote_verified) — reused as-is.
    q_tot, q_map, q_ver, _ = yx.postprocess_record(card, raw)
    json.dump(card, open(pf, "w"), ensure_ascii=False, indent=2)

    # 2) entity-presence guard — reused threshold/function from the daily path.
    frac, n_ent = yx.entity_presence(card, raw)
    if frac < yx.ENTITY_PRESENCE_MIN:
        qf = QUAR_DIR / slug / f"{vid}.json"
        qf.parent.mkdir(parents=True, exist_ok=True)
        json.dump(card, open(qf, "w"), ensure_ascii=False, indent=2)
        os.remove(pf)
        return ("quarantined", {"slug": slug, "video_id": vid, "title": card.get("video_title"),
                                "entity_presence": round(frac, 3), "n_entities": n_ent})
    return ("kept", {"slug": slug, "video_id": vid, "title": card.get("video_title"),
                     "insights": card.get("insight_total") or _count_insights(card),
                     "quotes": q_tot, "verified": q_ver, "timestamped": q_map})


def _run_finalize(items, date, label):
    """Finalize a list of (slug, vid), print per-card lines, write a run summary."""
    processed, quarantined = [], []
    for slug, vid in items:
        status, info = _finalize_one(slug, vid)
        if status == "missing":
            _err(f"  {label}: {slug}/{vid} — no card in _processed/, skip "
                 f"(extraction agent did not write it?)")
        elif status == "badjson":
            _err(f"  {label}: {slug}/{vid} — card is not valid JSON; leaving in place")
        elif status == "quarantined":
            quarantined.append(info)
            _err(f"  {label}: {slug}/{vid} — ✗ QUARANTINED "
                 f"({int(info['entity_presence']*100)}% of {info['n_entities']} entities) -> _quarantine/")
        else:
            processed.append(info)
            _err(f"  {label}: {slug}/{vid} — ✓ {info['insights']} insights, "
                 f"quotes {info['verified']}/{info['quotes']} verified, {info['timestamped']} timestamped")
    _write_summary(date, processed, quarantined, label)
    return processed, quarantined


def heal(date=None):
    """SELF-HEAL: finalize any RAW (un-finalized) cards already in _processed/ —
    interrupted-wave leftovers. Cheap: postprocess + guard only, NO re-extraction.
    Returns the number healed (kept + quarantined). Writes a summary only if it
    actually healed something."""
    date = date or _utc_now().strftime("%Y-%m-%d")
    raws = _raw_cards()
    if not raws:
        return 0
    _err(f"self-heal: finalizing {len(raws)} raw card(s) left by an interrupted wave...")
    processed, quarantined = _run_finalize(raws, date, "heal")
    return len(processed) + len(quarantined)


def cmd_heal(args):
    n = heal(date=args.date)
    if n == 0:
        _err("heal: no raw cards in _processed/ — nothing to finalize. (All cards are finalized.)")


def cmd_finalize(args):
    date = args.date or _utc_now().strftime("%Y-%m-%d")
    _run_finalize(_parse_items(args.items), date, "finalize")


def _write_summary(date, processed, quarantined, label="finalize"):
    RUNLOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = RUNLOG_DIR / f"extract_{date}.md"
    ts = _utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    tot_insights = sum(p["insights"] for p in processed)
    tot_quotes = sum(p["quotes"] for p in processed)
    tot_verified = sum(p["verified"] for p in processed)
    tot_ts = sum(p["timestamped"] for p in processed)
    pct = (100 * tot_verified // tot_quotes) if tot_quotes else 0
    kind = "self-heal" if label == "heal" else "extraction"

    lines = []
    lines.append(f"## Backfill {kind} run — {ts}")
    lines.append("")
    lines.append(f"- Transcripts {'healed' if label=='heal' else 'processed'} (kept): **{len(processed)}**")
    lines.append(f"- Quarantined (entity-presence < {int(yx.ENTITY_PRESENCE_MIN*100)}%): "
                 f"**{len(quarantined)}**")
    lines.append(f"- Total insights: **{tot_insights}**")
    lines.append(f"- Quotes verified / total: **{tot_verified} / {tot_quotes}** ({pct}%)")
    lines.append(f"- Quotes timestamped: **{tot_ts}**")
    if processed:
        lines.append("")
        lines.append("| slug/video_id | insights | quotes verified/total | timestamped |")
        lines.append("|---|---|---|---|")
        for p in processed:
            lines.append(f"| {p['slug']}/{p['video_id']} | {p['insights']} | "
                         f"{p['verified']}/{p['quotes']} | {p['timestamped']} |")
    if quarantined:
        lines.append("")
        lines.append("**Quarantined (NOT kept — review & re-extract from correct transcript):**")
        for q in quarantined:
            lines.append(f"- `{q['slug']}/{q['video_id']}` — {q['title']} "
                         f"({int(q['entity_presence']*100)}% of {q['n_entities']} entities present)")
    lines.append("")
    block = "\n".join(lines) + "\n"

    # Append (multiple runs per day accumulate under the same dated file).
    with open(logf, "a", encoding="utf-8") as fh:
        fh.write(block)

    _err("\n" + "=" * 60)
    _err(block.rstrip())
    _err("=" * 60)
    _err(f"Run summary appended to {logf}")
    _err("(JSON-only: no HTML report, no dashboard rebuild, no git.)")


def main():
    p = argparse.ArgumentParser(description="Historical (backfill) YouTube extraction — JSON-only, no publish.")
    # --history-root mirrors the collector's flag; without it, the path resolves to
    # the same external DEFAULT_HISTORY_ROOT the collector writes to.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--history-root", default=None,
                        help="override youtube-history/ root (default: same as the collector)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("worklist", parents=[common],
                       help="self-heal raw leftovers, then list transcripts still needing EXTRACTION")
    a.add_argument("--limit", type=int, default=None, help="process at most N this run")
    a.add_argument("--order", choices=["newest", "oldest", "longest"], default="newest")
    a.add_argument("--no-heal", action="store_true",
                   help="pure read-only listing; skip the self-heal of raw leftovers")
    a.add_argument("--date", default=None, help="date stamp for any self-heal run summary")
    a.set_defaults(fn=cmd_worklist)

    a = sub.add_parser("heal", parents=[common],
                       help="finalize any RAW (un-finalized) cards already in _processed/ — no re-extraction")
    a.add_argument("--date", default=None)
    a.set_defaults(fn=cmd_heal)

    a = sub.add_parser("prompt", parents=[common], help="emit the extraction prompt for one transcript")
    a.add_argument("slug")
    a.add_argument("video_id")
    a.set_defaults(fn=cmd_prompt)

    a = sub.add_parser("finalize", parents=[common], help="postprocess + entity guard + run summary (after agents done)")
    a.add_argument("items", nargs="+", help="slug/video_id tokens just extracted")
    a.add_argument("--date", default=None)
    a.set_defaults(fn=cmd_finalize)

    args = p.parse_args()
    if getattr(args, "history_root", None):
        _set_history_root(args.history_root)
    args.fn(args)


if __name__ == "__main__":
    main()
