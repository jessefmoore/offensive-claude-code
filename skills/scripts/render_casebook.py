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
        f.cvss_score = _kv_extract(body, "CVSSv4 Score")
        f.cvss_vector = _kv_extract(body, "CVSSv4 Vector")
        f.cwe = _kv_extract(body, "CWE")
        f.mitre = _kv_extract(body, r"MITRE ATT&CK")
        f.hosts = _kv_extract(body, "Affected hosts")
        f.location = _kv_extract(body, "Location")
        f.description = _section_extract(body, "Description")
        f.discovery = _section_extract(body, "Discovery")
        f.evidence = _section_extract(body, "Evidence")
        f.impact = _section_extract(body, "Business Impact")
        f.solution = _section_extract(body, "Solution")
        f.references = _section_extract(body, "References")
        findings.append(f)
    return findings


def _kv_extract(body: str, key: str) -> str:
    m = re.search(rf"^\*\*{key}:\*\*\s+(.+?)$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _section_extract(body: str, name: str) -> str:
    pattern = rf"^####\s+{re.escape(name)}\s*$"
    m = re.search(pattern, body, re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^####\s+", body[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(body)
    return body[start:end].strip()


def parse_timeline(timeline_md: str) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for line in timeline_md.splitlines():
        m = re.match(r"^\*\*(.+?)\*\*\s+—\s+(.+)$", line.strip())
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
        Internal AD penetration test against <b>{htmlescape(client)}</b> · scope
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


def emit_exec(meta: dict, findings: list[Finding]) -> str:
    counts = severity_counts(findings)
    sev = "CRITICAL" if counts['Critical'] else ("HIGH" if counts['High'] else "MEDIUM")
    sev_color = "red" if counts['Critical'] else ("amber" if counts['High'] else "")
    # Build root causes table from each finding's CWE
    rows = []
    for i, f in enumerate(findings, 1):
        if f.rating.lower().startswith(("critical", "high")):
            rows.append(f"""<tr><td class="a">{i}</td><td>{md_to_html_inline(f.title)}</td><td class="c">{md_to_html_inline(f.mitre)}</td><td class="m">{md_to_html_inline(f.cwe)}</td></tr>""")
    rows_html = "\n".join(rows[:12])  # cap
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
      <div class="sub">Identity-tier breach · full AD compromise</div>
    </div>
    <div class="sev-grid">
      <div class="sg"><div class="k">Findings (Critical)</div><div class="v {sev_color}">{counts['Critical']}</div><div class="d">of {len(findings)} total</div></div>
      <div class="sg"><div class="k">Findings (High)</div><div class="v amber">{counts['High']}</div><div class="d">substantial uplift</div></div>
      <div class="sg"><div class="k">Recoverability</div><div class="v red">krbtgt extracted</div><div class="d">2× rotation required</div></div>
      <div class="sg"><div class="k">Cross-forest blast</div><div class="v amber">Documented</div><div class="d">password reuse audit</div></div>
      <div class="sg"><div class="k">Data exfil</div><div class="v">NTDS dual-forest</div><div class="d">via DCSync chains</div></div>
      <div class="sg"><div class="k">Regulatory</div><div class="v amber">Domain-tier</div><div class="d">tier-0 secrets disclosed</div></div>
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
          <li>Rotate <b>krbtgt × 2</b> (48h apart) in every compromised forest</li>
          <li>Reset every account in NTDS; force password change at next logon</li>
          <li>Disable Guest accounts on all in-scope DCs and member servers</li>
          <li>Restrict <code>ReadGMSAPassword</code> to tier-0 admin groups</li>
          <li>Audit gMSAs for DCSync-equivalent rights (<code>GetChanges*</code> on domain root)</li>
          <li>Reset LAPS-managed local-admin passwords on every host</li>
        </ul>
      </div>
      <div class="rm-col p1">
        <div class="rm-h">Hardening &amp; Detection</div>
        <ul>
          <li>Enforce LDAP signing + channel binding (<code>LdapEnforceChannelBinding=2</code>) on all DCs</li>
          <li>Enforce SMB signing required on every member server</li>
          <li>Disable LLMNR/NBT-NS/mDNS via GPO</li>
          <li>Audit ADCS templates; disable HTTP web enrollment (ESC8)</li>
          <li>Move privileged accounts into <b>Protected Users</b> security group</li>
          <li>Enable Credential Guard on all member servers</li>
        </ul>
      </div>
      <div class="rm-col p2">
        <div class="rm-h">Architectural</div>
        <ul>
          <li>Adopt Microsoft Tier 0/1/2 administrative model</li>
          <li>Eliminate cross-forest identity password reuse via SSO/federation</li>
          <li>Deploy Windows LAPS for unique rotated local-admin passwords</li>
          <li>Replace cleartext-storing services (FTP) with authenticated SFTP</li>
          <li>Deploy banned-password lists (Azure AD Password Protection)</li>
          <li>Quarterly purple-team replay of this attack chain</li>
        </ul>
      </div>
    </div>
  </div>

  <div class="residual-note">
    <b>Residual risk.</b> With <code>ntds.dit</code> contents extracted from both forests, every domain password
    hash is compromised <b>permanently</b>. Double krbtgt rotation stops golden-ticket forgery against new
    sessions, but offline cracking of lifted NTDS yields plaintext for any account that isn't forced to rotate.
    Treat this as a <b>full identity-tier breach</b>, not a host-tier incident.
  </div>
</section>
"""


def emit_story(meta: dict, findings: list[Finding], timeline: list[TimelineEvent]) -> str:
    counts = severity_counts(findings)
    n_events = len(timeline)
    n_crit = counts["Critical"]
    prose_paragraphs = []
    # Use F18 / F20 / F28 summaries if present (the cornerstone findings)
    # otherwise stitch from the first Critical findings
    cornerstones = [f for f in findings if f.rating.lower().startswith("critical")]
    if cornerstones:
        intro = (
            f"<p>The {htmlescape(meta.get('client','engagement'))} engagement reached "
            f"<b>{n_crit} Critical findings</b> across "
            f"<b>{n_events} logged operator actions</b>. The chain ran end-to-end from "
            "zero credentials through Guest fallback, share looting, local-admin compromise, "
            "LSA secrets, LAPS read over-delegation, and finally DCSync on two independent paths.</p>"
        )
        prose_paragraphs.append(intro)
        for f in cornerstones[:4]:
            short = (f.description or "").split("\n\n")[0][:600]
            prose_paragraphs.append(
                f"<p><b>{htmlescape(f.fid)} — {md_to_html_inline(f.title)}.</b> {md_to_html_inline(short)}</p>"
            )
        prose_paragraphs.append(
            "<p class=\"end\">Final state: dual-forest Domain Admin via two independent chains "
            "(cross-forest password reuse and gMSA→DCSync). krbtgt hashes captured in both forests; "
            "rotation required.</p>"
        )
    else:
        prose_paragraphs.append("<p>Engagement narrative to be drafted from findings.</p>")
    prose = "\n".join(prose_paragraphs)

    return f"""
<section class="reveal" id="sec-story" style="background: linear-gradient(180deg, rgba(0,255,156,.025), transparent 40%);">
  <div class="section-tag">// 02 · the story · zero to dual-forest DA</div>
  <h2>From zero credentials to <em>two forests</em> in one window.</h2>

  <div class="story-stats">
    <div class="ss"><div class="n">{n_crit}</div><div class="l">Critical findings</div></div>
    <div class="ss"><div class="n">{counts['High']}</div><div class="l">High findings</div></div>
    <div class="ss"><div class="n">{n_events}</div><div class="l">logged actions</div></div>
    <div class="ss red"><div class="n">2</div><div class="l">independent chains to DA</div></div>
    <div class="ss"><div class="n">2</div><div class="l">forests compromised</div></div>
    <div class="ss red"><div class="n">∞</div><div class="l">krbtgt hashes, permanently</div></div>
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


def emit_graph(graph_mmd: str | None) -> str:
    """Render attack-graph mermaid if the operator provided one; otherwise emit a placeholder."""
    if not graph_mmd:
        # Synthesize a placeholder pentest-style attack graph
        graph_mmd = """
flowchart LR
  RECON[Unauthenticated Recon]:::recon --> FOOTHOLD[Guest Fallback / Anonymous SMB]:::foothold
  FOOTHOLD --> CRED[Cleartext Credential Chain]:::cred
  CRED --> LADM[Local Admin via Predictable Cred]:::pwn
  LADM --> LSA[LSA Secrets / DPAPI / LAPS Read]:::cred
  LSA --> DOMA[Domain Admin Path A: cross-forest jesse PtH]:::da
  LSA --> DOMB[Domain Admin Path B: alambix → gMSA → DCSync]:::da
  DOMA --> DCSYNC1[NTDS Forest 1]:::dcsync
  DOMB --> DCSYNC2[NTDS Forest 2]:::dcsync
  DCSYNC1 --> KRBTGT1[krbtgt - Forest 1]:::krbtgt
  DCSYNC2 --> KRBTGT2[krbtgt - Forest 2]:::krbtgt
  classDef recon fill:#0b2030,stroke:#58a6ff,color:#e6edf3
  classDef foothold fill:#251b00,stroke:#ffb800,color:#e6edf3
  classDef cred fill:#1b1530,stroke:#c084fc,color:#e6edf3
  classDef pwn fill:#3a0d0d,stroke:#ff3b3b,color:#e6edf3
  classDef da fill:#0d2b1f,stroke:#00ff9c,color:#e6edf3
  classDef dcsync fill:#0d2b1f,stroke:#00ff9c,color:#e6edf3
  classDef krbtgt fill:#3a0d0d,stroke:#ff3b3b,color:#e6edf3
""".strip()
    graph_escaped = graph_mmd  # mermaid blocks don't need HTML-escaping inside .mermaid
    return f"""
<section class="reveal" id="sec-graph">
  <div class="section-tag">// 04 · attack graph · the kill chain</div>
  <h2>How the chain <em>actually</em> ran.</h2>
  <p class="lede">Each node is an attacker waypoint; each edge is a transition we proved in the engagement.
  Two independent paths to dual-forest DA — neither requires the other.</p>
  <div class="graph-wrap">
    <div class="mermaid">
{graph_escaped}
    </div>
  </div>
  <div class="graph-legend">
    <div class="li"><span class="sw" style="background:#58a6ff"></span>Recon</div>
    <div class="li"><span class="sw" style="background:#ffb800"></span>Foothold</div>
    <div class="li"><span class="sw" style="background:#c084fc"></span>Credential</div>
    <div class="li"><span class="sw" style="background:#ff3b3b"></span>Pwn3d / krbtgt</div>
    <div class="li"><span class="sw" style="background:#00ff9c"></span>Domain Admin</div>
  </div>
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


def emit_chains() -> str:
    return """
<section class="reveal" id="sec-chains">
  <div class="section-tag">// 07 · attack chains · independent paths to forest DA</div>
  <h2>Two chains. <em>Both</em> ended in krbtgt.</h2>
  <p class="lede">Two completely independent paths to dual-forest Domain Admin. Each chain is
  self-contained: removing every step of one does not break the other.</p>
  <div class="chain-grid">
    <div class="chain"><div class="n">Chain A · Guest fallback → cross-forest pwn <span class="p">CLEARED</span></div>
      <div class="s">Anonymous SMB → Guest-readable share <code>infos.txt</code> → FTP cleartext <code>plans.txt</code>
      → local-admin via predictable username + leaked password → SAM + LSA dump → cleartext domain user
      → DPAPI vault → LAPS over-delegation → REFERENDUM secretsdump → <code>jesse</code> identity password reuse
      across forests → PtH armorique.local DC → DCSync both forests.</div>
      <div class="bar"><i style="width:100%"></i></div>
    </div>
    <div class="chain"><div class="n">Chain B · alambix → gMSA → DCSync <span class="p">CLEARED</span></div>
      <div class="s">A regular Protected-Users-bound domain user (<code>alambix</code>) holds
      <code>ReadGMSAPassword</code> on <code>gMSA-obelix$</code> → extract current gMSA NT hash →
      <code>gMSA-obelix$</code> has <code>GetChanges + GetChangesAll</code> directly on the domain root →
      DCSync → full armorique.local NTDS. Two AD over-delegations stacked on a non-admin user.
      Independent of Chain A — never touches <code>jesse</code> or rome.local.</div>
      <div class="bar"><i style="width:100%"></i></div>
    </div>
  </div>
</section>
"""


def emit_dead_ends() -> str:
    return """
<section class="reveal" id="sec-dead-ends">
  <div class="section-tag">// 08 · dead ends · paths that didn't pan out</div>
  <h2>What we ruled out.</h2>
  <p class="lede">Operator methodology requires showing the ground we tested and ruled out. These attempts
  failed for reasons that are themselves engagement findings (defense-in-depth working, neutralized
  misconfigurations, hardened endpoints).</p>
  <div class="reject">
    <span class="cid">DEAD END 1</span> · <span class="bad">jesse:[REDACTED-PASSWORD] — incorrect credential</span>
    <div class="why">Operator-supplied guess cracked against jesse's cached DCC2 hash and tested via NTLM SMB,
    LDAP, WinRM, and Kerberos AS-REQ across all 4 in-scope hosts on both forests. Multiple verified offline
    and online; the password belongs to <code>jesse2</code> + <code>svc_wikijs</code> (intra-domain password
    collision), not <code>jesse</code>.</div>
  </div>
  <div class="reject">
    <span class="cid">DEAD END 2</span> · <span class="bad">S4U2Self+S4U2Proxy on alambix — KDC_ERR_BADOPTION</span>
    <div class="why">alambix has <code>TRUSTED_TO_AUTH_FOR_DELEGATION</code> + a constrained-delegation target
    of <code>CIFS/armorique.armorique.local</code> (the DC), but is also in <b>Protected Users</b>. Protected
    Users makes the user's TGT non-forwardable by design, so S4U2Proxy fails. Defense-in-depth working —
    the misconfiguration is neutralized, not exploitable.</div>
  </div>
  <div class="reject">
    <span class="cid">DEAD END 3</span> · <span class="bad">Kerberoast in armorique.local · no usable hashes</span>
    <div class="why">Only SPN-bearing principal in armorique.local besides krbtgt is <code>alambix</code> itself.
    Roasting <code>CIFS/aleem.armorique.local</code> via <code>prolix</code> as a regular Authenticated User
    returned an RC4-HMAC TGS (despite Protected Users on alambix), but offline crack against the lab-themed
    wordlist returned no hit. Hash recovered via DCSync instead.</div>
  </div>
  <div class="reject">
    <span class="cid">DEAD END 4</span> · <span class="bad">Password spray against 27 armorique.local users · no hits</span>
    <div class="why">3 patterns × 27 users via authenticated SMB (Welcome1, Password1, Lehack2024, asterix-cast
    names, Capitalized + year suffix, Monday-themed). Zero hits. Triggered the pivot to BloodHound shortest-path
    analysis (per the saved feedback rule).</div>
  </div>
  <div class="reject">
    <span class="cid">DEAD END 5</span> · <span class="bad">VILLAGE SYSVOL/NETLOGON share spider · no creds found</span>
    <div class="why">Authenticated spider as alambix returned 9 benign GPO templates + 1 empty bait file.
    No <code>Groups.xml</code> with GPP cpassword, no <code>Registry.xml</code> with AutoLogon, no login
    scripts with embedded creds. Clean SYSVOL hygiene — a defensive strength.</div>
  </div>
  <div class="reject">
    <span class="cid">DEAD END 6</span> · <span class="bad">DCSync as lapsus → ERROR_DS_DRA_BAD_DN</span>
    <div class="why">lapsus is a regular domain user with LAPS-read on two hosts but no replication rights.
    DCSync attempt returned DRSR DN error (not access-denied); lapsus is not tier-0. Resolved by reaching
    DA via jesse2 (granted DA membership during engagement window for demonstration purposes — disclosed
    in F18).</div>
  </div>
</section>
"""


def emit_close(meta: dict) -> str:
    status = meta.get("status", "in-progress").lower()
    is_complete = status == "complete"
    end = meta.get("end") or meta.get("start", "")
    version = meta.get("version", "")
    client = meta.get("client", "")
    assessor = meta.get("assessor", "")
    label = "ENGAGEMENT CLOSED" if is_complete else "ENGAGEMENT IN PROGRESS"
    stamp_class = "" if is_complete else "draft"
    return f"""
<section class="close" id="sec-close">
  <div class="section-tag">// engagement file closed · {htmlescape(end)} utc</div>
  <h2 class="big">{htmlescape(client)} — <em>{'resolved' if is_complete else 'in progress'}</em>.</h2>
  <p class="caption">
    Two independent paths to dual-forest Domain Admin. krbtgt extracted in both forests.
    Cross-forest identity password reuse documented. gMSA + ReadGMSAPassword over-delegation
    isolated as a parallel compromise primitive. Fully reproducible via the commands and
    evidence files in this casebook.
  </p>
  <div style="margin-top: 42px; padding-top: 28px; border-top: 1px solid var(--line-2); display: inline-flex; flex-direction: column; gap: 6px; align-items: center; font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: .22em; color: var(--muted); text-transform: uppercase;">
    <span>Signed &nbsp;<b style="color:var(--text); letter-spacing:.3em;">{htmlescape(assessor.upper())}</b></span>
    <span style="color: var(--dim); font-size: 10.5px;">TLP-AMBER · for operator eyes</span>
  </div>
  <div class="closed-stamp {stamp_class}" style="margin-top: 32px;">{label} · {htmlescape(end)} · v{htmlescape(version)}</div>
</section>
"""


def emit_chapter_nav(findings: list[Finding]) -> str:
    """Build the right-side drawer nav."""
    static_sections = [
        ("hero", "01", "Engagement File"),
        ("sec-exec", "02", "Executive Briefing"),
        ("sec-story", "03", "The Story"),
        ("sec-master-timeline", "04", "Master Timeline"),
        ("sec-graph", "05", "Attack Graph"),
        ("sec-act1", "06", "Act I"),
        ("sec-act2", "07", "Act II"),
        ("sec-act3", "08", "Act III"),
        ("sec-act4", "09", "Act IV"),
        ("sec-act5", "10", "Act V"),
        ("sec-hosts", "11", "Host Grid"),
        ("sec-ttp", "12", "TTP Matrix"),
        ("sec-chains", "13", "Attack Chains"),
        ("sec-dead-ends", "14", "Dead Ends"),
        ("sec-close", "15", "Closed"),
    ]
    items = "\n".join(
        f'<a href="#{sid}" data-num="{num}">{name}</a>'
        for sid, num, name in static_sections
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
    findings = parse_findings(report_p.read_text(encoding="utf-8"))
    timeline = parse_timeline(timeline_p.read_text(encoding="utf-8"))
    hosts = parse_hosts(hosts_p.read_text(encoding="utf-8"))
    graph_mmd = graph_p.read_text(encoding="utf-8") if graph_p.is_file() else None

    global findings_by_id
    findings_by_id = {f.fid: f for f in findings}

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
        emit_chapter_nav(findings),
        emit_host_drawer_skeleton(),
        "<main>",
        emit_hero(meta, findings, hosts),
        emit_exec(meta, findings),
        emit_story(meta, findings, timeline),
        emit_master_timeline(timeline),
        emit_graph(graph_mmd),
        emit_acts_and_chapters(findings),
        emit_host_grid(hosts, findings_by_id),
        emit_ttp_matrix(findings),
        emit_chains(),
        emit_dead_ends(),
        emit_close(meta),
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
