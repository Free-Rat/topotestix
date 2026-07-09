# RabbitMQ First Targets

## Goal
Define the first deep-study targets for a RabbitMQ-based TopoTestix case study, in the recommended execution order.

---

## 1. Baseline quorum queue correctness

### Why first
This is the control case for the rest of the study. It establishes that the cluster and the test harness behave correctly under normal conditions before adding resource pressure or faults.

### Main idea
Run a 3-node RabbitMQ cluster with quorum queues and verify normal publish/consume behavior.

### Suggested knobs
- node count: 3
- quorum queue enabled
- durable vs non-durable messages
- publisher confirms on/off
- message count
- message size

### Suggested properties
- publisher-confirmed persistent messages are eventually consumable
- no phantom messages appear
- messages are not duplicated unless the client mode explicitly allows retry ambiguity
- cluster forms correctly and all nodes report healthy status

### What it gives the thesis
A clean baseline for later comparisons and a first demonstration that TopoTestix can express RabbitMQ correctness properties.

---

## 2. Disk-full / disk alarm

### Why second
This is one of RabbitMQ’s most natural and operationally relevant environment-sensitive failure modes.

### Main idea
Constrain disk space and drive the broker into low-space conditions while publishing persistent messages.

### Suggested knobs
- `virtualisation.diskSize`
- RabbitMQ `disk_free_limit`
- queue backlog size
- message size
- number of publishers
- data-dir placement

### Suggested faults
- fill the disk during runtime
- push the queue until disk alarms trigger
- free disk space and observe recovery

### Suggested properties
- disk alarms trigger under low-space conditions
- publishers block or fail clearly rather than succeeding silently
- confirmed messages are not silently lost
- after space is restored, the system recovers cleanly

### What it gives the thesis
A strong example of correctness depending on environment/resource state rather than only input data.

---

## 3. Network partition / quorum safety

### Why third
This gives the strongest classic distributed-systems story: majority/minority behavior and safety under partitions.

### Main idea
Partition a 3-node cluster and verify that quorum queues preserve safety.

### Suggested knobs
- partition shape: isolate 1 node vs isolate 2 nodes
- firewall rules
- packet delay / packet loss
- blocked AMQP ports vs blocked Erlang distribution ports
- heal timing

### Suggested faults
- one-way or two-way partitions
- transient partitions
- port-specific blocking

### Suggested properties
- minority partitions must not accept unsafe writes
- majority partition remains available
- after healing, the cluster converges
- no split-brain message history appears in quorum queues

### What it gives the thesis
A strong argument that environment-aware testing can expose cluster-topology-dependent correctness boundaries.

---

## 4. Memory pressure

### Why fourth
Memory pressure is easy to inject and highly realistic in production settings.

### Main idea
Reduce available memory and stress the cluster with queued messages and client activity.

### Suggested knobs
- `virtualisation.memorySize`
- swap on/off
- RabbitMQ `vm_memory_high_watermark`
- queue backlog size
- message size
- publisher concurrency

### Suggested faults
- sustained publish pressure under low memory
- force one node into OOM or near-OOM conditions
- restart after memory exhaustion

### Suggested properties
- memory alarms / flow control engage
- the broker degrades explicitly rather than corrupting state
- quorum queues recover safely after node restart
- confirmed-message safety is preserved when quorum assumptions hold

### What it gives the thesis
A realistic example of host-resource variation affecting distributed-system behavior.

---

## 5. Crash recovery

### Why fifth
This is high-value and literature-aligned, but more complex than the earlier targets.

### Main idea
Crash nodes at carefully chosen points relative to persistent-message publishing and recovery.

### Suggested knobs
- crash timing relative to publish and confirm
- one-node vs multi-node crash
- restart order
- durable queue settings
- message persistence mode

### Suggested faults
- kill a broker after publish but before confirm
- kill a broker after confirm
- hard shutdown / abrupt VM stop
- staggered restarts

### Suggested properties
- confirmed durable messages survive restart when quorum/durability assumptions hold
- unconfirmed messages are not incorrectly treated as committed
- cluster metadata remains recoverable
- the cluster returns to a healthy converged state after restart

### What it gives the thesis
A direct bridge to crash-consistency and durability literature, especially for environment-dependent persistence behavior.

---

## 6. DNS / hostname

### Why sixth
This is highly configuration-driven and useful, but less central than disk/quorum/memory/crash behavior.

### Main idea
Vary hostname and resolver setup to test RabbitMQ cluster formation and node identity assumptions.

### Suggested knobs
- short hostnames vs FQDNs
- `/etc/hosts`
- resolver search domains
- node-name conventions
- cluster peer addresses

### Suggested faults
- mismatched node names
- incomplete name-resolution setup
- ambiguous short-name resolution

### Suggested properties
- valid configurations cluster correctly
- invalid configurations fail clearly and reproducibly
- no accidental split cluster appears due to resolver mismatch
- management and client connectivity reflect the actual cluster state

### What it gives the thesis
A configuration-centric example showing that environment bugs are often about identity and resolution rather than application logic.

---

## Recommended execution order

1. Baseline quorum queue correctness
2. Disk-full / disk alarm
3. Network partition / quorum safety
4. Memory pressure
5. Crash recovery
6. DNS / hostname

---

## Why this order

- **Baseline first** to validate the harness and properties.
- **Disk-full second** because it is easy to trigger and highly likely to produce interesting, interpretable behavior.
- **Network partition third** because it gives the strongest distributed-systems correctness story.
- **Memory fourth** because it is realistic and operationally important.
- **Crash recovery fifth** because it is valuable but harder to stabilize.
- **DNS last** because it is configuration-rich, but slightly less central to the main durability/quorum narrative.

---

## Minimal first milestone

If only the first three targets are implemented initially, that is already enough for a strong first case-study slice:

1. baseline correctness
2. disk/resource sensitivity
3. partition/quorum safety

That combination already shows that TopoTestix explores both normal behavior and environment-dependent failure surfaces.
