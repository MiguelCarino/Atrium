#!/usr/bin/env python3
"""Theme from the wallpaper: give the bar, the popup panels, the launcher,
mako and the focused-window border an accent taken from the primary screen's
wallpaper.

    theme-from-wallpaper.py              same as apply
    theme-from-wallpaper.py apply        re-pick from the wallpaper the primary
                                         shows now
                                         (does nothing while the theme is off)
    theme-from-wallpaper.py on | off     follow the wallpaper / back to the theme's
                                         own accent (plain neon in cyberpunk)
    theme-from-wallpaper.py refresh      write whichever accent is in effect now:
                                         the wallpaper's if following, else the
                                         theme's (theme.py runs this on a switch)
    theme-from-wallpaper.py custom #rrggbb|off   your own accent for the current
                                         theme (kept per theme), over both the
                                         wallpaper's and the theme's
    theme-from-wallpaper.py status       accent, and whether it follows
    theme-from-wallpaper.py pick FILE    print the accent FILE would give, change nothing

wallpaper-slideshow.py runs `apply` each time the primary's picture changes, so with
the theme on the accent follows the slideshow on its own.

Desktop themes (~/.config/hypr/scripts/theme.py) decide whether this may run
at all: "following" means BOTH the theme allows it (accent_follow=yes in its
theme.conf) and the switch is on (theme_auto in display.conf, the display
panel's "Accent from wallpaper"). The switch is the user's and survives theme
changes; a theme with accent_follow=no simply overrules it while it is
current. When not following -- or when a wallpaper has no colour worth taking
-- the accent is the theme's own `accent=` (#rrggbb), and with none of that
either, the files are left empty and the stylesheets keep their own @cyan.
A colour of your own (`custom`, the display panel's colour button;
accent_custom_<theme> in display.conf) beats all of these while that theme
is current.

Only the ACCENT moves -- the colour the theme calls @cyan: edges, glows, the
lit pill, the selected tile. The page colour, the text and the status colours
(green good / yellow warn / magenta bad) never do, so a warning still looks
like a warning on any wallpaper, and the per-monitor workspace tints stay the
colour of their monitor.

How the colour is picked
------------------------
The image is shrunk to ~160 px and every pixel votes for its hue with a weight
of saturation x value, so a few vivid pixels outvote a large grey sky; the hue
with the most weight wins. It is then pushed to neon (high saturation, full
value) and, for the dark hues (blue, violet), lifted towards white until it is
bright enough to read on the near-black glass the way cyan does. A wallpaper with
no real colour in it (weight below MIN_VIVID) gives no accent at all, and the
theme stays neon rather than inventing one.

Where it goes
-------------
    ~/.config/waybar/generated/accent.css    @define-color cyan ...; imported
                                             near the end of style.css,
                                             panel.css and hypr/scripts/
                                             launcher.css -- only the desktop
                                             theme's generated/theme*.css
                                             comes after it
    ~/.config/mako/generated/accent          border/progress colours, include=d
                                             by mako/config; then makoctl reload
    display.py accent #rrggbb                the window border (lua/display.lua)

Both generated/ folders are left out of the dotfiles repo by sync.sh.
"""

import colorsys
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme  # noqa: E402  (theme.conf: accent, accent_follow)
import screens  # noqa: E402  (the primary screen: whose wallpaper is followed)

HOME = os.path.expanduser("~")
SLIDESHOW_STATE = os.path.join(HOME, ".cache/wallpaper-slideshow.json")
FALLBACK_WALLPAPER = os.path.join(HOME, "Pictures/Wallpapers/dp1-ultrawide.png")
WAYBAR_ACCENT = os.path.join(HOME, ".config/waybar/generated/accent.css")
MAKO_ACCENT = os.path.join(HOME, ".config/mako/generated/accent")
DISPLAY = os.path.join(HOME, ".config/hypr/scripts/display.py")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state"),
                     "hypr", "display.conf")

