{ lib, ... }:

# Three-node cluster on a single VLAN. The DNS / name-resolution axis is
# injected at runtime by the test driver (it writes /etc/hosts and
# /etc/resolv.conf on each node according to the fuzzed mode/domain — see
# test-script.py), so the underlying L2 topology stays fully connected and
# the fuzz surface is focused on the identity / resolution axis rather than
# on connectivity.
{
  roles.rabbit = [ 3 ];
  rabbitVlans = [ [ 1 ] ];
}
