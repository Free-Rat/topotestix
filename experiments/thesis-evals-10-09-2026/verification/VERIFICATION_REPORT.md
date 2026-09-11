# Verification report

## Headline counts

| Verdict | Count |
|---|---|
| match | 77 |
| within-tolerance | 5 |
| mismatch | 0 |
| not-reproduced | 0 |
| informational-observed | 9 |
| total | 91 |

## Kafka claims

| Claim | Expected | Observed | Verdict |
|---|---|---|---|
| k-01 | 13 of 50 pass / 37 of 50 fail | 13 pass / 37 fail of 50 seeds | match |
| k-02 | 37 failures all in kafka-large-message-on-kafka1 | 37 of 37 failing seeds failed only kafka-large-message-on-kafka1 | match |
| k-03 | message.max.bytes too small: 18 (RecordTooLargeException); log.segment.bytes too small: 19 (RecordBatchTooLargeException); Pass: 13 | broker-message-max-too-small: 18 (RecordTooLargeException); log-segment-too-small: 19 (RecordBatchTooLargeException); Pass: 13 | match |
| k-04 | 0/3/0 | 0/3/0 (1MiB/1MiB/1MiB) | match |
| k-05 | 0/3/0 | 0/3/0 (1MiB/1MiB/16MiB) | match |
| k-06 | 0/3/0 | 0/3/0 (1MiB/2MiB/1MiB) | match |
| k-07 | 0/2/0 | 0/2/0 (1MiB/2MiB/16MiB) | match |
| k-08 | 0/5/0 | 0/5/0 (1MiB/4MiB/1MiB) | match |
| k-09 | 0/2/0 | 0/2/0 (1MiB/4MiB/16MiB) | match |
| k-10 | 0/0/4 | 0/0/4 (2MiB/1MiB/1MiB) | match |
| k-11 | 2/0/0 | 2/0/0 (2MiB/1MiB/16MiB) | match |
| k-12 | 0/0/4 | 0/0/4 (2MiB/2MiB/1MiB) | match |
| k-13 | 4/0/0 | 4/0/0 (2MiB/2MiB/16MiB) | match |
| k-14 | 0/0/3 | 0/0/3 (2MiB/4MiB/1MiB) | match |
| k-15 | 2/0/0 | 2/0/0 (2MiB/4MiB/16MiB) | match |
| k-16 | 0/0/3 | 0/0/3 (4MiB/1MiB/1MiB) | match |
| k-17 | 1/0/0 | 1/0/0 (4MiB/1MiB/16MiB) | match |
| k-18 | 0/0/2 | 0/0/2 (4MiB/2MiB/1MiB) | match |
| k-19 | 3/0/0 | 3/0/0 (4MiB/2MiB/16MiB) | match |
| k-20 | 0/0/3 | 0/0/3 (4MiB/4MiB/1MiB) | match |
| k-21 | 1/0/0 | 1/0/0 (4MiB/4MiB/16MiB) | match |
| k-22 | broker-max iff message.max.bytes=1MiB | broker-max iff message.max.bytes=1MiB (all 18 cells) | match |
| k-23 | log-segment iff log.segment.bytes=1MiB | log-segment iff log.segment.bytes=1MiB (cells reachable past broker-max) | match |
| k-24 | seed 13 | seed 13: status=failed, failure_class=broker-message-max-too-small | match |
| k-25 | 10 pass / 1 fail | 10 pass / 1 fail (failed check: kafka-large-message-on-kafka1) | match |
| k-26 | seed 9 | seed 9: status=failed, failure_class=log-segment-too-small | match |
| k-27 | 10 pass / 1 fail | 10 pass / 1 fail (failed check: kafka-large-message-on-kafka1) | match |
| k-28 | minimized seed-9 fails with RecordTooLargeException | seed 9: original_class=log-segment-too-small, shrunk_status=failed, class_preserved=False | match |
| k-29 | 746496 configurations of which 50 sampled | 746496 configurations of which 50 sampled | match |
| k-30 | zero flips across all 50 seeds | flips=0 across kafka-sweep repetitions (present=True) | match |
| k-31 | 50-seed sweep with 37 failing configurations in one large-message property split into two deterministic classes | 13/37 of 50 seeds; failure classes: ['broker-message-max-too-small', 'log-segment-too-small'] | match |

## etcd v1 claims

