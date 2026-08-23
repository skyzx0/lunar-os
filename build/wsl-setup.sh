#!/usr/bin/env bash
# Provisions a fresh Arch WSL distribution for building Lunar OS.
# Run as root inside the distro; build/wsl.ps1 setup does this for you.

set -euo pipefail

log() { printf '\n:: %s\n' "$*"; }

log "Initialising the package keyring"
pacman-key --init
pacman-key --populate archlinux

log "Updating the system"
pacman -Syu --noconfirm

log "Installing build dependencies"
pacman -S --needed --noconfirm \
    archiso \
    arch-install-scripts \
    git rsync sudo \
    python python-build python-installer python-setuptools python-wheel \
    namcap shellcheck \
    gnupg pacman-contrib \
    erofs-utils squashfs-tools libisoburn dosfstools mtools

log "Tuning pacman and makepkg"
sed -i 's/^#ParallelDownloads.*/ParallelDownloads = 8/' /etc/pacman.conf
sed -i 's/^#MAKEFLAGS=.*/MAKEFLAGS="-j$(nproc)"/' /etc/makepkg.conf

# makepkg refuses to run as root.
if ! id builder &>/dev/null; then
    log "Creating the unprivileged build user"
    useradd -m -s /bin/bash builder
    echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder
    chmod 440 /etc/sudoers.d/builder
fi

# WSL rewrites /etc/resolv.conf on every start, which breaks pacstrap's ability
# to resolve mirrors inside the target chroot. Pin it.
if ! grep -q 'generateResolvConf' /etc/wsl.conf 2>/dev/null; then
    log "Pinning DNS so pacstrap can resolve mirrors"
    cat >> /etc/wsl.conf <<'EOF'

[network]
generateResolvConf = false
EOF
    rm -f /etc/resolv.conf
    cat > /etc/resolv.conf <<'EOF'
nameserver 9.9.9.9
nameserver 1.1.1.1
EOF
    chattr +i /etc/resolv.conf 2>/dev/null || true
fi

log "Verifying the pieces mkarchiso needs"
fail=0
for tool in mkarchiso pacstrap mkfs.erofs xorriso mkfs.fat; do
    if command -v "$tool" >/dev/null; then
        printf '   %-14s ok\n' "$tool"
    else
        printf '   %-14s MISSING\n' "$tool"
        fail=1
    fi
done

# WSL2 has a real kernel, but loop device support is what actually decides
# whether mkarchiso can assemble an image.
if losetup -f >/dev/null 2>&1; then
    printf '   %-14s ok\n' 'loop devices'
else
    printf '   %-14s MISSING\n' 'loop devices'
    fail=1
fi

(( fail == 0 )) || {
    echo
    echo "Something above is missing. The Docker path in build/win.ps1 is the"
    echo "fallback if this distro cannot be made to work."
    exit 1
}

log "Ready"
echo "   Build from Windows with: .\\build\\wsl.ps1 iso"
