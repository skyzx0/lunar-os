"""Manual installation commands, and a way to check the memory claims.

The steps here are the same operations install.py performs. They are kept in
one string rather than generated from the code because a manual procedure has
to be readable and adaptable, which generated output never is.
"""

import os
import subprocess

STEPS = r"""
Lunar OS - manual installation
==============================

The guided installer (lunar-setup) does all of this. Follow it by hand if you
want a layout the wizard does not offer, or to see exactly what it does.

Replace /dev/nvme0n1 with your target disk throughout. Everything on it will
be destroyed.

1. Identify the disk
--------------------
    lsblk -d -o NAME,PATH,SIZE,MODEL

2. Partition
------------
    sgdisk -Z /dev/nvme0n1
    sgdisk -n 1:0:+1024M -t 1:ef00 -c 1:LUNAR_ESP \
           -n 2:0:0      -t 2:8309 -c 2:LUNAR_LUKS /dev/nvme0n1

3. Encrypt
----------
argon2id with a 1 GiB memory cost is what makes an offline attack on the
passphrase expensive rather than merely slow. Lower it only if the machine
cannot spare the RAM at boot.

    cryptsetup luksFormat --type luks2 --cipher aes-xts-plain64 \
        --key-size 512 --hash sha512 --pbkdf argon2id \
        --pbkdf-memory 1048576 --pbkdf-parallel 4 --iter-time 5000 \
        --sector-size 4096 --use-random /dev/nvme0n1p2
    cryptsetup open /dev/nvme0n1p2 lunarcrypt

4. LVM inside the container
---------------------------
Swap lives inside the encrypted container, so hibernation images are encrypted
too. Swap outside it would leak whatever was in RAM.

    pvcreate /dev/mapper/lunarcrypt
    vgcreate lunar /dev/mapper/lunarcrypt
    lvcreate -L 8G -n swap lunar
    lvcreate -l 100%FREE -n root lunar

5. Filesystems
--------------
    mkfs.btrfs -f -L lunar /dev/lunar/root
    mkswap /dev/lunar/swap && swapon /dev/lunar/swap

    mount /dev/lunar/root /mnt
    for s in @ @home @var @log @pkg @snapshots; do
        btrfs subvolume create "/mnt/$s"
    done
    umount /mnt

    opts=noatime,compress=zstd:3,ssd,space_cache=v2
    mount -o $opts,subvol=@ /dev/lunar/root /mnt
    mkdir -p /mnt/{home,var,efi}
    mount -o $opts,subvol=@home,nodev,nosuid           /dev/lunar/root /mnt/home
    mount -o $opts,subvol=@var,nodev,nosuid,noexec     /dev/lunar/root /mnt/var
    mkdir -p /mnt/var/log /mnt/var/cache/pacman/pkg
    mount -o $opts,subvol=@log,nodev,nosuid,noexec     /dev/lunar/root /mnt/var/log
    mount -o $opts,subvol=@pkg,nodev,nosuid,noexec     /dev/lunar/root /mnt/var/cache/pacman/pkg

    mkfs.fat -F32 -n LUNARESP /dev/nvme0n1p1
    mount -o umask=0077,nodev,nosuid,noexec /dev/nvme0n1p1 /mnt/efi

6. Base system
--------------
    pacstrap -K /mnt base base-devel linux-hardened linux-lts linux-firmware \
        intel-ucode amd-ucode lvm2 cryptsetup btrfs-progs dosfstools \
        networkmanager nftables apparmor audit usbguard sbctl tpm2-tools \
        plymouth zram-generator sudo zsh vim

    genfstab -U /mnt >> /mnt/etc/fstab

7. Configure
------------
    arch-chroot /mnt
    ln -sf /usr/share/zoneinfo/Europe/Vienna /etc/localtime && hwclock --systohc
    sed -i 's/^#en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen
    echo 'LANG=en_US.UTF-8' > /etc/locale.conf
    echo lunar > /etc/hostname
    useradd -m -G wheel -s /bin/zsh yourname && passwd yourname
    passwd -l root

8. Hardening
------------
Rather than transcribing every sysctl and rule by hand, install the package
that ships them, then let the installer apply the profile to the mounted
system:

    pacman -S lunar-hardening
    lunar-setup --reapply

Read docs/SECURITY.md first. The Onion profile in particular is not what most
people should choose.

9. Boot
-------
The kernel, initramfs, microcode and command line are combined into one signed
unified kernel image. Nothing outside the encrypted container is both unsigned
and load-bearing.

    mkinitcpio -P
    bootctl install --esp-path=/efi
    sbctl create-keys
    sbctl enroll-keys --microsoft        # firmware must be in Setup Mode
    sbctl sign -s /efi/EFI/Linux/lunar-linux-hardened.efi

Then reboot, and re-enable Secure Boot in firmware.
"""


def _meminfo() -> dict:
    out = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            out[key] = int(rest.split()[0]) * 1024
    return out


def _human(n: int) -> str:
    return f"{n / 1024 ** 2:.0f} MiB"


def report_memory() -> None:
    """Print what the system is actually using.

    Published idle figures are usually measured in ways that flatter them.
    This reports the number that matters - total minus available - and the
    largest consumers, so the claim can be checked rather than believed.
    """
    m = _meminfo()
    used = m["MemTotal"] - m["MemAvailable"]

    print("Lunar OS memory report")
    print("=" * 46)
    print(f"  total          {_human(m['MemTotal'])}")
    print(f"  available      {_human(m['MemAvailable'])}")
    print(f"  in use         {_human(used)}   <- the figure that matters")
    print(f"  cached         {_human(m.get('Cached', 0))}")
    if m.get("SwapTotal"):
        swap_used = m["SwapTotal"] - m["SwapFree"]
        print(f"  swap in use    {_human(swap_used)} of {_human(m['SwapTotal'])} (zram)")
    print()

    try:
        ps = subprocess.run(
            ["ps", "-eo", "rss,comm", "--sort=-rss", "--no-headers"],
            capture_output=True, text=True, check=True).stdout.splitlines()[:12]
        print("  largest processes by RSS")
        for line in ps:
            rss, _, comm = line.strip().partition(" ")
            print(f"    {int(rss) // 1024:>6} MiB  {comm.strip()}")
    except Exception:
        pass

    print()
    print("  RSS double-counts shared libraries, so the process column sums to")
    print("  more than 'in use'. Compare the 'in use' figure across systems.")
