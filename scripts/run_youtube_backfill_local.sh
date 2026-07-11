#!/bin/bash
# run_youtube_backfill_local.sh — launchd wrapper for the YouTube historical backfill.
#
# Mirrors the structure of run_youtube_local.sh but with ZERO git operations.
# The backfill writes everything to youtube-history/ (outside the git repo);
# nothing is ever committed, pushed, or staged by this wrapper.
#
# Fires at 16:00 local via com.marketintel.youtube-backfill.plist — 4 hours
# after the 12:00 daily collector. Same residential IP, non-overlapping windows.
#
# Safeguards:
#   flock     — prevents stacked runs if a session overruns its window
#   BACKOFF   — 24 h skip after any exit-10 (IP signal / bot-check / consecutive fails)
#   osascript — macOS notification on hard-stop or unexpected exit
#
# INSTALL (one time):
#   cp config/com.marketintel.youtube-backfill.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.marketintel.youtube-backfill.plist
#
# MANUAL RUN (for testing):
#   bash scripts/run_youtube_backfill_local.sh

set -uo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HISTORY_ROOT="$(cd "$REPO_DIR/.." && pwd)/youtube-history"
STATE_DIR="$HISTORY_ROOT/_state"
RUNLOG_DIR="$HISTORY_ROOT/_runlog"
LOCKFILE="$STATE_DIR/backfill.lock"
BACKOFF_FILE="$STATE_DIR/BACKOFF"
TODAY="$(date -u '+%Y-%m-%d')"
LOG="$RUNLOG_DIR/launchd_${TODAY}.md"

# launchd starts with a bare PATH; add all tool locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Create runlog + state dirs if needed (already exist after first backfill session).
mkdir -p "$RUNLOG_DIR" "$STATE_DIR"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()    { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"YouTube Backfill\"" 2>/dev/null || true; }

# Soft-throttle monitor, shared with the daily wrapper (same file, can't drift).
# Missing file → disable loudly, never break collection.
if [ -f "$SCRIPT_DIR/_ip_health.sh" ]; then
    # shellcheck source=scripts/_ip_health.sh
    source "$SCRIPT_DIR/_ip_health.sh"
else
    log "WARN: scripts/_ip_health.sh missing — soft-throttle monitor DISABLED"
    throttle_watch() { :; }
fi

# TMPOUT declared early so the EXIT trap can always reference it safely.
TMPOUT=""
trap 'rm -f "$LOCKFILE" ${TMPOUT:+"$TMPOUT"}' EXIT

# ---------------------------------------------------------------------------
# Lockfile — PID-based single-instance guard.
# macOS does not ship flock(1); this is the portable equivalent.
# On EXIT (crash, kill, or normal finish) the trap above removes the lockfile,
# so a crashed run never permanently blocks subsequent triggers.
# ---------------------------------------------------------------------------
if [ -f "$LOCKFILE" ]; then
    OLD_PID="$(cat "$LOCKFILE" 2>/dev/null || echo "")"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        log "already running (PID ${OLD_PID} holds lock) — skipping this trigger"
        exit 0
    fi
    log "stale lockfile (PID ${OLD_PID:-unknown} no longer running) — clearing and proceeding"
fi
echo "$$" > "$LOCKFILE"

# ---------------------------------------------------------------------------
# BACKOFF check — skip for 24 h after any exit-10 (IP / bot signal).
# mtime of the BACKOFF file is the timestamp of the hard-stop.
# ---------------------------------------------------------------------------
if [ -f "$BACKOFF_FILE" ]; then
    AGE=$(( $(date +%s) - $(stat -f %m "$BACKOFF_FILE") ))
    if [ "$AGE" -lt 86400 ]; then
        log "BACKOFF active (${AGE}s elapsed, need 86400s / 24h) — skipping run"
        exit 0
    else
        log "BACKOFF expired (${AGE}s elapsed) — clearing marker and proceeding"
        rm -f "$BACKOFF_FILE"
    fi
fi

# ---------------------------------------------------------------------------
# Snapshot roster cursor BEFORE run (for the end-of-run summary line).
# ---------------------------------------------------------------------------
CURSOR_BEFORE="$(python3 -c "
import json, sys
try:
    d = json.load(open('$HISTORY_ROOT/_state/backfill_state.json'))
    print(d.get('roster_cursor', 0))
except Exception:
    print('?')
" 2>/dev/null || echo '?')"

log "=== YouTube backfill starting | cursor=${CURSOR_BEFORE}/77 ==="
log "repo:    $REPO_DIR"
log "history: $HISTORY_ROOT"
log ""

# Belt-and-suspenders: no git commands appear below this line.
cd "$REPO_DIR" || { log "FATAL: cannot cd $REPO_DIR"; exit 1; }

# ---------------------------------------------------------------------------
# Run the backfill.
# Output is teed to:
#   $TMPOUT  — temp file; scraped for summary lines after run completes
#   $LOG     — dated session log in youtube-history/_runlog/
#   stdout   — captured by launchd into ~/Library/Logs/market-intel-youtube-backfill.log
# The trap ensures $TMPOUT is removed even if the script is killed.
# ---------------------------------------------------------------------------
TMPOUT="$(mktemp)"

python3 scripts/backfill_youtube_history.py --per-channel-cap 6 2>&1 \
    | tee "$TMPOUT" \
    | tee -a "$LOG"
EXIT_CODE="${PIPESTATUS[0]}"

# ---------------------------------------------------------------------------
# Snapshot roster cursor AFTER run.
# ---------------------------------------------------------------------------
CURSOR_AFTER="$(python3 -c "
import json, sys
try:
    d = json.load(open('$HISTORY_ROOT/_state/backfill_state.json'))
    print(d.get('roster_cursor', 0))
except Exception:
    print('?')
" 2>/dev/null || echo '?')"

FETCHED_LINE="$(grep 'Done\. Fetched' "$TMPOUT" | tail -1)"
CURSOR_LINE="$(grep 'roster_cursor →' "$TMPOUT" | tail -1)"

# ---------------------------------------------------------------------------
# Handle exit codes.
# ---------------------------------------------------------------------------
if [ "$EXIT_CODE" -eq 0 ]; then
    log ""
    log "=== DONE | exit 0 | cursor ${CURSOR_BEFORE}→${CURSOR_AFTER}/77 ==="
    [ -n "$FETCHED_LINE" ] && log "  $FETCHED_LINE"
    [ -n "$CURSOR_LINE"  ] && log "  $CURSOR_LINE"
    log ""

elif [ "$EXIT_CODE" -eq 10 ]; then
    touch "$BACKOFF_FILE"
    log ""
    log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    log "HARD STOP — exit 10: IP signal (HTTP 429 / bot-check / consecutive meta fails)"
    log "BACKOFF marker written: $BACKOFF_FILE"
    log "No run will start for the next 24 h. MANUAL REVIEW REQUIRED."
    log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    log ""
    notify "YouTube backfill HARD-STOP — IP signal, backing off"

else
    log ""
    log "UNEXPECTED EXIT CODE $EXIT_CODE — see session log above for details"
    log "cursor: ${CURSOR_BEFORE}→${CURSOR_AFTER}/77"
    log ""
    notify "YouTube backfill unexpected exit $EXIT_CODE"
fi

# --- GAP 2: soft-throttle watch on this run's captured output ---------------
throttle_watch "$TMPOUT" "backfill"
