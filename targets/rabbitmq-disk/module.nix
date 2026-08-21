{ pkgs, nodeName, ... }:

# Stable base configuration applied to every node in the disk pressure
# target. Disk size and broker disk_free_limit are set by config.nix
# (fuzzed); this module only sets the host-level knobs that should not
# vary across runs.
{
  # Keep memory fixed so that memory alarms do not interfere with disk
  # alarm testing.
  virtualisation.memorySize = 2048;
  virtualisation.diskSize = 2048;

  # Disable the NixOS firewall so the test driver can communicate with
  # the broker directly through the QEMU user network.
  networking.firewall.enable = false;

  services.rabbitmq = {
    enable = true;
    managementPlugin.enable = true;
    unsafeCookie = "TOPOTESTIXRABBITMQCOOKIE";

    configItems = {
      # Distinct cluster name so this target cannot accidentally merge
      # with a parallel rabbitmq-cluster or rabbitmq-partition run.
      "cluster_name" = "topotestix-rabbitmq-disk";
      "log.console.level" = "info";
      # disk_free_limit.absolute is set by config.nix (fuzzed).
    };
  };

  environment.systemPackages = with pkgs; [
    coreutils
    curl
    gawk
    gnugrep
    gnused
    iproute2
    jq
    (python3.withPackages (ps: [ ps.pika ]))
    rabbitmq-server
    util-linux
  ];
}
