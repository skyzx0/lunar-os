"""Minimal curses UI primitives.

Monochrome with a single accent. No box-drawing noise, no icons.
Everything is centred in a fixed 74-column measure so the layout is
stable on both a 80x25 VGA console and a 200-column terminal.
"""

import curses
import textwrap

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
        """items: list of (label, blurb). Returns selected index, or None on Esc."""
        while True:
            self.clear()
            y = self.header(title, step)
            if preamble:
                y = self.paragraph(y, preamble, curses.color_pair(DIM))
            top = y
            for i, (label, blurb) in enumerate(items):
                sel = i == index
                mark = "  >  " if sel else "     "
                attr = curses.color_pair(ACCENT) | curses.A_BOLD if sel else 0
                self.put(top, mark + label, attr)
                if blurb:
                    self.put(top + 1, "     " + blurb[:MEASURE - 6],
                             curses.color_pair(DIM) | curses.A_DIM)
                    top += 1
                top += 2
            self.footer(hint or "up/down  select    enter  confirm    esc  back")
            self.s.refresh()

            k = self.s.getch()
            if k in (curses.KEY_UP, ord("k")):
                index = (index - 1) % len(items)
            elif k in (curses.KEY_DOWN, ord("j")):
                index = (index + 1) % len(items)
            elif k in (curses.KEY_ENTER, 10, 13):
                return index
            elif k == 27:
                return None

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
