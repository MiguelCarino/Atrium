#!/usr/bin/env python3
"""Render wallpapers for the luna theme: the bright, open-air mood of the
Windows XP years -- a green rolling hill under a blue sky with fair-weather
clouds, the same hill in autumn, soft light ribbons on blue, a wheat field
running to a tree line, and a calm sea under an azure sky -- all drawn from
scratch here (a few sine curves, value noise, gradients and Gaussian
falloffs). Nothing is taken from Microsoft: not the Bliss photograph (the
hill here is one smooth curve and our own noise, not a photo or a trace of
one), not the "Azul" or "Autumn" pictures, and no logo or flag shapes.

    make-luna-wallpaper.py --all                every variant, every monitor,
                                                into the slideshow folders
    make-luna-wallpaper.py -v hill -W 1720 -H 720 -o /tmp/x.png
    make-luna-wallpaper.py --list               the variants

--all writes ~/Pictures/Wallpapers/<OUTPUT>/luna-<variant>.png for every
screen connected now at its LOGICAL size (screens.sizes(logical=True): the
mode over the scale, turned when the screen is rotated -- DP-1 3440x1440,
DP-2 3200x1350, HDMI-A-1 1080x1920, DP-3 1600x900 here; 1920x1080 for the
primary when Hyprland is not running), the same names in every folder, so
the screens change together (the luna theme's set: wallpaper_prefix=luna- in
~/.config/themes/luna/theme.conf; `theme.py check luna` insists on matching
names).

Variants:
    autumn  the hill's geometry in ochre to rust, with darker furrow stripes
            following the contour, under a late-afternoon sky that warms to a
            pale straw at the horizon
    azure   a sea horizon at 0.58 H: an azure sky, the sea deepening towards
            the viewer, a haze band on the horizon, sun glitter as small
            specks in an ellipse, and a faint distant headland
    hill    one broad rolling green dome (two sines on a base line, edged by
            a 2x2 supersampled smoothstep), fine grass texture, a soft
            highlight along the crest, far bluish hills for distance, and
            three to five soft cumulus clouds with lit tops and grey-blue
            bellies
    swoosh  a deep-to-mid blue vertical gradient crossed by three soft light
            ribbons, each a cubic Bezier band with a Gaussian falloff
    wheat   rows of wheat converging on a vanishing point at 0.55 H, a thin
            dark tree line on the horizon, and a pale summer sky

The rules, as in make-moe-wallpaper.py and make-lofi-wallpaper.py, for the
same reasons:
  * On an HDR screen (DP-1) SDR is mapped into the HDR range, so nothing
    reaches full scale: every channel is capped at PEAK (a too-bright colour
    is scaled down whole, not clipped per channel, so it keeps its hue).
    A blue XP sky is the largest field on the screen, so every sky is held
    at relative luminance <= SKY_LUM, the clouds at <= CLOUD_LUM, and the
    clouds cover at most CLOUD_COVER of the frame (cumulus(): a cloud set
    that comes out bigger is thinned until it fits). The glitter specks
    are each <= GLITTER_LUM.
    "Luminance" here is the WCAG relative luminance (sRGB decoded), the
    same number the theme's stylesheets quote.
  * The bar sits on the top QUIET px: no detail at all there (no clouds,
    no ribbons), and detail fades in below it over FADE px (detail_band()).
    luna's bar is opaque, so this band is about calm under the bar rather
    than the contrast of glass pills over a busy picture (lofi's reason).
  * finish(): a vignette (x 1 - 0.12 r^2), a faint luminance-only grain
    (Gaussian, sigma GRAIN), the PEAK cap, and a +-0.5 LSB dither against
    the banding a big smooth 8-bit gradient gets.
Sizes follow the short side (k = short / 1440), so a cloud or a glitter
speck is about the same physical size on every screen, portrait included;
layout uses fractions of W and H.

The accent does NOT follow the wallpaper in this theme (accent_follow=no in
themes/luna/theme.conf): a green hill would win theme-from-wallpaper.py's
hue vote with a green that reads as "good", and the autumn one with an
orange that reads as "warn". So nothing here is tuned for that vote.

Deterministic: each variant's randomness is seeded with zlib.crc32(variant),
so the same variant and size always give the same image, and the screens of
one set share their cloud and ribbon layout (positions are fractions).
Pure numpy + Pillow (both installed); about 5 s per ultrawide image, --all
(five variants on four screens) about 60-90 s.
"""

