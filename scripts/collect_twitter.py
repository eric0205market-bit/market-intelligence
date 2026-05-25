#!/usr/bin/env python3
"""Collect tweets from GetXAPI for the Market Intelligence platform.

Two collection streams:
  A) Watchlist accounts (active = non-'delete' in config/twitter_classification.json),
     batched 15 per query.
  B) Hardcoded institutional-research keyword searches.

Same-author thread replies are merged into single items. Output is written under
raw/twitter/YYYY-MM-DD_HHMM/ (UTC timestamp):
  tweets.json                   full collection (all fields)
  tweets_for_routine.json       full collection, engagement fields stripped
  tweets_{alpha,data,shitpost}.json          per-category splits
  tweets_for_routine_{alpha,data}.json       per-category, engagement stripped

Run:  GETXAPI_KEY=xxxxx python3 scripts/collect_twitter.py
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
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
RESEARCH_LOOKBACK_HOURS = 14  # match watchlist window (was pulling years-old)

TCO_RE = re.compile(r"https://t\.co/\w+")
MAX_URL_RESOLUTIONS = 100     # cap t.co HEAD requests per run
URL_RESOLVE_TIMEOUT = 5       # seconds per t.co resolution
SELF_DOMAINS = ("x.com", "twitter.com", "t.co")  # dropped from final urls

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = REPO_ROOT / "config" / "twitter_watchlist.txt"
CLASSIFICATION_PATH = REPO_ROOT / "config" / "twitter_classification.json"
OUTPUT_ROOT = REPO_ROOT / "raw" / "twitter"

# Categories written to split files; 'delete' accounts are skipped entirely.
SPLIT_CATEGORIES = ("alpha", "data", "shitpost")
ROUTINE_CATEGORIES = ("alpha", "data")  # per-category routine files (no engagement)

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


def load_classification():
    """Return {handle: category} from twitter_classification.json, or {} if the
    file is missing/unparseable (caller falls back to the plain watchlist)."""
    if not CLASSIFICATION_PATH.exists():
        log(f"Classification not found at {CLASSIFICATION_PATH}")
        return {}
    try:
        data = json.loads(CLASSIFICATION_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        log(f"! Failed to parse classification: {exc}")
        return {}


def split_by_category(tweets, classification):
    """Bucket tweets by their author's category (case-insensitive). 'delete'
    authors are dropped; anyone not in the map lands in 'unclassified'."""
    lookup = {k.lower(): v for k, v in classification.items()}
    result = {"alpha": [], "data": [], "shitpost": [], "unclassified": []}
    for tweet in tweets:
        author = (tweet.get("author_username") or "").lower()
        category = lookup.get(author, "unclassified")
        if category == "delete":
            continue
        result.get(category, result["unclassified"]).append(tweet)
    return result


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


def collect_url_candidates(raw, text):
    """Return [{"tco", "resolved"}] from entities (already expanded) plus any
    t.co links found in the tweet text (resolved later, in a budgeted pass)."""
    candidates = []
    seen = set()
    entities = _first(raw, "entities", default={}) or {}
    for u in (entities.get("urls") or []):
        tco = _first(u, "url")
        resolved = _first(u, "expanded_url", "expandedUrl", "unwound_url")
        if not (tco or resolved):
            continue
        candidates.append({"tco": tco, "resolved": resolved})
        if tco:
            seen.add(tco)
        if resolved:
            seen.add(resolved)
    for match in TCO_RE.findall(text or ""):
        if match not in seen:
            seen.add(match)
            candidates.append({"tco": match, "resolved": None})
    return candidates


def resolve_tco(url):
    """Follow redirects to a t.co's destination. Returns None on failure."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=URL_RESOLVE_TIMEOUT)
        return r.url
    except Exception:  # noqa: BLE001 - network boundary
        return None


