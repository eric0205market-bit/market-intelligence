#!/bin/bash
# Manual, on-demand YouTube insight extraction — run on YOUR Claude subscription.
#
#   bash scripts/extract_youtube_local.sh
#
# What it does:
#   1. finds NEW raw transcripts (>= minimum_duration_minutes, no processed file yet,
#      not a re-upload of an already-processed episode);
#   2. extracts each with HEADLESS Claude Code (`claude -p`) on your subscription —
#      opus-tier channels -> Opus, sonnet-tier -> Sonnet (per config "tier");
#   3. maps quotes to caption cue times from the raw record's stored
#      transcript_segments (no re-fetch) and sets quote_verified;
#   4. renders reports/youtube_<date>.html, rebuilds the dashboard, commits & pushes.
#
# HARD RULES:
#   * NEVER uses the paid API. ANTHROPIC_API_KEY/AUTH_TOKEN are unset for the run.
#   * If a subscription usage limit is hit mid-run, it STOPS CLEANLY and reports what
#     finished; the next run catches up automatically via the new/dedup logic.
#   * If the headless `claude` CLI is not installed, it does NOT touch the API — it
#     prints how to trigger extraction via the interactive agent and exits.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:$PATH"
cd "$REPO" || { echo "FATAL: cannot cd $REPO"; exit 1; }

# Force subscription auth — never the paid API.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
PY=python3
DATE="$(date -u '+%Y-%m-%d')"

echo "=== YouTube extraction (manual / subscription) — $REPO ==="
git fetch origin main --quiet 2>/dev/null && git checkout main --quiet 2>/dev/null && git pull --rebase origin main --quiet 2>/dev/null || true

# --- worklist (bash 3.2-safe: no mapfile) -----------------------------------
WORK=()
while IFS= read -r line; do
  [ -n "$line" ] && WORK+=("$line")
done < <("$PY" scripts/youtube_extract.py worklist)
if [ "${#WORK[@]}" -eq 0 ]; then
  echo "No new eligible episodes to extract. (Nothing to do.)"
  exit 0
fi
echo "Found ${#WORK[@]} new episode(s) to extract:"
IDS=()
for line in "${WORK[@]}"; do
  id=$(printf '%s' "$line" | cut -f1); tier=$(printf '%s' "$line" | cut -f2)
  mins=$(printf '%s' "$line" | cut -f3); seg=$(printf '%s' "$line" | cut -f4)
  ch=$(printf '%s' "$line" | cut -f5); title=$(printf '%s' "$line" | cut -f6)
  model=$([ "$tier" = "opus" ] && echo "Opus" || echo "Sonnet")
  echo "  • $id  [$tier→$model]  ${mins}m  ${seg}  $ch — $title"
  IDS+=("$id")
done

# --- require the headless CLI; otherwise fall back to the interactive agent ---
if ! command -v claude >/dev/null 2>&1; then
  cat <<EOF

Headless 'claude' CLI is not installed on this machine, so this script cannot
run the extraction itself (and it will NOT use the paid API).

➤ Trigger it the other way instead: open Claude Code and say:

      run youtube extraction

The interactive agent will extract the episode(s) above on your subscription
(Opus/Sonnet per tier), set timestamps + quote_verified, render the digest,
rebuild the dashboard, and commit to main — same result, same dedup.
EOF
  exit 3
fi

# --- extract each via claude -p on the subscription -------------------------
extracted=(); n_opus=0; n_sonnet=0; limit_hit=0
for id in "${IDS[@]}"; do
  tier=$("$PY" scripts/youtube_extract.py tier "$id")
  model=$([ "$tier" = "opus" ] && echo "opus" || echo "sonnet")
  echo "--- extracting $id  (model: $model) ---"
  ptmp="$(mktemp)"; otmp="$(mktemp)"
  "$PY" scripts/youtube_extract.py prompt "$id" > "$ptmp"
  # Subscription run, single turn, JSON envelope. Never the API.
  if ! claude -p --model "$model" --output-format json --max-turns 1 < "$ptmp" > "$otmp" 2>"$otmp.err"; then
    if grep -qiE "usage limit|rate limit|quota|exceeded|limit reached|too many requests" "$otmp" "$otmp.err"; then
      echo "  ⚠ subscription usage limit reached — stopping cleanly. The next run resumes here."
      limit_hit=1; rm -f "$ptmp" "$otmp" "$otmp.err"; break
    fi
    echo "  ✗ $id: claude -p failed (non-limit). Skipping; next run retries."
    rm -f "$ptmp" "$otmp" "$otmp.err"; continue
  fi
  # Extract the model result text from the JSON envelope, strip any code fences.
  result="$("$PY" - "$otmp" <<'PYJSON'
