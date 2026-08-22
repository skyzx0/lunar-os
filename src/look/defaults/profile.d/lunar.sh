# Lunar OS shell environment.

# The tools are named for what they do rather than abbreviated to initials.
alias please='sudo'

# Show the machine on first interactive login of a session, not on every
# terminal. A fetch tool that runs in every new tab gets uninstalled.
if [ -n "${PS1:-}" ] && [ -z "${LUNAR_GREETED:-}" ] && [ -t 1 ]; then
    export LUNAR_GREETED=1
    command -v lunarfetch >/dev/null && lunarfetch
fi
