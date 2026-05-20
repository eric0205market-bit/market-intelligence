#!/usr/bin/env python3
"""Collect tweets from GetXAPI for the Market Intelligence platform.

Two collection streams:
  A) Watchlist accounts from config/twitter_watchlist.txt, batched 15 per query.
  B) Hardcoded institutional-research keyword searches.

Same-author thread replies are merged into single items. Output is written to
raw/twitter/YYYY-MM-DD_HHMM/tweets.json (UTC timestamp).

Run:  GETXAPI_KEY=xxxxx python3 scripts/collect_twitter.py
"""

import datetime
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

# --- GetXAPI endpoint -------------------------------------------------------
# These are the only knobs to change if the provider's request shape differs.
API_URL = "https://api.getxapi.com/twitter/tweet/advanced_search"
QUERY_PARAM = "q"          # name of the search-query parameter
PRODUCT_PARAM = "product"  # name of the result-type parameter
PRODUCT_VALUE = "Latest"   # newest-first ordering
AUTH_HEADER = "Authorization"
AUTH_PREFIX = "Bearer "

# --- Tunables ---------------------------------------------------------------
REQUEST_TIMEOUT = 30          # seconds
SLEEP_BETWEEN_CALLS = 0.5     # seconds, basic rate limiting
COST_PER_CALL_USD = 0.001
WATCHLIST_BATCH_SIZE = 15
WATCHLIST_MAX_PAGES = 3       # safety cap per batch
RESEARCH_MAX_PAGES = 1        # one page (~20 results) per research query
WATCHLIST_LOOKBACK_HOURS = 14 # overlap with previous run is acceptable
RESEARCH_LOOKBACK_HOURS = 12  # research searches were pulling years-old tweets

URL_RE = re.compile(r"https?://[^\s]+")

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = REPO_ROOT / "config" / "twitter_watchlist.txt"
OUTPUT_ROOT = REPO_ROOT / "raw" / "twitter"

RESEARCH_SEARCHES = [
    # Major banks
    '"JPM research" OR "JPMorgan research"',
    '"Goldman Sachs research" OR "GS research"',
    '"Morgan Stanley research"',
    '"Barclays research"',
    '"BofA research" OR "Bank of America research"',
    '"UBS research"',
    '"Citi research" OR "Citigroup research"',
    '"Deutsche Bank research"',
    '"Nomura research"',
    '"HSBC research"',
    # European & other banks
    '"SocGen research" OR "Societe Generale research"',
    '"BNP Paribas research"',
    '"Jefferies research"',
    '"Wells Fargo research"',
    '"RBC Capital" OR "RBC research"',
    '"Macquarie research"',
    '"Bernstein research"',
    '"Evercore ISI" OR "Evercore research"',
    '"Mizuho research"',
    '"Standard Chartered research"',
    '"CLSA research"',
    # Institutional research houses
    '"Torsten Slok" OR "Apollo research"',
    '"PIMCO" research',
    '"Renaissance Macro" OR "RenMac"',
    '"Strategas research" OR "Strategas"',
    '"Cornerstone Macro"',
    '"Ned Davis Research" OR "NDR research"',
    '"DataTrek" research',
]


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def build_query(core, lookback_hours):
    """Wrap the OR group in parens (so the trailing operators bind to the whole
    group, not just the last term) and constrain to a recent time window.

    `since_time:` takes epoch seconds; if the provider ignores it, the
    post-fetch created_at filter still trims anything older than the window.
    """
    since_epoch = int((datetime.datetime.now(datetime.timezone.utc)
                       - datetime.timedelta(hours=lookback_hours)).timestamp())
    return f"({core}) -filter:retweets since_time:{since_epoch}"


def load_watchlist():
    """Return de-duplicated handles (no @, no blanks/comments). Empty if missing."""
    if not WATCHLIST_PATH.exists():
        log(f"Watchlist not found at {WATCHLIST_PATH} — research searches only")
        return []
    accounts = []
    for line in WATCHLIST_PATH.read_text(encoding="utf-8").splitlines():
        handle = line.strip().lstrip("@").strip()
        if handle and not handle.startswith("#"):
            accounts.append(handle)
    return list(dict.fromkeys(accounts))


