#!/usr/bin/env python3
"""Research PDF Finder — weekly open-web discovery of public research PDFs.

Finds publicly-available full bank / asset-manager research PDFs (outlooks,
house views, chartbooks, weeklies, etc.) using Serper.dev Google search,
filtered down to fresh, on-topic, live documents. LINKS ONLY: we surface PDFs
that are already public on the open web — no download, no summarization, no
paywall circumvention. The reader opens the PDFs himself.

This is a deterministic, NO-LLM sibling to the Institutional Research module
(scripts/collect_institutional.py) and mirrors its funnel diagnostics, layered
date extraction, recency gate and junk filter — but uses a search API instead of
a headless browser, so it is fast and pure-API.

FREE-TIER SERPER NOTE: Serper's free plan REJECTS (HTTP 400 "Query pattern not
allowed for free accounts") any query that uses quoted phrases, the `filetype:`
operator, or the `tbs` freshness param. So queries are built as PLAIN keywords
with "pdf" as an ordinary word, e.g. `Goldman Sachs market outlook pdf`. We lean
entirely on the downstream filters to do the precision work: the post-hoc .pdf
gate, the title/snippet keyword gate, the domain blacklist, and the --days
recency filter (layered date extraction).

DATING & FRESHNESS: Serper rarely returns a date for PDF results, so dates are
extracted in layers (most-trusted first):
  1. Serper organic.date           (PRECISE)
  2. date in the URL path/filename (PRECISE)
  3. year/quarter/season in the TITLE or filename (APPROXIMATE — "Year Ahead
     2023", "Q2 2026", "Spring 2026", "Midyear 2022", "Oct 2025", "2026
     Outlook"); period start, shown with a ~ and an "approx" marker.
  4. nothing -> truly UNKNOWN AGE.
Precise dates are gated by --days. Approximate dates use a coarser window (last
~year + a forward allowance) so provably-old titles (2022-2024) are DROPPED while
current-cycle pieces are KEPT. The report splits kept links into a DATED group
(newest-first) and a separate UNKNOWN-AGE group.

WHITELIST IS A RANKING BOOSTER, NOT A GATE: PDFs from ANY domain are kept.
booster_domains (the house's own domains + known re-host portals, augmented at
runtime from config/institutional_sources.json) merely sort to the top and earn
an "authoritative" marker. Sell-side research is mass-distributed and re-hosted,
so finding already-public PDFs via open-web search is legitimate.

Run:
    SERPER_API_KEY=... python3 scripts/collect_research_pdfs.py --days 45 --dry-run --limit 5
    SERPER_API_KEY=... python3 scripts/collect_research_pdfs.py --days 45 --dry-run
    SERPER_API_KEY=... python3 scripts/collect_research_pdfs.py --days 30
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

# --- Paths ------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "research_pdf_sources.json"
INSTITUTIONAL_CONFIG = REPO_ROOT / "config" / "institutional_sources.json"
TEMPLATE = REPO_ROOT / "templates" / "research_pdfs_report.html"
DATA_ROOT = REPO_ROOT / "data" / "research_pdfs"
REPORTS_DIR = REPO_ROOT / "reports"
LATEST_NAME = "research_pdfs.json"

SERPER_ENDPOINT = "https://google.serper.dev/search"

# --- Tunables ---------------------------------------------------------------
DEFAULT_DAYS = 45              # generous for first runs; 30 steady-state
REQUEST_TIMEOUT = 15           # Serper API call timeout (s)
LINK_CHECK_TIMEOUT = 10        # per-link HEAD/GET timeout (s)
LINK_CHECK_WORKERS = 8         # concurrent link checks
SERPER_NUM = 20               # requested results/query (free tier serves ~10)
SERPER_PAUSE = 0.4            # polite pause between Serper calls (s)
# Approximate (title-derived) dates are coarse, so they get their own window:
APPROX_LOOKBACK_DAYS = 365    # keep title-dated items from the last ~year
APPROX_FORWARD_DAYS = 200     # ...plus forward-dated current-cycle pieces
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Two-label public suffixes we must keep intact when deriving the apex domain.
MULTI_TLDS = (
    "co.uk", "org.uk", "ac.uk", "gov.uk", "co.jp", "com.sg", "com.au",
    "com.hk", "com.cn", "co.in", "ne.jp", "or.jp",
)


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# --- Config -----------------------------------------------------------------
def load_sources():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return [s for s in config.get("sources", []) if s.get("id")]


def institutional_booster_hosts():
    """Apex domains pulled from config/institutional_sources.json urls, used to
    augment the booster set so re-hosts on those houses' own domains rank up."""
    hosts = set()
    if not INSTITUTIONAL_CONFIG.exists():
        return hosts
    try:
        cfg = json.loads(INSTITUTIONAL_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return hosts
    for src in cfg.get("sources", []):
        for url in src.get("urls", []) or []:
            host = host_of(url)
            if host:
                hosts.add(apex_domain(host))
    return hosts


# --- URL / domain helpers ---------------------------------------------------
def host_of(url):
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def apex_domain(host):
    host = (host or "").lower().lstrip(".")
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in MULTI_TLDS:
        return ".".join(labels[-3:])
    return last_two


def norm_url(url):
    """Lowercase host, strip query/fragment and trailing slash for dedup."""
    try:
        p = urlparse(url)
    except Exception:
        return url.lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{p.path.rstrip('/').lower()}"


def host_matches(host, domain):
    """True if host == domain or is a subdomain of it."""
    return host == domain or host.endswith("." + domain)


# --- Filters ----------------------------------------------------------------
# Domains that never carry the actual research PDF (SEO / press / ticker-
# aggregator / filings junk). Re-host MIRRORS that DO carry real PDFs
# (s3.amazonaws.com, *.vercel.app, IR portals e.g. chartnexus.com) are NOT
# blacklisted — later filters (keyword gate, freshness, link check) handle them.
BLACKLIST_DOMAINS = {
    "sec.gov", "businesswire.com", "prnewswire.com", "globenewswire.com",
    "researchandmarkets.com", "finviz.com", "stocktitan.net",
    "marketscreener.com", "financialcontent.com", "zacks.com",
    "benzinga.com", "seekingalpha.com", "marketbeat.com", "fool.com",
    "motleyfool.com", "tipranks.com", "investing.com", "alpha-sense.com",
    "forrester.com", "cfamontreal.org",
}
# Suffix blacklist for wildcard domains (*.finance.yahoo.com etc.).
BLACKLIST_SUFFIXES = ("finance.yahoo.com", "libanswers.com", "libguides.com")
# URL-path fragments that mark course/library/slide/IR-filing junk regardless of
# host. /resultannouncements/, annual-report and investor-presentation kill
# earnings releases and shareholder/IR decks that aren't market research.
BLACKLIST_PATH_TERMS = (
    "virtual-library", "/course", "/slides",
    "/resultannouncements/", "annual-report", "investor-presentation",
)

KEEP_KEYWORDS = (
    "outlook", "macro", "economic", "economics", "strategy", "themes",
    "year ahead", "midyear", "mid-year", "house view", "capital market",
    "market outlook", "investment outlook", "perspectives", "weekly",
    "monthly", "chartbook", "cio", "allocation", "asset allocation",
    "views", "deep dive", "eye on the market", "daily spark", "market regime",
)
# Drop terms: factsheet/legal/filings/IR boilerplate. Note we do NOT blanket-drop
# "earnings" — only "earnings results"/"results presentation" — so legit pieces
# like "Outlook for corporate earnings" survive. The IR/annual-report/risk-monitor
# phrases kill the junk flagged in the first dry-run (Barclays results, Apollo &
# Nomura IR decks, BlackRock risk monitor, Citi family office report).
DROP_KEYWORDS = (
    "factsheet", "fact sheet", "kiid", "kid ", "prospectus", "brochure",
    "nav", "performance summary", "terms of use", "privacy policy",
    "application form", "results presentation", "quarterly results",
    "earnings results", "8-k", "10-k", "10-q", "424b", "fwp",
    "x-17a-5", "proxy statement", "shelf registration",
    "annual report", "investor presentation", "year in review",
    "results at a glance", "market risk monitor", "family office report",
)


def domain_blacklisted(host):
    if not host:
        return True
    if host in BLACKLIST_DOMAINS or apex_domain(host) in BLACKLIST_DOMAINS:
        return True
    return any(host_matches(host, s) for s in BLACKLIST_SUFFIXES)


def path_blacklisted(url):
    path = url.lower()
    return any(term in path for term in BLACKLIST_PATH_TERMS)


def passes_title_gate(title, snippet):
    """KEEP only if the title/snippet hits a research keyword and avoids the
    factsheet/legal/filings drop list."""
    blob = f"{title} {snippet}".lower()
    if any(k in blob for k in DROP_KEYWORDS):
        return False
    return any(k in blob for k in KEEP_KEYWORDS)


def is_pdf_url(url):
    """True if the URL path ends in .pdf (query string ignored)."""
    return urlparse(url).path.lower().endswith(".pdf")


# --- Date handling ----------------------------------------------------------
ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
REL_RE = re.compile(r"(\d+)\s+(hour|day|week|month|year)s?\s+ago", re.I)


def parse_serper_date(raw, today):
    """Parse Serper's freeform organic.date to an ISO date string, else None.
    Handles '3 days ago', 'May 28, 2026', '2026-05-28', '28 May 2026'."""
    if not raw:
        return None
    raw = raw.strip()
    m = REL_RE.search(raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        delta = {
            "hour": datetime.timedelta(hours=n),
            "day": datetime.timedelta(days=n),
            "week": datetime.timedelta(weeks=n),
            "month": datetime.timedelta(days=30 * n),
            "year": datetime.timedelta(days=365 * n),
        }[unit]
        return (today - delta).isoformat()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y",
                "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    m = ISO_RE.search(raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def date_from_url(url):
    """Extract a PRECISE date embedded in the URL path or filename, else None.
    Handles /YYYY/MM/DD/, /YYYY/MM/, YYYYMMDD, _MM-DD-YYYY, _YYYY_MM, etc."""
    u = url.lower()
    # /YYYY/MM/DD/ or /YYYY/MM/
    m = re.search(r"/(20\d{2})/(\d{1,2})(?:/(\d{1,2}))?(?:[/_.-]|$)", u)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)),
                                 int(m.group(3) or 1)).isoformat()
        except ValueError:
            pass
    # _YYYYMMDD / -YYYYMMDD / YYYYMMDD (8 contiguous digits)
    m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", u)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)),
                                 int(m.group(3))).isoformat()
        except ValueError:
            pass
    # _MM-DD-YYYY / _M-D-YYYY (US filename style)
    m = re.search(r"(?<!\d)(\d{1,2})[-_](\d{1,2})[-_](20\d{2})(?!\d)", u)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(1)),
                                 int(m.group(2))).isoformat()
        except ValueError:
            pass
    # _YYYY_MM / -YYYY-MM (month granularity)
    m = re.search(r"(?<!\d)(20\d{2})[_-](\d{1,2})(?!\d)", u)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), 1).isoformat()
        except ValueError:
            pass
    return None


