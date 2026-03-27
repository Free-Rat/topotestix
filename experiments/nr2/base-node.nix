# base-node.nix
{ nodeConfig, ... }:

{
  networking.hostName = nodeConfig.role;

  networking.interfaces.eth0.ipv4.addresses = [
    { address = nodeConfig.ip; prefixLength = 24; }
  ];

  services.openssh.enable = true;
}
