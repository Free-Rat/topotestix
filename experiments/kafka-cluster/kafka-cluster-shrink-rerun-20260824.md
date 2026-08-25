# Kafka cluster shrink rerun — 2026-08-24 (draft evidence notes)

- **HEAD:** `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` (`git status` clean for tracked files; only untracked HANDOFF/PROMPT files present)
- **Date:** 2026-08-24 (all timestamps below UTC, from per-run `run.json`)
- **Purpose:** rerun the June Kafka shrinker experiments against HEAD to check whether (a) dotted-key config-choice overrides now reach the NixOS module end-to-end (June attempt died with a build error), and (b) whether the seed-9 minimal counterexample still collapses `RecordBatchTooLargeException` into `RecordTooLargeException`.

## Method

- CLI: `nix develop -c python3 -m topotestix.cli orchestrator <run|shrink> ...` (no system python).
- Override key format verified from source before running:
  - Role key is the topology role name, here `kafka` (`targets/kafka-cluster/topology.nix`: `roles.kafka = [ 3 ]`).
  - Paths are target-relative dotted paths **with a leading dot**, mapped to a **choice-list index**, e.g. `.services.apache-kafka.settings.log.segment.bytes = 0`. The shrinker's `findBestMatch`/`setValueByPath` (`lib/shrinker.nix`) resolves attribute names containing dots, and index 0 is the minimal list element (`shrinker.nix:valueAtChecked`).
  - Service name is `apache-kafka`; settings live under `services.apache-kafka.settings."<dotted.key>"` as plain integers (no `.text` suffix needed).
- Runs landed in the default store `.topotestix/runs/` (no `--output-dir` passed).

## Per-step results

| Step | Run dir(s) under `.topotestix/runs/` | Outcome | Key numbers | Wall time |
|---|---|---|---|---|
| 1. Micro-probe: dotted-key override, seed 9 + both keys forced to index 0 | `20260824-123925-kafka-cluster-seed-9-kafka-probe-dotted-override-20260824` | **PASS** — build succeeds (no June-style build error); run fails *by design*: only `kafka-large-message-on-kafka1` fails | `choices.json` contains both keys at index 0 (`log.segment.bytes=0`, `message.max.bytes=0` → resolved 1048576 each); summary 10 passed / 1 failed / 11 total; failure text contains `org.apache.kafka.common.errors.RecordTooLargeException: The request included a message larger than the max message size the server will accept.` | 3 m 18 s (12:39:25 → 12:42:43) |
| 2. Shrink seed 13 (expected class `RecordTooLargeException`) | 11 candidate dirs `20260824-125018…` through `20260824-132314-kafka-cluster-seed-13-kafka-shrink-seed13-rerun-20260824` (initial verify: `20260824-124657`) | **PASS** — clean reduction to all-minimal; failure class preserved | 1 initial verify + 11 candidate evaluations (all kept); final minimal `configChoices`: all 16 paths at index 0, incl. `message.max.bytes=0` (1 MiB) and `log.segment.bytes=0`; final run summary 10/1/11 with `RecordTooLargeException` in `report.json` | 36 m 13 s (12:50:18 → 13:26:31) |
| 3. Shrink seed 9 (expected class `RecordBatchTooLargeException`) | 13 dirs `20260824-133335…` through `20260824-141305-kafka-cluster-seed-9-kafka-shrink-seed9-rerun-20260824` | **PASS (mechanically)** — clean reduction to all-minimal; **class NOT preserved** | 1 initial + 12 candidate evaluations; initial run `report.json`: `RecordBatchTooLargeException`; final all-zero minimal run `report.json`: `RecordTooLargeException` — see verdict below | 42 m 42 s (13:33:35 → 14:16:17) |
| 4. etcd re-verify, shrink seed 3 | 2 dirs `20260824-141944…`, `20260824-142121-etcd-cluster-seed-3-etcd-shrink-seed3-rerun-20260824` | **PASS** — unchanged minimal config vs 2026-06-16 result in `docs/empirical-etcd-cluster.md` | Seed-3 fuzz was already minimal except `ELECTION_TIMEOUT=1`; single kept candidate shrinks it to 0. Final resolved values identical to doc: `memorySize=1024`, `diskSize=2048`, `HEARTBEAT_INTERVAL="100"`, `ELECTION_TIMEOUT="1250"`, `SNAPSHOT_COUNT="10000"`, `QUOTA_BACKEND_BYTES="2097152"`; failed check `etcd-quota-write-burst-etcd1`, message contains `mvcc: database space exceeded`; summary 11 passed / 1 failed / 12 total (doc expects exactly this) | 3 m 09 s (14:19:44 → 14:22:53) |

