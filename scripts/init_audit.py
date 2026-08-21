#!/usr/bin/env python3
"""Step -1: scaffold the two markdown files the report needs a human to write.

`cli.py report` takes --overview and --scope-note as free-form markdown, and
both have a shape the report depends on: --overview supplies the "摘要" chapter's
`##` sections, --scope-note the disclosure that qualifies the scope section's
file hashes. Neither is discoverable from --help, so both were routinely left
out and the report shipped without a protocol description at all.

Writes templates rather than empty files: an auditor filling in headings that
are already there produces a usable chapter; one facing a blank file writes
whatever occurs to them, and the reports stop matching each other.

Existing files are never overwritten — this is safe to re-run.
"""
import argparse
import os
import sys

OVERVIEW_TEMPLATE = """## 協定概要

<!-- 這個協定在做什麼、誰是使用者、資金怎麼流動。兩三段，讓讀者在看發現之前
     先理解系統，否則他無從判斷一筆發現的業務影響。 -->

本次檢測範圍為 `<目錄>` 下的 <N> 個 Solidity 檔案、共 <N> 行。

核心合約分工：

| 合約 | 職責 |
|---|---|
| `<Contract>` | <一句話說明它負責什麼、持有什麼> |

### <風險模型的小節，例如「違約時的損失吸收順序」>

<!-- 這個系統的損失由誰承擔、有沒有自動化風控。這決定了「參數無上下限」
     這類發現為什麼重要。沒有這段的話，讀者會覺得那些發現無關痛癢。 -->

## 資產保管與流向

<!-- 系統裡流通哪幾種資產，各自在什麼時候由哪個合約持有。
     這是判斷「資金會不會卡住／被提走」的前提。 -->

## 角色與權限

<!-- 逐個特權角色列出它實際能做什麼 —— 不是設定值，是能力範圍。
     每一項都要對得上程式碼裡的 modifier。 -->

### <角色名稱，例如 Governor>

- <能做什麼>（`<檔案>:<行號>`）

### 無權限函式

<!-- 任何人都能呼叫的函式。列出來，因為攻擊面從這裡開始。 -->
"""

SCOPE_NOTE_TEMPLATE = """## 檢測環境偏離揭露

<!-- 只有在本次掃描偏離了標準程序時才需要這個檔案；沒有偏離就刪掉它、
     report 不帶 --scope-note 即可。

     這一節接在「檢測範圍與方法」章末尾，緊鄰那張列出檔案 SHA-256 的表 ——
     因為它揭露的正是那張表的但書。典型情況：

       * 為了讓工具跑起來，在本機暫時改過原始碼（改名、拆檔、降版）
       * 某些檔案編不過而被排除
       * 使用了非官方版本的工具或依賴

     要寫清楚三件事：改了什麼、為什麼、對報告的哪些內容有影響
     （尤其是雜湊值與行號是否仍然成立）。 -->
"""


def write_template(path: str, content: str) -> str:
    if os.path.exists(path):
        return f"已存在，未覆寫：{path}"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已建立：{path}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--audit-dir", default="audit",
        help="放內部文件的目錄，預設 ./audit。工作底稿也預設寫在這裡，"
             "整個目錄都不應交付甲方（記得加進 .gitignore）",
    )
    args = parser.parse_args()

    print(write_template(os.path.join(args.audit_dir, "overview.md"), OVERVIEW_TEMPLATE))
    print(write_template(os.path.join(args.audit_dir, "scope_note.md"), SCOPE_NOTE_TEMPLATE))
    print(
        f"\n填好後於 Step 3 帶入：\n"
        f"  --overview {os.path.join(args.audit_dir, 'overview.md')}\n"
        f"  --scope-note {os.path.join(args.audit_dir, 'scope_note.md')}   # 無偏離則不帶\n"
        f"\n提醒：{args.audit_dir}/ 含工作底稿與內部語氣的文件，請加進 .gitignore。",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
