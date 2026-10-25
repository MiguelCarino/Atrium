#!/usr/bin/env python3
"""Render wallpapers for the lofi theme: a study room at dusk -- a rainy
window over the city, a lamp-lit desk with a sleeping cat, a rooftop under
string lights, a sunset over the skyline, and a record and a cassette on a
violet table -- all drawn from scratch here (stepped rectangles, discs,
lines and gradients), not copies of anybody's picture or any channel's art.

    make-lofi-wallpaper.py --all                every variant, every monitor,
                                                into the slideshow folders
    make-lofi-wallpaper.py -v desk -W 1720 -H 720 -o /tmp/x.png
    make-lofi-wallpaper.py --list               the variants

--all writes ~/Pictures/Wallpapers/<OUTPUT>/lofi-<variant>.png for every
screen connected now at its LOGICAL size (what Hyprland lays out: the mode
over the scale, turned when the screen is rotated; see logical_sizes(), the
same as make-moe-wallpaper.py's; 1920x1080 for the primary when Hyprland is
not running), the same names in every folder, so the screens change together
(the lofi theme's set: wallpaper_prefix=lofi- in ~/.config/themes/lofi/
theme.conf; `theme.py check lofi` insists on matching names).

Variants:
    rain     a rainy window at dusk: a violet-to-rose sky, two layers of
             skyline with lit windows, big blurred city bokeh, and the glass
             in front of it all -- slanted streaks and beaded drops -- in a
             dark window frame with a sill, a plant pot and a steaming mug
    desk     the desk at night: a striped wall, a window with a night sky,
             an anglepoise lamp throwing a peach pool, books, headphones, a
             cassette, a mug, and a curled cat with a thin peach rim light
    rooftop  a roof at night: stars, a crescent moon with its halo, lilac
             clouds, a distant lit skyline, a sagging string of warm bulbs
             and the ledge, water tower and antennas as silhouettes
    sunset   the sun half set behind three layers of skyline, lilac haze for
             distance, small birds and power lines
    vinyl    a still life: a record (grooves, a peach label) and a tilted
             cassette on a dusky violet table under a soft band of light

The rules, as in make-moe-wallpaper.py, for the same reasons:
  * On an HDR screen SDR is mapped into the HDR range, so nothing reaches full
    scale: every channel is capped at PEAK (scaled down whole, not clipped),
    and the big fields (the skies, the wall, the table) are held under
    SKY_LUM luminance -- dusk is dark anyway, 0.45 (0.55 for the sunset).
  * The bar's pills sit over the top 106 px, and their contrast numbers
    (themes/lofi/waybar.css) assume a backdrop no brighter than #5a4a6e
    there. Every sky starts at its DARKEST stop, held flat down to 106 px
    (sky()), and nothing bright is placed above it (clear_band()): that
    band keeps mean luminance <= 0.03 and no channel over 0.27.
  * The bar sits on the top QUIET px: no detail at all there; detail fades
    in below it over FADE px (detail_band(), put()).
  * finish(): a vignette (x 1 - 0.18 r^2), then a faint luminance-only film
    grain (Gaussian, sigma 0.010, the theme's grain), the PEAK cap, and a
    +-0.5 LSB dither against the banding a smooth 8-bit gradient gets.
Sizes follow the short side (k = short / 1440), so a drop or a bulb is
about the same physical size on every screen, portrait included; layout uses
fractions of W and H.

The accent does not follow the wallpaper in this theme (accent_follow=no:
themes/lofi/theme.conf says why), but the pictures are still built so that
theme-from-wallpaper.py's hue vote lands on peach or lilac -- never in the
bad red [340, 15] degrees nor the warn amber [40, 65] -- in case the user
turns following on. The sun, the lamp and the lit windows are peach, but
they are small; the big dusk fields are violet and outvote them, so every
picture lands on the lilac side. `theme-from-wallpaper.py pick` on the
DP-1 set (3440x1440), 2026-10-24:
    rain     #7d4eff   (hue 256)
    desk     #714eff   (hue 252)
    rooftop  #734eff   (hue 253)
    sunset   #8d3fff   (hue 264)
    vinyl    #7c4eff   (hue 256)
Measured on the same set: the top 106 px have mean luminance 0.006-0.011
and no channel over 0.255 (sunset; the others 0.19-0.23).

Deterministic: the same variant and size always give the same image.
Pure numpy + Pillow (both installed); about 5 s per ultrawide image, --all
(five variants on four screens) about a minute.
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
SKY_LUM = 0.45       # ceiling for the luminance of the big fields (dusk)
SUNSET_LUM = 0.55    # the sunset's sky only: its horizon glow is the point
QUIET = 36           # px under the bar with no detail at all (the bar's height)
FADE = 70            # px over which the detail fades in below that
TOP_BAND = QUIET + FADE   # 106: the band the pills' contrast numbers cover
GRAIN = 0.010        # film grain sigma, in 0..1 luminance

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
VARIANTS = ["rain", "desk", "rooftop", "sunset", "vinyl"]

# The theme's colours (themes/lofi/waybar.css, the l- names).
PEACH, PEACH_LT, LILAC, RAIN = "#f2a477", "#f6b48c", "#b9a3ea", "#8fbfe0"
CREAM = "#e8dccb"
WINDOW_LIT = ("#f2b88a", "#e8c49a")      # lit windows in the skylines
FRAME = "#1a1428"                        # window frames, silhouettes


def logical_sizes():
    """{output: (W, H)} as Hyprland lays the monitors out: mode / scale,
    swapped when rotated (make-matrix-rain.py explains why the logical size).
    screens.py's; without Hyprland, its 1920x1080 for the primary."""
    return screens.sizes(logical=True)


# -- colour helpers --------------------------------------------------------------
def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def rgba(h, a=1.0):
    """'#rrggbb' -> a PIL fill tuple with alpha a (0..1)."""
    return tuple(int(round(v * 255)) for v in hexc(h)) + (int(round(255 * a)),)


