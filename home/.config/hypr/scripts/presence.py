#!/usr/bin/env python3
"""Presence: is someone at the desk? The webcam, looked at once or twice a
second, answers only that -- a face, roughly facing the screen -- and the
desktop acts on it (presence.service; Settings > Presence, switched on in
Settings > Privacy). OFF as shipped: nothing opens the camera until you turn
it on there.

    presence.py run                     the service (runs in the venv below)
    presence.py status [--json]         the switch, the settings, what it sees now
    presence.py set KEY VALUE           a setting (SETTINGS below)
    presence.py pause [MINUTES]         release the camera for a while (default 60)
    presence.py resume                  ... and take it back now
    presence.py toggle-pause            the key: pause for an hour, or resume
    presence.py idle on|off             hypridle's listener (IDLE_S of no input); hypridle
                                        itself sends the same word with scripts/presence-idle
                                        (sh + ncat, no Python start every 20 s)
    presence.py watch                   look WATCH_FPS times a second for WATCH_S (the
                                        page's live view keeps asking while it is open)
    presence.py cameras [--json]        the capture devices (from sysfs: none is opened)
    presence.py test-image FILE...      what the detector makes of photos -- the way to
                                        try it without the camera

What it does with the answer (each one a setting, all but DND on):

    lock        you have gone (no face for away_s AND no keyboard / mouse for
                IDLE_S): lock the screen the usual way, `loginctl lock-session`
                (hypridle's lock_cmd -> hyprlock, never twice)
    wake        you are back (a face facing the screen in BACK_FRAMES frames in
                a row): turn the screens on if they were off. NEVER unlocks:
                the lock screen still wants your password
    media       pause what plays (playerctl) when you go, play the same
                players again when you are back
    dnd         Do Not Disturb while you are away (only off again if it was
                this that turned it on and it is still on -- auto-dnd.py's rule)
    automations the "presence-away" / "presence-back" triggers
                (`automations.py event ...`, through its socket)

Away needs both: no face AND no input, so typing in bad light never locks
you out. Input while "away" is "back" too (hypridle's on-resume): the camera
is not needed to notice you returning to the keyboard. The input side is
hypridle's, so whatever holds hypridle off (a fullscreen window, a browser
or mpv playing a video, Keep awake) also keeps "away" from happening: you
are not locked out of a film you are watching from the sofa, and a video
playing is not paused when you leave either -- music, which holds nothing
off, is.

Privacy, by construction:
  * frames live in memory, one at a time, at 320x240; nothing is written to
    disk, sent anywhere, or kept past the next frame. The only output is
    present / away. `test-image` reads files you name and nothing else.
  * the camera is open only while it is needed: never while paused, in
    gamemode, while another app holds a /dev/video* node (a call: it is then
    released at once and left alone until that app is done), or when no action
    is on. While you are away it is opened in short bursts every AWAY_EVERY_S,
    and after LONG_AWAY_S of being away not at all (your input brings it back).
  * the top bar's camera indicator (waybar/scripts/privacy.py: any process
    holding /dev/video*) shows "presence" whenever the camera is open -- this
    process names itself that.
  * the master switch is privacy.conf's presence=on|off (Settings > Privacy,
    `privacy_settings.py presence on|off`, which also enables / disables the
    service); the service checks it again every few seconds and stops when
    it is off.

The detector is OpenCV's YuNet (a 230 KB ONNX face model, CPU, a few ms a
frame) in a venv of its own: ~/.local/share/presence/venv (pip:
opencv-python-headless, numpy) and ~/.local/share/presence/
face_detection_yunet_2023mar.onnx. Facing: the nose between the eyes
(|yaw| <= YAW_MAX of the eye distance) and the eyes roughly level; a face in
profile still counts as "here", but only a facing one as "back", so someone
walking past does not wake the screens.

Gestures and gaze (gestures.py; Settings > Gestures & gaze; privacy.conf's
gestures= / gaze=, OFF as shipped) ride on this process: it stays the
camera's one owner, hands each frame and the faces YuNet found in it to
gestures.Vision, and looks 8-15 times a second (640x480 for hands) only
while one of them is on. Either one keeps the service running with
presence's own switch off; its away / back actions then do nothing.

Settings: $XDG_STATE_HOME/hypr/presence.json. What it is doing now (for the
page): $XDG_RUNTIME_DIR/presence-state.json, with the last look's faces as
boxes (shares of the frame, never the picture) for the page's live view. Control socket:
$XDG_RUNTIME_DIR/presence.sock. Logs: journalctl --user -t presence.
"""
import ctypes
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")     # before any `import cv2`
HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
sys.path.insert(0, HERE)
import desklog  # noqa: E402
import privacy_settings  # noqa: E402  (the master switch)

