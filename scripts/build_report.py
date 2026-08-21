"""Build a complete markdown security-scan report from the artifacts a
security-scan skill run produces:

  --before          filtered `slither --json` output (project files only) for this run
  --classification  classification.json written during Step 2 (A/B/C/D + dev notes,
                    plus optional manual_findings[] from human review)
  --env             scan_env.json written during Step 1 (toolchain/version info)
  --scope           scope.json from Step 1: the files the scan covered
  --overview        markdown inlined as the protocol-overview section
  --worksheet       where to write the internal worksheet (never into --out-dir)
  --out-dir         directory to write report.md into

classification.json / scan_env.json are optional: if missing, those report
sections are rendered with a note that Step 2/Step 1 metadata wasn't
captured, rather than failing outright.

When classification.json IS provided, it is validated and reconciled against
--before *before* any report is written:
  * every scan finding must appear in classification.json — findings left
    uncovered are treated as unclassified (graded like D; an uncovered High
    triggers Tier 4), never as resolved
  * entries that match no scan finding (stale file / copy mistakes), invalid
    category values, impact values that contradict the scan output, and B/C
    entries without a dev_note are hard errors: no report is written

Exit codes (gate semantics, propagated by report.py / cli.py):
  0  Tier 1/2  - deliverable
  2  validation/reconciliation error - report NOT written
  3  Tier 3, or grade not computable (no classification.json)
  4  Tier 4
"""
import argparse
import json
import os
import re
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filter_results import extract_findings  # noqa: E402

IMPACT_ORDER = ["High", "Medium", "Low", "Informational", "Optimization"]
# Remediation status is tracked separately from the A/B/C/D risk category —
# category answers "is this real and does it matter", status answers "has it
# been fixed yet". Optional field on both findings[] entries and
# manual_findings[] entries; absent means not yet triaged for remediation.
DEFAULT_STATUS = "待處理"
# Severity/impact values are shown verbatim as Slither outputs them (High,
# Medium, Critical, ...) everywhere in the report — not translated — so a
# client rescan's raw output can be correlated line-by-line against this
# document without a translation table in between.
# The industry-standard severity scale the delivery report presents. Distinct
# from `impact`, which stays verbatim-equal to Slither's own output and is the
# ONLY field the delivery gate reads — a human downgrade changes how a finding
# is presented but must never make a Slither High disappear from the gate's
# view. See references/severity_grading.md.
INDUSTRY_SEVERITIES = ["Critical", "High", "Medium", "Low", "Informational"]
INDUSTRY_SEVERITY_RANK = {s: i for i, s in enumerate(INDUSTRY_SEVERITIES)}
# Slither impact -> the industry severity it is considered equivalent to, for
# the sole purpose of detecting a human DOWNGRADE (which requires a rationale).
# An upgrade (e.g. Slither Low -> our High) needs no rationale: raising the
# stakes is never the direction abuse comes from.
IMPACT_AS_INDUSTRY = {
    "High": "High",
    "Medium": "Medium",
    "Low": "Low",
    "Informational": "Informational",
    "Optimization": "Informational",
}
# Findings carry one unified id across both sources; `scan_id` keeps the
# original scan-order index for rescan matching and is deliberately never
# rendered into the report.
VALID_SOURCES = {"tool", "manual"}
FINDING_ID_RE = re.compile(r"^[A-Z]{2,6}-\d{2,}$")

VALID_CATEGORIES = {"A", "B", "C", "D"}
# Reading order for the Findings section: what still needs fixing, then what is
# still undecided, then what was examined and accepted or dismissed.
CATEGORY_ORDER = {"A": 0, "B": 1, "D": 2, None: 3, "C": 4}
# Manual findings never carry C: a human-found issue that turns out not to be
# a problem is deleted from the list, not filed as a tool false positive.
MANUAL_CATEGORIES = {"A", "B", "D"}

# Tier -> process exit code. The tier itself never appears in the report body;
# this mapping is the whole of its externally visible effect, alongside the
# internal-draft watermark. None = not gradeable (no classification.json).
GATE_EXIT_BY_TIER = {1: 0, 2: 0, 3: 3, 4: 4, None: 3}


def format_lines(lines):
    """Render a finding's line-range as "90-100" / "90" instead of the raw
    Python list repr ("[90, 100]"), which reads as visual noise in a report
    meant for a client, not a data dump."""
    if not lines:
        return "?"
    if len(lines) == 1:
        return str(lines[0])
    return f"{min(lines)}-{max(lines)}"


