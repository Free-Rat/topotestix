let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  orchestrate = (import (builtins.toPath "/home/freerat/projects/topotestix/lib/orchestrate.nix") { inherit pkgs lib; testers = pkgs.testers; }).orchestrate;

  topologyTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-disk/topology.nix") { inherit lib; };
  configTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-disk/config.nix") { inherit lib; };
  baseModule = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-disk/module.nix");
  testScript = builtins.readFile (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-disk/test-script.py");
  propertiesMod = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-disk/properties.nix") { inherit lib; };
in
orchestrate {
  seed = 1;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "rabbitmq-disk-rep0-positive-e0-seed1";
  reportNode = "rabbit1";
  topologyChoices = (builtins.fromJSON "{}");
  configChoices = (builtins.fromJSON "{}");
  repetitionToken = "c20260910-6335ae";
}