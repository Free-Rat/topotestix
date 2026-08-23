# RabbitMQ Evaluation Audit

> This audit describes the pre-redesign implementation. The repository was
> subsequently changed according to its recommendations. Current target status
> and initial smoke observations are in `docs/rabbitmq/thesis-targets.md`.

Date: 2026-08-21
Baseline revision: `ae46abe923b9d6b892fe6cbbc4a4195a951907b6`

## Executive verdict

The current RabbitMQ suite is not ready to be presented as evidence of crash
consistency, quorum safety, or exact message preservation under resource
pressure. It is useful as a prototype of environment-aware testing, and the
disk experiment contains one strong operational observation, but the reports
currently claim more than their oracles establish.

The best thesis direction is to express a concrete production contract, vary
the environment that contract assumes, and preserve the complete history of
client operations and broker observations. A failing case should identify the
smallest configuration that invalidates the contract and show a reproducible,
externally visible consequence.

## Changes since the baseline commit

The worktree added five canonical targets:

- `rabbitmq-disk`
- `rabbitmq-partition`
- `rabbitmq-memory`
- `rabbitmq-crash`
- `rabbitmq-dns`

It also added three paired negative controls:

- `rabbitmq-disk-availability`
- `rabbitmq-partition-availability`
- `rabbitmq-dns-contract`

Supporting changes added expected-failure classifications, sweep classification
counts, dotted Nix attribute handling in the shrinker, and six empirical reports.
The implementation grew by roughly 5,000 tracked lines before counting the three
untracked negative-control property files.

## Target verdicts

| Target | What it currently demonstrates | Verdict |
| --- | --- | --- |
| Baseline | A three-node quorum queue can perform a small publish/consume smoke test | Keep as control; narrow exactly-once and repetition claims |
| Disk | A cluster can be put under filesystem pressure, recover space, and retain the expected message count in observed runs | Most promising; rerun and strengthen identity/alarm checks |
| Partition | Endpoint outcomes under unverified `iptables` cuts and eventual membership-name visibility after healing | Not yet evidence of quorum-history safety |
| Memory | Cluster boot and a small serial workload under several memory settings | Prototype only; pressure and alarm oracle are weak |
| Crash | Graceful shutdown, reset, and rejoin of a non-publishing follower | Not a crash test; rename or replace |
| DNS | Cluster behavior under symmetric static `/etc/hosts` corruption | Presentable only as host-file identity misconfiguration |

## Strongest observed result

The aggressive disk negative control produced the suite's most useful tactile
observation:

1. All nodes were filled to approximately 10 MB free with a configured 200 MB
   disk threshold.
2. A publish through `rabbit1` did not receive confirmation before the client's
   blocked-connection timeout.
3. The later queue count was 201 although only 200 messages had been confirmed
   before pressure.

This is not evidence of message loss or a RabbitMQ defect. It is evidence of an
ambiguous client-visible outcome: the write may commit even though the publisher
does not receive its confirmation within its availability budget. That is a
realistic production concern and a strong thesis scenario if reproduced and
measured explicitly.

## Principal validity problems

### Cached repetitions

Repeated seeds often resolve to identical Nix derivations. Several empirical
reports count cached derivation reuse as an independent RabbitMQ execution.
Future reports must separately state requested seeds, distinct configurations,
VM executions, cache hits, and independent reruns.

### Count-only safety checks

Disk, memory, and crash properties generally compare message counts. A loss and
a duplicate can cancel out. Every operation needs a unique ID and the final
oracle must compare exact sets or multisets, with confirmed, rejected, and
ambiguous operations classified separately.

### Weak health checks

Grepping `cluster_status` for three node names proves only that names appear in
the output. It does not prove that all members are running, connected, or that
the quorum queue replicas are healthy and synchronized.

### Crash semantics

`rabbitmq-crash` uses `rabbitmqctl stop_app`, then resets and rejoins the node.
No process or VM is killed while a publish is in flight, the likely leader is
not targeted, and the restarted node does not recover from its original local
state. Claims about crash consistency or the publish/confirm crash window are
unsupported.

### Partition semantics

