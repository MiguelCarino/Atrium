#!/usr/bin/env python3
"""Capture panel -- what the camera pill on the bar (custom/capture) opens.

    SCREENSHOT  Region, Window, Monitor, Annotate, Text (OCR), Pretty
    RECORD      Monitor, Region, Replay on/off, Save replay, SDR/HDR, Folder

Every tile is a front for something that already has a key bind; this panel
adds no capture logic of its own:

    hyprshot -m region|window|output   ALT+SHIFT+S / ALT+CTRL+S / ALT+S
    hypr/scripts/screenshot.sh         SUPER+SHIFT+S (annotate), SUPER+O (ocr), SUPER+CTRL+S (pretty)
    hypr/scripts/record.sh             ALT+F9 / ALT+SHIFT+F9 / ALT+F10 / ALT+SHIFT+F10

The record row follows the recorder live: it reads the same two pid files as
the REC pill (recording.capture), once a second while the panel is open. While
a recording runs both record tiles turn red and say Stop -- record.sh treats a
second "monitor" or "region" as stop, so the command is the same either way.
Save replay greys out while no replay buffer is running.

The SDR/HDR tile is the one tile that does not close the panel: it flips
record.sh's sticky range (= ALT+CTRL+F9) and relabels itself, so you pick the
range and then the capture in one visit.

A tile hides the panel and its click catchers first, and launches the capture
CAPTURE_DELAY later: grim would otherwise photograph the panel itself, and
slurp's overlay would open under a click catcher that is still up.

    capture_panel.py [x,y]   desktop position of the click that opened it
"""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import recording  # noqa: E402

HYPR = os.path.expanduser("~/.config/hypr/scripts")
SHOT = os.path.join(HYPR, "screenshot.sh")
RECORD = os.path.join(HYPR, "record.sh")
# Same directory as scrDir in hypr/lua/shared.lua and SCR_DIR in screenshot.sh.
SCR_DIR = os.path.expanduser("~/Pictures/Screenshots")
REC_DIR = os.environ.get("REC_DIR", os.path.expanduser("~/Videos/Recordings"))

CAPTURE_DELAY = 0.3         # seconds: long enough for the layer surfaces to go
POLL_MS = 1000

# (key, Font Awesome glyph, caption, command). Glyphs as escapes, never
# literal PUA characters -- see power_panel.py.
SCREENSHOTS = [
    ("shot-region",  "", "Region",   ["hyprshot", "-m", "region", "-o", SCR_DIR, "-s"]),
    ("shot-window",  "", "Window",   ["hyprshot", "-m", "window", "-o", SCR_DIR, "-s"]),
    ("shot-monitor", "", "Monitor",  ["hyprshot", "-m", "output", "-o", SCR_DIR, "-s"]),
    ("shot-annot",   "", "Annotate", [SHOT, "annotate"]),
    ("shot-ocr",     "", "Text",     [SHOT, "ocr"]),
    ("shot-pretty",  "\uf5fd", "Pretty",   [SHOT, "pretty"]),   # wand-magic-sparkles
]

RECORDS = [
    ("rec-monitor",  "", "Record monitor", [RECORD, "monitor"]),
    ("rec-region",   "", "Record region",  [RECORD, "region"]),
    ("rec-replay",   "", "Replay",         [RECORD, "toggle-replay"]),
    ("rec-save",     "", "Save replay",    [RECORD, "save-replay"]),
    ("rec-range",    "\uf042", "SDR",            [RECORD, "toggle-range"]),
    ("rec-folder",   "", "Folder",         None),     # opens REC_DIR
]

STOP_GLYPH = ""

# Runs "$@" after the panel is gone and reports a failure through mako -- the
# panel has exited by then, so nothing else would. Exit 1 with no output is
# how slurp says "Escape pressed", which is not a failure worth a toast.
LAUNCH = (
    'sleep "$0"; out=$("$@" 2>&1) || { [ -n "$out" ] && notify-send -a Capture '
    '-u critical "Capture" "$1 failed: $(printf %s "$out" | tail -n 3)"; }'
)


def label(text, cls, xalign=0.5):
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