SAMPLE = 160            # px on the long side; plenty for a hue vote
HUE_BINS = 36           # 10 degrees each
MIN_VIVID = 0.04        # mean saturation*value below this = "no colour in it"
NEON_S, NEON_V = 0.82, 1.0
MIN_LUMINANCE = 0.35  # relative luminance; cyan is ~0.75, the theme's dimmest neon ~0.3


# -- state (shared with display.py; the format is in lua/shared.lua) ----------
def read_state():
    state = {}
    try:
        with open(STATE) as handle:
            for line in handle:
                key, sep, value = line.partition("=")
                if sep:
                    state[key.strip()] = value.strip()
    except OSError:
        pass
    return state


def set_state(key, value):
    state = read_state()
    state[key] = value
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        for k in sorted(state):
            if state[k] != "":
                handle.write(f"{k}={state[k]}\n")
    os.replace(tmp, STATE)


def custom():
    """Your own accent for the current theme, or ""."""
    value = read_state().get(f"accent_custom_{theme.current()}", "")
    return value if len(value) == 7 and value.startswith("#") else ""


def following():
    """The theme allows it AND the switch is on (see the top of this file),
    and no colour of your own is set for this theme."""
    return theme.following() and not custom()


# -- colour ------------------------------------------------------------------
def current_wallpaper():
    try:
        with open(SLIDESHOW_STATE) as handle:
            path = json.load(handle).get(screens.primary())
        if path and os.path.exists(path):
            return path
    except (OSError, ValueError):
        pass
    return FALLBACK_WALLPAPER if os.path.exists(FALLBACK_WALLPAPER) else None


def pick_accent(path):
    """'#rrggbb', or None when the image has no colour worth taking."""
    with Image.open(path) as image:
        # A JPEG decoded at 1/2..1/8 scale straight away (draft): a 4K
        # wallpaper no longer costs its full-size RGB copy (the slideshow's
        # cgroup peaked at ~900 MB). A no-op for other formats.
        image.draft("RGB", (SAMPLE * 2, SAMPLE * 2))
        image = image.convert("RGB")
        image.thumbnail((SAMPLE, SAMPLE))
        rgb = np.asarray(image, dtype=np.float32) / 255.0
    rgb = rgb.reshape(-1, 3)
    mx, mn = rgb.max(axis=1), rgb.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    weight = sat * mx
    if weight.mean() < MIN_VIVID:
        return None

    # Hue in [0, 1), the usual hexcone formula, vectorised.
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    delta = np.maximum(mx - mn, 1e-6)
    hue = np.where(mx == r, ((g - b) / delta) % 6,
          np.where(mx == g, (b - r) / delta + 2, (r - g) / delta + 4)) / 6.0

    bins = np.floor(hue * HUE_BINS).astype(int) % HUE_BINS
    votes = np.bincount(bins, weights=weight, minlength=HUE_BINS)
    # Smooth over neighbours so a hue that straddles two bins is not split.
    votes = votes + 0.5 * (np.roll(votes, 1) + np.roll(votes, -1))
    best = int(votes.argmax())
    # The weighted circular mean of the hues inside the winning bin.
    inside = bins == best
    angle = hue[inside] * 2 * np.pi
    w = weight[inside]
    mean = np.arctan2((np.sin(angle) * w).sum(), (np.cos(angle) * w).sum())
    h = (mean / (2 * np.pi)) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(h, NEON_S, NEON_V)
    # Blue and violet at full value are still dark (cyan's luminance is ~0.75,
    # pure blue's ~0.07), and glows and thin edges in them vanish on the black
    # glass. Lift towards white until it is as legible as the theme needs.
    for _ in range(20):
        if 0.2126 * red + 0.7152 * green + 0.0722 * blue >= MIN_LUMINANCE:
            break
        red, green, blue = (c + (1 - c) * 0.08 for c in (red, green, blue))
    return "#{:02x}{:02x}{:02x}".format(round(red * 255), round(green * 255), round(blue * 255))


# -- outputs -----------------------------------------------------------------
def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)       # waybar watches this file; never show it half-written


