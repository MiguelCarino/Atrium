#!/usr/bin/env python3
"""Render "digital rain" stills for the matrix theme: columns of half-width
katakana and digits falling in phosphor green, each stream fading from a pale
head into dark green and then into black, with a few streams in front
(larger, brighter, a soft glow on the head) and most of them far behind.

    make-matrix-wallpaper.py --all              matrix-1..4.png for every
                                                monitor, into the slideshow
                                                folders (seeds 1..4)
    make-matrix-wallpaper.py --seed 3 -W 1720 -H 720 -o /tmp/x.png

--all writes ~/Pictures/Wallpapers/<OUTPUT>/matrix-<n>.png for every screen
connected now, each at its own size as it is seen (screens.py sizes(): a
rotated, portrait screen gets a portrait picture; 1920x1080 for the primary
when Hyprland is not running), one seed per n, so the screens change together -- the matrix theme's
slideshow set (wallpaper_prefix=matrix- in ~/.config/themes/matrix/theme.conf;
theme.py check matrix insists on the same names in every folder). Each
monitor gets its own render at its own size, not a crop: the rain is laid out
for that screen.

Same constraints as make-wallpaper.py, for the same reasons:
  * On an HDR screen SDR is mapped into the HDR range, so nothing reaches full
    scale: every channel is capped at PEAK, and the lit area is small -- the
    picture is mostly black, and most streams are the dim far layer.
  * The bar is glass over the top 36 px and blur smears whatever is bright
    under it, so the top band (QUIET px, scaled) is empty and the rain fades
    in below it.
  * A tiny noise dither hides the banding that big dark gradients get in
    8-bit.
  * Portrait works by construction: the rain falls down the picture as it is
    DISPLAYED (a portrait screen's folder holds portrait images), and glyph
    sizes follow the short side, so a glyph is about the same physical size
    on every screen of a usual desktop (~1080-1440 px over ~11-13 inches
    short side).

The glyphs: half-width katakana (U+FF66-FF9D), some of them mirrored as in
the film's rain, digits and a few symbols, drawn from Noto Sans Mono CJK JP
(Fedora's google-noto-sans-mono-cjk-vf-fonts), found through fc-match; IBM
Plex Mono covers the digits if the CJK face is missing. Every glyph is
rendered once per size into a mask, so a full 3440x1440 frame of ~10k glyphs
is a few seconds of numpy blits, not 10k text draws.

Deterministic: the same --seed and size always give the same image.
Pure numpy + Pillow (both installed).
"""

import argparse
import os
import random
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (scripts/screens.py: the screens and their sizes)

# Brightness ceiling, as a fraction of full scale (make-wallpaper.py uses
# 0.78). The pale heads are the only thing that gets near it.
PEAK = 0.78

# The theme's greens (matrix/theme.conf, waybar.css), 0..1.
HEAD   = (0.80, 1.00, 0.84)      # #ccffd6: a stream's leading glyph
BRIGHT = (0.00, 1.00, 0.255)     # #00ff41: the first cells behind it
MID    = (0.00, 0.56, 0.067)     # #008f11
DEEP   = (0.00, 0.23, 0.00)      # #003b00: the tail, just above black
FLOOR  = (0.000, 0.012, 0.004)   # the page: black with a breath of green

QUIET = 36          # px under the bar with no rain at all (the bar's height)
FADE = 70           # px over which the rain fades in below that

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
SEEDS = [1, 2, 3, 4]

KATAKANA = [chr(c) for c in range(0xFF66, 0xFF9E)]
DIGITS = list("0123456789")
SYMBOLS = list(":.=*+-<>|\"")


def font_file(pattern, fallback):
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if out and os.path.exists(out):
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return fallback


CJK = font_file("Noto Sans Mono CJK JP",
                "/usr/share/fonts/google-noto-sans-mono-cjk-vf-fonts/NotoSansMonoCJK-VF.ttc")
LATIN = font_file("IBM Plex Mono:style=Medium",
                  "/usr/share/fonts/ibm-plex-mono-fonts/IBMPlexMono-Medium.otf")


