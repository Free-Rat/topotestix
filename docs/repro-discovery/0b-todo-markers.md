# TODO markers — thesis chapters (provenance: thesis repo `/home/freerat/projects/master-thesis`, rev `c310f6e62832d17b0ea25d89d0c7ed1b66feade8`, dirty)

## 06-evaluation.typ

- **06-evaluation.typ:9 — TODO("DECISION")**
  - Per-question success criteria not yet drafted in @sec:research-questions; evidence for RQ4 pending (@sec:evaluation-planned-arm).
- **06-evaluation.typ:11 — TODO("DECISION")**
  - Draft-status open items: (1) RQ4 no evidence; (2) success criteria undefined; (3) execution accounting (unique resolved configurations, cache-hit vs fresh, wall-clock, compute cost) not reported; (4) no topology case study; (5) RabbitMQ disk/failure-domain cells rest on 1–3 executions; (6) run evidence local/uncommitted, no archival plan.
- **06-evaluation.typ:23 — TODO("EVIDENCE")**
  - Requests execution accounting for the principal sweeps: unique resolved configurations, duplicate-resolution rates, cache-hit vs fresh-execution status, wall-clock runtime, compute cost — to be derived from retained run artifacts once an analysis pipeline exists. Sweep tables currently report seeds and outcomes only.
- **06-evaluation.typ:42 — TODO("EXPERIMENT")**
  - No principal case study varies node count or network topology (all fixed three-node, single-network). Planned: topology-varying experiment (e.g. deferred Kafka rack-topology design) so topology fuzzing is supported empirically.
- **06-evaluation.typ:46 — TODO("EXPERIMENT")**
  - RQ4 exploratory arm (@sec:evaluation-planned-arm) is design baseline only: not frozen, implemented, or executed; no results reported.
- **06-evaluation.typ:52 — TODO("CITATION")**
  - Kafka durability semantics (ISR / acks / min.insync.replicas) need a versioned primary source.
- **06-evaluation.typ:227 — TODO("EXPERIMENT")** (@sec:etcd-shrinking)
  - etcd v2 space has 96 cells, sweep samples 50. Requests exhaustive enumeration of all 96 cells as baseline comparison against the sampled result (coverage of failure class + runtime cost). Not yet executed in this draft.
- **06-evaluation.typ:300 — TODO("EVIDENCE")**
  - Per-run commit hashes and run identifiers in RabbitMQ disk/failure-domain sections are interim provenance; once counterexample cells are re-run under the fresh-build protocol (@sec:evaluation-rabbitmq-crash), replace with a single evaluated-revision statement.
- **06-evaluation.typ:335 — TODO("EXPERIMENT")** (@sec:evaluation-rabbitmq-crash)
  - No RabbitMQ cell yet repeated under a fresh-build protocol with cache status recorded. Before submission: at least one fresh-build repetition each for the two counterexample contracts (disk, failure-domain) with cache state logged.
- **06-evaluation.typ:355 — TODO("EVIDENCE")**
  - Cited per-run artifacts are local, uncommitted `.topotestix/` directories. Requests archiving raw run evidence, analysis inputs, and exact dependency revisions in a versioned artifact location sufficient to reproduce every table in the chapter from machine-readable inputs.
- **06-evaluation.typ:391 — TODO("EXPERIMENT")**
  - RQ4 exploratory experiment (Kafka durability protocol) accepted in design but not frozen/implemented/executed; no results claimed.
- **06-evaluation.typ:395 — TODO("DECISION")**
  - Whether a bounded relevance qualifier ("operationally meaningful") is defensible remains open; no external relevance evidence planned.

## 07-discussion.typ

- **07-discussion.typ:114 — TODO("STRUCTURE")**
  - Discussion never maps interpretation back to RQ1–RQ4; requests a paragraph connecting shrinking/oracle/fault-model discussion to the research questions, cross-referencing @sec:evaluation-summary.

## 08-conclusions.typ

- **08-conclusions.typ:23 — TODO("WRITING")**
  - Chapter never returns a qualified yes/no to the thesis-level question; requests a closing statement. RQ4 carried as open hole in @chap:intro, @chap:evaluation, and conclusions; disposition to be settled.

## thesis.typ (abstract)

- **thesis.typ:47 — TODO("DECISION")**
  - Final abstract to be revised after the planned RQ4 experiment and expanded literature review; current text states only completed evidence; final research-question wording pending.
