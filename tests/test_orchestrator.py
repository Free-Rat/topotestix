import argparse
import os
import unittest
from unittest.mock import patch

from topotestix.nix import nix_base_command, nix_path, nix_string, project_nixpkgs_expr
from topotestix.orchestrator import (
    generate_fuzz_expr,
    generate_inspect_expr,
    generate_nix_expr,
    generate_shrink_inputs_expr,
    parse_json_object,
)
from topotestix.runner import compose_script_expr, properties_expr
from topotestix.targets import Target


class OrchestratorRenderingTests(unittest.TestCase):
    def test_nix_string_escapes_quotes(self):
        self.assertEqual(nix_string('name "with" quotes'), '"name \\"with\\" quotes"')

    def test_nix_path_uses_string_boundary(self):
        self.assertEqual(
            nix_path("/tmp/path with spaces/file.nix"),
            '(builtins.toPath "/tmp/path with spaces/file.nix")',
        )

    def test_project_nixpkgs_expr_uses_filtered_project_flake(self):
        expr = project_nixpkgs_expr("/tmp/project with spaces")
        self.assertIn("builtins.path", expr)
        self.assertIn('(builtins.toPath "/tmp/project with spaces")', expr)
        self.assertIn('"/tmp/project with spaces/flake.nix"', expr)
        self.assertIn('"/tmp/project with spaces/flake.lock"', expr)
        self.assertIn("filter = path: _: builtins.elem", expr)
        self.assertNotIn(
            '(builtins.getFlake (toString (builtins.toPath "/tmp/project with spaces")))',
            expr,
        )
        self.assertIn(".inputs.nixpkgs", expr)

    def test_nix_commands_do_not_update_the_project_lock(self):
        self.assertIn("--no-update-lock-file", nix_base_command("eval"))

    def test_parse_json_object_rejects_non_object(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_json_object("[]", "--config-choices")

    def test_generated_expression_uses_json_choices_and_escaped_name(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        expr = generate_nix_expr(
            seed=1,
            topology_target_path="targets/nginx/topology.nix",
            config_target_path="targets/nginx/config.nix",
            base_module_path="targets/nginx/module.nix",
            test_script_path="targets/nginx/test-script.py",
            properties_path="targets/nginx/properties.nix",
            name='nginx "quoted" test',
            project_root=project_root,
            topology_choices={".roles.machine": 0},
            config_choices={"machine": {".services.nginx.enable": 0}},
        )

        self.assertIn('name = "nginx \\"quoted\\" test";', expr)
        self.assertIn("reportNode = null;", expr)
        self.assertIn("topologyChoices = (builtins.fromJSON", expr)
        self.assertIn("configChoices = (builtins.fromJSON", expr)
        self.assertIn("builtins.toPath", expr)

    def test_generated_fuzz_expression_uses_safe_seed_and_path(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        expr = generate_fuzz_expr('seed "quoted"', "targets/nginx/config.nix", project_root)

        self.assertIn('seed = "seed \\"quoted\\"";', expr)
        self.assertIn("target = import (builtins.toPath", expr)
        self.assertIn("lib/fuzzer.nix", expr)

    def test_runtime_expressions_use_project_flake_nixpkgs(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = Target(
            name="nginx",
            description="test",
            topology_target=os.path.join(project_root, "targets/nginx/topology.nix"),
            config_target=os.path.join(project_root, "targets/nginx/config.nix"),
            base_module=os.path.join(project_root, "targets/nginx/module.nix"),
            test_script=os.path.join(project_root, "targets/nginx/test-script.py"),
            properties=os.path.join(project_root, "targets/nginx/properties.nix"),
            report_node="machine1",
        )
        inspect_expr = generate_inspect_expr(
            1, target.topology_target, target.config_target, project_root
        )
        self.assertNotIn("apacheKafka", inspect_expr)
        expressions = [
            generate_nix_expr(
                1,
                target.topology_target,
                target.config_target,
                target.base_module,
                target.test_script,
                target.properties,
                "test",
                project_root,
            ),
            generate_shrink_inputs_expr(
                1, target.topology_target, target.config_target, project_root
            ),
            generate_fuzz_expr("1", target.config_target, project_root),
            inspect_expr,
        ]
        with patch("topotestix.runner.get_target", return_value=target):
            expressions.extend(
                [
                    compose_script_expr(project_root, target.name),
                    properties_expr(project_root, target.name),
                ]
            )

        for expr in expressions:
            self.assertIn(".inputs.nixpkgs", expr)
            self.assertNotIn('builtins.getFlake "nixpkgs"', expr)


if __name__ == "__main__":
    unittest.main()
