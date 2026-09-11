# 0e — Repo Engineering Conventions (topotestix)

Read-only discovery for adding a new Python reproduction package idiomatically.
Snapshot at commit `9afe743` on branch `thesis-eval-repro` (see §6).

## 1. Python packaging (`pyproject.toml`)

- **Backend**: setuptools (`build-backend = "setuptools.build_meta"`), build requires `setuptools`.
- **Project**: name `topotestix`, version `0.1.0`, `requires-python = ">=3.9"` (no upper pin; Nix builds with `pkgs.python3`).
- **Dependencies**: none (`dependencies = []`) — stdlib-only Python code.
- **Entry point**: `[project.scripts] topotestix = "topotestix.cli:main"` (argparse CLI).
- **Packaging scope**: `[tool.setuptools.packages.find] include = ["topotestix*"]` — **only** the `topotestix/` tree is packaged. `experiments/`, `tests/`, `lib/`, `orchestrator/`, `targets/` are NOT packaged and NOT importable from an installed wheel.
- **Nix package** (flake.nix:25-34): `python3Packages.buildPythonApplication` with `pyproject = true`, `build-system = [ setuptools ]`, `doCheck = false`, `src = self`.

## 2. Test conventions

- **Runner**: `unittest` (NOT pytest). All Python tests live in `tests/test_*.py` (`test_cli.py`, `test_orchestrator.py`, `test_reports.py`, `test_run_store.py`, `test_sweep.py`), using `unittest.TestCase` classes + `unittest.mock`.
- **Invocation** (flake.nix:36-71):
  - CI check: `checks.python = runCommand "python-tests" ... python3 -m unittest discover -s tests -p 'test_*.py'` (copies `self` to a writable tree first).
  - CI check: `checks.default` runs `nix-unit --flake ${self}#tests` (nix-unit input pinned in flake).
  - Dev alias: `nix develop` shellHook defines `runtest` = `nix-unit --expr "import ./tests { lib = (import <nixpkgs> {}).lib; }" && python3 -m unittest discover -s tests -p "test_*.py"`.
- **Coexistence**: yes — nix-unit tests (`tests/*-test.nix`, aggregated by `tests/default.nix` importing each `../lib/*.nix` module) and Python unittests run side by side; Nix tests exercise `lib/*.nix`, Python tests exercise `topotestix/*.py`.
- Python tests import the package directly: `from topotestix.cli import build_parser` — they assume repo-root cwd (works in devShell and in the flake check because it copies the whole source).

## 3. Lint / format config

- `[tool.black]`: line-length 100, target py39.
- `[tool.ruff]`: line-length 100, target py39; `[tool.ruff.lint] select = ["E", "F", "I"]` (pycodestyle errors, pyflakes, isort).
- devShell provides `black` + `ruff`; no mypy/pyright config anywhere. No CI lint check — linters are manual/devShell only.

## 4. `experiments/` layout and precedent

Per `experiments/README.md`: "historical prototypes and smoke-test notes … not part of the production library, CLI, or CI contract." One directory per SUT/prototype:

| Dir | Contents |
|---|---|
| `etcd-cluster/` | sweep/shrink logs (`.log`), findings/notes `.md`, `*-summary.json`/`.txt`, `.nix`-adjacent rerun logs |
| `kafka-cluster/` | same + **Python script** `rerun-sweep-summarize-20260824.py`, shell helper `rerun-poll-20260824.sh`, minimal-case `.nix` files |
| `nginx/` | `smoke-test/` and `orchestrator-test/` subdirs each with `config-target.nix`, `module.nix`, `properties.nix`, `README.md`, `run-*.sh`, `test-script.py` (a NixOS testScript **snippet**, injected by the runner — not standalone Python) |
| `postgresql/` | smoke/sweep logs, findings/readiness `.md` |
| `rabbitmq/` | (empty at this commit) |
| `nr0/`–`nr8-mvp/` | numbered dev prototypes: standalone flakes, Rust `test_binary/` crates, shell scripts, result logs |