import json,sys,re
raw=open(sys.argv[1]).read()
try:
    env=json.loads(raw); txt=env.get("result", env) if isinstance(env,dict) else raw
    txt=txt if isinstance(txt,str) else json.dumps(txt)
except Exception:
    txt=raw
txt=re.sub(r"^```[a-zA-Z]*\n|\n```$","",txt.strip())
sys.stdout.write(txt)
PYJSON
)"
  if echo "$result" | grep -qiE "usage limit|limit reached|quota exceeded"; then
    echo "  ⚠ subscription usage limit reached — stopping cleanly."; limit_hit=1
    rm -f "$ptmp" "$otmp" "$otmp.err"; break
  fi
  # Validate JSON before writing the record.
  if echo "$result" | "$PY" -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
    echo "$result" > "processed/youtube/$id.json"
    extracted+=("$id")
    [ "$model" = "opus" ] && n_opus=$((n_opus+1)) || n_sonnet=$((n_sonnet+1))
    echo "  ✓ wrote processed/youtube/$id.json"
  else
    echo "  ✗ $id: model did not return valid JSON. Skipping; next run retries."
  fi
  rm -f "$ptmp" "$otmp" "$otmp.err"
done

if [ "${#extracted[@]}" -eq 0 ]; then
  echo "No episodes were successfully extracted this run."
  [ "$limit_hit" -eq 1 ] && exit 0 || exit 1
fi

# --- timestamps + quote_verified, then render + dashboard -------------------
echo "=== post-processing ${#extracted[@]} record(s) (timestamps + quote_verified) ==="
"$PY" scripts/youtube_extract.py postprocess "${extracted[@]}"
echo "=== rendering digest + rebuilding dashboard ==="
"$PY" scripts/youtube_extract.py publish --date "$DATE"

# --- commit & push ----------------------------------------------------------
git config user.name "github-actions" >/dev/null 2>&1
git config user.email "actions@github.com" >/dev/null 2>&1
git add processed/youtube reports/youtube_*.html index.html
if git diff --cached --quiet; then
  echo "Nothing to commit."
else
  git commit -q -m "youtube insights: +${#extracted[@]} episode(s) ($DATE, opus=$n_opus sonnet=$n_sonnet)"
  for i in 1 2 3; do git push origin main --quiet && break; git pull --rebase origin main --quiet || true; done
  echo "Committed & pushed."
fi

# --- summary ----------------------------------------------------------------
ts_cov=$("$PY" - "${extracted[@]}" <<'PYSUM'
import json,sys
from pathlib import Path
tot=ts=0
for vid in sys.argv[1:]:
    d=json.load(open(Path("processed/youtube")/f"{vid}.json"))
    for t in d.get("themes",[]):
        for i in t.get("insights",[]):
            if i.get("quote"): tot+=1
            if i.get("timestamp"): ts+=1
print(f"{ts}/{tot} quotes timestamped ({(100*ts//tot) if tot else 0}%)")
PYSUM
)
echo ""
echo "=== DONE ==="
echo "Episodes extracted: ${#extracted[@]}  (Opus: $n_opus, Sonnet: $n_sonnet)"
echo "Timestamp coverage: $ts_cov"
[ "$limit_hit" -eq 1 ] && echo "NOTE: stopped early on a usage limit — run again when quota refreshes to continue."
echo "Dashboard: index.html → KNOWLEDGE → YouTube / Podcasts"
