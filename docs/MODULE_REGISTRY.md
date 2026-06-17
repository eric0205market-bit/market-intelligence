MODULE REGISTRY — Market Intelligence
Единственная страница «что вообще есть». Last reconciled: 2026-06-17 (Tue)
Тонкий слой статуса. НЕ описывает дизайн (он в ARCHITECTURE) и НЕ дублирует детали
(они в CONTEXT-файлах). Одна строка на модуль/ветку.
Three-layer model:
ARCHITECTURE — дизайн, принципы, тиры, build order. Обновлять ПО СОБЫТИЮ (арх-решение).
MODULE REGISTRY (этот файл) — статус. Обновлять В МОМЕНТ рождения модуля / смены состояния.
CONTEXT_*.md — детальный лог на чат. Уже ведётся.
Недельный ритуал (в Architecture-чате): прочитать CONTEXT за неделю → арх-изменения свернуть
в ARCHITECTURE → обновить этот реестр → сверить дату выше.
States: live · trial · building · paused · designed (бриф готов) · not started
Repo: github.com/eric0205market-bit/market-intelligence · Pages: eric0205market-bit.github.io/market-intelligence
FLOW (скоропортящееся)
МодульStateOwner-chatBranchCadence / ModelNoteTwitter — AlphaliveTwittercollect→main; reports→claude/twitter-report2×/день (05:20/17:20 UTC via cron-job.org) · Opusv7 editorial+verificationTwitter — DataliveTwitterкак выше2×/день · Sonnetcatalog + data_pointsTwitter — ShitpostliveTwitterвнутри collect-twitter.yml2×/день · HaikuСобирает, под наблюдением. Переделка маршрута планируется (как и остальные Twitter-роутины)Twitter — Bank ResearchtrialTwitterвнутри collect-twitter.ymlWed+Sun 06:45 UTC · SonnetСобирает, 7 relayer-аккаунтов, author-signal. Решение ~сер. июня: оставить distinct view или влить в DataInstitutional ResearchliveInstitutionalclaude/institutionalВс 06:00 collect / 09:00 routine · Opus~101 сайт банков/AM, Playwright. Полностью автоматизированRESEARCH / Substacklive (interim)— (бесхозный)—Gmail Cloud RoutinePlaywright НЕ построен; Gmail режет картинки. Кандидат на отдельный чатBank PDF (Research PDF Finder)live—mainеженедельно · НЕТ LLMПервый отчёт 31 мая (commit 297d412). На дашборде в группе RESEARCH (#D97706). Sibling к InstitutionalEarnings Callsnot started——quarterly bulk · Haiku~500–1000 компаний; в ARCHITECTURE, не начат
KNOWLEDGE (накопительное)
МодульStateOwner-chatCadenceNoteYouTube / PodcastsliveYouTube/Podcastsdaily collect + manual extract77 каналов, дневной поток живой. СБОР: yt-dlp+субтитры, ЛОКАЛЬНО (launchd 12:00, без LLM/квоты, NOT GitHub Actions). ИЗВЛЕЧЕНИЕ: вручную в Claude Code на Opus-подписке (НЕ API), рубрик routines/routine_youtube.md + entity-guard (карантин). Дневные raw/processed/reports → GitHub. ИСТОРИЧЕСКИЙ БЭКФИЛЛ (с янв-2025) идёт: отдельный локальный код-путь, папка ВНЕ репо, никогда в GitHub. Задаёт шаблон для Concepts/Technology/SocietyConceptslive (Jun-17)Conceptsdaily78 источников (73 Deep + 5 Data). Сбор — Playwright, CLOUD (GitHub Actions), collection cron daily 10:00 UTC (0 10 * * *); извлечение вручную на Opus-подписке, routines/routine_concepts.md + entity-guard. Дневные raw/processed/reports → GitHub (группа KNOWLEDGE). Нет Flow → извлекаем всё. Backlog — docs/BACKLOG.mdTechnologybuildingTechnologydaily67 источников (17 Deep + 50 Flow). Triage Flow = watchlist-гейт + recency-cap + discovery-sample, детерминированно в коллекторе (track-wide, см. ARCHITECTURE «Flow triage»). Клон Concepts: cloud-сбор (GitHub Actions, Playwright) + извлечение Remote-routine. Seed config/technology_sources.json сверён с курацией. Канарейка-firstSocietynot startedсвой чатweekly~50 источников (демография, труд…). Наследует Concepts/Technology (cloud + Flow-триаж)
SYNTHESIS
МодульStateOwner-chatCadenceNoteSHIFTSdesignedсвой чаткаждые 2 нед · OpusНужно 2+ нед накопленных данныхInvestment Committeedesignedсвой чатon-demand · multi-frontierOpus+o3+Gemini + детерминир. правила
INFRA / сквозное
КомпонентStateNoteStorage: GitHub-as-busliveТекущая шина данных: коллекторы коммитят в main, Pages раздаётStorage: Supabasenot startedЦель из ARCHITECTURE_v3 (Postgres + pgvector). Миграция не начиналасьOntology (causal rules)not started~50–100 правил cause-effectEmbeddings (pgvector)not startedЗависит от SupabaseMonitoringphase 1 donePhase 1 = freshness gate (live). Phase 2 = health-strip. Phase 3 = single alert channel. (docs/BACKLOG.md)
ADJACENT (вне MI-пайплайна)
МодульStateNoteCorrelation ThermostatliveОтдельный аналитический инструмент (COR1M сигнал). Ближе к Macro Model. update_dashboard.py + html
COORDINATION RULES
Один чат — один владелец. Twitter (watchlist/коллекция) трогает ТОЛЬКО Twitter-чат. Institutional — только свой.
BUILD каждой роутины — в её чате. Этот (Architecture) чат проектирует и сверяет, не строит Twitter/Institutional.
Новый модуль/ветка родился → сразу строка сюда (а не «потом на недельной сверке»).
OPEN ITEMS (для недельной сверки)
RESEARCH/Substack — бесхозный, на Gmail-интериме (данные собираются). Решить: отдельный чат + Playwright или оставить как есть.
Bank Research trial — решение ~середина июня (distinct view vs влить в Data).
Twitter-роутины (все) — в режиме collect-and-monitor, запланирована переделка маршрутов; TBD когда и как.
YouTube/Podcasts — live (77 каналов). Активно: исторический бэкфилл (фоновый локальный сбор + ручное извлечение JSON-only вне репо). Хвосты: снести старый клон ~/market-intel-youtube, поправить путь в config/com.marketintel.youtube.plist, git rm --cached .DS_Store, поменять хэндл DOAC (клип-канал → основной).
KNOWLEDGE execution model — РЕШЕНО для Playwright-потоков: сбор в ОБЛАКЕ (GitHub Actions, daily, Playwright) + извлечение вручную на Opus-подписке. Подтверждено Concepts (live) и Technology (building). Society наследует. YouTube остаётся локальным (transcript-IP). Flow-триаж — решён track-wide (watchlist-гейт + recency-cap + discovery-sample, детерминированно в коллекторе; общий config/knowledge_watchlist.json) — см. ARCHITECTURE_v4 раздел «Flow triage». Локальный путь зарезервирован на случай IP-риска.
ARCHITECTURE_v3.md устарел в 4 местах (Bank Research, Twitter split, Storage, Substack) — свернуть в v4 при следующем арх-событии, не срочно.
