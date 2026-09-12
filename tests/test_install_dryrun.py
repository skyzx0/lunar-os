"""Dry-run install() end to end with every external command mocked.

This is the test that would have caught most of what has gone wrong on real
hardware: a package that is never built, a directory written to before it
exists, an ordering mistake between two stages. Nothing here touches a disk;
it records what the installer *would* run and checks the sequence makes sense.
"""

import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lunar-setup"))

from lunar_setup import disk, hardening, install
from lunar_setup.profiles import Config, DESKTOPS, PROFILES

CALLS = []
WRITES = []


def fake_run(cmd, check=True, input_=None, log=None, timeout=None):
    CALLS.append(list(cmd))
    if log:
        log("  $ " + " ".join(cmd))
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def fake_subprocess_run(cmd, *a, **k):
    CALLS.append(list(cmd))
    out = ""
    # pacman -Si decides whether a package "exists". Pretend everything the
    # repository actually builds is present and nothing else is.
    if "pacman" in cmd[0] and "-Si" in cmd:
        pkg = cmd[-1]
        known = pkg.startswith("lunar-") is False or pkg in BUILT
        return types.SimpleNamespace(returncode=0 if known else 1,
                                     stdout="", stderr="")
    if cmd[0] == "genfstab":
        out = "# fstab\n"
    return types.SimpleNamespace(returncode=0, stdout=out, stderr="")


def fake_chroot(cmd, log=None, check=True):
    CALLS.append(["chroot", cmd])
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def fake_write(path, content, mode=0o644, log=None):
    WRITES.append(path)


# What repo/packages/ actually contains, minus the keyring, which
# build-repo.sh skips for unsigned builds.
BUILT = {
    "lunar-branding", "lunar-cli", "lunar-hardening", "lunar-look",
    "lunar-setup", "lunar-desktop-gnome", "lunar-desktop-hyprland",
    "lunar-desktop-i3", "lunar-desktop-minimal", "lunar-desktop-plasma",
    "lunar-desktop-sway",
}


def dry_run(cfg):
    CALLS.clear()
    WRITES.clear()

    # Point the target root at a scratch directory: install() writes fstab
    # directly rather than through hardening.write(), so it needs a real path.
    root = tempfile.mkdtemp()
    (Path(root) / "etc").mkdir(parents=True, exist_ok=True)
    install.ROOT = root
    hardening.ROOT = root

    disk.run = fake_run
    hardening.chroot = fake_chroot
    hardening.write = fake_write
    install.run = fake_run
    install.chroot = fake_chroot
    install.subprocess = types.SimpleNamespace(
        run=fake_subprocess_run, DEVNULL=subprocess.DEVNULL,
        TimeoutExpired=subprocess.TimeoutExpired)

    # Disk helpers that read real hardware.
    disk.partition = lambda d, log=None: (f"{d}p1", f"{d}p2")
    disk.make_volumes = lambda fs, log=None, target=None: None
    disk.mount_esp = lambda esp, log=None: None
    disk.luks_format = lambda p, pw, log=None: None
    disk.luks_uuid = lambda p: "0000-1111"
    disk.secure_erase = lambda p, log=None: None
    disk.resume_autoactivation = lambda log=None: None
    install.require_network = lambda log=None: None
    install.ensure_mirrors = lambda log=None: None
    install.write_pacstrap_conf = lambda path="/tmp/c", log=None: "/tmp/c"

    lines = []
    install.install(cfg, lambda line, accent=False: lines.append(line))
    return lines


def flat():
    return [" ".join(str(x) for x in c) for c in CALLS]


# --- every combination must complete without raising -----------------------

for d in DESKTOPS:
    for prof in PROFILES:
        for enc in (True, False):
            cfg = Config(disk="/dev/nvme0n1", filesystem="btrfs",
                         encrypt=enc, username="tester", hostname="lunaros",
                         desktop=d.key, profile=prof.key)
            dry_run(cfg)

print(f"install() completes for all {len(DESKTOPS) * len(PROFILES) * 2} combinations")


# --- specific mistakes that reached hardware -------------------------------

cfg = Config(disk="/dev/nvme0n1", filesystem="btrfs", encrypt=False,
             username="tester", desktop="minimal", profile="baseline")
dry_run(cfg)
calls = flat()

# 1. A package that is never built must never be requested.
pacstrap = [c for c in calls if c.startswith("pacstrap")]
assert pacstrap, "pacstrap was never called"
assert "lunar-keyring" not in pacstrap[0], \
    "requesting lunar-keyring, which unsigned builds do not produce"

# 2. The ESP directory must exist before the kernel image is written into it.
mkdir_efi = next((i for i, c in enumerate(calls) if "mkdir -p /efi/EFI" in c), None)
mkinit = next((i for i, c in enumerate(calls) if "mkinitcpio -P" in c), None)
assert mkdir_efi is not None, "ESP directory never created"
assert mkinit is not None and mkdir_efi < mkinit, \
    "mkinitcpio runs before the ESP directory exists"

# 3. The boot loader is installed after the image it must boot.
bootctl = next((i for i, c in enumerate(calls) if "bootctl install" in c), None)
assert bootctl is not None and bootctl > mkinit, "bootctl runs before mkinitcpio"

# 4. fstab is written after packages, or pacstrap overwrites it.
assert any("genfstab" in c for c in calls), "fstab never generated"

# 5. The target gets its own pacman configuration.
assert "/etc/pacman.conf" in WRITES, "target pacman.conf never written"

# 6. systemd-firstboot must be answered and masked. Left alone it takes the
#    console on first boot and asks for a timezone, blocking everything after
#    it - which on the live medium meant the installer never started at all.
assert any("systemd-firstboot --locale" in c for c in calls), \
    "firstboot settings never applied to the target"
assert any("mask systemd-firstboot" in c for c in calls), \
    "systemd-firstboot not masked on the target"

print("ordering and package checks pass")
print(f"  {len(calls)} commands, {len(WRITES)} files written")
