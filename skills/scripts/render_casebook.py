"""Render a pentest engagement directory into a single self-contained HTML
"operator casebook" deliverable, alongside the existing report.md/report.html.

Inputs (read-only):
    engagements/<client-slug>/<YYYY-MM-DD>/
        engagement.yaml      client/dates/scope/model/assessor
        report.md            findings (parsed F-section by F-section)
        timeline.md          event log
        hosts.csv            host,ip,finding_id,proto,port
        evidence/raw/*.txt   command transcripts (inlined into .term blocks)
        attack_graph.mmd     OPTIONAL — operator-authored mermaid attack graph

Output:
    engagements/<client-slug>/<YYYY-MM-DD>/casebook.html

Usage:
    python skills/scripts/render_casebook.py \
        --engagement engagements/lehack2024/2026-05-22/ \
        --out engagements/lehack2024/2026-05-22/casebook.html
    # or simply:
    python skills/scripts/render_casebook.py \
        --engagement engagements/lehack2024/2026-05-22/

Idempotent — each run regenerates the file from current engagement state.
Stdlib only — no jinja/markdown/yaml deps required (we ship our own
minimal parsers for the structured-but-simple inputs we control).
"""
from __future__ import annotations
import argparse
import csv
import html
import json
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# CSS — phosphor-green operator-casebook aesthetic, ported from a friend's
# DFIR-casebook stylesheet, trimmed to the classes we use.
# ---------------------------------------------------------------------------
CSS = r"""
:root {
  --bg: #05070a;
  --bg-1: #0b0f14;
  --panel: #0e1319;
  --line: #1f2833;
  --line-2: #2b3645;
  --text: #e6edf3;
  --muted: #8b949e;
  --dim: #5a6472;
  --green: #00ff9c;
  --green-d: #00b36b;
  --red: #ff3b3b;
  --red-d: #a81212;
  --amber: #ffb800;
  --cyan: #58a6ff;
  --violet: #c084fc;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; background: var(--bg); color: var(--text);
  font-family: 'Inter', -apple-system, system-ui, sans-serif;
  scroll-behavior: smooth; overflow-x: hidden;
  font-size: clamp(17px, 0.6vw + 15px, 20px); line-height: 1.72;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
body::before {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(1400px 700px at 90% -10%, rgba(255,59,59,.10), transparent 60%),
    radial-gradient(1200px 800px at -10% 20%, rgba(0,255,156,.06), transparent 55%),
    radial-gradient(900px 600px at 50% 110%, rgba(88,166,255,.06), transparent 60%);
}
body::after {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 1;
  background-image:
    linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse at center, rgba(0,0,0,.85), transparent 80%);
}
.crt {
  position: fixed; inset: 0; pointer-events: none; z-index: 2;
  background: repeating-linear-gradient(180deg, rgba(255,255,255,0) 0px,
    rgba(255,255,255,0) 3px, rgba(255,255,255,.018) 4px);
}
main { position: relative; z-index: 3; width: 100%; }
code, pre, .mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
em { font-style: italic; color: var(--text); }
b { color: var(--text); }
a { color: var(--cyan); text-decoration: none; }
a:hover { color: var(--green); }

section { padding: 6vw 7vw; border-top: 1px solid var(--line); position: relative; }
.section-tag {
  display: inline-flex; align-items: center; gap: 10px;
  font-family: 'IBM Plex Mono'; font-size: 10px;
  letter-spacing: .35em; color: var(--green); text-transform: uppercase;
  padding: 6px 12px; border: 1px solid var(--green-d);
  background: rgba(0,255,156,.03); border-radius: 2px;
  margin-bottom: 18px;
}
.section-tag::before {
  content: ""; width: 8px; height: 8px; background: var(--green);
  box-shadow: 0 0 10px var(--green); border-radius: 50%;
  animation: blink 1.6s ease-in-out infinite;
}
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: .25; } }

/* --- kill-chain replay ("video" playback) --- */
.kc { border:1px solid var(--line-2); border-radius:6px; background:linear-gradient(180deg, rgba(0,255,156,.03), transparent 60%); padding:18px; }
.kc-controls { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
.kc-btn { font-family:'IBM Plex Mono'; font-size:13px; cursor:pointer; padding:7px 13px; border:1px solid var(--line-2); border-radius:4px; background:var(--panel); color:var(--text); transition:all .2s; }
.kc-btn:hover { border-color:var(--green); color:var(--green); box-shadow:0 0 10px rgba(0,255,156,.2); }
.kc-btn.play { border-color:var(--green-d); color:var(--green); min-width:84px; }
.kc-speeds { display:inline-flex; gap:4px; margin-left:6px; }
.kc-speed { font-family:'IBM Plex Mono'; font-size:11px; cursor:pointer; padding:6px 9px; border:1px solid var(--line); border-radius:3px; background:transparent; color:var(--muted); }
.kc-speed.sel { color:var(--bg); background:var(--green); border-color:var(--green); font-weight:600; }
.kc-counter { font-family:'IBM Plex Mono'; font-size:12px; color:var(--muted); margin-left:auto; }
.kc-counter b { color:var(--green); }
.kc-progress { height:4px; background:var(--line); border-radius:2px; overflow:hidden; margin-bottom:16px; cursor:pointer; }
.kc-progress-fill { height:100%; width:0; background:linear-gradient(90deg, var(--cyan), var(--green)); box-shadow:0 0 8px var(--green); transition:width .25s linear; }

/* --- kill-chain replay: interactive SVG attack graph (pivot topology / forensic edges) --- */
@keyframes kc-nodepulse { 0%{ filter:drop-shadow(0 0 1px rgba(0,255,156,.5)); } 50%{ filter:drop-shadow(0 0 12px rgba(0,255,156,1)); } 100%{ filter:drop-shadow(0 0 1px rgba(0,255,156,.5)); } }
.kc-graph { width:100%; overflow:auto; border:1px solid var(--line-2); border-radius:6px; margin-bottom:14px;
  background: radial-gradient(900px 500px at 25% 0%, rgba(0,255,156,.05), transparent 60%), radial-gradient(700px 400px at 90% 100%, rgba(88,166,255,.05), transparent 60%), var(--bg-1); }
.kc-svg { display:block; }
.kc-lane { fill:rgba(255,255,255,.012); stroke:rgba(255,255,255,.05); }
.kc-lanelbl { font-family:'IBM Plex Mono'; font-size:10px; letter-spacing:.25em; fill:var(--dim); text-transform:uppercase; }
.kc-edge { stroke:var(--line-2); stroke-width:2; fill:none; opacity:.3; transition:stroke .35s, opacity .35s, filter .35s, stroke-width .35s; }
.kc-edge.fired { opacity:.95; stroke:var(--green); stroke-width:2.5; filter:drop-shadow(0 0 5px var(--green)); }
.kc-edge.p1.fired { stroke:var(--amber); filter:drop-shadow(0 0 5px var(--amber)); }
.kc-edge.p4.fired { stroke:var(--violet); filter:drop-shadow(0 0 5px var(--violet)); }
.kc-edge.p3.fired, .kc-edge.p5.fired { stroke:var(--red); filter:drop-shadow(0 0 5px var(--red)); }
.kc-elabel { font-family:'IBM Plex Mono'; font-size:9.5px; fill:var(--dim); opacity:0; transition:opacity .35s; }
.kc-elabel.fired { opacity:.95; fill:var(--text); }
.kc-node { cursor:pointer; opacity:.4; transition:opacity .35s; }
.kc-node.on { opacity:1; }
.kc-node.live > rect { animation:kc-nodepulse 1.1s ease-in-out; }
.kc-node > rect { fill:var(--panel); stroke:var(--line-2); stroke-width:1.5; }
.kc-node.np0 > rect { stroke:var(--cyan); }   .kc-node.npop > rect { stroke:var(--green); fill:rgba(0,255,156,.06); }
.kc-node.np1 > rect { stroke:var(--amber); }   .kc-node.np2 > rect { stroke:var(--cyan); }
.kc-node.np3 > rect, .kc-node.np5 > rect { stroke:var(--red); }   .kc-node.np4 > rect { stroke:var(--violet); }
.kc-node.on.np3 > rect, .kc-node.on.np5 > rect { fill:rgba(255,59,59,.07); }
.kc-node.on.np1 > rect { fill:rgba(255,184,0,.06); }   .kc-node.on.np4 > rect { fill:rgba(192,132,252,.07); }
.kc-nt { font-family:'IBM Plex Mono'; font-size:11px; font-weight:600; fill:var(--text); }
.kc-ns { font-family:'IBM Plex Mono'; font-size:10px; fill:var(--muted); }
.kc-detail { font-family:'IBM Plex Mono'; font-size:12px; color:var(--muted); border:1px solid var(--line); border-left:3px solid var(--green-d); border-radius:4px; padding:10px 12px; background:var(--panel); min-height:20px; }
.kc-detail b { color:var(--green); }
h2 {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: clamp(30px, 4.4vw, 62px);
  margin: 0 0 10px 0; line-height: .95; letter-spacing: -.015em;
  text-transform: uppercase;
}
h2 .q {
  background: linear-gradient(180deg, var(--green), var(--green-d));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
h3 {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: clamp(18px, 2vw, 24px); text-transform: uppercase;
  letter-spacing: .03em; margin: 28px 0 12px;
}
.lede { color: var(--muted); line-height: 1.7;
  font-size: clamp(15px, 0.7vw + 12px, 17.5px); margin-bottom: 40px; }
.lede b { color: var(--text); }

/* HERO */
.case-hero {
  min-height: 100vh; padding: 48px 7vw 60px;
  display: grid; grid-template-rows: auto 1fr auto; position: relative;
  background:
    linear-gradient(180deg, rgba(0,255,156,.04), transparent 30%),
    repeating-linear-gradient(0deg, rgba(255,255,255,.015) 0 1px, transparent 1px 6px);
}
.masthead {
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid var(--line-2);
  padding-bottom: 14px; padding-right: 70px;
  font-family: 'IBM Plex Mono'; font-size: 11px;
  letter-spacing: .2em; color: var(--muted); text-transform: uppercase;
}
.masthead .left { display: flex; gap: 28px; align-items: center; }
.masthead .left .bar { width: 28px; height: 2px; background: var(--green); box-shadow: 0 0 8px var(--green); }
.masthead .left strong { color: var(--text); letter-spacing: .25em; }
.masthead .right { display: flex; gap: 22px; flex-wrap: wrap; }
.masthead .right span::before { content: "● "; color: var(--green); }

.case-hero .body {
  display: grid; grid-template-columns: 1.2fr 1fr; gap: 64px;
  align-items: center; padding: 72px 0 48px;
}
.case-hero h1 {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: clamp(54px, 9vw, 140px);
  line-height: .85; letter-spacing: -.035em; margin: 0;
  text-transform: uppercase;
}
.case-hero h1 span { display: block; }
.case-hero h1 .l1 { color: var(--text); }
.case-hero h1 .l2 {
  background: linear-gradient(90deg, var(--green) 0%, var(--cyan) 60%, var(--text) 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.case-hero h1 .l3 { color: var(--text); opacity: .14; letter-spacing: -.035em; }
.case-hero .subhead {
  margin-top: 28px; color: var(--muted);
  font-size: clamp(15px, 0.55vw + 13px, 17px); line-height: 1.65;
}
.case-hero .subhead b { color: var(--text); font-weight: 600; }

.dossier {
  border: 1px solid var(--line-2);
  background: linear-gradient(180deg, var(--panel), rgba(14,19,25,.5));
  padding: 28px; position: relative;
  font-family: 'IBM Plex Mono'; font-size: 12px;
  box-shadow: 0 20px 60px rgba(0,0,0,.6);
}
.dossier::before {
  content: "ENGAGEMENT FILE"; position: absolute; top: -1px; left: 16px;
  transform: translateY(-50%);
  background: var(--bg); padding: 4px 10px;
  font-size: 10px; letter-spacing: .3em; color: var(--green);
  border: 1px solid var(--green-d);
}
.dossier .row {
  display: grid; grid-template-columns: 170px 1fr; gap: 16px;
  padding: 8px 0; border-bottom: 1px dashed var(--line);
}
.dossier .row:last-child { border-bottom: none; }
.dossier .k { color: var(--dim); text-transform: uppercase; letter-spacing: .15em; font-size: 10px; }
.dossier .v { color: var(--text); font-size: 13px; }
.dossier .v.red   { color: var(--red); }
.dossier .v.green { color: var(--green); }
.dossier .v.amber { color: var(--amber); }
.dossier .v code { color: var(--text); background: rgba(0,255,156,.06); padding: 1px 6px; font-size: 11px; border-radius: 2px; border: 1px solid rgba(0,255,156,.15); }

.stamp {
  position: absolute; pointer-events: none;
  border: 3px solid var(--red); color: var(--red);
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  letter-spacing: .1em; padding: 8px 16px; font-size: 18px;
  text-transform: uppercase; transform: rotate(-12deg); opacity: .75;
}
.stamp.s1 { top: 22%; right: 6%; }
.stamp.s2 { top: 80px; right: 6%;
  border-color: var(--amber); color: var(--amber);
  transform: rotate(8deg); font-size: 11px; padding: 6px 12px; }

.scoreboard {
  border-top: 1px solid var(--line-2);
  padding-top: 28px;
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 0;
}
.score-cell {
  padding: 14px 18px; border-right: 1px solid var(--line);
  font-family: 'IBM Plex Mono';
}
.score-cell:last-child { border-right: none; }
.score-cell .k { font-size: 10px; letter-spacing: .3em; color: var(--dim); text-transform: uppercase; }
.score-cell .v {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: clamp(24px, 2.6vw, 38px); margin-top: 4px; color: var(--text);
}
.score-cell .v.g { color: var(--green); }
.score-cell .v.r { color: var(--red); }
.score-cell .v.a { color: var(--amber); }
.score-cell .d { color: var(--muted); font-size: 11px; margin-top: 2px; }

/* SEVERITY BANNER */
.sev-banner {
  border: 1px solid var(--line-2); background: var(--panel);
  margin: 24px 0 36px; padding: 0;
  display: grid; grid-template-columns: 280px 1fr;
}
.sev-banner .sev-lvl {
  border-right: 1px solid var(--line-2); padding: 26px 24px;
  background: linear-gradient(180deg, rgba(255,59,59,.10), transparent 80%);
  display: flex; flex-direction: column; gap: 6px;
}
.sev-banner .sev-lvl .lab { font-size: 10px; letter-spacing: .3em; color: var(--dim); text-transform: uppercase; font-family: 'IBM Plex Mono'; }
.sev-banner .sev-lvl .val {
  font-family: 'Fraunces', Georgia, serif; font-weight: 700;
  font-size: clamp(32px, 4vw, 52px); color: var(--red);
  text-transform: uppercase; letter-spacing: .02em; line-height: .95;
}
.sev-banner .sev-lvl .sub { font-size: 12px; color: var(--muted); }
.sev-banner .sev-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 0;
}
.sev-banner .sg { padding: 18px 22px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); font-family: 'IBM Plex Mono'; }
.sev-banner .sg:nth-child(3n) { border-right: none; }
.sev-banner .sg:nth-last-child(-n+3) { border-bottom: none; }
.sev-banner .sg .k { font-size: 9px; letter-spacing: .3em; color: var(--dim); text-transform: uppercase; }
.sev-banner .sg .v {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: clamp(16px, 1.8vw, 22px); margin-top: 4px; color: var(--text);
}
.sev-banner .sg .v.red { color: var(--red); }
.sev-banner .sg .v.amber { color: var(--amber); }
.sev-banner .sg .v.green { color: var(--green); }
.sev-banner .sg .d { color: var(--muted); font-size: 11px; margin-top: 2px; }

/* ROADMAP */
.roadmap { margin: 18px 0 24px; border: 1px solid var(--line-2); background: var(--panel); }
.rm-track { display: grid; grid-template-columns: repeat(3, 1fr); border-bottom: 1px solid var(--line-2); }
.rm-phase { padding: 14px 22px; border-right: 1px solid var(--line-2); display: flex; flex-direction: column; gap: 4px; }
.rm-phase:last-child { border-right: none; }
.rm-phase.p0 { background: linear-gradient(180deg, rgba(255,59,59,.10), transparent); }
.rm-phase.p1 { background: linear-gradient(180deg, rgba(255,184,0,.10), transparent); }
.rm-phase.p2 { background: linear-gradient(180deg, rgba(88,166,255,.10), transparent); }
.rm-phase .rm-when { font-family: 'IBM Plex Mono'; font-size: 10px; letter-spacing: .25em; color: var(--dim); text-transform: uppercase; }
.rm-phase .rm-title { font-family: 'Fraunces', Georgia, serif; font-weight: 600; font-size: 17px; text-transform: uppercase; }
.rm-phase.p0 .rm-title { color: var(--red); }
.rm-phase.p1 .rm-title { color: var(--amber); }
.rm-phase.p2 .rm-title { color: var(--cyan); }
.rm-body { display: grid; grid-template-columns: repeat(3, 1fr); }
.rm-col { padding: 16px 22px; border-right: 1px solid var(--line-2); }
.rm-col:last-child { border-right: none; }
.rm-col .rm-h { font-family: 'IBM Plex Mono'; font-size: 10px; letter-spacing: .3em; color: var(--green); text-transform: uppercase; margin-bottom: 10px; }
.rm-col ul { margin: 0; padding-left: 18px; }
.rm-col li { font-size: 13.5px; margin: 6px 0; line-height: 1.55; color: var(--muted); }
.rm-col li b { color: var(--text); }
.rm-col li code { color: var(--text); background: rgba(0,255,156,.06); padding: 0 4px; border-radius: 2px; font-size: 11.5px; }

.residual-note {
  margin-top: 20px; padding: 14px 18px;
  border-left: 3px solid var(--red);
  background: linear-gradient(90deg, rgba(255,59,59,.06), transparent 60%);
  font-size: 14px; color: var(--muted); line-height: 1.65;
}
.residual-note b { color: var(--red); }

/* STORY */
.story-stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0; margin: 16px 0 28px;
  border: 1px solid var(--line-2); background: var(--panel);
}
.story-stats .ss {
  padding: 16px 20px; border-right: 1px solid var(--line);
  font-family: 'IBM Plex Mono';
}
.story-stats .ss:last-child { border-right: none; }
.story-stats .ss .n {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: 26px; color: var(--green);
}
.story-stats .ss.red .n { color: var(--red); }
.story-stats .ss .l { font-size: 11px; color: var(--muted); margin-top: 4px; letter-spacing: .04em; }
.story-prose p { color: var(--muted); margin: 0 0 1.2rem; line-height: 1.7; }
.story-prose p b { color: var(--text); }
.story-prose p code { color: var(--text); background: rgba(0,255,156,.06); padding: 1px 5px; border-radius: 2px; font-size: .9em; border: 1px solid rgba(0,255,156,.15); }
.story-prose p.end { color: var(--text); font-weight: 500; margin-top: 1.6rem; padding-top: 1rem; border-top: 1px solid var(--line); }

/* ACT CARD */
.act-card {
  padding: 10vw 7vw 4vw;
  border-top: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(0,255,156,.03), transparent 30%);
}
.act-card .num {
  font-family: 'IBM Plex Mono'; font-size: 12px; letter-spacing: .4em;
  color: var(--green); text-transform: uppercase; margin-bottom: 14px;
}
.act-card .title {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: clamp(48px, 8vw, 110px);
  line-height: .9; letter-spacing: -.025em; text-transform: uppercase;
  margin: 0;
}
.act-card .title span { color: var(--green); }
.act-card .timecode {
  font-family: 'IBM Plex Mono'; color: var(--muted); font-size: 13px;
  margin-top: 18px; letter-spacing: .15em;
}
.act-card .description {
  margin-top: 22px; color: var(--muted);
  font-size: clamp(15px, 0.55vw + 13px, 17px); line-height: 1.65;
}
.act-card .description b { color: var(--text); }
.act-card .description code { color: var(--text); background: rgba(0,255,156,.06); padding: 1px 5px; border-radius: 2px; font-size: .9em; border: 1px solid rgba(0,255,156,.15); }

/* EVENT LIST */
.event-list { display: grid; gap: 2px; border: 1px solid var(--line); background: rgba(0,0,0,.2); }
.event {
  display: grid; grid-template-columns: 170px 110px 160px 1fr;
  gap: 18px; padding: 14px 18px;
  background: var(--panel); border-left: 3px solid var(--line-2);
  font-family: 'IBM Plex Mono'; font-size: 12px; color: var(--text);
  transition: background .2s, border-color .2s;
}
.event:hover { background: #131a22; border-left-color: var(--green); }
.event.act1 { border-left-color: var(--cyan); }
.event.act2 { border-left-color: var(--amber); }
.event.act3 { border-left-color: var(--violet); }
.event.act4 { border-left-color: var(--red); }
.event.act5 { border-left-color: var(--green); }
.event .t { color: var(--green); font-weight: 600; }
.event .host { color: var(--cyan); font-size: 11px; letter-spacing: .1em; }
.event .eid { color: var(--amber); font-size: 11px; letter-spacing: .05em; }
.event .desc { color: var(--muted); word-break: break-word; }
.event .desc b { color: var(--text); }
.event .desc code { color: var(--text); background: rgba(0,255,156,.06); padding: 1px 6px; border-radius: 2px; font-size: 11px; border: 1px solid rgba(0,255,156,.15); }

/* TERMINAL */
.term {
  background: #05090d; border: 1px solid var(--line-2);
  border-radius: 4px; overflow: hidden; margin: 16px 0;
  box-shadow: 0 8px 32px rgba(0,0,0,.5);
}
.term-head {
  background: linear-gradient(180deg, #0d1319, #080b0f);
  padding: 8px 14px; display: flex; align-items: center; gap: 10px;
  border-bottom: 1px solid var(--line-2);
  font-family: 'IBM Plex Mono'; font-size: 11px; color: var(--dim);
  letter-spacing: .15em; text-transform: uppercase;
}
.term-head .dots { display: flex; gap: 6px; }
.term-head .dots b { width: 10px; height: 10px; border-radius: 50%; display: block; }
.term-head .dots b:nth-child(1) { background: var(--red); }
.term-head .dots b:nth-child(2) { background: var(--amber); }
.term-head .dots b:nth-child(3) { background: var(--green); }
.term-head .title { margin-left: 8px; color: var(--muted); }
.term-body {
  padding: 14px 16px; font-family: 'IBM Plex Mono'; font-size: 12.5px;
  color: var(--text); white-space: pre-wrap; word-break: break-word;
  line-height: 1.65; overflow-x: auto;
}
.term-body .prompt { color: var(--green); user-select: none; }
.term-body .cmd { color: var(--text); }
.term-body .out { color: var(--muted); }
.term-body .hit { color: var(--amber); }
.term-body .ok { color: var(--green); }
.term-body .bad { color: var(--red); }
.term-body .meta { color: var(--cyan); }
.term-body .comment { color: var(--dim); font-style: italic; }

/* HOSTS */
.host-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}
.host {
  background: var(--panel); border: 1px solid var(--line-2);
  padding: 18px; position: relative; transition: transform .25s, border-color .25s;
}
.host:hover { transform: translateY(-3px); border-color: var(--green-d); }
.host::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--line-2); }
.host.entry::before { background: var(--cyan); }
.host.dc::before    { background: var(--red); }
.host.piv::before   { background: var(--amber); }
.host.vict::before  { background: var(--violet); }
.host.cloud::before { background: var(--green); }
.host .name {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: 18px; letter-spacing: .02em;
  display: flex; justify-content: space-between; align-items: baseline;
}
.host .name .ip { font-family: 'IBM Plex Mono'; font-size: 11px; color: var(--cyan); font-weight: 400; }
.host .role { margin-top: 2px; font-family: 'IBM Plex Mono'; font-size: 10px; color: var(--dim); letter-spacing: .25em; text-transform: uppercase; }
.host .verdict { margin-top: 12px; font-size: 13px; color: var(--muted); line-height: 1.55; }
.host .verdict code { color: var(--text); font-size: 11px; }
.host .verdict .findings { font-family: 'IBM Plex Mono'; font-size: 11px; color: var(--amber); margin-top: 8px; }

/* TTP */
.ttp-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1px; background: var(--line); border: 1px solid var(--line);
}
.ttp { background: var(--panel); padding: 14px 16px; }
.ttp .tactic { font-family: 'IBM Plex Mono'; font-size: 10px; letter-spacing: .3em; color: var(--green); text-transform: uppercase; }
.ttp .tech { font-family: 'Fraunces', Georgia, serif; font-weight: 600; font-size: 14px; margin: 6px 0 2px; letter-spacing: .02em; line-height: 1.15; }
.ttp .tech-id { font-family: 'IBM Plex Mono'; color: var(--amber); font-size: 11px; }
.ttp .ev { font-size: 12px; color: var(--muted); margin-top: 8px; line-height: 1.45; }
.ttp .ev code { font-family: 'IBM Plex Mono'; color: var(--text); background: rgba(0,255,156,.05); padding: 1px 4px; font-size: 11px; border-radius: 2px; }

/* CHAINS */
.chain-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px; }
.chain { background: var(--panel); border: 1px solid var(--line-2); padding: 16px 18px; position: relative; }
.chain::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--green); }
.chain.partial::before { background: var(--amber); }
.chain.blocked::before { background: var(--red); }
.chain .n { font-family: 'Fraunces', Georgia, serif; font-weight: 600; font-size: 15px; letter-spacing: .02em; display: flex; justify-content: space-between; align-items: baseline; text-transform: uppercase; }
.chain .n .p { font-family: 'IBM Plex Mono'; font-size: 12px; color: var(--green); font-weight: 600; }
.chain.partial .n .p { color: var(--amber); }
.chain.blocked .n .p { color: var(--red); }
.chain .s { margin-top: 8px; font-size: 12.5px; color: var(--muted); line-height: 1.55; }
.chain .s code { color: var(--text); background: rgba(0,255,156,.06); padding: 1px 4px; border-radius: 2px; font-size: 11px; }
.chain .bar { margin-top: 12px; height: 3px; background: rgba(255,255,255,.04); border-radius: 1px; overflow: hidden; }
.chain .bar > i { display: block; height: 100%; background: linear-gradient(90deg, var(--green-d), var(--green)); }
.chain.partial .bar > i { background: linear-gradient(90deg, var(--amber), #ff9a00); }
.chain.blocked .bar > i { background: linear-gradient(90deg, var(--red-d), var(--red)); }

/* TABLES */
.tbl { width: 100%; border-collapse: collapse; font-family: 'IBM Plex Mono'; font-size: 12.5px; border: 1px solid var(--line-2); margin: 12px 0; }
.tbl th { background: var(--panel); padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--line-2); color: var(--green); font-size: 10px; letter-spacing: .2em; text-transform: uppercase; font-weight: 500; }
.tbl td { padding: 10px 14px; border-bottom: 1px solid var(--line); color: var(--text); vertical-align: top; }
.tbl tr:hover td { background: rgba(0,255,156,.02); }
.tbl td.m { color: var(--muted); }
.tbl td.g { color: var(--green); }
.tbl td.a { color: var(--amber); }
.tbl td.r { color: var(--red); }
.tbl td.c { color: var(--cyan); }
.tbl td code { color: var(--text); background: rgba(0,255,156,.06); padding: 1px 4px; border-radius: 2px; font-size: 11px; }

/* DEAD ENDS (reject cards) */
.reject {
  border-left: 3px solid var(--red);
  background: linear-gradient(90deg, rgba(255,59,59,.05), transparent 60%);
  padding: 14px 18px; margin: 10px 0;
  font-family: 'IBM Plex Mono'; font-size: 12.5px;
}
.reject .cid { color: var(--amber); font-size: 11px; letter-spacing: .15em; text-transform: uppercase; }
.reject .bad { color: var(--red); font-weight: 600; }
.reject .ok  { color: var(--green); }
.reject .why { margin-top: 6px; color: var(--muted); font-size: 12px; line-height: 1.5; }

/* GRAPH */
.graph-wrap {
  border: 1px solid var(--line-2);
  background: radial-gradient(800px 400px at 50% 50%, rgba(0,255,156,.04), transparent 70%), #05090d;
  padding: 24px; overflow-x: auto;
}
.graph-legend {
  margin-top: 18px; display: flex; flex-wrap: wrap; gap: 24px;
  font-family: 'IBM Plex Mono'; font-size: 13px; color: var(--text);
  padding: 14px 18px; background: rgba(5,9,13,.6);
  border: 1px solid var(--line-2); border-radius: 3px; letter-spacing: .04em;
}
.graph-legend .li { display: flex; align-items: center; gap: 12px; }
.graph-legend .li .sw { width: 36px; height: 4px; border-radius: 1px; }

/* CLOSE */
.close {
  padding: 10vw 7vw 6vw; text-align: center;
  border-top: 1px solid var(--line);
  background: radial-gradient(800px 400px at 50% 0%, rgba(0,255,156,.1), transparent 60%);
  position: relative;
}
.close .big {
  font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  font-size: clamp(40px, 7vw, 92px);
  line-height: .95; letter-spacing: -.03em; text-transform: uppercase;
  margin: 0; color: var(--text);
}
.close .big span { color: var(--green); }
.close .big em { color: var(--green); font-style: italic; }
.close .caption {
  color: var(--muted); margin-top: 18px; font-family: 'IBM Plex Mono';
  font-size: 13px; letter-spacing: .2em; line-height: 1.6;
}
.close .closed-stamp {
  display: inline-block; margin-top: 28px;
  border: 3px solid var(--green); color: var(--green);
  padding: 14px 28px; font-family: 'Fraunces', Georgia, serif; font-weight: 600;
  letter-spacing: .2em; text-transform: uppercase;
  transform: rotate(-3deg); box-shadow: 0 0 40px rgba(0,255,156,.25);
}
.close .closed-stamp.draft { border-color: var(--amber); color: var(--amber); box-shadow: 0 0 40px rgba(255,184,0,.25); }

/* REVEAL */
.reveal { opacity: 1; transform: none; transition: opacity .8s, transform .8s; }
body.js-fade .reveal:not(.in) { opacity: 0; transform: translateY(20px); }
.reveal.in { opacity: 1; transform: translateY(0); }

/* CHAPTER NAV */
.chapter-nav { position: fixed; top: 18px; right: 18px; z-index: 50; font-family: 'IBM Plex Mono'; font-size: 10.5px; }
.chapter-nav-toggle {
  display: flex; align-items: center; justify-content: center;
  width: 44px; height: 36px;
  background: rgba(5,7,10,.92);
  border: 1px solid var(--line-2); border-radius: 3px;
  color: var(--dim); font-family: inherit; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: color .2s, border-color .2s, width .25s;
  letter-spacing: .12em; box-shadow: 0 4px 18px rgba(0,0,0,.35);
}
.chapter-nav-toggle:hover, .chapter-nav.open .chapter-nav-toggle { color: var(--green); border-color: var(--green); }
.chapter-nav.open .chapter-nav-toggle { width: auto; padding: 0 14px; }
.chapter-nav-toggle-label { display: none; }
.chapter-nav.open .chapter-nav-toggle-label { display: inline; text-transform: uppercase; font-size: 10px; letter-spacing: .18em; }
.chapter-nav-list {
  position: absolute; top: 44px; right: 0;
  display: flex; flex-direction: column; gap: 1px;
  padding: 10px 0; max-height: 0; width: 280px;
  overflow: hidden; background: rgba(5,7,10,.94);
  border: 1px solid transparent; border-radius: 3px;
  box-shadow: 0 12px 32px rgba(0,0,0,.5);
  opacity: 0; pointer-events: none;
  transition: max-height .28s, opacity .2s, border-color .2s;
}
.chapter-nav.open .chapter-nav-list { max-height: 78vh; opacity: 1; overflow-y: auto; border-color: var(--line-2); pointer-events: auto; }
.chapter-nav-list a {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 16px; color: var(--dim); text-decoration: none;
  letter-spacing: .14em; text-transform: uppercase;
  border-left: 2px solid transparent; white-space: nowrap; line-height: 1.3;
}
.chapter-nav-list a::before { content: attr(data-num); width: 26px; color: var(--line-2); font-weight: 600; font-size: 9.5px; flex-shrink: 0; }
.chapter-nav-list a:hover { color: var(--text); background: rgba(0,255,156,.04); }
.chapter-nav-list a.active { color: var(--green); border-left-color: var(--green); background: rgba(0,255,156,.07); }
.chapter-nav-list a.active::before { color: var(--green); }

/* HOST DRAWER */
.drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.55); backdrop-filter: blur(4px); z-index: 100; opacity: 0; pointer-events: none; transition: opacity .3s; }
.drawer-overlay.open { opacity: 1; pointer-events: auto; }
.host-drawer {
  position: fixed; top: 0; right: 0; height: 100vh;
  width: min(540px, 96vw); z-index: 101;
  background: linear-gradient(180deg, var(--bg-1), var(--bg));
  border-left: 1px solid var(--green-d);
  box-shadow: -20px 0 60px rgba(0,0,0,.6);
  transform: translateX(100%); transition: transform .35s cubic-bezier(.2,.8,.2,1);
  overflow-y: auto; font-family: 'IBM Plex Mono';
}
.host-drawer.open { transform: translateX(0); }
.host-drawer .head {
  position: sticky; top: 0; z-index: 2;
  padding: 20px 24px 16px;
  background: linear-gradient(180deg, var(--bg-1), rgba(11,15,20,.9));
  border-bottom: 1px solid var(--line-2);
  display: flex; justify-content: space-between; align-items: flex-start;
}
.host-drawer .head .name { font-family: 'Fraunces', Georgia, serif; font-weight: 600; font-size: 22px; letter-spacing: .02em; text-transform: uppercase; }
.host-drawer .head .ip { font-size: 12px; color: var(--cyan); margin-top: 4px; }
.host-drawer .head .role { font-size: 10px; color: var(--dim); letter-spacing: .25em; text-transform: uppercase; margin-top: 8px; }
.host-drawer .close-btn { background: transparent; border: 1px solid var(--line-2); color: var(--muted); width: 32px; height: 32px; cursor: pointer; font-size: 18px; border-radius: 2px; }
.host-drawer .close-btn:hover { color: var(--red); border-color: var(--red); }
.host-drawer .body { padding: 20px 24px 80px; font-size: 12.5px; line-height: 1.65; }
.host-drawer h4 { font-family: 'IBM Plex Mono'; font-size: 10px; letter-spacing: .3em; color: var(--green); text-transform: uppercase; margin: 20px 0 10px; font-weight: 500; }
.host-drawer h4:first-child { margin-top: 0; }
.host-drawer ul { padding-left: 18px; margin: 0; }
.host-drawer li { color: var(--muted); margin: 4px 0; }
.host-drawer li b { color: var(--text); }
.host-clickable { cursor: pointer; }

/* RESPONSIVE */
@media (max-width: 1024px) {
  section { padding: 8vw 6vw; }
  .case-hero { padding: 24px 6vw 40px; }
  .case-hero .body { grid-template-columns: 1fr; gap: 32px; padding: 48px 0 32px; }
  .masthead { flex-direction: column; align-items: flex-start; gap: 10px; font-size: 10px; }
  .scoreboard { grid-template-columns: repeat(3, 1fr); }
  .sev-banner { grid-template-columns: 1fr; }
  .sev-banner .sev-lvl { border-right: none; border-bottom: 1px solid var(--line-2); }
  .rm-track, .rm-body { grid-template-columns: 1fr; }
  .rm-phase, .rm-col { border-right: none; border-bottom: 1px solid var(--line-2); }
  .act-card { padding: 14vw 6vw 6vw; }
  .event { grid-template-columns: 130px 1fr; gap: 6px 14px; }
  .event > .host, .event > .eid { grid-column: 2; font-size: 10px; }
  .event > .desc { grid-column: 1 / -1; }
}
@media (max-width: 760px) {
  body { font-size: 14px; }
  .scoreboard { grid-template-columns: repeat(2, 1fr); }
  .dossier { padding: 20px 18px; }
  .dossier .row { grid-template-columns: 1fr; gap: 4px; }
  .stamp.s1 { top: 16px; right: 16px; font-size: 13px; padding: 6px 10px; }
  .stamp.s2 { display: none; }
  .event { grid-template-columns: 1fr; }
  .ttp-grid, .chain-grid, .host-grid { grid-template-columns: 1fr; }
  .host-drawer { width: 100vw; }
}
"""

