#!/usr/bin/env python3
"""Single entry point for the security-scan pipeline's automatable steps —
usable by anyone with Python 3, Foundry, and Slither installed, no Claude
Code required.

Subcommands (each maps 1:1 to a SKILL.md step):
    check   Step 0 - environment health check
    scan    Step 1 - run Slither, filter to project source, collect env info
    review  Step 2 - lint classification.json for the things a machine can check
    report  Step 3 - build report.md + report.pdf from scan/classification artifacts

The A/B/C/D judgement itself (Step 2) stays human-confirmed by design (see
references/pitfalls.md and SKILL.md); `review` covers only the mechanical part
of it — duplicated justifications, missing required fields, High findings that
were downgraded or dismissed. Suppression comments are an optional CI-hygiene
follow-up, not a numbered step, and have no subcommand.

Run `python3 cli.py <subcommand> --help` for each step's own options.
"""
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

SUBCOMMANDS = {
    "check": "env_check.py",
    "scan": "scan.py",
    "review": "review.py",
    "report": "report.py",
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(__doc__)
        print(f"usage: cli.py <{'|'.join(SUBCOMMANDS)}> [args...]", file=sys.stderr)
        sys.exit(2)

    sub = sys.argv[1]
    script_path = os.path.join(SCRIPTS_DIR, SUBCOMMANDS[sub])
    proc = subprocess.run([sys.executable, script_path, *sys.argv[2:]])
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
