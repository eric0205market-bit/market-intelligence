#!/usr/bin/env python3
"""Authoritative active/parked tally for config/concepts_sources.json.

The `_active_parked` header in the sources config used to be hand-maintained:
every session that flipped a `collect` flag was expected to also bump the
string by hand. It drifted — the header read "51 active / 27 parked" while the
flags actually said 50/28 (drift that entered 2026-06-27..07-09 when four
sources were parked to fix 404s/bot-blocks without the header being updated,
then partly un-parked again). A previous session rationalised the gap as a
"Deep/Data counted separately" convention and applied deltas within it; there
was no such convention — it was accumulated drift.

Fix: the header is now DERIVED from the flags, not hand-written.

  - The single source of truth is each source's `collect` flag:
    parked  <=>  collect is false ;  active  <=>  collect is not false
    (this mirrors collect_concepts.py, which skips `collect: false` sources).
  - `_active_parked` is regenerated from that count and carries an
    AUTO-GENERATED marker; human context lives in `_active_parked_note`, which
    holds NO numbers (so it cannot drift).

Usage:
    python3 scripts/concepts_source_tally.py            # print the tally
    python3 scripts/concepts_source_tally.py --json     # machine-readable
    python3 scripts/concepts_source_tally.py --write     # rewrite _active_parked
    python3 scripts/concepts_source_tally.py --check     # exit 1 if header drifted

`--check` is wired into scripts/concepts_health_check.py so a health run fails
loudly the moment a hand-edited header disagrees with the flags again.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "concepts_sources.json"

AUTOGEN_MARKER = (
    "[AUTO-GENERATED from collect flags by scripts/concepts_source_tally.py — "
    "do not hand-edit; run `python3 scripts/concepts_source_tally.py --write` to refresh]"
)


def is_parked(source):
    """Parked <=> `collect` is false. This is the definition `_active_parked`
    documents (and the one the reconciliation task specified: "mechanical count
    over collect flags -> 50 active / 28 parked").

    NOTE — do not "fix" this to also exclude paywalled sources. The daily
    collector additionally skips `paywalled: true` sources, so the set it
    *attempts* is smaller than the collect-active set (that attempted count is
    what concepts_health_check.load_active_sources() reports). These are two
    different, both-correct notions; `_active_parked` is the collect-flag one.
    """
    return source.get("collect") is False


def _breakdown(sources):
    counts = Counter((s.get("type") or "Untyped") for s in sources)
    order = ["Deep", "Data"] + sorted(k for k in counts if k not in ("Deep", "Data"))
    return " + ".join(f"{counts[k]} {k}" for k in order if counts.get(k))


def compute_tally(sources):
    active = [s for s in sources if not is_parked(s)]
    parked = [s for s in sources if is_parked(s)]
    return {
        "total": len(sources),
        "active": len(active),
        "parked": len(parked),
        "active_by_type": dict(Counter((s.get("type") or "Untyped") for s in active)),
        "parked_by_type": dict(Counter((s.get("type") or "Untyped") for s in parked)),
        "header": (
            f"{len(active)} active / {len(parked)} parked "
            f"(active: {_breakdown(active)}; parked: {_breakdown(parked)}) "
            f"{AUTOGEN_MARKER}"
        ),
    }


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _strip_marker(s):
    """Compare only the numeric body, ignoring the AUTO-GENERATED marker, so a
    stored header without the marker still counts as agreeing on the numbers."""
    return re.sub(r"\s*\[AUTO-GENERATED.*?\]\s*$", "", s or "").strip()


def check_header(cfg=None):
    """Return (agrees: bool, stored: str, computed: str) for the stored header."""
    if cfg is None:
        cfg = load_config()
    computed = compute_tally(cfg["sources"])["header"]
    stored = cfg.get("_active_parked", "")
    return _strip_marker(stored) == _strip_marker(computed), stored, computed


def write_header(new_header):
    """Minimal-diff rewrite of just the `_active_parked` value (no reformat)."""
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    cfg = json.loads(raw)
    old = cfg.get("_active_parked")
    if old is None:
        raise SystemExit("ERROR: config has no _active_parked key to rewrite.")
    # Write literal UTF-8 to match the rest of the file's style.
    new_enc = json.dumps(new_header, ensure_ascii=False)
    # The stored value may have been written either escaped (\\uXXXX) or literal;
    # try both encodings to locate it, then normalise to the literal form. This
    # keeps the rewrite idempotent and self-healing regardless of prior encoding.
    for old_enc in (json.dumps(old, ensure_ascii=False), json.dumps(old, ensure_ascii=True)):
        if raw.count(old_enc) == 1:
            if old_enc == new_enc:
                return False
            CONFIG_PATH.write_text(raw.replace(old_enc, new_enc), encoding="utf-8")
            return True
    raise SystemExit("ERROR: _active_parked value not uniquely locatable; aborting.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="rewrite _active_parked from the flags")
    g.add_argument("--check", action="store_true", help="exit 1 if the stored header drifted")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    cfg = load_config()
    tally = compute_tally(cfg["sources"])
    stored = cfg.get("_active_parked", "")
    agrees, _, _ = check_header(cfg)

    if args.check:
        if agrees:
            print(f"OK: _active_parked matches the flags — {tally['active']} active / "
                  f"{tally['parked']} parked.")
            return
        print("FAIL: _active_parked DISAGREES with the collect flags.", file=sys.stderr)
        print(f"  stored:   {stored}", file=sys.stderr)
        print(f"  computed: {tally['header']}", file=sys.stderr)
        print("  -> run: python3 scripts/concepts_source_tally.py --write", file=sys.stderr)
        sys.exit(1)

    if args.write:
        changed = write_header(tally["header"])
        print(("rewrote" if changed else "unchanged") + f": {tally['header']}")
        return

    if args.json:
        print(json.dumps(tally, indent=2))
        return

    print(tally["header"])
    print(f"  total={tally['total']}  active_by_type={tally['active_by_type']}  "
          f"parked_by_type={tally['parked_by_type']}")
    print(f"  header {'agrees with' if agrees else 'DISAGREES with'} stored _active_parked")


if __name__ == "__main__":
    main()
