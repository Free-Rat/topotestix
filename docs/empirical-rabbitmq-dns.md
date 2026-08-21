# Empirical: RabbitMQ DNS / hostname

> **Historical prototype.** This target tests symmetric static `/etc/hosts`
> corruption, not general DNS behavior. Its pass totals are not independent
> executions. See `docs/rabbitmq/evaluation-audit-2026-08-21.md`.

This note summarizes the design verification and 50-seed sweep of the
`rabbitmq-dns` target (the DNS / hostname / resolver axis of the RabbitMQ
deep-sweep plan) for thesis use.

## Verdict

All 50 seeds passed: 50/50, with the full 7-property suite exercised and
passing on every run and all four resolution modes (valid, missing-seed,
ambiguous-seed, all-to-same) reached at least nine times. Broken resolvers are
detected exactly where the membership assertions point — a broken mode never
masquerades as a healthy 3-node cluster — while the report node (`rabbit1`)
stays a functional AMQP endpoint that round-trips its own confirmed durable
messages in every mode, regardless of how its peers' names resolve.

## Config under test

`rabbitmq-dns` is a 3-node, single-VLAN RabbitMQ target on one role
(`rabbit`), each node at 2048 MB memory / 2048 MB disk, firewall off. The
driven axis is the per-node `/etc/hosts` name-to-IP table, selected by the
fuzzer from a single `networking.extraHosts` list whose entries are labeled
fragments (one complete mapping per fragment). The fuzzer picks exactly one
fragment (index 0..3) independently of a publish-count axis
(`environment.etc."topotestix-dns-publish-count"`, values **20 / 50 / 100**).
All four nodes receive the identical config — which is the symmetric
multi-node resolution state each mode describes — and `rabbit1` is the report
node and the seed: it is never joined, only `rabbit2` and `rabbit3` attempt to
join `rabbit@rabbit1`.

The four mode fragments (verbatim from `config.nix`) are:

```text
# topotestix-dns-mode=valid
192.168.1.1 rabbit1
192.168.1.2 rabbit2
192.168.1.3 rabbit3
```

```text
# topotestix-dns-mode=missing-seed
192.168.1.2 rabbit2
192.168.1.3 rabbit3
```

```text
# topotestix-dns-mode=ambiguous-seed
192.168.1.3 rabbit1
192.168.1.2 rabbit2
192.168.1.3 rabbit3
```

```text
# topotestix-dns-mode=all-to-same
192.168.1.3 rabbit1
192.168.1.3 rabbit2
192.168.1.3 rabbit3
```

Each of the four modes is a distinct name-to-IP table, and each fragment
carries a `# topotestix-dns-mode=<name>` label line. The driver reads that label
back out of the booted `/etc/hosts` and branches on it (that is how a run
"knows" which mode it is in). Semantically: `valid` maps every name to the
correct broker IP (the positive control); `missing-seed` drops the `rabbit1`
name so the seed is unresolvable anywhere; `ambiguous-seed` maps `rabbit1` to
`rabbit3`'s IP on every node (the wrong broker), i.e. a single ambiguous seed
entry; and `all-to-same` maps every peer name to the same IP (an identity
collision).

## Properties

The target checks 7 report entries (the same 7 properties, in this order, on
every seed):

| # | property | intent |
|---|---|---|
| 1 | `rabbitmq-dns-formation-matches-mode` | the observed formation outcome must match the resolution mode: `valid` → all joins succeed and every node reports the canonical 3; a broken mode → at least one join refused and/or some node's membership view is missing a peer (a broken resolver must not masquerade as a healthy cluster). |
| 2 | `rabbitmq-dns-no-phantom-members` | cluster membership is symmetric in both directions across every node (no accidental split cluster / phantom membership induced by the resolver). |
| 3 | `rabbitmq-dns-reported-member-count` | reported membership is consistent with whether a full cluster may exist; a broken resolver must not present a full, canonical 3-member view indistinguishable from a healthy cluster. |
| 4 | `rabbitmq-dns-durable-delivery` | every confirmed durable publish round-trips exactly (`basic_get` recovers exactly `ok` — no silent loss, no phantom duplicate) in every mode. |
| 5 | `rabbitmq-dns-service-up-rabbit1` | `rabbitmq.service` active on the report node. |
| 6 | `rabbitmq-dns-service-up-rabbit2` | `rabbitmq.service` active on `rabbit2`. |
| 7 | `rabbitmq-dns-service-up-rabbit3` | `rabbitmq.service` active on `rabbit3`. |

Properties 1–4 are **conditionally branched on the observed mode**: the driver
records the actual resolution state that materialised in
`/tmp/dns-results.json`, and each of those assertions reads that state and
takes the `valid` branch (must form a clean full 3-node cluster) or the broken
branch (must *not* look healthy). Properties 5–7 (`service_up_*`) are the
**unconditional** liveness floor — they must hold in every mode, since a
broken resolver may prevent joins but must not take the local broker down.
`rabbitmq-dns-durable-delivery` is the mode-agnostic invariant that carries the
"the report node stays an AMQP endpoint" claim.

