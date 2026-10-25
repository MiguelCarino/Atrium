#!/usr/bin/env python3
"""Render wallpapers for the seasons theme: three scenes for each season, all
at blue hour, dusk or night with a few lit details -- an orchard in blossom,
a forest edge full of fireflies, a maple grove dropping its leaves, a pine
forest under a dim aurora -- drawn from scratch here (stepped silhouettes,
discs, catenaries, particles and gradients), not copies of any photograph or
anybody's art, with no people and no place anyone could name.

    make-seasons-wallpaper.py --all             all 12, every monitor, into
                                                the slideshow folders
    make-seasons-wallpaper.py --season autumn   that season's 3, every monitor
    make-seasons-wallpaper.py -v winter-lake -W 1720 -H 720 -o /tmp/x.png
    make-seasons-wallpaper.py --list            the variants

--all and --season write ~/Pictures/Wallpapers/<OUTPUT>/seasons-<season>-
<variant>.png for every screen connected now at its LOGICAL size (screens.py,
as make-lofi-wallpaper.py does; 1920x1080 for the primary when Hyprland is
not running), the same names in every folder, so the screens change together.
Each season's theme.conf (themes/seasons/season/<s>/) sets
wallpaper_prefix=seasons-<s>-, so the slideshow shows only the season it is;
`theme.py check seasons` insists on matching names.

Variants:
    spring-orchard   rows of blossoming trees at blue hour, petals drifting,
                     a dark fresh-green meadow and the first star
    spring-meadow    rolling hills in layered greens under a lilac dusk,
                     wildflower specks, a thin crescent moon, soft clouds
    spring-shower    a shower over a pond: fine slanted rain, ripples, lily
                     pads, reeds, a blossom branch across one upper corner
    summer-canopy    a deep green forest edge at dusk: layered treelines, a
                     gold last light on the horizon, fireflies in the
                     undergrowth
    summer-coast     a cove at the end of sunset: the sun a capped half-disc
                     on the sea, its gold path, teal shallows, dune grass,
                     the first stars
    summer-field     sunflowers in silhouette under a summer night, the
                     Milky Way a soft band, a warm glow along the horizon
    autumn-maples    a maple grove: amber and rust crowns, leaves falling, a
                     leaf-strewn path, dusk mist between the trunks
    autumn-harvest   low hills, hay bales and pumpkins, a low harvest moon
                     behind a bare tree, a rust horizon
    autumn-mist      a river valley in fog: rust and umber hills fading into
                     mist bands, a still river holding a copper sky
    winter-pines     a snowy pine forest at night: stepped pines with snow
                     lips, a dim frost-and-silver aurora, moonlit snow
    winter-lake      a frozen lake under a silver moon: far mountains, ice
                     with cracks, the moon's path on it
    winter-snowfall  snow falling in three depths over hills, a lone cabin
                     with one warm window and its smoke

The rules, as in make-lofi-wallpaper.py, for the same reasons:
  * DP-1 is HDR, where SDR is mapped up into the HDR range: every channel is
    capped at PEAK (a colour scaled down whole, not clipped), the big fields
    (skies) are held under SKY_LUM, water under WATER_LUM, and snow -- the
    biggest light field this theme has -- under SNOW_LUM, darker than the
    sky: moonlit blue snow, not daylight white (field()).
  * Light accents (the sun's half-disc, the moons, lit windows, fireflies,
    close blossoms) each cover at most about 1.5% of the frame, all of them
    together at most about 6%.
  * The bar's pills sit over the top TOP_BAND (106) px, and the bar's
    contrast numbers assume it dark: every sky starts at its DARKEST stop,
    held flat to 106 px (sky()); detail fades in below QUIET over FADE px
    (detail_band()), and nothing bright reaches into the band at all
    (clear_band()). That band keeps mean luminance <= 0.03 and no channel
    over 0.27.
  * finish(): a vignette (x 1 - 0.18 r^2), a faint luminance-only grain
    (sigma 0.008, finer than lofi's 0.010: these are painted scenes, not a
    dusty room), the PEAK cap, and a +-0.5 LSB dither.
Sizes follow the short side (k = short / 1440), so a petal or a firefly is
about the same physical size on every screen, portrait included; layout uses
fractions of W and H.

The accent does not follow the wallpaper (accent_follow=no: each season's
accent is fixed and measured against its status colours), but the pictures
are still built so theme-from-wallpaper.py's hue vote lands on the season's
accent family or a cool hue -- never the bad red [340, 15] degrees -- in case
the user turns following on. `theme-from-wallpaper.py pick` on the DP-1 set
(3440x1440), 2026-10-24:
    spring-orchard   #2e5dff  (hue 227)    summer-canopy   #2e8fff  (hue 212)
    spring-meadow    #794eff  (hue 255)    summer-coast    #3f59ff  (hue 232)
    spring-shower    #2ea6ff  (hue 206)    summer-field    #3f58ff  (hue 232)
    autumn-maples    #ff852e  (hue  25)    winter-pines    #2e6fff  (hue 221)
    autumn-harvest   #7a4eff  (hue 255)    winter-lake     #2e68ff  (hue 223)
    autumn-mist      #ff8e2e  (hue  28)    winter-snowfall #2e6fff  (hue 221)
The two copper votes are the autumn accent's own family (#ee9a62, hue 24).
Their rusts were first drawn redder and voted hue 15-16, on the edge of the
bad range, so the crowns, mist and river were moved to the amber side of
rust (hue 21-30). Measured on all 48 files (four screens), WCAG luminance:
the top 106 px have mean luminance 0.0025-0.0051 and no channel over 0.161
(spring-meadow's lilac); pixels over 0.5 luminance (the light accents) cover
at most 0.12% of a frame (winter-lake's moon), and over 0.2 at most 2.2%.

Deterministic: the same variant and size always give the same image.
Pure numpy + Pillow; about 2-3 s per ultrawide image, --all (12 scenes on
four screens) 1.5-2 minutes in one process, peak memory about 550 MB.
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

PEAK = 0.80          # brightest channel value anywhere (lofi: 0.80)
SKY_LUM = 0.45       # ceiling for the luminance of the big fields (skies)
WATER_LUM = 0.35     # sea, pond, river and lake fields
SNOW_LUM = 0.30      # snow fields: the biggest light field, held darker than the sky
QUIET = 36           # px under the bar with no detail at all (the bar's height)
FADE = 70            # px over which the detail fades in below that
TOP_BAND = QUIET + FADE   # 106: the band the pills' contrast numbers cover
GRAIN = 0.008        # grain sigma, in 0..1 luminance (lofi: 0.010)

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
SEASONS = ("spring", "summer", "autumn", "winter")
VARIANTS = ["spring-orchard", "spring-meadow", "spring-shower",
            "summer-canopy", "summer-coast", "summer-field",
            "autumn-maples", "autumn-harvest", "autumn-mist",
            "winter-pines", "winter-lake", "winter-snowfall"]

# The season accents (themes/seasons/season/<s>/theme.conf) and a few of
# their kin, used for the small lit details.
BLOSSOM, BLOSSOM_DK = "#f4a8d0", "#7a3e62"
LAGOON, SUN_GOLD = "#5ccfd6", "#ecd27a"
COPPER, AMBER, RUST = "#ee9a62", "#c8782e", "#8a4420"
FROST, SILVER = "#8ccaf2", "#c4ccd8"
WARM_WINDOW = "#f2c48a"
STARLIGHT = "#e6e8f2"


def logical_sizes():
    """{output: (W, H)} as Hyprland lays the monitors out (screens.py)."""
    return screens.sizes(logical=True)


# -- colour helpers (make-lofi-wallpaper.py's, kept local) -------------------------
def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def rgba(h, a=1.0):
    """'#rrggbb' -> a PIL fill tuple with alpha a (0..1)."""
    return tuple(int(round(v * 255)) for v in hexc(h)) + (int(round(255 * a)),)


def lum(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def field(h, ceiling, a=1.0):
    """rgba(h, a), scaled down whole so its luminance is at most `ceiling`:
    for the snow and water fields (SNOW_LUM, WATER_LUM)."""
    c = hexc(h)
    c = c / max(1.0, float(lum(c)) / ceiling)
    return tuple(int(round(v * 255)) for v in c) + (int(round(255 * a)),)


def ramp(t, stops):
    pos = [p for p, _ in stops]
    cols = np.stack([hexc(c) for _, c in stops])
    return np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], -1).astype(np.float32)


def sky(W, H, stops, ceiling=SKY_LUM):
    """A gradient top -> bottom, luminance held under `ceiling`. The stops are
    fractions of H, darkest first, and the darkest is held flat down to
    TOP_BAND px before the gradient starts (the bar's pills sit there)."""
    pos = [p * (H - 1) for p, _ in stops]
    cols = [c for _, c in stops]
    hold = min(TOP_BAND, 0.25 * (H - 1))
    if len(pos) > 1 and pos[1] > hold + 1:
        pos.insert(1, hold)
        cols.insert(1, cols[0])
    t = np.arange(H, dtype=np.float32)
    col = ramp(t, list(zip(pos, cols)))
    col = col / np.maximum(lum(col) / ceiling, 1.0)[..., None]
    return np.broadcast_to(col[:, None, :], (H, W, 3)).copy()


def over(canvas, layer):
    a = layer[..., 3:4]
    return canvas * (1 - a) + layer[..., :3] * a


def pil_layer(img):
    return np.asarray(img, np.float32) / 255.0


def new_layer(W, H):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def blur_rgba(img, radius):
    """Gaussian blur in PREMULTIPLIED form, so a disc's transparent black
    surround does not bleed a dark rim into it. Returns a float RGBA layer."""
    a = np.asarray(img, np.float32) / 255
    if radius <= 0.3:
        return a
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
    """0 down to TOP_BAND, rising to 1 over the next 24 px: for the BRIGHT
    details, which must not reach into the band at all."""
    yy = np.arange(H, dtype=np.float32)[:, None, None]
    return np.clip((yy - TOP_BAND) / 24.0, 0.0, 1.0)


def put(canvas, layer, band):
    layer = layer.copy()
    layer[..., 3:4] *= band
    return over(canvas, layer)


def glow(canvas, cx, cy, radius, colour, alpha, power=2.0, sy=1.0):
    """A soft radial light (squashed vertically by sy < 1)."""
    H, W = canvas.shape[:2]
    y0, y1 = max(0, int(cy - radius * sy)), min(H, int(cy + radius * sy) + 1)
    x0, x1 = max(0, int(cx - radius)), min(W, int(cx + radius) + 1)
    if y0 >= y1 or x0 >= x1:
        return canvas
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    a = np.clip(1 - np.hypot(xx - cx, (yy - cy) / sy) / radius, 0, 1) ** power * alpha
    sub = canvas[y0:y1, x0:x1]
    canvas[y0:y1, x0:x1] = sub * (1 - a[..., None]) + hexc(colour) * a[..., None]
    return canvas


def disc(canvas, cx, cy, r, colour, k, bite=None, below=None):
    """A soft-edged disc (a moon, a sun). bite=(dx, dy, r2) takes a disc out
    (a crescent); below=y hides everything under y (a sun on the sea)."""
    H, W = canvas.shape[:2]
    y0, y1 = max(0, int(cy - r - 3)), min(H, int(cy + r + 4))
    x0, x1 = max(0, int(cx - r - 3)), min(W, int(cx + r + 4))
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    m = np.clip((r - np.hypot(xx - cx, yy - cy)) / (1.5 * k), 0, 1)
    if bite:
        dx, dy, r2 = bite
        m = np.clip(m - np.clip((r2 - np.hypot(xx - cx - dx, yy - cy - dy)) / (1.5 * k), 0, 1), 0, 1)
    if below is not None:
        m = m * np.clip((below - yy) / (1.2 * k), 0, 1)
    sub = canvas[y0:y1, x0:x1]
    canvas[y0:y1, x0:x1] = sub * (1 - m[..., None]) + hexc(colour) * m[..., None]
    return canvas


# -- shared scenery -----------------------------------------------------------------
def ridge(W, rng, base, amp, waves=(1.0, 2.3, 4.7, 9.1), n=320):
    """A rolling skyline: (x, y) points, base +- amp, a few sines summed."""
    xs = np.linspace(-0.02 * W, 1.02 * W, n)
    y = np.full_like(xs, base)
    for i, f in enumerate(waves):
        y += amp * rng.uniform(0.5, 1.0) / (i + 1) ** 0.9 * np.sin(2 * np.pi * f * xs / W + rng.uniform(0, 6.28))
    return list(zip(xs.tolist(), y.tolist()))


def peaks(W, rng, base, height, n):
    """A mountain range: straight slopes between random peaks and saddles."""
    pts, x = [(-0.02 * W, base)], -0.02 * W
    while x < 1.02 * W:
        x += W / n * rng.uniform(0.5, 1.2)
        pts.append((x, base - height * rng.uniform(0.45, 1.0)))
        x += W / n * rng.uniform(0.3, 0.8)
        pts.append((x, base - height * rng.uniform(0.05, 0.35)))
    return pts


def fill_below(d, W, H, pts, fill):
    d.polygon(pts + [(1.02 * W, H + 2), (-0.02 * W, H + 2)], fill=fill)


def hill(W, H, rng, k, base, amp, colour, waves=(1.0, 2.3, 4.7, 9.1), a=1.0, cap=None):
    img, d = new_layer(W, H)
    fill_below(d, W, H, ridge(W, rng, base, amp, waves), field(colour, cap, a) if cap else rgba(colour, a))
    return blur_rgba(img, 0.6 * k)


def branches(d, x, y, ang, length, width, depth, rng, fill, tips, spread=0.45):
    """A tree's limbs, recursively: each limb forks into two or three shorter
    ones. The tips (x, y) are collected, for crowns, blossoms and snow."""
    x1, y1 = x + length * math.cos(ang), y - length * math.sin(ang)
    d.line([(x, y), (x1, y1)], fill=fill, width=max(1, int(width)))
    if depth == 0:
        tips.append((x1, y1))
        return
    for i in range(rng.choice((2, 2, 3))):
        # the first fork leans left, the second right, a third goes on
        a = ang + rng.uniform(-spread, spread) + (0.8 * spread, -0.8 * spread, 0.0)[i]
        branches(d, x1, y1, a, length * rng.uniform(0.62, 0.78), width * 0.68, depth - 1, rng, fill, tips, spread)


def tree(d, x, ground, h, k, rng, trunk, depth=4, bole=0.38, limb=0.26, spread=0.45):
    """A broadleaf tree's trunk (bole: its share of h) and limbs (limb: the
    first one's share); returns the twig tips. A bare tree wants a shorter
    bole, longer limbs and a wider spread, or it is a pole with a tuft."""
    tips = []
    w = max(3, h * 0.07)
    d.polygon([(x - w * 0.8, ground), (x + w * 0.8, ground), (x + w * 0.4, ground - h * bole),
               (x - w * 0.4, ground - h * bole)], fill=trunk)
    branches(d, x, ground - h * (bole - 0.02), math.pi / 2 + rng.uniform(-0.1, 0.1), h * limb, w * 0.75, depth,
             rng, trunk, tips, spread)
    return tips


def crown(d, tips, k, rng, colours, r=(9, 22), per=4, a=(0.75, 0.95), mass=None):
    """Clustered discs round each twig tip: a blossom, leaf or autumn crown.
    mass='#rrggbb' first fills the crown's core with a few big darker discs
    between the tips -- without it a crown is a ring of tufts on bare limbs
    and the tree reads as a lollipop."""
    if mass and tips:
        xs, ys = [t[0] for t in tips], [t[1] for t in tips]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        rx, ry = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
        for _ in range(7):
            ex, ey = cx + rng.uniform(-0.55, 0.55) * rx, cy + rng.uniform(-0.3, 0.45) * ry
            er = max(rx, ry) * rng.uniform(0.35, 0.55)
            d.ellipse([ex - er, ey - er * 0.8, ex + er, ey + er * 0.8], fill=rgba(mass, 0.95))
    for tx, ty in tips:
        for _ in range(per):
            rr = rng.uniform(*r) * k
            cx, cy = tx + rng.uniform(-1.6, 1.6) * rr, ty + rng.uniform(-1.4, 1.2) * rr
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=rgba(rng.choice(colours), rng.uniform(*a)))


