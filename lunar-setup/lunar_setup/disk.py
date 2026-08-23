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

import json
import subprocess

MAPPER = "lunarcrypt"
VG = "lunar"


def run(cmd, check=True, input_=None, log=None):
    if log:
        log("  $ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, input=input_, text=True,
                          capture_output=True)


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


def partition(disk: str, log=None) -> tuple:
    """Wipe signatures and lay down GPT. Returns (esp, luks_part)."""
    run(["wipefs", "-a", disk], log=log)
    run(["sgdisk", "-Z", disk], log=log)
    run(["sgdisk",
         "-n", "1:0:+1024M", "-t", "1:ef00", "-c", "1:LUNAR_ESP",
         "-n", "2:0:0", "-t", "2:8309", "-c", "2:LUNAR_LUKS",
         disk], log=log)
    run(["partprobe", disk], check=False, log=log)
    suffix = "p" if disk[-1].isdigit() else ""
    return f"{disk}{suffix}1", f"{disk}{suffix}2"


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
    run(["vgcreate", VG, target], log=log)
    run(["lvcreate", "-L", f"{swap_gib}G", "-n", "swap", VG], log=log)
    run(["lvcreate", "-l", "100%FREE", "-n", "root", VG], log=log)

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
    run(["mkfs.fat", "-F32", "-n", "LUNARESP", esp], log=log)
    run(["mkdir", "-p", "/mnt/efi"], log=log)
    run(["mount", "-o", "umask=0077,nodev,nosuid,noexec", esp, "/mnt/efi"], log=log)


def luks_uuid(part: str) -> str:
    return subprocess.run(["blkid", "-s", "UUID", "-o", "value", part],
                          capture_output=True, text=True, check=True).stdout.strip()
