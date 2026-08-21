{ pkgs, nodeName, ... }:

{
  virtualisation.diskSize = 4096;
  virtualisation.memorySize = 1024;
  networking.firewall.enable = false;

  services.rabbitmq = {
    enable = true;
    managementPlugin.enable = true;
    unsafeCookie = "TOPOTESTIXRABBITMQCOOKIE";
    configItems = {
      "cluster_name" = "topotestix-rabbitmq-failure-domain";
      "log.console.level" = "info";
    };
  };

  systemd.services.rabbitmq.serviceConfig.Restart = pkgs.lib.mkForce "no";

  environment.systemPackages = with pkgs; [
    coreutils
    curl
    jq
    (python3.withPackages (ps: [ ps.pika ]))
    rabbitmq-server
  ];
}
