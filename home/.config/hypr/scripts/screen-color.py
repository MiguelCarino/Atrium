#!/usr/bin/env python3
"""Brightness and colour per screen, and the night light's warmth, as one
colour matrix (CTM) per screen.

    screen-color.py status                     JSON: every screen, what is set
    screen-color.py set <screen|all> <key> <value> [<key> <value> ...]
        brightness  20-100    %, in software (the backlight is not touched)
        warmth      1000-6500 K; 6500 is neutral, lower is warmer
        saturation  0-100     %; a colour matrix can take colour away, not add it
        red / green / blue  50-100   % gain, to make different screens match
      a value can be relative: "brightness -10"
    screen-color.py reset <screen|all>         back to neutral
    screen-color.py night <K>|off              the night light (nightlight.sh)
    screen-color.py apply                      send the matrices again (after a mode change)
    screen-color.py dim <percent>|off          dim every screen to <percent> of what it is set
                                               to, for now only (hypridle's dim listener)
    screen-color.py daemon                     holds the matrices (screen-color.service)

<screen> is a connector name (DP-1, HDMI-A-1) and is matched without case.
"all" sets every screen at once, and also the default a screen plugged in
later starts from.

Why a daemon of its own: Hyprland's hyprland-ctm-control-v1 takes one
matrix per screen and costs nothing to render (no shader pass, direct
scanout stays on), but only one client may hold it, and hyprsunset -- the
usual client -- sets the same matrix on every screen. So this replaces
hyprsunset: nightlight.sh's warmth is multiplied in here, per screen, with
whatever that screen has of its own. When the daemon stops, the compositor
resets every screen to neutral.

Speaks the Wayland wire protocol directly (python3 has no Wayland binding
here); only wl_registry, wl_output (v4, for the connector names) and the
CTM manager are used. Settings live in $XDG_STATE_HOME/hypr/screen-color.json;
the commands write it and send the daemon SIGUSR1.

`dim` is deliberately NOT in that file: it is the idle dim (hypridle.conf,
written by idle-settings.py), a multiplier over everything above that lasts
only until the next input. It lives in $XDG_RUNTIME_DIR/screen-color-dim,
which logging out empties, so a dim that never got its "dim off" (hypridle
killed mid-idle) cannot follow you into the next session or overwrite the
brightness you chose.
"""
import json
import math
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "screen-color.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
PIDFILE = os.path.join(RUNTIME, "screen-color.pid")
DIMFILE = os.path.join(RUNTIME, "screen-color-dim")
UNIT = "screen-color.service"

NEUTRAL = {"brightness": 100, "warmth": 6500, "saturation": 100, "red": 100, "green": 100, "blue": 100}
RANGES = {"brightness": (20, 100), "warmth": (1000, 6500), "saturation": (0, 100),
          "red": (50, 100), "green": (50, 100), "blue": (50, 100)}
ALIASES = {"bright": "brightness", "brillo": "brightness", "temp": "warmth", "temperature": "warmth",
           "warm": "warmth", "sat": "saturation", "r": "red", "g": "green", "b": "blue"}
LUMA = (0.2126, 0.7152, 0.0722)     # Rec. 709, what "grey" means for saturation


# --------------------------------- settings ---------------------------------

def load():
    try:
        with open(STATE) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    data.setdefault("screens", {})
    data.setdefault("night", 0)
    return data


def save(data):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def settings_for(data, name):
    """A screen's settings: neutral, then the "all" default, then its own."""
    out = dict(NEUTRAL)
    out.update(data["screens"].get("*", {}))
    out.update(data["screens"].get(name, {}))
    return out


def blackbody(k):
    t = max(1000, min(6600, k)) / 100
    r = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return tuple(max(0.0, min(255.0, c)) / 255 for c in (r, g, b))


def kelvin_rgb(k):
    """Kelvin -> RGB multipliers: the same fit (Tanner Helland's) as
    nightlight.sh's rgb_for, divided by 6500K's so that 6500 is exactly
    neutral (the raw fit leaves it a touch yellow)."""
    white = blackbody(6500)
    return tuple(min(1.0, c / w) for c, w in zip(blackbody(k), white))


def matrix(s, night):
    """Row-major 3x3: saturation first (towards the pixel's grey), then each
    channel scaled by brightness x warmth x night light x its own gain. Every
    entry stays >= 0, which the protocol requires."""
    warm = kelvin_rgb(s["warmth"])
    nl = kelvin_rgb(night) if night else (1.0, 1.0, 1.0)
    gains = [s["brightness"] / 100 * warm[i] * nl[i] * s[c] / 100
             for i, c in enumerate(("red", "green", "blue"))]
    sat = s["saturation"] / 100
    rows = []
    for i in range(3):
        rows += [gains[i] * ((1 - sat) * LUMA[j] + (sat if i == j else 0)) for j in range(3)]
    return rows


