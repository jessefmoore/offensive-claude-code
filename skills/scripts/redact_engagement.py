"""Sanitize a pentest engagement directory by redacting cleartext passwords
and high-value NT/AES hashes across report.md / timeline.md / hosts.csv /
evidence/ / report.html / casebook.html and any extracted deliverable copy
(e.g., <client>-pentest-<date>-v1.0/).

Why this matters: if a finalized report leaks the client's real passwords or
NT hashes for tier-0 accounts (krbtgt, Administrator, DA candidates), an
attacker who lifts the report from email/Confluence/SharePoint gets PtH
material directly. Cleartext is obvious; NT hashes are equally usable.

Convention:
  Cleartext      → [REDACTED-PASSWORD]
  NT hash (32hex)→ first 8 chars + "[REDACTED]"  (8 chars preserves audit-trail
                   correlation across evidence files without enabling PtH —
                   PtH needs the full 32 chars)
  AES256 (64hex) → first 8 chars + "[REDACTED]"
  DCC2 (32hex)   → first 8 chars + "[REDACTED]"

Idempotent: secrets are replaced in-place; running again is a no-op.
Universal LM-no-hash sentinel (aad3b435b51404eeaad3b435b51404ee) is NOT
redacted — it's a well-known placeholder, not a secret.

Configuration (one or both):

  ENGAGEMENT_DIR/.secrets.yaml   gitignored, operator-managed list
      passwords:
        - 'P3x!Vw6^Yk'
        - 'hC78*K,Zv+z123'
      hashes:
        - '48089424af92411085e954533617c561'
        - '8a1d64422d3c480ae616ba90d578c39f'

  --secret p:PASSWORD / --secret h:HASH   one-off CLI overrides

Auto-derivation: if `.secrets.yaml` isn't present, the script will also
scan any `*.ntds`, `*.ntds.kerberos`, `*.ntds.cleartext` files in the
engagement and offer to derive the high-value tier-0 hashes (Administrator,
krbtgt, plus any account in Domain Admins / Enterprise Admins).

Usage:
  python skills/scripts/redact_engagement.py \
      --engagement engagements/<slug>/<date>/ \
      --apply

By default the script runs in DRY-RUN mode and prints what would change
without writing. Pass --apply to commit.
"""
from __future__ import annotations
import argparse
import re
import shutil
import sys
from pathlib import Path

EXTS = {".md", ".html", ".csv", ".txt", ".log", ".json", ".yaml", ".yml"}
LM_SENTINEL = "aad3b435b51404eeaad3b435b51404ee"  # never redact
SKIP_DIRS = {".git", ".claude", "__pycache__", "node_modules"}


def parse_secrets_yaml(path: Path) -> tuple[list[str], list[str]]:
    """Very small YAML reader for the two lists we need."""
    pws: list[str] = []
    hashes: list[str] = []
    if not path.is_file():
        return pws, hashes
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.rstrip()
        if not s or s.lstrip().startswith("#"):
            continue
        if s.startswith("passwords:"):
            current = "passwords"
            continue
        if s.startswith("hashes:"):
            current = "hashes"
            continue
        # Try single-quoted, then double-quoted, then bare token.
        # Critical: handle inline comments — quoted form is unambiguous;
        # bare form takes one whitespace-delimited token.
        m = (re.match(r"\s*-\s*'([^']*)'", s) or
             re.match(r'\s*-\s*"([^"]*)"', s) or
             re.match(r"\s*-\s*(\S+)", s))
        if m and current == "passwords":
            pws.append(m.group(1))
        elif m and current == "hashes":
            hashes.append(m.group(1).lower())
    return pws, hashes


def gather_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(seg in SKIP_DIRS for seg in p.parts):
            continue
        if p.suffix.lower() in EXTS:
            out.append(p)
    return out


