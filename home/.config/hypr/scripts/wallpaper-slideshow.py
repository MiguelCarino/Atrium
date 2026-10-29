#!/usr/bin/env python3
"""wallpaper-slideshow -- rotate still wallpapers through hyprpaper, per monitor.

Replaces the mpvpaper video wallpapers (and wallpaper-pauser.py, which only
existed to pause them). A still image costs nothing between changes: Hyprland
redraws the background only when something on top of it moves, where a video
made it recomposite the whole output -- blur behind the translucent terminals
included -- 30 or 60 times a second.

Images
------
    ~/Pictures/Wallpapers/<OUTPUT>/      one folder per monitor, named after
                                         its connector (DP-1/, HDMI-A-1/ ...),
                                         images at that screen's size as it is
                                         SEEN -- a portrait (rotated) screen
                                         wants portrait images. `screens.py`
                                         prints each one's "pixels".
Drop images in (png, jpg, webp, jxl; symlinks are fine) and they join the
rotation at the next change -- the folder is re-read every time. A monitor
with no folder, or an empty one, is left alone (hyprpaper.conf still paints
it). hyprpaper scales each image to cover the output and centre-crops it.

Covered = paused
----------------
A monitor's slideshow only advances while its wallpaper can be seen. The
rule is wallpaper-pauser's: the output's active regular workspace has a
mapped, non-hidden window that is tiled, or fullscreen/maximized in any mode
-> covered. Empty, or only floating windows -> visible. INTERVAL counts
VISIBLE seconds only, so a covered monitor keeps its picture and picks up
the count where it left off once uncovered.

Matched set (MATCHED, the theme's wallpaper_prefix)
---------------------------------------------------
Only images whose names start with the desktop theme's prefix are used --
wallpaper_prefix= in ~/.config/themes/<name>/theme.conf ("skyline-" for
cyberpunk, rendered by make-wallpaper.py; "aero-" for aero, by
make-aero-wallpaper.py), read through ~/.config/hypr/scripts/theme.py every
time a picture is picked, so switching the theme switches the set without a
restart (theme.py then sends `next` so it happens at once, not at the next
turn). The rest stay in the folders, out of the rotation. ONLY_PREFIX is the
fallback for when no theme answers at all. With MATCHED on, the monitors
change TOGETHER: one shared clock (it runs while at least one wallpaper is
visible), one picture picked, and each monitor shows its own file of that
name -- seed 2 on all three, then seed 5 on all three. `next` (any monitor)
advances all of them. Prefix "" and MATCHED = False is the old behaviour:
every image, each monitor on its own clock.

The current image per monitor is remembered in ~/.cache/wallpaper-slideshow.json
and put back at login, so a restart does not jump back to the first image.

How it runs
-----------
Polls Hyprland's request socket (.socket.sock, what `hyprctl -j` uses) every
POLL seconds: two small JSON requests and no fork, ~0 CPU. Changing an image
is one `hyprctl hyprpaper wallpaper` call, every INTERVAL at most.

  wallpaper-slideshow.py               run (autostarted from lua/autostart.lua)
  wallpaper-slideshow.py -v            same, logging every decision to stderr
  wallpaper-slideshow.py next [OUTPUT] change now (all monitors, or one),
                                       covered or not, by signalling the daemon
  wallpaper-slideshow.py status        what each monitor shows and whether it
                                       counts as covered right now
  wallpaper-slideshow.py motion [on|off|toggle]
                                       the moving wallpaper's switch (below);
                                       prints {"video": ..., "on": ...}
  wallpaper-slideshow.py settings      everything Settings > Wallpaper shows,
                                       as JSON: the options below, the set,
                                       and per monitor its folder, how many
                                       pictures, which one it shows
  wallpaper-slideshow.py list OUTPUT   that monitor's folder as JSON (every
                                       picture, and whether it is in the set)
  wallpaper-slideshow.py show OUTPUT FILE
                                       show this picture on that monitor now
                                       (through the daemon when it runs, so its
                                       clock restarts; directly otherwise); it
                                       stays until the next change
  wallpaper-slideshow.py interval SECONDS
                                       how long a picture stays (60 .. 86400)
  wallpaper-slideshow.py auto [on|off|toggle]
                                       off = the picture only changes on
                                       `next` / `show` (and with the theme)
  wallpaper-slideshow.py shuffle [on|off|toggle]
                                       off = the pictures in name order
  wallpaper-slideshow.py lock-links    refresh the lock screen's links (below)

Options
-------
interval, auto and shuffle are kept in $XDG_STATE_HOME/hypr/wallpaper-slideshow.conf
(key=value; the commands above write it). The daemon re-reads it whenever it
changes, so a new interval counts from the next poll, no restart needed. A
missing file or key means the defaults below (INTERVAL, on, on).

Lock screen
-----------
Every picture shown is also linked at ~/.cache/wallpaper-slideshow/lock/<OUTPUT>
(a symlink, replaced each change). hyprlock.conf's "wallpaper" background
(scripts/lock-screen.py) points at those links, so the lock screen shows what
each monitor had without hyprlock.conf being rewritten every change.

Moving wallpaper
----------------
A theme may name a video (wallpaper_video= in its theme.conf: matrix has
matrix-rain.mp4, rendered by make-matrix-rain.py). While that theme is on,
the switch is on (wallpaper_motion in ~/.local/state/hypr/display.conf;
the display panel and the launcher flip it) and the monitor's folder has the
file, wallpaper-motion.py plays it in a loop on that monitor, over
hyprpaper's still (a GTK window on the background layer; NOT mpvpaper, which
cost ~830 MB of VRAM per monitor here -- wallpaper-motion.py says more). It
costs what the stills avoid -- ~1/4 of a CPU core decoding an ultrawide
screen's worth at 10 fps, and Hyprland recompositing the monitor for every frame. It KEEPS
PLAYING under windows (asked for: the rain should never freeze), so that is
the cost on every monitor all the time, with one exception:
  * gamemode (animations off) -> STOPPED: the process exits, CPU back for
                                 the game; it starts again with gamemode off;
  * locked (hyprlock running), or that monitor's screen off (DPMS) ->
                                 PAUSED (SIGUSR1; SIGUSR2 plays it again on
                                 unlock): nobody can see it, and the frozen
                                 frame comes back instantly;
  * other theme / switch off  -> stopped.
Checked every POLL seconds with the coverage above, so a change takes up to
5 s. The players are this daemon's: it stops them when it exits (SIGTERM
included), and kills a previous run's leftovers when it starts.

Single instance (flock on $XDG_RUNTIME_DIR/wallpaper-slideshow.lock; the pid is
written into it for `next`).
"""

