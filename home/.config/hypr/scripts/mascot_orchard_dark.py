#!/usr/bin/env python3
"""The orchard-dark theme's mascot: Hum, the same honeybee as
mascot_orchard.py (the drawing, the moods, the scenes, his words), bound to
that file's DARK palette -- light lines on the dark stage (#232325,
themes/orchard-dark/llm-chat.css paints the same on #stage). The bee
himself keeps his amber and his dark stripes; the outlines, the leaves, the
hive's straw and the card turn over for the night appearance."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mascot_orchard as _orchard  # noqa: E402

THEME = "orchard-dark"
PANEL = _orchard.DARK["panel"]
# The reaction sign: the dark appearance's accent text and status colours,
# >= 4.5:1 on the panel and the night sky.
EMOTE_COLOURS = {"accent": "#409cff", "warn": "#ff9f0a", "bad": "#ff453a", "good": "#30d158",
                 "love": "#ff375f", "dim": "#a1a1a6"}
TOPIC_LINES = _orchard.TOPIC_LINES
MOOD_BUBBLES = _orchard.MOOD_BUBBLES


class Mascot(_orchard.Mascot):
    PAL = _orchard.DARK


if __name__ == "__main__":
    import mascots
    mascots.main(sys.argv[1:], default_theme=THEME)