HOME = os.path.expanduser("~")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "presence")
VENV_PY = os.path.join(DATA, "venv", "bin", "python")
MODEL = os.path.join(DATA, "face_detection_yunet_2023mar.onnx")
CONF = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                    "hypr", "presence.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LIVE = os.path.join(RUNTIME, "presence-state.json")
CTL_SOCK = os.path.join(RUNTIME, "presence.sock")
AUTOMATIONS_SOCK = os.path.join(RUNTIME, "automations.sock")
SYSFS = "/sys/class/video4linux"
UNIT = "presence.service"

SETTINGS = {            # key: (default, kind)
    "lock": ("on", "on-off"),
    "wake": ("on", "on-off"),
    "media": ("on", "on-off"),
    "dnd": ("off", "on-off"),
    "automations": ("on", "on-off"),
    "away_s": (60, (15, 900)),
    "fps": (1, (1, 2)),
    "camera": ("auto", "text"),
}
ACTIONS = ("lock", "wake", "media", "dnd", "automations")
FRAME = (320, 240)
YAW_MAX = 0.35          # nose offset from between the eyes, in eye distances
ROLL_MAX = 0.5          # eye height difference, in eye distances
MIN_FACE = 0.06         # a face narrower than this share of the frame is not at the desk
SCORE = 0.8
BACK_FRAMES = 2
IDLE_S = 20             # hypridle's listener (hypridle.conf): no input this long
AWAY_EVERY_S = 4        # while away: a burst this often
BURST_FRAMES = 3        # frames read per burst (the first ones are often dark)
LONG_AWAY_S = 1800      # away this long: stop looking; input brings it back
CHECK_S = 5             # gamemode / other camera users / the switch, this often
RETRY_S = 30            # a camera that would not open: try again after this
DND_MODE = "do-not-disturb"
WATCH_FPS = 5           # Settings > Presence open: its live view asks for this many looks ...
WATCH_S = 15            # ... for this long, again and again while it stays open
MAX_BOXES = 4


def log(text, level="info"):
    desklog.log("presence", text, level)


# -- settings ------------------------------------------------------------------------------
def load(path=None):
    out = {k: v for k, (v, _kind) in SETTINGS.items()}
    try:
        with open(path or CONF) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return out
    for key, value in (data if isinstance(data, dict) else {}).items():
        try:
            out[key] = check(key, value)
        except ValueError:
            pass
    return out


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
    if kind == "text":
        value = str(value).strip()
        if not value or len(value) > 80:
            raise ValueError(f"{key}: auto, a /dev/video* path or a camera's name")
        return value
    lo, hi = kind
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} is a whole number, {lo}..{hi}") from None
    if not lo <= n <= hi:
        raise ValueError(f"{key} goes from {lo} to {hi}")
    return n


def save(key, value, path=None):
    path = path or CONF
    conf = load(path)
    conf[key] = check(key, value)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".presence-")
    with os.fdopen(fd, "w") as handle:
        json.dump({k: v for k, v in conf.items() if v != SETTINGS[k][0]}, handle, indent=1)
    os.replace(tmp, path)


def switched_on():
    """privacy.conf's master switch (off unless you turned it on)."""
    return privacy_settings.presence_on(privacy_settings.load())


def camera_wanted():
    """Presence, gestures or gaze (gestures.py, which reads this process's
    frames): any of them keeps the service running."""
    return privacy_settings.camera_wanted(privacy_settings.load())