# Title/filename year–quarter–season parser (APPROXIMATE dates). Sits ABOVE the
# truly-undated fallback: many research PDFs carry no Serper/URL date but DO name
# their period in the title or filename. Quarter/season/month -> period start;
# midyear -> Jul 1; bare year -> Jan 1.
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_SEASON_MONTH = {"spring": 3, "summer": 6, "autumn": 9, "fall": 9, "winter": 12}
_YR = r"((?:20)[1-3]\d)"   # 2010–2039
_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)[\s\-_/.]*" + _YR + r"\b", re.I)
_QUARTER_RE = re.compile(
    r"\bq([1-4])[\s\-_/]*" + _YR + r"\b|\b" + _YR + r"[\s\-_/]*q([1-4])\b", re.I)
_SEASON_RE = re.compile(
    r"\b(spring|summer|autumn|fall|winter)[\s\-_/]*" + _YR + r"\b", re.I)
_MIDYEAR_RE = re.compile(
    r"\b(?:mid[\s\-]?year|half[\s\-]?year)[\s\-_/]*" + _YR + r"\b|\b" + _YR +
    r"[\s\-_/]*(?:mid[\s\-]?year|half[\s\-]?year)\b", re.I)
_BAREYEAR_RE = re.compile(r"\b" + _YR + r"\b")


