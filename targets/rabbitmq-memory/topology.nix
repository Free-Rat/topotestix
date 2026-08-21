{ lib, ... }:

# Three-node cluster on a single VLAN. Memory pressure is applied at
# runtime by the test driver via publishing load, with the host-level
# memory size and broker watermark configured by config.nix. The
# underlying topology stays fully connected so the fuzz surface is
# focused on memory behavior rather than on connectivity.
{
  roles.rabbit = [ 3 ];
  rabbitVlans = [ [ 1 ] ];
}
