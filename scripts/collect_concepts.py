#!/usr/bin/env python3
"""Daily Concepts-stream scraper for the Market Intelligence KNOWLEDGE track.

Clone of scripts/collect_institutional.py, adapted for the Concepts stream.
Same deterministic Playwright machinery (settle_index, looks_like_article, junk
filter, layered extract_date, per-source funnel, --days recency gate); NO LLM.

Two deliberate differences from the Institutional collector:

  1. Config shape. config/concepts_sources.json sources are
     {name, index_url, category, type, paywalled, trust, verify_listing}
     (a single index_url per source, no `id`). We derive a stable `source_slug`
     from the name and wrap index_url into a one-element URL list so the rest of
     the institutional crawl logic is reused unchanged.

  2. Output layout. Institutional writes one date-bucketed articles.json. Concepts
     writes ONE FILE PER ARTICLE, YouTube-style:
         raw/concepts/<source_slug>/<url_hash>.json
     each record:
         {record_id, source_slug, source_name, source_url, category, type,
          paywalled, title, published_date, language, author, word_count,
          text, image_urls, collected_at}
     The required-by-spec keys are source_name, source_url, title,
     published_date, text, image_urls, author, word_count; the rest are
     traceability/envelope-support fields the extraction routine reuses.

Per-run diagnostics (funnel + manifest) are written to
    raw/concepts/_runs/<YYYY-MM-DD>/{funnel.txt,funnel.json,run.json}
Dirs whose name starts with "_" are run artifacts, never a source slug — the
extraction routine's worklist scans raw/concepts/<slug>/<hash>.json and skips
"_"-prefixed dirs.

The scraper is defensive: a source that times out, blocks, or errors is logged
as a warning and skipped — the run never crashes. Window-based collection
(--days) self-heals missed days: re-running picks up anything still in window.

Setup:
    pip install playwright && playwright install chromium

Run:
    python3 scripts/collect_concepts.py                       # all sources, --days 3
    python3 scripts/collect_concepts.py --ids a16z_blog,bis_papers_speeches
    python3 scripts/collect_concepts.py --days 7 --budget 180
"""

import argparse
import datetime
import hashlib
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
CONFIG_PATH = REPO_ROOT / "config" / "concepts_sources.json"
RAW_ROOT = REPO_ROOT / "raw" / "concepts"
RUNS_ROOT = RAW_ROOT / "_runs"

# --- Tunables ---------------------------------------------------------------
LOOKBACK_DAYS = 3             # daily stream: only keep articles within this window
PAGE_TIMEOUT_MS = 10_000      # 10s per page navigation
SOURCE_TIMEOUT_S = 120        # 120s wall-clock budget per source (--budget overrides)
INDEX_PHASE_S = 60            # cap index-page crawling so articles get budget too
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
  text = text.replace(/[ \t ]+/g, ' ');  // collapse spaces/tabs/nbsp
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

  // --- author / byline (concepts addition): meta -> byline element -> JSON-LD ---
  let author = '';
  const authMeta = [
    'meta[name="author"]', 'meta[property="article:author"]',
    'meta[name="parsely-author"]', 'meta[property="og:article:author"]',
    'meta[name="byl"]', 'meta[name="sailthru.author"]', 'meta[name="twitter:creator"]'
  ];
  for (const s of authMeta) {
    const m = document.querySelector(s);
    if (m && m.content && m.content.trim()) { author = m.content.trim(); break; }
  }
  if (!author) {
    const b = document.querySelector(
      '[rel=author], .byline, .byline__name, .author-name, .author, ' +
      '.post-author, [itemprop=author]'
    );
    if (b && b.innerText) author = b.innerText.trim();
  }
  if (!author) {
    for (const sc of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        let j = JSON.parse(sc.textContent);
        const nodes = Array.isArray(j) ? j.slice() : [j];
        while (nodes.length) {
          const o = nodes.shift();
          if (!o || typeof o !== 'object') continue;
          let a = o.author;
          if (a) {
            if (Array.isArray(a)) a = a[0];
            if (a && typeof a === 'object') a = a.name;
            if (typeof a === 'string' && a.trim()) { author = a.trim(); break; }
          }
          if (Array.isArray(o['@graph'])) nodes.push(...o['@graph']);
        }
      } catch (e) {}
      if (author) break;
    }
  }
  author = author.replace(/^by\s+/i, '').split('|')[0].split('\n')[0].trim().slice(0, 120);

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
  return { title, author, text, images: images.slice(0, 20), date_raw: (date || '').trim() };
}
""".replace("__MIN_W__", str(MIN_IMAGE_WIDTH))


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def slugify(name):
    """Stable, filesystem-safe source slug derived from a source name.
    All 78 seed names slugify uniquely (verified)."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "source"


