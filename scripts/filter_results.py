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


def is_own_finding(detector: dict, src_prefixes: list[str]) -> bool:
    elements = detector.get("elements", [])
    for element in elements:
        rel = (element.get("source_mapping", {}) or {}).get("filename_relative") or ""
        if any(rel.startswith(prefix) for prefix in src_prefixes):
            return True
    if not elements:
        file, _ = _fallback_location(detector.get("description") or "")
        if file != "?":
            return any(file.startswith(prefix) for prefix in src_prefixes)
    return False


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
    args = parser.parse_args()

    with open(args.raw_json, encoding="utf-8") as f:
        data = json.load(f)

    detectors = data.get("results", {}).get("detectors", [])
    own = [d for d in detectors if is_own_finding(d, args.src_prefix)]

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
