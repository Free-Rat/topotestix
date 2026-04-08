#!/usr/bin/env bash
set -e

TEST_NAME="${1:-package-test}"
RESULTS_DIR="./test-results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${RESULTS_DIR}/${TEST_NAME}_${TIMESTAMP}.log"

mkdir -p "$RESULTS_DIR"

echo "Running test: $TEST_NAME"
echo "Results will be saved to: $LOG_FILE"

nix log "/nix/store/$(readlink result | xargs basename)" 2>/dev/null | tee "$LOG_FILE"

if grep -q "test script finished" "$LOG_FILE"; then
    echo ""
    echo "=== TEST RESULT: PASS ==="
    echo "Log saved to: $LOG_FILE"
else
    echo ""
    echo "=== TEST RESULT: FAIL ==="
    echo "Log saved to: $LOG_FILE"
    exit 1
fi
