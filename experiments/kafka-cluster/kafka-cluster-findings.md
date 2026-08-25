# Kafka-cluster strengthening findings

Date: 2026-06-13  
Target: `kafka-cluster`  
Scope: strengthen the Kafka SUT so the thesis sweep is more likely to find runtime/data-plane failures rather than only trivial startup failures.

## Summary

The original `kafka-cluster` target was too shallow for empirical thesis results:

- 4 fuzzable configuration options.
- 1 property, only checking topic visibility via `kafka-topics.sh --list`.
- No data-plane check, no survival-after-delay check, no size/replication stress.

The target has now been expanded to:

- 16 fuzzable options.
- 746,496 configuration combinations.
- 5 high-level properties, expanded to 11 individual property checks per run.
- A new runtime/data-plane failure mode around Kafka message-size limits.

## Implemented changes

### Configuration surface

File: `targets/kafka-cluster/config.nix`

Added/expanded fuzzed dimensions:

| Category | Options |
|---|---|
| VM resources | `virtualisation.memorySize`, `virtualisation.diskSize` |
| JVM | `services.apache-kafka.jvmOptions` |
| Replication / ISR | `offsets.topic.replication.factor`, `transaction.state.log.replication.factor`, `transaction.state.log.min.isr`, `min.insync.replicas`, `default.replication.factor` |
| Behaviour | `unclean.leader.election.enable`, `auto.create.topics.enable`, `log.retention.hours`, `log.segment.bytes` |
| Payload-size stress | `message.max.bytes`, `replica.fetch.max.bytes` |
| Threading | `num.network.threads`, `num.io.threads` |

Current combination count:

```text
3 memory values
* 3 disk values
* 3 heap values
* 10 binary options
* 3 retention values
* 3 message.max.bytes values
* 3 replica.fetch.max.bytes values
= 746,496 combinations
```

### Properties

File: `targets/kafka-cluster/properties.nix`

Properties now include:

| Property | Purpose | Individual checks |
|---|---|---:|
| `topic_visible_from_all_brokers` | Control-plane metadata visibility | 3 |
| `topic_roundtrip` | Small-message produce/consume data plane | 3 |
| `service_still_up_after_delay` | JVM/process survival after 30 s | 3 |
| `multi_topic_creation` | RF=3 topic creation on 3 brokers | 1 |
| `large_message_roundtrip` | 1.5 MiB produce/consume with `acks=all` | 1 |

Total: 11 checks per run.

## Findings during implementation

### Finding 1 — invalid Python in property spec

The first draft of `multi_topic_creation` contained invalid Python:

```python
for t in topotestix-a topotestix-b topotestix-c:
```

The NixOS test driver type checker caught it before the VM ran:

```text
testScriptWithTypes:80: error: Invalid syntax
```

Fix:

```python
for t in ("topotestix_a", "topotestix_b", "topotestix_c"):
```

This is not a Kafka finding, but it confirms that the composed test-script path is actually checked before execution.

### Finding 2 — too-small JVM heap produced only startup failures

The initial aggressive heap proposal included variants such as:

```nix
[ "-Xms64m"  "-Xmx128m" ]
[ "-Xms256m" "-Xmx512m" ]
[ "-Xms512m" "-Xmx768m" ]
```

A seed-1 run failed during Kafka startup with:

```text
java.lang.OutOfMemoryError: Java heap space
ERROR Encountered fatal fault: Error starting LogManager
```

Run dir:

```text
.topotestix/runs/20260613-130139-kafka-cluster-seed-1-kafka-cluster-seed-1
```

Interpretation:

- This is a real configuration-induced failure.
- But it is weak thesis evidence because Kafka never reaches the property-checking phase.
- The target should prefer configurations where Kafka starts and fails during meaningful behaviour checks.

Decision:

Raise the heap family to:

```nix
[ "-Xms256m"  "-Xmx512m"  ]
[ "-Xms512m"  "-Xmx1024m" ]
[ "-Xms1024m" "-Xmx1536m" ]
```

and keep memory sizes at:

```nix
[ 2048 3072 4096 ]
```

This keeps a tight 512 MiB max-heap variant, but avoids known-useless startup-only failures in the common case.

### Finding 3 — strengthened baseline can pass healthy configs

After the heap correction, two sanity seeds passed all then-current checks:

| Run dir | Seed | Result | Checks |
|---|---:|---|---:|
| `.topotestix/runs/20260613-132412-kafka-cluster-seed-1-kafka-cluster-seed-1` | 1 | passed | 10/10 |
| `.topotestix/runs/20260613-132843-kafka-cluster-seed-2-kafka-cluster-seed-2` | 2 | passed | 10/10 |

This confirmed that the target was not merely broken after expansion.

### Finding 4 — payload-size configuration creates a useful runtime failure

New proposal:

```nix
services.apache-kafka.settings."message.max.bytes"       = [ 1048576 2097152 4194304 ];
services.apache-kafka.settings."replica.fetch.max.bytes" = [ 1048576 2097152 4194304 ];
```

New property:

