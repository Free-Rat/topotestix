#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

echo "=========================================="
echo "Kafka Test Runner for nr8-mvp"
echo "=========================================="
echo ""

SHOW_HELP() {
    echo "Usage: $0 [SEED]"
    echo ""
    echo "SEED: Optional seed number (1-10). Default: 1"
    echo ""
    echo "This script builds and runs the Kafka NixOS VM test"
    echo "for the specified seed using the fuzzed configuration."
}

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    SHOW_HELP
    exit 0
fi

SEED="${1:-1}"

if ! [[ "$SEED" =~ ^[0-9]+$ ]] || [ "$SEED" -lt 1 ] || [ "$SEED" -gt 10 ]; then
    fail "Invalid seed: $SEED (must be 1-10)"
    exit 1
fi

info "Testing Kafka with seed=$SEED"
echo ""

echo "Step 1: Evaluating flake..."
NIXOS_TESTS=$(nix eval .#nixosTests --json 2>&1) || {
    fail "Failed to evaluate nixosTests"
    exit 1
}
pass "NixOS tests evaluated successfully"

echo ""
echo "Step 2: Getting test store path for seed=$SEED..."
STORE_PATH=$(echo "$NIXOS_TESTS" | grep -o "\"${SEED}\":\"[^\"]*\"" | cut -d'"' -f4) || {
    fail "Could not find test for seed=$SEED"
    exit 1
}
info "Store path: $STORE_PATH"
pass "Test derivation found"

echo ""
echo "Step 3: Checking KVM..."
if [ -c /dev/kvm ]; then
    pass "KVM is available (/dev/kvm)"
else
    warn "/dev/kvm not found"
fi

echo ""
echo "Step 4: Building and running test..."
echo "This will run the NixOS VM test (requires KVM)..."
echo ""

rm -f result

RESULTS_DIR="./test-results"
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${RESULTS_DIR}/kafka-test-${SEED}_${TIMESTAMP}.log"

if nix build .#nixosTests."${SEED}" 2>&1 | tee "$LOG_FILE"; then
    pass "Test derivation built successfully"
else
    fail "Failed to build test"
    exit 1
fi

if [ ! -L result ]; then
    fail "Build succeeded but result symlink not created"
    exit 1
fi

pass "Result symlink created"

echo ""
echo "Step 5: Running test via nix log..."
echo "(This executes the VM test and captures output)"
echo ""

if nix log "$STORE_PATH" 2>&1 | tee -a "$LOG_FILE"; then
    pass "Test log captured"
else
    warn "nix log completed with warnings"
fi

echo ""
echo "Step 6: Analyzing test results..."
if grep -q "test script finished" "$LOG_FILE"; then
    TEST_TIME=$(grep "test script finished" "$LOG_FILE" | grep -oE "[0-9]+\.[0-9]+s" | head -1)
    pass "Test completed successfully in ${TEST_TIME:-unknown}"
    
    if grep -q "Kafka version: 4.2.0" "$LOG_FILE"; then
        pass "Kafka version verified: 4.2.0"
    fi
    
    if grep -q "must succeed: which kafka-topics.sh" "$LOG_FILE"; then
        pass "Kafka binary check passed"
    fi
    
    echo ""
    echo "=== TEST RESULT: PASS ==="
else
    echo ""
    echo "=== TEST RESULT: FAIL ==="
    fail "Test did not complete successfully"
    echo ""
    echo "Check log file for details: $LOG_FILE"
    exit 1
fi

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo ""
echo "Seed: $SEED"
echo "Store path: $STORE_PATH"
echo "Result: $(readlink result)"
echo "Log file: $LOG_FILE"
echo ""
echo "=========================================="