| Claim | Expected | Observed | Verdict |
|---|---|---|---|
| e1-01 | 39 pass / 11 fail of 50 seeds | 39 pass / 11 fail of 50 seeds | match |
| e1-02 | seeds 5,7,20,21,25,29,30,34,38,42,49 | failing seeds 5,7,20,21,25,29,30,34,38,42,49 | match |
| e1-03 | class invalid-etcd-election-timeout-heartbeat-ratio with empty 0/0 property report (failure pre-property-suite) | failure_class=invalid-etcd-election-timeout-heartbeat-ratio; failing seeds with recorded checks: [] | match |
| e1-04 | heartbeat-interval=250ms with election-timeout=1000ms; error 'election-timeout should be at least 5x heartbeat-interval' | > etcd2 # [  893.401980] etcd[952]: {"level":"warn","ts":"2026-09-10T02:15:22.037650Z","caller":"etcdmain/etcd.go:66","msg":"failed to verify flags","error":"--election-timeout[1000ms] should be at least as 5 times as --heartbeat-interval[… | match |

## etcd v2 claims

| Claim | Expected | Observed | Verdict |
|---|---|---|---|
| e2-01 | 37 pass / 13 fail of 50 runs | 37 pass / 13 fail of 50 seeds | match |
| e2-02 | seeds 3,6,12,13,14,28,33,34,38,40,41,42,43 | failing seeds 3,6,12,13,14,28,33,34,38,40,41,42,43 | match |
| e2-03 | all 13 in class quota-backend-too-small-for-write-burst; failed check is last one etcd-quota-write-burst-etcd1 | failure_class=quota-backend-too-small-for-write-burst; 13/13 failing seeds failed only etcd-quota-write-burst-etcd1 | match |
| e2-04 | etcdserver: mvcc: database space exceeded | Error: etcdserver: mvcc: database space exceeded | match |
| e2-05 | 0/13/13 | 0/13/13 (quota 2097152) | match |
| e2-06 | 20/0/20 | 20/0/20 (quota 8388608) | match |
| e2-07 | 17/0/17 | 17/0/17 (quota 67108864) | match |
| e2-08 | 2MiB: 13/13 fail; 8MiB: 0/20 fail; 64MiB: 0/17 fail | 2MiB: 0/13 pass, 13/13 fail; 8MiB: 20/20 pass, 0/20 fail; 64MiB: 17/17 pass, 0/17 fail | match |
| e2-09 | 11 of 12 checks pass in every failing run | 13/13 failing runs fail only etcd-quota-write-burst-etcd1 (11 of 12 checks passing) | match |
| e2-10 | 6 options product 96 configurations of which 50 sampled | 96 configurations of which 50 sampled | match |
| e2-11 | seeds 3 and 40 shrink to identical minimal configuration | identical | match |
| e2-12 | 3 etcd nodes on one VLAN; memory 1024 MiB; disk 2048 MiB; heartbeat 100 ms; election timeout 1250 ms; snapshot count 10000; QUOTA_BACKEND_BYTES=2097152 (2 MiB) | final_config={"disk_size": 2048, "election_timeout_ms": 1250, "heartbeat_interval_ms": 100, "memory_size": 1024, "quota_backend_bytes": 2097152, "roles_etcd": 3, "snapshot_count": 10000} | match |
| e2-13 | 11 passed / 1 failed / 12 total | seed 3: 11/1/12; seed 40: 11/1/12 | match |
| e2-14 | identical final choice maps and resolved values | identical_minimal_config=True | match |
| e2-15 | 96 cells executed; 32 fail all at QUOTA_BACKEND_BYTES=2097152 (2 MiB); 64 pass | 96/96 cells with a property verdict; 32 fail (32 at 2097152); 64 pass; cells per quota {'2097152': 32, '67108864': 32, '8388608': 32} | match |

## RabbitMQ claims

