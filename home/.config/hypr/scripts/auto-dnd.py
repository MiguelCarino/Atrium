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

A screen share counts only once it has lasted SHARE_ENGAGE_S, and stays
counted for SHARE_GRACE_S after it ends (ShareDebounce). Hyprland reports
every screencopy client as a share -- a one-row grim, a colour picker, a
thumbnail -- and those last well under a second; without this, one every
30 s turned DND on and off ~1,600 times a night (and mako's mode switching
with it). Who held the share is logged once per share (share_owner), and a
summary of the ignored blips once an hour. On top of that, DND is never
turned back on within MIN_TOGGLE_S of this turning it off: whatever the
reasons do, mako sees at most one change per that many seconds.

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
import hyprbus  # noqa: E402  (Hyprland's events: the shared relay, or socket2 directly)


def _load_settings_module():
    spec = importlib.util.spec_from_file_location("notify_settings", os.path.join(HERE, "notify-settings.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


settings = _load_settings_module()   # the switches and the quiet hours (no GTK, no side effects)

MODE = "do-not-disturb"
RELEASE_S = 3
SHARE_ENGAGE_S = 10     # a share must last this long to count (screencopy blips do not)
SHARE_GRACE_S = 20      # ...and stays counted this long after it ends (a call re-sharing)
MIN_TOGGLE_S = 30       # never back on within this long of turning it off
BLIP_REPORT_S = 3600    # the "ignored N short shares" summary, at most this often
# Screen capture tools a share can be told apart by (the process names);
# a portal share (a call, OBS) shows up as the portal itself.
CAPTURE_TOOLS = ("grim", "wf-recorder", "wl-screenrec", "gpu-screen-recorder", "obs",
                 "kooha", "hyprpicker", "wayvnc", "xdg-desktop-portal-hyprland")
RESCAN_S = 30           # a Proton game can set its class after mapping: no event for that


def makoctl(*args):
    try:
        return subprocess.run(["makoctl", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def dnd_on():
    return MODE in makoctl("mode").split()


def bell():
    """Redraw the bar's notification bell (bar_signals.py "notifications")."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import bar_signals
        return bar_signals.poke("notifications")
    except Exception:       # noqa: BLE001 - no bar: nothing to redraw
        return 0


def set_dnd(on, why):
    makoctl("mode", "-a" if on else "-r", MODE)
    bell()
    print(f"auto-dnd: {'on' if on else 'off'} ({why})", flush=True)


def games():
    try:
        out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=3).stdout
        return sum(1 for c in json.loads(out or "[]") if c.get("class", "").startswith("steam_app_"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _proc_name(pid):
    """A process' command line, shortened: "grim -g ..." (or its comm)."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
    except OSError:
        return ""
    if not argv:
        return ""
    # python3 /path/island.py -> island.py: the script is the name worth reading
    if os.path.basename(argv[0]).startswith("python") and len(argv) > 1:
        argv = argv[1:]
    return " ".join([os.path.basename(argv[0])] + argv[1:3])[:80]


def _ppid(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return int(fh.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def share_owner(proc="/proc"):
    """Who is capturing the screen right now, best guess: the capture tools
    running, each with the process that started it ("grim (from island.py)").
    "" when none is found (it was too quick, or something else holds it)."""
    found = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return ""
    for pid in pids:
        try:
            with open(f"{proc}/{pid}/comm") as fh:
                comm = fh.read().strip()
        except OSError:
            continue
        if comm in CAPTURE_TOOLS or comm.startswith("obs"):
            parent = _proc_name(_ppid(pid))
            found.append(f"{comm} (from {parent})" if parent else comm)
    return ", ".join(sorted(set(found)))


class ShareDebounce:
    """A screen share with hysteresis: `active` turns on only once a share
    has run engage_s, and off grace_s after the last one ended (a new one
    within the grace keeps it on). Pure: every call takes `now` (monotonic
    seconds), so the tests drive the clock.

    event(on, now) for each screencast>>1 / >>0, poll(now) at the deadline()
    it asks for; both say True when `active` changed. A share that ended
    before engage_s is a blip: counted (self.blips), never active."""

    def __init__(self, engage_s=SHARE_ENGAGE_S, grace_s=SHARE_GRACE_S):
        self.engage_s, self.grace_s = engage_s, grace_s
        self.raw = False            # Hyprland says a share runs
        self.since = None           # when the current share started
        self.off_at = None          # active, the share over: when to let go
        self.active = False
        self.blips = 0

    def event(self, on, now):
        if on and not self.raw:
            self.raw, self.since, self.off_at = True, now, None
        elif not on and self.raw:
            self.raw = False
            if self.active:
                self.off_at = now + self.grace_s
            else:
                self.since = None
                self.blips += 1
        return self.poll(now)

    def poll(self, now):
        if self.raw and not self.active and now - self.since >= self.engage_s:
            self.active = True
            return True
        if self.active and not self.raw and self.off_at is not None and now >= self.off_at:
            self.active, self.off_at, self.since = False, None, None
            return True
        return False

    def deadline(self):
        """The next moment poll() could change something (None: no timer)."""
        if self.raw and not self.active:
            return self.since + self.engage_s
        if self.active and not self.raw:
            return self.off_at
        return None


class ToggleLimiter:
    """At most one DND change per min_s seconds in the direction that
    flaps: back on soon after this turned it off. Pure, like ShareDebounce."""

    def __init__(self, min_s=MIN_TOGGLE_S):
        self.min_s = min_s
        self.last_off = None

    def may_turn_on(self, now):
        return self.last_off is None or now - self.last_off >= self.min_s

    def turned_off(self, now):
        self.last_off = now

    def on_after(self):
        """When turning on is allowed again (None: it is)."""
        return None if self.last_off is None else self.last_off + self.min_s


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
        self.share = ShareDebounce()
        self.limiter = ToggleLimiter()
        self.retry_at = None        # turning on waits for the limiter until then
        self.blip_report_at = time.monotonic() + BLIP_REPORT_S
        self.quiet = settings.quiet_now(self.conf, datetime.datetime.now())
        self.ours = False           # DND is on because this turned it on
        self.declined = False       # you turned that off: wait for the reasons to end
        self.release_at = None      # when to let go, after the reasons ended
        self.reported = None
        self.share_by = ""

    @property
    def sharing(self):
        return self.share.active

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
            now = time.monotonic()
            if not self.ours and not self.limiter.may_turn_on(now):
                self.retry_at = self.limiter.on_after()     # flapping: wait, then try again
            elif not self.ours and not dnd_on() and not self.declined:
                self.retry_at = None
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
                self.limiter.turned_off(time.monotonic())
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
            on = data.split(",")[0] == "1"
            now = time.monotonic()
            if on and not self.share.raw:
                self.share_by = share_owner() or "unknown (a portal client or too quick to see)"
            blips = self.share.blips
            changed = self.share.event(on, now)
            if self.share.blips == 1 and blips == 0:
                print(f"auto-dnd: ignoring screen shares shorter than {SHARE_ENGAGE_S} s "
                      f"(this one: {self.share_by})", flush=True)
            if not changed:
                return
        else:
            return
        self.update()

    def next_due(self):
        """The next monotonic moment due() has something to do (None: none)."""
        times = [t for t in (self.release_at, self.retry_at, self.share.deadline()) if t is not None]
        return min(times) if times else None

    def due(self, now=None):
        """The timed part: a share passing its engage time or its grace, a
        turn-on the limiter held back, the game/quiet release, the hourly
        blip summary."""
        now = time.monotonic() if now is None else now
        if self.share.poll(now):
            if self.share.active:
                print(f"auto-dnd: screen share for {SHARE_ENGAGE_S} s+ by {self.share_by}", flush=True)
            self.update()
        if self.retry_at is not None and now >= self.retry_at:
            self.retry_at = None
            self.update()
        if self.release_at and now >= self.release_at:
            if self.reasons():
                self.release_at = None
            else:
                self.release()
        if now >= self.blip_report_at:
            self.blip_report_at = now + BLIP_REPORT_S
            if self.share.blips > 1:
                print(f"auto-dnd: ignored {self.share.blips} short screen shares in the last hour "
                      f"(latest: {self.share_by})", flush=True)
            self.share.blips = 0


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
            sock = hyprbus.connect({"openwindow", "closewindow", "screencast"}, direct=path)  # Watch.event's
        except OSError:
            time.sleep(2)
            continue
        buf, rescan = b"", time.monotonic() + RESCAN_S
        with sock:
            while True:
                now = time.monotonic()
                edge = watch.until_change()
                due = watch.next_due()
                wait = min(rescan, due if due is not None else rescan,
                           now + edge + 1 if edge is not None else rescan) - now
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
                watch.due(now)
                if now >= rescan or not ready:      # the 30 s rescan, or a timed wake-up
                    rescan = now + RESCAN_S
                    watch.game = games() > 0
                    watch.reload()


if __name__ == "__main__":
    main()
