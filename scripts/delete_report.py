#!/usr/bin/env python3
"""Delete all repo files related to one or more report patterns.

Searches reports/, raw/, and data/ for files matching the given pattern(s),
shows them, asks for confirmation, then git-rm's them, regenerates index.html,
commits, and pushes.

Usage:
    python3 scripts/delete_report.py twitter_2026-05-20
    python3 scripts/delete_report.py twitter_2026-05-20 twitter_2026-05-21
    python3 scripts/delete_report.py --dry-run research_2026-05-19

Matching is a substring test against each file's repo-relative path, with path
separators and underscores treated interchangeably. So `twitter_2026-05-20`
matches both reports/twitter_2026-05-20_2027.html and the
raw/twitter/2026-05-20_2027/ collection files (which use a '/'), and a bare
date like `2026-05-20` matches everything for that day in all three trees.
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = ("reports", "raw", "data")
UPDATE_DASHBOARD = REPO_ROOT / "scripts" / "update_dashboard.py"


def git(*args, check=True, capture=False):
    return subprocess.run(["git", *args], cwd=str(REPO_ROOT), check=check,
                          text=True, capture_output=capture)


def matches_pattern(rel_path, patterns):
    candidates = (rel_path, rel_path.replace("/", "_"))
    return any(p in c for p in patterns for c in candidates)


def find_matches(patterns):
    found = []
    for name in SEARCH_DIRS:
        root = REPO_ROOT / name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if matches_pattern(rel, patterns):
                found.append(rel)
    return found


def tracked_set():
    return set(git("ls-files", capture=True).stdout.splitlines())


def prune_empty_dirs():
    """Remove now-empty directories left under the search roots (not the roots)."""
    for name in SEARCH_DIRS:
        root = REPO_ROOT / name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir():
                try:
                    next(path.iterdir())
                except StopIteration:
                    path.rmdir()
                except OSError:
                    pass


def main():
    parser = argparse.ArgumentParser(
        description="Delete repo files matching report pattern(s).")
    parser.add_argument("patterns", nargs="+", help="substring pattern(s) to match")
    parser.add_argument("--dry-run", action="store_true",
                        help="only show what would be deleted; change nothing")
    args = parser.parse_args()

    patterns = [p for p in args.patterns if p.strip()]
    if not patterns:
        print("Error: no non-empty pattern given.", file=sys.stderr)
        sys.exit(1)

    matches = find_matches(patterns)
    label = ", ".join(patterns)
    if not matches:
        print(f"No files match: {label}")
        return

    print(f"Matched {len(matches)} file(s) for: {label}")
    for rel in matches:
        print(f"  {rel}")

    if args.dry_run:
        print("\n[dry-run] Nothing changed.")
        return

    try:
        answer = input(f"\nDelete these {len(matches)} file(s)? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer != "y":
        print("Aborted. Nothing changed.")
        return

    tracked = tracked_set()
    tracked_matches = [r for r in matches if r in tracked]
    untracked_matches = [r for r in matches if r not in tracked]

    if tracked_matches:
        git("rm", "--quiet", "--", *tracked_matches)
    for rel in untracked_matches:
        try:
            (REPO_ROOT / rel).unlink()
        except OSError as exc:
            print(f"  ! could not remove untracked {rel}: {exc}")

    prune_empty_dirs()

    # Regenerate the dashboard so it no longer lists the removed reports.
    if UPDATE_DASHBOARD.exists():
        subprocess.run([sys.executable, str(UPDATE_DASHBOARD)],
                       cwd=str(REPO_ROOT), check=False)
        git("add", "index.html", check=False)

    git("commit", "-m", f"cleanup: remove {label}", check=False)
    push = git("push", check=False)
    if push.returncode != 0:
        print("Committed locally, but push failed — push manually when ready.")
    else:
        print("Done.")


if __name__ == "__main__":
    main()
