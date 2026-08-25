# 6 Evaluation

This chapter presents the empirical evaluation of TopoTestix on three real-world distributed systems: a three-node Apache Kafka cluster, a three-node etcd cluster, and a three-broker RabbitMQ cluster. The Kafka and etcd targets are evaluated as uniform 50-seed sweeps; the RabbitMQ targets are evaluated on designed counterexample cells. All targets are deployed as NixOS test drivers and exposed to the property-based fuzzing pipeline described in Chapter 5. The chapter is deliberately self-contained: for every reported result it states the target, the fuzzed configuration space, the property suite, the sweep outcome, the failure class, and (where available) a minimized reproduction. PostgreSQL is not part of this evaluation and is discussed separately in the related-work chapter.

The evaluation is guided by three research questions, all of which are answered in the summary at the end of this chapter:

> **RQ1.** Can TopoTestix automatically surface configuration-dependent property violations in real distributed systems, given only declarative system-under-test definitions and a property suite?
>
> **RQ2.** Are the surfaced violations of practical relevance, i.e. do they correspond to failure modes that would not be caught by ordinary startup or smoke tests?
>
> **RQ3.** Can TopoTestix localize the surfaced violations by shrinking the failing configuration to a small, reproducible repro, suitable for inclusion in a regression test or bug report?

The chapter is organized as follows. Section 6.1 describes the common evaluation setup. Section 6.2 presents the Kafka case study. Section 6.3 presents the etcd case study, including a first-iteration sweep, a refined second-iteration sweep, and shrinking results. Section 6.4 presents the RabbitMQ case study: a capacity/confirmation SLO with a falsifiability-boundary discussion, a correlated-failure contract, and an abrupt-crash contract, each on designed positive/negative cells. Section 6.5 discusses the cross-cutting observations that emerged from all three studies, including framework fixes motivated by the evaluation and known limitations of the generic shrinker. Section 6.6 lists the threats to validity. Section 6.7 summarizes the answers to the three research questions.

## 6.1 Evaluation Setup

Both case studies follow the same evaluation protocol. For each target, TopoTestix is invoked with a deterministic random seed and a fixed seed range (1..50). Each seed instantiates a complete NixOS test derivation, builds it, starts the virtual cluster, runs the full property suite, and persists the structured per-run report under `.topotestix/runs/`. The runs are grouped by the orchestrator's sweep command and aggregated into a CSV/JSON summary.

The two sweep targets are deliberately different in character. Kafka is a partitioned log/stream system with broker-side configuration that strongly affects data-plane behaviour, and the case study focuses on size-limit interactions under a large-payload workload. etcd is a Raft-based key-value store with a small cluster size and a quota-bounded backend, and the case study focuses on the interaction between a write-burst workload and the configured backend quota. The RabbitMQ targets (Section 6.4) add a message-broker perspective: capacity/confirmation under disk pressure, correlated failure domains, and abrupt broker crashes.

For every run the property suite returns one of two outcomes:

- **pass** — the run completed and all 11 (Kafka) or 12 (etcd) property checks were reached and succeeded, or all property checks that were reached succeeded and the run completed.
- **fail** — at least one property check that was reached failed, and the structured report records the failure class and a representative error message extracted from the cluster log.

In the Kafka sweep, the same ten baseline properties are present in every run, and the eleventh (large-message) property is the only one that can fail. In the etcd sweep, the final property is the quota write-burst; it is intentionally ordered last so that all basic health, leader, KV, and TTL checks must run before it. A failure in any property marks the run as failed; the failing check is recorded with a short class label so that the sweep can be summarized by class.

The fuzzable configuration dimensions for both targets are summarized in Table 6.1. The detailed per-dimension value sets are listed in the case-study sections.

**Table 6.1** — Fuzzable configuration dimensions per target.

| Target | Topology | Fuzzable options | Total combinations | Properties (per-run checks) |
|---|---|---:|---:|---:|
| `kafka-cluster` | 3 brokers | 16 | 746,496 | 11 |
| `etcd-cluster` (v2) | 3 nodes, 1 vlan | 6 | 96 | 12 |
| `rabbitmq` (disk / failure-domain / crash) | 3 brokers | 8 / 3 / 4 | 864 / 4 / 24 | 5 / 2 / 3 |

The two targets share the same sweep size (50 seeds) and the same per-seed protocol. This makes the per-seed pass/fail counts directly comparable and prevents any one target from being favoured by sample size. Detailed per-seed reproduction commands are given in the case-study sections; the aggregated run directories are stored under `.topotestix/runs/` and listed in the per-target sweep summaries in `experiments/`.

## 6.2 Case Study: Apache Kafka

### 6.2.1 Target Setup

The Kafka target is a three-broker cluster that is built and started by a NixOS test driver. The target consists of:

- a topology description `targets/kafka-cluster/topology.nix` declaring three nodes `kafka1`, `kafka2`, `kafka3` on a single private network;
- a NixOS configuration module `targets/kafka-cluster/config.nix` that parameterizes the Apache Kafka service via the standard NixOS `services.apache-kafka` options;
- a property suite `targets/kafka-cluster/properties.nix` with five high-level properties, expanded to 11 per-run checks;
- a test script `targets/kafka-cluster/test-script.py` that composes the property suite with the standard TopoTestix runner.

Each broker is configured with its own advertised listener `kafka<i>:9092`, and the test driver only uses port `9092` for control-plane and data-plane interactions.

### 6.2.2 Configuration Space

The original Kafka target had only four fuzzable options and one property, and only a small subset of failure modes was reachable. The target was therefore expanded before the 50-seed sweep reported in this chapter. The fuzzed configuration space is:

- `virtualisation.memorySize` — VM RAM in MiB (2048 / 3072 / 4096).
- `virtualisation.diskSize` — VM disk in MiB (2048 / 4096 / 8192).
- `services.apache-kafka.jvmOptions` — JVM heap family (`-Xms256m/-Xmx512m`, `-Xms512m/-Xmx1024m`, `-Xms1024m/-Xmx1536m`).
- `offsets.topic.replication.factor` — 1 / 3.
- `transaction.state.log.replication.factor` — 1 / 3.
- `transaction.state.log.min.isr` — 1 / 2.
- `min.insync.replicas` — 1 / 2.
- `default.replication.factor` — 1 / 3.
- `unclean.leader.election.enable` — `true` / `false`.
- `auto.create.topics.enable` — `true` / `false`.
- `log.retention.hours` — 1 / 24 / 168.
- `log.segment.bytes` — 1 MiB / 16 MiB.
- `message.max.bytes` — 1 MiB / 2 MiB / 4 MiB.
- `replica.fetch.max.bytes` — 1 MiB / 2 MiB / 4 MiB.
- `num.network.threads` — 2 / 3.
- `num.io.threads` — 4 / 6.

The product of the per-dimension value counts is 746,496 distinct configurations. Of these, only 50 are sampled in the sweep, which is sufficient to expose both large failure classes multiple times (Section 6.2.4). The heap-size and memory-size ranges were chosen to keep startup failures rare while still exercising realistic small-footprint configurations; the very low values (e.g. 64 MiB) that produced `OutOfMemoryError` during target development were removed because they only yielded startup failures, which are less informative than post-start workload failures (Section 6.5.1).

### 6.2.3 Properties

The property suite consists of five high-level properties, each expanded to one or more per-run checks:

