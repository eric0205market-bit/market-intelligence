#!/usr/bin/env python3
"""Weekly institutional-research scraper for the Market Intelligence platform.

Reads config/institutional_sources.json, visits each source's listing/index
pages with headless Chromium (Playwright), follows links that look like fresh
articles/reports, and keeps the ones published within the lookback window
(default 7 days). For every kept article it extracts title, publication date,
main body text, and content images.

Output (UTC-dated):
  raw/institutional/YYYY-MM-DD/articles.json
      full, pretty archive of the UNIONED set for this date (this run's
      harvest merged by URL with any existing same-date file — see FIX 3
      below; never wholesale-replaced without --force)
  data/institutional/latest/articles_institutional.json
      compact, empty-field-stripped, routine-ready mirror, REBUILT from the
      date directory above (not from this run's harvest alone)

Write safety (institutional write-safety audit, 2026-07): a second same-day
collect is common (this stream can be triggered by both an external
workflow_dispatch and the GitHub Actions `schedule` cron). This script used to
wholesale-overwrite both output files every run, silently losing or degrading
articles a prior run had already captured. It now:
  FIX 1 — rejects a fetch whose HTTP status is >= 400 before its body is ever
          treated as content, plus a length-gated block-page marker check for
          WAF challenges served at 200 (see BLOCKPAGE_RE).
  FIX 2 — replaces the old 100-CHARACTER junk floor (which filtered almost
          nothing against this stream's ~765-word median article) with a
          calibrated multi-rule floor: MIN_WORD_COUNT, paywall/login-prompt
          detection, GDPR-consent-page detection, and a JSON/metadata-blob
          density check. See classify_reject() and the comments above it for
          the evidence each threshold was calibrated against.
  FIX 3 — unions this run's harvest with any existing same-date raw archive
          by URL (union_articles()), keeping the higher-word_count QUALIFYING
          version on collision. latest/ is always rebuilt from the resulting
          date-directory file, never unioned into directly (it isn't
          date-scoped, so merging into it would accumulate forever).

The scraper is defensive: a source that times out, blocks, or errors is logged
as a warning and skipped — the run never crashes.

Setup:
    pip install playwright && playwright install chromium

Run:
    python3 scripts/collect_institutional.py
    python3 scripts/collect_institutional.py --ids goldman_sachs,jpmorgan
    python3 scripts/collect_institutional.py --budget 180   # per-source seconds
    python3 scripts/collect_institutional.py --force        # skip the union;
                                                              # this run's
                                                              # harvest alone
                                                              # becomes raw+latest
"""

import argparse
import datetime
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# --- Paths ------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "institutional_sources.json"
RAW_ROOT = REPO_ROOT / "raw" / "institutional"
LATEST_DIR = REPO_ROOT / "data" / "institutional" / "latest"
LATEST_NAME = "articles_institutional.json"

# --- Tunables ---------------------------------------------------------------
LOOKBACK_DAYS = 7             # only keep articles published within this window
PAGE_TIMEOUT_MS = 10_000      # 10s per page navigation
SOURCE_TIMEOUT_S = 120        # 120s wall-clock budget per source (--budget overrides)
INDEX_PHASE_S = 60            # cap index-page crawling so articles get budget too
# bank_bulge sources have far more listing pages, so give them a larger budget.
BULGE_SOURCE_TIMEOUT_S = 300
BULGE_INDEX_PHASE_S = 120
PAGE_DELAY_S = 2              # polite delay between page visits
MAX_INDEX_PAGES = 10          # don't crawl more than this many index pages/source
MAX_ARTICLES_PER_SOURCE = 30  # safety cap so one source can't run away
MIN_IMAGE_WIDTH = 200         # skip icons/logos below this width
DEFAULT_VIEWPORT = {"width": 1366, "height": 900}
RETRY_VIEWPORT = {"width": 1280, "height": 800}  # used only on navigation retry
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Two-label public suffixes we must keep intact when deriving the apex domain.
MULTI_TLDS = (
    "co.uk", "org.uk", "ac.uk", "gov.uk",
    "com.sg", "com.au", "co.jp", "co.in", "com.hk", "com.cn",
)

EXT_RE = re.compile(r"\.(html?|aspx|php)$", re.I)
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
PURE_NUM_RE = re.compile(r"^\d+$")

# Date strings, tried in order, after an ISO attempt. 4-digit-year forms come
# first so they win over the 2-digit-year fallbacks (e.g. "29/04/25").
DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
    "%Y.%m.%d", "%d.%m.%Y", "%m.%d.%Y",
    "%B %d, %Y", "%B %d %Y", "%d %B %Y", "%d %B, %Y",
    "%b %d, %Y", "%b %d %Y", "%d %b %Y", "%d %b, %Y",
    "%m/%d/%y", "%d/%m/%y", "%d.%m.%y",
)
# Free-text date patterns (used only when no metadata date is found).
TEXT_DATE_RES = (
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b([A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})\b"),  # May 28, 2026
    re.compile(r"\b(\d{1,2}\s+[A-Z][a-z]{2,8}\.?\s+\d{4})\b"),    # 28 May 2026
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),                   # 05/28/2026
    re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b"),                 # 28.05.2026
)
# A date sitting next to an explicit label, e.g. "Published: May 28, 2026".
LABEL_DATE_RE = re.compile(
    r"(?:published|posted|date|updated|last\s+updated)\s*[:\-]?\s*"
    r"([A-Za-z0-9.,/ -]{6,20})",
    re.I,
)
# A date encoded directly in the URL path, e.g. /2026/05/28/.
URL_DATE_RE = re.compile(r"/(19\d{2}|20\d{2})/(\d{1,2})/(\d{1,2})(?:[/?#.]|$)")

