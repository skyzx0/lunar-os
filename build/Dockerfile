# Build environment for Lunar OS. Always x86_64: the target is x86_64, and
# archiso has no working aarch64 path. On Apple Silicon this runs through
# Rosetta (fast) or TCG (slow but correct).

FROM --platform=linux/amd64 archlinux:base-devel

# The container both builds images and installs one to a loop device, so it
# needs the tools the installer drives as well as the ones archiso needs:
# partitioning, LVM, encryption, filesystems.
RUN pacman-key --init && \
    pacman -Syu --noconfirm --needed \
        archiso \
        git \
        python \
        python-build \
        python-installer \
        python-setuptools \
        python-wheel \
        namcap \
        shellcheck \
        rsync \
        gnupg \
        pacman-contrib \
        sudo \
        arch-install-scripts \
        archinstall \
        erofs-utils \
        squashfs-tools \
        gptfdisk \
        parted \
        lvm2 \
        cryptsetup \
        btrfs-progs \
        e2fsprogs \
        util-linux \
        libisoburn \
        dosfstools \
        mtools \
        edk2-ovmf \
        qemu-img && \
    pacman -Scc --noconfirm

# makepkg refuses to run as root, so packages are built as an unprivileged
# user. mkarchiso still needs root, hence the sudo rule.
RUN useradd -m -s /bin/bash builder && \
    echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder && \
    chmod 440 /etc/sudoers.d/builder

# Parallel compression and downloads; these dominate ISO build time.
RUN sed -i 's/^#ParallelDownloads.*/ParallelDownloads = 8/' /etc/pacman.conf && \
    sed -i 's/^#MAKEFLAGS=.*/MAKEFLAGS="-j$(nproc)"/' /etc/makepkg.conf && \
    sed -i 's/^COMPRESSZST=.*/COMPRESSZST=(zstd -c -T0 --ultra -20 -)/' /etc/makepkg.conf

COPY entrypoint.sh /usr/local/bin/entrypoint
RUN chmod 755 /usr/local/bin/entrypoint

WORKDIR /src
ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["help"]
