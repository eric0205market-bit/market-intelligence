#!/usr/bin/env python3
"""Helper for on-demand YouTube insight extraction (manual, subscription-run).

Subcommands (called by scripts/extract_youtube_local.sh, and reusable by the
interactive Claude Code agent):

  worklist                 list NEW eligible raw transcripts (TSV) — the work to do
  tier <video_id>          print the model tier (opus|sonnet) for a video, from config
  prompt <video_id>        emit the full extraction prompt (rubric + meta + transcript)
  postprocess <id>...      deterministically set timestamp (from the raw record's stored
                           transcript_segments) + quote_verified on processed/youtube/<id>.json
  publish                  render reports/youtube_<date>.html (cumulative) + rebuild dashboard

Eligibility: transcript present, duration >= minimum_duration_minutes (config),
and NOT already processed (no processed/youtube/<id>.json). A content-dedup
safeguard also skips a raw whose channel + duration matches an already-processed
episode (re-uploads), so we never burn subscription quota re-extracting the same
content under a new video id.

NO network, NO API key, NO external API — pure local file work.
"""
import datetime
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "raw" / "youtube"
PROC_DIR = REPO / "processed" / "youtube"
CONFIG = REPO / "config" / "youtube_sources_full.json"
RUBRIC = REPO / "routines" / "routine_youtube.md"

DUP_DURATION_TOLERANCE = 3   # seconds; same channel + ~same length => re-upload


def _cfg():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _min_seconds():
    return int(_cfg().get("minimum_duration_minutes", 25)) * 60


def _tier_lookup():
    """channel_name / channel_handle -> tier, from config (default sonnet)."""
    by_name, by_handle = {}, {}
    for c in _cfg().get("channels", []):
        t = (c.get("tier") or "sonnet").lower()
        by_name[c["name"]] = t
        m = re.search(r"/(@[^/?#]+)", c.get("source", ""))
        if m:
            by_handle[m.group(1)] = t
    return by_name, by_handle


def tier_for(rec):
    by_name, by_handle = _tier_lookup()
    return (by_name.get(rec.get("channel_name"))
            or by_handle.get(rec.get("channel_handle"))
            or "sonnet")


def _raw_records():
    out = []
    for f in sorted(glob.glob(str(RAW_DIR / "*" / "*.json"))):
        try:
            d = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue
        d["_path"] = f
        out.append(d)
    return out


def _processed_ids():
    return {os.path.basename(f)[:-5] for f in glob.glob(str(PROC_DIR / "*.json"))
            if os.path.basename(f) != QUARANTINE_LOG.name}


def _processed_sigs():
    """(channel_name, duration_seconds) of already-processed episodes — for content-dedup."""
    sigs = []
    for f in glob.glob(str(PROC_DIR / "*.json")):
        if os.path.basename(f) == QUARANTINE_LOG.name:
            continue
        try:
            d = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue
        sigs.append((d.get("channel_name"), d.get("duration_seconds") or 0))
    return sigs


def worklist():
    """Return list of eligible raw records (new, >= min duration, not a dup)."""
    min_s = _min_seconds()
    done = _processed_ids()
    sigs = _processed_sigs()
    elig = []
    for d in _raw_records():
        if not d.get("transcript_available"):
            continue
        dur = d.get("duration_seconds") or 0
        if dur < min_s:
            continue
        if d["video_id"] in done:
            continue
        # content-dedup: same channel + near-identical duration as a processed ep
        if any(ch == d.get("channel_name") and abs(sec - dur) <= DUP_DURATION_TOLERANCE
               for ch, sec in sigs):
            continue
        elig.append(d)
    elig.sort(key=lambda d: -(d.get("duration_seconds") or 0))
    return elig


def cmd_worklist(_):
    for d in worklist():
        print("\t".join([
            d["video_id"], tier_for(d), str(round((d.get("duration_seconds") or 0) / 60)),
            "seg" if d.get("transcript_segments") else "noseg",
            (d.get("channel_name") or "")[:28], (d.get("video_title") or "")[:60],
        ]))


def cmd_tier(args):
    for d in _raw_records():
        if d["video_id"] == args.id:
            print(tier_for(d)); return
    print("sonnet")


