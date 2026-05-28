#!/usr/bin/env python3
"""Inject a fixed 'back to dashboard' button into every report in reports/.

PWA installs (home-screen icon) have no browser back button, so each report
needs a persistent link back to index.html. Idempotent: files that already
carry the button are skipped, so this can run on every workflow invocation
across all reports. Only the button element is added — no other content/JS is
touched.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"

# Kept byte-identical to the snippet baked into templates/.
BACK_BUTTON = (
    '<a href="../index.html" id="mi-back" '
    'style="position:fixed;top:12px;left:12px;z-index:9999;background:#1a1a2e;'
    'color:white;border-radius:20px;padding:6px 14px;font-size:14px;'
    'text-decoration:none;opacity:0.85;box-shadow:0 2px 8px rgba(0,0,0,0.3);'
    'min-height:44px;display:inline-flex;align-items:center;" '
    "onmouseover=\"this.style.opacity='1'\" "
    "onmouseout=\"this.style.opacity='0.85'\">← MI</a>"
)
# Dedup markers: the unique id, plus the visible "← MI" label.
MARKERS = ('id="mi-back"', "← MI")
BODY_RE = re.compile(r"<body[^>]*>", re.IGNORECASE)
HEAD_CLOSE_RE = re.compile(r"</head>", re.IGNORECASE)


def has_button(text):
    return any(marker in text for marker in MARKERS)


def inject(text):
    """Return (new_text, changed). Insert just after <body>; fall back to after
    </head>, then to the top of the file."""
    if has_button(text):
        return text, False
    m = BODY_RE.search(text)
    if m:
        idx = m.end()
        return text[:idx] + "\n" + BACK_BUTTON + text[idx:], True
    m = HEAD_CLOSE_RE.search(text)
    if m:
        idx = m.end()
        return text[:idx] + "\n" + BACK_BUTTON + text[idx:], True
    return BACK_BUTTON + "\n" + text, True


def main():
    if not REPORTS_DIR.is_dir():
        print("No reports/ directory; nothing to do")
        return
    patched = skipped = 0
    for path in sorted(REPORTS_DIR.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        new_text, changed = inject(text)
        if changed:
            path.write_text(new_text, encoding="utf-8")
            patched += 1
        else:
            skipped += 1
    print(f"Back button: patched {patched}, already present {skipped}")


if __name__ == "__main__":
    main()
