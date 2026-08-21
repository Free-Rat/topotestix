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
operations and verifies confirmed IDs exactly once after recovery. This remains
a thesis candidate until both leader and follower cases run reproducibly.

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

## Initial smoke observations

These are implementation checks, not repeated thesis measurements:

- Disk seed 1 passed all five exact-history, capacity, and recovery properties.
- Spread failure-domain placement passed availability and exact recovery.
- Colocating `rabbit1` and `rabbit2` in the failed domain produced the intended
  counterexample: the sole survivor did not complete the confirmed publish
  within the test-driver budget, while exact recovery still passed.
- Abrupt follower crash preserved every confirmed message exactly once and
  replaced the broker PID, but the restarted follower did not return to the
  queue's `online` member set within 120 seconds. This is an unresolved recovery
  result, not a passing durability case.

The local evidence is under `.topotestix/runs-thesis-redesign/`. These runs must
be repeated with fresh builds and repository provenance before citation.
