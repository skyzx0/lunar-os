# Lunar OS security model

## What each profile actually defends against

| Threat | Baseline | Hardened | Paranoid | Onion |
|---|---|---|---|---|
| Stolen laptop, powered off | yes | yes | yes | yes |
| Stolen laptop, suspended (keys in RAM) | no | no | partial | partial |
| Malicious USB device plugged in while unattended | no | yes | yes | yes |
| Tampered boot chain (evil maid) | no | partial | partial | partial |
| Remote network attack on an exposed service | yes | yes | yes | yes |
| Malware already running as your user | no | partial | partial | partial |
| Kernel privilege escalation exploit | partial | partial | yes | yes |
| Network observer learning which sites you visit | no | no | no | yes |
| Global adversary correlating traffic | no | no | no | no |

## Mechanisms

**Disk.** LUKS2, aes-xts-plain64 with a 512-bit key, argon2id at 1 GiB memory
cost and a 5-second iteration target. That cost is deliberate: it makes GPU and
ASIC passphrase cracking expensive rather than merely annoying. Swap sits inside
the same container, so hibernation images are encrypted too.

**Boot.** Kernel, initramfs, microcode and command line are combined into one
unified kernel image and signed with keys generated on your machine by `sbctl`.
With Secure Boot enforcing, an attacker cannot swap in a modified initramfs
without breaking the signature. The ESP itself is still unencrypted and
writable by anyone with physical access — Secure Boot detects tampering, it does
not prevent it.

**Kernel.** `linux-hardened` by default, with `linux-lts` installed as a
fallback entry. Full speculative-execution mitigations including `nosmt`, which
costs real performance on multithreaded workloads. Module signature enforcement,
`lockdown=integrity` (Hardened) or `confidentiality` (Paranoid and above),
`init_on_alloc`/`init_on_free`, kstack randomisation, and an aggressive module
blacklist covering obscure network protocols, rare filesystems and
DMA-capable buses.

**Userspace.** `hardened_malloc` preloaded system-wide. AppArmor with cached
profiles. Firejail defaults on Paranoid and above. Flatpak with portals for
anything that does not need host access. umask 077 and `HOME_MODE 0700`.

**Network.** nftables with a default-drop input chain and rate-limited ICMP.
Paranoid and Onion add default-drop egress, so an implant cannot phone home over
an unusual port without you noticing the log lines. DNS goes over TLS to Quad9
with DNSSEC validation; mDNS and LLMNR are off. MAC randomisation and IPv6
privacy extensions are on for Wi-Fi.

## Where the claims stop

These are the parts worth knowing before you trust it with anything real.

**AppArmor, not SELinux.** You asked for SELinux in the profile options. Arch
does not ship a working SELinux policy — enabling it means patching `pam`,
`coreutils`, `shadow` and `systemd` from the AUR and maintaining a policy
yourself, and one upstream update can leave you with an unbootable machine. The
honest engineering answer is that AppArmor with real, maintained profiles beats
SELinux with a policy nobody is auditing. If you want mandatory access control
with a policy that is genuinely maintained, that argues for Fedora or a
Whonix-style layered design, not Arch.

**Onion mode is not Whonix.** Transparent Tor routing on a single host means the
Tor process and your applications share a kernel. Any local privilege escalation
or kernel bug deanonymises you completely, because the same machine knows both
your real IP and your Tor circuits. Whonix and Tails put the Tor gateway on a
separate machine or a read-only amnesic system for exactly this reason. Use
Onion mode to resist a curious ISP; do not use it if being identified would put
you in danger.

**Rolling release versus stability.** Arch does not do security backports; it
does version bumps. You get fixes fast, and you also get regressions fast. A
hardened kernel plus a rolling base means you will eventually boot into a
machine that does not work. The btrfs snapshot layout exists for that morning.

**Your own repo is now your own attack surface.** Anything installed from
`repo.lunaros.org` is trusted with root at install time. The signing key must
live somewhere other than the build machine and other than the web server. If
you sign packages on the same box that serves them, the repo adds risk rather
than removing it.

**Secure Boot with your own keys locks out other operating systems.** Enrolling
custom keys without `--microsoft` will brick option ROMs on some hardware and
prevent Windows from booting. The installer passes `--microsoft` for this
reason; that also means Microsoft's signing key stays trusted, which is a real
weakening, and it is the pragmatic choice on consumer laptops.

**Some hardening is profile-gated, on purpose.** Three settings break real
machines rather than merely inconveniencing them, so they apply only on
Paranoid and Onion:

- `module.sig_enforce=1` refuses every out-of-tree driver. That means no
  NVIDIA, no Broadcom wireless, no VirtualBox. On a machine that needs one of
  those it is not hardening, it is a brick.
- `nosmt` disables hyperthreading and roughly halves multithreaded
  throughput. It closes real cross-thread attacks, and is worth that cost only
  when those attacks are in your threat model.
- `iommu=force` is not used at all. It prevents some machines from booting,
  and adds little over `intel_iommu=on` / `amd_iommu=on`, which are always set.

There is also no `hidepid` entry for `/proc` in fstab. systemd mounts `/proc`
before fstab is read, and an entry it disagrees with drops the machine into
emergency mode at boot. Process visibility is restricted per service with
`ProtectProc` instead, which cannot make the system unbootable.

**UEFI only.** The install medium has no BIOS boot path. Signed unified kernel
images, Secure Boot enrolment and TPM2 sealing all require UEFI, so a machine
that can only boot BIOS cannot run the installed system regardless. Offering a
BIOS live medium would just move the failure later.

**Suspend leaks keys.** Nothing here clears the LUKS master key from RAM on
suspend. If the threat is someone taking the machine while it is asleep,
configure hibernation instead of suspend, or shut down.

## Auditing your install

    sudo lynis audit system
    arch-audit
    sudo aa-status
    sudo nft list ruleset
    sbctl status
    sudo usbguard list-devices
