#!/usr/bin/env python3
"""Per-game settings: each Steam game remembers its own screen, refresh
rates, HDR, volume and screen brightness / warmth, and gets them back each
time it starts (game-profiles.service).

    game-profiles.py               watch (the service)
    game-profiles.py save [appid]  keep the settings in effect now as the
                                   running game's profile (or appid's)
    game-profiles.py forget <appid>
    game-profiles.py list          JSON: every profile
    game-profiles.py status        JSON: the game running now, its profile

A profile holds what `save` saw, all of it optional:
    name         the game's name (Steam's appmanifest, else the window title)
    monitor      the screen its window goes to (a connector name, "DP-1")
    rates        {screen: Hz}           display.py rate
    hdr          on | off               display.py hdr <the HDR screen> --
                                        hdr_output(): the primary if it has
                                        HDR, else the first that has
    volume       0-100, the default output (wpctl)
    screens      {screen: {brightness, warmth}}   screen-color.py

The first window of steam_app_<id> applies the profile, after taking a
snapshot of the same settings as they were; the last window of that game
closing puts back what the profile changed, and only that. Do Not Disturb is
auto-dnd.py's, gamemode is lua/gamemode.lua's -- neither is touched here.
Profiles: $XDG_STATE_HOME/hypr/game-profiles.json; the snapshot of a game
still running: game-profiles-active.json beside it (so a restart of the
service, or of the session mid-game, still restores).
"""
import json
import os
import re
import select
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
PROFILES = os.path.join(STATE_DIR, "game-profiles.json")
ACTIVE = os.path.join(STATE_DIR, "game-profiles-active.json")
DISPLAY = os.path.join(HERE, "display.py")
SCREEN_COLOR = os.path.join(HERE, "screen-color.py")
STEAMAPPS = [os.path.expanduser(p) for p in ("~/.local/share/Steam/steamapps", "~/.steam/steam/steamapps",
                                            "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps")]
APPLY_DELAY_S = 1.5     # a game maps its window, then often moves / resizes it: let it settle
RESCAN_S = 30           # Proton can set the class after mapping: no event for that
CLASS = re.compile(r"steam_app_(\d+)$")

sys.path.insert(0, HERE)
import screens  # noqa: E402  (scripts/screens.py: the primary, the HDR screens)


def hdr_output():
    """The screen a profile's "hdr" is about -- what `display.py hdr auto`
    picks: the primary when it can do HDR, else the first screen that can
    (the host file's M.hdr_capable). None on a machine with no HDR screen:
    profiles then never hold or touch "hdr"."""
    capable = screens.hdr_capable()
    if not capable:
        return None
    p = screens.primary()
    return p if p in capable else capable[0]


# -- small helpers -------------------------------------------------------------
def run(*cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=dict(os.environ, DISPLAY_QUIET="1")).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def load(path, default):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)


