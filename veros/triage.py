#!/usr/bin/env python3
"""Step 2, drafted by a model: classify each scan finding and write the report
fields a human would otherwise type.

    veros triage                       # audit/scan/classification_skeleton.json -> classification.json
    veros triage --dry-run             # what it would send, and the token estimate
    veros triage --only ISL-02 ISL-05  # redo specific findings

Every entry this writes carries `ai_drafted: true`. The delivery gate refuses to
grade a case as deliverable while any of those remain, and `veros confirm` is
where a person takes the judgement on. That is deliberate: the classification is
what the report certifies, and a model's say-so is not a sign-off.

Two passes, because they ask different questions:

  * per finding — is what the tool matched a real problem here (A/B/C/D), and if
    so, what breaks and how is it fixed. Findings are batched by source file so
    one read of that file serves all of them.
  * per contract — the scenario library in references/logic_scan.md, which is
    the half Slither cannot see. Whole file, one contract at a time.

The methodology (scenario library, grading standard) goes in the system prompt
behind a cache breakpoint, so it is written once and read cheaply on every
subsequent call rather than re-billed per batch.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as veros_config  # noqa: E402
import docs as veros_docs  # noqa: E402

MAX_SOURCE_CHARS = 120_000  # a very large contract still fits a 1M window; this bounds cost
CONTEXT_LINES = 40          # source shown either side of a finding when sending excerpts


CLASSIFY_TOOL = {
    "name": "record_classifications",
    "description": "逐筆記錄本批發現的處置分類與報告欄位。每一筆掃描發現都必須出現一次。",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id", "category", "severity", "dev_note",
                        "title", "explanation", "impact_detail",
                        "proof_of_concept", "remediation", "severity_rationale",
                    ],
                    "properties": {
                        "id": {"type": "string", "description": "對應輸入的發現編號，原樣回填"},
                        "category": {
                            "type": "string",
                            "enum": ["A", "B", "C", "D"],
                            "description": "A 已確認需修復；B 已知風險但可接受；C 誤報；D 信心不足待人工確認。信心不足一律填 D，不要猜。",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["Critical", "High", "Medium", "Low", "Informational"],
                        },
                        "severity_rationale": {
                            "type": "string",
                            "description": "只有判得比工具輕時才需要；否則填空字串。",
                        },
                        "dev_note": {
                            "type": "string",
                            "description": "判斷依據，必須引用具體的檔案:行號。禁止「沒問題」這類空泛字眼。B/C 類必填。",
                        },
                        "title": {"type": "string", "description": "一句話標題：根因 + 影響。不是 detector 名稱。A/D 類必填，C 類填空字串。"},
                        "explanation": {"type": "string", "description": "哪個函式、正常該怎麼運作、為何出錯。A/D 類必填。"},
                        "impact_detail": {"type": "string", "description": "具體危害與業務損失。A/D 類必填。"},
                        "proof_of_concept": {"type": "string", "description": "攻擊步驟或重現方式；若目前不可利用，寫明成立條件。A/D 類必填。"},
                        "remediation": {"type": "string", "description": "怎麼修，給程式碼片段或 diff。A 類必填。"},
                    },
                },
            }
        },
    },
}

SCENARIO_TOOL = {
    "name": "record_scenario_findings",
    "description": "記錄情境庫比對後命中的問題。沒有命中就回傳空陣列 —— 不要為了交差硬湊。",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "title", "severity", "category", "lines", "scenario",
                        "description", "impact_detail", "proof_of_concept",
                        "remediation", "dev_note",
                    ],
                    "properties": {
                        "title": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["Critical", "High", "Medium", "Low", "Informational"],
                        },
                        "category": {"type": "string", "enum": ["A", "B", "D"]},
                        "lines": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "問題所在的行號，[起, 迄]",
                        },
                        "scenario": {"type": "string", "description": "命中的情境編號，例如 L3"},
                        "description": {"type": "string"},
                        "impact_detail": {"type": "string"},
                        "proof_of_concept": {"type": "string"},
                        "remediation": {"type": "string"},
                        "dev_note": {"type": "string", "description": "判斷依據，必須引用 檔案:行號"},
                    },
                },
            }
        },
    },
}


def read_doc(name: str) -> str:
    path = dict(veros_docs.DOCS).get(name, (None,))[0]
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def system_blocks() -> list:
    """Methodology first, behind a cache breakpoint — identical on every call."""
    methodology = "\n\n".join(
        part for part in (
            "# 情境庫\n\n" + read_doc("logic_scan"),
            "# 嚴重度評定標準\n\n" + read_doc("severity_grading"),
        ) if part.strip()
    )
    return [
        {
            "type": "text",
            "text": (
                "你是智能合約安全審計員，正在執行一次交付前自我檢查的分類步驟。\n\n"
                "原則（不可違反）：\n"
                "1. 只根據提供的原始碼判斷，不要臆測沒看到的程式碼。需要看別的檔案才能判斷時，一律填 D。\n"
                "2. 信心不足一律填 D，不要為了讓清單好看而猜 A/B/C。誤判成 C 等於把真漏洞藏起來。\n"
                "3. dev_note 必須引用具體的 檔案:行號，寫出你實際查證了什麼。\n"
                "4. 「僅 owner/admin 可呼叫所以可接受」這種理由，必須先確認該 modifier 的實作邏輯真的有效，"
                "並把確認結果寫進 dev_note —— 權限檢查本身壞掉是靜態工具的典型漏報。\n"
                "5. 判得比工具輕（降級）時必須填 severity_rationale。\n\n"
                + methodology
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def excerpt(project_dir: str, rel_path: str, lines) -> str:
    path = os.path.join(project_dir, rel_path)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.readlines()
    if not lines:
        lo, hi = 0, min(len(src), CONTEXT_LINES * 2)
    else:
        lo = max(0, min(lines) - 1 - CONTEXT_LINES)
        hi = min(len(src), max(lines) + CONTEXT_LINES)
    return "".join(f"{i + 1:5d} | {src[i]}" for i in range(lo, hi))


def client_and_kwargs(args):
    try:
        import anthropic
    except ImportError:
        sys.exit("需要 anthropic 套件：pip install anthropic")
    key = veros_config.require_api_key(args.api_key)
    model = args.model or veros_config.resolve_model()
    effort = args.effort or veros_config.resolve_effort()
    return anthropic.Anthropic(api_key=key), model, effort


def call_tool(client, model, effort, system, user_text, tool):
    """One request that must come back as a call to `tool`."""
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        response = stream.get_final_message()
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return block.input, response.usage
    return None, response.usage


def classify_batch(client, model, effort, project_dir, batch):
    listing = []
    for f in batch:
        listing.append(
            f"### {f['id']}\n"
            f"detector: {f.get('check')}\n"
            f"工具判定 impact: {f.get('impact')}\n"
            f"位置: {f.get('file')}:{f.get('lines')}\n"
            f"工具描述:\n{(f.get('description') or '').strip()}\n"
        )
    src = excerpt(project_dir, batch[0].get("file", ""), None)
    body = (
        f"以下 {len(batch)} 筆發現都位於 `{batch[0].get('file')}`。逐筆判斷，"
        "每一筆都要出現在回傳結果中。\n\n"
        f"## 原始碼（{batch[0].get('file')}，含行號）\n```solidity\n{src}\n```\n\n"
        "## 待分類的發現\n\n" + "\n".join(listing)
    )
    return call_tool(client, model, effort, system_blocks(), body, CLASSIFY_TOOL)


def scan_scenarios(client, model, effort, project_dir, rel_path):
    path = os.path.join(project_dir, rel_path)
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    if len(src) > MAX_SOURCE_CHARS:
        return None, None
    numbered = "".join(f"{i + 1:5d} | {line}\n" for i, line in enumerate(src.splitlines()))
    body = (
        f"對 `{rel_path}` 逐條比對系統提示中的情境庫。採兩段式判定：先看合約是否具備該情境的"
        "前置條件，有才逐行讀關鍵語句確認。命中的才回報；沒有命中就回傳空陣列。\n\n"
        f"```solidity\n{numbered}\n```"
    )
    return call_tool(client, model, effort, system_blocks(), body, SCENARIO_TOOL)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scan-dir", default=os.path.join("audit", "scan"))
    parser.add_argument("--project-dir", default=".", help="原始碼根目錄，發現的檔案路徑相對於此")
    parser.add_argument("--model", help="覆蓋 veros config 的模型設定")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--api-key")
    parser.add_argument("--only", nargs="*", help="只重跑指定編號的發現")
    parser.add_argument("--skip-scenarios", action="store_true", help="跳過情境庫比對（只做逐筆分類）")
    parser.add_argument("--dry-run", action="store_true", help="只顯示會送出什麼，不呼叫 API")
    args = parser.parse_args()

    skeleton_path = os.path.join(args.scan_dir, "classification_skeleton.json")
    out_path = os.path.join(args.scan_dir, "classification.json")
    if not os.path.isfile(skeleton_path):
        sys.exit(f"找不到 {skeleton_path} —— 先跑 `veros scan`。")
    with open(skeleton_path, encoding="utf-8") as f:
        data = json.load(f)

    findings = data.get("findings", [])
    if args.only:
        wanted = set(args.only)
        findings = [f for f in findings if f.get("id") in wanted]
        if not findings:
            sys.exit(f"沒有符合的發現：{', '.join(sorted(wanted))}")

    by_file = {}
    for f in findings:
        by_file.setdefault(f.get("file", "?"), []).append(f)
    contracts = sorted(p for p in by_file if p.endswith(".sol"))

    if args.dry_run:
        print(f"待分類 {len(findings)} 筆，分成 {len(by_file)} 批（依檔案）：")
        for path, group in sorted(by_file.items()):
            print(f"  {len(group):3d} 筆  {path}")
        if not args.skip_scenarios:
            print(f"\n情境庫比對：{len(contracts)} 份合約，每份一次呼叫")
        print(f"\n模型 {args.model or veros_config.resolve_model()}，"
              f"共約 {len(by_file) + (0 if args.skip_scenarios else len(contracts))} 次 API 呼叫。")
        return

    client, model, effort = client_and_kwargs(args)
    index = {f["id"]: f for f in data.get("findings", [])}
    filled = 0

    for path, group in sorted(by_file.items()):
        print(f"分類 {len(group)} 筆：{path}", file=sys.stderr)
        result, usage = classify_batch(client, model, effort, args.project_dir, group)
        if not result:
            print(f"  模型未回傳結果，跳過 {path}", file=sys.stderr)
            continue
        for item in result.get("findings", []):
            entry = index.get(item.get("id"))
            if not entry:
                continue
            for field in ("category", "severity", "severity_rationale", "dev_note",
                          "title", "explanation", "impact_detail",
                          "proof_of_concept", "remediation"):
                if item.get(field):
                    entry[field] = item[field]
            entry["ai_drafted"] = True
            filled += 1

    if not args.skip_scenarios:
        manual = data.setdefault("manual_findings", [])
        existing = len(manual)
        for i, rel_path in enumerate(contracts, start=1):
            print(f"情境庫比對 {i}/{len(contracts)}：{rel_path}", file=sys.stderr)
            result, _ = scan_scenarios(client, model, effort, args.project_dir, rel_path)
            if not result:
                continue
            for item in result.get("findings", []):
                item.update({
                    "id": f"{_prefix(data)}-{900 + len(manual)}",
                    "source": "manual",
                    "file": rel_path,
                    "ai_drafted": True,
                })
                manual.append(item)
        print(f"情境庫新增 {len(manual) - existing} 筆", file=sys.stderr)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total = filled + len(data.get("manual_findings", []))
    print(f"\n已寫入 {out_path}：{filled} 筆掃描發現、"
          f"{len(data.get('manual_findings', []))} 筆情境庫發現，全部標記為 AI 草稿。")
    print(f"下一步：`veros review` 看機械檢查，逐筆複核後 `veros confirm`，再跑 `veros report`。")
    print(f"在確認完成前，report 一律不會判定為可交付。")


def _prefix(data) -> str:
    for f in data.get("findings", []):
        ident = f.get("id") or ""
        if "-" in ident:
            return ident.rsplit("-", 1)[0]
    return "PRJ"


if __name__ == "__main__":
    main()
