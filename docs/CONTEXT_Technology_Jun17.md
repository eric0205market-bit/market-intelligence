# CONTEXT — Market Intelligence / Technology branch
Handoff для нового чата (владелец Technology-рутины). Дата: 2026-06-17.
Комм: по-русски, English для технических терминов. Промты для Claude Code — англоязычным код-блоком.
Извлечение крутится через **Routines** (вставляешь содержимое `routine_*.md` как самодостаточный промт в Remote-routine).

---

## 0. TL;DR — что это за чат
Этот чат **владеет потоком Technology** — второй из трёх KNOWLEDGE-потоков. **Concepts уже построен,
стабилен и живёт** (cloud-сбор daily 10:00 UTC + ручное извлечение через Routine + дашборд). Technology
его **КЛОНИРУЕТ**. Меняются ровно три вещи: (1) список источников, (2) cadence, (3) — **главное** —
добавляется **ПОЛИТИКА ТРИАЖА**, потому что у Technology **50 Flow-источников** (из 67 всего:
17 Deep + 50 Flow, Data нет) — высокочастотные ленты, извлекать всё нельзя. Сборка идёт здесь;
координация — в Architecture-чате. **Seed `technology_sources.json` уже сгенерирован** (см. §4).

---

## 1. Что такое Technology и чем отличается от Concepts
- **Concepts был чистым случаем:** только Deep + Data, **без Flow** → извлекаем всё, триаж не нужен.
- **Technology — Flow-heavy:** 67 источников = **17 Deep + 50 Flow** (Data нет). Flow = быстрые ленты
  (новости/блоги большого объёма). Брать всё = шум + лишний расход Opus.
- → **НУЖЕН ТРИАЖ** (см. §3): отбирать, что извлекать, по entity/повестке/релевантности. Это
  центральная новая задача Technology — Concepts её сознательно отложил сюда.
- **Cadence:** подтвердить (вероятно daily, как Concepts).

---

## 2. Исполнительная модель — КЛОН as-built Concepts (не изобретать)
Клонировать **живые** Concepts-файлы (они в репо на `main`), меняя `concepts`→`technology`:
- **Сбор:** `scripts/collect_concepts.py` → `collect_technology.py`. **Cloud (GitHub Actions cron).**
  Коллектор уже закалён — забрать всё: incremental crash-safe flush (пишет по ходу), `--resume`,
  **hard per-source timeout** (один сайт не вешает прогон), retry/backoff для flaky-листингов,
  `progress.json`, per-source funnel, junk-filter + word-floor, per-source overrides
  (`url_must_contain` для host-restriction, `article_path_re` для single-slug essays).
- **Workflow:** `.github/workflows/collect-concepts.yml` → `collect-technology.yml`. Cron **спит**
  (закомментирован) до прохождения канарейки.
- **Извлечение:** `routines/routine_concepts.md` → `routine_technology.md`. Самодостаточный промт,
  вставляется в Routine **«MI - Technology» (Remote)**. Только извлечение (сбор — крон). **+ ДОБАВИТЬ
  TRIAGE — см. §3.** (Concepts-рутина прямо помечает «триаж добавляется в Technology, не здесь».)
- **Publish:** `scripts/publish_concepts.py` → `publish_technology.py`. Entity-presence guard +
  quarantine, quote-verify, NEW-ONLY report, dashboard rebuild, прямой `push origin main` с retry-rebase.
- **Report template:** `templates/concepts_report.html` → `technology_report.html`. **ВАЖНО:** клонировать
  **отрефайненный** Concepts-шаблон (YouTube-выровненные чипы entities/speaker, цветные type/conviction
  чипы, sort по source/insight, source-filter, expand/collapse all, per-group collapse) — **НЕ** старый
  Institutional-шаблон.
- **Dashboard:** одна строка в `scripts/update_dashboard.py` `REPORT_TYPES` (key `"technology_"`,
  group `"knowledge"`, свой цвет/иконка).
- **Storage:** `raw/technology/<slug>/<hash>.json`, `processed/technology/<id>.json`,
  `reports/technology_<date>.html`.

---

## 3. ТРИАЖ — новая машинерия (центральная задача Technology)
**Проблема:** 50 Flow-источников дают слишком много низкосигнальных статей. Извлекать всё = дорого (Opus)
+ шумно. (Курация уже пометила 3 как заведомо шумные — `collection_note` в seed: ArXiv cs.AI, ArXiv cs.LG,
Hacker News — это prime-кандидаты на жёсткий фильтр.)

**Что нужно:** отбор ДО дорогого извлечения — какие Flow-статьи стоят извлечения. По возможности
**детерминированный** (без LLM), как остальная фильтрация коллектора.

**Подходы (решить в этом чате / с Architecture-чатом):**
- **по entity-присутствию:** брать Flow-статью, только если упоминает сущности из watchlist
  (компании/тикеры/темы повестки);
- **по типу источника:** Deep/Data — извлекаем всё (как Concepts); **Flow — фильтруем**;
- recency-gate + record_id-dedup уже есть в коллекторе.

**Где живёт триаж:** вероятно в коллекторе (детерминированный фильтр перед записью в worklist) ИЛИ
как лёгкий STEP 0.5 в рутине. Решить и зафиксировать.

