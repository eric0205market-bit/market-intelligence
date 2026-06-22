#!/usr/bin/env python3
"""Concepts historical-backfill collector (RAW ONLY — no extraction, no publish).

COMPLETELY SEPARATE from the daily pipeline (scripts/collect_concepts.py).
- Manual trigger only; NEVER run by GitHub Actions or any cron.
- Writes to a history root OUTSIDE the git repo (never committed), mirroring the
  YouTube backfill convention (~/.../market-intelligence/youtube-history/) but
  under a Concepts root:
      ~/Dropbox (Personal)/Business/InvestTool/market-intelligence/concepts-history/
        {source_slug}/{record_id}.json   — daily raw shape + "backfill": true
        _state/backfill_state.json
        _runlog/{timestamp}.md
  (Override with $CONCEPTS_HISTORY_ROOT.)

WHAT IT DOES (this step = RAW ONLY)
  For each signal source, ENUMERATE article URLs back to --start (default
  2025-01-01) via a SITEMAP-FIRST method (pagination is JS-walled — confirmed by
  probe), then FETCH each article's raw text + date — reusing the daily
  collector's per-article fetch (extract_article) + layered extract_date. NO
  card extraction, NO HTML, NO dashboard, NO git.

DEDUP — against BOTH:
  - the DAILY corpus on main:  repo raw/concepts/*/<id>.json  AND
                               repo processed/concepts/<id>.json
  - the history folder:        concepts-history/<slug>/<id>.json
  record_id = same url-hash the daily collector uses, so a URL already collected
  daily (or already backfilled) is never re-fetched.

ENUMERATION METHODS (3 signal source-types)
  flat_html   Paul Graham — articles.html lists every essay (page order = newest
              first); single-slug <word>.html detector.
  wp_sitemap  a16z — sitemap_index.xml -> post-sitemap*.xml, keep lastmod >= start.
  js_listing  Howard Marks / Oaktree memos — no sitemap; render the memos listing
              with Playwright (scroll) and harvest /insights/memo links.

THROTTLE (polite, sequential; web scraping, not an API)
  - Sequential only, no concurrency.
  - 4-10 s random sleep after every article fetch.
  - 20-60 s pause between sources.
  - Per-source fetch cap (--per-source-cap) + overall session cap (--session-cap).
HARD STOP (save state, exit 10) on 429 / bot-check / consent signals or 3
  consecutive fetch failures. Do NOT retry in a loop.

KNOWN LIMITATIONS (the runner only fetches SIGNAL_TIER_ORDER, which avoids these):
  - Generic-sitemap enumeration follows up to 40 index sub-maps: enough to reach
    recent posts on small paginated blog sitemaps, but it OVER-counts a few very
    large corporate sitemaps (e.g. capital_economics) — those are Stage-3, not in
    the runner. Counts are informational; the fetch step date-filters every record.
  - fetch_to_date sources (oxford_economics, research_affiliates) have bulk/
    migration-stamped lastmods, so their true 2025+ subset only emerges at fetch.
  - deepmind_blog (js_listing) render currently harvests 0 — needs render tuning.

USAGE
  python3 scripts/backfill_concepts_history.py --signal-tier --session-cap 150   # the local job
  python3 scripts/backfill_concepts_history.py --canary --enumerate-only
  python3 scripts/backfill_concepts_history.py --canary --per-source-cap 10
  python3 scripts/backfill_concepts_history.py --canary --sources paul_graham_essays
"""
import argparse
import datetime
import importlib.util
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

# --- reuse the daily collector's fetch + date logic (NOT forked) ---
REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("collect_concepts", REPO_ROOT / "scripts" / "collect_concepts.py")
cc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cc)
from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# --- history root: OUTSIDE the repo, never committed ---
DEFAULT_HISTORY_ROOT = (
    Path.home() / "Dropbox (Personal)" / "Business" / "InvestTool"
    / "market-intelligence" / "concepts-history"
)
HIST_ROOT = Path(os.environ.get("CONCEPTS_HISTORY_ROOT") or DEFAULT_HISTORY_ROOT).expanduser()
STATE_PATH = HIST_ROOT / "_state" / "backfill_state.json"
RUNLOG_DIR = HIST_ROOT / "_runlog"

# --- daily corpus (read-only, for dedup) ---
DAILY_RAW = REPO_ROOT / "raw" / "concepts"
DAILY_PROCESSED = REPO_ROOT / "processed" / "concepts"

