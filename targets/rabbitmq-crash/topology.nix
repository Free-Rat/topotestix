{ lib, ... }:

# Three independent VMs on one VLAN. The driver kills the observed quorum-queue
# leader or follower with SIGKILL and restarts the same service and data dir.
{
  roles.rabbit = [ 3 ];
  rabbitVlans = [ [ 1 ] ];
}