- creates a topic with 3 partitions and RF=3,
- generates a 1.5 MiB message,
- produces with `acks=all`,
- consumes it back,
- compares consumed bytes with expected bytes.

The intentionally interesting case is:

```text
message.max.bytes = 1048576  # 1 MiB
large message      = 1572864 # 1.5 MiB
```

This lets Kafka start, then fails during a real data-plane operation.

Test run:

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster --seed 13 --project-root .
```

Run dir:

```text
.topotestix/runs/20260613-153958-kafka-cluster-seed-13-kafka-cluster-seed-13
```

Observed failure evidence from `stderr.log`:

```text
org.apache.kafka.common.errors.RecordTooLargeException:
The request included a message larger than the max message size the server will accept.

AssertionError: Failed properties: kafka-large-message-on-kafka1
```

Interpretation:

- Kafka started successfully.
- The failure occurred during a property check.
- The failure is configuration-induced and explainable.
- This is much stronger thesis evidence than a startup timeout/OOM.

## Framework limitation found and fixed

Initially, for the seed-13 property failure, `stderr.log` clearly contained the failed property, but the copied `report.json` was empty:

```json
[]
```

and `run.json` summarized:

```json
"summary": { "failed": 0, "passed": 0, "total": 0 }
```

Root cause:

- The runner wrote `/tmp/report.json` in the VM.
- Then it raised `AssertionError` when any property failed.
- Because the NixOS VM test derivation failed, Nix did not materialize the normal output path from which the orchestrator parses `report.json`.
- The useful evidence remained in `stderr.log`, but the structured report was lost.

Fix:

- `lib/runner.nix` no longer raises after writing/copying `report.json`.
- The NixOS VM derivation succeeds for property failures.
- TopoTestix still marks the run failed from `report.json` via `report_passed(report)`.
- Infrastructure failures outside `_check()` still fail the VM derivation.

This fix landed as commit `ca2530d` (2026-06-15). As of commit `c0807fe` (2026-08-21), `report_passed` accepts exactly the statuses in `ACCEPTED_STATUSES = {passed, expected_failure}`, so designed expected failures count as passes; the June runs in this document contain only passed/failed statuses, so all counts here are identical under the current definitions.

Validation run:

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster --seed 13 --project-root .
# run dir: .topotestix/runs/20260613-160354-kafka-cluster-seed-13-kafka-cluster-seed-13
```

The fixed `run.json` now reports:

```json
"summary": { "failed": 1, "passed": 10, "total": 11 }
```

and the failed `report.json` entry includes the production-relevant Kafka error:

```text
org.apache.kafka.common.errors.RecordTooLargeException:
The request included a message larger than the max message size the server will accept.
```

This preserves structured failure data for shrinking and thesis sweep analysis.

## Fixed 50-seed sweep result

The final fixed sweep is documented in:

```text
experiments/kafka-cluster-sweep-1-50-fixed-20260613.md
experiments/kafka-cluster-sweep-1-50-fixed-20260613-summary.json
experiments/kafka-cluster-sweep-1-50-fixed-20260613-summary.txt
experiments/kafka-cluster-sweep-1-50-fixed-20260613.log
```

Result: 13 passed, 37 failed. The failures split into two production-relevant configuration classes:

- 18 × `RecordTooLargeException` from `message.max.bytes = 1 MiB`.
- 19 × `RecordBatchTooLargeException` from `log.segment.bytes = 1 MiB`.

These are configuration/workload compatibility bugs, not Kafka implementation bugs. They are nevertheless thesis-useful because Kafka starts and normal small-message properties pass; failure appears only under a large-payload data-plane property.

Provenance note (added 2026-08-24): the June sweep artifacts above predate per-run git-provenance recording and do not embed a commit hash, so their provenance is unverifiable after the fact. Their numbers are unchanged; the rerun below supersedes them as citable evidence.

## 2026-08-24 rerun at HEAD `8ff5f96f`

The dotted-key override probe (whose June attempt had died in a build error), both Kafka shrinks (seeds 13 and 9), and the full 50-seed sweep were re-executed on 2026-08-24 at `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` with a clean tracked tree. Every rerun `run.json` records this `gitHead` plus an artifact manifest (`998cae1`). Raw notes: `experiments/kafka-cluster/kafka-cluster-shrink-rerun-20260824.md`.

### Probe: dotted-key overrides build and take effect

Run dir:

```text
.topotestix/runs/20260824-123925-kafka-cluster-seed-9-kafka-probe-dotted-override-20260824
```

Overrides `.services.apache-kafka.settings.log.segment.bytes = 0` and `.services.apache-kafka.settings.message.max.bytes = 0` built cleanly and reached the NixOS module — no June-style build error. The failure is the designed one: only `kafka-large-message-on-kafka1` fails, with `RecordTooLargeException`; summary 10 passed / 1 failed / 11 total. (A killed earlier launch left an orphan dir `20260824-123640-…` without a `run.json`; it is unused.)

### Shrink seed 13: clean reduction, class preserved

Final run dir:

```text
.topotestix/runs/20260824-132314-kafka-cluster-seed-13-kafka-shrink-seed13-rerun-20260824
```

