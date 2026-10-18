[ -f ~/.bashrc ] && . ~/.bashrc
# First console: straight into Sway.
if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
  if [ -z "$XDG_RUNTIME_DIR" ]; then
    # No logind session: fall back to seatd and a private runtime dir.
    export XDG_RUNTIME_DIR=/tmp/runtime-$UID LIBSEAT_BACKEND=seatd
    mkdir -p -m 0700 "$XDG_RUNTIME_DIR"
  fi
  export XDG_CURRENT_DESKTOP=sway XDG_SESSION_TYPE=wayland
  # No hardware GL driver in this build: Sway draws on the CPU (fast enough
  # for the desktop; much faster than software GL).
  export WLR_RENDERER=pixman
  sway > /tmp/sway-$UID.log 2>&1
  echo "Sway exited - its log is /tmp/sway-$UID.log. Type: sway  to start it again."
fi
