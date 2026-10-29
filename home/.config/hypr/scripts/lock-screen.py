#!/usr/bin/env python3
"""lock-screen -- the lock screen's look, kept in ~/.config/hypr/hyprlock.conf.

hyprlock reads that file every time it starts, i.e. at every lock, so a change
here shows at the next lock with nothing to restart. This script only edits
the lines it owns and keeps everything else -- comments, the colours, the
hand-tuned positions -- exactly as it was. Settings > Wallpaper & lock screen
is its front end; the search bar can run it too.

    lock-screen.py status              everything below as JSON
    lock-screen.py background screenshot|wallpaper|color [COLOUR]
                     screenshot  what was on each screen at lock time, blurred
                     wallpaper   each screen's current wallpaper (the links
                                 wallpaper-slideshow.py keeps, see its
                                 "Lock screen" section)
                     color       a plain colour: rgb(10, 12, 20), #0a0c14 ...
    lock-screen.py blur 0..4           blur passes (0 = sharp; 3 was the default)
    lock-screen.py dim 0.1..1          brightness of the background (1 = as is)
    lock-screen.py clock 24h|12h       the big clock
    lock-screen.py date on|off         the date under it
    lock-screen.py user on|off         your user name above the password field
    lock-screen.py layout on|off       the keyboard layout under the field
    lock-screen.py message [TEXT]      a line of your own under it ("" = none)
    lock-screen.py screen [OUTPUT]     where the field, clock and labels go
                                       (an output name; none = every screen)
    lock-screen.py preview             lock now (the real lock: it needs the
                                       password to come back)

How the file is edited
----------------------
The file is cut into its top-level blocks (background { ... }, label { ... }).
A label's job is told by its text: $TIME / $TIME12 is the clock, a `date`
command the date, $LAYOUT the layout, $USER / $DESC the user name, and the
one holding the "# lock-screen.py: message" comment line is the message.
Turning one off comments the whole block out with "#off# " in front of every
line, so turning it on again brings back exactly what was there; a block
that was never there comes from TEMPLATES below, in the clock's colours.
The wallpaper background is the file's own background block pointed at
the primary screen's link, plus one generated copy per other monitor (marked
"# lock-screen.py: per-screen copy"), rewritten on every change.
Every write is atomic, and the previous file is kept as
$XDG_STATE_HOME/hypr/hyprlock.conf.prev.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys

CONF = os.path.expanduser("~/.config/hypr/hyprlock.conf")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
PREV = os.path.join(STATE_DIR, "hyprlock.conf.prev")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import screens  # noqa: E402  (scripts/screens.py: the primary screen)
SLIDESHOW = os.path.join(HERE, "wallpaper-slideshow.py")
WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
LOCK_LINKS = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                          "wallpaper-slideshow", "lock")
OFF = "#off# "              # prefix of a turned-off block's lines
MESSAGE_MARK = "# lock-screen.py: message"
COPY_MARK = "# lock-screen.py: per-screen copy"
BLUR_SIZE = 8               # blur_size written when blur goes from 0 to on

# Blocks that may be missing from the file, added when turned on. {mon} is
# where the clock is; {font} the file's text font variable (or a plain one);
# {color} the clock's colour, so a new label matches what is there.
TEMPLATES = {
    "user": """\
# User name, over the password field (lock-screen.py user on|off).
label {{
    monitor = {mon}
    text = $USER
    font_size = 16
    font_family = {font}
    color = {color}
    position = 0, 40
    halign = center
    valign = center
}}
""",
    "message": """\
# A line of your own (lock-screen.py message TEXT).
label {{
    {mark}
    monitor = {mon}
    text = {text}
    font_size = 16
    font_family = {font}
    color = {color}
    position = 0, -150
    halign = center
    valign = center
}}
""",
    "date": """\
# Date
label {{
    monitor = {mon}
    text = cmd[update:60000] date +"{date_fmt}"
    font_size = 22
    font_family = {font}
    color = {color}
    position = 0, 120
    halign = center
    valign = center
}}
""",
    "layout": """\