def _mk(year, month):
    y = int(year)
    if 2010 <= y <= 2035:
        try:
            return datetime.date(y, month, 1).isoformat()
        except ValueError:
            return None
    return None


def date_from_title(text):
    """Approximate ISO date (period start) from a title/filename, else None."""
    if not text:
        return None
    # Underscores are word chars, so \b won't fire across them (e.g.
    # "fels_oct2021"); normalize to spaces so filename tokens parse too.
    t = text.lower().replace("_", " ")
    m = _MONTH_RE.search(t)            # most specific: month + year
    if m:
        d = _mk(m.group(2), _MONTHS[m.group(1)[:3]])
        if d:
            return d
    m = _QUARTER_RE.search(t)          # quarter + year (either order)
    if m:
        q = m.group(1) or m.group(4)
        y = m.group(2) or m.group(3)
        d = _mk(y, (int(q) - 1) * 3 + 1)
        if d:
            return d
    m = _SEASON_RE.search(t)           # season + year
    if m:
        d = _mk(m.group(2), _SEASON_MONTH[m.group(1).lower()])
        if d:
            return d
    m = _MIDYEAR_RE.search(t)          # midyear/half-year + year -> Jul 1
    if m:
        d = _mk(m.group(1) or m.group(2), 7)
        if d:
            return d
    m = _BAREYEAR_RE.search(t)         # bare year -> Jan 1
    if m:
        d = _mk(m.group(1), 1)
        if d:
            return d
    return None