def lum(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def ramp(t, stops):
    """Colour at t (array) along [(pos, '#rrggbb'), ...]; pos may be px."""
    pos = [p for p, _ in stops]
    cols = np.stack([hexc(c) for _, c in stops])
    return np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], -1).astype(np.float32)


def sky(W, H, stops, ceiling=SKY_LUM, angle=0.0):
    """A gradient field top -> bottom (tilted by `angle`: 0..1 adds some of x),
    luminance held under `ceiling`. The stops are fractions of H, darkest
    first, and the darkest is held flat down to TOP_BAND px before the
    gradient starts: the bar's pills sit there, and their contrast numbers
    want it dark on a short screen (900 px) as much as on a tall one."""
    pos = [p * (H - 1) for p, _ in stops]
    cols = [c for _, c in stops]
    hold = min(TOP_BAND, 0.25 * (H - 1))
    if len(pos) > 1 and pos[1] > hold + 1:
        pos.insert(1, hold)
        cols.insert(1, cols[0])
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = yy * (1 - angle) + (xx / max(1, W - 1)) * (H - 1) * angle
    rgb = ramp(t, list(zip(pos, cols)))
    over_ = np.maximum(lum(rgb) / ceiling, 1.0)[..., None]
    return rgb / over_


def over(canvas, layer):
    """Alpha-composite a float RGBA layer (H, W, 4) onto a float RGB canvas."""
    a = layer[..., 3:4]
    return canvas * (1 - a) + layer[..., :3] * a


def pil_layer(img):
    return np.asarray(img, np.float32) / 255.0