class Atlas:
    """Every glyph at one size as a float mask (cell-sized, 0..1), plus a
    mirrored copy of each katakana. masks[i] is drawn at a cell's top-left."""

    def __init__(self, size, cw, ch):
        self.cw, self.ch = cw, ch
        cjk = ImageFont.truetype(CJK, size) if os.path.exists(CJK) else None
        if cjk is not None:
            # The variable font opens at its lightest master, which turns
            # to hairlines at 17 px; Medium is what the film's rain weighs.
            try:
                cjk.set_variation_by_name("Medium")
            except (OSError, ValueError, AttributeError):
                pass
        latin = ImageFont.truetype(LATIN, int(size * 0.92))
        self.masks = []
        for chars, face, mirror in ((KATAKANA, cjk or latin, True),
                                    (DIGITS, latin, False),
                                    (SYMBOLS, latin, False)):
            for c in chars:
                m = self._draw(c, face)
                self.masks.append(m)
                if mirror:
                    self.masks.append(m[:, ::-1].copy())
        # Katakana dominate the rain, as in the film; digits are the
        # second most common, symbols rare.
        nk = len(KATAKANA) * 2
        nd = len(DIGITS)
        w = [1.0] * nk + [1.6] * nd + [0.5] * (len(self.masks) - nk - nd)
        total = sum(w)
        self.weights = [x / total for x in w]

    def _draw(self, c, face):
        img = Image.new("L", (self.cw, self.ch), 0)
        d = ImageDraw.Draw(img)
        box = d.textbbox((0, 0), c, font=face)
        x = (self.cw - (box[2] - box[0])) / 2 - box[0]
        y = (self.ch - (box[3] - box[1])) / 2 - box[1]
        d.text((x, y), c, font=face, fill=255)
        return np.asarray(img, np.float32) / 255.0

    def pick(self, rng):
        return self.masks[rng.choices(range(len(self.masks)), self.weights)[0]]