# ---------------------------------------------------------------------------
# JS — reveal-on-scroll, chapter-nav drawer toggle, host-drawer slide-out.
# Mermaid is loaded from CDN at the bottom of the document.
# ---------------------------------------------------------------------------
JS = r"""
document.body.classList.add('js-fade');

const io = new IntersectionObserver(entries => {
  entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('in'); });
}, { threshold: 0.08 });
document.querySelectorAll('.reveal').forEach(el => io.observe(el));

// Chapter nav drawer
const nav = document.querySelector('.chapter-nav');
const navToggle = document.querySelector('.chapter-nav-toggle');
if (nav && navToggle) {
  navToggle.addEventListener('click', () => nav.classList.toggle('open'));
  document.addEventListener('click', (e) => {
    if (!nav.contains(e.target)) nav.classList.remove('open');
  });
  const links = document.querySelectorAll('.chapter-nav-list a');
  const sections = Array.from(document.querySelectorAll('section[id]'));
  const navObserver = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        const id = e.target.id;
        links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
      }
    });
  }, { threshold: 0.3 });
  sections.forEach(s => navObserver.observe(s));
}

// Host drawer
const drawer = document.querySelector('.host-drawer');
const overlay = document.querySelector('.drawer-overlay');
const closeDrawer = () => {
  drawer && drawer.classList.remove('open');
  overlay && overlay.classList.remove('open');
};
if (drawer && overlay) {
  overlay.addEventListener('click', closeDrawer);
  document.querySelector('.host-drawer .close-btn')?.addEventListener('click', closeDrawer);
  document.querySelectorAll('.host-clickable').forEach(h => {
    h.addEventListener('click', () => {
      const data = JSON.parse(h.dataset.host || '{}');
      const head = drawer.querySelector('.head');
      head.querySelector('.name').textContent = data.name || '';
      head.querySelector('.ip').textContent = data.ip || '';
      head.querySelector('.role').textContent = data.role || '';
      const body = drawer.querySelector('.body');
      body.innerHTML = data.detail || '';
      drawer.classList.add('open');
      overlay.classList.add('open');
    });
  });
}

// Mermaid init
if (window.mermaid) {
  mermaid.initialize({
    startOnLoad: true,
    theme: 'dark',
    themeVariables: {
      darkMode: true,
      background: '#05090d',
      primaryColor: '#0e1319',
      primaryTextColor: '#e6edf3',
      primaryBorderColor: '#2b3645',
      lineColor: '#5a6472',
      secondaryColor: '#1f2833',
      tertiaryColor: '#0b0f14'
    },
    flowchart: { curve: 'basis', htmlLabels: true }
  });
}
"""

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    fid: str
    title: str
    rating: str = ""
    cvss_score: str = ""
    cvss_vector: str = ""
    cwe: str = ""
    mitre: str = ""
    hosts: str = ""
    location: str = ""
    description: str = ""
    discovery: str = ""
    evidence: str = ""
    impact: str = ""
    solution: str = ""
    remediation: str = ""
    references: str = ""
    body: str = ""


