# Experiments

This directory contains historical prototypes and smoke-test notes from early TopoTestix development. These files are not part of the production library, CLI, or CI contract.

Use `lib/`, `orchestrator/`, `targets/`, `tests/`, and `docs/` as the source of current behavior.

## Layout

Run data (logs, sweep summaries, findings) is grouped into one directory per SUT:

| Directory | Content |
|---|---|
| `etcd-cluster/` | etcd Raft cluster sweep/shrink logs, summaries, and findings |
| `kafka-cluster/` | Kafka KRaft cluster sweep/shrink logs, minimal-case configs, and findings |
| `kafka-rack-links/` | Kafka rack-link campaign runner (`campaign.py`) and sweep directories (ledger, per-run artifacts, summary) |
| `kafka-topology/` | Kafka topology-first campaign runner (`campaign.py`) and campaign directories (ledger, per-run artifacts, summary) |
| `nginx/` | nginx smoke and orchestrator test harnesses (`smoke-test/`, `orchestrator-test/`) |
| `postgresql/` | PostgreSQL primary/standby sweep logs and readiness notes |
| `nr0/`..`nr8-mvp/` | Numbered development prototypes (early module/fuzzer/MVP experiments, not SUT-specific) |
