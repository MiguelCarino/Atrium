#!/usr/bin/env python3
"""Play a looping video as one monitor's wallpaper: a GTK3 window on the
BACKGROUND layer (over hyprpaper's still, under everything else), filled by
GStreamer. Started, paused and stopped by wallpaper-slideshow.py (its "Moving
wallpaper" section says when); not meant to be run by hand, but it can be:

    wallpaper-motion.py <OUTPUT> <video>     e.g. DP-1 ~/Pictures/Wallpapers/DP-1/matrix-rain.mp4
    wallpaper-motion.py react on|off|status  the reactions below (default on)

    SIGUSR1  pause (the frame stays on screen; the decoder stops)
    SIGUSR2  play again
    SIGTERM  quit

Reactions (React below), every REACT_S while playing, never while paused --
and gamemode stops these processes altogether (wallpaper-slideshow.py):
  * speed follows the CPU: SPEED_IDLE at rest up to SPEED_BUSY under full
    load, smoothed so a short spike does not jerk it. An instant rate change
    (GStreamer 1.18+), so no flush and no black frame.
  * light follows the time of day: a little dimmer at night (the night
    light's START / END in nightlight.sh), full in the day.
  * colour follows the weather (wttr.py's cached answer, no fetching here):
    clear = as made, cloud / fog = cooler and a touch greyer, rain / storm =
    cooler and darker, snow = paler.
  All of it through a videobalance element (brightness, contrast,
  saturation, hue), which is a passthrough while everything is neutral.
  wallpaper_react=off in display.conf turns it off (`react off`); the
  running players notice within REACT_S and go back to neutral.

Why not mpvpaper (which this replaced the day it was tried): on this NVIDIA
machine every mpvpaper costs ~830 MB of VRAM before it plays anything -- the
same at 640x360 as at 3440x1440, whatever mpv's options -- so three monitors
were ~2.5 GB, the reason video wallpapers went in the first place. This is
a plain GTK3 window: the frames are decoded on the CPU (avdec_h264; the loops
are 10 fps and mostly black, so that is cheap) and drawn by gtksink with
cairo into an ordinary shm buffer -- no GL context of its own, a few MB.

The loop is gapless: a SEGMENT seek, and at every segment-done another one
from 0, never a flush -- no black frame or stall at the seam.
"""

import signal

# Before anything slow: until GLib's handlers below are in, SIGUSR1/2's
# default action would KILL this process, and the slideshow may pause it the
# moment it starts.
signal.signal(signal.SIGUSR1, signal.SIG_IGN)
signal.signal(signal.SIGUSR2, signal.SIG_IGN)

import datetime  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gst", "1.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gst, Gtk, GtkLayerShell  # noqa: E402


STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "display.conf")
REACT_KEY = "wallpaper_react"
REACT_S = 2
SPEED_IDLE, SPEED_BUSY = 0.6, 1.6
SMOOTH = 0.3                # how far each tick moves towards the new target
NIGHTLIGHT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nightlight.sh")
# The night light's own times when Settings > Screens changed them (start= /
# end= lines); nightlight.sh's defaults above are only the fallback.
NIGHTLIGHT_CONF = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                               "hypr", "nightlight.conf")
WEATHER_RAW = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-weather-raw.json")
WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
NIGHT_BRIGHTNESS = -0.08    # videobalance brightness, -1..1
# weather kind -> (brightness, saturation, hue): small nudges, the rain is
# still the theme's green. hue -1..1 is the whole circle: +0.03 leans cooler.
WEATHER = {
    "sun": (0.0, 1.0, 0.0), "partly": (0.0, 1.0, 0.0),
    "cloud": (-0.02, 0.85, 0.02), "fog": (-0.03, 0.75, 0.02),
    "showers": (-0.04, 0.9, 0.04), "rain": (-0.05, 0.9, 0.05), "heavy": (-0.07, 0.85, 0.06),
    "storm": (-0.08, 0.9, 0.07), "snow": (0.03, 0.7, 0.03),
}


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


def react_on():
    return read_state().get(REACT_KEY) != "off"


