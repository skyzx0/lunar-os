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
    [[ -f /run/dbus/pid ]] && kill "$(cat /run/dbus/pid)" 2>/dev/null
    [[ -n "$PARTX_POLLER" ]] && kill "$PARTX_POLLER" 2>/dev/null
    [[ "${UEFI_SHIM:-0}" == 1 ]] && umount /sys/firmware 2>/dev/null
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

# archinstall formats the ESP as FAT32 and mounts it. A kernel without vfat
# support fails that mount deep into the run with "unknown filesystem type";
# check here instead, where the reason is obvious.
modprobe vfat 2>/dev/null || true
if ! grep -qw vfat /proc/filesystems; then
    probe_img="$WORK/vfat-probe.img"
    truncate -s 8M "$probe_img" && mkfs.fat "$probe_img" >/dev/null 2>&1
    mkdir -p "$WORK/vfat-probe"
    if mount -o loop "$probe_img" "$WORK/vfat-probe" 2>/dev/null; then
        umount "$WORK/vfat-probe"
    else
        fail "this kernel cannot mount FAT32, which the EFI partition needs"
        exit 1
    fi
    rm -f "$probe_img"
fi

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

# archinstall calls several systemd client tools directly on this container -
# timedatectl waiting for clock sync, systemctl checking on reflector.service,
# localectl validating the chosen keymap - each failing the same way: "System
# has not been booted with systemd as init system" or "Failed to connect to
# system scope bus". Three different call sites, three different failures
# across four rounds of chasing this, because they were patched one at a
# time with the skip flags archinstall happens to expose (--offline,
# --skip-ntp, --skip-wkd). localectl's keymap check has no such flag, and
# there is no guarantee it is the last one that does not.
#
# Both messages trace to the same two missing things, neither related to the
# flags above: systemd client tools refuse to run at all unless
# /run/systemd/system exists (their sd_booted() check, tested directly - it
# is checked before anything touches the bus), and even past that they need
# an actual system bus to talk to. This container has neither, because
# nothing here runs systemd as PID 1. Providing both closes every call of
# this shape at once, present or future, rather than special-casing each one
# archinstall happens to hit.
start_dbus() {
    mkdir -p /run/systemd/system /run/dbus
    command -v dbus-daemon >/dev/null || { fail "dbus-daemon is missing"; return 1; }
    rm -f /run/dbus/pid /run/dbus/system_bus_socket
    dbus-daemon --system --fork
    for _ in $(seq 1 20); do
        [[ -S /run/dbus/system_bus_socket ]] && return 0
        sleep 0.1
    done
    fail "dbus-daemon did not create its socket in time"
    return 1
}

# archinstall installs systemd-boot only if the running system booted through
# UEFI, which it decides by whether /sys/firmware/efi exists. Whether a CI
# runner exposes that depends on how the runner itself was booted, which is
# outside anyone's control. Inside this throwaway container, present a
# stand-in: a tmpfs over /sys/firmware with the one directory archinstall
# checks. Firmware variables are not writable, so bootctl falls back to
# installing without touching NVRAM - which is also the safe thing for a
# test to do. On a real machine none of this runs.
UEFI_SHIM=0
if [[ ! -d /sys/firmware/efi ]]; then
    say "no UEFI in this container; presenting a stand-in for archinstall"
    mount -t tmpfs lunar-efi /sys/firmware \
        && mkdir -p /sys/firmware/efi/efivars \
        && echo 64 > /sys/firmware/efi/fw_platform_size \
        && UEFI_SHIM=1
    [[ -d /sys/firmware/efi ]] || { fail "could not present UEFI; systemd-boot cannot be installed"; exit 1; }
fi

# Prefer the host's udevd, shared in through /run/udev. It receives kernel
# device events; one started inside this container would not, because those
# events are delivered only to the host's network namespace. Start our own
# only when no udevd is reachable at all, as a last resort.
if udevadm control --ping 2>/dev/null; then
    say "using the host's udev"
else
    say "no reachable udev; starting one (partition UUIDs may be missing)"
    start_udev || fail "continuing without udev"
fi

say "starting a system D-Bus (needed by timedatectl/localectl/systemctl)"
start_dbus || fail "continuing without dbus; some archinstall checks may fail"

LOOP="$(losetup -P -f --show "$IMAGE")"
[[ -n "$LOOP" ]] || { fail "could not attach a loop device"; exit 1; }
say "attached $LOOP"
udevadm settle --timeout=10 2>/dev/null || true

