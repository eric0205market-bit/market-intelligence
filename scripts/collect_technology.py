#!/usr/bin/env python3
"""Daily Technology-stream scraper for the Market Intelligence KNOWLEDGE track.

Clone of scripts/collect_concepts.py. Same deterministic Playwright machinery
(settle_index, looks_like_article, junk filter, layered extract_date, per-source
funnel, --days recency gate, per-source timeout, retry/backoff, crash-safe flush);
NO LLM. Emits the identical per-article record shape; the extraction routine
(routines/routine_technology.md) produces the SAME KNOWLEDGE card atom with
source_type="technology" (docs/KNOWLEDGE_CARD_SCHEMA.md, unchanged shared contract).

ONE deliberate addition over Concepts: TRIAGE.

  Concepts is Deep+Data only -> extract everything. Technology is Flow-heavy
  (67 sources = 17 Deep + 50 Flow). Extracting every Flow article would be noisy
  and burn Opus, so the collector triages at INPUT — it decides which articles
  get WORKLISTED (written to raw/) before the expensive extraction step. Triage is
  deterministic (no LLM), exactly like the rest of the collector's filtering. It
  cuts what is collected/worklisted, NOT what is extracted: extraction stays
  "one source per subagent", unchanged from Concepts.

  Per source TYPE:
    Deep  (type=="Deep")  -> extract-all, no triage gate (like Concepts).
    Flow  (type=="Flow")  -> an article is worklisted ONLY IF it
            (a) matches the WATCHLIST (>=1 curated term in title+body,
                case-insensitive, token/word-boundary so "AI" != "again"), then
            (b) passes the existing RECENCY gate (--days window), then
            (c) survives the PER-SOURCE CAP: keep at most N_FLOW newest per run.
    FIREHOSE (Flow sources the curation flagged high-volume/aggregator in
            config _triage.flagged_high_volume_or_aggregator — ArXiv cs.AI,
            ArXiv cs.LG, Hacker News) -> same watchlist gate, strictest cap
            N_FIREHOSE (< N_FLOW); never any un-gated articles.

  The watchlist lives in config/technology_watchlist.json — an OWNER-CURATED flat
  term list (tickers, company names, technologies, agenda themes). If it is empty
  or missing, the watchlist gate is DISABLED (pass-through) with a loud warning,
  so the collector still runs while the owner curates it.

FUNNEL (numbers reconcile per source):
    Deep:  fetched -> recency_passed -> (quality) -> worklisted
    Flow:  fetched -> recency_passed -> watchlist_passed -> capped -> worklisted
Per-run diagnostics (funnel + manifest) land in
    raw/technology/_runs/<YYYY-MM-DD>/{funnel.txt,funnel.json,run.json}
Dirs whose name starts with "_" are run artifacts, never a source slug.

The scraper is defensive: a source that times out, blocks, or errors is logged as
a warning and skipped — the run never crashes. Window-based collection (--days)
self-heals missed days.

Setup:
    pip install playwright && playwright install chromium

Run:
    python3 scripts/collect_technology.py                       # all sources, --days 3
    python3 scripts/collect_technology.py --ids semianalysis,hacker_news_top_stories
    python3 scripts/collect_technology.py --days 7 --budget 180
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
CONFIG_PATH = REPO_ROOT / "config" / "technology_sources.json"
WATCHLIST_PATH = REPO_ROOT / "config" / "technology_watchlist.json"
RAW_ROOT = REPO_ROOT / "raw" / "technology"
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

# --- TRIAGE tunables --- TUNE AFTER CANARY ----------------------------------
# Per-source caps on how many newest articles a Flow source contributes per run.
# Deep sources are uncapped by triage (extract-all; still bounded by the
# MAX_ARTICLES_PER_SOURCE safety cap above). recency window = LOOKBACK_DAYS.
N_FLOW = 25        # max newest articles kept per Flow source per run     (TUNE)
N_FIREHOSE = 8     # stricter cap for high-volume/aggregator Flow sources (TUNE)

# Watchlist relevance gate. After the wide-diagnostic re-cut, Technology runs over
# a curated DURABLE-KNOWLEDGE source set (perishable news migrated to the FLOW /
# Newsletters track), so it does NOT gate Flow on the watchlist — Flow now means
# "recency + per-source cap only", identical to Deep on relevance. The watchlist /
# discovery-sample machinery below is retained intact for FUTURE streams (e.g.
# Society) that re-cut differently: flip this True to re-arm the entity gate.
WATCHLIST_GATE = False

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
    """Stable, filesystem-safe source slug derived from a source name."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "source"


