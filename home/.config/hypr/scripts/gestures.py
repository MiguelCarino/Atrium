#!/usr/bin/env python3
"""Gestures and gaze: the presence camera (presence.py), looked at faster
while either is on, turned into a few deliberate desktop actions -- a hand
held up to the webcam, or which MONITOR your head is turned to. Settings >
Gestures & gaze; each one switched on there (privacy.conf's gestures= /
gaze=, OFF as shipped).

    gestures.py status [--json]         the switches, the settings, what it sees now
    gestures.py set KEY VALUE           a setting (SETTINGS below)
    gestures.py map GESTURE ACTION      what a gesture does (GESTURES -> ACTIONS)
    gestures.py actions [--json]        the action catalog
    gestures.py do ACTION               run one catalog action now (the page's "Try")
    gestures.py toggle gestures|gaze    the key: switch one on / off, with a bubble
    gestures.py calibrate MONITOR       look at that monitor: the service averages
                                        CALIB_S of your head pose (needs gaze on)
    gestures.py forget MONITOR|all      drop a calibration
    gestures.py test-image FILE...      what the models make of photos (hands, head
                                        pose); the way to try it without the camera
    gestures.py replay FILE             a recorded landmark sequence (JSON lines, see
                                        replay()) through the recognizers: prints what
                                        would fire. Never runs an action

ONE CAMERA, ONE OWNER. Nothing here opens the camera: presence.py's watcher
owns it (and with it the pauses -- gamemode, another app using the camera,
the pause key, nobody at the desk -- and the bar's camera indicator, which
says "presence" whenever it is open). It imports this module and hands each
frame it already read, plus the faces its YuNet detector already found, to
Vision.frame(); the frame is dropped right after, as before. With gestures or
gaze on the watcher looks VISION fps (8-15) instead of 1-2, and at 640x480
instead of 320x240 while gestures are on (hands are small); it runs even
with presence's own actions off (privacy_settings.camera_wanted()).

GESTURES (a hand, MediaPipe's palm detector + hand landmark model as OpenCV
Zoo's ONNX files, run by OpenCV's dnn on the CPU, 2 threads; while a hand is
being followed its last landmarks stand in for the palm detector):

    swipe_left / swipe_right   the hand moved across SWIPE % of the picture
                               in under SWIPE_S, mostly sideways ("left" is
                               YOUR left; `swap` for a mirrored camera)
    open_palm, thumbs_up, thumbs_down, victory, fist
                               the pose held still for hold_ms

Deliberate by construction: nothing counts unless a face is in the picture
turned roughly to the screens (GATE_YAW) -- someone walking past, or you
looking away, does nothing; a pose fires only after being held still; a
fired pose must be let go before it fires again; after anything fires there
is COOLDOWN_S of nothing; nothing at all while the screen is locked.

Each gesture is mapped (Settings) to one entry of ACTIONS, a FIXED catalog
of safe desktop actions: argv lists and fixed Lua, never a shell, nothing
that types or clicks in a window. "confirm" / "cancel" answer the Confirm
bubble voice-command.py is showing (makoctl invoke on that notification's
own action -- nothing when there is none).

GAZE (no extra model): head pose from YuNet's five landmarks -- yaw (the
nose against the eyes), pitch (the nose between eyes and mouth) and where
the face is in the picture -- smoothed, matched to the nearest per-monitor
calibration (Settings: look at a monitor, press its button; at least two
monitors). Which monitor, not which window: a webcam cannot do better. Once
the answer has held for dwell_ms it is "looking at" (status, the page) and,
only with gaze_focus on (off as shipped), focuses the window you used last
on that monitor -- never while a window is fullscreen or the screen is locked.

CPU: the service measures its own CPU time per frame and lowers the frame
rate to stay inside `cpu` (% of one core), down to MIN_FPS.

Privacy: as presence.py -- frames in memory one at a time, nothing written
or sent; the only things kept are the settings and the calibrations (a few
numbers per monitor: head angles, not pictures). `test-image` and `replay`
read only the files you name.

Models: ~/.local/share/presence/{palm_detection,handpose_estimation}_
mediapipe_2023feb.onnx (OpenCV Zoo, Apache-2.0; the pre/post-processing
below follows its demo code). Settings: $XDG_STATE_HOME/hypr/gestures.json.
What it sees now: presence's $XDG_RUNTIME_DIR/presence-state.json, "vision".
Logs: journalctl --user -t presence.
"""
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")     # before any `import cv2`
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desklog  # noqa: E402
import privacy_settings  # noqa: E402  (the switches)

HOME = os.path.expanduser("~")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "presence")
VENV_PY = os.path.join(DATA, "venv", "bin", "python")
PALM_MODEL = os.path.join(DATA, "palm_detection_mediapipe_2023feb.onnx")
HAND_MODEL = os.path.join(DATA, "handpose_estimation_mediapipe_2023feb.onnx")
CONF = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                    "hypr", "gestures.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LIVE = os.path.join(RUNTIME, "presence-state.json")         # presence.py writes it
CTL_SOCK = os.path.join(RUNTIME, "presence.sock")
PRIVACY = os.path.join(HERE, "privacy_settings.py")

GESTURES = ("swipe_left", "swipe_right", "open_palm", "thumbs_up", "thumbs_down", "victory", "fist")
GESTURE_NAMES = {"swipe_left": "Swipe left", "swipe_right": "Swipe right", "open_palm": "Open palm",
                 "thumbs_up": "Thumbs up", "thumbs_down": "Thumbs down", "victory": "Victory (two fingers)",
                 "fist": "Fist"}
