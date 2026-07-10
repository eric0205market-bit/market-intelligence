#!/usr/bin/env python3
"""Concepts-stream extraction helper + publisher (KNOWLEDGE track).

Clone of scripts/youtube_extract.py, adapted for text articles. Deterministic —
no LLM. The extraction itself (raw article -> KNOWLEDGE card JSON) is done by the
Opus subscription routine in routines/routine_concepts.md, ONE source per
subagent. This script provides the surrounding deterministic machinery:

  worklist                 list new raw/concepts records with no processed card yet
                           (dedup against processed/concepts/<record_id>.json)
  postprocess <id...>      set quote_verified on each insight (quote present in
                           the raw article text). Concepts has no timestamps.
  publish [--date] [--ids] entity-presence guard -> quarantine topic-mismatch
                           cards (NOT deleted), render NEW-ONLY
                           reports/concepts_<date>.html, rebuild the dashboard.

Card contract: docs/KNOWLEDGE_CARD_SCHEMA.md (v1). source_type="concepts".

Raw layout : raw/concepts/<source_slug>/<record_id>.json   (collector output)
Processed   : processed/concepts/<record_id>.json           (one card per source)
Report      : reports/concepts_<YYYY-MM-DD>.html            (NEW-ONLY, this run)
Quarantine  : processed/concepts/_quarantine.json           (non-destructive)

The routine commits + pushes after publish (same as the YouTube routine); this
script only renders + rebuilds the dashboard, exactly like youtube_extract.py
publish delegates git to the routine.
"""
import datetime
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO / "raw" / "concepts"
PROC_DIR = REPO / "processed" / "concepts"
TEMPLATE = REPO / "templates" / "concepts_report.html"
REPORTS_DIR = REPO / "reports"
QUARANTINE_LOG = PROC_DIR / "_quarantine.json"


def _norm(s):
    """Lowercase + collapse non-alphanumerics to single spaces (match-friendly)."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


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


# --- worklist junk pre-filter ------------------------------------------------
# STRUCTURAL (theme-agnostic) signal only — catches a raw record that was
# collected as if it were an article but is actually one of three junk shapes:
# an archive/listing index page mistaken for a post, a broken glyph-soup
# extraction (a JS canvas/font render captured instead of real text), or a
# CAPTCHA/bot-check interstitial. Without this, a record like that never gets a
# card (an agent correctly refuses it every time) and never gets removed from
# raw/, so it resurfaces in the worklist FOREVER — one bad source can then
# quietly block a whole day's extraction (2026-07-10: 14/14 worklisted
# aswath_damodaran records were 2026-06/07 archive-page leftovers, netting 0
# cards). Skip-not-delete: raw is untouched, only kept out of THIS list.
#
# Deliberately NOT a bare word-count floor — tested against the live corpus
# and rejected: genuinely short-but-complete articles (a 152-word CFR "In
# Memoriam" notice, a 132-word Dimensional podcast-episode page) already have
# real, successfully-extracted cards sitting at 123-160 words, directly
# overlapping the word range real junk (paywall teasers, cookie-gate pages)
# also occupies at this source mix. Any length threshold either fails to catch
# the junk or clips proven-good short content — length alone can't tell them
# apart here. Verified 0 false positives for the three signals below across
# all 509 currently-processed (proven-real) cards.
_GLYPH_RE = re.compile(r"[▀-▟]")   # Unicode block-drawing chars —
# a glyph-soup extraction is near-entirely these; real article text has none.
_GLYPH_DENSITY_MIN = 0.15

_BOT_CHECK_RE = re.compile(
    r"unusual traffic|are you a human|verify you.?re (a person|human)|"
    r"captcha|access denied|please enable javascript and cookies|"
    r"checking your browser", re.I)


def _looks_like_archive_listing(title, url):
    """The extractor found no real headline, so title fell back to the raw
    URL — the classic symptom of a monthly/yearly archive index page being
    enumerated as if it were an individual post."""
    if not title or not url:
        return False
    return title.strip().rstrip("/") == url.strip().rstrip("/")


def _worklist_junk_reason(d):
    """'archive-listing' | 'glyph-soup' | 'bot-check' | None for a raw record
    about to be offered in the daily worklist."""
    text = d.get("text") or ""
    if _looks_like_archive_listing(d.get("title") or "", d.get("source_url") or ""):
        return "archive-listing"
    if text and (len(_GLYPH_RE.findall(text)) / len(text)) > _GLYPH_DENSITY_MIN:
        return "glyph-soup"
    if _BOT_CHECK_RE.search(text[:500]):
        return "bot-check"
    return None


# --- worklist ---------------------------------------------------------------
def cmd_worklist(_args):
    done = _processed_ids()
    rows = []
    dropped = {}                       # junk reason -> count
    per_source = {}                    # slug -> {"kept": n, "junk": n}
    for f in _raw_files():
        rid = Path(f).stem
        if rid in done:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        slug = d.get("source_slug", "")
        bucket = per_source.setdefault(slug, {"kept": 0, "junk": 0})
        reason = _worklist_junk_reason(d)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            bucket["junk"] += 1
            print(f"  JUNK_SKIPPED [{reason}] {slug}/{rid}: "
                  f"{(d.get('title') or '')[:70]}", file=sys.stderr)
            continue
        bucket["kept"] += 1
        rows.append((rid, slug, d.get("title", ""), f))

    # HEALTH CHECK: a source whose worklist contribution THIS RUN is 100% junk
    # (>=1 record seen, 0 kept) is exactly the failure mode that let Damodaran
    # block the routine silently for 3 weeks — call it out distinctly so it's
    # visible even when the run's overall headline is "no new articles" (a
    # mixed-junk source with at least one real article is not flagged; that's
    # normal noise, not a stuck source).
    all_junk_sources = {slug: b["junk"] for slug, b in per_source.items()
                        if b["kept"] == 0 and b["junk"] > 0}
    if all_junk_sources:
        print("\n⚠ SOURCE(S) PRODUCING ONLY JUNK this run (0 kept, all skipped) — "
              "likely a broken listing/collection method, not a one-off:", file=sys.stderr)
        for slug, n in sorted(all_junk_sources.items(), key=lambda kv: -kv[1]):
            print(f"    {slug}: {n} junk record(s), 0 real", file=sys.stderr)

    if dropped:
        print("\nworklist pre-filter skipped (not deleted): "
              + ", ".join(f"{k}={n}" for k, n in sorted(dropped.items())), file=sys.stderr)
    if not rows:
        print("No new Concepts articles to extract.")
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
    quotes = verified = total = 0
    for theme in (card.get("themes") or []):
        for ins in (theme.get("insights") or []):
            if not isinstance(ins, dict):
                continue
            total += 1
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


def _write_quarantine_log(new_entries):
    """Merge new_entries into QUARANTINE_LOG instead of replacing it wholesale —
    same class of bug as the report-overwrite fix in _render(): the log is a
    single running list with NO date scoping, so a plain write_text() on every
    publish call that quarantines anything wipes out every earlier run's
    entries, same-day or any prior day. Union by record_id (new_entries wins on
    overlap, e.g. a re-check after a source fix); same shrink-guard tripwire as
    _render() — refuse to write rather than silently lose entries."""
    existing = []
    if QUARANTINE_LOG.exists():
        try:
            existing = json.loads(QUARANTINE_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"  WARN: could not parse existing {QUARANTINE_LOG.name} — "
                  f"treating as empty (this run's entries will still be written)")
            existing = []

    merged = {e["record_id"]: e for e in existing if e.get("record_id")}
    existing_ids = set(merged)
    merged.update({e["record_id"]: e for e in new_entries if e.get("record_id")})
    merged_list = list(merged.values())

    if len(merged_list) < len(existing):
        sys.exit(f"FATAL: merge would SHRINK {QUARANTINE_LOG.name} from "
                 f"{len(existing)} to {len(merged_list)} entries — refusing to "
                 f"write. This should be mathematically impossible for a union "
                 f"merge; something is wrong upstream (investigate before "
                 f"re-running).")
    if existing:
        added = sum(1 for e in new_entries
                   if e.get("record_id") and e["record_id"] not in existing_ids)
        print(f"  merging into existing quarantine log: {len(existing)} entry(ies) "
              f"on disk + {len(new_entries)} this run -> {len(merged_list)} total "
              f"({added} new, {len(new_entries) - added} already present)")

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
    """Cards currently embedded in reports/concepts_<date>.html, if that file
    already exists (e.g. from an earlier run today). [] if missing/unparseable.

    Uses JSONDecoder.raw_decode from the `const REPORT_DATA = ` marker instead
    of a regex match ending at the first `);` — a naive regex would truncate
    early if any card's text happens to contain that two-character sequence."""
    out_path = REPORTS_DIR / f"concepts_{date}.html"
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


