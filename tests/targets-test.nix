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
}
