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
    parser.add_argument(
        "--scan-dir",
        help="Step 1 的 --out-dir。由它推出 --before/--classification/--env/--scope 的"
             "預設路徑（results_before.json / classification.json / scan_env.json / "
             "scope.json），四者仍可個別指定覆蓋。找不到的檔案就當作未提供",
    )
    parser.add_argument(
        "--before",
        help="Step 1 的 results_before.json：本次掃描過濾後的發現，報告的事實來源。"
             "未指定時取自 --scan-dir",
    )
    parser.add_argument(
        "--classification",
        help="Step 2 的 classification.json：逐筆的處置分類與判斷依據。"
             "省略時不列發現明細、不評等級（exit 3）",
    )
    parser.add_argument(
        "--env",
        help="Step 1 的 scan_env.json：工具鏈與相依套件版本，用於報告的受檢版本欄位",
    )
    parser.add_argument(
        "--scope",
        help="Step 1 的 scope.json：受檢檔案清單、行數與 SHA-256。"
             "這是報告的效力邊界，省略時該節註明未提供",
    )
    parser.add_argument(
        "--overview",
        help="markdown，內嵌為「摘要」章的協定理解：協定怎麼運作、資產保管、角色與權限",
    )
    parser.add_argument(
        "--scope-note",
        help="markdown，接在「檢測範圍與方法」章末尾：本次偏離標準程序之處"
             "（例如為了讓工具跑起來暫時改過原始碼，使部分檔案雜湊與交付版本不符）",
    )
    parser.add_argument("--client", help="甲方名稱，出現在封面與報告標題")
    parser.add_argument("--engagement-from", help="檢測期間起日（YYYY-MM-DD）")
    parser.add_argument("--engagement-to", help="檢測期間迄日（YYYY-MM-DD）")
    parser.add_argument(
        "--worksheet",
        help="內部工作底稿的輸出路徑。含內部語氣與全量逐筆明細，不可交付甲方；"
             "預設寫到 <專案>/audit/worksheet.md 而非 --out-dir",
    )
    parser.add_argument(
        "--out-dir", default="security-scan-report",
        help="report.md 與 report.pdf 的輸出目錄（交付物）。預設 ./security-scan-report —— "
             "刻意與工作底稿所在的 audit/ 分開，那裡放的是不可交付的內部文件",
    )
    parser.add_argument("--font", help="指定 CJK 字型檔；省略時自動偵測（見 md_to_pdf.py）")
    parser.add_argument("--font-bold", help="指定粗體字型檔；省略時找同目錄的 Bold 檔")
    parser.add_argument(
        "--include-false-positives", action="store_true",
        help="把經查證為誤報（C）的發現也逐筆列進報告；預設不列",
    )
    parser.add_argument("--skip-pdf", action="store_true", help="只產 report.md，跳過 PDF")
    args = parser.parse_args()

    # --scan-dir fills in whatever was not named explicitly. Step 1 writes all
    # four files into one directory under fixed names, so repeating each path
    # on every report call was busywork that also invited mixing runs.
    if args.scan_dir:
        for flag, filename in (
            ("before", "results_before.json"),
            ("classification", "classification.json"),
            ("env", "scan_env.json"),
            ("scope", "scope.json"),
        ):
            if not getattr(args, flag):
                candidate = os.path.join(args.scan_dir, filename)
                if os.path.isfile(candidate):
                    setattr(args, flag, candidate)
    if not args.before:
        parser.error("需要 --before，或用 --scan-dir 指向 Step 1 的輸出目錄")

    py = find_report_python()

    build_cmd = [
        py, os.path.join(SCRIPTS_DIR, "build_report.py"),
        "--before", args.before, "--out-dir", args.out_dir,
    ]
    if args.classification:
        build_cmd += ["--classification", args.classification]
    if args.env:
        build_cmd += ["--env", args.env]
    for flag in ("scope", "overview", "scope_note", "client", "engagement_from", "engagement_to"):
        value = getattr(args, flag)
        if value:
            build_cmd += ["--" + flag.replace("_", "-"), value]
    if args.include_false_positives:
        build_cmd.append("--include-false-positives")
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