def url_hash(url):
    """Stable short id for an article URL (dedup + filename)."""
    return hashlib.sha1(norm_url(url).encode("utf-8")).hexdigest()[:16]


# --- Watchlist (triage gate) ------------------------------------------------
def load_watchlist(path=WATCHLIST_PATH):
    """Load the owner-curated watchlist. Returns (terms, compiled_regex_or_None).

    The file is config/technology_watchlist.json with a flat `terms` list (string
    keys starting with "_" are documentation/header comments, ignored). The regex
    matches any term, case-insensitive, on ALPHANUMERIC boundaries so short tokens
    behave (e.g. "AI" matches "AI chips" but NOT "again" or "RAID"), while terms
    that contain punctuation ("GPT-4", "C++") still match cleanly.

    Returns regex=None when the watchlist is empty/missing — the caller then
    DISABLES the gate (pass-through) with a loud warning rather than dropping all
    Flow articles."""
    terms = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], None
    raw = data.get("terms") if isinstance(data, dict) else data
    for t in (raw or []):
        if isinstance(t, str) and t.strip():
            terms.append(t.strip())
    if not terms:
        return [], None
    # Longest-first so a combined alternation prefers the most specific match
    # (boolean result is order-independent, but it keeps the regex well-behaved).
    alts = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    rx = re.compile(r"(?<![A-Za-z0-9])(?:" + alts + r")(?![A-Za-z0-9])", re.I)
    return terms, rx


def watchlist_hit(text, rx):
    """True if any watchlist term occurs in text (token/word-boundary match).
    rx is None -> gate disabled -> always True (pass-through)."""
    if rx is None:
        return True
    return bool(rx.search(text or ""))


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
    "/our-firm/", "/who-we-are", "/terms-and-conditions", "/privacy", "/cookie",
    "/subscribe", "/newsletter", "/about/", "/about-us",
    "/programs/", "/program/", "/events/", "/event/",
)
MIN_TEXT_LEN = 100     # shorter than this (chars) = empty/nav page
MIN_ARTICLE_WORDS = 120  # research articles run long; below this is a teaser /
                         # landing / announcement stub, not extraction-worthy.

# Login-wall / member-profile pages (forum software like XenForo) tend to be
# just over MIN_ARTICLE_WORDS thanks to boilerplate ("Guests have limited
# access...", a PHP print_r()-style debug array dump of addon versions, etc.)
# so the word floor alone doesn't catch them — confirmed on SemiWiki
# (raw/technology/semiwiki/*.json member-profile records, title "Log in",
# body opens with a literal "Array\n(\n[content] => ..." dump). These are
# content-SHAPE signatures, not URL-shape, so they apply as a global backstop
# regardless of which source's link-discovery let the URL through.
LOGIN_WALL_TITLE_EXACT = ("log in", "sign in", "register")
PHP_DEBUG_DUMP_RE = re.compile(r"Array\s*\(\s*\[\w+\]\s*=>")
LOGIN_WALL_BODY_RE = re.compile(
    r"guests have limited access|you must be logged-in|"
    r"you must be logged in|register to (view|continue|reply)", re.I)


def too_short(text):
    """True if text is too short to be a real article body (char OR word floor)."""
    t = text or ""
    return len(t) < MIN_TEXT_LEN or len(t.split()) < MIN_ARTICLE_WORDS


def is_junk(article):
    """True if an article is boilerplate (legal/privacy/careers), a listing
    page, an empty/nav page, a login-wall/member-profile page, or sits at a
    junk URL path."""
    title = (article.get("title") or "").strip().lower()
    if title in LOGIN_WALL_TITLE_EXACT:
        return True
    text = article.get("text") or ""
    if PHP_DEBUG_DUMP_RE.search(text) or LOGIN_WALL_BODY_RE.search(text):
        return True
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


