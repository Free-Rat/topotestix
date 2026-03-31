#!/usr/bin/env bash

# Test NixOS config fuzzer by building generated configs
# Valid configs can be built, invalid ones will produce errors

set -e

cd "$(dirname "$0")"

MAX_SEED=${1:-1000}
PARALLEL_JOBS=${2:-4}
OUTPUT_DIR="./fuzzer-results"
mkdir -p "$OUTPUT_DIR"

echo "Testing NixOS config fuzzer with seeds 1-$MAX_SEED"
echo "Using $PARALLEL_JOBS parallel jobs"
echo ""

rm -f "$OUTPUT_DIR/results.txt"

echo "Running build tests..."

# Use xargs for parallel execution
seq 1 "$MAX_SEED" | xargs -P "$PARALLEL_JOBS" -I {} bash -c '
    seed={}
    output=$(nix build .#nixosConfigurations."$seed".config.system.build.toplevel --dry-run 2>&1)
    if echo "$output" | grep -q "^error:"; then
        echo "$seed:INVALID"
    else
        echo "$seed:VALID"
    fi
' > "$OUTPUT_DIR/results.txt" 2>&1

# Summary
valid_count=$(grep -c ":VALID" "$OUTPUT_DIR/results.txt" 2>/dev/null || echo 0)
invalid_count=$(grep -c ":INVALID" "$OUTPUT_DIR/results.txt" 2>/dev/null || echo 0)

echo ""
echo "=== Summary ==="
echo "Valid configs: $valid_count"
echo "Invalid configs: $invalid_count"
echo "Total tested: $MAX_SEED"
