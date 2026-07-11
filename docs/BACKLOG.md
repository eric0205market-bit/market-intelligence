## Backlog — Monitoring / Alerting (deferred, decided 2026-05-29, Twitter chat)
PHASE 1 (done): Freshness gate — routines abort and publish nothing if collection data is stale (scripts/check_freshness.py + STEP 0 in each routine).

- PHASE 2 — Central health panel (build when several routines exist; do NOT build per-routine banners). Each routine writes ONE status line (ok / stale / error + run time + data collected_at) to a shared status file (e.g. data/status/routines.json). Dashboard renders one compact health strip: green/red dot per routine, so all routine health is visible at a glance in one place. Adding a routine = it writes its status line; panel shows it automatically (~2 min status-writer per routine). Don't build until the schema is informed by a few real routines.
- PHASE 3 — Single alert channel. One notification (email/Telegram) that fires ONLY when a routine goes red, built on top of the Phase 2 status file, so no manual checking is needed.

Rationale: per-routine banners = clutter and don't scale; relying on report dates across many routines = silent misses. One status file -> one panel -> one alert.

## KNOWLEDGE shared-capability backlog → ARCHITECTURE CHAT (logged 2026-06-16, Concepts canary)
These are SHARED across the KNOWLEDGE track (Concepts/Technology/Society hit the same sources). Decide once in the Architecture chat — do NOT build per-source hacks into Concepts.

