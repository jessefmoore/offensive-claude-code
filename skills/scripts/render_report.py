"""Render a pentest engagement's report.md into a self-contained report.html.

Self-contained means: embedded CSS, embedded syntax-highlighting styles
(Pygments), and every referenced image base64-inlined as a data URI. The
output HTML opens correctly when emailed, shared via cloud drive, or
extracted from a zip on an offline machine — no broken images, no
external font/CSS calls.

Layout assumption (see agents/report-writer-internalpen.md):

    engagements/<client>/<date>/
        report.md              <- input
        report.html            <- output
        evidence/              <- images referenced via ![](evidence/...)

Configuration (all optional):
    REPORT_TITLE_PREFIX   Override the <title> tag prefix (default uses
                          the engagement.yaml client field).
    REPORT_ACCENT         Hex color for accent (default #c0392b — desaturated red).

Dependencies (install via pip):
    markdown            Markdown -> HTML (with fenced_code, tables, toc, attr_list)
    pygments            Server-side syntax highlighting

Usage:
    python render_report.py <engagement-dir>
    python render_report.py <engagement-dir> --final   # bump verification & strip "draft" badge
"""
import argparse
import base64
import mimetypes
import re
import sys
from pathlib import Path

try:
    import markdown as md
    from markdown.extensions.codehilite import CodeHiliteExtension
    from markdown.extensions.toc import TocExtension
    from pygments.formatters import HtmlFormatter
except ImportError as e:
    sys.stderr.write(
        f"missing dependency: {e.name}\n"
        f"install with: python -m pip install markdown pygments\n"
    )
    sys.exit(2)


SEVERITY_CLASS = {
    "critical": "sev-critical",
    "high": "sev-high",
    "medium": "sev-medium",
    "low": "sev-low",
    "informational": "sev-info",
    "info": "sev-info",
}


def load_engagement_meta(engagement_dir: Path) -> dict:
    meta = {}
    yml = engagement_dir / "engagement.yaml"
    if not yml.is_file():
        return meta
    for line in yml.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def inline_image(html: str, engagement_dir: Path) -> str:
    """Replace <img src="evidence/..."> with base64 data URIs."""
    pattern = re.compile(r'<img\s+([^>]*?)src="([^"]+)"([^>]*?)>')

    def repl(m: re.Match) -> str:
        pre, src, post = m.group(1), m.group(2), m.group(3)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        img_path = (engagement_dir / src).resolve()
        if not img_path.is_file():
            return f'<img {pre}src="{src}" alt="MISSING: {src}" data-missing="true"{post}>'
        mime, _ = mimetypes.guess_type(str(img_path))
        if not mime or not mime.startswith("image/"):
            return m.group(0)
        b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
        return f'<img {pre}src="data:{mime};base64,{b64}"{post}>'

    return pattern.sub(repl, html)


def tag_severity_cells(html: str) -> str:
    """Wrap severity labels in colored badges so the renderer can style them.

    Matches table cells whose entire content is a severity word (case-insensitive)
    and wraps with a span carrying the right class.
    """
    def repl(m: re.Match) -> str:
        whitespace, word = m.group(1), m.group(2)
        cls = SEVERITY_CLASS.get(word.lower())
        if not cls:
            return m.group(0)
        return f"<td>{whitespace}<span class=\"sev-badge {cls}\">{word}</span></td>"

    return re.sub(
        r"<td>(\s*)(Critical|High|Medium|Low|Informational|Info)\s*</td>",
        repl,
        html,
    )


def tag_solution_blocks(html: str) -> str:
    """Color-code Immediate/Short-term/Long-term solution headings."""
    mapping = {
        "Immediate": "sol-immediate",
        "Short-term": "sol-short",
        "Long-term": "sol-long",
    }
    for label, cls in mapping.items():
        html = re.sub(
            rf"<p><strong>{re.escape(label)}([^<]*)</strong></p>",
            rf'<p class="{cls}"><strong>{label}\1</strong></p>',
            html,
        )
    return html


