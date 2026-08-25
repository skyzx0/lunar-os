"""Disk layout: GPT, ESP, LUKS2 container, LVM, btrfs subvolumes.

Layout produced (whole-disk, no dual boot):

    /dev/sdX1   1024 MiB   EF00   ESP, holds the signed unified kernel image
    /dev/sdX2   rest       8309   LUKS2 -> LVM VG "lunar"
                                    lv root   (btrfs or ext4)
                                    lv swap   (encrypted by inheritance)

/boot lives inside the ESP only as a UKI. Kernel, initramfs, cmdline and
microcode are baked into one PE binary and signed, so nothing outside the
LUKS container is both unsigned and load-bearing.
"""

import glob
import json
import os
import subprocess

MAPPER = "lunarcrypt"
VG = "lunar"


class CommandFailed(RuntimeError):
    """A failed command, carrying what the command actually said.

    subprocess.CalledProcessError stringifies to the command and exit code
    only. When stderr is captured, that means the one piece of information
    needed to fix the problem is the piece that gets discarded.
    """

    def __init__(self, cmd, returncode, stderr, stdout=""):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = (stderr or "").strip()
        self.stdout = (stdout or "").strip()
        detail = self.stderr or self.stdout or "(no output)"
        super().__init__(f"{' '.join(cmd)}\n  exit {returncode}: {detail}")


def run(cmd, check=True, input_=None, log=None, timeout=None):
    """Run a command with its output captured and its input closed.

    stdin is /dev/null unless something is explicitly passed. With output
    captured, any command that decides to prompt - LVM asking whether to wipe
    a signature it found, fsck asking to repair - writes the question into a
    pipe nobody can see and then waits forever for an answer. Closing stdin
    turns that silent hang into an immediate, visible failure.
    """
    if log:
        log("  $ " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, check=False,
                           input=input_,
                           stdin=None if input_ is not None else subprocess.DEVNULL,
                           text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # With stdin closed a prompt cannot hang us, but a device that stops
        # responding still can. Report it rather than sitting there.
        raise CommandFailed(cmd, -1,
                            f"timed out after {timeout}s with no output") from None
    if r.returncode != 0:
        if log and (r.stderr or "").strip():
            for line in r.stderr.strip().splitlines()[:6]:
                log("    " + line)
        if check:
            raise CommandFailed(cmd, r.returncode, r.stderr, r.stdout)
    return r


def list_disks():
    """Return [(path, model, size_human, rotational)] for real block devices."""
    out = subprocess.run(
        ["lsblk", "-J", "-d", "-b", "-o", "NAME,PATH,SIZE,MODEL,TYPE,RM,RO"],
        capture_output=True, text=True, check=True).stdout
    disks = []
    for d in json.loads(out)["blockdevices"]:
        if d["type"] != "disk" or d.get("ro"):
            continue
        size = int(d["size"])
        if size < 16 * 1024**3:          # 16 GiB floor
            continue
        disks.append((d["path"], (d.get("model") or "unknown").strip(),
                      human(size), bool(d.get("rm"))))
    return disks


def human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def memory_bytes() -> int:
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    return 8 * 1024**3


def existing_partitions(disk: str) -> list:
    """Partition device paths currently present on disk."""
    out = subprocess.run(["lsblk", "-lno", "PATH,TYPE", disk],
                         capture_output=True, text=True).stdout
    return [line.split()[0] for line in out.splitlines()
            if line.split()[-1] == "part"]


def release_disk(disk: str, log=None) -> None:
    """Free a disk still held from an earlier attempt.

    A failed install leaves the target mounted, its volume group active and
    its swap enabled - deliberately, so the state can be inspected. All of
    that keeps the kernel holding the device, and the next run then fails at
    the first command with "Device or resource busy", which names neither the
    holder nor the fix.

    Everything here is best-effort: on a first install there is nothing to
    release and every call is a no-op.
    """
    base = os.path.basename(disk)

    # Swap on the target keeps its logical volume open.
    run(["swapoff", "-a"], check=False, log=log)

    # An earlier run may have left the new root mounted.
    subprocess.run(["umount", "-R", "/mnt"], capture_output=True, text=True)

    # Deactivate volume groups whose physical volumes live on this disk. Only
    # this disk: deactivating everything would take out the running system if
    # the installer is ever run from an installed one.
    pvs = subprocess.run(["pvs", "--noheadings", "-o", "pv_name,vg_name"],
                         capture_output=True, text=True).stdout
    for line in pvs.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].startswith(disk):
            if log:
                log(f"  releasing volume group {fields[1]}")
            run(["vgchange", "-an", fields[1]], check=False, log=log)

    # Close device-mapper devices stacked on this disk: LUKS containers from
    # a previous encrypted attempt, and any leftover LVM mappings.
    for entry in sorted(glob.glob(f"/sys/class/block/{base}*")):
        holders = os.path.join(entry, "holders")
        if not os.path.isdir(holders):
            continue
        for holder in os.listdir(holders):
            name_file = f"/sys/class/block/{holder}/dm/name"
            try:
                with open(name_file) as fh:
                    name = fh.read().strip()
            except OSError:
                continue
            if log:
                log(f"  releasing mapping {name}")
            run(["cryptsetup", "close", name], check=False)
            run(["dmsetup", "remove", "--force", name], check=False)

    run(["udevadm", "settle"], check=False, log=log)


