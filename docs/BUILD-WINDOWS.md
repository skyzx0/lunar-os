# Building Lunar OS on Windows

Windows cannot build this natively. `mkarchiso` needs `pacstrap`, bind mounts
and a chroot, and the resulting rootfs needs a case-sensitive filesystem that
carries Unix ownership and setuid bits. Everything runs inside an x86_64 Arch
container on the WSL2 backend. Windows holds the source, the finished ISO, and
your signing key — nothing else.

## One-time setup

In an elevated PowerShell:

    wsl --install
    winget install Docker.DockerDesktop
    winget install GnuPG.Gpg4win
    winget install SoftwareFreedomConservancy.QEMU

Start Docker Desktop and confirm **Settings > General > Use the WSL 2 based
engine** is on. The Hyper-V backend also works, but it is slower and its virtual
disk grows without ever shrinking.

Give the WSL VM enough headroom. Create `%USERPROFILE%\.wslconfig`:

    [wsl2]
    memory=12GB
    processors=6
    swap=8GB

Then `wsl --shutdown` so it takes effect.

If you cloned with Git, stop it rewriting line endings:

    git config core.autocrlf input

Then:

    .\build\win.ps1 doctor      # checks WSL, Docker, memory, disk, gpg
    .\build\win.ps1 genkey      # creates the repo signing key, wires it in
    .\build\win.ps1 image       # builds the Arch build container

`build\win.cmd` is a shim for the same thing from `cmd.exe`, so you do not have
to fight the execution policy.

## Building

    .\build\win.ps1 check       # lint, compile the installer, verify package sets
    .\build\win.ps1 repo        # build and sign every package -> out\repo\
    .\build\win.ps1 iso         # repo, then the ISO -> out\lunar-*.iso
    .\build\win.ps1 test        # boot the ISO in QEMU with WHPX acceleration
    .\build\win.ps1 shell       # poke around inside the build container

Expect roughly 20 minutes for a first ISO on a reasonable x86_64 laptop, most of
it downloading packages.

## Writing to a USB stick

Do not use `dd` from WSL. WSL2 does not pass raw USB block devices through, and
what looks like it worked will produce a stick that does not boot.

Use **Rufus** and pick **DD Image** mode when it asks — ISO mode rewrites the
boot structure and breaks the UEFI path. Balena Etcher and Ventoy both work too;
Ventoy is the least destructive option if you want other ISOs on the same stick.

## Why the build happens in a container volume

The container rsyncs `/src` into a Docker volume before building rather than
working in the mounted Windows directory. Two reasons, both of which produce
silent corruption rather than a clear error:

- **NTFS is case-insensitive by default.** Arch packages ship files that differ
  only in case. Extraction quietly overwrites them and you get an ISO that boots
  into a broken userland, with no failure at build time. Per-directory case
  sensitivity via `fsutil file setCaseSensitiveInfo` exists but does not
  propagate to files created later, so it cannot be relied on.
- **The 9p mount does not carry ownership, setuid bits or extended
  attributes.** Every file arrives owned by the container user, so `sudo` in the
  built image ends up non-setuid and file capabilities are lost.

Only `out\` is bind-mounted, and only finished artefacts are written there.

## Line endings

If Git handed the tree CRLF endings, `#!/usr/bin/env bash` becomes
`bash^M` and the error you get — `bad interpreter` — names a file that looks
perfectly fine in an editor. The container strips CRs from shell scripts,
PKGBUILDs and config files during the copy, so builds work either way, but
`.gitattributes` in the repository root pins everything to LF and
`core.autocrlf input` keeps your diffs clean.

## Signing

