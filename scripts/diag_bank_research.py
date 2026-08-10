#!/usr/bin/env python3
"""Diagnostic ONLY — not part of any collection workflow, writes nothing to
data/ or raw/. Isolates why collect_bank_research.py returns zero tweets
while the watchlist collector (same key, same run) is healthy.

v2 REWRITE: the first version used ct.api_search(), which catches every HTTP
exception, logs a warning, and returns an EMPTY list — so a "0" in that
table meant "genuinely zero results" OR "the call failed" and there was no
way to tell them apart. Proof it actually happened: that run reported
TheChartReport as 0 hits WITHOUT filter:images and 14 WITH it. Image tweets
are a strict subset of all tweets, so a real API can never return MORE
results after narrowing the query — the "0" had to be a swallowed failure,
not a true empty result. Every other zero in that table was therefore
equally untrustworthy.

This version never calls ct.api_search(). It issues each request directly
(reusing ct.API_URL/AUTH_HEADER/AUTH_PREFIX/QUERY_PARAM/PRODUCT_PARAM/
PRODUCT_VALUE/build_query/extract_tweet_list/extract_pagination) and
records, per call: the HTTP status code, whether an exception fired (and
its text), and the parsed hit count — with an explicit outcome column
(OK / HTTP_<code> / EXC) so a failed call can never render as a bare
number. A capped page (has_more=True) prints as ">=N (page cap)", not N,
so a capped result is never mistaken for an exact count either.

Also tests the OR-query shapes collect_bank_research.py actually builds
(never tested directly before this), with 3s spacing between calls and a
429 -> 30s sleep -> one retry, both attempts recorded.

Run:  GETXAPI_KEY=xxxxx python3 scripts/diag_bank_research.py [--days 5]
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_twitter as ct  # noqa: E402 — reuse constants/helpers, NOT api_search
from collect_bank_research import BANK_RESEARCH_ACCOUNTS  # noqa: E402

SLEEP_BETWEEN_CALLS_S = 3.0
SLEEP_ON_429_S = 30.0
CALL_BUDGET = 30   # informational cap this diagnostic targets (~30); we do
                    # not hard-abort mid-run on it (an incomplete diagnostic
                    # defeats the purpose) but we print the running total
                    # after every call and warn loudly if it's exceeded.

_total_calls = [0]  # mutable cell so do_search() can bump a shared counter


def do_search(api_key, query):
    """Issue ONE logical search (with one 429 -> 30s -> retry-once escalation)
    and return the list of per-HTTP-attempt dicts:
      {"attempt": 1|2, "http_status": int|None, "outcome": "OK"|"HTTP_<code>"|"EXC",
       "exc_text": str|None, "hit_count": int|None, "capped": bool|None}
    outcome/hit_count/capped are None-safe: hit_count is ONLY ever an int
    when outcome == "OK" — a failed attempt never gets a number."""
    headers = {ct.AUTH_HEADER: f"{ct.AUTH_PREFIX}{api_key}"}
    params = {ct.QUERY_PARAM: query, ct.PRODUCT_PARAM: ct.PRODUCT_VALUE}
    attempts = []
    for attempt in (1, 2):
        result = {"attempt": attempt, "http_status": None, "outcome": None,
                  "exc_text": None, "hit_count": None, "capped": None}
        _total_calls[0] += 1
        try:
            resp = requests.get(ct.API_URL, headers=headers, params=params,
                                timeout=ct.REQUEST_TIMEOUT)
            result["http_status"] = resp.status_code
            if resp.status_code == 429:
                result["outcome"] = "HTTP_429"
                attempts.append(result)
                if attempt == 1:
                    print(f"    -> HTTP 429, sleeping {SLEEP_ON_429_S:.0f}s then retrying once")
                    time.sleep(SLEEP_ON_429_S)
                    continue
                break  # second 429 in a row — give up, don't retry again
            if resp.status_code != 200:
                result["outcome"] = f"HTTP_{resp.status_code}"
                attempts.append(result)
                break
            try:
                payload = resp.json()
            except ValueError as exc:
                result["outcome"] = "EXC"
                result["exc_text"] = f"JSON decode failed: {exc}"
                attempts.append(result)
                break
            tweets = ct.extract_tweet_list(payload)
            _cursor, has_more = ct.extract_pagination(payload)
            result["outcome"] = "OK"
            result["hit_count"] = len(tweets)
            result["capped"] = bool(has_more) and len(tweets) > 0
            attempts.append(result)
            break
        except Exception as exc:  # noqa: BLE001 — this is the boundary we're
                                   # instrumenting, not hiding: record it, don't swallow it
            result["outcome"] = "EXC"
            result["exc_text"] = f"{type(exc).__name__}: {exc}"
            attempts.append(result)
            break
    time.sleep(SLEEP_BETWEEN_CALLS_S)
    print(f"    running total API calls: {_total_calls[0]}"
          + (f"  *** OVER BUDGET ({CALL_BUDGET}) ***" if _total_calls[0] > CALL_BUDGET else ""))
    return attempts


def fmt_hits(attempt):
    """Never a bare number for a failed call — only OK gets a count."""
    if attempt["outcome"] != "OK":
        return "-"
    if attempt["capped"]:
        return f">={attempt['hit_count']} (page cap)"
    return str(attempt["hit_count"])


def fmt_outcome(attempt):
    if attempt["outcome"] == "EXC":
        return f"EXC: {attempt['exc_text']}"
    return attempt["outcome"]


def print_row(label, query, attempts):
    for a in attempts:
        tag = f"  [retry {a['attempt']}]" if a["attempt"] > 1 else ""
        print(f"{label:<40} outcome={fmt_outcome(a):<28} hits={fmt_hits(a):<18}"
              f"qlen={len(query):>4}{tag}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=5, help="lookback window, days")
    args = ap.parse_args()

    api_key = os.environ.get("GETXAPI_KEY")
    if not api_key:
        print("ERROR: GETXAPI_KEY not set.", file=sys.stderr)
        sys.exit(2)

    lookback_hours = args.days * 24

    print()
    print(f"=== BANK-RESEARCH QUERY DIAGNOSTIC v2 ({args.days}d window) ===")
    print("outcome is OK / HTTP_<code> / EXC — a failed call NEVER renders as a number")
    print(f"spacing: {SLEEP_BETWEEN_CALLS_S:.0f}s between calls; on HTTP 429: "
          f"sleep {SLEEP_ON_429_S:.0f}s and retry once (both attempts recorded)")
    print()

    print("--- per-account: from:<account>  (no filter:images) vs  from:<account> filter:images ---")
    for account in BANK_RESEARCH_ACCOUNTS:
        query_plain = ct.build_query(f"from:{account}", lookback_hours)
        attempts_plain = do_search(api_key, query_plain)
        print_row(f"{account} (plain)", query_plain, attempts_plain)

        query_img = ct.build_query(f"from:{account} filter:images", lookback_hours)
        attempts_img = do_search(api_key, query_img)
        print_row(f"{account} (filter:images)", query_img, attempts_img)
    print()

    print("--- OR-query shapes actually built by collect_bank_research.py (never tested directly before) ---")

    # (a) full 8-account OR, WITH filter:images — exactly what collect_bank_research.py builds.
    core_full_img = "(" + " OR ".join(f"from:{a}" for a in BANK_RESEARCH_ACCOUNTS) + ") filter:images"
    query_full_img = ct.build_query(core_full_img, lookback_hours)
    print(f"\n(a) full 8-account OR + filter:images:\n    {query_full_img}")
    print_row("(a) full OR + filter:images", query_full_img, do_search(api_key, query_full_img))

    # (b) same OR group WITHOUT filter:images.
    core_full_plain = "(" + " OR ".join(f"from:{a}" for a in BANK_RESEARCH_ACCOUNTS) + ")"
    query_full_plain = ct.build_query(core_full_plain, lookback_hours)
    print(f"\n(b) full 8-account OR, no filter:images:\n    {query_full_plain}")
    print_row("(b) full OR, no filter:images", query_full_plain, do_search(api_key, query_full_plain))

    # (c) 2-account OR (MikeZaccardi OR dailychartbook), with and without filter:images —
    # both individually confirmed non-empty in the per-account loop above (baseline sanity check).
    two_accounts = ["MikeZaccardi", "dailychartbook"]
    core_2_img = "(" + " OR ".join(f"from:{a}" for a in two_accounts) + ") filter:images"
    query_2_img = ct.build_query(core_2_img, lookback_hours)
    print(f"\n(c1) 2-account OR + filter:images:\n    {query_2_img}")
    print_row("(c1) 2-account OR + filter:images", query_2_img, do_search(api_key, query_2_img))

    core_2_plain = "(" + " OR ".join(f"from:{a}" for a in two_accounts) + ")"
    query_2_plain = ct.build_query(core_2_plain, lookback_hours)
    print(f"\n(c2) 2-account OR, no filter:images:\n    {query_2_plain}")
    print_row("(c2) 2-account OR, no filter:images", query_2_plain, do_search(api_key, query_2_plain))

    # (d) re-run bare from:TheChartReport twice more — was its earlier 0 flaky?
    for i in (1, 2):
        query_tcr = ct.build_query("from:TheChartReport", lookback_hours)
        print(f"\n(d{i}) re-run bare from:TheChartReport:\n    {query_tcr}")
        print_row(f"(d{i}) TheChartReport re-run", query_tcr, do_search(api_key, query_tcr))

    print()
    print("=" * 60)
    print(f"TOTAL API calls made: {_total_calls[0]} (target budget: ~{CALL_BUDGET})")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
