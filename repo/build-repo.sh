#!/usr/bin/env bash
# Builds every package under repo/packages/ and assembles a pacman repository
# at repo/out/lunar/os/x86_64/.
#
#   ./repo/build-repo.sh              build and sign
#   ./repo/build-repo.sh --no-sign    build only; sign later on a trusted host
#
# Signing needs a key. Create one with build/mac.sh genkey (macOS) or
# build/win.ps1 genkey (Windows), or by hand:
#   gpg --full-generate-key
#   gpg --export --armor KEYID > repo/packages/lunar-keyring/lunar.gpg
#   echo KEYID > repo/signing-key.txt
#
# The private key must NOT live on the machine that serves the repo.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
top="$(dirname "$here")"
out="$here/out/lunar/os/x86_64"
pkgver=0.1.0

sign=1
[[ "${1:-}" == "--no-sign" ]] && sign=0

if (( sign )); then
    [[ -f "$here/signing-key.txt" ]] || {
        echo "repo/signing-key.txt missing. Use --no-sign, or generate a key first." >&2
        exit 1
    }
    key="$(cat "$here/signing-key.txt")"
    sign_args=(--sign --key "$key")
    repoadd_args=(--sign --key "$key")
else
    sign_args=()
    repoadd_args=()
fi

mkdir -p "$out"

# Package the working tree once and hand the same tarball to every PKGBUILD
# that needs it. Sourcing from a git URL would mean this repository could only
# be built after it had already been published somewhere.
tarball="lunar-os-$pkgver.tar.gz"
echo ":: staging source tarball"
tar czf "/tmp/$tarball" \
    --exclude='./repo/out' --exclude='./out' --exclude='./work' \
    --exclude='./.git' --exclude='__pycache__' \
    --transform "s,^\.,lunar-os," -C "$top" .

cleanup() { rm -f "$here"/packages/*/"$tarball" "/tmp/$tarball"; }
trap cleanup EXIT

for pkgdir in "$here"/packages/*/; do
    name="$(basename "$pkgdir")"

    # The keyring package exists to ship signing keys. Without a key there is
    # nothing to put in it, and a keyring of nothing is worse than none.
    if [[ "$name" == "lunar-keyring" ]] && (( ! sign )); then
        echo ":: skipping $name (unsigned build)"
        continue
    fi

    echo ":: building $name"
    cp "/tmp/$tarball" "$pkgdir/" 2>/dev/null || true

    # --nodeps is deliberate. The desktop packages are metapackages whose
    # depends() are what the installed system pulls in, not what building them
    # requires; letting makepkg -s install them here drags in the whole of
    # GNOME and fails on any dependency that lives in the AUR. Real build
    # dependencies are makedepends and are already present in the build
    # environment.
    ( cd "$pkgdir" && makepkg --clean --force --noconfirm --nodeps "${sign_args[@]}" )

    mv "$pkgdir"/*.pkg.tar.zst* "$out/" 2>/dev/null || true
done

echo ":: assembling database"
repo-add "${repoadd_args[@]}" --new --remove "$out/lunar.db.tar.zst" "$out"/*.pkg.tar.zst

if (( sign )); then
    echo ":: verifying signatures"
    for p in "$out"/*.pkg.tar.zst; do
        gpg --verify "$p.sig" "$p" >/dev/null 2>&1 || { echo "unsigned: $p" >&2; exit 1; }
    done
else
    echo ":: unsigned build - pacman will reject this repo unless SigLevel is relaxed"
fi

echo
echo "Repository built at $out"
ls -1 "$out"/*.pkg.tar.zst | sed 's,.*/,  ,'