def _render(cards, date):
    """Write reports/concepts_<date>.html from `cards`, MERGING with whatever
    is already there instead of replacing it — a second same-day run (e.g. two
    routine passes on 2026-06-25) must not silently drop the first run's cards.
    Merge is a union keyed by record_id; `cards` (this run's freshly-loaded,
    guard-passed set) wins on overlap. NEW-ONLY-across-days semantics are
    preserved automatically: a card only ever gets merged into the report for
    the date `_render` was called with, driven by that record's own
    processed_at / the caller's explicit --ids for that day — dates are never
    cross-mixed here.

    GUARD: the merged card count can only ever grow or stay flat (it is a
    union). If it were ever observed to shrink, that would mean the merge
    logic itself broke — hard-stop rather than silently write a corrupted
    report."""
    if not TEMPLATE.exists():
        sys.exit(f"template not found: {TEMPLATE}")

    existing = _existing_report_cards(date)
    merged = {c["record_id"]: c for c in existing if c.get("record_id")}
    added = sum(1 for c in cards if c.get("record_id") not in merged)
    merged.update({c["record_id"]: c for c in cards if c.get("record_id")})
    merged_cards = list(merged.values())

    if len(merged_cards) < len(existing):
        sys.exit(f"FATAL: merge would SHRINK reports/concepts_{date}.html from "
                 f"{len(existing)} to {len(merged_cards)} card(s) — refusing to "
                 f"write. This should be mathematically impossible for a union "
                 f"merge; something is wrong upstream (investigate before "
                 f"re-running).")
    if existing:
        print(f"  merging into existing report: {len(existing)} card(s) on disk "
              f"+ {len(cards)} card(s) this run -> {len(merged_cards)} total "
              f"({added} new, {len(cards) - added} already present)")

    payload = json.dumps(_build_payload(merged_cards, date), ensure_ascii=False)
    html = TEMPLATE.read_text(encoding="utf-8").replace("__REPORT_DATA__", payload)
    if "__REPORT_DATA__" in html:
        sys.exit("ERROR: placeholder __REPORT_DATA__ still present after substitution")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"concepts_{date}.html"
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
        _write_quarantine_log(quarantined)
        print(f"    -> logged to {QUARANTINE_LOG.relative_to(REPO)}. Re-extract these from "
              f"their raw article, then re-publish. (Processed files left in place.)\n")

    # --- render NEW-ONLY report (guard-filtered) + rebuild dashboard ---
    _render(ok_cards, date)
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
    a.set_defaults(fn=cmd_publish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
