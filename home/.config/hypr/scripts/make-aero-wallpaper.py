#!/usr/bin/env python3
"""Render Windows 7-style "Aero" wallpapers: a deep gradient, sweeping ribbons
of light converging on a soft glow, and out-of-focus bokeh -- the Harmony look,
without the logo (that one is Microsoft's; this is only the mood).

    make-aero-wallpaper.py --all                  every palette, every monitor,
                                                  into the slideshow folders
    make-aero-wallpaper.py -p teal -o x.png -W 1920 -H 1080 --seed 3
    make-aero-wallpaper.py --list                 the palettes

--all writes ~/Pictures/Wallpapers/<OUTPUT>/aero-<palette>.png for every
screen connected now, each at its own size as it is seen (screens.py sizes():
a rotated, portrait screen gets a portrait picture; 1920x1080 for the primary
when Hyprland is not running). -W / -H default to the primary's size.
wallpaper-slideshow.py re-reads those folders at every change, so they join
the rotation with no restart -- and on the primary the bar's accent follows
them (theme-from-wallpaper.py), which is most of the fun.

Same constraints as make-wallpaper.py, for the same reasons:
  * On an HDR screen SDR is mapped into the HDR range, so nothing is allowed to
    reach full white: highlights are soft-clipped to PEAK.
  * The bar is glass over the top 36 px and blur smears bright areas, so the
    light is kept in the middle and lower part of the frame and the top stays
    in the gradient's dark end.
  * A tiny noise dither hides the banding that big smooth gradients get in
    8-bit.
Deterministic: the same --seed and size always give the same image.

Pure numpy + Pillow (both installed); a few seconds per image, --all about a
minute and a half.
"""

import argparse
import math
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (scripts/screens.py: the screens and their sizes)

PEAK = 0.80

# name: (background top, background bottom, glow, ribbon hues as RGB 0..1)
PALETTES = {
    "blue": ((0.01, 0.05, 0.16), (0.02, 0.22, 0.48), (0.55, 0.85, 1.00),
             [(0.25, 0.75, 1.00), (0.40, 0.95, 0.85), (0.70, 0.55, 1.00), (0.95, 0.80, 0.35)]),
    "teal": ((0.00, 0.08, 0.10), (0.01, 0.30, 0.34), (0.55, 1.00, 0.90),
             [(0.20, 0.95, 0.80), (0.30, 0.70, 1.00), (0.75, 1.00, 0.45), (0.95, 0.95, 0.60)]),
    "aurora": ((0.01, 0.04, 0.08), (0.03, 0.20, 0.14), (0.60, 1.00, 0.65),
               [(0.30, 1.00, 0.55), (0.25, 0.80, 1.00), (0.70, 0.40, 1.00), (1.00, 0.45, 0.70)]),
    # "harmony" replaced "sunset" (2026-10-17). The aero theme lets the accent
    # follow the wallpaper, and sunset's red ribbons won the hue vote with
    # #ff2e5e -- the theme's "bad" red, so every selection and lit edge read
    # as an error. A warm palette fails the same way in orange (warn, night
    # light), so the set stays in the cool family Aero was known for: this one
    # is the Windows 7 "Harmony" mood, azure with cyan, lime and a pale gold
    # strand. It sorts into sunset's place, so --all keeps every other
    # palette's seed (and picture) as it was.
    "harmony": ((0.01, 0.05, 0.13), (0.02, 0.26, 0.50), (0.70, 0.92, 1.00),
                [(0.30, 0.85, 1.00), (0.55, 0.95, 0.35), (0.45, 0.70, 1.00), (0.95, 0.85, 0.45)]),
    "violet": ((0.03, 0.01, 0.10), (0.20, 0.06, 0.40), (0.85, 0.65, 1.00),
               [(0.70, 0.40, 1.00), (0.35, 0.60, 1.00), (1.00, 0.45, 0.85), (0.50, 0.95, 1.00)]),
}

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")