def blur_rgba(img, radius):
    """Gaussian blur of an RGBA image in PREMULTIPLIED form (PIL blurs the four
    channels apart, so the transparent black round a disc bleeds a dark rim
    into it). Premultiply, blur, divide back. Returns a float RGBA layer."""
    a = np.asarray(img, np.float32) / 255
    pre = a[..., :3] * a[..., 3:4]
    chans = [Image.fromarray((pre[..., i] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
             for i in range(3)]
    alpha = Image.fromarray((a[..., 3] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    al = np.asarray(alpha, np.float32) / 255
    rgb = np.dstack([np.asarray(c, np.float32) / 255 for c in chans]) / np.maximum(al[..., None], 1e-3)
    return np.dstack([np.clip(rgb, 0, 1), al])


def detail_band(H):
    """0 under the bar, rising to 1 over FADE px below QUIET."""
    yy = np.arange(H, dtype=np.float32)[:, None, None]
    return np.clip((yy - QUIET) / FADE, 0.0, 1.0) ** 1.5


def clear_band(H):
    """0 down to TOP_BAND (106 px), rising to 1 over the next 24: for the
    BRIGHT details (drops, bokeh, bulbs, stars), which must not reach into
    the band the pills' contrast numbers assume dark at all -- detail_band()
    alone lets them in at partial strength from QUIET on."""
    yy = np.arange(H, dtype=np.float32)[:, None, None]
    return np.clip((yy - TOP_BAND) / 24.0, 0.0, 1.0)


def put(canvas, layer, band):
    """Composite a detail layer, faded out under the bar."""
    layer = layer.copy()
    layer[..., 3:4] *= band
    return over(canvas, layer)


def glow(canvas, cx, cy, radius, colour, alpha, power=2.0):
    """A soft radial light: `colour` laid over the canvas, alpha falling from
    `alpha` at the centre to 0 at `radius`."""
    H, W = canvas.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    a = np.clip(1 - np.hypot(xx - cx, yy - cy) / radius, 0, 1) ** power * alpha
    return canvas * (1 - a[..., None]) + hexc(colour) * a[..., None]


# -- shared scenery ----------------------------------------------------------------
def skyline(W, H, rng, k, base_y, layers, haze=None, windows=True):
    """Stepped rectangles with roof details, far layer first, as one float RGBA
    layer. layers: [(colour, min_h, max_h, min_w, max_w), ...] with heights
    as fractions of H and widths in k-px. Each building is a block, sometimes
    with a narrower setback on top, a rooftop box or an antenna. Lit windows:
    2-4k squares in WINDOW_LIT at alpha 0.5, on a grid, on at most 6% of the
    building area. `haze` ('#rrggbb', a) tints the farther layers towards the
    sky, more the further back."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    n = len(layers)
    for li, (colour, h0, h1, w0, w1) in enumerate(layers):
        col = hexc(colour)
        if haze is not None and n > 1:
            mix = haze[1] * (n - 1 - li) / (n - 1)
            col = col * (1 - mix) + hexc(haze[0]) * mix
        fill = tuple(int(v * 255) for v in col) + (255,)
        x = -rng.uniform(0, 40) * k
        far = (n - 1 - li) / max(1, n - 1)          # 1 = farthest layer
        while x < W:
            bw = rng.uniform(w0, w1) * k
            bh = rng.uniform(h0, h1) * H
            top = base_y - bh
            d.rectangle([x, top, x + bw, H], fill=fill)
            roof = rng.random()
            if roof < 0.30:                          # a setback storey
                inset = bw * rng.uniform(0.15, 0.3)
                sh = rng.uniform(0.04, 0.10) * bh
                d.rectangle([x + inset, top - sh, x + bw - inset, top], fill=fill)
                top_detail = top - sh
            else:
                top_detail = top
            if rng.random() < 0.25:                  # an antenna
                ax = x + bw * rng.uniform(0.3, 0.7)
                d.line([(ax, top_detail), (ax, top_detail - rng.uniform(18, 50) * k)],
                       fill=fill, width=max(1, int(2 * k)))
            elif rng.random() < 0.3:                 # a rooftop box
                bx = x + bw * rng.uniform(0.1, 0.5)
                d.rectangle([bx, top_detail - 10 * k, bx + bw * 0.25, top_detail], fill=fill)
            if windows:
                size = max(2.0, rng.uniform(2, 4) * k * (1 - 0.4 * far))
                step = size * 3.2
                # 0.55 of 1/3.2^2 (~10%) of the slots lit: about 5% of the area
                p_on = 0.55 * (1 - 0.3 * far)
                wy = top + step
                while wy < H - step:
                    wx = x + step * 0.6
                    while wx < x + bw - step * 0.6:
                        if rng.random() < p_on * 0.98:
                            c = rgba(rng.choice(WINDOW_LIT), 0.5 * (1 - 0.35 * far))
                            d.rectangle([wx, wy, wx + size, wy + size], fill=c)
                        wx += step
                    wy += step
            x += bw + rng.uniform(-4, 6) * k
    return pil_layer(img)


def bokeh(W, H, rng, k, n, colours, y0, y1, alpha=(0.12, 0.25), r=(20, 70), blur=7, x0=0.0, x1=None):
    """Out-of-focus lights: soft discs between y0 and y1 (and x0..x1, px),
    each a colour from `colours` at alpha in `alpha`, premultiplied-blurred."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        rr = rng.uniform(*r) * k
        x, y = rng.uniform(x0, W if x1 is None else x1), rng.uniform(y0, y1)
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=rgba(rng.choice(colours), rng.uniform(*alpha)))
    return blur_rgba(layer, blur * k)


def rain_streaks(W, H, rng, k, n, y0=0.0):
    """Rain running down the glass: thin lines slanted 8-12 degrees from the
    vertical, 30-90k long, #c9c4e6 at alpha 0.18-0.28. (At 0.10-0.18 and
    20-60k they all but vanished once the picture was scaled down, and the
    drops alone read as snow.)"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        ang = math.radians(rng.uniform(8, 12))
        L = rng.uniform(30, 90) * k
        x, y = rng.uniform(-0.1 * W, W), rng.uniform(y0, H)
        d.line([(x, y), (x + L * math.sin(ang), y + L * math.cos(ang))],
               fill=rgba("#c9c4e6", rng.uniform(0.18, 0.28)), width=max(1, int(round(1.4 * k))))
    return blur_rgba(layer, 0.6 * k)


def drops(W, H, rng, k, n, y0=0.0, ledges=(), posts=()):
    """Beads of water on the glass: a disc with a lighter body (alpha 0.3), a
    1 px highlight at its top left and, for most, a faint trail above it
    where it ran. Water collects low: the drops thin out towards the top of
    the pane (y drawn as y0 + (H - y0) * sqrt(u)), and about a third of
    them gather just above a ledge (a y, the top of a muntin or the sill)
    or beside a post (an x, a vertical muntin). Spread evenly over the sky
    they read as falling snow."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        r = rng.uniform(2.5, 8) * k
        x, y = rng.uniform(0, W), y0 + (H - y0) * math.sqrt(rng.random())
        pick = rng.random()
        if ledges and pick < 0.20:                   # beaded along a ledge
            y = rng.choice(ledges) - rng.uniform(1.2, 5) * r
        elif posts and pick < 0.33:                  # running down beside a post
            x = rng.choice(posts) + rng.choice((-1, 1)) * rng.uniform(1.2, 4) * r
        if y < y0:
            continue
        if rng.random() < 0.7:                       # a trail where it ran
            d.line([(x - 0.15 * r, y - r * rng.uniform(3, 7)), (x, y - r)],
                   fill=rgba("#c9c4e6", 0.10), width=max(1, int(r * 0.5)))
        d.ellipse([x - r, y - r, x + r, y + r], fill=rgba("#cdc6e6", 0.30))
        d.ellipse([x - r * 0.55, y - r * 0.55, x + r * 0.45, y + r * 0.45], fill=rgba("#b8b0d8", 0.16))
        hx, hy = x - r * 0.45, y - r * 0.45
        d.rectangle([hx, hy, hx + max(1, k), hy + max(1, k)], fill=rgba("#efe8f6", 0.65))
    return blur_rgba(layer, 0.45 * k)


def steam(W, H, rng, k, x, y, height, n=3):
    """Wisps rising from a mug: soft sine curves at alpha 0.08."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(n):
        ph = rng.uniform(0, 6.28)
        ox = (i - (n - 1) / 2) * 10 * k
        pts = [(x + ox + 7 * k * math.sin(ph + s * 5.0) * (0.4 + s), y - s * height) for s in np.linspace(0, 1, 40)]
        d.line(pts, fill=rgba(CREAM, 0.08), width=max(1, int(3 * k)))
    return blur_rgba(layer, 2.5 * k)


def mug(d, x, y, k, body="#3a2a44", rim="#4c3a58"):
    """A mug standing at (x, y = its foot), with a handle on the right."""
    w, h = 46 * k, 54 * k
    d.rounded_rectangle([x - w / 2, y - h, x + w / 2, y], radius=8 * k, fill=rgba(body))
    d.ellipse([x + w / 2 - 8 * k, y - h * 0.78, x + w / 2 + 18 * k, y - h * 0.28], outline=rgba(body),
              width=max(2, int(7 * k)))
    d.line([(x - w / 2 + 3 * k, y - h + 2 * k), (x + w / 2 - 3 * k, y - h + 2 * k)], fill=rgba(rim),
           width=max(1, int(2 * k)))
    return y - h


def stars(W, H, rng, k, density, y0, y1, amax=0.7):
    """Points of light at `density` per px between y0 and y1, alpha <= amax."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(int(density * W * max(0, y1 - y0))):
        x, y = rng.uniform(0, W), rng.uniform(y0, y1)
        r = rng.choice((0.6, 0.8, 1.0, 1.4)) * k
        d.ellipse([x - r, y - r, x + r, y + r], fill=rgba("#eae4f2", rng.uniform(0.2, amax)))
    return blur_rgba(layer, 0.35 * k)


def clouds(W, H, rng, k, n, colour, alpha, y0, y1):
    """Soft cloud banks between y0 and y1 (px)."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        cx, cy = rng.uniform(0, W), rng.uniform(y0, y1)
        width = rng.uniform(260, 520) * k
        for _ in range(10):
            r = rng.uniform(0.15, 0.28) * width
            x = cx + rng.uniform(-0.5, 0.5) * width
            y = cy - rng.uniform(0, 0.18) * width * (1 - abs(x - cx) / width)
            d.ellipse([x - r, y - r * 0.55, x + r, y + r * 0.45], fill=rgba(colour, alpha))
    return blur_rgba(layer, 14 * k)


def catenary(x0, y0, x1, y1, sag, n=80):
    """Points of a hanging wire from (x0, y0) to (x1, y1) whose lowest point
    hangs `sag` px below the higher end's level (+y is down)."""
    half = (x1 - x0) / 2
    lo, hi = 1e-3 * half, 1e4 * half
    for _ in range(60):                 # solve c*(cosh(half/c) - 1) = sag
        c = (lo + hi) / 2
        if c * (math.cosh(half / c) - 1) > sag:
            lo = c
        else:
            hi = c
    xm, ylow = (x0 + x1) / 2, max(y0, y1) + sag
    tilt = (y1 - y0) / (x1 - x0)
    pts = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        y = ylow - c * (math.cosh((x - xm) / c) - 1) + tilt * (x - xm) - (max(y0, y1) - (y0 + y1) / 2)
        pts.append((x, y))
    return pts


def rim_light(mask, dx, dy, colour, alpha):
    """A thin light along the edge of a silhouette mask (float H x W) on the
    side facing (dx, dy): mask pixels whose neighbour that way is outside."""
    shifted = np.roll(np.roll(mask, -dy, axis=0), -dx, axis=1)
    edge = np.clip(mask - shifted, 0, 1)
    out = np.zeros(mask.shape + (4,), np.float32)
    out[..., :3] = hexc(colour)
    out[..., 3] = edge * alpha
    return out


# -- the variants ------------------------------------------------------------------
def rain(W, H, rng, k, band):
    clear = clear_band(H)            # bright details stay out of the top 106 px
    canvas = sky(W, H, [(0.0, "#1b1733"), (0.40, "#3b2d58"), (0.72, "#7a4d6a"), (1.0, "#c27a6a")])
    area = W * H / (3440 * 1440)
    base = 0.84 * H
    canvas = put(canvas, skyline(W, H, rng, k, base,
                                 [("#33284a", 0.16, 0.36, 60, 140), ("#1f1830", 0.06, 0.22, 70, 170)],
                                 haze=("#5a4468", 0.45)), band)
    # the city's lights, far out of focus behind the wet glass
    canvas = put(canvas, bokeh(W, H, rng, k, int(46 * area) + 10, [PEACH, PEACH, LILAC, RAIN, "#e8c49a"],
                               0.42 * H, 0.95 * H, r=(30, 90), blur=10), band * clear)
    # the glass: streaks, then drops
    canvas = put(canvas, rain_streaks(W, H, rng, k, int(520 * area) + 80, TOP_BAND), band * clear)
    side, bar = 54 * k, 20 * k
    sill_top = 0.90 * H
    # (half the drops of the first draft, gathered on the muntins and sill)
    canvas = put(canvas, drops(W, H, rng, k, int(75 * area * 6) + 30, TOP_BAND,
                               ledges=(0.46 * H - bar / 2, sill_top),
                               posts=(W / 2 - bar / 2, W / 2 + bar / 2)), band * clear)
    # the window frame and muntins, the sill and what stands on it
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, 0, side, H], fill=rgba(FRAME))
    d.rectangle([W - side, 0, W, H], fill=rgba(FRAME))
    d.rectangle([0, 0, W, 30 * k], fill=rgba(FRAME))               # under the bar: dark anyway
    d.rectangle([W / 2 - bar / 2, 0, W / 2 + bar / 2, sill_top], fill=rgba(FRAME))
    d.rectangle([side, 0.46 * H - bar / 2, W - side, 0.46 * H + bar / 2], fill=rgba(FRAME))
    d.rectangle([0, sill_top, W, H], fill=rgba("#211a30"))
    d.rectangle([0, sill_top, W, sill_top + 4 * k], fill=rgba("#3a2e4a"))  # the sill's lit edge
    # a plant pot on the left of the sill: a tapered pot and a few leaves
    px = 0.16 * W
    pw, ph = 70 * k, 64 * k
    d.polygon([(px - pw / 2, sill_top - ph), (px + pw / 2, sill_top - ph),
               (px + pw * 0.38, sill_top), (px - pw * 0.38, sill_top)], fill=rgba("#3a2834"))
    for i in range(7):
        a = math.radians(-160 + i * 23)
        L = rng.uniform(60, 110) * k
        cx, cy = px + math.cos(a) * L * 0.5, sill_top - ph - 8 * k + math.sin(a) * L * 0.5
        d.ellipse([cx - L * 0.32, cy - L * 0.14, cx + L * 0.32, cy + L * 0.14], fill=rgba("#23302e"))
    # the mug on the right, steam rising off it
    mx = 0.80 * W
    mtop = mug(d, mx, sill_top, k)
    canvas = over(canvas, blur_rgba(layer, 0.5 * k))
    canvas = put(canvas, steam(W, H, rng, k, mx, mtop - 6 * k, 120 * k), band)
    return canvas


def desk(W, H, rng, k, band):
    clear = clear_band(H)            # bright details stay out of the top 106 px
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    canvas = sky(W, H, [(0.0, "#16132a"), (0.6, "#1d1830"), (1.0, "#211b36")])
    # faint wallpaper stripes
    canvas = canvas * (1 + 0.035 * np.sin(xx / (22 * k) * math.pi)[..., None] * band)
    desk_top = 0.78 * H
    # the window behind: a night sky with three bokeh
    wx0, wx1 = 0.10 * W, 0.10 * W + max(0.24 * W, 0.42 * H)
    wy0, wy1 = max(0.18 * H, TOP_BAND + 40 * k), 0.58 * H
    win = sky(int(wx1 - wx0), int(wy1 - wy0), [(0.0, "#141128"), (1.0, "#2e2550")])
    sub = canvas[int(wy0):int(wy0) + win.shape[0], int(wx0):int(wx0) + win.shape[1]]
    sub[:] = win
    lay = stars(W, H, rng, k, 0.0004, wy0, wy1)
    lay[..., 3] *= ((xx > wx0) & (xx < wx1) & (yy > wy0) & (yy < wy1))
    canvas = put(canvas, lay, band * clear)
    bk = bokeh(W, H, rng, k, 3, [PEACH, LILAC, RAIN], wy0 + 0.5 * (wy1 - wy0), wy1 - 20 * k,
               alpha=(0.22, 0.25), r=(24, 40), blur=6, x0=wx0 + 40 * k, x1=wx1 - 40 * k)
    bk[..., 3] *= ((xx > wx0) & (xx < wx1) & (yy > wy0) & (yy < wy1))
    canvas = put(canvas, bk, band * clear)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fw = 16 * k
    d.rectangle([wx0 - fw, wy0 - fw, wx1 + fw, wy1 + fw], outline=rgba("#120f22"), width=int(fw))
    d.rectangle([(wx0 + wx1) / 2 - fw / 3, wy0, (wx0 + wx1) / 2 + fw / 3, wy1], fill=rgba("#120f22"))
    d.rectangle([wx0, (wy0 + wy1) / 2 - fw / 3, wx1, (wy0 + wy1) / 2 + fw / 3], fill=rgba("#120f22"))
    # the desk
    d.rectangle([0, desk_top, W, H], fill=rgba("#2b2038"))
    d.rectangle([0, desk_top, W, desk_top + 5 * k], fill=rgba("#3b2e4a"))
    canvas = over(canvas, blur_rgba(layer, 0.5 * k))

    # the lamp's light: a pool on the desk and a fainter one on the wall
    lx = 0.74 * W
    head = (lx - 60 * k, desk_top - 330 * k)
    canvas = glow(canvas, head[0] - 20 * k, desk_top + 40 * k, 560 * k, "#f0a070", 0.35, power=1.3)
    cone = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(cone).polygon([(head[0] - 40 * k, head[1] + 50 * k), (head[0] - 330 * k, desk_top),
                                  (head[0] + 160 * k, desk_top)], fill=rgba("#f0a070", 0.07))
    canvas = put(canvas, blur_rgba(cone, 30 * k), band)
    canvas = glow(canvas, head[0], head[1] + 60 * k, 420 * k, "#c98a6a", 0.12, power=2.0)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sil = "#140f20"
    # the anglepoise: a base, two arms, a cone head pointing down-left
    base = (lx + 40 * k, desk_top)
    elbow = (lx + 110 * k, desk_top - 190 * k)
    d.ellipse([base[0] - 50 * k, base[1] - 14 * k, base[0] + 50 * k, base[1] + 6 * k], fill=rgba(sil))
    d.line([base, elbow], fill=rgba(sil), width=int(9 * k))
    d.line([elbow, head], fill=rgba(sil), width=int(9 * k))
    d.ellipse([elbow[0] - 9 * k, elbow[1] - 9 * k, elbow[0] + 9 * k, elbow[1] + 9 * k], fill=rgba(sil))
    hx, hy = head
    d.polygon([(hx - 10 * k, hy - 24 * k), (hx + 22 * k, hy - 6 * k), (hx - 30 * k, hy + 70 * k),
               (hx - 90 * k, hy + 40 * k)], fill=rgba(sil))
    d.ellipse([hx - 70 * k, hy + 44 * k, hx - 44 * k, hy + 62 * k], fill=rgba("#f2c49a", 0.75))  # the bulb
    # books: a stack lying down and two standing, between window and lamp
    bx = 0.50 * W if W > H else 0.24 * W     # portrait: keep clear of the cat
    y = desk_top
    for i, (bw, bh, c) in enumerate(((240, 30, "#3e3352"), (210, 26, "#4a3346"), (226, 34, "#33405a"))):
        off = rng.uniform(-14, 14) * k
        d.rectangle([bx - bw * k / 2 + off, y - bh * k, bx + bw * k / 2 + off, y], fill=rgba(c))
        d.line([(bx - bw * k / 2 + off + 8 * k, y - bh * k / 2), (bx + bw * k / 2 + off - 8 * k, y - bh * k / 2)],
               fill=rgba("#5c4a66"), width=max(1, int(2 * k)))
        y -= bh * k
    for i, (bw, bh, c, lean) in enumerate(((34, 190, "#402f4c", 0), (30, 170, "#2f3a52", 8))):
        x0 = bx + 150 * k + i * 38 * k
        d.polygon([(x0, desk_top), (x0 + bw * k, desk_top), (x0 + bw * k + lean * k, desk_top - bh * k),
                   (x0 + lean * k, desk_top - bh * k)], fill=rgba(c))
    # headphones on the top book
    cx, cy = bx - 30 * k, y
    d.arc([cx - 70 * k, cy - 110 * k, cx + 70 * k, cy + 30 * k], 180, 360, fill=rgba("#2a2238"), width=int(10 * k))
    for sx in (-1, 1):
        d.rounded_rectangle([cx + sx * 70 * k - 18 * k, cy - 46 * k, cx + sx * 70 * k + 18 * k, cy],
                            radius=10 * k, fill=rgba("#2a2238"))
    # a cassette lying on the desk beside the books: its bottom edge on the
    # desk top, like everything else that stands there
    ccx, ccy = bx - 220 * k, desk_top - 26 * k
    d.rounded_rectangle([ccx - 80 * k, ccy - 26 * k, ccx + 80 * k, ccy + 26 * k], radius=6 * k, fill=rgba("#3a3050"))
    d.rectangle([ccx - 60 * k, ccy - 18 * k, ccx + 60 * k, ccy - 4 * k], fill=rgba("#8a7468"))
    for sx in (-1, 1):
        d.ellipse([ccx + sx * 32 * k - 10 * k, ccy + 2 * k, ccx + sx * 32 * k + 10 * k, ccy + 22 * k],
                  outline=rgba("#1c1830"), width=max(1, int(3 * k)))
    # the mug, right of the lamp
    mx = lx + 190 * k
    mtop = mug(d, mx, desk_top + 10 * k, k)
    canvas = over(canvas, blur_rgba(layer, 0.5 * k))
    canvas = put(canvas, steam(W, H, rng, k, mx, mtop - 6 * k, 110 * k), band)

    # the cat, curled on the desk in the lamp's pool: body, head, ears, tail
    cat = Image.new("L", (W, H), 0)
    dc = ImageDraw.Draw(cat)
    catx, caty = lx - 260 * k, desk_top + 3 * k
    dc.ellipse([catx - 120 * k, caty - 86 * k, catx + 120 * k, caty], fill=255)          # body
    dc.ellipse([catx + 60 * k, caty - 92 * k, catx + 140 * k, caty - 24 * k], fill=255)  # head
    for ex in (78, 116):                                                                   # ears
        dc.polygon([(catx + (ex - 16) * k, caty - 80 * k), (catx + (ex + 16) * k, caty - 80 * k),
                    (catx + (ex + 2) * k, caty - 116 * k)], fill=255)
    # the tail: out of the rear and curled up round it. Its box starts inside
    # the body ellipse, so the arc grows out of the body with no gap (a gap
    # showed the wall through it, and the rim light outlined it).
    dc.arc([catx - 130 * k, caty - 100 * k, catx - 10 * k, caty - 4 * k], 80, 235, fill=255, width=int(18 * k))
    m = np.asarray(cat, np.float32) / 255
    body = np.zeros((H, W, 4), np.float32)
    body[..., :3] = hexc("#140f20")
    body[..., 3] = m
    canvas = over(canvas, body)
    # the rim: the edge facing the lamp (up and to the right), 1-2 px
    s = max(1, int(round(2 * k)))
    canvas = over(canvas, rim_light(m, s, -s, PEACH, 0.8))
    return canvas


def rooftop(W, H, rng, k, band):
    clear = clear_band(H)            # bright details stay out of the top 106 px
    canvas = sky(W, H, [(0.0, "#141128"), (1.0, "#2e2550")])
    canvas = put(canvas, stars(W, H, rng, k, 0.0002, TOP_BAND, 0.70 * H), band * clear)
    # lilac-lit clouds low over the city
    canvas = put(canvas, clouds(W, H, rng, k, 5, "#5a4a7e", 0.30, 0.42 * H, 0.66 * H), band)
    # the crescent moon: a disc with an offset disc taken out, and a halo
    mx, my, mr = 0.78 * W, max(0.24 * H, TOP_BAND + 90 * k), 40 * k
    canvas = glow(canvas, mx, my, mr * 4.5, LILAC, 0.12)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    disc = np.clip((mr - np.hypot(xx - mx, yy - my)) / (1.5 * k), 0, 1)
    bite = np.clip((mr * 0.92 - np.hypot(xx - mx - 0.42 * mr, yy - my + 0.18 * mr)) / (1.5 * k), 0, 1)
    moon = np.clip(disc - bite, 0, 1)
    canvas = canvas * (1 - moon[..., None]) + hexc("#ece0cc") * moon[..., None]
    # a distant lit skyline
    canvas = put(canvas, skyline(W, H, rng, k, 0.86 * H, [("#2a2244", 0.06, 0.18, 40, 110)],
                                 haze=None), band)
    # the string of bulbs: a wire sagging between two posts, glowing bulbs
    ledge = 0.86 * H
    x0, x1 = -0.02 * W, 1.02 * W
    pts = catenary(x0, 0.50 * H, x1, 0.46 * H, 0.14 * H)
    wire = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dw = ImageDraw.Draw(wire)
    dw.line(pts, fill=rgba("#120e1e"), width=max(1, int(2.5 * k)))
    lights = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lights)
    bulbs = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    db = ImageDraw.Draw(bulbs)
    for i, (bx, by) in enumerate(catenary(x0, 0.50 * H, x1, 0.46 * H, 0.14 * H, n=int(W / (90 * k)))):
        r = rng.uniform(3, 5) * k
        by += 10 * k
        dl.ellipse([bx - r * 6, by - r * 6, bx + r * 6, by + r * 6], fill=rgba("#f2b070", 0.30))
        db.line([(bx, by - 10 * k), (bx, by - r)], fill=rgba("#120e1e"), width=max(1, int(2 * k)))
        db.ellipse([bx - r, by - r, bx + r, by + r * 1.3], fill=rgba("#f6c890", 0.95))
    canvas = put(canvas, blur_rgba(lights, 8 * k), band * clear)
    canvas = put(canvas, pil_layer(wire), band)
    canvas = put(canvas, blur_rgba(bulbs, 0.6 * k), band * clear)
    # the roof: the ledge, a water tower on the left, antennas on the right
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sil = rgba("#100c1c")
    d.rectangle([0, ledge, W, H], fill=sil)
    d.rectangle([0, ledge - 8 * k, W, ledge], fill=rgba("#1c1630"))         # the parapet's top
    tx, tw, tb = 0.12 * W, 150 * k, ledge
    legs = 120 * k
    for lxx in (tx - tw * 0.4, tx - tw * 0.12, tx + tw * 0.12, tx + tw * 0.4):
        d.line([(lxx, tb), (lxx * 0.9 + tx * 0.1, tb - legs)], fill=sil, width=int(6 * k))
    d.line([(tx - tw * 0.45, tb - legs * 0.5), (tx + tw * 0.45, tb - legs * 0.5)], fill=sil, width=int(4 * k))
    d.rectangle([tx - tw / 2, tb - legs - 170 * k, tx + tw / 2, tb - legs], fill=sil)
    d.polygon([(tx - tw / 2 - 8 * k, tb - legs - 170 * k), (tx + tw / 2 + 8 * k, tb - legs - 170 * k),
               (tx, tb - legs - 240 * k)], fill=sil)
    for i, (ax, ah) in enumerate(((0.84 * W, 260), (0.88 * W, 180), (0.93 * W, 220))):
        d.line([(ax, ledge), (ax, ledge - ah * k)], fill=sil, width=int(5 * k))
        for j in range(3):
            yb = ledge - ah * k * (0.55 + 0.15 * j)
            wbar = (40 - 10 * j) * k
            d.line([(ax - wbar, yb), (ax + wbar, yb)], fill=sil, width=int(3 * k))
    canvas = over(canvas, blur_rgba(layer, 0.5 * k))
    return canvas


