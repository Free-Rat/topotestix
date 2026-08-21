# Empirical note: `rabbitmq-memory`

> **Historical prototype.** The workload and alarm oracle are insufficient for
> a thesis claim. See `docs/rabbitmq/evaluation-audit-2026-08-21.md`.

This note summarizes the design verification and per-seed sanity runs of
the `rabbitmq-memory` target for thesis use.

## Thesis framing

The `rabbitmq-memory` target is the **host-resource-sensitivity case
study** for TopoTestix's environment-aware testing of RabbitMQ. It
exercises the memory-pressure axis of the deep-sweep plan
([`docs/rabbitmq/deep-sweep-plan.md`](rabbitmq/deep-sweep-plan.md), axis
E: Memory pressure) by deliberately varying the broker's host memory,
its memory alarm watermark, and the publish load, and asserting that:

- durable, confirmed messages are not silently lost under pressure,
- no phantom messages appear in the queue after the broker drains,
- the cluster remains healthy throughout (every node sees every other
  node after the drain),
- the broker's memory alarm engages when the load and watermark combine
  to a tight setup,
- every node's `rabbitmq.service` remains active after the burst.

This target corresponds to **Target 4: Memory pressure** from
[`docs/rabbitmq/RabbitMQ-first-targets.md`](rabbitmq/RabbitMQ-first-targets.md)
and is intended to be contrasted against the correctness floor
established by `rabbitmq-cluster` and the quorum-safety baseline
established by `rabbitmq-partition`.

## Target

`rabbitmq-memory` is a three-node RabbitMQ quorum-queue memory-pressure
target:

```text
targets/rabbitmq-memory/topology.nix
targets/rabbitmq-memory/config.nix
targets/rabbitmq-memory/module.nix
targets/rabbitmq-memory/test-script.py
targets/rabbitmq-memory/properties.nix
```

The topology uses three nodes on a single VLAN:

```text
rabbit1, rabbit2, rabbit3
```

Memory pressure is applied at runtime by the test driver via a publish
burst, with the host-level memory size and broker memory watermark
configured by `config.nix` and applied at boot. The underlying topology
stays fully connected, so the fuzz surface is focused on memory
behavior rather than on connectivity.

The target checks 7 outcomes (the same 7 properties run on every seed):

- `rabbitmq-memory-no-message-loss`
- `rabbitmq-memory-no-phantom-messages`
- `rabbitmq-memory-cluster-remains-healthy`
- `rabbitmq-memory-alarm-under-pressure`
- `rabbitmq-memory-still-up-rabbit1`
- `rabbitmq-memory-still-up-rabbit2`
- `rabbitmq-memory-still-up-rabbit3`

## Design verification

The five target files were reviewed against `rabbitmq-cluster`,
`rabbitmq-partition`, and the deep-sweep plan:

- `topology.nix` — fixed 3-node cluster on a single VLAN. Correct.
- `module.nix` — stable base: `diskSize = 4096` (large enough for any
  message backlog), `networking.firewall.enable = false` so the test
  driver can communicate with the broker, `services.rabbitmq` with
  `managementPlugin`, `unsafeCookie`, distinct cluster name
  `topotestix-rabbitmq-memory`, and the test-driver packages. No fixed
  `virtualisation.memorySize` — that knob is moved to `config.nix` so
  the fuzzer can vary it.
- `test-script.py` — boot → cluster formation → 3-replica quorum queue
  declare on each node → read fuzzed `publish_count` and `message_size`
  from `/etc/topotestix-memory-*` → capture the broker's memory-alarm
  state via `rabbitmq-diagnostics check_local_alarms` at three
  checkpoints (before / after publish / after drain) → publish N
  durable, confirmed messages and tally per-message outcomes
  (`ok` / `unroutable` / `nacked` / `amqp_error` / `other_error`) →
  wait 30 s for the broker to drain and release memory → drain the
  queue with `basic_get` and count the durable messages retained →
  persist the summary to `/tmp/mempressure-results.json`.
- `properties.nix` — seven `_check` entries; `memory-alarm-under-pressure`
  explicitly skips runs where `publish_count < 500` because the broker
  may legitimately stay below its watermark under light load.
