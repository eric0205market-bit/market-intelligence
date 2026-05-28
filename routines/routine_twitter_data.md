# CLOUD ROUTINE — TWITTER DATA INTELLIGENCE
# Model: Sonnet 4.6
# Trigger: 2x/day after collection

## STEP 1: FETCH DATA

Clone the repository and read the data file:

```bash
git clone https://github.com/eric0205market-bit/market-intelligence.git
cd market-intelligence
```

Read the file: `data/twitter/latest/tweets_for_routine_data.json`

This is your input — a JSON array of tweets from DATA accounts. Read the ENTIRE file contents. Do not skip, truncate, or summarize the JSON.

If the file is missing or empty, stop and report: "No data file found."

## STEP 2: PROCESS

You are a data curator for an active daily trader. You receive tweets from DATA accounts — people who post charts, data points, economic indicators, market stats, fund flows, and news. NOT original analysis (that's Alpha routine). These accounts are valuable for WHAT they share, not for their opinions.

Your job: organize the data flow so the trader sees every chart, every data point, every stat — grouped by topic, nothing missed.

### INPUT FORMAT
JSON with tweets array. Each tweet: id, tweet_url, text/full_text, author_username, created_at, urls, images.

NO engagement metrics. ALL accounts EQUAL.

### HOW TO PROCESS

**This is a DATA catalog, not editorial analysis.**

Key difference from Alpha routine:
- Alpha = original thinking, editorial judgment needed
- Data = charts, stats, indicators — CATALOG everything, minimal editorial

**Images are critical.** Most value in Data tweets IS the chart/image. A tweet without its chart is almost worthless. Ensure every image is captured.

**Group by topic.** Don't list by author — group by what the data shows:
- Market data (indices, sectors, commodities, FX, rates)
- Fund flows & positioning (ETF flows, CFTC, prime broker, AAII)
- Economic indicators (CPI, NFP, PMI, housing, etc.)
- Earnings & corporate (if any)
- Crypto data (on-chain, exchange flows, stablecoin supply)
- Other data

**Minimal summary.** Don't analyze — describe what the chart/data shows in 1-2 sentences. The trader will look at the chart themselves.

**Include everything.** Data tweets are almost never noise. A chart is a chart. Only exclude: pure retweets without addition, completely off-topic (sports scores), broken images.

### OUTPUT SECTIONS

#### SUMMARY
3-4 sentences. What data came through today. "15 charts covering X, Y, Z themes. Key numbers: [list 3-5 standout data points]."

#### DATA BY TOPIC
Grouped by theme. Each group:
```json
{
  "topic": "Fund Flows & Positioning",
  "items": [
    {
      "author": "neilksethi",
      "description": "Goldman: HF net leverage at 59%, 85th percentile. MF cash allocations at 1.4%, near record low.",
      "tweet_url": "...",
      "images": ["..."],
      "data_points": ["HF leverage 59%", "MF cash 1.4%"],
      "created_at": "ISO timestamp"
    }
  ]
}
```

`data_points` = extractable numbers/stats from the chart or text.

#### LINK QUEUE
External links for other routines.

### OUTPUT FORMAT

```json
{
  "report_type": "TWITTER DATA INTELLIGENCE",
  "collected_at": "...",
  "input_stats": {
    "total_tweets": N,
    "unique_authors": N,
    "tweets_with_images": N,
    "after_filter": N
  },
  "summary": "...",
  "topics": [
    {
      "topic": "Topic Name",
      "items": [
        {
          "author": "username",
          "description": "1-2 sentences describing the data",
          "tweet_url": "...",
          "images": ["..."],
          "data_points": ["key stat 1", "key stat 2"],
          "created_at": "ISO timestamp"
        }
      ]
    }
  ],
  "links": [...],
  "coverage": {
    "authors_covered": N,
    "authors_total": N
  }
}
```

### RULES

1. **Images are the content.** Never drop an image.
2. **Catalog, don't analyze.** Describe data, don't interpret.
3. **Group by topic, not by author.**
4. **Extract data_points** — specific numbers from charts/text.
5. **Coverage target: 90%+** — almost nothing is noise in Data accounts.
6. **Include created_at** for each item — freshness matters.

### VERIFICATION CHECKLIST (do this AFTER completing the report)

Before outputting, verify:

- [ ] Coverage ≥ 90% of unique authors? If below, you are filtering too aggressively — go back and add the missing authors' tweets.
- [ ] Every author who posted 2+ tweets: do they have at least 1 item in the report? If not, go back and add.
- [ ] Every tweet with images/charts: is it in the report? Charts ARE the content for Data accounts — never drop a chart.
- [ ] after_filter should be ≥ 80% of total_tweets. If you filtered more than 20%, your noise threshold is too high for Data accounts. Go back and include more.
- [ ] Any author completely missing from the report? Review their tweets — Data accounts rarely post noise.

If any check fails, go back and fix before outputting the JSON.

## STEP 3: FETCH TEMPLATE

Use web_fetch to get the HTML template:
```
https://raw.githubusercontent.com/eric0205market-bit/market-intelligence/main/templates/twitter_data_report.html
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
git checkout -b claude/twitter-data-$(date +%Y%m%d_%H%M)

mkdir -p reports
# Save HTML file as reports/twitter_data_YYYY-MM-DD_HHMM.html  (HHMM = current UTC time, e.g. $(date -u +%H%M))

git add reports/
git commit -m "Twitter Data: YYYY-MM-DD HH:MM — N items, M data points"
git push origin HEAD
```

The GitHub Action will auto-merge to main.