@dataclass
class TimelineEvent:
    when: str
    text: str


@dataclass
class HostRow:
    host: str
    ip: str
    findings: list[str] = field(default_factory=list)


SEVERITY_ORDER = ["critical", "high", "medium", "low", "informational", "info"]


def parse_yaml_lite(text: str) -> dict:
    """Minimal YAML key:value parser; sufficient for engagement.yaml."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        out[k] = v
    return out


def parse_findings(report_md: str) -> list[Finding]:
    """Pull F-section structured fields from the canonical report.md."""
    findings: list[Finding] = []
    # Split on lines that look like '### F<n> — title'
    pattern = re.compile(r"^### (F\d+)\s+—\s+(.+?)$", re.MULTILINE)
    matches = list(pattern.finditer(report_md))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report_md)
        body = report_md[start:end].strip()
        f = Finding(fid=m.group(1), title=m.group(2).strip())
        f.body = body
        f.rating = _kv_extract(body, "Rating")
        f.cvss_score = _kv_extract(body, r"CVSS\s*v?4(?:\.0)?\s*Score")
        f.cvss_vector = _kv_extract(body, r"CVSS\s*v?4(?:\.0)?\s*Vector")
        f.cwe = _kv_extract(body, "CWE")
        f.mitre = _kv_extract(body, r"MITRE ATT&CK")
        f.hosts = _kv_extract(body, r"Affected hosts?")
        f.location = _kv_extract(body, "Location")
        f.description = _section_extract(body, "Description")
        f.discovery = _section_extract(body, "Discovery")
        f.evidence = _section_extract(body, "Evidence")
        f.impact = _section_extract(body, r"(?:Business )?Impact")
        f.solution = _section_extract(body, "Solution")
        f.remediation = _section_extract(body, r"Remediation") or f.solution
        f.references = _section_extract(body, "References")
        findings.append(f)
    return findings


def _kv_extract(body: str, key: str) -> str:
    m = re.search(rf"^\*\*{key}:\*\*\s+(.+?)$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _section_extract(body: str, name: str) -> str:
    pattern = rf"^####\s+{name}\s*$"
    m = re.search(pattern, body, re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^####\s+", body[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(body)
    return body[start:end].strip()


def extract_h2_section(md: str, name: str) -> str:
    """Return the body of a top-level '## <name>' section from a markdown doc, else ''.
    `name` is treated as a regex (so callers can pass alternations)."""
    m = re.search(rf"^##\s+{name}\s*$", md, re.MULTILINE | re.IGNORECASE)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^##\s+", md[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(md)
    return md[start:end].strip()


def bucket_remediation(findings: list["Finding"]) -> "OrderedDict[str, list[str]]":
    """Aggregate each finding's Remediation items into P0/P1/P2 by their leading
    Immediate / Short-term / Long-term label. Falls back to keyword heuristics."""
    buckets: "OrderedDict[str, list[str]]" = OrderedDict([("P0", []), ("P1", []), ("P2", [])])
    for f in findings:
        if not f.remediation:
            continue
        # split into list items (numbered or bulleted)
        items = re.split(r"^\s*(?:\d+\.|[-*])\s+", f.remediation, flags=re.MULTILINE)
        for raw in items:
            raw = " ".join(raw.split()).strip()
            if not raw:
                continue
            low = raw.lower()
            if low.startswith("**immediate") or "immediate" in low[:24]:
                key = "P0"
            elif low.startswith("**short") or "short-term" in low[:24] or "short term" in low[:24]:
                key = "P1"
            elif low.startswith("**long") or "long-term" in low[:24] or "long term" in low[:24]:
                key = "P2"
            else:
                key = "P1"
            txt = re.sub(r"^\*\*(?:immediate|short[- ]term|long[- ]term)\:?\*\*\s*", "", raw, flags=re.IGNORECASE)
            buckets[key].append(f"<b>{htmlescape(f.fid)}</b> · {md_to_html_inline(txt)}")
    return buckets


def parse_timeline(timeline_md: str) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for line in timeline_md.splitlines():
        # accept an optional leading bullet ("- " / "* ") and en- or em-dash separator
        m = re.match(r"^[-*]?\s*\*\*(.+?)\*\*\s+[—–-]\s+(.+)$", line.strip())
        if m:
            events.append(TimelineEvent(when=m.group(1), text=m.group(2)))
    return events


def parse_hosts(hosts_csv: str) -> dict[str, HostRow]:
    rows: dict[str, HostRow] = OrderedDict()
    reader = csv.DictReader(hosts_csv.splitlines())
    for r in reader:
        h = (r.get("host") or "").strip()
        if not h:
            continue
        if h not in rows:
            rows[h] = HostRow(host=h, ip=(r.get("ip") or "").strip())
        fid = (r.get("finding_id") or "").strip()
        if fid and fid not in rows[h].findings:
            rows[h].findings.append(fid)
    return rows


# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------
def severity_counts(findings: Iterable[Finding]) -> "OrderedDict[str, int]":
    counts = OrderedDict([("Critical", 0), ("High", 0), ("Medium", 0), ("Low", 0), ("Info", 0)])
    for f in findings:
        r = f.rating.lower()
        if "critical" in r:
            counts["Critical"] += 1
        elif "high" in r:
            counts["High"] += 1
        elif "medium" in r:
            counts["Medium"] += 1
        elif "low" in r:
            counts["Low"] += 1
        elif "info" in r:
            counts["Info"] += 1
    return counts


def role_for_host(host: str, ip: str) -> str:
    """Infer host role from the hostname (best-effort, override as needed)."""
    h = host.lower()
    if "dc" in h or h in ("babaorum", "village"):
        return "dc"
    if "ws" in h or "workstation" in h:
        return "vict"
    if "svr" in h or "server" in h or h in ("metronum", "referendum"):
        return "piv"
    if h in ("iis",):
        return "entry"
    if "aws" in h or "cloud" in h:
        return "cloud"
    return "piv"


def verdict_for_findings(fids: list[str], findings_by_id: dict[str, Finding]) -> str:
    crit = sum(1 for f in fids if findings_by_id.get(f, Finding("", "")).rating.lower().startswith("critical"))
    high = sum(1 for f in fids if findings_by_id.get(f, Finding("", "")).rating.lower().startswith("high"))
    if crit:
        return "Pwn3d — Critical findings present"
    if high:
        return "Compromised — High-severity findings"
    return "Accessible — informational/medium issues"


def htmlescape(s: str) -> str:
    return html.escape(s, quote=True)


def md_to_html_inline(text: str) -> str:
    """Convert a small subset of markdown inline syntax into HTML."""
    text = htmlescape(text)
    # Code spans `x`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold **x**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic *x*
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
    # Links [text](url)
    text = re.sub(r"\[(.+?)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


_PROMPT_RE = re.compile(r"^(\s*)([\$#>])\s+(.*)$")
_SHELL_LANGS = {"bash", "sh", "shell", "zsh", "powershell", "pwsh", "cmd", "ps1", "console"}
# A line that looks like tool output rather than a command: starts with a
# protocol/status banner or contains tool markers. nxc/impacket/certipy/etc.
_OUTPUT_LINE_RE = re.compile(
    r"^(SMB|LDAP|LDAPS|WINRM|FTP|RDP|MSSQL|SSH|WMI|NFS|VNC|RPC|HTTP|HTTPS|"
    r"SPIDER_PLUS|LAPS|LSASSY|GPP_PASS|GPP_AUTO|COERCE_PLUS|LSASSY|"
    r"\s*\[[+\-*!?]\]|\s*INFO:|\s*WARNING:|\s*ERROR:|"
    r"\s+\->|\s+→|\s*\|"
    r")",
    re.IGNORECASE,
)


def _looks_like_command(line: str, lang: str) -> bool:
    """When lang is a shell, anything that doesn't look like banner/output is
    a command. Otherwise (lang empty or 'text') don't auto-add prompts."""
    if lang.lower() not in _SHELL_LANGS:
        return False
    stripped = line.lstrip()
    if not stripped:
        return False
    if _OUTPUT_LINE_RE.match(line):
        return False
    if stripped.startswith(("#", "//")):
        return False
    # Banner lines from `nmap -sn`, `ip addr`, etc. usually contain colons in
    # specific patterns; if a line has " | " or starts with column headers,
    # treat as output too.
    if re.match(r"^\s*\w+\s+:\s+", line) and "=" not in line:
        return False
    # Lines that are tabular output from nxc/impacket usually have multiple
    # consecutive spaces between fields — heuristic: 3+ spaces = output.
    if re.search(r"\S {3,}\S", line):
        return False
    return True


