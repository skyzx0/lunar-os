# Testing

Every ISO is installed into a virtual machine and booted before it is
published. This exists because it did not, and the cost of that was several
weeks of debugging on real hardware, one failure at a time, with each
diagnosis requiring a photograph of a screen.

## What runs, and when

In the build, before the ISO is published:

| Check | Catches |
|---|---|
| `tests/test_build_script.py` | a build function called but not defined |
| `tests/test_installer.py` | a crash in the installer's own error handling |
| `tests/test_install_dryrun.py` | wrong ordering, packages that are never built |
| `tools/check-packages.py` | package names that no longer exist upstream |
| `tools/install-test.sh` | the installer, run for real against a loop device |
| `tools/boot-test.sh` | whether what it produced actually boots |
| `tools/vm-test.sh` | the live medium end to end (manual: takes about an hour) |

The first four take about a second between them. The install test takes a few
minutes and is the one that matters: it runs the real installer against a
loopback disk, then the boot test starts the disk it produced.

**Why a loop device rather than a virtual machine.** The installer needs a
block device, not a machine. A loop device is one, so partitioning, LVM,
filesystems, `pacstrap`, the chroot configuration and the boot loader all run
for real, in the container, in minutes. Installing inside an emulated machine
covered the same ground and took an hour, which is long enough that nobody
runs it and bugs reach hardware instead.

## The install test

    tools/install-test.sh 20        # inside the build container

Creates a sparse image, attaches it with `losetup -P` so partitions appear as
`/dev/loop0p1` and `p2` exactly as they would on an NVMe drive, and runs
`lunaros-setup --unattended` against it. Then it checks the result is a system
rather than a filled disk: fstab, os-release, the user account, the kernel,
the unified kernel image, the boot loader.

## The boot test

    tools/boot-test.sh out/lunar-test-disk.qcow2

Boots the disk the install test produced, with UEFI firmware, and waits for a
login prompt. It also names the failure: nothing bootable, a root that would
not mount, or a kernel panic are three different problems and the log makes
them look similar.

## The full medium test

    tools/vm-test.sh out/lunar-2026.09.05-x86_64.iso

It boots the image's kernel directly rather than through the boot loader,
because `systemd-boot` cannot be driven from a script and the unattended flag
has to reach the kernel command line. Then:

1. The live system starts and `lunar-autoinstall` sees `lunar.autoinstall` on
   the command line.
2. It runs `lunaros-setup --unattended` against `/etc/lunar/autoinstall.json`,
   installing to `/dev/vda`.
3. The machine powers off, and the script checks for `LUNAR AUTOINSTALL OK`.
4. The disk is booted on its own, with no installation medium attached, and
   the script waits for a login prompt on the serial console.

**Both halves are required.** An installer that reports success and produces a
system that does not boot has not succeeded, and that failure mode is invisible
to any check short of booting it.

Logs land in `$WORK` (`install.log` and `boot.log`) and are uploaded as build
artefacts when the test fails, so a failure can be read rather than
photographed.

## Unattended installation

`lunar-autoinstall` runs only when the kernel was booted with
`lunar.autoinstall`. There is no way to reach it from the welcome screen and
nothing on a normal boot triggers it — it erases a disk without asking.

The target can be overridden on the command line:

    lunar.autoinstall lunar.disk=/dev/sda

The answer file accepts any field of the installer's `Config`, and ignores
keys it does not recognise rather than failing on an answer file written for a
different version.

## What is still not tested

- **Real firmware.** QEMU with OVMF is not a ThinkPad's UEFI. Secure Boot
  enrolment and TPM sealing behave differently on hardware, and the test skips
  both.
- **The desktops.** The VM test installs the minimal profile. A graphical
  session starting correctly is not verified.
- **Encrypted installs.** The unattended path uses an unencrypted disk,
  because there is nowhere safe to put a passphrase in a test.

Those three are where a hardware failure is still possible. Everything below
them is now checked before an image is published.