import argparse
import atexit
import fcntl
import json
import os
import random
import re
import signal
import socket
import subprocess
import sys
import threading
import time

INTERVAL = 600.0    # s of VISIBLE time before a monitor's image changes
ONLY_PREFIX = "skyline-"  # fallback prefix when theme.py cannot be asked ("" = all)
MATCHED = True          # all monitors change together, to the same name
POLL = 5.0          # s between Hyprland checks
IPC_TIMEOUT = 1.0
WALLDIR = os.path.expanduser("~/Pictures/Wallpapers")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".jxl")
STATE = os.path.expanduser("~/.cache/wallpaper-slideshow.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LOCK = os.path.join(RUNTIME, "wallpaper-slideshow.lock")
NEXT_REQUEST = os.path.join(RUNTIME, "wallpaper-slideshow.next")
OPTIONS = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                       "hypr", "wallpaper-slideshow.conf")
LOCK_LINKS = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                          "wallpaper-slideshow", "lock")
INTERVAL_RANGE = (60, 86400)    # s: a minute .. a day
THEME_SCRIPT = os.path.expanduser("~/.config/hypr/scripts/theme-from-wallpaper.py")

VERBOSE = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import theme  # ~/.config/hypr/scripts/theme.py: wallpaper_prefix
except ImportError:
    theme = None
