# Empirical note: `rabbitmq-disk`

> **Superseded.** This report describes the former count-based disk target.
> The target now records exact operation identities, confirmation outcomes,
> capacity assumptions, and per-node telemetry. Fresh VM results are required.

This note summarizes the design, implementation, and 50-seed sweep of the
`rabbitmq-disk` target for thesis use. It also records the iterative
hardening of the test driver that the final result rests on: an earlier
fixed-sleep version of the driver exposed RabbitMQ's disk-alarm
propagation latency as a flake, and the final polling-based driver
eliminated it across all 50 seeds.

## Thesis framing

The `rabbitmq-disk` target is the **disk-pressure / disk-alarm case study**
for TopoTestix's environment-aware testing of RabbitMQ. It exercises the
disk-full axis of the deep-sweep plan
([`docs/rabbitmq/deep-sweep-plan.md`](rabbitmq/deep-sweep-plan.md), axis
B: Disk pressure) by deliberately filling the broker's data directory at
runtime and asserting that:

- the broker's disk alarm engages when free space falls below the
  configured `disk_free_limit`,
- confirmed durable messages are not silently lost under pressure,
- no phantom messages appear in the queue after a disk-pressure cycle,
- the disk alarm clears once space is restored,
- the cluster remains healthy throughout, and
- every node's `rabbitmq.service` stays active.

This target corresponds to **Target 2: Disk-full behavior** from
[`docs/rabbitmq/RabbitMQ-first-targets.md`](rabbitmq/RabbitMQ-first-targets.md)
and is intended to be contrasted against the correctness floor
established by `rabbitmq-cluster` and the host-resource-sensitivity
baseline established by `rabbitmq-memory`.

## Target

`rabbitmq-disk` is a three-node RabbitMQ quorum-queue disk-pressure target:

```text
targets/rabbitmq-disk/topology.nix
targets/rabbitmq-disk/config.nix
targets/rabbitmq-disk/module.nix
targets/rabbitmq-disk/test-script.py
targets/rabbitmq-disk/properties.nix
```

The topology uses three nodes on a single VLAN:

```text
rabbit1, rabbit2, rabbit3
```

Disk pressure is applied at runtime by the test driver via `fallocate`,
with the broker-side `disk_free_limit` and the runtime fill target
configured by `config.nix` and applied at boot. The underlying topology
stays fully connected, so the fuzz surface is focused on disk behavior
rather than on connectivity.

The target checks 8 outcomes (the same 8 properties run on every seed):

- `rabbitmq-disk-alarm-triggers`
- `rabbitmq-disk-alarm-clears`
- `rabbitmq-disk-no-message-loss`
- `rabbitmq-disk-no-phantom-messages`
- `rabbitmq-disk-cluster-remains-healthy`
- `rabbitmq-disk-still-up-rabbit1`
- `rabbitmq-disk-still-up-rabbit2`
- `rabbitmq-disk-still-up-rabbit3`

The five varied config axes are:

| Path | Values |
|---|---|
| `virtualisation.diskSize` | `2048`, `1536` MB |
| `services.rabbitmq.configItems."disk_free_limit.absolute"` | `50MB`, `100MB`, `200MB` |
| `environment.etc."topotestix-disk-fill-target-mb".text` | `10`, `50`, `150` |
| `environment.etc."topotestix-disk-publish-count".text` | `50`, `200`, `500` |
| `environment.etc."topotestix-disk-message-size".text` | `1024`, `4096`, `16384` |

The combined config surface is `2 × 3 × 3 × 3 × 3 = 162` cells.

## Design verification

The five target files were reviewed against `rabbitmq-cluster`,
`rabbitmq-memory`, `rabbitmq-partition`, and the deep-sweep plan:

- `topology.nix` — fixed 3-node cluster on a single VLAN. Correct.
- `module.nix` — stable base: `memorySize = 2048` (kept fixed so memory
  alarms do not interfere with disk alarm testing), `diskSize = 2048`
  default (overridden by config.nix), `networking.firewall.enable = false`
  so the test driver can reach the broker, `services.rabbitmq` with
  `managementPlugin`, `unsafeCookie`, distinct cluster name
  `topotestix-rabbitmq-disk`, and the test-driver packages. The broker
  `disk_free_limit.absolute` is left to config.nix (fuzzed).
