import json
import os
import subprocess
import tempfile
from typing import Optional


def resolve_path(path: str, project_root: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(os.path.abspath(project_root), path))


def nix_string(value: str) -> str:
    return json.dumps(value)


def nix_path(path: str) -> str:
    return f"(builtins.toPath {nix_string(path)})"


def nix_json(value) -> str:
    return f"(builtins.fromJSON {nix_string(json.dumps(value, sort_keys=True))})"


def project_nixpkgs_expr(project_root: str) -> str:
    flake_root = resolve_path(".", project_root)
    allowed_paths = [
        flake_root,
        os.path.join(flake_root, "flake.nix"),
        os.path.join(flake_root, "flake.lock"),
    ]
    allowed_paths_expr = "[ " + " ".join(nix_string(path) for path in allowed_paths) + " ]"
    return f"""(builtins.getFlake (builtins.unsafeDiscardStringContext (toString (builtins.path {{
  path = {nix_path(flake_root)};
  name = "topotestix-locked-flake";
  filter = path: _: builtins.elem (toString path) {allowed_paths_expr};
}})))).inputs.nixpkgs"""


def nix_base_command(command: str) -> list[str]:
    return [
        "nix",
        command,
        "--impure",
        "--no-update-lock-file",
        "--extra-experimental-features",
        "nix-command flakes",
    ]


def eval_json(nix_expr: str) -> dict:
    result = subprocess.run(
        nix_base_command("eval") + ["--json", "--expr", nix_expr],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"nix eval failed:\n{result.stderr}")
    return json.loads(result.stdout)


def eval_raw(nix_expr: str) -> str:
    result = subprocess.run(
        nix_base_command("eval") + ["--raw", "--expr", nix_expr],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"nix eval failed:\n{result.stderr}")
    return result.stdout


def build_test(
    nix_expr: str, output_link: str, expr_path: Optional[str] = None
) -> subprocess.CompletedProcess:
    if expr_path:
        with open(expr_path, "w") as f:
            f.write(nix_expr)
        temp_path = expr_path
        cleanup = False
    else:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".nix", delete=False) as f:
            f.write(nix_expr)
            f.flush()
            temp_path = f.name
        cleanup = True

    try:
        return subprocess.run(
            nix_base_command("build") + ["--file", temp_path, "-o", output_link, "-L"],
            capture_output=True,
            text=True,
        )
    finally:
        if cleanup:
            os.unlink(temp_path)