def sunset(W, H, rng, k, band):
    canvas = sky(W, H, [(0.0, "#1e1a3a"), (0.32, "#4a3466"), (0.62, "#a86a80"), (0.86, "#e09a78"),
                        (1.0, "#e09a78")], ceiling=SUNSET_LUM)
    horizon = 0.72 * H              # the sun's centre: the far skyline's tops
    sx, sr = 0.60 * W, 90 * k
    # the glow round the sun, then the disc (half under the skyline), all warm
    # (hue 18-30): no saturated pink or red
    canvas = glow(canvas, sx, horizon, 900 * k, "#e8a070", 0.35, power=2.2)
    canvas = glow(canvas, sx, horizon, 300 * k, "#f0b080", 0.35, power=1.8)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    disc = np.clip((sr - np.hypot(xx - sx, yy - horizon)) / (1.5 * k), 0, 1)
    sun = hexc("#f0b080") * 0.92
    canvas = canvas * (1 - disc[..., None]) + sun * disc[..., None]
    # birds: small V's in the upper middle
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(9):
        bx, by = rng.uniform(0.25, 0.75) * W, rng.uniform(0.30, 0.52) * H
        s = rng.uniform(7, 13) * k
        d.line([(bx - s, by - s * 0.5), (bx, by), (bx + s, by - s * 0.6)], fill=rgba("#2a2040", 0.85),
               width=max(1, int(2 * k)), joint="curve")
    canvas = put(canvas, blur_rgba(layer, 0.4 * k), band)
    # three skylines, each on its own base so the far one half hides the
    # sun; the further back, the more it is lost in lilac haze (premixed)
    for base, colour, h0, h1, w0, w1 in ((0.80, "#7e6290", 0.04, 0.13, 50, 120),
                                         (0.90, "#4e3a66", 0.06, 0.16, 60, 150),
                                         (1.00, "#221a34", 0.04, 0.12, 70, 170)):
        canvas = put(canvas, skyline(W, H, rng, k, base * H, [(colour, h0, h1, w0, w1)]), band)
    # power lines: two wires between poles in the foreground
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sil = rgba("#161124")
    poles = [-0.05 * W, 0.30 * W, 0.68 * W, 1.05 * W]
    top = 0.60 * H
    for px in poles:
        d.line([(px, H), (px, top - 10 * k)], fill=sil, width=int(10 * k))
        d.line([(px - 40 * k, top), (px + 40 * k, top)], fill=sil, width=int(6 * k))
    for a, b in zip(poles, poles[1:]):
        for off in (-34, 34):
            d.line(catenary(a + off * k, top, b + off * k, top, 0.05 * H), fill=sil, width=max(1, int(2 * k)))
    canvas = over(canvas, blur_rgba(layer, 0.5 * k))
    return canvas


