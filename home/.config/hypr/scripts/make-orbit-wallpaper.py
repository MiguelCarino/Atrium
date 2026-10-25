#!/usr/bin/env python3
"""Wallpapers for the orbit theme: real photographs of space -- Earth from
Apollo and from the International Space Station, and nebulae and galaxies
from the James Webb Space Telescope -- fetched from NASA's and ESA/Webb's
own archives, checked against a known SHA-256, and cropped for each screen.
Nothing is drawn here and nothing is shipped: the pictures are downloaded
on first use and kept in the cache.

    make-orbit-wallpaper.py --all               every variant, every monitor,
                                                into the slideshow folders
    make-orbit-wallpaper.py -v cliffs -W 1720 -H 720 -o /tmp/x.jpg
    make-orbit-wallpaper.py --list              the variants
    make-orbit-wallpaper.py --credits           who took each one, and the licence

--all writes ~/Pictures/Wallpapers/<OUTPUT>/orbit-<variant>.jpg for every
screen connected now at its LOGICAL size (screens.sizes(logical=True), as
make-lofi-wallpaper.py does), the same names in every folder, so the screens
change together (wallpaper_prefix=orbit- in ~/.config/themes/orbit/
theme.conf). JPEG, not PNG: the sources are JPEG photographs, and a lossless
copy of one would be ten times the size for nothing.

Variants (SOURCES below has the archive id, the URL and the credit of each):
    earthrise   Apollo 8, 24 Dec 1968: Earth rising over the Moon (Anders)
    marble      Apollo 17, 7 Dec 1972: the whole Earth, "The Blue Marble"
    aurora      ISS Expedition 72: the aurora borealis over the night side
    nightpass   ISS Expedition 43: an aurora along the limb, cities below
    cliffs      Webb NIRCam: the "Cosmic Cliffs" of the Carina Nebula
    pillars     Webb NIRCam: the Pillars of Creation in M16
    deepfield   Webb NIRCam: SMACS 0723, Webb's First Deep Field

Licences. NASA's own photographs (Apollo, ISS) are not copyrighted in the
United States (NASA's media guidelines: free to use, credit "NASA", no
suggestion of endorsement). The Webb images are published by ESA/Webb under
Creative Commons Attribution 4.0 International (CC BY 4.0) with the credit
given in SOURCES -- `--credits` prints it, and the theme README carries it.
Neither licence allows using NASA's or ESA's logos or names to suggest they
endorse this desktop, and nothing here does.

How each picture is fitted:
  * "cover": scaled to fill the screen and cropped round a focus point (the
    fraction of the source the crop is centred on, kept inside the image),
    so the subject survives a 21:9 ultrawide and a 9:16 portrait alike;
  * "contain": the whole picture, scaled to `fill` of the screen's short
    side and centred on black -- for the Blue Marble, whose background is
    already black, so the pad is invisible and the Earth is never cut.

The rules every theme's wallpapers keep (make-moe-wallpaper.py has the long
reasons):
  * DP-1 is HDR, where SDR is mapped into the HDR range: no channel reaches
    full scale. Each picture is scaled down whole to PEAK (never clipped,
    so no colour shifts), and the big bright fields -- the Blue Marble's
    clouds, the Cosmic Cliffs' dust -- are held under FIELD_LUM by a soft
    highlight roll-off.
  * The bar sits over the top of the screen; its pills are opaque in this
    theme (themes/orbit/waybar.css) but a dark band still keeps the edges of
    the screen quiet: the top TOP_BAND px are faded towards black (to TOP_KEEP
    of their brightness at the very top).
Deterministic: the same source and size always give the same image.

Pure Pillow + numpy (both installed). The first --all downloads about 45 MB
(the cache: ~/.cache/orbit-wallpapers/); then about 20 s for every variant
on four screens.
"""

import argparse
import hashlib
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (scripts/screens.py: the screens and their sizes)

PEAK = 0.80          # brightest channel value anywhere (make-wallpaper.py: 0.78)
FIELD_LUM = 0.55     # highlights roll off above this luminance
TOP_BAND = 106       # px faded towards black under the bar (lofi's TOP_BAND)
TOP_KEEP = 0.45      # brightness left at the very top edge
QUALITY = 92         # JPEG quality, 4:4:4 (no chroma subsampling: stars stay sharp)

WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                     "orbit-wallpapers")

NASA = "https://images-assets.nasa.gov/image/{0}/{0}~orig.jpg"
WEBB = "https://cdn.esawebb.org/archives/images/{1}/{0}.jpg"
PD = "public domain in the US (NASA media guidelines)"
CCBY = "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"

# variant: (archive id, url, sha256, credit, licence, page, fit)
#   fit = ("cover", focus_x, focus_y) or ("contain", fill)
SOURCES = {
    "earthrise": ("as08-14-2383", NASA.format("as08-14-2383"),
                  "4b1484e9bb55652e30a56c03c27141938885a09e4b3c0bcabb8841e1e94ed9d9",
                  "NASA / Bill Anders, Apollo 8", PD,
                  "https://images.nasa.gov/details/as08-14-2383", ("cover", 0.47, 0.585)),
    "marble": ("as17-148-22727", NASA.format("as17-148-22727"),
               "cb4c3d2da98ee72130ebfd2ea472fc84ede6726002c2a8c9cabd86e4deea9f0f",
               "NASA, Apollo 17 crew", PD,
               "https://images.nasa.gov/details/as17-148-22727", ("contain", 1.04)),
    "aurora": ("iss072e159172", NASA.format("iss072e159172"),
               "f072bf191f5eec9ceb9458744b828bca8d7d9e4a9fcfeb68b0c8db9bceaf82a9",
               "NASA, ISS Expedition 72 crew", PD,
               "https://images.nasa.gov/details/iss072e159172", ("cover", 0.5, 0.62)),
    "nightpass": ("iss043e059141", NASA.format("iss043e059141"),
                  "c51463f7e85da60a4e9898d8e7a1dc59dba8488500cf6a1daa8b0ce8d9c57474",
                  "NASA, ISS Expedition 43 crew", PD,
                  "https://images.nasa.gov/details/iss043e059141", ("cover", 0.5, 0.55)),
    "cliffs": ("weic2205a", WEBB.format("weic2205a", "large"),
               "99771479d4d83f439c95792b54069e7fd368f416c021346b1aa85058b3ca4d79",
               "NASA, ESA, CSA, and STScI", CCBY,
               "https://esawebb.org/images/weic2205a/", ("cover", 0.5, 0.58)),
    "pillars": ("weic2216a", WEBB.format("weic2216a", "publicationjpg"),
                "d65709455d8751b4e2114db81746364a921446772b82b8da08f741d649d91418",
                "NASA, ESA, CSA, STScI; J. DePasquale, A. Koekemoer, A. Pagan (STScI)", CCBY,
                "https://esawebb.org/images/weic2216a/", ("cover", 0.48, 0.42)),
    "deepfield": ("weic2209a", WEBB.format("weic2209a", "large"),
                  "746ccafe3569b816cd6e906f89d192b61faae187af38b805853af9d3da8d40b6",
                  "NASA, ESA, CSA, and STScI", CCBY,
                  "https://esawebb.org/images/weic2209a/", ("cover", 0.5, 0.5)),
}
VARIANTS = list(SOURCES)

# Pillow refuses images over ~179 Mpx as a decompression-bomb guard; the
# Cosmic Cliffs are 123 Mpx, under it, and these are checked by hash anyway.
Image.MAX_IMAGE_PIXELS = 200_000_000


def logical_sizes():
    """{output: (W, H)} as Hyprland lays the monitors out (screens.py's)."""
    return screens.sizes(logical=True)


