# Empirical note: `etcd-cluster`

This note summarizes the etcd empirical case study for thesis use.

## Thesis framing

The etcd experiments should **not** be described as finding etcd implementation bugs.

Use this framing instead:

> TopoTestix found production-relevant configuration/workload incompatibilities in a real Raft-based key-value store. In the stronger v2 experiment, etcd starts and passes basic distributed-system checks, but a write-burst workload fails when the configured backend quota is too small.

## Target

`etcd-cluster` is a three-node etcd/Raft target:

```text
targets/etcd-cluster/topology.nix
targets/etcd-cluster/config.nix
targets/etcd-cluster/module.nix
targets/etcd-cluster/test-script.py
targets/etcd-cluster/properties.nix
```

The topology uses three nodes:

```text
etcd1, etcd2, etcd3
```

The target checks 12 outcomes in v2:

- cluster health from all three nodes,
- cross-node key/value roundtrips,
- exactly one Raft leader,
- lease/TTL expiry,
- delayed service/cluster health from all three nodes,
- quota write burst.

## v1 result: startup-only timing constraint

The first 50-seed sweep found a real etcd configuration constraint:

```text
heartbeat-interval = 250
election-timeout   = 1000
```

etcd rejects this because election timeout must be at least five times heartbeat interval:

```text
failed to verify flags: --election-timeout[1000ms] should be at least as 5 times as --heartbeat-interval[250ms]
```

Aggregate:

| Outcome | Count |
|---|---:|
| Passed | 39 |
| Failed | 11 |
| Total | 50 |

This is useful as configuration-validation evidence, but it is weaker than the later v2 result because the failures occur before the property suite runs (`0/0` property reports).

## v2 result: quota/workload incompatibility

The v2 target removes the invalid timing combination and adds a quota write-burst property.

v2 fuzzed quota values:

```text
QUOTA_BACKEND_BYTES = 2097152   # 2 MiB
QUOTA_BACKEND_BYTES = 8388608   # 8 MiB
QUOTA_BACKEND_BYTES = 67108864  # 64 MiB
```

50-seed v2 sweep:

| Outcome | Count |
|---|---:|
| Passed | 37 |
| Failed | 13 |
| Total | 50 |

Failed seeds:

```text
3, 6, 12, 13, 14, 28, 33, 34, 38, 40, 41, 42, 43
```

Failure class:

```text
quota-backend-too-small-for-write-burst: 13
```

Quota correlation:

| quota-backend-bytes | Passed | Failed |
|---:|---:|---:|
| 2097152 | 0 | 13 |
| 8388608 | 20 | 0 |
| 67108864 | 17 | 0 |

Representative error:

```text
etcdserver: mvcc: database space exceeded
```

## Shrinking

Two representative v2 failures were shrunk:

```text
seed 3
seed 40
```

Both shrank to the same minimal choices.

Resolved minimal configuration:

```text
roles.etcd = 3
etcdVlans = [ 1 ]
virtualisation.memorySize = 1024
virtualisation.diskSize = 2048
ETCD_HEARTBEAT_INTERVAL = 100
ETCD_ELECTION_TIMEOUT = 1250
ETCD_SNAPSHOT_COUNT = 10000
ETCD_QUOTA_BACKEND_BYTES = 2097152
```

Both minimized runs preserve the intended property-level failure:

```text
passed=11
failed=1
total=12
failed check: etcd-quota-write-burst-etcd1
failure message contains: etcdserver: mvcc: database space exceeded
```

Unlike the Kafka shrinking case, the generic shrinker worked cleanly for etcd v2: the minimized result is still a post-start property failure, not a Nix/build/startup failure.

## Artifacts

Detailed experiment files:

```text
experiments/etcd-cluster/etcd-cluster-findings.md
experiments/etcd-cluster/etcd-cluster-notes.md
experiments/etcd-cluster/etcd-cluster-v2-shrinking.md
experiments/etcd-cluster/etcd-cluster-v2-sweep-1-50-20260616.md
experiments/etcd-cluster/etcd-cluster-v2-sweep-1-50-20260616-summary.json
experiments/etcd-cluster/etcd-cluster-v2-sweep-1-50-20260616-summary.txt
experiments/etcd-cluster/etcd-cluster-v2-shrink-seed-3.log
experiments/etcd-cluster/etcd-cluster-v2-shrink-seed-40.log
```

Representative minimized run directories:

```text
.topotestix/runs/20260616-142216-etcd-cluster-seed-3-etcd-cluster-shrink-3
.topotestix/runs/20260616-143326-etcd-cluster-seed-40-etcd-cluster-shrink-40
```

## Suggested thesis paragraph

TopoTestix was also evaluated on a three-node etcd cluster. After an initial sweep exposed a startup-only timing-configuration constraint, the target was refined to avoid invalid timing combinations and to include a quota-sensitive write-burst workload. In the resulting 50-seed sweep, 37 configurations passed and 13 failed. All failures occurred when the backend quota was 2 MiB: etcd started, elected a leader, passed health checks, supported cross-node key/value operations, honored TTL expiry, and remained healthy after a delay, but the final write-burst property failed with `etcdserver: mvcc: database space exceeded`. Shrinking two representative failures produced the same minimal configuration, isolating the small backend quota as the relevant cause. This result demonstrates that TopoTestix can find realistic workload/configuration incompatibilities in a real Raft-based distributed system.
