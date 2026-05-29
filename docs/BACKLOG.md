## Backlog — Monitoring / Alerting (deferred, decided 2026-05-29, Twitter chat)
PHASE 1 (done): Freshness gate — routines abort and publish nothing if collection data is stale (scripts/check_freshness.py + STEP 0 in each routine).

- PHASE 2 — Central health panel (build when several routines exist; do NOT build per-routine banners). Each routine writes ONE status line (ok / stale / error + run time + data collected_at) to a shared status file (e.g. data/status/routines.json). Dashboard renders one compact health strip: green/red dot per routine, so all routine health is visible at a glance in one place. Adding a routine = it writes its status line; panel shows it automatically (~2 min status-writer per routine). Don't build until the schema is informed by a few real routines.
- PHASE 3 — Single alert channel. One notification (email/Telegram) that fires ONLY when a routine goes red, built on top of the Phase 2 status file, so no manual checking is needed.

Rationale: per-routine banners = clutter and don't scale; relying on report dates across many routines = silent misses. One status file -> one panel -> one alert.
