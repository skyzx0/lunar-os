#!/bin/sh
# Builds the USB image: GPT, an EFI partition with GRUB and the kernel, and
# the ext4 root. Then compresses it for download.
set -e
BOARD_DIR=$(dirname "$0")

UUID=$(dumpe2fs "$BINARIES_DIR/rootfs.ext2" 2>/dev/null | sed -n 's/^Filesystem UUID: *\(.*\)/\1/p')
sed -i "s/UUID_TMP/$UUID/g" "$BINARIES_DIR/efi-part/EFI/BOOT/grub.cfg"
sed "s/UUID_TMP/$UUID/g" "$BOARD_DIR/genimage.cfg" > "$BINARIES_DIR/genimage.cfg"
support/scripts/genimage.sh -c "$BINARIES_DIR/genimage.cfg"

gzip -9 -c "$BINARIES_DIR/lunar-core.img" > "$BINARIES_DIR/lunar-core.img.gz"
