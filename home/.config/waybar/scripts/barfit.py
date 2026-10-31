#!/usr/bin/env python3
"""Is this bar on a narrow screen? The pills that can say less ask once.

    barfit.py narrow        "yes" or "no" for the bar this runs under
    barfit.py vbars N...    the meters' markup for these percentages

The centre capsules (date, clock, weather, updates ...) and the island that
opens out of them are only centred while neither side of the bar is wider
than half of what the capsules leave: GTK gives each side at most that half,
and a side that will not shrink to it pushes the centre group over (the
island then opens beside it, not over it). Made on a 3440 px ultrawide, the
right side was a good 100-200 px too wide on a 1920 px laptop, depending on
the theme. So on a screen narrower than NARROW_BELOW (logical px) the pills
that carry a second figure drop it -- the CPU's RAM, the GPU's VRAM; their
panels still show both.

Which screen: waybar hands every custom module's exec the name of its bar's
output in WAYBAR_OUTPUT_NAME, and a bar that moves to another screen is a
new bar with new scripts, so asking once at the start is enough. Without it
(a script run by hand), the primary (screens.py). Without Hyprland, not
narrow: the bar as it always was.

Never in the toolbox card (in_card): its pills (the top bar's, with the top
bar off: bar-settings.py card_lines) have the card's width to themselves and
nothing to keep centred, so they say everything there. The card's scripts
run in waybar-toolbox.service's cgroup, which is how they know.
"""
import os
import sys

HYPR = os.path.expanduser("~/.config/hypr/scripts")
if HYPR not in sys.path:
    sys.path.insert(0, HYPR)

NARROW_BELOW = 2560


def width(output=None, mons=None):
    """The logical width of the bar's screen, or None when it is not known."""
    try:
        import screens
        if mons is None:
            mons = screens.hyprctl_monitors()
        name = output or os.environ.get("WAYBAR_OUTPUT_NAME") or screens.primary(mons=mons)
    except Exception:       # noqa: BLE001 - no Hyprland, no screens.py: the usual bar
        return None
    for m in mons:
        if m.get("name") == name:
            return screens.logical_size(m.get("width", 0), m.get("height", 0),
                                        float(m.get("scale") or 1), int(m.get("transform") or 0))[0]
    return None


CARD_UNIT = "/waybar-toolbox.service"


def in_card(cgroup_path="/proc/self/cgroup"):
    """Whether this runs under the toolbox waybar (its cgroup)."""
    try:
        with open(cgroup_path) as fh:
            return any(line.rstrip().endswith(CARD_UNIT) for line in fh)
    except OSError:
        return False


def narrow(output=None, mons=None):
    if in_card():
        return False
    w = width(output, mons)
    return w is not None and w < NARROW_BELOW


# Vertical meters (vbars.sh draws the same for the shell pills; keep the two
# equal -- tests/test_bar_pills.py checks): 4 segments of 25%, bottom up, one
# short markup line each, a pair of lower-half blocks per segment (the empty
# upper half is the gap). Lit: `colour` (None: the pill's own CSS colour);
# unlit: the same, faint. Above 0 lights the first segment.
VB_SEG = "\u2584\u2584"
VB_CAP = "\u2582\u2582"           # a battery's terminal, over the top segment
VB_CAP_SIZE = 1600
VB_FAINT = "28%"
VB_OPEN = "<span font_family='monospace' size='4000' line_height='0.75'>"


def lit(percent):
    try:
        v = max(0, min(100, int(float(percent))))
    except (TypeError, ValueError):
        v = 0
    return (v + 24) // 25


def vbars(values, colour=None, cap=False):
    """Markup for one meter per value, side by side (a space apart). cap:
    a battery's terminal as a fifth, faint line on top."""
    col = f" color='{colour}'" if colour else ""
    on = f"<span{col}>{VB_SEG}</span>"
    off = f"<span{col} fgalpha='{VB_FAINT}'>{VB_SEG}</span>"
    counts = [lit(v) for v in values]
    rows = [" ".join(on if n >= row else off for n in counts) for row in (4, 3, 2, 1)]
    if cap:
        # Small: a short line (the bar's 38 px hold four segments and a
        # sliver more), and narrower than the body, like a terminal.
        rows.insert(0, " ".join(f"<span{col} size='{VB_CAP_SIZE}' fgalpha='{VB_FAINT}'>{VB_CAP}</span>"
                                for _ in counts))
    return VB_OPEN + "\n".join(rows) + "</span>"


def main(argv):
    if argv[1:] == ["narrow"]:
        print("yes" if narrow() else "no")
        return 0
    if argv[1:2] == ["vbars"] and len(argv) > 2:
        print(vbars(argv[2:]))
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
