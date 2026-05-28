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


def current_branch():
    return git("rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip()


def is_dirty():
    return bool(git("status", "--porcelain", capture=True).stdout.strip())


def delete_matches(matches):
    """git-rm tracked matches and unlink untracked ones (only those present on
    the current checkout). Returns the number of files removed."""
    tracked = tracked_set()
    removed = 0
    tracked_present = [r for r in matches
                       if r in tracked and (REPO_ROOT / r).exists()]
    if tracked_present:
        git("rm", "--quiet", "--", *tracked_present)
        removed += len(tracked_present)
    for rel in matches:
        if rel not in tracked and (REPO_ROOT / rel).exists():
            try:
                (REPO_ROOT / rel).unlink()
                removed += 1
            except OSError as exc:
                print(f"  ! could not remove untracked {rel}: {exc}")
    return removed


def regenerate_dashboard():
    if UPDATE_DASHBOARD.exists():
        subprocess.run([sys.executable, str(UPDATE_DASHBOARD)],
                       cwd=str(REPO_ROOT), check=False)
        git("add", "index.html", check=False)


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


def do_deletion(matches, label):
    """git-rm matches, regenerate the dashboard, and commit on the current HEAD.
    Returns the number of files removed (0 means nothing was staged, so no
    commit was made)."""
    removed = delete_matches(matches)
    prune_empty_dirs()
    regenerate_dashboard()
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return 0
    git("commit", "-m", f"cleanup: remove {label}", check=False)
    return removed


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

    # Deletions must always land on a clean, up-to-date main so the live
    # dashboard updates and the push is never rejected as non-fast-forward,
    # regardless of which branch is checked out.
    original_branch = current_branch()
    switched = stashed = False

    # 1. Start clean and up to date on main: stash work, switch, sync.
    if is_dirty():
        git("stash", "push", "-u", "-m", "delete_report: preserve work", check=False)
        stashed = True
    if original_branch != "main":
        git("checkout", "main", check=False)
        switched = True
    git("pull", "origin", "main", check=False)

    # 2. Delete + regenerate dashboard + commit on main.
    removed = do_deletion(matches, label)

    if not removed:
        print("Nothing to delete on main (matched files were not present there).")
    else:
        # 3. Re-sync onto the latest remote before pushing, so we never push
        #    from a stale state. If the rebase conflicts (e.g. the churning
        #    index.html), drop our commit, hard-sync to remote, and re-apply
        #    the deletions on top of current main.
        git("fetch", "origin", "main", check=False)
        rebased = git("rebase", "origin/main", check=False)
        if rebased.returncode != 0:
            git("rebase", "--abort", check=False)
            pulled = git("pull", "--rebase", "origin", "main", check=False)
            if pulled.returncode != 0:
                git("rebase", "--abort", check=False)
                git("reset", "--hard", "origin/main", check=False)
                removed = do_deletion(matches, label)
        push = git("push", "origin", "main", check=False)
        if push.returncode != 0:
            print("Committed on main, but push failed — run "
                  "'git push origin main' manually.")
        else:
            print(f"Removed {removed} file(s); committed and pushed to main.")

    # 4. Return the user to their branch and restore their stashed work.
    if switched:
        back = git("checkout", original_branch, check=False)
        if back.returncode != 0:
            print(f"! Could not switch back to {original_branch}; you are on main.")
            return
    if stashed:
        pop = git("stash", "pop", check=False)
        if pop.returncode != 0:
            print("! Could not restore stashed changes; see 'git stash list'.")


if __name__ == "__main__":
    main()
