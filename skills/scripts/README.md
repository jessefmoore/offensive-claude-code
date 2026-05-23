# skills/scripts/

Persistent scratch space for helper scripts Claude has already built.
Check here BEFORE writing a new helper — if a script with the capability
you need already exists, reuse it (and improve it) instead of recreating.

## Conventions

- **One purpose per file.** Filename describes the capability
  (`kali_ssh.py`, `ludus_range_info.py`, `ntlm_relay_helper.sh`).
- **Top-of-file docstring** stating what it does, default targets, env
  vars, and example invocations. Future-Claude greps this folder; make
  the first 10 lines self-explanatory.
- **No secrets in source — no exceptions.** No hardcoded IPs, hostnames,
  usernames, or passwords, even as defaults. Read all sensitive config
  from env vars or a sibling `.env` file (gitignored). Provide a
  `.env.example` with empty values so the required keys are discoverable.
  This repo is public — assume anything committed is world-readable.
- **Stdlib first.** Only add a dependency when the win is clear
  (paramiko for password SSH, requests for HTTP APIs). Note required
  packages in the docstring.
- **Exit codes matter.** Propagate the remote command's exit status when
  the script is a wrapper. Future tooling may chain these.

## Current scripts

Run `ls skills/scripts/` for the canonical list. As of writing:

| Script               | Purpose                                             |
|----------------------|-----------------------------------------------------|
| `kali_ssh.py`        | Non-interactive password SSH via paramiko. Config via `KALI_HOST` / `KALI_USER` / `KALI_PASS` env vars or `skills/scripts/.env` (see `.env.example`). |
| `new_engagement.py`  | Scaffold a new pentest engagement directory under `./engagements/<client>/<date>/` with report.md template, engagement.yaml, timeline.md, hosts.csv, and an empty `evidence/`. Invoked by the `report-writer` agent at engagement kickoff. |
| `render_report.py`   | Render `report.md` → self-contained `report.html` (embedded CSS, Pygments syntax highlighting, base64-inlined evidence images). Pass `--final` to drop the draft banner. Requires `markdown` + `pygments` (pip). |
| `ntds_diff.py`       | Cross-dump NT-hash collision audit between two `secretsdump`/`nxc --ntds` outputs. Surfaces cross-forest password reuse (same plaintext password unlocks two unrelated identity domains) and intra-domain collisions (shared service-account passwords). Stdlib-only. |
| `nxc_kerberos_wrapper.py` | Run nxc with Kerberos auth on a Kali that has neither `/etc/hosts` for the AD realms (no sudo) nor a clock synced to the DC. Configurable via `NXC_HOSTS=name=ip,...` and `NXC_OFFSET=<seconds>` env vars. Works for every nxc flag/protocol; pass nxc args verbatim after the script name. |
| `render_casebook.py` | Render an engagement dir into a self-contained pentest "operator casebook" HTML deliverable (alternate to `render_report.py`). Hero with engagement dossier + scoreboard, executive briefing, master timeline (phased), mermaid attack graph, 5 acts with per-finding chapters, host grid, MITRE ATT&CK matrix, attack chains, dead ends, close stamp. Single self-contained file (~250–400 KB), no external deps except Google Fonts + mermaid CDN. Invoked by the `report-writer-casebook` agent at engagement Final. Stdlib only. |
| `redact_engagement.py` | Sanitize a finalized engagement directory by redacting cleartext passwords (full mask `[REDACTED-PASSWORD]`) and tier-0 NT/AES/DCC2 hashes (partial mask — first 8 hex chars + `[REDACTED]`) across `report.md` / `timeline.md` / `evidence/` / HTML / extracted v1.0 dir. Reads `<engagement>/.secrets.yaml` (gitignored) for the secrets list; auto-derives `krbtgt`+`Administrator` NT hashes from `*.ntds` dump files. Dry-run by default, `--apply` to commit. Idempotent. Run before publishing any final deliverable. |

## When to promote a script out of here

If a script grows methodology (not just plumbing) — e.g. a multi-step
attack workflow with decision points — move it into its parent skill's
folder (`skills/<skill-name>/scripts/`) and reference it from
`SKILL.md`. `skills/scripts/` is for cross-skill utilities.
