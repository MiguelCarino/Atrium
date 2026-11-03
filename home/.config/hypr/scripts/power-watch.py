#!/usr/bin/env python3
"""The charger and the battery, watched (power-watch.service): what the
rest of the desktop reacts to when the laptop is unplugged, plugged in or
running low.

    power-watch.py daemon     the watcher (power-watch.service)
    power-watch.py status     JSON: the power state read now, the settings,
                              and what the daemon last wrote

What it does on each change:
  * writes $XDG_RUNTIME_DIR/power-state.json (power_state.POWER_STATE):
    {"has_battery", "on_battery", "ac_online", "battery": {...} or null,
     "warned": [percent, ...], "updated": epoch} -- for the bar and Settings,
    which can read it instead of sysfs; power_state.py answers the same
    questions directly for anything that needs them fresher.
  * the charger plugged in / unplugged: `automations.py event power-plugged`
    / `power-unplugged`, so a rule can switch the theme, the night light,
    the sound or anything else on it. The state at startup is the starting
    point, not an event (automations.py treats its own triggers the same way).
  * the battery reaching each of the warn_at percentages (battery.json,
    power_state.load_settings(); 20, 10 and 5 unless changed) while it
    discharges: one notification per percentage per discharge -- critical at
    the lowest one, with the time left when the battery can say -- and
    `automations.py event battery-low` with AUTOMATION_PERCENT=<percentage>.
    "Reaching" is capacity <= the percentage, so unplugging at 15 % warns at
    once (once: for the lowest percentage passed, 20 here; 10 and 5 are still
    to come). Plugging the charger in resets them all. A restart of this
    daemon during the same discharge does not warn again: the percentages
    already warned are read back from power-state.json.
  * then `battery-saver.py auto`, when that script exists, so the battery
    saver can turn itself on or off (saver_auto_at, saver_on_unplug) without
    a loop of its own.

How it notices. The kernel sends a uevent for the power_supply subsystem
when the charger comes or goes, the battery's status changes and -- on most
laptops, this ASUS included -- each time the capacity moves by a percent.
One long-lived `udevadm monitor --udev --subsystem-match=power_supply` child
turns those into lines on a pipe this process sleeps on: no polling, no
fork per check, zero wake-ups while nothing happens. udevadm is part of
systemd, so it is always there; if it dies it is started again after
RESTART_S. On top of that the battery is read every POLL_S anyway, because
some firmware sends no uevent for capacity at all (and an event can be lost
across suspend); on a machine without a battery that read is every
IDLE_POLL_S, which is where a desktop PC spends its life: this daemon then
does nothing but sleep, and writes power-state.json once with
has_battery false. Nothing else changes for it.

A charger change arrives as a burst -- ACAD, then BATT, then the USB-C
ports, within milliseconds -- so a uevent starts a DEBOUNCE_S wait and the
whole burst is one check (one battery-saver run, not four). Firmware also
updates the battery's status a moment after the charger's "online", so one
more check runs SETTLE_S later to catch the status it has by then.

Reading the battery is power_state.py's job (it knows which supplies are
the machine's own, and the units); this file only decides what is new.
Every command it starts runs in the background, so a slow automations rule
or notification never holds the watch up; finished ones are reaped each
loop.
"""
import json
import os
import select
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_state  # noqa: E402  (no GTK, no forks: sysfs reads)
import desk_common  # noqa: E402  (notify argv, atomic JSON)

UDEV_ARGV = ["udevadm", "monitor", "--udev", "--subsystem-match=power_supply"]
AUTOMATIONS = os.path.join(HERE, "automations.py")
SAVER = os.path.join(HERE, "battery-saver.py")    # Track Saver's; run only when it exists
POLL_S = 60             # the fallback battery read, with a battery
IDLE_POLL_S = 600       # ...without one (a desktop: a battery cannot appear without a uevent)
DEBOUNCE_S = 0.5        # a uevent burst (charger, battery, USB-C ports) is one check
SETTLE_S = 3            # one more check after a burst: the battery's status lags the charger's
RESTART_S = 10          # udevadm ended: start it again after this long
# The statuses a battery reports while a charger is connected: power_state's.
_PLUGGED_STATUSES = power_state.PLUGGED_STATUSES


def log(text):
    print(f"power-watch: {text}", flush=True)


# -- the uevent stream ---------------------------------------------------------------
def parse_uevent(line):
    """The supply a `udevadm monitor` line is about, or None for anything
    else (its header, a blank line, another subsystem). The lines look like

        UDEV  [12345.678901] change   /devices/.../power_supply/BATT (power_supply)
    """
    parts = line.split()
    if len(parts) < 4 or parts[0] != "UDEV" or parts[-1] != "(power_supply)":
        return None
    path = parts[-2]
    if "/power_supply/" not in path:
        return None
    return path.rstrip("/").rsplit("/", 1)[-1] or None


