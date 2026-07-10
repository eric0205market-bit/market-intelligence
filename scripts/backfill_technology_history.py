#!/usr/bin/env python3
"""Technology historical-backfill collector (RAW ONLY — no extraction, no publish).

CLONE of scripts/backfill_concepts_history.py — the exact proven design (sitemap-
first enumeration; flat_html / js_listing / index_render fallbacks; dedup vs the
daily corpus + history; per-site quarantine; resumable _state). Retargeted to the
TECHNOLOGY stream: reuses scripts/collect_technology.py for fetch + date logic, the
technology daily corpus for dedup, and a SEPARATE history root.

COMPLETELY SEPARATE from the daily pipeline (scripts/collect_technology.py).
- Manual / launchd trigger only; NEVER run by GitHub Actions.
- Writes to a history root OUTSIDE the git repo (never committed), mirroring the
  Concepts/YouTube backfill convention but under a Technology root:
      ~/Dropbox (Personal)/Business/InvestTool/market-intelligence/technology-history/
        {source_slug}/{record_id}.json   — daily raw shape + "backfill": true
        _state/backfill_state.json
        _runlog/{timestamp}.md
  (Override with $TECHNOLOGY_HISTORY_ROOT.)

SCOPE — SIGNAL TIER = the 27 ACTIVE Deep sources only (type=="Deep", collect!=False,
  not paywalled). The 5 ACTIVE Flow sources (mit_technology_review, ars_technica,
  wired, nvidia_developer_blog, infoq) are PERISHABLE news — EXCLUDED from backfill.
  Cloud-parked-but-residential-OK analytical sources are included if reachable.

DEDUP — against BOTH:
  - the TECHNOLOGY daily corpus on main:  repo raw/technology/<slug>/<id>.json AND
                                          repo processed/technology/<id>.json
  - the history folder:                   technology-history/<slug>/<id>.json
  record_id = same url-hash the daily collector uses (ct.url_hash), so a URL already
  collected daily (or already backfilled) is never re-enumerated as "new".

ENUMERATION METHODS (unified taxonomy, default = generic sitemap with reliable
  <lastmod> dates):
    sitemap         generic sitemap, lastmod >= start
    sitemap_path    sitemap + per-source article-path filter + bulk-stamp guard
    fetch_to_date   sitemap URLs but lastmods are bulk/migration-stamped -> date
                    each at FETCH time via the daily extract_date
    js_listing      render a JS listing, harvest links (date at fetch)
    index_render    GENERAL render-harvest (navigate -> settle/scroll -> dismiss
                    banner -> collect_anchors -> looks_like_article). Optional light
                    pagination via "paginate". Stage-3 fallback for JS-walled /
                    sitemap-less sites. Date @ fetch.

THIS STEP (CANARY) = ENUMERATE ONLY. No article bodies fetched, no history files
  written beyond _state. --enumerate-final probes each source's method and counts,
  per source, how many article URLs fall in [--start .. now] minus the daily corpus.

USAGE
  python3 scripts/backfill_technology_history.py --enumerate-final          # the canary
  python3 scripts/backfill_technology_history.py --enumerate-final --start 2025-01-01
  python3 scripts/backfill_technology_history.py --canary --enumerate-only
  python3 scripts/backfill_technology_history.py --canary --sources semianalysis
"""
import argparse
import datetime
import gzip
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
_spec = importlib.util.spec_from_file_location("collect_technology", REPO_ROOT / "scripts" / "collect_technology.py")
ct = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ct)
from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# --- history root: OUTSIDE the repo, never committed ---
DEFAULT_HISTORY_ROOT = (
    Path.home() / "Dropbox (Personal)" / "Business" / "InvestTool"
    / "market-intelligence" / "technology-history"
)
HIST_ROOT = Path(os.environ.get("TECHNOLOGY_HISTORY_ROOT") or DEFAULT_HISTORY_ROOT).expanduser()
STATE_PATH = HIST_ROOT / "_state" / "backfill_state.json"
RUNLOG_DIR = HIST_ROOT / "_runlog"

