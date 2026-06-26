# ROUTINE — CONCEPTS **HISTORICAL BACKFILL** EXTRACTION (JSON-only)
# Model: Opus (subscription) — one ARTICLE per subagent, same as the daily run. NEVER the paid API.
# Input:  concepts-history/<slug>/<record_id>.json            (backfill-collected raw articles)
# Output: concepts-history/_processed/<slug>/<record_id>.json (knowledge cards)
#         concepts-history/_quarantine/<slug>/<record_id>.json (entity-guard failures)
#         concepts-history/_runlog/extract_<YYYY-MM-DD>.md      (run summary)
# Cadence: MANUAL / quota-bound. Decoupled from collection. Run quota-bounded batches with
#          --limit N and resume; the worklist re-lists only the unprocessed.

This is the historical analog of `routine_concepts.md`, and the Concepts twin of
`routine_youtube_backfill.md`. It MIRRORS THE DAILY CONCEPTS QUALITY EXACTLY and reuses
(does not fork) the daily logic via `scripts/concepts_backfill_extract.py`, which imports
`postprocess_record`, `entity_presence`, and `ENTITY_PRESENCE_MIN` from
`scripts/publish_concepts.py`. The extraction prompt is the daily `routine_concepts.md`
STEP 2 rubric (single-sourced from that file). The card contract is
`docs/KNOWLEDGE_CARD_SCHEMA.md` (v1).

**The ONLY differences from the daily routine are the I/O paths and the publish step:**
JSON-only — **NO HTML report, NO dashboard rebuild, and NO `git add/commit/push` anywhere.**
Deep history stays out of the repo (`concepts-history/` is outside the git tree).

**SCOPE — heavy think-tanks EXCLUDED.** The worklist automatically skips the heavy slugs
(`brookings_institution`, `carnegie_endowment`) pending the Society/Science taxonomy
decision. Everything else in `concepts-history/` (signal tier + Stage-3, ~2,450 articles)
is in scope.

---

## STEP 0 — WORKLIST GATE (MANDATORY, RUN FIRST) — self-heals interrupted waves
Build the worklist — every backfill article that has text and NO **FINALIZED** card yet in
`_processed/` (or a `_quarantine/` card). Dedup is by **finalized status + global
record_id, not mere file presence**: a raw card written by an agent whose wave was
interrupted (no `_finalized` stamp) does NOT count as done. Use `--limit N` for a
quota-bounded batch; default order is newest `published_date` first.

    python3 scripts/concepts_backfill_extract.py worklist --limit N         # newest first
    python3 scripts/concepts_backfill_extract.py worklist --order oldest     # or oldest / longest

**SELF-HEAL is automatic.** Before listing, `worklist` FIRST finalizes any raw leftover
cards in `_processed/` (cheap — postprocess + entity guard only, NO re-extraction; activity
to stderr, a summary to `_runlog/`), THEN lists the truly-missing on stdout. So an
interrupted wave self-heals on the next run instead of leaving a silent dedup trap. (Run the
heal explicitly with `... heal`; `worklist --no-heal` is a pure read-only listing — never
feed `--no-heal` rows to extraction.)

TSV columns (stdout only): `slug  record_id  words  source_name  title`.
If it prints nothing: STOP — nothing to do. Otherwise process ONLY the listed rows.

## STEP 1 — EXTRACT (one article per subagent, Opus)
For EACH worklisted row, emit the per-article prompt and hand it to its OWN subagent:

    python3 scripts/concepts_backfill_extract.py prompt <slug> <record_id>

This prompt is the daily STEP 2 rubric + the raw record + the exact output path. Spawn one
Opus subagent per article. Each subagent:
- works EXCLUSIVELY from the single article in its prompt (never another article, a sibling
  task, the title alone, or prior knowledge — same one-source rule as daily);
- outputs ONLY the JSON knowledge card (no fences, no prose);
- writes it to `concepts-history/_processed/<slug>/<record_id>.json` (create parent dirs);
- leaves every `quote_verified` = false (STEP 2 finalize sets it);
- touches NOTHING else — no git, no HTML, no other files.

## STEP 2 — FINALIZE (run ONCE, only AFTER every subagent has completed)
**Do not run finalize until all spawned extraction agents for the batch have returned** —
otherwise a late agent can overwrite a just-postprocessed card (the daily race). Then:

    python3 scripts/concepts_backfill_extract.py finalize <slug>/<id> <slug>/<id> ...

finalize, for each card: (1) runs `postprocess_record` — sets `quote_verified` by checking
each quote verbatim against the raw `text`, and recomputes `insight_total` (reused from the
daily publish path); (2) runs the **entity-presence guard** — any card whose `top_entities`
are <40% present in its raw `text` is a topic mismatch (hallucinated / cross-contaminated)
and is **MOVED to `_quarantine/<slug>/`**, not kept; (3) stamps `_finalized` on kept cards
and writes/append the run summary to `_runlog/extract_<date>.md`.

If finalize prints a quarantine line: report the id(s) to the owner and re-extract from the
correct article next batch. Never hand-edit a card to pass the guard.

## RUN SUMMARY (no dashboard)
finalize prints and appends to `concepts-history/_runlog/extract_<YYYY-MM-DD>.md`: articles
processed, total insights, quarantined count, quotes verified/total. **No git.**

## HARD RULES
- NEVER render HTML, rebuild the dashboard, or run any `git` command in this routine.
- NEVER use the paid API — Opus on the subscription only. On a usage limit, STOP CLEANLY:
  finalize whatever cards were already written, report what finished, and end. The next run
  resumes — the worklist re-lists only the still-unprocessed articles.
- `concepts-history/` (deep history) stays OUT of the repo — do not `git add` it.
- Heavy think-tanks (brookings/carnegie) are OUT of scope here (auto-excluded) until the
  Society/Science taxonomy is decided.
