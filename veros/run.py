#!/usr/bin/env python3
"""Run the whole pipeline: doctor -> scan -> AI triage -> review -> report.

    veros run --src-prefix src/ --client "<甲方名稱>"

What comes out is a draft. Every classification the model wrote is tagged
`ai_drafted`, the gate refuses to grade the case as deliverable while those
tags remain, and the PDF says so on its first page. Turning that draft into
something you can hand over is a separate, human act:

    veros confirm --list        what still needs reading
    veros confirm <ids...>      sign off on the ones you have checked
    veros report                re-grade now that a person stands behind it

`doctor` failing stops the run — a project that does not compile produces a
scan of nothing, and a report from that is worse than no report. `review`
failing does not: it flags things worth a second look, which is exactly what
the human pass is for.
"""
import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def step(title: str, script: str, argv: list, fatal: bool = True) -> int:
    print(f"\n\033[1m▸ {title}\033[0m", file=sys.stderr)
    code = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, script), *argv]).returncode
    if code and fatal:
        sys.exit(f"\n{title} 失敗（exit {code}），流程中止。")
    return code


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--src-prefix", action="append", default=[], help="原始碼目錄，可重複，預設 src/")
    parser.add_argument("--exclude-path", action="append", default=[], help="排除的路徑前綴，可重複")
    parser.add_argument("--full-audit", action="store_true", help="連相依套件的發現也保留")
    parser.add_argument("--audit-dir", default="audit", help="所有產物的根目錄，預設 ./audit")
    parser.add_argument("--client", help="甲方名稱")
    parser.add_argument("--engagement-from")
    parser.add_argument("--engagement-to")
    parser.add_argument("--model", help="覆蓋 veros config 的模型設定")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--skip-doctor", action="store_true", help="跳過環境健檢")
    parser.add_argument("--skip-scenarios", action="store_true", help="AI 判讀時跳過情境庫比對")
    parser.add_argument("--include-false-positives", action="store_true")
    args = parser.parse_args()

    scan_dir = os.path.join(args.audit_dir, "scan")
    src_prefixes = args.src_prefix or ["src/"]

    if not args.skip_doctor:
        doctor_argv = []
        for p in src_prefixes:
            doctor_argv += ["--src-prefix", p]
        step("Step 0　環境健檢", "env_check.py", doctor_argv)

    scan_argv = ["--out-dir", scan_dir]
    for p in src_prefixes:
        scan_argv += ["--src-prefix", p]
    for p in args.exclude_path:
        scan_argv += ["--exclude-path", p]
    if args.full_audit:
        scan_argv.append("--full-audit")
    # A previous classification, if there is one, means only genuinely new
    # findings need the model's attention — and a human's afterwards.
    previous = os.path.join(scan_dir, "classification.json")
    if os.path.isfile(previous):
        scan_argv += ["--prev-classification", previous]
    step("Step 1　Slither 掃描", "scan.py", scan_argv)

    triage_argv = ["--scan-dir", scan_dir]
    if args.model:
        triage_argv += ["--model", args.model]
    if args.effort:
        triage_argv += ["--effort", args.effort]
    if args.skip_scenarios:
        triage_argv.append("--skip-scenarios")
    step("Step 2　AI 判讀（草稿）", "triage.py", triage_argv)

    step("Step 2　機械檢查", "review.py",
         ["--classification", os.path.join(scan_dir, "classification.json")], fatal=False)

    report_argv = ["--scan-dir", scan_dir, "--out-dir", os.path.join(args.audit_dir, "report")]
    for flag in ("client", "engagement_from", "engagement_to"):
        value = getattr(args, flag)
        if value:
            report_argv += ["--" + flag.replace("_", "-"), value]
    if args.include_false_positives:
        report_argv.append("--include-false-positives")
    gate = step("Step 3　產出報告", "report.py", report_argv, fatal=False)

    print(f"""
\033[1m完成 —— 但這份是草稿。\033[0m

分類判斷由模型產出，全部標記為未經人工確認，因此閘門不會判定為可交付
（本次 exit code {gate}）。分類是這份報告唯一的可信度來源，必須有人逐筆看過。

  veros confirm --list      看還有哪些待確認
  veros confirm <編號...>   確認你已讀過的
  veros report              重新評定

產物都在 {args.audit_dir}/ 底下，只有 {args.audit_dir}/report/ 可以交付。""", file=sys.stderr)
    sys.exit(gate)


if __name__ == "__main__":
    main()
