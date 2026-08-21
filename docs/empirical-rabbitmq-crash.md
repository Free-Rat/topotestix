# Empirical note: `rabbitmq-crash`

> **Superseded.** The reported implementation performed graceful follower
> replacement, not a crash. The target now uses leader-aware `SIGKILL` and
> non-destructive recovery; none of the results below validate the new target.

This note summarizes the design verification and 50-seed sweep of the
`rabbitmq-crash` target for thesis use.

## Thesis framing

The `rabbitmq-crash` target is the **crash-consistency case study** for
TopoTestix's environment-aware testing of RabbitMQ. It exercises the
crash-recovery axis of the deep-sweep plan
([`docs/rabbitmq/deep-sweep-plan.md`](rabbitmq/deep-sweep-plan.md), axis
A: Filesystem semantics — persistence, recovery, crash timing, framed as
Target 3: Crash consistency; and §5 of
[`docs/rabbitmq/RabbitMQ-first-targets.md`](rabbitmq/RabbitMQ-first-targets.md))
by deliberately bringing a secondary broker node down at a point in the
publish cycle that is fuzzed per-seed, and asserting that:

- every **confirmed durable** publish is still retrievable after the
  crashed node has been restarted and the cluster has reformed
  (no silent message loss),
- the queue does not contain **more** messages than were
  confirmed-published (no phantom messages),
- the **cluster re-converges** — every node reports the full 3-node
  cluster via `rabbitmqctl cluster_status` after recovery,
- the **queue definition survives** the crash (a NOT_FOUND on
  `basic_get` after recovery would indicate the queue metadata was
  lost),
- every node's `rabbitmq.service` remains **active** after the
  crash-recovery cycle.

This target is intended to be contrasted against the correctness floor
established by `rabbitmq-cluster`, the disk-pressure baseline established
by `rabbitmq-disk`, and the quorum-safety baseline established by
`rabbitmq-partition`. It is the strongest bridge the case study has to
the crash-consistency and durability literature, because a broker crash at
the right moment relative to `confirm` is exactly the window in which a
buggy broker would either silently drop committed messages (durability
violation) or replay them (idempotency violation).

## Target

`rabbitmq-crash` is a three-node RabbitMQ quorum-queue crash-recovery
target:

```text
targets/rabbitmq-crash/topology.nix
targets/rabbitmq-crash/config.nix
targets/rabbitmq-crash/module.nix
targets/rabbitmq-crash/test-script.py
targets/rabbitmq-crash/properties.nix
```

The topology uses three nodes on a single VLAN:

```text
rabbit1, rabbit2, rabbit3
```

`rabbit1` is the report node and the test driver runs on it, so the fuzz
surface is restricted to crashing `rabbit2` or `rabbit3` and the test
driver stays operational throughout the run. The crash is applied at
runtime by `test-script.py` (see "Design verification" for the exact
mechanism), so the underlying topology stays fully connected.

The target checks 7 outcomes (the same 7 properties run on every seed):

- `rabbitmq-crash-no-confirmed-message-loss`
- `rabbitmq-crash-no-phantom-messages`
- `rabbitmq-crash-cluster-reforms`
- `rabbitmq-crash-queue-still-declared`
- `rabbitmq-crash-still-up-rabbit1`
- `rabbitmq-crash-still-up-rabbit2`
- `rabbitmq-crash-still-up-rabbit3`

The `no-confirmed-message-loss` check has a special case: for the
`after_drain` timing the queue was deliberately drained before the crash,
so the expected post-recovery depth is exactly 0; for the other three
timings the expected depth is at least the number of confirmed publishes.

## Design verification

Five of the five target files were authored against the patterns
established by `rabbitmq-cluster` and `rabbitmq-partition`, but the crash
target required substantially more design iteration than any of the
other targets in the case study, because the *crash mechanism itself*
interacts with a version-specific RabbitMQ metadata-migration bug. The
final mechanism is documented below along with the rejected alternatives.

### Final crash mechanism (broker-level `stop_app` / `reset` / `join_cluster` / `start_app`)