# The catalog: name -> (label, what it runs). Lua is fixed text; nothing here
# is built from anything the camera saw. The workspace steps are ALT+wheel's
# (lua/binds.lua: the cube when it is loaded), the overview SUPER+D's.
ACTIONS = {
    "none": ("Nothing", None),
    "workspace-prev": ("Previous workspace", ("lua", 'local c = hl.plugin.cube; if c then c.prev() else '
                                                     'hl.dispatch(hl.dsp.focus({ workspace = "e-1" })) end')),
    "workspace-next": ("Next workspace", ("lua", 'local c = hl.plugin.cube; if c then c.next() else '
                                                 'hl.dispatch(hl.dsp.focus({ workspace = "e+1" })) end')),
    "overview": ("Window overview (SUPER+D)",
                 ("lua", 'if hl.plugin.hyprview then hl.plugin.hyprview.toggle("") end')),
    "overview-all": ("Overview of every workspace (SUPER+SHIFT+D)",
                     ("lua", 'if hl.plugin.hyprview then hl.plugin.hyprview.toggle("all special") end')),
    "confirm": ("Confirm the voice command's question", ("bubble", "confirm")),
    "cancel": ("Cancel the voice command's question", ("bubble", "cancel")),
    "play-pause": ("Play / pause media", ("argv", ["playerctl", "play-pause"])),
    "mute": ("Mute / unmute the sound", ("argv", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])),
    "dismiss": ("Dismiss the newest notification", ("argv", ["makoctl", "dismiss"])),
}
DEFAULT_MAP = {"swipe_left": "workspace-prev", "swipe_right": "workspace-next", "open_palm": "overview",
               "thumbs_up": "confirm", "thumbs_down": "cancel", "victory": "none", "fist": "none"}
SETTINGS = {            # key: (default, kind)
    "fps": (10, (8, 15)),               # looks a second while gestures / gaze are on
    "cpu": (30, (5, 100)),              # % of one core the service may use
    "hold_ms": (800, (400, 2000)),      # a pose held this long fires
    "swipe": (25, (10, 50)),            # % of the picture's width a swipe crosses
    "swap": ("off", "on-off"),          # swap left / right (a camera that mirrors)
    "feedback": ("on", "on-off"),       # a small bubble saying what fired
    "dwell_ms": (1000, (300, 5000)),    # gaze: held this long before it counts
    "gaze_focus": ("off", "on-off"),    # gaze: focus the last window on that monitor
    **{f"map_{g}": (a, "action") for g, a in DEFAULT_MAP.items()},
}
BUBBLE_APP = "Voice commands"           # voice-command.py's Notifier
MIN_FPS = 3
HAND_FRAME = (640, 480)                 # the camera's size while gestures are on
GATE_YAW = 0.6          # a face counts as turned to the screens up to this yaw
FACE_GRACE_S = 1.0      # ... and keeps counting this long after it was last seen
FACE_SCORE = 0.8
MIN_FACE = 0.06         # presence.py's: a smaller face is not at the desk
MIN_HAND = 0.06         # a hand narrower than this share of the picture is ignored
HOLD_MOVE = 0.08        # a held pose moves less than this (share of the width)
GAP_S = 0.35            # a hand missing this long is gone (one dropped frame is not)
SWIPE_S = 0.8
COOLDOWN_S = 1.0
CALIB_S = 3.0           # calibration: look this long (the first SETTLE_S not counted)
SETTLE_S = 0.5
CALIB_MIN = 5           # samples a calibration needs
GAZE_WEIGHTS = (1.0, 1.5, 0.7, 0.7)     # yaw, pitch, face x, face y
GAZE_MAX = 0.45         # farther than this from every calibration: not sure
GAZE_MARGIN = 0.8       # the nearest must be this much nearer than the next
GAZE_ALPHA = 0.5        # smoothing
FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))


def log(text, level="info"):
    desklog.log("presence", "vision: " + text, level)


# -- settings ------------------------------------------------------------------------------
def load(path=None):
    """The settings over SETTINGS' defaults, plus "calibration": {monitor:
    {"mean": [yaw, pitch, x, y], "n", "when"}}."""
    out = {k: v for k, (v, _kind) in SETTINGS.items()}
    out["calibration"] = {}
    try:
        with open(path or CONF) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return out
    data = data if isinstance(data, dict) else {}
    for key, value in data.items():
        if key == "calibration":
            out[key] = {m: c for m, c in (value.items() if isinstance(value, dict) else ())
                        if isinstance(c, dict) and valid_mean(c.get("mean"))}
            continue
        try:
            out[key] = check(key, value)
        except ValueError:
            pass
    return out


def valid_mean(mean):
    return isinstance(mean, list) and len(mean) == 4 and all(isinstance(v, (int, float)) for v in mean)


def check(key, value):
    """The value as stored, or ValueError saying what is wrong."""
    if key not in SETTINGS:
        raise ValueError(f"no setting {key!r} ({', '.join(SETTINGS)})")
    kind = SETTINGS[key][1]
    if kind == "on-off":
        value = str(value).lower()
        if value not in ("on", "off"):
            raise ValueError(f"{key} is on or off")
        return value
    if kind == "action":
        value = str(value).strip()
        if value not in ACTIONS:
            raise ValueError(f"{key}: one of {', '.join(ACTIONS)}")
        return value
    lo, hi = kind
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} is a whole number, {lo}..{hi}") from None
    if not lo <= n <= hi:
        raise ValueError(f"{key} goes from {lo} to {hi}")
    return n


def write(conf, path=None):
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = {k: v for k, v in conf.items() if k in SETTINGS and v != SETTINGS[k][0]}
    if conf.get("calibration"):
        body["calibration"] = conf["calibration"]
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".gestures-")
    with os.fdopen(fd, "w") as handle:
        json.dump(body, handle, indent=1)
    os.replace(tmp, path)


def save(key, value, path=None):
    conf = load(path)
    conf[key] = check(key, value)
    write(conf, path)


def save_calibration(monitor, mean, n, path=None):
    conf = load(path)
    conf["calibration"][monitor] = {"mean": [round(v, 4) for v in mean], "n": n, "when": int(time.time())}
    write(conf, path)


def forget(monitor, path=None):
    conf = load(path)
    if monitor == "all":
        conf["calibration"] = {}
    elif conf["calibration"].pop(monitor, None) is None:
        raise ValueError(f"{monitor} is not calibrated")
    write(conf, path)


def switches(conf=None):
    """{"gestures": bool, "gaze": bool}: privacy.conf's (OFF as shipped)."""
    conf = conf if conf is not None else privacy_settings.load()
    return {"gestures": privacy_settings.gestures_on(conf), "gaze": privacy_settings.gaze_on(conf)}


