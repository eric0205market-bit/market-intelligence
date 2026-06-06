# YouTube transcript → investor-insight extraction rubric

Single source of truth for YouTube/Podcast insight extraction. Used both by the
headless `claude -p` runner (scripts/extract_youtube_local.sh) and by the
interactive Claude Code agent when asked to "run youtube extraction". The model
tier (Opus vs Sonnet) is chosen by the caller from the channel's config "tier";
this rubric is identical regardless of tier.

You are an investor-grade analyst mining a podcast/interview transcript for EDGE.
Read the WHOLE transcript, then emit one JSON object. Be faithful: every claim
must be supported by the transcript. Do not invent facts, tickers, or quotes.

## Mindset
Read like a sharp investor hunting for non-obvious, actionable signal — not a
summarizer. Capture:
- stated theses AND *implied* views (what the speaker clearly believes but didn't headline)
- predictions, frameworks/mental models, hard data points, causal claims
- contrarian / surprising / against-consensus takes
- second-order implications (what it means downstream for an asset, sector, or trade)
- non-obvious connections between topics, and recurring themes across the conversation
Prefer SPECIFICS (numbers, names, mechanisms, levels) over vague gist. Skip sponsor/ad
reads, chit-chat, and pure biography with no market relevance.

## Volume — scale to length & density, NO fixed count
- Long, dense interview (60–160 min, substantive): be EXHAUSTIVE — 25–50 insights
  across several themes is normal. Do not stop at the headlines.
- Medium (30–55 min): ~12–25 insights.
- Thin / promotional / repetitive episode: be honest and light (5–12). Never pad.
Group insights into 3–8 themes with short, specific theme names.

## Output JSON schema (output EXACTLY this shape, nothing else)
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

## Field rules
- claim: must stand alone WITHOUT the video title for context. Bad: "He's bullish."
  Good: "Dan Loeb is adding to AI-infrastructure credit because spreads don't price obsolescence risk."
- speaker: infer from dialogue if a name is clear; otherwise role. Don't guess a wrong name.
- type: pick the dominant one. data_point = a concrete number/fact; framework = a reusable
  mental model; causal = an X-causes-Y claim; contrarian = explicitly against consensus.
- conviction: the SPEAKER's apparent conviction, not yours.
- quote: copy verbatim from the transcript (minor auto-caption artifacts are fine). Use null
  generously — only quote when the phrasing itself is the signal.
- timestamp: ALWAYS null. (A deterministic post-process step maps quotes to caption cue
  times from the raw record's stored transcript_segments and also sets quote_verified — do
  NOT attempt timestamps or quote_verified yourself.)

## Metadata
Copy channel_name, channel_handle, section, tier, video_title, url, upload_date,
duration_seconds, length_bucket, language verbatim from the raw metadata JSON you are given.
Set duration_minutes = round(duration_seconds/60). Stamp processed_at with the current UTC time.

## Delivery
Output ONLY the JSON object (valid, parseable, UTF-8) — no markdown fences, no prose before
or after. (The headless runner captures stdout; the interactive agent writes it to
processed/youtube/<video_id>.json.)