# -- what a face is -------------------------------------------------------------------------
def facing(face, frame_w):
    """(here, facing) for one YuNet row: [x, y, w, h, right eye x, y, left
    eye x, y, nose x, y, mouth corners x, y, x, y, score]."""
    if len(face) < 15 or face[14] < SCORE or face[2] < MIN_FACE * frame_w:
        return False, False
    rex, rey, lex, ley, nx = face[4], face[5], face[6], face[7], face[8]
    eyes = abs(lex - rex)
    if eyes < 4:
        return True, False
    yaw = (nx - (rex + lex) / 2) / eyes
    roll = abs(ley - rey) / eyes
    return True, abs(yaw) <= YAW_MAX and roll <= ROLL_MAX


def judge(faces, frame_w):
    """(anyone here, anyone facing the screen) for one frame's faces."""
    here = look = False
    for face in faces if faces is not None else ():
        h, f = facing([float(v) for v in face], frame_w)
        here, look = here or h, look or f
    return here, look


def boxes(faces, size):
    """The faces one look found, for the page: where (shares of the frame),
    how sure, facing or not. No pixels."""
    w, h = size
    out = []
    for face in (faces if faces is not None else ())[:MAX_BOXES]:
        face = [float(v) for v in face]
        here, look = facing(face, w)
        out.append({"x": round(face[0] / w, 3), "y": round(face[1] / h, 3), "w": round(face[2] / w, 3),
                    "h": round(face[3] / h, 3), "score": round(face[14], 2) if len(face) > 14 else 0,
                    "here": here, "facing": look})
    return out


class Presence:
    """present / away from what each frame shows and whether you are typing.

    feed() returns "away", "back" or None. Away: no face for away_s while the
    input is idle. Back: BACK_FRAMES facing frames in a row, or any input."""

    def __init__(self, away_s, clock=time.monotonic):
        self.away_s, self.clock = away_s, clock
        self.state = "present"
        self.last_seen = clock()
        self.since = clock()
        self.streak = 0
        self.idle = False       # unknown counts as busy: never lock blind

    def feed(self, here, look):
        now = self.clock()
        if self.state == "present":
            if here or not self.idle:       # typing counts as being here
                self.last_seen = now
            elif self.idle and now - self.last_seen >= self.away_s:
                return self.go("away", now)
            return None
        self.streak = self.streak + 1 if look else 0
        if self.streak >= BACK_FRAMES:
            return self.go("present", now)
        return None

    def input(self, idle):
        """hypridle: idle on / off. Input while away is being back."""
        self.idle = idle
        now = self.clock()
        if idle:                            # the last input was IDLE_S ago
            self.last_seen = max(self.last_seen, now - IDLE_S)
        else:
            self.last_seen = now
            if self.state == "away":
                return self.go("present", now)
        return None

    def go(self, state, now):
        self.state, self.since, self.streak = state, now, 0
        self.last_seen = now
        return "away" if state == "away" else "back"


# -- the camera -----------------------------------------------------------------------------
def cameras():
    """[{dev, name, usb}] capture nodes from sysfs (index 0: the metadata
    nodes are index 1), USB ones first. Nothing is opened."""
    out = []
    try:
        names = sorted(os.listdir(SYSFS), key=lambda n: int(n[5:]) if n[5:].isdigit() else 99)
    except OSError:
        return out
    for node in names:
        if not node.startswith("video"):
            continue
        base = os.path.join(SYSFS, node)
        if read(os.path.join(base, "index")).strip() not in ("", "0"):
            continue
        try:
            usb = "/usb" in os.path.realpath(os.path.join(base, "device"))
        except OSError:
            usb = False
        out.append({"dev": "/dev/" + node, "name": read(os.path.join(base, "name")).strip(), "usb": usb})
    out.sort(key=lambda c: not c["usb"])
    return out


def pick_cameras(choice, found):
    """The devices to try, in order, for the "camera" setting."""
    if choice == "auto":
        return [c["dev"] for c in found]
    if choice.startswith("/dev/"):
        return [choice]
    return [c["dev"] for c in found if choice.lower() in c["name"].lower()]


