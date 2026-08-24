# RabbitMQ Thesis Targets

This document is the implementation status for the redesigned RabbitMQ case
study. Empirical results are intentionally omitted until fresh VM executions
have been collected from the current code.

## Current thesis targets

### `rabbitmq-disk`

Production contract: the configured free-space reserve covers RabbitMQ's disk
alarm threshold and the planned consumer-outage backlog while confirmed durable
messages remain recoverable exactly once.

The target varies:

- per-node volume size;
- `disk_free_limit`;
- initial free-space reserve;
- backlog rate and consumer-outage duration;
- message size;
- publisher confirmation timeout;
- capacity safety factor.

The evidence records every operation ID and outcome (`confirmed`, `rejected`,
`timed_out`, or `ambiguous`), per-node disk telemetry, and every recovered
message ID. Underprovisioned cells can expose the client-visible ambiguity where
a publish exceeds its confirmation budget but later appears in the queue.

Status: **thesis target**. The capacity/confirmation contract was not
originally demonstrably falsifiable: the strict capacity model (broker alarm
threshold + outage backlog, safety-scaled) entails the SLO, so a contract
guarded by strict sufficiency was vacuous. Commit `761b053` exposed the weaker
naive (backlog-only) planning model alongside the strict model in the
contract's evidence, and the contract now fires when *either* model declares
capacity sufficient. The falsifiability gap was then closed with evidence:
a naive-sufficient / strict-insufficient cell fails exactly the capacity
contract (200/200 `ambiguous` `ConnectionBlockedTimeout` operations, 14 alarm
samples), and an all-minimum cell with the threshold at the lowest value above
the observed fill floor reproduces the same single-contract failure with a
≈160× smaller payload (see the matrix rows below).

### `rabbitmq-failure-domain`

Production contract: three quorum replicas placed in three independent failure
domains retain write availability after loss of any one declared domain.

The positive control spreads the three nodes across three zones. The failing
configuration places two replicas in one zone. The driver abruptly kills every
broker in the selected zone, attempts a confirmed write through a survivor,
restores the original services and data directories, and compares exact message
identities.

This models correlated failure, not a physically shared block device. A failing
colocated cell is the intended discoverable configuration counterexample.

### `rabbitmq-crash`

Production contract: every confirmed persistent message survives one abrupt
broker-process failure when quorum remains available.

The target observes the quorum queue leader, selects a leader or follower from
that state, kills the RabbitMQ service cgroup with `SIGKILL`, and restarts the
same service against its unchanged data directory. It records unique publish
operations and verifies confirmed IDs exactly once after recovery.

Status: **thesis target** (promoted from thesis candidate on 2026-08-22).
Evidence: follower reproductions (3), leader, during-publish (1), and
during-publish retunes (2) under
`.topotestix/runs-thesis-redesign/`, all 3/3 PASS with 50/50 confirmed
operations recovered exactly once; plus the durable cluster-rejoin finding
(section *Final cell matrix* below).

## Controls and prototypes

- `rabbitmq-cluster` is the harness baseline.
- `rabbitmq-partition`, `rabbitmq-memory`, and `rabbitmq-dns` remain prototypes.
- Property-only availability targets are negative-control oracle variants, not
  independent RabbitMQ scenarios.

## Required evaluation protocol

1. Run one positive and one failing/underprovisioned cell for each contract.
2. Force fresh Nix builds for every claimed independent repetition.
3. Reproduce each failure at least three times.
4. Retain resolved choices, operation history, telemetry, report, Git revision,
   and Nix store path.
5. Shrink each failure to the smallest violating configuration.
6. State separately what was confirmed, rejected, timed out, and ambiguous.

The historical `docs/empirical-rabbitmq-*.md` reports do not validate these
redesigned targets.

## Final cell matrix (2026-08-22, evidence in `.topotestix/runs-thesis-redesign/`)

Every run below carries `report.json`, `run.json` (gitHead, artifacts,
reproduceCommand), `choices.json`, `resolved.json`, `expr.nix`, logs, and the
materialized evidence payload. Git revision per run is in its `run.json`.

