let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  orchestrate = (import (builtins.toPath "/home/freerat/projects/topotestix/lib/orchestrate.nix") { inherit pkgs lib; testers = pkgs.testers; }).orchestrate;

  topologyTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-crash/topology.nix") { inherit lib; };
  configTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-crash/config.nix") { inherit lib; };
  baseModule = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-crash/module.nix");
  testScript = builtins.readFile (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-crash/test-script.py");
  propertiesMod = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-crash/properties.nix") { inherit lib; };
in
orchestrate {
  seed = 1;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "rabbitmq-crash-rep0-leader-e0-seed1";
  reportNode = "rabbit1";
  topologyChoices = (builtins.fromJSON "{}");
  configChoices = (builtins.fromJSON "{\"rabbit\": {\".environment.etc.topotestix-crash-target-role.text\": 1}}");
  repetitionToken = "c20260910-6335ae";
}