# -- hands: what pose ---------------------------------------------------------------------
def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], (a[2] if len(a) > 2 else 0) - (b[2] if len(b) > 2 else 0)]


def _len(v):
    return math.sqrt(sum(c * c for c in v))


def _dist(a, b):
    return _len(_sub(a, b))


def _cos(u, v):
    nu, nv = _len(u), _len(v)
    return sum(a * b for a, b in zip(u, v)) / (nu * nv) if nu and nv else 0.0


def finger(lm, ids):
    """"out" (straight, reaching away from the wrist), "in" (bent or
    folded) or None (in between: no pose is read from it)."""
    mcp, pip, _dip, tip = (lm[i] for i in ids)
    bend = _cos(_sub(pip, mcp), _sub(tip, pip))
    reach = _dist(lm[0], tip) / max(_dist(lm[0], pip), 1e-6)
    if bend > 0.7 and reach > 1.15:
        return "out"
    if bend < 0.35 or reach < 1.05:
        return "in"
    return None


def thumb(lm):
    """The thumb, the same way: "out" is straight and away from the palm."""
    palm = max(_dist(lm[0], lm[9]), 1e-6)
    bend = _cos(_sub(lm[3], lm[2]), _sub(lm[4], lm[3]))
    away = _dist(lm[4], lm[9]) / palm
    if bend > 0.6 and away > 0.8:
        return "out"
    if away < 0.6:
        return "in"
    return None


def classify(world, screen):
    """One hand's pose (GESTURES' still ones) or None. `world`: the model's
    21 metric 3-D landmarks (finger shapes, whatever the distance); `screen`:
    the 21 in the picture, y down (which way the thumb points)."""
    if not world or len(world) < 21 or not screen or len(screen) < 21:
        return None
    fingers = [finger(world, ids) for ids in FINGERS]
    th = thumb(world)
    if None in fingers:
        return None
    if all(f == "out" for f in fingers):
        return "open_palm" if th != "in" else None
    if fingers == ["out", "out", "in", "in"]:
        return "victory"
    if all(f == "in" for f in fingers):
        if th == "out":
            v = _sub(screen[4], screen[2])
            n = math.hypot(v[0], v[1])
            if n and v[1] < -0.7 * n:
                return "thumbs_up"
            if n and v[1] > 0.7 * n:
                return "thumbs_down"
            return None                         # a thumb sideways is nothing
        return "fist" if th == "in" else None
    return None


