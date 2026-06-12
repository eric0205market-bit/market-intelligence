# ROUTINE — YOUTUBE / PODCASTS **HISTORICAL BACKFILL** EXTRACTION (JSON-only)
# Model: Opus (subscription) — one transcript per subagent, same as the daily run.
# Input:  youtube-history/<slug>/<video_id>.json   (backfill-collected transcripts)
# Output: youtube-history/_processed/<slug>/<video_id>.json   (knowledge cards)
#         youtube-history/_quarantine/<slug>/<video_id>.json  (entity-guard failures)
#         youtube-history/_runlog/extract_<YYYY-MM-DD>.md      (run summary)
# Cadence: MANUAL / quota-bound. Decoupled from collection. Run quota-bounded batches
#          with --limit N and resume; the worklist re-lists only the unprocessed.

This is the historical analog of `routine_youtube.md`. It MIRRORS THE DAILY QUALITY
EXACTLY and reuses (does not fork) the daily logic via `scripts/youtube_backfill.py`,
which imports `build_prompt`, `postprocess_record`, `entity_presence`, and the
`ENTITY_PRESENCE_*` thresholds from `scripts/youtube_extract.py`. The card schema is
the daily knowledge-card schema in `routine_youtube.md` STEP 2 OUTPUT FORMAT.

**The ONLY differences from the daily routine are the I/O paths and the publish step:**
JSON-only — **NO HTML report, NO dashboard rebuild, and NO `git add/commit/push` anywhere.**
Deep history stays out of the repo.

---

## STEP 0 — WORKLIST GATE (MANDATORY, RUN FIRST) — self-heals interrupted waves
Build the worklist — every backfill transcript that has a transcript and NO
**FINALIZED** card yet in `_processed/` (or a `_quarantine/` card). Dedup is by
**finalized status, not mere file presence**: a raw card written by an agent whose
wave was interrupted (has quotes but no `quote_verified`/timestamps) does NOT count
as done. Use `--limit N` for a quota-bounded batch; default order is newest
`upload_date` first (most valuable first).

    python3 scripts/youtube_backfill.py worklist --limit N            # newest first
    python3 scripts/youtube_backfill.py worklist --order oldest       # or oldest / longest

**SELF-HEAL is automatic.** Before listing, `worklist` FIRST finalizes any raw
leftover cards in `_processed/` (cheap — postprocess + entity guard only, NO
re-extraction; activity goes to stderr, a summary to `_runlog/`), THEN lists the
truly-missing transcripts on stdout. So an interrupted wave **self-heals on the next
run** instead of leaving a silent dedup trap. (You can run the heal explicitly with
`python3 scripts/youtube_backfill.py heal`; `worklist --no-heal` gives a pure
read-only listing and is only for inspection — never feed `--no-heal` rows to
extraction, as raw leftovers would be re-extracted.)

TSV columns (stdout only): `slug  video_id  tier  mins  seg|noseg  channel  title`.
If it prints nothing: STOP — nothing to do. Otherwise process ONLY the listed rows.

## STEP 1 — EXTRACT (one transcript per subagent, Opus)
For EACH worklisted row, emit the per-episode prompt and hand it to its OWN subagent:

    python3 scripts/youtube_backfill.py prompt <slug> <video_id>

This prompt is IDENTICAL to the daily one (same STEP 2 rubric + metadata + transcript).
Spawn one Opus subagent per transcript. Each subagent:
- works EXCLUSIVELY from the single transcript in its prompt (never another episode,
  a sibling task, the title alone, or prior knowledge — same one-transcript rule as daily);
- outputs ONLY the JSON knowledge card (no fences, no prose);
- writes it to `youtube-history/_processed/<slug>/<video_id>.json` (create parent dirs);
- touches NOTHING else — no git, no HTML, no other files.

## STEP 2 — FINALIZE (run ONCE, only AFTER every subagent has completed)
**Do not run finalize until all spawned extraction agents for the batch have returned**
— otherwise a late agent can overwrite a just-postprocessed card (the daily race). Then:

    python3 scripts/youtube_backfill.py finalize <slug>/<id> <slug>/<id> ...

finalize, for each card: (1) runs `postprocess_record` — maps quotes to caption cue
times from the transcript's stored `transcript_segments` and sets `quote_verified`
(reused verbatim from the daily path); (2) runs the **entity-presence guard** — any
card whose `top_entities` are <40% present in its transcript is treated as a topic
mismatch (hallucinated / cross-contaminated) and **MOVED to `_quarantine/<slug>/`**,
not kept; (3) writes/append the run summary to `_runlog/extract_<date>.md`.

If finalize prints a quarantine line: report the id(s) to the owner and re-extract from
the correct transcript next batch. Never hand-edit a card to pass the guard.

## RUN SUMMARY (no dashboard)
finalize prints and appends to `youtube-history/_runlog/extract_<YYYY-MM-DD>.md`:
transcripts processed, total insights, quarantined count, quotes verified/total,
timestamped count. **No git.**

## HARD RULES
- NEVER render HTML, rebuild the dashboard, or run any `git` command in this routine.
- NEVER use the paid API — Opus on the subscription only. On a usage limit, STOP
  CLEANLY: finalize whatever cards were already written, report what finished, and end.
  The next run resumes — the worklist re-lists only the still-unprocessed transcripts.
- `youtube-history/` (deep history) stays OUT of the repo — do not `git add` it.