def pine(d, x, base, h, w, k, fill, snow=None, tiers=5):
    """A stepped pine: stacked triangles narrowing upwards on a short trunk;
    snow=colour adds a lip of snow along each tier's lower edge and a cap."""
    d.rectangle([x - w * 0.05, base - h * 0.14, x + w * 0.05, base], fill=fill)
    for i in range(tiers):
        f = i / tiers
        yb = base - h * 0.12 - h * 0.78 * f
        hw = w * 0.5 * (1 - 0.78 * f)
        th = h * 0.30
        d.polygon([(x - hw, yb), (x + hw, yb), (x, yb - th)], fill=fill)
        if snow:
            lip = max(2, 4 * k)
            d.polygon([(x - hw, yb), (x + hw, yb), (x + hw * 0.78, yb - lip), (x - hw * 0.78, yb - lip)], fill=snow)
    if snow:
        top = base - h * 0.12 - h * 0.78 * (tiers - 1) / tiers - h * 0.30
        d.polygon([(x - 6 * k, top + 9 * k), (x + 6 * k, top + 9 * k), (x, top)], fill=snow)


def stars(W, H, rng, k, density, y0, y1, amax=0.7, colour=STARLIGHT):
    img, d = new_layer(W, H)
    for _ in range(int(density * W * max(0, y1 - y0))):
        x, y = rng.uniform(0, W), rng.uniform(y0, y1)
        r = rng.choice((0.6, 0.8, 1.0, 1.4)) * k
        d.ellipse([x - r, y - r, x + r, y + r], fill=rgba(colour, rng.uniform(0.2, amax)))
    return blur_rgba(img, 0.35 * k)


