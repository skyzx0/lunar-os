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
import re
import shutil
import subprocess
import tempfile
import uuid

from .locales import x11_for
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
    if "plasma" in cfg.all_desktops():
        pkgs.append("lunar-look")
    return pkgs


# archinstall's desktop profiles install the bare minimum: Plasma gets only
# plasma-desktop (no network applet, no battery or power management, no
# volume control, no Bluetooth), i3 gets xterm, and none of the tiling
# desktops get a way to pick a Wi-Fi network. These fill that in.

# Every graphical desktop.
DESKTOP_COMMON = [
    "firefox",
    "noto-fonts", "noto-fonts-emoji", "ttf-dejavu",
    "xdg-user-dirs",
    "power-profiles-daemon", "upower",   # battery, power-saver mode
    "bluez", "bluez-utils",
    "python", "python-gobject", "gtk4", "libadwaita",   # Lunar Look
]

# Per desktop, on top of the above and archinstall's own selection.
DESKTOP_EXTRAS = {
    # plasma-meta is the full Plasma: network applet (plasma-nm), battery
    # and power (powerdevil), volume (plasma-pa), Bluetooth (bluedevil),
    # display settings (kscreen), themes for GTK apps. Then the usual apps.
    "plasma": ["plasma-meta", "kvantum", "konsole", "dolphin", "kate", "ark",
               "spectacle", "gwenview", "okular", "kcalc", "filelight"],
    # The gnome group is already complete; power profiles come from above.
    "gnome": [],
    "hyprland": ["waybar", "hyprlock", "hypridle", "network-manager-applet",
                 "blueman", "pavucontrol", "brightnessctl", "swaybg", "btop", "cava",
                 "git", "base-devel"],                  # lunar-ii builds illogical-impulse
    "sway": ["network-manager-applet", "blueman", "thunar", "wofi", "swayidle", "swaylock"],
    "i3": ["alacritty", "network-manager-applet", "blueman", "pavucontrol",
           "brightnessctl", "thunar", "picom", "feh"],
    "minimal": [],
}


def graphical(cfg: Config) -> bool:
    return any(d != "minimal" for d in cfg.all_desktops())


def greeter_for(cfg: Config):
    """One login screen for all selected desktops. SDDM and GDM both list
    every installed session; SDDM is preferred when Plasma or Hyprland is
    among them, GDM when GNOME is, LightDM otherwise."""
    chosen = cfg.all_desktops()
    if not graphical(cfg):
        return None
    if "plasma" in chosen or "hyprland" in chosen:
        return "sddm"
    if "gnome" in chosen:
        return "gdm"
    return "lightdm-gtk-greeter"


def desktop_packages(desktop: str) -> list:
    if desktop not in DESKTOP_EXTRAS or desktop == "minimal":
        return []
    return DESKTOP_COMMON + DESKTOP_EXTRAS[desktop]


def available_packages(pkgs: list, emit=None) -> list:
    """Drop package names the repositories do not have.

    One unknown name makes pacman refuse the whole transaction, which would
    fail the install at the package step. Better to install everything else
    and say what was skipped. Runs on the live medium, which has pacman; if
    the check itself cannot run, the list is used unchanged.
    """
    if subprocess.run(["pacman", "-Sy", "--noconfirm"],
                      capture_output=True).returncode != 0:
        return pkgs
    keep, skipped = [], []
    for name in pkgs:
        ok = subprocess.run(["pacman", "-Si", name], capture_output=True).returncode == 0
        (keep if ok else skipped).append(name)
    if skipped and emit:
        emit(f"  skipping packages the repositories do not have: {' '.join(skipped)}")
    return keep


def extra_packages(cfg: Config) -> list:
    """Packages beyond what archinstall's profile brings in."""
    pkgs = ["zsh", "vim", "networkmanager", "nftables", "plymouth",
            "zram-generator", "sudo", "fastfetch"]
    p = cfg.profile_obj()
    if p.apparmor:
        pkgs.append("apparmor")
    if p.usbguard:
        pkgs.append("usbguard")
    if p.auditd:
        pkgs.append("audit")
    return list(dict.fromkeys(pkgs + [p for d in cfg.all_desktops() for p in desktop_packages(d)] + lunar_packages(cfg)
                              + list(cfg.extra_packages)))


# --------------------------------------------------------------------------
# the disk