# JS run inside each article page to pull everything in one round trip.
EXTRACT_JS = r"""
() => {
  const contentSelectors = [
    'article', 'main', '[role=main]', '.article-body', '.post-body',
    '.entry-content', '.article__body', '.article-content', '.post-content',
    '.content', '#content', '.rich-text', '.body-content'
  ];
  let main = null;
  for (const sel of contentSelectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText && el.innerText.trim().length > 200) { main = el; break; }
  }
  if (!main) main = document.body;

  // --- text: strip chrome from a clone of the main element ---
  const clone = main.cloneNode(true);
  clone.querySelectorAll(
    'nav,header,footer,aside,script,style,noscript,form,iframe,button,' +
    '.nav,.menu,.sidebar,.footer,.header,.advert,.advertisement,.ad,' +
    '.cookie,.newsletter,.subscribe,.share,.social,.related,.breadcrumb'
  ).forEach(e => e.remove());
  let text = (clone.innerText || '');
  text = text.replace(/[ \t ]+/g, ' ');  // collapse spaces/tabs/nbsp
  text = text.replace(/ *\n */g, '\n');        // trim around newlines
  text = text.replace(/\n{3,}/g, '\n\n').trim(); // at most one blank line

  // --- images: content imgs wider than the icon threshold ---
  const seen = new Set();
  const images = [];
  main.querySelectorAll('img').forEach(img => {
    const src = img.currentSrc || img.src || '';
    if (!src || src.startsWith('data:')) return;
    if (/logo|icon|sprite|favicon|avatar|placeholder|pixel|spacer/i.test(src)) return;
    const w = img.naturalWidth || img.clientWidth ||
              parseInt(img.getAttribute('width') || '0', 10) || 0;
    if (w && w <= __MIN_W__) return;       // known and too small -> skip
    if (seen.has(src)) return;
    seen.add(src);
    images.push(src);
  });

  // --- title ---
  const ogTitle = document.querySelector('meta[property="og:title"]');
  const h1 = document.querySelector('h1');
  const title = ((ogTitle && ogTitle.content) || (h1 && h1.innerText) ||
                 document.title || '').trim();

  // --- date: meta tags -> <time> -> JSON-LD ---
  let date = '';
  const metaSel = [
    'meta[property="article:published_time"]',
    'meta[name="article:published_time"]',
    'meta[property="og:article:published_time"]',
    'meta[name="datePublished"]',
    'meta[itemprop="datePublished"]',
    'meta[name="date"]',
    'meta[name="pubdate"]',
    'meta[name="publish-date"]',
    'meta[name="publishdate"]',
    'meta[name="dc.date"]',
    'meta[name="dcterms.created"]'
  ];
  for (const s of metaSel) {
    const m = document.querySelector(s);
    if (m && m.content) { date = m.content; break; }
  }
  if (!date) {
    const t = document.querySelector('time[datetime]');
    if (t) date = t.getAttribute('datetime') || (t.innerText || '');
  }
  if (!date) {
    for (const sc of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        let j = JSON.parse(sc.textContent);
        const nodes = Array.isArray(j) ? j.slice() : [j];
        while (nodes.length) {
          const o = nodes.shift();
          if (!o || typeof o !== 'object') continue;
          if (o.datePublished) { date = o.datePublished; break; }
          if (Array.isArray(o['@graph'])) nodes.push(...o['@graph']);
        }
      } catch (e) {}
      if (date) break;
    }
  }
  return { title, text, images: images.slice(0, 20), date_raw: (date || '').trim() };
}
""".replace("__MIN_W__", str(MIN_IMAGE_WIDTH))


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def strip_empty(article):
    """Article copy with empty fields removed (None, "", [], {})."""
    return {k: v for k, v in article.items() if v not in (None, "", [], {})}


# --- Junk filter ------------------------------------------------------------
# Boilerplate/legal/recruiting pages that slip through as "articles".
JUNK_TITLE_TERMS = (
    "privacy", "cookie", "terms", "disclaimer", "contact us", "careers",
    "our people", "leadership", "diversity", "inclusion", "legal information",
)
# Listing pages whose title ends with one of these.
JUNK_TITLE_SUFFIXES = ("articles & insights", "articles and insights")
# URL path fragments that mark a page as product/recruiting/legal boilerplate
# rather than research.
JUNK_URL_TERMS = (
    "/legal/", "/privacy/", "/cookie/", "/terms/", "/careers/", "/contact/",
    "/college-savings", "/529-", "/401k", "/everyday-", "/retirement-planning",
    "/commercial-real-estate", "/restaurant-finance", "/franchise-loans",
    "/municipal-banking", "/equipment-financing", "/fraud-protection",
    "/treasury-management", "/payables", "/receivables", "/commercial-loans",
    "/what-we-do/goldman-sachs-global-institute", "/our-firm/", "/who-we-are",
    "/terms-and-conditions", "/privacy", "/cookie", "/legal/",
)
MIN_TEXT_LEN = 100   # legacy char floor — kept only as a NEVER-negative backstop;
                      # see MIN_WORD_COUNT below for the real content floor.

# --- Content floor (write-safety audit, 2026-07) -----------------------------
# MIN_TEXT_LEN (100 chars =~ 15-20 words) filtered almost nothing against this
# stream's ~765-word median article. Calibrated against real raw pulled from
# git history (institutional write-safety audit): the bottom of the kept
# distribution was bare login prompts (yardeni_research, 19 words), explicit
# paywall notices (gavekal, 23 words), nav-menu chrome (moodys_analytics,
# 21 words) and a GDPR consent notice (world_bank, 24 words) — ALL below 25
# words. Nothing genuine was found below 30 words in a full hand review of
# every kept article <=80 words. MIN_WORD_COUNT sits at 25: excludes the
# hand-verified-100%-junk bottom slice, keeps everything hand-verified real.
MIN_WORD_COUNT = 25