def url_hash(url):
    """Stable short id for an article URL (dedup + filename)."""
    return hashlib.sha1(norm_url(url).encode("utf-8")).hexdigest()[:16]


# --- Junk filter ------------------------------------------------------------
# Boilerplate/legal/recruiting pages that slip through as "articles".
JUNK_TITLE_TERMS = (
    "privacy", "cookie", "terms", "disclaimer", "contact us", "careers",
    "our people", "leadership", "diversity and inclusion",
    "diversity, equity", "legal information",
    # Bot-block interstitials (Cloudflare/Akamai/Imperva-style). These have
    # short, characteristic titles distinct from any real article title, and
    # unlike the Cloudflare "checking your browser" interstitial in
    # extract_article(), a HARD block page like this won't resolve with more
    # wait time — it must be dropped as junk, not retried or "kept" as a
    # 100+-word article (confirmed 2026-07-08: chatham_house residential test
    # kept 5 "Sorry, you have been blocked" pages before this fix, each just
    # over the MIN_ARTICLE_WORDS floor).
    "sorry, you have been blocked", "you have been blocked",
    "access denied", "just a moment",
)
# Listing pages whose title ends with one of these.
JUNK_TITLE_SUFFIXES = ("articles & insights", "articles and insights")
# URL path fragments that mark a page as product/recruiting/legal boilerplate
# rather than research.
JUNK_URL_TERMS = (
    "/legal/", "/privacy/", "/cookie/", "/terms/", "/careers/", "/contact/",
    "/our-firm/", "/who-we-are", "/terms-and-conditions", "/privacy", "/cookie",
    "/subscribe", "/newsletter", "/about/", "/about-us",
    # Section/landing/announcement pages that carry dated or hyphenated slugs and
    # so pass looks_like_article, but are NOT research (surfaced on the canary by
    # Carnegie: /programs/ overview pages, /events/ announcements).
    "/programs/", "/program/", "/events/", "/event/",
)
MIN_TEXT_LEN = 100     # shorter than this (chars) = empty/nav page
MIN_ARTICLE_WORDS = 120  # research articles run long; below this is a teaser /
                         # landing / announcement stub, not extraction-worthy.


def too_short(text):
    """True if text is too short to be a real article body (char OR word floor).
    The word floor catches paywall teasers and announcement stubs that clear the
    char floor (e.g. a 45-word program blurb)."""
    t = text or ""
    return len(t) < MIN_TEXT_LEN or len(t.split()) < MIN_ARTICLE_WORDS


def is_junk(article):
    """True if an article is boilerplate (legal/privacy/careers), a listing
    page, an empty/nav page, or sits at a junk URL path."""
    title = (article.get("title") or "").strip().lower()
    if any(term in title for term in JUNK_TITLE_TERMS):
        return True
    if any(title.endswith(suffix) for suffix in JUNK_TITLE_SUFFIXES):
        return True
    if too_short(article.get("text")):
        return True
    url = (article.get("url") or "").lower()
    if any(term in url for term in JUNK_URL_TERMS):
        return True
    return False


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
    # Unix epoch timestamps (seconds=10 digits, milliseconds=13 digits).
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
    # Try each format against the raw value and a period-trimmed variant.
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
    Labelled dates are preferred over loose matches."""
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
JSONLD_DATE_KEYS = ("datePublished", "dateCreated", "uploadDate", "dateModified")
LDJSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
META_KEY_RE = re.compile(r'(?:name|property|itemprop)\s*=\s*["\']([^"\']+)["\']', re.I)
META_CONTENT_RE = re.compile(r'content\s*=\s*["\']([^"\']*)["\']', re.I)
TIME_TAG_RE = re.compile(r"<time\b([^>]*)>", re.I)
TIME_DT_RE = re.compile(r'datetime\s*=\s*["\']([^"\']+)["\']', re.I)
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
    """Catch dates embedded in inline JSON state (Next.js / Nuxt / hydration)."""
    found = {}
    for k, v in JSON_STATE_DATE_RE.findall(html):
        found.setdefault(k.lower(), []).append(v)
    for key in _JSON_STATE_DATE_KEYS:
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
    order: JSON-LD -> meta tags -> <time> -> URL path -> visible text."""
    if html:
        for layer in (_jsonld_date, _meta_date, _time_date, _json_state_date):
            d = layer(html)
            if d:
                return d
    d = date_from_url(url)
    if d:
        return d
    if html:
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


