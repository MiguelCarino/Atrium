"""Settings page: presence -- the webcam telling the desktop whether you are
at the desk (presence.py; its docstring has how and what it never does).

    STATUS       on / off (the switch itself is on Settings > Privacy, where
                 the camera belongs), what it sees now, whether the camera is
                 open and why not; Pause for an hour / Resume
    LIVE         does it see you right now: the faces of the last look drawn as
                 boxes in a mirrored frame (green facing the screen, amber turned
                 away, grey too far / unsure) -- boxes only, the picture never
                 leaves presence.py. While the page is open it reads
                 presence-state.json a few times a second and asks the service
                 (`watch`) for 5 looks a second; closing the page lets it go back.
    WHEN YOU GO  lock the screen, pause media, Do Not Disturb, automations;
                 after how long
    WHEN YOU ARE BACK   wake the screens (never unlock), media again
    CAMERA       which one, 1 or 2 looks a second

Nothing is kept here: every control runs presence.py (set, pause, resume)
or privacy_settings.py presence on|off, and the page redraws from
`presence.py status --json`.
"""
from .common import *  # noqa: F401,F403  (the shared helpers and paths; Gtk 3)

from gi.repository import GLib, Gtk  # noqa: E402,F401

import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "presence", "title": "Presence", "icon": "", "group": "Smart", "order": 22, "parent": "intelligence", "tab": "Presence",
        "keywords": ["webcam", "camera", "away", "walk away", "lock when I leave", "presencia", "cámara",
                     "face", "at the desk", "wake screen", "pause media when away", "auto lock"]}

PRESENCE = os.path.join(HYPR, "presence.py")
PRIVACY = os.path.join(HYPR, "privacy_settings.py")
SETTINGS = os.path.join(HYPR, "settings.py")
SWITCHES = [
    ("lock", "", "Lock the screen when you walk away", "no face and no keyboard or mouse"),
    ("media", "", "Pause music and video while you are away", "resumes when you are back"),
    ("dnd", "", "Do Not Disturb while you are away", "off again when you are back"),
    ("automations", "", "Tell Automations", "presence-away / presence-back triggers"),
    ("wake", "", "Turn the screens on when you are back", "never unlocks"),
]
AWAY = [("30", "30 s"), ("60", "1 min"), ("120", "2 min"), ("300", "5 min")]
FPS = [("1", "1 a second"), ("2", "2 a second")]
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LIVE = os.path.join(RUNTIME, "presence-state.json")
CTL_SOCK = os.path.join(RUNTIME, "presence.sock")
LIVE_MS = 250           # how often the live view reads the state file
WATCH_EVERY_S = 10      # ... and asks the service for fast looks (it grants 15 s)
STALE_S = 6             # an older look is "the last one", not "now"
COLORS = {"facing": (0.30, 0.85, 0.45), "here": (0.95, 0.70, 0.20), "unsure": (0.55, 0.55, 0.55)}


# -- pure helpers (tests/test_presence.py) -------------------------------------------------
def status_text(data):
    """The status line under the title."""
    if not data.get("on"):
        others = [name for name, on in (("gestures", data.get("gestures")), ("gaze", data.get("gaze"))) if on]
        if others:
            return f"Off, but the camera stays open for {' and '.join(others)}"
        return "Off: nothing opens the camera"
    if not all((data.get("installed") or {}).values()):
        return "On, but its face detector is not installed"
    live = data.get("live")
    if data.get("service") != "active" or not live:
        return f"On, but the service is {data.get('service') or 'not running'}"
    seen = "you are at the desk" if live.get("state") == "present" else "you are away"
    cam = f"camera open ({live.get('device')})" if live.get("camera") \
        else f"the camera is closed: {live['why']}" if live.get("why") else "the camera is closed between looks"
    vision = live.get("vision") or {}
    if live.get("camera") and vision.get("fps"):
        cam = f"camera open ({live.get('device')}) for gestures / gaze"
    if live.get("paused_for"):
        cam = f"paused for {max(1, live['paused_for'] // 60)} more min"
    return f"{seen}  ·  {cam}"


