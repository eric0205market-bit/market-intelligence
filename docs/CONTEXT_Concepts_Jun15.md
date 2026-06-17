# CONTEXT — Market Intelligence / Concepts branch
Handoff для нового чата (владелец Concepts-рутины). Дата: 2026-06-15.
Комм: по-русски, English для технических терминов. Промты для Claude Code — англоязычным код-блоком.

---

## 0. TL;DR — что это за чат

Этот чат **владеет потоком Concepts** (KNOWLEDGE-трек MI). Задача: построить поток
по образцу уже работающих модулей и довести до стабильного дневного цикла.
**Сборка идёт здесь** (готовим промты → вставляем в Claude Code). Координация по
всем трём новым рутинам (Concepts / Technology / Society) остаётся в Architecture-чате —
туда возвращаемся после стабилизации Concepts.

Concepts — **первый из трёх** и задаёт шаблон. Technology и Society потом клонируют его
(меняется только список источников + cadence + политика триажа).

---

## 1. Что такое Concepts

Поток глубоких аналитических/тезисных источников (think tanks, VC, макро-шопы,
стратеги): McKinsey, a16z, BCG, Bridgewater, Stratechery, Anthropic/OpenAI blog и т.д.
Сбор — **Playwright по сайтам** (не транскрипты, в отличие от YouTube). Cadence — **daily**.

**Важное свойство Concepts:** после курации в нём **нет Flow-источников** — только
Deep (73) и Data (5, тоже извлекаем как тексты). Значит **триаж не нужен — извлекаем
всё**. Это делает Concepts самым чистым pattern-setter'ом. Машинерию триажа (брать не
всё, а по entity/повестке) спроектируем уже в Technology (там 54 Flow).

---

## 2. Исполнительная модель (KNOWLEDGE EXECUTION MODEL)

Берём ровно паттерн, зафиксированный на YouTube, но **механизм сбора другой** (Playwright,
не yt-dlp). Для Playwright-механики ближайший готовый образец — **Institutional** (~101 сайт,
Playwright). Поэтому: **сбор клонируем с Institutional, извлечение — с YouTube.**

**Сбор — CLOUD (GitHub Actions), daily.**
- Решение по открытому вопросу «локально или облако»: **облако**, как Institutional.
  Обоснование: Playwright по публичным статейным листингам не несёт transcript-IP-риска,
  который увёл YouTube в локаль; Institutional уже делает это в облаке без проблем.
  → обновить MODULE_REGISTRY (снять OPEN ITEM «local vs cloud для Concepts»).
- Детерминированный, без LLM. Per-source budgets, recency-gate, settle_index, junk-filter,
  per-source funnel-диагностика — всё как в `collect_institutional.py`.

**Извлечение — MANUAL, на Opus-подписке (НЕ API), в Claude Code.**
- Триггер вручную владельцем («run concepts extraction» / следовать файлу).
- Рутина: `routines/routine_concepts.md` (конвенция `routine_*.md`).
- Эмитит **KNOWLEDGE_CARD_SCHEMA v1** — единый конверт + атом инсайта (см. §3).
- **Entity-presence guard:** top_entities сверяются с сырьём; <~40% → карантин
  (`processed/concepts/_quarantine.json`), не удаляется, выводится в отчёте. Норма = 0.
- **ONE-SOURCE-PER-SUBAGENT** (каждый субагент видит только свой текст — защита от
  подмешивания чужих инсайтов).

**Storage — daily stream → GitHub** (как у всех):
`raw/concepts/<source>/<hash>.json`, `processed/concepts/<id>.json`,
`reports/concepts_<date>.html`. Дайджест — **NEW-ONLY за прогон**.
- Историч. бэкфилла для Concepts на старте **нет** (в отличие от YouTube). Аддитивно потом.

---

## 3. Контракт извлечения — KNOWLEDGE_CARD_SCHEMA v1 (НЕ менять)

