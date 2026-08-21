{ lib }:

let
  combinators = import ../lib/combinators.nix { inherit lib; };
  fuzzerMod = import ../lib/fuzzer.nix { inherit lib; };
  expand-topology-mod = import ../lib/expand-topology.nix { inherit lib; };
  merge = import ../lib/merge.nix { inherit lib; };
  shrinker = import ../lib/shrinker.nix { inherit lib; };
  runnerMod = import ../lib/runner.nix { pkgs = null; inherit lib; testers = null; };

  fuzzer = fuzzerMod.fuzzer;
  expandTopology = expand-topology-mod.expandTopology;
  composeTestScript = runnerMod.composeTestScript;
in
(import ./combinators-test.nix { inherit lib; combinators = combinators; })
//
(import ./fuzzer-test.nix { inherit lib; fuzzer = fuzzer; })
//
(import ./expand-topology-test.nix { inherit lib; expand-topology = expandTopology; })
//
(import ./merge-test.nix { inherit lib; merge = merge; })
//
(import ./runner-test.nix { inherit lib; composeTestScript = composeTestScript; })
//
(import ./orchestrate-test.nix { inherit lib; fuzzer = fuzzer; expand-topology = expandTopology; merge = merge; })
//
(import ./shrinker-test.nix { inherit lib; fuzzer = fuzzer; shrinker = shrinker; expand-topology = expandTopology; })
//
(import ./targets-test.nix { inherit lib; })
