"""Fail `make security` on any high or critical npm advisory that is not an accepted risk.

`npm audit` alone cannot say "this one is dev-only and has no fix"; the file
docs/security/accepted-risks.json does, with the reason and a review date. Production dependencies
(`--omit=dev`) get no exceptions.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCEPTED = ROOT / "docs/security/accepted-risks.json"
BLOCKING = {"high", "critical"}


def advisories(audit: dict) -> set[tuple[str, str]]:
    """(advisory id, severity) of each high or critical advisory in an `npm audit --json` report."""
    found = set()
    for vulnerability in audit.get("vulnerabilities", {}).values():
        for via in vulnerability.get("via", []):
            if isinstance(via, dict) and via.get("severity") in BLOCKING:
                found.add((via["url"].rsplit("/", 1)[-1], via["severity"]))
    return found


def run_audit(*flags: str) -> dict:
    proc = subprocess.run(  # nosec B603 B607
        ["npm", "audit", "--json", *flags], cwd=ROOT / "frontend", capture_output=True, text=True
    )
    return json.loads(proc.stdout or "{}")


def check(production: dict, everything: dict, accepted: set[str]) -> list[str]:
    problems = [
        f"production dependency advisory {a} ({s})" for a, s in sorted(advisories(production))
    ]
    problems += [
        f"advisory {a} ({s}) is not in docs/security/accepted-risks.json"
        for a, s in sorted(advisories(everything))
        if a not in accepted
    ]
    return problems


def main() -> int:
    accepted = {item["advisory"] for item in json.loads(ACCEPTED.read_text())["npm"]}
    problems = check(run_audit("--omit=dev"), run_audit(), accepted)
    for problem in problems:
        print(f"npm audit: {problem}")
    if problems:
        return 1
    print(f"npm audit: no high or critical advisories (accepted and documented: {len(accepted)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
