"""lunar-setup - the Lunar OS installer.

    lunar-setup                 interactive wizard
    lunar-setup --unattended F  install from a JSON answer file
    lunar-setup --reapply       re-apply the security profile on a live system
"""

import argparse
import curses
import json
import os
import subprocess
import sys

from . import disk, hardening, install, ui
from .profiles import DESKTOPS, PROFILES, Config

STEPS = 9


def step(n: int) -> str:
    return f"{n} / {STEPS}"


def validate_hostname(v: str):
    if not v or len(v) > 63:
        return "Between 1 and 63 characters."
    if not all(c.isalnum() or c == "-" for c in v):
        return "Letters, digits and hyphens only."
    return None


def validate_username(v: str):
    if not v or not v[0].isalpha():
        return "Must start with a letter."
    if not all(c.isalnum() or c in "-_" for c in v):
        return "Letters, digits, hyphen and underscore only."
    if v in ("root", "admin", "nobody"):
        return "Reserved name."
    return None


def validate_passphrase(v: str):
    if len(v) < 12:
        return "At least 12 characters. This is the only thing between an "\
               "attacker with the disk and everything on it."
    return None


def wizard(stdscr) -> Config:
    ui.init_colors()
    stdscr.keypad(True)
    s = ui.Screen(stdscr)
    cfg = Config()

    s.clear()
    y = s.header("Lunar OS")
    y = s.paragraph(y, "Arch-based, encrypted by default, hardened by default. "
                       "This installer erases an entire disk. Nothing is written "
                       "until the final confirmation.")
    s.footer("press any key to continue")
    stdscr.refresh()
    stdscr.getch()

    # 1 - keymap
    keymaps = [("us", "United States"), ("de", "German"),
               ("uk", "United Kingdom"), ("fr", "French")]
    i = s.menu("Keyboard layout", [(k[1], k[0]) for k in keymaps], step=step(1))
    if i is None:
        return None
    cfg.keymap = keymaps[i][0]
    subprocess.run(["loadkeys", cfg.keymap], check=False)

    # 2 - disk
    disks = disk.list_disks()
    if not disks:
        raise SystemExit("No disk of at least 16 GiB found.")
    items = [(f"{p}  {size}", f"{model}" + ("  removable" if rm else ""))
             for p, model, size, rm in disks]
    i = s.menu("Target disk", items, step=step(2),
               preamble="Every partition on the selected disk is destroyed.")
    if i is None:
        return None
    cfg.disk = disks[i][0]

    i = s.menu("Overwrite before encrypting?", [
        ("No", "Fast. Old data stays readable in unused blocks until overwritten."),
        ("Yes", "Fills the disk with random data first. Slow, but leaves no trace "
                "of what was there or how much of the disk is in use."),
    ], step=step(2))
    if i is None:
        return None
    cfg.wipe_disk = i == 1

    # 3 - filesystem
    i = s.menu("Filesystem", [
        ("btrfs", "Subvolumes, transparent zstd compression, snapshots before updates."),
        ("ext4", "Simpler. No snapshots."),
    ], step=step(3))
    if i is None:
        return None
    cfg.filesystem = ("btrfs", "ext4")[i]

    # 4 - passphrase
    while True:
        pw = s.prompt("Disk encryption", "Passphrase", step=step(4), secret=True,
                      validator=validate_passphrase,
                      help_text="Unlocks the disk at every boot. There is no "
                                "recovery if you lose it.")
        if pw is None:
            return None
        again = s.prompt("Disk encryption", "Repeat", step=step(4), secret=True)
        if again is None:
            return None
        if pw == again:
            cfg.luks_passphrase = pw
            break

    # 5 - identity
    cfg.hostname = s.prompt("System", "Hostname", step=step(5), default="lunar",
                            validator=validate_hostname,
                            help_text="Visible on the local network unless you "
                                      "disable mDNS. A generic name leaks less.")
    if cfg.hostname is None:
        return None
    cfg.username = s.prompt("Account", "Username", step=step(5),
                            validator=validate_username)
    if cfg.username is None:
        return None
    while True:
        pw = s.prompt("Account", "Password", step=step(5), secret=True,
                      validator=lambda v: None if len(v) >= 8 else "At least 8 characters.")
        if pw is None:
            return None
        if pw == s.prompt("Account", "Repeat", step=step(5), secret=True):
            cfg.user_password = pw
            break

    # 6 - timezone
    tz = s.prompt("Locale", "Timezone", step=step(6), default="Europe/Vienna",
                  help_text="IANA name, for example Europe/Vienna. "
                            "UTC reveals the least about you.")
    if tz is None:
        return None
    cfg.timezone = tz

    # 7 - desktop
    i = s.menu("Desktop", [(d.name, d.blurb) for d in DESKTOPS], step=step(7),
               preamble="All graphical options default to Wayland. X11 cannot "
                        "isolate applications from each other's input.")
    if i is None:
        return None
    cfg.desktop = DESKTOPS[i].key

    # 8 - security profile
    i = s.menu("Security profile", [(p.name, p.blurb) for p in PROFILES],
               step=step(8), index=1,
               preamble="Each profile includes the one above it. All of them "
                        "encrypt the disk.")
    if i is None:
        return None
    cfg.profile = PROFILES[i].key

    # 9 - review
    p = cfg.profile_obj()
    body = (f"Disk {cfg.disk} will be erased.\n\n"
            f"Filesystem {cfg.filesystem}    Desktop {cfg.desktop_obj().name}    "
            f"Profile {p.name}\n"
            f"Host {cfg.hostname}    User {cfg.username}    Timezone {cfg.timezone}")
    if not s.confirm("Review", body, step=step(9),
                     yes="Erase " + cfg.disk + " and install"):
        return None
    return cfg