# Block-page / WAF-challenge signatures. LENGTH-GATED, not marker-alone: during
# calibration a genuine 3,288-word galaxy.com article about API "rate limits"
# matched a naive rate-limit regex. Historical block pages captured by this
# collector ran 15-120 words (Cloudflare "Sorry, you have been blocked" +
# Ray ID on opec/carlyle/wisdomtree; CloudFront "request could not be
# satisfied" on carnegie; Akamai "Access Denied" + errors.edgesuite.net on
# goldman_sachs; a bot-check interstitial "Performing security verification...
# verifies you are not a bot" on ark_invest, served at HTTP 200 — the reason a
# status check alone is not sufficient). BLOCKPAGE_MAX_WORDS sits at 200, well
# above the largest observed block page (120 words) with real margin.
BLOCKPAGE_MAX_WORDS = 200
BLOCKPAGE_RE = re.compile(
    r"sorry, you have been blocked|cloudflare ray id|"
    r"the request could not be satisfied|generated by cloudfront|"
    r"errors\.edgesuite\.net|"
    r"performing security verification|verif(?:y|ies|ying) you are not a bot",
    re.I,
)

# Paywall / login-prompt signatures. Also LENGTH-GATED. Calibration found real,
# attributable content in gavekal "/teaser/" pages from ~90 words up (named
# countries, specific figures) — those must survive. Content-free stubs
# ("Sign In... Start a free trial", "User Login... paywalled article") topped
# out at 50 words. PAYWALL_MAX_WORDS sits at 60: below the 69-140 word range
# hand-verified to carry real signal, above the confirmed-empty-content stubs.
PAYWALL_MAX_WORDS = 60
PAYWALL_RE = re.compile(
    r"start a free trial|paywalled article|want to view this page|"
    r"request access to|sign up for a free trial|sign in to view documents",
    re.I,
)

# GDPR/cookie consent-notice capture (world_bank: extraction landed on the
# cookie banner instead of the publication page). Observed at 24 words;
# generous margin to 100.
CONSENT_MAX_WORDS = 100
CONSENT_RE = re.compile(r"we collect and process your personal information", re.I)

# JSON/metadata-blob detector (Carnegie JSON-LD-in-body, Messari API-reference
# docs). DENSITY-gated across the FULL text, not a first-chars-only check: a
# naive "starts with { " rule would have discarded four genuine Carnegie
# articles (371-2747 words) that carry a small fixed-size JSON-LD header
# followed by real prose — their "key": density is 0.4-3.2 per 100 words.
# Messari's API-reference pages are JSON-shaped throughout regardless of
# length (10.3-30.3 per 100 words). JSON_DENSITY_MIN sits at 6.0, with >3x
# margin on both sides of that observed gap.
JSON_DENSITY_MIN = 6.0
_KV_RE = re.compile(r'"[a-zA-Z_]+"\s*:\s*[\["\d]')


def _json_density(text):
    words = len((text or "").split())
    if not words:
        return 0.0
    return 100 * len(_KV_RE.findall(text)) / words


# Funnel reason -> (marker_regex_or_None, max_words_or_None). None max_words
# means the rule has no length gate (used only by the title/url checks below,
# which are structural, not content-shaped).
def classify_reject(article):
    """Return a short reason string if `article` should be rejected before
    ever being treated as content, else None. LENGTH-GATED where a marker is
    involved (RULE 2): a marker alone never rejects on its own — see the
    module-level comments above for why (real articles have matched every
    marker used here in isolation during calibration)."""
    title = (article.get("title") or "").strip().lower()
    if any(term in title for term in JUNK_TITLE_TERMS):
        return "junk_title"
    if any(title.endswith(suffix) for suffix in JUNK_TITLE_SUFFIXES):
        return "junk_title"
    url = (article.get("url") or "").lower()
    if any(term in url for term in JUNK_URL_TERMS):
        return "junk_url"

    text = article.get("text") or ""
    words = len(text.split())
    if BLOCKPAGE_RE.search(text) and words <= BLOCKPAGE_MAX_WORDS:
        return "blockpage"
    if PAYWALL_RE.search(text) and words <= PAYWALL_MAX_WORDS:
        return "paywall"
    if CONSENT_RE.search(text) and words <= CONSENT_MAX_WORDS:
        return "consent_notice"
    if _json_density(text) >= JSON_DENSITY_MIN:
        return "json_metadata"
    if words < MIN_WORD_COUNT:
        return "too_short"
    return None


def is_junk(article):
    """Back-compat wrapper: True if `article` should be rejected."""
    return classify_reject(article) is not None


# --- URL helpers ------------------------------------------------------------
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
    return url.split("#", 1)[0].rstrip("/").lower()


def path_segments(path):
    return [s for s in path.strip("/").split("/") if s]