def extract_date(organic_date, url, title, today):
    """Layered date extraction. Returns (iso_date, source) where source is one
    of: 'serper' / 'url' (PRECISE real dates), 'title' (APPROXIMATE — from the
    title or filename year/quarter/season), or None (truly undated)."""
    iso = parse_serper_date(organic_date, today)
    if iso:
        return iso, "serper"
    iso = date_from_url(url)
    if iso:
        return iso, "url"
    iso = date_from_title(title)
    if iso:
        return iso, "title"
    fname = urlparse(url).path.rsplit("/", 1)[-1]
    iso = date_from_title(fname)
    if iso:
        return iso, "title"
    return None, None


def within_days(iso_date, days, today):
    """Strict recency gate for PRECISE dates: kept if 0 <= age <= days."""
    if not iso_date:
        return False
    try:
        d = datetime.date.fromisoformat(iso_date)
    except ValueError:
        return False
    return 0 <= (today - d).days <= days


def within_approx_window(iso_date, today):
    """Coarse recency gate for APPROXIMATE (title-derived) dates: kept if within
    the last ~year plus a forward allowance for current-cycle pieces. Wider than
    within_days() because the granularity is only year/quarter/season — this is
    what drops 'Year Ahead 2023' / 'outlook-2024' while keeping 'Q2 2026'."""
    if not iso_date:
        return False
    try:
        d = datetime.date.fromisoformat(iso_date)
    except ValueError:
        return False
    lo = today - datetime.timedelta(days=APPROX_LOOKBACK_DAYS)
    hi = today + datetime.timedelta(days=APPROX_FORWARD_DAYS)
    return lo <= d <= hi


def date_bucket(iso_date, today):
    """Coarse recency bucket for the date-spread diagnostic: one of
    'lt30' (<30d, incl. future-dated), 'd30_90' (30-90d), 'gt90' (>90d),
    'undated'."""
    if not iso_date:
        return "undated"
    try:
        d = datetime.date.fromisoformat(iso_date)
    except ValueError:
        return "undated"
    age = (today - d).days
    if age < 30:
        return "lt30"
    if age <= 90:
        return "d30_90"
    return "gt90"


# --- Serper search ----------------------------------------------------------
def serper_search(query, api_key, stats=None):
    """One Serper search; returns the organic list (may be empty). Never raises
    — a failed query is logged and treated as zero results.

    Queries MUST be plain keywords: the free tier 400s on quotes / filetype: /
    tbs (see module docstring). When `stats` (a dict) is given, the HTTP outcome
    is tallied: stats['q200'] / stats['q400'] / stats['qother'] / stats['qerr']
    so we can confirm the free tier is actually serving these plain queries."""
    body = {"q": query, "num": SERPER_NUM, "gl": "us", "hl": "en"}
    try:
        resp = requests.post(
            SERPER_ENDPOINT, json=body, timeout=REQUEST_TIMEOUT,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )
        if stats is not None:
            if resp.status_code == 200:
                stats["q200"] = stats.get("q200", 0) + 1
            elif resp.status_code == 400:
                stats["q400"] = stats.get("q400", 0) + 1
            else:
                stats["qother"] = stats.get("qother", 0) + 1
        resp.raise_for_status()
        return resp.json().get("organic", []) or []
    except Exception as exc:
        # Network/timeout/parse errors (not an HTTP status we already counted).
        if stats is not None and not isinstance(exc, requests.HTTPError):
            stats["qerr"] = stats.get("qerr", 0) + 1
        log(f"    WARN serper query failed ({type(exc).__name__}): {query}")
        return []


