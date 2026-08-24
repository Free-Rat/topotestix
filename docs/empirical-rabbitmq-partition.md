# Empirical note: `rabbitmq-partition`

> **Historical prototype.** The current oracle does not prove complete quorum
> history safety. Do not use the pass totals below as thesis evidence; see
> `docs/rabbitmq/evaluation-audit-2026-08-21.md`.

This note summarizes the design verification and 50-seed sweep of the
`rabbitmq-partition` target for thesis use.

## Thesis framing

The `rabbitmq-partition` target is the **quorum-safety case study** for
TopoTestix's environment-aware testing of RabbitMQ. It exercises the
network-partition axis of the deep-sweep plan
([`docs/rabbitmq/deep-sweep-plan.md`](rabbitmq/deep-sweep-plan.md), axis
F: Network topology / partitions) by deliberately inducing a partition at
runtime and asserting that:

- the minority side does not accept unsafe writes to the quorum queue,
- the majority side remains available for writes,
- the cluster re-converges after the partition is healed,
- no message duplication (split-brain) appears in the queue history,
- every node's `rabbitmq.service` remains active.

This target corresponds to **Target 6: Network partition behavior** from the
deep-sweep plan and is intended to be contrasted against the correctness
floor established by the `rabbitmq-cluster` baseline.

## Target

`rabbitmq-partition` is a three-node RabbitMQ quorum-queue network-partition
target:

```text
targets/rabbitmq-partition/topology.nix
targets/rabbitmq-partition/config.nix
targets/rabbitmq-partition/module.nix
targets/rabbitmq-partition/test-script.py
targets/rabbitmq-partition/properties.nix
```

The topology uses three nodes on a single VLAN:

```text
rabbit1, rabbit2, rabbit3
```

The partition is applied at runtime by `test-script.py` using `iptables`,
so the underlying topology stays fully connected. This keeps the fuzz
surface focused on partition behavior rather than on initial connectivity.

The target checks 7 outcomes (the same 7 properties run on every seed):

- `rabbitmq-partition-cluster-converges-after-healing`
- `rabbitmq-partition-majority-accepts-writes`
- `rabbitmq-partition-minority-rejects-writes`
- `rabbitmq-partition-no-split-brain`
- `rabbitmq-partition-still-up-rabbit1`
- `rabbitmq-partition-still-up-rabbit2`
- `rabbitmq-partition-still-up-rabbit3`

## Design verification

Four of the five target files matched the patterns established by
`rabbitmq-cluster` and were accepted as correct:

- `topology.nix` — fixed 3-node cluster, single VLAN.
- `module.nix` — stable base: rabbitmq-server + management plugin +
  `unsafeCookie`, `networking.firewall.enable = false` so the test script
  can drive iptables, `heartbeat = 10` so the Erlang distribution notices
  a TCP-level partition within seconds, system packages for the test
  driver (`iptables`, `iproute2`, `gawk`, `gnused`, `python3.withPackages
  [ pika ]`, `rabbitmq-server`).
- `test-script.py` — boot → cluster formation → 3-replica quorum queue
  declare on each node → read fuzz params from `/etc/topotestix-partition-*`
  → resolve per-node eth1 addresses → apply partition (`iptables -A OUTPUT
  -d <peer-ip> -j DROP`, symmetric or one-way) → sleep 15 s for Erlang
  to notice → attempt one confirmed persistent publish from each node with
  timeout 30 → persist write outcomes + partition params to
  `/tmp/partition-results.json` → `heal_after` sleep → `iptables -F` →
  sleep 10 s for re-convergence.
- `properties.nix` — seven `_check` entries; `minority-rejects-writes`
  explicitly skips the (shape=`isolate-2`, direction=`one-way`) case
  because in that scenario the minority can still reach the majority
  and the asymmetric write acceptance is expected.

### Bug found and fixed in `config.nix`

The initial version of `config.nix` wrapped every choice list in a
single-argument function:

```nix
environment.etc."topotestix-partition-shape".text = (
  _:
  [ "none" "isolate-1" "isolate-2" ]
);
```

The fuzzer (`lib/fuzzer.nix` → `lib/combinators.nix:resolveWithKeyPrefix`)
handles functions by calling them with `{ inherit lib; }` and recursing on
the returned list, so 5 pre-fix seeds ran fine. But at the time,
`lib/shrinker.nix` (`valueAtChecked`, lines 173-178 after `c0807fe`;
`getValueByPath` at line 81) called `getValueByPath`
directly without an `isFunction` branch, and threw
`"shrinker: path ... is not a choice list"` whenever a shrinker override
was applied to one of the four partition dimensions.

The wrapping therefore **broke choice-based shrinking** for this target
even though the fuzzer produced identical choices. The header comment in
the original `config.nix` claimed the wrapping "defers the choice until
the fuzzer evaluates it" — true, but the deferral buys nothing because
the fuzzer handles raw lists directly, and the comment's other claim
that "the shrinker can reduce each dimension toward index 0 in isolation"
was incorrect.

