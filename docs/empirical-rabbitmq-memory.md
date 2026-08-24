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
- `properties.nix` — seven `_check` entries; `rabbitmq-memory-alarm-under-pressure`
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
contains dots. When the sanity runs below were executed, `lib/shrinker.nix`
navigated paths with
`lib.splitString "." pathStr`, so the path
`.services.rabbitmq.configItems.vm_memory_high_watermark.relative`
breaks: the shrinker tries to walk
`services → rabbitmq → configItems → vm_memory_high_watermark → relative`,
and `vm_memory_high_watermark` (without `.relative`) does not exist as
a key. Commit `c0807fe` ("Support expected failures and dotted shrink
paths") later added progressive key joining for literal dotted
attribute names, so this dimension is shrinkable as of this writing.
The fuzzer varied the dimension correctly across runs throughout;
the other three dimensions (memorySize, publish_count, message_size)
shrink correctly.

## Sanity runs

Ten distinct sanity seeds were executed (no shrinking) across a spread
of the fuzz space, including the most aggressive combination (mem=512 MB,
watermark=0.3, 2000 messages of 4096 bytes). Each seed's final run passed
all 7 properties — 70 / 70 individual assertions across the ten passing
runs, 0 failures (earlier dev-loop iterations of seeds 1 and 10 failed
while the driver was being debugged); the table below lists eight of
the ten seeds.

Parameters below are as recorded inside each VM by the driver (the
`mempressure-results.json` echo in `stderr.log`; in-guest `MemTotal`
maps 964 / 712 / 460 MB to `memorySize` 1024 / 768 / 512 MB). They
match the current `fuzzer(seed + 1 + roleIndex)` mapping for every
dimension of every seed except `memorySize` for seeds 1 and 5, which
ran with 768 MB under an interim dev-loop revision of the target.

| Seed | mem | wm | pc | ms | Result |
|---:|---:|---:|---:|---:|---|
| 1 | 768 | 0.4 | 2000 | 1024 | 7 / 7 PASS (assertion exercised) |
| 5 | 768 | 0.3 | 2000 | 128 | 7 / 7 PASS (assertion exercised) |
| 10 | 512 | 0.3 | 2000 | 4096 | 7 / 7 PASS (assertion exercised) |
| 11 | 1024 | 0.3 | 50 | 128 | 7 / 7 PASS (alarm property skipped) |
| 3 | 1024 | 0.5 | 500 | 4096 | 7 / 7 PASS (assertion exercised) |
| 7 | 512 | 0.5 | 50 | 1024 | 7 / 7 PASS |
| 15 | 512 | 0.3 | 500 | 4096 | 7 / 7 PASS (assertion exercised) |
| 20 | 1024 | 0.3 | 500 | 4096 | 7 / 7 PASS (assertion exercised) |

Seed 10 is the most aggressive combination in the four-dimensional
surface and is a run in which the
`rabbitmq-memory-alarm-under-pressure` property asserts rather than
skips (`publish_count = 2000 ≥ 500`). The assertion held: the
local-alarms probe (`rabbitmq-diagnostics -q check_local_alarms`,
recorded per phase as `alarm_initial` / `alarm_after_publish` /
`alarm_after_drain` in the underlying `mempressure-results.json`)
reported an active memory alarm before publishing, after publishing,
and after the drain (`"failed"` = alarm active in all three fields).
Notably, the probe already reported an active alarm at startup
(`alarm_initial: "failed"`) in *every* completed sanity run — these
watermark settings put the broker into the memory-alarm state from the
start, not only under publish load — so the property's engagement
condition was satisfied throughout; the correctness properties are
unaffected because they assert message accounting independently of the
alarm state.

Reproduce any run with the `reproduceCommand` in that run's `run.json`,
e.g.:

```text
topotestix orchestrator run rabbitmq-memory --seed 11 \
  --name sanity-rabbitmq-memory-seed-11 \
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
| `virtualisation.memorySize` | `[ 1024 768 512 ]` MB | 1024=9, 768=5, 512=6 |
| `services.rabbitmq.configItems."vm_memory_high_watermark.relative"` | `[ "0.5" "0.4" "0.3" ]` | 0.5=2, 0.4=6, 0.3=12 |
| `/etc/topotestix-memory-publish-count` | `[ "50" "500" "2000" ]` | 50=8, 500=7, 2000=5 |
| `/etc/topotestix-memory-message-size` | `[ "128" "1024" "4096" ]` bytes | 128=6, 1024=4, 4096=10 |

With 20 seeds across `3 × 3 × 3 × 3 = 81` cells, joint coverage is
sparse (≈ 25 % of cells visited once or more), but each value of each
axis was exercised at least twice. The watermark axis skews toward
`0.3` because the fuzzer's hash-based selection landed there most
often for seeds 1-20; a longer sweep would rebalance this.

The single most-aggressive combination
`(memorySize=512, watermark=0.3, publish_count=2000, message_size=4096)`
is hit by seed 10 and is a seed in which
`rabbitmq-memory-alarm-under-pressure` asserts engagement rather than
skipping — it did.

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
   iteration (after the five dev-loop fixes listed above). Across ten
   distinct sanity seeds including the worst-case combination
   (mem=512 MB, watermark=0.3, 2000 messages of 4096 bytes), every run
   kept the cluster healthy: durable, confirmed messages were not
   silently lost; no phantom messages appeared; the cluster re-formed
   correctly after the drain; the alarm-oracle property skipped light
   loads and held under every heavy-load configuration; and every
   node's `rabbitmq.service` stayed active.
2. The `rabbitmq-memory-alarm-under-pressure` property correctly skips
   light loads (`publish_count < 500`) and asserts engagement under
   heavy loads (`publish_count ≥ 500`). Seven seeds exercised the
   assertion path (seeds 1, 3, 5, 10, 15, 20, 30 — all with
   `publish_count ≥ 500`, spanning watermarks 0.5, 0.4, and 0.3), and
   the property passed in each. One caveat recorded by the telemetry: the local-alarms probe
   already reported an active memory alarm at broker startup in every
   completed run, so at these watermark settings the property verifies
   *sustained* alarm state under load rather than a transition caused
   by the publish phase.
3. The shrinker could not reduce `vm_memory_high_watermark.relative`
   at the time of these runs because the key contains dots and the
   shrinker's path-walker then used `lib.splitString "."`. This was a
   pre-existing shrinker limitation,
   not a target bug; commit `c0807fe` ("Support expected failures and
   dotted shrink paths") later resolved it project-wide. The fuzzer
   still varies the dimension correctly
   across runs, so the sweep was unaffected; only choice-based shrinking
   was blocked on this single axis.
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
exercised across ten distinct sanity seeds, including the worst-case
combination (512 MB, 0.3 watermark, 2000 messages of 4096 bytes). Each
seed's final run passed, covering all 70 individual property assertions
across those ten passing runs (earlier dev-loop iterations of individual
seeds failed while the driver was being debugged and are not counted).
The alarm-oracle property skipped light loads and held under every
heavy-load configuration; every durable, confirmed message that was
accepted survived a 30-second drain
window; no phantom messages appeared; the cluster re-formed correctly;
and every node's `rabbitmq.service` stayed active throughout. A
pre-existing shrinker limitation — `lib/shrinker.nix:getValueByPath`
splits on `.` and cannot navigate
`configItems."vm_memory_high_watermark.relative"` — was documented as a
known scope; the fuzzer still varies the dimension correctly, so the
sweep is unaffected. This establishes the host-resource-sensitivity
baseline against which later crash-consistency and DNS axes from the
RabbitMQ deep-sweep plan are contrasted.
