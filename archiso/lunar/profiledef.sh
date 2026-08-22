#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="lunar"
iso_label="LUNAR_$(date +%Y%m)"
iso_publisher="Lunar OS"
iso_application="Lunar OS Live/Install Medium"
iso_version="$(date +%Y.%m.%d)"
install_dir="lunar"
buildmodes=('iso')

# UEFI only, deliberately. The installed system boots a signed unified kernel
# image, enrols Secure Boot keys and can seal the LUKS key to a TPM - none of
# which exists on a BIOS machine. Offering a BIOS boot path would advertise
# support for hardware that cannot run the result.
bootmodes=('uefi-x64.systemd-boot.esp' 'uefi-x64.systemd-boot.eltorito')

arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="erofs"
airootfs_image_tool_options=('-zlz4hc,12' '-E' 'ztailpacking')

file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/etc/gshadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/.zlogin"]="0:0:644"
  ["/root/.bash_profile"]="0:0:644"
  ["/usr/local/bin/lunar-live-user"]="0:0:755"
)
