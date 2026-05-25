"""Render an HTB / HackSmarter writeup.md into a self-contained writeup.html
styled like the p3ta00 CTF blog (JetBrains Mono, "Cyberpunk Neon" terminal
theme), re-branded with a JFM ASCII masthead.

Self-contained: embedded CSS, embedded Pygments syntax styles, Google-Fonts
JetBrains Mono inlined via @import fallback + system monospace, and every
referenced screenshot base64-inlined. Opens offline with no broken assets.

Two styles, selected with --style or auto-detected from the path:

  htb          writeups/htb/<machine-slug>/        (default)
  hacksmarter  writeups/hacksmarter/<lab-slug>/

HTB writeups carry YAML-ish frontmatter (title, os, difficulty, date, ip,
points, user_flag, root_flag, tags) which becomes the chip/flag header.

HackSmarter writeups (see agents/report-writer-hacksmarter.md) have no
frontmatter — instead the body opens with an embedded ASCII masthead, a
tagline line, a breadcrumb line, then `# <Title>` and a metadata table. In
hacksmarter style this preamble is stripped (the renderer supplies its own
masthead) and the title is read from the first `# ` heading.

Dependencies:
    markdown, pygments   (pip install markdown pygments)

Usage:
    python render_htb_writeup.py writeups/htb/silentium
    python render_htb_writeup.py writeups/hacksmarter/edge
    python render_htb_writeup.py writeups/hacksmarter/edge --style hacksmarter
"""
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

# JFM block-character masthead (same figlet style as the p3ta00 P3TA banner).
JFM_ASCII = r"""     ██╗███████╗███╗   ███╗
     ██║██╔════╝████╗ ████║
     ██║█████╗  ██╔████╔██║
██   ██║██╔══╝  ██║╚██╔╝██║
╚█████╔╝██║     ██║ ╚═╝ ██║
 ╚════╝ ╚═╝     ╚═╝     ╚═╝"""

# Per-style branding. Selected by --style / path auto-detection.
STYLES = {
    "htb": {
        "section": "htb",            # prompt + nav path segment (~/<section>/<slug>)
        "tagline": "Sr. cybersecurity advisor | and helping others with cybersecurity",
        "page_title": "JFM // {title} — HTB",
        "nav": [
            ("~/ home", "#"),
            ("~/htb", "#"),
            ("~/writeups", "#"),
            ("~/about", "#"),
        ],
        "extra_css": "",
    },
    "hacksmarter": {
        "section": "ctf",
        "tagline": "Security Advisor | jessefmoore on LinkedIn, X, and GitHub",
        "page_title": "{title} — HackSmarter | jfm@kali",
        "nav": [
            ("~/ home", "#"),
            ("~/ctf", "#"),
            ("~/writeups", "#"),
            ("~/about", "#"),
        ],
        # hacksmarter renders via build_edge() (EDGE_CSS owns all styling),
        # so extra_css is unused here — kept for parity with the htb entry.
        "extra_css": "",
    },
}

