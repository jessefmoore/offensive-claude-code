"""Run a command on an arbitrary SSH host with password auth (paramiko).

Generic sibling to kali_ssh.py for pivoting to lab targets whose creds we
recover mid-engagement. All config is positional/argv — nothing hardcoded.

Usage:
    python3 ssh_cmd.py <host> <user> <password> "<command>"
    echo "<command>" | python3 ssh_cmd.py <host> <user> <password>
"""
import sys
import paramiko

if len(sys.argv) < 4:
    sys.stderr.write("usage: ssh_cmd.py <host> <user> <password> [cmd]\n")
    sys.exit(2)

host, user, password = sys.argv[1], sys.argv[2], sys.argv[3]
cmd = " ".join(sys.argv[4:]) if sys.argv[4:] else sys.stdin.read()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, username=user, password=password,
          look_for_keys=False, allow_agent=False, timeout=15)
_, out, err = c.exec_command(cmd, timeout=120)
sys.stdout.write(out.read().decode("utf-8", "replace"))
e = err.read().decode("utf-8", "replace")
if e:
    sys.stderr.write(e)
rc = out.channel.recv_exit_status()
c.close()
sys.exit(rc)
