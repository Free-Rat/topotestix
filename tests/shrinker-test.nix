# Shrinker test suite
#
# Tests the shrinker module: apply, choicePaths, valueAt, optionsFor.
# The shrinker applies choice overrides to fuzzed output, enabling
# choice-based shrinking where lower indices produce simpler values.

{ lib, fuzzer, shrinker, expand-topology ? null, ... }:

let
  configTarget = {
    virtualisation.memorySize = [ 512 1024 2048 4096 ];
    services.openssh.enable = [ false true ];
    services.nginx.enable = [ false true ];
  };

  topologyTarget = {
    nodeCount = [ 1 3 5 ];
    roles.broker = [ 1 2 3 ];
    roles.controller = [ 1 ];
    brokerVlans = [ [ 1 ] [ 1 10 ] ];
    controllerVlans = [ [ 2 ] [ 2 10 ] ];
  };

in
{
  # choicePaths — lists all choice paths in a target spec

  testChoicePathsFlat = {
    expr = shrinker.choicePaths configTarget;
    expected = [ ".services.nginx.enable" ".services.openssh.enable" ".virtualisation.memorySize" ];
  };

  testChoicePathsTopology = {
    expr = shrinker.choicePaths topologyTarget;
    expected = [ ".brokerVlans" ".controllerVlans" ".nodeCount" ".roles.broker" ".roles.controller" ];
  };

  testChoicePathsEmpty = {
    expr = shrinker.choicePaths { x = 42; y = "hello"; };
    expected = [];
  };

  # valueAt — get value at specific index

  testValueAtFirst = {
    expr = shrinker.valueAt configTarget ".virtualisation.memorySize" 0;
    expected = 512;
  };

  testValueAtLast = {
    expr = shrinker.valueAt configTarget ".virtualisation.memorySize" 3;
    expected = 4096;
  };

  testValueAtMiddle = {
    expr = shrinker.valueAt configTarget ".virtualisation.memorySize" 2;
    expected = 2048;
  };

  testValueAtBool = {
    # bool is [false true], index 0 = false
    expr = shrinker.valueAt configTarget ".services.openssh.enable" 0;
    expected = false;
  };

  testValueAtBoolTrue = {
    expr = shrinker.valueAt configTarget ".services.openssh.enable" 1;
    expected = true;
  };

  # optionsFor — get the full option list for a path

  testOptionsForMemory = {
    expr = shrinker.optionsFor configTarget ".virtualisation.memorySize";
    expected = [ 512 1024 2048 4096 ];
  };

  testOptionsForBool = {
    expr = shrinker.optionsFor configTarget ".services.openssh.enable";
    expected = [ false true ];
  };

  testOptionsForVlans = {
    expr = shrinker.optionsFor topologyTarget ".brokerVlans";
    expected = [ [ 1 ] [ 1 10 ] ];
  };

  # apply — identity when choices_override is empty

  testApplyIdentity = {
    expr = shrinker.apply configTarget { virtualisation.memorySize = 2048; services.openssh.enable = true; services.nginx.enable = false; } {};
    expected = { virtualisation.memorySize = 2048; services.openssh.enable = true; services.nginx.enable = false; };
  };

  # apply — override a single path

  testApplyOverrideSingle = {
    expr = shrinker.apply configTarget
      { virtualisation.memorySize = 4096; services.openssh.enable = true; services.nginx.enable = true; }
      { ".virtualisation.memorySize" = 0; };
    expected = { virtualisation.memorySize = 512; services.openssh.enable = true; services.nginx.enable = true; };
  };

  # apply — override multiple paths

  testApplyOverrideMultiple = {
    expr = shrinker.apply configTarget
      { virtualisation.memorySize = 4096; services.openssh.enable = true; services.nginx.enable = true; }
      { ".virtualisation.memorySize" = 0; ".services.openssh.enable" = 0; };
    expected = { virtualisation.memorySize = 512; services.openssh.enable = false; services.nginx.enable = true; };
  };

  # apply — override to simplest value (index 0)

  testApplyOverrideToSimplest = {
    expr = shrinker.apply configTarget
      { virtualisation.memorySize = 2048; services.openssh.enable = true; services.nginx.enable = true; }
      { ".virtualisation.memorySize" = 0; ".services.nginx.enable" = 0; };
    expected = { virtualisation.memorySize = 512; services.openssh.enable = true; services.nginx.enable = false; };
  };

  # apply — override topology VLANs

  testApplyOverrideVlans = {
    expr = shrinker.apply topologyTarget
      { nodeCount = 3; roles.broker = 2; roles.controller = 1; brokerVlans = [ 1 10 ]; controllerVlans = [ 2 10 ]; }
      { ".brokerVlans" = 0; ".controllerVlans" = 0; };
    expected = { nodeCount = 3; roles.broker = 2; roles.controller = 1; brokerVlans = [ 1 ]; controllerVlans = [ 2 ]; };
  };

  # Integration: fuzzer → shrinker pipeline

  testFuzzerThenShrinkerIdentity = {
    # Shrinker with empty overrides returns fuzzer result unchanged
    expr =
      let
        fuzzed = fuzzer { seed = "42"; target = configTarget; };
      in
      shrinker.apply configTarget fuzzed.result {};
    expected =
      (fuzzer { seed = "42"; target = configTarget; }).result;
  };

  testFuzzerThenShrinkerOverride = {
    # Override fuzzer choice to simpler value
    expr =
      let
        fuzzed = fuzzer { seed = "42"; target = configTarget; };
      in
      shrinker.apply configTarget fuzzed.result { ".virtualisation.memorySize" = 0; };
    expected =
      let
        fuzzed2 = fuzzer { seed = "42"; target = configTarget; };
      in
      fuzzed2.result // { virtualisation.memorySize = 512; };
  };

  testFuzzerChoiceKeysExistInShrinkerPaths = {
    expr =
      let
        fuzzed = fuzzer { seed = "42"; target = configTarget; };
        paths = shrinker.choicePaths configTarget;
      in
      builtins.all (path: builtins.elem path paths) (builtins.attrNames fuzzed.choices);
    expected = true;
  };

  testFuzzerChoicesDirectlyUsableWithShrinker = {
    expr =
      let
        fuzzed = fuzzer { seed = "42"; target = configTarget; };
        firstChoice = builtins.head (builtins.attrNames fuzzed.choices);
        overrides = { ${firstChoice} = fuzzed.choices.${firstChoice}; };
      in
      shrinker.apply configTarget fuzzed.result overrides;
    expected = (fuzzer { seed = "42"; target = configTarget; }).result;
  };

  testTopologyPipelineFuzzerShrinkerExpand = {
    expr =
      let
        fuzzed = fuzzer { seed = "42"; target = topologyTarget; };
        shrunk = shrinker.apply topologyTarget fuzzed.result {
          ".roles.broker" = 0;
          ".brokerVlans" = 0;
        };
        expanded = expand-topology { topology-map = shrunk; };
      in
      {
        nodes = builtins.attrNames expanded.nodeConfigs;
        brokerVlans = expanded.nodeConfigs.broker1.virtualisation.vlans;
      };
    expected = {
      nodes = [ "broker1" "controller1" ];
      brokerVlans = [ 1 ];
    };
  };

  testShrinkerRejectsInvalidPath = {
    expr = (builtins.tryEval (builtins.deepSeq (shrinker.apply configTarget {} { ".doesNotExist" = 0; }) true)).success;
    expected = false;
  };

  testShrinkerRejectsInvalidPathFormat = {
    expr = (builtins.tryEval (builtins.deepSeq (shrinker.apply configTarget {} { "virtualisation.memorySize" = 0; }) true)).success;
    expected = false;
  };

  testShrinkerRejectsOutOfRangeIndex = {
    expr = (builtins.tryEval (builtins.deepSeq (shrinker.apply configTarget {} { ".virtualisation.memorySize" = 99; }) true)).success;
    expected = false;
  };

  # Nested target: choicePaths, valueAt, optionsFor

  testChoicePathsNested = {
    expr = shrinker.choicePaths { virtualisation = { memorySize = [ 512 1024 2048 ]; diskSize = [ 1024 2048 ]; }; };
    expected = [ ".virtualisation.diskSize" ".virtualisation.memorySize" ];
  };

  testValueAtNested = {
    expr = shrinker.valueAt { virtualisation = { memorySize = [ 512 1024 2048 ]; }; } ".virtualisation.memorySize" 1;
    expected = 1024;
  };

  testOptionsForNested = {
    expr = shrinker.optionsFor { virtualisation = { memorySize = [ 512 1024 2048 ]; }; } ".virtualisation.memorySize";
    expected = [ 512 1024 2048 ];
  };

  testDottedAttributePath = {
    expr = shrinker.apply
      { services.rabbitmq.configItems."disk_free_limit.absolute" = [ 50 100 200 ]; }
      { services.rabbitmq.configItems."disk_free_limit.absolute" = 200; }
      { ".services.rabbitmq.configItems.disk_free_limit.absolute" = 0; };
    expected = { services.rabbitmq.configItems."disk_free_limit.absolute" = 50; };
  };

  testDottedAttributeValueAt = {
    expr = shrinker.valueAt
      { services.rabbitmq.configItems."disk_free_limit.absolute" = [ 50 100 200 ]; }
      ".services.rabbitmq.configItems.disk_free_limit.absolute"
      1;
    expected = 100;
  };

  testRejectsAmbiguousNestedAndDottedPaths = {
    expr = (builtins.tryEval (builtins.deepSeq (shrinker.choicePaths {
      a.b = [ 1 2 ];
      "a.b" = [ 3 4 ];
    }) true)).success;
    expected = false;
  };
}
