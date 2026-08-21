#!/usr/bin/env python3
"""Locate or print the methodology that ships with Veros.

The scenario library, the grading standard, the field notes and SKILL.md are
installed alongside the code. They are what Step 2 is carried out against, so
an auditor — or an LLM driving the pipeline — needs to be able to find them
without knowing where pip put the package.

    veros docs                 list what is available and where
    veros docs logic_scan      print one of them
    veros docs --path          print the directory, for piping into other tools
"""
import argparse
import os
import sys

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCES_DIR = os.path.join(PKG_DIR, "references")

DOCS = {
    "skill": (os.path.join(PKG_DIR, "SKILL.md"), "完整流程指引，也是驅動 LLM 走完 Step 0-3 的依據"),
    "logic_scan": (os.path.join(REFERENCES_DIR, "logic_scan.md"), "情境庫：Slither 抓不到的業務邏輯漏洞，Step 2 逐份合約比對"),
    "severity_grading": (os.path.join(REFERENCES_DIR, "severity_grading.md"), "嚴重度評定標準"),
    "pitfalls": (os.path.join(REFERENCES_DIR, "pitfalls.md"), "實測踩過的坑，開始前必讀"),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("name", nargs="?", choices=sorted(DOCS), help="印出指定文件的內容")
    parser.add_argument("--path", action="store_true", help="只印出安裝目錄的路徑")
    args = parser.parse_args()

    if args.path:
        print(PKG_DIR)
        return

    if args.name:
        path = DOCS[args.name][0]
        if not os.path.isfile(path):
            sys.exit(f"找不到 {path} —— 安裝不完整？")
        with open(path, encoding="utf-8") as f:
            sys.stdout.write(f.read())
        return

    print(f"Veros 方法論文件（安裝於 {PKG_DIR}）：\n")
    for name, (path, desc) in DOCS.items():
        mark = " " if os.path.isfile(path) else "!"
        print(f" {mark} {name:18} {desc}")
    incidents = os.path.join(REFERENCES_DIR, "domain_incidents")
    if os.path.isdir(incidents):
        files = sorted(f[:-3] for f in os.listdir(incidents) if f.endswith(".md") and f != "README.md")
        print(f"\n   domain_incidents   各業務領域的公開事故模式：{', '.join(files)}")
    print("\n用 `veros docs <name>` 印出內容，`veros docs --path` 取得目錄路徑。")


if __name__ == "__main__":
    main()
