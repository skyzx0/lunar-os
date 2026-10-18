#!/bin/bash
# quick-rebuild.sh - a new Lunar OS Core image in minutes, without compiling.
#
# Takes the last full build's image and puts the current Lunar files into it:
# everything under core/board/lunar/overlay (the desktop rice, configs,
# lunar-install, ltxs, its app recipes, scripts) plus what post-build.sh does
# to them. Programs and the kernel stay as they were in that build.
#
# For changes to the package list, the kernel or anything in core/package,
# a full build is still needed (Build Lunar OS Core).
#
#   sudo core/quick-rebuild.sh OLD.img.gz VERSION OUT.img.gz

set -euo pipefail
OLD=$1 VERSION=$2 OUT=$3
HERE=$(cd "$(dirname "$0")" && pwd)
OVERLAY=$HERE/board/lunar/overlay
WORK=$(mktemp -d)
LOOP=""
cleanup() {
    umount "$WORK/root" 2>/dev/null || true
    [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT

echo ":: unpacking $(basename "$OLD")"
gunzip -c "$OLD" > "$WORK/img"
LOOP=$(losetup -fP --show "$WORK/img")
partx -u "$LOOP" 2>/dev/null || true
for _ in $(seq 20); do [[ -b "${LOOP}p2" ]] && break; sleep 0.5; done
mkdir -p "$WORK/root"
mount "${LOOP}p2" "$WORK/root"
R=$WORK/root

echo ":: putting in the current Lunar files"
rsync -rlt --chown=0:0 "$OVERLAY/" "$R/"

# What post-build.sh does to the same files.
chmod 0440 "$R/etc/sudoers.d/wheel"
sed -i '/^IMAGE_VERSION=/d' "$R/usr/lib/os-release"
echo "IMAGE_VERSION=$VERSION" >> "$R/usr/lib/os-release"
touch "$R/etc/lunar-live"
ids=$(awk -F: '$1 == "lunar" {print $3 ":" $4}' "$R/etc/passwd")
[[ -n "$ids" ]] && chown -R "$ids" "$R/home/lunar"
mkdir -p "$R/etc/skel"
cp -a "$R/home/lunar/." "$R/etc/skel/"
chown -R 0:0 "$R/etc/skel"

sync
umount "$R"
losetup -d "$LOOP"; LOOP=""

echo ":: compressing"
if command -v pigz >/dev/null; then pigz -9 -c "$WORK/img" > "$OUT"; else gzip -9 -c "$WORK/img" > "$OUT"; fi
echo ":: done: $OUT"
