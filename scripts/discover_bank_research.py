#!/usr/bin/env python3
"""One-off discovery of Twitter "bank-research relayer" accounts.

Reuses the GetXAPI plumbing in scripts/collect_twitter.py (api_search,
build_query, normalize_tweet, extract_tweet_list, API constants, GETXAPI_KEY) —
the API client is NOT reimplemented here. Runs three discovery nets, all filtered
to image tweets, and ranks AUTHORS by how often they post research-style image
tweets so a human can hand-pick relayers to curate.

Discovery ONLY: writes to raw/bank_research_discovery/<date>/, never touches the
watchlist, routines, or collect_twitter.py. Output is not committed by default.

Design facts (respect these): the signal is the AUTHOR, not bank keywords;
filter:images is the core quality filter; engagement is intentionally NOT used as
a filter (good research often has <5 likes); bank names are used only for TAGGING.

Run:  GETXAPI_KEY=xxxxx python3 scripts/discover_bank_research.py [--days 14] [--max-pages 2]
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_twitter as ct  # noqa: E402 — reuse the existing API client/plumbing

# NET 1 — seed relayers (their own image tweets + their reposters' image tweets)
SEEDS = ["neilksethi", "MikeZaccardi", "eliant_capital", "LanceRoberts",
         "TheChartReport", "HFI_Research"]

# NET 2 — distinctive research-report vocabulary ("Exhibit" kept but noisy)
VOCAB = ['"Global Fund Manager Survey"', '"Bull & Bear"', '"Risk Appetite"',
         '"Equity Sentiment Indicator"', "GFMS", "Exhibit"]
NOISY_VOCAB = {"Exhibit"}  # flagged: broad, may pull non-research image tweets

# NET 3 — strategist names that relayers cite in text
STRATEGISTS = ["Hartnett", "Subramanian", "Feroli", "Pasquariello", "Kostin",
               '"Mike Wilson"', "Slok", "Kolanovic", "Rubner"]

# Bank prefix tokens — for TAGGING only (case-insensitive, word-ish match).
BANK_PREFIX_TOKENS = [
    "BoA", "BofA", "Bank of America", "Goldman", "GS:", "GS ", "DB:", "DB ",
    "Deutsche", "JPM", "JPMAM", "Morgan Stanley", "MS:", "UBS", "Barclays",
    "Citi", "Yardeni", "Morningstar", "Apollo", "Pimco", "PIMCO", "Wells Fargo",
    "Jefferies", "Nomura", "HSBC", "SocGen", "BNP", "RBC", "Macquarie",
    "Bernstein", "Evercore", "Mizuho", "Standard Chartered", "CLSA", "Strategas",
    "Ned Davis", "DataTrek",
]
_BANK_PATTERNS = [re.compile(r"\b" + re.escape(t), re.IGNORECASE)
                  for t in BANK_PREFIX_TOKENS]


def has_bank_prefix(text):
    """True if the tweet text starts with or contains a known bank token."""
    return any(p.search(text or "") for p in _BANK_PATTERNS)


# Bank/AM coverage groups (canonical name -> tokens) for the coverage diagnostic:
# how often each bank actually gets relayed across all collected image tweets.
# "Slok" rolls up into Apollo (Torsten Slok / Apollo).
BANK_GROUPS = [
    ("BofA",               ["BoA", "BofA", "Bank of America"]),
    ("Goldman/GS",         ["Goldman", "GS:", "GS "]),
    ("Deutsche/DB",        ["Deutsche", "DB:", "DB "]),
    ("JPM/JPMAM",          ["JPM", "JPMAM"]),
    ("Morgan Stanley/MS",  ["Morgan Stanley", "MS:"]),
    ("UBS",                ["UBS"]),
    ("Barclays",           ["Barclays"]),
    ("Citi",               ["Citi"]),
    ("Yardeni",            ["Yardeni"]),
    ("Morningstar",        ["Morningstar"]),
    ("Apollo/Slok",        ["Apollo", "Slok"]),
    ("PIMCO",              ["PIMCO", "Pimco"]),
    ("Wells Fargo",        ["Wells Fargo"]),
    ("Jefferies",          ["Jefferies"]),
    ("Nomura",             ["Nomura"]),
    ("HSBC",               ["HSBC"]),
    ("SocGen",             ["SocGen"]),
    ("BNP",                ["BNP"]),
    ("RBC",                ["RBC"]),
    ("Macquarie",          ["Macquarie"]),
    ("Bernstein",          ["Bernstein"]),
    ("Evercore",           ["Evercore"]),
    ("Mizuho",             ["Mizuho"]),
    ("Standard Chartered", ["Standard Chartered"]),
    ("CLSA",               ["CLSA"]),
    ("Strategas",          ["Strategas"]),
    ("Ned Davis",          ["Ned Davis"]),
    ("DataTrek",           ["DataTrek"]),
]
_BANK_GROUP_PATTERNS = [
    (name, [re.compile(r"\b" + re.escape(tok), re.IGNORECASE) for tok in toks])
    for name, toks in BANK_GROUPS
]


def banks_in(text):
    """Canonical bank names whose tokens appear in the text (for coverage)."""
    text = text or ""
    return [name for name, pats in _BANK_GROUP_PATTERNS if any(p.search(text) for p in pats)]


def load_known_handles():
    """Handles the collector already tracks (classification.json keys — what the
    collector uses for its active set — plus watchlist.txt as fallback).
    Lowercased for comparison."""
    handles = set()
    cls = getattr(ct, "CLASSIFICATION_PATH", None)
    if cls and cls.exists():
        try:
            data = json.loads(cls.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                handles.update(k.lower() for k in data)
        except Exception:
            pass
    wl = getattr(ct, "WATCHLIST_PATH", None)
    if wl and wl.exists():
        for line in wl.read_text(encoding="utf-8").splitlines():
            h = line.strip().lstrip("@").strip()
            if h and not h.startswith("#"):
                handles.add(h.lower())
    return handles


def build_net_queries():
    """Return [(net_label, core_query)]; filter:images is on every query."""
    queries = []
    for s in SEEDS:
        queries.append(("net1-seed", f"from:{s} filter:images"))
        queries.append(("net1-network", f"filter:images (@{s})"))
    for term in VOCAB:
        queries.append(("net2-vocab", f"{term} filter:images"))
    for name in STRATEGISTS:
        queries.append(("net3-strategist", f"{name} filter:images"))
    return queries


def main():
    ap = argparse.ArgumentParser(
        description="Discover bank-research relayer accounts (discovery only).")
    ap.add_argument("--days", type=int, default=14, help="lookback window, days")
    ap.add_argument("--max-pages", type=int, default=2, help="pages per query")
    args = ap.parse_args()

    # Read the key exactly as collect_twitter.py does. Stop loudly if absent.
    api_key = os.environ.get("GETXAPI_KEY")
    if not api_key:
        print("ERROR: GETXAPI_KEY not set in environment — cannot run discovery "
              "locally. Run via CI (workflow_dispatch with the GETXAPI_KEY "
              "secret) instead.", file=sys.stderr)
        sys.exit(2)

    lookback_hours = args.days * 24
    queries = build_net_queries()
    ct.log(f"Discovery: {len(queries)} queries | {args.days}d lookback | "
           f"max {args.max_pages} pages/query | filter:images on all")

    seen = {}  # tweet id -> {"tweet": normalized, "nets": set(net labels)}
    api_calls = 0
    for net, core in queries:
        query = ct.build_query(core, lookback_hours)  # adds time window; Latest
        ct.log(f"[{net}] {core}")
        raws, calls = ct.api_search(api_key, query, args.max_pages)
        api_calls += calls
        for raw in raws:
            tweet = ct.normalize_tweet(raw, net)
            tid = tweet.get("id")
            if not tid:
                continue
            if not tweet.get("images"):  # must have >=1 image (defensive)
                continue
            if tid in seen:
                seen[tid]["nets"].add(net)
            else:
                seen[tid] = {"tweet": tweet, "nets": {net}}

    known = load_known_handles()
    authors = {}
    for entry in seen.values():
        t = entry["tweet"]
        author = t.get("author_username") or "unknown"
        rec = authors.setdefault(author, {
            "author": author, "tweet_count": 0, "nets": set(),
            "bank_prefix_hits": 0, "already_in_watchlist": author.lower() in known,
            "sample_urls": [],
        })
        rec["tweet_count"] += 1
        rec["nets"] |= entry["nets"]
        if len(rec["sample_urls"]) < 3 and t.get("tweet_url"):
            rec["sample_urls"].append(t["tweet_url"])
        if has_bank_prefix(t.get("text") or t.get("full_text") or ""):
            rec["bank_prefix_hits"] += 1

    ranked = sorted(
        authors.values(),
        key=lambda r: (-r["tweet_count"], -r["bank_prefix_hits"], r["author"].lower()))
    for r in ranked:
        r["nets"] = sorted(r["nets"])

    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    out_dir = ct.REPO_ROOT / "raw" / "bank_research_discovery" / day
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "authors_ranked.json").write_text(
        json.dumps(ranked, ensure_ascii=False, indent=2), encoding="utf-8")

    with (out_dir / "authors_ranked.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["author", "tweet_count", "bank_prefix_hits",
                         "already_in_watchlist", "nets"])
        for r in ranked:
            writer.writerow([r["author"], r["tweet_count"], r["bank_prefix_hits"],
                             r["already_in_watchlist"], "|".join(r["nets"])])

    total_tweets = len(seen)
    cost = round(api_calls * ct.COST_PER_CALL_USD, 4)

    # Bank coverage: across ALL collected image tweets, how many contain each
    # bank's token(s) — i.e. which banks actually get relayed on Twitter.
    bank_counts = {name: 0 for name, _ in BANK_GROUPS}
    for entry in seen.values():
        text = entry["tweet"].get("text") or entry["tweet"].get("full_text") or ""
        for name in set(banks_in(text)):
            bank_counts[name] += 1
    bank_ranked = sorted(bank_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    with (out_dir / "bank_coverage.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["bank", "tweet_count"])
        for name, c in bank_ranked:
            writer.writerow([name, c])

    seed_set = {s.lower() for s in SEEDS}

    print()
    print("=== TOP 40 BANK-RESEARCH RELAYER CANDIDATES ===")
    print(f"{'#':>3}  {'author':<24} {'tweets':>6} {'bank':>5} {'in_wl':>6}  nets")
    print("-" * 88)
    for i, r in enumerate(ranked[:40], 1):
        wl = "yes" if r["already_in_watchlist"] else "no"
        print(f"{i:>3}  {r['author'][:24]:<24} {r['tweet_count']:>6} "
              f"{r['bank_prefix_hits']:>5} {wl:>6}  {','.join(r['nets'])}")

    print()
    print("=== BANK COVERAGE (image tweets containing each bank token) ===")
    print(f"{'bank':<22} {'tweet_count':>11}")
    print("-" * 35)
    for name, c in bank_ranked:
        print(f"{name:<22} {c:>11}")

    print()
    print("=== TOP 20 NON-SEED AUTHORS — SAMPLE URLS (eyeball relayer vs noise) ===")
    nonseed = [r for r in ranked if r["author"].lower() not in seed_set][:20]
    for r in nonseed:
        wl = "yes" if r["already_in_watchlist"] else "no"
        print(f"\n@{r['author']} | tweets={r['tweet_count']} "
              f"bank_hits={r['bank_prefix_hits']} in_wl={wl} nets={','.join(r['nets'])}")
        for u in r["sample_urls"][:3]:
            print(f"    {u}")

    print()
    print("=== TOTALS ===")
    print(f"unique image tweets : {total_tweets}")
    print(f"unique authors      : {len(ranked)}")
    print(f"API calls           : {api_calls}")
    print(f"estimated cost USD  : {cost}")
    print(f"output dir          : {out_dir.relative_to(ct.REPO_ROOT)}")
    print("note: net2 'Exhibit' is broad/noisy — included but weight it lightly.")


if __name__ == "__main__":
    main()