def settle_index(page, extra_ms=0):
    """Give a JS-rendered index page time to inject its article links before
    harvesting. Bounded so per-source budgets aren't blown. extra_ms adds a
    longer settle on retry attempts for slow/soft-blocking listings."""
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass
    page.wait_for_timeout(800 + extra_ms)


# Index harvest is retried with backoff: flaky/JS-heavy/soft-blocking listings
# (e.g. Carnegie's root) intermittently return 0 article links on the first hit.
INDEX_NAV_ATTEMPTS = 3
INDEX_BACKOFF_S = (0, 2, 4)   # sleep before attempts 1, 2, 3


def harvest_index(page, limiter, index_url, slug, errors, deadline=None):
    """Navigate an index page, settle it, and return harvested anchors. Retries
    with backoff when navigation fails OR the page yields 0 anchors (a longer
    settle each retry). Bounded by `deadline` (monotonic time) — a HARD cap so a
    blocked/hanging listing can never burn the whole run; retries stop once the
    deadline passes. Returns the anchor list (possibly empty). Never raises."""
    anchors = []
    for attempt in range(INDEX_NAV_ATTEMPTS):
        if deadline is not None and time.monotonic() > deadline:
            log(f"  {slug}: index deadline reached — stopping retries")
            break
        if attempt:
            time.sleep(INDEX_BACKOFF_S[min(attempt, len(INDEX_BACKOFF_S) - 1)])
        limiter.wait()
        try:
            navigate(page, index_url)
        except (PlaywrightTimeout, PlaywrightError) as exc:
            if attempt == INDEX_NAV_ATTEMPTS - 1:
                log(f"  WARN {slug}: index failed {index_url} — {type(exc).__name__}")
                errors.append({"source_slug": slug, "url": index_url,
                               "error": f"index: {type(exc).__name__}"})
            continue
        settle_index(page, extra_ms=attempt * 1_500)
        anchors = collect_anchors(page, page.url)
        if anchors:
            return anchors
        # 0 anchors despite a successful load → likely JS-not-settled or a soft
        # block; back off and retry with a longer settle.
        log(f"  {slug}: index returned 0 anchors (attempt {attempt + 1}/{INDEX_NAV_ATTEMPTS})")
    return anchors


