# Building Lunar OS on macOS

macOS cannot build this natively. `mkarchiso` needs `pacstrap`, bind mounts and
a chroot, and the target rootfs needs a case-sensitive filesystem that carries
Unix ownership. Everything therefore runs inside an x86_64 Arch container; the
only things that touch macOS are the source tree, the finished ISO, and your
GPG key.

## One-time setup

    brew install colima docker gnupg qemu

    colima start --arch x86_64 --vm-type vz --vz-rosetta \
                 --cpu 6 --memory 12 --disk 80

Docker Desktop works too. Enable **Settings > General > Use Rosetta for
x86_64/amd64 emulation** — without it the ISO build falls back to TCG and takes
well over an hour instead of a few minutes.

Then:

    ./build/mac.sh doctor      # verifies runtime, Rosetta, memory, disk, gpg
    ./build/mac.sh genkey      # creates the repo signing key, wires it in
    ./build/mac.sh image       # builds the Arch build container

## Building

    ./build/mac.sh check       # lint, compile the installer, verify package sets
    ./build/mac.sh repo        # build and sign every package -> out/repo/
    ./build/mac.sh iso         # repo, then the ISO -> out/lunar-*.iso
    ./build/mac.sh test        # boot the ISO in QEMU under UEFI
    ./build/mac.sh shell       # poke around inside the build container

## Writing to a USB stick

`dd` on macOS uses different device names and flags than the Linux instructions
in the README:

    diskutil list                          # find the disk, e.g. disk4
    diskutil unmountDisk /dev/disk4
    sudo dd if=out/lunar-*.iso of=/dev/rdisk4 bs=4m status=progress
    diskutil eject /dev/disk4

Note `rdisk4`, not `disk4` — the raw device is roughly ten times faster. Confirm
the disk number twice; `dd` will happily overwrite your system drive.

## Why the build happens in a volume, not a bind mount

The container copies `/src` into a Docker volume before building. Bind-mounting
the macOS filesystem directly into `pacstrap` produces a broken rootfs for two
reasons:

- **APFS is case-insensitive by default.** Arch packages ship files that differ
  only in case. Extraction silently overwrites them, and you get an ISO that
  boots to a broken userland with no error at build time.
- **The bind mount does not preserve ownership, setuid bits or xattrs.** Every
  file lands owned by whatever the container user is, so `sudo` ends up
  non-setuid and capabilities are lost.

Only `out/` is bind-mounted, and only finished artefacts are written there.

## Signing

`~/.gnupg` is mounted read-only into the container so `makepkg --sign` can use
your key without it ever being baked into an image layer. That does mean the
passphrase prompt appears inside the container; if you use a hardware key or
`pinentry-mac`, the socket will not be forwarded and signing will fail. In that
case, build unsigned and sign on the host afterwards:

    ./build/mac.sh shell
    # inside: cd /build/src && ./repo/build-repo.sh --no-sign

    # back on macOS:
    for p in out/repo/lunar/os/x86_64/*.pkg.tar.zst; do gpg --detach-sign "$p"; done
    gpg --detach-sign out/repo/lunar/os/x86_64/lunar.db.tar.zst

Keep the private key off the machine that serves the repository. See
`docs/SECURITY.md`.

## Skipping the local build entirely

On Apple Silicon, CI is often the better option: GitHub's runners are native
x86_64 Linux, so a build there is faster than one on your own machine going
through Rosetta, and it needs nothing installed locally.

    brew install gh && gh auth login
    git init && git add -A && git commit -m "initial"
    gh repo create lunar-os --private --source=. --push
    gh workflow run build-iso.yml && gh run watch
    gh run download --name lunar-iso

Then test the downloaded ISO locally with `./build/mac.sh test`. Full details
and the signing caveat in `docs/BUILD-CI.md`.

Do not switch the workflow to a `macos-*` runner. They have no Docker and no
nested virtualisation, so `mkarchiso` cannot run on them.

## Known friction on Apple Silicon

- Rosetta does not implement AVX-512. Nothing in the build path uses it, but a
  package added later might; the symptom is an illegal instruction fault during
  `makepkg`, not a clear error message.
- `build/mac.sh test` runs an x86_64 guest with no hardware acceleration, since
  Rosetta accelerates processes, not full VMs. It is fast enough to click
  through the installer and slow enough that you will not enjoy using the result.
  For a realistic test, write the ISO to a USB stick and boot real hardware.
- Colima occasionally loses the Rosetta binfmt registration after a host reboot.
  `colima restart` fixes it; `doctor` will tell you when it has happened.
