#!/usr/bin/env python3
"""Generate index.html — the Market Intelligence dashboard — from reports/.

Scans reports/ for <type>_YYYY-MM-DD[_HHMM].html files, groups them by type and
day, and writes a self-contained (no external deps) responsive dashboard to the
repo root. "Today"/"Yesterday" are derived from the most recent *report* date,
not the system clock.

Add a new source type by adding one entry to REPORT_TYPES.
"""

import html
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
INDEX_PATH = REPO_ROOT / "index.html"

# Adding a new source = one entry here (key must match the filename prefix).
# "label" is a DISPLAY name only (the key is the data link — never rename it).
# "group" selects the rhythm container (see GROUPS); colours encode rhythm by
# hue (pulse = blue family, research = amber family) and stream by tone.
REPORT_TYPES = {
    "twitter_alpha":    {"label": "Twitter Alpha",    "color": "#6366F1", "icon": "🧠", "group": "pulse"},
    "twitter_data":     {"label": "Twitter Data",     "color": "#3B82F6", "icon": "📊", "group": "pulse"},
    "twitter_shitpost": {"label": "Twitter Shitpost", "color": "#0EA5E9", "icon": "🃏", "group": "pulse"},
    "twitter_bank_research": {"label": "Twitter Banks", "color": "#F59E0B", "icon": "🏦", "group": "research"},
    "research_pdfs":    {"label": "Bank PDF",       "color": "#D97706", "icon": "📑", "group": "research"},
    "institutional":    {"label": "Institutional Research", "color": "#EA580C", "icon": "🏛️", "group": "research"},
    "research":         {"label": "Newsletters & News", "color": "#06B6D4", "icon": "🔬", "group": "pulse"},
    # Future sources (no reports yet — appear automatically once files land):
    "youtube":          {"label": "YouTube",          "color": "#dc2626", "icon": "▶️", "group": "pulse"},
    "podcasts":         {"label": "Podcasts",         "color": "#8b5cf6", "icon": "🎙️", "group": "research"},
    "concepts":         {"label": "Concepts",         "color": "#0891b2", "icon": "💡", "group": "research"},
    "tech":             {"label": "Tech",             "color": "#475569", "icon": "⚙️", "group": "research"},
    "society":          {"label": "Society",          "color": "#be185d", "icon": "🌐", "group": "pulse"},
}
FALLBACK_COLOR = "#64748b"
FALLBACK_ICON = "📄"

# Rhythm groups, rendered in this order (pulse → research). Each renders as a
# bordered container with the group's own Latest/Previous rows. Membership is
# config-driven via each stream's "group" above — adding a slow stream is one
# REPORT_TYPES line, no markup changes here.
GROUPS = [
    {"key": "pulse",    "label": "⚡ PULSE",    "caption": "· intraday · 2–3×/day"},
    {"key": "research", "label": "📑 RESEARCH", "caption": "· daily to weekly"},
]
DEFAULT_GROUP = "pulse"

FILENAME_RE = re.compile(
    r"^(?P<type>.+?)_(?P<date>\d{4}-\d{2}-\d{2})(?:_(?P<time>\d{4}))?\.html$")


def parse_reports():
    """Return list of report dicts parsed from reports/*.html."""
    reports = []
    if not REPORTS_DIR.is_dir():
        return reports
    for path in REPORTS_DIR.glob("*.html"):
        m = FILENAME_RE.match(path.name)
        if not m:
            continue
        try:
            day = datetime.strptime(m.group("date"), "%Y-%m-%d").date()
        except ValueError:
            continue
        time = m.group("time")
        reports.append({
            "type": m.group("type"),
            "day": day,
            "date_str": m.group("date"),
            "time": time,
            "filename": path.name,
            "sort_key": (day.isoformat(), time or "0000"),
        })
    return reports


def type_meta(type_key):
    meta = REPORT_TYPES.get(type_key)
    if meta:
        return meta
    return {
        "label": type_key.replace("_", " ").title(),
        "color": FALLBACK_COLOR,
        "icon": FALLBACK_ICON,
        "group": DEFAULT_GROUP,
    }


def ordered_types(type_keys):
    """Known types in REPORT_TYPES order first, then any unknown types A-Z."""
    known = [k for k in REPORT_TYPES if k in type_keys]
    unknown = sorted(k for k in type_keys if k not in REPORT_TYPES)
    return known + unknown


