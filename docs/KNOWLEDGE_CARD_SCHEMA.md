# KNOWLEDGE CARD SCHEMA — common contract
## v1 · 2026-06-07 · owner: Architecture chat

Единый формат `processed`-записи для ВСЕХ потоков трека KNOWLEDGE
(YouTube, Concepts, Technology, Society). Каждая рутина (`routines/routine_*.md`)
эмитит один JSON-объект на источник в этой форме.

**Зачем:** чтобы три новых потока копились в совместимом виде и при заливке в
Supabase это был один чистый импорт, а не переписывание данных.

**YouTube grandfathered.** YouTube продолжает работать как есть, его формат НЕ
меняем. На стыке (загрузка в базу) разница конверта подравнивается одним
маппингом — см. раздел «YouTube mapping» внизу. Никакой переделки YouTube.

---

## Структура записи

```
ENVELOPE (про источник)
  + themes[]  →  insights[]   (insight = атом, идентичен во всех потоках)
```

---

## 1. ENVELOPE — source-agnostic (одинаково во всех потоках)

| поле | тип | что |
|---|---|---|
| `record_id` | str | стабильный id источника (video_id у видео, url-хэш/slug у статьи) |
| `source_type` | str | `youtube` \| `concepts` \| `technology` \| `society` |
| `source_name` | str | канал / издание (e.g. "a16z", "SemiAnalysis") |
| `source_url` | str | прямой URL источника |
| `title` | str | заголовок выпуска / статьи |
| `published_date` | str | дата публикации источника (YYYY-MM-DD) |
| `language` | str | язык контента (e.g. "en") |
| `processed_at` | str | UTC-таймстамп извлечения (ISO) |
| `processor` | str | кто извлёк (e.g. "claude-code-sub-opus") |
| `tags` | str[] | лёгкие теги из контролируемого словаря (см. §4) |
| `gist` | str | 1–3 предложения сути, конкретно, не обобщённо |
| `themes` | obj[] | см. §3 |
| `insight_total` | int | суммарно инсайтов по всем темам |
| `top_entities` | str[] | 5–12 важнейших сущностей по всей записи (нужно entity-guard'у) |
| `source_meta` | obj | под-блок, специфичный для типа источника, см. §2 |

---

## 2. source_meta — специфика по типу источника

Маленький под-объект, поля зависят от `source_type`. Общий слой их не читает —
они для отображения и будущей фильтрации.

**youtube:** `channel_handle`, `duration_seconds`, `duration_minutes`,
`length_bucket`, `timestamps_available`, `tier`

**concepts / technology / society (тексты):** `author`, `word_count`,
`paywalled` (bool, опц.)

---

## 3. theme

```
{ "theme": "<короткое конкретное имя темы>",
  "insights": [ <insight>, ... ] }
```
3–8 тем на запись. Имена тем — короткие и специфичные, не общие бакеты.

---

## 4. insight — АТОМ (дословно из YouTube, одна правка: locator)

Это ценность формата и место, где консистентность критична для базы.
Менять нельзя — все потоки пишут идентично.

| поле | тип | что |
|---|---|---|
| `claim` | str | самодостаточное утверждение, понятное БЕЗ заголовка. Плохо: «He's bullish». Хорошо: «Dan Loeb adds AI-infra credit because spreads don't price obsolescence risk». |
| `speaker` | str | кто сказал — имя если ясно из контекста, иначе роль ("host", "guest, fund CIO"). У статей = автор. Не угадывать имя. |
| `type` | str | `thesis` \| `prediction` \| `framework` \| `data_point` \| `causal` \| `contrarian` \| `anecdote`. Брать доминирующий. `causal` = X-causes-Y (крючок для онтологии). |
| `entities` | str[] | компании/тикеры/люди/сектора/технологии в этом инсайте |
| `conviction` | str | `high` \| `medium` \| `low` \| `exploratory` — убеждённость ГОВОРЯЩЕГО, не твоя |
| `so_what` | str | одна строка: почему инвестору не пофиг / как это торговать или мониторить |
| `quote` | str\|null | дословная цитата из источника, или null. Цитировать только когда сама формулировка — сигнал. |
| `locator` | str\|null | где в источнике: таймкод (видео) или якорь абзаца/секции (текст) |
| `quote_verified` | bool | сверена ли цитата с сырьём |

---

## 5. Контролируемый словарь тегов (§4 envelope `tags`)

Ровно эти 8 (из ARCHITECTURE — лёгкие теги для просмотра человеком, НЕ фильтр):

`Macro` · `Energy` · `Tech` · `Crypto` · `Geopolitics` · `Positioning` · `AI` · `Society`

Запись может нести несколько. Не фильтрует — весь контент всё равно попадает в отчёты.

---

## 6. Зачем эти поля (связь с будущей базой)

Чтобы было понятно, что менять нельзя:

- **Эмбединги (Layer 2):** вектор считается на `claim` (+`so_what`). Поэтому claim
  обязан быть самодостаточным — это требование эмбедингов, не стилистика. Вектор
  живёт в Supabase, не в JSON; схему под него менять не нужно.
- **Онтология (Layer 1, causal-правила):** правила срабатывают на `entities[]` и
  на `type:"causal"`. Это уже встроено — отдельных полей онтологии в карточке не надо.
- **entity-guard:** сверяет `top_entities` с сырьём; <~40% присутствия → карантин.
  Поэтому `top_entities` обязателен и должен реально встречаться в источнике.

---

## 7. YouTube mapping (на момент заливки в базу — НЕ сейчас)

YouTube пишет в своём виде, не трогаем. При импорте в Supabase подровнять конверт:

| YouTube | common |
|---|---|
| `video_id` | `record_id` |
| `video_title` | `title` |
| `upload_date` | `published_date` |
| `channel_name` | `source_name` |
| `url` | `source_url` |
| `channel_handle`, `duration_*`, `length_bucket`, `timestamps_available`, `tier` | → `source_meta` |
| `section` | → свести к `tags` (§5) |
| insight `timestamp` | `locator` |

Работа на день, при загрузке. Данные YouTube переизвлекать не нужно.

---

## Версионирование
- v1 (2026-06-07): первая фиксация. Атом инсайта = YouTube as-built. Конверт обобщён.
- Менять только в Architecture-чате, по событию; bump версии + строка сюда.
