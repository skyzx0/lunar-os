# Launch the installer on tty1 only; other TTYs stay a plain shell so a
# failed install is still debuggable.
if [[ "$(tty)" == /dev/tty1 ]]; then
    exec lunar-setup
fi