MIB = 1024 * 1024
ESP_MIB = 1024
FIRST_MIB = 1                  # archinstall rejects a first partition before 1 MiB
GPT_BACKUP_MIB = 1             # the backup GPT header lives in the last MiB


def _size(mib: int) -> dict:
    """A size in whole MiB.

    archinstall 4 requires sector_size as an object rather than null, has no
    percentage unit, and rejects anything not aligned. Whole MiB satisfies all
    three. The published example configs show null sector sizes and
    percentages; both predate the current parser.
    """
    return {"sector_size": {"value": 512, "unit": "B"},
            "unit": "MiB", "value": int(mib)}


def disk_bytes(device: str) -> int:
    """The size of the target disk, read from the kernel."""
    for cmd in (["blockdev", "--getsize64", device],
                ["lsblk", "-bdno", "SIZE", device]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 check=True).stdout.strip()
            if out:
                return int(out.split()[0])
        except (OSError, subprocess.CalledProcessError, ValueError):
            continue
    raise RuntimeError(f"cannot read the size of {device}")


def disk_config(cfg: Config, size_bytes: int = None) -> dict:
    """An explicit two-partition layout: an ESP, and the rest for the system.

    Sizes are computed from the real disk rather than expressed as "the
    rest", because archinstall validates that the final partition ends before
    the backup GPT header and there is no percentage unit to lean on.
    """
    if size_bytes is None:
        size_bytes = disk_bytes(cfg.disk)

    total_mib = size_bytes // MIB
    root_start = FIRST_MIB + ESP_MIB
    root_mib = total_mib - root_start - GPT_BACKUP_MIB
    if root_mib < 8 * 1024:
        raise RuntimeError(
            f"{cfg.disk} is {total_mib // 1024} GiB; Lunar OS needs at least "
            f"{(root_start + 8 * 1024) // 1024 + 1} GiB.")

    esp_id, root_id = str(uuid.uuid4()), str(uuid.uuid4())
    fs = "btrfs" if cfg.filesystem == "btrfs" else "ext4"

    root = {
        "btrfs": [],
        "dev_path": None,
        "flags": [],
        "fs_type": fs,
        "mount_options": ["compress=zstd"] if fs == "btrfs" else [],
        "mountpoint": None if fs == "btrfs" else "/",
        "obj_id": root_id,
        "size": _size(root_mib),
        "start": _size(root_start),
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
        "config_type": "manual_partitioning",
        "device_modifications": [{
            "device": cfg.disk,
            "wipe": True,
            "partitions": [
                {
                    "btrfs": [],
                    "dev_path": None,
                    "flags": ["boot", "esp"],
                    "fs_type": "fat32",
                    "mount_options": [],
                    "mountpoint": "/boot",
                    "obj_id": esp_id,
                    "size": _size(ESP_MIB),
                    "start": _size(FIRST_MIB),
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


ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


_ARCHINSTALL_WORD = re.compile(r"(?<![/\w.-])Archinstall(?![/\w.-])")


def rebrand(line: str) -> str:
    """Lunar's names in archinstall's progress lines.

    Only product names change. Paths (/var/log/archinstall/...) and package
    names (archlinux-keyring) stay exact, so anything the user might need to
    look up or type still matches the real thing. The failure log shown on
    error is left unfiltered on purpose.
    """
    line = line.replace("Arch Linux", "Lunar OS")
    return _ARCHINSTALL_WORD.sub("lunaros-setup", line)


def write_asset_cmd(name: str, dest: str, mode: str = "644") -> str:
    """A command that writes one of the bundled files into the target.

    archinstall runs these inside the installed system, which cannot see the
    install medium, so the file travels inside the command itself. base64
    keeps any quotes or $ in the file from being read by the shell.
    """
    with open(os.path.join(ASSETS, name), "rb") as fh:
        return write_bytes_cmd(fh.read(), dest, mode)


def write_bytes_cmd(data: bytes, dest: str, mode: str = "644") -> str:
    import base64
    blob = base64.b64encode(data).decode()
    return (f"mkdir -p {os.path.dirname(dest)} && "
            f"printf '%s' '{blob}' | base64 -d > {dest} && chmod {mode} {dest}")


def render_asset(name: str, cfg: Config) -> bytes:
    """A bundled config with the chosen keyboard layout filled in.

    Most layouts have no variant; an empty variant is an error in Sway (and
    pointless elsewhere), so the whole variant line is dropped then.
    """
    with open(os.path.join(ASSETS, name)) as fh:
        text = fh.read()
    layout, variant = x11_for(cfg.keymap)
    text = text.replace("@XKB_LAYOUT@", layout)
    if variant:
        text = text.replace("@XKB_VARIANT@", variant)
    else:
        text = "".join(l for l in text.splitlines(True) if "@XKB_VARIANT@" not in l)
    return text.encode()


def user_files_cmds(cfg: Config, files: list) -> list:
    """Per-user config files: into /etc/skel for future users, and straight
    into the new user's home, because archinstall creates that user before
    these commands run, so skel alone would never reach them."""
    cmds = [write_bytes_cmd(render_asset(asset, cfg), f"/etc/skel/{rel}")
            for asset, rel in files]
    if cfg.username:
        home = f"/home/{cfg.username}"
        for _, rel in files:
            cmds.append(f"install -Dm644 /etc/skel/{rel} {home}/{rel}")
        cmds.append(f"chown -R {cfg.username}: {home}/.config")
    return cmds


# Each tiling desktop's own configs: (bundled file, path in the home folder).
_GTK_DARK = [("desktops/common/gtk-settings.ini", ".config/gtk-3.0/settings.ini"),
             ("desktops/common/gtk-settings.ini", ".config/gtk-4.0/settings.ini")]
DESKTOP_USER_FILES = {
    "hyprland": [
        ("desktops/hyprland/hyprland.conf", ".config/hypr/hyprland.conf"),
        ("desktops/hyprland/hyprlock.conf", ".config/hypr/hyprlock.conf"),
        ("desktops/hyprland/hypridle.conf", ".config/hypr/hypridle.conf"),
        ("desktops/hyprland/kitty.conf", ".config/kitty/kitty.conf"),
        ("desktops/hyprland/btop/btop.conf", ".config/btop/btop.conf"),
        ("desktops/hyprland/btop/lunar.theme", ".config/btop/themes/lunar.theme"),
        ("desktops/hyprland/cava.conf", ".config/cava/config"),
        ("desktops/hyprland/dunstrc", ".config/dunst/dunstrc"),
        ("desktops/hyprland/wofi/config", ".config/wofi/config"),
        ("desktops/waybar/config-hyprland.json", ".config/waybar/hyprland.json"),
        ("desktops/waybar/style.css", ".config/waybar/style.css"),
    ] + _GTK_DARK,
    "sway": [
        ("desktops/sway/config", ".config/sway/config"),
        ("desktops/sway/foot.ini", ".config/foot/foot.ini"),
        ("desktops/hyprland/wofi/config", ".config/wofi/config"),
        ("desktops/waybar/config-sway.json", ".config/waybar/sway.json"),
        ("desktops/waybar/style.css", ".config/waybar/style.css"),
    ] + _GTK_DARK,
    "i3": [
        ("desktops/i3/config", ".config/i3/config"),
        ("desktops/i3/i3status.conf", ".config/i3status/config"),
        ("desktops/i3/alacritty.toml", ".config/alacritty/alacritty.toml"),
    ] + _GTK_DARK,
}


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
        # Identity: the OS name every tool reads, the login banner, and the
        # package command. Shared with the live ISO (lunar_setup/assets).
        write_asset_cmd("os-release", "/usr/lib/os-release"),
        write_asset_cmd("issue", "/etc/issue"),
        write_asset_cmd("ltxs", "/usr/local/bin/ltxs", "755"),

        # Keep a package update from restoring the vendor os-release.
        "grep -q '^NoUpgrade.*os-release' /etc/pacman.conf || "
        "sed -i '/^\\[options\\]/a NoUpgrade = usr/lib/os-release' /etc/pacman.conf",

        # systemd-firstboot takes the console on first boot and asks for
        # things this installer already set. Masked, it cannot appear.
        "systemctl mask systemd-firstboot.service",

        # Services the hardening depends on.
        "systemctl enable NetworkManager.service || true",
    ]


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
        "done; fi")

    if cfg.spoof_network:
        cmds.append("systemctl enable lunar-spoof.service || true")

    # The X11 side of the keyboard layout. archinstall's own installer can
    # propagate this live via a temporary systemd-nspawn boot of the target,
    # but that needs a real container-boot stack this build environment does
    # not have, and - unlike everything else in this list - degrades badly
    # rather than gracefully: it produces gigabytes of boot console output
    # before failing. The console side is unaffected either way; archinstall
    # writes /etc/vconsole.conf directly, unconditionally, before that step
    # ever runs.
    # X11 names its layouts differently from the console (uk -> gb), and has
    # separate variants (de nodeadkeys); the keymap table maps between them.
    xkb_layout, xkb_variant = x11_for(cfg.keymap)
    variant_line = (f"        Option \"XkbVariant\" \"{xkb_variant}\"\n"
                    if xkb_variant else "")
    cmds.append(
        "mkdir -p /etc/X11/xorg.conf.d && "
        f"printf 'Section \"InputClass\"\n"
        f"        Identifier \"keyboard\"\n"
        f"        MatchIsKeyboard \"on\"\n"
        f"        Option \"XkbLayout\" \"{xkb_layout}\"\n"
        f"{variant_line}"
        f"        Option \"AutoRepeat\" \"250 50\"\n"
        f"EndSection\n' > /etc/X11/xorg.conf.d/00-keyboard.conf")

    # fastfetch with the half moon, system-wide (a user's own
    # ~/.config/fastfetch/config.jsonc still takes precedence); neofetch,
    # which Arch no longer carries, runs it too.
    cmds += [
        write_asset_cmd("fetch/logo.txt", "/usr/share/lunaros/fetch-logo.txt"),
        write_asset_cmd("fetch/config.jsonc", "/etc/xdg/fastfetch/config.jsonc"),
        write_asset_cmd("fetch/neofetch", "/usr/local/bin/neofetch", "755"),
    ]

    # Power profiles and Bluetooth on any graphical desktop. Tolerant of a
    # missing unit: a package skipped above should cost that feature only.
    if graphical(cfg):
        cmds.append("systemctl enable power-profiles-daemon.service bluetooth.service || true")

    # Every install: pacman goes through ltxs in a terminal, and the Lunar
    # icon that os-release names (LOGO=lunar) exists, so "About this
    # system" screens show the moon.
    cmds += [
        write_asset_cmd("shell/lunar-shell.sh", "/etc/lunaros/shell.sh"),
        "grep -q /etc/lunaros/shell.sh /etc/bash.bashrc 2>/dev/null || "
        "echo '[ -r /etc/lunaros/shell.sh ] && . /etc/lunaros/shell.sh' >> /etc/bash.bashrc",
        "mkdir -p /etc/zsh && (grep -q /etc/lunaros/shell.sh /etc/zsh/zshrc 2>/dev/null || "
        "echo '[ -r /etc/lunaros/shell.sh ] && . /etc/lunaros/shell.sh' >> /etc/zsh/zshrc)",
        write_asset_cmd("plasma/lunar-logo.svg", "/usr/share/icons/hicolor/scalable/apps/lunar.svg"),
        write_asset_cmd("plasma/lunar-logo.svg", "/usr/share/pixmaps/lunar.svg"),
    ]

    # The moon wallpaper, for every graphical desktop.
    if graphical(cfg):
        cmds.append(write_asset_cmd("plasma/lunar-wallpaper.png",
                                    "/usr/share/wallpapers/Lunar/contents/images/3840x2160.png"))

    # Lunar Look: one settings app for the look of every desktop.
    if graphical(cfg):
        cmds += [
            write_asset_cmd("look/lunar-look", "/usr/local/bin/lunar-look", "755"),
            write_asset_cmd("look/lunar-look-app", "/usr/local/lib/lunaros/lunar-look-app"),
            write_asset_cmd("look/look.json", "/etc/lunaros/look.json"),
            write_asset_cmd("look/lunar-look.desktop", "/usr/share/applications/lunar-look.desktop"),
        ]

    # Hyprland: lunar-ii, which installs illogical-impulse (offered at first login).
    if "hyprland" in cfg.all_desktops():
        cmds += [
            write_asset_cmd("ii/lunar-ii", "/usr/local/bin/lunar-ii", "755"),
            write_asset_cmd("ii/lunar-ii.desktop", "/usr/share/applications/lunar-ii.desktop"),
        ]

    # GNOME: dark, the moon, a Lunar dock - as system defaults, so anything
    # changed in Settings overrides them.
    if "gnome" in cfg.all_desktops():
        cmds += [
            write_asset_cmd("desktops/gnome/dconf-profile-user", "/etc/dconf/profile/user"),
            write_asset_cmd("desktops/gnome/00-lunar", "/etc/dconf/db/local.d/00-lunar"),
            "dconf update || true",
        ]

    # Hyprland, Sway, i3: their whole look lives in the user's config files.
    files = list(dict.fromkeys(f for d in cfg.all_desktops()
                               for f in DESKTOP_USER_FILES.get(d, [])))
    if files:
        cmds += user_files_cmds(cfg, files)
    if graphical(cfg) and cfg.username:
        # Generate the user's Lunar Look files now, as that user. Hyprland and
        # foot refuse a missing included file, so they get an empty one if the
        # run fails for any reason - the defaults in the main configs still hold.
        u, home = cfg.username, f"/home/{cfg.username}"
        cmds.append(
            f"runuser -u {u} -- env HOME={home} /usr/local/bin/lunar-look apply --no-reload || true; "
            f"for f in .config/hypr/lunar-look.conf .config/foot/lunar-look.ini .config/sway/lunar-look .config/i3/lunar-look; do "
            f"[ -d {home}/$(dirname $f) ] && [ ! -e {home}/$f ] && runuser -u {u} -- touch {home}/$f; done; true")
    if greeter_for(cfg) == "lightdm-gtk-greeter":
        cmds.append(write_asset_cmd("desktops/common/lightdm-gtk-greeter.conf",
                                    "/etc/lightdm/lightdm-gtk-greeter.conf"))

    # Plasma: black, see-through, the moon as wallpaper and at login. These
    # are defaults; lunar-plasma-setup applies them once at first login and
    # everything stays changeable in System Settings.
    if "plasma" in cfg.all_desktops():
        cmds += [
            write_asset_cmd("plasma/Lunar.colors", "/usr/share/color-schemes/Lunar.colors"),
            write_asset_cmd("plasma/Lunar.colorscheme", "/usr/share/konsole/Lunar.colorscheme"),
            write_asset_cmd("plasma/Lunar.profile", "/usr/share/konsole/Lunar.profile"),
            write_asset_cmd("plasma/lunar-wallpaper-preview.png",
                            "/usr/share/wallpapers/Lunar/contents/screenshot.png"),
            write_asset_cmd("plasma/wallpaper-metadata.json",
                            "/usr/share/wallpapers/Lunar/metadata.json"),
            write_asset_cmd("plasma/lunar-plasma-setup", "/usr/local/bin/lunar-plasma-setup", "755"),
            write_asset_cmd("plasma/plasma-layout.js", "/usr/share/lunaros/plasma-layout.js"),
            write_asset_cmd("plasma/lunar-logo.svg", "/usr/share/lunaros/lunar-logo.svg"),
            write_asset_cmd("plasma/lunar-plasma-setup.desktop",
                            "/etc/xdg/autostart/lunar-plasma-setup.desktop"),
            write_asset_cmd("plasma/sddm-lunar.conf", "/etc/sddm.conf.d/10-lunar.conf"),
            write_asset_cmd("plasma/sddm-breeze-theme.conf.user",
                            "/usr/share/sddm/themes/breeze/theme.conf.user"),
        ]

    # Boot splash: the half moon, name and slogan on black while the system
    # starts, and the passphrase prompt when the disk is encrypted. Needs the
    # theme, the plymouth hook in the boot image, and "splash" on the kernel
    # command line; the rebuild below then includes all three.
    theme = "/usr/share/plymouth/themes/lunar"
    cmds += [
        *[write_asset_cmd(f"plymouth/{f}", f"{theme}/{f}")
          for f in sorted(os.listdir(os.path.join(ASSETS, "plymouth")))],
        "plymouth-set-default-theme lunar || true",
        # After systemd or udev, whichever archinstall chose, so it starts
        # before the encryption prompt. Only if the hook is actually there:
        # naming a missing hook would make the boot-image rebuild fail.
        "if [ -f /usr/lib/initcpio/install/plymouth ]; then "
        "sed -i -E '/^HOOKS=/{/[( ]plymouth[ )]/!s/([( ])(systemd|udev)([ )])/\\1\\2 plymouth\\3/}' "
        "/etc/mkinitcpio.conf; fi",
        "if [ -f /etc/kernel/cmdline ] && [ -f /usr/lib/initcpio/install/plymouth ]; then "
        "for p in quiet splash loglevel=3 rd.udev.log_level=3 vt.global_cursor_default=0; do "
        "grep -qw \"$p\" /etc/kernel/cmdline || sed -i \"s|\\$| $p|\" /etc/kernel/cmdline; "
        "done; fi",
        # Straight to the splash: the boot menu stays hidden unless a key is
        # held while starting (Space), instead of 15 seconds of text.
        "for f in /boot/loader/loader.conf /efi/loader/loader.conf; do "
        "[ -f \"$f\" ] && sed -i 's/^timeout.*/timeout 0/' \"$f\"; done; true",
    ]

    # Nothing between the firmware logo and the splash. Arch's kernel presets
    # carry a --splash option pointing at Arch's logo, and archinstall turns
    # it on when it sets up UKIs, so every boot flashed that logo. Removed:
    # the screen stays black until the moon starts waxing.
    cmds.append(
        "sed -i -E 's#[[:space:]]*--splash[= ]/usr/share/systemd/bootctl/splash-arch\\.bmp##' "
        "/etc/mkinitcpio.d/*.preset 2>/dev/null; true")


    # Rebuild the boot images last. archinstall built them before any of the
    # above ran, so they still carry Arch's os-release: the boot menu title
    # and the "Welcome to ..." line both come from it. A failure here is
    # reported but does not abort - the system still boots, with the old
    # names - since archinstall treats any failed command as a failed install.
    cmds.append(
        "mkinitcpio -P || echo 'lunaros-setup: rebuilding the boot images "
        "failed; the boot menu may still show the old name' >&2")

    return cmds


# --------------------------------------------------------------------------
# building the configuration


def enabled_services(cfg: Config) -> list:
    p = cfg.profile_obj()
    services = ["nftables"]
    if p.apparmor:
        services.append("apparmor")
    if p.auditd:
        services.append("auditd")
    if p.usbguard:
        services.append("usbguard")
    return services


def build_config(cfg: Config, size_bytes: int = None) -> dict:
    main = PROFILE_FOR.get(cfg.desktop, PROFILE_FOR["minimal"])
    details = [d for k in cfg.all_desktops() for d in PROFILE_FOR.get(k, PROFILE_FOR["minimal"])["details"]]
    profile = {"main": main["main"], "details": list(dict.fromkeys(details)), "greeter": greeter_for(cfg)}
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
        "disk_config": disk_config(cfg, size_bytes),
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
        # True unconditionally. This only skips archinstall's own network
        # conveniences - a wifi prompt, a version check, and fetching Arch's
        # mirror-status JSON to re-rank mirrors - none of which the install
        # depends on: connectivity is checked before this runs (see
        # require_network in install(), reused from the older engine), and
        # the mirrorlist is already ranked by ensure_mirrors(). Left False,
        # a later step calls `systemctl show` to wait on reflector.service,
        # which needs a running systemd talking to dbus. A live medium has
        # that; a container building and testing the image does not, and
        # archinstall does not fail gracefully when it is missing.
        "offline": True,
        "packages": extra_packages(cfg),
        # Top level: archinstall 4 ignores it under pacman_config and
        # silently downloads one package at a time.
        "parallel_downloads": 8,
        "profile_config": {
            "gfx_driver": "All open-source",
            "greeter": profile["greeter"],
            "profile": {"main": profile["main"], "details": profile["details"]},
        },
        "script": "guided",
        # Enabled by archinstall itself rather than by a custom command, so a
        # missing unit is reported rather than silently skipped.
        "services": enabled_services(cfg),
        "silent": True,
        "swap": {"enabled": True, "algorithm": "zstd"},
        "timezone": cfg.timezone,
    }
    return config


def build_credentials(cfg: Config) -> dict:
    """Passwords, kept in a separate file so they never enter the main config.

    Plaintext goes under the keys prefixed with "!", which archinstall hashes
    with yescrypt before use. The unprefixed enc_password and
    root_enc_password fields take an *already hashed* password and store it
    verbatim; putting plaintext there creates an account whose password is
    the literal hash string, so nobody can ever log in. That was a real bug
    here, caught by running the configuration through archinstall's own
    parser rather than trusting the example files.
    """
    creds = {
        "users": [{
            "username": cfg.username,
            "!password": cfg.user_password,
            "sudo": True,
            "groups": [],
        }],
    }
    if not cfg.root_locked:
        creds["!root-password"] = cfg.user_password
    if cfg.encrypt:
        creds["encryption_password"] = cfg.luks_passphrase
    return creds


# --------------------------------------------------------------------------
# running it


WRAPPER_SOURCE = '''\
import sys

from archinstall.lib.installer import Installer

# set_keyboard_language() boots the target with systemd-nspawn to push the
# layout to X11 live. That needs a working container-boot stack, which a
# build environment lacks, and it fails by streaming boot output for
# gigabytes rather than erroring. The console keymap is unaffected: it is
# written to /etc/vconsole.conf beforehand by set_vconsole(). The X11 layout
# is written directly by the Lunar layer instead.
Installer.set_keyboard_language = lambda self, language: True

from archinstall.main import main

if __name__ == "__main__":
    sys.exit(main())
'''


def archinstall_available() -> bool:
    return shutil.which("archinstall") is not None


def install(cfg: Config, emit) -> None:
    """Install through archinstall, streaming its output to emit()."""
    if not archinstall_available():
        raise RuntimeError(
            "archinstall is not installed on this medium.\n"
            "  It is the installation engine; the medium cannot install\n"
            "  without it.")

    # Checked here rather than left to archinstall's own online check, which
    # the offline=True setting above disables. Before anything destructive:
    # finding out there is no network after the disk has been erased leaves a
    # machine that neither boots its old system nor has a new one.
    from .install import require_network
    emit("Checking the connection", accent=True)
    require_network(log=emit)
    emit("  mirrors reachable")

    emit("Checking the package list", accent=True)
    config_packages = available_packages(extra_packages(cfg), emit)

    workdir = tempfile.mkdtemp(prefix="lunar-archinstall-")
    config_path = os.path.join(workdir, "user_configuration.json")
    creds_path = os.path.join(workdir, "user_credentials.json")

    with open(config_path, "w") as fh:
        conf = build_config(cfg)
        conf["packages"] = config_packages      # the checked list, not the raw one
        json.dump(conf, fh, indent=2)
    # Credentials are readable by root only, and removed afterwards.
    fd = os.open(creds_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(build_credentials(cfg), fh, indent=2)

    # archinstall's own console-keyboard step can try to live-propagate the
    # X11 side by booting the target with systemd-nspawn - a real container
    # boot, which a build environment has no working stack for. Unlike the
    # dbus-only calls fixed above, that one does not fail cleanly: it reads
    # a boot console in a loop, so the failure is gigabytes of output rather
    # than a clean error. The console side is unaffected: archinstall's
    # set_vconsole() writes /etc/vconsole.conf from the same value directly,
    # unconditionally, before this method ever runs. The X11 side is set
    # directly in the Lunar layer above instead of through this mechanism.
    #
    # archinstall runs as a separate process, so this cannot be patched from
    # here directly; a tiny wrapper does the patch and then runs archinstall
    # itself, in the same process, so the patch applies before anything else
    # imports or calls it.
    wrapper_path = os.path.join(workdir, "run_archinstall.py")
    with open(wrapper_path, "w") as fh:
        fh.write(WRAPPER_SOURCE)

    emit("Installing with archinstall", accent=True)
    emit(f"  target {cfg.disk}   desktop {' + '.join(cfg.all_desktops())}   profile {cfg.profile}")
    emit(f"  configuration {config_path}")
    emit("")

    cmd = ["python3", wrapper_path, "--config", config_path, "--creds", creds_path,
           "--silent",
           # All three wait on a running systemd talking to dbus - present on
           # a real live medium, absent inside a build container. None of
           # them affect the installed system; they only pause the installer
           # until the live session's own clock, keyring sync and reflector
           # run have settled.
           #
           # --offline has to be a command-line flag, not only the "offline"
           # key already set in the JSON config above. archinstall reads
           # this particular gate from args.offline - the argparse namespace
           # built from the CLI - never from the parsed config object, so the
           # JSON key alone does nothing here. Confirmed by grepping
           # archinstall's own source for anywhere it reads the config
           # object's offline field for this check: nowhere does.
           "--offline", "--skip-ntp", "--skip-wkd"]

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
                emit("   " + rebrand(line)[:110])
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
