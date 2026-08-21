{ lib, ... }:

# Production contract: the configured free-space reserve must cover RabbitMQ's
# disk alarm threshold plus the backlog accumulated during a consumer outage.
# Index 0 is the least aggressive value so failures shrink toward a small case.
{
  virtualisation.diskSize = [ 2048 4096 ];

  services.rabbitmq.configItems."disk_free_limit.absolute" = [
    "50MB"
    "100MB"
    "200MB"
  ];

  environment.etc."topotestix-disk-initial-free-mb".text = [
    "500"
    "250"
    "100"
  ];

  environment.etc."topotestix-disk-backlog-rate".text = [
    "10"
    "25"
  ];

  environment.etc."topotestix-disk-consumer-outage-seconds".text = [
    "2"
    "8"
  ];

  environment.etc."topotestix-disk-message-size".text = [
    "1024"
    "4096"
    "16384"
  ];

  environment.etc."topotestix-disk-confirm-timeout-ms".text = [
    "1000"
    "3000"
  ];

  environment.etc."topotestix-disk-capacity-safety-factor-milli".text = [
    "1000"
    "1500"
  ];
}
