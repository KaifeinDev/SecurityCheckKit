#!/usr/bin/env python3
"""Step 2 lint for classification.json — the checks a machine can make about a
classification pass, run while the pass can still be changed.

This exists because the same checks used to live in the *delivered report*,
where they fired after the fact: by the time a reviewer read "30 findings share
one dev_note, please spot-check", the PDF was already built and the nudge was
addressed to the client rather than to us. Everything here is rule-based on
purpose — no judgement calls, nothing an LLM should be asked to remember.

Exit codes (deliberately NOT the same scale as cli.py report):
    0  nothing to spot-check
    1  findings need a human look (a warning, not an error)
    2  classification.json missing or unreadable
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_report import (  # noqa: E402
    DUPLICATE_DEV_NOTE_THRESHOLD,
    IMPACT_AS_INDUSTRY,
    INDUSTRY_SEVERITY_RANK,
)

# A dev_note shorter than this is very unlikely to contain what the rules ask
# for (a specific mitigating control plus a file:line reference).
MIN_DEV_NOTE_CHARS = 40

DUP_PREAMBLE = (
    "以下每組發現皆共用完全相同的 dev_note 文字。共用本身不代表分類錯誤——同一根因造成的大量同類發現，"
    "合理的作法就是驗證一次、套用到全部——但這也是「模板化理由未逐筆查證」最容易藏身的地方。"
    "請針對每一組，抽查至少一筆是否真的核對過該筆自己的檔案位置，而非直接沿用。"
)

HIGH_DISMISSED_PREAMBLE = (
    "以下是工具判定 High、而我方判定為誤報（C）的發現。依 severity_grading.md，判 C 是 High 唯一的"
    "脫身路徑，所以這是整份分類裡權重最高、甲方最可能逐條挑戰的判斷。請確認每一筆的 dev_note 都是"
    "針對該筆自己的程式碼寫的，不是與其他筆共用的模板理由。"
)

HIGH_DOWNGRADED_PREAMBLE = (
    "以下是工具判定 High、而我方在報告中呈現為較低嚴重度的發現。閘門讀的是工具的 impact，所以降級"
    "不會讓這些項目繞過交付閘門，但它會改變甲方看到的樣子——報告會並列印出兩個等級與降級理由。"
)


def all_entries(classification):
    """Yield (entry, kind) for both sources in one sequence."""
    for entry in classification.get("findings", []) or []:
        yield entry, "tool"
    for entry in classification.get("manual_findings", []) or []:
        yield entry, "manual"


def label(entry):
    ident = entry.get("id") or "(未編號)"
    where = entry.get("file") or "?"
    lines = entry.get("lines") or []
    if lines:
        where += ":" + (f"{min(lines)}-{max(lines)}" if len(lines) > 1 else str(lines[0]))
    what = entry.get("check") or entry.get("title") or ""
    return f"{ident}｜{what} — {where}"


def check_duplicate_dev_notes(classification):
    groups = {}
    for entry, _ in all_entries(classification):
        if entry.get("category") not in ("B", "C"):
            continue
        note = (entry.get("dev_note") or "").strip()
        if note:
            groups.setdefault(note, []).append(entry)
    return [items for items in groups.values() if len(items) >= DUPLICATE_DEV_NOTE_THRESHOLD]


def check_short_dev_notes(classification):
    out = []
    for entry, _ in all_entries(classification):
        note = (entry.get("dev_note") or "").strip()
        if note and len(note) < MIN_DEV_NOTE_CHARS:
            out.append((entry, len(note)))
    return out


def check_missing_fields(classification):
    """Fields cli.py report will hard-fail on — reported here first so Step 2
    can fix them before a report run wastes a cycle."""
    out = []
    for entry, _ in all_entries(classification):
        cat = entry.get("category")
        if cat == "A" and not (entry.get("remediation") or "").strip():
            out.append((entry, "缺 remediation（A 類必填）"))
        if cat == "D":
            missing = [
                f
                for f in ("confirm_what", "confirm_who", "confirm_branches")
                if not (entry.get(f) or "").strip()
            ]
            if missing:
                out.append((entry, "缺 " + "／".join(missing) + "（D 類必填）"))
        if not entry.get("severity"):
            out.append((entry, "缺 severity（必填）"))
    return out


def _is_downgrade(entry):
    severity = entry.get("severity")
    impact = entry.get("impact")
    if not severity or not impact:
        return False
    equivalent = IMPACT_AS_INDUSTRY.get(impact)
    if equivalent is None or severity not in INDUSTRY_SEVERITY_RANK:
        return False
    return INDUSTRY_SEVERITY_RANK[severity] > INDUSTRY_SEVERITY_RANK[equivalent]


def check_downgrades_without_rationale(classification):
    return [
        entry
        for entry, kind in all_entries(classification)
        if kind == "tool" and _is_downgrade(entry) and not (entry.get("severity_rationale") or "").strip()
    ]


def check_high_downgraded(classification):
    # A missing severity is not a downgrade — it is an unfilled field, already
    # reported by check_missing_fields. Reporting it here too would drown the
    # real downgrades in noise on any not-yet-filled classification file.
    return [
        entry
        for entry, kind in all_entries(classification)
        if kind == "tool"
        and entry.get("impact") == "High"
        and entry.get("severity")
        and entry.get("severity") not in ("High", "Critical")
    ]


def check_high_dismissed(classification):
    return [
        entry
        for entry, kind in all_entries(classification)
        if kind == "tool" and entry.get("impact") == "High" and entry.get("category") == "C"
    ]


def check_unclassified(classification):
    return [entry for entry, _ in all_entries(classification) if not entry.get("category")]


def build_result(classification):
    dup = check_duplicate_dev_notes(classification)
    return {
        "duplicate_dev_notes": [
            {
                "count": len(items),
                "checks": sorted({i.get("check") or i.get("title") or "" for i in items}),
                "ids": [i.get("id") for i in items],
                "dev_note": items[0].get("dev_note"),
            }
            for items in dup
        ],
        "short_dev_notes": [{"id": e.get("id"), "chars": n} for e, n in check_short_dev_notes(classification)],
        "missing_fields": [{"id": e.get("id"), "problem": p} for e, p in check_missing_fields(classification)],
        "downgrades_without_rationale": [e.get("id") for e in check_downgrades_without_rationale(classification)],
        "high_downgraded": [
            {"id": e.get("id"), "impact": e.get("impact"), "severity": e.get("severity")}
            for e in check_high_downgraded(classification)
        ],
        "high_dismissed": [
            {"id": e.get("id"), "check": e.get("check")} for e in check_high_dismissed(classification)
        ],
        "unclassified": [e.get("id") for e in check_unclassified(classification)],
    }


def render_text(classification, result):
    out = []
    total = 0

    # Sections that can legitimately run to three digits (a classification file
    # whose severity column is simply not filled in yet produces one line per
    # finding) are truncated: the point is to say WHICH sections need work, and
    # a wall of identical lines buries the sections that need judgement.
    MAX_LINES_PER_SECTION = 15

    def section(title, body_lines, preamble=None):
        nonlocal total
        if not body_lines:
            return
        total += len(body_lines)
        out.append(f"## {title}（{len(body_lines)} 項）")
        if preamble:
            out.append(preamble)
        out.extend(body_lines[:MAX_LINES_PER_SECTION])
        if len(body_lines) > MAX_LINES_PER_SECTION:
            out.append(f"- …另有 {len(body_lines) - MAX_LINES_PER_SECTION} 項同類（完整清單用 --json）")
        out.append("")

    dup = check_duplicate_dev_notes(classification)
    section(
        "重複使用的判斷理由",
        [
            f"- {len(items)} 筆共用同一段理由（detector：{', '.join(sorted({i.get('check') or i.get('title') or '' for i in items}))}）："
            + ", ".join(str(i.get("id")) for i in items[:6])
            + (f" 等 {len(items)} 筆" if len(items) > 6 else "")
            for items in dup
        ],
        DUP_PREAMBLE,
    )

    section(
        "工具判 High、我方判誤報（C）",
        [f"- {label(e)}" for e in check_high_dismissed(classification)],
        HIGH_DISMISSED_PREAMBLE,
    )

    section(
        "工具判 High、我方呈現為較低嚴重度",
        [f"- {label(e)}（impact High → severity {e.get('severity')}）" for e in check_high_downgraded(classification)],
        HIGH_DOWNGRADED_PREAMBLE,
    )

    section(
        "降級但未附 severity_rationale",
        [f"- {label(e)}" for e in check_downgrades_without_rationale(classification)],
        "cli.py report 會因此 exit 2，先在這裡補完。",
    )

    section(
        "必填欄位缺漏",
        [f"- {label(e)}：{p}" for e, p in check_missing_fields(classification)],
        "cli.py report 會因此 exit 2，先在這裡補完。",
    )

    section(
        "dev_note 過短",
        [f"- {label(e)}（{n} 字）" for e, n in check_short_dev_notes(classification)],
        f"少於 {MIN_DEV_NOTE_CHARS} 字通常放不下「具體緩解措施 + 檔案:行號」，請確認不是敷衍。",
    )

    section(
        "未分類",
        [f"- {label(e)}" for e in check_unclassified(classification)],
        "未分類在判級時視同 D，未分類的 High 直接把等級打到第四級。",
    )

    if total == 0:
        return "classification.json 沒有待抽查項目。\n", 0
    out.append(f"合計 {total} 項待抽查。這些是提醒，不是錯誤 —— 逐項確認後即可進入下一步。")
    return "\n".join(out) + "\n", total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", required=True)
    parser.add_argument("--json", action="store_true", help="輸出結構化結果（供工作底稿引用）")
    args = parser.parse_args()

    try:
        with open(args.classification, encoding="utf-8") as f:
            classification = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"讀不到或無法解析 {args.classification}：{exc}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        result = build_result(classification)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        total = sum(len(v) for v in result.values())
        sys.exit(1 if total else 0)

    text, total = render_text(classification, build_result(classification))
    print(text, end="")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
