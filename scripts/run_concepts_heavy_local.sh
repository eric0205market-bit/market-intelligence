#!/bin/bash
# run_concepts_heavy_local.sh — launchd wrapper for the Concepts HEAVY think-tank
# backfill (Brookings, Carnegie, CFR, RAND, PIIE, Chatham House, WEF, Hudson, GMF,
# IISS, IMF Blog, NBER, SSRN, CSIS, Atlantic Council).
#
# SEPARATE from the signal-tier backfill (run_concepts_backfill_local.sh) — its own
# lockfile, its own _state/heavy_state.json, its own runlog — so the two never race.
# ZERO git operations; everything is written to concepts-history/ (OUTSIDE the repo).
#
# Heavy = STRUCTURAL genre+length filter (theme-agnostic, NO watchlist): drop non-
# analytical formats by URL path + a ~800-word floor; render-retry under-rendered
# analysis before the length gate. Thousands of fetches -> drains over the at-
# computer windows, resumable via file-dedup + the heavy_state.json done-set, then
# NO-OPs once complete.
#
# Fires at 17:30 + 22:30 local via com.marketintel.concepts-heavy.plist — staggered
# from the signal-tier backfill (16:45 / 21:45) and the YouTube backfill (16:00 /
# 21:00) so no two heavy local jobs start together.
#
# PER-SITE QUARANTINE (no global halt): a 429/bot block or repeated failures on one
# think-tank records that SOURCE in heavy_state.json ("blocked": {slug:{at,reason}}),
# cools it 24h, and CONTINUES through the others. A source with no usable sitemap is
# FLAGGED in the log for rework (never guessed).
#
# Safeguards:
#   lockfile  — PID-based single-instance guard (no stacked runs)
#   per-site  — collector quarantines a blocked site for 24h; the run continues
#   osascript — macOS notification if a site got quarantined / flagged or on error
#
# INSTALL (one time):
#   cp config/com.marketintel.concepts-heavy.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.marketintel.concepts-heavy.plist
#   launchctl start com.marketintel.concepts-heavy        # kick off the first run now
#
# MANUAL RUN (for testing):
#   bash scripts/run_concepts_heavy_local.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HISTORY_ROOT="$(cd "$REPO_DIR/.." && pwd)/concepts-history"
STATE_DIR="$HISTORY_ROOT/_state"
RUNLOG_DIR="$HISTORY_ROOT/_runlog"
STATE_FILE="heavy_state.json"
LOCKFILE="$STATE_DIR/heavy.lock"
TODAY="$(date -u '+%Y-%m-%d')"
LOG="$RUNLOG_DIR/launchd_heavy_${TODAY}.md"

# UNCAPPED by default — drain the whole heavy tier over successive firings (resumable
# via file-dedup + the done-set). Overridable via env for testing.
SESSION_CAP="${CONCEPTS_HEAVY_SESSION_CAP:-1000000}"
PER_SOURCE_CAP="${CONCEPTS_HEAVY_PER_SOURCE_CAP:-1000000}"
MIN_WORDS="${CONCEPTS_HEAVY_MIN_WORDS:-800}"

# launchd starts with a bare PATH; add tool locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
mkdir -p "$RUNLOG_DIR" "$STATE_DIR"

log()    { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"Concepts Heavy\"" 2>/dev/null || true; }

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

# NOTE: no global BACKOFF gate. A blocked SITE is quarantined per-source inside the
# collector (heavy_state.json "blocked"); the run is never globally halted.

DONE_BEFORE="$(python3 -c "import json;print(len(json.load(open('$STATE_DIR/$STATE_FILE')).get('done',[])))" 2>/dev/null || echo 0)"
RECORDS_BEFORE="$(find "$HISTORY_ROOT" -name '*.json' -not -path '*_state*' -not -path '*_runlog*' 2>/dev/null | wc -l | tr -d ' ')"

log "=== Concepts HEAVY starting | sources complete=${DONE_BEFORE}/15 | records=${RECORDS_BEFORE} | min_words=${MIN_WORDS} | UNCAPPED (session=${SESSION_CAP} per-source=${PER_SOURCE_CAP}) ==="
log "repo:    $REPO_DIR"
log "history: $HISTORY_ROOT (OUTSIDE git)"

# Belt-and-suspenders: no git commands below this line.
cd "$REPO_DIR" || { log "FATAL: cannot cd $REPO_DIR"; exit 1; }

TMPOUT="$(mktemp)"
python3 scripts/backfill_concepts_history.py --heavy-tier --start 2025-01-01 \
        --state-file "$STATE_FILE" --min-words "$MIN_WORDS" \
        --session-cap "$SESSION_CAP" --per-source-cap "$PER_SOURCE_CAP" 2>&1 \
    | tee "$TMPOUT" | tee -a "$LOG"
EXIT_CODE="${PIPESTATUS[0]}"

DONE_AFTER="$(python3 -c "import json;print(len(json.load(open('$STATE_DIR/$STATE_FILE')).get('done',[])))" 2>/dev/null || echo 0)"
RECORDS_AFTER="$(find "$HISTORY_ROOT" -name '*.json' -not -path '*_state*' -not -path '*_runlog*' 2>/dev/null | wc -l | tr -d ' ')"
WRITTEN_LINE="$(grep 'written this run' "$TMPOUT" | tail -1)"

# Per-site quarantined sources, surfaced from heavy state (NOT a global halt).
BLOCKED="$(python3 -c "import json;b=json.load(open('$STATE_DIR/$STATE_FILE')).get('blocked',{});print(', '.join(sorted(b)) if b else 'none')" 2>/dev/null || echo '?')"

if [ "$EXIT_CODE" -eq 0 ]; then
    log "=== DONE | exit 0 | sources complete ${DONE_BEFORE}→${DONE_AFTER}/15 | records ${RECORDS_BEFORE}→${RECORDS_AFTER} ==="
    [ -n "$WRITTEN_LINE" ] && log "  $WRITTEN_LINE"
    log "  per-site quarantined (24h cooldown, run continued past them): ${BLOCKED}"
    if [ "$BLOCKED" != "none" ] && [ "$BLOCKED" != "?" ]; then
        notify "Concepts Heavy done — quarantined: ${BLOCKED}"
    fi
else
    log "UNEXPECTED EXIT $EXIT_CODE — see session log above (quarantined: ${BLOCKED})"
    notify "Concepts Heavy unexpected exit $EXIT_CODE"
fi
