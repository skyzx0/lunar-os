#!/usr/bin/env bash
# Turn Arch's official releng profile into Lunar OS.
#
#   lunar/apply.sh <profile-dir>
#
# Everything here is a small, separate change on top of the unmodified
# upstream profile. Add new changes as new numbered steps, one at a time,
# so a broken build always points at the last step added.
set -euo pipefail

P="$1"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
ASSETS="$REPO/lunar-setup/lunar_setup/assets"
A="$P/airootfs"
say() { printf ':: %s\n' "$*"; }

# 1. ISO identity: filename, volume label, publisher.
say "1. ISO identity"
sed -i \
    -e 's|^iso_name=.*|iso_name="lunaros"|' \
    -e 's|^iso_label="ARCH_|iso_label="LUNAROS_|' \
    -e 's|^iso_publisher=.*|iso_publisher="Lunar OS <https://github.com/skyzx0/lunar-os>"|' \
    -e 's|^iso_application=.*|iso_application="Lunar OS Live/Rescue"|' \
    "$P/profiledef.sh"

# 2. Boot menu titles (UEFI systemd-boot, GRUB, BIOS syslinux).
say "2. Boot menu titles"
sed -i 's/Arch Linux/Lunar OS/g' \
    "$P"/efiboot/loader/entries/*.conf \
    "$P"/grub/*.cfg \
    "$P"/syslinux/*.cfg

# 3. Hostname and welcome message on the live system.
say "3. Hostname and welcome message"
echo "lunaros" > "$A/etc/hostname"
cp "$HERE/motd" "$A/etc/motd"

# 4. OS name in os-release and the login banner. The hook is numbered 10-
#    so it runs before the boot image is built from os-release.
say "4. OS name"
install -Dm644 "$ASSETS/os-release" "$A/usr/share/lunaros/os-release"
install -Dm644 "$ASSETS/issue" "$A/usr/share/lunaros/issue"
install -Dm644 "$HERE/10-lunar-branding.hook" "$A/etc/pacman.d/hooks/10-lunar-branding.hook"

# 5. The Lunar OS installer.
say "5. Installer"
mkdir -p "$A/usr/local/lib/lunaros-setup"
cp -r "$REPO/lunar-setup/lunar_setup" "$A/usr/local/lib/lunaros-setup/"
install -Dm755 "$HERE/lunaros-setup" "$A/usr/local/bin/lunaros-setup"
sed -i 's|^file_permissions=(|file_permissions=(\n  ["/usr/local/bin/lunaros-setup"]="0:0:755"|' "$P/profiledef.sh"

# 6. BIOS boot menu background (Arch's logo otherwise).
say "6. Boot menu background"
cp "$HERE/splash.png" "$P/syslinux/splash.png"

# 7. ltxs, the Lunar package command.
say "7. ltxs"
install -Dm755 "$ASSETS/ltxs" "$A/usr/local/bin/ltxs"
sed -i 's|^file_permissions=(|file_permissions=(\n  ["/usr/local/bin/ltxs"]="0:0:755"|' "$P/profiledef.sh"

# 8. A larger, sharper console font: the logo and the installer's progress
#    bar are drawn with box and block characters, which Terminus has, and
#    the default 8x16 font is tiny on a high-resolution laptop screen.
say "8. Console font"
grep -qx terminus-font "$P/packages.x86_64" || echo terminus-font >> "$P/packages.x86_64"
printf 'KEYMAP=us\nFONT=ter-v22b\n' > "$A/etc/vconsole.conf"

say "done"
