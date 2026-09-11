# 0a — Framework Surface Discovery (TopoTestix)

Author: discovery subagent 0a. Research-only snapshot for reproduction-harness authors.

## 1. Repo state

- Repo: `/home/freerat/projects/topotestix`
- HEAD: `9afe743463666fd4e768fd63a1c48f5823dd5b8c`
- Branch: `thesis-eval-repro`
- Dirty: YES
  - Modified: `targets/default.nix`
  - Added (staged): `targets/etcd-cluster-v1/config.nix`, `targets/etcd-cluster-v1/properties.nix`
  - Untracked: `thesis-eval-reproduction-plan.md`
- Thesis repo: `/home/freerat/projects/master-thesis` (thesis text at `thesis/put-thesis/chapters/06-evaluation.typ`)

Invocation convention (python3 not on PATH):

```bash
# from repo root
nix develop -c python3 -m topotestix.cli <args...>
# or (scripts): nix run nixpkgs#python3 -- -c '...'
```

Note: nix output contains harmless warnings (`netrc-file`, `trusted-public-keys` restricted settings) on stderr; ignore/suppress with `2>/dev/null`.

Registered targets (`nix develop -c python3 -m topotestix.cli targets list`):
`etcd-cluster`, `etcd-cluster-v1`, `kafka`, `kafka-cluster`, `nginx`, `postgresql`, `rabbitmq-cluster`, `rabbitmq-crash`, `rabbitmq-disk`, `rabbitmq-disk-availability`, `rabbitmq-dns`, `rabbitmq-dns-contract`, `rabbitmq-failure-domain`, `rabbitmq-memory`, `rabbitmq-partition`, `rabbitmq-partition-availability`.

## 2. CLI surface

Source of truth: `topotestix/cli.py` (argparse). Entry: `python3 -m topotestix.cli` → `main()` in cli.py:186. Global flag: `--project-root` (default `None`; resolved by `project_root_from_args` in topotestix/targets.py:99 → `os.path.abspath(value)` or `os.getcwd()`).

### 2.1 `targets`
- `targets list [--project-root DIR] [--json]`
- `targets show <target> [--project-root DIR] [--json]`

### 2.2 `orchestrator run` — one seed, full VM build+run
```
orchestrator run <target>
  --seed INT (default 1)
  --topology-choices JSON-OBJECT (default {})
  --config-choices JSON-OBJECT (default {})
  --project-root DIR      # SUPPRESS default; per-subcommand, wins over global
  --output-dir DIR        # run store dir (default <project-root>/.topotestix/runs)
  --name NAME             # default "<target>-seed-<seed>"
  --json                  # print JSON {passed, runDir, report}
  --quiet                 # suppress human summary
  --verbose               # INFO diagnostics
  --topology-target PATH  # override topology target path
  --config-target PATH    # override config target path
  --base-module PATH
  --test-script PATH
  --properties PATH
```
- `--topology-choices` / `--config-choices` are parsed via `parse_json_object` (topotestix/orchestrator.py:25): **inline JSON string**, must be a JSON **object** (dict), else `ArgumentTypeError`. No file support in the flag itself (pass `"$(cat file.json)"` if needed).
- Exit code: **0 if passed, 1 if failed** (cmd_run, orchestrator.py:678). Fatal CLI errors (RuntimeError/ValueError/FileNotFoundError) → `error: ...` on stderr, exit **2** (cli.py:216-218). Target override paths are resolved relative to `--project-root` (`resolve_path` in topotestix/nix.py).

### 2.3 `orchestrator fuzz` — pure choice resolution, NO build
```
orchestrator fuzz <target>
  --seed STRING (REQUIRED — note: not int; passed to nix as string)
  (same --project-root/--output-dir/--name/--json/--quiet/--verbose and target overrides)
```
Evaluates `lib/fuzzer.nix` `fuzzer { seed; target = configTarget; }` via `nix eval --json`; prints `{choices, result}`-shaped JSON. Exit 0 (even if choices look odd — no test is run). cmd_fuzz uses `target.config_target` only (orchestrator.py:681-685).

### 2.4 `orchestrator shrink` — minimize a failing seed
```
orchestrator shrink <target> <seed:int>
  (same common + override flags)
```
Behavior (cmd_shrink, orchestrator.py:688-753):
1. `nix eval` `generate_shrink_inputs_expr` to get fuzzed `topologyChoices` + per-role `configChoices` for the seed.
2. Runs the seed once (full VM run) with those choices; if it **passes** → prints "Initial seed passed; nothing to shrink." to stderr, exit **1**.
3. Greedy loop (`candidate_choice_maps`, orchestrator.py:606): for every int choice path, tries indices `current-1 … 0`; topology choices first, then per-role config choices (roles sorted). Each candidate is a FULL VM run (`run_once`) recorded into the run store. Repeats until no candidate keeps the failure.
4. Output: final topology choices JSON, final config choices JSON, and a one-line reproduce command; exit **0**. Every trial run leaves a run dir (including passing intermediates) in the run store.

