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
    return {os.path.basename(f)[:-5] for f in glob.glob(str(PROC_DIR / "*.json"))}


def _processed_sigs():
    """(channel_name, duration_seconds) of already-processed episodes — for content-dedup."""
    sigs = []
    for f in glob.glob(str(PROC_DIR / "*.json")):
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


def cmd_prompt(args):
    d = _raw_by_id(args.id)
    if not d:
        sys.exit(f"raw record not found for {args.id}")
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
    print("Extract investor insights from ONE podcast episode, following this rubric exactly:\n")
    print(rubric)
    print("\n---\nRAW METADATA (copy these fields into your output):\n")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("\n---\nTRANSCRIPT (read all of it):\n")
    print(d.get("transcript") or "")


# --- deterministic timestamp + quote_verified post-processing -----------------
def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", (s or "").lower())).strip()


def _fmt_ts(sec):
    sec = int(sec); h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fragments(quote):
    return [n for n in (_norm(p) for p in re.split(r"\.\.\.|…|\[.*?\]", quote)) if len(n) >= 15]


def _build_index(segments):
    import bisect  # noqa: F401 (used by caller)
    starts, times, parts, cur = [], [], [], 0
    for seg in segments or []:
        nt = _norm(seg.get("text"))
        if not nt:
            continue
        starts.append(cur); times.append(seg.get("start") or 0)
        parts.append(nt); cur += len(nt) + 1
    return " ".join(parts), starts, times


def cmd_postprocess(args):
    import bisect
    total = mapped = verified = 0
    for vid in args.ids:
        pf = PROC_DIR / f"{vid}.json"
        if not pf.exists():
            print(f"  postprocess: {vid} — no processed file, skip"); continue
        d = json.load(open(pf))
        raw = _raw_by_id(vid) or {}
        seg_body, starts, times = _build_index(raw.get("transcript_segments"))
        # Verify quotes against BOTH the flat transcript AND the timed segments.
        # Some raw records have a flat `transcript` that is out of sync with
        # `transcript_segments`; the segments are the authoritative caption text,
        # so a quote sourced from them must still verify.
        body_tx = (_norm(raw.get("transcript")) + " " + seg_body).strip()
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
                # timestamp: map first fragment to a cue start (only if segments exist)
                ts = None
                if times:
                    frag = frags[0] if frags else _norm(q)[:40]
                    pos = seg_body.find(frag) if len(frag) >= 12 else -1
                    if pos >= 0:
                        i = bisect.bisect_right(starts, pos) - 1
                        ts = _fmt_ts(times[max(i, 0)])
                        mapped += 1; any_ts = True
                ins["timestamp"] = ts
        d["timestamps_available"] = any_ts
        json.dump(d, open(pf, "w"), ensure_ascii=False, indent=2)
        print(f"  postprocess: {vid} — quotes verified, timestamps {'set' if any_ts else 'none (no segments)'}")
    print(f"postprocess totals: quotes={total} verified={verified} timestamped={mapped}")


def cmd_publish(args):
    date = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    render_cmd = [sys.executable, str(REPO / "scripts" / "render_youtube_digest.py"),
                  "--date", date]
    if args.ids:                       # NEW-ONLY: restrict to this run's episodes
        render_cmd += [f"--ids={args.ids}"]   # = form: safe for ids starting with '-'
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
    a.add_argument("--ids", default=None); a.set_defaults(fn=cmd_publish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
