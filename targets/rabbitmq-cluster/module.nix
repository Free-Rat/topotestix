{ pkgs, nodeName, ... }:

{
  virtualisation.memorySize = 2048;
  virtualisation.diskSize = 2048;

  # Keep the baseline target focused on quorum-queue correctness, not Erlang
  # distribution port discovery. The dedicated network/firewall target can
  # reintroduce filtered ports deliberately.
  networking.firewall.enable = false;

  services.rabbitmq = {
    enable = true;
    managementPlugin.enable = true;
    unsafeCookie = "TOPOTESTIXRABBITMQCOOKIE";

    configItems = {
      # The NixOS module already sets listeners.tcp.1 from listenAddress/port.
      # Keep management on the default port because the properties use the HTTP
      # API locally on each node.
      "cluster_name" = "topotestix-rabbitmq";
      "log.console.level" = "info";
    };
  };

  environment.systemPackages = with pkgs; [
    coreutils
    curl
    gnugrep
    gnused
    jq
    (python3.withPackages (ps: [ ps.pika ]))
    rabbitmq-server
  ];
}
