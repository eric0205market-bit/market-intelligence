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
| RESEARCH / Substack | live (interim) | — (бесхозный) | — | Gmail Cloud Routine | Playwright НЕ построен; Gmail режет картинки. Кандидат на отдельный чат |
| Bank PDF (Research PDF Finder) | live | — | main | еженедельно · НЕТ LLM | Первый отчёт 31 мая (commit 297d412). На дашборде в группе RESEARCH (#D97706). Sibling к Institutional |
| Earnings Calls | not started | — | — | quarterly bulk · Haiku | ~500–1000 компаний; в ARCHITECTURE, не начат |

## KNOWLEDGE (накопительное)

| Модуль | State | Owner-chat | Cadence | Note |
|---|---|---|---|---|
| YouTube / Podcasts | live | YouTube/Podcasts | daily collect + manual extract | **77 каналов**, дневной поток живой. СБОР: yt-dlp+субтитры, **ЛОКАЛЬНО** (launchd 12:00, без LLM/квоты, NOT GitHub Actions). ИЗВЛЕЧЕНИЕ: вручную в Claude Code на **Opus-подписке** (НЕ API), рубрик `routines/routine_youtube.md` + entity-guard (карантин). Дневные raw/processed/reports → GitHub. **ИСТОРИЧЕСКИЙ БЭКФИЛЛ** (с янв-2025) идёт: отдельный локальный код-путь, папка **ВНЕ репо**, никогда в GitHub. Задаёт шаблон для Concepts/Technology/Society |
| Concepts | live (Jun-17) | Concepts | daily | **78 источников** (73 Deep + 5 Data). Сбор — Playwright, **CLOUD (GitHub Actions), collection cron daily 10:00 UTC** (`0 10 * * *`); извлечение вручную на Opus-подписке, `routines/routine_concepts.md` + entity-guard. Дневные raw/processed/reports → GitHub (группа KNOWLEDGE). Нет Flow → извлекаем всё. Backlog — docs/BACKLOG.md |
| Technology | building | Technology | daily | **67 источников** (17 Deep + 50 Flow). Triage Flow = watchlist-гейт + recency-cap + discovery-sample, детерминированно в коллекторе (track-wide, см. ARCHITECTURE «Flow triage»). Клон Concepts: cloud-сбор (GitHub Actions, Playwright) + извлечение Remote-routine. Seed `config/technology_sources.json` сверён с курацией. Канарейка-first |
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
- RESEARCH/Substack — бесхозный, на Gmail-интериме (данные собираются). Решить: отдельный чат + Playwright или оставить как есть.
- Bank Research trial — решение ~середина июня (distinct view vs влить в Data).
- Twitter-роутины (все) — в режиме collect-and-monitor, запланирована переделка маршрутов; TBD когда и как.
- YouTube/Podcasts — **live** (77 каналов). Активно: исторический бэкфилл (фоновый локальный сбор + ручное извлечение JSON-only вне репо). Хвосты: снести старый клон `~/market-intel-youtube`, поправить путь в `config/com.marketintel.youtube.plist`, `git rm --cached .DS_Store`, поменять хэндл DOAC (клип-канал → основной).
- **KNOWLEDGE execution model — РЕШЕНО для Playwright-потоков:** сбор в ОБЛАКЕ (GitHub Actions, daily, Playwright) + извлечение вручную на Opus-подписке. Подтверждено Concepts (live) и Technology (building). Society наследует. YouTube остаётся локальным (transcript-IP). **Flow-триаж — решён track-wide** (watchlist-гейт + recency-cap + discovery-sample, детерминированно в коллекторе; общий `config/knowledge_watchlist.json`) — см. ARCHITECTURE_v4 раздел «Flow triage». Локальный путь зарезервирован на случай IP-риска.
- ARCHITECTURE_v3.md устарел в 4 местах (Bank Research, Twitter split, Storage, Substack) — свернуть в v4 при следующем арх-событии, не срочно.
