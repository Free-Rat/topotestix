{ lib, composeTestScript }:

let
  simpleResult = composeTestScript {
    testScript = "machine.succeed('hello')";
    properties = [];
    reportNode = "machine";
  };

  singleProp = [
    { name = "nginx-responds";
      setup = ''
        def check_nginx(machine):
            machine.succeed("curl localhost")
      '';
      check = ''
        _check("nginx-responds", check_nginx, machine)
      '';
    }
  ];

  propsResult = composeTestScript {
    testScript = "machine.succeed('nginx -t')";
    properties = singleProp;
    reportNode = "broker1";
  };

  indexOf = substr: str:
    let
      totalLen = builtins.stringLength str;
      subLen = builtins.stringLength substr;
      go = i:
        if i + subLen > totalLen
        then -1
        else if builtins.substring i subLen str == substr
        then i
        else go (i + 1);
    in
    go 0;
in
{
  testComposeTestScriptContainsHarness = {
    expr =
      lib.hasInfix "_report = []" simpleResult
      && lib.hasInfix "_all_passed = True" simpleResult
      && lib.hasInfix "def _check(" simpleResult;
    expected = true;
  };

  testComposeTestScriptContainsImports = {
    expr =
      lib.hasInfix "import json" simpleResult
      && lib.hasInfix "import base64" simpleResult;
    expected = true;
  };

  testComposeTestScriptContainsReportFooter = {
    expr =
      lib.hasInfix "copy_from_machine" simpleResult
      && lib.hasInfix "/tmp/report.json" simpleResult
      && lib.hasInfix "base64 -d" simpleResult;
    expected = true;
  };

  testComposeTestScriptReportNodeMachine = {
    expr =
      lib.hasInfix "machine.succeed" simpleResult
      && lib.hasInfix "machine.copy_from_machine" simpleResult;
    expected = true;
  };

  testComposeTestScriptReportNodeCustom = {
    expr =
      lib.hasInfix "broker1.succeed" propsResult
      && lib.hasInfix "broker1.copy_from_machine" propsResult;
    expected = true;
  };

  testComposeTestScriptPropertySetup = {
    expr = lib.hasInfix "def check_nginx(machine):" propsResult;
    expected = true;
  };

  testComposeTestScriptPropertyCheck = {
    expr = lib.hasInfix "_check" propsResult;
    expected = true;
  };

  testComposeTestScriptUserTestScript = {
    expr = lib.hasInfix "machine.succeed('nginx -t')" propsResult;
    expected = true;
  };

  testComposeTestScriptDoesNotRaiseOnPropertyFailure = {
    expr = !(lib.hasInfix "raise AssertionError" simpleResult);
    expected = true;
  };

  testExpectedFailureOnlyClassifiesAssertions = {
    expr =
      lib.hasInfix "except AssertionError as e:" simpleResult
      && lib.hasInfix "except Exception as e:" simpleResult;
    expected = true;
  };

  testComposeTestScriptPreambleBeforeFooter = {
    expr =
      (indexOf "_report = []" simpleResult) < (indexOf "copy_from_machine" simpleResult);
    expected = true;
  };

  testComposeTestScriptSetupBeforeCheck = {
    expr =
      (indexOf "def check_nginx" propsResult) < (indexOf "_check(\"nginx-responds\"" propsResult);
    expected = true;
  };
}