def render_term_block(code: str, lang: str = "") -> str:
    """Render a fenced code block as a .term panel with prompt/output coloring.

    Heuristics per line:
        '$ x' / '> x'           → explicit prompt + cmd
        line containing 'Pwn3d' → hit (amber)
        line containing '[+]'   → ok (green)
        line containing '[-]'   → bad (red)
        line containing '[*]'/'[!]' → meta (cyan)
        # comment (shell)       → dim italic
        if lang is bash/sh/ps:
            line not matching any output marker → implicit prompt + cmd
        otherwise: out (muted)
    """
    rendered: list[str] = []
    lang_lower = lang.lower()
    for raw in code.splitlines():
        if not raw.strip():
            rendered.append("")
            continue
        m = _PROMPT_RE.match(raw)
        if m and m.group(2) in ("$", ">"):
            indent = htmlescape(m.group(1))
            rendered.append(
                f'{indent}<span class="prompt">{htmlescape(m.group(2))}</span> '
                f'<span class="cmd">{htmlescape(m.group(3))}</span>'
            )
            continue
        if "Pwn3d" in raw:
            rendered.append(f'<span class="hit">{htmlescape(raw)}</span>')
            continue
        if "[+]" in raw:
            rendered.append(f'<span class="ok">{htmlescape(raw)}</span>')
            continue
        if "[-]" in raw:
            rendered.append(f'<span class="bad">{htmlescape(raw)}</span>')
            continue
        if "[*]" in raw or "[!]" in raw:
            rendered.append(f'<span class="meta">{htmlescape(raw)}</span>')
            continue
        if raw.lstrip().startswith("#") and not raw.lstrip().startswith("##"):
            rendered.append(f'<span class="comment">{htmlescape(raw)}</span>')
            continue
        if _looks_like_command(raw, lang_lower):
            # Auto-prepend a green $ prompt so bare bash commands look like
            # real terminal entries.
            rendered.append(
                f'<span class="prompt">$</span> '
                f'<span class="cmd">{htmlescape(raw)}</span>'
            )
            continue
        rendered.append(f'<span class="out">{htmlescape(raw)}</span>')
    title_lang = lang_lower if lang_lower else "output"
    body = "\n".join(rendered)
    return (
        '<div class="term">\n'
        f'  <div class="term-head"><span class="dots"><b></b><b></b><b></b></span>'
        f'<span class="title">operator@kali // {htmlescape(title_lang)}</span></div>\n'
        f'<div class="term-body">{body}</div>\n'
        '</div>'
    )


def md_to_html_block(text: str) -> str:
    """Convert simple markdown paragraphs + lists + fenced code into HTML.

    Fenced ``` blocks become .term panels (terminal style). Inline prose
    becomes <p>; bullet/numbered lines become <ul><li>; everything else
    is concatenated paragraph text.
    """
    if not text:
        return ""

    # Split into prose chunks and fenced code blocks.
    fenced_re = re.compile(r"^```(.*)$", re.MULTILINE)
    parts: list[str] = []
    pos = 0
    while pos < len(text):
        m_open = fenced_re.search(text, pos)
        if not m_open:
            # No more fences — render the rest as prose.
            parts.append(_render_prose(text[pos:]))
            break
        # Render prose before this fence.
        if m_open.start() > pos:
            parts.append(_render_prose(text[pos:m_open.start()]))
        lang = m_open.group(1).strip()
        body_start = m_open.end() + 1  # skip newline after ```lang
        m_close = fenced_re.search(text, body_start)
        if not m_close:
            # Unclosed fence — treat the remainder as code.
            parts.append(render_term_block(text[body_start:], lang))
            break
        code = text[body_start:m_close.start()].rstrip("\n")
        parts.append(render_term_block(code, lang))
        pos = m_close.end() + 1
    return "\n".join(p for p in parts if p)