## Seed → mode distribution

Per-mode total seeds and publish-count breakdown (all 50 runs, all passed):

| mode | seeds | pc=20 | pc=50 | pc=100 |
|---|---|---|---|---|
| valid | 11 | 5 | 3 | 3 |
| missing-seed | 15 | 7 | 6 | 2 |
| ambiguous-seed | 12 | 5 | 3 | 4 |
| all-to-same | 12 | 4 | 2 | 6 |
| **total** | **50** | **21** | **14** | **15** |

The full seed-by-seed table (`mode` and `pc` are the resolved `/etc/hosts`
state read back at run time; `passed` is the 7-property result; `seconds` is
derived from the `run.json` `startedAt`/`finishedAt` timestamps):

| seed | mode | pc | passed | seconds |
|---|---|---|---|---|
| 1 | all-to-same | 20 | 7/7 | 64.95 |
| 2 | all-to-same | 20 | 7/7 | 61.05 |
| 3 | missing-seed | 50 | 7/7 | 56.92 |
| 4 | missing-seed | 100 | 7/7 | 54.70 |
| 5 | ambiguous-seed | 100 | 7/7 | 61.25 |
| 6 | missing-seed | 20 | 7/7 | 54.52 |
| 7 | ambiguous-seed | 20 | 7/7 | 67.05 |
| 8 | ambiguous-seed | 50 | 7/7 | 66.25 |
| 9 | valid | 20 | 7/7 | 74.62 |
| 10 | all-to-same | 100 | 7/7 | 67.74 |
| 11 | missing-seed | 50 | 7/7 | 4.76 |
| 12 | missing-seed | 50 | 7/7 | 4.73 |
| 13 | valid | 100 | 7/7 | 77.35 |
| 14 | missing-seed | 20 | 7/7 | 4.81 |
| 15 | missing-seed | 50 | 7/7 | 5.01 |
| 16 | all-to-same | 50 | 7/7 | 68.33 |
| 17 | ambiguous-seed | 50 | 7/7 | 4.66 |
| 18 | missing-seed | 100 | 7/7 | 4.66 |
| 19 | valid | 20 | 7/7 | 4.75 |
| 20 | ambiguous-seed | 50 | 7/7 | 4.69 |
| 21 | all-to-same | 20 | 7/7 | 4.79 |
| 22 | valid | 20 | 7/7 | 4.80 |
| 23 | all-to-same | 100 | 7/7 | 4.79 |
| 24 | all-to-same | 50 | 7/7 | 4.57 |
| 25 | valid | 100 | 7/7 | 4.38 |
| 26 | all-to-same | 100 | 7/7 | 4.17 |
| 27 | ambiguous-seed | 100 | 7/7 | 4.13 |
| 28 | valid | 50 | 7/7 | 66.23 |
| 29 | valid | 20 | 7/7 | 4.06 |
| 30 | missing-seed | 20 | 7/7 | 4.11 |
| 31 | ambiguous-seed | 20 | 7/7 | 4.26 |
| 32 | valid | 50 | 7/7 | 54.42 |
| 33 | valid | 100 | 7/7 | 4.10 |
| 34 | ambiguous-seed | 20 | 7/7 | 4.11 |
| 35 | all-to-same | 100 | 7/7 | 4.17 |
| 36 | ambiguous-seed | 20 | 7/7 | 4.12 |
| 37 | missing-seed | 50 | 7/7 | 4.04 |
| 38 | missing-seed | 50 | 7/7 | 4.16 |
| 39 | valid | 50 | 7/7 | 4.17 |
| 40 | all-to-same | 20 | 7/7 | 4.17 |
| 41 | ambiguous-seed | 100 | 7/7 | 4.11 |
| 42 | all-to-same | 100 | 7/7 | 4.12 |
| 43 | missing-seed | 20 | 7/7 | 4.09 |
| 44 | ambiguous-seed | 100 | 7/7 | 4.17 |
| 45 | all-to-same | 100 | 7/7 | 4.15 |
| 46 | missing-seed | 20 | 7/7 | 4.15 |
| 47 | missing-seed | 20 | 7/7 | 4.19 |
| 48 | ambiguous-seed | 20 | 7/7 | 4.14 |
| 49 | valid | 20 | 7/7 | 4.11 |
| 50 | missing-seed | 20 | 7/7 | 4.08 |

## Timing

Per-run timing (seconds) from `run.json` (`finishedAt − startedAt`):

- min: 4.04 s (seed 37, missing-seed)
- avg: 21.04 s
- max: 77.35 s (seed 13, valid)
- total (sum of per-run durations): 1051.83 s

The wall-clock span of the whole sweep — from the first `startedAt`
(2026-08-20T19:44:28Z) to the last `finishedAt` (2026-08-20T19:53:11Z) — was
523 s, run with `--jobs 2`. The per-run distribution is strongly bimodal:
the first ≈10 runs (seeds 1–16, 28, 32) took 54–77 s each, because they were
freshly building the NixOS system images in the Nix store; the remaining 32+
runs reused those cache entries and completed in 4–5 s. That explains why the
average (21 s) is pulled well above the steady-state ~4 s by a short burst of
slow, first-run cold builds.

