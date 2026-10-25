#!/usr/bin/env python3
"""Theme previews: one small picture per desktop theme, made from the theme's
own files, WITHOUT switching to it -- what Settings > Theme > Gallery shows
before a click switches.

    make-theme-previews.py                 every theme (theme.py themes()):
                                           make the stale ones, print the paths
    make-theme-previews.py <name>...       only those themes
        --force                            make them even when fresh
        --cache <dir>                      another cache folder (the tests'
                                           scratch); default below
        --json                             [{name, label, about, path}] instead

    importable: preview(name), render(name), about(name), palette(name, part),
                stale(name), CACHE

What one preview is (SIZE, 360x180 -- three to a row in the Settings window)
---------------------------------------------------------------------------
    the wallpaper   the theme's FIRST still for the primary screen
                    (~/Pictures/Wallpapers/<primary>/<wallpaper_prefix>*, by
                    name, the slideshow's IMAGE_EXT), cropped to fill. None
                    found: a diagonal gradient from term.background to the
                    accent (a quarter of the way), so a theme without pictures
                    still shows its colours, and never a large light field
                    (DP-1 is HDR, themes/README)
    a bar strip     three pills along the top: workspaces (the first lit in
                    the accent), a clock, and good / warn / bad status pills,
                    in the bar's palette (@surface, @edge, @text, @good...)
    a panel card    bottom right, in the panels' palette: a heading, the
                    theme's name, an accent slider, three chips (the first
                    lit) and the three status dots
The text is drawn in the theme's own face: theme.conf font= (its first family
fontconfig really has -- `fc-match -f '%{file}'`, checked against
'%{family}' because fc-match always answers with SOMETHING), else sans-serif.
The user's own font override (display.conf font_user) is left out on
purpose: a preview shows the theme, and stays the same whoever's machine it
is made on. Corners follow hypr.rounding (Hyprland's window rounding), capped
at 12 px so a round theme does not eat its card.

The colours
-----------
Read the way GTK3 reads them: every `@define-color` of the base stylesheets
(theme.py TARGETS: waybar/style.css + style-toolbox.css for the bar,
waybar/panel.css for the panels), then @cyan = the theme's accent= (the
generated accent.css comes next in the live order), then -- a seasonal
theme -- the season's palette.css (the s-* names its roles are written in,
which theme.py puts before every GTK3 stylesheet), then the theme's own
waybar.css / panel.css with its season's additions (theme.py theme_text())
-- the LAST definition of a name wins. Stylesheets do not inherit
(theme.py), so only the theme's own two files count, not its inherit=
chain's. Values resolve roughly: #rgb / #rrggbb / #rrggbbaa,
rgb() / rgba(), @name, alpha(c, a), mix(a, b, t), shade(c, f) (scaled RGB,
not GTK's HLS -- close enough at 160 px), lighter() / darker(), and the
named white / black / transparent. Anything else falls back to the base
neon, never an exception. A wallpaper-following accent (accent_follow=yes)
is not guessed: the preview shows accent= or the base cyan.

The cache
---------
$XDG_CACHE_HOME/theme-previews/<theme>.png (~/.cache/...). Each PNG carries
its key in a text chunk ("preview-key"): a SHA-256 over VERSION, SIZE, the
season in effect, the mtimes of the theme's theme.conf chain, its waybar.css /
panel.css, that season's theme.conf / palette.css / waybar.css / panel.css,
the base stylesheets, the wallpaper picked, and the font file. preview()
makes a new one only when that key changed (lazily: the Settings page asks as
it shows), so editing a theme or adding a picture shows on the next look. Made the same
from the same files -- the output is byte-for-byte deterministic (fixed
clock text, no randomness, Pillow's PNG writer), which the tests check.
Measured on this machine (3440x1440 pictures on DP-1, nine themes): every
theme from cold in 0.88 s, Python's start included (most of it decoding the
pictures; Image.draft() shrinks a JPEG while it decodes), in the page's
background thread; every theme fresh -- one PNG header and the stats per
theme -- in 0.20 s.
"""
import functools
import hashlib
import json
import math
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import theme as T  # noqa: E402  (themes(), load(), the base stylesheets)
import screens  # noqa: E402  (the primary)