| Claim | Expected | Observed | Verdict |
|---|---|---|---|
| r-01 | 5/5 properties pass; 50/50 publishes confirmed; 0 alarm samples (run 20260822-183835-...-seed-1-phase2-disk-positive, rev 998cae1) | 5/5 checks pass; 0 ambiguous publishes; 0 alarm samples | match |
| r-02 | nominal free-space target 100 MB (recorded post-fill approx 104.5 MB); alarm threshold 200 MB; 200 messages of 16 KiB; 1 s confirm timeout; 1.5x safety factor | confirm_timeout_ms=1000; disk_free_limit_mb=190; message_size_kib=16; nominal_free_target_mb=100; planned_messages=200; safety_factor_milli=1500 | match |
| r-03 | naive_capacity_sufficient=true (approx 104.5 MB > approx 4.69 MB naive req) while capacity_sufficient=false (104.5 MB < approx 204.69 MB strict req) | naive_capacity_sufficient=True; capacity_sufficient=False | match |
| r-04 | disk_free alarm activates during publish (14 alarm samples); all 200 publish attempts ambiguous with ConnectionBlockedTimeout | 14 alarm samples; 200 ambiguous publish attempts | match |
| r-05 | 22 of the unconfirmed messages were durably applied by the broker | 22 unconfirmed messages durably applied | match |
| r-06 | exactly one property fails: rabbitmq-disk-capacity-confirmation-contract; other four (incl. recovery and consistency) pass | 4/5 checks pass; failing: rabbitmq-disk-capacity-confirmation-contract | match |
| r-07 | 22 and 23 recovered messages respectively | cell-x reproduction recovered counts: 23 and 22 | within-tolerance |
| r-08 | pass 5/5 (both rows incl. rerun) | 2/2 positive rows: 5/5 checks, 0 ambiguous, 0 alarms | match |
| r-09 | fails capacity contract only | strict_sufficient=False; naive_sufficient=True; 200 ambiguous; 14 alarm samples | match |
| r-10 | 22 recovered (repro 1); 23 recovered (repro 2) | cell-x reproduction recovered counts: 23 and 22 | within-tolerance |
| r-11 | fails capacity contract only | 20 ambiguous publish attempts; 16 alarm samples | match |
| r-12 | 20/20 ambiguous; 16 alarm samples | second minimal execution: 4/5 checks, 20 ambiguous, 15 alarms (first execution: 16 alarms) | within-tolerance |
| r-13 | pass 2/2 (two properties); 11/11 tracked operations recover exactly once (run 20260822-190647-...-phase2-faildom-spread; rev 998cae1) | 2/2 properties; 11/11 operations exactly once; probe=confirmed; failing:  | match |
| r-14 | colocated: rabbitmq-failure-domain-exact-recovery passes (11/11 exactly once incl. ambiguous probe); rabbitmq-failure-domain-retains-quorum-availability fails with OuterCommandTimeout evidence | 1/2 properties; 11/11 operations exactly once; probe=ambiguous; failing: rabbitmq-failure-domain-retains-quorum-availability | match |
| r-15 | pass 2/2; 11/11 exactly once | 2/2 properties; 11/11 operations exactly once; probe=confirmed; failing:  | match |
| r-16 | fails availability contract; recovery passes | 1/2 properties; 11/11 operations exactly once; probe=ambiguous; failing: rabbitmq-failure-domain-retains-quorum-availability | match |
| r-17 | same verdict as colocated | 1/2 properties; 11/11 operations exactly once; probe=ambiguous; failing: rabbitmq-failure-domain-retains-quorum-availability | match |
| r-18 | all cells pass 3/3; every confirmed persistent publish survived one SIGKILL; zero ambiguous operations | 6/6 crash rows: pass 3/3, 50 confirmed, 0 ambiguous | match |
| r-19 | 0 ambiguous operations across all crash cells (negative observation) | ambiguous counts across 6 crash rows: during-publish=0,follower-repA=0,follower-repB=0,leader=0,retune-follower=0,retune-leader=0 | match |
| r-20 | pass 3/3 | 3/3 checks; 50 confirmed; 0 ambiguous; leader rabbit1->rabbit1 | match |
| r-21 | pass 3/3 | 3/3 checks; 50 confirmed; 0 ambiguous; leader rabbit1->rabbit1 | match |
| r-22 | pass 3/3 | 3/3 checks; 50 confirmed; 0 ambiguous; leader rabbit1->rabbit3 | within-tolerance |
| r-23 | pass 3/3 | 3/3 checks; 50 confirmed; 0 ambiguous; leader rabbit1->rabbit1 | match |
| r-24 | pass 3/3 | 3/3 checks; 50 confirmed; 0 ambiguous; leader rabbit1->rabbit1 | match |
| r-25 | pass 3/3 | 3/3 checks; 50 confirmed; 0 ambiguous; leader rabbit1->rabbit2 | match |
| r-26 | rest of cells single execution (existence claims only) | during-publish=2; follower=2; leader=1; retune-leader=1 | match |
| r-27 | 13 etcd failures in single quota class with deterministic split by QUOTA_BACKEND_BYTES; reproduced RabbitMQ counterexamples on designed cells | etcd v2 37/13 in class quota-backend-too-small-for-write-burst; 7 rabbitmq disk cell rows | informational-observed |