def group_types(group_key, type_keys):
    """Types belonging to a rhythm group, in REPORT_TYPES order."""
    return [t for t in ordered_types(type_keys)
            if type_meta(t).get("group", DEFAULT_GROUP) == group_key]


def fmt_time(time):
    if not time or len(time) != 4:
        return ""
    return f"{time[:2]}:{time[2:]}"


def render_card(report):
    meta = type_meta(report["type"])
    t = fmt_time(report["time"])
    sub = report["date_str"] + (f" &middot; {t}" if t else "")
    return (
        f'<a class="card" style="--accent:{meta["color"]}" '
        f'href="reports/{html.escape(report["filename"], quote=True)}">'
        f'<span class="ctype">{meta["icon"]} {html.escape(meta["label"])}</span>'
        f'<span class="cmeta mono">{sub}</span></a>'
    )


def render_top_section(reports):
    """One bordered container per rhythm group. Inside each, the unchanged
    Latest/Previous mechanic: 'Latest' = most recent report of each type in the
    group, 'Previous' = second most recent (regardless of calendar day). Each
    card carries its own date/time; the row header is just the label."""
    if not reports:
        return '<p class="empty">No reports yet.</p>'
    by_type = {}
    for r in reports:
        by_type.setdefault(r["type"], []).append(r)
    for items in by_type.values():
        items.sort(key=lambda r: r["sort_key"], reverse=True)  # newest first
    blocks = []
    for group in GROUPS:
        types = group_types(group["key"], by_type)
        if not types:  # group entirely absent from data → skip its container
            continue
        rows = []
        for rank, label in ((0, "Latest"), (1, "Previous")):
            cards = "".join(
                render_card(by_type[t][rank]) for t in types if len(by_type[t]) > rank)
            if cards:
                rows.append(
                    f'<div class="day-row"><div class="day-label">'
                    f'<span>{label}</span></div>'
                    f'<div class="cards">{cards}</div></div>'
                )
        if rows:
            blocks.append(
                f'<div class="group">'
                f'<div class="group-head">'
                f'<span class="group-label">{group["label"]}</span>'
                f'<span class="group-caption">{group["caption"]}</span></div>'
                f'{"".join(rows)}</div>'
            )
    return "".join(blocks)


def render_archive(reports):
    by_type = {}
    for r in reports:
        by_type.setdefault(r["type"], []).append(r)
    groups_html = []
    for group in GROUPS:
        types = group_types(group["key"], by_type)
        if not types:  # no archived reports for this group → skip its subgroup
            continue
        sections = []
        for type_key in types:
            meta = type_meta(type_key)
            items = sorted(by_type[type_key], key=lambda r: r["sort_key"], reverse=True)
            links = []
            for r in items:
                t = fmt_time(r["time"])
                links.append(
                    f'<a class="arch-link" href="reports/{html.escape(r["filename"], quote=True)}">'
                    f'<span class="d mono">{r["date_str"]}</span>'
                    f'<span class="t mono">{t}</span></a>'
                )
            sections.append(
                f'<div class="arch-section">'
                f'<button class="arch-header" type="button" onclick="toggle(this)">'
                f'<span class="arrow">&#9656;</span>'
                f'<span class="dot" style="--accent:{meta["color"]}"></span>'
                f'<span>{html.escape(meta["label"])}</span>'
                f'<span class="count">({len(items)})</span></button>'
                f'<div class="arch-body"><div class="arch-inner">{"".join(links)}</div></div>'
                f'</div>'
            )
        groups_html.append(
            f'<div class="arch-group-label">{html.escape(group["key"].capitalize())}</div>'
            f'{"".join(sections)}'
        )
    return "".join(groups_html) or '<p class="empty">No reports yet.</p>'


def build_html(reports):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    top = render_top_section(reports)
    archive = render_archive(reports)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Market Intelligence</title>
<style>
:root {{
  --header-bg: #1a1a2e;
  --body-bg: #fafafa;
  --card-bg: #ffffff;
  --text: #1a1a1a;
  --muted: #6b7280;
  --border: #e5e7eb;
  --hover: #f3f4f6;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--body-bg); color: var(--text); line-height: 1.5;
  overflow-x: hidden;
}}
.mono {{ font-family: "SF Mono", "Fira Code", ui-monospace, monospace; }}

