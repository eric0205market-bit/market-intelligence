# MODULE REGISTRY — Market Intelligence
## Единственная страница «что вообще есть». Last reconciled: 2026-06-17 (Tue)

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
| YouTube / Podcasts | live | YouTube/Podcasts | daily collect + manual extract | **77 каналов**, дневной поток живой. СБОР: yt-dlp+субтитры, **ЛОКАЛЬНО** (launchd 12:00, без LLM/квоты, NOT GitHub Actions). ИЗВЛЕЧЕНИЕ: вручную в Claude Code на **Opus-подписке** (НЕ API), рубрик `routines/routine_youtube.md` + entity-guard (карантин). Дневные raw/processed/reports → GitHub. **ИСТОРИЧЕСКИЙ БЭКФИЛЛ: активен** — ~1116 processed-эпизодов в youtube-history/ (вне репо, на родителе репо), roster_cursor 32/77, отдельный launchd-агент `com.marketintel.youtube-backfill` (Hour 16, локально). Фронт: oldest эпизод 2025-02-03; 5 каналов completed (плейлист исчерпан, не до 2025-01), из них glassnode = complete-empty (0 транскриптов ≥ min-duration). Дневной поток: ~451 карточек в processed/youtube, reports по 2026-06-27. Задаёт шаблон для Concepts/Technology/Society |
| Concepts | live (Jun-17) | Concepts | daily | Сбор — Playwright, **CLOUD (GitHub Actions), collection-only cron daily 10:00 UTC** (`0 10 * * *`), без LLM (recency-gate `--days`, без watchlist); извлечение вручную на Opus-подписке, `routines/routine_concepts.md` + entity-guard. Дневные raw/processed/reports → GitHub (группа KNOWLEDGE), поток живой. Нет Flow. 78 curated = 52 active + 26 parked (post Jun-27 relocation). Active 52 = 50 Deep + 2 Data; parked 26 = 23 Deep + 3 Data. **11 IR/foreign-policy think-tanks relocated → Society (Jun-27 taxonomy):** 9 deactivated here (Brookings, RAND, CFR, Carnegie, Atlantic Council, CSIS, Hudson, German Marshall Fund, IISS) + 2 already parked (Stimson, Chatham). Sources retained in file (collect:false, non-destructive). Collector honors collect:false (deferred). Backfill (Jan-2025+) extracting JSON-only in concepts-history/ (outside git, ~295/~2100, ongoing). Society/Science taxonomy РЕШЕНА: 11 IR think-tanks → Society (Jun-27), добавлены в society_sources.json. Backlog in docs/BACKLOG.md |
| Technology | live | Technology | daily 10:00 UTC | Cloud cron (GitHub Actions, Playwright) collection-only --days 3 + ручное извлечение (routine_technology.md, Remote, Opus-подписка). **67 = 32 active + 35 parked.** Active = 27 Deep (extract-all + recency) + 5 Flow-capped (MIT TR, Ars, Wired, NVIDIA Dev, InfoQ; cap N=25). Parked 35: 23 → Newsletters (22 G3 + The Information), 4 adapter-backlog (arXiv×2, Papers With Code, HN), 4 RSS/SPA/cloud-IP revisit, 3 landing revisit-or-drop, 1 drop (AnandTech). **Watchlist OFF** (WATCHLIST_GATE=False, durable extract-all). Reports live с 2026-06-22. config — источник правды |
| Society | not started | свой чат | weekly | ~50 источников (демография, труд…). Наследует Concepts/Technology (cloud + Flow-триаж) |

## SYNTHESIS

| Модуль | State | Owner-chat | Cadence | Note |
|---|---|---|---|---|
| SHIFTS | designed | свой чат | каждые 2 нед · Opus | Нужно 2+ нед накопленных данных |
| Investment Committee | designed | свой чат | on-demand · multi-frontier | Opus+o3+Gemini + детерминир. правила |

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
- **KNOWLEDGE execution model — РЕШЕНО для Playwright-потоков:** сбор в ОБЛАКЕ (GitHub Actions, daily, Playwright) + извлечение вручную на Opus-подписке. Подтверждено Concepts (live) и Technology (live). Society наследует. YouTube остаётся локальным (transcript-IP). **Flow-триаж — решён track-wide** (watchlist-гейт + recency-cap + discovery-sample, детерминированно в коллекторе; общий `config/knowledge_watchlist.json`) — см. ARCHITECTURE_v4 раздел «Flow triage». Локальный путь зарезервирован на случай IP-риска. Technology — LIVE (cloud cron 10:00 UTC + manual Remote, как Concepts); track-wide watchlist/discovery-sample НЕ задействован (WATCHLIST_GATE=False), механизм сохранён как спецификация для Society.
- Backlog (track-wide): RSS/JS-render reader — вернёт adapter/SPA/cloud-IP источники (arXiv×2, HN, Papers With Code, Import AI, Derek Lowe, S&P Global, WikiChip); residential-supplement для cloud-IP-blocked.
- ARCHITECTURE_v3.md устарел в 4 местах (Bank Research, Twitter split, Storage, Substack) — свернуть в v4 при следующем арх-событии, не срочно.
