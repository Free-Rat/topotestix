#!/usr/bin/env bash

# Test NixOS config fuzzer by evaluating generated configs
# This verifies the fuzzer produces valid NixOS configurations

set -e

cd "$(dirname "$0")"

MAX_SEED=${1:-100}
OUTPUT_DIR="./fuzzer-results"
mkdir -p "$OUTPUT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Testing NixOS config fuzzer with seeds 1-$MAX_SEED"
echo ""

rm -f "$OUTPUT_DIR/results.txt"

test_seed() {
    local seed=$1
    local result
    
    result=$(nix eval --impure --json --expr "
let 
  lib = import <nixpkgs/lib>;
  fuzzer = import ./fuzzer.nix { inherit lib; };
  config = fuzzer { seed = \"$seed\"; fuzz = import ./fuzzed_nodes.nix; };
in config.config
" 2>&1)
    
    if [ $? -eq 0 ] && echo "$result" | grep -q "memorySize"; then
        echo "$seed:VALID"
    else
        echo "$seed:INVALID: $(echo "$result" | head -1)"
    fi
}
export -f test_seed

echo "Running fuzzer tests..."

while IFS= read -r line; do
    seed="${line%%:*}"
    status="${line##*:}"
    echo "$seed:$status" >> "$OUTPUT_DIR/results.txt"
done < <(for seed in $(seq 1 "$MAX_SEED"); do test_seed "$seed"; done)

echo ""
echo "=== Summary ==="
valid_count=$(grep -c ":VALID" "$OUTPUT_DIR/results.txt" 2>/dev/null || echo 0)
invalid_count=$(grep -c ":INVALID" "$OUTPUT_DIR/results.txt" 2>/dev/null || echo 0)

echo "Valid configs: $valid_count"
echo "Invalid configs: $invalid_count"
echo "Total tested: $MAX_SEED"

echo ""
echo "Sample results (first 10):"
head -10 "$OUTPUT_DIR/results.txt"

echo ""
echo "Results saved to: $OUTPUT_DIR/results.txt"
