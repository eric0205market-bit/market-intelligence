#!/usr/bin/env python3
"""Historical (backfill) Technology insight extraction — JSON-only, NO publish.

Clone of scripts/concepts_backfill_extract.py for the Technology KNOWLEDGE track.
Mirrors the DAILY Technology quality (routine_technology.md STEP 2 rubric, per-article
SONNET extraction, entity-presence guard + quarantine, deterministic quote_verified
postprocess) — differing ONLY in I/O paths and the publish step:

  * reads backfill articles from   technology-history/<slug>/<record_id>.json
  * writes knowledge cards to        technology-history/_processed/<slug>/<record_id>.json
  * quarantines topic-mismatch cards technology-history/_quarantine/<slug>/<record_id>.json
  * writes a run summary to          technology-history/_runlog/extract_<YYYY-MM-DD>.md
  * NEVER renders HTML, rebuilds the dashboard, or touches git.

The quality logic is REUSED (imported) from publish_technology.py — not forked:
  postprocess_record() (sets quote_verified by checking the quote against the raw
  text; scrubs @handle/URL/login byline junk via clean_author), entity_presence(),
  and ENTITY_PRESENCE_MIN. The extraction prompt is the daily routine_technology.md
  STEP 2 rubric (single-sourced from the routine file) + the raw record, so quality
  is identical to the daily path. Cards carry source_type="technology" (set by the
  rubric) and processor="claude-code-sub-sonnet" (subscription SONNET, never Opus,
  NEVER the paid API).

SCOPE — all 12 core source dirs in technology-history/ (~2,961 raw records). NO
exclusions (the collector already applied a word-floor + render-retry, so the raw
tier is already clean); the structural worklist pre-filter is therefore disabled.

Subcommands (identical contract to concepts_backfill_extract.py):
  worklist [--limit N] [--order newest|oldest|longest]
        Self-heal raw leftovers first, then list backfill articles that still need
        EXTRACTION (no FINALIZED card under _processed/, no _quarantine/ card).
        Dedup by FINALIZED status AND global record_id — not mere file presence.
        TSV columns:  slug  record_id  words  source_name  title
  prompt <slug> <record_id>
        Emit the per-article extraction prompt (daily rubric + raw record).
  finalize <slug>/<record_id> ...   (run ONCE, AFTER every extraction agent done)
        postprocess_record (quote_verified) + entity-presence guard (quarantine
        topic-mismatch cards) + run summary. No HTML, no dashboard, NO git.
  heal  Finalize any RAW (un-finalized) cards already in _processed/ — no re-extraction.

NO network, NO API key, NO git, NO HTML/dashboard. Pure local file work.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# Reuse the DAILY Technology quality logic — do NOT fork it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_technology as pt  # noqa: E402  -> postprocess_record, entity_presence, ENTITY_PRESENCE_MIN, clean_author

REPO = Path(__file__).resolve().parent.parent
ROUTINE = REPO / "routines" / "routine_technology.md"

# technology-history/ lives OUTSIDE the git repo (sibling of concepts-history/). Use the
# same literal the collector (backfill_technology_history.py) writes to; override via
# $TECHNOLOGY_HISTORY_ROOT or --history-root. (Literal avoids importing the collector,
# which would pull in Playwright.)
DEFAULT_HISTORY_ROOT = (
    Path.home() / "Dropbox (Personal)" / "Business" / "InvestTool"
    / "market-intelligence" / "technology-history"
)
HIST_DIR = Path(os.environ.get("TECHNOLOGY_HISTORY_ROOT") or DEFAULT_HISTORY_ROOT).expanduser()
PROC_DIR = HIST_DIR / "_processed"
QUAR_DIR = HIST_DIR / "_quarantine"
RUNLOG_DIR = HIST_DIR / "_runlog"

# Reserved top-level names under technology-history/ (outputs/state, not source slugs).
_RESERVED = {"_processed", "_quarantine", "_runlog", "_state"}
# NO source exclusions for Technology — all 12 core source dirs are in scope.
HEAVY_EXCLUDE = set()

# STRUCTURAL pre-filter for the extraction worklist (theme-agnostic — URL path + word
# floor). DISABLED for Technology: the backfill collector already applied a word-floor
# (MIN_ARTICLE_WORDS) + render-retry, so the raw tier is already clean and every record
# is in scope (~2,961). Mechanism kept for future tuning; defaults are permissive so
# NOTHING is dropped from the worklist. Records are only ever SKIPPED, never deleted.
WORKLIST_DROP_PATHS = {}          # no per-source genre drops
GLOBAL_MIN_WORDS = 0              # no global word floor (collector already gated)
WORKLIST_MIN_WORDS = {}           # no per-source overrides


# Deterministic cookie-consent-banner signature. Phase-1's SPA render-retry (W&B is a
# JS SPA) sometimes captured the OneTrust "Privacy Preference Center" consent
# interstitial as the whole article body instead of the post. Those records have NO
# article content — a Sonnet agent can only refuse them, so skip them at the worklist
# and never spend a call. NARROW by construction: requires BOTH marker phrases within
# the first 400 chars, so a real article that merely mentions cookies is never dropped
# (verified: all 180 matches were pure banners, 422-868w, zero article content).
COOKIE_BANNER_RE = re.compile(
    r"Privacy Preference Center.{0,120}"
    r"When you visit any website, it may store or retrieve information on your browser",
    re.S)


def _is_cookie_banner(rec):
    return bool(COOKIE_BANNER_RE.search((rec.get("text") or "")[:400]))


def _worklist_drop(rec):
    """Return a drop-reason ('cookie-banner' | 'genre:<frag>' | 'length:<Nw>') if this
    raw record is junk, else None. Cookie-banner is the deterministic contamination
    skip; the rest is URL-path + word-floor (theme-agnostic). A GLOBAL word floor
    applies to every source; per-source WORKLIST_MIN_WORDS / WORKLIST_DROP_PATHS
    override it."""
    if _is_cookie_banner(rec):
        return "cookie-banner"
    slug = rec.get("_slug") or rec.get("source_slug", "")
    path = urlparse(rec.get("source_url", "")).path.lower()
    for frag in WORKLIST_DROP_PATHS.get(slug, ()):
        if frag in path:
            return f"genre:{frag}"
    floor = WORKLIST_MIN_WORDS.get(slug, GLOBAL_MIN_WORDS)
    w = rec.get("word_count") or len((rec.get("text") or "").split())
    if w < floor:
        return f"length:<{floor}w"
    return None

PROCESSOR = "claude-code-sub-sonnet"   # subscription SONNET, never Opus, NEVER the paid API


def _set_history_root(root):
    global HIST_DIR, PROC_DIR, QUAR_DIR, RUNLOG_DIR
    HIST_DIR = Path(root).expanduser()
    PROC_DIR = HIST_DIR / "_processed"
    QUAR_DIR = HIST_DIR / "_quarantine"
    RUNLOG_DIR = HIST_DIR / "_runlog"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _err(*a):
    """Progress/summary to STDERR so `worklist` stdout stays pure TSV even when it
    self-heals first (the orchestrator parses stdout)."""
    print(*a, file=sys.stderr)


# --- history (raw) indexing -------------------------------------------------
def _hist_records():
    """All backfill article records: technology-history/<slug>/<record_id>.json,
    excluding reserved output dirs AND the deferred heavy slugs."""
    out = []
    for f in sorted(glob.glob(str(HIST_DIR / "*" / "*.json"))):
        slug = Path(f).parent.name
        if slug in _RESERVED or slug in HEAVY_EXCLUDE:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        d["_slug"] = slug
        d["_path"] = f
        out.append(d)
    return out


def _hist_record(slug, rid):
    f = HIST_DIR / slug / f"{rid}.json"
    if not f.exists():
        return None
    try:
        d = json.load(open(f, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    d["_slug"] = slug
    d["_path"] = str(f)
    return d


# --- finalized-status dedup -------------------------------------------------
# NOTE vs youtube_backfill: the daily Technology rubric tells the agent to WRITE
# `quote_verified: false` on every insight, so YouTube's "quote_verified key present"
# test cannot distinguish a raw agent card from a finalized one. Instead, finalize
# stamps an explicit `_finalized` marker; a raw agent card lacks it. Same intent:
# an interrupted wave's raw cards are NOT counted done — they self-heal, not re-extract.
def _is_finalized(card):
    return bool(card.get("_finalized"))


def _card_status(slug, rid):
    """'finalized' | 'raw' | 'quarantined' | None for an article's output card."""
    if (QUAR_DIR / slug / f"{rid}.json").exists():
        return "quarantined"
    pf = PROC_DIR / slug / f"{rid}.json"
    if not pf.exists():
        return None
    try:
        card = json.load(open(pf, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "raw"
    return "finalized" if _is_finalized(card) else "raw"


def _raw_cards():
    """Every card in _processed/ that is NOT yet finalized (interrupted-wave
    leftovers). Returns [(slug, rid), ...]. These need finalize, NOT re-extraction."""
    out = []
    for f in sorted(glob.glob(str(PROC_DIR / "*" / "*.json"))):
        slug = Path(f).parent.name
        rid = Path(f).name[:-5]
        try:
            card = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            out.append((slug, rid)); continue
        if not _is_finalized(card):
            out.append((slug, rid))
    return out


def _global_done_ids():
    """record_ids DONE anywhere: a FINALIZED card under any slug in _processed/, OR
    any card in _quarantine/. record_id is a global url-hash, so one finalized card
    means that article is done regardless of slug."""
    done = set()
    for f in glob.glob(str(PROC_DIR / "*" / "*.json")):
        try:
            card = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if _is_finalized(card):
            done.add(Path(f).name[:-5])
    for f in glob.glob(str(QUAR_DIR / "*" / "*.json")):
        done.add(Path(f).name[:-5])
    return done


def _skip_path():
    return HIST_DIR / "_state" / "extract_skip.json"


def _skip_ids():
    """record_ids an extraction agent explicitly REFUSED (no article content — nav-only
    SPA captures, foreign-lang SEO spam in the sitemap, non-cookie junk). Recorded so
    they don't recycle into every worklist and waste a Sonnet call. Deterministic and
    reversible (just a JSON list); raw files are never deleted."""
    try:
        return set(json.loads(_skip_path().read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def add_skips(rids):
    cur = _skip_ids()
    cur.update(r for r in rids if r)
    _skip_path().parent.mkdir(parents=True, exist_ok=True)
    _skip_path().write_text(json.dumps(sorted(cur), indent=0), encoding="utf-8")
    return len(cur)


def cmd_skip(args):
    rids = [it.rsplit("/", 1)[-1].rsplit(":", 1)[-1].strip() for it in args.items if it.strip()]
    total = add_skips(rids)
    _err(f"skip-list: added {len(rids)}, now {total} record_ids excluded from the worklist")


# --- worklist ---------------------------------------------------------------
def worklist(order="newest", limit=None):
    done = _global_done_ids()
    skip = _skip_ids()
    elig = []
    dropped = {}   # drop-reason -> count (logged to stderr; raw files are NOT deleted)
    for d in _hist_records():
        if not (d.get("text") or "").strip():   # routine: skip records with no text
            continue
        if d.get("record_id") in done:
            continue
        if d.get("record_id") in skip:           # agent-refused junk (recorded skip-list)
            dropped["refused-skip"] = dropped.get("refused-skip", 0) + 1
            continue
        reason = _worklist_drop(d)               # structural / cookie-banner skip (not deleted)
        if reason:
            key = reason.split(":", 1)[0]
            dropped[key] = dropped.get(key, 0) + 1
            continue
        elig.append(d)
    if dropped:
        _err("worklist pre-filter skipped (not deleted): "
             + ", ".join(f"{k}={n}" for k, n in sorted(dropped.items())))
    if order == "oldest":
        elig.sort(key=lambda d: (d.get("published_date") or "", d.get("record_id", "")))
    elif order == "longest":
        elig.sort(key=lambda d: -(d.get("word_count") or 0))
    else:  # newest (default) — most recent first
        elig.sort(key=lambda d: (d.get("published_date") or "", d.get("record_id", "")), reverse=True)
    if limit is not None:
        elig = elig[:limit]
    return elig


def cmd_worklist(args):
    # SELF-HEAL FIRST: finalize raw leftovers from an interrupted wave (cheap;
    # postprocess + guard only, NO re-extraction) so they count as done — THEN list
    # the truly-missing. Heal output is on stderr; only the TSV goes to stdout.
    if not getattr(args, "no_heal", False):
        heal(date=getattr(args, "date", None))
    for d in worklist(order=args.order, limit=args.limit):
        print("\t".join([
            d["_slug"], d.get("record_id", ""),
            str(d.get("word_count") or 0),
            (d.get("source_name") or "")[:28],
            (d.get("title") or "")[:60],
        ]))


# --- prompt (daily rubric, single-sourced from routine_technology.md) ---------
def _rubric():
    """STEP 2 rubric text from routine_technology.md (PROCESS..just before STEP 3),
    with the repo-path DELIVERY subsection stripped (backfill overrides delivery)."""
    try:
        txt = ROUTINE.read_text(encoding="utf-8")
    except OSError:
        return "(routine_technology.md not found — extract per docs/KNOWLEDGE_CARD_SCHEMA.md)"
    m = re.search(r"## STEP 2 .*?(?=\n## STEP 3 )", txt, re.S)
    body = m.group(0) if m else txt
    body = re.sub(r"### DELIVERY.*?(?=\n### VERIFICATION CHECKLIST)", "", body, flags=re.S)
    return body.strip()


def build_prompt(record, slug):
    rid = record.get("record_id") or ""
    meta = {
        "record_id": rid, "source_slug": slug,
        "source_name": record.get("source_name", ""), "source_url": record.get("source_url", ""),
        "title": record.get("title", ""), "published_date": record.get("published_date", ""),
        "language": record.get("language", "en"), "author": record.get("author", ""),
        "word_count": record.get("word_count", 0), "paywalled": bool(record.get("paywalled", False)),
    }
    out_path = PROC_DIR / slug / f"{rid}.json"
    return "\n".join([
        "Extract ONE Technology article into the common KNOWLEDGE card. Follow the rubric",
        f'below EXACTLY. Output ONLY the JSON card (no fences, no prose). Set processor="{PROCESSOR}".',
        "",
        _rubric(),
        "",
        "=== RAW RECORD — extract ONLY from THIS article's text (one-source rule) ===",
        json.dumps(meta, ensure_ascii=False, indent=2),
        "",
        "TEXT:",
        (record.get("text") or ""),
        "",
        "=== DELIVERY (BACKFILL, JSON-ONLY — overrides the routine's processed/technology path) ===",
        f"Write the JSON card to this exact path (create parent dirs):\n  {out_path}",
        "One article -> one file. Leave every quote_verified=false (finalize sets it).",
        "Touch NOTHING else: no other files, no HTML, no dashboard, no git.",
    ])


def cmd_prompt(args):
    # GUARD: emitting a prompt is what lets an extraction agent WRITE to
    # _processed/<slug>/<rid>.json — worklist() already excludes done ids via
    # _global_done_ids(), but `prompt` can be invoked directly (out-of-band, a
    # stale wave list, a manual re-run) and had no check of its own. Without
    # this, a re-extraction would silently overwrite an already-finalized (or
    # already-quarantined) card with a fresh — possibly worse — one, with no
    # trace of what was lost (this script never sees the prior content once
    # the agent's write has already replaced it).
    status = _card_status(args.slug, args.record_id)
    if status in ("finalized", "quarantined") and not getattr(args, "force", False):
        sys.exit(f"REFUSING: technology-history/{'_processed' if status == 'finalized' else '_quarantine'}"
                 f"/{args.slug}/{args.record_id}.json is already {status} — emitting this prompt would let "
                 f"an extraction agent overwrite it with a fresh re-extraction. Pass --force if you "
                 f"specifically intend to re-extract this article.")
    d = _hist_record(args.slug, args.record_id)
    if not d:
        sys.exit(f"history record not found: technology-history/{args.slug}/{args.record_id}.json")
    print(build_prompt(d, args.slug))


# --- finalize ---------------------------------------------------------------
def _parse_items(items):
    out = []
    for it in items:
        it = it.strip()
        if not it:
            continue
        sep = "/" if "/" in it else (":" if ":" in it else None)
        if not sep:
            sys.exit(f"bad item '{it}' — expected slug/record_id")
        slug, rid = it.rsplit(sep, 1)
        out.append((slug.strip(), rid.strip()))
    return out


def _count_insights(card):
    return sum(len(t.get("insights") or []) for t in (card.get("themes") or []))


def _finalize_one(slug, rid):
    """Finalize ONE written card in place: postprocess (quote_verified) then the
    entity-presence guard. Below-threshold cards MOVE to _quarantine/. Kept cards get
    a `_finalized` stamp. No extraction. Returns (status, info)."""
    pf = PROC_DIR / slug / f"{rid}.json"
    if not pf.exists():
        return ("missing", None)
    try:
        card = json.load(open(pf, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ("badjson", None)
    raw = _hist_record(slug, rid) or {}

    # 1) deterministic postprocess (quote_verified + insight_total) — reused as-is.
    quotes, verified = pt.postprocess_record(card, raw)

    # 2) entity-presence guard — reused threshold/function from the daily path.
    frac, n_ent = pt.entity_presence(card, raw)
    if frac < pt.ENTITY_PRESENCE_MIN:
        qf = QUAR_DIR / slug / f"{rid}.json"
        qf.parent.mkdir(parents=True, exist_ok=True)
        json.dump(card, open(qf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.remove(pf)
        return ("quarantined", {"slug": slug, "record_id": rid, "title": card.get("title"),
                                "entity_presence": round(frac, 3), "n_entities": n_ent})
    card["_finalized"] = True
    card["_finalized_at"] = _utc_now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    json.dump(card, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return ("kept", {"slug": slug, "record_id": rid, "title": card.get("title"),
                     "insights": card.get("insight_total") or _count_insights(card),
                     "quotes": quotes, "verified": verified})


def _run_finalize(items, date, label):
    processed, quarantined = [], []
    for slug, rid in items:
        status, info = _finalize_one(slug, rid)
        if status == "missing":
            _err(f"  {label}: {slug}/{rid} — no card in _processed/, skip (agent did not write it?)")
        elif status == "badjson":
            _err(f"  {label}: {slug}/{rid} — card is not valid JSON; leaving in place")
        elif status == "quarantined":
            quarantined.append(info)
            _err(f"  {label}: {slug}/{rid} — ✗ QUARANTINED "
                 f"({int(info['entity_presence']*100)}% of {info['n_entities']} entities) -> _quarantine/")
        else:
            processed.append(info)
            _err(f"  {label}: {slug}/{rid} — ✓ {info['insights']} insights, "
                 f"quotes {info['verified']}/{info['quotes']} verified")
    _write_summary(date, processed, quarantined, label)
    return processed, quarantined


def heal(date=None):
    """SELF-HEAL: finalize any RAW (un-finalized) cards in _processed/ — interrupted-
    wave leftovers. Cheap: postprocess + guard only, NO re-extraction."""
    date = date or _utc_now().strftime("%Y-%m-%d")
    raws = _raw_cards()
    if not raws:
        return 0
    _err(f"self-heal: finalizing {len(raws)} raw card(s) left by an interrupted wave...")
    processed, quarantined = _run_finalize(raws, date, "heal")
    return len(processed) + len(quarantined)


def cmd_heal(args):
    if heal(date=args.date) == 0:
        _err("heal: no raw cards in _processed/ — nothing to finalize. (All cards finalized.)")


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
    pct = (100 * tot_verified // tot_quotes) if tot_quotes else 0
    kind = "self-heal" if label == "heal" else "extraction"

    lines = [f"## Backfill Technology {kind} run — {ts}", ""]
    lines.append(f"- Articles {'healed' if label == 'heal' else 'processed'} (kept): **{len(processed)}**")
    lines.append(f"- Quarantined (entity-presence < {int(pt.ENTITY_PRESENCE_MIN*100)}%): **{len(quarantined)}**")
    lines.append(f"- Total insights: **{tot_insights}**")
    lines.append(f"- Quotes verified / total: **{tot_verified} / {tot_quotes}** ({pct}%)")
    if processed:
        lines += ["", "| slug/record_id | insights | quotes verified/total |", "|---|---|---|"]
        for p in processed:
            lines.append(f"| {p['slug']}/{p['record_id']} | {p['insights']} | {p['verified']}/{p['quotes']} |")
    if quarantined:
        lines += ["", "**Quarantined (NOT kept — review & re-extract from correct article):**"]
        for q in quarantined:
            lines.append(f"- `{q['slug']}/{q['record_id']}` — {q['title']} "
                         f"({int(q['entity_presence']*100)}% of {q['n_entities']} entities present)")
    block = "\n".join(lines) + "\n"
    with open(logf, "a", encoding="utf-8") as fh:
        fh.write(block)
    _err("\n" + "=" * 60)
    _err(block.rstrip())
    _err("=" * 60)
    _err(f"Run summary appended to {logf}")
    _err("(JSON-only: no HTML report, no dashboard rebuild, no git.)")


def main():
    p = argparse.ArgumentParser(description="Historical (backfill) Technology extraction — JSON-only, no publish.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--history-root", default=None,
                        help="override technology-history/ root (default: same as the collector)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("worklist", parents=[common],
                       help="self-heal raw leftovers, then list articles still needing EXTRACTION")
    a.add_argument("--limit", type=int, default=None, help="process at most N this run")
    a.add_argument("--order", choices=["newest", "oldest", "longest"], default="newest")
    a.add_argument("--no-heal", action="store_true", help="pure read-only listing; skip self-heal")
    a.add_argument("--date", default=None)
    a.set_defaults(fn=cmd_worklist)

    a = sub.add_parser("heal", parents=[common],
                       help="finalize any RAW cards already in _processed/ — no re-extraction")
    a.add_argument("--date", default=None)
    a.set_defaults(fn=cmd_heal)

    a = sub.add_parser("prompt", parents=[common], help="emit the extraction prompt for one article")
    a.add_argument("slug")
    a.add_argument("record_id")
    a.add_argument("--force", action="store_true",
                    help="allow emitting a prompt for an already-finalized/quarantined id")
    a.set_defaults(fn=cmd_prompt)

    a = sub.add_parser("skip", parents=[common],
                       help="record agent-refused junk ids so they never recycle into the worklist")
    a.add_argument("items", nargs="+", help="slug/record_id (or bare record_id) tokens the agents refused")
    a.set_defaults(fn=cmd_skip)

    a = sub.add_parser("finalize", parents=[common],
                       help="postprocess + entity guard + run summary (after agents done)")
    a.add_argument("items", nargs="+", help="slug/record_id tokens just extracted")
    a.add_argument("--date", default=None)
    a.set_defaults(fn=cmd_finalize)

    args = p.parse_args()
    if getattr(args, "history_root", None):
        _set_history_root(args.history_root)
    args.fn(args)


if __name__ == "__main__":
    main()
