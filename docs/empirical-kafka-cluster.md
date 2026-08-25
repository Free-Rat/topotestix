# Kafka-cluster empirical finding interpretation

This note explains how to interpret the Kafka 50-seed sweep results for thesis writing.

## Main conclusion

The Kafka sweep should **not** be presented as discovering Kafka implementation bugs.

A better and more accurate claim is:

> TopoTestix automatically surfaced production-relevant Kafka configuration/workload incompatibilities. The cluster starts successfully and basic checks pass, but a realistic workload-specific data-plane property fails.

This is valuable because many production failures are not caused by software defects in the system under test. They are caused by invalid or incomplete configuration relative to the workload being deployed.

## Why the finding is valuable

The fixed Kafka sweep found failures where:

1. Kafka starts successfully.
2. The brokers expose port `9092`.
3. Basic service-liveness checks pass.
4. Topic visibility checks pass.
5. Small-message produce/consume checks pass.
6. Multi-topic creation checks pass.
7. Only the large-payload data-plane property fails.

This is stronger than a trivial startup failure. It shows that the system can look healthy under ordinary smoke tests while still violating an application-level workload property.

## Production relevance

The large-message property sends and consumes a 1.5 MiB Kafka record. This is a realistic workload assumption for systems that send larger events, serialized documents, binary payloads, analytics records, or batched application messages.

TopoTestix found two concrete failure classes.

### 1. Broker maximum message size too small

Example failure:

```text
org.apache.kafka.common.errors.RecordTooLargeException:
The request included a message larger than the max message size the server will accept.
```

Cause:

```text
message.max.bytes = 1048576  # 1 MiB
large test record = 1572864  # 1.5 MiB
```

Interpretation:

The cluster is healthy for ordinary small messages, but the configured broker limit is incompatible with the deployed workload.

### 2. Log segment size too small

Example failure:

```text
org.apache.kafka.common.errors.RecordBatchTooLargeException:
The request included message batch larger than the configured segment size on the server.
```

Representative configuration:

```text
message.max.bytes = 4194304  # 4 MiB, apparently large enough
log.segment.bytes = 1048576  # 1 MiB, still too small
large test record = 1572864  # 1.5 MiB
```

Interpretation:

This is more interesting than simply setting `message.max.bytes` too low. The broker message-size limit appears to allow the workload, but another related Kafka setting, `log.segment.bytes`, still rejects the batch. This demonstrates that TopoTestix can expose non-obvious configuration interactions.

## Thesis-safe wording

Use wording like:

> The Kafka experiment did not reveal a defect in Kafka itself. Instead, it demonstrated that TopoTestix can automatically find configuration-dependent violations of workload properties in a real distributed system. In particular, it found configurations where the Kafka cluster booted successfully and passed basic health and small-message checks, but failed a large-message produce/consume property due to incompatible `message.max.bytes` or `log.segment.bytes` settings.

Avoid wording like:

> TopoTestix found Kafka bugs.

Better alternatives:

- configuration bug
- misconfiguration
- workload/configuration incompatibility
- configuration interaction
- property violation under a realistic workload

## Fixed 50-seed sweep result

The finished Kafka case study is documented in:

```text
experiments/kafka-cluster/kafka-cluster-case-study.md
```

The fixed sweep result is documented in:

```text
experiments/kafka-cluster/kafka-cluster-sweep-1-50-fixed-20260613.md
experiments/kafka-cluster/kafka-cluster-sweep-1-50-fixed-20260613-summary.json
experiments/kafka-cluster/kafka-cluster-sweep-1-50-fixed-20260613-summary.txt
experiments/kafka-cluster/kafka-cluster-sweep-1-50-fixed-20260613.log
```

The minimized/class-isolating repro configs are:

```text
experiments/kafka-cluster/kafka-cluster-min-message-max.nix
experiments/kafka-cluster/kafka-cluster-min-log-segment.nix
```

Aggregate result:

| Outcome | Count |
|---|---:|
| Passed | 13 |
| Failed | 37 |
| Total | 50 |

Failure classes:

| Class | Count | Exception |
|---|---:|---|
| Broker max-message limit too small | 18 | `RecordTooLargeException` |
| Log segment size too small | 19 | `RecordBatchTooLargeException` |