1. **Topic visibility from all brokers** — a topic `topotestix-cluster` is visible via `kafka-topics.sh --list` from each broker. Expands to 3 checks.
2. **Topic roundtrip** — produce a small string (`topotestix-payload`) and consume it back from each broker. Expands to 3 checks.
3. **Service still up after delay** — `systemctl is-active apache-kafka` returns active on each broker after a 30-second sleep. Expands to 3 checks.
4. **Multi-topic creation** — create three topics `topotestix_a`, `topotestix_b`, `topotestix_c` with `--partitions 3 --replication-factor 3` and verify the list contains exactly three lines. Expands to 1 check.
5. **Large-message roundtrip** — produce a 1.5 MiB record with `acks=all` to a 3-partition RF=3 topic and consume it back; the consumer must receive at least 1.5 MiB. Expands to 1 check.

The total per-run check count is therefore 3+3+3+1+1 = 11. The large-message property is the only one that is expected to fail in the sweep; the first four properties act as a "system is actually working" filter and pass in every run that reaches them.

### 6.2.4 Sweep Results

The Kafka 50-seed sweep was executed with the following command:

```bash
python3 -m topotestix.cli orchestrator sweep kafka-cluster --seeds 1..50 --project-root .
```

The aggregate outcome is shown in Table 6.2. Of the 50 runs, 13 passed all 11 checks and 37 failed. Crucially, all 37 failures are concentrated in a single property, `kafka-large-message-on-kafka1`. Whenever a run reached the large-message property and the property failed, the other 10 properties had already passed. Whenever a run passed the large-message property, all 11 properties passed.

**Table 6.2** — Aggregate Kafka 50-seed sweep outcome.

| Outcome | Count | Share |
|---|---:|---:|
| Passed (11/11) | 13 | 26% |
| Failed (≥1 of 11) | 37 | 74% |
| Total | 50 | 100% |

The 37 failures fall into two clean and repeatable classes. Table 6.3 reports the per-class counts together with the underlying Kafka exception.

**Table 6.3** — Kafka failure classes in the 50-seed sweep.

| Class | Count | Kafka exception | Triggering configuration |
|---|---:|---|---|
| Broker `message.max.bytes` too small | 18 | `RecordTooLargeException` | `message.max.bytes = 1 MiB` |
| Log segment size too small | 19 | `RecordBatchTooLargeException` | `log.segment.bytes = 1 MiB` |
| Pass | 13 | n/a | larger size limits in effect |

A cross-tabulation of the three size-related options (`message.max.bytes`, `replica.fetch.max.bytes`, `log.segment.bytes`) against the outcome class is given in Table 6.4. The table shows that the two failure classes are triggered deterministically by specific value ranges, irrespective of the JVM heap, the VM size, and the replication-factor settings.

**Table 6.4** — Kafka sweep outcomes by (`message.max.bytes`, `replica.fetch.max.bytes`, `log.segment.bytes`).

| `message.max.bytes` | `replica.fetch.max.bytes` | `log.segment.bytes` | pass | broker-max | log-segment |
|---:|---:|---:|---:|---:|---:|
| 1 MiB | 1 MiB | 1 MiB | 0 | 3 | 0 |
| 1 MiB | 1 MiB | 16 MiB | 0 | 3 | 0 |
| 1 MiB | 2 MiB | 1 MiB | 0 | 3 | 0 |
| 1 MiB | 2 MiB | 16 MiB | 0 | 2 | 0 |
| 1 MiB | 4 MiB | 1 MiB | 0 | 5 | 0 |
| 1 MiB | 4 MiB | 16 MiB | 0 | 2 | 0 |
| 2 MiB | 1 MiB | 1 MiB | 0 | 0 | 4 |
| 2 MiB | 1 MiB | 16 MiB | 2 | 0 | 0 |
| 2 MiB | 2 MiB | 1 MiB | 0 | 0 | 4 |
| 2 MiB | 2 MiB | 16 MiB | 4 | 0 | 0 |
| 2 MiB | 4 MiB | 1 MiB | 0 | 0 | 3 |
| 2 MiB | 4 MiB | 16 MiB | 2 | 0 | 0 |
| 4 MiB | 1 MiB | 1 MiB | 0 | 0 | 3 |
| 4 MiB | 1 MiB | 16 MiB | 1 | 0 | 0 |
| 4 MiB | 2 MiB | 1 MiB | 0 | 0 | 2 |
| 4 MiB | 2 MiB | 16 MiB | 3 | 0 | 0 |
| 4 MiB | 4 MiB | 1 MiB | 0 | 0 | 3 |
| 4 MiB | 4 MiB | 16 MiB | 1 | 0 | 0 |

Two observations follow directly from this cross-tabulation. First, the broker-max class is triggered exactly when `message.max.bytes` is the smallest value (1 MiB) and the test payload (1.5 MiB) exceeds it, independently of the other size options. Second, the log-segment class is triggered exactly when `log.segment.bytes` is the smallest value (1 MiB), even if `message.max.bytes` is large enough to allow the record. The latter observation is the more interesting one, because it shows that the obvious "raise `message.max.bytes`" fix would not have made the failing configurations pass.

The per-seed outcomes for this sweep are available in `experiments/kafka-cluster/kafka-cluster-sweep-1-50-fixed-20260613-summary.txt` and `-summary.json` (see Section 6.2.7). A full re-execution of the sweep on 2026-08-24 at HEAD `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` reproduced the aggregate exactly — 13 passed / 37 failed, the same 19/18 class split, and zero per-seed flips across all 50 seeds — with every run recording its `gitHead` (`experiments/kafka-cluster/kafka-cluster-sweep-rerun-20260824-summary.{json,txt}`). Because the June artifacts predate per-run provenance recording, the rerun summaries serve as the machine-verifiable record of these numbers; the numbers themselves are unchanged.

### 6.2.5 Failure Class 1: `message.max.bytes` Too Small

The first class is the simplest: when `message.max.bytes = 1 MiB` and the test payload is 1.5 MiB, the broker rejects the produce with `RecordTooLargeException`. The representative seed is 13, and the original report extract is:

```text
org.apache.kafka.common.errors.RecordTooLargeException:
The request included a message larger than the max message size the server will accept.
```

The corresponding configuration in the representative run is:

```text
message.max.bytes        = 1048576   # 1 MiB
log.segment.bytes        = 1048576   # 1 MiB
replica.fetch.max.bytes  = 2097152   # 2 MiB
large test record        = 1572864   # 1.5 MiB
```

The distinguishing property is `kafka-large-message-on-kafka1`. In the same run, all 10 baseline properties pass:

```text
PASS kafka-multi-topic-on-kafka1
PASS kafka-still-up-kafka1
PASS kafka-still-up-kafka2
PASS kafka-still-up-kafka3
PASS kafka-roundtrip-on-kafka1
PASS kafka-roundtrip-on-kafka2
PASS kafka-roundtrip-on-kafka3
PASS kafka-topic-visible-from-kafka1
PASS kafka-topic-visible-from-kafka2
PASS kafka-topic-visible-from-kafka3
```

A class-isolating minimized configuration that isolates only this failure class, while keeping all other options at a simple baseline, is provided in `experiments/kafka-cluster/kafka-cluster-min-message-max.nix`. The corresponding validation run is reproducible with:

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster \
  --seed 1 \
  --name kafka-cluster-min-message-max \
  --project-root . \
  --config-target experiments/kafka-cluster/kafka-cluster-min-message-max.nix