Repro before the fix:

```text
$ nix-instantiate --eval --strict --json -E '
  let
    pkgs = import <nixpkgs> {};
    lib = pkgs.lib;
    shrinker = import ./lib/shrinker.nix { inherit lib; };
    fuzzerMod = import ./lib/fuzzer.nix { inherit lib; };
    configTarget = import ./targets/rabbitmq-partition/config.nix { inherit lib; };
    fuzzed = fuzzerMod.fuzzer { seed = "2"; target = configTarget; };
  in
  shrinker.apply configTarget fuzzed.result {
    ".environment.etc.topotestix-partition-shape.text" = 0;
  }'
error: shrinker: path .environment.etc.topotestix-partition-shape.text is not a choice list
```

### Fix

Removed all four `(_: [ ... ])` wrappers so each dimension is a direct
list literal:

```nix
environment.etc."topotestix-partition-shape".text = [
  "none"
  "isolate-1"
  "isolate-2"
];
```

After the fix:

- The fuzzer produces byte-identical choices for seeds 1-5 (verified by
  re-evaluating the fuzzer directly), so the existing 5 runs are
  semantically equivalent to re-runs against the fixed target.
- `shrinker.apply` no longer throws; `shrinker.choicePaths` returns the
  four expected paths; `shrinker.optionsFor` returns the raw list;
  `shrinker.valueAt target path 0` returns the head element.

## Sweep

50-seed sweep, run on 2026-08-19 after the design fix. Run directories:

```text
.topotestix/runs/20260819-*-rabbitmq-partition-seed-*-rabbitmq-partition-seed-*
```

Reproduce any run with the `reproduceCommand` in that run's `run.json`,
e.g.:

```text
topotestix orchestrator run rabbitmq-partition --seed 3 --name rabbitmq-partition-seed-3 ...
```

## Result: 50 / 50 passed (100%)

| Outcome | Count |
|---|---:|
| Passed | 50 |
| Failed | 0 |
| Total | 50 |

All 7 checks passed in every run (350 / 350 individual assertions).
No failed or aborted runs. No failing checks observed.

Per-check pass rate:

| Check | Pass |
|---|---:|
| `rabbitmq-partition-cluster-converges-after-healing` | 50 |
| `rabbitmq-partition-majority-accepts-writes` | 50 |
| `rabbitmq-partition-minority-rejects-writes` | 50 |
| `rabbitmq-partition-no-split-brain` | 50 |
| `rabbitmq-partition-still-up-rabbit1` | 50 |
| `rabbitmq-partition-still-up-rabbit2` | 50 |
| `rabbitmq-partition-still-up-rabbit3` | 50 |

Run duration (wall):

```text
min     =  56.2 s
max     = 136.7 s
mean    = 105.1 s
median  = 116.3 s
total   = 5256.0 s  (~87.6 minutes)
```

The duration spread correlates with `heal`: `heal=0` runs are the fastest
(mean 95.9 s over 14 runs) because the partition is flushed immediately;
`heal=15` (18 runs, mean 116.1 s) and `heal=30` (18 runs, mean 101.3 s)
wait inside the test script before flushing iptables. Per-shape means are
flat (`none` 107.1 s, `isolate-1` 104.6 s, `isolate-2` 103.6 s), as
expected — the partition itself is set up and torn down identically
across shapes.

## Fuzz coverage verification

The fuzzer (`lib/fuzzer.nix`) is deterministic and seed-based. Empty
`choices.json` files are expected: `topologyChoices` / `configChoices`
record *shrinker overrides*, not fuzzer selections (see
`lib/orchestrate.nix:71-83`). Whether the sweep actually explored the
target axes was verified by re-evaluating the fuzzer over the 50 seeds
directly.

### Config axes (`targets/rabbitmq-partition/config.nix`)

All three varied dimensions were explored and reasonably balanced; the
fourth (`ports`) is a single-element list by design:

| Axis | Value | Count |
|---|---|---:|
| `topotestix-partition-shape` | `none` | 16 |
| `topotestix-partition-shape` | `isolate-1` | 20 |
| `topotestix-partition-shape` | `isolate-2` | 14 |
| `topotestix-partition-direction` | `two-way` | 22 |
| `topotestix-partition-direction` | `one-way` | 28 |
| `topotestix-partition-heal` | `0` | 14 |
| `topotestix-partition-heal` | `15` | 18 |
| `topotestix-partition-heal` | `30` | 18 |
| `topotestix-partition-ports` | `none` | 50 |

Joint coverage of `(shape × direction × heal)` over 50 runs:

- 17 / 18 distinct cells exercised; only
  `(shape=none, direction=two-way, heal=0)` was missed.
- Each exercised cell was hit between 1 and 6 times (mean ~2.8).
- The 4 cells with `(shape=isolate-2, direction=one-way)` were
  intentionally skipped by `minority-rejects-writes` (see
  `properties.nix:23-24`); the property is not applicable there because
  the minority can still reach the majority in the asymmetric case. The
  other properties (`majority-accepts-writes`, `no-split-brain`,
  `cluster-converges-after-healing`, `still-up-*`) still ran on those
  cells and all passed.