def read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def other_camera_users(me=None):
    """Names of the other processes holding a /dev/video* node (a call)."""
    me = me if me is not None else os.getpid()
    users = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"/proc/{pid}/fd/{fd}").startswith("/dev/video"):
                    users.add(read(f"/proc/{pid}/comm").strip() or pid)
                    break
            except OSError:
                continue
    return sorted(users)


class Camera:
    """One cv2.VideoCapture, opened on demand and released as soon as it is
    not needed. Frames are returned, never kept."""

    def __init__(self, devices):
        self.devices, self.cap, self.dev = devices, None, None
        self.size = FRAME           # gestures.py's HAND_FRAME while gestures are on

    def open(self):
        import cv2
        for dev in self.devices:
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ok, _frame = cap.read()
                if ok:
                    self.cap, self.dev = cap, dev
                    return True
            cap.release()
        return False

    def frame(self):
        if self.cap is None and not self.open():
            return None
        ok, frame = self.cap.read()
        if not ok:
            self.release()
            return None
        return frame

    def release(self):
        if self.cap is not None:
            self.cap.release()
        self.cap = None

    @property
    def is_open(self):
        return self.cap is not None


class Detector:
    def __init__(self, model=None):
        import cv2
        self.cv2 = cv2
        self.net = cv2.FaceDetectorYN.create(model or MODEL, "", FRAME, SCORE, 0.3, 5)
        self.size = FRAME
        self.faces = None

    def __call__(self, frame):
        """(here, facing) for one BGR frame."""
        h, w = frame.shape[:2]
        if w > FRAME[0]:            # 640x480 for gestures' hands: faces are found at 320
            scale = FRAME[0] / w
            frame = self.cv2.resize(frame, (FRAME[0], int(h * scale)))
            h, w = frame.shape[:2]
        if (w, h) != self.size:
            self.net.setInputSize((w, h))
            self.size = (w, h)
        _ok, faces = self.net.detect(frame)
        self.faces = faces          # for gestures.py's gaze (in self.size's pixels)
        return judge(faces, w)


# -- what it does -------------------------------------------------------------------------
def run(*cmd, timeout=5):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.stdout if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class Actions:
    """away() / back(): the switched-on actions, never fighting you (DND
    and media are only undone when it was this that did them)."""

    def __init__(self, runner=run):
        self.run = runner
        self.paused_players = []
        self.our_dnd = False

    def away(self, conf):
        done = []
        if conf["media"] == "on":
            self.paused_players = []
            for player in self.run("playerctl", "-l").split():
                if self.run("playerctl", "-p", player, "status").strip() == "Playing":
                    self.run("playerctl", "-p", player, "pause")
                    self.paused_players.append(player)
            if self.paused_players:
                done.append("paused " + ", ".join(self.paused_players))
        if conf["dnd"] == "on" and DND_MODE not in self.run("makoctl", "mode").split():
            self.run("makoctl", "mode", "-a", DND_MODE)
            self.our_dnd = True
            done.append("do not disturb on")
        if conf["automations"] == "on":
            poke_automations("presence-away")
        if conf["lock"] == "on" and not self.run("pidof", "hyprlock").strip():
            self.run("loginctl", "lock-session")
            done.append("locked")
        return done

    def back(self, conf):
        done = []
        if conf["wake"] == "on" and screens_off(self.run):
            self.run("hyprctl", "dispatch", "hl.dsp.dpms({ on = true })")
            done.append("screens on")
        if conf["media"] == "on":
            for player in self.paused_players:
                if self.run("playerctl", "-p", player, "status").strip() == "Paused":
                    self.run("playerctl", "-p", player, "play")
                    done.append("playing " + player)
        self.paused_players = []
        if self.our_dnd:
            if DND_MODE in self.run("makoctl", "mode").split():
                self.run("makoctl", "mode", "-r", DND_MODE)
                done.append("do not disturb off")
            self.our_dnd = False
        if conf["automations"] == "on":
            poke_automations("presence-back")
        return done


