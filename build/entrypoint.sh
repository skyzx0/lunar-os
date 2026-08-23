#!/usr/bin/env bash
# Runs inside the build container. /src is the read-only source tree from the
# host; /build is a Linux-native volume; /out is where finished artefacts land.
#
# The source tree is copied into /build rather than built in place. macOS APFS
# is case-insensitive by default and carries no Unix ownership across the bind
# mount, and pacstrap will produce a corrupt rootfs on such a filesystem.

set -euo pipefail

SRC=/src
WORK=/build/src
OUT=/out

log() { printf '\n:: %s\n' "$*"; }

sync_source() {
    log "Copying source into the container volume"
    mkdir -p "$WORK"
    rsync -a --delete \
        --exclude 'out/' --exclude 'work/' --exclude '__pycache__/' \
        --exclude '.git/' \
        "$SRC"/ "$WORK"/

    # Windows hosts hand us CRLF. A shebang followed by \r produces
    # "bad interpreter: /usr/bin/env bash^M", and a PKGBUILD with CRLF makes
    # makepkg fail in ways that point nowhere near the real cause.
    # Detect text files rather than matching extensions: .service, .timer,
    # motd, signing-key.txt and PKGBUILD all matter and share no suffix.
    local crlf
    crlf=$(grep -rlI $'\r' "$WORK" 2>/dev/null || true)
    if [[ -n "$crlf" ]]; then
        log "Normalising CRLF line endings"
        printf '%s\n' "$crlf" | xargs -r sed -i 's/\r$//'
    fi

    chmod +x "$WORK"/repo/build-repo.sh "$WORK"/build/*.sh 2>/dev/null || true
    chown -R builder:builder "$WORK"
}

cmd_repo() {
    sync_source
    if [[ ! -f "$WORK/repo/signing-key.txt" ]]; then
        cat >&2 <<'MSG'

repo/signing-key.txt is missing.

Generate a signing key on the host, then:

    gpg --export --armor KEYID > repo/packages/lunar-keyring/lunar.gpg
    echo KEYID > repo/signing-key.txt
    echo "KEYID:4:" > repo/packages/lunar-keyring/lunar-trusted
    : > repo/packages/lunar-keyring/lunar-revoked

The container reads ~/.gnupg read-only to sign. See docs/BUILD-MACOS.md.

MSG
        exit 1
    fi
    log "Building packages"
    sudo -u builder bash -c "cd '$WORK' && ./repo/build-repo.sh"

    mkdir -p "$OUT/repo"
    rsync -a "$WORK/repo/out/" "$OUT/repo/"
    log "Packages in out/repo/"
}

cmd_repo_unsigned() {
    sync_source
    log "Building packages (unsigned)"
    sudo -u builder bash -c "cd '$WORK' && ./repo/build-repo.sh --no-sign"
    mkdir -p "$OUT/repo"
    rsync -a "$WORK/repo/out/" "$OUT/repo/"
    log "Packages in out/repo/ - sign them before publishing"
}

# The shipped pacman.conf points [lunar] at a public server that does not exist
# until you publish one. For a local build the repo we just made IS the source
# of truth, so rewrite it to a file:// URL pointing at repo/out.
wire_local_repo() {
    local repo_dir="$WORK/repo/out/lunar/os/x86_64"
    local siglevel="Required DatabaseRequired"

    [[ -f "$repo_dir/lunar.db.tar.zst" ]] || {
        echo "No local repo at $repo_dir - run 'repo' or 'repo-unsigned' first." >&2
        exit 1
    }

    # An unsigned local build has to relax SigLevel or pacman refuses the db.
    # This is scoped to the build container and never reaches the installed
    # system, whose pacman.conf comes from the target's own configuration.
    if ! compgen -G "$repo_dir/*.sig" >/dev/null; then
        siglevel="Optional TrustAll"
        log "Local repo is unsigned - relaxing SigLevel for this build only"
    fi

    log "Pointing [lunar] at the local repository"
    python3 - "$WORK/archiso/lunar/pacman.conf" "$repo_dir" "$siglevel" <<'PYEOF'
import re, sys
conf, repo_dir, siglevel = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(conf).read()
block = "[lunar]\nSigLevel = %s\nServer = file://%s\n" % (siglevel, repo_dir)
text = re.sub(r"\[lunar\][^\[]*", block, text)
open(conf, "w").write(text)
PYEOF

    # The keyring package only exists in signed builds; asking pacstrap for a
    # package that was never built fails the whole ISO.
    if ! compgen -G "$repo_dir/lunar-keyring-*.pkg.tar.zst" >/dev/null; then
        log "No keyring package - removing it from the live medium package list"
        sed -i '/^lunar-keyring$/d' "$WORK/archiso/lunar/packages.x86_64"
    fi
}

# archiso enables units by shipping symlinks in airootfs. Creating them here
# rather than committing symlinks keeps one auditable list of everything the
# live medium starts, and survives checkouts on filesystems without symlinks.
enable_live_units() {
    local ar="$WORK/archiso/lunar/airootfs"
    log "Enabling live medium services"

    mkdir -p "$ar/etc/systemd/system/multi-user.target.wants"

    # Boot to a console. The desktop is installed and one keystroke away
    # from the welcome screen, but starting it at boot costs several hundred
    # megabytes and a minute of startup for someone who came to run an
    # installer.
    ln -sf /usr/lib/systemd/system/multi-user.target "$ar/etc/systemd/system/default.target"
    rm -f "$ar/etc/systemd/system/display-manager.service"

    for unit in lunar-live-user.service; do
        ln -sf "../$unit" "$ar/etc/systemd/system/multi-user.target.wants/$unit"
    done
    ln -sf /usr/lib/systemd/system/NetworkManager.service \
        "$ar/etc/systemd/system/multi-user.target.wants/NetworkManager.service"

    # A rescue console must survive whatever else breaks.
    mkdir -p "$ar/etc/systemd/system/getty.target.wants"
    for tty in tty1 tty2; do
        ln -sf /usr/lib/systemd/system/getty@.service \
            "$ar/etc/systemd/system/getty.target.wants/getty@$tty.service"
    done

    # A console medium runs none of these, and each costs memory a small
    # machine does not have to spare. Masked rather than disabled so a
    # dependency cannot pull them back in.
    for unit in systemd-oomd.service packagekit.service man-db.service \
                bluetooth.service ModemManager.service cups.service \
                avahi-daemon.service avahi-daemon.socket upower.service \
                plasma-baloorunner.service; do
        ln -sf /dev/null "$ar/etc/systemd/system/$unit"
    done
}

# pacstrap aborts on file conflicts, and the message points at the package
# rather than at the profile that duplicated the file. Catch it here, where
# the fix is obvious, instead of 3 minutes into a package download.
check_profile_conflicts() {
    local repo_dir="$WORK/repo/out/lunar/os/x86_64"
    local ar="$WORK/archiso/lunar/airootfs"
    local conflicts=0

    [[ -d "$ar" ]] || return 0
    for pkg in "$repo_dir"/*.pkg.tar.zst; do
        [[ -f "$pkg" ]] || continue
        while read -r path; do
            path="${path#./}"
            # Directories are expected to overlap; only files conflict. The
            # archive root normalises to an empty string, which would match
            # airootfs itself.
            [[ -z "$path" || "$path" == */ ]] && continue
            [[ "$path" == .* ]] && continue          # .PKGINFO, .BUILDINFO
            if [[ -f "$ar/$path" ]]; then
                echo "  conflict: $(basename "$pkg") also ships /$path" >&2
                conflicts=1
            fi
        done < <(tar -tf "$pkg" 2>/dev/null)
    done

    if (( conflicts )); then
        echo >&2
        echo "The archiso profile ships files that a Lunar package also owns." >&2
        echo "Remove them from archiso/lunar/airootfs and let the package own them." >&2
        exit 1
    fi
}

