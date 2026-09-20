#!/usr/bin/env bash
# Install Lunar OS in a virtual machine, from the ISO, and check the result
# boots. This exercises the live medium end to end - the boot entries, the
# autoinstall unit, the whole path a real user takes.
#
# It is NOT what runs in the build: installing under emulation takes about an
# hour. The build installs to a loopback disk (tools/install-test.sh) and then
# boots the result (tools/boot-test.sh), which covers the same ground in a few
# minutes. Use this one when you want to test the medium itself.
#
# This is the test that has been missing. Every failure so far - a package
# that was never built, a disk held by a previous run, a prompt nobody could
# see, an error drawn where it could not be read - would have been caught
# here in ten minutes instead of on real hardware over days.
#
#   tools/vm-test.sh out/lunar-2026.09.05-x86_64.iso
#
# Exit status is 0 only if the installer finished AND the installed system
# booted to a login prompt on its own.

set -uo pipefail

ISO="${1:-}"
# Created explicitly: when WORK is inherited from the environment nothing
# else makes the directory, and the first thing to write into it fails in a
# way that only shows up later as a missing file.
WORK="${WORK:-$(mktemp -d)}"
mkdir -p "$WORK" || { echo "cannot create $WORK" >&2; exit 1; }
DISK="$WORK/target.qcow2"
INSTALL_LOG="$WORK/install.log"
BOOT_LOG="$WORK/boot.log"
MEM="${MEM:-3072}"
INSTALL_TIMEOUT="${INSTALL_TIMEOUT:-3600}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-900}"

red=$'\033[31m'; green=$'\033[32m'; dim=$'\033[2m'; cyan=$'\033[36m'; off=$'\033[0m'
say()  { printf '\n%s::%s %s\n' "$cyan" "$off" "$*"; }
fail() { printf '\n%s!!%s %s\n' "$red" "$off" "$*" >&2; }
ok()   { printf '\n%s ok%s %s\n' "$green" "$off" "$*"; }

[[ -f "$ISO" ]] || { fail "usage: $0 <iso>"; exit 1; }

command -v qemu-system-x86_64 >/dev/null || { fail "qemu-system-x86_64 missing"; exit 1; }
command -v qemu-img >/dev/null || { fail "qemu-img missing"; exit 1; }

# --- firmware -------------------------------------------------------------

find_fw() {
    for f in "$@"; do [[ -f "$f" ]] && { echo "$f"; return; }; done
}
# Arch, Ubuntu and Homebrew all put the firmware somewhere different.
FW_CODE="$(find_fw \
    /usr/share/edk2/x64/OVMF_CODE.4m.fd \
    /usr/share/edk2-ovmf/x64/OVMF_CODE.fd \
    /usr/share/OVMF/OVMF_CODE_4M.fd \
    /usr/share/OVMF/OVMF_CODE.fd \
    /usr/share/qemu/edk2-x86_64-code.fd \
    /opt/homebrew/share/qemu/edk2-x86_64-code.fd \
    /usr/local/share/qemu/edk2-x86_64-code.fd)"
FW_VARS_SRC="$(find_fw \
    /usr/share/edk2/x64/OVMF_VARS.4m.fd \
    /usr/share/edk2-ovmf/x64/OVMF_VARS.fd \
    /usr/share/OVMF/OVMF_VARS_4M.fd \
    /usr/share/OVMF/OVMF_VARS.fd \
    /opt/homebrew/share/qemu/edk2-x86_64-vars.fd \
    /usr/local/share/qemu/edk2-x86_64-vars.fd)"

[[ -n "$FW_CODE" ]] || { fail "no UEFI firmware found (install edk2-ovmf or ovmf)"; exit 1; }
FW_VARS="$WORK/OVMF_VARS.fd"
if [[ -n "$FW_VARS_SRC" ]]; then
    cp "$FW_VARS_SRC" "$FW_VARS" || { fail "could not copy $FW_VARS_SRC"; exit 1; }
else
    qemu-img create -f raw "$FW_VARS" 4M >/dev/null
fi
[[ -f "$FW_VARS" ]] || { fail "firmware variables file was not created at $FW_VARS"; exit 1; }
chmod u+w "$FW_VARS"

