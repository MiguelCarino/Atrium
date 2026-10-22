#!/usr/bin/env python3
"""Do Not Disturb on by itself while a Steam game is open, while the screen
is being shared and during the quiet hours, and off again when none of them
is (auto-dnd.service).

Follows Hyprland's event socket: openwindow / closewindow re-count the
steam_app_* windows (the class the gamemode hooks in lua/gamemode.lua key on),
screencast>>1 / >>0 is a portal share starting / ending (a call, OBS through
the portal; not record.sh, which captures without the portal). The quiet
hours are a clock: the loop wakes at their next edge.

Which of the three count is yours to say: dnd_games, dnd_share and quiet
(with quiet_from / quiet_to / quiet_days) in
$XDG_STATE_HOME/hypr/notifications.json, which notify-settings.py owns --
Settings > Notifications, or `notify-settings.py set dnd_games off`. It is
read again on every wake-up; notify-settings.py sends SIGUSR1 after a change
so the wake-up is immediate. A reason switched off while it holds DND on
counts as over: DND goes off as if the game had closed.

It never fights you or a focus round (timers.py):
  * DND already on when a reason starts -> left alone, and left on after.
  * it turned DND on and you turn it off -> stays off until every reason is
    over and a new one starts.
  * the reasons end while a focus round runs -> DND stays on; the round
    ends it as usual.
The last game window closing waits RELEASE_S first: games that go launcher
window -> game window close one just before mapping the next.

What it is doing is written to $XDG_RUNTIME_DIR/auto-dnd.json (ours, declined,
reasons) each time it changes, so the Settings page can say "on by itself,
for the quiet hours" instead of only "on".
"""
import datetime
import importlib.util
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timers  # noqa: E402  (no GTK: the focus round's state)


def _load_settings_module():
    spec = importlib.util.spec_from_file_location("notify_settings", os.path.join(HERE, "notify-settings.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


settings = _load_settings_module()   # the switches and the quiet hours (no GTK, no side effects)

MODE = "do-not-disturb"
RELEASE_S = 3
RESCAN_S = 30           # a Proton game can set its class after mapping: no event for that
SIGNAL = 14             # waybar's notification bell (notifications.py)


def makoctl(*args):
    try:
        return subprocess.run(["makoctl", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def dnd_on():
    return MODE in makoctl("mode").split()


def set_dnd(on, why):
    makoctl("mode", "-a" if on else "-r", MODE)
    subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar"])
    print(f"auto-dnd: {'on' if on else 'off'} ({why})", flush=True)


def games():
    try:
        out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=3).stdout
        return sum(1 for c in json.loads(out or "[]") if c.get("class", "").startswith("steam_app_"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def focus_running():
    return any(t.get("kind") == "focus" for t in timers.load()["timers"])


def socket_path():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "hypr")
    if not sig:
        try:
            sig = sorted(os.listdir(base))[-1]
        except (OSError, IndexError):
            return None
    return os.path.join(base, sig, ".socket2.sock")


class Watch:
    """The three reasons, what this has done about them, and when to let go.
    The facts (a game window, a share, the clock) are kept apart from the
    switches (self.conf), so turning a switch back on picks up a game that
    is still running."""

    def __init__(self, conf=None):
        self.conf = conf or settings.load()
        self.game = games() > 0
        self.sharing = False
        self.quiet = settings.quiet_now(self.conf, datetime.datetime.now())
        self.ours = False           # DND is on because this turned it on
        self.declined = False       # you turned that off: wait for the reasons to end
        self.release_at = None      # when to let go, after the reasons ended
        self.reported = None

    def reasons(self):
        return " and ".join(r for r, on in (("game", self.game and self.conf["dnd_games"]),
                                            ("screen share", self.sharing and self.conf["dnd_share"]),
                                            ("quiet hours", self.quiet)) if on)

    def reload(self, now=None):
        """The settings and the clock again (each wake-up, and on SIGUSR1)."""
        self.conf = settings.load()
        self.tick(now)

    def tick(self, now=None):
        self.quiet = settings.quiet_now(self.conf, now or datetime.datetime.now())
        self.update()

    def until_change(self, now=None):
        """Seconds to the next edge of the quiet hours (None: no edge)."""
        now = now or datetime.datetime.now()
        at = settings.next_change(self.conf, now)
        return None if at is None else max(0.0, (at - now).total_seconds())

    def update(self):
        why = self.reasons()
        if why:
            self.release_at = None
            if not self.ours and not dnd_on() and not self.declined:
                set_dnd(True, why)
                # Only if it took: with mako not up yet (login) or
                # restarting, "ours" with DND off would read as you turning
                # it off, and it would stay off for the whole night. Not
                # ours, it simply tries again on the next wake-up.
                self.ours = dnd_on()
            elif self.ours and not dnd_on():
                self.ours, self.declined = False, True     # you turned it off: respected
        else:
            self.declined = False
            if self.ours and self.release_at is None:
                self.release_at = time.monotonic() + RELEASE_S
        self.report()

    def release(self):
        self.release_at = None
        if self.ours:
            self.ours = False
            if dnd_on() and not focus_running():
                set_dnd(False, "reasons over")
        self.report()

    def report(self):
        """$XDG_RUNTIME_DIR/auto-dnd.json, when what it says has changed."""
        state = {"ours": self.ours, "declined": self.declined, "reasons": self.reasons()}
        if state == self.reported:
            return
        self.reported = state
        try:
            tmp = settings.AUTO_STATE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(state, fh)
            os.replace(tmp, settings.AUTO_STATE)
        except OSError:
            pass

    def event(self, line):
        name, _, data = line.partition(">>")
        if name in ("openwindow", "closewindow"):
            self.game = games() > 0
        elif name == "screencast":
            self.sharing = data.split(",")[0] == "1"
        else:
            return
        self.update()


def main():
    # SIGUSR1 from notify-settings.py: the settings changed. The handler does
    # nothing itself; set_wakeup_fd writes a byte to `wake`, which the select
    # below watches like the event socket. Installed first, so a signal can
    # never arrive while SIGUSR1 still has its default action (exit).
    wake_r, wake_w = socket.socketpair()
    wake_r.setblocking(False)
    wake_w.setblocking(False)
    signal.signal(signal.SIGUSR1, lambda *_: None)
    signal.set_wakeup_fd(wake_w.fileno())
    path = socket_path()
    if not path:
        sys.exit("auto-dnd: cannot locate Hyprland's event socket")
    watch = Watch()
    watch.update()
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
                now = time.monotonic()
                edge = watch.until_change()
                wait = min(rescan, watch.release_at or rescan, now + edge + 1 if edge is not None else rescan) - now
                ready, _, _ = select.select([sock, wake_r], [], [], max(0.0, wait))
                if wake_r in ready:
                    try:
                        while wake_r.recv(64):
                            pass
                    except BlockingIOError:
                        pass
                    watch.reload()
                if sock in ready:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break           # Hyprland restarted: reconnect
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        watch.event(line.decode("utf-8", "replace"))
                now = time.monotonic()
                if watch.release_at and now >= watch.release_at:
                    if watch.reasons():
                        watch.release_at = None
                    else:
                        watch.release()
                if now >= rescan or not ready:      # the 30 s rescan, or a timed wake-up
                    rescan = now + RESCAN_S
                    watch.game = games() > 0
                    watch.reload()


if __name__ == "__main__":
    main()