class Tile:
    def __init__(self, key, glyph, caption, on_click):
        self.glyph_text, self.caption = glyph, caption
        self.button = Gtk.Button()
        self.button.set_relief(Gtk.ReliefStyle.NONE)
        self.button.set_can_focus(False)
        self.button.get_style_context().add_class("pw-tile")
        # One class per tile (cap-rec-range, cap-region...), so a theme can
        # restyle a single tile: the HDR range tile shares .live with the
        # recording tiles but means "a mode is on", not "recording now".
        # No base rule uses it.
        self.button.get_style_context().add_class(f"cap-{key}")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_valign(Gtk.Align.CENTER)
        self.glyph = label(glyph, "pw-glyph")
        self.text = label(caption, "pw-label")
        self.text.set_line_wrap(True)
        self.text.set_justify(Gtk.Justification.CENTER)
        self.text.set_max_width_chars(9)
        box.pack_start(self.glyph, False, False, 0)
        box.pack_start(self.text, False, False, 0)
        self.button.add(box)
        self.button.connect("clicked", lambda *_: on_click(key))

    def show(self, glyph=None, caption=None, live=False, sensitive=True):
        self.glyph.set_text(glyph or self.glyph_text)
        self.text.set_text(caption or self.caption)
        ctx = self.button.get_style_context()
        (ctx.add_class if live else ctx.remove_class)("live")
        self.button.set_sensitive(sensitive)


class Capture(panelui.Panel):
    def setup(self):
        self.tiles = {}
        self.commands = {key: cmd for key, _g, _c, cmd in SCREENSHOTS + RECORDS}
        self.fired = False

    def build(self):
        for heading, actions in (("SCREENSHOT", SCREENSHOTS), ("RECORD", RECORDS)):
            self.card.pack_start(label(heading, "kb-heading", 0.0), False, False, 0)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_homogeneous(True)
            row.get_style_context().add_class("cap-row")
            for key, glyph, caption, _cmd in actions:
                tile = Tile(key, glyph, caption, self.press)
                self.tiles[key] = tile
                row.pack_start(tile.button, True, True, 0)
            self.card.pack_start(row, False, False, 0)
        self.refresh()

    def on_ready(self):
        GLib.timeout_add(POLL_MS, self.refresh)

    def refresh(self):
        recording_now = recording.capture(recording.REC_PID) is not None
        replay_now = recording.capture(recording.REPLAY_PID) is not None
        for key in ("rec-monitor", "rec-region"):
            if recording_now:
                self.tiles[key].show(STOP_GLYPH, "Stop", live=True)
            else:
                self.tiles[key].show()
        self.tiles["rec-replay"].show(
            caption="Replay on" if replay_now else "Replay off", live=replay_now)
        self.tiles["rec-save"].show(sensitive=replay_now)
        hdr = self.range() == "hdr"
        self.tiles["rec-range"].show(caption="HDR" if hdr else "SDR", live=hdr)
        return True

    def range(self):
        try:
            return subprocess.run([RECORD, "range"], capture_output=True, text=True,
                                  timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "sdr"

    def press(self, key):
        if key == "rec-range":
            # REC_QUIET: the relabelled tile is the feedback; no toast on top.
            subprocess.run(self.commands[key], env=dict(os.environ, REC_QUIET="1"),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.refresh()
            return
        if self.fired:
            return                      # a double click must not capture twice
        self.fired = True
        self.hide()
        for catcher in self.catchers:
            catcher.hide()
        GLib.timeout_add(200, self.quit)

        cmd = self.commands[key]
        if cmd is None:
            os.makedirs(REC_DIR, exist_ok=True)
            cmd = ["xdg-open", REC_DIR]
        env = dict(os.environ)
        # satty lives in ~/.local/bin, which is not on the PATH waybar was
        # started with (screenshot.sh adds it too; hyprshot does not need it).
        env["PATH"] = env.get("PATH", "") + ":" + os.path.expanduser("~/.local/bin")
        try:
            subprocess.Popen(["sh", "-c", LAUNCH, str(CAPTURE_DELAY), *cmd],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True,
                             env=env)
        except OSError as exc:
            try:
                subprocess.Popen(["notify-send", "-u", "critical", "Capture",
                                  f"{cmd[0]} failed: {exc}"], start_new_session=True)
            except OSError:
                pass


if __name__ == "__main__":
    panelui.run(Capture)