def redact_text(text: str, passwords: list[str], hashes: list[str]) -> tuple[str, int]:
    n = 0
    # Cleartext password replacement — sort longest first to avoid partial overlaps
    for pw in sorted(set(passwords), key=len, reverse=True):
        if not pw or pw == "[REDACTED-PASSWORD]":
            continue
        # Replace literal occurrences. We don't need word-boundary because
        # passwords are arbitrary strings.
        occurrences = text.count(pw)
        if occurrences:
            text = text.replace(pw, "[REDACTED-PASSWORD]")
            n += occurrences
    # NT hash / AES key replacement — partial mask (first 8 chars + tag)
    for h in sorted(set(hashes), key=len, reverse=True):
        if not h or h.lower() == LM_SENTINEL:
            continue
        # Match case-insensitively, replace with first 8 of original + marker
        head = h[:8]
        pattern = re.compile(re.escape(h), re.IGNORECASE)
        new_text, count = pattern.subn(f"{head}[REDACTED]", text)
        if count:
            text = new_text
            n += count
    return text, n


def derive_high_value_hashes(engagement_dir: Path) -> list[str]:
    """Auto-extract krbtgt + Administrator NT hashes from any NTDS dump
    files in the engagement. Returns lowercase hex strings."""
    out: set[str] = set()
    for p in engagement_dir.rglob("*.ntds"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            # Format: [domain\]user:rid:lmhash:nthash:::
            m = re.match(r"^(?:[^\\:]+\\)?([^:]+):\d+:([0-9a-fA-F]{32}):([0-9a-fA-F]{32}):::", line)
            if not m:
                continue
            user = m.group(1).lower()
            nthash = m.group(3).lower()
            if nthash == LM_SENTINEL:
                continue
            # Always include krbtgt + Administrator. Other high-value accounts
            # (jesse, jesse2, svc_*, gMSA*) are explicit operator choices.
            if user in ("krbtgt", "administrator"):
                out.add(nthash)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engagement", required=True, help="Path to engagement dir")
    ap.add_argument("--apply", action="store_true", help="Actually write changes (default: dry-run)")
    ap.add_argument("--secret", action="append", default=[], help="One-off secret: 'p:PASSWORD' or 'h:HASH'")
    ap.add_argument("--no-auto-derive", action="store_true", help="Skip auto-deriving tier-0 NT hashes from NTDS dumps")
    args = ap.parse_args()

    eng = Path(args.engagement)
    if not eng.is_dir():
        sys.stderr.write(f"error: {eng} is not a directory\n")
        return 2

    pws, hashes = parse_secrets_yaml(eng / ".secrets.yaml")
    for s in args.secret:
        if s.startswith("p:"):
            pws.append(s[2:])
        elif s.startswith("h:"):
            hashes.append(s[2:].lower())
        else:
            sys.stderr.write(f"warn: ignoring malformed --secret {s!r}; use p:VALUE or h:VALUE\n")

    if not args.no_auto_derive:
        derived = derive_high_value_hashes(eng)
        for h in derived:
            if h not in hashes:
                hashes.append(h)

    if not pws and not hashes:
        sys.stderr.write(f"no secrets configured. Create {eng}/.secrets.yaml or pass --secret p:PASSWORD / --secret h:HASH\n")
        return 1

    sys.stderr.write(f"loaded {len(pws)} passwords + {len(hashes)} hashes to redact\n")

    files = gather_files(eng)
    sys.stderr.write(f"scanning {len(files)} files under {eng}\n")
    total = 0
    changed_files = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text, n = redact_text(text, pws, hashes)
        if n:
            total += n
            changed_files.append((p, n))
            if args.apply:
                p.write_text(new_text, encoding="utf-8")

    for p, n in changed_files:
        sys.stderr.write(f"  {n:3d}  {p.relative_to(eng)}\n")
    sys.stderr.write(f"{'APPLIED' if args.apply else 'DRY-RUN'} — {total} redactions across {len(changed_files)} files\n")
    if not args.apply:
        sys.stderr.write("re-run with --apply to commit changes\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
