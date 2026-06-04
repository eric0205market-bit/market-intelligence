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
# This script is meant to run against a DEDICATED CLONE kept OUTSIDE Dropbox
# (so Dropbox can't sync .git mid-commit). It always hard-resets to origin/main
# before collecting, so the clone never diverges. Idempotent and safe to re-run.
#
# Schedule it with the launchd plist in this repo (see SETUP below), or invoke
# it by hand:  bash scripts/run_youtube_local.sh
#
# SETUP (one time):
#   git clone https://github.com/eric0205market-bit/market-intelligence.git \
#       "$HOME/market-intel-youtube"
#   # install deps into the python3 the plist uses:
#   python3 -m pip install --upgrade "yt-dlp[default]" curl_cffi youtube-transcript-api
#   cp "$HOME/market-intel-youtube/config/com.marketintel.youtube.plist" \
#       "$HOME/Library/LaunchAgents/"
#   launchctl load "$HOME/Library/LaunchAgents/com.marketintel.youtube.plist"
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

cd "$REPO_DIR" || { log "FATAL: cannot cd $REPO_DIR"; exit 1; }

log "=== YouTube local run starting in $REPO_DIR ==="
git config user.name  "github-actions"   >/dev/null 2>&1
git config user.email "actions@github.com" >/dev/null 2>&1

# Sync to the authoritative main, discarding any local state in this clone.
git fetch origin main --quiet || { log "FATAL: git fetch failed"; exit 1; }
git checkout main --quiet 2>/dev/null || git checkout -b main --quiet
git reset --hard origin/main --quiet || { log "FATAL: git reset failed"; exit 1; }

# Collect (writes raw/youtube/** and state/youtube_seen.json). Pass through any
# extra flags, e.g. --max-channels for a smoke run.
python3 scripts/collect_youtube.py "$@" 2>&1 | tee -a "$LOG"

git add -- raw/youtube state/youtube_seen.json 2>/dev/null || true
if git diff --cached --quiet; then
  log "No new YouTube data to commit."
  log "=== done (nothing to commit) ==="
  exit 0
fi

git commit -q -m "data: youtube collection $(date -u '+%Y-%m-%d %H:%M')"
for i in 1 2 3; do
  if git push origin main --quiet; then
    log "Pushed to main."
    break
  fi
  log "Push attempt $i failed; rebasing and retrying."
  git pull --rebase origin main --quiet || true
done
log "=== done ==="
