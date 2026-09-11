let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  orchestrate = (import (builtins.toPath "/home/freerat/projects/topotestix/lib/orchestrate.nix") { inherit pkgs lib; testers = pkgs.testers; }).orchestrate;

  topologyTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-cluster/topology.nix") { inherit lib; };
  configTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-cluster/config.nix") { inherit lib; };
  baseModule = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-cluster/module.nix");
  testScript = builtins.readFile (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-cluster/test-script.py");
  propertiesMod = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-cluster/properties.nix") { inherit lib; };
in
orchestrate {
  seed = 30;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "kafka-sweep-rep1-seed30";
  reportNode = "kafka1";
  topologyChoices = (builtins.fromJSON "{}");
  configChoices = (builtins.fromJSON "{}");
  repetitionToken = "c20260910-6335ae";
}