"""Settings page: gestures and gaze -- a hand held up to the webcam, and
which monitor you are looking at (gestures.py; its docstring has how and
what it never does). Both ride on presence.py's camera: one owner.

    STATUS      the two switches (privacy.conf's gestures= / gaze=, OFF as
                shipped), what the camera sees now, Pause / Resume
    GESTURES    each gesture -> one action of the fixed catalog; how long a
                pose is held, how far a swipe goes, a mirrored camera, the
                little bubble saying what fired
    GAZE        per monitor: Calibrate (look at it, press, keep looking 3 s);
                how long you look before it counts; focus the last window
                there (off as shipped)
    SPEED       looks a second (8-15) and the CPU it may use

Nothing is kept here: every control runs gestures.py (set, map, calibrate,
forget), presence.py (pause / resume) or privacy_settings.py gestures|gaze
on|off, and the page redraws from `gestures.py status --json`.
"""
from .common import *  # noqa: F401,F403  (the shared helpers and paths; Gtk 3)

from gi.repository import GLib, Gtk  # noqa: E402,F401

import os  # noqa: E402

PAGE = {"id": "gestures", "title": "Gestures & gaze", "icon": "", "group": "Safety", "order": 23,
        "keywords": ["gesture", "hand", "swipe", "thumbs up", "palm", "webcam", "camera", "gaze", "look at",
                     "head tracking", "eye tracking", "monitor focus", "gestos", "mirada", "mano"]}

GESTURES_PY = os.path.join(HYPR, "gestures.py")
PRESENCE = os.path.join(HYPR, "presence.py")
PRIVACY = os.path.join(HYPR, "privacy_settings.py")
SETTINGS = os.path.join(HYPR, "settings.py")
HOLD = [("500", "0.5 s"), ("800", "0.8 s"), ("1200", "1.2 s"), ("1600", "1.6 s")]
SWIPE = [("15", "Short"), ("25", "Normal"), ("35", "Long")]
DWELL = [("500", "0.5 s"), ("1000", "1 s"), ("2000", "2 s"), ("3000", "3 s")]
FPS = [("8", "8 a second"), ("10", "10"), ("12", "12"), ("15", "15")]
CPU = [("15", "15 % of a core"), ("30", "30 %"), ("50", "50 %"), ("100", "a whole core")]
ICONS = {"swipe_left": "", "swipe_right": "", "open_palm": "", "thumbs_up": "",
         "thumbs_down": "", "victory": "", "fist": ""}


# -- pure helpers (tests/test_gestures.py) ---------------------------------------------------
def status_text(data):
    """The status line under the switches."""
    sw = data.get("switches") or {}
    if not (sw.get("gestures") or sw.get("gaze")):
        return ("Off. Nothing reads hands or head turns until you switch one on here; the camera stays "
                "presence's alone (Settings > Presence).")
    if not all((data.get("installed") or {}).values()):
        return "On, but the hand models are missing: ~/.local/share/presence (see gestures.py's docstring)."
    live = data.get("live")
    if data.get("service") != "active" or not live:
        return f"On, but the camera service is {data.get('service') or 'not running'} (journalctl --user -u presence)."
    if live.get("error") and sw.get("gestures"):
        return f"Gestures stopped: {live['error']} (switch them off and on to try again)."
    if not data.get("camera"):
        return f"Waiting: the camera is closed ({data.get('why') or 'between looks'})."
    bits = [f"{live.get('fps')} looks a second"]
    if live.get("cpu_ms"):
        bits.append(f"{live['cpu_ms']:.0f} ms of CPU each")
    if sw.get("gestures"):
        hold = live.get("holding")
        bits.append(f"holding {hold[0].replace('_', ' ')} {int(hold[1] * 100)} %" if hold else
                    f"hand: {(live.get('hand') or 'none').replace('_', ' ')}")
    if sw.get("gaze"):
        bits.append(f"looking at {live.get('looking_at') or '-'}")
    return "  ·  ".join(bits)


def calibration_text(monitor, calibration):
    c = (calibration or {}).get(monitor)
    if not c:
        return "not calibrated: look at it and press Calibrate"
    return f"calibrated ({c.get('n', '?')} looks)"


def gaze_hint(monitors, calibration):
    done = [m for m in monitors if m in (calibration or {})]
    if len(done) >= 2:
        return f"{len(done)} of {len(monitors)} monitors calibrated"
    return "calibrate at least two monitors: sit as you usually do, look at the middle of one, press its button"