def build_html(body: str, title: str, accent: str, draft: bool) -> str:
    pyg_css = HtmlFormatter(style="monokai").get_style_defs(".codehilite")
    draft_badge = (
        '<div class="draft-badge">DRAFT — work in progress</div>' if draft else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
:root {{
    --accent: {accent};
    --text: #1a1a1a;
    --muted: #6b6b6b;
    --border: #d8d8d8;
    --bg: #ffffff;
    --bg-alt: #fafafa;
    --critical: #b30000;
    --high: #d35400;
    --medium: #d4a017;
    --low: #2e86c1;
    --info: #7b7d7d;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
    font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: var(--text);
    background: var(--bg);
    max-width: 920px;
    margin: 0 auto;
    padding: 48px 40px 96px;
    line-height: 1.55;
    font-size: 15px;
}}
h1, h2, h3, h4, h5 {{ color: var(--text); font-weight: 600; line-height: 1.25; }}
h1 {{ font-size: 30px; border-bottom: 3px solid var(--accent); padding-bottom: 12px; margin-top: 0; }}
h2 {{ font-size: 24px; border-bottom: 1px solid var(--border); padding-bottom: 6px; margin-top: 42px; }}
h3 {{ font-size: 19px; margin-top: 32px; }}
h4 {{ font-size: 16px; margin-top: 20px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
hr {{ border: none; border-top: 1px solid var(--border); margin: 36px 0; }}
p {{ margin: 10px 0; }}
strong {{ color: var(--text); }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
table {{ border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 14px; }}
th, td {{ border: 1px solid var(--border); padding: 8px 12px; text-align: left; vertical-align: top; }}
th {{ background: var(--bg-alt); font-weight: 600; }}
tr:nth-child(even) td {{ background: var(--bg-alt); }}
code {{
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: 13px;
    background: #f0f0f0;
    padding: 1px 5px;
    border-radius: 3px;
}}
pre {{
    background: #272822;
    color: #f8f8f2;
    padding: 14px 18px;
    border-radius: 5px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.45;
}}
pre code {{ background: transparent; padding: 0; color: inherit; font-size: 13px; }}
.codehilite {{ background: #272822; border-radius: 5px; margin: 12px 0; }}
.codehilite pre {{ margin: 0; }}
img {{ max-width: 100%; border: 1px solid var(--border); border-radius: 4px; margin: 12px 0; display: block; }}
img[data-missing="true"] {{ display: inline-block; padding: 8px 12px; background: #fff0f0; border: 1px dashed #b30000; color: #b30000; }}
blockquote {{ border-left: 4px solid var(--accent); padding: 4px 14px; color: var(--muted); margin: 14px 0; background: var(--bg-alt); }}

/* Severity badges */
.sev-badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 3px;
    font-weight: 600;
    font-size: 13px;
    color: white;
    letter-spacing: 0.02em;
}}
.sev-critical {{ background: var(--critical); }}
.sev-high {{ background: var(--high); }}
.sev-medium {{ background: var(--medium); color: #1a1a1a; }}
.sev-low {{ background: var(--low); }}
.sev-info {{ background: var(--info); }}

/* Solution callouts */
.sol-immediate, .sol-short, .sol-long {{
    padding: 6px 12px;
    border-left: 4px solid var(--accent);
    background: var(--bg-alt);
    margin: 10px 0 4px;
}}
.sol-immediate {{ border-left-color: var(--critical); }}
.sol-short {{ border-left-color: var(--high); }}
.sol-long {{ border-left-color: var(--low); }}

/* Finding heading anchor */
h3[id^="f"] {{
    background: var(--bg-alt);
    padding: 10px 14px;
    border-left: 4px solid var(--accent);
    margin-top: 36px;
}}

/* Draft banner */
.draft-badge {{
    position: fixed;
    top: 18px;
    right: 18px;
    background: #d35400;
    color: white;
    padding: 6px 14px;
    border-radius: 3px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.06em;
    box-shadow: 0 2px 6px rgba(0,0,0,0.18);
    z-index: 10;
}}

/* Pygments syntax highlighting */
{pyg_css}

@media print {{
    body {{ max-width: none; padding: 24px; font-size: 12px; }}
    .draft-badge {{ display: none; }}
    h2 {{ page-break-before: auto; }}
    h3[id^="f"] {{ page-break-before: always; }}
    pre {{ white-space: pre-wrap; word-break: break-word; }}
}}
</style>
</head>
<body>
{draft_badge}
{body}
</body>
</html>
"""


def render(engagement_dir: Path, final: bool) -> Path:
    report_md = engagement_dir / "report.md"
    if not report_md.is_file():
        sys.exit(f"report.md not found in {engagement_dir}")

    raw = report_md.read_text(encoding="utf-8")

    extensions = [
        "fenced_code",
        "tables",
        "attr_list",
        "sane_lists",
        CodeHiliteExtension(guess_lang=False, css_class="codehilite"),
        TocExtension(permalink=True, anchorlink=False),
    ]
    body = md.markdown(raw, extensions=extensions, output_format="html5")

    body = tag_severity_cells(body)
    body = tag_solution_blocks(body)
    body = inline_image(body, engagement_dir)

    meta = load_engagement_meta(engagement_dir)
    client = meta.get("client", engagement_dir.parent.name)
    title_prefix = __import__("os").environ.get("REPORT_TITLE_PREFIX", "Internal Pentest")
    accent = __import__("os").environ.get("REPORT_ACCENT", "#c0392b")
    title = f"{title_prefix} — {client}"

    html = build_html(body, title, accent, draft=not final)
    out = engagement_dir / "report.html"
    out.write_text(html, encoding="utf-8")
    return out


def main():
    p = argparse.ArgumentParser(description="Render a pentest report.md to a self-contained report.html")
    p.add_argument("engagement_dir", help="Path to engagements/<client>/<date>/")
    p.add_argument("--final", action="store_true", help="Mark as final (removes draft banner)")
    args = p.parse_args()

    eng = Path(args.engagement_dir).resolve()
    if not eng.is_dir():
        sys.exit(f"not a directory: {eng}")

    out = render(eng, args.final)
    sys.stdout.write(f"rendered: {out}\n")


if __name__ == "__main__":
    main()
