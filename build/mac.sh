#!/usr/bin/env bash
# Lunar OS build driver for macOS.
#
#   build/mac.sh doctor    check the toolchain and report what is missing
#   build/mac.sh image     build the Arch build container
#   build/mac.sh check     lint and sanity-check without building anything
#   build/mac.sh repo      build and sign the package repository
#   build/mac.sh iso       build the live/install ISO
#   build/mac.sh test      boot the ISO in QEMU with UEFI firmware
#   build/mac.sh shell     interactive shell inside the build container
#   build/mac.sh clean     drop the build volume and host artefacts

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE=lunar-build
VOLUME=lunar-build-vol
OUT="$ROOT/out"

log()  { printf '\n:: %s\n' "$*"; }
warn() { printf '\n!! %s\n' "$*" >&2; }
die()  { printf '\n!! %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------
# container runtime detection

detect_runtime() {
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        RUNTIME=docker
    elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
        RUNTIME=podman
    else
        die "No running container runtime. Start Docker Desktop, or:
    brew install colima docker
    colima start --arch x86_64 --vm-type vz --vz-rosetta --cpu 6 --memory 12 --disk 80"
    fi
}

host_arch() { uname -m; }

# --------------------------------------------------------------------------

cmd_doctor() {
    log "Host"
    printf '   macOS %s on %s\n' "$(sw_vers -productVersion)" "$(host_arch)"

    detect_runtime
    printf '   runtime: %s\n' "$RUNTIME"

    if [[ "$(host_arch)" == "arm64" ]]; then
        log "Apple Silicon"
        if $RUNTIME info 2>/dev/null | grep -qi rosetta; then
            printf '   Rosetta translation available. x86_64 builds run near native.\n'
        else
            warn "No Rosetta layer detected. x86_64 emulation will fall back to
   TCG and an ISO build may take over an hour. Enable it with:

     Docker Desktop  Settings > General > Use Rosetta for x86_64/amd64
     colima          colima delete && colima start --arch x86_64 \\
                       --vm-type vz --vz-rosetta --cpu 6 --memory 12 --disk 80"
        fi
    fi

    log "Resources"
    local mem
    mem=$($RUNTIME info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
    if [[ "$mem" -gt 0 ]]; then
        printf '   VM memory: %s GiB\n' "$((mem / 1024 / 1024 / 1024))"
        [[ "$mem" -lt $((6 * 1024 ** 3)) ]] && \
            warn "mkarchiso wants at least 6 GiB. Raise the VM memory limit."
    fi
    printf '   Free host disk: %s\n' "$(df -h "$ROOT" | awk 'NR==2 {print $4}')"

    log "Signing"
    if [[ -f "$ROOT/repo/signing-key.txt" ]]; then
        printf '   key id: %s\n' "$(cat "$ROOT/repo/signing-key.txt")"
    else
        warn "repo/signing-key.txt missing. 'repo' and 'iso' will fail.
   Run: build/mac.sh genkey"
    fi
    command -v gpg >/dev/null || warn "gpg not installed: brew install gnupg"

    log "Optional"
    command -v qemu-system-x86_64 >/dev/null \
        && printf '   qemu present, "test" will work\n' \
        || printf '   qemu missing, install with: brew install qemu\n'
}

cmd_genkey() {
    command -v gpg >/dev/null || die "brew install gnupg"
    log "Generating a Lunar OS repository signing key"
    cat <<'MSG'
Answer the prompts. Recommended: RSA 4096, no expiry, a real passphrase.
This key signs every package your machines will trust with root. Back up
~/.gnupg somewhere offline afterwards.

MSG
    gpg --full-generate-key

    local keyid
    keyid=$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr:/ {print $10; exit}')
    [[ -n "$keyid" ]] || die "Could not determine the new key id."

    gpg --export --armor "$keyid" > "$ROOT/repo/packages/lunar-keyring/lunar.gpg"
    echo "$keyid" > "$ROOT/repo/signing-key.txt"
    echo "$keyid:4:" > "$ROOT/repo/packages/lunar-keyring/lunar-trusted"
    : > "$ROOT/repo/packages/lunar-keyring/lunar-revoked"

    log "Key $keyid recorded"
    printf '   repo/signing-key.txt and the keyring package are populated.\n'
}

cmd_image() {
    detect_runtime
    log "Building the $IMAGE container"
    $RUNTIME build --platform linux/amd64 -t "$IMAGE" "$ROOT/build"
}

ensure_image() {
    detect_runtime
    $RUNTIME image inspect "$IMAGE" >/dev/null 2>&1 || cmd_image
    $RUNTIME volume inspect "$VOLUME" >/dev/null 2>&1 || $RUNTIME volume create "$VOLUME" >/dev/null
    mkdir -p "$OUT"
}

# mkarchiso does bind mounts and pacstrap chroots, so it needs full privileges.
# ~/.gnupg is mounted read-only so makepkg can sign without the private key
# ever being copied into the image layer.
run_in_container() {
    ensure_image
    local gpg_mount=()
    [[ -d "$HOME/.gnupg" ]] && gpg_mount=(-v "$HOME/.gnupg:/home/builder/.gnupg:ro")

    $RUNTIME run --rm -it \
        --platform linux/amd64 \
        --privileged \
        -v "$ROOT:/src:ro" \
        -v "$VOLUME:/build" \
        -v "$OUT:/out" \
        "${gpg_mount[@]}" \
        "$IMAGE" "$@"
}

cmd_test() {
    command -v qemu-system-x86_64 >/dev/null || die "brew install qemu"
    local iso=""
    for f in "$OUT"/*.iso; do
        [[ -f "$f" ]] && { iso="$f"; break; }
    done
    [[ -n "$iso" ]] || die "No ISO in out/. Run: ./build/mac.sh iso
   Or drop a downloaded ISO into $OUT"
    log "ISO: $(basename "$iso")"

    local fw_code fw_vars
    # A bare pipeline here returns non-zero when nothing matches, and under
    # 'set -e' that killed the script with no output at all. Search explicitly.
    fw_code=""
    for candidate in \
        /opt/homebrew/share/qemu/edk2-x86_64-code.fd \
        /usr/local/share/qemu/edk2-x86_64-code.fd \
        /opt/homebrew/share/qemu/edk2-x86_64-code.fd.bz2 \
        /opt/homebrew/Cellar/qemu/*/share/qemu/edk2-x86_64-code.fd
    do
        [[ -f "$candidate" ]] && { fw_code="$candidate"; break; }
    done
    if [[ -z "$fw_code" ]]; then
        warn "UEFI firmware not found. Looked for edk2-x86_64-code.fd under
   /opt/homebrew/share/qemu and /usr/local/share/qemu.

   See what your install has:
     ls \$(brew --prefix qemu)/share/qemu | grep -i edk2"
        die "Cannot boot without UEFI firmware."
    fi
    log "Firmware: $fw_code"

    fw_vars="$OUT/OVMF_VARS.fd"
    if [[ ! -f "$fw_vars" ]]; then
        # Some builds ship a matching vars template; a blank 4M image works too.
        if [[ -f "${fw_code%code.fd}vars.fd" ]]; then
            cp "${fw_code%code.fd}vars.fd" "$fw_vars"
        else
            qemu-img create -f raw "$fw_vars" 4M >/dev/null
        fi
    fi

    [[ -f "$OUT/test.qcow2" ]] || qemu-img create -f qcow2 "$OUT/test.qcow2" 40G

    log "Booting $(basename "$iso")"
    if [[ "$(host_arch)" == "arm64" ]]; then
        warn "x86_64 guest under emulation on Apple Silicon. Expect it to be slow;
   this is only useful for exercising the installer, not for benchmarking."
    fi

    qemu-system-x86_64 \
        -machine q35 -m 4096 -smp 4 \
        -drive if=pflash,format=raw,readonly=on,file="$fw_code" \
        -drive if=pflash,format=raw,file="$fw_vars" \
        -drive file="$OUT/test.qcow2",if=virtio,format=qcow2 \
        -cdrom "$iso" \
        -boot d \
        -device virtio-net-pci,netdev=n0 -netdev user,id=n0 \
        -display default,show-cursor=on
}

cmd_clean() {
    detect_runtime
    $RUNTIME volume rm -f "$VOLUME" 2>/dev/null || true
    rm -rf "$OUT"
    log "Removed the build volume and out/"
}

case "${1:-doctor}" in
    doctor) cmd_doctor ;;
    genkey) cmd_genkey ;;
    image)  cmd_image ;;
    check)  run_in_container check ;;
    repo)   run_in_container repo ;;
    iso)    run_in_container repo && run_in_container iso ;;
    shell)  run_in_container shell ;;
    test)   cmd_test ;;
    clean)  cmd_clean ;;
    *)      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
esac
