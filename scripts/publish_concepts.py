#!/usr/bin/env python3
"""Concepts-stream extraction helper + publisher (KNOWLEDGE track).

Clone of scripts/youtube_extract.py, adapted for text articles. Deterministic —
no LLM. The extraction itself (raw article -> KNOWLEDGE card JSON) is done by the
Opus subscription routine in routines/routine_concepts.md, ONE source per
subagent. This script provides the surrounding deterministic machinery:

  worklist [--purge]       list new raw/concepts records with no processed card yet
                           (dedup against processed/concepts/<record_id>.json).
                           Structural junk pre-filter skips (not deletes) known
                           junk shapes; a per-source 100%-junk health check is
                           printed to stderr. --purge additionally runs `purge`
                           (below) in the same pass.
  purge                    deterministic, git-tracked cleanup of the skip-not-
                           delete gap: git rm's (a) orphaned raw/ records the
                           worklist filter would skip, and (b) zero-insight
                           processed/ cards whose underlying record
                           independently matches a junk signal. Never touches
                           a record matching no signal (protects thin-but-real
                           cards). Stages deletions only — does not commit.
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
# collected as if it were an article but is actually one of several junk
# shapes: an archive/listing index page mistaken for a post, a broken
# glyph-soup extraction (a JS canvas/font render captured instead of real
# text), a CAPTCHA/bot-check interstitial, a cookie-consent-preference-center
# capture (a JS widget/chart page where the scraper caught only the cookie
# overlay), or a known non-article site-furniture page (team-bio, careers,
# compliance-policy — named per-source, since these are fixed corporate pages
# that will never become a real Concepts article regardless of word count).
# Without this, a record like that never gets a card (an agent correctly
# refuses it every time) and never gets removed from raw/, so it resurfaces in
# the worklist FOREVER — one bad source can then quietly block a whole day's
# extraction (2026-07-10: 14/14 worklisted aswath_damodaran records were
# 2026-06/07 archive-page leftovers, netting 0 cards; 2026-08-07:
# blackrock_investment_institute's "Stock Quote & Chart" cookie-consent-only
# page slipped through this same filter before the cookie-consent signal
# existed). Skip-not-delete: raw is untouched, only kept out of THIS list.
#
# Deliberately NOT a bare word-count floor — tested against the live corpus
# and rejected: genuinely short-but-complete articles (a 152-word CFR "In
# Memoriam" notice, a 132-word Dimensional podcast-episode page) already have
# real, successfully-extracted cards sitting at 123-160 words, directly
# overlapping the word range real junk (paywall teasers, cookie-gate pages)
# also occupies at this source mix. Any length threshold either fails to catch
# the junk or clips proven-good short content — length alone can't tell them
# apart here. Same reasoning killed a candidate "video-player-widget
# vocabulary" signal for World Economic Forum video pages (2026-08-07): real,
# successfully-extracted WEF video-blurb cards sit at 253-290 words with the
# identical player-chrome boilerplate as a genuine zero-insight WEF video
# stub — the chrome is a fixed page template present on EVERY WEF video page,
# real or thin, so it carries no discriminating signal here. Verified 0 false
# positives for every signal below across all 757 currently-processed,
# non-zero-insight (proven-real) cards.
_GLYPH_RE = re.compile(r"[▀-▟]")   # Unicode block-drawing chars —
# a glyph-soup extraction is near-entirely these; real article text has none.
_GLYPH_DENSITY_MIN = 0.15

_BOT_CHECK_RE = re.compile(
    r"unusual traffic|are you a human|verify you.?re (a person|human)|"
    r"captcha|access denied|please enable javascript and cookies|"
    r"checking your browser", re.I)

# Cookie-consent-only capture: the scraper caught a cookie/consent-preference
# overlay instead of the real page content (a JS-rendered stock-quote/chart
# widget, in the incident that prompted this). Density alone is NOT enough —
# real articles that happen to render a cookie banner alongside genuine prose
# (e.g. IISS product pages, ~3% cookie-word density) sit close to the same
# density as true junk; the reliable structural tell is WHERE the consent
# block starts: real content ALWAYS opens before it in a real page (170-280+
# words of substance first, IISS-verified); pure junk opens WITH it (word 0).
_COOKIE_MARKER_RE = re.compile(
    r"manage your cookies|privacy preference center|cookie notice|"
    r"manage consent preferences|this website uses cookies", re.I)
_COOKIE_WORD_RE = re.compile(r"\bcookies?\b", re.I)
_COOKIE_DENSITY_MIN = 0.02
_COOKIE_PRECEDING_WORDS_MAX = 60   # real content before the marker, in words


def _looks_like_cookie_consent(text):
    if not text:
        return False
    words = text.split()
    if not words:
        return False
    density = len(_COOKIE_WORD_RE.findall(text)) / len(words)
    if density < _COOKIE_DENSITY_MIN:
        return False
    m = _COOKIE_MARKER_RE.search(text)
    if not m:
        return False
    return len(text[:m.start()].split()) <= _COOKIE_PRECEDING_WORDS_MAX


def _looks_like_archive_listing(title, url):
    """The extractor found no real headline, so title fell back to the raw
    URL — the classic symptom of a monthly/yearly archive index page being
    enumerated as if it were an individual post."""
    if not title or not url:
        return False
    return title.strip().rstrip("/") == url.strip().rstrip("/")


# Per-source known non-article site-furniture pages, by URL path fragment —
# same design as the backfill extractor's WORKLIST_DROP_PATHS (theme-agnostic:
# keys off URL shape, not content). These are fixed corporate pages (team
# bios, careers postings, compliance/legal policy documents) that will never
# become a real Concepts insight article no matter how much prose they carry —
# confirmed by reading each one's full text before listing it here. Scoped
# per-source and per-path; extend only after individually verifying a page.
WORKLIST_DROP_PATHS = {
    "blackrock_investment_institute": (
        "/meet-the-bii-team",
        "/our-approach-to-sustainability",
        "/best-execution-and-order-placement-policy",
    ),
    "carnegie_endowment": (
        "/employment-opportunities-at-the-carnegie-endowment",
    ),
    "bridgewater_research": (
        "/phishing-and-fraud-awareness-notice",
        "/sustainable-finance-disclosure-regulation-disclosures",
    ),
}


def _looks_like_known_nonarticle_path(slug, url):
    path = (url or "").lower()
    return any(frag in path for frag in WORKLIST_DROP_PATHS.get(slug, ()))


def _worklist_junk_reason(d):
    """'archive-listing' | 'glyph-soup' | 'bot-check' | 'cookie-consent' |
    'known-path' | None for a raw record about to be offered in the daily
    worklist (or, when re-applied at purge time, for an already-processed
    zero-insight card's own stored title/source_url/text)."""
    text = d.get("text") or ""
    title = d.get("title") or ""
    url = d.get("source_url") or ""
    if _looks_like_archive_listing(title, url):
        return "archive-listing"
    if _looks_like_known_nonarticle_path(d.get("source_slug", ""), url):
        return "known-path"
    if text and (len(_GLYPH_RE.findall(text)) / len(text)) > _GLYPH_DENSITY_MIN:
        return "glyph-soup"
    if _BOT_CHECK_RE.search(text[:500]):
        return "bot-check"
    if _looks_like_cookie_consent(text):
        return "cookie-consent"
    return None


# --- worklist ---------------------------------------------------------------
def cmd_worklist(args):
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

    if getattr(args, "purge", False):
        cmd_purge(args)

    if not rows:
        print("No new Concepts articles to extract.")
        return
    print(f"{len(rows)} new article(s) to extract:")
    for rid, slug, title, f in rows:
        print(f"  {rid}  [{slug}]  {title[:70]}")
        print(f"      {Path(f).relative_to(REPO)}")


# --- purge (the skip-not-delete gap) -----------------------------------------
def _zero_insight_processed():
    """(rid, card, path) for every processed/concepts card with 0 insights —
    the class of record that got fully extracted (a card exists) but the
    agent correctly found nothing: same underlying junk shapes the worklist
    filter now catches BEFORE extraction, just not purged after the fact."""
    out = []
    for f in glob.glob(str(PROC_DIR / "*.json")):
        if Path(f).name.startswith("_"):
            continue
        try:
            card = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        n = sum(len(t.get("insights") or []) for t in (card.get("themes") or []))
        if n == 0:
            out.append((Path(f).stem, card, f))
    return out


def cmd_purge(_args):
    """Deterministically remove on-disk orphaned junk, using the EXACT SAME
    structural signals as the worklist filter (_worklist_junk_reason) — never
    a bespoke purge-only rule. Two targets:

      1. raw/concepts/ records not yet processed that the filter would skip —
         these sit forever under skip-not-delete with no other way off disk.
      2. processed/concepts/ zero-insight cards whose underlying record
         independently matches a junk signal — confirmed junk that already
         got carded before this filter existed, not merely thin-but-real
         content (a card is checked against its own raw record when the raw
         file still exists, or its own stored title/source_url when raw was
         already removed by an earlier manual purge — sufficient for the
         URL-shape signals: archive-listing, known-path).

    A zero-insight card that matches NO signal is left untouched and reported
    separately — e.g. a genuine thin-but-real article the extractor
    under-called is not junk and must never be purged just for being short.

    git rm, never a bare unlink: every deletion is staged, reversible, and
    shows up in `git status` for the normal commit flow to pick up (this
    script never commits on its own)."""
    done = _processed_ids()
    raw_targets = []
    for f in _raw_files():
        rid = Path(f).stem
        if rid in done:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        reason = _worklist_junk_reason(d)
        if reason:
            raw_targets.append((d.get("source_slug", ""), rid, reason, f))

    processed_targets, protected = [], []
    for rid, card, pf in _zero_insight_processed():
        raw = _raw_by_id(rid)
        probe = raw if raw is not None else {
            "title": card.get("title"), "source_url": card.get("source_url"),
            "source_slug": "", "text": "",
        }
        reason = _worklist_junk_reason(probe)
        slug = (raw or {}).get("source_slug") or card.get("source_name", "")
        if reason:
            processed_targets.append((slug, rid, reason, pf))
        else:
            protected.append((slug, rid, card.get("title", "")[:60]))

    targets = raw_targets + processed_targets
    if not targets:
        print("purge: nothing on disk matches a structural junk signal.")
    else:
        print(f"\npurge: removing {len(targets)} confirmed-junk record(s) via git rm "
              f"({len(raw_targets)} raw, {len(processed_targets)} processed):")
        for slug, rid, reason, path in sorted(targets):
            kind = "raw" if (slug, rid, reason, path) in raw_targets else "processed"
            print(f"  [{kind}:{reason}] {slug}/{rid}  {Path(path).relative_to(REPO)}")
        subprocess.run(["git", "rm", "-q", "--"] + [t[3] for t in targets],
                        check=True, cwd=REPO)
        print("  -> staged for deletion (git status), not committed here.")

    if protected:
        print(f"\npurge: {len(protected)} zero-insight card(s) matched NO junk "
              f"signal — left in place (thin-but-real, not junk):")
        for slug, rid, title in sorted(protected):
            print(f"  [kept] {slug}/{rid}  {title}")


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
    a = sub.add_parser("worklist")
    a.add_argument("--purge", action="store_true",
                    help="also purge on-disk junk matching a structural signal "
                         "(orphaned raw records + zero-insight processed cards)")
    a.set_defaults(fn=cmd_worklist)
    sub.add_parser("purge").set_defaults(fn=cmd_purge)
    a = sub.add_parser("postprocess"); a.add_argument("ids", nargs="+"); a.set_defaults(fn=cmd_postprocess)
    a = sub.add_parser("publish")
    a.add_argument("--date", default=None)
    a.add_argument("--ids", default=None)
    a.set_defaults(fn=cmd_publish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
