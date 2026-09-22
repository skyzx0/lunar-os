"""Install through archinstall rather than by hand.

Lunar's wizard decides *what* to install. archinstall - Arch's own installer,
maintained by Arch developers and run on every official ISO - does the
installing: partitioning, encryption, filesystems, pacstrap, the boot loader,
unified kernel images, user accounts.

This replaced a hand-written installation engine. That engine was correct in
intent and kept failing in practice, one edge case at a time: udev timing,
LVM reactivating a disk mid-install, hidden prompts, systemd-firstboot taking
the console. Every one of those is a problem archinstall solved years ago
against real hardware. Rediscovering them is not a good use of anyone's time.

What stays Lunar's own is everything that makes it Lunar - the branding, the
hardening, the commands, os-release - applied inside the installed system
through archinstall's custom_commands hook, which runs post-install in a
chroot.
"""

import json
import os
import shutil
import subprocess
import tempfile
import uuid

from .profiles import Config

MEDIUM_REPO = "/var/lib/lunar/repo"
ARCHINSTALL_LOG = "/var/log/archinstall/install.log"


# --------------------------------------------------------------------------
# what archinstall should install


# archinstall profile names for each Lunar desktop. "Minimal" installs nothing
# graphical; the Lunar metapackage then brings in the pieces we actually want.
PROFILE_FOR = {
    "plasma":   {"main": "Desktop", "details": ["KDE Plasma"], "greeter": "sddm"},
    "gnome":    {"main": "Desktop", "details": ["GNOME"],      "greeter": "gdm"},
    "hyprland": {"main": "Desktop", "details": ["Hyprland"],   "greeter": "sddm"},
    "sway":     {"main": "Desktop", "details": ["Sway"],       "greeter": "lightdm-gtk-greeter"},
    "i3":       {"main": "Desktop", "details": ["i3-wm"],      "greeter": "lightdm-gtk-greeter"},
    "minimal":  {"main": "Minimal", "details": [],             "greeter": None},
}


def lunar_packages(cfg: Config) -> list:
    """Lunar's own packages, which exist only if the medium carries them."""
    if not os.path.exists(os.path.join(MEDIUM_REPO, "lunar.db.tar.zst")):
        return []
    pkgs = ["lunar-cli", "lunar-hardening", "lunar-branding"]
    if cfg.desktop == "plasma":
        pkgs.append("lunar-look")
    return pkgs


def extra_packages(cfg: Config) -> list:
    """Packages beyond what archinstall's profile brings in."""
    pkgs = ["zsh", "vim", "networkmanager", "nftables", "plymouth",
            "zram-generator", "sudo"]
    p = cfg.profile_obj()
    if p.apparmor:
        pkgs.append("apparmor")
    if p.usbguard:
        pkgs.append("usbguard")
    if p.auditd:
        pkgs.append("audit")
    return pkgs + lunar_packages(cfg) + list(cfg.extra_packages)


# --------------------------------------------------------------------------
# the disk


def _size(unit: str, value) -> dict:
    return {"sector_size": None, "unit": unit, "value": value}


def disk_config(cfg: Config) -> dict:
    """An explicit two-partition layout: an ESP, and the rest for the system.

    Explicit rather than archinstall's interactive defaults, because an
    unattended install must not depend on anything decided at a prompt.
    """
    esp_id, root_id = str(uuid.uuid4()), str(uuid.uuid4())

    fs = "btrfs" if cfg.filesystem == "btrfs" else "ext4"
    root = {
        "btrfs": [],
        "flags": [],
        "fs_type": fs,
        "size": _size("Percent", 100),
        "mount_options": ["compress=zstd"] if fs == "btrfs" else [],
        "mountpoint": None if fs == "btrfs" else "/",
        "obj_id": root_id,
        "start": _size("MiB", 1025),
        "status": "create",
        "type": "primary",
    }
    if fs == "btrfs":
        root["btrfs"] = [
            {"name": "@", "mountpoint": "/"},
            {"name": "@home", "mountpoint": "/home"},
            {"name": "@log", "mountpoint": "/var/log"},
            {"name": "@pkg", "mountpoint": "/var/cache/pacman/pkg"},
            {"name": "@snapshots", "mountpoint": "/.snapshots"},
        ]

    config = {
        "config_type": "default_layout",
        "device_modifications": [{
            "device": cfg.disk,
            "wipe": True,
            "partitions": [
                {
                    "btrfs": [],
                    "flags": ["boot", "esp"],
                    "fs_type": "fat32",
                    "size": _size("MiB", 1024),
                    "mount_options": [],
                    "mountpoint": "/boot",
                    "obj_id": esp_id,
                    "start": _size("MiB", 1),
                    "status": "create",
                    "type": "primary",
                },
                root,
            ],
        }],
    }

    if cfg.encrypt:
        config["disk_encryption"] = {
            "encryption_type": "luks",
            "partitions": [root_id],
        }

    return config


