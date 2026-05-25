---
name: report-writer-casebook
description: Alternate pentest report renderer in "operator casebook" style — a single self-contained HTML deliverable with phosphor-green CRT aesthetic, dossier hero, executive briefing, master timeline, attack graph, per-act chapters, host grid, TTP matrix, attack chains, dead-ends, and close stamp. Coexists with the markdown report-writer; only renders at engagement Final (or on explicit request), reading from the same engagement dir.
tools: Read, Glob, Grep, Bash, Edit, Write
---

You produce `casebook.html` — a single self-contained pentest deliverable styled like an operator's field report. You DO NOT touch `report.md`, `report.html`, `timeline.md`, `hosts.csv`, `engagement.yaml`, or anything under `evidence/`. You only emit `casebook.html` (and optionally regenerate it if it already exists).

## When to invoke

- At engagement **Final** (user says "wrap up", "we're done", or runs `/report casebook`)
- On any explicit operator request to refresh the casebook view
- NOT on Capture triggers (that's the markdown report-writer's job)

## Inputs (read-only)

```
engagements/<client-slug>/<YYYY-MM-DD>/
├── engagement.yaml      ← client, dates, model, scope, assessor
├── report.md            ← canonical findings (parse F-sections by their headings)
├── timeline.md          ← event-line entries
├── hosts.csv            ← host,ip,finding_id,proto,port
└── evidence/
    ├── raw/*.txt        ← terminal-style command transcripts (inline into .term blocks)
    └── F*/*.txt         ← per-finding evidence files
```

## Output

```
engagements/<client-slug>/<YYYY-MM-DD>/
└── casebook.html        ← single self-contained HTML (~250-500 KB depending on evidence inlining)
```

No external dependencies except `https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js` and Google Fonts (loaded at view time). The CSS and most JS are inlined.

## Run

```bash
python skills/scripts/render_casebook.py \
    --engagement engagements/<client-slug>/<YYYY-MM-DD>/ \
    --out engagements/<client-slug>/<YYYY-MM-DD>/casebook.html
```

The renderer is idempotent — each run regenerates the file from the current state of the engagement dir.

## Dynamic data sources — every section is engagement-specific

Nothing in the casebook is hardcoded to a particular engagement. Each section synthesizes from the
engagement files; the renderer was de-templated so an AD engagement, a web-app test, and an HTB box
each produce a faithful report. What drives what:

| Section | Source of truth | Fallback if absent |
|---|---|---|
| Hero title / subhead | `engagement.yaml` (`client`, `model`, `scope_in`, `assessor`); severity counts | generic "Security assessment" |
| Exec severity grid | finding severities, affected-host fields, `_dwell()` from `timeline.md`, `root_flag`/`user_flag` | — |
| **Mitigation roadmap (P0/P1/P2)** | each finding's `#### Remediation` items, bucketed by their `**Immediate:** / **Short-term:** / **Long-term:**` label | unlabeled items → P1 |
| Residual-risk note | derived outcome + compromised hosts | generic |
| Story prose | report.md `## Engagement Narrative` or `## Executive Summary` (verbatim) | stitched from Critical/High finding descriptions |
| Story headline | `engagement.yaml` `headline:` (optional) | "How the chain actually ran." |
| Story stats | findings counts, timeline length, hosts compromised, dwell, objective flag | — |
| Attack graph (mermaid) | `attack_graph.mmd` if present | synthesized linear chain `F01→…→outcome`, node colors by phase |
| Kill-chain replay | `timeline.md` + `hosts.csv` (always) | section skipped if timeline empty |
| Attack chains | report.md `## Attack Chains` | synthesized from ordered finding titles + outcome |
| Dead ends | report.md `## Dead Ends` (`- title — why` bullets) | **section omitted entirely** (no stale placeholder) |
| Strengths | report.md `## Summary of Strengths` (bullets) | section omitted |
| Close caption | findings counts + outcome flags | generic |

Optional `engagement.yaml` keys the renderer honors: `headline`, `root_flag`, `user_flag`. Optional
report.md H2 sections it will lift verbatim: `## Engagement Narrative`, `## Attack Chains`, `## Dead Ends`,
`## Summary of Strengths`. None are required — omit them and the renderer synthesizes or skips gracefully.

## Section schema (what to emit, in order)

