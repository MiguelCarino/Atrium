#!/usr/bin/env python3
"""The mascot, small enough for a notification: one 16 x 16 pixel sprite per
desktop theme (mascots.py's mascots are ASCII scenes 48+ columns wide --
unreadable at 48 px), so a theme whose mascot does not shrink gets a little
cousin instead: Orbit's probe is a sputnik.

    mascot_icons.py path [--theme T] [--mood M] [--badge ICON]
                                    the PNG for it (made once, then cached)
    mascot_icons.py sheet OUT.png   every theme x mood on one sheet, to look at
    mascot_icons.py clear           drop the cache (after editing a sprite)

    icon(theme=None, mood="calm", badge=None) -> path      the same, in Python

MOODS -- a sign over the top-right corner, the way the chat stage puts one
over the mascot's head (mascot_common.draw_emote):

    calm      none: the mascot just says it (most notifications)
    alert     a red "!" (critical: something is wrong, or about to be)
    relieved  a green tick (it was handled)

badge is the notifying app's own icon (an icon-theme name or a file), drawn
small in the bottom-right corner so a timer still looks like a timer.

Sprites are drawn on a grid of 18 x 18 cells (the sprite at the bottom left,
the sign's corner free above it) and scaled by SCALE with no smoothing: 108
px, which mako (max-icon-size 48) halves and a bit -- crisp on both a normal
and a HiDPI screen. Cache: $XDG_CACHE_HOME/hypr/mascot-icons/, the file name
carrying a hash of the sprite, so an edited sprite never shows a stale icon.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                     "hypr", "mascot-icons")
GRID = 18
SCALE = 6
MOODS = ("calm", "alert", "relieved")
DEFAULT = "moe"

# -- the sprites ----------------------------------------------------------------
# Rows are built from runs so every row is provably 16 cells: "." is clear,
# every other letter a colour of that sprite's palette.


def _rows(*runs):
    rows = ["".join(r) for r in runs]
    bad = [i for i, r in enumerate(rows) if len(r) != 16]
    if len(rows) != 16 or bad:
        raise ValueError(f"sprite rows {bad} are not 16 cells")
    return rows


def _disc(cx, cy, r, outline, fill, rows=None):
    """A filled circle on a 16 x 16 grid: fill(x, y) picks each inner cell."""
    grid = [list(r) for r in rows] if rows else [["."] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            if d <= r - 1.0:
                grid[y][x] = fill(x, y)
            elif d <= r:
                grid[y][x] = outline
    return grid


def _line(grid, x0, y0, x1, y1, c):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        if 0 <= x0 < 16 and 0 <= y0 < 16:
            grid[y0][x0] = c
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _put(grid, cells, c):
    for x, y in cells:
        grid[y][x] = c
    return grid


def _outline(grid, inside, c):
    """Ring every cell of the letters in inside with c (4 neighbours), so a
    thin shape stays visible on a light notification too."""
    ring = [(x + dx, y + dy) for y in range(16) for x in range(16) if grid[y][x] in inside
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
    for x, y in ring:
        if 0 <= x < 16 and 0 <= y < 16 and grid[y][x] == ".":
            grid[y][x] = c
    return grid


def _moe():
    # the chibi cat-eared girl: pink hair, big eyes, a sailor collar
    return {"o": "#2a1630", "h": "#f4a6c8", "s": "#ffe0cc", "w": "#ffffff",
            "k": "#3a1a40", "b": "#ff8fab", "m": "#c0405a", "c": "#5a7bd8"}, _rows(
        ("..", "o", "." * 10, "o", ".."),
        (".", "oho", "." * 8, "oho", "."),
        (".", "ohho", "." * 6, "ohho", "."),
        (".", "ohhh", "o" * 6, "hhho", "."),
        ("o", "h" * 14, "o"),
        ("o", "h" * 14, "o"),
        ("o", "hhhh", "s", "hhhh", "s", "hhhh", "o"),
        ("o", "hh", "s" * 10, "hh", "o"),
        ("o", "hs", "s", "wk", "s" * 4, "wk", "s", "sh", "o"),
        ("o", "hs", "s", "kk", "s" * 4, "kk", "s", "sh", "o"),
        ("o", "hs", "b", "s" * 8, "b", "sh", "o"),
        (".", "o", "hs", "sss", "mm", "sss", "sh", "o", "."),
        (".", "o", "h", "s" * 10, "h", "o", "."),
        ("..", "o", "s" * 10, "o", ".."),
        ("...", "o" * 10, "..."),
        ("....", "o", "c" * 6, "o", "...."))


def _matrix():
    # the hooded hacker: a dark hood, two green eyes in the shadow
    return {"o": "#020a04", "h": "#1d4426", "f": "#050d07", "g": "#5dff7e",
            "d": "#1e8f3a"}, _rows(
        (".....", "o" * 6, "....."),
        ("...", "oo", "h" * 6, "oo", "..."),
        ("..", "o", "h" * 10, "o", ".."),
        (".", "o", "h" * 12, "o", "."),
        (".", "o", "hhh", "f" * 6, "hhh", "o", "."),
        ("o", "hhh", "f" * 8, "hhh", "o"),
        ("o", "hh", "f" * 10, "hh", "o"),
        ("o", "hh", "ff", "gg", "ff", "gg", "ff", "hh", "o"),
        ("o", "hh", "f" * 10, "hh", "o"),
        ("o", "hh", "fff", "dddd", "fff", "hh", "o"),
        ("o", "hhh", "f" * 8, "hhh", "o"),
        ("o", "hhhh", "f" * 6, "hhhh", "o"),
        ("o", "h" * 14, "o"),
        ("o", "hhhhh", "dddd", "hhhhh", "o"),
        ("o", "h" * 14, "o"),
        ("o" * 16,))


def _win95():
    # the paperclip assistant: a bent wire (outer loop, inner loop), two big
    # eyes with raised brows riding on top of it
    g = [["."] * 16 for _ in range(16)]
    for x0, y0, x1, y1 in ((4, 7, 4, 14), (4, 15, 10, 15), (11, 14, 11, 9),
                           (6, 9, 6, 12), (6, 13, 9, 13), (9, 12, 9, 6), (10, 6, 10, 6)):
        _line(g, x0, y0, x1, y1, "p")
    _put(g, [(5, 15), (11, 15), (5, 6), (6, 5), (7, 5), (8, 5)], "p")
    _put(g, [(4, 8), (4, 9), (4, 10), (6, 10), (6, 11)], "q")      # the light on the wire
    _outline(g, "pq", "o")
    eyes = _rows(
        (".", "kkk", ".", "kkk", "........"),
        ("." * 16,),
        ("o", "ww", "o", "ww", "o", "." * 9),
        ("o", "wk", "o", "wk", "o", "." * 9),
        ("o", "ww", "o", "ww", "o", "." * 9),
        (".", "oo", ".", "oo", "." * 10),
        *[("." * 16,)] * 10)
    for y, row in enumerate(eyes):
        for x, ch in enumerate(row):
            if ch != ".":
                g[y][x + 3] = ch
    return {"o": "#2b2f3a", "p": "#9ea4b6", "q": "#eef0f6", "w": "#ffffff",
            "k": "#101018"}, ["".join(r) for r in g]


def _aero():
    # the glossy orb buddy: a blue sphere, a white gloss, a smile
    def fill(x, y):
        if ((x + 0.5 - 6.2) / 3.6) ** 2 + ((y + 0.5 - 4.3) / 1.8) ** 2 < 1:
            return "w"
        return "a" if y < 6 else "b" if y < 11 else "c"
    g = _disc(8, 8, 7.6, "o", fill)
    _put(g, [(5, 8), (5, 9), (10, 8), (10, 9)], "k")
    _put(g, [(5, 11), (6, 12), (7, 12), (8, 12), (9, 12), (10, 11)], "k")
    return {"o": "#0a2a5a", "a": "#8fdcff", "b": "#3aa0f0", "c": "#1c6cc8",
            "w": "#f4fbff", "k": "#0b2550"}, ["".join(r) for r in g]


def _cyberpunk():
    # the neon android: a steel head, a magenta visor with cyan eyes
    return {"o": "#0a0b12", "m": "#4a5070", "v": "#ff2fb4", "c": "#3ff0ff",
            "g": "#14161e", "n": "#23263a", "a": "#3ff0ff"}, _rows(
        ("....", "o" * 7, "a", "...."),
        ("...", "o", "m" * 7, "o", "a", "..."),
        ("..", "o", "m" * 10, "o", ".."),
        (".", "o", "m" * 12, "o", "."),
        (".", "o", "m" * 12, "o", "."),
        ("o", "v" * 14, "o"),
        ("o", "v", "ccc", "v" * 6, "ccc", "v", "o"),
        ("o", "v" * 14, "o"),
        (".", "o", "m" * 12, "o", "."),
        (".", "o", "mmm", "g" * 6, "mmm", "o", "."),
        (".", "o", "m" * 12, "o", "."),
        ("..", "o", "m" * 10, "o", ".."),
        ("...", "o" * 10, "..."),
        (".....", "o", "nnnn", "o", "....."),
        ("...", "o", "m" * 8, "o", "..."),
        ("..", "o", "m" * 10, "o", ".."))


def _lofi():
    # the sleepy ginger cat: striped head, closed eyes, a white muzzle
    return {"o": "#3a2010", "r": "#e8893a", "d": "#c0661f", "i": "#f5a0a8",
            "k": "#3a2010", "w": "#fff3e6", "n": "#f07890"}, _rows(
        (".", "o", "." * 12, "o", "."),
        ("oio", "." * 10, "oio"),
        ("orio", "." * 8, "oiro"),
        ("o", "rrr", "o" * 8, "rrr", "o"),
        ("o", "r" * 5, "d", "rr", "d", "r" * 5, "o"),
        ("o", "r" * 14, "o"),
        ("o", "rrr", "d", "r" * 6, "d", "rrr", "o"),
        ("o", "r" * 14, "o"),
        ("o", "rr", "kkk", "r" * 4, "kkk", "rr", "o"),
        ("o", "r" * 14, "o"),
        ("o", "rrr", "w" * 8, "rrr", "o"),
        ("o", "rr", "wwww", "nn", "wwww", "rr", "o"),
        ("o", "rr", "www", "k", "ww", "k", "www", "rr", "o"),
        (".", "o", "r", "w" * 10, "r", "o", "."),
        ("..", "o", "r" * 10, "o", ".."),
        ("...", "o" * 10, "..."))


def _luna():
    # the cheerful manila folder: a tab, a front flap with a face
    return {"o": "#7a5418", "t": "#e0b050", "f": "#f6d27a", "k": "#4a3010",
            "w": "#ffffff", "b": "#f0907a"}, _rows(
        ("." * 16,),
        ("..", "o" * 5, "." * 9),
        (".", "o", "t" * 5, "o", "." * 8),
        ("o", "t" * 6, "o" * 9),
        ("o", "t" * 14, "o"),
        ("o" * 16,),
        ("o", "f" * 14, "o"),
        ("o", "f" * 14, "o"),
        ("o", "fff", "wk", "ffff", "wk", "fff", "o"),
        ("o", "fff", "kk", "ffff", "kk", "fff", "o"),
        ("o", "f", "b", "f" * 10, "b", "f", "o"),
        ("o", "f" * 5, "k", "ff", "k", "f" * 5, "o"),
        ("o", "f" * 6, "kk", "f" * 6, "o"),
        ("o", "f" * 14, "o"),
        ("o", "f" * 14, "o"),
        ("o" * 16,))


def _orbit():
    # the probe, shrunk to a sputnik: a silver ball, four swept-back
    # antennas, a red beacon -- and a face, it is still the mascot
    g = [["."] * 16 for _ in range(16)]
    for x0, y0, x1, y1 in ((6, 7, 0, 15), (7, 8, 3, 15), (5, 6, 0, 11), (8, 9, 7, 15)):
        _line(g, x0, y0, x1, y1, "a")

    def fill(x, y):
        if ((x + 0.5 - 8.6) ** 2 + (y + 0.5 - 3.6) ** 2) < 2.2:
            return "w"
        return "s" if x + y < 18 else "m"
    g = _disc(10, 5.5, 5.2, "o", fill, g)
    _put(g, [(8, 5), (8, 6), (12, 5), (12, 6)], "k")
    _put(g, [(9, 8), (10, 8), (11, 8)], "k")
    _put(g, [(10, 0)], "l")
    return {"o": "#1d2433", "s": "#d8dde8", "m": "#9aa3b8", "w": "#ffffff",
            "a": "#a8b0c4", "k": "#1d2433", "l": "#ff4d4d"}, ["".join(r) for r in g]


def _seasons():
    # the fox kit: tall ears, an orange face, a white muzzle
    return {"o": "#5a2a0c", "r": "#f08a2c", "w": "#fff4e8", "k": "#2a1408",
            "e": "#4a2410"}, _rows(
        (".", "o", "." * 12, "o", "."),
        (".", "oo", "." * 10, "oo", "."),
        (".", "oeo", "." * 8, "oeo", "."),
        (".", "oro", "." * 8, "oro", "."),
        (".", "orro", "." * 6, "orro", "."),
        ("o", "rrr", "o" * 8, "rrr", "o"),
        ("o", "r" * 14, "o"),
        ("o", "r" * 14, "o"),
        ("o", "rr", "wk", "r" * 6, "wk", "rr", "o"),
        ("o", "rr", "kk", "r" * 6, "kk", "rr", "o"),
        ("o", "ww", "r" * 10, "ww", "o"),
        (".", "o", "www", "rr", "ww", "rr", "www", "o", "."),
        ("..", "o", "wwww", "kk", "wwww", "o", ".."),
        ("...", "o", "w" * 8, "o", "..."),
        ("....", "o", "w" * 6, "o", "...."),
        (".....", "o" * 6, "....."))


def _orchard():
    # Hum, the honeybee: two antennae, pale wings either side, a round amber
    # body in dark stripes, two eyes and a smile (orchard and orchard-dark:
    # the dark outline reads on a light notification and a dark one)
    return {"k": "#1d1d1f", "y": "#f5b400", "w": "#e8f1ff", "e": "#ffffff"}, _rows(
        ("....", "k", "......", "k", "...."),
        (".....", "k", "....", "k", "....."),
        ("......", "kkkk", "......"),
        (".", "ww", "..", "k", "yyyy", "k", "..", "ww", "."),
        ("wwww", "k", "yyyyyy", "k", "wwww"),
        ("www", "k", "y", "ek", "yy", "ek", "y", "k", "www"),
        (".", "ww", "k", "yyyyyyyy", "k", "ww", "."),
        ("..", "k", "yyy", "k", "yy", "k", "yyy", "k", ".."),
        ("..", "k", "yyyy", "kk", "yyyy", "k", ".."),
        ("..", "k" * 12, ".."),
        ("..", "k", "y" * 10, "k", ".."),
        ("..", "k" * 12, ".."),
        ("...", "k", "y" * 8, "k", "..."),
        ("....", "k" * 8, "...."),
        (".....", "k", "yyyy", "k", "....."),
        ("......", "kkkk", "......"))


SPRITES = {"moe": _moe, "matrix": _matrix, "win95": _win95, "aero": _aero,
           "cyberpunk": _cyberpunk, "lofi": _lofi, "luna": _luna,
           "orbit": _orbit, "seasons": _seasons,
           "orchard": _orchard, "orchard-dark": _orchard}

# The mood signs, 7 x 7, drawn over the top-right corner of the grid.
SIGNS = {
    "alert": ({"r": "#f0565a", "w": "#ffffff", "o": "#3a0c10"}, (
        ".ooooo.",
        "orrwrro",
        "orrwrro",
        "orrwrro",
        "orrrrro",
        "orrwrro",
        ".ooooo.")),
    "relieved": ({"g": "#3fbf7f", "w": "#ffffff", "o": "#0c3a22"}, (
        ".ooooo.",
        "oggggwo",
        "ogggwwo",
        "owgwwgo",
        "owwwggo",
        "ogwgggo",
        ".ooooo.")),
}


def current_theme():
    try:
        sys.path.insert(0, HERE)
        import theme as desktop
        return desktop.current()
    except Exception:
        return DEFAULT


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + ((int(c[6:8], 16),) if len(c) == 8 else (255,))


def _badge_image(badge, px):
    """The app's icon as a px x px RGBA image, or None: a file path, or an
    icon-theme name looked up with GTK (only here, so a cached icon never
    pays for loading GTK)."""
    from PIL import Image
    path = os.path.expanduser(badge)
    if not os.path.isfile(path):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            info = Gtk.IconTheme.get_default().lookup_icon(badge, px, Gtk.IconLookupFlags.FORCE_SIZE)
            path = info.get_filename() if info else None
        except Exception:
            path = None
    if not path:
        return None
    try:
        if path.endswith(".svg"):
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, px, px)
            img = Image.frombytes("RGBA" if pb.get_has_alpha() else "RGB",
                                  (pb.get_width(), pb.get_height()), pb.get_pixels(),
                                  "raw", "RGBA" if pb.get_has_alpha() else "RGB",
                                  pb.get_rowstride())
        else:
            img = Image.open(path)
        return img.convert("RGBA").resize((px, px), Image.LANCZOS)
    except Exception:
        return None


def render(theme, mood="calm", badge=None):
    """The icon as a PIL image."""
    from PIL import Image, ImageDraw
    palette, rows = SPRITES.get(theme, SPRITES[DEFAULT])()
    img = Image.new("RGBA", (GRID * SCALE, GRID * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def cells(pal, grid, ox, oy):
        for y, row in enumerate(grid):
            for x, ch in enumerate(row):
                if ch != "." and ch in pal:
                    x0, y0 = (ox + x) * SCALE, (oy + y) * SCALE
                    draw.rectangle((x0, y0, x0 + SCALE - 1, y0 + SCALE - 1), fill=_hex(pal[ch]))

    cells(palette, rows, 0, GRID - 16)
    if mood in SIGNS:
        pal, sign = SIGNS[mood]
        cells(pal, sign, GRID - 7, 0)
    if badge:
        px = 7 * SCALE
        b = _badge_image(badge, px - 2 * SCALE)
        if b:
            x0 = y0 = GRID * SCALE - px
            draw.rounded_rectangle((x0, y0, x0 + px - 1, y0 + px - 1), radius=2 * SCALE,
                                   fill=(18, 20, 28, 235), outline=(255, 255, 255, 90), width=2)
            img.alpha_composite(b, (x0 + SCALE, y0 + SCALE))
    return img


def icon(theme=None, mood="calm", badge=None):
    """The cached PNG's path (rendered on first use)."""
    theme = theme if theme in SPRITES else (current_theme() if theme is None else DEFAULT)
    if theme not in SPRITES:
        theme = DEFAULT
    if mood not in MOODS:
        mood = "calm"
    src = repr(SPRITES[theme]()) + repr(SIGNS.get(mood)) + repr((GRID, SCALE, badge))
    tag = hashlib.sha1(src.encode()).hexdigest()[:10]
    path = os.path.join(CACHE, f"{theme}-{mood}-{tag}.png")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        render(theme, mood, badge).save(tmp, "PNG")
        os.replace(tmp, path)
    return path


