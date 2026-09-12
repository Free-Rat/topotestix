{ lib, ... }:

{
  # Three racks of two brokers each, plus one client. VLANs:
  #   31, 32, 33 = rack-local network of rack-a, rack-b, rack-c;
  #   10 = rack-a <-> rack-b link, 11 = rack-a <-> rack-c link,
  #   12 = rack-b <-> rack-c link; a link exists only when both of its racks
  #   choose it, and each rack chooses at least one of its two links;
  #   20 = client network, never used for controller or replication traffic.
  roles.racka = [ 2 ];
  roles.rackb = [ 2 ];
  roles.rackc = [ 2 ];
  roles.client = [ 1 ];

  rackaVlans = [
    [ 10 11 20 31 ]
    [ 10 20 31 ]
    [ 11 20 31 ]
  ];
  rackbVlans = [
    [ 10 12 20 32 ]
    [ 10 20 32 ]
    [ 12 20 32 ]
  ];
  rackcVlans = [
    [ 11 12 20 33 ]
    [ 11 20 33 ]
    [ 12 20 33 ]
  ];
  clientVlans = [ [ 20 ] ];
}
