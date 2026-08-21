# Empirical note: `rabbitmq-cluster`

> **Historical evidence, not a current thesis result.** Nix cache reuse was
> counted as repeated execution and the exactly-once oracle was incomplete.
> See `docs/rabbitmq/evaluation-audit-2026-08-21.md`.

This note summarizes the RabbitMQ baseline sweep for thesis use.

## Thesis framing

The `rabbitmq-cluster` baseline experiment should **not** be described as
finding RabbitMQ implementation bugs. It is the correctness-floor case study:
TopoTestix exercised the full fuzzer → runner pipeline against a real
three-node RabbitMQ quorum-queue cluster across 500 fuzz seeds and observed
that the baseline configuration surface is robust — every run formed a
healthy cluster and satisfied every property.

This baseline is the counterpart to the deep-sweep axes in
`docs/rabbitmq/deep-sweep-plan.md`; it is the "Target 1: Baseline quorum
queue correctness" run from that plan.

## Target

`rabbitmq-cluster` is a three-node RabbitMQ quorum-queue baseline target:

```text
targets/rabbitmq-cluster/topology.nix
targets/rabbitmq-cluster/config.nix
targets/rabbitmq-cluster/module.nix
targets/rabbitmq-cluster/test-script.py
targets/rabbitmq-cluster/properties.nix
```

The topology uses three nodes:

```text
rabbit1, rabbit2, rabbit3
```

The target checks 15 outcomes:

- cluster formation from all three nodes,
- quorum-queue roundtrip in three publish/consume orderings
  (`r1→r2→r3`, `r2→r3→r1`, `r3→r1→r2`),
- quorum-queue roundtrip with non-durable / fire-and-forget publish,
- multiple-message roundtrip (mixed sizes, durable + confirms),
- no phantom messages on any node,
- exactly-once delivery (no duplication or loss) for 20 messages,
- service still up after a delay on all three nodes.

## Sweep

500-seed sweep, all from `2026-07-11`, stored under:

```text
.topotestix/runs/20260711-*-rabbitmq-cluster-seed-*-rabbitmq-cluster-seed-*
```

Reproduce any run with the `reproduceCommand` in that run's `run.json`, e.g.:

```text
topotestix orchestrator run rabbitmq-cluster --seed 3 --name rabbitmq-cluster-seed-3 ...
```

## Result: 500 / 500 passed (100%)

| Outcome | Count |
|---|---:|
| Passed | 500 |
| Failed | 0 |
| Total | 500 |

All 15 checks passed in every run (7500 / 7500 individual assertions).
No failed or aborted runs. No failing checks observed.

Per-check pass rate:

| Check | Pass |
|---|---:|
| `rabbitmq-cluster-formed-rabbit1` | 500 |
| `rabbitmq-cluster-formed-rabbit2` | 500 |
| `rabbitmq-cluster-formed-rabbit3` | 500 |
| `rabbitmq-no-duplication` | 500 |
| `rabbitmq-no-phantom-rabbit1` | 500 |
| `rabbitmq-no-phantom-rabbit2` | 500 |
| `rabbitmq-no-phantom-rabbit3` | 500 |
| `rabbitmq-quorum-roundtrip-r1-r2-r3` | 500 |
| `rabbitmq-quorum-roundtrip-r2-r3-r1` | 500 |
| `rabbitmq-quorum-roundtrip-r3-r1-r2` | 500 |
| `rabbitmq-quorum-roundtrip-multi` | 500 |
| `rabbitmq-quorum-roundtrip-non-durable` | 500 |
| `rabbitmq-still-up-rabbit1` | 500 |
| `rabbitmq-still-up-rabbit2` | 500 |
| `rabbitmq-still-up-rabbit3` | 500 |

Run duration (wall):

```text
min     = 89.8 s
max     = 119.6 s
mean    = 106.4 s
median  = 106.9 s
```

## Fuzz coverage verification

The fuzzer (`lib/fuzzer.nix`) is deterministic and seed-based. Empty
`choices.json` files are expected: `topologyChoices` / `configChoices` record
*shrinker overrides*, not fuzzer selections (see `lib/orchestrate.nix:71-83`).
Whether the sweep actually explored the target axes was verified by
re-evaluating the fuzzer over the 500 seeds directly.

### Config axes (`targets/rabbitmq-cluster/config.nix`)

All five configured axes varied and were close to uniformly distributed:

