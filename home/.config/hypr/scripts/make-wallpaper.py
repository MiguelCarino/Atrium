#!/usr/bin/env python3
"""Render the default wallpaper: a quiet neon night-city over a perspective grid.

Writes ~/Pictures/Wallpapers/dp1-ultrawide.png (the name is historical) at
the primary screen's size (screens.py; 1920x1080 without Hyprland), the path
hyprpaper.conf paints every screen with before the slideshow starts. Procedural on purpose, so it can be regenerated,
re-seeded or re-coloured instead of hunting for a stock image of the right size:

    ~/.config/hypr/scripts/make-wallpaper.py                 # default output
    ~/.config/hypr/scripts/make-wallpaper.py --seed 7        # different skyline
    ~/.config/hypr/scripts/make-wallpaper.py -o /tmp/x.png -W 1720 -H 720

then repaint without restarting anything:

    hyprctl hyprpaper wallpaper "<OUTPUT>,$HOME/Pictures/Wallpapers/dp1-ultrawide.png"

The cyberpunk theme's slideshow set (prefix "skyline-", ~/.config/themes/
cyberpunk/theme.conf) is this picture at seeds 2-5, rendered once per monitor
at that monitor's own size (as `screens.py` prints it: "pixels"), so the
screens change together:

    for s in 2 3 4 5; do
        make-wallpaper.py --seed $s -W <width> -H <height> -o ~/Pictures/Wallpapers/<OUTPUT>/skyline-seed$s.png
    done        # once per screen

DESIGN CONSTRAINTS (why it looks the way it does):
  * It sits behind translucent, blurred windows and a 36px waybar at the top.
    So the top band is plain near-black (no stars, no glow) and nothing large
    is bright: the only light is a thin horizon line, a dim half-sun and
    pin-prick windows. Blur smears bright areas across every window above them.
  * On an HDR panel SDR content is mapped into the HDR range, and full-white or
    saturated full-field areas come out glaring. Peak values are capped well
    below 255 (see PEAK) and the glow uses low alpha.
  * The palette is waybar's NEON theme (style.css): cyan #00f0ff, magenta
    #ff2a6d, purple #b026ff on near-black #06080f, so bar and desktop match.
  * Large dark gradients band visibly in 8-bit; a tiny noise dither (numpy, if
    installed -- it is skipped otherwise) hides that.
  * Any aspect ratio, portrait included (a rotated 1080x1920 screen, say).
    The picture is laid out in a design space 1440 units TALL and as wide as
    the output's aspect asks (3440 for 43:18, 3413 for 64:27, 810 for
    portrait), scaled uniformly -- never stretched. Everything is drawn in
    those units, so a building is the same shape on every screen and a wider
    screen simply sees more city. The two things whose size was tied to the
    ultrawide's width are scaled to the short side instead: the sun (300
    units, at most 30% of the width, so it still sits between towers on a
    portrait screen) and the vignette (inner radius from the short side,
    outer from the long one; at 3440x1440 both are the old values).
Deterministic: the same --seed and size always give the same image, and at
3440x1440 the same image as before the any-aspect change.
"""
import argparse
import math
import os
import random
import sys

import cairo

# Theme colours as 0..1 floats -- straight from waybar/style.css.
def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

BG      = hexrgb("#06080f")   # near-black, the page colour of the whole theme
CYAN    = hexrgb("#00f0ff")
MAGENTA = hexrgb("#ff2a6d")
PURPLE  = hexrgb("#b026ff")
DEEP    = hexrgb("#1a0b2e")   # sky just above the horizon: purple pushed into black

# Brightness ceiling for anything drawn (fraction of full scale). Keeps the
# HDR-mapped SDR image from having glaring highlights.
PEAK = 0.78


def dim(c, k):
    return tuple(min(PEAK, v * k) for v in c)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def sky(cr, W, H, hz):
    """Vertical gradient: flat BG through the top ~third (bar area stays calm),
    easing into DEEP purple and a faint magenta haze just above the horizon."""
    g = cairo.LinearGradient(0, 0, 0, hz)
    g.add_color_stop_rgb(0.00, *BG)
    g.add_color_stop_rgb(0.30, *BG)
    g.add_color_stop_rgb(0.70, *mix(BG, DEEP, 0.75))
    g.add_color_stop_rgb(0.93, *mix(DEEP, dim(MAGENTA, 0.35), 0.35))
    g.add_color_stop_rgb(1.00, *mix(DEEP, dim(MAGENTA, 0.45), 0.55))
    cr.set_source(g)
    cr.rectangle(0, 0, W, hz)
    cr.fill()