def _raw_by_id(vid):
    for d in _raw_records():
        if d["video_id"] == vid:
            return d
    return None


def build_prompt(d):
    """Build the single-episode extraction prompt (rubric + metadata + transcript)
    from a raw/history record `d`. Shared by the daily (cmd_prompt) and the backfill
    path so both feed the model an IDENTICAL prompt — only the input dir differs."""
    meta = {k: d.get(k) for k in (
        "video_id", "url", "channel_name", "channel_handle", "section",
        "video_title", "upload_date", "duration_seconds", "length_bucket", "language")}
    meta["tier"] = tier_for(d)
    # Embed only the STEP 2 PROCESS rubric — the per-episode extraction spec —
    # not the routine's STEP 0/1/3 (worklist / fetch / publish+git), which would
    # be noise in a single-episode headless prompt. Falls back to the whole file.
    full = RUBRIC.read_text(encoding="utf-8")
    m = re.search(r"## STEP 2: PROCESS\s*(.*?)(?:\n## STEP 3|\Z)", full, re.S)
    rubric = m.group(1).strip() if m else full
    return "\n".join([
        "Extract investor insights from ONE podcast episode, following this rubric exactly:\n",
        rubric,
        "\n---\nRAW METADATA (copy these fields into your output):\n",
        json.dumps(meta, ensure_ascii=False, indent=2),
        "\n---\nTRANSCRIPT (read all of it):\n",
        d.get("transcript") or "",
    ])


def cmd_prompt(args):
    d = _raw_by_id(args.id)
    if not d:
        sys.exit(f"raw record not found for {args.id}")
    print(build_prompt(d))


# --- deterministic timestamp + quote_verified post-processing -----------------
def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", (s or "").lower())).strip()


def _fmt_ts(sec):
    sec = int(sec); h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fragments(quote):
    return [n for n in (_norm(p) for p in re.split(r"\.\.\.|…|\[.*?\]", quote)) if len(n) >= 15]


def _collapse_rolling(segs):
    """Collapse rolling-window caption overlap (same logic as the collector) so
    stored segments read as clean prose — lifts quote/timestamp matching for the
    existing corpus without re-collecting. Manual (non-rolling) cues are unchanged."""
    out = []
    prev = []
    for s in segs or []:
        words = (s.get("text") or "").split()
        if not words:
            continue
        lp = [w.lower() for w in prev]
        lw = [w.lower() for w in words]
        k = 0
        for j in range(min(len(lp), len(lw)), 0, -1):
            if lp[-j:] == lw[:j]:
                k = j
                break
        new = words[k:]
        if not new:
            if out:
                out[-1]["end"] = s.get("end")
            prev = words
            continue
        out.append({"start": s.get("start"), "end": s.get("end"), "text": " ".join(new)})
        prev = words
    return out


def _build_index(segments):
    import bisect  # noqa: F401 (used by caller)
    starts, times, parts, cur = [], [], [], 0
    for seg in _collapse_rolling(segments):
        nt = _norm(seg.get("text"))
        if not nt:
            continue
        starts.append(cur); times.append(seg.get("start") or 0)
        parts.append(nt); cur += len(nt) + 1
    return " ".join(parts), starts, times