# --- paywall-teaser detection (deterministic, no LLM) ------------------------
# A short body carrying a subscribe/sign-in prompt is a paywall teaser, not
# the real article — same bug class as the SemiWiki login-wall case above,
# confirmed independently on Society's Foreign Affairs raw
# (raw/society/foreign_affairs/da11902084ae95ef.json): a 413-word teaser
# silently overwrote a good 2698-word raw on re-collection.
#
# Two signals combined: a known paywall-marker PHRASE is present, AND the
# total text is short. The length gate is LOAD-BEARING, not cosmetic — many
# sites emit the SAME subscribe/login footer on a full article as on its own
# teaser (site chrome present regardless of whether the article itself is
# paywalled), so marker presence alone false-positives on real long articles.
# Word count is what actually distinguishes "a 400-word preview with a
# subscribe wall" from "a 2500-word article with a subscribe ad at the
# bottom." Both conditions are required.
#
# Deliberately EXCLUDES a bare "already a subscriber? sign in/log in" pattern:
# tested against the real raw corpus and it false-positived on 9 of 10 hits,
# all on Wired — that phrase is a generic returning-user link Wired shows on
# every article regardless of length/completeness (a newsletter-signup nag,
# not a content gate), so it carries no real signal on its own. The confirmed
# real casualty (Foreign Affairs, raw/society/foreign_affairs/
# da11902084ae95ef.json) matches via "Subscribe to unlock" instead, which
# this pattern set still catches.
TEASER_MARKER_RE = re.compile(
    r"subscribe (now|to unlock|to continue|to read|to get)|"
    r"finish reading this article|"
    r"this is a subscriber-only feature|"
    r"sign in to continue|"
    r"unlock (this (article|feature)|access)|"
    r"get unlimited access to all|"
    r"enter your email and we.?ll send",
    re.I,
)
TEASER_MAX_WORDS = 700  # texts this short (or shorter) that also carry a
                        # paywall marker are almost certainly a teaser, not
                        # a complete article — well above MIN_ARTICLE_WORDS
                        # (120, the general junk floor) but comfortably below
                        # a real long-form piece.


def looks_like_teaser(text):
    """True if `text` reads as a paywall teaser rather than the full article:
    a known paywall-marker phrase is present AND the total text is no longer
    than TEASER_MAX_WORDS. Both conditions required — see the module comment
    above for why length (not marker presence alone) is load-bearing."""
    if not text:
        return False
    if len(text.split()) > TEASER_MAX_WORDS:
        return False
    return bool(TEASER_MARKER_RE.search(text))


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
# intermittently return 0 article links on the first hit.
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


def extract_article(page):
    """Run EXTRACT_JS, giving images a moment to load for width measurement."""
    try:
        page.wait_for_load_state("load", timeout=3_000)
    except Exception:
        pass
    page.wait_for_timeout(400)
    data = page.evaluate(EXTRACT_JS)
    try:
        data["html"] = page.content()
    except Exception:
        data["html"] = ""
    data["images"] = [urljoin(page.url, src) for src in data.get("images", [])]
    return data


# Per-source funnel counter keys (instrumentation only). The triage chain is
# explicit so the numbers reconcile per source:
#   Flow: fetched -> (−dropped_old) recency_passed -> (−dropped_short/junk/watchlist)
#         watchlist_passed -> (−dropped_capped) capped -> (−dropped_undated) worklisted
#   Deep: same chain with NO watchlist gate and NO triage cap (dropped_watchlist=0,
#         dropped_capped=0); watchlist_passed == quality-passed, capped == that count.
FUNNEL_KEYS = (
    "anchors_found", "candidates", "fetched", "nav_errors",
    "dropped_old", "recency_passed",
    "dropped_short", "dropped_junk",
    "dropped_watchlist", "watchlist_passed",
    "dropped_capped", "capped",
    "dropped_undated", "worklisted",
    "degrade_skipped",  # write_source_records() refused to overwrite a better
                        # existing raw file with a worse re-fetch — see the
                        # no-degrade guard there.
)


