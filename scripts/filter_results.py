"""Filter a raw `slither --json` output down to findings that touch the
project's own source files, dropping everything that only touches
third-party dependencies (e.g. lib/).

Usage:
    python3 filter_results.py <raw.json> <filtered.json> --src-prefix src/

`--src-prefix` may be repeated to allow multiple project source roots.
Matching is done against each element's source_mapping.filename_relative.
Detectors with an empty `elements` list (observed: unindexed-event-address)
fall back to parsing the file path out of the description text — see
_fallback_location().
"""
# Keeps annotations unevaluated so the PEP 604 `dict | None` below doesn't
# raise TypeError at import time on Python 3.9 — which is the system python
# on macOS, and the one report.py's interpreter probe picks first when it has
# fpdf2 + matplotlib installed. This one line is all that stands between the
# pipeline and running on 3.9; without it the probe selects an interpreter
# that then dies importing this module.
from __future__ import annotations

import argparse
import json
import re

# Some Slither detectors (observed: unindexed-event-address) report an empty
# `elements` list — there is no source_mapping anywhere in the finding. The
# only location signal left is embedded in the description/markdown text as
# `(path/File.sol#123)` or `(path/File.sol#123-145)`. Without this fallback,
# is_own_finding() silently treats every such finding as third-party noise —
# including ones about the project's own contracts — because the loop over
# `elements` never executes.
_FALLBACK_FILE_LINE_RE = re.compile(r"\(([\w./-]+\.sol)#(\d+)(?:-(\d+))?\)")


def _fallback_location(description: str) -> tuple[str, list[int]]:
    m = _FALLBACK_FILE_LINE_RE.search(description or "")
    if not m:
        return "?", []
    file = m.group(1)
    start = int(m.group(2))
    end = int(m.group(3)) if m.group(3) else start
    return file, list(range(start, end + 1))


def extract_findings(results_json: dict | None) -> list[dict]:
    """Flatten `slither --json` detectors into the flat fields the pipeline
    passes around (skeleton generation, report rendering, and the
    classification<->scan reconciliation). File/lines come from the first
    element that has a source mapping — keep this the single definition, so
    the fingerprint scan.py writes into classification_skeleton.json is the
    same one build_report.py matches against."""
    findings = []
    if not results_json:
        return findings
    for d in results_json.get("results", {}).get("detectors", []):
        file, lines = "?", []
        for el in d.get("elements", []):
            sm = el.get("source_mapping") or {}
            if sm.get("filename_relative"):
                file = sm["filename_relative"]
                lines = sm.get("lines") or []
                break
        if file == "?":
            file, lines = _fallback_location(d.get("description") or "")
        findings.append({
            "check": d.get("check", "?"),
            "impact": d.get("impact", "Informational"),
            "file": file,
            "lines": lines,
            # Slither descriptions embed tabs/newlines for terminal output;
            # collapse them — they break markdown tables and CJK fonts have
            # no glyph for \t.
            "description": " ".join((d.get("description") or "").split()),
        })
    return findings


def _detector_files(detector: dict) -> list[str]:
    elements = detector.get("elements", [])
    files = [
        (el.get("source_mapping", {}) or {}).get("filename_relative") or ""
        for el in elements
    ]
    if not elements:
        file, _ = _fallback_location(detector.get("description") or "")
        if file != "?":
            files = [file]
    return [f for f in files if f]


def is_excluded(detector: dict, exclude_paths: list[str] | None) -> bool:
    """True when any file this finding touches sits under an excluded prefix."""
    if not exclude_paths:
        return False
    return any(
        f.startswith(ex) for f in _detector_files(detector) for ex in exclude_paths
    )


def is_own_finding(detector: dict, src_prefixes: list[str], exclude_paths: list[str] | None = None) -> bool:
    """True when the finding touches the project's own source and is not excluded.

    `exclude_paths` carves mock/test scaffolding back out of an otherwise
    in-scope source root. Real case: a project keeps stubs in
    `contracts/fake/`, and every `locked-ether` hit came from those mocks —
    findings about code that is never deployed, competing for the same manual
    triage attention as findings about code that is. `--src-prefix` cannot
    express this because the stubs live *inside* the source root.

    Exclusion wins over inclusion: a finding is dropped when ANY file it
    touches is excluded, so a mock cannot drag real contracts into scope by
    appearing alongside them in one detector.
    """
    if is_excluded(detector, exclude_paths):
        return False
    return any(
        f.startswith(prefix) for f in _detector_files(detector) for prefix in src_prefixes
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_json")
    parser.add_argument("filtered_json")
    parser.add_argument(
        "--src-prefix",
        action="append",
        required=True,
        help="Path prefix (relative to project root) considered part of the project's own source. Repeatable.",
    )
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Path prefix to drop even when it sits inside --src-prefix, for mocks/stubs "
             "that are never deployed (e.g. contracts/fake/). Repeatable.",
    )
    args = parser.parse_args()

    with open(args.raw_json, encoding="utf-8") as f:
        data = json.load(f)

    detectors = data.get("results", {}).get("detectors", [])
    own = [d for d in detectors if is_own_finding(d, args.src_prefix, args.exclude_path)]

    data["results"]["detectors"] = own
    with open(args.filtered_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    counts = {}
    for d in own:
        counts[d.get("impact", "Unknown")] = counts.get(d.get("impact", "Unknown"), 0) + 1
    print(f"kept {len(own)}/{len(detectors)} findings touching {args.src_prefix}")
    print("by impact:", counts)


if __name__ == "__main__":
    main()