CSS = """
:root{
  --bg-dark:#1a1b26; --bg-darker:#16161e; --bg-lighter:#24283b;
  --bg-highlight:#292e42; --terminal-black:#414868;
  --foreground:#e6e6fa; --foreground-dark:#8b7aa8; --comment:#8b7aa8;
  --cyan:#00e8ff; --blue:#00a2ff; --purple:#b620e0; --magenta:#ff006e;
  --pink:#ff10f0; --red:#ff2975; --orange:#ff7c00; --yellow:#ffea00;
  --green:#00ff9f; --teal:#00ff9f; --border:#ff10f0; --selection:#33467c;
  --glow:rgba(255,16,240,0.3); --digital-rain:#00ff41;
  --title-accent:var(--purple);
}
*{margin:0;padding:0;box-sizing:border-box;}
html{font-size:16px;scroll-behavior:smooth;}
body{background:var(--bg-dark);color:var(--foreground);
  font-family:'JetBrains Mono','Fira Code','SF Mono','Monaco','Roboto Mono',monospace;
  line-height:1.7;min-height:100vh;}
::selection{background:var(--selection);color:var(--foreground);}
a{color:var(--cyan);text-decoration:none;}
a:hover{text-shadow:0 0 8px var(--glow);}

.terminal-window{background:var(--bg-darker);border:1px solid var(--terminal-black);
  border-radius:8px;margin:20px auto;max-width:1100px;overflow:hidden;
  box-shadow:0 0 0 1px rgba(0,0,0,.3),0 25px 50px -12px rgba(0,0,0,.5),0 0 60px rgba(255,16,240,.15);}
.terminal-header{background:linear-gradient(180deg,var(--bg-highlight)0%,var(--bg-lighter)100%);
  padding:12px 16px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--terminal-black);}
.terminal-buttons{display:flex;gap:8px;}
.terminal-btn{width:12px;height:12px;border-radius:50%;border:none;}
.terminal-btn.close{background:var(--red);}
.terminal-btn.minimize{background:var(--yellow);}
.terminal-btn.maximize{background:var(--green);}
.terminal-title{flex:1;text-align:center;color:var(--foreground-dark);font-size:.85rem;}
.terminal-body{padding:24px;}

.ascii-header{color:var(--cyan);font-size:.7rem;line-height:1.2;margin-bottom:8px;
  text-shadow:0 0 10px var(--glow);white-space:pre;overflow-x:auto;}
.tagline{color:var(--foreground-dark);font-size:.85rem;margin-bottom:6px;}
.tagline::before{content:'// ';color:var(--green);}

.nav-section{margin:18px 0;padding:14px 0;border-top:1px dashed var(--terminal-black);
  border-bottom:1px dashed var(--terminal-black);}
.nav-list{list-style:none;display:flex;flex-wrap:wrap;gap:10px 25px;}
.nav-item a{color:var(--foreground);display:inline-flex;align-items:center;gap:8px;transition:all .2s;}
.nav-item a::before{content:'>';color:var(--green);}
.nav-item a:hover{color:var(--cyan);}
.nav-item a:hover::before{color:var(--pink);}

.prompt-line{margin:14px 0 6px;}
.prompt-user{color:var(--cyan);} .prompt-at{color:var(--foreground-dark);}
.prompt-host{color:var(--purple);} .prompt-path{color:var(--blue);} .prompt-symbol{color:var(--pink);}

.meta-row{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 8px;}
.chip{background:var(--bg-lighter);border:1px solid var(--terminal-black);
  border-radius:4px;padding:4px 12px;font-size:.8rem;color:var(--foreground-dark);}
.chip b{color:var(--foreground);}
.difficulty{padding:4px 12px;border-radius:4px;font-size:.8rem;color:var(--bg-dark);font-weight:700;}
.difficulty-easy{background:var(--green);} .difficulty-medium{background:var(--orange);}
.difficulty-hard{background:var(--red);} .difficulty-insane{background:var(--purple);}

.flag-box{background:var(--bg-lighter);border:1px solid var(--terminal-black);
  border-left:3px solid var(--green);border-radius:0 4px 4px 0;padding:12px 16px;margin:10px 0;}
.flag-box .lbl{color:var(--green);}
.flag-box code{color:var(--yellow);}

.content h1{color:var(--purple);font-size:1.5rem;margin:34px 0 14px;border-bottom:1px solid var(--terminal-black);padding-bottom:8px;}
.content h1::before{content:'## ';color:var(--pink);}
.content h2{color:var(--cyan);font-size:1.15rem;margin:26px 0 12px;}
.content h2::before{content:'# ';color:var(--pink);}
.content h3{color:var(--blue);font-size:1rem;margin:20px 0 10px;}
.content h3::before{content:'> ';color:var(--green);}
.content p{margin:10px 0;} .content ul,.content ol{margin:10px 0 10px 24px;}
.content li{margin:4px 0;}
.content strong{color:var(--pink);}
.content blockquote{border-left:3px solid var(--orange);background:var(--bg-lighter);
  padding:8px 16px;margin:12px 0;color:var(--foreground-dark);border-radius:0 4px 4px 0;}
.content hr{border:none;border-top:1px dashed var(--terminal-black);margin:24px 0;}

pre,code{font-family:'JetBrains Mono','Fira Code',monospace;}
.content pre,.content .highlight{background:var(--bg-darker);border:1px solid var(--terminal-black);
  border-radius:4px;padding:15px;overflow-x:auto;margin:15px 0;}
.content code{background:var(--bg-lighter);padding:2px 6px;border-radius:3px;color:var(--orange);}
.content pre code,.content .highlight code{background:none;padding:0;color:var(--foreground);}

.content table{border-collapse:collapse;margin:15px 0;width:100%;font-size:.9rem;}
.content th,.content td{border:1px solid var(--terminal-black);padding:8px 12px;text-align:left;}
.content th{background:var(--bg-highlight);color:var(--cyan);}
.content tr:nth-child(even){background:var(--bg-lighter);}

.content img{max-width:100%;border:1px solid var(--terminal-black);border-radius:4px;margin:14px 0;
  box-shadow:0 0 20px rgba(255,16,240,.12);}

footer{margin-top:30px;padding-top:16px;border-top:1px dashed var(--terminal-black);
  color:var(--foreground-dark);font-size:.85rem;}
@media(max-width:768px){.ascii-header{font-size:.45rem;}}
"""

