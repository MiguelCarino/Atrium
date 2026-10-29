#!/usr/bin/env python3
"""Render wallpapers for the orchard theme (the macOS-like desktop): one
picture for every era of that desktop's wallpapers, from the first glossy
blue of 2001 to the liquid glass of 2025 -- a blue swoosh, light streaks,
ribbons, a spiral of light, two auroras, two galaxies, an ocean wave, the
granite valley and its cliff at dusk, a snowy range, an autumn lake, dunes
by day and by night, an island and a coast at dusk, gradient hills, flowing
waves, a bloom, green hills, silk, a tall forest at dawn, glass waves and an
alpine lake. Every one is drawn from scratch here (Perlin noise, a small
heightfield renderer, analytic curves and gradients). Nothing is taken from
Apple: no photograph is downloaded, traced or sampled, no colour is picked
off one, and the file names say what is in the picture, never a release
name. Each picture only EVOKES its era's mood (a blue swoosh, an aurora, a
granite wall at golden hour); the geometry, the noise and the light are our
own.

    make-orchard-wallpaper.py --all             every variant, every monitor,
                                                into the slideshow folders
    make-orchard-wallpaper.py --all --also HDMI-A-1=1080x1920
                                                ... and a folder that is not
                                                connected now, at that size
    make-orchard-wallpaper.py -v 07 -W 1720 -H 720 -o /tmp/x.png
    make-orchard-wallpaper.py -v dunes-day -o /tmp/x.png
    make-orchard-wallpaper.py --list            the variants

--all writes ~/Pictures/Wallpapers/<OUTPUT>/orchard-NN-<slug>.png for every
screen connected now at its LOGICAL size (screens.sizes(logical=True): the
mode over the scale, turned when the screen is rotated -- DP-1 3440x1440,
DP-2 3200x1350, DP-3 1600x900 here; 1920x1080 for the primary when Hyprland
is not running), the same names in every folder, so the screens change
together (the orchard themes' set: wallpaper_prefix=orchard- in
~/.config/themes/orchard/theme.conf; `theme.py check orchard` compares DP-1,
DP-2 and HDMI-A-1, so the portrait HDMI-A-1 folder needs the set too even
while that screen is unplugged -- hence --also).

Variants (NN-slug: the era it evokes, in plain words -- what is drawn):
    01-azure-swoosh     the first glossy-blue desktop (2001): a luminous azure
                        S-ribbon with a satin highlight on sapphire, a fainter
                        echo below it, a cloth-like shimmer
    02-azure-streaks    light streaks (2002): sixty fine curved filaments of
                        cyan-white fanning out of a focus off the lower left
                        corner, with bloom, on a cobalt radial gradient
    03-blue-ribbons     brushed blue ribbons (2003): three translucent
                        twisting bands with bright edges and dark cores, soft
                        drop shadows, over brushed cobalt
    04-light-rays       swirling light (2005): a three-armed spiral of light
                        with a white core, god-ray streaks and sparkle, on
                        deep navy
    05-aurora-space     aurora over space (2007): a starfield and folded
                        aurora curtains, teal at the foot to violet and pink
                        at the top, with ray striations
    06-aurora-snow      the snowy aurora (2009): cooler lilac and ice-blue
                        curtains, snow glitter, a frosted fog band
    07-spiral-galaxy    the big spiral galaxy (2011): an inclined two-armed
                        disc galaxy -- warm bulge, blue arms, pink knots,
                        dust lanes -- over a deep starfield
    08-galaxy-nebula    the starfield galaxy (2012): a diagonal milky way with
                        a warm core, dark rifts and diffraction-spiked stars
    09-ocean-wave       the big ocean wave (2013): a towering wave peaking
                        left of centre -- a clean turquoise face where the
                        light comes through the lip, already broken into
                        white water on its left -- spray streaming off the
                        crest, foam lace in the trough, an overcast sky
    10-granite-valley   the granite valley (2014): a granite monolith at
                        golden hour over a conifer valley, ridges fading into
                        haze
    11-granite-cliff-dusk  the great cliff at dusk (2015): the wall in
                        alpenglow under a blue-violet sky, first stars
    12-snowy-peaks      the snowy range (2016): a ridged range under a low
                        sun, snow on the gentle slopes, two haze layers
    13-mountain-lake    the autumn alpine lake (2017): mountains mirrored in a
                        rippled lake, gold and orange trees on the shore
    14-dunes-day        desert dunes by day (2018): sharp-crested dunes under
                        a low warm sun, wind ripples, a hazy horizon
    15-dunes-night      desert dunes by night (2018): the same dunes in
                        moonlight, stars and a blue horizon glow
    16-island-dusk      the rocky island at dusk (2019): an island on a calm
                        sea under a peach-to-lavender sky, its reflection
    17-coast-cliffs     coastal cliffs (2020): five headlands receding into
                        fog, a pastel sky, foam at the cliff feet
    18-gradient-hills   smooth gradient hills (2020): five layered hills in
                        blue, violet, magenta and coral, soft crest shadows
    19-flowing-waves    colourful flowing waves (2021): overlapping ribbons in
                        purple, blue, pink and coral with soft shading
    20-orange-bloom     the abstract bloom (2022): translucent orange petals
                        radiating from one point over a dark warm ground
    21-green-hills      rolling green hills (2023): stylised hills in fresh
                        greens, fog between them, vine rows on the nearest
    22-silk-folds       silky folds (2024): a sheet of teal-to-blue silk with
                        a soft sheen
    23-redwood-dawn     tall-forest sunrise (2024): giant red-brown trunks in
                        dusky dawn mist, rim-lit by a low sun, god rays slanting
                        between them, a fern floor
    24-glass-waves      liquid-glass waves (2025): translucent glass layers
                        that refract the gradient behind them, bright rims
    25-alpine-lake      the deep-blue alpine lake (2025): a sapphire lake in
                        dark pine ridges under a snowy peak, afternoon light

Composition is resolution-independent: everything is drawn in u = (x -
W/2) / H and v = y / H, so the ultrawide shows more at the sides, the 16:9
screens the middle, and the portrait screen a crop around the subject; the
subjects sit on the centre region. The noise (Perlin, seeded from the
variant only, evaluated in u, v or in world space) and the geometry are the
same on every screen, so the four screens show one picture at four crops.

The rules, as in make-luna-wallpaper.py and make-lofi-wallpaper.py, for the
same reasons:
  * Scenes are composed in float32 LINEAR light (lights add as light does,
    hazes and glows mix as they do in air) and encoded to sRGB at the end.
  * On an HDR screen (DP-1) SDR is mapped into the HDR range, so nothing
    reaches full scale: every channel is capped at PEAK after encoding (a too
    bright colour is scaled down whole, not clipped, so it keeps its hue),
    and no large field is brighter than FIELD_LUM relative luminance (the
    luminance of a heavily blurred copy is held under it, so a bright sky or
    a pale abstract is dimmed as a field while a small highlight inside it
    keeps its contrast) -- the theme's own rule (themes/orchard/theme.conf:
    no large field above 0.52).
  * The bar and the island's notch sit on the top QUIET px: the picture
    there is blended into a heavily blurred copy of itself, and the detail
    fades back in over FADE px below (calm_top()), so the bar and the notch
    sit on calm colour.
  * finish(): a soft vignette (x 1 - VIGNETTE r^2), a fine luminance-only
    grain (Gaussian, GRAIN LSB), the PEAK cap, a triangular +-0.5 LSB
    dither, then 8 bit: no banding in any gradient.
Edges are analytic (a smoothstep one pixel wide), never stair-stepped.
Pixel sizes that should look the same on every screen (a star, a filament)
follow the short side (k = short / 1440).

Deterministic: the geometry is seeded with "orchard-<slug>" (so the screens
agree), the grain and dither with "orchard-<slug>-<W>x<H>". Pure numpy +
Pillow (both installed). Renders one image at a time, float32 throughout:
peak memory well under 1.5 GB at 3440x1440, 5-30 s per ultrawide image.
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

PEAK = 0.80          # brightest channel value anywhere, sRGB-encoded
FIELD_LUM = 0.50     # ceiling for a large field's relative luminance (theme: 0.52)
QUIET = 36           # px under the bar with no detail at all (the bar's 38 px strip)
FADE = 70            # px over which the detail fades back in below that
GRAIN = 0.6          # luminance grain sigma, in 8-bit LSB
VIGNETTE = 0.12      # the corners darkened by this much
F32 = np.float32

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
VARIANTS = [
    ("01", "azure-swoosh"), ("02", "azure-streaks"), ("03", "blue-ribbons"),
    ("04", "light-rays"), ("05", "aurora-space"), ("06", "aurora-snow"),
    ("07", "spiral-galaxy"), ("08", "galaxy-nebula"), ("09", "ocean-wave"),
    ("10", "granite-valley"), ("11", "granite-cliff-dusk"), ("12", "snowy-peaks"),
    ("13", "mountain-lake"), ("14", "dunes-day"), ("15", "dunes-night"),
    ("16", "island-dusk"), ("17", "coast-cliffs"), ("18", "gradient-hills"),
    ("19", "flowing-waves"), ("20", "orange-bloom"), ("21", "green-hills"),
    ("22", "silk-folds"), ("23", "redwood-dawn"), ("24", "glass-waves"),
    ("25", "alpine-lake"),
]


def filename(number, slug):
    return f"orchard-{number}-{slug}.png"


# -- colour ------------------------------------------------------------------------
def srgb_to_lin(c):
    c = np.asarray(c, F32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(F32)


def lin_to_srgb(c):
    c = np.clip(c, 0.0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055).astype(F32)


def hexs(h):
    """'#rrggbb' -> sRGB-encoded floats (3,)."""
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], F32)


def col(h, gain=1.0):
    """'#rrggbb' -> LINEAR floats (3,), times gain (gain > 1 is light, not paint)."""
    return srgb_to_lin(hexs(h)) * F32(gain)


def lum(rgb):
    """WCAG relative luminance of LINEAR rgb (..., 3)."""
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def ramp(t, stops):
    """Colour at t along [(pos, '#rrggbb'), ...]: interpolated in sRGB (the
    way a designer's gradient runs: perceptually even), returned LINEAR."""
    t = np.asarray(t, F32)
    pos = [p for p, _ in stops]
    cs = np.stack([hexs(c) for _, c in stops])
    out = np.stack([np.interp(t, pos, cs[:, i]).astype(F32) for i in range(3)], -1)
    return srgb_to_lin(out)


def kelvin(t):
    """An approximate blackbody colour (linear, max channel 1) for a star's
    temperature: the usual Tanner Helland fit, enough for a tint."""
    t = t / 100.0
    r = 1.0 if t <= 66 else min(1.0, 1.29293618606 * (t - 60) ** -0.1332047592)
    g = (0.39008157876 * math.log(t) - 0.63184144378) if t <= 66 else 1.12989086089 * (t - 60) ** -0.0755148492
    b = 1.0 if t >= 66 else (0.0 if t <= 19 else 0.54320678911 * math.log(t - 10) - 1.19625408914)
    c = srgb_to_lin(np.clip([r, g, b], 0, 1))
    return c / c.max()


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    """a towards b by t: t a (H, W) / (H, 1) weight or a scalar."""
    if np.ndim(t) == 2:
        t = t[..., None]
    return a + (b - a) * t


def add(canvas, colour, amount):
    """Add light: colour (3,) or (H, W, 3) times amount (2-D)."""
    if np.ndim(amount) == 2:
        amount = amount[..., None]
    return canvas + colour * amount


# -- blur and sampling --------------------------------------------------------------
def _box(a, r, axis):
    """Box filter of radius r (px, int) along axis, edges clamped (cumsum)."""
    if r < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    p = np.pad(a, pad, mode="edge").astype(np.float64)
    c = np.cumsum(p, axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(F32)


def _resize(a, w, h):
    """Bilinear resize of a 2-D float array (PIL mode F)."""
    return np.asarray(Image.fromarray(np.ascontiguousarray(a, F32), "F").resize((w, h), Image.BILINEAR), F32)


def blur(a, sigma, sy=None):
    """Gaussian blur (three box passes) of a 2-D or (H, W, 3) array, sigma in
    px (sy: a different vertical sigma). Big blurs run on a shrunk copy,
    which is both faster and smoother."""
    sy = sigma if sy is None else sy
    if a.ndim == 3:
        return np.stack([blur(a[..., i], sigma, sy) for i in range(a.shape[2])], -1)
    if sigma < 0.3 and sy < 0.3:
        return a.astype(F32)
    H, W = a.shape
    s = max(1.0, min(sigma, sy) / 4.0)
    if s > 1.5:
        w, h = max(4, int(W / s)), max(4, int(H / s))
        small = _resize(a, w, h)
        small = blur(small, sigma * w / W, sy * h / H)
        return _resize(small, W, H)
    out = a.astype(F32)
    for sg, axis in ((sigma, 1), (sy, 0)):
        # Three boxes of width w give a Gaussian of variance 3 (w^2 - 1) / 12.
        r = int(round((math.sqrt(4 * sg * sg + 1) - 1) / 2))
        for _ in range(3):
            out = _box(out, r, axis)
    return out


def sample(img, x, y):
    """Bilinear lookup of img (H, W[, 3]) at float pixel coords x, y (H, W)."""
    H, W = img.shape[:2]
    x = np.clip(x, 0, W - 1.001)
    y = np.clip(y, 0, H - 1.001)
    x0 = x.astype(np.int32)
    y0 = y.astype(np.int32)
    fx = (x - x0).astype(F32)
    fy = (y - y0).astype(F32)
    if img.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    a = img[y0, x0] * (1 - fx) + img[y0, x0 + 1] * fx
    b = img[y0 + 1, x0] * (1 - fx) + img[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


# -- noise -------------------------------------------------------------------------
GX = np.array([1, -1, 1, -1, 1, -1, 0, 0], F32)
GY = np.array([1, 1, -1, -1, 0, 0, 1, -1], F32)


class Noise:
    """Seeded 2-D Perlin (gradient) noise evaluated at any float coordinates,
    so the same pattern lands at the same u, v (or world x, z) on every
    screen. fbm() sums octaves, each turned and shifted, so the lattice never
    shows; ridged() is the ridged multifractal (sharp crests) mountains use."""

    def __init__(self, rng):
        p = rng.permutation(256).astype(np.int32)
        self.perm = np.concatenate([p, p, p[:1]])
        self.shift = rng.uniform(-500, 500, (16, 2)).astype(F32)
        ang = rng.uniform(0, 2 * math.pi, 16)
        self.rot = np.stack([np.cos(ang), np.sin(ang)], -1).astype(F32)

    def __call__(self, x, y):
        x, y = np.broadcast_arrays(np.asarray(x, F32), np.asarray(y, F32))
        xf = np.floor(x)
        yf = np.floor(y)
        xi = xf.astype(np.int32) & 255
        yi = yf.astype(np.int32) & 255
        x = x - xf
        y = y - yf
        u = x * x * x * (x * (x * 6 - 15) + 10)
        v = y * y * y * (y * (y * 6 - 15) + 10)
        p = self.perm
        a = p[xi] + yi
        b = p[xi + 1] + yi
        h00, h01, h10, h11 = p[a] & 7, p[a + 1] & 7, p[b] & 7, p[b + 1] & 7
        n00 = GX[h00] * x + GY[h00] * y
        n10 = GX[h10] * (x - 1) + GY[h10] * y
        n01 = GX[h01] * x + GY[h01] * (y - 1)
        n11 = GX[h11] * (x - 1) + GY[h11] * (y - 1)
        nx0 = n00 + u * (n10 - n00)
        nx1 = n01 + u * (n11 - n01)
        return nx0 + v * (nx1 - nx0)

    def _oct(self, i, x, y, f):
        c, s = self.rot[i]
        ox, oy = self.shift[i]
        return self(f * (c * x - s * y) + ox, f * (s * x + c * y) + oy)

    def fbm(self, x, y, octaves=5, lac=2.0, gain=0.5):
        """About -1..1 (Perlin's +-0.7 rescaled)."""
        out = 0.0
        amp, total, f = 1.0, 0.0, 1.0
        for i in range(octaves):
            out = out + amp * self._oct(i, x, y, f)
            total += amp
            amp *= gain
            f *= lac
        return out * F32(1.45 / total)

    def ridged(self, x, y, octaves=6, lac=2.05, gain=0.5, sharp=2.0):
        """0..1: crests (1 - |n|)^sharp, each octave weighted by the last, so
        detail gathers on the ridges and the valleys stay smooth."""
        out = 0.0
        amp, total, f, w = 1.0, 0.0, 1.0, 1.0
        for i in range(octaves):
            r = (1 - np.abs(self._oct(i, x, y, f) * 1.45)).clip(0, 1) ** sharp
            out = out + amp * r * w
            w = np.clip(r * 1.6, 0, 1)
            total += amp
            amp *= gain
            f *= lac
        return out / F32(total)


# -- the frame ---------------------------------------------------------------------
class Frame:
    """One render: the size, the u/v grids, the seeded generators."""

    def __init__(self, W, H, slug):
        self.W, self.H = W, H
        self.k = min(W, H) / 1440
        self.half = W / H / 2                      # the u extent: +-half
        self.u = ((np.arange(W, dtype=F32) + 0.5 - W / 2) / H)[None, :]
        self.v = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
        self.px = 1.0 / H                          # one pixel in u/v units
        self.rng = np.random.default_rng(zlib.crc32(f"orchard-{slug}".encode()))
        self.noise = Noise(self.rng)

    def uu(self):
        return np.broadcast_to(self.u, (self.H, self.W))

    def vv(self):
        return np.broadcast_to(self.v, (self.H, self.W))

    def vgrad(self, stops):
        """A vertical gradient over v as a full (H, W, 3) canvas."""
        return np.ascontiguousarray(np.broadcast_to(ramp(self.v[:, 0], stops)[:, None, :],
                                                    (self.H, self.W, 3)))

    def aa(self, d):
        """Coverage 0..1 from a signed distance d in u/v units (> 0 inside):
        a smoothstep one pixel wide -- the analytic antialiasing."""
        return smoothstep(-0.5, 0.5, d * self.H)

    def centre_u(self, want, margin=0.30):
        """Where to put a subject that wants to sit at u = want on the
        ultrawide: pulled in so it stays at least `margin` inside the frame
        on a narrower screen (portrait: it lands near the middle)."""
        lim = max(0.0, self.half - margin)
        return float(np.clip(want, -lim, lim))


def ystroke(fr, layer, vc, sigma, inten):
    """Splat a thin line into `layer` (H, W): for every column a Gaussian
    across the curve v = vc(u) (vc, sigma, inten: (W,) arrays in v units),
    the vertical gap scaled by the slope so the width is measured across the
    line. Only a window of rows around the curve is touched, so sixty
    filaments cost less than one full-frame pass."""
    H, W = fr.H, fr.W
    slope = np.gradient(vc) * H                      # dv/dx in px per px
    cosf = 1 / np.sqrt(1 + slope ** 2)
    spx = np.maximum(sigma * H, 0.55)
    reach = np.minimum(np.ceil(4 * spx / cosf).max(), 80).astype(int)
    rows = np.arange(-reach, reach + 1)[:, None]
    cy = vc * H - 0.5
    r = np.floor(cy).astype(int)[None, :] + rows
    d = (r - cy[None, :]) * cosf[None, :]
    val = inten[None, :] * np.exp(-(d / spx[None, :]) ** 2)
    cols = np.broadcast_to(np.arange(W)[None, :], r.shape)
    ok = (r >= 0) & (r < H) & (val > 1e-5)
    np.add.at(layer, (r[ok], cols[ok]), val[ok].astype(F32))


def starfield(fr, density, v0=0.0, v1=1.0, weight=None, temp=(3500, 9000), bright=1.0,
              size=0.75, seed_shift=0, layer=None):
    """Stars: Poisson positions over the WIDEST frame (u in +-1.3) so every
    screen shows the same sky, a power-law brightness (many faint, few
    bright), tinted by temperature, splatted bilinearly and blurred to
    1-2 px discs. `weight(u, v)` thins them (a galaxy band); returns an
    (H, W, 3) linear light layer."""
    rng = np.random.default_rng(zlib.crc32(f"stars-{seed_shift}".encode()) ^ int(fr.rng.integers(1 << 30)))
    n = int(density * 2.6 * (v1 - v0))
    us = rng.uniform(-1.3, 1.3, n).astype(F32)
    vs = rng.uniform(v0, v1, n).astype(F32)
    mag = (rng.pareto(1.6, n) + 1).astype(F32)
    b = np.minimum(mag ** 1.25 * 0.035, 4.0) * bright
    if weight is not None:
        keep = rng.random(n) < weight(us, vs)
        us, vs, b = us[keep], vs[keep], b[keep]
        n = len(us)
    tk = rng.beta(2.2, 2.0, n)
    temps = temp[0] + (temp[1] - temp[0]) * tk
    tints = np.stack([kelvin(t) for t in np.linspace(temp[0], temp[1], 8)])
    ti = np.clip(((temps - temp[0]) / max(1, temp[1] - temp[0]) * 7.99).astype(int), 0, 7)
    x = (us * fr.H + fr.W / 2 - 0.5)
    y = (vs * fr.H - 0.5)
    vis = (x > 1) & (x < fr.W - 2) & (y > 1) & (y < fr.H - 2)
    x, y, b, ti = x[vis], y[vis], b[vis], ti[vis]
    out = np.zeros((fr.H, fr.W, 3), F32) if layer is None else layer
    npx = fr.H * fr.W
    acc = np.zeros((3, npx), F32)
    x0 = x.astype(int)
    y0 = y.astype(int)
    fx = x - x0
    fy = y - y0
    for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                      (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        idx = (y0 + dy) * fr.W + (x0 + dx)
        for c in range(3):
            acc[c] += np.bincount(idx, weights=b * w * tints[ti, c], minlength=npx).astype(F32)
    acc = np.moveaxis(acc.reshape(3, fr.H, fr.W), 0, -1)
    sg = max(0.55, size * fr.k)
    # A Gaussian splat keeps the integral: scale so a star's peak is ~ b.
    out += blur(acc, sg) * (2 * math.pi * sg * sg) ** 0.5 * 0.9
    # The brightest few get a soft halo, as a lens gives them.
    out += blur(acc * (acc > 0.6), 3.0 * fr.k + 1) * 0.6
    return out


def zoom_blur(img, cx, cy, strength=0.25, n=24):
    """Radial (zoom) blur of a 2-D or 3-D layer about pixel (cx, cy): the
    average of n copies scaled about it by 1..1-strength. Turns a glow into
    god rays."""
    H, W = img.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(F32)
    acc = np.zeros_like(img, F32)
    for i in range(n):
        s = 1 - strength * i / (n - 1)
        acc += sample(img, cx + (xx - cx) * s, cy + (yy - cy) * s)
    return acc / n


# -- the heightfield renderer -----------------------------------------------------------
class Terrain:
    """A small heightfield renderer for the landscapes ("voxel space", done
    per column and vectorised). The camera sits at height cam_h looking
    level along +z with focal length f (in v units per world unit at
    distance 1); the horizon is at v = hv. A world point (x, h, z) lands at
    u = x f / z, v = hv - (h - cam_h) f / z -- so the picture is laid out in
    u, v like everything else here, and the ultrawide simply sees more of
    the world at the sides.

    The height function hfun(x, z) is sampled on nz geometric distance
    steps x every column. Front to back, a running minimum of the projected
    tops tells, for each pixel row, which step first covers it (one
    searchsorted for the whole frame). Light (normals, sun, cast shadows)
    is computed once on the step grid and gathered per pixel, interpolated
    in depth between the two steps the view ray passes (gather_smooth());
    the surface itself -- rock, snow, trees, texture -- is decided per pixel
    from the world point the pixel sees (zpix(), xpix(), ray_height()), so
    sheer faces and snow lines stay crisp. shade() composites over the sky
    in bands of rows, with vertical subsamples to antialias the ridges."""

    def __init__(self, fr, hfun, cam_h, hv, f, z_near, z_far, nz=None, cam_x=0.0):
        self.fr = fr
        H, W = fr.H, fr.W
        nz = nz or int(1400 + 400 * fr.k)
        self.hv, self.f, self.cam_h = hv, f, cam_h
        zs = (z_near * (z_far / z_near) ** (np.arange(nz, dtype=np.float64) / (nz - 1))).astype(F32)
        self.zs = zs
        self.u = fr.u[0]
        self.cam_x = cam_x
        self.r0 = 0                      # first row of the band shade() is on
        # The heights, a slab of steps at a time: the noise behind hfun makes
        # a dozen temporaries the size of its input, and a whole grid at once
        # would cost a gigabyte on the ultrawide.
        h = np.empty((nz, W), F32)
        for i in range(0, nz, 192):
            X = cam_x + self.u[None, :] * zs[i:i + 192, None] / f
            h[i:i + 192] = hfun(X, np.broadcast_to(zs[i:i + 192, None], X.shape))
        self.h = h
        top = (hv - (h - cam_h) * f / zs[:, None]) * H
        np.clip(top, -2 * H, 3 * H, out=top)
        M = np.minimum.accumulate(top, axis=0)
        self.top = top
        self.nz = nz
        # Normals from the step grid: d/dx across columns (world step z/(fH)),
        # d/dz along steps.
        dhdx = np.gradient(h, axis=1) / (zs / (f * H))[:, None]
        dhdz = np.gradient(h, axis=0) / np.gradient(zs)[:, None]
        n = np.stack([-dhdx, np.ones_like(h), -dhdz], -1)
        del dhdx, dhdz
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        self.normal = n
        # The searchsorted over the whole frame: columns laid end to end,
        # each offset by BIG so the flattened -M is ascending.
        big = 8.0 * H
        key = (-M.T.astype(np.float64) + (np.arange(W, dtype=np.float64) * big)[:, None]).ravel()
        self._key, self._big = key, big
        del M

    def index(self, dy=0.0):
        """For each pixel (row centre + dy), the step that covers it (nz = sky)."""
        H, W = self.fr.H, self.fr.W
        y = (np.arange(H, dtype=np.float64) + 0.5 + dy)[:, None]
        q = (-y + (np.arange(W, dtype=np.float64) * self._big)[None, :])
        idx = np.searchsorted(self._key, q.ravel(), side="left").reshape(H, W)
        idx -= (np.arange(W) * self.nz)[None, :]
        return np.clip(idx, 0, self.nz).astype(np.int32)

    def gather_smooth(self, grid, idx, dy=0.0):
        """Like gather(), but interpolated in depth: a pixel first covered
        by step i has its view ray pass above the ground at step i - 1 and
        below it at step i, so it meets the ground between them -- at the
        fraction where the two signed gaps (projected top minus the row)
        cross zero. Mixing the two steps by that fraction turns the flat
        blocks (and terraces) of plain voxel rendering into smooth faces."""
        H, W = idx.shape
        cols = np.broadcast_to(np.arange(W)[None, :], (H, W))
        i = np.minimum(idx, self.nz - 1)
        j = np.maximum(i - 1, 0)
        y = (np.arange(H, dtype=F32) + 0.5 + dy + self.r0)[:, None]
        d1 = self.top[i, cols] - y          # <= 0: the ground is above the ray at i
        d0 = self.top[j, cols] - y          # > 0: below it at i - 1
        t = np.clip(d0 / np.maximum(d0 - d1, 1e-4), 0, 1)   # 0 at i - 1, 1 at i
        t = np.where(i == j, 1, 1 - t)                      # weight of step i - 1
        gi, gj = grid[i, cols], grid[j, cols]
        if grid.ndim == 3:
            t = t[..., None]
        return gi + (gj - gi) * t

    def shadows(self, hfun, sun, dist, k=20, sub=4, soft=0.08):
        """Cast shadows on the step grid: from every (sub-sampled) step,
        march k times towards the sun over `dist` world units and see if the
        terrain rises above the ray; the closest call, over a penumbra that
        widens with distance, gives a soft visibility 0..1, upsampled to the
        full grid. Costs about k / sub^2 height evaluations of the grid."""
        s = np.asarray(sun, np.float64)
        s = s / np.linalg.norm(s)
        hlen = math.hypot(s[0], s[2])
        dx, dz, slope = s[0] / hlen, s[2] / hlen, s[1] / hlen
        zs = self.zs[::sub][:, None]
        X = self.cam_x + self.u[None, ::sub] * zs / self.f
        h0 = self.h[::sub, ::sub]
        occ = np.full(h0.shape, -1.0, F32)
        for i in range(1, k + 1):
            t = dist * (i / k) ** 1.6
            hh = hfun(X + dx * t, np.broadcast_to(zs + dz * t, X.shape))
            occ = np.maximum(occ, (hh - (h0 + slope * t)) / (soft * (1 + t)))
        vis = 1 - smoothstep(-0.2, 1.0, occ)
        return np.clip(_resize(vis.astype(F32), self.fr.W, self.nz), 0, 1)

    @property
    def X(self):
        """World x of every step and column (computed on demand: cheap)."""
        return self.cam_x + self.u[None, :] * self.zs[:, None] / self.f

    def ray_height(self, idx, dy=0.0, z=None):
        """World height of the view ray where it meets the surface (the
        smoothed distance): on a cliff face, the height of the rock this
        pixel shows; anywhere, the true height of what the pixel sees."""
        if z is None:
            z = self.zpix(idx, dy)
        v = self.vblock(idx) + F32(dy / self.fr.H)
        return self.cam_h + (self.hv - v) * z / self.f

    def vblock(self, idx):
        """v of the rows of the block being shaded (see shade())."""
        return self.fr.v[self.r0:self.r0 + idx.shape[0]]

    def zpix(self, idx, dy=0.0):
        """Per-pixel distance, smoothed between steps."""
        return self.gather_smooth(np.broadcast_to(self.zs[:, None], (self.nz, self.fr.W)), idx, dy)

    def xpix(self, z):
        """Per-pixel world x from a per-pixel distance."""
        return self.cam_x + self.fr.u * z / self.f

    def shade(self, surface, sky, samples=2):
        """Composite with per-pixel shading: surface(idx, dy) returns the
        land colour (H, W, 3) for one vertical subsample; sky behind.
        Returns (image, coverage)."""
        acc = np.zeros_like(sky)
        cov = np.zeros(sky.shape[:2], F32)
        H = self.fr.H
        step = max(64, int(1.6e6 // self.fr.W))
        for i in range(samples):
            dy = (i + 0.5) / samples - 0.5
            idx = self.index(dy)
            # In bands of rows: surface() makes a dozen frame-sized
            # temporaries, which at 3440 x 1440 would cost a gigabyte.
            for r0 in range(0, H, step):
                r1 = min(H, r0 + step)
                self.r0 = r0
                ib = idx[r0:r1]
                land = ib < self.nz
                if land.any():
                    acc[r0:r1] += np.where(land[..., None], surface(ib, dy), sky[r0:r1])
                else:
                    acc[r0:r1] += sky[r0:r1]
                cov[r0:r1] += land
            self.r0 = 0
        return acc / samples, cov / samples



def fog(colour, z, haze, density, height=None, falloff=None):
    """Aerial perspective: colour (.., 3) towards `haze` by 1 - exp(-z density),
    thinner with height when height/falloff are given."""
    d = density * z
    if height is not None:
        d = d * np.exp(-np.maximum(height, 0) / falloff)
    t = 1 - np.exp(-d)
    return mix(colour, haze, t)


def sky_dome(fr, hv, zenith, horizon, sun=None, sun_col=None, sun_size=0.04, glow=0.25,
             power=0.55, below=None):
    """A sky: zenith colour high up, the horizon colour at v = hv (the
    gradient runs in sRGB with `power` < 1 keeping the zenith deep for
    longer), plus a sun (or moon) at (u, v) with a tight disc glow and a
    broad Mie-like halo, in linear light."""
    t = np.clip(1 - (hv - fr.v) / max(hv, 1e-3), 0, 1) ** (1 / power)
    sky = ramp(t[:, 0], [(0.0, zenith), (1.0, horizon)])[:, None, :]
    sky = np.ascontiguousarray(np.broadcast_to(sky, (fr.H, fr.W, 3)))
    if below is not None:
        sky[fr.v[:, 0] > hv] = col(below)
    if sun is not None:
        d = np.sqrt((fr.u - sun[0]) ** 2 + (fr.v - sun[1]) ** 2)
        sc = col(sun_col)
        sky = add(sky, sc, glow * np.exp(-d / 0.18) + 0.5 * glow * np.exp(-d / 0.05))
        if sun_size > 0:
            sky = add(sky, sc, 3.0 * smoothstep(sun_size * 1.05, sun_size * 0.95, d))
    return sky


def cloud_deck(fr, nz, hv, f, alt, scale, cover, lit, dark, sun_u=0.0, drift=(0.0, 0.0),
               soft=0.14, stretch=1.8, alpha=0.9, octaves=6):
    """Clouds on a flat deck at height alt over the camera, in perspective:
    a sky pixel above the horizon looks at deck point z = alt f / (hv - v),
    x = u z / f, and a domain-warped fbm there decides the cloud -- so they
    shrink and crowd towards the horizon as a real deck does. Lit by the
    density gradient towards the sun (thin sunward edges bright, thick
    bellies grey). Returns (colour, alpha); computed in bands of rows, only
    above the horizon."""
    H, W = fr.H, fr.W
    c_out = np.zeros((H, W, 3), F32)
    a_out = np.zeros((H, W), F32)
    last = int(min(H, math.ceil(hv * H)))
    step = max(32, int(1.0e6 // W))
    sx = -0.12 if sun_u < 0 else 0.12
    for r0 in range(0, last, step):
        r1 = min(last, r0 + step)
        v = fr.v[r0:r1]
        dv = np.maximum(hv - v, 1e-3)
        z = alt * f / dv
        x = fr.u * z / f
        px = (x + drift[0]) / scale
        pz = np.broadcast_to((z + drift[1]) / (scale * stretch), px.shape)
        wx = nz.fbm(px * 0.5 + 11, pz * 0.5, 3) * 0.6
        wz = nz.fbm(px * 0.5, pz * 0.5 + 23, 3) * 0.6
        n = nz.fbm(px + wx, pz + wz, octaves) * 0.5 + 0.5
        n2 = nz.fbm(px + wx + sx, pz + wz + 0.05, octaves) * 0.5 + 0.5
        dens = smoothstep(cover, cover + soft, n)
        fade = smoothstep(0.0, 0.06, hv - v) * np.exp(-z / (alt * 60))
        a_out[r0:r1] = dens * fade * alpha
        thick = smoothstep(cover, cover + 0.35, n)
        shade = np.clip(0.75 + 4.0 * (n - n2) - 0.35 * thick, 0, 1)
        c_out[r0:r1] = mix(np.broadcast_to(col(dark), shade.shape + (3,)), col(lit), shade)
    return c_out, a_out


def calm_top(img):
    """The top QUIET px blended into a heavily blurred copy, the detail
    fading back in over FADE px below: the bar and the notch sit on calm
    colour, whatever the picture does under them."""
    H = img.shape[0]
    n = min(H, QUIET + FADE + 160)
    soft = blur(img[:n], 40, 18)
    y = np.arange(n, dtype=F32)[:, None]
    w = 1 - smoothstep(QUIET, QUIET + FADE, y)
    out = img.copy()
    out[:n] = mix(img[:n], soft, w * 0.92)
    return out


def cap_fields(img):
    """FIELD_LUM: dim any LARGE bright area (the luminance of a copy blurred
    over ~6 % of the height) down to the ceiling, smoothly, so a pale sky or
    a light abstract is held as a field while small highlights keep their
    contrast to it."""
    H = img.shape[0]
    L = blur(lum(img), 0.06 * H)
    f = np.minimum(1.0, FIELD_LUM / np.maximum(L, 1e-6))
    f = blur(f, 0.03 * H)
    return img * f[..., None]


def finish(img, seed):
    """Fields capped, the vignette, sRGB encoding, a luminance-only grain,
    the PEAK cap (scaled whole, never clipped per channel), a triangular
    +-0.5 LSB dither, then 8 bit, clipped once more to PEAK."""
    H, W = img.shape[:2]
    img = calm_top(cap_fields(np.nan_to_num(img.astype(F32), nan=0.0, posinf=4.0)))
    yy = ((np.arange(H, dtype=F32) - H / 2) / (H / 2))[:, None]
    xx = ((np.arange(W, dtype=F32) - W / 2) / (W / 2))[None, :]
    img *= (1 - VIGNETTE * (xx * xx + yy * yy) / 2)[..., None]
    s = lin_to_srgb(img)
    del img
    rng = np.random.default_rng(zlib.crc32(seed.encode()))
    s += (rng.normal(0, GRAIN / 255, (H, W, 1))).astype(F32)
    np.clip(s, 0.0, None, out=s)
    peak = s.max(axis=-1, keepdims=True)
    s /= np.maximum(peak / PEAK, 1.0)
    s *= 255.0
    s += (rng.random((H, W, 3), F32) - rng.random((H, W, 3), F32)) * 0.5
    top = math.floor(PEAK * 255 + 1e-6)
    return Image.fromarray(np.clip(np.rint(s), 0, top).astype(np.uint8), "RGB")


# == the variants ==================================================================
# Each scene(fr) returns a LINEAR (H, W, 3) float32 canvas; render() finishes it.

def azure_swoosh(fr):
    """01: the first glossy-blue era. Sapphire, and one broad luminous fold
    of azure light along y = 0.55 + 0.18 sin(2.1 u + 0.6) -- a Gaussian
    cross-section with a satin specular band on its upper edge and a soft
    shadow under it -- a fainter echo below, a cloth-like shimmer."""
    nz = fr.noise
    c = fr.vgrad([(0.0, "#071f4c"), (0.45, "#0d3a86"), (1.0, "#1f6fd0")])
    u, v = fr.u, fr.v
    # A broad bloom behind the ribbon's middle: the light seems to come from it.
    c = add(c, col("#2f86e8"), 0.35 * np.exp(-((u - 0.05) ** 2 / 0.5 + (v - 0.58) ** 2 / 0.06)))
    shimmer = 1 + 0.03 * nz.fbm(u * 2.2, v * 5.0, 4)
    for off, gain in ((0.16, 0.40), (0.0, 1.0)):
        yc = 0.55 + off + 0.18 * np.sin(2.1 * u + 0.6 - off * 1.5)
        slope = 0.18 * 2.1 * np.cos(2.1 * u + 0.6 - off * 1.5)
        d = (v - yc) / np.sqrt(1 + slope ** 2)
        sg = 0.09 * (0.85 + 0.25 * np.sin(1.3 * u + 1.0))
        body = np.exp(-(d / sg) ** 2)
        # Across the fold the light runs from pale aqua on the lit upper half
        # to a saturated azure underneath: a ribbon, not a stripe.
        across = ramp(np.clip(0.5 + d / (2.2 * sg), 0, 1), [(0.0, "#a8dcff"), (0.45, "#4aa8ff"), (1.0, "#1f6fff")])
        # The satin band: narrow, on the upper edge, breathing along u.
        spec = np.exp(-((d + 0.55 * sg) / (0.16 * sg)) ** 2) * (0.6 + 0.4 * np.sin(2.7 * u + 2.0))
        # A second, finer sheen line on the lower lip of the fold.
        lip = np.exp(-((d - 0.62 * sg) / (0.07 * sg)) ** 2) * 0.35
        shade = np.exp(-((d - 1.25 * sg) / (0.5 * sg)) ** 2)
        c = c * (1 - 0.30 * gain * shade)[..., None]
        c = add(c, across, gain * 0.55 * body * shimmer)
        c = add(c, col("#eaf6ff"), gain * (0.30 * spec + 0.12 * lip) * shimmer)
    # Cloth: a long low-frequency fold pattern over the whole field.
    c *= (1 + 0.03 * nz.fbm(u * 1.2 + 3, v * 7.0, 3))[..., None]
    return c


def azure_streaks(fr):
    """02: light streaks. Cobalt brightening towards a focus beyond the lower
    left corner; sixty fine filaments fan out of it as quadratic curves
    (0.6-2 px across, fading along their length), added as light, then a
    two-radius bloom of the streak layer."""
    rng = fr.rng
    u, v = fr.u, fr.v
    fu, fv = -fr.half - 0.18, 1.12
    if fr.half < 0.6:                      # portrait / narrow: the fan's source stays in reach
        fu = -fr.half - 0.10
    r = np.sqrt((u - fu) ** 2 + (v - fv) ** 2)
    c = ramp(np.clip(r / 2.0, 0, 1), [(0.0, "#2a6fe0"), (0.35, "#1446a8"), (0.75, "#0a2a72"), (1.0, "#06194a")])
    layer = np.zeros((fr.H, fr.W), F32)
    uu = fr.u[0]
    for _ in range(60):
        ang = math.radians(rng.uniform(8, 52))
        bend = rng.uniform(-0.35, 0.10)
        du = np.maximum(uu - fu, 0)
        vc = fv - math.tan(ang) * du - bend * du ** 2
        L = rng.uniform(0.9, 2.6)
        inten = (np.exp(-du / L) * smoothstep(0.0, 0.25, du) * rng.uniform(0.25, 1.0) ** 2).astype(F32)
        sig = np.full(fr.W, max(rng.uniform(0.6, 2.0) / 1440, 0.55 / fr.H), F32)
        ystroke(fr, layer, vc.astype(F32), sig, inten * 1.6)
    glow = layer + 0.35 * blur(layer, 18 * fr.k + 1) * 6 + 0.25 * blur(layer, 70 * fr.k + 1) * 14
    c = add(c, col("#bfe8ff"), glow * 0.9)
    c = add(c, col("#ffffff"), np.clip(layer - 0.8, 0, None) * 0.6)
    return c


def blue_ribbons(fr):
    """03: brushed blue ribbons. Cobalt with a brushed-metal grain (Perlin
    stretched 400:1 along x), and three translucent bands that twist (their
    width runs through |cos|), each with a dark core, Fresnel-bright edges,
    a satin highlight and a soft drop shadow on what lies under it."""
    nz = fr.noise
    u, v = fr.u, fr.v
    c = fr.vgrad([(0.0, "#08214f"), (0.5, "#11408f"), (1.0, "#0b2c6a")])
    c = add(c, col("#2a64c4"), 0.25 * np.exp(-((u + 0.1) ** 2 / 0.8 + (v - 0.6) ** 2 / 0.12)))
    brushed = nz.fbm(u * 0.9, v * 360.0, 3) * 0.6 + nz.fbm(u * 3.0 + 9, v * 900.0, 2) * 0.4
    c *= (1 + 0.04 * brushed)[..., None]
    specs = [(0.66, 0.10, 1.6, 0.4, 0.060, "#3f8cff"),
             (0.52, 0.12, 1.25, 2.1, 0.050, "#59a8ff"),
             (0.40, 0.09, 2.0, 4.0, 0.040, "#7cc0ff")]
    for base, amp, fq, ph, th, hue in specs:
        yc = base + amp * np.sin(fq * u + ph) + 0.03 * np.sin(3.1 * u + ph * 2)
        slope = amp * fq * np.cos(fq * u + ph) + 0.03 * 3.1 * np.cos(3.1 * u + ph * 2)
        d = (v - yc) / np.sqrt(1 + slope ** 2)
        twist = np.cos(0.9 * fq * u + ph * 1.7)
        t = th * (0.18 + 0.82 * np.abs(twist) ** 0.8)
        inside = fr.aa(t - np.abs(d))
        s = np.clip(np.abs(d) / t, 0, 1)
        # The drop shadow first: the band's mask, pushed down and blurred.
        sh = blur(inside, 22 * fr.k + 1)
        shift = int(26 * fr.k) + 1
        sh = np.concatenate([np.zeros((shift, fr.W), F32), sh[:-shift]], 0)
        c *= (1 - 0.38 * sh)[..., None]
        core = 0.45 + 0.55 * s ** 3
        edge = s ** 10
        hl = np.exp(-((d / t + 0.45 * np.sign(twist)) / 0.12) ** 2)
        band = col(hue) * core[..., None] * 0.9
        band = add(band, col("#e8f4ff"), 0.55 * edge + 0.45 * hl)
        c = mix(c, band, inside * 0.62)
        c = add(c, col("#cfe6ff"), inside * edge * 0.25)
    return c


def light_rays(fr):
    """04: swirling light. A polar spiral centred near (0.15, 0.47): three
    Archimedean arms r = a + b(theta + 2 pi n + phase), each drawn as a
    bundle of fine filaments (the distance to the nearest wrap, a Gaussian
    that widens outwards), a white-to-azure core flare, god-ray streaks (a
    zoom blur of the glow about the centre), sparkle and a faint lens bloom,
    on deep navy."""
    rng, nz = fr.rng, fr.noise
    cu = fr.centre_u(0.15, 0.25)
    cv = 0.50
    u, v = fr.u, fr.v
    c = fr.vgrad([(0.0, "#020719"), (0.55, "#04113a"), (1.0, "#061848")])
    dx = u - cu
    dy = (v - cv) * 1.45                   # squashed: the swirl is seen at an angle
    r = np.sqrt(dx * dx + dy * dy)
    th = np.arctan2(dy, dx)
    wob = 0.018 * nz.fbm(np.cos(th) * 2 + r * 3, np.sin(th) * 2, 3)
    glow = np.zeros_like(r)
    fil = np.zeros_like(r)
    a, b = 0.02, 0.15
    fade = np.exp(-r / 0.32) * smoothstep(0.0, 0.08, r) * smoothstep(1.1, 0.5, r)
    for j in range(3):
        for o, wf, gi in ((0.0, 1.0, 1.0), (-0.22, 0.45, 0.55), (0.18, 0.4, 0.5), (0.42, 0.3, 0.3), (-0.5, 0.3, 0.25)):
            ph = 2 * math.pi * j / 3 + 0.4 + o
            s = (r + wob - a) / b - th - ph
            n = np.round(s / (2 * math.pi))
            dist = np.abs(s - 2 * math.pi * n) * b
            w = (0.004 + 0.035 * r) * wf
            glow += np.exp(-(dist / (w * 3)) ** 2) * fade * gi * 0.5
            fil += np.exp(-(dist / w) ** 2) * fade * gi
    core = np.exp(-(r / 0.035) ** 2) * 2.2 + np.exp(-r / 0.08) * 0.5
    light = (glow + fil + core).astype(F32)
    cx_px = cu * fr.H + fr.W / 2
    cy_px = cv * fr.H
    rays = zoom_blur(light, cx_px, cy_px, 0.5, 32)
    beams = smoothstep(-0.2, 0.8, nz.fbm(th * 4.0, 1.0, 2))
    c = add(c, col("#1f6cff"), glow * 0.8 + rays * 0.9 * beams)
    c = add(c, col("#8cc4ff"), fil * 0.55)
    c = add(c, col("#eaf4ff"), core * 0.8 + fil ** 2 * 0.15)
    # Sparkle: small points scattered along the arms.
    sp = np.zeros((fr.H, fr.W), F32)
    n = 1400
    rr = rng.uniform(0.03, 0.8, n) ** 1.3
    arm = rng.integers(0, 3, n)
    tt = (rr - a) / b - (2 * math.pi * arm / 3 + 0.4) + rng.normal(0, 0.15, n)
    px = cu + rr * np.cos(tt)
    py = cv + rr * np.sin(tt) / 1.45
    xi = (px * fr.H + fr.W / 2).astype(int)
    yi = (py * fr.H).astype(int)
    ok = (xi >= 0) & (xi < fr.W) & (yi >= 0) & (yi < fr.H)
    np.add.at(sp, (yi[ok], xi[ok]), (rng.pareto(2.2, ok.sum()) * 0.6 * np.exp(-rr[ok] / 0.5)).astype(F32))
    sp = blur(sp, max(0.6, 0.8 * fr.k)) * 5
    c = add(c, col("#e6f2ff"), sp + blur(sp, 5 * fr.k + 1) * 0.6)
    c = add(c, col("#1a4fc8"), 0.35 * blur(glow, 80 * fr.k + 1))
    return c


def aurora(fr, curtains, sky, snow=False):
    """The aurora scenes (05, 06): a sky gradient, a starfield, two folded
    curtains (curtain()), bloom, a faint glow low in the sky."""
    nz = fr.noise
    u, v = fr.u, fr.v
    c = fr.vgrad(sky)
    light = np.zeros_like(c)
    for spec in curtains:
        light += curtain(fr, *spec)
    light = light + blur(light, 16 * fr.k + 1) * 0.45 + blur(light, 80 * fr.k + 1) * 0.40
    # The stars dim where the aurora is bright (the eye adapts), not added over it.
    stars = starfield(fr, 4200, 0.0, 1.0, bright=0.8, temp=(5000, 10000))
    c += stars * np.exp(-lum(light) * 6)[..., None] + light
    c = add(c, col(sky[-1][1]), 0.20 * smoothstep(0.7, 1.0, v) * np.ones_like(u))
    if snow:
        glitter = starfield(fr, 7000, 0.05, 1.0, temp=(8000, 12000), bright=0.45, size=0.55, seed_shift=7)
        c += glitter * (0.3 + 0.7 * smoothstep(0.5, 1.0, v))[..., None]
        fogn = nz.fbm(u * 2.2, v * 8.0 + 40, 5) * 0.5 + 0.5
        band = smoothstep(0.74, 1.02, v) * (0.5 + 0.5 * fogn)
        c = mix(c, col("#5a6496"), band * 0.6)
        c = add(c, col("#b8c4f0"), band * 0.04)
    return c


def aurora_space(fr):
    """05: aurora over space -- indigo to black; two curtains, teal at the
    foot rising through blue into violet and pink."""
    curtains = [
        # base, amp, fold, decays (green, blue, pink), hues, gain, phase
        (0.64, 0.10, 0.85, (0.035, 0.09, 0.19), ("#22e6b0", "#4a5cff", "#e04fc8"), 1.0, 0.0),
        (0.54, 0.08, 0.7, (0.025, 0.06, 0.14), ("#30d0d8", "#6a50ff", "#ff5fb0"), 0.55, 3.3),
    ]
    return aurora(fr, curtains, [(0.0, "#020108"), (0.45, "#080626"), (0.8, "#140d3c"), (1.0, "#1d1248")])


def aurora_snow(fr):
    """06: the snowy aurora -- cooler curtains (ice blue into lilac and
    pink), snow glitter and a frosted fog band."""
    curtains = [
        (0.62, 0.10, 0.85, (0.035, 0.09, 0.18), ("#7fe6ff", "#7a8cff", "#d890e8"), 0.95, 1.7),
        (0.52, 0.08, 0.7, (0.025, 0.06, 0.13), ("#a8f0ff", "#8aa0ff", "#c898ff"), 0.5, 5.2),
    ]
    return aurora(fr, curtains, [(0.0, "#02040c"), (0.45, "#081030"), (0.8, "#141c48"), (1.0, "#222a5a")],
                  snow=True)


def spiral_galaxy(fr):
    """07: the big spiral galaxy. A disc inclined 62 deg (y / cos i), two
    logarithmic arms of pitch 14 deg (phase theta - ln r / tan p, wobbled by
    fbm so they fray and branch), clumped by fbm into star clouds; a warm
    bulge; filamentary dust lanes on the inner edge of the arms (and across
    the near side of the bulge); blue arm stars, pink knots; a deep
    starfield behind."""
    nz = fr.noise
    u, v = fr.u, fr.v
    c = fr.vgrad([(0.0, "#010206"), (1.0, "#02040b")])
    c += starfield(fr, 4500, 0.0, 1.0, bright=0.55, temp=(4800, 10000))
    gu = fr.centre_u(0.36, 0.62) if fr.half > 0.6 else 0.0
    gv = 0.55
    R = 0.52
    pa = math.radians(-24)
    ci = math.cos(math.radians(62))
    dx, dy = u - gu, v - gv
    xr = dx * math.cos(pa) + dy * math.sin(pa)
    yr = (-dx * math.sin(pa) + dy * math.cos(pa)) / ci
    r = np.sqrt(xr * xr + yr * yr) / R
    th = np.arctan2(yr, xr)
    pitch = math.tan(math.radians(14))
    phi = th - np.log(np.maximum(r, 0.03)) / pitch + 0.9 * nz.fbm(xr * 3.5, yr * 3.5, 4) * smoothstep(0.1, 0.5, r)
    arm = ((1 + np.cos(2 * phi)) / 2) ** 2.2
    clump = np.clip(nz.fbm(xr * 16, yr * 16, 5) * 0.5 + 0.5, 0, 1)
    disk = np.exp(-r / 0.42) * smoothstep(1.35, 0.6, r)
    arms = disk * (0.12 + 0.88 * arm * (0.25 + 1.3 * clump ** 1.6)) * smoothstep(0.04, 0.2, r) * 0.8
    lanes = nz.ridged(xr * 9 + 3, yr * 9, 5, sharp=4.0)
    inner = ((1 + np.cos(2 * (phi + 0.65))) / 2) ** 4
    dust = (inner * (0.3 + 1.6 * lanes ** 1.5) * smoothstep(0.08, 0.25, r) * smoothstep(1.1, 0.35, r)) * 0.9
    nearside = smoothstep(0.0, 0.03, -(-dx * math.sin(pa) + dy * math.cos(pa)))
    bulge = np.exp(-(r / 0.06) ** 0.9) * 1.0 + np.exp(-(r / 0.012) ** 2) * 1.2
    g = add(np.zeros_like(c), col("#8fb4ff"), arms * 1.0)
    g = add(g, col("#ffd9a8"), bulge + disk * 0.18)
    g *= np.exp(-dust * (1 + 0.8 * nearside))[..., None]
    knots = smoothstep(0.80, 0.95, np.clip(nz.fbm(xr * 40 + 5, yr * 40, 3) * 0.5 + 0.5, 0, 1)) * arm * disk
    g = add(g, col("#ff4f98"), knots * 2.2)
    g += blur(g, 25 * fr.k + 1) * 0.3 + blur(g, 90 * fr.k + 1) * 0.25
    c += g

    def weight(us, vs):
        ddx, ddy = us - gu, vs - gv
        x2 = ddx * math.cos(pa) + ddy * math.sin(pa)
        y2 = (-ddx * math.sin(pa) + ddy * math.cos(pa)) / ci
        rr = np.sqrt(x2 * x2 + y2 * y2) / R
        ph = np.arctan2(y2, x2) - np.log(np.maximum(rr, 0.03)) / pitch
        return np.clip(((1 + np.cos(2 * ph)) / 2) ** 2 * np.exp(-rr / 0.35) * 1.4, 0, 1)
    c += starfield(fr, 26000, 0.0, 1.0, weight=weight, temp=(9000, 15000), bright=0.45, size=0.55, seed_shift=3)
    return c


def galaxy_nebula(fr):
    """08: the starfield galaxy. A milky-way band across the frame at -28
    deg: a Gaussian across it, fbm clouds along it, dark rifts (a ridged
    noise near the centre line), a warm core towards one end, blue edges;
    star density follows the band; a few bright stars with faint four-point
    diffraction spikes."""
    nz, rng = fr.noise, fr.rng
    u, v = fr.u, fr.v
    c = fr.vgrad([(0.0, "#010208"), (1.0, "#040612")])
    ang = math.radians(-28)
    du, dv = u - 0.0, v - 0.56
    along = du * math.cos(ang) + dv * math.sin(ang)
    across = -du * math.sin(ang) + dv * math.cos(ang)
    across = across + 0.05 * nz.fbm(along * 1.5, 3.0, 3)
    band = np.exp(-(across / 0.17) ** 2)
    clouds = nz.fbm(along * 3.0, across * 6.0, 6) * 0.5 + 0.5
    fine = nz.fbm(along * 12.0 + 4, across * 16.0, 4) * 0.5 + 0.5
    rift = nz.ridged(along * 2.2 + 8, across * 4.5, 5, sharp=3.0)
    rift *= np.exp(-(across / 0.08) ** 2) * smoothstep(0.35, 0.75, clouds)
    core = np.exp(-((along - 0.30) / 0.35) ** 2)
    glow = band * (0.25 + 0.95 * clouds ** 1.5) * (0.7 + 0.5 * fine)
    neb = add(np.zeros_like(c), col("#7f9cff"), glow * 0.55 * (1 - 0.6 * core))
    neb = add(neb, col("#ffd2a0"), glow * core * 1.2)
    neb = add(neb, col("#ff7a8a"), band * core * smoothstep(0.7, 0.9, fine) * 0.4)
    neb *= np.exp(-2.6 * rift)[..., None]
    c += neb
    def weight(us, vs):
        x2 = -us * math.sin(ang) + (vs - 0.56) * math.cos(ang)
        return 0.15 + 0.85 * np.exp(-(x2 / 0.2) ** 2)
    c += starfield(fr, 52000, 0.0, 1.0, weight=weight, bright=0.55, size=0.6)
    # Bright stars with diffraction spikes.
    for _ in range(14):
        su = rng.uniform(-1.25, 1.25)
        sv = rng.uniform(0.12, 0.95)
        b = rng.uniform(0.6, 1.8)
        x0 = su * fr.H + fr.W / 2
        y0 = sv * fr.H
        L = int(70 * fr.k * b) + 6
        xa, xb = int(max(0, x0 - L)), int(min(fr.W, x0 + L + 1))
        ya, yb = int(max(0, y0 - L)), int(min(fr.H, y0 + L + 1))
        if xb <= xa or yb <= ya:
            continue
        lx = np.arange(xa, xb, dtype=F32)[None, :] - x0
        ly = np.arange(ya, yb, dtype=F32)[:, None] - y0
        sw = 0.7 * max(fr.k, 0.7)
        spike = (np.exp(-np.abs(lx) / (L * 0.25)) * np.exp(-(ly / sw) ** 2)
                 + np.exp(-np.abs(ly) / (L * 0.25)) * np.exp(-(lx / sw) ** 2)) * 0.35
        disc = np.exp(-(lx * lx + ly * ly) / (2 * (1.3 * fr.k + 0.6) ** 2)) * 2.5
        halo = np.exp(-np.sqrt(lx * lx + ly * ly) / (8 * fr.k + 2)) * 0.25
        tint = kelvin(rng.uniform(4500, 11000))
        c[ya:yb, xa:xb] += ((spike + disc + halo) * b)[..., None] * tint
    return c


def curtain(fr, base, amp, fold, decays, hues, gain, phase):
    """One aurora curtain as light (H, W, 3). The hem is a parametric curve
    (u(t), v(t)) that may fold back on itself (u(t) is not monotonic where
    `fold` is large: the S-bends of a sheet seen edge-on), splatted as a
    thin line whose brightness flickers along t (the rays); then every
    column is smeared UPWARDS by a one-sided exponential (a recursive
    filter, bottom to top), once per colour with its own length -- short
    for the green at the foot, longer for the blue, longest for the pink at
    the top -- so the colour climbs the rays the way it does in the sky."""
    nz = fr.noise
    H, W = fr.H, fr.W
    n = int(14 * H)
    t = np.linspace(-1.5, 1.5, n).astype(F32)
    one = np.full_like(t, phase)
    uc = t + fold * (0.09 * np.sin(t * 6.0 + phase) + 0.05 * np.sin(t * 13.0 + 2 * phase))
    vc = (base + 0.13 * np.sin(1.25 * t + phase) + amp * nz.fbm(t * 2.0 + phase * 3, one, 2)
          + 0.03 * np.sin(t * 3.1 + phase))
    patch = smoothstep(-0.25, 0.65, nz.fbm(t * 1.6 + phase, one + 9, 3)) ** 1.4
    rays = np.clip(nz.fbm(t * 150.0 + phase, one + 3, 3) * 0.5 + 0.5, 0, 1) ** 3.0
    # Where the sheet turns edge-on (du/dt near 0) the points pile up into a
    # bright fold; real folds are brighter, but only so much.
    dudt = np.abs(np.gradient(uc, t))
    b = (patch * (0.12 + 0.88 * rays) * gain * 1.3 * np.clip(dudt / 0.5, 0.35, 1.0)).astype(F32)
    x = uc * H + W / 2 - 0.5
    y = vc * H - 0.5
    ok = (x > 0) & (x < W - 1) & (y > 0) & (y < H - 1)
    x, y, b = x[ok], y[ok], b[ok]
    x0 = x.astype(int)
    y0 = y.astype(int)
    fx, fy = x - x0, y - y0
    # How tall the rays are in each column: the curtain's brightness there
    # (its ends taper -- shorter, dimmer rays -- instead of stopping on a cut).
    xi = np.clip(np.rint(x).astype(int), 0, W - 1)
    tall = np.bincount(xi, weights=patch[ok], minlength=W) / np.maximum(np.bincount(xi, minlength=W), 1)
    tall = blur(tall[None, :].astype(F32), 25 * fr.k + 1)[0]
    line = np.zeros(H * W, F32)
    for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        line += np.bincount((y0 + dy) * W + x0 + dx, weights=b * w, minlength=H * W).astype(F32)
    line = blur(line.reshape(H, W), max(0.7, 1.2 * fr.k), max(0.6, 0.8 * fr.k))
    # A soft foot under the hem: it glows into the dark rather than ending on a cut.
    foot = blur(line, 2 * fr.k + 0.5, 9 * fr.k + 1)
    out = np.zeros((H, W, 3), F32)
    for length, hue, g in zip(decays, hues, (1.0, 0.8, 0.55)):
        a = np.exp(-1.0 / (length * H * (0.35 + 0.65 * tall))).astype(F32)
        sm = np.empty_like(line)
        acc = np.zeros(W, F32)
        for row in range(H - 1, -1, -1):
            acc = line[row] + a * acc
            sm[row] = acc
        sm *= (1 - a)[None, :] * 22.0
        sm = blur(sm, 1.2 * fr.k + 0.4, 0.3)
        out += col(hue) * (sm * g)[..., None]
    # And a faint diffuse glow hanging BELOW the hem (top to bottom this
    # time): without it the dark under a bright hem reads as a hill.
    a = F32(math.exp(-1.0 / (0.03 * H)))
    down = np.empty_like(line)
    acc = np.zeros(W, F32)
    for row in range(H):
        acc = line[row] + a * acc
        down[row] = acc
    down = blur(down * F32(1 - a) * 22.0, 6 * fr.k + 1)
    out += col(hues[0], 1.4) * (line * 1.6 + foot * 2.5)[..., None]
    out += col(hues[1]) * (down * 0.35)[..., None]
    return out


def lambert(T, sun, sun_col, sky_col, ground_col, sky_amb=0.35, ground_amb=0.10, shadow=None):
    """Light per step: direct sun (Lambert, wrapped a little so the
    terminator is soft, times the cast-shadow visibility) plus a
    hemispheric ambient -- sky from above, bounce from below. sun = a
    direction (x, y, z), towards the light. One channel at a time: the
    step grid is large."""
    s = np.asarray(sun, F32)
    s = s / np.linalg.norm(s)
    n = T.normal
    ndl = n[..., 0] * s[0] + n[..., 1] * s[1] + n[..., 2] * s[2]
    ndl += 0.08
    ndl /= 1.08
    np.clip(ndl, 0, None, out=ndl)
    if shadow is not None:
        ndl *= shadow
    up = n[..., 1] * 0.5 + 0.5
    sc, kc, gc = col(sun_col), col(sky_col) * sky_amb, col(ground_col) * ground_amb
    out = np.empty(ndl.shape + (3,), F32)
    for c in range(3):
        out[..., c] = sc[c] * ndl + gc[c] + (kc[c] - gc[c]) * up
    return out


def snowy_peaks(fr):
    """12: the snowy range. A ridged-multifractal range (sharp crests,
    smooth valleys) ten to forty units out, behind darker foothills; lit by
    a low afternoon sun from the left with cast shadows. Light is computed
    per step and interpolated; the surface is decided per pixel from the
    true height the pixel sees -- snow where the ground is gentle and high
    (its line broken by noise), bare streaked rock on the steep faces, dark
    forest low down -- then two haze layers (one pooled in the valleys, one
    over distance), a deep blue sky with cloud wisps."""
    nz = fr.noise
    hv = 0.66
    f = 3.0
    cam_h = 1.8

    def hfun(x, z):
        far = smoothstep(8, 20, z)
        macro = np.clip(0.55 + 0.55 * nz.fbm(x / 16 + 3, z / 16, 3), 0.15, 1.1)
        rid = nz.ridged(x / 8.0, z / 8.0, 6, sharp=1.7)
        peaks = 3.4 * far * macro * rid
        hills = (0.9 * nz.fbm(x / 2.6 + 9, z / 2.6, 5) + 0.45) * (1 - 0.6 * far)
        # a broad massif a little right of centre, so the range has a summit
        massif = 2.0 * np.exp(-((x - 0.12 * z) / (0.30 * z + 2)) ** 2) * far * (0.4 + 0.6 * rid)
        return np.maximum(hills, 0.0) + peaks + massif

    T = Terrain(fr, hfun, cam_h, hv, f, 2.5, 160.0, nz=int(2000 + 600 * fr.k))
    sun = (-0.75, 0.30, -0.35)
    shade = T.shadows(hfun, sun, 14.0)
    light = lambert(T, sun, "#ffe2c0", "#8fb0e8", "#3a4250", sky_amb=0.42, shadow=shade)
    del shade
    ny = np.ascontiguousarray(T.normal[..., 1])
    sky = sky_dome(fr, hv, "#2a5596", "#c9d6e6", power=0.55)
    cc, ca = cloud_deck(fr, nz, hv, f, 7.0, 7.0, 0.60, "#f6f4f0", "#98a2b8", -0.5, alpha=0.75)
    sky = mix(sky, cc, ca)

    def surface(idx, dy):
        L = T.gather_smooth(light, idx, dy)
        n_y = T.gather_smooth(ny, idx, dy)
        z = T.zpix(idx, dy)
        x = T.xpix(z)
        rh = T.ray_height(idx, dy, z)
        # The snow line: high on the ridges, tongues reaching down the
        # gullies (noise in x alone makes vertical fingers), broken finely.
        snowline = (1.8 + 0.5 * nz.fbm(x / 3, z / 3, 3) + 0.55 * nz.fbm(x * 2.2, z * 0.3 + 7, 3)
                    + 0.2 * nz.fbm(x * 6, rh * 6 + 4, 2))
        snow = (smoothstep(0.53, 0.66, n_y + 0.05 * nz.fbm(x * 9, rh * 9, 3))
                * smoothstep(snowline - 0.06, snowline + 0.06, rh))
        streak = nz.fbm(x * 9.0, rh * 4.0, 3)
        # Bump (an emboss): the fine relief the step grid cannot hold --
        # fractured rock, wind crust, small gullies -- as the difference of
        # one texture and itself nudged towards the sun (up and to the left):
        # rising towards the light is lit, falling away is shaded.
        rel = lambda a, b: nz.fbm(a * 7.0 + 5, b * 5.0, 4) + 0.5 * nz.ridged(a * 14.0, b * 10.0, 3)
        bump = np.clip((rel(x, rh) - rel(x + 0.012, rh - 0.010)) * 6.0, -0.5, 0.5)
        rock = mix(np.broadcast_to(col("#615a52"), z.shape + (3,)), col("#383430"), smoothstep(-0.4, 0.5, streak))
        low = smoothstep(1.3, 0.5, rh)
        ground = mix(rock, col("#1f2c1c"), low * 0.9)
        c = mix(ground, col("#eef2f8"), snow) * L * (1.0 + bump * (0.9 - 0.7 * snow))[..., None]
        c = fog(c, z, col("#a9bfda"), 0.014)
        return fog(c, z, col("#9ab0cc"), 0.025, height=rh, falloff=0.45)
    img, _ = T.shade(surface, sky)
    return img


def mirror(fr, hfun, w, cam_h, hv, f, z_near, z_far, surface_of, sky, nz_steps=None, cam_x=0.0):
    """The reflection a calm water plane at height w shows: the scene seen
    from the camera mirrored through the plane (height 2w - cam_h), its
    rows above the horizon -- the pixel at row y on the water reflects row
    2 hv H - y of this image (sample it with reflect()). Ground under the
    water is dropped (-100), so the water itself reflects sky."""
    def hm(x, z):
        h = hfun(x, z)
        return np.where(h > w + 1e-3, h, -100.0)
    T = Terrain(fr, hm, 2 * w - cam_h, hv, f, z_near, z_far, nz=nz_steps or int(900 + 300 * fr.k), cam_x=cam_x)
    img, _ = T.shade(surface_of(T), sky, samples=1)
    return img


def reflect(fr, mimg, hv, rows, dx=0.0, dy=0.0):
    """Look up the mirror image for water pixels: rows is the row block's v
    (column vector), dx/dy pixel offsets (ripples)."""
    H, W = fr.H, fr.W
    y = (2 * hv - rows) * H - 0.5 + dy
    x = np.arange(W, dtype=F32)[None, :] + dx
    return sample(mimg, np.broadcast_to(x, np.broadcast(x, y).shape), np.broadcast_to(y, np.broadcast(x, y).shape))


def fresnel(v, hv, f, base=0.02):
    """Schlick reflectance of water for a pixel row below the horizon: the
    view ray dips atan((v - hv) / f) under the horizon."""
    s = np.sin(np.arctan(np.maximum(v - hv, 1e-4) / f))
    return base + (1 - base) * (1 - s) ** 5


def water_ripple(nz, x, z, scale, amp):
    """Pixel offsets (dx, dy) for the reflection from ripples on the water
    at world (x, z): the slope of a stretched fbm (waves are longer across
    the view than along it), in px, weaker far away where they are too
    small to see."""
    e = 0.02 * scale
    a = nz.fbm(x / scale, z / (scale * 0.4), 4)
    bx = nz.fbm((x + e) / scale, z / (scale * 0.4), 4)
    bz = nz.fbm(x / scale, (z + e) / (scale * 0.4), 4)
    damp = 1.0 / (1.0 + z / 12.0)
    return (bx - a) / 0.02 * amp * damp, (bz - a) / 0.02 * amp * damp * 1.6


def dune_field(nz):
    """The dune heightfield of 14 and 15: transverse dunes across a wind
    turned 0.35 rad from the view -- each a sawtooth of a long windward
    slope ((s / 0.72)^1.25) and a short steep lee face, its crest line
    wandering (fbm warp) and its height varying along it; small dunes on
    their backs; a slow swell; a far range on the horizon."""
    th = 0.35
    c, s = math.cos(th), math.sin(th)

    def profile(t):
        fr_ = t - np.floor(t)
        wind = (fr_ / 0.72) ** 1.25
        lee = np.clip(1 - (fr_ - 0.72) / 0.28, 0, 1) ** 0.8
        return np.where(fr_ < 0.72, wind, lee)

    def hfun(x, z):
        p = x * c + z * s
        q = -x * s + z * c
        p = p + 0.9 * nz.fbm(q / 7.0, p / 7.0, 3)
        big = profile(p / 3.2 + 0.25 * nz.fbm(q / 4.0 + 7, 0.3, 3))
        amp = 0.95 * (0.55 + 0.45 * nz.fbm(q / 9.0 + 3, p / 9.0, 3))
        small = profile(p / 0.85 + 0.3 * nz.fbm(q / 1.5, p / 1.5 + 9, 2)) * 0.07
        swell = 0.45 * nz.fbm(x / 18.0 + 5, z / 18.0, 3)
        far = smoothstep(50, 90, z) * (1.2 * nz.ridged(x / 14.0, z / 14.0, 4, sharp=1.4) + 0.3)
        return big * amp + small + swell + far
    return hfun, (c, s)


def dunes(fr, night):
    nz = fr.noise
    hv, f, cam_h = 0.42, 2.4, 1.05
    hfun, (c, s) = dune_field(nz)
    T = Terrain(fr, hfun, cam_h, hv, f, 1.2, 160.0)
    if night:
        sun, sun_col, skyc, gnd, amb = (-0.80, 0.30, -0.20), "#9cb4ff", "#30458a", "#141a2c", 0.22
        sky = sky_dome(fr, hv, "#040818", "#2a3f78", sun=(-1.6, 0.0), sun_col="#c8d4ff",
                       sun_size=0.0, glow=0.10, power=0.45)
        sky = add(sky, col("#4a5ea0"), 0.35 * np.exp(-np.maximum(hv - fr.v, 0) / 0.06))
        sky += starfield(fr, 6500, 0.0, hv, bright=0.75) * smoothstep(hv, hv - 0.15, fr.v)[..., None]
        sand, haze, dens = col("#b9a088", 0.42), col("#1c2a52"), 0.014
    else:
        sun, sun_col, skyc, gnd, amb = (0.85, 0.24, -0.25), "#ffd2a0", "#8eb2e8", "#a06a3a", 0.55
        sky = sky_dome(fr, hv, "#4878b8", "#ead2b0", sun=(1.6, 0.25), sun_col="#ffcc90",
                       sun_size=0.0, glow=0.10, power=0.5)
        sand, haze, dens = col("#d39a62"), col("#e2c39c"), 0.012
    shadow = T.shadows(hfun, sun, 6.0, k=22, soft=0.03)
    light = lambert(T, sun, sun_col, skyc, gnd, sky_amb=amb, ground_amb=0.18, shadow=shadow)
    del shadow
    sd = np.asarray(sun, F32) / np.linalg.norm(sun)

    def surface(idx, dy):
        L = T.gather_smooth(light, idx, dy)
        z = T.zpix(idx, dy)
        x = T.xpix(z)
        p = x * c + z * s
        q = -x * s + z * c
        # Wind ripples: fine crests across the wind, as an emboss against the
        # light, fading out with distance (too fine to see beyond ~25 units).
        rip = lambda pp: np.sin((pp * 11.0 + 1.2 * nz.fbm(q * 1.2, pp * 1.2, 3)) * 2 * math.pi)
        bump = (rip(p) - rip(p + 0.006 * np.sign(sd[0] * c + sd[2] * s + 1e-6))) * 0.5
        bump *= np.exp(-z / 9.0) * 0.35
        tone = 1 + 0.06 * nz.fbm(x * 0.8, z * 0.8, 3)
        col_ = sand * L * (tone + bump)[..., None]
        return fog(col_, z, haze, dens)
    img, _ = T.shade(surface, sky)
    return img


def dunes_day(fr):
    """14: desert dunes by day -- sharp-crested dunes under a low warm sun
    from the right, cast shadows in the lee, wind ripples close up, a hazy
    warm horizon under a pale blue sky."""
    return dunes(fr, night=False)


def dunes_night(fr):
    """15: the same dunes by night -- moonlight from the left, cool blue
    shadows, a starfield and a dusk-blue glow on the horizon."""
    return dunes(fr, night=True)


def granite_world(nz):
    """The granite valley of 10 and 11: a flat floor of conifers (cones());
    on the right the valley wall with a monolith -- a sheer face whose foot
    line bulges out into the valley in a prow, its top a broad dome sloping
    back -- a wall of slabs over a talus apron on the left, rounded domes
    and ridges closing the valley far away."""
    def hfun(x, z):
        floor = 0.04 * nz.fbm(x / 3, z / 3, 3)
        trees = cones(x, z, 0.11, 0.22) * smoothstep(0.8, 2.0, z)
        # The right wall and its prow.
        xf = 1.7 + 0.11 * (z - 10) - 1.3 * np.exp(-((z - 14) / 3.2) ** 2) + 0.25 * nz.fbm(z / 2.0, 3.0, 4)
        top = (2.2 + 0.9 * np.exp(-((z - 15) / 5.5) ** 2) + 0.25 * nz.fbm(x / 2, z / 2, 4)
               - 0.06 * np.maximum(x - xf, 0))
        right = smoothstep(0.0, 0.30, x - xf) * top * smoothstep(5.0, 8.0, z)
        # The left wall: slabs rising past x = -2.2 - 0.05 z, a talus apron.
        lw = -x - 2.2 - 0.05 * z + 0.6 * nz.fbm(z / 4, 1.0, 3)
        left = smoothstep(0.0, 0.45, lw) * (1.7 + 0.9 * nz.ridged(x / 3.5, z / 3.5, 5, sharp=1.6))
        left += smoothstep(-0.9, 0.2, lw) * 0.35 + smoothstep(0.5, 3.0, lw) * 0.6
        far = smoothstep(30, 45, z) * (1.0 + 1.4 * nz.ridged(x / 9, z / 9, 5, sharp=1.3))
        dome = 2.4 * np.clip(1 - ((x + 1.5) / 4.5) ** 2 - ((z - 48) / 6) ** 2, 0, None) ** 0.45
        return np.maximum.reduce([floor + trees, right, left, far, dome])
    return hfun


def granite_surface(T, nz, light, haze, dens, alpen=None):
    """Per-pixel surface for the granite scenes: granite (pale, warm,
    streaked vertically -- the dark water streaks of real walls -- by fbm
    of the height the pixel sees, with a fine emboss) on the walls, dark
    conifers on the floor (anything low), fog; `alpen` = (colour, from, to)
    adds a glow on the top of the walls (rh between from and to)."""
    ny = np.ascontiguousarray(T.normal[..., 1])

    def surface(idx, dy):
        L = T.gather_smooth(light, idx, dy)
        n_y = T.gather_smooth(ny, idx, dy)
        z = T.zpix(idx, dy)
        x = T.xpix(z)
        rh = T.ray_height(idx, dy, z)
        # Across the wall in VIEW angle (x / z), so the streaks run straight
        # down a sheer face however it recedes.
        along = x / z * 9.0 + 0.02 * z
        streak = nz.fbm(along * 1.6, rh * 0.25, 5)
        tone = 1 + 0.12 * nz.fbm(along * 0.25 + 3, rh * 0.4, 3)
        rel = lambda a, b: nz.fbm(a * 9.0 + 5, b * 4.0, 4)
        bump = np.clip((rel(along, rh) - rel(along + 0.01, rh - 0.008)) * 5.0, -0.35, 0.35)
        granite = mix(np.broadcast_to(col("#bdb4a6"), z.shape + (3,)), col("#6a655e"),
                      smoothstep(0.0, 0.8, streak) * 0.45)
        granite = granite * (tone + bump)[..., None]
        rock = smoothstep(0.32, 0.5, rh) * (1 - 0.3 * smoothstep(0.85, 0.97, n_y))
        trees = mix(np.broadcast_to(col("#14221a"), z.shape + (3,)), col("#2c4226"),
                    smoothstep(-0.3, 0.6, nz.fbm(x * 14, z * 14 + rh * 30, 2)))
        c = mix(trees, granite, rock) * L
        if alpen is not None:
            ac, a0, a1 = alpen
            c = c + granite * col(ac) * (smoothstep(a0, a1, rh) * rock)[..., None]
        c = fog(c, z, haze, dens)
        # ground mist pooled on the valley floor
        return fog(c, z, haze, 0.06, height=rh, falloff=0.25)
    return surface


def granite_valley(fr):
    """10: the granite valley at golden hour -- the monolith lit warm from
    the left, the left wall in shade, a dark conifer floor, domes and ridges
    fading into gold haze at the valley's end, a pale blue-gold sky."""
    nz = fr.noise
    hv, f, cam_h = 0.60, 2.0, 0.60
    hfun = granite_world(nz)
    T = Terrain(fr, hfun, cam_h, hv, f, 1.0, 120.0)
    sun = (-0.55, 0.28, -0.80)
    shadow = T.shadows(hfun, sun, 10.0, k=20)
    light = lambert(T, sun, "#ffc98a", "#86a8d8", "#4a3a2a", sky_amb=0.38, shadow=shadow)
    del shadow
    sky = sky_dome(fr, hv, "#4a78b4", "#efd2a2", power=0.55)
    cc, ca = cloud_deck(fr, nz, hv, f, 6.0, 8.0, 0.62, "#ffe2bc", "#a0a0b4", -0.6, alpha=0.6)
    sky = mix(sky, cc, ca)
    img, _ = T.shade(granite_surface(T, nz, light, col("#d8c8ac"), 0.022), sky)
    return img


def granite_cliff_dusk(fr):
    """11: the great cliff at dusk -- the monolith seen square on at blue
    hour: no sun on the valley, alpenglow (pink-orange) on the top of the
    wall fading to cool blue-grey below, a starry blue-violet sky with a
    faint moon glow, the forest at its foot almost black."""
    nz = fr.noise
    hv, f, cam_h = 0.68, 2.0, 0.60
    hfun = granite_world(nz)
    T = Terrain(fr, hfun, cam_h, hv, f, 1.0, 120.0, cam_x=1.2)
    light = lambert(T, (-0.3, 0.6, -0.7), "#3a4a78", "#5a6ca8", "#141824", sky_amb=0.55)
    sky = sky_dome(fr, hv, "#141a44", "#9a86b8", sun=(-0.85, 0.22), sun_col="#c8ccff",
                   sun_size=0.0, glow=0.08, power=0.6)
    sky += starfield(fr, 3500, 0.0, hv, bright=0.6) * smoothstep(0.55, 0.15, fr.v)[..., None]
    surf = granite_surface(T, nz, light, col("#7a74a0"), 0.02, alpen=("#ff9a6a", 2.0, 2.7))
    img, _ = T.shade(surf, sky)
    return img


def _hash2(ix, iz, salt):
    """Integer lattice hash -> float 0..1 (vectorised)."""
    h = (ix * np.int32(374761393) + iz * np.int32(668265263) + np.int32(salt) * np.int32(974711)).astype(np.int32)
    h = (h ^ (h >> 13)) * np.int32(1274126177)
    h = h ^ (h >> 16)
    return (h & 0xFFFF).astype(F32) / F32(65535.0)


def cones(x, z, s, height, salt=1, density=0.85, shape=1.2):
    """A conifer stand as a heightfield: one tree per (jittered) cell of
    size s, each a cone of its own height (0.6-1.0 x `height`) and a
    spire-sharp top (shape > 1; shape < 1 rounds it into a broadleaf
    dome); the max over the 3 x 3 neighbouring cells. Cells left empty
    (1 - density) make clearings."""
    cx = np.floor(x / s).astype(np.int32)
    cz = np.floor(z / s).astype(np.int32)
    out = np.zeros(np.broadcast(x, z).shape, F32)
    for ox in (-1, 0, 1):
        for oz in (-1, 0, 1):
            ix, iz = cx + ox, cz + oz
            jx = _hash2(ix, iz, salt)
            jz = _hash2(ix, iz, salt + 7)
            hh = _hash2(ix, iz, salt + 13)
            px = (ix + 0.15 + 0.7 * jx) * s
            pz = (iz + 0.15 + 0.7 * jz) * s
            d = np.sqrt((x - px) ** 2 + (z - pz) ** 2)
            th = height * (0.6 + 0.4 * hh) * (hh < density + 0.15)
            r = 0.42 * s * (0.8 + 0.4 * hh)
            out = np.maximum(out, th * np.clip(1 - d / r, 0, None) ** shape)
    return out


def range_h(nz, x, z, near, far, height, scale=8.0, sharp=1.7, centre=0.12):
    """A ridged mountain range between distances near..far (rising over a
    few units), heights varied by a broad macro noise, a massif near
    u = centre so the range has a summit."""
    band = smoothstep(near, near + 8, z) * smoothstep(far + 30, far, z)
    macro = np.clip(0.55 + 0.55 * nz.fbm(x / 16 + 3, z / 16, 3), 0.15, 1.1)
    rid = nz.ridged(x / scale, z / scale, 6, sharp=sharp)
    massif = 0.6 * np.exp(-((x - centre * z) / (0.30 * z + 2)) ** 2)
    return height * band * (macro + massif) * rid


def lake_scene(fr, hfun, cam_h, hv, f, z_far, make_surface, sky, water, ripple=(3.0, 5.0), foam=None,
               cam_x=0.0):
    """Compose a scene over calm water at height 0: the land (hfun, the
    water cut flat at 0) shaded by make_surface(T) -> surface(idx, dy);
    the water reflects the mirrored render (mirror()), distorted by
    ripples, mixed with the water's own colour by Fresnel. water =
    (deep colour, sky-tinted shallow colour); foam(x, z) -> 0..1 paints
    white water on it (surf at the foot of cliffs)."""
    nz = fr.noise
    def hland(x, z):
        return np.maximum(hfun(x, z), 0.0)
    T = Terrain(fr, hland, cam_h, hv, f, 0.6, z_far, cam_x=cam_x)
    mimg = mirror(fr, hfun, 0.0, cam_h, hv, f, 0.6, z_far, make_surface, sky, cam_x=cam_x)
    mimg = blur(mimg, 0.8 * fr.k + 0.3, 2.5 * fr.k + 0.5)     # a still lake is never a perfect mirror
    land = make_surface(T)
    deep, shallow = col(water[0]), col(water[1])

    def surface(idx, dy):
        c = land(idx, dy)
        z = T.zpix(idx, dy)
        rh = T.ray_height(idx, dy, z)
        wet = smoothstep(0.006, 0.0, rh)
        if not wet.any():
            return c
        x = T.xpix(z)
        v = T.vblock(idx)
        ddx, ddy = water_ripple(nz, x, z, ripple[0], ripple[1] * fr.k)
        refl = reflect(fr, mimg, hv, v + F32(dy / fr.H), ddx, ddy)
        R = fresnel(v, hv, f)
        body = mix(np.broadcast_to(deep, c.shape), shallow, smoothstep(0.3, 0.0, (v - hv)))
        wcol = body * (1 - R)[..., None] + refl * R[..., None]
        if foam is not None:
            wcol = mix(wcol, col("#dfe6ea", 0.9), foam(x, z))
        return mix(c, wcol, wet)
    img, _ = T.shade(surface, sky)
    return img


def mountain_lake(fr):
    """13: the autumn alpine lake -- a still lake in the foreground,
    shores of gold, orange and red deciduous trees under dark conifers,
    grey mountains with a little early snow behind, all mirrored in the
    rippled water; a calm, pale sky."""
    nz = fr.noise
    hv, f, cam_h = 0.50, 2.3, 0.30

    def hfun(x, z):
        shore = 8.0 + 2.5 * nz.fbm(x / 5.0, 2.0, 3) + 0.06 * x * x
        side = smoothstep(0.0, 1.0, np.abs(x) - 2.8 - 0.30 * z)
        rise = np.maximum(smoothstep(shore - 0.2, shore + 0.8, z), side)
        hills = rise * (0.42 + 0.25 * nz.fbm(x / 2.5 + 4, z / 2.5, 5) + 1.0 * smoothstep(shore + 2, shore + 10, z))
        # rounded crowns: deciduous trees on the banks
        ground = -0.4 + hills
        # trees from the waterline up (a crown on drowned ground would be cut)
        trees = smoothstep(-0.02, 0.04, ground) * cones(x, z, 0.13, 0.12, density=0.95, shape=0.45)
        mtn = range_h(nz, x, z, 14, 45, 2.9, scale=7.0)
        return ground + np.maximum(trees, mtn)

    def make_surface(T):
        sun = (-0.85, 0.38, 0.15)
        light = lambert(T, sun, "#ffe2c0", "#9cb8e0", "#3a3226", sky_amb=0.42)
        ny = np.ascontiguousarray(T.normal[..., 1])

        def surface(idx, dy):
            L = T.gather_smooth(light, idx, dy)
            n_y = T.gather_smooth(ny, idx, dy)
            z = T.zpix(idx, dy)
            x = T.xpix(z)
            rh = T.ray_height(idx, dy, z)
            leaf = nz.fbm(x * 6, z * 6 + rh * 9, 3)
            autumn = ramp(np.clip(leaf * 0.5 + 0.5, 0, 1), [(0.0, "#7a1e0c"), (0.35, "#c24a12"),
                                                           (0.6, "#e08a1e"), (0.85, "#e8b83a"), (1.0, "#9a9a30")])
            pines = mix(np.broadcast_to(col("#14261a"), z.shape + (3,)), col("#24402a"),
                        smoothstep(-0.4, 0.6, nz.fbm(x * 12, z * 12 + rh * 20, 2)))
            trees = mix(autumn, pines, smoothstep(0.35, 0.9, rh + 0.3 * nz.fbm(x * 2, z * 2, 2)))
            streak = nz.fbm(x / z * 30.0, rh * 3.0, 3)
            rock = mix(np.broadcast_to(col("#6c6863"), z.shape + (3,)), col("#3e3c3a"), smoothstep(-0.3, 0.6, streak))
            is_rock = np.maximum(smoothstep(1.2, 1.7, rh), smoothstep(0.62, 0.45, n_y) * smoothstep(0.5, 0.9, rh))
            snow = smoothstep(0.62, 0.72, n_y) * smoothstep(2.4, 2.7, rh + 0.4 * nz.fbm(x * 2, rh * 2, 2))
            rel = lambda a, b: nz.fbm(a * 7.0 + 5, b * 5.0, 4)
            bump = np.clip((rel(x, rh) - rel(x + 0.012, rh - 0.010)) * 5.0, -0.4, 0.4) * is_rock
            c = mix(mix(trees, rock, is_rock), col("#e8eef4"), snow) * L * (1 + bump)[..., None]
            return fog(c, z, col("#b4c4d8"), 0.011)
        return surface

    sky = sky_dome(fr, hv, "#4c78b0", "#d4dde6", power=0.55)
    cc, ca = cloud_deck(fr, nz, hv, f, 6.0, 7.0, 0.60, "#f6f2ea", "#a4aab8", -0.5, alpha=0.7)
    sky = mix(sky, cc, ca)
    return lake_scene(fr, hfun, cam_h, hv, f, 140.0, make_surface, sky, ("#123040", "#4a6a80"),
                      ripple=(1.5, 2.5))


def island_dusk(fr):
    """16: the rocky island at dusk -- a steep island (a ridged dome,
    cliffs where it meets the sea) far out on a calm sea, under a sky
    running from lavender overhead to peach at the horizon where the sun
    has just gone; the island in soft silhouette with a warm rim, the sky
    and the island mirrored in the gently waving sea, mist on the water."""
    nz = fr.noise
    hv, f, cam_h = 0.56, 2.6, 0.12
    ic = fr.centre_u(0.10, 0.45) * 22 / f

    def hfun(x, z):
        d = np.sqrt(((x - ic) / 6.5) ** 2 + ((z - 19) / 3.0) ** 2)
        d = d + 0.10 * nz.fbm(x / 1.5, z / 1.5, 4)
        dome = np.clip(1 - d, 0, None)
        rid = nz.ridged(x / 2.2, z / 2.2, 6, sharp=1.6)
        h = 1.7 * dome ** 0.7 * (0.5 + 0.7 * rid) + 0.30 * smoothstep(0.0, 0.06, dome)
        # a smaller islet to the side
        d2 = np.sqrt(((x - ic - 9.5) / 1.8) ** 2 + ((z - 30) / 1.2) ** 2) + 0.15 * nz.fbm(x, z, 3)
        h2 = 0.5 * np.clip(1 - d2, 0, None) ** 0.6
        return np.maximum(h, h2) - 0.02

    sky = fr.vgrad([(0.0, "#3a3266"), (0.22, "#6a5a92"), (0.40, "#c09ab8"), (hv - 0.05, "#f4b8a0"),
                    (hv, "#f7c8a0"), (1.0, "#f7c8a0")])
    sky = add(sky, col("#ffb080"), 0.35 * np.exp(-(((fr.u + 0.55) / 0.5) ** 2 + ((fr.v - hv) / 0.10) ** 2)))
    cc, ca = cloud_deck(fr, nz, hv, f, 5.0, 6.0, 0.62, "#ffc8b0", "#7a6a98", -0.6, stretch=3.5, alpha=0.55)
    sky = mix(sky, cc, ca)

    def make_surface(T):
        light = lambert(T, (-0.9, 0.12, 0.4), "#ff9a70", "#8070b0", "#302838", sky_amb=0.55)
        ny = np.ascontiguousarray(T.normal[..., 1])

        def surface(idx, dy):
            L = T.gather_smooth(light, idx, dy)
            n_y = T.gather_smooth(ny, idx, dy)
            z = T.zpix(idx, dy)
            x = T.xpix(z)
            rh = T.ray_height(idx, dy, z)
            rock = mix(np.broadcast_to(col("#5a5048"), z.shape + (3,)), col("#3a3430"),
                       smoothstep(-0.3, 0.6, nz.fbm(x / z * 40, rh * 4, 3)))
            scrub = mix(np.broadcast_to(col("#3a4430"), z.shape + (3,)), col("#55603a"),
                        smoothstep(-0.3, 0.6, nz.fbm(x * 6, z * 6, 3)))
            c = mix(rock, scrub, smoothstep(0.6, 0.85, n_y)) * L
            c = fog(c, z, col("#c8a8b8"), 0.022)
            return fog(c, z, col("#e8c0b0"), 0.25, height=rh, falloff=0.08)
        return surface
    img = lake_scene(fr, hfun, cam_h, hv, f, 120.0, make_surface, sky, ("#2a2a50", "#8a7aa8"),
                     ripple=(1.2, 5.0))
    # Gentle wave bands: long, low swells catch the light across the sea.
    below = smoothstep(hv, hv + 0.01, fr.v)
    zsea = cam_h * f / np.maximum(fr.v - hv, 1e-4)
    swell = nz.fbm(fr.u * zsea / f / 6.0, zsea / 1.2, 3)
    img *= (1 + 0.10 * swell * below * np.exp(-zsea / 30))[..., None]
    return img


def alpine_lake(fr):
    """25: the deep-blue alpine lake in afternoon light -- clear sapphire
    water ringed by dark pine ridges that come down to it from both sides,
    a snowy peak far beyond, glassy reflections, a crisp sky."""
    nz = fr.noise
    hv, f, cam_h = 0.52, 2.2, 0.45

    def hfun(x, z):
        # The basin: the water's edge pulls in towards the middle with
        # distance (a lake narrowing to the far shore), the ridges rise
        # steeply out of it on both sides.
        edge = 1.6 + 0.12 * z - 0.004 * z * z + 0.4 * nz.fbm(z / 3, 2.0, 3)
        side = np.abs(x - 0.03 * z) - edge
        ridge = smoothstep(-0.2, 1.8, side) * (1.4 + 0.8 * nz.fbm(x / 3, z / 3, 4) + 0.08 * z)
        far = smoothstep(17, 20, z) * (0.6 + 0.3 * nz.fbm(x / 2, z / 2, 3))
        ground = -0.3 + np.maximum(ridge, far) + 0.3 * smoothstep(-0.4, 0.2, side)
        pines = smoothstep(-0.02, 0.05, ground) * cones(x, z, 0.10, 0.20, salt=5) * smoothstep(2.6, 1.6, ground)
        peak = range_h(nz, x, z, 36, 80, 2.7, scale=9.0, centre=0.02)
        return ground + np.maximum(pines, peak)

    def make_surface(T):
        sun = (0.6, 0.55, -0.45)
        shadow = T.shadows(lambda x, z: hfun(x, z), sun, 6.0, k=14)
        light = lambert(T, sun, "#fff0dc", "#8cb4f0", "#2a3440", sky_amb=0.42, shadow=shadow)
        ny = np.ascontiguousarray(T.normal[..., 1])

        def surface(idx, dy):
            L = T.gather_smooth(light, idx, dy)
            n_y = T.gather_smooth(ny, idx, dy)
            z = T.zpix(idx, dy)
            x = T.xpix(z)
            rh = T.ray_height(idx, dy, z)
            pine = mix(np.broadcast_to(col("#0f2016"), z.shape + (3,)), col("#25412a"),
                       smoothstep(-0.4, 0.6, nz.fbm(x * 10, z * 10 + rh * 20, 2)))
            rock = mix(np.broadcast_to(col("#6a6660"), z.shape + (3,)), col("#3c3a38"),
                       smoothstep(-0.3, 0.6, nz.fbm(x / z * 30.0, rh * 3.0, 3)))
            hi = smoothstep(2.2, 2.8, rh)
            snow = smoothstep(0.5, 0.7, n_y + 0.1 * nz.fbm(x * 3, rh * 3, 2)) * smoothstep(2.7, 3.1, rh)
            c = mix(mix(pine, rock, hi), col("#eef3fa"), snow) * L
            return fog(c, z, col("#a8c0e0"), 0.006)
        return surface

    sky = sky_dome(fr, hv, "#1f56a8", "#bcd2ec", power=0.5)
    cc, ca = cloud_deck(fr, nz, hv, f, 7.0, 8.0, 0.64, "#ffffff", "#a8b4c8", 0.5, alpha=0.7)
    sky = mix(sky, cc, ca)
    return lake_scene(fr, hfun, cam_h, hv, f, 140.0, make_surface, sky, ("#06284a", "#1f5a8a"),
                      ripple=(1.0, 2.0))


def layer_curve(fr, base, terms):
    """v of a smooth crest over u: base + sum of a sin(f u + phase)."""
    u = fr.u
    y = np.full_like(u, base)
    for a, fq, ph in terms:
        y = y + a * np.sin(fq * u + ph)
    return y


def gradient_hills(fr):
    """18: smooth gradient hills. Five layered hills, back to front, each a
    sum of slow sines; filled with a vertical gradient that is lightest on
    its crest; each casting a soft shadow up onto the layer behind (the
    layer's own mask, blurred and nudged up). Blue at the back, through
    violet and magenta, to coral at the front."""
    rng = fr.rng
    c = fr.vgrad([(0.0, "#1a2a6a"), (0.5, "#3c4fa8"), (1.0, "#6a6ad0")])
    c = add(c, col("#8aa0ff"), 0.25 * np.exp(-((fr.u - 0.2) ** 2 / 0.6 + (fr.v - 0.45) ** 2 / 0.05)))
    layers = [
        (0.42, "#4a6ad8", "#2a3c98"), (0.52, "#6a58d0", "#3a2c90"), (0.62, "#9a4cc8", "#4c2280"),
        (0.72, "#d0509a", "#6a1e60"), (0.83, "#f07a6a", "#8a2c4a"),
    ]
    for i, (base, top, bottom) in enumerate(layers):
        terms = [(0.05 + 0.02 * i, rng.uniform(1.2, 2.0), rng.uniform(0, 6)),
                 (0.025, rng.uniform(2.5, 3.6), rng.uniform(0, 6)),
                 (0.012, rng.uniform(4.5, 6.0), rng.uniform(0, 6))]
        y = layer_curve(fr, base, terms)
        mask = fr.aa(fr.v - y)
        sh = blur(mask, 30 * fr.k + 1)
        shift = int(10 * fr.k) + 1
        sh = np.concatenate([sh[shift:], np.repeat(sh[-1:], shift, 0)], 0)
        c *= (1 - 0.30 * sh * (1 - mask))[..., None]
        t = np.clip((fr.v - y) / 0.35, 0, 1) ** 0.7
        fill = ramp(t, [(0.0, top), (1.0, bottom)])
        # a soft light on the crest itself
        fill = add(fill, col(top), 0.35 * np.exp(-np.clip(fr.v - y, 0, None) / 0.012))
        c = mix(c, fill, mask)
    return c


def flowing_waves(fr):
    """19: colourful flowing waves. Six ribbons sweep across the frame from
    lower left to upper right, layered back to front; each is shaded from
    its edge's slope (a pseudo-normal: the steeper the curve, the darker
    the face below it) and lit along its crest; a soft ambient-occlusion
    shadow lies on the layer under each edge."""
    rng = fr.rng
    u, v = fr.u, fr.v
    c = fr.vgrad([(0.0, "#1c0e3a"), (1.0, "#2a1450")])
    cols = [("#3a2a9a", "#1c1460"), ("#5a3ac8", "#2a1c80"), ("#2f6ae0", "#18308a"),
            ("#b04ac8", "#5a1a78"), ("#f0609a", "#8a1c50"), ("#ff8a6a", "#a83a3a")]
    for i, (lit, dark) in enumerate(cols):
        base = 0.20 + 0.13 * i
        y = (base - 0.22 * u + 0.09 * np.sin(2.3 * u + rng.uniform(0, 6))
             + 0.04 * np.sin(4.1 * u + rng.uniform(0, 6)) + 0.015 * np.sin(7.3 * u + rng.uniform(0, 6)))
        slope = np.gradient(y[0]) * fr.H
        mask = fr.aa(v - y)
        ao = blur(mask, 40 * fr.k + 1)
        c *= (1 - 0.45 * ao * (1 - mask))[..., None]
        depth = np.clip((v - y) / 0.30, 0, 1)
        light = np.clip(0.55 - 2.2 * slope[None, :], 0, 1)
        fill = mix(np.broadcast_to(col(lit), c.shape), col(dark), depth ** 0.6)
        fill = fill * (0.75 + 0.5 * light)[..., None]
        fill = add(fill, col(lit), 0.45 * np.exp(-np.clip(v - y, 0, None) / 0.008) * (0.4 + light))
        c = mix(c, fill, mask)
    return c


def orange_bloom(fr):
    """20: the abstract bloom. Twelve long translucent petals (superellipse
    blades) radiate from a point a little below and right of centre; each
    is a gradient from a deep red base to a bright amber tip with a lit
    rim; overlapping petals darken each other (multiplied, as dyed glass),
    the outer ones softened as if out of focus; a dark warm ground."""
    rng = fr.rng
    u, v = fr.u, fr.v
    cu = fr.centre_u(0.12, 0.3)
    cv = 0.92
    c = fr.vgrad([(0.0, "#140604"), (0.6, "#24090a"), (1.0, "#2e0c08")])
    c = add(c, col("#ff6a20"), 0.10 * np.exp(-(((u - cu) / 0.6) ** 2 + ((v - cv) / 0.4) ** 2)))
    petals = []
    for i in range(13):
        ang = -math.pi / 2 + (i - 6) * 0.20 + rng.normal(0, 0.04)
        L = rng.uniform(0.64, 0.74) * (1.0 - 0.30 * abs(i - 6) / 6)
        Wd = rng.uniform(0.10, 0.14)
        petals.append((abs(i - 6), ang, L, Wd))
    petals.sort(key=lambda p: -p[0])           # outer petals first (behind)
    for rank, ang, L, Wd in petals:
        ca, sa = math.cos(ang), math.sin(ang)
        dx, dy = u - cu, v - cv
        a = dx * ca + dy * sa                  # along the petal
        b = -dx * sa + dy * ca                 # across
        t = a / L
        width = Wd * np.clip(np.sin(np.clip(t, 0, 1) * math.pi), 0, 1) ** 0.7 + 1e-4
        shape = 1 - (np.abs(b) / width) ** 2.5
        inside = (t > 0) & (t < 1)
        d = np.where(inside, shape * width, -1.0)
        soft = 0.5 + rank * 1.4                # px of edge softness: depth of field
        m = smoothstep(-soft / fr.H, soft / fr.H, d)
        tint = ramp(np.clip(t, 0, 1), [(0.0, "#5a0c06"), (0.35, "#c0300c"), (0.75, "#f07a18"), (1.0, "#ffb44a")])
        rim = np.exp(-np.clip(d, 0, None) / (0.004 + 0.001 * rank)) * smoothstep(0, 0.2, t)
        petal = add(tint * 1.1, col("#ffd08a"), rim * 0.8)
        # translucent over what is behind, and darkening where they overlap
        c = mix(c, c * petal * 2.2, m * 0.55)
        c = mix(c, petal, m * 0.55)
    c = add(c, col("#ff9a40"), 0.25 * np.exp(-(((u - cu) ** 2 + (v - cv) ** 2) / 0.01)))
    return c


def silk_folds(fr):
    """22: silky folds. A sheet of silk: a low-frequency, domain-warped
    noise folded into creases (h = -|n|^0.8: soft rounded tops, sharp
    valleys where the cloth doubles back), lit from the upper left -- a
    soft Lambert term, a broad sheen and a tight highlight along the
    crests. The colour runs across the sheet, teal at the top left through
    green to deep blue at the bottom right; the light does the rest."""
    nz = fr.noise
    u, v = fr.u, fr.v

    def h(a, b):
        wa = a + 0.35 * nz.fbm(a * 0.7 + 3, b * 0.7, 3)
        wb = b + 0.35 * nz.fbm(a * 0.7, b * 0.7 + 7, 3)
        n = nz.fbm(wa * 1.15, wb * 1.6, 3)
        return -np.abs(n) ** 0.8 + 0.25 * nz.fbm(wa * 0.6 + 11, wb * 0.6, 2)
    e = 1.0 / fr.H
    uu, vv = np.broadcast_arrays(u, v)
    h0 = h(uu, vv)
    hx = (h(uu + e, vv) - h0) / e
    hy = (h(uu, vv + e) - h0) / e
    k = 0.045
    n = np.stack([-hx * k, -hy * k, np.ones_like(h0)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    L = np.array([-0.55, -0.55, 0.63], F32)
    L /= np.linalg.norm(L)
    Hh = L + np.array([0, 0, 1], F32)
    Hh /= np.linalg.norm(Hh)
    ndh = np.clip(n @ Hh, 0, 1)
    diff = np.clip(n @ L, 0, 1)
    t = np.clip(0.5 + 0.55 * (u * 0.45 + (v - 0.5) * 0.9), 0, 1)
    base = ramp(t, [(0.0, "#2aa8a0"), (0.35, "#138a74"), (0.65, "#0c4a78"), (1.0, "#061a4a")])
    c = base * (0.22 + 0.95 * diff ** 1.4)[..., None]
    c = add(c, col("#c8fff0"), 0.30 * ndh ** 18 + 0.35 * ndh ** 120)
    return c


def glass_waves(fr):
    """24: liquid-glass waves. A deep-blue-to-cyan gradient behind five
    translucent glass bands (each the region between two flowing curves);
    through each band the gradient is refracted (sampled with an offset
    that grows towards the band's edges, as a thick lens bends it), tinted
    and brightened a little, with bright rims along both edges and a soft
    shadow under the band."""
    rng = fr.rng
    u, v = fr.u, fr.v
    bg = fr.vgrad([(0.0, "#020a2a"), (0.45, "#06338a"), (0.8, "#0a6ac8"), (1.0, "#22b4e8")])
    bg = add(bg, col("#3ad0ff"), 0.30 * np.exp(-(((u + 0.3) / 0.8) ** 2 + ((v - 0.95) / 0.25) ** 2)))
    # Soft colour fields behind the glass, so its refraction has something to bend.
    for gu, gv, r, hue, a in ((-0.6, 0.55, 0.25, "#5a4cff", 0.35), (0.5, 0.45, 0.30, "#00c8ff", 0.30),
                              (0.05, 0.75, 0.20, "#7af0ff", 0.25), (0.9, 0.80, 0.25, "#2a5aff", 0.30)):
        bg = add(bg, col(hue), a * np.exp(-(((u - gu) ** 2 + (v - gv) ** 2) / (r * r))))
    c = bg.copy()
    yy, xx = np.mgrid[0:fr.H, 0:fr.W].astype(F32)
    for i in range(4):
        base = 0.20 + 0.17 * i
        ph = rng.uniform(0, 6)
        y0 = base + 0.12 * np.sin(1.3 * u + ph) + 0.04 * np.sin(3.1 * u + 2 * ph)
        th = 0.20 + 0.08 * np.sin(1.1 * u + ph * 1.3)
        y1 = y0 + th
        mid = (y0 + y1) / 2
        half = th / 2
        d = half - np.abs(v - mid)                  # > 0 inside
        m = fr.aa(d)
        s = np.clip(1 - d / half, 0, 1)             # 0 in the middle, 1 at the edges
        sh = blur(m, 18 * fr.k + 1)
        off = int(14 * fr.k) + 1
        sh = np.concatenate([np.zeros((off, fr.W), F32), sh[:-off]], 0)
        c *= (1 - 0.30 * sh * (1 - m))[..., None]
        bend = (s ** 3) * np.sign(v - mid) * 220 * fr.k
        refr = sample(bg, xx + bend * 0.3, yy - bend)
        glass = add(refr * 1.08, col("#9ae6ff"), 0.10 + 0.5 * s ** 6)
        rim = np.exp(-np.clip(d, 0, None) * fr.H / (2.0 * fr.k + 0.6))
        glass = add(glass, col("#e8fbff"), rim * 0.55)
        c = mix(c, glass, m * 0.92)
    return c


def coast_cliffs(fr):
    """17: coastal cliffs at dusk. Headland after headland (the coastline
    x_c(z) swings out and back as it recedes) drop as cliffs into a calm
    sea on the left; seen from a cliff top, each farther one paler in the
    fog, five or six deep; a pastel pink-to-blue sky; surf lines the cliff
    feet (foam where the water meets the coast)."""
    nz = fr.noise
    hv, f, cam_h = 0.44, 2.2, 1.9

    def xc(z):
        # bending left with distance, so each farther headland steps out
        # across the sea into view; the sine makes the headlands and coves
        return 2.8 - 0.075 * z + 0.9 * np.abs(np.sin(z / 2.6 + 0.4)) ** 0.6 + 0.35 * nz.fbm(z / 3.0, 5.0, 3)

    def hfun(x, z):
        d = x - xc(z)
        cliff = smoothstep(-0.05, 0.45, d + 0.08 * nz.fbm(x * 3, z * 3, 3))
        top = 0.85 + 0.010 * z + 0.40 * nz.fbm(x / 2.2, z / 2.2, 5) + 0.7 * smoothstep(1.0, 5.0, d)
        return -0.3 + cliff * (top + 0.3) + 0.06 * nz.fbm(x * 6, z * 6, 2) * cliff

    sky = fr.vgrad([(0.0, "#3c4c86"), (0.20, "#6a7ab0"), (0.36, "#c8a8c4"), (hv, "#f2c4b8"), (1.0, "#f2c4b8")])
    cc, ca = cloud_deck(fr, nz, hv, f, 5.0, 6.0, 0.63, "#f8d0c4", "#8a86ac", 0.4, stretch=3.0, alpha=0.5)
    sky = mix(sky, cc, ca)

    def make_surface(T):
        sun = (-0.75, 0.22, -0.35)          # low over the sea, on the left
        light = lambert(T, sun, "#ffb08a", "#9a9ad0", "#3a3040", sky_amb=0.5)
        ny = np.ascontiguousarray(T.normal[..., 1])

        def surface(idx, dy):
            L = T.gather_smooth(light, idx, dy)
            n_y = T.gather_smooth(ny, idx, dy)
            z = T.zpix(idx, dy)
            x = T.xpix(z)
            rh = T.ray_height(idx, dy, z)
            rock = mix(np.broadcast_to(col("#7a665a"), z.shape + (3,)), col("#3c3430"),
                       smoothstep(-0.3, 0.6, nz.fbm(x / z * 30, rh * 5, 3)))
            rel = lambda a, b: nz.fbm(a * 40 + 5, b * 6.0, 3)
            rock = rock * (1 + np.clip((rel(x / z, rh) - rel(x / z + 0.002, rh - 0.01)) * 4, -0.35, 0.35))[..., None]
            grass = mix(np.broadcast_to(col("#56603a"), z.shape + (3,)), col("#8a8a52"),
                        smoothstep(-0.4, 0.6, nz.fbm(x * 3, z * 3, 3)))
            c = mix(rock, grass, smoothstep(0.55, 0.8, n_y)) * L
            # fog: thick sea fog lying low, and the haze of distance
            c = fog(c, z, col("#e2c0c0"), 0.040)
            return fog(c, z, col("#ecc8c4"), 0.12, height=rh, falloff=0.15)
        return surface

    def foam(x, z):
        d = xc(z) - x
        lace = smoothstep(-0.1, 0.5, nz.fbm(x * 8, z * 3, 3))
        return np.clip(np.exp(-np.maximum(d, 0) / 0.10) * (0.35 + 0.65 * lace) * 0.85, 0, 1) * (d > -0.2)

    return lake_scene(fr, hfun, cam_h, hv, f, 90.0, make_surface, sky, ("#28345a", "#a090b0"),
                      ripple=(1.0, 4.0), foam=foam, cam_x=0.0)


def green_hills(fr):
    """21: rolling green hills. Five stylised hills, back to front, each a
    smooth sum of sines lit from the upper left by its slope; between them
    a soft fog that pales the farther ones; on the nearest hill, vine rows
    running down the slope (lines through a vanishing point above it, the
    way rows converge in perspective); a pale morning sky."""
    rng = fr.rng
    u, v = fr.u, fr.v
    c = fr.vgrad([(0.0, "#6a9ad0"), (0.30, "#a8c8e4"), (0.5, "#dbe6e8"), (1.0, "#dbe6e8")])
    greens = [("#8ab49a", "#6a9a82"), ("#6aa860", "#4a8444"), ("#5aa63e", "#36782a"),
              ("#4c9a30", "#2c6a1e"), ("#3e8e24", "#1f5a14")]
    fogc = col("#dce8e6")
    for i, (lit, dark) in enumerate(greens):
        base = 0.46 + 0.085 * i
        y = layer_curve(fr, base, [(0.035 + 0.012 * i, rng.uniform(1.4, 2.2), rng.uniform(0, 6)),
                                    (0.018, rng.uniform(3.0, 4.2), rng.uniform(0, 6)),
                                    (0.006, rng.uniform(6.0, 8.0), rng.uniform(0, 6))])
        slope = np.gradient(y[0]) * fr.H
        mask = fr.aa(v - y)
        depth = np.clip((v - y) / 0.25, 0, 1)
        shade = np.clip(0.55 + 3.5 * slope[None, :] * np.exp(-depth * 2), 0, 1)
        fill = mix(np.broadcast_to(col(lit), c.shape), col(dark), np.clip(depth * 0.8 + (1 - shade) * 0.5, 0, 1))
        fill = add(fill, col("#e8f4c8"), 0.20 * np.exp(-np.clip(v - y, 0, None) / 0.01))
        if i == len(greens) - 1:
            vx, vy = 0.25 * u.max() if fr.half > 0.6 else 0.0, y.min() - 0.25
            q = (u - vx) / np.maximum(v - vy, 1e-3)
            dens = 8.0
            period = (v - vy) / dens * fr.H
            rows = 0.5 + 0.5 * np.cos(2 * math.pi * q * dens)
            fade = smoothstep(2.5, 7.0, period) * smoothstep(0.0, 0.03, v - y)
            fill = fill * (1 - 0.16 * smoothstep(0.5, 0.95, rows) * fade)[..., None]
        fill = fill * (1 + 0.04 * fr.noise.fbm(u * 30, v * 30, 3))[..., None]
        haze = (len(greens) - 1 - i) / (len(greens) - 1)
        fill = mix(fill, fogc, 0.40 * haze ** 1.5)
        # a fog bank lying in the dip in front of this hill
        c = mix(c, fogc, 0.18 * np.exp(-np.abs(v - y) / 0.03) * (v < y))
        c = mix(c, fill, mask)
    return c


def redwood_dawn(fr):
    """23: tall-forest sunrise. Giant trunks in five depth layers, far to
    near, in warm dawn mist, the low sun up and to the left behind the
    canopy: each trunk a tapered vertical cylinder -- dark, rounded, its
    furrowed bark (ridged noise along it) and a hot rim on its sun side
    catching the light; the farther layers pale into the mist. God rays
    slant down from the sun (stripes in the angle about it, from noise),
    laid in twice between the layers so the near trunks stand in front of
    them. A dark fern floor with lit tips, ground mist, the canopy's shade
    darkening the top."""
    rng, nz = fr.rng, fr.noise
    u, v = fr.u, fr.v
    H, W = fr.H, fr.W
    su, sv = -fr.half * 0.55 - 0.15, -0.10
    rs = np.sqrt((u - su) ** 2 + (v - sv) ** 2)
    phi = np.arctan2(v - sv, u - su)
    mist = col("#8a5a4c")
    c = fr.vgrad([(0.0, "#2a1c22"), (0.35, "#6e4a48"), (0.65, "#9a6650"), (1.0, "#5a3a2c")])
    c = add(c, col("#ffc488"), 1.0 * np.exp(-rs / 0.25))
    c *= (0.7 + 0.3 * np.exp(-np.maximum(u - su, 0) / 1.2))[..., None]
    beams = smoothstep(0.55, 0.85, nz.fbm(phi * 16.0, 3.0, 3) * 0.5 + 0.5) ** 1.3
    beams = beams * np.exp(-rs / 1.1) * smoothstep(0.1, 0.5, rs)
    layers = [(0.12, 0.010, 0.86, 12), (0.25, 0.017, 0.70, 9), (0.42, 0.028, 0.48, 7),
              (0.65, 0.045, 0.22, 5), (1.0, 0.080, 0.05, 4)]
    for li, (depth, wid, haze, n) in enumerate(layers):
        spots = np.sort(rng.uniform(-1.3, 1.3, n))
        mask = np.zeros((H, W), F32)
        dd = np.zeros((H, W), F32)
        for x0 in spots:
            w = wid * rng.uniform(0.7, 1.3)
            cx = x0 + rng.uniform(-0.012, 0.012) * (v - 0.5)
            half = w * (0.80 + 0.35 * v)
            m = np.broadcast_to(fr.aa(half - np.abs(u - cx)), (H, W))
            take = m > mask
            mask = np.maximum(mask, m)
            dd = np.where(take, np.broadcast_to((u - cx) / half, (H, W)), dd)
        d = np.clip(dd, -1, 1)
        rim = smoothstep(-0.55, -1.0, d) ** 1.5             # the sun is to the left
        round_ = np.sqrt(np.clip(1 - d * d, 0, 1))
        furrow = nz.ridged(u / wid * 4.0 + depth * 7, v * 0.9, 4, sharp=2.2)
        trunk = col("#4a2210") * ((0.30 + 0.70 * round_ * (0.5 - 0.5 * d)) * (0.25 + 1.2 * furrow))[..., None]
        trunk = add(trunk, col("#ff9a50"), rim * (0.5 + 0.8 * furrow) * 0.9)
        trunk = mix(trunk, mist * (0.7 + 0.9 * np.exp(-rs / 0.5))[..., None], haze)
        c = mix(c, trunk, mask)
        if li in (1, 3):
            c = add(c, col("#ffc488"), beams * 1.1)
    # The floor: ferns, ground mist, the canopy's shade at the top.
    floor_v = 0.89 + 0.02 * nz.fbm(u * 3, 1.0, 3)
    lean = np.sign(nz.fbm(u * 9, 1.0, 2) + 1e-3)
    fern = smoothstep(-0.1, 0.6, nz.fbm(u * 55 + lean * v * 40, v * 14, 3))
    fern2 = smoothstep(0.0, 0.7, nz.fbm(u * 140 - lean * v * 90, v * 35, 2))
    fm = fr.aa(v - floor_v + 0.02 * smoothstep(-0.2, 0.6, nz.fbm(u * 25, 2.0, 2)))
    ferns = mix(np.broadcast_to(col("#060a03"), (H, W, 3)), col("#24381a"), np.clip(fern * 0.6 + fern2 * 0.3, 0, 1))
    ferns = add(ferns, col("#ffb870"), 0.20 * fern2 * smoothstep(0.97, 0.86, v) * beams)
    c = mix(c, mist, 0.35 * np.exp(-np.abs(v - floor_v) / 0.035))
    c = mix(c, ferns, fm)
    c *= (0.6 + 0.4 * smoothstep(0.0, 0.3, v))[..., None]
    return c


def ocean_wave(fr):
    """09: the big ocean wave. A towering wave peaks left of centre: to the
    right of the peak its face is clean -- turquoise near the lip, where
    the light comes through thin water, to deep teal at its foot, streaked
    along the crest -- and at the peak the lip pitches over a dark tube;
    to the left it has already broken into an avalanche of white water.
    Spray streams back off the crest; whitewater boils at the foot; the
    trough in front is laced with foam; an overcast sky and a dark far sea
    behind."""
    nz = fr.noise
    u, v = fr.u, fr.v
    hz = 0.42
    c = fr.vgrad([(0.0, "#56636e"), (0.25, "#8a96a0"), (hz, "#b0bac0"), (hz + 0.001, "#2a4656"),
                  (1.0, "#123040")])
    c *= (1 + 0.06 * nz.fbm(u * 3, v * 9, 4) * (v < hz))[..., None]
    c *= (1 + 0.12 * nz.fbm(u * 4, v * 60, 3) * (v > hz))[..., None]
    peak = fr.centre_u(-0.10, 0.35)
    left = u < peak
    prof = np.where(left, np.exp(-((u - peak) / 0.75) ** 2), np.exp(-((u - peak) / 0.42) ** 2))
    base = 0.80
    crest = base - (0.08 + 0.46 * prof) + 0.012 * nz.fbm(u * 6, 1.0, 3)
    face = fr.aa(v - crest) * fr.aa(base + 0.02 - v)
    t = np.clip((v - crest) / (base - crest), 0, 1)
    water = ramp(t, [(0.0, "#62d4cc"), (0.12, "#2fa8b0"), (0.35, "#127080"), (0.7, "#0a4a5c"), (1.0, "#08324a")])
    water = add(water, col("#7ae0d0"), 0.25 * (1 - prof) * np.exp(-t / 0.2))
    flow = nz.fbm(u * 6 + 3, t * 26 + 0.6 * nz.fbm(u * 3, t * 3, 2), 4)
    drain = nz.fbm(u * 70, v * 5 + u * 3, 3)
    water = water * (1 + (0.12 * flow + 0.05 * drain) * (0.3 + t))[..., None]
    water = add(water, col("#bfe8e4"), 0.16 * smoothstep(0.35, 0.8, flow) * (1 - t))
    tube = np.exp(-((t - 0.25) / 0.14) ** 2) * np.exp(-((u - peak - 0.06) / 0.10) ** 2)
    water = water * (1 - 0.6 * tube)[..., None]
    c = mix(c, water, face)
    # the broken side: an avalanche of white water down the face, its own
    # lumpy shading (lit tops, grey hollows)
    broken = smoothstep(peak + 0.02, peak - 0.22, u + 0.06 * nz.fbm(v * 8, 3.0, 2))
    # the churn tumbles down the face: noise stretched along the fall line
    churn = nz.fbm(u * 9 + 0.4 * v, v * 4.5, 5) * 0.7 + nz.fbm(u * 30, v * 22, 3) * 0.3
    foamc = mix(np.broadcast_to(col("#a8b4ba"), c.shape), col("#f0f4f5"), smoothstep(-0.5, 0.4, churn))
    avalanche = broken * smoothstep(-0.02, 0.05, v - crest + 0.03) * fr.aa(base + 0.03 - v)
    avalanche *= smoothstep(-0.9, -0.2, churn + 0.8 * (1 - t))
    c = mix(c, foamc * 0.92, np.clip(avalanche, 0, 1))
    # the lip on the clean side: a thin frothy white edge
    lipn = nz.fbm(u * 45, v * 45, 4)
    dl = (v - crest) / (0.006 + 0.014 * prof)
    lip = np.exp(-np.clip(dl, 0, None) ** 2) * (v > crest - 0.004) * smoothstep(-0.5, 0.3, lipn) * (1 - broken)
    c = mix(c, col("#eef4f4", 0.95), np.clip(lip * 1.3, 0, 1))
    # spray streaming back off the crest
    above = np.clip((crest - v) / (0.26 * prof + 0.02), 0, 1)
    veil = nz.fbm(u * 5 - v * 6, v * 9 + u * 2, 5) * 0.5 + 0.5
    spray = np.exp(-above * 2.2) * (v < crest + 0.01) * prof ** 1.3 * smoothstep(0.25, 0.85, veil)
    spray *= 0.6 + 0.6 * broken
    c = mix(c, col("#e2e8ea", 0.85), np.clip(spray * 0.75, 0, 1))
    # whitewater at the foot, lace in the trough
    foot = np.exp(-((v - base) / 0.03) ** 2) * smoothstep(-0.4, 0.5, nz.fbm(u * 12, v * 20, 4))
    c = mix(c, col("#d8e2e4", 0.9), np.clip(foot * (0.4 + 0.6 * prof), 0, 1))
    front = smoothstep(base, base + 0.03, v)
    lines = 1 - smoothstep(0.0, 0.035, np.abs(nz.fbm(u * 3, v * 26 + 0.5 * nz.fbm(u * 2, v * 2, 2), 4)))
    lines *= smoothstep(-0.2, 0.4, nz.fbm(u * 10 + 4, v * 30, 3))            # broken up
    c = mix(c, col("#c8d4d8", 0.8), lines * front * 0.45)
    return c


# == render and main ====================================================================
SCENES = {
    "azure-swoosh": azure_swoosh, "azure-streaks": azure_streaks, "blue-ribbons": blue_ribbons,
    "light-rays": light_rays, "aurora-space": aurora_space, "aurora-snow": aurora_snow,
    "spiral-galaxy": spiral_galaxy, "galaxy-nebula": galaxy_nebula,
    "snowy-peaks": snowy_peaks, "dunes-day": dunes_day, "dunes-night": dunes_night,
    "granite-valley": granite_valley, "granite-cliff-dusk": granite_cliff_dusk,
    "mountain-lake": mountain_lake, "island-dusk": island_dusk, "alpine-lake": alpine_lake,
    "gradient-hills": gradient_hills, "flowing-waves": flowing_waves, "orange-bloom": orange_bloom,
    "silk-folds": silk_folds, "glass-waves": glass_waves, "coast-cliffs": coast_cliffs,
    "green-hills": green_hills, "redwood-dawn": redwood_dawn, "ocean-wave": ocean_wave,
}


def lookup(name):
    """'07', '7' or 'spiral-galaxy' -> (number, slug)."""
    for number, slug in VARIANTS:
        if name in (number, slug, str(int(number)), f"{number}-{slug}"):
            return number, slug
    raise SystemExit(f"make-orchard-wallpaper: no variant {name!r} (try --list)")


def render(w, h, variant):
    """The finished PIL RGB image of a variant ('07', 'spiral-galaxy', ...)."""
    slug = lookup(variant)[1]
    fr = Frame(w, h, slug)
    canvas = SCENES[slug](fr).astype(F32)
    return finish(canvas, f"orchard-{slug}-{w}x{h}")


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


def parse_also(items):
    """['HDMI-A-1=1080x1920', ...] -> {'HDMI-A-1': (1080, 1920)}."""
    out = {}
    for item in items or ():
        name, _, size = item.partition("=")
        try:
            w, h = (int(x) for x in size.lower().split("x"))
        except ValueError:
            raise SystemExit(f"make-orchard-wallpaper: --also wants NAME=WxH, not {item!r}")
        out[name] = (w, h)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="every variant for every monitor folder")
    ap.add_argument("--list", action="store_true", help="the variants")
    ap.add_argument("-v", "--variant", default="01", help="a number (07) or a slug (spiral-galaxy)")
    ap.add_argument("-o", "--output", help="one image to this path")
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's (logical)")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's (logical)")
    ap.add_argument("--also", action="append", metavar="NAME=WxH",
                    help="with --all: one more folder at this size (a screen not connected now)")
    a = ap.parse_args()
    if a.list:
        print("\n".join(f"{n}-{s}" for n, s in VARIANTS))
        return
    if a.all:
        sizes = dict(screens.sizes(logical=True))
        sizes.update(parse_also(a.also))
        # One image at a time, variant by variant: the memory of one render is
        # freed before the next, and the screens of a set land together.
        for number, slug in VARIANTS:
            for mon, (w, h) in sizes.items():
                write(render(w, h, slug), os.path.join(WALLDIR, mon, filename(number, slug)))
        return
    if not a.output:
        ap.error("give -o FILE, or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size(logical=True)
    write(render(a.width, a.height, a.variant), a.output)


if __name__ == "__main__":
    main()
