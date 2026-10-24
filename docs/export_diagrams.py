"""Export the inline SVG diagrams in docs/*.html to standalone files in docs/diagrams/ for the README.

Run from the repo root: python3 docs/export_diagrams.py
"""
import re
from pathlib import Path

DOCS = Path(__file__).parent
OUT = DOCS / "diagrams"

# (source page, title id of the diagram, output name)
DIAGRAMS = [
    ("app-architecture.html", "app-arch-title", "app-architecture.svg"),
    ("editor-agent-flow.html", "ea-title", "editor-agent-flow.svg"),
    ("iwr-diagrams.html", "iwr-mech-title", "iwr-mechanism.svg"),
    ("iwr-diagrams.html", "iwr-flow-title", "iwr-flow.svg"),
    ("ministral-architecture.html", "ministral-arch-title", "ministral-architecture.svg"),
]


def export(page: str, title_id: str, name: str) -> None:
    html = (DOCS / page).read_text()
    style = re.search(r"<style>(.*?)</style>", html, re.DOTALL).group(1)
    for svg in re.findall(r"<svg class=\"arch\".*?</svg>", html, re.DOTALL):
        if f'id="{title_id}"' in svg:
            break
    else:
        raise SystemExit(f"{title_id} not found in {page}")
    _, _, w, h = re.search(r'viewBox="([^"]+)"', svg).group(1).split()
    svg = svg.replace("<svg ", f'<svg width="{w}" height="{h}" ', 1)
    svg = re.sub(r"(<svg[^>]*>)", r"\1\n<style>" + style.replace("\\", r"\\") + "</style>", svg, count=1)
    (OUT / name).write_text(svg + "\n")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for args in DIAGRAMS:
        export(*args)
        print("wrote", OUT / args[2])