def _render_prose(text: str) -> str:
    """Render the non-code portion of a markdown section."""
    if not text or not text.strip():
        return ""
    out: list[str] = []
    buf: list[str] = []
    list_buf: list[str] = []
    in_list = False
    for line in text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            if buf:
                out.append("<p>" + md_to_html_inline(" ".join(buf).strip()) + "</p>")
                buf = []
            in_list = True
            item = re.sub(r"^\s*[-*]\s+", "", line)
            list_buf.append("<li>" + md_to_html_inline(item) + "</li>")
        elif re.match(r"^\s*\d+\.\s+", line):
            if buf:
                out.append("<p>" + md_to_html_inline(" ".join(buf).strip()) + "</p>")
                buf = []
            in_list = True
            item = re.sub(r"^\s*\d+\.\s+", "", line)
            list_buf.append("<li>" + md_to_html_inline(item) + "</li>")
        elif not line.strip():
            if buf:
                out.append("<p>" + md_to_html_inline(" ".join(buf).strip()) + "</p>")
                buf = []
            if in_list:
                out.append("<ul>" + "".join(list_buf) + "</ul>")
                list_buf = []
                in_list = False
        else:
            if in_list and list_buf:
                list_buf[-1] = list_buf[-1][:-5] + " " + md_to_html_inline(line.strip()) + "</li>"
            else:
                buf.append(line.strip())
    if buf:
        out.append("<p>" + md_to_html_inline(" ".join(buf).strip()) + "</p>")
    if in_list and list_buf:
        out.append("<ul>" + "".join(list_buf) + "</ul>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML emitters
# ---------------------------------------------------------------------------
def emit_hero(meta: dict, findings: list[Finding], hosts: dict[str, HostRow]) -> str:
    client = meta.get("client", "ENGAGEMENT")
    case_id = meta.get("client_slug", "engagement").upper()
    window = f"{meta.get('start','')} to {meta.get('end','')}"
    model = meta.get("model", "")
    assessor = meta.get("assessor", "")
    auth = meta.get("authorization", "")
    scope = meta.get("scope_in", "")
    version = meta.get("version", "")
    status = meta.get("status", "in-progress")
    counts = severity_counts(findings)
    crit_findings = sum(1 for f in findings if f.rating.lower().startswith("critical"))
    n_hosts = len(hosts)
    n_pwn = sum(1 for h in hosts.values() if any(
        findings_by_id.get(fid, Finding("","")).rating.lower().startswith("critical") for fid in h.findings
    ))
    # Find Time-to-Foothold / Time-to-DA from timeline if possible
    # We populate findings_by_id lazily as a side effect — define here:
    classification = "TLP-AMBER"
    return f"""
<section class="case-hero" id="hero">
  <div class="masthead">
    <div class="left">
      <span class="bar"></span>
      <strong>OPERATOR CASEBOOK</strong>
      <span>CLASSIFICATION: {classification}</span>
    </div>
    <div class="right">
      <span>WINDOW {htmlescape(window)}</span>
      <span>ASSESSOR {htmlescape(assessor)}</span>
      <span>MODEL {htmlescape(model)}</span>
    </div>
  </div>

  <div class="body">
    <div>
      <div class="section-tag">Engagement File // {htmlescape(meta.get('start',''))}</div>
      <h1>
        <span class="l1">{htmlescape(client)}</span>
        <span class="l2">PENETRATION TEST</span>
        <span class="l3">// {htmlescape(case_id)}</span>
      </h1>
      <p class="subhead">
        Security assessment against <b>{htmlescape(client)}</b> · scope
        <code>{htmlescape(scope)}</code> · testing model <b>{htmlescape(model)}</b> ·
        <b>{counts['Critical']}</b> Critical / <b>{counts['High']}</b> High /
        <b>{counts['Medium']}</b> Medium / <b>{counts['Low']}</b> Low /
        <b>{counts['Info']}</b> Informational findings · authorized under
        <em>{htmlescape(auth)}</em>. This document walks every chain, every TTP,
        every verbatim command.
      </p>
    </div>
    <div class="dossier">
      <div class="row"><div class="k">Engagement ID</div><div class="v">{htmlescape(case_id)} / {htmlescape(meta.get('start',''))}</div></div>
      <div class="row"><div class="k">Client</div><div class="v">{htmlescape(client)}</div></div>
      <div class="row"><div class="k">Window</div><div class="v">{htmlescape(window)}</div></div>
      <div class="row"><div class="k">Testing Model</div><div class="v amber">{htmlescape(model)}</div></div>
      <div class="row"><div class="k">Operator</div><div class="v">{htmlescape(assessor)}</div></div>
      <div class="row"><div class="k">Authorization</div><div class="v">{htmlescape(auth)}</div></div>
      <div class="row"><div class="k">Scope (in)</div><div class="v"><code>{htmlescape(scope)}</code></div></div>
      <div class="row"><div class="k">Scope (out)</div><div class="v">{htmlescape(meta.get('scope_out',''))}</div></div>
      <div class="row"><div class="k">Hosts Compromised</div><div class="v red">{n_pwn} / {n_hosts}</div></div>
      <div class="row"><div class="k">Findings (Critical)</div><div class="v red">{crit_findings}</div></div>
      <div class="row"><div class="k">Final Status</div><div class="v {'green' if status=='complete' else 'amber'}">{htmlescape(status.upper())}</div></div>
      <div class="row"><div class="k">Version</div><div class="v">{htmlescape(version)}</div></div>
      <div class="stamp s1">CONFIDENTIAL</div>
      <div class="stamp s2">FOR OPERATOR EYES</div>
    </div>
  </div>

  <div class="scoreboard">
    <div class="score-cell"><div class="k">Critical</div><div class="v r">{counts['Critical']}</div><div class="d">findings</div></div>
    <div class="score-cell"><div class="k">High</div><div class="v a">{counts['High']}</div><div class="d">findings</div></div>
    <div class="score-cell"><div class="k">Medium</div><div class="v">{counts['Medium']}</div><div class="d">findings</div></div>
    <div class="score-cell"><div class="k">Hosts Pwn3d</div><div class="v g">{n_pwn} / {n_hosts}</div><div class="d">{n_hosts} in scope</div></div>
    <div class="score-cell"><div class="k">Total Findings</div><div class="v">{len(findings)}</div><div class="d">cleared</div></div>
    <div class="score-cell"><div class="k">Version</div><div class="v g">{htmlescape(version or '0.x')}</div><div class="d">{htmlescape(status)}</div></div>
  </div>
</section>
"""


def _worst_finding(findings: list[Finding]) -> Finding | None:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "informational": 4}
    ranked = sorted(findings, key=lambda f: order.get(f.rating.lower().split()[0] if f.rating else "info", 5))
    return ranked[0] if ranked else None


def _dwell(timeline: list[TimelineEvent]) -> str:
    """Human-ish span between first and last timeline event (best-effort)."""
    if len(timeline) < 2:
        return "single session"
    a, b = timeline[0].when, timeline[-1].when
    ma = re.search(r"(\d{1,2}):(\d{2})", a)
    mb = re.search(r"(\d{1,2}):(\d{2})", b)
    same_day = a[:10] == b[:10]
    if ma and mb and same_day:
        d = (int(mb.group(1)) * 60 + int(mb.group(2))) - (int(ma.group(1)) * 60 + int(ma.group(2)))
        if 0 <= d < 600:
            return f"~{d} min" if d < 90 else f"~{d // 60}h {d % 60}m"
    return f"{a} → {b}"


def emit_exec(meta: dict, findings: list[Finding], timeline: list[TimelineEvent]) -> str:
    counts = severity_counts(findings)
    sev = "CRITICAL" if counts['Critical'] else ("HIGH" if counts['High'] else ("MEDIUM" if counts['Medium'] else "LOW"))
    sev_color = "red" if counts['Critical'] else ("amber" if counts['High'] else "")
    worst = _worst_finding(findings)
    worst_txt = htmlescape(worst.title) if worst else "no critical issues"
    # hosts pwn3d derived from each high/critical finding's affected-host field
    pwn_hosts = {f.hosts.split("(")[0].strip() for f in findings if f.rating.lower().startswith(("critical", "high")) and f.hosts}
    pwn_hosts.discard("")
    root_flag = meta.get("root_flag", "")
    recover = "Root/admin obtained" if root_flag else ("Privileged access" if counts['Critical'] else "Limited")
    # Build root causes table from each finding's CWE
    rows = []
    for i, f in enumerate(findings, 1):
        if f.rating.lower().startswith(("critical", "high")):
            rows.append(f"""<tr><td class="a">{i}</td><td>{md_to_html_inline(f.title)}</td><td class="c">{md_to_html_inline(f.mitre)}</td><td class="m">{md_to_html_inline(f.cwe)}</td></tr>""")
    rows_html = "\n".join(rows[:12])  # cap
    # Mitigation roadmap synthesized from each finding's Remediation (Immediate/Short/Long -> P0/P1/P2)
    buckets = bucket_remediation(findings)
    def _rm_list(items: list[str]) -> str:
        if not items:
            return "<li>No items at this horizon — see detailed findings.</li>"
        return "\n".join(f"<li>{it}</li>" for it in items[:8])
    residual = (
        f"<b>Residual risk.</b> The chain ended in <b>{htmlescape(recover.lower())}</b> on "
        f"<b>{htmlescape(', '.join(sorted(pwn_hosts)) or meta.get('client',''))}</b>. Until every "
        "credential, key, and secret exposed along the documented path is rotated, treat the affected "
        "systems as compromised. Re-test after remediation to confirm the chain is broken."
    )
    return f"""
<section class="reveal" id="sec-exec" style="background: linear-gradient(180deg, rgba(255,59,59,.04), transparent 50%);">
  <div class="section-tag" style="color: var(--red); border-color: var(--red-d); background: rgba(255,59,59,.04);">// 01 · executive briefing</div>
  <h2>What <em>actually</em> happened.</h2>
  <p class="lede">
    Plain-language summary for executive decisioning. Severity rating aligned to CVSSv4 and operator
    judgment. The engagement against <b>{htmlescape(meta.get('client',''))}</b> identified
    <b>{counts['Critical']}</b> Critical, <b>{counts['High']}</b> High, <b>{counts['Medium']}</b> Medium,
    <b>{counts['Low']}</b> Low, and <b>{counts['Info']}</b> Informational findings.
  </p>

  <div class="sev-banner">
    <div class="sev-lvl">
      <div class="lab">Severity</div>
      <div class="val">{sev}</div>
      <div class="sub">Highest-rated issue: {worst_txt}</div>
    </div>
    <div class="sev-grid">
      <div class="sg"><div class="k">Findings (Critical)</div><div class="v {sev_color}">{counts['Critical']}</div><div class="d">of {len(findings)} total</div></div>
      <div class="sg"><div class="k">Findings (High)</div><div class="v amber">{counts['High']}</div><div class="d">substantial uplift</div></div>
      <div class="sg"><div class="k">Outcome</div><div class="v red">{htmlescape(recover)}</div><div class="d">{'flag captured' if root_flag else 'see findings'}</div></div>
      <div class="sg"><div class="k">Hosts compromised</div><div class="v amber">{len(pwn_hosts)}</div><div class="d">{htmlescape(', '.join(sorted(pwn_hosts))[:48]) or 'in-scope estate'}</div></div>
      <div class="sg"><div class="k">Dwell / window</div><div class="v">{htmlescape(_dwell(timeline))}</div><div class="d">{len(timeline)} logged actions</div></div>
      <div class="sg"><div class="k">Testing model</div><div class="v amber">{htmlescape(meta.get('model','—'))}</div><div class="d">{htmlescape(meta.get('status','') or 'engagement')}</div></div>
    </div>
  </div>

  <h3>Root Causes · Findings by Underlying Control Failure</h3>
  <table class="tbl" style="font-size: 13px;">
    <thead><tr><th>#</th><th>Finding</th><th>MITRE ATT&CK</th><th>CWE</th></tr></thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <h3 style="margin-top: 36px;">Mitigation Roadmap</h3>
  <div class="roadmap">
    <div class="rm-track">
      <div class="rm-phase p0"><span class="rm-when">P0 · ≤ 48h</span><span class="rm-title">Contain &amp; Rotate</span></div>
      <div class="rm-phase p1"><span class="rm-when">P1 · ≤ 2 weeks</span><span class="rm-title">Harden &amp; Detect</span></div>
      <div class="rm-phase p2"><span class="rm-when">P2 · ≤ 30 days</span><span class="rm-title">Architect Out</span></div>
    </div>
    <div class="rm-body">
      <div class="rm-col p0">
        <div class="rm-h">Immediate containment</div>
        <ul>
          {_rm_list(buckets['P0'])}
        </ul>
      </div>
      <div class="rm-col p1">
        <div class="rm-h">Hardening &amp; Detection</div>
        <ul>
          {_rm_list(buckets['P1'])}
        </ul>
      </div>
      <div class="rm-col p2">
        <div class="rm-h">Architectural</div>
        <ul>
          {_rm_list(buckets['P2'])}
        </ul>
      </div>
    </div>
  </div>

  <div class="residual-note">
    {residual}
  </div>
</section>
"""


