# ROUTINE — TECHNOLOGY EXTRACTION (KNOWLEDGE track)
# Model: Opus (subscription phase — all articles on Opus). NEVER fall back to the paid API.
# Input: raw/technology/<source_slug>/<record_id>.json  (articles collected by scripts/collect_technology.py)
# Output: processed/technology/<record_id>.json  + reports/technology_<date>.html, published via scripts/publish_technology.py
# Card contract: docs/KNOWLEDGE_CARD_SCHEMA.md (v1) — the SHARED envelope+theme+insight atom for the whole KNOWLEDGE track.
# Cadence: on demand, after the daily collection, run on subscription when quota is fresh. Runs LOCALLY in the dedicated clone.

This routine is the Technology analog of routine_concepts.md, for TEXT articles.
The insight atom is IDENTICAL across the KNOWLEDGE track (YouTube / Concepts /
Technology / Society) so everything lands in Supabase as one clean import — see
docs/KNOWLEDGE_CARD_SCHEMA.md.

**TRIAGE HAPPENS AT COLLECTION — NOT HERE.** Technology is Flow-heavy (67 sources
= 17 Deep + 50 Flow). The deterministic triage that decides which Flow articles
are worth extracting lives in the COLLECTOR (`scripts/collect_technology.py`):
Deep sources extract-all; Flow sources are gated by watchlist + recency + a
per-source cap BEFORE anything is written to `raw/technology/`. So by the time
you see a worklisted article, it has already passed triage. Do NOT add a triage
step here — extract every worklisted article, exactly like Concepts. (One source
per subagent, unchanged.)

## STEP 0 — WORKLIST GATE (MANDATORY, RUN FIRST)
Before anything else, build the worklist — every raw article that has NO
`processed/technology/<record_id>.json` yet (record_id-dedup against processed):

    python3 scripts/publish_technology.py worklist

If it prints "No new Technology articles to extract.": STOP. Generate nothing,
write no JSON/HTML, commit/push nothing. Output that one line and end the run.
Continue below ONLY if the worklist has >= 1 article. (This is the Technology
analog of the freshness gate the cloud routines run first.)

## STEP 1 — FETCH INPUT
For each worklisted article, read its raw record directly from the LOCAL working
copy (no git clone — this routine runs in the already-checked-out dedicated clone):

    raw/technology/<source_slug>/<record_id>.json

Each raw record carries: `record_id`, `source_slug`, `source_name`, `source_url`,
`category`, `type`, `paywalled`, `title`, `published_date`, `language`, `author`,
`word_count`, the full plain-text `text`, `image_urls`, `collected_at`. Read the
WHOLE `text`. If a record has no `text` (or it is empty), skip it.

## STEP 2 — PROCESS (per docs/KNOWLEDGE_CARD_SCHEMA.md v1)

You are an investor-grade analyst mining a long-form research article for EDGE.
Read the WHOLE article, then emit one JSON object in the common KNOWLEDGE card
shape. Be faithful: every claim must be supported by the article. Do not invent
facts, tickers, or quotes.

**ONE ARTICLE ONLY — ONE SOURCE PER SUBAGENT.** Work EXCLUSIVELY from the single
raw record you are given. Every claim, entity, and quote must come from THIS
article's `text` — never from another article, a sibling subagent running in
parallel, the title alone, or your own prior knowledge. If the article's content
seems to contradict its title, extract from the actual TEXT (note the discrepancy
in the gist) — never substitute a different article's material. A card whose
`top_entities` are <~40% present in its own raw `text` is QUARANTINED by the
publish guard (STEP 3) and not published.