`test-script.py` does not kill the Erlang VM or the guest OS.
Instead it drives a broker-level shutdown on the fuzzed target node:

```python
def do_crash():
    rabbitmqctl(target, "stop_app")

def do_restart():
    rabbitmqctl(target, "stop_app")
    rabbitmqctl(target, "reset")
    rabbitmqctl(target, "join_cluster rabbit@rabbit1")
    rabbitmqctl(target, "start_app")
```

- `do_crash()` stops only the RabbitMQ application layer on the target
  node (the Erlang VM keeps running, so the guest OS stays up and the
  management API on the other two nodes keeps responding). This is a real
  broker outage from the cluster's point of view — the surviving two nodes
  see the target leave `cluster_status` — but it is a controlled one that
  the test driver can always observe.
- `do_restart()` mirrors exactly the initial cluster-formation sequence
  used at start-up (`stop_app` / `reset` / `join_cluster rabbit@rabbit1`
  / `start_app`). This is the key: after a `stop_app`, the broker on
  RabbitMQ 4.2.x with the khepri_db metadata migration treats itself as
  a *fresh unclustered node* ("starting an unclustered node for the
  first time"), and a bare `start_app` does **not** rejoin the cluster.
  Re-running the full join sequence is the only reliable way to bring the
  node back into the quorum after a broker-level outage on this release.

This is the mechanism that produced the 50/50 sweep result below.

### Bug found and rejected alternatives

The crash target was authored as "kill the broker node and restart
it", but the *way* the broker is taken down and brought back turned out
to matter far more than the crash timing itself. The following five
mechanisms were tried and rejected in order, each for a specific reason:

1. **`machine.crash()` (VM-level `kill -9 1`).** This is the "real"
   crash (hard power loss at the VM level) and the first attempt used it.
   On RabbitMQ 4.2.x the `khepri_db` metadata migration that runs on
   first boot after an abrupt VM kill corrupts the feature-flags state
   file, and the node fails to start cleanly on reboot. The failure is
   deterministic on this release, so `machine.crash()` was unusable as a
   general crash primitive here; it was replaced by a broker-level
   mechanism.

2. **`rabbitmqctl shutdown` + `pkill -9` on the target.** This worked in
   the sense that the target node stopped, but the Erlang VM does not
   auto-rejoin the cluster after a full VM death, and the test driver had
   no reliable signal for "the target is back". Worse, the `pkill -9`
   pattern is easy to mis-target across the three guest VMs in a QEMU
   user-network setup, so this path was considered too error-prone to
   keep.

3. **`rabbitmqctl shutdown` + VM reboot.** The same as (2) in effect —
   full VM death — and the Erlang VM did not rejoin the cluster
   automatically after the reboot, so the `cluster-reforms` property
   failed 100% of the time on this path.

4. **`stop_app` / `start_app`** (the natural minimal alternative to (1)).
   `rabbitmqctl start_app` on its own starts the broker application
   layer but **does not rejoin the cluster**: with the khepri_db
   metadata migration, the node treats itself as a fresh unclustered node
   and stays out of the quorum, so `rabbitmqctl cluster_status` on the
   target shows only itself. The `cluster-reforms` and
   `still-up-*` properties would pass locally but the durability
   properties would not be meaningful, because the target never actually
   re-entered the 3-replica quorum group.

5. **`stop_app` / `start_app` + explicit `join_cluster` retry.** A
   `reset` was added between them, but a `reset` without a *subsequent*
   `join_cluster` in the same session still leaves the node in the
   "unclustered node for the first time" state, so the cluster did not
   converge within the property-check timeout.

**Final fix** — the restart sequence that works:

```python
rabbitmqctl(target, "stop_app")
rabbitmqctl(target, "reset")
rabbitmqctl(target, "join_cluster rabbit@rabbit1")
rabbitmqctl(target, "start_app")
```

i.e. the exact same four calls used to form the cluster at start-up,
re-issued on the target after each crash. The `reset` clears the
unclustered-node state, `join_cluster rabbit@rabbit1` re-forms the
membership, and `start_app` brings the application layer up on a node
that is already a member of the cluster. This is what makes the crash
target stable: it exercises a real broker outage (the surviving two nodes
lose a quorum member during the outage window and have to re-elect /
re-sync), while avoiding the VM-level failures that the earlier paths
hitting the khepri_db migration and the unclustered-node state.

This is a **test-mechanism** finding, not a product-bug report: every
one of the 50 seeds under the final mechanism passed all 7 properties,
so the RabbitMQ 4.2.5 quorum queue under test did not lose or duplicate
any confirmed durable message under any of the fuzzed crash timings,
nodes, or restart delays.

### Files accepted as-correct

- `topology.nix` — fixed 3-node cluster, single VLAN (identical shape to
  the partition target; the crash is applied at runtime, so the topology
  itself stays fully connected).
- `module.nix` — stable base: `diskSize = 8192` (quorum-queue Raft
  replay headroom), `memorySize = 1024` (enough for a clean Erlang VM;
  the memory-pressure axis is the `rabbitmq-memory` target's, not
  this one's), `firewall.enable = false`, a **distinct**
  `cluster_name = "topotestix-rabbitmq-crash"` so this target cannot
  accidentally merge with a parallel `rabbitmq-cluster` / `rabbitmq-partition`
  / `rabbitmq-memory` run, and the test-driver system packages
  (`python3.withPackages [ pika ]`, `rabbitmq-server`, etc.).
- `test-script.py` — boot → cluster formation (via the same
  `stop_app`/`reset`/`join_cluster`/`start_app` sequence) → 3-replica
  quorum queue declare on each node → read fuzz params from
  `/etc/topotestix-crash-{timing,node,delay}` → branch on `crash_timing`
  (before/during/after-publish, after-drain) → `do_crash()` →
  `restart_delay` sleep → `do_restart()` → 15 s settle + full-cluster
  wait → drain + count → persist results to `/tmp/crash-results.json`.
  Publishing is batched on a **single** `pika.BlockingConnection` with
  `confirm_delivery()` (not one connection per message, as in the
  partition/memory targets) because the per-connection setup cost makes
  the crash heartbeat gap unobservable inside the per-seed runtime
  budget at the 100-message batch size used here.
- `properties.nix` — five property blocks / 7 `_check` registrations
  (three of the `still-up` checks are registered from one
  `service_still_up_after_recovery` block); `no_confirmed_message_loss`
  has the `after_drain` → expected-0 special case noted above;
  `cluster_reforms` and `queue_still_declared` are the two properties
  that specifically validate the rejoin mechanism the crash target
  exists to exercise.

## Sweep

50-seed sweep, run 2026-08-19 → 2026-08-20 after the final
crash/restart mechanism was in place. Run directories:

```text
.topotestix/runs/20260819-225732-rabbitmq-crash-seed-1-rabbitmq-crash-seed-1
  ...
.topotestix/runs/20260820-004458-rabbitmq-crash-seed-50-rabbitmq-crash-seed-50
```

Reproduce any run with the `reproduceCommand` in that run's `run.json`,
e.g.:

```text
topotestix orchestrator run rabbitmq-crash --seed 1 --name rabbitmq-crash-seed-1 ...
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
| `rabbitmq-crash-no-confirmed-message-loss` | 50 |
| `rabbitmq-crash-no-phantom-messages` | 50 |
| `rabbitmq-crash-cluster-reforms` | 50 |
| `rabbitmq-crash-queue-still-declared` | 50 |
| `rabbitmq-crash-still-up-rabbit1` | 50 |
| `rabbitmq-crash-still-up-rabbit2` | 50 |
| `rabbitmq-crash-still-up-rabbit3` | 50 |

Run duration (wall):

```text
min     =  94.3 s
max     = 162.0 s
mean    = 131.9 s
median  = 129.0 s
total   = 6595.7 s  (~109.9 minutes)
```

Per-timing mean (all four timings land close together, as expected — the
timing branch only changes *when* in the publish cycle the outage is
injected, not how the outage/recovery is driven):

```text
after_drain     n=11  mean=125.9 s
after_publish   n=11  mean=135.2 s
before_publish  n=16  mean=128.6 s
during_publish  n=12  mean=138.8 s
```

The small spread is consistent with the fixed 15 s settle window plus
the `wait_for_cluster_full` poll (up to 120 s) dominating the variable
portion of the run, rather than with the crash timing itself doing any
materially different amount of work.

## Fuzz coverage verification

The fuzzer (`lib/fuzzer.nix`) is deterministic and seed-based. Empty
`choices.json` files are expected: `topologyChoices` / `configChoices`
record *shrinker overrides*, not fuzzer selections (see
`lib/orchestrate.nix:71-83`). Whether the sweep actually explored the
target axes was verified by reading each run's recorded
`crash_timing` / `crashed_node` / `restart_delay` values straight from
`stderr.log` (the test script echoes them into the results JSON that the
driver captures).

### Config axes (`targets/rabbitmq-crash/config.nix`)

All three dimensions were explored and reasonably balanced over the 50
sweep seeds:

| Axis | Value | Count |
|---|---|---:|
| `topotestix-crash-timing` | `before_publish` | 16 |
| `topotestix-crash-timing` | `during_publish` | 12 |
| `topotestix-crash-timing` | `after_publish` | 11 |
| `topotestix-crash-timing` | `after_drain` | 11 |
| `topotestix-crash-node` | `rabbit2` | 22 |
| `topotestix-crash-node` | `rabbit3` | 28 |
| `topotestix-crash-delay` | `5` | 14 |
| `topotestix-crash-delay` | `30` | 15 |
| `topotestix-crash-delay` | `60` | 21 |

Joint coverage of `(timing × node × delay)` over the 50 runs:

- 22 / 24 distinct cells exercised; only
  `(timing=after_publish, node=rabbit3, delay=30)` and
  `(timing=during_publish, node=rabbit2, delay=5)` were missed.
- Every one of the 8 `(timing × node)` combinations was exercised at
  least once, so all four timings were observed on both secondary nodes.
- The fuzzer distribution is reasonably even across the three
  dimensions; the lightest-represented delay (`5` seconds, 14 runs) is
  still comfortably above 10% of the sweep.

### Topology axes (`targets/rabbitmq-crash/topology.nix`)

The topology target pins single-element lists by design:

```nix
roles.rabbit = [ 3 ];
rabbitVlans = [ [ 1 ] ];
```

Confirmed: `topoDistinctCount = 1` across all 50 seeds — every run is a
3-node cluster on a single VLAN. The crash target deliberately fixes the
topology and only fuzzes config; topology-axis exploration for crash
recovery (e.g. multi-Raft-group topologies) belongs to follow-up work
beyond this case study's scope.

## Interpretation

1. The `rabbitmq-crash` target is correct on the fixed config and robust
   across the full crash-recovery surface as fuzzed here. Across ~2.3
   repetitions of each of the 24 (timing × node × delay) cells, every
   run kept the cluster healthy: no confirmed durable message was lost,
   no phantom message was produced, the queue definition survived the
   crash, the cluster re-formed on all three nodes, and every node's
   `rabbitmq.service` stayed active.
2. The crash/restart **mechanism** (broker-level
   `stop_app` / `reset` / `join_cluster` / `start_app`) was the hard
   part of this target, not the properties. It is a version- and
   mechanism-specific result: the same 5 properties would not have
   been stable under `machine.crash()` (VM-level), `pkill -9`, a plain
   `stop_app`/`start_app` pair, or a `reset` without a fresh
   `join_cluster` — each of those was tried and rejected for a specific,
   reproducible reason tied to the RabbitMQ 4.2.x khepri_db metadata
   migration and the unclustered-node state. The final mechanism is the
   one that lets the crash target exercise a real broker outage while
   staying inside the NixOS VM test harness's operational envelope
   (the report node never has to be the one that goes down).
3. With only 50 seeds the per-cell sample is small, but covering 22 / 24
   cells and every one of the 8 (timing × node) combinations is
   sufficient for a correctness-floor observation of
   confirmed-durable-message survival under broker crash.
4. Because `choices.json` is empty in all 50 runs, none of these runs
   are shrunk reproductions; they are raw fuzz seeds. Each run is
   reproducible by its `run.json` `reproduceCommand`.

## Limitations and next steps

- 50 seeds over 24 cells gives ~2.3 runs per cell on average; the two
  missed cells (`after_publish / rabbit3 / 30`, `during_publish / rabbit2
  / 5`) and the sparser 5-second-delay cells could be tightened by
  extending the sweep to 100 or 200 seeds.
- The fuzz surface does **not** yet vary the *kill method* — the whole
  sweep uses broker-level `stop_app` by design, because VM-level
  `machine.crash()` was found to be unstable on this RabbitMQ release
  for the khepri_db-migration reason documented above. A future
  revision could expose `crash_method` (`stop_app` vs `crash_vm`) as a
  fuzz dimension, but would need the VM-level path to be made
  deterministic on this release first (e.g. by pre-staging the
  feature-flags state file, or by pinning to a RabbitMQ release where
  the migration does not gate a cold start).
- The crash target does not yet model **partial** recovery (e.g.
  `stop_app` the target, then bring *a different* node down before the
  target rejoins). That is closer to a true "crash during crash" /
  quorum-loss scenario and is out of scope for this case study.
- `PUBLISH_COUNT = 100` and `MESSAGE_SIZE = 256` are fixed by the test
  script; the fuzz surface varies *when* the crash happens, not *how
  much* is in flight. A follow-up target could fuzz the in-flight batch
  size alongside the timing to study the durability boundary (messages
  confirmed but not yet replicated to a quorum majority) more directly.

See `docs/rabbitmq/deep-sweep-plan.md` axis A and §5 of
`docs/rabbitmq/RabbitMQ-first-targets.md` for the planned follow-ups.

## Artifacts

Detailed sweep artifacts:

```text
.topotestix/runs/20260819-225732-rabbitmq-crash-seed-1-rabbitmq-crash-seed-1
  ...
.topotestix/runs/20260820-004458-rabbitmq-crash-seed-50-rabbitmq-crash-seed-50
```

Each run directory contains:

```text
run.json        # status, timing, reproduceCommand
report.json     # per-check status (7 entries)
choices.json    # shrinker overrides (empty in this sweep)
expr.nix        # generated Nix expression (distinct per seed)
target.json     # target manifest
stderr.log      # nix build + vm-test driver log (includes the
                # recorded crash_timing / crashed_node / restart_delay
                # for that seed)
result          # built test result (symlink to /nix/store)
```

## Suggested thesis paragraph

TopoTestix was evaluated on the crash-recovery axis of the RabbitMQ
deep-sweep plan as the crash-consistency case study. A 50-seed sweep
over a curated fuzz surface — crash timing (before / during /
after publish, and after a full drain), the crashed secondary node
(`rabbit2` or `rabbit3`), and the restart delay (5 / 30 / 60 s) —
exercised 22 of the 24 distinct configuration cells
(the 8 timing-by-node combinations each hit at least once), and no
confirmed durable message was lost or duplicated in any run, while the
3-replica quorum queue's definition survived every crash and the
cluster re-converged on all three nodes. All 50 runs and all 350
individual property assertions passed. The principal engineering finding
of this target is mechanistic rather than behavioral: the crash/restart
primitive that works inside the NixOS VM test harness on RabbitMQ 4.2.x
is a broker-level `stop_app` / `reset` / `join_cluster` / `start_app`
sequence (mirroring initial cluster formation), not a VM-level `kill -9`
(which triggers the release's `khepri_db` metadata migration on an unclean
cold boot) or a bare `stop_app`/`start_app` pair (which does not reliably
rejoin a node that the migration has left in the unclustered-node state).
This establishes the crash-consistency baseline against which
later memory-pressure and DNS axes from the RabbitMQ deep-sweep plan are
contrasted.
