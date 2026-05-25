"""Scaffold a new pentest engagement directory with the report-writer-internalpen template.

Creates ./engagements/<client-slug>/<YYYY-MM-DD>/ with:
    engagement.yaml   metadata (client, scope, window, assessor)
    report.md         template seeded with front matter
    timeline.md       chronological event log (empty)
    hosts.csv         affected-hosts matrix (header only)
    evidence/         directory for command output, screenshots, etc.

If the target directory already exists, appends -2, -3, etc. to the date
folder so a re-kickoff doesn't clobber existing work.

Usage:
    python new_engagement.py --client "ACME Corp" --start 2026-05-22 \\
        --end 2026-05-30 --model "Grey Box" --assessor "Jesse Moore, OSCP"

The script prints the absolute path to the new engagement directory on
the last line of stdout so the caller can `cd` into it.
"""
import argparse
import re
import sys
from pathlib import Path


REPORT_TEMPLATE = """# Internal Network Penetration Test for {client}

**Engagement window:** {start} to {end} ({days} days)
**Testing model:** {model}
**Assessor:** {assessor}
**Report date:** {report_date}
**Version:** 0.1 (draft)

---

## Executive Summary

_To be completed at end of engagement._

## Methodology and Approach

The assessment followed the Orange Cyberdefense AD attack mindmap (2025-03)
as the primary playbook, supplemented by the OSSTMM and PTES frameworks
for non-AD portions of the scope. Phases applied to this engagement:

1. **Unauthenticated recon** — network sweep, LLMNR/NBT-NS/mDNS poisoning,
   anonymous SMB/LDAP/RPC enumeration, user enumeration via Kerberos,
   lockout-aware password spray.
2. **Initial foothold** — NTLM relay (SMB / LDAP / HTTP / ADCS), captured
   hash cracking, low-privilege shell from sprayed credentials.
3. **Authenticated enumeration** — BloodHound collection, ADCS template
   audit (Certipy), GPO and ACL review, SMB share trawl.
4. **Privilege escalation and lateral movement** — Kerberoasting,
   delegation abuse (constrained / unconstrained / RBCD), ADCS ESC1–15
   abuse, coercion-then-relay chains, DPAPI extraction, GPP cpassword,
   LAPS read.
5. **Domain dominance** — DCSync, Golden / Silver / Diamond ticket
   forging, krbtgt extraction, ACL persistence on tier-0 objects.

## Scope

- **In scope:** _<subnets, domains, hostnames>_
- **Out of scope:** _<explicit exclusions>_
- **Testing window:** {start} to {end}
- **Authorization:** _<SOW or rules-of-engagement reference>_

## Summary of Strengths

_To be completed as defensive observations accumulate._

## Summary of Findings

| Rating         | Count |
|----------------|-------|
| Critical       | 0     |
| High           | 0     |
| Medium         | 0     |
| Low            | 0     |
| Informational  | 0     |

### Risk Rating Definitions

- **Critical** — Direct, immediate, and comprehensive compromise of the environment is possible.
- **High** — Significant compromise possible with minimal additional effort or chained conditions.
- **Medium** — Compromise possible under specific conditions; meaningful uplift to attacker capability.
- **Low** — Limited impact; useful to an attacker only in combination with other issues.
- **Informational** — Hygiene or hardening recommendations with no direct exploitability.

### Findings Index

| ID  | Title | Rating | CVSSv4 |
|-----|-------|--------|--------|

---

## Detailed Findings

_Findings are appended here by the report-writer-internalpen agent as they are confirmed._

---

## Engagement Timeline

_See `timeline.md` for the running log. This section is regenerated on each capture._

---

## Host Vulnerability Matrix

_See `hosts.csv` for the source data. This table is regenerated on each capture._

| Host | IP | Findings | Highest Rating |
|------|-----|----------|----------------|

---

## Appendix A — Tools Used

| Tool             | Purpose                                          |
|------------------|--------------------------------------------------|
| NetExec (nxc)    | SMB/LDAP/WinRM enumeration, password spray       |
| Impacket suite   | Kerberos attacks, SMB relay, secretsdump         |
| BloodHound-CE    | AD attack-path mapping                           |
| Certipy-ad       | ADCS template enumeration and abuse              |
| Responder        | LLMNR/NBT-NS/mDNS poisoning                      |
| mitm6            | IPv6 DHCP / DNS takeover                         |
| Hashcat          | Offline hash cracking                            |

## Appendix B — OSINT Findings

_Not applicable to internal engagement._
"""

ENGAGEMENT_YAML_TEMPLATE = """client: "{client}"
client_slug: "{slug}"
start: {start}
end: {end}
model: "{model}"
assessor: "{assessor}"
status: "in-progress"
version: "0.1"
"""

HOSTS_CSV_HEADER = "host,ip,finding_id,proto,port\n"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "engagement"


def days_between(start: str, end: str) -> int:
    from datetime import date
    a = date.fromisoformat(start)
    b = date.fromisoformat(end)
    return max((b - a).days + 1, 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--client", required=True, help="Client name (will be slugified for path)")
    p.add_argument("--start", required=True, help="Engagement start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="Engagement end date YYYY-MM-DD")
    p.add_argument("--model", required=True, choices=["Black Box", "Grey Box", "White Box"])
    p.add_argument("--assessor", required=True, help='e.g. "Jesse Moore, OSCP"')
    p.add_argument("--root", default="engagements", help="Engagements root dir (default: engagements/)")
    args = p.parse_args()

    slug = slugify(args.client)
    root = Path(args.root).resolve()
    base = root / slug / args.start
    target = base
    suffix = 1
    while target.exists():
        suffix += 1
        target = base.with_name(f"{args.start}-{suffix}")

    (target / "evidence").mkdir(parents=True)
    days = days_between(args.start, args.end)
    from datetime import date

    (target / "report.md").write_text(
        REPORT_TEMPLATE.format(
            client=args.client,
            start=args.start,
            end=args.end,
            days=days,
            model=args.model,
            assessor=args.assessor,
            report_date=date.today().isoformat(),
        ),
        encoding="utf-8",
    )

    (target / "engagement.yaml").write_text(
        ENGAGEMENT_YAML_TEMPLATE.format(
            client=args.client,
            slug=slug,
            start=args.start,
            end=args.end,
            model=args.model,
            assessor=args.assessor,
        ),
        encoding="utf-8",
    )

    (target / "timeline.md").write_text(
        f"# Engagement Timeline — {args.client}\n\n"
        f"Started {args.start}. Append events below in `**YYYY-MM-DD HH:MM** — event description` format.\n\n",
        encoding="utf-8",
    )

    (target / "hosts.csv").write_text(HOSTS_CSV_HEADER, encoding="utf-8")

    sys.stdout.write(f"engagement scaffolded\n{target}\n")


if __name__ == "__main__":
    main()
