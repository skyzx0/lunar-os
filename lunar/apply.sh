#!/usr/bin/env bash
set -euo pipefail

P="$1"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
ASSETS="$REPO/lunar-setup/lunar_setup/assets"
A="$P/airootfs"
say() { printf ':: %s\n' "$*"; }

say "1. ISO identity"
sed -i \
    -e 's|^iso_name=.*|iso_name="lunaros"|' \
    -e 's|^iso_label="ARCH_|iso_label="LUNAROS_|' \
    -e 's|^iso_publisher=.*|iso_publisher="Lunar OS <https://github.com/skyzx0/lunar-os>"|' \
    -e 's|^iso_application=.*|iso_application="Lunar OS Live/Rescue"|' \
    "$P/profiledef.sh"

say "2. Boot menu titles"
sed -i 's/Arch Linux/Lunar OS/g' \
    "$P"/efiboot/loader/entries/*.conf \
    "$P"/grub/*.cfg \
    "$P"/syslinux/*.cfg

say "3. Hostname and welcome message"
echo "lunaros" > "$A/etc/hostname"
cp "$HERE/motd" "$A/etc/motd"

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

say "6. Boot menu background"
cp "$HERE/splash.png" "$P/syslinux/splash.png"

# 7. ltxs, the Lunar package command.
say "7. ltxs"
install -Dm755 "$ASSETS/ltxs" "$A/usr/local/bin/ltxs"
sed -i 's|^file_permissions=(|file_permissions=(\n  ["/usr/local/bin/ltxs"]="0:0:755"|' "$P/profiledef.sh"

say "8. Console font"
grep -qx terminus-font "$P/packages.x86_64" || echo terminus-font >> "$P/packages.x86_64"
printf 'KEYMAP=us\nFONT=ter-v22b\n' > "$A/etc/vconsole.conf"

if [[ "${LUNAR_LIVE:-0}" == 1 ]]; then
    say "9. Live edition"
    sed -i -e 's|^iso_name=.*|iso_name="lunaros-live"|' \
           -e 's|^iso_application=.*|iso_application="Lunar OS Live"|' "$P/profiledef.sh"
    sed -i '/^virtualbox-guest-utils-nox$/d' "$P/packages.x86_64"
    pacman -Sy >/dev/null 2>&1 || true
    while read -r pkg; do
        [[ -z "$pkg" ]] && continue
        if pacman -Si "$pkg" >/dev/null 2>&1 || pacman -Sg "$pkg" >/dev/null 2>&1; then
            grep -qx "$pkg" "$P/packages.x86_64" || echo "$pkg" >> "$P/packages.x86_64"
        else
            echo "   skipping $pkg (not in the repositories)"
        fi
    done < "$HERE/live/packages.live"
    install -Dm755 "$HERE/live/live-setup" "$A/usr/local/lib/lunaros-setup/live-setup"
    install -Dm644 "$HERE/live/zz-lunar-live.hook" "$A/etc/pacman.d/hooks/zz-lunar-live.hook"
    sed -i 's|archisobasedir=%INSTALL_DIR%|& copytoram=n cow_spacesize=3G|' \
        "$P"/efiboot/loader/entries/*.conf "$P"/grub/*.cfg "$P"/syslinux/*.cfg
    sed -i 's/Lunar OS install medium/Lunar OS Live/; s/Lunar OS (x86_64/Lunar OS Live (x86_64/' \
        "$P"/efiboot/loader/entries/*.conf "$P"/grub/*.cfg "$P"/syslinux/*.cfg 2>/dev/null || true
    sed -i "s|^airootfs_image_tool_options=.*|airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '15' '-b' '1M')|" "$P/profiledef.sh"
fi

say "done"
