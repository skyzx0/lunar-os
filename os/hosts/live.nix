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
  # Like any install medium: a root console, not a desktop.
  lunar.desktop = lib.mkForce "console";
  services.getty.autologinUser = lib.mkForce "root";
  users.users.root.shell = pkgs.zsh;
  users.users.root.initialHashedPassword = lib.mkForce "";

  programs.zsh = {
    enable = true;
    autosuggestions.enable = true;
    syntaxHighlighting.enable = true;
    promptInit = "";
    interactiveShellInit = ''
      PROMPT=$'%F{#969fff}%n%f@lunar %F{white}%~%f %F{#969fff}>%f '
      [[ $(tty) == /dev/tty1 && -z "''${LUNAR_MOTD_SHOWN:-}" ]] && { export LUNAR_MOTD_SHOWN=1; lunar-motd; }
    '';
  };

  # A readable console font on laptop screens.
  console = {
    earlySetup = true;
    packages = [ pkgs.terminus_font ];
    font = "ter-v24n";
  };

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

  environment.etc."lunaros/live".text = "";
  environment.etc."lunar/dialogrc".source = ../assets/dialogrc;
  environment.systemPackages = with pkgs; [ lunar.lunar-tools xfsprogs btrfs-progs gptfdisk parted networkmanager ];
  # The engine lunar-genconf copies onto the new system.
  systemd.tmpfiles.rules = [ "L+ /var/lib/lunar/engine - - - - ${flakeSource}" ];

  # What nixos-install needs to finish the system without the internet.
  system.extraDependencies = with pkgs; [ stdenvNoCC busybox makeInitrdNGTool ] ++ jq.all;

  system.stateVersion = "26.05";
}