def set_react(value):
    """display.conf's format (lua/shared.lua): key=value, sorted, atomic."""
    state = read_state()
    state[REACT_KEY] = value
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        for k in sorted(state):
            if state[k] != "":
                handle.write(f"{k}={state[k]}\n")
    os.replace(tmp, STATE)


def cpu_times():
    with open("/proc/stat") as handle:
        fields = [int(x) for x in handle.readline().split()[1:]]
    idle = fields[3] + fields[4]            # idle + iowait
    return sum(fields), idle


def is_night(now=None):
    """Inside the night light's START..END (crossing midnight is fine): the
    times in nightlight.conf when it has them, else nightlight.sh's defaults,
    else 20:00 / 07:00 -- the same order theme-schedule.py's boundaries()
    uses. Equal start and end (a hand edit) count as no conf, as in
    nightlight.sh."""
    def read(path, pattern):
        got = {}
        try:
            with open(path) as handle:
                for line in handle:
                    m = re.match(pattern, line)
                    if m and int(m[2].split(":")[0]) < 24 and int(m[2].split(":")[1]) < 60:
                        got[m[1].upper()] = m[2]
        except OSError:
            pass
        return got
    found = {"START": "20:00", "END": "07:00", **read(NIGHTLIGHT, r'(START|END)="(\d{1,2}:\d{2})"')}
    conf = {**found, **read(NIGHTLIGHT_CONF, r'(start|end)=\s*(\d{1,2}:\d{2})\s*$')}
    if conf["START"] != conf["END"]:
        found = conf
    minutes = lambda hm: int(hm.split(":")[0]) * 60 + int(hm.split(":")[1])
    now = now or datetime.datetime.now()
    cur, s, e = now.hour * 60 + now.minute, minutes(found["START"]), minutes(found["END"])
    return (s <= cur < e) if s < e else (cur >= s or cur < e)