VERSION = "1"               # bump when the drawing changes: every preview goes stale
SIZE = (360, 180)
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "theme-previews")
WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".jxl")    # wallpaper-slideshow.py's
KEY_CHUNK = "preview-key"
CLOCK = "12:34"             # fixed: the same picture every time
BASE_CYAN = (0, 240, 255, 255)
README = os.path.join(T.THEMES_DIR, "README")
ABOUT_MAX = 90              # characters of the short description

# The base stylesheets each part's palette starts from (theme.py TARGETS:
# the same files the theme's file overrides).
BASES = {"bar": ("waybar.css", T.TARGETS["waybar.css"][2]),
         "panel": ("panel.css", T.TARGETS["panel.css"][2])}

# What a name resolves to when neither the base nor the theme says (or its
# value cannot be read): the base neon's own values.
FALLBACK = {"surface": (6, 8, 16, 214), "text": (230, 252, 255, 255), "text-dim": (150, 215, 230, 140),
            "edge": (0, 240, 255, 71), "green": (57, 255, 20, 255), "yellow": (249, 240, 2, 255),
            "magenta": (255, 42, 109, 255), "good": (57, 255, 20, 31), "good-fg": (141, 255, 110, 255),
            "warn": (249, 240, 2, 36), "warn-fg": (249, 240, 2, 255), "bad": (255, 42, 109, 41),
            "bad-fg": (255, 107, 149, 255), "surface-deep": (2, 3, 8, 179), "cyan": BASE_CYAN}


# -- colours -------------------------------------------------------------------------
DEFINE = re.compile(r"@define-color\s+([\w-]+)\s+([^;]+);")
COMMENT = re.compile(r"/\*.*?\*/", re.S)
NAMED = {"white": (255, 255, 255, 255), "black": (0, 0, 0, 255), "transparent": (0, 0, 0, 0)}


def defines(path):
    """[(name, value text)] of a stylesheet's @define-color lines, in order
    (comments dropped first: a commented-out define does not count)."""
    try:
        with open(path, encoding="utf-8") as handle:
            css = handle.read()
    except OSError:
        return []
    return defines_text(css)


def defines_text(css):
    """defines() of stylesheet text already read (theme.py hands the season
    palette and theme_text() over as text)."""
    return [(n, v.strip()) for n, v in DEFINE.findall(COMMENT.sub("", css or ""))]


