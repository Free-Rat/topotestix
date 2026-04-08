{ lib }:

let
  mkKafkaPackage = { pkgs }:
    pkgs.apacheKafka;

  mkKafkaTest = { pkgs, testers, runNixOSTest, kafkaPackage, nodeConfig ? {}, seed ? null }:
    let
      testName = if seed != null then "kafka-test-${toString seed}" else "kafka-test";
      baseConfig = {
        environment.systemPackages = [
          kafkaPackage
          pkgs.coreutils
          pkgs.procps
          pkgs.util-linux
          pkgs.jre
        ];

        environment.sessionVariables = {
          KAFKA_HOME = "${kafkaPackage}";
        };

        virtualisation.memorySize = 2048;
        virtualisation.diskSize = 5120;
      };
    in
    runNixOSTest {
      name = testName;

      nodes = {
        machine =
          { pkgs, ... }:
          builtins.removeAttrs (lib.recursiveUpdate baseConfig nodeConfig) ["machine"];
      };

      testScript =
        { nodes, ... }:
        ''
          machine.succeed("which kafka-topics.sh")
          machine.succeed("ls ${kafkaPackage}/bin/")
          machine.succeed("ls ${kafkaPackage}/config/")

          result = machine.succeed("java -version")
          machine.log(result)

          result = machine.succeed("${kafkaPackage}/bin/kafka-topics.sh --version")
          machine.log(f"Kafka version: {result}")

          machine.succeed("mkdir -p /tmp/zookeeper")
          machine.succeed("mkdir -p /tmp/kafka-logs")
        '';
    };
in
{
  inherit mkKafkaPackage mkKafkaTest;
}
