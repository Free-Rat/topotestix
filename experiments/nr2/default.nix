# default.nix
{ nixpkgs, lib }:

let
  generators = import ./generators.nix { inherit lib; };
  properties = import ./properties.nix {
    inherit lib nixpkgs;
    baseNode = cfg: import ./base-node.nix { nodeConfig = cfg; };
  };

  cases = generators;

  mkTest = cfg: {
    name = "test-${cfg.ip}-${cfg.role}";
    value = properties.connectivity cfg;
  };

in
builtins.listToAttrs (map mkTest cases)