def clouds(W, H, rng, k, n, colour, alpha, y0, y1):
    img, d = new_layer(W, H)
    for _ in range(n):
        cx, cy = rng.uniform(0, W), rng.uniform(y0, y1)
        width = rng.uniform(260, 520) * k
        for _ in range(10):
            r = rng.uniform(0.15, 0.28) * width
            x = cx + rng.uniform(-0.5, 0.5) * width
            y = cy - rng.uniform(0, 0.18) * width * (1 - abs(x - cx) / width)
            d.ellipse([x - r, y - r * 0.55, x + r, y + r * 0.45], fill=rgba(colour, alpha))
    return blur_rgba(img, 14 * k)


def mist(W, H, k, y, height, colour, alpha):
    """A horizontal fog band centred on y: alpha falls off as a Gaussian."""
    out = np.zeros((H, W, 4), np.float32)
    yy = np.arange(H, dtype=np.float32)
    out[..., :3] = hexc(colour)
    out[..., 3] = (alpha * np.exp(-((yy - y) / height) ** 2))[:, None]
    return out


def flakes(W, H, rng, k, n, r, alpha, colour, y0, blur):
    """Particles: snow, pollen, distant petals. Discs, blurred by depth."""
    img, d = new_layer(W, H)
    for _ in range(n):
        x, y, rr = rng.uniform(0, W), rng.uniform(y0, H), rng.uniform(*r) * k
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=rgba(colour, rng.uniform(*alpha)))
    return blur_rgba(img, blur * k)


def leaves(W, H, rng, k, n, colours, y0, y1, size=(4, 9), a=(0.6, 0.9)):
    """Falling leaves or petals: small rotated diamonds (a leaf's outline at
    this size), each turned its own way."""
    img, d = new_layer(W, H)
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(y0, y1)
        s, th = rng.uniform(*size) * k, rng.uniform(0, math.pi)
        c, sn = math.cos(th), math.sin(th)
        pts = [(x + c * s, y + sn * s), (x - sn * s * 0.45, y + c * s * 0.45),
               (x - c * s, y - sn * s), (x + sn * s * 0.45, y - c * s * 0.45)]
        d.polygon(pts, fill=rgba(rng.choice(colours), rng.uniform(*a)))
    return blur_rgba(img, 0.5 * k)


def fireflies(canvas, W, H, rng, k, n, y0, y1, clear):
    """Warm yellow-green specks, each with a small halo."""
    halo, dh = new_layer(W, H)
    core, dc = new_layer(W, H)
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(y0, y1)
        r = rng.uniform(1.4, 2.6) * k
        dh.ellipse([x - 7 * r, y - 7 * r, x + 7 * r, y + 7 * r], fill=rgba("#c8d860", rng.uniform(0.10, 0.22)))
        dc.ellipse([x - r, y - r, x + r, y + r], fill=rgba("#e6f08a", rng.uniform(0.7, 0.95)))
    canvas = put(canvas, blur_rgba(halo, 6 * k), clear)
    return put(canvas, blur_rgba(core, 0.6 * k), clear)


def wisps(W, H, rng, k, x, y, height, colour="#8a94a8", n=3, a=0.10):
    """Smoke or steam: soft sine curves rising and drifting right."""
    img, d = new_layer(W, H)
    for i in range(n):
        ph = rng.uniform(0, 6.28)
        pts = [(x + (i - 1) * 6 * k + 9 * k * math.sin(ph + s * 5.0) * (0.4 + s) + 60 * k * s * s,
                y - s * height) for s in np.linspace(0, 1, 48)]
        d.line(pts, fill=rgba(colour, a), width=max(1, int(5 * k)))
    return blur_rgba(img, 3 * k)


def grass(d, W, base, k, rng, fill, n, h=(20, 60), lean=0.3):
    """Blades: thin slanted lines rising from y=base."""
    for _ in range(n):
        x = rng.uniform(0, W)
        L = rng.uniform(*h) * k
        a = math.pi / 2 + rng.uniform(-lean, lean)
        d.line([(x, base), (x + L * math.cos(a), base - L * math.sin(a))], fill=fill, width=max(1, int(2 * k)))