class Monitor:
    """The long-lived udevadm child, read without blocking: read() gives the
    complete lines that have arrived. When it ends (or cannot start) it is
    tried again after RESTART_S; meanwhile the fallback read carries on."""

    def __init__(self, argv=None, clock=time.monotonic):
        self.argv = list(argv or UDEV_ARGV)
        self.clock = clock
        self.proc, self.buf, self.retry_at = None, b"", 0.0

    def start(self):
        if self.proc or self.clock() < self.retry_at:
            return
        try:
            self.proc = subprocess.Popen(self.argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL)
            os.set_blocking(self.proc.stdout.fileno(), False)
        except OSError as err:
            log(f"cannot start {self.argv[0]} ({err}); reading the battery every {POLL_S} s only")
            self.proc, self.retry_at = None, self.clock() + RESTART_S

    def stop(self):
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc.wait()
            self.proc.stdout.close()
            self.proc = None

    def fileno(self):
        return self.proc.stdout.fileno()

    def read(self):
        """The new complete lines; [] (and a restart later) when it ended."""
        if not self.proc:
            return []
        try:
            chunk = os.read(self.fileno(), 65536)
        except BlockingIOError:
            return []
        if not chunk:
            self.stop()
            self.buf, self.retry_at = b"", self.clock() + RESTART_S
            return []
        self.buf += chunk
        *lines, self.buf = self.buf.split(b"\n")
        return [line.decode("utf-8", "replace") for line in lines]


# -- what is new ---------------------------------------------------------------------
def snapshot(root=None):
    """The power state, read now (power_state.py)."""
    return {"has_battery": power_state.has_battery(root), "on_battery": power_state.on_battery(root),
            "ac_online": power_state.ac_online(root), "battery": power_state.battery(root)}


def plugged(snap):
    """Is a charger connected: the charger's own "online" when one is
    reported, else what the battery's status implies; None when neither
    says (a desktop, a battery reading Unknown). power_state.plugged_from()
    is the rule, shared with battery-saver.py."""
    return power_state.plugged_from(snap["ac_online"], (snap["battery"] or {}).get("status"))


def crossed(capacity, warn_at, warned):
    """The warn_at percentages CAPACITY has reached (<=) that were not
    warned yet this discharge, highest first."""
    return sorted((p for p in warn_at if capacity <= p and p not in warned), reverse=True)


