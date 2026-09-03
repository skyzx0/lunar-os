#!/usr/bin/env python3
"""Check every package the installer asks for against the real repositories.

Package names move to the AUR, get renamed, or turn out never to have been in
the official repositories at all. Discovering that during an installation
means discovering it after the disk has been erased.

This runs inside the build container, which has pacman and a network, so the
answer comes from the actual repositories rather than from anyone's memory.

Exit status:
  0  every essential package exists
  1  an essential package is missing, or the check could not run
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lunar-setup"))

from lunar_setup import install
from lunar_setup.profiles import Config, DESKTOPS, PROFILES

# Built by repo/build-repo.sh rather than fetched from a repository.
OURS_PREFIX = "lunar-"


def metapackage_depends() -> dict:
    """Dependencies declared by our own metapackages.

    These are never resolved at build time - the packages are built with
    --nodeps because their depends() describe what the installed system pulls
    in, not what building them needs. So a name that has moved to the AUR
    stays undetected until somebody installs that desktop.
    """
    import re
    out = {}
    root = Path(__file__).resolve().parent.parent / "repo" / "packages"
    for pkgbuild in sorted(root.glob("*/PKGBUILD")):
        text = pkgbuild.read_text()
        m = re.search(r"^depends=\((.*?)\)", text, re.S | re.M)
        if not m:
            continue
        names = re.findall(r"'([^']+)'", m.group(1))
        # Strip version constraints and provider syntax.
        names = [n.split(">")[0].split("<")[0].split("=")[0] for n in names]
        out[pkgbuild.parent.name] = [n for n in names
                                     if not n.startswith(OURS_PREFIX)]
    return out


def collect() -> set:
    """Every package name any configuration can ask for."""
    names = set(install.BASE) | set(install.SECURITY) | set(install.FAST_BASE)
    for d in DESKTOPS:
        for p in PROFILES:
            names |= set(install.package_set(Config(desktop=d.key, profile=p.key)))
    names |= set(install.AUR_SUGGESTED)
    return names


def exists(pkg: str) -> bool:
    return subprocess.run(["pacman", "-Si", pkg],
                          capture_output=True).returncode == 0


def main() -> int:
    print(":: refreshing package databases")
    if subprocess.run(["pacman", "-Sy", "--noconfirm"],
                      capture_output=True).returncode != 0:
        print("!! could not sync databases; skipping the check", file=sys.stderr)
        return 0

    names = sorted(collect())
    ours, upstream = [], []
    for n in names:
        (ours if n.startswith(OURS_PREFIX) else upstream).append(n)

    missing = [p for p in upstream if not exists(p)]
    ok = len(upstream) - len(missing)

    print(f":: {ok}/{len(upstream)} upstream packages found"
          f"  ({len(ours)} built locally)")

    check_metapackages()

    if not missing:
        return 0

    essential = install.REQUIRED.intersection(missing)
    optional = sorted(set(missing) - essential)

    if optional:
        print()
        print("   These are not in the repositories. The installer drops them")
        print("   at install time, so nothing breaks, but they are dead weight")
        print("   in the package lists:")
        for p in optional:
            print(f"     {p}")

    if essential:
        print()
        print("!! Packages the system cannot boot without are missing:",
              file=sys.stderr)
        for p in sorted(essential):
            print(f"     {p}", file=sys.stderr)
        return 1

    return 0


def check_metapackages() -> int:
    """Report metapackage dependencies that no longer exist.

    Not fatal: a broken desktop metapackage only affects installs that choose
    that desktop, and failing the whole build over it would be worse than
    saying so clearly.
    """
    problems = 0
    for pkg, deps in metapackage_depends().items():
        missing = [d for d in deps if not exists(d)]
        if missing:
            problems += 1
            print()
            print(f"   {pkg} depends on packages that are not in the "
                  f"repositories:")
            for d in missing:
                print(f"     {d}")
            print(f"   Choosing that desktop in the installer will fail.")
    return problems


if __name__ == "__main__":
    sys.exit(main())
