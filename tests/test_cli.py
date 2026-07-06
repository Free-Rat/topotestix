import unittest
from unittest.mock import patch

from topotestix.cli import build_parser
from topotestix.orchestrator import (
    generate_inspect_expr,
    parse_seed_range,
    reproduce_command,
    sweep_events,
)
from topotestix.targets import Target


class CliTests(unittest.TestCase):
    def test_orchestrator_run_accepts_target_seed(self):
        args = build_parser().parse_args(["orchestrator", "run", "kafka", "--seed", "7"])

        self.assertEqual(args.command, "orchestrator")
        self.assertEqual(args.orchestrator_command, "run")
        self.assertEqual(args.target, "kafka")
        self.assertEqual(args.seed, 7)

    def test_targets_list_accepts_local_project_root(self):
        args = build_parser().parse_args(["targets", "list", "--project-root", "."])

        self.assertEqual(args.command, "targets")
        self.assertEqual(args.targets_command, "list")
        self.assertEqual(args.project_root, ".")

    def test_global_project_root_survives_subparser_defaults(self):
        args = build_parser().parse_args(["--project-root", "/repo", "targets", "list"])

        self.assertEqual(args.project_root, "/repo")

    def test_seed_range_parses_inclusive_range(self):
        self.assertEqual(parse_seed_range("2..4"), [2, 3, 4])

    def test_seed_range_parses_comma_list(self):
        self.assertEqual(parse_seed_range("1,3,5"), [1, 3, 5])

    def test_runs_list_accepts_output_dir(self):
        args = build_parser().parse_args(["runs", "list", "--output-dir", "/tmp/runs"])

        self.assertEqual(args.output_dir, "/tmp/runs")

    def test_reproduce_command_includes_target_paths(self):
        target = Target(
            name="nginx",
            description="",
            topology_target="targets/nginx/topology.nix",
            config_target="targets/nginx/config.nix",
            base_module="targets/nginx/module.nix",
            test_script="targets/nginx/test-script.py",
            properties="targets/nginx/properties.nix",
            report_node="machine1",
        )

        command = reproduce_command("/repo", target, 4, "nginx-fail", {}, {})

        self.assertIn("--project-root /repo", command)
        self.assertIn("--topology-target targets/nginx/topology.nix", command)
        self.assertIn("--properties targets/nginx/properties.nix", command)

    def test_generated_inspect_expression_contains_topology_and_role_fuzz(self):
        expr = generate_inspect_expr(
            3,
            "targets/nginx/topology.nix",
            "targets/nginx/config.nix",
            "/repo",
        )

        self.assertIn("topologyChoices = fuzzedTopology.choices;", expr)
        self.assertIn("roleFuzz", expr)
        self.assertIn("expandTopology", expr)

    def test_sweep_events_reports_failures(self):
        target = Target(
            name="nginx",
            description="",
            topology_target="targets/nginx/topology.nix",
            config_target="targets/nginx/config.nix",
            base_module="targets/nginx/module.nix",
            test_script="targets/nginx/test-script.py",
            properties="targets/nginx/properties.nix",
            report_node="machine1",
        )
        fake_result = type("Result", (), {"returncode": 1})()

        with patch(
            "topotestix.orchestrator.run_once", return_value=(False, [], "/tmp/run", fake_result)
        ):
            events = list(sweep_events("/repo", target, [4], fail_fast=True))

        self.assertEqual(events[0].type, "sweep_started")
        self.assertEqual(events[2].type, "run_failed")
        self.assertEqual(events[-1].data["failures"], 1)


if __name__ == "__main__":
    unittest.main()