# --- daily corpus (read-only, for dedup) ---
DAILY_RAW = REPO_ROOT / "raw" / "technology"
DAILY_PROCESSED = REPO_ROOT / "processed" / "technology"

# --- tunables ---
BACKFILL_START_DEFAULT = "2025-01-01"
SESSION_CAP_DEFAULT = 40
PER_SOURCE_CAP_DEFAULT = 12
SLEEP_FETCH = (4.0, 10.0)     # per-SITE politeness (same-domain, sequential) — KEEP
SLEEP_SOURCE = (1.0, 3.0)     # different site next — brief courtesy gap, not a throttle
CONSECUTIVE_FAIL_ABORT = 3    # per-SOURCE: this many in a row quarantines that site, not the run
SITE_COOLDOWN_S = 24 * 3600   # per-SITE quarantine window after a 429/bot block; others keep running
SHORT_RETRY_WORDS = 150       # a fetch under this -> render-retry (JS settle/scroll) before length gate
HTTP_TIMEOUT = 20

_BOT_RE = re.compile(r"429|too many requests|unusual traffic|are you a human|"
                     r"captcha|access denied|bot detection|cloudflare|"
                     r"403 forbidden|403 error|error 403|http 403", re.I)

# --- per-source backfill METHOD (default for any source not listed = generic
#     sitemap with reliable <lastmod> dates). Same unified taxonomy as Concepts;
#     a rule may carry "sitemap_url" to point enum_sitemap at a specific sitemap
#     (bypassing apex-root discovery) when the corporate apex sitemap is the wrong
#     one or lists a whole hub. Populated from the canary probe.
BACKFILL_METHODS = {
    # --- SCOPE FILTERS: the generic apex sitemap over-counts (locale dupes / hub /
    #     non-analytical genres). Restrict to real article paths. ---
    "hugging_face_blog": {                     # apex sitemap = entire HF Hub; use the
        "method": "sitemap_path",              # dedicated blog sub-sitemap only
        "sitemap_url": "https://huggingface.co/sitemap-blog.xml",
        "contains": "/blog/"},
    "google_ai_blog": {                        # blog.google is all sections + /intl/
        "method": "sitemap_path",              # locale dupes; keep the AI section only
        "path_re": re.compile(r"/innovation-and-ai/"),
        "exclude": ["/intl/"]},
    "wood_mackenzie": {                         # /news/opinion + /blogs analysis only;
        "method": "sitemap_path",               # drop bare /news, podcasts, events, press
        "path_re": re.compile(r"/(news/opinion|blogs)/"),
        "exclude": ["/podcasts/", "/events/", "/press-releases/"]},
    # --- QUICK FIXES: a usable sitemap exists, the apex-root probe just missed it. ---
    "microsoft_research_blog": {                # apex = MS-corporate; point at the
        "method": "sitemap_path",               # research WP index, keep /research/blog/
        "sitemap_url": "https://www.microsoft.com/en-us/research/sitemap.xml",
        "contains": "/research/blog/"},
    "benchmark_minerals": {                     # real sitemap.xml has 4,399 URLs but NO
        "method": "fetch_to_date",              # <lastmod> -> date each at fetch time
        "sitemap_url": "https://source.benchmarkminerals.com/sitemap.xml",
        "contains": "/article/"},
    # semiwiki: NO method entry needed — its WordPress sitemap_index 502'd transiently
    #   during the first run; the generic sitemap path + http_get retry now reaches it.
    #
    # LEFT FLAGGED for later (need render or are paywalled/blocked — NOT solved here):
    #   apple_ml_research, mistral_blog (render); meta_ai_blog (gzip+403/cloud-block);
    #   nature_biotechnology, nature_energy, nature_machine_intelligence (paywalled
    #   multi-journal). These fall through to the generic path and re-flag as no-sitemap.
}


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
_UA = {"User-Agent": ct.USER_AGENT}