def run_install(stdscr, cfg) -> None:
    ui.init_colors()
    s = ui.Screen(stdscr)
    emit = s.log_view("Installing")
    try:
        install.install(cfg, emit)
    except Exception as exc:                      # noqa: BLE001
        emit("")
        emit("Installation failed: " + str(exc), accent=True)
        emit("A transcript is at /tmp/lunar-setup.log")
    emit("")
    emit("press any key to exit")
    stdscr.getch()


def main() -> int:
    ap = argparse.ArgumentParser(prog="lunar-setup")
    ap.add_argument("--unattended", metavar="FILE",
                    help="JSON answer file, same keys as Config")
    ap.add_argument("--reapply", action="store_true",
                    help="re-apply the security profile to the running system")
    ap.add_argument("--steps", action="store_true",
                    help="print the manual installation commands and exit")
    ap.add_argument("--memory", action="store_true",
                    help="report current memory use, for checking idle claims")
    args = ap.parse_args()

    # These two are read-only and useful without privileges.
    if args.steps:
        from .manual import STEPS
        print(STEPS)
        return 0

    if args.memory:
        from .manual import report_memory
        report_memory()
        return 0

    if os.geteuid() != 0:
        print("lunar-setup must run as root.", file=sys.stderr)
        return 1

    if args.reapply:
        cfg = Config(**json.load(open("/etc/lunar/setup.json")))
        hardening.ROOT = "/"
        hardening.apply(cfg, "", log=lambda m, accent=False: print(m))
        return 0

    if args.unattended:
        cfg = Config(**json.load(open(args.unattended)))
        install.install(cfg, lambda m, accent=False: print(m))
        return 0

    cfg = curses.wrapper(wizard)
    if cfg is None:
        print("Cancelled. Nothing was written.")
        return 1
    curses.wrapper(run_install, cfg)

    os.makedirs("/mnt/etc/lunar", exist_ok=True)
    saved = {k: v for k, v in vars(cfg).items()
             if k not in ("luks_passphrase", "user_password")}
    with open("/mnt/etc/lunar/setup.json", "w") as fh:
        json.dump(saved, fh, indent=2)
    os.chmod("/mnt/etc/lunar/setup.json", 0o600)
    install.unmount()
    return 0


if __name__ == "__main__":
    sys.exit(main())
