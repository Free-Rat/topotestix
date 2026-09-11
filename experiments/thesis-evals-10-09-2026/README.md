# Thesis evaluation reproduction — output directory

Re-run everything from the repo root (branch `thesis-eval-repro`):

    nix develop -c python3 -m experiments.reproduce \
        --manifest experiments/reproduce/MANIFEST.json --out experiments/thesis-evals-10-09-2026 --phase all

Phases (pass individually with `--phase <name>`):

  - `run`      — execute every manifest unit (nix build + VM); resumable via
                 `raw/<unit-id>/status.json`; `--jobs K` bounds concurrency,
                 `--force` re-runs done units, `--only <entry>` limits scope.
  - `digest`   — (re)write `raw/<unit-id>/log-digest.json` from the unit logs.
                 Runs automatically at the end of `run`; run it on its own
                 after any out-of-band run so the committed tree keeps the
                 log-derived evidence.
  - `analyze`  — rebuild `analysis/` from `raw/` + `resolution/` (pure).
  - `verify`   — score `study/repro-discovery/claims.csv` against `analysis/`
                 and write `verification/claims-matrix.csv` (pure).
  - `report`   — write `verification/VERIFICATION_REPORT.md` + this README.

`--dry-run` prints unit counts, wall-clock/compute estimates, and a `--jobs`
recommendation without executing anything. See
`python3 -m experiments.reproduce --help` for the authoritative flag list.

## Directory contents

  - `MANIFEST.lock.json` — pinned revs, host, extraction source (provenance),
    and `campaign_token`: the fresh-execution token threaded into every unit's
    `--repetition-token`. Re-running `--phase all` against this dir reuses it
    (idempotent). A new `--out` dir, or `--fresh-token`, mints a new token so
    every unit re-executes as a genuine VM run instead of a Nix cache replay.
  - `raw/<unit-id>/`     — one directory per planned unit: status.json,
    run.json, choices.json, resolved.json, report.json, timing.json,
    resources.json, nix-build.json, stdout/stderr logs, evidence payloads,
    and log-digest.json — a bounded projection of the logs (which are
    gitignored: ~340 MB/campaign) carrying every line analysis parses, so
    analysis is identical whether the *.log files are present or not.
  - `resolution/<target>/` — pure per-seed resolution statistics:
    per-seed-choices.jsonl, uniqueness.json, marginals.csv,
    pairwise-coverage.json.
  - `analysis/`          — deterministic artifacts written by analyze.py:
    kafka-sweep(.json/.csv), kafka-crosstab.csv, kafka-shrink.json,
    kafka-min-configs.json, etcd-v1-sweep.json, etcd-v2-sweep.json,
    etcd-v2-quota-correlation.csv, etcd-v2-shrink.json,
    etcd-v2-exhaustive(.json/.csv), rabbitmq-{disk,faildom,crash}-cells.csv,
    determinism.json, test-suites.json, stage-timing.json, parallelism.json,
    execution-accounting(.json/.csv).
  - `verification/`      — claims-matrix.csv (one row per thesis claim) and
    VERIFICATION_REPORT.md (human-readable summary).

## Verdict semantics (verification/claims-matrix.csv)

  - `match`                  — artifact present; observed equals expected.
  - `within-tolerance`       — observed inside the range the claim text allows
    (e.g. "22 or 23 recovered", "approx 104.5 MB" accepted as 100-110).
  - `mismatch`               — artifact present; observed contradicts the claim.
  - `not-reproduced`         — artifact or data row absent; the `reason` column
    says which. Never treated as a pass.
  - `informational-observed` — informational/timing claim; the observed value
    is reported but never scored as mismatch.

Analysis and verification are pure functions of `raw/` + `resolution/`:
re-running them re-executes zero VM runs and must produce byte-identical
outputs (no timestamps; the lock file owns provenance). That holds for a
fresh clone too, where the gitignored `*.log` files are absent and
`log-digest.json` is the source for everything derived from them.

`stage-timing.json` reports only stages the VM driver itself timed
(`vm_boot_s`, `test_script_s`); `nix_eval_s`/`build_s` are null because the
nix build log carries no per-line timestamps. `parallelism.json` compares
group wall-clock spans (max end - min start), never sums of per-unit wall
times — concurrency does not shrink such a sum.