The no-split-brain property checks uniqueness only among messages that happen to
be observed. It can pass with missing confirmed writes or even an empty queue.
The one-way network model is not verified, command statuses were not retained in
the original evidence, and the heal delay occurs after writes have completed.

### Memory semantics

The alarm helper ignores the diagnostic command's exit status and does not
distinguish memory alarms from other local alarms. The workload is serial and at
most about 8 MB of message bodies, with no concurrent pressure, OOM, swap, or
restart scenario.

### DNS scope

The target varies one symmetric `/etc/hosts` fragment. It does not exercise DNS
servers, TTLs, search domains, short names versus FQDNs, or asymmetric resolver
views. Broken modes also encode the expected conclusion directly and accept a
broad range of failures.

## Recommended thesis-grade scenarios

### 1. Disk-capacity planning contract

Production assumption: every RabbitMQ data volume reserves enough headroom for
the configured alarm threshold and the largest expected quorum backlog.

Configuration model:

- per-node data-volume size and placement;
- `disk_free_limit`;
- initial disk utilization;
- backlog rate, message size, and consumer outage duration;
- publisher confirmation timeout.

Failure evidence:

- timestamp every publish attempt and confirmation;
- capture per-node free space and alarms over time;
- classify confirmed, rejected, timed out, and ambiguous operations;
- restore space and compare exact message IDs;
- shrink to the smallest headroom/backlog combination that violates the
  confirmation-latency contract.

This should be the primary case study.

### 2. Failure-domain placement contract

Production assumption: three quorum replicas placed on three declared failure
domains tolerate loss of any one domain.

Configuration model:

- node-to-disk or node-to-zone placement;
- shared versus independent backing volumes;
- queue replica placement;
- one-domain outage.

Failure evidence:

- model a plausible but incorrect placement where two nodes share one volume or
  failure domain;
- remove that domain;
- show that the nominal three-node cluster loses quorum or its availability SLO;
- contrast it with the correctly distributed placement.

This directly tests a configuration assumption rather than rediscovering a
known quorum rule.

### 3. Confirm-before-crash durability contract

Production assumption: a confirmed persistent message survives one abrupt
broker or VM failure when quorum assumptions hold.

Configuration model:

- leader versus follower failure;
- process kill versus VM power-off;
- crash timing before, during, and after confirmation;
- restart without reset;
- durable versus transient message mode.

Failure evidence:

- use unique operation IDs and a client-side history;
- trigger a real `SIGKILL` or VM shutdown;
- query queue leader and members before the fault;
- preserve and restart the node's original data directory;
- verify every confirmed operation exactly once and classify uncertain writes.

### 4. Resolver-view consistency contract

Production assumption: every cluster node resolves every RabbitMQ node name to
the same stable identity.

Configuration model:

- per-node resolver views rather than one shared host file;
- short names versus FQDNs and long-node-name mode;
- stale records, search domains, and transient resolver failure.

Failure evidence:

- show the resolution matrix from each node;
- record exact join diagnostics;
- detect singleton or split clusters precisely;
- distinguish configuration rejection from harness or command failure.

## Evidence policy

No current pass total should be quoted as an independent repetition count.
Results produced before the corrected disk alarm parser and result schemas must
be labeled historical and must not be attached to the current implementation.
The canonical reports under `docs/empirical-rabbitmq-*.md` require revision
before thesis use.

At minimum, each final experiment should include:

- exact repository and lock-file revisions;
- complete forced choices and resolved configuration;
- cache-hit versus actual-execution status;
- three independent reproductions of every failure;
- exact client-operation history and broker telemetry;
- a positive control and a negative control;
- a minimized failing configuration;
- a statement of what the oracle does and does not prove.

## Cleanup performed during this audit

- Expected failures now classify only deliberate `AssertionError` contract
  violations; parsing, I/O, and programming errors remain failures.
- Unknown and unexpected statuses now contribute to failed report counts.
- Disk and partition drivers retain process statuses for client attempts.
- The disk availability expectation now uses cluster-wide observed alarms.
- Dotted RabbitMQ Nix keys have regression tests, and ambiguous path encodings
  are rejected.
- Scratch scripts, agent handoff notes, a backup driver, and a stale HTML status
  snapshot were removed.

