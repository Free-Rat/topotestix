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

  topologyTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-failure-domain/topology.nix") { inherit lib; };
  configTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-failure-domain/config.nix") { inherit lib; };
  baseModule = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-failure-domain/module.nix");
  testScript = builtins.readFile (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-failure-domain/test-script.py");
  propertiesMod = import (builtins.toPath "/home/freerat/projects/topotestix/targets/rabbitmq-failure-domain/properties.nix") { inherit lib; };
in
orchestrate {
  seed = 1;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "rabbitmq-faildom-rep0-colocated-e1-seed1";
  reportNode = "rabbit1";
  topologyChoices = (builtins.fromJSON "{}");
  configChoices = (builtins.fromJSON "{\"rabbit\": {\".environment.etc.topotestix-failure-domain-placement.json.text\": 1}}");
  repetitionToken = "c20260914-14b712";
}