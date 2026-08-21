{ lib, ... }:

# Three-node cluster on a single VLAN. The partition is applied at runtime
# by the test script using iptables, so the underlying topology stays fully
# connected. This keeps the fuzz surface focused on partition behavior rather
# than on initial connectivity.
{
  roles.rabbit = [ 3 ];
  rabbitVlans = [ [ 1 ] ];
}