def stars(cr, W, H, hz, rng):
    """Sparse, faint stars in the middle band only: never in the top 90px
    (under the bar) and fading out towards the horizon haze."""
    top = 90
    for _ in range(int(W * H / 26000)):
        x = rng.uniform(0, W)
        y = top + (hz * 0.72 - top) * rng.random() ** 1.4
        a = rng.uniform(0.10, 0.38) * (1 - (y - top) / (hz * 0.72))
        c = rng.choice([CYAN, PURPLE, (0.8, 0.85, 1.0)])
        cr.set_source_rgba(*dim(c, 1), a)
        cr.arc(x, y, rng.uniform(0.6, 1.4), 0, 2 * math.pi)
        cr.fill()


def sun(cr, W, hz, R):
    """A dim synthwave half-sun sitting on the horizon, sliced by horizontal
    gaps that widen towards the bottom. Low alpha so it reads as a glow behind
    the skyline rather than a bright disc."""
    cx = W * 0.5
    cr.save()
    # Outer halo first: a wide, very soft radial glow.
    halo = cairo.RadialGradient(cx, hz, R * 0.4, cx, hz, R * 2.6)
    halo.add_color_stop_rgba(0, *dim(MAGENTA, 0.9), 0.16)
    halo.add_color_stop_rgba(0.5, *dim(PURPLE, 0.8), 0.06)
    halo.add_color_stop_rgba(1, *PURPLE, 0)
    cr.set_source(halo)
    cr.rectangle(cx - R * 2.6, hz - R * 2.6, R * 5.2, R * 2.6)
    cr.fill()

    # Clip to the upper half-disc minus the slices.
    cr.arc(cx, hz, R, math.pi, 2 * math.pi)
    cr.close_path()
    cr.clip()
    n = 6
    for i in range(n):
        # slices start in the lower 55% of the disc and get thicker downwards
        t = i / n
        y = hz - R * 0.62 * (1 - t)
        h = 3 + 13 * t
        cr.rectangle(cx - R, y, 2 * R, h)
    cr.rectangle(cx - R, hz - R, 2 * R, R)
    cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    g = cairo.LinearGradient(0, hz - R, 0, hz)
    # Darker at the crown, warmest where it meets the horizon glow: the disc
    # reads as light coming up from below rather than a flat bright shape.
    g.add_color_stop_rgba(0, *dim(MAGENTA, 0.70), 0.36)
    g.add_color_stop_rgba(0.65, *dim(MAGENTA, 0.80), 0.46)
    g.add_color_stop_rgba(1, *dim(PURPLE, 0.75), 0.42)
    cr.set_source(g)
    cr.fill()
    cr.restore()