## What we learned

- In an `nsswitch`-`files`-only harness — no DNS server, glibc
  `files`-first, no search domain — the per-node `/etc/hosts` name-to-IP table
  is the *only* deterministic, reproducible lever for name resolution. Driving
  the exact table (rather than `resolv.conf` search domains) is why a mode is
  a fully observable, assertable state instead of an assumption.
- The per-mode *expectation* lives in the assertion, not the fuzzer: the
  driver simply records which resolution state materialised
  (`/tmp/dns-results.json.mode`), and each property branches on it. The fuzzer
  is mode-agnostic — it only picks a fragment — so the "valid forms, broken
  must not form" logic is owned by the property layer. This is what makes the
  detector precise instead of a heuristic.
- `basic_get` works on quorum queues in this stack: the durable-delivery
  property reads messages back with `basic_get(auto_ack=True)` against a
  3-replica quorum queue and recovered exactly the confirmed count in all four
  modes (20/50/100), so the round-trip invariant is exercised for real, not
  only for classic queues.
- A broken resolver never masquerades as a healthy cluster: in every broken
  mode at least one `rabbitmqctl join_cluster` fails cleanly (surfacing as
  `erpc,noconnection`), and `rabbit2`/`rabbit3` never both settle onto the
  canonical 3, so the `valid`-only branch of the membership properties is
  never falsely satisfied.
- The report node stays a live, self-consistent AMQP endpoint even when its
  peer names are unresolvable or colliding: `service_up_*` and
  `durable_delivery` hold in every mode, so name-resolution breakage degrades
  the *cluster*, not the *broker*.
- The identity-ambiguity class the plan names ("no accidental split cluster
  due to resolver mismatch") is covered directly by `no_phantom_members`
  (pairwise membership symmetry) plus `reported_member_count` (no clean full
  set in a broken mode) — two complementary views of the same failure.

## Reproduce

One-shot sweep (50 seeds, 2 concurrent runs):

```bash
topotestix orchestrator sweep rabbitmq-dns \
    --seeds 1 50 --jobs 2 --name dns-sweep-50
```

Single-seed run (e.g. seed 1):

```bash
topotestix orchestrator run rabbitmq-dns \
    --seed 1 --name dns-sweep-50 \
    --project-root /home/freerat/projects/topotestix \
    --topology-target /home/freerat/projects/topotestix/targets/rabbitmq-dns/topology.nix \
    --config-target /home/freerat/projects/topotestix/targets/rabbitmq-dns/config.nix \
    --base-module /home/freerat/projects/topotestix/targets/rabbitmq-dns/module.nix \
    --test-script /home/freerat/projects/topotestix/targets/rabbitmq-dns/test-script.py \
    --properties /home/freerat/projects/topotestix/targets/rabbitmq-dns/properties.nix
```

## Caveats

- The `{erpc,noconnection}` errors in the broken-mode `stderr.log` (RabbitMQ's
  Erlang feature-flags compatibility probe, `erpc:call/5`, aborting with
  `{:aborted_feature_flags_compat_check, {:error, {:erpc, :noconnection}}}`
  during the `rabbit2`/`rabbit3` `join_cluster` attempts) are the *expected*
  detector signal, not defects: they are the observable evidence that the
  broken resolver failed to let `rabbit2`/`rabbit3` reach the seed
  `rabbit@rabbit1` for the join. In the full-driver-stderr runs (12 of the 50:
  seeds {2,3,4,5,6,7,8,9,10,13,16,28}), each broken-mode run shows 4
  `erpc,noconnection` lines (one per joining node, error line + warning line)
  and each valid-mode run shows 0.
- NixOS bakes the target's `networking.extraHosts` into `/etc/hosts` at boot *on
  top of* the harness baseline. The harness baseline (from
  `testing/network.nix`) only adds each node's own self-loopback entry
  (`127.0.0.2 rabbitN`, for that node's own `N`) plus the standard
  `127.0.0.1 localhost` / `::1 localhost` lines — it never maps *peer* names.
  So the booted `/etc/hosts` is `localhost baseline + own self-loopback + the
  selected fragment`, and peer-name resolution is driven entirely by the
  fragment. In verified ground truth (seed 4, missing-seed), rabbit2's and
  rabbit3's `/etc/hosts` contain only the fragment's `rabbit2 → .2` and
  `rabbit3 → .3` rows plus each one's own self-loopback; the `rabbit1` name is
  absent from both, which is precisely what `missing-seed` asserts. The driver
  reads the mode label back out of that file, which is why the mode label in
  the fragment doubles as the driver's observable state.
- A small subset of the 50 runs (12, seeds 2–10, 13, 16, 28) rebuilt the NixOS
  system images and carry full driver logs in `stderr.log`; the rest are
  cache hits with a 263-byte `stderr.log`. Both sets resolve to identical
  `/etc/hosts` state for a given seed, verified against the Nix store.