```

The run was stored in `.topotestix/runs/20260615-172715-kafka-cluster-seed-1-kafka-cluster-min-message-max` and confirmed 10/11 passing checks and a single failure of `kafka-large-message-on-kafka1` with `RecordTooLargeException`.

### 6.2.6 Failure Class 2: `log.segment.bytes` Too Small

The second class is more subtle. When `message.max.bytes` is large enough for the record but `log.segment.bytes = 1 MiB`, the broker still rejects the record batch. The representative seed is 9, and the original report extract is:

```text
org.apache.kafka.common.errors.RecordBatchTooLargeException:
The request included message batch larger than the configured segment size on the server.
```

The corresponding configuration in the representative run is:

```text
message.max.bytes        = 4194304   # 4 MiB
log.segment.bytes        = 1048576   # 1 MiB
replica.fetch.max.bytes  = 4194304   # 4 MiB
large test record        = 1572864   # 1.5 MiB
```

A class-isolating minimized configuration that isolates only this failure class is provided in `experiments/kafka-cluster/kafka-cluster-min-log-segment.nix`. The corresponding validation run is reproducible with:

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster \
  --seed 1 \
  --name kafka-cluster-min-log-segment \
  --project-root . \
  --config-target experiments/kafka-cluster/kafka-cluster-min-log-segment.nix
```

The run was stored in `.topotestix/runs/20260615-173157-kafka-cluster-seed-1-kafka-cluster-min-log-segment` and confirmed 10/11 passing checks and a single failure of `kafka-large-message-on-kafka1` with `RecordBatchTooLargeException`.

This second class is the more interesting empirical finding of the Kafka case study, for two reasons. First, it shows that the surfaced violation is not a "fix the obvious size limit" issue: a system operator who only knew about `message.max.bytes` would have raised it to 4 MiB and would still have observed the failure. Second, it shows that TopoTestix can expose non-obvious configuration interactions across related but distinct settings.

### 6.2.7 Shrinking Limitations for the Kafka Case Study

The generic TopoTestix shrinker initially did **not** produce trustworthy final minimizations for the two Kafka case-study failures. Two distinct issues were identified; one of them has since been fixed and empirically verified, while the other stands.

The first issue is that the generic shrinker preserves the property "this run fails" but does not preserve the property "this run fails with this specific exception class". When seed 9 (log-segment) is shrunk, the shrinker can reduce `message.max.bytes` to 1 MiB, which then makes the failure collapse into the `RecordTooLargeException` class. The shrinker therefore returns a different failure than the one the operator is debugging. This is not merely a theoretical possibility: in the 2026-08-24 rerun at HEAD `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c`, the fully minimized seed-9 run (`.topotestix/runs/20260824-141305-kafka-cluster-seed-9-kafka-shrink-seed9-rerun-20260824`) fails with `RecordTooLargeException` although the un-shrunk seed-9 run fails with `RecordBatchTooLargeException`. The class-preservation limitation is therefore confirmed on the current code.

The second issue was a choice-path limitation that is specific to Kafka: the broker settings are referenced as Nix attribute names containing dots (`"message.max.bytes"`, `"log.segment.bytes"`, etc.), and TopoTestix choice paths also use dots as separators. The two uses of the dot character collided when choice paths are passed on the command line, so the generic shrinker's choice overrides became ambiguous for these settings, and some raw shrink attempts produced `0/0` property reports due to Nix/build failures rather than the intended Kafka property failure. This issue is fixed as of commit `c0807fe` (2026-08-21): choice paths now resolve by progressively joining dot-separated path parts, with genuine overlaps between nested and dotted attribute names rejected as ambiguous instead of guessed. The 2026-08-24 rerun verifies the fix end-to-end: a seed-9 probe that forces `.services.apache-kafka.settings.log.segment.bytes` and `.services.apache-kafka.settings.message.max.bytes` to their minimal values builds cleanly, reaches the NixOS module, and fails exactly where designed (`.topotestix/runs/20260824-123925-kafka-cluster-seed-9-kafka-probe-dotted-override-20260824`), and both Kafka shrinks complete as clean mechanical reductions to all-minimal configurations (seed 13: `.topotestix/runs/20260824-132314-kafka-cluster-seed-13-kafka-shrink-seed13-rerun-20260824`, failure class preserved; seed 9: reduction clean, class collapsed as described above).

The class-isolating minimized configurations therefore intentionally fix all unrelated options to simple baseline values and leave only the failure-causing size constraint variable. They are minimal in the practical thesis sense: they are the smallest configurations in which the failure class can be reproduced and in which the 10 baseline properties still pass. After the `c0807fe` fix, the residual gap is failure-class preservation only — mechanical shrinkability itself is no longer in question.

### 6.2.8 Discussion

The Kafka case study supports a number of empirical claims.

First, TopoTestix can automatically surface configuration-dependent property violations in a real distributed system without any hand-written regression test. The sweep was an out-of-the-box property-based fuzzing run over 50 seeds; the failures were produced by the framework, not by the developer.

Second, the surfaced violations are not Kafka implementation defects. The cluster starts, runs for the full duration of the property suite, and serves all small-message and metadata properties correctly. The failures only appear when the workload exceeds the configured size limits. The fact that 10/11 properties pass in every failing run is a strong signal that ordinary smoke tests would not have detected the issue.

Third, the failure classes are configuration interactions, not single-setting mistakes. In the log-segment case, the obvious `message.max.bytes` setting is already large enough; the issue is the interaction between `log.segment.bytes` and the record-batch size. This is exactly the kind of "looks healthy, only fails under a realistic workload" failure mode that motivates property-based fuzzing of distributed systems.

Fourth, the failures are reproducible as NixOS test runs and are accompanied by class-isolating minimized configurations. The two minimized repros are small enough to fit on a single screen and can be added to a regression suite.

The Kafka case study is therefore a positive answer to **RQ1** and **RQ2**, and a partial answer to **RQ3**: the failures are localized, but the localization is done by class-isolating minimized configurations rather than by the generic shrinker (Section 6.5.2).

## 6.3 Case Study: etcd

### 6.3.1 Target Setup

The etcd target is a three-node etcd/Raft cluster. The target consists of:

- a topology description `targets/etcd-cluster/topology.nix` declaring three nodes `etcd1`, `etcd2`, `etcd3` on a single private network with one vlan;
- a NixOS configuration module `targets/etcd-cluster/config.nix` that parameterizes the `services.etcd` service;
- a property suite `targets/etcd-cluster/properties.nix` with six high-level properties, expanded to 12 per-run checks;
- a test script `targets/etcd-cluster/test-script.py` that composes the property suite with the standard TopoTestix runner.

The cluster forms a Raft group of three members and exposes the standard etcd v3 client API on each node.

### 6.3.2 Configuration Space and Properties

The v2 etcd target fuzzes six options on a fixed three-member topology (`etcdVlans = [1]`, `roles.etcd = 3`):

- `virtualisation.memorySize` — 1024 / 2048 MiB.
- `virtualisation.diskSize` — 2048 / 4096 MiB.
- `services.etcd.extraConf.HEARTBEAT_INTERVAL` — 100 / 250 ms.
- `services.etcd.extraConf.ELECTION_TIMEOUT` — 1250 / 2500 ms.
- `services.etcd.extraConf.SNAPSHOT_COUNT` — 10000 / 100000.
- `services.etcd.extraConf.QUOTA_BACKEND_BYTES` — 2 MiB / 8 MiB / 64 MiB.

The product of the per-dimension value counts is 96 distinct configurations; the sweep samples 50 of them, just over half the space.

The v2 property suite consists of six high-level properties:

1. **Cluster healthy** — `etcdctl endpoint health --cluster` succeeds from all three nodes. Expands to 3 checks.
2. **KV roundtrip** — write a key/value from one node and read it back from another. Expands to 3 checks (1→2, 1→3, 2→1).
3. **Leader is one of three** — the cluster has exactly one leader. Expands to 1 check.
4. **Lease TTL expiry** — a leased key disappears after the lease expires. Expands to 1 check.
5. **Service still up after delay** — `systemctl is-active etcd` returns active and `etcdctl endpoint health --cluster` succeeds on all three nodes after a 20-second sleep. Expands to 3 checks.
6. **Quota write burst** — write 80 distinct 64 KiB values into a new prefix, totalling approximately 5 MiB, and read the last one back. Expands to 1 check.

