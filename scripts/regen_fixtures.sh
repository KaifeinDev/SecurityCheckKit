#!/usr/bin/env bash
# Regenerate both regression fixtures' reports into a throwaway directory so a
# change to the report layer can be diffed against a known-good baseline.
#
# The fixtures ship their full Step 1/2 artifacts (results_*.json,
# classification.json, scan_env.json), so this needs neither slither nor forge.
# Markdown only (--skip-pdf): PDF layout is verified separately by eye, because
# the known fpdf2 subsetting bug (references/pitfalls.md #6) is silent.
#
# Usage: scripts/regen_fixtures.sh <out-root>
#   e.g. scripts/regen_fixtures.sh /tmp/sck-baseline
set -uo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:?usage: regen_fixtures.sh <out-root>}"
rm -rf "$OUT"; mkdir -p "$OUT"
: > "$OUT/exit_codes.txt"
for f in timelock-vault vulnerable-vault; do
  SRC="$KIT/test-fixtures/$f/security-scan-report"
  # vulnerable-vault never ran Step 3, so it has no results_after.json; fall
  # back to results_before.json the way the skill documents for that case.
  AFTER="$SRC/results_after.json"; [ -f "$AFTER" ] || AFTER="$SRC/results_before.json"
  mkdir -p "$OUT/$f"
  python3 "$KIT/scripts/cli.py" report \
    --before "$SRC/results_before.json" \
    --after "$AFTER" \
    --classification "$SRC/classification.json" \
    --env "$SRC/scan_env.json" \
    --out-dir "$OUT/$f" --skip-pdf > "$OUT/$f/stdout.txt" 2> "$OUT/$f/stderr.txt"
  echo "$f exit=$?" >> "$OUT/exit_codes.txt"
done
cat "$OUT/exit_codes.txt"
