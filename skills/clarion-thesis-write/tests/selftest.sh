#!/bin/bash
# Self-test for validate-page.py.
#
# A checker nobody tests is a checker that silently rots — which is exactly
# what happened before 2026-08-20, when two workspace rules pointed at a
# validate-page.py that did not exist and nothing noticed.
#
# Each fixture reproduces a bug class that actually shipped to production:
#   DEADPAGE  — RDDT: tab machinery referenced but never declared; the page
#               threw at render and served an error boundary to every visitor.
#   BLANKTAB  — DECK: tab ids derived from labels while guards used literal
#               ids; the panel painted on load and blanked on click.
#   GOODPAGE  — a known-clean page; guards against the checker becoming so
#               strict that it fails everything (the other way to lose trust).
#
# Run after ANY edit to validate-page.py. Exit 0 = the checker still works.

set -u
SCRIPT="$(dirname "$0")/../scripts/validate-page.py"
FIX="$(dirname "$0")/fixtures"
fails=0

expect() {  # expect <ticker> <expected-exit> <must-contain>
  local ticker="$1" want="$2" needle="$3" out rc
  out="$(python3 "$SCRIPT" --ticker "$ticker" --routes-dir "$FIX" 2>&1)"; rc=$?
  if [ "$rc" != "$want" ]; then
    echo "FAIL $ticker: exit $rc, wanted $want"; echo "$out"; fails=$((fails+1)); return
  fi
  if ! echo "$out" | grep -q "$needle"; then
    echo "FAIL $ticker: output missing '$needle'"; echo "$out"; fails=$((fails+1)); return
  fi
  echo "ok   $ticker (exit $rc, matched '$needle')"
}

expect DEADPAGE 1 "referenced but never declared"
expect BLANKTAB 1 "UNREACHABLE PANEL"
expect GOODPAGE 0 "every tab reaches a panel"

if [ "$fails" -eq 0 ]; then
  echo "--- validate-page.py self-test PASSED (3/3) ---"; exit 0
fi
echo "--- validate-page.py self-test FAILED ($fails) ---"; exit 1