import screens  # noqa: E402  (scripts/screens.py: which screen is the primary)


def theme_output():
    """The output whose picture the accent of the bar & co. follows
    (theme-from-wallpaper.py; off/on from the display panel), and the
    leader of the matched set: the primary screen (screens.py). Asked each
    time, so a primary picked in Settings > Screens takes over at once."""
    return screens.primary()


def prefix():
    """The current theme's wallpaper_prefix. Asked on every pick (two small
    file reads), never cached: a theme switch must not need a restart."""
    if theme is not None:
        try:
            return theme.get("wallpaper_prefix")
        except (OSError, ValueError):
            pass
    return ONLY_PREFIX


# ------------------------------------------------------------------- options --
def load_options():
    """{"interval": seconds, "auto": bool, "shuffle": bool} from OPTIONS, the
    defaults for whatever is missing or unreadable."""
    raw = {}
    try:
        with open(OPTIONS) as f:
            for line in f:
                key, sep, value = line.partition("=")
                if sep and not key.lstrip().startswith("#"):
                    raw[key.strip()] = value.strip()
    except OSError:
        pass
    return options_from(raw)


def options_from(raw):
    try:
        interval = float(raw.get("interval", INTERVAL))
    except ValueError:
        interval = INTERVAL
    lo, hi = INTERVAL_RANGE
    return {"interval": min(max(interval, lo), hi),
            "auto": raw.get("auto", "on") != "off",
            "shuffle": raw.get("shuffle", "on") != "off"}


def save_options(opts):
    """Atomic key=value, the same shape display.conf has."""
    os.makedirs(os.path.dirname(OPTIONS), exist_ok=True)
    tmp = OPTIONS + ".tmp"
    with open(tmp, "w") as f:
        f.write("# wallpaper-slideshow.py's options (Settings > Wallpaper writes them)\n")
        f.write(f"interval={int(opts['interval'])}\n")
        f.write(f"auto={'on' if opts['auto'] else 'off'}\n")
        f.write(f"shuffle={'on' if opts['shuffle'] else 'off'}\n")
    os.replace(tmp, OPTIONS)


def switch_value(arg, current):
    """on / off / toggle -> bool; ValueError for anything else."""
    if arg == "toggle":
        return not current
    if arg in ("on", "off"):
        return arg == "on"
    raise ValueError(arg)


def next_in_order(pool, now):
    """Shuffle off: the picture after `now` in name order, wrapping round
    (the first one when `now` is not in the pool)."""
    if not pool:
        return None
    names = [os.path.basename(p) for p in pool]
    key = os.path.basename(now or "")
    if key in names:
        return pool[(names.index(key) + 1) % len(pool)]
    later = [p for p in pool if os.path.basename(p) > key] if key else []
    return later[0] if later else pool[0]


def log(msg, always=False):
    if VERBOSE or always:
        print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ Hyprland --
def hypr_dir():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        sys.exit("wallpaper-slideshow: HYPRLAND_INSTANCE_SIGNATURE is not set "
                 "(run it from inside Hyprland)")
    return os.path.join(RUNTIME, "hypr", sig)


