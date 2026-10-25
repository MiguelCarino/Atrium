#!/usr/bin/env python3
"""What every theme's mascot shares: the cell grid, the noise, the tool ->
prop mapping, and the checker / terminal demo. Pure Python, no GTK.

    Canvas(cols, rows)      cells of (char, fg, bg); markup() is Pango markup
    lcg(*seed)              a small deterministic noise source
    dw(ch), display_width(s)
    prop_kind(tool)         bash book pad lens globe helpers todo wand
    check_size((theme, cols, rows, ticks))   used by mascots.py --check
    ansi(markup, panel)     Pango markup -> ANSI truecolour, for the demo

The mascots themselves: moe_mascot.py (moe) and mascot_<theme>.py for the
others; mascots.py picks one per desktop theme and holds the CLI.

The grid only ever holds single-column characters: cell() turns anything
whose east_asian_width is W, F or A (ambiguous is wide in a CJK monospace
font such as M PLUS 1 Code) into "?", so a row of cols cells is cols columns
in every font. A cell may have a background colour (Pango's background=);
moe never sets one, and a grid without any is marked up exactly as before:
a blank cell joins whatever run it sits in, coloured or not.
"""

import html
import unicodedata

STATES = ("idle", "thinking", "tool", "writing", "done", "error")
TOOLS = ("Bash", "Read", "Edit", "Write", "Grep", "Glob", "WebSearch", "WebFetch",
         "Task", "Agent", "TodoWrite", "mcp__x__y", "Unknown", None)
COMBOS = [(s, None) for s in STATES if s != "tool"] + [("tool", t) for t in TOOLS]