import argparse
import math
import os
import sys
import zlib

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (scripts/screens.py: the screens and their sizes)

PEAK = 0.80          # brightest channel value anywhere (make-wallpaper.py: 0.78)
SKY_LUM = 0.50       # ceiling for the relative luminance of every sky
CLOUD_LUM = 0.70     # ceiling for a cloud's lit top
CLOUD_COVER = 0.20   # most of the frame the clouds may cover (summed alpha)
GLITTER_LUM = 0.75   # ceiling for each speck of sun glitter on the sea
QUIET = 40           # k-px under the bar with no detail at all
FADE = 60            # k-px over which the detail fades in below that
GRAIN = 0.006        # luminance grain sigma, in 0..1
VIGNETTE = 0.12      # corners darkened by this much

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
VARIANTS = ["autumn", "azure", "hill", "swoosh", "wheat"]


# -- colour helpers --------------------------------------------------------------
def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def lum(rgb):
    """WCAG relative luminance of sRGB values in 0..1 (any shape (..., 3)).
    The 2.2 power stands in for the piecewise sRGB curve: within 0.005 of
    it everywhere that matters here, and much cheaper on 5 M pixels."""
    lin = np.clip(rgb, 0, None) ** 2.2
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def cap_lum(rgb, ceiling):
    """Scale each colour down whole until its luminance is <= ceiling (a
    colour under it is left alone). Luminance goes as value^2.2, so the
    factor is (ceiling / L)^(1/2.2)."""
    L = lum(rgb)
    f = np.minimum(1.0, (ceiling / np.maximum(L, 1e-6)) ** (1 / 2.2))
    return rgb * f[..., None]