def source(variant):
    """The cached original for a variant, downloaded and checked on first use.
    A file whose hash is wrong is never used: it is deleted and fetched once
    more, and a second mismatch is an error (the archive changed it)."""
    ident, url, sha, *_ = SOURCES[variant]
    path = os.path.join(CACHE, f"{ident}.jpg")
    for attempt in (1, 2):
        if not os.path.exists(path):
            os.makedirs(CACHE, exist_ok=True)
            print(f"downloading {ident} ({url})", file=sys.stderr)
            req = urllib.request.Request(url, headers={"User-Agent": "make-orbit-wallpaper.py"})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp, open(path + ".part", "wb") as out:
                    while chunk := resp.read(1 << 20):
                        out.write(chunk)
            except OSError as exc:      # URLError, HTTPError, a timeout, a full disk
                # No half file left behind, and one line instead of a traceback.
                if os.path.exists(path + ".part"):
                    os.remove(path + ".part")
                raise SystemExit(f"{ident}: download failed ({exc}); {url}")
            os.replace(path + ".part", path)
        with open(path, "rb") as handle:
            if hashlib.sha256(handle.read()).hexdigest() == sha:
                return path
        os.remove(path)
    raise SystemExit(f"{ident}: the download does not match its SHA-256 ({url})")


def fit(img, W, H, how):
    """The source scaled and cropped (cover) or padded (contain) to W x H."""
    w, h = img.size
    if how[0] == "contain":
        s = how[1] * min(W, H) / max(w, h)
        img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H), (0, 0, 0))
        # Centred; whatever spills over the edges (fill > 1) is cut evenly.
        canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
        return canvas
    fx, fy = how[1], how[2]
    s = max(W / w, H / h)
    cw, ch = W / s, H / s                            # the crop, in source px
    x0 = min(max(fx * w - cw / 2, 0), w - cw)
    y0 = min(max(fy * h - ch / 2, 0), h - ch)
    return img.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))


def finish(img):
    """HDR-safe: highlights rolled off above FIELD_LUM, everything scaled to
    PEAK, the band under the bar faded towards black."""
    a = np.asarray(img, np.float32) / 255
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    # Reinhard-style shoulder above FIELD_LUM: scale the pixel (all three
    # channels together, so the hue holds) so its luminance approaches 1.0
    # smoothly instead of running straight into it.
    knee = FIELD_LUM
    over = np.maximum(lum - knee, 0)
    target = np.where(lum > knee, knee + over / (1 + over / (1 - knee)), lum)
    a *= (target / np.maximum(lum, 1e-6))[..., None]
    a *= PEAK
    H = a.shape[0]
    band = min(TOP_BAND, H // 4)
    t = np.clip(np.arange(H, dtype=np.float32) / band, 0, 1)
    a *= (TOP_KEEP + (1 - TOP_KEEP) * (t * t * (3 - 2 * t)))[:, None, None]
    return Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))


def render(W, H, variant):
    with Image.open(source(variant)) as img:
        return finish(fit(img.convert("RGB"), W, H, SOURCES[variant][6]))


def write(img, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    img.save(tmp, "JPEG", quality=QUALITY, subsampling=0, optimize=True)
    os.replace(tmp, path)
    print(path)


def credits():
    for variant, (ident, _url, _sha, who, lic, page, _fit) in SOURCES.items():
        print(f"{variant:10} {ident:15} {who}\n{'':26} {lic}\n{'':26} {page}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="every variant for every monitor folder")
    ap.add_argument("--list", action="store_true", help="the variants")
    ap.add_argument("--credits", action="store_true", help="the source, credit and licence of each")
    ap.add_argument("-v", "--variant", default="earthrise", choices=VARIANTS)
    ap.add_argument("-o", "--output", help="one image to this path")
    ap.add_argument("-W", "--width", type=int, help="default: the primary screen's (logical)")
    ap.add_argument("-H", "--height", type=int, help="default: the primary screen's (logical)")
    a = ap.parse_args()
    if a.list:
        print("\n".join(VARIANTS))
        return
    if a.credits:
        credits()
        return
    if a.all:
        for variant in VARIANTS:
            for mon, (w, h) in logical_sizes().items():
                write(render(w, h, variant), os.path.join(WALLDIR, mon, f"orbit-{variant}.jpg"))
        return
    if not a.output:
        ap.error("give -o FILE, or --all")
    if not (a.width and a.height):
        a.width, a.height = screens.primary_size(logical=True)
    write(render(a.width, a.height, a.variant), a.output)


if __name__ == "__main__":
    main()
