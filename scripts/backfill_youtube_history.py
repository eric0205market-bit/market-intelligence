#!/usr/bin/env python3
"""YouTube historical-backfill collector.

COMPLETELY SEPARATE from the daily pipeline (scripts/collect_youtube.py).
- Manual trigger only; NOT run by launchd or GitHub Actions.
- Writes to HISTORY_ROOT outside the git repo (never committed).
- Reads the 77-channel config but never touches daily raw/state files.

WHAT IT DOES
  For each channel, walks back through uploads (newest-first) to
  BACKFILL_START (default 2025-01-01), fetching >=25-min transcripts
  not already present in either the daily corpus or the history folder.

THROTTLING (stricter than daily)
  - Sequential only; no concurrency.
  - 15-45 s random sleep after every per-video yt-dlp call.
  - 2-5 min random pause between channels.
  - 10-25 s sleep before each listing batch.
  - --limit-rate 500K on subtitle downloads.
  - Hard session cap (default 30 videos).

HARD STOP on ANY of:
  - HTTP 429 / "Too Many Requests" in yt-dlp stderr
  - bot-check / consent / sign-in signals in stderr
  - 3+ consecutive metadata failures in a row
  Saves state and exits immediately with code 10. Do NOT retry in a loop.

USAGE
  python3 scripts/backfill_youtube_history.py --canary --channels "all_in_podcast,wealthion"
  python3 scripts/backfill_youtube_history.py --channels "all_in_podcast" --session-cap 20
  python3 scripts/backfill_youtube_history.py  # full run (all 77 channels)

Storage layout:
  ~/Dropbox (Personal)/Business/InvestTool/market-intelligence/youtube-history/
    {slug}/{video_id}.json   — same JSON schema as daily + "backfill": true
    _state/backfill_state.json
    _runlog/{timestamp}.md
"""
import argparse
import datetime
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Paths — DAILY pipeline (read-only references)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DAILY_CONFIG_PATH = REPO_ROOT / "config" / "youtube_sources_full.json"
DAILY_RAW_ROOT = REPO_ROOT / "raw" / "youtube"
DAILY_STATE_PATH = REPO_ROOT / "state" / "youtube_seen.json"

# History root — OUTSIDE the git repo, never committed
DEFAULT_HISTORY_ROOT = (
    Path.home()
    / "Dropbox (Personal)"
    / "Business"
    / "InvestTool"
    / "market-intelligence"
    / "youtube-history"
)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
BACKFILL_START_DEFAULT = "2025-01-01"   # walk back to this date
MIN_DURATION_MINUTES_DEFAULT = 25       # mirrors daily config default
SESSION_CAP_DEFAULT = 30                # hard cap per manual run
LIST_BATCH_SIZE = 25                    # videos per yt-dlp listing call
CONSECUTIVE_FAIL_ABORT = 3             # consecutive metadata failures = abort

SLEEP_VIDEO_MIN = 15.0      # s — between each per-video yt-dlp sequence
SLEEP_VIDEO_MAX = 45.0
SLEEP_CHANNEL_MIN = 120.0   # s — between channels (2 min)
SLEEP_CHANNEL_MAX = 300.0   # s — between channels (5 min)
SLEEP_LISTING_MIN = 10.0    # s — before each listing batch
SLEEP_LISTING_MAX = 25.0

YTDLP_TIMEOUT = 120         # s per subprocess call
IMPERSONATE = ["--extractor-args", "youtube:player_client=default,web_safari"]
SUB_LANGS_MANUAL = "en,en-US,en-GB,en-CA,en-AU,en-IE"
SUB_LANGS_AUTO = "en,en-US,en-GB"

