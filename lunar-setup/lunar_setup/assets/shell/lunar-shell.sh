# Lunar OS interactive shell settings (bash and zsh).

# Lunar OS manages packages with ltxs; there is no pacman command. The engine
# ltxs runs on stays installed underneath - updates and ltxs itself need it -
# but it is not something to type. Scripts that call it are unaffected: this
# only exists in interactive shells.
pacman() {
    printf 'pacman: not a Lunar OS command. Use ltxs:\n' >&2
    printf '  ltxs install <package>   ltxs remove <package>   ltxs update   ltxs help\n' >&2
    return 127
}