def lcg(*seed):
    """A 32-bit LCG folded over the seed integers; returns a draw function
    yielding floats in [0, 1). Same seed, same sequence, always."""
    s = 2166136261
    for v in seed:
        s = ((s ^ (int(v) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    state = [s or 1]

    def draw():
        state[0] = (state[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        return (state[0] >> 8) / float(1 << 24)

    draw()
    return draw


def dw(ch):
    """Display width of one character in a CJK monospace font (A counts as 2)."""
    if " " <= ch < "\x7f":
        return 1
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1


def display_width(s):
    return sum(dw(c) for c in s)


def prop_kind(tool):
    t = (tool or "").strip()
    if t.startswith("mcp__"):
        return "wand"
    if t == "Bash":
        return "bash"
    if t in ("Read", "NotebookRead"):
        return "book"
    if t in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "pad"
    if t in ("Grep", "Glob", "WebSearch", "ToolSearch"):
        return "lens"
    if t == "WebFetch":
        return "globe"
    if t in ("Task", "Agent"):
        return "helpers"
    if t == "TodoWrite":
        return "todo"
    return "wand"


class Canvas:
    """cols x rows cells, each a single-column character, a colour (None for
    a blank cell) and a background (None: the panel shows through).
    Out-of-range writes are clipped silently."""

    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.ch = [[" "] * cols for _ in range(rows)]
        self.fg = [[None] * cols for _ in range(rows)]
        self.bg = [[None] * cols for _ in range(rows)]
        self.occ = [[False] * cols for _ in range(rows)]

    def cell(self, x, y, c, colour, bg=None):
        if 0 <= x < self.cols and 0 <= y < self.rows:
            if dw(c) != 1:
                c = "?"
            self.ch[y][x] = c
            self.fg[y][x] = colour if c != " " else None
            if bg is not None:
                self.bg[y][x] = bg

    def get(self, x, y):
        if 0 <= x < self.cols and 0 <= y < self.rows:
            return self.ch[y][x]
        return None

    def put(self, x, y, s, colour, solid=False, bg=None):
        """Write s at (x, y). Spaces are transparent unless solid (or bg)."""
        for i, c in enumerate(s):
            if c == " " and not solid and bg is None:
                continue
            self.cell(x + i, y, c, colour, bg)

    def sprite(self, x, y, s, colour, bg=None):
        """Write s with its outer spaces transparent and inner ones opaque:
        a sprite row that hides what is behind it between its edges."""
        a = len(s) - len(s.lstrip(" "))
        b = len(s.rstrip(" "))
        if a >= b:
            return
        self.put(x + a, y, s[a:b], colour, solid=True, bg=bg)
        if 0 <= y < self.rows:
            for c in range(max(0, x + a), min(self.cols, x + b)):
                self.occ[y][c] = True

    def fill(self, x, y, w, h, bg, ch=" ", colour=None, occupy=True):
        """A solid block of background (blank cells unless ch)."""
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if 0 <= xx < self.cols and 0 <= yy < self.rows:
                    self.ch[yy][xx] = ch
                    self.fg[yy][xx] = colour if ch != " " else None
                    self.bg[yy][xx] = bg
                    if occupy:
                        self.occ[yy][xx] = True

    def recolour(self, x, y, colour=None, bg=None):
        if 0 <= x < self.cols and 0 <= y < self.rows:
            if colour is not None and self.ch[y][x] != " ":
                self.fg[y][x] = colour
            if bg is not None:
                self.bg[y][x] = bg

    def shift_row(self, y, dx):
        """Rotate row y by dx cells (a glitch); width never changes."""
        if not (0 <= y < self.rows) or not dx:
            return
        for grid in (self.ch, self.fg, self.bg, self.occ):
            row = grid[y]
            dx %= self.cols
            grid[y] = row[-dx:] + row[:-dx]

    def lines(self):
        return ["".join(r) for r in self.ch]

    def markup(self):
        out = []
        for chars, cols, bgs in zip(self.ch, self.fg, self.bg):
            parts, run, run_col, run_bg = [], [], None, None
            for c, col, bg in zip(chars, cols, bgs):
                # A blank cell has no colour to show: it joins any run with
                # its own background.
                if (c == " " and bg == run_bg) or (col == run_col and bg == run_bg):
                    run.append(c)
                    continue
                if run:
                    parts.append((run_col, run_bg, "".join(run)))
                run, run_col, run_bg = [c], (col if c != " " else None), bg
            if run:
                parts.append((run_col, run_bg, "".join(run)))
            line = []
            for col, bg, text in parts:
                text = html.escape(text, quote=False)
                if col is None and bg is None:
                    line.append(text)
                elif bg is None:
                    line.append('<span foreground="%s">%s</span>' % (col, text))
                elif col is None:
                    line.append('<span background="%s">%s</span>' % (bg, text))
                else:
                    line.append('<span foreground="%s" background="%s">%s</span>' % (col, bg, text))
            out.append("".join(line))
        return "\n".join(out)


def stream_lines(words, width, seed=31, count=400):
    """Words drawn from `words`, wrapped to `width`: the text a mascot
    streams onto its scroll / screen while the model writes."""
    r = lcg(seed)
    text_lines, cur = [], ""
    for _ in range(count):
        w = words[int(r() * len(words))]
        if len(cur) + len(w) + (1 if cur else 0) > width:
            text_lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    text_lines.append(cur)
    return [l.ljust(width) for l in text_lines]


class BaseMascot:
    """The public half every non-moe mascot shares: lines / markup over its
    _render(), and bubble() from its BUBBLES / TOOL_BUBBLES tables (OTHER
    takes the tool's name: an MCP tool's last part, or the raw name).

    mood= and scene= (mascot_mood.py) are taken and ignored: moods is False,
    so the frontend leaves this mascot's face and bubble as they were. A
    mascot that draws them sets moods = True and overrides say()."""

    BUBBLES = {}
    TOOL_BUBBLES = {}
    OTHER = "%s"
    moods = False

    def lines(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool).lines()

    def markup(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool).markup()

    def say(self, topic):
        from mascot_mood import default_line
        return default_line(topic)

    def bubble(self, state, tool=None, mood=None):
        if state == "tool":
            if tool and tool.startswith("mcp__"):
                return self.OTHER % tool.split("__")[-1]
            return self.TOOL_BUBBLES.get(tool or "", self.OTHER % (tool or "tool"))
        return self.BUBBLES.get(state, self.BUBBLES.get("idle", "..."))

    def _render(self, state, tick, tool):
        raise NotImplementedError


# The reaction sign over the head (mascot_mood.View.emote): fallback colours
# for a mascot without EMOTE_COLOURS of its own.
EMOTE_FALLBACK = {"accent": "#7fd4ff", "warn": "#f2c14e", "bad": "#ff6b6b",
                  "good": "#6ee08a", "love": "#ff8fb8", "dim": "#9aa3b2"}


def draw_emote(cv, emote, anchor, colours=None):
    """Draw a View.emote -- (text, tone, age in seconds) -- with its first
    character at anchor (x, y), the cell just above the right side of the
    mascot's head. It pops in (a dot for a quarter second), floats up one
    row after 1.5 s and blinks out in its last second (REACT_S's hold ends
    it; the age is all it knows). Clipped to the canvas, never wider than
    it; single-column ASCII only, like everything on the grid."""
    if not emote or not anchor:
        return
    text, tone, age = emote[0], emote[1], float(emote[2])
    colour = (colours or {}).get(tone) or EMOTE_FALLBACK.get(tone) or EMOTE_FALLBACK["accent"]
    if age < 0.25:
        text = "."
    elif age > 7.5 and int(age * 4) % 2:
        return
    x, y = anchor
    if age >= 1.5:
        y -= 1
    x = max(0, min(x, cv.cols - len(text)))
    y = max(0, min(y, cv.rows - 1))
    cv.put(x, y, text, colour)


def blink(tick, period=53):
    """True on the frames the eyes are shut: every few seconds, and a double
    blink now and then."""
    return tick % period in (0, 1) or tick % (period * 3) in (5, 6)


# --- check / demo ------------------------------------------------------------

def check_size(job):
    """Every state/prop combo at one size and theme, at the given ticks:
    exact rows, exact display columns per row, markup that parses and says
    the same text, the public calls the same picture."""
    import xml.etree.ElementTree as ET
    import mascots
    theme, cols, rows, ticks = job
    m = mascots.Mascot(cols, rows, theme=theme)
    fails, n = [], 0
    for state, tool in COMBOS:
        for tick in ticks:
            n += 1
            cv = m._render(state, tick, tool)
            ls, mk = cv.lines(), cv.markup()
            where = "%s %dx%d %s/%s t%d" % (theme, cols, rows, state, tool, tick)
            if len(ls) != rows:
                fails.append("%s: %d rows" % (where, len(ls)))
            for i, l in enumerate(ls):
                if display_width(l) != cols:
                    fails.append("%s row %d: width %d" % (where, i, display_width(l)))
            try:
                root = ET.fromstring("<m>" + mk + "</m>")
            except ET.ParseError as e:
                fails.append("%s: markup %s" % (where, e))
                continue
            if "".join(root.itertext()).split("\n") != ls:
                fails.append("%s: markup text != lines" % where)
            if len(fails) > 5:
                return n, fails
        if m.lines(state, 7, tool) != m._render(state, 7, tool).lines() \
                or m.markup(state, 7, tool) != m._render(state, 7, tool).markup():
            fails.append("%s %dx%d %s/%s: public call differs" % (theme, cols, rows, state, tool))
    if getattr(m, "moods", False):
        for state, tool, mood, scene in MOOD_COMBOS:
            for tick in list(ticks)[::5]:
                n += 1
                cv = m._render(state, tick, tool, mood, scene)
                where = "%s %dx%d %s/%s %s %s t%d" % (theme, cols, rows, state, tool, mood,
                                                     "+".join(sorted(scene)) or "-", tick)
                fails += _check_canvas(cv, cols, rows, where)
                if len(fails) > 5:
                    return n, fails
        # The reaction signs: every one, at each stage of its life, over
        # the head anchor the render leaves (m.head, inside the canvas).
        from mascot_mood import EMOTES
        for state, mood in (("idle", "happy"), ("thinking", "curious"), ("done", "excited"),
                            ("error", "worried"), ("tool", "focused")):
            for tick in list(ticks)[:2]:
                cv = m._render(state, tick, "Bash" if state == "tool" else None, mood, frozenset({"night"}))
                head = getattr(m, "head", None)
                where = "%s %dx%d %s %s t%d" % (theme, cols, rows, state, mood, tick)
                if not head or not (0 <= head[0] < cols and 0 <= head[1] < rows):
                    fails.append("%s: head anchor %r outside the canvas" % (where, head))
                    return n, fails
                for text, tone in set(EMOTES.values()):
                    for age in (0.1, 1.0, 2.0, 8.2):
                        n += 1
                        cv = m._render(state, tick, "Bash" if state == "tool" else None, mood,
                                       frozenset({"night"}))
                        draw_emote(cv, (text, tone, age), m.head)
                        fails += _check_canvas(cv, cols, rows, where + " emote %s@%.1f" % (text, age))
                        if len(fails) > 5:
                            return n, fails
    return n, fails


def _mood_combos():
    """Every mood in the states that show it, and every scene tag alone and
    in a crowd, for the mascots that draw them (mascots.py --check)."""
    from mascot_mood import MOODS, SCENES
    out = []
    for mood in MOODS:
        for state, tool in (("idle", None), ("thinking", None), ("tool", "Bash"),
                            ("tool", "Task"), ("writing", None), ("done", None), ("error", None)):
            out.append((state, tool, mood, frozenset({"night"})))
    crowd = frozenset({"day", "rain", "party", "festive", "clock", "music", "cold", "hot"})
    for tag in SCENES:
        for state, tool in (("idle", None), ("tool", "Read"), ("done", None)):
            out.append((state, tool, "calm", frozenset({tag})))
    for mood in ("excited", "sleepy", "worried"):
        for state, tool in (("idle", None), ("thinking", None), ("tool", "Task"), ("done", None)):
            out.append((state, tool, mood, crowd))
            out.append((state, tool, mood, frozenset(SCENES)))
    return out


def _check_canvas(cv, cols, rows, where):
    import xml.etree.ElementTree as ET
    fails = []
    ls, mk = cv.lines(), cv.markup()
    if len(ls) != rows:
        fails.append("%s: %d rows" % (where, len(ls)))
    for i, l in enumerate(ls):
        if display_width(l) != cols:
            fails.append("%s row %d: width %d" % (where, i, display_width(l)))
    try:
        root = ET.fromstring("<m>" + mk + "</m>")
    except ET.ParseError as e:
        return fails + ["%s: markup %s" % (where, e)]
    if "".join(root.itertext()).split("\n") != ls:
        fails.append("%s: markup text != lines" % where)
    return fails


MOOD_COMBOS = _mood_combos()


def ansi(markup, panel="#2b1d2e"):
    """Pango markup from markup() to ANSI truecolour, for the demo."""
    import re

    def rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    base = "\x1b[48;2;%d;%d;%dm" % rgb(panel)
    out = []
    span = re.compile(r'<span( foreground="(#[0-9a-f]{6})")?( background="(#[0-9a-f]{6})")?>(.*?)</span>', re.I)
    for line in markup.split("\n"):
        s, pos = base, 0
        for m in span.finditer(line):
            s += html.unescape(line[pos:m.start()])
            seq = ""
            if m.group(2):
                seq += "\x1b[38;2;%d;%d;%dm" % rgb(m.group(2))
            if m.group(4):
                seq += "\x1b[48;2;%d;%d;%dm" % rgb(m.group(4))
            s += seq + html.unescape(m.group(5)) + "\x1b[39m" + base
            pos = m.end()
        s += html.unescape(line[pos:]) + "\x1b[0m"
        out.append(s)
    return "\n".join(out)
