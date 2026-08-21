#!/usr/bin/env python3
"""Run the whole pipeline: doctor -> scan -> AI triage -> review -> report.

Two ways to get Step 2 done, depending on what you already pay for:

    veros run --src-prefix src/ --client "<甲方>"     # calls the API (needs a key)
    veros run --brief --src-prefix src/               # stops at the work order
    veros run --apply --client "<甲方>"                # resume once an agent finished it

A Claude Pro/Max subscription does not issue an API key, so `--brief` exists for
the case where the auditor is already paying for an agent: Veros writes the same
prompts to disk, that agent works through them, and `--apply` validates and
merges what comes back.

What comes out either way is a draft. Every classification the model wrote is
tagged `ai_drafted`, the gate refuses to grade the case as deliverable while
those tags remain, and the PDF says so on its first page:

    veros confirm --list        what still needs reading
    veros confirm <ids...>      sign off on the ones you have checked
    veros report                re-grade now that a person stands behind it

`doctor` failing stops the run — a project that does not compile produces a scan
of nothing, and a report from that is worse than no report. `review` failing
does not: it flags things worth a second look, which is what the human pass is
for.
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
    parser.add_argument(
        "--brief", action="store_true",
        help="不打 API：跑到產出判讀工單為止，交給你現有的 agent 完成"
             "（Claude Pro／Max 訂閱沒有 API key，這是給那種情況用的）",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="agent 完成工單後接續：套用結果 → review → report",
    )
    parser.add_argument("--skip-doctor", action="store_true", help="跳過環境健檢")
    parser.add_argument("--skip-scenarios", action="store_true", help="AI 判讀時跳過情境庫比對")
    parser.add_argument("--include-false-positives", action="store_true")
    args = parser.parse_args()

    scan_dir = os.path.join(args.audit_dir, "scan")
    classification = os.path.join(scan_dir, "classification.json")
    src_prefixes = args.src_prefix or ["src/"]

    def finish():
        """Steps 2b and 3 — shared by the API path and the --apply resume."""
        step("Step 2　機械檢查", "review.py", ["--classification", classification], fatal=False)

        report_argv = ["--scan-dir", scan_dir, "--out-dir", os.path.join(args.audit_dir, "report")]
        for flag in ("client", "engagement_from", "engagement_to"):
            value = getattr(args, flag)
            if value:
                report_argv += ["--" + flag.replace("_", "-"), value]
        if args.include_false_positives:
            report_argv.append("--include-false-positives")
        gate = step("Step 3　產出報告", "report.py", report_argv, fatal=False)

        # Exit 2 is a validation failure: no report was written at all. Telling
        # someone their draft is ready and pointing them at `veros confirm`
        # would be a lie about a file that does not exist.
        if gate == 2:
            print(f"""
\033[1m未產出報告。\033[0m

classification.json 未通過驗證（exit 2），逐筆錯誤列在上方。修正後重跑：

  veros report

驗證是刻意擋在產出之前的 —— 對不上掃描結果的分類會讓報告的數字失去意義。""", file=sys.stderr)
            sys.exit(gate)

        print(f"""
\033[1m完成 —— 但這份是草稿。\033[0m

分類判斷由模型產出，全部標記為未經人工確認，因此閘門不會判定為可交付
（本次 exit code {gate}）。分類是這份報告唯一的可信度來源，必須有人逐筆看過。

  veros confirm --list      看還有哪些待確認
  veros confirm <編號...>   確認你已讀過的
  veros report              重新評定

產物都在 {args.audit_dir}/ 底下，只有 {args.audit_dir}/report/ 可以交付。""", file=sys.stderr)
        sys.exit(gate)

    # Resuming after an agent worked through the brief: the scan already ran.
    if args.apply:
        step("Step 2　套用工單結果", "triage.py", ["--scan-dir", scan_dir, "--apply-brief"])
        finish()

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
    if os.path.isfile(classification):
        scan_argv += ["--prev-classification", classification]
    step("Step 1　Slither 掃描", "scan.py", scan_argv)

    if args.brief:
        brief_argv = ["--scan-dir", scan_dir, "--emit-brief"]
        if args.skip_scenarios:
            brief_argv.append("--skip-scenarios")
        step("Step 2　產出判讀工單", "triage.py", brief_argv)
        brief_dir = os.path.join(scan_dir, "brief")
        print(f"""
\033[1m工單已就緒 —— 接下來由你的 agent 執行。\033[0m

  1. 讓 agent 讀 {brief_dir}/README.md，逐份完成 task-*.md，
     結果寫進 {brief_dir}/results/
  2. veros run --apply --client "<甲方名稱>"

工單已含原始碼、情境庫與 schema，不需要 API key。""", file=sys.stderr)
        return

    triage_argv = ["--scan-dir", scan_dir]
    if args.model:
        triage_argv += ["--model", args.model]
    if args.effort:
        triage_argv += ["--effort", args.effort]
    if args.skip_scenarios:
        triage_argv.append("--skip-scenarios")
    step("Step 2　AI 判讀（草稿）", "triage.py", triage_argv)

    finish()


if __name__ == "__main__":
    main()
