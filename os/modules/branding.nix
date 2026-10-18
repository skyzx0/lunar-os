# Lunar OS everywhere a name or version is shown: os-release, boot menu,
# login, the boot splash.
{ config, lib, pkgs, ... }:
let
  ver = config.lunar.version;
in
{
  system.nixos = {
    distroName = "Lunar OS";
    distroId = "lunar";
    vendorName = "Lunar OS";
    vendorId = "lunar";
    label = ver;
    extraOSReleaseArgs = {
      ID_LIKE = "";
      LOGO = "lunar";
      ANSI_COLOR = "38;2;150;160;255";
      HOME_URL = "https://github.com/skyzx0/lunar-os";
      VERSION = "${ver} (Eclipse)";
      VERSION_ID = ver;
      VERSION_CODENAME = "eclipse";
      PRETTY_NAME = "Lunar OS ${ver} (Eclipse)";
      BUILD_ID = ver;
      CPE_NAME = "cpe:/o:lunar:lunar:${ver}";
      SUPPORT_END = "";
    };
  };
  networking.hostName = lib.mkDefault "lunar";

  services.getty.greetingLine = "Lunar OS ${ver} \\l";
  services.getty.helpLine = lib.mkForce "";

  # The boot splash: the half moon on black.
  boot.plymouth = {
    enable = true;
    theme = "lunar";
    themePackages = [ pkgs.lunar.plymouth-theme ];
  };
  boot.initrd.systemd.enable = true;
  boot.consoleLogLevel = 3;
  boot.initrd.verbose = false;
  boot.kernelParams = [ "quiet" "splash" "loglevel=3" "rd.udev.log_level=3" "udev.log_priority=3" "vt.global_cursor_default=0" ];

  environment.etc = {
    "lunaros/wallpaper.png".source = "${pkgs.lunar.assets}/wallpaper.png";
    "lunaros/fetch-logo.txt".source = "${pkgs.lunar.assets}/fetch-logo.txt";
    "lunaros/look.json".source = "${pkgs.lunar.assets}/look/look.json";
    "xdg/fastfetch/config.jsonc".source = "${pkgs.lunar.assets}/fastfetch.jsonc";
    "lunar/INSTALL.txt".source = "${pkgs.lunar.assets}/INSTALL.txt";
  };
}