Provenance note (added 2026-08-24): the June artifacts above were produced before the repository recorded per-run git provenance and do not carry a verifiable commit hash. Their numbers are unchanged, but as citable evidence they are superseded-in-provenance by the rerun below.

## 2026-08-24 rerun at HEAD `8ff5f96f`

All reruns on this page were executed on 2026-08-24 at commit `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c`. This HEAD includes the shrinker rewrite `c0807fe` (2026-08-21; dotted-key choice-path support and expected-failure handling) and `998cae1` (2026-08-22; per-run `gitHead` plus artifact manifest in `run.json`). Every rerun run directory records this `gitHead`, so these results are machine-verifiable from the run store in a way the June artifacts are not.

### Sweep rerun: identical aggregate, zero per-seed flips

The 50-seed sweep was re-executed sequentially with the same parallelism and store layout as June:

| Outcome | Count |
|---|---:|
| Passed | 13 |
| Failed | 37 |
| Total | 50 |

Failure classes are identical to June:

| Class | Count | Exception |
|---|---:|---|
| Broker max-message limit too small | 18 | `RecordTooLargeException` |
| Log segment size too small | 19 | `RecordBatchTooLargeException` |

There were zero per-seed flips against the June summary: seed status, category, and failed-property set match on all 50 seeds. Every failure remains a post-start data-plane failure of `kafka-large-message-on-kafka1`; the property-level classifications emitted by the rerun are `{failed: 37, passed: 513}`. Average wall time was ≈189 s/seed (2 h 37 m total). Machine-readable summaries:

```text
experiments/kafka-cluster/kafka-cluster-sweep-rerun-20260824-summary.json
experiments/kafka-cluster/kafka-cluster-sweep-rerun-20260824-summary.txt
```

The old artifacts record only passed/failed counts, so their totals are numerically identical under the current status definitions (`report_passed` now also accepts `expected_failure`, a status June runs never used); the rerun supersedes them because its provenance is recorded.

### Dotted-key config overrides reach the NixOS module

The June forced-override attempt had died in a Nix build error before any property ran. At HEAD, a seed-9 probe that forces both dotted broker settings to index 0 builds cleanly and takes effect end-to-end:

```text
.topotestix/runs/20260824-123925-kafka-cluster-seed-9-kafka-probe-dotted-override-20260824
```

Overrides applied: `.services.apache-kafka.settings.log.segment.bytes = 0` and `.services.apache-kafka.settings.message.max.bytes = 0` (both resolve to 1 MiB). The run fails by design and only by design: the single failing check is `kafka-large-message-on-kafka1` with `RecordTooLargeException`; summary 10 passed / 1 failed / 11 total. (An earlier aborted launch left an incomplete sibling directory without a `run.json`; it is not evidence and was left untouched.)

### Shrink seed 13: clean reduction, failure class preserved

Final minimized-validation run:

```text
.topotestix/runs/20260824-132314-kafka-cluster-seed-13-kafka-shrink-seed13-rerun-20260824
```

The shrinker evaluated 11 candidates and kept every reduction; the minimal config sets all 16 config choice indices to 0, which resolves `message.max.bytes` to its simplest value (1 MiB). The minimized run still fails with the original class — `RecordTooLargeException` on `kafka-large-message-on-kafka1`; summary 10 passed / 1 failed / 11 total.

### Shrink seed 9: clean reduction, failure class collapses (known limitation)

Final minimized-validation run:

```text
.topotestix/runs/20260824-141305-kafka-cluster-seed-9-kafka-shrink-seed9-rerun-20260824
```

12 candidates were evaluated; the minimal config again sets every choice index to 0. The initial un-shrunk seed-9 run fails with `RecordBatchTooLargeException` (the log-segment class), while the fully minimized run fails with `RecordTooLargeException` (the broker-max class): the shrinker reduces the failure into the other size-limit class. Verdict for the current code: the mechanical shrink itself is now clean (post-start property failure, no Nix/build/startup errors — confirming the dotted-key fix end-to-end), but the class-preservation limitation stands. Class-isolating minimized configurations therefore remain the right vehicle for reproducing each Kafka failure class on demand.

## Empirical claim supported by this result

The Kafka experiment supports the following claim:

> TopoTestix can explore a large distributed-system configuration space and identify configurations that satisfy basic availability and smoke-test properties but violate more workload-specific data-plane properties.

This is a useful result for the thesis because it shows the benefit of property-based testing over ordinary service-startup or health-check validation.
