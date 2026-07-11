#!/bin/bash
# Local runner for the YouTube/Podcasts collector.
#
# WHY THIS EXISTS: YouTube hard-blocks per-video extraction from GitHub Actions
# (datacenter) IPs with a "Sign in to confirm you're not a bot" error — every
# yt-dlp player client fails there. The identical collector gets a ~100%
# transcript hit-rate from a residential IP. So transcripts are collected from
# a residential machine on a schedule (launchd on macOS) instead of in Actions,
# and the results are committed straight to main — the same commit-to-main flow
# the Actions collectors use.
#
# Runs against the Dropbox working copy (unified repo). Path is resolved
# relative to this script's location — no hardcoded paths. Working-tree edits
# are preserved via --autostash; only raw/youtube and state/youtube_seen.json
# are ever staged or committed. Idempotent and safe to re-run.
#
# Schedule it with the launchd plist in this repo (see SETUP below), or invoke
# it by hand:  bash scripts/run_youtube_local.sh
#
# SETUP (one time):
#   # install deps into the python3 the plist uses:
#   python3 -m pip install --upgrade "yt-dlp[default]" curl_cffi youtube-transcript-api
#   cp config/com.marketintel.youtube.plist ~/Library/LaunchAgents/
#   # edit the plist's ProgramArguments path to this file's absolute location,
#   # then:
#   launchctl load ~/Library/LaunchAgents/com.marketintel.youtube.plist
set -uo pipefail

# Repo root = parent of this script's dir (scripts/..).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# launchd starts with a minimal PATH; add the usual tool locations so git,
# python3 and yt-dlp resolve. Adjust if your python lives elsewhere.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/market-intel-youtube.log"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"YouTube Daily\"" 2>/dev/null || true; }

# Shared IP-health state + monitor — one residential IP serves both collectors.
HISTORY_ROOT="$(cd "$REPO_DIR/.." && pwd)/youtube-history"
BACKOFF_FILE="$HISTORY_ROOT/_state/BACKOFF"
# Soft-throttle monitor, shared with the backfill wrapper. If the file is
# missing, disable it LOUDLY rather than break collection (fail loud, not blind).
if [ -f "$SCRIPT_DIR/_ip_health.sh" ]; then
    # shellcheck source=scripts/_ip_health.sh
    source "$SCRIPT_DIR/_ip_health.sh"
else
    log "WARN: scripts/_ip_health.sh missing — soft-throttle monitor DISABLED"
    throttle_watch() { :; }
fi

cd "$REPO_DIR" || { log "FATAL: cannot cd $REPO_DIR"; exit 1; }

log "=== YouTube local run starting in $REPO_DIR ==="

# --- GAP 1: honor the shared BACKOFF the backfill wrapper writes on exit-10 --
# One residential IP serves both collectors. If backfill hard-stopped on a
# 429 / bot signal in the last 24h, the daily run stands down too rather than
# charge the sensitized IP. mtime of the marker = time of the hard-stop.
# NOTE: the marker only clears once it is >24h old. Whichever collector next
# sees a stale one removes it — so if backfill is ever DISABLED, the daily run
# clears the dead marker itself (below) instead of logging "stale" forever.
if [ -f "$BACKOFF_FILE" ]; then
    AGE=$(( $(date +%s) - $(stat -f %m "$BACKOFF_FILE") ))
    if [ "$AGE" -lt 86400 ]; then
        log "BACKOFF active (${AGE}s < 86400s / 24h) — skipping daily run to protect shared IP"
        notify "Daily YouTube run skipped — shared BACKOFF active (IP cooling down)"
        exit 0
    fi
    log "BACKOFF marker stale (${AGE}s >= 24h) — clearing dead marker and proceeding"
    rm -f "$BACKOFF_FILE"
fi

git config user.name  "github-actions"   >/dev/null 2>&1
git config user.email "actions@github.com" >/dev/null 2>&1

# Ensure we are on main, but NEVER `git reset --hard`: this script may run in the
# browsable working copy, so it must not discard the user's edits. We touch ONLY
# our own output paths (raw/youtube, state) and integrate via rebase --autostash,
# which parks any unrelated working changes and restores them afterward.
git fetch origin main --quiet || { log "FATAL: git fetch failed"; exit 1; }
git checkout main --quiet 2>/dev/null || git checkout -b main --quiet

# Collect (writes raw/youtube/** and state/youtube_seen.json). Pass through any
# extra flags, e.g. --max-channels for a smoke run.
TMPOUT="$(mktemp)"; trap 'rm -f "$TMPOUT"' EXIT
python3 scripts/collect_youtube.py "$@" 2>&1 | tee "$TMPOUT" | tee -a "$LOG"
throttle_watch "$TMPOUT" "daily"

# Stage ONLY our outputs and commit them if there are any.
git add -- raw/youtube state/youtube_seen.json 2>/dev/null || true
if git diff --cached --quiet; then
  log "No new YouTube data to commit."
else
  git commit -q -m "data: youtube collection $(date -u '+%Y-%m-%d %H:%M')"
  log "Committed new collection data."
fi

# Integrate latest main and push. --autostash preserves any unrelated edits in
# the working tree (the browsable copy); no hard reset, ever.
for i in 1 2 3; do
  if ! git pull --rebase --autostash origin main --quiet 2>>"$LOG"; then
    log "pull --rebase failed (attempt $i); aborting rebase and retrying."
    git rebase --abort 2>/dev/null || true
    continue
  fi
  if git push origin main --quiet; then
    log "Pushed to main (or already up to date)."
    break
  fi
  log "Push attempt $i failed; retrying."
done
log "=== done ==="
