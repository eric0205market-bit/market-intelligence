#!/bin/bash
# Local residential runner for cloud-IP-blocked Concepts DAILY sources.
#
# WHY THIS EXISTS: some Concepts sources are healthy from a residential IP but
# get near-zero anchors from GitHub Actions' datacenter IPs (Chatham House,
# IEA Oil Market Report — confirmed 2026-07-08: Actions gets ~2 anchors,
# residential gets a full listing, same pattern as scripts/run_youtube_local.sh
# and YouTube's Actions block). This is the DAILY analog of that fix, NOT the
# history backfill — it writes into the tracked raw/concepts/ tree (via
# collect_concepts.py, same as the cloud cron) and commits straight to main,
# so recovered articles flow into the normal daily extraction worklist. It
# does NOT touch concepts-history/ and shares nothing with the backfill state.
#
# REUSABLE SHAPE (read this before copying for Technology/Society):
#   This script only differs from a generic "residential daily supplement"
#   runner in the 4 variables right below (STREAM/COLLECTOR/RAW_DIR/SLUGS) plus
#   the commit message. To stand up the same fix for Technology or Society
#   later: copy this file, point COLLECTOR at scripts/collect_technology.py or
#   scripts/collect_society.py, RAW_DIR at raw/technology or raw/society, set
#   SLUGS to that stream's residential_recoverable-tagged source slugs, and
#   give it its own launchd Label + StandardOutPath in a sibling .plist (see
#   config/com.marketintel.concepts-residential.plist for the template).
#   Both collectors already take the same --ids/--days CLI shape as
#   collect_concepts.py, so the WRAPPER needs no changes beyond the 4
#   variables — but the --residential opt-in gate (a source must be BOTH
#   collect:false AND residential_only:true to run under --residential; every
#   other collect:false/paywalled source stays skipped) currently only exists
#   in collect_concepts.py (skip_reason_for()/--residential flag). Porting
#   this wrapper to Technology/Society also means porting that same ~10-line
#   gate into collect_technology.py/collect_society.py first.
#
# SAFETY: `collect_concepts.py --ids <slugs>` only touches the named sources
# (see main()'s --ids filter) — this NEVER runs the full 47-source daily
# sweep, so it can't double-collect or interfere with the 10:00 UTC cloud cron.
# Only raw/concepts and its _runs/<date> log are ever staged or committed —
# same --autostash/no-hard-reset discipline as run_youtube_local.sh, so any
# unrelated working-tree edits in the Dropbox browsable copy are preserved.
#
# SETUP (one time, NOT done automatically by this script):
#   cp config/com.marketintel.concepts-residential.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.marketintel.concepts-residential.plist
#
# MANUAL RUN (for testing — this is how you should first confirm it works):
#   bash scripts/run_concepts_residential_local.sh
set -uo pipefail

# --- stream config (the 4 lines to change when copying for another stream) ---
STREAM="concepts"
COLLECTOR="scripts/collect_concepts.py"
RAW_DIR="raw/concepts"
SLUGS="chatham_house,iea_oil_market_report"
DAYS="${CONCEPTS_RESIDENTIAL_DAYS:-3}"   # tight daily window; override for a one-off wide test

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# launchd starts with a minimal PATH; add the usual tool locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/market-intel-${STREAM}-residential.log"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }

cd "$REPO_DIR" || { log "FATAL: cannot cd $REPO_DIR"; exit 1; }

log "=== ${STREAM} residential run starting (slugs=${SLUGS} days=${DAYS}) in $REPO_DIR ==="
git config user.name  "github-actions"     >/dev/null 2>&1
git config user.email "actions@github.com" >/dev/null 2>&1

# Same non-destructive integration discipline as run_youtube_local.sh: never
# `git reset --hard` (this repo may be the owner's browsable working copy),
# only touch our own output paths, integrate via rebase --autostash.
git fetch origin main --quiet || { log "FATAL: git fetch failed"; exit 1; }
git checkout main --quiet 2>/dev/null || git checkout -b main --quiet

# --resume merges into today's existing raw/concepts/_runs/<date>/{run,funnel,
# progress}.json instead of overwriting them (a no-op if no run happened yet
# today) — avoids clobbering the cloud cron's or another local run's same-day
# diagnostics with just this narrow --ids slice.
python3 "$COLLECTOR" --ids "$SLUGS" --days "$DAYS" --residential --resume 2>&1 | tee -a "$LOG"

git add -- "$RAW_DIR" 2>/dev/null || true
if git diff --cached --quiet; then
  log "No new ${STREAM} residential data to commit."
else
  git commit -q -m "data: ${STREAM} residential collection $(date -u '+%Y-%m-%d %H:%M') (${SLUGS})"
  log "Committed new residential collection data."
fi

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
