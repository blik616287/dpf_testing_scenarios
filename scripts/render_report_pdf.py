#!/usr/bin/env python3
"""Render BENCHMARK_REPORT.md to a paginated PDF.

- Pre-renders the embedded Mermaid block to PNG via mermaid-cli (npx mmdc).
- Converts markdown -> HTML with tables/fenced-code/attr_list extensions.
- Applies CSS that:
    * starts each numbered top-level section (## N. ...) on a new page,
    * forbids tables, figures, and code blocks from splitting across pages,
    * shrinks oversized tables / wraps long cells so they fit the page,
    * embeds chart PNGs as figures sized to the page.
- Renders PDF via WeasyPrint.
"""

from __future__ import annotations

import base64
import mimetypes
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown
from weasyprint import HTML, CSS

ROOT = Path(__file__).resolve().parent.parent
SOURCE_MD = ROOT / "BENCHMARK_REPORT.md"
OUTPUT_PDF = ROOT / "BENCHMARK_REPORT.pdf"
BUILD_DIR = ROOT / "build"
MERMAID_PNG = BUILD_DIR / "diagram_topology.png"


def render_mermaid_blocks(md_text: str) -> str:
    """Find ```mermaid fenced blocks, render to PNG via mmdc, replace with image refs."""
    pattern = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
    matches = list(pattern.finditer(md_text))
    if not matches:
        return md_text

    BUILD_DIR.mkdir(exist_ok=True)
    out_text = md_text
    for idx, m in enumerate(matches):
        diagram_src = m.group(1)
        src_path = BUILD_DIR / f"diagram_{idx}.mmd"
        png_path = BUILD_DIR / f"diagram_{idx}.png"
        src_path.write_text(diagram_src)

        cmd = [
            "npx", "-y", "@mermaid-js/mermaid-cli",
            "-i", str(src_path),
            "-o", str(png_path),
            "-b", "white",
            "-w", "1800",
            "-s", "2",
            "--puppeteerConfigFile", str(BUILD_DIR / "puppeteer.json"),
        ]
        # write a puppeteer config to allow chromium sandbox-less run
        (BUILD_DIR / "puppeteer.json").write_text(
            '{"args":["--no-sandbox","--disable-setuid-sandbox"]}'
        )
        print(f"[mermaid] rendering block {idx} -> {png_path.name}", file=sys.stderr)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not png_path.exists():
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            raise RuntimeError(f"mmdc failed for diagram {idx}")
        # Replace fenced block with an image ref using an absolute path.
        # Use a marker so we can post-process to figure-with-caption later.
        replacement = (
            f"\n<figure class=\"mermaid-figure\">\n"
            f"<img src=\"{png_path.as_uri()}\" alt=\"Topology diagram\"/>\n"
            f"<figcaption>Figure: pod-to-pod data path, both arms.</figcaption>\n"
            f"</figure>\n"
        )
        out_text = out_text.replace(m.group(0), replacement, 1)
    return out_text


def rewrite_relative_image_paths(md_text: str) -> str:
    """Rewrite ![alt](relative/path.png) to absolute file:// URIs so WeasyPrint loads them."""
    def repl(match: re.Match[str]) -> str:
        alt = match.group(1)
        src = match.group(2)
        if src.startswith(("http://", "https://", "data:", "file:")):
            return match.group(0)
        candidate = (ROOT / src).resolve()
        if candidate.exists():
            return f"![{alt}]({candidate.as_uri()})"
        return match.group(0)
    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, md_text)