def live_text(data, live):
    """(headline, detail, kind) for the live view; kind picks the dot's colour:
    facing / here / unsure / off."""
    if not data.get("on") and not ((live or {}).get("vision") or {}).get("fps"):
        return "Not watching", "presence is off (Settings > Privacy)", "off"
    if not live:
        return "Not watching", "the service is not running", "off"
    if live.get("paused_for"):
        return "Paused", f"the camera is closed for {max(1, live['paused_for'] // 60)} more min", "off"
    look = live.get("look")
    if live.get("why") and not live.get("camera"):
        return "Camera closed", live["why"], "off"
    if not look:
        return "Waiting for the first look", "the camera is opening", "unsure"
    age = max(0.0, time.time() - look.get("at", 0))
    faces = look.get("faces") or []
    if look.get("facing"):
        head, kind = "I see you, facing the screen", "facing"
    elif look.get("here"):
        head, kind = "I see you, turned away", "here"
    elif faces:
        head, kind = "A face, but too far or unclear", "unsure"
    else:
        head, kind = "Nobody in view", "unsure"
    bits = []
    if faces:
        best = max(f.get("score", 0) for f in faces)
        bits.append(f"{len(faces)} face{'s' if len(faces) > 1 else ''}, {best:.0%} sure")
    bits.append("just now" if age < 1.5 else f"{age:.0f} s ago")
    bits.append("counted as at the desk" if live.get("state") == "present" else "counted as away")
    if age > STALE_S:
        head = "Last look: " + head[0].lower() + head[1:]
    return head, "  ·  ".join(bits), kind


def mirrored(face):
    """A box in the drawing's terms: mirrored like a mirror, as people expect."""
    return 1 - face["x"] - face["w"], face["y"], face["w"], face["h"]