def sheet(out):
    from PIL import Image, ImageDraw
    size = GRID * SCALE
    pad = 12
    bgs = [(14, 22, 38, 255), (236, 238, 242, 255)]
    themes = list(SPRITES)
    img = Image.new("RGBA", (len(themes) * (size + pad) + pad, 2 * len(MOODS) * (size + pad) + pad + 4),
                    (40, 40, 48, 255))
    for bi, bg in enumerate(bgs):
        for mi, mood in enumerate(MOODS):
            for ti, t in enumerate(themes):
                x = pad + ti * (size + pad)
                y = pad + (bi * len(MOODS) + mi) * (size + pad)
                ImageDraw.Draw(img).rectangle((x, y, x + size - 1, y + size - 1), fill=bg)
                img.alpha_composite(render(t, mood, "alarm-symbolic" if mood == "calm" and bi else None), (x, y))
    img.save(out)
    return out


def main(argv):
    args = argv[1:]
    cmd = args.pop(0) if args else "path"
    opts = {"--theme": None, "--mood": "calm", "--badge": None}
    while args and args[0] in opts:
        k = args.pop(0)
        opts[k] = args.pop(0) if args else None
    if cmd == "path":
        print(icon(opts["--theme"], opts["--mood"], opts["--badge"]))
    elif cmd == "sheet" and args:
        print(sheet(args[0]))
    elif cmd == "clear":
        import shutil
        shutil.rmtree(CACHE, ignore_errors=True)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
