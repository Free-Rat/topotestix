{
  description = "VM harness for binary testing";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = {
    self,
    nixpkgs,
  }: let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
  in {
    packages.${system}.binary = pkgs.rustPlatform.buildRustPackage {
      pname = "tested-binary";
      version = "0.1.0";
      src = ./test_binary;
      cargoLock = ./test_binary/Cargo.lock;
    };

    # NixOS VM test
    nixosTests.vm-test = let
      testedBinary = self.packages.${system}.binary;
      testLib = import (nixpkgs + "/nixos/lib/testing-python.nix") {
        inherit system pkgs;
      };
    in
      testLib.makeTest {
        name = "binary-test";

        nodes.machine = {pkgs, ...}: {
          environment.systemPackages = [
            testedBinary
            pkgs.coreutils
          ];

          virtualisation.memorySize = 1024;
        };

        nodes.machine2 = {pkgs, ...}: {
          environment.systemPackages = [
            testedBinary
            pkgs.coreutils
          ];

          virtualisation.memorySize = 1024;
        };
        testScript = ''
          ${builtins.readFile ./test.py}
        '';
      };
  };
}