def render(width, height, palette, seed):
    top, bottom, glow_rgb, hues = PALETTES[palette]
    rng = np.random.default_rng(seed)
    portrait = height > width
    # Work in a coordinate space where the short side is 1, so every feature
    # keeps its proportions on the ultrawide and on the rotated portrait panel.
    short = min(width, height)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    u, v = xs / short, ys / short
    W, H = width / short, height / short

    # Background: vertical gradient, darker at the top, plus a broad lift
    # around the focal point so the light seems to come from somewhere.
    t = (v / H) ** 1.3
    img = (np.array(top, np.float32)[None, None, :] * (1 - t[..., None])
           + np.array(bottom, np.float32)[None, None, :] * t[..., None])

    fx, fy = (W * 0.5, H * 0.58) if portrait else (W * 0.42, H * 0.6)
    r2 = (u - fx) ** 2 + (v - fy) ** 2
    img += np.array(bottom, np.float32) * 0.6 * np.exp(-r2 / 0.5)[..., None]

    # Ribbons: bands of light along smooth curves through the focal point,
    # each a bundle of thin strands so it reads as a swoosh rather than a tube.
    light = np.zeros_like(img)
    n_ribbons = 5
    for i in range(n_ribbons):
        hue = np.array(hues[i % len(hues)], np.float32)
        angle = rng.uniform(-0.55, 0.35) + (math.pi / 2 if portrait else 0)
        # A curve y = A sin(k s + phi) along a rotated axis s through the focus.
        ca, sa = math.cos(angle), math.sin(angle)
        s = (u - fx) * ca + (v - fy) * sa          # along the ribbon
        n = -(u - fx) * sa + (v - fy) * ca         # across it
        amp = rng.uniform(0.10, 0.30)
        k = rng.uniform(1.2, 2.4)
        phi = rng.uniform(0, 2 * math.pi)
        centre = amp * np.sin(k * s + phi) - amp * math.sin(phi)   # passes through the focus
        slope = amp * k * np.cos(k * s + phi)
        dist = np.abs(n - centre) / np.sqrt(1 + slope ** 2)
        # Widest and brightest near the focus, tapering away from it.
        taper = np.exp(-(s / rng.uniform(0.9, 1.6)) ** 2)
        width_ = rng.uniform(0.012, 0.03) * (0.35 + taper)
        strands = 6
        band = np.zeros_like(dist)
        for j in range(strands):
            off = (j - strands / 2) * width_ * 0.9
            band += np.exp(-((dist - np.abs(off)) / (width_ * 0.45)) ** 2) * (1 - abs(j - strands / 2) / strands)
        core = np.exp(-(dist / (width_ * 0.25)) ** 2)
        strength = (0.22 * band + 0.5 * core) * taper * rng.uniform(0.55, 1.0)
        light += strength[..., None] * hue
        # A wide faint haze around each ribbon: the "glass" glow of Aero.
        light += (0.06 * np.exp(-(dist / 0.12) ** 2) * taper)[..., None] * hue

    # The glow where the ribbons meet.
    glow = np.exp(-r2 / 0.010) * 0.55 + np.exp(-r2 / 0.08) * 0.18
    light += glow[..., None] * np.array(glow_rgb, np.float32)

    # Bokeh: soft discs, more of them near the focus, a few with a brighter rim
    # like a real out-of-focus highlight.
    for _ in range(int(70 * W * H / 2.4)):
        bx = fx + rng.normal(0, W * 0.32)
        by = fy + rng.normal(0, H * 0.28)
        br = rng.uniform(0.01, 0.06)
        x0, x1 = int(max(0, (bx - br * 1.5) * short)), int(min(width, (bx + br * 1.5) * short))
        y0, y1 = int(max(0, (by - br * 1.5) * short)), int(min(height, (by + br * 1.5) * short))
        if x1 <= x0 or y1 <= y0:
            continue
        d = np.sqrt((u[y0:y1, x0:x1] - bx) ** 2 + (v[y0:y1, x0:x1] - by) ** 2) / br
        disc = np.clip(1.2 - d, 0, 1) ** 0.6
        rim = np.exp(-((d - 0.92) / 0.08) ** 2) * 0.5
        alpha = rng.uniform(0.03, 0.12) * (disc + rim * (rng.random() < 0.4))
        colour = np.array(hues[rng.integers(len(hues))], np.float32) * 0.6 + np.array(glow_rgb) * 0.4
        light[y0:y1, x0:x1] += alpha[..., None] * colour

    # Keep the bar's band (top of a landscape screen) quiet: blur would smear
    # any light there across every pill.
    if not portrait:
        quiet = np.clip((v - 0.06) / 0.25, 0, 1) ** 1.5
        light *= quiet[..., None]

    img = img + light
    # Soft clip: linear up to the knee, then a smooth shoulder that never
    # passes PEAK.
    knee = PEAK * 0.7
    over = np.maximum(img - knee, 0)
    img = np.where(img > knee, knee + (PEAK - knee) * (1 - np.exp(-over / (PEAK - knee))), img)
    # Vignette and dither.
    vig = 1 - 0.35 * (((u - W / 2) / W) ** 2 + ((v - H / 2) / H) ** 2) * 2
    img *= vig[..., None]
    img += rng.normal(0, 0.6 / 255, img.shape).astype(np.float32)
    return Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-p", "--palette", default="blue", choices=sorted(PALETTES))
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("-o", "--output")
    ap.add_argument("--all", action="store_true",
                    help="every palette for every monitor, into the slideshow folders")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("\n".join(sorted(PALETTES)))
        return
    if args.all:
        for output, (w, h) in screens.sizes().items():
            folder = os.path.join(WALLDIR, output)
            os.makedirs(folder, exist_ok=True)
            # A seed per palette, so the set is five different sweeps rather
            # than one sweep in five colours.
            for index, palette in enumerate(sorted(PALETTES)):
                path = os.path.join(folder, f"aero-{palette}.png")
                render(w, h, palette, args.seed + index).save(path, optimize=True)
                print(path)
        return
    path = args.output or os.path.join(WALLDIR, f"aero-{args.palette}.png")
    pw, ph = screens.primary_size() if not (args.width and args.height) else (0, 0)
    render(args.width or pw, args.height or ph, args.palette, args.seed).save(path, optimize=True)
    print(path)


if __name__ == "__main__":
    sys.exit(main())
