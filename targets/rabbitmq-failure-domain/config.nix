{ lib, ... }:

# A complete placement map is one choice because role configuration is shared
# by all RabbitMQ nodes. The second choice models a realistic colocated pair.
{
  environment.etc."topotestix-failure-domain-placement.json".text = [
    ''{"rabbit1":"zone-a","rabbit2":"zone-b","rabbit3":"zone-c"}''
    ''{"rabbit1":"zone-a","rabbit2":"zone-a","rabbit3":"zone-b"}''
  ];

  environment.etc."topotestix-failed-domain".text = [ "zone-a" ];
  environment.etc."topotestix-domain-confirm-timeout-ms".text = [ "2000" "5000" ];
}