## Seed-9 class-preservation verdict (key thesis question)

**The minimal counterexample COLLAPSES the exception class; it does not preserve it.**

- Initial un-shrunk seed-9 run (`20260824-133335-…`): `RecordBatchTooLargeException` (the log-segment class).
- Final minimal run after shrinking (`20260824-141305-…`, all choice indices 0, i.e. both `message.max.bytes` and `log.segment.bytes` reduced to 1 MiB): `RecordTooLargeException`.

So at HEAD `8ff5f96f`, the generic shrinker still reduces the seed-9 failure into the `RecordTooLargeException` class, exactly as recorded for June (`docs/thesis-chapter-6-evaluation.md` §6.2.7). The mechanical shrinking itself is now clean (post-start property failure, 10/1/11, no build/startup error).

## Dotted-key override status vs June

June's forced-override attempt (`experiments/kafka-cluster/kafka-cluster-shrink-seed-9-choice-override-limitation.log`, run `20260615-172601-…-kafka-cluster-shrink-9-log-segment`) ended in a **build error**. At HEAD, the same style of override builds and takes effect end-to-end: the probe's only failing property is the large-message roundtrip with `RecordTooLargeException`, which is precisely what forcing `message.max.bytes` to 1 MiB should produce against the 1.5 MiB payload in `targets/kafka-cluster/properties.nix`.

## Raw artifacts

- Logs (this rerun):
  - `experiments/kafka-cluster/rerun-probe-dotted-override.log`
  - `experiments/kafka-cluster/rerun-shrink-seed-13.log`
  - `experiments/kafka-cluster/rerun-shrink-seed-9.log`
  - `experiments/etcd-cluster/rerun-shrink-seed-3-c0807fe.log`
- Per-run payloads: `run.json`, `report.json`, `choices.json`, `resolved.json`, `stdout.log`, `stderr.log` inside each run dir listed above.
- Reproduce commands are embedded verbatim in each shrink log ("Reproduce with:" section) and in each run dir's `run.json` → `reproduceCommand`.

## Notes / deviations

- An earlier probe launch was killed by the launching shell (process-group kill on timeout) before detaching correctly; it left an **incomplete, unused run dir** `20260824-123640-kafka-cluster-seed-9-kafka-probe-dotted-override-20260824` (has `expr.nix` etc., no `run.json`). It was left in place untouched; the valid probe is the `-123925-` dir.
- No existing run directories were modified or deleted; nothing under `docs/` or the thesis chapters was touched; no git commits/pushes were made.

---

# 2026-08-24 etcd seed-40 rerun

- **HEAD:** `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` (tracked files clean before start)
- **Command:** `nix develop -c python3 -m topotestix.cli orchestrator shrink etcd-cluster 40 --name etcd-shrink-seed40-rerun-20260824 --json`
- **Log:** `experiments/etcd-cluster/rerun-shrink-seed-40-c0807fe.log`

| Item | Value |
|---|---|
| Run dir (final minimized validation) | `.topotestix/runs/20260824-144914-etcd-cluster-seed-40-etcd-shrink-seed40-rerun-20260824` |
| All 6 shrink-step dirs | `20260824-144136`, `-144310`, `-144442`, `-144615`, `-144744`, `-144914` (all `…-etcd-shrink-seed40-rerun-20260824`) |
| gitHead | `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` |
| Final choices | topology `{".etcdVlans": 0, ".roles.etcd": 0}`; config all 6 paths at index 0 (`ELECTION_TIMEOUT`, `HEARTBEAT_INTERVAL`, `QUOTA_BACKEND_BYTES`, `SNAPSHOT_COUNT`, `.virtualisation.diskSize`, `.virtualisation.memorySize`) — **identical to June** (`docs/empirical-etcd-cluster.md`) and to June's log `etcd-cluster-v2-shrink-seed-40.log` |
| Resolved minimal config | `memorySize=1024`, `diskSize=2048`, `ELECTION_TIMEOUT="1250"`, `HEARTBEAT_INTERVAL="100"`, `SNAPSHOT_COUNT="10000"`, `QUOTA_BACKEND_BYTES="2097152"` — **identical to June doc values** |
| Outcome counts | passed=11 / failed=1 / total=12 (doc expects exactly this) |
| Failing check | `etcd-quota-write-burst-etcd1`; message contains `etcdserver: mvcc: database space exceeded` |
| Wall time | ≈ 9 m 07 s (14:41:36 → 14:50:42 UTC; budget was ≤30 min) |