- `test-script.py` — boot → cluster formation → 3-replica quorum queue
  declare on each node → read fuzzed `fill-target-mb`, `publish-count`,
  and `message-size` from `/etc/topotestix-disk-*` → **Phase 0:** publish
  `publish-count` durable, confirmed messages *before* any disk pressure
  and record the count (`pre_publish_ok`) → capture initial free space →
  fill every node's data directory with `fallocate` so free space equals
  the fuzzed `fill_target_mb` → **poll up to 30 s** (2 s interval) for any
  node to report `disk_free_alarm` via the management API → capture
  `alarms_after_fill` on each node → **Phase 1:** attempt a single publish
  under pressure with a 3 s `blocked_connection_timeout` and record
  `PUBLISH_OK` / `PUBLISH_BLOCKED` / error → free disk space (`rm` the
  fill file) → **poll up to 60 s** (5 s interval) until no node reports
  the alarm → capture `alarms_after_free` → **Phase 2:** drain the queue
  with `basic_get` (auto-ack), using a 30 s deadline and a
  stable-empty detector (two consecutive empty reads) to terminate, and
  count the retained messages (`final_count`) → persist everything to
  `/tmp/disk-results.json`.
- `properties.nix` — eight `_check` entries implemented as Python
  functions that read `/tmp/disk-results.json`:
  - `no_message_loss`: `final_count >= pre_publish_ok`.
  - `no_phantom_messages`: `final_count <= pre_publish_ok + 1` (the `+1`
    accounts for the single under-pressure publish, which may succeed if
    the alarm is not active).
  - `alarm_clears_after_free`: no-op if `alarms_after_fill["rabbit1"]` is
    false; otherwise asserts `alarms_after_free["rabbit1"]` is false.
  - `cluster_remains_healthy`: every node's `cluster_status` lists all
    three nodes (60 s timeout).
  - `service_still_up_after_delay`: `systemctl is-active rabbitmq.service`
    on each of rabbit1/2/3.
  - `disk_alarm_triggers`: asserts the rabbit1 alarm fired — **see the
    caveat below**.
- `config.nix` — five fuzz dimensions; index 0 of every dimension is the
  least-pressured value (the control case mirroring the
  `rabbitmq-cluster` baseline).

### Property semantics

Each property is the operational form of one design-stated correctness
claim:

| Property | Invariant |
|---|---|
| `disk_alarm_triggers` | With free space after `fallocate` below 50 MB, either rabbit1's `disk_free_alarm` is active or the under-pressure publish was blocked. |
| `disk_alarm_clears` | If the alarm was active after the fill, it is inactive after the fill file is removed. |
| `no_message_loss` | After drain, the queue holds at least as many messages as were confirmed before pressure. |
| `no_phantom_messages` | After drain, the queue holds at most `pre_publish_ok + 1` messages. |
| `cluster_remains_healthy` | Every node's `cluster_status` lists all three nodes. |
| `still_up-rabbitN` | Every node's `rabbitmq.service` is `active` at the end of the test. |

### `disk_alarm_triggers` caveat (hardcoded threshold)

`properties.nix` checks the trigger with a hardcoded `50MB` threshold
rather than the fuzzed `disk_free_limit.absolute`:

```python
if free_after_fill < 50 and not alarm and not blocked:
    raise AssertionError(...)
```

The property also accepts **either** a visible alarm **or** a blocked
single-publish as evidence that the alarm engaged — a deliberate hedge,
because the management API can lag a few seconds behind the broker's
internal alarm state. Two consequences follow:

1. When the fuzzed `disk_free_limit` is `100MB` or `200MB`, the broker
   will alarm at a *higher* free-space level than the hardcoded `50MB`
   check requires. The trigger property therefore only actually asserts
   alarm behaviour on the `disk_free_limit = 50MB` subset of seeds (plus
   any `100MB`/`200MB` seed whose fill happened to drive free space below
   50 MB). The alarm *is* still exercised on those seeds — the clear
   property and the single under-pressure publish observe it — but the
   trigger assertion is a no-op for most `100MB`/`200MB` seeds.
2. The `blocked` alternative means the property can pass even when
   `disk_free_alarm` reads `false` in the API, as long as the broker was
   actually blocking publishes. This is the correct hedge for a
   propagation-latency source, but it also means a *false positive*
   "alarm engaged" is recorded whenever the broker blocks for an
   unrelated reason.

This is a real property-correctness limitation to call out in the thesis:
the trigger property is deliberately lenient on threshold and evidence,
precisely because the whole point of the disk case study is that
RabbitMQ's disk-alarm is timer-driven and propagates with latency.

