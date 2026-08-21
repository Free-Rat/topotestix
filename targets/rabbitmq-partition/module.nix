{ pkgs, nodeName, ... }:

# Stable base configuration applied to every node in the partition target.
# Partition parameters live in config.nix and are read by the test script
# from files under /etc at runtime.
{
  virtualisation.memorySize = 2048;
  virtualisation.diskSize = 2048;

  # Disable the NixOS firewall so the test script can manage iptables
  # rules directly without interference from the generated firewall chain.
  networking.firewall.enable = false;

  services.rabbitmq = {
    enable = true;
    managementPlugin.enable = true;
    unsafeCookie = "TOPOTESTIXRABBITMQCOOKIE";

    configItems = {
      # Distinct cluster name so this target cannot accidentally merge
      # with a parallel rabbitmq-cluster run.
      "cluster_name" = "topotestix-rabbitmq-partition";
      "log.console.level" = "info";
      # Short heartbeat so the Erlang distribution notices a TCP-level
      # partition within a few seconds rather than waiting for the 60s
      # default. The test script relies on this to detect a partition
      # before attempting writes.
      "heartbeat" = "10";
    };
  };

  environment.systemPackages = with pkgs; [
    coreutils
    curl
    gawk
    gnugrep
    gnused
    iptables
    iproute2
    jq
    (python3.withPackages (ps: [ ps.pika ]))
    rabbitmq-server
  ];
}
