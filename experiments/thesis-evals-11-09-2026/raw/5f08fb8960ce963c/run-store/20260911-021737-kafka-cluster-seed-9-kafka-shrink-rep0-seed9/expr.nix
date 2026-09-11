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
  seed = 9;
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = "kafka-shrink-rep0-seed9";
  reportNode = "kafka1";
  topologyChoices = (builtins.fromJSON "{\".kafkaVlans\": 0, \".roles.kafka\": 0}");
  configChoices = (builtins.fromJSON "{\"kafka\": {\".services.apache-kafka.jvmOptions\": 0, \".services.apache-kafka.settings.auto.create.topics.enable\": 0, \".services.apache-kafka.settings.default.replication.factor\": 0, \".services.apache-kafka.settings.log.retention.hours\": 0, \".services.apache-kafka.settings.log.segment.bytes\": 0, \".services.apache-kafka.settings.message.max.bytes\": 1, \".services.apache-kafka.settings.min.insync.replicas\": 1, \".services.apache-kafka.settings.num.io.threads\": 0, \".services.apache-kafka.settings.num.network.threads\": 0, \".services.apache-kafka.settings.offsets.topic.replication.factor\": 1, \".services.apache-kafka.settings.replica.fetch.max.bytes\": 2, \".services.apache-kafka.settings.transaction.state.log.min.isr\": 1, \".services.apache-kafka.settings.transaction.state.log.replication.factor\": 0, \".services.apache-kafka.settings.unclean.leader.election.enable\": 1, \".virtualisation.diskSize\": 1, \".virtualisation.memorySize\": 1}}");
  repetitionToken = "c20260910-6335ae";
}