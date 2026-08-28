"""Runs the actual installation once the wizard has collected a Config."""

import os
import subprocess

from . import disk, hardening
from .profiles import DESKTOPS

ROOT = "/mnt"

BASE = [
    "base", "base-devel", "linux-firmware", "intel-ucode", "amd-ucode",
    "lvm2", "cryptsetup", "btrfs-progs", "e2fsprogs", "dosfstools",
    "networkmanager", "nftables", "systemd-resolvconf",
    "sudo", "zsh", "vim", "git", "man-db", "pacman-contrib", "reflector",
    "zram-generator",
    "lunar-keyring", "lunar-hardening", "lunar-setup", "lunar-branding",
    "lunar-cli",
    "plymouth",
]

SECURITY = [
    "apparmor", "audit", "usbguard", "firejail",
    "bubblewrap", "flatpak", "arch-audit", "sbctl", "tpm2-tools",
    "tpm2-tss", "rkhunter", "lynis", "chrony", "tor",
    "torsocks", "macchanger", "polkit",
]

# In the AUR, so pacstrap cannot install them. Left to the user post-install
# with an AUR helper; the hardening code degrades gracefully when they are
# absent rather than leaving a system that will not boot.
AUR_SUGGESTED = ["hardened_malloc", "opensnitch"]


def chroot(cmd, log=None, check=True):
    return hardening.chroot(cmd, log=log, check=check)


def run(cmd, log=None, check=True, input_=None):
    return disk.run(cmd, check=check, input_=input_, log=log)


def kernel_packages(profile) -> list:
    if profile.hardened_kernel:
        # linux-lts is the fallback: linux-hardened has broken on new laptops
        # more than once, and an unbootable machine is not a secure machine.
        return ["linux-hardened", "linux-hardened-headers", "linux-lts"]
    return ["linux", "linux-headers", "linux-lts"]


# The smallest set that boots, decrypts, reaches the network and can install
# anything else. Everything beyond this is a choice the user can make later
# with ltxs, which is the point: a fast install is a small install.
FAST_BASE = [
    "base", "linux-hardened", "linux-firmware", "intel-ucode", "amd-ucode",
    "lvm2", "cryptsetup", "btrfs-progs", "dosfstools",
    "networkmanager", "nftables", "sudo", "zsh", "vim",
    "lunar-cli", "lunar-hardening",
]


def package_set(cfg) -> list:
    if getattr(cfg, "fast", False):
        pkgs = list(FAST_BASE)
        p = cfg.profile_obj()
        if p.apparmor:
            pkgs.append("apparmor")
        return sorted(set(pkgs))
    return _full_package_set(cfg)


def _full_package_set(cfg) -> list:
    p = cfg.profile_obj()
    pkgs = list(BASE) + kernel_packages(p) + list(SECURITY)
    pkgs.append(cfg.desktop_obj().meta)
    if dm := cfg.desktop_obj().dm:
        pkgs.append(dm)
    pkgs += cfg.extra_packages
    return sorted(set(pkgs))


# Official geo-routed mirror first, then per-continent fallbacks. Used when
# mirror ranking fails or produces nothing: an empty mirrorlist makes pacstrap
# fail with "no servers configured for repository", which names the symptom
# and not the cause.
FALLBACK_MIRRORS = [
    "https://geo.mirror.pkgbuild.com/$repo/os/$arch",
    "https://europe.mirror.pkgbuild.com/$repo/os/$arch",
    "https://america.mirror.pkgbuild.com/$repo/os/$arch",
    "https://asia.mirror.pkgbuild.com/$repo/os/$arch",
]


def have_network(timeout: float = 5.0) -> bool:
    """Can we actually reach a mirror?

    A default route proves nothing: captive portals, DNS failures and blocked
    outbound 443 all look like a working connection right up until a download
    fails partway through an install.
    """
    import socket
    for host in ("geo.mirror.pkgbuild.com", "archlinux.org"):
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def require_network(log=None) -> None:
    if have_network():
        return
    raise disk.CommandFailed(
        ["network"], 1,
        "No connection to the package mirrors.\n"
        "  Nothing can be installed without one.\n"
        "\n"
        "  Connect, then run lunaros-setup again:\n"
        "    Wi-Fi      nmtui\n"
        "               or: iwctl, then station wlan0 connect YOUR-NETWORK\n"
        "    Wired      should be automatic; check the cable\n"
        "    Verify     ping -c1 archlinux.org\n"
        "\n"
        "  Reach a shell with Ctrl+Alt+F2.")


