# TopoTestix Orchestrator

Central coordinator that drives the full pipeline: fuzzer → expandTopology → merge → runner → build → report.

## Two-Layer Architecture

The orchestrator has two components:

1. **`lib/orchestrate.nix`** — Nix function that composes the full pipeline
2. **`topotestix/orchestrator.py`** — Python implementation of run/fuzz/shrink/sweep helpers used by the CLI
3. **`topotestix/cli.py`** — public `topotestix` command tree (`orchestrator`, `runner`, `runs`, `targets`)

All Nix-type computation (fuzzer, expandTopology, mkForce merge) must happen in Nix — these values can't be serialized through Python. Python is a thin CLI wrapper: generate temp `.nix` file → `nix build --impure` → parse `report.json`.

`lib/orchestrate.nix` is the real pipeline logic and is testable with `nix-unit`. `topotestix/orchestrator.py` handles CLI args, path resolution, temp file generation, build execution, run-store writing, and result parsing.

## Data Flow (Single Pass — Phase 2)

```
User provides either a target name from `targets/default.nix` or explicit path overrides, plus:
  --seed,
  --config-target,
  --topology-target,
  --base-module,
  --test-script,
  --properties,
  --name,
  --project-root

topotestix orchestrator:
  1. Resolve all paths to absolute
  2. Generate temp .nix file that calls orchestrate.nix
  3. nix build --impure --file tempfile.nix -o result-link
  4. Parse result-link/report.json
  5. Write run metadata/logs into `.topotestix/runs`
  6. Print summary or JSON output

lib/orchestrate.nix (inside the temp file):
  1. fuzzer(seed + 0, topologyTarget) → topology-map
  2. expandTopology(topology-map) → nodeConfigs + nodeRoles
  3. For each role (alphabetical): fuzzer(seed + 1 + roleIndex, configTarget) → roleConfig
  4. For each node: mergeConfigs(base, roleConfig[nodeRoles[node]], topologyConfig[node])
  5. runner.run(nodeConfigs, testScript, properties, name) → NixOS test derivation
```

## Seed Derivation

All seeds derived from a single `master_seed`:

| Seed offset | Purpose | Example (master_seed=5) |
|---|---|---|
| +0 | topology | "5" |
| +1 + roleIndex | per-role config | broker: "6", controller: "7" |

Role ordering is alphabetical: sorted role names determine `roleIndex`.

```
master_seed = 5, roles = [broker, controller]

seed map:
  topology:   "5"  (master_seed + 0)
  broker:     "6"  (master_seed + 1 + 0)
  controller: "7"  (master_seed + 1 + 1)
```

All nodes of the same role share one fuzzer call (identical config). Seed is converted to string because the fuzzer uses string seeds for hashing.

## Node Naming: Always Indexed

expandTopology names all nodes with `roleName + 1-based index`:

```
roles = { broker = 2; controller = 1; }
→ broker1, broker2, controller1
```

No special cases, no conditional naming. Count=1 still gets index: `machine1`, not `machine`.

Rationale:
- Predictable and consistent
- Decoupled from fuzzed role counts — names stay indexed and predictable for each expanded role
- No name changes between different topology seeds

Impact: single-node test scripts use `machine1` instead of `machine`.

## expandTopology Enhancement: nodeRoles

expandTopology now returns `{ nodeConfigs, nodeRoles }` instead of just the node attrset:

```nix
expandTopology {
  topology-map = {
    roles = { broker = 2; controller = 1; };
    brokerVlans = [ 1 ];
    controllerVlans = [ 2 10 ];
  };
}
# => {
#   nodeConfigs = {
#     broker1     = { virtualisation.vlans = [ 1 ]; };
#     broker2     = { virtualisation.vlans = [ 1 ]; };
#     controller1 = { virtualisation.vlans = [ 2 10 ]; };
#   };
#   nodeRoles = {
#     broker1     = "broker";
#     broker2     = "broker";
#     controller1 = "controller";
#   };
# }
```

`nodeConfigs` is the same attrset as before (just wrapped in a record). `nodeRoles` maps each node name to its role name. This lets orchestrate.nix look up which role config applies to each node.

