{ lib, ... }:

# Fuzzable partition parameters. Each dimension is a separate file so the
# fuzzer resolves them independently and the shrinker can reduce each
# dimension toward index 0 in isolation.
#
# Index 0 of every dimension is the simplest / safest value so that
# shrinking toward 0 produces a minimal, still-relevant configuration.
{
  # Which nodes are isolated from the rest of the cluster.
  #   none      = no partition (control case)
  #   isolate-1 = 1 node isolated from the other 2 (minority of 1)
  #   isolate-2 = 2 nodes isolated from the remaining 1 (minority of 1, majority of 2 is isolated)
  environment.etc."topotestix-partition-shape".text = [
    "none"
    "isolate-1"
    "isolate-2"
  ];

  # Which ports to block between the partitioned sides.
  #   none    = block all IP traffic between sides (full network partition)
  #
  # Port-specific blocking (AMQP-only, Erlang-only, or both) is left as
  # future work. The Erlang distribution in particular can use ephemeral
  # ports resolved via EPMD, so a port-list rule does not reliably
  # partition the cluster in the NixOS VM test harness. The test script
  # implements "none" as a blanket drop on the inter-side traffic.
  environment.etc."topotestix-partition-ports".text = [
    "none"
  ];

  # Direction of the partition.
  #   two-way = both sides block each other (symmetric)
  #   one-way = only the isolated side blocks outgoing traffic (asymmetric)
  environment.etc."topotestix-partition-direction".text = [
    "two-way"
    "one-way"
  ];

  # How long the partition stays in effect before being healed, in seconds.
  environment.etc."topotestix-partition-heal".text = [
    "0"
    "15"
    "30"
  ];
}