def is_external(url):
    """True if the URL is not an x.com / twitter.com / t.co self-link."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return True
    host = host.split("@")[-1].split(":")[0]
    return not any(host == d or host.endswith("." + d) for d in SELF_DOMAINS)


def resolve_and_finalize_urls(tweets, budget=MAX_URL_RESOLUTIONS):
    """Resolve t.co links (research_search tweets first), then write each
    tweet's final ``urls`` list of {tco, resolved}, dropping self-links.

    Returns the number of HEAD requests actually made.
    """
    cache = {}
    used = 0
    ordered = sorted(
        tweets, key=lambda t: 0 if t.get("source") == "research_search" else 1)
    for t in ordered:
        for cand in t.get("_url_candidates", []):
            tco = cand.get("tco")
            if cand.get("resolved") is not None or not tco:
                continue
            if tco in cache:
                cand["resolved"] = cache[tco]
            elif used < budget:
                resolved = resolve_tco(tco)
                cache[tco] = resolved
                cand["resolved"] = resolved
                used += 1
            # over budget: leave resolved=None (keep the raw t.co)

    for t in tweets:
        final = []
        seen = set()
        for cand in t.get("_url_candidates", []):
            resolved = cand.get("resolved")
            if resolved and not is_external(resolved):
                continue  # drop self-links once we know the destination
            key = resolved or cand.get("tco")
            if not key or key in seen:
                continue
            seen.add(key)
            final.append({"tco": cand.get("tco"), "resolved": resolved})
        t["urls"] = final
    return used


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

    # Author handle can live in several places; fall back to 'unknown' so the
    # field is never empty and tweet_url is still buildable.
    author_username = _first(author, "userName", "username", "screen_name",
                             "handle", default="")
    if not author_username:
        user_obj = _first(raw, "user", "author", default={}) or {}
        author_username = (
            _first(user_obj, "screen_name", "userName", "username", "handle",
                   default="")
            or _first(raw, "username", "screen_name", "userName", default="")
            or "unknown"
        )

    tweet_id = str(_first(raw, "id", "id_str", "tweet_id", default=""))
    tweet_url = (f"https://x.com/{author_username}/status/{tweet_id}"
                 if author_username and tweet_id else None)

    quoted = _first(raw, "quoted_tweet", "quotedTweet", "quoted_status")
    if isinstance(quoted, dict):
        is_quote = True
        quoted_text = _first(quoted, "text", "full_text", "fullText")
    else:
        is_quote = bool(_first(raw, "is_quote", "isQuote", default=False))
        quoted_text = None

    return {
        "id": tweet_id,
        "tweet_url": tweet_url,
        "text": text,
        "author_username": author_username,
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
        "urls": [],  # finalized in resolve_and_finalize_urls()
        "images": extract_images(raw),
        "source": source,
        "search_query": search_query,
        "_url_candidates": collect_url_candidates(raw, text),
        "_in_reply_to_id": _first(raw, "inReplyToId", "in_reply_to_status_id_str",
                                  "in_reply_to_id"),
        "_in_reply_to_username": _first(raw, "inReplyToUsername",
                                        "in_reply_to_screen_name"),
        "_conversation_id": _first(raw, "conversationId", "conversation_id"),
        "_created_dt": created_dt,
    }


def strip_internal(tweet):
    return {k: v for k, v in tweet.items() if not k.startswith("_")}


ENGAGEMENT_FIELDS = ("likes", "retweets", "replies", "author_followers")


def strip_engagement(tweet):
    """Copy of a tweet with engagement metrics removed (recursively for the
    tweets nested inside a thread) so the routine sees no popularity signal."""
    out = {k: v for k, v in tweet.items() if k not in ENGAGEMENT_FIELDS}
    if out.get("thread_tweets"):
        out["thread_tweets"] = [strip_engagement(x) for x in out["thread_tweets"]]
    return out


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
    urls, seen_urls, images = [], set(), []
    for m in members:
        for u in (m.get("urls") or []):
            key = u.get("resolved") or u.get("tco") if isinstance(u, dict) else u
            if key and key not in seen_urls:
                seen_urls.add(key)
                urls.append(u)
        images.extend(m.get("images") or [])
    head["is_thread"] = True
    head["thread_tweets"] = [strip_internal(m) for m in members]
    head["full_text"] = combined
    head["urls"] = urls
    head["images"] = list(dict.fromkeys(images))
    return head


# --- Main -------------------------------------------------------------------

def main():
    api_key = os.environ.get("GETXAPI_KEY")
    if not api_key:
        log("ERROR: GETXAPI_KEY environment variable not set")
        sys.exit(1)

    classification = load_classification()
    if classification:
        accounts = [a for a, c in classification.items() if c != "delete"]
        log(f"Classification: {len(classification)} accounts, "
            f"{len(accounts)} active (non-delete) to collect")
    else:
        accounts = load_watchlist()
        log(f"No classification — falling back to watchlist ({len(accounts)})")

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

    # --- Resolve t.co links and finalize urls (research_search prioritized) ---
    resolved_count = resolve_and_finalize_urls(deduped)
    log(f"Resolved {resolved_count} t.co links (cap {MAX_URL_RESOLUTIONS}/run)")

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

    # Second file for the Cloud Routine: same data, engagement metrics removed
    # so the model curates on substance, not popularity.
    routine_output = dict(output)
    routine_output["tweets"] = [strip_engagement(t) for t in items]
    routine_path = out_dir / "tweets_for_routine.json"
    routine_path.write_text(json.dumps(routine_output, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    # Split output by author category (additional files; tweets.json stays full).
    meta = {k: v for k, v in output.items() if k != "tweets"}
    split = split_by_category(items, classification)

    def write_split(category, tweets, strip):
        payload = dict(meta)
        payload["category"] = category
        payload["tweets"] = [strip_engagement(t) for t in tweets] if strip else tweets
        payload["total_tweets"] = len(payload["tweets"])
        prefix = "tweets_for_routine_" if strip else "tweets_"
        (out_dir / f"{prefix}{category}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for category in SPLIT_CATEGORIES:
        write_split(category, split[category], strip=False)
    for category in ROUTINE_CATEGORIES:
        write_split(category, split[category], strip=True)

    # Stats: category by author, but research_search tweets counted as 'research'.
    cat_counts = Counter()
    classification_lc = {k.lower(): v for k, v in classification.items()}
    for t in items:
        if t.get("source") == "research_search":
            cat_counts["research"] += 1
        else:
            cat_counts[classification_lc.get(
                (t.get("author_username") or "").lower(), "unclassified")] += 1
    images_count = sum(1 for t in items if t.get("images"))
    by_category = ", ".join(
        f"{c}={cat_counts.get(c, 0)}"
        for c in ("alpha", "data", "shitpost", "research", "unclassified"))

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

    split_files = ([f"tweets_{c}.json" for c in SPLIT_CATEGORIES]
                   + [f"tweets_for_routine_{c}.json" for c in ROUTINE_CATEGORIES])

    log("=== Twitter Collection Complete ===")
    log(f"Total: {len(deduped)} tweets")
    log(f"By category: {by_category}")
    log(f"Images: {images_count} tweets with images")
    log(f"Threads: {thread_count}  |  t.co resolved: {resolved_count}")
    log(f"API calls: {api_calls}  |  est. cost: ${output['estimated_cost_usd']}")
    log(f"Output dir: {out_dir.relative_to(REPO_ROOT)}")
    log(f"  tweets.json, tweets_for_routine.json + {', '.join(split_files)}")
    log("=" * 50)


if __name__ == "__main__":
    main()