def looks_like_article(url, apex):
    """True if the link points at an individual article/report (not a listing).

    Mirrors the inverse of the listing-page filter: article URLs carry a date,
    a numeric document id, or a multi-word title slug (3+ hyphens)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if apex_domain(parsed.netloc) != apex:
        return False
    if parsed.path.lower().endswith(".pdf"):
        return False  # can't innerText a PDF
    segs = path_segments(parsed.path)
    if not segs:
        return False
    has_year = any(YEAR_RE.match(s) for s in segs)
    has_doc_id = any(PURE_NUM_RE.match(s) and len(s) >= 4 for s in segs)
    leaf = EXT_RE.sub("", segs[-1])
    return has_year or has_doc_id or leaf.count("-") >= 3


# --- Date parsing -----------------------------------------------------------
def parse_date(value):
    """Best-effort parse of a date string to a datetime.date, else None."""
    if not value:
        return None
    v = value.strip()
    # Unix epoch timestamps (seconds=10 digits, milliseconds=13 digits), e.g.
    # JPMorgan's <meta name="alg-search-date" content="1779804720">.
    if v.isdigit() and len(v) in (10, 13):
        try:
            ts = int(v) / (1000 if len(v) == 13 else 1)
            d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()
            if 2000 <= d.year <= 2035:
                return d
        except (ValueError, OverflowError, OSError):
            pass
    # ISO 8601 (with or without time/zone).
    iso = v.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(iso).date()
    except ValueError:
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", v)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    # Try each format against the raw value (preserves dotted numeric dates like
    # 28.05.2026) and a period-trimmed variant ("Sep." -> "Sep").
    for candidate in (v, v.replace(".", "").strip()):
        for fmt in DATE_FORMATS:
            try:
                return datetime.datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def date_from_url(url):
    """Pull a YYYY/MM/DD date out of a URL path, e.g. /2026/05/28/, else None."""
    m = URL_DATE_RE.search(urlparse(url).path)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def find_date_in_text(text):
    """Scan the top of an article's text for a plausible publication date.

    Labelled dates ("Published: ...", "Date: ...") are preferred over loose
    matches because they are far more likely to be the publication date rather
    than a date mentioned in the body. Window bumped to 5000 chars so dates
    that sit past a long nav/header (e.g. PGIM ~1700 chars in) are still caught
    — label-first ordering keeps loose body dates a last resort."""
    head = (text or "")[:5000]
    for m in LABEL_DATE_RE.finditer(head):
        d = parse_date(m.group(1).strip())
        if d:
            return d
    for rx in TEXT_DATE_RES:
        m = rx.search(head)
        if m:
            d = parse_date(m.group(1))
            if d:
                return d
    return None


# --- Layered date extraction from rendered HTML -----------------------------
# JSON-LD date keys in preference order (published beats created/modified).
JSONLD_DATE_KEYS = ("datePublished", "dateCreated", "uploadDate", "dateModified")
LDJSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
META_KEY_RE = re.compile(r'(?:name|property|itemprop)\s*=\s*["\']([^"\']+)["\']', re.I)
META_CONTENT_RE = re.compile(r'content\s*=\s*["\']([^"\']*)["\']', re.I)
TIME_TAG_RE = re.compile(r"<time\b([^>]*)>", re.I)
TIME_DT_RE = re.compile(r'datetime\s*=\s*["\']([^"\']+)["\']', re.I)
# meta key classification: publication-ish vs modified-ish.
_META_PUBLISH_RE = re.compile(
    r"publish|pubdate|posted|release|created|issued|content_date|article:published",
    re.I)
_META_MODIFIED_RE = re.compile(r"modif|updated", re.I)


def _jsonld_date(html):
    """Recursively scan all JSON-LD blocks; return the highest-priority date."""
    found = {k: [] for k in JSONLD_DATE_KEYS}
    for block in LDJSON_RE.findall(html):
        block = block.strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except Exception:
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                for k in JSONLD_DATE_KEYS:
                    if isinstance(o.get(k), str):
                        found[k].append(o[k])
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    for key in JSONLD_DATE_KEYS:
        for val in found[key]:
            d = parse_date(val)
            if d:
                return d
    return None


def _meta_date(html):
    """Scan date-ish <meta> tags, preferring publication dates over modified."""
    metas = []
    for tag in META_TAG_RE.findall(html):
        km = META_KEY_RE.search(tag)
        cm = META_CONTENT_RE.search(tag)
        if not km or not cm:
            continue
        key = km.group(1).strip().lower()
        content = cm.group(1).strip()
        if not content:
            continue
        if any(w in key for w in ("date", "time", "publish", "modif", "created")):
            metas.append((key, content))
    # priority buckets: explicit-publish -> generic -> modified/updated
    buckets = (
        lambda k: _META_PUBLISH_RE.search(k) and not _META_MODIFIED_RE.search(k),
        lambda k: not _META_PUBLISH_RE.search(k) and not _META_MODIFIED_RE.search(k),
        lambda k: bool(_META_MODIFIED_RE.search(k)),
    )
    for pred in buckets:
        for key, content in metas:
            if pred(key):
                d = parse_date(content)
                if d:
                    return d
    return None


def _time_date(html):
    """Return the first parseable <time datetime="..."> value."""
    for attrs in TIME_TAG_RE.findall(html):
        dm = TIME_DT_RE.search(attrs)
        if dm:
            d = parse_date(dm.group(1))
            if d:
                return d
    return None


# Inline JSON state blobs (Next.js __NEXT_DATA__, hydration props, etc.) often
# carry the publication date as a date-keyed value. We match both raw and
# backslash-escaped JSON forms so escaped script payloads work too. The value
# is intentionally bounded ([^"\\]{0,30}) so we never run away into the next
# field. Only date-shaped keys are accepted — never raw "any ISO" — to avoid
# grabbing compliance/session/copyright dates elsewhere on the page.
_JSON_STATE_DATE_KEYS = (
    "datepublished", "publishedat", "publishedon", "publisheddate",
    "publish_date", "publication_date", "publicationdate",
    "postdate", "post_date", "articledate", "article_date",
    "displaydate", "releasedate", "release_date", "date",
)
JSON_STATE_DATE_RE = re.compile(
    r'(?:\\"|")(' + "|".join(_JSON_STATE_DATE_KEYS) + r')(?:\\"|")\s*:\s*'
    r'(?:\\"|")(\d{4}-\d{2}-\d{2}[^"\\]{0,30})',
    re.I,
)


def _json_state_date(html):
    """Catch dates embedded in inline JSON state (Next.js / Nuxt / hydration
    blobs). Handles both raw and backslash-escaped JSON. Prefers explicit
    publish-ish keys over the generic 'date'."""
    found = {}
    for k, v in JSON_STATE_DATE_RE.findall(html):
        found.setdefault(k.lower(), []).append(v)
    for key in _JSON_STATE_DATE_KEYS:   # priority = declaration order above
        for v in found.get(key, ()):
            d = parse_date(v)
            if d:
                return d
    return None


def _html_to_text(html):
    """Crude tag strip for the visible-text date fallback."""
    h = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", html)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def extract_date(html, url):
    """Best-effort publication date from a rendered page, trying layers in
    order: JSON-LD -> meta tags -> <time> -> URL path -> visible text.
    Returns a datetime.date or None. Pure function (testable on saved HTML)."""
    if html:
        for layer in (_jsonld_date, _meta_date, _time_date, _json_state_date):
            d = layer(html)
            if d:
                return d
    d = date_from_url(url)
    if d:
        return d
    if html:
        # Cap the HTML-stripped scan tightly: full-HTML strip mixes nav, body,
        # and footer (compliance/disclosure expiration dates live in footers
        # and would otherwise become false positives). The cleaner pass-2
        # fallback uses extract_article's main-body-only text where the wider
        # 5000-char window is safe.
        return find_date_in_text(_html_to_text(html)[:1500])
    return None


# --- Scraping ---------------------------------------------------------------
class RateLimiter:
    """Enforce a minimum gap between page visits (politeness)."""

    def __init__(self, gap_s):
        self.gap_s = gap_s
        self._last = 0.0

    def wait(self):
        elapsed = time.monotonic() - self._last
        if self._last and elapsed < self.gap_s:
            time.sleep(self.gap_s - elapsed)
        self._last = time.monotonic()


def collect_anchors(page, base_url):
    """All href values on the current page, resolved to absolute URLs."""
    try:
        hrefs = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        )
    except Exception:
        return []
    out = []
    for href in hrefs:
        if not href:
            continue
        href = href.strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        out.append(urljoin(base_url, href))
    return out


def settle_index(page):
    """Give a JS-rendered index page time to inject its article links before
    harvesting. Many institutional listings are client-side rendered, so a
    domcontentloaded DOM has nav chrome but no article links yet. Bounded so
    per-source budgets aren't blown: <=5s network-idle + one scroll + ~0.8s.
    Mirrors extract_article's wait style; never raises."""
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass  # some sites never go idle (polling/analytics) — proceed anyway
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass  # trigger lazy-loaded lists
    page.wait_for_timeout(800)


