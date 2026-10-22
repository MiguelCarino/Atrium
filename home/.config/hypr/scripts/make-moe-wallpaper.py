#!/usr/bin/env python3
"""Render wallpapers for the moe theme: pastel Japanese scenes -- cherry
blossoms on a soft sky, Mt. Fuji at dusk, sakura under the moon, and a
kawaii pattern of tiny hearts, stars and flowers -- all drawn from scratch
here (branches grown by a little recursive walk, blossoms built petal by
petal), not copies of anybody's picture.

    make-moe-wallpaper.py --all                 every variant, every monitor,
                                                into the slideshow folders
    make-moe-wallpaper.py -v fuji -W 1720 -H 720 -o /tmp/x.png
    make-moe-wallpaper.py --list                the variants

--all writes ~/Pictures/Wallpapers/<OUTPUT>/moe-<variant>.png for every
screen connected now at its LOGICAL size (what Hyprland lays out: the mode
over the scale, turned when the screen is rotated -- a 2560x1080 screen at
scale 0.8 is 3200x1350, a rotated one portrait; see logical_sizes(), the same
as make-matrix-rain.py's; 1920x1080 for the primary when Hyprland is not
running), the same names in every folder, so the screens change together (the moe theme's set:
wallpaper_prefix=moe- in ~/.config/themes/moe/theme.conf; `theme.py check
moe` insists on matching names). make-moe-sakura.py draws its falling-petal
video over this script's sakura-day picture.

Variants:
    sakura-day  a pale pink -> lavender -> faint sky gradient, two blossoming
                branches reaching in from the upper corners, drifting petals,
                soft bokeh and tiny four-point sparkles
    fuji        pastel dusk: Mt. Fuji in periwinkle with a pink-tinted cap,
                two ranges of hazy hills, a pale sun disc, drifting petals
    yozakura    night sakura: deep indigo-plum (never black), a large pale
                moon with its halo, stars, a glowing branch of pale blossoms
    kawaii      a diagonal pink/lavender gradient scattered with low-contrast
                hearts, stars and sakura flowers, and a few soft clouds

Same constraints as make-wallpaper.py, for the same reasons:
  * On an HDR screen SDR is mapped into the HDR range, so nothing reaches full
    scale: every channel is capped at PEAK, and the big fields (the skies)
    are pastels DIMMED to luminance <= ~0.6 -- a pastel sky is the largest
    area on the screen, and true near-white there would glare;
  * a tiny noise dither hides the banding a big smooth gradient gets in
    8-bit;
  * the bar sits on the top QUIET px: no branches, blossoms or sparkles
    there, they fade in below it over FADE px (the sky itself goes on).
Sizes follow the short side, so a blossom is about the same physical size
on every screen, portrait included; branch layout uses the long side.

How a blossom is made: five notched petals (a rounded teardrop with a small
V cut into its tip), each filled with a radial gradient from a pale centre
to the petal's pink, a darker pink line down the middle, then a ring of
thin stamens with golden tips. Drawn once per size at 4x on its own sprite
and scaled down (supersampled edges), then rotated and pasted -- a branch
holds a few hundred of them and redrawing each would be slow.

Deterministic: the same variant and size always give the same image.
Pure numpy + Pillow (both installed); a few seconds per ultrawide image.
"""

import argparse
import math
import os
import random
import sys
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (scripts/screens.py: the screens and their sizes)

PEAK = 0.80          # brightest channel value anywhere (make-wallpaper.py: 0.78)
SKY_LUM = 0.60       # ceiling for the luminance of the big sky fields
QUIET = 36           # px under the bar with no detail at all (the bar's height)
FADE = 70            # px over which the detail fades in below that

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
VARIANTS = ["sakura-day", "fuji", "yozakura", "kawaii"]


def logical_sizes():
    """{output: (W, H)} as Hyprland lays the monitors out: mode / scale,
    swapped when rotated (make-matrix-rain.py explains why the logical size:
    a fractional-scale monitor draws a window at it). screens.py's; without
    Hyprland, its 1920x1080 for the primary."""
    return screens.sizes(logical=True)


