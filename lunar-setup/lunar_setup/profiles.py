"""Desktop and security profiles offered by lunar-setup."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Desktop:
    key: str
    name: str
    blurb: str
    meta: str
    session: str          # display-manager session, "" for none
    dm: str               # display manager package, "" for none


DESKTOPS = [
    Desktop(
        key="hyprland",
        name="Hyprland",
        blurb="Wayland tiling compositor. Lowest attack surface of the graphical options.",
        meta="lunar-desktop-hyprland",
        session="hyprland",
        dm="greetd",
    ),
    Desktop(
        key="plasma",
        name="KDE Plasma",
        blurb="Full Wayland desktop. Good hardware support, largest package set.",
        meta="lunar-desktop-plasma",
        session="plasma",
        dm="sddm",
    ),
    Desktop(
        key="gnome",
        name="GNOME",
        blurb="Wayland by default, strongest Flatpak/portal sandboxing integration.",
        meta="lunar-desktop-gnome",
        session="gnome",
        dm="gdm",
    ),
    Desktop(
        key="sway",
        name="Sway",
        blurb="Wayland tiling, i3 layout with a compositor. Middle ground "
              "between Hyprland and bare i3.",
        meta="lunar-desktop-sway",
        session="sway",
        dm="greetd",
    ),
    Desktop(
        key="i3",
        name="i3",
        blurb="X11 tiling. The lightest graphical option with a real WM. "
              "No compositor, no Wayland.",
        meta="lunar-desktop-i3",
        session="i3",
        dm="greetd",
    ),
    Desktop(
        key="minimal",
        name="Minimal (TTY)",
        blurb="No graphical stack at all. A terminal and nothing else.",
        meta="lunar-desktop-minimal",
        session="",
        dm="",
    ),
]


@dataclass(frozen=True)
class SecurityProfile:
    key: str
    name: str
    blurb: str
    # feature switches consumed by hardening.py
    hardened_kernel: bool = True
    hardened_malloc: bool = True
    apparmor: bool = True
    nftables_egress_filter: bool = False
    usbguard: bool = True
    auditd: bool = True
    lockdown: str = "integrity"        # "", "integrity", "confidentiality"
    secure_boot: bool = True
    tpm2_unlock: bool = False
    encrypted_swap: bool = True
    tor_transparent: bool = False
    mac_randomisation: bool = True
    disable_ipv6: bool = False
    firejail_defaults: bool = False


PROFILES = [
    SecurityProfile(
        key="baseline",
        name="Baseline",
        blurb="Hardened kernel, AppArmor, full-disk encryption, default-deny inbound firewall.",
        usbguard=False,
        auditd=False,
        secure_boot=False,
    ),
    SecurityProfile(
        key="hardened",
        name="Hardened",
        blurb="Baseline plus Secure Boot with your own keys, USBGuard, auditd, hardened_malloc.",
    ),
    SecurityProfile(
        key="paranoid",
        name="Paranoid",
        blurb=(
            "Hardened plus kernel lockdown=confidentiality, egress filtering, "
            "Firejail defaults, MAC randomisation, TPM2-sealed unlock."
        ),
        lockdown="confidentiality",
        nftables_egress_filter=True,
        firejail_defaults=True,
        tpm2_unlock=True,
    ),
    SecurityProfile(
        key="onion",
        name="Onion",
        blurb=(
            "Paranoid plus transparent Tor routing for all traffic. "
            "Read docs/SECURITY.md before choosing this: it is not Whonix."
        ),
        lockdown="confidentiality",
        nftables_egress_filter=True,
        firejail_defaults=True,
        tpm2_unlock=True,
        tor_transparent=True,
        disable_ipv6=True,
    ),
]


@dataclass
class Config:
    """Everything the wizard collects. Serialised to /tmp/lunar-setup.json."""

    disk: str = ""
    wipe_disk: bool = False           # cryptsetup-style random overwrite first
    luks_passphrase: str = ""
    filesystem: str = "btrfs"         # btrfs | ext4
    hostname: str = "lunar"
    username: str = ""
    user_password: str = ""
    root_locked: bool = True
    timezone: str = "UTC"
    locale: str = "en_US.UTF-8"
    keymap: str = "us"
    desktop: str = "hyprland"
    # More desktops installed alongside the main one; pick one at login.
    extra_desktops: list = field(default_factory=list)
    profile: str = "hardened"
    encrypt: bool = True              # LUKS2 full-disk encryption
    fast: bool = False                # minimal console system, fastest install
    spoof_network: bool = False       # MAC/hostname/DNS randomisation at boot
    cover_traffic: bool = False       # decoy traffic; off, and honestly caveated
    extra_packages: list = field(default_factory=list)

    def all_desktops(self) -> list:
        """The main desktop first, then the others, without repeats."""
        out = [self.desktop] + [d for d in self.extra_desktops if d != "minimal"]
        return list(dict.fromkeys(out))

    def desktop_obj(self) -> Desktop:
        return next(d for d in DESKTOPS if d.key == self.desktop)

    def profile_obj(self) -> SecurityProfile:
        return next(p for p in PROFILES if p.key == self.profile)