def load_json(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def severity_counts(results_json):
    counts = OrderedDict((lvl, 0) for lvl in IMPACT_ORDER)
    if not results_json:
        return counts
    for d in results_json.get("results", {}).get("detectors", []):
        impact = d.get("impact", "Informational")
        counts[impact] = counts.get(impact, 0) + 1
    return counts


def fingerprint(check, file, lines):
    return (check, file, min(lines) if lines else None)


def validate_common_fields(entry, ident, expected_source, tool_impact=None):
    """Validate the fields shared by findings[] and manual_findings[] entries.

    `tool_impact` is the scan output's impact for tool findings (None for
    manual ones, which have no tool opinion to be measured against). Returns a
    list of error strings; an empty list means the entry passed.
    """
    errors = []

    ident_value = entry.get("id")
    if not isinstance(ident_value, str) or not FINDING_ID_RE.match(ident_value):
        errors.append(
            f"{ident} 的 id 格式無效：{ident_value!r}（應為 <專案縮寫大寫>-<兩位數以上編號>，例如 BGT-01）。"
        )

    source = entry.get("source")
    if source not in VALID_SOURCES:
        errors.append(f"{ident} 的 source 值無效：{source!r}（只接受 {'/'.join(sorted(VALID_SOURCES))}）。")
    elif source != expected_source:
        errors.append(
            f"{ident} 的 source 是 {source!r}，但它出現在 "
            f"{'findings[]' if expected_source == 'tool' else 'manual_findings[]'} 裡 —— "
            f"應為 {expected_source!r}。"
        )

    severity = entry.get("severity")
    if severity not in INDUSTRY_SEVERITY_RANK:
        errors.append(
            f"{ident} 的 severity 值無效：{severity!r}（必填，只接受 {'/'.join(INDUSTRY_SEVERITIES)}）。"
        )
    elif tool_impact is not None:
        # A downgrade relative to the tool's own opinion is the direction that
        # needs justifying: the gate reads `impact`, so a downgrade cannot open
        # the gate, but it does change what the client is shown.
        tool_equivalent = IMPACT_AS_INDUSTRY.get(tool_impact)
        if tool_equivalent is not None and INDUSTRY_SEVERITY_RANK[severity] > INDUSTRY_SEVERITY_RANK[tool_equivalent]:
            if not (entry.get("severity_rationale") or "").strip():
                errors.append(
                    f"{ident} 把工具判定的 {tool_impact} 降為 {severity}，但沒有 severity_rationale —— "
                    "降級必須附理由（報告會並列印出兩個等級，理由是甲方唯一能檢視這個判斷的依據）。"
                )

    category = entry.get("category")
    if category == "A" and not (entry.get("remediation") or "").strip():
        errors.append(f"{ident} 分類為 A（已確認需修復）但沒有 remediation —— A 類必須寫出怎麼修。")
    if category == "D":
        for field, label in (
            ("confirm_what", "要確認什麼"),
            ("confirm_who", "問誰"),
            ("confirm_branches", "兩種答案各自怎麼做"),
        ):
            if not (entry.get(field) or "").strip():
                errors.append(f"{ident} 分類為 D（待確認）但沒有 {field}（{label}）—— D 類不得停在問句。")

    return errors


def validate_finding_ids(classification):
    """Findings share one id sequence across both sources, so uniqueness has to
    be checked where both lists are visible at once."""
    errors = []
    seen = {}
    for key in ("findings", "manual_findings"):
        for entry in classification.get(key, []):
            ident_value = entry.get("id")
            if not isinstance(ident_value, str):
                continue  # format already reported by validate_common_fields
            if ident_value in seen:
                errors.append(
                    f"id {ident_value!r} 重複出現（{seen[ident_value]} 與 {key}）—— "
                    "掃描發現與人工發現共用同一組編號序列，不得重複。"
                )
            else:
                seen[ident_value] = key
    return errors


def validate_top_level_keys(classification, known_ids):
    """Validate the two optional top-level keys the redesigned report consumes."""
    errors = []

    coverage = classification.get("scenario_coverage")
    if coverage is not None:
        if not isinstance(coverage, dict) or not isinstance(coverage.get("contracts"), list):
            errors.append("scenario_coverage 格式錯誤：應為 {\"contracts\": [...]}。")
        else:
            for i, row in enumerate(coverage["contracts"]):
                where = f"scenario_coverage.contracts[{i}]"
                if not isinstance(row, dict) or not isinstance(row.get("file"), str):
                    errors.append(f"{where} 缺少 file（字串）。")
                    continue
                for field in ("checked", "not_applicable", "hits"):
                    value = row.get(field, [])
                    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                        errors.append(f"{where} 的 {field} 應為字串陣列。")
                for hit in row.get("hits", []) or []:
                    if isinstance(hit, str) and hit not in known_ids:
                        errors.append(
                            f"{where} 的 hits 列出 {hit!r}，但沒有這個編號的發現 —— "
                            "覆蓋矩陣的命中必須指向實際存在的 finding id。"
                        )

    reasons = classification.get("scope_exclusion_reasons")
    if reasons is not None:
        if not isinstance(reasons, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in reasons.items()
        ):
            errors.append("scope_exclusion_reasons 格式錯誤：應為 {\"<排除路徑前綴>\": \"<理由>\"} 的字串對字串。")

    return errors


def reconcile(scan_list, classification):
    """Match classification.json findings 1:1 against the scan output.

    Returns (effective_findings, errors). Each effective finding is a scan
    finding plus the matched entry's id/category/dev_note; scan findings
    nobody classified get category None (rendered and graded as 未分類).
    Errors are returned rather than raised so main() can print them all at
    once instead of failing one by one.
    """
    errors = []
    pool = {}
    for idx, f in enumerate(scan_list):
        pool.setdefault(fingerprint(f["check"], f["file"], f["lines"]), []).append(idx)

    matched = {}
    for entry in classification.get("findings", []):
        ident = f"classification.json findings id={entry.get('id')} ({entry.get('check')} @ {entry.get('file')}:{format_lines(entry.get('lines'))})"
        candidates = pool.get(fingerprint(entry.get("check"), entry.get("file"), entry.get("lines")))
        if not candidates:
            errors.append(
                f"{ident} 對不上本次掃描結果（--before）的任何發現 —— "
                "可能是沿用了上次掃描的過期分類檔，或 check/file/lines 抄寫錯誤。"
            )
            continue
        idx = candidates.pop(0)
        scan_f = scan_list[idx]

        category = entry.get("category") or None
        if category is not None and category not in VALID_CATEGORIES:
            errors.append(f"{ident} 的 category 值無效：{category!r}（只接受大寫 A/B/C/D，或留空表示未分類）。")
            category = None
        claimed_impact = entry.get("impact")
        if claimed_impact and claimed_impact != scan_f["impact"]:
            errors.append(
                f"{ident} 的 impact 寫的是 {claimed_impact!r}，但掃描結果是 {scan_f['impact']!r} —— "
                "impact 以掃描輸出為準，請修正分類檔（嚴重度寫錯會直接影響資安等級計算）。"
            )
        if category in ("B", "C") and not (entry.get("dev_note") or "").strip():
            errors.append(f"{ident} 分類為 {category} 但沒有 dev_note —— B/C 是抑制的依據，必須附具體理由。")

        errors += validate_common_fields(entry, ident, "tool", tool_impact=scan_f["impact"])

        matched[idx] = {
            "id": entry.get("id"),
            "scan_id": entry.get("scan_id"),
            "source": entry.get("source"),
            "category": category,
            "dev_note": entry.get("dev_note"),
            "severity": entry.get("severity"),
            "severity_rationale": entry.get("severity_rationale"),
            "title": entry.get("title"),
            "explanation": entry.get("explanation"),
            "impact_detail": entry.get("impact_detail"),
            "proof_of_concept": entry.get("proof_of_concept"),
            "remediation": entry.get("remediation"),
            "confirm_what": entry.get("confirm_what"),
            "confirm_who": entry.get("confirm_who"),
            "confirm_branches": entry.get("confirm_branches"),
            "status": entry.get("status"),
            "auto_classified": entry.get("auto_classified"),
            "carried_from_previous": entry.get("carried_from_previous"),
        }

    effective = []
    for idx, f in enumerate(scan_list):
        e = dict(f)
        m = matched.get(idx, {})
        e["id"] = m.get("id")
        e["category"] = m.get("category")
        e["dev_note"] = m.get("dev_note")
        for field in (
            "scan_id",
            "source",
            "severity",
            "severity_rationale",
            "title",
            "explanation",
            "impact_detail",
            "proof_of_concept",
            "remediation",
            "confirm_what",
            "confirm_who",
            "confirm_branches",
            "auto_classified",
            "carried_from_previous",
        ):
            e[field] = m.get(field)
        # `status` is already read off the classification entry elsewhere in the
        # renderers via .get("status"); keep it on the effective dict too so an
        # unclassified finding doesn't inherit a stale value from the scan JSON.
        e["status"] = m.get("status")
        effective.append(e)
    return effective, errors


DUPLICATE_DEV_NOTE_THRESHOLD = 5


def detect_duplicate_dev_notes(effective):
    """Group B/C findings that share the exact same dev_note text across at
    least DUPLICATE_DEV_NOTE_THRESHOLD entries.

    This does NOT mean the classification is wrong — a genuinely-shared root
    cause across many findings of the same check (e.g. "these N calls-loop
    findings all originate from the same four role-gated batch functions") is
    a legitimate reason to reuse one verified dev_note. But a human reviewer
    reading only a rolled-up "B: 59 筆" count in a summary table has no way to
    notice that 30 of those 59 share one paragraph, and no way to tell
    "verified once, correctly applies to all 30" apart from "written once,
    never re-checked against the other 29." Both look identical in the data.
    This function does not — and cannot — resolve that ambiguity; it only
    makes the duplication impossible to miss, forcing an explicit human
    judgment call instead of a silent one. See references/pitfalls.md for the
    incident (an initial classification pass reused one plausible-sounding
    but factually wrong justification across 27 findings without reading
    their actual call sites) that motivated this check.
    """
    groups = {}
    for f in effective:
        if f["category"] not in ("B", "C"):
            continue
        note = (f.get("dev_note") or "").strip()
        if not note:
            continue
        groups.setdefault(note, []).append(f)
    return [items for items in groups.values() if len(items) >= DUPLICATE_DEV_NOTE_THRESHOLD]


def validate_manual_findings(classification):
    """Validate classification.json's manual_findings[] (human-review findings
    that no Slither detector produced). Returns (manual_list, errors)."""
    errors = []
    manual = []
    for m in classification.get("manual_findings", []):
        ident = f"classification.json manual_findings id={m.get('id')}"
        # severity is validated by validate_common_fields against the same set
        # (INDUSTRY_SEVERITIES == MANUAL_SEVERITIES); manual findings have no
        # tool impact to compare against, so no downgrade check applies.
        errors += validate_common_fields(m, ident, "manual")
        category = m.get("category")
        if category not in MANUAL_CATEGORIES:
            errors.append(
                f"{ident} 的 category 值無效：{category!r}（人工發現只接受 A/B/D —— "
                "若複核後認定不是問題，請直接從 manual_findings 移除，而不是標成 C）。"
            )
        if not (m.get("title") or m.get("description") or "").strip():
            errors.append(f"{ident} 缺少 title/description，無法寫進報告。")
        if not (m.get("dev_note") or "").strip():
            errors.append(f"{ident} 沒有 dev_note —— 人工發現必須附判斷依據。")
        manual.append(m)
    return manual, errors


def is_high_risk_manual(m):
    return m.get("severity") in ("Critical", "High")


def compute_grade(effective, manual, classification_provided):
    """Compute the Tier 1-4 executive-summary grade.

    Inputs are the *reconciled* findings (every scan finding, classified or
    not) plus manual_findings — so an omitted classification entry can only
    ever lower the grade, never raise it. Rules per
    references/severity_grading.md (deliberately conservative draft):
      Tier 4: any High scan finding not classified C (unclassified counts),
              or any Critical/High manual finding
      Tier 3: any A (confirmed, unfixed), D (pending), or unclassified item
      Tier 2: any B (accepted risk), otherwise
      Tier 1: everything present is classified C (false positive)
    Order matters: checked top-to-bottom, first match wins.
    """
    if not classification_provided:
        return {"tier": None, "label": None, "reason": "尚未提供分類資料（Step 2 未寫入 classification.json），無法計算資安等級。"}

    high_scan = [f for f in effective if f["impact"] == "High" and f["category"] != "C"]
    high_manual = [m for m in manual if is_high_risk_manual(m)]
    if high_scan or high_manual:
        return {
            "tier": 4,
            "label": "第四級",
            "reason": (
                f"偵測到 {len(high_scan) + len(high_manual)} 項危急／高嚴重度發現尚未排除，"
                "需修復並重新掃描後才可交付。"
            ),
        }

    confirmed = [f for f in effective if f["category"] == "A"] + [m for m in manual if m.get("category") == "A"]
    pending_d = [f for f in effective if f["category"] == "D"] + [m for m in manual if m.get("category") == "D"]
    unclassified = [f for f in effective if f["category"] is None]
    if confirmed or pending_d or unclassified:
        parts = []
        if confirmed:
            parts.append(f"{len(confirmed)} 項已確認需修復（分類 A）")
        if pending_d:
            parts.append(f"{len(pending_d)} 項待人工確認（分類 D）")
        if unclassified:
            parts.append(f"{len(unclassified)} 項掃描發現未分類（視同待確認）")
        return {
            "tier": 3,
            "label": "第三級",
            "reason": "、".join(parts) + "，建議完成修復/確認後再交付。",
        }

    accepted = [f for f in effective if f["category"] == "B"] + [m for m in manual if m.get("category") == "B"]
    if accepted:
        return {
            "tier": 2,
            "label": "第二級",
            "reason": (
                f"無高風險項目及待處理事項，但有 {len(accepted)} 項已知風險經工程團隊評估為可接受風險"
                "（分類為 B），詳見「完整分類明細」。"
            ),
        }

    return {"tier": 1, "label": "第一級", "reason": "掃描範圍內無待處理或已知風險項目，詳見「完整分類明細」。"}


def render_internal_banner(grade_info):
    """Tier 3/4 (and ungraded) reports are internal work-tracking documents,
    not deliverables — say so at the very top, before any number a reader
    could quote out of context."""
    if grade_info["tier"] in (1, 2):
        return ""
    # The tier itself is deliberately not printed: the case-level grade is an
    # internal gate (exit code) and does not appear in the report body. What a
    # reader of a stray draft needs is the handling instruction, not our
    # internal grading vocabulary.
    return (
        "**【內部工作版本 — 不可作為交付文件】**\n\n"
        "本報告尚有未完成處理或待確認之項目，僅供工程團隊追蹤使用；"
        "請於完成處理後重新產出報告，方可交付。\n\n"
        "---\n\n"
    )


def render_limitations():
    return (
        "本報告由本檢測工具產出，解讀時請留意以下範圍限制：\n\n"
        "- **偵測範圍**：靜態分析擅長偵測「程式寫法特徵層級」的問題（如重入模式、`tx.origin` 授權、"
        "弱亂數來源、未檢查的低階呼叫回傳值等）。\n"
        "- **已知偵測邊界**：業務邏輯層級的問題 —— 例如權限檢查的實作邏輯錯誤、應存在而未實作的保護、"
        "經濟模型層面的攻擊（搶跑、滑點）—— 靜態規則無法窮舉，本工具以情境庫逐合約比對補充涵蓋，"
        "但其涵蓋程度不等同於系統性審計。\n"
        "- **文件性質**：本報告為交付前之**自我檢查證明**，證明工程團隊已執行掃描並對每一筆發現"
        "完成逐筆判讀；其不構成、亦不取代由獨立第三方執行之完整安全審計。\n"
    )


def render_standards_appendix():
    """Recap of the per-finding disposition classes only. The case-level tier
    is not part of the delivered report (it drives the exit code and the
    internal-draft watermark), so its definitions are not reproduced here."""
    return (
        "本報告對每一筆發現標示兩個獨立欄位：**嚴重度**（Critical／High／Medium／Low／Informational，"
        "由工程團隊依實際影響判定）與**處置**（下列 A／B／C／D）。掃描工具自身回報的 impact 若與本報告"
        "呈現的嚴重度不同，該筆會並列印出兩者與調整理由。\n\n"
        "- **A｜已確認需修復**：確認為真實問題（多涉及資金流向或權限控制邏輯），必須修復。\n"
        "- **B｜已知風險但可接受**：問題確實存在，但經工程團隊評估風險可控（例如僅管理者可呼叫、"
        "另有其他層級防護），附具體理由後接受並於報告揭露。\n"
        "- **C｜誤報**：靜態分析限制造成的誤判，實際已有防護機制或該判斷邏輯不適用。\n"
        "- **D｜待確認**：尚無法判定歸屬者一律列此類；判讀信心不足時寧列 D，不猜測分類。"
        "此類項目均附「要確認什麼／由誰確認／兩種答案各自的處置」。\n"
        ""
    )


def all_items(effective, manual):
    """Scan findings and manual findings in one sequence, ordered by what the
    reader has to act on: disposition first (confirmed before accepted), then
    severity within each. Origin is deliberately not part of the ordering — a
    reader wants the problems grouped by what they must do about them, not by
    which of our two mechanisms happened to notice them (`source` records
    that)."""
    items = list(effective) + list(manual)
    return sorted(items, key=lambda i: (
        CATEGORY_ORDER.get(i.get("category"), 99),
        INDUSTRY_SEVERITY_RANK.get(i.get("severity"), 99),
    ))


def item_location(item):
    return f"{item.get('file', '?')}:{format_lines(item.get('lines'))}"


def item_title(item):
    # Lands in markdown table cells and "###" headings, so it has to stay on
    # one line — descriptions keep Slither's own line breaks now.
    desc = " ".join((item.get("description") or "").split())
    return item.get("title") or item.get("check") or desc[:60]


def render_severity_counts(effective, manual):
    """The report's single severity table, counted on the presented `severity`.

    The old report printed three different High counts in three sections (raw
    tool impact, non-false-positive impact, and A-class only). One number now,
    with the tool's own raw count stated once alongside it as context.
    """
    counts = {s: 0 for s in INDUSTRY_SEVERITIES}
    for item in list(effective) + list(manual):
        sev = item.get("severity")
        if sev in counts:
            counts[sev] += 1
    lines = ["| 嚴重程度 | 筆數 |", "|---|---|"]
    for sev in INDUSTRY_SEVERITIES:
        lines.append(f"| {sev} | {counts[sev]} |")
    lines.append(f"| **總計** | **{sum(counts.values())}** |")
    return "\n".join(lines) + "\n"


def render_classification_disclosure(effective):
    """State how many findings were decided by machine or carried over rather
    than judged this time. Without this line, "逐筆人工判讀" overstates what
    happened: a real run had 209 of 236 C-class findings auto-classified."""
    auto = [f for f in effective if f.get("auto_classified")]
    carried = [f for f in effective if f.get("carried_from_previous")]
    if not auto and not carried:
        return ""
    parts = []
    if auto:
        by_check = {}
        for f in auto:
            by_check[f["check"]] = by_check.get(f["check"], 0) + 1
        detail = "、".join(f"{k} {v} 筆" for k, v in sorted(by_check.items()))
        parts.append(f"{len(auto)} 筆由風格預分類自動判定（{detail}），非人工逐筆判讀")
    if carried:
        parts.append(f"{len(carried)} 筆沿用前次掃描的分類結果")
    return "\n> 揭露：上述筆數中，" + "；".join(parts) + "。\n"


def render_scope(scope, exclusion_reasons):
    if not scope:
        return "_未提供掃描範圍資料（Step 1 未寫入 scope.json）。_\n"
    files = scope.get("files") or []
    totals = scope.get("totals") or {}
    out = [
        f"本次檢測涵蓋以下 {totals.get('files', len(files))} 個 Solidity 原始檔"
        f"（合計 {totals.get('lines', 0)} 行）。此清單即本報告的效力邊界 —— "
        "未列於此的檔案不在本次檢測範圍內。\n",
        "| 檔案 | 行數 |",
        "|---|---|",
    ]
    for f in files:
        out.append(f"| `{f['path']}` | {f['lines']} |")

    excludes = scope.get("exclude_paths") or []
    if excludes:
        out += ["", "**排除的路徑**", "", "| 路徑 | 排除理由 |", "|---|---|"]
        for prefix in excludes:
            reason = (exclusion_reasons or {}).get(prefix) or (exclusion_reasons or {}).get(
                prefix.rstrip("/")
            ) or "未註明"
            out.append(f"| `{prefix}` | {reason} |")

    if files:
        out += ["", "<sub>檔案內容雜湊（SHA-256），供比對交付程式碼是否與受檢版本一致：</sub>", ""]
        for f in files:
            out.append(f"<sub>`{f['path']}` — `{f['sha256']}`</sub><br>")
    return "\n".join(out) + "\n"


def render_scope_note(md):
    """A deviation disclosure belongs beside the scope it qualifies, not in the
    protocol write-up: the scope section states file hashes as proof of what was
    audited, and this is where a caveat on those hashes has to be readable."""
    if not md:
        return ""
    return re.sub(r"^(#{2,5}) ", r"#\1 ", md.strip(), flags=re.M) + "\n\n"


def render_overview(overview_md):
    """Inlined verbatim: --overview supplies its own `##` section headings, so
    wrapping it in one more would render a page carrying nothing but a title.
    The placeholder does need a heading of its own, having no content to
    supply one."""
    if not overview_md:
        return (
            "### 協定理解摘要\n\n"
            "_未提供協定理解摘要。_ 本節原應說明受檢系統的運作方式、各合約職責與特權角色的實際權限範圍；"
            "缺少此節時，讀者無從判斷後續發現的業務影響。\n"
        )
    # Inlined under a top-level chapter now, so every heading is demoted one
    # level; authors keep writing `##`/`###` and the report decides the
    # hierarchy it needs. Deepest first, or a `##` promoted to `###` would be
    # demoted a second time by the next pass and collapse the nesting.
    return re.sub(r"^(#{2,5}) ", r"#\1 ", overview_md.strip(), flags=re.M) + "\n"


def render_methodology(env=None):
    """Numbered steps, in the shape a third-party audit report uses. Scope
    limitations live in their own section — stating them here as well made the
    method read as a disclaimer twice over."""
    return (
        "本次檢測依以下步驟執行：\n\n"
        "1. **靜態分析掃描**：以 Slither 對「掃描範圍」所列全部原始檔執行完整 detector 掃描。\n"
        "2. **逐筆判讀與補充比對**：對掃描產出的每一筆發現判定其處置分類並記錄判斷依據，"
        "工具回報的嚴重度與本報告呈現的嚴重度若有落差則逐筆附上調整理由；同時對範圍內每一份合約，"
        "逐條比對內部維護的邏輯漏洞情境庫（權限檢查實作、未保護的狀態變更、旗標未落實、價格源可操縱、"
        "記帳與實際結果脫鉤、簽章雜湊綁定範圍、可組合模組的交互失效等），並依受檢系統所屬業務領域"
        "比對該領域公開已知的事故模式，補靜態規則無法涵蓋的業務邏輯層級問題。\n"
        "3. **產出與覆核**：彙整為本報告，並對共用同一判斷理由的發現群組進行抽查。\n"
        + _toolchain_line(env)
    )


def _toolchain_line(env):
    """The versions the scan ran under, in one line.

    The report tells the client they can rerun the same tool and reconcile the
    numbers; that claim is empty without saying which version. This used to be
    a table of its own — it does not need a section, but it does need to be
    somewhere."""
    if not env:
        return ""
    parts = [
        f"Slither {env['slither_version']}" if env.get("slither_version") else "",
        f"solc {env['solc_version']}" if env.get("solc_version") else "",
        f"Foundry {env['forge_version'].replace('forge Version: ', '')}" if env.get("forge_version") else "",
    ]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return "\n本次掃描的工具版本：" + "、".join(parts) + "。重新掃描時使用相同版本，方能與本報告的數字逐筆對照。\n"


def render_scenario_coverage(coverage):
    if not coverage or not coverage.get("contracts"):
        return (
            "_未提供情境庫覆蓋紀錄。_\n\n"
            "**注意**：本報告的「檢測方法」宣稱已對每一份合約執行情境庫比對，但未附逐合約的覆蓋紀錄，"
            "該項宣稱因此無法被檢驗。\n"
        )
    lines = [
        "下表為情境庫逐合約的比對結果。「已查證」為前置條件成立、實際讀碼確認過的情境數；"
        "「不適用」為合約不具備該情境前置條件而跳過的情境數；「命中」列出對應的發現編號。\n",
        "| 合約 | 已查證 | 不適用 | 命中 |",
        "|---|---|---|---|",
    ]
    for row in coverage["contracts"]:
        hits = "、".join(row.get("hits") or []) or "—"
        lines.append(
            f"| `{row.get('file')}` | {len(row.get('checked') or [])} | "
            f"{len(row.get('not_applicable') or [])} | {hits} |"
        )
    return "\n".join(lines) + "\n"


CATEGORY_LABEL = {
    "A": "已確認需修復（A）",
    "B": "已知風險但可接受（B）",
    "C": "誤報（C）",
    "D": "待確認（D）",
    None: "未分類",
}

# Severities whose B/C findings are still written up individually. Anything
# below this goes to the one-page detector summary: the detail is what a
# client can challenge, and the judgements worth challenging are the ones on
# high-severity findings.
DETAILED_SEVERITIES = {"Critical", "High", "Medium"}

# Cyfrin-style reading labels: severity letter + sequence within that severity
# ([H-1], [M-2], ...). Deliberately DERIVED at render time rather than stored
# in classification.json: the label encodes severity, and severity is a Step 2
# human decision that can change — a stored one would silently go stale the
# first time a finding is re-graded. Rescan matching and carry-over key on the
# fingerprint (check + file + line), never on this, so deriving it is safe.
SEVERITY_CODE = {
    "Critical": "C",
    "High": "H",
    "Medium": "M",
    "Low": "L",
    "Informational": "I",
}


def is_real_finding(item):
    """Whether a finding is presented as an actual problem, as opposed to one
    that was examined and dismissed.

    Only these carry a [S-#] label and the full Description / Impact / PoC /
    Recommended Mitigation layout. A false positive dropped into the [H-n]
    sequence would read as a confirmed High to anyone scanning the report —
    the label is a claim about the finding, not just a bullet number."""
    return item.get("source") == "manual" or item.get("category") in ("A", "D", None)


CYFRIN_SECTIONS = (
    # A finding's heading is "[S-#] TITLE"; with no authored title it falls back
    # to the detector name ("reentrancy-eth"), which names the check rather than
    # the problem — the format asks for root cause + impact in the title itself.
    ("title", "標題"),
    ("explanation", "說明"),
    ("impact_detail", "影響"),
    ("proof_of_concept", "PoC"),
    ("remediation", "建議修法"),
)


def report_missing_sections(items, labels):
    """List real findings whose Cyfrin-style sections are still empty.

    A reminder rather than an error: the structure is being introduced over an
    existing body of findings, so blocking the build would mean no report at
    all until every one is written up. The report itself marks each gap 待補,
    so nothing silently reads as complete."""
    gaps = []
    for item in items:
        if not is_real_finding(item):
            continue
        present = dict(item)
        present["explanation"] = finding_explanation(item)
        missing = [
            zh for field, zh in CYFRIN_SECTIONS
            if not (present.get(field) or "").strip()
            # D findings answer "what to confirm" instead of proposing a fix.
            and not (field == "remediation" and item.get("category") == "D")
        ]
        if missing:
            label = labels.get(id(item))
            name = f"[{label}] " if label else ""
            gaps.append(f"{name}{item.get('id') or '未編號'}：缺 {'、'.join(missing)}")
    if gaps:
        print(f"提醒：{len(gaps)} 項發現的說明欄位尚未填寫，報告中以「待補」標示：")
        for g in gaps:
            print(f"  - {g}")


def finding_explanation(item):
    """The human account of the problem.

    Manual findings have no tool output — their `description` is already the
    human write-up, so it serves as the explanation rather than being labelled
    as something the scanner said."""
    text = (item.get("explanation") or "").strip()
    if text:
        return text
    if item.get("source") == "manual":
        return (item.get("description") or "").strip()
    return ""


def tool_description(item):
    """Slither's own words, or empty for a human-found issue."""
    if item.get("source") == "manual":
        return ""
    return (item.get("description") or "").strip()


REF_RE = re.compile(r"\b([A-Z]{2,6}-\d{2,})\b")


def relabel_refs(text, id_to_label):
    """Rewrite scan-id cross-references in human prose to the [S-#] labels.

    Done at render time, never in classification.json. The label is derived
    from severity, so it moves whenever a finding is re-graded or one is added
    ahead of it — prose rewritten to "同 [M-1]" would keep pointing at [M-1]
    after that slot became a different finding, and nothing would flag it.
    Authors keep writing the stable ISL-02, and every build resolves it to
    whatever that finding's label currently is.

    Ids with no label (false positives, accepted risks) are left alone: those
    findings keep their scan id as their heading, so the reference still lands.
    """
    if not text:
        return text
    return REF_RE.sub(
        lambda m: f"[{id_to_label[m.group(1)]}]" if m.group(1) in id_to_label else m.group(0),
        text,
    )


def assign_labels(items):
    """Map id(item) -> "H-1" over the real findings, in the order given."""
    seen = {}
    labels = {}
    for item in items:
        if not is_real_finding(item):
            continue
        code = SEVERITY_CODE.get(item.get("severity"), "X")
        seen[code] = seen.get(code, 0) + 1
        labels[id(item)] = f"{code}-{seen[code]}"
    return labels


def is_detailed(item, include_false_positives=False):
    if item.get("source") == "manual":
        return True
    if item.get("category") in ("A", "D", None):
        return True
    if item.get("category") == "C":
        # A false positive is something the report concluded is NOT a finding.
        # Off by default: listing seventeen of them after the real ones invites
        # the reader to treat the section as a mixed bag. On when the client
        # wants the tool's own output accounted for line by line.
        return include_false_positives and item.get("severity") in DETAILED_SEVERITIES
    return item.get("severity") in DETAILED_SEVERITIES


# Slither ends a reentrancy description with, for every state variable it
# touched, the full roster of other functions that variable is reachable from.
# On a contract the size of LoanManager that enumeration is ~85% of the
# description's bytes and repeats the same handful of names once per variable.
# It identifies the variable's blast radius, not the bug; the reader needs the
# external call and the write that follows it, which sit in the first few
# lines. Collapse each roster to its size and keep everything else verbatim.
XFUNC_HEADER_RE = re.compile(r"can be used in cross function reentrancies:$")
# Cap for descriptions that arrive already flattened to a single line — older
# classification.json files written before scan.py stopped collapsing newlines.
# Nothing can be re-segmented out of those reliably (Slither's own item
# separator, " - ", also occurs inside expressions like `dueDate_ - startDate_`),
# so the honest fallback is to truncate and point at the raw scan output.
FLAT_DESCRIPTION_CAP = 600
# A section keeps every item up to MAX_SECTION_ITEMS; past that it shows the
# first KEEP_SECTION_ITEMS and reports how many were left out. Sized so the
# lists that carry meaning (the state variables written after an external call
# — typically a handful) survive intact, while the roster-shaped ones (every
# file sharing a pragma) collapse.
MAX_SECTION_ITEMS = 8
KEEP_SECTION_ITEMS = 5
# A single item is one fact (one call site, one write), so it is kept whole
# well past normal prose length — but a struct literal spanning a whole
# constructor still has to stop somewhere.
MAX_ITEM_CHARS = 400
# No verbatim run of tool output longer than this may reach the report. Checked
# against the finished markdown so the invariant survives future renderers, not
# just this one. See assert_no_raw_dump().
MAX_VERBATIM_RUN = 500


def clip_item(text: str) -> str:
    if len(text) <= MAX_ITEM_CHARS:
        return text
    return f"{text[:MAX_ITEM_CHARS].rstrip()}……（截斷，完整內容見掃描原始輸出）"


def assert_no_raw_dump(markdown: str, scan_list) -> None:
    """Fail the build if a scan finding's description reached the report as one
    verbatim run.

    format_description() is the only sanctioned way tool output enters the
    report, and it always either splits the description into sections or
    truncates it. This checks the finished markdown instead of trusting that,
    so a future renderer that goes back to interpolating `description` directly
    — which is exactly how an 8000-character reentrancy paragraph got shipped —
    is caught at build time rather than in the delivered PDF.

    The test is deliberately per line, not over the whole document: the defect
    is a description collapsed onto ONE line. Normalising whitespace across the
    document instead would erase the very indentation that distinguishes a
    laid-out finding from a dump, and flag correctly rendered ones.
    """
    descriptions = []
    for f in scan_list:
        desc = " ".join((f.get("description") or "").split())
        if len(desc) > MAX_VERBATIM_RUN:
            descriptions.append((desc[:MAX_VERBATIM_RUN], f))
    offenders = OrderedDict()
    for line in markdown.splitlines():
        norm = " ".join(line.split())
        if len(norm) <= MAX_VERBATIM_RUN:
            continue
        for prefix, f in descriptions:
            if prefix in norm:
                offenders[f"{f.get('check')} @ {f.get('file')}:{format_lines(f.get('lines'))}"] = True
    if offenders:
        print(
            f"報告中出現掃描工具原始描述的逐字傾印（超過 {MAX_VERBATIM_RUN} 字元），未產出報告。\n"
            "工具輸出必須經 format_description() 分段與收合後才能寫入報告；"
            "若是 dev_note 直接貼上工具描述，請改寫為判斷理由。\n"
            "涉及的發現：",
            file=sys.stderr,
        )
        for o in offenders:
            print(f"  - {o}", file=sys.stderr)
        sys.exit(2)


def format_description(desc: str, label: str = "說明") -> list[str]:
    """Render a Slither description as readable markdown lines.

    Slither descriptions are indented trees whose leaves are often rosters —
    every file sharing a pragma, every function a state variable is reachable
    from. The parent line already says what the group is, so past a handful of
    entries the members stop informing and start burying the finding: the
    reentrancy description for a large contract runs to 8000 characters, ~85%
    of it those rosters. Long lists are replaced by their size with a pointer
    to the raw scan output; short ones are kept whole.

    Indentation depth is deliberately not used to decide this — Slither is not
    consistent about it (pragma nests its file list one level deeper than
    solc-version does), so the rule is the size of the list, which behaves the
    same for every detector.

    Returns a list of markdown lines so callers can splice them into the
    section they are building."""
    desc = (desc or "").rstrip()
    if not desc.strip():
        return []

    if "\n" not in desc:
        desc = desc.strip()
        if len(desc) <= FLAT_DESCRIPTION_CAP:
            return [f"**{label}**：{desc}", ""]
        return [
            f"**{label}**：{desc[:FLAT_DESCRIPTION_CAP].rstrip()}……",
            "",
            f"（原始描述共 {len(desc)} 字元，此處截斷；完整內容見掃描原始輸出。"
            "此筆的 classification.json 產生時描述仍被壓成單行，"
            "重新產生分類表即可還原分段。）",
            "",
        ]

    head = []
    sections = OrderedDict()          # section header -> [items]
    current = None                    # section the next item belongs to
    roster = None                     # (variable, [entries]) being collected
    reachable = OrderedDict()         # state variable -> reachable function count

    def close_roster(trailing_write=None):
        """Slither interleaves reentrancy information: each state-variable write
        is followed by that variable's roster, then the next write. Entries and
        writes carry identical indentation, so the only reliable boundary is
        that a write always sits immediately before the next roster header —
        that line is handed back here so it is recorded as the write it is
        rather than counted as roster noise."""
        nonlocal roster
        if roster is None:
            return
        var, entries = roster
        kept = [e for e in entries if e is not trailing_write]
        reachable[var] = reachable.get(var, 0) + len(kept)
        roster = None

    for raw in desc.split("\n"):
        if not raw.strip():
            continue
        line = raw.strip()
        is_item = line.startswith("-")
        item = line.lstrip("-").strip() if is_item else line

        if XFUNC_HEADER_RE.search(line):
            trailing = roster[1][-1] if (roster and roster[1]) else None
            close_roster(trailing_write=trailing)
            if trailing is not None and current is not None:
                sections[current].append(trailing)
            var = XFUNC_HEADER_RE.sub("", line).strip()
            var = re.sub(r"\s*\([^()]*#[^()]*\)\s*$", "", var).strip()
            roster = (var, [])
            continue

        if roster is not None and is_item:
            roster[1].append(item)
            continue

        close_roster()
        if item.endswith(":"):
            current = item
            sections.setdefault(current, [])
        elif is_item and current is not None:
            sections[current].append(item)
        else:
            head.append(item)

    close_roster()

    out = [f"**{label}**：", ""]
    out += [f"- {h}" for h in head]
    for header, items in sections.items():
        out.append(f"- {header}")
        # Slither repeats a write verbatim once per state variable it touches
        # (an event emission covering three variables is listed three times).
        items = list(OrderedDict.fromkeys(items))
        shown = items if len(items) <= MAX_SECTION_ITEMS else items[:KEEP_SECTION_ITEMS]
        out += [f"  - {clip_item(i)}" for i in shown]
        if len(shown) < len(items):
            out.append(f"  - （其餘 {len(items) - len(shown)} 項省略，清單見掃描原始輸出）")
    if reachable:
        names = "、".join(reachable)
        out.append(
            f"- 可跨函式重入的狀態變數共 {len(reachable)} 個（{names}），"
            f"合計可達函式 {sum(reachable.values())} 處；完整清單見掃描原始輸出。"
        )
    out.append("")
    return out

def render_finding_detail(item, label=None, id_to_label=None):
    label = label or item.get("id")
    rows = []
    # A labelled finding carries its severity in the label itself ([M-10] is a
    # Medium), so repeating it in the table is one more row to read for nothing.
    # Unlabelled ones (false positives, headed by their scan id) still need it.
    if not is_real_finding(item):
        sev = item.get("severity") or "—"
        impact = item.get("impact")
        if impact and IMPACT_AS_INDUSTRY.get(impact) != item.get("severity"):
            sev += f"（工具 impact：{impact}）"
        rows.append(("嚴重度", sev))
    # No 處置 row: every finding sits under a heading naming its disposition,
    # so repeating it per finding says the same thing twice.
    rows.append(("位置", f"`{item_location(item)}`"))
    id_to_label = id_to_label or {}
    ref = lambda t: relabel_refs(t, id_to_label)
    heading = f"[{label}] {item_title(item)}" if is_real_finding(item) else f"{item.get('id')}｜{item_title(item)}"
    out = [f"#### {heading}", ""]
    # Plain labelled lines rather than a table: two rows of metadata never
    # needed a grid, and a per-finding table was the thing that kept splitting
    # across page boundaries.
    out += [f"**{k}**：{v}" for k, v in rows]
    out.append("")
    # Only ever present on a downgrade, so the heading says so plainly. The
    # tool's own rating comes with it: a client who rescans will see High where
    # we wrote Medium, and an undeclared discrepancy reads worse than a
    # declared one.
    impact = item.get("impact")
    if item.get("severity_rationale"):
        note = ""
        if impact and IMPACT_AS_INDUSTRY.get(impact) != item.get("severity"):
            note = f"（掃描工具判定為 {impact}）"
        out += [f"**嚴重度異動**{note}：{ref(item['severity_rationale'])}", ""]

    if not is_real_finding(item):
        # Examined and dismissed: the load-bearing content is why it does not
        # apply. An "Impact" section for a false positive states a harm that
        # was just concluded not to exist.
        out += format_description(item.get("description"))
        note = (item.get("dev_note") or "").strip()
        if note:
            out += [f"**判斷依據**：{ref(note)}", ""]
        return "\n".join(out)

    def section(heading_text, text, missing_hint):
        body = ref((text or "").strip())
        if body:
            return [f"**{heading_text}**：{body}", ""]
        return [f"**{heading_text}**：（待補 —— {missing_hint}）", ""]

    # One 說明 per finding, whatever its source. Previously the human account
    # and the tool's own words were separate blocks, so a finding the tool
    # found carried two and a human-found one carried a single block — the
    # difference read as a difference in the findings, not in their origin.
    explanation = finding_explanation(item)
    if explanation:
        out += [f"**說明**：{ref(explanation)}", ""]
    elif tool_description(item):
        out += format_description(tool_description(item), label="說明")
    else:
        out += section("說明", "", "哪個函式、正常應如何運作、為何出錯")
    out += section("影響", item.get("impact_detail"), "具體危害與對應的業務損失")
    out += section("PoC", item.get("proof_of_concept"), "攻擊邏輯，或可重現的測試碼")

    # PoC now carries why a confirmed finding is real, so 判斷依據 would restate
    # it. An accepted risk has no PoC-shaped answer to "why is this tolerable",
    # so B keeps it — dropping it would leave the acceptance unexplained.
    note = (item.get("dev_note") or "").strip()
    if note and item.get("category") == "B":
        out += [f"**接受理由**：{ref(note)}", ""]
    if item.get("category") == "D":
        out += [
            "**待確認事項**：",
            "",
            f"- 要確認什麼：{ref(item.get('confirm_what')) or '—'}",
            f"- 由誰確認：{item.get('confirm_who') or '—'}",
            f"- 兩種答案各自的處置：{ref(item.get('confirm_branches')) or '—'}",
            "",
        ]
    else:
        out += section("建議修法", item.get("remediation"), "diff 或修改後的程式碼片段，與短期／長期建議")
    return "\n".join(out)


def render_result_totals(items, all_count, include_false_positives=False):
    """Counts before detail: a reader opening Audit Result should see the shape
    of the outcome before the first write-up, not have to tally 30 headings."""
    by_cat = OrderedDict()
    by_sev = OrderedDict((sev, 0) for sev in INDUSTRY_SEVERITIES)
    for i in items:
        cat = i.get("category")
        by_cat[cat] = by_cat.get(cat, 0) + 1
        sev = i.get("severity")
        if sev in by_sev:
            by_sev[sev] += 1
    rest = all_count - len(items)
    lead = f"本次共 {all_count} 項發現，本章逐筆列出其中 {len(items)} 項。"
    if rest > 0:
        excluded = (
            "低嚴重度（Low／Informational）且經判定為可接受風險或誤報者"
            if include_false_positives
            else "經查證為誤報者，以及低嚴重度且經判定為可接受風險者"
        )
        lead += f"其餘 {rest} 項為{excluded}，逐筆紀錄保留於工作底稿，可依需要調閱。"
    out = [lead, "", "| 嚴重度 | 筆數 |", "|---|---|"]
    out += [f"| {sev} | {n} |" for sev, n in by_sev.items()]
    out += ["", "| 處置分類 | 筆數 |", "|---|---|"]
    for cat in sorted(by_cat, key=lambda c: CATEGORY_ORDER.get(c, 99)):
        out.append(f"| {CATEGORY_LABEL.get(cat, cat or '未分類')} | {by_cat[cat]} |")
    out.append("")
    return "\n".join(out)


def render_findings_section(effective, manual, classification_provided, include_false_positives=False):
    if not classification_provided:
        return "_未提供分類資料（Step 2 未寫入 classification.json），無法列出發現明細。_\n"
    items = [i for i in all_items(effective, manual) if is_detailed(i, include_false_positives)]
    if not items:
        return "本次無需要個別說明的發現。\n"
    labels = assign_labels(items)
    id_to_label = {
        i.get("id"): labels[id(i)] for i in items if id(i) in labels and i.get("id")
    }

    out = [render_result_totals(items, len(effective) + len(manual), include_false_positives)]
    out.append(
        "編號 `[H-1]` 為嚴重度代碼（C 危急／H 高／M 中／L 低／I 資訊）加該嚴重度內的序號，"
        "僅指派給經判定確實成立、需要處置的發現；經查證為誤報或已接受之風險沿用掃描編號。\n"
    )
    # all_items() already orders by category then severity, so grouping is a
    # matter of emitting a heading when the category changes.
    current = object()
    for item in items:
        cat = item.get("category")
        if cat != current:
            current = cat
            out.append(f"### {CATEGORY_LABEL.get(cat, cat or '未分類')}\n")
        out.append(render_finding_detail(item, labels.get(id(item)), id_to_label))
    return "\n".join(out)


def render_toc(report_body):
    """Section list built from the assembled body, so it cannot drift."""
    heads = re.findall(r"^## (.+)$", report_body, re.M)
    return "\n".join(f"- {h}" for h in heads) + "\n"


def render_worksheet(effective, manual, dup_groups, coverage, review_text):
    """The internal companion document: everything the delivery report stops
    short of. Never rendered to PDF, and written outside the delivery folder."""
    out = [
        "# 工作底稿（內部）",
        "",
        "本檔為交付報告的內部工作底稿，**不隨交付物提供給甲方**：內容包含全量逐筆分類、"
        "複核提醒與完整覆蓋矩陣，寫作語氣以內部溝通為準。",
        "",
        "## 複核提醒",
        "",
        review_text.strip() or "（無）",
        "",
        "## 完整情境庫覆蓋矩陣",
        "",
    ]
    if coverage and coverage.get("contracts"):
        out += ["| 合約 | 已查證情境 | 不適用 | 命中 |", "|---|---|---|---|"]
        for row in coverage["contracts"]:
            out.append(
                f"| `{row.get('file')}` | {'、'.join(row.get('checked') or []) or '—'} | "
                f"{'、'.join(row.get('not_applicable') or []) or '—'} | "
                f"{'、'.join(row.get('hits') or []) or '—'} |"
            )
    else:
        out.append("（未提供）")
    out += ["", "## 全量逐筆分類", ""]
    for item in all_items(effective, manual):
        out.append(
            f"- **{item.get('id') or '未編號'}｜{item_title(item)}** — "
            f"{item_location(item)}｜severity {item.get('severity') or '—'}"
            f"／impact {item.get('impact') or '—'}"
            f"／{CATEGORY_LABEL.get(item.get('category'), item.get('category'))}"
            + ("｜自動預分類" if item.get("auto_classified") else "")
            + ("｜沿用前次" if item.get("carried_from_previous") else "")
        )
        note = (item.get("dev_note") or "").replace("\n", " ").strip()
        if note:
            out.append(f"  - 判斷依據：{note}")
    out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--classification")
    parser.add_argument("--env")
    parser.add_argument("--scope")
    parser.add_argument("--overview", help="Markdown file inlined as the protocol-overview section")
    parser.add_argument(
        "--include-false-positives",
        action="store_true",
        help="把經查證為誤報（C）的發現也逐筆列進報告。預設不列 —— 它們是「不是問題」的"
             "結論，與需要處置的發現混在一起會稀釋後者",
    )
    parser.add_argument(
        "--scope-note",
        help="Markdown inlined at the end of Audit Methodology and Scoping — "
             "deviations from the standard procedure that qualify what the scope "
             "section claims (e.g. source altered locally to make the scan run)",
    )
    parser.add_argument("--client", help="Client name for the cover page")
    parser.add_argument("--engagement-from")
    parser.add_argument("--engagement-to")
    parser.add_argument("--worksheet", help="Path to write the internal worksheet markdown to")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    before = load_json(args.before)
    classification = load_json(args.classification)
    env = load_json(args.env)
    scope = load_json(args.scope)
    def read_md(path):
        if not path:
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    overview_md = read_md(args.overview)
    scope_note_md = read_md(args.scope_note)

    scan_list = extract_findings(before)

    errors = []
    manual = []
    if classification is not None:
        effective, errors = reconcile(scan_list, classification)
        manual, manual_errors = validate_manual_findings(classification)
        errors += manual_errors
        errors += validate_finding_ids(classification)
        known_ids = {
            e.get("id")
            for key in ("findings", "manual_findings")
            for e in classification.get(key, [])
            if isinstance(e.get("id"), str)
        }
        errors += validate_top_level_keys(classification, known_ids)
    else:
        effective = [dict(f, id=None, category=None, dev_note=None) for f in scan_list]

    if errors:
        print("classification.json 驗證失敗，未產出報告。請修正以下問題後重跑：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    dup_groups = detect_duplicate_dev_notes(effective)
    if dup_groups:
        # Non-blocking, and no longer printed into the delivered report: the
        # spot-check reminder belongs to us, not to the client, so it goes to
        # stderr and to the worksheet. `cli.py review` is where it is meant to
        # be read, while Step 2 can still act on it.
        print(
            f"提醒：{len(dup_groups)} 組發現共用同一段 dev_note（達 {DUPLICATE_DEV_NOTE_THRESHOLD} 筆以上門檻），"
            "詳見工作底稿或 `cli.py review`，建議抽查後再交付。",
            file=sys.stderr,
        )

    os.makedirs(args.out_dir, exist_ok=True)
    grade_info = compute_grade(effective, manual, classification is not None)
    coverage = (classification or {}).get("scenario_coverage")
    exclusion_reasons = (classification or {}).get("scope_exclusion_reasons")

    engagement = "—"
    if args.engagement_from or args.engagement_to:
        engagement = f"{args.engagement_from or '—'} ~ {args.engagement_to or '—'}"
    elif env:
        engagement = env.get("scan_date", "—")

    total_items = len(effective) + len(manual)
    body = f"""## 檢測範圍與方法

### 掃描範圍

{render_scope(scope, exclusion_reasons)}
### 檢測方法

{render_methodology(env)}
### 範圍限制

{render_limitations()}
{render_scope_note(scope_note_md)}---

## 摘要

**受檢對象**：{args.client or '（未指定）'}
**檢測期間**：{engagement}
**受檢版本**：{(env or {}).get('git_commit') or 'N/A'}

本次共提出 {total_items} 項發現，依嚴重程度分布如下：

{render_severity_counts(effective, manual)}{render_classification_disclosure(effective)}
全部發現逐筆列於「檢測結果」，依處置分類分組。

{render_overview(overview_md)}
---

## 檢測結果

{render_findings_section(effective, manual, classification is not None, args.include_false_positives)}
### 附錄：發現處置分類

{render_standards_appendix()}"""

    title = f"{args.client} " if args.client else ""
    report = (
        f"# {title}智能合約安全檢測報告\n\n"
        f"**檢測工具**: Slither\n"
        f"**檢測日期**: {engagement}\n\n"
        "---\n\n"
        f"{render_internal_banner(grade_info)}"
        "## 目錄\n\n"
        f"{render_toc(body)}\n"
        "---\n\n"
        f"{body}"
    )

    ordered = all_items(effective, manual)
    detailed = [i for i in ordered if is_detailed(i, args.include_false_positives)]
    report_missing_sections(detailed, assign_labels(detailed))

    assert_no_raw_dump(report, scan_list)

    report_path = os.path.join(args.out_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"wrote {report_path}")

    if args.worksheet:
        review_lines = []
        for items in dup_groups:
            checks = sorted({i["check"] for i in items})
            ids = ", ".join(str(i.get("id")) for i in items)
            review_lines.append(f"- {len(items)} 筆共用同一段理由（{', '.join(checks)}）：{ids}")
        worksheet = render_worksheet(
            effective, manual, dup_groups, coverage, "\n".join(review_lines)
        )
        os.makedirs(os.path.dirname(os.path.abspath(args.worksheet)), exist_ok=True)
        with open(args.worksheet, "w", encoding="utf-8") as f:
            f.write(worksheet)
        print(f"wrote {args.worksheet}")

    exit_code = GATE_EXIT_BY_TIER[grade_info["tier"]]
    if exit_code == 0:
        print("閘門通過：本報告可作為交付文件（exit code 0）")
    else:
        blockers = [
            i.get("id") or "未編號"
            for i in all_items(effective, manual)
            if i.get("category") in ("A", "D", None) or (i.get("impact") == "High" and i.get("category") != "C")
        ]
        print(f"閘門未通過：本報告為內部工作版本，不可交付（exit code {exit_code}）")
        if blockers:
            print("卡住閘門的項目：" + ", ".join(dict.fromkeys(blockers)))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
