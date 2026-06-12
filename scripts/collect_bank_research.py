#!/usr/bin/env python3
"""Bank-research relayer collection stream — a separate, low-risk module.

Reuses the proven GetXAPI plumbing in scripts/collect_twitter.py (api_search,
build_query, normalize_tweet, extract_tweet_list, strip_internal, API constants,
GETXAPI_KEY handling). collect_twitter.py's logic is NOT modified — only imported.

Collects recent IMAGE tweets from a curated set of bank-research relayer accounts
(search by AUTHOR, never by bank keyword; no engagement filter), tags each tweet
with the bank(s) named in its text, and writes a compact stream.

Run:  GETXAPI_KEY=xxxxx python3 scripts/collect_bank_research.py [--days 5] [--max-pages 3]
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_twitter as ct  # noqa: E402 — reuse the existing API client/plumbing

BANK_RESEARCH_ACCOUNTS = ["neilksethi", "neilksethinew", "MikeZaccardi", "LanceRoberts",
                          "TheChartReport", "HFI_Research", "eliant_capital",
                          "dailychartbook"]

# Canonical bank -> tokens for deterministic tagging (case-insensitive, word-ish).
# Prefixes like "BoA:"/"Goldman:" are caught (word-boundary start) along with
# in-body mentions. A tweet may match several banks; none -> [].
BANK_TAGS = [
    ("BofA", ["BofA", "BoA", "Bank of America",
              "Hartnett", "Subramanian", "Bull & Bear", "FMS", "Fund Manager Survey"]),
    ("Goldman", ["Goldman", "GS:", "GS ",
                 "Kostin", "Pasquariello", "Risk Appetite", "Sentiment Indicator",
                 "John Flood"]),
    ("Apollo/Slok", ["Apollo", "Slok"]),
    ("JPM", ["JPM", "JPMAM", "JP Morgan", "Feroli", "Kolanovic"]),
    ("Morgan Stanley", ["Morgan Stanley", "MS:", "Mike Wilson"]),
    ("Deutsche", ["Deutsche", "DB:"]),
    ("Yardeni", ["Yardeni"]),
    ("Morningstar", ["Morningstar"]),
    ("Citi", ["Citi"]),
    ("UBS", ["UBS"]),
    ("Barclays", ["Barclays"]),
    ("BNP", ["BNP"]),
    ("SocGen", ["SocGen"]),
    ("HSBC", ["HSBC"]),
    ("Nomura", ["Nomura", "McElligott", "McElligot"]),
    ("Citadel", ["Citadel", "Rubner"]),
    ("RBC", ["RBC"]),
    ("Macquarie", ["Macquarie"]),
    ("Bernstein", ["Bernstein"]),
    ("Evercore", ["Evercore"]),
    ("Mizuho", ["Mizuho"]),
    ("Standard Chartered", ["Standard Chartered"]),
    ("CLSA", ["CLSA"]),
    ("Strategas", ["Strategas"]),
    ("Ned Davis", ["Ned Davis"]),
    ("DataTrek", ["DataTrek"]),
    ("Wells Fargo", ["Wells Fargo"]),
    ("Jefferies", ["Jefferies"]),
    ("PIMCO", ["PIMCO"]),
]
_TAG_PATTERNS = [(name, [re.compile(r"\b" + re.escape(t), re.IGNORECASE) for t in toks])
                 for name, toks in BANK_TAGS]


def tag_banks(text):
    """Return canonical bank names whose tokens appear in the text (ordered)."""
    text = text or ""
    return [name for name, pats in _TAG_PATTERNS if any(p.search(text) for p in pats)]


def main():
    ap = argparse.ArgumentParser(description="Bank-research relayer collection stream.")
    ap.add_argument("--days", type=int, default=5, help="lookback window, days")
    ap.add_argument("--max-pages", type=int, default=3, help="pages per query")
    args = ap.parse_args()

    api_key = os.environ.get("GETXAPI_KEY")
    if not api_key:
        print("ERROR: GETXAPI_KEY not set — cannot collect locally. Run via CI "
              "(workflow_dispatch with the GETXAPI_KEY secret).", file=sys.stderr)
        sys.exit(2)

    # Search by AUTHOR only, image tweets only. build_query() adds the time
    # window + -filter:retweets exactly as the main collector does.
    core = "(" + " OR ".join(f"from:{a}" for a in BANK_RESEARCH_ACCOUNTS) + ") filter:images"
    query = ct.build_query(core, args.days * 24)
    ct.log(f"Bank-research: {len(BANK_RESEARCH_ACCOUNTS)} accounts | {args.days}d | "
           f"max {args.max_pages} pages | filter:images | no engagement filter")
    ct.log(f"query: {query}")
    raws, api_calls = ct.api_search(api_key, query, args.max_pages)

    seen = {}  # dedupe by tweet id; keep only tweets with >=1 image
    for raw in raws:
        t = ct.strip_internal(ct.normalize_tweet(raw, "bank_research"))
        tid = t.get("id")
        if not tid or not t.get("images") or tid in seen:
            continue
        t["banks"] = tag_banks(t.get("text") or t.get("full_text") or "")
        seen[tid] = t
    tweets = list(seen.values())

    by_bank = {}
    for t in tweets:
        for b in t["banks"]:
            by_bank[b] = by_bank.get(b, 0) + 1
    by_bank = dict(sorted(by_bank.items(), key=lambda kv: (-kv[1], kv[0])))

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "collected_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback_days": args.days,
        "total_tweets": len(tweets),
        "accounts": BANK_RESEARCH_ACCOUNTS,
        "by_bank": by_bank,
        "tweets": tweets,
    }

    ct.LATEST_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = ct.LATEST_DIR / "tweets_bank_research.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    raw_dir = ct.OUTPUT_ROOT / now.strftime("%Y-%m-%d_%H%M")
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "bank_research.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- stdout summary ----
    by_author = {}
    for t in tweets:
        a = (t.get("author_username") or "unknown").lower()
        by_author[a] = by_author.get(a, 0) + 1

    print()
    print("=== BANK-RESEARCH COLLECTION ===")
    print(f"total image tweets : {len(tweets)}")
    print(f"API calls          : {api_calls}  (est cost USD "
          f"{round(api_calls * ct.COST_PER_CALL_USD, 4)})")
    print("\nper-author counts:")
    for a in BANK_RESEARCH_ACCOUNTS:
        print(f"  {a:<18} {by_author.get(a.lower(), 0)}")
    seed_lower = {a.lower() for a in BANK_RESEARCH_ACCOUNTS}
    for a, c in sorted(((a, c) for a, c in by_author.items() if a not in seed_lower),
                       key=lambda kv: -kv[1]):
        print(f"  {a:<18} {c}  (unexpected — not a seed)")
    print("\nby_bank:")
    if by_bank:
        for b, c in by_bank.items():
            print(f"  {b:<20} {c}")
    else:
        print("  (no banks tagged)")
    print("\n5 sample tagged tweets (author | banks | text[:80] | image?):")
    samples = [t for t in tweets if t["banks"]][:5] or tweets[:5]
    for t in samples:
        txt = (t.get("text") or t.get("full_text") or "").replace("\n", " ")[:80]
        print(f"  @{t.get('author_username')} | {','.join(t['banks']) or '-'} | "
              f"{txt} | img={'y' if t.get('images') else 'n'}")
    print(f"\nwrote: {latest_path.relative_to(ct.REPO_ROOT)}")
    print(f"       {(raw_dir / 'bank_research.json').relative_to(ct.REPO_ROOT)}")


if __name__ == "__main__":
    main()
