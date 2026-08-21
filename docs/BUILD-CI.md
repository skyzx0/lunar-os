# Building without a local machine

If your own machine cannot spare 40 GiB, the build runs fine on someone else's.
Every option here is a Linux host with Docker, which is the only thing the build
actually requires.

## GitHub Actions

`.github/workflows/build-iso.yml` builds the ISO on a hosted runner.

    git init && git add -A && git commit -m "initial"
    gh repo create lunar-os --private --source=. --push

Then run it from the Actions tab, or:

    gh workflow run build-iso.yml
    gh run watch

Roughly 25 minutes. The ISO is uploaded as a build artifact, and attached to a
GitHub Release if you tick **publish** or push a `v*` tag.

Things worth knowing before you rely on it:

- **Disk.** Hosted runners have about 21 GiB free and `mkarchiso` wants 25. The
  workflow deletes the preinstalled .NET, Android, GHC and JVM toolchains first,
  which frees roughly 25 GiB. If a future package set grows the ISO, this is the
  step that breaks.
- **Artifact storage.** The free plan includes 500 MB of Actions storage, and
  the ISO is larger than that. The artifact will fail to upload or evict older
  ones. Releases do not count against that quota, so use the release path for
  anything you want to keep.
- **Private repositories consume minutes.** 2000 per month on the free plan;
  each build is about 25. Public repositories are unmetered.
- **Timeout.** Set to 120 minutes. A normal build is well inside that.

## Why CI builds are unsigned

The workflow runs `repo-unsigned` deliberately. Putting the repository signing
key into Actions secrets would mean a compromised workflow file, a compromised
third-party action, or GitHub itself could sign packages that your machines
install with root privileges. That is a strictly worse position than having no
signing at all, because `SigLevel = Required` would then be telling you
something false.

The correct split: build in CI, sign on a machine you control.

    gh run download --name lunar-iso
    # or fetch the packages, not just the ISO, from a repo-unsigned run

    for p in out/repo/lunar/os/x86_64/*.pkg.tar.zst; do gpg --detach-sign "$p"; done
    gpg --detach-sign out/repo/lunar/os/x86_64/lunar.db.tar.zst

An unsigned ISO is fine for testing in a VM. Do not install it on hardware you
care about and then point pacman at an unsigned repository.

## A rented VM

Often simpler than CI, and the only option if you want to iterate rather than
push a commit for every attempt. Any x86_64 Linux VM with 4 GB RAM and 60 GB
disk works. A Hetzner CX22 or equivalent runs a few euro a month and can be
destroyed the moment the ISO is downloaded.

    # on the VM
    sudo pacman -Syu --needed archiso git      # if Arch
    git clone <your repo> && cd lunar-os
    make repo && make iso

    # from your machine
    scp user@vm:~/lunar-os/out/lunar-*.iso .

On a Debian or Ubuntu VM, use the container path instead:

    ./build/mac.sh image     # the script is macOS-flavoured but the
    ./build/mac.sh iso       # container commands work on any Linux host

This is also the answer for Windows on ARM, where local x86_64 emulation is too
slow to be worth attempting.

## What does not work

- **GitHub Codespaces and most hosted dev containers.** `mkarchiso` needs
  `--privileged` for its bind mounts and chroots, and nested privileged
  containers are not available there.
- **WSL on a full disk.** Freeing space is not optional; the build fails
  partway and strands a 20 GiB work directory inside a virtual disk that does
  not shrink when you delete it.
- **Anything without a real Linux kernel.** There is no path to building this
  that does not involve `pacstrap` and `chroot` somewhere.
