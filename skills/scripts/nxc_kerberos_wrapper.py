"""nxc + Kerberos auth without /etc/hosts edits or system clock changes.

Drops two shims into the Python process before exec'ing nxc:

  1. socket.getaddrinfo override — resolves AD realms / DC hostnames to a fixed
     IP map you provide. Lets nxc connect to <REALM>:88 (the KDC) and to
     <hostname>:445 (the target) without needing /etc/hosts (no sudo) or DNS.
  2. datetime / time.time patch — applies a fixed offset so Kerberos PA-ENC-
     TIMESTAMP pre-auth lands within the KDC's ±5min window when the Kali
     clock is wrong and you can't `sudo ntpdate`.

Used during the Lehack2024 engagement because (a) Kali had no passwordless
sudo so /etc/hosts edits were impossible, (b) the lab DC was 3 hours behind
Kali wall-clock. nxc would fail with `[Errno -2] Name or service not known`
on `<REALM>:88` lookups, and Kerberos AS-REQ would fail with
`KRB_AP_ERR_SKEW`. This wrapper makes nxc Just Work in that environment.

Usage:
    # 1. Mint a TGT (or other ccache) for the target user — usually via
    #    impacket-getTGT with -hashes or -aesKey.
    impacket-getTGT armorique.local/alambix -aesKey <AES256> -dc-ip 10.3.10.13
    # → writes alambix.ccache

    # 2. Set hosts + skew via env (or edit HOSTS below in-place).
    export NXC_HOSTS='armorique.local=10.3.10.13,village.armorique.local=10.3.10.13,village=10.3.10.13'
    export NXC_OFFSET=-10800              # seconds (negative = clock ahead of DC)
    export KRB5CCNAME=$PWD/alambix.ccache
    export KRB5_CONFIG=/tmp/krb5.conf     # optional; some impacket paths honor it

    # 3. Use exactly like nxc — every flag works:
    python3 nxc_kerberos_wrapper.py smb village.armorique.local -k --use-kcache --shares
    python3 nxc_kerberos_wrapper.py smb village.armorique.local -k --use-kcache --users
    python3 nxc_kerberos_wrapper.py ldap village.armorique.local -k --use-kcache --kerberoasting roast.txt

Config:
  NXC_HOSTS    comma-separated host=ip pairs (case-insensitive matching).
               Apply to BOTH the REALM-as-hostname KDC lookup and the target
               hostname for SMB/LDAP/etc.
  NXC_OFFSET   integer seconds added to the process clock. Negative when
               Kali is ahead of the DC.
  NXC_PATH     path to the nxc executable (default: /usr/bin/nxc)

Tested with nxc v1.4.x and impacket 0.14.0.dev0 on Kali Linux.
"""
import os
import socket
import sys
import datetime as _dt_mod
import time as _time_mod


def _parse_hosts(spec: str) -> dict:
    out = {}
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        name, ip = entry.split("=", 1)
        out[name.strip().lower()] = ip.strip()
    return out


HOSTS = _parse_hosts(os.environ.get("NXC_HOSTS", ""))
OFFSET = int(os.environ.get("NXC_OFFSET", "0"))
NXC_PATH = os.environ.get("NXC_PATH", "/usr/bin/nxc")


# --- clock-skew shim ----------------------------------------------------
if OFFSET:
    _REAL_DT = _dt_mod.datetime
    _real_time = _time_mod.time
    _time_mod.time = lambda: _real_time() + OFFSET

    class _DT(_REAL_DT):
        @classmethod
        def now(cls, tz=None):
            ts = _real_time() + OFFSET
            return _REAL_DT.fromtimestamp(ts, tz) if tz else _REAL_DT.fromtimestamp(ts)

        @classmethod
        def utcnow(cls):
            return _REAL_DT.utcfromtimestamp(_real_time() + OFFSET)

        @classmethod
        def fromtimestamp(cls, ts, tz=None):
            return _REAL_DT.fromtimestamp(ts, tz) if tz else _REAL_DT.fromtimestamp(ts)

    _dt_mod.datetime = _DT


# --- DNS shim -----------------------------------------------------------
if HOSTS:
    _real_gai = socket.getaddrinfo

    def _gai(host, *a, **kw):
        if isinstance(host, str):
            ip = HOSTS.get(host.lower())
            if ip:
                host = ip
        return _real_gai(host, *a, **kw)

    socket.getaddrinfo = _gai


# --- exec nxc -----------------------------------------------------------
if not os.path.exists(NXC_PATH):
    sys.stderr.write(f"error: nxc not found at {NXC_PATH}\n")
    sys.exit(2)

sys.argv = ["nxc"] + sys.argv[1:]
exec(compile(open(NXC_PATH).read(), NXC_PATH, "exec"))
