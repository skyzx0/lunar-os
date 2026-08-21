#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="lunar"
iso_label="LUNAR_$(date +%Y%m)"
iso_publisher="Lunar OS"
iso_application="Lunar OS Live/Install Medium"
iso_version="$(date +%Y.%m.%d)"
install_dir="lunar"
buildmodes=('iso')
bootmodes=('bios.syslinux.mbr' 'bios.syslinux.eltorito'
           'uefi-x64.systemd-boot.esp' 'uefi-x64.systemd-boot.eltorito')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="erofs"
airootfs_image_tool_options=('-zlz4hc,12' '-E' 'ztailpacking')

file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/etc/gshadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/.zlogin"]="0:0:644"
)
