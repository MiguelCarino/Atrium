#!/usr/bin/env python3
"""Build the icon themes the desktop themes point at (icon_theme= in
~/.config/themes/<name>/theme.conf; theme.py sets it through gsettings).

    make-icon-theme.py --all        every variant below
    make-icon-theme.py win95        one of them
    make-icon-theme.py --list       the variants
    make-icon-theme.py --sheet win95 -o /tmp/x.png
                                    a contact sheet of what the filter made,
                                    pixel-doubled, for a look before switching

Each variant is a real XDG icon theme in ~/.local/share/icons/<Dir>/ that
INHERITS the set it filters, so it holds only the icons it changes and
everything else (above all the -symbolic ones libadwaita draws its buttons
with, which the stylesheets recolour anyway) falls through unchanged:

    win95  ~/.local/share/icons/Win95/, Inherits=Chicago95,Adwaita,hicolor.
           Chicago95 (grassmunk, GPL-3.0+/MIT; README in its folder) is the
           hand-drawn Windows 95 set; this fills the apps it lacks: an alias
           first (ALIASES: Ptyxis -> its terminal, winemine -> Minesweeper),
           copied; else the app's Papirus icon (SOURCE) through the 16-colour
           filter -- saturation up, a light 2x2 dither, nearest of the 16
           Windows 95 colours, on/off alpha, a 1px black rim; 64..256 are
           those pixel-doubled, never smoothed.
    cyberpunk ~/.local/share/icons/Neon/,
           Inherits=Sweet-Rainbow,candy-icons,breeze-dark,Adwaita,hicolor.
           Designed sets first: Sweet-Rainbow's folders (cyan-to-mauve
           outlines) and Candy's gradient app icons (EliverLara, GPL-3; in
           ~/.local/share/icons). The apps Candy lacks: an alias into Candy
           if there is one, else TRACED (trace(): the Papirus icon flattened
           to a few colour regions, drawn as their borders) in Sweet-Rainbow's
           own gradient over a dark glass body -- neon_icon(). Paintings
           are not traced: a full-bleed picture keeps itself in a rounded
           gradient frame, other painted art (many colours, or a Steam game
           icon) keeps itself with a soft neon halo.
    moe    ~/.local/share/icons/Moe/, Inherits=Papirus,Adwaita,hicolor.
           Papirus (the light one: moe's chrome is pastel) with PINK folders:
           what papirus-folders does, done as links in this theme rather than
           edits to Papirus itself (folder_links()). No filter.
    lofi   ~/.local/share/icons/Lofi/, Inherits=Papirus-Dark,Papirus,Adwaita,
           hicolor. The same recolouring with PALE ORANGE folders (the lamp's
           peach), over Papirus-DARK: lofi's chrome is dusk violet, so the
           symbolic and panel icons want the light-on-dark set. The folder
           links point into Papirus's places (the folders are the same art in
           both). No filter, so no NATIVE sizes.
    luna   ~/.local/share/icons/Luna/, Inherits=Papirus,Adwaita,hicolor.
           The same recolouring with YELLOW folders: Papirus's folder-yellow
           is the nearest open match to the manila folders the XP era is
           remembered by (drawing XP's own icons, or a set that copies them,
           would be Microsoft's trade dress). Over the LIGHT Papirus, as moe:
           luna's cards are cream, and Papirus's dark symbolic icons suit
           them. No filter, so no NATIVE sizes.
    orbit  ~/.local/share/icons/Orbit/, Inherits=Papirus-Dark,Papirus,
           Adwaita,hicolor. Built as lofi is: Papirus-DARK (orbit's consoles
           are slate navy, so the symbolic and panel icons want the
           light-on-dark set) with BLUE-GREY folders -- the steel of the
           console rules, quieter than the telemetry teal, which stays for
           focus and the accent. No filter, so no NATIVE sizes.
    seasons-spring / -summer / -autumn / -winter
           ~/.local/share/icons/Seasons-Spring/ (-Summer, -Autumn, -Winter),
           Inherits=Papirus-Dark,Papirus,Adwaita,hicolor. Four variants of
           one theme, built as lofi is (Papirus-DARK: every season is
           dark-based), each with its season's folder colour: PINK blossom,
           GREEN deep leaf, DEEPORANGE rust leaf, BLUE frost. Each season's
           theme.conf (themes/seasons/season/<s>/) names its variant, so the
           folders turn with the season through gsettings, live. No filter.
    matrix ~/.local/share/icons/Phosphor/, Inherits=Adwaita,hicolor.
           Everything traced, green line art on an opaque near-black body
           (the look asked for): Adwaita's full-colour names (folders, files,
           devices) and every app, drawn from Papirus's flat versions --
           flat art traces into clean lines where Adwaita's gradients traced
           into tangles. Photos and game art become a black-to-green duotone
           in a green frame -- phosphor_icon().

Tracing (trace()) works at 4x (2x at 256): a light blur, a median-cut down to
5 colours (3 at 16/24, so small icons keep only their big shapes), a mode
filter so specks join their region, borders between regions dilated to
about 1 px at 16 .. 5 px at 256, then Lanczos down -- smooth, even lines.
Papirus (PapirusDevelopmentTeam, GPL-3): Papirus and Papirus-Dark, the
user's copy in ~/.local/share/icons first, else the system's in
/usr/share/icons (Fedora: papirus-icon-theme, papirus-icon-theme-dark --
Atrium's packages/dnf.txt installs both); papirus_dir() finds it. Without
any, nothing is built. The designed bases (Chicago95, candy-icons,
Sweet-Rainbow) are not packaged and are optional: without them win95 and
cyberpunk trace every app instead of only the ones the base lacks, and
the missing name in Inherits= is skipped (Adwaita draws the rest);
`theme.py check` names what is missing. The two earlier filters (Sobel edges on Adwaita) made
tangles of texture and were replaced, not kept.

Run again after installing an app (its icon is not in the filtered set until
then; it shows its own colours meanwhile). A build replaces its folder
whole -- only a folder this script made (it leaves .made-by-make-icon-theme
in it) -- and is made in <Dir>.building first, swapped in only when it is
complete, so a failed build leaves the old set working. GTK apps pick a changed theme up
live; mako's icon-path is set by theme.py from the same key.

Deterministic: the same installed apps always give the same files.
Needs Gtk 3 (lookup and SVG rendering, as GTK itself would draw the source),
numpy and Pillow; a few seconds per variant.
"""