# --- Dead-link check --------------------------------------------------------
def check_link(url):
    """True if the URL resolves to a live PDF (HTTP 200 + pdf content-type, or
    a %PDF magic-byte body). Tries HEAD first, falls back to a ranged GET."""
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.head(url, headers=headers, timeout=LINK_CHECK_TIMEOUT,
                          allow_redirects=True)
        ctype = r.headers.get("Content-Type", "").lower()
        if r.status_code == 200 and ("pdf" in ctype or
                                     (is_pdf_url(url) and "html" not in ctype)):
            return True
    except Exception:
        pass
    # Fallback: ranged GET — many servers reject HEAD or omit content-type.
    try:
        r = requests.get(url, headers={**headers, "Range": "bytes=0-1023"},
                         timeout=LINK_CHECK_TIMEOUT, allow_redirects=True,
                         stream=True)
        if r.status_code not in (200, 206):
            return False
        ctype = r.headers.get("Content-Type", "").lower()
        chunk = next(r.iter_content(1024), b"") or b""
        r.close()
        if "pdf" in ctype:
            return True
        if chunk[:5] == b"%PDF-":
            return True
        return False
    except Exception:
        return False


def check_links(items):
    """Annotate each item with item['alive'] (bool) concurrently."""
    with ThreadPoolExecutor(max_workers=LINK_CHECK_WORKERS) as pool:
        futures = {pool.submit(check_link, it["url"]): it for it in items}
        for fut in as_completed(futures):
            it = futures[fut]
            try:
                it["alive"] = fut.result()
            except Exception:
                it["alive"] = False
    return items


# --- Funnel -----------------------------------------------------------------
FUNNEL_KEYS = (
    "queries", "raw", "pdf", "blacklist", "titlegate", "freshness",
    "dedup", "linkcheck", "kept",
)
DATE_SPREAD_KEYS = ("lt30", "d30_90", "gt90", "undated")


def _date_sort_key(iso):
    """Numeric sort key that puts newer dates first (more negative = newer).
    Empty/undated -> 0; the undated flag in the sort tuple already pushes those
    after all dated items within the same booster group."""
    try:
        return -datetime.date.fromisoformat(iso).toordinal()
    except (ValueError, TypeError):
        return 0


