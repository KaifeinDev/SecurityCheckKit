"""Step 1 of the security-scan pipeline, runnable standalone without Claude
Code: run Slither, filter to the project's own source (unless --full-audit),
and write scan_env.json for build_report.py to consume later.

Usage:
    python3 scan.py --out-dir /tmp/security-scan [--src-prefix src/] [--full-audit]
                    [--prev-classification /path/to/last/classification.json]

Writes into --out-dir:
    results_raw.json             - unfiltered `slither --json` output
    results_before.json          - filtered (or a copy of raw, if --full-audit)
    scan_env.json                - toolchain/version info for the report
    scope.json                   - the project's own .sol files with line count
                                   and sha256, plus the --exclude-path removals:
                                   what the report states as its scope, so the
                                   boundary of the self-check is on the record
    classification_skeleton.json - Step 2 starting point: every finding
                                   prefilled (id/check/impact/file/lines/
                                   description), category + dev_note left
                                   empty for the human pass. Copying facts by
                                   hand was the easiest way to desync the
                                   classification from the scan; prefilling
                                   removes that failure mode. With
                                   --prev-classification, findings matching a
                                   previous run also get category/dev_note
                                   carried over (tagged carried_from_previous)
                                   so only genuinely new findings need review.

Prints a summary table (check / impact / file:line / description) to stdout
so a human can eyeball findings before running the classification step.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_check import gather_scan_env  # noqa: E402
from filter_results import extract_findings, is_own_finding, is_excluded, _fallback_location  # noqa: E402
from build_report import IMPACT_AS_INDUSTRY  # noqa: E402


# Detectors that report code-style/readability observations rather than
# anything that can become a vulnerability. These dominate raw output by
# volume — a real benchmark run produced 443 own-code findings of which 179
# were naming-convention alone — and hand-classifying them one by one crowds
# out attention that belongs on the findings that matter.
#
# They are pre-classified as C rather than dropped: they still appear in the
# report, so the numbers stay reconcilable against a re-scan, and the
# `auto_classified` marker tells Step 2 exactly what was decided by machine.
# Keep this list conservative — a detector belongs here only if it can NEVER
# indicate a security problem. Anything arguable (solc-version, pragma,
# unused-state) stays out and gets human judgement.
STYLE_ONLY_CHECKS = {
    "naming-convention",
    "unindexed-event-address",
}

STYLE_DEV_NOTE = (
    "純命名/事件索引等風格檢查（{check}），不構成安全性問題，由 scan 依 STYLE_ONLY_CHECKS "
    "自動預分類為 C。如認為此筆有安全含義，清空 category 與 auto_classified 後重新判定。"
)


def _default_id_prefix(project_dir):
    """Finding ids need a stable per-project prefix; the directory name is the
    only project identity scan.py has. Non-alphabetic characters are dropped so
    a name like `bot-gold-token` yields BOT rather than BO-."""
    name = os.path.basename(os.path.abspath(project_dir))
    letters = "".join(ch for ch in name if ch.isalpha()).upper()
    return (letters[:3] or "PRJ")


def collect_scope(project_dir, src_prefixes, exclude_paths):
    """Enumerate the project's own .sol files with line count and content hash.

    This is what the report's scope section states to the client: a self-check
    proof with no stated boundary proves nothing, and --exclude-path removals
    were previously invisible in the delivered document.

    Deliberately unaffected by --full-audit: that flag widens which *findings*
    are kept, but the scope section answers "which of YOUR files did we scan",
    not "how many files did crytic-compile parse".
    """
    # Guard against a bare string being passed where a list is expected: it
    # would iterate per character, and a "/" character becomes an absolute
    # root path that walks the whole filesystem.
    if isinstance(src_prefixes, str):
        src_prefixes = [src_prefixes]
    if isinstance(exclude_paths, str):
        exclude_paths = [exclude_paths]
    prefixes = [p.lstrip("/") for p in (src_prefixes or ["src/"]) if p.strip("/")]
    prefixes = [p if p.endswith("/") else p + "/" for p in prefixes] or ["src/"]
    excludes = [p if p.endswith("/") else p + "/" for p in (exclude_paths or [])]
    files = []
    total_lines = 0
    for prefix in prefixes:
        root = os.path.join(project_dir, prefix)
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if not name.endswith(".sol"):
                    continue
                abs_path = os.path.join(dirpath, name)
                rel = os.path.relpath(abs_path, project_dir)
                if any(rel.startswith(x) for x in excludes):
                    continue
                try:
                    with open(abs_path, "rb") as fh:
                        blob = fh.read()
                except OSError:
                    continue
                lines = blob.count(b"\n") + (1 if blob and not blob.endswith(b"\n") else 0)
                files.append(
                    {"path": rel, "lines": lines, "sha256": hashlib.sha256(blob).hexdigest()}
                )
                total_lines += lines
    files.sort(key=lambda f: f["path"])
    return {
        "src_prefix": prefixes,
        "exclude_paths": excludes,
        "files": files,
        "totals": {"files": len(files), "lines": total_lines},
    }


def build_classification_skeleton(before_json, auto_style=True, id_prefix="PRJ"):
    """Prefill classification.json's findings[] straight from the scan output,
    leaving only the two human fields (category, dev_note) empty. Lines are
    collapsed to [min, max] — the same shape the reconciliation in
    build_report.py fingerprints on.

    With `auto_style` (default), findings whose check is in STYLE_ONLY_CHECKS
    are additionally pre-filled as category C with a stated reason, mirroring
    how carry_over_classifications() prefills from a previous run: the human
    reviews a marked decision instead of making it from scratch."""
    skeleton_findings = []
    for i, f in enumerate(extract_findings(before_json), start=1):
        lines = f["lines"]
        entry = {
            "id": f"{id_prefix}-{i:02d}",
            "scan_id": i,
            "source": "tool",
            "check": f["check"],
            "impact": f["impact"],
            # Pre-filled to the tool's own equivalent, so leaving it alone is
            # never a downgrade and never needs a rationale. Raising or lowering
            # it is the human's call in Step 2.
            "severity": IMPACT_AS_INDUSTRY.get(f["impact"], "Informational"),
            "severity_rationale": "",
            "file": f["file"],
            "lines": [min(lines), max(lines)] if lines else [],
            # Kept verbatim, newlines and all. Slither indents its descriptions
            # into sections ("External calls:", "State variables written after
            # the call(s):", ...) and flattening them to one line is what turns
            # a reentrancy finding into an unreadable 8000-character paragraph.
            # The report renderer needs that structure to lay the finding out.
            "description": f["description"],
            "category": "",
            "dev_note": "",
            "remediation": "",
        }
        if auto_style and f["check"] in STYLE_ONLY_CHECKS:
            entry["category"] = "C"
            entry["dev_note"] = STYLE_DEV_NOTE.format(check=f["check"])
            entry["auto_classified"] = "style"
        skeleton_findings.append(entry)
    return {
        "findings": skeleton_findings,
        "manual_findings": [],
        # Both are consumed by the report's scope / scenario-coverage sections;
        # present-but-empty so Step 2 sees they exist and need filling.
        "scenario_coverage": {"contracts": []},
        "scope_exclusion_reasons": {},
    }


def carry_over_classifications(skeleton, prev):
    """Prefill category/dev_note in a fresh skeleton from a previous run's
    classification.json, so a re-scan only asks the human about findings that
    are actually new. Matching is conservative: exact fingerprint (check +
    file + start line) first, then a check+file fallback that only fires when
    both sides have exactly one unmatched candidate — line numbers drift when
    suppression comments or unrelated edits shift the file, but an ambiguous
    match must not silently reuse the wrong dev_note. Everything unmatched
    stays blank (and unclassified findings can only lower the report grade).

    Carried entries are tagged with carried_from_previous so Step 2 can show
    the human which prefills to double-check. Previous manual_findings are
    copied wholesale — they describe code the tool can't see, so only a human
    re-read can retire them. Returns stats for the console summary."""
    prev_entries = prev.get("findings", [])
    unmatched_prev = set(range(len(prev_entries)))
    unmatched_new = set(range(len(skeleton["findings"])))
    stats = {"exact": 0, "fallback": 0, "resolved": [], "new": 0}

    def start_line(lines):
        return min(lines) if lines else None

    by_fp = {}
    for j, e in enumerate(prev_entries):
        key = (e.get("check"), e.get("file"), start_line(e.get("lines")))
        by_fp.setdefault(key, []).append(j)

    def adopt(new_idx, prev_idx, how):
        entry = prev_entries[prev_idx]
        unmatched_prev.discard(prev_idx)
        unmatched_new.discard(new_idx)
        if not (entry.get("category") or "").strip():
            return  # nothing useful to carry; still consumes the match
        f = skeleton["findings"][new_idx]
        f["category"] = entry["category"]
        f["dev_note"] = entry.get("dev_note", "")
        f["carried_from_previous"] = how
        stats[how] += 1

    for i in sorted(unmatched_new):
        f = skeleton["findings"][i]
        key = (f["check"], f["file"], start_line(f["lines"]))
        candidates = [j for j in by_fp.get(key, []) if j in unmatched_prev]
        if candidates:
            adopt(i, candidates[0], "exact")

    for i in sorted(unmatched_new):
        f = skeleton["findings"][i]
        same_new = [
            k for k in unmatched_new
            if (skeleton["findings"][k]["check"], skeleton["findings"][k]["file"]) == (f["check"], f["file"])
        ]
        same_prev = [
            j for j in unmatched_prev
            if (prev_entries[j].get("check"), prev_entries[j].get("file")) == (f["check"], f["file"])
        ]
        if len(same_new) == 1 and len(same_prev) == 1:
            adopt(i, same_prev[0], "fallback")

    stats["new"] = len(unmatched_new)
    stats["resolved"] = [
        f"id={prev_entries[j].get('id')} {prev_entries[j].get('check')} @ "
        f"{prev_entries[j].get('file')}:{start_line(prev_entries[j].get('lines'))}"
        for j in sorted(unmatched_prev)
    ]

    for m in prev.get("manual_findings", []):
        copied = dict(m)
        copied["carried_from_previous"] = "manual"
        skeleton["manual_findings"].append(copied)
    stats["manual"] = len(prev.get("manual_findings", []))
    return stats


def run_slither(project_dir, raw_json_path):
    proc = subprocess.run(
        ["slither", ".", "--json", raw_json_path],
        cwd=project_dir, capture_output=True, text=True, timeout=600,
    )
    # Slither exits non-zero whenever it has findings, that's not a failure.
    if not os.path.isfile(raw_json_path):
        raise SystemExit(
            f"slither did not produce {raw_json_path}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )


def print_summary(detectors):
    if not detectors:
        print("no findings")
        return
    print(f"{'check':<28} {'impact':<14} {'location':<40} description")
    print("-" * 110)
    for d in detectors:
        elements = d.get("elements", [])
        loc = "?"
        if elements:
            sm = elements[0].get("source_mapping", {}) or {}
            rel = sm.get("filename_relative", "?")
            lines = sm.get("lines", [])
            loc = f"{rel}:{lines[0]}" if lines else rel
        else:
            # Detectors with an empty `elements` list (observed:
            # unindexed-event-address) have no source_mapping to read here —
            # reuse the same description-text fallback filter_results.py uses,
            # so the terminal summary doesn't print "?" for a location that's
            # actually known and correctly populated in the skeleton/report.
            file, lines = _fallback_location(d.get("description") or "")
            if file != "?":
                loc = f"{file}:{lines[0]}" if lines else file
        desc = (d.get("description") or "").replace("\n", " ").strip()
        print(f"{d.get('check', '?'):<28} {d.get('impact', '?'):<14} {loc:<40} {desc[:60]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--src-prefix", action="append", default=[], help="Repeatable. Defaults to src/.")
    parser.add_argument("--full-audit", action="store_true", help="Keep findings from lib/ dependencies too")
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Path prefix to drop even when inside --src-prefix, for mocks/stubs that are "
             "never deployed (e.g. contracts/fake/). Repeatable.",
    )
    parser.add_argument(
        "--no-auto-style",
        action="store_true",
        help="Do not pre-classify pure style findings (naming-convention, "
             "unindexed-event-address) as C; leave every finding for manual classification.",
    )
    parser.add_argument(
        "--id-prefix",
        help="Uppercase project abbreviation for finding ids (e.g. BGT -> BGT-01). "
             "Defaults to the first three letters of the project directory name.",
    )
    parser.add_argument(
        "--prev-classification",
        help="Path to a previous run's classification.json: findings that match "
             "(check + file + start line, with a conservative check+file fallback "
             "for shifted lines) get their category/dev_note prefilled in the new "
             "skeleton, so Step 2 only reviews what actually changed.",
    )
    args = parser.parse_args()

    src_prefixes = args.src_prefix or ["src/"]
    os.makedirs(args.out_dir, exist_ok=True)

    raw_path = os.path.join(args.out_dir, "results_raw.json")
    before_path = os.path.join(args.out_dir, "results_before.json")
    env_path = os.path.join(args.out_dir, "scan_env.json")
    skeleton_path = os.path.join(args.out_dir, "classification_skeleton.json")
    scope_path = os.path.join(args.out_dir, "scope.json")

    print(f"running slither in {os.path.abspath(args.project_dir)} ...")
    run_slither(args.project_dir, raw_path)

    with open(raw_path, encoding="utf-8") as f:
        data = json.load(f)
    detectors = data.get("results", {}).get("detectors", [])

    if args.full_audit:
        # --exclude-path still applies: --full-audit widens scope to dependencies,
        # it does not mean "audit the mocks the project told us to ignore".
        kept = [d for d in detectors if not is_excluded(d, args.exclude_path)]
    else:
        kept = [d for d in detectors if is_own_finding(d, src_prefixes, args.exclude_path)]

    data["results"]["detectors"] = kept
    with open(before_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    env = gather_scan_env(args.project_dir)
    env["scan_date"] = datetime.datetime.now().isoformat()
    with open(env_path, "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)

    scope = collect_scope(args.project_dir, src_prefixes, args.exclude_path)
    with open(scope_path, "w", encoding="utf-8") as f:
        json.dump(scope, f, ensure_ascii=False, indent=2)

    id_prefix = args.id_prefix or _default_id_prefix(args.project_dir)
    skeleton = build_classification_skeleton(
        data, auto_style=not args.no_auto_style, id_prefix=id_prefix
    )
    carry_stats = None
    if args.prev_classification:
        with open(args.prev_classification, encoding="utf-8") as f:
            prev = json.load(f)
        carry_stats = carry_over_classifications(skeleton, prev)
    with open(skeleton_path, "w", encoding="utf-8") as f:
        json.dump(skeleton, f, ensure_ascii=False, indent=2)

    counts = {}
    for d in kept:
        counts[d.get("impact", "Unknown")] = counts.get(d.get("impact", "Unknown"), 0) + 1

    scope_desc = "all findings (--full-audit)" if args.full_audit else f"prefixes {src_prefixes}"
    if args.exclude_path:
        scope_desc += f", excluding {args.exclude_path}"
    print(f"kept {len(kept)}/{len(detectors)} findings ({scope_desc})")
    print(
        f"scope: {scope['totals']['files']} files / {scope['totals']['lines']} lines"
        + (f", excluded {args.exclude_path}" if args.exclude_path else "")
    )
    print("by impact:", counts)

    auto_styled = [f for f in skeleton["findings"] if f.get("auto_classified") == "style"]
    if auto_styled:
        by_check = {}
        for f in auto_styled:
            by_check[f["check"]] = by_check.get(f["check"], 0) + 1
        detail = ", ".join(f"{k} {v}" for k, v in sorted(by_check.items()))
        print(
            f"auto-classified as C (pure style, still in report): {len(auto_styled)} — {detail}\n"
            f"  Step 2 needs to classify the remaining "
            f"{len(skeleton['findings']) - len(auto_styled)}. Use --no-auto-style to disable."
        )
    print()
    print_summary(kept)
    print()
    print(f"wrote {raw_path}\nwrote {before_path}\nwrote {env_path}\nwrote {skeleton_path}")
    print()
    if carry_stats:
        print(f"沿用上次分類（{args.prev_classification}）：")
        print(f"  - {carry_stats['exact']} 筆完全比對沿用（check+file+起始行號一致）")
        if carry_stats["fallback"]:
            print(f"  - {carry_stats['fallback']} 筆以 check+file 比對沿用（行號有位移，已標記 carried_from_previous=fallback，請複核）")
        print(f"  - {carry_stats['new']} 筆為本次新出現，category/dev_note 留空待分類")
        if carry_stats["resolved"]:
            print(f"  - 上次分類檔有 {len(carry_stats['resolved'])} 筆在本次掃描已不存在（已修復或位置大幅變動，未帶入）：")
            for r in carry_stats["resolved"]:
                print(f"      {r}")
        if carry_stats["manual"]:
            print(f"  - 上次的 {carry_stats['manual']} 筆 manual_findings 已原樣帶入 —— 人工發現不隨掃描結果失效，"
                  "請逐筆重新確認仍然成立（已修復的直接刪除）")
        print()
    print("Step 2: 複製 classification_skeleton.json 為 classification.json，"
          "逐筆填入 category（A/B/C/D）與 dev_note；其餘欄位已預填，請勿改動"
          "（check/file/lines 是報告階段比對掃描結果的依據）。"
          "人工複核發現的工具外問題請寫進 manual_findings（格式見 SKILL.md），"
          "並依 references/logic_scan.md 的情境庫對每份合約跑一輪邏輯漏洞檢查。")


if __name__ == "__main__":
    main()