# -- spring --------------------------------------------------------------------------
def spring_orchard(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#0c1020"), (0.45, "#1e2848"), (0.78, "#3c3c64"), (1.0, "#4a4468")])
    canvas = put(canvas, stars(W, H, rng, k, 0.00005, TOP_BAND, 0.5 * H, 0.5), band * clear)
    # the first star: one brighter point with a little halo
    sx, sy = 0.72 * W, max(0.22 * H, TOP_BAND + 60 * k)
    canvas = glow(canvas, sx, sy, 16 * k, "#dfe4f4", 0.35)
    canvas = disc(canvas, sx, sy, 2.2 * k, "#eef0f8", k)
    ground = 0.80 * H
    canvas = put(canvas, hill(W, H, rng, k, 0.70 * H, 0.03 * H, "#1a2a2a"), band)
    # three rows of trees, far first: smaller, hazier, closer together
    for row, (gy, scale, trunk, cols, step) in enumerate((
            (0.72, 0.42, "#1a2230", ("#3e3250", "#5a4262", "#6a4a6c"), 150),
            (0.77, 0.62, "#141a22", ("#56344e", "#7e4a6c", "#965a7e"), 210),
            (0.86, 0.95, "#0e1218", ("#5e2e4c", BLOSSOM_DK, "#9a5278", "#b8668e", "#d88cb2"), 330))):
        img, d = new_layer(W, H)
        x = rng.uniform(-0.5, 0.5) * step * k
        while x < W + step * k:
            h = rng.uniform(0.85, 1.1) * scale * 0.42 * H
            tips = tree(d, x, gy * H, h, k, rng, rgba(trunk), depth=4)
            crown(d, tips, k * scale, rng, cols, r=(14, 30), per=4, mass=cols[0])
            x += step * k * rng.uniform(0.85, 1.15)
        canvas = put(canvas, blur_rgba(img, (1.6 - row * 0.6) * k), band)
    # the meadow under the near row
    img, d = new_layer(W, H)
    fill_below(d, W, H, ridge(W, rng, ground + 0.04 * H, 0.01 * H), rgba("#1c3a24"))
    grass(d, W, ground + 0.05 * H, k, rng, rgba("#24452c"), int(W / (4 * k)), (12, 34))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    # petals drifting across the frame: a few close and light, more far and dim
    canvas = put(canvas, leaves(W, H, rng, k, int(260 * W / 3440) + 40, ("#c27ea2", "#a8688c", "#e0a6c4"),
                                TOP_BAND + 30 * k, H, size=(2.5, 5), a=(0.35, 0.75)), band * clear)
    return canvas


def spring_meadow(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#100e22"), (0.40, "#2a2448"), (0.72, "#5a4876"), (1.0, "#6e5682")])
    canvas = put(canvas, clouds(W, H, rng, k, 6, "#6a5888", 0.28, 0.30 * H, 0.55 * H), band)
    mx, my = 0.22 * W, max(0.20 * H, TOP_BAND + 70 * k)
    canvas = glow(canvas, mx, my, 120 * k, "#b8a8e0", 0.10)
    canvas = disc(canvas, mx, my, 26 * k, "#ece6d8", k, bite=(9 * k, -5 * k, 25 * k))
    for base, amp, col in ((0.64, 0.05, "#26304a"), (0.72, 0.05, "#1e3a32"),
                           (0.80, 0.045, "#183424"), (0.90, 0.04, "#122a1c")):
        canvas = put(canvas, hill(W, H, rng, k, base * H, amp * H, col), band)
    # wildflowers in the foreground grass: pink, white and lilac specks,
    # thicker (and a little bigger) near the bottom
    img, d = new_layer(W, H)
    grass(d, W, H, k, rng, rgba("#16301e"), int(W / (3 * k)), (30, 90))
    for _ in range(int(900 * W / 3440) + 80):
        y = 0.82 * H + (H - 0.82 * H) * math.sqrt(rng.random())
        x = rng.uniform(0, W)
        r = (1.2 + 2.2 * (y - 0.82 * H) / (0.18 * H)) * k
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=rgba(rng.choice(("#d892b8", "#cfd0dc", "#a898d8", "#e0a8c8")), rng.uniform(0.45, 0.85)))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band * clear)
    return canvas


def spring_shower(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#0c1218"), (0.45, "#1e2a36"), (0.70, "#2e3c48")])
    canvas = put(canvas, clouds(W, H, rng, k, 8, "#2e3a48", 0.45, 0.18 * H, 0.45 * H), band)
    shore = 0.62 * H
    canvas = put(canvas, hill(W, H, rng, k, shore - 0.03 * H, 0.03 * H, "#1a2c26"), band)
    # the pond: a dark water field holding a little of the sky
    pond = np.zeros((H, W, 4), np.float32)
    yy = np.arange(H, dtype=np.float32)
    pond[..., :3] = ramp(yy, [(shore, "#26343e"), (H, "#101a20")])[:, None, :]
    pond[..., :3] /= np.maximum(lum(pond[..., :3]) / WATER_LUM, 1.0)[..., None]
    pond[..., 3] = (yy >= shore)[:, None]
    canvas = over(canvas, pond)
    img, d = new_layer(W, H)
    # ripples where the drops land: thin ellipses, flatter further away
    for _ in range(int(140 * W / 3440) + 20):
        y = shore + (H - shore) * rng.random() ** 0.8
        x = rng.uniform(0, W)
        depth = (y - shore) / (H - shore)
        for j in range(rng.choice((1, 2, 3))):
            rx = (8 + 14 * j) * k * (0.4 + depth)
            d.ellipse([x - rx, y - rx * 0.22, x + rx, y + rx * 0.22], outline=rgba("#6a7c8c", 0.32 - 0.08 * j),
                      width=max(1, int(1.2 * k)))
    # lily pads: dark discs with a notch, flattened by the view
    for _ in range(14):
        y = shore + (H - shore) * rng.uniform(0.2, 0.95)
        x = rng.uniform(0.05, 0.95) * W
        rx = rng.uniform(26, 50) * k * (0.5 + (y - shore) / (H - shore))
        a0 = rng.uniform(0, 360)
        d.pieslice([x - rx, y - rx * 0.35, x + rx, y + rx * 0.35], a0 + 20, a0 + 340, fill=rgba("#1e3a26"))
        if rng.random() < 0.3:
            d.ellipse([x - 4 * k, y - 3 * k, x + 4 * k, y + 3 * k], fill=rgba("#d8a0c0", 0.8))   # a bud
    # reeds and cattails at both sides, in silhouette
    for side in (0, 1):
        for _ in range(26):
            x = (rng.uniform(0, 0.14) if side == 0 else rng.uniform(0.86, 1.0)) * W
            base = H + 4
            L = rng.uniform(0.16, 0.34) * H
            a = math.pi / 2 + rng.uniform(-0.12, 0.12)
            tx, ty = x + L * math.cos(a), base - L * math.sin(a)
            d.line([(x, base), (tx, ty)], fill=rgba("#0c1410"), width=max(1, int(3 * k)))
            if rng.random() < 0.4:
                d.rounded_rectangle([tx - 4 * k, ty + 6 * k, tx + 4 * k, ty + 34 * k], radius=4 * k,
                                    fill=rgba("#1a140e"))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    # the blossom branch across the top-left corner, kept under the band
    img, d = new_layer(W, H)
    y0 = TOP_BAND + 40 * k
    pts, tips = [], []
    for i in range(9):
        t = i / 8
        pts.append((-10 * k + t * 0.30 * W, y0 + 40 * k * math.sin(t * 2.4) + t * 60 * k))
    d.line(pts, fill=rgba("#140e12"), width=max(2, int(12 * k)), joint="curve")
    for (px, py) in pts[1:]:
        for s in (-1, 1):
            tx, ty = px + rng.uniform(20, 60) * k, py + s * rng.uniform(24, 60) * k
            d.line([(px, py), (tx, ty)], fill=rgba("#140e12"), width=max(1, int(5 * k)))
            tips.append((tx, ty))
    crown(d, tips + pts[2:], k, rng, ("#a05a80", "#c47ca0", BLOSSOM_DK), r=(7, 14), per=4)
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band * clear)
    # the rain: fine, slanted, faint
    img, d = new_layer(W, H)
    for _ in range(int(900 * W * H / (3440 * 1440)) + 100):
        ang = math.radians(rng.uniform(10, 14))
        L = rng.uniform(24, 70) * k
        x, y = rng.uniform(-0.1 * W, W), rng.uniform(TOP_BAND, H)
        d.line([(x, y), (x + L * math.sin(ang), y + L * math.cos(ang))],
               fill=rgba("#9aacbc", rng.uniform(0.10, 0.22)), width=max(1, int(round(1.2 * k))))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band * clear)
    return canvas


