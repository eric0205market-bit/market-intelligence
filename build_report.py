import json, os

REPORT_JSON = {
  "report_type": "TWITTER BANK RESEARCH",
  "collected_at": "2026-06-24T17:23:33Z",
  "window_days": 4,
  "date": "2026-06-24 — TWITTER BANK RESEARCH · 13 items · JPM 10 · Apollo/Slok 2 · BofA 1",
  "input_stats": {
    "total_tweets": 60,
    "considered": 60,
    "kept": 13,
    "dropped": 47,
    "deduped": 0
  },
  "summary": "JPM/Cembalest dominates with 10 items: semiconductor technicals breaching dot-com-era levels, massive hedge fund chip accumulation, AI hyperscalers risking negative FCF, SpaceX free-float timeline, gold share of central bank reserves driven by price not allocation, P/E discount trap for non-US allocators, and Aerospace & Defense multi-year strength.\n\nApollo/Slok (2): flags the inverted oil-price narrative — cheaper crude may amplify demand and raise inflation — and raises the risk of critical global distillate tank drawdowns.\n\nBofA (1): consumer housing sentiment flips net positive for the first time since 2023.\n\nCount: JPM 10 · Apollo/Slok 2 · BofA 1.",
  "by_bank_counts": {"JPM": 10, "Apollo/Slok": 2, "BofA": 1},
  "topics": [
    {
      "topic": "JPM (10) — Cembalest: AI capex, semiconductor technicals, equity concentration, global returns",
      "bank": "JPM",
      "theme": "Cembalest JPMAM — AI capex / FCF risk, semiconductor technicals at dot-com levels, equity concentration, long-run global return benchmarks",
      "items": [
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069771524966396387",
          "text": "Aerospace & Defense has consolidated (to put it nicely) since early March, but the group has been strong since the start of last year JPMAM https://t.co/frcJkevPOC",
          "images": ["https://pbs.twimg.com/media/HLlOO-TWsAALLK_.jpg"],
          "created_at": "2026-06-24T13:16:00.000Z",
          "relayers": [],
          "data_points": ["JPM · JPMAM"]
        },
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069769957374583038",
          "text": "Banks $KBE lit heading into mid-year... and earnings season... $JPM https://t.co/tajq6DSAi7",
          "images": ["https://pbs.twimg.com/media/HLlMzvNWAAAiTeE.png"],
          "created_at": "2026-06-24T13:09:46.000Z",
          "relayers": [],
          "data_points": ["JPM"]
        },
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069767763971674147",
          "text": "AI hyperscalers could turn free cash flow negative this year... but can they just turn the spigot on a whim? Chart from Cembalest JPMAM https://t.co/FVoxmRYEWc",
          "images": ["https://pbs.twimg.com/media/HLlK0D1XIAAwkuw.png"],
          "created_at": "2026-06-24T13:01:04.000Z",
          "relayers": [],
          "data_points": ["JPM · Cembalest"]
        },
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069762716835656158",
          "text": "Cembalest JPMAM: Equity market concentration: the US is actually at the lower end\n\nbut nobody actually allocated across 45 country ETFs.. more like US & International.. and international is far less top-heavy https://t.co/40BCgyjBaL",
          "images": ["https://pbs.twimg.com/media/HLlGORHXQAAWhDe.jpg"],
          "created_at": "2026-06-24T12:41:00.000Z",
          "relayers": [],
          "data_points": ["JPM · Cembalest"]
        },
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069760199951282336",
          "text": "Cembalest JPMAM: Massive jump in hedge fund chip exposure https://t.co/NlsHa3SFWA",
          "images": ["https://pbs.twimg.com/media/HLlD7xoWAAAX6g-.png"],
          "created_at": "2026-06-24T12:31:00.000Z",
          "relayers": [],
          "data_points": ["JPM · Cembalest"]
        },
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069757729711743127",
          "text": "Estimates of SpaceX free float timeline JPMAM $SPCX https://t.co/DgUSFa7xpK",
          "images": ["https://pbs.twimg.com/media/HLlBr_XXkAAszaV.png"],
          "created_at": "2026-06-24T12:21:11.000Z",
          "relayers": [],
          "data_points": ["JPM · JPMAM"]
        },
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069757684627206326",
          "text": "Cembalest JPMAM:  The semiconductor stock rally has generated technicals breaching levels last seen during the dot-com boom https://t.co/P2g0XdPS5W",
          "images": ["https://pbs.twimg.com/media/HLlBpUTWYAAVPKC.png"],
          "created_at": "2026-06-24T12:21:00.000Z",
          "relayers": [],
          "data_points": ["JPM · Cembalest"]
        },
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069755100738806084",
          "text": "Only South Africa and Australia have had better stock market returns than the US. JPMAM \n\nWeighted average long-run real CAGR near 5% for stocks (careful with those 10% assumed stock market returns in your personal financial planning) https://t.co/8Zkay7Batc",
          "images": ["https://pbs.twimg.com/media/HLk_S-JWkAA8qna.png"],
          "created_at": "2026-06-24T12:10:44.000Z",
          "relayers": [],
          "data_points": ["JPM · JPMAM"]
        },
        {
          "author": "dailychartbook",
          "tweet_url": "https://x.com/dailychartbook/status/2069752686048604286",
          "text": "\"Almost the entire increase in the gold share of central bank reserves since 2009 is a function of rising gold prices rather than higher gold allocations.\"\n\n-JPM Cembalest https://t.co/mfhiw9Odbp",
          "images": ["https://pbs.twimg.com/media/HLk9GZCXgAARSXE.jpg"],
          "created_at": "2026-06-24T12:01:09.000Z",
          "relayers": [],
          "data_points": ["JPM · Cembalest"]
        },
        {
          "author": "dailychartbook",
          "tweet_url": "https://x.com/dailychartbook/status/2069729628118196560",
          "text": "\"The P/E ratio discount for non-US stocks has been the equivalent of a bug zapper for many asset allocators.\"\n\n-JPM Cembalest https://t.co/5muyYNnGAv",
          "images": ["https://pbs.twimg.com/media/HLkoIQMXIAAWrnK.jpg"],
          "created_at": "2026-06-24T10:29:31.000Z",
          "relayers": [],
          "data_points": ["JPM · Cembalest"]
        }
      ]
    },
    {
      "topic": "Apollo/Slok (2) — Oil price paradox and distillate inventory risk",
      "bank": "Apollo/Slok",
      "theme": "Slok on oil — lower crude prices as demand amplifier, risk of critical global distillate tank drawdowns",
      "items": [
        {
          "author": "MikeZaccardi",
          "tweet_url": "https://x.com/MikeZaccardi/status/2069741638428094802",
          "text": "The narrative in markets is changing from “lower oil prices mean lower inflation” to “lower oil prices mean more demand in an already overheating economy, which means higher inflation.”\n\nTorsten at Apollo https://t.co/mrRZxjsGTI",
          "images": ["https://pbs.twimg.com/media/HLkzDT4XsAACwCZ.jpg"],
          "created_at": "2026-06-24T11:17:15.000Z",
          "relayers": [],
          "data_points": ["Apollo/Slok"]
        },
        {
          "author": "dailychartbook",
          "tweet_url": "https://x.com/dailychartbook/status/2069737553763106899",
          "text": "\"What are the implications if some tanks reach critical levels somewhere in the world, including distillate fuels in the US?\"\n\n-Apollo Slok https://t.co/yz8l4cN0U6",
          "images": ["https://pbs.twimg.com/media/HLkvVbWWcAAqDtQ.jpg"],
          "created_at": "2026-06-24T11:01:01.000Z",
          "relayers": [],
          "data_points": ["Apollo/Slok"]
        }
      ]
    },
    {
      "topic": "BofA (1) — Consumer housing sentiment turns positive",
      "bank": "BofA",
      "theme": "BofA survey — buy-vs-rent sentiment net positive for first time since 2023",
      "items": [
        {
          "author": "LanceRoberts",
          "tweet_url": "https://x.com/LanceRoberts/status/2069732153844240541",
          "text": "For the first time since 2023, more consumers say it's better to buy a home than to rent, according to Bank of America's latest survey. https://t.co/pJxkMW8Jg3",
          "images": ["https://pbs.twimg.com/media/HLkqSGLWwAEr2ii.jpg"],
          "created_at": "2026-06-24T10:39:33.000Z",
          "relayers": [],
          "data_points": ["BofA"]
        }
      ]
    }
  ],
  "banks": [
    {
      "bank": "JPM",
      "theme": "Cembalest JPMAM — AI capex / FCF risk, semiconductor technicals at dot-com levels, equity concentration, long-run global return benchmarks",
      "items": [
        {"author": "MikeZaccardi", "text": "Aerospace & Defense has consolidated (to put it nicely) since early March, but the group has been strong since the start of last year JPMAM https://t.co/frcJkevPOC", "tweet_url": "https://x.com/MikeZaccardi/status/2069771524966396387", "images": ["https://pbs.twimg.com/media/HLlOO-TWsAALLK_.jpg"], "created_at": "2026-06-24T13:16:00.000Z", "relayers": []},
        {"author": "MikeZaccardi", "text": "Banks $KBE lit heading into mid-year... and earnings season... $JPM https://t.co/tajq6DSAi7", "tweet_url": "https://x.com/MikeZaccardi/status/2069769957374583038", "images": ["https://pbs.twimg.com/media/HLlMzvNWAAAiTeE.png"], "created_at": "2026-06-24T13:09:46.000Z", "relayers": []},
        {"author": "MikeZaccardi", "text": "AI hyperscalers could turn free cash flow negative this year... but can they just turn the spigot on a whim? Chart from Cembalest JPMAM https://t.co/FVoxmRYEWc", "tweet_url": "https://x.com/MikeZaccardi/status/2069767763971674147", "images": ["https://pbs.twimg.com/media/HLlK0D1XIAAwkuw.png"], "created_at": "2026-06-24T13:01:04.000Z", "relayers": []},
        {"author": "MikeZaccardi", "text": "Cembalest JPMAM: Equity market concentration: the US is actually at the lower end\n\nbut nobody actually allocated across 45 country ETFs.. more like US & International.. and international is far less top-heavy https://t.co/40BCgyjBaL", "tweet_url": "https://x.com/MikeZaccardi/status/2069762716835656158", "images": ["https://pbs.twimg.com/media/HLlGORHXQAAWhDe.jpg"], "created_at": "2026-06-24T12:41:00.000Z", "relayers": []},
        {"author": "MikeZaccardi", "text": "Cembalest JPMAM: Massive jump in hedge fund chip exposure https://t.co/NlsHa3SFWA", "tweet_url": "https://x.com/MikeZaccardi/status/2069760199951282336", "images": ["https://pbs.twimg.com/media/HLlD7xoWAAAX6g-.png"], "created_at": "2026-06-24T12:31:00.000Z", "relayers": []},
        {"author": "MikeZaccardi", "text": "Estimates of SpaceX free float timeline JPMAM $SPCX https://t.co/DgUSFa7xpK", "tweet_url": "https://x.com/MikeZaccardi/status/2069757729711743127", "images": ["https://pbs.twimg.com/media/HLlBr_XXkAAszaV.png"], "created_at": "2026-06-24T12:21:11.000Z", "relayers": []},
        {"author": "MikeZaccardi", "text": "Cembalest JPMAM:  The semiconductor stock rally has generated technicals breaching levels last seen during the dot-com boom https://t.co/P2g0XdPS5W", "tweet_url": "https://x.com/MikeZaccardi/status/2069757684627206326", "images": ["https://pbs.twimg.com/media/HLlBpUTWYAAVPKC.png"], "created_at": "2026-06-24T12:21:00.000Z", "relayers": []},
        {"author": "MikeZaccardi", "text": "Only South Africa and Australia have had better stock market returns than the US. JPMAM \n\nWeighted average long-run real CAGR near 5% for stocks (careful with those 10% assumed stock market returns in your personal financial planning) https://t.co/8Zkay7Batc", "tweet_url": "https://x.com/MikeZaccardi/status/2069755100738806084", "images": ["https://pbs.twimg.com/media/HLk_S-JWkAA8qna.png"], "created_at": "2026-06-24T12:10:44.000Z", "relayers": []},
        {"author": "dailychartbook", "text": "\"Almost the entire increase in the gold share of central bank reserves since 2009 is a function of rising gold prices rather than higher gold allocations.\"\n\n-JPM Cembalest https://t.co/mfhiw9Odbp", "tweet_url": "https://x.com/dailychartbook/status/2069752686048604286", "images": ["https://pbs.twimg.com/media/HLk9GZCXgAARSXE.jpg"], "created_at": "2026-06-24T12:01:09.000Z", "relayers": []},
        {"author": "dailychartbook", "text": "\"The P/E ratio discount for non-US stocks has been the equivalent of a bug zapper for many asset allocators.\"\n\n-JPM Cembalest https://t.co/5muyYNnGAv", "tweet_url": "https://x.com/dailychartbook/status/2069729628118196560", "images": ["https://pbs.twimg.com/media/HLkoIQMXIAAWrnK.jpg"], "created_at": "2026-06-24T10:29:31.000Z", "relayers": []}
      ]
    },
    {
      "bank": "Apollo/Slok",
      "theme": "Slok on oil — lower crude prices as demand amplifier, risk of critical global distillate tank drawdowns",
      "items": [
        {"author": "MikeZaccardi", "text": "The narrative in markets is changing from “lower oil prices mean lower inflation” to “lower oil prices mean more demand in an already overheating economy, which means higher inflation.”\n\nTorsten at Apollo https://t.co/mrRZxjsGTI", "tweet_url": "https://x.com/MikeZaccardi/status/2069741638428094802", "images": ["https://pbs.twimg.com/media/HLkzDT4XsAACwCZ.jpg"], "created_at": "2026-06-24T11:17:15.000Z", "relayers": []},
        {"author": "dailychartbook", "text": "\"What are the implications if some tanks reach critical levels somewhere in the world, including distillate fuels in the US?\"\n\n-Apollo Slok https://t.co/yz8l4cN0U6", "tweet_url": "https://x.com/dailychartbook/status/2069737553763106899", "images": ["https://pbs.twimg.com/media/HLkvVbWWcAAqDtQ.jpg"], "created_at": "2026-06-24T11:01:01.000Z", "relayers": []}
      ]
    },
    {
      "bank": "BofA",
      "theme": "BofA survey — buy-vs-rent sentiment net positive for first time since 2023",
      "items": [
        {"author": "LanceRoberts", "text": "For the first time since 2023, more consumers say it's better to buy a home than to rent, according to Bank of America's latest survey. https://t.co/pJxkMW8Jg3", "tweet_url": "https://x.com/LanceRoberts/status/2069732153844240541", "images": ["https://pbs.twimg.com/media/HLkqSGLWwAEr2ii.jpg"], "created_at": "2026-06-24T10:39:33.000Z", "relayers": []}
      ]
    }
  ]
}

with open('/home/user/market-intelligence/templates/twitter_data_report.html', 'r') as f:
    template = f.read()

# Replace __REPORT_DATA__ with the JSON (as a JS object literal, not a string)
json_str = json.dumps(REPORT_JSON, ensure_ascii=False, indent=2)
html = template.replace('__REPORT_DATA__', json_str)

out_path = '/home/user/market-intelligence/reports/twitter_bank_research_2026-06-24_1749.html'
os.makedirs('/home/user/market-intelligence/reports', exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Written: {out_path} ({os.path.getsize(out_path)} bytes)")
