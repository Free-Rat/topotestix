# flake.nix
{
  description = "NixOS config fuzzer";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      lib = nixpkgs.lib;
      pkgs = nixpkgs;

      fuzzer = import ./fuzzer.nix { inherit lib; };
      # fuzzer = import ./fuzzer-module.nix { inherit lib; };

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
    };

  # in {
  #   nixosConfigurations.test = lib.nixosSystem {
  #     inherit system;
  #
  #     modules = [
  #       ./template_config.nix
  #       (fuzzer {
  #         seed = "0"; # default seed
  #         fuzz = import ./fuzzed_options.nix { inherit pkgs; };
  #       })
  #     ];
  #   };
  # };
}
