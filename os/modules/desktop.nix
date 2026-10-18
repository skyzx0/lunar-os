# The Lunar desktop: Hyprland with Lunar's own bar, launcher, notifications,
# lock screen and terminal, signed in through a Lunar login screen.
{ config, lib, pkgs, ... }:
let
  cfg = config.lunar;
  # The desktop's default settings, with this computer's keyboard filled in.
  # lunar-session copies them into ~/.config on first sign-in.
  skel = pkgs.runCommand "lunar-skel" { } ''
    cp -r ${pkgs.lunar.assets}/skel $out
    chmod -R u+w $out
    sed -i -e 's/@XKB_LAYOUT@/${cfg.keyboard.layout}/' \
           -e 's/@XKB_VARIANT@/${cfg.keyboard.variant}/' $out/hypr/hyprland.conf
  '';
  greeting = "Lunar OS - see what's on the other side of the moon";
in
lib.mkIf (cfg.desktop == "lunar") {
  programs.hyprland = {
    enable = true;
    xwayland.enable = true;
  };
  programs.hyprlock.enable = true;
  programs.dconf.enable = true;
  services.gvfs.enable = true;
  services.udisks2.enable = true;
  services.gnome.gnome-keyring.enable = true;

  environment.sessionVariables.NIXOS_OZONE_WL = "1";

  environment.etc = {
    "lunaros/skel".source = skel;
    "xdg/gtk-3.0/settings.ini".source = "${pkgs.lunar.assets}/gtk-settings.ini";
    "xdg/gtk-4.0/settings.ini".source = "${pkgs.lunar.assets}/gtk-settings.ini";
  };

  # Login: the Lunar greeting, then the desktop.
  services.greetd = {
    enable = true;
    useTextGreeter = true;
    settings.default_session = {
      user = "greeter";
      command = lib.concatStringsSep " " [
        "${pkgs.tuigreet}/bin/tuigreet"
        "--time --remember --asterisks"
        "--greeting '${greeting}'"
        "--theme 'border=lightblue;text=white;prompt=lightblue;time=gray;action=gray;button=lightblue;container=black;input=white'"
        "--cmd ${pkgs.lunar.lunar-session}/bin/lunar-session"
      ];
    };
  };

  environment.systemPackages = with pkgs; [
    lunar.lunar-session
    lunar.lunar-welcome
    lunar.polkit-agent
    kitty
    waybar
    wofi
    dunst
    hypridle
    swaybg
    networkmanagerapplet
    pavucontrol
    brightnessctl
    grim slurp
    cava
    nautilus
    loupe
    gnome-text-editor
    adwaita-icon-theme
    libnotify
  ];

  xdg.portal = {
    enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
  };
}
