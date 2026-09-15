"""
StudyMatch — one-command build for the local data browser.

Regenerates every sample dataset (generate_sample_data.py) and bakes the
result into viewer_template.html to produce a single self-contained HTML
file you can open directly in a browser — no server, no Claude, no
internet required except for the Google Fonts request (falls back to a
system sans/mono stack if that's unreachable).

Run:
    python build_viewer.py

Output:
    studymatch-data-browser.html   (double-click it, or open with your browser)

Add --no-regen to skip re-running generate_sample_data.py and just
rebuild the HTML from whatever is currently in sample/*.json.
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SAMPLE_DIR = HERE / "sample"
TEMPLATE = HERE / "viewer_template.html"
OUTPUT = HERE / "studymatch-data-browser.html"

KEYS = [
    "university", "courses", "students", "course_membership", "personality_profiles",
    "archetypes", "availability", "academic_profiles", "pairwise_compatibility",
    "groups", "group_membership", "match_data", "course_chat_messages", "group_feedback",
]


def regenerate():
    print("Regenerating sample data (generate_sample_data.py)...", flush=True)
    subprocess.run([sys.executable, str(HERE / "generate_sample_data.py")], check=True, cwd=HERE)


def build():
    data = {k: json.loads((SAMPLE_DIR / f"{k}.json").read_text(encoding="utf-8")) for k in KEYS}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE.read_text(encoding="utf-8")
    if "__DATA_PLACEHOLDER__" not in template:
        raise SystemExit("viewer_template.html is missing the __DATA_PLACEHOLDER__ marker.")
    OUTPUT.write_text(template.replace("__DATA_PLACEHOLDER__", blob), encoding="utf-8")
    print(f"Wrote {OUTPUT}  ({OUTPUT.stat().st_size / 1024:.0f} KB)")
    print("Open it directly in a browser - everything is embedded, no server needed.")


if __name__ == "__main__":
    if "--no-regen" not in sys.argv:
        regenerate()
    build()