def emit_story(meta: dict, findings: list[Finding], timeline: list[TimelineEvent], report_md: str = "") -> str:
    counts = severity_counts(findings)
    n_events = len(timeline)
    n_crit = counts["Critical"]
    pwn_hosts = {f.hosts.split("(")[0].strip() for f in findings
                 if f.rating.lower().startswith(("critical", "high")) and f.hosts}
    pwn_hosts.discard("")
    # Prefer operator-authored narrative from report.md (verbatim), else stitch from findings.
    narrative = (extract_h2_section(report_md, r"Engagement Narrative")
                 or extract_h2_section(report_md, r"Executive Summary"))
    headline = meta.get("headline", "") or meta.get("story_title", "")
    if narrative:
        prose = _render_prose(narrative)
        if not headline:
            headline = "How the chain <em>actually</em> ran."
    else:
        paras = [
            f"<p>The <b>{htmlescape(meta.get('client','engagement'))}</b> engagement logged "
            f"<b>{n_events} operator actions</b> producing <b>{n_crit} Critical</b> and "
            f"<b>{counts['High']} High</b> findings. The chain ran end-to-end as follows.</p>"
        ]
        for f in findings:
            if not f.rating.lower().startswith(("critical", "high")):
                continue
            short = (f.description or "").split("\n\n")[0][:600]
            paras.append(f"<p><b>{htmlescape(f.fid)} — {md_to_html_inline(f.title)}.</b> {md_to_html_inline(short)}</p>")
        if meta.get("root_flag") or meta.get("user_flag"):
            paras.append(f"<p class=\"end\">Final state: {htmlescape('root/admin obtained' if meta.get('root_flag') else 'foothold obtained')} on "
                         f"<b>{htmlescape(', '.join(sorted(pwn_hosts)) or meta.get('client',''))}</b>.</p>")
        prose = "\n".join(paras)
        if not headline:
            headline = "How the chain <em>actually</em> ran."

    stats = [
        (str(n_crit), "Critical findings", ""),
        (str(counts['High']), "High findings", ""),
        (str(n_events), "logged actions", ""),
        (str(len(pwn_hosts)), "hosts compromised", "red" if pwn_hosts else ""),
        (htmlescape(_dwell(timeline)), "window", ""),
        ("✓" if meta.get("root_flag") else ("✓" if meta.get("user_flag") else "—"),
         "objective" + (" (root)" if meta.get("root_flag") else (" (user)" if meta.get("user_flag") else "")),
         "red" if meta.get("root_flag") else ""),
    ]
    stat_html = "\n".join(
        f'    <div class="ss {cls}"><div class="n">{val}</div><div class="l">{lab}</div></div>'
        for val, lab, cls in stats
    )
    return f"""
<section class="reveal" id="sec-story" style="background: linear-gradient(180deg, rgba(0,255,156,.025), transparent 40%);">
  <div class="section-tag">// 02 · the story</div>
  <h2>{headline}</h2>

  <div class="story-stats">
{stat_html}
  </div>

  <div class="story-prose">
    {prose}
  </div>
</section>
"""


def emit_master_timeline(timeline: list[TimelineEvent]) -> str:
    """Phase the timeline events by inferring offensive-phase from the text."""
    phases: OrderedDict[str, list[TimelineEvent]] = OrderedDict([
        ("Phase 0 · Unauthenticated recon", []),
        ("Phase 1 · Initial foothold", []),
        ("Phase 2 · Authenticated enumeration", []),
        ("Phase 3 · Privilege escalation", []),
        ("Phase 4 · Lateral movement", []),
        ("Phase 5 · Domain dominance", []),
    ])
    for ev in timeline:
        t = ev.text.lower()
        if any(k in t for k in ["ping sweep", "null", "anonymous", "guest", "kerbrute", "rid-brute", "smb-pol", "sweep", "ldap-pol"]):
            phases["Phase 0 · Unauthenticated recon"].append(ev)
        elif any(k in t for k in ["foothold", "credential chain", "infos.txt", "ftp", "spider"]):
            phases["Phase 1 · Initial foothold"].append(ev)
        elif any(k in t for k in ["bloodhound", "kerberoast", "as-rep", "user enum"]):
            phases["Phase 2 · Authenticated enumeration"].append(ev)
        elif any(k in t for k in ["local admin", "pwn3d", "localix", "laps", "sam", "lsa", "dpapi", "shadow cred"]):
            phases["Phase 3 · Privilege escalation"].append(ev)
        elif any(k in t for k in ["referendum", "metronum", "psexec", "wmiexec", "winrm", "pivot", "secretsdump"]):
            phases["Phase 4 · Lateral movement"].append(ev)
        elif any(k in t for k in ["dcsync", "ntds", "krbtgt", "domain admin", "forest"]):
            phases["Phase 5 · Domain dominance"].append(ev)
        else:
            phases["Phase 2 · Authenticated enumeration"].append(ev)
    parts = []
    for name, evs in phases.items():
        if not evs:
            continue
        rows = "\n".join(
            f"<tr><td>{htmlescape(e.when)}</td><td>{md_to_html_inline(e.text)}</td></tr>"
            for e in evs
        )
        parts.append(f"""
  <h3>{htmlescape(name)}</h3>
  <table class="tbl" style="font-size:.87em">
    <thead><tr><th>UTC</th><th>Event</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>""")
    return f"""
<section class="reveal" id="sec-master-timeline" style="background: linear-gradient(180deg, rgba(100,200,255,.05), transparent 80%); border-top:2px solid rgba(100,200,255,.35); border-bottom:2px solid rgba(100,200,255,.35);">
  <div class="section-tag" style="color:var(--text)">// 03 · master timeline · phased</div>
  <h2>The full kill chain, minute by minute.</h2>
  <p class="lede">Six offensive phases — recon, foothold, authenticated enum, privilege escalation, lateral
  movement, domain dominance. Each row corresponds to a verifiable operator action logged in <code>timeline.md</code>.</p>
  {''.join(parts)}
</section>
"""


def _phase_class_for_finding(f: "Finding") -> str:
    """Map a finding to a graph node class by phase keywords in its title."""
    t = (f.title + " " + f.cwe + " " + f.mitre).lower()
    if any(k in t for k in ["dcsync", "ntds", "krbtgt", "domain admin", "root", "privilege escalation", "file write", "sudo"]):
        return "da"
    if any(k in t for k in ["credential", "password", "secret", "hash", "token", "reuse"]):
        return "cred"
    if any(k in t for k in ["rce", "code execution", "injection", "upload", "deserial", "exploit"]):
        return "pwn"
    if any(k in t for k in ["disclosure", "enumeration", "recon", "exposure", "ssrf"]):
        return "recon"
    return "foothold"


def emit_graph(graph_mmd: str | None, findings: list[Finding] | None = None, meta: dict | None = None) -> str:
    """Render the operator-authored attack graph (attack_graph.mmd) if present; otherwise
    synthesize a linear mermaid chain from the ordered findings for THIS engagement."""
    meta = meta or {}
    if not graph_mmd:
        nodes = []
        edges = []
        prev = "START"
        nodes.append('  START([Unauthenticated]):::recon')
        for f in (findings or []):
            nid = f.fid.upper()
            label = f"{f.fid}: {f.title}".replace('"', "'")[:54]
            cls = _phase_class_for_finding(f)
            nodes.append(f'  {nid}["{label}"]:::{cls}')
            edges.append(f"  {prev} --> {nid}")
            prev = nid
        outcome = "ROOT / Domain Admin" if meta.get("root_flag") else ("Foothold" if meta.get("user_flag") else "Objective")
        ocls = "da" if meta.get("root_flag") else "pwn"
        nodes.append(f'  WIN(({outcome})):::{ocls}')
        edges.append(f"  {prev} --> WIN")
        graph_mmd = (
            "flowchart LR\n" + "\n".join(nodes) + "\n" + "\n".join(edges) + "\n"
            "  classDef recon fill:#0b2030,stroke:#58a6ff,color:#e6edf3\n"
            "  classDef foothold fill:#251b00,stroke:#ffb800,color:#e6edf3\n"
            "  classDef cred fill:#1b1530,stroke:#c084fc,color:#e6edf3\n"
            "  classDef pwn fill:#3a0d0d,stroke:#ff3b3b,color:#e6edf3\n"
            "  classDef da fill:#0d2b1f,stroke:#00ff9c,color:#e6edf3\n"
        )
    graph_escaped = graph_mmd  # mermaid blocks don't need HTML-escaping inside .mermaid
    return f"""
<section class="reveal" id="sec-graph">
  <div class="section-tag">// 04 · attack graph · the kill chain</div>
  <h2>How the chain <em>actually</em> ran.</h2>
  <p class="lede">Each node is an attacker waypoint; each edge is a transition proven in the engagement.
  Authored from <code>attack_graph.mmd</code> if present, else synthesized from the ordered findings.</p>
  <div class="graph-wrap">
    <div class="mermaid">
{graph_escaped}
    </div>
  </div>
  <div class="graph-legend">
    <div class="li"><span class="sw" style="background:#58a6ff"></span>Recon / disclosure</div>
    <div class="li"><span class="sw" style="background:#ffb800"></span>Foothold</div>
    <div class="li"><span class="sw" style="background:#c084fc"></span>Credential</div>
    <div class="li"><span class="sw" style="background:#ff3b3b"></span>Code exec / Pwn3d</div>
    <div class="li"><span class="sw" style="background:#00ff9c"></span>Root / Domain Admin</div>
  </div>
</section>
"""


def _phase_of(text: str) -> int:
    """Infer offensive phase index 0-5 from free-text event (mirrors emit_master_timeline)."""
    t = text.lower()
    if any(k in t for k in ["dcsync", "ntds", "krbtgt", "domain admin", "forest", "golden", "silver ticket"]):
        return 5
    if any(k in t for k in ["psexec", "wmiexec", "winrm", "smbexec", "pivot", "secretsdump", "lateral", "relay"]):
        return 4
    if any(k in t for k in ["local admin", "pwn3d", "laps", "sam", "lsa", "dpapi", "shadow cred", "root", "sudo", "privesc", "escalat", "gmsa"]):
        return 3
    if any(k in t for k in ["bloodhound", "kerberoast", "as-rep", "user enum", "ldap", "enum"]):
        return 2
    if any(k in t for k in ["foothold", "credential chain", "ftp", "spider", "rce", "shell", "login", "exploit", "cve"]):
        return 1
    if any(k in t for k in ["ping sweep", "null", "anonymous", "guest", "kerbrute", "rid-brute", "sweep", "nmap", "recon", "scan"]):
        return 0
    return 2


_PHASE_SHORT = {0: "RECON", 1: "FOOTHOLD", 2: "ENUM", 3: "PRIVESC", 4: "LATERAL", 5: "DOMINANCE"}


def _wrap(s: str, width: int, maxlines: int) -> list[str]:
    """Greedy word-wrap to <=width chars, capped at maxlines (last line ellipsised if truncated)."""
    words = s.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= maxlines:
                break
    if cur and len(lines) < maxlines:
        lines.append(cur)
    joined = " ".join(lines)
    if len(joined) < len(s) and lines:
        lines[-1] = lines[-1][: max(0, width - 1)].rstrip() + "…"
    return lines[:maxlines]


def _mitre_label(m: str) -> str:
    """Turn a finding MITRE string ('T1552.001 — Unsecured Credentials: Credentials In Files')
    into a compact node chip: technique name + T-ID, e.g. 'Unsecured Credentials · T1552.001'."""
    if not m:
        return ""
    tid = re.search(r"T\d{4}(?:\.\d{3})?", m)
    parts = re.split(r"\s[—–-]\s", m, maxsplit=1)
    name = (parts[1] if len(parts) > 1 else parts[0]).split(":")[0].strip()
    name = re.sub(r"^T\d{4}(?:\.\d{3})?\s*", "", name)  # strip any leading id
    if len(name) > 20:
        name = name[:19].rstrip() + "…"
    return f"{name} · {tid.group(0)}" if (name and tid) else (name or (tid.group(0) if tid else ""))


