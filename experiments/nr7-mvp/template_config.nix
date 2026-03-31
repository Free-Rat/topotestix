# template_config.nix
{ pkgs, lib, ... }:

{
  system.stateVersion = "24.05";

  services.openssh.enable = true;

  environment.systemPackages = with pkgs; [
    vim
    git
  ];

  boot.loader.grub.enable = true;
  boot.loader.grub.devices = [ "nodev" ];

  fileSystems."/" = {
    device = "tmpfs";
    fsType = "tmpfs";
  };

  users.users.testuser = lib.mkForce {
    ignoreShellProgramCheck = true;
    shell = pkgs.bash;
  };
}