def ramp(t):
    """Colour of a trail cell, t = 0 at the head .. 1 at the tail's end:
    pale head -> #00ff41 -> #008f11 -> #003b00 -> nothing."""
    stops = [(0.00, HEAD, 1.00), (0.06, BRIGHT, 0.95), (0.30, MID, 0.85),
             (0.70, DEEP, 0.75), (1.00, DEEP, 0.0)]
    for (t0, c0, a0), (t1, c1, a1) in zip(stops, stops[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            col = tuple(c0[i] + (c1[i] - c0[i]) * u for i in range(3))
            return col, a0 + (a1 - a0) * u
    return DEEP, 0.0


def blit(canvas, mask, x, y, rgb, a):
    """Lighten-blend one glyph into the canvas (max, not add: overlapping
    streams must not sum into a hot spot -- that is exactly the glare the
    HDR panel punishes)."""
    H, W, _ = canvas.shape
    h, w = mask.shape
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x, None] * a
    patch = m * np.asarray(rgb, np.float32)
    region = canvas[y0:y1, x0:x1]
    np.maximum(region, patch, out=region)


def layer(W, H, rng, size, density, bright, trail, heads):
    """One depth of rain on its own canvas. size: glyph px; density: streams
    per column on average; bright: the layer's overall level; trail: (min,
    max) stream length in cells; heads: chance a stream shows its head (the
    rest have already run off the bottom, or start above the top)."""
    cw = max(6, int(size * 0.82))
    ch = max(8, int(size * 1.08))
    atlas = Atlas(size, cw, ch)
    canvas = np.zeros((H, W, 3), np.float32)
    head_pts = []
    rows = H // ch + 2
    for col in range(W // cw + 1):
        x = col * cw
        n = sum(1 for _ in range(8) if rng.random() < density / 8)
        for _ in range(n):
            length = rng.randint(*trail)
            # The head's row: anywhere from above the top to below the
            # bottom, so some streams are cut off at either edge.
            head = rng.randint(-length // 3, rows + length // 3)
            show_head = rng.random() < heads
            level = bright * rng.uniform(0.55, 1.0)
            for k in range(length):
                r = head - k
                if r < 0 or r >= rows:
                    continue
                t = k / max(1, length - 1)
                if k == 0 and not show_head:
                    continue
                rgb, a = ramp(t if show_head else 0.06 + t * 0.94)
                # A few cells flicker: the "glitch" of a glyph changing.
                if rng.random() < 0.035:
                    rgb, a = BRIGHT, min(1.0, a * 1.4 + 0.2)
                blit(canvas, atlas.pick(rng), x, r * ch, rgb, a * level)
            if show_head and 0 <= head < rows:
                head_pts.append((x + cw // 2, head * ch + ch // 2, level))
    return canvas, head_pts, cw, ch


def render(W, H, seed):
    rng = random.Random(seed)
    k = min(W, H) / 1440          # glyph sizes follow the short side
    bg = np.zeros((H, W, 3), np.float32)
    bg[:] = FLOOR

    # Far to near. The far layer is most of the picture and stays dim; the
    # near one is sparse, big and the only one with real glow.
    layers = [
        dict(size=int(17 * k), density=0.9, bright=0.30, trail=(10, 34), heads=0.25),
        dict(size=int(24 * k), density=0.55, bright=0.62, trail=(8, 26), heads=0.45),
        dict(size=int(34 * k), density=0.17, bright=0.92, trail=(6, 18), heads=0.75),
    ]
    # A portrait screen has more rows per column than the trails are long,
    # so at the landscape density it looks thinned out: scale the streams
    # per column by how much taller than the short side the picture is.
    for spec in layers:
        spec["density"] *= H / min(W, H)
    out = bg
    glow_pts = []
    for spec in layers:
        canvas, heads, cw, ch = layer(W, H, rng, **spec)
        out = np.maximum(out, canvas)
        glow_pts += [(x, y, lv, cw) for x, y, lv in heads if spec["bright"] > 0.5]

    # Glow: soft green halos round the near heads, drawn small and blurred,
    # then ADDED at low strength -- light bleeding into the air, not a disc.
    glow = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(glow)
    for x, y, lv, cw in glow_pts:
        r = cw * 0.9
        d.ellipse((x - r, y - r, x + r, y + r), fill=int(255 * min(1.0, lv)))
    glow = np.asarray(glow.filter(ImageFilter.GaussianBlur(max(2, 10 * k))), np.float32) / 255.0
    out = out + glow[..., None] * np.asarray(BRIGHT, np.float32) * 0.22

    # Vignette: the corners sink into black, so the edge of the screen is
    # quiet and the bezels do not frame a bright band.
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx = (xx - W / 2) / (W / 2)
    dy = (yy - H / 2) / (H / 2)
    v = np.clip(1.0 - 0.38 * (dx * dx + dy * dy) ** 1.2, 0.35, 1.0)
    out = out * v[..., None]

    # Under the bar: nothing for QUIET px, then a fade -- in pixels, not
    # design units, because the bar is 36 px on every screen.
    band = np.clip((yy[:, :1] - QUIET) / FADE, 0.0, 1.0) ** 1.5
    out = FLOOR + (out - FLOOR) * band[..., None]

    # PEAK: hard cap per channel (the HDR rule), then 8-bit with a +-1 dither
    # so the dark floor does not band.
    out = np.clip(out, 0.0, PEAK)
    px = out * 255.0 + np.random.default_rng(seed).uniform(-0.5, 0.5, out.shape)
    return Image.fromarray(np.clip(np.rint(px), 0, 255).astype(np.uint8), "RGB")


def write(img, path):
    """Beside the target, then renamed over it: the slideshow may hand this
    path to hyprpaper at any moment, and a half-written PNG is a blank screen."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    try:
        img.save(tmp, "PNG")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    print(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true",
                    help="matrix-1..4.png for every monitor folder")
    ap.add_argument("-o", "--output", help="one image to this path")
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.all:
        # One monitor at a time, one image at a time: a 3440x1440 float
        # canvas per layer is ~60 MB, and this box is shared.
        for n, seed in enumerate(SEEDS, 1):
            for mon, (w, h) in screens.sizes().items():
                write(render(w, h, seed), os.path.join(WALLDIR, mon, f"matrix-{n}.png"))
        return
    if not a.output:
        ap.error("give -o FILE, or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size()
    if a.width <= 0 or a.height <= 0:
        ap.error("width/height must be positive")
    write(render(a.width, a.height, a.seed), a.output)


if __name__ == "__main__":
    main()
