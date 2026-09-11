{
  lib,
  fuzzer,
  shrinker,
  expandTopology,
}:

let
  topologyTarget = import ../targets/kafka-topology/topology.nix { inherit lib; };
  configTarget = import ../targets/kafka-topology/config.nix { inherit lib; };
  fuzzedTopology =
    (fuzzer {
      seed = "1";
      target = topologyTarget;
    }).result;
  fuzzedConfig =
    (fuzzer {
      seed = "2";
      target = configTarget;
    }).result;
  topologyAt =
    index:
    shrinker.apply topologyTarget fuzzedTopology {
      ".clientVlans" = index;
    };
  configAt =
    placement: intervention:
    shrinker.apply configTarget fuzzedConfig {
      ".environment.etc.topotestix-kafka-placement.json.text" = placement;
      ".environment.etc.topotestix-kafka-intervention.text" = intervention;
    };
  shared = topologyAt 0;
  separated = topologyAt 1;
  sharedExpansion = expandTopology { topology-map = shared; };
  separatedExpansion = expandTopology { topology-map = separated; };
in
{
  testKafkaTopologyHasFiveBrokersAndOneClient = {
    expr = shared.roles;
    expected = {
      client = 1;
      kafka = 5;
    };
  };

  testKafkaTopologySharedClientPlane = {
    expr = {
      client = sharedExpansion.nodeConfigs.client1.virtualisation.vlans;
      brokers = map (name: sharedExpansion.nodeConfigs.${name}.virtualisation.vlans) [
        "kafka1"
        "kafka2"
        "kafka3"
        "kafka4"
        "kafka5"
      ];
    };
    expected = {
      client = [ 10 ];
      brokers = [
        [
          10
          20
        ]
        [
          10
          20
        ]
        [
          10
          20
        ]
        [
          10
          20
        ]
        [
          10
          20
        ]
      ];
    };
  };

  testKafkaTopologySeparatedClientPlane = {
    expr = separatedExpansion.nodeConfigs.client1.virtualisation.vlans;
    expected = [ 20 ];
  };

  testKafkaTopologySpreadPlacementManifest = {
    expr = builtins.fromJSON ((configAt 0 0).environment.etc."topotestix-kafka-placement.json".text);
    expected = {
      profile = "spread";
      replicas = [
        1
        3
        5
      ];
      failed_rack = "rack-a";
    };
  };

  testKafkaTopologyConcentratedRackKillManifest = {
    expr = {
      placement = builtins.fromJSON (
        (configAt 1 2).environment.etc."topotestix-kafka-placement.json".text
      );
      intervention = (configAt 1 2).environment.etc.topotestix-kafka-intervention.text;
    };
    expected = {
      placement = {
        profile = "concentrated";
        replicas = [
          1
          2
          3
        ];
        failed_rack = "rack-a";
      };
      intervention = "rack-kill";
    };
  };
}