### MINDSET / HOW TO PROCESS
Read like a sharp investor hunting for non-obvious, actionable signal — not a
summarizer. Capture:
- stated theses AND *implied* views (what the author clearly believes but didn't headline)
- predictions, frameworks/mental models, hard data points, causal claims
- contrarian / surprising / against-consensus takes
- second-order implications (what it means downstream for an asset, sector, or trade)
- non-obvious connections, and recurring themes across the piece
Prefer SPECIFICS (numbers, names, mechanisms, levels) over vague gist. Skip
boilerplate, disclaimers, marketing, and author-bio filler.

### VOLUME — scale to length & density, NO fixed count
- Long, dense report (deep essay / working paper): be EXHAUSTIVE — 15–40 insights
  across several themes is normal. Do not stop at the headlines.
- Medium article: ~8–18 insights.
- Thin / promotional / repetitive piece: be honest and light (3–10). Never pad.
Group insights into 3–8 themes with short, specific theme names.

### OUTPUT FORMAT (output EXACTLY this shape — the common KNOWLEDGE card)
```json
{
  "record_id": "<copy from raw>",
  "source_type": "technology",
  "source_name": "<copy from raw>",
  "source_url": "<copy from raw>",
  "title": "<copy from raw>",
  "published_date": "<copy from raw, YYYY-MM-DD>",
  "language": "<copy from raw, e.g. 'en'>",
  "processed_at": "<ISO8601 UTC now>",
  "processor": "<set by caller, e.g. claude-code-sub-opus>",
  "tags": ["<0+ from the controlled vocabulary, see below>"],
  "gist": "1–3 sentence essence, specific not generic",
  "themes": [
    {"theme": "<short specific theme name>",
     "insights": [
       {"claim": "<standalone, self-contained sentence an investor could act on or file>",
        "speaker": "<the author's name (from raw author); if none, the source_name; never invent a name>",
        "type": "thesis|prediction|framework|data_point|causal|contrarian|anecdote",
        "entities": ["companies/tickers/people/sectors/technologies in this insight"],
        "conviction": "high|medium|low|exploratory",
        "so_what": "<one line: why an investor should care / how to trade or watch it>",
        "quote": "<short VERBATIM quote from the text (<=240 chars) ONLY where the wording carries signal; else null>",
        "locator": "<paragraph/section anchor where this sits in the article (e.g. a short heading or the opening words of the paragraph); else null>",
        "quote_verified": false}
     ]}
  ],
  "insight_total": <int = total insights across all themes>,
  "top_entities": ["<the most important 5–12 entities across the whole article>"],
  "source_meta": {"author": "<copy from raw author>", "word_count": <copy from raw>, "paywalled": <copy bool from raw>}
}
```

### FIELD RULES
- claim: must stand alone WITHOUT the title for context. Bad: "He's bullish."
  Good: "Nvidia is gating HBM allocation to lock hyperscalers into multi-year GPU commitments."
  (The claim is what the embedding is computed on — self-containment is a DB
  requirement, not stylistic. See schema §6.)
- speaker: the article's author (raw `author`). If the raw `author` is empty, use
  the `source_name` (e.g. "SemiAnalysis", "Ars Technica"). Do NOT guess a person's name.
- type: pick the dominant one. data_point = a concrete number/fact; framework =
  a reusable mental model; causal = an X-causes-Y claim (ontology hook); contrarian
  = explicitly against consensus.
- conviction: the AUTHOR's apparent conviction, not yours.
- quote: copy verbatim from the `text`. Use null generously — only quote when the
  phrasing itself is the signal.
- locator: a short paragraph/section anchor so a reader can find it in the article
  (a heading, or the first ~6 words of the paragraph). NO timestamps (text source).
- quote_verified: ALWAYS leave false. (STEP 3 postprocess sets it deterministically
  by checking each quote against the raw `text` — do NOT set it yourself.)

### TAGS — controlled vocabulary (envelope `tags`), EXACTLY these 8
`Macro` · `Energy` · `Tech` · `Crypto` · `Geopolitics` · `Positioning` · `AI` · `Society`
A card may carry several. Tags are light human-browsing aids, NOT a filter — all
content is published regardless.

### METADATA
Copy record_id, source_name, source_url, title, published_date, language verbatim
from the raw record. source_meta.author / word_count / paywalled copy from raw.
Stamp processed_at with the current UTC time. Set source_type="technology".

### DELIVERY
Write the JSON object to `processed/technology/<record_id>.json` (valid, parseable,
UTF-8). One article → one file.

### VERIFICATION CHECKLIST (do AFTER drafting each article, before writing its JSON)
- [ ] Does every `claim` stand alone WITHOUT the title for context?
- [ ] No fabricated facts, tickers, or quotes — every claim supported by the `text`?
- [ ] Do the `top_entities` (and the gist's subject) actually appear in THIS article's
      `text`? If the card is about a different topic than the text you read, you used
      the wrong source — re-read the correct raw record and redo it. (The publish
      guard quarantines any card whose entities are <~40% present in its text.)
- [ ] Every `quote` is verbatim from the `text` or `null` (no paraphrase as a quote)?
- [ ] Insight count scaled to the article's length & density, NOT padded?
- [ ] Theme names short and specific (not generic buckets)?
- [ ] `speaker` is the author (or source_name) — no invented person names?
- [ ] Every `quote_verified` left `false` (STEP 3 sets it)?
If any check fails, fix it before writing the card.

## STEP 3 — PUBLISH (final step — after every card's JSON is written and its checklist passes)
You are at the repo root (the local dedicated clone). The deterministic publish
sets `quote_verified` on each insight, runs the **entity-presence guard**, renders
the NEW-ONLY `reports/technology_<date>.html` (only this run's cards), rebuilds the
dashboard (KNOWLEDGE → Technology), and then you commit & push to `main`. Run exactly
this from the repo root, with `IDS` set to the comma-separated record_ids you wrote
this run:

**ENTITY-PRESENCE GUARD (automatic, every run).** Before rendering, publish checks
every candidate card: what fraction of its `top_entities` actually appear in its raw
article `text`. Any card below ~40% is treated as a topic mismatch (hallucinated or
cross-contaminated extraction), is **QUARANTINED — excluded from the report, NOT
auto-deleted** — logged to `processed/technology/_quarantine.json`, and printed in the
publish output. If publish prints a quarantine warning: STOP, report the quarantined
record_id(s) to the owner, re-extract them from their correct raw article, and
re-publish. Never hand-edit a card to pass the guard.

```
IDS=<id1,id2,...>                       # the record_ids you just wrote
python3 scripts/publish_technology.py postprocess ${IDS//,/ }
python3 scripts/publish_technology.py publish --date "$(date -u +%F)" --ids "$IDS"
git add processed/technology reports/technology_*.html index.html
git commit -m "technology insights: +N article(s) ($(date -u +%F))"
for i in 1 2 3; do git push origin main && break; git pull --rebase origin main; done
```

Do NOT render, commit, or push by hand beyond these commands — `publish_technology.py
publish` does the rendering and dashboard rebuild deterministically.

### STOP ON LIMIT
If a subscription usage limit is hit mid-run, STOP CLEANLY: publish whatever cards
were already fully written (run STEP 3 for those ids), report what finished, and
end. The next run resumes automatically — the STEP 0 worklist re-lists only the
still-unprocessed articles via the record_id dedup. NEVER fall back to the paid API.