def postprocess_record(d, raw):
    """Deterministically set quote_verified + timestamp on every insight of card `d`
    from its raw record. Mutates `d` in place; returns (total, mapped, verified, any_ts).
    Shared by the daily (cmd_postprocess) and the backfill path so the timestamp +
    quote-verification logic is IDENTICAL — only the file I/O around it differs."""
    import bisect
    raw = raw or {}
    has_segs = bool(raw.get("transcript_segments"))   # records collected before
    # the timed-caption feature have none; their timestamps came from the one-time
    # re-fetch backfill and must be PRESERVED (never clobbered to null here).
    seg_body, starts, times = _build_index(raw.get("transcript_segments"))
    # Verify quotes against BOTH the flat transcript AND the timed segments.
    # Some raw records have a flat `transcript` that is out of sync with
    # `transcript_segments`; the segments are the authoritative caption text,
    # so a quote sourced from them must still verify.
    body_tx = (_norm(raw.get("transcript")) + " " + seg_body).strip()
    total = mapped = verified = 0
    any_ts = False
    for t in d.get("themes", []):
        for ins in t.get("insights", []):
            q = ins.get("quote")
            if not q:
                ins["timestamp"] = None
                continue
            total += 1
            frags = _fragments(q)
            # quote_verified: all fragments present in the raw plain transcript
            ok = bool(frags) and all(fr in body_tx for fr in frags)
            if not ok:
                nq = _norm(q)
                ok = len(nq) >= 25 and nq in body_tx
            ins["quote_verified"] = ok
            if ok:
                verified += 1
            # timestamp: map first fragment to a cue start — ONLY when this record
            # has stored segments. With no segments, leave the existing timestamp
            # untouched (do not clobber a backfilled one to null).
            if has_segs:
                ts = None
                frag = frags[0] if frags else _norm(q)[:40]
                pos = seg_body.find(frag) if len(frag) >= 12 else -1
                if pos >= 0:
                    i = bisect.bisect_right(starts, pos) - 1
                    ts = _fmt_ts(times[max(i, 0)])
                    mapped += 1; any_ts = True
                ins["timestamp"] = ts
            elif ins.get("timestamp"):
                mapped += 1                       # preserved existing timestamp
    if has_segs:                                  # only recompute the flag when we
        d["timestamps_available"] = any_ts        # actually (re)mapped from segments
    return total, mapped, verified, any_ts


def cmd_postprocess(args):
    total = mapped = verified = 0
    for vid in args.ids:
        pf = PROC_DIR / f"{vid}.json"
        if not pf.exists():
            print(f"  postprocess: {vid} — no processed file, skip"); continue
        d = json.load(open(pf))
        t_, m_, v_, any_ts = postprocess_record(d, _raw_by_id(vid) or {})
        total += t_; mapped += m_; verified += v_
        json.dump(d, open(pf, "w"), ensure_ascii=False, indent=2)
        print(f"  postprocess: {vid} — quotes verified, timestamps {'set' if any_ts else 'none (no segments)'}")
    print(f"postprocess totals: quotes={total} verified={verified} timestamped={mapped}")


ENTITY_PRESENCE_MIN = 0.40   # a record whose top_entities are <40% present in its
                             # raw transcript is treated as a topic mismatch
                             # (hallucinated/cross-contaminated extraction) and quarantined.
ENTITY_CHECK_MIN_N = 4       # only judge records with >=4 entities (small lists are noisy)
QUARANTINE_LOG = PROC_DIR / "_quarantine.json"


