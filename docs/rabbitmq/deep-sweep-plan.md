# Deep Sweep Plan — RabbitMQ Quorum Queues

## Goal
Use **RabbitMQ quorum queues** as the single deep case study for environment-aware testing.

## Why this SUT
RabbitMQ is the best candidate because it exposes many environment-sensitive failure surfaces in one system:

- **Filesystem semantics** — persistence, recovery, crash timing
- **Disk-full / quota / inode exhaustion** — disk alarms, blocked publishers, recovery behavior
- **libc / DNS differences** — hostname resolution and cluster formation
- **Permissions / MAC / capabilities** — data-dir access, service startup, TLS/key access
- **Memory pressure / swap / OOM** — alarms, flow control, node death under load
- **Network topology / MTU / firewall** — clustering, partitions, quorum availability

That makes it ideal for studying one software system under many environment axes.

## Thesis framing
> RabbitMQ demonstrates that correctness depends not only on message inputs, but on filesystem behavior, host limits, resolver setup, memory pressure, and cluster topology.

## Core properties to test

1. **Durable delivery**
   - Confirmed persistent messages should survive crash/restart when quorum is preserved.
2. **No phantom messages**
   - Messages should not appear unless they were published.
3. **Graceful degradation**
   - Under resource exhaustion or partial partitions, RabbitMQ should fail explicitly rather than silently corrupt state.
4. **Quorum safety**
   - Minority partitions must not accept writes to quorum queues.
5. **Recovery**
   - After faults are removed, the cluster should converge and resume normal operation.

## Deep-sweep axes

### A. Filesystem / durability axis
Vary:
- ext4 / xfs / btrfs / tmpfs (where practical)
- crash timing
- data-dir placement
- queue type and persistence settings

Faults:
- hard shutdown
- kill -9 of one or more nodes
- restart after partial writes

Properties:
- confirmed persistent messages survive
- cluster metadata remains recoverable

### B. Disk pressure axis
Vary:
- disk size / quota
- `disk_free_limit`
- message size
- queue backlog

Faults:
- fill disk
- exhaust inodes

Properties:
- disk alarms trigger
- publishers block or fail clearly
- no silent data loss

### C. DNS / resolver axis
Vary:
- `/etc/hosts`
- `/etc/resolv.conf`
- search domains
- short hostnames vs FQDNs

Properties:
- valid configs cluster correctly
- invalid configs fail cleanly
- no accidental split cluster from name-resolution mismatch

### D. Permissions / capability axis
Vary:
- root vs non-root
- data-dir ownership
- TLS key permissions
- capability drops
- MAC policy on/off if available

Properties:
- startup fails explicitly when access is insufficient
- no partial startup that looks healthy but is broken

### E. Memory pressure axis
Vary:
- cgroup memory caps
- swap on/off
- `vm_memory_high_watermark`
- queue backlog size

Faults:
- memory pressure during publish/consume
- OOM kill of one node

Properties:
- memory alarms / flow control engage
- quorum queues recover after node restart

### F. Network topology axis
Vary:
- partitions
- MTU
- firewall rules
- packet loss / delay
- blocked Erlang or AMQP ports

Properties:
- majority side remains available
- minority side cannot accept unsafe writes
- healed network converges

## NixOS module suitability

RabbitMQ is viable for real TopoTestix fuzzing, but the reason is **not** that the stock NixOS module exposes a large typed configuration surface.

The built-in NixOS module is fairly small. The important options are:

- `services.rabbitmq.enable`
- `services.rabbitmq.package`
- `services.rabbitmq.listenAddress`
- `services.rabbitmq.port`
- `services.rabbitmq.dataDir`
- `services.rabbitmq.unsafeCookie`
- `services.rabbitmq.configItems`
- `services.rabbitmq.config`
- `services.rabbitmq.plugins`
- `services.rabbitmq.pluginDirs`
- `services.rabbitmq.managementPlugin.enable`
- `services.rabbitmq.managementPlugin.port`

