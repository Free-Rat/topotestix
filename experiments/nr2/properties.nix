# properties.nix
{ lib, nixpkgs, baseNode }:

let
  mkConnectivityProperty = cfg:
    nixpkgs.lib.nixosTest {
      name = "connectivity-${cfg.ip}-${cfg.role}";

      nodes = {
        machine = { ... }: {
          imports = [ (baseNode cfg) ];
        };
      };

      testScript = ''
        machine.wait_for_unit("multi-user.target")

        # PROPERTY: ssh must be reachable
        machine.wait_for_open_port(22)

        # PROPERTY: system must not crash
        machine.succeed("echo system alive")
      '';
    };
in
{
  connectivity = mkConnectivityProperty;
}
