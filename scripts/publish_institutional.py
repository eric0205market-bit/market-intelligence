#!/usr/bin/env python3
"""One-command publish for the Institutional Research weekly report.

Used by the Desktop routine after it has produced the synthesis JSON.
This single command:
  1. fetches origin and checks out claude/institutional (creating it from
     origin if the local branch doesn't exist yet)
  2. rebases on origin/claude/institutional so we're on the latest base
  3. substitutes the JSON into templates/institutional_report.html
     (same __REPORT_DATA__ placeholder mechanism as render_twitter_report.py)
  4. writes reports/institutional_<YYYY-MM-DD>.html
  5. git add + commit (skips cleanly if the file is byte-identical)
  6. git push origin claude/institutional  (triggers merge-to-main.yml,
     which lands the report on main and regenerates the dashboard)

Usage:
    python3 scripts/publish_institutional.py PATH_TO_REPORT.json

Optional flags:
    --date YYYY-MM-DD     date used in the filename (default: today UTC)
    --branch NAME         override target branch (default: claude/institutional)
    --no-push             render + commit only (skip the push)
"""
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "templates" / "institutional_report.html"
REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_BRANCH = "claude/institutional"


def run(cmd, **kw):
    """Run a git/shell command in the repo, raising on failure."""
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True, **kw)


def quiet(cmd):
    """Run a command and return its exit code without printing."""
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True).returncode


def commit_message(date, data):
    """Mirror the Twitter routine's commit-message style (date + stats)."""
    is_ = (data.get("input_stats") or {}) if isinstance(data, dict) else {}
    cv = (data.get("coverage") or {}) if isinstance(data, dict) else {}
    parts = []
    if is_.get("total_articles") is not None:
        parts.append(f"{is_['total_articles']} articles")
    if is_.get("sources_present") is not None:
        parts.append(f"{is_['sources_present']} sources")
    pct = cv.get("coverage_pct")
    if pct is not None:
        if pct <= 1:
            pct *= 100
        parts.append(f"{int(round(pct))}% coverage")
    detail = ", ".join(parts) or "published"
    return f"Institutional Research: {date} — {detail}"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("data", help="path to the institutional report JSON")
    p.add_argument("--date", help="YYYY-MM-DD used in the output filename "
                                   "(default: today UTC)")
    p.add_argument("--branch", default=DEFAULT_BRANCH,
                   help=f"target branch (default: {DEFAULT_BRANCH})")
    p.add_argument("--no-push", action="store_true",
                   help="skip the push (still renders, adds, and commits)")
    args = p.parse_args()

    data_path = Path(args.data).resolve()
    if not data_path.exists():
        sys.exit(f"data not found: {data_path}")
    if not TEMPLATE.exists():
        sys.exit(f"template not found: {TEMPLATE}")

    raw = data_path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"data is not valid JSON: {exc}")

    date = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    out_name = f"institutional_{date}.html"
    out_path = REPORTS_DIR / out_name

    # --- branch setup: be safe across fresh clones AND warm working trees ----
    run(["git", "fetch", "origin", args.branch])
    if quiet(["git", "rev-parse", "--verify", args.branch]) == 0:
        run(["git", "checkout", args.branch])
    else:
        run(["git", "checkout", "-b", args.branch, f"origin/{args.branch}"])
    # rebase so we don't clobber other commits since last run
    run(["git", "pull", "--rebase", "origin", args.branch])

    # --- render: simple placeholder substitution -----------------------------
    template = TEMPLATE.read_text(encoding="utf-8")
    html = template.replace("__REPORT_DATA__", raw)
    if "__REPORT_DATA__" in html:
        sys.exit("ERROR: placeholder __REPORT_DATA__ still present after substitution")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path.relative_to(REPO_ROOT)} ({len(html):,} bytes)")

    # --- commit (idempotent: skip if nothing staged) -------------------------
    run(["git", "add", str(out_path.relative_to(REPO_ROOT))])
    if quiet(["git", "diff", "--cached", "--quiet"]) == 0:
        print("nothing to commit (file already up to date) — done.")
        return
    run(["git", "commit", "-m", commit_message(date, parsed)])

    if args.no_push:
        print("--no-push: skipping push")
        return

    # --- push with the same retry+rebase pattern as collect-twitter.yml ------
    for attempt in (1, 2, 3):
        try:
            run(["git", "push", "origin", args.branch])
            break
        except subprocess.CalledProcessError:
            if attempt == 3:
                sys.exit("push failed after 3 attempts")
            print(f"push failed (attempt {attempt}); pulling --rebase before retry")
            run(["git", "pull", "--rebase", "origin", args.branch])

    print(f"pushed to origin/{args.branch}; merge-to-main.yml will land it on main.")


if __name__ == "__main__":
    main()
