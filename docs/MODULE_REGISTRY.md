# MODULE REGISTRY — Market Intelligence
## Единственная страница «что вообще есть». Last reconciled: 2026-06-29 (Mon)

Тонкий слой статуса. НЕ описывает дизайн (он в ARCHITECTURE) и НЕ дублирует детали
(они в CONTEXT-файлах). Одна строка на модуль/ветку.

**Three-layer model:**
1. **ARCHITECTURE** — дизайн, принципы, тиры, build order. Обновлять ПО СОБЫТИЮ (арх-решение).
2. **MODULE REGISTRY** (этот файл) — статус. Обновлять В МОМЕНТ рождения модуля / смены состояния.
3. **CONTEXT_*.md** — детальный лог на чат. Уже ведётся.

**Недельный ритуал (в Architecture-чате):** прочитать CONTEXT за неделю → арх-изменения свернуть
в ARCHITECTURE → обновить этот реестр → сверить дату выше.

**States:** `live` · `trial` · `building` · `paused` · `designed` (бриф готов) · `not started`

Repo: github.com/eric0205market-bit/market-intelligence · Pages: eric0205market-bit.github.io/market-intelligence

---

## FLOW (скоропортящееся)

| Модуль | State | Owner-chat | Branch | Cadence / Model | Note |
|---|---|---|---|---|---|
| Twitter — Alpha | live | Twitter | collect→main; reports→claude/twitter-report | 2×/день (05:20/17:20 UTC via cron-job.org) · Opus | v7 editorial+verification |
| Twitter — Data | live | Twitter | как выше | 2×/день · Sonnet | catalog + data_points |
| Twitter — Shitpost | live | Twitter | внутри collect-twitter.yml | 2×/день · Haiku | Собирает, под наблюдением. Переделка маршрута планируется (как и остальные Twitter-роутины) |
| Twitter — Bank Research | trial | Twitter | внутри collect-twitter.yml | Wed+Sun 06:45 UTC · Sonnet | Собирает, 7 relayer-аккаунтов, author-signal. Решение ~сер. июня: оставить distinct view или влить в Data |
| Institutional Research | live | Institutional | claude/institutional | Вс 06:00 collect / 09:00 routine · Opus | ~101 сайт банков/AM, Playwright. Полностью автоматизирован |
| Newsletters & News (ex-Substack) | live (interim) | — (нужен владелец-чат) | daily | Gmail Cloud Routine, живой ~2 мес (минус: Gmail режет графики). **Full non-email версия (Playwright/прямой сбор) — pending.** Intake: 23 из Technology (22 G3 + The Information) + крипто-пул (Decrypt…) + платные (Bloomberg/Barron's, объём по ToS). Новая сборка — нужен отдельный чат |
| Bank PDF (Research PDF Finder) | live | — | main | еженедельно · НЕТ LLM | Первый отчёт 31 мая (commit 297d412). На дашборде в группе RESEARCH (#D97706). Sibling к Institutional |
| Earnings Calls | not started | — | — | quarterly bulk · Haiku | ~500–1000 компаний; в ARCHITECTURE, не начат |

## KNOWLEDGE (накопительное)

| Модуль | State | Owner-chat | Cadence | Note |
|---|---|---|---|---|
| YouTube / Podcasts | live | YouTube/Podcasts | daily collect + manual extract | **77 каналов**, дневной поток живой. СБОР: yt-dlp+субтитры, **ЛОКАЛЬНО** (launchd 12:00, без LLM/квоты, NOT GitHub Actions). ИЗВЛЕЧЕНИЕ: вручную в Claude Code на **Opus-подписке** (НЕ API), рубрик `routines/routine_youtube.md` + entity-guard (карантин). Дневные raw/processed/reports → GitHub. **ИСТОРИЧЕСКИЙ БЭКФИЛЛ: активен** — ~1116 processed-эпизодов в youtube-history/ (вне репо, на родителе репо), roster_cursor 32/77, отдельный launchd-агент `com.marketintel.youtube-backfill` (Hour 16, локально). Фронт: oldest эпизод 2025-02-03; 5 каналов completed (плейлист исчерпан, не до 2025-01), из них glassnode = complete-empty (0 транскриптов ≥ min-duration). Дневной поток: ~451 карточек в processed/youtube, reports по 2026-06-27. Задаёт шаблон для Concepts/Technology/Society. **Write-safety audit (Jul-10):** publish bugs 1–2 existed → fixed (union within date + shrink-guard + legacy fallback, fail-closed without --force). Bug 3 structurally absent (dedup before fetch, no --force flag). Bug 4 (cmd_prompt) existed → fixed (bb3162fa; _card_status() was dead code). Zero losses across all 32 reports verified. In-flight race on a not-yet-extracted id consciously left open (no data loss — both agents write a fresh extraction of the same transcript). All 5 backfill machinery files tracked; youtube-history/ gitignored. |
| Concepts | live (Jun-17) | Concepts | daily | Сбор — Playwright, **CLOUD (GitHub Actions), collection-only cron daily 10:00 UTC** (`0 10 * * *`), без LLM (recency-gate `--days`, без watchlist); извлечение вручную на Opus-подписке, `routines/routine_concepts.md` + entity-guard. Дневные raw/processed/reports → GitHub (группа KNOWLEDGE), поток живой. Нет Flow. **50 active / 28 parked (78 curated)**; active 48 Deep + 2 Data, parked 25 Deep + 3 Data (post Jun-27 relocation; NBER parked → Science). **10 IR/foreign-policy think-tanks relocated → Society (Jun-27 taxonomy):** 9 deactivated here (Brookings, RAND, CFR, Carnegie, Atlantic Council, CSIS, Hudson, German Marshall Fund, IISS) + Stimson (already parked). **Chatham House NOT relocated — single-homed in Concepts (RSS).** Sources retained in file (collect:false, non-destructive). Collector honors collect:false (deferred). Backfill (Jan-2025+) JSON-only in concepts-history/ (outside git) on **Sonnet** — **COMPLETE**: 2608 finalized + 1 quarantined, worklist empty (340 raw legitimately excluded by length/genre filters). **Daily extraction remains Opus.** **Write-safety guards live:** no-degrade ratio + length-gated teaser detector (collector), union + shrink-guard (publish), cmd_prompt clobber-guard (backfill extraction). Losses: 18 cards @2026-06-25 (publish bug, recovered); 1 degraded raw of 501 (reader comment, restored). Society/Science taxonomy РЕШЕНА: 10 IR think-tanks → Society (Jun-27), добавлены в society_sources.json. Counts AUTO-GENERATED from collect flags (scripts/concepts_source_tally.py; --check fails on drift; health check fails loudly on hand-edit). The old hand-written header drifted — there was never a '+offset' convention. ⚠ **50 ≠ 45. Do NOT reconcile down.** 50 = active-by-flag; 45 = sources the collector ATTEMPTS (50 minus 5 paywalled, also skipped). Both correct, different questions. Chatham House single-homed in Concepts (RSS via cloud cron since 2026-07-08); NOT residential-recoverable. Daily stream healthy (a16z fixed; ARK, ECB, Hussman, Damodaran, Chatham recovered). Backlog in docs/BACKLOG.md |
| Technology | live | Technology | daily 10:00 UTC | Cloud cron (GitHub Actions, Playwright) collection-only --days 3 + ручное извлечение (routine_technology.md, Remote, Opus-подписка). **67 = 32 active + 35 parked.** Active = 27 Deep (extract-all + recency) + 5 Flow-capped (MIT TR, Ars, Wired, NVIDIA Dev, InfoQ; cap N=25). Parked 35: 23 → Newsletters (22 G3 + The Information), 4 adapter-backlog (arXiv×2, Papers With Code, HN), 4 RSS/SPA/cloud-IP revisit, 3 landing revisit-or-drop, 1 drop (AnandTech). **Watchlist OFF** (WATCHLIST_GATE=False, durable extract-all). Reports live с 2026-06-22. config — источник правды. **Write-safety guards live** (same three as Concepts: no-degrade+length-gated-teaser collector, union+shrink-guard publish, cmd_prompt clobber-guard). **Backfill machinery now in repo** (backfill_technology_history.py + technology_backfill_extract.py, b3e0d5b2 + wrapper/plist); phase-2 draining ~1695/~2780 in technology-history/ (outside git), on Sonnet. Losses: 41 cards @2026-06-25 (publish bug, recovered); 1 degraded raw of 936 (SemiWiki, restored). Bonus fix: is_junk() login-wall filter was marker-gated and silently discarded real articles — now length-gated. |
| Society | live | Society | Sun 10:00 UTC collect (cron) / manual extract · Opus | Клон Technology, **WEEKLY**. Cloud collect (`collect-society.yml`, cron `0 10 * * 0`); извлечение вручную `routines/routine_society.md` + entity-guard. 67 sources = 47 active + 20 parked. Первый авто-сбор Sun 2026-07-05. Включает **10** IR think-tanks relocated from Concepts (Jun-27, collect:false в concepts — нет двойного сбора; Chatham House removed from Society, single-homed in Concepts). Flow-триаж как в Technology: WATCHLIST_GATE=False (durable extract-all + recency, cap N=25), watchlist/discovery-sample OFF. Society history seed: brookings_institution (104) + carnegie_endowment (28) moved from concepts-history/ → society-history/ (outside git). Brookings exists nowhere else — Society never collected it; historical depth (Jan-2025+) awaiting Society's own backfill. **Write-safety (Jul-10):** publish bugs fixed (0 losses — cumulative publish). Bug 3 fixed (1 of 524, Foreign Affairs teaser, restored). Bug 4 prospective — backfill NOT started. **DECISION (owner, 2026-07-09): build Society backfill with BOTH guards in place BEFORE first run; canary must DEMONSTRATE both guards firing, not merely their presence.** Source policy: no heroics — JS-SPA / bot-block / no pagination / teasers → skip-log and move on; workarounds (RSS/JS-render/residential) are a shared backlog capability, not built here. Start from the 132 already-collected records (brookings 104 + carnegie 28) in society-history/. No cron; does not touch the live weekly stream. |

## SYNTHESIS

| Модуль | State | Owner-chat | Cadence | Note |
|---|---|---|---|---|
| SHIFTS | designed | свой чат | каждые 2 нед · Opus | Нужно 2+ нед накопленных данных |
| Investment Committee | designed | свой чат | on-demand · multi-frontier | Opus+o3+Gemini + детерминир. правила |
| Discovery Layer | designed | Discovery-чат | — | Design fixed, build not started. Спека: CONTEXT_Discovery_Layer_Jul06 + BUILD_PLAN_Discovery_Jul06 (supersedes CONTEXT_Discovery_Loop_Jun10). Не модуль — слой поверх storage/embeddings/ontology/SHIFTS/Committee из build order |

## INFRA / сквозное

| Компонент | State | Note |
|---|---|---|
| Storage: GitHub-as-bus | live | Текущая шина данных: коллекторы коммитят в main, Pages раздаёт |
| Storage: Supabase | not started | Цель из ARCHITECTURE_v3 (Postgres + pgvector). Миграция не начиналась |
| Ontology (causal rules) | not started | ~50–100 правил cause-effect |
| Embeddings (pgvector) | not started | Зависит от Supabase |
| Monitoring | phase 1 done | Phase 1 = freshness gate (live). Phase 2 = health-strip. Phase 3 = single alert channel. (docs/BACKLOG.md) |

## ADJACENT (вне MI-пайплайна)

| Модуль | State | Note |
|---|---|---|
| Correlation Thermostat | live | Отдельный аналитический инструмент (COR1M сигнал). Ближе к Macro Model. update_dashboard.py + html |

---

## COORDINATION RULES
- **Один чат — один владелец.** Twitter (watchlist/коллекция) трогает ТОЛЬКО Twitter-чат. Institutional — только свой.
- **BUILD каждой роутины — в её чате.** Этот (Architecture) чат проектирует и сверяет, не строит Twitter/Institutional.
- **Новый модуль/ветка родился → сразу строка сюда** (а не «потом на недельной сверке»).

## OPEN ITEMS (для недельной сверки)
- Newsletters & News (ex-Substack) — live на Gmail-интериме (~2 мес). Нужен владелец-чат + full non-email rebuild (Playwright). Intake: 23 (22 G3 + The Information) + крипто + платные (ToS).
- Bank Research trial — решение ~середина июня (distinct view vs влить в Data).
- Twitter-роутины (все) — в режиме collect-and-monitor, запланирована переделка маршрутов; TBD когда и как.
- YouTube хвост: DOAC handle в `config/youtube_sources_full.json` всё ещё @TheDiaryOfACEOClips (клип-канал, не проходит 25-мин фильтр) — нужен основной канал DOAC. Конфиг-фикс, полоса YouTube-чата.
- KNOWLEDGE execution model — **ЗАКРЫТО (РЕШЕНО; все 4 потока live):** облако (GitHub Actions, Playwright) + ручное извлечение на Opus-подписке; YouTube локальный (transcript-IP). As-built Flow-триаж (WATCHLIST_GATE=False для Technology И Society; watchlist/discovery-sample OFF) — в ARCHITECTURE_v4 «KNOWLEDGE EXECUTION MODEL».
- Backlog (track-wide): RSS/JS-render reader — вернёт adapter/SPA/cloud-IP источники (arXiv×2, HN, Papers With Code, Import AI, Derek Lowe, S&P Global, WikiChip); residential-supplement для cloud-IP-blocked.
- **SCIENCE line reserved (future):** nber_working_papers + ssrn parked with shared future_line:"Science" tag (revive together). PIIE, IMF Blog, WEF stay ACTIVE in Concepts (macro/policy, not academic preprints).
- **publish_*.py data-loss bugs (cross-stream) — RESOLVED (Jul-10).** Fixed across all four streams: Concepts (18 cards @2026-06-25 recovered), Technology (41 cards @2026-06-25 recovered), Society (0 losses — cumulative publish), YouTube (0 losses across 32 reports verified). Fix: union by record_id + shrink-guard tripwire in every publish_*.py + YouTube equivalent; plus raw-record no-degrade guard (Bug 3) and cmd_prompt clobber-guard (Bug 4). Full rules → WRITE SAFETY in ARCHITECTURE_v4.
- **Shared module vs three copies (4c) — OPEN, now confirmed by a 4th case.** All four bugs propagated because publish_*.py / collect_*.py / *_backfill_extract.py are cloned between streams. Recommendation: extract the guards into a shared module AFTER the fires are out. Until then, every new bug will replicate the same way.
- **Audit publish_institutional.py + Institutional collector for bugs 1–3** (same ancestor). Institutional has no owner chat — needs one, or a read-only audit.
- **Shared capabilities to port from Concepts:** (1) RSS fetch route (fetch_mode:"rss", plain HTTP, bypasses bot-blocks — probe RSS BEFORE building browser/residential workarounds; solved Damodaran, Chatham House); (2) fresh_context_per_article (Cloudflare flags context after index visit; recovered ARK Invest, 13 articles); (3) reusable residential daily path (--residential gate + residential_only:true; each stream ports the gate into its own collector; only iea_oil_market_report still needs it — SUPERSEDES old 'no per-stream residential path' note); (4) health check (scripts/concepts_health_check.py — days-since-last-card + consecutive-zero-kept streak; a16z was dead 2 weeks unnoticed after a 404/site restructure — worth generalizing across streams).
- **Model discipline:** daily extraction = Opus (all streams). History backfills = Sonnet (Opus ~5x quota drain on rubric-bound extraction; Concepts lesson).
- ARCHITECTURE_v3.md устарел в 4 местах (Bank Research, Twitter split, Storage, Substack) — свернуть в v4 при следующем арх-событии, не срочно.