# archinstall repartitions the disk itself, mid-install, then wipes the new
# partitions' signatures immediately - with no pause in between. On a loop
# device nothing tells the kernel to re-read the partition table, so the
# /dev/loopNpM node does not exist yet and wipefs fails with "No such file or
# directory". That is the failure this handles.
#
# Two things that looked like fixes and were not, both tested:
#   - udev alone: there is no event for it to react to until something asks
#     the kernel to rescan.
#   - a background loop running `partx -u`: archinstall calls wipefs within
#     microseconds of writing the table, faster than any polling interval.
#     Eight attempts, eight failures.
#
# What works is doing the rescan at the moment it is needed: a wipefs on PATH
# ahead of the real one which, if its target does not exist yet, runs
# `partx -u` on the parent disk and waits for the node before handing over.
# Eight attempts, eight clean wipes. archinstall finds binaries with
# shutil.which, so a wrapper earlier on PATH is what it runs. This applies
# only inside the test; a live medium has udev and a real disk.
SHIMS="$WORK/shims"
mkdir -p "$SHIMS"
cat > "$SHIMS/wipefs" <<'SHIM'
#!/usr/bin/env bash
real="$(PATH=/usr/sbin:/usr/bin:/sbin:/bin command -v -- wipefs)"
target="${*: -1}"
if [[ "$target" == /dev/* && ! -e "$target" ]]; then
    parent="$(printf '%s' "$target" | sed -E 's/p?[0-9]+$//')"
    name="$(basename "$target")"
    for _ in $(seq 1 150); do
        partx -u "$parent" 2>/dev/null
        [[ -e "$target" ]] && break
        # Where /dev is not the kernel's devtmpfs, the kernel knows the
        # partition but nothing creates its node; do it from sysfs.
        if [[ -r "/sys/class/block/$name/dev" ]]; then
            IFS=: read -r maj min < "/sys/class/block/$name/dev"
            mknod "$target" b "$maj" "$min" 2>/dev/null
            [[ -e "$target" ]] && break
        fi
        sleep 0.02
    done
fi
exec "$real" "$@"
SHIM
chmod +x "$SHIMS/wipefs"

# lsblk takes partition numbers and UUIDs from udev's database. Where udev
# cannot see kernel events - a container, unless it shares the host's udev -
# those come back empty and archinstall stops with "Unable to determine new
# partition number". The shim runs the real lsblk and fills only the empty
# fields from sysfs and blkid; where udev works, it changes nothing.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -m755 "$SCRIPT_DIR/shims/lsblk" "$SHIMS/lsblk"

# localectl's keyboard-layout queries route through systemd-localed over
# D-Bus, which the plain dbus-daemon above does not provide (it is a bus,
# not the service registered on it). This answers the same two read-only
# queries directly from disk.
install -m755 "$SCRIPT_DIR/shims/localectl" "$SHIMS/localectl"

export PATH="$SHIMS:$PATH"
PARTX_POLLER=""

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
# archinstall unmounts the target when it finishes, so mount it again here to
# look inside. The layout is known: partition 1 is the ESP (mounted at /boot,
# which is where systemd-boot and the unified kernel images live), partition 2
# is the root.

CHECK="$WORK/check"
mkdir -p "$CHECK"
udevadm settle --timeout=10 2>/dev/null || true
partx -u "$LOOP" 2>/dev/null || true

say "mounting the result to inspect it"
mount "${LOOP}p2" "$CHECK" || { fail "could not mount the installed root"; exit 1; }
mkdir -p "$CHECK/boot"
mount "${LOOP}p1" "$CHECK/boot" || { fail "could not mount the ESP"; exit 1; }

problems=0
check() {
    if compgen -G "$CHECK/$1" >/dev/null; then
        printf '   %-46s ok\n' "$1"
    else
        printf '   %-46s %sMISSING%s\n' "$1" "$red" "$off"
        problems=1
    fi
}

say "what was produced"
check etc/fstab
check etc/hostname
check etc/passwd
check etc/pacman.conf
check usr/lib/os-release
check "boot/EFI/Linux/*.efi"
check boot/EFI/systemd/systemd-bootx64.efi
# The fallback path firmware boots when it has no entry of its own - which is
# how a freshly installed disk starts, and how the boot test starts it.
check boot/EFI/BOOT/BOOTX64.EFI
check boot/loader/loader.conf

say "identity"
if grep -q 'Lunar OS' "$CHECK/usr/lib/os-release" 2>/dev/null; then
    echo "   os-release says Lunar OS"
else
    echo "   ${red}os-release does not name Lunar OS${off}"
    problems=1
fi

say "the account"
if grep -q '^tester:' "$CHECK/etc/passwd"; then
    echo "   tester exists"
else
    echo "   ${red}tester is missing${off}"
    problems=1
fi

say "first boot"
if [[ -L "$CHECK/etc/systemd/system/systemd-firstboot.service" ]]; then
    echo "   systemd-firstboot is masked"
else
    echo "   ${red}systemd-firstboot is not masked: first boot would stop and ask questions${off}"
    problems=1
fi

say "the unified kernel image"
ls -lh "$CHECK"/boot/EFI/Linux/*.efi 2>/dev/null | sed 's/^/   /' \
    || echo "   ${red}none - this would not boot${off}"

say "the kernel command line"
[[ -f "$CHECK/etc/kernel/cmdline" ]] && sed 's/^/   /' "$CHECK/etc/kernel/cmdline"

say "Lunar commands"
for cmd in ltxs lunarfetch lunar-privacy; do
    if [[ -x "$CHECK/usr/bin/$cmd" ]]; then
        printf '   %-16s installed\n' "$cmd"
    else
        printf '   %-16s not installed\n' "$cmd"
    fi
done

umount "$CHECK/boot" 2>/dev/null
umount "$CHECK" 2>/dev/null

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
