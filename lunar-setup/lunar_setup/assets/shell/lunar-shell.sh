# Lunar OS interactive shell settings (bash and zsh).

# Packages are managed with ltxs. pacman stays installed as the engine
# underneath - ltxs, updates and the installer all use it - but typing it
# goes through ltxs. Scripts and "sudo pacman" are unaffected: this only
# exists in interactive shells.
pacman() {
    printf '\033[2mLunar OS uses ltxs  ->  ltxs %s\033[0m\n' "$*" >&2
    command ltxs "$@"
}
