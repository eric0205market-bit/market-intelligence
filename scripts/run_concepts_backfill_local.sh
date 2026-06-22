#!/bin/bash
# run_concepts_backfill_local.sh — launchd wrapper for the Concepts historical backfill.
#
# Mirrors scripts/run_youtube_backfill_local.sh with ZERO git operations. The
# backfill writes everything to concepts-history/ (OUTSIDE the git repo, sibling
# of youtube-history/); nothing is ever committed, pushed, or staged.
#
# Fires overnight (02:00 + 04:00 local) via com.marketintel.concepts-backfill.plist
# — clear of the Concepts daily cloud cron (10:00 UTC = 12:00 local), the YouTube
# daily collector (12:00), and the YouTube backfill (16:00 / 21:00). Each firing
# chips a session-capped chunk off the Stage-1+2 signal tier, resumable via
# file-dedup + the _state/backfill_state.json done-set, then NO-OPs once complete.
#
# Safeguards:
#   lockfile  — PID-based single-instance guard (no stacked runs)
#   BACKOFF   — 24h skip after any exit-10 (429 / bot-check / consecutive fails)
#   osascript — macOS notification on hard-stop or unexpected exit
#
# INSTALL (one time):
#   cp config/com.marketintel.concepts-backfill.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.marketintel.concepts-backfill.plist
#
# MANUAL RUN (for testing):
#   bash scripts/run_concepts_backfill_local.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HISTORY_ROOT="$(cd "$REPO_DIR/.." && pwd)/concepts-history"
STATE_DIR="$HISTORY_ROOT/_state"
RUNLOG_DIR="$HISTORY_ROOT/_runlog"
LOCKFILE="$STATE_DIR/backfill.lock"
BACKOFF_FILE="$STATE_DIR/BACKOFF"
TODAY="$(date -u '+%Y-%m-%d')"
LOG="$RUNLOG_DIR/launchd_${TODAY}.md"

# Per-firing throttle budget (articles). Overnight 2 firings ≈ 2×SESSION_CAP/night.
SESSION_CAP="${CONCEPTS_BACKFILL_SESSION_CAP:-150}"

# launchd starts with a bare PATH; add tool locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
mkdir -p "$RUNLOG_DIR" "$STATE_DIR"

log()    { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"Concepts Backfill\"" 2>/dev/null || true; }

TMPOUT=""
trap 'rm -f "$LOCKFILE" ${TMPOUT:+"$TMPOUT"}' EXIT

# --- single-instance lock (macOS has no flock(1); PID-based equivalent) ---
if [ -f "$LOCKFILE" ]; then
    OLD_PID="$(cat "$LOCKFILE" 2>/dev/null || echo "")"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        log "already running (PID ${OLD_PID}) — skipping this trigger"; exit 0
    fi
    log "stale lockfile (PID ${OLD_PID:-unknown}) — clearing"
fi
echo "$$" > "$LOCKFILE"

# --- 24h BACKOFF after any exit-10 (block/429 signal) ---
if [ -f "$BACKOFF_FILE" ]; then
    AGE=$(( $(date +%s) - $(stat -f %m "$BACKOFF_FILE") ))
    if [ "$AGE" -lt 86400 ]; then
        log "BACKOFF active (${AGE}s/86400s) — skipping run"; exit 0
    fi
    log "BACKOFF expired — clearing"; rm -f "$BACKOFF_FILE"
fi

DONE_BEFORE="$(python3 -c "import json;print(len(json.load(open('$STATE_DIR/backfill_state.json')).get('done',[])))" 2>/dev/null || echo 0)"
RECORDS_BEFORE="$(find "$HISTORY_ROOT" -name '*.json' -not -path '*_state*' -not -path '*_runlog*' 2>/dev/null | wc -l | tr -d ' ')"

log "=== Concepts backfill starting | sources complete=${DONE_BEFORE} | records=${RECORDS_BEFORE} | session-cap=${SESSION_CAP} ==="
log "repo:    $REPO_DIR"
log "history: $HISTORY_ROOT (OUTSIDE git)"

# Belt-and-suspenders: no git commands below this line.
cd "$REPO_DIR" || { log "FATAL: cannot cd $REPO_DIR"; exit 1; }

TMPOUT="$(mktemp)"
python3 scripts/backfill_concepts_history.py --signal-tier --start 2025-01-01 \
        --session-cap "$SESSION_CAP" 2>&1 \
    | tee "$TMPOUT" | tee -a "$LOG"
EXIT_CODE="${PIPESTATUS[0]}"

DONE_AFTER="$(python3 -c "import json;print(len(json.load(open('$STATE_DIR/backfill_state.json')).get('done',[])))" 2>/dev/null || echo 0)"
RECORDS_AFTER="$(find "$HISTORY_ROOT" -name '*.json' -not -path '*_state*' -not -path '*_runlog*' 2>/dev/null | wc -l | tr -d ' ')"
SESSION_LINE="$(grep 'session fetched:' "$TMPOUT" | tail -1)"

if [ "$EXIT_CODE" -eq 0 ]; then
    log "=== DONE | exit 0 | sources complete ${DONE_BEFORE}→${DONE_AFTER}/31 | records ${RECORDS_BEFORE}→${RECORDS_AFTER} ==="
    [ -n "$SESSION_LINE" ] && log "  $SESSION_LINE"
elif [ "$EXIT_CODE" -eq 10 ]; then
    touch "$BACKOFF_FILE"
    log "HARD STOP — exit 10 (429 / bot-check / consecutive fails). BACKOFF 24h. MANUAL REVIEW."
    notify "Concepts backfill HARD-STOP — backing off 24h"
else
    log "UNEXPECTED EXIT $EXIT_CODE — see session log above"
    notify "Concepts backfill unexpected exit $EXIT_CODE"
fi
