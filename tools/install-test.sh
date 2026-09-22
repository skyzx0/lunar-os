#!/usr/bin/env bash
# Install Lunar OS to a loopback disk image, inside the build container.
#
# The installer needs a block device, not a virtual machine. A loop device is
# one, so the whole thing - partitioning, LVM, filesystems, pacstrap, chroot
# configuration, the boot loader - runs for real in a few minutes instead of
# an hour of emulated boot.
#
# What this does not check is whether the result boots. That needs firmware
# and a kernel, and is a separate, shorter test.
#
#   tools/install-test.sh [image-size-GiB]

set -uo pipefail

SIZE="${1:-20}"
WORK="${WORK:-/build/install-test}"
IMAGE="$WORK/disk.img"
LOG="$WORK/install.log"

red=$'\033[31m'; green=$'\033[32m'; dim=$'\033[2m'; cyan=$'\033[36m'; off=$'\033[0m'
say()  { printf '\n%s::%s %s\n' "$cyan" "$off" "$*"; }
fail() { printf '\n%s!!%s %s\n' "$red" "$off" "$*" >&2; }
ok()   { printf '\n%s ok%s %s\n' "$green" "$off" "$*"; }

LOOP=""
UDEVD_PID=""
cleanup() {
    say "cleaning up"
    swapoff -a 2>/dev/null
    umount -R /mnt 2>/dev/null
    vgchange -an lunar 2>/dev/null
    [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null
    [[ -n "$UDEVD_PID" ]] && kill "$UDEVD_PID" 2>/dev/null
}
trap cleanup EXIT

[[ $EUID -eq 0 ]] || { fail "must run as root"; exit 1; }
for cmd in losetup sgdisk partprobe wipefs pacstrap arch-chroot \
           pvcreate vgcreate lvcreate mkfs.ext4 mkfs.btrfs mkfs.fat \
           genfstab cryptsetup udevadm; do
    command -v "$cmd" >/dev/null || { fail "$cmd is missing"; exit 1; }
done

mkdir -p "$WORK"
rm -f "$IMAGE"

say "creating a ${SIZE} GiB image"
truncate -s "${SIZE}G" "$IMAGE"

# -P so the kernel creates partition nodes: the installer addresses them as
# ${disk}p1 and ${disk}p2, exactly as it would on an NVMe drive.
# The installer's own partition() calls partprobe after sgdisk and expects
# the resulting /dev/loopNpM nodes to exist, the way they always do on a
# real boot with udev running. Nothing in this container reacts to the
# kernel's partition uevents, so start udevd for the duration of the test
# rather than teaching the installer about a gap that only exists here.
start_udev() {
    local bin
    bin="$(command -v udevd || command -v /usr/lib/systemd/systemd-udevd || true)"
    if [[ -z "$bin" ]]; then
        fail "no udev daemon binary found (systemd-udevd or udevd)"
        return 1
    fi
    "$bin" --daemon 2>/dev/null &
    UDEVD_PID=$!
    # trigger picks up devices that already existed (the loop control node);
    # settle waits for the queue this starts to actually drain.
    udevadm trigger 2>/dev/null || true
    udevadm settle --timeout=10 2>/dev/null || true
}

say "starting udev (needed for loop partition device nodes)"
start_udev || fail "continuing without udev; partition nodes may not appear"

LOOP="$(losetup -P -f --show "$IMAGE")"
[[ -n "$LOOP" ]] || { fail "could not attach a loop device"; exit 1; }
say "attached $LOOP"
udevadm settle --timeout=10 2>/dev/null || true

# Belt and braces: create any node udev still missed by reading the kernel's
# own partition table directly from sysfs. Cheap, and makes the difference
# between a real failure and a race that only happens in CI.
sync_loop_nodes() {
    local base
    base="$(basename "$LOOP")"
    for part in "/sys/class/block/$base"/"$base"p*; do
        [[ -d "$part" ]] || continue
        local name maj min
        name="$(basename "$part")"
        IFS=: read -r maj min < "$part/dev"
        [[ -e "/dev/$name" ]] || mknod "/dev/$name" b "$maj" "$min"
    done
}
sync_loop_nodes

# The device manager is not running in a container, so the installer's waits
# for it return immediately. That is fine; the partitions appear synchronously.
ANSWERS="$WORK/answers.json"
cat > "$ANSWERS" <<EOF
{
  "disk": "$LOOP",
  "encrypt": false,
  "filesystem": "ext4",
  "hostname": "lunaros",
  "username": "tester",
  "user_password": "lunar",
  "root_locked": true,
  "timezone": "UTC",
  "locale": "en_US.UTF-8",
  "keymap": "us",
  "desktop": "minimal",
  "profile": "baseline",
  "fast": true
}
EOF

say "installing (log $LOG)"
set -o pipefail
if lunaros-setup --unattended "$ANSWERS" 2>&1 | tee "$LOG"; then
    ok "the installer completed"
else
    rc=$?
    fail "the installer failed (exit $rc)"
    echo "$dim--- last 60 lines ---$off"
    tail -60 "$LOG"
    exit 1
fi

# --- check the result is a system, not just a filled disk -----------------

say "checking what was produced"
problems=0
check() {
    if [[ -e "/mnt/$1" ]]; then
        printf '   %-46s ok\n' "$1"
    else
        printf '   %-46s %sMISSING%s\n' "$1" "$red" "$off"
        problems=1
    fi
}

check etc/fstab
check etc/hostname
check etc/os-release
check etc/passwd
check etc/pacman.conf
check etc/machine-id
check usr/bin/ltxs
check usr/bin/lunaros-setup
check boot/vmlinuz-linux-hardened
check efi/EFI/Linux
check efi/EFI/systemd/systemd-bootx64.efi
check etc/systemd/system/display-manager.service 2>/dev/null || true

say "the account"
grep -q '^tester:' /mnt/etc/passwd \
    && echo "   tester exists" \
    || { echo "   ${red}tester is missing${off}"; problems=1; }

say "the unified kernel image"
if compgen -G "/mnt/efi/EFI/Linux/*.efi" >/dev/null; then
    ls -lh /mnt/efi/EFI/Linux/*.efi | sed 's/^/   /'
else
    echo "   ${red}no unified kernel image was produced - this would not boot${off}"
    problems=1
fi

say "the kernel command line"
[[ -f /mnt/etc/kernel/cmdline ]] && sed 's/^/   /' /mnt/etc/kernel/cmdline

if (( problems )); then
    fail "the installation finished but the result is incomplete"
    exit 1
fi

# Hand the image to the boot test. Converting to qcow2 drops the unwritten
# parts of a 20 GiB sparse file to a few hundred megabytes.
trap - EXIT
cleanup

OUT_IMAGE="${OUT:-/out}/lunar-test-disk.qcow2"
if command -v qemu-img >/dev/null; then
    say "exporting the installed disk for the boot test"
    qemu-img convert -O qcow2 -c "$IMAGE" "$OUT_IMAGE" \
        && ls -lh "$OUT_IMAGE" | sed 's/^/   /'
else
    say "qemu-img not present; copying the raw image"
    cp --sparse=always "$IMAGE" "${OUT:-/out}/lunar-test-disk.img"
fi

ok "install test passed"
