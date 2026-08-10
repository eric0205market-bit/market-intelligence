#!/usr/bin/env python3
"""Freshness gate for Twitter routines. Exit 0 if all given data files EXIST,
are fresh (collected_at within --max-age-hours of now UTC), AND are non-empty;
exit 1 otherwise. Run BEFORE generating any report; on non-zero exit the
routine must STOP and publish nothing.

Freshness alone is not enough — a collector can fail cleanly (zero items)
while still stamping a fresh collected_at (e.g. a broken query that returns
0 results is indistinguishable from "ran a moment ago" by age alone). The
2026-08-10 bank-research query broke exactly this way: collected_at
2026-08-10T06:50:46Z, total_tweets 0 — fresh AND empty, and the age-only
gate passed it."""
import argparse, json, os, sys
from datetime import datetime, timezone

def parse_dt(s):
    if not s: return None
    s = s.strip().replace("Z", "+00:00")
    try: dt = datetime.fromisoformat(s)
    except ValueError: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def is_empty(d):
    """True if the payload carries zero items — fresh-but-empty must still
    fail the gate. Covers a bare list ([]), or a dict whose total_tweets is
    0, or whose tweets list is empty (either condition alone is enough)."""
    if isinstance(d, list):
        return len(d) == 0
    if isinstance(d, dict):
        if d.get("total_tweets") == 0:
            return True
        tweets = d.get("tweets")
        if isinstance(tweets, list) and len(tweets) == 0:
            return True
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-age-hours", type=float, default=6.0)
    a = ap.parse_args()
    now = datetime.now(timezone.utc); max_age = a.max_age_hours * 3600; ok = True
    for p in a.files:
        # Explicit existence guard, checked before attempting to read: a
        # missing input must fail loudly and unambiguously as a missing file,
        # never be swallowed into a generic parse error and never treated as
        # a pass. (This is the same "missing == FAIL, not skip" principle the
        # routines now apply to the gate command itself failing to run.)
        if not os.path.exists(p):
            print(f"FRESHNESS GATE FAILED — missing input {p}"); ok = False; continue
        try:
            with open(p) as f: d = json.load(f)
        except Exception as e:
            print(f"FAIL  {p}: cannot read ({e})"); ok = False; continue

        # Age check — a bare-list payload carries no collected_at, so there's
        # nothing to age-check; the emptiness check below still applies to it.
        age_h = None
        if isinstance(d, dict):
            raw = d.get("collected_at") or (d.get("meta") or {}).get("collected_at")
            ca = parse_dt(raw)
            if ca is None:
                print(f"FAIL  {p}: no valid collected_at"); ok = False; continue
            age_h = (now - ca).total_seconds() / 3600
            if age_h > a.max_age_hours:
                print(f"FAIL  {p}: STALE collected_at {ca.isoformat()} = {age_h:.1f}h old (max {a.max_age_hours}h)"); ok = False; continue

        # Emptiness check — fresh (or age-inapplicable) is not enough; a
        # collector can fail cleanly and still stamp a fresh collected_at.
        if is_empty(d):
            print(f"FRESHNESS GATE FAILED — {p} is fresh but EMPTY (0 items)"); ok = False; continue

        if age_h is not None:
            print(f"OK    {p}: collected_at {ca.isoformat()} ({age_h:.1f}h old), non-empty")
        else:
            print(f"OK    {p}: non-empty (no collected_at to age-check)")
    if not ok:
        print("FRESHNESS GATE FAILED — routine must STOP and publish nothing."); sys.exit(1)
    print("FRESHNESS GATE PASSED."); sys.exit(0)

if __name__ == "__main__":
    main()
