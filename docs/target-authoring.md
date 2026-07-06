# Target Authoring Guide

This is a practical cheat sheet for creating a new TopoTestix target. A target is the complete definition of one system under test (SUT): its topology, fuzzable configuration surface, base NixOS module, setup script, properties, and registry entry.

If you only remember one thing: **copy the closest existing target, keep the first version small and fixed-topology, run one seed, then expand the fuzz surface.**

---

## Quick start checklist

1. Pick a target name: `kebab-case`, e.g. `rabbitmq-cluster`, `postgresql`, `my-service-cluster`.
2. Create `targets/<target-name>/` with exactly these files:

   ```text
   targets/<target-name>/
   ├── topology.nix
   ├── config.nix
   ├── module.nix
   ├── test-script.py
   └── properties.nix
   ```

3. Register it in `targets/default.nix`.
4. Validate the registry and composed script:

   ```bash
   topotestix targets list
   topotestix targets show <target-name>
   topotestix runner show-properties <target-name>
   topotestix runner compose-script <target-name> > /tmp/<target-name>-script.py
   ```

5. Run one seed:

   ```bash
   topotestix orchestrator run <target-name> --seed 1 --verbose
   ```

6. If it passes, sweep a small range:

   ```bash
   topotestix orchestrator sweep <target-name> --seeds 1..10 --resume
   ```

From a fresh checkout where `topotestix` is not installed, prefix commands with `nix run . --`, for example:

```bash
nix run . -- targets list
nix run . -- orchestrator run nginx --seed 1
```

---

## Mental model: what each target file does

| File | Purpose | Runs where? |
|---|---|---|
| `topology.nix` | Fuzz target for roles, node counts, and per-role VLAN choices | Nix evaluator, before VM build |
| `config.nix` | Fuzz target for per-role NixOS option values | Nix evaluator, once per role |
| `module.nix` | Stable base NixOS module for every node | Inside each VM node config |
| `test-script.py` | NixOS test driver procedure: boot, wait, form cluster, seed data | Python test driver |
| `properties.nix` | Property helpers and `_check(...)` calls appended after `test-script.py` | Python test driver |
| `targets/default.nix` | Named target registry consumed by the CLI | Nix evaluator |

`topology.nix`, `config.nix`, and `properties.nix` are imported with `lib`. `module.nix` is the file that receives `pkgs`, so package lists usually belong there.

The orchestrator composes one node config as:

```text
base module  ⊕  fuzzed role config  ⊕  fuzzed topology config
```

Fuzzed config and topology override base values. Keep fixed, required service setup in `module.nix`; put experimental dimensions in `config.nix`.

---

## Naming conventions

| Thing | Convention | Good | Avoid |
|---|---|---|---|
| Target name / directory | `kebab-case` | `kafka-cluster` | `KafkaCluster`, `kafka cluster` |
| File names | Fixed names | `test-script.py` | `test.py`, `properties.py` |
| Role names | Python-safe lowercase identifiers; preferably singular | `machine`, `rabbit`, `broker`, `primary` | `rabbit-node`, `1broker`, `kafka.controller` |
| Node variables | Auto-generated as `<role><index>` | `rabbit1`, `broker2`, `machine1` | `rabbit`, `machine` |
| VLAN key | `<role>Vlans` | `brokerVlans` | `broker_vlans`, `vlans.broker` |
| Property attr key | `snake_case` | `cluster_formed` | `cluster-formed` |
| Report property name | stable `kebab-case` string | `rabbitmq-cluster-formed` | changing per run |

Important details:

- Node indices are **always 1-based**. A single-node role named `machine` becomes `machine1`, not `machine`.
- Role names become Python variables in `test-script.py` and `properties.nix`, so do not use hyphens in role names.
- Target names may use hyphens because they are CLI/registry names, not Python variables.
- Role names are sorted alphabetically for per-role config seed derivation. Adding or renaming roles can change which config values each role receives for the same master seed.

---

## NixOS test documentation

TopoTestix targets ultimately run as NixOS VM tests via `testers.runNixOSTest`, so the standard NixOS test-driver API applies.

Useful upstream references:

