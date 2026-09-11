import json
import os

from .nix import eval_json, eval_raw, nix_path, nix_string, project_nixpkgs_expr, resolve_path
from .reports import read_report_path
from .run_store import RunStore, default_runs_dir
from .targets import get_target


def compose_script_expr(project_root: str, target_name: str) -> str:
    target = get_target(project_root, target_name)
    if not target.report_node:
        raise ValueError(f"target {target_name!r} must define reportNode for runner compose-script")
    abs_runner = resolve_path("lib/runner.nix", project_root)
    return f"""let
  nixpkgs = {project_nixpkgs_expr(project_root)};
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;
  runner = import {nix_path(abs_runner)} {{ inherit pkgs lib; testers = pkgs.testers; }};
  testScript = builtins.readFile {nix_path(target.test_script)};
  propertiesMod = import {nix_path(target.properties)} {{ inherit lib; }};
in
runner.composeTestScript {{
  inherit testScript;
  properties = builtins.attrValues propertiesMod;
  reportNode = {nix_string(target.report_node)};
}}"""


def properties_expr(project_root: str, target_name: str) -> str:
    target = get_target(project_root, target_name)
    return f"""let
  nixpkgs = {project_nixpkgs_expr(project_root)};
  lib = nixpkgs.lib;
  propertiesMod = import {nix_path(target.properties)} {{ inherit lib; }};
in
builtins.attrNames propertiesMod"""


def cmd_compose_script(args, project_root: str) -> int:
    print(eval_raw(compose_script_expr(project_root, args.target)))
    return 0


def cmd_show_properties(args, project_root: str) -> int:
    names = eval_json(properties_expr(project_root, args.target))
    if args.json:
        print(json.dumps(names, indent=2))
    else:
        for name in names:
            print(name)
    return 0


def cmd_inspect_report(args, project_root: str) -> int:
    path = args.path_or_run_id
    if not os.path.exists(path):
        path = RunStore(default_runs_dir(project_root)).resolve_run(path)
    report = read_report_path(path)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    for entry in report:
        status = entry.get("status", "unknown").upper()
        line = f"{status}\t{entry.get('name', 'unnamed')}"
        if entry.get("message"):
            line += f"\t{entry['message']}"
        print(line)
    return 0
