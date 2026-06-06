#!/usr/bin/env python3
"""Render a standalone YouTube insights digest (one HTML file, openable directly).

Deterministic: reads processed/youtube/*.json (the insight records extracted by
Claude) and emits youtube_digests/<date>.html. No intelligence here — all the
judgment lives in the processed records; this only lays them out.

Layout: episodes grouped by channel; each episode is an expandable <details>
card (header + gist + theme chips with counts); expanding reveals the themes
and, under each, the insights with type/speaker/entity chips and a quote +
timestamp where present.

Usage: python3 scripts/render_youtube_digest.py [--date YYYY-MM-DD]
"""
import argparse
import datetime
import glob
import html
import json
import os
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROCESSED = REPO / "processed" / "youtube"
OUT_DIR = REPO / "reports"

TYPE_COLORS = {
    "thesis": "#6366f1", "prediction": "#0ea5e9", "framework": "#8b5cf6",
    "data_point": "#059669", "causal": "#d97706", "contrarian": "#dc2626",
    "anecdote": "#64748b",
}
CONV_COLORS = {"high": "#16a34a", "medium": "#ca8a04", "low": "#94a3b8",
               "exploratory": "#94a3b8"}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def ts_link(url, ts):
    """Turn HH:MM:SS / MM:SS into a YouTube ?t= deep link, if present."""
    if not ts:
        return ""
    parts = str(ts).split(":")
    try:
        sec = 0
        for p in parts:
            sec = sec * 60 + int(p)
    except ValueError:
        return f'<span class="ts">{esc(ts)}</span>'
    sep = "&" if "?" in url else "?"
    return f'<a class="ts" href="{esc(url)}{sep}t={sec}s" target="_blank" rel="noopener">▶ {esc(ts)}</a>'


def chip(text, color=None, cls="chip"):
    style = f' style="background:{color}1a;color:{color};border-color:{color}55"' if color else ""
    return f'<span class="{cls}"{style}>{esc(text)}</span>'


def render_insight(ins):
    t = ins.get("type", "")
    parts = [f'<div class="insight">']
    parts.append('<div class="i-claim">' + esc(ins.get("claim", "")) + "</div>")
    meta = []
    if t:
        meta.append(chip(t, TYPE_COLORS.get(t, "#475569")))
    if ins.get("speaker"):
        meta.append(chip("🗣 " + ins["speaker"], cls="chip chip-spk"))
    conv = ins.get("conviction")
    if conv:
        meta.append(chip("conviction: " + conv, CONV_COLORS.get(conv, "#64748b")))
    for e in (ins.get("entities") or [])[:12]:
        meta.append(chip(e, cls="chip chip-ent"))
    parts.append('<div class="i-meta">' + "".join(meta) + "</div>")
    if ins.get("so_what"):
        parts.append('<div class="i-sowhat"><b>So what:</b> ' + esc(ins["so_what"]) + "</div>")
    if ins.get("quote"):
        verified = ins.get("quote_verified", True)
        if verified:
            q = '<div class="i-quote">“' + esc(ins["quote"]) + "”"
        else:
            q = ('<div class="i-quote i-para">≈ “' + esc(ins["quote"]) + "” "
                 '<span class="para-tag" title="Not found verbatim in the auto-caption transcript — treat as a close paraphrase, not an exact quote.">paraphrase</span>')
        if ins.get("timestamp") and ins.get("_url"):
            q += " " + ts_link(ins["_url"], ins["timestamp"])
        elif ins.get("timestamp"):
            q += ' <span class="ts">' + esc(ins["timestamp"]) + "</span>"
        q += "</div>"
        parts.append(q)
    parts.append("</div>")
    return "".join(parts)