The total per-run check count is 3+3+1+1+3+1 = 12. The quota write-burst property is intentionally ordered last so that it can only fail in configurations where the cluster has already passed all five basic properties. The property name carries the `zz_` prefix in the implementation to ensure this ordering.

### 6.3.3 v1 Sweep: Startup Configuration Constraint

The first etcd sweep used a slightly broader heartbeat/election-timing space that included an invalid combination:

```text
heartbeat-interval = 250
election-timeout   = 1000
```

etcd rejects this combination at startup, before the property suite runs:

```text
failed to verify flags: --election-timeout[1000ms] should be at least as 5 times as --heartbeat-interval[250ms]
```

The v1 50-seed sweep produced the aggregate outcome shown in Table 6.5. The 11 failed seeds are 5, 7, 20, 21, 25, 29, 30, 34, 38, 42, 49, all of which fail with the same `invalid-etcd-election-timeout-heartbeat-ratio` class and a `0/0` property-report count.

**Table 6.5** — Aggregate etcd v1 50-seed sweep outcome.

| Outcome | Count | Share |
|---|---:|---:|
| Passed | 39 | 78% |
| Failed (startup-only) | 11 | 22% |
| Total | 50 | 100% |

The v1 sweep is useful as evidence that TopoTestix can expose real configuration constraints in a real distributed system, but it is the weaker of the two etcd results. The failure is detected before the property suite runs, and the structured property report is empty. It is therefore not a workload/configuration incompatibility in the sense of **RQ2**; it is a configuration validation failure. The v2 target was designed to address this gap.

### 6.3.4 v2 Sweep: Workload/Quota Incompatibility

The v2 sweep was obtained with the following command:

```bash
python3 -m topotestix.cli orchestrator sweep etcd-cluster --seeds 1..50 --project-root .
```

The aggregate outcome is shown in Table 6.6. Of the 50 runs, 37 passed all 12 checks and 13 failed. All 13 failures belong to a single class, `quota-backend-too-small-for-write-burst`, and in every failing run the failure is in the last property, `etcd-quota-write-burst-etcd1`.

**Table 6.6** — Aggregate etcd v2 50-seed sweep outcome.

| Outcome | Count | Share |
|---|---:|---:|
| Passed (12/12) | 37 | 74% |
| Failed (≥1 of 12) | 13 | 26% |
| Total | 50 | 100% |

The 13 failed seeds are 3, 6, 12, 13, 14, 28, 33, 34, 38, 40, 41, 42, 43. The failure class is the same in all 13 cases:

```text
quota-backend-too-small-for-write-burst: 13
```

The representative error message is:

```text
etcdserver: mvcc: database space exceeded
```

The strong correlation between the failure and the configured backend quota is shown in Table 6.7. Every run with `QUOTA_BACKEND_BYTES = 2097152` (2 MiB) fails; every run with `QUOTA_BACKEND_BYTES = 8388608` (8 MiB) or `67108864` (64 MiB) passes. The correlation is deterministic across the 50 seeds, with no observed counter-examples.

**Table 6.7** — etcd v2 outcomes by backend quota.

| `QUOTA_BACKEND_BYTES` | Passed | Failed | Total |
|---:|---:|---:|---:|
| 2 MiB (2097152) | 0 | 13 | 13 |
| 8 MiB (8388608) | 20 | 0 | 20 |
| 64 MiB (67108864) | 17 | 0 | 17 |

Crucially, in every failing run the cluster passes the first 11 properties: the cluster is healthy from all three nodes, key/value roundtrips work, there is exactly one leader, the lease TTL expires correctly, and the cluster remains healthy after a 20-second delay. Only the 12th property, the quota write-burst, fails. This is exactly the "system looks healthy, only fails under a realistic workload" pattern that **RQ2** asks for.

The per-seed CSV for this sweep is available as part of `experiments/etcd-cluster/etcd-cluster-v2-sweep-1-50-20260616-summary.txt`, and the per-seed outcomes are listed in the per-seed table in `experiments/etcd-cluster/etcd-cluster-v2-sweep-1-50-20260616.md`.

### 6.3.5 Shrinking Results

Two representative v2 failures were shrunk: seed 3 and seed 40. Both seeds failed in the original sweep with the `quota-backend-too-small-for-write-burst` class. The shrink logs are stored in `experiments/etcd-cluster/etcd-cluster-v2-shrink-seed-3.log` and `experiments/etcd-cluster/etcd-cluster-v2-shrink-seed-40.log`.

Both seeds shrink to the same minimal configuration, listed in Table 6.8. The shrinking works cleanly: the minimized runs are still post-start property failures, not Nix/build/startup failures, and the structured report records exactly one failed check, `etcd-quota-write-burst-etcd1`, with the `mvcc: database space exceeded` error message.

**Table 6.8** — Minimal etcd v2 failing configuration produced by the generic shrinker.

| Option | Value |
|---|---|
| `roles.etcd` | 3 |
| `etcdVlans` | [1] |
| `virtualisation.memorySize` | 1024 MiB |
| `virtualisation.diskSize` | 2048 MiB |
| `ETCD_HEARTBEAT_INTERVAL` | 100 ms |
| `ETCD_ELECTION_TIMEOUT` | 1250 ms |
| `ETCD_SNAPSHOT_COUNT` | 10000 |
| `ETCD_QUOTA_BACKEND_BYTES` | 2097152 (2 MiB) |

The validation runs for the minimized configurations are stored in:

```text
.topotestix/runs/20260616-142216-etcd-cluster-seed-3-etcd-cluster-shrink-3
.topotestix/runs/20260616-143326-etcd-cluster-seed-40-etcd-cluster-shrink-40
```

Both minimized runs preserve the intended property-level failure:

```text
passed=11
failed=1
total=12
failed check: etcd-quota-write-burst-etcd1
failure message contains: etcdserver: mvcc: database space exceeded
```

Both shrinks were re-executed on 2026-08-24 at HEAD `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` — that is, on the rewritten shrinker (`c0807fe`, 2026-08-21) with per-run `gitHead` recording (`998cae1`). The minimal configurations are identical to the 2026-06-16 results: same final choice maps, same resolved values, the same single failing check `etcd-quota-write-burst-etcd1` containing `mvcc: database space exceeded`, and the same 11/1/12 counts (final runs `.topotestix/runs/20260824-142121-etcd-cluster-seed-3-etcd-shrink-seed3-rerun-20260824` and `.topotestix/runs/20260824-144914-etcd-cluster-seed-40-etcd-shrink-seed40-rerun-20260824`). This empirically confirms the logic-equivalence of the rewrite for these single-segment setting names.

The minimized configurations are reproducible with the same orchestrator command and the same `--topology-choices` and `--config-choices` flags, listed in `experiments/etcd-cluster/etcd-cluster-v2-shrinking.md`.

### 6.3.6 Discussion

The etcd case study is a strong positive answer to all three research questions.

For **RQ1**, TopoTestix automatically produced 13 failing configurations out of 50 in an out-of-the-box sweep. The failures were classified into a single, clean class without manual intervention.

For **RQ2**, the failures are not startup failures. In every failing run, the cluster boots, elects a leader, passes the full basic distributed-system property suite (cluster health, cross-node KV, single leader, TTL expiry, delayed health), and only fails when the workload exceeds the configured backend quota. The fact that the 2 MiB quota is unconditionally insufficient and the 8 MiB quota is unconditionally sufficient (Table 6.7) is a clean illustration of a workload/configuration incompatibility that a smoke test would not have detected.

For **RQ3**, the generic shrinker localizes both representative failures to the same minimal configuration (Table 6.8). The minimal configuration is small, deterministic, and reproducible. It is small enough to be added verbatim to a regression test or a bug report. The etcd case study is therefore a stronger shrinker result than the Kafka case study, where the generic shrinker encountered the choice-path and class-preservation issues described in Section 6.2.7.

