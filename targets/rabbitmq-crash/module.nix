{ pkgs, nodeName, ... }:

# Stable base configuration applied to every node in the crash
# recovery target. Crash timing, crashed node, kill method, and
# restart delay are all set by config.nix (fuzzed); this module only
# sets the host-level knobs that should not vary across runs.
{
  # The broker data dir is sized for crash recovery. The Erlang
  # distribution and quorum queues can replay from on-disk Raft logs,
  # so the disk must hold the worst-case backlog of confirmed durable
  # messages plus the headroom the Erlang VM needs.
  virtualisation.diskSize = 8192;

  # Default 1024 MB is enough for the Erlang VM to run cleanly while
  # a 3-replica quorum queue replays after restart. The memory pressure
  # axis is exercised by the rabbitmq-memory target, not here.
  virtualisation.memorySize = 1024;

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
      # with a parallel rabbitmq-cluster, rabbitmq-partition, or
      # rabbitmq-memory run.
      "cluster_name" = "topotestix-rabbitmq-crash";
      "log.console.level" = "info";
    };
  };

  # The test controls the outage duration. Automatic restart would turn a
  # SIGKILL into an uncontrolled short interruption.
  systemd.services.rabbitmq.serviceConfig.Restart = pkgs.lib.mkForce "no";

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
