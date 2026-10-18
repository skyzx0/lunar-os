"""Runs the actual installation once the wizard has collected a Config."""

import os
import subprocess
import time

from . import disk, hardening
from .profiles import DESKTOPS

ROOT = "/mnt"

BASE = [
    # base-devel is a build toolchain: several hundred megabytes that a
    # normal install never uses. Install it with ltxs when needed.
    "base", "linux-firmware", "intel-ucode", "amd-ucode",
    "lvm2", "cryptsetup", "btrfs-progs", "e2fsprogs", "dosfstools",
    "networkmanager", "nftables", "systemd-resolvconf",
    "sudo", "zsh", "vim", "git", "man-db", "pacman-contrib", "reflector",
    "zram-generator",
    # lunar-keyring deliberately absent: it only exists in signed builds, and
    # resolve_packages() would drop it anyway. Listing it here made every
    # unsigned install fail on a package that was never built.
    "lunar-hardening", "lunar-setup", "lunar-branding", "lunar-cli",
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
    """Write a mirror list that works on a slow or flaky connection.

    Arch's own geo-routed CDN goes first: it is always in sync and routes to a
    nearby node. After it, mirrors ranked by the Arch mirror-status score -
    only ones synced in the last 12 hours with every package, since a lagging
    mirror answers 404 for files the database says exist. Ranking by score
    downloads nothing here; ranking by measured speed (--sort rate) times out
    on a slow Wi-Fi link and ranks nothing. Continent fallbacks go last, so
    pacman always has somewhere else to try when one server fails a file.

    pacman's own stall timeout is also switched off for the installer: on a
    slow link it aborts a download that is merely slow, which pacstrap
    reports as "failed retrieving file".
    """
    mirrorlist = "/etc/pacman.d/mirrorlist"

    log("Selecting mirrors", accent=True)
    ranked = []
    try:
        r = disk.run(["reflector", "--protocol", "https", "--age", "12",
                      "--completion-percent", "100", "--sort", "score",
                      "--latest", "15", "--connection-timeout", "10"],
                     check=False, timeout=90)
        if r.returncode == 0:
            ranked = [l for l in r.stdout.splitlines() if l.strip().startswith("Server")]
    except (OSError, disk.CommandFailed):
        pass

    with open(mirrorlist, "w") as fh:
        fh.write("# Written by lunaros-setup\n")
        fh.write(f"Server = {FALLBACK_MIRRORS[0]}\n")
        for line in ranked:
            fh.write(line.strip() + "\n")
        for m in FALLBACK_MIRRORS[1:]:
            fh.write(f"Server = {m}\n")
    log(f"  Arch CDN first, then {len(ranked)} ranked mirrors and {len(FALLBACK_MIRRORS) - 1} fallbacks")

    try:
        with open("/etc/pacman.conf") as fh:
            conf = fh.read()
        if "\nDisableDownloadTimeout" not in conf:
            conf = conf.replace("[options]\n", "[options]\nDisableDownloadTimeout\n", 1)
            with open("/etc/pacman.conf", "w") as fh:
                fh.write(conf)
    except OSError:
        pass


ON_MEDIUM_REPO = "/var/lib/lunar/repo"


def medium_repo() -> str:
    """Where the Lunar packages live on the booted medium, if they do.

    The build copies them here so an install does not depend on a repository
    being published anywhere. Returns "" when they are absent, which is the
    normal case on an installed system running --reapply.
    """
    db = os.path.join(ON_MEDIUM_REPO, "lunar.db.tar.zst")
    return ON_MEDIUM_REPO if os.path.exists(db) else ""


def write_pacstrap_conf(path: str = "/tmp/lunar-pacstrap.conf", log=None) -> str:
    """Build the pacman configuration used to populate the target.

    Written fresh rather than reusing the live medium's own file. The medium's
    config points [lunar] at wherever the ISO build happened to keep the
    packages, and inheriting that is how an install ends up looking for a
    directory that only ever existed inside a build container.
    """
    repo = medium_repo()
    siglevel = "Optional TrustAll"
    marker = os.path.join(ON_MEDIUM_REPO, ".siglevel")
    if os.path.exists(marker):
        try:
            with open(marker) as fh:
                siglevel = fh.read().strip() or siglevel
        except OSError:
            pass

    lines = [
        "# Generated by lunaros-setup for this installation only.",
        "[options]",
        "HoldPkg = pacman glibc",
        "Architecture = auto",
        "CheckSpace",
        "ParallelDownloads = 8",
        "SigLevel = Required DatabaseOptional",
        "LocalFileSigLevel = Optional",
        "",
        "[core]",
        "Include = /etc/pacman.d/mirrorlist",
        "",
        "[extra]",
        "Include = /etc/pacman.d/mirrorlist",
        "",
        "[multilib]",
        "Include = /etc/pacman.d/mirrorlist",
        "",
    ]

    if repo:
        lines += [
            "[lunar]",
            f"SigLevel = {siglevel}",
            f"Server = file://{repo}",
            "",
        ]
        if log:
            log(f"  using the repository on the medium ({repo})")
    elif log:
        log("  no Lunar repository on this medium; installing base packages only")

    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


def write_target_pacman_conf(log=None) -> None:
    """The installed system's own configuration.

    It must not inherit the file:// repository: that path belongs to the
    installation medium and disappears the moment you reboot, leaving every
    pacman command failing on a repository it cannot reach.
    """
    hardening.write("/etc/pacman.conf", """
[options]
HoldPkg           = pacman glibc
Architecture      = auto
CheckSpace
ParallelDownloads = 8
Color
SigLevel          = Required DatabaseOptional
LocalFileSigLevel = Optional

# Lunar's own files are protected from being reverted by package updates.
NoUpgrade = usr/lib/os-release

[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist

[multilib]
Include = /etc/pacman.d/mirrorlist

# The Lunar repository. Uncomment once you publish and sign one; until then
# the Lunar packages installed here are the versions from your medium and are
# not updated by 'ltxs -u'.
#[lunar]
#SigLevel = Required DatabaseRequired
#Server = https://repo.lunaros.org/$repo/os/$arch
""", log=log)


# Without these the installed system does not boot, decrypt or reach a
# network. If one of them is unavailable the install must stop; everything
# else is desirable rather than essential.
REQUIRED = {
    "base", "linux-hardened", "linux", "linux-firmware", "systemd",
    "lvm2", "cryptsetup", "networkmanager", "sudo",
}


def resolve_packages(pkgs: list, conf: str, log=None) -> list:
    """Drop packages that do not exist, and stop if an essential one is gone.

    pacstrap is all-or-nothing: one unknown name aborts the transaction and
    leaves an erased disk with nothing on it. Package names move between
    repositories, get renamed, or turn out to have been in the AUR all along,
    and a distribution that fails to install because an optional audit tool
    was reorganised is not one anybody can use.
    """
    subprocess.run(["pacman", "--config", conf, "-Sy"],
                   capture_output=True, text=True)

    available, missing = [], []
    for pkg in pkgs:
        r = subprocess.run(["pacman", "--config", conf, "-Si", pkg],
                           capture_output=True, text=True)
        (available if r.returncode == 0 else missing).append(pkg)

    if missing:
        essential = REQUIRED.intersection(missing)
        if essential:
            raise disk.CommandFailed(
                ["resolve"], 1,
                "Packages the system cannot boot without are unavailable:\n"
                f"  {' '.join(sorted(essential))}\n"
                "  The mirror may be incomplete, or the package set is wrong\n"
                "  for this architecture. Nothing has been installed.")
        if log:
            log(f"  skipping {len(missing)} unavailable: {' '.join(missing)}")

    return available


def set_password(user: str, password: str, log=None) -> None:
    """Set a user's password without putting it on a command line."""
    if log:
        log(f"  setting the password for {user}")
    r = subprocess.run(["arch-chroot", ROOT, "chpasswd"],
                       input=f"{user}:{password}\n",
                       text=True, capture_output=True)
    if r.returncode != 0:
        raise disk.CommandFailed(["chpasswd", user], r.returncode, r.stderr)


DESIRED_GROUPS = ["wheel", "audio", "video", "storage", "optical",
                  "network", "input", "users"]


def create_user(cfg, log=None) -> None:
    """Create the account, joining only groups that actually exist.

    useradd fails the whole command if any named group is missing, and the
    set of groups a base install creates has changed over time. Asking for
    one that no longer exists would abort the install at the very last step,
    after everything has been downloaded and written.
    """
    present = []
    for group in DESIRED_GROUPS:
        r = subprocess.run(["arch-chroot", ROOT, "getent", "group", group],
                           capture_output=True, text=True)
        if r.returncode == 0:
            present.append(group)

    groups = ",".join(present) if present else "wheel"
    if log:
        log(f"  groups: {groups}")

    shell = "/bin/zsh"
    if not os.path.exists(os.path.join(ROOT, "bin/zsh")):
        shell = "/bin/bash"
        if log:
            log("  zsh not installed, using bash as the login shell")

    chroot(f"useradd -m -G {groups} -s {shell} {cfg.username}", log=log)


def run_pacstrap(conf: str, pkgs: list, log=None, timeout: int = 3600) -> int:
    """Install the package set, streaming output into the transcript.

    Two things this gets right that the plain call did not.

    stdin is closed. pacman asks questions - which provider to use, whether to
    replace a package, whether to trust a key - and with stdin inherited from
    a wizard that owns the terminal, the question is never seen and the answer
    never comes. The install simply stops, with no output and no error, which
    is indistinguishable from a slow download.

    Output is streamed rather than left on the terminal, so what pacman said
    ends up in the transcript. Every diagnosis so far has depended on someone
    photographing a screen before it scrolled.
    """
    cmd = ["pacstrap", "-K", "-C", conf, ROOT] + pkgs
    if log:
        log(f"  $ pacstrap -K -C {conf} {ROOT} ({len(pkgs)} packages)")

    # stdin is fed from `yes` rather than closed. Closing it stops the hang
    # but turns any prompt into an abort; feeding it means a question about
    # which provider to use, or whether to replace a package, is answered and
    # the install continues. Both beat waiting forever on a question nobody
    # can see, which is what an inherited terminal produced.
    yes_proc = subprocess.Popen(["yes"], stdout=subprocess.PIPE)

    proc = subprocess.Popen(
        cmd,
        stdin=yes_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "LC_ALL": "C"},
    )
    yes_proc.stdout.close()      # only the child needs the read end

    start = time.time()
    last = ""
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            # Download progress redraws the same line hundreds of times; keep
            # the transcript readable by dropping consecutive duplicates.
            if line == last:
                continue
            last = line
            if log:
                log("   " + line[:100])
            if time.time() - start > timeout:
                proc.kill()
                if log:
                    log(f"  pacstrap exceeded {timeout}s and was stopped")
                return 124
    finally:
        proc.stdout.close()
        yes_proc.kill()
        yes_proc.wait()

    return proc.wait()


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
    conf = write_pacstrap_conf(log=log)
    pkgs = resolve_packages(package_set(cfg), conf, log=log)
    log(f"  {len(pkgs)} packages")

    rc = run_pacstrap(conf, pkgs, log=log)
    if rc != 0:
        raise disk.CommandFailed(
            ["pacstrap", ROOT], rc,
            "Package installation failed.\n"
            "  The transcript above shows which package or mirror was the\n"
            f"  problem. The configuration used is at {conf}.")

    log("Configuring package management", accent=True)
    write_target_pacman_conf(log=log)

    log("Generating fstab", accent=True)
    with open(f"{ROOT}/etc/fstab", "a") as fh:
        fh.write(subprocess.run(["genfstab", "-U", ROOT],
                                capture_output=True, text=True, check=True).stdout)
    # tmpfs with noexec for /tmp and a real size cap
    with open(f"{ROOT}/etc/fstab", "a") as fh:
        fh.write("tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,size=2G,mode=1777 0 0\n")
        # No /proc entry: systemd mounts it before fstab is read, and an
        # entry here that the kernel or systemd disagrees with drops the
        # machine into emergency mode at boot. Process hiding is applied per
        # service with ProtectProc instead, which cannot break booting.
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

    # systemd decides a system has "never booted" when /etc/machine-id is
    # absent, and then systemd-firstboot takes the console and asks for a
    # timezone, locale and root password before anything else can run. The
    # installer has already been told all of that, so answer it here and
    # generate the machine id; then mask the unit so it cannot appear later.
    chroot(f"systemd-firstboot --locale='{cfg.locale}' "
           f"--keymap='{cfg.keymap}' --timezone='{cfg.timezone}' "
           f"--hostname='{cfg.hostname}' --setup-machine-id",
           check=False, log=log)
    chroot("systemctl mask systemd-firstboot.service", check=False, log=log)

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
    create_user(cfg, log=log)
    # Passed on stdin, never interpolated into a shell command: a password
    # containing a quote or a backtick would otherwise break the command or
    # have part of itself executed, and would be visible in the process list.
    set_password(cfg.username, cfg.user_password, log=log)
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
    # mkinitcpio writes the unified kernel image straight into the ESP, and
    # bootctl - which creates that directory - has not run yet. Without this
    # the image generation fails on a missing path.
    chroot("mkdir -p /efi/EFI/Linux /efi/EFI/BOOT", log=log)
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
    if medium_repo() and os.path.exists(
            os.path.join(ROOT, "usr/share/pacman/keyrings/lunar.gpg")):
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