def ensure_mirrors(log=None) -> None:
    """Rank mirrors, and guarantee the list is not empty afterwards.

    reflector needs the internet to rank mirrors. When it cannot reach the
    mirror status service it exits without writing, leaving whatever was
    there - which on a fresh medium is a file with every server commented out.
    """
    mirrorlist = "/etc/pacman.d/mirrorlist"

    log("Selecting mirrors", accent=True)
    r = run(["reflector", "--protocol", "https", "--latest", "20",
             "--sort", "rate", "--save", mirrorlist],
            check=False, log=log)

    active = []
    try:
        with open(mirrorlist) as fh:
            active = [l for l in fh if l.strip().startswith("Server")]
    except OSError:
        pass

    if r.returncode != 0 or not active:
        log("  ranking unavailable, using the built-in mirror list")
        with open(mirrorlist, "w") as fh:
            fh.write("# Written by lunaros-setup: mirror ranking was unavailable.\n")
            for m in FALLBACK_MIRRORS:
                fh.write(f"Server = {m}\n")
    else:
        log(f"  {len(active)} mirrors ranked")


def install(cfg, emit) -> None:
    log = emit
    p = cfg.profile_obj()

    # Checked before anything destructive. Finding out there is no network
    # after the disk has been erased leaves a machine that neither boots its
    # old system nor has a new one.
    log("Checking the connection", accent=True)
    require_network(log=log)
    log("  mirrors reachable")

    # ---- disk ----------------------------------------------------------
    log("Partitioning", accent=True)
    esp, luks_part = disk.partition(cfg.disk, log=log)

    if cfg.wipe_disk:
        log("Overwriting the data partition with random bytes", accent=True)
        log("  This can take hours on a large spinning disk.")
        disk.secure_erase(luks_part, log=log)

    if cfg.encrypt:
        log("Creating the LUKS2 container (argon2id, 1 GiB memory cost)", accent=True)
        disk.luks_format(luks_part, cfg.luks_passphrase, log=log)
        disk.make_volumes(cfg.filesystem, log=log)
        uuid = disk.luks_uuid(luks_part)
    else:
        log("Creating volumes without encryption", accent=True)
        log("  Anyone with physical access can read this disk.")
        disk.make_volumes(cfg.filesystem, log=log, target=luks_part)
        uuid = ""
    disk.mount_esp(esp, log=log)
    # Our own volumes are up now; let LVM manage devices normally again.
    disk.resume_autoactivation(log=log)

    # ---- base system ---------------------------------------------------
    ensure_mirrors(log=log)

    log("Installing packages", accent=True)
    pkgs = package_set(cfg)
    log(f"  {len(pkgs)} packages")
    subprocess.run(["pacstrap", "-K", ROOT] + pkgs, check=True)

    log("Generating fstab", accent=True)
    with open(f"{ROOT}/etc/fstab", "a") as fh:
        fh.write(subprocess.run(["genfstab", "-U", ROOT],
                                capture_output=True, text=True, check=True).stdout)
    # tmpfs with noexec for /tmp and a real size cap
    with open(f"{ROOT}/etc/fstab", "a") as fh:
        fh.write("tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,size=2G,mode=1777 0 0\n")
        fh.write("proc /proc proc nosuid,nodev,noexec,hidepid=2,gid=proc 0 0\n")
        # /dev/shm is world-writable and a standard place to stage a payload.
        fh.write("tmpfs /dev/shm tmpfs rw,nosuid,nodev,noexec 0 0\n")

    # ---- locale, time, identity ----------------------------------------
    log("Configuring the system", accent=True)
    chroot(f"ln -sf /usr/share/zoneinfo/{cfg.timezone} /etc/localtime && hwclock --systohc",
           log=log)
    chroot(f"sed -i 's/^#\\s*{cfg.locale}/{cfg.locale}/' /etc/locale.gen && locale-gen", log=log)
    hardening.write("/etc/locale.conf", f"LANG={cfg.locale}\n", log=log)
    hardening.write("/etc/vconsole.conf", f"KEYMAP={cfg.keymap}\n", log=log)
    hardening.write("/etc/hostname", cfg.hostname + "\n", log=log)

    # Brand the installed system. os-release is what neofetch, GRUB, systemd,
    # bug trackers and half the desktop read to name the distribution; leaving
    # it saying "Arch Linux" would be the single most visible wrong thing.
    # It lives in /usr/lib and is symlinked from /etc, and the arch package
    # owns it, so the file is replaced and pacman is told to leave it alone.
    hardening.write("/usr/lib/os-release", """
NAME="Lunar OS"
PRETTY_NAME="Lunar OS"
ID=lunar
ID_LIKE=arch
BUILD_ID=rolling
ANSI_COLOR="0;36"
HOME_URL="https://lunaros.org"
DOCUMENTATION_URL="https://lunaros.org/docs"
SUPPORT_URL="https://lunaros.org/support"
BUG_REPORT_URL="https://lunaros.org/bugs"
LOGO=lunar
""", log=log)
    hardening.write("/etc/lsb-release", """
LSB_VERSION=1.4
DISTRIB_ID=LunarOS
DISTRIB_RELEASE=rolling
DISTRIB_DESCRIPTION="Lunar OS"
""", log=log)
    hardening.write("/etc/issue", "\nLunar OS \\r (\\l)\n\n", log=log)

    # pacman would restore Arch's os-release on the next filesystem update.
    chroot("grep -q '^NoUpgrade.*os-release' /etc/pacman.conf || "
           "sed -i 's|^#NoUpgrade.*|NoUpgrade = usr/lib/os-release|' /etc/pacman.conf",
           check=False, log=log)
    hardening.write("/etc/hosts", f"""
127.0.0.1   localhost
::1         localhost
127.0.1.1   {cfg.hostname}.localdomain {cfg.hostname}
""", log=log)

    # ---- users ---------------------------------------------------------
    chroot(f"useradd -m -G wheel,audio,video,storage -s /bin/zsh {cfg.username}", log=log)
    chroot(f"chpasswd <<< '{cfg.username}:{cfg.user_password}'", log=log)
    if cfg.root_locked:
        chroot("passwd -l root", log=log)
    hardening.write("/etc/sudoers.d/10-lunar", """
%wheel ALL=(ALL:ALL) ALL
Defaults passwd_timeout=1
Defaults timestamp_timeout=5
Defaults lecture=never
Defaults use_pty
Defaults logfile=/var/log/sudo.log
Defaults !targetpw
""", mode=0o440, log=log)

    # ---- hardening -----------------------------------------------------
    log("Applying the " + p.name + " profile", accent=True)
    hardening.apply(cfg, uuid, log=log)

    # ---- network privacy toggles ---------------------------------------
    if cfg.spoof_network:
        log("Enabling network spoofing at boot", accent=True)
        # A boot-time oneshot rather than baked config, so it can be turned
        # off later with 'lunar-privacy spoof off' without editing files.
        hardening.write("/etc/systemd/system/lunar-spoof.service", """
[Unit]
Description=Lunar network spoofing
Before=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/bin/lunar-privacy spoof on
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
""", log=log)
        chroot("systemctl enable lunar-spoof.service", check=False, log=log)

    if cfg.cover_traffic:
        log("Enabling cover traffic", accent=True)
        chroot("lunar-privacy cover on --rate low", check=False, log=log)

    # ---- initramfs + unified kernel image -------------------------------
    log("Building the unified kernel image", accent=True)
    hardening.write("/etc/mkinitcpio.conf.d/lunar.conf", """
# plymouth-encrypt belongs to the busybox 'encrypt' hook and conflicts with
# sd-encrypt. With a systemd initramfs, systemd-ask-password renders the
# passphrase prompt through plymouth on its own.
HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard
       sd-vconsole block sd-encrypt lvm2 filesystems fsck)
COMPRESSION="zstd"
COMPRESSION_OPTIONS=(-19)
""", log=log)

    hardening.write("/etc/plymouth/plymouthd.conf", """
[Daemon]
Theme=lunar
ShowDelay=0
DeviceTimeout=8
""", log=log)

    kernel = "linux-hardened" if p.hardened_kernel else "linux"
    for k in (kernel, "linux-lts"):
        hardening.write(f"/etc/mkinitcpio.d/{k}.preset", f"""
ALL_kver="/boot/vmlinuz-{k}"
PRESETS=('default')
default_uki="/efi/EFI/Linux/lunar-{k}.efi"
# No vendor splash bitmap: the boot splash is Plymouth's.
default_options=""
""", log=log)
    chroot("mkinitcpio -P", log=log)

    # ---- boot ----------------------------------------------------------
    log("Installing the boot loader", accent=True)
    chroot("bootctl install --esp-path=/efi", log=log)
    hardening.write("/efi/loader/loader.conf", """
default lunar-linux-hardened.efi
timeout 0
console-mode keep
editor no
""", log=log)

    if p.secure_boot:
        log("Enrolling Secure Boot keys", accent=True)
        log("  Firmware must already be in Setup Mode for this to succeed.")
        r = chroot("sbctl create-keys && sbctl enroll-keys --microsoft", check=False, log=log)
        if r.returncode != 0:
            log("  Key enrolment failed. Run 'sbctl enroll-keys' after clearing")
            log("  the platform key in firmware. The system still boots.")
        else:
            chroot("sbctl sign -s /efi/EFI/Linux/lunar-linux-hardened.efi "
                   "&& sbctl sign -s /efi/EFI/BOOT/BOOTX64.EFI "
                   "&& sbctl sign -s /efi/EFI/systemd/systemd-bootx64.efi",
                   check=False, log=log)

    if p.tpm2_unlock:
        log("Sealing the LUKS key to the TPM (PCRs 0,2,4,7)", accent=True)
        r = subprocess.run(
            ["systemd-cryptenroll", "--tpm2-device=auto",
             "--tpm2-pcrs=0+2+4+7", "--tpm2-with-pin=yes", luks_part],
            input=cfg.luks_passphrase, text=True, capture_output=True)
        if r.returncode != 0:
            log("  No usable TPM2 found. Passphrase unlock stays as the only method.")

    # ---- display manager and appearance ---------------------------------
    d = cfg.desktop_obj()
    if d.dm:
        chroot(f"systemctl enable {d.dm}", check=False, log=log)

    # greetd drives the tiling sessions, which have no display manager of
    # their own. Point tuigreet at the chosen session's launch command.
    if d.dm == "greetd":
        session_cmd = {"hyprland": "Hyprland", "sway": "sway",
                       "i3": "i3"}.get(d.key, d.session)
        greetd = (
            "[terminal]\n"
            "vt = 1\n\n"
            "[default_session]\n"
            'command = "tuigreet --time --remember --remember-session '
            '--asterisks --cmd ' + session_cmd + '"\n'
            "user = \"greeter\"\n"
        )
        hardening.write("/etc/greetd/config.toml", greetd, log=log)
        chroot("useradd -M -G video -s /usr/bin/nologin greeter 2>/dev/null; "
               "install -d -o greeter -g greeter /var/lib/greetd",
               check=False, log=log)

    if d.dm == "sddm":
        hardening.write("/etc/sddm.conf.d/lunar.conf", """
[Theme]
Current=lunar
CursorTheme=breeze_cursors

[General]
DisplayServer=wayland
""", log=log)

    if d.key == "plasma":
        # Plasma reads this once, when a session first starts without an
        # existing configuration. Copied per-user rather than enforced, so
        # anything the user changes afterwards stays changed.
        chroot(f"install -Dm644 -o {cfg.username} -g {cfg.username} "
               "/usr/share/lunar/layout/org.lunaros.desktop.js "
               f"/home/{cfg.username}/.config/plasma-org.kde.plasma.desktop-layout.js",
               check=False, log=log)

    # ---- repo -----------------------------------------------------------
    chroot("pacman-key --populate lunar", check=False, log=log)
    chroot("systemctl enable lunar-updates.timer", check=False, log=log)

    log("")
    log("Optional, from the AUR after first boot:", accent=True)
    log("  " + " ".join(AUR_SUGGESTED))
    log("")
    log("Installation complete.", accent=True)
    log("Remove the installation medium and reboot.")
    if p.secure_boot:
        log("On first boot, re-enable Secure Boot in firmware.")


def unmount(log=None) -> None:
    subprocess.run(["swapoff", "-a"], check=False)
    subprocess.run(["umount", "-R", ROOT], check=False)
    subprocess.run(["cryptsetup", "close", disk.MAPPER], check=False)