def suspend_autoactivation(log=None) -> None:
    """Stop LVM from reactivating volume groups mid-install.

    udev runs pvscan on every new partition. On a reinstall it finds the
    previous run's metadata, activates the volume group, and the device is
    held before the installer can wipe it. Masking the unit for the duration
    of the install removes the race rather than trying to win it.
    """
    run(["systemctl", "mask", "--runtime", "lvm2-pvscan@.service"],
        check=False, log=log)


def resume_autoactivation(log=None) -> None:
    run(["systemctl", "unmask", "--runtime", "lvm2-pvscan@.service"],
        check=False, log=log)


def disk_is_busy(disk: str) -> str:
    """Return a description of what still holds the disk, or an empty string."""
    base = os.path.basename(disk)
    holders = []
    for entry in sorted(glob.glob(f"/sys/class/block/{base}*")):
        hdir = os.path.join(entry, "holders")
        if os.path.isdir(hdir):
            holders += os.listdir(hdir)

    mounted = subprocess.run(["findmnt", "-rno", "SOURCE,TARGET"],
                             capture_output=True, text=True).stdout
    mounts = [l for l in mounted.splitlines() if l.startswith(disk)]

    parts = []
    if holders:
        parts.append("device-mapper holders: " + ", ".join(sorted(set(holders))))
    if mounts:
        parts.append("still mounted: " + "; ".join(mounts))
    return "  ".join(parts)


def partition(disk: str, log=None) -> tuple:
    """Wipe signatures and lay down GPT. Returns (esp, luks_part)."""
    suspend_autoactivation(log=log)
    release_disk(disk, log=log)

    busy = disk_is_busy(disk)
    if busy:
        raise CommandFailed(
            ["release", disk], 1,
            f"{disk} is still in use after releasing it.\n"
            f"  {busy}\n"
            "  Reboot the live medium and try again; something outside the\n"
            "  installer is holding the disk.")

    # Signatures live inside the partitions, and sgdisk only rewrites the
    # table. Clear them while the partitions still exist: once the table is
    # replaced, udev sees the same old LVM metadata in the new partition,
    # autoactivates the volume group, and the device is busy before anything
    # here gets a chance to touch it.
    for part in existing_partitions(disk):
        run(["wipefs", "-a", part], check=False, log=log)

    run(["wipefs", "-a", disk], log=log)
    run(["sgdisk", "-Z", disk], log=log)
    run(["sgdisk",
         "-n", "1:0:+1024M", "-t", "1:ef00", "-c", "1:LUNAR_ESP",
         "-n", "2:0:0", "-t", "2:8309", "-c", "2:LUNAR_LUKS",
         disk], log=log)
    run(["partprobe", disk], check=False, log=log)
    run(["udevadm", "settle"], check=False, log=log)

    suffix = "p" if disk[-1].isdigit() else ""
    esp, data = f"{disk}{suffix}1", f"{disk}{suffix}2"

    # udev may have autoactivated something off the new partitions in the
    # moment between creating them and wiping them.
    release_disk(disk, log=log)

    for part in (esp, data):
        run(["wipefs", "-a", part], check=False, log=log)

    # LVM headers sit in the first megabytes and survive a wipefs that was
    # blocked. Zeroing the start is decisive, cheap, and means the next tool
    # finds nothing to ask about.
    run(["dd", "if=/dev/zero", f"of={data}", "bs=1M", "count=16",
         "conv=fsync"], check=False, log=log)
    run(["udevadm", "settle"], check=False, log=log)

    still_busy = disk_is_busy(disk)
    if still_busy:
        raise CommandFailed(
            ["prepare", disk], 1,
            f"{disk} became busy again after partitioning.\n"
            f"  {still_busy}\n"
            "  Something is reactivating it. Reboot and retry.")

    return esp, data


def secure_erase(part: str, log=None) -> None:
    """Fill with random data via a throwaway LUKS mapping - far faster than
    /dev/urandom and just as opaque to an analyst."""
    run(["cryptsetup", "open", "--type", "plain", "-d", "/dev/urandom",
         part, "lunarwipe"], log=log)
    subprocess.run(["dd", "if=/dev/zero", "of=/dev/mapper/lunarwipe",
                    "bs=16M", "status=progress", "oflag=direct"], check=False)
    run(["cryptsetup", "close", "lunarwipe"], log=log)