# Well-known consent-button ids/selectors, tried before the generic name match.
COOKIE_SELECTORS = (
    "#onetrust-accept-btn-handler",          # OneTrust (very common)
    ".onetrust-accept-btn-handler",
    "#truste-consent-button",                # TrustArc
    "#truste-consent-required",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # Cookiebot
    "button[aria-label*='accept' i]",
    "button[title*='accept' i]",
    "[data-testid*='accept' i]",
)
# Generic accept/agree button names (accessible-name match) used as a fallback.
COOKIE_NAME_RE = re.compile(r"\b(accept|agree|allow all|got it)\b", re.I)


def dismiss_cookie_banner(page):
    """Best-effort click of a cookie/consent accept button. Never raises."""
    for sel in COOKIE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click(timeout=1_500)
                page.wait_for_timeout(300)
                return True
        except Exception:
            pass
    try:
        loc = page.get_by_role("button", name=COOKIE_NAME_RE).first
        if loc.count() > 0:
            loc.click(timeout=1_500)
            page.wait_for_timeout(300)
            return True
    except Exception:
        pass
    return False


def navigate(page, url):
    """Navigate to url and dismiss any cookie banner. On failure, retry once
    with a different viewport and a longer, more lenient wait (helps sites like
    morganstanley.com/ideas that gate the initial load). Raises on final
    failure so callers log/record it exactly as before.

    Returns the Playwright Response of the navigation that succeeded (or None
    if Playwright itself returns none, e.g. a same-document navigation) so
    callers can gate on HTTP status before treating the page as content."""
    response = None
    try:
        response = page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
    except (PlaywrightTimeout, PlaywrightError):
        # Retry with a different viewport and a longer, more lenient wait; then
        # restore the default viewport so later pages stay consistent.
        try:
            page.set_viewport_size(RETRY_VIEWPORT)
            response = page.goto(url, timeout=PAGE_TIMEOUT_MS * 2, wait_until="commit")
            page.wait_for_timeout(2_000)
        finally:
            page.set_viewport_size(DEFAULT_VIEWPORT)
    dismiss_cookie_banner(page)
    return response


def extract_article(page):
    """Run EXTRACT_JS, giving images a moment to load for width measurement."""
    try:
        page.wait_for_load_state("load", timeout=3_000)
    except Exception:
        pass
    page.wait_for_timeout(400)
    data = page.evaluate(EXTRACT_JS)
    # Full rendered HTML for layered date extraction (JSON-LD/meta/time scan).
    try:
        data["html"] = page.content()
    except Exception:
        data["html"] = ""
    # Resolve any relative image URLs against the final page URL.
    data["images"] = [urljoin(page.url, src) for src in data.get("images", [])]
    return data


