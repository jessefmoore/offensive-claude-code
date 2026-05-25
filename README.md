# Offensive Security Research Config for Claude Code

A comprehensive Claude Code configuration tailored for security researchers, red teamers, and vulnerability analysts. Includes 30 specialized skills, 10 agents, and a large vulnerability/technique reference base covering the full offensive security lifecycle — plus lab-operator personas (HTB, HackSmarter) and a reporting pipeline (internal-pentest, HTB, HackSmarter, and operator-casebook deliverables).

> Originally bootstrapped from [hypnguyen1209/offensive-claude](https://github.com/hypnguyen1209/offensive-claude) as a starting point, and since substantially extended (lab-operator personas, the reporting pipeline, additional skills, and an expanded knowledge base). Thanks to the original author.

## Quick Setup

```bash
# Method 1: One-liner install (recommended)
curl -sL https://raw.githubusercontent.com/jessefmoore/offensive-claude/main/install.sh | bash
```

```bash
# Method 2: Clone + install script
git clone https://github.com/jessefmoore/offensive-claude.git ~/offensive-claude
cd ~/offensive-claude && bash install.sh
```

```bash
# Method 3: Manual copy
git clone https://github.com/jessefmoore/offensive-claude.git ~/offensive-claude
cp -r ~/offensive-claude/skills ~/.claude/skills
cp -r ~/offensive-claude/agents ~/.claude/agents
cp ~/offensive-claude/CLAUDE.md ~/.claude/CLAUDE.md
```

Skills and agents activate automatically — no additional configuration needed.

## Structure

```
.
├── skills/                        # 30 skill modules (SKILL.md per directory)
│   ├── recon-osint/
│   ├── vulnerability-analysis/
│   ├── exploit-development/
│   ├── ...
│   ├── scripts/                   # reusable helper scripts (renderers, engagement tooling)
│   └── references/                # vulnerability pattern files
├── agents/                        # 10 specialized sub-agents
├── CLAUDE.md                      # System prompt & behavior config
├── settings.json                  # Claude Code settings, permissions, MCP servers
├── install.sh                     # One-liner install script
└── README.md
```

## Skills (30)

| # | Skill | Coverage |
|---|-------|----------|
| 01 | recon-osint | Subdomain enum, CVE lookup, breach intel, DNS history, Shodan/Censys |
| 02 | vulnerability-analysis | Taint analysis, source-sink tracing, false positive discipline |
| 03 | exploit-development | ROP chains, heap exploitation, shellcode, deserialization, mitigation bypass |
| 04 | reverse-engineering | IDA/Ghidra, Frida, angr, firmware extraction, anti-RE bypass |
| 05 | web-pentest | SQLi, XSS, SSRF, race conditions, GraphQL, JWT, business logic |
| 06 | network-attack | AD exploitation, lateral movement, pivoting, wireless, protocol attacks |
| 07 | red-team-ops | C2, persistence, privesc, defense evasion, LOLBins, exfiltration |
| 08 | cloud-security | AWS/Azure/GCP privesc, container escape, Kubernetes, IaC review |
| 09 | malware-analysis | Static/dynamic analysis, YARA rules, unpacking, C2 protocol RE |
| 10 | ai-security | Prompt injection, RAG poisoning, model extraction, adversarial ML |
| 11 | threat-hunting | MITRE ATT&CK mapping, Sigma rules, log correlation, behavioral detection |
| 12 | privesc-linux | SUID, capabilities, sudo, kernel exploits, Docker escape, cron abuse |
| 13 | privesc-windows | Token abuse, service exploitation, UAC bypass, credential harvesting |
| 14 | coding-mastery | Python/C/Go/Rust/ASM for exploit dev, scanners, C2, crypto |
| 15 | crypto-analysis | TLS auditing, hash cracking, RSA attacks, side-channel, implementation review |
| 16 | incident-response | Memory forensics (Volatility), timeline analysis, IOC extraction, containment |
| 17 | edr-evasion | Hook unhooking, direct/indirect syscalls, AMSI/ETW bypass, sleep masking |
| 18 | initial-access | HTML smuggling, ISO/MOTW bypass, DLL sideload, staged payloads, phishing |
| 19 | shellcode-dev | PEB walk, API hashing, loaders, PE-to-shellcode, cross-platform |
| 20 | windows-mitigations | ASLR/DEP/CFG/CET/ACG bypass, WDAC/ASR bypass, PPL exploitation |
| 21 | windows-boundaries | Kernel/user boundary, sandbox escape, AppContainer, COM elevation |
| 22 | keylogger-arch | SetWindowsHookEx, RawInput, direct HID, ETW capture, stealth IOCs |
| 23 | mobile-pentest | Android/iOS, Frida, SSL pinning bypass, exported components, biometric bypass |
| 24 | advanced-redteam | C2 infra (redirectors, malleable profiles), OPSEC, tiered infrastructure |
| 25 | active-directory-attack | Kerberoasting, NTLM relay, Golden/Silver Ticket, ADCS, delegation abuse |
| 26 | hacksmarter-labs | HackSmarter VPN range — conventions, machine archetypes, per-lab index |
| 27 | sliver-c2 | Sliver C2 — implant generation, listeners, beacons, post-ex, armory, pivoting |
| 28 | socks-pivoting | SOCKS proxying, proxychains config/modes, multi-hop tunneling, DNS, OPSEC |
| 29 | htb | Hack The Box operator persona — 0xdf methodology, enum, user→root workflow |
| 30 | netexec | NetExec (nxc) across SMB/LDAP/WinRM/MSSQL/SSH — enum, spray, creds, lateral move |

## Agents (10)

| Agent | Role |
|-------|------|
| redteam-planner | Designs attack paths, C2 infrastructure, OPSEC strategies |
| exploit-researcher | CVE research, patch diffing, exploitation chain development |
| security-reviewer | Deep code security audit with exploitability validation |
| reverse-engineer | Binary/firmware analysis, vulnerability discovery in compiled code |
| ai-researcher | ML architecture, training optimization, interpretability, safety |
| network-analyst | Packet analysis, protocol dissection, IDS/IPS rule creation |
| report-writer-internalpen | Internal Network Penetration Test report — live markdown + self-contained HTML (kickoff/capture/final) |
| report-writer-casebook | "Operator casebook" deliverable — phosphor-CRT HTML with mermaid attack graph + interactive kill-chain replay |
| report-writer-htb | Hack The Box machine write-up — p3ta00 "Cyberpunk Neon" theme (writeup.md + self-contained HTML) |
| report-writer-hacksmarter | HackSmarter lab write-up — p3ta00 CTF-blog style (narrative, creds table, dead ends, flags) |

## Vulnerability References (47 files)

Detailed patterns with vulnerable/secure code examples, organized by category:

- **Taint Analysis** (4): source-sink tracing, filter evaluation, threat model, false positive reduction
- **Memory Safety** (7): buffer overflow, integer overflow, UAF, null deref, OOB read, unsafe Rust
- **Injection** (11): SQL, command, XSS, SSRF, SSTI, XXE, deserialization, path traversal, file upload, prototype pollution, ReDoS
- **Authentication** (8): bypass, authorization flaws, session management, hardcoded creds, default creds, brute force, permissions
- **Cryptography** (4): weak algorithms, key management, side-channel, certificate validation
- **Concurrency** (3): race conditions, TOCTOU, established patterns
- **Web/API** (5): CORS, CSRF, open redirect, resource exhaustion, API security
- **Supply Chain** (3): dependency confusion, code integrity, ML model files
- **Active Directory** (1): delegation, GPO abuse, RODC, SCCM/WSUS, ADCS, trust attacks

## MCP Servers

| Server | Purpose |
|--------|---------|
| mitm-search | Web search via mcp.mitm.vn |
| ida-multi-mcp | IDA Pro integration (decompile, rename, xrefs, patching) |
| jadx-mcp-server | Android APK decompilation and analysis |

## How It Works

1. Claude Code reads `CLAUDE.md` as the system prompt — sets offensive security persona
2. Skills activate contextually based on your question/task
3. Agents can be spawned as sub-agents for parallel or specialized work
4. Reference files are loaded on-demand when deeper vulnerability patterns are needed

## Customization

- Add new skills: create `skills/<name>/SKILL.md` with YAML frontmatter
- Add new agents: create `agents/<name>.md` with role description
- Add MCP servers: edit `mcpServers` in `settings.json`
- Modify permissions: edit `permissions.allow` in `settings.json`

## Requirements

- Claude Code CLI, Desktop App, or VS Code extension
- For MCP integrations: IDA Pro with ida-multi-mcp plugin, JADX with MCP server