# -- summer --------------------------------------------------------------------------
def treeline(W, H, rng, k, base, h0, h1, colour, r0, r1):
    """A broadleaf forest edge: a wall of rounded crowns of mixed heights."""
    img, d = new_layer(W, H)
    d.rectangle([0, base, W, H], fill=rgba(colour))
    x = -r1 * k
    while x < W + r1 * k:
        r = rng.uniform(r0, r1) * k
        top = base - rng.uniform(h0, h1) * H
        d.rectangle([x - r * 0.15, top, x + r * 0.15, base], fill=rgba(colour))
        for j in range(4):
            cy = top + j * r * 0.9
            rr = r * (1.0 + 0.2 * j) * rng.uniform(0.85, 1.1)
            d.ellipse([x - rr, cy - rr * 0.9, x + rr, cy + rr * 0.9], fill=rgba(colour))
        x += r * rng.uniform(1.1, 1.7)
    return img


def summer_canopy(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#08101a"), (0.42, "#14263a"), (0.66, "#2a3e46"), (0.76, "#5a5a3c"),
                        (1.0, "#5a5a3c")])
    horizon = 0.74 * H
    canvas = glow(canvas, 0.38 * W, horizon, 0.55 * W, "#c89040", 0.30, power=2.0, sy=0.22)
    canvas = glow(canvas, 0.38 * W, horizon, 0.18 * W, "#e0b060", 0.22, power=2.0, sy=0.25)
    canvas = put(canvas, stars(W, H, rng, k, 0.00003, TOP_BAND, 0.40 * H, 0.45), band * clear)
    for base, h0, h1, col, r0, r1 in ((0.76, 0.06, 0.12, "#1a2c26", 40, 80),
                                      (0.82, 0.10, 0.22, "#10221a", 50, 110),
                                      (0.92, 0.18, 0.40, "#081610", 70, 150)):
        canvas = put(canvas, blur_rgba(treeline(W, H, rng, k, base * H, h0, h1, col, r0, r1), 0.6 * k), band)
    img, d = new_layer(W, H)
    fill_below(d, W, H, ridge(W, rng, 0.94 * H, 0.012 * H), rgba("#060e0a"))
    grass(d, W, 0.95 * H, k, rng, rgba("#08140c"), int(W / (3 * k)), (20, 70))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    return fireflies(canvas, W, H, rng, k, int(70 * W / 3440) + 14, 0.70 * H, 0.97 * H, clear)


def summer_coast(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#0a0e22"), (0.36, "#1c2244"), (0.52, "#4a3a58"), (0.62, "#a06a50")])
    canvas = put(canvas, stars(W, H, rng, k, 0.00008, TOP_BAND, 0.42 * H, 0.6), band * clear)
    horizon = 0.62 * H
    sx = 0.56 * W
    canvas = glow(canvas, sx, horizon, 0.40 * W, "#d08a4a", 0.30, power=2.2, sy=0.30)
    canvas = disc(canvas, sx, horizon + 30 * k, 64 * k, "#f0c070", k, below=horizon)   # mostly set
    # the sea: dark, a little of the sky in it, teal shallows nearer
    yy = np.arange(H, dtype=np.float32)
    sea = ramp(yy, [(horizon, "#2a2a40"), (0.80 * H, "#0e1a2a"), (0.88 * H, "#12343a"), (H, "#0a1e22")])
    sea /= np.maximum(lum(sea) / WATER_LUM, 1.0)[..., None]
    m = (yy >= horizon)[:, None, None]
    canvas = np.where(m, np.broadcast_to(sea[:, None, :], canvas.shape), canvas)
    # the sun's path: short gold dashes, wider and fainter towards the shore
    img, d = new_layer(W, H)
    y = horizon + 3 * k
    while y < 0.86 * H:
        t = (y - horizon) / (0.86 * H - horizon)
        for _ in range(3):
            w = rng.uniform(6, 30) * k * (0.5 + 2.5 * t)
            x = sx + rng.gauss(0, 30 * k * (0.4 + 3 * t))
            d.line([(x - w, y), (x + w, y)], fill=rgba(SUN_GOLD, 0.55 * (1 - t) + 0.08), width=max(1, int(2 * k)))
        y += rng.uniform(4, 9) * k * (0.6 + 2 * t)
    canvas = put(canvas, blur_rgba(img, 0.6 * k), band * clear)
    # the shallows' edge and a dune in silhouette with its grass
    img, d = new_layer(W, H)
    for i in range(3):
        yb = 0.885 * H + i * 10 * k
        d.line(ridge(W, rng, yb, 6 * k, (3.0, 7.0)), fill=rgba(LAGOON, 0.10 - 0.025 * i), width=max(1, int(2 * k)))
    dune = ridge(W, rng, 0.92 * H, 0.05 * H, (0.8, 1.7))
    dune = [(x, y + 0.06 * H * max(0, 1 - x / (0.45 * W))) if x < 0.45 * W else (x, y) for x, y in dune]
    dune = [(x, y if x < 0.62 * W else y - 0.10 * H * (x - 0.62 * W) / (0.40 * W)) for x, y in dune]
    fill_below(d, W, H, dune, rgba("#0a0c12"))
    for x, y in dune[::2]:
        if x > 0.55 * W and rng.random() < 0.9:
            for _ in range(3):
                L = rng.uniform(30, 90) * k
                a = math.pi / 2 + rng.uniform(-0.5, 0.3)
                d.line([(x, y + 4 * k), (x + L * math.cos(a), y + 4 * k - L * math.sin(a))],
                       fill=rgba("#0a0c12"), width=max(1, int(2 * k)))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    return canvas


def summer_field(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#05081a"), (0.45, "#0e1430"), (0.74, "#22223a"), (0.82, "#4a3a3a"),
                        (1.0, "#4a3a3a")])
    horizon = 0.80 * H
    canvas = glow(canvas, 0.62 * W, horizon, 0.6 * W, "#a0603a", 0.28, power=2.0, sy=0.18)
    # the Milky Way: a soft diagonal band, dense with small stars
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = ((xx - 0.5 * W) * 0.42 - (yy - 0.45 * H) * 0.91) / (0.09 * max(W, H) + 0.05 * H)
    band_a = np.exp(-dist ** 2) * 0.22 * np.clip((yy - TOP_BAND) / (60 * k), 0, 1)
    band_a *= (0.75 + 0.25 * np.sin(xx / (90 * k) + yy / (140 * k)))
    canvas = canvas * (1 - band_a[..., None]) + hexc("#5a5a7c") * band_a[..., None]
    lay = stars(W, H, rng, k, 0.0016, TOP_BAND, 0.78 * H, 0.55)
    lay[..., 3] *= np.exp(-dist ** 2) * 0.9 + 0.08
    canvas = put(canvas, lay, band * clear)
    del yy, xx, dist, band_a
    canvas = put(canvas, hill(W, H, rng, k, horizon, 0.012 * H, "#141018"), band)
    # sunflowers: stems with leaves, heads as a dark disc in a ring of petals,
    # most facing away from us (east, where the sun will rise)
    img, d = new_layer(W, H)
    sil = rgba("#07080a")
    petal = rgba("#2a1c0c")
    rows = ((0.82, 0.10, 34, 0.45), (0.87, 0.18, 54, 0.75), (0.95, 0.30, 84, 1.0))
    for gy, hmax, step, sc in rows:
        x = rng.uniform(0, step) * k
        while x < W + step * k:
            L = rng.uniform(0.6, 1.0) * hmax * H
            top = gy * H - L
            hx = x + rng.uniform(-8, 8) * k
            d.line([(x, H), (hx, top)], fill=sil, width=max(1, int(4 * k * sc)))
            for j in (0.35, 0.6):
                ly = H - (H - top) * j
                s = rng.choice((-1, 1))
                d.polygon([(x, ly), (x + s * 34 * k * sc, ly - 10 * k * sc), (x + s * 18 * k * sc, ly + 6 * k * sc)],
                          fill=sil)
            # the head: a ring of pointed petals a shade warmer than the
            # silhouette (the horizon glow catching them), the dark disc on top
            r = rng.uniform(16, 24) * k * sc
            for p in range(16):
                a = p / 16 * 2 * math.pi + rng.uniform(-0.08, 0.08)
                ca, sa = math.cos(a), math.sin(a)
                d.polygon([(hx + ca * r * 0.7 - sa * r * 0.22, top + (sa * r * 0.7 + ca * r * 0.22) * 0.85),
                           (hx + ca * r * 1.75, top + sa * r * 1.75 * 0.85),
                           (hx + ca * r * 0.7 + sa * r * 0.22, top + (sa * r * 0.7 - ca * r * 0.22) * 0.85)],
                          fill=petal)
            d.ellipse([hx - r, top - r * 0.85, hx + r, top + r * 0.85], fill=sil)
            x += step * k * rng.uniform(0.8, 1.3)
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    return canvas