def last_events(live):
    out = []
    for what, detail, _when in (live or {}).get("events") or []:
        out.append(f"{str(what).replace('_', ' ')}: {detail}")
    return "  ·  ".join(out[-3:])


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.calibrating = None

        w.pack_start(heading("STATUS"), False, False, 0)
        self.master = {}
        for key, icon, title, sub in (
                ("gestures", "", "Hand gestures", "swipe, open palm, thumbs up ... to the webcam"),
                ("gaze", "", "Notice which monitor you look at", "from how your head is turned")):
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.switch(k, state))
            grid, _ = row(icon, title, sub, sw)
            self.master[key] = sw
            w.pack_start(grid, False, False, 0)
        self.status = dp.label("", "ctl-sub")
        self.status.set_line_wrap(True)
        w.pack_start(self.status, False, False, 0)
        self.events = dp.label("", "ctl-sub")
        self.events.set_line_wrap(True)
        w.pack_start(self.events, False, False, 0)
        w.pack_start(links_row(link("Pause the camera for an hour", lambda: self.run(PRESENCE, "pause", "60")),
                               link("Resume", lambda: self.run(PRESENCE, "resume")),
                               link("Check again", self.refresh),
                               link("Open Presence", lambda: spawn(SETTINGS, "presence"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("GESTURES"), False, False, 0)
        self.maps = {}
        self.combos_ready = False
        for g in ("swipe_left", "swipe_right", "open_palm", "thumbs_up", "thumbs_down", "victory", "fist"):
            combo = Gtk.ComboBoxText()
            combo.connect("changed", lambda c, k=g: self.pick(k, c))
            grid, _ = row(ICONS[g], g.replace("_", " ").capitalize(), "", combo)
            self.maps[g] = combo
            w.pack_start(grid, False, False, 0)
        grid, _ = row("", "Hold a pose for", "a pose fires once it has been held this long, still")
        w.pack_start(grid, False, False, 0)
        self.hold = Chips(lambda key: self.run(GESTURES_PY, "set", "hold_ms", key))
        w.pack_start(self.hold.widget, False, False, 0)
        grid, _ = row("", "Swipe length", "how far across the camera's picture a swipe has to go")
        w.pack_start(grid, False, False, 0)
        self.swipe = Chips(lambda key: self.run(GESTURES_PY, "set", "swipe", key))
        w.pack_start(self.swipe.widget, False, False, 0)
        self.toggles = {}
        for key, icon, title, sub in (
                ("swap", "", "Swap left and right", "for a camera that mirrors its picture"),
                ("feedback", "", "Say what fired", "a small bubble: \"Thumbs up: Confirm\"")):
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
            grid, _ = row(icon, title, sub, sw)
            self.toggles[key] = sw
            w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("GAZE"), False, False, 0)
        grid, self.gaze_sub = row("", "Calibration", "")
        w.pack_start(grid, False, False, 0)
        self.monitor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.monitor_box, False, False, 0)
        self.monitor_rows = {}
        w.pack_start(links_row(link("Forget every calibration", lambda: self.run(GESTURES_PY, "forget", "all"))),
                     False, False, 0)
        grid, _ = row("", "Look for", "a monitor counts as looked at after this long")
        w.pack_start(grid, False, False, 0)
        self.dwell = Chips(lambda key: self.run(GESTURES_PY, "set", "dwell_ms", key))
        w.pack_start(self.dwell.widget, False, False, 0)
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state: self.toggle("gaze_focus", state))
        grid, _ = row("", "Focus the monitor you look at",
                      "its last-used window; never while a window is fullscreen or the screen is locked", sw)
        self.toggles["gaze_focus"] = sw
        w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SPEED"), False, False, 0)
        grid, _ = row("", "Looks a second", "only while gestures or gaze is on; presence alone looks once or twice")
        w.pack_start(grid, False, False, 0)
        self.fps = Chips(lambda key: self.run(GESTURES_PY, "set", "fps", key))
        w.pack_start(self.fps.widget, False, False, 0)
        grid, _ = row("", "CPU limit", "the looks a second go down (to 3) to stay under it")
        w.pack_start(grid, False, False, 0)
        self.cpu = Chips(lambda key: self.run(GESTURES_PY, "set", "cpu", key))
        w.pack_start(self.cpu.widget, False, False, 0)
        note = dp.label("What it keeps: nothing but these settings and, per monitor, a few numbers for how your "
                        "head is turned when you look at it. The pictures are presence's: looked at in memory "
                        "and dropped, never saved or sent. Only while one of the switches above is on does the "
                        "camera look 8-15 times a second (the CPU limit can hold it lower); it is released in "
                        "gamemode, while another app (a call) uses it, and while paused, and the camera icon in "
                        "the top bar says \"presence\" whenever it is open. Gestures count only while a face is "
                        "turned to the screens, after a deliberate hold, never while the screen is locked, and "
                        "only run the fixed actions listed here -- nothing clicks or types.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(note, False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    def run(self, *cmd, timeout=30):
        if self.updating:
            return

        def work():
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        background(work, lambda err: (self.refresh(), self.msg.set_text(err)))

    def switch(self, key, state):
        self.run(PRIVACY, key, "on" if state else "off")
        return True             # moves when the refresh says it did

    def toggle(self, key, state):
        self.run(GESTURES_PY, "set", key, "on" if state else "off")
        return False

    def pick(self, gesture, combo):
        if self.updating or not combo.get_active_id():
            return
        self.run(GESTURES_PY, "map", gesture, combo.get_active_id())

    def calibrate(self, monitor):
        if self.calibrating:
            return
        self.calibrating = monitor
        self.msg.set_text(f"Look at the middle of {monitor} now, as you usually sit, for 3 seconds…")

        def work():
            try:
                res = subprocess.run([GESTURES_PY, "calibrate", monitor], capture_output=True, text=True,
                                     timeout=15)
                return (res.stdout if res.returncode == 0 else res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)

        def done(text):
            self.calibrating = None
            self.refresh()
            self.msg.set_text(text)
        background(work, done)

    def refresh(self):
        background(lambda: run_json(GESTURES_PY, "status", "--json") or {}, self.draw)

    def monitor_row(self, name):
        if name not in self.monitor_rows:
            grid, sub = row("", name, "", link("Calibrate", lambda m=name: self.calibrate(m)))
            self.monitor_rows[name] = (grid, sub)
            self.monitor_box.pack_start(grid, False, False, 0)
        return self.monitor_rows[name][1]

    def draw(self, data):
        if not data:
            self.msg.set_text("gestures.py did not answer (run it in a terminal to see why)")
            return
        self.updating = True
        try:
            s, sw = data["settings"], data.get("switches") or {}
            for key, widget in self.master.items():
                widget.set_state(bool(sw.get(key)))
                widget.set_active(bool(sw.get(key)))
            self.status.set_text(status_text(data))
            self.events.set_text(last_events(data.get("live")))
            actions = data.get("actions") or {}
            for g, combo in self.maps.items():
                if not self.combos_ready:
                    for key, label_text in actions.items():
                        combo.append(key, label_text)
                combo.set_active_id(s.get(f"map_{g}", "none"))
            self.combos_ready = bool(actions)
            for key, widget in self.toggles.items():
                widget.set_active(s.get(key) == "on")
            self.hold.set(HOLD if str(s["hold_ms"]) in dict(HOLD) else HOLD + [(str(s["hold_ms"]),
                          f"{s['hold_ms']} ms")], str(s["hold_ms"]))
            self.swipe.set(SWIPE if str(s["swipe"]) in dict(SWIPE) else SWIPE + [(str(s["swipe"]),
                           f"{s['swipe']} %")], str(s["swipe"]))
            self.dwell.set(DWELL if str(s["dwell_ms"]) in dict(DWELL) else DWELL + [(str(s["dwell_ms"]),
                           f"{s['dwell_ms']} ms")], str(s["dwell_ms"]))
            self.fps.set(FPS if str(s["fps"]) in dict(FPS) else FPS + [(str(s["fps"]), str(s["fps"]))],
                         str(s["fps"]))
            self.cpu.set(CPU if str(s["cpu"]) in dict(CPU) else CPU + [(str(s["cpu"]), f"{s['cpu']} %")],
                         str(s["cpu"]))
            monitors = data.get("monitors") or []
            for name in monitors:
                self.monitor_row(name).set_text(calibration_text(name, s.get("calibration")))
            for name, (grid, _sub) in list(self.monitor_rows.items()):
                if name not in monitors:
                    self.monitor_box.remove(grid)
                    del self.monitor_rows[name]
            self.gaze_sub.set_text(gaze_hint(monitors, s.get("calibration")))
        finally:
            self.updating = False
        self.widget.show_all()