def skyline(cr, W, hz, rng, depth):
    """One row of building silhouettes standing on the horizon.

    depth 0 = far (short, lighter, hazier), 1 = near (taller, near-black).
    Each row is filled solid, then sprinkled with a few lit windows. Taller
    blocks cluster away from the centre so the sun stays visible between them.
    """
    base_h = (60, 50, 90)[depth]
    var_h  = (140, 230, 380)[depth]
    # Atmospheric perspective: far rows are lifted towards the purple haze,
    # the near row is almost pure black.
    body   = (mix(DEEP, PURPLE, 0.10), mix(DEEP, BG, 0.45), mix(BG, (0, 0, 0), 0.45))[depth]
    win_a  = (0.16, 0.28, 0.42)[depth]
    x = -rng.uniform(0, 40)
    blocks = []
    while x < W:
        w = rng.uniform(26, 80) * (1 + 0.45 * depth)
        # distance from centre 0..1; buildings shrink near the sun so it
        # stays visible, the near row most of all.
        d = abs((x + w / 2) - W / 2) / (W / 2)
        reach = (2.4, 1.9, 1.35)[depth]
        squash = (0.25, 0.15, 0.0)[depth] + (0.75, 0.85, 1.0)[depth] * min(1, d * reach) ** 1.5
        h = (base_h + var_h * rng.random() ** 1.8) * squash
        if depth == 2 and h < 70:
            # gap in the near row: skip it entirely rather than leave stubs
            x += w
            continue
        blocks.append((x, w, h))
        x += w + rng.uniform(0, 18) * (depth < 2)

    cr.set_source_rgb(*body)
    for x, w, h in blocks:
        cr.rectangle(x, hz - h, w, h + 1)
        # occasional antenna / stepped top on the taller ones
        if h > base_h + var_h * 0.5 and rng.random() < 0.5:
            sw = w * rng.uniform(0.3, 0.6)
            cr.rectangle(x + (w - sw) / 2, hz - h - h * 0.12, sw, h * 0.12 + 1)
            if rng.random() < 0.6:
                cr.rectangle(x + w / 2 - 1, hz - h - h * 0.12 - 40, 2, 40)
    cr.fill()

    # Rim light: a hairline of colour along the roofs of the near rows, as if
    # lit from the horizon haze. Very low alpha, it is only there for depth.
    if depth:
        cr.set_line_width(1)
        cr.set_source_rgba(*dim(PURPLE if depth == 1 else MAGENTA, 0.9), 0.22)
        for x, w, h in blocks:
            cr.move_to(x, hz - h + 0.5)
            cr.line_to(x + w, hz - h + 0.5)
        cr.stroke()

    # Lit windows: tiny, sparse, mostly cyan with a few magenta. A per-building
    # "occupancy" keeps some towers dark so it doesn't turn into a dot grid.
    for x, w, h in blocks:
        occ = rng.random() ** 2 * 0.22
        if occ < 0.02:
            continue
        cols = max(1, int(w // 9))
        rows = max(1, int(h // 12))
        for r in range(rows):
            for c in range(cols):
                if rng.random() > occ:
                    continue
                col = MAGENTA if rng.random() < 0.18 else CYAN
                cr.set_source_rgba(*dim(col, 0.85), win_a * rng.uniform(0.5, 1))
                cr.rectangle(x + 4 + c * 9, hz - h + 8 + r * 12, 3, 4)
                cr.fill()


def grid(cr, W, H, hz):
    """Perspective floor grid below the horizon, drawn in cyan with alpha that
    fades to nothing near the horizon (far lines would just alias into a band)
    and stays low near the bottom edge so it doesn't fight window content."""
    # Floor fill: near-black with a faint purple lift right under the horizon.
    g = cairo.LinearGradient(0, hz, 0, H)
    g.add_color_stop_rgb(0, *mix(DEEP, BG, 0.35))
    g.add_color_stop_rgb(0.12, *mix(DEEP, BG, 0.80))
    g.add_color_stop_rgb(0.40, *BG)
    g.add_color_stop_rgb(1, *mix(BG, (0, 0, 0), 0.4))
    cr.set_source(g)
    cr.rectangle(0, hz, W, H - hz)
    cr.fill()

    cx = W / 2
    depth_h = H - hz
    cr.save()
    cr.rectangle(0, hz + 1, W, depth_h)
    cr.clip()

    # Vertical (converging) lines: evenly spaced at the bottom edge, all
    # meeting at the vanishing point on the horizon. Their alpha ramps up from
    # zero at the horizon, where dozens of them converge into a grey smear.
    spacing = 210
    n = int(W * 4 / spacing)
    fade = cairo.LinearGradient(0, hz, 0, H)
    fade.add_color_stop_rgba(0.00, *dim(CYAN, 0.9), 0.0)
    fade.add_color_stop_rgba(0.15, *dim(CYAN, 0.9), 0.05)
    fade.add_color_stop_rgba(0.60, *dim(CYAN, 0.9), 0.20)
    fade.add_color_stop_rgba(1.00, *dim(CYAN, 0.9), 0.15)
    cr.set_source(fade)
    cr.set_line_width(1.5)
    for i in range(-n, n + 1):
        cr.move_to(cx, hz)
        cr.line_to(cx + i * spacing, H)
    cr.stroke()

    # Horizontal lines: a real ground plane seen from eye height, so row k
    # (k metres away) lands at hz + f/k -- they bunch up towards the horizon.
    # Rows too close to the horizon are skipped; they would only alias.
    f = depth_h * 1.6
    k = 1.0
    while True:
        y = hz + f / k
        k += 1
        if y > H:
            continue
        if y - hz < 14:
            break
        t = (y - hz) / depth_h                      # 0 at horizon .. 1 at bottom
        a = 0.22 * min(1, t * 4) * (1 - 0.3 * t)
        cr.set_source_rgba(*dim(CYAN, 0.9), a)
        cr.set_line_width(0.8 + 1.4 * t)
        cr.move_to(0, y)
        cr.line_to(W, y)
        cr.stroke()
    cr.restore()


def horizon(cr, W, hz):
    """The one 'neon' accent: a thin magenta line on the horizon with a soft
    bloom above and below, brightest at the centre and fading out to the sides."""
    for spread, a in ((26, 0.10), (9, 0.22), (2.2, 0.55)):
        g = cairo.LinearGradient(0, hz - spread, 0, hz + spread)
        g.add_color_stop_rgba(0, *MAGENTA, 0)
        g.add_color_stop_rgba(0.5, *dim(MAGENTA, 1), a)
        g.add_color_stop_rgba(1, *MAGENTA, 0)
        cr.set_source(g)
        cr.rectangle(0, hz - spread, W, 2 * spread)
        cr.fill()
    # Side fade: darken the outer thirds of that band so the light pools centre.
    side = cairo.LinearGradient(0, 0, W, 0)
    side.add_color_stop_rgba(0, *BG, 0.75)
    side.add_color_stop_rgba(0.3, *BG, 0.0)
    side.add_color_stop_rgba(0.7, *BG, 0.0)
    side.add_color_stop_rgba(1, *BG, 0.75)
    cr.set_source(side)
    cr.rectangle(0, hz - 30, W, 60)
    cr.fill()


def vignette(cr, W, H):
    """Darken the corners so window edges on the sides read against black.
    Radii from the short and the long side, so a portrait screen gets the
    same falloff turned on its side instead of an inside-out gradient (an
    inner radius larger than the outer one, which W * 0.62 gave at 810 wide)."""
    r = cairo.RadialGradient(W / 2, H * 0.62, min(W, H) * 0.35,
                             W / 2, H * 0.62, max(W, H) * 0.62)
    r.add_color_stop_rgba(0, 0, 0, 0, 0)
    r.add_color_stop_rgba(1, 0, 0, 0, 0.55)
    cr.set_source(r)
    cr.rectangle(0, 0, W, H)
    cr.fill()


def dither(surface, seed):
    """+-1 LSB noise against gradient banding. Optional: needs numpy."""
    try:
        import numpy as np
    except ImportError:
        return
    surface.flush()
    W, H = surface.get_width(), surface.get_height()
    buf = np.ndarray((H, surface.get_stride() // 4, 4), np.uint8, surface.get_data())
    noise = np.random.default_rng(seed).integers(-1, 2, (H, W, 1), dtype=np.int16)
    px = buf[:, :W, :3].astype(np.int16) + noise
    buf[:, :W, :3] = np.clip(px, 0, 255).astype(np.uint8)
    surface.mark_dirty()


def render(W, H, seed):
    rng = random.Random(seed)
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cr = cairo.Context(s)
    # Everything is laid out in a 3440x1440 design space and scaled, so a
    # small preview (-W 860 -H 360) is the same picture.
    # Uniform scale from the height; the design width follows the aspect
    # (see DESIGN CONSTRAINTS), so nothing is ever stretched.
    k = H / 1440
    cr.scale(k, k)
    W, H = W / k, 1440
    hz = H * 0.60                          # horizon a bit below the middle

    sky(cr, W, H, hz)
    stars(cr, W, H, hz, rng)
    sun(cr, W, hz, min(300, W * 0.30))
    skyline(cr, W, hz, rng, 0)
    skyline(cr, W, hz, rng, 1)
    grid(cr, W, H, hz)
    skyline(cr, W, hz, rng, 2)
    horizon(cr, W, hz)
    vignette(cr, W, H)
    dither(s, seed)
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-o", "--output",
                    default=os.path.expanduser("~/Pictures/Wallpapers/dp1-ultrawide.png"))
    # Any aspect ratio: the design space is 1440 units tall and as wide as
    # the aspect asks, scaled uniformly (see DESIGN CONSTRAINTS).
    ap.add_argument("-W", "--width", type=int,
                    help="output width (any aspect ratio, portrait included; "
                         "default: the primary screen's)")
    ap.add_argument("-H", "--height", type=int,
                    help="output height (see -W)")
    ap.add_argument("--seed", type=int, default=2077)
    a = ap.parse_args()
    if not (a.width and a.height):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import screens      # scripts/screens.py: the primary screen's size
        a.width, a.height = screens.primary_size()
    # cairo's own message for this is "invalid matrix (not invertible)".
    if a.width <= 0 or a.height <= 0:
        ap.error("width/height must be positive")
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    # Write beside the target and rename over it: the default output is the
    # live wallpaper hyprpaper reads (at login, or on a repaint) at any moment,
    # and a half-written PNG there would leave the screen blank. os.replace is atomic
    # within one filesystem, and a failed write leaves the old image intact.
    tmp = a.output + ".tmp"
    try:
        render(a.width, a.height, a.seed).write_to_png(tmp)
        os.replace(tmp, a.output)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    print(a.output)


if __name__ == "__main__":
    main()