def split_args(text):
    """"a, mix(b, c, 0.5), 0.3" -> ["a", "mix(b, c, 0.5)", "0.3"]: commas
    at the top level only."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return out


def number(text):
    text = text.strip()
    return float(text[:-1]) / 100 if text.endswith("%") else float(text)


def clamp(v):
    return max(0, min(255, int(round(v))))


def colour(expr, names, depth=0):
    """A GTK3 colour expression -> (r, g, b, a) 0-255, or None when it cannot
    be read. names: name -> value text (the palette so far)."""
    expr = expr.strip()
    if depth > 24:                                   # a define that refers to itself
        return None
    try:
        if expr.startswith("#"):
            h = expr[1:]
            if len(h) in (3, 4):
                h = "".join(c * 2 for c in h)
            if len(h) == 6:
                h += "ff"
            if len(h) != 8:
                return None
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
        if expr.startswith("@"):
            name = expr[1:]
            return colour(names[name], names, depth + 1) if name in names else None
        if expr.lower() in NAMED:
            return NAMED[expr.lower()]
        m = re.fullmatch(r"([\w-]+)\s*\((.*)\)", expr, re.S)
        if not m:
            return None
        fn, args = m.group(1).lower(), split_args(m.group(2))
        if fn in ("rgb", "rgba"):
            rgb = [clamp(number(a) * 255) if a.strip().endswith("%") else clamp(float(a)) for a in args[:3]]
            alpha = number(args[3]) if len(args) > 3 else 1.0
            return (*rgb, clamp(alpha * 255))
        if fn == "alpha":
            c = colour(args[0], names, depth + 1)
            return None if c is None else (*c[:3], clamp(c[3] * number(args[1])))
        if fn == "mix":
            a, b, t = colour(args[0], names, depth + 1), colour(args[1], names, depth + 1), number(args[2])
            return None if a is None or b is None else tuple(clamp(x * (1 - t) + y * t) for x, y in zip(a, b))
        if fn in ("shade", "lighter", "darker"):
            c = colour(args[0], names, depth + 1)
            f = number(args[1]) if fn == "shade" else (1.3 if fn == "lighter" else 0.7)
            return None if c is None else (*(clamp(x * f) for x in c[:3]), c[3])
    except (ValueError, IndexError, KeyError):
        return None
    return None


def palette(name, part="panel"):
    """The resolved colours of one part ("bar" or "panel") of a theme:
    name -> (r, g, b, a). The base files' defines, then @cyan = accent=, then
    (a seasonal theme) the season's palette.css, then the theme's own file
    with its season's additions -- GTK's last-definition-wins order, and the
    order theme.py generated_text() writes. Without the season's palette the
    seasons theme's every role (@s-surface, @s-rule, @s-good...) is an
    unknown name, and its card came out in the base neon: surface
    (6, 8, 16, 214) and edge (0, 240, 255, 71) in autumn, measured before
    the fix; only @cyan followed the season."""
    filename, bases = BASES[part]
    names = {}
    for base in bases:
        names.update(defines(base))
    conf = T.load(name, user=False)
    accent = conf.get("accent", "")
    if T.HEX.match(accent or ""):
        names["cyan"] = accent
    names.update(defines_text(T.season_palette(conf)))
    names.update(defines_text(T.theme_text(conf, filename)))
    out = dict(FALLBACK)
    for key in names:
        value = colour(names[key], names)
        if value is not None:
            out[key] = value
    return out


def hex_rgba(text, default=(0, 0, 0, 255)):
    c = colour(text or "", {})
    return c if c is not None else default


# -- inputs: wallpaper, font, rounding --------------------------------------------------
def wallpaper(name, output=None, walldir=None):
    """The theme's first still for the screen (by file name), or None."""
    prefix = T.load(name, user=False).get("wallpaper_prefix", "")
    folder = os.path.join(walldir or WALLDIR, output or screens.primary())
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for n in names:
        if n.startswith(prefix) and n.lower().endswith(IMAGE_EXT) and os.path.isfile(os.path.join(folder, n)):
            return os.path.join(folder, n)
    return None


@functools.lru_cache(maxsize=64)
def fc_match(family):
    """(file, family) fontconfig gives for a family name, or ("", "")."""
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}\t%{family}", family],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return "", ""
    file, _, fam = out.partition("\t")
    return file.strip(), fam.strip()


def font_file(name):
    """The file of the theme's face: the first family in font= that
    fontconfig really has (its answer's family list names it), else
    sans-serif's. "" when fontconfig is not there (Pillow's own face then)."""
    for family in T.font_list(T.load(name, user=False).get("font", "")):
        file, fams = fc_match(family)
        if file and family.lower() in [f.strip().lower() for f in fams.split(",")]:
            return file
    return fc_match("sans-serif")[0]