def triage_tier(source, firehose_slugs):
    """Classify a source for triage: 'Deep', 'Firehose', or 'Flow'.
    Deep -> extract-all. Firehose -> watchlist gate + strictest cap. Flow -> capped.

    The FIREHOSE flag OVERRIDES the type: the curation tagged a few high-volume
    aggregators (ArXiv cs.AI, cs.LG, Hacker News) as firehose even though two are
    typed "Deep". Per spec these get the watchlist gate and the strictest cap —
    never un-gated extract-all — so firehose is checked BEFORE the Deep policy."""
    if source["source_slug"] in firehose_slugs:
        return "Firehose"
    if (source.get("type") or "") == "Deep":
        return "Deep"
    return "Flow"


def collect_source(page, limiter, source, cutoff_date, errors, collected_at,
                   watchlist_rx, firehose_slugs, budget_s=SOURCE_TIMEOUT_S,
                   index_phase_s=INDEX_PHASE_S, funnels=None, tiers=None):
    """Return a list of fresh-article RECORDS for one source (after triage).
    Never raises. Each record is the per-article JSON written to
    raw/technology/<source_slug>/<url_hash>.json."""
    slug = source["source_slug"]
    name = source.get("name", slug)
    tier = triage_tier(source, firehose_slugs)
    is_deep = tier == "Deep"
    triage_cap = None if is_deep else (N_FIREHOSE if tier == "Firehose" else N_FLOW)
    if tiers is not None:
        tiers[slug] = tier
    funnel = {k: 0 for k in FUNNEL_KEYS}
    # Technology sources carry a single index_url; wrap it into the URL list the
    # crawl logic expects.
    urls = [source["index_url"]] if source.get("index_url") else []
    if not urls:
        log(f"  {slug}: no index_url — skipping")
        if funnels is not None:
            funnels[slug] = funnel
        return []

    apex = apex_domain(urlparse(urls[0]).netloc)
    # Optional PER-SOURCE article-detector override (single-slug essays).
    extra_re = None
    if source.get("article_path_re"):
        try:
            extra_re = re.compile(source["article_path_re"], re.I)
        except re.error:
            log(f"  {slug}: bad article_path_re — ignoring")
    # Optional PER-SOURCE scope: only keep article links whose URL contains this
    # substring (host-restriction for blog-on-subdomain cases).
    url_must = (source.get("url_must_contain") or "").lower()
    # Optional PER-SOURCE exclusion: drop article links whose URL contains this
    # substring, even though it otherwise looks_like_article(). Used when a
    # source's real articles and its junk pages share the same URL SHAPE (e.g.
    # SemiWiki: /forum/threads/<id> is a real article, /forum/members/<id> is
    # a login-wall profile page — both have a 4+ digit numeric path segment,
    # so looks_like_article() can't tell them apart by shape alone).
    url_must_not = (source.get("url_must_not_contain") or "").lower()
    start = time.monotonic()
    seen = {norm_url(u) for u in urls}   # don't treat index pages as articles
    candidates = []
    records = []

    def over_budget():
        return (time.monotonic() - start) > budget_s

    # --- Pass 1: walk index page(s), gather article links ---
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
            if is_article and url_must and url_must not in link.lower():
                continue   # per-source scope: outside the allowed host/path
            if is_article and url_must_not and url_must_not in link.lower():
                continue   # per-source exclusion: same URL shape, known-junk path
            if is_article:
                seen.add(key)
                candidates.append(link)
                funnel["candidates"] += 1

    # --- Pass 2: visit candidate articles, apply recency + quality + TRIAGE ---
    skipped_old = junk = off_watchlist = 0
    paywalled = bool(source.get("paywalled", False))
    category = source.get("category", "")
    stype = source.get("type", "")
    for article_url in candidates:
        if len(records) >= MAX_ARTICLES_PER_SOURCE:
            log(f"  {slug}: hit per-source article cap ({MAX_ARTICLES_PER_SOURCE})")
            break
        if over_budget():
            log(f"  {slug}: source time budget reached while reading articles")
            break
        limiter.wait()
        try:
            navigate(page, article_url)
            data = extract_article(page)
        except (PlaywrightTimeout, PlaywrightError) as exc:
            funnel["nav_errors"] += 1
            log(f"  WARN {slug}: article failed {article_url} — {type(exc).__name__}")
            errors.append({"source_slug": slug, "url": article_url,
                           "error": f"article: {type(exc).__name__}"})
            continue
        funnel["fetched"] += 1

        # (b) RECENCY gate (shared with Concepts) -------------------------------
        pub_date = (extract_date(data.get("html", ""), article_url)
                    or parse_date(data.get("date_raw"))
                    or find_date_in_text(data.get("text")))
        if pub_date is not None and pub_date < cutoff_date:
            skipped_old += 1
            funnel["dropped_old"] += 1
            continue
        funnel["recency_passed"] += 1

        text = data.get("text", "")
        title = data.get("title", "")
        # quality: is_junk reads url/title/text; build the minimal shape it expects.
        if is_junk({"url": article_url, "title": title, "text": text}):
            junk += 1
            if too_short(text):
                funnel["dropped_short"] += 1
            else:
                funnel["dropped_junk"] += 1
            continue

        # (a) WATCHLIST gate — DISABLED for Technology (durable extract-all set).
        # Retained behind WATCHLIST_GATE for future streams that DO want to filter
        # high-volume Flow feeds by entity/agenda. When off, Flow == Deep on
        # relevance (recency + per-source cap only); dropped_watchlist stays 0 and
        # watchlist_passed counts everything that cleared recency + quality.
        if WATCHLIST_GATE and not is_deep and not watchlist_hit(title + "\n" + text, watchlist_rx):
            off_watchlist += 1
            funnel["dropped_watchlist"] += 1
            continue
        funnel["watchlist_passed"] += 1

        record = {
            "record_id": url_hash(article_url),
            "source_slug": slug,
            "source_name": name,
            "source_url": article_url,
            "category": category,
            "type": stype,
            "paywalled": paywalled,
            "title": title,
            "published_date": pub_date.isoformat() if pub_date else "",
            "language": "en",
            "author": data.get("author", "") or "",
            "word_count": len((text or "").split()),
            "text": text,
            "teaser": looks_like_teaser(text),
            "image_urls": data.get("images", []),
            "collected_at": collected_at,
        }
        records.append(record)

    # --- (c) PER-SOURCE TRIAGE CAP: keep at most N newest (Flow/Firehose) ---
    # Deep is uncapped by triage. Sort newest-first; undated sort last so a dated
    # article is never dropped in favour of an undated one.
    if triage_cap is not None and len(records) > triage_cap:
        records.sort(key=lambda r: r["published_date"] or "", reverse=True)
        funnel["dropped_capped"] = len(records) - triage_cap
        records = records[:triage_cap]
        log(f"  {slug}: triage cap kept {triage_cap} newest of "
            f"{triage_cap + funnel['dropped_capped']} ({tier})")
    funnel["capped"] = len(records)

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
    funnel["worklisted"] = len(records)
    if funnels is not None:
        funnels[slug] = funnel
    log(f"  {slug} [{tier}]: {len(records)} worklisted "
        f"(scanned {len(candidates)} candidates, {skipped_old} old, "
        f"{off_watchlist} off-watchlist, {undated} undated, {junk} junk)")
    return records


