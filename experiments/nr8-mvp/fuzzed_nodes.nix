# fuzzed_nodes.nix - fuzzing specification for test node configurations
{
  virtualisation = {
    memorySize = [
      512
      1024
      2048
      4096
    ];

    diskSize = [
      1024
      2048
      5120
      10240
    ];
  };

  boot = {
    tmp.cleanOnBoot = [
      true
      false
    ];
  };

  services = {
    openssh.enable = [
      true
      false
    ];
  };
}