def hypr_request(cmd):
    """One request on .socket.sock, e.g. 'j/monitors'. Returns parsed JSON."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(IPC_TIMEOUT)
    try:
        s.connect(os.path.join(hypr_dir(), ".socket.sock"))
        s.sendall(cmd.encode())
        chunks = []
        while True:  # Hyprland closes the connection after the reply
            d = s.recv(65536)
            if not d:
                break
            chunks.append(d)
    finally:
        s.close()
    return json.loads(b"".join(chunks))


def coverage():
    """{output: (covered_bool, reason)} for every enabled monitor."""
    monitors = hypr_request("j/monitors")
    clients = hypr_request("j/clients")
    out = {}
    for m in monitors:
        if m.get("disabled"):
            continue
        ws = m.get("activeWorkspace", {}).get("id")
        covering = [
            c for c in clients
            if c.get("workspace", {}).get("id") == ws
            and c.get("mapped") and not c.get("hidden")
            # tiled, or fullscreen/maximized in any mode (fullscreen > 0)
            and (not c.get("floating") or c.get("fullscreen", 0) > 0)
        ]
        if covering:
            names = ",".join(sorted({c.get("class") or "?" for c in covering}))
            out[m["name"]] = (True, f"ws {ws}: covered by {names}")
        else:
            out[m["name"]] = (False, f"ws {ws}: visible")
    return out


# ----------------------------------------------------------------- hyprpaper --
def images(output):
    d = os.path.join(WALLDIR, output)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    want = prefix()
    return [os.path.join(d, n) for n in names
            if n.lower().endswith(IMAGE_EXT) and n.startswith(want)
            and os.path.isfile(os.path.join(d, n))]


def all_images(output):
    """Every picture in the monitor's folder, in the set or not."""
    d = os.path.join(WALLDIR, output)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names
            if n.lower().endswith(IMAGE_EXT) and os.path.isfile(os.path.join(d, n))]


def outputs_known(state=None):
    """Monitors with a folder of their own, plus any the state remembers."""
    try:
        found = {n for n in os.listdir(WALLDIR) if os.path.isdir(os.path.join(WALLDIR, n))}
    except OSError:
        found = set()
    return sorted(found | set(state or {}))


def link_for_lock(output, path):
    """~/.cache/wallpaper-slideshow/lock/<output> -> path (see "Lock screen").
    Replaced atomically: hyprlock may be reading it at that moment."""
    try:
        os.makedirs(LOCK_LINKS, exist_ok=True)
        link = os.path.join(LOCK_LINKS, output)
        tmp = link + ".tmp"
        if os.path.lexists(tmp):
            os.remove(tmp)
        os.symlink(path, tmp)
        os.replace(tmp, link)
    except OSError as e:
        log(f"{output}: lock link: {e}")