import argparse
import configparser
import glob
import os
import shutil
import subprocess
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402

HOME = os.path.expanduser("~")
ICONS = os.path.join(HOME, ".local", "share", "icons")
MARKER = ".made-by-make-icon-theme"

# The 16 colours of a Windows 95 icon (the VGA palette, Windows' order).
W95_PALETTE = np.array([[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in (
    0x000000, 0x800000, 0x008000, 0x808000, 0x000080, 0x800080, 0x008080, 0xc0c0c0,
    0x808080, 0xff0000, 0x00ff00, 0xffff00, 0x0000ff, 0xff00ff, 0x00ffff, 0xffffff)], float)
W95_WEIGHT = np.array([0.30, 0.59, 0.11])      # luma weights: green errors cost most
BAYER2 = np.array([[0, 2], [3, 1]]) / 4 - 0.375
DITHER = 32                                     # dither amplitude, in 0..255 steps
# (64 while the source was Adwaita's gradients; Papirus is flat, and its
# colours land on the 16 with less help -- less dither, less speckle.)
SATURATE = 1.8

OUTLINE_GREEN = np.array([0x3d, 0xdc, 0x68], float)     # the matrix accent
OUTLINE_FILL = np.array([0x04, 0x0a, 0x06], float)
OUTLINE_LO, OUTLINE_HI = 0.06, 0.20
# Neon's lines run the gradient of Sweet-Rainbow's folders (cyan at the left
# to a soft mauve at the right), so a traced app sits beside them as one set.
NEON_FROM = np.array([0, 255, 255], float)
NEON_TO = np.array([165, 83, 168], float)
NEON_FILL = np.array([0x06, 0x08, 0x10], float)          # the panels' near-black
NEON_FILL_ALPHA = 0.45                                    # a dark glass body, not opaque
NEON_GLOW = 0.45                                          # halo strength, 0..1
# Where the traced icons come from: Papirus's flat art (solid shapes, few
# colours) traces into clean lines; Adwaita's gradients and textures traced
# into tangles. Papirus-Dark inherits breeze-dark and hicolor, so an app it
# lacks is traced from the icon the app ships.
SOURCE = "Papirus-Dark"

# app icon -> icons that show the same thing, best first; the first one the
# variant's designed base (Chicago95, Candy) has is COPIED, not traced. Only
# for apps those bases lack under their own name.
ALIASES = {
    "org.gnome.Ptyxis": ["org.gnome.Terminal", "utilities-terminal", "terminal"],
    "kitty": ["kitty", "utilities-terminal", "terminal"],
    "com.system76.CosmicTerm": ["utilities-terminal", "terminal", "org.gnome.Terminal"],
    "com.system76.CosmicFiles": ["system-file-manager", "org.gnome.Nautilus", "file-manager"],
    "com.system76.CosmicEdit": ["accessories-text-editor", "org.gnome.TextEditor", "text-editor"],
    "com.system76.CosmicSettings": ["preferences-system", "org.gnome.Settings", "systemsettings"],
    "com.system76.CosmicStore": ["system-software-install", "org.gnome.Software", "software-store"],
    "com.system76.CosmicPlayer": ["multimedia-video-player", "video-player", "totem"],
    "com.system76.CosmicScreenshot": ["applets-screenshooter", "org.gnome.Screenshot", "screenshot"],
    "org.gnome.Settings": ["preferences-system", "systemsettings"],
    "org.gnome.tweaks": ["preferences-desktop-theme", "gnome-tweaks"],
    "org.gnome.Characters": ["accessories-character-map", "gucharmap"],
    "org.gnome.font-viewer": ["preferences-desktop-font", "font-viewer"],
    "org.gnome.Loupe": ["image-viewer", "eog"],
    "org.gnome.Papers": ["org.gnome.Evince", "evince", "document-viewer"],
    "okular": ["org.gnome.Evince", "evince"],
    "org.gnome.Epiphany": ["epiphany", "web-browser"],
    "org.gnome.Yelp": ["help-browser", "yelp"],
    "winhelp": ["help-browser"],
    "org.gnome.Weather": ["gnome-weather", "weather"],
    "org.gnome.clocks": ["clock", "gnome-clocks"],
    "org.gnome.Logs": ["logviewer", "gnome-logs"],
    "org.gnome.Contacts": ["office-address-book", "contacts"],
    "org.gnome.Connections": ["preferences-desktop-remote-desktop", "remmina"],
    "org.remmina.Remmina": ["preferences-desktop-remote-desktop", "remmina"],
    "org.gnome.Snapshot": ["accessories-camera", "cheese", "camera"],
    "org.gnome.Showtime": ["multimedia-video-player", "video-player", "totem"],
    "mpv": ["mpv", "multimedia-video-player", "video-player"],
    "org.gnome.Decibels": ["multimedia-audio-player", "audio-player"],
    "org.pulseaudio.pavucontrol": ["multimedia-volume-control", "pavucontrol", "audio-volume-high"],
    "gnome-color-manager": ["preferences-color", "colors"],
    "displaycal": ["displaycal", "preferences-color", "colors"],
    "nvtop": ["gnome-system-monitor", "utilities-system-monitor", "htop"],
    "keepassxc": ["keepassxc", "password", "dialog-password"],
    "com.google.Chrome": ["google-chrome", "chrome"],
    "fcitx": ["fcitx", "preferences-desktop-locale"],
    "im-chooser": ["preferences-desktop-locale", "input-keyboard"],
    "gscan2pdf": ["scanner", "simple-scan"],
    "notepad": ["accessories-text-editor"],
    "wordpad": ["office-writer", "libreoffice-writer"],
    "winemine": ["gnome-mines", "mines"],
    "winefile": ["system-file-manager", "wine"],
    "winecfg": ["preferences-system", "wine", "winecfg"],
    "regedit": ["wine", "preferences-system"],
    "msiexec": ["wine", "system-software-install"],
    "org.gnome.Tour": ["help-about", "help-browser"],
    "rygel": ["network-server", "multimedia"],
    "com.rustdesk.RustDesk": ["rustdesk", "preferences-desktop-remote-desktop"],
    "org.deskflow.deskflow": ["deskflow", "synergy", "input-mouse"],
}
# displaycal-* (curve viewer, profile info...) all mean "colour tools".
ALIAS_PREFIXES = {"displaycal-": ["preferences-color", "colors"]}


def aliases(name):
    return ALIASES.get(name) or next((t for p, t in ALIAS_PREFIXES.items() if name.startswith(p)), [])


NATIVE = {"win95": [16, 24, 32, 48], "matrix": [16, 24, 32, 48, 64, 96, 128, 256],
          "cyberpunk": [16, 24, 32, 48, 64, 96, 128, 256]}
# win95's big sizes: (size, drawn from, factor) -- nearest-neighbour only.
DOUBLED = [(64, 32, 2), (96, 48, 2), (128, 32, 4), (256, 32, 8)]

VARIANTS = {
    "win95": dict(dir="Win95", name="Windows 95",
                  comment="Chicago95 plus every other app in 16 colours (make-icon-theme.py)",
                  inherits="Chicago95,Adwaita,hicolor", cover=("Chicago95",)),
    "cyberpunk": dict(dir="Neon", name="Neon",
                      comment="Sweet-Rainbow folders, Candy apps, and the rest traced in their neon (make-icon-theme.py)",
                      inherits="Sweet-Rainbow,candy-icons,breeze-dark,Adwaita,hicolor",
                      cover=("Sweet-Rainbow", "candy-icons")),
    "moe": dict(dir="Moe", name="Moe",
                comment="Papirus with pink folders (make-icon-theme.py)",
                inherits="Papirus,Adwaita,hicolor", cover=None, folder_colour="pink"),
    "lofi": dict(dir="Lofi", name="Lo-fi",
                 comment="Papirus-Dark with pale orange folders (make-icon-theme.py)",
                 inherits="Papirus-Dark,Papirus,Adwaita,hicolor", cover=None, folder_colour="paleorange"),
    "luna": dict(dir="Luna", name="Luna",
                 comment="Papirus with yellow (manila) folders (make-icon-theme.py)",
                 inherits="Papirus,Adwaita,hicolor", cover=None, folder_colour="yellow"),
    "orbit": dict(dir="Orbit", name="Orbit",
                  comment="Papirus-Dark with blue-grey (steel) folders (make-icon-theme.py)",
                  inherits="Papirus-Dark,Papirus,Adwaita,hicolor", cover=None, folder_colour="bluegrey"),
    # The seasons theme's four variants: one folder colour each. The name
    # says the season, so the four are told apart in an icon-theme picker.
    "seasons-spring": dict(dir="Seasons-Spring", name="Seasons (spring)",
                           comment="Papirus-Dark with pink (blossom) folders (make-icon-theme.py)",
                           inherits="Papirus-Dark,Papirus,Adwaita,hicolor", cover=None, folder_colour="pink"),
    "seasons-summer": dict(dir="Seasons-Summer", name="Seasons (summer)",
                           comment="Papirus-Dark with green (deep leaf) folders (make-icon-theme.py)",
                           inherits="Papirus-Dark,Papirus,Adwaita,hicolor", cover=None, folder_colour="green"),
    "seasons-autumn": dict(dir="Seasons-Autumn", name="Seasons (autumn)",
                           comment="Papirus-Dark with deep orange (rust leaf) folders (make-icon-theme.py)",
                           inherits="Papirus-Dark,Papirus,Adwaita,hicolor", cover=None, folder_colour="deeporange"),
    "seasons-winter": dict(dir="Seasons-Winter", name="Seasons (winter)",
                           comment="Papirus-Dark with blue (frost) folders (make-icon-theme.py)",
                           inherits="Papirus-Dark,Papirus,Adwaita,hicolor", cover=None, folder_colour="blue"),
    "matrix": dict(dir="Phosphor", name="Phosphor",
                   comment="Papirus traced as green line art on black (make-icon-theme.py)",
                   inherits="Adwaita,hicolor", cover=None),
}


# -- finding icons -------------------------------------------------------------
def theme(name):
    t = Gtk.IconTheme()
    t.set_custom_theme(name)
    return t


def app_icons():
    """Icon= of every .desktop file a launcher would show, by name (paths
    and NoDisplay/Hidden entries left out), sorted for determinism."""
    dirs = [os.path.join(HOME, ".local", "share")]
    dirs += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    names = set()
    for d in dirs:
        for path in glob.glob(os.path.join(d, "applications", "*.desktop")):
            parser = configparser.RawConfigParser(strict=False, interpolation=None)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if entry.get("NoDisplay") == "true" or entry.get("Hidden") == "true":
                continue
            icon = entry.get("Icon", "").strip()
            if icon and not os.path.isabs(icon):
                names.add(icon)
    return sorted(names)


def in_theme(t, name, theme_dirs):
    """Does `name` resolve inside one of `theme_dirs` itself (not via
    hicolor or a further inherited set)?"""
    info = t.lookup_icon(name, 32, 0)
    path = info.get_filename() if info else None
    return bool(path) and any(f"/{d}/" in path for d in theme_dirs)


def render(t, name, size):
    """`name` from theme `t` at exactly size x size, RGBA, or None."""
    info = t.lookup_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
    if not info:
        return None
    try:
        pb = info.load_icon()
    except Exception:  # GLib.Error: a broken file in someone's icon folder
        return None
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    im = Image.frombytes("RGBA", (pb.get_width(), pb.get_height()), pb.get_pixels(),
                         "raw", "RGBA", pb.get_rowstride())
    if im.size != (size, size):     # a non-square source: centre it
        im.thumbnail((size, size), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size))
        canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
        im = canvas
    return im


