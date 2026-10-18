# Lunar OS installed on a disk. Its settings: /etc/lunar/system.conf.
{ config, lib, ... }:
let
  hardware = ../host/hardware.nix;
in
{
  imports = lib.optional (builtins.pathExists hardware) hardware;

  # Used when system.conf has no [mounts] (the guided installer's labels).
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

  # Straight to the splash; hold Space at power-on for the menu of versions.
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