def set_wallpaper(output, path):
    """True on success. hyprpaper answers 'error: ...' with exit 1 for a bad
    path, and fails the same way when it is not running yet."""
    try:
        r = subprocess.run(["hyprctl", "hyprpaper", "wallpaper",
                            f"{output},{path},cover"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"{output}: hyprctl failed ({e})", always=True)
        return False
    if r.returncode != 0:
        log(f"{output}: hyprpaper refused {path}: "
            f"{(r.stdout + r.stderr).strip()}", always=True)
        return False
    return True


RETHEME_TIMEOUT_S = 120


def reap(proc, timeout=None, name=""):
    """Wait for a child in a thread of its own (so it never lingers as a
    zombie, and never holds up the poll); past `timeout` it is killed."""
    def wait():
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log(f"{name or proc.args[0]}: still running after {timeout} s, killed", always=True)
            proc.kill()
            proc.wait()
    threading.Thread(target=wait, daemon=True).start()


def retheme():
    """Let theme-from-wallpaper.py re-pick the accent from the picture just
    shown. In the background: it reads the state file this daemon just
    wrote, does nothing while the theme is off, and must never hold up the
    next poll. Reaped by a thread (it was left a zombie for hours before)."""
    try:
        reap(subprocess.Popen([THEME_SCRIPT, "apply"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True),
             RETHEME_TIMEOUT_S, "theme-from-wallpaper.py")
    except OSError as e:
        log(f"theme: {e}")


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(current):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(current, f, indent=1)
        os.replace(tmp, STATE)
    except OSError:
        pass


# ---------------------------------------------------------- moving wallpaper --
MOTION_KEY = "wallpaper_motion"     # display.conf: "off" = stills only


def video_name():
    if theme is not None:
        try:
            return theme.get("wallpaper_video") or ""
        except (OSError, ValueError):
            pass
    return ""


def motion_on():
    return theme is None or theme.read_state().get(MOTION_KEY, "on") != "off"


def gamemode():
    """lua/gamemode.lua's own test: animations off == gamemode on."""
    try:
        return hypr_request("j/getoption animations:enabled").get("int", 1) == 0
    except (OSError, ValueError):
        return False


MOTION_PLAYER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wallpaper-motion.py")


class Motion:
    def __init__(self):
        self.procs = {}         # output -> [Popen, path]
        # Leftovers of a previous daemon (killed without cleaning up).
        # Anchored to the exact command start() runs: a loose pattern also
        # matched any shell whose command line merely mentioned the script.
        try:
            subprocess.run(["pkill", "-f", f"^{re.escape(sys.executable)} {re.escape(MOTION_PLAYER)} "],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        atexit.register(self.stop_all)

    def start(self, output, path):
        try:
            proc = subprocess.Popen([sys.executable, MOTION_PLAYER, output, path],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        except OSError as e:
            log(f"{output}: wallpaper-motion.py: {e}", always=True)
            return
        self.procs[output] = [proc, path, False]       # [Popen, video, paused]
        log(f"{output}: moving wallpaper {os.path.basename(path)}")

    def stop(self, output, why):
        proc = self.procs.pop(output, [None])[0]
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=3)        # reaped, not left a zombie
                except subprocess.TimeoutExpired:
                    pass
            log(f"{output}: moving wallpaper stopped ({why})")

    def stop_all(self):
        for output in list(self.procs):
            self.stop(output, "exit")

    def pause(self, output, paused, why):
        entry = self.procs[output]
        if entry[2] == paused:
            return
        try:
            entry[0].send_signal(signal.SIGUSR1 if paused else signal.SIGUSR2)
            entry[2] = paused
            log(f"{output}: moving wallpaper {'paused (' + why + ')' if paused else 'playing'}")
        except OSError:
            pass

    @staticmethod
    def unseen():
        """{output: why} for monitors nobody can see: all of them while
        hyprlock runs, and any whose screen is off (DPMS)."""
        try:
            mons = hypr_request("j/monitors")
        except (OSError, ValueError):
            mons = []
        try:
            locked = subprocess.run(["pidof", "hyprlock"], stdout=subprocess.DEVNULL, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            locked = False
        out = {}
        for m in mons:
            if locked:
                out[m["name"]] = "locked"
            elif not m.get("dpmsStatus", True):
                out[m["name"]] = "screen off"
        return out

    def step(self, cov):
        name = video_name()
        want = bool(name) and motion_on() and not gamemode()
        unseen = self.unseen() if self.procs else {}
        why = "gamemode" if name and motion_on() else "off"
        for output, (covered, _) in cov.items():
            path = os.path.join(WALLDIR, output, name) if name else ""
            entry = self.procs.get(output)
            if entry and (entry[0].poll() is not None or entry[1] != path):
                self.stop(output, "exited" if entry[0].poll() is not None else "new video")
                entry = None
            if not (want and os.path.isfile(path)):
                if entry:
                    self.stop(output, why)
                continue
            if not entry:
                # The first pause waits a poll: a signal this soon could beat
                # the player's handlers (it ignores them until it has them).
                self.start(output, path)
                continue
            self.pause(output, output in unseen, unseen.get(output, ""))
        for output in list(self.procs):
            if output not in cov:
                self.stop(output, "monitor gone")


# ------------------------------------------------------------------- daemon --
class Slideshow:
    def __init__(self):
        self.current = load_state()     # output -> path shown now
        self.visible_for = {}           # output -> visible seconds since change
        self.queue = {}                 # output -> shuffled paths still to show
        self.applied = set()            # outputs set since start
        self.names = []                 # MATCHED: shuffled names still to show
        self.shared_visible = 0.0       # MATCHED: the one shared clock
        self.motion = Motion()
        self.options = load_options()
        self.options_mtime = self.options_stamp()
        for output, path in self.current.items():
            if os.path.isfile(path):
                link_for_lock(output, path)

    @staticmethod
    def options_stamp():
        try:
            return os.stat(OPTIONS).st_mtime_ns
        except OSError:
            return None

    def reload_options(self):
        """Re-read OPTIONS when the file changed (one stat per poll)."""
        stamp = self.options_stamp()
        if stamp != self.options_mtime:
            self.options_mtime = stamp
            self.options = load_options()
            log(f"options: {self.options}")

    def pick(self, output):
        """Next image: walk a shuffled pass through the folder, so every image
        shows once before any repeats, and never the same one twice running."""
        pool = images(output)
        if not pool:
            return None
        if not self.options["shuffle"]:
            return next_in_order(pool, self.current.get(output))
        q = [p for p in self.queue.get(output, []) if p in pool]
        if not q:
            q = pool[:]
            random.shuffle(q)
            if len(q) > 1 and q[0] == self.current.get(output):
                q.append(q.pop(0))
        nxt = q.pop(0)
        self.queue[output] = q
        return nxt

    def show(self, output, path, why):
        if set_wallpaper(output, path):
            self.current[output] = path
            self.visible_for[output] = 0.0
            self.applied.add(output)
            save_state(self.current)
            link_for_lock(output, path)
            log(f"{output}: {os.path.basename(path)}  ({why})")
            if output == theme_output():
                retheme()
            return True
        return False

    def restore(self, output):
        """First sight of an output: put back what it showed last time, so a
        login continues the rotation instead of restarting it."""
        pool = images(output)
        if not pool:
            return
        last = self.current.get(output)
        path = last if last in pool else self.pick(output)
        self.show(output, path, "restore")

    # -- matched: every monitor on the same name -------------------------------
    def pick_name(self, outputs):
        """Next name for all monitors: a shuffled pass through the names, the
        file names of the leader's folder (theme_output(), else the first)."""
        lead = theme_output()
        leader = lead if lead in outputs else (sorted(outputs) or [None])[0]
        pool = [os.path.basename(p) for p in images(leader)] if leader else []
        if not pool:
            return None
        now = os.path.basename(self.current.get(leader, ""))
        if not self.options["shuffle"]:
            return os.path.basename(next_in_order(pool, now))
        q = [n for n in self.names if n in pool]
        if not q:
            q = pool[:]
            random.shuffle(q)
            if len(q) > 1 and q[0] == now:
                q.append(q.pop(0))
        self.names = q[1:]
        return q[0]

    def show_name(self, outputs, name, why):
        for output in outputs:
            path = os.path.join(WALLDIR, output, name)
            if not os.path.isfile(path):
                path = self.pick(output)        # that monitor has no such file
            if path and path != self.current.get(output):
                self.show(output, path, why)
            elif path:
                self.applied.add(output)
        self.shared_visible = 0.0

    def step_matched(self, dt, forced, cov):
        outputs = list(cov)
        new = [o for o in outputs if o not in self.applied]
        if new or forced is not None:
            lead = theme_output()
            leader = lead if lead in outputs else sorted(outputs)[0]
            name = os.path.basename(self.current.get(leader, ""))
            # Keep what the leader shows if it still belongs to the set (a login
            # carries on); otherwise -- or on `next` -- a new name for everyone.
            if forced is not None or not name.startswith(prefix()) or \
                    name not in [os.path.basename(p) for p in images(leader)]:
                name = self.pick_name(outputs)
            if name:
                # All of them: show_name skips a monitor already on that file.
                self.show_name(outputs, name, "next" if forced is not None else "restore")
            return
        if not self.options["auto"]:
            return
        if any(not covered for covered, _ in cov.values()):
            self.shared_visible += dt
        if self.shared_visible >= self.options["interval"]:
            name = self.pick_name(outputs)
            if name:
                self.show_name(outputs, name, "matched")

    def choose(self, request, cov):
        """`show OUTPUT FILE`: that picture on that monitor, and its clock (the
        shared one with MATCHED) starts again, so it gets a full turn."""
        _, output, path = (request.split("\t") + ["", ""])[:3]
        if output not in cov or not os.path.isfile(path):
            log(f"show: {output} {path}: no such monitor or file", always=True)
            return
        if self.show(output, path, "chosen"):
            self.shared_visible = 0.0

    def step(self, dt, forced):
        try:
            cov = coverage()
        except (OSError, ValueError) as e:
            log(f"hyprland query failed ({e})")
            return
        self.reload_options()
        self.motion.step(cov)
        if forced is not None and forced.startswith("show\t"):
            self.choose(forced, cov)
            forced, dt = None, 0.0
        if MATCHED:
            self.step_matched(dt, forced, cov)
            for output in list(self.applied):
                if output not in cov:
                    self.applied.discard(output)
            return
        for output, (covered, reason) in cov.items():
            if output not in self.applied:
                self.restore(output)
                continue
            if forced is not None and (forced == "" or forced == output):
                path = self.pick(output)
                if path:
                    self.show(output, path, "next")
                continue
            if covered or not self.options["auto"]:
                continue
            self.visible_for[output] = self.visible_for.get(output, 0.0) + dt
            if self.visible_for[output] >= self.options["interval"]:
                path = self.pick(output)
                if path and path != self.current.get(output):
                    self.show(output, path, reason)
                else:
                    self.visible_for[output] = 0.0
        # Unplugged monitors: forget them, so a replug restores.
        for output in list(self.applied):
            if output not in cov:
                self.applied.discard(output)

    def run(self):
        forced = []

        def on_next(_signum, _frame):
            try:
                with open(NEXT_REQUEST) as f:
                    forced.append(f.read().strip())
                os.remove(NEXT_REQUEST)
            except OSError:
                forced.append("")
        signal.signal(signal.SIGUSR1, on_next)
        # A plain exit on SIGTERM, so atexit stops the mpvpapers (the default
        # SIGTERM skips it and left them playing with no daemon).
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

        last = time.monotonic()
        while True:
            if not os.path.isdir(hypr_dir()):
                log("Hyprland instance is gone; exiting", always=True)
                return
            now = time.monotonic()
            # Cap dt: after a suspend, monotonic jumps by the sleep time, and
            # that was not time anyone spent looking at the wallpaper.
            dt = min(now - last, POLL * 2)
            last = now
            self.step(dt, forced.pop(0) if forced else None)
            while forced:   # several `next` in one poll: apply them all
                self.step(0.0, forced.pop(0))
            # A `next` signal does not cut this short (the handler returns, so
            # Python resumes the sleep); it is picked up within POLL seconds.
            time.sleep(POLL)


def take_lock():
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


def daemon_pid():
    try:
        with open(LOCK) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def settings_json():
    """`settings`: the page's whole view in one answer. The coverage needs
    Hyprland; without it every monitor is simply "unknown"."""
    state = load_state()
    try:
        cov = coverage()
    except (OSError, ValueError, SystemExit):
        cov = {}
    outputs = {}
    for output in sorted(set(outputs_known(state)) | set(cov)):
        every = all_images(output)
        current = state.get(output, "")
        outputs[output] = {
            "folder": os.path.join(WALLDIR, output),
            "exists": os.path.isdir(os.path.join(WALLDIR, output)),
            "pictures": len(every),
            "in_set": len(images(output)),
            "current": current if current and os.path.exists(current) else "",
            "connected": output in cov,
            "covered": cov[output][0] if output in cov else None,
        }
    return {**load_options(), "prefix": prefix(), "matched": MATCHED, "theme_output": theme_output(),
            "daemon": daemon_pid(), "folder": WALLDIR, "options_file": OPTIONS,
            "lock_links": LOCK_LINKS, "outputs": outputs,
            "interval_range": list(INTERVAL_RANGE)}


def cli_options(args):
    """The commands Settings > Wallpaper uses. Returns an exit status (or
    the message sys.exit prints)."""
    if args.command == "settings":
        print(json.dumps(settings_json()))
        return 0
    if args.command == "list":
        if not args.output:
            return f"list: which monitor? (e.g. {theme_output() or 'DP-1'})"
        want = prefix()
        print(json.dumps([{"path": p, "name": os.path.basename(p),
                           "in_set": os.path.basename(p).startswith(want)} for p in all_images(args.output)]))
        return 0
    if args.command == "lock-links":
        for output, path in load_state().items():
            if os.path.isfile(path):
                link_for_lock(output, path)
        print(LOCK_LINKS)
        return 0
    if args.command == "show":
        path = os.path.abspath(os.path.expanduser(args.file))
        if not args.output or not args.file:
            return "show: OUTPUT FILE"
        if not os.path.isfile(path):
            return f"show: no such file: {args.file}"
        if any(c in path for c in "\t\n"):
            return "show: a file name with a tab or a line break cannot be passed on"
        try:
            connected = set(coverage())
        except (OSError, ValueError, SystemExit):
            connected = None            # no Hyprland answer: let hyprpaper say
        if connected is not None and args.output not in connected:
            # The daemon (and hyprpaper) would drop it without a word.
            return f"show: {args.output} is not connected now"
        pid = daemon_pid()
        if pid:
            with open(NEXT_REQUEST, "w") as f:
                f.write(f"show\t{args.output}\t{path}")
            os.kill(pid, signal.SIGUSR1)
            return 0
        # No daemon: do what its show() does, minus the clock.
        if not set_wallpaper(args.output, path):
            return f"show: hyprpaper did not take {path}"
        state = load_state()
        state[args.output] = path
        save_state(state)
        link_for_lock(args.output, path)
        return 0
    opts = load_options()
    try:
        if args.command == "interval":
            if args.output:
                lo, hi = INTERVAL_RANGE
                value = float(args.output)
                if not lo <= value <= hi:
                    return f"interval: {lo} .. {hi} seconds"
                opts["interval"] = value
        elif args.output:
            opts[args.command] = switch_value(args.output, opts[args.command])
    except ValueError:
        return f"{args.command}: " + ("a number of seconds" if args.command == "interval" else "on, off or toggle")
    if args.output:
        save_options(opts)
    print(json.dumps(opts))
    return 0


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description="Rotate still wallpapers per monitor.")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every change")
    ap.add_argument("command", nargs="?", default="run",
                    choices=("run", "next", "status", "motion", "settings", "list", "show",
                             "interval", "auto", "shuffle", "lock-links"))
    ap.add_argument("output", nargs="?", default="",
                    help="with next: only this monitor; with motion/auto/shuffle: on, off or toggle; "
                         "with list/show: the monitor; with interval: seconds")
    ap.add_argument("file", nargs="?", default="", help="with show: the picture")
    args = ap.parse_args()
    VERBOSE = args.verbose

    if args.command in ("settings", "list", "show", "interval", "auto", "shuffle", "lock-links"):
        sys.exit(cli_options(args))

    if args.command == "status":
        state = load_state()
        for output, (covered, reason) in coverage().items():
            n = len(images(output))
            shown = os.path.basename(state.get(output, "")) or "-"
            print(f"{output:10} {'PAUSED' if covered else 'RUNS':6} {reason:40} "
                  f"{n} images, showing {shown}")
        print("daemon:", daemon_pid() or "not running")
        print("moving wallpaper:", video_name() or "none in this theme",
              "| switch", "on" if motion_on() else "off", "| gamemode" if gamemode() else "")
        return

    if args.command == "motion":
        if args.output in ("on", "off", "toggle"):
            if theme is None:
                sys.exit("wallpaper-slideshow: theme.py is not importable")
            want = args.output if args.output != "toggle" else ("off" if motion_on() else "on")
            state = theme.read_state()
            state[MOTION_KEY] = want
            theme.write_state(state)
        elif args.output:
            sys.exit("motion: on, off or toggle")
        print(json.dumps({"video": video_name(), "on": motion_on()}))
        return

    if args.command == "next":
        pid = daemon_pid()
        if not pid:
            sys.exit("wallpaper-slideshow: daemon is not running")
        with open(NEXT_REQUEST, "w") as f:
            f.write(args.output)
        os.kill(pid, signal.SIGUSR1)
        return

    lock = take_lock()
    if lock is None:
        log("another wallpaper-slideshow is already running; exiting")
        return
    Slideshow().run()


if __name__ == "__main__":
    main()
