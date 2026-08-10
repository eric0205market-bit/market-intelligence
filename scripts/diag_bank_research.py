#!/usr/bin/env python3
"""Diagnostic ONLY — not part of any collection workflow, writes nothing to
data/ or raw/. Isolates why collect_bank_research.py returns zero tweets
while the watchlist collector (same key, same run) is healthy.

For each of the 8 BANK_RESEARCH_ACCOUNTS, issues two single-account searches
with the SAME time window collect_bank_research.py uses (--days 5 ->
build_query(..., days*24)):
  1. `from:<account>`                 (no filter:images)
  2. `from:<account> filter:images`   (with filter:images, matching the
                                        real collector's query shape)
and prints a table of hit counts. 8 accounts x 2 variants x 1 page each =
16 API calls total, exactly the budget this diagnostic is capped to.

Reading the table:
  - both columns 0        -> the account itself is dead/silent for this
                              window (nothing to do with filter:images)
  - col 1 has hits, col 2 is 0  -> filter:images is the culprit for that
                              account (no image tweets in-window, or the
                              operator itself misbehaves)
  - both columns have hits but collect_bank_research.py still returns 0
                              -> look at the OR-query construction instead
                              of any single account

Run:  GETXAPI_KEY=xxxxx python3 scripts/diag_bank_research.py [--days 5]
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_twitter as ct  # noqa: E402 — reuse api_search/build_query/log
from collect_bank_research import BANK_RESEARCH_ACCOUNTS  # noqa: E402

MAX_PAGES = 1  # one page per call — we only need a hit count, not full results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=5, help="lookback window, days")
    args = ap.parse_args()

    api_key = os.environ.get("GETXAPI_KEY")
    if not api_key:
        print("ERROR: GETXAPI_KEY not set.", file=sys.stderr)
        sys.exit(2)

    lookback_hours = args.days * 24
    total_calls = 0
    rows = []

    for account in BANK_RESEARCH_ACCOUNTS:
        query_plain = ct.build_query(f"from:{account}", lookback_hours)
        raws_plain, calls_plain = ct.api_search(api_key, query_plain, MAX_PAGES)
        total_calls += calls_plain

        query_img = ct.build_query(f"from:{account} filter:images", lookback_hours)
        raws_img, calls_img = ct.api_search(api_key, query_img, MAX_PAGES)
        total_calls += calls_img

        rows.append((account, len(raws_plain), len(raws_img)))

    print()
    print(f"=== BANK-RESEARCH QUERY DIAGNOSTIC ({args.days}d window) ===")
    print(f"{'account':<18}{'no filter:images':>18}{'with filter:images':>20}")
    print("-" * 56)
    for account, n_plain, n_img in rows:
        flag = ""
        if n_plain == 0 and n_img == 0:
            flag = "  <- account dead/silent this window"
        elif n_plain > 0 and n_img == 0:
            flag = "  <- filter:images kills it"
        print(f"{account:<18}{n_plain:>18}{n_img:>20}{flag}")
    print("-" * 56)
    print(f"total API calls made: {total_calls} (budget: 16)")
    print()


if __name__ == "__main__":
    main()
