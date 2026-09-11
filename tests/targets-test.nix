{ lib }:

let
  targets = import ../targets/default.nix;
  requiredPaths = target: [
    target.topologyTarget
    target.configTarget
    target.baseModule
    target.testScript
    target.properties
  ];
in
{
  testRegisteredTargetFilesExist = {
    expr = lib.all (target: lib.all builtins.pathExists (requiredPaths target))
      (builtins.attrValues targets);
    expected = true;
  };

  testThesisRabbitMqTargetsRegistered = {
    expr =
      targets ? rabbitmq-disk
      && targets ? rabbitmq-crash
      && targets ? rabbitmq-failure-domain;
    expected = true;
  };

  testThesisKafkaTopologyTargetRegistered = {
    expr =
      targets ? kafka-topology
      && builtins.pathExists ../targets/kafka-topology/KafkaTopologyWorkload.java
      && builtins.pathExists ../targets/kafka-topology/oracle.py;
    expected = true;
  };
}
