#!/usr/bin/env python3
"""Render a Twitter intelligence HTML report (alpha / data / shitpost).

Usage:
    python3 scripts/render_twitter_report.py --type alpha    report.json
    python3 scripts/render_twitter_report.py --type data     report.json
    python3 scripts/render_twitter_report.py --type shitpost report.json

Default output path: reports/twitter_{type}_{YYYY-MM-DD}.html
Override with --output or --template for an arbitrary template file.
"""
import argparse
import os
import sys
from datetime import datetime

# Resolve templates relative to the script so --type works from any CWD.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = {
    "alpha":    os.path.join(_REPO_ROOT, "templates", "twitter_alpha_report.html"),
    "data":     os.path.join(_REPO_ROOT, "templates", "twitter_data_report.html"),
    "shitpost": os.path.join(_REPO_ROOT, "templates", "twitter_shitpost_report.html"),
}


def render(template_path, data_path, output_path):
    with open(template_path, 'r') as f:
        template = f.read()
    with open(data_path, 'r') as f:
        data = f.read()
    html = template.replace('__REPORT_DATA__', data)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(html)
    print(f"Rendered: {output_path}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument('--type', dest='report_type', choices=sorted(TEMPLATES),
                   help='Report type — picks the matching template.')
    p.add_argument('--template',
                   help='Override template path (alternative to --type).')
    p.add_argument('--output', '-o', help='Output HTML path.')
    p.add_argument('data', help='Path to the JSON report data.')
    args = p.parse_args()

    if args.template:
        template_path = args.template
        type_label = 'report'
    elif args.report_type:
        template_path = TEMPLATES[args.report_type]
        type_label = args.report_type
    else:
        p.error('one of --type or --template is required')

    date = datetime.now().strftime('%Y-%m-%d')
    output_path = args.output or f'reports/twitter_{type_label}_{date}.html'
    render(template_path, args.data, output_path)


if __name__ == '__main__':
    main()
