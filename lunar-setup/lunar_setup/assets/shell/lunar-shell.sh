# Lunar OS interactive shell settings (bash and zsh).

# There is no pacman command on Lunar OS - packages are ltxs. Typed pacman,
# with or without sudo, answers the way any missing command does.
#
# This lives only in interactive shells. The engine ltxs runs on stays
# installed, and anything that runs it itself - ltxs, updates, package
# builds that call "sudo pacman" internally - is unaffected.

_lunar_not_found() {
    if [ -n "${ZSH_VERSION:-}" ]; then
        printf 'zsh: command not found: %s\n' "$1" >&2
    else
        printf 'bash: %s: command not found\n' "$1" >&2
    fi
    return 127
}

pacman() {
    _lunar_not_found pacman
}

# sudo pacman: find the command sudo would run (past sudo's own options and
# the values some of them take) and answer as sudo does for a missing one.
sudo() {
    local skip=0 a
    for a in "$@"; do
        if [ "$skip" = 1 ]; then skip=0; continue; fi
        case "$a" in
            -u|-g|-C|-D|-h|-p|-r|-t|-T|-U|--user|--group|--close-from|--chdir|--host|--prompt|--role|--type|--command-timeout|--other-user)
                skip=1; continue ;;
            --) continue ;;
            -*) continue ;;
        esac
        if [ "$a" = pacman ] || [ "$a" = /usr/bin/pacman ]; then
            printf 'sudo: %s: command not found\n' "$a" >&2
            return 1
        fi
        break
    done
    command sudo "$@"
}