**Verdict:** minimal config is **identical** to the June 2026-06-16 seed-40 result. Same 5 kept shrink steps, same final choice map, same failing property and message.

Note: `shrink --json` does not emit a JSON document to stdout at HEAD; it prints the human-readable "Final … choices" + "Reproduce with:" block (same as the previous agent's seed-3 rerun log). Raw per-run JSON payloads live in each run dir.

---

# 2026-08-24 sweep rerun

- **HEAD:** `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` (tracked files clean before start)
- **Command:** `nix develop -c python3 -m topotestix.cli orchestrator sweep kafka-cluster --seeds 1..50 --name kafka-cluster-sweep-1-50-rerun-20260824 --json` (sequential, `jobs=1`, default store `.topotestix/runs/` — same parallelism/store as the June invocation recorded in `kafka-cluster-sweep-1-50-fixed-20260613.md`)
- **Console log:** `experiments/kafka-cluster/rerun-sweep-1-50-20260824.log`

| Item | Rerun (2026-08-24) | June (2026-06-13) | Match |
|---|---|---|---|
| Run dirs | 50 × `.topotestix/runs/20260824-<HHMMSS>-kafka-cluster-seed-N-kafka-cluster-sweep-1-50-rerun-20260824` (N = 1..50) | 50 × `20260613-*` (since deleted from store) | n/a |
| gitHead | `8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c` | pre-2026-06-19 refactor HEAD | n/a |
| Passed / Failed seeds | **13 / 37** (total 50, skipped 0) | 13 / 37 | ✅ exact |
| Categories | 19 `log-segment-too-small`, 18 `broker-message-max-too-small`, 13 `pass` | same | ✅ exact |
| Per-seed flips vs June | **none** (status + category + failedProperties identical for all 50 seeds) | — | ✅ zero flips |
| Tool-emitted `classifications` (property-level) | `failed: 37, passed: 513` | not emitted in June log format | n/a |
| Wall time | 2 h 37 m 43 s (`totalTime` 9462.7 s, avgRunTime 189.3 s/seed) | ~3.6 h | faster (same order) |
| Failed property | `kafka-large-message-on-kafka1` on every failing seed | same | ✅ |

Machine-readable summary (June schema): `experiments/kafka-cluster/kafka-cluster-sweep-rerun-20260824-summary.{json,txt}`, derived from the new run store payloads (`run.json`/`resolved.json`/`report.json`) by `experiments/kafka-cluster/rerun-sweep-summarize-20260824.py`.

**Config-draw reproduction detail:** with one field-mapping correction, **every drawn config value on every seed matches June exactly** (autoCreate, heap, logSegmentBytes, memory, messageMax, replicaFetchMax, rf, unclean). The old summary's `minIsr` column provably drew from `min.insync.replicas` (rerun values match it 50/50), not from `transaction.state.log.min.isr` (23/50) — i.e. the apparent "minIsr swap" on 27 seeds is a labeling quirk of the June artifact, not a behavioral change since June. The rerun summary reproduces the June mapping for like-for-like comparison and additionally records `transactionStateLogMinIsr`. The June choice lists themselves are unchanged (`transaction.state.log.min.isr = [ 1 2 ]` both before and after commit `2037a66`, 2026-06-19).

No startup/OOM/build failures occurred; all failures are post-start data-plane property failures, as in June.

Notes / deviations:

- No existing run directories modified or deleted; nothing under `docs/` touched; no commits/pushes.
- New files created only under `experiments/`: the two logs above, `rerun-poll-20260824.sh` (read-only poll helper), `rerun-sweep-summarize-20260824.py`, and the two summary files.
- A stray probe (`orchestrator shrink etcd-cluster 40 --name json-probe-x --output-dir /tmp/opencode/jsonprobe`) was launched for ~10 s while checking `--json` behavior, then killed before its first candidate completed; it wrote nothing into the repo's `.topotestix/runs/` store.
- Sweep ran ~1 h faster than June (2h38m vs ~3.6h); per-seed runtime ~189 s vs ~270 s in June — machine-load difference, same sequential mode.
