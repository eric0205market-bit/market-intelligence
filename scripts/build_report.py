import json
import sys

with open('/home/user/market-intelligence/data/research_2026-08-28_0304.json') as f:
    data = json.load(f)

items = data['items']
meta = data['meta']

CAT_COLORS = {
    "macro": "#e24b4a", "credit": "#378add", "positioning": "#ef9f27",
    "AI/infra": "#1d9e75", "crypto": "#7f77dd", "geopolitics": "#d85a30",
    "energy": "#f97316", "tech": "#06b6d4", "gold": "#d4a017",
    "culture": "#ec4899", "labor": "#8b5cf6", "regulation": "#64748b",
    "science": "#14b8a6", "venture": "#84cc16"
}

URGENCY_LABEL = {"act": "🔴 Act Now", "deep": "🔵 Deep", "watch": "🟡 Watch"}
URGENCY_EMOJI = {"act": "🔴", "deep": "🔵", "watch": "🟡"}

cat_counts = {}
urg_counts = {"act": 0, "deep": 0, "watch": 0}
for it in items:
    cat_counts[it['cat']] = cat_counts.get(it['cat'], 0) + 1
    urg_counts[it['urgency']] += 1

cats_present = sorted(cat_counts.keys())

def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

cat_pills = ''.join(
    f'<button class="pill cat-pill" data-cat="{c}" style="--pill-color:{CAT_COLORS.get(c, "#64748b")}" onclick="setCatFilter(\'{c}\')">{esc(c)} <span class="pill-count">{cat_counts[c]}</span></button>\n'
    for c in cats_present
)

urg_pills = ''.join(
    f'<button class="pill urg-pill" data-urg="{u}" onclick="setUrgFilter(\'{u}\')">{URGENCY_LABEL[u]} <span class="pill-count">{urg_counts[u]}</span></button>\n'
    for u in ["act", "deep", "watch"]
)

def chart_html(it):
    c = it['charts']
    hot_class = ' chart-hot' if c.get('hot') else ''
    if c['count'] > 0:
        label = f"📊 {c['count']} chart{'s' if c['count'] != 1 else ''}"
        if c.get('hot'):
            label = "🔥 CHART WORTH SAVING — " + label
        return f'<div class="chart-box{hot_class}"><div class="chart-placeholder">{label}</div><div class="chart-desc">{esc(c["desc"])}</div></div>'
    else:
        return f'<div class="chart-box{hot_class}"><div class="chart-desc">{esc(c["desc"])}</div></div>'

def card_html(it):
    color = CAT_COLORS.get(it['cat'], '#64748b')
    charts_flag = ''
    if it['charts']['count'] > 0 or it['charts'].get('hot'):
        charts_flag = '🔥' if it['charts'].get('hot') else '📊'
    return f'''
  <div class="card" data-id="{it['id']}" data-cat="{esc(it['cat'])}" data-urg="{esc(it['urgency'])}" data-src="{esc(it['source'])}">
    <div class="card-header" onclick="toggleCard({it['id']})">
      <span class="idx">#{it['id']:02d}</span>
      <span class="urg-emoji">{URGENCY_EMOJI[it['urgency']]}</span>
      <span class="src-badge" style="background:{color}22;color:{color};border:1px solid {color}55">{esc(it['source'])}</span>
      <span class="cat-tag">{esc(it['cat'])}</span>
      <span class="charts-flag">{charts_flag}</span>
      <span class="card-title">{esc(it['title'])}</span>
      <span class="chevron">▾</span>
    </div>
    <div class="card-body">
      <div class="section">
        <div class="label">THE IDEA</div>
        <div class="idea-text">{esc(it['idea'])}</div>
      </div>
      <div class="angle-box" style="border-left-color:{color};background:{color}0d">
        <div class="label">MY ANGLE</div>
        <div class="angle-text">{esc(it['angle'])}</div>
      </div>
      <div class="tweets-row">
        <div class="tweet-box tweet-a">
          <div class="tweet-head"><span class="tweet-label label-a">TWEET A</span><button class="copy-btn" onclick="copyTweet({it['id']},'a')">📋 Copy</button></div>
          <div class="tweet-text">{esc(it['tweetA'])}</div>
        </div>
        <div class="tweet-box tweet-b">
          <div class="tweet-head"><span class="tweet-label label-b">TWEET B</span><button class="copy-btn" onclick="copyTweet({it['id']},'b')">📋 Copy</button></div>
          <div class="tweet-text">{esc(it['tweetB'])}</div>
        </div>
      </div>
      {chart_html(it)}
      <a class="read-link" href="{it['link']}" target="_blank" rel="noopener">↗ Read full article</a>
    </div>
  </div>
'''