COOKIE_SELECTORS = (
    "#onetrust-accept-btn-handler",
    ".onetrust-accept-btn-handler",
    "#truste-consent-button",
    "#truste-consent-required",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "button[aria-label*='accept' i]",
    "button[title*='accept' i]",
    "[data-testid*='accept' i]",
)
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
    with a different viewport and a longer, more lenient wait."""
    try:
        page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
    except (PlaywrightTimeout, PlaywrightError):
        try:
            page.set_viewport_size(RETRY_VIEWPORT)
            page.goto(url, timeout=PAGE_TIMEOUT_MS * 2, wait_until="commit")
            page.wait_for_timeout(2_000)
        finally:
            page.set_viewport_size(DEFAULT_VIEWPORT)
    dismiss_cookie_banner(page)


# Cloudflare's transient "checking your browser" / "performing security
# verification" interstitial. It self-clears client-side after a few seconds
# on most sites (ARK confirmed: resolves to the real article ~3s after
# domcontentloaded) — the generic 400ms settle in extract_article() is too
# short to see that resolution, so short interstitial text gets captured and
# misread as "this article is a teaser stub". One bounded retry catches it.
CLOUDFLARE_INTERSTITIAL_RE = re.compile(
    r"performing security verification|checking your browser|"
    r"just a moment|verification successful.{0,40}waiting", re.I)
CLOUDFLARE_RETRY_WAIT_MS = 4_000


def extract_article(page):
    """Run EXTRACT_JS, giving images a moment to load for width measurement.
    Retries once with a longer settle if the page is still showing a
    Cloudflare interstitial (see CLOUDFLARE_INTERSTITIAL_RE) — most such
    challenges clear client-side within a few seconds; a hard block (e.g. a
    "Just a moment..." page that never advances) just fails the same way
    after the retry, at the cost of one extra wait."""
    try:
        page.wait_for_load_state("load", timeout=3_000)
    except Exception:
        pass
    page.wait_for_timeout(400)
    data = page.evaluate(EXTRACT_JS)
    text = data.get("text") or ""
    if len(text) < 500 and CLOUDFLARE_INTERSTITIAL_RE.search(text):
        page.wait_for_timeout(CLOUDFLARE_RETRY_WAIT_MS)
        retry = page.evaluate(EXTRACT_JS)
        if len(retry.get("text") or "") > len(text):
            data = retry
    try:
        data["html"] = page.content()
    except Exception:
        data["html"] = ""
    data["images"] = [urljoin(page.url, src) for src in data.get("images", [])]
    return data


# Per-source funnel counter keys (instrumentation only).
FUNNEL_KEYS = (
    "anchors_found", "candidates", "visited", "nav_errors",
    "dropped_undated", "dropped_old", "dropped_short", "dropped_junk", "kept",
)


def collect_source(page, limiter, source, cutoff_date, errors,
                   collected_at, budget_s=SOURCE_TIMEOUT_S,
                   index_phase_s=INDEX_PHASE_S, funnels=None, browser=None):
    """Return a list of fresh-article RECORDS for one source. Never raises.

    Each record is the per-article JSON object written to
    raw/concepts/<source_slug>/<url_hash>.json. funnels (optional dict) records
    this source's funnel counters under funnels[slug]. `browser` is only
    needed when source.get("fresh_context_per_article") is set (see Pass 2)."""
    slug = source["source_slug"]
    name = source.get("name", slug)
    funnel = {k: 0 for k in FUNNEL_KEYS}
    # Concepts sources carry a single index_url; wrap it into the URL list the
    # institutional crawl logic expects.
    urls = [source["index_url"]] if source.get("index_url") else []
    if not urls:
        log(f"  {slug}: no index_url — skipping")
        if funnels is not None:
            funnels[slug] = funnel
        return []

    apex = apex_domain(urlparse(urls[0]).netloc)
    # Optional PER-SOURCE article-detector override (NOT a global relaxation of
    # looks_like_article — that precision is depended on by the healthy sources).
    # Used for single-slug essay sites (e.g. Paul Graham: /<word>.html).
    extra_re = None
    if source.get("article_path_re"):
        try:
            extra_re = re.compile(source["article_path_re"], re.I)
        except re.error:
            log(f"  {slug}: bad article_path_re — ignoring")
    # Same idea as article_path_re but for the QUERY STRING — some sites key
    # articles by a query param rather than a path segment (e.g. SSRN:
    # papers.cfm?abstract_id=NNNNNNN has no year/doc-id/hyphens in the PATH at
    # all, so looks_like_article() never matches it however the path looks).
    query_re = None
    if source.get("article_query_re"):
        try:
            query_re = re.compile(source["article_query_re"], re.I)
        except re.error:
            log(f"  {slug}: bad article_query_re — ignoring")
    # Optional PER-SOURCE scope: only keep article links whose URL contains this
    # substring. Used when the listing lives on a subdomain that shares an apex
    # with a nav-heavy main site (e.g. NY Fed's Liberty Street Economics blog on
    # libertystreeteconomics.newyorkfed.org vs the www.newyorkfed.org nav). Does
    # NOT affect the shared looks_like_article detector or any other source.
    url_must = (source.get("url_must_contain") or "").lower()
    start = time.monotonic()
    seen = {norm_url(u) for u in urls}   # don't treat index pages as articles
    candidates = []
    records = []

    def over_budget():
        return (time.monotonic() - start) > budget_s

    # --- Pass 1: walk index page(s), gather article links ---
    # Hard caps per source: the index phase is bounded by index_phase_s and
    # pass-2 by budget_s (over_budget). Combined with navigate()'s 10/20s goto
    # timeouts, no single source can exceed ~budget_s + one in-flight navigate.
    index_deadline = start + index_phase_s
    for index_url in urls[:MAX_INDEX_PAGES]:
        if (time.monotonic() - start) > index_phase_s:
            log(f"  {slug}: index phase budget reached")
            break
        anchors = harvest_index(page, limiter, index_url, slug, errors,
                                deadline=index_deadline)
        funnel["anchors_found"] += len(anchors)
        for link in anchors:
            key = norm_url(link)
            if key in seen:
                continue
            is_article = looks_like_article(link, apex)
            if not is_article and extra_re is not None:
                parsed = urlparse(link)
                if (apex_domain(parsed.netloc) == apex
                        and extra_re.match(parsed.path)):
                    is_article = True
            if not is_article and query_re is not None:
                parsed = urlparse(link)
                if (apex_domain(parsed.netloc) == apex
                        and query_re.search(parsed.query)):
                    is_article = True
            if is_article and url_must and url_must not in link.lower():
                continue   # per-source scope: outside the allowed host/path
            if is_article:
                seen.add(key)
                candidates.append(link)
                funnel["candidates"] += 1

    # --- Pass 2: visit candidate articles, keep the recent ones ---
    skipped_old = junk = 0
    paywalled = bool(source.get("paywalled", False))
    category = source.get("category", "")
    stype = source.get("type", "")
    # Some sites (confirmed: ARK Invest) run bot-detection that flags the
    # BROWSER CONTEXT once it has visited the index/listing page — every
    # article page visited afterward in that SAME context then hard-fails a
    # Cloudflare challenge that never clears, no matter how long you wait.
    # A brand-new context (no shared cookies/fingerprint history) visiting
    # the SAME article URL directly passes immediately. So for opted-in
    # sources, Pass 2 opens ONE throwaway context per article instead of
    # reusing the shared `page` that just harvested the index.
    fresh_ctx = bool(source.get("fresh_context_per_article")) and browser is not None
    for article_url in candidates:
        if len(records) >= MAX_ARTICLES_PER_SOURCE:
            log(f"  {slug}: hit per-source article cap ({MAX_ARTICLES_PER_SOURCE})")
            break
        if over_budget():
            log(f"  {slug}: source time budget reached while reading articles")
            break
        limiter.wait()
        article_page = page
        article_context = None
        if fresh_ctx:
            article_context = browser.new_context(
                user_agent=USER_AGENT, viewport=DEFAULT_VIEWPORT,
                ignore_https_errors=True,
            )
            article_page = article_context.new_page()
            article_page.set_default_timeout(PAGE_TIMEOUT_MS)
        try:
            navigate(article_page, article_url)
            data = extract_article(article_page)
        except (PlaywrightTimeout, PlaywrightError) as exc:
            if article_context is not None:
                article_context.close()
            funnel["nav_errors"] += 1
            log(f"  WARN {slug}: article failed {article_url} — {type(exc).__name__}")
            errors.append({"source_slug": slug, "url": article_url,
                           "error": f"article: {type(exc).__name__}"})
            continue
        if article_context is not None:
            article_context.close()
        funnel["visited"] += 1

        pub_date = (extract_date(data.get("html", ""), article_url)
                    or parse_date(data.get("date_raw"))
                    or find_date_in_text(data.get("text")))
        if pub_date is not None and pub_date < cutoff_date:
            skipped_old += 1
            funnel["dropped_old"] += 1
            continue

        text = data.get("text", "")
        # is_junk reads url/title/text; build the minimal shape it expects.
        if is_junk({"url": article_url, "title": data.get("title", ""), "text": text}):
            junk += 1
            if too_short(text):
                funnel["dropped_short"] += 1
            else:
                funnel["dropped_junk"] += 1
            continue

        record = {
            "record_id": url_hash(article_url),
            "source_slug": slug,
            "source_name": name,
            "source_url": article_url,
            "category": category,
            "type": stype,
            "paywalled": paywalled,
            "title": data.get("title", ""),
            "published_date": pub_date.isoformat() if pub_date else "",
            "language": "en",
            "author": data.get("author", "") or "",
            "word_count": len((text or "").split()),
            "text": text,
            "image_urls": data.get("images", []),
            "collected_at": collected_at,
        }
        records.append(record)

    # --- Undated cap: keep at most the first 5 undated articles per source ---
    total_undated = sum(1 for r in records if not r["published_date"])
    if total_undated > 5:
        capped, seen_undated = [], 0
        for r in records:
            if not r["published_date"]:
                seen_undated += 1
                if seen_undated > 5:
                    funnel["dropped_undated"] += 1
                    continue
            capped.append(r)
        records = capped
        log(f"  {slug}: capped {total_undated} undated articles to 5")

    undated = sum(1 for r in records if not r["published_date"])
    funnel["kept"] = len(records)
    if funnels is not None:
        funnels[slug] = funnel
    log(f"  {slug}: {len(records)} new "
        f"(scanned {len(candidates)} candidates, "
        f"{skipped_old} old, {undated} undated, {junk} junk)")
    return records


RSS_AUTHOR_PAREN_RE = re.compile(r"\(([^)]+)\)\s*$")


def collect_source_rss(source, cutoff_date, collected_at, funnels=None,
                       timeout_s=30):
    """Return fresh-article RECORDS for a `fetch_mode: rss` source. Fetches the
    feed URL once (no Playwright, no per-article navigation) and reads the FULL
    article body straight out of each item's <description>/<content:encoded> —
    used for sources whose article pages CAPTCHA/bot-block headless browsers on
    a per-page-visit basis but whose RSS feed serves full text unblocked (e.g.
    Blogger's `?alt=rss` feed). Never raises; same record shape as
    collect_source() so it flows through write_source_records() unchanged."""
    import ssl
    import urllib.error
    import urllib.request
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    slug = source["source_slug"]
    name = source.get("name", slug)
    funnel = {k: 0 for k in FUNNEL_KEYS}
    rss_url = source.get("rss_url")
    if not rss_url:
        log(f"  {slug}: fetch_mode=rss but no rss_url — skipping")
        if funnels is not None:
            funnels[slug] = funnel
        return []

    # Some local Python installs (esp. macOS python.org builds without the
    # "Install Certificates" step) lack a populated default cert store; prefer
    # certifi's bundle when available so this doesn't depend on machine setup.
    try:
        import certifi
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_ctx = ssl.create_default_context()

    req = urllib.request.Request(rss_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ssl_ctx) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        log(f"  WARN {slug}: rss fetch failed — {type(exc).__name__}: {exc}")
        if funnels is not None:
            funnels[slug] = funnel
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        log(f"  WARN {slug}: rss parse failed — {exc}")
        if funnels is not None:
            funnels[slug] = funnel
        return []

    items = root.findall(".//item")
    funnel["anchors_found"] = len(items)
    paywalled = bool(source.get("paywalled", False))
    category = source.get("category", "")
    stype = source.get("type", "")
    records = []
    skipped_old = junk = 0

    for item in items:
        link_el = item.find("link")
        title_el = item.find("title")
        desc_el = item.find("description")
        pubdate_el = item.find("pubDate")
        author_el = item.find("author")
        link = (link_el.text or "").strip() if link_el is not None else ""
        if not link:
            continue
        funnel["candidates"] += 1

        pub_date = None
        if pubdate_el is not None and pubdate_el.text:
            try:
                pub_date = parsedate_to_datetime(pubdate_el.text.strip()).date()
            except (TypeError, ValueError):
                pub_date = parse_date(pubdate_el.text)
        if pub_date is None:
            pub_date = date_from_url(link)

        funnel["visited"] += 1   # no separate navigate step; the feed IS the fetch

        if pub_date is not None and pub_date < cutoff_date:
            skipped_old += 1
            funnel["dropped_old"] += 1
            continue

        title = (title_el.text or "").strip() if title_el is not None else ""
        text = _html_to_text(desc_el.text or "") if desc_el is not None else ""
        author = ""
        if author_el is not None and author_el.text:
            m = RSS_AUTHOR_PAREN_RE.search(author_el.text.strip())
            author = m.group(1) if m else author_el.text.strip()

        if is_junk({"url": link, "title": title, "text": text}):
            junk += 1
            if too_short(text):
                funnel["dropped_short"] += 1
            else:
                funnel["dropped_junk"] += 1
            continue

        records.append({
            "record_id": url_hash(link),
            "source_slug": slug,
            "source_name": name,
            "source_url": link,
            "category": category,
            "type": stype,
            "paywalled": paywalled,
            "title": title,
            "published_date": pub_date.isoformat() if pub_date else "",
            "language": "en",
            "author": author,
            "word_count": len(text.split()),
            "text": text,
            "image_urls": [],
            "collected_at": collected_at,
        })

    total_undated = sum(1 for r in records if not r["published_date"])
    if total_undated > 5:
        capped, seen_undated = [], 0
        for r in records:
            if not r["published_date"]:
                seen_undated += 1
                if seen_undated > 5:
                    funnel["dropped_undated"] += 1
                    continue
            capped.append(r)
        records = capped

    funnel["kept"] = len(records)
    if funnels is not None:
        funnels[slug] = funnel
    log(f"  {slug}: {len(records)} new (rss: {len(items)} items, "
        f"{skipped_old} old, {junk} junk)")
    return records


def skip_reason_for(source, allow_residential=False):
    """Why this source is not Playwright-collected, or None to collect it.
    `collect: false` defers a source entirely; `paywalled: true` sources can't be
    scraped (auth/Cloudflare) and reach the owner by other channels.

    `residential_only: true` sources stay `collect: false` (so the normal
    cloud cron / unscoped daily run always skips them — they're genuinely
    unreachable from Actions IPs) but are ALLOWED when allow_residential=True
    (set via --residential, used only by the local residential-runner wrapper
    scripts). This is a deliberate opt-in gate, not a relaxation of `collect:
    false` in general — every other collect:false/paywalled source is still
    skipped even with --residential."""
    if source.get("collect") is False:
        if allow_residential and source.get("residential_only"):
            return None
        return source.get("skip_reason") or "deferred (collect=false)"
    if source.get("paywalled"):
        return source.get("skip_reason") or "paywalled"
    return None


def write_source_records(records):
    """Flush one source's per-article files immediately (crash-safe). Returns the
    count of NEW files written. Called right after each source so an interrupted
    run keeps everything collected so far instead of losing it all."""
    new = 0
    for rec in records:
        src_dir = RAW_ROOT / rec["source_slug"]
        src_dir.mkdir(parents=True, exist_ok=True)
        out_path = src_dir / f"{rec['record_id']}.json"
        if not out_path.exists():
            new += 1
        out_path.write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return new


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ids",
        help="comma-separated source SLUGS to run (default: all sources)",
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
        "--resume", action="store_true",
        help="resume today's run: skip sources already completed (per the run's "
             "progress.json) and continue where a prior invocation left off",
    )
    parser.add_argument(
        "--residential", action="store_true",
        help="allow collect:false sources tagged residential_only:true to run "
             "(used by the local residential-runner wrapper scripts for "
             "cloud-IP-blocked sources; every other collect:false/paywalled "
             "source is still skipped)",
    )
    args = parser.parse_args()

    def budget_for(_source):
        """Per-source (budget_s, index_phase_s). Concepts has no bank_bulge
        tier, so every source gets the same budget; --budget overrides the total
        and scales the index phase to keep the same share."""
        base_total, base_index = SOURCE_TIMEOUT_S, INDEX_PHASE_S
        if args.budget:
            return args.budget, round(args.budget * base_index / base_total)
        return base_total, base_index

    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config not found: {CONFIG_PATH}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = config.get("sources", [])
    # Derive a stable slug for each source up front (the config has no `id`).
    for s in sources:
        s["source_slug"] = slugify(s.get("name", ""))

    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        sources = [s for s in sources if s["source_slug"] in wanted]
        missing = wanted - {s["source_slug"] for s in sources}
        if missing:
            log(f"Unknown slugs ignored: {', '.join(sorted(missing))}")

    now = datetime.datetime.now(datetime.timezone.utc)
    collected_at = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    cutoff_date = (now - datetime.timedelta(days=args.days)).date()
    log(f"Collecting Concepts stream from {len(sources)} source(s); "
        f"keeping articles since {cutoff_date.isoformat()}")

    run_dir = RUNS_ROOT / now.strftime("%Y-%m-%d")
    progress_path = run_dir / "progress.json"

    errors = []
    funnels = {}
    skipped = []                       # paywalled / deferred — never attempted
    by_source = {}
    completed = []                     # slugs fully processed this run-day
    total_records = 0
    new_files = 0

    # --- resume: restore today's partial state so a re-kill continues, not restarts ---
    if args.resume and progress_path.exists():
        try:
            prev = json.loads(progress_path.read_text(encoding="utf-8"))
            funnels = prev.get("funnels", {}) or {}
            by_source = prev.get("by_source", {}) or {}
            errors = prev.get("errors", []) or []
            skipped = prev.get("skipped", []) or []
            completed = prev.get("completed", []) or []
            total_records = prev.get("total_articles", 0) or 0
            new_files = prev.get("new_files", 0) or 0
            log(f"RESUME: {len(completed)} source(s) already done; continuing")
        except (json.JSONDecodeError, OSError):
            log("RESUME: progress.json unreadable — starting fresh")

    completed_set = set(completed)
    skipped_set = {s["source_slug"] for s in skipped}
    limiter = RateLimiter(PAGE_DELAY_S)

    def write_progress(current=None):
        write_json(progress_path, {
            "collected_at": collected_at,
            "updated_at": datetime.datetime.now(datetime.timezone.utc)
                                   .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "lookback_days": args.days,
            "sources_total": len(sources),
            "current": current,
            "completed": completed,
            "sources_done": len(completed),
            "skipped": skipped,
            "by_source": by_source,
            "funnels": funnels,
            "errors": errors,
            "total_articles": total_records,
            "new_files": new_files,
        })

    write_progress()  # stamp an initial progress file so disk shows the run started

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
            slug = source["source_slug"]
            if slug in completed_set:        # already done (resume) — skip
                continue
            reason = skip_reason_for(source, allow_residential=args.residential)
            if reason:
                log(f"[{i}/{len(sources)}] {slug} — SKIP ({reason[:70]})")
                if slug not in skipped_set:
                    skipped.append({"source_slug": slug, "name": source.get("name"),
                                    "reason": reason})
                    skipped_set.add(slug)
                continue
            log(f"[{i}/{len(sources)}] {slug}")
            write_progress(current=slug)
            src_budget, src_index = budget_for(source)
            try:
                if source.get("fetch_mode") == "rss":
                    found = collect_source_rss(source, cutoff_date, collected_at,
                                               funnels=funnels)
                else:
                    found = collect_source(page, limiter, source, cutoff_date, errors,
                                           collected_at, budget_s=src_budget,
                                           index_phase_s=src_index, funnels=funnels,
                                           browser=browser)
            except Exception as exc:  # last-resort guard: never crash the run
                log(f"  WARN {slug}: unexpected error — {type(exc).__name__}: {exc}")
                errors.append({"source_slug": slug, "error": f"{type(exc).__name__}: {exc}"})
                found = []
            # --- crash-safe incremental flush: write this source NOW ---
            new_files += write_source_records(found)
            for rec in found:
                by_source[rec["source_slug"]] = by_source.get(rec["source_slug"], 0) + 1
            total_records += len(found)
            completed.append(slug)
            completed_set.add(slug)
            write_progress()

        browser.close()

    skipped_slugs = {s["source_slug"] for s in skipped}

    # --- per-source funnel instrumentation (counters only) ---
    # Only sources that were actually attempted appear in the funnel; skipped
    # (paywalled/deferred) sources are reported separately and must NOT be flagged
    # as empty listings.
    for s in sources:
        if s["source_slug"] not in skipped_slugs:
            funnels.setdefault(s["source_slug"], {k: 0 for k in FUNNEL_KEYS})
    # Listing-health flags: a verify_listing source that yielded 0 candidates
    # almost certainly has a wrong/blocked index_url.
    verify_by_slug = {s["source_slug"]: bool(s.get("verify_listing", False))
                      for s in sources}
    listing_empty = sorted(
        slug for slug, f in funnels.items() if f["candidates"] == 0
    )

    cols = list(FUNNEL_KEYS)
    labels = ["source", "anchors", "candidates", "visited", "nav_err",
              "undated", "old", "short", "junk", "kept"]
    flines = [f"{labels[0]:30}" + "".join(f"{h:>11}" for h in labels[1:]),
              "-" * (30 + 11 * len(cols))]
    for slug in sorted(funnels, key=lambda k: (funnels[k]["kept"], k)):
        f = funnels[slug]
        flines.append(f"{slug[:29]:30}" + "".join(f"{f[c]:>11}" for c in cols))
    funnel_table = "\n".join(flines)
    print(funnel_table)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "funnel.txt").write_text(funnel_table + "\n", encoding="utf-8")
    funnel_payload = {
        "collected_at": collected_at,
        "columns": cols,
        "notes": [
            "Counters only — collection behavior is unchanged.",
            "candidates = anchors that passed looks_like_article (after dedup).",
            "visited = article pages where navigate+extract both succeeded.",
            "dropped_old = pub_date < cutoff (recency gate).",
            "dropped_short/dropped_junk split the single is_junk drop by reason.",
            "dropped_undated = undated items removed by the >5 per-source cap.",
            "kept = per-article files written (after the undated cap).",
        ],
        "sources": funnels,
    }
    (run_dir / "funnel.json").write_text(
        json.dumps(funnel_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- run manifest (freshness-gate compatible: top-level collected_at) ---
    run_payload = {
        "collected_at": collected_at,
        "lookback_days": args.days,
        "sources_processed": len(sources),
        "sources_attempted": len(sources) - len(skipped),
        "sources_skipped": len(skipped),
        "total_articles": total_records,
        "new_files": new_files,
        "by_source": by_source,
        "listing_empty": listing_empty,
        "listing_empty_verify": [s for s in listing_empty if verify_by_slug.get(s)],
        "skipped": skipped,
        "errors": errors,
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- summary ---
    log("=" * 60)
    log(f"DONE: {total_records} article(s) ({new_files} new file(s)) from "
        f"{len(by_source)} source(s); {len(sources) - len(skipped)} attempted, "
        f"{len(skipped)} skipped; {len(errors)} error(s)")
    for slug in sorted(by_source, key=lambda k: -by_source[k]):
        log(f"  {slug:<34}{by_source[slug]}")
    if skipped:
        log(f"SKIPPED (paywalled/deferred — not attempted): {len(skipped)}")
        for s in skipped:
            log(f"  {s['source_slug']:<32} {s['reason'][:60]}")
    if listing_empty:
        log(f"LISTING EMPTY (0 candidates) — verify index_url: {len(listing_empty)}")
        for slug in listing_empty:
            flag = " [verify_listing]" if verify_by_slug.get(slug) else ""
            log(f"  {slug}{flag}")
    if errors:
        log(f"Errors ({len(errors)}):")
        for e in errors[:20]:
            log(f"  {e.get('source_slug', '?')}: {e.get('error', '')}")
    log(f"Raw:    {RAW_ROOT.relative_to(REPO_ROOT)}/<slug>/<hash>.json")
    log(f"Run:    {(run_dir / 'run.json').relative_to(REPO_ROOT)}")
    log(f"Funnel: {(run_dir / 'funnel.json').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
