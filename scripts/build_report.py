"""Build a complete markdown security-scan report from the artifacts a
security-scan skill run produces:

  --before          filtered `slither --json` output (project files only), pre-suppression
  --after           filtered `slither --json` output (project files only), post-suppression
  --classification  classification.json written during Step 2 (A/B/C/D + dev notes,
                    plus optional manual_findings[] from human review)
  --env             scan_env.json written during Step 1 (toolchain/version info)
  --out-dir         directory to write report.md and the comparison chart PNG into

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
from md_to_pdf import find_cjk_font  # noqa: E402

IMPACT_ORDER = ["High", "Medium", "Low", "Informational", "Optimization"]
# Manual findings can be "Critical" (MANUAL_SEVERITIES), scan findings top
# out at "High" (Slither's own scale) — one combined rank so both kinds can
# sort into a single summary table together.
SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Informational": 4, "Optimization": 5}
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
# B/C are the only categories a suppression comment may back (see the A/D
# "不得抑制" rule in render_standards_appendix) — the same dev_note field is
# reused for both, but the label must say which kind of justification it is.
SUPPRESSIBLE_CATEGORIES = {"B", "C"}


def dev_note_label(category, actually_suppressed):
    """`category in SUPPRESSIBLE_CATEGORIES` only means B/C is ELIGIBLE for a
    suppression comment — it says nothing about whether one was actually
    added. Conflating the two previously made every B/C item claim "已加上
    抑制註解" regardless of whether Step 3 had even run, which is a false
    statement whenever before==after (Step 3 not executed) or during partial
    Step 3 execution (only some B/C items covered so far). `actually_suppressed`
    must be independently verified — see render_classification_detail — by
    checking whether the finding is actually absent from the --after scan."""
    if category in SUPPRESSIBLE_CATEGORIES and actually_suppressed:
        return "備註（已加上抑制註解）"
    return "備註"
# Manual findings are human-judged, so "Critical" is allowed even though
# Slither's own scale tops out at High. For grading, Critical >= High.
MANUAL_SEVERITIES = {"Critical", "High", "Medium", "Low", "Informational"}
# A manual finding can't be a false positive of a tool — if human review
# concludes it isn't a problem, it should be removed from the list, not
# classified C.
MANUAL_CATEGORIES = {"A", "B", "D"}

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


def make_chart(before_counts, after_counts, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    try:
        font_path = find_cjk_font()
        font_manager.fontManager.addfont(font_path)
        cjk_family = font_manager.FontProperties(fname=font_path).get_name()
        matplotlib.rcParams["font.family"] = cjk_family
    except SystemExit:
        pass  # fall back to default font; CJK labels degrade but the chart still renders

    labels = IMPACT_ORDER
    before_vals = [before_counts.get(l, 0) for l in labels]
    after_vals = [after_counts.get(l, 0) for l in labels]

    x = range(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(7, 3.2))
    # BSOS 文件規格設計系統 v1.0 §2.2 Colorful 700 層級：Red 700（工具原始輸出）
    # 與 Blue 700（交付版掃描結果），與 md_to_pdf.py 的 RED_700/BLUE_700 對齊，
    # 讓圖表與報告正文（標題色、Critical/High 底色）共用同一套色票。
    ax.bar([i - width / 2 for i in x], before_vals, width, label="工具原始輸出", color="#8E3128")
    ax.bar([i + width / 2 for i in x], after_vals, width, label="交付版掃描結果", color="#24487F")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("發現數量")
    ax.set_title("各嚴重度發現數量：工具原始輸出 vs 交付版掃描結果", loc="left")
    # 依 §2 圖表規範：不加外框陰影，只保留淺色水平格線與中性灰軸線，圖例不加框。
    ax.legend(frameon=False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#E4E4E7", linewidth=0.8)  # Gray 200
    ax.xaxis.grid(False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#A1A1AA")  # Gray 400
    ax.tick_params(axis="both", length=0, colors="#52525B")  # Gray 600
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


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
        parts = []
        if high_scan:
            parts.append(f"{len(high_scan)} 項高嚴重度掃描發現尚未排除（非誤報）")
        if high_manual:
            parts.append(f"{len(high_manual)} 項人工複核判定之危急／高風險")
        return {
            "tier": 4,
            "label": "第四級",
            "reason": "偵測到 " + "、".join(parts) + "，需修復並重新掃描後才可交付。",
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
    status = grade_info["label"] or "尚未評估（缺少 Step 2 分類資料）"
    return (
        "**【內部工作版本 — 不可作為交付文件】**\n\n"
        f"本報告資安等級為：{status}。依交付規範，此狀態僅供工程團隊追蹤修復與確認進度；"
        "請於完成處理後重新掃描並產出第一級或第二級報告，方可交付甲方。\n\n"
        "---\n\n"
    )


def render_triage_summary(effective):
    """A/B/C/D breakdown of the scan's own findings, independent of severity.

    Placed ahead of the severity table deliberately: a reader deciding
    whether to trust this report cares first about "how much of what the
    tool flagged was actually real" (audit quality/signal-to-noise), not
    "how many Highs are left" (remediation priority — that's a different
    question, answered by the severity table right after this one).
    """
    counts = {"A": 0, "B": 0, "C": 0, "D_or_unclassified": 0}
    for f in effective:
        cat = f["category"]
        if cat == "A":
            counts["A"] += 1
        elif cat == "B":
            counts["B"] += 1
        elif cat == "C":
            counts["C"] += 1
        else:  # "D" or None (unclassified) — both mean "not yet resolved"
            counts["D_or_unclassified"] += 1
    total = len(effective)
    if total == 0:
        return ""
    pct = lambda n: f"{n / total * 100:.0f}%"
    lines = [
        f"| 分類 | 筆數 | 佔比 | 意思 |",
        f"|---|---|---|---|",
        f"| 真漏洞（A） | {counts['A']} | {pct(counts['A'])} | 逐筆確認，程式碼需要修改 |",
        f"| 可接受風險（B） | {counts['B']} | {pct(counts['B'])} | 工具描述的行為真實存在，經確認在此情境下不構成安全問題 |",
        f"| 誤報（C） | {counts['C']} | {pct(counts['C'])} | 工具的判斷邏輯本身不適用 |",
    ]
    if counts["D_or_unclassified"]:
        lines.append(
            f"| 待確認／未分類 | {counts['D_or_unclassified']} | {pct(counts['D_or_unclassified'])} | "
            "尚未有足夠把握判斷，依規則計入判級時視同 D |"
        )
    return (
        f"掃描工具本身找到 **{total}** 筆，經逐筆分類複核：\n\n" + "\n".join(lines) + "\n"
    )


def render_executive_summary(grade_info, before_counts, after_counts, manual, before_after_identical, effective):
    if grade_info["tier"] is None:
        return f"_{grade_info['reason']}_\n"
    total_before = sum(before_counts.values())
    total_after = sum(after_counts.values())
    manual_note = f"另有 {len(manual)} 筆由人工複核提出、非掃描工具產出的發現（見「人工複核發現」章節）。" if manual else ""
    note = ""
    if before_after_identical:
        note = (
            "\n> 註：本次「工具原始輸出」與「交付版掃描結果」完全相同 —— 代表未加入任何抑制註解"
            "（Step 3 尚未執行，或本案沒有需要標註的 B/C 類項目），並非比對失敗。"
            "各項目的實際處理狀態見「完整分類明細」。\n"
        )
    return (
        f"**本案資安等級：{grade_info['label']}**"
        "（各等級之定義與判定條件見「附錄二：發現分類與資安等級評定標準」）\n\n"
        f"{grade_info['reason']}\n\n"
        f"{render_triage_summary(effective)}\n"
        f"掃描工具原始輸出共 {total_before} 項；交付版掃描結果為 {total_after} 項"
        "（此為甲方以相同工具版本重新掃描交付程式碼時可重現的數字，兩者差異之逐筆理由見「完整分類明細」）。"
        f"{manual_note}\n"
        f"{note}"
    )


def render_limitations():
    return (
        "本報告由 Slither 靜態分析工具掃描產生，並經工程團隊逐筆人工分類複核。解讀本報告時，"
        "請留意以下範圍限制：\n\n"
        "- **偵測範圍**：靜態分析擅長偵測「程式寫法特徵層級」的問題（如重入模式、`tx.origin` 授權、"
        "弱亂數來源、未檢查的低階呼叫回傳值等）。\n"
        "- **已知偵測邊界**：業務邏輯層級的問題 —— 例如權限檢查的實作邏輯錯誤、應存在而未實作的保護、"
        "經濟模型層面的攻擊（搶跑、滑點）—— 不在靜態分析工具的可偵測範圍內。本報告的"
        "「人工複核發現」章節記錄工程團隊在分類複核過程中以人工方式補充發現的此類問題，"
        "但人工複核的覆蓋程度不等同於系統性審計。\n"
        "- **文件性質**：本報告為交付前之**自我檢查證明**，證明工程團隊已執行掃描並對每一筆發現"
        "完成逐筆判讀；其不構成、亦不取代由獨立第三方執行之完整安全審計。\n"
    )


def render_env_table(env):
    if not env:
        return "_未提供掃描環境資訊（Step 1 未寫入 scan_env.json）。_\n"
    rows = [
        ("掃描時間", env.get("scan_date", "N/A")),
        ("專案路徑", env.get("project_path", "N/A")),
        ("Git commit", env.get("git_commit") or "N/A（非 git 專案或未提供）"),
        ("Solidity / solc 版本", env.get("solc_version", "N/A")),
        ("Slither 版本", env.get("slither_version", "N/A")),
        ("Foundry (forge) 版本", env.get("forge_version", "N/A")),
    ]
    lines = ["| 項目 | 內容 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    deps = env.get("dependencies") or []
    if deps:
        lines.append("")
        lines.append("**相依套件版本**")
        lines.append("")
        lines.append("| 套件 | 版本 |")
        lines.append("|---|---|")
        for dep in deps:
            lines.append(f"| {dep.get('name', 'N/A')} | {dep.get('version', 'N/A')} |")
    return "\n".join(lines) + "\n"


def render_summary_table(before_counts, after_counts):
    intro = (
        "「工具原始輸出」為 Slither 掃描的未經處理結果；「交付版掃描結果」為對含抑制註解之交付版程式碼"
        "重新掃描的結果 —— **亦即甲方使用相同版本 Slither（見「掃描環境資訊」）對交付程式碼自行掃描時，"
        "可重現的數字**。兩者的差異全部來自經人工分類為 B（可接受風險）或 C（誤報）並加上抑制註解的項目，"
        "逐筆理由與註解位置見「完整分類明細」。\n\n"
        "嚴重程度沿用掃描工具原文的五個等級：High、Medium、Low、Informational、Optimization。\n"
    )
    lines = ["| 嚴重程度 | 工具原始輸出 | 交付版掃描結果 | 差異 |", "|---|---|---|---|"]
    for lvl in IMPACT_ORDER:
        b, a = before_counts.get(lvl, 0), after_counts.get(lvl, 0)
        lines.append(f"| {lvl} | {b} | {a} | {a - b:+d} |")
    total_b, total_a = sum(before_counts.values()), sum(after_counts.values())
    lines.append(f"| **總計** | **{total_b}** | **{total_a}** | **{total_a - total_b:+d}** |")
    return intro + "\n" + "\n".join(lines) + "\n"


def render_findings_summary_table(effective, manual, classification_provided):
    """One row per finding that actually needs a decision or action: A-class
    scan findings, plus every manual finding (which by definition is never a
    false positive — see MANUAL_CATEGORIES). B/C scan findings are excluded
    on purpose: they're already covered exhaustively in the classification
    detail section, and listing all 100+ of them here would bury the
    handful that matter under noise a reader has to scroll past.

    This complements — does not replace — the severity-count table:
    severity counts answer "how bad is what's left"; this table answers
    "which specific items, and what's the status of each" at a glance,
    before the reader has to open individual finding write-ups."""
    if not classification_provided:
        return "_未提供分類資料（Step 2 未寫入 classification.json），無法列出總表。_\n"
    rows = []
    for f in effective:
        if f["category"] == "A":
            ident = f"#{f['id']}" if f["id"] is not None else "未編號"
            rows.append((SEVERITY_RANK.get(f["impact"], 99), ident, f["check"], f["impact"], f.get("status") or DEFAULT_STATUS))
    for m in manual:
        title = m.get("title") or (m.get("description") or "")[:40]
        rows.append((SEVERITY_RANK.get(m.get("severity"), 99), str(m.get("id")), title, m.get("severity"), m.get("status") or DEFAULT_STATUS))
    if not rows:
        return "本次無需要決策或處理的發現（所有掃描發現皆為 B/C 類，且無人工複核發現）。\n"
    rows.sort(key=lambda r: r[0])
    lines = ["| 編號 | 標題 | 嚴重度 | 狀態 |", "|---|---|---|---|"]
    for _, ident, title, severity, status in rows:
        lines.append(f"| {ident} | {title} | {severity} | {status} |")
    return "\n".join(lines) + "\n"


def render_manual_findings(manual, classification_provided):
    if not classification_provided:
        return "_未提供分類資料（Step 2 未寫入 classification.json），人工複核結果不明。_\n"
    if not manual:
        return "本次人工複核未提出掃描工具輸出以外的額外發現。\n"
    intro = (
        "以下項目由工程團隊在逐筆分類複核過程中以人工方式發現，**不在掃描工具的輸出之列**"
        "（多屬靜態分析無法偵測的邏輯層級問題，見「檢測方法與範圍限制」）。"
        "各筆開頭的「編號 M1、M2…」為人工複核發現之流水號：\n"
    )
    lines = [intro]
    for m in manual:
        title = m.get("title") or (m.get("description") or "")[:60]
        loc = f"{m.get('file', '?')}:{format_lines(m.get('lines'))}"
        scenario = f"／情境 {m['scenario']}" if m.get("scenario") else ""
        status = m.get("status") or DEFAULT_STATUS
        lines.append(
            f"- **編號 {m.get('id')}｜{title}**（嚴重度：{m.get('severity')}／分類 {m.get('category')}"
            f"{scenario}／狀態：{status}）— {loc}"
        )
        desc = (m.get("description") or "").replace("\n", " ").strip()
        if desc:
            lines.append(f"  - 說明：{desc}")
        note = m.get("dev_note")
        if note:
            # Manual findings have no Slither `check` name to target with a
            # `slither-disable` comment — the suppression-comment mechanism
            # is Slither-specific and never applies here, regardless of
            # category, so this always renders the plain label.
            lines.append(f"  - {dev_note_label(m.get('category'), actually_suppressed=False)}：{note}")
        lines.append("")
    return "\n".join(lines)


def render_duplicate_dev_note_warning(dup_groups):
    if not dup_groups:
        return "本次分類無單一理由套用於 5 筆以上發現的情況。\n"
    lines = [
        "以下每組發現皆共用**完全相同**的 dev_note 文字。共用本身不代表分類錯誤——同一根因造成的"
        "大量同類發現，合理的作法就是驗證一次、套用到全部——但這也是「模板化理由未逐筆查證」最容易"
        "藏身的地方。**請針對每一組，抽查至少一筆是否真的核對過該筆自己的檔案位置，而非直接沿用**：\n",
    ]
    for items in dup_groups:
        checks = sorted({f["check"] for f in items})
        files = sorted({f["file"].split("/")[-1] for f in items})
        # Enumerating every id turned this section into pages of "編號209, 編號210,
        # ..." for a 169-finding group -- the reviewer needs to know WHICH group to
        # spot-check, not to read every member. Show a handful as entry points and
        # keep the id list itself in classification.json.
        sample = [f"編號{f['id']}" if f["id"] is not None else "未編號" for f in items[:5]]
        more = f" 等 {len(items)} 筆" if len(items) > len(sample) else ""
        file_note = "、".join(files[:4]) + (f" 等 {len(files)} 檔" if len(files) > 4 else "")
        lines.append(
            f"- **{len(items)} 筆共用同一段理由**（detector：{', '.join(checks)}；涉及 {file_note}）："
            f"{', '.join(sample)}{more}"
        )
        note = items[0]["dev_note"].replace("\n", " ")
        if len(note) > 160:
            note = note[:160] + "…（全文見該筆分類明細）"
        lines.append(f"  - 理由摘要：{note}")
    return "\n".join(lines) + "\n"


def render_grouped_findings(items, with_locations):
    """Collapse findings into one row per (detector, rationale).

    A report is the conclusions, not the working. Listing every finding
    individually buries the handful that need action -- a real run produced
    377 C and 37 B findings against 8 actionable ones, with one B rationale
    repeated verbatim 21 times. Grouping is by (check, dev_note) rather than
    check alone, because the same detector can be judged differently in
    different files and merging those would misattribute the reasoning.

    `with_locations` keeps every file:line for B, where the client still has
    to find the code to decide whether to accept the risk; C only needs the
    file spread, since its conclusion is "no action". Per-finding records stay
    in classification.json either way, so a re-scan reconciles every row.
    """
    groups = {}
    for item in items:
        key = (item["check"], (item.get("dev_note") or "").strip())
        groups.setdefault(key, []).append(item)

    if with_locations:
        head = (f"本類共 {len(items)} 筆，歸併為 {len(groups)} 組判定。"
                "問題確實存在但經評估風險可控，逐組列出全部位置與接受理由。\n")
        cols = "| 檢查器 | 筆數 | 位置 | 接受理由 |"
    else:
        head = (f"本類共 {len(items)} 筆，歸併為 {len(groups)} 組判定。"
                "均為靜態分析器的誤判或無安全影響項目，不需處置。\n")
        cols = "| 檢查器 | 筆數 | 涉及檔案 | 判定理由 |"

    lines = [head, cols, "|---|---|---|---|"]
    for (check, note), group in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][0])):
        if with_locations:
            locs = "；".join(
                f"{item['file'].split('/')[-1]}:{format_lines(item['lines'])}" for item in group
            )
        else:
            files = sorted({item["file"].split("/")[-1] for item in group})
            locs = "、".join(files[:3]) + (f" 等 {len(files)} 檔" if len(files) > 3 else "")
        cell = (note or "—").replace("\n", " ").replace("|", "\\|")
        lines.append(f"| {check} | {len(group)} | {locs} | {cell} |")
    lines.append("")
    return lines


def render_classification_detail(effective, classification_provided, after_list):
    if not classification_provided:
        return "_未提供分類資料（Step 2 未寫入 classification.json）。_\n"
    if not effective:
        return "本次掃描沒有需要分類的發現。\n"

    # A finding only genuinely has a suppression comment applied if it no
    # longer shows up in the --after scan. Category alone (B/C) only means
    # "eligible", not "done" — see dev_note_label().
    after_fingerprints = {fingerprint(f["check"], f["file"], f["lines"]) for f in after_list}

    label = {
        "A": "A. 已確認漏洞，需修復",
        "B": "B. 已知風險但可接受",
        "C": "C. 可直接忽略（誤報）",
        "D": "D. 待人工確認",
        None: "未分類（視同待人工確認）",
    }
    intro = (
        "以下依處置分類列出本次掃描的發現。各筆開頭的「編號 N」為掃描發現之流水號"
        "（依掃描輸出順序編定，與「附錄一：待人工確認清單」的編號一致，便於對照）；"
        "無該類項目時以「—」表示。\n\n"
        "其中 B（已知風險）與 C（誤報）以彙總方式呈現：這兩類的結論分別是「已評估後接受」與"
        "「不需處置」，逐筆展開同一段理由只會稀釋真正需要行動的項目，故按「檢查器 × 判定理由」"
        "歸併；B 類仍逐組列出全部位置，供後續查核。A 與 D 類逐筆完整列出。每一筆的逐項紀錄"
        "均保存在 classification.json，重掃時可逐筆對帳，稽核性不受影響。\n"
    )
    lines = [intro]
    for cat in ["A", "B", "C", "D", None]:
        items = [f for f in effective if f["category"] == cat]
        if cat is None and not items:
            continue  # only surface the unclassified bucket when it's non-empty
        lines.append(f"### {label[cat]}\n")
        if not items:
            lines.append("—\n")
            continue
        if cat in ("B", "C"):
            lines.extend(render_grouped_findings(items, with_locations=(cat == "B")))
            continue
        for item in items:
            ident = f"編號 {item['id']}" if item["id"] is not None else "未編號（不在分類紀錄中）"
            loc = f"{item['file']}:{format_lines(item['lines'])}"
            # Status (remediation progress) only means something for A/D —
            # B/C are permanent verdicts (accepted risk / false positive),
            # not things with a "fixed yet?" lifecycle.
            status_suffix = f"／狀態：{item.get('status') or DEFAULT_STATUS}" if cat in ("A", "D") else ""
            lines.append(f"- **{ident}｜{item['check']}**（嚴重度：{item['impact']}{status_suffix}）— {loc}")
            desc = item["description"].replace("\n", " ").strip()
            if desc:
                lines.append(f"  - 原始描述：{desc}")
            if item.get("dev_note"):
                fp = fingerprint(item["check"], item["file"], item["lines"])
                suppressed = fp not in after_fingerprints
                lines.append(f"  - {dev_note_label(item['category'], suppressed)}：{item['dev_note']}")
            lines.append("")
    return "\n".join(lines)


def render_standards_appendix():
    """Bullet-point recap of the two-layer standard (per-finding A/B/C/D +
    whole-project Tier 1-4) so a client reading only the report can interpret
    the grade without asking for references/severity_grading.md."""
    return (
        "本報告的判讀採兩層標準：先對每一筆發現進行**處置分類**（A／B／C／D），"
        "再由全部分類結果推導**整案資安等級**（第一級～第四級）。兩者為獨立系統，字母與級數不可互相對照。\n\n"
        "**發現處置分類（逐筆判定）**\n\n"
        "- **A｜已確認漏洞，需修復**：確認為真實問題（多涉及資金流向或權限控制邏輯），必須修復；"
        "不得以註解抑制，抑制等同隱匿。\n"
        "- **B｜已知風險但可接受**：問題確實存在，但經工程團隊評估風險可控（例如僅管理者可呼叫、"
        "另有其他層級防護），附具體理由後可加註解抑制，並於報告揭露。\n"
        "- **C｜可直接忽略（誤報）**：靜態分析限制造成的誤判，實際已有防護機制；"
        "附具體理由後可加註解抑制。\n"
        "- **D｜待人工確認**：尚無法判定歸屬者一律列此類，不得抑制；判讀信心不足時寧列 D，不猜測分類。\n"
        "- **人工複核發現**：掃描工具輸出之外、由人工閱讀原始碼發現的問題，僅得分類 A／B／D；"
        "經確認非問題者直接自清單移除，不設誤報分類。\n\n"
        "**整案資安等級（以下由第一級至第四級列出定義；實際評定則由高至低逐條檢查，符合任一條件即定為該級）**\n\n"
        "- **第一級｜可直接交付**：掃描範圍內所有發現均確認為誤報，且無待處理之人工複核發現。\n"
        "- **第二級｜可交付，需揭露已知風險**：無下列第三、四級情況，但存在 B 類已知風險。\n"
        "- **第三級｜待確認，不建議交付**：無下列第四級情況，但存在任何 A（已確認未修復）或 D（待確認）項目，"
        "或有掃描發現未完成分類（未分類一律視同 D，不視同已解決）。\n"
        "- **第四級｜不通過**：存在任一「High」嚴重度且非誤報的掃描發現，或任一「Critical／High」的人工複核發現。"
        "高嚴重度項目不得以「可接受風險」定級 —— 只能修復，或確認為誤報。\n"
        "- 未提供分類結果時不予評級，報告一律視為內部工作版本。\n"
    )


def render_pending_appendix(effective, manual, classification_provided):
    if not classification_provided:
        return "_未提供分類資料，無法產生此附錄。_\n"
    pending = [f for f in effective if f["category"] in ("D", None)]
    pending_manual = [m for m in manual if m.get("category") == "D"]
    if not effective and not manual:
        return "本次掃描沒有任何發現，因此沒有項目需要分類。\n"
    if not pending and not pending_manual:
        return (
            "本次沒有待人工確認的項目 —— 所有掃描發現皆已分類為 A（已確認需修復）、"
            "B（可接受風險）或 C（誤報）並附上理由。\n"
        )
    lines = ["| 編號 | 項目 | 嚴重度 | 位置 | 說明 |", "|---|---|---|---|---|"]
    for item in pending:
        ident = item["id"] if item["id"] is not None else "—"
        loc = f"{item['file']}:{format_lines(item['lines'])}"
        desc = item["description"].replace("\n", " ").replace("|", "/").strip()[:150]
        if item["category"] is None:
            desc = f"【未分類】{desc}"
        lines.append(f"| {ident} | {item['check']} | {item['impact']} | {loc} | {desc} |")
    for m in pending_manual:
        loc = f"{m.get('file', '?')}:{format_lines(m.get('lines'))}"
        desc = (m.get("description") or "").replace("\n", " ").replace("|", "/").strip()[:150]
        lines.append(f"| {m.get('id')} | {m.get('title') or '人工複核發現'} | {m.get('severity')} | {loc} | {desc} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--classification")
    parser.add_argument("--env")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    before = load_json(args.before)
    after = load_json(args.after)
    classification = load_json(args.classification)
    env = load_json(args.env)

    scan_list = extract_findings(before)
    after_list = extract_findings(after)

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
        # Non-blocking — this is a nudge for human re-review, not a hard
        # validation failure. See detect_duplicate_dev_notes() for why it
        # can't safely be an error.
        print(
            f"提醒：{len(dup_groups)} 組發現共用同一段 dev_note（達 {DUPLICATE_DEV_NOTE_THRESHOLD} 筆以上門檻），"
            "已收錄進報告「複核提醒」章節，建議抽查後再交付。",
            file=sys.stderr,
        )

    before_counts = severity_counts(before)
    after_counts = severity_counts(after)
    before_after_identical = before is not None and after is not None and before == after

    os.makedirs(args.out_dir, exist_ok=True)
    chart_path = os.path.join(args.out_dir, "severity_chart.png")
    make_chart(before_counts, after_counts, chart_path)

    scan_date = (env or {}).get("scan_date", "N/A")
    grade_info = compute_grade(effective, manual, classification is not None)

    report = f"""# 智能合約安全檢測報告

