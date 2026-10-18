# Lunar OS shell defaults.
export EDITOR=nano
if [ -n "$BASH_VERSION" ] && [[ $- == *i* ]]; then
  PS1='\[\e[38;2;150;160;255m\]\u\[\e[0m\] \w \[\e[2m\]>\[\e[0m\] '
  alias ls='ls --color=auto' ll='ls -lah --color=auto' grep='grep --color=auto'
fi
