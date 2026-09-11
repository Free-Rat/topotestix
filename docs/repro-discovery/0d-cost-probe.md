# 0d — Cost probe: three end-to-end experiment units + campaign extrapolation

Subagent 0d, 2026-09-04. Branch `thesis-eval-repro`, dirty working tree.
Framework invoked as `nix develop -c python3 -m topotestix.cli ...` (repo root).
Host: 30 GiB total RAM (~22–23 GiB available at probe start), 0 swap.

## Method notes

- psutil is **not** available inside `nix develop` (import fails) → resource
  sampling done with a background bash watcher (`/tmp/opencode/watch-ram.sh`)
  sampling `/proc/meminfo` MemAvailable and summed RSS of all qemu processes
  every 2 s.
- The CLI's nix build (`topotestix/nix.py:build_test`, `nix build --file <expr>
  -o result -L`) runs the NixOS test **during the build**: the VM phase lives
  inside `nix build` (`vm-test-run-<name> …` lines in `stderr.log`).
- The derivation name (`vm-test-run-<name>`) contains the run `--name`, so a
  unique `--name` forces a **fresh** build + VM run. An identical
  (target, seed, choices, name) rerun is a **cache replay**: instant, and — per
  plan §"Honesty about cache vs fresh" — NOT a fresh VM execution. All three
  probes used fresh names, hence measured fresh-build costs. The determinism
  repetitions in the campaign must also vary the name (e.g. append
  `-rep<N>`) or force `nix-store --delete` to get honest fresh runs.

## Unit 1 — kafka-cluster, seed 1 (full VM run)

- Command:
  `nix develop -c python3 -m topotestix.cli orchestrator run kafka-cluster --seed 1 --name kafka-cost-probe-0d --project-root .`
- Run dir: `.topotestix/runs/20260904-085849-kafka-cluster-seed-1-kafka-cost-probe-0d`
- Wall clock: **213.8 s** (3m33.8s); exit code **1** (expected: seed 1 = known
  `broker-message-max-too-small` failure class; properties 11 PASS / 1 FAIL,
  overall FAILED — matches sweep records).
- Build phase ≈ 34 s (nix eval + 196 derivations built, incl. first-time
  download of test-driver python deps from cache.nixos.org); VM phase ≈ 178 s
  (3 VMs: boot ~10 s, kafka service up ~14 s, +30 s settle sleeps, roundtrips).
- Fresh or cached: **fresh** ("these 196 derivations will be built"; new name
  → new `vm-test-run-kafka-cost-probe-0d.drv`).
- Peak RAM: qemu RSS sum **3.05 GiB** (3 VMs ≈ 1.0 GiB each); host
  MemAvailable floor 19.2 GiB (from ~23.4 GiB baseline).

## Unit 2 — etcd-cluster (v2, `targets/etcd-cluster`), seed 1

- Command:
  `nix develop -c python3 -m topotestix.cli orchestrator run etcd-cluster --seed 1 --name etcd-v2-cost-probe-0d --project-root .`
- Run dir: `.topotestix/runs/20260904-090243-etcd-cluster-seed-1-etcd-v2-cost-probe-0d`
- Wall clock: **97.9 s**; exit code **0** (12/12 PASS, overall PASSED).
- Build phase ≈ 15 s (65 derivations, deps now cached); VM phase ≈ 83 s.
- Fresh or cached: **fresh** ("these 65 derivations will be built").
- Peak RAM: qemu RSS sum **1.58 GiB** (3 VMs ≈ 0.53 GiB each); MemAvailable
  floor 20.8 GiB.

## Unit 3 — rabbitmq designed cell: disk positive control (`rabbitmq-disk`), seed 1

- Invocation reconstructed from retained run
  `.topotestix/runs-thesis-redesign/20260822-183835-rabbitmq-disk-seed-1-phase2-disk-positive/run.json`
  (`reproduceCommand`) + `choices.json`. The designed cell **is** the target
  (`targets/rabbitmq-disk/*`); `choices.json` there shows
  `{topologyChoices:{}, configChoices:{}}` — no forced choice overrides needed.
- Command:
  `nix develop -c python3 -m topotestix.cli orchestrator run rabbitmq-disk --seed 1 --name rabbitmq-disk-cost-probe-0d --project-root . --topology-target ./targets/rabbitmq-disk/topology.nix --config-target ./targets/rabbitmq-disk/config.nix --base-module ./targets/rabbitmq-disk/module.nix --test-script ./targets/rabbitmq-disk/test-script.py --properties ./targets/rabbitmq-disk/properties.nix`
- Run dir: `.topotestix/runs/20260904-090430-rabbitmq-disk-seed-1-rabbitmq-disk-cost-probe-0d`
- Wall clock: **82.6 s**; exit code **0** (5/5 PASS — matches thesis disk
  positive control 5/5).
- Build phase ≈ 27 s (68 derivations); VM phase ≈ 55 s.
- Fresh or cached: **fresh** ("these 68 derivations will be built").
- Peak RAM: qemu RSS sum **2.11 GiB** (3 VMs ≈ 0.70 GiB each); MemAvailable
  floor 20.1 GiB.

## Shrink cost model

`orchestrator shrink <target> <seed>` (`topotestix/orchestrator.py:cmd_shrink`)
does: 1 initial verify run + a loop over candidate choice maps
(`candidate_choice_maps`, decrementing each choice index one path at a time);
**every candidate is a full `run_once` = full nix build + VM run**. Number of
builds = #accepted shrinks + #tried-and-rejected candidates, driven by the
choice-space size per role (config + topology). From the help text alone the
build count is not fixed; the plan itself says "dozens of builds each".
Working estimate: **10–30 builds per shrink loop, midpoint 20** (each at the
target's per-run cost above). Historical shrink logs
(`experiments/*/etcd-cluster-v2-shrink-seed-*.log`,
`kafka-cluster-shrink-seed-*.log`) confirm multi-hour loops.

## Campaign extrapolation (per `thesis-eval-reproduction-plan.md` §counts)

Per-run wall clocks (fresh build, jobs=1): kafka 214 s, etcd v1/v2 98 s,
rabbitmq cell 83 s. Shrink: 20 builds/run target (range 10–30).

| Group | Runs | Unit cost | Total |
|---|---|---|---|
| kafka sweep, seeds 1..50 × rep2 | 100 | 214 s | 5.94 h |
| kafka shrink (seeds 9, 13) | 2 × (10–30) builds | 214 s | 1.19–3.57 h (mid 2.38 h) |
| etcd v1 sweep, seeds 1..50 | 50 | 98 s | 1.36 h |
| etcd v2 sweep, seeds 1..50 × rep2 | 100 | 98 s | 2.72 h |
| etcd v2 shrink (seeds 3, 40 × rep2) | 4 × (10–30) builds | 98 s | 1.09–3.27 h (mid 2.18 h) |
| etcd v2 exhaustive, 96 forced-choice cells | 96 | 98 s | 2.61 h |
| rabbitmq designed cells | ~12 | 83 s | 0.28 h |
| **Total, jobs=1** | | | **~17.5 h (range ~15–21 h)** |

Caveats:
- If the two repetitions per seed are run under an identical name, they become
  nix **cache replays** (≈0 s, but not fresh VM executions — see honesty note
  above). The table above prices the honest version (fresh names per rep).
- etcd v2 exhaustive cells are per-cell forced `--config-choices`; same 3-node
  cluster cost per cell.
- etcd v1 archived config may need target-file overrides (same cost per run).

## Parallelism

- Host RAM: 30 GiB total, ~22 GiB available during probing. No swap.
- Per-cluster peak (qemu RSS sum): kafka 3.05 GiB, etcd 1.58 GiB, rabbitmq
  2.11 GiB. Worst case = all concurrent jobs are kafka sweeps: each job runs 3
  VMs (sweep `--jobs N` ⇒ up to N × nodes-per-cluster VMs at once, per the
  sweep help text).
- Safe max jobs K from RAM: floor(22 GiB / ~3.1 GiB) ≈ 7; leaving headroom for
  nix builds (CPU-bound, drivers) and the OS ⇒ **K = 4–5**; recommend
  `--jobs 4` (≈12–13 GiB VM RSS worst case, comfortable margin). Nix
  `max-jobs` also bounds concurrent builds.
- Expected campaign wall clock at `--jobs 4`: ~17.5 h / 4 ≈ 4.4 h theoretical;
  realistically ~5–7 h (build steps serialize on CPU and the shrink loops are
  inherently sequential). Range ≈ 4–8 h.

## Raw artifacts

- Probe logs: `/tmp/opencode/{kafka,etcd,rmq}-run.log`, `/tmp/opencode/ram-{kafka,etcd,rmq}.log`
- Run dirs under `.topotestix/runs/`: `20260904-*-{kafka-cost-probe-0d,etcd-v2-cost-probe-0d,rabbitmq-disk-cost-probe-0d}`