def duration(minutes):
    """45 -> "45 min", 125 -> "2 h 5 min"."""
    hours, mins = divmod(int(minutes), 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h {mins} min" if mins else f"{hours} h"


def warning(capacity, minutes_left, critical):
    """(title, body) of the low-battery notification."""
    title = f"Battery low: {capacity}%"
    left = f"About {duration(minutes_left)} left. " if minutes_left else ""
    if critical:
        return title, left + "Plug in the charger now, or save your work."
    return title, left + "Plug in the charger soon."


def _change_key(snap):
    """What counts as a change for battery-saver.py: not the watts, which
    move on every read."""
    bat = snap["battery"] or {}
    return (snap["has_battery"], snap["on_battery"], snap["ac_online"], bat.get("status"), bat.get("capacity"))


def _prior_warned(path=None):
    """The percentages power-state.json says were warned, when it says the
    battery was discharging then (a restart in the middle of a discharge)."""
    data = desk_common.read_json(path or power_state.POWER_STATE, {}, typed=True)
    if not data.get("on_battery"):
        return set()
    return {p for p in data.get("warned", []) if isinstance(p, int) and not isinstance(p, bool)}


class Watch:
    """One check at a time: check() reads the state, decides what is new
    and starts what that calls for. The commands go through SPAWN (argv,
    env) -> a Popen-like object, so the tests hand in a recorder; ROOT is
    the power_supply folder (None: power_state's)."""

    def __init__(self, spawn=None, root=None, saver=SAVER, automations=AUTOMATIONS, now=time.time):
        self.spawn = spawn or self._popen
        self.root = root
        self.saver, self.automations = saver, automations
        self.now = now
        self.last = None            # the previous snapshot (None: none yet)
        self.warned = set()         # warn_at percentages warned this discharge
        self.written = None         # what power-state.json says, minus "updated"
        self.children = []

    # the commands
    @staticmethod
    def _popen(argv, env=None):
        return subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)

    def start(self, argv, env=None):
        try:
            child = self.spawn(argv, env)
        except OSError as err:
            log(f"cannot run {os.path.basename(argv[1] if len(argv) > 1 else argv[0])}: {err}")
            return
        if child is not None:
            self.children.append(child)

    def reap(self):
        """Forget the commands that have finished (no zombies left behind)."""
        self.children = [c for c in self.children if getattr(c, "poll", lambda: 0)() is None]

    def event(self, name, **facts):
        env = dict(os.environ, **{f"AUTOMATION_{k.upper()}": str(v) for k, v in facts.items()})
        self.start([sys.executable, self.automations, "event", name], env)

    def notify(self, title, body, critical):
        argv = desk_common.notify_argv(title, body, app="Battery", urgency="critical" if critical else "normal",
                                       icon="battery-caution" if critical else "battery-low",
                                       mood="alert" if critical else None)
        self.start(argv)

    # the check
    def restore(self, path=None):
        """After a restart: the percentages already warned this discharge."""
        self.warned = _prior_warned(path)

    def check(self):
        """Read, compare, act. Returns what it did, in words (the log, the tests)."""
        snap = snapshot(self.root)
        settings = power_state.load_settings()
        did = []
        now_plugged = plugged(snap)
        if self.last is not None:
            was = plugged(self.last)
            if was is not None and now_plugged is not None and was != now_plugged:
                name = "power-plugged" if now_plugged else "power-unplugged"
                self.event(name)
                did.append(name)
        if now_plugged and not snap["on_battery"]:
            self.warned.clear()
        bat = snap["battery"]
        if snap["on_battery"] and bat and bat.get("capacity") is not None:
            new = crossed(bat["capacity"], settings["warn_at"], self.warned)
            if new:
                percent = new[-1]                           # the lowest one passed
                critical = percent == min(settings["warn_at"])
                self.warned.update(new)
                self.notify(*warning(bat["capacity"], bat.get("minutes_left"), critical), critical)
                self.event("battery-low", percent=percent)
                did.append(f"battery-low {percent}" + (" (critical)" if critical else ""))
        changed = self.last is None or _change_key(snap) != _change_key(self.last)
        self.write(snap)
        if (changed or did) and os.path.exists(self.saver):
            self.start([sys.executable, self.saver, "auto"])
            did.append("battery-saver auto")
        self.last = snap
        return did

    def write(self, snap):
        """power-state.json, when what it says has changed."""
        state = dict(snap, warned=sorted(self.warned, reverse=True))
        if state == self.written:
            return
        try:
            desk_common.atomic_write_json(power_state.POWER_STATE, dict(state, updated=int(self.now())))
            self.written = state
        except OSError as err:
            log(f"cannot write {power_state.POWER_STATE}: {err}")

    def poll_s(self):
        return POLL_S if self.last and self.last["has_battery"] else IDLE_POLL_S


# -- the loop ------------------------------------------------------------------------
def serve(watch, monitor, clock=time.monotonic, wait=select.select, running=lambda: True):
    """Sleep on the udevadm pipe; check after each uevent burst (DEBOUNCE_S,
    then once more SETTLE_S later) and every poll_s() regardless. RUNNING
    is asked before each sleep (the tests stop the loop with it)."""
    did = watch.check()
    if did:
        log(", ".join(did))
    next_poll = clock() + watch.poll_s()
    burst_at = settle_at = None
    while running():
        monitor.start()
        deadlines = [next_poll] + [t for t in (burst_at, settle_at) if t is not None]
        if not monitor.proc:
            deadlines.append(monitor.retry_at)
        timeout = max(0.0, min(deadlines) - clock())
        fds = [monitor] if monitor.proc else []
        try:
            ready, _, _ = wait(fds, [], [], timeout)
        except InterruptedError:
            ready = []
        if ready:
            names = [n for n in (parse_uevent(line) for line in monitor.read()) if n]
            if names and burst_at is None:
                burst_at = clock() + DEBOUNCE_S
        now = clock()
        due = False
        if burst_at is not None and now >= burst_at:
            burst_at, settle_at, due = None, now + SETTLE_S, True
        elif settle_at is not None and now >= settle_at:
            settle_at, due = None, True
        if now >= next_poll:
            due = True
        if due:
            did = watch.check()
            if did:
                log(", ".join(did))
            next_poll = clock() + watch.poll_s()
        watch.reap()


def status():
    """The status command's JSON: read now, plus what the daemon wrote."""
    snap = snapshot()
    written = desk_common.read_json(power_state.POWER_STATE, None, typed=False)
    return dict(snap, plugged=plugged(snap), saver_active=power_state.saver_active(),
                frugal=power_state.frugal(fresh=True), settings=power_state.load_settings(),
                warned=(written or {}).get("warned", []) if isinstance(written, dict) else [],
                daemon=written if isinstance(written, dict) else None)


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if cmd == "daemon":
        # SIGTERM (systemctl stop) unwinds through the finally below, so the
        # udevadm child goes with this process instead of lingering.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        watch, monitor = Watch(), Monitor()
        watch.restore()
        try:
            serve(watch, monitor)
        finally:
            monitor.stop()
        return 0
    print(__doc__.split("\n\n")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