- **Residential-collection path for cloud-IP-blocked sources — reusable path now exists.** Some sources collect fine from a residential IP but the GitHub Actions IP range is blocked (~2 anchors). A reusable `--residential` gate + `residential_only:true` is available; each stream ports the gate into its own collector — this **SUPERSEDES the old "shared-supplement only / do NOT build a per-stream residential path" guidance.** **Chatham House — RESOLVED via RSS** (fetch_mode:rss, `path/83/feed.xml`, full-body items, works from the cloud cron on any IP; no residential path needed — removed from the residential list). Of the original cohort only **IEA Oil Market Report** still needs the residential path. YouTube already collects residentially. (Technology/Society may hit more.)
- **RSS / newsletter ingestion route** for bot-blocked sites (block headless at ANY IP). Concepts dropped, HIGH-VALUE, `revisit_route: rss_or_newsletter`: **McKinsey Global Institute, McKinsey Insights, Citi GPS** — still bot-blocked, **no live RSS found** (probe RSS first per the shared RSS route; none exposed as of Jul-09). Bank-PDF cohort unchanged.
- **JS-render (headed/interaction) collection path** for client-rendered SPAs (static anchor harvest can't reach article links, any IP). Concepts dropped: HIGH-VALUE `revisit_route: rss_or_js_render` — **Bain Insights, Sequoia Arc** (Sequoia has a **working sitemap** — try that before JS-render), **Lux Capital**; lower-priority `js_render` — **Stimson Center**.
- **SSRN — listing fixed, hard Cloudflare block remains.** index_url now points at the ERN category page (55 real `abstract_id` links vs 15 static before), but papers.ssrn.com serves an interactive Cloudflare challenge on every abstract page **even from a completely fresh browser context** (fails cold, first visit; `fresh_context_per_article` does NOT help). Honestly parked (`collect:false`); now **Science-tagged** (`future_line:"Science"` — revive with NBER when the Science line is built).

### Added 2026-06-29 (Society canary + first cloud dispatch) — all Architecture/shared; do NOT build per-source fixes inside any stream
- **Residential / RSS / JS-render path for cloud-IP-blocked sources healthy locally** (extends the three routes above). 6 sources parked, `revisit_route: residential-or-rss`: Society — **aeon, american_enterprise_institute, bruegel, iea_commentaries, african_arguments**; Concepts — **stimson** (chatham_house RESOLVED via RSS 2026-07-08 — removed from this list).
- **Paywalled headline/listing-signal collector** (CONTEXT §4 intent): 8 paywalled Society sources parked — capture title/listing as **agenda signal, NOT body**.
- **Deep-fetch + paywall-detection for truncated bodies:** The Diplomat (~150-word teasers); **FA features, Project Syndicate, Slow Boring, Noahpinion** flagged `paywalled:false` but yield lede-only.
- **Collector article-filter triage:** non-article pages slip through `looks_like_article` (topic-hub / landing / author-archive / product).
- **Collector author-field defects:** Atlantic Council (one author on all UkraineAlert), The Wire China (one author for all), IFS (author = Facebook URL).

### Added 2026-07-10 (write-safety reconcile)
- **society-history/ backfill machinery to build — guards FIRST.** Build the Society backfill with BOTH write-safety guards in place BEFORE the first run: fetch-time dedup (`already_known()`, no `--force`) AND prompt-time `cmd_prompt` clobber-guard. Canary must **DEMONSTRATE both guards firing**, not merely their presence (owner decision 2026-07-09). Start from the 132 already-collected records (brookings 104 + carnegie 28) in `society-history/`. No cron; must not touch the live weekly stream. Source policy: no heroics (JS-SPA / bot-block / no-pagination / teaser → skip-log; workarounds are shared-backlog, not built here).
- **.gitignore:** `concepts-history/` + `technology-history/` added (belt-and-suspenders; these history dirs already live outside the repo at the parent level). History data never enters git; Dropbox versioning is the backup — retention-limited, so the guards are the real defense.
- **Automated purge path for orphaned/immortal junk raw (RULE 8).** `record_id`=URL-hash records the new collect path never overwrites, so they resurface in the worklist forever (the daily worklist filter now SKIPS them but does not remove them). Concepts removed 20 by hand via `git rm`; needs a repeatable purge step, and propagate to all streams.

### Added 2026-07-10 (Institutional write-safety audit)
- **Upstream dedup:** 416 of 435 shared URLs between two runs are EXACT word_count ties — refetch is deterministic in 96% of cases. Don't fetch a URL already in today's raw → ~96% less collector work and no repeat WAF hit (Carnegie's 403 likely provoked by a second pass from the same IP range).
- **Bug 1 publish-side** (union / shrink-guard / `--force`): design decision open — report is prose synthesis, so union-by-record_id does not transfer.
- **`routines/routine_institutional_v1.md`** — dead, referenced by nothing (grep .py/.yml/.md); v2 never existed. Delete (owner: Institutional chat).
- **`MIN_TEXT_LEN=100`** — dead constant kept as a "legacy backstop", zero active references. Delete. (Dead code comes back to life: `_card_status()` was dead in three streams and that was the hole.)
- **`LOOKBACK_DAYS=7`** is the script default on manual run without `--days` (the workflow always sends `--days 10`). The script docstring shows a flagless invocation → the window silently narrows.
- **Source `iea`:** 22 articles → 0 when the window narrows. Lead on an IP block; no direct evidence.
- **`routines/youtube_extraction_routine.md`** — untracked file from another stream sitting in the worktree.

### Added 2026-07-10 (Society backfill quality debts — collector-side, owner chats)
- **heavy_sitemap recency-sort bug:** `walk_sitemap_recent()` sorts sub-maps by date but NOT articles within them before the cap → "150 newest" are not newest (Brookings recorded 0 of 150, all out-of-window 2013–2024). Affects any heavy_sitemap stream (Concepts/Technology think-tank backfills too).
- **author-widget scrape:** Brookings raw author taken from a "More On / Related" widget, not the byline ("Rebecca Winthrop" wrongly on 3 unrelated articles). speaker is a contract field.
- **nautilus duplicate-URL:** one article under several URL variants, record_id not normalized before dedup → 73 extra fetches. Affects the generic sitemap method.
- **is_junk() in LIVE `collect_society.py`** lacks `/project(s)/`, `/attachment/`, `/tag/`, `/category/`, `/author/` (added only in the backfill-supplement). Non-article enumeration should be rejected at the enumerator, not after extraction (the_point: 87 of 106 were WordPress `/attachment/` pages).
- **RSS port for Society:** Concepts' generic `collect_source_rss()` (fetch_mode:rss + rss_url, plain urllib, works from any cloud IP) NOT ported into `collect_society.py`. 5 cloud-IP-blocked sources (aeon, AEI, bruegel, iea_commentaries, african_arguments) — verify each has a working feed, then port. Closes backlog #1 (residential/RSS) for those five.
- **translated-source false quarantine:** 10 non-English WBB cards quarantined because translated entity names don't match Arabic/French raw — entity-guard non-English limitation, NOT fabrication.

## Conventions

- **Local-Dropbox sync — first AND last action of every session that touches this repo.** Whenever a session touches this repo (read or write), the FIRST action AND the LAST action is to sync the user's working clone at `~/Dropbox (Personal)/Business/InvestTool/market-intelligence/market-intelligence` to `origin/main` — regardless of whether THIS session pushed anything. CI collection commits (collect-twitter, bank-research, merge-to-main, …) advance `origin/main` continuously, so the Dropbox folder can drift behind even when Claude Code did nothing. The Dropbox folder and `origin/main` must never be left divergent.

  **⚠ Bug fixed 2026-07-10 (foreign-stash pop).** `git stash push` creates NO entry when the tree is already clean ("No local changes to save"). An unconditional `git stash pop` afterward then pops a PRE-EXISTING stash belonging to an EARLIER session — silently applying someone else's WIP to the working tree. This happened on 2026-07-10: a clean-tree session popped `stash@{2}` ("user WIP: dashboard bank_research + v1 deletion", created 2026-05-30), which conflicted on `.DS_Store`. Nothing was lost (the session stopped and reported per this convention), but the half-applied foreign WIP had to be unwound by hand. Fix: pop ONLY a stash this session actually pushed.

  **The sequence** (run via `git -C "<that path>"`), from the repo root:
  1. Record the stash top before pushing: `BEFORE=$(git rev-parse -q --verify refs/stash || echo none)`
  2. `git stash push --include-untracked -m "autosync <session> <timestamp>"`
  3. Record it after: `AFTER=$(git rev-parse -q --verify refs/stash || echo none)`
  4. `git fetch origin main` → `git checkout main` → `git pull --rebase origin main`
  5. **Pop ONLY if step 2 created a new entry** (`AFTER != BEFORE`). If the tree was clean, `stash push` creates nothing, `refs/stash` is unchanged, and a blind `git stash pop` would pop a PRE-EXISTING stash from an earlier session — someone else's WIP. Never pop what you did not push.
  6. If popping: verify the top stash is the one you just created (match the `autosync` message) before `git stash pop`.

  ⚠ If `stash pop` conflicts, STOP and report — do not force, do not discard.
  ⚠ Never `git stash drop` or `git stash clear` a stash you did not create. Foreign stashes are the owner's to adjudicate.
  ⚠ `.DS_Store` is macOS junk and is the most common phantom conflict here. It is untracked/ignored; if it blocks a pop, it is safe to discard THAT FILE (not the stash).

## Neil Sethi search-ban (2026-06-15)
@neilksethi was suspended by X (posting BoA charts); restarted as @neilksethinew. Both are wired into collection (BANK_RESEARCH_ACCOUNTS, twitter_watchlist.txt, classification=data) — config is CORRECT. But @neilksethinew returns ZERO via GetXAPI because X search-suppresses restarted-after-suspension accounts: the profile/tweets are live (verified: a "DB: Positioning…" chart, 780 views) but absent from the search index, and collection only uses /twitter/tweet/advanced_search. This is an X-side limitation, NOT a code bug. DECISION: no code change, no new provider. Collection will auto-resume the day X re-indexes him (typically weeks). Until then, bank-research coverage leans on Zaccardi + others and is thinner on Neil's narrative. Do NOT re-diagnose — just check periodically whether neilksethinew tweet count >0 in tweets_bank_research.json. (Note: local GETXAPI_KEY in .env is expired/401 — irrelevant to CI/production, which works.)