# Per-source funnel counter keys. status_rejected/blockpage_rejected/
# paywall_rejected/consent_rejected/json_rejected/too_short/dropped_junk are
# rejection reasons from Fix 1 (HTTP status gate) and Fix 2 (content floor,
# see classify_reject) — logged loudly, never silently, per RULE 1.
FUNNEL_KEYS = (
    "anchors_found", "candidates", "visited", "nav_errors",
    "dropped_undated", "dropped_old",
    "status_rejected", "blockpage_rejected", "paywall_rejected",
    "consent_rejected", "json_rejected", "too_short", "dropped_junk",
    "kept",
)


def collect_source(page, limiter, source, cutoff_date, errors,
                   budget_s=SOURCE_TIMEOUT_S, index_phase_s=INDEX_PHASE_S,
                   funnels=None):
    """Return a list of fresh-article dicts for one source. Never raises.

    funnels (optional dict): if given, records this source's funnel counters
    under funnels[sid]. Counting only — does not affect collection behavior."""
    sid = source["id"]
    name = source.get("name", sid)
    funnel = {k: 0 for k in FUNNEL_KEYS}
    urls = source.get("urls") or []
    if not urls:
        log(f"  {sid}: no urls ({source.get('status', 'skip')}) — skipping")
        if funnels is not None:
            funnels[sid] = funnel
        return []

    apex = apex_domain(urlparse(urls[0]).netloc)
    start = time.monotonic()
    seen = {norm_url(u) for u in urls}   # don't treat index pages as articles
    candidates = []                       # ordered, de-duplicated article URLs
    articles = []

    def over_budget():
        return (time.monotonic() - start) > budget_s

    # --- Pass 1: walk index pages, gather article links ---
    # Capped (count + time) so sources with many listing pages still leave
    # budget for actually reading articles in pass 2.
    for index_url in urls[:MAX_INDEX_PAGES]:
        if (time.monotonic() - start) > index_phase_s:
            log(f"  {sid}: index phase budget reached")
            break
        limiter.wait()
        try:
            navigate(page, index_url)
        except (PlaywrightTimeout, PlaywrightError):
            # One bounded retry before giving up on this index page.
            try:
                limiter.wait()
                navigate(page, index_url)
            except (PlaywrightTimeout, PlaywrightError) as exc:
                log(f"  WARN {sid}: index failed {index_url} — {type(exc).__name__}")
                errors.append({"source_id": sid, "url": index_url,
                               "error": f"index: {type(exc).__name__}"})
                continue
        # Let client-side JS inject the article links before harvesting them.
        settle_index(page)
        anchors = collect_anchors(page, page.url)
        funnel["anchors_found"] += len(anchors)
        for link in anchors:
            key = norm_url(link)
            if key in seen:
                continue
            if looks_like_article(link, apex):
                seen.add(key)
                candidates.append(link)
                funnel["candidates"] += 1

    # --- Pass 2: visit candidate articles, keep the recent ones ---
    skipped_old = junk = 0
    for article_url in candidates:
        if len(articles) >= MAX_ARTICLES_PER_SOURCE:
            log(f"  {sid}: hit per-source article cap ({MAX_ARTICLES_PER_SOURCE})")
            break
        if over_budget():
            log(f"  {sid}: source time budget reached while reading articles")
            break
        limiter.wait()
        try:
            response = navigate(page, article_url)
        except (PlaywrightTimeout, PlaywrightError) as exc:
            funnel["nav_errors"] += 1
            log(f"  WARN {sid}: article failed {article_url} — {type(exc).__name__}")
            errors.append({"source_id": sid, "url": article_url,
                           "error": f"article: {type(exc).__name__}"})
            continue
        # --- FIX 1, layer 1: HTTP status gate. Reject before the body is ever
        # treated as content — a 403/404/5xx page is not an article, no matter
        # what its text says. (Layer 2, the blockpage marker+length check, runs
        # below after extraction — some WAF challenges return 200 precisely to
        # defeat a status-only check; see BLOCKPAGE_RE.)
        status = response.status if response is not None else None
        if status is not None and status >= 400:
            funnel["status_rejected"] += 1
            log(f"  REJECT {sid}: status {status} — {article_url}")
            errors.append({"source_id": sid, "url": article_url,
                           "error": f"status_rejected:{status}"})
            continue
        try:
            data = extract_article(page)
        except (PlaywrightTimeout, PlaywrightError) as exc:
            funnel["nav_errors"] += 1
            log(f"  WARN {sid}: article failed {article_url} — {type(exc).__name__}")
            errors.append({"source_id": sid, "url": article_url,
                           "error": f"article: {type(exc).__name__}"})
            continue
        funnel["visited"] += 1

        # Layered: JSON-LD/meta/<time>/URL/visible-text (extract_date), then the
        # prior DOM date_raw + clean-text fallbacks (kept as additional layers).
        pub_date = (extract_date(data.get("html", ""), article_url)
                    or parse_date(data.get("date_raw"))
                    or find_date_in_text(data.get("text")))
        if pub_date is not None and pub_date < cutoff_date:
            skipped_old += 1
            funnel["dropped_old"] += 1
            continue
        # No date found: keep it (capped later). An undated article surfaced on
        # a listing page is more likely new than old, so include rather drop it.
        article = {
            "source_id": sid,
            "source_name": name,
            "category": source.get("category", ""),
            "url": article_url,
            "title": data.get("title", ""),
            "date": pub_date.isoformat() if pub_date else "",
            "text": data.get("text", ""),
            "images": data.get("images", []),
        }
        reason = classify_reject(article)
        if reason is not None:
            junk += 1
            reason_key = {
                "blockpage": "blockpage_rejected",
                "paywall": "paywall_rejected",
                "consent_notice": "consent_rejected",
                "json_metadata": "json_rejected",
                "too_short": "too_short",
            }.get(reason, "dropped_junk")  # junk_title / junk_url -> dropped_junk
            funnel[reason_key] += 1
            words = len((article.get("text") or "").split())
            log(f"  REJECT {sid}: {reason} ({words}w) — {article_url}")
            continue
        articles.append(article)

    # --- Undated cap: keep at most the first 5 undated articles per source ---
    total_undated = sum(1 for a in articles if not a["date"])
    if total_undated > 5:
        capped, seen_undated = [], 0
        for a in articles:
            if not a["date"]:
                seen_undated += 1
                if seen_undated > 5:
                    funnel["dropped_undated"] += 1
                    continue
            capped.append(a)
        articles = capped
        log(f"  {sid}: capped {total_undated} undated articles to 5")

    undated = sum(1 for a in articles if not a["date"])
    funnel["kept"] = len(articles)
    if funnels is not None:
        funnels[sid] = funnel
    log(f"  {sid}: {len(articles)} new "
        f"(scanned {len(candidates)} candidates, "
        f"{skipped_old} old, {undated} undated, {junk} junk)")
    return articles


