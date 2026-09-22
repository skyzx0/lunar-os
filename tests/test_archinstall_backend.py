"""The archinstall backend: configuration shape and the Lunar layer.

archinstall is Arch's own installer and is trusted to do the installing. What
this checks is the part Lunar is responsible for - that the configuration it
hands archinstall is well formed, and that its post-install commands cannot
damage the system archinstall built.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lunar-setup"))

from lunar_setup import archinstall_backend as ab
from lunar_setup.profiles import Config, DESKTOPS, PROFILES

# 1. Every combination produces a valid configuration.
for d in DESKTOPS:
    for p in PROFILES:
        for enc in (True, False):
            for fs in ("ext4", "btrfs"):
                cfg = Config(disk="/dev/vda", desktop=d.key, profile=p.key,
                             encrypt=enc, filesystem=fs, username="u",
                             user_password="p", luks_passphrase="l")
                conf = ab.build_config(cfg)
                creds = ab.build_credentials(cfg)
                json.dumps(conf)
                json.dumps(creds)

                dm = conf["disk_config"]["device_modifications"][0]
                assert dm["device"] == "/dev/vda"
                assert dm["wipe"] is True
                assert len(dm["partitions"]) == 2
                assert dm["partitions"][0]["mountpoint"] == "/boot"
                assert ("disk_encryption" in conf["disk_config"]) == enc
                assert conf["bootloader_config"]["uki"] is True

print(f"configuration valid for all "
      f"{len(DESKTOPS) * len(PROFILES) * 4} combinations")

# 2. Passwords never appear in the main configuration.
cfg = Config(disk="/dev/vda", username="u", user_password="SECRET-PW",
             encrypt=True, luks_passphrase="SECRET-LUKS")
text = json.dumps(ab.build_config(cfg))
assert "SECRET-PW" not in text, "user password leaked into the config file"
assert "SECRET-LUKS" not in text, "disk passphrase leaked into the config file"
print("no secrets in the main configuration")

# 3. The Lunar layer masks firstboot. Left unmasked, it takes the console on
#    first boot and asks for settings the installer already applied.
assert "systemctl mask systemd-firstboot.service" in ab.lunar_layer(Config())
print("systemd-firstboot is masked")

# 4. Kernel hardening must never touch the parameters that locate or unlock
#    the disk. archinstall writes those; replacing them makes an encrypted
#    system unbootable.
for p in PROFILES:
    params = ab.kernel_hardening(Config(profile=p.key))
    bad = [x for x in params if x.startswith(("root=", "rd.luks", "cryptdevice"))]
    assert not bad, f"{p.key} would overwrite boot-critical parameters: {bad}"

# ... and the command that applies them must preserve what is already there.
d = tempfile.mkdtemp()
os.makedirs(f"{d}/etc/kernel")
original = "rd.luks.name=abc=root root=/dev/mapper/root rw"
Path(f"{d}/etc/kernel/cmdline").write_text(original + "\n")
cmd = [c for c in ab.lunar_layer(Config()) if "kernel/cmdline" in c][0]
cmd = cmd.replace("/etc/kernel/cmdline", f"{d}/etc/kernel/cmdline")
cmd = cmd.replace("mkinitcpio -P", "true")
subprocess.run(["bash", "-c", cmd], check=True)
first = Path(f"{d}/etc/kernel/cmdline").read_text().strip()
subprocess.run(["bash", "-c", cmd], check=True)
second = Path(f"{d}/etc/kernel/cmdline").read_text().strip()

assert first.startswith(original), "archinstall's boot parameters were lost"
assert first == second, "applying twice changed the command line"
print("kernel hardening appends, preserves unlock parameters, is idempotent")
