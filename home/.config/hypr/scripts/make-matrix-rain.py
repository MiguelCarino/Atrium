#!/usr/bin/env python3
"""Render the matrix theme's MOVING wallpaper: digital rain as a seamless
video loop, one per monitor, played by wallpaper-slideshow.py (mpvpaper)
behind the windows.

    make-matrix-rain.py --all                 matrix-rain.mp4 for every
                                              monitor folder (~1 min each)
    make-matrix-rain.py -W 1720 -H 720 --seconds 6 -o /tmp/x.mp4
    make-matrix-rain.py -W 1720 -H 720 --frame 40 -o /tmp/x.png
                                              one still frame, for a look

--all writes ~/Pictures/Wallpapers/<OUTPUT>/matrix-rain.mp4 for every monitor
at its LOGICAL size (logical_sizes(): the mode over the scale, turned when
rotated -- a 2560x1080 screen at scale 0.8 is 3200x1350; --only OUTPUT for
one): the name in
wallpaper_video= in ~/.config/themes/matrix/theme.conf. The stills
(make-matrix-wallpaper.py, matrix-1..4.png) stay: they are what hyprpaper
shows under the video, and all there is while it is off or stopped.

How it moves -- as in the film, the GLYPHS DO NOT MOVE: every cell of the
grid holds one glyph for good (a few swap now and then), and a stream is a
bright head stepping down its column a cell at a time, lighting the glyphs it
passes; behind it they fade from pale through green to nothing. Three depths
(the stills' layers): far small dim and slow, near big brighter and faster.

Calm on purpose -- the green-on-everything matrix made its user dizzy:
  * slow: 2.5-9 cells a second (the film is ~15-20), the far layer slowest;
  * 10 frames a second: a head steps at most once a frame, so smoother
    would add nothing but compositor work -- every new frame makes Hyprland
    recomposite the monitor, blur behind glass included (why the old video
    wallpapers went); it plays under windows too, and the slideshow STOPS it
    in gamemode;
  * the theme's soft green (#3ddc68), not #00ff41 neon; PEAK 0.70 (the HDR
    rule, make-wallpaper.py), lower than the stills' 0.78.

Seamless: the loop is LOOP seconds; every stream's cycle (screen height plus
its trail plus a gap, in cells) is crossed a whole number of times in it, and
every swapping glyph's period divides it, so the last frame runs into the
first. Deterministic: same size, same video.

Pure numpy + Pillow, frames piped to ffmpeg (libx264: decoded in hardware by
mpv's hwdec on any GPU; the scene is mostly black and mostly still, so a
30 s ultrawide loop is a few MB).
"""

import argparse
import importlib.util
import os
import random
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("matrix_still", os.path.join(HERE, "make-matrix-wallpaper.py"))
still = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(still)     # its Atlas (glyphs), OUTPUTS, WALLDIR, QUIET, FADE

FPS = 10
LOOP = 30                           # seconds
FRAMES = FPS * LOOP
NAME = "matrix-rain.mp4"
PEAK = 0.70

# The calmer matrix's greens (themes/matrix: accent #3ddc68), 0..1.
HEAD = (0.83, 0.97, 0.86)           # #d4f8dc
BRIGHT = (0.24, 0.86, 0.41)         # #3ddc68
MID = (0.13, 0.59, 0.25)            # #22963f
DEEP = (0.05, 0.20, 0.09)           # #0d3317
FLOOR = np.array(still.FLOOR, np.float32)
STOPS = [(0.00, HEAD, 1.00), (0.06, BRIGHT, 0.95), (0.30, MID, 0.85),
         (0.70, DEEP, 0.75), (1.00, DEEP, 0.00)]

