{
  description = "VM harness for binary testing";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system}.binary = pkgs.stdenv.mkDerivation {
        name = "tested-binary";
        src = ./binary;

        dontUnpack = true;

        nativeBuildInputs = [ pkgs.autoPatchelfHook ];

        buildInputs = [
          pkgs.glibc
          pkgs.stdenv.cc.cc.lib
        ];

        installPhase = ''
          mkdir -p $out/bin
          cp $src $out/bin/binary
          chmod +x $out/bin/binary
        '';
      };
      nixosTests.vm-test =
        let
          testedBinary = self.packages.${system}.binary;
        in
        pkgs.testers.runNixOSTest {
          name = "binary-test";

          nodes = {
            machine =
              { pkgs, ... }:
              {
                environment.systemPackages = [
                  testedBinary
                  pkgs.coreutils

                  pkgs.file
                  pkgs.binutils
                  pkgs.strace
                ];

                virtualisation.memorySize = 1024;
              };
          };

          testScript =
            { nodes, ... }:
            ''
            ${builtins.readFile ./test.py}
            '';
        };
    };
}
