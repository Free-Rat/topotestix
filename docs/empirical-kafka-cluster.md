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

## Empirical claim supported by this result

The Kafka experiment supports the following claim:

> TopoTestix can explore a large distributed-system configuration space and identify configurations that satisfy basic availability and smoke-test properties but violate more workload-specific data-plane properties.

This is a useful result for the thesis because it shows the benefit of property-based testing over ordinary service-startup or health-check validation.
