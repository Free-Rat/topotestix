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
              start_all()

              # machine = nodes.machine

              machine.succeed("ls /run/current-system/sw/bin/binary")

              result = machine.succeed("ls -l /run/current-system/sw/bin/binary")
              machine.log(result)

              # machine.shell_interact()

              result = machine.succeed("/run/current-system/sw/bin/binary")
              print(result)

              result = machine.succeed("time /run/current-system/sw/bin/binary")
              print(result)

              result = machine.succeed("/run/current-system/sw/bin/binary")
              print(result)
            '';
        };
    };
}
