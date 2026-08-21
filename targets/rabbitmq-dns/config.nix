{ lib, ... }:

# Fuzzable DNS / name-resolution parameters, one attribute per dimension so
# the fuzzer resolves each independently and the shrinker can reduce each
# toward index 0 in isolation. Index 0 of every dimension is the valid state,
# so shrinking converges on the baseline control case.
#
# `dns-mode` is the driven axis. It selects a *deterministic* per-node
# /etc/hosts name-to-IP mapping through `networking.extraHosts`. We drive the
# exact name-to-IP table rather than glibc search-domain expansion for two
# reasons:
#
#   1. Inter-VM name resolution in the NixOS test harness goes through
#      /etc/hosts, not a resolver. With glibc "files"-first nsswitch and no DNS
#      server in these VMs, the search domain is never consulted for these
#      lookups — only an exact /etc/hosts entry can change them. So the
#      name-to-IP table is the only deterministic, reproducible lever here.
#
#   2. The identity ambiguity — which broker a cluster peer name resolves to —
#      is the exact bug class the deep-sweep plan names ("no accidental split
#      cluster appears due to resolver mismatch"). Each mode below yields a
#      distinct, concretely-observable cluster membership, so the harness can
#      assert which resolution state actually occurred rather than assume it.
#
# All four "rabbit" nodes are fuzzed together (identical config), which is
# exactly the symmetric multi-node resolution state these modes describe.
{
  # The fuzzer selects one complete fragment. NixOS incorporates the selected
  # fragment into the generated read-only /etc/hosts before the VM boots.
  networking.extraHosts = [
    ''
      # topotestix-dns-mode=valid
      192.168.1.1 rabbit1
      192.168.1.2 rabbit2
      192.168.1.3 rabbit3
    ''
    ''
      # topotestix-dns-mode=missing-seed
      192.168.1.2 rabbit2
      192.168.1.3 rabbit3
    ''
    ''
      # topotestix-dns-mode=ambiguous-seed
      192.168.1.3 rabbit1
      192.168.1.2 rabbit2
      192.168.1.3 rabbit3
    ''
    ''
      # topotestix-dns-mode=all-to-same
      192.168.1.3 rabbit1
      192.168.1.3 rabbit2
      192.168.1.3 rabbit3
    ''
  ];

  # How each node's /etc/hosts maps the cluster's peer names onto broker IPs
  # (the NixOS-test VMs sit at 192.168.1.1 / .2 / .3; index 0 is valid).
  #
  #   "valid"         : rabbit1->.1, rabbit2->.2, rabbit3->.3 on every node
  #                     (the baseline state). A full 3-node cluster forms and
  #                     durable delivery works — the positive control.
  #   "missing-seed"  : the rabbit1 name is absent from every node's hosts
  #                     file, so the cluster seed is unresolvable anywhere.
  #                     Formation must fail cleanly; the run must never be
  #                     reported as a healthy 3-node cluster.
  #   "ambiguous-seed": on every node rabbit1 resolves to the WRONG broker's IP
  #                     (rabbit3's), so joining rabbit@rabbit1 reaches a
  #                     different broker than the true seed. Expected to be
  #                     detected as not-a-clean-full-cluster.
  #   "all-to-same"   : every peer name resolves to rabbit3's IP on every node,
  #                     so both rabbit@rabbit1 and rabbit@rabbit2 reach the
  #                     same broker. Expected to be detected as not-a-clean-
  #                     full-cluster (identity collision).
  # Durable messages published during delivery verification when the cluster
  # is healthy. Only exercised in the "valid" state (the other modes are
  # expected to fail formation, so there is no cluster to publish into), but
  # fuzzing it varies the load on the resolution-dependent happy path.
  # Index 0 is the smallest (least aggressive).
  environment.etc."topotestix-dns-publish-count".text = [
    "20"
    "50"
    "100"
  ];
}