def camera_items(cameras, current):
    items = [("auto", "Automatic")] + [(c["dev"], f"{c['name']} ({c['dev'][5:]})") for c in cameras]
    if current not in dict(items):
        items.append((current, current))
    return items


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False

        w.pack_start(heading("STATUS"), False, False, 0)
        self.master = Gtk.Switch()
        self.master.connect("state-set", lambda _s, state: self.switch_master(state))
        grid, self.status = row("", "Notice when you are at the desk", "", self.master)
        w.pack_start(grid, False, False, 0)
        self.camera_off = link("Camera off", lambda: self.run(PRIVACY, "camera", "off"))
        w.pack_start(links_row(self.camera_off,
                               link("Pause for an hour", lambda: self.run(PRESENCE, "pause", "60")),
                               link("Resume", lambda: self.run(PRESENCE, "resume")),
                               link("Open Privacy", lambda: spawn(SETTINGS, "privacy")),
                               link("Gestures & gaze", lambda: spawn(SETTINGS, "gestures"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("LIVE"), False, False, 0)
        live = Gtk.Box(spacing=14)
        self.view = Gtk.DrawingArea()
        self.view.set_size_request(192, 144)
        self.view.connect("draw", self.paint)
        live.pack_start(self.view, False, False, 0)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        words.set_valign(Gtk.Align.CENTER)
        self.verdict = dp.label("", "ctl-title")
        self.detail = dp.label("", "ctl-sub")
        self.detail.set_line_wrap(True)
        self.detail.set_max_width_chars(60)
        words.pack_start(self.verdict, False, False, 0)
        words.pack_start(self.detail, False, False, 0)
        live.pack_start(words, True, True, 0)
        w.pack_start(live, False, False, 0)
        self.data, self.live, self.kind = {}, None, "off"
        self.ticking = None
        self.watched_at = 0
        w.pack_start(sep(), False, False, 0)

        self.switches = {}
        for title, keys in (("WHEN YOU GO", ("lock", "media", "dnd", "automations")),
                            ("WHEN YOU ARE BACK", ("wake",))):
            w.pack_start(heading(title), False, False, 0)
            for key, icon, name, sub in (s for s in SWITCHES if s[0] in keys):
                sw = Gtk.Switch()
                sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
                grid, _ = row(icon, name, sub, sw)
                self.switches[key] = sw
                w.pack_start(grid, False, False, 0)
            if title == "WHEN YOU GO":
                grid, self.away_sub = row("", "Away after", "")
                w.pack_start(grid, False, False, 0)
                self.away = Chips(lambda key: self.run(PRESENCE, "set", "away_s", key))
                w.pack_start(self.away.widget, False, False, 0)
            w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("CAMERA"), False, False, 0)
        self.camera = Chips(lambda key: self.run(PRESENCE, "set", "camera", key))
        w.pack_start(self.camera.widget, False, False, 0)
        self.fps = Chips(lambda key: self.run(PRESENCE, "set", "fps", key))
        w.pack_start(self.fps.widget, False, False, 0)
        w.pack_start(dp.label("Nothing is saved or sent.  SUPER+CTRL+SHIFT+P pauses for an hour.", "ctl-sub"),
                     False, False, 0)
        note = dp.label("Each picture is looked at in memory and dropped before the next. The camera is "
                        "closed while paused, in gamemode or while another app (a call) uses it; while you "
                        "are away it only peeks every few seconds, and after half an hour not at all (your "
                        "keyboard brings it back). The top bar's camera icon says \"presence\" while it is "
                        "open.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(details(note, label="How it works"), False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    def run(self, *cmd):
        if self.updating:
            return

        def work():
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        background(work, lambda err: (self.refresh(), self.msg.set_text(err)))

    def toggle(self, key, state):
        self.run(PRESENCE, "set", key, "on" if state else "off")
        return False

    def switch_master(self, state):
        # Off means the camera off: gestures and gaze ride on the same camera,
        # so they go off too (Gestures & gaze turns them back on).
        self.run(PRIVACY, "presence", "on") if state else self.run(PRIVACY, "camera", "off")
        return True             # moves when the refresh says it did

    def refresh(self):
        background(lambda: run_json(PRESENCE, "status", "--json") or {}, self.draw)
        if self.ticking is None:
            self.ticking = GLib.timeout_add(LIVE_MS, self.tick)

    # -- the live view -------------------------------------------------------------------
    def tick(self):
        """Every LIVE_MS while the page shows; stops itself once it does not."""
        if not self.widget.get_mapped():
            self.ticking = None
            return False
        try:
            with open(LIVE) as handle:
                self.live = json.load(handle)
        except (OSError, ValueError):
            self.live = None
        now = time.monotonic()
        if self.live and now - self.watched_at >= WATCH_EVERY_S:
            self.watched_at = now
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
                    s.sendto(b"watch", CTL_SOCK)
            except OSError:
                pass
        head, detail, self.kind = live_text(self.data, self.live)
        self.verdict.set_text(("●  " if self.kind in ("facing", "here") else "○  ") + head)
        self.detail.set_text(detail)
        self.view.queue_draw()
        return True

    def paint(self, area, cr):
        width, height = area.get_allocated_width(), area.get_allocated_height()
        fg = area.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        r = 10
        cr.new_sub_path()
        for x, y, a in ((width - r, r, -math.pi / 2), (width - r, height - r, 0),
                        (r, height - r, math.pi / 2), (r, r, math.pi)):
            cr.arc(x, y, r, a, a + math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.06)
        cr.fill_preserve()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
        cr.set_line_width(1)
        cr.stroke()
        look = (self.live or {}).get("look") or {}
        fresh = self.kind != "off" and time.time() - look.get("at", 0) <= STALE_S
        faces = (look.get("faces") or []) if fresh else []
        if not faces:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.4)
            cr.select_font_face("sans")
            cr.set_font_size(12)
            text = "camera closed" if self.kind == "off" else "nobody in view"
            ext = cr.text_extents(text)
            cr.move_to((width - ext.width) / 2 - ext.x_bearing, height / 2 - ext.height / 2 - ext.y_bearing)
            cr.show_text(text)
            return
        for face in faces:
            x, y, w, h = mirrored(face)
            red, green, blue = COLORS["facing" if face.get("facing") else "here" if face.get("here")
                                      else "unsure"]
            cr.set_source_rgba(red, green, blue, 0.18)
            cr.rectangle(x * width, y * height, w * width, h * height)
            cr.fill_preserve()
            cr.set_source_rgba(red, green, blue, 0.95)
            cr.set_line_width(2)
            cr.stroke()

    def draw(self, data):
        if not data:
            self.msg.set_text("Presence did not answer")
            return
        self.data = data
        self.updating = True
        try:
            s = data["settings"]
            self.master.set_state(bool(data.get("on")))
            self.master.set_active(bool(data.get("on")))
            self.status.set_text(status_text(data))
            self.camera_off.set_visible(bool(data.get("on") or data.get("gestures") or data.get("gaze")))
            for key, sw in self.switches.items():
                sw.set_active(s.get(key) == "on")
            away = str(s.get("away_s", 60))
            self.away.set(AWAY if away in dict(AWAY) else AWAY + [(away, f"{away} s")], away)
            self.away_sub.set_text(f"no face for {s.get('away_s', 60)} s, idle for {data.get('idle_s', 20)} s")
            self.camera.set(camera_items(data.get("cameras") or [], s.get("camera", "auto")),
                            s.get("camera", "auto"))
            self.fps.set(FPS, str(s.get("fps", 1)))
        finally:
            self.updating = False
        self.widget.show_all()
        self.camera_off.set_visible(bool(data.get("on") or data.get("gestures") or data.get("gaze")))
