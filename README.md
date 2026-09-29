# Lunar OS

Arch Linux's official ISO profile (`releng`), with Lunar OS branding and the
`lunaros-setup` installer. Nothing else.

    lunar/apply.sh      every change made to the upstream profile, numbered
    lunar-setup/        the installer
    lunar-setup/lunar_setup/assets/
                        files shared by the live ISO and installed systems:
                        os-release, the login banner, ltxs

## ltxs

The Lunar package command. pacman does the work underneath.

    ltxs install <package>...   ltxs search <term>
    ltxs remove <package>...    ltxs info <package>
    ltxs update                 ltxs list
    ltxs clean                  ltxs files <package> / ltxs owns <file>
    .github/workflows/  builds the ISO and publishes it as a release

Changes are added to `lunar/apply.sh` one at a time. Each build is tested on
real hardware before the next change goes in, so a failure always points at
the most recent step.

## Desktops

Every desktop gets a browser, fonts, battery and power-saver support
(power-profiles-daemon), and Bluetooth. On top of that:

    plasma     full Plasma (plasma-meta): network, battery, volume, Bluetooth,
               display settings; Konsole, Dolphin, Kate, Ark, Spectacle,
               Gwenview, Okular, KCalc, Filelight
    gnome      the full GNOME group
    hyprland   Waybar, hyprlock, hypridle, network and Bluetooth applets
    sway       network and Bluetooth applets, Thunar
    i3         Alacritty, network and Bluetooth applets, Thunar, picom

Every desktop gets the Lunar look: black, see-through terminals, the half
moon as wallpaper. Hyprland, Sway and i3 get complete configs (bar, keys,
lock screen, idle) in ~/.config - yours to edit. GNOME gets dark defaults
and a dock; anything changed in Settings wins.

Plasma also gets the Lunar look at first login: black colours, a
see-through terminal, translucent panel, the half moon as wallpaper and
behind the login screen. It is applied once; change anything afterwards in
System Settings and it stays changed.

## pacman

There is no pacman command on Lunar OS: typing it points to `ltxs`. The
engine underneath stays installed, because ltxs and updates run on it, and
scripts that call it are unaffected.