def screens_off(runner=run):
    try:
        mons = json.loads(runner("hyprctl", "monitors", "-j") or "[]")
    except ValueError:
        return False
    return any(m.get("dpmsStatus") is False for m in mons)


def poke_automations(event):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(f"event {event}".encode(), AUTOMATIONS_SOCK)
    except OSError:
        pass


def gamemode_on(runner=run):
    """lua/gamemode.lua's own test: animations off is gamemode on."""
    try:
        answer = json.loads(runner("hyprctl", "getoption", "animations:enabled", "-j") or "{}")
    except ValueError:
        return False
    return answer.get("bool") is False or answer.get("int") == 0


def name_process(name=b"presence"):
    """So the bar's camera indicator says "presence" (prctl PR_SET_NAME)."""
    try:
        ctypes.CDLL(None).prctl(15, ctypes.c_char_p(name), 0, 0, 0)
    except (OSError, AttributeError):
        pass


# -- the service ---------------------------------------------------------------------------
class Watcher:
    """The loop: when to look, what the look means, when to let go."""

    def __init__(self, camera=None, detector=None, actions=None, clock=time.monotonic,
                 busy=other_camera_users, gaming=gamemode_on, enabled=switched_on, settings=load,
                 vision=None):
        self.vision = vision        # gestures.Vision: gestures + gaze on the same frames
        self.watching = True        # presence's own switch (enabled()); off = only vision
        self.clock = clock
        self.settings = settings
        self.conf = settings()
        self.camera = camera
        self.detector = detector
        self.actions = actions or Actions()
        self.busy, self.gaming, self.enabled = busy, gaming, enabled
        self.presence = Presence(self.conf["away_s"], clock)
        self.pause_until = 0
        self.why = None             # why the camera is not being used, or None
        self.next_check = 0
        self.next_look = 0
        self.retry_at = 0
        self.last_event = None
        self.warned = False         # "no picture" said once until a picture comes
        self.watch_until = 0        # the page's live view is open: look faster
        self.look = None            # the last look, for the live view

    def needed(self):
        """Why the camera must stay closed now, or None."""
        now = self.clock()
        if now < self.pause_until:
            return "paused"
        if not (self.watching and any(self.conf[a] == "on" for a in ACTIONS)) and not self.seeing():
            return "every action is off"
        if self.presence.state == "away" and now - self.presence.since >= LONG_AWAY_S:
            return "away a long time: waiting for the keyboard or mouse"
        return self.why

    def checks(self):
        """The slow checks, every CHECK_S: the switch, gamemode, other camera
        users. False when the service should stop."""
        now = self.clock()
        if now < self.next_check:
            return True
        self.next_check = now + CHECK_S
        self.watching = self.enabled()
        if self.vision is not None:
            self.vision.refresh()
            size = (self.vision.frame_size if self.seeing() else None) or FRAME
            if getattr(self.camera, "size", size) != size:
                self.camera.release()       # reopened at the new size
                self.camera.size = size
        if not self.watching and not self.seeing():
            return False
        camera = self.conf["camera"]
        self.conf = self.settings()
        self.presence.away_s = self.conf["away_s"]
        if self.conf["camera"] != camera and hasattr(self.camera, "devices"):
            self.camera.release()           # another camera picked on the page
            self.camera.devices = pick_cameras(self.conf["camera"], cameras())
            self.retry_at = 0
            log(f"camera: {', '.join(self.camera.devices) or 'none found'}")
        why = None
        if self.gaming():
            why = "gamemode"
        else:
            others = self.busy()
            if others:
                why = "the camera is in use by " + ", ".join(others)
        if why and why != self.why:
            log(f"camera released: {why}")
        self.why = why
        return True

    def step(self):
        """One turn of the loop; returns how long to sleep."""
        now = self.clock()
        why = self.needed()
        if why:
            self.camera.release()
            return 1.0
        if now < self.retry_at or now < self.next_look:
            return max(0.05, min(self.retry_at, self.next_look) - now) if now < self.retry_at else \
                max(0.05, self.next_look - now)
        away = self.presence.state == "away"
        frames = BURST_FRAMES if away else 1
        result = None
        for _ in range(frames):
            frame = self.camera.frame()
            if frame is None:
                self.camera.release()
                self.retry_at = now + RETRY_S
                if not self.warned:
                    log(f"no picture from the camera; trying again every {RETRY_S} s", "warning")
                    self.warned = True
                return 1.0
            self.warned = False
            result = self.detector(frame)
            self.look = {"here": result[0], "facing": result[1], "at": time.time(),
                         "faces": boxes(getattr(self.detector, "faces", None),
                                        getattr(self.detector, "size", FRAME))}
            if self.seeing():               # gestures / gaze: the same frame, the same faces
                self.vision.frame(frame, getattr(self.detector, "faces", None),
                                  getattr(self.detector, "size", FRAME))
            del frame                       # nothing outlives the look
            if not away or result[1]:
                break
        if away:
            self.camera.release()           # bursts only while away
        self.event(self.presence.feed(*result))
        fps = self.vision.fps() if self.seeing() else self.conf["fps"]
        if now < self.watch_until:
            fps = max(fps, WATCH_FPS)
        period = AWAY_EVERY_S if self.presence.state == "away" else 1.0 / fps
        self.next_look = now + period
        return max(0.05, period)

    def seeing(self):
        """Gestures or gaze on: look faster, and hand them each frame."""
        return self.vision is not None and self.vision.active

    def event(self, what):
        if not what or not self.watching:   # presence itself switched off: only vision
            return
        done = self.actions.away(self.conf) if what == "away" else self.actions.back(self.conf)
        self.last_event = (what, time.time())
        log(f"{what}: " + (", ".join(done) if done else "nothing to do"))

    def control(self, msg):
        word, _, arg = msg.strip().partition(" ")
        if word == "idle" and arg in ("on", "off"):
            self.event(self.presence.input(arg == "on"))
        elif word == "pause":
            minutes = int(arg) if arg.isdigit() else 60
            self.pause_until = self.clock() + minutes * 60
            self.camera.release()
            log(f"paused for {minutes} min")
        elif word == "resume":
            self.pause_until = 0
            self.next_check = 0
            log("resumed")
        elif word == "reload":
            self.next_check = 0
        elif word == "watch":
            self.watch_until = self.clock() + WATCH_S
            self.next_look = min(self.next_look, self.clock())
        elif word == "calibrate" and self.vision is not None:
            self.vision.refresh()           # gaze may have been switched on a moment ago
            self.vision.control(msg)

    def live(self):
        now = self.clock()
        return {"state": self.presence.state, "camera": self.camera.is_open, "device": self.camera.dev,
                "why": self.needed(), "idle": self.presence.idle,
                "paused_for": max(0, int(self.pause_until - now)),
                "seen_ago": int(now - self.presence.last_seen),
                "last_event": self.last_event, "pid": os.getpid(), "updated": time.time(),
                "watching": self.watching, "look": self.look, "watched": now < self.watch_until,
                "vision": self.vision.live() if self.vision is not None else None}