BASE_CYAN = "#00f0ff"       # the base stylesheets' own @cyan, for a theme with no accent at all


def ambient_tint(accent):
    """The ambient desktop's warmth (ambient.py, Settings > Ambient) laid
    over whichever accent won: a few degrees of hue towards amber at night,
    towards blue in a focus block. A theme with no accent gets the tint on
    the base neon. Unchanged -- and nothing imported -- while ambient's
    accent is off (its runtime file is missing)."""
    if not os.path.exists(os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}",
                                       "ambient-accent.conf")):
        return accent
    try:
        import ambient
        out = ambient.tinted(accent or BASE_CYAN)
        return accent if (not accent and out == BASE_CYAN) else out
    except Exception:       # noqa: BLE001 -- the ambient desktop failing must not stop the accent
        return accent


def write_outputs(accent, source=""):
    """accent None = your own for this theme, else the theme's accent= (or
    none at all)."""
    if not accent and custom():
        accent, source = custom(), "your own colour"
    if not accent:
        own = theme.get("accent")
        if own and len(own) == 7 and own.startswith("#"):
            accent, source = own.lower(), f"theme '{theme.current()}' (accent=)"
    accent = ambient_tint(accent)
    if accent:
        write(WAYBAR_ACCENT,
              f"/* GENERATED by theme-from-wallpaper.py from {os.path.basename(source)}"
              " -- do not edit. */\n"
              f"@define-color cyan {accent};\n")
        write(MAKO_ACCENT,
              f"# GENERATED by theme-from-wallpaper.py -- do not edit.\n"
              f"border-color={accent.upper()}B3\n"
              f"progress-color=over {accent.upper()}59\n")
    else:
        write(WAYBAR_ACCENT, "/* GENERATED by theme-from-wallpaper.py -- no accent: the stylesheets' own. */\n")
        write(MAKO_ACCENT, "# GENERATED by theme-from-wallpaper.py -- no accent: mako/config's own.\n")
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    theme.apply_apps(accent)        # Qt, Firefox, Chrome (theme.py "other apps")
    # Each on its own: a stuck mako must not cost the display its accent.
    # The files are written either way; a hung one picks them up later.
    for argv, extra, timeout in ((["makoctl", "reload"], {}, 10),
                                 ([DISPLAY, "accent", accent or "off"],
                                  {"env": dict(os.environ, DISPLAY_QUIET="1")}, 60)):
        try:
            subprocess.run(argv, **quiet, **extra, timeout=timeout)
        except subprocess.TimeoutExpired:
            pass


# -- commands ----------------------------------------------------------------
def apply(force=False):
    if not (force or following()):
        return
    path = current_wallpaper()
    accent = pick_accent(path) if path else None
    write_outputs(accent, path or "")
    print(accent or "none (neon)")


def main(argv):
    cmd = argv[0] if argv else "apply"
    if cmd == "apply":
        apply()
    elif cmd == "on":
        set_state("theme_auto", "on")
        apply(force=True)
    elif cmd == "off":
        set_state("theme_auto", "off")
        write_outputs(None)
    elif cmd == "refresh":
        if following():
            apply(force=True)
        else:
            write_outputs(None)
    elif cmd == "custom" and len(argv) == 2:
        value = argv[1].lower()
        if value != "off" and not (len(value) == 7 and value.startswith("#")
                                   and all(c in "0123456789abcdef" for c in value[1:])):
            sys.exit("custom: #rrggbb or off")
        set_state(f"accent_custom_{theme.current()}", "" if value == "off" else value)
        main(["refresh"])
    elif cmd == "status":
        print(json.dumps({"following": following(), "custom": custom(),
                          "allowed": theme.get("accent_follow") == "yes",
                          "accent": read_state().get("accent", ""),
                          "wallpaper": current_wallpaper()}))
    elif cmd == "pick" and len(argv) == 2:
        print(pick_accent(argv[1]) or "none (neon)")
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
