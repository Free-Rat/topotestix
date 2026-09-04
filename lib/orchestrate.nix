# TopoTestix Orchestrate
#
# Composes the full fuzzer → shrinker → expandTopology → merge → runner pipeline.
#
# This is the central Nix function that ties all modules together. The Python
# orchestrator (orchestrator.py) generates a Nix expression that calls this
# function, then builds it with `nix build`.
#
# All Nix-type computation happens here — the fuzzer, shrinker, expandTopology,
# mkForce merge, and runner all operate on Nix types that can't be serialized
# through Python (module functions, mkForce values, etc.).
#
# Seed derivation:
#   master_seed is an integer. Seeds for each dimension are derived as strings:
#     str(master_seed)                  → topology (fuzzer seed)
#     str(master_seed + 1 + roleIndex)  → per-role config (fuzzer seeds)
#   Role index is alphabetical: broker=0, controller=1, machine=0, etc.
#   All nodes of the same role share one fuzzer call (identical config).
#
# Shrinking parameters:
#   topologyChoices — choice overrides for topology (empty = no shrinking)
#   configChoices   — choice overrides per role (empty = no shrinking)
#   When empty, the shrinker is the identity function.
#   See docs/shrinking.md for details.
#
# Example — single-node nginx test:
#
#   orchestrate {
#     seed = 5;
#     topologyTarget = { roles.machine = [ 1 ]; machineVlans = [ [ 1 ]; };
#     configTarget = import ./targets/nginx/config.nix { inherit lib; };
#     baseModule = import ./targets/nginx/module.nix;
#     testScript = builtins.readFile ./targets/nginx/test-script.py;
#     properties = builtins.attrValues (import ./targets/nginx/properties.nix { inherit lib; });
#     name = "nginx-smoke";
#   }
#
# Example — multi-node Kafka test with shrinking:
#
#   orchestrate {
#     seed = 42;
#     topologyTarget = import ./targets/kafka/topology.nix { inherit lib; };
#     configTarget = import ./targets/kafka/config.nix { inherit lib; };
#     baseModule = import ./targets/kafka/module.nix;
#     testScript = builtins.readFile ./targets/kafka/test-script.py;
#     properties = builtins.attrValues (import ./targets/kafka/properties.nix { inherit lib; });
#     name = "kafka-cluster";
#     topologyChoices = { ".nodeCount" = 0; };
#     configChoices = { broker = { ".virtualisation.memorySize" = 0; }; };
#   }

{ pkgs, lib, testers }:

let
  fuzzerMod = import ./fuzzer.nix { inherit lib; };
  expandTopologyMod = import ./expand-topology.nix { inherit lib; };
  mergeMod = import ./merge.nix { inherit lib; };
  shrinkerMod = import ./shrinker.nix { inherit lib; };
  runnerMod = import ./runner.nix { inherit pkgs lib testers; };

in
{
  orchestrate = { seed
                , topologyTarget
                , configTarget
                , baseModule
                , testScript
                , properties
                , name
                , reportNode ? null
                , topologyChoices ? {}
                , configChoices ? {}
                , repetitionToken ? null  # forces a fresh VM run; excluded from SUT identity
                }:
    let
      # Step 1: Fuzz the topology target to get a topology-map
      seedStr = toString seed;
      fuzzedTopology = fuzzerMod.fuzzer {
        seed = seedStr;
        target = topologyTarget;
      };

      # Step 2: Apply shrinking overrides (identity when topologyChoices is empty)
      testTopology = shrinkerMod.apply topologyTarget fuzzedTopology.result topologyChoices;

      # Step 3: Expand topology-map into per-node configs and role mapping
      expansion = expandTopologyMod.expandTopology { topology-map = testTopology; };
      nodeConfigs = expansion.nodeConfigs;
      nodeRoles = expansion.nodeRoles;

      # Step 4: Fuzz config target once per role (alphabetical order)
      # Role names sorted alphabetically for deterministic seed derivation
      roleNames = builtins.sort (a: b: a < b) (builtins.attrNames testTopology.roles);

      roleConfigs = builtins.listToAttrs (lib.imap0 (idx: roleName:
        let
          roleSeed = toString (seed + 1 + idx);
          fuzzedRole = fuzzerMod.fuzzer {
            seed = roleSeed;
            target = configTarget;
          };
          roleChoices = configChoices.${roleName} or {};
          testRoleConfig = shrinkerMod.apply configTarget fuzzedRole.result roleChoices;
        in
        {
          name = roleName;
          value = testRoleConfig;
        }
      ) roleNames);

      # Step 5: Three-layer merge per node
      # Each node's final config: base ⊕ roleConfig ⊕ topologyConfig
      # Merge happens inside the module function where pkgs is in scope
      finalNodeConfigs = lib.mapAttrs (nodeName: nodeTopoConfig:
        { pkgs, ... }:
        mergeMod.mergeConfigs {
          base = baseModule { inherit pkgs nodeName; };
          config = roleConfigs.${nodeRoles.${nodeName}};
          topology = nodeTopoConfig;
        }
      ) nodeConfigs;

    in
    runnerMod.run {
      nodeConfigs = finalNodeConfigs;
      inherit testScript properties name;
      inherit reportNode repetitionToken;
    };
}
