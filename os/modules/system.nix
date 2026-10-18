# The base system: users, networking, sound, Bluetooth, fonts, the engine.
{ config, lib, pkgs, nixpkgs, ... }:
let
  cfg = config.lunar;
  apps = map (n: lib.attrByPath (lib.splitString "." n)
    (throw "system.conf: [apps] has \"${n}\", which is not an app (try: ltxs search ${n})") pkgs) cfg.apps;

  # The engine's own commands stay usable for Lunar's tools, but typed at a
  # prompt they answer like any command that isn't there.
  hidden = [
    "nix" "nix-env" "nix-shell" "nix-build" "nix-store" "nix-instantiate" "nix-channel"
    "nix-collect-garbage" "nix-copy-closure" "nix-daemon" "nix-hash" "nix-prefetch-url"
    "nixos-rebuild" "nixos-install" "nixos-enter" "nixos-generate-config" "nixos-option"
    "nixos-version" "nixos-help" "nixos-firewall-tool" "nixos-build-vms"
  ];
in
{
  nixpkgs.config.allowUnfree = true;

  nix = {
    settings = {
      experimental-features = [ "nix-command" "flakes" ];
      auto-optimise-store = true;
      trusted-users = [ "root" "@wheel" ];
      warn-dirty = false;
    };
    channel.enable = false;
    registry.nixpkgs.flake = nixpkgs;
    nixPath = [ "nixpkgs=${nixpkgs}" ];
    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 30d";
    };
  };
  documentation.nixos.enable = false;
  system.tools.nixos-option.enable = false;
  system.tools.nixos-version.enable = false;

  environment.interactiveShellInit = ''
    _lunar_missing() { printf 'bash: %s: command not found\n' "$1" >&2; return 127; }
  '' + lib.concatMapStrings (c: ''
    ${c}() { _lunar_missing ${c}; }
  '') hidden;

  # Passwords are set with `passwd` (lunarstrap asks for the first one).
  users.mutableUsers = true;
  users.users.${cfg.user.name} = {
    isNormalUser = true;
    description = cfg.user.description;
    extraGroups = [ "wheel" "networkmanager" "video" "audio" "input" ];
  };
  security.sudo.wheelNeedsPassword = !cfg.live;

  networking.networkmanager.enable = true;
  hardware.enableRedistributableFirmware = true;
  hardware.bluetooth.enable = true;
  services.blueman.enable = cfg.desktop == "lunar";
  services.upower.enable = true;
  services.power-profiles-daemon.enable = true;
  services.fwupd.enable = true;
  zramSwap.enable = true;

  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
  };
  security.rtkit.enable = true;

  time.timeZone = lib.mkDefault "UTC";
  i18n.defaultLocale = lib.mkDefault "en_US.UTF-8";
  services.xserver.xkb = {
    layout = cfg.keyboard.layout;
    variant = cfg.keyboard.variant;
  };
  console.useXkbConfig = true;

  fonts.packages = with pkgs; [ noto-fonts noto-fonts-color-emoji dejavu_fonts jetbrains-mono ];
  fonts.fontconfig.defaultFonts = {
    sansSerif = [ "Noto Sans" ];
    monospace = [ "JetBrains Mono" ];
  };

  programs.firefox.enable = cfg.desktop == "lunar";
  programs.git.enable = true;

  environment.systemPackages = (with pkgs; [
    lunar.ltxs
    lunar.lunar-tools
    fastfetch
    btop htop
    curl wget
    nano vim
    unzip zip p7zip
    file tree jq
    pciutils usbutils
    gptfdisk parted dosfstools e2fsprogs btrfs-progs
  ]) ++ apps;

  environment.shellAliases.lunarfetch = "fastfetch";
}