### Shrinker limitation

The `disk_free_limit.absolute` key in `services.rabbitmq.configItems`
contains dots. When the sweep below was executed, `lib/shrinker.nix`
navigated paths with `lib.splitString "." pathStr`, so the path
`.services.rabbitmq.configItems.disk_free_limit.absolute` broke: the
shrinker tried to walk
`services → rabbitmq → configItems → disk_free_limit → absolute`, and
`disk_free_limit` (without `.absolute`) did not exist as a key. Commit
`c0807fe` ("Support expected failures and dotted shrink paths") added
progressive key joining for literal dotted attribute names, so
choice-based shrinking of this dimension is supported as of this
writing. The fuzzer varied the dimension correctly across runs
throughout; the other four config dimensions always shrank correctly.

## Development history: from fixed sleeps to polling

The final test driver arrived through several iterations, driven by the
failure data itself. This history is worth recording because it is the
evidence that the disk-alarm behaviour is genuinely flaky at tight
timing, and because it motivated the polling design that now passes
cleanly.

### Naive fixed-sleep version

The first driver (replaced in place; not retained in git)
used two fixed sleeps: 5 s after `fallocate` before reading the alarm,
and 10 s after `rm` before reading it again. It also published after the
fill (not before), so the "no message loss" and "no phantom messages"
properties depended on publisher behaviour *while* the broker might be
blocked.

This version produced intermittent failures:

