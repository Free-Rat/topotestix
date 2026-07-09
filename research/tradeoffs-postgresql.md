# Research: PostgreSQL streaming-replication target tradeoffs

## Summary
For a first thesis-grade PostgreSQL target, the best default is **1 primary + 1 standby**. It is the smallest setup that still exposes control-plane misconfigurations, lag/durability issues, sync-commit stalls, slot retention problems, and standby read-conflict behavior; a second standby mostly adds cascade/timeline-switch coverage at the cost of more boot time and flakiness. PostgreSQL’s native docs and test suite already cover these behaviors directly, so the target can stay close to vanilla nixpkgs and still produce citable failures. [PostgreSQL docs](https://www.postgresql.org/docs/current/warm-standby.html) [PG tests](https://github.com/postgres/postgres/blob/e18b0cb7/src/test/recovery/t/004_timeline_switch.pl)

## Findings
1. **Topology: choose 1+1 for v1; defer 1+2 and witnesses.**
   - **Recommended base:** 1 primary + 1 standby. It is enough to test streaming, read-only standby behavior, sync commit, lag, promotion, and WAL retention. [Docs](https://www.postgresql.org/docs/current/warm-standby.html)
   - **Why not 1+2 initially:** the second standby mainly buys cascading replication and timeline-switch behavior, which is real but topology-heavy and slower to boot; it is best as v2 once 1+1 is stable. PostgreSQL already has a dedicated cascading-replication test for timeline switches. [PG test](https://github.com/postgres/postgres/blob/e18b0cb7/src/test/recovery/t/004_timeline_switch.pl)
   - **Why not a witness/arbiter:** vanilla PostgreSQL streaming replication has no witness concept; adding one means moving into orchestration-manager territory (Patroni/repmgr/DCS), which is a different thesis target. [Patroni tests](https://github.com/patroni/patroni/blob/6e2e2392/features/basic_replication.feature)

2. **Fuzz surface: keep v1 small and high-signal; push archival/delay knobs to v2.**

   | Option | Verdict | Why |
   |---|---|---|
   | `wal_level` | **v2** | `logical` adds surface area you do not need for physical streaming; keep v1 on `replica`. [Docs](https://www.postgresql.org/docs/18/continuous-archiving.html) |
   | `max_wal_senders` | **initial** | Directly gates replication connections; low values fail cleanly. [Docs](https://www.postgresql.org/docs/current/warm-standby.html) |
   | `max_replication_slots` | **initial** | Cleanly exercises slot provisioning vs. too-small cluster config. [Docs](https://www.postgresql.org/docs/current/warm-standby.html) |
   | `synchronous_standby_names` | **initial** | Core sync/async fork; use empty vs specific standby name, or `ANY 1`/`FIRST 1` for multi-standby setups. `ALL 1` is not PostgreSQL syntax. [Docs](https://www.postgresql.org/docs/current/runtime-config-replication.html) |
   | `synchronous_commit` | **initial** | Gives distinct durability/latency modes (`off`, `local`, `on`, `remote_write`, `remote_apply`). [Docs](https://www.postgresql.org/docs/current/runtime-config-replication.html) |
   | `wal_keep_size` | **initial** | Small values surface catch-up loss when no slot/archive protects WAL. [Docs](https://www.postgresql.org/docs/current/warm-standby.html) |
   | `archive_mode` | **v2** | Valuable for PITR/data-loss classes, but archiving adds async failure modes and host-path assumptions. [Docs](https://www.postgresql.org/docs/current/continuous-archiving.html) |
   | `archive_command` (working/broken) | **v2** | Broken command is a good negative, but only after archive plumbing is stable. [Docs](https://www.postgresql.org/docs/current/continuous-archiving.html) |
   | `hot_standby` | **initial** | Needed to distinguish read-only standby vs recovery-disabled standby; clean pass/fail. [Docs](https://www.postgresql.org/docs/18/hot-standby.html) |
   | `hot_standby_feedback` | **v2** | Mostly matters for recovery-conflict/bloat tradeoffs; harder to assert cleanly. [Docs](https://www.postgresql.org/docs/18/hot-standby.html) |
   | `max_connections` | **v2** | Can expose shared-memory sizing issues, but it is a heavier startup-time lever. [Docs](https://www.postgresql.org/docs/18/hot-standby.html) |
   | `shared_buffers` | **initial** | Good resource-exhaustion knob; low-memory VMs make it a useful OOM trigger. [Docs](https://www.postgresql.org/docs/18/hot-standby.html) |
   | `effective_cache_size` | **skip** | Mostly planner tuning; weak failure signal. |
   | `primary_slot_name` | **initial** | Directly decides whether WAL is retained for the standby; high-value failure class. [Docs](https://www.postgresql.org/docs/current/warm-standby.html) |
   | `recovery_min_apply_delay` | **v2** | Great for delayed-replay/PITR semantics, but more timing-sensitive in QEMU. [Docs](https://www.postgresql.org/docs/current/runtime-config-replication.html) |
   | `virtualisation.memorySize` | **initial** | Strongest resource-exhaustion lever with a clear pass/fail signal. [NixOS module](https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/services/databases/postgresql.nix) |
   | `virtualisation.diskSize` | **v2** | Useful for WAL/archive fill-up, but it can be noisy and slow. |

   **Suggested v1 set (6–10 knobs):** `max_wal_senders`, `max_replication_slots`, `synchronous_standby_names`, `synchronous_commit`, `wal_keep_size`, `primary_slot_name`, `hot_standby`, `shared_buffers`, `virtualisation.memorySize`.

   **Aggressive v2 set:** add `wal_level=logical`, `archive_mode`, `archive_command`, `hot_standby_feedback`, `max_connections`, `recovery_min_apply_delay`, `virtualisation.diskSize`.

3. **Properties: prefer tolerant “eventually visible / no data loss” checks over strict latency bounds.**
   NixOS VM boots and QEMU clocks vary, so 1-second visibility claims are too brittle; use bounded waiting plus explicit state queries. The PostgreSQL test suite itself tends to do this (wait for catch-up, then assert content or timeline behavior). [PG tests](https://github.com/postgres/postgres/blob/e18b0cb7/src/test/recovery/t/004_timeline_switch.pl) [PG tests](https://github.com/postgres/postgres/blob/f9562b95/src/test/recovery/t/045_archive_restartpoint.pl)

   | Property | Query / check | Why it is worth v1 | Expected cost / risk |
   |---|---|---|---|
   | Connectivity / health | `SELECT 1`; `pg_is_in_recovery()`; `systemctl is-active postgresql` | Cheap smoke gate; catches startup and crash-loop failures. [Docs](https://www.postgresql.org/docs/18/functions-admin.html) | High pass rate, low cost, low flake |
   | Role partition | Primary accepts `INSERT`; standby rejects writes (or is read-only) | Confirms actual primary/standby split, not just service liveness. [PG test](https://github.com/postgres/postgres/blob/207cb2ab/src/test/recovery/t/001_stream_rep.pl) | High pass rate, low cost, low flake |
   | Data plane | `INSERT` on primary, then `SELECT` same row on standby | Surfaces “control plane works, data doesn’t” bugs. [Patroni feature](https://github.com/patroni/patroni/blob/6e2e2392/features/basic_replication.feature) | High/medium pass rate, medium wait, medium flake |
   | Replica lag | `pg_current_wal_lsn()` vs `pg_last_wal_replay_lsn()` (or replay timestamp) | Detects stalled replay / lag build-up. [Docs](https://www.postgresql.org/docs/18/functions-admin.html) [Docs](https://www.postgresql.org/docs/18/warm-standby.html) | Medium cost, medium flake |
   | Slot health | `SELECT slot_name, active, restart_lsn FROM pg_replication_slots` | Directly checks slot setup and retention path. [Docs](https://www.postgresql.org/docs/18/view-pg-replication-slots.html) | Low/medium cost, low flake |
   | Sync-commit behavior | Set `synchronous_standby_names`, kill standby, run `INSERT` with timeout | Catches silent durability regressions / commit hangs. [Docs](https://www.postgresql.org/docs/current/runtime-config-replication.html) [Patroni issue class](https://github.com/patroni/patroni/issues/3468) | Medium cost, medium flake |
   | WAL retention / catch-up loss | Stop standby, generate WAL, restart and assert catch-up or expected failure mode | Very thesis-friendly negative result: “standby needed a new base backup.” [Docs](https://www.postgresql.org/docs/current/warm-standby.html) [pgBackRest issue class](https://github.com/pgbackrest/pgbackrest/issues/2474) | Medium/high cost, medium/high flake |

   **V1 priority order:** connectivity → role partition → data plane → slot health → lag → sync-commit. Add failover/promotion only after those are green.

4. **Failure taxonomy: use 4–5 classes, not one giant “replication failed.”**
   - **Resource exhaustion** — OOM, disk-full, `pg_wal` fill, startup loops. Real class: backup/archiver helpers or WAL directories exhaust resources and stop progress. [Docs](https://www.postgresql.org/docs/current/continuous-archiving.html) [NixOS issue class](https://github.com/NixOS/nixpkgs/issues/385603)
   - **Replication misconfiguration** — bad `pg_hba.conf`, too-small `max_wal_senders`/`max_replication_slots`, wrong `primary_conninfo`, wrong `synchronous_standby_names`. [Docs](https://www.postgresql.org/docs/current/warm-standby.html) [NixOS module](https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/services/databases/postgresql.nix)
   - **Sync-commit liveness stall** — standby disappears but commits wait or hang instead of failing clearly. Real class: stale synchronous-standby tracking. [Patroni issue](https://github.com/patroni/patroni/issues/3468)
   - **WAL retention / catch-up loss** — standby falls behind, WAL is recycled, and a new base backup is needed. [Docs](https://www.postgresql.org/docs/current/warm-standby.html) [pgBackRest issue class](https://github.com/pgbackrest/pgbackrest/issues/2474)
   - **Recovery conflict / read cancellation** — hot standby queries canceled by VACUUM/DDL/replay conflicts; useful for thesis discussion even when expected. [Docs](https://www.postgresql.org/docs/18/hot-standby.html)

5. **NixOS/PostgreSQL sharp edges to plan around.**
   - **`postgresql.service` starts after `network.target`, not a stronger readiness target.** In tests, wait for the port / readiness explicitly; do not assume the unit is ready just because the VM booted. [NixOS module](https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/services/databases/postgresql.nix)
   - **`postgresql-setup` historically assumed a writable primary and could hang on standby bootstraps.** The module now skips setup when `standby.signal` exists, so standbys need a dedicated bootstrap path. [NixOS PR](https://github.com/NixOS/nixpkgs/pull/469863)
   - **`pg_hba.conf` is generated from `services.postgresql.authentication`.** Replication auth must be inserted declaratively; a bad fragment can override the defaults or block the standby entirely. [NixOS module](https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/services/databases/postgresql.nix)
   - **PG12+ uses `standby.signal`/`recovery.signal`; `recovery.conf` is gone.** Use the signal file + `primary_conninfo`/`restore_command` path, not the old file. [NixOS module](https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/services/databases/postgresql.nix) [Docs](https://www.postgresql.org/docs/current/warm-standby.html)
   - **Archive helpers run as the postgres user in a hardened systemd sandbox.** PATH/syscall-filter issues can break `archive_command` even when the command itself is fine. [NixOS issue class](https://github.com/NixOS/nixpkgs/issues/385603) [Discourse](https://discourse.nixos.org/t/grant-postgres-user-access-to-path/48301)

6. **Time and complexity estimate: v1 should be a small multi-day task, not a refactor project.**
   The PostgreSQL target has since been implemented and swept; see [`experiments/postgresql/`](../experiments/postgresql/) for the empirical results. The code itself was much less invasive than Kafka because PostgreSQL already has a first-class NixOS module and standard streaming-replication commands.

   **Practical v1 estimate:**
   - skeleton topology + module + bootstrap: **0.5–1 day**
   - smoke test + one green property: **0.5 day**
   - add 4–6 more properties and stabilize waits: **1–2 days**
   - first 3–10 seed sweep + shrink fixes: **background time, ~1 day wall clock**

   **Recommended phase order:** skeleton → smoke → connectivity/role property → data-plane + lag + slot + sync-commit → optional failover/timeline or archive/PITR → sweep.

## Sources
- Kept: PostgreSQL 18/Current docs (warm standby, replication, hot standby, continuous archiving, functions admin, replication slots) — primary semantics and query APIs.
- Kept: NixOS `services.postgresql` module source — exact module behavior, auth generation, startup ordering, `standby.signal` handling.
- Kept: PostgreSQL TAP tests `001_stream_rep.pl`, `004_timeline_switch.pl`, `035_standby_logical_decoding.pl`, `040_standby_failover_slots_sync.pl`, `045_archive_restartpoint.pl` — realistic assertions for replication, promotion, slots, and archive recovery.
- Kept: Patroni `features/basic_replication.feature` and `tests/test_sync.py` — real-world sync and failover assertions.
- Kept: NixOS PR/issue threads on standby setup and syscall-filter/archive pitfalls — module-specific sharp edges.
- Dropped: NixOS wiki / generic blog posts — useful context, but not authoritative enough for the thesis brief.
- Dropped: SEO-style PostgreSQL overview pages — redundant with upstream docs.

## Gaps
- I could not inspect the exact git history/commit timings from this environment, so the time estimate was inferred from the work plan and current artifact state at time of writing rather than precise log chronology. The plan has since been completed and the estimates were broadly validated by the actual PostgreSQL sweep.
- I did not validate a concrete NixOS test harness for `archive_mode`/`restore_command` end-to-end; that should be prototyped only after the 1+1 streaming-only smoke path is stable.
- I did not benchmark actual QEMU boot/runtime for your host; the pass-rate and flakiness estimates are qualitative, not measured.
