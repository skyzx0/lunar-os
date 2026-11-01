{ config, lib, ... }:
let
  hardware = ../host/hardware.nix;
in
{
  imports = lib.optional (builtins.pathExists hardware) hardware;

  fileSystems."/" = lib.mkDefault {
    device = "/dev/disk/by-label/lunar-root";
    fsType = "ext4";
    options = [ "noatime" ];
  };
  fileSystems."/boot" = lib.mkDefault {
    device = "/dev/disk/by-label/LUNAR-EFI";
    fsType = "vfat";
    options = [ "umask=0077" ];
  };

  boot.loader = if config.lunar.boot.mode == "efi" then {
    systemd-boot.enable = true;
    systemd-boot.configurationLimit = 15;
    efi.canTouchEfiVariables = true;
    timeout = 0;
  } else {
    grub.enable = true;
    grub.device = config.lunar.boot.device;
    grub.configurationLimit = 15;
    timeout = 1;
  };

  system.stateVersion = "26.05";
}