def dim_factor():
    """The idle dim as a 0.05-1.0 multiplier; 1.0 when not dimmed."""
    try:
        with open(DIMFILE) as handle:
            return max(5, min(100, int(handle.read().strip()))) / 100
    except (OSError, ValueError):
        return 1.0


# ------------------------------ wayland client ------------------------------

def u32(v):
    return struct.pack("=I", v)


def wl_string(s):
    b = s.encode() + b"\0"
    return u32(len(b)) + b + b"\0" * (-len(b) % 4)


def read_string(buf, off):
    n, = struct.unpack_from("=I", buf, off)
    s = buf[off + 4:off + 4 + n - 1].decode("utf-8", "replace")
    return s, off + 4 + n + (-n % 4)


class Client:
    def __init__(self):
        path = os.environ.get("WAYLAND_DISPLAY", "wayland-1")
        if not path.startswith("/"):
            path = os.path.join(RUNTIME, path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.buf = b""
        self.next_id = 2
        self.outputs = {}           # registry name -> {"id": object id, "name": "DP-1" or None}
        self.ctm = None
        self.blocked = False
        self.registry = self.new_id()
        self.send(1, 1, u32(self.registry))         # wl_display.get_registry

    def new_id(self):
        self.next_id += 1
        return self.next_id - 1

    def send(self, obj, opcode, payload=b""):
        self.sock.sendall(struct.pack("=II", obj, ((8 + len(payload)) << 16) | opcode) + payload)

    def bind(self, name, iface, version):
        oid = self.new_id()
        self.send(self.registry, 0, u32(name) + wl_string(iface) + u32(version) + u32(oid))
        return oid

    def read(self):
        """Handle what the compositor sent: True when a screen appeared (apply
        again), None when the connection is gone."""
        chunk = self.sock.recv(65536)
        if not chunk:
            return None
        self.buf += chunk
        changed = False
        while len(self.buf) >= 8:
            obj, word = struct.unpack_from("=II", self.buf)
            size, opcode = word >> 16, word & 0xFFFF
            if len(self.buf) < size:
                break
            body, self.buf = self.buf[8:size], self.buf[size:]
            changed |= self.event(obj, opcode, body)
        return changed

    def event(self, obj, opcode, body):
        if obj == 1 and opcode == 0:                # wl_display.error
            _, code = struct.unpack_from("=II", body)
            sys.exit(f"screen-color: wayland error {code}: {read_string(body, 8)[0]}")
        if obj == self.registry:
            name, = struct.unpack_from("=I", body)
            if opcode == 0:                         # global
                iface, off = read_string(body, 4)
                version, = struct.unpack_from("=I", body, off)
                if iface == "wl_output" and version >= 4:
                    self.outputs[name] = {"id": self.bind(name, iface, 4), "name": None}
                elif iface == "hyprland_ctm_control_manager_v1":
                    self.ctm = self.bind(name, iface, min(version, 2))
            elif opcode == 1 and name in self.outputs:     # global_remove
                self.send(self.outputs.pop(name)["id"], 0)  # wl_output.release
            return False
        if obj == self.ctm and opcode == 0:         # blocked: someone else holds it
            self.blocked = True
            return False
        for out in self.outputs.values():
            if out["id"] == obj:
                if opcode == 4:                     # name
                    out["name"] = read_string(body, 0)[0]
                return opcode == 2                  # done: apply to the new screen
        return False

    def apply(self, data):
        if not self.ctm:
            return
        done = []
        dim = dim_factor()
        for out in self.outputs.values():
            if out["name"]:
                s = settings_for(data, out["name"])
                s["brightness"] *= dim
                values = matrix(s, data.get("night", 0))
                self.send(self.ctm, 0, u32(out["id"]) +
                          b"".join(struct.pack("=i", round(v * 256)) for v in values))
                done.append(out["name"] + ("" if values == matrix(NEUTRAL, 0) else " (set)"))
        self.send(self.ctm, 1)                      # commit
        print("screen-color: applied to " + ", ".join(sorted(done)), flush=True)


def daemon():
    # hyprsunset would hold the CTM manager and block this one.
    try:
        killed = subprocess.run(["pkill", "-x", "hyprsunset"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        killed = False
    if killed:
        time.sleep(0.5)                 # let the compositor drop its hold first
    client = Client()
    reload_r, reload_w = os.pipe()
    os.set_blocking(reload_w, False)
    signal.signal(signal.SIGUSR1, lambda *_: os.write(reload_w, b"x"))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with open(PIDFILE, "w") as handle:
        handle.write(str(os.getpid()))
    try:
        while True:
            ready, _, _ = select.select([client.sock, reload_r], [], [])
            apply = False
            if reload_r in ready:
                os.read(reload_r, 64)
                apply = True
            if client.sock in ready:
                changed = client.read()
                if changed is None:
                    sys.exit("screen-color: compositor went away")
                apply |= changed
            if client.blocked:
                sys.exit("screen-color: another colour client (hyprsunset?) holds the screens")
            if apply:
                client.apply(load())
    finally:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


# --------------------------------- commands ---------------------------------

def monitors():
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=3).stdout
        return json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def poke():
    """Tell the daemon to re-read the settings, starting it if it is down."""
    try:
        with open(PIDFILE) as handle:
            os.kill(int(handle.read()), signal.SIGUSR1)
            return
    except (OSError, ValueError):
        pass
    try:
        subprocess.run(["systemctl", "--user", "start", UNIT], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass


def resolve(data, target):
    """The screen names a target means: one connector, or "all"."""
    names = [m["name"] for m in monitors()]
    if target.lower() == "all":
        return ["*"] + sorted(set(names) | (set(data["screens"]) - {"*"}))
    for name in names + list(data["screens"]):
        if name.lower() == target.lower():
            return [name]
    sys.exit(f"screen-color: no screen called {target!r} (screens: {', '.join(names)})")


def set_values(target, pairs):
    data = load()
    if len(pairs) % 2:
        sys.exit("screen-color: give <key> <value> pairs")
    names = resolve(data, target)
    for key, value in zip(pairs[::2], pairs[1::2]):
        key = ALIASES.get(key.lower(), key.lower())
        if key not in RANGES:
            sys.exit(f"screen-color: unknown setting {key!r} ({', '.join(RANGES)})")
        lo, hi = RANGES[key]
        try:
            number = int(float(value))
        except ValueError:
            sys.exit(f"screen-color: {value!r} is not a number")
        for name in names:
            now = settings_for(data, name)[key]
            new = now + number if value[0] in "+-" else number
            data["screens"].setdefault(name, {})[key] = max(lo, min(hi, new))
    for name in names:          # keep the file to what differs from neutral
        own = {k: v for k, v in data["screens"].get(name, {}).items() if v != NEUTRAL[k]}
        if own or (name != "*" and data["screens"].get("*")):
            data["screens"][name] = own
        else:
            data["screens"].pop(name, None)
    save(data)
    poke()


def set_dim(value):
    """`dim off` (or 100) removes the dim; `dim 40` shows every screen at 40 %
    of its own brightness. Only pokes the daemon when something changed, so
    hypridle's on-resume `dim off` after every idle stretch costs nothing."""
    before = dim_factor()
    if value in ("off", "100"):
        try:
            os.remove(DIMFILE)
        except OSError:
            pass
    else:
        try:
            percent = max(5, min(100, int(float(value))))
        except ValueError:
            sys.exit(f"screen-color: dim takes a percent or off, not {value!r}")
        os.makedirs(RUNTIME, exist_ok=True)
        with open(DIMFILE, "w") as handle:
            handle.write(str(percent))
    if dim_factor() != before:
        poke()


def status():
    print(json.dumps(status_data(), indent=1))


def status_data():
    """What `status` prints, as a dict (desktopctl.py imports this)."""
    data = load()
    screens = []
    for m in monitors():
        s = settings_for(data, m["name"])
        screens.append({"name": m["name"], "description": m.get("description", ""),
                        **s, "neutral": s == NEUTRAL})
    alive = False
    try:
        with open(PIDFILE) as handle:
            os.kill(int(handle.read()), 0)
            alive = True
    except (OSError, ValueError):
        pass
    return {"screens": screens, "all": settings_for(data, "*"), "night": data["night"],
            "dim": round(dim_factor() * 100), "running": alive, "ranges": RANGES}


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "daemon":
        daemon()
    elif cmd == "status":
        status()
    elif cmd == "set" and len(args) >= 4:
        set_values(args[1], args[2:])
    elif cmd == "reset" and len(args) == 2:
        data = load()
        for name in resolve(data, args[1]):
            data["screens"].pop(name, None)
        if args[1].lower() == "all":
            data["screens"] = {}
        save(data)
        poke()
    elif cmd == "apply":
        poke()
    elif cmd == "dim" and len(args) == 2:
        set_dim(args[1])
    elif cmd == "night" and len(args) == 2:
        data = load()
        data["night"] = 0 if args[1] == "off" else max(1000, min(6500, int(args[1])))
        save(data)
        poke()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