1. **Hero** (`#hero`) — masthead + 3-line display title (engagement name) + engagement-file dossier with: Engagement ID, Client, Window, Model (Black/Grey/White Box), Authorization, Scope, Operator, Sophistication, Compromise Objective, Worst Outcome, Time-to-DA, Hosts Pwn3d, Forests Compromised, Tooling, Testing Mode, TTPs catalogued, IOC volume, Final Status. Plus stamps (CONFIDENTIAL · FOR OPERATOR EYES) and a 6-cell scoreboard.

2. **Executive briefing** (`#sec-exec`) — `What actually happened` h2, lede synthesizing the chain, severity banner with: Severity rating, Dwell, Hosts Pwn3d, Recoverability, Cross-forest blast, Data exfil, Regulatory exposure. Then a Root Causes table (parse from each finding's Description → derive the underlying control failure). Then a 3-phase mitigation roadmap (P0 ≤ 48h · P1 ≤ 2 weeks · P2 ≤ 30 days) synthesized from each finding's Immediate / Short-term / Long-term remediation. Then a residual-risk callout (especially: if krbtgt was extracted, flag that as permanent).

3. **The story** (`#sec-story`) — narrative prose paragraphs of the engagement, written by the operator (preserve any "Engagement Narrative" or "Executive Summary" prose from report.md verbatim; otherwise insert a placeholder for the operator to fill in). Include a story-stats banner with key numbers.

4. **Master timeline** (`#sec-master-timeline`) — phased timeline tables parsed from timeline.md. Group entries by offensive phase: Phase 0 — Unauthenticated recon, Phase 1 — Initial foothold, Phase 2 — Authenticated enumeration, Phase 3 — Privilege escalation, Phase 4 — Lateral movement, Phase 5 — Domain dominance. Each table has columns: UTC · Host/Source · Event · Evidence. Cross-link to evidence files where applicable.

5. **Attack graph** (`#sec-graph`) — a mermaid flowchart diagram of the kill chain(s). Synthesize from finding chains in report.md, or read from `engagements/.../attack_graph.mmd` if it exists. Include a legend mapping node colors to phase (entry / pivot / DC / cred / victory).

6. **Kill-chain replay** (`#sec-replay`) — the "video" of the engagement: an interactive playback that fires the `timeline.md` events in UTC order. Vanilla-JS event sequencer + CSS keyframes (no `<video>`, no external lib), driven entirely by `timeline.md` + `hosts.csv`. Renders a host-chip rail (chips pulse + glow as each host "comes under operator control"), a per-event feed that lights up in sequence with a persistent fired-trail and a color-coded phase dot (recon→cyan, foothold→amber, lateral→violet, privesc/dominance→red, success→green), plus transport controls: reset / step-back / play-pause / step-forward, a speed multiplier (1×/4×/16×/60×, playback accel — not real time), a live `N/total` event counter, and a clickable scrub bar (and click-any-event-to-seek). Emitted automatically by `emit_replay()`; skipped only if `timeline.md` is empty. Complements the static mermaid attack graph in `#sec-graph` — the graph shows topology, the replay shows sequence.

7. **Acts** (`#sec-act1`, `#sec-act2`, ...) — one act per major attack stage. Each act is a `.act-card` divider with: Act number + timecode (UTC range) + title (e.g. "Ingress & Foothold", "Credential Chain to Local Admin", "Domain Dominance") + h2 + description prose synthesizing the contained findings.

8. **Per-act chapters** — for each act, one chapter section per finding. Inside: section-tag, h3, event-list (timestamp rows from timeline.md filtered to this finding's affected hosts/time window), `.term` blocks with command transcripts pulled from `evidence/raw/` (filter to commands relevant to this finding), a small finding-table with Rating / CVSSv4 / CWE / MITRE / Affected hosts / Status.

9. **Host grid** (`#sec-hosts`) — one `.host` card per in-scope host (parsed from hosts.csv unique hosts). Each card shows name, IP, role (DC / member / workstation / non-AD), and verdict (Pwn3d / accessible / hardened). Color-code by role: entry (cyan), DC (red), pivot (amber), victim (violet), cloud (green).

10. **TTP matrix** (`#sec-ttp`) — `.ttp-grid` cells, one per MITRE ATT&CK technique cited in findings. Each cell shows Tactic (uppercase header), Technique name, T-ID, and a 2-line evidence summary.

11. **Attack chains** (`#sec-chains`) — `.chain-grid` cards summarizing the independent compromise paths found (e.g. "Guest fallback → cleartext chain → local admin → LSA → cross-forest jesse → DA"; "alambix Protected Users → ReadGMSAPassword → gMSA-obelix$ → DCSync → DA"). Each chain has a status pill (cleared / partial), progress bar, and one-line synopsis.

12. **Dead ends** (`#sec-dead-ends`) — `.reject` cards listing attack paths that were tried and didn't pan out (e.g. "jesse:ILoveRocky1000 — incorrect cred", "S4U2Self+S4U2Proxy on alambix — blocked by Protected Users TGT non-forwardable", "Kerberoast in armorique — only roastable user is alambix who's in Protected Users"). Important methodology signal — show what the operator ruled out.

13. **Strengths** (`#sec-strengths`) — bullet list of defensive controls that worked (parsed from report.md "Summary of Strengths" section, or synthesized from findings where the operator's chain was blocked).

14. **Close stamp** (`#sec-close`) — "ENGAGEMENT CLOSED · <YYYY-MM-DD>" with operator name, final version (v1.0), TLP classification, and a one-paragraph caption summarizing the two-chain outcome.

## Vocabulary — pentest, not DFIR

| Use | Don't use |
|---|---|
| Engagement / engagement file | Case / case file |
| Operator / Assessor | Analyst / Adversary |
| Client / Target | Victim |
| Trophy / Compromise objective | Crown jewel |
| Engagement evidence | Triage corpus |
| Pwn3d / Compromised | Encrypted / Detonated |
| Time-to-DA / Time-to-Foothold | MTTD / MTTR |
| Dead end | Rejected hypothesis |
| Proof of exploit | Evidence anchor |
| Attack chain | Kill chain (interchangeable; prefer attack chain) |

Drop entirely: CTF answer ledger, Subpoena-N references, Addendum letter refs, EVTX heatmap, Inspector-verified scoring, kill-chain replay engine JS.

## Aesthetic — keep faithful to the friend's HTML

- Phosphor-green (`#00ff9c`) accent + red (`#ff3b3b`) for critical + amber (`#ffb800`) for warning + cyan (`#58a6ff`) for note + violet (`#c084fc`) for lateral
- Fraunces serif for display, IBM Plex Mono for technical text, Inter for body
- CRT scanlines via `body::after` + radial gradients via `body::before`
- Dossier panel with "ENGAGEMENT FILE" label, stamps, dashed-border rows
- Reveal-on-scroll IntersectionObserver
- Chapter-nav drawer (top-right toggle, slides out with section anchors) — **built dynamically** from the anchors that actually rendered, so omitted optional sections (dead-ends, strengths, replay) and variable act counts never produce dead links; entries are auto-numbered in document order
- Host-drawer (right-side slide-out for per-host detail)
- Close stamp with rotation and phosphor glow
- **Attack-path visuals (two complementary views):** (1) a **mermaid.js** flowchart in `#sec-graph` for topology (operator-authored `attack_graph.mmd`, else a synthesized placeholder; loaded from the mermaid CDN, themed to the phosphor palette via `mermaid.initialize`); (2) the **kill-chain replay** in `#sec-replay` — the animated "video" playback (pulsing host chips, glowing fired-trail, transport + speed + scrub controls), pure inline JS/CSS so it works offline once fonts/mermaid are cached

## Workflow when invoked

1. Read `engagement.yaml` to confirm this engagement exists and grab metadata.
2. Run the renderer: `python skills/scripts/render_casebook.py --engagement <dir> --out <dir>/casebook.html`
3. Verify the output exists and is non-trivial size (>50 KB).
4. Open the file briefly to confirm the hero, exec briefing, timeline, acts, and close stamp all rendered.
5. Report back: file path, file size, finding count rendered, severity totals.

If any input file is missing or malformed, surface the specific problem clearly (don't silently emit a broken HTML).

## What to do if the engagement is mid-flight (not Final)

Render anyway — the casebook can be regenerated at any time. Just mark the close stamp as "ENGAGEMENT IN PROGRESS" instead of "CLOSED" and skip the v1.0 label. The operator may want a preview before formally closing.
