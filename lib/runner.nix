# TopoTestix Runner
#
# Composes NixOS test scripts with property-based testing harness and calls
# testers.runNixOSTest. Property helpers are injected into the testScript and
# property checks are appended after the user script.
#
# composeTestScript:
#   Merges harness preamble, property setup, user testScript, auto-appended
#   property checks, and report footer into a single Python string.
#
# run:
#   Calls testers.runNixOSTest with the composed testScript and node configs.
#
# Report harness:
#   - _check() catches ALL exceptions and does NOT re-raise
#   - All properties are always evaluated; failing properties are logged
#   - Report written to /tmp/report.json in VM, copied out via copy_from_machine
#   - JSON base64-encoded to avoid shell escaping issues
#   - Property failures do not fail the NixOS VM derivation; TopoTestix marks
#     the run failed from report.json so structured failure data is preserved.
#
# See docs/runner.md for full design.

{ pkgs, lib, testers }:

let
  propsLib = import ./properties.nix { inherit lib; };

  harnessPreamble = ''
    import json
    import base64

    _report = []
    _all_passed = True

    def _check(name, fn, *args, **kwargs):
        global _all_passed
        try:
            fn(*args, **kwargs)
            _report.append({"name": name, "status": "passed"})
        except Exception as e:
            _report.append({"name": name, "status": "failed", "message": str(e)})
            _all_passed = False

    def _check_expected(name, fn, expect_failure, *args, **kwargs):
        """Record a deliberate contract violation separately from a defect."""
        global _all_passed
        try:
            fn(*args, **kwargs)
        except AssertionError as e:
            if expect_failure:
                _report.append({
                    "name": name,
                    "status": "expected_failure",
                    "message": str(e),
                })
            else:
                _report.append({"name": name, "status": "failed", "message": str(e)})
                _all_passed = False
        except Exception as e:
            # I/O, parsing, and programming errors are harness failures even when
            # the scenario is expected to violate its contract.
            _report.append({"name": name, "status": "failed", "message": str(e)})
            _all_passed = False
        else:
            if expect_failure:
                _report.append({
                    "name": name,
                    "status": "unexpected_pass",
                    "message": "the contract was expected to be violated",
                })
                _all_passed = False
            else:
                _report.append({"name": name, "status": "passed"})
  '';

  composeReportFooter = reportNode: ''
    encoded = base64.b64encode(json.dumps(_report).encode()).decode()
    ${reportNode}.succeed("echo " + "'" + encoded + "'" + " | base64 -d > /tmp/report.json")
    ${reportNode}.copy_from_machine("/tmp/report.json")
  '';

  composeTestScript = { testScript, properties, reportNode }:
    let
      composedProps = propsLib.composeProperties properties;
    in
    lib.concatStringsSep "\n" [
      harnessPreamble
      composedProps.setup
      testScript
      composedProps.check
      (composeReportFooter reportNode)
    ];

in
{
  inherit composeTestScript;

  run = { nodeConfigs, testScript, properties ? [], name, reportNode ? null }:
    let
      effectiveReportNode =
        if reportNode != null
        then reportNode
        else lib.head (builtins.attrNames nodeConfigs);

      fullTestScript = composeTestScript {
        inherit testScript properties;
        reportNode = effectiveReportNode;
      };

    in
    testers.runNixOSTest {
      inherit name;
      nodes = nodeConfigs;
      testScript = fullTestScript;
    };
}