# -- colour helpers --------------------------------------------------------------
def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def lum(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def ramp(t, stops):
    """Colour at t (array, 0..1) along [(pos, '#rrggbb'), ...]."""
    pos = [p for p, _ in stops]
    cols = np.stack([hexc(c) for _, c in stops])
    return np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], -1).astype(np.float32)


def sky(W, H, stops, angle=0.0):
    """A gradient field: t runs top -> bottom, tilted by `angle` (0..1 adds
    some of x), luminance held under SKY_LUM."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = (yy / max(1, H - 1)) * (1 - angle) + (xx / max(1, W - 1)) * angle
    rgb = ramp(t, stops)
    over = np.maximum(lum(rgb) / SKY_LUM, 1.0)[..., None]
    return rgb / over


def over(canvas, layer):
    """Alpha-composite a float RGBA layer (H, W, 4) onto a float RGB canvas."""
    a = layer[..., 3:4]
    return canvas * (1 - a) + layer[..., :3] * a


def pil_layer(img):
    return np.asarray(img, np.float32) / 255.0


def blur_rgba(img, radius):
    """Gaussian blur of an RGBA image in PREMULTIPLIED form. PIL blurs the
    four channels independently, so the transparent black round a shape
    bleeds into its colour -- every cloud and bokeh disc came out with a
    dark rim. Premultiply, blur, divide back."""
    a = np.asarray(img, np.float32) / 255
    pre = a[..., :3] * a[..., 3:4]
    chans = [Image.fromarray((pre[..., i] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
             for i in range(3)]
    alpha = Image.fromarray((a[..., 3] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    al = np.asarray(alpha, np.float32) / 255
    rgb = np.dstack([np.asarray(c, np.float32) / 255 for c in chans]) / np.maximum(al[..., None], 1e-3)
    return np.dstack([np.clip(rgb, 0, 1), al])


# -- blossoms and petals ---------------------------------------------------------
def petal_points(length, width, notch=0.12, n=40):
    """Outline of one sakura petal pointing up (+y is down in images): narrow
    at the base (0, 0), widest about three quarters of the way out, then the
    two rounded lobes of the tip with a small V cut between them, the V's
    point at (0, -length * (1 - notch))."""
    def half(t):
        return 0.5 * width * t ** 0.6 * max(0.0, 1 - t ** 4) ** 0.5
    right = [(half(i / n * 0.985), -length * (i / n * 0.985)) for i in range(n + 1)]
    left = [(-x, y) for x, y in reversed(right)]
    return right + [(0.0, -length * (1 - notch))] + left


def blossom_sprite(radius, petal="#f393ba", centre="#fde3ee", vein="#d96c98",
                   stamen="#f2c94c", alpha=1.0, open_=1.0):
    """One five-petal sakura flower, RGBA, about 2*radius across. open_ < 1
    makes a half-open bloom (petals shorter, closer)."""
    ss = 4
    size = int(radius * 2.4 * ss) | 1
    c = size / 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    length = radius * ss * (0.75 + 0.25 * open_)
    width = length * 1.0
    for k in range(5):
        ang = math.radians(k * 72 - 90 + 8)
        cs, sn = math.cos(ang + math.pi / 2), math.sin(ang + math.pi / 2)
        pts = [(c + x * cs - y * sn, c + x * sn + y * cs) for x, y in petal_points(length, width)]
        md.polygon(pts, fill=255)
    m = np.asarray(mask, np.float32) / 255
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.hypot(xx - c, yy - c) / max(1.0, length)
    col = ramp(np.clip(d, 0, 1), [(0.0, centre), (0.18, centre), (0.55, petal), (1.0, petal)])
    # a faint darker line down each petal
    ang = np.arctan2(yy - c, xx - c)
    vein_w = np.zeros_like(d)
    for k in range(5):
        a0 = math.radians(k * 72 - 90 + 8)
        da = np.angle(np.exp(1j * (ang - a0)))
        vein_w = np.maximum(vein_w, np.exp(-(da / 0.035) ** 2) * (d > 0.22) * (d < 0.65))
    col = col * (1 - 0.22 * vein_w[..., None]) + hexc(vein) * (0.22 * vein_w[..., None])
    rgba = np.dstack([col, m * alpha])
    img = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA")
    d2 = ImageDraw.Draw(img)
    # stamens: thin lines out of the centre with golden tips
    rng = random.Random(int(radius * 1000) % 9973)
    for k in range(9):
        a = math.radians(k * 40 + rng.uniform(-12, 12))
        r1 = length * rng.uniform(0.20, 0.28)
        x1, y1 = c + r1 * math.cos(a), c + r1 * math.sin(a)
        d2.line([(c, c), (x1, y1)], fill=(232, 120, 150, int(200 * alpha)), width=max(1, ss // 2))
        rr = max(1.0, ss * radius / 34)
        d2.ellipse([x1 - rr, y1 - rr, x1 + rr, y1 + rr], fill=tuple(int(v * 255) for v in hexc(stamen)) + (int(255 * alpha),))
    return img.resize((size // ss, size // ss), Image.LANCZOS)


def petal_sprite(length, colour="#f6b3cb", alpha=0.85):
    """One loose petal (for drifting), pointing up, RGBA."""
    ss = 4
    L = length * ss
    size = int(L * 1.3) | 1
    img = Image.new("L", (size, size), 0)
    pts = petal_points(L, L * 0.72)
    cx, cy = size / 2, size / 2 + L / 2
    ImageDraw.Draw(img).polygon([(cx + x, cy + y) for x, y in pts], fill=255)
    m = np.asarray(img, np.float32) / 255
    yy = np.mgrid[0:size, 0:size][0].astype(np.float32)
    t = np.clip((cy - yy) / L, 0, 1)
    col = ramp(t, [(0.0, "#fde8f0"), (1.0, colour)])
    rgba = np.dstack([col, m * alpha])
    out = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA")
    return out.resize((max(2, size // ss),) * 2, Image.LANCZOS)


# -- branches --------------------------------------------------------------------
def grow(rng, x, y, ang, length, width, depth, segs):
    """A gnarled branch: a walk of short segments that bends a little each
    step and forks now and then. Appends (x0, y0, x1, y1, width) to segs and
    returns the tips [(x, y, width)]."""
    tips = []
    steps = rng.randint(6, 10)
    step = length / steps
    for i in range(steps):
        ang += rng.uniform(-0.28, 0.28)
        nx, ny = x + step * math.cos(ang), y + step * math.sin(ang)
        w = width * (1 - 0.55 * i / steps)
        segs.append((x, y, nx, ny, w))
        if depth > 0 and i > 0 and rng.random() < 0.45:
            side = rng.choice((-1, 1))
            tips += grow(rng, nx, ny, ang + side * rng.uniform(0.45, 0.95),
                         length * rng.uniform(0.35, 0.6), w * 0.62, depth - 1, segs)
        x, y = nx, ny
    tips.append((x, y, width * 0.45))
    return tips


def branch_layer(W, H, rng, k, start, ang, length, colours, blossom_kw, density=1.0, glow=None):
    """A branch with its blossoms, as a float RGBA layer. `start` is where it
    enters (just off the edge), `ang` its heading."""
    segs = []
    tips = grow(rng, start[0], start[1], ang, length, 26 * k, 3, segs)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    bark, bark_hi = colours
    for x0, y0, x1, y1, w in segs:
        w = max(1.5, w)
        d.line([(x0, y0), (x1, y1)], fill=bark, width=int(round(w)))
        r = w / 2
        d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=bark)
    # a thin lighter line along the upper side of the thicker limbs
    for x0, y0, x1, y1, w in segs:
        if w > 6 * k:
            d.line([(x0, y0 - w * 0.25), (x1, y1 - w * 0.25)], fill=bark_hi, width=max(1, int(w * 0.18)))
    layer = Image.fromarray((blur_rgba(layer, 0.6 * k) * 255).astype(np.uint8), "RGBA")
    # blossoms: clusters at the tips, scattered along the limbs
    sizes = [int(24 * k), int(30 * k), int(38 * k)]
    sprites = {}

    def sprite(r, o):
        key = (r, round(o, 1))
        if key not in sprites:
            sprites[key] = blossom_sprite(r, open_=o, **blossom_kw)
        return sprites[key]

    spots = []
    for x, y, w in tips:
        for _ in range(int(rng.randint(3, 6) * density)):
            spots.append((x + rng.gauss(0, 30 * k), y + rng.gauss(0, 26 * k)))
    for x0, y0, x1, y1, w in segs:
        if w < 20 * k and rng.random() < 0.7 * density:
            t = rng.random()
            spots.append((x0 + (x1 - x0) * t + rng.gauss(0, 10 * k), y0 + (y1 - y0) * t + rng.gauss(0, 10 * k)))
    rng.shuffle(spots)
    for x, y in spots:
        r = rng.choice(sizes)
        img = sprite(r, rng.choice((1.0, 1.0, 1.0, 0.75)))
        img = img.rotate(rng.uniform(0, 72), resample=Image.BICUBIC, expand=False)
        layer.alpha_composite(img, (int(x - img.width / 2), int(y - img.height / 2)))
        # a few buds beside the open flowers
        if rng.random() < 0.25:
            br = max(3, int(5 * k))
            bx, by = x + rng.uniform(-30, 30) * k, y + rng.uniform(-30, 30) * k
            ImageDraw.Draw(layer).ellipse([bx - br, by - br * 1.3, bx + br, by + br * 1.3],
                                          fill=tuple(int(v * 255) for v in hexc(blossom_kw.get("vein", "#e07fa4"))) + (230,))
    arr = pil_layer(layer)
    if glow is not None:
        halo = np.asarray(Image.fromarray((arr[..., 3] * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(18 * k)), np.float32) / 255
        g = np.dstack([np.broadcast_to(hexc(glow), arr.shape[:2] + (3,)), halo * 0.45])
        base = np.zeros_like(arr)
        base = g * (1 - arr[..., 3:4]) + arr * arr[..., 3:4]
        base[..., 3] = np.maximum(arr[..., 3], g[..., 3])
        base[..., :3] = np.where(base[..., 3:4] > 0,
                                 (g[..., :3] * g[..., 3:4] * (1 - arr[..., 3:4]) + arr[..., :3] * arr[..., 3:4])
                                 / np.maximum(base[..., 3:4], 1e-6), 0)
        arr = base
    return arr


# -- small things ------------------------------------------------------------------
def drifting_petals(W, H, rng, k, n, colour="#f6b3cb", alpha=0.8):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cache = {}
    for _ in range(n):
        L = rng.choice((9, 11, 13, 16)) * k
        key = round(L)
        if key not in cache:
            cache[key] = petal_sprite(L, colour, alpha)
        img = cache[key].rotate(rng.uniform(0, 360), resample=Image.BICUBIC, expand=True)
        layer.alpha_composite(img, (int(rng.uniform(0, W)), int(rng.uniform(0, H))))
    return pil_layer(layer)


def bokeh(W, H, rng, k, n, colours, alpha=0.18):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        r = rng.uniform(20, 70) * k
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        c = tuple(int(v * 255) for v in hexc(rng.choice(colours)))
        d.ellipse([x - r, y - r, x + r, y + r], fill=c + (int(255 * alpha * rng.uniform(0.5, 1.0)),))
    return blur_rgba(layer, 6 * k)


def sparkle(d, x, y, r, colour, a):
    """A four-point star."""
    c = tuple(int(v * 255) for v in hexc(colour)) + (int(255 * a),)
    t = r * 0.18
    d.polygon([(x, y - r), (x + t, y - t), (x + r, y), (x + t, y + t),
               (x, y + r), (x - t, y + t), (x - r, y), (x - t, y - t)], fill=c)


def sparkles(W, H, rng, k, n, colour="#fff6fb", alpha=0.75):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        r = rng.uniform(4, 11) * k
        sparkle(d, rng.uniform(0, W), rng.uniform(0, H), r, colour, alpha * rng.uniform(0.5, 1.0))
    return blur_rgba(layer, 0.5 * k)


def heart(d, x, y, r, c):
    d.ellipse([x - r, y - r * 0.9, x, y + r * 0.1], fill=c)
    d.ellipse([x, y - r * 0.9, x + r, y + r * 0.1], fill=c)
    d.polygon([(x - r * 0.97, y - r * 0.25), (x + r * 0.97, y - r * 0.25), (x, y + r * 1.05)], fill=c)


def clouds(W, H, rng, k, n, colour, alpha, ymax=0.7):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = tuple(int(v * 255) for v in hexc(colour))
    for _ in range(n):
        cx, cy = rng.uniform(0, W), rng.uniform(0.15, ymax) * H
        width = rng.uniform(180, 380) * k
        for _ in range(9):
            r = rng.uniform(0.18, 0.32) * width
            x = cx + rng.uniform(-0.5, 0.5) * width
            y = cy - rng.uniform(0, 0.25) * width * (1 - abs(x - cx) / width)
            d.ellipse([x - r, y - r, x + r, y + r * 0.6], fill=c + (int(255 * alpha),))
    return blur_rgba(layer, 10 * k)


def detail_band(H):
    yy = np.arange(H, dtype=np.float32)[:, None, None]
    return np.clip((yy - QUIET) / FADE, 0.0, 1.0) ** 1.5


def put(canvas, layer, band):
    """Composite a detail layer, faded out under the bar."""
    layer = layer.copy()
    layer[..., 3:4] *= band
    return over(canvas, layer)


# -- the variants ------------------------------------------------------------------
BARK = ((74, 42, 62, 255), (122, 84, 104, 255))


def sakura_day(W, H, rng, k, band, branches=True):
    canvas = sky(W, H, [(0.0, "#b7a3ec"), (0.45, "#f1a9cb"), (1.0, "#9fcdf2")], angle=0.15)
    canvas = put(canvas, bokeh(W, H, rng, k, int(26 * W * H / 3440 / 1440) + 8,
                               ["#ffffff", "#ffd6e7", "#e9dcff"]), band)
    canvas = put(canvas, clouds(W, H, rng, k, 4, "#f4e6f2", 0.35, ymax=0.85), band)
    if branches:
        # Two branches, each keeping to its own upper corner: the middle of
        # the screen stays open sky (one version met in the middle in a clump).
        # On a portrait screen they hang steeper and reach further down, or
        # all their blossoms bunched up under the bar.
        tall = H > W
        long = 0.9 * H if tall else W
        drop = 0.55 if tall else 0.0
        thin = 0.55 if tall else 1.0       # fewer blossoms per limb on the narrow screen
        canvas = put(canvas, branch_layer(W, H, rng, k, (-30 * k, QUIET + 0.05 * H), 0.42 + drop,
                                          0.46 * long, BARK, dict(petal="#f393ba"), density=thin), band)
        canvas = put(canvas, branch_layer(W, H, rng, k, (W + 30 * k, QUIET + 0.22 * H if tall else QUIET + 0.10 * H),
                                          math.pi - 0.50 - drop, 0.34 * long, BARK, dict(petal="#f6a6c6"),
                                          density=0.8 * thin), band)
    canvas = put(canvas, drifting_petals(W, H, rng, k, int(40 * W * H / 3440 / 1440) + 10), band)
    canvas = put(canvas, sparkles(W, H, rng, k, int(30 * W * H / 3440 / 1440) + 8), band)
    return canvas


def fuji(W, H, rng, k, band):
    canvas = sky(W, H, [(0.0, "#9d8be0"), (0.42, "#f09cc0"), (0.62, "#f8bca6"), (1.0, "#c695cf")])
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # the sun: a pale disc low in the sky, with a soft halo
    sx, sy, sr = 0.72 * W, 0.40 * H, 70 * k
    d = np.hypot(xx - sx, yy - sy)
    halo = np.clip(1 - d / (sr * 5), 0, 1) ** 2 * 0.35
    disc = np.clip((sr - d) / (2 * k), 0, 1)
    sun = hexc("#ffe4d6")
    canvas = canvas * (1 - halo[..., None]) + sun * halo[..., None]
    canvas = canvas * (1 - disc[..., None] * 0.9) + sun * (disc[..., None] * 0.9)
    canvas = put(canvas, clouds(W, H, rng, k, 5, "#f6d6e2", 0.30, ymax=0.5), band)
    # Mt. Fuji: concave slopes up to a flat, slightly notched top
    base_y = 0.80 * H
    peak_y = base_y - min(0.46 * H, 0.42 * W)
    cx = 0.40 * W
    half = (base_y - peak_y) * 2.1
    top = (base_y - peak_y) * 0.09
    x = xx - cx
    t = np.clip(np.abs(x) / half, 0, 1)
    ridge = peak_y + (base_y - peak_y) * np.clip((np.abs(x) - top) / (half - top), 0, 1) ** 0.62
    ridge = ridge + np.sin(x / (18 * k)) * 1.5 * k
    mountain = (yy >= ridge) & (np.abs(x) < half)
    shade = ramp(np.clip((yy - peak_y) / (base_y - peak_y), 0, 1),
                 [(0.0, "#9b93cf"), (1.0, "#7c78b8")])
    # the snowcap: down to a wavy line about a quarter of the way
    cap_line = peak_y + (base_y - peak_y) * (0.26 + 0.05 * np.sin(x / (40 * k)) + 0.03 * np.sin(x / (13 * k)))
    snow = mountain & (yy < cap_line)
    snow_col = ramp(np.clip((yy - peak_y) / (base_y - peak_y) * 3, 0, 1), [(0.0, "#fbe2ee"), (1.0, "#f0c2d8")])
    m = mountain.astype(np.float32)[..., None]
    canvas = canvas * (1 - m) + shade * m
    s = snow.astype(np.float32)[..., None]
    canvas = canvas * (1 - s) + snow_col * s
    # ridges of snow running down: a faint lighter left face
    # the lit (left) flank: a soft brightening across the slope, no seam
    lit = np.clip(-x / half * 1.6, -0.4, 1.0) * 0.035
    canvas = canvas + (mountain * lit)[..., None]
    # hills in front, hazier the further back
    for i, (col, h0, amp, per) in enumerate([("#b49bc9", 0.78, 0.035, 260), ("#9b84b8", 0.86, 0.04, 190),
                                              ("#836ea6", 0.93, 0.03, 140)]):
        ph = rng.uniform(0, 6.28)
        line = h0 * H + amp * H * (np.sin(xx[0] / (per * k) + ph) * 0.6 + np.sin(xx[0] / (per * 0.37 * k) + ph * 2) * 0.4)
        hill = (yy >= line[None, :]).astype(np.float32)[..., None]
        canvas = canvas * (1 - hill) + hexc(col) * hill
    canvas = put(canvas, drifting_petals(W, H, rng, k, int(30 * W * H / 3440 / 1440) + 8), band)
    return canvas


def yozakura(W, H, rng, k, band):
    canvas = sky(W, H, [(0.0, "#1d1636"), (0.55, "#2e1f45"), (1.0, "#432a4f")])
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # stars
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    for _ in range(int(260 * W * H / 3440 / 1440) + 40):
        x, y = rng.uniform(0, W), rng.uniform(0, 0.8 * H)
        r = rng.choice((0.8, 1.0, 1.3, 1.8)) * k
        a = int(255 * rng.uniform(0.35, 0.9))
        dr.ellipse([x - r, y - r, x + r, y + r], fill=(246, 232, 255, a))
    for _ in range(12):
        sparkle(dr, rng.uniform(0, W), rng.uniform(0, 0.7 * H), rng.uniform(6, 10) * k, "#f7e9ff", 0.8)
    canvas = put(canvas, blur_rgba(layer, 0.4 * k), band)
    # the moon: large and pale, a wide soft halo, faint maria
    mx, my, mr = 0.70 * W, 0.30 * H, 120 * k
    d = np.hypot(xx - mx, yy - my)
    halo = np.clip(1 - d / (mr * 4.5), 0, 1) ** 2.2 * 0.45
    moon_col = hexc("#f3e6ef")
    canvas = canvas * (1 - halo[..., None]) + hexc("#8f7aa8") * halo[..., None]
    disc = np.clip((mr - d) / (2 * k), 0, 1)
    maria = np.zeros_like(d)
    for _ in range(6):
        ox, oy, orr = rng.uniform(-0.5, 0.5) * mr, rng.uniform(-0.5, 0.5) * mr, rng.uniform(0.15, 0.35) * mr
        maria = np.maximum(maria, np.clip(1 - np.hypot(xx - mx - ox, yy - my - oy) / orr, 0, 1) * 0.10)
    face = moon_col - maria[..., None] * 0.6
    canvas = canvas * (1 - disc[..., None]) + face * disc[..., None]
    tall = H > W            # portrait: hang steeper, reach further down
    long = 0.9 * H if tall else W
    canvas = put(canvas, branch_layer(W, H, rng, k, (-30 * k, QUIET + 0.10 * H), 0.22 + (0.6 if tall else 0.0),
                                      0.45 * long,
                                      ((40, 24, 44, 255), (82, 56, 84, 255)),
                                      dict(petal="#f6b0cf", centre="#fff0f6", vein="#d97fac", stamen="#f6dc8e"),
                                      density=0.7 if tall else 1.3, glow="#ffb8d8"), band)
    canvas = put(canvas, drifting_petals(W, H, rng, k, int(24 * W * H / 3440 / 1440) + 6, "#f0bfd5", 0.6), band)
    return canvas


def kawaii(W, H, rng, k, band):
    canvas = sky(W, H, [(0.0, "#f2a3c7"), (0.5, "#c5a6f0"), (1.0, "#f4b2cf")], angle=0.6)
    canvas = put(canvas, clouds(W, H, rng, k, 6, "#f8e6f1", 0.45, ymax=0.9), band)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    step = int(150 * k)
    flower = blossom_sprite(int(22 * k), petal="#f08cb8", centre="#fde4ee", alpha=0.6)
    for gy in range(-step, H + step, step):
        for gx in range(-step, W + step, step):
            off = step / 2 if (gy // step) % 2 else 0
            x = gx + off + rng.uniform(-0.25, 0.25) * step
            y = gy + rng.uniform(-0.25, 0.25) * step
            kind = rng.random()
            if kind < 0.38:
                heart(d, x, y, rng.uniform(15, 22) * k, (236, 110, 160, int(255 * 0.45)))
            elif kind < 0.70:
                sparkle(d, x, y, rng.uniform(14, 22) * k, "#fff4fa", 0.65)
            elif kind < 0.92:
                img = flower.rotate(rng.uniform(0, 72), resample=Image.BICUBIC)
                layer.alpha_composite(img, (int(x - img.width / 2), int(y - img.height / 2)))
            else:
                r = rng.uniform(3, 5) * k
                d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 240, 248, 120))
    canvas = put(canvas, blur_rgba(layer, 0.5 * k), band)
    return canvas


def render(W, H, variant):
    rng = random.Random(f"{variant}-{W}x{H}")
    k = min(W, H) / 1440
    band = detail_band(H)
    canvas = {"sakura-day": sakura_day, "fuji": fuji, "yozakura": yozakura, "kawaii": kawaii}[variant](
        W, H, rng, k, band)
    return finish(canvas, f"{variant}-{W}x{H}")


def finish(canvas, seed):
    """PEAK cap (the HDR rule), then 8-bit with a +-1 dither. The cap SCALES
    a too-bright colour down whole instead of clipping each channel: clipped,
    a pale pink snowcap or the moon came out flat grey (every channel at the
    same 0.80)."""
    canvas = np.clip(canvas, 0.0, None)
    peak = canvas.max(axis=-1, keepdims=True)
    out = canvas / np.maximum(peak / PEAK, 1.0)
    noise = np.random.default_rng(zlib.crc32(seed.encode())).uniform(-0.5, 0.5, out.shape)
    px = out * 255.0 + noise
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
    ap.add_argument("--all", action="store_true", help="every variant for every monitor folder")
    ap.add_argument("--list", action="store_true", help="the variants")
    ap.add_argument("-v", "--variant", default="sakura-day", choices=VARIANTS)
    ap.add_argument("-o", "--output", help="one image to this path")
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's (logical)")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's (logical)")
    a = ap.parse_args()
    if a.list:
        print("\n".join(VARIANTS))
        return
    if a.all:
        for variant in VARIANTS:
            for mon, (w, h) in logical_sizes().items():
                write(render(w, h, variant), os.path.join(WALLDIR, mon, f"moe-{variant}.png"))
        return
    if not a.output:
        ap.error("give -o FILE, or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size(logical=True)
    write(render(a.width, a.height, a.variant), a.output)


if __name__ == "__main__":
    main()
