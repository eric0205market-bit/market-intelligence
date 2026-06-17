#!/usr/bin/env python3
"""Concepts-stream extraction helper + publisher (KNOWLEDGE track).

Clone of scripts/youtube_extract.py, adapted for text articles. Deterministic —
no LLM. The extraction itself (raw article -> KNOWLEDGE card JSON) is done by the
Opus subscription routine in routines/routine_concepts.md, ONE source per
subagent. This script provides the surrounding deterministic machinery:

  worklist                 list new raw/concepts records with no processed card yet
                           (dedup against processed/concepts/<record_id>.json)
  postprocess <id...>      set quote_verified on each insight (quote present in
                           the raw article text). Concepts has no timestamps.
  publish [--date] [--ids] entity-presence guard -> quarantine topic-mismatch
                           cards (NOT deleted), render NEW-ONLY
                           reports/concepts_<date>.html, rebuild the dashboard.

Card contract: docs/KNOWLEDGE_CARD_SCHEMA.md (v1). source_type="concepts".

Raw layout : raw/concepts/<source_slug>/<record_id>.json   (collector output)
Processed   : processed/concepts/<record_id>.json           (one card per source)
Report      : reports/concepts_<YYYY-MM-DD>.html            (NEW-ONLY, this run)
Quarantine  : processed/concepts/_quarantine.json           (non-destructive)

The routine commits + pushes after publish (same as the YouTube routine); this
script only renders + rebuilds the dashboard, exactly like youtube_extract.py
publish delegates git to the routine.
"""
import datetime
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO / "raw" / "concepts"
PROC_DIR = REPO / "processed" / "concepts"
TEMPLATE = REPO / "templates" / "concepts_report.html"
REPORTS_DIR = REPO / "reports"
QUARANTINE_LOG = PROC_DIR / "_quarantine.json"