- [NixOS manual: Integration tests](https://nixos.org/manual/nixos/stable/#sec-nixos-tests)
- [Nixpkgs manual: `testers.runNixOSTest`](https://nixos.org/manual/nixpkgs/stable/#tester-runnixostest)

Most target authors only need the Python test-driver primitives used inside `test-script.py` and `properties.nix`:

| Primitive | Use |
|---|---|
| `start_all()` | Start all VMs in a multi-node test |
| `machine.wait_for_unit("service.service")` | Wait until a systemd unit is active |
| `machine.wait_for_open_port(8080)` | Wait until a TCP port is listening |
| `machine.wait_until_succeeds("command")` | Retry a shell command until it exits successfully |
| `machine.succeed("command")` | Run a shell command; fail the test if it exits non-zero |
| `machine.fail("command")` | Assert that a shell command fails |
| `machine.copy_from_machine("/path")` | Copy a file from a VM into the test output |

TopoTestix adds its own report harness around these primitives. Put fatal setup steps in `test-script.py`; put checks that should be recorded as structured pass/fail entries in `properties.nix` using `_check(...)`.

---

## Step-by-step target creation

### 1. Start from the closest existing target

Use a similar service as a template:

```bash
cp -r targets/nginx targets/my-service
# or for clustered services:
cp -r targets/rabbitmq-cluster targets/my-service-cluster
```

Then edit all five files and add a registry entry.

For a first working target, prefer:

- fixed node count, e.g. `roles.rabbit = [ 3 ];`
- one simple connected VLAN choice, e.g. `rabbitVlans = [ [ 1 ] ];`
- 1-3 safe config dimensions
- one smoke property

Add more fuzzing after the smoke version is stable.

---

### 2. Write `topology.nix`

`topology.nix` is a fuzzer target. Every list is a choice list. The fuzzer picks one element from each list, then `expandTopology` creates VM nodes.

Single-node template:

```nix
{ lib, ... }:

{
  roles.machine = [ 1 ];
  machineVlans = [ [ 1 ] ];
}
```

Three-node cluster template:

```nix
{ lib, ... }:

{
  roles.rabbit = [ 3 ];
  rabbitVlans = [ [ 1 ] ];
}
```

Two-role template:

```nix
{ lib, ... }:

{
  roles.broker = [ 3 ];
  roles.controller = [ 1 ];

  # Outer list = choices. Inner list = actual VLAN membership.
  brokerVlans = [ [ 1 10 ] ];
  controllerVlans = [ [ 2 10 ] ];
}
```

Topology rules:

- `roles.<role> = [ countChoices... ];`
- `<role>Vlans = [ vlanListChoices... ];`
- nodes on the same VLAN can communicate
- nodes on different VLANs cannot communicate
- a node can be on multiple VLANs, e.g. `[ 1 10 ]`
- all nodes of the same role get the same VLAN list

Shrinking convention: put simpler topology choices first. Examples:

```nix
roles.broker = [ 1 3 5 ];           # fewer nodes first
brokerVlans = [ [ 1 ] [ 1 10 ] ];   # simpler network first
```

Be careful with fuzzed node counts. If `roles.broker = [ 1 3 ];`, then `broker3` does not exist for some seeds. Hard-coded references to `broker3` in Python will fail for the one-node case. For initial targets, keep counts fixed unless the script/properties are written to handle every possible topology.

---

### 3. Write `config.nix`

`config.nix` defines the fuzzable NixOS options applied per role. The orchestrator runs the config fuzzer once per role, so all nodes with the same role share the same fuzzed config.

Template:

```nix
{ lib, ... }:

let
  c = import ../../lib/combinators.nix { inherit lib; };
in
{
  virtualisation.memorySize = [ 1024 2048 4096 ];
  virtualisation.diskSize = [ 2048 4096 ];

  services.openssh.enable = c.bool;

  # If the final NixOS option value is itself a list, wrap it in an outer
  # choice list. Outer list = choices; inner list = actual option value.
  services.myService.extraFlags = [
    []
    [ "--safe-mode" ]
    [ "--safe-mode" "--verbose" ]
  ];
}
```

Config rules:

- Every list is interpreted as a choice list.
- Empty choice lists are invalid as choice lists. If the intended final value is an empty list, wrap it: `some.option = [ [] ];`.
- Lower index should mean simpler/smaller/safer because shrinking moves indices toward `0`.
- Use single-element lists for fixed fuzz dimensions, e.g. `virtualisation.memorySize = [ 2048 ];`.
- Keep service-critical invariants in `module.nix` if disabling them would make every run meaningless.
- Avoid huge choice surfaces at first; each new dimension increases the search/shrink space.

Common dimensions:

```nix
virtualisation.memorySize = [ 1024 2048 4096 ];
virtualisation.diskSize = [ 2048 4096 8192 ];
services.<service>.enable = [ true ];
services.<service>.<option> = [ value1 value2 value3 ];
services.<service>.configItems."some.key" = [ "small" "medium" "large" ];
```

---

### 4. Write `module.nix`

`module.nix` is the stable base config applied to every node. It is a NixOS module function called with `pkgs` and `nodeName`.

Template:

```nix
{ pkgs, nodeName, ... }:

{
  services.myService.enable = true;

  networking.firewall.allowedTCPPorts = [
    1234
    5678
  ];

  environment.systemPackages = with pkgs; [
    coreutils
    curl
    jq
  ];
}
```

Use `module.nix` for:

- enabling the SUT
- required packages used by `test-script.py` or properties
- firewall ports
- stable service configuration
- node-specific stable config based on `nodeName` when necessary

Avoid putting experimental values here if they are meant to be fuzzed in `config.nix`. Fuzzed config uses `mkForce` and will override base values, but keeping responsibilities separate makes failures easier to interpret.

---

### 5. Write `test-script.py`

`test-script.py` is the procedural setup that runs before properties. Use it to boot machines, wait for services, form clusters, and create baseline data. It is ordinary NixOS test-driver Python; see the [NixOS integration test documentation](https://nixos.org/manual/nixos/stable/#sec-nixos-tests) for the full upstream API.

Single-node template:

```python
machine1.wait_for_unit("my-service.service")
machine1.wait_for_open_port(8080)
machine1.wait_until_succeeds("curl -fsS http://localhost:8080/health")
```

Cluster template:

```python
start_all()

for machine in [rabbit1, rabbit2, rabbit3]:
    machine.wait_for_unit("rabbitmq.service")
    machine.wait_for_open_port(5672)

# Service-specific cluster formation goes here.
```

Guidelines:

- Use generated node variable names: `machine1`, `rabbit1`, `rabbit2`, etc.
- Use `start_all()` for multi-node tests when you need all VMs booted together.
- Put fatal setup requirements directly in the script. A bare `machine.succeed(...)` failure stops the test and may produce no `report.json`.
- Put assertions you want reported as properties in `properties.nix`, not as bare setup commands.
- Always wait for units/ports/health checks before running workload commands.
- Make the script valid for every topology choice in `topology.nix`.

---

### 6. Write `properties.nix`

`properties.nix` returns an attrset of property definitions. Each property has:

- `name`: stable report name
- `setup`: Python helper definitions injected before `test-script.py`
- `check`: Python code appended after `test-script.py`, usually calling `_check(...)`

Template:

```nix
{ lib }:

{
  responds_to_health = {
    name = "my-service-responds-to-health";
    setup = ''
def check_my_service_health(machine):
    machine.succeed("curl -fsS http://localhost:8080/health")
    '';
    check = ''
_check("my-service-responds-to-health", check_my_service_health, machine1)
    '';
  };
}
```

Cluster property template:

```nix
{ lib }:

{
  cluster_formed = {
    name = "my-service-cluster-formed";
    setup = ''
def check_cluster_formed(machine):
    machine.succeed("my-service-cli cluster status | grep -q healthy")
    '';
    check = ''
_check("my-service-cluster-formed-node1", check_cluster_formed, node1)
_check("my-service-cluster-formed-node2", check_cluster_formed, node2)
_check("my-service-cluster-formed-node3", check_cluster_formed, node3)
    '';
  };
}
```

Property rules:

- `_check(name, fn, *args)` catches exceptions, records pass/fail, and continues to the next property.
- All properties in the module are currently included automatically.
- Make `_check` names unique; these are what you see in reports.
- Do not rely only on the attr key (`cluster_formed`); the `name`/`_check` strings are the stable report identifiers.
- If a failure should not abort the whole test, wrap it in `_check`.
- If a failure means setup is impossible and later properties are meaningless, keep it in `test-script.py` as a fatal command.

---

### 7. Register the target in `targets/default.nix`

Add an entry:

```nix
my-service-cluster = {
  description = "Three-node My Service cluster target";
  topologyTarget = ./my-service-cluster/topology.nix;
  configTarget = ./my-service-cluster/config.nix;
  baseModule = ./my-service-cluster/module.nix;
  testScript = ./my-service-cluster/test-script.py;
  properties = ./my-service-cluster/properties.nix;
  reportNode = "node1";
};
```

`reportNode` must be an existing generated node name for every topology choice. It is the VM used to write and copy out `report.json`. For single-node targets this is usually `machine1`; for clusters choose a stable node such as `rabbit1`, `kafka1`, `primary1`, or `node1`.

---

## CLI usage and result interpretation

### Inspect targets

```bash
topotestix targets list
topotestix targets show <target>
topotestix targets show <target> --json
```

Interpretation:

- `targets list` prints `<name> <description>` for all registry entries.
- `targets show` prints resolved paths and `reportNode`.
- If your target is missing, the registry entry is wrong or `targets/default.nix` does not evaluate.

---

### Inspect properties and composed script

```bash
topotestix runner show-properties <target>
topotestix runner compose-script <target> > /tmp/composed.py
```

Interpretation:

- `show-properties` prints property attr keys from `properties.nix`.
- `compose-script` shows the exact Python script the runner will execute: report harness, property setup, your `test-script.py`, property checks, and report writing.
- Use `compose-script` when Python indentation, missing node names, or `_check` placement is unclear.

---

### Inspect fuzzed config choices

```bash
topotestix orchestrator fuzz <target> --seed 1
```

This evaluates the target's **config** fuzz surface for one seed and prints JSON like:

```json
{
  "choices": {
    ".virtualisation.memorySize": 1
  },
  "result": {
    "virtualisation": {
      "memorySize": 2048
    }
  }
}
```

Interpretation:

- `result` is the concrete config selected for that seed.
- `choices` maps target paths to selected choice indices.
- Shrinking tries to reduce these indices toward `0`, so index `0` should be the simplest value.

---

### Run one seed

```bash
topotestix orchestrator run <target> --seed 1 --verbose
```

Useful variants:

```bash
# Machine-readable output
topotestix orchestrator run <target> --seed 1 --json

# Custom run name
topotestix orchestrator run <target> --seed 1 --name smoke-seed-1

# Temporary path override while iterating
topotestix orchestrator run <target> --seed 1 \
  --test-script targets/<target>/test-script.py \
  --properties targets/<target>/properties.nix
```

Human output contains:

```text
============================================================
 TopoTestix Results
 Seed: 1
 Name: <target>-seed-1
============================================================
  PASS  property-name
  FAIL  property-name: failure message

 Overall: PASSED|FAILED
 Run dir: .topotestix/runs/<run-id>
============================================================
```

Interpretation:

- `PASS property` means that `_check(...)` completed without exception.
- `FAIL property: message` means `_check(...)` caught an exception. The VM test may still have produced a valid `report.json`.
- `VM test FAILED (build error)` means NixOS test setup/build failed outside the report harness. Inspect `stderr.log`.
- `No report.json found` usually means the script failed before report writing, often due to fatal setup code, missing node variable, service timeout, or Python syntax error.

Exit codes:

- `0`: all properties passed and build succeeded
- `1`: run completed but failed, or sweep had failures
- `2`: CLI/path/evaluation error caught by the top-level command

---

### Sweep seeds

```bash
topotestix orchestrator sweep <target> --seeds 1..50
```

Useful variants:

```bash
# Stop after first failure
topotestix orchestrator sweep <target> --seeds 1..50 --fail-fast

# Resume: skip seeds already present in the run store
topotestix orchestrator sweep <target> --seeds 1..50 --resume

# Parallel execution; tune carefully because each seed boots VM(s)
topotestix orchestrator sweep <target> --seeds 1..50 --jobs 2

# JSON summary
topotestix orchestrator sweep <target> --seeds 1..50 --json
```

Interpretation:

- Each seed creates a run directory under `.topotestix/runs/` unless `--output-dir` is used.
- `--resume` skips any seed with an existing run for that target, whether passed or failed. Delete the run directory to force a re-run.
- `--jobs N` may run `N × nodes-per-cluster` VMs at once. Keep it low on memory-constrained machines.
- In parallel mode, results are printed in completion order, not seed order.

---

### Inspect stored runs

```bash
topotestix runs list
topotestix runs show <run-id>
topotestix runs report <run-id>
topotestix runs logs <run-id>
topotestix runs logs <run-id> --stderr
topotestix runner inspect-report <run-id>
```

Run directory contents:

| File | Meaning |
|---|---|
| `run.json` | metadata: target, seed, status, summary, reproduce command |
| `target.json` | target paths used for the run |
| `choices.json` | explicit shrink/override choices passed to the run |
| `expr.nix` | generated Nix expression built by the orchestrator |
| `stdout.log` | stdout from `nix build` / NixOS test |
| `stderr.log` | stderr from `nix build` / NixOS test |
| `report.json` | structured property report parsed by TopoTestix |
| `result` | symlink to the Nix build output |

Debugging order:

1. `topotestix runs show <run-id>` — confirm target, seed, status, reproduce command.
2. `topotestix runs report <run-id>` — inspect property failures.
3. `topotestix runs logs <run-id> --stderr` — inspect build/test-driver failures.
4. `topotestix runs logs <run-id>` — inspect VM/test stdout.
5. Open `<run-dir>/expr.nix` if path resolution or generated Nix is suspicious.

---

### Shrink a failing seed

```bash
topotestix orchestrator shrink <target> <seed> --verbose
```

Interpretation:

- Shrinking first verifies that the initial seed fails.
- It then tries lower choice indices for topology choices, then per-role config choices.
- If a simpler choice still fails, it is kept.
- Final output includes `Final topology choices`, `Final config choices`, and a full reproduce command.

Use the reproduce command from shrink output when documenting or re-running the minimized case.

---

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `unknown target` | missing/invalid `targets/default.nix` entry | run `topotestix targets list`; fix registry name |
| Python `NameError: machine is not defined` | node is named `machine1`, not `machine` | use `<role><index>` variables |
| Python `NameError: broker3 is not defined` | topology can generate fewer nodes than script references | fix node count or make script valid for all topologies |
| `No report.json found` | fatal setup failure before report writing | inspect stderr/stdout; move non-fatal assertions to properties |
| All seeds fail immediately | fuzz surface violates service invariants | move invariant config to `module.nix` or remove unsafe choices |
| Shrinking gives odd “minimal” result | choice lists are not ordered simplest-first | reorder choices with safest/smallest at index `0` |
| List-valued option becomes one element | forgot outer choice list | use `[ [ actual list ] [ alternative list ] ]` |
| Cluster nodes cannot communicate | VLAN choices do not overlap | ensure roles that must talk share a VLAN |
| Report copy fails | `reportNode` is wrong/missing | set `reportNode` to an existing node for all topologies |

---

## Review checklist before committing a target

- [ ] Target directory has the five standard files.
- [ ] Target is registered in `targets/default.nix` with a clear description.
- [ ] Target name is `kebab-case`; role names are Python-safe identifiers.
- [ ] `reportNode` exists for every topology choice.
- [ ] `topology.nix` choices are ordered simplest-first.
- [ ] `config.nix` choices are ordered simplest-first.
- [ ] Any list-valued NixOS option in `config.nix` is wrapped in an outer choice list.
- [ ] `test-script.py` references only nodes that exist for every topology choice.
- [ ] `properties.nix` uses `_check(...)` with unique stable names.
- [ ] `topotestix targets show <target>` works.
- [ ] `topotestix runner compose-script <target>` works.
- [ ] `topotestix orchestrator run <target> --seed 1 --verbose` either passes or fails in an expected, interpretable way.
- [ ] A small sweep has been run or there is a note explaining why not.
