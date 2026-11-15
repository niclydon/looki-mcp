#!/usr/bin/env bash
# Run the offline looki-mcp test suite (OB-69925 local gate).
#
# This is the single command both local development and scripts/deploy.sh
# use, so the suite list cannot drift between "I ran it" and "the deploy
# gated on it". Exit 0 means every listed suite passed; any failure exits 1.
#
# Python selection: $LOOKI_TEST_PYTHON if set, otherwise the repo venv
# (.venv/bin/python) if present, otherwise python3 on PATH.
#
# Deliberately excluded suites:
# - scripts/test_all_tools.py — live: talks to a running server with real
#   Looki credentials (http://localhost:3456/mcp). Never run offline.
# - scripts/test_deploy.sh — exercises deploy machinery (tmp git remotes);
#   covered separately by scripts/test_deploy.sh itself.
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -n "${LOOKI_TEST_PYTHON:-}" ]]; then
  PY="$LOOKI_TEST_PYTHON"
elif [[ -x "$repo_root/.venv/bin/python" ]]; then
  PY="$repo_root/.venv/bin/python"
else
  PY="python3"
fi

# Explicit allowlist of offline suites. Add new offline suites here; a glob
# would silently pick up a future live test.
SUITES=(
  test_audio_summary.py
  test_cache.py
  test_chat_history.py
  test_composites.py
  test_envelope.py
  test_geo.py
  test_governed_get.py
  test_governor.py
  test_health_reports.py
  test_highlights.py
  test_insight_llm.py
  test_journals_by_date.py
  test_journals_helpers.py
  test_journals_sort_order.py
  test_memory_overview.py
  test_moment_files_pagination.py
  test_realtime_describe.py
  test_scan.py
  test_storage_helpers.py
  test_storage_media_key.py
  test_summaries.py
  test_video_duration.py
)

passed=0
failed=()
mkdir -p tmp
for suite in "${SUITES[@]}"; do
  script="scripts/$suite"
  [[ -f "$script" ]] || { failed+=("$suite (missing)"); echo "[FAIL] $suite (file missing)"; continue; }
  log="tmp/offline-test-$suite.log"
  if "$PY" "$script" >"$log" 2>&1; then
    passed=$((passed + 1))
    echo "[PASS] $suite"
  else
    failed+=("$suite")
    echo "[FAIL] $suite (see $log)"
  fi
done

echo "[compile] python -m compileall looki_mcp"
if "$PY" -m compileall -q looki_mcp >tmp/offline-test-compileall.log 2>&1; then
  echo "[PASS] compileall looki_mcp"
else
  failed+=("compileall")
  echo "[FAIL] compileall (see tmp/offline-test-compileall.log)"
fi

total=${#SUITES[@]}
echo "offline gate: $passed/$total suites passed"
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "offline gate: FAILED: ${failed[*]}"
  exit 1
fi
