# generators.nix
{ lib }:

let
  ips = lib.genList (i: "10.0.0.${toString (i + 1)}") 5;
  roles = [ "client" "server" ];
in
lib.cartesianProductOfSets {
  ip = ips;
  role = roles;
}