# -- the filters ---------------------------------------------------------------
def win95(im):
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(SATURATE)).enhance(1.1)
    a = np.asarray(im, float)
    shape = a[..., 3] >= 128
    h, w = shape.shape
    rgb = a[..., :3] + np.tile(BAYER2, (h // 2 + 1, w // 2 + 1))[:h, :w, None] * DITHER
    dist = (((rgb[:, :, None, :] - W95_PALETTE[None, None]) ** 2) * W95_WEIGHT).sum(-1)
    out = np.zeros(a.shape)
    out[..., :3] = W95_PALETTE[dist.argmin(-1)]
    out[..., 3] = shape * 255
    mask = Image.fromarray((shape * 255).astype(np.uint8))
    rim = (np.asarray(mask.filter(ImageFilter.MaxFilter(3))) > 0) & ~shape
    out[rim] = [0, 0, 0, 255]
    return Image.fromarray(out.astype(np.uint8))


def richness(im):
    """(coverage, colours) of a 48px render: how much of its square it fills,
    and how many distinct 15-bit colours it has."""
    a = np.asarray(im)
    shape = a[..., 3] > 128
    rgb = a[..., :3][shape].astype(int) >> 3
    return shape.mean(), len(np.unique(rgb[:, 0] * 1024 + rgb[:, 1] * 32 + rgb[:, 2]))


def is_photo(im):
    """A picture rather than a drawing (Steam's game covers): fills its
    square and has hundreds of colours. Tracing those makes noise."""
    coverage, colours = richness(im)
    return coverage >= 0.85 and colours > 350


# Icons that are paintings whatever their colours say: Steam's per-game
# icons (key art, mandalas, logos on texture). Measured, they could not be
# told from busy-but-traceable drawings (the Settings gear traced as busy as
# a game cover), so they are named instead.
ART_PREFIXES = ("steam_icon_",)


def is_art(name):
    return name.startswith(ART_PREFIXES)


def is_rich(im):
    """Painted art of any shape -- a shaded logo, a mandala -- traced into
    noise just the same; kept as it is."""
    return richness(im)[1] > 350


def trace(t, name, size):
    """(lines, alpha) at `size`, both 0..1, or None: the icon reduced to a few
    flat colour regions and drawn as the borders between them (its
    silhouette included). Worked at 4x (2x at 256) and scaled down with
    Lanczos, so the lines come out smooth and even, about 1 px at 16 and
    ~5 px at 256; small icons keep fewer regions, hence fewer lines."""
    scale = 2 if size >= 256 else 4
    big = size * scale
    im = render(t, name, big)
    if im is None:
        return None
    a = np.asarray(im, float) / 255
    alpha = a[..., 3]
    shape = alpha >= 0.5
    rgb = (a[..., :3] * alpha[..., None] + 0.5 * (1 - alpha[..., None])) * 255
    flat = Image.fromarray(rgb.astype(np.uint8)).filter(ImageFilter.GaussianBlur(big / 160))
    k = 3 if size <= 24 else 5
    q = flat.quantize(colors=k, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = q.filter(ImageFilter.ModeFilter(5))     # specks merge into their region
    lab = np.asarray(q).astype(int)
    lab[~shape] = -1
    edge = np.zeros(lab.shape, bool)
    edge[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    edge[1:, :] |= lab[1:, :] != lab[:-1, :]
    width = int(round(scale * (1 + size / 64))) | 1
    lines = Image.fromarray((edge * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(max(3, width)))
    lines = np.asarray(lines.resize((size, size), Image.LANCZOS), float) / 255
    alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).resize((size, size), Image.LANCZOS),
                       float) / 255
    return np.clip(lines, 0, 1), np.clip(alpha, 0, 1)


def rounded(size, radius):
    m = Image.new("L", (size * 4, size * 4), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius * 4, fill=255)
    return np.asarray(m.resize((size, size), Image.LANCZOS), float) / 255


def frame(size, width):
    """A rounded-square outline, 0..1, `width` px."""
    outer = rounded(size, size * 0.18)
    inner = np.zeros_like(outer)
    w = max(1, int(round(width)))
    if size - 2 * w > 0:
        inner[w:size - w, w:size - w] = rounded(size - 2 * w, max(1, size * 0.18 - w))
    return np.clip(outer - inner, 0, 1), outer


def gradient(size):
    x = np.linspace(0, 1, size)[None, :, None]
    return NEON_FROM * (1 - x) + NEON_TO * x


def win95_icon(t, name, size):
    im = render(t, name, size)
    return win95(im) if im is not None else None


def neon_icon(t, name, size):
    """Cyberpunk's: the traced lines in Sweet-Rainbow's cyan-to-mauve
    gradient over a dark glass body, a faint glow in the same colours; a
    photo is kept, its corners rounded, in a gradient frame."""
    col = np.broadcast_to(gradient(size), (size, size, 3))
    probe = render(t, name, 48)
    if probe is not None and (is_photo(probe) or (is_art(name) and richness(probe)[0] >= 0.85)):
        im = np.asarray(render(t, name, size), float)
        ring, inside = frame(size, 1 + size / 64)
        rgb = im[..., :3] * (1 - ring[..., None]) + col * ring[..., None]
        return Image.fromarray(np.dstack([rgb, np.maximum(inside * im[..., 3] / 255, ring) * 255]).astype(np.uint8))
    if probe is not None and (is_rich(probe) or is_art(name)):
        # Its own colours, a soft neon halo round its shape: of the set
        # without being shredded into lines.
        im = np.asarray(render(t, name, size), float)
        shape = im[..., 3] / 255
        halo = np.asarray(Image.fromarray((shape * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(max(1.0, size / 20))), float) / 255 * NEON_GLOW
        a = np.maximum(shape, halo)
        w = np.where(a > 0, shape / np.maximum(a, 1e-6), 0)[..., None]
        rgb = im[..., :3] * w + col * (1 - w)
        return Image.fromarray(np.dstack([rgb, np.clip(a, 0, 1) * 255]).astype(np.uint8))
    traced = trace(t, name, size)
    if traced is None:
        return None
    lines, alpha = traced
    glow = np.asarray(Image.fromarray((lines * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(max(1.0, size / 24))), float) / 255 * NEON_GLOW
    body = alpha * NEON_FILL_ALPHA
    a = np.maximum(np.maximum(body, lines), glow)
    lit = np.maximum(lines, glow)
    w = np.where(a > 0, lit / np.maximum(a, 1e-6), 0)[..., None]
    rgb = NEON_FILL * (1 - w) + col * w
    return Image.fromarray(np.dstack([rgb, np.clip(a, 0, 1) * 255]).astype(np.uint8))


def phosphor_icon(t, name, size):
    """Matrix's: the traced lines in the accent green on an opaque near-black
    body (the green outline and black fill asked for); a photo becomes a
    black-to-green duotone in a green frame."""
    probe = render(t, name, 48)
    if probe is not None and (is_photo(probe) or is_art(name)):
        im = np.asarray(render(t, name, size), float) / 255
        lum = (im[..., :3] @ [0.2126, 0.7152, 0.0722])[..., None]
        rgb = OUTLINE_FILL * (1 - lum) + OUTLINE_GREEN * lum
        ring, inside = frame(size, 1 + size / 64)
        rgb = rgb * (1 - ring[..., None]) + OUTLINE_GREEN * ring[..., None]
        return Image.fromarray(np.dstack([rgb, np.maximum(inside * im[..., 3], ring) * 255]).astype(np.uint8))
    traced = trace(t, name, size)
    if traced is None:
        return None
    lines, alpha = traced
    a = np.maximum(alpha, lines)
    rgb = OUTLINE_FILL * (1 - lines[..., None]) + OUTLINE_GREEN * lines[..., None]
    return Image.fromarray(np.dstack([rgb, np.clip(a, 0, 1) * 255]).astype(np.uint8))


# -- building ------------------------------------------------------------------
def plan(variant):
    """[(context dir, icon name, source theme, source name, filter or None)]:
    a filter is called as fn(theme, name, size); None copies the source."""
    v = VARIANTS[variant]
    jobs = []
    if v.get("folder_colour"):
        return jobs             # links only (folder_links()), nothing drawn
    if v["cover"]:
        # A designed base (Chicago95; Sweet-Rainbow + Candy): only the apps it
        # lacks, copied from it under another name if it has one, else made.
        base = v["cover"][0]
        cover = theme(base)
        fn = win95_icon if variant == "win95" else neon_icon
        for name in app_icons():
            if in_theme(cover, name, v["cover"]):
                continue
            target = next((a for a in aliases(name) if in_theme(cover, a, v["cover"])), None)
            if target:
                jobs.append(("apps", name, base, target, None))
            else:
                jobs.append(("apps", name, SOURCE, name, fn))
    else:
        # Matrix: everything traced -- Adwaita's full-colour names (folders,
        # files, devices), drawn from Papirus's flat versions, and every app.
        adwaita = "/usr/share/icons/Adwaita/scalable"
        for context in sorted(os.listdir(adwaita)):
            for f in sorted(os.listdir(os.path.join(adwaita, context))):
                name = f.rsplit(".", 1)[0]
                if not name.endswith("-symbolic"):
                    jobs.append((context, name, SOURCE, name, phosphor_icon))
        jobs += [("apps", name, SOURCE, name, phosphor_icon) for name in app_icons()]
    return jobs


def papirus_dir(home=HOME, data_dirs=None):
    """Papirus's folder: the user's copy (~/.local/share/icons/Papirus, as
    on a machine set up by hand) before the system's (XDG_DATA_DIRS, so
    /usr/share/icons/Papirus from papirus-icon-theme) -- the order GTK
    itself looks in. None when there is neither."""
    if data_dirs is None:
        data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    roots = [os.path.join(home, ".local", "share", "icons")] + [os.path.join(d, "icons") for d in data_dirs if d]
    return next((os.path.join(r, "Papirus") for r in roots
                 if os.path.isfile(os.path.join(r, "Papirus", "index.theme"))), None)


PAPIRUS = papirus_dir()


def folder_links(v, out):
    """papirus-folders' recolouring, as links in OUR theme instead of edits to
    Papirus (which matrix and cyberpunk trace from): for every folder-<c>-*
    and user-<c>-* icon of the colour, a link without the colour --
    folder.svg -> Papirus's folder-pink.svg, user-home.svg -> user-pink-home.svg
    -- at every size Papirus has them. Returns the (size, context) dirs made."""
    colour, made = v["folder_colour"], set()
    for size_dir in sorted(os.listdir(PAPIRUS)):
        places = os.path.join(PAPIRUS, size_dir, "places")
        if "@" in size_dir or not os.path.isdir(places):
            continue
        for f in sorted(os.listdir(places)):
            for prefix in (f"folder-{colour}", f"user-{colour}"):
                if f == prefix + ".svg" or f.startswith(prefix + "-"):
                    target = os.path.join(places, f)
                    if os.path.islink(target):
                        continue        # Papirus's own aliases among the colours
                    plain = f.replace(f"-{colour}", "", 1)
                    folder = os.path.join(out, size_dir, "places")
                    os.makedirs(folder, exist_ok=True)
                    os.symlink(target, os.path.join(folder, plain))
                    made.add((int(size_dir.split("x")[0]), "places"))
    return made


def build(variant, quiet=False):
    v = VARIANTS[variant]
    final = os.path.join(ICONS, v["dir"])
    if os.path.exists(final) and not os.path.exists(os.path.join(final, MARKER)):
        sys.exit(f"{final} exists and was not made by this script; not touching it")
    # Built beside the live set and swapped in only when complete: a build
    # that fails half-way (a filter bug did) must not leave the theme with
    # no icons at all.
    out = final + ".building"
    shutil.rmtree(out, ignore_errors=True)
    themes, made, skipped = {}, set(), []
    if v.get("folder_colour"):
        made |= folder_links(v, out)
    for context, name, src_theme, src_name, fn in (plan(variant) if not v.get("folder_colour") else []):
        t = themes.setdefault(src_theme, theme(src_theme))
        drawn = {}
        for size in NATIVE[variant]:
            im = fn(t, src_name, size) if fn else render(t, src_name, size)
            if im is None:
                break
            drawn[size] = im
        if not drawn:
            skipped.append(name)
            continue
        if variant == "win95":
            for size, base, factor in DOUBLED:
                if base in drawn:
                    drawn[size] = drawn[base].resize((base * factor,) * 2, Image.NEAREST)
        for size, im in drawn.items():
            folder = os.path.join(out, f"{size}x{size}", context)
            os.makedirs(folder, exist_ok=True)
            im.save(os.path.join(folder, name + ".png"), optimize=True)
            made.add((size, context))
    os.makedirs(out, exist_ok=True)     # nothing drawn (no source at all) still makes a valid, empty set
    write_index(out, v, made)
    open(os.path.join(out, MARKER), "w").close()
    subprocess.run(["gtk-update-icon-cache", "-f", "-q", out], check=False)
    old = final + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(final):
        os.rename(final, old)
    os.rename(out, final)
    shutil.rmtree(old, ignore_errors=True)
    out = final
    if not quiet:
        count = (len({n for _, n, *_ in plan(variant)}) - len(skipped)) if not v.get("folder_colour") \
            else sum(len(fs) for _, _, fs in os.walk(out))
        print(f"{variant}: {count} icons in {out}"
              + (f"; no source for {', '.join(skipped)}" if skipped else ""))


CONTEXT_NAMES = {"apps": "Applications", "devices": "Devices", "mimetypes": "MimeTypes",
                 "places": "Places", "status": "Status", "emblems": "Emblems"}


def write_index(out, v, made):
    dirs = sorted(made)
    lines = ["[Icon Theme]", f"Name={v['name']}", f"Comment={v['comment']}",
             f"Inherits={v['inherits']}", "Example=folder",
             "Directories=" + ",".join(f"{s}x{s}/{c}" for s, c in dirs), ""]
    for size, context in dirs:
        lines += [f"[{size}x{size}/{context}]", f"Size={size}",
                  f"Context={CONTEXT_NAMES.get(context, context.title())}", "Type=Fixed", ""]
    with open(os.path.join(out, "index.theme"), "w") as handle:
        handle.write("\n".join(lines))


def sheet(variant, path):
    """Source above, result below, both pixel-doubled, 12 per row."""
    jobs = plan(variant)
    cols, cell = 12, 104
    rows = (len(jobs) + cols - 1) // cols
    bg = (0x00, 0x6d, 0x6d, 255) if variant == "win95" else (0, 0, 0, 255)
    img = Image.new("RGBA", (cols * cell, rows * cell * 2), bg)
    themes = {}
    for k, (_, name, src_theme, src_name, fn) in enumerate(jobs):
        t = themes.setdefault(src_theme, theme(src_theme))
        x, y = (k % cols) * cell + 4, (k // cols) * cell * 2 + 4
        before = render(t, src_name, 48)
        after = fn(t, src_name, 48) if fn else before
        if before:
            img.alpha_composite(before.resize((96, 96), Image.NEAREST), (x, y))
        if after:
            img.alpha_composite(after.resize((96, 96), Image.NEAREST), (x, y + cell))
    img.save(path)
    print(path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("variant", nargs="?", choices=sorted(VARIANTS))
    p.add_argument("--all", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--sheet", metavar="VARIANT", choices=sorted(VARIANTS))
    p.add_argument("-o", "--output", default="/tmp/icon-sheet.png")
    args = p.parse_args()
    if args.list:
        for key, v in VARIANTS.items():
            print(f"{key:8} -> ~/.local/share/icons/{v['dir']}/  (Inherits={v['inherits']})")
    elif args.sheet:
        sheet(args.sheet, args.output)
    elif args.all or args.variant:
        if not PAPIRUS:
            sys.exit("no Papirus icon theme (~/.local/share/icons/Papirus or /usr/share/icons/Papirus):"
                     " sudo dnf install papirus-icon-theme papirus-icon-theme-dark")
        for variant in (sorted(VARIANTS) if args.all else [args.variant]):
            build(variant)
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