## Properties: Include All

`orchestrate.nix` uses `builtins.attrValues propertiesModule` to include all properties from the module:

```nix
properties = builtins.attrValues (import /path/to/properties.nix { inherit lib; });
```

The user defines which properties exist by choosing the properties module. Adding a new property to the module automatically includes it in testing.

Future addition: selective property inclusion via `--property-name` CLI flag.

## The `pkgs` Problem and Multi-Node Merge

Base modules are functions `{ pkgs, ... }: { ... }` — they need `pkgs` in scope, which only exists inside the NixOS module system. The three-layer merge must happen inside each node's module function:

```nix
nodeConfigs = lib.mapAttrs (nodeName: nodeTopoConfig:
  { pkgs, ... }:
    mergeConfigs {
      base = baseModule { inherit pkgs; };
      config = roleConfigs.${nodeRoles.${nodeName}};
      topology = nodeTopoConfig;
    }
) topologyNodeConfigs;
```

This is the same pattern as the nginx smoke test, generalized for multi-node.

## `lib/orchestrate.nix` Interface

```nix
# lib/orchestrate.nix
{ pkgs, lib, testers }:

{ seed              # integer: master seed
, topologyTarget    # Nix attrset: topology fuzz target
, configTarget      # Nix attrset: config fuzz target
, baseModule        # Nix module function: { pkgs, ... }: { ... }
, testScript        # string: Python test script content
, properties        # attrset: properties module (all properties included)
, name              # string: test name
, reportNode ? null  # string: node that writes report (defaults to first node)
}:
```

Returns a NixOS test derivation (result of `runner.run`).

## CLI Interface

```
topotestix orchestrator run nginx \
  --seed 5 \
  --project-root .
```

Target definitions live in `targets/default.nix`. Explicit path overrides still exist for advanced use, and `--project-root` controls where targets and the run store are resolved.

## `topotestix/orchestrator.py` Structure

```python
def generate_nix_expr(args) -> str:
    """Generate a Nix expression string that calls orchestrate.nix."""

def build_test(nix_expr: str, output_link: str) -> subprocess.CompletedProcess:
    """Run nix build --impure --file with the generated expression."""

def parse_report(result_path: str) -> list[dict]:
    """Read and parse report.json from the build output."""

def main():
    """CLI helpers: parse args, generate expr, build, parse report, print summary."""
```

## How Python Passes Paths to Nix

Python generates a temp `.nix` file containing a `let ... in` expression that imports all the necessary modules and calls `orchestrate.nix`.

```nix
let
  flakeRoot = "/abs/path/to/topotestix";
  flakeSource = builtins.path {
    path = builtins.toPath flakeRoot;
    name = "topotestix-locked-flake";
    filter = path: _: builtins.elem (toString path) [
      flakeRoot
      "${flakeRoot}/flake.nix"
      "${flakeRoot}/flake.lock"
    ];
  };
  nixpkgs = (builtins.getFlake (
    builtins.unsafeDiscardStringContext (toString flakeSource)
  )).inputs.nixpkgs;
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  orchestrate = import /abs/path/to/lib/orchestrate.nix { inherit pkgs lib; testers = pkgs.testers; };

  configTarget = import /abs/path/to/targets/nginx/config.nix { inherit lib; };
  topologyTarget = import /abs/path/to/targets/nginx/topology.nix { inherit lib; };
  baseModule = import /abs/path/to/targets/nginx/module.nix;
  propertiesMod = import /abs/path/to/targets/nginx/properties.nix { inherit lib; };
  testScript = builtins.readFile /abs/path/to/targets/nginx/test-script.py;
in
orchestrate {
  seed = 5;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "nginx-smoke";
}
```

Python resolves all paths to absolute, creates an explicitly filtered flake source containing only `flake.nix` and `flake.lock`, obtains Nixpkgs from that source's locked input, generates this file to a temp location, and runs `nix build --impure --no-update-lock-file --file tempfile.nix -o result-link`. Runtime evaluation therefore follows `flake.lock` rather than the caller's `nixpkgs` registry entry, without copying the project working tree or run artifacts into the Nix store.

