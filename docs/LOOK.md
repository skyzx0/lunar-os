# The desktop look

Plasma underneath, configured to not look like stock Plasma.

## What is changed

**Colour scheme.** Near-black surfaces (`#0a0b0d` to `#161820`) with one cyan
accent (`#5ec8d8`) and no other hue anywhere in the chrome. Breeze tints every
surface blue; Lunar keeps chrome neutral and spends its only colour on focus
and selection, so the thing you are interacting with is the only coloured
thing on screen.

**Window decorations.** No borders, no title-bar gradient, buttons on the
right in `IAX` order. Maximised windows are borderless.

**Panel.** One floating slim panel, centre-aligned, fitted to its contents
rather than spanning the screen. Launcher, pager, icon-only tasks, tray,
clock. No widgets beyond that.

**Desktop.** Flat colour, no wallpaper, no folder view. A folder view keeps a
directory watcher and a thumbnailer alive for files nobody is looking at.

**Login.** A custom SDDM theme: half moon, one input, no avatars and no
wallpaper. The session and power controls sit in the corners in muted text.
The moon is drawn with Canvas rather than shipped as a bitmap, so it is sharp
on any panel.

**Konsole.** Matching palette, 8px margins, no blur, block cursor in the
accent colour.

**Animations at 0.4x.** Plasma's defaults are slow enough to feel like
latency once you use the machine daily.

## What is not changed

The widget style stays Breeze. A custom Plasma style means reimplementing
every widget and re-breaking it at every Plasma release, for a difference most
people would not notice past the colour scheme. The colours, decorations,
layout and login screen carry the identity; the widget internals are not worth
the maintenance.

## How it is applied

Defaults ship in `/etc/skel/.config`, copied into a new account once. They are
not enforced system configuration: anything changed in System Settings stays
changed, and nothing reverts on upgrade.

The panel layout is a Plasma layout script, read once when a session first
starts without existing configuration. That survives Plasma updates that
change the config file format, which a pre-generated `appletsrc` would not.

To re-apply the layout after changing things:

    plasma-apply-lookandfeel -a org.lunaros.desktop

Or reset the panel only:

    cp /usr/share/lunar/layout/org.lunaros.desktop.js \
       ~/.config/plasma-org.kde.plasma.desktop-layout.js
    systemctl --user restart plasma-plasmashell