# Patterns that indicate rate-limiting or bot-check in yt-dlp stderr
_BOT_PATTERNS = [
    r"HTTP Error 429",
    r"Too Many Requests",
    r"confirm you.{0,30}not a (robot|bot)",
    r"are you a (robot|bot)",
    r"consent\.youtube\.com",
    r"Sign in to confirm",
    r"please sign in",
    r"verify.{0,20}(human|robot)",
    r"unusual traffic",
]
_BOT_RE = re.compile("|".join(_BOT_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def log_hard_stop(reason: str, stderr_tail: str = "") -> None:
    bar = "=" * 70
    print(f"\n{bar}", flush=True)
    print("HARD STOP — bot-check / rate-limit signal detected", flush=True)
    print(f"  Reason : {reason}", flush=True)
    if stderr_tail:
        print(f"  Stderr : {stderr_tail}", flush=True)
    print("  Action : state saved; exiting code 10; do NOT retry.", flush=True)
    print(bar, flush=True, file=sys.stderr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "channel"


def handle_from_source(source: str, vtype: str) -> str:
    if vtype == "playlist":
        qs = parse_qs(urlparse(source).query)
        return (qs.get("list") or [""])[0]
    m = re.search(r"/(@[^/?#]+)", source)
    return m.group(1) if m else source


def _norm_handle(h) -> str:
    return str(h or "").lstrip("@").strip().lower()


def resolve_channel(name: str, cfg_handle: str, meta: dict) -> tuple[str, str]:
    """Per-video selective attribution. Compare the video's real uploader
    (yt-dlp uploader_id) to the slug's CONFIGURED handle:
      • MATCH  -> keep the curated config channel_name/handle (preserves host
                  suffixes and sub-show names, e.g. Animal Spirits on @TheCompoundNews).
      • DIFFER -> genuine cross-post: use the real yt-dlp channel + uploader_id.
    section/tier come from config; video_title is never touched here.
    Falls back to config when yt-dlp gave no uploader_id."""
    yt_uid = str(meta.get("yt_uploader_id") or "").strip()
    if yt_uid and _norm_handle(yt_uid) and _norm_handle(yt_uid) != _norm_handle(cfg_handle):
        ytc = str(meta.get("yt_channel") or "").strip()
        return (ytc or name, yt_uid if yt_uid.startswith("@") else "@" + yt_uid)
    return name, cfg_handle


def upload_date_iso(yyyymmdd) -> str | None:
    if yyyymmdd and re.fullmatch(r"\d{8}", str(yyyymmdd)):
        return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return None


def length_bucket(duration) -> str:
    if not duration:
        return "long"
    return "short" if duration < 20 * 60 else "long"


def sleep_v(label: str = "") -> None:
    secs = random.uniform(SLEEP_VIDEO_MIN, SLEEP_VIDEO_MAX)
    log(f"  [throttle] sleeping {secs:.0f}s {label}")
    time.sleep(secs)


def sleep_listing() -> None:
    secs = random.uniform(SLEEP_LISTING_MIN, SLEEP_LISTING_MAX)
    log(f"  [throttle] {secs:.0f}s before listing batch")
    time.sleep(secs)


def sleep_channel() -> None:
    secs = random.uniform(SLEEP_CHANNEL_MIN, SLEEP_CHANNEL_MAX)
    log(f"[throttle] inter-channel pause: {secs:.0f}s ({secs / 60:.1f} min)")
    time.sleep(secs)


# ---------------------------------------------------------------------------
# yt-dlp wrapper
# ---------------------------------------------------------------------------
def run_ytdlp(args: list[str], timeout: int = YTDLP_TIMEOUT):
    """Run yt-dlp; returns (returncode, stdout, stderr). Never raises."""
    cmd = ["yt-dlp", "--ignore-config", "--no-warnings", "--no-progress"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        log("FATAL: yt-dlp not found on PATH")
        sys.exit(2)


def _check_stderr_for_bot(rc: int, err: str) -> None:
    """Raise SystemExit(10) immediately if stderr signals bot-check or 429."""
    m = _BOT_RE.search(err or "")
    if m:
        tail = err.strip()[-400:]
        log_hard_stop(f"pattern match: {m.group()!r}", tail)
        raise SystemExit(10)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
def list_source_batch(source: str, vtype: str, start_idx: int, batch_size: int) -> list[dict]:
    """Fetch a batch of uploads (newest-first). start_idx is 1-based inclusive."""
    url = source
    if vtype == "channel":
        base = url.rstrip("/")
        url = base if base.endswith("/videos") else base + "/videos"
    end_idx = start_idx + batch_size - 1
    args = [
        "--flat-playlist",
        "-I", f"{start_idx}-{end_idx}",
        "--print", "%(id)s\t%(title)s",
    ] + IMPERSONATE + [url]
    rc, out, err = run_ytdlp(args)
    _check_stderr_for_bot(rc, err)

    entries = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        vid = vid.strip()
        if vid and vid != "NA":
            entries.append({"id": vid, "title": title.strip()})

    if not entries and rc != 0:
        last = err.strip().splitlines()[-1][:160] if err.strip() else "no output"
        log(f"    listing {start_idx}-{end_idx}: no results (rc={rc}): {last}")
    return entries


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def get_metadata(video_id: str) -> dict | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    args = ["--skip-download", "--dump-json"] + IMPERSONATE + [url]
    rc, out, err = run_ytdlp(args)
    _check_stderr_for_bot(rc, err)
    if rc != 0 or not out.strip():
        if err.strip():
            log(f"      metadata rc={rc}: {err.strip().splitlines()[-1][:160]}")
        return None
    try:
        d = json.loads(out.splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return None
    return {
        "title": d.get("title") or "",
        "upload_date": d.get("upload_date"),
        "duration": d.get("duration"),
        "manual_langs": list((d.get("subtitles") or {}).keys()),
        "auto_langs": list((d.get("automatic_captions") or {}).keys()),
        # Ground-truth posting channel (previously not captured) — for selective
        # per-video attribution and stored on the record.
        "yt_channel": d.get("channel"),
        "yt_uploader_id": d.get("uploader_id"),
        "yt_channel_id": d.get("channel_id"),
    }


# ---------------------------------------------------------------------------
# Transcript fetching (mirrors daily collector logic exactly)
# ---------------------------------------------------------------------------
def _pick_langs(available: list, wanted_csv: str) -> list[str]:
    avail = set(available)
    picked = [w for w in wanted_csv.split(",") if w in avail]
    if picked:
        return picked
    en_like = [a for a in available
               if a.lower().startswith("en") and not a.lower().endswith("-orig")]
    return en_like[:1] or [a for a in available if a.lower().startswith("en")][:1]


def _vtt_to_text(vtt_path: Path) -> str:
    try:
        raw = vtt_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines_out, last = [], None
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == "WEBVTT" or s.startswith(("Kind:", "Language:", "NOTE", "STYLE")):
            continue
        if "-->" in s or re.fullmatch(r"\d+", s):
            continue
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"\{[^}]+\}", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        if not s or s == last:
            continue
        lines_out.append(s)
        last = s
    return " ".join(lines_out).strip()


def _ts_to_sec(ts: str) -> float | None:
    parts = ts.strip().replace(",", ".").split(":")
    try:
        sec = 0.0
        for p in parts:
            sec = sec * 60 + float(p)
        return round(sec, 3)
    except ValueError:
        return None


def _parse_vtt_segments(vtt_path: Path) -> list[dict]:
    try:
        raw = vtt_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    segs, cur_start, cur_end, cur_lines = [], None, None, []

    def flush():
        nonlocal cur_lines, cur_start, cur_end
        if cur_start is not None and cur_lines:
            txt = re.sub(r"\s+", " ", " ".join(cur_lines)).strip()
            if txt:
                segs.append({"start": cur_start, "end": cur_end, "text": txt})
        cur_lines.clear()

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
        if re.fullmatch(r"\d+", s):
            continue
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"\{[^}]+\}", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            cur_lines.append(s)
    flush()
    return _collapse_rolling(segs)


def _collapse_rolling(segs: list[dict]) -> list[dict]:
    out, prev = [], []
    for s in segs:
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


def _download_subs(video_id: str, mode: str, langs: list[str], tmpdir: str):
    url = f"https://www.youtube.com/watch?v={video_id}"
    flag = "--write-subs" if mode == "manual" else "--write-auto-subs"
    out_tmpl = str(Path(tmpdir) / "%(id)s.%(ext)s")
    args = [
        "--skip-download", flag,
        "--sub-langs", ",".join(langs), "--sub-format", "vtt",
        "--convert-subs", "vtt", "-o", out_tmpl,
        "--limit-rate", "500K",
    ] + IMPERSONATE + [url]
    rc, out, err = run_ytdlp(args)
    _check_stderr_for_bot(rc, err)
    vtts = sorted(Path(tmpdir).glob(f"{video_id}*.vtt"),
                  key=lambda p: ("-orig" in p.name, len(p.name)))
    for vtt in vtts:
        text = _vtt_to_text(vtt)
        if text:
            return text, _parse_vtt_segments(vtt)
    return "", []


def _transcript_api_fallback(video_id: str):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None, [], None, "en"
    try:
        listing = YouTubeTranscriptApi.list_transcripts(video_id)
        tr = None
        for cand in listing:
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
            segs.append({
                "start": start,
                "end": round(start + float(c.get("duration", 0.0)), 3),
                "text": re.sub(r"\s+", " ", t),
            })
        text = re.sub(r"\s+", " ", " ".join(s["text"] for s in segs)).strip()
        if not text:
            return None, [], None, "en"
        source = "auto" if getattr(tr, "is_generated", True) else "manual"
        return text, segs, source, tr.language_code
    except Exception as exc:
        log(f"    transcript-api fallback failed: {type(exc).__name__}")
        return None, [], None, "en"


def fetch_transcript(video_id: str, meta: dict):
    """Returns (text|None, segments, source|None, language)."""
    tmpdir = tempfile.mkdtemp(prefix="ytbf_")
    try:
        if meta.get("manual_langs"):
            langs = _pick_langs(meta["manual_langs"], SUB_LANGS_MANUAL)
            if langs:
                text, segs = _download_subs(video_id, "manual", langs, tmpdir)
                if text:
                    return text, segs, "manual", langs[0]
        if meta.get("auto_langs"):
            langs = _pick_langs(meta["auto_langs"], SUB_LANGS_AUTO)
            if langs:
                text, segs = _download_subs(video_id, "auto", langs, tmpdir)
                if text:
                    return text, segs, "auto", langs[0]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    text, segs, source, lang = _transcript_api_fallback(video_id)
    if text:
        return text, segs, source, lang
    return None, [], None, "en"


# ---------------------------------------------------------------------------
# Dedup — collect all video IDs already known for a channel
# ---------------------------------------------------------------------------
def collect_known_ids(slug: str, history_root: Path) -> set[str]:
    known: set[str] = set()
    for folder in (history_root / slug, DAILY_RAW_ROOT / slug):
        if folder.exists():
            known.update(f.stem for f in folder.glob("*.json"))
    # NOTE: daily state seen_ids intentionally excluded.
    # seen_ids = "this ID was listed/examined by the daily pipeline."
    # It does NOT mean a transcript file was written.
    # Dedup is file-based only: if no file exists, the video needs backfilling.
    return known


# ---------------------------------------------------------------------------
# Backfill state (separate from daily state — lives in history_root/_state/)
# ---------------------------------------------------------------------------
_STATE_PATH = "_state/backfill_state.json"


def load_backfill_state(history_root: Path) -> dict:
    p = history_root / _STATE_PATH
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("WARNING: backfill state unreadable; starting fresh")
    return {"channels": {}}


def save_backfill_state(state: dict, history_root: Path, dry_run: bool) -> None:
    if dry_run:
        return
    p = history_root / _STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Write a fetched record to the history folder
# ---------------------------------------------------------------------------
def write_record(record: dict, history_root: Path, dry_run: bool) -> None:
    if dry_run:
        return
    # Output folder is PINNED to the source slug (carried on the record as a
    # private "_slug"), never derived from channel_name — so per-video relabels
    # (cross-posts, display names) cannot fragment a channel's folder. Falls back
    # to slugify(channel_name) only for legacy records without _slug.
    slug = record.pop("_slug", None) or slugify(record["channel_name"])
    out_dir = history_root / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{record['video_id']}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Per-channel backfill
# ---------------------------------------------------------------------------
def process_channel(
    ch: dict,
    backfill_state: dict,
    history_root: Path,
    session_cap: int,
    fetched_this_session: int,
    backfill_start: str,
    min_duration_seconds: int,
    dry_run: bool,
    per_channel_cap: int | None = None,
) -> tuple[int, str]:
    """
    Walk this channel backward and fetch missing transcripts.

    Returns (fetched_count, stop_reason).
    Raises SystemExit(10) on bot-check; caller must save state first.
    """
    name = ch["name"]
    source = ch["source"]
    vtype = ch.get("type", "channel")
    slug = slugify(name)                       # PINNED: folder/state/dedup key
    display = ch.get("display_name") or name   # attribution label (channel_name)
    handle = ch.get("handle") or handle_from_source(source, vtype)

    ch_state = backfill_state["channels"].setdefault(slug, {
        "fetched_ids": [],
        "oldest_seen_date": None,
        "completed": False,
        "playlist_offset": 1,
        "last_session": None,
    })

    if ch_state.get("completed"):
        log(f"  {name}: already completed (walked to {backfill_start}) — skip")
        return 0, "already_completed"

    playlist_offset: int = ch_state.get("playlist_offset", 1)
    known_ids = collect_known_ids(slug, history_root)
    fetched_ids_set: set[str] = set(ch_state.get("fetched_ids", []))

    log(f"  {name} [{slug}]")
    log(f"    offset={playlist_offset}, known={len(known_ids)}, "
        f"backfill_fetched={len(fetched_ids_set)}")

    fetched_this_channel = 0
    stop_reason = "session_cap"
    consecutive_meta_failures = 0
    consecutive_pre_cutoff = 0     # counts consecutive pre-cutoff items (hardening against stray pins)

    while fetched_this_session + fetched_this_channel < session_cap:
        # ---- listing batch ----
        sleep_listing()
        log(f"    listing items {playlist_offset}-{playlist_offset + LIST_BATCH_SIZE - 1}")
        batch = list_source_batch(source, vtype, playlist_offset, LIST_BATCH_SIZE)

        if not batch:
            log(f"    no more videos at offset {playlist_offset} — channel exhausted")
            ch_state["completed"] = True
            stop_reason = "exhausted"
            break

        past_cutoff = False
        for v in batch:
            vid = v["id"]

            if fetched_this_session + fetched_this_channel >= session_cap:
                stop_reason = "session_cap"
                past_cutoff = True     # break outer loop too
                break

            if per_channel_cap is not None and fetched_this_channel >= per_channel_cap:
                stop_reason = "per_channel_cap"
                past_cutoff = True
                break

            if vid in known_ids or vid in fetched_ids_set:
                log(f"    {vid}: already known — skip")
                continue

            # ---- metadata ----
            meta = get_metadata(vid)
            if meta is None:
                consecutive_meta_failures += 1
                log(f"    {vid}: metadata unavailable (fail #{consecutive_meta_failures}) — skip")
                if consecutive_meta_failures >= CONSECUTIVE_FAIL_ABORT:
                    log_hard_stop(
                        f"{CONSECUTIVE_FAIL_ABORT} consecutive metadata failures — "
                        "possible throttle or block"
                    )
                    raise SystemExit(10)
                known_ids.add(vid)
                sleep_v(f"(post-skip {vid})")
                continue
            consecutive_meta_failures = 0   # reset on success

            upd = meta.get("upload_date")
            iso = upload_date_iso(upd)

            if iso and iso < backfill_start:
                # Require 2 CONSECUTIVE pre-cutoff items before marking complete.
                # A single stray pinned/out-of-order video must not false-complete the channel.
                consecutive_pre_cutoff += 1
                known_ids.add(vid)   # don't re-examine this item in future sessions
                if consecutive_pre_cutoff >= 2:
                    log(f"    {vid}: upload {iso} — 2nd consecutive pre-cutoff, marking complete")
                    ch_state["completed"] = True
                    stop_reason = "past_cutoff"
                    past_cutoff = True
                    break
                else:
                    log(f"    {vid}: upload {iso} — 1st pre-cutoff (stray?), skipping; need 2 consecutive")
                    sleep_v(f"(post-skip {vid})")
                    continue
            else:
                consecutive_pre_cutoff = 0   # reset: post-cutoff video breaks the consecutive run

            dur = meta.get("duration") or 0
            if min_duration_seconds and dur and dur < min_duration_seconds:
                log(f"    {vid}: {dur // 60}m < {min_duration_seconds // 60}m min — skip")
                known_ids.add(vid)
                sleep_v(f"(post-skip {vid})")
                continue

            # ---- transcript ----
            log(f"    {vid}: fetching transcript [{meta['title'][:55]}]")
            text, segments, src, lang = fetch_transcript(vid, meta)
            available = bool(text)

            # Selective attribution: keep curated config display-name/handle when the
            # video is genuinely on this slug's channel; use the real yt-dlp channel
            # for cross-posts. section/tier stay from config; video_title untouched.
            # `display` is the attribution label (display_name override or name);
            # the output folder stays pinned to `slug` via the private "_slug".
            ch_name, ch_handle = resolve_channel(display, handle, meta)

            record = {
                "_slug": slug,
                "video_id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "channel_name": ch_name,
                "channel_handle": ch_handle,
                "section": ch.get("section", ""),
                "tier": ch.get("tier"),
                "video_title": meta.get("title") or v.get("title") or "",
                "upload_date": iso,
                "duration_seconds": dur,
                "length_bucket": length_bucket(dur),
                "transcript_available": available,
                "transcript_source": src,
                "language": lang,
                "transcript": text if available else None,
                "timestamps_available": bool(segments),
                "transcript_segments": segments if available else None,
                "yt_channel": meta.get("yt_channel"),
                "yt_uploader_id": meta.get("yt_uploader_id"),
                "yt_channel_id": meta.get("yt_channel_id"),
                "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "backfill": True,
            }
            write_record(record, history_root, dry_run)

            fetched_ids_set.add(vid)
            known_ids.add(vid)
            fetched_this_channel += 1

            log(f"    {vid}: {'OK ' + src + ' ' + str(len(text)) + 'ch' if available else 'NO transcript'}")

            if iso and (ch_state["oldest_seen_date"] is None or iso < ch_state["oldest_seen_date"]):
                ch_state["oldest_seen_date"] = iso

            sleep_v(f"(post-video {vid})")

        if past_cutoff or ch_state.get("completed"):
            break

        playlist_offset += LIST_BATCH_SIZE
        ch_state["playlist_offset"] = playlist_offset

    # persist updated channel state
    ch_state["fetched_ids"] = sorted(fetched_ids_set)
    ch_state["playlist_offset"] = playlist_offset
    ch_state["last_session"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    log(f"  {name}: +{fetched_this_channel} this session, "
        f"total_backfilled={len(fetched_ids_set)}, stop={stop_reason}")
    return fetched_this_channel, stop_reason


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------
def write_runlog(
    history_root: Path,
    channel_results: list[tuple[str, int, str]],
    session_total: int,
    session_cap: int,
    dry_run: bool,
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H%M%S")
    lines = [f"# YouTube backfill — {now.strftime('%Y-%m-%d %H:%M:%S UTC')}", ""]
    lines += [
        f"- session_cap: {session_cap}",
        f"- total fetched this session: {session_total}",
        f"- dry_run: {dry_run}",
        "",
        "## Per channel",
        "",
        "| Channel | Fetched | Stop reason |",
        "|---|---|---|",
    ]
    for ch_name, fetched, reason in channel_results:
        lines.append(f"| {ch_name} | {fetched} | {reason} |")
    body = "\n".join(lines) + "\n"
    if not dry_run:
        log_dir = history_root / "_runlog"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{ts}.md").write_text(body, encoding="utf-8")
    print("\n" + body, flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="YouTube historical backfill (SEPARATE from daily pipeline)"
    )
    p.add_argument(
        "--history-root",
        default=str(DEFAULT_HISTORY_ROOT),
        help="History storage folder (outside git repo, default: %(default)s)",
    )
    p.add_argument(
        "--channels",
        default=None,
        help="Comma-separated slugs or name substrings to restrict to",
    )
    p.add_argument(
        "--session-cap",
        type=int,
        default=SESSION_CAP_DEFAULT,
        help=f"Max videos to fetch per run (default {SESSION_CAP_DEFAULT})",
    )
    p.add_argument(
        "--backfill-start",
        default=BACKFILL_START_DEFAULT,
        help=f"Walk back to this date YYYY-MM-DD (default {BACKFILL_START_DEFAULT})",
    )
    p.add_argument(
        "--canary",
        action="store_true",
        help="Canary mode: forces --session-cap 10; requires --channels",
    )
    p.add_argument(
        "--per-channel-cap",
        type=int,
        default=None,
        metavar="N",
        help="Max videos fetched per channel per session (default: unlimited). "
             "Saves playlist offset so the channel resumes on the next cursor rotation.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log only; do not write files or save state",
    )
    return p.parse_args()


def main():
    args = parse_args()

    if args.canary:
        if not args.channels:
            print("ERROR: --canary requires --channels (specify 1-2 channels)", file=sys.stderr)
            sys.exit(1)
        args.session_cap = min(args.session_cap, 10)
        log("CANARY MODE — session cap clamped to 10, full conservative pacing")

    history_root = Path(args.history_root).expanduser()
    history_root.mkdir(parents=True, exist_ok=True)

    config = json.loads(DAILY_CONFIG_PATH.read_text(encoding="utf-8"))
    min_duration_seconds = int(config.get("minimum_duration_minutes", MIN_DURATION_MINUTES_DEFAULT)) * 60
    all_channels = config.get("channels", [])
    total_roster = len(all_channels)

    backfill_state = load_backfill_state(history_root)

    # --- Channel selection and persisted roster cursor ---
    # Full-roster mode: rotate the channel list each session so the 30-video cap
    # is spread evenly across all 77 channels over successive runs.  The cursor
    # (stored in state) points to the index in all_channels where the next session
    # should begin.  Explicit --channels overrides this and leaves the cursor alone.
    if args.channels:
        wanted = [w.strip().lower() for w in args.channels.split(",") if w.strip()]
        channels = [
            c for c in all_channels
            if slugify(c["name"]) in wanted
            or any(w in c["name"].lower() for w in wanted)
        ]
        if not channels:
            log(f"ERROR: no channels matched {wanted!r} in config")
            sys.exit(1)
        cursor = None   # explicit filter — roster cursor does not apply
    else:
        cursor = backfill_state.get("roster_cursor", 0)
        channels = all_channels[cursor:] + all_channels[:cursor]

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    log(f"=== YouTube backfill [{mode}] ===")
    log(f"  channels     : {len(channels)} of {total_roster}")
    log(f"  session_cap  : {args.session_cap}")
    log(f"  backfill_start: {args.backfill_start}")
    log(f"  min_duration : {min_duration_seconds // 60}m")
    log(f"  history_root : {history_root}")
    if args.per_channel_cap is not None:
        log(f"  per_channel_cap: {args.per_channel_cap}")
    if cursor is not None:
        log(f"  roster_cursor: {cursor}/{total_roster} → starting at '{channels[0]['name']}'")
    log("")

    channel_results: list[tuple[str, int, str]] = []
    total_fetched = 0
    channels_started = 0   # how many channels we actually entered this session

    for i, ch in enumerate(channels):
        if total_fetched >= args.session_cap:
            log(f"Session cap {args.session_cap} reached — stopping after {channels_started} channels.")
            break

        channels_started += 1

        try:
            fetched, stop_reason = process_channel(
                ch, backfill_state, history_root,
                args.session_cap, total_fetched,
                args.backfill_start, min_duration_seconds, args.dry_run,
                per_channel_cap=args.per_channel_cap,
            )
        except SystemExit as exc:
            if exc.code == 10:
                # advance cursor past the channel that triggered the stop
                if cursor is not None:
                    backfill_state["roster_cursor"] = (cursor + channels_started) % total_roster
                save_backfill_state(backfill_state, history_root, args.dry_run)
                channel_results.append((ch["name"], 0, "HARD_STOP_BOT_CHECK"))
                write_runlog(history_root, channel_results, total_fetched,
                             args.session_cap, args.dry_run)
                sys.exit(10)
            raise

        channel_results.append((ch["name"], fetched, stop_reason))
        total_fetched += fetched

        # Update and persist cursor after every channel so state is crash-safe.
        if cursor is not None:
            backfill_state["roster_cursor"] = (cursor + channels_started) % total_roster
        save_backfill_state(backfill_state, history_root, args.dry_run)

        # inter-channel pause (skip after last channel or when cap reached)
        if i < len(channels) - 1 and total_fetched < args.session_cap:
            sleep_channel()

    write_runlog(history_root, channel_results, total_fetched, args.session_cap, args.dry_run)
    if cursor is not None:
        next_c = backfill_state.get("roster_cursor", cursor)
        log(f"  roster_cursor → {next_c}/{total_roster} "
            f"(next session starts at '{all_channels[next_c]['name']}')")
    log(f"Done. Fetched {total_fetched} videos this session.")


if __name__ == "__main__":
    main()
