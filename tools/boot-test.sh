#!/usr/bin/env bash
# Boot a disk image that was already installed, and check it reaches a login
# prompt on its own.
#
# This is the half that the loopback install test cannot answer: an installer
# can write every file correctly and still produce something that does not
# boot, because the boot loader, the unified kernel image or the command line
# is wrong. Nothing short of booting it finds that.
#
# No installation happens here, so it takes a minute or two rather than an
# hour.
#
#   tools/boot-test.sh out/lunar-test-disk.qcow2

set -uo pipefail

IMAGE="${1:-}"
WORK="${WORK:-$(mktemp -d)}"
mkdir -p "$WORK"
LOG="$WORK/boot.log"
TIMEOUT="${BOOT_TIMEOUT:-600}"
MEM="${MEM:-2048}"

red=$'\033[31m'; green=$'\033[32m'; dim=$'\033[2m'; cyan=$'\033[36m'; off=$'\033[0m'
say()  { printf '\n%s::%s %s\n' "$cyan" "$off" "$*"; }
fail() { printf '\n%s!!%s %s\n' "$red" "$off" "$*" >&2; }
ok()   { printf '\n%s ok%s %s\n' "$green" "$off" "$*"; }

[[ -f "$IMAGE" ]] || { fail "usage: $0 <disk image>"; exit 1; }
command -v qemu-system-x86_64 >/dev/null || { fail "qemu-system-x86_64 missing"; exit 1; }

find_fw() { for f in "$@"; do [[ -f "$f" ]] && { echo "$f"; return; }; done; }
FW_CODE="$(find_fw \
    /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd \
    /usr/share/edk2/x64/OVMF_CODE.4m.fd /usr/share/edk2-ovmf/x64/OVMF_CODE.fd \
    /opt/homebrew/share/qemu/edk2-x86_64-code.fd \
    /usr/local/share/qemu/edk2-x86_64-code.fd)"
FW_VARS_SRC="$(find_fw \
    /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd \
    /usr/share/edk2/x64/OVMF_VARS.4m.fd /usr/share/edk2-ovmf/x64/OVMF_VARS.fd)"
[[ -n "$FW_CODE" ]] || { fail "no UEFI firmware found"; exit 1; }

FW_VARS="$WORK/OVMF_VARS.fd"
if [[ -n "$FW_VARS_SRC" ]]; then
    cp "$FW_VARS_SRC" "$FW_VARS" || { fail "could not copy firmware variables"; exit 1; }
else
    qemu-img create -f raw "$FW_VARS" 4M >/dev/null
fi
chmod u+w "$FW_VARS"

ACCEL="tcg"; [[ -w /dev/kvm ]] && ACCEL="kvm"
say "booting $(basename "$IMAGE")  firmware $(basename "$FW_CODE")  accel $ACCEL"

FMT="qcow2"
[[ "$IMAGE" == *.img ]] && FMT="raw"

timeout "$TIMEOUT" qemu-system-x86_64 \
    -machine q35 -accel "$ACCEL" -m "$MEM" -smp 2 \
    -drive if=pflash,format=raw,readonly=on,file="$FW_CODE" \
    -drive if=pflash,format=raw,file="$FW_VARS" \
    -drive file="$IMAGE",if=virtio,format="$FMT" \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -nographic > "$LOG" 2>&1

# A login prompt is the proof. Everything before it can succeed while the
# system still fails to come up.
if grep -qE "lunaros login:|login:" "$LOG"; then
    ok "the installed system booted to a login prompt"
    grep -m1 -E "login:" "$LOG" | sed 's/^/   /'
    exit 0
fi

fail "the installed system did not reach a login prompt"

# Name the failure rather than leaving 600 lines to read.
if grep -qi "No bootable device\|BdsDxe: failed to load" "$LOG"; then
    echo "  the firmware found nothing to boot: the boot loader or the"
    echo "  unified kernel image was not installed where firmware looks"
elif grep -qi "Failed to mount\|Dependency failed\|emergency mode" "$LOG"; then
    echo "  the kernel started but the system could not mount its root:"
    grep -iE "Failed to mount|Dependency failed|emergency" "$LOG" | head -5 | sed 's/^/    /'
elif grep -qi "Kernel panic" "$LOG"; then
    echo "  kernel panic:"
    grep -iA3 "Kernel panic" "$LOG" | head -8 | sed 's/^/    /'
elif [[ ! -s "$LOG" ]]; then
    echo "  the virtual machine produced no output at all"
fi

echo "$dim--- last 60 lines ---$off"
tail -60 "$LOG"
echo "$dim--- full log at $LOG ---$off"
exit 1
