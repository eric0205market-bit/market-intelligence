# MARKET INTELLIGENCE PLATFORM — ARCHITECTURE v4
## Date: May 31, 2026 (supersedes v3, May 24)
## Revised: Jun 07, 2026 — added KNOWLEDGE EXECUTION MODEL (YouTube built; local collection + subscription-Opus extraction; deep history outside repo)
## Revised: Jun 17, 2026 — KNOWLEDGE collection decided per IP-risk (Concepts live, cloud Playwright; Technology building); track-wide Flow triage decided
## Revised: Jun 27, 2026 — Technology live (cloud cron 10:00 UTC + manual Remote, as Concepts); Flow re-cut (22 G3 → Newsletters, Technology watchlist OFF); Newsletters live on interim
## Revised: Jun 27, 2026 — Concepts reconcile: 61 active/17 parked (78 curated); Data sources collected as normal articles (no Data-module routing); backfill extraction ongoing.
## Revised: Jun 27, 2026 — YouTube reconcile: backfill quantified (~1116 processed, cursor 32/77, Hour-16 agent); tails closed (clone removed, plist template fixed, .DS_Store); DOAC handle open; YouTube confirmed emitting own per-video schema (not shared card).
## Revised: Jun 27, 2026 — Concepts→Society relocation: 11 IR think-tanks moved to Society; Concepts now 52 active / 26 parked (78 curated).
## Revised: Jun 29, 2026 — Society built/live (weekly cron Sun 10:00 UTC, first auto-collect Jul-05) → ALL FOUR KNOWLEDGE streams live (YouTube, Concepts, Technology, Society). AS-BUILT correction: track-wide Flow triage NOT engaged by Technology/Society (WATCHLIST_GATE=False; watchlist/discovery-sample OFF). Taxonomy move (11 IR think-tanks Concepts→Society, Jun-27) finalized: Concepts companion edit collect:false done, no double-collection.
## Revised: Jul 9, 2026 — Concepts 51/27 (NBER parked); Society 47/20 (67 sources, 10 IR think-tanks, Chatham House single-homed in Concepts); SCIENCE line reserved (NBER+SSRN); Society history seed (Brookings 104 + Carnegie 28) → society-history/; shared capabilities (RSS route, fresh context, residential path, health check) + publish_*.py data-loss bugs flagged cross-stream.
## Revised: Jul 9, 2026 (v2) — Concepts counts corrected to 50/28, now auto-generated from collect flags (tally script + drift check); note 50≠45 (attempted). Society 47/20 (67). Model discipline: daily=Opus, backfill=Sonnet.
## Revised: Jul 10, 2026 — WRITE SAFETY rules recorded (4 bugs / 3 layers / one root: cloned code). Guards live in all four streams. Concepts history COMPLETE (2608). Supabase load preconditions: blast-radius ratio scan, teaser:true marking, PK = (source_slug, record_id).
## Revised: Jul 10, 2026 (v2) — Institutional write-safety: Bug 3 fixed & deployed (8ff354b0), aggregate-shaped union + status gate + content floor; Bug 1 consciously unfixed (prose report); Bugs 2/4 N/A. New rules: 5 (unit of write determines guard shape — redesign, don't port), 6 (union without status-gate makes the dataset worse), 7 (code ships via claude/** only; data-direct/code-via-branch asymmetry now explicit; ff-only not reset --hard; delete dead guards). Marker lists rot — length-only backstop mandatory. 4c reframed: share invariants, not guards. Unowned production trigger flagged. HTTP status gate unexercised — watch status_rejected on Sunday.
## Revised: Jul 10, 2026 (v3) — RULE 8 disposition (Concepts daily worklist filter+health-check landed); Institutional bug 3 fixed & deployed (8ff354b0), rules 5-7, 4c reframed, external triggers recorded as fact; YouTube IP-safety (50cc83e), RULE 9. Technology history COMPLETE.

> **Design doc — slow-changing.** Holds the model, principles, tiers, knowledge
> architecture, build order. Does NOT hold live status — that's in
> **MODULE_REGISTRY.md** (the single source of truth for "what's built / running").
> Update this doc only on an architectural event (new track, storage change,
> new model tier, new module on the map). See "Doc model" at the end.

---

## OVERVIEW

Fully automated intelligence platform for an active daily trader (Switzerland). Generalist — edge from connecting dots across domains: geopolitics, energy, AI, demographics, macro.

