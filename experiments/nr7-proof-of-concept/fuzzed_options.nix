# fuzzed_options.nix
{ pkgs, ... }:
{
  services.openssh.enable = [
    true
    false
  ];

  networking.firewall.enable = [
    true
    false
  ];

  services.nginx.enable = [
    true
    false
  ];

  services.nginx.virtualHosts."test.local".root = [
    "/var/www"
    "/srv/http"
  ];

  boot = {
    loader.systemd-boot.enable = [
      true
      false
    ];
  };

  users.users.testuser.isNormalUser = true;

  users.users.testuser.shell = [
    pkgs.bash
    pkgs.zsh
  ];

  programs.zsh.enable = [
    true
    false
  ];
}
