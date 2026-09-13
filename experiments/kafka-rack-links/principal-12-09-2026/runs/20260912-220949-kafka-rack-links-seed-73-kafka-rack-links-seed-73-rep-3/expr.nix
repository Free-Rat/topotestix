let
  nixpkgs = (builtins.getFlake (builtins.unsafeDiscardStringContext (toString (builtins.path {
  path = (builtins.toPath "/home/freerat/projects/topotestix");
  name = "topotestix-locked-flake";
  filter = path: _: builtins.elem (toString path) [ "/home/freerat/projects/topotestix" "/home/freerat/projects/topotestix/flake.nix" "/home/freerat/projects/topotestix/flake.lock" ];
})))).inputs.nixpkgs;
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  orchestrate = (import (builtins.toPath "/home/freerat/projects/topotestix/lib/orchestrate.nix") {
    inherit pkgs lib;
    testers = pkgs.testers;
  }).orchestrate;

  topologyTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-rack-links/topology.nix") { inherit lib; };
  configTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-rack-links/config.nix") { inherit lib; };
  baseModule = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-rack-links/module.nix");
  testScript = builtins.readFile (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-rack-links/test-script.py");
  propertiesMod = import (builtins.toPath "/home/freerat/projects/topotestix/targets/kafka-rack-links/properties.nix") { inherit lib; };
in
orchestrate {
  seed = 73;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "kafka-rack-links-seed-73-rep-3";
  reportNode = "client1";
  topologyChoices = (builtins.fromJSON "{}");
  configChoices = (builtins.fromJSON "{}");
  repetitionToken = "principal-12-09-2026-seed-73-rep-3";
}