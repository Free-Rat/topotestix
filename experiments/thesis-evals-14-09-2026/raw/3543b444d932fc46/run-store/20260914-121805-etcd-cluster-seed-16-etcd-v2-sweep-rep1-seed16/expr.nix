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

  topologyTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/topology.nix") { inherit lib; };
  configTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/config.nix") { inherit lib; };
  baseModule = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/module.nix");
  testScript = builtins.readFile (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/test-script.py");
  propertiesMod = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/properties.nix") { inherit lib; };
in
orchestrate {
  seed = 16;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "etcd-v2-sweep-rep1-seed16";
  reportNode = "etcd1";
  topologyChoices = (builtins.fromJSON "{}");
  configChoices = (builtins.fromJSON "{}");
  repetitionToken = "c20260914-14b712";
}