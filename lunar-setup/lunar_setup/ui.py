"""Minimal curses UI primitives.

Monochrome with a single accent. No box-drawing noise, no icons.
Everything is centred in a fixed 74-column measure so the layout is
stable on both a 80x25 VGA console and a 200-column terminal.
"""

import curses
import locale
import re
import textwrap
import threading
import time

MEASURE = 74

ACCENT = 1
DIM = 2
INVERT = 3
WARN = 4


def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(ACCENT, curses.COLOR_CYAN, -1)
    curses.init_pair(DIM, curses.COLOR_WHITE, -1)
    curses.init_pair(INVERT, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(WARN, curses.COLOR_YELLOW, -1)
    curses.curs_set(0)


class Screen:
    def __init__(self, stdscr):
        self.s = stdscr
        self.h, self.w = stdscr.getmaxyx()
        self.left = max(2, (self.w - MEASURE) // 2)

    # ---------- drawing ----------

    def clear(self) -> None:
        self.s.erase()
        self.h, self.w = self.s.getmaxyx()
        self.left = max(2, (self.w - MEASURE) // 2)

    def put(self, y: int, text: str, attr=0, indent: int = 0) -> None:
        if 0 <= y < self.h:
            self.s.addnstr(y, self.left + indent, text, self.w - self.left - indent - 1, attr)

    def header(self, title: str, step: str = "") -> int:
        self.put(1, "LUNAR", curses.color_pair(ACCENT) | curses.A_BOLD)
        if step:
            self.put(1, step, curses.color_pair(DIM) | curses.A_DIM,
                     indent=MEASURE - len(step))
        self.put(3, title, curses.A_BOLD)
        return 5

    def paragraph(self, y: int, text: str, attr=0) -> int:
        for line in textwrap.wrap(text, MEASURE):
            self.put(y, line, attr)
            y += 1
        return y + 1

    def footer(self, hint: str) -> None:
        self.put(self.h - 2, hint, curses.color_pair(DIM) | curses.A_DIM)

    # ---------- input ----------

    def menu(self, title: str, items, step: str = "", hint: str = "",
             preamble: str = "", index: int = 0):
        """items: list of (label, blurb). Returns selected index, or None on Esc.

        Scrolls and type-to-filter, because some lists (keyboard layouts,
        timezones) are far longer than a console screen and an off-screen
        option is an option nobody can choose.
        """
        filter_text = ""
        while True:
            self.clear()
            y = self.header(title, step)
            if preamble:
                y = self.paragraph(y, preamble, curses.color_pair(DIM))

            shown = [(i, it) for i, it in enumerate(items)
                     if not filter_text
                     or filter_text in it[0].lower()
                     or filter_text in (it[1] or "").lower()]
            if not shown:
                shown = [(i, it) for i, it in enumerate(items)]
                filter_text = ""
            if index not in [i for i, _ in shown]:
                index = shown[0][0]

            has_blurbs = any(it[1] for _, it in shown)
            per_item = 2 if has_blurbs else 1
            room = max(3, (self.h - y - 4) // per_item)

            pos = next(n for n, (i, _) in enumerate(shown) if i == index)
            first = max(0, min(pos - room // 2, len(shown) - room))
            window = shown[first:first + room]

            top = y
            if first > 0:
                self.put(top - 1, "     ...", curses.color_pair(DIM) | curses.A_DIM)
            for real_i, (label, blurb) in window:
                sel = real_i == index
                mark = "  >  " if sel else "     "
                attr = curses.color_pair(ACCENT) | curses.A_BOLD if sel else 0
                self.put(top, mark + label, attr)
                if has_blurbs and blurb:
                    self.put(top + 1, "     " + blurb[:MEASURE - 6],
                             curses.color_pair(DIM) | curses.A_DIM)
                top += per_item
            if first + room < len(shown):
                self.put(top, "     ...", curses.color_pair(DIM) | curses.A_DIM)

            if filter_text:
                self.put(self.h - 3, f"filter: {filter_text}",
                         curses.color_pair(ACCENT))
            base = hint or "up/down  select    enter  confirm    esc  back"
            if len(items) > room:
                base += "    type to filter"
            self.footer(base)
            self.s.refresh()

            k = self.s.getch()
            positions = [i for i, _ in shown]
            here = positions.index(index)

            if k in (curses.KEY_UP,):
                index = positions[(here - 1) % len(positions)]
            elif k in (curses.KEY_DOWN,):
                index = positions[(here + 1) % len(positions)]
            elif k == curses.KEY_PPAGE:
                index = positions[max(0, here - room)]
            elif k == curses.KEY_NPAGE:
                index = positions[min(len(positions) - 1, here + room)]
            elif k == curses.KEY_HOME:
                index = positions[0]
            elif k == curses.KEY_END:
                index = positions[-1]
            elif k in (curses.KEY_ENTER, 10, 13):
                return index
            elif k == 27:
                if filter_text:
                    filter_text = ""
                    continue
                return None
            elif k in (curses.KEY_BACKSPACE, 127, 8):
                filter_text = filter_text[:-1]
            elif 32 <= k < 127:
                filter_text += chr(k).lower()

    def prompt(self, title: str, label: str, step: str = "", secret: bool = False,
               default: str = "", validator=None, help_text: str = "") -> str:
        buf = list(default)
        error = ""
        curses.curs_set(0 if secret else 1)
        try:
            while True:
                self.clear()
                y = self.header(title, step)
                if help_text:
                    y = self.paragraph(y, help_text, curses.color_pair(DIM))
                self.put(y, label, curses.A_BOLD)
                shown = "*" * len(buf) if secret else "".join(buf)
                self.put(y + 2, "  " + shown + " ", curses.color_pair(INVERT))
                if error:
                    self.put(y + 4, error, curses.color_pair(WARN))
                self.footer("enter  confirm    esc  back")
                self.s.refresh()

                k = self.s.getch()
                if k in (curses.KEY_ENTER, 10, 13):
                    value = "".join(buf)
                    if validator:
                        error = validator(value) or ""
                        if error:
                            continue
                    return value
                if k == 27:
                    return None
                if k in (curses.KEY_BACKSPACE, 127, 8):
                    if buf:
                        buf.pop()
                elif 32 <= k < 127:
                    buf.append(chr(k))
        finally:
            curses.curs_set(0)

    def confirm(self, title: str, body: str, step: str = "",
                yes: str = "Proceed", no: str = "Go back") -> bool:
        idx = self.menu(title, [(no, ""), (yes, "")], step=step, preamble=body)
        return idx == 1

    def log_view(self, title: str):
        """Returns a callable used as a live progress log sink."""
        self.clear()
        self.header(title)
        self.s.refresh()
        state = {"y": 5, "lines": []}

        def emit(line: str, accent: bool = False):
            state["lines"].append((line, accent))
            visible = state["lines"][-(self.h - 8):]
            self.clear()
            self.header(title)
            for i, (text, acc) in enumerate(visible):
                attr = curses.color_pair(ACCENT) if acc else curses.color_pair(DIM)
                self.put(5 + i, text[:MEASURE], attr)
            self.s.refresh()

        return emit


# --------------------------------------------------------------------------
# installation progress


LOGO = [
    "██╗     ██╗   ██╗███╗   ██╗ █████╗ ██████╗      ██████╗ ███████╗",
    "██║     ██║   ██║████╗  ██║██╔══██╗██╔══██╗    ██╔═══██╗██╔════╝",
    "██║     ██║   ██║██╔██╗ ██║███████║██████╔╝    ██║   ██║███████╗",
    "██║     ██║   ██║██║╚██╗██║██╔══██║██╔══██╗    ██║   ██║╚════██║",
    "███████╗╚██████╔╝██║ ╚████║██║  ██║██║  ██║    ╚██████╔╝███████║",
    "╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝     ╚═════╝ ╚══════╝",
]
SLOGAN = "See what's on the other side of the moon"

# What the installer is doing, recognised from its own output. Each phase
# owns a stretch of the bar; the bar only ever moves forward.
PHASES = [
    (("checking the connection",), "Checking the connection", 0, 3),
    (("checking the package list",), "Checking packages", 3, 6),
    (("installing with archinstall", "starting installation"), "Starting", 6, 8),
    (("wiping", "partition", "formatting", "mkfs"), "Preparing the disk", 8, 14),
    (("luks", "encrypt", "cryptsetup"), "Encrypting the disk", 14, 18),
    (("pacstrap", "installing packages", "downloading", "installing ", "upgrading",
      "retrieving", "packages ("), "Installing the system", 18, 72),
    (("bootloader", "bootctl", "systemd-boot"), "Installing the boot loader", 72, 76),
    (("creating user", "setting password", "sudo permissions", "enabling service"),
     "Setting up your account", 76, 79),
    (("executing custom command",), "Applying Lunar OS", 79, 98),
    (("installation complete",), "Lunar OS is installed", 100, 100),
]


def _utf8() -> bool:
    return "utf" in (locale.getpreferredencoding(False) or "").lower()

_COUNT = re.compile(r"\(\s*(\d+)/(\d+)\)")


class InstallProgress:
    """A progress bar for the installation; Tab shows the full output.

    The installation runs in a worker thread that only calls feed(); all
    drawing happens on the main thread in run(), so curses is never touched
    from two threads.
    """

    def __init__(self, stdscr, custom_total: int = 0):
        self.s = stdscr
        self.lines = []
        self.lock = threading.Lock()
        self.phase = -1
        self.pct = 0.0
        self.custom_total = max(custom_total, 1)
        self.custom_done = 0
        self.details = False
        self.started = time.time()
        self.last_line_at = time.time()
        self.finished = False
        self.failed = False

    # ---- fed from the worker thread ----------------------------------------

    def feed(self, line: str, accent: bool = False) -> None:
        low = line.lower()
        with self.lock:
            self.lines.append((line, accent))
            del self.lines[:-2000]
            self.last_line_at = time.time()
            for i, (keys, _label, _a, _b) in enumerate(PHASES):
                if any(k in low for k in keys):
                    if i > self.phase:
                        self.phase = i
                        self.pct = max(self.pct, PHASES[i][2])
                    break
            if self.phase < 0:
                return
            _keys, _label, start, end = PHASES[self.phase]
            if "executing custom command" in low:
                self.custom_done += 1
                self.pct = max(self.pct, start + (end - start) *
                               min(self.custom_done / self.custom_total, 1))
            elif (m := _COUNT.search(line)) and self.phase == 5 and int(m.group(2)):
                frac = int(m.group(1)) / int(m.group(2))
                self.pct = max(self.pct, start + (end - start) * 0.85 * frac)
            else:
                self.pct += (end - self.pct) * 0.012

    def finish(self, failed: bool) -> None:
        with self.lock:
            self.finished = True
            self.failed = failed
            if not failed:
                self.phase = len(PHASES) - 1
                self.pct = 100.0
            else:
                self.details = True

    # ---- the main thread ---------------------------------------------------

    def run(self, worker: threading.Thread) -> None:
        """Draw until the worker ends, then until a key is pressed."""
        self.s.timeout(150)
        waiting = False
        while True:
            if not worker.is_alive() and not waiting:
                waiting = True
                curses.flushinp()
            self._tick()
            self.draw(waiting)
            ch = self.s.getch()
            if ch == 9:                                   # Tab
                self.details = not self.details
            elif ch == curses.KEY_RESIZE:
                self.s.erase()
            elif waiting and ch in (10, 13, curses.KEY_ENTER, 27, 32):
                return

    def _tick(self) -> None:
        # Long downloads print nothing for a while; keep the bar alive
        # without ever reaching the end of the phase on time alone.
        with self.lock:
            if self.phase >= 0 and not self.finished and time.time() - self.last_line_at > 2:
                end = PHASES[self.phase][3]
                self.pct = min(self.pct + 0.01, max(self.pct, end - 1))

    def draw(self, waiting: bool) -> None:
        s = self.s
        s.erase()
        h, w = s.getmaxyx()
        with self.lock:
            lines = list(self.lines)
            pct, phase, failed, details = self.pct, self.phase, self.failed, self.details
        left = max(1, (w - MEASURE) // 2)
        accent = curses.color_pair(ACCENT)
        dim = curses.color_pair(DIM) | curses.A_DIM

        def put(y, x, text, attr=0):
            if 0 <= y < h - 1 and x < w - 1:
                try:
                    s.addnstr(y, x, text, w - x - 1, attr)
                except curses.error:
                    pass

        elapsed = int(time.time() - self.started)
        clock = f"{elapsed // 60}:{elapsed % 60:02d}"

        if details:
            put(1, left, "LUNAR OS", accent | curses.A_BOLD)
            put(1, left + MEASURE - len(clock), clock, dim)
            put(2, left, "Installation output", dim)
            rows = h - 6
            for i, (text, acc) in enumerate(lines[-rows:]):
                put(4 + i, left, text[:w - left - 2], accent if acc else curses.color_pair(DIM))
            hint = "Tab  progress" + ("      Enter  continue" if waiting else "")
            put(h - 2, left, hint, dim)
            s.refresh()
            return

        # The logo when there is room for it, the name otherwise.
        y = max(1, (h - 18) // 2)
        if _utf8() and w >= len(LOGO[0]) + 4 and h >= 22:
            lx = max(1, (w - len(LOGO[0])) // 2)
            for i, row in enumerate(LOGO):
                put(y + i, lx, row, accent | curses.A_BOLD)
            y += len(LOGO) + 1
        else:
            put(y, (w - 8) // 2, "LUNAR OS", accent | curses.A_BOLD)
            y += 2
        put(y, max(1, (w - len(SLOGAN)) // 2), SLOGAN, dim)
        y += 4

        if failed:
            label = "The installation did not finish"
        elif phase >= 0:
            label = PHASES[phase][1]
        else:
            label = "Getting ready"
        if not waiting and not failed and phase < len(PHASES) - 1:
            label += "." * (1 + int(time.time() * 2) % 3)
        bar_w = min(MEASURE, w - 4) - 6
        bx = max(1, (w - bar_w - 6) // 2)
        put(y, bx, label, curses.A_BOLD | (curses.color_pair(WARN) if failed else 0))
        y += 2
        filled = int(bar_w * min(pct, 100) / 100)
        full, empty = ("█", "░") if _utf8() else ("#", "-")
        put(y, bx, full * filled, accent)
        put(y, bx + filled, empty * (bar_w - filled), dim)
        put(y, bx + bar_w + 1, f"{int(pct):3d}%", curses.A_BOLD)
        y += 2
        put(y, bx, f"{clock} elapsed", dim)
        if waiting and not failed:
            msg = "Remove the USB stick, then press Enter"
            put(y + 2, max(1, (w - len(msg)) // 2), msg, accent | curses.A_BOLD)
        hint = "Tab  show details" + ("      Enter  continue" if waiting else "")
        put(h - 2, max(1, (w - len(hint)) // 2), hint, dim)
        s.refresh()