| Target | Cell | Run dir | Verdict |
|---|---|---|---|
| rabbitmq-crash | follower / before_publish (reproduction 1) | `20260822-173148-rabbitmq-crash-seed-1-phase1-crash-follower-smoke-2` | 3/3 PASS (gitHead `118a5ab`; `run.json` is backfilled, see note below) |
| rabbitmq-crash | follower / before_publish (reproduction 2) | `20260822-175757-rabbitmq-crash-seed-1-phase2-crash-follower-repA` | 3/3 PASS |
| rabbitmq-crash | follower / before_publish (reproduction 3) | `20260822-180022-rabbitmq-crash-seed-1-phase2-crash-follower-repB` | 3/3 PASS |
| rabbitmq-crash | leader / before_publish | `20260822-185806-rabbitmq-crash-seed-1-phase2-crash-leader` | 3/3 PASS (leader transferred rabbit1 → rabbit2) |
| rabbitmq-crash | during_publish / follower (kill after batch) | `20260822-190037-rabbitmq-crash-seed-1-phase2-crash-during` | 3/3 PASS, 0 ambiguous ops |
| rabbitmq-crash | during_publish / follower, delay 10 s, 50 ops | `20260822-202330-rabbitmq-crash-seed-1-phase3-crash-during-retune` | 3/3 PASS, 0 ambiguous ops |
| rabbitmq-crash | during_publish / leader, delay 10 s, 50 ops | `20260822-202536-rabbitmq-crash-seed-1-phase3-crash-during-retune-2` | 3/3 PASS, 0 ambiguous ops |
| rabbitmq-disk | positive control (seed-1 cell, 500 MB free) | `20260822-183835-rabbitmq-disk-seed-1-phase2-disk-positive` | 5/5 PASS (50/50 confirmed, 0 alarms) |
| rabbitmq-disk | positive control re-run post-`761b053` | `20260822-224837-rabbitmq-disk-seed-1-phase3-disk-positive-v2` | 5/5 PASS (50/50 confirmed, 0 alarms; both sufficiency flags true) |
| rabbitmq-disk | counterexample: 100 MB free / 200 MB alarm threshold / 200 × 16 KiB (naive-sufficient, strict-insufficient) | `20260822-225112-rabbitmq-disk-seed-1-phase3-disk-counterexample` | `capacity-confirmation-contract` FAILS (intended; `naive_capacity_sufficient=true`, `capacity_sufficient=false`, 200/200 `ambiguous` `ConnectionBlockedTimeout`, 14 alarm samples); 4 other properties PASS |
| rabbitmq-disk | counterexample, reproduction 1 (identical cell) | `20260823-104643-rabbitmq-disk-seed-1-phase3-disk-counterexample-repA` | identical signature (200/200 `ambiguous` `ConnectionBlockedTimeout`, 14 alarm samples, 22 recovered); same single-contract FAILURE |
| rabbitmq-disk | counterexample, reproduction 2 (identical cell) | `20260823-105452-rabbitmq-disk-seed-1-phase3-disk-counterexample-repB` | identical signature (23 recovered); same single-contract FAILURE |
| rabbitmq-disk | minimal cell: all dimensions at their minimum, threshold 200 MB (lowest value above the ≈104.5 MB fill floor) | `20260823-001413-rabbitmq-disk-seed-1-phase3-disk-counterexample-min` | same single-contract failure, 20/20 `ambiguous`, 16 alarm samples, 20 × 1 KiB payload (incidental duplicate repro: `20260822-231356-…-phase3-disk-counterexample-min`, identical verdict) |
| rabbitmq-failure-domain | spread placement (positive) | `20260822-190647-rabbitmq-failure-domain-seed-1-phase2-faildom-spread` | 2/2 PASS (probe confirmed, 11/11 recovered) |
| rabbitmq-failure-domain | colocated placement (counterexample 1) | `20260822-190921-rabbitmq-failure-domain-seed-1-phase2-faildom-colocA` | `retains-quorum-availability` FAILS (intended), `exact-recovery` PASSES |
| rabbitmq-failure-domain | colocated placement (counterexample 2) | `20260822-191139-rabbitmq-failure-domain-seed-1-phase2-faildom-colocB` | same (intended) |

Notes:

- All cited matrix runs except `phase1-crash-follower-smoke-2` and the
  `phase3-disk-*`
  runs are on git revision
  `998cae1` ("Orchestrator: retain evidence payloads and record git
  provenance") (see the next two bullets for those exceptions; the uncited
  debug run `phase1-crash-follower-smoke` is on `118a5ab`).
- The four `phase3-disk-*` run dirs (positive-v2, counterexample,
  counterexample-min ×2) are on `761b053`
  ("Disk target: expose the naive-capacity counterexample
  contract"), which amends the contract after the Phase-2 runs; the two
  identical-cell counterexample reproductions (repA, repB) are on
  `70a59ad` ("Document the complete RabbitMQ thesis case study"), a
  documentation-only commit whose target code is identical to `761b053`. The
  disk positive control was re-run on `761b053` (positive-v2) so every cited
disk verdict has a post-amendment provenance.
- `phase1-crash-follower-smoke-2` is on `118a5ab`: a Phase-1 orchestrator
  regression (PermissionError on the store-copied `report.json`) left
  `run.json` unwritten, and it was backfilled later; its `crash-results.json`
  carries the same evidence fields and its verdict is 3/3 PASS. Thesis
  citations prefer the four `998cae1` crash reproductions (repA, repB, leader,
  during); the smoke-2 run is cited with its provenance caveat where used.

This matrix supersedes the historical "Initial smoke observations" section,
which has been removed.