## Shrinking (Phase 4)

Phase 4 adds **choice-based shrinking** — reducing individual choice indices toward 0 to find the minimal config that still triggers a failure. See [shrinking.md](shrinking.md) for full design.

**Shrinker module:** `lib/shrinker.nix` — pure Nix function that applies choice overrides to fuzzed output. Identity when no overrides are provided.

**Fuzzer changes:** returns `{ result, choices }` instead of just a flat attrset. `choices` maps path strings (e.g. `".memorySize"`) to the index the fuzzer selected.

**Orchestrator `--shrink` mode:** Python drives the iterative shrinking loop:

```
1. nix eval: fuzzer(seed, target) → { result, choices }
2. nix eval: shrinker.choicePaths(target) → list of shrinkable paths
3. For each dimension (topology, then each role):
     For each path in dimension:
       For index from current_index-1 down to 0:
         nix eval: shrinker.apply(target, fuzzed, {path: index})
         nix build: orchestrate with updated overrides
         If test fails → keep override, update accumulated choices
         If test passes → discard override, try next index
4. Output: minimal overrides map per dimension
```

Two shrinking approaches, by priority:

| Approach | Method | Status | Trade-off |
|---|---|---|---|
| **A: Choice-based shrinking** | Reduce choice indices toward 0, using target spec ordering | Phase 4 | Finds truly simpler configs. Target spec convention: lower index = simpler |
| **B: Target-aware shrinking** | Use NixOS default values as baseline; weight shrinking toward error-prone configs | Future | More semantically meaningful. Requires querying NixOS module system |

## Future Additions (Not Phase 2)

- Selective property inclusion via `--property-name` CLI flag
- Value-aware shrinking — use NixOS defaults as baseline, weight toward error-prone configs
- Speculative parallel shrinking (the greedy shrinking loop stays sequential; parallel seed execution is implemented via `sweep --jobs N`)
- Failure-reproducing flake output
- Runner as HTTP service
- TUI monitoring and attach mode

## Sweep and parallel execution

`orchestrator sweep` runs a range of seeds (`--seeds 1..50` or `1,3,7`) sequentially by default. `--jobs N` runs up to `N` seeds concurrently in worker threads (each `run_once` blocks on a `nix build` subprocess, so the GIL is released).

```bash
# Sequential (default)
python3 -m topotestix.cli orchestrator sweep kafka-cluster --seeds 1..50 --project-root .

# Parallel
python3 -m topotestix.cli orchestrator sweep kafka-cluster --seeds 1..50 --jobs 3 --project-root .
```

- **Resource caveat:** each seed builds a NixOS test that boots QEMU VM(s). `jobs × nodes-per-cluster` VMs may run at once. Tune `--jobs` to host RAM and Nix `max-jobs` to avoid OOM or builder contention. Default is `1` (opt-in parallelism).
- **Output order:** with `--jobs > 1`, run lines are emitted in **completion order**; the `[i/total (seed=N)]` label uses the completion count for executed runs (and the seed-list position for `--resume` skips). With `--jobs 1` seed order is preserved.
- **Timing:** every run reports an elapsed time `(Xs)`; the sweep summary prints `total <wall-clock>s avg <mean-per-run>s`. In `--json` mode the summary includes `totalTime`, `avgRunTime`, and `jobs`, and each failure entry carries `elapsed`. Under parallelism `sum(elapsed)` may exceed `totalTime` (runs overlap); `avgRunTime` is the mean per-run *duration*, `totalTime` is sweep *wall clock*.
- **`--fail-fast`:** on the first failure, no further seeds are submitted; in-flight runs finish, queued futures are cancelled.
- **Shrinking stays sequential:** the greedy `orchestrator shrink` loop depends on each step's result, so it is not parallelized.

## Example of use:

From the project root, use the current CLI:

```bash
python3 -m topotestix.cli orchestrator run nginx --seed 5 --project-root .
```

To test a failing seed (nginx disabled):

```bash
python3 -m topotestix.cli orchestrator run nginx --seed 1 --project-root .
```
