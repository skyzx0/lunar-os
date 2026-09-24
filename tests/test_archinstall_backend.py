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

SIZE = 20 * 1024 ** 3        # a 20 GiB disk, supplied rather than measured

# 1. Every combination produces a valid configuration.
for d in DESKTOPS:
    for p in PROFILES:
        for enc in (True, False):
            for fs in ("ext4", "btrfs"):
                cfg = Config(disk="/dev/vda", desktop=d.key, profile=p.key,
                             encrypt=enc, filesystem=fs, username="u",
                             user_password="p", luks_passphrase="l")
                conf = ab.build_config(cfg, size_bytes=SIZE)
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

# The layout must fit: archinstall rejects a final partition that runs into
# the backup GPT header, and there is no "rest of the disk" unit to lean on.
conf = ab.build_config(Config(disk="/dev/vda"), size_bytes=SIZE)
parts = conf["disk_config"]["device_modifications"][0]["partitions"]
esp, root = parts
for part in parts:
    for key in ("start", "size"):
        assert part[key]["unit"] == "MiB", "sizes must be whole MiB"
        assert part[key]["sector_size"] is not None, "sector_size cannot be null"
    assert "dev_path" in part, "archinstall requires dev_path on every partition"
end_mib = root["start"]["value"] + root["size"]["value"]
assert end_mib <= SIZE // (1024 * 1024) - 1, "root runs into the backup GPT header"
assert root["start"]["value"] == esp["start"]["value"] + esp["size"]["value"], \
    "partitions overlap or leave a gap"

# Too small a disk is refused with a message, not a crash deep in archinstall.
try:
    ab.build_config(Config(disk="/dev/vda"), size_bytes=4 * 1024 ** 3)
    raise AssertionError("a 4 GiB disk was accepted")
except RuntimeError as exc:
    assert "needs at least" in str(exc)

print(f"configuration valid for all "
      f"{len(DESKTOPS) * len(PROFILES) * 4} combinations")

# 2. Passwords never appear in the main configuration.
cfg = Config(disk="/dev/vda", username="u", user_password="SECRET-PW",
             encrypt=True, luks_passphrase="SECRET-LUKS")
text = json.dumps(ab.build_config(cfg, size_bytes=SIZE))
assert "SECRET-PW" not in text, "user password leaked into the config file"
assert "SECRET-LUKS" not in text, "disk passphrase leaked into the config file"
print("no secrets in the main configuration")

creds = ab.build_credentials(Config(username="u", user_password="pw",
                                    root_locked=False))
user = creds["users"][0]
assert "!password" in user, "plaintext must use the !password key"
assert "enc_password" not in user, \
    "enc_password takes a hash; plaintext there makes login impossible"
assert "root_enc_password" not in creds, \
    "root_enc_password takes a hash; use !root-password for plaintext"
print("credentials use the keys archinstall hashes")

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


# --- archinstall's own parser ------------------------------------------------
# The strongest check available without installing: hand every configuration
# to the parser archinstall itself uses. Schema drift between archinstall
# releases then fails here, in seconds, rather than after an ISO is built.
try:
    from archinstall.lib.args import ArchConfig, Arguments
except Exception:
    print("archinstall not importable here; parser check skipped")
else:
    parsed = 0
    for d in DESKTOPS:
        for p in PROFILES:
            for enc in (True, False):
                cfg = Config(disk="/dev/vda", desktop=d.key, profile=p.key,
                             encrypt=enc, username="u", user_password="p",
                             luks_passphrase="l", root_locked=False)
                merged = {**ab.build_config(cfg, size_bytes=SIZE),
                          **ab.build_credentials(cfg)}
                # The disk section needs a real block device to resolve; the
                # loopback install test covers it for real.
                merged.pop("disk_config")
                c = ArchConfig.from_config(merged, Arguments())
                u = c.auth_config.users[0]
                assert u.password.enc_password != "p", \
                    "password stored verbatim instead of hashed"
                parsed += 1
    print(f"archinstall's parser accepts all {parsed} configurations")


# --- --offline must be a real CLI flag, not only a JSON key -----------------
# archinstall's _verify_service_stop() gate is read from args.offline, the
# argparse namespace built from the command line, never from the parsed
# config object. Setting "offline": true in the JSON file alone does nothing
# for this check - confirmed by grepping archinstall's own source, which has
# no reader for config.offline anywhere. This shipped once with only the
# JSON key set and failed in CI with a dbus error the JSON key looked like it
# should have prevented.

import unittest.mock as _mock

_calls = []


def _fake_popen(cmd, **kw):
    _calls.append(cmd)
    m = _mock.MagicMock()
    if cmd and cmd[0] == "yes":
        m.stdout = _mock.MagicMock()
    else:
        m.stdout = iter([])
        m.wait.return_value = 0
    return m


# subprocess.run is implemented on top of subprocess.Popen, so mocking Popen
# globally also breaks disk_bytes()'s own subprocess.run calls before the
# code under test is even reached. Give it a fixed size directly instead.
with _mock.patch.object(ab, "disk_bytes", return_value=SIZE), \
     _mock.patch("subprocess.Popen", side_effect=_fake_popen):
    _cfg = Config(disk="/dev/vda", username="u", user_password="p")
    try:
        ab.install(_cfg, lambda m, accent=False: None)
    except Exception:
        pass  # only the argv passed to archinstall matters here

archinstall_calls = [c for c in _calls if c and c[0] == "archinstall"]
assert archinstall_calls, "archinstall was never invoked"
assert "--offline" in archinstall_calls[0], (
    "the JSON 'offline' key is set but --offline is missing from argv; "
    "archinstall reads this gate from args.offline (CLI only) and will "
    "not honour the JSON key")
print("--offline is present on the actual command line")
