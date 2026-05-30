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

Pipeline (all in this one script):
  1. SEARCH  — config/research_pdf_sources.json: each source x each query term,
               Serper web search `"<name>" <term> filetype:pdf`.
  2. FILTER  — PDF gate, domain blacklist, title/snippet keyword gate, freshness
               (layered date extraction + post-hoc recency), URL/title dedup,
               optional dead-link check.
  3. RANK    — sort by (booster desc, date desc, undated last).
  4. WRITE   — data/research_pdfs/latest + dated archive, funnel.json/funnel.txt.
  5. RENDER  — reports/research_pdfs_<date>.html via the __REPORT_DATA__
               placeholder mechanism (same as institutional_report.html).

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
SERPER_NUM = 20               # results per query
SERPER_PAUSE = 0.4            # polite pause between Serper calls (s)
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
    "forrester.com",
}
# Suffix blacklist for wildcard domains (*.finance.yahoo.com etc.).
BLACKLIST_SUFFIXES = ("finance.yahoo.com", "libanswers.com", "libguides.com")
# URL-path fragments that mark course/library/slide junk regardless of host.
BLACKLIST_PATH_TERMS = ("virtual-library", "/course", "/slides")

KEEP_KEYWORDS = (
    "outlook", "macro", "economic", "economics", "strategy", "themes",
    "year ahead", "midyear", "mid-year", "house view", "capital market",
    "market outlook", "investment outlook", "perspectives", "weekly",
    "monthly", "chartbook", "cio", "allocation", "asset allocation",
    "views", "deep dive", "eye on the market", "daily spark", "market regime",
)
# Drop terms: factsheet/legal/filings boilerplate. Note we do NOT blanket-drop
# "earnings" — only "earnings results"/"results presentation" — so legit pieces
# like "Outlook for corporate earnings" survive.
DROP_KEYWORDS = (
    "factsheet", "fact sheet", "kiid", "kid ", "prospectus", "brochure",
    "nav", "performance summary", "terms of use", "privacy policy",
    "application form", "results presentation", "quarterly results",
    "earnings results", "8-k", "10-k", "10-q", "424b", "fwp",
    "x-17a-5", "proxy statement", "shelf registration",
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
    """Extract a date embedded in the URL path or filename, else None.
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


def extract_date(organic_date, url, today):
    """Layered: Serper organic.date -> date in URL/filename -> None."""
    return parse_serper_date(organic_date, today) or date_from_url(url)


def within_days(iso_date, days, today):
    if not iso_date:
        return False
    try:
        d = datetime.date.fromisoformat(iso_date)
    except ValueError:
        return False
    return 0 <= (today - d).days <= days


# --- Serper search ----------------------------------------------------------
def tbs_for_days(days, today):
    """Map the lookback window to a Serper freshness tbs token. Serper's tbs is
    fuzzy, so this is the FIRST of a belt-and-suspenders pair (post-hoc
    within_days() is the second)."""
    if days <= 7:
        return "qdr:w"
    if days <= 31:
        return "qdr:m"
    cd_min = (today - datetime.timedelta(days=days))
    return (f"cdr:1,cd_min:{cd_min.month}/{cd_min.day}/{cd_min.year},"
            f"cd_max:{today.month}/{today.day}/{today.year}")


def serper_search(query, api_key, tbs):
    """One Serper search; returns the organic list (may be empty). Never raises
    — a failed query is logged and treated as zero results."""
    body = {"q": query, "num": SERPER_NUM, "gl": "us", "hl": "en"}
    if tbs:
        body["tbs"] = tbs
    try:
        resp = requests.post(
            SERPER_ENDPOINT, json=body, timeout=REQUEST_TIMEOUT,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json().get("organic", []) or []
    except Exception as exc:
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
    tbs = tbs_for_days(args.days, today)
    boosters = institutional_booster_hosts()
    for s in load_sources():
        for d in s.get("booster_domains", []):
            boosters.add(d.lower())

    log(f"Research PDF Finder: {len(sources)} source(s), window {args.days}d "
        f"(tbs={tbs}); {len(boosters)} booster domains; "
        f"link-check={'off' if args.no_check_links else 'on'}; "
        f"undated={'drop' if args.drop_undated else 'keep'}")

    funnels = {s["id"]: {k: 0 for k in FUNNEL_KEYS} for s in sources}
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
            query = f'"{name}" {term} filetype:pdf'
            f["queries"] += 1
            organic = serper_search(query, api_key, tbs)
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
                    continue

                # (c) title/snippet keyword gate
                title = (o.get("title") or "").strip()
                snippet = (o.get("snippet") or "").strip()
                if not passes_title_gate(title, snippet):
                    f["titlegate"] += 1
                    continue

                # (d) freshness — layered date extraction + post-hoc recency
                iso = extract_date(o.get("date"), url, today)
                undated = iso is None
                if undated:
                    if args.drop_undated:
                        f["freshness"] += 1
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

    # --- RANK: booster desc, date desc, undated last ---
    kept.sort(key=lambda it: (
        not it["booster"],          # boosters first
        it["undated"],              # dated before undated
        _date_sort_key(it["date"]),  # newest first
    ))

    # --- by-source counts ---
    by_source = {}
    for it in kept:
        by_source[it["source_id"]] = by_source.get(it["source_id"], 0) + 1

    collected_at = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_str = now.strftime("%Y-%m-%d")
    payload = {
        "collected_at": collected_at,
        "lookback_days": args.days,
        "total": len(kept),
        "sources_processed": len(sources),
        "by_source": by_source,
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
    write_funnel(archive_dir, collected_at, funnels)

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
    log(f"Latest:  {_rel(latest_dir / LATEST_NAME)}")
    log(f"Archive: {_rel(archive_dir / LATEST_NAME)}")
    log(f"Report:  {_rel(report_path)}")
    if args.dry_run:
        log("DRY-RUN: wrote to /tmp only; no repo files changed, no commit.")


def write_funnel(out_dir, collected_at, funnels):
    cols = list(FUNNEL_KEYS)
    width = max((len(s) for s in funnels), default=6) + 2
    header = f"{'source':<{width}}" + "".join(f"{h:>11}" for h in cols)
    lines = [header, "-" * len(header)]
    for sid in sorted(funnels, key=lambda k: (funnels[k]["kept"], k)):
        row = funnels[sid]
        lines.append(f"{sid:<{width}}" + "".join(f"{row[c]:>11}" for c in cols))
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
            "freshness= dropped as out-of-window (or undated with --drop-undated).",
            "dedup    = dropped as duplicate URL or near-dup title.",
            "linkcheck= dropped by the dead-link / pdf-content-type check.",
            "kept     = PDFs written to output.",
        ],
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