# -- autumn --------------------------------------------------------------------------
def autumn_maples(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#0e0c16"), (0.40, "#24182a"), (0.70, "#4a3a2c"), (1.0, "#5a4430")])
    ground = 0.82 * H
    canvas = put(canvas, mist(W, H, k, 0.70 * H, 0.10 * H, "#7a624a", 0.22), band)
    # two rows of maples: the far row hazy, the near row bigger and warmer
    for row, (gy, scale, trunk, cols, step) in enumerate((
            (0.76, 0.55, "#2a1e1a", ("#5a3a20", "#6a4022", "#4e3020"), 190),
            (0.84, 1.0, "#120a0a", ("#8a4a1c", AMBER, "#a85a24", "#d08a3a", "#6a3416"), 360))):
        img, d = new_layer(W, H)
        x = rng.uniform(-0.3, 0.3) * step * k
        while x < W + step * k:
            h = rng.uniform(0.85, 1.15) * scale * 0.48 * H
            tips = tree(d, x, gy * H, h, k, rng, rgba(trunk), depth=4)
            crown(d, tips, k * scale, rng, cols, r=(14, 30), per=4, a=(0.8, 0.95), mass=cols[-1] if row else cols[2])
            x += step * k * rng.uniform(0.85, 1.2)
        canvas = put(canvas, blur_rgba(img, (1.4 - row * 0.9) * k), band)
        if row == 0:
            canvas = put(canvas, mist(W, H, k, 0.78 * H, 0.05 * H, "#6a5440", 0.30), band)
    # the ground and a path narrowing away, strewn with leaves
    img, d = new_layer(W, H)
    fill_below(d, W, H, ridge(W, rng, ground, 0.01 * H), rgba("#1a120a"))
    cx = 0.5 * W
    d.polygon([(cx - 0.03 * W, ground + 4 * k), (cx + 0.03 * W, ground + 4 * k), (cx + 0.22 * W, H), (cx - 0.22 * W, H)],
              fill=rgba("#2a1a12"))
    canvas = put(canvas, blur_rgba(img, 1.0 * k), band)
    canvas = put(canvas, leaves(W, H, rng, k, int(1400 * W / 3440) + 100, (RUST, "#a0501e", "#6a3416", AMBER),
                                ground, H, size=(3, 8), a=(0.6, 0.95)), band)
    # leaves falling
    canvas = put(canvas, leaves(W, H, rng, k, int(160 * W / 3440) + 30, (AMBER, "#b0602a", RUST, "#d89048"),
                                TOP_BAND + 20 * k, ground, size=(4, 8)), band * clear)
    return canvas


def autumn_harvest(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#0c0a1a"), (0.42, "#221a34"), (0.68, "#4a2a34"), (0.80, "#6a3a2c"),
                        (1.0, "#6a3a2c")])
    horizon = 0.76 * H
    mx, my, mr = 0.66 * W, horizon - 0.10 * H, 0.075 * min(W, H)
    canvas = glow(canvas, mx, my, mr * 3.2, "#d08a50", 0.16)
    canvas = disc(canvas, mx, my, mr, "#e8b478", k)
    canvas = put(canvas, stars(W, H, rng, k, 0.00006, TOP_BAND, 0.5 * H, 0.5), band * clear)
    # a bare tree against the moon
    img, d = new_layer(W, H)
    tree(d, mx - 1.1 * mr, horizon + 0.03 * H, 0.36 * H, k, rng, rgba("#100a0c"), depth=6,
         bole=0.26, limb=0.30, spread=0.6)
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    for base, amp, col in ((0.77, 0.02, "#2a1a1e"), (0.83, 0.03, "#1e1414"), (0.92, 0.03, "#140e0c")):
        canvas = put(canvas, hill(W, H, rng, k, base * H, amp * H, col), band)
    # hay bales (round, with their spiral) and pumpkins along the near hill
    img, d = new_layer(W, H)
    for i in range(int(7 * W / 3440) + 3):
        x = rng.uniform(0.05, 0.95) * W
        y = rng.uniform(0.86, 0.95) * H
        r = rng.uniform(36, 62) * k * (0.6 + (y - 0.86 * H) / (0.09 * H) * 0.6)
        d.ellipse([x - r * 1.2, y - r, x + r * 1.2, y + r * 0.2], fill=rgba("#4a3418"))
        d.ellipse([x - r * 0.55, y - r * 0.8, x + r * 0.35, y + r * 0.05], outline=rgba("#5e4420"),
                  width=max(1, int(3 * k)))
    for i in range(int(9 * W / 3440) + 3):
        x, y = rng.uniform(0.05, 0.95) * W, rng.uniform(0.93, 0.98) * H
        r = rng.uniform(14, 24) * k
        d.ellipse([x - r * 1.25, y - r, x + r * 1.25, y], fill=rgba("#8a4214"))
        d.line([(x, y - r), (x + 3 * k, y - r - 8 * k)], fill=rgba("#2a2410"), width=max(1, int(3 * k)))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    return canvas


