{
  description = "TopoTestix — environment-aware property-based testing for distributed systems";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    nix-unit.url = "github:nix-community/nix-unit";
    nix-unit.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    { self, nixpkgs, nix-unit }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      lib = nixpkgs.lib;

      topotestixLib = import ./lib { inherit lib; };

    in
    {
      lib = topotestixLib;

      tests = import ./tests { inherit lib; };

      packages.${system} = {
        default = pkgs.python3Packages.buildPythonApplication {
          pname = "topotestix";
          version = "0.1.0";
          src = self;
          pyproject = true;
          build-system = [ pkgs.python3Packages.setuptools ];
          doCheck = false;
        };
      };

      checks.${system} = {
        default = pkgs.runCommand "tests" {
          nativeBuildInputs = [ nix-unit.packages.${system}.default ];
        } ''
          export HOME="$TMPDIR"
          mkdir -p "$HOME/.cache/nix"
          nix-unit --eval-store "$TMPDIR/eval-store" \
            --extra-experimental-features flakes \
            --override-input nixpkgs ${nixpkgs} \
            --flake ${self}#tests
          touch $out
        '';

        python = pkgs.runCommand "python-tests" {
          nativeBuildInputs = [ pkgs.python3 ];
        } ''
          cp -r ${self} source
          chmod -R u+w source
          cd source
          python3 -m unittest discover -s tests -p 'test_*.py'
          touch $out
        '';
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          nix-unit.packages.${system}.default
          python3
          python3Packages.black
          ruff
        ];

        shellHook = ''
          alias runtest='nix-unit --expr "import ./tests { lib = (import <nixpkgs> {}).lib; }" && python3 -m unittest discover -s tests -p "test_*.py"'
        '';
      };
    };
}
