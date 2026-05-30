# CLOUD ROUTINE — TWITTER BANK RESEARCH DIGEST
# Model: Sonnet 4.6
# Trigger: 2x/week (fixed cadence)
# Catalog, not analysis — group bank/strategist research, image-first.

## STEP 0 — FRESHNESS GATE (FIRST, MANDATORY)

Clone the repository:

```bash
git clone https://github.com/eric0205market-bit/market-intelligence.git
cd market-intelligence
python3 scripts/check_freshness.py data/twitter/latest/tweets_bank_research.json --max-age-hours 24
```

If the gate prints `FRESHNESS GATE FAILED` or exits non-zero, **STOP**: do not read the data file, do not render, do not push. Output a single line: "ABORT — bank-research data stale (>24h); publishing nothing." Continue only on `FRESHNESS GATE PASSED.`

## STEP 1 — SELECT RESEARCH ITEMS (key filter)

Read `data/twitter/latest/tweets_bank_research.json` ENTIRELY. Consider only tweets whose `created_at` is within the **last 4 days** of the file's `collected_at`. From the considered set, **KEEP** an item only if:

  (a) its `banks` tag is non-empty (a canonical bank or strategist matched) — research; keep regardless of author; OR
  (b) its `banks` tag is empty BUT `author_username == "neilksethi"` (case-insensitive) — Neil's image tweets are almost all research; keep.

**DROP** the rest. Rationale: empty-banks tweets from high-volume relayers like MikeZaccardi are price-chart / meme noise without a research signal.

## STEP 2 — CONTENT DEDUP

Repost accounts (especially `dailychartbook`) frequently mirror an original tweet under a new id with identical or near-identical chart and text. Collapse near-duplicates:

- Same `images` URL set → duplicate.
- Near-identical normalized text (case-folded, whitespace-collapsed, stripped of leading "@user " or trailing "https://t.co/…" URLs) → duplicate.

For each duplicate cluster: **PREFER** the original poster over the relayer, and within ties, prefer the version with the most narrative text (keep Neil's commentary). The surviving item carries a `relayers: [usernames]` array listing every account that also carried it (excluding the kept author).

## STEP 3 — BUILD DIGEST (catalog, not analysis)

Group items **BY BANK**. Order banks by KEPT-item count desc (ties: alphabetical). A single item belongs to every canonical bank in its `banks` tag (it appears once per bank in the output — counted once in totals).

For each bank section:
- One-line **theme subheading** synthesizing the tweets under it (e.g., "Hartnett FMS — cash low, risk-on tilt"). Keep it descriptive, not editorial.
- One entry per item:
  - chart image(s) inline (every image rendered — images are the content)
  - relayer text **verbatim** (do not paraphrase; Neil's commentary is high-signal)
  - author handle + tweet link
  - date (`created_at`)
  - if `relayers` non-empty: small footer "also carried by: @a, @b"

Top of the report — **SUMMARY** (4–6 lines): recurring themes across banks + per-bank counts ("BofA 6, Goldman 4, JPM 3, …").

### OUTPUT JSON (sidecar, also fed to the template)

```json
{
  "report_type": "TWITTER BANK RESEARCH",
  "collected_at": "<from input>",
  "window_days": 4,
  "input_stats": {
    "total_tweets": N,
    "considered": N,
    "kept": N,
    "dropped": N,
    "deduped": N
  },
  "summary": "<4-6 lines>",
  "by_bank_counts": {"BofA": N, "Goldman": N, "...": N},
  "banks": [
    {
      "bank": "BofA",
      "theme": "<one-line subheading>",
      "items": [
        {
          "author": "neilksethi",
          "text": "<verbatim>",
          "tweet_url": "...",
          "images": ["..."],
          "created_at": "ISO",
          "relayers": ["dailychartbook"]
        }
      ]
    }
  ]
}
```

### RULES
1. **Catalog, don't analyze.** No buy/sell calls. No "this means…". Just group + caption.
2. **Images are the content.** Every image rendered inline. Never drop a chart.
3. **Verbatim text.** Do not rewrite the relayer's caption. Neil's narrative especially.
4. **One item per tweet per bank** — same tweet can appear under two banks if it tags two.
5. **Theme subheadings are descriptive, not editorial** — name what the chart shows.

### VERIFICATION CHECKLIST (after the report, before render)

- [ ] STEP 0 actually run and PASS reproduced verbatim at the top of the JSON output.
- [ ] `kept + dropped == considered`; `considered ≤ total_tweets`.
- [ ] Every KEPT item has `banks` non-empty OR `author_username == neilksethi` (lowercased).
- [ ] Every kept item carries ≥1 image.
- [ ] `by_bank_counts` matches the sum of `items` in `banks`.
- [ ] No paraphrasing in any `text` field.

If any check fails, fix and re-verify before rendering.

## STEP 4 — FETCH TEMPLATE

Reuse the Twitter Data report template (same image-first catalog style):

```
https://raw.githubusercontent.com/eric0205market-bit/market-intelligence/main/templates/twitter_data_report.html
```

In the template, find `__REPORT_DATA__` inside the `<script>` tag and replace with the JSON object from STEP 3 (raw object, not stringified).

## STEP 5 — SAVE / PUSH

```bash
git checkout -b claude/twitter-bank-research-$(date +%Y%m%d_%H%M)
mkdir -p reports
# Save HTML as reports/twitter_bank_research_YYYY-MM-DD_HHMM.html (HHMM = current UTC)
git add reports/
git commit -m "Bank Research: YYYY-MM-DD HH:MM — N items across K banks"
git push origin HEAD
```

The `Merge to main` action will pick up the `claude/twitter-bank-research-*` branch and merge it. Do not push to main directly. Do not modify any other file in this routine.
