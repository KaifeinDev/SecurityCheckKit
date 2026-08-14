"""Step 4 wrapper: build_report.py + md_to_pdf.py in one call, runnable
standalone without Claude Code.

Usage:
    python3 report.py --before b.json --out-dir DIR \\
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
import sys

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
    parser.add_argument("--classification")
    parser.add_argument("--env")
    parser.add_argument("--scope")
    parser.add_argument("--overview")
    parser.add_argument("--client")
    parser.add_argument("--engagement-from")
    parser.add_argument("--engagement-to")
    parser.add_argument("--worksheet", help="Internal worksheet path; defaults to <project>/audit/worksheet.md")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--font", help="Passed through to md_to_pdf.py")
    parser.add_argument("--font-bold", help="Passed through to md_to_pdf.py")
    parser.add_argument("--skip-pdf", action="store_true", help="Only produce report.md, skip PDF conversion")
    args = parser.parse_args()

    py = find_report_python()

    build_cmd = [
        py, os.path.join(SCRIPTS_DIR, "build_report.py"),
        "--before", args.before, "--out-dir", args.out_dir,
    ]
    if args.classification:
        build_cmd += ["--classification", args.classification]
    if args.env:
        build_cmd += ["--env", args.env]
    for flag in ("scope", "overview", "client", "engagement_from", "engagement_to"):
        value = getattr(args, flag)
        if value:
            build_cmd += ["--" + flag.replace("_", "-"), value]
    # The worksheet is an internal companion document, so it defaults NEXT TO
    # the other internal notes (audit/) rather than into the delivery folder.
    worksheet = args.worksheet or os.path.join(
        os.path.dirname(os.path.abspath(args.out_dir)), "audit", "worksheet.md"
    )
    build_cmd += ["--worksheet", worksheet]
    # The worksheet carries internal-voice notes and the full per-finding dump.
    # If its directory is tracked, it ships with the client's code. Warn only —
    # .gitignore belongs to the client's project, not to this kit.
    worksheet_dir = os.path.dirname(os.path.abspath(worksheet))
    os.makedirs(worksheet_dir, exist_ok=True)
    if subprocess.run(
        ["git", "check-ignore", "-q", worksheet],
        cwd=worksheet_dir,
        capture_output=True,
    ).returncode != 0:
        print(
            f"警告：{worksheet} 未被 gitignore —— 工作底稿含內部語氣與全量明細，"
            "不應隨程式碼交付給甲方。請把該目錄加進專案的 .gitignore。",
            file=sys.stderr,
        )
    build_env = dict(os.environ)
    if args.font:
        build_env["SECURITY_SCAN_CJK_FONT"] = args.font
    # build_report.py's exit code carries the delivery-gate verdict (0 = Tier
    # 1/2 deliverable, 3/4 = internal-only report, 2 = validation error, see
    # its docstring). Tier 3/4 still produce a (watermarked) report + PDF for
    # internal tracking, so only a validation error aborts here.
    gate_code = subprocess.run(build_cmd, env=build_env).returncode
    if gate_code not in (0, 3, 4):
        raise SystemExit(gate_code)

    if args.skip_pdf:
        raise SystemExit(gate_code)

    md_path = os.path.join(args.out_dir, "report.md")
    pdf_path = os.path.join(args.out_dir, "report.pdf")
    pdf_cmd = [py, os.path.join(SCRIPTS_DIR, "md_to_pdf.py"), md_path, pdf_path]
    if args.font:
        pdf_cmd += ["--font", args.font]
    if args.font_bold:
        pdf_cmd += ["--font-bold", args.font_bold]
    subprocess.run(pdf_cmd, check=True)
    print(f"wrote {pdf_path}")
    raise SystemExit(gate_code)


if __name__ == "__main__":
    main()