def _norm(s):
    """Lowercase + collapse non-alphanumerics to single spaces (match-friendly)."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# --- raw / processed indexing ----------------------------------------------
def _raw_files():
    """All collector records, skipping _-prefixed run-artifact dirs (_runs)."""
    out = []
    if not RAW_ROOT.exists():
        return out
    for src_dir in sorted(RAW_ROOT.iterdir()):
        if not src_dir.is_dir() or src_dir.name.startswith("_"):
            continue
        out.extend(sorted(glob.glob(str(src_dir / "*.json"))))
    return out


def _raw_by_id(record_id):
    """Load a single raw record by its record_id (== filename stem), or None."""
    for f in _raw_files():
        if Path(f).stem == record_id:
            try:
                return json.load(open(f, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _processed_ids():
    ids = set()
    if not PROC_DIR.exists():
        return ids
    for f in glob.glob(str(PROC_DIR / "*.json")):
        if Path(f).name.startswith("_"):   # skip _quarantine.json
            continue
        ids.add(Path(f).stem)
    return ids


# --- worklist ---------------------------------------------------------------
def cmd_worklist(_args):
    done = _processed_ids()
    rows = []
    for f in _raw_files():
        rid = Path(f).stem
        if rid in done:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows.append((rid, d.get("source_slug", ""), d.get("title", ""), f))
    if not rows:
        print("No new Concepts articles to extract.")
        return
    print(f"{len(rows)} new article(s) to extract:")
    for rid, slug, title, f in rows:
        print(f"  {rid}  [{slug}]  {title[:70]}")
        print(f"      {Path(f).relative_to(REPO)}")


# --- quote verification (postprocess) ---------------------------------------
def _quote_present(quote, body_norm):
    """True if a quote is faithfully present in the normalized raw text.
    Tolerates caption-style artifacts by also accepting a long core fragment."""
    qn = _norm(quote)
    if not qn:
        return False
    if qn in body_norm:
        return True
    # Fallback: accept if a long contiguous core (first/last ~40 norm-chars) hits.
    if len(qn) >= 50:
        if qn[:40] in body_norm or qn[-40:] in body_norm:
            return True
    return False


def postprocess_record(card, raw):
    """Set quote_verified on every insight + recompute insight_total to match the
    actual insight count (schema §1: insight_total = total across all themes — the
    LLM's self-count can drift by one). Returns (quotes, verified)."""
    body = _norm((raw or {}).get("text"))
    quotes = verified = total = 0
    for theme in (card.get("themes") or []):
        for ins in (theme.get("insights") or []):
            if not isinstance(ins, dict):
                continue
            total += 1
            if ins.get("quote"):
                quotes += 1
                ok = bool(body) and _quote_present(ins["quote"], body)
                ins["quote_verified"] = ok
                if ok:
                    verified += 1
            else:
                ins.setdefault("quote_verified", False)
    card["insight_total"] = total
    return quotes, verified


def cmd_postprocess(args):
    total = verified = 0
    for rid in args.ids:
        pf = PROC_DIR / f"{rid}.json"
        if not pf.exists():
            print(f"  postprocess: {rid} — no processed file, skip")
            continue
        card = json.load(open(pf, encoding="utf-8"))
        q, v = postprocess_record(card, _raw_by_id(rid) or {})
        total += q
        verified += v
        json.dump(card, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  postprocess: {rid} — quotes {v}/{q} verified")
    print(f"postprocess totals: quotes={total} verified={verified}")


# --- entity-presence guard ---------------------------------------------------
ENTITY_PRESENCE_MIN = 0.40   # a card whose top_entities are <40% present in its
                             # raw article text is a topic mismatch (hallucinated
                             # / cross-contaminated extraction) and is quarantined.
ENTITY_CHECK_MIN_N = 4       # only judge cards with >=4 entities (small lists noisy)


def entity_presence(card, raw):
    """Fraction of a card's top_entities that appear in its raw article text.
    Returns (fraction, n_entities). Real cards sit well above 0.40."""
    body = _norm((raw or {}).get("text"))
    ents = [e for e in (card.get("top_entities") or []) if e]
    if not body or len(ents) < ENTITY_CHECK_MIN_N:
        return 1.0, len(ents)            # can't judge -> pass through
    def present(e):
        ws = [w for w in _norm(e).split() if len(w) > 3]
        return any(w in body for w in ws) if ws else (_norm(e) in body)
    hit = sum(1 for e in ents if present(e))
    return hit / len(ents), len(ents)


# --- render (NEW-ONLY) -------------------------------------------------------
def _build_payload(cards, date, lookback_days=None):
    insights = sum(
        len(t.get("insights") or []) for c in cards for t in (c.get("themes") or [])
    )
    quotes = verified = 0
    for c in cards:
        for t in (c.get("themes") or []):
            for ins in (t.get("insights") or []):
                if ins.get("quote"):
                    quotes += 1
                    if ins.get("quote_verified"):
                        verified += 1
    sources = len({c.get("source_name") for c in cards if c.get("source_name")})
    stats = {
        "cards": len(cards),
        "insights": insights,
        "sources": sources,
        "quote_verified_pct": (round(100 * verified / quotes) if quotes else None),
    }
    if lookback_days is not None:
        stats["lookback_days"] = lookback_days
    return {
        "date": date,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                                  .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "stats": stats,
        "cards": cards,
    }


def _render(cards, date):
    if not TEMPLATE.exists():
        sys.exit(f"template not found: {TEMPLATE}")
    payload = json.dumps(_build_payload(cards, date), ensure_ascii=False)
    html = TEMPLATE.read_text(encoding="utf-8").replace("__REPORT_DATA__", payload)
    if "__REPORT_DATA__" in html:
        sys.exit("ERROR: placeholder __REPORT_DATA__ still present after substitution")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"concepts_{date}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path.relative_to(REPO)} "
          f"({len(html):,} bytes, {len(cards)} card(s))")


def cmd_publish(args):
    date = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # Candidate ids: explicit --ids, else everything processed on `date`.
    if args.ids:
        cand = [x.strip() for x in args.ids.split(",") if x.strip()]
    else:
        cand = []
        for f in sorted(glob.glob(str(PROC_DIR / "*.json"))):
            if Path(f).name.startswith("_"):
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if (d.get("processed_at") or "")[:10] == date:
                cand.append(Path(f).stem)

    # --- ENTITY-PRESENCE GUARD: quarantine topic-mismatch cards, never publish them ---
    ok_cards, quarantined = [], []
    for rid in cand:
        pf = PROC_DIR / f"{rid}.json"
        if not pf.exists():
            continue
        try:
            card = json.load(open(pf, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        frac, n = entity_presence(card, _raw_by_id(rid))
        if frac < ENTITY_PRESENCE_MIN:
            quarantined.append({"record_id": rid, "title": card.get("title"),
                                "source_name": card.get("source_name"),
                                "entity_presence": round(frac, 3), "n_entities": n})
        else:
            ok_cards.append(card)

    if quarantined:
        print("\n⚠ QUARANTINED (entity presence < %d%% — NOT published, kept for your review):"
              % int(ENTITY_PRESENCE_MIN * 100))
        for q in quarantined:
            print(f"    ✗ [{q['record_id']}] {q['source_name']} — {q['title']}  "
                  f"({int(q['entity_presence']*100)}% of {q['n_entities']} entities present)")
        QUARANTINE_LOG.write_text(json.dumps(quarantined, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(f"    -> logged to {QUARANTINE_LOG.relative_to(REPO)}. Re-extract these from "
              f"their raw article, then re-publish. (Processed files left in place.)\n")

    # --- render NEW-ONLY report (guard-filtered) + rebuild dashboard ---
    _render(ok_cards, date)
    subprocess.run([sys.executable, str(REPO / "scripts" / "update_dashboard.py")], check=True)
    bb = REPO / "scripts" / "inject_back_button.py"
    if bb.exists():
        subprocess.run([sys.executable, str(bb)], check=True)
    print(f"published {len(ok_cards)} card(s); "
          f"{len(quarantined)} quarantined; date {date}")


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("worklist").set_defaults(fn=cmd_worklist)
    a = sub.add_parser("postprocess"); a.add_argument("ids", nargs="+"); a.set_defaults(fn=cmd_postprocess)
    a = sub.add_parser("publish")
    a.add_argument("--date", default=None)
    a.add_argument("--ids", default=None)
    a.set_defaults(fn=cmd_publish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