# ── HackSmarter "edge" style ────────────────────────────────────────────────
# Ported from writeups/hacksmarter/edge/writeup.html: GitHub-dark palette, IBM
# Plex Mono, green-dominant headings, a sticky left sidebar with site nav + an
# auto-generated "on this page" table of contents.
EDGE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;600&family=Inter:wght@300;400;500&display=swap');
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root{
  --bg:#0d1117; --bg2:#010409; --bg3:#161b22; --border:#21262d;
  --text:#c9d1d9; --muted:#8b949e; --green:#39d353; --green-bright:#56d364;
  --cyan:#58a6ff; --amber:#e3b341; --red:#f85149;
  --mono:'IBM Plex Mono','Courier New',monospace; --sans:'Inter',system-ui,sans-serif;
}
html{scroll-behavior:smooth;}
body{background:var(--bg2);color:var(--text);font-family:var(--mono);font-size:14px;
  line-height:1.7;display:flex;flex-direction:column;min-height:100vh;}
.site-header{background:var(--bg2);border-bottom:1px solid var(--border);padding:1.5rem 2rem;}
.site-header pre.ascii-logo{font-family:var(--mono);font-size:11px;line-height:1.2;color:var(--green);
  text-shadow:0 0 8px rgba(57,211,83,0.5);white-space:pre;overflow-x:auto;margin-bottom:0.5rem;}
.site-header .tagline{color:var(--muted);font-size:12px;}
.wrapper{display:flex;flex:1;max-width:1200px;width:100%;margin:0 auto;}
aside.sidebar{width:240px;min-width:240px;background:var(--bg2);border-right:1px solid var(--border);
  padding:2rem 1.5rem;position:sticky;top:0;height:100vh;overflow-y:auto;}
aside.sidebar .sidebar-label{color:var(--muted);font-size:11px;text-transform:uppercase;
  letter-spacing:0.08em;margin-bottom:1rem;}
aside.sidebar nav ul{list-style:none;} aside.sidebar nav ul li{margin-bottom:0.35rem;}
aside.sidebar nav ul li a{color:var(--muted);text-decoration:none;font-size:13px;transition:color 0.15s;
  display:block;padding:0.2rem 0.4rem;border-radius:3px;}
aside.sidebar nav ul li a:hover,aside.sidebar nav ul li a.active{color:var(--green);background:rgba(57,211,83,0.08);}
aside.sidebar .divider{border:none;border-top:1px solid var(--border);margin:1.2rem 0;}
aside.sidebar .toc-label{color:var(--muted);font-size:11px;text-transform:uppercase;
  letter-spacing:0.08em;margin-bottom:0.6rem;}
aside.sidebar .toc a{color:var(--muted);font-size:12px;text-decoration:none;display:block;
  padding:0.15rem 0.4rem;border-radius:3px;transition:color 0.15s;border-left:2px solid transparent;}
