# How Lunar OS installs

`lunaros-setup` is the front end. **archinstall** does the installing.

## Why archinstall

Lunar used to install with its own engine: hand-written partitioning, LVM,
encryption, `pacstrap`, boot loader. It was correct in intent and kept failing
in practice, one edge case at a time over several weeks:

- a disk still held by LVM from a previous attempt
- LVM reactivating that disk the moment it was repartitioned
- device nodes that udev had not created yet
- `lvcreate` and `pacstrap` stopping on prompts nobody could see
- `systemd-firstboot` taking the console and asking for a timezone
- a package listed that was never built

Every one of those is a problem archinstall solved long ago, against real
hardware, with many more users than Lunar will ever have. It is Arch's own
installer, maintained by Arch developers and shipped on every official ISO.
Rediscovering its fixes one at a time was not a good use of anyone's time.

## What each part does

**archinstall** — partitions the disk, sets up LUKS encryption, creates the
filesystems and btrfs subvolumes, installs the packages, installs systemd-boot,
builds unified kernel images, creates the user account.

**Lunar** — everything that makes the result Lunar OS rather than Arch:

- the wizard, the half moon, the welcome screen
- `ltxs`, `lunarfetch`, `lunar-privacy`, `lunaros-setup`
- the security profiles, applied through the `lunar-hardening` package
- os-release, so the system names itself Lunar OS
- kernel hardening parameters
- masking `systemd-firstboot`

Lunar's part runs inside the installed system through archinstall's
`custom_commands`, which executes post-install in a chroot.

## One rule the Lunar layer follows

It **appends** to the kernel command line and never replaces it. archinstall
writes the parameters that unlock an encrypted disk and locate the root
filesystem into `/etc/kernel/cmdline`. Replacing that file would produce an
encrypted system that cannot find its own disk. `tests/test_archinstall_backend.py`
checks this on every build: the unlock parameters must survive, and applying
the hardening twice must change nothing.

## The configuration

`lunaros-setup` turns your choices into archinstall's two JSON files:

- `user_configuration.json` — disk layout, packages, desktop, locale, boot loader
- `user_credentials.json` — passwords, readable by root only, deleted afterwards

Passwords never enter the first file. The test checks that too.

## How the configuration is verified

The example configurations archinstall publishes lag its parser. Building from
them produced four errors the parser would have rejected or, worse, accepted:

| What the examples show | What archinstall 4 requires | Effect if wrong |
|---|---|---|
| `"sector_size": null` | `{"value": 512, "unit": "B"}` | crash before installing |
| a `Percent` size unit | whole `MiB`; there is no percent unit | crash |
| partitions without `dev_path` | the key present, even if null | crash |
| plaintext in `enc_password` | plaintext under `!password` | **installs, then nobody can log in** |

The last one is the dangerous kind: it does not fail. `enc_password` takes an
already-hashed password and stores it verbatim, so an account ends up with the
literal plaintext as its "hash". Plaintext belongs under `!password`, which
archinstall hashes with yescrypt.

These were found by running the generated configuration through archinstall's
own parser and its `--dry-run` mode against a real loop device - every desktop,
encrypted and not, ext4 and btrfs, 24 combinations - rather than by reading the
examples. `tests/test_archinstall_backend.py` now runs every configuration
through the parser on each build, so the next schema change fails in seconds.

Two further details, also from the source rather than the documentation:

- The root partition's size is computed from the real disk, because archinstall
  rejects a final partition that runs into the backup GPT header.
- `parallel_downloads` is read at the top level. Under `pacman_config` it is
  ignored, and packages download one at a time.

## The old engine

Still present, selected explicitly:

    lunaros-setup --engine lunar

Kept for comparison, not recommended.

## When something fails

archinstall keeps its own log at `/var/log/archinstall/install.log`. On a
failure, `lunaros-setup` prints the last 40 lines of it along with its own
transcript, and names both files.