ACCEL="tcg"
[[ -w /dev/kvm ]] && ACCEL="kvm"
say "firmware $FW_CODE, acceleration $ACCEL"
if [[ "$ACCEL" == "tcg" ]]; then
    say "no KVM: every instruction is emulated, so this takes tens of minutes"
fi

# --- extract the kernel so the command line can be controlled -------------
# systemd-boot cannot be driven headlessly, and the autoinstall flag has to
# reach the kernel. Booting the ISO's kernel directly is the reliable way.

say "extracting the kernel from the image"
EXTRACT="$WORK/iso"
mkdir -p "$EXTRACT"
if command -v bsdtar >/dev/null; then
    bsdtar -xf "$ISO" -C "$EXTRACT" 2>/dev/null || true
elif command -v 7z >/dev/null; then
    7z x -o"$EXTRACT" "$ISO" >/dev/null || true
else
    fail "need bsdtar or 7z to read the image"; exit 1
fi

KERNEL="$(find "$EXTRACT" -name 'vmlinuz-linux-hardened' | head -1)"
INITRD="$(find "$EXTRACT" -name 'initramfs-linux-hardened.img' | head -1)"
[[ -f "$KERNEL" && -f "$INITRD" ]] || { fail "kernel or initramfs not found in the image"; exit 1; }

# --- install --------------------------------------------------------------

qemu-img create -f qcow2 "$DISK" 24G >/dev/null
say "installing (timeout ${INSTALL_TIMEOUT}s, log $INSTALL_LOG)"

timeout "$INSTALL_TIMEOUT" qemu-system-x86_64 \
    -machine q35 -accel "$ACCEL" -m "$MEM" -smp 2 \
    -drive if=pflash,format=raw,readonly=on,file="$FW_CODE" \
    -drive if=pflash,format=raw,file="$FW_VARS" \
    -drive file="$DISK",if=virtio,format=qcow2 \
    -cdrom "$ISO" \
    -kernel "$KERNEL" -initrd "$INITRD" \
    -append "archisobasedir=lunar archisodevice=/dev/sr0 console=ttyS0,115200 systemd.firstboot=off lunar.autoinstall lunar.disk=/dev/vda" \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -nographic -serial mon:stdio \
    > "$INSTALL_LOG" 2>&1

if grep -q "LUNAR AUTOINSTALL OK" "$INSTALL_LOG"; then
    ok "installer finished"
else
    fail "installation did not complete"

    # Say which kind of failure this was. A timeout with no installer output
    # means something blocked before it ever started, and that is a different
    # problem from an installer that ran and failed.
    if grep -q "LUNAR AUTOINSTALL" "$INSTALL_LOG"; then
        echo "  the installer started and did not finish"
    else
        echo "  the installer never started: something blocked earlier in boot"
    fi
    if grep -q "terminating on signal 15" "$INSTALL_LOG"; then
        echo "  the virtual machine was stopped by the ${INSTALL_TIMEOUT}s timeout"
    fi

    echo "$dim--- last 80 lines ---$off"
    tail -80 "$INSTALL_LOG"
    echo "$dim--- full log at $INSTALL_LOG ---$off"
    exit 1
fi

# --- boot what was installed ---------------------------------------------
# An installer that reports success and produces a system that does not boot
# has not succeeded. This is the half that matters.

say "booting the installed system (timeout ${BOOT_TIMEOUT}s)"

timeout "$BOOT_TIMEOUT" qemu-system-x86_64 \
    -machine q35 -accel "$ACCEL" -m "$MEM" -smp 2 \
    -drive if=pflash,format=raw,readonly=on,file="$FW_CODE" \
    -drive if=pflash,format=raw,file="$FW_VARS" \
    -drive file="$DISK",if=virtio,format=qcow2 \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -nographic -serial mon:stdio \
    > "$BOOT_LOG" 2>&1

if grep -qiE "lunaros login:|Lunar OS|Welcome to" "$BOOT_LOG"; then
    ok "the installed system boots"
else
    fail "the installed system did not reach a login prompt"
    echo "$dim--- last 60 lines ---$off"
    tail -60 "$BOOT_LOG"
    echo "$dim--- full log at $BOOT_LOG ---$off"
    exit 1
fi

say "logs: $INSTALL_LOG  $BOOT_LOG"
ok "install and boot both succeeded"