aside.sidebar .toc a:hover{color:var(--green);background:rgba(57,211,83,0.06);}
aside.sidebar .toc a.lvl-2{padding-left:1rem;font-size:11px;}
aside.sidebar .toc a.lvl-3{padding-left:1.7rem;font-size:11px;color:#6e7681;}
main.content{flex:1;background:var(--bg);padding:2.5rem 3rem 4rem;min-width:0;}
.breadcrumb{font-family:var(--mono);font-size:12px;color:var(--muted);margin-bottom:2rem;}
.breadcrumb .prompt{color:var(--green);} .breadcrumb .path{color:var(--cyan);}
main.content h1{font-family:var(--mono);font-size:1.6rem;color:var(--green-bright);font-weight:600;
  margin:2.5rem 0 1rem;padding-bottom:0.4rem;border-bottom:1px solid var(--border);}
main.content h1:first-of-type{margin-top:0;}
main.content h2{font-family:var(--mono);font-size:1.15rem;color:#7ee787;font-weight:500;margin:2rem 0 0.75rem;}
main.content h3{font-family:var(--mono);font-size:1rem;color:var(--amber);font-weight:500;margin:1.5rem 0 0.6rem;}
main.content p{margin-bottom:1rem;color:var(--text);line-height:1.75;}
main.content a{color:var(--cyan);text-decoration:none;} main.content a:hover{text-decoration:underline;}
main.content strong{color:var(--green-bright);}
main.content code{font-family:var(--mono);font-size:12.5px;background:rgba(110,118,129,0.15);
  border:1px solid var(--border);padding:0.1em 0.4em;border-radius:3px;color:#f0a0a0;}
main.content pre,main.content .highlight{font-family:var(--mono);font-size:12.5px;background:var(--bg3);
  border:1px solid var(--border);border-left:3px solid #30363d;border-radius:4px;padding:1.1rem 1.25rem;
  overflow-x:auto;margin:0.5rem 0 1.25rem;color:#e6edf3;line-height:1.6;}
main.content pre code,main.content .highlight code{background:none;border:none;padding:0;font-size:inherit;color:inherit;border-radius:0;}
main.content hr{border:none;border-top:1px solid var(--border);margin:2.5rem 0;}
main.content ul,main.content ol{margin:0.5rem 0 1rem 1.5rem;color:var(--text);}
main.content li{margin-bottom:0.4rem;line-height:1.7;}
main.content blockquote{border-left:3px solid var(--amber);background:var(--bg3);padding:0.6rem 1rem;
  margin:1rem 0;color:var(--muted);border-radius:0 4px 4px 0;}
main.content table{border-collapse:collapse;width:100%;margin:1rem 0 1.5rem;font-size:13px;}
main.content th{background:var(--bg3);color:var(--muted);font-weight:500;text-align:left;padding:0.5rem 0.75rem;border:1px solid var(--border);}
main.content td{padding:0.45rem 0.75rem;border:1px solid var(--border);color:var(--text);}
main.content tr:nth-child(even) td{background:rgba(255,255,255,0.02);}
main.content img{max-width:100%;border:1px solid var(--border);border-radius:4px;margin:1rem 0;}
table.meta-table{border-collapse:collapse;margin:1.5rem 0 2rem;width:auto;min-width:420px;}
table.meta-table th,table.meta-table td{border:1px solid var(--border);padding:0.45rem 0.9rem;font-size:13px;}
table.meta-table th{background:var(--bg3);color:var(--muted);font-weight:400;text-align:left;width:110px;}
table.meta-table td{color:var(--text);} table.meta-table tr:nth-child(even) td{background:rgba(255,255,255,0.015);}
footer.site-footer{background:var(--bg2);border-top:1px solid var(--border);padding:1rem 2rem;
  color:var(--muted);font-size:12px;text-align:center;}
::-webkit-scrollbar{width:6px;height:6px;} ::-webkit-scrollbar-track{background:var(--bg2);}
::-webkit-scrollbar-thumb{background:#30363d;border-radius:3px;} ::-webkit-scrollbar-thumb:hover{background:#484f58;}
@media(max-width:900px){
  .wrapper{flex-direction:column;}
  aside.sidebar{width:100%;min-width:0;height:auto;position:static;border-right:none;border-bottom:1px solid var(--border);}
  main.content{padding:1.5rem 1.25rem 3rem;}
  .site-header pre.ascii-logo{font-size:7px;}
}
"""

# Sidebar site-nav for the edge style. {slug} is substituted for the active item.
EDGE_NAV = [
    ("~/ home", "#", False),
    ("~/ctf/", "#", False),
    ("~/ctf/{slug}", "#", True),
    ("~/blog/", "#", False),
    ("~/vulnresearch/", "#", False),
    ("~/about/", "#", False),
]


def parse_frontmatter(text: str):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip()
            body = text[end + 4:].lstrip("\n")
            for line in block.splitlines():
                if ":" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition(":")
                    meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta, body


def strip_hacksmarter_preamble(body: str):
    """HackSmarter writeups embed their own ASCII masthead, tagline, and
    breadcrumb before the `# <Title>` heading. The renderer supplies those,
    so drop everything up to and including the first `# ` heading and return
    (title, remaining_body). If no heading is found early, leave body intact.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines[:20]):
        if line.startswith("# "):
            title = line[2:].strip()
            return title, "\n".join(lines[i + 1:]).lstrip("\n")
    return None, body


def flatten_toc(tokens, acc=None):
    """Flatten the markdown TocExtension token tree into an ordered list of
    (level, id, name) for building a sidebar table of contents."""
    if acc is None:
        acc = []
    for t in tokens:
        acc.append((t["level"], t["id"], t["name"]))
        if t.get("children"):
            flatten_toc(t["children"], acc)
    return acc


def inline_images(html: str, base: Path) -> str:
    pat = re.compile(r'<img\s+([^>]*?)src="([^"]+)"([^>]*?)>')

    def repl(m):
        pre, src, post = m.group(1), m.group(2), m.group(3)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        p = (base / src).resolve()
        if not p.is_file():
            return f'<img {pre}src="{src}" alt="MISSING:{src}"{post}>'
        mime, _ = mimetypes.guess_type(str(p))
        if not mime or not mime.startswith("image/"):
            return m.group(0)
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f'<img {pre}src="data:{mime};base64,{b64}"{post}>'

    return pat.sub(repl, html)


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_edge(machine_dir, slug, title, brand, md_html, toc_items) -> Path:
    """Render the HackSmarter "edge" style: GitHub-dark theme with a sticky
    left sidebar (site nav + auto-generated table of contents)."""
    section = brand["section"]
    tagline = brand["tagline"]
    page_title = brand["page_title"].format(title=esc(title))

    # Pygments without its own background so the edge code-block style shows.
    pyg = HtmlFormatter(style="monokai", nobackground=True).get_style_defs(".highlight")

    # Style the metadata table (first table in the body) as a compact meta-table.
    md_html = re.sub(r"<table>", '<table class="meta-table">', md_html, count=1)

    site_nav = ""
    for label, href, active in EDGE_NAV:
        cls = ' class="active"' if active else ""
        site_nav += f'<li><a href="{href}"{cls}>{esc(label.format(slug=slug))}</a></li>'

    toc_links = ""
    for level, hid, name in toc_items:
        if level > 3:
            continue
        cls = f' class="lvl-{level}"' if level > 1 else ""
        prefix = "↳ " if level > 1 else ""
        toc_links += f'<a href="#{hid}"{cls}>{prefix}{esc(name)}</a>'
    toc_block = (
        f'<hr class="divider"><div class="toc-label">on this page</div>'
        f'<nav class="toc">{toc_links}</nav>'
        if toc_links else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<style>{EDGE_CSS}
{pyg}</style></head>
<body>
<header class="site-header">
<pre class="ascii-logo">{esc(JFM_ASCII)}</pre>
<div class="tagline">{esc(tagline)}</div>
</header>
<div class="wrapper">
<aside class="sidebar">
  <div class="sidebar-label">navigation</div>
  <nav><ul>{site_nav}</ul></nav>
  {toc_block}
</aside>
<main class="content">
  <div class="breadcrumb"><span class="prompt">jfm@kali</span>:<span class="path">~/{esc(section)}/{esc(slug)}</span>$</div>
  <h1>{esc(title)}</h1>
{md_html}
</main>
</div>
<footer class="site-footer">{esc(tagline)}</footer>
</body></html>"""

    out = machine_dir / "writeup.html"
    out.write_text(html, encoding="utf-8")
    return out


def build(machine_dir: Path, style: str = "htb") -> Path:
    src = machine_dir / "writeup.md"
    if not src.is_file():
        sys.stderr.write(f"error: {src} not found\n")
        sys.exit(1)

    brand = STYLES[style]
    meta, body = parse_frontmatter(src.read_text(encoding="utf-8"))
    slug = machine_dir.name

    if style == "hacksmarter":
        ks_title, body = strip_hacksmarter_preamble(body)
        title = meta.get("title") or ks_title or slug.capitalize()
    else:
        title = meta.get("title", machine_dir.name.capitalize())
    diff = meta.get("difficulty", "").strip().lower()

    md_parser = md.Markdown(
        extensions=[
            "fenced_code", "tables", "attr_list", "sane_lists",
            CodeHiliteExtension(guess_lang=False, css_class="highlight"),
            TocExtension(permalink=False),
        ],
    )
    md_html = md_parser.convert(body)
    md_html = inline_images(md_html, machine_dir)
    toc_items = flatten_toc(getattr(md_parser, "toc_tokens", []))

    if style == "hacksmarter":
        return build_edge(
            machine_dir, slug, title, brand, md_html, toc_items,
        )

    pyg = HtmlFormatter(style="monokai").get_style_defs(".highlight")

    chips = []
    if meta.get("os"):
        chips.append(f'<span class="chip"><b>OS</b> {esc(meta["os"])}</span>')
    if meta.get("date"):
        chips.append(f'<span class="chip"><b>Date</b> {esc(meta["date"])}</span>')
    if meta.get("ip"):
        chips.append(f'<span class="chip"><b>IP</b> {esc(meta["ip"])}</span>')
    if meta.get("points"):
        chips.append(f'<span class="chip"><b>Points</b> {esc(meta["points"])}</span>')
    if diff:
        chips.append(f'<span class="difficulty difficulty-{diff}">{esc(diff)}</span>')
    if meta.get("tags"):
        for t in meta["tags"].split(","):
            t = t.strip()
            if t:
                chips.append(f'<span class="chip">{esc(t)}</span>')

    flags = []
    if meta.get("user_flag"):
        flags.append(f'<div class="flag-box"><span class="lbl">user.txt</span> &rarr; <code>{esc(meta["user_flag"])}</code></div>')
    if meta.get("root_flag"):
        flags.append(f'<div class="flag-box"><span class="lbl">root.txt</span> &rarr; <code>{esc(meta["root_flag"])}</code></div>')

    nav = "".join(
        f'<li class="nav-item"><a href="{href}">{esc(label)}</a></li>'
        for label, href in brand["nav"]
    )

    section = brand["section"]
    prompt = (
        f'<div class="prompt-line"><span class="prompt-user">jfm</span>'
        f'<span class="prompt-at">@</span><span class="prompt-host">kali</span>'
        f'<span class="prompt-path">:~/{esc(section)}/{esc(slug)}</span>'
        f'<span class="prompt-symbol">$</span> cat writeup.md</div>'
    )
    page_title = brand["page_title"].format(title=esc(title))
    tagline = brand["tagline"]

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}
{pyg}
{brand["extra_css"]}</style></head>
<body>
<div class="terminal-window">
  <div class="terminal-header">
    <div class="terminal-buttons">
      <button class="terminal-btn close"></button>
      <button class="terminal-btn minimize"></button>
      <button class="terminal-btn maximize"></button>
    </div>
    <div class="terminal-title">jfm@kali: ~/{esc(section)}/{esc(slug)} — writeup</div>
  </div>
  <div class="terminal-body">
    <div class="ascii-header">{esc(JFM_ASCII)}</div>
    <div class="tagline">{esc(tagline)}</div>
    <nav class="nav-section"><ul class="nav-list">{nav}</ul></nav>
    {prompt}
    <h1 style="color:var(--title-accent);font-size:1.8rem;margin:14px 0 4px;">{esc(title)}</h1>
    <div class="meta-row">{''.join(chips)}</div>
    {''.join(flags)}
    <div class="content">
{md_html}
    </div>
    <footer>
      <span class="prompt-user">jfm</span><span class="prompt-at">@</span><span class="prompt-host">kali</span>
      <span class="prompt-symbol"> $</span> — {esc(tagline)}
    </footer>
  </div>
</div>
</body></html>"""

    out = machine_dir / "writeup.html"
    out.write_text(html, encoding="utf-8")
    return out


def detect_style(machine_dir: Path) -> str:
    parts = {p.lower() for p in machine_dir.parts}
    if "hacksmarter" in parts:
        return "hacksmarter"
    return "htb"


def main():
    args = [a for a in sys.argv[1:]]
    style = None
    if "--style" in args:
        i = args.index("--style")
        try:
            style = args[i + 1]
            del args[i:i + 2]
        except IndexError:
            sys.stderr.write("error: --style requires a value (htb|hacksmarter)\n")
            sys.exit(2)
    if not args:
        sys.stderr.write(
            "usage: render_htb_writeup.py <writeup-dir> [--style htb|hacksmarter]\n"
        )
        sys.exit(2)
    machine_dir = Path(args[0]).resolve()
    if not machine_dir.is_dir():
        sys.stderr.write(f"error: {machine_dir} is not a directory\n")
        sys.exit(1)
    if style is None:
        style = detect_style(machine_dir)
    if style not in STYLES:
        sys.stderr.write(f"error: unknown style '{style}' (use htb|hacksmarter)\n")
        sys.exit(2)
    out = build(machine_dir, style)
    print(f"[+] rendered {out}  ({out.stat().st_size // 1024} KB)  [style={style}]")


if __name__ == "__main__":
    main()