# Active keyboard layout, under the field.
label {{
    monitor = {mon}
    text = $LAYOUT
    font_size = 14
    font_family = {font}
    color = {color}
    position = 0, -100
    halign = center
    valign = center
}}
""",
}


# ------------------------------------------------------------------ parsing --
class Block:
    """One top-level `name { ... }`: its lines as they are in the file (with
    the OFF prefix when turned off)."""

    def __init__(self, kind, lines, off=False):
        self.kind, self.lines, self.off = kind, lines, off

    def plain(self):
        return [ln[len(OFF):] if self.off and ln.startswith(OFF) else ln for ln in self.lines]

    def get(self, key):
        """The value as written (## escapes kept), any trailing comment cut."""
        for ln in self.plain()[1:-1]:
            m = re.match(rf"\s*{re.escape(key)}\s*=(.*)$", strip_comment(ln, keep=True))
            if m:
                return m.group(1).strip()
        return None

    def has_line(self, text):
        return any(ln.strip() == text for ln in self.plain())

    def set(self, key, value):
        """Replace key's value in place (indentation kept), or add the key
        before the closing brace."""
        lines = self.plain()
        for i, ln in enumerate(lines[1:-1], 1):
            m = re.match(rf"(\s*){re.escape(key)}(\s*)=", ln)
            if m:
                lines[i] = f"{m.group(1)}{key}{m.group(2)}= {value}".rstrip() + "\n"
                break
        else:
            indent = next((re.match(r"\s*", ln).group(0) for ln in lines[1:-1] if ln.strip()), "    ")
            lines.insert(len(lines) - 1, f"{indent}{key} = {value}".rstrip() + "\n")
        self.lines = lines
        if self.off:
            self.turn(False)
            self.turn(True)

    def drop(self, key):
        lines = self.plain()
        self.lines = [lines[0]] + [ln for ln in lines[1:-1]
                                   if not re.match(rf"\s*{re.escape(key)}\s*=", ln)] + [lines[-1]]
        if self.off:
            self.turn(False)
            self.turn(True)

    def turn(self, off):
        lines = self.plain()
        self.off = off
        self.lines = [OFF + ln if off else ln for ln in lines]

    def role(self):
        if self.kind != "label":
            return self.kind
        text = self.get("text") or ""
        if self.has_line(MESSAGE_MARK):
            return "message"
        if "$TIME" in text:
            return "clock"
        if re.search(r"\bdate\b", text):
            return "date"
        if "$LAYOUT" in text:
            return "layout"
        if "$USER" in text or "$DESC" in text:
            return "user"
        return "label"


def parse(text):
    """[str | Block]: loose lines (comments, blank, variables) and blocks."""
    items, cur, depth, off = [], None, 0, False
    for ln in text.splitlines(keepends=True):
        if not ln.endswith("\n"):
            ln += "\n"
        bare = ln[len(OFF):] if ln.startswith(OFF) else ln
        code = strip_comment(bare)
        if cur is None:
            m = re.match(r"\s*([A-Za-z][\w-]*)\s*\{\s*$", code)
            if m:
                off = ln.startswith(OFF)
                cur, depth = Block(m.group(1), [ln], off), 1
                if "}" in code:
                    depth = 0
                continue
            items.append(ln)
            continue
        cur.lines.append(ln)
        depth += code.count("{") - code.count("}")
        if depth <= 0:
            items.append(cur)
            cur = None
    if cur is not None:         # an unclosed block: keep it as text
        items.extend(cur.lines)
    return items


def strip_comment(line, keep=False):
    """hyprlang: # starts a comment, ## is a literal # (left as ## with keep)."""
    out, i = [], 0
    while i < len(line):
        if line[i] == "#":
            if line[i + 1:i + 2] == "#":
                out.append("##" if keep else "#")
                i += 2
                continue
            break
        out.append(line[i])
        i += 1
    return "".join(out)


def render(items):
    return "".join(it if isinstance(it, str) else "".join(it.lines) for it in items)


def blocks(items, role=None, kind=None, live=None):
    out = [it for it in items if isinstance(it, Block)]
    if kind:
        out = [b for b in out if b.kind == kind]
    if role:
        out = [b for b in out if b.role() == role]
    if live is not None:
        out = [b for b in out if b.off != live]
    return out


def main_background(items):
    """The file's own background block: the first one that is not a copy."""
    return next((b for b in blocks(items, kind="background") if not b.has_line(COPY_MARK)), None)


# ----------------------------------------------------------------- reading --
def escape_text(text):
    """A message for a label's text = line: Pango markup escaped, # doubled
    (hyprlang's comment char), one line. $ becomes &#36; so neither hyprlang
    ($variables) nor hyprlock ($USER, $TIME) swaps anything in, and a leading
    "cmd[" is written &#99;md[ so hyprlock shows it instead of running it as
    a shell command; Pango turns both back into the plain characters."""
    text = " ".join(text.split())
    text = html.escape(text, quote=False).replace("#", "##").replace("$", "&##36;")
    if text.startswith("cmd["):
        text = "&##99;" + text[1:]
    return text


def unescape_text(value):
    return html.unescape((value or "").replace("##", "#"))


def background_mode(path):
    if path == "screenshot":
        return "screenshot"
    if not path:
        return "color"
    if os.path.expanduser(path).startswith(LOCK_LINKS + os.sep):
        return "wallpaper"
    return "picture"        # a fixed picture of your own (a hand edit)


def status(items):
    bg = main_background(items)
    path = (bg.get("path") or "") if bg else ""
    clock = next(iter(blocks(items, "clock", live=True)), None)

    def on(role):
        return bool(blocks(items, role, live=True))
    message = next(iter(blocks(items, "message", live=True)), None)
    field = next(iter(blocks(items, kind="input-field")), None)
    passes = bg.get("blur_passes") if bg else None
    bright = bg.get("brightness") if bg else None
    return {
        "background": background_mode(path),
        "path": path,
        "color": (bg.get("color") if bg else None) or "rgba(0, 0, 0, 1.0)",
        "blur": int(passes) if passes and passes.isdigit() else 0,
        "dim": float(bright) if bright and re.match(r"^[\d.]+$", bright) else 1.0,
        "clock": ("12h" if clock and "$TIME12" in (clock.get("text") or "") else "24h") if clock else "off",
        "date": on("date"),
        "user": on("user"),
        "layout": on("layout"),
        "message": unescape_text(message.get("text")) if message else "",
        "screen": (field.get("monitor") or "") if field else "",
        "copies": [b.get("monitor") for b in blocks(items, kind="background") if b.has_line(COPY_MARK)],
        "conf": CONF,
    }


# ----------------------------------------------------------------- editing --
COLOUR = re.compile(r"^(rgba?\(\s*[\d.\s,]+\)|#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?)$")


def colour_value(text):
    """'#0a0c14' / '0a0c14' / 'rgb(10, 12, 20)' -> what hyprlock takes."""
    text = text.strip()
    if not COLOUR.match(text):
        raise ValueError(f"not a colour: {text!r} (rgb(10, 12, 20) or #0a0c14)")
    if text.startswith("rgb"):
        return text
    return f"rgb({text.lstrip('#')})"


def wallpaper_outputs():
    """Monitors with a lock link, the leader first."""
    try:
        names = sorted(os.listdir(LOCK_LINKS))
    except OSError:
        names = []
    names = [n for n in names if not n.endswith(".tmp")]
    leader = screens.primary()      # wallpaper-slideshow.py's theme_output()
    return sorted(names, key=lambda n: (n != leader, n))


def set_background(items, mode, colour=None, outputs=None):
    bg = main_background(items)
    was_wallpaper = bg is not None and background_mode(bg.get("path") or "") == "wallpaper"
    if bg is None:
        bg = Block("background", ["background {\n", "    monitor =\n", "}\n"])
        items.insert(0, bg)
        items.insert(0, "\n")
    # The old per-screen copies go whatever the new mode is.
    for b in blocks(items, kind="background"):
        if b.has_line(COPY_MARK):
            idx = items.index(b)
            del items[idx]
            if idx < len(items) and items[idx] == "\n":
                del items[idx]
    bg.turn(False)
    if mode != "wallpaper" and was_wallpaper:
        # The wallpaper mode pinned this block to the first screen; back to
        # every screen (what the file had before it).
        bg.set("monitor", "")
    if mode == "screenshot":
        bg.set("path", "screenshot")
    elif mode == "color":
        bg.set("path", "")
        if colour:
            bg.set("color", colour_value(colour))
    elif mode == "wallpaper":
        outputs = outputs if outputs is not None else wallpaper_outputs()
        if not outputs:
            raise ValueError("no wallpaper links yet (wallpaper-slideshow.py lock-links makes them)")
        # Every block names its screen: an empty monitor = would be drawn on
        # every screen as well, under (or, depending on hyprlock's sort, over)
        # that screen's own copy -- and decode the first screen's picture for
        # all of them. A screen with no link of its own gets hyprlock's plain
        # black.
        bg.set("monitor", outputs[0])
        bg.set("path", os.path.join(LOCK_LINKS, outputs[0]))
        at = items.index(bg) + 1
        for output in outputs[1:]:
            copy = Block("background", list(bg.plain()))
            copy.lines.insert(1, f"    {COPY_MARK}\n")
            copy.set("monitor", output)
            copy.set("path", os.path.join(LOCK_LINKS, output))
            items.insert(at, copy)
            items.insert(at, "\n")
            at += 2
    else:
        raise ValueError("background: screenshot, wallpaper or color")


def set_on_backgrounds(items, key, value):
    for b in blocks(items, kind="background"):
        if value is None:
            b.drop(key)
        else:
            b.set(key, value)


def label_style(items):
    clock = next(iter(blocks(items, "clock")), None)
    variables = "".join(it for it in items if isinstance(it, str))
    font = "$font_text" if re.search(r"^\$font_text\s*=", variables, re.M) else "Sans"
    return {"mon": (clock.get("monitor") if clock else "") or "",
            "color": (clock.get("color") if clock else None) or "rgba(255, 255, 255, 0.9)",
            "font": font, "date_fmt": date_format(variables)}


def date_format(variables):
    """The date label's strftime: the theme's $lock_date (hyprlock_theme.py
    writes one per theme, "%^A // %d %^B" and the like) when the file
    defines it, so a date turned back on matches the theme; else a plain
    "%A, %d %B"."""
    return "$lock_date" if re.search(r"^\$lock_date\s*=", variables, re.M) else "%A, %d %B"


def add_block(items, role, **extra):
    """A block from TEMPLATES, placed after the last label (before any
    trailing blank lines)."""
    text = TEMPLATES[role].format(mark=MESSAGE_MARK, **label_style(items), **extra)
    new = parse(text)
    labels = blocks(items, kind="label")
    at = items.index(labels[-1]) + 1 if labels else len(items)
    items[at:at] = ["\n"] + new
    return next(b for b in new if isinstance(b, Block))


def set_shown(items, role, on):
    found = blocks(items, role)
    if found:
        for b in found:
            b.turn(not on)
    elif on:
        add_block(items, role)


def set_clock(items, mode):
    clock = next(iter(blocks(items, "clock")), None)
    if clock is None:
        raise ValueError("hyprlock.conf has no clock label ($TIME) to change")
    text = clock.get("text") or "$TIME"
    clock.set("text", re.sub(r"\$TIME(12)?", "$TIME12" if mode == "12h" else "$TIME", text))


def set_message(items, text):
    found = blocks(items, "message")
    if not text.strip():
        for b in found:
            b.turn(True)
        return
    if found:
        found[0].set("text", escape_text(text))
        found[0].turn(False)
    else:
        add_block(items, "message", text=escape_text(text))


def set_screen(items, output):
    """The password field and every label to one monitor ("" = all)."""
    for b in blocks(items):
        if b.kind in ("input-field", "label"):
            b.set("monitor", output)


def change(items, command, args):
    """Apply one command to the parsed file (the pure part: tested)."""
    arg = args[0] if args else ""
    if command == "background":
        set_background(items, arg, args[1] if len(args) > 1 else None)
    elif command == "blur":
        if not arg.isdigit() or not 0 <= int(arg) <= 4:
            raise ValueError("blur: 0 to 4")
        set_on_backgrounds(items, "blur_passes", arg)
        if int(arg):
            for b in blocks(items, kind="background"):
                if not (b.get("blur_size") or "").isdigit() or int(b.get("blur_size")) == 0:
                    b.set("blur_size", str(BLUR_SIZE))
    elif command == "dim":
        try:
            value = float(arg)
        except ValueError:
            value = -1
        if not 0.1 <= value <= 1:
            raise ValueError("dim: 0.1 to 1")
        set_on_backgrounds(items, "brightness", f"{value:g}")
    elif command == "clock":
        if arg not in ("24h", "12h"):
            raise ValueError("clock: 24h or 12h")
        set_clock(items, arg)
    elif command in ("date", "user", "layout"):
        if arg not in ("on", "off"):
            raise ValueError(f"{command}: on or off")
        set_shown(items, command, arg == "on")
    elif command == "message":
        set_message(items, " ".join(args))
    elif command == "screen":
        if arg and not re.match(r"^[\w.:-]+$", arg):
            raise ValueError(f"screen: not an output name: {arg!r}")
        set_screen(items, arg)
    else:
        raise ValueError(f"unknown command {command!r}")


def balanced(text):
    depth = 0
    for ln in text.splitlines():
        code = strip_comment(ln)
        depth += code.count("{") - code.count("}")
        if depth < 0:
            return False
    return depth == 0


def write(text):
    """Atomic, through a symlink if the file is one, the old copy kept."""
    real = os.path.realpath(CONF)
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        shutil.copy2(real, PREV)
    except OSError:
        pass
    tmp = real + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, real)


def load():
    with open(CONF) as f:
        return f.read()


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    command, args = argv[0], argv[1:]
    try:
        text = load()
    except OSError as e:
        return f"lock-screen: cannot read {CONF}: {e}"
    if command == "status":
        print(json.dumps(status(parse(text))))
        return 0
    if command == "preview":
        # The real thing: there is no preview mode in hyprlock.
        subprocess.Popen(["sh", "-c", "pidof hyprlock || hyprlock"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    if command == "background" and args[:1] == ["wallpaper"]:
        # Make sure the links exist before pointing hyprlock at them.
        try:
            subprocess.run([SLIDESHOW, "lock-links"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            return f"lock-screen: wallpaper-slideshow.py lock-links failed: {e}"
    items = parse(text)
    try:
        change(items, command, args)
    except ValueError as e:
        return f"lock-screen: {e}"
    new = render(items)
    if not balanced(new):
        return "lock-screen: the edit would leave hyprlock.conf unbalanced; nothing written"
    if new != text:
        write(new)
    print(json.dumps(status(parse(new))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
