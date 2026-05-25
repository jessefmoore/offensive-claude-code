"""HTB API v4 helper — machine info, flag submission, and KB cross-reference.

Reads credentials from env vars or sibling .env file (same pattern as kali_ssh.py).
Base URL: https://labs.hackthebox.com/api/v4

Configuration:
    HTB_API_KEY   Your HTB API key (Profile → Settings → API Key)

Env vars take precedence over .env file values.

Usage:
    python htb_api.py active              # Show active machine + IP (spawn first in browser)
    python htb_api.py info <name>         # Machine details + KB hints
    python htb_api.py search <name>       # Search machines by name (paginated scan)
    python htb_api.py flag <value>        # Submit user or root flag
    python htb_api.py flag <value> --difficulty 70
    python htb_api.py hints [name]        # KB cross-reference for active or named machine

NOTE: Spawn, stop, and reset are not available via the HTB API v4.
      Use the browser at https://app.hackthebox.com/machines/<name>
      Then run `active` here to get the IP.

Requires: requests (pip install requests)
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.stderr.write("error: requests not installed — run: pip install requests\n")
    sys.exit(2)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "https://labs.hackthebox.com/api/v4"
SCRIPT_DIR = Path(__file__).parent
KB_INDEX = SCRIPT_DIR.parent.parent / "kb" / "htb" / "0xdf-machine-index.md"


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


file_env = load_env_file(SCRIPT_DIR / ".env")
API_KEY = cfg("HTB_API_KEY", file_env)

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
})


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def api_get(path: str, params: dict = None) -> dict:
    r = SESSION.get(f"{BASE_URL}{path}", params=params, timeout=15)
    if r.status_code == 401:
        sys.stderr.write("error: HTB_API_KEY is invalid or expired\n")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


def api_post(path: str, body: dict = None) -> dict:
    r = SESSION.post(f"{BASE_URL}{path}", json=body or {}, timeout=15)
    if r.status_code == 401:
        sys.stderr.write("error: HTB_API_KEY is invalid or expired\n")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Machine helpers
# ---------------------------------------------------------------------------
def get_active_machine() -> dict | None:
    """Return the active machine dict or None."""
    data = api_get("/machine/active")
    return data.get("info")


def get_machine_profile(name_or_id: str | int) -> dict | None:
    """Look up a machine by name or ID. Returns info dict or None."""
    try:
        data = api_get(f"/machine/profile/{name_or_id}")
        return data.get("info")
    except requests.HTTPError:
        return None


def search_machines_paginated(term: str, max_pages: int = 5) -> list[dict]:
    """Scan paginated machine list for name matches."""
    term_lower = term.lower()
    matches = []
    for page in range(1, max_pages + 1):
        try:
            data = api_get("/machine/paginated", params={"per_page": 100, "page": page})
        except requests.HTTPError:
            break
        machines = data.get("data", [])
        if not machines:
            break
        for m in machines:
            if term_lower in m.get("name", "").lower():
                matches.append(m)
    return matches


def fmt_machine(m: dict, prefix: str = "") -> str:
    """Format a machine dict for display."""
    lines = []
    name = m.get("name", "?")
    os_name = m.get("os", "?")
    diff = m.get("difficultyText", m.get("difficulty", "?"))
    mid = m.get("id", "?")
    points = m.get("points") or m.get("static_points")
    ip = m.get("ip")

    # playInfo may be nested
    play = m.get("playInfo", {})
    is_spawned = play.get("isSpawned", False)
    is_active = play.get("isActive", False)
    expires = play.get("expires_at")

    user_owned = m.get("authUserInUserOwns", False)
    root_owned = m.get("authUserInRootOwns", False)

    lines.append(f"{prefix}Name       : {name}")
    lines.append(f"{prefix}ID         : {mid}")
    lines.append(f"{prefix}OS         : {os_name}")
    lines.append(f"{prefix}Difficulty : {diff}")
    if points:
        lines.append(f"{prefix}Points     : {points}")
    if ip:
        lines.append(f"{prefix}IP         : {ip}")
    if is_spawned or is_active:
        lines.append(f"{prefix}Status     : SPAWNED{' (expires: ' + str(expires) + ')' if expires else ''}")
    owned = []
    if user_owned:
        owned.append("user")
    if root_owned:
        owned.append("root")
    if owned:
        lines.append(f"{prefix}Owned      : {', '.join(owned)}")

    labels = [lb.get("name", "") for lb in m.get("labels", [])]
    if labels:
        lines.append(f"{prefix}Labels     : {', '.join(labels)}")

    lines.append(f"{prefix}Browser    : https://app.hackthebox.com/machines/{name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# KB cross-reference
# ---------------------------------------------------------------------------
def kb_hints(machine_name: str) -> str:
    """Search the local 0xdf machine index for technique hints."""
    if not KB_INDEX.is_file():
        return "(kb/htb/0xdf-machine-index.md not found)"

    text = KB_INDEX.read_text(encoding="utf-8", errors="ignore")
    target = machine_name.lower()
    hints = []

    for line in text.splitlines():
        if target in line.lower() and "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 3:
                hints.append(line.strip())

    output = []
    if hints:
        output.append(f"0xdf index entries for '{machine_name}':")
        for h in hints[:5]:
            output.append(f"  {h}")
    else:
        output.append(f"'{machine_name}' not in local index (new machine — no 0xdf tags yet)")

    output.append("")
    output.append("Foothold patterns : kb/htb/foothold-patterns.md")
    output.append("HTB methodology   : skills/htb/SKILL.md")
    return "\n".join(output)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_active(_args):
    m = get_active_machine()
    if not m:
        print("No machine currently active.")
        print("Spawn one at: https://app.hackthebox.com/machines")
        return

    print("=== Active Machine ===")
    print(fmt_machine(m))
    print()

    name = m.get("name", "")
    ip = m.get("ip")
    if not ip:
        # Try full profile for IP
        profile = get_machine_profile(m.get("id", name))
        if profile:
            ip = profile.get("ip")
            if ip:
                print(f"IP (from profile): {ip}")

    print()
    print("=== KB Hints ===")
    print(kb_hints(name))


def cmd_info(args):
    # Try direct profile lookup by name first (fast)
    machine = get_machine_profile(args.name)
    if not machine:
        # Fall back to paginated scan
        results = search_machines_paginated(args.name)
        if not results:
            print(f"No machines found matching '{args.name}'")
            sys.exit(1)
        # Prefer exact match
        exact = [r for r in results if r.get("name", "").lower() == args.name.lower()]
        machine = exact[0] if exact else results[0]

    print(f"=== Machine: {machine.get('name')} ===")
    print(fmt_machine(machine))
    print()
    print("=== KB Hints ===")
    print(kb_hints(machine.get("name", "")))


def cmd_search(args):
    results = search_machines_paginated(args.term)
    if not results:
        print(f"No machines found matching '{args.term}'")
        return
    print(f"{'Name':<20} {'OS':<10} {'Difficulty':<12} {'ID':<6} {'Owned'}")
    print("-" * 60)
    for m in results[:25]:
        name = m.get("name", "?")
        os_name = m.get("os", "?")
        diff = str(m.get("difficultyText", m.get("difficulty", "?")))
        mid = str(m.get("id", "?"))
        user_done = "U" if m.get("authUserInUserOwns") else "."
        root_done = "R" if m.get("authUserInRootOwns") else "."
        print(f"{name:<20} {os_name:<10} {diff:<12} {mid:<6} {user_done}{root_done}")


def cmd_flag(args):
    flag_value = args.value.strip()
    if not flag_value:
        sys.stderr.write("error: flag value is empty\n")
        sys.exit(1)

    m = get_active_machine()
    if not m:
        sys.stderr.write("error: no active machine — spawn one in the browser first\n")
        sys.exit(1)

    mid = m["id"]
    name = m.get("name", "?")
    difficulty = args.difficulty

    print(f"Submitting flag for {name} (difficulty: {difficulty}/100)...")
    try:
        resp = api_post("/machine/own", {
            "id": mid,
            "flag": flag_value,
            "difficulty": difficulty,
        })
        msg = resp.get("message", "")
        success = resp.get("success", 1) != 0

        if success and "Incorrect" not in msg:
            flag_type = "ROOT" if resp.get("type") == "root" or "root" in msg.lower() else "USER"
            print(f"[+] {flag_type} FLAG CORRECT — {name}")
            print(f"    {msg}")
        else:
            print(f"[-] Incorrect flag: {msg}")
            sys.exit(1)
    except requests.HTTPError as e:
        body = e.response.text
        try:
            body = json.loads(body).get("message", body)
        except Exception:
            pass
        # 500 with "Incorrect Flag" is expected for wrong flags
        if "Incorrect" in body:
            print(f"[-] Incorrect flag")
        else:
            sys.stderr.write(f"error: {e.response.status_code} — {body}\n")
        sys.exit(1)


def cmd_hints(args):
    name = getattr(args, "name", None)
    if not name:
        m = get_active_machine()
        if not m:
            print("No active machine. Pass machine name: python htb_api.py hints <name>")
            sys.exit(0)
        name = m.get("name", "")
    print(f"=== KB Hints: {name} ===")
    print(kb_hints(name))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HTB API v4 helper — machine info and flag submission",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("active", help="Show active machine + IP")

    p_info = sub.add_parser("info", help="Look up machine by name")
    p_info.add_argument("name")

    p_search = sub.add_parser("search", help="Search machines by name")
    p_search.add_argument("term")

    p_flag = sub.add_parser("flag", help="Submit a flag for the active machine")
    p_flag.add_argument("value", help="Flag hash string")
    p_flag.add_argument("--difficulty", type=int, default=50, metavar="1-100")

    p_hints = sub.add_parser("hints", help="KB cross-reference for active or named machine")
    p_hints.add_argument("name", nargs="?", default=None)

    args = parser.parse_args()
    dispatch = {
        "active": cmd_active,
        "info": cmd_info,
        "search": cmd_search,
        "flag": cmd_flag,
        "hints": cmd_hints,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