def font(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    except OSError:
        return ImageFont.load_default(size)


def rounding(name):
    try:
        return max(0, min(12, int(float(T.load(name, user=False).get("hypr.rounding", "8")))))
    except ValueError:
        return 8


# -- the short description -------------------------------------------------------------
def first_sentence(text):
    text = " ".join(text.split())
    m = re.search(r"(?<!\d)[.;](\s|$)| -- ", text)
    return text[:m.start()] if m else text


def shorten(text, limit=ABOUT_MAX):
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(",:;-")
    return cut + "…"


def tidy(text, name, label):
    """First sentence, a leading "<Name>:" dropped when it only repeats the
    theme's name ("Luna: an original homage..." -> "An original homage..."),
    first letter up, cut to ABOUT_MAX."""
    text = first_sentence(text).strip()
    head, sep, rest = text.partition(": ")
    if sep and rest and len(head) <= 32 and (name.lower() in head.lower() or label.lower() in head.lower()):
        text = rest
    text = text[:1].upper() + text[1:]
    return shorten(text)


def header_text(path):
    """theme.conf's opening comment after its " -- ", up to the first blank
    comment line: "~/.config/themes/luna/theme.conf -- Luna: ..."."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    parts = []
    for line in lines:
        if not line.startswith("#"):
            break
        body = line[1:].strip()
        if not body:
            if parts:
                break
            continue
        if not parts:
            if " -- " not in body:
                continue
            body = body.split(" -- ", 1)[1]
        parts.append(body)
    return " ".join(parts)


def readme_text(name, path=README):
    """The theme's paragraph in themes/README ("    luna/        Luna: ..."
    and its indented lines after), or ""."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    parts = []
    for line in lines:
        m = re.match(r"^\s{2,}(\S+)/\s+(.*)$", line)
        if parts:
            if m or not line.startswith(" " * 8) or not line.strip():
                break
            parts.append(line.strip())
        elif m and m.group(1) == name:
            parts.append(m.group(2).strip())
    return " ".join(parts)


def about(name, readme=README):
    """A one-line description: theme.conf's header, else the README's
    paragraph, else ""."""
    label = T.load(name, user=False).get("name") or name
    text = header_text(os.path.join(T.theme_dir(name), "theme.conf")) or readme_text(name, readme)
    return tidy(text, name, label) if text else ""


# -- drawing ---------------------------------------------------------------------------------
def cover(path, size):
    """The picture scaled and centre-cropped to fill size, RGBA."""
    w, h = size
    with Image.open(path) as im:
        im.draft("RGB", (w * 2, h * 2))             # JPEG: decode at a fraction of the size
        im = im.convert("RGB")
        scale = max(w / im.width, h / im.height)
        sw, sh = max(w, math.ceil(im.width * scale)), max(h, math.ceil(im.height * scale))
        im = im.resize((sw, sh), Image.Resampling.LANCZOS, reducing_gap=3.0)
        left, top = (sw - w) // 2, (sh - h) // 2
        return im.crop((left, top, left + w, top + h)).convert("RGBA")


def gradient(size, start, end):
    """A diagonal from start (top left) to end (bottom right), RGBA."""
    w, h = size
    out = Image.new("RGBA", size)
    px = out.load()
    span = (w - 1) + (h - 1) or 1
    for y in range(h):
        for x in range(w):
            t = (x + y) / span
            px[x, y] = (*(clamp(a * (1 - t) + b * t) for a, b in zip(start[:3], end[:3])), 255)
    return out


def layer(base, draw_fn):
    """Draw on a clear layer and lay it over base (so a translucent fill
    over another blends, as the compositor's would)."""
    top = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(top))
    return Image.alpha_composite(base, top)


def text_width(draw, text, face):
    left, _, right, _ = draw.textbbox((0, 0), text, font=face)
    return right - left


def over(top, under):
    """top laid over under (both RGBA 0-255): the opaque colour seen."""
    a = top[3] / 255
    return (*(clamp(t * a + u * (1 - a)) for t, u in zip(top[:3], under[:3])), 255)


def luminance(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(fill, under, palette):
    """The text colour for a lit fill: whichever of the palette's text,
    text-bright and ink reads best on it (WCAG contrast). The panels pick
    per rule; a preview cannot read the rules, so it measures -- win95's
    navy chip wants white (16.0:1 vs black's 1.3:1)."""
    seen = over(fill, over(under, (16, 16, 16, 255)))
    options = [palette[k] for k in ("text", "text-bright", "ink") if k in palette]
    return max(options, key=lambda c: contrast(over(c, seen), seen))


def pill(draw, box, fill, edge, radius):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=edge, width=1)