**Принцип:** триаж режет на входе (что собирать/воркслистить), а НЕ внутри извлечения — извлечение
остаётся «один источник на субагента», как в Concepts.

---

## 4. Источники
- **`config/technology_sources.json` уже сгенерирован** из `MI_KNOWLEDGE_Source_Curation.xlsx`
  (строки Stream=Technology, KEEP=Yes) — лежит готовым seed'ом, в том же формате, что `concepts_sources.json`.
- **Состав: 67 источников = 17 Deep + 50 Flow** (Data нет). 57 trusted / 10 unverified; 2 paywalled.
- Поля: `name, index_url, category, type` (Deep/Flow), `paywalled, trust, verify_listing`. Доп.:
  `collection_note` у 3 шумных (high volume / aggregator → триаж-кандидаты), и блок `_triage`
  (deep=extract_all, flow=filter_before_extraction).
- `collect:false` НЕ проставлен — решается в этом чате после канарейки (как было в Concepts).
- `verify_listing:true` у всех — на канарейке проверить, что `index_url` реально отдаёт датированные статьи.

---

## 5. Уроки Concepts — забрать обязательно (чтобы не наступать повторно)
1. **merge-to-main automation:** push в ветку `claude/**` → **авто-мёрж в `main`**. «Push = merge»,
   отдельного гейта нет. Cloud-run пишет служебным `GITHUB_TOKEN` → НЕ триггерит авто-мёрж → данные
   облачного прогона остаются на ветке, пока не сольёшь PAT-пушем. Учитывать при любом «hold the push».
2. **Cloud vs blocked.** Облако собирает основную массу, НО часть сайтов: блокирует **облачный IP**
   (дата-центр), блокирует робота с **любого IP** (бот-защита), или **JS-SPA** (контента нет в статичном
   DOM). Категории и что делать:
   - неверный `index_url` (лендинг/раздел) → подобрать правильный адрес списка (Carnegie-style);
   - PDF/doc-id → отложить в Bank PDF module;
   - paywalled → `collect:false`;
   - bot-blocked (любой IP) → drop, revisit через RSS/newsletter;
   - JS-SPA → drop, revisit через RSS или JS-render;
   - cloud-IP-blocked, но с домашнего берётся → park (residential supplement, бэклог);
   - per-source overrides: `url_must_contain` (host-restriction), `article_path_re` (single-slug essays).
3. **Канарейка-first staged rollout** (что сработало, повторить):
   канарейка 3-5 (вкл. один трудный) → wide collection-only diagnostic (все источники) → URL-fix pass →
   **cloud verification run** (`workflow_dispatch` на ветке) → extraction review batch (~10-12 разнородных,
   локально, без пуша) → full run → launch.
4. **Минимальный merge для облачного теста:** `workflow_dispatch` не работает, пока workflow не на
   default-ветке (`main`). Поэтому коллектор + workflow + config кладутся в main **рано** (cron спит) —
   это безопасно, ничего само не бежит.
5. **Извлечение надёжно:** entity-presence guard + quote-verify держатся на масштабе (Concepts:
   900/901 цитат сверены, 0 в карантине на 36 источниках). Тонкие карточки от платных/SPA — это честная
   бедность контента, не баг (модель не раздувает).
6. **Известный polish-долг** (можно сразу заложить в Technology): поле `author` иногда ловит CMS-мусор
   (URL, @handle, логин) — чистить до человека/организации/пусто.
7. **Routine = самодостаточный `.md`**, вставляется в Remote-routine. Работает на **свежем main**
   (Remote-окружение берёт свежий main — проверено на Institutional). Failure mode: на несвежей копии
   worklist пустой → no-op (безопасно, ничего не ломает).
8. **Числа должны сходиться:** активные + отложенные = всего источников; владелец проверяет.

---

## 6. Что НЕ трогать
- Живые daily-пайплайны **YouTube, Institutional, Concepts** — не касаться. Technology **аддитивно**,
  свои файлы (`collect_technology`, `routine_technology`, `publish_technology`, `technology_report`,
  своя workflow).
- `docs/KNOWLEDGE_CARD_SCHEMA.md` — **общий, НЕ менять** (только в Architecture-чате). Technology эмитит
  ровно тот же атом, `source_type="technology"`.

---

## 7. Репо / окружение
- GitHub: `github.com/eric0205market-bit/market-intelligence` (main).
- Рабочая копия: `/Users/bacopa/Dropbox (Personal)/Business/InvestTool/market-intelligence/market-intelligence`.
- Структура: `scripts/`, `config/`, `routines/`, `templates/`, `reports/`, `.github/workflows/`, `docs/`.
- Канарейка-first; пользователь не программист — Claude Code делает технику, не гонять по терминалу.

---

## 8. Карта дальше
Technology (этот чат) → стабилизировать → **Society** (клон, weekly) → после трёх потоков:
база (**Supabase + embeddings + ontology**) → **SHIFTS**.

**Backlog (Architecture-чат, общий для KNOWLEDGE-трека):**
1. **RSS / JS-render reader** — вернуть bot/SPA-blocked высокоценные источники (McKinsey, Citi, Bain,
   Sequoia [у неё есть живой RSS], Lux). Technology упрётся в те же сайты.
2. **Residential-collection supplement** — для cloud-IP-blocked источников (Chatham House, IEA + будущие).
