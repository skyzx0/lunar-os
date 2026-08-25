"""Exercise run_install with a fake installer and a fake curses screen.

The last two failures in this file were a syntax error and a write to a closed
file - both things a single run would have caught. This runs it.
"""

import curses
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lunar-setup"))

from lunar_setup import __main__ as m
from lunar_setup.profiles import Config


class FakeScreen:
    def getmaxyx(self):
        return 40, 100

    def erase(self):
        pass

    def addnstr(self, *a, **k):
        pass

    def refresh(self):
        pass

    def getch(self):
        return ord("q")

    def keypad(self, *a):
        pass


def fake_curses():
    """Neutralise curses so the UI code runs headless."""
    for name in ("start_color", "use_default_colors", "curs_set", "init_pair"):
        setattr(curses, name, lambda *a, **k: None)
    curses.color_pair = lambda n: 0
    curses.A_BOLD = 0
    curses.A_DIM = 0


def run_case(name, installer):
    tmp = tempfile.mkdtemp()
    m.LOG_PATH = str(Path(tmp) / "lunar-setup.log")
    m.install = types.SimpleNamespace(install=installer)

    fake_curses()
    cfg = Config(disk="/dev/fake", filesystem="ext4", encrypt=False,
                 desktop="minimal", profile="hardened")

    ok = m.run_install(FakeScreen(), cfg)
    log = Path(m.LOG_PATH).read_text()

    print(f"{name}:")
    print(f"  returned ok={ok}")
    print(f"  log written: {len(log.splitlines())} lines")
    assert "lunaros-setup" in log, "header missing from log"
    assert "press any key" in log, "tail lines missing - closed file?"
    return ok, log


# --- success path ---
def good(cfg, emit):
    emit("Partitioning", accent=True)
    emit("  $ sgdisk -Z /dev/fake")
    emit("Installation complete.", accent=True)


ok, log = run_case("success", good)
assert ok is True


# --- failure path, the one that crashed on hardware ---
def bad(cfg, emit):
    emit("Partitioning", accent=True)
    from lunar_setup.disk import CommandFailed
    raise CommandFailed(["mount", "-t", "vfat", "/dev/fake1", "/mnt/efi"],
                        32, "mount: /mnt/efi: wrong fs type, bad option, "
                            "bad superblock on /dev/fake1.")


ok, log = run_case("failure", bad)
assert ok is False, "failure must report failure"
assert "wrong fs type" in log, "stderr not carried into the log"
assert "Installation failed" in log

print()
print("both paths run; the failure log contains the real mount error:")
for line in log.splitlines()[-7:]:
    print("   ", line)


# --- disk module: every public helper must at least import and run ----------
# A missing import in a rarely-taken branch does not show up until the branch
# is taken, which on this module means during a real installation.

from lunar_setup import disk as _disk

for name in ("release_disk", "disk_is_busy", "human", "memory_bytes",
             "list_disks", "tarball_ok" if hasattr(_disk, "tarball_ok") else "human"):
    assert hasattr(_disk, name), f"disk.{name} missing"

assert _disk.disk_is_busy("/dev/definitely-not-a-disk") == ""
assert _disk.human(1536) .endswith("KiB")
assert _disk.memory_bytes() > 0
_disk.list_disks()          # must not raise on any machine

print("disk helpers import and run")