# Far to near, like the stills; speed in cells per second.
LAYERS = [
    dict(size=17, density=0.9, bright=0.28, trail=(10, 34), heads=0.25, speed=(2.5, 4.0)),
    dict(size=24, density=0.5, bright=0.55, trail=(8, 26), heads=0.45, speed=(4.0, 6.0)),
    dict(size=34, density=0.15, bright=0.85, trail=(6, 18), heads=0.75, speed=(6.0, 9.0)),
]
SWAP = 0.03                                   # share of cells whose glyph swaps
SWAP_PERIODS = [FRAMES // k for k in (6, 10, 15)]   # frames; each divides the loop


def ramp(t):
    """(rgb, alpha) arrays for trail positions t (0 = head .. 1 = tail end)."""
    ts = [s[0] for s in STOPS]
    rgb = np.stack([np.interp(t, ts, [s[1][c] for s in STOPS]) for c in range(3)], -1)
    return rgb.astype(np.float32), np.interp(t, ts, [s[2] for s in STOPS]).astype(np.float32)


class Layer:
    def __init__(self, W, H, rng, size, density, bright, trail, heads, speed):
        self.cw = cw = max(6, int(size * 0.82))
        self.ch = ch = max(8, int(size * 1.08))
        atlas = still.Atlas(size, cw, ch)
        self.cols, self.rows = W // cw + 1, H // ch + 2
        self.W, self.H = W, H
        # Two glyph sheets: what each cell shows, and what a swapping cell
        # shows in its other half-period (the same glyph for the rest).
        self.g0 = np.zeros((self.rows * ch, self.cols * cw), np.float32)
        self.g1 = np.zeros_like(self.g0)
        self.swap_period = np.zeros((self.rows, self.cols), np.int32)
        self.swap_phase = np.zeros((self.rows, self.cols), np.int32)
        for r in range(self.rows):
            for c in range(self.cols):
                g = atlas.pick(rng)
                self.g0[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = g
                if rng.random() < SWAP:
                    self.g1[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = atlas.pick(rng)
                    self.swap_period[r, c] = rng.choice(SWAP_PERIODS)
                    self.swap_phase[r, c] = rng.randrange(FRAMES)
                else:
                    self.g1[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = g
        # Streams: column, trail length, cycle (cells per pass), phase, level.
        self.streams = []
        for col in range(self.cols):
            n = sum(1 for _ in range(8) if rng.random() < density * (H / min(W, H)) / 8)
            for _ in range(n):
                length = rng.randint(*trail)
                cycle = max(self.rows + length + 2, round(rng.uniform(*speed) * LOOP))
                self.streams.append((col, length, cycle, rng.uniform(0, cycle),
                                     bright * rng.uniform(0.55, 1.0), rng.random() < heads))
        self.ramps = {n: ramp(np.arange(n) / max(1, n - 1)) for n in range(trail[0], trail[1] + 1)}
        self.bright = bright

    def frame(self, f):
        """(rgb canvas HxWx3, [(x, y, level) of visible heads])."""
        colour = np.zeros((self.rows, self.cols, 3), np.float32)
        heads = []
        for col, length, cycle, phase, level, show_head in self.streams:
            head = int((phase + cycle * f / FRAMES) % cycle) - 1
            rgb, alpha = self.ramps[length]
            lo, hi = max(0, head - length + 1), min(self.rows - 1, head)
            if lo > hi:
                continue
            k = head - np.arange(lo, hi + 1)            # cells behind the head
            vals = rgb[k] * (alpha[k] * level)[:, None]
            if not show_head:
                vals[k == 0] = 0
            elif 0 <= head < self.rows:
                heads.append(((col + 0.5) * self.cw, (head + 0.5) * self.ch, level))
            np.maximum(colour[lo:hi + 1, col], vals, out=colour[lo:hi + 1, col])
        on = (self.swap_period > 0) & (((f + self.swap_phase) // np.maximum(self.swap_period, 1)) % 2 == 1)
        if on.any():
            sheet = np.where(np.repeat(np.repeat(on, self.ch, 0), self.cw, 1), self.g1, self.g0)
        else:
            sheet = self.g0
        big = np.repeat(np.repeat(colour, self.ch, 0), self.cw, 1)
        return (big * sheet[..., None])[:self.H, :self.W], heads


def scene(W, H):
    rng = random.Random(f"{W}x{H}")
    k = min(W, H) / 1440
    layers = []
    for spec in LAYERS:
        spec = dict(spec, size=int(spec["size"] * k))
        layers.append(Layer(W, H, rng, **spec))
    # Vignette and the quiet band under the bar, as the stills have them.
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    v = np.clip(1.0 - 0.38 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) ** 1.2, 0.35, 1.0)
    band = np.clip((yy - still.QUIET) / still.FADE, 0.0, 1.0) ** 1.5
    return layers, (v * band)[..., None], k


def render_frame(W, H, layers, shade, k, f):
    out = np.zeros((H, W, 3), np.float32)
    glow_pts = []
    for layer in layers:
        canvas, heads = layer.frame(f)
        np.maximum(out, canvas, out=out)
        if layer.bright > 0.5:
            glow_pts += [(x, y, lv, layer.cw) for x, y, lv in heads]
    # Glow round the near heads, drawn at quarter size, blurred, added faintly.
    q = 4
    glow = Image.new("L", (W // q + 1, H // q + 1), 0)
    d = ImageDraw.Draw(glow)
    for x, y, lv, cw in glow_pts:
        r = cw * 0.9 / q
        d.ellipse((x / q - r, y / q - r, x / q + r, y / q + r), fill=int(255 * min(1.0, lv)))
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, 10 * k / q))).resize((W, H), Image.BILINEAR)
    out += (np.asarray(glow, np.float32) / 255.0)[..., None] * np.asarray(BRIGHT, np.float32) * 0.20
    out = FLOOR + (out - FLOOR) * shade
    return (np.clip(out, 0.0, PEAK) * 255.0 + 0.5).astype(np.uint8)


def logical_sizes():
    """{output: (W, H)} as the player's window will be: Hyprland's LOGICAL
    size (mode / scale, swapped when rotated). GTK3 has no fractional scale,
    so on a 2560x1080 screen at scale 0.8 the window is 3200x1350; a
    2560x1080 video there was stretched by gtksink in software every frame
    (~40% of a core) and shrunk back by the compositor. screens.py's (the
    stills' module imports it); without Hyprland, its 1920x1080 for the
    primary."""
    return still.screens.sizes(logical=True)


def encode(W, H, path, frames):
    layers, shade, k = scene(W, H)
    tmp = path + ".part.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "animation",
         "-pix_fmt", "yuv420p", "-g", str(FPS * 5), "-movflags", "+faststart", tmp],
        stdin=subprocess.PIPE)
    for f in range(frames):
        ff.stdin.write(render_frame(W, H, layers, shade, k, f).tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        sys.exit(f"ffmpeg failed for {path}")
    os.replace(tmp, path)
    print(f"{path}  {os.path.getsize(path) / 1e6:.1f} MB")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--all", action="store_true")
    p.add_argument("--only", metavar="OUTPUT", help="with --all: just this monitor")
    p.add_argument("-o", "--output")
    p.add_argument("-W", "--width", type=int, default=1720)
    p.add_argument("-H", "--height", type=int, default=720)
    p.add_argument("--seconds", type=int, default=LOOP, help="shorter test videos (not seamless)")
    p.add_argument("--frame", type=int, help="write one frame as a PNG instead")
    args = p.parse_args()
    if not shutil.which("ffmpeg") and args.frame is None:
        sys.exit("ffmpeg is needed")
    if args.all:
        for out, (W, H) in logical_sizes().items():
            if args.only and out != args.only:
                continue
            folder = os.path.join(still.WALLDIR, out)
            os.makedirs(folder, exist_ok=True)
            encode(W, H, os.path.join(folder, NAME), FRAMES)
    elif args.output and args.frame is not None:
        layers, shade, k = scene(args.width, args.height)
        Image.fromarray(render_frame(args.width, args.height, layers, shade, k, args.frame)).save(args.output)
        print(args.output)
    elif args.output:
        encode(args.width, args.height, args.output, min(FRAMES, args.seconds * FPS))
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
