{ pkgs, nodeName, ... }:

# Stable base configuration applied to every node in the memory
# pressure target. Memory size and broker watermark are set by
# config.nix (fuzzed); this module only sets the host-level knobs that
# should not vary across runs.
{
  # The broker data dir is sized for large message backlogs even when
  # the VM memory is tight. The fuzzer does not vary disk size because
  # memory pressure is the focus of this target.
  virtualisation.diskSize = 4096;

  # Disable the NixOS firewall so the test driver can communicate with
  # the broker directly through the QEMU user network without the
  # generated firewall chain interfering.
  networking.firewall.enable = false;

  services.rabbitmq = {
    enable = true;
    managementPlugin.enable = true;
    unsafeCookie = "TOPOTESTIXRABBITMQCOOKIE";

    configItems = {
      # Distinct cluster name so this target cannot accidentally merge
      # with a parallel rabbitmq-cluster or rabbitmq-partition run.
      "cluster_name" = "topotestix-rabbitmq-memory";
      "log.console.level" = "info";
      # vm_memory_high_watermark.relative is set by config.nix (fuzzed).
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
  ];
}