def write_live(data):
    try:
        fd, tmp = tempfile.mkstemp(dir=RUNTIME, prefix=".presence-")
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, LIVE)
    except OSError:
        pass


def serve():
    if not camera_wanted():
        print("presence: off in Settings > Privacy (privacy_settings.py presence on), and so are "
              "gestures and gaze", file=sys.stderr)
        return 0
    if not os.path.exists(MODEL):
        log(f"no face model at {MODEL}", "error")
        return 1
    name_process()
    conf = load()
    devices = pick_cameras(conf["camera"], cameras())
    if not devices:
        log("no camera found", "warning")
    import gestures         # gestures + gaze: they share this camera, never open their own
    watcher = Watcher(camera=Camera(devices), detector=Detector(), vision=gestures.Vision())
    try:
        os.unlink(CTL_SOCK)
    except OSError:
        pass
    ctl = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    ctl.bind(CTL_SOCK)
    ctl.settimeout(0)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    log(f"watching for presence (cameras: {', '.join(devices) or 'none'})")
    try:
        while True:
            if not watcher.checks():
                log("switched off in Settings > Privacy: stopping")
                return 0
            wait = watcher.step()
            write_live(watcher.live())
            ready, _, _ = select.select([ctl], [], [], wait)
            if ready:
                watcher.control(ctl.recv(256).decode("utf-8", "replace"))
                write_live(watcher.live())
    finally:
        watcher.camera.release()
        for path in (CTL_SOCK, LIVE):
            try:
                os.unlink(path)
            except OSError:
                pass


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


