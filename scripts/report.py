"""Step 4 wrapper: build_report.py + md_to_pdf.py in one call, runnable
standalone without Claude Code.

Usage:
    python3 report.py --before b.json --after a.json --out-dir DIR \\
        [--classification c.json] [--env e.json] [--font path] [--skip-pdf]

`--classification` / `--env` are optional (see build_report.py docstring for
what happens when they're missing).

Note: build_report.py / md_to_pdf.py need fpdf2 + matplotlib, which per
references/pitfalls.md live in the system python, not the Slither venv (the
venv's pip has been broken before). Since an activated venv shadows `python3`
on PATH too, this script probes candidate interpreters for one that actually
has fpdf2 + matplotlib rather than trusting whichever python launched it.
Override with $SECURITY_SCAN_REPORT_PYTHON if none of the guesses fit.
"""
import argparse
import os
import shutil
import subprocess

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

_CANDIDATE_PYTHONS = [
    "/usr/bin/python3",
    "/usr/local/bin/python3",
    "/home/linuxbrew/.linuxbrew/bin/python3",
    "python3",
]


def find_report_python() -> str:
    override = os.environ.get("SECURITY_SCAN_REPORT_PYTHON")
    candidates = [override] if override else []
    candidates += _CANDIDATE_PYTHONS
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        resolved = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if not resolved or not os.path.isfile(resolved):
            continue
        probe = subprocess.run(
            [resolved, "-c", "import fpdf, matplotlib"], capture_output=True
        )
        if probe.returncode == 0:
            return resolved
    raise SystemExit(
        "No python with fpdf2 + matplotlib found (tried: "
        f"{', '.join(seen)}). Install them (`python3 -m pip install --user "
        "--break-system-packages fpdf2 matplotlib`) or set "
        "SECURITY_SCAN_REPORT_PYTHON to a python that has them."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--classification")
    parser.add_argument("--env")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--font", help="Passed through to md_to_pdf.py")
    parser.add_argument("--skip-pdf", action="store_true", help="Only produce report.md, skip PDF conversion")
    args = parser.parse_args()

    py = find_report_python()

    build_cmd = [
        py, os.path.join(SCRIPTS_DIR, "build_report.py"),
        "--before", args.before, "--after", args.after, "--out-dir", args.out_dir,
    ]
    if args.classification:
        build_cmd += ["--classification", args.classification]
    if args.env:
        build_cmd += ["--env", args.env]
    subprocess.run(build_cmd, check=True)

    if args.skip_pdf:
        return

    md_path = os.path.join(args.out_dir, "report.md")
    pdf_path = os.path.join(args.out_dir, "report.pdf")
    pdf_cmd = [py, os.path.join(SCRIPTS_DIR, "md_to_pdf.py"), md_path, pdf_path]
    if args.font:
        pdf_cmd += ["--font", args.font]
    subprocess.run(pdf_cmd, check=True)


if __name__ == "__main__":
    main()
