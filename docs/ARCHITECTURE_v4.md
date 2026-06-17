MARKET INTELLIGENCE PLATFORM — ARCHITECTURE v4
Date: May 31, 2026 (supersedes v3, May 24)
Revised: Jun 07, 2026 — added KNOWLEDGE EXECUTION MODEL (YouTube built; local collection + subscription-Opus extraction; deep history outside repo)
Revised: Jun 17, 2026 — KNOWLEDGE collection decided per IP-risk (Concepts live, cloud Playwright; Technology building); track-wide Flow triage decided
Design doc — slow-changing. Holds the model, principles, tiers, knowledge
architecture, build order. Does NOT hold live status — that's in
MODULE_REGISTRY.md (the single source of truth for "what's built / running").
Update this doc only on an architectural event (new track, storage change,
new model tier, new module on the map). See "Doc model" at the end.
OVERVIEW
Fully automated intelligence platform for an active daily trader (Switzerland). Generalist — edge from connecting dots across domains: geopolitics, energy, AI, demographics, macro.
Portfolio: equities 60-70%, crypto ~20%, bonds ~20%. 150+ Substack subscriptions. Max plan.
Core principle: deterministic where possible, LLM only where necessary. Three model tiers by task complexity. Collectors commit data, the dashboard generator renders — no LLM in rendering.
TWO-TRACK ARCHITECTURE
Content splits into two fundamentally different types, processed differently.
FLOW — perishable, time-sensitive
"What's happening now?" — consumed daily, forgotten in a week.
Twitter (three routes: Alpha, Data, Shitpost)
Twitter Banks (institutional research relayed on Twitter, author-signal)
Institutional Research (bank / asset-manager websites)
Bank PDF (public full research PDFs)
Newsletters & News (Substack / newsletters)
Earnings calls (quarterly, bulk)
KNOWLEDGE — deep, lasting, accumulative
"How does the world work?" — builds over months.
YouTube / Podcasts — built / live (77 channels). Concepts — built / live (Jun-17). Technology — building. Society — not started. (See KNOWLEDGE EXECUTION MODEL below.)
Classification is by content depth, not by source. A channel can post a daily recap (flow) and a 2-hour interview (knowledge). But most flow-source content stays flow.
Rhythm sub-split (presentation layer)
Within FLOW, the dashboard groups streams by cadence, because the trader scans them differently:
PULSE — intraday (2–3×/day): Twitter Alpha, Twitter Data, Twitter Shitpost, Newsletters & News
RESEARCH — daily→weekly: Twitter Banks, Bank PDF, Institutional Research
This is config-driven (a group field per stream in REPORT_TYPES), so a new slow stream = one line. KNOWLEDGE streams will form their own group(s) when built.
SYSTEM DIAGRAM
COLLECTION (100% deterministic scripts, cloud — GitHub Actions)
┌───────────────────────────────────┐    ┌──────────────────────────┐
│           FLOW SOURCES            │    │   KNOWLEDGE SOURCES      │
│                                   │    │  (YouTube live; see below)│
│  Twitter Alpha/Data/Shitpost      │    │  YouTube    (transcript) │
│              (GetXAPI, 2×/day)    │    │  Concepts   (Playwright) │
│  Twitter Banks (relayer accts,    │    │  Technology (Playwright) │
│              author-signal)       │    │  Society    (Playwright) │
│  Institutional (bank/AM sites,    │    │                          │
│              Playwright, weekly)  │    │                          │
│  Bank PDF (public PDFs, weekly,   │    │                          │
│              NO LLM)              │    │                          │
│  Newsletters (Gmail interim)      │    │                          │
│  Earnings (transcript API)        │    │                          │
└────────────────┬──────────────────┘    └────────────┬─────────────┘
                 │                                     │
                 ▼                                     ▼
PROCESSING (deterministic → LLM → deterministic)
  FLOW: filter/classify (determ.) → summarize/extract              KNOWLEDGE:
        (Opus/Sonnet/Haiku by route) → JSON → HTML (determ.)       cards + chart
                                                                   vision (Sonnet)
                 │                                     │
                 ▼                                     ▼