cards = ''.join(card_html(it) for it in items)

included_rows = ''.join(
    f'<div class="report-row"><span class="report-src" onclick="filterBySrc(\'{esc(s["name"])}\')">{esc(s["name"])}</span><span class="report-count">{s["count"]} item{"s" if s["count"] != 1 else ""}</span></div>\n'
    for s in meta['includedSources']
)

skipped_rows = ''.join(
    f'<div class="report-row skipped"><span class="report-src-skipped">{esc(s["name"])}</span><span class="report-reason">{esc(s["reason"])}</span></div>\n'
    for s in meta['skippedSources']
)

items_json = json.dumps(items, ensure_ascii=False)
meta_json = json.dumps(meta, ensure_ascii=False)

html = f'''<title>Research Intelligence — {meta['date']}</title>
<style>
  :root {{
    --bg: #ffffff;
    --card-bg: #f8f7f5;
    --text: #1a1a1a;
    --text-dim: #6b6b6b;
    --text-faint: #9a9a9a;
    --border: #e5e2dd;
    --border-strong: #d4d0c9;
    --mono: 'SF Mono', 'Consolas', 'Menlo', monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 0 0 60px 0;
    line-height: 1.5;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; padding: 24px 16px; }}
  header {{ margin-bottom: 20px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 6px 0; letter-spacing: -0.01em; }}
  .subhead {{ color: var(--text-dim); font-size: 0.9rem; }}
  .filter-bar {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0; }}
  .pill {{
    font-family: inherit; font-size: 0.78rem; padding: 5px 11px; border-radius: 999px;
    border: 1px solid var(--border-strong); background: transparent; color: var(--text-dim);
    cursor: pointer; white-space: nowrap; transition: all 0.12s ease;
  }}
  .pill:hover {{ border-color: var(--text-dim); }}
  .pill.active {{
    background: var(--pill-color, #333); color: #fff; border-color: var(--pill-color, #333);
  }}
  .pill-count {{ opacity: 0.75; font-size: 0.72em; }}
  .urg-pill.active {{ background: #333; border-color: #333; color: #fff; }}
  .card {{
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px;
    margin-bottom: 10px; overflow: hidden;
  }}
  .card-header {{
    display: flex; align-items: center; gap: 8px; padding: 12px 14px; cursor: pointer;
    flex-wrap: wrap;
  }}
  .card-header:hover {{ background: #f1efec; }}
  .idx {{ font-family: var(--mono); color: var(--text-faint); font-size: 0.78rem; width: 28px; flex-shrink:0; }}
  .urg-emoji {{ font-size: 0.9rem; flex-shrink:0; }}
  .src-badge {{ font-size: 0.72rem; padding: 2px 8px; border-radius: 6px; font-weight: 600; white-space: nowrap; }}
  .cat-tag {{
    font-size: 0.68rem; padding: 2px 7px; border-radius: 5px; background: #eceae5; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 0.03em; white-space: nowrap;
  }}
  .charts-flag {{ font-size: 0.85rem; }}
  .card-title {{ font-weight: 600; font-size: 0.92rem; flex: 1; min-width: 180px; }}
  .chevron {{ color: var(--text-faint); font-size: 0.8rem; margin-left: auto; transition: transform 0.15s ease; }}
  .card.open .chevron {{ transform: rotate(180deg); }}
  .card-body {{ display: none; padding: 4px 16px 16px 16px; }}
  .card.open .card-body {{ display: block; }}
  .section {{ margin-bottom: 12px; }}
  .label {{
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--text-faint); margin-bottom: 4px;
  }}
  .idea-text {{ font-size: 0.92rem; color: var(--text); }}
  .angle-box {{
    border-left: 2px solid; padding: 8px 12px; border-radius: 4px; margin-bottom: 14px;
  }}
  .angle-text {{ font-style: italic; font-size: 0.88rem; color: var(--text); }}
  .tweets-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }}
  .tweet-box {{
    flex: 1 1 260px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
  }}
  .tweet-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
  .tweet-label {{ font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em; }}
  .label-a {{ color: #378add; }}
  .label-b {{ color: #7f77dd; }}
  .copy-btn {{
    font-family: inherit; font-size: 0.7rem; padding: 3px 8px; border-radius: 5px;
    border: 1px solid var(--border-strong); background: #fff; cursor: pointer; color: var(--text-dim);
  }}
  .copy-btn:hover {{ background: #f1efec; }}
  .tweet-text {{ font-size: 0.85rem; color: var(--text); }}
  .chart-box {{
    border: 1px dashed var(--border-strong); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px;
  }}
  .chart-box.chart-hot {{ border-color: #d4a017; background: #fdf8ec; }}
  .chart-placeholder {{ font-size: 0.8rem; font-weight: 600; color: var(--text-dim); margin-bottom: 3px; }}
  .chart-hot .chart-placeholder {{ color: #a1780f; }}
  .chart-desc {{ font-size: 0.8rem; color: var(--text-dim); }}
  .read-link {{ font-size: 0.82rem; color: #378add; text-decoration: none; font-weight: 600; }}
  .read-link:hover {{ text-decoration: underline; }}
  .report-card {{
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px;
    margin-top: 24px; padding: 14px 16px;
  }}
  .report-summary {{ cursor: pointer; font-weight: 600; font-size: 0.9rem; display:flex; align-items:center; gap:8px; }}
  .report-summary .chevron {{ margin-left: 0; }}
  .report-body {{ display: none; margin-top: 12px; }}
  .report-card.open .report-body {{ display: block; }}
  .report-card.open .chevron {{ transform: rotate(180deg); }}
  .report-section-title {{ font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-faint); margin: 12px 0 6px 0; }}
  .report-row {{ display: flex; justify-content: space-between; font-size: 0.85rem; padding: 4px 0; border-bottom: 1px solid var(--border); gap: 10px; }}
  .report-src {{ color: #378add; cursor: pointer; text-decoration: underline; text-decoration-color: transparent; }}
  .report-src:hover {{ text-decoration-color: #378add; }}
  .report-src-skipped {{ color: var(--text-dim); }}
  .report-count {{ color: var(--text-faint); flex-shrink: 0; }}
  .report-reason {{ color: var(--text-faint); font-size: 0.78rem; text-align: right; max-width: 55%; }}
  .no-results {{ text-align: center; color: var(--text-faint); padding: 30px; font-size: 0.9rem; display: none; }}
  @media (max-width: 480px) {{
    .card-header {{ gap: 6px; }}
    .card-title {{ font-size: 0.85rem; }}
  }}
</style>

<div class="wrap">
  <header>
    <h1>🔵 RESEARCH INTELLIGENCE</h1>
    <div class="subhead">{meta['date']} · {meta['time']} · {meta['itemsExtracted']} items from {len(meta['includedSources'])} sources</div>
  </header>

  <div class="filter-bar" id="cat-filter-bar">
    <button class="pill active" data-cat="all" onclick="setCatFilter('all')">All <span class="pill-count">{len(items)}</span></button>
    {cat_pills}
  </div>
  <div class="filter-bar" id="urg-filter-bar">
    <button class="pill active" data-urg="all" onclick="setUrgFilter('all')">All</button>
    {urg_pills}
  </div>

  <div id="cards-container">
    {cards}
  </div>
  <div class="no-results" id="no-results">No items match this filter.</div>

  <div class="report-card" id="report-card">
    <div class="report-summary" onclick="toggleReport()">
      <span>📋 Session Report</span><span class="chevron">▾</span>
    </div>
    <div class="report-body">
      <div>Window: <strong>{meta['windowStart']}</strong> → <strong>{meta['windowEnd']}</strong></div>
      <div>Emails in window: {meta['emailsInWindow']} · Emails read: {meta['emailsRead']} · Items extracted: {meta['itemsExtracted']}</div>
      <div class="report-section-title">Included Sources (click to filter)</div>
      {included_rows}
      <div class="report-section-title">Skipped Sources</div>
      {skipped_rows}
    </div>
  </div>
</div>

<script>
const ITEMS = {items_json};
const META = {meta_json};

let catFilter = 'all';
let urgFilter = 'all';
let srcFilter = null;

function applyFilters() {{
  const cards = document.querySelectorAll('.card');
  let visibleCount = 0;
  cards.forEach(function(card) {{
    const cat = card.getAttribute('data-cat');
    const urg = card.getAttribute('data-urg');
    const src = card.getAttribute('data-src');
    let show = true;
    if (catFilter !== 'all' && cat !== catFilter) show = false;
    if (urgFilter !== 'all' && urg !== urgFilter) show = false;
    if (srcFilter !== null && src.indexOf(srcFilter) === -1) show = false;
    card.style.display = show ? '' : 'none';
    if (show) visibleCount++;
  }});
  document.getElementById('no-results').style.display = visibleCount === 0 ? 'block' : 'none';
}}

function setCatFilter(cat) {{
  catFilter = cat;
  srcFilter = null;
  document.querySelectorAll('#cat-filter-bar .pill').forEach(function(p) {{
    p.classList.toggle('active', p.getAttribute('data-cat') === cat);
  }});
  document.querySelectorAll('.card').forEach(function(c) {{ c.classList.remove('open'); }});
  applyFilters();
}}

function setUrgFilter(urg) {{
  urgFilter = urg;
  srcFilter = null;
  document.querySelectorAll('#urg-filter-bar .pill').forEach(function(p) {{
    p.classList.toggle('active', p.getAttribute('data-urg') === urg);
  }});
  document.querySelectorAll('.card').forEach(function(c) {{ c.classList.remove('open'); }});
  applyFilters();
}}

function filterBySrc(name) {{
  srcFilter = name;
  catFilter = 'all';
  urgFilter = 'all';
  document.querySelectorAll('#cat-filter-bar .pill').forEach(function(p) {{
    p.classList.toggle('active', p.getAttribute('data-cat') === 'all');
  }});
  document.querySelectorAll('#urg-filter-bar .pill').forEach(function(p) {{
    p.classList.toggle('active', p.getAttribute('data-urg') === 'all');
  }});
  applyFilters();
  document.querySelectorAll('.card').forEach(function(card) {{
    const src = card.getAttribute('data-src');
    if (src.indexOf(name) !== -1) card.classList.add('open');
  }});
  const container = document.getElementById('cards-container');
  if (container) container.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
}}

function toggleCard(id) {{
  const card = document.querySelector('.card[data-id="' + id + '"]');
  if (card) card.classList.toggle('open');
}}

function toggleReport() {{
  document.getElementById('report-card').classList.toggle('open');
}}

function copyTweet(itemId, which) {{
  var item = ITEMS.find(function(i) {{ return i.id === itemId; }});
  var text = which === 'a' ? item.tweetA : item.tweetB;
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  var btn = event.target;
  btn.textContent = '✓ Copied';
  setTimeout(function() {{ btn.textContent = '📋 Copy'; }}, 1500);
}}
</script>
'''

with open('/home/user/market-intelligence/reports/research_2026-08-28_0304.html', 'w') as f:
    f.write(html)

print("done", len(html))