def vinyl(W, H, rng, k, band):
    clear = clear_band(H)            # bright details stay out of the top 106 px
    canvas = sky(W, H, [(0.0, "#181429"), (0.55, "#241d3c"), (1.0, "#2e2448")])
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # a soft diagonal band of light across the table
    s = ((xx - 0.65 * W) * 0.55 + (yy - 0.65 * H) * 0.83) / (0.18 * max(W, H))
    # (faded in over the top third, so it has no edge under the bar)
    light = np.exp(-s ** 2) * 0.16 * np.clip((yy - QUIET) / (0.35 * H), 0, 1) ** 1.5
    canvas = canvas * (1 - light[..., None]) + hexc("#b49ab8") * light[..., None]
    # the record: grooves shaded with sin(r f), a sheen, a peach label, the hole
    R = min(0.40 * H, 0.30 * W, 420 * k)
    cx, cy = 0.26 * W, H - 0.62 * R
    portrait = W < H
    margin = 24 * k
    if portrait:
        # a tall screen: keep the whole record on it, and raise it (and the
        # cassette below) so the two read as a still life, not as two
        # things clipped at the bottom corners
        cx, cy = max(cx, R + margin), 0.72 * H
    r = np.hypot(xx - cx, yy - cy)
    th = np.arctan2(yy - cy, xx - cx)
    disc = np.clip((R - r) / (1.5 * k), 0, 1)
    groove = 0.5 + 0.5 * np.sin(r / (2.2 * k))
    sheen = np.abs(np.cos(th - 0.8)) ** 6 * 0.10
    base = hexc("#15111f")
    col = base[None, None, :] * (0.85 + 0.25 * groove[..., None]) + sheen[..., None] * hexc("#a090b8")
    canvas = canvas * (1 - disc[..., None]) + col * disc[..., None]
    label = np.clip((0.33 * R - r) / (1.5 * k), 0, 1)
    lab_col = hexc("#d9926a") * (0.95 + 0.05 * np.sin(th * 3))[..., None]
    canvas = canvas * (1 - label[..., None]) + lab_col * label[..., None]
    ring = np.clip(1 - np.abs(r - 0.22 * R) / (1.2 * k), 0, 1) * label * 0.35
    canvas = canvas * (1 - ring[..., None]) + hexc("#8a5a46") * ring[..., None]
    hole = np.clip((7 * k - r) / (1.2 * k), 0, 1)
    canvas = canvas * (1 - hole[..., None]) + hexc("#1a1530") * hole[..., None]

    # the cassette, tilted, lower right: drawn upright on its own layer, rotated
    cw, ch = int(560 * k), int(360 * k)
    cas = Image.new("RGBA", (cw + 40, ch + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(cas)
    o = 20
    d.rounded_rectangle([o, o, o + cw, o + ch], radius=22 * k, fill=rgba("#3a3050"))
    d.rounded_rectangle([o + 30 * k, o + 26 * k, o + cw - 30 * k, o + ch * 0.62], radius=10 * k,
                        fill=rgba("#a89080"))                                    # the label
    for i in range(3):
        ly = o + (54 + i * 22) * k
        d.line([(o + 60 * k, ly), (o + cw - 60 * k - (i * 60) * k, ly)], fill=rgba("#6e5a5a"), width=max(1, int(3 * k)))
    d.rounded_rectangle([o + 140 * k, o + ch * 0.36, o + cw - 140 * k, o + ch * 0.58], radius=12 * k,
                        fill=rgba("#1c1830"))                                    # the window
    for sxx in (o + 190 * k, o + cw - 190 * k):
        cyy = o + ch * 0.47
        d.ellipse([sxx - 30 * k, cyy - 30 * k, sxx + 30 * k, cyy + 30 * k], fill=rgba("#3a2420"))  # tape
        d.ellipse([sxx - 16 * k, cyy - 16 * k, sxx + 16 * k, cyy + 16 * k], fill=rgba("#d9ccbc", 0.85))
        for a in range(6):
            aa = math.radians(a * 60)
            d.line([(sxx, cyy), (sxx + 13 * k * math.cos(aa), cyy + 13 * k * math.sin(aa))],
                   fill=rgba("#3a3050"), width=max(1, int(3 * k)))
    d.polygon([(o + 120 * k, o + ch), (o + cw - 120 * k, o + ch), (o + cw - 150 * k, o + ch * 0.78),
               (o + 150 * k, o + ch * 0.78)], fill=rgba("#30283f"))
    cas = cas.rotate(14, resample=Image.BICUBIC, expand=True)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # a soft shadow first
    shadow = Image.new("RGBA", cas.size, (0, 0, 0, 0))
    shadow.putalpha(cas.getchannel("A").point(lambda v: v * 0.45))
    px = int(min(W - cas.width * 0.85, 0.66 * W))
    py = int(H - cas.height * 0.95)
    if portrait:                       # all of it on screen, overlapping the record's edge
        px = int(W - cas.width - margin)
        py = int(min(cy + 0.35 * R, H - cas.height - margin))
    layer.alpha_composite(shadow, (px + int(14 * k), py + int(18 * k)))
    lay = blur_rgba(layer, 14 * k)
    canvas = put(canvas, lay, band)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(cas, (px, py))
    canvas = put(canvas, blur_rgba(layer, 0.4 * k), band)
    # a few low sparkles of dust in the light band, below the bar
    sp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sp)
    for _ in range(int(40 * W * H / 3440 / 1440) + 8):
        x, y = rng.uniform(0, W), rng.uniform(0.25 * H, H)
        r_ = rng.uniform(0.8, 1.8) * k
        ds.ellipse([x - r_, y - r_, x + r_, y + r_], fill=rgba("#efe2d6", rng.uniform(0.10, 0.30)))
    canvas = put(canvas, blur_rgba(sp, 0.5 * k), band * clear)
    return canvas


SCENES = {"rain": rain, "desk": desk, "rooftop": rooftop, "sunset": sunset, "vinyl": vinyl}


def render(W, H, variant):
    rng = random.Random(f"lofi-{variant}-{W}x{H}")
    k = min(W, H) / 1440
    band = detail_band(H)
    canvas = SCENES[variant](W, H, rng, k, band)
    return finish(canvas, f"lofi-{variant}-{W}x{H}")


def finish(canvas, seed):
    """Vignette, film grain, PEAK cap (the HDR rule), then 8-bit with a
    +-0.5 LSB dither. The grain is luminance only (the same offset on all
    three channels, so it never tints), seeded from the name and size. The
    cap SCALES a too-bright colour down whole instead of clipping each
    channel, so a pale bulb keeps its hue."""
    H, W = canvas.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
    canvas = canvas * (1 - 0.18 * r2)[..., None]
    rng = np.random.default_rng(zlib.crc32(seed.encode()))
    canvas = canvas + rng.normal(0, GRAIN, (H, W, 1)).astype(np.float32)
    canvas = np.clip(canvas, 0.0, None)
    peak = canvas.max(axis=-1, keepdims=True)
    out = canvas / np.maximum(peak / PEAK, 1.0)
    noise = rng.uniform(-0.5, 0.5, out.shape)
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
    ap.add_argument("-v", "--variant", default="rain", choices=VARIANTS)
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
                write(render(w, h, variant), os.path.join(WALLDIR, mon, f"lofi-{variant}.png"))
        return
    if not a.output:
        ap.error("give -o FILE, or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size(logical=True)
    write(render(a.width, a.height, a.variant), a.output)


if __name__ == "__main__":
    main()