Portfolio: equities 60-70%, crypto ~20%, bonds ~20%. 150+ Substack subscriptions. Max plan.

**Core principle:** deterministic where possible, LLM only where necessary. Three model tiers by task complexity. Collectors commit data, the dashboard generator renders — no LLM in rendering.

---

## TWO-TRACK ARCHITECTURE

Content splits into two fundamentally different types, processed differently.

### FLOW — perishable, time-sensitive
"What's happening now?" — consumed daily, forgotten in a week.
- Twitter (three routes: Alpha, Data, Shitpost)
- Twitter Banks (institutional research relayed on Twitter, author-signal)
- Institutional Research (bank / asset-manager websites)
- Bank PDF (public full research PDFs)
- Newsletters & News (Substack / newsletters)
- Earnings calls (quarterly, bulk)

### KNOWLEDGE — deep, lasting, accumulative
"How does the world work?" — builds over months.
- **YouTube / Podcasts — built / live** (77 channels). **Concepts — built / live** (Jun-17). **Technology — built / live** (Jun-27; cloud cron 10:00 UTC + manual Remote extraction, as Concepts; Flow re-cut: 22 G3 → Newsletters; watchlist OFF for Technology). **Society — built / live** (Jun-29; weekly cron Sun 10:00 UTC, first auto-collect Jul-05; manual Remote extraction, as Technology). **All four KNOWLEDGE streams are now live.** (See KNOWLEDGE EXECUTION MODEL below.)

**Classification is by content depth, not by source.** A channel can post a daily recap (flow) and a 2-hour interview (knowledge). But most flow-source content stays flow.

### Rhythm sub-split (presentation layer)
Within FLOW, the dashboard groups streams by **cadence**, because the trader scans them differently:
- **PULSE** — intraday (2–3×/day): Twitter Alpha, Twitter Data, Twitter Shitpost, Newsletters & News
- **RESEARCH** — daily→weekly: Twitter Banks, Bank PDF, Institutional Research

This is config-driven (a `group` field per stream in `REPORT_TYPES`), so a new slow stream = one line. KNOWLEDGE streams will form their own group(s) when built.

---

## SYSTEM DIAGRAM

```
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
```

> **Diagram caveat (Jun-07):** the COLLECTION/PROCESSING boxes above describe the **FLOW** track (cloud, GitHub Actions, API tiers). The first built KNOWLEDGE stream (YouTube) does **not** follow this — its collection runs **locally** (launchd, no LLM) and its extraction runs on the **Opus subscription** in Claude Code, not the cloud API. See "KNOWLEDGE EXECUTION MODEL" below.

---

## MODEL TIERS

Three tiers, all cloud API (works when Mac is off):

| Tier | Models | Used for |
|------|--------|----------|
| Bulk | Haiku, DeepSeek | Tweet/article summaries, tagging, classification, Shitpost route, Earnings |
| Medium | Sonnet | Twitter Data route, Twitter Banks, knowledge cards, chart vision |
| Frontier | Opus, o3, Gemini | Twitter Alpha route, Institutional, SHIFTS, Investment Committee |

**Note vs v3:** Twitter is no longer a single Sonnet report. It's split by route: **Alpha → Opus** (editorial + verification), **Data → Sonnet** (catalog + data points), **Shitpost → Haiku** (paused). Institutional runs on Opus.

**Why not local models:** must run when Mac is off; API cost for bulk ≈ electricity of local GPU; simpler stack.

**Tier routing on subscription (Jun-07):** the table above is the **cloud API** plan. The built KNOWLEDGE stream (YouTube) currently extracts on the **Opus Max subscription** in Claude Code, so tier routing is **bypassed — everything runs on Opus**. The `tier` field in the YouTube config (opus/sonnet split) is reserved for a future API phase and is ignored today. Tiers apply as written once a stream moves to the cloud API.

---

## FLOW SOURCES (current design)

**Twitter — three routes** (GetXAPI, 2×/day, ~05:20 / 17:20 UTC via cron-job.org)
- One collection pass, split by author category, three independent report routes.
- Alpha (Opus): signal, theses, positioning — editorial + verification pass (prompt v7).
- Data (Sonnet): catalog + structured data_points.
- Shitpost (Haiku): currently **paused**.
- Engagement metrics stripped before LLM (anti-bias). Images preserved (charts).