def draw_bar(img, bar, face, radius):
    """The bar strip: workspaces, clock, status pills (y 6..26)."""
    w = img.width
    top, bottom = 6, 26
    r = min(radius, (bottom - top) // 2)

    def go(d):
        # workspaces: four numbers, the first lit
        pill(d, (8, top, 92, bottom), bar["surface"], bar["edge"], r)
        for i in range(4):
            x = 14 + i * 19
            if i == 0:
                d.rounded_rectangle((x - 2, top + 3, x + 14, bottom - 3), radius=max(0, r - 2), fill=bar["cyan"])
            d.text((x + 6, (top + bottom) // 2), str(i + 1), font=face, anchor="mm",
                   fill=readable(bar["cyan"], bar["surface"], bar) if i == 0 else bar["text"])
        # clock, centred
        cw = text_width(d, CLOCK, face) + 20
        pill(d, ((w - cw) // 2, top, (w + cw) // 2, bottom), bar["surface"], bar["edge"], r)
        d.text((w // 2, (top + bottom) // 2), CLOCK, font=face, anchor="mm", fill=bar["text"])
        # status: good / warn / bad, from the right
        x = w - 8
        for kind, word in (("bad", "bat"), ("warn", "upd"), ("good", "cpu")):
            tw = text_width(d, word, face) + 14
            pill(d, (x - tw, top, x, bottom), bar["surface"], bar["edge"], r)
            d.rounded_rectangle((x - tw + 2, top + 2, x - 2, bottom - 2), radius=max(0, r - 2), fill=bar[kind])
            d.text((x - tw / 2, (top + bottom) // 2), word, font=face, anchor="mm", fill=bar[f"{kind}-fg"])
            x -= tw + 4
    return layer(img, go)


def draw_card(img, panel, faces, radius, label):
    """The panel card, bottom right: heading, name, slider, chips, dots."""
    w, h = img.size
    box = (w - 178, 38, w - 10, h - 10)
    x0, y0, x1, _ = box
    small, body, title = faces

    img = layer(img, lambda d: d.rounded_rectangle(box, radius=radius, fill=panel["surface"],
                                                   outline=panel["edge"], width=1))

    def go(d):
        d.text((x0 + 12, y0 + 10), "THEME", font=small, fill=panel["text-dim"])
        d.text((x0 + 12, y0 + 24), label, font=title, fill=panel["text"])
        # the slider: a track in the edge colour, 60 % filled in the accent
        ty = y0 + 56
        d.rounded_rectangle((x0 + 12, ty, x1 - 12, ty + 4), radius=2, fill=panel["edge"])
        mid = x0 + 12 + int((x1 - x0 - 24) * 0.6)
        d.rounded_rectangle((x0 + 12, ty, mid, ty + 4), radius=2, fill=panel["cyan"])
        d.ellipse((mid - 5, ty - 3, mid + 5, ty + 7), fill=panel["cyan"])
        # three chips, the first lit (the accent WASH, the panels' .active)
        cy = y0 + 72
        cx = x0 + 12
        for i, word in enumerate(("On", "Off", "Auto")):
            cw = text_width(d, word, body) + 14
            fill = panel.get("accent", panel["cyan"]) if i == 0 else panel["surface-deep"]
            d.rounded_rectangle((cx, cy, cx + cw, cy + 18), radius=min(radius, 9), fill=fill,
                                outline=panel["cyan"] if i == 0 else panel["edge"], width=1)
            d.text((cx + cw / 2, cy + 9), word, font=body, anchor="mm",
                   fill=readable(fill, panel["surface"], panel) if i == 0 else panel["text"])
            cx += cw + 5
        # good / warn / bad dots and a dim line
        dy = y0 + 104
        for i, kind in enumerate(("green", "yellow", "magenta")):
            d.ellipse((x0 + 12 + i * 14, dy, x0 + 21 + i * 14, dy + 9), fill=panel[kind])
        d.text((x0 + 56, dy + 4), "good / warn / bad", font=small, anchor="lm", fill=panel["text-dim"])
    return layer(img, go)


def render(name, output=None, walldir=None):
    """The preview of one theme as a PIL image (SIZE, RGB)."""
    conf = T.load(name, user=False)
    bar, panel = palette(name, "bar"), palette(name, "panel")
    picture = wallpaper(name, output, walldir)
    if picture:
        try:
            img = cover(picture, SIZE)
        except (OSError, ValueError, Image.DecompressionBombError):
            picture = None
    if not picture:
        bg = hex_rgba(conf.get("term.background"), (7, 9, 15, 255))
        end = tuple(clamp(a * 0.75 + b * 0.25) for a, b in zip(bg, panel["cyan"]))
        img = gradient(SIZE, bg, (*end[:3], 255))
    path = font_file(name)
    small, body, title = font(path, 9), font(path, 11), font(path, 15)
    radius = rounding(name)
    img = draw_bar(img, bar, body, radius)
    img = draw_card(img, panel, (small, body, title), radius, conf.get("name") or name)
    return img.convert("RGB")


# -- the cache -------------------------------------------------------------------------------
def inputs(name, output=None, walldir=None):
    """The files a preview is made from (missing ones too: a file that
    appears later must change the key)."""
    files = [os.path.join(T.theme_dir(link), "theme.conf") for link in T.chain(name)]
    files += [os.path.join(T.theme_dir(name), f) for f in ("waybar.css", "panel.css")]
    s = season(name)
    if s:
        # The season in effect: its accent= and palette, and the css it adds
        # to the theme's own (winter/waybar.css, summer/panel.css). The path
        # names the season, so the key also moves when the season turns.
        files += [os.path.join(T.season_dir(name, s), f)
                  for f in ("theme.conf", "palette.css", "waybar.css", "panel.css")]
    for _, bases in BASES.values():
        files += list(bases)
    files.append(README)
    picture = wallpaper(name, output, walldir)
    if picture:
        files.append(picture)
    files.append(font_file(name))
    return files


def season(name):
    """The season theme `name` shows now ("" for a theme without seasons)."""
    return T.load(name, user=False).get("season", "")


def key(name, output=None, walldir=None):
    h = hashlib.sha256(f"{VERSION}|{SIZE}|{name}|{season(name)}".encode())
    for path in inputs(name, output, walldir):
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            stamp = -1
        h.update(f"|{path}={stamp}".encode())
    return h.hexdigest()


def cached_key(path):
    try:
        with Image.open(path) as im:
            return im.text.get(KEY_CHUNK, "")
    except (OSError, ValueError, AttributeError):
        return ""


def path_of(name, cache=None):
    return os.path.join(cache or CACHE, f"{name}.png")


def stale(name, cache=None, output=None, walldir=None):
    return cached_key(path_of(name, cache)) != key(name, output, walldir)


def preview(name, cache=None, force=False, output=None, walldir=None):
    """The path of the theme's preview, made first when missing or stale."""
    path = path_of(name, cache)
    want = key(name, output, walldir)
    if not force and cached_key(path) == want:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    info = PngImagePlugin.PngInfo()
    info.add_text(KEY_CHUNK, want)
    tmp = f"{path}.{os.getpid()}.tmp"
    render(name, output, walldir).save(tmp, "PNG", pnginfo=info, optimize=False)
    os.replace(tmp, path)       # atomic: the page may be reading it
    return path


def main(argv):
    force, as_json, cache, names = False, False, None, []
    args = iter(argv)
    for arg in args:
        if arg == "--force":
            force = True
        elif arg == "--json":
            as_json = True
        elif arg == "--cache":
            cache = next(args, None)
        elif arg in ("-h", "--help"):
            print(__doc__.split("\n\n")[1])
            return 0
        else:
            names.append(arg)
    known = dict(T.themes())
    for n in names:
        if n not in known:
            print(f"make-theme-previews: no theme {n!r} (theme.py list)", file=sys.stderr)
            return 2
    rows = []
    for n in names or list(known):
        rows.append({"name": n, "label": known[n], "about": about(n), "path": preview(n, cache, force)})
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for row in rows:
            print(row["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
