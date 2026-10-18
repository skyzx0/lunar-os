# Turns /etc/lunar/system.conf into the system. ltxs copies it here
# (host/system.conf) before applying.
{ config, lib, ... }:
let
  conf = import ../lib/conf.nix { inherit lib; file = ../host/system.conf; };
  v = conf.values;
  has = k: v ? ${k};
  known = [
    "system.hostname" "system.timezone" "system.keyboard" "system.keyboard_variant"
    "system.locale" "system.boot" "system.boot_disk"
    "user.name" "user.fullname"
    "desktop.session"
  ];
  unknown = builtins.filter (k: !(builtins.elem k known)) (builtins.attrNames v);

  device = d:
    if lib.hasPrefix "UUID=" d then "/dev/disk/by-uuid/${lib.removePrefix "UUID=" d}"
    else if lib.hasPrefix "LABEL=" d then "/dev/disk/by-label/${lib.removePrefix "LABEL=" d}"
    else d;
  mount = m:
    let f = builtins.filter (s: s != "") (lib.splitString " " m.value); in
    if builtins.length f < 2 then throw "system.conf: [mounts] ${m.point} needs at least a device and a type"
    else {
      name = m.point;
      value = {
        device = device (builtins.elemAt f 0);
        fsType = builtins.elemAt f 1;
        options = if builtins.length f > 2 then lib.splitString "," (builtins.elemAt f 2) else [ "defaults" ];
      };
    };
  fsMounts = builtins.filter (m: m.point != "swap") conf.mounts;
  swaps = builtins.filter (m: m.point == "swap") conf.mounts;
in
{
  assertions = map (k: {
    assertion = false;
    message = "system.conf: unknown setting \"${lib.last (lib.splitString "." k)}\" in [${builtins.head (lib.splitString "." k)}]";
  }) unknown;

  networking.hostName = lib.mkIf (has "system.hostname") v."system.hostname";
  time.timeZone = lib.mkIf (has "system.timezone") v."system.timezone";
  i18n.defaultLocale = lib.mkIf (has "system.locale") v."system.locale";
  lunar.keyboard.layout = lib.mkIf (has "system.keyboard") v."system.keyboard";
  lunar.keyboard.variant = lib.mkIf (has "system.keyboard_variant") v."system.keyboard_variant";
  lunar.boot.mode = lib.mkIf (has "system.boot") v."system.boot";
  lunar.boot.device = lib.mkIf (has "system.boot_disk") v."system.boot_disk";
  lunar.user.name = lib.mkIf (has "user.name") v."user.name";
  lunar.user.description = lib.mkIf (has "user.fullname") v."user.fullname";
  lunar.desktop = lib.mkIf (has "desktop.session") v."desktop.session";
  lunar.apps = conf.apps;

  fileSystems = lib.mkIf (!config.lunar.live && fsMounts != [ ]) (builtins.listToAttrs (map mount fsMounts));
  swapDevices = lib.mkIf (!config.lunar.live) (map (m: { device = device (builtins.head (lib.splitString " " m.value)); }) swaps);
}