**Script precedent** (`experiments/kafka-cluster/rerun-sweep-summarize-20260824.py`):
- Standalone `#!/usr/bin/env python3` script, stdlib only (`argparse`, `csv`, `json`, `os`).
- **No `topotestix` package imports** — reads run-store JSON directly from `--runs-dir .topotestix/runs`.
- Invoked from repo root: `nix develop -c python3 experiments/kafka-cluster/rerun-sweep-summarize-20260824.py --runs-dir .topotestix/runs ...` (usage docstring).
- Emits `*-summary.json` + `*-summary.txt` next to the experiment's logs.

So: the established precedent for a reproduction tool in `experiments/` is a **standalone script tree**, not a packaged module.

## 5. Repo conventions worth following

- **File naming**: kebab-case for Nix/logs/docs (`expand-topology.nix`, `etcd-cluster-sweep-1-50-20260616-summary.json`), snake_case for Python modules (`run_store.py`, `reports.py`). Experiment artifacts carry date stamps (`-YYYYMMDD`) in filenames.
- **Nix modules** (`lib/*.nix`): each file is a function taking `{ lib }` (plus `pkgs`/`testers` where needed, injected via `runnerFor`/`orchestrateFor` in `lib/default.nix:10-16`) and returning an attribute set; `lib/default.nix` aggregates via `inherit`. Tests aggregate in `tests/default.nix` with attrset `//`.
- **Atomic-write patterns**: no shared `atomic-write` utility exists. Precedents in `topotestix/run_store.py`:
  - atomic *create*: `os.makedirs(run_dir, exist_ok=False)` + `FileExistsError` retry (run_store.py:83-96).
  - `write_json`: `json.dump(..., indent=2, sort_keys=True)` + trailing newline (run_store.py:97-101).
  - `safe_name()` regex `[A-Za-z0-9_.-]+` → `-` for run IDs.
- **Python style**: stdlib-only, `typing` hints (`Optional`, `list[str]`), argparse with `--verbose/--quiet/--json`, module docstrings explaining provenance/purpose, soft-fail helpers (e.g. `git_head` returns `""` on failure), type comments rare; comments explain *why*.
- **Run data**: run store at `.topotestix/runs/<run-id>/` with `run.json`, `resolved.json`, `report.json`.

## 6. Git state (at time of discovery)

- Branch: `thesis-eval-repro`
- HEAD: `9afe743463666fd4e768fd63a1c48f5823dd5b8c` ("docs: rerun update")
- Staged (new): `targets/etcd-cluster-v1/config.nix`, `targets/etcd-cluster-v1/properties.nix`
- Modified: `targets/default.nix`
- Untracked: `thesis-eval-reproduction-plan.md`

## RECOMMENDATIONS

- **Package location**: `experiments/reproduce/` is consistent with the layout (one dir per experiment/tool), **but** it must be a **standalone script tree**, not an installable package: pyproject only packages `topotestix*`, so `experiments.*` can never be imported from the installed app. Also, unlike `nr0`/`nginx` subdirs, nothing in `experiments/` is added to `checks.` — CI won't run it automatically. Follow the `rerun-sweep-summarize-20260824.py` precedent.
- **Entry-point style**: `nix develop -c python3 experiments/reproduce/<name>.py --runs-dir .topotestix/runs ...` run from repo root (argparse CLI, stdlib-only). Do NOT add a console_script (keeps experiments/ out of the production CLI contract per `experiments/README.md`). If multiple modules are needed, use a `experiments/reproduce/` directory with plain-module relative structure driven by a main script (relative imports work only if run as `python -m` from repo root or with the dir on `sys.path`; the safest repo-precedent form is flat single-file scripts or a main script that does explicit path insertion — prefer flat).
- **Test location**: Python unit tests must go in `tests/test_*.py` to be picked up by `unittest discover -s tests -p 'test_*.py'` (both the flake `checks.python` and the `runtest` alias). Since `experiments/reproduce/` is not importable as a package, tests should load the script via `importlib.util.spec_from_file_location("...", "experiments/reproduce/<name>.py")` or duplicate/pure-function logic placed in the script and loaded that way — no existing test does cross-tree imports, so keep the loader helper small. Nix-side behavior belongs in `lib/*.nix` + `tests/*-test.nix` if any.
- If the tool ends up needing real reuse of `topotestix` internals (e.g. `RunStore`), prefer importing `topotestix` (works from repo-root cwd and in devShell) rather than reimplementing, but keep `experiments/` outside pyproject packaging.