# --- tunables ---
BACKFILL_START_DEFAULT = "2025-01-01"
SESSION_CAP_DEFAULT = 40
PER_SOURCE_CAP_DEFAULT = 12
SLEEP_FETCH = (4.0, 10.0)
SLEEP_SOURCE = (20.0, 60.0)
CONSECUTIVE_FAIL_ABORT = 3
HTTP_TIMEOUT = 20

_BOT_RE = re.compile(r"429|too many requests|unusual traffic|are you a human|"
                     r"captcha|access denied|bot detection|cloudflare", re.I)

# --- per-source backfill METHOD (default for any source not listed = generic
#     sitemap with reliable <lastmod> dates). One unified taxonomy:
#       sitemap         generic sitemap, lastmod >= start
#       sitemap_path    sitemap + per-source article-path filter + bulk-stamp guard
#       fetch_to_date   sitemap URLs but lastmods are bulk/migration-stamped ->
#                       date each at FETCH time via the daily extract_date
#       flat_html_byline  Paul Graham — fetch each essay, parse "Month Year" byline
#       js_listing      render a JS listing, harvest links (date at fetch)
BACKFILL_METHODS = {
    "paul_graham_essays": {"method": "flat_html_byline"},
    "howard_marks_memos": {"method": "js_listing",
                           "listing": "https://www.oaktreecapital.com/insights/memos",
                           "url_must": "/insights/memo"},
    "deepmind_blog": {"method": "js_listing",
                      "listing": "https://deepmind.google/discover/blog/",
                      "url_must": "/discover/blog/"},
    "ny_fed_liberty_street_economics": {"method": "sitemap_path", "contains": "libertystreeteconomics",
                                        "path_re": re.compile(r"/20\d{2}/\d{2}/")},
    "vanguard_research": {"method": "sitemap_path", "contains": "/articles/"},
    "world_gold_council": {"method": "sitemap_path", "contains": "/goldhub/"},
    "glencore_investor_reports": {"method": "sitemap_path", "contains": "/media-and-insights/news/"},
    "noema_magazine": {"method": "sitemap_path", "single_segment": True,
                       "exclude": ["/author/", "/tag/", "/category/", "/issue/",
                                   "/podcast", "/newsletter", "/about", "/events"]},
    "dimensional_fund_advisors": {"method": "sitemap_path", "contains": "/us-en/insights/"},  # one locale only
    "research_affiliates": {"method": "fetch_to_date", "contains": "/insights/"},
    "oxford_economics": {"method": "fetch_to_date", "path_re": re.compile(r"^/resource/[^/]+/?$"),
                         "exclude": ["/resource/tag", "/zh-hans/", "/ja/", "/de/", "/fr/",
                                     "/es/", "/it/", "/pt/", "/ko/", "/nl/", "/zh-hant/"]},
}


# Stage-1 (clean) + Stage-2 (corrected) signal sources, SMALL-first so capped/
# resumed runs complete whole sources. Flagged Stage-3 sources are excluded
# (oaktree_capital_insights, bcg_henderson_institute, ark_invest_research,
# palladium_magazine, sf_fed_economic_letters, capital_economics, aqr_perspectives,
# ecb_blog, openai_blog, the_gradient_stanford — need a method still).
SIGNAL_TIER_ORDER = [
    "founders_fund_blog", "matt_ball", "hussman_funds_commentary", "ray_dalio_principles",
    "paul_graham_essays", "horizon_kinetics", "gavekal_research", "benedict_evans",
    "morgan_housel_collab_fund", "aswath_damodaran", "greylock_blog", "glencore_investor_reports",
    "verdad_capital_research", "packy_mccormick_not_boring", "st_louis_fed_fred_blog",
    "works_in_progress", "anthropic_blog", "gmo_white_papers", "vanguard_research", "sequoia_arc",
    "bessemer_venture_partners", "ny_fed_liberty_street_economics", "a16z_blog", "noema_magazine",
    "world_gold_council", "howard_marks_memos", "deepmind_blog", "byrne_hobart_the_diff",
    "dimensional_fund_advisors", "research_affiliates", "oxford_economics",
]