**Twitter Banks** (relayer accounts, author-signal — replaces v3 keyword search)
- v3's "28 bank-name keyword queries → 0% useful" is **abandoned**.
- New design: ~7 relayer accounts that systematically repost bank research → author-signal collection, Sonnet. Runs Wed + Sun ~06:45 UTC. In trial; mid-June decision: keep as distinct view or fold into Data.

**Institutional Research** (NEW — was "separate future project" in v3)
- ~101 bank / asset-manager websites scraped directly (Playwright), weekly (Sun: collect 06:00 / routine 09:00 UTC), Opus. Fully automated.

**Bank PDF / Research PDF Finder** (NEW)
- Deterministic, **no LLM**. Weekly. Discovers public full research PDFs via deep paths. Sibling to Institutional. Surfaced on dashboard as "Bank PDF".

**Newsletters & News** (Substack)
- **Live on Gmail Cloud Routine (interim), ~2 months** (only downside: Gmail strips charts/images). **Full non-email version (direct/Playwright) pending** — intake: 23 from Technology (22 G3 + The Information) + crypto pool (Decrypt etc.) + possibly paid (Bloomberg/Barron's via owner subscription, volume per source ToS). Needs owner chat.

**Earnings calls** (quarterly, bulk — Haiku) — **not started.** ~500–1000 companies; deterministic beat/miss + Haiku commentary → embeddings.

---

## STORAGE

**Current — GitHub-as-bus:** collectors commit `reports/*.html`; `scripts/update_dashboard.py` reads them and writes `index.html`; GitHub Pages serves the live dashboard. `claude/**` branches auto-merge to main via `merge-to-main.yml`, which re-runs the generator on main's full report set (so the committed `index.html` is a derived artifact CI overwrites — config in the generator is what matters).

**Target — Supabase (Postgres + pgvector):** unchanged from v3, **not started.** Schema (raw_items, knowledge_cards, ontology_rules, chart_data, promoted_items, earnings) and migration path as in v3. Gradual; can run in parallel.

**Preconditions of the base load (not "clean up later"):**
- **Blast-radius scan is a precondition, not a follow-up.** `quote_verified` is a contract field of `KNOWLEDGE_CARD_SCHEMA v1` and the entity-guard verifies against raw; degraded raw makes part of the corpus unverifiable. Scan by **WORD-COUNT RATIO** (card's `source_meta.word_count` vs current raw), NOT by teaser signature — Concepts' single degraded record was clobbered by a reader comment (158w), not a paywall teaser, so a ratio scan catches strictly more than a marker scan.
- **`teaser:true` records must be marked or filtered before load.** Society: 11 of 22 Foreign Affairs cards are "born teasers" (good raw never existed) — a pre-existing `paywalled:false` debt, now detectable.
- **Primary key = (source_slug, record_id).** `record_id` alone collides across slugs (one article reachable from two listings) and would silently merge two cards.
- **Chart vision** (chart_data population via Sonnet) and **PDF content ingestion** (no mechanism yet — design needed) are both preconditions of a complete base load. Charts currently accumulate as URLs unprocessed (tier-routing off); PDFs are collected as links only. A base loaded without them leaves the visual/PDF-heavy streams (Twitter Banks, Institutional, Bank PDF) largely unextracted.
- ⚠ **PROVENANCE CHECK (track-wide blocker, discovered by the Society backfill Jul-10).** quote_verified + entity-guard verify PRESENCE, not ORIGIN. A quote can be verbatim and an entity truly present while BOTH come from template chrome (sidebars: "The Latest / Related / Most Popular", nav rails), not the article body. Society backfill passed 22 fabricated the_point cards + 15 "Archives" listings (one card = ~10 unrelated teasers) GREEN on both guards; only a corpus-wide near-dup scan caught them, post-hoc. Any source with a related/latest rail is an injection vector. The rubric + guard are SHARED across all streams → YouTube/Concepts/Technology may carry the same contamination. FIX: add a provenance check to the rubric (claim/quote text must trace to the article body, isolated from detected chrome zones) AND run it over already-extracted corpora BEFORE load, not after.
- ⚠ **SPEAKER PROVENANCE (track-wide blocker, discovered by the Society backfill Jul-10).** speaker is a contract field of schema v1. Extraction subagents systematically replaced raw `author` with a name from the article body, "inferring the convention" from neighboring cards (self-reinforcing). Society: 142 cards / 962 insights across 11 sources, fixed. The rubric is shared → other streams' corpora may carry the same substitution. Verify speaker origin (must equal raw author) before load.
- **Corpus inventory (live counts per stream) is itself a precondition.** These docs carry no live counts; count in-repo before planning the load.

---

## WRITE SAFETY (hard rules)

**Four bugs, three layers, one root: code is cloned between streams.** Bugs 1–2 (publish render, `_quarantine.json`), Bug 3 (raw records), Bug 4 (backfill extraction prompt) are all the same class — *writing over an existing file without reading it first.*

**RULE 1 — No write over an existing file without a merge or a guard.**
- aggregates (reports, quarantine logs) → **union by (slug, record_id)**
- content (raw records) → **no-degrade ratio guard** (`DEGRADE_MIN_RATIO=0.8`)
- every rejection logged loudly and visible in the funnel (`degrade_skipped`), never silent.

**RULE 2 — Length-gate, not marker-gate.** Any junk/teaser detector requires BOTH a marker AND a length threshold, and is tested ONLY against real raw from git history, never synthetic. Five real cases where a marker signature nearly cut live content: `/forum/members/` vs `/forum/threads/` URL shape (would have killed 66 real articles); W&B nav boilerplate (present on 387 real articles); "already a subscriber" false-fired on 9 of 10 real Wired articles; SemiWiki login footer on every thread including real ones; Foreign Affairs serves the same subscribe footer on full articles and on teasers (site chrome). Sixth independent confirmation (Institutional): a 3288-word galaxy.com article ABOUT rate limits matched the rate-limit regex. A naive "JSON starts-with-`{`" rule would have discarded 4 real Carnegie articles (371–2747 words) over a JSON-LD header; a 150-word paywall cutoff would have discarded real Gavekal teasers (90–140 words). Both rebuilt as density/length rules from real data. ⚠ **Marker lists rot.** Institutional found 6 blocking mechanisms; the 6th matches NO marker and was caught only by the word floor. A length-only backstop is mandatory INDEPENDENT of the marker list.

**RULE 3 — In KNOWLEDGE extraction, the AGENT writes the card, not the script.** The write instruction lives in `routines/routine_*.md`; no code can intercept the agent's Write tool. Therefore **refusing to issue the prompt is the only point of control available to code.** `cmd_prompt()` (or equivalent) MUST check card status and refuse on finalized/quarantined without `--force`. `finalize`/`heal` run *after* the card exists — too late. ⚠ The worklist's dedup (`_global_done_ids`) protects `worklist`, NOT `prompt` — `cmd_prompt` is a separate entry point callable with an arbitrary id. "Worklist dedup covers us" is FALSE.

**RULE 4 — Out-of-git data (`*-history/`) has no right to error.** Live `raw/` is tracked and was restorable from git; `history/` is not. Any history write path requires BOTH: fetch-time dedup (`already_known()` gates the download, no `--force`) AND prompt-time clobber-guard. Dropbox versioning covers all history dirs (owner-confirmed) — a required condition, not a convenience, and it has a retention limit, so the guards are the real defense. **Backfill machinery lives in the repo; `history/` data never does.**

**RULE 5 — The unit of write determines the shape of the guard. Do not port, redesign.** KNOWLEDGE streams write one file per article, so a per-article word-count ratio guard sees degradation. Institutional writes AGGREGATES (`raw/<date>/articles.json` = the whole run). If a re-run fails to re-open a URL, the record is ABSENT from the new set — the ratio guard has nothing to compare and the article vanishes silently. By file shape this is Bug 1 (aggregate) though the symptom reads as Bug 3. Correct fix for aggregates: **union by URL within the date dir**, tiebreak by word_count among records passing the floor. Non-date-scoped dirs (`latest/`) are NEVER merged into (accumulates forever) — they are REBUILT from the date dir.

**RULE 6 — Union without a status-gate makes the dataset WORSE.** Block pages persist for weeks (WisdomTree: Cloudflare, 4 collections running; Carnegie: CloudFront 403 for five weeks). For such URLs no good version exists in ANY run. A plain overwrite drops them; a union PRESERVES them — permanently enshrining junk as canon. The status-gate is a hard dependency, not a preference: it ships before or with any union. Anyone porting union checks this FIRST.

**RULE 7 — Code always ships via `claude/**` → `merge-to-main.yml`. Direct commits to main are reserved for the runner's DATA commits** (its `GITHUB_TOKEN` does not trigger merge-to-main). This asymmetry — data direct, code via branch — was never written down and reads as permission to commit code straight to main. A multi-worktree repo structurally invites the error: an agent working in the shared root-checkout (branch `main`) commits where it is *looking*, not where it *should*. Institutional's write-safety fix (`457e0520`) sat unpushed for hours this way while the buggy collector kept running weekly in production. **Failure form, seen three times in one audit: reading or acting in the wrong place — not the place that mattered** (also: reading `timeout-minutes` at HEAD instead of the run's `head_sha`). Corollary: to realign a local branch use `git merge --ff-only origin/main`, never `git reset --hard` — ff-only refuses on unexpected divergence instead of silently discarding local work. Corollary: **dead code comes back to life.** `MIN_TEXT_LEN` survives as a declared "legacy backstop" constant with zero references; `_card_status()` existed and was never called in three streams — that was the hole. Delete dead guards; do not leave them lying next to the door.

**RULE 8 — Every extraction worklist needs a structural junk pre-filter, and skips must be visible.** `record_id` = URL hash, so a record collected BEFORE a source is fixed carries a URL family the new collect path will NEVER overwrite — no collision ever occurs. Such records are not "awaiting overwrite"; they are ORPHANED and resurface in the extraction worklist FOREVER, blocking the run. (Concepts daily 2026-07-10: 15 worklisted, 15 junk, 0 cards — a whole day's collection lost.) Root cause: Concepts' BACKFILL worklist had a structural filter (`_worklist_drop`: word-floor + junk-path); the DAILY worklist had NONE — the filter was cloned to the wrong place. Requirement: every stream's extraction worklist MUST carry a structural junk pre-filter (word-floor + bot-page / junk-path / archive-listing signals; theme-agnostic; SKIP not delete), AND junk-skips MUST be visible in the health check, never silent — otherwise a source quietly emitting only junk (Damodaran did for ~3 weeks) blocks the routine every morning unnoticed. A PURGE path is also needed for already-orphaned junk (Concepts had none; 20 files removed by hand via `git rm`).

**RULE 9 — Shared-IP streams: the guard must protect the module that can't protect itself, and must detect soft throttling, not just the hard wall.** YouTube daily collection and history backfill share one residential IP (~320–400 yt-dlp calls/day; zero incidents on record). Two structural gaps, each worse than the raw numbers: (1) the emergency BACKOFF marker was read ONLY by the backfill wrapper — daily collection ignored it and ran at noon regardless, hitting the same irritated IP after a backfill abort. The guard protected the module that already stops itself, not the live stream. Now both wrappers honor the shared `youtube-history/_state/BACKOFF` (fresh <24h → daily run SKIPS; stale >24h self-cleaned). (2) The hard wall (429) is visible — backfill self-halts — but soft shadow-throttling before it is not, and the daily collector had NO inter-request pauses at all. Added `scripts/_ip_health.sh` (sourced by both wrappers, DRY): per-run empty/partial-transcript % + non-benign metadata-unavailable rate, WARN at ≥30% one run OR ≥15% two runs OR non-benign ≥3. **FAIL-LOUD WHEN BLIND:** if the parser reads 0 attempts but the summary shows processed videos, it emits BLIND-WARN ("log format may have changed, monitor is blind") rather than reporting a clean 0% — a monitor that cannot see must say so (cf. Institutional's `status_rejected`, cf. dead `_card_status`). Frequency held at 2/day; a cautious 3/day trial only after a week of clean `[ip-health]` logs — no longer a blind jump. Bottleneck is channel depth (self-draining), not backfill.

**Anti-false-alarm notes:**
- Duplicate `finalize` entries in a runlog are NOT proof of damage. `_finalize_one` is deterministic; a re-invoked unchanged batch double-logs byte-identical output. Compare per-record insight/verified/quote counts between occurrences before concluding a clobber.
- **`record_id` collides across source slugs** (one article reachable from two listings). Files are keyed `<slug>/<record_id>`. Any state/dedup keyed on `record_id` ALONE will silently merge two cards. ⚠ Applies to the future Supabase load: primary key must be `(source_slug, record_id)`, not `record_id`.
- YouTube: cards with zero insights are intentionally excluded from the digest, so "episodes in report < cards for that date" can be legitimate — not a loss.

---

## DASHBOARD (presentation)

Generated by `scripts/update_dashboard.py` from `reports/*.html`, config in `REPORT_TYPES` (keyed by report filename prefix = the data link; `label` = display name; `color`, `icon`, `group` per stream). Sections: **Today's Intelligence** (PULSE / RESEARCH groups, each with Latest + Previous) and **Archive** (same subgroups, accordion + counts).

**Color logic:** hue = rhythm group, tone = stream. PULSE = blue family (#6366F1 / #3B82F6 / #0EA5E9 / #06B6D4); RESEARCH = amber family (#F59E0B Twitter Banks / #D97706 Bank PDF / #EA580C Institutional). Applied to card left-border and archive dot.

**Graceful degradation:** a stream with no report file renders nothing (e.g. Shitpost while paused), never errors. Unknown future types fall back to `DEFAULT_GROUP`.

Adding a stream = one `REPORT_TYPES` line with its `group`; no markup changes.

---

## KNOWLEDGE ARCHITECTURE (design — not built)

Two layers for finding connections; not a rigid tree.

**Layer 1 — Ontology (deterministic, hand-built, ~50–100 rules):** known cause-effect chains (oil↑→inflation↑→rates↑; Fed↑→growth↓→credit↓; AI capex↑→semis↑; Hormuz→oil shock; aggregate guidance cuts→growth slowdown; etc.). New flow item matching a trigger auto-surfaces related items — no LLM.

**Layer 2 — Embeddings (emergent, pgvector):** every quality-passing item gets a vector; connections emerge from semantic proximity, not predefined categories (e.g. "consumer stocks as post-bubble contrarian play" links to labor-AI, tech-positioning, Nifty-Fifty parallels with no causal rule).

**Light tags (~8, human browsing only):** Macro, Energy, Tech, Crypto, Geopolitics, Positioning, AI, Society. Not a filter — all content still appears in reports.

**Why not rigid ontology:** predefined trees create blind spots; the edge is connecting dots that don't fit existing categories.

---

## KNOWLEDGE EXECUTION MODEL (added Jun-07 — YouTube built; template for the track)

The KNOWLEDGE track diverges from the FLOW execution model. FLOW = cloud (GitHub Actions) collection + cloud API tiers. The first built KNOWLEDGE stream (YouTube / Podcasts) established a different, **local + subscription** pattern. This is the reference template for Concepts / Technology / Society (the *pattern* transfers; the collection *mechanism* may differ — YouTube uses yt-dlp transcripts, Concepts/Tech/Society use Playwright over sites).

**Collection — LOCAL, deterministic, no LLM:**
- Runs on the Mac via `launchd` (YouTube: 12:00 daily), not GitHub Actions. yt-dlp + subtitles; no LLM, no quota.
- Safeguards: per-run caps; window-based collection self-heals missed days.
- **IP is the main risk** for transcript sources — conservative throttling, hard-stop on any 429 / bot-check / consent-wall, no personal-account cookies.

**Extraction — MANUAL, on the Opus Max subscription (not API):**
- Triggered by the user in Claude Code when quota is fresh; follows a single routine file.
- **Routine convention:** `routines/routine_*.md` (e.g. `routine_youtube.md`). Quality is tuned by editing this one file — it is the contract the in-code routine follows.
- **Entity-presence guard:** each extracted record's entities are checked against the raw transcript; <~40% presence → **quarantine** (non-destructive, excluded from output, surfaced in the run report). Catches subagent hallucination (a whole episode invented from a neighbour). Norm = 0 quarantined.
- One-transcript-per-subagent rule; verbatim quote + timestamp verification, non-destructive.

**Storage — split by recency:**
- **Daily stream** → GitHub as usual: `raw/`, `processed/`, dated `reports/*.html`, dashboard. Same bus as FLOW.
- **Deep history** (backfill, pre-current): separate local code path, separate folder **OUTSIDE the git repo, never committed/pushed**. Backup = Dropbox; raw is re-collectable, processed re-extractable. Destined for the future Supabase load. JSON-only — no reports, no dashboard — except a one-time dated-HTML render for the slice with upload-date ≥ Apr 1 2026 (so the visible archive is continuous from April). **YouTube backfill status (Jun-27):** active via a dedicated launchd agent `com.marketintel.youtube-backfill` (Hour 16, local) — ~1116 processed episodes in `youtube-history/`, roster_cursor 32/77, oldest episode 2025-02-03 (a channel is marked complete when its playlist is exhausted, not at a fixed date floor).

**Resolved (Jun-17) — collection mechanism is chosen per IP-risk, not local-by-default:** transcript sources (YouTube) collect **locally** (transcript IP-risk); Playwright-over-public-sites (Concepts, confirmed live; Technology building; Society to follow) collect in the **cloud** (GitHub Actions), same as Institutional. Extraction-on-subscription + routine + guard + history-outside-repo carry over either way. The local path stays reserved for any future source with IP-risk.

**Flow triage — track-wide (decided Jun-17).** KNOWLEDGE sources carry a depth type (Deep / Flow / Data) from curation. Triage applies only to **Flow** (high-volume news); **Deep** = extract-all; **Data** module not built — Concepts collects Data-typed sources as normal articles (no routing). Flow is triaged **deterministically in the collector, before the worklist** (not inside extraction, no LLM):
- items whose title+body match `config/knowledge_watchlist.json` (tickers / companies / sectors / themes, owner-maintained) → worklisted up to a generous per-source cap;
- a small recency-capped **discovery sample** of the freshest *non-matching* items per source per run is also kept, so cross-domain novelty is not blind-spotted (the owner's edge);
- **firehose** sources (e.g. ArXiv cs.AI / cs.LG, Hacker News; flagged in source config) require a watchlist match (no discovery sample) + a tight cap.
Caps are tunable knobs. No LLM in triage — semantic triage is deferred to the future embeddings layer. The watchlist is **shared across KNOWLEDGE Flow streams** (Technology, Society); seed from portfolio holdings + `config/twitter_watchlist.json` + the 8 light tags; it may later merge with the Discovery Loop WATCH_AGENDA. Concepts has no Flow; 50 active / 28 parked (78 curated), collector honors collect:false — so it exercises none of this triage. (Society config coverage: 47 active / 20 parked, 67 sources.)

**AS-BUILT CORRECTION (Jun-27 / Jun-29) — neither Technology NOR Society engages the track-wide triage above.** The watchlist-gate + recency-cap + discovery-sample mechanism described above was the Jun-17 *design decision*, but it is **NOT what got built.** Both shipped Flow streams run with `WATCHLIST_GATE=False` (durable extract-all): Deep sources extract-all with a recency window; perishable news Flow is parked → Newsletters (`collect:false`); the remaining Flow sources take a small per-source recency cap (N=25). No watchlist-gate, no discovery-sample. The watchlist + discovery-sample code **exists in the collector but is OFF** for both streams — retained as a future option, not the as-built behaviour. (Technology Flow-capped sources: MIT TR, Ars, Wired, NVIDIA Dev, InfoQ.) This supersedes "Society enables it by flipping the flag."

---

## CHART / IMAGE UNDERSTANDING (design)

Collection saves image CDN URLs (no files) → vision model (Sonnet) returns description + key numbers + trends → stored in chart_data → original URL preserved for display. Extracted numbers can feed own charts (Recharts/D3). Critical for bank-research screenshots and data charts.

---

## SYNTHESIS (designed, not built)

**SHIFTS (every 2 weeks, Opus):** flow reports + knowledge queries + ontology activations → emerging clusters, cross-domain connections, narrative evolution, weak signals, source divergence, contrarian detection → SHIFTS report. Needs 2+ weeks of accumulated multi-source data.

**Investment Committee (on-demand, multi-frontier):** deterministic pre-processing (portfolio, risk rules, Haiku pre-screen) → Opus + o3 + Gemini debate (devil's advocate, scenarios) → deterministic validation + decision journal + thesis-monitoring triggers.

**Promote mechanism:** user saves a flow item to knowledge with a one-line annotation → embedded, searchable, future near-neighbors auto-flagged.

---

## MONITORING

- **Phase 1 — freshness gate: built / live.** Flags stale streams.
- Phase 2 — health strip (per-stream status): backlog.
- Phase 3 — single alert channel: backlog.
(Detail in repo `docs/BACKLOG.md`.)

---

## BUILD ORDER

Status per item lives in **MODULE_REGISTRY.md** — this is the sequence only.

1. **FLOW track** — Twitter (3 routes), Twitter Banks, Institutional, Bank PDF live; Newsletters live on interim (full rebuild pending); Earnings pending. ← largely done
2. **Storage migration** — Supabase project, schema, collectors → Supabase API (keep Pages for reports).
3. **Knowledge infrastructure** — ontology rules, pgvector, embedding pipeline.
4. **Knowledge track + Earnings** — YouTube **(built / live, Jun-07)**, Concepts **(built / live, Jun-17)**, Technology **(built / live, Jun-27)**, Society **(built / live, Jun-29; first auto-collect Jul-05)** — all four KNOWLEDGE streams live; Earnings pending.
5. **Synthesis** — SHIFTS, queryable knowledge base, promote, "interesting detector".
6. **Investment Committee** — multi-frontier integration, rules, decision journal.

---

## INFRASTRUCTURE

```
market-intelligence/
├── .github/workflows/   # collection crons + merge-to-main.yml
├── scripts/             # collectors + update_dashboard.py (generator)
├── config/              # watchlists, source lists, classification
├── reports/             # generated HTML reports (data bus → Pages)
├── docs/                # ARCHITECTURE, MODULE_REGISTRY, BACKLOG
└── index.html           # auto-generated dashboard (CI overwrites)
```

Cloud: GitHub Actions + Pages (free), Anthropic Max plan, GetXAPI (~$2/mo), Haiku/DeepSeek + Sonnet APIs. Supabase when migrated.

---

## KEY DECISIONS

Carried from v3: two-track architecture; deterministic-first; three model tiers; Supabase target; two-layer knowledge (ontology + embeddings, no rigid tree); source-based separate reports; loose tags; promote mechanism; chart vision; cloud-only; Investments module separate; Earnings via Haiku.

**New in v4:**
1. **Twitter split into three routes** (Alpha/Opus, Data/Sonnet, Shitpost/Haiku) — not one report.
2. **Twitter Banks = author-signal via relayer accounts** — keyword search abandoned.
3. **Institutional Research is live** — direct bank/AM site scraping (was "future separate project").
4. **Bank PDF — new deterministic, no-LLM module** (Research PDF Finder), sibling to Institutional.
5. **Dashboard rhythm grouping** — FLOW split into PULSE / RESEARCH by cadence; config-driven; color = rhythm.
6. **Stream renames** — Bank Research→Twitter Banks, Research→Newsletters & News, Research PDFs→Bank PDF (display labels only; data keys unchanged).
7. **Three-layer doc model** (see below) — status moved out of this doc into the registry.

**Updated Jun-07 (KNOWLEDGE execution, from YouTube buildout):**
8. **KNOWLEDGE collection can be LOCAL** (launchd, no LLM) — the track is no longer cloud-only. The v3/v4 "cloud-only" stance now applies to **FLOW**; KNOWLEDGE collection may run on the Mac (no-LLM scripts run fine locally; transcript IP-risk favours a controlled local path).
9. **KNOWLEDGE extraction on the Opus Max subscription** (manual, Claude Code) — tier routing deferred to a future API phase; today everything is Opus.
10. **KNOWLEDGE deep-history data lives OUTSIDE the git repo** (never GitHub), backed up on Dropbox, destined for Supabase. Daily stream still goes to GitHub.
11. **Routine convention `routines/routine_*.md`** — one file per stream, edited to tune extraction quality.
12. **Entity-presence guard** (quarantine) — standard defence against extraction hallucination for the KNOWLEDGE track.

**Updated Jun-17 (KNOWLEDGE collection + triage):**
13. **KNOWLEDGE collection is decided per IP-risk, not local-by-default** — transcript sources local (YouTube); Playwright-over-public-sites cloud (Concepts live, Technology building, Society to follow), like Institutional.
14. **Track-wide Flow triage** — deterministic in the collector: watchlist-gate (shared `config/knowledge_watchlist.json`) + recency-cap + a small discovery-sample of non-matching items (preserves novelty); firehose sources gated harder. No LLM in triage. **⚠️ As-built deviation (Jun-27/29): this is NOT what shipped.** Technology AND Society run `WATCHLIST_GATE=False` (durable extract-all + recency, perishable Flow parked → Newsletters, cap N=25); the watchlist/discovery-sample code is present but OFF. See "AS-BUILT CORRECTION" in KNOWLEDGE EXECUTION MODEL.

---

## DOC MODEL

1. **ARCHITECTURE** (this file) — design. Update on an architectural event.
2. **MODULE_REGISTRY.md** — status (one line per module/branch). Update the moment a module is born or changes state.
3. **CONTEXT_*.md** — detailed per-chat session log.
Plus a **weekly reconcile** in the Architecture chat: read the week's CONTEXT files → fold real arch changes here → update the registry.

**Coordination:** one chat owns one routine (Twitter chat owns the watchlist/collection; Institutional its own; etc.). The Architecture chat designs and reconciles — it does not build the per-routine collectors.
