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

# 4. OS name in os-release and the login banner.
say "4. OS name"
install -Dm644 "$HERE/os-release" "$A/usr/share/lunaros/os-release"
install -Dm644 "$HERE/issue" "$A/usr/share/lunaros/issue"
install -Dm644 "$HERE/lunar-branding.hook" "$A/etc/pacman.d/hooks/lunar-branding.hook"

# 5. The Lunar OS installer.
say "5. Installer"
mkdir -p "$A/usr/local/lib/lunaros-setup"
cp -r "$REPO/lunar-setup/lunar_setup" "$A/usr/local/lib/lunaros-setup/"
install -Dm755 "$HERE/lunaros-setup" "$A/usr/local/bin/lunaros-setup"
sed -i 's|^file_permissions=(|file_permissions=(\n  ["/usr/local/bin/lunaros-setup"]="0:0:755"|' "$P/profiledef.sh"

say "done"