def emit_replay(timeline: list[TimelineEvent], hosts: dict[str, "HostRow"],
                meta: dict | None = None, findings: list[Finding] | None = None) -> str:
    """Interactive kill-chain replay rendered as an animated SVG attack graph (pivot topology /
    forensic edges). Waypoint nodes are laid out in a serpentine flow; directional edges fire in
    UTC-timestamp order with a persistent glowing trail and the reached node pulses. Self-contained
    vanilla-JS sequencer + CSS, driven by timeline.md + hosts.csv."""
    if not timeline:
        return ""
    meta = meta or {}
    host_names = [h for h in hosts.keys() if h]

    def short_time(w: str) -> str:
        m = re.search(r"(\d{1,2}:\d{2})(?::\d{2})?", w)
        return m.group(1) if m else (w[-8:] if len(w) > 8 else w)

    fid_title = {f.fid: f.title for f in (findings or [])}
    fid_mitre = {f.fid: f.mitre for f in (findings or [])}
    # Build the node sequence: node 0 = OPERATOR, then one waypoint per timeline event.
    events = []
    for ev in timeline:
        p = _phase_of(ev.text)
        plain = re.sub(r"\*\*?|`|\[|\]", "", ev.text)
        fidm = re.search(r"\bF\d{1,2}\b", ev.text)
        fid = fidm.group(0) if fidm else None
        host = next((h for h in host_names if h.lower() in plain.lower()),
                    host_names[0] if host_names else "target")
        if fid:
            mlabel = _mitre_label(fid_mitre.get(fid, ""))
            head = f"{fid} · {mlabel}" if mlabel else f"{fid} · {host[:16]}"
            desc = fid_title.get(fid) or _PHASE_SHORT.get(p, "")
        else:
            head = _PHASE_SHORT.get(p, "STEP")
            desc = re.sub(r"^F\d+\s*[:\-]?\s*", "", plain)
        events.append({"t": ev.when, "x": md_to_html_inline(ev.text), "p": p,
                       "head": head, "lines": _wrap(desc, 30, 3), "tlabel": short_time(ev.when)})

    op_ip = (meta.get("attacker_ip", "") or "attacker").split("(")[0].strip()[:18]
    nodes = [{"head": "OPERATOR", "lines": [op_ip], "p": "op"}] + events  # N+1 nodes
    N = len(events)

    # Serpentine grid layout (wider/taller boxes to fit a wrapped finding title).
    cols = min(max(N + 1, 1), 4)
    NW, NH, COLW, ROWH, MX, MY = 270, 92, 326, 172, 34, 30
    pos = []
    for i in range(len(nodes)):
        row = i // cols
        inrow = i % cols
        col = inrow if row % 2 == 0 else (cols - 1 - inrow)
        x = MX + col * COLW
        y = MY + row * ROWH
        pos.append((x, y, x + NW / 2, y + NH / 2))
    rows = (len(nodes) + cols - 1) // cols
    W = MX * 2 + (cols - 1) * COLW + NW
    H = MY * 2 + (rows - 1) * ROWH + NH

    svg = []
    # edges first (drawn under nodes): edge k connects node k-1 -> node k, fires at step k
    for k in range(1, len(nodes)):
        _, _, x1, y1 = pos[k - 1]
        _, _, x2, y2 = pos[k]
        p = events[k - 1]["p"]
        svg.append(f'<line class="kc-edge p{p}" data-i="{k}" x1="{x1:.0f}" y1="{y1:.0f}" '
                   f'x2="{x2:.0f}" y2="{y2:.0f}" marker-end="url(#kcarrow)"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 6
        svg.append(f'<text class="kc-elabel" data-i="{k}" x="{mx:.0f}" y="{my:.0f}" '
                   f'text-anchor="middle">{htmlescape(events[k-1]["tlabel"])}</text>')
    # nodes
    for i, nd in enumerate(nodes):
        x, y, _, _ = pos[i]
        on = " on" if i == 0 else ""
        txt = f'<text class="kc-nt" x="{x+12:.0f}" y="{y+22:.0f}">{htmlescape(str(nd["head"]))}</text>'
        for j, ln in enumerate(nd["lines"]):
            txt += f'<text class="kc-ns" x="{x+12:.0f}" y="{y+40+j*14:.0f}">{htmlescape(str(ln))}</text>'
        svg.append(
            f'<g class="kc-node np{nd["p"]}{on}" data-i="{i}">'
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{NW}" height="{NH}" rx="6"/>{txt}</g>')
    svg_markup = "\n      ".join(svg)
    data_json = json.dumps(events, ensure_ascii=False)
    return f"""
<section class="reveal" id="sec-replay" style="background: linear-gradient(180deg, rgba(0,255,156,.03), transparent 60%);">
  <div class="section-tag">// 05 · attack graph · interactive · forensic edges</div>
  <h2>Watch the chain <em>fire</em>.</h2>
  <p class="lede">Pivot topology of the engagement. Press play and the edges activate in UTC-timestamp
  order — each waypoint pulses as it comes under operator control and a glowing trail persists behind
  the cursor. Click any node to inspect its event. Speed is a playback multiplier, not real time.</p>
  <div class="kc" data-events='{htmlescape(data_json)}'>
    <div class="kc-controls">
      <button class="kc-btn" data-act="reset" title="Reset">&#10227;</button>
      <button class="kc-btn" data-act="back" title="Step back">&#9198;</button>
      <button class="kc-btn play" data-act="play">&#9654; PLAY</button>
      <button class="kc-btn" data-act="fwd" title="Step forward">&#9197;</button>
      <span class="kc-speeds">
        <button class="kc-speed sel" data-speed="1">1&times;</button>
        <button class="kc-speed" data-speed="60">60&times;</button>
        <button class="kc-speed" data-speed="240">240&times;</button>
        <button class="kc-speed" data-speed="900">900&times;</button>
      </span>
      <span class="kc-counter"><b class="kc-cur">0</b>/{N} events</span>
    </div>
    <div class="kc-progress" title="Scrub"><div class="kc-progress-fill"></div></div>
    <div class="kc-graph">
      <svg class="kc-svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}" preserveAspectRatio="xMinYMin meet">
      <defs><marker id="kcarrow" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="context-stroke"/></marker></defs>
      {svg_markup}
      </svg>
    </div>
    <div class="kc-detail">Press &#9654; or click a node to inspect the step.</div>
  </div>
  <script>
  (function(){{
    var root = document.querySelector('#sec-replay .kc');
    var data = JSON.parse(root.getAttribute('data-events'));
    var edges = {{}}, elabels = {{}}, nodes = {{}};
    root.querySelectorAll('.kc-edge').forEach(function(e){{ edges[+e.getAttribute('data-i')] = e; }});
    root.querySelectorAll('.kc-elabel').forEach(function(e){{ elabels[+e.getAttribute('data-i')] = e; }});
    root.querySelectorAll('.kc-node').forEach(function(n){{ nodes[+n.getAttribute('data-i')] = n; }});
    var fill = root.querySelector('.kc-progress-fill');
    var curEl = root.querySelector('.kc-cur');
    var detail = root.querySelector('.kc-detail');
    var playBtn = root.querySelector('[data-act=play]');
    var idx = 0, timer = null, speed = 1, BASE = 1300;
    function paint(){{
      for(var k in edges){{ k=+k; edges[k].classList.toggle('fired', k<=idx); }}
      for(var k in elabels){{ k=+k; elabels[k].classList.toggle('fired', k<=idx); }}
      for(var i in nodes){{ i=+i; nodes[i].classList.toggle('on', i<=idx); nodes[i].classList.toggle('live', i===idx); }}
      fill.style.width = (data.length ? (idx/data.length*100) : 0) + '%';
      curEl.textContent = idx;
      if(idx>0){{ var e=data[idx-1]; detail.innerHTML = '<b>'+e.t+'</b> &middot; '+e.x; }}
      else {{ detail.textContent = 'Press ▶ or click a node to inspect the step.'; }}
    }}
    function step(){{ if(idx>=data.length){{ stop(); return; }} idx++; paint(); }}
    function play(){{ if(timer) return; if(idx>=data.length) idx=0; playBtn.innerHTML='&#10073;&#10073; PAUSE'; timer=setInterval(step, BASE/speed); }}
    function stop(){{ if(timer){{ clearInterval(timer); timer=null; }} playBtn.innerHTML='&#9654; PLAY'; }}
    root.querySelector('[data-act=play]').onclick=function(){{ timer?stop():play(); }};
    root.querySelector('[data-act=reset]').onclick=function(){{ stop(); idx=0; paint(); }};
    root.querySelector('[data-act=back]').onclick=function(){{ stop(); if(idx>0) idx--; paint(); }};
    root.querySelector('[data-act=fwd]').onclick=function(){{ stop(); step(); }};
    root.querySelectorAll('.kc-speed').forEach(function(b){{ b.onclick=function(){{
      root.querySelectorAll('.kc-speed').forEach(function(x){{x.classList.remove('sel');}}); b.classList.add('sel');
      speed=parseFloat(b.getAttribute('data-speed')); if(timer){{ stop(); play(); }}
    }};}});
    root.querySelector('.kc-progress').onclick=function(e){{ stop(); var rc=this.getBoundingClientRect(); idx=Math.round((e.clientX-rc.left)/rc.width*data.length); idx=Math.max(0,Math.min(data.length,idx)); paint(); }};
    for(var i in nodes){{ (function(n){{ n.addEventListener('click', function(){{ stop(); idx=+n.getAttribute('data-i'); paint(); }}); }})(nodes[i]); }}
    paint();
  }})();
  </script>
</section>
"""


def emit_acts_and_chapters(findings: list[Finding]) -> str:
    """Group findings into 5 acts by ordinal severity + position; emit a section per finding."""
    # Bucket findings into 5 acts roughly by F-number
    acts = {
        1: ("ACT I", "Unauthenticated Recon &amp; Foothold", "act1"),
        2: ("ACT II", "Credential Chain &amp; Local Admin", "act2"),
        3: ("ACT III", "Privilege Escalation &amp; Credential Stores", "act3"),
        4: ("ACT IV", "Lateral Movement &amp; Cross-Forest Pivot", "act4"),
        5: ("ACT V", "Domain Dominance", "act5"),
    }
    grouped: OrderedDict[int, list[Finding]] = OrderedDict((i, []) for i in range(1, 6))
    for f in findings:
        n = int(re.search(r"\d+", f.fid).group(0))
        if n <= 6:
            grouped[1].append(f)
        elif n <= 11:
            grouped[2].append(f)
        elif n <= 16:
            grouped[3].append(f)
        elif n <= 22:
            grouped[4].append(f)
        else:
            grouped[5].append(f)

    out = []
    for act_n, group in grouped.items():
        if not group:
            continue
        name, title, cls = acts[act_n]
        out.append(f"""
<section class="act-card reveal" id="sec-act{act_n}">
  <div class="num">{name} · {len(group)} finding{'s' if len(group)!=1 else ''}</div>
  <h2 class="title">{title}</h2>
  <div class="timecode">→ {len(group)} chapter{'s' if len(group)!=1 else ''} · {', '.join(f.fid for f in group)}</div>
  <p class="description">
    {md_to_html_inline(group[0].description.split('\n\n')[0][:480] if group[0].description else 'Engagement act ' + str(act_n) + ' findings.')}
  </p>
</section>
""")
        # Per-finding chapter
        for f in group:
            out.append(emit_chapter(f, cls))
    return "\n".join(out)


def emit_chapter(f: Finding, act_cls: str) -> str:
    rating_class = {
        "critical": "r", "high": "a", "medium": "m", "low": "m", "info": "m", "informational": "m"
    }.get(f.rating.lower().split()[0] if f.rating else "", "m")
    # Show first 800 chars of description, with simple markdown
    desc = md_to_html_block(f.description) if f.description else ""
    discovery = md_to_html_block(f.discovery) if f.discovery else ""
    impact = md_to_html_block(f.impact) if f.impact else ""
    return f"""
<section class="reveal" id="sec-{f.fid.lower()}">
  <div class="section-tag">// {htmlescape(f.fid)} · {md_to_html_inline(f.title)}</div>
  <table class="tbl" style="width:auto; min-width:60%;">
    <tr><th>Rating</th><td class="{rating_class}">{md_to_html_inline(f.rating)}</td></tr>
    <tr><th>CVSSv4</th><td>{md_to_html_inline(f.cvss_score)} <span class="m">{md_to_html_inline(f.cvss_vector)}</span></td></tr>
    <tr><th>CWE</th><td>{md_to_html_inline(f.cwe)}</td></tr>
    <tr><th>MITRE</th><td class="c">{md_to_html_inline(f.mitre)}</td></tr>
    <tr><th>Hosts</th><td>{md_to_html_inline(f.hosts)}</td></tr>
    <tr><th>Location</th><td>{md_to_html_inline(f.location)}</td></tr>
  </table>
  <h3>What we proved</h3>
  {desc}
  <h3>How we proved it</h3>
  {discovery}
  <h3>Impact</h3>
  {impact}
</section>
"""


def emit_host_grid(hosts: dict[str, HostRow], findings_by_id: dict[str, Finding]) -> str:
    cards = []
    for h in hosts.values():
        role = role_for_host(h.host, h.ip)
        verdict = verdict_for_findings(h.findings, findings_by_id)
        crit_count = sum(1 for fid in h.findings if findings_by_id.get(fid, Finding("","")).rating.lower().startswith("critical"))
        findings_str = ", ".join(h.findings)
        detail_html = (
            f"<h4>Findings · {len(h.findings)}</h4>"
            f"<ul>" + "".join(
                f"<li><b>{htmlescape(fid)}</b> — {md_to_html_inline(findings_by_id.get(fid, Finding('','')).title)} ({md_to_html_inline(findings_by_id.get(fid, Finding('','')).rating)})</li>"
                for fid in h.findings
            ) + "</ul>"
        )
        # Stash detail in data-host attribute for the drawer
        import json
        data_host = htmlescape(json.dumps({
            "name": h.host,
            "ip": h.ip,
            "role": role.upper(),
            "detail": detail_html,
        }))
        cards.append(f"""
    <div class="host {role} host-clickable" data-host='{data_host}'>
      <div class="name">{htmlescape(h.host)} <span class="ip">{htmlescape(h.ip)}</span></div>
      <div class="role">{role.upper()}</div>
      <div class="verdict">{verdict}<div class="findings">{len(h.findings)} findings · {crit_count} Critical</div><div class="findings">{findings_str}</div></div>
    </div>""")
    return f"""
<section class="reveal" id="sec-hosts">
  <div class="section-tag">// 05 · host grid · the estate</div>
  <h2>Every host. Every verdict.</h2>
  <p class="lede">Each card lists the per-host findings and the worst-case verdict.
  Click any card for the per-host drawer with the full finding list.</p>
  <div class="host-grid">{''.join(cards)}</div>
</section>
"""


def emit_ttp_matrix(findings: list[Finding]) -> str:
    # Extract every "MITRE ATT&CK:" line; parse T-IDs
    cells: OrderedDict[str, list[Finding]] = OrderedDict()
    for f in findings:
        if not f.mitre:
            continue
        # T-IDs match T\d+(.\d+)?
        for m in re.finditer(r"\bT\d{4}(?:\.\d{3})?\b", f.mitre):
            tid = m.group(0)
            cells.setdefault(tid, []).append(f)
    items = []
    for tid, fs in cells.items():
        # Try to extract the technique name from the first finding's MITRE field
        name_match = re.search(rf"{re.escape(tid)}\s*[—–-]\s*([^,;\n]+)", fs[0].mitre)
        name = (name_match.group(1).strip() if name_match else "")
        # Tactic guess from T-ID range (very loose)
        tactic = guess_tactic(tid)
        evidence = ", ".join(f.fid for f in fs)
        items.append(f"""
    <div class="ttp">
      <div class="tactic">{tactic}</div>
      <div class="tech">{htmlescape(name) or 'Technique'}</div>
      <div class="tech-id">{tid}</div>
      <div class="ev">Cited in <code>{evidence}</code></div>
    </div>""")
    return f"""
<section class="reveal" id="sec-ttp">
  <div class="section-tag">// 06 · MITRE ATT&amp;CK · techniques in this engagement</div>
  <h2>The <em>{len(cells)}</em> TTPs we ran.</h2>
  <p class="lede">Every distinct sub-technique referenced across the findings. Click any T-ID to look up
  the official ATT&amp;CK entry.</p>
  <div class="ttp-grid">{''.join(items)}</div>
</section>
"""


def guess_tactic(tid: str) -> str:
    # Crude T-ID → tactic mapping (selected ranges)
    n = int(re.match(r"T(\d{4})", tid).group(1)) if re.match(r"T(\d{4})", tid) else 0
    if n in (1078, 1110, 1212): return "Initial Access / Cred"
    if n in (1003,): return "Credential Access"
    if n in (1190,): return "Initial Access"
    if n in (1112,): return "Defense Evasion"
    if n in (1059, 1218, 1574): return "Execution / Persistence"
    if n in (1486, 1490): return "Impact"
    if n in (1557,): return "Adversary-in-the-Middle"
    if n in (1558,): return "Steal Authentication"
    if n in (1649,): return "Steal/Forge Certs"
    if n in (1552,): return "Unsecured Credentials"
    if n in (1083, 1087, 1201): return "Discovery"
    if n in (1021,): return "Lateral Movement"
    if n in (1078,): return "Valid Accounts"
    if n in (1134,): return "Token Manipulation"
    return "ATT&CK"


def emit_chains(findings: list[Finding], meta: dict, report_md: str = "") -> str:
    """Render attack chains. Prefer an operator-authored '## Attack Chains' section in report.md;
    otherwise synthesize a single primary chain from the ordered findings."""
    authored = extract_h2_section(report_md, r"Attack Chains")
    if authored:
        body = _render_prose(authored)
        cards = f'<div class="chain"><div class="n">Primary chain <span class="p">CLEARED</span></div><div class="s">{body}</div><div class="bar"><i style="width:100%"></i></div></div>'
        lede = "Operator-authored compromise path(s) for this engagement."
    else:
        steps = [f"{f.fid} {f.title}" for f in findings]
        outcome = "root/admin" if meta.get("root_flag") else ("foothold" if meta.get("user_flag") else "objective")
        chain_txt = " → ".join(htmlescape(s) for s in steps) or "see detailed findings"
        if steps:
            chain_txt += f" → <b>{htmlescape(outcome)}</b>"
        cleared = "CLEARED" if (meta.get("root_flag") or meta.get("user_flag")) else "PARTIAL"
        cards = (f'<div class="chain"><div class="n">Primary chain <span class="p">{cleared}</span></div>'
                 f'<div class="s">{chain_txt}</div><div class="bar"><i style="width:100%"></i></div></div>')
        lede = "The compromise path, synthesized from the ordered findings. Each step is a proven transition documented in the detailed findings."
    return f"""
<section class="reveal" id="sec-chains">
  <div class="section-tag">// 07 · attack chains · how compromise was reached</div>
  <h2>The path to compromise.</h2>
  <p class="lede">{lede}</p>
  <div class="chain-grid">
    {cards}
  </div>
</section>
"""


def emit_dead_ends(report_md: str = "") -> str:
    """Render dead ends ONLY from an operator-authored '## Dead Ends' section in report.md.
    Each '- **title** — why' (or '- title — why') list item becomes a reject card.
    If no such section exists, the section is omitted entirely (no stale placeholder)."""
    section = extract_h2_section(report_md, r"Dead Ends")
    if not section:
        return ""
    cards = []
    n = 0
    for line in section.splitlines():
        m = re.match(r"^\s*(?:\d+\.|[-*])\s+(.+)$", line)
        if not m:
            continue
        item = m.group(1).strip()
        # split "title — why" / "title - why" / "title: why"
        parts = re.split(r"\s+[—–-]\s+|:\s+", item, maxsplit=1)
        title = parts[0].strip()
        why = parts[1].strip() if len(parts) > 1 else ""
        n += 1
        cards.append(
            f'  <div class="reject"><span class="cid">DEAD END {n}</span> · '
            f'<span class="bad">{md_to_html_inline(title)}</span>'
            + (f'<div class="why">{md_to_html_inline(why)}</div>' if why else "")
            + "</div>"
        )
    if not cards:
        return ""
    return f"""
<section class="reveal" id="sec-dead-ends">
  <div class="section-tag">// 08 · dead ends · paths that didn't pan out</div>
  <h2>What we ruled out.</h2>
  <p class="lede">Operator methodology requires showing the ground we tested and ruled out — failed attempts
  are themselves signal (defense-in-depth working, neutralized misconfigurations, hardened endpoints).</p>
{chr(10).join(cards)}
</section>
"""


def emit_strengths(report_md: str = "") -> str:
    """Render defensive controls that worked, from report.md '## Summary of Strengths'
    (bullet list). Omitted entirely if the section is absent or empty."""
    section = extract_h2_section(report_md, r"Summary of Strengths|Strengths")
    if not section:
        return ""
    items = [re.sub(r"^\s*(?:\d+\.|[-*])\s+", "", ln).strip()
             for ln in section.splitlines() if re.match(r"^\s*(?:\d+\.|[-*])\s+", ln)]
    items = [i for i in items if i]
    if not items:
        return ""
    lis = "\n".join(f"    <li>{md_to_html_inline(i)}</li>" for i in items)
    return f"""
<section class="reveal" id="sec-strengths" style="background: linear-gradient(180deg, rgba(0,255,156,.03), transparent 50%);">
  <div class="section-tag">// 09 · strengths · what held</div>
  <h2>Controls that <em>worked</em>.</h2>
  <p class="lede">Defenses that blocked or slowed the operator. Recording these is as much a finding as the failures.</p>
  <ul class="strengths">
{lis}
  </ul>
</section>
"""


def emit_close(meta: dict, findings: list[Finding] | None = None) -> str:
    status = meta.get("status", "in-progress").lower()
    is_complete = status in ("complete", "final", "closed")
    end = meta.get("end") or meta.get("start", "")
    version = meta.get("version", "")
    client = meta.get("client", "")
    assessor = meta.get("assessor", "")
    counts = severity_counts(findings or [])
    n = len(findings or [])
    outcome = ("Full root/administrative compromise achieved." if meta.get("root_flag")
               else ("Interactive foothold established." if meta.get("user_flag")
                     else "Findings documented across the in-scope estate."))
    caption = (
        f"{n} finding{'s' if n != 1 else ''} — {counts['Critical']} Critical, {counts['High']} High. "
        f"{outcome} Every step is reproducible via the commands and evidence files in this casebook; "
        "rotate all exposed secrets and re-test to confirm the chain is broken."
    )
    label = "ENGAGEMENT CLOSED" if is_complete else "ENGAGEMENT IN PROGRESS"
    stamp_class = "" if is_complete else "draft"
    return f"""
<section class="close" id="sec-close">
  <div class="section-tag">// engagement file closed · {htmlescape(end)} utc</div>
  <h2 class="big">{htmlescape(client)} — <em>{'resolved' if is_complete else 'in progress'}</em>.</h2>
  <p class="caption">
    {htmlescape(caption)}
  </p>
  <div style="margin-top: 42px; padding-top: 28px; border-top: 1px solid var(--line-2); display: inline-flex; flex-direction: column; gap: 6px; align-items: center; font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: .22em; color: var(--muted); text-transform: uppercase;">
    <span>Signed &nbsp;<b style="color:var(--text); letter-spacing:.3em;">{htmlescape(assessor.upper())}</b></span>
    <span style="color: var(--dim); font-size: 10.5px;">TLP-AMBER · for operator eyes</span>
  </div>
  <div class="closed-stamp {stamp_class}" style="margin-top: 32px;">{label} · {htmlescape(end)} · v{htmlescape(version)}</div>
</section>
"""


SECTION_LABELS = {
    "hero": "Engagement File",
    "sec-exec": "Executive Briefing",
    "sec-story": "The Story",
    "sec-master-timeline": "Master Timeline",
    "sec-graph": "Attack Graph",
    "sec-replay": "Kill-Chain Replay",
    "sec-hosts": "Host Grid",
    "sec-ttp": "TTP Matrix",
    "sec-chains": "Attack Chains",
    "sec-dead-ends": "Dead Ends",
    "sec-strengths": "Strengths",
    "sec-close": "Closed",
}
_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}


def emit_chapter_nav(body_html: str) -> str:
    """Build the right-side drawer nav from the anchors that ACTUALLY rendered, in document
    order. Optional sections (replay, dead-ends, strengths) and variable act counts are reflected
    automatically; per-finding chapter anchors are skipped."""
    present = []
    seen = set()
    for sid in re.findall(r'id="(hero|sec-[a-z0-9-]+)"', body_html):
        if sid in seen:
            continue
        seen.add(sid)
        if sid in SECTION_LABELS:
            label = SECTION_LABELS[sid]
        else:
            m = re.match(r"sec-act(\d+)$", sid)
            if m:
                label = f"Act {_ROMAN.get(int(m.group(1)), m.group(1))}"
            else:
                continue  # per-finding chapter (sec-f01, …) — not a nav-level section
        present.append((sid, label))
    items = "\n".join(
        f'<a href="#{sid}" data-num="{i:02d}">{name}</a>'
        for i, (sid, name) in enumerate(present, 1)
    )
    return f"""
<nav class="chapter-nav">
  <button class="chapter-nav-toggle" aria-label="Open chapter navigation">
    <span>≡</span>
    <span class="chapter-nav-toggle-label">CHAPTERS</span>
  </button>
  <div class="chapter-nav-list">
    {items}
  </div>
</nav>
"""


def emit_host_drawer_skeleton() -> str:
    return """
<div class="drawer-overlay"></div>
<aside class="host-drawer">
  <div class="head">
    <div>
      <div class="name"></div>
      <div class="ip"></div>
      <div class="role"></div>
    </div>
    <button class="close-btn" aria-label="Close drawer">×</button>
  </div>
  <div class="body"></div>
</aside>
"""


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
# Global so emit_hero can reference for hosts pwn3d count
findings_by_id: dict[str, Finding] = {}


def render(engagement_dir: Path, out_path: Path) -> None:
    meta_p = engagement_dir / "engagement.yaml"
    report_p = engagement_dir / "report.md"
    timeline_p = engagement_dir / "timeline.md"
    hosts_p = engagement_dir / "hosts.csv"
    graph_p = engagement_dir / "attack_graph.mmd"

    for p in (meta_p, report_p, timeline_p, hosts_p):
        if not p.is_file():
            sys.stderr.write(f"error: missing required input {p}\n")
            sys.exit(2)

    meta = parse_yaml_lite(meta_p.read_text(encoding="utf-8"))
    report_md = report_p.read_text(encoding="utf-8")
    findings = parse_findings(report_md)
    timeline = parse_timeline(timeline_p.read_text(encoding="utf-8"))
    hosts = parse_hosts(hosts_p.read_text(encoding="utf-8"))
    graph_mmd = graph_p.read_text(encoding="utf-8") if graph_p.is_file() else None

    global findings_by_id
    findings_by_id = {f.fid: f for f in findings}

    # Build the body sections first, then derive the chapter-nav from the anchors that
    # actually rendered (so optional/empty sections never leave dead nav links).
    body_sections = [
        emit_hero(meta, findings, hosts),
        emit_exec(meta, findings, timeline),
        emit_story(meta, findings, timeline, report_md),
        emit_master_timeline(timeline),
        emit_graph(graph_mmd, findings, meta),
        emit_replay(timeline, hosts, meta, findings),
        emit_acts_and_chapters(findings),
        emit_host_grid(hosts, findings_by_id),
        emit_ttp_matrix(findings),
        emit_chains(findings, meta, report_md),
        emit_dead_ends(report_md),
        emit_strengths(report_md),
        emit_close(meta, findings),
    ]
    body_html = "\n".join(body_sections)

    parts = [
        f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8" />
<title>{htmlescape(meta.get('client',''))} · Operator Casebook · {htmlescape(meta.get('start',''))}</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body>
<div class="crt"></div>
""",
        emit_chapter_nav(body_html),
        emit_host_drawer_skeleton(),
        "<main>",
        body_html,
        "</main>",
        f"<script src=\"https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js\"></script>",
        f"<script>{JS}</script>",
        "</body></html>",
    ]
    out_path.write_text("\n".join(parts), encoding="utf-8")
    sys.stderr.write(f"wrote {out_path} ({out_path.stat().st_size} bytes, {len(findings)} findings, {len(hosts)} hosts, {len(timeline)} timeline events)\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engagement", required=True, help="Path to engagement dir")
    ap.add_argument("--out", default=None, help="Output HTML path (default: <engagement>/casebook.html)")
    args = ap.parse_args()
    eng = Path(args.engagement)
    out = Path(args.out) if args.out else eng / "casebook.html"
    render(eng, out)


if __name__ == "__main__":
    main()