# --------------------------------------------------------------------------
# Lunar's own layer, run inside the installed system


def kernel_hardening(cfg: Config) -> list:
    """Kernel parameters Lunar adds on top of what archinstall sets.

    Deliberately excludes anything that locates or unlocks a disk - root=,
    rd.luks.*, cryptdevice= - because archinstall owns those and gets them
    right for the layout it created.
    """
    p = cfg.profile_obj()
    params = [
        "init_on_alloc=1", "init_on_free=1", "page_alloc.shuffle=1",
        "slab_nomerge", "randomize_kstack_offset=on", "vsyscall=none",
        "debugfs=off", "intel_iommu=on", "amd_iommu=on",
        "efi=disable_early_pci_dma", "spectre_v2=on", "tsx=off",
        "quiet", "splash", "systemd.firstboot=off",
    ]
    if p.apparmor:
        params += ["lsm=landlock,lockdown,yama,integrity,apparmor,bpf"]
    if p.lockdown:
        params.append(f"lockdown={p.lockdown}")
    if p.lockdown == "confidentiality":
        params += ["module.sig_enforce=1", "mitigations=auto,nosmt"]
    else:
        params.append("mitigations=auto")
    return params


def lunar_layer(cfg: Config) -> list:
    """Commands archinstall runs in a chroot once the base system is in.

    Each is independent and tolerant of failure: a missing optional package
    should cost a feature, not the whole installation.
    """
    p = cfg.profile_obj()
    cmds = [
        # Identity. os-release is what every tool reads to name the system.
        "printf 'NAME=\"Lunar OS\"\\nPRETTY_NAME=\"Lunar OS\"\\nID=lunar\\n"
        "ID_LIKE=arch\\nBUILD_ID=rolling\\nANSI_COLOR=\"0;36\"\\n"
        "HOME_URL=\"https://lunaros.org\"\\nLOGO=lunar\\n' > /usr/lib/os-release",

        # Keep a package update from restoring the vendor os-release.
        "grep -q '^NoUpgrade.*os-release' /etc/pacman.conf || "
        "sed -i '/^\\[options\\]/a NoUpgrade = usr/lib/os-release' /etc/pacman.conf",

        # systemd-firstboot takes the console on first boot and asks for
        # things this installer already set. Masked, it cannot appear.
        "systemctl mask systemd-firstboot.service",

        # Services the hardening depends on.
        "systemctl enable nftables.service || true",
        "systemctl enable NetworkManager.service || true",
    ]

    if p.apparmor:
        cmds.append("systemctl enable apparmor.service || true")
    if p.auditd:
        cmds.append("systemctl enable auditd.service || true")
    if p.usbguard:
        cmds.append("systemctl enable usbguard.service || true")

    # The hardening configuration itself - sysctl, the module blacklist, the
    # firewall, PAM limits - ships as files in the lunar-hardening package,
    # so installing that package is what applies it. Nothing here needs to
    # write those files by hand.

    # Kernel hardening parameters are *appended* to the command line
    # archinstall wrote, never substituted for it. archinstall puts the
    # parameters that unlock an encrypted disk and find the root filesystem
    # in that file; replacing it produces a system that cannot boot.
    params = " ".join(kernel_hardening(cfg))
    cmds.append(
        "if [ -f /etc/kernel/cmdline ]; then "
        f"for p in {params}; do "
        "grep -qw \"$p\" /etc/kernel/cmdline || "
        "sed -i \"s|$| $p|\" /etc/kernel/cmdline; "
        "done; mkinitcpio -P || true; fi")

    if cfg.spoof_network:
        cmds.append("systemctl enable lunar-spoof.service || true")

    # Plymouth splash, so boot shows the half moon rather than kernel text.
    cmds.append(
        "plymouth-set-default-theme lunar 2>/dev/null || true")

    return cmds


# --------------------------------------------------------------------------
# building the configuration


