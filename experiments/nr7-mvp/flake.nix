{
  description = "NixOS config fuzzer + testing pipeline";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      lib = nixpkgs.lib;
      pkgs = nixpkgs.legacyPackages.${system};

      fuzzer = import ./fuzzer.nix { inherit lib; };

      kafka = import ./kafka-test { inherit lib; };

      mkSystem =
        seed:
        lib.nixosSystem {
          inherit system;

          modules = [
            ./template_config.nix
            (fuzzer {
              seed = toString seed;
              fuzz = import ./fuzzed_options.nix;
            })
          ];
        };

      seeds = builtins.genList (i: i + 1) 1000;

    in
    {
      nixosConfigurations = lib.genAttrs (map toString seeds) (s: mkSystem s);

      packages.${system} = {
        kafka = kafka.mkKafkaPackage { inherit pkgs; };
        default = kafka.mkKafkaPackage { inherit pkgs; };
      };

      nixosTests = {
        kafka-test = kafka.mkKafkaTest {
          inherit pkgs;
          testers = pkgs.testers;
          runNixOSTest = pkgs.testers.runNixOSTest;
          kafkaPackage = self.packages.${system}.kafka;
        };
      };
    };
}