# --- Response parsing (defensive — provider field names can vary) -----------

def _first(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


def extract_tweet_list(payload):
    if not isinstance(payload, dict):
        return []
    for key in ("tweets", "results", "data"):
        val = payload.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for inner in ("tweets", "results"):
                if isinstance(val.get(inner), list):
                    return val[inner]
    return []


def extract_pagination(payload):
    """Return (cursor, has_more)."""
    if not isinstance(payload, dict):
        return None, False
    cursor = (payload.get("next_cursor") or payload.get("cursor")
              or payload.get("next_page"))
    has_more = payload.get("has_more")
    if has_more is None:
        has_more = payload.get("has_next_page")
    if has_more is None:
        has_more = bool(cursor)
    return cursor, bool(has_more)


def parse_created_at(value):
    if not value:
        return None
    value = str(value)
    iso_formats = (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for fmt in iso_formats:
        try:
            dt = datetime.datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except ValueError:
            pass
    # Classic Twitter format: "Tue May 19 14:30:00 +0000 2026"
    try:
        return datetime.datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None


def extract_urls(raw, text=""):
    """Prefer expanded URLs from entities; fall back to URLs in the tweet text
    (the API may not return a populated entities block)."""
    urls = []
    entities = _first(raw, "entities", default={}) or {}
    for u in (entities.get("urls") or []):
        expanded = _first(u, "expanded_url", "expandedUrl", "unwound_url", "url")
        if expanded:
            urls.append(expanded)
    if not urls and text:
        urls = [m.rstrip(".,);]") for m in URL_RE.findall(text)]
    return list(dict.fromkeys(urls))


def extract_images(raw):
    images = []
    containers = []
    for key in ("extendedEntities", "extended_entities", "entities"):
        container = _first(raw, key, default={})
        if isinstance(container, dict):
            containers.append(container)
    if isinstance(raw.get("media"), list):
        containers.append({"media": raw["media"]})
    for container in containers:
        for m in (container.get("media") or []):
            mtype = _first(m, "type", default="")
            if mtype in ("photo", "image", "animated_gif", ""):
                url = _first(m, "media_url_https", "media_url", "mediaUrl",
                             "media_url_large", "url")
                if url:
                    images.append(url)
    return list(dict.fromkeys(images))


def to_iso_z(dt, fallback):
    if dt is None:
        return fallback
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def normalize_tweet(raw, source, search_query=None):
    """Map a provider tweet object onto our output schema.

    Internal helper keys (prefixed with '_') are used for thread detection and
    stripped before the tweet is written to disk.
    """
    author = _first(raw, "author", "user", default={}) or {}
    created_raw = _first(raw, "created_at", "createdAt", "date")
    created_dt = parse_created_at(created_raw)
    text = _first(raw, "text", "full_text", "fullText", default="")

    quoted = _first(raw, "quoted_tweet", "quotedTweet", "quoted_status")
    if isinstance(quoted, dict):
        is_quote = True
        quoted_text = _first(quoted, "text", "full_text", "fullText")
    else:
        is_quote = bool(_first(raw, "is_quote", "isQuote", default=False))
        quoted_text = None

    return {
        "id": str(_first(raw, "id", "id_str", "tweet_id", default="")),
        "text": text,
        "author_username": _first(author, "userName", "username", "screen_name",
                                  "handle", default=""),
        "author_name": _first(author, "name", "displayName", default=""),
        "author_followers": _first(author, "followers", "followers_count",
                                   "followersCount", default=0),
        "created_at": to_iso_z(created_dt, created_raw),
        "likes": _first(raw, "likeCount", "likes", "favorite_count",
                        "favoriteCount", default=0),
        "retweets": _first(raw, "retweetCount", "retweets", "retweet_count",
                           default=0),
        "replies": _first(raw, "replyCount", "replies", "reply_count", default=0),
        "is_quote": is_quote,
        "quoted_tweet_text": quoted_text,
        "is_thread": False,
        "thread_tweets": None,
        "full_text": text,
        "urls": extract_urls(raw, text),
        "images": extract_images(raw),
        "source": source,
        "search_query": search_query,
        "_in_reply_to_id": _first(raw, "inReplyToId", "in_reply_to_status_id_str",
                                  "in_reply_to_id"),
        "_in_reply_to_username": _first(raw, "inReplyToUsername",
                                        "in_reply_to_screen_name"),
        "_conversation_id": _first(raw, "conversationId", "conversation_id"),
        "_created_dt": created_dt,
    }


def strip_internal(tweet):
    return {k: v for k, v in tweet.items() if not k.startswith("_")}


# --- API call ---------------------------------------------------------------

def api_search(api_key, query, max_pages):
    """Paginated search. Returns (list_of_raw_tweets, api_calls_made).

    On any error the current query is abandoned and whatever was collected so
    far is returned, so one bad call never stops the whole run.
    """
    headers = {AUTH_HEADER: f"{AUTH_PREFIX}{api_key}"}
    collected = []
    calls = 0
    cursor = None
    for page in range(max_pages):
        params = {QUERY_PARAM: query, PRODUCT_PARAM: PRODUCT_VALUE}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = requests.get(API_URL, headers=headers, params=params,
                                timeout=REQUEST_TIMEOUT)
            calls += 1
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - boundary, log and move on
            log(f"  ! API error (page {page + 1}): {exc}")
            break
        tweets = extract_tweet_list(payload)
        collected.extend(tweets)
        log(f"  page {page + 1}: {len(tweets)} tweets")
        time.sleep(SLEEP_BETWEEN_CALLS)
        cursor, has_more = extract_pagination(payload)
        if not tweets or not has_more or not cursor:
            break
    return collected, calls


# --- Thread detection -------------------------------------------------------

def detect_threads(tweets):
    """Merge same-author reply chains into single thread items.

    Two signals union tweets into a thread:
      1. A reply whose parent (by id) is present and shares the author.
      2. Same author + same conversation id (the whole chain shares one).
    """
    valid = [t for t in tweets if t.get("id")]
    parent = {t["id"]: t["id"] for t in valid}
    id_map = {t["id"]: t for t in valid}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Signal 1: reply chain to same author within the collected set.
    for t in valid:
        rid = t.get("_in_reply_to_id")
        if rid and str(rid) in id_map:
            parent_tweet = id_map[str(rid)]
            same_author = (
                (parent_tweet.get("author_username") or "").lower()
                == (t.get("author_username") or "").lower()
            )
            if same_author:
                union(t["id"], str(rid))

    # Signal 2: same author + same conversation id.
    conv_groups = defaultdict(list)
    for t in valid:
        conv = t.get("_conversation_id")
        if conv:
            key = ((t.get("author_username") or "").lower(), str(conv))
            conv_groups[key].append(t)
    for members in conv_groups.values():
        if len(members) > 1:
            base = members[0]["id"]
            for m in members[1:]:
                union(base, m["id"])

    groups = defaultdict(list)
    for t in valid:
        groups[find(t["id"])].append(t)

    items = []
    for members in groups.values():
        if len(members) == 1:
            items.append(strip_internal(members[0]))
        else:
            members.sort(key=lambda t: t.get("_created_dt")
                         or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc))
            items.append(merge_thread(members))
    # Pass through any tweets that lacked an id (rare).
    items.extend(strip_internal(t) for t in tweets if not t.get("id"))
    return items


def merge_thread(members):
    head = strip_internal(members[0])
    combined = "\n\n".join((m.get("text") or "").strip()
                           for m in members if (m.get("text") or "").strip())
    urls, images = [], []
    for m in members:
        urls.extend(m.get("urls") or [])
        images.extend(m.get("images") or [])
    head["is_thread"] = True
    head["thread_tweets"] = [strip_internal(m) for m in members]
    head["full_text"] = combined
    head["urls"] = list(dict.fromkeys(urls))
    head["images"] = list(dict.fromkeys(images))
    return head


# --- Main -------------------------------------------------------------------

def main():
    api_key = os.environ.get("GETXAPI_KEY")
    if not api_key:
        log("ERROR: GETXAPI_KEY environment variable not set")
        sys.exit(1)

    accounts = load_watchlist()
    log(f"Loaded {len(accounts)} watchlist accounts")

    # Set TWITTER_DEBUG_RAW=1 to dump raw API objects for schema debugging.
    debug_raw = os.environ.get("TWITTER_DEBUG_RAW") == "1"
    raw_samples = []
    raw_empty_author = []

    def capture(raw, normalized_tweet):
        if not debug_raw:
            return
        if len(raw_samples) < 8:
            raw_samples.append(raw)
        if not normalized_tweet["author_username"] and len(raw_empty_author) < 8:
            raw_empty_author.append(raw)

    normalized = []
    api_calls = 0
    now = datetime.datetime.now(datetime.timezone.utc)
    watchlist_cutoff = now - datetime.timedelta(hours=WATCHLIST_LOOKBACK_HOURS)
    research_cutoff = now - datetime.timedelta(hours=RESEARCH_LOOKBACK_HOURS)

    # --- Stream A: watchlist ---
    batches = list(chunked(accounts, WATCHLIST_BATCH_SIZE))
    for i, batch in enumerate(batches, 1):
        query = build_query(" OR ".join(f"from:{a}" for a in batch),
                            WATCHLIST_LOOKBACK_HOURS)
        log(f"Watchlist batch {i}/{len(batches)} ({len(batch)} accounts)")
        raws, calls = api_search(api_key, query, WATCHLIST_MAX_PAGES)
        api_calls += calls
        for raw in raws:
            t = normalize_tweet(raw, "watchlist")
            if t["_created_dt"] is not None and t["_created_dt"] < watchlist_cutoff:
                continue  # outside the lookback window
            normalized.append(t)
            capture(raw, t)

    # --- Stream B: institutional research searches ---
    for i, query in enumerate(RESEARCH_SEARCHES, 1):
        full_query = build_query(query, RESEARCH_LOOKBACK_HOURS)
        log(f"Research search {i}/{len(RESEARCH_SEARCHES)}: {query[:60]}")
        raws, calls = api_search(api_key, full_query, RESEARCH_MAX_PAGES)
        api_calls += calls
        for raw in raws:
            t = normalize_tweet(raw, "research_search", query)
            if t["_created_dt"] is not None and t["_created_dt"] < research_cutoff:
                continue  # drop stale results the time operator may have missed
            normalized.append(t)
            capture(raw, t)

    # --- Deduplicate by tweet id across both streams (keep first seen) ---
    deduped = []
    seen = set()
    for t in normalized:
        tid = t.get("id")
        if tid and tid in seen:
            continue
        if tid:
            seen.add(tid)
        deduped.append(t)

    watchlist_count = sum(1 for t in deduped if t["source"] == "watchlist")
    research_count = sum(1 for t in deduped if t["source"] == "research_search")

    # --- Thread detection (also strips internal helper fields) ---
    items = detect_threads(deduped)
    thread_count = sum(1 for t in items if t.get("is_thread"))

    out_dir = OUTPUT_ROOT / now.strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tweets.json"

    output = {
        "collected_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "watchlist_accounts": len(accounts),
        "research_searches": len(RESEARCH_SEARCHES),
        "total_tweets": len(deduped),
        "total_threads": thread_count,
        "watchlist_tweets": watchlist_count,
        "research_search_tweets": research_count,
        "api_calls_made": api_calls,
        "estimated_cost_usd": round(api_calls * COST_PER_CALL_USD, 4),
        "tweets": items,
    }

    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    if debug_raw:
        debug_path = out_dir / "_raw_sample.json"
        debug_path.write_text(json.dumps({
            "note": ("Raw API tweet objects for schema debugging. 'samples' = "
                     "first objects seen; 'empty_author_samples' = objects whose "
                     "author_username came out empty."),
            "samples": raw_samples,
            "empty_author_samples": raw_empty_author,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"DEBUG: wrote {len(raw_samples)} samples + "
            f"{len(raw_empty_author)} empty-author samples to {debug_path.name}")

    log("=" * 50)
    log(f"Saved {out_path.relative_to(REPO_ROOT)}")
    log(f"  total tweets (unique): {len(deduped)}")
    log(f"  threads detected:      {thread_count}")
    log(f"  watchlist tweets:      {watchlist_count}")
    log(f"  research tweets:       {research_count}")
    log(f"  API calls made:        {api_calls}")
    log(f"  estimated cost (USD):  {output['estimated_cost_usd']}")
    log("=" * 50)


if __name__ == "__main__":
    main()
