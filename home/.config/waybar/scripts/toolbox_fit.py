#!/usr/bin/env python3
"""Size the toolbox box to its card.

The toolbox is a top waybar (so its tray runs in a row -- see config-toolbox),
which layer-shell anchors left + right and stretches between its margins; its
height follows the content. Every pixel of it takes clicks -- including any
transparent part beside the card, where a click neither reaches the desktop
nor closes the section. So the left margin is worked out from how wide the
card is, and that depends on the tray row once it outgrows the other rows.

Writes ../generated/toolbox-margin.jsonc (pulled in by config-toolbox's
"include") and exits 0 if it changed, so toolbox.sh knows to reload the
toolbox waybar before showing it; 1 if it was already right.

Neither number is fixed, because both change with the desktop theme (its font,
padding, how wide the power pill is):

  * the right edge: the card's right edge goes under the sliders pill, found
    from where the click that opened it landed (hyprctl cursorpos, when it is
    in the bar strip of the toolbox's screen). Within TOLERANCE of the edge
    already written, that one is kept, so clicking another spot of the same
    pill does not mean a restart. Opened from a key, the edge stays.
  * the card's width: measured. A layer surface narrower than its content
    grows past its margins, so `measure` (toolbox.sh, right after the card is
    shown) reads the real width off `hyprctl layers` and keeps it per theme
    in ~/.local/state/hypr/toolbox-fit.json. A theme not measured yet starts
    from PROBE_W, narrower than any card, so the first open always measures.
    measure exits 0 when the fit changed (toolbox.sh then refits and shows
    the card again), 1 when it was right.

    toolbox_fit.py            fit before opening
    toolbox_fit.py measure    after opening
"""

import json
import os
import re
import subprocess
import sys

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "generated", "toolbox-margin.jsonc")
CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config-toolbox")
CACHE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "toolbox-fit.json")
DISPLAY_STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                             "hypr", "display.conf")
MARGIN_TOP = 4
MARGIN_RIGHT = 58       # before any click has placed it
BAR_H = 40              # a click above this is on the bar
PILL_HALF = 15          # the cursor is somewhere on the pill: its middle, give or take
TOLERANCE = 16
PROBE_W = 120           # an unmeasured theme's card: too narrow on purpose

# The tray row's icons are 18 px (icon-size) with 10 px between (spacing);
# the rows' 150 px min-width covers five, each one after widens the card.
ROW_W = 150
PER_ICON = 28           # icon-size + spacing
SPACING = 10


def tray_items():
    try:
        out = subprocess.run(
            ["busctl", "--user", "--json=short", "get-property",
             "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
             "org.kde.StatusNotifierWatcher", "RegisteredStatusNotifierItems"],
            capture_output=True, text=True, timeout=2).stdout
        return len(json.loads(out)["data"])
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        return 1


def hypr(*args):
    return json.loads(subprocess.run(["hyprctl", *args, "-j"], capture_output=True,
                                     text=True, timeout=2).stdout)


def toolbox_output():
    """The screen the toolbox is on: config-toolbox's "output" line, which
    Settings > Bar & toolbox (hypr/scripts/bar-settings.py screen) moves
    together with the bar's."""
    try:
        with open(CONFIG) as handle:
            for line in handle:
                m = re.match(r'^\s*"output"\s*:\s*"([^"]+)"', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    # No "output" line: the primary screen (hypr/scripts/screens.py), where
    # the bar goes by default.
    sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
    import screens
    return screens.primary()


def toolbox_monitor():
    output = toolbox_output()
    try:
        for mon in hypr("monitors"):
            if mon["name"] == output:
                return mon
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        pass
    return None


def usable_width(mon):
    """Monitor width in layout pixels."""
    if mon is None:
        return 3440
    transformed = mon["transform"] % 2 == 1
    return int((mon["height"] if transformed else mon["width"]) / mon["scale"])


def theme():
    try:
        with open(DISPLAY_STATE) as handle:
            for line in handle:
                if line.startswith("theme="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def load(path, default):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def written():
    """(right, left) margins in the generated file, or None."""
    try:
        with open(OUT) as handle:
            m = re.search(r'"margin":\s*"\d+ (\d+) \d+ (\d+)"', handle.read())
        return (int(m.group(1)), int(m.group(2))) if m else None
    except OSError:
        return None


def tray_extra(items):
    return max(0, PER_ICON * items - SPACING - ROW_W)


def right_margin(mon, width, current):
    """Under the pill the click landed on; else where it was."""
    try:
        x, y = (int(v) for v in subprocess.run(["hyprctl", "cursorpos"], capture_output=True,
                                                text=True, timeout=2).stdout.split(","))
    except (subprocess.SubprocessError, OSError, ValueError):
        return current
    if mon is None or not (mon["x"] <= x < mon["x"] + width and mon["y"] <= y < mon["y"] + BAR_H):
        return current
    want = max(MARGIN_TOP, width - (x - mon["x"] + PILL_HALF))
    return current if abs(want - current) <= TOLERANCE else want


def write(text):
    try:
        with open(OUT) as handle:
            if handle.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, OUT)
    return True


def fit(right=None):
    mon = toolbox_monitor()
    width = usable_width(mon)
    current = (written() or (MARGIN_RIGHT, 0))[0]
    if right is None:
        right = right_margin(mon, width, current)
    card = load(CACHE, {}).get(theme(), PROBE_W) + tray_extra(tray_items())
    left = max(width - right - card, 0)
    return write("// GENERATED by scripts/toolbox_fit.py -- do not edit.\n"
                 f'{{ "margin": "{MARGIN_TOP} {right} 0 {left}" }}\n')


def measure():
    """The card as drawn (the toolbox is showing): keep its width for this
    theme; True when that moves the fit."""
    try:
        shown = [layer["w"] for mon in hypr("layers").values() for level in mon["levels"].values()
                 for layer in level if layer["namespace"] == "waybar-toolbox"]
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, AttributeError):
        return False
    if not shown:
        return False
    base = shown[0] - tray_extra(tray_items())
    cache = load(CACHE, {})
    if cache.get(theme()) == base:
        return False
    cache[theme()] = base
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as handle:
        json.dump(cache, handle)
    return fit(right=(written() or (MARGIN_RIGHT, 0))[0])


def main():
    if sys.argv[1:] == ["measure"]:
        sys.exit(0 if measure() else 1)
    sys.exit(0 if fit() else 1)


if __name__ == "__main__":
    main()
