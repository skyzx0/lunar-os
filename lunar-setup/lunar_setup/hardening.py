"""Applies a SecurityProfile to the freshly pacstrapped system at /mnt.

Everything here is idempotent and file-based so the same code path can be
re-run later by `lunar-setup --reapply` on a running system.
"""

import os
import subprocess

ROOT = "/mnt"


def chroot(cmd, log=None, check=True):
    if log:
        log("  # " + cmd)
    return subprocess.run(["arch-chroot", ROOT, "bash", "-c", cmd],
                          check=check, text=True, capture_output=True)


def write(path: str, content: str, mode: int = 0o644, log=None) -> None:
    full = os.path.join(ROOT, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(content.lstrip("\n"))
    os.chmod(full, mode)
    if log:
        log(f"  + {path}")


# --------------------------------------------------------------------------


def kernel_cmdline(profile, luks_uuid: str) -> str:
    parts = [
        f"rd.luks.name={luks_uuid}=lunarcrypt",
        "rd.luks.options=discard,no-read-workqueue,no-write-workqueue",
        "root=/dev/lunar/root",
        "resume=/dev/lunar/swap",
        "rw",
        "quiet",
        "loglevel=3",
        # memory hygiene
        "init_on_alloc=1",
        "init_on_free=1",
        "page_alloc.shuffle=1",
        "slab_nomerge",
        "randomize_kstack_offset=on",
        "vsyscall=none",
        # speculative execution: do not let the kernel trade safety for speed
        "mitigations=auto,nosmt",
        "spectre_v2=on",
        "spec_store_bypass_disable=on",
        "l1tf=full,force",
        "mds=full,nosmt",
        "tsx=off",
        "tsx_async_abort=full,nosmt",
        # DMA and firmware
        "iommu=force",
        "intel_iommu=on",
        "amd_iommu=force_isolation",
        "efi=disable_early_pci_dma",
        "debugfs=off",
        "module.sig_enforce=1",
    ]
    if profile.apparmor:
        parts += ["lsm=landlock,lockdown,yama,integrity,apparmor,bpf",
                  "apparmor=1", "security=apparmor"]
    if profile.lockdown:
        parts.append(f"lockdown={profile.lockdown}")
    if profile.disable_ipv6:
        parts.append("ipv6.disable=1")
    return " ".join(parts)


def sysctl(profile) -> str:
    return f"""
# Managed by lunar-setup. Edit /etc/sysctl.d/99-lunar-local.conf instead.

# --- kernel -------------------------------------------------------------
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.printk = 3 3 3 3
kernel.unprivileged_bpf_disabled = 1
net.core.bpf_jit_harden = 2
kernel.yama.ptrace_scope = {"3" if profile.lockdown == "confidentiality" else "2"}
kernel.kexec_load_disabled = 1
kernel.sysrq = 4
kernel.perf_event_paranoid = 3
kernel.randomize_va_space = 2
kernel.core_pattern = |/bin/false
dev.tty.ldisc_autoload = 0
vm.unprivileged_userfaultfd = 0
fs.protected_symlinks = 1
fs.protected_hardlinks = 1
fs.protected_fifos = 2
fs.protected_regular = 2
fs.suid_dumpable = 0

# --- network ------------------------------------------------------------
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_rfc1337 = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.icmp_echo_ignore_all = 1
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_ra = 0
net.ipv6.conf.all.use_tempaddr = 2
net.ipv6.conf.default.use_tempaddr = 2
"""


def blacklist() -> str:
    """Attack surface that a laptop or workstation has no business exposing."""
    mods = [
        # obscure network protocols
        "dccp", "sctp", "rds", "tipc", "n-hdlc", "ax25", "netrom", "x25",
        "rose", "decnet", "econet", "af_802154", "ipx", "appletalk", "psnap",
        "p8023", "p8022", "can", "atm",
        # rare filesystems that are historically CVE farms
        "cramfs", "freevxfs", "jffs2", "hfs", "hfsplus", "squashfs", "udf",
        "cifs", "nfs", "nfsv3", "nfsv4", "ksmbd", "gfs2",
        # thunderbolt / firewire DMA
        "firewire-core", "firewire-ohci", "firewire-sbp2", "thunderbolt",
        # misc
        "vivid", "bluetooth", "btusb", "uvcvideo",
    ]
    lines = "\n".join(f"install {m} /bin/false\nblacklist {m}" for m in mods)
    return "# Managed by lunar-setup.\n" + lines + "\n"


def nftables(profile) -> str:
    egress = """
        # Paranoid/Onion: deny by default, allow only what is declared.
        ct state established,related accept
        oif "lo" accept
        udp dport 53 accept
        tcp dport { 53, 80, 443, 853 } accept
        udp dport { 123, 443 } accept
        counter log prefix "lunar-egress-drop " drop
""" if profile.nftables_egress_filter else """
        ct state established,related accept
        accept
"""
    return f"""
#!/usr/bin/nft -f
# Managed by lunar-setup. Local rules: /etc/nftables.d/*.nft

flush ruleset

table inet lunar {{
    chain input {{
        type filter hook input priority filter; policy drop;

        ct state invalid drop
        ct state established,related accept
        iif "lo" accept

        # Rate-limited ICMP: keep PMTU working without becoming a beacon.
        ip protocol icmp icmp type {{ destination-unreachable, time-exceeded,
                                     parameter-problem }} limit rate 4/second accept
        ip6 nexthdr icmpv6 icmpv6 type {{ destination-unreachable, packet-too-big,
                                         time-exceeded, parameter-problem,
                                         nd-neighbor-solicit, nd-neighbor-advert }} accept

        counter drop
    }}

    chain forward {{
        type filter hook forward priority filter; policy drop;
        counter drop
    }}

    chain output {{
        type filter hook output priority filter; policy {
            "drop" if profile.nftables_egress_filter else "accept"};
{egress}
    }}
}}

include "/etc/nftables.d/*.nft"
"""


def resolved_conf(profile) -> str:
    return """
[Resolve]
DNS=9.9.9.9#dns.quad9.net 149.112.112.112#dns.quad9.net
FallbackDNS=1.1.1.1#cloudflare-dns.com
DNSOverTLS=yes
DNSSEC=yes
MulticastDNS=no
LLMNR=no
Cache=yes
"""


def pam_faillock() -> str:
    return """
# Managed by lunar-setup.
deny = 5
unlock_time = 900
fail_interval = 900
even_deny_root
root_unlock_time = 1200
"""


def pwquality() -> str:
    return """
# Managed by lunar-setup.
minlen = 12
minclass = 3
maxrepeat = 3
usercheck = 1
enforcing = 1
dictcheck = 1
"""


def networkmanager_privacy(profile) -> str:
    if not profile.mac_randomisation:
        return ""
    return """
[device-mac-randomization]
wifi.scan-rand-mac-address=yes

[connection-mac-randomization]
ethernet.cloned-mac-address=stable
wifi.cloned-mac-address=random

[connection]
ipv6.ip6-privacy=2
"""


def apply(cfg, luks_part_uuid: str, log=None) -> None:
    p = cfg.profile_obj()

    write("/etc/sysctl.d/99-lunar-hardening.conf", sysctl(p), log=log)
    write("/etc/modprobe.d/lunar-blacklist.conf", blacklist(), log=log)
    write("/etc/nftables.conf", nftables(p), mode=0o700, log=log)
    os.makedirs(f"{ROOT}/etc/nftables.d", exist_ok=True)
    write("/etc/systemd/resolved.conf.d/lunar.conf", resolved_conf(p), log=log)
    write("/etc/security/faillock.conf", pam_faillock(), log=log)
    write("/etc/security/pwquality.conf", pwquality(), log=log)
    write("/etc/kernel/cmdline", kernel_cmdline(p, luks_part_uuid) + "\n", log=log)

    if nm := networkmanager_privacy(p):
        write("/etc/NetworkManager/conf.d/99-lunar-privacy.conf", nm, log=log)

    # umask 077 for every login shell and systemd user unit
    write("/etc/profile.d/lunar-umask.sh", "umask 077\n", mode=0o755, log=log)
    chroot("sed -i 's/^UMASK.*/UMASK 077/' /etc/login.defs", log=log)
    chroot("sed -i 's/^HOME_MODE.*/HOME_MODE 0700/' /etc/login.defs", check=False, log=log)

    if p.hardened_malloc:
        # A missing library in ld.so.preload breaks every binary on the system,
        # including the ones needed to undo it. Only wire it up if it is there.
        lib = os.path.join(ROOT, "usr/lib/libhardened_malloc.so")
        if os.path.exists(lib):
            write("/etc/ld.so.preload", "/usr/lib/libhardened_malloc.so\n", log=log)
        elif log:
            log("  hardened_malloc not installed (AUR) - skipping ld.so.preload")

    services = ["nftables", "systemd-resolved", "systemd-timesyncd",
                "NetworkManager", "fstrim.timer"]
    if p.apparmor:
        services.append("apparmor")
    if p.auditd:
        services.append("auditd")
    if p.usbguard:
        services += ["usbguard", "usbguard-dbus"]
    if p.tor_transparent:
        services.append("tor")
    for svc in services:
        chroot(f"systemctl enable {svc}", check=False, log=log)

    if p.usbguard:
        # Trust exactly what is plugged in right now, reject everything after.
        chroot("usbguard generate-policy > /etc/usbguard/rules.conf "
               "&& chmod 600 /etc/usbguard/rules.conf", check=False, log=log)

    if p.firejail_defaults:
        chroot("firecfg", check=False, log=log)

    if p.tor_transparent:
        write("/etc/tor/torrc.d/lunar-transparent.conf", """
VirtualAddrNetworkIPv4 10.192.0.0/10
AutomapHostsOnResolve 1
TransPort 127.0.0.1:9040 IsolateClientAddr IsolateClientProtocol IsolateDestAddr
DNSPort 127.0.0.1:9053
""", log=log)
        write("/etc/nftables.d/tor-transparent.nft", """
table inet lunar-tor {
    chain output {
        type nat hook output priority -100;
        meta skuid "tor" return
        oif "lo" return
        meta l4proto udp th dport 53 redirect to :9053
        meta l4proto tcp redirect to :9040
    }
}
""", log=log)

    # AppArmor: cache profiles so boot is not slowed by parsing
    if p.apparmor:
        chroot("aa-teardown 2>/dev/null; apparmor_parser -Q /etc/apparmor.d/ "
               "|| true", check=False, log=log)
