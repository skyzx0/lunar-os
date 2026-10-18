#!/bin/sh
# Runs after the overlay is copied into the target, before the image.
set -e
BOARD_DIR=$(dirname "$0")

# Boot menu on the EFI partition.
mkdir -p "$BINARIES_DIR/efi-part/EFI/BOOT"
cp -f "$BOARD_DIR/grub.cfg" "$BINARIES_DIR/efi-part/EFI/BOOT/grub.cfg"

# git keeps only the executable bit; sudo refuses files others can write.
chmod 0440 "$TARGET_DIR/etc/sudoers.d/wheel"
grep -q '^@includedir /etc/sudoers.d' "$TARGET_DIR/etc/sudoers" ||
    echo '@includedir /etc/sudoers.d' >> "$TARGET_DIR/etc/sudoers"

# Which build this is (ltxs update compares it with the newest release).
sed -i '/^IMAGE_VERSION=/d' "$TARGET_DIR/usr/lib/os-release"
echo "IMAGE_VERSION=${LUNAR_VERSION:-dev}" >> "$TARGET_DIR/usr/lib/os-release"

# The USB stick is the live system until lunar-install copies it to a disk.
touch "$TARGET_DIR/etc/lunar-live"
mkdir -p "$TARGET_DIR/boot/efi"

# Services: Wi-Fi, wired DHCP, DNS, clock, seat fallback.
wants="$TARGET_DIR/etc/systemd/system/multi-user.target.wants"
mkdir -p "$wants"
for unit in iwd systemd-networkd systemd-resolved systemd-timesyncd seatd bluetooth; do
    if [ -f "$TARGET_DIR/usr/lib/systemd/system/$unit.service" ]; then
        ln -sf "/usr/lib/systemd/system/$unit.service" "$wants/$unit.service"
    fi
done
ln -sf ../run/systemd/resolve/stub-resolv.conf "$TARGET_DIR/etc/resolv.conf"

# Sound for every user session: PipeWire, its PulseAudio side, WirePlumber.
uw="$TARGET_DIR/etc/systemd/user"
for s in pipewire.socket pipewire-pulse.socket; do
    [ -f "$TARGET_DIR/usr/lib/systemd/user/$s" ] || continue
    mkdir -p "$uw/sockets.target.wants"
    ln -sf "/usr/lib/systemd/user/$s" "$uw/sockets.target.wants/$s"
done
if [ -f "$TARGET_DIR/usr/lib/systemd/user/wireplumber.service" ]; then
    mkdir -p "$uw/pipewire.service.wants"
    ln -sf /usr/lib/systemd/user/wireplumber.service "$uw/pipewire.service.wants/wireplumber.service"
fi

# The same desktop for every new user.
mkdir -p "$TARGET_DIR/etc/skel"
cp -a "$TARGET_DIR/home/lunar/." "$TARGET_DIR/etc/skel/"

# No trace of the build system's own name.
for f in "$TARGET_DIR/etc/os-release" "$TARGET_DIR/usr/lib/os-release"; do
    [ -L "$f" ] || [ ! -e "$f" ] || grep -q 'Lunar' "$f" ||
        cp -f "$BOARD_DIR/overlay/usr/lib/os-release" "$f"
done
