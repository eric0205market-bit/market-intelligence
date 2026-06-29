# CONTEXT — Market Intelligence / Society branch
Handoff для нового чата (владелец Society-рутины). Дата: 2026-06-27.
Комм по-русски, English для терминов. Промты для Claude Code — англоязычным блоком.

---

## 0. TL;DR
Этот чат **владеет потоком Society** — третий и последний KNOWLEDGE-поток. YouTube,
Concepts и Technology уже **live** и пишут дневные отчёты. Society — **клон Technology**
(который сам клон Concepts), отличия: **cadence weekly** + свой список + taxonomy-решение (§5).
Сборка здесь, координация в Architecture-чате. После Society — база (Supabase + embeddings
+ ontology) → SHIFTS.

## 1. Что такое Society
Длинные эссе + аналитика по обществу: геополитика/IR, демография, труд, энергопереход
как соц-явление, культура/идеи. Foreign Affairs, Economist, Noema, Aeon, The Diplomat,
think-tanks и т.д. Сбор — Playwright по сайтам. **Cadence — weekly** (а не daily): поток
менее скоропортящийся, чем Technology.

## 2. Исполнительная модель (клон Technology as-built)
Technology уже отладил Flow-проблему на практике — **берём его реализацию, не мою исходную
watchlist-спеку.** Что реально работает в Technology (и наследует Society):

- **Сбор — CLOUD (GitHub Actions, Playwright), collection-only, без LLM.** Для Society —
  **weekly cron** (напр. Вс), окно `--days 7`. recency-gate + record_id-dedup в коллекторе.
- **Извлечение — MANUAL на Opus-подписке**, `routines/routine_society.md` + entity-guard
  (карантин <40%) + **one-source-per-subagent**. Remote-routine, как Concepts/Technology.
- **Политика по типам (как сделал Technology):**
  - **Deep → extract-all** + recency (без фильтра).
  - **Flow → НЕ watchlist-гейт.** Technology поступил так: скоропортящиеся новостные Flow
    **запарковал → Newsletters** (`collect:false`, `skip_reason "→ FLOW/Newsletters"`), а
    оставил небольшой набор Flow с **per-source cap N=25**. **WATCHLIST_GATE=False** (durable
    extract-all). Society делает так же: на канарейке решить, какие Flow держать активными,
    остальные перишабл — park→Newsletters.
  - **Data → не в этом потоке** (10 чисто-дата публикаторов Society ушли в Data module ещё
    на курации; в seed их нет).
- watchlist/discovery-sample механизм есть в коде как спецификация, но **выключен** —
  не включать без отдельного решения.
- **collect:false honored** коллектором (parked-источники не собираются).
- Дневной/недельный поток → GitHub: `raw/society/`, `processed/society/`, `reports/society_<date>.html`.

## 3. Контракт извлечения — KNOWLEDGE_CARD_SCHEMA v1 (не менять)
Рутина пишет ровно этот формат, `source_type="society"`. Атом инсайта (claim самодостаточный,
speaker=author, type, conviction=убеждённость автора, so_what, quote|null, locator=якорь
абзаца, quote_verified) — дословно как в Concepts/Technology. tags — те же 8 (Society в т.ч.).
Авторитет — `docs/KNOWLEDGE_CARD_SCHEMA.md`.

## 4. Источники
- Seed готов: **`config/society_sources.json`** — **57 источников = 16 Deep + 41 Flow.**
- 10 чисто-дата публикаторов (Our World in Data, Pew, UN Population, BLS, Indeed Hiring Lab,
  Lightcast, PRB, Oxford Demography, SNB Studies, KOF) → **Data module**, в seed исключены.
- **4 дубля с Concepts** помечены `dedup_note` (Noema, Palladium, Works in Progress, SNB-домен) —
  Concepts их уже собирает; не собирать дважды (или собирать в одном доме).
- Платные (Economist, FT, Nikkei, SCMP, Stratfor) — `paywalled:true`, Playwright берёт
  заголовок/листинг как сигнал повестки, не тело.
- `verify_listing:true` у всех — на канарейке проверить, что index_url отдаёт датированные статьи.

## 5. Taxonomy — РЕШЕНО (Jun-27): 11 think-tanks перенесены Concepts→Society
Контекст: прямого Technology→Society переноса в конфигах не было (скоропортящиеся
defense/geopolitics из Technology — War Zone, Defense One, Breaking Defense — ушли в
**Newsletters/FLOW**, не в Society; они уже пристроены). Реальный перенос — по Concepts:
тяжёлые внешнеполитические/оборонные think-tanks из Concepts пересекались с геополитикой
Society. Владелец решил **перенести их в Society** (2026-06-27).

**Уже в `society_sources.json`** (блок `_relocated_from_concepts`):
- **9 active:** RAND, CFR, Carnegie Endowment, Atlantic Council, CSIS, Hudson, IISS,
  Brookings, German Marshall Fund (собирались в Concepts нормально → index_url рабочие, взяты as-built).
- **2 parked** (`collect:false`, несут свой реальный skip_reason): Stimson (JS-SPA, 0-2 anchors
  любой IP), Chatham House (cloud-IP-blocked — в облаке Actions не берётся). В Society они тоже
  не соберутся — оставлены запаркованными честно, не «открывать заново».

**Вторая половина переноса (ОБЯЗАТЕЛЬНО, иначе двойной сбор):** эти 11 надо
**убрать из `config/concepts_sources.json`** (`collect:false`, skip_reason «relocated → Society»).
Это правка Concepts-конфига → работа Concepts-чата / координации. Готовый CC-промт для этого
идёт вместе с этим пакетом — прогнать до/параллельно со стартом Society.

## 6. Уроки Concepts/Technology — забрать (чтобы не наступать)
1. **merge-to-main авто:** push в ветку `claude/**` → авто-мёрж в `main`. Cloud-run пишет
   служебным `GITHUB_TOKEN` → НЕ триггерит авто-мёрж → данные облачного прогона висят на ветке
   до PAT-пуша. Учитывать при «hold the push».
2. **Многие think-tank/эссе-сайты — JS-SPA или bot-block** (особенно с облачного Actions-IP).
   Ждать того же у части Society (CFR/RAND/Carnegie ок в Concepts, но Stimson/Chatham — нет).
   Парковать с `collect:false` + `skip_reason` + `revisit_route`, не блокировать поток.
3. **Revisit (RSS/JS-render) — ОБЩАЯ будущая возможность** (Architecture-чат). НЕ строить
   per-source RSS/JS-render внутри Society. Парковать и идти дальше.
4. **Paywall teasers** (тело короткое) — парковать как Technology (Science AAAS пример).
5. **Канарейка-first**, потом масштаб. Пользователь не программист — CC делает технику.

## 7. Репо / окружение
- GitHub: `github.com/eric0205market-bit/market-intelligence` (main). Рабочая копия —
  Dropbox-клон; CC обычно работает в worktree (`.claude/worktrees/...`) — это отдельный чекаут.
- Структура: `scripts/`, `config/`, `routines/`, `templates/`, `reports/`, `.github/workflows/`, `docs/`.
- Дашборд: `scripts/update_dashboard.py` — добавить поток = одна строка в `REPORT_TYPES`
  (key `society_`, group KNOWLEDGE).

## 8. Карта дальше
Society (этот чат) → стабилизировать → **все три KNOWLEDGE-потока live** → база
(**Supabase + pgvector embeddings + ontology**) → **SHIFTS**. Society — последний поток
перед сборкой базы.