Авторитет — `KNOWLEDGE_CARD_SCHEMA.md` (owner: Architecture-чат). Рутина обязана писать
ровно этот формат, чтобы при заливке в Supabase это был один импорт.

- **ENVELOPE:** record_id (url-хэш/slug), source_type=`concepts`, source_name, source_url,
  title, published_date, language, processed_at, processor, tags[] (см. словарь), gist,
  themes[], insight_total, top_entities[] (для guard'а), source_meta.
- **source_meta (тексты):** `author`, `word_count`, `paywalled`(опц.).
- **theme:** {theme, insights[]} — 3–8 тем, имена короткие и конкретные.
- **insight (АТОМ, дословно из YouTube — менять нельзя):** claim (самодостаточный!),
  speaker (=author у статей; не угадывать имя), type (thesis|prediction|framework|
  data_point|causal|contrarian|anecdote), entities[], conviction (high|medium|low|
  exploratory — убеждённость АВТОРА), so_what (одна строка для инвестора), quote|null,
  locator|null (для текста — якорь абзаца/секции), quote_verified(bool).
- **tags — ровно 8:** Macro · Energy · Tech · Crypto · Geopolitics · Positioning · AI · Society.
- Эмбединг считается на `claim`(+`so_what`) → claim ОБЯЗАН быть самодостаточным.

---

## 4. Источники

- Seed-конфиг готов: **`config/concepts_sources.json`** (78 источников = Concepts с KEEP=Yes,
  без Move-to). Поля: name, index_url, category, type (Deep/Data), paywalled, trust, verify_listing.
- Первоисточник курации — **`MI_KNOWLEDGE_Source_Curation.xlsx`** (лист Sources).
- `verify_listing:true` у всех — часть index_url редакторские, при канарейке проверить,
  что URL реально отдаёт датированные статьи (иначе поправить путь, как делали в Institutional).
- 2 платных в списке (BCA, Yardeni) — Playwright возьмёт листинг/превью.
- Выкинуто из Concepts при курации: 4 фонд-письма (нет листинга, google-search) + OPEC (→ Data module).

---

## 5. Что НЕ трогать

- Дневные пайплайны YouTube и Institutional **настроены и работают** — не касаться.
  Новое — аддитивно, свои файлы (collect_concepts, routine_concepts, concepts_report, своя workflow).
- KNOWLEDGE_CARD_SCHEMA — менять только в Architecture-чате.

---

## 6. Репо / окружение

- GitHub: `github.com/eric0205market-bit/market-intelligence` (main).
- Рабочая копия: `/Users/bacopa/Dropbox (Personal)/Business/InvestTool/market-intelligence/market-intelligence`.
- Структура: `scripts/` (коллекторы + update_dashboard.py), `config/`, `routines/`,
  `templates/`, `reports/` (шина → Pages), `.github/workflows/`, `docs/` (ARCHITECTURE, REGISTRY, BACKLOG).
- Дашборд: `scripts/update_dashboard.py`, добавление потока = одна строка в `REPORT_TYPES`
  (key = префикс файла отчёта `concepts_`, group = KNOWLEDGE).

---

## 7. Принципы (как себя вести)

- Одна архитектура, не прыгать. Рутина = единый `routine_*.md`, качество правится правкой этого файла.
- Не ломать работающее. Диагностика (read-only) до правки. Claude Code делает технику —
  не гонять владельца по терминалу.
- Данные — в GitHub только дневной поток (код + отчёты лёгкие). Глубокая история (если появится) — вне репо.
- Точность критична, владелец проверяет цифры. Непроверенное не выдавать за факт.
- Старт любого сбора — **канарейка** (3–5 источников), ревью, потом масштаб.

---

## 8. Карта дальше

Concepts (этот чат) → стабилизировать → вернуться в Architecture-чат → Technology
(клон + 54 Flow, нужна политика триажа) → Society (клон, weekly, 10 Data-источников
ушли в Data module). После трёх — база (Supabase + embeddings + ontology) → SHIFTS.