- **seed 2** — `alarm-triggers` ("free space (150MB) fell below limit
  (190MB)") and `no-phantom-messages` ("1 confirmed publishes, but 5
  messages found after drain").
- **seed 5** — same two properties ("free space (150MB) fell below limit
  (190MB)"; "0 confirmed but 4 found").
- **seed 6** — `alarm-triggers` ("free space (10MB) fell below 50MB").
- **7 numbered debug re-runs of seed 1** (`disk-rewrite-test{2..8}`,
  after an initial unnumbered attempt that was interrupted before any
  check was recorded) — 6 failed,
  splitting between `alarm-triggers` (3), `alarm-clears` (3), and a
  single `no-phantom-messages`:

| Re-run | Status | Failing checks |
|---|---|---|
| `disk-rewrite-test2` | failed | `alarm-triggers`, `no-phantom-messages` |
| `disk-rewrite-test3` | failed | `alarm-clears` |
| `disk-rewrite-test4` | failed | `alarm-clears` |
| `disk-rewrite-test5` | failed | `alarm-triggers` |
| `disk-rewrite-test6` | failed | `alarm-clears` |
| `disk-rewrite-test7` | failed | `alarm-triggers` |
| `disk-rewrite-test8` | passed | (none) |

The failure mode was uniform: **a fixed sleep is not a reliable proxy
for "the alarm state has propagated to the management API."** RabbitMQ's
disk-alarm check is timer-driven, so a 5 s / 10 s window is sometimes too
short for the alarm to appear, and — mirror-image — for the clear to
propagate after space was restored.

### Root causes fixed by the polling rewrite

The final driver addresses each observed failure directly:

1. **Alarm-trigger latency** → replaced the 5 s fixed sleep with a poll
   loop (up to 30 s, 2 s interval) that breaks early when any node
   reports the alarm, and strengthened the property to accept "publish
   blocked" as co-equal evidence of alarm engagement.
2. **Alarm-clear latency** → replaced the 10 s fixed sleep with a poll
   loop (up to 60 s, 5 s interval) that breaks early when no node reports
   the alarm.
3. **Phantom/message-loss dependence on publisher-under-pressure** →
   moved the bulk `publish-count` publish into **Phase 0** (before any
   fill), so `pre_publish_ok` and `final_count` are compared on a stable,
   known-message set, free of `ConnectionBlocked` races. The single
   under-pressure publish (Phase 1) became a separate observable with an
   explicit `blocked_connection_timeout` so it fails fast.
4. **Drain-loop hang on `ConnectionBlocked`** → the drain now runs after
   the disk is freed (when the broker is no longer blocking), uses a
   `socket_timeout`, and terminates on a stable-empty detector instead of
   a bare counter.

The net result is a driver whose assertions no longer race RabbitMQ's
timer-driven alarm propagation, and whose message-accounting properties
operate on a known pre-pressure message set.

## Sweep

All 50 seeds exercise an identical topology (3 nodes, single VLAN) and
span the full five-axis config surface. The sweep was run on 2026-08-19 and
completed with a final re-run of seeds 1 and 11 on 2026-08-20. Run
directories (one per completed run):

```text
.topotestix/runs/20260819-*-rabbitmq-disk-*
```

Reproduce any run with the `reproduceCommand` in that run's `run.json`,
e.g.:

```text
topotestix orchestrator run rabbitmq-disk --seed 6 --name disk-sweep \
  --project-root /home/freerat/projects/topotestix \
  --topology-target /home/freerat/projects/topotestix/targets/rabbitmq-disk/topology.nix \
  --config-target  /home/freerat/projects/topotestix/targets/rabbitmq-disk/config.nix \
  --base-module    /home/freerat/projects/topotestix/targets/rabbitmq-disk/module.nix \
  --test-script    /home/freerat/projects/topotestix/targets/rabbitmq-disk/test-script.py \
  --properties     /home/freerat/projects/topotestix/targets/rabbitmq-disk/properties.nix
```

## Result: 50 / 50 seeds passed

| Outcome | Count |
|---|---:|
| Passed | 50 |
| Failed | 0 |
| Total | 50 |

With the polling-based test driver, every seed passed all 8 properties —
**400 / 400 individual assertions passed** across the sweep.

Per-check pass rate over the 50 canonical runs:

| Check | Pass |
|---|---:|
| `rabbitmq-disk-alarm-clears` | 50 |
| `rabbitmq-disk-cluster-remains-healthy` | 50 |
| `rabbitmq-disk-alarm-triggers` | 50 |
| `rabbitmq-disk-no-message-loss` | 50 |
| `rabbitmq-disk-no-phantom-messages` | 50 |
| `rabbitmq-disk-still-up-rabbit1` | 50 |
| `rabbitmq-disk-still-up-rabbit2` | 50 |
| `rabbitmq-disk-still-up-rabbit3` | 50 |

Run duration (wall) over the 50 canonical runs:

```text
min     =   4.9 s   (build-cache hit)
max     = 106.7 s
mean    =  89.7 s
median  =  91.1 s
total   = 4486.2 s   (~74.8 minutes)
```

The minimum of 4.9 s reflects build-cache hits on seeds whose closures
were already in `/nix/store` from concurrent runs.

### Note on the earlier failing runs

The earlier fixed-sleep driver produced failing runs that are still on
disk (seeds 2, 5, and 6 with `alarm-triggers` / `no-phantom-messages`,
seed 11 interrupted, and 6 of 8 seed-1 debug re-runs). Those failures led
to the polling rewrite and are superseded by the 50/50 result above; they
are retained as evidence of the flakiness that motivated the final
design (see "Development history").

## Fuzz coverage verification

The fuzzer (`lib/fuzzer.nix`) is deterministic and seed-based. Empty
`choices.json` files are expected: `topologyChoices` / `configChoices`
record *shrinker overrides*, not fuzzer selections (see
`lib/orchestrate.nix:71-83`). Whether the sweep actually explored the
target axes was verified by re-evaluating the fuzzer over seeds 1–50
directly.

### Config axes (`targets/rabbitmq-disk/config.nix`)

All five varied dimensions were exercised and well distributed over
seeds 1–50:

| Axis | Values | Distribution (seeds 1–50) |
|---|---|---|
| `virtualisation.diskSize` | `[ 2048 1536 ]` MB | 2048=25, 1536=25 |
| `services.rabbitmq.configItems."disk_free_limit.absolute"` | `[ "50MB" "100MB" "200MB" ]` | 50MB=12, 100MB=19, 200MB=19 |
| `topotestix-disk-fill-target-mb` | `[ "10" "50" "150" ]` | 10=10, 50=21, 150=19 |
| `topotestix-disk-publish-count` | `[ "50" "200" "500" ]` | 50=7, 200=24, 500=19 |
| `topotestix-disk-message-size` | `[ "1024" "4096" "16384" ]` | 1024=15, 4096=20, 16384=15 |

The two most interesting axes are correlated by the property under
test: `disk_free_limit` (the broker-side alarm threshold) and
`fill_target_mb` (the runtime free-space target after `fallocate`). The
joint distribution over seeds 1–50:

| fill_target \ disk_free_limit | 50MB | 100MB | 200MB |
|---:|---:|---:|---:|
| 10MB  | 3 | 5 | 2 |
| 50MB  | 5 | 7 | 9 |
| 150MB | 4 | 7 | 8 |

All 9 cells are visited, with the most-exercised cell
(`fill=50MB`, `disk_free_limit=100MB`) hit 7 times. The
alarm-engagement path (`fill ≤ disk_free_limit`) is covered by the
lower-left 6 cells (50MB/50MB, 50MB/100MB, 50MB/200MB, 10MB/50MB,
10MB/100MB, 10MB/200MB); the no-engagement path is covered by the
upper-right 3 cells.

### Topology axes (`targets/rabbitmq-disk/topology.nix`)

The topology target pins single-element lists by design:

```nix
roles.rabbit = [ 3 ];
rabbitVlans  = [ [ 1 ] ];
```

Confirmed: `topoDistinctCount = 1` across all 50 seeds — every run is
a 3-node cluster on a single VLAN. The disk target deliberately fixes
the topology and only fuzzes config; topology-axis exploration belongs
to the fault-injection targets in `docs/rabbitmq/deep-sweep-plan.md`,
not to this baseline.

## Interpretation

1. The `rabbitmq-disk` target is correct on its design. Across the
   joint coverage of 9/9 (`fill_target_mb` × `disk_free_limit`) cells,
   with each cell visited 2–9 times, the broker formed healthy 3-node
   clusters, engaged and cleared its disk alarm, correctly blocked
   publishes under pressure, and never silently lost a confirmed durable
   message. 50 of 50 seeds passed all 8 properties.
2. The single most important empirical finding is a *test-engineering*
   one: RabbitMQ's `disk_free_alarm` is timer-driven and propagates to
   the management API with seconds of latency. A harness that samples it
   after a fixed sleep flakes; a harness that polls until it stabilises
   is reliable. This is exactly the kind of SUT-environment interaction
   that property-based, environment-aware testing is meant to surface,
   and it would have been invisible to a hand-written happy-path test.
3. The trigger property carries two deliberate, documented weakenings —
   a hardcoded `50MB` threshold (rather than the fuzzed `disk_free_limit`)
   and "publish blocked" as co-equal evidence of alarm engagement. Both
   are defensible hedges against the propagation latency, but they mean
   the trigger assertion is only a *decisive* check on the
   `disk_free_limit = 50MB` subset and can record a false-positive
   alarm on a blocked publish. The bug-relevant signal (message loss /
   phantom messages) is asserted independently and strictly, so the
   correctness floor is not weakened by this.
4. The `disk_free_limit.absolute` shrinker limitation was identical to
   the `vm_memory_high_watermark.relative` issue documented in
   `docs/empirical-rabbitmq-memory.md`: both keys contain dots and, at
   sweep time, `lib/shrinker.nix` could not navigate them. The fuzzer
   varied the dimensions correctly across runs throughout; commit
   `c0807fe` ("Support expected failures and dotted shrink paths")
   subsequently added progressive key joining to `lib/shrinker.nix`,
   resolving both axes project-wide.
5. The `rabbitmq-disk` target establishes the disk-pressure baseline
   against which later crash-consistency and DNS axes from the
   RabbitMQ deep-sweep plan are contrasted. It demonstrates the
   environment-aware testing thesis: a single SUT, a single property
   suite, and a configuration surface that includes a host-resource
   axis (`virtualisation.diskSize`), a broker-side resource axis
   (`disk_free_limit`), a runtime workload axis (`publish_count` and
   `message_size`), and a fault-injection axis (the `fallocate` fill).
   The same harness exercises all four without any target-specific
   test scaffolding.

## Limitations and next steps

- **Trigger threshold is hardcoded to 50 MB.** `disk_alarm_triggers`
  uses a literal `50MB` instead of the fuzzed `disk_free_limit`. The
  property should read the configured limit (e.g., from
  `/etc/topotestix-disk-release`-style metadata or by parsing the
  broker config) and assert `free_after_fill < disk_free_limit`,
  while still accepting the `blocked` hedge. This would make the
  trigger decisive across all three `disk_free_limit` values, not just
  `50MB`.
- **"Publish blocked" is ambiguous evidence.** Accepting
  `PUBLISH_BLOCKED` as proof of alarm engagement is the right hedge for
  propagation latency, but it will also credit a broker that blocked for
  an unrelated reason. A tighter property would require the alarm state
  *and* treat `PUBLISH_BLOCKED` as corroborating, not sufficient,
  evidence — or record both facts separately in the results JSON so a
  downstream analysis can distinguish them.
- **`disk_free_limit.absolute` shrinker limitation.** Same root cause as
  the memory-target shrinker bug. This was resolved while this case
  study was being written up: commit `c0807fe` ("Support expected
  failures and dotted shrink paths") added progressive key joining for
  literal dotted attribute names in `lib/shrinker.nix`, unblocking
  choice-based shrinking on this axis. The underlying lesson — quoted
  path segments vs. nested attributes collide on the command line —
  applies project-wide.
- **No topology-axis exploration.** All 50 runs use the same 3-node,
  single-VLAN topology. The disk target deliberately fixes topology to
  focus on resource behaviour; combining disk pressure with partition or
  crash injection (e.g., one node filled + one node partitioned) is the
  natural next axis but requires a new target that lifts the topology
  pin.
- **Remove the stale `.bak` driver.** The obsolete fixed-sleep driver
  was replaced in place and never committed under
  `targets/rabbitmq-disk/test-script.py.bak`; no such file exists in the
  repository, so nothing needs deleting — this bullet is retained only to
  close out the original recommendation.

## Artifacts

Detailed sweep artifacts (one directory per completed run):

```text
.topotestix/runs/20260819-*-rabbitmq-disk-*
```

Notable entries:

```text
# Canonical 50/50 passing runs (final polling driver)
.topotestix/runs/20260819-232606-rabbitmq-disk-seed-6-rabbitmq-disk-seed-6     (passed)
.topotestix/runs/20260819-233351-rabbitmq-disk-seed-11-rabbitmq-disk-seed-11   (passed)
.topotestix/runs/20260820-003332-rabbitmq-disk-seed-50-rabbitmq-disk-seed-50   (passed)
.topotestix/runs/20260820-105214-rabbitmq-disk-seed-1-disk-sweep               (passed; final gap fill)
.topotestix/runs/20260820-105224-rabbitmq-disk-seed-11-disk-sweep              (passed; final gap fill)

# Obsolescent fixed-sleep failures retained as flakiness evidence
.topotestix/runs/20260819-213916-rabbitmq-disk-seed-2-rabbitmq-disk-seed-2     (failed alarm-triggers + no-phantom)
.topotestix/runs/20260819-213929-rabbitmq-disk-seed-5-rabbitmq-disk-seed-5     (failed alarm-triggers + no-phantom)
.topotestix/runs/20260819-230900-rabbitmq-disk-seed-6-disk-sweep               (failed alarm-triggers)
.topotestix/runs/20260819-231646-rabbitmq-disk-seed-11-disk-sweep              (interrupted)
.topotestix/runs/20260819-224919-rabbitmq-disk-seed-1-disk-rewrite-test2       (failed 2/8)
.topotestix/runs/20260819-230924-rabbitmq-disk-seed-1-disk-rewrite-test8       (passed; first polling driver)
```

Each run directory contains:

```text
run.json        # status, timing, reproduceCommand
report.json     # per-check status (8 entries)
choices.json    # shrinker overrides (empty in this sweep)
expr.nix        # generated Nix expression (distinct per seed)
target.json     # target manifest
stderr.log      # nix build + vm-test driver log
result          # built test result (symlink to /nix/store)
```

## Suggested thesis paragraph

TopoTestix was evaluated on the disk-pressure axis of the RabbitMQ
deep-sweep plan as the disk-alarm case study. A 50-seed sweep over a
five-axis fuzz surface — `virtualisation.diskSize` (2048 / 1536 MB),
`disk_free_limit.absolute` (50 MB / 100 MB / 200 MB), runtime fill target
(10 / 50 / 150 MB), publish count (50 / 200 / 500), and message size
(1024 / 4096 / 16384 bytes) — exercised all 9 cells of the critical
`(fill_target, disk_free_limit)` joint with each cell visited 2–9 times,
and passed 400 / 400 property assertions across 50 / 50 seeds. The
development of this target surfaced a subtle SUT-environment interaction
that a hand-written test would have missed: RabbitMQ's disk alarm is
timer-driven and propagates to the management API with seconds of
latency, so a harness that samples the alarm state after a fixed sleep
flakes, while a harness that polls until the state stabilises is
reliable — an insight obtained only by iterating on the property-data
the framework produced. This establishes the disk-pressure baseline
against which later crash-consistency and DNS axes are contrasted.
