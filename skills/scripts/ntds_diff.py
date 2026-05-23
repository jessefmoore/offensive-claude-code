"""Cross-forest / cross-dump NT-hash collision audit.

Given two `impacket-secretsdump` (or `nxc --ntds`) output files, report:
  - Cross-dump NT-hash collisions: same NT in BOTH dumps → same plaintext password
    unlocks both identities (single credential pivot, no trust required)
  - Intra-dump collisions: same NT used by multiple users WITHIN one dump
    (shared service-account passwords, copy-paste provisioning errors)

Both have caused real Lehack2024-class findings; they're easy to miss without a
mechanical diff because operators eyeball NTDS by user name, not by hash.

Usage:
    python ntds_diff.py forestA.ntds forestB.ntds
    python ntds_diff.py forestA.ntds forestB.ntds --include-machine

Excludes machine accounts (`<name>$`) by default — they have host-unique
secrets and noise the output. Pass --include-machine to keep them.

Excludes the well-known empty-password NT (31d6cfe0d16ae931b73c59d7e0c089c0)
which all disabled-no-password accounts share.

Input format expected (impacket / nxc --ntds):
    [domain\]user:rid:LM:NT:::
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

EMPTY_NT = "31d6cfe0d16ae931b73c59d7e0c089c0"


def load(path: Path, include_machine: bool) -> dict[str, list[str]]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for line in path.read_text(errors="replace").splitlines():
        parts = line.strip().split(":")
        if len(parts) < 4:
            continue
        user = parts[0].rsplit("\\", 1)[-1]  # strip "domain\" prefix if present
        nt = parts[3].lower()
        if not include_machine and user.endswith("$"):
            continue
        if nt == EMPTY_NT:
            continue
        by_hash[nt].append(user)
    return by_hash


def label(path: Path) -> str:
    # short label from the filename — strip extension and timestamp-y suffix
    return path.stem.split("_")[0] or path.stem


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump_a")
    ap.add_argument("dump_b")
    ap.add_argument("--include-machine", action="store_true", help="Include $-suffix machine accounts")
    args = ap.parse_args()

    pa, pb = Path(args.dump_a), Path(args.dump_b)
    la, lb = label(pa), label(pb)
    a = load(pa, args.include_machine)
    b = load(pb, args.include_machine)

    a_total = sum(len(v) for v in a.values())
    b_total = sum(len(v) for v in b.values())
    print(f"{la:<20s}  users: {a_total:4d}  unique hashes: {len(a)}")
    print(f"{lb:<20s}  users: {b_total:4d}  unique hashes: {len(b)}")
    print()

    print("=== Cross-dump NT hash collisions (same plaintext password in BOTH) ===")
    print(f"{'NT hash':34s}  {la:30s} <-> {lb}")
    print("-" * 120)
    common = sorted(set(a) & set(b))
    cross_hits = 0
    for h in common:
        cross_hits += 1
        ra = ",".join(a[h])
        rb = ",".join(b[h])
        print(f"{h}  {ra:30s} <-> {rb}")
    if not cross_hits:
        print("(none)")
    print()

    print("=== Intra-dump collisions (same NT, multiple users WITHIN one dump) ===")
    intra_hits = 0
    for tag, m in [(la, a), (lb, b)]:
        for h, users in m.items():
            if len(users) > 1:
                intra_hits += 1
                print(f"  {tag:20s}  {h}  {users}")
    if not intra_hits:
        print("(none)")

    print()
    print(f"Summary: {cross_hits} cross-dump collision(s), {intra_hits} intra-dump collision(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
