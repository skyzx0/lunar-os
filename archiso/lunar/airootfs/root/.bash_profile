# Live medium: greet on tty1, plain shell elsewhere so a failed run is still
# debuggable from another console.
if [[ "$(tty)" == /dev/tty1 && -z "${LUNAR_GREETED:-}" ]]; then
    export LUNAR_GREETED=1
    lunar-welcome
fi
