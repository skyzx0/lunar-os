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
import time
import sys

from . import disk, hardening, install, ui
from .locales import KEYMAPS, LOCALES, TIMEZONES, keymap_labels, x11_for
from .profiles import DESKTOPS, PROFILES, Config

STEPS = 10


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
    y = s.paragraph(y, "Encrypted by default. Hardened by default. "
                       "This installer erases an entire disk. Nothing is written "
                       "until the final confirmation.")
    s.footer("press any key to continue")
    stdscr.refresh()
    stdscr.getch()

    # 1 - keymap
    i = s.menu("Keyboard layout", keymap_labels(), step=step(1),
               preamble="The layout is applied immediately so you can test it "
                        "when typing the passphrase.")
    if i is None:
        return None
    cfg.keymap = KEYMAPS[i][0]
    subprocess.run(["loadkeys", cfg.keymap], check=False)

    # 1b - locale
    i = s.menu("System language", [(label, code) for code, label in LOCALES],
               step=step(1),
               preamble="Sets messages, dates and number formats. The keyboard "
                        "layout is separate and already chosen.")
    if i is None:
        return None
    cfg.locale = LOCALES[i][0]

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

    # 4 - encryption
    i = s.menu("Disk encryption", [
        ("Encrypt the disk (LUKS2)",
         "Everything except the boot loader is unreadable without the "
         "passphrase. Costs a passphrase at every boot."),
        ("No encryption",
         "Faster to set up. Anyone with the disk can read every file on it."),
    ], step=step(4), index=0,
       preamble="This cannot be changed later without reinstalling.")
    if i is None:
        return None
    cfg.encrypt = i == 0

    if not cfg.encrypt:
        # Not a scare screen: a plain statement of what is being given up, once,
        # so the choice is informed rather than a default someone clicked past.
        ok = s.confirm("No encryption", step=step(4),
            body="Without encryption, anyone who takes this machine or removes "
                 "the drive can read every file on it: documents, saved "
                 "passwords, browser sessions, SSH keys. No password on the "
                 "login screen changes that, because the login screen is not "
                 "involved when the disk is read on another computer.\n\n"
                 "The security profile still applies. Full-disk encryption is "
                 "the single largest thing it provides, and it will be off.",
            yes="Install without encryption", no="Go back and encrypt")
        if not ok:
            cfg.encrypt = True

    if cfg.encrypt:
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
    items = [(z, "") for z in TIMEZONES] + [("Type another...", "")]
    i = s.menu("Timezone", items, step=step(6),
               preamble="UTC reveals the least about where you are.")
    if i is None:
        return None
    if i == len(TIMEZONES):
        tz = s.prompt("Timezone", "IANA name", step=step(6), default="UTC",
                      help_text="For example Europe/Vienna or America/Denver.")
        if tz is None:
            return None
        cfg.timezone = tz
    else:
        cfg.timezone = TIMEZONES[i]

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

    # 9 - network privacy
    i = s.menu("Network privacy", [
        ("None", "No network identity randomisation."),
        ("Spoof", "Randomise MAC, hostname and IPv6 each connection. "
                  "Low cost, safe to leave on."),
        ("Spoof + cover traffic", "Also generate decoy traffic. Weak against a "
                                  "capable observer - see the note next."),
    ], step=step(9), index=1,
       preamble="Both are off unless chosen here, and both can be changed "
                "later with the lunar-privacy command.")
    if i is None:
        return None
    cfg.spoof_network = i >= 1
    cfg.cover_traffic = i == 2

    if cfg.cover_traffic:
        ok = s.confirm("Cover traffic", step=step(9),
            body="Cover traffic raises the effort for someone casually watching "
                 "your connection to tell when you are active. It does NOT hide "
                 "which sites you visit, does not defeat a capable observer who "
                 "sees your real traffic underneath, and does not make you "
                 "anonymous. A machine emitting constant noise also has its own "
                 "recognisable signature.\n\nEnable it anyway?",
            yes="Enable cover traffic", no="Spoof only")
        if not ok:
            cfg.cover_traffic = False

    # 10 - review
    p = cfg.profile_obj()
    lines = [f"Disk {cfg.disk} will be erased.", ""]
    if not cfg.encrypt:
        lines += ["NOT ENCRYPTED - readable by anyone who has the disk.", ""]
    lines += [
        f"Filesystem {cfg.filesystem}    Desktop {cfg.desktop_obj().name}"
        f"    Profile {p.name}",
        f"Keyboard {cfg.keymap}    Language {cfg.locale}    Timezone {cfg.timezone}",
        f"Host {cfg.hostname}    User {cfg.username}",
    ]
    if cfg.spoof_network or cfg.cover_traffic:
        extras = []
        if cfg.spoof_network:
            extras.append("network spoofing")
        if cfg.cover_traffic:
            extras.append("cover traffic")
        lines.append("Also: " + ", ".join(extras))

    if not s.confirm("Review", "\n".join(lines), step=step(10),
                     yes="Erase " + cfg.disk + " and install"):
        return None
    return cfg