def status():
    active = run("systemctl", "--user", "is-active", UNIT).strip()
    return {"on": switched_on(), "settings": load(), "service": active or "inactive",
            "installed": {"venv": os.path.exists(VENV_PY), "model": os.path.exists(MODEL)},
            "cameras": cameras(), "live": read_live() if active == "active" else None,
            "idle_s": IDLE_S, "conf": CONF,
            "gestures": privacy_settings.gestures_on(privacy_settings.load()),
            "gaze": privacy_settings.gaze_on(privacy_settings.load())}


def human(data):
    s, live = data["settings"], data.get("live")
    lines = [f"presence {'on' if data['on'] else 'off'} (Settings > Privacy), service {data['service']}",
             "actions: " + ", ".join(f"{a} {s[a]}" for a in ACTIONS) + f"; away after {s['away_s']} s, "
             f"{s['fps']} fps, camera {s['camera']}"]
    if not all(data["installed"].values()):
        lines.append(f"not installed: {DATA} (venv with opencv-python-headless, the YuNet model)")
    if live:
        lines.append(f"now: {live['state']}, camera {'open' if live['camera'] else 'closed'}"
                     + (f" ({live['why']})" if live.get("why") else ""))
    return "\n".join(lines)


def test_images(paths):
    """What the detector makes of each photo (no camera)."""
    import cv2
    detector = Detector()
    out = []
    for path in paths:
        frame = cv2.imread(path)
        if frame is None:
            out.append({"file": path, "error": "not an image"})
            continue
        here, look = detector(frame)
        out.append({"file": path, "here": here, "facing": look})
        del frame
    return out


def main(argv):
    cmd, args = (argv[0] if argv else "status"), argv[1:]
    if cmd == "run":
        return serve()
    if cmd == "status":
        data = status()
        print(json.dumps(data) if "--json" in args else human(data))
    elif cmd == "set" and len(args) == 2:
        try:
            save(args[0], args[1])
        except ValueError as err:
            return f"presence: {err}"
        poke("reload")
    elif cmd == "pause":
        if args and not (args[0].isdigit() and 1 <= int(args[0]) <= 24 * 60):
            return "presence: pause MINUTES (1..1440)"
        if not poke("pause " + (args[0] if args else "60")):
            return "presence: not running"
    elif cmd == "resume":
        if not poke("resume"):
            return "presence: not running"
    elif cmd == "toggle-pause":
        live = read_live()
        if not live:
            return "presence: not running (Settings > Privacy turns it on)"
        paused = live.get("paused_for", 0) > 0
        poke("resume" if paused else "pause 60")
        subprocess.run([NOTIFY, "-a", "Presence", "-i", "camera-web", "-u", "low",
                        "Presence resumed" if paused else "Presence paused for an hour",
                        "" if paused else "the camera is released; SUPER+CTRL+SHIFT+P again resumes"],
                       capture_output=True, timeout=5, check=False)
    elif cmd == "idle" and args and args[0] in ("on", "off"):
        poke("idle " + args[0])
    elif cmd == "watch":
        if not poke("watch"):
            return "presence: not running"
    elif cmd == "cameras":
        found = cameras()
        print(json.dumps(found) if "--json" in args else
              "\n".join(f"{c['dev']}  {c['name']}{'  (usb)' if c['usb'] else ''}" for c in found) or "none")
    elif cmd == "test-image" and args:
        print(json.dumps(test_images(args), indent=1))
    else:
        print(__doc__.split("\n\n")[1])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
