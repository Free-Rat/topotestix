let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  orchestrate = (import (builtins.toPath "/home/freerat/projects/topotestix/lib/orchestrate.nix") { inherit pkgs lib; testers = pkgs.testers; }).orchestrate;

  topologyTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/topology.nix") { inherit lib; };
  configTarget = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/config.nix") { inherit lib; };
  baseModule = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/module.nix");
  testScript = builtins.readFile (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/test-script.py");
  propertiesMod = import (builtins.toPath "/home/freerat/projects/topotestix/targets/etcd-cluster/properties.nix") { inherit lib; };
in
orchestrate {
  seed = 1;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "etcd-v2-exhaustive-rep0-cell090";
  reportNode = "etcd1";
  topologyChoices = (builtins.fromJSON "{\".etcdVlans\": 0, \".roles.etcd\": 0}");
  configChoices = (builtins.fromJSON "{\"etcd\": {\".services.etcd.extraConf.ELECTION_TIMEOUT\": 1, \".services.etcd.extraConf.HEARTBEAT_INTERVAL\": 1, \".services.etcd.extraConf.QUOTA_BACKEND_BYTES\": 0, \".services.etcd.extraConf.SNAPSHOT_COUNT\": 0, \".virtualisation.diskSize\": 1, \".virtualisation.memorySize\": 1}}");
  repetitionToken = "c20260910-6335ae";
}