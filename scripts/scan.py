"""Step 1 of the security-scan pipeline, runnable standalone without Claude
Code: run Slither, filter to the project's own source (unless --full-audit),
and write scan_env.json for build_report.py to consume later.

Usage:
    python3 scan.py --out-dir /tmp/security-scan [--src-prefix src/] [--full-audit]

Writes into --out-dir:
    results_raw.json    - unfiltered `slither --json` output
    results_before.json - filtered (or a copy of raw, if --full-audit)
    scan_env.json        - toolchain/version info for the report

Prints a summary table (check / impact / file:line / description) to stdout
so a human can eyeball findings before running the classification step.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_check import gather_scan_env  # noqa: E402
from filter_results import is_own_finding  # noqa: E402


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
        desc = (d.get("description") or "").replace("\n", " ").strip()
        print(f"{d.get('check', '?'):<28} {d.get('impact', '?'):<14} {loc:<40} {desc[:60]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--src-prefix", action="append", default=[], help="Repeatable. Defaults to src/.")
    parser.add_argument("--full-audit", action="store_true", help="Keep findings from lib/ dependencies too")
    args = parser.parse_args()

    src_prefixes = args.src_prefix or ["src/"]
    os.makedirs(args.out_dir, exist_ok=True)

    raw_path = os.path.join(args.out_dir, "results_raw.json")
    before_path = os.path.join(args.out_dir, "results_before.json")
    env_path = os.path.join(args.out_dir, "scan_env.json")

    print(f"running slither in {os.path.abspath(args.project_dir)} ...")
    run_slither(args.project_dir, raw_path)

    with open(raw_path, encoding="utf-8") as f:
        data = json.load(f)
    detectors = data.get("results", {}).get("detectors", [])

    if args.full_audit:
        kept = detectors
    else:
        kept = [d for d in detectors if is_own_finding(d, src_prefixes)]

    data["results"]["detectors"] = kept
    with open(before_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    env = gather_scan_env(args.project_dir)
    env["scan_date"] = datetime.datetime.now().isoformat()
    with open(env_path, "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)

    counts = {}
    for d in kept:
        counts[d.get("impact", "Unknown")] = counts.get(d.get("impact", "Unknown"), 0) + 1

    scope = "all findings (--full-audit)" if args.full_audit else f"prefixes {src_prefixes}"
    print(f"kept {len(kept)}/{len(detectors)} findings ({scope})")
    print("by impact:", counts)
    print()
    print_summary(kept)
    print()
    print(f"wrote {raw_path}\nwrote {before_path}\nwrote {env_path}")


if __name__ == "__main__":
    main()