STORAGE & OUTPUT
  GitHub-as-bus (current): collectors commit reports/*.html        KNOWLEDGE GRAPH
  → generator builds index.html → GitHub Pages (live dashboard)    Supabase (TARGET,
  Supabase migration = target, NOT started                         not started)
                 │                                     │
                 └──────────────────┬──────────────────┘
                                    ▼
SYNTHESIS (designed, not built)
  SHIFTS (every 2 weeks · Opus)  →  INVESTMENT COMMITTEE (multi-frontier + rules)
Diagram caveat (Jun-07): the COLLECTION/PROCESSING boxes above describe the FLOW track (cloud, GitHub Actions, API tiers). The first built KNOWLEDGE stream (YouTube) does not follow this — its collection runs locally (launchd, no LLM) and its extraction runs on the Opus subscription in Claude Code, not the cloud API. See "KNOWLEDGE EXECUTION MODEL" below.
MODEL TIERS
Three tiers, all cloud API (works when Mac is off):
TierModelsUsed forBulkHaiku, DeepSeekTweet/article summaries, tagging, classification, Shitpost route, EarningsMediumSonnetTwitter Data route, Twitter Banks, knowledge cards, chart visionFrontierOpus, o3, GeminiTwitter Alpha route, Institutional, SHIFTS, Investment Committee
Note vs v3: Twitter is no longer a single Sonnet report. It's split by route: Alpha → Opus (editorial + verification), Data → Sonnet (catalog + data points), Shitpost → Haiku (paused). Institutional runs on Opus.
Why not local models: must run when Mac is off; API cost for bulk ≈ electricity of local GPU; simpler stack.
Tier routing on subscription (Jun-07): the table above is the cloud API plan. The built KNOWLEDGE stream (YouTube) currently extracts on the Opus Max subscription in Claude Code, so tier routing is bypassed — everything runs on Opus. The tier field in the YouTube config (opus/sonnet split) is reserved for a future API phase and is ignored today. Tiers apply as written once a stream moves to the cloud API.
FLOW SOURCES (current design)
Twitter — three routes (GetXAPI, 2×/day, ~05:20 / 17:20 UTC via cron-job.org)
One collection pass, split by author category, three independent report routes.
Alpha (Opus): signal, theses, positioning — editorial + verification pass (prompt v7).
Data (Sonnet): catalog + structured data_points.
Shitpost (Haiku): currently paused.
Engagement metrics stripped before LLM (anti-bias). Images preserved (charts).
Twitter Banks (relayer accounts, author-signal — replaces v3 keyword search)
v3's "28 bank-name keyword queries → 0% useful" is abandoned.
New design: ~7 relayer accounts that systematically repost bank research → author-signal collection, Sonnet. Runs Wed + Sun ~06:45 UTC. In trial; mid-June decision: keep as distinct view or fold into Data.
Institutional Research (NEW — was "separate future project" in v3)
~101 bank / asset-manager websites scraped directly (Playwright), weekly (Sun: collect 06:00 / routine 09:00 UTC), Opus. Fully automated.
Bank PDF / Research PDF Finder (NEW)
Deterministic, no LLM. Weekly. Discovers public full research PDFs via deep paths. Sibling to Institutional. Surfaced on dashboard as "Bank PDF".
Newsletters & News (Substack)
Still on Gmail Cloud Routine (interim); Playwright collector not built (Gmail strips images). Currently has no owner chat — flagged.
Earnings calls (quarterly, bulk — Haiku) — not started. ~500–1000 companies; deterministic beat/miss + Haiku commentary → embeddings.
STORAGE
Current — GitHub-as-bus: collectors commit reports/*.html; scripts/update_dashboard.py reads them and writes index.html; GitHub Pages serves the live dashboard. claude/** branches auto-merge to main via merge-to-main.yml, which re-runs the generator on main's full report set (so the committed index.html is a derived artifact CI overwrites — config in the generator is what matters).
Target — Supabase (Postgres + pgvector): unchanged from v3, not started. Schema (raw_items, knowledge_cards, ontology_rules, chart_data, promoted_items, earnings) and migration path as in v3. Gradual; can run in parallel.
DASHBOARD (presentation)
Generated by scripts/update_dashboard.py from reports/*.html, config in REPORT_TYPES (keyed by report filename prefix = the data link; label = display name; color, icon, group per stream). Sections: Today's Intelligence (PULSE / RESEARCH groups, each with Latest + Previous) and Archive (same subgroups, accordion + counts).
Color logic: hue = rhythm group, tone = stream. PULSE = blue family (#6366F1 / #3B82F6 / #0EA5E9 / #06B6D4); RESEARCH = amber family (#F59E0B Twitter Banks / #D97706 Bank PDF / #EA580C Institutional). Applied to card left-border and archive dot.
Graceful degradation: a stream with no report file renders nothing (e.g. Shitpost while paused), never errors. Unknown future types fall back to DEFAULT_GROUP.
Adding a stream = one REPORT_TYPES line with its group; no markup changes.
KNOWLEDGE ARCHITECTURE (design — not built)
Two layers for finding connections; not a rigid tree.
Layer 1 — Ontology (deterministic, hand-built, ~50–100 rules): known cause-effect chains (oil↑→inflation↑→rates↑; Fed↑→growth↓→credit↓; AI capex↑→semis↑; Hormuz→oil shock; aggregate guidance cuts→growth slowdown; etc.). New flow item matching a trigger auto-surfaces related items — no LLM.
Layer 2 — Embeddings (emergent, pgvector): every quality-passing item gets a vector; connections emerge from semantic proximity, not predefined categories (e.g. "consumer stocks as post-bubble contrarian play" links to labor-AI, tech-positioning, Nifty-Fifty parallels with no causal rule).
Light tags (~8, human browsing only): Macro, Energy, Tech, Crypto, Geopolitics, Positioning, AI, Society. Not a filter — all content still appears in reports.
Why not rigid ontology: predefined trees create blind spots; the edge is connecting dots that don't fit existing categories.
KNOWLEDGE EXECUTION MODEL (added Jun-07 — YouTube built; template for the track)
The KNOWLEDGE track diverges from the FLOW execution model. FLOW = cloud (GitHub Actions) collection + cloud API tiers. The first built KNOWLEDGE stream (YouTube / Podcasts) established a different, local + subscription pattern. This is the reference template for Concepts / Technology / Society (the pattern transfers; the collection mechanism may differ — YouTube uses yt-dlp transcripts, Concepts/Tech/Society use Playwright over sites).
Collection — LOCAL, deterministic, no LLM:
Runs on the Mac via launchd (YouTube: 12:00 daily), not GitHub Actions. yt-dlp + subtitles; no LLM, no quota.
Safeguards: per-run caps; window-based collection self-heals missed days.
IP is the main risk for transcript sources — conservative throttling, hard-stop on any 429 / bot-check / consent-wall, no personal-account cookies.
Extraction — MANUAL, on the Opus Max subscription (not API):
Triggered by the user in Claude Code when quota is fresh; follows a single routine file.
Routine convention: routines/routine_*.md (e.g. routine_youtube.md). Quality is tuned by editing this one file — it is the contract the in-code routine follows.
Entity-presence guard: each extracted record's entities are checked against the raw transcript; <~40% presence → quarantine (non-destructive, excluded from output, surfaced in the run report). Catches subagent hallucination (a whole episode invented from a neighbour). Norm = 0 quarantined.
One-transcript-per-subagent rule; verbatim quote + timestamp verification, non-destructive.
Storage — split by recency:
Daily stream → GitHub as usual: raw/, processed/, dated reports/*.html, dashboard. Same bus as FLOW.
Deep history (backfill, pre-current): separate local code path, separate folder OUTSIDE the git repo, never committed/pushed. Backup = Dropbox; raw is re-collectable, processed re-extractable. Destined for the future Supabase load. JSON-only — no reports, no dashboard — except a one-time dated-HTML render for the slice with upload-date ≥ Apr 1 2026 (so the visible archive is continuous from April).
Resolved (Jun-17) — collection mechanism is chosen per IP-risk, not local-by-default: transcript sources (YouTube) collect locally (transcript IP-risk); Playwright-over-public-sites (Concepts, confirmed live; Technology building; Society to follow) collect in the cloud (GitHub Actions), same as Institutional. Extraction-on-subscription + routine + guard + history-outside-repo carry over either way. The local path stays reserved for any future source with IP-risk.
Flow triage — track-wide (decided Jun-17). KNOWLEDGE sources carry a depth type (Deep / Flow / Data) from curation. Triage applies only to Flow (high-volume news); Deep = extract-all; Data publishers are routed out of the reading stream (to the Data module). Flow is triaged deterministically in the collector, before the worklist (not inside extraction, no LLM):
items whose title+body match config/knowledge_watchlist.json (tickers / companies / sectors / themes, owner-maintained) → worklisted up to a generous per-source cap;
a small recency-capped discovery sample of the freshest non-matching items per source per run is also kept, so cross-domain novelty is not blind-spotted (the owner's edge);
firehose sources (e.g. ArXiv cs.AI / cs.LG, Hacker News; flagged in source config) require a watchlist match (no discovery sample) + a tight cap.
Caps are tunable knobs. No LLM in triage — semantic triage is deferred to the future embeddings layer. The watchlist is shared across KNOWLEDGE Flow streams (Technology, Society); seed from portfolio holdings + config/twitter_watchlist.json + the 8 light tags; it may later merge with the Discovery Loop WATCH_AGENDA. Concepts has no Flow sources, so it runs extract-all and exercises none of this.
CHART / IMAGE UNDERSTANDING (design)
Collection saves image CDN URLs (no files) → vision model (Sonnet) returns description + key numbers + trends → stored in chart_data → original URL preserved for display. Extracted numbers can feed own charts (Recharts/D3). Critical for bank-research screenshots and data charts.
SYNTHESIS (designed, not built)
SHIFTS (every 2 weeks, Opus): flow reports + knowledge queries + ontology activations → emerging clusters, cross-domain connections, narrative evolution, weak signals, source divergence, contrarian detection → SHIFTS report. Needs 2+ weeks of accumulated multi-source data.
Investment Committee (on-demand, multi-frontier): deterministic pre-processing (portfolio, risk rules, Haiku pre-screen) → Opus + o3 + Gemini debate (devil's advocate, scenarios) → deterministic validation + decision journal + thesis-monitoring triggers.
Promote mechanism: user saves a flow item to knowledge with a one-line annotation → embedded, searchable, future near-neighbors auto-flagged.
MONITORING
Phase 1 — freshness gate: built / live. Flags stale streams.
Phase 2 — health strip (per-stream status): backlog.
Phase 3 — single alert channel: backlog.
(Detail in repo docs/BACKLOG.md.)
BUILD ORDER
Status per item lives in MODULE_REGISTRY.md — this is the sequence only.
FLOW track — Twitter (3 routes), Twitter Banks, Institutional, Bank PDF live; Newsletters on interim; Earnings pending. ← largely done
Storage migration — Supabase project, schema, collectors → Supabase API (keep Pages for reports).
Knowledge infrastructure — ontology rules, pgvector, embedding pipeline.
Knowledge track + Earnings — YouTube (built / live, Jun-07), Concepts (built / live, Jun-17); Technology (building), Society, Earnings pending.
Synthesis — SHIFTS, queryable knowledge base, promote, "interesting detector".
Investment Committee — multi-frontier integration, rules, decision journal.
INFRASTRUCTURE
market-intelligence/
├── .github/workflows/   # collection crons + merge-to-main.yml
├── scripts/             # collectors + update_dashboard.py (generator)
├── config/              # watchlists, source lists, classification
├── reports/             # generated HTML reports (data bus → Pages)
├── docs/                # ARCHITECTURE, MODULE_REGISTRY, BACKLOG
└── index.html           # auto-generated dashboard (CI overwrites)
Cloud: GitHub Actions + Pages (free), Anthropic Max plan, GetXAPI (~$2/mo), Haiku/DeepSeek + Sonnet APIs. Supabase when migrated.
KEY DECISIONS
Carried from v3: two-track architecture; deterministic-first; three model tiers; Supabase target; two-layer knowledge (ontology + embeddings, no rigid tree); source-based separate reports; loose tags; promote mechanism; chart vision; cloud-only; Investments module separate; Earnings via Haiku.
New in v4:
Twitter split into three routes (Alpha/Opus, Data/Sonnet, Shitpost/Haiku) — not one report.
Twitter Banks = author-signal via relayer accounts — keyword search abandoned.
Institutional Research is live — direct bank/AM site scraping (was "future separate project").
Bank PDF — new deterministic, no-LLM module (Research PDF Finder), sibling to Institutional.
Dashboard rhythm grouping — FLOW split into PULSE / RESEARCH by cadence; config-driven; color = rhythm.
Stream renames — Bank Research→Twitter Banks, Research→Newsletters & News, Research PDFs→Bank PDF (display labels only; data keys unchanged).
Three-layer doc model (see below) — status moved out of this doc into the registry.
Updated Jun-07 (KNOWLEDGE execution, from YouTube buildout):
8. KNOWLEDGE collection can be LOCAL (launchd, no LLM) — the track is no longer cloud-only. The v3/v4 "cloud-only" stance now applies to FLOW; KNOWLEDGE collection may run on the Mac (no-LLM scripts run fine locally; transcript IP-risk favours a controlled local path).
9. KNOWLEDGE extraction on the Opus Max subscription (manual, Claude Code) — tier routing deferred to a future API phase; today everything is Opus.
10. KNOWLEDGE deep-history data lives OUTSIDE the git repo (never GitHub), backed up on Dropbox, destined for Supabase. Daily stream still goes to GitHub.
11. Routine convention routines/routine_*.md — one file per stream, edited to tune extraction quality.
12. Entity-presence guard (quarantine) — standard defence against extraction hallucination for the KNOWLEDGE track.
Updated Jun-17 (KNOWLEDGE collection + triage):
13. KNOWLEDGE collection is decided per IP-risk, not local-by-default — transcript sources local (YouTube); Playwright-over-public-sites cloud (Concepts live, Technology building, Society to follow), like Institutional.
14. Track-wide Flow triage — deterministic in the collector: watchlist-gate (shared config/knowledge_watchlist.json) + recency-cap + a small discovery-sample of non-matching items (preserves novelty); firehose sources gated harder. No LLM in triage.
DOC MODEL
ARCHITECTURE (this file) — design. Update on an architectural event.
MODULE_REGISTRY.md — status (one line per module/branch). Update the moment a module is born or changes state.
CONTEXT_*.md — detailed per-chat session log.
Plus a weekly reconcile in the Architecture chat: read the week's CONTEXT files → fold real arch changes here → update the registry.
Coordination: one chat owns one routine (Twitter chat owns the watchlist/collection; Institutional its own; etc.). The Architecture chat designs and reconciles — it does not build the per-routine collectors.
