#!/usr/bin/env python3
"""Render the moe theme's MOVING wallpaper: sakura petals drifting down over
the sakura-day picture, as a seamless video loop per monitor, played by
wallpaper-slideshow.py (wallpaper-motion.py) behind the windows.

    make-moe-sakura.py --all                  moe-sakura.mp4 for every monitor
                                              folder (a minute or two each)
    make-moe-sakura.py --only DP-2 --all      one monitor (by connector name)
    make-moe-sakura.py -W 1720 -H 720 --seconds 6 -o /tmp/x.mp4
    make-moe-sakura.py -W 1720 -H 720 --frame 40 -o /tmp/x.png
                                              one still frame, for a look

--all writes ~/Pictures/Wallpapers/<OUTPUT>/moe-sakura.mp4 at each monitor's
LOGICAL size (make-moe-wallpaper.py's logical_sizes(): the mode over the
scale, turned when rotated): the name in wallpaper_video= in
~/.config/themes/moe/theme.conf. The background is make-moe-wallpaper.py's
sakura-day picture at the same size, rendered here through that script (so
the two never disagree); the stills (moe-*.png) are what hyprpaper shows
under the video, and all there is while it is off or stopped.

The petals: three depths -- far (small, faint, slowest), mid, near (bigger,
nearly opaque) -- each petal falling down the whole screen once per loop on
a gentle sine sway, turning, and TUMBLING (its width breathes with a cosine,
a petal seen edge-on and then flat again). Calm on purpose: one screen
height in 30 s is ~50 px a second on a 1440 px screen, nothing darts.

Seamless: the loop is LOOP seconds, every petal crosses its fall (screen
plus a margin above and below) exactly once in it, and its sway, turn and
tumble run a whole number of cycles in it, so the last frame runs into the
first. Petals fade under the bar (make-moe-wallpaper.py's QUIET/FADE band).
Deterministic: same size, same video.

Sprites: make-moe-wallpaper.py's petal_sprite, pre-rendered per depth at 24
turns x 6 tumble widths and cached; each frame is the background plus ~100
small alpha blits (numpy), piped to ffmpeg (libx264, as make-matrix-rain.py:
decoded in software by the player, cheap at 10 fps).
"""

import argparse
import importlib.util
import math
import os
import random
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("moe_still", os.path.join(HERE, "make-moe-wallpaper.py"))
still = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(still)

FPS = 10
LOOP = 30                           # seconds
FRAMES = FPS * LOOP
NAME = "moe-sakura.mp4"
TURNS = 24                          # pre-rendered rotations per sprite
TUMBLES = 6                         # pre-rendered widths (edge-on .. flat)

# (petal length at k=1, petals per 3440x1440, alpha, colour, sway amplitude at k=1)
DEPTHS = [
    (14, 60, 0.60, "#f2b6cf", 26),
    (21, 36, 0.82, "#f4a3c4", 40),
    (30, 16, 0.94, "#f392ba", 60),
]


class Petal:
    def __init__(self, rng, W, H, k, depth):
        length, _n, self.alpha, colour, sway = depth
        self.key = (round(length * k), colour)
        self.x0 = rng.uniform(-0.05, 1.05) * W
        self.margin = 4 * length * k
        self.phase = rng.random()                       # where in its fall at frame 0
        self.sway = sway * k * rng.uniform(0.6, 1.0)
        self.sway_n = rng.choice((1, 2, 3))             # whole cycles per loop
        self.sway_ph = rng.uniform(0, 2 * math.pi)
        self.turn_n = rng.choice((-2, -1, 1, 2))        # whole turns per loop
        self.turn0 = rng.random()
        self.tumble_n = rng.choice((2, 3, 4))
        self.tumble_ph = rng.uniform(0, 2 * math.pi)

    def at(self, f, H):
        t = f / FRAMES
        u = (self.phase + t) % 1.0
        y = -self.margin + u * (H + 2 * self.margin)
        x = self.x0 + self.sway * math.sin(2 * math.pi * self.sway_n * t + self.sway_ph)
        turn = int(((self.turn0 + self.turn_n * t) % 1.0) * TURNS) % TURNS
        flat = abs(math.cos(2 * math.pi * self.tumble_n * t + self.tumble_ph))
        tumble = min(TUMBLES - 1, int(flat * TUMBLES))
        return x, y, turn, tumble


class Sprites:
    def __init__(self):
        self.cache = {}

    def get(self, key, alpha, turn, tumble):
        ck = (key, alpha, turn, tumble)
        if ck not in self.cache:
            length, colour = key
            base = still.petal_sprite(length, colour, alpha)
            w = max(1, int(base.width * (0.25 + 0.75 * (tumble + 0.5) / TUMBLES)))
            img = base.resize((w, base.height), Image.LANCZOS)
            img = img.rotate(360 * turn / TURNS, resample=Image.BICUBIC, expand=True)
            a = np.asarray(img, np.float32) / 255
            self.cache[ck] = (a[..., :3], a[..., 3:4])
        return self.cache[ck]


def scene(W, H):
    rng = random.Random(f"moe-sakura-{W}x{H}")
    k = min(W, H) / 1440
    area = W * H / (3440 * 1440)
    petals = []
    for depth in DEPTHS:
        petals += [(Petal(rng, W, H, k, depth), depth) for _ in range(max(3, int(depth[1] * area)))]
    bg = np.asarray(still.render(W, H, "sakura-day"), np.float32) / 255
    band = still.detail_band(H)[:, 0, 0]
    return bg, petals, band


def render_frame(W, H, bg, petals, band, sprites, f):
    out = bg.copy()
    for petal, depth in petals:
        x, y, turn, tumble = petal.at(f, H)
        rgb, a = sprites.get(petal.key, petal.alpha, turn, tumble)
        h, w = a.shape[:2]
        x0, y0 = int(x - w / 2), int(y - h / 2)
        xa, ya = max(0, x0), max(0, y0)
        xb, yb = min(W, x0 + w), min(H, y0 + h)
        if xa >= xb or ya >= yb:
            continue
        sa = a[ya - y0:yb - y0, xa - x0:xb - x0] * band[ya:yb, None, None]
        region = out[ya:yb, xa:xb]
        region *= 1 - sa
        region += rgb[ya - y0:yb - y0, xa - x0:xb - x0] * sa
    out = out / np.maximum(out.max(axis=-1, keepdims=True) / still.PEAK, 1.0)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def encode(W, H, path, frames):
    bg, petals, band = scene(W, H)
    sprites = Sprites()
    tmp = path + ".part.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "film",
         "-pix_fmt", "yuv420p", "-g", str(FPS * 5), "-movflags", "+faststart", tmp],
        stdin=subprocess.PIPE)
    for f in range(frames):
        ff.stdin.write(render_frame(W, H, bg, petals, band, sprites, f).tobytes())
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
        for out, (W, H) in still.logical_sizes().items():
            if args.only and out != args.only:
                continue
            folder = os.path.join(still.WALLDIR, out)
            os.makedirs(folder, exist_ok=True)
            encode(W, H, os.path.join(folder, NAME), FRAMES)
    elif args.output and args.frame is not None:
        bg, petals, band = scene(args.width, args.height)
        Image.fromarray(render_frame(args.width, args.height, bg, petals, band, Sprites(), args.frame)).save(args.output)
        print(args.output)
    elif args.output:
        encode(args.width, args.height, args.output, min(FRAMES, args.seconds * FPS))
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