def _rel(path):
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"freshness window in days (default: {DEFAULT_DAYS})")
    ap.add_argument("--drop-undated", action="store_true",
                    help="exclude PDFs with no extractable date (kept by default)")
    ap.add_argument("--no-check-links", action="store_true",
                    help="skip the dead-link / pdf-content-type check")
    ap.add_argument("--limit", type=int, default=None,
                    help="only process the first N sources (for testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="write to /tmp and print a summary; no repo writes")
    args = ap.parse_args()

    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        sys.exit("ERROR: SERPER_API_KEY not set (env var / GitHub secret).")

    sources = load_sources()
    if args.limit:
        sources = sources[:args.limit]
    if not sources:
        sys.exit("ERROR: no sources loaded from config.")

    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date()
    boosters = institutional_booster_hosts()
    for s in load_sources():
        for d in s.get("booster_domains", []):
            boosters.add(d.lower())

    log(f"Research PDF Finder: {len(sources)} source(s), window {args.days}d "
        f"(plain free-tier queries, no tbs); {len(boosters)} booster domains; "
        f"link-check={'off' if args.no_check_links else 'on'}; "
        f"undated={'drop' if args.drop_undated else 'keep'}")

    funnels = {s["id"]: {k: 0 for k in FUNNEL_KEYS} for s in sources}
    # Diagnostics: HTTP outcome of every Serper call, the recency spread of all
    # PDF candidates BEFORE the freshness filter, and how many previously-undated
    # items the title parser newly dropped as provably-old.
    query_stats = {"q200": 0, "q400": 0, "qother": 0, "qerr": 0}
    date_spread = {k: 0 for k in DATE_SPREAD_KEYS}
    title_dropped_old = 0
    blacklist_drops = []   # diagnostic: every item the blacklist removed
    seen_urls = set()
    kept = []   # accumulated across all sources

    for i, src in enumerate(sources, 1):
        sid = src["id"]
        name = src["name"]
        terms = src.get("query_terms", []) or []
        f = funnels[sid]
        # Per-source near-dup-by-title map: norm_title -> chosen item. Items with
        # an empty normalized title bypass this map and are collected directly.
        by_title = {}
        untitled = []

        log(f"[{i}/{len(sources)}] {sid} ({name}): {len(terms)} term(s)")
        for term in terms:
            # FREE-TIER: plain keywords only — no quotes, no filetype:, no tbs.
            query = f"{name} {term} pdf"
            f["queries"] += 1
            organic = serper_search(query, api_key, query_stats)
            time.sleep(SERPER_PAUSE)
            for o in organic:
                url = (o.get("link") or "").strip()
                if not url:
                    continue
                f["raw"] += 1
                host = host_of(url)

                # (a) PDF gate. Non-.pdf URLs survive only if link-checking is on
                # (the check will confirm/deny the pdf content-type); with checks
                # off we keep only explicit .pdf links.
                if not is_pdf_url(url) and args.no_check_links:
                    continue
                f["pdf"] += 1

                # (b) domain / path blacklist
                if domain_blacklisted(host) or path_blacklisted(url):
                    f["blacklist"] += 1
                    blacklist_drops.append({
                        "source": name, "domain": host,
                        "title": (o.get("title") or "").strip(), "url": url})
                    continue

                # (c) title/snippet keyword gate
                title = (o.get("title") or "").strip()
                snippet = (o.get("snippet") or "").strip()
                if not passes_title_gate(title, snippet):
                    f["titlegate"] += 1
                    continue

                # (d) freshness — layered date extraction + post-hoc recency.
                # date_source: serper/url (PRECISE) -> --days gate; title
                # (APPROXIMATE) -> coarser window; None -> kept unless
                # --drop-undated. Record the recency bucket of every candidate
                # reaching this stage (pre-drop) for the date-spread diagnostic.
                iso, dsrc = extract_date(o.get("date"), url, title, today)
                approx = (dsrc == "title")
                undated = iso is None
                date_spread[date_bucket(iso, today)] += 1
                if undated:
                    if args.drop_undated:
                        f["freshness"] += 1
                        continue
                elif approx:
                    if not within_approx_window(iso, today):
                        # Newly droppable: precise layers found nothing, but the
                        # title/filename names a provably-old period.
                        f["freshness"] += 1
                        title_dropped_old += 1
                        continue
                elif not within_days(iso, args.days, today):
                    f["freshness"] += 1
                    continue

                # (e) dedup — global by normalized URL, then per-source by title
                key = norm_url(url)
                if key in seen_urls:
                    f["dedup"] += 1
                    continue
                booster = any(host_matches(host, d) for d in boosters)
                item = {
                    "source_id": sid,
                    "source": name,
                    "title": title or url.rsplit("/", 1)[-1],
                    "date": iso or "",
                    "date_source": dsrc or "none",
                    "approx": approx,
                    "url": url,
                    "domain": host,
                    "booster": booster,
                    "undated": undated,
                }
                tkey = re.sub(r"[^a-z0-9]+", " ", item["title"].lower()).strip()
                if not tkey:
                    seen_urls.add(key)
                    untitled.append(item)
                    continue
                prev = by_title.get(tkey)
                if prev is not None:
                    # Near-dup same report on another host: prefer booster, then
                    # dated. Keep the better one, drop the other.
                    better = (booster and not prev["booster"]) or \
                             (booster == prev["booster"] and not undated
                              and prev["undated"])
                    f["dedup"] += 1
                    if not better:
                        continue
                    seen_urls.discard(norm_url(prev["url"]))
                seen_urls.add(key)
                by_title[tkey] = item

        # collect this source's surviving items (post per-source title dedup)
        src_items = list(by_title.values()) + untitled
        kept.extend(src_items)
        f["kept"] = len(src_items)

    # --- dead-link check (default ON) ---
    if not args.no_check_links and kept:
        log(f"Checking {len(kept)} link(s) for live PDF content-type...")
        check_links(kept)
        for it in kept:
            if not it.get("alive"):
                funnels[it["source_id"]]["linkcheck"] += 1
                funnels[it["source_id"]]["kept"] -= 1
        kept = [it for it in kept if it.get("alive")]
    for it in kept:
        it.pop("alive", None)

    # --- RANK: dated first (newest first), undated last. booster is a LABEL
    # ONLY — it no longer affects ordering (off-house items are not suppressed).
    kept.sort(key=lambda it: (
        it["undated"],              # dated before undated
        _date_sort_key(it["date"]),  # newest first
    ))

    # --- by-source counts + kept date breakdown / age distribution ---
    by_source = {}
    kept_breakdown = {"real": 0, "title": 0, "unknown": 0}
    kept_age = {k: 0 for k in DATE_SPREAD_KEYS}
    for it in kept:
        by_source[it["source_id"]] = by_source.get(it["source_id"], 0) + 1
        if it["undated"]:
            kept_breakdown["unknown"] += 1
        elif it["approx"]:
            kept_breakdown["title"] += 1
            kept_age[date_bucket(it["date"], today)] += 1
        else:
            kept_breakdown["real"] += 1
            kept_age[date_bucket(it["date"], today)] += 1
    kept_age_dist = {k: kept_age[k] for k in ("lt30", "d30_90", "gt90")}

    collected_at = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_str = now.strftime("%Y-%m-%d")
    payload = {
        "collected_at": collected_at,
        "lookback_days": args.days,
        "total": len(kept),
        "sources_processed": len(sources),
        "by_source": by_source,
        "query_stats": query_stats,
        "date_spread": date_spread,
        "kept_breakdown": kept_breakdown,
        "kept_age_dist": kept_age_dist,
        "title_parser_newly_dropped": title_dropped_old,
        "blacklist_drops": blacklist_drops,
        "items": kept,
    }

    # --- output locations (dry-run -> /tmp) ---
    if args.dry_run:
        base = Path("/tmp/research_pdfs_dryrun")
        latest_dir = base / "latest"
        archive_dir = base / date_str
        report_path = base / f"research_pdfs_{date_str}.html"
    else:
        latest_dir = DATA_ROOT / "latest"
        archive_dir = DATA_ROOT / date_str
        report_path = REPORTS_DIR / f"research_pdfs_{date_str}.html"
    latest_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # latest: compact; archive: pretty
    (latest_dir / LATEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    (archive_dir / LATEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- funnel.json / funnel.txt ---
    diag = {
        "title_parser_newly_dropped": title_dropped_old,
        "kept_breakdown": kept_breakdown,
        "kept_age_dist": kept_age_dist,
    }
    write_funnel(archive_dir, collected_at, funnels, query_stats, date_spread,
                 diag)

    # --- RENDER report ---
    render_report(payload, report_path)

    # --- summary ---
    log("=" * 60)
    log(f"DONE: {len(kept)} PDF(s) from {len(by_source)} source(s)")
    for sid in sorted(by_source, key=lambda k: -by_source[k]):
        log(f"  {sid:<28}{by_source[sid]}")
    zero = [s["id"] for s in sources if by_source.get(s["id"], 0) == 0]
    if zero:
        log(f"Zero-output sources ({len(zero)}) — tune query_terms/domains:")
        log("  " + ", ".join(zero))
    qs = query_stats
    log(f"Serper calls: {sum(qs.values())} "
        f"(200={qs['q200']}, 400={qs['q400']}, other={qs['qother']}, err={qs['qerr']})")
    ds = date_spread
    log(f"Date spread of PDF candidates (pre-freshness): "
        f"<30d={ds['lt30']}, 30-90d={ds['d30_90']}, >90d={ds['gt90']}, "
        f"undated={ds['undated']}")
    kb = kept_breakdown
    log(f"Kept by date source: real={kb['real']}, title-derived={kb['title']}, "
        f"unknown-age={kb['unknown']}")
    log(f"Title parser newly DROPPED (no precise date, title says old): "
        f"{title_dropped_old}")
    ka = kept_age_dist
    log(f"Kept DATED age dist: <30d={ka['lt30']}, 30-90d={ka['d30_90']}, "
        f">90d={ka['gt90']}")
    log(f"Latest:  {_rel(latest_dir / LATEST_NAME)}")
    log(f"Archive: {_rel(archive_dir / LATEST_NAME)}")
    log(f"Report:  {_rel(report_path)}")
    if args.dry_run:
        log("DRY-RUN: wrote to /tmp only; no repo files changed, no commit.")


def write_funnel(out_dir, collected_at, funnels, query_stats=None,
                 date_spread=None, diag=None):
    cols = list(FUNNEL_KEYS)
    width = max((len(s) for s in funnels), default=6) + 2
    header = f"{'source':<{width}}" + "".join(f"{h:>11}" for h in cols)
    lines = [header, "-" * len(header)]
    for sid in sorted(funnels, key=lambda k: (funnels[k]["kept"], k)):
        row = funnels[sid]
        lines.append(f"{sid:<{width}}" + "".join(f"{row[c]:>11}" for c in cols))
    if query_stats is not None:
        lines.append("")
        lines.append(f"serper calls: {sum(query_stats.values())}  "
                     f"200={query_stats['q200']} 400={query_stats['q400']} "
                     f"other={query_stats['qother']} err={query_stats['qerr']}")
    if date_spread is not None:
        lines.append(f"date spread (pre-freshness): <30d={date_spread['lt30']} "
                     f"30-90d={date_spread['d30_90']} >90d={date_spread['gt90']} "
                     f"undated={date_spread['undated']}")
    if diag is not None:
        kb = diag["kept_breakdown"]
        ka = diag["kept_age_dist"]
        lines.append(f"kept by source: real={kb['real']} "
                     f"title-derived={kb['title']} unknown-age={kb['unknown']}")
        lines.append(f"kept dated age: <30d={ka['lt30']} 30-90d={ka['d30_90']} "
                     f">90d={ka['gt90']}")
        lines.append("title parser newly dropped (was undated, title old): "
                     f"{diag['title_parser_newly_dropped']}")
    table = "\n".join(lines)
    print(table)
    (out_dir / "funnel.txt").write_text(table + "\n", encoding="utf-8")
    (out_dir / "funnel.json").write_text(json.dumps({
        "collected_at": collected_at,
        "columns": cols,
        "notes": [
            "queries  = Serper calls (sources x query_terms).",
            "raw      = organic results returned across all queries.",
            "pdf      = passed the .pdf gate (or kept for link-check confirm).",
            "blacklist= dropped by domain/path blacklist.",
            "titlegate= dropped by the title/snippet keyword gate.",
            "freshness= dropped as out-of-window (precise>--days, approx>~1yr, "
            "or undated with --drop-undated).",
            "dedup    = dropped as duplicate URL or near-dup title.",
            "linkcheck= dropped by the dead-link / pdf-content-type check.",
            "kept     = PDFs written to output.",
            "query_stats = HTTP outcome of each Serper call (free-tier 400 check).",
            "date_spread = recency buckets of PDF candidates BEFORE the freshness "
            "filter.",
            "kept_breakdown = kept items by date source (real=serper/url, "
            "title-derived=approx, unknown-age=no date anywhere).",
            "kept_age_dist = age buckets of the kept DATED items.",
            "title_parser_newly_dropped = previously-undated items dropped because "
            "the title/filename names a provably-old period.",
        ],
        "query_stats": query_stats or {},
        "date_spread": date_spread or {},
        "kept_breakdown": (diag or {}).get("kept_breakdown", {}),
        "kept_age_dist": (diag or {}).get("kept_age_dist", {}),
        "title_parser_newly_dropped": (diag or {}).get(
            "title_parser_newly_dropped", 0),
        "sources": funnels,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def render_report(payload, report_path):
    """Substitute the payload JSON into the __REPORT_DATA__ placeholder, the
    same mechanism as publish_institutional.py / institutional_report.html."""
    if not TEMPLATE.exists():
        log(f"WARN: template missing ({_rel(TEMPLATE)}); skipping report render")
        return
    template = TEMPLATE.read_text(encoding="utf-8")
    raw = json.dumps(payload, ensure_ascii=False)
    html = template.replace("__REPORT_DATA__", raw)
    if "__REPORT_DATA__" in html:
        log("ERROR: placeholder __REPORT_DATA__ still present after substitution")
        return
    report_path.write_text(html, encoding="utf-8")
    log(f"wrote {_rel(report_path)} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