1 initial verification + 11 candidate evaluations, all kept; minimal config = all 16 config choice indices at 0 ⇒ `message.max.bytes` resolves to 1 MiB. Failure class PRESERVED: final run still fails `kafka-large-message-on-kafka1` with `RecordTooLargeException`; summary 10/1/11.

### Shrink seed 9: mechanically clean reduction, class collapses

Final run dir:

```text
.topotestix/runs/20260824-141305-kafka-cluster-seed-9-kafka-shrink-seed9-rerun-20260824
```

1 initial + 12 candidate evaluations; minimal config all-zero indices as in June. Initial run fails with `RecordBatchTooLargeException`; the fully minimized run fails with `RecordTooLargeException`. Verdict at HEAD `8ff5f96f`: mechanical shrinking is now clean post-fix (post-start property failure, 10/1/11, no build/startup errors), but the class-preservation limitation is confirmed on current code — exactly as recorded for June.

### Sweep rerun: exact match to June

50 seeds, sequential, same parallelism/store as the June invocation:

| Outcome | Rerun (2026-08-24) | June (2026-06-13) |
|---|---|---|
| Passed / failed seeds | 13 / 37 | 13 / 37 |
| Categories | 19 log-segment-too-small, 18 broker-message-max-too-small | identical |
| Per-seed flips vs June | none (status + category + failed properties identical, 50/50) | — |
| Property-level classifications | `{failed: 37, passed: 513}` | not emitted in June format |
| Wall time | 2 h 37 m (avg ≈189 s/seed) | ≈3.6 h |

All failures remain post-start data-plane failures of `kafka-large-message-on-kafka1`; no startup/OOM/build failures occurred. Machine-readable summaries (June schema, derived from the new per-run payloads): `experiments/kafka-cluster/kafka-cluster-sweep-rerun-20260824-summary.{json,txt}`. Because the old artifacts contain only passed/failed statuses, their numbers are identical under HEAD definitions; the rerun adds recorded provenance and the new `classifications` field.

## Proposed Kafka direction for the thesis sweep

Keep the new payload-size stress dimensions and large-message property. They are more thesis-useful than the earlier too-small JVM heap variants because they create failures after the distributed system has started.

Recommended sweep dimensions for Kafka:

1. Keep heap fuzzing, but avoid known startup-only impossible values.
2. Keep RF/ISR fuzzing.
3. Keep payload-size fuzzing:
   - `message.max.bytes`
   - `replica.fetch.max.bytes`
4. Keep `large_message_roundtrip` with a 1.5 MiB payload and `acks=all`.
5. Run sweeps in chunks of 10 seeds with `--resume`.

Suggested sweep command after fixing structured report capture:

```bash
python3 -m topotestix.cli orchestrator sweep kafka-cluster --seeds 1..10 --resume --json --project-root . | tee experiments/kafka-cluster-sweep-1-10.json
```

Repeat for `11..20`, `21..30`, etc.

## Reproduction commands

Known startup/OOM finding:

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster --seed 1 --project-root .
# historical run dir: .topotestix/runs/20260613-130139-kafka-cluster-seed-1-kafka-cluster-seed-1
```

Known payload-size property failure:

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster --seed 13 --project-root .
# run dir: .topotestix/runs/20260613-153958-kafka-cluster-seed-13-kafka-cluster-seed-13
```

2026-08-24 rerun minimizations (HEAD `8ff5f96f`, from the "Reproduce with:" blocks in `rerun-shrink-seed-{13,9}.log`; the same commands with `--seed 9` reproduce the seed-9 collapse):

```bash
python3 -m topotestix.cli orchestrator run kafka-cluster \
  --seed 13 \
  --name kafka-shrink-seed13-rerun-20260824 \
  --project-root . \
  --topology-choices '{".kafkaVlans": 0, ".roles.kafka": 0}' \
  --config-choices '{"kafka": {".services.apache-kafka.jvmOptions": 0, ".services.apache-kafka.settings.auto.create.topics.enable": 0, ".services.apache-kafka.settings.default.replication.factor": 0, ".services.apache-kafka.settings.log.retention.hours": 0, ".services.apache-kafka.settings.log.segment.bytes": 0, ".services.apache-kafka.settings.message.max.bytes": 0, ".services.apache-kafka.settings.min.insync.replicas": 0, ".services.apache-kafka.settings.num.io.threads": 0, ".services.apache-kafka.settings.num.network.threads": 0, ".services.apache-kafka.settings.offsets.topic.replication.factor": 0, ".services.apache-kafka.settings.replica.fetch.max.bytes": 0, ".services.apache-kafka.settings.transaction.state.log.min.isr": 0, ".services.apache-kafka.settings.transaction.state.log.replication.factor": 0, ".services.apache-kafka.settings.unclean.leader.election.enable": 0, ".virtualisation.diskSize": 0, ".virtualisation.memorySize": 0}}'
# final run dir: .topotestix/runs/20260824-132314-kafka-cluster-seed-13-kafka-shrink-seed13-rerun-20260824
```
