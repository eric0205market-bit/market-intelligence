#!/usr/bin/env python3
"""YouTube/Podcasts Collector — Phase 1: collection only.

Daily collector for a pilot set of YouTube channels / playlists. For each
source it lists recent uploads (yt-dlp, no API key), fetches the transcript of
each NEW video, and writes one raw JSON per video plus a per-channel seen-state
so videos are never re-fetched. NO LLM, NO summarization, NO report — that is
deliberately out of scope for Phase 1 (see BUILD_BRIEF).

This is a deterministic sibling to the other collectors in this repo
(scripts/collect_twitter.py, collect_institutional.py, collect_research_pdfs.py)
and follows their conventions: REPO_ROOT-relative paths, a timestamped log(),
raw output under raw/<source>/, a run summary, and a workflow that commits the
results straight to main.

WINDOW / DEDUP (BUILD_BRIEF):
  * State: state/youtube_seen.json — per channel slug, the set of already-seen
    video ids (+ last run / last upload seen).
  * First ever run for a channel: only fetch uploads within the last
    `first_run_window_days` (config, default 7). This avoids pulling history.
  * Subsequent runs: fetch uploads NOT in the seen set, restricted to the last
    ~14 days, so a newly-added channel can't backfill its whole history.
  * Safety caps: <= MAX_NEW_PER_CHANNEL new videos/channel/run, <= MAX_NEW_TOTAL
    per run.
  * Listings are newest-first, so once we hit an upload older than the window we
    mark it (and everything past it) seen and stop scanning that channel — old
    videos are skipped permanently, never re-examined.

TRANSCRIPTS (BUILD_BRIEF order):
  1. yt-dlp manual subtitles (--write-subs)         -> source "manual"
  2. yt-dlp auto subtitles    (--write-auto-subs)   -> source "auto"
  3. youtube-transcript-api fallback                -> source "auto"/"manual"
  A video with no obtainable transcript is STILL written, with
  transcript_available=false / transcript=null, so we keep a record and don't
  retry it forever.

CLOUD-IP NOTE: YouTube frequently throttles transcript/subtitle fetching from
cloud IPs (GitHub Actions runners). yt-dlp impersonation (curl_cffi) materially
helps; the workflow installs it. The per-channel "ZERO transcripts" list in the
run summary is the early-warning signal for blocked channels.

Run:
    python3 scripts/collect_youtube.py                       # full daily run
    python3 scripts/collect_youtube.py --max-channels 3 --dry-run   # spike test
    python3 scripts/collect_youtube.py --channels cnbc,wealthion    # subset
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# --- Paths ------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "youtube_sources_full.json"
STATE_PATH = REPO_ROOT / "state" / "youtube_seen.json"
RAW_ROOT = REPO_ROOT / "raw" / "youtube"
RUNLOG_DIR = RAW_ROOT / "_runlog"

# --- Tunables ---------------------------------------------------------------
DEFAULT_FIRST_RUN_WINDOW_DAYS = 7    # first-ever run per channel (config wins)
STEADY_WINDOW_DAYS = 14              # guard so newly-added channels can't backfill
MAX_NEW_PER_CHANNEL = 10            # safety cap (BUILD_BRIEF)
MAX_NEW_TOTAL = 60                  # safety cap (BUILD_BRIEF)
LIST_LIMIT = 25                    # how many recent uploads to flat-list per source
SHORT_MAX_SECONDS = 20 * 60        # <20min = "short", >=20min = "long" (tag only)
YTDLP_TIMEOUT = 120                # per yt-dlp subprocess (s)
# Browser impersonation dramatically reduces YouTube blocking from cloud IPs;
# requires the curl_cffi extra (installed by the workflow). Harmless if absent.
IMPERSONATE = ["--extractor-args", "youtube:player_client=default,web_safari"]
SUB_LANGS_MANUAL = "en,en-US,en-GB,en-CA,en-AU,en-IE"
SUB_LANGS_AUTO = "en,en-US,en-GB"


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "channel"


def handle_from_source(source, vtype):
    """Human-friendly @handle (channels) or playlist id (playlists) for output."""
    if vtype == "playlist":
        qs = parse_qs(urlparse(source).query)
        return (qs.get("list") or [""])[0]
    m = re.search(r"/(@[^/?#]+)", source)
    if m:
        return m.group(1)
    return source


def _norm_handle(h):
    return str(h or "").lstrip("@").strip().lower()


def resolve_channel(name, cfg_handle, meta):
    """Per-video selective attribution. Compare the video's real uploader (yt-dlp
    uploader_id) to the slug's CONFIGURED handle:
      • MATCH  -> keep curated config channel_name/handle (preserves host suffixes
                  and sub-show names, e.g. Animal Spirits on @TheCompoundNews).
      • DIFFER -> genuine cross-post: use the real yt-dlp channel + uploader_id.
    section/tier stay from config; video_title is never touched. Falls back to
    config when yt-dlp returned no uploader_id."""
    yt_uid = str(meta.get("yt_uploader_id") or "").strip()
    if yt_uid and _norm_handle(yt_uid) and _norm_handle(yt_uid) != _norm_handle(cfg_handle):
        ytc = str(meta.get("yt_channel") or "").strip()
        return (ytc or name, yt_uid if yt_uid.startswith("@") else "@" + yt_uid)
    return name, cfg_handle


# --- yt-dlp plumbing --------------------------------------------------------
def run_ytdlp(args, capture=True, timeout=YTDLP_TIMEOUT):
    """Invoke yt-dlp. Returns (returncode, stdout, stderr). Never raises."""
    cmd = ["yt-dlp", "--ignore-config", "--no-warnings", "--no-progress"] + args
    try:
        proc = subprocess.run(
            cmd, capture_output=capture, text=True, timeout=timeout,
        )
        return proc.returncode, (proc.stdout or ""), (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        log("FATAL: yt-dlp not found on PATH")
        sys.exit(2)


def list_source(source, vtype, limit):
    """Flat-list the most recent uploads (newest-first). Returns [{id,title}]."""
    url = source
    if vtype == "channel":
        # Target the uploads ("Videos") tab so we don't pull Shorts/Live tabs.
        base = url.rstrip("/")
        if not base.endswith("/videos"):
            url = base + "/videos"
    args = [
        "--flat-playlist", "--playlist-end", str(limit),
        "--print", "%(id)s\t%(title)s",
    ] + IMPERSONATE + [url]
    rc, out, err = run_ytdlp(args)
    entries = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        vid = vid.strip()
        if vid and vid != "NA":
            entries.append({"id": vid, "title": title.strip()})
    if not entries and rc != 0:
        log(f"    list failed (rc={rc}): {err.strip().splitlines()[-1] if err.strip() else 'no output'}")
    return entries


def get_metadata(video_id):
    """dump-json (simulate, no file writes) -> dict of the fields we need, or None."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    args = ["--skip-download", "--dump-json"] + IMPERSONATE + [url]
    rc, out, err = run_ytdlp(args)
    if rc != 0 or not out.strip():
        if err.strip():
            log(f"      yt-dlp: {err.strip().splitlines()[-1][:160]}")
        return None
    try:
        d = json.loads(out.splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return None
    return {
        "title": d.get("title") or "",
        "upload_date": d.get("upload_date"),          # YYYYMMDD or None
        "duration": d.get("duration"),                # seconds or None
        "manual_langs": list((d.get("subtitles") or {}).keys()),
        "auto_langs": list((d.get("automatic_captions") or {}).keys()),
        # Ground-truth posting channel (previously not captured) — for selective
        # per-video attribution and stored on the record.
        "yt_channel": d.get("channel"),
        "yt_uploader_id": d.get("uploader_id"),
        "yt_channel_id": d.get("channel_id"),
    }


def diagnose(config):
    """Cloud-IP probe: YouTube frequently blocks per-video extraction from
    datacenter (Actions) IPs even when flat listing works. Try several yt-dlp
    player clients against one freshly-listed video and report which (if any)
    return metadata + subtitle info. Run from inside Actions to find a working
    transport before committing to a transport in the steady collector."""
    clients = ["tv", "ios", "mweb", "web_safari", "android", "default", "web"]
    # Get one real, current video id from the first source (listing works).
    first = config["channels"][0]
    listed = list_source(first["source"], first.get("type", "channel"), 1)
    if not listed:
        log("DIAGNOSE: could not even list a video — listing is blocked too.")
        return
    vid = listed[0]["id"]
    url = f"https://www.youtube.com/watch?v={vid}"
    log(f"DIAGNOSE: probing player clients on {vid} ({first['name']})")
    log(f"DIAGNOSE: yt-dlp {subprocess.run(['yt-dlp','--version'],capture_output=True,text=True).stdout.strip()}")
    print("", flush=True)
    print(f"| player_client | result | detail |", flush=True)
    print(f"|---|---|---|", flush=True)
    for c in clients:
        args = ["--skip-download", "--dump-json",
                "--extractor-args", f"youtube:player_client={c}", url]
        rc, out, err = run_ytdlp(args, timeout=90)
        if rc == 0 and out.strip():
            try:
                d = json.loads(out.splitlines()[0])
                man = len(d.get("subtitles") or {})
                auto = len(d.get("automatic_captions") or {})
                print(f"| {c} | OK | dur={d.get('duration')} subs(man={man},auto={auto}) |",
                      flush=True)
                continue
            except (json.JSONDecodeError, IndexError):
                pass
        last = err.strip().splitlines()[-1][:120] if err.strip() else f"rc={rc}"
        print(f"| {c} | FAIL | {last} |", flush=True)


def _pick_langs(available, wanted_csv):
    """Intersect available caption langs with our wanted list, preserving order;
    fall back to any en* the video actually has."""
    avail = set(available)
    picked = [w for w in wanted_csv.split(",") if w in avail]
    if picked:
        return picked
    en_like = [a for a in available if a.lower().startswith("en")
               and not a.lower().endswith("-orig")]
    return en_like[:1] or ([a for a in available if a.lower().startswith("en")][:1])


def _vtt_to_text(vtt_path):
    """Strip a VTT subtitle file to clean plain text (handles auto-caption
    rolling duplicates and inline <...> word-timing tags)."""
    try:
        raw = Path(vtt_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines_out = []
    last = None
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == "WEBVTT" or s.startswith(("Kind:", "Language:", "NOTE", "STYLE")):
            continue
        if "-->" in s:                       # timestamp / cue-timing line
            continue
        if re.fullmatch(r"\d+", s):          # numeric cue index
            continue
        s = re.sub(r"<[^>]+>", "", s)        # inline word-timing tags
        s = re.sub(r"\{[^}]+\}", "", s)      # rare cue styling
        s = re.sub(r"\s+", " ", s).strip()
        if not s or s == last:               # collapse rolling auto-caption dups
            continue
        lines_out.append(s)
        last = s
    return " ".join(lines_out).strip()


def _ts_to_sec(ts):
    """'00:01:02.345' / '01:02.345' / '00:01:02,345' -> float seconds."""
    parts = ts.strip().replace(",", ".").split(":")
    try:
        sec = 0.0
        for p in parts:
            sec = sec * 60 + float(p)
        return round(sec, 3)
    except ValueError:
        return None


def _parse_vtt_segments(vtt_path):
    """Parse a VTT into timed cues: [{start, end, text}] (seconds). Collapses the
    rolling-duplicate cues that auto-captions emit, keeping the earliest start
    and extending the end. This preserves cue timing for later timestamp mapping."""
    try:
        raw = Path(vtt_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    segs = []
    cur_start = cur_end = None
    cur_lines = []

    def flush():
        nonlocal cur_lines, cur_start, cur_end
        if cur_start is not None and cur_lines:
            txt = re.sub(r"\s+", " ", " ".join(cur_lines)).strip()
            if txt:
                segs.append({"start": cur_start, "end": cur_end, "text": txt})
        cur_lines = []

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == "WEBVTT" or s.startswith(("Kind:", "Language:", "NOTE", "STYLE")):
            continue
        if "-->" in s:
            flush()
            m = re.match(r"([\d:.,]+)\s*-->\s*([\d:.,]+)", s)
            cur_start = _ts_to_sec(m.group(1)) if m else None
            cur_end = _ts_to_sec(m.group(2)) if m else None
            continue
        if re.fullmatch(r"\d+", s):                # numeric cue index
            continue
        s = re.sub(r"<[^>]+>", "", s)              # inline word-timing tags
        s = re.sub(r"\{[^}]+\}", "", s)            # cue styling
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            cur_lines.append(s)
    flush()
    return _collapse_rolling(segs)


def _collapse_rolling(segs):
    """Collapse rolling-window caption overlap so segment text reads as clean
    prose (matching the de-duplicated flat transcript). Auto-captions emit cues
    like 'A B C' then 'A B C D E' then 'D E F'; this keeps only each cue's NEW
    words while preserving that cue's start time. Non-rolling (manual) captions,
    where consecutive cues don't overlap, are left unchanged."""
    out = []
    prev = []
    for s in segs:
        words = (s.get("text") or "").split()
        if not words:
            continue
        lp = [w.lower() for w in prev]
        lw = [w.lower() for w in words]
        k = 0
        for j in range(min(len(lp), len(lw)), 0, -1):     # longest suffix==prefix overlap
            if lp[-j:] == lw[:j]:
                k = j
                break
        new = words[k:]
        if not new:                                       # fully contained -> extend end
            if out:
                out[-1]["end"] = s.get("end")
            prev = words
            continue
        out.append({"start": s.get("start"), "end": s.get("end"), "text": " ".join(new)})
        prev = words
    return out


def _download_subs(video_id, mode, langs, tmpdir):
    """Download subtitles with yt-dlp. mode in {'manual','auto'}. Returns
    (plain_text, segments) for the best vtt found, or ('', [])."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    flag = "--write-subs" if mode == "manual" else "--write-auto-subs"
    out_tmpl = str(Path(tmpdir) / "%(id)s.%(ext)s")
    args = [
        "--skip-download", flag,
        "--sub-langs", ",".join(langs), "--sub-format", "vtt",
        "--convert-subs", "vtt", "-o", out_tmpl,
    ] + IMPERSONATE + [url]
    run_ytdlp(args, capture=True)
    # Prefer a clean lang file over the ASR "-orig" variant (which is word-tagged).
    vtts = sorted(Path(tmpdir).glob(f"{video_id}*.vtt"),
                  key=lambda p: ("-orig" in p.name, len(p.name)))
    for vtt in vtts:
        text = _vtt_to_text(vtt)
        if text:
            return text, _parse_vtt_segments(vtt)
    return "", []


def fetch_transcript(video_id, meta):
    """Try manual subs -> auto subs -> youtube-transcript-api.
    Returns (text|None, segments(list), source|None, language). `segments` are
    timed caption cues [{start,end,text}] (seconds) — empty if none obtained."""
    tmpdir = tempfile.mkdtemp(prefix="ytsub_")
    try:
        # 1. manual subtitles
        if meta.get("manual_langs"):
            langs = _pick_langs(meta["manual_langs"], SUB_LANGS_MANUAL)
            if langs:
                text, segs = _download_subs(video_id, "manual", langs, tmpdir)
                if text:
                    return text, segs, "manual", langs[0]
        # 2. auto subtitles
        if meta.get("auto_langs"):
            langs = _pick_langs(meta["auto_langs"], SUB_LANGS_AUTO)
            if langs:
                text, segs = _download_subs(video_id, "auto", langs, tmpdir)
                if text:
                    return text, segs, "auto", langs[0]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 3. youtube-transcript-api fallback
    text, segs, source, lang = _transcript_api_fallback(video_id)
    if text:
        return text, segs, source, lang
    return None, [], None, "en"


def _transcript_api_fallback(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None, [], None, "en"
    try:
        listing = YouTubeTranscriptApi.list_transcripts(video_id)
        tr = None
        for cand in listing:                         # prefer English
            if cand.language_code.lower().startswith("en"):
                tr = cand
                break
        if tr is None:
            tr = next(iter(listing), None)
        if tr is None:
            return None, [], None, "en"
        chunks = tr.fetch()
        segs = []
        for c in chunks:
            t = (c.get("text") or "").strip()
            if not t:
                continue
            start = round(float(c.get("start", 0.0)), 3)
            segs.append({"start": start,
                         "end": round(start + float(c.get("duration", 0.0)), 3),
                         "text": re.sub(r"\s+", " ", t)})
        text = re.sub(r"\s+", " ", " ".join(s["text"] for s in segs)).strip()
        if not text:
            return None, [], None, "en"
        source = "auto" if getattr(tr, "is_generated", True) else "manual"
        return text, segs, source, tr.language_code
    except Exception as exc:                          # noqa: BLE001 — best-effort
        log(f"    transcript-api fallback failed: {type(exc).__name__}")
        return None, [], None, "en"


# --- State ------------------------------------------------------------------
def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("WARNING: state file unreadable; starting fresh")
    return {"channels": {}}


def save_state(state, dry_run):
    if dry_run:
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# --- Core -------------------------------------------------------------------
def fmt_window_start(days):
    start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return start.strftime("%Y%m%d")


def length_bucket(duration):
    if not duration:
        return "long"        # unknown duration -> treat as long (conservative tag)
    return "short" if duration < SHORT_MAX_SECONDS else "long"


def upload_date_iso(yyyymmdd):
    if yyyymmdd and re.fullmatch(r"\d{8}", yyyymmdd):
        return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return None


def process_channel(ch, state, args, total_so_far):
    """Returns (records, stats_dict). records are written by the caller."""
    name = ch["name"]
    source = ch["source"]
    vtype = ch.get("type", "channel")
    section = ch.get("section", "")
    slug = slugify(name)                       # PINNED: folder/state/dedup key
    display = ch.get("display_name") or name   # attribution label (channel_name)
    handle = ch.get("handle") or handle_from_source(source, vtype)

    ch_state = state["channels"].get(slug, {"seen_ids": []})
    seen = set(ch_state.get("seen_ids", []))
    first_run = not ch_state.get("seen_ids") and "last_run" not in ch_state

    window_days = (args.first_run_window_days if first_run else STEADY_WINDOW_DAYS)
    window_start = fmt_window_start(window_days)

    log(f"  {name} [{slug}] — {'first run' if first_run else 'steady'}, "
        f"window {window_days}d")

    listed = list_source(source, vtype, LIST_LIMIT)
    if not listed:
        return [], {"slug": slug, "name": name, "found": 0, "ok": 0, "missing": 0,
                    "error": "no listing (channel resolve/list failed)"}

    new_candidates = [v for v in listed if v["id"] not in seen]
    records = []
    ok = missing = 0
    newest_upload = ch_state.get("last_upload_date")

    for idx, v in enumerate(new_candidates):
        vid = v["id"]
        # global + per-channel caps
        if len(records) >= MAX_NEW_PER_CHANNEL or total_so_far + len(records) >= MAX_NEW_TOTAL:
            # remaining new candidates: leave UNSEEN (they are newer than the cap
            # boundary; we just ran out of budget this run and want them next run)
            break

        meta = get_metadata(vid)
        if meta is None:
            log(f"    {vid}: metadata unavailable — skipping (marked seen)")
            seen.add(vid)
            continue

        upd = meta.get("upload_date")
        if upd and upd < window_start:
            # newest-first listing => this and everything after is out of window.
            # Mark the whole tail seen so old videos are never re-examined.
            for tail in new_candidates[idx:]:
                seen.add(tail["id"])
            log(f"    {vid}: older than window ({upd}) — stop; tail marked seen")
            break

        # Minimum-duration gate (config: minimum_duration_minutes). Skip shorter
        # uploads and mark them seen so they are never re-checked. Unknown
        # duration (0) is kept rather than dropped.
        dur = meta.get("duration") or 0
        min_dur = getattr(args, "min_duration_seconds", 0)
        if min_dur and dur and dur < min_dur:
            log(f"    {vid}: {dur // 60}m < min {min_dur // 60}m — skip (marked seen)")
            seen.add(vid)
            continue

        text, segments, src, lang = fetch_transcript(vid, meta)
        available = bool(text)
        iso = upload_date_iso(upd)
        # Selective attribution: keep curated config display-name/handle when the
        # video is genuinely on this slug's channel; use the real yt-dlp channel
        # for cross-posts. section/tier stay from config; video_title untouched.
        # Output folder stays pinned to `slug` via the private "_slug".
        ch_name, ch_handle = resolve_channel(display, handle, meta)
        record = {
            "_slug": slug,
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "channel_name": ch_name,
            "channel_handle": ch_handle,
            "section": section,
            "tier": ch.get("tier"),
            "video_title": meta.get("title") or v.get("title") or "",
            "upload_date": iso,
            "duration_seconds": meta.get("duration") or 0,
            "length_bucket": length_bucket(meta.get("duration")),
            "transcript_available": available,
            "transcript_source": src,
            "language": lang,
            "transcript": text if available else None,
            # Timed caption cues kept alongside the plain transcript so future
            # records carry timing for timestamp mapping.
            "timestamps_available": bool(segments),
            "transcript_segments": segments if available else None,
            "yt_channel": meta.get("yt_channel"),
            "yt_uploader_id": meta.get("yt_uploader_id"),
            "yt_channel_id": meta.get("yt_channel_id"),
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        records.append(record)
        seen.add(vid)
        if available:
            ok += 1
            log(f"    {vid}: transcript OK ({src}, {len(text)} chars) — {record['video_title'][:60]}")
        else:
            missing += 1
            log(f"    {vid}: NO transcript — {record['video_title'][:60]}")
        if iso and (newest_upload is None or iso > newest_upload):
            newest_upload = iso

    # persist channel state
    ch_state["seen_ids"] = sorted(seen)
    ch_state["last_run"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if newest_upload:
        ch_state["last_upload_date"] = newest_upload
    state["channels"][slug] = ch_state

    return records, {"slug": slug, "name": name, "found": len(records),
                     "ok": ok, "missing": missing, "error": None}


def write_records(records, dry_run):
    base = Path(tempfile.gettempdir()) / "youtube_dryrun" if dry_run else RAW_ROOT
    for r in records:
        # Folder PINNED to the source slug (private "_slug"), never derived from
        # channel_name — per-video relabels can't fragment a channel's folder.
        slug = r.pop("_slug", None) or slugify(r["channel_name"])
        out_dir = base / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{r['video_id']}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")


def write_runlog(stats, totals, dry_run):
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# YouTube collector run — {today}", ""]
    lines.append(f"- Channels processed: {totals['channels']}")
    lines.append(f"- Videos found (new): {totals['found']}")
    lines.append(f"- Transcripts OK: {totals['ok']}")
    lines.append(f"- Transcripts missing: {totals['missing']}")
    hit = (100.0 * totals["ok"] / totals["found"]) if totals["found"] else 0.0
    lines.append(f"- Transcript hit-rate: {hit:.0f}%")
    lines.append("")
    lines.append("## Per channel")
    lines.append("")
    lines.append("| Channel | Found | OK | Missing | Note |")
    lines.append("|---|---|---|---|---|")
    for s in stats:
        note = s["error"] or ""
        lines.append(f"| {s['name']} | {s['found']} | {s['ok']} | {s['missing']} | {note} |")
    zero = [s["name"] for s in stats
            if (s["found"] > 0 and s["ok"] == 0) or s["error"]]
    lines.append("")
    lines.append("## Channels returning ZERO transcripts (watch these)")
    lines.append("")
    if zero:
        for n in zero:
            lines.append(f"- {n}")
    else:
        lines.append("- (none)")
    body = "\n".join(lines) + "\n"

    base = Path(tempfile.gettempdir()) / "youtube_dryrun" / "_runlog" if dry_run else RUNLOG_DIR
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{today}.md").write_text(body, encoding="utf-8")
    print("\n" + body, flush=True)


def parse_args():
    p = argparse.ArgumentParser(description="YouTube/Podcasts collector (Phase 1)")
    p.add_argument("--max-channels", type=int, default=None,
                   help="process only the first N channels (spike test)")
    p.add_argument("--channels", default=None,
                   help="comma-separated slugs or name substrings to restrict to")
    p.add_argument("--first-run-window-days", type=int, default=None,
                   help="override config first_run_window_days")
    p.add_argument("--dry-run", action="store_true",
                   help="write outputs under the temp dir, do not touch repo/state")
    p.add_argument("--diagnose", action="store_true",
                   help="cloud-IP probe: test yt-dlp player clients and exit")
    return p.parse_args()


def main():
    args = parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if args.diagnose:
        diagnose(config)
        return
    if args.first_run_window_days is None:
        args.first_run_window_days = config.get(
            "first_run_window_days", DEFAULT_FIRST_RUN_WINDOW_DAYS)
    args.min_duration_seconds = int(config.get("minimum_duration_minutes", 0)) * 60

    channels = config.get("channels", [])
    if args.channels:
        wanted = [w.strip().lower() for w in args.channels.split(",") if w.strip()]
        channels = [c for c in channels
                    if slugify(c["name"]) in wanted
                    or any(w in c["name"].lower() for w in wanted)]
    if args.max_channels:
        channels = channels[:args.max_channels]

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    log(f"YouTube collector [{mode}] — {len(channels)} source(s), "
        f"first-run window {args.first_run_window_days}d")

    state = load_state()
    all_stats = []
    totals = {"channels": 0, "found": 0, "ok": 0, "missing": 0}

    for ch in channels:
        if totals["found"] >= MAX_NEW_TOTAL:
            log(f"  Global cap {MAX_NEW_TOTAL} reached — stopping.")
            break
        records, stats = process_channel(ch, state, args, totals["found"])
        write_records(records, args.dry_run)
        all_stats.append(stats)
        totals["channels"] += 1
        totals["found"] += stats["found"]
        totals["ok"] += stats["ok"]
        totals["missing"] += stats["missing"]

    save_state(state, args.dry_run)
    write_runlog(all_stats, totals, args.dry_run)
    log(f"Done. {totals['ok']}/{totals['found']} transcripts OK "
        f"across {totals['channels']} channel(s).")


if __name__ == "__main__":
    main()
