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

      kafka = import ./kafka-test.nix { inherit lib; };

      mkKafkaTest = seed:
        let
          fuzzedNodeConfig = fuzzer {
            seed = toString seed;
            fuzz = import ./fuzzed_nodes.nix;
          };
        in
        kafka.mkKafkaTest {
          inherit pkgs;
          testers = pkgs.testers;
          runNixOSTest = pkgs.testers.runNixOSTest;
          kafkaPackage = self.packages.${system}.kafka;
          nodeConfig = fuzzedNodeConfig.config;
          seed = seed;
        };

      seeds = builtins.genList (i: i + 1) 10;

    in
    {
      packages.${system} = {
        kafka = kafka.mkKafkaPackage { inherit pkgs; };
        default = kafka.mkKafkaPackage { inherit pkgs; };
      };

      nixosTests = lib.genAttrs (map toString seeds) (s: mkKafkaTest s);
    };
}
