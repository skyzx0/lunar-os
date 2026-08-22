# Memory and footprint

## What Plasma actually idles at

Measured as `MemTotal - MemAvailable` on a freshly booted, logged-in desktop
with nothing open. Run `lunar-setup --memory` to reproduce it.

| Configuration | Idle |
|---|---|
| Plasma 6 Wayland, stock Arch | 750 – 950 MB |
| Plasma 6 with the tuning below | 550 – 680 MB |
| Hyprland profile | 330 – 420 MB |
| Minimal profile, no graphical stack | 130 – 190 MB |

**300 MB is not reachable with Plasma.** Not with configuration, not with
service masking, not by removing components. The floor is set by what the
session needs to run at all: `kwin_wayland` alone is 180–260 MB with software
rendering, `plasma-shell` another 200–280 MB, and `systemd`, `dbus`,
`NetworkManager`, `pipewire` and the display manager account for most of the
rest. Removing enough to reach 300 MB means removing the desktop.

If sub-400 MB matters more than Plasma does, choose Hyprland in the installer.
That is the honest trade, and it is why the choice exists.

Two further cautions about the numbers above. They assume software rendering;
with a real GPU driver, `kwin_wayland` drops considerably but the driver's own
allocations partly offset it. And figures published by other distributions are
frequently measured differently — immediately after boot before the session has
settled, or as `free -m` "used" excluding reclaimable slab. Compare
`MemTotal - MemAvailable` or you are comparing nothing.

## What the tuning does

**zram instead of disk swap.** Compressed swap in RAM, sized at half of memory,
zstd. Typically 3:1 on desktop working sets. It also means swapped pages are
never written anywhere an attacker can read later, which is why it is on even
where memory is plentiful.

**`vm.swappiness = 180`.** Correct with zram and wrong without it. When swap is
compressed RAM, moving pages there is cheap and should happen eagerly; when it
is a disk, the same setting causes stalls. If you disable zram, put swappiness
back to 60.

**Baloo off.** The file indexer costs 150–250 MB resident and continuous I/O.
On the live medium it indexes a read-only image it will never see again.

**Blur and background-contrast effects off.** The two most expensive desktop
effects, and the first things that hurt under software rendering.

**`systemd-oomd`, `packagekit`, `man-db` masked on the live medium.** Masked
rather than disabled so a dependency cannot pull them back in.

**Not `plasma-meta`.** The metapackage pulls the full KDE application suite —
roughly doubling the image for software nobody opens from a live session. Lunar
ships the desktop, the network and audio applets, and a terminal.

## Measuring it yourself

    lunar-setup --memory

Reports total, available, in-use and the largest processes by RSS. RSS
double-counts shared libraries, so the process column sums to more than the
in-use figure; compare the in-use figure across systems, not the process list.

For a breakdown that accounts for sharing properly:

    sudo smem -tk -c "pss uss command" | tail -20

## Where the remaining weight is

If you want to push further, in order of return:

1. **Swap Plasma for Hyprland.** Worth 200–300 MB, more than everything else
   combined.
2. **Drop SDDM**, log in on a TTY and start the session manually. Worth 40–70 MB
   and costs you a graphical login.
3. **Drop `pipewire`** if you do not need audio. Worth 30–50 MB.
4. **Build without `systemd-resolved`** and use a static `/etc/resolv.conf`.
   Worth 15–25 MB, and loses DNS-over-TLS — a bad trade on a distribution whose
   point is not leaking DNS.

Steps 3 and 4 are listed for completeness rather than as recommendations.
