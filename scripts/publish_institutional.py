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
DATA_PATH = REPO_ROOT / "data" / "institutional" / "latest" / "articles_institutional.json"
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


def override_from_data(parsed, data):
    """Replace the routine-LLM's period / input_stats with values derived from
    the canonical collected-articles file. Leaves after_filter untouched (per
    request — it's the LLM's own filter count, not a data fact).

    Returns a list of human-readable override descriptions for logging."""
    overrides = []
    arts = data.get("articles") or []
    today = datetime.datetime.now(datetime.timezone.utc).date()

    dates = []
    for a in arts:
        d = (a.get("date") or "").strip()
        if len(d) < 10:
            continue
        try:
            dt = datetime.date.fromisoformat(d[:10])
        except ValueError:
            continue
        # Cap newest at today — keeps misparsed future dates (e.g. 2027-…)
        # from polluting period.to. The articles themselves are unchanged.
        if dt > today:
            continue
        dates.append(dt)
    sources = {a.get("source_id") for a in arts if a.get("source_id")}

    period = parsed.setdefault("period", {})
    input_stats = parsed.setdefault("input_stats", {})

    if data.get("lookback_days") is not None:
        old, new = period.get("lookback_days"), data["lookback_days"]
        if old != new:
            period["lookback_days"] = new
            overrides.append(f"period.lookback_days: {old} -> {new}")
    if dates:
        new_from, new_to = min(dates).isoformat(), max(dates).isoformat()
        old_from, old_to = period.get("from"), period.get("to")
        if old_from != new_from:
            period["from"] = new_from
            overrides.append(f"period.from: {old_from} -> {new_from}")
        if old_to != new_to:
            period["to"] = new_to
            overrides.append(f"period.to: {old_to} -> {new_to}")
    if arts:
        old, new = input_stats.get("total_articles"), len(arts)
        if old != new:
            input_stats["total_articles"] = new
            overrides.append(f"input_stats.total_articles: {old} -> {new}")
    if sources:
        old, new = input_stats.get("sources_present"), len(sources)
        if old != new:
            input_stats["sources_present"] = new
            overrides.append(f"input_stats.sources_present: {old} -> {new}")

    return overrides


def strip_images_outside_charts(parsed):
    """Images belong only to D_charts (per the routine spec — images are
    high-value here and shouldn't be reassigned). Strip them from A_debates'
    attributed items, B_calls, and C_deep_reads. Returns (items_touched,
    images_stripped)."""
    items_touched = 0
    images_stripped = 0
    s = (parsed.get("sections") or {})
    for theme in (s.get("A_debates") or []):
        for it in (theme.get("items") or []):
            imgs = it.get("images") or []
            if imgs:
                images_stripped += len(imgs)
                items_touched += 1
                it["images"] = []
    for key in ("B_calls", "C_deep_reads"):
        for it in (s.get(key) or []):
            imgs = it.get("images") or []
            if imgs:
                images_stripped += len(imgs)
                items_touched += 1
                it["images"] = []
    return items_touched, images_stripped


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

    # --- derive period / input_stats from the CANONICAL data file -----------
    # The routine LLM tends to copy the spec's example values verbatim (e.g.
    # lookback_days: 30) instead of reading the data. Override here so the
    # published report reflects what was actually collected.
    if DATA_PATH.exists():
        try:
            canonical = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"warning: {DATA_PATH} is not valid JSON; period/stats NOT overridden")
        else:
            for line in override_from_data(parsed, canonical):
                print(f"override: {line}")
    else:
        print(f"warning: canonical data file not found at {DATA_PATH}; "
              "period/stats NOT overridden")

    # --- enforce images-only-in-charts -------------------------------------
    n_items, n_imgs = strip_images_outside_charts(parsed)
    if n_imgs:
        print(f"stripped {n_imgs} image(s) from {n_items} item(s) outside D_charts "
              "(images belong only to charts)")

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

    # --- render: substitute the (possibly-mutated) JSON into the template ---
    template = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(parsed, ensure_ascii=False)
    html = template.replace("__REPORT_DATA__", payload)
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