**檢測工具**: Slither
**檢測日期**: {scan_date}

---

{render_internal_banner(grade_info)}## 1. 摘要結論

{render_executive_summary(grade_info, before_counts, after_counts, manual, before_after_identical, effective)}
---

## 2. 待決策／待處理項目總表

以下只列出需要決策或行動的項目（掃描發現中的 A 類，以及全部人工複核發現——人工發現依規則不會是 C 類誤報）。
B/C 類掃描發現數量龐大且已判定為可接受風險或誤報，不在此重複列出，完整清單見「9. 完整分類明細」。
**狀態欄位反映本次產出報告當下的處置進度**，尚未標註狀態的項目預設顯示「{DEFAULT_STATUS}」。

{render_findings_summary_table(effective, manual, classification is not None)}
---

## 3. 檢測方法與範圍限制

{render_limitations()}
---

## 4. 掃描環境資訊

{render_env_table(env)}
---

## 5. 摘要統計

{render_summary_table(before_counts, after_counts)}
---

## 6. 掃描結果對照圖表

![各嚴重度發現數量對照：工具原始輸出與交付版掃描結果](severity_chart.png)

---

## 7. 人工複核發現

{render_manual_findings(manual, classification is not None)}
---

## 8. 複核提醒：重複使用的判斷理由

{render_duplicate_dev_note_warning(dup_groups)}
---

## 9. 完整分類明細

{render_classification_detail(effective, classification is not None, after_list)}
---

## 附錄一：待人工確認清單

{render_pending_appendix(effective, manual, classification is not None)}
---

## 附錄二：發現分類與資安等級評定標準

{render_standards_appendix()}
"""

    report_path = os.path.join(args.out_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"wrote {report_path}")
    print(f"wrote {chart_path}")

    exit_code = GATE_EXIT_BY_TIER[grade_info["tier"]]
    print(f"資安等級: {grade_info['label'] or '尚未評估'}")
    if exit_code == 0:
        print("閘門通過：本報告可作為交付文件（exit code 0）")
    else:
        print(f"閘門未通過：本報告為內部工作版本，不可交付（exit code {exit_code}）")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
