"""Build a complete markdown security-scan report from the artifacts a
security-scan skill run produces:

  --before          filtered `slither --json` output (project files only), pre-fix
  --after           filtered `slither --json` output (project files only), post-fix
  --classification  classification.json written during Step 2 (A/B/C + dev notes)
  --env             scan_env.json written during Step 1 (toolchain/version info)
  --out-dir         directory to write report.md and the comparison chart PNG into

classification.json / scan_env.json are optional: if missing, those report
sections are rendered with a note that Step 2/Step 1 metadata wasn't
captured, rather than failing outright.
"""
import argparse
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md_to_pdf import find_cjk_font  # noqa: E402

IMPACT_ORDER = ["High", "Medium", "Low", "Informational", "Optimization"]


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
        pass  # fall back to default font; labels below are ASCII-safe anyway

    labels = IMPACT_ORDER
    before_vals = [before_counts.get(l, 0) for l in labels]
    after_vals = [after_counts.get(l, 0) for l in labels]

    x = range(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.bar([i - width / 2 for i in x], before_vals, width, label="忽略前", color="#c0392b")
    ax.bar([i + width / 2 for i in x], after_vals, width, label="忽略後", color="#2e7d32")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Findings")
    ax.set_title("Findings by Severity: Before vs After")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


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
    lines = ["| 嚴重程度 | 忽略前 | 忽略後 | 差異 |", "|---|---|---|---|"]
    for lvl in IMPACT_ORDER:
        b, a = before_counts.get(lvl, 0), after_counts.get(lvl, 0)
        lines.append(f"| {lvl} | {b} | {a} | {a - b:+d} |")
    total_b, total_a = sum(before_counts.values()), sum(after_counts.values())
    lines.append(f"| **總計** | **{total_b}** | **{total_a}** | **{total_a - total_b:+d}** |")
    return "\n".join(lines) + "\n"


def render_classification_detail(classification):
    if not classification:
        return (
            "_未提供分類資料（Step 2 未寫入 classification.json）。_\n"
        )
    findings = classification.get("findings", [])
    if not findings:
        return "本次掃描沒有需要分類的發現。\n"

    label = {
        "A": "A. 可直接忽略（False Positive）",
        "B": "B. 已知風險但可接受（Accepted Risk）",
        "C": "C. 待人工確認",
    }
    lines = []
    for cat in ["A", "B", "C"]:
        items = [f for f in findings if f.get("category") == cat]
        lines.append(f"### {label[cat]}\n")
        if not items:
            lines.append("本次無此類項目。\n")
            continue
        for item in items:
            loc = f"{item.get('file', '?')}:{item.get('lines', '?')}"
            lines.append(f"**#{item.get('id')} `{item.get('check')}`** [{item.get('impact')}] — {loc}\n")
            desc = (item.get("description") or "").replace("\n", " ").strip()
            if desc:
                lines.append(f"- 原始描述：{desc}\n")
            note = item.get("dev_note")
            if note:
                lines.append(f"- Dev Note：{note}\n")
            lines.append("")
    return "\n".join(lines)


def render_c_class_appendix(classification):
    if not classification:
        return "_未提供分類資料，無法產生此附錄。_\n"
    findings = classification.get("findings", [])
    if not findings:
        return "本次掃描沒有任何發現，因此沒有項目需要分類。\n"
    c_items = [f for f in findings if f.get("category") == "C"]
    if not c_items:
        return "本次掃描沒有列入 C 類的項目 —— 所有發現皆已分類為 A（誤報）或 B（可接受風險）並附上理由。\n"
    lines = ["| # | Check | Impact | 位置 | 說明 |", "|---|---|---|---|---|"]
    for item in c_items:
        loc = f"{item.get('file', '?')}:{item.get('lines', '?')}"
        desc = (item.get("description") or "").replace("\n", " ").replace("|", "/").strip()
        lines.append(f"| {item.get('id')} | {item.get('check')} | {item.get('impact')} | {loc} | {desc[:150]} |")
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

    before_counts = severity_counts(before)
    after_counts = severity_counts(after)

    os.makedirs(args.out_dir, exist_ok=True)
    chart_path = os.path.join(args.out_dir, "severity_chart.png")
    make_chart(before_counts, after_counts, chart_path)

    scan_date = (env or {}).get("scan_date", "N/A")

    report = f"""# 智能合約安全檢測報告

**檢測工具**: Slither
**檢測日期**: {scan_date}

---

## 1. 掃描環境資訊

{render_env_table(env)}
---

## 2. 摘要統計

{render_summary_table(before_counts, after_counts)}
---

## 3. 忽略前後對照圖表

![Findings by severity, before vs after](severity_chart.png)

---

## 4. 完整分類明細

{render_classification_detail(classification)}
---

## 5. 附錄：C 類待人工確認清單

{render_c_class_appendix(classification)}
"""

    report_path = os.path.join(args.out_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"wrote {report_path}")
    print(f"wrote {chart_path}")


if __name__ == "__main__":
    main()