The v1 result is included in the chapter for two reasons. First, it shows that the framework can detect real configuration-validation errors in a real distributed system, even before any property is reached. Second, it motivates the v2 redesign: the v1 result is informative, but the v2 result is more useful for the thesis claim, because the v2 result is a post-start workload/configuration incompatibility.

## 6.4 Case Study: RabbitMQ

### 6.4.1 Target Setup

The RabbitMQ case study uses a three-broker RabbitMQ 4.2.5 cluster (`rabbit1`, `rabbit2`, `rabbit3` on a single private network) with quorum queues for replicated, acknowledged delivery. As with the other case studies, each contract is a NixOS test driver with four components: a topology description (`targets/rabbitmq-<target>/topology.nix`), NixOS modules (`module.nix`, `config.nix`) declaring the per-contract fuzzable options, a property suite (`properties.nix`) of high-level properties expanded into per-run checks, and a test driver (`test-script.py`) that composes workload, fault injection, and evidence collection and emits a structured per-run evidence payload (`disk-results.json`, `failure-domain-results.json`, or `crash-results.json`).

Three contracts are evaluated, each with the property set listed next to it:

- **`rabbitmq-disk` — capacity/confirmation SLO.** Five properties: `rabbitmq-disk-recovers-healthy`, `rabbitmq-disk-capacity-confirmation-contract` (the SLO), `rabbitmq-disk-confirmed-recovered-exactly-once`, `rabbitmq-disk-exact-operation-history`, and `rabbitmq-disk-no-unexplained-messages`.
- **`rabbitmq-failure-domain` — correlated-domain failure.** Two properties: `rabbitmq-failure-domain-exact-recovery` and `rabbitmq-failure-domain-retains-quorum-availability`.
- **`rabbitmq-crash` — abrupt broker failure.** Three properties: `rabbitmq-crash-confirmed-recovered-exactly-once`, `rabbitmq-crash-fault-was-abrupt-and-role-accurate` (evidence that the kill was abrupt and hit the requested role), and `rabbitmq-crash-queue-and-cluster-recover`.

Unlike the Kafka and etcd sweeps, the RabbitMQ case study is not a uniform sweep of the fuzzable space. Each contract is evaluated on a small set of *designed cells* — a positive control plus the smallest configurations expected to violate it — where each cell targets a specific hypothesis about fault semantics and oracle coverage. This is the intended use profile of the harness for a *known* failure-mode family; the Kafka and etcd sweeps demonstrate the same harness on an *unknown* one.

### 6.4.2 Configuration Spaces

- **Disk:** eight dimensions — VM volume (2048/4096 MB), `disk_free_limit` (50/100/200 MB), initial free-space target (500/250/100 MB), backlog rate (10/25 msg/s), consumer outage (2/8 s), message size (1/4/16 KiB), confirm timeout (1/3 s), capacity safety factor (1.0×/1.5×) — a product of 864 cells.
- **Failure domain:** three dimensions — replica placement (spread vs. colocated), failed domain (`zone-a`), confirm timeout (2/5 s) — four cells.
- **Crash:** four dimensions — kill timing (`before_publish`/`during_publish`/`after_publish`), target role (leader/follower, resolved from the observed quorum-queue leader, not from a hostname), kill delay (2/10 s), publish batch (20/50) — 24 cells.

The oracle boundaries matter for reading the results. The disk contract treats a publish as `ambiguous` when the client receives no confirmation within the timeout while the broker may in fact have applied it; the failure-domain contract models a *declared* correlated failure of one zone (not a shared physical block device) and probes availability through the queue; the crash contract observes the queue leader, kills the selected role with SIGKILL (`Restart=no`, so PID replacement is the abruptness evidence), and restarts the service against the same data directory.

### 6.4.3 Disk Capacity: the Falsifiability Boundary

This contract initially had a defect that the evaluation itself exposed: the strict capacity model in the target's oracle — required free space equals the broker's disk-alarm threshold plus the backlog accumulated during the consumer outage, scaled by the safety factor — *entails* the SLO. If declared capacity is sufficient, the `disk_free` alarm cannot activate during the workload, and every confirmed publish succeeds; a contract that fires only when declared capacity is sufficient *and* the run still misbehaves is vacuously true. The positive control behaved exactly as the model predicted (5/5 properties pass, 50/50 publishes confirmed, zero alarm samples across all telemetry phases: ".topotestix/runs-thesis-redesign/20260822-183835-rabbitmq-disk-seed-1-phase2-disk-positive", gitHead `998cae1`), but the contract could never produce the counterexample it was designed to catch.

The fix (commit `761b053`) exposes a weaker *naive* planning model — one that budgets only the backlog payload and ignores the alarm threshold — alongside the strict model in the contract's evidence, and lets the contract fire when *either* model declares capacity sufficient. Because strict sufficiency implies naive sufficiency, every strictly-sufficient cell keeps exactly the old behaviour; the newly covered band is the one where a backlog-only planner passes yet the broker's alarm breaks the confirmation SLO.

