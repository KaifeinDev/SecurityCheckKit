"""Filter a raw `slither --json` output down to findings that touch the
project's own source files, dropping everything that only touches
third-party dependencies (e.g. lib/).

Usage:
    python3 filter_results.py <raw.json> <filtered.json> --src-prefix src/

`--src-prefix` may be repeated to allow multiple project source roots.
Matching is done against each element's source_mapping.filename_relative.
"""
import argparse
import json


def is_own_finding(detector: dict, src_prefixes: list[str]) -> bool:
    for element in detector.get("elements", []):
        rel = (element.get("source_mapping", {}) or {}).get("filename_relative") or ""
        if any(rel.startswith(prefix) for prefix in src_prefixes):
            return True
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