def weather_kind():
    """wttr.py's kind for the cached current condition, or None."""
    try:
        with open(WEATHER_RAW) as handle:
            code = int(json.load(handle)["current_condition"][0]["weatherCode"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    try:
        sys.path.insert(0, WAYBAR_SCRIPTS)
        from wttr import KINDS          # the bar's own table, so both agree
    except Exception:  # noqa: BLE001 -- the bar's module failing must not stop the wallpaper
        return None
    finally:
        if sys.path[0] == WAYBAR_SCRIPTS:
            sys.path.pop(0)
    return next((kind for kind, codes in KINDS.items() if code in codes), "cloud")


class React:
    """Speed from the CPU, light from the clock, colour from the weather."""

    def __init__(self, motion):
        self.motion = motion
        self.last = cpu_times()
        self.speed = 1.0
        self.applied = None
        GLib.timeout_add_seconds(REACT_S, self.tick)

    def targets(self):
        total, idle = cpu_times()
        dt, di = total - self.last[0], idle - self.last[1]
        self.last = (total, idle)
        load = max(0.0, min(1.0, 1 - di / dt)) if dt > 0 else 0.0
        want = SPEED_IDLE + (SPEED_BUSY - SPEED_IDLE) * min(1.0, load / 0.8)
        self.speed += (want - self.speed) * SMOOTH
        bright, sat, hue = WEATHER.get(weather_kind(), (0.0, 1.0, 0.0))
        if is_night():
            bright += NIGHT_BRIGHTNESS
        return round(self.speed, 2), round(bright, 3), round(sat, 3), round(hue, 3)

    def tick(self):
        if not self.motion.playing:
            return True
        if react_on():
            want = self.targets()
        else:
            want = (1.0, 0.0, 1.0, 0.0)
            self.speed = 1.0
        if want != self.applied:
            self.applied = want
            self.motion.apply(*want)
        return True


def gdk_monitor(name):
    """The GdkMonitor of Hyprland output `name`, matched by layout position
    (GDK names monitors by model, never by connector; launcher.py does the
    same)."""
    try:
        mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True,
                                         text=True, timeout=2).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    want = next((m for m in mons if m.get("name") == name), None)
    display = Gtk.Window().get_display()
    for i in range(display.get_n_monitors() if want else 0):
        box = display.get_monitor(i).get_geometry()
        if (box.x, box.y) == (want["x"], want["y"]):
            return display.get_monitor(i)
    return None


class Motion:
    def __init__(self, output, path):
        monitor = gdk_monitor(output)
        if monitor is None:
            sys.exit(f"wallpaper-motion: no monitor {output}")
        self.pipe = Gst.parse_launch(
            f'filesrc location="{path}" ! qtdemux ! h264parse ! avdec_h264 max-threads=2 '
            "! videoconvert ! videobalance name=bal ! videoconvert "
            "! gtksink name=sink force-aspect-ratio=false sync=true")
        self.balance = self.pipe.get_by_name("bal")
        self.rate = 1.0
        self.playing = True
        sink = self.pipe.get_by_name("sink")

        win = Gtk.Window()
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "wallpaper-motion")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.BACKGROUND)
        GtkLayerShell.set_monitor(win, monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_exclusive_zone(win, -1)     # under the bar too
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        win.add(sink.props.widget)
        win.connect("destroy", lambda *_: self.quit())
        win.show_all()

        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::segment-done", lambda *_: self.loop(Gst.SeekFlags.SEGMENT))
        bus.connect("message::error", self.on_error)
        bus.connect("message::async-done", self.first_seek)
        self.seeked = False
        self.pipe.set_state(Gst.State.PLAYING)

        self.react = React(self)
        for sig, fn in ((signal.SIGUSR1, lambda: self.state(Gst.State.PAUSED)),
                        (signal.SIGUSR2, lambda: self.state(Gst.State.PLAYING)),
                        (signal.SIGTERM, self.quit), (signal.SIGINT, self.quit)):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda f=fn: (f(), True)[1])

    def first_seek(self, *_):
        # Once prerolled: switch to segment seeks, so the end of the file
        # posts segment-done (looped below) instead of EOS.
        if not self.seeked:
            self.seeked = True
            self.loop(Gst.SeekFlags.FLUSH | Gst.SeekFlags.SEGMENT)

    def loop(self, flags):
        self.pipe.seek(self.rate, Gst.Format.TIME, flags, Gst.SeekType.SET, 0, Gst.SeekType.NONE, -1)

    def state(self, st):
        self.playing = st == Gst.State.PLAYING
        self.pipe.set_state(st)

    def apply(self, speed, brightness, saturation, hue):
        shown = getattr(self, "shown", None)
        if shown is None or abs(shown[0] - speed) >= 0.1 or shown[1:] != (brightness, saturation, hue):
            self.shown = (speed, brightness, saturation, hue)
            print(f"wallpaper-motion: speed {speed}x, brightness {brightness}, "
                  f"saturation {saturation}, hue {hue}", file=sys.stderr, flush=True)
        self.balance.set_property("brightness", brightness)
        self.balance.set_property("saturation", saturation)
        self.balance.set_property("hue", hue)
        if speed != self.rate and self.seeked:
            self.rate = speed
            # An instant rate change: no flush, no stall; the segment loop
            # above keeps the same rate at every seam.
            self.pipe.seek(speed, Gst.Format.TIME, Gst.SeekFlags.INSTANT_RATE_CHANGE,
                           Gst.SeekType.NONE, 0, Gst.SeekType.NONE, 0)

    def on_error(self, _bus, msg):
        err, _ = msg.parse_error()
        print(f"wallpaper-motion: {err.message}", file=sys.stderr)
        self.quit()

    def quit(self):
        self.pipe.set_state(Gst.State.NULL)
        Gtk.main_quit()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "react":
        if sys.argv[2] in ("on", "off"):
            set_react(sys.argv[2])
        elif sys.argv[2] != "status":
            sys.exit("react: on, off or status")
        print(json.dumps({"on": react_on(), "night": is_night(), "weather": weather_kind()}))
        return
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip())
    Gst.init(None)
    Motion(sys.argv[1], sys.argv[2])
    Gtk.main()


if __name__ == "__main__":
    main()
