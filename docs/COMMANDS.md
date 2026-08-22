# Lunar OS commands

Four commands, each doing something the underlying tool does not. Renaming
`pacman` to feel distinctive would be a cost with no benefit; these exist
because they add checks, context, or recovery.

`pacman`, `systemctl` and everything else remain available and unmodified.

## lum - packages

    lum get <pkg>      install, taking a btrfs snapshot first
    lum drop <pkg>     remove, refusing to orphan the boot chain
    lum up             upgrade, with a snapshot and a CVE report after
    lum sync           refresh databases
    lum find <term>    search, marking what is already installed
    lum show <pkg>     details
    lum tree <pkg>     dependency tree
    lum why <pkg>      explain why something is installed
    lum audit          known vulnerabilities in what you have
    lum orphans        packages nothing depends on
    lum big            what is actually using the disk
    lum clean          drop cached packages, keeping the last two
    lum rollback       list snapshots and how to restore one
    lum verify         check installed files against their packages

What it adds over `pacman`:

- **Snapshots before every change.** An upgrade that breaks the boot chain is
  a thirty-second recovery with a snapshot and a reinstall without one.
- **A refusal list.** `lum drop systemd` stops and explains. `pacman -R` does
  it, and you find out at the next reboot.
- **CVE reporting after upgrades**, so "up to date" means something checkable.
- **`lum why`**, which answers the question `pacman -Qi` makes you infer.
- **`lum verify`**, which reads every installed file and reports what differs
  from its package. Modified configuration is normal; modified binaries are not.

## lunarfetch - what this machine is

Runs in a few milliseconds, reads `/proc` and `/sys` directly rather than
shelling out. Beyond the usual kernel and uptime it reports the four things
that matter on this distribution, because a fetch tool here should answer
whether the machine is doing what it claims:

    Mandatory access   AppArmor enforcing
    Kernel lockdown    confidentiality
    Secure Boot        enabled
    Root encryption    LUKS2

It runs once per login session, not per terminal. A fetch tool that fires in
every new tab gets uninstalled within a week.

## lunar-setup - installation and hardening

    lunar-setup                  guided installer
    lunar-setup --steps          print the manual commands
    lunar-setup --memory         report memory use
    lunar-setup --reapply        re-apply the security profile
    lunar-setup --unattended F   install from an answer file

## lunar-diagnose - when the desktop does not start

Live medium only. Collects failed units, display manager status, this boot's
errors and the graphics situation in one output.

## Deliberately not renamed

`systemctl`, `journalctl`, `nft`, `cryptsetup`, `sbctl`. Every one of these
has documentation, forum answers and manual pages that a Lunar-specific alias
would cut you off from. A distribution that renames standard tools makes its
users harder to help.