def _passes_filter(url, rule):
    p = urlparse(url); full, path = url.lower(), p.path
    if rule.get("contains") and rule["contains"].lower() not in full:
        return False
    if rule.get("path_re") and not rule["path_re"].search(path):
        return False
    if rule.get("exclude") and any(x in full for x in rule["exclude"]):
        return False
    if rule.get("single_segment"):
        segs = [s for s in path.strip("/").split("/") if s]
        if len(segs) != 1 or "." in segs[0] or len(segs[0]) < 6:
            return False
    return True


def _bulk_guard(dated):
    """Drop a lastmod that dominates (>40%) — a migration/bulk stamp, not a real date."""
    if not dated:
        return dated, None
    from collections import Counter
    top_date, top_n = Counter(d for _, d in dated).most_common(1)[0]
    if top_n / len(dated) > 0.40:
        return [(l, d) for l, d in dated if d != top_date], (top_date, top_n)
    return dated, None


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# --- polite HTTP for sitemap / flat-archive enumeration (TLS unverified: env certs vary) ---
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
_UA = {"User-Agent": cc.USER_AGENT}


def http_get(url, timeout=HTTP_TIMEOUT):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout, context=_CTX) as r:
            return r.status, r.read(4_000_000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"({type(e).__name__})"


# --- enumeration ------------------------------------------------------------
def enum_js_listing_render(page, listing, url_must):
    """Render a JS listing (scroll) and harvest article links matching url_must.
    Dates are NOT available from the listing -> determined later at fetch time."""
    if page is None:
        return None   # caller (HTTP-only context) flags this source for a render pass
    try:
        cc.navigate(page, listing)
    except (PlaywrightTimeout, PlaywrightError):
        return []
    cc.settle_index(page)
    for _ in range(5):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
        except Exception:
            break
    apex = cc.apex_domain(urlparse(listing).netloc)
    out, seen = [], set()
    for a in cc.collect_anchors(page, page.url):
        if url_must in a and cc.apex_domain(urlparse(a).netloc) == apex:
            key = cc.norm_url(a)
            if key not in seen and key != cc.norm_url(listing):
                seen.add(key); out.append((a, None))
    return out


# --- dedup ------------------------------------------------------------------
def already_known(slug, record_id):
    if (DAILY_PROCESSED / f"{record_id}.json").exists():
        return "daily-processed"
    for d in DAILY_RAW.glob(f"*/{record_id}.json"):
        return "daily-raw"
    if (HIST_ROOT / slug / f"{record_id}.json").exists():
        return "history"
    return None


# --- fetch one article (reuse daily extract_article + extract_date) ---------
def fetch_article(page, url):
    cc.navigate(page, url)
    data = cc.extract_article(page)
    text = data.get("text", "")
    pub = (cc.extract_date(data.get("html", ""), url)
           or cc.parse_date(data.get("date_raw"))
           or cc.find_date_in_text(text))
    return {
        "title": data.get("title", ""), "author": (data.get("author") or ""),
        "text": text, "image_urls": data.get("images", []),
        "published_date": pub.isoformat() if pub else "",
        "word_count": len((text or "").split()),
    }


def sleep(rng, label=""):
    s = random.uniform(*rng)
    log(f"  [throttle] {s:.0f}s {label}")
    time.sleep(s)


# ===========================================================================
# TIER ENUMERATION (enumerate-only across the signal tier; HTTP, no fetches)
# ===========================================================================
HEAVY_TIER = {
    "brookings_institution", "csis", "atlantic_council", "carnegie_endowment",
    "rand_corporation", "council_on_foreign_relations", "peterson_institute_piie",
    "chatham_house", "world_economic_forum", "hudson_institute", "german_marshall_fund",
    "iiss", "imf_blog", "nber_working_papers", "ssrn",
}
_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_MNUM = {m: i for i, m in enumerate(_MONTHS, 1)}
_BYLINE_RE = re.compile(r"\b(" + "|".join(m.capitalize() for m in _MONTHS) + r")\s+(20\d{2})\b")
# Article-sitemaps we prefer inside a sitemap index (vs page/tag/author maps).
_ARTICLE_MAP_HINT = re.compile(r"post|article|insight|blog|news|memo|essay|research|publication", re.I)
START_DEFAULT = "2025-01-01"


def pg_byline_date(essay_url):
    """Fetch a Paul Graham essay and parse its 'Month Year' byline -> YYYY-MM-01."""
    s, b = http_get(essay_url)
    if s != 200 or not b:
        return None
    txt = re.sub(r"<[^>]+>", " ", b)
    m = _BYLINE_RE.search(txt[:1200])   # byline sits right under the title
    if not m:
        return None
    return f"{int(m.group(2)):04d}-{_MNUM[m.group(1).lower()]:02d}-01"


def enum_pg_byline(start):
    """Enumerate ALL PG essays, date each by its byline, keep >= start."""
    s, b = http_get("https://paulgraham.com/articles.html")
    if s != 200:
        return [], f"archive {s}"
    links = re.findall(r'<a href="([a-z0-9][a-z0-9\-]*\.html)"', b, re.I)
    links = [l for l in dict.fromkeys(links) if l not in ("index.html", "rss.html", "articles.html")]
    out, undated = [], 0
    for i, slug in enumerate(links):
        u = "https://paulgraham.com/" + slug
        d = pg_byline_date(u)
        if d is None:
            undated += 1
        elif d >= start:
            out.append((u, d))
        time.sleep(0.25)   # polite to a small personal site
    return out, (None if not undated else f"{undated} undated essays skipped")


def discover_sitemaps(base):
    s, b = http_get(base + "/robots.txt", timeout=12)
    sm = re.findall(r"(?im)^sitemap:\s*(\S+)", b) if b else []
    for p in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml"):
        if base + p not in sm:
            sm.append(base + p)
    return sm


def sitemap_entries(url, apex, depth=0, budget=None):
    """Return [(loc, lastmod)] for article-ish URLs on `apex`, following an index
    one level (preferring article/post sub-maps), bounded by `budget` sub-maps."""
    if budget is None:
        budget = [40]   # follow enough index sub-maps to reach recent posts on
                        # paginated blog sitemaps (blogspot/Ghost order varies)
    s, b = http_get(url)
    if s != 200 or "<" not in (b or ""):
        return []
    head = b[:300].lower()
    if "<sitemapindex" in head:
        subs = re.findall(r"<loc>([^<]+)</loc>", b)
        subs.sort(key=lambda u: (0 if _ARTICLE_MAP_HINT.search(u) else 1))  # article maps first
        out = []
        for sub in subs:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            out += sitemap_entries(sub, apex, depth + 1, budget)
        return out
    rows = []
    for m in re.finditer(r"<url>(.*?)</url>", b, re.S):
        block = m.group(1)
        lm = re.search(r"<loc>([^<]+)</loc>", block)
        ld = re.search(r"<lastmod>([^<]+)</lastmod>", block)
        if not lm:
            continue
        loc = lm.group(1)
        if cc.apex_domain(urlparse(loc).netloc) == apex:
            rows.append((loc, (ld.group(1)[:10] if ld else None)))
    return rows


def enum_sitemap(index_url, start, rule=None, use_dates=True, use_bulk_guard=False):
    """Discover the source's sitemap(s), apply an optional per-source article-path
    `rule` (else the generic looks_like_article filter), and return
    [(url, date_or_None)] with a note. use_dates=True -> keep lastmod >= start
    (after bulk-stamp guard); use_dates=False (fetch_to_date) -> return the
    path-filtered URLs with date=None (the fetch step dates them). None if no sitemap."""
    parsed = urlparse(index_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    apex = cc.apex_domain(parsed.netloc)
    entries = []
    for sm in discover_sitemaps(base):
        entries = sitemap_entries(sm, apex)
        if entries:
            break
    if not entries:
        return None, "no-sitemap"
    if rule:
        entries = [(l, d) for l, d in entries if _passes_filter(l, rule)]
    else:
        entries = [(l, d) for l, d in entries if cc.looks_like_article(l, apex)]
    if not use_dates:
        return [(l, None) for l, _ in entries], "fetch_to_date (lastmods unreliable)"
    dated = [(l, d) for l, d in entries if d]
    note = None
    if use_bulk_guard:
        dated, bulk = _bulk_guard(dated)
        note = f"dropped {bulk[1]} bulk-stamped {bulk[0]}" if bulk else None
    if not dated:
        return None, "sitemap has URLs but no usable lastmod dates"
    plus = sorted([(l, d) for l, d in dated if d >= start], key=lambda r: r[1], reverse=True)
    return plus, note


def detect_and_enumerate(slug, source, start, page=None):
    """Unified enumerator. Returns (method, result, note); result is
    [(url, date_or_None)] or a 'FLAG:...' string. `page` enables js_listing render."""
    m = BACKFILL_METHODS.get(slug, {"method": "sitemap"})
    method = m["method"]
    if method == "flat_html_byline":
        rows, note = enum_pg_byline(start)
        return method, rows, note
    if method == "js_listing":
        rows = enum_js_listing_render(page, m["listing"], m["url_must"])
        if rows is None:
            return method, "FLAG:js_listing — render needed to enumerate (run with a fetch page)", None
        return method, rows, "date at fetch"
    if method == "fetch_to_date":
        res, note = enum_sitemap(source["index_url"], start, rule=m, use_dates=False)
        return (method, res, note) if res is not None else (method, "FLAG:" + (note or "no sitemap"), None)
    if method == "sitemap_path":
        res, note = enum_sitemap(source["index_url"], start, rule=m, use_dates=True, use_bulk_guard=True)
        return (method, res, note) if res is not None else (method, "FLAG:" + (note or "no sitemap"), None)
    res, note = enum_sitemap(source["index_url"], start, rule=None, use_dates=True)
    if res is None:
        return "no-sitemap", "FLAG:no sitemap discovered — needs js_listing/flat method", note
    return "sitemap", res, note


def run_enumerate_final(start, page=None):
    """Final signal-tier enumeration with the finalized per-source methods."""
    cfg_all = {cc.slugify(s["name"]): s for s in
               json.loads((REPO_ROOT / "config" / "concepts_sources.json").read_text())["sources"]}
    active = [s for s in cfg_all.values() if not (s.get("collect") is False or s.get("paywalled"))]
    signal = sorted((s for s in active if cc.slugify(s["name"]) not in HEAVY_TIER),
                    key=lambda s: cc.slugify(s["name"]))
    bonus = [cfg_all[s] for s in ("sequoia_arc",) if s in cfg_all]   # disabled SPA, sitemap-reachable
    log(f"SIGNAL-TIER FINAL enumeration | {len(signal)} sources (+{len(bonus)} bonus) | start={start}\n")
    log(f"  {'source':<32}{'method':<18}{'count':>6}  range / note")
    rows = []; total_dated = 0; total_fetch = 0; flags = []
    for s in signal + bonus:
        slug = cc.slugify(s["name"])
        try:
            method, res, note = detect_and_enumerate(slug, s, start, page=page)
        except Exception as e:
            log(f"  {slug:<32}{'ERROR':<18}{type(e).__name__}"); flags.append((slug, f"error {type(e).__name__}")); continue
        if isinstance(res, str) and res.startswith("FLAG:"):
            log(f"  {slug:<32}{method:<18}  FLAG: {res[5:]}"); flags.append((slug, res[5:])); continue
        new = [(u, d) for (u, d) in res if not already_known(slug, cc.url_hash(u))]
        fetchdate = method in ("fetch_to_date", "js_listing")
        if fetchdate:
            total_fetch += len(new)
        else:
            total_dated += len(new)
        ds = sorted(d for _, d in new if d)
        rng = (f"{ds[0]}..{ds[-1]}" if ds else "date@fetch")
        log(f"  {slug:<32}{method:<18}{len(new):>6}  {rng}" + (f"  ({note})" if note else ""))
        rows.append((slug, method, len(new), fetchdate))
    log("\n" + "=" * 66)
    log(f"SIGNAL-TIER TOTAL: {total_dated + total_fetch} >= {start}  =  "
        f"{total_dated} sitemap-dated (confirmed 2025+)  +  {total_fetch} date-at-fetch "
        f"candidates (2025+ subset emerges at fetch)  across {len(rows)} sources")
    if flags:
        log(f"FLAGGED ({len(flags)}): " + "; ".join(f"{s} ({w[:40]})" for s, w in flags))
    return rows, flags


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--canary", action="store_true", help="signal-tier canary: PG, Howard Marks, a16z")
    ap.add_argument("--sources", default=None, help="comma-separated slugs (default: canary set)")
    ap.add_argument("--start", default=BACKFILL_START_DEFAULT, help="backfill back to this date (YYYY-MM-DD)")
    ap.add_argument("--per-source-cap", type=int, default=PER_SOURCE_CAP_DEFAULT)
    ap.add_argument("--session-cap", type=int, default=SESSION_CAP_DEFAULT)
    ap.add_argument("--enumerate-only", action="store_true", help="list counts; fetch nothing")
    ap.add_argument("--enumerate-final", action="store_true",
                    help="FINAL signal-tier enumeration with finalized per-source methods (renders js_listing)")
    ap.add_argument("--signal-tier", action="store_true",
                    help="fetch the full Stage-1+2 signal tier (small-first; flagged Stage-3 sources excluded)")
    ap.add_argument("--dry-run", action="store_true", help="fetch but don't write to history")
    args = ap.parse_args()

    if args.enumerate_final:
        with sync_playwright() as pw:   # js_listing sources need a render page
            b = pw.chromium.launch(headless=True)
            ctx = b.new_context(user_agent=cc.USER_AGENT, viewport=cc.DEFAULT_VIEWPORT, ignore_https_errors=True)
            pg = ctx.new_page(); pg.set_default_timeout(cc.PAGE_TIMEOUT_MS)
            run_enumerate_final(args.start, page=pg)
            b.close()
        return

    canary = ["paul_graham_essays", "howard_marks_memos", "a16z_blog"]
    if args.sources:
        slugs = [s.strip() for s in args.sources.split(",")]
    elif args.signal_tier:
        slugs = SIGNAL_TIER_ORDER
    else:
        slugs = canary
    cfg_all = {cc.slugify(s["name"]): s for s in
               json.loads((REPO_ROOT / "config" / "concepts_sources.json").read_text())["sources"]}

    # Per-source completion state (skip fully-collected sources -> true overnight no-op).
    done_path = HIST_ROOT / "_state" / "backfill_state.json"
    try:
        done = set(json.loads(done_path.read_text()).get("done", []))
    except Exception:
        done = set()
    def mark_done(s):
        done.add(s)
        done_path.parent.mkdir(parents=True, exist_ok=True)
        done_path.write_text(json.dumps({"done": sorted(done)}, indent=2), encoding="utf-8")

    log(f"Concepts backfill — RAW ONLY | start={args.start} | history={HIST_ROOT}")
    log(f"sources: {slugs} | per-source-cap={args.per_source_cap} session-cap={args.session_cap}"
        + (" | ENUMERATE-ONLY" if args.enumerate_only else "") + (" | DRY-RUN" if args.dry_run else ""))
    HIST_ROOT.mkdir(parents=True, exist_ok=True)

    summary = []
    session_fetched = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=cc.USER_AGENT, viewport=cc.DEFAULT_VIEWPORT, ignore_https_errors=True)
        page = ctx.new_page(); page.set_default_timeout(cc.PAGE_TIMEOUT_MS)

        for si, slug in enumerate(slugs):
            meta = cfg_all.get(slug, {})
            if not meta:
                log(f"[{slug}] not in config — skip"); continue
            if slug in done and not args.enumerate_only:
                log(f"=== [{slug}] already complete — skip ==="); continue
            log(f"\n=== [{slug}] ===")
            # enumerate via the generic detector (sitemap / PG byline / etc.)
            try:
                method, res, note = detect_and_enumerate(slug, meta, args.start, page=page)
            except Exception as e:
                log(f"  enumerate ERROR {type(e).__name__}: {e}")
                summary.append((slug, 0, 0, 0, 0, "enum-error")); continue
            if isinstance(res, str) and res.startswith("FLAG:"):
                log(f"  FLAGGED ({method}): {res[5:]} — skip (not a clean Stage-1 source)")
                summary.append((slug, 0, 0, 0, 0, "flagged")); continue
            cand = res  # [(url, enum_date)]
            log(f"  method={method} | enumerated {len(cand)} URL(s) >= {args.start}"
                + (f" | NOTE: {note}" if note else ""))

            # dedup vs daily corpus + history
            fresh, ded = [], 0
            for url, d in cand:
                rid = cc.url_hash(url)
                if already_known(slug, rid):
                    ded += 1
                else:
                    fresh.append((url, d, rid))
            log(f"  after dedup vs daily+history: {len(fresh)} new ({ded} already known)")
            if args.enumerate_only:
                summary.append((slug, len(cand), ded, len(fresh), 0, "enum-only")); continue
            if not fresh:
                mark_done(slug)
                log(f"  nothing new — source COMPLETE (marked done)")
                summary.append((slug, len(cand), ded, 0, 0, "complete")); continue

            # fetch raw text (throttled, session-capped, resumable via file dedup)
            kept = 0; consec_fail = 0; dates = []
            for url, enum_date, rid in fresh[:args.per_source_cap]:
                if session_fetched >= args.session_cap:
                    log("  session cap reached — stopping (resumable: re-run to continue)"); break
                try:
                    rec = fetch_article(page, url); consec_fail = 0
                except (PlaywrightTimeout, PlaywrightError) as e:
                    consec_fail += 1
                    log(f"  WARN fetch {url[:55]} — {type(e).__name__} ({consec_fail}/{CONSECUTIVE_FAIL_ABORT})")
                    if consec_fail >= CONSECUTIVE_FAIL_ABORT:
                        log("HARD STOP: 3 consecutive fetch failures — exit 10")
                        _write_runlog(summary, args, hard_stop=True); sys.exit(10)
                    sleep(SLEEP_FETCH); continue
                session_fetched += 1
                if _BOT_RE.search((rec.get("text") or "")[:400]) or _BOT_RE.search(rec.get("title") or ""):
                    log("HARD STOP: bot/consent/429 signal in fetched page — exit 10")
                    _write_runlog(summary, args, hard_stop=True); sys.exit(10)
                # prefer the article's own date; fall back to the enumeration date (sitemap lastmod / PG byline)
                pub = rec["published_date"] or (enum_date or "")
                if rec["published_date"] and rec["published_date"] < args.start:
                    log(f"  drop (article date {rec['published_date']} < {args.start}): {rec['title'][:44]}")
                    sleep(SLEEP_FETCH); continue
                if not pub:
                    log(f"  drop (no date): {rec['title'][:44]}"); sleep(SLEEP_FETCH); continue
                if len((rec.get("text") or "")) < cc.MIN_TEXT_LEN:
                    log(f"  drop (short/empty): {rec['title'][:44]}"); sleep(SLEEP_FETCH); continue
                record = {
                    "record_id": rid, "source_slug": slug,
                    "source_name": meta.get("name", slug), "source_url": url,
                    "category": meta.get("category", ""), "type": meta.get("type", ""),
                    "paywalled": bool(meta.get("paywalled", False)),
                    "title": rec["title"], "published_date": pub, "language": "en",
                    "author": rec["author"], "word_count": rec["word_count"],
                    "text": rec["text"], "image_urls": rec["image_urls"],
                    "collected_at": datetime.datetime.now(datetime.timezone.utc)
                                     .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "backfill": True, "enumerated_via": method, "lastmod": enum_date,
                }
                if not args.dry_run:
                    d = HIST_ROOT / slug; d.mkdir(parents=True, exist_ok=True)
                    (d / f"{rid}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                kept += 1; dates.append(pub)
                log(f"  +kept [{pub}] {rec['word_count']:>5}w  {rec['title'][:48]}")
                sleep(SLEEP_FETCH)
            drange = f"{min(dates)}..{max(dates)}" if dates else "n/a"
            summary.append((slug, len(cand), ded, len(fresh), kept, drange))
            if si < len(slugs) - 1 and not args.enumerate_only:
                sleep(SLEEP_SOURCE, "inter-source")
        browser.close()

    _write_runlog(summary, args)
    log("\n" + "=" * 64)
    log(f"{'source':<26}{'enum':>6}{'dupe':>6}{'new':>6}{'kept':>6}  date-range")
    for slug, enm, ded, fr, kp, dr in summary:
        log(f"  {slug:<24}{enm:>6}{ded:>6}{fr:>6}{kp:>6}  {dr}")
    log(f"session fetched: {session_fetched} | history: {HIST_ROOT}")


def _write_runlog(summary, args, hard_stop=False):
    RUNLOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    lines = [f"# Concepts backfill run {ts}",
             f"- start={args.start} per_source_cap={args.per_source_cap} session_cap={args.session_cap}",
             f"- mode={'enumerate-only' if args.enumerate_only else ('dry-run' if args.dry_run else 'fetch')}"
             + (" | HARD-STOP" if hard_stop else ""), "",
             "| source | enumerated | dup | new | kept | date-range |",
             "|---|---|---|---|---|---|"]
    for slug, enm, ded, fr, kp, dr in summary:
        lines.append(f"| {slug} | {enm} | {ded} | {fr} | {kp} | {dr} |")
    (RUNLOG_DIR / f"{ts}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