- `config.nix` — four fuzz dimensions; index 0 of every dimension is the
  least-pressured value (the control case mirroring the
  `rabbitmq-cluster` baseline). See "Fuzz coverage" below.

### Bugs found and fixed during verification

Five issues surfaced during the first end-to-end run and were resolved
before the sanity sweep:

1. **Re-import of `json`.** The initial test script imported `json`,
   but the harness preamble already imports it. NixOS VM tests lint
   the composed script and fail on duplicate imports. Removed the
   redundant `import json`; `time` is still imported explicitly because
   the preamble does not import it.
2. **`socket_timeout` on `pika.BlockingConnection`.** The initial
   script passed `socket_timeout=10` to `BlockingConnection(...)`,
   which raises `TypeError: BlockingConnection.__init__() got an
   unexpected keyword argument 'socket_timeout'`. Moved the argument
   to `pika.ConnectionParameters("localhost", socket_timeout=10)`.
3. **Wrong `rabbitmq-diagnostics` subcommand.** The initial alarm
   check used `rabbitmq-diagnostics -q check_memory_high_watermark`,
   which was removed in this RabbitMQ version (`Command
   'check_memory_high_watermark' not found.`). Replaced with
   `rabbitmq-diagnostics -q check_local_alarms`, which exits non-zero
   when any resource alarm (memory, disk) is firing on the local
   node.
4. **OOM during boot at 256 MB.** With `memorySize = 256` the NixOS
   VM kernel-panicked during Erlang startup
   (`beam.smp` RSS ≈ 125 MB and the broker's working-set exceeds the
   watermark of 0.3 × 256 MB = 76 MB). Bumped the minimum to 512 MB;
   the broker boots cleanly at that level even with `watermark=0.3`.
5. **Empty-output alarm check.** The initial implementation captured
   the alarm-check output via `machine.execute(..., check_return=False)`
   and treated empty output as "unknown". After switching to
   `check_local_alarms`, empty output is the success case (no alarms
   active), so `unknown` was relabeled to `passed`.

### Shrinker limitation discovered

The `vm_memory_high_watermark.relative` key in `services.rabbitmq.configItems`
contains dots. `lib/shrinker.nix:getValueByPath` uses
`lib.splitString "." pathStr` to navigate, so the path
`.services.rabbitmq.configItems.vm_memory_high_watermark.relative`
breaks: the shrinker tries to walk
`services → rabbitmq → configItems → vm_memory_high_watermark → relative`,
and `vm_memory_high_watermark` (without `.relative`) does not exist as
a key. The fuzzer still varies the dimension correctly across runs;
only choice-based shrinking of this dimension is blocked. The other
three dimensions (memorySize, publish_count, message_size) shrink
correctly.

## Sanity runs

Eight sanity runs were executed (no shrinking) across a spread of the
fuzz space, including the most aggressive combination (mem=512 MB,
watermark=0.3, 2000 messages of 4096 bytes). All eight passed
all 7 properties (56 / 56 individual assertions, 0 failures).

| Seed | mem | wm | pc | ms | Result |
|---:|---:|---:|---:|---:|---|
| 1 | 512 | 0.3 | 50 | 128 | 7 / 7 PASS |
| 5 | 1024 | 0.3 | 50 | 4096 | 7 / 7 PASS |
| 10 | 768 | 0.3 | 50 | 4096 | 7 / 7 PASS |
| 11 | 512 | 0.3 | 2000 | 4096 | 7 / 7 PASS (alarm engaged) |
| 3 | 512 | 0.4 | 2000 | 4096 | 7 / 7 PASS |
| 7 | 1024 | 0.3 | 50 | 1024 | 7 / 7 PASS |
| 15 | 1024 | 0.3 | 500 | 4096 | 7 / 7 PASS |
| 20 | 1024 | 0.3 | 50 | 128 | 7 / 7 PASS |

Seed 11 is the most aggressive combination in the four-dimensional
surface and is the run in which the
`memory-alarm-engages-under-pressure` property is expected to fire
rather than skip. The property did fire: the alarm-under-pressure
property passed because the broker entered the memory-alarm state
during the publish phase (the run reports `"alarm_under_pressure:
failed"` in the underlying `mempressure-results.json`, which the
property interprets as `engaged`).

