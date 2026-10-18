# What one Lunar OS install is made of. Set from /etc/lunar/system.conf.
{ lib, ... }:
let
  inherit (lib) mkOption types;
in
{
  options.lunar = {
    user = {
      name = mkOption { type = types.str; default = "lunar"; };
      description = mkOption { type = types.str; default = "Lunar"; };
    };
    keyboard = {
      layout = mkOption { type = types.str; default = "us"; };
      variant = mkOption { type = types.str; default = ""; };
    };
    boot = {
      mode = mkOption { type = types.enum [ "efi" "bios" ]; default = "efi"; };
      device = mkOption { type = types.str; default = "nodev"; };
    };
    desktop = mkOption { type = types.enum [ "lunar" "console" ]; default = "lunar"; };
    apps = mkOption { type = types.listOf types.str; default = [ ]; };
    live = mkOption { type = types.bool; default = false; };
    version = mkOption { type = types.str; default = "1.0"; };
  };
}
