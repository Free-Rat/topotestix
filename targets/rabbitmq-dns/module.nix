{ pkgs, nodeName, ... }:

# Stable base configuration applied to every node in the DNS / hostname
# target. The name-resolution knobs (hosts entries, search list, domain) are
# injected at runtime by test-script.py from the fuzzed /etc parameters, so
# this module only sets the host-level baseline that should not vary across
# runs.
{
  # RabbitMQ on a small, standard disk and memory budget. The DNS axis does
  # not apply filesystem or memory pressure (those are the rabbitmq-disk and
  # rabbitmq-memory targets); disk 2048 MB / memory 2048 MB is ample headroom
  # for a healthy 3-replica quorum queue to form and for 100 confirmed
  # publishes to persist.
  virtualisation.memorySize = 2048;
  virtualisation.diskSize = 2048;

  # Keep the NixOS firewall off so inter-VM Erlang distribution (node_name
  # discovery) and the management API work through the QEMU user network,
  # the same baseline the cluster target uses. The DNS target varies name
  # resolution, not the packet path.
  networking.firewall.enable = false;

  # Name resolution in the NixOS test harness runs through each VM's /etc/hosts
  # (NixOS testing writes every node's bare hostname to it), so the baseline
  # leaves search / domain unset and the driver rewrites /etc/hosts at runtime
  # — see the DNS rationale in config.nix and the apply logic in test-script.py.
  # The network is statically addressed by the harness (no DHCP); the
  # management API inter-VM connectivity the properties use is local, so there
  # is no firewall or interface config to vary for this target.
  services.rabbitmq = {
    enable = true;
    managementPlugin.enable = true;
    unsafeCookie = "TOPOTESTIXRABBITMQCOOKIE";

    configItems = {
      # Distinct cluster name so this target cannot accidentally merge with a
      # parallel rabbitmq-cluster / rabbitmq-partition / rabbitmq-memory /
      # rabbitmq-disk / rabbitmq-crash run.
      "cluster_name" = "topotestix-rabbitmq-dns";
      "log.console.level" = "info";
    };
  };

  environment.systemPackages = with pkgs; [
    coreutils
    curl
    gnugrep
    gnused
    iproute2
    jq
    (python3.withPackages (ps: [ ps.pika ]))
    rabbitmq-server
  ];
}