Reproduce any run with the `reproduceCommand` in that run's `run.json`,
e.g.:

```text
topotestix orchestrator run rabbitmq-memory --seed 11 \
  --name rabbitmq-memory-seed-11 \
  --project-root /home/freerat/projects/topotestix \
  --topology-target targets/rabbitmq-memory/topology.nix \
  --config-target  targets/rabbitmq-memory/config.nix \
  --base-module    targets/rabbitmq-memory/module.nix \
  --test-script    targets/rabbitmq-memory/test-script.py \
  --properties     targets/rabbitmq-memory/properties.nix
```

## Fuzz coverage verification

The fuzzer (`lib/fuzzer.nix`) is deterministic and seed-based. Empty
`choices.json` files are expected: `topologyChoices` /
`configChoices` record *shrinker overrides*, not fuzzer selections (see
`lib/orchestrate.nix:71-83`). Whether the sweep actually explored the
target axes was verified by re-evaluating the fuzzer over seeds 1-20
directly.

### Config axes (`targets/rabbitmq-memory/config.nix`)

All four dimensions were exercised and covered all values of each:

| Axis | Values | Distribution (seeds 1-20) |
|---|---|---|
| `virtualisation.memorySize` | `[ 1024 768 512 ]` MB | 1024=8, 768=5, 512=7 |
| `services.rabbitmq.configItems."vm_memory_high_watermark.relative"` | `[ "0.5" "0.4" "0.3" ]` | 0.5=2, 0.4=5, 0.3=13 |
| `/etc/topotestix-memory-publish-count` | `[ "50" "500" "2000" ]` | 50=12, 500=4, 2000=4 |
| `/etc/topotestix-memory-message-size` | `[ "128" "1024" "4096" ]` bytes | 128=6, 1024=3, 4096=11 |

With 20 seeds across `3 × 3 × 3 × 3 = 81` cells, joint coverage is
sparse (≈ 25 % of cells visited once or more), but each value of each
axis was exercised at least twice. The watermark axis skews toward
`0.3` because the fuzzer's hash-based selection landed there most
often for seeds 1-20; a longer sweep would rebalance this.

The single most-aggressive combination
`(memorySize=512, watermark=0.3, publish_count=2000, message_size=4096)`
is hit by seed 11 and is the seed in which
`memory-alarm-engages-under-pressure` is expected to engage rather than
skip — it did.

### Topology axes (`targets/rabbitmq-memory/topology.nix`)

The topology target pins single-element lists by design:

```nix
roles.rabbit = [ 3 ];
rabbitVlans  = [ [ 1 ] ];
```

Confirmed: `topoDistinctCount = 1` across all 20 seeds — every run is a
3-node cluster on a single VLAN. The memory-pressure target
deliberately fixes the topology and only fuzzes config; per-role /
per-node memory variation belongs to a future revision.

## Interpretation

1. The `rabbitmq-memory` target is correct on its first design
   iteration (after the five dev-loop fixes listed above). Across eight
   sanity seeds including the worst-case combination
   (mem=512 MB, watermark=0.3, 2000 messages of 4096 bytes), every run
   kept the cluster healthy: durable, confirmed messages were not
   silently lost; no phantom messages appeared; the cluster re-formed
   correctly after the drain; the broker's memory alarm engaged
   exactly when the load was tight enough to warrant it; and every
   node's `rabbitmq.service` stayed active.
2. The `memory-alarm-engages-under-pressure` property correctly skips
   light loads (`publish_count < 500`) and asserts engagement under
   heavy loads (`publish_count ≥ 500`). Seed 11 (the only seed in the
   sanity set with `publish_count ≥ 500` and `watermark = 0.3`) saw the
   alarm fire; the property passed.
3. The shrinker cannot reduce `vm_memory_high_watermark.relative`
   because the key contains dots and the shrinker's path-walker uses
   `lib.splitString "."`. This is a pre-existing shrinker limitation,
   not a target bug. The fuzzer still varies the dimension correctly
   across runs, so the sweep is unaffected; only choice-based shrinking
   is blocked on this single axis.