## Config spaces claims

| Claim | Expected | Observed | Verdict |
|---|---|---|---|
| c-01 | 16 options; 746496 combinations; 11 checks | kafka-cluster: space_size=746496 | match |
| c-02 | 6 options; 96 combinations; 12 checks | etcd-cluster: space_size=96 | match |
| c-03 | 8/3/4 options; 864/4/24 combinations; 5/2/3 checks | rabbitmq-disk=864; rabbitmq-faildom=4; rabbitmq-crash=24 | match |
| c-04 | product of per-dimension value counts = 746496 | kafka-cluster: space_size=746496; product of per-dimension value counts | match |

## Test suites claims

| Claim | Expected | Observed | Verdict |
|---|---|---|---|
| t-01 | 57 tests | python suite: ran=59, ok=True | within-tolerance |
| t-02 | 114 tests | nix suite: successful=114/114, ok=True | match |

## Discussion / informational claims

| Claim | Expected | Observed | Verdict |
|---|---|---|---|
| m-01 | all 32 cells visited (informational; historical) |  | informational-observed |
| m-02 | all 9 cells of the critical joint within a 162-cell space |  | informational-observed |
| m-03 | 22 of 24 cells |  | informational-observed |
| m-04 | 3-node Kafka; 3-node etcd; 3-broker RabbitMQ |  | informational-observed |
| m-05 | 80 distinct 64 KiB values (approx 5 MiB total) |  | informational-observed |
| m-06 | 1.5 MiB record with acks=all to 3-partition RF-3 topic; consumer must receive at least 1.5 MiB |  | informational-observed |
| m-07 | 500/500 runs passing all 15 checks (cache-reuse caveat) |  | informational-observed |
| m-08 | Kafka 13/37 of 50 with zero per-seed flips on re-execution; etcd v2 37/13 all quota class | kafka 13/37, flips=0; etcd v2 37/13, failure_class=quota-backend-too-small-for-write-burst | informational-observed |

## Execution accounting

| Group | Units | Seeds | Fresh | Cache replay | Wall total (s) | Compute hours | Peak RSS (MiB) | Space size |
|---|---|---|---|---|---|---|---|---|
| etcd-cluster | 198 | 50 | 204 | 0 | 18589.6 | 0.393747 | 1038.9 | 96 |
| etcd-cluster-v1 | 100 | 50 | 100 | 0 | 26809.6 | 0.194114 | 1036.6 | 64 |
| kafka-cluster | 104 | 50 | 127 | 0 | 23563.8 | 0.211719 | 1046.1 | 746496 |
| rabbitmq-crash | 6 | 1 | 6 | 0 | 567.727 | 0.0118194 | 1047.5 | 24 |
| rabbitmq-disk | 7 | 1 | 7 | 0 | 1157.26 | 0.0137722 | 1048.1 | 864 |
| rabbitmq-disk-serial | 4 | 1 | 4 | 0 | 497.239 | 0.00771944 | 1047.9 | 864 |
| rabbitmq-faildom | 3 | 1 | 3 | 0 | 273.313 | 0.00567778 | 1047.0 | 4 |
| test-suites | 2 | 0 | 0 | 0 | 1.742 | 0.000119444 | 70.2 |  |

| Totals | Units | Fresh | Cache replay | Wall total (s) | Compute hours |
|---|---|---|---|---|---|
| all groups | 424 | 451 | 0 | 71460.2 | 0.838689 |

| Resolution target | Space size | Seeds | Unique resolved | Duplicate rate |
|---|---|---|---|---|
| etcd-cluster | 96 | 50 | 40 | 0.2 |
| etcd-cluster-v1 | 64 | 50 | 34 | 0.32 |
| kafka-cluster | 746496 | 50 | 50 | 0 |
| rabbitmq-crash | 24 | 50 | 21 | 0.58 |
| rabbitmq-disk | 864 | 50 | 49 | 0.02 |
| rabbitmq-failure-domain | 4 | 50 | 4 | 0.92 |

## Discrepancies

None.

## Determinism (per-seed flips across repetitions)

| Entry | Repetitions present | Flips |
|---|---|---|
| etcd-v1-sweep | True | 0 |
| etcd-v2-sweep | True | 0 |
| kafka-sweep | True | 0 |
