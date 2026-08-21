{ lib, ... }:

# Three-node cluster on a single VLAN. Disk pressure is applied at runtime
# by the test driver via fallocate, so the underlying topology stays fully
# connected. This keeps the fuzz surface focused on disk behavior rather
# than on connectivity.
{
  roles.rabbit = [ 3 ];
  rabbitVlans = [ [ 1 ] ];
}