Python unit tests and Nix unit tests pass after these changes. RabbitMQ VM tests
were not rerun during the audit, so the changed disk and negative-control oracles
have no fresh empirical result yet.

## Closure (2026-08-22)

The gap items in the evidence policy above were closed on git revisions
`998cae1` ("Orchestrator: retain evidence payloads and record git
provenance") and `761b053` ("Disk target: expose the naive-capacity
counterexample contract"), with evidence under
`.topotestix/runs-thesis-redesign/`:

- **Exact repository revision**: every retained run dir carries `run.json`
  with `gitHead`, `artifacts`, and `reproduceCommand`; eleven thesis runs
  exist on `998cae1`, the four `phase3-disk-*` run dirs (positive-v2,
  counterexample, counterexample-min ×2) are on `761b053`, plus
  the whitelisted `phase1-crash-follower-smoke-2`
  on `118a5ab` (backfilled `run.json`, provenance caveat documented in
  `docs/rabbitmq/thesis-targets.md`).
- **Complete forced choices and resolved configuration**: every run dir
  carries `choices.json` and `resolved.json` (and `expr.nix`, `target.json`,
  `stdout/stderr.log`, `result`).
- **Cache hit vs. actual execution**: Phase-2 cells were run as fresh
  orchestrator invocations against a clean committed tree; the materialized
  run dirs (one per execution, unique name and timestamp) are the cited
  evidence rather than aggregated cache statistics.
- **Three independent reproductions of every failure**: the colocated
  failure-domain counterexample has two `998cae1` reproductions
  (`20260822-190921-…-phase2-faildom-colocA`,
  `20260822-191139-…-phase2-faildom-colocB`) plus the pre-HEAD
  `20260821-125835-…-thesis-domain-colocated-counterexample-2`; the crash
  contract has four `998cae1` reproductions (repA, repB, leader, during)
  and the during cell was additionally retuned twice
  (delay 10 s, 50 ops, follower and leader) — all 3/3 PASS with 0 ambiguous
  operations.
- **Exact client-operation history and broker telemetry**: payloads
  `crash-results.json`, `disk-results.json`,
  `failure-domain-results.json` record per-operation outcome
  (`confirmed`/`rejected`/`timed_out`/`ambiguous`), per-node disk telemetry
  phases, and exact recovered message identities.
- **Positive and negative controls**: failure-domain (spread vs. colocated),
  crash (follower, leader, during), and disk positive control (5/5 PASS,
  50/50 confirmed, 0 alarms, re-verified on `761b053` as
  `20260822-224837-…-phase3-disk-positive-v2`). The disk counterexample was
  achieved by Option A of the T1 design decision: commit `761b053` exposed
  the naive (backlog-only) capacity model alongside the strict model and let
  the contract fire when either declares capacity sufficient; a
  naive-sufficient / strict-insufficient cell then fails exactly the capacity
  contract (`.topotestix/runs-thesis-redesign/20260822-225112-…-phase3-disk-
counterexample`: 200/200 `ambiguous` `ConnectionBlockedTimeout` operations,
  14 alarm samples, 4 other properties PASS).
- **Minimized failing configuration**: the colocated cell is minimal by
  construction (it differs from the passing spread control in exactly one
  configuration dimension, replica placement, per the two cells'
  `choices.json`); the crash during cell varies a single timing dimension.
  Disk: an all-minimum cell — every dimension at its smallest value with the
  alarm threshold at the lowest option above the observed ≈104.5 MB fill
  floor — reproduces the same single-contract failure at a 20 × 1 KiB
  payload (`.topotestix/runs-thesis-redesign/20260823-001413-…-phase3-disk-
counterexample-min`), with an accidental duplicate reproduction
  (`20260822-231356-…-phase3-disk-counterexample-min`) showing the identical
  verdict. The threshold dimension cannot shrink further because the
  available free-space floor sits above the 100 MB option; that bound is
  part of the result, not a residual gap.
- **What the oracle does and does not prove**: stated per contract in the
  cell matrix and the thesis chapter evaluation section; in particular
  `rabbitmq-failure-domain` models a declared zone outage, not a shared
  block device, and the disk oracle bounds only the confirmation SLO for
  the declared backlog (it does not model I/O saturation beyond the
  alarm).