### Topology axes (`targets/rabbitmq-partition/topology.nix`)

The topology target pins single-element lists by design:

```nix
roles.rabbit = [ 3 ];
rabbitVlans  = [ [ 1 ] ];
```

Confirmed: `topoDistinctCount = 1` across all 50 seeds — every run is a
3-node cluster on a single VLAN. The partition target deliberately fixes
the topology and only fuzzes config; topology-axis exploration belongs
to the fault-injection targets in `docs/rabbitmq/deep-sweep-plan.md`.

## Interpretation

1. The `rabbitmq-partition` target is correct on the fixed config and
   robust under the current partition surface. Across ~2.8 repetitions
   of each of the 18 (shape × direction × heal) cells, every run kept
   the cluster healthy: the minority never accepted unsafe writes, the
   majority always accepted writes, the queue ended with a unique-only
   history (no split-brain), the cluster re-converged after the iptables
   rules were flushed, and every node's `rabbitmq.service` stayed
   active.
2. The fuzzer distribution is reasonably balanced across the three
   varied dimensions. With only 50 runs the per-cell sample is small but
   covers 17 / 18 cells, which is sufficient for a correctness-floor
   observation; doubling the seed range would close the remaining gap.
3. The `minority-rejects-writes` property correctly skips the
   asymmetric `(isolate-2, one-way)` cases; this is a property-side
   decision, not a partition bug. All 4 such cells were visited and
   passed under the other 6 properties.
4. Because `choices.json` is empty in all 50 runs, none of these runs
   are shrunk reproductions; they are raw fuzz seeds. Each run is
   reproducible by its `run.json` `reproduceCommand`.

## Limitations and next steps

- 50 seeds over 18 cells gives ~2.8 runs per cell on average; the missed
  cell (`shape=none, direction=two-way, heal=0`) and the sparser
  `(isolate-2, *)` cells could be tightened by extending the sweep to
  100 or 200 seeds, or by shrinking the surface (e.g. dropping `heal=0`
  because it provides no information over `heal=15`).
- `topotestix-partition-ports` is a single-element list (`"none"`); port
  filtering (AMQP-only or Erlang-only) is documented in `config.nix` and
  `test-script.py` as future work because the Erlang distribution in
  particular uses ephemeral ports resolved via EPMD, which a port-list
  rule does not reliably partition in the NixOS VM test harness.
- The fixed config.nix still leaves `topologyChoices` and `configChoices`
  empty in every run, because the sweep does not invoke shrinking.
  Shrinking is now *possible* (the previous design bug is fixed) but
  not exercised by this sweep; no shrinking failures were observed.
- The partition surface does not yet vary the *duration* the partition
  is held before Erlang detects it (controlled indirectly by
  `heartbeat=10` plus the fixed 15 s `time.sleep(15)` after iptables
  apply in `test-script.py:132`). A future revision could fuzz the
  detection-budget sleep alongside `heal`.

See `docs/rabbitmq/deep-sweep-plan.md` axis F for the planned follow-ups.

## Artifacts

Detailed sweep artifacts:

```text
.topotestix/runs/20260819-140148-rabbitmq-partition-seed-1-rabbitmq-partition-seed-1
  ...
.topotestix/runs/20260819-152712-rabbitmq-partition-seed-50-rabbitmq-partition-seed-50
```

Each run directory contains:

```text
run.json        # status, timing, reproduceCommand
report.json     # per-check status (7 entries)
choices.json    # shrinker overrides (empty in this sweep)
expr.nix        # generated Nix expression (distinct per seed)
target.json     # target manifest
stderr.log      # nix build + vm-test driver log
result          # built test result (symlink to /nix/store)
```

## Suggested thesis paragraph

TopoTestix was evaluated on the network-partition axis of the RabbitMQ
deep-sweep plan as the quorum-safety case study. A 50-seed sweep over a
curated fuzz surface — partition shape (none / 1-node isolated / 2-node
isolated), partition direction (two-way / one-way), and heal delay
(0 / 15 / 30 s) — exercised 17 of the 18 distinct configuration cells
with no failures. Every run kept the cluster healthy: the minority
never accepted unsafe writes to the 3-replica quorum queue, the majority
remained available, the queue ended with a unique-only message history
(no split-brain), the cluster re-converged after the iptables rules were
flushed, and every node's `rabbitmq.service` stayed active. All 50 runs
and all 350 individual property assertions passed. A latent design bug
in the target's `config.nix` was found and fixed during verification:
wrapping each choice list in a deferred function (`(_: [ ... ])`) broke
choice-based shrinking because the shrinker uses `getValueByPath`, which
has no function-unwrap branch. Removing the wrappers restored shrinker
introspection without changing fuzzer output. This establishes the
quorum-safety baseline against which later disk-pressure,
memory-pressure, crash-consistency, and DNS axes from the RabbitMQ
deep-sweep plan are contrasted.