def ramp(t, stops):
    """Colour at t (array) along [(pos, '#rrggbb'), ...], pos ascending."""
    pos = [p for p, _ in stops]
    cols = np.stack([hexc(c) for _, c in stops])
    return np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], -1).astype(np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    """a over b by t: t is a (H, W) or (H, W, 1) weight, a/b colours or images."""
    if np.ndim(t) == 2:
        t = t[..., None]
    return a * (1 - t) + b * t


# -- noise -------------------------------------------------------------------------
def value_noise(W, H, cw, ch, rng):
    """Smooth value noise in 0..1: a random lattice with cells cw x ch px,
    upsampled bicubically (PIL does the interpolation, which keeps a full
    screen of it to a few tens of milliseconds)."""
    cw, ch = max(1.0, cw), max(1.0, ch)
    gw, gh = int(W / cw) + 4, int(H / ch) + 4
    grid = rng.random((gh, gw)).astype(np.float32)
    big = Image.fromarray(grid, "F").resize((int(gw * cw), int(gh * ch)), Image.BICUBIC)
    return np.asarray(big, np.float32)[int(ch):int(ch) + H, int(cw):int(cw) + W]


def fbm(W, H, cell, rng, octaves=4, aspect=1.0, gain=0.5):
    """Fractal (fBm) noise in about 0..1: octaves of value_noise, each half
    the cell size and `gain` the weight of the last. `aspect` > 1 stretches
    the cells horizontally (grass, waves, cloud streaks)."""
    out = np.zeros((H, W), np.float32)
    amp, total = 1.0, 0.0
    for _ in range(octaves):
        out += amp * value_noise(W, H, cell * aspect, cell, rng)
        total += amp
        amp *= gain
        cell /= 2
    return out / total


# -- bands and finishing ---------------------------------------------------------
def detail_band(H, k):
    """0 over the top QUIET k-px (the bar), rising to 1 over FADE k-px below:
    every detail layer is multiplied by it."""
    yy = np.arange(H, dtype=np.float32)[:, None]
    return np.clip((yy - QUIET * k) / (FADE * k), 0.0, 1.0) ** 1.5


def sky(W, H, top, bottom, horizon, power=1.0):
    """The sky: `top` at y = 0 to `bottom` at y = horizon (px), held there
    below it, every pixel capped at SKY_LUM. `power` > 1 keeps the blue deep
    for longer and brightens only near the horizon, as a real sky does."""
    yy = np.arange(H, dtype=np.float32)[:, None]
    t = np.clip(yy / max(1.0, horizon), 0, 1) ** power
    rgb = ramp(np.broadcast_to(t, (H, W)), [(0.0, top), (1.0, bottom)])
    return cap_lum(rgb, SKY_LUM)


def finish(canvas, seed):
    """Vignette, luminance grain, PEAK cap (the HDR rule), then 8-bit with a
    +-0.5 LSB dither, clipped to PEAK once more after it. The grain is the same offset on all three channels, so
    it never tints. The cap SCALES a too-bright colour down whole instead of
    clipping each channel, so a pale cloud keeps its hue."""
    H, W = canvas.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
    canvas = canvas * (1 - VIGNETTE * r2)[..., None]
    rng = np.random.default_rng(seed ^ 0x5EED)
    canvas = canvas + rng.normal(0, GRAIN, (H, W, 1)).astype(np.float32)
    canvas = np.clip(canvas, 0.0, None)
    peak = canvas.max(axis=-1, keepdims=True)
    out = canvas / np.maximum(peak / PEAK, 1.0)
    px = out * 255.0 + rng.uniform(-0.5, 0.5, out.shape)
    # Clipped to PEAK again after the dither: float32 leaves a capped value a
    # hair over PEAK * 255, and a dither near +0.5 would round it one step up.
    top = math.floor(PEAK * 255 + 1e-6)
    return Image.fromarray(np.clip(np.rint(px), 0, top).astype(np.uint8), "RGB")


# -- shared scenery: the hill --------------------------------------------------------
def crest_fn(W, H, short, rng):
    """The hill's crest y(x), px: y = 0.62 H + 0.06 H sin(...) + 0.03 H sin(...).
    The first term is one broad dome (its peak placed left of centre, a
    third of the way in, where the eye enters a landscape); the second a
    slower roll on its shoulder. Frequencies are per short side, so the
    ultrawide shows one whole dome and the portrait screen one slope of it."""
    peak_u = rng.uniform(0.38, 0.46) * W / short
    phi2 = rng.uniform(0, 2 * math.pi)
    def crest(x):
        u = x / short
        return (0.62 * H + 0.06 * H * np.sin((u - peak_u) * 1.25 - math.pi / 2)
                + 0.03 * H * np.sin(u * 2.3 + phi2))
    return crest


def coverage(crest, W, H):
    """How much of each pixel lies below the crest (0..1): the edge of a
    2x2 supersample, each subsample a 1-subpixel smoothstep across the
    curve. The crest depends on x only, so this costs four 1-D curves and
    four cheap passes, not a 2x image."""
    yy = np.arange(H, dtype=np.float32)[:, None]
    xx = np.arange(W, dtype=np.float32)
    cov = np.zeros((H, W), np.float32)
    for dx in (-0.25, 0.25):
        c = crest(xx + dx).astype(np.float32)[None, :]
        for dy in (-0.25, 0.25):
            cov += smoothstep(-0.25, 0.25, yy + dy - c)
    return cov / 4


def hill_land(canvas, W, H, k, short, rng, crest, horizon_col, grass, highlight, far_col,
              furrows=False):
    """The far hill and the dome over a sky canvas. grass = (lit crest, low),
    highlight = the crest band's colour, far_col = the far hill before the
    haze. With furrows=True (autumn), darker stripes follow the contour,
    closer together towards the crest, as ploughed rows recede."""
    yy = np.arange(H, dtype=np.float32)[:, None]
    xx = np.arange(W, dtype=np.float32)

    # The far hills: a lower-contrast range behind the dome, lifted towards
    # the horizon colour (aerial perspective), seen where the dome dips. Three
    # overlapping rolls, about +-0.054 H in all, quick enough (per short
    # side) that the narrow gap beside the dome shows a hump or two, so the
    # range visibly rises and falls -- a nearly flat line here read as a
    # seam in the picture, not a hill. Its top stays below 0.536 H, under
    # the dome's highest point (0.53 H), so it never towers over the dome.
    far_phi = rng.uniform(0, 2 * math.pi)
    def far(x):
        u = x / short
        return (0.59 * H + 0.030 * H * np.sin(u * 2.6 + far_phi)
                + 0.017 * H * np.sin(u * 5.9 + far_phi * 2)
                + 0.007 * H * np.sin(u * 12.1 + far_phi * 3))
    # A softer edge than the dome's (3 px, not 1): distance blurs a skyline.
    fy = far(xx).astype(np.float32)[None, :]
    fcov = smoothstep(-1.5, 1.5, yy - fy)
    fcol = mix(hexc(far_col), hexc(horizon_col), 0.45)
    ftex = fbm(W, H, 60 * k, rng, 3, aspect=3)
    fland = fcol[None, None, :] * (0.97 + 0.06 * ftex)[..., None]
    # Haze on the ridge: the top 4% of H fades a further 35% into the
    # horizon colour, so the range melts into the sky instead of ending on a
    # hard line.
    ridge = np.clip((yy - fy) / (0.04 * H), 0, 1)
    fland = mix(fland, hexc(horizon_col)[None, None, :], (0.35 * (1 - ridge))[..., None])
    canvas = mix(canvas, fland, fcov)

    # The dome. depth: 0 on the crest, 1 at the bottom edge of the frame.
    cy = crest(xx).astype(np.float32)[None, :]
    depth = np.clip((yy - cy) / np.maximum(H - cy, 1), 0, 1)
    land = ramp(depth ** 0.7, [(0.0, grass[0]), (1.0, grass[1])])
    # The light comes from the upper left: the slope facing it is a little
    # brighter, the far side of the dome a little darker.
    slope = np.gradient(crest(xx).astype(np.float32))       # px per px: > 0 falling to the right
    face = np.clip(-slope * 8, -1, 1)[None, :] * (1 - depth) * 0.06
    land *= (1 + face)[..., None]
    # Grass: fine value noise stretched along the ground, +-3 %, and a broad
    # fBm so the field rolls in light and shade instead of lying flat.
    fine = value_noise(W, H, 5 * k, 2 * k, rng) * 0.5 + value_noise(W, H, 2.5 * k, 1.2 * k, rng) * 0.5
    broad = fbm(W, H, 260 * k, rng, 3, aspect=2.5)
    land *= (1 + 0.06 * (fine - 0.5) + 0.10 * (broad - 0.5))[..., None]
    if furrows:
        # Rows along the contour: the phase runs as depth^0.55, so they bunch
        # towards the crest (farther away) and open out at the bottom.
        phase = depth ** 0.55 * 46
        period_px = (H - cy) / (46 * 0.55) * np.maximum(depth, 1e-3) ** 0.45
        fade = smoothstep(3, 8, period_px)                    # no moire where they bunch up
        stripe = smoothstep(0.55, 0.95, 0.5 + 0.5 * np.sin(2 * math.pi * phase + 3 * (broad - 0.5)))
        land *= (1 - 0.14 * stripe * fade)[..., None]
    # The soft band of light along the crest, where the grass catches the sky.
    dist = (yy - cy) / (0.035 * H)
    band = np.exp(-np.clip(dist, 0, None) ** 2) * 0.35
    land = mix(land, hexc(highlight)[None, None, :], band)
    return mix(canvas, land, coverage(crest, W, H))


def cumulus(canvas, W, H, k, short, rng, band, n, lit, belly, y_range, crest=None):
    """n soft fair-weather clouds: an ellipse envelope (flatter below than
    above, as a cumulus sits on its condensation level) eroded by fBm and
    smoothstep-thresholded, so the edges are soft and lumpy. Shaded from
    `lit` at the top to `belly` underneath. Each colour is capped at
    CLOUD_LUM, the layer faded under the bar by `band`, and the whole set
    thinned (a higher threshold) until it covers <= CLOUD_COVER."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    clouds = []
    # Spread across the width: one per slot, jittered, so they never pile up.
    for i in range(n):
        cx = (i + rng.uniform(0.2, 0.8)) / n * W
        rx = rng.uniform(0.18, 0.30) * short * (1.0 if W >= H else 0.8)
        ry = rx * rng.uniform(0.36, 0.46)
        cy = rng.uniform(*y_range) * H
        cy = max(cy, (QUIET + FADE) * k + ry * 1.2)           # never into the bar's band
        if crest is not None:                                  # and never behind the hill
            cy = min(cy, float(crest(np.array([cx]))[0]) - ry * 0.9)
        clouds.append((cx, cy, rx, ry))
    noise = fbm(W, H, 90 * k, rng, 5, aspect=1.6)
    noise2 = fbm(W, H, 40 * k, rng, 3)
    dens = np.zeros((H, W), np.float32)
    shade = np.zeros((H, W), np.float32)
    for cx, cy, rx, ry in clouds:
        ry_y = np.where(yy < cy, ry, ry * 0.55)                # a flatter belly
        e = 1 - ((xx - cx) / rx) ** 2 - ((yy - cy) / ry_y) ** 2
        d = e + 0.9 * (noise - 0.5)
        here = d > dens
        dens = np.maximum(dens, d)
        # Lit from above: 1 on top, 0 on the belly, the noise breaking it up
        # into lumps that each catch the light.
        s = np.clip((cy + 0.35 * ry - yy) / (1.3 * ry) + 0.6 * (noise2 - 0.5), 0, 1)
        shade = np.where(here, s, shade)
    lit_c, belly_c = cap_lum(hexc(lit), CLOUD_LUM), cap_lum(hexc(belly), CLOUD_LUM)
    colour = mix(belly_c[None, None, :], lit_c[None, None, :], smoothstep(0, 1, shade))
    lo = 0.30
    while True:
        alpha = smoothstep(lo, lo + 0.35, dens) * 0.92 * band
        if alpha.mean() <= CLOUD_COVER or lo > 0.9:
            break
        lo += 0.05
    return mix(canvas, colour, alpha)


# -- the variants --------------------------------------------------------------------
def hill(W, H, k, short, rng, band):
    horizon = 0.62 * H
    canvas = sky(W, H, "#1f5fbf", "#8fb8e8", horizon, power=1.6)
    crest = crest_fn(W, H, short, rng)
    canvas = cumulus(canvas, W, H, k, short, rng, band, int(rng.integers(3, 6)),
                     "#eef2fa", "#8c9cbc", (0.16, 0.36), crest)
    canvas = hill_land(canvas, W, H, k, short, rng, crest, "#8fb8e8",
                          ("#4f9a2e", "#2a6a1c"), "#7cc04a", "#3f7a3a")
    return canvas


def autumn(W, H, k, short, rng, band):
    horizon = 0.62 * H
    canvas = sky(W, H, "#2a5aa8", "#c8b890", horizon, power=1.5)
    crest = crest_fn(W, H, short, rng)
    canvas = cumulus(canvas, W, H, k, short, rng, band, int(rng.integers(3, 5)),
                     "#f2e6d4", "#8a8aa4", (0.16, 0.34), crest)
    canvas = hill_land(canvas, W, H, k, short, rng, crest, "#c8b890",
                          ("#b07a26", "#6a3e14"), "#d0a052", "#7a6a48", furrows=True)
    return canvas


def bezier(p, n=1200):
    """n points along the cubic Bezier with control points p (4 x 2)."""
    t = np.linspace(0, 1, n)[:, None]
    p = np.asarray(p, np.float32)
    return ((1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1]
            + 3 * (1 - t) * t ** 2 * p[2] + t ** 3 * p[3])


def swoosh(W, H, k, short, rng, band):
    canvas = sky(W, H, "#0b2a6a", "#2a63c8", H - 1, power=1.2)
    yy = np.arange(H, dtype=np.float32)[:, None]
    xx = np.arange(W, dtype=np.float32)
    light = np.zeros((H, W), np.float32)
    # Ribbons run across the long way of the screen. Each is a cubic Bezier
    # whose control points march across x, so it is a function y(x) and the
    # distance to it is the vertical gap times cos(slope) -- the per-column
    # trick make-aero-wallpaper.py uses, instead of a point-to-curve search.
    # Each ribbon gets its own slot down the screen (they fan out from the
    # lower left and part towards the right), so they never bunch into one.
    for i in range(3):
        y0 = (0.62 + 0.10 * i + rng.uniform(-0.03, 0.03)) * H
        y3 = (0.30 + 0.20 * i + rng.uniform(-0.04, 0.04)) * H
        p = [(-0.05 * W, y0), (rng.uniform(0.25, 0.4) * W, y0 - rng.uniform(0.10, 0.30) * H),
             (rng.uniform(0.6, 0.75) * W, y3 + rng.uniform(0.05, 0.25) * H), (1.05 * W, y3)]
        pts = bezier(p)
        cy = np.interp(xx, pts[:, 0], pts[:, 1]).astype(np.float32)
        slope = np.gradient(cy)
        dist = np.abs(yy - cy[None, :]) / np.sqrt(1 + slope ** 2)[None, :]
        # Widest in the middle of the screen, tapering at the ends.
        taper = 0.35 + 0.65 * np.sin(np.clip(xx / W, 0, 1) * math.pi) ** 1.5
        width = rng.uniform(26, 60) * k * taper[None, :]
        light += 0.30 * np.exp(-(dist / width) ** 2) * rng.uniform(0.7, 1.0)
        # a thin brighter core on one edge, so it reads as a folded ribbon
        light += 0.10 * np.exp(-((dist - 0.6 * width) / (0.12 * width)) ** 2)
    alpha = np.clip(light, 0, 0.42) * band
    return mix(canvas, hexc("#ffffff")[None, None, :], alpha)


def wheat(W, H, k, short, rng, band):
    vy = 0.55 * H
    vx = rng.uniform(0.42, 0.58) * W
    canvas = sky(W, H, "#3a74c8", "#b4d0ec", vy, power=1.4)
    # A few thin, high wisps: a summer sky, not an empty one.
    wisp = smoothstep(0.58, 0.80, fbm(W, H, 160 * k, rng, 4, aspect=4.0))
    yy = np.arange(H, dtype=np.float32)[:, None]
    wisp *= np.clip((vy - yy) / (0.25 * H), 0, 1) * band
    canvas = mix(canvas, cap_lum(hexc("#e6eef8"), CLOUD_LUM)[None, None, :], wisp * 0.35)

    xx = np.arange(W, dtype=np.float32)[None, :]
    depth = np.clip((yy - vy) / (H - vy), 0, 1)                  # 0 on the horizon
    field = ramp(np.broadcast_to(depth ** 0.6, (H, W)), [(0.0, "#c8a040"), (1.0, "#7a5a1c")])
    # Rows: lines through the vanishing point are equal steps of the ground
    # coordinate q = (x - vx) / (y - vy). A row's period on screen shrinks to
    # nothing at the horizon, so the stripes fade out where it drops under a
    # few pixels (no moire), leaving the haze of distance.
    dy = np.maximum(yy - vy, 1.0)
    q = (xx - vx) / dy
    density = 1.8 / k                                             # rows per unit q
    period_px = dy / density
    stripes = 0.5 + 0.5 * np.cos(2 * math.pi * q * density)
    amp = smoothstep(3, 9, period_px)
    field *= (1 - 0.16 * amp * smoothstep(0.35, 1.0, stripes))[..., None]
    # Ears of wheat: fine noise stretched vertically, stronger up close.
    ears = value_noise(W, H, 1.6 * k, 7 * k, rng)
    sway = fbm(W, H, 220 * k, rng, 3, aspect=2)
    field *= (1 + (0.04 + 0.06 * depth) * (ears - 0.5) + 0.10 * (sway - 0.5))[..., None]
    # Haze over the far field, from the sky's horizon colour.
    field = mix(field, hexc("#b4d0ec")[None, None, :], (1 - depth) ** 6 * 0.35)
    ground = smoothstep(-0.5, 0.5, yy - vy) * np.ones((1, W), np.float32)
    canvas = mix(canvas, field, ground)
    # The tree line: crowns from 1-D noise, 4..14 k-px tall, one dark green.
    tops = fbm(W, 8, 40 * k, rng, 4)[4] * 0.6 + value_noise(W, 8, 9 * k, 4, rng)[4] * 0.4
    hgt = (4 + 12 * tops) * k
    trees = smoothstep(-0.5, 0.5, yy - (vy - hgt[None, :])) * smoothstep(-0.5, 0.5, vy + 1.5 * k - yy)
    tree_col = mix(hexc("#1f3a1c"), hexc("#b4d0ec"), 0.18)
    return mix(canvas, tree_col[None, None, :], trees)


def azure(W, H, k, short, rng, band):
    hy = 0.58 * H
    canvas = sky(W, H, "#2a6ac8", "#9cc4ec", hy, power=1.5)
    yy = np.arange(H, dtype=np.float32)[:, None]
    xx = np.arange(W, dtype=np.float32)[None, :]
    depth = np.clip((yy - hy) / (H - hy), 0, 1)
    sea = ramp(np.broadcast_to(depth ** 0.8, (H, W)), [(0.0, "#0e4a8a"), (1.0, "#08305e")])
    # Waves: noise stretched along the horizon, cells growing towards the
    # viewer (two layers mixed by depth stand in for true perspective).
    far_w = value_noise(W, H, 40 * k, 2 * k, rng)
    near_w = value_noise(W, H, 120 * k, 9 * k, rng)
    waves = mix(far_w[..., None], near_w[..., None], depth)[..., 0]
    sea *= (1 + (0.03 + 0.05 * depth) * (waves - 0.5))[..., None]
    water = smoothstep(-0.5, 0.5, yy - hy) * np.ones((1, W), np.float32)
    canvas = mix(canvas, sea, water)

    # The headland: a faint low ridge on the horizon, a little to one side,
    # half lost in the haze.
    hx = rng.uniform(0.10, 0.30) * W
    hw = 0.22 * W if W >= H else 0.4 * W
    prof = np.clip(1 - ((xx - hx) / hw) ** 2, 0, None) ** 0.7
    ridge = prof * (0.028 * H) * (0.85 + 0.15 * fbm(W, 4, 30 * k, rng, 3)[2][None, :])
    land = smoothstep(-0.5, 0.5, yy - (hy - ridge)) * smoothstep(-0.5, 0.5, hy + 0.5 - yy) * (prof > 0)
    canvas = mix(canvas, mix(hexc("#3a5f8e"), hexc("#9cc4ec"), 0.35)[None, None, :], land * 0.85)

    # The haze band on the horizon, both sides of it.
    haze = np.exp(-((yy - hy) / (0.022 * H)) ** 2) * 0.30 * np.ones((1, W), np.float32)
    canvas = mix(canvas, hexc("#b8d0ea")[None, None, :], haze)

    # Sun glitter: small horizontal specks inside an ellipse below the sun's
    # (unseen, high) position, thick near its middle, thinning to its rim.
    gx = rng.uniform(0.58, 0.72) * W
    gy = hy + 0.17 * (H - hy)
    rx, ry = (0.10 * W if W >= H else 0.28 * W), 0.15 * (H - hy)
    speck = cap_lum(hexc("#e2eaf2"), GLITTER_LUM)
    glit = np.zeros((H, W), np.float32)
    count = int(2600 * (W * H) / (3440 * 1440))
    for _ in range(count):
        ex, ey = rng.normal(0, 0.45), rng.normal(0, 0.45)
        if ex * ex + ey * ey > 1:
            continue
        x = gx + ex * rx
        y = gy + ey * ry
        d = (y - hy) / (H - hy)                         # specks grow towards the viewer
        sw = (1.5 + 5 * d) * k * rng.uniform(0.6, 1.4)
        sh = max(0.6, (0.6 + 1.2 * d) * k)
        x0, x1 = int(max(0, x - 2 * sw)), int(min(W, x + 2 * sw + 1))
        y0, y1 = int(max(0, y - 2 * sh)), int(min(H, y + 2 * sh + 1))
        if x1 <= x0 or y1 <= y0:
            continue
        lx = np.arange(x0, x1, dtype=np.float32)[None, :]
        ly = np.arange(y0, y1, dtype=np.float32)[:, None]
        a = np.exp(-((lx - x) / sw) ** 2 - ((ly - y) / sh) ** 2) * rng.uniform(0.35, 0.9) * (1 - ex * ex - ey * ey)
        glit[y0:y1, x0:x1] = np.maximum(glit[y0:y1, x0:x1], a)
    # a faint sheen under the specks, so they sit on lit water
    sheen = np.exp(-(((xx - gx) / (1.3 * rx)) ** 2 + ((yy - gy) / (1.3 * ry)) ** 2)) * 0.10 * water
    canvas = mix(canvas, hexc("#7aa6d8")[None, None, :], sheen)
    return mix(canvas, speck[None, None, :], np.clip(glit, 0, 1) * water)


SCENES = {"autumn": autumn, "azure": azure, "hill": hill, "swoosh": swoosh, "wheat": wheat}


def render(W, H, variant):
    seed = zlib.crc32(variant.encode())
    rng = np.random.default_rng(seed)
    short = min(W, H)
    k = short / 1440
    canvas = SCENES[variant](W, H, k, short, rng, detail_band(H, k))
    return finish(canvas.astype(np.float32), seed)


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
    ap.add_argument("-v", "--variant", default="hill", choices=VARIANTS)
    ap.add_argument("-o", "--output", help="one image to this path")
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's (logical)")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's (logical)")
    a = ap.parse_args()
    if a.list:
        print("\n".join(VARIANTS))
        return
    if a.all:
        sizes = screens.sizes(logical=True)
        for variant in VARIANTS:
            for mon, (w, h) in sizes.items():
                write(render(w, h, variant), os.path.join(WALLDIR, mon, f"luna-{variant}.png"))
        return
    if not a.output:
        ap.error("give -o FILE, or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size(logical=True)
    write(render(a.width, a.height, a.variant), a.output)


if __name__ == "__main__":
    main()