def render_episode(rec):
    url = rec.get("url", "")
    themes = rec.get("themes", []) or []
    n_ins = sum(len(t.get("insights", []) or []) for t in themes)
    dur = rec.get("duration_minutes") or round((rec.get("duration_seconds") or 0) / 60)
    head = (
        f'<summary class="ep-sum">'
        f'<span class="ep-title">{esc(rec.get("video_title",""))}</span>'
        f'<span class="ep-badges">'
        f'{chip(str(dur)+" min")}'
        f'{chip(str(n_ins)+" insights", "#6366f1")}'
        f'{chip(esc(rec.get("upload_date","")))}'
        f'</span></summary>'
    )
    body = ['<div class="ep-body">']
    if url:
        body.append(f'<div class="ep-link"><a href="{esc(url)}" target="_blank" rel="noopener">▶ Watch on YouTube</a></div>')
    if rec.get("gist"):
        body.append('<div class="ep-gist">' + esc(rec["gist"]) + "</div>")
    # theme-count chips
    tchips = "".join(chip(f'{t.get("theme","")} · {len(t.get("insights",[]) or [])}', "#0ea5e9")
                     for t in themes)
    body.append('<div class="ep-themes-row">' + tchips + "</div>")
    for t in themes:
        body.append('<div class="theme">')
        body.append('<div class="theme-h">' + esc(t.get("theme", "")) +
                    f' <span class="theme-n">{len(t.get("insights",[]) or [])}</span></div>')
        for ins in t.get("insights", []) or []:
            ins["_url"] = url
            body.append(render_insight(ins))
        body.append("</div>")
    body.append("</div>")
    return f'<details class="ep">{head}{"".join(body)}</details>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    # NEW-ONLY per-day reports (like the other routines): restrict the digest to
    # a specific run's episodes. --ids is the explicit list; with neither flag we
    # fall back to records whose processed_at date == --date. (No more cumulative.)
    ap.add_argument("--ids", default=None,
                    help="comma-separated video_ids to include (this run's new episodes)")
    args = ap.parse_args()
    date = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    files = sorted(glob.glob(str(PROCESSED / "*.json")))
    recs = []
    for f in files:
        try:
            recs.append(json.load(open(f)))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARN: skip {f}: {e}")

    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        recs = [r for r in recs if r.get("video_id") in wanted]
    else:
        recs = [r for r in recs if (r.get("processed_at") or "")[:10] == date]

    # group by channel
    by_ch = defaultdict(list)
    for r in recs:
        by_ch[r.get("channel_name", "Unknown")].append(r)
    for ch in by_ch:
        by_ch[ch].sort(key=lambda r: -(r.get("duration_seconds") or 0))

    total_ins = sum(sum(len(t.get("insights", []) or []) for t in (r.get("themes") or []))
                    for r in recs)

    blocks = []
    for ch in sorted(by_ch, key=lambda c: -sum(
            sum(len(t.get("insights", []) or []) for t in (r.get("themes") or []))
            for r in by_ch[c])):
        eps = by_ch[ch]
        ch_ins = sum(sum(len(t.get("insights", []) or []) for t in (r.get("themes") or []))
                     for r in eps)
        ep_html = "".join(render_episode(r) for r in eps)
        blocks.append(
            f'<section class="ch"><h2 class="ch-h">{esc(ch)} '
            f'<span class="ch-meta">{len(eps)} episode(s) · {ch_ins} insights</span></h2>{ep_html}</section>'
        )

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Insights Digest — {date}</title>
<style>
:root {{ --bg:#f6f7fb; --card:#ffffff; --card2:#f1f3f9; --tx:#1b2230; --mut:#5b6478; --br:#dde2ec; --acc:#4f46e5; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--tx); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
.wrap {{ max-width:1040px; margin:0 auto; padding:28px 20px 80px; }}
header.top {{ border-bottom:1px solid var(--br); padding-bottom:18px; margin-bottom:22px; }}
header.top h1 {{ margin:0 0 6px; font-size:24px; }}
header.top .sub {{ color:var(--mut); font-size:14px; }}
.controls {{ margin:14px 0 0; display:flex; gap:10px; }}
.controls button {{ background:var(--card2); color:var(--tx); border:1px solid var(--br); border-radius:8px; padding:7px 12px; cursor:pointer; font-size:13px; }}
.controls button:hover {{ border-color:var(--acc); }}
.ch {{ margin:0 0 30px; }}
.ch-h {{ font-size:18px; margin:0 0 12px; padding:8px 0; border-bottom:1px solid var(--br); position:sticky; top:0; background:var(--bg); z-index:2; }}
.ch-meta {{ color:var(--mut); font-size:13px; font-weight:400; }}
.ep {{ background:var(--card); border:1px solid var(--br); border-radius:12px; margin:0 0 12px; overflow:hidden; }}
.ep {{ box-shadow:0 1px 2px rgba(16,24,40,.05); }}
.ep[open] {{ border-color:#c7d2fe; }}
.ep-sum {{ cursor:pointer; padding:14px 16px; display:flex; justify-content:space-between; align-items:flex-start; gap:14px; list-style:none; }}
.ep-sum::-webkit-details-marker {{ display:none; }}
.ep-title {{ font-weight:600; }}
.ep-badges {{ display:flex; gap:6px; flex-shrink:0; flex-wrap:wrap; justify-content:flex-end; }}
.ep-body {{ padding:4px 16px 18px; border-top:1px solid var(--br); }}
.ep-link {{ margin:10px 0 4px; }}
.ep-link a, a {{ color:#2563eb; text-decoration:none; }}
.ep-link a:hover {{ text-decoration:underline; }}
.ep-gist {{ color:#334155; font-size:14.5px; margin:10px 0 12px; padding:10px 12px; background:var(--card2); border-left:3px solid var(--acc); border-radius:6px; }}
.ep-themes-row {{ display:flex; flex-wrap:wrap; gap:6px; margin:0 0 14px; }}
.theme {{ margin:16px 0; }}
.theme-h {{ font-size:15px; font-weight:700; color:#0f172a; margin:0 0 8px; }}
.theme-n {{ background:var(--acc); color:#fff; border-radius:20px; padding:1px 8px; font-size:12px; margin-left:4px; }}
.insight {{ border:1px solid var(--br); border-radius:10px; padding:11px 13px; margin:8px 0; background:#fbfcfe; }}
.i-claim {{ font-weight:600; margin-bottom:7px; color:#161c28; }}
.i-meta {{ display:flex; flex-wrap:wrap; gap:5px; margin-bottom:6px; }}
.chip {{ display:inline-block; font-size:11.5px; padding:2px 8px; border-radius:20px; border:1px solid var(--br); background:#eef1f8; color:var(--mut); white-space:nowrap; }}
.chip-spk {{ color:#475569; }}
.chip-ent {{ background:#eef2ff; color:#3730a3; border-color:#c7d2fe; }}
.i-sowhat {{ font-size:13.5px; color:#334155; margin:5px 0; }}
.i-sowhat b {{ color:#4f46e5; }}
.i-quote {{ font-size:13.5px; color:#475569; font-style:italic; margin-top:6px; padding-left:10px; border-left:2px solid var(--br); }}
.ts {{ font-style:normal; color:#b91c1c; font-size:12px; margin-left:4px; white-space:nowrap; }}
a.ts:hover {{ text-decoration:underline; }}
.i-para {{ border-left-color:#d97706; }}
.para-tag {{ font-style:normal; font-size:10.5px; color:#92660e; background:#fef6e3; border:1px solid #e6cf94; border-radius:10px; padding:0 6px; margin-left:4px; cursor:help; }}
.legend {{ color:var(--mut); font-size:12px; margin-top:8px; }}
.legend code {{ background:var(--card2); padding:1px 5px; border-radius:4px; }}
</style></head><body><div class="wrap">
<header class="top">
  <h1>YouTube Insights Digest</h1>
  <div class="sub">{date} · {len(recs)} episodes · {total_ins} insights · {len(by_ch)} channels<br>
  <span style="font-size:12.5px">One-time backlog extraction (≥25-min episodes). Standalone — not wired into the dashboard.</span>
  <div class="legend">Quotes shown “verbatim” are matched in the source transcript; “≈ … <span class="para-tag">paraphrase</span>” means close-but-not-exact (auto-caption drift). Timestamps were not available (transcripts stored as plain text) — every link opens the episode at the start.</div></div>
  <div class="controls">
    <button onclick="document.querySelectorAll('details.ep').forEach(d=>d.open=true)">Expand all</button>
    <button onclick="document.querySelectorAll('details.ep').forEach(d=>d.open=false)">Collapse all</button>
  </div>
</header>
{"".join(blocks)}
</div></body></html>"""

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Filename prefix "youtube_" matches the dashboard's report discovery
    # (update_dashboard.py FILENAME_RE: <type>_YYYY-MM-DD.html).
    out = OUT_DIR / f"youtube_{date}.html"
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out}  ({len(recs)} episodes, {total_ins} insights, {len(by_ch)} channels)")


if __name__ == "__main__":
    main()
