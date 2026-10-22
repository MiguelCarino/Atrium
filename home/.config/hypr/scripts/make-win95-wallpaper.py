#!/usr/bin/env python3
"""Render wallpapers for the win95 theme: the plain teal desktop every
Windows 95 machine started on, and blue skies with fair-weather cumulus in
the spirit of its "Clouds" start-up screen -- drawn from scratch here (puffs
and noise, below), not a copy of Microsoft's picture.

    make-win95-wallpaper.py --all          every variant, every monitor, into
                                           the slideshow folders
    make-win95-wallpaper.py -v clouds-2 -W 1720 -H 720 -o /tmp/x.png
    make-win95-wallpaper.py --list         the variants

--all writes ~/Pictures/Wallpapers/<OUTPUT>/win95-<variant>.png for every
screen connected now, each at its own size as it is seen (screens.py sizes():
a rotated, portrait screen gets a portrait picture; 1920x1080 for the primary
when Hyprland is not running): the same names in every folder, so the
screens change together (the
win95 theme's set: wallpaper_prefix=win95- in ~/.config/themes/win95/
theme.conf; `theme.py check win95` insists on matching names). Each monitor
gets its own render at its own size, not a crop, so the clouds are laid out
for that screen -- portrait included: sizes follow the short side, and the
number of clouds follows the area.

Same constraints as make-wallpaper.py, for the same reasons:
  * On an HDR screen SDR is mapped into the HDR range, so nothing gets near
    full scale: the teal is Windows 95's #008080 at DIM (~#006d6d), the sky is
    a mid blue, and the clouds' sunlit tops are capped at PEAK -- a white
    cumulus is the largest bright thing on the screen, so the skies keep
    their cover to roughly a quarter of the frame;
  * a tiny noise dither hides the banding that a big smooth sky gets in
    8-bit (the plain teal is flat on purpose: it was flat).
The theme's bar is an opaque grey strip, so unlike the glass themes there is
no quiet band to keep under it.

How a cloud is made: one to three lobes side by side, each a dome; a row of
wide low puffs under every lobe for a continuous (soft, flat on average)
base, then a few dozen soft gaussian puffs spread across the lobes, as high
as the dome allows, bigger towards the middle. Their density is SUMMED and
saturated, so where puffs overlap the core is solid and a lone puff at the
rim stays thin -- then fractal value noise erodes the edge (never the open
sky) into a wispy fringe. The light comes from above: a point is lit by its
height in the cloud (only the lower part ramps to the blue-grey base) and by
how high it sits in its own puff (the cauliflower lumps), so tops and middles
come out brightest. (Version 1 shaded by how much cloud lay ABOVE a point:
every edge, sides included, came out lit and every centre dark -- outlined,
stickers on a sky; and a jittered grid left them in rows. Now each cloud goes
at the best of a dozen random spots, farthest from the others.)

Deterministic: the same variant and size always give the same image.
Pure numpy + Pillow (both installed); under a second per ultrawide image.
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (scripts/screens.py: the screens and their sizes)

PEAK = 0.80          # brightest channel value anywhere (make-wallpaper.py: 0.78)
DIM = 0.85           # the flat teal, as a fraction of #008080

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")

# variant: None for the flat teal, else the sky:
#   top, bottom      sky colour at the top and bottom edge (RGB 0..1)
#   clouds           clouds per short-side square of picture
#   size             cloud width as a fraction of the short side (min, max)
#   lit, shade       a cloud's sunlit top and shadowed belly (RGB 0..1)
#   seed
VARIANTS = {
    "teal": None,
    # The classic: mid-blue sky, a scatter of small fair-weather clouds.
    "clouds-1": dict(top=(0.10, 0.30, 0.66), bottom=(0.34, 0.55, 0.84), clouds=5.0,
                     size=(0.20, 0.55), lit=(0.80, 0.80, 0.80), shade=(0.50, 0.58, 0.72), seed=95),
    # Bigger, fewer, higher: a summer afternoon.
    "clouds-2": dict(top=(0.08, 0.26, 0.60), bottom=(0.30, 0.52, 0.82), clouds=2.4,
                     size=(0.36, 0.70), lit=(0.80, 0.79, 0.77), shade=(0.48, 0.55, 0.70), seed=1995),
    # Late in the day: a deeper sky, peach light on the tops, lavender
    # bellies. (A grey-brown shade under a warm lit made muddy brown centres:
    # the two ends of the light ramp must both be clean colours.)
    "clouds-3": dict(top=(0.05, 0.17, 0.46), bottom=(0.30, 0.42, 0.68), clouds=3.6,
                     size=(0.26, 0.56), lit=(0.80, 0.70, 0.60), shade=(0.44, 0.45, 0.66), seed=824),
}


def value_noise(W, H, cell, rng):
    """Smooth random field, 0..1: a coarse random grid upsampled bicubically."""
    gw, gh = max(2, int(W / cell) + 2), max(2, int(H / cell) + 2)
    grid = rng.random((gh, gw), dtype=np.float32)
    img = Image.fromarray(grid, "F").resize((W, H), Image.BICUBIC)
    return np.asarray(img, np.float32)


def fbm(W, H, cell, octaves, rng):
    out = np.zeros((H, W), np.float32)
    amp, total = 1.0, 0.0
    for _ in range(octaves):
        out += amp * value_noise(W, H, cell, rng)
        total += amp
        amp *= 0.5
        cell = max(2.0, cell / 2)
    return out / total


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def cloud_shape(width, rng, q):
    """One cumulus on its own quarter-scale canvas: (density 0..1, light 0..1,
    x of its centre, y of its baseline, in canvas px).

    Built from a few dozen soft gaussian puffs rather than a row of hard
    discs (that read as a sticker): scattered under a dome that is tallest in
    the middle, bigger towards the centre, their density SUMMED and then
    saturated, so overlapping puffs make a solid core and the lone ones at
    the rim stay thin and see-through -- a wispy edge, not an outline.

    The light, 1 = the sunlit colour, 0 = the shadowed base. Two parts, both
    from above, both brightest at the top and the middle:
      * height in the cloud: the lowest ~half, above the baseline, ramps
        down to the blue-grey base; everything higher is in the sun;
      * each puff's own top: its upper half lighter than its lower half,
        averaged over the puffs by their density, which draws the
        cauliflower lumps without darkening the core.
    (The old shading measured how much cloud lay ABOVE a point, which made
    every edge -- sides included -- bright and every centre dark: an
    inverted, outlined look.)"""
    wq = width / q
    w = max(8, int(wq * 1.6))
    h = max(8, int(wq * 0.80))
    cx, base = w / 2, h * 0.82
    dome = wq * rng.uniform(0.26, 0.42)              # the cloud's height
    X = np.arange(w, dtype=np.float32)[None, :]
    Y = np.arange(h, dtype=np.float32)[:, None]
    dens = np.zeros((h, w), np.float32)
    lsum = np.zeros((h, w), np.float32)
    # One to three lobes (towers) side by side, each its own dome: a single
    # dome per cloud made every cloud the same bun.
    lobes = []
    for _ in range(int(rng.integers(1, 4))):
        lobes.append((rng.uniform(-0.32, 0.32), rng.uniform(0.24, 0.44),
                      rng.uniform(0.55, 1.0)))

    def puff(x, y, r):
        nonlocal dens, lsum
        sig = r * 0.62
        g = np.exp(-((X - x) ** 2 + (Y - y) ** 2) / (2.0 * sig * sig))
        dens += g
        lsum += g * np.clip(0.55 + 0.45 * (y - Y) / r, 0.0, 1.0)

    # The base: a row of wide, low puffs under every lobe, end to end, so the
    # cloud sits on one continuous bottom. Without it the puffs at a lobe's
    # ends (which the dome leaves at the baseline) stood alone beside the
    # cloud like bubbles.
    for lc, lw, _lh in lobes:
        steps = max(3, int(lw * 14))
        for k in range(steps):
            u = lc + (k / (steps - 1) * 2.0 - 1.0) * lw * 0.85
            r = wq * rng.uniform(0.07, 0.10)
            puff(cx + u * wq, base - r * rng.uniform(0.5, 0.8), r)
    # The body: puffs spread evenly across each lobe, as high as its dome
    # allows there, bigger towards the middle.
    for _ in range(int(rng.integers(40, 80))):
        lc, lw, lh = lobes[int(rng.integers(len(lobes)))]
        v = rng.uniform(-0.85, 0.85)                                 # across the lobe
        top = dome * lh * (1.0 - v * v) ** 0.6 * rng.uniform(0.75, 1.1)
        r = wq * rng.uniform(0.05, 0.11) * (0.65 + 0.5 * (1.0 - abs(v)))
        puff(cx + (lc + v * lw) * wq,
             base - max(r * 0.6, rng.uniform(0.15, 1.0) ** 0.7 * top), r)
    puff_light = lsum / np.maximum(dens, 1e-4)
    # The base, soft: a ramp that starts a little above the baseline and
    # reaches nothing well below it -- flat on average, never a ruled line.
    dens *= 1.0 - smoothstep(base - 0.02 * wq, base + 0.10 * wq, Y)
    m = 1.0 - np.exp(-1.6 * dens)
    height_light = smoothstep(0.0, 0.45, (base - Y) / dome)
    light = np.clip(0.45 * height_light + 0.55 * puff_light * (0.35 + 0.65 * height_light), 0.0, 1.0)
    return m, light, cx, base


def sky(W, H, spec):
    rng = np.random.default_rng(spec["seed"])
    short = min(W, H)
    # Clouds are built on a quarter-size canvas (they are soft anyway), then
    # scaled up; only the noise and the colour run at full size.
    q = 4
    w4, h4 = W // q + 1, H // q + 1
    mask = np.zeros((h4, w4), np.float32)
    light = np.ones((h4, w4), np.float32)
    n = max(2, int(round(spec["clouds"] * W * H / short ** 2)))
    # Sizes skewed towards small (u ** 1.3): a few big clouds and many small
    # ones, the way a real sky looks -- equal-sized clouds read as a pattern.
    lo, hi = spec["size"]
    widths = sorted((lo + (hi - lo) * rng.random() ** 1.3) * short for _ in range(n))[::-1]
    # Placed biggest first, each at the best of a dozen random spots: the one
    # farthest from the clouds already there (Mitchell's best candidate).
    # Even cover without a pattern -- a jittered grid left the clouds in
    # visible rows, pure chance bunched them.
    centres = []
    for width in widths:
        if H > W:
            # Portrait: the short side is the WIDTH, and a cloud sized from
            # it spans the screen edge to edge -- a band, not a cloud. (The
            # puffs fill ~70% of a cloud's nominal width, so 0.9 tops out
            # under half the screen.)
            width *= 0.9
        m, lt, mcx, mbase = cloud_shape(width, rng, q)
        mh, mw = m.shape
        best, best_d = None, -1.0
        for _ in range(12):
            x = rng.uniform(-0.05, 1.05) * W
            y = rng.uniform(0.12, 0.95) * H
            d = min((((x - cx) / 1.6) ** 2 + (y - cy) ** 2 for cx, cy in centres),
                    default=0.0)
            if d > best_d:
                best, best_d = (x, y), d
        centres.append(best)
        x0 = int(best[0] / q - mcx)
        y0 = int(best[1] / q - mbase)
        ys, xs = max(0, y0), max(0, x0)
        ye, xe = min(h4, y0 + mh), min(w4, x0 + mw)
        if ys < ye and xs < xe:
            mm = m[ys - y0:ye - y0, xs - x0:xe - x0]
            ll = lt[ys - y0:ye - y0, xs - x0:xe - x0]
            region, lregion = mask[ys:ye, xs:xe], light[ys:ye, xs:xe]
            # Two clouds that touch merge, never add up into a hot spot: the
            # density is the max, and each pixel takes the light of whichever
            # cloud is denser there.
            take = mm > region
            lregion[take] = ll[take]
            np.maximum(region, mm, out=region)
    m = np.asarray(Image.fromarray(mask, "F").resize((W, H), Image.BICUBIC), np.float32)
    lt = np.asarray(Image.fromarray(light, "F").resize((W, H), Image.BICUBIC), np.float32)

    # Ragged, wispy edges: the soft shapes eroded by fractal noise -- big
    # cells for the lumps, small ones for the fringe. Only the edge moves (the
    # noise is scaled by how far from solid the mask is), the cores stay
    # whole; the wide smoothstep leaves a long thin fringe, not a rim.
    noise = fbm(W, H, 0.05 * short, 6, rng)
    # Erode only: where there is no cloud the noise must not make one (it
    # sprinkled faint specks across the open sky).
    m = np.minimum(m - (1.0 - m) * 1.1 * (noise - 0.42), m * 3.0)
    dens = smoothstep(0.08, 0.75, m)
    # A little of the same noise in the light: sunlit cumulus is not one flat
    # white.
    lt = np.clip(lt + 0.25 * (noise - 0.5), 0.0, 1.0)

    lit = np.asarray(spec["lit"], np.float32)
    shade = np.asarray(spec["shade"], np.float32)
    cloud = shade + (lit - shade) * lt[..., None]

    yy = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    top = np.asarray(spec["top"], np.float32)
    bottom = np.asarray(spec["bottom"], np.float32)
    bg = np.broadcast_to(top + (bottom - top) * yy ** 0.9, (H, W, 3))
    out = bg + (cloud - bg) * dens[..., None]

    out = np.clip(out, 0.0, PEAK)
    px = out * 255.0 + np.random.default_rng(spec["seed"]).uniform(-0.5, 0.5, out.shape)
    return Image.fromarray(np.clip(np.rint(px), 0, 255).astype(np.uint8), "RGB")


def render(W, H, variant):
    spec = VARIANTS[variant]
    if spec is None:
        teal = tuple(int(round(c * DIM)) for c in (0x00, 0x80, 0x80))
        return Image.new("RGB", (W, H), teal)
    return sky(W, H, spec)


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
    ap.add_argument("-v", "--variant", default="clouds-1", choices=sorted(VARIANTS))
    ap.add_argument("-o", "--output", help="one image to this path")
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's")
    a = ap.parse_args()
    if a.list:
        print("\n".join(VARIANTS))
        return
    if a.all:
        # One image at a time: a 3440x1440 float canvas is ~60 MB, and this
        # box is shared.
        for variant in VARIANTS:
            for mon, (w, h) in screens.sizes().items():
                write(render(w, h, variant), os.path.join(WALLDIR, mon, f"win95-{variant}.png"))
        return
    if not a.output:
        ap.error("give -o FILE, or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size()
    if a.width <= 0 or a.height <= 0:
        ap.error("width/height must be positive")
    write(render(a.width, a.height, a.variant), a.output)


if __name__ == "__main__":
    main()
