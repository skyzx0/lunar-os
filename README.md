# Lunar OS

An Arch-based distribution with its own package repository, a curses installer
called `lunar-setup`, and hardening applied at install time rather than bolted
on afterwards.

Full-disk LUKS2 encryption is mandatory. `linux-hardened` is the default kernel.
The installer offers four security profiles and four desktop options.

## Build on macOS

Everything runs inside an x86_64 Arch container; macOS only holds the source,
the finished ISO, and your signing key. Full notes and the reasons behind the
container in `docs/BUILD-MACOS.md`.

    brew install colima docker gnupg qemu
    colima start --arch x86_64 --vm-type vz --vz-rosetta \
                 --cpu 6 --memory 12 --disk 80

    make mac-doctor    # checks runtime, Rosetta, memory, disk, gpg
    make mac-genkey    # creates the repo signing key and wires it in
    make mac-iso       # builds packages then the ISO into out/
    make mac-test      # boots it in QEMU under UEFI

Docker Desktop works instead of colima, but Rosetta must be enabled under
Settings > General or the build falls back to TCG and takes over an hour.

## Build on Windows

Same idea as macOS: an x86_64 Arch container on the WSL2 backend. Full notes in
`docs/BUILD-WINDOWS.md`.

    wsl --install
    winget install Docker.DockerDesktop GnuPG.Gpg4win SoftwareFreedomConservancy.QEMU
    git config core.autocrlf input

    .\build\win.ps1 doctor    # checks WSL, Docker, memory, disk, gpg
    .\build\win.ps1 genkey    # creates the repo signing key and wires it in
    .\build\win.ps1 iso       # builds packages then the ISO into out\
    .\build\win.ps1 test      # boots it in QEMU with WHPX

`build\win.cmd` does the same from `cmd.exe`. Write the ISO with Rufus in
**DD Image** mode, not ISO mode, and not with `dd` from WSL.

Without Docker, `build\wsl.ps1` builds in a WSL2 Arch distro instead — same
result, about 15 GiB less overhead:

    .\build\wsl.ps1 doctor
    .\build\wsl.ps1 setup
    .\build\wsl.ps1 iso

## Build in CI

No local machine with 40 GiB to spare? `.github/workflows/build-iso.yml` builds
the ISO on a GitHub runner in about 25 minutes.

    gh repo create lunar-os --private --source=. --push
    gh workflow run build-iso.yml && gh run watch

CI builds are deliberately unsigned: a signing key in Actions secrets could be
used by a compromised workflow to sign packages your machines install as root.
Build there, sign on a machine you control. Details and rented-VM alternatives
in `docs/BUILD-CI.md`.

## Build on Arch

    make install-deps
    make repo          # builds and signs everything in repo/packages
    make iso           # produces out/lunar-YYYY.MM.DD-x86_64.iso

Before the first `make repo`, create a signing key and record its ID:

    gpg --full-generate-key                 # RSA 4096, no expiry
    gpg --export --armor KEYID > repo/packages/lunar-keyring/lunar.gpg
    echo KEYID > repo/signing-key.txt
    echo KEYID:4: > repo/packages/lunar-keyring/lunar-trusted
    : > repo/packages/lunar-keyring/lunar-revoked

Test the ISO before writing it to hardware:

    qemu-system-x86_64 -enable-kvm -m 4096 -smp 4 \
      -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd \
      -drive if=pflash,format=raw,file=OVMF_VARS.4m.fd \
      -cdrom out/lunar-*.iso -drive file=test.qcow2,if=virtio

## Layout

    archiso/lunar/          live medium profile consumed by mkarchiso
    lunar-setup/            the installer (Python, stdlib only, curses UI)
      lunar_setup/profiles.py    desktop and security profile definitions
      lunar_setup/disk.py        GPT, LUKS2, LVM, btrfs subvolumes
      lunar_setup/hardening.py   every config file the profiles write
      lunar_setup/install.py     pacstrap, chroot config, UKI, Secure Boot
      lunar_setup/__main__.py    the wizard
    repo/                   PKGBUILDs and the signing/publishing script
    build/                  container build path used by macOS and Windows
    hardening/              the same configs as standalone files, shipped
                            in the lunar-hardening package
    docs/SECURITY.md        threat model and what the profiles do not cover
    docs/BUILD-MACOS.md     building from macOS, and the traps in doing so
    docs/BUILD-WINDOWS.md   building from Windows, same
    docs/BUILD-CI.md        building on GitHub Actions or a rented VM
    docs/PERFORMANCE.md     what it actually idles at, and why
    branding/               boot splash artwork and Plymouth theme

The files under `hardening/etc/` are generated from `hardening.py` so the
installer and the package can never drift apart. Regenerate them after editing
that module.

## Live session

The medium boots straight into a Plasma session with a black half-moon splash,
autologin as an unprivileged `lunar` user with no password, and a welcome
window offering the guided installer, a terminal installer, or the manual
command sequence.

## Installer

    lunar-setup                      interactive
    lunar-setup --steps              print the manual installation commands
    lunar-setup --memory             report memory use, to check the claims
    lunar-setup --unattended a.json  answer file, same keys as Config
    lunar-setup --reapply            re-apply the profile on a running system

The wizard writes nothing until the review screen is confirmed. Esc at any step
goes back.

## Disk layout produced

    /dev/sdX1  1 GiB   ESP, holds the signed unified kernel image
    /dev/sdX2  rest    LUKS2 -> LVM "lunar" -> lv root, lv swap

With btrfs: subvolumes `@`, `@home`, `@var`, `@log`, `@pkg`, `@snapshots`,
mounted with `nodev,nosuid` and `noexec` where it does not break anything.

## Security profiles

| Profile | Adds |
|---|---|
| Baseline | hardened kernel, AppArmor, LUKS2, default-deny inbound |
| Hardened | Secure Boot with your keys, USBGuard, auditd, hardened_malloc |
| Paranoid | lockdown=confidentiality, egress filtering, Firejail, TPM2 unlock |
| Onion | transparent Tor routing, IPv6 off |

Read `docs/SECURITY.md` before choosing Onion. It is not Whonix and it does not
protect against the things Whonix protects against.

## Status

Nothing here has been booted on real hardware yet. The disk and boot paths are
destructive by nature; test in a VM with OVMF and a throwaway qcow2 first.