### 2.5 `orchestrator sweep` — range of seeds
```
orchestrator sweep <target>
  --seeds RANGE (REQUIRED)  # "1..100" inclusive range (or descending "50..1") or comma list "1,3,7"  (parse_seed_range, orchestrator.py:756)
  --fail-fast               # stop scheduling after first failure (drains in-flight)
  --resume                  # skip seeds already having a run.json for this target (pass OR fail); delete run dir to re-run
  --jobs INT (default 1)    # parallel seeds via ThreadPoolExecutor; jobs>1 emits events in completion order
  (same common + override flags)
```
- Exit: **1 if any seed failed, else 0** (orchestrator.py:837).
- `--json` prints a single summary object at end:
  `{target, total, completed, skipped, failed, failures:[{seed,runDir,returncode,elapsed}], classifications:{status:count}, totalTime, avgRunTime, jobs}`.
- No repetitions per seed: each seed is run exactly once (fresh run dir each time).

### 2.6 `runner`
```
runner compose-script <target> [--project-root DIR]
runner inspect-report <path_or_run_id> [--project-root DIR] [--json]
runner show-properties <target> [--project-root DIR] [--json]
```

### 2.7 `runs`
```
runs list  [--project-root DIR] [--output-dir DIR] [--json]
runs show  <run_id-prefix-or-dir> [--project-root] [--output-dir]   # prints run.json
runs logs  <run_id> [--project-root] [--output-dir] [--stderr]      # stdout.log | stderr.log
runs report <run_id> [--project-root] [--output-dir]                # report.json
```
Run id may be a directory path, a full id, or a unique id prefix (`RunStore.resolve_run`, run_store.py:122).

### 2.8 Env note
`cmd_runs` defaults output dir to `default_runs_dir(project_root)` = `<project-root>/.topotestix/runs` (run_store.py:10). Thesis evidence uses `--output-dir .topotestix/runs-thesis-redesign` etc.

## 3. Run-store schema (real example)

Retention dirs present:
- `.topotestix/runs/` (default; kafka sweeps, min-config validations from 2026-06/08)
- `.topotestix/runs-thesis-redesign/` (thesis phase evidence, passed via `--output-dir`)
- `.topotestix/runs-negative-controls/` (negative-control evidence)

### Run-dir naming
Flat under the store root; `RunStore.create_run` (run_store.py:83):
`<YYYYmmdd-HHMMSS>-<target>-seed-<seed>-<safe(name)>` with `-2`, `-3`… suffix on collision (atomic `os.makedirs(exist_ok=False)`). `safe_name` replaces non-`[A-Za-z0-9_.-]` with `-`. Files are written by `run_once` (orchestrator.py:199-279).

Real example analyzed: `.topotestix/runs-thesis-redesign/20260822-175757-rabbitmq-crash-seed-1-phase2-crash-follower-repA/`

Files present: `run.json`, `choices.json`, `resolved.json`, `report.json`, `target.json`, `expr.nix`, `stdout.log`, `stderr.log`, `result` (symlink to nix store path), plus materialized artifacts (here `crash-results.json` copied from `$out`).

### `run.json` (key: type — sample)
- `id`: str — dir name
- `target`: str — `"rabbitmq-crash"`
- `seed`: int — `1`
- `name`: str — run name
- `status`: str — `"passed" | "failed"`
- `startedAt` / `finishedAt`: str — ISO-8601 UTC (`datetime.now(timezone.utc).isoformat()`)
- `runDir`: str — relative to project root (e.g. `.topotestix/runs-thesis-redesign/<id>`)
- `resultPath`: str — relative path of `result` symlink
- `gitHead`: str — full `git rev-parse HEAD` of project root ("" if unavailable)
- `artifacts`: list[str] — names materialized from `$out` (e.g. `["crash-results.json"]`; `[]` on build failure)
- `summary`: object `{passed:int, failed:int, total:int}` — from `report_summary(report)`
- `reproduceCommand`: str — fully-quoted shell command (see §5)

### `choices.json`
- `topologyChoices`: object — map of dotted choice-path → int index (here `{}`)
- `configChoices`: object — map of role name → (choice-path → int) (here `{}`)

Example non-empty (kafka probe run `.topotestix/runs/20260824-123925-kafka-cluster-seed-9-kafka-probe-dotted-override-20260824/run.json` reproduceCommand):
`--config-choices '{"kafka": {".services.apache-kafka.settings.log.segment.bytes": 0, ".services.apache-kafka.settings.message.max.bytes": 0}}'`

### `resolved.json` (from `generate_inspect_expr`)
- `topology`: object — expanded topology map (`roles`: role→count(int), plus per-role lists e.g. `rabbitVlans`)
- `topologyChoices`: object — resolved topology choice paths (leading-dot form, e.g. `.roles.rabbit`, `.rabbitVlans`) → int
- `roleFuzz`: object — role → `{choices: {path:int}, seed: str, result: {…fuzzed config attrs…}}` (roles sorted alphabetically; role seed = `seed + 1 + role_index`)
- `nodeRoles`: object — node → role
- `nodeConfigs`: object — node → NixOS config attrs (e.g. `virtualisation.vlans`)

