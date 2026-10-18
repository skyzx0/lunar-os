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

Several desktops can be installed together; choose between them at the
login screen. The first one picked decides which login screen that is.

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

## Lunar Look

One app for the look of every desktop: accent colour, terminal and window
transparency, blur, corner rounding, animation speed and wallpaper. Open it
from Settings in the app menu, with Super+I on Hyprland, Sway and i3, or run
`lunar-look`. Changes apply at once to everything running.

    lunar-look apply           apply the current settings everywhere
    lunar-look set KEY VALUE   e.g. lunar-look set accent "#ff8fb1"
    lunar-look reset           back to the Lunar defaults

Settings are in ~/.config/lunaros/look.json. Each program's own config
includes a small generated file, so your own edits to those configs stay.
On Plasma, translucent windows come from the Lunar Kvantum theme, generated
from the accent, rather than by forcing window opacity.

## Hyprland: illogical-impulse

Hyprland comes as illogical-impulse (github.com/end-4/dots-hyprland,
GPL-3.0), installed during the Lunar installation and themed as Lunar: its
colour pipeline builds the palette from the moon wallpaper and the Lunar
accent on first launch, with transparency on, the moon as the bar icon and
the user's keyboard layout. It is pinned to a commit matching the Hyprland
version Lunar ships, and installed as the user (its installer refuses root),
with a sudo rule that exists only while it runs.

If that part fails - no internet, a build error - the Lunar installation
still completes with Lunar's own Hyprland setup, and the first login offers
it again. Details: /var/log/lunaros-ii-install.log. `lunar-ii` reinstalls it.

## Testing every desktop: `lunar-test`

After installing, log in to Plasma or Hyprland, open a terminal and run `lunar-test`
(or open "Lunar Test" from the app menu). It takes 1-3 minutes, never more than about 5:

- checks the system (name, ltxs, hidden pacman, boot splash) and each installed
  desktop's config with that desktop's own validator
- starts Hyprland and Sway in a window and i3 in Xephyr, opens a terminal with
  fastfetch in each, takes a screenshot and closes it again
- writes `~/lunar-test/<date>/index.html` (pass/fail list plus screenshots) and opens it

Plasma and GNOME can't run inside another desktop, so log in to each of them once and
run `lunar-test` there too. `lunar-test --checks` skips the screenshots (seconds).

## Lunar OS Core (independent)

`core/` is Lunar OS built entirely from source, based on no other distribution:
the compiler toolchain, glibc, the Linux kernel, systemd, Mesa, GTK, PipeWire and
Sway are all compiled by the "Build Lunar OS Core" workflow, with Buildroot as the
build tool. Lunar's own packages (swaylock, swayidle, mako, tofi, brightnessctl)
are in `core/package/`.

The workflow publishes `lunar-core-<version>.img.gz`: write it to a USB stick and
it boots into the Lunar desktop (user `lunar`, password `lunar`).

- `sudo lunar-install` installs it on the computer's disk (disk, account,
  computer name, time zone, keyboard).
- `ltxs` is the package manager: `ltxs list`, `sudo ltxs install firefox`,
  `sudo ltxs upgrade` for apps, `sudo ltxs update` for the system itself
  (from the newest release here; the repository must be public for that).
- Desktop: Sway with the Lunar rice; Super+D apps, Super+Return terminal,
  Super+E files, Super+B browser, Super+W Wi-Fi, Super+L lock.

### Quick builds

"Quick build Lunar OS Core" makes a new image in about 5-10 minutes without
compiling: it takes the last full build and puts the current files from
`core/board/lunar/overlay` into it (the rice, configs, installer, ltxs and its
recipes). Use the full build only when the package list, the kernel or
`core/package` changes.