The upstream NixOS test at `/home/freerat/.nix-defexpr/channels_root/nixos/nixpkgs/nixos/tests/rabbitmq.nix` is only a single-node smoke test. It enables RabbitMQ, enables the management plugin, waits for the service, checks `rabbitmqctl status`, waits for port `15672`, and publishes one AMQP message. It is useful as a starting point, but it is not a clustered or adversarial test.

### Verdict

- **Stock NixOS module fuzzability:** medium
- **TopoTestix SUT with a thin custom wrapper:** good

The module gives two important escape hatches:

1. `services.rabbitmq.configItems` for `rabbitmq.conf` key-value settings.
2. `services.rabbitmq.config` for advanced Erlang-format nested settings.

Therefore, the right approach is not to fuzz only the stock `services.rabbitmq` options. Instead, define a dedicated TopoTestix target that exposes a curated, shrink-friendly fuzz surface and translates those generated choices into RabbitMQ config plus host/environment config.

Suggested target layout:

```text
targets/rabbitmq-cluster/topology.nix
targets/rabbitmq-cluster/config.nix
targets/rabbitmq-cluster/module.nix
targets/rabbitmq-cluster/properties.nix
```

### Recommended fuzz-surface design

Service-level RabbitMQ knobs, mostly through `configItems` / `config`:

- disk alarm threshold / `disk_free_limit` behavior
- memory alarm / `vm_memory_high_watermark` behavior
- listener address / AMQP port
- management plugin on/off
- cluster node names and Erlang cookie handling
- quorum queue settings and queue declaration parameters
- heartbeat / connection timeout settings
- partition-handling policy where applicable

Host-level NixOS/environment knobs:

- `virtualisation.memorySize`
- `virtualisation.diskSize`
- swap on/off
- data directory path and mount layout
- filesystem choice for RabbitMQ state, where practical
- hostname / domain / `/etc/hosts`
- resolver configuration / search domains
- firewall rules for AMQP, EPMD, and Erlang distribution ports
- data-dir ownership and permissions
- systemd service overrides such as file descriptor limits or sandboxing
- process crash / VM shutdown timing

### Axis-by-axis suitability

| Axis | Fit | Notes |
|---|---:|---|
| Filesystem semantics | Good | RabbitMQ persistence and quorum queues make crash/recovery behavior meaningful. |
| Disk-full / quota / inode exhaustion | Very good | RabbitMQ has explicit disk alarms and publisher blocking behavior. |
| DNS / resolver behavior | Good | Erlang distribution and clustering are hostname-sensitive. |
| glibc vs musl | Weak/medium | Plain NixOS is glibc-oriented; musl would need extra packaging/container work. |
| Permissions / capabilities | Good | Data dir, cookie, TLS material, and systemd restrictions are all testable. |
| Memory pressure / swap / OOM | Very good | RabbitMQ has memory alarms and flow control, plus observable failure/recovery behavior. |
| Network topology / MTU / firewall | Very good | Clustering and quorum queues expose meaningful majority/minority properties. |

Bottom line:

> RabbitMQ is good enough for serious TopoTestix fuzzing if treated as a custom cluster target. The NixOS module is thin, but `configItems`, `config`, and NixOS host-level controls provide enough surface for a deep environment-aware case study.

## Suggested experiment structure

### Target 1: Baseline quorum queue correctness
- 3-node cluster
- publish/consume roundtrip
- verify confirmed persistent delivery

### Target 2: Disk-full behavior
- small virtual disks
- growing queue backlog
- assert disk alarms and safe blocking

### Target 3: Crash consistency
- kill nodes after publish confirm
- restart and verify recovery

### Target 4: DNS sensitivity
- vary name resolution and cluster addresses
- verify startup/cluster formation

### Target 5: Memory pressure
- low memory caps
- assert graceful degradation and recovery

### Target 6: Network partition behavior
- isolate minority/majority sets
- verify quorum safety

## What this gives the thesis
This single SUT can support a strong argument that TopoTestix is not just testing inputs, but **searching environment space**. RabbitMQ is broad enough to show multiple bug classes, but focused enough to study deeply with a unified harness and a small set of properties.

## Recommended chapter headline
**Case Study: Environment-Aware Property-Based Testing of RabbitMQ Quorum Queues**
