#!/usr/bin/env python3
"""Freshness gate for Twitter routines. Exit 0 if all given data files are fresh
(collected_at within --max-age-hours of now UTC), exit 1 otherwise. Run BEFORE
generating any report; on non-zero exit the routine must STOP and publish nothing."""
import argparse, json, sys
from datetime import datetime, timezone

def parse_dt(s):
    if not s: return None
    s = s.strip().replace("Z", "+00:00")
    try: dt = datetime.fromisoformat(s)
    except ValueError: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-age-hours", type=float, default=6.0)
    a = ap.parse_args()
    now = datetime.now(timezone.utc); max_age = a.max_age_hours * 3600; ok = True
    for p in a.files:
        try:
            with open(p) as f: d = json.load(f)
        except Exception as e:
            print(f"FAIL  {p}: cannot read ({e})"); ok = False; continue
        raw = d.get("collected_at") or (d.get("meta") or {}).get("collected_at")
        ca = parse_dt(raw)
        if ca is None:
            print(f"FAIL  {p}: no valid collected_at"); ok = False; continue
        age_h = (now - ca).total_seconds() / 3600
        if age_h > a.max_age_hours:
            print(f"FAIL  {p}: STALE collected_at {ca.isoformat()} = {age_h:.1f}h old (max {a.max_age_hours}h)"); ok = False
        else:
            print(f"OK    {p}: collected_at {ca.isoformat()} ({age_h:.1f}h old)")
    if not ok:
        print("FRESHNESS GATE FAILED — routine must STOP and publish nothing."); sys.exit(1)
    print("FRESHNESS GATE PASSED."); sys.exit(0)

if __name__ == "__main__":
    main()