def autumn_mist(W, H, rng, k, band):
    canvas = sky(W, H, [(0.0, "#100c14"), (0.40, "#2e1e24"), (0.66, "#6a4a2a"), (0.74, "#8a5e30"),
                        (1.0, "#8a5434")])
    # layered hills, each fading into a mist band at its foot
    layers = ((0.50, 0.06, "#3a2a1c", "#8a6a4a"), (0.58, 0.06, "#2e2014", "#7a5c40"),
              (0.66, 0.05, "#24180e", "#6a5038"), (0.74, 0.05, "#1a1208", "#5a4430"))
    for base, amp, col, fog in layers:
        canvas = put(canvas, hill(W, H, rng, k, base * H, amp * H, col, waves=(0.7, 1.6, 3.3, 7.0)), band)
        canvas = put(canvas, mist(W, H, k, base * H + 0.03 * H, 0.03 * H, fog, 0.35), band)
    # the river: a band winding out of the valley, holding the copper sky
    yy = np.arange(H, dtype=np.float32)
    img, d = new_layer(W, H)
    top, bot = 0.78 * H, H
    left, right = [], []
    for i in range(41):
        t = i / 40
        y = top + (bot - top) * t
        c = W * (0.5 + 0.18 * math.sin(t * 3.2 + 0.6) * t)
        w = W * (0.015 + 0.20 * t ** 1.4)
        left.append((c - w, y))
        right.append((c + w, y))
    d.polygon(left + right[::-1], fill=(255, 255, 255, 255))
    m = np.asarray(img.getchannel("A"), np.float32) / 255
    river = ramp(yy, [(top, "#7e5432"), (H, "#3a2414")])
    river /= np.maximum(lum(river) / WATER_LUM, 1.0)[..., None]
    river = np.broadcast_to(river[:, None, :], canvas.shape)
    m = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0 * k))
    m = np.asarray(m, np.float32)[..., None] / 255
    canvas = canvas * (1 - m) + river * m
    # still-water lines across it
    img, d = new_layer(W, H)
    for _ in range(60):
        y = rng.uniform(top + 10 * k, H)
        x = rng.uniform(0.2, 0.8) * W
        d.line([(x - rng.uniform(20, 120) * k, y), (x + rng.uniform(20, 120) * k, y)],
               fill=rgba("#c0905a", 0.10), width=max(1, int(1.5 * k)))
    lay = blur_rgba(img, 0.6 * k)
    lay[..., 3] *= m[..., 0]
    canvas = put(canvas, lay, band)
    canvas = put(canvas, mist(W, H, k, 0.86 * H, 0.06 * H, "#5a4430", 0.30), band)
    return canvas


# -- winter --------------------------------------------------------------------------
def aurora(W, H, rng, k, y0, height):
    """A dim aurora: vertical curtains along a wavering line, frost blue
    fading to silver at their tops, kept below the band."""
    out = np.zeros((H, W, 4), np.float32)
    xs = np.arange(W, dtype=np.float32)
    centre = y0 + 0.06 * H * np.sin(xs / W * 5.1 + rng.uniform(0, 6)) + 0.03 * H * np.sin(xs / W * 13 + 1)
    strength = 0.5 + 0.5 * np.sin(xs / W * 9 + rng.uniform(0, 6)) * np.sin(xs / (40 * k) + 2)
    yy = np.arange(H, dtype=np.float32)[:, None]
    rel = (centre[None, :] - yy) / height          # 0 at the curtain's foot, 1 at its top
    a = np.where(rel > 0, np.exp(-rel * 2.2), np.exp(rel * 14)) * np.clip(strength, 0, 1)[None, :]
    mixc = np.clip(rel, 0, 1)[..., None]
    out[..., :3] = hexc("#4a8ab8") * (1 - mixc) + hexc("#8a98b0") * mixc
    out[..., 3] = a * 0.20
    return out