def luks_format(part: str, passphrase: str, log=None) -> None:
    run(["cryptsetup", "luksFormat",
         "--type", "luks2",
         "--cipher", "aes-xts-plain64",
         "--key-size", "512",
         "--hash", "sha512",
         "--pbkdf", "argon2id",
         "--pbkdf-memory", "1048576",     # 1 GiB
         "--pbkdf-parallel", "4",
         "--iter-time", "5000",
         "--sector-size", "4096",
         "--use-random",
         "--batch-mode", part],
        input_=passphrase, log=log)
    run(["cryptsetup", "open", part, MAPPER], input_=passphrase, log=log)


def make_volumes(filesystem: str, log=None, target: str = None) -> None:
    """Build LVM and filesystems on target.

    target defaults to the opened LUKS container. On an unencrypted install it
    is the bare partition, and everything above this layer is identical - which
    is why encryption is a single decision rather than a different installer.
    """
    if target is None:
        target = f"/dev/mapper/{MAPPER}"
    swap_gib = max(2, min(16, round(memory_bytes() / 1024**3)))

    run(["pvcreate", "-ff", "-y", target], log=log)
    run(["vgcreate", "-y", VG, target], log=log)
    # -y answers the "wipe the signature I found?" prompt that a previous
    # attempt's filesystem leaves behind. -Zy zeroes the start of the volume
    # so the next tool does not find that signature either.
    run(["lvcreate", "-y", "-Zy", "-W", "y", "-L", f"{swap_gib}G",
         "-n", "swap", VG], log=log)
    run(["lvcreate", "-y", "-Zy", "-W", "y", "-l", "100%FREE",
         "-n", "root", VG], log=log)

    root = f"/dev/{VG}/root"
    if filesystem == "btrfs":
        run(["mkfs.btrfs", "-f", "-L", "lunar", root], log=log)
        run(["mount", root, "/mnt"], log=log)
        for sub in ("@", "@home", "@log", "@pkg", "@snapshots", "@var"):
            run(["btrfs", "subvolume", "create", f"/mnt/{sub}"], log=log)
        run(["umount", "/mnt"], log=log)

        opts = "noatime,compress=zstd:3,ssd,space_cache=v2"
        run(["mount", "-o", f"{opts},subvol=@", root, "/mnt"], log=log)
        for sub, path, extra in (
            ("@home", "/mnt/home", "nodev,nosuid"),
            ("@var", "/mnt/var", "nodev,nosuid,noexec"),
            ("@log", "/mnt/var/log", "nodev,nosuid,noexec"),
            ("@pkg", "/mnt/var/cache/pacman/pkg", "nodev,nosuid,noexec"),
            ("@snapshots", "/mnt/.snapshots", "nodev,nosuid,noexec"),
        ):
            run(["mkdir", "-p", path], log=log)
            run(["mount", "-o", f"{opts},subvol={sub},{extra}", root, path], log=log)
    else:
        run(["mkfs.ext4", "-F", "-L", "lunar", root], log=log)
        run(["mount", "-o", "noatime", root, "/mnt"], log=log)

    run(["mkswap", "-L", "lunarswap", f"/dev/{VG}/swap"], log=log)
    run(["swapon", f"/dev/{VG}/swap"], log=log)


def mount_esp(esp: str, log=None) -> None:
    # udev has to catch up with the new partition table before the device node
    # is reliably usable; without this the mkfs can succeed and the mount that
    # follows it fail on the same path.
    run(["udevadm", "settle"], check=False, log=log)
    # mount normally auto-loads the driver, but not on every kernel and not
    # when the module is built as one that autoload does not cover.
    run(["modprobe", "vfat"], check=False, log=log)
    run(["mkfs.fat", "-F32", "-n", "LUNARESP", esp], log=log)
    run(["udevadm", "settle"], check=False, log=log)
    run(["mkdir", "-p", "/mnt/efi"], log=log)

    # -t vfat explicitly: autodetection reads the superblock, and on a
    # just-created filesystem the kernel may still have the old one cached.
    opts = "umask=0077,nodev,nosuid,noexec"
    r = run(["mount", "-t", "vfat", "-o", opts, esp, "/mnt/efi"],
            check=False, log=log)
    if r.returncode != 0:
        # Some firmware-written ESPs reject noexec. Losing it is a small
        # hardening loss and better than an install that cannot finish.
        if log:
            log("    retrying without noexec")
        r = run(["mount", "-t", "vfat", "-o", "umask=0077,nodev,nosuid",
                 esp, "/mnt/efi"], check=False, log=log)
    if r.returncode != 0:
        raise CommandFailed(["mount", esp, "/mnt/efi"], r.returncode, r.stderr)


def luks_uuid(part: str) -> str:
    return subprocess.run(["blkid", "-s", "UUID", "-o", "value", part],
                          capture_output=True, text=True, check=True).stdout.strip()
