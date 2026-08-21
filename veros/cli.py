#!/usr/bin/env python3
"""Veros — smart contract security scan pipeline.

Subcommands:
    run      the whole pipeline end to end, with the AI drafting Step 2
    init     scaffold the audit/ markdown the report expects a human to write
    config   model and API key for the AI step
    docs     show the methodology that ships with Veros (scenario library, ...)
    doctor   Step 0 - environment health check (is this project scannable)
    scan     Step 1 - run Slither, filter to project source, collect env info
    triage   Step 2 - have a model draft the classification
    review   Step 2 - lint classification.json for the things a machine can check
    confirm  Step 2 - sign off on AI-drafted classifications, one by one
    report   Step 3 - build report.md + report.pdf from the scan artifacts

The A/B/C/D judgement itself (Step 2) stays human-confirmed by design (see
references/pitfalls.md and SKILL.md); `review` covers only the mechanical part
of it — duplicated justifications, missing required fields, High findings that
were downgraded or dismissed. Suppression comments are an optional CI-hygiene
follow-up, not a numbered step, and have no subcommand.

Everything Veros writes for a project lives under one directory, `audit/`:

    audit/scan/       Step 1 artifacts (results_before.json, scope.json, ...)
    audit/overview.md  written by the auditor, becomes the 摘要 chapter
    audit/scope_note.md   optional deviation disclosure
    audit/worksheet.md    internal working notes — NOT deliverable
    audit/report/      report.md + report.pdf — this is what ships

Only audit/report/ is meant to leave the building; the rest carries
internal-voice notes and the full per-finding dump.

Run `veros <subcommand> --help` for each step's own options.
"""
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

SUBCOMMANDS = {
    "run": "run.py",
    "init": "init_audit.py",
    "config": "config.py",
    "docs": "docs.py",
    "doctor": "env_check.py",
    "scan": "scan.py",
    "triage": "triage.py",
    "review": "review.py",
    "confirm": "confirm.py",
    "report": "report.py",
}

# `check` was this command's name before it became `doctor`. Kept working so a
# pinned CI job does not break on upgrade; undocumented, and not listed above.
ALIASES = {"check": "doctor"}


def main() -> None:
    argv = sys.argv[1:]
    sub = argv[0] if argv else None
    sub = ALIASES.get(sub, sub)

    if sub not in SUBCOMMANDS:
        print(__doc__)
        print(f"usage: veros <{'|'.join(SUBCOMMANDS)}> [args...]", file=sys.stderr)
        sys.exit(2)

    script_path = os.path.join(SCRIPTS_DIR, SUBCOMMANDS[sub])
    proc = subprocess.run([sys.executable, script_path, *argv[1:]])
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
