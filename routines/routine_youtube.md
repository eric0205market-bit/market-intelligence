# ROUTINE — YOUTUBE / PODCASTS EXTRACTION
# Model: Opus (subscription phase — all episodes on Opus; the config "tier" field is for the future API phase only)
# Input: raw/youtube/<channel>/<id>.json  (new transcripts collected by scripts/collect_youtube.py, launchd 12:00)
# Output: processed/youtube/<id>.json  + reports/youtube_<date>.html, published via scripts/youtube_extract.py publish (postprocess + render + dashboard + commit/push)
# Cadence: on demand, after the 12:00 collection, run on subscription when quota is fresh. Runs LOCALLY in the dedicated clone — no git clone step.

## STEP 0 — WORKLIST GATE (MANDATORY, RUN FIRST)
Before anything else, build the worklist — every raw transcript that has NO `processed/youtube/<id>.json` yet (id-dedup + content-dedup of re-uploads) and is >= 25 minutes:

    python3 scripts/youtube_extract.py worklist

If it prints nothing: STOP. Generate nothing, write no JSON/HTML, commit/push nothing. Output a one-line note ("No new YouTube episodes to extract.") and end the run. Continue to the steps below ONLY if the worklist has >= 1 episode. (This is the YouTube analog of the freshness gate the cloud routines run first.)

## STEP 1: FETCH INPUT
For each worklisted episode, read its raw record directly from the LOCAL working copy (no git clone — unlike the cloud routines, this routine runs in the already-checked-out dedicated clone):

    raw/youtube/<channel_slug>/<video_id>.json

Each raw record carries the metadata (channel_name, channel_handle, section, tier, video_title, url, upload_date, duration_seconds, length_bucket, language), the full plain-text `transcript`, and — for episodes collected after the timed-caption upgrade — `transcript_segments` (timed caption cues used later by the publish step for timestamps). Read the WHOLE transcript. If a record has no transcript, skip it.

## STEP 2: PROCESS

You are an investor-grade analyst mining a podcast/interview transcript for EDGE. Read the WHOLE transcript, then emit one JSON object. Be faithful: every claim must be supported by the transcript. Do not invent facts, tickers, or quotes.

### INPUT
One raw record per episode (STEP 1): metadata + the full `transcript` (+ `transcript_segments` when present). One episode → one JSON object written to `processed/youtube/<video_id>.json`.

