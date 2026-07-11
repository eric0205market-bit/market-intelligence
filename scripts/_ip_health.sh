#!/bin/bash
# _ip_health.sh — shared soft-throttle monitor for the YouTube collectors.
# Sourced by run_youtube_local.sh (daily) and run_youtube_backfill_local.sh
# (backfill). One residential IP serves both; this warns BEFORE a hard 429.
#
# The sourcing wrapper must already define: log(), notify(), and HISTORY_ROOT.
# It NEVER stops a run — the hard-429 / exit-10 path stays in the collectors.
# Thresholds are calibrated to the clean-record baseline (empty/partial 2.5%,
# non-benign metadata-unavailable ~0): 0 false-positives on all history to date.

throttle_watch() {
    local out="$1" label="$2" succ empty partial attempts unavail benign nonbenign rate prev counts processed pf
    counts=$(grep -hoE 'transcript OK \([a-z]+, [0-9]+ chars|OK (auto|manual) [0-9]+ch' "$out" 2>/dev/null | grep -oE '[0-9]+')
    succ=$(printf '%s\n' "$counts" | grep -c .)
    partial=$(printf '%s\n' "$counts" | awk 'NF && $1<5000' | grep -c .)
    empty=$(grep -c 'NO transcript' "$out" 2>/dev/null); empty=${empty:-0}
    attempts=$(( succ + empty ))

    # --- blind-parser guard: a monitor that can't see must SAY so, not read 0% ---
    # If we matched 0 attempts but the run summary shows videos were processed,
    # the per-video log vocabulary likely changed and the monitor is blind.
    if [ "$attempts" -eq 0 ]; then
        processed=$(grep -hoE 'Fetched [0-9]+ video|[0-9]+/[0-9]+ transcripts OK' "$out" 2>/dev/null | grep -oE '[0-9]+' | sort -rn | head -1)
        processed=${processed:-0}
        if [ "$processed" -gt 0 ]; then
            log "  [ip-health] WARN — parser matched 0 transcript attempts but run summary processed ${processed}; per-video log format may have changed — monitor is BLIND"
            notify "IP-health BLIND (${label}): 0 parsed attempts but summary shows ${processed} — log vocabulary may have changed"
        else
            log "  [ip-health] ${label}: 0 videos processed this run (nothing to assess)"
        fi
        return
    fi

    unavail=$(grep -c 'metadata unavailable' "$out" 2>/dev/null); unavail=${unavail:-0}
    benign=$(grep -icE 'Premiere|members-only|Private video|This video is unavailable|age-restrict|confirm your age|HTTP Error 404|has been removed|been deleted' "$out" 2>/dev/null); benign=${benign:-0}
    nonbenign=$(( unavail - benign )); [ "$nonbenign" -lt 0 ] && nonbenign=0
    rate=$(( (empty + partial) * 100 / attempts ))
    log "  [ip-health] ${label}: attempts=${attempts} empty=${empty} partial=${partial} empty/partial=${rate}% nonbenign-unavail=${nonbenign} (baseline 2.5% / 0)"

    # Trend memory for the 2-consecutive-run rule.
    pf="${HISTORY_ROOT}/_state/ip_health_${label}.last"
    prev=$(cat "$pf" 2>/dev/null); prev=${prev:-0}; echo "$rate" > "$pf" 2>/dev/null || true
    if [ "$rate" -ge 30 ] || [ "$nonbenign" -ge 3 ] || { [ "$rate" -ge 15 ] && [ "$prev" -ge 15 ]; }; then
        log "  [ip-health] WARN — soft-throttle signal (empty/partial ${rate}% [prev ${prev}%], nonbenign ${nonbenign})"
        notify "IP-health WARN (${label}): empty/partial ${rate}%, nonbenign-unavail ${nonbenign} — possible soft throttle"
    fi
}
