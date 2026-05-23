"""Run a shell command on a remote SSH host (typically a lab Kali) via paramiko.

Used when Windows OpenSSH can't supply a password non-interactively.

Configuration (no defaults — must be provided):
    KALI_HOST   target hostname/IP
    KALI_USER   username
    KALI_PASS   password
    KALI_PORT   ssh port (optional, default 22)
    KALI_TIMEOUT  remote command timeout in seconds (optional, default 600)

Values are read from process env first, then from a sibling .env file
(`skills/scripts/.env`, gitignored). See `.env.example` for the format.

Usage:
    python kali_ssh.py "whoami; ip -4 -br addr"
    echo "long command" | python kali_ssh.py
"""
import os, sys, paramiko
from pathlib import Path


def load_env_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def cfg(key: str, file_env: dict, required: bool = True, default=None):
    val = os.environ.get(key) or file_env.get(key) or default
    if required and not val:
        sys.stderr.write(f"error: {key} not set (env var or .env file)\n")
        sys.exit(2)
    return val


file_env = load_env_file(Path(__file__).with_name(".env"))

HOST = cfg("KALI_HOST", file_env)
USER = cfg("KALI_USER", file_env)
PASS = cfg("KALI_PASS", file_env)
PORT = int(cfg("KALI_PORT", file_env, required=False, default="22"))
TIMEOUT = int(cfg("KALI_TIMEOUT", file_env, required=False, default="600"))

cmd = " ".join(sys.argv[1:]) if sys.argv[1:] else sys.stdin.read()
if not cmd.strip():
    sys.stderr.write("error: no command provided (pass as args or stdin)\n")
    sys.exit(2)

# Force UTF-8 on stdout/stderr — Kali tools emit Unicode (box-drawing,
# arrows, emoji) that the default Windows cp1252 console cannot encode.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASS,
          look_for_keys=False, allow_agent=False, timeout=15)

_, stdout, stderr = c.exec_command(cmd, get_pty=False, timeout=TIMEOUT)
sys.stdout.write(stdout.read().decode("utf-8", "replace"))
err = stderr.read().decode("utf-8", "replace")
if err:
    sys.stderr.write(err)
sys.exit(stdout.channel.recv_exit_status())
