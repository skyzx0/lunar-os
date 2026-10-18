# Lunar OS's own packages, available as pkgs.lunar.* everywhere in the system.
final: prev:
let
  assets = ../assets;
  script = name: deps:
    final.runCommand name { nativeBuildInputs = [ final.makeWrapper ]; meta.mainProgram = name; } ''
      install -Dm755 ${../scripts + "/${name}"} $out/bin/${name}
      patchShebangs $out/bin/${name}
      ${final.lib.optionalString (deps != [ ]) ''
        wrapProgram $out/bin/${name} --prefix PATH : ${final.lib.makeBinPath deps}
      ''}
    '';
in
{
  lunar = {
    # Wallpaper, logos, the boot splash, the desktop's default settings.
    assets = final.runCommand "lunar-assets" { } ''
      mkdir -p $out
      cp -r ${assets}/. $out/
    '';

    plymouth-theme = final.runCommand "lunar-plymouth-theme" { } ''
      dir=$out/share/plymouth/themes/lunar
      mkdir -p $dir
      cp ${assets}/plymouth/*.png ${assets}/plymouth/lunar.script $dir/
      sed -e "s|/usr/share/plymouth/themes/lunar|$dir|g" \
        ${assets}/plymouth/lunar.plymouth > $dir/lunar.plymouth
    '';

    ltxs = script "ltxs" (with final; [ jq gnused gnugrep coreutils ]);

    # Installing: the guided installer and the manual tools it is built on.
    lunar-tools = final.symlinkJoin {
      name = "lunar-tools";
      paths = map (n: script n (with final; [
        dialog gptfdisk dosfstools e2fsprogs util-linux coreutils gnused gnugrep gawk less
      ])) [ "lunar-install" "lunar-genconf" "lunarstrap" "lunar-chroot" "lunar-guide" ];
    };

    lunar-session = script "lunar-session" [ ];
    lunar-welcome = script "lunar-welcome" [ ];

    polkit-agent = final.writeShellScriptBin "polkit-agent" ''
      exec ${final.polkit_gnome}/libexec/polkit-gnome-authentication-agent-1
    '';

    # Lunar Look: one settings app for colours, transparency and wallpaper.
    lunar-look =
      let
        py = final.python3.withPackages (p: [ p.pygobject3 ]);
      in
      final.stdenvNoCC.mkDerivation {
        pname = "lunar-look";
        version = "1";
        dontUnpack = true;
        nativeBuildInputs = [ final.wrapGAppsHook4 final.gobject-introspection final.makeWrapper ];
        buildInputs = [ final.gtk4 final.libadwaita ];
        installPhase = ''
          mkdir -p $out/bin $out/libexec/lunar-look $out/share/applications
          cp ${assets}/look/lunar-look ${assets}/look/lunar-look-app $out/libexec/lunar-look/
          substituteInPlace $out/libexec/lunar-look/lunar-look \
            --replace-fail "#!/usr/bin/env python3" "#!${py}/bin/python3"
          substituteInPlace $out/libexec/lunar-look/lunar-look-app \
            --replace-quiet "#!/usr/bin/env python3" "#!${py}/bin/python3"
          chmod +x $out/libexec/lunar-look/*
          sed 's|^Exec=.*|Exec=lunar-look|' ${assets}/look/lunar-look.desktop \
            > $out/share/applications/lunar-look.desktop
        '';
        dontWrapGApps = true;
        # The wrapper goes in bin/; the engine and the app stay side by side in
        # libexec, where each loads the other as a Python module.
        postFixup = ''
          makeWrapper $out/libexec/lunar-look/lunar-look $out/bin/lunar-look \
            "''${gappsWrapperArgs[@]}"
        '';
        meta.mainProgram = "lunar-look";
      };
  };
}