def build_config(cfg: Config) -> dict:
    profile = PROFILE_FOR.get(cfg.desktop, PROFILE_FOR["minimal"])
    p = cfg.profile_obj()

    kernels = ["linux-hardened", "linux-lts"] if p.hardened_kernel else ["linux", "linux-lts"]
    if cfg.fast:
        kernels = kernels[:1]

    mirror = {
        "mirror_regions": {},
        "custom_servers": [],
        "optional_repositories": [],
        "custom_repositories": [],
    }
    if lunar_packages(cfg):
        # Lunar's packages, from the medium. TrustAll because an unsigned
        # build has no key to check against; a signed one sets its own level.
        mirror["custom_repositories"].append({
            "name": "lunar",
            "url": f"file://{MEDIUM_REPO}",
            "sign_check": "Optional",
            "sign_option": "TrustAll",
        })

    config = {
        "archinstall-language": "English",
        "audio_config": {"audio": "pipewire"},
        "bootloader_config": {
            "bootloader": "Systemd-boot",
            # Unified kernel images: kernel, initramfs and command line in one
            # signed binary. The whole boot chain Secure Boot can verify.
            "uki": True,
            "removable": False,
        },
        "custom_commands": lunar_layer(cfg),
        "debug": False,
        "disk_config": disk_config(cfg),
        "hostname": cfg.hostname,
        "kernels": kernels,
        "locale_config": {
            "kb_layout": cfg.keymap,
            "sys_enc": "UTF-8",
            "sys_lang": cfg.locale.split(".")[0] if cfg.locale else "en_US",
        },
        "mirror_config": mirror,
        "network_config": {"type": "nm"},
        "no_pkg_lookups": False,
        "ntp": True,
        "offline": False,
        "packages": extra_packages(cfg),
        "pacman_config": {"color": True, "parallel_downloads": 8},
        "profile_config": {
            "gfx_driver": "All open-source (default)",
            "greeter": profile["greeter"],
            "profile": {"main": profile["main"], "details": profile["details"]},
        },
        "script": "guided",
        "silent": True,
        "swap": {"enabled": True, "algorithm": "zstd"},
        "timezone": cfg.timezone,
    }
    return config


def build_credentials(cfg: Config) -> dict:
    """Passwords, kept in a separate file so they never enter the main config.

    Both the current and the previous archinstall formats are written. Each
    version ignores the keys it does not recognise, so one file works across
    the ISO releases a user might boot.
    """
    user = {"username": cfg.username, "sudo": True}
    creds = {
        # archinstall 3.x
        "users": [{**user, "enc_password": cfg.user_password}],
        # archinstall 2.x
        "!users": [{**user, "!password": cfg.user_password}],
    }
    if not cfg.root_locked:
        creds["root_enc_password"] = cfg.user_password
    if cfg.encrypt:
        creds["encryption_password"] = cfg.luks_passphrase
        creds["!encryption-password"] = cfg.luks_passphrase
    return creds


# --------------------------------------------------------------------------
# running it


def archinstall_available() -> bool:
    return shutil.which("archinstall") is not None


def install(cfg: Config, emit) -> None:
    """Install through archinstall, streaming its output to emit()."""
    if not archinstall_available():
        raise RuntimeError(
            "archinstall is not installed on this medium.\n"
            "  It is the installation engine; the medium cannot install\n"
            "  without it.")

    workdir = tempfile.mkdtemp(prefix="lunar-archinstall-")
    config_path = os.path.join(workdir, "user_configuration.json")
    creds_path = os.path.join(workdir, "user_credentials.json")

    with open(config_path, "w") as fh:
        json.dump(build_config(cfg), fh, indent=2)
    # Credentials are readable by root only, and removed afterwards.
    fd = os.open(creds_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(build_credentials(cfg), fh, indent=2)

    emit("Installing with archinstall", accent=True)
    emit(f"  target {cfg.disk}   desktop {cfg.desktop}   profile {cfg.profile}")
    emit(f"  configuration {config_path}")
    emit("")

    cmd = ["archinstall", "--config", config_path, "--creds", creds_path,
           "--silent"]

    # Output streamed, stdin fed from `yes`: the same two properties that the
    # hand-written engine needed and got wrong for weeks. archinstall is
    # non-interactive with --silent, so this is a safety net, not a crutch.
    yes_proc = subprocess.Popen(["yes"], stdout=subprocess.PIPE)
    proc = subprocess.Popen(
        cmd, stdin=yes_proc.stdout,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env={**os.environ, "LC_ALL": "C.UTF-8"})
    yes_proc.stdout.close()

    last = ""
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line and line != last:
                emit("   " + line[:110])
                last = line
    finally:
        proc.stdout.close()
        yes_proc.kill()
        yes_proc.wait()

    rc = proc.wait()

    try:
        os.remove(creds_path)
    except OSError:
        pass

    if rc != 0:
        emit("")
        emit("archinstall reported a failure. Its own log follows.", accent=True)
        try:
            with open(ARCHINSTALL_LOG) as fh:
                for line in fh.read().splitlines()[-40:]:
                    emit("   " + line[:110])
        except OSError:
            emit(f"   ({ARCHINSTALL_LOG} could not be read)")
        raise RuntimeError(
            f"archinstall exited with status {rc}.\n"
            f"  Its full log is at {ARCHINSTALL_LOG}.\n"
            f"  The configuration it was given is at {config_path}.")

    emit("")
    emit("Installation complete.", accent=True)
    emit("Remove the installation medium and reboot.")
