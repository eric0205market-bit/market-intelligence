#!/usr/bin/env python3
"""Technology-stream extraction helper + publisher (KNOWLEDGE track).

Clone of scripts/publish_concepts.py. Deterministic — no LLM. The extraction
itself (raw article -> KNOWLEDGE card JSON) is done by the Opus subscription
routine in routines/routine_technology.md, ONE source per subagent. This script
provides the surrounding deterministic machinery:

  worklist                 list new raw/technology records with no processed card
                           yet (dedup against processed/technology/<record_id>.json)
  postprocess <id...>      set quote_verified on each insight (quote present in
                           the raw article text). Technology has no timestamps.
  publish [--date] [--ids] entity-presence guard -> quarantine topic-mismatch
                           cards (NOT deleted), render NEW-ONLY
                           reports/technology_<date>.html, rebuild the dashboard.

Card contract: docs/KNOWLEDGE_CARD_SCHEMA.md (v1). source_type="technology".

Raw layout : raw/technology/<source_slug>/<record_id>.json   (collector output)
Processed   : processed/technology/<record_id>.json           (one card per source)
Report      : reports/technology_<YYYY-MM-DD>.html            (NEW-ONLY, this run)
Quarantine  : processed/technology/_quarantine.json           (non-destructive)

The routine commits + pushes after publish (same as the YouTube routine); this
script only renders + rebuilds the dashboard.
"""
import datetime
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO / "raw" / "technology"
PROC_DIR = REPO / "processed" / "technology"
TEMPLATE = REPO / "templates" / "technology_report.html"
REPORTS_DIR = REPO / "reports"
QUARANTINE_LOG = PROC_DIR / "_quarantine.json"