# --- FIX 3: union by URL, inside the date directory --------------------------
# raw/institutional/<date>/articles.json and latest/articles_institutional.json
# are AGGREGATES (RULE 1) — the unit of record is the article, keyed by URL.
# A second same-day collect must merge with the first, not wholesale-replace
# it. On URL collision, keep the higher-word_count version, but ONLY among
# versions that pass classify_reject (Fix 2's floor) — a 325-word JSON-LD blob
# must never beat a 280-word real article on word count alone.
def union_articles(old_articles, new_articles):
    """Merge old_articles (this date's existing raw archive, if any) with
    new_articles (this run's harvest) by URL. Returns (unioned_list, stats).

    stats:
      union_recovered — URL existed only in old_articles (this run did not
                         rediscover it) and its old version passed the floor;
                         carried forward instead of silently dropped.
      degrade_skipped — URL existed in both; the qualifying OLD version had a
                         higher word_count than the qualifying NEW version, so
                         old was kept and the new (worse) fetch was discarded.
      floor_rejected  — URL had no qualifying candidate at all (old and/or new
                         both failed classify_reject, or the only candidate
                         failed it); nothing enters the union for it.
    """
    by_url_old = {a["url"]: a for a in old_articles if a.get("url")}
    by_url_new = {a["url"]: a for a in new_articles if a.get("url")}
    stats = {"union_recovered": 0, "degrade_skipped": 0, "floor_rejected": 0}
    result = []

    for url in set(by_url_old) | set(by_url_new):
        old_a, new_a = by_url_old.get(url), by_url_new.get(url)
        candidates = []
        if old_a is not None and classify_reject(old_a) is None:
            candidates.append(("old", old_a))
        if new_a is not None and classify_reject(new_a) is None:
            candidates.append(("new", new_a))

        if not candidates:
            stats["floor_rejected"] += 1
            continue

        origin, winner = max(
            candidates, key=lambda oc: len((oc[1].get("text") or "").split())
        )
        result.append(winner)
        if old_a is not None and new_a is None:
            stats["union_recovered"] += 1
        elif old_a is not None and new_a is not None and origin == "old":
            # A genuine degrade means old was STRICTLY better than new — an
            # exact word-count tie (the common case: an unchanged page
            # refetched identically) is not a degrade and must not be counted
            # as one, even though max()'s stable tie-break also picks "old"
            # first in that case.
            w_old = len((old_a.get("text") or "").split())
            w_new = len((new_a.get("text") or "").split())
            if w_old > w_new:
                stats["degrade_skipped"] += 1

    return result, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ids",
        help="comma-separated source ids to run (default: all sources)",
    )
    parser.add_argument(
        "--days", type=int, default=LOOKBACK_DAYS,
        help=f"lookback window in days (default: {LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--budget", type=int, default=None,
        help=f"per-source time budget in seconds (default: {SOURCE_TIMEOUT_S})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="deliberate rebuild: skip the union with any existing same-date "
             "raw archive (this run's harvest alone becomes the new raw + "
             "latest). Nothing else bypasses the union.",
    )
    args = parser.parse_args()

    def budget_for(source):
        """Per-source (budget_s, index_phase_s). bank_bulge gets the larger
        budget; --budget overrides the total and scales the index phase to keep
        the same share."""
        if source.get("category") == "bank_bulge":
            base_total, base_index = BULGE_SOURCE_TIMEOUT_S, BULGE_INDEX_PHASE_S
        else:
            base_total, base_index = SOURCE_TIMEOUT_S, INDEX_PHASE_S
        if args.budget:
            return args.budget, round(args.budget * base_index / base_total)
        return base_total, base_index

    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config not found: {CONFIG_PATH}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = config.get("sources", [])
    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        sources = [s for s in sources if s["id"] in wanted]
        missing = wanted - {s["id"] for s in sources}
        if missing:
            log(f"Unknown ids ignored: {', '.join(sorted(missing))}")

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff_date = (now - datetime.timedelta(days=args.days)).date()
    log(f"Collecting institutional research from {len(sources)} source(s); "
        f"keeping articles since {cutoff_date.isoformat()}")

    all_articles = []
    errors = []
    funnels = {}  # per-source funnel counters (instrumentation only)
    limiter = RateLimiter(PAGE_DELAY_S)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport=DEFAULT_VIEWPORT,
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT_MS)

        for i, source in enumerate(sources, 1):
            sid = source.get("id", f"#{i}")
            log(f"[{i}/{len(sources)}] {sid}")
            src_budget, src_index = budget_for(source)
            try:
                found = collect_source(page, limiter, source, cutoff_date, errors,
                                       budget_s=src_budget,
                                       index_phase_s=src_index,
                                       funnels=funnels)
                all_articles.extend(found)
            except Exception as exc:  # last-resort guard: never crash the run
                log(f"  WARN {sid}: unexpected error — {type(exc).__name__}: {exc}")
                errors.append({"source_id": sid, "error": f"{type(exc).__name__}: {exc}"})
                continue

        browser.close()

    collected_at = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # --- FIX 3: union with any existing same-date raw archive -----------------
    date_dir = RAW_ROOT / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    raw_path = date_dir / "articles.json"

    existing_articles = []
    if not args.force and raw_path.exists():
        try:
            existing_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            existing_articles = existing_payload.get("articles", [])
        except json.JSONDecodeError:
            log(f"WARN: existing {raw_path} is not valid JSON — "
                f"treating as empty (no union)")

    if args.force:
        log("--force: skipping union with any existing same-date raw archive")
        final_articles = all_articles
        union_stats = {"union_recovered": 0, "degrade_skipped": 0, "floor_rejected": 0}
    else:
        final_articles, union_stats = union_articles(existing_articles, all_articles)
        if existing_articles:
            log(f"Union: {len(existing_articles)} existing + {len(all_articles)} new "
                f"-> {len(final_articles)} unioned "
                f"(recovered={union_stats['union_recovered']}, "
                f"degrade_skipped={union_stats['degrade_skipped']}, "
                f"floor_rejected={union_stats['floor_rejected']})")

    # --- by-source counts, computed from the FINAL (unioned) set -------------
    by_source = {}
    for art in final_articles:
        by_source[art["source_id"]] = by_source.get(art["source_id"], 0) + 1

    meta = {
        "collected_at": collected_at,
        "lookback_days": args.days,
        "total_articles": len(final_articles),
        "sources_processed": len(sources),
        "by_source": by_source,
        "errors": errors,
    }

    # --- raw archive: full + pretty (union already applied) ------------------
    raw_payload = dict(meta)
    raw_payload["articles"] = final_articles
    raw_path.write_text(
        json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- per-source funnel instrumentation (counters only) ---
    # Ensure every processed source appears even if a hard crash skipped its
    # in-source recording (last-resort guard in the loop above).
    for s in sources:
        funnels.setdefault(s.get("id", ""), {k: 0 for k in FUNNEL_KEYS})
    cols = list(FUNNEL_KEYS)
    labels = ["source", "anchors", "candidates", "visited", "nav_err",
              "undated", "old", "status", "block", "paywall", "consent",
              "json", "short", "junk", "kept"]
    flines = [f"{labels[0]:24}" + "".join(f"{h:>9}" for h in labels[1:]),
              "-" * (24 + 9 * len(cols))]
    for sid in sorted(funnels, key=lambda k: (funnels[k]["kept"], k)):
        f = funnels[sid]
        flines.append(f"{sid[:23]:24}" + "".join(f"{f[c]:>9}" for c in cols))
    funnel_table = "\n".join(flines)
    print(funnel_table)
    (date_dir / "funnel.txt").write_text(funnel_table + "\n", encoding="utf-8")
    funnel_payload = {
        "collected_at": collected_at,
        "columns": cols,
        "notes": [
            "Counters only for the per-source table below — collection "
            "behavior is unaffected by counting.",
            "candidates = anchors that passed looks_like_article (after dedup).",
            "visited = article pages where navigate+extract both succeeded.",
            "dropped_old maps to the existing skipped_old (pub_date < cutoff).",
            "status_rejected = HTTP status >= 400 (Fix 1, layer 1) — rejected "
            "before extraction, body never treated as content.",
            "blockpage/paywall/consent/json rejections = Fix 2 content-floor "
            "reasons (classify_reject); each is marker+length gated except "
            "too_short (word-count-only) and json (density-only).",
            "dropped_undated: NO date-stage drop exists; no-date articles are "
            "KEPT by design. This counts only undated items removed by the >5 "
            "per-source undated cap.",
            "kept = articles written to THIS RUN's harvest (pre-union).",
        ],
        "union": {
            "existing_count": len(existing_articles),
            "new_harvest_count": len(all_articles),
            "final_count": len(final_articles),
            "union_recovered": union_stats["union_recovered"],
            "degrade_skipped": union_stats["degrade_skipped"],
            "floor_rejected": union_stats["floor_rejected"],
            "forced_rebuild": args.force,
        },
        "sources": funnels,
    }
    (date_dir / "funnel.json").write_text(
        json.dumps(funnel_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- latest: REBUILT from the (unioned, floor-passed) date dir, not from
    # this run's harvest alone. latest/ is NOT date-scoped, so it must never
    # be unioned into directly (that would accumulate forever) — it is always
    # a full rebuild of the current date directory's final content.
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    latest_payload = {
        "collected_at": collected_at,
        "lookback_days": args.days,
        "total_articles": len(final_articles),
        "by_source": by_source,
        "articles": [strip_empty(a) for a in final_articles],
    }
    (LATEST_DIR / LATEST_NAME).write_text(
        json.dumps(latest_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    # --- summary ---
    log("=" * 52)
    log(f"DONE: {len(final_articles)} article(s) from {len(by_source)} source(s) "
        f"in the final unioned set; {len(errors)} error(s) this run")
    for sid in sorted(by_source, key=lambda k: -by_source[k]):
        log(f"  {sid:<32}{by_source[sid]}")
    if errors:
        log(f"Errors ({len(errors)}):")
        for e in errors[:20]:
            log(f"  {e.get('source_id', '?')}: {e.get('error', '')}")
    log(f"Raw:    {raw_path.relative_to(REPO_ROOT)}")
    log(f"Latest: {(LATEST_DIR / LATEST_NAME).relative_to(REPO_ROOT)}")
    log(f"Funnel: {(date_dir / 'funnel.json').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