The designed counterexample cell ("Cell X") sits in that band: free-space target 100 MB (the driver's fill lands at ≈104.5 MB free), alarm threshold 200 MB, 200 messages × 16 KiB, 1 s confirm timeout, 1.5× safety factor. The run (".topotestix/runs-thesis-redesign/20260822-225112-rabbitmq-disk-seed-1-phase3-disk-counterexample", gitHead `761b053`) produces exactly the designed outcome:

- `naive_capacity_sufficient = true` (≈104.5 MB free ≥ 4.69 MiB backlog) and `capacity_sufficient = false` (104.5 MB < 200 MB + backlog) — the two capacity models disagree, and the contract fires;
- the broker's `disk_free` alarm activates during the publish phase (14 alarm samples; RabbitMQ evaluates the alarm on a timer, so the `after_fill` checkpoint still reads it as inactive), the broker then blocks connections, and **all 200 publish attempts end as `ambiguous` operations** with `ConnectionBlockedTimeout`;
- 22 of the unconfirmed messages were nevertheless durably applied by the broker — exactly the ambiguity boundary this thesis's property language is built to express;
- precisely one property fails (`rabbitmq-disk-capacity-confirmation-contract`), while the other four — including both recovery and consistency properties — pass;
- independent reproductions: two further runs of the *identical* cell (".topotestix/runs-thesis-redesign/20260823-104643-…-phase3-disk-counterexample-repA" and "…/20260823-105452-…-phase3-disk-counterexample-repB", gitHead `70a59ad`, a documentation-only commit over the identical target code) reproduce the same signature — 200/200 `ambiguous`, 14 alarm samples, 22 and 23 recovered — so the counterexample is not a one-off.

That signature — one contract firing with an actionable message while the rest of the suite stays consistent — is the intended counterexample behaviour.

| Cell | strict-suff. | naive-suff. | operations | alarm samples | verdict | run (gitHead) |
|---|---|---|---|---|---|---|
| positive, 500 MB free | true | true† | 50/50 confirmed | 0 | pass 5/5 | `…/20260822-183835-…-phase2-disk-positive` (`998cae1`) |
| positive, 500 MB free (re-run post-fix) | true | true | 50/50 confirmed | 0 | pass 5/5 | `…/20260822-224837-…-phase3-disk-positive-v2` (`761b053`) |
| Cell X: 100 MB free / 200 MB limit / 200 × 16 KiB | **false** | true | 200/200 ambiguous (`ConnectionBlockedTimeout`) | 14 | **fails** capacity contract only | `…/20260822-225112-…-phase3-disk-counterexample` (`761b053`) |
| Cell X, reproduction 1 (identical cell) | **false** | true | 200/200 ambiguous (`ConnectionBlockedTimeout`) | 14 | **fails** capacity contract only (22 recovered) | `…/20260823-104643-…-phase3-disk-counterexample-repA` (`70a59ad`) |
| Cell X, reproduction 2 (identical cell) | **false** | true | 200/200 ambiguous (`ConnectionBlockedTimeout`) | 14 | **fails** capacity contract only (23 recovered) | `…/20260823-105452-…-phase3-disk-counterexample-repB` (`70a59ad`) |
| minimal: 100 MB free / 200 MB limit / 20 × 1 KiB, all other dimensions minimum | **false** | true | 20/20 ambiguous | 16 | **fails** capacity contract only | `…/20260823-001413-…-phase3-disk-counterexample-min` (`761b053`) |

*Table 6.9 — RabbitMQ disk cells.*

† `naive_capacity_sufficient` was recorded only from commit `761b053` onward; for the `998cae1` positive-control row the value is implied (500 MB free ≫ ≈50 KiB backlog), not read from the payload.

### 6.4.4 Failure Domain: the Correlated-Failure Counterexample

The spread placement (one replica per zone) is the positive control: failing `zone-a` removes one of three replicas, majority survives, the probe publishes and confirms within budget, and all 11 tracked operations recover exactly once (pass 2/2; ".topotestix/runs-thesis-redesign/20260822-190647-rabbitmq-failure-domain-seed-1-phase2-faildom-spread", gitHead `998cae1`).

The colocated placement puts two of the three replicas in `zone-a`. Failing that zone removes a quorum majority, so the queue cannot commit any confirmation write. Both counterexample runs (".topotestix/runs-thesis-redesign/20260822-190921-…-phase2-faildom-colocA" and "…/20260822-191139-…-phase2-faildom-colocB", both gitHead `998cae1`) produce the designed result: `rabbitmq-failure-domain-exact-recovery` **passes** (all 11 operations recover exactly once, including the probe's message, which the oracle records as `ambiguous`), while `rabbitmq-failure-domain-retains-quorum-availability` **fails** with the structured message identifying the surviving single replica and the `OuterCommandTimeout` evidence. The two runs are independent reproductions (distinct `op_id`s, identical failure shape), plus an earlier pair from before the thesis-evidence baseline ("…/20260821-125706-…-colocated-counterexample" and "…/20260821-125835-…-colocated-counterexample-2").

| Cell | failed domain | surviving replicas | probe | recovery | verdict | run (gitHead) |
|---|---|---|---|---|---|---|
| spread | `zone-a` | 2 of 3 | confirmed | 11/11 exactly once | pass 2/2 | `…/20260822-190647-…-phase2-faildom-spread` (`998cae1`) |
| colocated | `zone-a` | **1 of 3** | `ambiguous` (`OuterCommandTimeout`) | 11/11 exactly once | **fails** availability contract; recovery passes | `…/20260822-190921-…-phase2-faildom-colocA` (`998cae1`) |
| colocated, repro 2 | `zone-a` | 1 of 3 | `ambiguous` | 11/11 exactly once | same | `…/20260822-191139-…-phase2-faildom-colocB` (`998cae1`) |

*Table 6.10 — RabbitMQ failure-domain cells.*

### 6.4.5 Abrupt Crash: durability and the ambiguous-operation boundary

The crash contract states that every confirmed publish survives one abrupt broker failure of the requested role, followed by exact-once recovery. Across the evaluated cells — follower reproductions, leader, and during-publish variants (Table 6.11) — the outcome is uniformly pass 3/3 with 50/50 operations confirmed and **zero ambiguous operations**, including:

- **leader kill:** the queue leader migrates `rabbit1` → `rabbit2` across the kill, and the cluster and queue fully recover ("…/20260822-185806-…-phase2-crash-leader");
- **during-publish retune** (10 s kill delay with a 50-operation batch, repeated for both roles): still zero ambiguous operations ("…/20260822-202330-…-phase3-crash-during-retune" and "…/20260822-202536-…-phase3-crash-during-retune-2").

Two findings are worth recording. First, the Phase-1 smoke run exposed a real driver defect — a naively restarted broker returned to service as a healthy singleton outside the queue's online member set — which was fixed with a cluster-aware restart plus rejoin forensics (commit `cd06a3c`) and is visible as recovered state in every subsequent run (`rejoined_cluster` and online member sets equal the full three-node cluster). That is the evaluation-harness finding loop in action: smoke run → oracle exposes the gap → driver fixed → re-run confirms. Second, the *ambiguous-operation* boundary was **not** exercised by any crash cell on this stack (RabbitMQ 4.2.5, quorum queues, Pika confirmed channel): in-flight confirms either complete before the kill or re-commit durably. This is reported as an honest negative observation with its cell parameters, not as a pass claim about ambiguity handling; the ambiguous path of the property language is instead exercised by the disk counterexample (`ConnectionBlockedTimeout`) and the failure-domain probe (`OuterCommandTimeout`).

| Cell | role killed | operations | ambiguous | leader before → after | verdict | run (gitHead) |
|---|---|---|---|---|---|---|
| follower, repro A | `rabbit2` | 50/50 confirmed | 0 | `rabbit1` → `rabbit1` | pass 3/3 | `…/20260822-175757-…-phase2-crash-follower-repA` (`998cae1`) |
| follower, repro B | `rabbit2` | 50/50 confirmed | 0 | `rabbit1` → `rabbit1` | pass 3/3 | `…/20260822-180022-…-phase2-crash-follower-repB` (`998cae1`) |
| leader | `rabbit1` | 50/50 confirmed | 0 | `rabbit1` → `rabbit2` | pass 3/3 | `…/20260822-185806-…-phase2-crash-leader` (`998cae1`) |
| during-publish, follower | `rabbit2` | 50/50 confirmed | 0 | `rabbit1` → `rabbit1` | pass 3/3 | `…/20260822-190037-…-phase2-crash-during` (`998cae1`) |
| during retune, follower, 10 s delay | `rabbit2` | 50/50 confirmed | 0 | `rabbit1` → `rabbit1` | pass 3/3 | `…/20260822-202330-…-phase3-crash-during-retune` (`998cae1`) |
| during retune, leader, 10 s delay | `rabbit1` | 50/50 confirmed | 0 | `rabbit1` → `rabbit2` | pass 3/3 | `…/20260822-202536-…-phase3-crash-during-retune-2` (`998cae1`) |

*Table 6.11 — RabbitMQ crash cells.*

### 6.4.6 Shrinking and Minimality for the RabbitMQ Cells

Three observations, in decreasing order of generality.

- **Failure domain is minimal by construction.** The passing and failing cells differ in exactly one configuration dimension — replica placement — as verified from the two runs' `choices.json` files. No shrink run is needed: the failing cell already sits on the minimal face of the failure region with respect to every dimension.
- **Disk minimality has a binding constraint, and the evidence shows why.** Cell X fails (Table 6.9). Holding the alarm threshold at 200 MB — the smallest offered value above the observed fill floor (≈104.5 MB free, below which the 100 MB threshold cannot be crossed) — and setting *every other dimension to its minimum* (2048 MB volume, 10 msg/s × 2 s = 20 × 1 KiB, 1 s timeout, 1.0× factor) reproduces the identical single-contract failure with a ≈160× smaller payload (20/20 ambiguous, 16 alarm samples: ".topotestix/runs-thesis-redesign/20260823-001413-…-phase3-disk-counterexample-min", gitHead `761b053`). A duplicate of this run ("…/20260822-231356-…-phase3-disk-counterexample-min"), started inadvertently, yields the same verdict and independently confirms the result. Thus the violation is minimal with respect to every non-threshold dimension, and the run evidence explains — and bounds — the one dimension that cannot shrink: the available free-space floor sits above the 100 MB threshold.
- **Methodological note.** The generic seed-based shrinker (Section 6.5.2) cannot be applied to these counterexamples: it shrinks around a seed, while the RabbitMQ counterexample cells are designed cells with *forced* choices. Minimality was therefore established (a) by construction (failure domain) and (b) by a designed all-minimum verification run at the shrinking limit (disk) — the same *class* of result the shrinker produces for the etcd counterexample, obtained by a different procedure.

### 6.4.7 Discussion

**RQ1 (well-engineered property suites expose violations on demand).** Affirmed on a third system. The disk counterexample fires exactly one property with an actionable, structured message (`naive_capacity_sufficient=true`, `capacity_sufficient=false`, per-operation `ambiguous`/`ConnectionBlockedTimeout`, alarm telemetry), while recovery and consistency properties stay green; the failure-domain counterexample likewise isolates the availability contract and names the surviving replica. Failure classification is crisp, and the evidence payloads (per-operation outcome + exception type + alarm samples) are what make each counterexample citable.

**RQ2 (healthy-under-smoke, failing-under-contract).** Affirmed as the general shape: every failing RabbitMQ run has a healthy baseline (the other properties pass; both recovery properties pass even while the SLO is violated), and the Phase-1 → fixed → re-verified loop for the crash driver shows the harness catching a real oracle gap.

**RQ3 (shrinkability).** Partial on RabbitMQ: failure-domain minimality holds by construction and disk minimality holds up to the demonstrated fill-floor binding constraint, but the generic shrinker still cannot consume forced-choice cells (Section 6.5.2) — the remaining framework gap.

Two cross-cutting lessons. First, oracles and contracts must be *co-designed*: an oracle so strong that it entails the SLO vacates the contract (the falsifiability boundary of Section 6.4.3). Second, `ambiguous` must remain a first-class operation outcome in the property language, otherwise broker-side blocking silently degenerates into "the client gave up", and the disk counterexample — broker applied 22 messages the client never saw confirmed — would be unrepresentable.

## 6.5 Cross-cutting Observations

This section discusses observations that emerged from both case studies and that are independent of the individual targets.

### 6.5.1 Framework Fixes Motivated by the Evaluation

The evaluation surfaced a real defect in the runner, which was fixed before the final sweep was executed. The defect and the fix are worth reporting here because they show that the evaluation was performed against a tool that was being actively exercised against real systems.

The defect was in the run/report materialization path of `lib/runner.nix`. The runner writes a structured `report.json` inside the NixOS VM, copies it out, and then raises an `AssertionError` if any property failed. Because the runner raised, the NixOS test derivation was marked as failed, and Nix did not materialize the output path that the orchestrator uses to extract `report.json`. The structured report was therefore lost, and the orchestrator could only see a `0/0` summary in `run.json`. The useful failure evidence survived in `stderr.log`, but the structured per-check report was empty, which made sweep aggregation impossible.

The fix was to remove the `raise` from the per-property failure path in `lib/runner.nix`. The runner now always writes and copies `report.json`, and the NixOS test derivation succeeds. The orchestrator then marks the run as failed from the contents of `report.json` via `report_passed(report)`. Infrastructure failures outside the `_check()` path still fail the VM derivation. After the fix, the validation run for seed 13 reports `"summary": { "failed": 1, "passed": 10, "total": 11 }` in `run.json` and the failed `report.json` entry includes the `RecordTooLargeException` text. The full unit-test suite (`34/34` tests) and `nix flake check` both pass after the fix.

This observation is also relevant to the methodology: the final sweeps reported in this chapter are the post-fix sweeps. The pre-fix sweeps are explicitly excluded from the thesis results.

Three later commits complete this evidence chain. `ca2530d` (2026-06-15) is the report-materialization fix described above. `c0807fe` (2026-08-21) added expected-failure handling (`_check_expected`, with `ACCEPTED_STATUSES = {passed, expected_failure}` in `report_passed`) and dotted-key shrink-path support, and `998cae1` (2026-08-22) made every run record its `gitHead` and an artifact manifest. The 2026-08-24 reruns cited in Sections 6.2.4, 6.2.7, 6.3.5, and 6.5.2 verify that these changes leave all reported June numbers unchanged.

### 6.5.2 Shrinker Behaviour

The two sweep case studies show two different shrinker behaviours, and both are worth reporting.

For etcd v2, the generic shrinker worked cleanly. Both representative failures (seed 3, seed 40) shrink to the same minimal configuration (Table 6.8), and the minimized failures are still post-start property failures. The shrinker therefore gives a positive answer to **RQ3** for etcd. This result also survives the shrinker rewrite: rerunning both shrinks on 2026-08-24 at HEAD `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` (which includes `c0807fe`) produced minimal configurations identical to the June ones, with the same single failing check and the same 11/1/12 counts (final runs `.topotestix/runs/20260824-142121-etcd-cluster-seed-3-etcd-shrink-seed3-rerun-20260824` and `.topotestix/runs/20260824-144914-etcd-cluster-seed-40-etcd-shrink-seed40-rerun-20260824`, each recording its `gitHead`). This confirms the logic-equivalence of the rewrite for these setting names.

For Kafka, the generic shrinker encountered two issues:

1. **Failure preservation is not failure-class preservation.** The shrinker preserves "this run fails" but not "this run fails with this specific exception class". For seed 9, an unconstrained shrinker can reduce `message.max.bytes` and collapse the `RecordBatchTooLargeException` class into the simpler `RecordTooLargeException` class. The 2026-08-24 rerun at HEAD `8ff5f96f` shows this concretely on the current code: the fully minimized run fails with `RecordTooLargeException` where the un-shrunk run fails with `RecordBatchTooLargeException`.
2. **Choice-path limitation for dotted setting names.** Kafka's broker settings use Nix attribute names containing dots (`"message.max.bytes"`, `"log.segment.bytes"`, etc.), and TopoTestix choice paths also use dots as separators; the two uses collided on the command line, and some raw shrink attempts produced `0/0` property reports due to Nix/build failures. As of `c0807fe` (2026-08-21) this issue is fixed — choice paths resolve through progressive joining with explicit ambiguity rejection, and the 2026-08-24 rerun shows dotted overrides building cleanly, reaching the NixOS module, and both shrinks completing as clean mechanical reductions.

The Kafka case study therefore continues to use validated class-isolating minimized configurations rather than claiming automatic shrinker minimality; after the fix, what remains is precisely the class-preservation limitation. The etcd v2 result demonstrates that the generic shrinker produces trustworthy minimal repros when class preservation is not at stake, and the Kafka result motivates one remaining future framework improvement: a class-aware shrinker.

### 6.5.3 Reproducibility

Both case-study sweeps are reproducible end-to-end with the orchestrator commands listed in Sections 6.2 and 6.3. Every per-seed run was stored in `.topotestix/runs/<timestamp>-<target>-seed-<n>-<name>`, and the aggregated summary is stored under `experiments/`. Per-run directories are local, gitignored artifacts: the retained evidence for the Kafka and etcd case studies is the committed sweep summaries and run logs under `experiments/`, while the full per-run payloads of the RabbitMQ case study are retained under `.topotestix/runs-thesis-redesign/`. The class-isolating minimized configurations are stored as standalone Nix files (`experiments/kafka-cluster/kafka-cluster-min-message-max.nix`, `experiments/kafka-cluster/kafka-cluster-min-log-segment.nix`) and are reproducible with the same orchestrator command and a different `--config-target`. The etcd minimized configurations are reproducible with the same orchestrator command and explicit `--topology-choices` and `--config-choices` flags.

A single re-execution of the sweeps therefore reproduces the thesis results bit-for-bit, given the same Nix store. The use of Nix-based test derivations is the key enabler of this reproducibility: the cluster configuration is captured in Nix expressions, the test script is captured in Python source, and the per-run outputs are captured as Nix build outputs.

### 6.5.4 Comparison Between the Three Case Studies

The three case studies are deliberately complementary. Kafka is a partitioned log system with rich broker-side configuration; the failures it surfaces are configuration interactions between related size limits. etcd is a Raft-based key-value store with a quota-bounded backend; the failures it surfaces are workload/configuration incompatibilities between the configured backend quota and a multi-MiB write burst. RabbitMQ is a message broker whose quorum-queue replication supports the capacity/confirmation, correlated-failure, and abrupt-crash contracts; its designed counterexample cells surface single-contract violations with crisp structured evidence (Section 6.4). Together, the three case studies exercise the "configuration interaction", "workload/configuration incompatibility", and "fault-semantics contract" failure modes that motivated this thesis.

The two sweep case studies produce pass/fail splits in the 26%–37% pass / 63%–74% fail range (Tables 6.2 and 6.6), which is a useful operating point for a property-based fuzzer: most configurations are still healthy, but a substantial minority exposes a violation. The RabbitMQ cells are not a sweep, but they show the same design intent in concentrated form: every counterexample cell fails exactly one contract while the recovery and consistency properties stay green. All three case studies also produce failures that are concentrated in a single property and that are accompanied by a clear, repeatable error class. This is the empirical signature of a well-designed property-based fuzzing target, and it is what distinguishes these results from a random crash hunt.

## 6.6 Threats to Validity

Several threats to the validity of the evaluation are worth discussing.

**Construct validity.** The three targets are not representative of all distributed systems. Kafka is a partitioned log/stream system, etcd is a Raft-based key-value store, and RabbitMQ is a message broker; all are mature, single-tenant systems, and none exercises multi-tenant scheduling, network partitions, or clock skew. The properties that are checked are deliberately simple (e.g. "produce and consume one record", "write 80 values and read one back"). The evaluation therefore does not claim that TopoTestix can find violations of arbitrary, complex properties; it claims that TopoTestix can find violations of well-engineered property suites written in the style described in Chapter 4.

**Internal validity.** The sweeps are run sequentially on a single Nix store, and the per-seed run time is non-trivial (multiple minutes for Kafka, slightly less for etcd). The sweep is therefore not a true random sample of the 746,496 (Kafka) or 96 (etcd v2) configurations, but a deterministic pseudo-random sample driven by the seed. The clean cross-tabulation in Table 6.4 and the deterministic 0/13/0 split in Table 6.7 suggest that the sample size is large enough to characterize the failure-class structure, but a larger sample (e.g. 200 or 500 seeds) would be needed to claim coverage of the full configuration space.

**External validity.** The failure classes that TopoTestix surfaced for Kafka and etcd are not Kafka or etcd implementation bugs; they are configuration-dependent workload incompatibilities. This is the most defensible claim that can be made on the basis of three case studies, but it is also a narrower claim than "TopoTestix finds bugs in distributed systems". Additional targets would be needed to test the generality of the claim, and the choice of additional targets (e.g. PostgreSQL, Redis, ZooKeeper) is left to future work.

**Reliability.** The two sweeps, the two class-isolating minimized configurations, the two etcd shrink runs, and the RabbitMQ case-study cells (Section 6.4) are all reproducible from the same orchestrator commands. The project test suites (57/57 Python unit tests and 114/114 Nix `nix-unit` tests) pass as of the commit cited in Section 6.4. The evidence base is also no longer anchored to artifacts without recorded provenance: the Kafka 50-seed sweep and both etcd shrinks were re-executed on 2026-08-24 at HEAD `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c`, every rerun run directory records this `gitHead` plus an artifact manifest (a capability added in `998cae1`), the sweep reproduced the June aggregates exactly with zero per-seed flips, and the etcd shrinks reproduced the June minima identically. The reproducibility is therefore a strength, not a weakness, of the evaluation. The shrinker limitations described in Section 6.5.2 are a reliability caveat for the Kafka case study specifically; the seed-9 rerun demonstrates the class-collapse caveat concretely on the current code.

**Conclusion validity.** The pass/fail splits and the per-class failure counts are obtained by aggregating the structured per-seed reports, not by visual inspection. The aggregated summaries are stored in machine-readable form (`-summary.json` and `-summary.txt`) and are reproducible from the raw run directories. The numerical claims in Sections 6.2.4 and 6.3.4 are therefore exact for the executed sweeps, not estimated.

## 6.7 Summary

This chapter presented the empirical evaluation of TopoTestix on three real-world distributed systems: a three-broker Apache Kafka cluster, a three-node etcd cluster, and a three-broker RabbitMQ cluster. The Kafka sweep produced 13 passes and 37 failures out of 50 seeds, with the failures concentrated in a single property (`kafka-large-message-on-kafka1`) and split into two configuration classes (`RecordTooLargeException` from a 1 MiB `message.max.bytes`, and `RecordBatchTooLargeException` from a 1 MiB `log.segment.bytes`). The etcd v2 sweep produced 37 passes and 13 failures out of 50 seeds, with the failures concentrated in a single property (`etcd-quota-write-burst-etcd1`) and split by the configured backend quota (every 2 MiB run fails, every 8 MiB or 64 MiB run passes). Two representative etcd failures shrink to the same minimal configuration, and two class-isolating minimized Kafka configurations reproduce each Kafka failure class on demand. The RabbitMQ case study (Section 6.4) extends the evidence to a message broker and a correlated-failure mode: each designed counterexample fires exactly one contract with crisp structured evidence — the capacity contract minimized to a 20 × 1 KiB payload — while recovery and consistency properties stay green in every run.

The three research questions posed at the start of this chapter can be answered as follows.

> **RQ1.** Yes. TopoTestix automatically surfaced 50 distinct failing runs across the two targets out of 100 total runs. The failures were classified into a small number of clean, repeatable failure classes without manual intervention. The failures were obtained by running the same out-of-the-box sweep command on both targets, and the per-class counts were obtained by aggregating the structured per-seed reports.
>
> **RQ2.** Yes. In every failing run, the distributed system had started and had passed a substantial baseline property suite (10/11 checks for Kafka, 11/12 checks for etcd). The failures only appeared when a workload-specific property (large-message produce/consume for Kafka, multi-MiB write burst for etcd) was checked. The surfaced violations are therefore not "the system does not start" failures, they are "the system looks healthy under ordinary smoke tests but fails under a realistic workload" failures.
>
> **RQ3.** Partially. For etcd v2, the generic shrinker localizes both representative failures to the same minimal configuration, and 2026-08-24 reruns of both shrinks (seeds 3 and 40) on the rewritten shrinker (`c0807fe`) produce identical minimal configurations. For Kafka, the dotted choice-path limitation was fixed by the same rewrite and verified by the 2026-08-24 rerun; the remaining issue is failure-class preservation — the minimized seed-9 counterexample collapses `RecordBatchTooLargeException` into `RecordTooLargeException` (confirmed by the rerun). Class-isolating minimized configurations are provided for Kafka, and a class-aware shrinker is left to future work.

The strongest empirical claim supported by both case studies is therefore:

> TopoTestix can automatically surface production-relevant, configuration-dependent property violations in real distributed systems. These violations are not implementation defects in the system under test. They are realistic configuration bugs, configuration interactions, and workload/configuration incompatibilities that ordinary smoke tests do not detect, because the system starts and ordinary properties pass.

This claim answers the central research question of the thesis and is supported by the per-class failure counts, the per-seed cross-tabulations, and the class-isolating minimized configurations reported in this chapter.