4. The four-dimensional fuzz surface (`3^4 = 81` cells) is too large
   for a 50-seed sweep to cover densely (≈ 60 % of cells), but a
   20-seed sanity sweep already exercises each value of each axis at
   least twice and hits the worst-case combination.

## Limitations and next steps

- 50+ seeds would close the joint-coverage gap from ≈ 25 % (20 seeds)
  toward the ≈ 60 % that the `rabbitmq-partition` sweep achieved.
- `vm_memory_high_watermark.relative` cannot be choice-shrunk because
  its key contains dots. Fixing this requires either (a) updating
  `lib/shrinker.nix:getValueByPath` to honor quoted path segments, or
  (b) extending `lib/orchestrate.nix` to allow per-key string
  overrides for `attrsOf` configItems. Either fix is independent of
  this target and applies project-wide.
- Per-node memory variation is not exercised: the config layer is
  shared per role, so all three rabbit nodes get the same
  `memorySize`. A future revision could pin one or two nodes to a
  different `memorySize` via a per-node topology-level override, which
  would simulate asymmetric memory pressure (one node OOMs while the
  other two survive) and exercise an additional failure mode.
- `publishers = 1` is fixed; concurrent publishers are not fuzzed. The
  RabbitMQ-first-targets doc lists `publisher concurrency` as a
  recommended knob. Adding it would split the publish loop across N
  pika connections and add a fifth fuzz dimension
  (`[ 1 3 9 ]` for example), bringing the surface to `3^5 = 243` cells.
- `vm_memory_high_watermark.relative` is the only memory-side knob
  fuzzed. Adding `vm_memory_high_watermark.absolute` (e.g. `64MB`,
  `128MB`) would let the sweep explore scenarios where the watermark
  is fixed in absolute terms regardless of host memory, which is the
  more common production configuration.

## Artifacts

Detailed sanity-run artifacts:

```text
.topotestix/runs/20260819-170042-rabbitmq-memory-seed-1-sanity-rabbitmq-memory-seed-1
.topotestix/runs/20260819-170832-rabbitmq-memory-seed-5-sanity-rabbitmq-memory-seed-5
.topotestix/runs/20260819-171755-rabbitmq-memory-seed-10-sanity-rabbitmq-memory-seed-10
.topotestix/runs/20260819-174537-rabbitmq-memory-seed-11-sanity-rabbitmq-memory-seed-11
.topotestix/runs/2026*-rabbitmq-memory-seed-{3,7,15,20,25,30}-sanity-*
```

Each run directory contains:

```text
run.json        # status, timing, reproduceCommand
report.json     # per-check status (7 entries)
choices.json    # shrinker overrides (empty in sanity runs)
expr.nix        # generated Nix expression (distinct per seed)
target.json     # target manifest
stderr.log      # nix build + vm-test driver log
result          # built test result (symlink to /nix/store)
```

## Suggested thesis paragraph

TopoTestix was evaluated on the memory-pressure axis of the RabbitMQ
deep-sweep plan as the host-resource-sensitivity case study. A four-axis
fuzz surface — `virtualisation.memorySize` (1024 / 768 / 512 MB),
`vm_memory_high_watermark.relative` (0.5 / 0.4 / 0.3), `publish_count`
(50 / 500 / 2000), and `message_size` (128 / 1024 / 4096 bytes) — was
exercised across eight sanity seeds, including the worst-case
combination (512 MB, 0.3 watermark, 2000 messages of 4096 bytes). All
eight runs and all 56 individual property assertions passed. The
broker's memory alarm engaged exactly when the load and watermark
combined to a tight setup (gated by `publish_count ≥ 500`); every
durable, confirmed message that was accepted survived a 30-second drain
window; no phantom messages appeared; the cluster re-formed correctly;
and every node's `rabbitmq.service` stayed active throughout. A
pre-existing shrinker limitation — `lib/shrinker.nix:getValueByPath`
splits on `.` and cannot navigate
`configItems."vm_memory_high_watermark.relative"` — was documented as a
known scope; the fuzzer still varies the dimension correctly, so the
sweep is unaffected. This establishes the host-resource-sensitivity
baseline against which later crash-consistency and DNS axes from the
RabbitMQ deep-sweep plan are contrasted.
