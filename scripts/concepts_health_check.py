#!/usr/bin/env python3
"""Concepts daily-stream health check (KNOWLEDGE track, Concepts only).

Read-only diagnostic. For every ACTIVE source in config/concepts_sources.json
(collect != false) reports:

  - last_card_date   most recent published_date of a processed/concepts card
                      attributed to that source (by source_name), else "never"
  - days_since_card   today - last_card_date (calendar days), else None
  - zero_streak       consecutive most-recent daily runs (from
                      raw/concepts/_runs/<date>/funnel.json) with kept==0 for
                      that source's slug, counting back from the newest run
                      until a run with kept>0 or no funnel data for that slug
  - status            STALE if zero_streak >= STALE_STREAK_DAYS (source has
                      gone quiet for that many consecutive runs) — this is the
                      slow-and-silent failure mode (broken index_url, bot-block
                      onset, etc.) that a raw "0 new today" count won't surface
                      on its own, because CANDIDATES SO IT LOOKS ALIVE while
                      always dropping to old/junk.

This catches exactly what the a16z_blog outage was: kept==0 for 12+ straight
days while the source stayed in the "attempted, not skipped" list looking
healthy in isolation. Nothing here modifies config, raw, or processed data.

Run:
    python3 scripts/concepts_health_check.py                 # human table
    python3 scripts/concepts_health_check.py --json           # machine-readable
    python3 scripts/concepts_health_check.py --stale-only     # only flagged rows

Wiring into the daily workflow (not done automatically by this script — see
.github/workflows/collect-concepts.yml): add a step after the existing
`collect` job step that runs this script and greps its stdout for "STALE";
fail (or just log/annotate) the step if any STALE line is present. Keeping it
a separate opt-in step (rather than folding into collect_concepts.py) means a
health regression never blocks or slows down the actual collection run.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "concepts_sources.json"
PROCESSED_ROOT = REPO_ROOT / "processed" / "concepts"
RUNS_ROOT = REPO_ROOT / "raw" / "concepts" / "_runs"

STALE_STREAK_DAYS = 5   # consecutive zero-kept runs before flagging STALE
STALE_CARD_DAYS = 10    # days since last card before flagging STALE (if ever)


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "source"


def load_active_sources():
    """Mirrors skip_reason_for() in collect_concepts.py: collect:false OR
    paywalled:true sources are never attempted by the daily collector, so they
    have no funnel/card history to assess and would only show up as spurious
    'never/0 runs' rows here."""
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = config.get("sources", [])
    out = []
    for s in sources:
        if s.get("collect") is False or s.get("paywalled"):
            continue
        slug = slugify(s.get("name", ""))
        out.append({"slug": slug, "name": s.get("name", ""),
                    "index_url": s.get("index_url", "")})
    return out


def last_card_dates():
    """slug -> most recent card date (YYYY-MM-DD str) among processed cards,
    matched by source_name -> slug (cards don't store slug directly). Prefers
    published_date; falls back to processed_at's date component when a card's
    published_date is empty (some extractions can't recover a source date) so
    such cards aren't silently invisible to this check."""
    by_name_latest = {}
    for f in PROCESSED_ROOT.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        name = d.get("source_name")
        if not name:
            continue
        pub = d.get("published_date") or (d.get("processed_at") or "")[:10]
        if not pub:
            continue
        if name not in by_name_latest or pub > by_name_latest[name]:
            by_name_latest[name] = pub
    return {slugify(name): date for name, date in by_name_latest.items()}


def daily_kept_by_slug():
    """slug -> [(date_str, kept_int), ...] sorted oldest -> newest, from every
    raw/concepts/_runs/<date>/funnel.json found on disk."""
    out = {}
    if not RUNS_ROOT.is_dir():
        return out
    for run_dir in sorted(RUNS_ROOT.iterdir()):
        if not run_dir.is_dir():
            continue
        fj = run_dir / "funnel.json"
        if not fj.exists():
            continue
        try:
            data = json.loads(fj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for slug, row in (data.get("sources") or {}).items():
            out.setdefault(slug, []).append((run_dir.name, row.get("kept", 0)))
    return out


def zero_streak(runs_for_slug):
    """Consecutive kept==0 runs counting back from the newest. None if the
    slug has no run history at all (can't assess)."""
    if not runs_for_slug:
        return None
    streak = 0
    for _date, kept in reversed(runs_for_slug):
        if kept == 0:
            streak += 1
        else:
            break
    return streak


def days_since(date_str, today):
    try:
        d = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
    return (today - d).days


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    ap.add_argument("--stale-only", action="store_true", help="only print flagged rows")
    args = ap.parse_args()

    today = datetime.datetime.now(datetime.timezone.utc).date()
    sources = load_active_sources()
    last_cards = last_card_dates()
    kept_history = daily_kept_by_slug()

    rows = []
    for s in sources:
        slug = s["slug"]
        last_card = last_cards.get(slug)
        dsc = days_since(last_card, today) if last_card else None
        streak = zero_streak(kept_history.get(slug, []))
        runs_seen = len(kept_history.get(slug, []))
        stale = (streak is not None and streak >= STALE_STREAK_DAYS) or \
                (dsc is not None and dsc >= STALE_CARD_DAYS) or \
                (last_card is None and runs_seen >= STALE_STREAK_DAYS)
        rows.append({
            "slug": slug,
            "name": s["name"],
            "last_card_date": last_card or "never",
            "days_since_card": dsc,
            "zero_streak": streak,
            "runs_seen": runs_seen,
            "status": "STALE" if stale else "ok",
        })

    rows.sort(key=lambda r: (r["status"] != "STALE", -(r["zero_streak"] or 0)))

    if args.stale_only:
        rows = [r for r in rows if r["status"] == "STALE"]

    if args.json:
        print(json.dumps({"generated_at": today.isoformat(), "sources": rows}, indent=2))
        return

    print(f"Concepts daily-stream health check — {today.isoformat()}")
    print(f"(STALE = zero_streak >= {STALE_STREAK_DAYS} runs, or days_since_card >= "
          f"{STALE_CARD_DAYS}, or never-carded with >= {STALE_STREAK_DAYS} runs seen)")
    print()
    hdr = f"{'status':6} {'source':32} {'last_card':11} {'days_since':10} {'zero_streak':11} {'runs_seen':9}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        dsc = "-" if r["days_since_card"] is None else str(r["days_since_card"])
        zs = "-" if r["zero_streak"] is None else str(r["zero_streak"])
        flag = "STALE" if r["status"] == "STALE" else ""
        print(f"{flag:6} {r['slug']:32} {r['last_card_date']:11} {dsc:10} {zs:11} {r['runs_seen']:9}")

    n_stale = sum(1 for r in rows if r["status"] == "STALE")
    print()
    print(f"{n_stale} STALE / {len(rows)} active sources.")
    if n_stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
