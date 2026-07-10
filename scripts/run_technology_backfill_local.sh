#!/bin/bash
# run_technology_backfill_local.sh — launchd wrapper for the Technology historical
# backfill (RAW ONLY). Clone of scripts/run_concepts_backfill_local.sh, retargeted to
# the Technology stream with ZERO git operations.
#
# Writes everything to technology-history/ (OUTSIDE the git repo, sibling of
# concepts-history/ and youtube-history/); nothing is ever committed, pushed, or
# staged. The backfill collector (backfill_technology_history.py) already resolves
# its history root to the ABSOLUTE path below, so this wrapper pins the SAME absolute
# path for its bookkeeping — correct whether launched from the main clone or a git
# worktree (do NOT derive it from $REPO_DIR/.. like the Concepts wrapper, which breaks
# under a worktree).
#
# Fires at 16:45 + 21:45 local via com.marketintel.technology-backfill.plist — the
# slot the Concepts backfill used. Concepts is fully drained (NO-OPs), so unload it
# (see the plist header) and there is no clash:
#   • Concepts daily cloud cron   10:00 UTC (= 12:00 local)
#   • YouTube daily collector     12:00 local (launchd)
#   • YouTube backfill            16:00 / 21:00 local (launchd)
#   • Technology backfill         16:45 / 21:45 local (this job)
#
# SCOPE — the FINAL 12 core analytical sources (--core): firehose-5, carbon_brief,
# wood_mackenzie, ieee_spectrum (extraction-infeasible), timmerman_report (paywalled)
# and all flagged/render/Nature sources are EXCLUDED. The drain is UNCAPPED: one
# firing drains the whole core backlog in a single multi-hour run (12 DIFFERENT sites,
# load distributed). Resumable via file-dedup + _state/technology_backfill_state.json
# (done-set) — the 21:45 firing / next day continues any tail, then NO-OPs once
# complete. WORD-FLOOR (MIN_ARTICLE_WORDS) + RENDER-RETRY are active inside the
# collector (sub-floor records are dropped, SPA bodies re-rendered).
#
# PER-SITE QUARANTINE (no global halt): a 429/bot block or repeated failures on one
# site records that SOURCE in _state ("blocked": {slug:{at,reason}}), cools it 24h, and
# the run CONTINUES through the other sites. This wrapper just surfaces the blocked
# list at the end.
#
# Safeguards: PID lockfile (single instance); per-site quarantine in the collector;
# osascript notification on quarantine / unexpected exit.
#
# INSTALL (one time):
#   cp config/com.marketintel.technology-backfill.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.marketintel.technology-backfill.plist
# MANUAL RUN (for testing):
#   bash scripts/run_technology_backfill_local.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# History root: ABSOLUTE, matching backfill_technology_history.py DEFAULT_HISTORY_ROOT.
# Overridable via env (kept in sync with the collector, which honours the same var).
DEFAULT_HISTORY_ROOT="$HOME/Dropbox (Personal)/Business/InvestTool/market-intelligence/technology-history"
HISTORY_ROOT="${TECHNOLOGY_HISTORY_ROOT:-$DEFAULT_HISTORY_ROOT}"
export TECHNOLOGY_HISTORY_ROOT="$HISTORY_ROOT"
STATE_DIR="$HISTORY_ROOT/_state"
RUNLOG_DIR="$HISTORY_ROOT/_runlog"
STATE_FILE="technology_backfill_state.json"
LOCKFILE="$STATE_DIR/backfill.lock"
TODAY="$(date -u '+%Y-%m-%d')"
LOG="$RUNLOG_DIR/launchd_${TODAY}.md"

# UNCAPPED by default — one firing drains the entire core backlog (resumable via
# file-dedup, so a tail spills into the next firing). Overridable via env for testing.
SESSION_CAP="${TECHNOLOGY_BACKFILL_SESSION_CAP:-1000000}"
PER_SOURCE_CAP="${TECHNOLOGY_BACKFILL_PER_SOURCE_CAP:-1000000}"

# launchd starts with a bare PATH; add tool locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
mkdir -p "$RUNLOG_DIR" "$STATE_DIR"

log()    { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"Technology Backfill\"" 2>/dev/null || true; }

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
# collector (_state/$STATE_FILE "blocked"); the run is never globally halted.

DONE_BEFORE="$(python3 -c "import json;print(len(json.load(open('$STATE_DIR/$STATE_FILE')).get('done',[])))" 2>/dev/null || echo 0)"
RECORDS_BEFORE="$(find "$HISTORY_ROOT" -name '*.json' -not -path '*_state*' -not -path '*_runlog*' 2>/dev/null | wc -l | tr -d ' ')"

log "=== Technology backfill starting | sources complete=${DONE_BEFORE}/12 | records=${RECORDS_BEFORE} | UNCAPPED (session=${SESSION_CAP} per-source=${PER_SOURCE_CAP}) ==="
log "repo:    $REPO_DIR"
log "history: $HISTORY_ROOT (OUTSIDE git)"

# Belt-and-suspenders: no git commands below this line.
cd "$REPO_DIR" || { log "FATAL: cannot cd $REPO_DIR"; exit 1; }

TMPOUT="$(mktemp)"
python3 scripts/backfill_technology_history.py --core --start 2025-01-01 \
        --session-cap "$SESSION_CAP" --per-source-cap "$PER_SOURCE_CAP" \
        --state-file "$STATE_FILE" 2>&1 \
    | tee "$TMPOUT" | tee -a "$LOG"
EXIT_CODE="${PIPESTATUS[0]}"

DONE_AFTER="$(python3 -c "import json;print(len(json.load(open('$STATE_DIR/$STATE_FILE')).get('done',[])))" 2>/dev/null || echo 0)"
RECORDS_AFTER="$(find "$HISTORY_ROOT" -name '*.json' -not -path '*_state*' -not -path '*_runlog*' 2>/dev/null | wc -l | tr -d ' ')"

# Per-site quarantined sources, surfaced from collector state (NOT a global halt).
BLOCKED="$(python3 -c "import json;b=json.load(open('$STATE_DIR/$STATE_FILE')).get('blocked',{});print(', '.join(sorted(b)) if b else 'none')" 2>/dev/null || echo '?')"

if [ "$EXIT_CODE" -eq 0 ]; then
    log "=== DONE | exit 0 | sources complete ${DONE_BEFORE}→${DONE_AFTER}/12 | records ${RECORDS_BEFORE}→${RECORDS_AFTER} ==="
    log "  per-site quarantined (24h cooldown, run continued past them): ${BLOCKED}"
    if [ "$BLOCKED" != "none" ] && [ "$BLOCKED" != "?" ]; then
        notify "Technology backfill done — quarantined: ${BLOCKED}"
    fi
else
    log "UNEXPECTED EXIT $EXIT_CODE — see session log above (quarantined: ${BLOCKED})"
    notify "Technology backfill unexpected exit $EXIT_CODE"
fi