def winter_pines(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#050914"), (0.45, "#0c1830"), (0.80, "#16263e"), (1.0, "#1a2a44")])
    canvas = put(canvas, stars(W, H, rng, k, 0.00010, TOP_BAND, 0.6 * H, 0.6), band * clear)
    canvas = put(canvas, aurora(W, H, rng, k, 0.40 * H, 0.22 * H), band * clear)
    snow = field("#9aaccc", SNOW_LUM)
    # three rows of pines, far to near; the snow on them darker far away
    for gy, h0, h1, w, col, sn, step in ((0.70, 0.12, 0.20, 70, "#0e1626", field("#5a6a88", SNOW_LUM), 46),
                                         (0.78, 0.20, 0.32, 120, "#0a101c", field("#7a8aaa", SNOW_LUM), 90),
                                         (0.90, 0.34, 0.55, 200, "#060a12", snow, 190)):
        img, d = new_layer(W, H)
        fill_below(d, W, H, ridge(W, rng, gy * H, 0.008 * H), sn)
        x = rng.uniform(0, step) * k
        while x < W + step * k:
            h = rng.uniform(h0, h1) * H
            pine(d, x, gy * H + 4 * k, h, w * k * rng.uniform(0.8, 1.2), k, rgba(col), sn)
            x += step * k * rng.uniform(0.6, 1.4)
        canvas = put(canvas, blur_rgba(img, 0.6 * k), band)
    img, d = new_layer(W, H)
    fill_below(d, W, H, ridge(W, rng, 0.93 * H, 0.01 * H), snow)
    canvas = put(canvas, blur_rgba(img, 1.0 * k), band)
    return canvas


def winter_lake(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#070b18"), (0.45, "#121c36"), (0.62, "#22304c"), (1.0, "#22304c")])
    canvas = put(canvas, stars(W, H, rng, k, 0.00008, TOP_BAND, 0.5 * H, 0.55), band * clear)
    mx, my, mr = 0.30 * W, max(0.24 * H, TOP_BAND + 90 * k), 38 * k
    canvas = glow(canvas, mx, my, mr * 5, SILVER, 0.12)
    canvas = disc(canvas, mx, my, mr, "#dfe4ec", k)
    shore = 0.64 * H
    img, d = new_layer(W, H)
    fill_below(d, W, H, peaks(W, rng, shore, 0.20 * H, 7), rgba("#1a2438"))
    canvas = put(canvas, blur_rgba(img, 1.2 * k), band)
    img, d = new_layer(W, H)
    pk = peaks(W, rng, shore, 0.11 * H, 11)
    fill_below(d, W, H, pk, rgba("#101828"))
    # snow on the near range's peaks: the top quarter of each slope
    for (x0, y0), (x1, y1) in zip(pk, pk[1:]):
        if y1 < y0:      # a rising slope: cap at its top
            d.polygon([(x1, y1), (x1 - (x1 - x0) * 0.25, y1 + (y0 - y1) * 0.25),
                       (x1 + (x1 - x0) * 0.12, y1 + (y0 - y1) * 0.22)], fill=field("#8a9ab8", SNOW_LUM))
    canvas = put(canvas, blur_rgba(img, 0.6 * k), band)
    # the ice: a frost-blue field below the shore line
    yy = np.arange(H, dtype=np.float32)
    ice = ramp(yy, [(shore, "#2a3a54"), (H, "#141e30")])
    ice /= np.maximum(lum(ice) / WATER_LUM, 1.0)[..., None]
    m = (yy >= shore)[:, None, None]
    canvas = np.where(m, np.broadcast_to(ice[:, None, :], canvas.shape), canvas)
    # the moon's path on the ice: a soft column, brighter near the shore
    path = np.zeros((H, W, 4), np.float32)
    xs = np.arange(W, dtype=np.float32)
    t = np.clip((yy - shore) / (H - shore), 0, 1)[:, None]
    path[..., :3] = hexc("#aab8cc")
    path[..., 3] = np.exp(-((xs[None, :] - mx) / (30 * k * (1 + 4 * t))) ** 2) * 0.30 * (1 - 0.6 * t) * (yy >= shore)[:, None]
    canvas = over(canvas, path)
    # cracks: jagged polylines, a lighter edge beside a dark line
    img, d = new_layer(W, H)
    for _ in range(int(16 * W / 3440) + 5):
        x, y = rng.uniform(0, W), rng.uniform(shore + 0.05 * H, H)
        pts = [(x, y)]
        ang = rng.uniform(-0.4, 0.4) + rng.choice((0, math.pi))
        for _ in range(rng.randint(5, 12)):
            ang += rng.uniform(-0.7, 0.7)
            L = rng.uniform(20, 70) * k
            x, y = x + L * math.cos(ang), y + L * math.sin(ang) * 0.3
            pts.append((x, y))
        d.line([(px, py + 1.5 * k) for px, py in pts], fill=rgba("#5a6a84", 0.35), width=max(1, int(1.5 * k)))
        d.line(pts, fill=rgba("#0a1220", 0.6), width=max(1, int(1.5 * k)))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    return canvas


def winter_snowfall(W, H, rng, k, band):
    clear = clear_band(H)
    canvas = sky(W, H, [(0.0, "#080c16"), (0.45, "#141c2c"), (0.75, "#222c3e"), (1.0, "#283244")])
    # far flakes first (small, dim, sharp), then the hills, then nearer ones
    area = W * H / (3440 * 1440)
    canvas = put(canvas, flakes(W, H, rng, k, int(1600 * area) + 200, (0.7, 1.4), (0.25, 0.5), "#b8c4d8",
                                TOP_BAND, 0.4), band * clear)
    for base, amp, col in ((0.66, 0.05, "#5a6478"), (0.76, 0.05, "#6a7690"), (0.88, 0.04, "#7a88a4")):
        canvas = put(canvas, hill(W, H, rng, k, base * H, amp * H, col, cap=SNOW_LUM * (0.7 + 0.3 * (base - 0.66) / 0.22)),
                     band)
    # the cabin on the middle hill: walls, a snowy roof, a chimney, one warm
    # window (a small light accent) and its glow on the snow
    cx, gy = 0.64 * W, 0.78 * H
    cw, ch = 150 * k, 90 * k
    canvas = glow(canvas, cx - 0.2 * cw, gy + 20 * k, 140 * k, "#c08a50", 0.14, sy=0.5)
    img, d = new_layer(W, H)
    d.rectangle([cx - cw / 2, gy - ch, cx + cw / 2, gy], fill=rgba("#141824"))
    d.rectangle([cx + cw * 0.18, gy - ch - 70 * k, cx + cw * 0.30, gy - ch - 10 * k], fill=rgba("#141824"))
    d.polygon([(cx - cw * 0.62, gy - ch), (cx + cw * 0.62, gy - ch), (cx, gy - ch - 70 * k)], fill=rgba("#141824"))
    d.polygon([(cx - cw * 0.62, gy - ch), (cx, gy - ch - 70 * k), (cx + cw * 0.62, gy - ch),
               (cx + cw * 0.5, gy - ch - 8 * k), (cx, gy - ch - 60 * k), (cx - cw * 0.5, gy - ch - 8 * k)],
              fill=field("#a8b4cc", SNOW_LUM))
    d.rectangle([cx - cw * 0.30, gy - ch * 0.66, cx - cw * 0.08, gy - ch * 0.30], fill=rgba(WARM_WINDOW, 0.92))
    d.line([(cx - cw * 0.19, gy - ch * 0.66), (cx - cw * 0.19, gy - ch * 0.30)], fill=rgba("#141824"),
           width=max(1, int(3 * k)))
    canvas = put(canvas, blur_rgba(img, 0.5 * k), band)
    canvas = put(canvas, wisps(W, H, rng, k, cx + cw * 0.24, gy - ch - 72 * k, 260 * k), band * clear)
    # bare trees on the far hill, drawn small
    img, d = new_layer(W, H)
    for _ in range(int(10 * W / 3440) + 3):
        tx = rng.uniform(0, W)
        tree(d, tx, 0.68 * H, rng.uniform(0.08, 0.14) * H, k, rng, rgba("#2a3040"), depth=4)
    canvas = put(canvas, blur_rgba(img, 0.8 * k), band)
    canvas = put(canvas, flakes(W, H, rng, k, int(500 * area) + 60, (1.4, 2.6), (0.35, 0.6), "#c8d2e2",
                                TOP_BAND, 0.9), band * clear)
    canvas = put(canvas, flakes(W, H, rng, k, int(70 * area) + 10, (4, 7), (0.25, 0.45), "#d2dae8",
                                TOP_BAND, 3.0), band * clear)
    return canvas


SCENES = {
    "spring-orchard": spring_orchard, "spring-meadow": spring_meadow, "spring-shower": spring_shower,
    "summer-canopy": summer_canopy, "summer-coast": summer_coast, "summer-field": summer_field,
    "autumn-maples": autumn_maples, "autumn-harvest": autumn_harvest, "autumn-mist": autumn_mist,
    "winter-pines": winter_pines, "winter-lake": winter_lake, "winter-snowfall": winter_snowfall,
}


def render(W, H, variant):
    rng = random.Random(f"seasons-{variant}-{W}x{H}")
    k = min(W, H) / 1440
    band = detail_band(H)
    canvas = SCENES[variant](W, H, rng, k, band)
    return finish(canvas, f"seasons-{variant}-{W}x{H}")


def finish(canvas, seed):
    """Vignette, grain, PEAK cap (the HDR rule), then 8-bit with a +-0.5 LSB
    dither. The grain is luminance only, seeded from the name and size; the
    cap SCALES a too-bright colour down whole, so a pale moon keeps its hue."""
    H, W = canvas.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
    canvas = canvas * (1 - 0.18 * r2)[..., None]
    del yy, xx, r2
    rng = np.random.default_rng(zlib.crc32(seed.encode()))
    canvas = canvas + rng.normal(0, GRAIN, (H, W, 1)).astype(np.float32)
    canvas = np.clip(canvas, 0.0, None)
    peak = canvas.max(axis=-1, keepdims=True)
    out = canvas / np.maximum(peak / PEAK, 1.0)
    px = out * 255.0 + rng.uniform(-0.5, 0.5, out.shape).astype(np.float32)
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
    ap.add_argument("--all", action="store_true", help="all 12 variants for every monitor folder")
    ap.add_argument("--season", choices=SEASONS, help="that season's 3 variants for every monitor folder")
    ap.add_argument("--list", action="store_true", help="the variants")
    ap.add_argument("-v", "--variant", default="autumn-maples", choices=VARIANTS)
    ap.add_argument("-o", "--output", help="one image to this path")
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's (logical)")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's (logical)")
    a = ap.parse_args()
    if a.list:
        print("\n".join(VARIANTS))
        return
    if a.all or a.season:
        for variant in VARIANTS:
            if a.season and not variant.startswith(a.season + "-"):
                continue
            for mon, (w, h) in logical_sizes().items():
                write(render(w, h, variant), os.path.join(WALLDIR, mon, f"seasons-{variant}.png"))
        return
    if not a.output:
        ap.error("give -o FILE, --season S or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size(logical=True)
    write(render(a.width, a.height, a.variant), a.output)


if __name__ == "__main__":
    main()
