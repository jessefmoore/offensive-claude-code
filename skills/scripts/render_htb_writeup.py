"""Render an HTB machine writeup.md into a self-contained writeup.html styled
like the p3ta00 CTF blog (JetBrains Mono, "Cyberpunk Neon" terminal theme),
re-branded with a JFM ASCII masthead.

Self-contained: embedded CSS, embedded Pygments syntax styles, Google-Fonts
JetBrains Mono inlined via @import fallback + system monospace, and every
referenced screenshot base64-inlined. Opens offline with no broken assets.

Layout (see agents/report-writer-htb.md):

    writeups/htb/<machine-slug>/
        writeup.md         <- input (YAML-ish frontmatter + markdown body)
        writeup.html       <- output
        assets/            <- screenshots referenced via ![](assets/...)

Frontmatter keys (between leading '---' fences):
    title, os, difficulty, date, ip, points, user_flag, root_flag, tags

Dependencies:
    markdown, pygments   (pip install markdown pygments)

Usage:
    python render_htb_writeup.py writeups/htb/silentium
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

TAGLINE = "Sr. cybersecurity advisor | and helping others with cybersecurity"

NAV_ITEMS = [
    ("~/ home", "https://p3ta00.github.io/"),
    ("~/htb", "#"),
    ("~/writeups", "#"),
    ("~/about", "#"),
]

CSS = """
:root{
  --bg-dark:#1a1b26; --bg-darker:#16161e; --bg-lighter:#24283b;
  --bg-highlight:#292e42; --terminal-black:#414868;
  --foreground:#e6e6fa; --foreground-dark:#8b7aa8; --comment:#8b7aa8;
  --cyan:#00e8ff; --blue:#00a2ff; --purple:#b620e0; --magenta:#ff006e;
  --pink:#ff10f0; --red:#ff2975; --orange:#ff7c00; --yellow:#ffea00;
  --green:#00ff9f; --teal:#00ff9f; --border:#ff10f0; --selection:#33467c;
  --glow:rgba(255,16,240,0.3); --digital-rain:#00ff41;
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


def build(machine_dir: Path) -> Path:
    src = machine_dir / "writeup.md"
    if not src.is_file():
        sys.stderr.write(f"error: {src} not found\n")
        sys.exit(1)

    meta, body = parse_frontmatter(src.read_text(encoding="utf-8"))
    title = meta.get("title", machine_dir.name.capitalize())
    slug = machine_dir.name
    diff = meta.get("difficulty", "").strip().lower()

    md_html = md.markdown(
        body,
        extensions=[
            "fenced_code", "tables", "attr_list", "sane_lists",
            CodeHiliteExtension(guess_lang=False, css_class="highlight"),
            TocExtension(permalink=False),
        ],
    )
    md_html = inline_images(md_html, machine_dir)

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
        for label, href in NAV_ITEMS
    )

    prompt = (
        f'<div class="prompt-line"><span class="prompt-user">jfm</span>'
        f'<span class="prompt-at">@</span><span class="prompt-host">kali</span>'
        f'<span class="prompt-path">:~/htb/{esc(slug)}</span>'
        f'<span class="prompt-symbol">$</span> cat writeup.md</div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JFM // {esc(title)} — HTB</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}
{pyg}</style></head>
<body>
<div class="terminal-window">
  <div class="terminal-header">
    <div class="terminal-buttons">
      <button class="terminal-btn close"></button>
      <button class="terminal-btn minimize"></button>
      <button class="terminal-btn maximize"></button>
    </div>
    <div class="terminal-title">jfm@kali: ~/htb/{esc(slug)} — writeup</div>
  </div>
  <div class="terminal-body">
    <div class="ascii-header">{esc(JFM_ASCII)}</div>
    <div class="tagline">{esc(TAGLINE)}</div>
    <nav class="nav-section"><ul class="nav-list">{nav}</ul></nav>
    {prompt}
    <h1 style="color:var(--purple);font-size:1.8rem;margin:14px 0 4px;">{esc(title)}</h1>
    <div class="meta-row">{''.join(chips)}</div>
    {''.join(flags)}
    <div class="content">
{md_html}
    </div>
    <footer>
      <span class="prompt-user">jfm</span><span class="prompt-at">@</span><span class="prompt-host">kali</span>
      <span class="prompt-symbol"> $</span> — Sr. cybersecurity advisor · helping others with cybersecurity
    </footer>
  </div>
</div>
</body></html>"""

    out = machine_dir / "writeup.html"
    out.write_text(html, encoding="utf-8")
    return out


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: render_htb_writeup.py <writeups/htb/machine-dir>\n")
        sys.exit(2)
    machine_dir = Path(sys.argv[1]).resolve()
    if not machine_dir.is_dir():
        sys.stderr.write(f"error: {machine_dir} is not a directory\n")
        sys.exit(1)
    out = build(machine_dir)
    print(f"[+] rendered {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