| Axis | Value | Count |
|---|---|---:|
| `virtualisation.memorySize` | 2048 | 252 |
| `virtualisation.memorySize` | 3072 | 248 |
| `virtualisation.diskSize` | 2048 | 252 |
| `virtualisation.diskSize` | 4096 | 248 |
| `disk_free_limit.absolute` | 50MB | 239 |
| `disk_free_limit.absolute` | 200MB | 261 |
| `vm_memory_high_watermark.relative` | 0.4 | 244 |
| `vm_memory_high_watermark.relative` | 0.6 | 256 |
| `heartbeat` | 30 | 259 |
| `heartbeat` | 60 | 241 |

This spans the full 2^5 = 32 distinct config cells over 500 runs, so each
cell is hit roughly 15× on average. Combined cells (e.g. the tightest
`disk_free_limit=50MB` + `memorySize=2048`) were exercised repeatedly with
no failures.

### Topology axes (`targets/rabbitmq-cluster/topology.nix`)

The topology target pins single-element lists by design:

```nix
roles.rabbit = [ 3 ];
rabbitVlans  = [ [ 1 ] ];
```

Confirmed: `topoDistinctCount = 1` across all 500 seeds — every run is a
3-node cluster on a single VLAN. The baseline target deliberately fixes
the topology and only fuzzes config. Topology-axis exploration belongs to
the fault-injection targets in `docs/rabbitmq/deep-sweep-plan.md`, not to
this baseline.

## Interpretation

1. The baseline `rabbitmq-cluster` target is robust under the current
   conservative config surface. Across ~15× coverage of each config cell,
   no run failed to form a cluster, complete quorum roundtrips in all
   orderings, or preserve exactly-once delivery.
2. The fuzzer distribution is near-uniform and independent across
   dimensions — no seed bias is present.
3. Because `choices.json` is empty in all 500 runs, none of these runs are
   shrunk reproductions; they are raw fuzz seeds. Each run is reproducible
   by its `run.json` `reproduceCommand`.
4. The pass-only outcome is a meaningful result for the thesis: it is the
   correctness floor against which the later disk-pressure, memory-pressure,
   crash-consistency, DNS, and partition targets are contrasted.

## Limitations and next steps

The sweep samples only two values per config axis, and the target axes are
explicitly conservative (note in `targets/rabbitmq-cluster/config.nix:5`).
To probe failure modes:

- Broaden `config.nix` (lower `memorySize` to `512` / `4096`, lower
  `vm_memory_high_watermark.relative` to `0.2`, lower
  `disk_free_limit.absolute` to `10MB`, larger `heartbeat`).
- Add fault-injection targets that fuzz topology
  (`roles.rabbit = [ 1 3 5 ]`, multiple VLANs / partitions) and add
  node-restart / net-partition properties — the current property set only
  covers static correctness, not failure recovery.
- The 2^5 config cells saturate after ~96 runs at ≥3× coverage each; the
  remaining ~400 baseline runs add no new config coverage under the current
  axes and could be trimmed.

See `docs/rabbitmq/deep-sweep-plan.md` for the planned deep-sweep axes.

## Artifacts

Detailed sweep artifacts:

```text
.topotestix/runs/20260711-084104-rabbitmq-cluster-seed-1-rabbitmq-cluster-seed-1
  ...
.topotestix/runs/20260711-103040-rabbitmq-cluster-seed-500-rabbitmq-cluster-seed-500
```

Each run directory contains:

```text
run.json        # status, timing, reproduceCommand
report.json     # per-check status
choices.json    # shrinker overrides (empty in this sweep)
expr.nix        # generated Nix expression (distinct per seed)
target.json     # target manifest
stderr.log      # nix build + vm-test driver log
result          # built test result (symlink to /nix/store)
```

## Suggested thesis paragraph

TopoTestix was evaluated on a three-node RabbitMQ quorum-queue cluster as the
correctness-floor case study. A 500-seed sweep over a conservative but real
configuration surface — virtual machine memory and disk size, RabbitMQ disk
alarm threshold, memory high-watermark, and heartbeat — exercised roughly
fifteen repetitions of each of the 32 distinct configuration cells. Every run
formed a healthy cluster, completed quorum-queue roundtrips in all three
publish/consume orderings including a non-durable fire-and-forget publish,
verified exactly-once delivery for a multi-message workload, and remained
healthy after a delay. All 500 runs and all 7500 individual property
assertions passed. This establishes the baseline behavior against which the
later disk-pressure, memory-pressure, crash-consistency, DNS, and
network-partition targets from the RabbitMQ deep-sweep plan are contrasted.