def notify(title, body=""):
    subprocess.run(["notify-send", "-a", "Game profiles", "-u", "low", "-t", "3000",
                    "-h", "string:x-canonical-private-synchronous:game-profiles", title, body],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def clients():
    try:
        return json.loads(run("hyprctl", "clients", "-j", timeout=3) or "[]")
    except ValueError:
        return []


def monitors():
    try:
        return json.loads(run("hyprctl", "monitors", "-j", timeout=3) or "[]")
    except ValueError:
        return []


def games():
    """{appid: [client, ...]} of every steam_app_* window open now."""
    out = {}
    for c in clients():
        m = CLASS.match(c.get("class", ""))
        if m:
            out.setdefault(m[1], []).append(c)
    return out


def game_name(appid, windows=()):
    for folder in STEAMAPPS:
        try:
            with open(os.path.join(folder, f"appmanifest_{appid}.acf"), errors="replace") as handle:
                m = re.search(r'"name"\s+"([^"]+)"', handle.read())
                if m:
                    return m[1]
        except OSError:
            continue
    title = next((w.get("title") for w in windows if w.get("title")), "")
    return title or f"steam_app_{appid}"


# -- the settings a profile can hold -------------------------------------------
def display_status():
    try:
        return {o["name"]: o for o in json.loads(run(DISPLAY, "status"))["outputs"]}
    except (ValueError, KeyError):
        return {}


def screen_status():
    try:
        return {s["name"]: s for s in json.loads(run(SCREEN_COLOR, "status"))["screens"]}
    except (ValueError, KeyError):
        return {}


def volume():
    m = re.search(r"Volume: ([\d.]+)", run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"))
    return round(float(m[1]) * 100) if m else None


def live(game_monitor=None):
    """The settings in effect now, in a profile's shape."""
    outputs = display_status()
    out = {"rates": {n: o["rate"] for n, o in outputs.items()},
           "screens": {n: {"brightness": s["brightness"], "warmth": s["warmth"]}
                       for n, s in screen_status().items()}}
    hdr_out = hdr_output()
    if hdr_out in outputs:
        out["hdr"] = "on" if outputs[hdr_out]["hdr_wanted"] else "off"
    vol = volume()
    if vol is not None:
        out["volume"] = vol
    if game_monitor:
        out["monitor"] = game_monitor
    return out


def same_rate(a, b):
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return False


def apply(settings, windows=(), now=None):
    """Make `settings` (a profile, or a snapshot to restore) live; returns
    the keys that really changed, as a profile-shaped dict."""
    now = now if now is not None else live()
    changed = {}
    for screen, hz in settings.get("rates", {}).items():
        if not same_rate(now.get("rates", {}).get(screen), hz):
            run(DISPLAY, "rate", screen, str(hz))
            changed.setdefault("rates", {})[screen] = hz
    hdr = settings.get("hdr")
    if hdr in ("on", "off") and hdr != now.get("hdr") and hdr_output():
        run(DISPLAY, "hdr", hdr_output(), hdr)
        changed["hdr"] = hdr
    vol = settings.get("volume")
    if vol is not None and vol != now.get("volume"):
        run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(100, vol)) / 100:.2f}")
        changed["volume"] = vol
    for screen, values in settings.get("screens", {}).items():
        have = now.get("screens", {}).get(screen, {})
        diff = {k: v for k, v in values.items() if have.get(k) != v}
        if diff:
            run(SCREEN_COLOR, "set", screen, *[str(x) for kv in diff.items() for x in kv])
            changed.setdefault("screens", {})[screen] = diff
    mon = settings.get("monitor")
    if mon:
        for w in windows:
            if w.get("monitor") is not None and monitor_name(w["monitor"]) != mon:
                run("hyprctl", "eval", f'hl.dispatch(hl.dsp.window.move({{ monitor = "{mon}", '
                                       f'follow = false, window = "address:{w["address"]}" }}))')
                changed["monitor"] = mon
    return changed


def monitor_name(mid):
    return next((m["name"] for m in monitors() if m.get("id") == mid), None)


def snapshot_for(changed, before):
    """Of the `before` settings, the parts `changed` touched: what to put
    back. The monitor is not put back -- the game's window is gone."""
    snap = {}
    for screen in changed.get("rates", {}):
        if screen in before.get("rates", {}):
            snap.setdefault("rates", {})[screen] = before["rates"][screen]
    for key in ("hdr", "volume"):
        if key in changed and key in before:
            snap[key] = before[key]
    for screen, diff in changed.get("screens", {}).items():
        old = before.get("screens", {}).get(screen, {})
        vals = {k: old[k] for k in diff if k in old}
        if vals:
            snap.setdefault("screens", {})[screen] = vals
    return snap