def http_get(url, timeout=HTTP_TIMEOUT, retries=1):
    """Polite GET. Transparently gunzips .gz / gzip-magic bodies (so gzipped
    sitemaps parse) and retries once on a transient 502/503/network error (e.g.
    semiwiki's flaky WordPress sitemap)."""
    last = (None, "")
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA),
                                        timeout=timeout, context=_CTX) as r:
                raw = r.read(6_000_000)
                if url.lower().endswith(".gz") or raw[:2] == b"\x1f\x8b":
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                return r.status, raw.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            last = (e.code, "")
            if e.code in (502, 503) and attempt < retries:
                time.sleep(2.0); continue
            return last
        except Exception as e:
            last = (None, f"({type(e).__name__})")
            if attempt < retries:
                time.sleep(2.0); continue
    return last


# --- enumeration ------------------------------------------------------------
def enum_js_listing_render(page, listing, url_must):
    """Render a JS listing (scroll) and harvest article links matching url_must.
    Dates are NOT available from the listing -> determined later at fetch time."""
    if page is None:
        return None   # caller (HTTP-only context) flags this source for a render pass
    try:
        ct.navigate(page, listing)
    except (PlaywrightTimeout, PlaywrightError):
        return []
    ct.settle_index(page)
    for _ in range(5):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
        except Exception:
            break
    apex = ct.apex_domain(urlparse(listing).netloc)
    out, seen = [], set()
    for a in ct.collect_anchors(page, page.url):
        if url_must in a and ct.apex_domain(urlparse(a).netloc) == apex:
            key = ct.norm_url(a)
            if key not in seen and key != ct.norm_url(listing):
                seen.add(key); out.append((a, None))
    return out


def enum_index_render(page, source, rule):
    """GENERAL render-harvest enumerator (Stage-3 fallback). Reuses the shared
    collect_technology machinery — ct.navigate (dismisses cookie/consent banners) ->
    ct.settle_index (+ scroll) -> ct.collect_anchors — then keeps on-apex links that
    pass ct.looks_like_article (or a per-source article_path_re), optionally
    restricted to url_must. Light pagination via rule['paginate'] = a {n} URL
    template; without it the listing is RECENT-ONLY (flagged in the note).
    Returns ([(url, None)], note) — dates determined later at FETCH time."""
    if page is None:
        return None, "render needed"
    listing = rule.get("listing") or source["index_url"]
    url_must = (rule.get("url_must") or "").lower()
    apath = rule.get("article_path_re")
    apex = ct.apex_domain(urlparse(listing).netloc)
    pag = rule.get("paginate")
    pages = [listing]
    if pag:
        pages += [pag["template"].format(n=n) for n in range(2, int(pag.get("max", 6)) + 1)]

    out, seen = [], {ct.norm_url(listing)}
    empties = 0
    for pg_url in pages:
        try:
            ct.navigate(page, pg_url)
        except (PlaywrightTimeout, PlaywrightError):
            empties += 1
            if empties >= 2:
                break
            continue
        ct.settle_index(page)
        for _ in range(4):   # nudge infinite-scroll / lazy listings
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
            except Exception:
                break
        before = len(out)
        for a in ct.collect_anchors(page, page.url):
            if ct.apex_domain(urlparse(a).netloc) != apex:
                continue
            if url_must and url_must not in a.lower():
                continue
            is_art = ct.looks_like_article(a, apex)
            if not is_art and apath is not None and apath.search(urlparse(a).path):
                is_art = True
            if not is_art:
                continue
            key = ct.norm_url(a)
            if key in seen:
                continue
            seen.add(key); out.append((a, None))
        if pag and len(out) == before:   # paginated page added nothing new
            empties += 1
            if empties >= 2:
                break
        else:
            empties = 0
    note = "date@fetch; " + ("paginated" if pag else "RECENT-ONLY (no pagination configured)")
    return out, note


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
def fetch_article(page, url, render=False):
    ct.navigate(page, url)            # ct.navigate already dismisses cookie banners…
    ct.dismiss_cookie_banner(page)    # …BONUS: a second pass for late-injected consent
    if render:                        # RENDER-RETRY: let JS-heavy pages inject body text
        ct.settle_index(page)
        for _ in range(2):
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
            except Exception:
                break
        ct.dismiss_cookie_banner(page)
    data = ct.extract_article(page)
    text = data.get("text", "")
    pub = (ct.extract_date(data.get("html", ""), url)
           or ct.parse_date(data.get("date_raw"))
           or ct.find_date_in_text(text))
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
# SITEMAP enumeration (HTTP, no render)
# ===========================================================================
_ARTICLE_MAP_HINT = re.compile(r"post|article|insight|blog|news|memo|essay|research|publication", re.I)
START_DEFAULT = "2025-01-01"


