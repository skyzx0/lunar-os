# Reads Lunar's system.conf (sections, "key = value" lines, and a plain list
# under [apps]) into { values; apps; mounts; }.
{ lib, file }:
let
  raw = if builtins.pathExists file then builtins.readFile file else "";
  strip = l: lib.trim (builtins.head (lib.splitString "#" l));
  step = acc: line:
    let l = strip line; in
    if l == "" then acc
    else if lib.hasPrefix "[" l && lib.hasSuffix "]" l then
      acc // { section = lib.toLower (lib.removeSuffix "]" (lib.removePrefix "[" l)); }
    else if acc.section == "apps" then
      acc // { apps = acc.apps ++ [ l ]; }
    else
      let m = builtins.match "([^=]+)=(.*)" l; in
      if m == null then throw "system.conf: can't read \"${l}\" in [${acc.section}] (expected: name = value)"
      else
        let k = lib.trim (builtins.elemAt m 0); v = lib.trim (builtins.elemAt m 1); in
        if acc.section == "mounts" then acc // { mounts = acc.mounts ++ [ { point = k; value = v; } ]; }
        else acc // { values = acc.values // { "${acc.section}.${lib.toLower k}" = v; }; };
in
builtins.foldl' step { section = ""; values = { }; apps = [ ]; mounts = [ ]; } (lib.splitString "\n" raw)
