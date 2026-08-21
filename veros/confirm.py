#!/usr/bin/env python3
"""Mark AI-drafted classifications as reviewed by a person.

`veros run` fills classification.json with a model's judgement and tags every
entry `ai_drafted`. While any of those tags remain, the delivery gate refuses
to grade the case as deliverable and the report carries a draft watermark —
because "可交付" asserts that someone stands behind the call that these
findings are false positives, and a model's say-so is not that.

This is the step where a person takes that on. Reviewing means reading the
finding and its dev_note against the code, not skimming the list: clearing a
flag transfers responsibility for that judgement from the model to you.

    veros confirm --list           what is still unconfirmed
    veros confirm ISL-02 ISL-03    confirm specific findings
    veros confirm --all            confirm everything (only after reading it)

Exit codes:
    0  done
    1  nothing matched the ids given
    2  classification.json missing or unreadable
"""
import argparse
import json
import os
import sys


def load(path):
    if not os.path.isfile(path):
        sys.exit(f"找不到 {path} —— 先跑 `veros run` 或 `veros scan`。")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"讀不了 {path}：{exc}")


def entries(data):
    for key in ("findings", "manual_findings"):
        for entry in data.get(key, []):
            yield entry


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("ids", nargs="*", help="要標記為已確認的發現編號，例如 ISL-02")
    parser.add_argument(
        "--classification", default=os.path.join("audit", "scan", "classification.json"),
        help="classification.json 的路徑，預設 ./audit/scan/classification.json",
    )
    parser.add_argument("--list", action="store_true", help="只列出尚未確認的項目，不修改")
    parser.add_argument("--all", action="store_true", help="全部標記為已確認")
    args = parser.parse_args()

    data = load(args.classification)
    pending = [e for e in entries(data) if e.get("ai_drafted")]

    if args.list or (not args.ids and not args.all):
        if not pending:
            print("沒有待確認的 AI 草稿。")
            return
        print(f"尚有 {len(pending)} 筆為 AI 草稿、未經人工確認：\n")
        for e in pending:
            title = e.get("title") or e.get("check") or "—"
            print(f"  {e.get('id', '?'):10} {e.get('category', '?')}  {title[:56]}")
        print("\n逐筆讀過 dev_note 與程式碼後，用 `veros confirm <編號...>` 或 `--all` 標記。")
        return

    if args.all:
        targets = pending
    else:
        wanted = set(args.ids)
        targets = [e for e in pending if e.get("id") in wanted]
        missing = wanted - {e.get("id") for e in targets}
        if missing:
            print(f"以下編號不在待確認清單中：{', '.join(sorted(missing))}", file=sys.stderr)
            if not targets:
                sys.exit(1)

    for e in targets:
        e.pop("ai_drafted", None)

    with open(args.classification, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    left = sum(1 for e in entries(data) if e.get("ai_drafted"))
    print(f"已確認 {len(targets)} 筆；尚餘 {left} 筆待確認。")
    if not left:
        print("全部確認完畢，重新跑 `veros report` 即可重新評定是否可交付。")


if __name__ == "__main__":
    main()