`%APPDATA%\gnupg` is mounted read-only into the container so `makepkg --sign`
can use your key without it ever entering an image layer. Gpg4win's `gpg-agent`
socket is not forwarded, so if your key needs a pinentry prompt or lives on a
smartcard, signing inside the container will fail. Build unsigned and sign on
the Windows side instead:

    .\build\win.ps1 shell
    # inside: cd /build/src && ./repo/build-repo.sh --no-sign

    # back in PowerShell:
    Get-ChildItem out\repo\lunar\os\x86_64\*.pkg.tar.zst |
        ForEach-Object { gpg --detach-sign $_.FullName }
    gpg --detach-sign out\repo\lunar\os\x86_64\lunar.db.tar.zst

Keep the private key off the machine that serves the repository. See
`docs/SECURITY.md`.

## Building without Docker

`build\wsl.ps1` does the same job using WSL2 directly. WSL2 runs a real Linux
kernel with loop device and chroot support, which is all `mkarchiso` needs, so
Docker Desktop is not required at all.

    .\build\wsl.ps1 doctor    # checks WSL, disk space, distro readiness
    .\build\wsl.ps1 setup     # installs an Arch distro and its build deps
    .\build\wsl.ps1 iso       # builds packages then the ISO into out\
    .\build\wsl.ps1 shell     # a shell inside the build distro

Trade-offs against the container path:

- **Less disk overhead.** No Docker Desktop, no second VM, no `ext4.vhdx` that
  only ever grows. Roughly 15 GiB lighter overall.
- **Less isolation.** The build tooling lives in a distro you keep, so a broken
  `pacman -Syu` is yours to fix rather than something you throw away and rebuild
  with `docker build`.
- **Slightly less predictable.** WSL is not a normal Linux environment. It
  rewrites `/etc/resolv.conf` on every start, which breaks `pacstrap`'s ability
  to resolve mirrors inside the target chroot; `wsl-setup.sh` pins the file and
  makes it immutable. If a build fails in a way the container path does not,
  that difference is the first place to look.

The source is copied onto the distro's ext4 filesystem before building, for the
same case-sensitivity and ownership reasons described above. Never build from
`/mnt/c/...`.

If C: is short on space, move the build distro to another drive:

    .\build\wsl.ps1 move D:\wsl

That exports, unregisters and re-imports the distro. If the re-import fails the
export tarball is left in `%TEMP%`, so nothing is lost.

## "Docker is not installed" when it plainly is

Docker Desktop does not register its CLI until you launch the app once, and
PowerShell captures `PATH` when the window opens. So the usual cause is a stale
shell, not a missing install.

1. Launch **Docker Desktop** from the Start menu. Accept the EULA and wait for
   the whale icon to report "Engine running". First run may want a reboot.
2. Close the PowerShell window and open a new one. Refreshing `PATH` in the
   existing session will not happen on its own.
3. `.\build\win.ps1 doctor` again.

`doctor` falls back to the standard install directories and will use
`docker.exe` from there for the current run, telling you what it did. To make it
permanent:

    setx PATH "%PATH%;C:\Program Files\Docker\Docker\resources\bin"

The QEMU installer has the same habit and never touches `PATH` at all. Only
`test` needs it:

    setx PATH "%PATH%;C:\Program Files\qemu"

## Known friction

- **Windows on ARM.** There is no Rosetta equivalent. x86_64 containers run
  under qemu-user emulation, and an ISO build takes hours when it does not fall
  over on an unimplemented instruction mid-compile. Borrow an x86_64 machine or
  a cloud VM for the length of the build.
- **Docker Desktop's virtual disk only grows.** After a few ISO builds
  `ext4.vhdx` will be tens of gigabytes. `.\build\win.ps1 clean` drops the build
  volume; reclaiming the space from the VHDX itself needs
  `wsl --shutdown` followed by `Optimize-VHD` or `diskpart compact vdisk`.
- **Antivirus scanning the Docker volume** can double build times. Excluding
  `%LOCALAPPDATA%\Docker` from real-time scanning helps, at the obvious cost.
- **WHPX and other hypervisors conflict.** If VirtualBox or VMware is installed,
  `.\build\win.ps1 test` may refuse to start. WSL2 requires the Windows
  hypervisor platform; the two cannot both own the CPU.