def hand_summary(hand, size):
    """{pose, x, y, w} for a model hand ({"screen", "world"}), x / y / w as
    shares of the picture's width / height; None when it is too small."""
    w, h = size
    pts = hand["screen"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    width = (max(xs) - min(xs)) / w
    if width < MIN_HAND:
        return None
    palm = [pts[i] for i in (0, 5, 9, 13, 17)]
    return {"pose": classify(hand.get("world"), pts), "w": width,
            "x": sum(p[0] for p in palm) / 5 / w, "y": sum(p[1] for p in palm) / 5 / h}


class Recognizer:
    """Hands, frame by frame -> a gesture now and then. feed() returns a
    GESTURES name or None. Swipes: SWIPE_S of the hand's track. Poses: the
    same pose, still, for hold_ms; then let go before it fires again."""

    def __init__(self, hold_s=0.8, swipe=0.25, swap=False):
        self.hold_s, self.swipe, self.swap = hold_s, swipe, swap
        self.track = []         # [(t, x, y)] of the present hand
        self.pose = None        # (pose, since, x, y) being held
        self.latched = None     # fired; waits for the pose to go
        self.unlatch_at = None  # ... gone since (a flicker is not letting go)
        self.cool_until = 0
        self.last_seen = None
        self.holding = None     # (pose, share of hold_s done), for the page

    def reset(self):
        self.track, self.pose, self.latched, self.holding, self.unlatch_at = [], None, None, None, None

    def feed(self, hand, now):
        if hand is None:
            if self.last_seen is None or now - self.last_seen > GAP_S:
                self.reset()
            return None
        self.last_seen = now
        x, y = hand["x"], hand["y"]
        self.track = [p for p in self.track if now - p[0] <= SWIPE_S] + [(now, x, y)]
        if now < self.cool_until:
            # the hand going back after a swipe is not a swipe the other way:
            # nothing moved during the cooldown counts afterwards
            self.track = [(now, x, y)]
            self.pose, self.holding = None, None
            return None
        fired = self.swiped(now) or self.held(hand.get("pose"), now, x, y)
        if fired:
            self.cool_until = now + COOLDOWN_S
            self.track, self.holding = [], None
        return fired

    def swiped(self, now):
        if len(self.track) < 3:
            return None
        t1, x1, y1 = self.track[-1]
        for t0, x0, y0 in self.track[:-2]:
            dx, dy = x1 - x0, y1 - y0
            if abs(dx) >= self.swipe and abs(dy) < 0.5 * abs(dx):
                # the picture is not mirrored: your hand going to YOUR right
                # moves it left in the picture
                right = dx < 0
                if self.swap:
                    right = not right
                self.pose = None
                return "swipe_right" if right else "swipe_left"
        return None

    def held(self, pose, now, x, y):
        if self.latched:                    # fired: it must be let go first
            if pose == self.latched:
                self.unlatch_at = None
            elif self.unlatch_at is None:
                self.unlatch_at = now
            elif now - self.unlatch_at >= GAP_S:
                self.latched, self.unlatch_at = None, None
        if pose is None or pose == self.latched:
            self.pose, self.holding = None, None
            return None
        if self.pose is None or self.pose[0] != pose or math.hypot(x - self.pose[2], y - self.pose[3]) > HOLD_MOVE:
            self.pose = (pose, now, x, y)
        done = (now - self.pose[1]) / self.hold_s
        self.holding = (pose, min(1.0, done))
        if done >= 1.0:
            self.latched, self.unlatch_at, self.pose = pose, None, None
            return pose
        return None


# -- gaze: which monitor -------------------------------------------------------------------
def head_pose(face, size):
    """(yaw, pitch, x, y) of one YuNet row ([x, y, w, h, right eye, left eye,
    nose, mouth corners, score]) in a picture of `size`, or None. yaw: the
    nose off the eyes' middle in eye distances (+ = toward the picture's
    right); pitch: the nose's height between the eyes (0) and the mouth (1);
    x / y: the face's centre as shares of the picture."""
    if face is None or len(face) < 15:
        return None
    w, h = size
    face = [float(v) for v in face]
    if face[14] < FACE_SCORE or face[2] < MIN_FACE * w:
        return None
    rex, rey, lex, ley, nx, ny, rmx, rmy, lmx, lmy = face[4:14]
    ex, ey = (rex + lex) / 2, (rey + ley) / 2
    eyes = math.hypot(lex - rex, ley - rey)
    mouth = (rmy + lmy) / 2 - ey
    if eyes < 4 or mouth < 2:
        return None
    return ((nx - ex) / eyes, (ny - ey) / mouth, (face[0] + face[2] / 2) / w, (face[1] + face[3] / 2) / h)


def main_face(faces, size):
    """The head pose of the biggest face (the one at the desk), or None."""
    best = None
    for face in faces if faces is not None else ():
        face = [float(v) for v in face]
        if best is None or face[2] > best[2]:
            best = face
    return head_pose(best, size) if best else None


def gaze_distance(a, b):
    return math.sqrt(sum(wt * (x - y) ** 2 for wt, x, y in zip(GAZE_WEIGHTS, a, b)))


def nearest_monitor(feat, calibration):
    """The calibrated monitor `feat` is looking at, or None (too far from all
    of them, or between two)."""
    if feat is None or len(calibration) < 2:
        return None
    ranked = sorted((gaze_distance(feat, c["mean"]), m) for m, c in calibration.items())
    best, mon = ranked[0]
    if best > GAZE_MAX or best > GAZE_MARGIN * ranked[1][0]:
        return None
    return mon


class Gaze:
    """Head poses -> the monitor you look at. feed() returns the monitor when
    a new one has held for dwell_s, else None. Calibration runs here too:
    start(), and feed() returns ("calibrated", monitor, mean, n) or
    ("calibration failed", monitor, why) when it is done."""

    def __init__(self, calibration=None, dwell_s=1.0):
        self.calibration = calibration or {}
        self.dwell_s = dwell_s
        self.smooth = None
        self.candidate = None   # (monitor, since)
        self.looking = None
        self.last_face = None
        self.calibrating = None     # (monitor, started, [samples])

    def start(self, monitor, now):
        self.calibrating = (monitor, now, [])

    def feed(self, feat, now):
        if feat is None:
            if self.last_face is None or now - self.last_face > FACE_GRACE_S:
                self.smooth, self.candidate, self.looking = None, None, None
            return self.calibration_step(None, now)
        self.last_face = now
        self.smooth = feat if self.smooth is None else tuple(
            GAZE_ALPHA * f + (1 - GAZE_ALPHA) * s for f, s in zip(feat, self.smooth))
        done = self.calibration_step(feat, now)
        if done or self.calibrating:
            return done
        mon = nearest_monitor(self.smooth, self.calibration)
        if mon is None or mon == self.looking:
            self.candidate = None
            return None
        if self.candidate is None or self.candidate[0] != mon:
            self.candidate = (mon, now)
        if now - self.candidate[1] >= self.dwell_s:
            self.looking, self.candidate = mon, None
            return mon
        return None

    def calibration_step(self, feat, now):
        if not self.calibrating:
            return None
        mon, started, samples = self.calibrating
        if feat is not None and now - started >= SETTLE_S:
            samples.append(feat)            # raw, not smoothed: the smoothing lags
        if now - started < CALIB_S:
            return None
        self.calibrating = None
        if len(samples) < CALIB_MIN:
            return ("calibration failed", mon, "no face seen long enough: sit as usual and look at it")
        mean = [sum(s[i] for s in samples) / len(samples) for i in range(4)]
        self.calibration = dict(self.calibration, **{mon: {"mean": mean, "n": len(samples)}})
        return ("calibrated", mon, mean, len(samples))


# -- the actions ---------------------------------------------------------------------------
def run(*cmd, timeout=5):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.stdout if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def bubble_id(action, runner=run):
    """The id of voice-command.py's notification offering `action`, or None."""
    try:
        shown = json.loads(runner("makoctl", "list", "-j") or "[]")
    except ValueError:
        return None
    for n in shown if isinstance(shown, list) else ():
        acts = n.get("actions") or {}
        keys = acts.keys() if isinstance(acts, dict) else [a.get("key") if isinstance(a, dict) else a for a in acts]
        if n.get("app_name") == BUBBLE_APP and action in keys:
            return n.get("id")
    return None


def commands(action, runner=run):
    """The argv lists `action` runs now ([] = nothing to do). Fixed text
    only: the catalog's Lua and argv, a notification id from makoctl."""
    if action not in ACTIONS:
        raise ValueError(f"no action {action!r}")
    what = ACTIONS[action][1]
    if what is None:
        return []
    kind, body = what
    if kind == "lua":
        return [["hyprctl", "eval", body]]
    if kind == "argv":
        return [list(body)]
    nid = bubble_id(body, runner)
    return [["makoctl", "invoke", "-n", str(nid), body]] if nid is not None else []


def do(action, runner=run):
    """Run `action`; what it ran (for the log), [] when there was nothing to do."""
    cmds = commands(action, runner)
    for argv in cmds:
        runner(*argv)
    return cmds


def locked(runner=run):
    return bool(runner("pidof", "hyprlock").strip())


def focus_on_monitor(monitor, runner=run):
    """Focus the window you used last on `monitor`'s workspace (the monitor
    itself when it has none). Nothing when it already has the focus, when
    the focused window is fullscreen, or when the screen is locked. Returns
    what it did, or None."""
    try:
        mons = json.loads(runner("hyprctl", "monitors", "-j") or "[]")
        active = json.loads(runner("hyprctl", "activewindow", "-j") or "{}")
    except ValueError:
        return None
    mon = next((m for m in mons if m.get("name") == monitor), None)
    if not all(ch.isalnum() or ch in "-_." for ch in monitor):
        return None                         # never a name that would need quoting
    if not mon or mon.get("focused") or (active or {}).get("fullscreen") or locked(runner):
        return None
    ws = (mon.get("activeWorkspace") or {}).get("id")
    try:
        clients = json.loads(runner("hyprctl", "clients", "-j") or "[]")
    except ValueError:
        clients = []
    mine = [c for c in clients if (c.get("workspace") or {}).get("id") == ws and c.get("mapped", True)
            and not c.get("hidden") and str(c.get("address", "")).startswith("0x")]
    if mine:
        last = min(mine, key=lambda c: c.get("focusHistoryID", 1 << 30))
        lua = f"hl.dispatch(hl.dsp.focus({{ window = 'address:{last['address']}' }}))"
    else:
        lua = f"hl.dispatch(hl.dsp.focus({{ monitor = '{monitor}' }}))"
    runner("hyprctl", "eval", lua)
    return "focused " + (last.get("class") or "a window" if mine else monitor)


def feedback(title, body, runner=run):
    runner("notify-send", "-a", "Gestures", "-i", "input-touchpad", "-u", "low", "-t", "1500",
           "-h", "string:x-canonical-private-synchronous:gesture", title, body)


# -- the models (run in presence's venv) ----------------------------------------------------
def palm_anchors(np):
    """The palm detector's 2016 SSD anchors (centres; 24x24 x 2, 12x12 x 6)."""
    out = []
    for size, per in ((24, 2), (12, 6)):
        for y in range(size):
            for x in range(size):
                out += [((x + 0.5) / size, (y + 0.5) / size)] * per
    return np.array(out, dtype=np.float32)


class Hands:
    """MediaPipe's two hand models through OpenCV dnn: the palm detector
    (192x192) finds a palm, the landmark model (224x224, on a crop turned so
    the hand points up) gives its 21 points. __call__(frame) -> [{"screen",
    "world", "score"}], the biggest hand only. While a hand is followed, its
    last landmarks give the next crop and the detector is skipped."""

    PALM_IN = 192
    HAND_IN = 224
    PALM_IDS = (0, 5, 9, 13, 17, 1, 2)

    def __init__(self, palm=PALM_MODEL, hand=HAND_MODEL, threads=2):
        import cv2
        import numpy as np
        self.cv2, self.np = cv2, np
        cv2.setNumThreads(threads)
        self.palm_net = cv2.dnn.readNet(palm)
        self.hand_net = cv2.dnn.readNet(hand)
        self.anchors = palm_anchors(np)
        self.follow = None

    def __call__(self, frame):
        hand = self.landmarks(frame, self.follow) if self.follow is not None else None
        if hand is None:
            palms = self.palms(frame)
            hand = self.landmarks(frame, palms[0]) if len(palms) else None
        self.follow = self.palm_from(hand["screen"]) if hand else None
        return [hand] if hand else []

    def palms(self, frame, score_min=0.6):
        cv2, np = self.cv2, self.np
        h, w = frame.shape[:2]
        ratio = self.PALM_IN / max(h, w)
        nh, nw = int(h * ratio), int(w * ratio)
        img = cv2.resize(frame, (nw, nh))
        left, top = (self.PALM_IN - nw) // 2, (self.PALM_IN - nh) // 2
        img = cv2.copyMakeBorder(img, top, self.PALM_IN - nh - top, left, self.PALM_IN - nw - left,
                                 cv2.BORDER_CONSTANT, value=(0, 0, 0))
        blob = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)[np.newaxis] / 255.0
        self.palm_net.setInput(blob)
        boxes, scores = self.palm_net.forward(self.palm_net.getUnconnectedOutLayersNames())
        score = 1 / (1 + np.exp(-scores[0, :, 0].astype(np.float64)))
        delta = boxes[0]
        scale = max(h, w)
        pad = np.array([left / ratio, top / ratio])
        cxy = delta[:, :2] / self.PALM_IN + self.anchors
        half = delta[:, 2:4] / self.PALM_IN / 2
        rects = np.concatenate([(cxy - half) * scale - pad, (cxy + half) * scale - pad], axis=1)
        keep = cv2.dnn.NMSBoxes([[float(a), float(b), float(c - a), float(d - b)] for a, b, c, d in rects],
                                score.tolist(), score_min, 0.3, top_k=5)
        keep = np.array(keep).reshape(-1)
        out = []
        for i in keep:
            pts = (delta[i, 4:18].reshape(7, 2) / self.PALM_IN + self.anchors[i]) * scale - pad
            out.append(np.r_[rects[i], pts.reshape(-1), score[i]])
        return out

    def palm_from(self, screen):
        np = self.np
        pts = np.array([screen[i][:2] for i in self.PALM_IDS], dtype=np.float64)
        return np.r_[pts.min(axis=0), pts.max(axis=0), pts.reshape(-1), 1.0]

    def crop(self, image, box, pre):
        """The palm box shifted / enlarged as MediaPipe does, cut out and
        padded square. (crop, the box, its top-left in `image`)."""
        np, cv2 = self.np, self.cv2
        size = box[1] - box[0]
        box = box + (np.array([0, 0]) if pre else np.array([0, -0.4])) * size
        centre, size = box.sum(axis=0) / 2, box[1] - box[0]
        half = size * (4 if pre else 3) / 2
        box = np.array([centre - half, centre + half]).astype(np.int32)
        box[:, 0] = np.clip(box[:, 0], 0, image.shape[1])
        box[:, 1] = np.clip(box[:, 1], 0, image.shape[0])
        img = image[box[0][1]:box[1][1], box[0][0]:box[1][0]]
        side = int(np.linalg.norm(img.shape[:2]) if pre else max(img.shape[:2]))
        ph, pw = side - img.shape[0], side - img.shape[1]
        left, top = pw // 2, ph // 2
        img = cv2.copyMakeBorder(img, top, ph - top, left, pw - left, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        return img, box, box[0] - [left, top]

    def landmarks(self, frame, palm, conf_min=0.8):
        np, cv2 = self.np, self.cv2
        image, _box, bias = self.crop(frame, palm[0:4].reshape(2, 2), True)
        if image.size == 0 or min(image.shape[:2]) < 8:
            return None
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pts = palm[4:18].reshape(7, 2) - bias
        p1, p2 = pts[0], pts[2]                             # wrist, middle finger's base
        rad = np.pi / 2 - np.arctan2(-(p2[1] - p1[1]), p2[0] - p1[0])
        rad -= 2 * np.pi * np.floor((rad + np.pi) / (2 * np.pi))
        angle = float(np.rad2deg(rad))
        box = palm[0:4].reshape(2, 2) - bias
        centre = tuple(float(v) for v in box.sum(axis=0) / 2)
        rot = cv2.getRotationMatrix2D(centre, angle, 1.0)
        rotated = cv2.warpAffine(image, rot, (image.shape[1], image.shape[0]))
        rpts = np.c_[pts, np.ones(len(pts))] @ rot.T
        crop, rbox, _ = self.crop(rotated, np.array([rpts.min(axis=0), rpts.max(axis=0)]), False)
        if crop.size == 0 or min(crop.shape[:2]) < 8:
            return None
        blob = cv2.resize(crop, (self.HAND_IN, self.HAND_IN), interpolation=cv2.INTER_AREA)
        self.hand_net.setInput(blob.astype(np.float32)[np.newaxis] / 255.0)
        lms, conf, _handed, world = self.hand_net.forward(self.hand_net.getUnconnectedOutLayersNames())
        conf = float(conf.reshape(-1)[0])
        if conf < conf_min:
            return None
        lm = lms.reshape(-1, 3).astype(np.float64)
        world = world.reshape(-1, 3).astype(np.float64)
        k = max((rbox[1] - rbox[0]) / self.HAND_IN)
        lm[:, :2] = (lm[:, :2] - self.HAND_IN / 2) * k
        lm[:, 2] *= k
        back = cv2.getRotationMatrix2D((0, 0), angle, 1.0)[:, :2]
        lm[:, :2] = lm[:, :2] @ back
        world[:, :2] = world[:, :2] @ back
        inv = cv2.invertAffineTransform(rot)
        c = np.append(rbox.sum(axis=0) / 2, 1)
        lm[:, :2] += inv @ c + bias
        return {"screen": lm.tolist(), "world": world.tolist(), "score": conf}


# -- what presence.py's watcher calls ------------------------------------------------------
class Vision:
    """Gestures + gaze over the frames presence.py's watcher already reads.

    refresh()   the switches and settings again (the watcher's slow checks)
    active      either one is on: the watcher looks faster then
    fps()       how often to look (fps, held down by the CPU budget)
    frame_size  what to ask the camera for
    frame(frame, faces, size)   one picture (and the faces YuNet found in it)
    process(hands, faces, size, now)   the same from landmarks (replay, tests)
    control(text)   "calibrate MONITOR"
    live()      what the page shows"""

    def __init__(self, hands=None, settings=load, flags=switches, runner=run, clock=time.monotonic,
                 cpu=time.process_time, dry_run=False):
        self.settings, self.flags, self.runner = settings, flags, runner
        self.clock, self.cpu, self.dry_run = clock, cpu, dry_run
        self.hands = hands
        self.hands_error = None     # the models failed: said in live(), retried when switched on again
        self.on = {"gestures": False, "gaze": False}
        self.conf = settings()
        self.recognizer = Recognizer()
        self.gaze = Gaze()
        self.face_at = None         # when a face turned to the screens was last seen
        self.cost = None            # CPU seconds per frame (smoothed)
        self.last_cpu = None
        self.events = []            # [(what, detail, wall time)] newest last, a few
        self.hand = None
        self.calibration_msg = None
        self.refresh()

    def refresh(self):
        try:
            self.on = dict(self.flags())
        except (OSError, ValueError, KeyError):
            pass
        self.conf = self.settings()
        r = self.recognizer
        r.hold_s, r.swipe, r.swap = self.conf["hold_ms"] / 1000, self.conf["swipe"] / 100, self.conf["swap"] == "on"
        self.gaze.dwell_s = self.conf["dwell_ms"] / 1000
        if not self.gaze.calibrating:
            self.gaze.calibration = dict(self.conf["calibration"])
        if not self.on["gestures"]:
            self.recognizer.reset()
            self.hand = None
            self.hands_error = None
        if not self.on["gaze"]:
            self.gaze.looking = None
            if self.gaze.calibrating:       # switched off mid-calibration
                self.calibration_msg = {"monitor": self.gaze.calibrating[0], "state": "failed",
                                        "why": "gaze is off", "at": time.time()}
                self.gaze.calibrating = None

    @property
    def active(self):
        return self.on["gestures"] or self.on["gaze"]

    @property
    def frame_size(self):
        return HAND_FRAME if self.on["gestures"] else None

    def fps(self):
        target = self.conf["fps"]
        if not self.cost:
            return target
        return max(MIN_FPS, min(target, (self.conf["cpu"] / 100) / self.cost))

    def frame(self, frame, faces, size):
        """One picture: the hand model only when gestures are on and a face
        is turned to the screens (the cheap check first)."""
        now = self.clock()
        cpu = self.cpu()
        if self.last_cpu is not None:
            used = max(0.0, cpu - self.last_cpu)
            self.cost = used if self.cost is None else 0.8 * self.cost + 0.2 * used
        self.last_cpu = cpu
        hands = []
        if self.on["gestures"] and not self.hands_error and self.facing(faces, size, now):
            try:
                if self.hands is None:
                    self.hands = Hands()
                h, w = frame.shape[:2]
                hands = [dict(x, size=(w, h)) for x in self.hands(frame)]
            except Exception as exc:    # noqa: BLE001  (cv2.error: a missing / broken model)
                # said once; presence and gaze go on without hands
                self.hands_error = f"the hand models did not load or run: {exc}"[:300]
                log(self.hands_error, "error")
        return self.process(hands, faces, size, now)

    def facing(self, faces, size, now):
        pose = main_face(faces, size)
        if pose is not None and abs(pose[0]) <= GATE_YAW:
            self.face_at = now
        return self.face_at is not None and now - self.face_at <= FACE_GRACE_S

    def process(self, hands, faces, size, now):
        """The recognizers on this frame's landmarks; runs (or, dry, only
        names) what fires. Returns [(kind, what, action)]."""
        fired = []
        if self.on["gestures"]:
            facing = self.facing(faces, size, now)
            hand = None
            if facing and hands:
                summaries = [hand_summary(h, h.get("size", size)) for h in hands]
                summaries = [s for s in summaries if s]
                hand = max(summaries, key=lambda s: s["w"]) if summaries else None
            self.hand = hand
            what = self.recognizer.feed(hand, now)
            if what:
                fired.append(("gesture", what, self.conf.get(f"map_{what}", "none")))
        if self.on["gaze"] or self.gaze.calibrating:
            got = self.gaze.feed(main_face(faces, size), now)
            if isinstance(got, tuple):
                fired.append(("calibration", got, None))
            elif got and self.on["gaze"]:
                fired.append(("gaze", got, "focus" if self.conf["gaze_focus"] == "on" else None))
        for item in fired:
            self.act(*item)
        return fired

    def act(self, kind, what, action):
        if kind == "calibration":
            if what[0] == "calibrated":
                _, mon, mean, n = what
                if not self.dry_run:
                    save_calibration(mon, mean, n)
                self.calibration_msg = {"monitor": mon, "state": "done", "n": n, "at": time.time()}
                self.note("calibrated", f"{mon} ({n} looks)")
            else:
                self.calibration_msg = {"monitor": what[1], "state": "failed", "why": what[2], "at": time.time()}
                self.note("calibration failed", f"{what[1]}: {what[2]}")
            return
        if kind == "gaze":
            done = None
            if action == "focus" and not self.dry_run:
                done = focus_on_monitor(what, self.runner)
            self.note("looking at", what + (f": {done}" if done else ""))
            return
        label = ACTIONS.get(action, ("?",))[0]
        if action == "none":
            self.note(what, "not mapped")
            return
        if self.dry_run:
            self.note(what, f"would run {action}")
            return
        if locked(self.runner):
            self.note(what, "ignored: the screen is locked")
            return
        ran = do(action, self.runner)
        self.note(what, f"{action}" + ("" if ran else " (nothing to do)"))
        if self.conf["feedback"] == "on":
            feedback(GESTURE_NAMES.get(what, what), label if ran else label + ": nothing to do", self.runner)

    def note(self, what, detail):
        self.events = (self.events + [(what, detail, time.time())])[-5:]
        if not self.dry_run:
            log(f"{what}: {detail}")

    def control(self, text):
        word, _, arg = text.strip().partition(" ")
        if word == "calibrate" and arg:
            if not self.on["gaze"]:
                self.calibration_msg = {"monitor": arg, "state": "failed", "why": "gaze is off", "at": time.time()}
                return
            self.gaze.start(arg, self.clock())
            self.calibration_msg = {"monitor": arg, "state": "looking", "at": time.time()}
            log(f"calibrating {arg}: look at it")

    def live(self):
        hold = self.recognizer.holding
        return {"gestures": self.on["gestures"], "gaze": self.on["gaze"],
                "fps": round(self.fps(), 1) if self.active else None,
                "cpu_ms": round(self.cost * 1000, 1) if self.cost else None,
                "hand": (self.hand or {}).get("pose") if self.hand else None,
                "holding": [hold[0], round(hold[1], 2)] if hold else None,
                "looking_at": self.gaze.looking, "calibration": self.calibration_msg,
                "events": self.events, "error": self.hands_error}


# -- the commands ----------------------------------------------------------------------------
def poke(msg):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(msg.encode(), CTL_SOCK)
        return True
    except OSError:
        return False


def read_live():
    try:
        with open(LIVE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def monitors():
    try:
        return [m.get("name") for m in json.loads(run("hyprctl", "monitors", "-j") or "[]") if m.get("name")]
    except ValueError:
        return []


def status():
    service = run("systemctl", "--user", "is-active", "presence.service").strip() or "inactive"
    live = read_live() if service == "active" else None
    return {"switches": switches(), "presence": privacy_settings.presence_on(privacy_settings.load()),
            "settings": {k: v for k, v in load().items()}, "service": service,
            "installed": {"venv": os.path.exists(VENV_PY), "palm": os.path.exists(PALM_MODEL),
                          "hand": os.path.exists(HAND_MODEL)},
            "monitors": monitors(), "live": (live or {}).get("vision"),
            "camera": (live or {}).get("camera"), "why": (live or {}).get("why"),
            "gestures": list(GESTURES), "names": GESTURE_NAMES,
            "actions": {k: v[0] for k, v in ACTIONS.items()}, "conf": CONF}


def human(data):
    s, sw, live = data["settings"], data["switches"], data.get("live") or {}
    lines = [f"gestures {'on' if sw['gestures'] else 'off'}, gaze {'on' if sw['gaze'] else 'off'} "
             f"(Settings > Gestures & gaze); presence service {data['service']}",
             "gestures: " + ", ".join(f"{g} -> {s['map_' + g]}" for g in GESTURES),
             f"hold {s['hold_ms']} ms, swipe {s['swipe']} %, {s['fps']} fps, cpu {s['cpu']} %, "
             f"gaze dwell {s['dwell_ms']} ms, focus {s['gaze_focus']}",
             "calibrated: " + (", ".join(s["calibration"]) or "none")]
    if not all(data["installed"].values()):
        lines.append(f"not installed: {DATA} (the venv and the two hand models)")
    if live:
        lines.append(f"now: {live.get('fps')} fps, hand {live.get('hand') or '-'}, "
                     f"looking at {live.get('looking_at') or '-'}")
    return "\n".join(lines)


def calibrate(monitor, wait=CALIB_S + 4, sleep=time.sleep):
    """Ask the service to calibrate `monitor`; wait for its answer."""
    if monitor not in monitors():
        return f"gestures: no monitor {monitor!r} ({', '.join(monitors())})"
    if not switches()["gaze"]:
        return "gestures: gaze is off (Settings > Gestures & gaze)"
    if not poke("calibrate " + monitor):
        return "gestures: the presence service is not running"
    start = time.time()
    while time.time() - start < wait:
        sleep(0.3)
        msg = ((read_live() or {}).get("vision") or {}).get("calibration") or {}
        if msg.get("monitor") == monitor and msg.get("at", 0) >= start - 1 and msg.get("state") != "looking":
            if msg["state"] == "done":
                print(f"{monitor} calibrated ({msg.get('n')} looks)")
                return 0
            return f"gestures: {msg.get('why') or 'calibration failed'}"
    return "gestures: no answer from the service (is the camera paused?)"


def toggle(which):
    on = not switches()[which]
    res = subprocess.run([sys.executable, PRIVACY, which, "on" if on else "off"], capture_output=True,
                         text=True, timeout=30)
    if res.returncode:
        return (res.stderr or res.stdout).strip() or f"gestures: could not switch {which}"
    subprocess.run(["notify-send", "-a", "Gestures", "-i", "camera-web", "-u", "low",
                    f"{'Gestures' if which == 'gestures' else 'Gaze'} {'on' if on else 'off'}",
                    "the camera icon in the bar shows when it is in use" if on else ""],
                   capture_output=True, timeout=5, check=False)
    return 0


def ensure_venv(argv):
    """test-image needs OpenCV: re-run in presence's venv when this python has none."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        venv = os.path.dirname(os.path.dirname(VENV_PY))
        if os.path.exists(VENV_PY) and os.path.realpath(sys.prefix) != os.path.realpath(venv):
            os.execv(VENV_PY, [VENV_PY, os.path.abspath(__file__), *argv])
        sys.exit("gestures: no OpenCV (presence's venv: ~/.local/share/presence/venv)")


def test_images(paths):
    """What the models make of each photo: hands, poses, head pose (no camera)."""
    import cv2
    hands = Hands()
    face_net = None
    face_model = os.path.join(DATA, "face_detection_yunet_2023mar.onnx")
    if os.path.exists(face_model):
        face_net = cv2.FaceDetectorYN.create(face_model, "", (320, 240), FACE_SCORE, 0.3, 5)
    out = []
    for path in paths:
        frame = cv2.imread(path)
        if frame is None:
            out.append({"file": path, "error": "not an image"})
            continue
        h, w = frame.shape[:2]
        hands.follow = None                 # every photo on its own
        t = time.perf_counter()
        found = hands(frame)
        ms = (time.perf_counter() - t) * 1000
        entry = {"file": path, "ms": round(ms, 1), "hands": []}
        for hand in found:
            s = hand_summary(hand, (w, h)) or {}
            entry["hands"].append({"pose": s.get("pose"), "score": round(hand["score"], 2),
                                   "fingers": [finger(hand["world"], ids) for ids in FINGERS],
                                   "thumb": thumb(hand["world"])})
        if face_net is not None:
            face_net.setInputSize((w, h))
            _ok, faces = face_net.detect(frame)
            pose = main_face(faces, (w, h))
            entry["head"] = [round(v, 3) for v in pose] if pose else None
        out.append(entry)
        del frame
    return out


def replay(path, settings=None, flags=None):
    """A recorded sequence through Vision, dry: JSON lines of {"t": seconds,
    "size": [w, h], "face": a YuNet row or null, "hands": [{"screen": 21
    [x, y, z] in pixels, "world": 21 [x, y, z]}]}, optional "calibrate":
    MONITOR on a line starts a calibration. Returns [(t, kind, what, action)]."""
    clock = [0.0]
    vision = Vision(hands=None, settings=settings or load,
                    flags=flags or (lambda: {"gestures": True, "gaze": True}),
                    runner=lambda *a, **k: "", clock=lambda: clock[0], cpu=lambda: 0.0, dry_run=True)
    out = []
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            item = json.loads(line)
            clock[0] = float(item.get("t", clock[0]))
            if item.get("calibrate"):
                vision.control("calibrate " + item["calibrate"])
            size = tuple(item.get("size") or (640, 480))
            faces = [item["face"]] if item.get("face") else None
            hands = [dict(h, size=size) for h in item.get("hands") or ()]
            for kind, what, action in vision.process(hands, faces, size, clock[0]):
                out.append((clock[0], kind, what, action))
    return out


def main(argv):
    cmd, args = (argv[0] if argv else "status"), argv[1:]
    if cmd == "status":
        data = status()
        print(json.dumps(data) if "--json" in args else human(data))
    elif cmd == "set" and len(args) == 2:
        try:
            save(args[0], args[1])
        except ValueError as err:
            return f"gestures: {err}"
        poke("reload")
    elif cmd == "map" and len(args) == 2:
        if args[0] not in GESTURES:
            return f"gestures: no gesture {args[0]!r} ({', '.join(GESTURES)})"
        try:
            save("map_" + args[0], args[1])
        except ValueError as err:
            return f"gestures: {err}"
        poke("reload")
    elif cmd == "actions":
        print(json.dumps({k: v[0] for k, v in ACTIONS.items()}) if "--json" in args else
              "\n".join(f"{k:16} {v[0]}" for k, v in ACTIONS.items()))
    elif cmd == "do" and len(args) == 1:
        if args[0] not in ACTIONS:
            return f"gestures: no action {args[0]!r} ({', '.join(ACTIONS)})"
        ran = do(args[0])
        print("\n".join(" ".join(a) for a in ran) or "nothing to do")
    elif cmd == "toggle" and args and args[0] in ("gestures", "gaze"):
        return toggle(args[0])
    elif cmd == "calibrate" and len(args) == 1:
        return calibrate(args[0])
    elif cmd == "forget" and len(args) == 1:
        try:
            forget(args[0])
        except ValueError as err:
            return f"gestures: {err}"
        poke("reload")
    elif cmd == "test-image" and args:
        ensure_venv(argv)
        print(json.dumps(test_images(args), indent=1))
    elif cmd == "replay" and len(args) == 1:
        for t, kind, what, action in replay(args[0]):
            print(f"{t:7.2f}  {kind:11} {what if not isinstance(what, tuple) else ' '.join(map(str, what[:2]))}"
                  + (f"  -> {action}" if action else ""))
    else:
        print(__doc__.split("\n\n")[1])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
