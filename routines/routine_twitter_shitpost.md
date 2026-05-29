# CLOUD ROUTINE — SHITPOST RADAR
# Model: Haiku 4.5
# Trigger: 2x/day after collection

## STEP 0 — FRESHNESS GATE (MANDATORY, RUN FIRST)
Before anything else, verify the input is from the current collection cycle:

    python3 scripts/check_freshness.py data/twitter/latest/tweets_shitpost.json --max-age-hours 6

If it exits non-zero / prints "FRESHNESS GATE FAILED": STOP. Generate nothing, write no JSON/HTML, commit/push nothing. Output a one-line abort note including the script's message, then end the run. Continue to the steps below ONLY if the gate PASSES.

## STEP 1: FETCH DATA

Clone the repository and read the data file:

```bash
git clone https://github.com/eric0205market-bit/market-intelligence.git
cd market-intelligence
```

Read the file: `data/twitter/latest/tweets_shitpost.json`

This is your input — a JSON array of tweets from SHITPOST accounts. Read the ENTIRE file contents. Do not skip, truncate, or summarize the JSON.

If the file is missing or empty, stop and report: "No shitpost data file found."

## STEP 2: PROCESS

You process tweets from SHITPOST accounts — active traders who mostly post noise but occasionally drop substance. You are NOT an editor. You are a SCANNER running 4 specific methods.

### INPUT FORMAT
JSON with tweets array. Each tweet: id, tweet_url, text/full_text, author_username, created_at, images, is_quote, quoted_tweet_text.

### 4 METHODS — run all, output results

#### METHOD A+E: TICKERS + DELTA
1. Scan ALL tweets for token/ticker mentions: $TICKER format, plain text (BTC, ETH, SOL, etc.), project names (Hyperliquid→HYPE, Zcash→ZEC, etc.)
2. Count mentions per ticker
3. Flag which tickers are NEW (not commonly mentioned by this group — mark as new)
4. For each ticker: list which authors mentioned it and the sentiment context (one short phrase)

#### METHOD B: SENTIMENT PER TICKER
For each ticker found in Method A:
- Classify each mention as bull / bear / neutral based on context
- "full port, 10x, retire" = bull
- "careful, overvalued, top" = bear
- "trading X", factual mention = neutral
- Output: ticker → bull count, bear count, neutral count

#### METHOD C: OUTLIER FILTER (MAIN METHOD)
Find tweets that are UNUSUALLY substantive for shitpost accounts:
- Tweet > 200 characters (shitposters normally write 20-80ch)
- Tweet with charts/images from normally text-only poster
- Tweet with actual thesis, data, or analysis instead of usual one-liners
- For each outlier: author, why it's unusual, summary of content, tweet_url

#### METHOD F: VOLUME METRIC
- Total tweets
- Active authors (out of total in watchlist)
- Silent authors count

### OUTPUT FORMAT

```json
{
  "report_type": "SHITPOST RADAR",
  "collected_at": "...",
  "volume": {
    "total_tweets": N,
    "active_authors": N,
    "total_authors": 35,
    "silent_authors": N
  },
  "tickers": [
    {
      "ticker": "ZEC",
      "mentions": 2,
      "is_new": true,
      "bull": 2, "bear": 0, "neutral": 0,
      "who": [
        {"author": "gainzy222", "context": "full port, 10x thesis"},
        {"author": "CryptoHayes", "context": "trifecta bull video"}
      ]
    }
  ],
  "outliers": [
    {
      "author": "gainzy222",
      "usual_length": 50,
      "this_length": 461,
      "summary": "ZEC full port thesis...",
      "tweet_url": "...",
      "images": []
    }
  ]
}
```

IMPORTANT: total_authors = use the category_accounts field from the input metadata, NOT watchlist_accounts. If category_accounts is missing, count unique authors in the tweets array and add ~30% for typically silent accounts.

### RULES
1. Process ALL tweets — don't skip any
2. Ticker detection: be broad — $BTC, "bitcoin", "btc", project names all count
3. Outlier threshold: >200 chars OR has images when author normally doesn't
4. Don't analyze or editorialize — just scan and report
5. Keep summaries short (1-2 sentences per outlier)

### VERIFICATION CHECKLIST (do this AFTER completing the report)

Before outputting, verify:

- [ ] Every author's tweets scanned for tickers? If an author has 3+ tweets and zero ticker mentions, double-check — they may use project names instead of $TICKER format.
- [ ] Every author with 3+ tweets appears somewhere in the output (tickers or outliers)? If not, review their tweets.
- [ ] Every tweet > 200 characters flagged as outlier? These are unusually long for shitpost accounts.
- [ ] Every tweet with images from a normally text-only author flagged as outlier?
- [ ] Volume numbers correct? total_tweets + active_authors + silent_authors should match the input.

If any check fails, go back and fix before outputting the JSON.

## STEP 3: FETCH TEMPLATE

Use web_fetch to get the HTML template:
```
https://raw.githubusercontent.com/eric0205market-bit/market-intelligence/main/templates/twitter_shitpost_report.html
```

## STEP 4: RENDER REPORT

Take the JSON output from Step 2. Take the HTML template from Step 3.

In the template, find the placeholder `__REPORT_DATA__` inside the `<script>` tag. Replace it with the JSON object (not stringified — raw JS object).

Output the complete HTML file.

## STEP 5: SAVE

Save the HTML report to the repository:

```bash
git clone https://github.com/eric0205market-bit/market-intelligence.git
cd market-intelligence
git checkout -b claude/twitter-shitpost-$(date +%Y%m%d_%H%M)

mkdir -p reports
# Save HTML file as reports/twitter_shitpost_YYYY-MM-DD_HHMM.html  (HHMM = current UTC time, e.g. $(date -u +%H%M))

git add reports/
git commit -m "Shitpost Radar: YYYY-MM-DD HH:MM — N tickers, M outliers"
git push origin HEAD
```

The GitHub Action will auto-merge to main.