header {{ background: var(--header-bg); color: #fff; padding: 22px 20px; }}
.wrap {{ max-width: 1100px; margin: 0 auto; }}
header h1 {{ font-size: 17px; font-weight: 700; letter-spacing: 0.14em; }}

main {{ max-width: 1100px; margin: 0 auto; padding: 24px 20px 48px; }}
.section-title {{
  font-size: 12px; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--muted); margin: 26px 0 12px;
}}
.section-title:first-child {{ margin-top: 4px; }}

.day-row {{ margin-bottom: 20px; }}
.day-label {{
  display: flex; gap: 8px; align-items: baseline;
  font-size: 13px; font-weight: 600; margin-bottom: 10px;
}}
.day-label .date {{ color: var(--muted); font-size: 12px; font-weight: 400; }}

.group {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 18px 2px; margin-bottom: 16px;
}}
.group-head {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 16px; }}
.group-label {{ font-size: 14px; font-weight: 700; letter-spacing: 0.04em; }}
.group-caption {{ font-size: 12px; color: var(--muted); }}

.cards {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
@media (min-width: 600px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (min-width: 900px) {{ .cards {{ grid-template-columns: repeat(4, 1fr); }} }}

.card {{
  display: flex; flex-direction: column; gap: 6px;
  background: var(--card-bg); border: 1px solid var(--border);
  border-left: 4px solid var(--accent, {FALLBACK_COLOR}); border-radius: 8px;
  padding: 14px 16px; text-decoration: none; color: inherit; min-height: 44px;
  transition: transform .15s ease, box-shadow .15s ease;
}}
.card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0,0,0,.08); }}
.card .ctype {{ font-size: 14px; font-weight: 600; }}
.card .cmeta {{ font-size: 12px; color: var(--muted); }}

.archive {{ margin-top: 6px; }}
.arch-group-label {{
  font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--muted); margin: 16px 0 8px;
}}
.arch-group-label:first-child {{ margin-top: 0; }}
.arch-section {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 8px; overflow: hidden;
}}
.arch-header {{
  width: 100%; text-align: left; font: inherit; cursor: pointer;
  background: none; border: none; color: var(--text); font-weight: 600;
  font-size: 14px; padding: 0 16px; min-height: 48px;
  display: flex; align-items: center; gap: 10px;
}}
.arch-header:hover {{ background: var(--hover); }}
.arch-header .arrow {{ color: var(--muted); transition: transform .25s ease; }}
.arch-section.open .arrow {{ transform: rotate(90deg); }}
.arch-header .dot {{
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--accent, {FALLBACK_COLOR}); flex-shrink: 0;
}}
.arch-header .count {{ color: var(--muted); font-weight: 500; margin-left: auto; }}
.arch-body {{ max-height: 0; overflow: hidden; transition: max-height .3s ease; }}
.arch-inner {{ padding-bottom: 6px; }}
.arch-link {{
  display: flex; gap: 14px; align-items: center; min-height: 44px;
  padding: 8px 18px; text-decoration: none; color: var(--text);
  border-top: 1px solid var(--hover); font-size: 13px;
}}
.arch-link:hover {{ background: var(--hover); }}
.arch-link .t {{ color: var(--muted); font-size: 12px; }}

.empty {{ color: var(--muted); font-size: 14px; padding: 8px 0; }}

footer {{
  max-width: 1100px; margin: 0 auto; padding: 8px 20px 40px;
  color: var(--muted); font-size: 12px;
}}
</style>
</head>
<body>
<header><div class="wrap"><h1>MARKET INTELLIGENCE</h1></div></header>
<main>
  <div class="section-title">Today's Intelligence</div>
  {top}
  <div class="section-title">Archive</div>
  <div class="archive">{archive}</div>
</main>
<footer>Last updated: {now}</footer>
<script>
function toggle(btn) {{
  var sec = btn.closest('.arch-section');
  var body = sec.querySelector('.arch-body');
  if (sec.classList.toggle('open')) {{
    body.style.maxHeight = body.scrollHeight + 'px';
  }} else {{
    body.style.maxHeight = '0';
  }}
}}
window.addEventListener('resize', function () {{
  document.querySelectorAll('.arch-section.open .arch-body').forEach(function (b) {{
    b.style.maxHeight = b.scrollHeight + 'px';
  }});
}});
</script>
</body>
</html>
"""


def main():
    reports = parse_reports()
    INDEX_PATH.write_text(build_html(reports), encoding="utf-8")
    print(f"Wrote {INDEX_PATH} from {len(reports)} reports")


if __name__ == "__main__":
    main()
