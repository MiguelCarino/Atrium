#!/usr/bin/env python3
"""Size the toolbox box to its card, and put it where its button is.

The toolbox is a horizontal waybar (so its tray runs in a row -- see
config-toolbox), which layer-shell anchors left + right and stretches between
its margins; its height follows the content. Every pixel of it takes clicks
-- including any transparent part beside the card, where a click neither
reaches the desktop nor closes the section. So the margins are worked out
from how wide the card is, and that depends on the tray row once it outgrows
the other rows.

Writes ../generated/toolbox-margin.jsonc (pulled in by config-toolbox's
"include": the bar's "position" and "margin", which is why config-toolbox has
no "position" of its own -- waybar takes from an include only the keys the
config lacks) and exits 0 if it changed, so toolbox.sh knows to restart the
toolbox waybar before showing it; 1 if it was already right.

WHERE IT GOES. Two places, after where the button that opens it is:

  * the top bar's sliders pill (custom/toolbox): "position": "top", the
    card dropping down under the pill. The usual case.
  * the dock's or the taskbar's toolbox button (hypr/scripts/dock.py), while
    the dock engine is running: the top bar's pill is hidden then
    (toolbox.sh status), so the card opens from the bottom, "position":
    "bottom", next to that button. dock.py writes where the button is to
    $XDG_RUNTIME_DIR/dock-toolbox.json (DOCK_BUTTON below: its pid, screen,
    layout, edge, the bar's and the button's rectangles and the strip it
    reserves) and removes it when it stops; a file whose pid is gone is
    left over from a crash and counts as no dock. Which edge:
      bottom (the taskbar, a bottom dock)  above the button, the card's
               right edge flush with the button's: the taskbar's button is
               next to the tray at the right, the dock's is its last item
      left / right (a side dock)  beside the dock, the card's bottom level
               with the button's bottom, opening upwards -- the toolbox has
               to stay a horizontal bar (top or bottom) for its tray row, and
               a bottom bar's margins can put the card anywhere, so it goes
               beside the button rather than at some screen corner.
    A dock or taskbar that reserves its strip (the taskbar, a dock that
    never hides) already pushes the card's anchor edge in, so only GAP is
    added; a hiding dock reserves nothing and the card clears it by its own
    thickness.

Neither the margins nor the card's width is fixed, because both change with
the desktop theme (its font, padding, how wide the power pill is) and with
what is open:

  * the anchor: under the sliders pill, its right edge found from where the
    click that opened it landed (hyprctl cursorpos, when it is in the bar
    strip of the toolbox's screen). Within TOLERANCE of the edge already
    written, that one is kept, so clicking another spot of the same pill does
    not mean a restart. Opened from a key, the edge stays. It is remembered
    as TOP_KEY in the cache, so a dock switched off finds it again. At the
    dock: from DOCK_BUTTON, not the click. A dock grows and shrinks around
    its centre as apps open and close, which slides its last button along,
    so the card stays put while the button has moved by at most DOCK_SLACK
    -- the card is still beside it -- and the toolbox waybar is restarted
    only when the dock is switched on or off or changes layout, edge or
    autohide (dock.py runs `toolbox.sh refit` then), or at a click once the
    button has wandered further than that.
  * the card's width: measured. A layer surface narrower than its content
    grows past its margins, so `measure` (toolbox.sh, right after the card is
    shown) reads the real width off `hyprctl layers` and keeps it per theme
    in ~/.local/state/hypr/toolbox-fit.json (card_key: per theme, and per
    dock layout and top bar, which change the card's rows). A theme not measured yet starts
    from PROBE_W, narrower than any card, so the first open always measures.
    measure exits 0 when the fit changed (toolbox.sh then refits and shows
    the card again), 1 when it was right.

    toolbox_fit.py            fit before opening (or on toolbox.sh refit)
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
DOCK_BUTTON = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}",
                           "dock-toolbox.json")
MARGIN_TOP = 4
MARGIN_RIGHT = 58       # before any click has placed it
BAR_H = 40              # a click above this is on the bar
PILL_HALF = 15          # the cursor is somewhere on the pill: its middle, give or take
TOLERANCE = 16
PROBE_W = 120           # an unmeasured theme's card: too narrow on purpose
TOP_KEY = "@top_right"  # the cache's entry for the sliders pill's edge (no theme is named so)
GAP = 6                 # between the dock (or taskbar) and the card
EDGE = 4                # the card never closer than this to a screen edge
DOCK_SLACK = 96         # px the dock's button may slide before the card follows it

# The tray row's icons are 18 px (icon-size) with 10 px between (spacing);
# the rows' 150 px min-width covers five, each one after widens the card.
ROW_W = 150
PER_ICON = 28           # icon-size + spacing
SPACING = 10


# -- pure ---------------------------------------------------------------------
def tray_extra(items):
    return max(0, PER_ICON * items - SPACING - ROW_W)


def margin_text(place):
    """The generated file for a placement {"position", "margin": (top,
    right, bottom, left)}."""
    top, right, bottom, left = place["margin"]
    return ("// GENERATED by scripts/toolbox_fit.py -- do not edit.\n"
            f'{{ "position": "{place["position"]}", "margin": "{top} {right} {bottom} {left}" }}\n')


def parse_margin(text):
    """margin_text's placement back, or None. An older file without a
    "position" was a top one."""
    m = re.search(r'"margin":\s*"(\d+) (\d+) (\d+) (\d+)"', text or "")
    if not m:
        return None
    pos = re.search(r'"position":\s*"(top|bottom)"', text)
    return {"position": pos.group(1) if pos else "top", "margin": tuple(int(v) for v in m.groups())}


def top_place(width, right, card):
    """Under the sliders pill: right margin `right`, as wide as the card."""
    return {"position": "top", "margin": (MARGIN_TOP, right, 0, max(width - right - card, 0))}


def live_dock(data, alive):
    """The DOCK_BUTTON record, its rectangles as tuples, if it is whole and
    its dock still runs (alive(pid)); else None."""
    if not isinstance(data, dict):
        return None
    try:
        pid = int(data.get("pid"))
        rects = [tuple(int(v) for v in data[k]) for k in ("monitor", "bar", "button")]
        reserved = max(0, int(data.get("reserved") or 0))
    except (TypeError, ValueError, KeyError):
        return None
    if any(len(r) != 4 for r in rects) or data.get("position") not in ("bottom", "left", "right"):
        return None
    if not alive(pid):
        return None
    return dict(data, monitor=rects[0], bar=rects[1], button=rects[2], reserved=reserved)


def dock_place(dock, card, current=None, slack=DOCK_SLACK):
    """Next to the dock's or taskbar's toolbox button (the docstring's
    WHERE IT GOES). dock is a live_dock() record (layout coordinates),
    card the card's width, current the placement written now: its margin
    along the dock (the right one under a bottom dock, the bottom one beside
    a side dock) is kept while the button is within `slack` of where it
    would put the card now."""
    mx, my, mw, mh = dock["monitor"]
    bar_x, bar_y, bar_w, _bar_h = dock["bar"]
    bx, by, bw, bh = dock["button"]
    bar_x, bar_y, bx, by = bar_x - mx, bar_y - my, bx - mx, by - my
    edge, zone = dock["position"], dock["reserved"]
    # The strip the toolbox may use: layer-shell measures a surface's
    # margins from inside the zones other surfaces reserve.
    area_l = zone if edge == "left" else 0
    area_r = mw - zone if edge == "right" else mw
    area_b = mh - zone if edge == "bottom" else mh
    if edge == "bottom":
        x1 = bx + bw                        # the card's right edge, flush with the button's
        y1 = bar_y - GAP                    # its bottom, just above the bar
    else:
        x1 = (bar_x + bar_w + GAP + card) if edge == "left" else (bar_x - GAP)
        y1 = by + bh                        # its bottom, level with the button's
    x1 = max(area_l + EDGE + card, min(area_r - EDGE, x1))
    y1 = max(EDGE, min(area_b, y1))
    right, bottom = area_r - x1, area_b - y1
    if current and current.get("position") == "bottom":
        _top, c_right, c_bottom, _left = current["margin"]
        if edge == "bottom" and abs(c_right - right) <= slack and c_right + card <= area_r - area_l:
            right = c_right
        elif edge != "bottom" and abs(c_bottom - bottom) <= slack:
            bottom = c_bottom
    left = max(area_r - area_l - right - card, 0)
    return {"position": "bottom", "margin": (0, right, bottom, left)}


# -- the machine --------------------------------------------------------------
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


def card_key(cfg=None):
    """What a measured width is kept under: the theme, and with the dock
    engine on its layout and whether the top bar is off -- those change
    which rows the card has (bar-settings.py toolbox-config-path). A width
    is only ever measured upwards (a layer surface is never narrower than
    its margins make it), so a card that got narrower needs a key of its
    own to be measured again."""
    key = theme()
    try:
        if cfg is None:
            sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
            import dock
            cfg = dock.read_settings()
        if cfg.get("enabled"):
            key += f"|{cfg.get('layout')}" + ("|nobar" if not cfg.get("top_bar", True) else "")
    except Exception:         # noqa: BLE001 - no dock: the theme's own
        pass
    return key


def load(path, default):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as handle:
        json.dump(cache, handle)


def written():
    """The placement in the generated file, or None."""
    try:
        with open(OUT) as handle:
            return parse_margin(handle.read())
    except OSError:
        return None


def pid_alive(pid):
    return pid > 0 and os.path.exists(f"/proc/{pid}")


def dock_button(output):
    """The dock's toolbox button (DOCK_BUTTON) when a dock runs and has it
    on the toolbox's screen; else None, and the top bar's pill is the
    button. (A dock on another screen than the bar: the card stays under
    the top bar's corner, the pill's place.)"""
    dock = live_dock(load(DOCK_BUTTON, None), pid_alive)
    return dock if dock and dock.get("output") == output else None


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


def fit(follow_click=True):
    """Write the placement for now; True when it changed. follow_click
    False (measure): the sliders pill's edge as it is, no cursor read."""
    mon = toolbox_monitor()
    cache = load(CACHE, {})
    card = cache.get(card_key(), PROBE_W) + tray_extra(tray_items())
    current = written()
    dock = dock_button(mon["name"] if mon else toolbox_output())
    if dock is not None:
        return write(margin_text(dock_place(dock, card, current)))
    width = usable_width(mon)
    edge = cache.get(TOP_KEY)
    if not isinstance(edge, int):
        edge = current["margin"][1] if current and current["position"] == "top" else MARGIN_RIGHT
    right = right_margin(mon, width, edge) if follow_click else edge
    if right != cache.get(TOP_KEY):
        cache[TOP_KEY] = right
        save_cache(cache)
    return write(margin_text(top_place(width, right, card)))


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
    key = card_key()
    if cache.get(key) == base:
        return False
    cache[key] = base
    save_cache(cache)
    return fit(follow_click=False)


def main():
    if sys.argv[1:] == ["measure"]:
        sys.exit(0 if measure() else 1)
    sys.exit(0 if fit() else 1)


if __name__ == "__main__":
    main()