CSS_STYLES = """
@page {
    size: A4;
    margin: 12mm 12mm 14mm 12mm;
    @bottom-right {
        content: counter(page) " / " counter(pages);
        font-size: 8.5pt;
        color: #666;
    }
    @bottom-left {
        content: "DPF Pod-to-Pod Acceleration Benchmark Report";
        font-size: 8.5pt;
        color: #666;
    }
}

html { font-size: 10pt; }
body {
    font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
    line-height: 1.38;
    color: #1a1a1a;
}

h1 {
    font-size: 20pt;
    margin: 0 0 0.3em 0;
    border-bottom: 2px solid #333;
    padding-bottom: 0.15em;
}
h2 {
    font-size: 14pt;
    margin-top: 1.1em;
    margin-bottom: 0.4em;
    border-bottom: 1px solid #888;
    padding-bottom: 0.1em;
    page-break-after: avoid;
}
h3 {
    font-size: 12pt;
    margin-top: 0.8em;
    margin-bottom: 0.3em;
    page-break-after: avoid;
}
h4 {
    font-size: 10.5pt;
    margin-top: 0.6em;
    margin-bottom: 0.25em;
    page-break-after: avoid;
}

p { margin: 0.4em 0; orphans: 3; widows: 3; }
ul, ol { margin: 0.4em 0; padding-left: 1.4em; orphans: 3; widows: 3; }
li { margin: 0.15em 0; }

a { color: #0b4a8f; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Tables: never split across pages, shrink to fit */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 0.5em 0;
    font-size: 8pt;
    line-height: 1.25;
    page-break-inside: avoid;
    break-inside: avoid;
    table-layout: auto;
}
th, td {
    border: 1px solid #b0b0b0;
    padding: 2px 4px;
    vertical-align: top;
    word-wrap: break-word;
    overflow-wrap: anywhere;
}
tr { page-break-inside: avoid; break-inside: avoid; }
th {
    background: #efefef;
    text-align: left;
    font-weight: 600;
}
tr:nth-child(even) td { background: #fafafa; }

/* Code */
code {
    font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
    font-size: 0.88em;
    background: #f3f3f3;
    padding: 1px 3px;
    border-radius: 2px;
    overflow-wrap: anywhere;
}
pre {
    font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
    font-size: 8.5pt;
    background: #f6f6f6;
    border: 1px solid #ddd;
    padding: 8px 10px;
    border-radius: 3px;
    overflow-x: auto;
    page-break-inside: avoid;
    break-inside: avoid;
    white-space: pre-wrap;
    word-break: break-word;
}
pre code { background: transparent; padding: 0; font-size: inherit; }

/* Images / figures */
img {
    max-width: 100%;
    height: auto;
}
figure, p > img, p:has(> img) {
    page-break-inside: avoid;
    break-inside: avoid;
    text-align: center;
    margin: 0.8em auto;
}
figure.mermaid-figure img {
    max-width: 100%;
    max-height: 230mm;
    object-fit: contain;
}
figcaption {
    font-size: 9pt;
    color: #555;
    margin-top: 0.3em;
    text-align: center;
}

hr { border: 0; border-top: 1px solid #ccc; margin: 1.2em 0; }

/* Inline emphasis around table-of-results */
strong { color: #111; }

/* Force chart images to render as block-level no-break units */
p img { display: block; margin: 0 auto; }
"""


def wrap_chart_images_in_figures(html: str) -> str:
    """Turn paragraphs that contain only a chart image into <figure> blocks with captions."""
    pattern = re.compile(
        r"<p>\s*<img\s+([^>]*?)alt=\"([^\"]*)\"([^>]*)/?>\s*</p>",
        re.IGNORECASE,
    )
    def repl(m: re.Match[str]) -> str:
        attrs_pre = m.group(1)
        alt = m.group(2)
        attrs_post = m.group(3)
        return (
            f"<figure class=\"chart-figure\">"
            f"<img {attrs_pre}alt=\"{alt}\"{attrs_post}/>"
            f"<figcaption>{alt}</figcaption>"
            f"</figure>"
        )
    return pattern.sub(repl, html)


def main() -> int:
    if not SOURCE_MD.exists():
        print(f"missing {SOURCE_MD}", file=sys.stderr)
        return 1
    if not shutil.which("npx"):
        print("npx not found in PATH", file=sys.stderr)
        return 1

    md_text = SOURCE_MD.read_text()
    md_text = render_mermaid_blocks(md_text)
    md_text = rewrite_relative_image_paths(md_text)

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "attr_list", "toc", "sane_lists"],
        output_format="html5",
    )
    html_body = wrap_chart_images_in_figures(html_body)

    html_doc = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>DPF Pod-to-Pod Benchmark Report</title>"
        "</head><body>" + html_body + "</body></html>"
    )

    HTML(string=html_doc, base_url=str(ROOT)).write_pdf(
        target=str(OUTPUT_PDF),
        stylesheets=[CSS(string=CSS_STYLES)],
    )
    print(f"wrote {OUTPUT_PDF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
