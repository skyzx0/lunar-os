# The USB stick: Lunar OS running live, with lunar-install to put it on a disk.
{ config, lib, pkgs, modulesPath, self, nixpkgs, ... }:
let
  installed = self.nixosConfigurations.lunar.config.system.build.toplevel;
  flakeSource = builtins.path { path = ../.; name = "lunar-engine"; };
in
{
  imports = [
    "${modulesPath}/installer/cd-dvd/iso-image.nix"
    "${modulesPath}/profiles/base.nix"
    "${modulesPath}/profiles/all-hardware.nix"
  ];

  lunar.live = true;
  users.users.lunar.initialPassword = "lunar";

  image.baseName = lib.mkForce "lunar-os-${config.system.nixos.label}";
  isoImage = {
    squashfsCompression = "zstd -Xcompression-level 12";
    volumeID = "LUNAR_OS";
    appendToMenuLabel = " Live";
    makeEfiBootable = true;
    makeUsbBootable = true;
    splashImage = ../assets/boot-menu.png;
    efiSplashImage = ../assets/boot-menu.png;
    grubTheme = null;
    # The installed system and the package set it is built from come on the
    # stick, so installing copies them instead of downloading them.
    storeContents = [ installed nixpkgs.outPath flakeSource ];
  };
  boot.loader.timeout = lib.mkForce 2;
  # No ZFS on the stick: it's large and Lunar doesn't install onto it.
  boot.supportedFilesystems.zfs = lib.mkForce false;

  swapDevices = lib.mkImageMediaOverride [ ];
  fileSystems = lib.mkImageMediaOverride config.lib.isoFileSystems;
  boot.initrd.luks.devices = lib.mkImageMediaOverride { };

  # Straight into the desktop.
  services.greetd.settings.initial_session = {
    user = "lunar";
    command = "${pkgs.lunar.lunar-session}/bin/lunar-session";
  };

  environment.etc."lunaros/live".text = "";
  # The engine lunar-genconf copies onto the new system.
  systemd.tmpfiles.rules = [ "L+ /var/lib/lunar/engine - - - - ${flakeSource}" ];

  # What nixos-install needs to finish the system without the internet.
  system.extraDependencies = with pkgs; [ stdenvNoCC busybox makeInitrdNGTool ] ++ jq.all;

  system.stateVersion = "26.05";
}
