"""lunar-hardening must not own files that Arch packages own - and must not
solve that by quietly dropping the settings.

pacman refuses to install two packages that own the same path, so shipping
/etc/nftables.conf (owned by nftables) or /etc/security/faillock.conf (owned
by pam) makes the install fail. The tempting fix is to skip those files,
which builds and installs cleanly and leaves the system with Arch's stock
firewall and no lockout policy, with nothing reporting it. This checks both
halves: no conflicting paths, and every setting still reaches the place its
consumer reads.
"""

import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
hardening = root / "hardening"
shipped = {str(p.relative_to(hardening)) for p in hardening.rglob("*") if p.is_file()}

# Paths owned by Arch packages lunar-hardening depends on or may coexist with.
ARCH_OWNED = {
    "etc/nftables.conf",              # nftables
    "etc/security/faillock.conf",     # pam
    "etc/security/pwquality.conf",    # libpwquality
    "etc/systemd/zram-generator.conf",
}
clash = shipped & ARCH_OWNED
assert not clash, f"lunar-hardening would own Arch-owned paths: {sorted(clash)}"
print(f"no Arch-owned paths among {len(shipped)} shipped files")

# The firewall: the ruleset exists, and the service is pointed at it.
assert "etc/lunar/nftables.conf" in shipped, "Lunar's firewall ruleset is no longer shipped"
dropin = (hardening / "etc/systemd/system/nftables.service.d/lunar.conf").read_text()
starts = re.findall(r"^ExecStart=(.+)$", dropin, re.M)
assert starts and starts[-1].strip() == "/usr/bin/nft -f /etc/lunar/nftables.conf", \
    "nftables.service is not pointed at Lunar's ruleset"
assert "ExecStart=\n" in dropin, "drop-in must clear ExecStart before replacing it"
print("firewall ruleset shipped and nftables.service loads it")

# The settings that moved to drop-in directories are still present.
for path in ("etc/security/pwquality.conf.d/lunar.conf",
             "etc/systemd/zram-generator.conf.d/lunar.conf"):
    assert path in shipped, f"{path} is missing"
print("pwquality and zram settings present as drop-ins")

# Faillock has no drop-in directory: carried in /usr/share, copied on install.
assert "usr/share/lunar-hardening/faillock.conf" in shipped, "faillock settings not shipped"
pkgbuild = (root / "repo/packages/lunar-hardening/PKGBUILD").read_text()
assert re.search(r"^install=lunar-hardening\.install$", pkgbuild, re.M), \
    "PKGBUILD no longer runs the install script that places faillock.conf"
script = (root / "repo/packages/lunar-hardening/lunar-hardening.install").read_text()
assert "/etc/security/faillock.conf" in script and "post_install" in script
print("faillock settings are copied into place on install and upgrade")

# The audit watch follows the ruleset's real location.
rules = (hardening / "etc/audit/rules.d/lunar.rules").read_text()
assert "/etc/lunar/nftables.conf" in rules, "audit rule still watches the old ruleset path"
print("audit watches the ruleset at its actual path")