def _norm(s):
    """Lowercase + collapse non-alphanumerics to single spaces (match-friendly)."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# --- author / speaker cleanup (deterministic, no LLM) ------------------------
# Shared KNOWLEDGE-track polish: CMS bylines often leak a bare @handle, a URL, a
# login/path, or an empty string instead of a human/org name. Clean those to a
# real name, falling back to the source's own name. Generic on purpose so the
# Society stream (which clones this) inherits it unchanged.
_AUTHOR_JUNK_RE = re.compile(r"https?://|www\.|@|[\\/]|\.com\b|\.org\b|\blogin\b|\bsign[\s-]?in\b", re.I)
# Trailing words that make a source NAME read as a feed rather than an org/person.
_SRC_SUFFIX_RE = re.compile(r"\s*(?:\bblog\b|\bnews\b|\(free content\)|\(top stories\)|\barchived\b)\s*$", re.I)


def _source_person(source_name):
    """Source name reduced to an org-ish label for use as a byline fallback
    (strip trailing 'Blog'/'News'/'(free content)' etc.)."""
    name = (source_name or "").strip()
    cleaned = _SRC_SUFFIX_RE.sub("", name).strip()
    return cleaned or name


def _is_byline_junk(value):
    """True if a byline value is not a usable human/org name: empty, a bare
    @handle/URL/path/login, or a single all-lowercase token (handle-like)."""
    v = (value or "").strip().lstrip("@").strip()
    if not v:
        return True
    if _AUTHOR_JUNK_RE.search(v):
        return True
    # A lone all-lowercase token with no space reads as a handle, not a name
    # ("cohere", "benchmarkmin"); a capitalised single name ("Lysandre") is kept.
    if " " not in v and v == v.lower():
        return True
    return False


def clean_author(author, source_name):
    """Return a clean byline: strip a leading '@'; if the value is junk (handle/
    URL/login/empty), fall back to the source name. Never returns junk."""
    if _is_byline_junk(author):
        return _source_person(source_name)
    return (author or "").strip().lstrip("@").strip()


def clean_speaker(speaker, cleaned_author, source_name):
    """Clean an insight speaker the same way; when junk, prefer the already-cleaned
    author, else the source name."""
    if _is_byline_junk(speaker):
        return cleaned_author or _source_person(source_name)
    return (speaker or "").strip().lstrip("@").strip()


# --- raw / processed indexing ----------------------------------------------
def _raw_files():
    """All collector records, skipping _-prefixed run-artifact dirs (_runs)."""
    out = []
    if not RAW_ROOT.exists():
        return out
    for src_dir in sorted(RAW_ROOT.iterdir()):
        if not src_dir.is_dir() or src_dir.name.startswith("_"):
            continue
        out.extend(sorted(glob.glob(str(src_dir / "*.json"))))
    return out


def _raw_by_id(record_id):
    """Load a single raw record by its record_id (== filename stem), or None."""
    for f in _raw_files():
        if Path(f).stem == record_id:
            try:
                return json.load(open(f, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _processed_ids():
    ids = set()
    if not PROC_DIR.exists():
        return ids
    for f in glob.glob(str(PROC_DIR / "*.json")):
        if Path(f).name.startswith("_"):   # skip _quarantine.json
            continue
        ids.add(Path(f).stem)
    return ids


# --- worklist ---------------------------------------------------------------
def cmd_worklist(_args):
    done = _processed_ids()
    rows = []
    for f in _raw_files():
        rid = Path(f).stem
        if rid in done:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows.append((rid, d.get("source_slug", ""), d.get("title", ""), f))
    if not rows:
        print("No new Technology articles to extract.")
        return
    print(f"{len(rows)} new article(s) to extract:")
    for rid, slug, title, f in rows:
        print(f"  {rid}  [{slug}]  {title[:70]}")
        print(f"      {Path(f).relative_to(REPO)}")


# --- quote verification (postprocess) ---------------------------------------
def _quote_present(quote, body_norm):
    """True if a quote is faithfully present in the normalized raw text.
    Tolerates caption-style artifacts by also accepting a long core fragment."""
    qn = _norm(quote)
    if not qn:
        return False
    if qn in body_norm:
        return True
    # Fallback: accept if a long contiguous core (first/last ~40 norm-chars) hits.
    if len(qn) >= 50:
        if qn[:40] in body_norm or qn[-40:] in body_norm:
            return True
    return False


def postprocess_record(card, raw):
    """Set quote_verified on every insight + recompute insight_total to match the
    actual insight count (schema §1: insight_total = total across all themes — the
    LLM's self-count can drift by one). Returns (quotes, verified)."""
    body = _norm((raw or {}).get("text"))
    # --- byline cleanup: scrub @handle/URL/login junk from author + speakers ---
    source_name = card.get("source_name", "")
    sm = card.get("source_meta")
    if isinstance(sm, dict):
        sm["author"] = clean_author(sm.get("author"), source_name)
        author_clean = sm["author"]
    else:
        author_clean = clean_author(card.get("author"), source_name)
    quotes = verified = total = 0
    for theme in (card.get("themes") or []):
        for ins in (theme.get("insights") or []):
            if not isinstance(ins, dict):
                continue
            total += 1
            ins["speaker"] = clean_speaker(ins.get("speaker"), author_clean, source_name)
            if ins.get("quote"):
                quotes += 1
                ok = bool(body) and _quote_present(ins["quote"], body)
                ins["quote_verified"] = ok
                if ok:
                    verified += 1
            else:
                ins.setdefault("quote_verified", False)
    card["insight_total"] = total
    return quotes, verified


def cmd_postprocess(args):
    total = verified = 0
    for rid in args.ids:
        pf = PROC_DIR / f"{rid}.json"
        if not pf.exists():
            print(f"  postprocess: {rid} — no processed file, skip")
            continue
        card = json.load(open(pf, encoding="utf-8"))
        q, v = postprocess_record(card, _raw_by_id(rid) or {})
        total += q
        verified += v
        json.dump(card, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  postprocess: {rid} — quotes {v}/{q} verified")
    print(f"postprocess totals: quotes={total} verified={verified}")


def _write_quarantine_log(new_entries, date, force=False):
    """Merge new_entries into QUARANTINE_LOG instead of replacing it wholesale —
    a plain write_text() on every publish call that quarantines anything wiped
    out every earlier run's entries (same-day or any prior day; the log has no
    date scoping of its own). Union by record_id (new_entries wins on overlap,
    e.g. a re-check after a source fix); each entry gets a `date` field stamped
    with the run's --date so history is legible even though the file itself
    isn't split per-date. Called unconditionally (even with new_entries == [])
    so a merge/write always happens rather than being gated on `if quarantined`
    — that gate was incidental to the bug, not the cause, but removing it means
    every publish call re-affirms the existing log is intact.

    SHRINK-GUARD: refuses to write (FATAL) if the merged count is smaller than
    what's already on disk, unless force=True (--force/--rebuild) — a union
    can only grow or stay flat, so a shrink means something is wrong upstream."""
    existing = []
    if QUARANTINE_LOG.exists():
        try:
            existing = json.loads(QUARANTINE_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"  WARN: could not parse existing {QUARANTINE_LOG.name} — "
                  f"treating as empty (this run's entries will still be written)")
            existing = []

    dated_new = [{**e, "date": e.get("date") or date} for e in new_entries]
    merged = {e["record_id"]: e for e in existing if e.get("record_id")}
    existing_ids = set(merged)
    merged.update({e["record_id"]: e for e in dated_new if e.get("record_id")})
    merged_list = list(merged.values())

    if len(merged_list) < len(existing) and not force:
        sys.exit(f"FATAL: merge would SHRINK {QUARANTINE_LOG.name} from "
                 f"{len(existing)} to {len(merged_list)} entries — refusing to "
                 f"write. This should be mathematically impossible for a union "
                 f"merge; something is wrong upstream (investigate before "
                 f"re-running, or pass --force to write anyway).")
    if existing:
        added = sum(1 for e in dated_new
                   if e.get("record_id") and e["record_id"] not in existing_ids)
        print(f"  merging into existing quarantine log: {len(existing)} entry(ies) "
              f"on disk + {len(dated_new)} this run -> {len(merged_list)} total "
              f"({added} new, {len(dated_new) - added} already present)")

    QUARANTINE_LOG.write_text(json.dumps(merged_list, ensure_ascii=False, indent=2),
                              encoding="utf-8")


# --- entity-presence guard ---------------------------------------------------
ENTITY_PRESENCE_MIN = 0.40   # a card whose top_entities are <40% present in its
                             # raw article text is a topic mismatch (hallucinated
                             # / cross-contaminated extraction) and is quarantined.
ENTITY_CHECK_MIN_N = 4       # only judge cards with >=4 entities (small lists noisy)


def entity_presence(card, raw):
    """Fraction of a card's top_entities that appear in its raw article text.
    Returns (fraction, n_entities). Real cards sit well above 0.40."""
    body = _norm((raw or {}).get("text"))
    ents = [e for e in (card.get("top_entities") or []) if e]
    if not body or len(ents) < ENTITY_CHECK_MIN_N:
        return 1.0, len(ents)            # can't judge -> pass through
    def present(e):
        ws = [w for w in _norm(e).split() if len(w) > 3]
        return any(w in body for w in ws) if ws else (_norm(e) in body)
    hit = sum(1 for e in ents if present(e))
    return hit / len(ents), len(ents)


# --- render (NEW-ONLY) -------------------------------------------------------
def _build_payload(cards, date, lookback_days=None):
    insights = sum(
        len(t.get("insights") or []) for c in cards for t in (c.get("themes") or [])
    )
    quotes = verified = 0
    for c in cards:
        for t in (c.get("themes") or []):
            for ins in (t.get("insights") or []):
                if ins.get("quote"):
                    quotes += 1
                    if ins.get("quote_verified"):
                        verified += 1
    sources = len({c.get("source_name") for c in cards if c.get("source_name")})
    stats = {
        "cards": len(cards),
        "insights": insights,
        "sources": sources,
        "quote_verified_pct": (round(100 * verified / quotes) if quotes else None),
    }
    if lookback_days is not None:
        stats["lookback_days"] = lookback_days
    return {
        "date": date,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                                  .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "stats": stats,
        "cards": cards,
    }


def _existing_report_cards(date):
    """Cards currently embedded in reports/technology_<date>.html, if that file
    already exists (e.g. from an earlier run today). [] if missing/unparseable.

    Uses JSONDecoder.raw_decode from the `const REPORT_DATA = ` marker instead
    of a regex match ending at the first `);` — a naive regex would truncate
    early if any card's text happens to contain that two-character sequence."""
    out_path = REPORTS_DIR / f"technology_{date}.html"
    if not out_path.exists():
        return []
    html = out_path.read_text(encoding="utf-8")
    marker = "const REPORT_DATA = "
    i = html.find(marker)
    if i == -1:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(html, i + len(marker))
    except json.JSONDecodeError:
        print(f"  WARN: could not parse existing REPORT_DATA in {out_path.name} "
              f"— treating as empty (a fresh render will still include every "
              f"card passed to this run, nothing already-processed is lost)")
        return []
    return data.get("cards", []) or []


def _render(cards, date, force=False):
    """Write reports/technology_<date>.html from `cards`, MERGING with whatever
    is already there instead of replacing it — a second same-day (or later,
    partial-batch) run must not silently drop an earlier run's cards. Merge is
    a union keyed by record_id; `cards` (this run's freshly-loaded, guard-passed
    set) wins on overlap. NEW-ONLY-across-days semantics are preserved
    automatically: a card only ever gets merged into the report for the date
    `_render` was called with — dates are never cross-mixed here.

    SHRINK-GUARD: the merged card count can only ever grow or stay flat (it is
    a union). If it were ever observed to shrink, that would mean the merge
    logic itself broke — hard-stop rather than silently write a corrupted
    report, unless force=True (--force/--rebuild) explicitly overrides it."""
    if not TEMPLATE.exists():
        sys.exit(f"template not found: {TEMPLATE}")

    existing = _existing_report_cards(date)
    merged = {c["record_id"]: c for c in existing if c.get("record_id")}
    added = sum(1 for c in cards if c.get("record_id") not in merged)
    merged.update({c["record_id"]: c for c in cards if c.get("record_id")})
    merged_cards = list(merged.values())

    if len(merged_cards) < len(existing) and not force:
        sys.exit(f"FATAL: merge would SHRINK reports/technology_{date}.html from "
                 f"{len(existing)} to {len(merged_cards)} card(s) — refusing to "
                 f"write. This should be mathematically impossible for a union "
                 f"merge; something is wrong upstream (investigate before "
                 f"re-running, or pass --force to write anyway).")
    if existing:
        print(f"  merging into existing report: {len(existing)} card(s) on disk "
              f"+ {len(cards)} card(s) this run -> {len(merged_cards)} total "
              f"({added} new, {len(cards) - added} already present)")

    payload = json.dumps(_build_payload(merged_cards, date), ensure_ascii=False)
    html = TEMPLATE.read_text(encoding="utf-8").replace("__REPORT_DATA__", payload)
    if "__REPORT_DATA__" in html:
        sys.exit("ERROR: placeholder __REPORT_DATA__ still present after substitution")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"technology_{date}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path.relative_to(REPO)} "
          f"({len(html):,} bytes, {len(merged_cards)} card(s))")


def cmd_publish(args):
    date = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # Candidate ids: explicit --ids, else everything processed on `date`.
    if args.ids:
        cand = [x.strip() for x in args.ids.split(",") if x.strip()]
    else:
        cand = []
        for f in sorted(glob.glob(str(PROC_DIR / "*.json"))):
            if Path(f).name.startswith("_"):
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if (d.get("processed_at") or "")[:10] == date:
                cand.append(Path(f).stem)

    # --- ENTITY-PRESENCE GUARD: quarantine topic-mismatch cards, never publish them ---
    ok_cards, quarantined = [], []
    for rid in cand:
        pf = PROC_DIR / f"{rid}.json"
        if not pf.exists():
            continue
        try:
            card = json.load(open(pf, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        frac, n = entity_presence(card, _raw_by_id(rid))
        if frac < ENTITY_PRESENCE_MIN:
            quarantined.append({"record_id": rid, "title": card.get("title"),
                                "source_name": card.get("source_name"),
                                "entity_presence": round(frac, 3), "n_entities": n})
        else:
            ok_cards.append(card)

    if quarantined:
        print("\n⚠ QUARANTINED (entity presence < %d%% — NOT published, kept for your review):"
              % int(ENTITY_PRESENCE_MIN * 100))
        for q in quarantined:
            print(f"    ✗ [{q['record_id']}] {q['source_name']} — {q['title']}  "
                  f"({int(q['entity_presence']*100)}% of {q['n_entities']} entities present)")
    # Called unconditionally (not gated on `if quarantined:`) — see
    # _write_quarantine_log's docstring for why.
    _write_quarantine_log(quarantined, date, force=args.force)
    if quarantined:
        print(f"    -> logged to {QUARANTINE_LOG.relative_to(REPO)}. Re-extract these from "
              f"their raw article, then re-publish. (Processed files left in place.)\n")

    # --- render NEW-ONLY report (guard-filtered) + rebuild dashboard ---
    _render(ok_cards, date, force=args.force)
    subprocess.run([sys.executable, str(REPO / "scripts" / "update_dashboard.py")], check=True)
    bb = REPO / "scripts" / "inject_back_button.py"
    if bb.exists():
        subprocess.run([sys.executable, str(bb)], check=True)
    print(f"published {len(ok_cards)} card(s); "
          f"{len(quarantined)} quarantined; date {date}")


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("worklist").set_defaults(fn=cmd_worklist)
    a = sub.add_parser("postprocess"); a.add_argument("ids", nargs="+"); a.set_defaults(fn=cmd_postprocess)
    a = sub.add_parser("publish")
    a.add_argument("--date", default=None)
    a.add_argument("--ids", default=None)
    a.add_argument("--force", "--rebuild", dest="force", action="store_true",
                   help="allow the report/quarantine merge to shrink an existing "
                        "file's record count instead of refusing to write "
                        "(only needed for a deliberate rebuild that legitimately "
                        "removes records, e.g. a retraction)")
    a.set_defaults(fn=cmd_publish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
