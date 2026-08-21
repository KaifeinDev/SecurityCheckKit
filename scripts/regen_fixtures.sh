#!/usr/bin/env bash
# Regenerate both regression fixtures' reports into a throwaway directory so a
# change to the report layer can be diffed against a known-good baseline.
#
# The fixtures ship their full Step 1/2 artifacts (results_before.json,
# classification.json, scan_env.json, scope.json) plus audit/overview.md, so
# this needs neither slither nor forge.
#
# The flags below must stay in step with how the committed fixture reports were
# produced. They did not, for a while: this script passed only --before,
# --classification and --env, so its output was missing the scope table, the
# per-file hashes and the protocol overview, and diffing it against the
# committed report.md showed hundreds of lines of difference that had nothing
# to do with the change under test — which defeats the one purpose it has.
#
# Markdown only (--skip-pdf): PDF layout is verified separately by eye, because
# the known fpdf2 subsetting bug (references/pitfalls.md #6) is silent.
#
# Usage: scripts/regen_fixtures.sh <out-root>
#   e.g. scripts/regen_fixtures.sh /tmp/sck-baseline
set -uo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
# Run the working tree, not whatever `veros` happens to be installed — the
# point is to test the code in front of you.
VEROS=(python3 "$KIT/veros/cli.py")
OUT="${1:?usage: regen_fixtures.sh <out-root>}"
CLIENT="（測試夾具）"
ENGAGED="2026-08-14"
rm -rf "$OUT"; mkdir -p "$OUT"
: > "$OUT/exit_codes.txt"
for f in timelock-vault vulnerable-vault; do
  FIXTURE="$KIT/test-fixtures/$f"
  SRC="$FIXTURE/security-scan-report"
  mkdir -p "$OUT/$f"
  "${VEROS[@]}" report \
    --before "$SRC/results_before.json" \
    --classification "$SRC/classification.json" \
    --env "$SRC/scan_env.json" \
    --scope "$SRC/scope.json" \
    --overview "$FIXTURE/audit/overview.md" \
    --client "$CLIENT" \
    --engagement-from "$ENGAGED" --engagement-to "$ENGAGED" \
    --worksheet "$OUT/$f/worksheet.md" \
    --out-dir "$OUT/$f" --skip-pdf > "$OUT/$f/stdout.txt" 2> "$OUT/$f/stderr.txt"
  echo "$f exit=$?" >> "$OUT/exit_codes.txt"
done
cat "$OUT/exit_codes.txt"