# -- the watcher ---------------------------------------------------------------
class Watch:
    def __init__(self):
        self.active = load(ACTIVE, {})        # appid -> {"name", "restore"}
        self.pending = {}                     # appid -> when to apply

    def sync(self):
        """Compare the games open now with the ones handled."""
        open_now = games()
        for appid in open_now:
            if appid not in self.active and appid not in self.pending:
                self.pending[appid] = time.monotonic() + APPLY_DELAY_S
        for appid in list(self.pending):
            if appid not in open_now:
                del self.pending[appid]
        for appid in list(self.active):
            if appid not in open_now:
                self.closed(appid)
        return open_now

    def due(self):
        now = time.monotonic()
        ready = [a for a, at in self.pending.items() if at <= now]
        if ready:
            open_now = games()
            for appid in ready:
                del self.pending[appid]
                if appid in open_now:
                    self.opened(appid, open_now[appid])

    def opened(self, appid, windows):
        profile = load(PROFILES, {}).get(appid)
        name = (profile or {}).get("name") or game_name(appid, windows)
        if not profile:
            self.active[appid] = {"name": name, "restore": {}}
            save(ACTIVE, self.active)
            return
        before = live()
        changed = apply(profile, windows, before)
        self.active[appid] = {"name": name, "restore": snapshot_for(changed, before)}
        save(ACTIVE, self.active)
        if changed:
            notify(f"Game profile: {name}", describe(changed))
        print(f"game-profiles: {appid} opened, applied {changed}", flush=True)

    def closed(self, appid):
        entry = self.active.pop(appid)
        save(ACTIVE, self.active)
        restore = entry.get("restore") or {}
        if restore:
            apply(restore)
            notify(f"{entry.get('name', appid)} closed", "settings put back")
        print(f"game-profiles: {appid} closed, restored {restore}", flush=True)

    def timeout(self):
        if self.pending:
            return max(0.0, min(self.pending.values()) - time.monotonic())
        return RESCAN_S


def describe(settings):
    parts = []
    if "monitor" in settings:
        parts.append(f"on {settings['monitor']}")
    parts += [f"{s} {float(hz):g} Hz" for s, hz in settings.get("rates", {}).items()]
    if "hdr" in settings:
        parts.append(f"HDR {settings['hdr']}")
    if "volume" in settings:
        parts.append(f"volume {settings['volume']}%")
    for s, vals in settings.get("screens", {}).items():
        parts.append(f"{s} " + ", ".join(f"{k} {v}" for k, v in vals.items()))
    return " · ".join(parts)


def socket_path():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "hypr")
    if not sig:
        try:
            sig = sorted(os.listdir(base))[-1]
        except (OSError, IndexError):
            return None
    return os.path.join(base, sig, ".socket2.sock")


def watch():
    path = socket_path()
    if not path:
        sys.exit("game-profiles: cannot locate Hyprland's event socket")
    w = Watch()
    w.sync()
    while True:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
        except OSError:
            time.sleep(2)
            continue
        buf, rescan = b"", time.monotonic() + RESCAN_S
        with sock:
            while True:
                ready, _, _ = select.select([sock], [], [], min(w.timeout(), max(0.0, rescan - time.monotonic())))
                if ready:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break           # Hyprland restarted: reconnect
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    if any(l.startswith((b"openwindow>>", b"closewindow>>", b"windowtitle")) for l in lines):
                        w.sync()
                w.due()
                if time.monotonic() >= rescan:
                    rescan = time.monotonic() + RESCAN_S
                    w.sync()


# -- commands ------------------------------------------------------------------
def cmd_save(appid=None):
    open_now = games()
    if appid is None:
        if not open_now:
            sys.exit("game-profiles: no game is running -- give an appid")
        appid = next(iter(open_now))
    windows = open_now.get(appid, [])
    mon = monitor_name(windows[0]["monitor"]) if windows else None
    profile = live(mon)
    profile["name"] = game_name(appid, windows)
    profiles = load(PROFILES, {})
    profiles[appid] = profile
    save(PROFILES, profiles)
    # Saved mid-game: what is live now IS the profile, so closing the game
    # must still put back what was there before it started (kept as is).
    notify(f"Saved for {profile['name']}", describe(profile))
    print(json.dumps({appid: profile}, indent=1))


def main(argv):
    cmd = argv[0] if argv else "watch"
    if cmd == "watch":
        watch()
    elif cmd == "save" and len(argv) <= 2:
        cmd_save(argv[1] if len(argv) == 2 else None)
    elif cmd == "forget" and len(argv) == 2:
        profiles = load(PROFILES, {})
        if profiles.pop(argv[1], None) is None:
            sys.exit(f"game-profiles: no profile for {argv[1]}")
        save(PROFILES, profiles)
    elif cmd == "list":
        print(json.dumps(load(PROFILES, {}), indent=1))
    elif cmd == "status":
        open_now = games()
        profiles = load(PROFILES, {})
        print(json.dumps({"running": {a: {"name": game_name(a, ws), "profile": profiles.get(a)}
                                      for a, ws in open_now.items()},
                          "active": load(ACTIVE, {})}, indent=1))
    else:
        sys.exit(__doc__.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