### MINDSET / HOW TO PROCESS
Read like a sharp investor hunting for non-obvious, actionable signal — not a summarizer. Capture:
- stated theses AND *implied* views (what the speaker clearly believes but didn't headline)
- predictions, frameworks/mental models, hard data points, causal claims
- contrarian / surprising / against-consensus takes
- second-order implications (what it means downstream for an asset, sector, or trade)
- non-obvious connections between topics, and recurring themes across the conversation
Prefer SPECIFICS (numbers, names, mechanisms, levels) over vague gist. Skip sponsor/ad reads, chit-chat, and pure biography with no market relevance.

### VOLUME — scale to length & density, NO fixed count
- Long, dense interview (60–160 min, substantive): be EXHAUSTIVE — 25–50 insights across several themes is normal. Do not stop at the headlines.
- Medium (30–55 min): ~12–25 insights.
- Thin / promotional / repetitive episode: be honest and light (5–12). Never pad.
Group insights into 3–8 themes with short, specific theme names.

### OUTPUT FORMAT (output EXACTLY this shape, nothing else)
```json
{
  "video_id","url","channel_name","channel_handle","section","tier","video_title","upload_date",
  "duration_seconds","duration_minutes","length_bucket","language",
  "processed_at": "<ISO8601 UTC>", "processor": "<set by caller, e.g. claude-code-sub-opus>",
  "timestamps_available": false,
  "gist": "1–3 sentence essence, specific not generic",
  "themes": [
    {"theme":"<short specific theme name>",
     "insights":[
       {"claim":"<standalone, self-contained sentence an investor could act on or file>",
        "speaker":"<name if identifiable from context (e.g. 'Raoul Pal','host','guest, fund CIO')>",
        "type":"thesis|prediction|framework|data_point|causal|contrarian|anecdote",
        "entities":["companies/tickers/people/sectors/technologies mentioned"],
        "conviction":"high|medium|low|exploratory",
        "so_what":"<one line: why an investor should care / how it could be traded or watched>",
        "quote":"<short VERBATIM quote (<=240 chars) ONLY where the exact wording carries signal; else null>",
        "timestamp": null}
     ]}
  ],
  "insight_total": <int = total insights across all themes>,
  "top_entities": ["<the most important 5–12 entities across the episode>"]
}
```

### FIELD RULES
- claim: must stand alone WITHOUT the video title for context. Bad: "He's bullish." Good: "Dan Loeb is adding to AI-infrastructure credit because spreads don't price obsolescence risk."
- speaker: infer from dialogue if a name is clear; otherwise role. Don't guess a wrong name.
- type: pick the dominant one. data_point = a concrete number/fact; framework = a reusable mental model; causal = an X-causes-Y claim; contrarian = explicitly against consensus.
- conviction: the SPEAKER's apparent conviction, not yours.
- quote: copy verbatim from the transcript (minor auto-caption artifacts are fine). Use null generously — only quote when the phrasing itself is the signal.
- timestamp: ALWAYS null. (A deterministic post-process step maps quotes to caption cue times from the raw record's stored transcript_segments and also sets quote_verified — do NOT attempt timestamps or quote_verified yourself.)

### METADATA
Copy channel_name, channel_handle, section, tier, video_title, url, upload_date, duration_seconds, length_bucket, language verbatim from the raw metadata JSON you are given. Set duration_minutes = round(duration_seconds/60). Stamp processed_at with the current UTC time.

### DELIVERY
Output ONLY the JSON object (valid, parseable, UTF-8) — no markdown fences, no prose before or after. (The headless runner captures stdout; the interactive agent writes it to `processed/youtube/<video_id>.json`.)

### VERIFICATION CHECKLIST (do AFTER drafting each episode, before writing its JSON)
- [ ] Does every `claim` stand alone WITHOUT the video title for context? If any reads as "He's bullish", rewrite it with the subject + specifics.
- [ ] No fabricated facts, tickers, or quotes — every claim is supported by the transcript?
- [ ] Every `quote` is either verbatim from the transcript or `null` (no paraphrase dressed as a quote)?
- [ ] Is the insight count scaled to the episode's length & density (exhaustive on long/dense, light on thin) and NOT padded?
- [ ] Are theme names short and specific (not generic buckets)?
- [ ] Is every `timestamp` left `null` and `timestamps_available` left `false` (the publish step sets timestamps + quote_verified)?

If any check fails, fix it before writing the episode's JSON.

## STEP 3 — PUBLISH (final step — after every episode's JSON is written and its checklist passes)
The repository is already cloned and you are at its root (the local dedicated clone). The deterministic publish maps each quote to a caption cue time from the raw record's stored `transcript_segments`, sets `quote_verified`, renders the NEW-ONLY `reports/youtube_<date>.html` (only this run's episodes, like the other routines), rebuilds the dashboard (KNOWLEDGE → YouTube / Podcasts), and commits & pushes to `main`. Run exactly this from the repo root, with `IDS` set to the comma-separated video_ids you processed this run:

```
IDS=<id1,id2,...>                       # the episodes you just wrote
python3 scripts/youtube_extract.py postprocess ${IDS//,/ }
python3 scripts/youtube_extract.py publish --date "$(date -u +%F)" --ids "$IDS"
git add processed/youtube reports/youtube_*.html index.html
git commit -m "youtube insights: +N episode(s) ($(date -u +%F))"
for i in 1 2 3; do git push origin main && break; git pull --rebase origin main; done
```

Do NOT render, commit, or push by hand beyond these commands — `youtube_extract.py publish` does the rendering and dashboard rebuild deterministically. (The whole worklist → extract → publish pipeline is also wrapped in `bash scripts/extract_youtube_local.sh` for the headless `claude -p` path; this routine is the manual/interactive path the script delegates to when no headless CLI is present.)

### STOP ON LIMIT
If a subscription usage limit is hit mid-run, STOP CLEANLY: publish whatever episodes were already fully drafted (run STEP 3 for those ids), report what finished, and end. The next run resumes automatically — the STEP 0 worklist re-lists only the still-unprocessed episodes via the dedup. NEVER fall back to the paid API.
