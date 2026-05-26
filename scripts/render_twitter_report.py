#!/usr/bin/env python3
"""Render Twitter Alpha report from JSON data + HTML template."""
import json, sys, os
from datetime import datetime

def render(template_path, data_path, output_path):
    with open(template_path, 'r') as f:
        template = f.read()
    with open(data_path, 'r') as f:
        data = f.read()
    html = template.replace('__REPORT_DATA__', data)
    with open(output_path, 'w') as f:
        f.write(html)
    print(f"Rendered: {output_path}")

if __name__ == '__main__':
    template = sys.argv[1] if len(sys.argv) > 1 else 'templates/twitter_alpha_report.html'
    data_file = sys.argv[2] if len(sys.argv) > 2 else None
    if not data_file:
        print("Usage: python3 render_twitter_report.py <template> <report.json> [output.html]")
        sys.exit(1)
    timestamp = datetime.now().strftime('%Y-%m-%d')
    output = sys.argv[3] if len(sys.argv) > 3 else f'reports/twitter_alpha_{timestamp}.html'
    os.makedirs(os.path.dirname(output), exist_ok=True)
    render(template, data_file, output)