cmd_iso() {
    sync_source
    enable_live_units
    check_profile_conflicts
    wire_local_repo
    log "Building the ISO"
    # mkarchiso wants a real Linux work directory with functioning ownership.
    rm -rf /build/work
    mkarchiso -v -w /build/work -o "$OUT" "$WORK/archiso/lunar"
    chmod 644 "$OUT"/*.iso
    rm -rf /build/work
    log "ISO in out/"
    ls -lh "$OUT"/*.iso
}

cmd_check() {
    sync_source
    log "Compiling the installer"
    python -m compileall -q "$WORK/lunar-setup/lunar_setup"
    log "Shell lint"
    shellcheck "$WORK/repo/build-repo.sh" "$WORK/build/entrypoint.sh" || true
    log "PKGBUILD lint"
    for p in "$WORK"/repo/packages/*/PKGBUILD; do namcap "$p" || true; done
    log "Package set sanity check"
    cd "$WORK/lunar-setup" && python -c "
from lunar_setup.profiles import Config, PROFILES, DESKTOPS
from lunar_setup import install
for d in DESKTOPS:
    for p in PROFILES:
        c = Config(desktop=d.key, profile=p.key)
        pkgs = install.package_set(c)
        assert pkgs, (d.key, p.key)
        print(f'{d.key:10s} {p.key:10s} {len(pkgs):3d} packages')
"
}

cmd_shell() {
    sync_source
    cd "$WORK"
    exec bash
}

cmd_clean() {
    rm -rf /build/work /build/src
    log "Container volume cleared"
}

case "${1:-help}" in
    repo)  cmd_repo ;;
    repo-unsigned) cmd_repo_unsigned ;;
    iso)   cmd_iso ;;
    check) cmd_check ;;
    shell) cmd_shell ;;
    clean) cmd_clean ;;
    *)
        cat <<'MSG'
entrypoint commands: repo | repo-unsigned | iso | check | shell | clean
Invoke from macOS with build/mac.sh instead of calling this directly.
MSG
        ;;
esac
