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
  name = "rabbitmq-disk-rep0-cell-x-e1-seed1";
  reportNode = "rabbit1";
  topologyChoices = (builtins.fromJSON "{}");
  configChoices = (builtins.fromJSON "{\"rabbit\": {\".environment.etc.topotestix-disk-backlog-rate.text\": 1, \".environment.etc.topotestix-disk-capacity-safety-factor-milli.text\": 1, \".environment.etc.topotestix-disk-confirm-timeout-ms.text\": 0, \".environment.etc.topotestix-disk-consumer-outage-seconds.text\": 1, \".environment.etc.topotestix-disk-initial-free-mb.text\": 2, \".environment.etc.topotestix-disk-message-size.text\": 2, \".services.rabbitmq.configItems.disk_free_limit.absolute\": 2, \".virtualisation.diskSize\": 1}}");
  repetitionToken = "c20260910-6335ae";
}