def discover_sitemaps(base):
    s, b = http_get(base + "/robots.txt", timeout=12)
    sm = re.findall(r"(?im)^sitemap:\s*(\S+)", b) if b else []
    for p in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml",
              "/news-sitemap.xml", "/post-sitemap.xml"):
        if base + p not in sm:
            sm.append(base + p)
    return sm


def sitemap_entries(url, apex, depth=0, budget=None):
    """Return [(loc, lastmod)] for article-ish URLs on `apex`, following an index
    one level (preferring article/post sub-maps), bounded by `budget` sub-maps."""
    if budget is None:
        budget = [40]
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
        if ct.apex_domain(urlparse(loc).netloc) == apex:
            rows.append((loc, (ld.group(1)[:10] if ld else None)))
    return rows


def enum_sitemap(index_url, start, rule=None, use_dates=True, use_bulk_guard=False):
    """Discover the source's sitemap(s), apply an optional per-source article-path
    `rule` (else the generic looks_like_article filter), and return
    [(url, date_or_None)] with a note. use_dates=True -> keep lastmod >= start
    (after bulk-stamp guard); use_dates=False (fetch_to_date) -> path-filtered URLs
    with date=None. None if no sitemap."""
    parsed = urlparse(index_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    apex = ct.apex_domain(parsed.netloc)
    entries = []
    # a rule may pin an exact sitemap URL when apex-root discovery finds the wrong
    # one (MS-corporate apex) or a whole-hub sitemap (HF). apex is taken from that
    # sitemap's own host so cross-host article URLs still pass the apex filter.
    candidates = ([rule["sitemap_url"]] if (rule and rule.get("sitemap_url"))
                  else discover_sitemaps(base))
    if rule and rule.get("sitemap_url"):
        apex = ct.apex_domain(urlparse(rule["sitemap_url"]).netloc)
    for sm in candidates:
        entries = sitemap_entries(sm, apex)
        if entries:
            break
    if not entries:
        return None, "no-sitemap"
    if rule:
        entries = [(l, d) for l, d in entries if _passes_filter(l, rule)]
    else:
        entries = [(l, d) for l, d in entries if ct.looks_like_article(l, apex)]
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
    if method == "js_listing":
        rows = enum_js_listing_render(page, m["listing"], m["url_must"])
        if rows is None:
            return method, "FLAG:js_listing — render needed to enumerate (run with a fetch page)", None
        return method, rows, "date at fetch"
    if method == "index_render":
        rows, note = enum_index_render(page, source, m)
        if rows is None:
            return method, "FLAG:index_render — render page needed to enumerate", None
        return method, rows, note
    if method == "fetch_to_date":
        res, note = enum_sitemap(source["index_url"], start, rule=m, use_dates=False)
        return (method, res, note) if res is not None else (method, "FLAG:" + (note or "no sitemap"), None)
    if method == "sitemap_path":
        res, note = enum_sitemap(source["index_url"], start, rule=m, use_dates=True, use_bulk_guard=True)
        return (method, res, note) if res is not None else (method, "FLAG:" + (note or "no sitemap"), None)
    res, note = enum_sitemap(source["index_url"], start, rule=None, use_dates=True)
    if res is None:
        return "no-sitemap", "FLAG:no sitemap discovered — needs js_listing/index_render method", note
    return "sitemap", res, note


# --- signal tier = the 27 ACTIVE Deep sources (exclude the 5 ACTIVE Flow) ---
EXCLUDE_FLOW = {"mit_technology_review", "ars_technica", "wired",
                "nvidia_developer_blog", "infoq"}


def _load_deep_active():
    """The 27 ACTIVE Deep sources: type=='Deep', collect!=False, not paywalled.
    Returns {slug: source} sorted by slug. The 5 ACTIVE Flow are excluded by type."""
    cfg = json.loads((REPO_ROOT / "config" / "technology_sources.json").read_text())["sources"]
    out = {}
    for s in cfg:
        if s.get("collect") is False or s.get("paywalled"):
            continue
        if s.get("type") != "Deep":
            continue
        slug = ct.slugify(s["name"])
        out[slug] = s
    return dict(sorted(out.items()))


def run_enumerate_final(start, page=None):
    """Signal-tier enumeration across the 27 Deep sources (enumerate-only)."""
    deep = _load_deep_active()
    log(f"TECHNOLOGY SIGNAL-TIER enumeration | {len(deep)} Deep sources "
        f"(5 Flow excluded: {', '.join(sorted(EXCLUDE_FLOW))}) | start={start}\n")
    log(f"  {'source':<32}{'method':<14}{'new':>6}  range / note")
    rows = []; total_dated = 0; total_fetch = 0; flags = []
    for slug, s in deep.items():
        try:
            method, res, note = detect_and_enumerate(slug, s, start, page=page)
        except Exception as e:
            log(f"  {slug:<32}{'ERROR':<14}{type(e).__name__}")
            flags.append((slug, f"error {type(e).__name__}")); continue
        if isinstance(res, str) and res.startswith("FLAG:"):
            log(f"  {slug:<32}{method:<14}  FLAG: {res[5:]}")
            flags.append((slug, res[5:])); continue
        new = [(u, d) for (u, d) in res if not already_known(slug, ct.url_hash(u))]
        fetchdate = method in ("fetch_to_date", "js_listing", "index_render")
        if fetchdate:
            total_fetch += len(new)
        else:
            total_dated += len(new)
        ds = sorted(d for _, d in new if d)
        rng = (f"{ds[0]}..{ds[-1]}" if ds else "date@fetch")
        log(f"  {slug:<32}{method:<14}{len(new):>6}  {rng}" + (f"  ({note})" if note else ""))
        rows.append((slug, method, len(new), fetchdate, note or "",
                     (ds[0] if ds else ""), (ds[-1] if ds else "")))
    log("\n" + "=" * 66)
    log(f"SIGNAL-TIER TOTAL: {total_dated + total_fetch} new (post-dedup) >= {start}  =  "
        f"{total_dated} sitemap-dated (confirmed 2025+)  +  {total_fetch} date-at-fetch "
        f"candidates (2025+ subset emerges at fetch)  across {len(rows)} sources")
    if flags:
        log(f"FLAGGED / infeasible ({len(flags)}): " + "; ".join(f"{s} ({w[:48]})" for s, w in flags))
    _write_enum_runlog(rows, flags, start)
    return rows, flags


def _write_enum_runlog(rows, flags, start):
    RUNLOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    lines = [f"# Technology backfill ENUMERATE-ONLY {ts}",
             f"- start={start} | scope=27 ACTIVE Deep (5 Flow excluded)", "",
             "| source | method | new(post-dedup) | earliest | latest | note |",
             "|---|---|---|---|---|---|"]
    for slug, method, n, fetchdate, note, lo, hi in rows:
        lines.append(f"| {slug} | {method} | {n} | {lo} | {hi} | {note} |")
    if flags:
        lines += ["", "## FLAGGED / infeasible", ""]
        for s, w in flags:
            lines.append(f"- **{s}** — {w}")
    (RUNLOG_DIR / f"enum-{ts}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- FINAL drain core (12): firehose-5, carbon_brief, wood_mackenzie, all flagged/
#     render/Nature sources EXCLUDED. Also EXCLUDED after the fetch canaries:
#       timmerman_report — paywall teasers (29w median), render won't help (like Nature)
#       ieee_spectrum    — extraction-infeasible: body stays ~50-90w nav-crumbs even
#                          AFTER render-retry (generic extractor can't reach IEEE's DOM)
#     Both would only ever produce sub-word-floor drops, so they are off the core. ---
CORE12 = [
    "anyscale_ray_blog", "bloombergnef_free_content", "cohere_blog", "fabricated_knowledge",
    "hugging_face_blog", "google_ai_blog", "microsoft_research_blog",
    "servethehome", "the_next_platform", "weights_biases_blog",
    "semianalysis", "together_ai_blog",
]


def run_fetch(slugs, start, per_source_cap, session_cap, state_file, dry_run=False):
    """Capped RAW fetch: enumerate (scoped rules) -> dedup -> fetch body+date for up
    to per_source_cap newest in-window per source -> write technology-history/<slug>/
    <id>.json (daily raw shape + backfill:true). Per-site politeness + quarantine.
    Sequential. Returns a per-source diagnostics list for the canary report."""
    deep = _load_deep_active()
    done_path = HIST_ROOT / "_state" / state_file
    try:
        st = json.loads(done_path.read_text())
    except Exception:
        st = {}
    done = set(st.get("done", [])); blocked = dict(st.get("blocked", {}))

    def _save():
        done_path.parent.mkdir(parents=True, exist_ok=True)
        done_path.write_text(json.dumps({"done": sorted(done), "blocked": blocked}, indent=2), encoding="utf-8")

    def cooling(s):
        b = blocked.get(s)
        if not b:
            return False
        try:
            at = datetime.datetime.fromisoformat(b["at"])
            return (datetime.datetime.now(datetime.timezone.utc) - at).total_seconds() < SITE_COOLDOWN_S
        except Exception:
            return True

    log(f"TECHNOLOGY FETCH CANARY — RAW ONLY | start={start} | per_source_cap={per_source_cap} "
        f"| session_cap={session_cap} | sources={len(slugs)} | history={HIST_ROOT}"
        + (" | DRY-RUN" if dry_run else ""))
    HIST_ROOT.mkdir(parents=True, exist_ok=True)
    diags = []; session_fetched = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        cx = browser.new_context(user_agent=ct.USER_AGENT, viewport=ct.DEFAULT_VIEWPORT, ignore_https_errors=True)
        page = cx.new_page(); page.set_default_timeout(ct.PAGE_TIMEOUT_MS)
        for si, slug in enumerate(slugs):
            d = {"slug": slug, "enum": 0, "dedup": 0, "fresh": 0, "fetched": 0, "written": 0,
                 "drop_short": 0, "drop_nodate": 0, "drop_outwin": 0, "render_fired": 0,
                 "render_rescued": 0, "status": "", "samples": [], "wcs": [], "dates": []}
            meta = deep.get(slug)
            if not meta:
                d["status"] = "not-active-Deep"; diags.append(d); continue
            if cooling(slug):
                d["status"] = f"quarantined({blocked[slug].get('reason','')[:24]})"; diags.append(d); continue
            log(f"\n=== [{slug}] ===")
            try:
                method, res, note = detect_and_enumerate(slug, meta, start, page=page)
            except Exception as e:
                d["status"] = f"enum-error {type(e).__name__}"; log(f"  enum ERROR {e}"); diags.append(d); continue
            if isinstance(res, str) and res.startswith("FLAG:"):
                d["status"] = "flagged"; log(f"  FLAGGED: {res[5:]}"); diags.append(d); continue
            d["enum"] = len(res)
            fresh = []
            for url, dt in res:
                if already_known(slug, ct.url_hash(url)):
                    d["dedup"] += 1
                else:
                    fresh.append((url, dt, ct.url_hash(url)))
            d["fresh"] = len(fresh)
            log(f"  method={method} | enum-in-window={d['enum']} | dedup-skip={d['dedup']} | fresh={d['fresh']}")
            if not fresh:
                done.add(slug); _save(); d["status"] = "complete(nothing-new)"; diags.append(d); continue

            consec_fail = 0; blocked_reason = None
            for url, enum_date, rid in fresh[:per_source_cap]:
                if session_fetched >= session_cap:
                    d["status"] = d["status"] or "session-cap"; log("  session cap reached"); break
                try:
                    rec = fetch_article(page, url); consec_fail = 0
                except (PlaywrightTimeout, PlaywrightError) as e:
                    consec_fail += 1
                    log(f"  WARN fetch {url[:55]} — {type(e).__name__} ({consec_fail}/{CONSECUTIVE_FAIL_ABORT})")
                    if consec_fail >= CONSECUTIVE_FAIL_ABORT:
                        blocked_reason = f"{CONSECUTIVE_FAIL_ABORT} consecutive fetch failures ({type(e).__name__})"
                        log(f"  PER-SITE BLOCK [{slug}]: {blocked_reason}"); break
                    sleep(SLEEP_FETCH); continue
                session_fetched += 1; d["fetched"] += 1
                if _BOT_RE.search((rec.get("text") or "")[:400]) or _BOT_RE.search(rec.get("title") or ""):
                    blocked_reason = "429 / bot-check / consent page served"
                    log(f"  PER-SITE BLOCK [{slug}]: {blocked_reason}"); break
                # RENDER-RETRY (generic): SPA/JS sources (W&B, IEEE) return a near-empty
                # static body. If the first fetch is below the daily word-floor, re-fetch
                # ONCE through the Playwright render path (settle+scroll) and keep it if it
                # hydrated more text. Then the floor judges the better of the two.
                if ct.too_short(rec.get("text") or ""):
                    d["render_fired"] += 1
                    before = rec["word_count"]
                    try:
                        rec2 = fetch_article(page, url, render=True)
                        if rec2["word_count"] > rec["word_count"]:
                            rec = rec2
                    except (PlaywrightTimeout, PlaywrightError):
                        pass
                    if not ct.too_short(rec.get("text") or ""):
                        d["render_rescued"] += 1
                        log(f"  render-retry RESCUED {before}w -> {rec['word_count']}w  {rec['title'][:40]}")
                    else:
                        log(f"  render-retry no-rescue {before}w -> {rec['word_count']}w  {rec['title'][:40]}")
                pub = rec["published_date"] or (enum_date or "")
                if rec["published_date"] and rec["published_date"] < start:
                    d["drop_outwin"] += 1
                    log(f"  drop(out-of-window {rec['published_date']}): {rec['title'][:42]}"); sleep(SLEEP_FETCH); continue
                if not pub:
                    d["drop_nodate"] += 1
                    log(f"  drop(no date): {rec['title'][:42]}"); sleep(SLEEP_FETCH); continue
                if ct.too_short(rec.get("text") or ""):   # daily word-floor (MIN_ARTICLE_WORDS)
                    d["drop_short"] += 1
                    log(f"  drop(short<{ct.MIN_ARTICLE_WORDS}w {rec['word_count']}w): {rec['title'][:42]}"); sleep(SLEEP_FETCH); continue
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
                if not dry_run:
                    dd = HIST_ROOT / slug; dd.mkdir(parents=True, exist_ok=True)
                    (dd / f"{rid}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                d["written"] += 1; d["wcs"].append(rec["word_count"]); d["dates"].append(pub)
                if len(d["samples"]) < 2:
                    first = next((ln.strip() for ln in (rec["text"] or "").splitlines() if ln.strip()), "")
                    d["samples"].append((rec["title"], pub, rec["word_count"], first[:140]))
                log(f"  +kept [{pub}] {rec['word_count']:>5}w  {rec['title'][:48]}")
                sleep(SLEEP_FETCH)
            if blocked_reason:
                blocked[slug] = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                 "reason": blocked_reason}
                _save(); d["status"] = f"BLOCKED@{d['written']}"
            else:
                if slug in blocked:
                    blocked.pop(slug, None); _save()
                d["status"] = d["status"] or "drained"
            diags.append(d)
            if si < len(slugs) - 1:
                sleep(SLEEP_SOURCE, "inter-source")
        browser.close()
    return diags


def _report_fetch(diags, start):
    import statistics
    log("\n" + "=" * 86)
    log(f"{'source':<26}{'fetch':>6}{'writ':>5}{'short':>6}{'rndr':>5}{'resc':>5}{'medwc':>7}  status")
    tot = {"enum": 0, "dedup": 0, "fresh": 0, "fetched": 0, "written": 0,
           "drop_short": 0, "render_fired": 0, "render_rescued": 0}
    for d in diags:
        for k in tot:
            tot[k] += d.get(k, 0)
        mwc = int(statistics.median(d["wcs"])) if d["wcs"] else 0
        log(f"  {d['slug']:<24}{d['fetched']:>6}{d['written']:>5}{d['drop_short']:>6}"
            f"{d['render_fired']:>5}{d['render_rescued']:>5}{mwc:>7}  {d['status']}")
    log(f"  {'TOTAL':<24}{tot['fetched']:>6}{tot['written']:>5}{tot['drop_short']:>6}"
        f"{tot['render_fired']:>5}{tot['render_rescued']:>5}")
    RUNLOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    lines = [f"# Technology FETCH CANARY {ts}", f"- start={start} | per_source_cap=12", "",
             "| source | enum | dedup | fresh | fetched | written | drop_short | render_fired | render_rescued | median_wc | date-range | status |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in diags:
        mwc = int(statistics.median(d["wcs"])) if d["wcs"] else 0
        dr = f"{min(d['dates'])}..{max(d['dates'])}" if d["dates"] else "—"
        lines.append(f"| {d['slug']} | {d['enum']} | {d['dedup']} | {d['fresh']} | {d['fetched']} | "
                     f"{d['written']} | {d['drop_short']} | {d['render_fired']} | {d['render_rescued']} | {mwc} | {dr} | {d['status']} |")
    (RUNLOG_DIR / f"fetch-{ts}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default=BACKFILL_START_DEFAULT, help="backfill back to this date (YYYY-MM-DD)")
    ap.add_argument("--enumerate-final", action="store_true",
                    help="signal-tier enumeration across the 27 Deep sources (renders js_listing/index_render)")
    ap.add_argument("--enumerate-only", action="store_true", help="list counts; fetch nothing")
    ap.add_argument("--canary", action="store_true", help="probe a small canary set")
    ap.add_argument("--core", action="store_true", help="FULL DRAIN: the FINAL 12 core analytical sources")
    ap.add_argument("--fetch", action="store_true", help="fetch body+date for --sources (capped)")
    ap.add_argument("--sources", default=None, help="comma-separated slugs")
    ap.add_argument("--per-source-cap", type=int, default=PER_SOURCE_CAP_DEFAULT)
    ap.add_argument("--session-cap", type=int, default=SESSION_CAP_DEFAULT)
    ap.add_argument("--state-file", default="technology_backfill_state.json",
                    help="filename under _state/ for done/blocked")
    ap.add_argument("--dry-run", action="store_true", help="fetch but don't write to history")
    args = ap.parse_args()

    if args.core or args.fetch:
        slugs = CORE12 if args.core else [s.strip() for s in (args.sources or "").split(",") if s.strip()]
        if not slugs:
            ap.error("--fetch requires --sources (or use --core)")
        diags = run_fetch(slugs, args.start, args.per_source_cap, args.session_cap,
                          args.state_file, dry_run=args.dry_run)
        _report_fetch(diags, args.start)
        return

    if args.enumerate_final or args.canary:
        with sync_playwright() as pw:   # js_listing / index_render sources need a render page
            b = pw.chromium.launch(headless=True)
            cx = b.new_context(user_agent=ct.USER_AGENT, viewport=ct.DEFAULT_VIEWPORT, ignore_https_errors=True)
            pg = cx.new_page(); pg.set_default_timeout(ct.PAGE_TIMEOUT_MS)
            if args.canary:
                deep = _load_deep_active()
                pick = [s.strip() for s in args.sources.split(",")] if args.sources else list(deep)[:3]
                log(f"CANARY probe: {pick} | start={args.start}\n")
                for slug in pick:
                    s = deep.get(slug)
                    if not s:
                        log(f"  {slug}: not an active Deep source"); continue
                    method, res, note = detect_and_enumerate(slug, s, args.start, page=pg)
                    if isinstance(res, str) and res.startswith("FLAG:"):
                        log(f"  {slug:<32}{method:<14}  FLAG: {res[5:]}"); continue
                    new = [(u, d) for (u, d) in res if not already_known(slug, ct.url_hash(u))]
                    log(f"  {slug:<32}{method:<14}{len(new):>6} new  ({note or ''})")
            else:
                run_enumerate_final(args.start, page=pg)
            b.close()
        return

    ap.error("specify a mode: --enumerate-final | --canary | --core | --fetch --sources ...")


if __name__ == "__main__":
    main()