LOG_PATH = "/tmp/lunar-setup.log"


def run_install(stdscr, cfg) -> bool:
    """Run the installation. Returns True on success.

    The log file stays open for the whole function and is closed by the
    context manager on the way out, after the last emit. Closing it in a
    finally block and then emitting again - which is what an earlier version
    did - crashes on a closed file and buries whatever the real failure was.
    """
    ui.init_colors()
    s = ui.Screen(stdscr)
    screen_log = s.log_view("Installing")

    failed = False

    # Everything the installer prints goes to a file as well as the screen.
    # A curses log view holds only what fits, and the line that explains a
    # failure is usually the one that has already scrolled away.
    with open(LOG_PATH, "w", buffering=1) as log_file:

        def emit(line: str, accent: bool = False) -> None:
            # The screen is the thing the user is looking at; never let a
            # logging problem take the installer down with it.
            try:
                log_file.write(line + "\n")
            except (ValueError, OSError):
                pass
            screen_log(line, accent)

        emit(f"lunaros-setup {time.strftime('%Y-%m-%d %H:%M:%S')}")
        emit(f"target {cfg.disk}   filesystem {cfg.filesystem}   "
             f"encrypted {'yes' if cfg.encrypt else 'no'}")
        emit(f"desktop {cfg.desktop}   profile {cfg.profile}")
        emit("")

        try:
            install.install(cfg, emit)
        except Exception as exc:                      # noqa: BLE001
            failed = True
            emit("")
            emit("Installation failed.", accent=True)
            for line in str(exc).splitlines():
                emit("  " + line)
            emit("")
            emit(f"The full transcript is at {LOG_PATH}")
            emit("Reach a shell with Ctrl+Alt+F2 to read it.")

        emit("")
        emit("press any key to exit")
        stdscr.getch()

    return not failed


def main() -> int:
    ap = argparse.ArgumentParser(prog="lunar-setup")
    ap.add_argument("--unattended", metavar="FILE",
                    help="JSON answer file, same keys as Config")
    ap.add_argument("--reapply", action="store_true",
                    help="re-apply the security profile to the running system")
    ap.add_argument("--fast", action="store_true",
                    help="minimal console system, smallest package set")
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
    if cfg is not None and args.fast:
        cfg.fast = True
        cfg.desktop = "minimal"
    if cfg is None:
        print("Cancelled. Nothing was written.")
        return 1
    ok = curses.wrapper(run_install, cfg)

    if not ok:
        # Leave the target mounted. Tearing it down on failure destroys the
        # evidence and means the next attempt starts from a half-built disk
        # with no way to see what happened.
        print(f"Installation failed. See {LOG_PATH}")
        print("The target is still mounted at /mnt for inspection.")
        print("Re-run lunaros-setup to start over; it re-partitions from scratch.")
        return 1

    os.makedirs("/mnt/etc/lunar", exist_ok=True)
    # Secrets never touch the installed system's config.
    saved = {k: v for k, v in vars(cfg).items()
             if k not in ("luks_passphrase", "user_password")}
    with open("/mnt/etc/lunar/setup.json", "w") as fh:
        json.dump(saved, fh, indent=2)
    os.chmod("/mnt/etc/lunar/setup.json", 0o600)
    install.unmount()
    return 0


if __name__ == "__main__":
    sys.exit(main())