### `report.json`
Top-level JSON **array** of property results; each entry `{name: str, status: str, message: str(optional)}`; `status ∈ {"passed","failed","expected_failure","unexpected_pass","unknown"}`. Overall pass = every entry `passed` (or expected per `report_passed`, topotestix/reports.py) AND build returncode 0.

### `target.json`
`{name, description, topologyTarget, configTarget, baseModule, testScript, properties, reportNode}` — all str; paths are ABSOLUTE (resolved against project root), `reportNode` may be `""`.

### `expr.nix`
The generated nix expression passed to `nix build` (see `generate_nix_expr`, orchestrator.py:35): imports orchestrate.nix + the 5 target files, sets `seed`, `topologyChoices`, `configChoices` as embedded Nix JSON.

## 4. run vs sweep vs shrink vs fuzz

- **run**: one seed → one run dir; exit 0/1.
- **sweep**: `--seeds` list/range, one run per seed (no repeats), `--jobs` parallelism, `--resume` skips seeds with existing run.json for the target, `--fail-fast` stops scheduling new seeds after a failure. Emits events (sweep_started, run_started, run_passed/run_failed with `elapsed`, run_skipped, sweep_finished with `classifications`/`totalTime`/`avgRunTime`).
- **shrink**: needs a failing seed; first verifies failure (exit 1 if it passes), then greedy index-wise descent over topology then config choice maps; every candidate is a full VM run with its own run dir; prints final choices + reproduce command.
- **fuzz**: pure `nix eval` of the config fuzzer for a seed — no VM build, no run store writes; prints choices+result JSON, always exit 0.

## 5. Target-file overrides

Yes — every `orchestrator` subcommand accepts `--topology-target`, `--config-target`, `--base-module`, `--test-script`, `--properties` (`add_common_target_overrides`, cli.py:20; applied by `apply_overrides`, orchestrator.py:186, falling back to registry values per-field). Paths are resolved relative to `--project-root`. There is also a pseudo-target `__legacy__` (`get_cli_target`, orchestrator.py:617) that builds a Target entirely from the five override flags (name `legacy`).

This is exactly how the Kafka class-isolating minimal configs were validated (evidence: `experiments/kafka-cluster/kafka-cluster-case-study.md` lines ~80-180; note the top-level files `experiments/kafka-cluster-min-message-max.nix` and `experiments/kafka-cluster-min-log-segment.nix` exist, not under `experiments/kafka-cluster/`):

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster \
  --seed 1 \
  --name kafka-cluster-min-message-max \
  --project-root . \
  --config-target experiments/kafka-cluster-min-message-max.nix
# (analogous for --config-target experiments/kafka-cluster-min-log-segment.nix)
```

`run.json.reproduceCommand` always embeds all five override flags with absolute paths (example from kafka probe run):
```
topotestix orchestrator run kafka-cluster --seed 9 --name kafka-probe-dotted-override-20260824 \
  --project-root /home/freerat/projects/topotestix \
  --topology-target /home/freerat/projects/topotestix/targets/kafka-cluster/topology.nix \
  --config-target /home/freerat/projects/topotestix/targets/kafka-cluster/config.nix \
  --base-module /home/freerat/projects/topotestix/targets/kafka-cluster/module.nix \
  --test-script /home/freerat/projects/topotestix/targets/kafka-cluster/test-script.py \
  --properties /home/freerat/projects/topotestix/targets/kafka-cluster/properties.nix \
  --config-choices '{"kafka": {".services.apache-kafka.settings.log.segment.bytes": 0, ".services.apache-kafka.settings.message.max.bytes": 0}}'
```
Caveat recorded in the case study: the generic shrinker can't express dotted Kafka setting paths (`kafka-cluster-shrink-seed-9-choice-override-limitation.log`); the dotted choice paths above DO work as `--config-choices` input (validated 2026-08-24, run `20260824-123925-kafka-cluster-seed-9-kafka-probe-dotted-override-20260824`, status failed as expected with `kafka-large-message-on-kafka1` RecordTooLargeException).

## 6. Tests

- Nix (nix-unit): `tests/*.nix` aggregated by `tests/default.nix` (combinators, fuzzer, expand-topology, merge, runner, orchestrate, shrinker, targets tests).
  - Run: `nix develop -c nix-unit --expr "import ./tests { lib = (import <nixpkgs> {}).lib; }"`
  - Verified live: **`🎉 114/114 successful`** (matches thesis claim of 114).
  - Also via flake check: `nix-unit --eval-store "$TMPDIR/eval-store" --override-input nixpkgs ${nixpkgs} --flake .#tests` (flake.nix:42-46).
- Python (stdlib unittest): `tests/test_cli.py`, `test_orchestrator.py`, `test_reports.py`, `test_run_store.py`, `test_sweep.py` — **57 `def test_` functions** (matches thesis claim of 57).
  - Run: `nix develop -c python3 -m unittest discover -s tests -p 'test_*.py'`
  - Both also wired as flake `checks` (`.#checks.default` and `.#checks.python`, flake.nix:39-60); devShell has alias `runtest`.