def _write_quarantine_log(new_entries, date, force=False):
    """Merge new_entries into QUARANTINE_LOG instead of overwriting it — a second
    publish call (same day or a different day) must not erase quarantine entries
    from an earlier run. Union keyed by video_id; each entry stamped with `date`
    so it is date-scoped/inspectable; new_entries win on overlap.

    Called UNCONDITIONALLY (even with an empty new_entries) so an empty run can
    never be mistaken for a reason to skip writing, and prior entries are always
    preserved rather than only being touched when this run happens to quarantine
    something.

    SHRINK-GUARD: refuse to write if the merge would produce fewer entries than
    already on disk — mathematically impossible for a union merge, so this is a
    hard-stop unless force=True explicitly overrides it."""
    existing = []
    if QUARANTINE_LOG.exists():
        try:
            existing = json.loads(QUARANTINE_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"  WARN: could not parse existing {QUARANTINE_LOG.name} "
                  f"— treating as empty (nothing already-quarantined is lost; "
                  f"this run's entries will still be written)")
            existing = []
    merged = {e["video_id"]: e for e in existing if e.get("video_id")}
    for e in new_entries:
        e = dict(e)
        e["date"] = date
        merged[e["video_id"]] = e
    merged_entries = list(merged.values())

    if len(merged_entries) < len(existing) and not force:
        sys.exit(f"FATAL: merge would SHRINK {QUARANTINE_LOG} from "
                 f"{len(existing)} to {len(merged_entries)} entries — refusing "
                 f"to write. This should be mathematically impossible for a "
                 f"union merge; something is wrong upstream (investigate before "
                 f"re-running, or pass --force to write anyway).")

    QUARANTINE_LOG.write_text(json.dumps(merged_entries, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return merged_entries, existing


def entity_presence(rec, raw):
    """Fraction of a record's top_entities that actually appear in its raw transcript.
    Returns (fraction, n_entities). The exact integrity check that caught the one
    hallucinated extraction: a real record sits well above 0.40; a fabricated one ~0."""
    tx = _norm((raw or {}).get("transcript"))
    seg = " ".join(s.get("text", "") for s in ((raw or {}).get("transcript_segments") or []))
    body = (tx + " " + _norm(seg)).strip()
    ents = [e for e in (rec.get("top_entities") or []) if e]
    if not body or len(ents) < ENTITY_CHECK_MIN_N:
        return 1.0, len(ents)            # can't judge -> pass through
    def present(e):
        ws = [w for w in _norm(e).split() if len(w) > 3]
        return any(w in body for w in ws) if ws else (_norm(e) in body)
    hit = sum(1 for e in ents if present(e))
    return hit / len(ents), len(ents)


def cmd_publish(args):
    date = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # Candidate ids for this publish (explicit --ids, else everything processed today).
    if args.ids:
        cand = [x.strip() for x in args.ids.split(",") if x.strip()]
    else:
        cand = []
        for f in sorted(glob.glob(str(PROC_DIR / "*.json"))):
            if Path(f).name == QUARANTINE_LOG.name:
                continue
            try:
                d = json.load(open(f))
            except (json.JSONDecodeError, OSError):
                continue
            if (d.get("processed_at") or "")[:10] == date:
                cand.append(d["video_id"])

    # --- ENTITY-PRESENCE GUARD: quarantine topic-mismatch records, never publish them ---
    ok, quarantined = [], []
    for vid in cand:
        pf = PROC_DIR / f"{vid}.json"
        if not pf.exists():
            continue
        try:
            rec = json.load(open(pf))
        except (json.JSONDecodeError, OSError):
            continue
        frac, n = entity_presence(rec, _raw_by_id(vid))
        if frac < ENTITY_PRESENCE_MIN:
            quarantined.append({"video_id": vid, "title": rec.get("video_title"),
                                "entity_presence": round(frac, 3), "n_entities": n})
        else:
            ok.append(vid)

    if quarantined:
        print("\n⚠ QUARANTINED (entity presence < %d%% — NOT published, kept for your review):"
              % int(ENTITY_PRESENCE_MIN * 100))
        for q in quarantined:
            print(f"    ✗ [{q['video_id']}] {q['title']}  "
                  f"({int(q['entity_presence']*100)}% of {q['n_entities']} entities in transcript)")

    merged_q, existing_q = _write_quarantine_log(quarantined, date, force=getattr(args, "force", False))
    if quarantined:
        print(f"    -> logged to {QUARANTINE_LOG} ({len(merged_q)} total entries, "
              f"{len(existing_q)} previously on disk). Re-extract these from their raw "
              f"transcripts, then re-publish. (Processed files left in place; not deleted.)\n")

    render_cmd = [sys.executable, str(REPO / "scripts" / "render_youtube_digest.py"),
                  "--date", date]
    # Always pass an explicit (guard-filtered) id list so quarantined records can't render.
    render_cmd += [f"--ids={','.join(ok)}"]
    if getattr(args, "force", False):
        render_cmd += ["--force"]
    subprocess.run(render_cmd, check=True)
    subprocess.run([sys.executable, str(REPO / "scripts" / "update_dashboard.py")], check=True)
    bb = REPO / "scripts" / "inject_back_button.py"
    if bb.exists():
        subprocess.run([sys.executable, str(bb)], check=True)


def main():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("worklist").set_defaults(fn=cmd_worklist)
    a = sub.add_parser("tier"); a.add_argument("id"); a.set_defaults(fn=cmd_tier)
    a = sub.add_parser("prompt"); a.add_argument("id"); a.set_defaults(fn=cmd_prompt)
    a = sub.add_parser("postprocess"); a.add_argument("ids", nargs="+"); a.set_defaults(fn=cmd_postprocess)
    a = sub.add_parser("publish"); a.add_argument("--date", default=None)
    a.add_argument("--ids", default=None)
    a.add_argument("--force", action="store_true",
                    help="override the report/quarantine shrink-guards")
    a.set_defaults(fn=cmd_publish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
