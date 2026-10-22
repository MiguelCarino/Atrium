#!/usr/bin/env python3
"""Colours the bar's scripts and the popup panels DRAW, as opposed to the ones
CSS paints: Pango markup (the CPU / GPU labels, weather glyphs, "Sure?"
prompts) and cairo graphs (CPU, GPU, network, weather). CSS cannot reach
either, so the desktop theme hands them over as data:

    ~/.config/themes/<name>/theme.conf     color.<name>=#rrggbb
        -> ~/.config/hypr/scripts/theme.py writes, resolved through the
           theme's inheritance, ~/.config/waybar/generated/colors.conf:
    ~/.config/waybar/generated/colors.conf     <name>=#rrggbb, one per line

    import themecolors
    themecolors.hex("cpu", "#ff2a6d")      '#ff2a6d' (or the theme's)
    themecolors.rgb("cpu", "#ff2a6d")      (1.0, 0.165, 0.427), for cairo

Every caller passes the cyberpunk value as the fallback, so a missing file,
a missing key or a malformed line simply means today's colour -- nothing here
can fail a bar script. The file is read once per process: the panels are
short-lived (a theme change shows in the next one opened), and the
long-running bar scripts are shell, which read it on every tick themselves
(cpu_usage.sh, gpu_usage.sh). No GTK import: wttr.py runs in the bar.
"""

import os
import re

COLORS = os.path.expanduser("~/.config/waybar/generated/colors.conf")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_cache = None


def _load():
    global _cache
    if _cache is None:
        _cache = {}
        try:
            with open(COLORS) as handle:
                for line in handle:
                    key, sep, value = line.strip().partition("=")
                    if sep and not key.startswith("#") and _HEX.match(value.strip()):
                        _cache[key.strip()] = value.strip().lower()
        except OSError:
            pass
    return _cache


def hex(name, fallback):  # noqa: A001  (shadows the builtin on purpose: themecolors.hex)
    return _load().get(name, fallback)


def rgb(name, fallback):
    h = hex(name, fallback).lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