def skip_reason_for(source):
    """Why this source is not Playwright-collected, or None to collect it."""
    if source.get("collect") is False:
        return source.get("skip_reason") or "deferred (collect=false)"
    if source.get("paywalled"):
        return source.get("skip_reason") or "paywalled"
    return None


# A re-fetch below this fraction of the EXISTING raw's word_count is treated
# as a degrade, not an update, and is refused (see write_source_records()).
# Tunable: 0.8 means a new fetch must retain at least 80% of the prior raw's
# length to be allowed to overwrite it.
DEGRADE_MIN_RATIO = 0.8


def write_source_records(records, funnels=None):
    """Flush one source's per-article files immediately (crash-safe). Returns
    the count of NEW files written.

    NO-DEGRADE GUARD: before overwriting an EXISTING raw file for a known
    record_id, compare the new fetch against what's already on disk:
      - a new record flagged `teaser` (see looks_like_teaser()) NEVER
        overwrites an existing non-teaser record, regardless of word_count —
        a paywall bounce is never "an update" to a real article;
      - otherwise, the new word_count must be >= DEGRADE_MIN_RATIO of the
        existing word_count, or the write is refused.
    A refused write is logged loudly (source, record_id, existing vs new
    word_count, url) and counted in that source's funnel as
    `degrade_skipped` so it surfaces in the run report instead of vanishing
    silently. The existing good raw is left untouched on disk. New
    record_ids (no existing file) always write, exactly as before — the
    guard applies to OVERWRITES only."""
    new = 0
    for rec in records:
        src_dir = RAW_ROOT / rec["source_slug"]
        src_dir.mkdir(parents=True, exist_ok=True)
        out_path = src_dir / f"{rec['record_id']}.json"

        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = None
            if existing is not None:
                existing_wc = existing.get("word_count") or 0
                new_wc = rec.get("word_count") or 0
                existing_is_teaser = bool(existing.get("teaser"))
                new_is_teaser = bool(rec.get("teaser"))
                degraded = (
                    (new_is_teaser and not existing_is_teaser)
                    or (existing_wc > 0 and new_wc < existing_wc * DEGRADE_MIN_RATIO)
                )
                if degraded:
                    reason = "new fetch is a paywall teaser" if new_is_teaser and not existing_is_teaser \
                        else f"new word_count below {int(DEGRADE_MIN_RATIO*100)}% of existing"
                    log(f"  DEGRADE_SKIPPED [{rec['source_slug']}] {rec['record_id']}: "
                        f"{reason} — existing={existing_wc}w new={new_wc}w "
                        f"url={rec.get('source_url')}")
                    if funnels is not None:
                        slug = rec["source_slug"]
                        funnels.setdefault(slug, {k: 0 for k in FUNNEL_KEYS})
                        funnels[slug]["degrade_skipped"] += 1
                    continue
        else:
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
    args = parser.parse_args()

    def budget_for(_source):
        """Per-source (budget_s, index_phase_s). Every source gets the same
        budget; --budget overrides the total and scales the index phase."""
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

    # Firehose set: sources the curation flagged high-volume/aggregator. Resolved
    # from config _triage by name, plus any source carrying a collection_note.
    flagged_names = set(
        (config.get("_triage") or {}).get("flagged_high_volume_or_aggregator", [])
    )
    firehose_slugs = {
        s["source_slug"] for s in sources
        if s.get("name") in flagged_names or s.get("collection_note")
    }

    # Watchlist (triage gate). Empty/missing -> gate disabled (pass-through).
    watchlist_terms, watchlist_rx = load_watchlist()
    if not WATCHLIST_GATE:
        log(f"Watchlist gate OFF for this stream (durable extract-all set); "
            f"{len(watchlist_terms)} term(s) loaded but unused. "
            f"Per-source caps still apply (N_FLOW={N_FLOW}, N_FIREHOSE={N_FIREHOSE}); "
            f"firehose sources: {sorted(firehose_slugs) or 'none'}")
    elif watchlist_rx is None:
        log("WARN: watchlist empty/missing — Flow watchlist gate DISABLED "
            "(pass-through). Curate config/technology_watchlist.json.")
    else:
        log(f"Watchlist: {len(watchlist_terms)} term(s) loaded; "
            f"firehose sources: {sorted(firehose_slugs) or 'none'}")

    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        sources = [s for s in sources if s["source_slug"] in wanted]
        missing = wanted - {s["source_slug"] for s in sources}
        if missing:
            log(f"Unknown slugs ignored: {', '.join(sorted(missing))}")

    now = datetime.datetime.now(datetime.timezone.utc)
    collected_at = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    cutoff_date = (now - datetime.timedelta(days=args.days)).date()
    log(f"Collecting Technology stream from {len(sources)} source(s); "
        f"keeping articles since {cutoff_date.isoformat()}")

    run_dir = RUNS_ROOT / now.strftime("%Y-%m-%d")
    progress_path = run_dir / "progress.json"

    errors = []
    funnels = {}
    tiers = {}
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
            tiers = prev.get("tiers", {}) or {}
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
            "tiers": tiers,
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
            reason = skip_reason_for(source)
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
                found = collect_source(page, limiter, source, cutoff_date, errors,
                                       collected_at, watchlist_rx, firehose_slugs,
                                       budget_s=src_budget, index_phase_s=src_index,
                                       funnels=funnels, tiers=tiers)
            except Exception as exc:  # last-resort guard: never crash the run
                log(f"  WARN {slug}: unexpected error — {type(exc).__name__}: {exc}")
                errors.append({"source_slug": slug, "error": f"{type(exc).__name__}: {exc}"})
                found = []
            # --- crash-safe incremental flush: write this source NOW ---
            new_files += write_source_records(found, funnels=funnels)
            for rec in found:
                by_source[rec["source_slug"]] = by_source.get(rec["source_slug"], 0) + 1
            total_records += len(found)
            completed.append(slug)
            completed_set.add(slug)
            write_progress()

        browser.close()

    skipped_slugs = {s["source_slug"] for s in skipped}

    # --- per-source funnel instrumentation (counters only) ---
    for s in sources:
        if s["source_slug"] not in skipped_slugs:
            funnels.setdefault(s["source_slug"], {k: 0 for k in FUNNEL_KEYS})
            tiers.setdefault(s["source_slug"], triage_tier(s, firehose_slugs))
    # Listing-health flags: a verify_listing source that yielded 0 candidates
    # almost certainly has a wrong/blocked index_url.
    verify_by_slug = {s["source_slug"]: bool(s.get("verify_listing", False))
                      for s in sources}
    listing_empty = sorted(
        slug for slug, f in funnels.items() if f["candidates"] == 0
    )

    cols = list(FUNNEL_KEYS)
    labels = ["source", "tier", "anchors", "cands", "fetched", "nav_err",
              "old", "recency", "short", "junk", "wl_drop", "wl_pass",
              "cap_drop", "capped", "undated", "worklist", "degraded"]
    header = f"{labels[0]:30}{labels[1]:>9}" + "".join(f"{h:>10}" for h in labels[2:])
    flines = [header, "-" * len(header)]
    for slug in sorted(funnels, key=lambda k: (funnels[k]["worklisted"], k)):
        f = funnels[slug]
        flines.append(
            f"{slug[:29]:30}{tiers.get(slug, '?'):>9}"
            + "".join(f"{f[c]:>10}" for c in cols)
        )
    funnel_table = "\n".join(flines)
    print(funnel_table)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "funnel.txt").write_text(funnel_table + "\n", encoding="utf-8")
    funnel_payload = {
        "collected_at": collected_at,
        "columns": cols,
        "triage": {
            "n_flow": N_FLOW,
            "n_firehose": N_FIREHOSE,
            "lookback_days": args.days,
            "watchlist_terms": len(watchlist_terms),
            "watchlist_enabled": watchlist_rx is not None,
            "firehose_slugs": sorted(firehose_slugs),
        },
        "tiers": tiers,
        "notes": [
            "Counters only — collection behavior is unchanged.",
            "candidates = anchors that passed looks_like_article (after dedup).",
            "fetched = article pages where navigate+extract both succeeded.",
            "dropped_old = pub_date < cutoff (recency gate); recency_passed = the rest.",
            "dropped_short/dropped_junk split the is_junk drop by reason.",
            "dropped_watchlist = Flow articles with no watchlist term (Deep: always 0).",
            "watchlist_passed = articles that reached record-build (passed recency, "
            "quality, and — for Flow — the watchlist).",
            "dropped_capped = removed by the per-source triage cap (N_FLOW/N_FIREHOSE; "
            "Deep: 0); capped = kept after that cap.",
            "dropped_undated = undated items removed by the >5 per-source cap.",
            "worklisted = per-article files written (final, after all caps).",
            "Flow chain: fetched -> recency_passed -> watchlist_passed -> capped -> worklisted.",
            "Deep chain: fetched -> recency_passed -> worklisted (no watchlist, no triage cap).",
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
        "tiers": tiers,
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
        log(f"  {slug:<34}{by_source[slug]}  [{tiers.get(slug, '?')}]")
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
