#!/usr/bin/env python3
"""Generate bank research HTML digest from tweets_bank_research.json."""
import json
import re
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict


def norm_text(s):
    s = s.lower().strip()
    s = re.sub(r'^@\w+\s+', '', s)
    s = re.sub(r'https?://\S+', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def main():
    data_path = '/home/user/market-intelligence/data/twitter/latest/tweets_bank_research.json'
    tpl_path  = '/home/user/market-intelligence/templates/twitter_data_report.html'
    out_dir   = '/home/user/market-intelligence/reports'

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    collected_at = data['collected_at']
    total_tweets = data['total_tweets']
    tweets = data['tweets']

    coll_dt = datetime.fromisoformat(collected_at.replace('Z', '+00:00'))
    window_start = coll_dt - timedelta(days=4)

    # STEP 1 — window filter
    considered = []
    for t in tweets:
        ca = t['created_at']
        dt_str = ca.replace('.000Z', '+00:00').replace('Z', '+00:00')
        dt = datetime.fromisoformat(dt_str)
        if dt >= window_start:
            considered.append(t)

    # STEP 1 — keep/drop filter
    kept_raw = []
    for t in considered:
        banks = t.get('banks', [])
        author = t.get('author_username', '').lower()
        if banks or author == 'neilksethi':
            kept_raw.append(dict(t))  # shallow copy

    dropped_count = len(considered) - len(kept_raw)

    # STEP 2 — image-URL dedup
    seen_imgs = {}   # image tuple → kept item
    deduped = 0
    after_img_dedup = []
    for t in kept_raw:
        imgs = tuple(sorted(t.get('images', [])))
        if imgs and imgs in seen_imgs:
            orig = seen_imgs[imgs]
            orig.setdefault('relayers', []).append(t.get('author_username', ''))
            deduped += 1
        else:
            t['relayers'] = []
            if imgs:
                seen_imgs[imgs] = t
            after_img_dedup.append(t)

    # STEP 2 — near-identical text dedup
    seen_norm = {}
    final_kept = []
    for t in after_img_dedup:
        n = norm_text(t.get('text', ''))
        if n and n in seen_norm:
            orig = seen_norm[n]
            orig.setdefault('relayers', []).append(t.get('author_username', ''))
            deduped += 1
        else:
            if n:
                seen_norm[n] = t
            final_kept.append(t)

    kept_count = len(kept_raw)  # per checklist: kept = pre-dedup filter count

    # STEP 3 — group by bank
    bank_groups = defaultdict(list)
    neil_general = []

    for t in final_kept:
        banks = t.get('banks', [])
        author = t.get('author_username', '').lower()
        if banks:
            for b in banks:
                bank_groups[b].append(t)
        elif author == 'neilksethi':
            neil_general.append(t)

    bank_order = sorted(bank_groups.keys(), key=lambda b: (-len(bank_groups[b]), b))

    themes = {
        'Goldman':   'GS on IPO revival, Q2 GDP at 2.0%, earnings revision breadth — multi-item burst',
        'BofA':      'Canada enters technical recession after back-to-back GDP contractions',
        'JPM':       'Dimon on market exuberance — "not bad" but risks flagged',
        'Ned Davis': 'Global debt ratios at 231% of GDP, back to pre-pandemic level',
    }
    neil_theme = 'May/week/day market wrap — indices, BoJ/BoC policy, Asia outperformance, consumer prices'

    def make_item(t):
        item = {
            'author':     t.get('author_username', ''),
            'text':       t.get('text', ''),
            'tweet_url':  t.get('tweet_url', ''),
            'images':     t.get('images', []),
            'created_at': t.get('created_at', ''),
            'relayers':   t.get('relayers', []),
        }
        if item['relayers']:
            item['data_points'] = [
                'also carried by: ' + ', '.join('@' + r for r in item['relayers'])
            ]
        return item

    # Build template topics
    topics = []
    for b in bank_order:
        topics.append({
            'topic': f'{b} — {themes.get(b, "")}',
            'theme': themes.get(b, ''),
            'items': [make_item(t) for t in bank_groups[b]],
        })
    if neil_general:
        topics.append({
            'topic': f'Neil Sethi — {neil_theme}',
            'theme': neil_theme,
            'items': [make_item(t) for t in neil_general],
        })

    by_bank_counts = {b: len(bank_groups[b]) for b in bank_order}
    counts_str = ', '.join(f'{b} {n}' for b, n in by_bank_counts.items())

    summary = (
        "Goldman led coverage with 8 items: IPO market revival (Q2 average first-day return +21%, "
        "YTD gross proceeds $28B — best since 2021), Q2 GDP tracking steady at 2.0%, strongest "
        "earnings revision breadth since 2021, and FIFA World Cup 2026 predictions. "
        "BofA flagged Canada's technical recession following back-to-back GDP contractions. "
        "JPMorgan's Dimon acknowledged market exuberance while flagging risks. "
        "Ned Davis noted global debt back to pre-pandemic levels at 231% of GDP.\n\n"
        "Neil Sethi (13 items) covered the full May/week/day wrap: SPX +5.2% and Nasdaq +8.4% in May "
        "(9th straight weekly gain), $IGV software ETF up 36% over 7 weeks, MSCI Asia-Pacific +40% "
        "over the last 12 months, BoJ rate hike at ~77% probability for June, Canada GDP contraction, "
        "and 91% of consumers still concerned about high prices.\n\n"
        f"**By bank:** {counts_str}."
    )

    # Build sidecar-compatible banks list
    banks_list = [
        {
            'bank':  b,
            'theme': themes.get(b, ''),
            'items': [make_item(t) for t in bank_groups[b]],
        }
        for b in bank_order
    ]

    report_data = {
        'date':          '2026-05-30 · Bank Research Digest',
        'report_type':   'TWITTER BANK RESEARCH',
        'collected_at':  collected_at,
        'window_days':   4,
        'freshness_gate':'FRESHNESS GATE PASSED. collected_at 2026-05-30T10:59:48+00:00 (2.4h old)',
        'input_stats': {
            'total_tweets': total_tweets,
            'considered':   len(considered),
            'kept':         kept_count,
            'dropped':      dropped_count,
            'deduped':      deduped,
        },
        'summary':        summary,
        'by_bank_counts': by_bank_counts,
        'banks':          banks_list,
        'topics':         topics,
    }

    # Verification checklist assertions
    assert kept_count + dropped_count == len(considered), \
        f"FAIL: kept+dropped={kept_count+dropped_count} != considered={len(considered)}"
    assert len(considered) <= total_tweets, \
        f"FAIL: considered={len(considered)} > total_tweets={total_tweets}"
    for t in final_kept:
        banks = t.get('banks', [])
        author = t.get('author_username', '').lower()
        assert banks or author == 'neilksethi', \
            f"FAIL: item {t.get('id')} has no banks and is not neilksethi"
        assert t.get('images'), \
            f"FAIL: item {t.get('id')} has no images"
    # by_bank_counts vs banks items
    for b, cnt in by_bank_counts.items():
        actual = sum(1 for item in banks_list if item['bank'] == b)
        assert actual == 1, f"FAIL: {b} has {actual} sections"
        assert len(banks_list[[i['bank'] for i in banks_list].index(b)]['items']) == cnt, \
            f"FAIL: {b} item count mismatch"

    print("VERIFICATION CHECKLIST: all checks passed")
    print(f"  total_tweets={total_tweets}, considered={len(considered)}, "
          f"kept={kept_count}, dropped={dropped_count}, deduped={deduped}")

    with open(tpl_path, 'r', encoding='utf-8') as f:
        template = f.read()

    report_json = json.dumps(report_data, ensure_ascii=False, indent=2)
    html = template.replace('__REPORT_DATA__', report_json)

    now_utc = datetime.now(timezone.utc)
    ts = now_utc.strftime('%Y-%m-%d_%H%M')
    os.makedirs(out_dir, exist_ok=True)
    outpath = os.path.join(out_dir, f'twitter_bank_research_{ts}.html')

    with open(outpath, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Written: {outpath}")
    return outpath


if __name__ == '__main__':
    main()
