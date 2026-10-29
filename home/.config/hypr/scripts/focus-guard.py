#!/usr/bin/env python3
"""Focus guard: notices when you are scattered -- hopping between unrelated
windows for a good while -- and offers a focus block; runs the focus block
(a timer in the bar, the notifications held, the distracting apps and sites
dimmed or made to wait 10 seconds -- never blocked); and at its end says what
came in and what you did. The daily focus minutes go into the brief and the
journal (brief.py).

    focus-guard.py daemon              the service (focus-guard.service)
    focus-guard.py start [MIN] [--suggested]
                                       a focus block of MIN minutes (default:
                                       timers.py's focus_min); without the
                                       service running, a plain focus round
                                       (timers.py focus)
    focus-guard.py stop                end the block (and its break) now
    focus-guard.py toggle              start one, or stop the one running (the key)
    focus-guard.py status [--json]     what the service is doing
    focus-guard.py get [--json]        the settings, the switches, today's and
                                       the week's focus (Settings > Focus)
    focus-guard.py set on|off          the service (enable --now / disable --now)
    focus-guard.py set detect on|off   noticing scattered switching (the
                                       privacy switch, privacy.conf focus_watch)
    focus-guard.py set KEY VALUE       a setting (DEFAULTS below); minutes,
                                       break_min, long_break_min, long_every
                                       are timers.py's own settings
    focus-guard.py apps|sites add|remove WORD   the distracting lists
    focus-guard.py stats [--json] [DAYS]   focus minutes per day (default 7)
    focus-guard.py sample [app|site]   show the "still want this?" card (its
                                       buttons do nothing)
    focus-guard.py check [--json]      how scattered the last window_min look
                                       now (the daemon's numbers; nothing shown)
    focus-guard.py overlay [--render PNG]   (internal) the card; its JSON on stdin

NOTICING (off as shipped: it watches which window has the focus, so it is a
privacy switch -- Settings > Focus and Settings > Privacy; privacy.conf
focus_watch). The daemon follows Hyprland's event socket (activewindow:
class and title) and, at its start, seeds the last window_min from the
activity history (activity-log.py's activity.jsonl, when that is on). A
window counts once it kept the focus DWELL_S. Each one is reduced at once
to a GROUP, and only the group and the time are kept, in memory:

    the project context you are in (contexts.py) for its terminals, editors
    and file managers, and for any window whose title names its repo;
    else the projects-folder repo the title names (brief.py's project_of);
    else the app (terminals, editors, file managers each one family);
    "private" for private windows (activity-log.py's rule + the Privacy
    page's list, password managers) -- their titles are never read.

Scattered = in the last window_min (20) there were at least N switches
between groups (a switch INTO a distracting app or site counts twice) among
at least G different groups -- sensitivity low 45/6, medium 30/5, high
20/4 per 20 min, scaled with window_min. Going back and forth between an
editor and a terminal on the same repo is one group: no switch at all.

The offer goes to the live suggestions strip (suggest.py, its "focus" kind)
when that runs and takes it, else a notification with "Focus N min". Never
during a block or a break, a fullscreen window, gamemode, Do Not Disturb or
a lock; at most once per cooldown_min; when= always | work (only in
workhours.py's work time) | free (only outside it). After an offer the count
starts again from nothing.

THE BLOCK is a timers.py focus round (the bar's countdown pill, its
systemd timer, its rounds-today count), started through here so it gets:

    quiet    dnd: Do Not Disturb (timers.py turns it off at the end) |
             project: contexts.py's project-focus mako mode for the context
             you are in (Do Not Disturb when you are in none) | none
    dimming  style dim: the windows of the apps on the list, and a browser
             window while its title names a site on the list, are tagged
             "focus-dim" and lua/focusguard.lua makes them dim_pct % opaque |
             delay: a newly opened app window waits on a hidden workspace
             (special:focusguard) behind a card "Still want Discord?" whose
             "Open it" unlocks after delay_s; "Not now" keeps it there until
             the block ends (it comes back by itself); a browser landing on a
             site gets the same card, with "Back to work" | both
    breaks   on: timers.py's pomodoro rhythm (a break after each round, a long
             one every long_every) | off: the block just ends
    the end  digest: what was held back (notify-digest.py; with dnd it is
             automations.py's built-in dnd-digest rule) and summary: one
             notification "what you did" -- where the time went (the
             activity history, by project and app, brief.py's tally), how
             many switches, your commits in the block (git log, brief.py's
             commits_in); "Focus again" when breaks are off

A focus round started anywhere else (the launcher's "focus", a suggestion's
"Start a focus round", timers.py focus) comes here first through
timers.start_focus, so it follows these settings too; with the service off
it is the plain timers.py round. The automations get "focus-start" /
"focus-end" events and a "focus N" / "focus off" action.

STATS ($XDG_STATE_HOME/hypr/focus-guard-stats.json, STATS_DAYS kept): per
day the focused minutes, blocks, offers made and taken, apps that waited
and were opened anyway. Counts only, no names. brief.py shows them.

SETTINGS: $XDG_STATE_HOME/hypr/focus-guard.conf (key=value; DEFAULTS /
LIMITS / CHOICES; a bad line is its default). The running block (which
windows are tagged, parked, allowed): $XDG_RUNTIME_DIR/focus-guard.json, so
a restarted service picks it up again; a stopped one gives the parked
windows back and lifts the dimming first.

NEVER: closes, kills or blocks a window; runs anything a model said; sends
anything anywhere. Window titles live in memory only, for the moment it
takes to find the group or a site.
"""
import datetime as dt
import importlib.util
import json
import math
import os
import queue
import re
import select
import signal
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desk_common  # noqa: E402  (notify: the notification, through scripts/notify)
SELF = os.path.abspath(__file__)
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
CONF = os.path.join(STATE_HOME, "hypr", "focus-guard.conf")
STATS = os.path.join(STATE_HOME, "hypr", "focus-guard-stats.json")
ACTIVITY = os.path.join(STATE_HOME, "hypr", "activity.jsonl")
LIVE = os.path.join(RUNTIME, "focus-guard.json")
DIM_FILE = os.path.join(RUNTIME, "focus-guard-dim.conf")       # read by lua/focusguard.lua
CONTEXTS_STATE = os.path.join(RUNTIME, "contexts.json")
SOCK = os.path.join(RUNTIME, "focus-guard.sock")
UNIT = "focus-guard.service"
AUTOMATIONS = os.path.join(HERE, "automations.py")
NOTIFY_DIGEST = os.path.join(HERE, "notify-digest.py")
SETTINGS_APP = os.path.join(HERE, "settings.py")
APP = "Focus guard"
ICON = ""             # bullseye, like timers.py's focus pill
TAG = "focus-dim"
PARK = "special:focusguard"

TICK_S = 5
HYPR_EVENTS = ("activewindow", "activewindowv2", "openwindow", "windowtitlev2", "closewindow",
               "configreloaded")       # what Daemon.event reads (through hyprbus, only these wake it)
DWELL_S = 2.0               # a window has the focus this long before it counts
KEEP_S = 3600               # history older than this is dropped
LOCK_GAP_S = 120            # asleep / locked longer than this: start counting again
STATS_DAYS = 120
OVERLAY_WAIT_S = 60         # an unanswered card: "Not now"
ADDRESS = re.compile(r"0x[0-9a-f]{4,16}$")
WORKSPACE = re.compile(r"[\w:.+-]{1,40}$")
BROWSERS = re.compile(r"firefox|chrom|brave|zen|librewolf|vivaldi|opera|epiphany|floorp|waterfox|"
                      r"msedge|qutebrowser|falkon|midori", re.I)
FAMILIES = (("terminal", re.compile(r"term|kitty|foot|alacritty|wezterm|konsole|ghostty|tilix|terminator", re.I)),
            ("editor", re.compile(r"code|codium|zed|neovide|gedit|texteditor|kate|sublime|jetbrains|pycharm|"
                                  r"idea|emacs|gvim|lapce|helix", re.I)),
            ("files", re.compile(r"nautilus|thunar|dolphin|cosmic.?files|nemo|pcmanfm", re.I)))
WORK_FAMILIES = ("terminal", "editor", "files")
SENSITIVITY = {"low": (45, 6), "medium": (30, 5), "high": (20, 4)}     # switches, groups per 20 min

DEFAULTS = {"sensitivity": "medium", "window_min": "20", "cooldown_min": "60", "when": "always",
            "quiet": "dnd", "style": "dim", "dim_pct": "55", "delay_s": "10",
            "apps": "discord,vesktop,steam,spotify,org.telegram.desktop",
            "sites": "youtube,reddit,instagram,facebook,tiktok,twitch,netflix,twitter",
            "breaks": "on", "digest": "on", "summary": "on"}
LIMITS = {"window_min": (10, 60), "cooldown_min": (15, 480), "dim_pct": (20, 90), "delay_s": (3, 30)}
CHOICES = {"sensitivity": tuple(SENSITIVITY), "when": ("always", "work", "free"),
           "quiet": ("dnd", "project", "none"), "style": ("dim", "delay", "both"),
           "breaks": ("on", "off"), "digest": ("on", "off"), "summary": ("on", "off")}
LISTS = {"apps": re.compile(r"[a-z0-9][\w.+-]{0,63}$"), "sites": re.compile(r"[a-z0-9][\w .-]{1,39}$")}
TIMER_KEYS = {"minutes": "focus_min", "break_min": "break_min", "long_break_min": "long_break_min",
              "long_every": "long_every"}


def _module(name, filename, folder=HERE):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(folder, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[name]
            raise
    return mod


def timers():
    return _module("timers", "timers.py")


def suggest():
    """suggest.py's helpers: the event socket, hyprctl, DND / gamemode /
    lock checks, the private-window rule, its socket."""
    return _module("suggest", "suggest.py")


def brief():
    """brief.py's activity reading (periods, tally, project_of, commits_in)."""
    return _module("brief", "brief.py")


def privacy():
    return _module("privacy_settings", "privacy_settings.py")


def log(text):
    print(f"focus-guard: {text}", file=sys.stderr, flush=True)


# -- settings -------------------------------------------------------------------------------
def check_value(key, value):
    """The tidy value for KEY, or None when it is not one."""
    value = str(value).strip().lower()
    if key in CHOICES:
        return value if value in CHOICES[key] else None
    if key in LIMITS:
        try:
            n = int(value)
        except ValueError:
            return None
        lo, hi = LIMITS[key]
        return str(n) if lo <= n <= hi else None
    if key in LISTS:
        words = []
        for word in value.split(","):
            word = " ".join(word.split())
            if word and LISTS[key].match(word) and word not in words:
                words.append(word)
        return ",".join(words)
    return None


def read_settings(path=None):
    values = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                key = key.strip()
                if sep and key in DEFAULTS:
                    good = check_value(key, value)
                    if good is not None:
                        values[key] = good
    except OSError:
        pass
    return values


def write_setting(key, value, path=None):
    """Keep KEY=VALUE (checked); the file holds only what differs from DEFAULTS."""
    good = check_value(key, value)
    if good is None:
        raise ValueError(f"{key}: {value!r} is not one of its values")
    path = path or CONF
    values = read_settings(path)
    values[key] = good
    changed = {k: v for k, v in values.items() if v != DEFAULTS[k]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write("# focus-guard.py settings (focus-guard.py set KEY VALUE; Settings > Focus)\n")
        handle.writelines(f"{k}={v}\n" for k, v in changed.items())
    os.replace(tmp, path)
    return good


def items(values, key):
    return [w for w in (values.get(key) or "").split(",") if w]


def number(values, key):
    return int(values.get(key) or DEFAULTS[key])


def watch_on(conf=None):
    """May the daemon follow the focus to notice scattering (privacy.conf
    focus_watch; OFF as shipped)?"""
    try:
        return privacy().focus_watch_on(conf if conf is not None else privacy().load())
    except Exception:       # noqa: BLE001 -- unsure: off
        return False


# -- what a window is (pure: tests/test_focus_guard.py) ---------------------------------------
def family(cls):
    for name, pattern in FAMILIES:
        if pattern.search(cls or ""):
            return name
    return None


def distracting_app(cls, apps):
    """Is the class on the apps list: the whole class, or its last dotted
    part ("com.discordapp.Discord" -> "discord"), case-insensitive."""
    c = (cls or "").lower()
    return bool(c) and any(c == a or c.rsplit(".", 1)[-1] == a for a in apps)


def site_of(cls, title, sites):
    """The listed site a browser window's title names (as a word), or None."""
    if not BROWSERS.search(cls or "") or not title:
        return None
    for site in sites:
        if re.search(rf"(?<![\w.]){re.escape(site)}(?![\w])", title, re.I):
            return site
    return None


def group_of(cls, title, private, repos, context="", project_of=None):
    """The group a focused window belongs to (the module docstring says
    which). Titles are looked at here and nowhere kept."""
    if not cls:
        return ""
    if private:
        return "private"
    proj = project_of(title, repos) if project_of and title else None
    fam = family(cls)
    if context and (fam in WORK_FAMILIES or (proj or "").lower() == context.lower()
                    or re.search(rf"\b{re.escape(context)}\b", title or "", re.I)):
        return f"project:{context}"
    if proj:
        return f"project:{proj}"
    return fam or cls.lower()


def scatter(history, now, window_s, sensitivity="medium"):
    """How scattered the last window_s were. history: [(t, group,
    distracting)] in time order, one per window that kept the focus. The
    group that had the focus when the window began counts as the start."""
    start = now - window_s
    before = [h for h in history if h[0] < start]
    inside = [h for h in history if h[0] >= start]
    prev = before[-1][1] if before else None
    switches = weighted = 0
    groups, seen_distracting = set(), 0
    if prev:
        groups.add(prev)
    for _t, group, dis in inside:
        if not group:
            continue
        groups.add(group)
        if prev is not None and group != prev:
            switches += 1
            weighted += 2 if dis else 1
            seen_distracting += 1 if dis else 0
        prev = group
    base_s, base_g = SENSITIVITY.get(sensitivity, SENSITIVITY["medium"])
    need = math.ceil(base_s * window_s / 1200)
    groups.discard("")
    return {"switches": switches, "weighted": weighted, "groups": len(groups), "distracting": seen_distracting,
            "need": need, "need_groups": base_g,
            "scattered": weighted >= need and len(groups) >= base_g}


# -- stats ----------------------------------------------------------------------------------------
STAT_KEYS = ("minutes", "blocks", "offered", "taken", "waited", "opened")


def load_stats(path=None):
    try:
        with open(path or STATS) as handle:
            data = json.load(handle)
        days = data.get("days") if isinstance(data, dict) else None
        return {"days": days if isinstance(days, dict) else {}}
    except (OSError, ValueError):
        return {"days": {}}


def add_stats(day=None, path=None, **inc):
    """Add to a day's counts (today by default); old days are dropped."""
    path = path or STATS
    data = load_stats(path)
    key = (day or dt.date.today()).isoformat()
    row = data["days"].setdefault(key, {})
    for k, v in inc.items():
        if k in STAT_KEYS:
            row[k] = round(row.get(k, 0) + v, 1)
    cutoff = (dt.date.today() - dt.timedelta(days=STATS_DAYS)).isoformat()
    data["days"] = {d: r for d, r in data["days"].items() if d >= cutoff}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)
    return row


def day_stats(day, path=None):
    """{"minutes", "blocks", ...} for a date, or None when nothing was focused
    (brief.py's brief and journal read this)."""
    row = load_stats(path)["days"].get(day.isoformat())
    if not row or not row.get("minutes"):
        return None
    return {k: row.get(k, 0) for k in STAT_KEYS}


def recent_stats(days=7, today=None, path=None):
    today = today or dt.date.today()
    data = load_stats(path)["days"]
    out = []
    for back in range(days - 1, -1, -1):
        d = today - dt.timedelta(days=back)
        row = data.get(d.isoformat(), {})
        out.append({"day": d.isoformat(), **{k: row.get(k, 0) for k in STAT_KEYS}})
    return out


def minutes_text(minutes):
    m = int(round(minutes))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


# -- the summary at the end (pure but for its inputs) -----------------------------------------------
def summary_lines(tally, switches, commits, parked_names):
    """The "what you did" lines: where the time went, the switching, the
    commits, what waited."""
    lines = []
    if tally and tally.get("projects"):
        top = ", ".join(f"{name.removeprefix('project:')} {minutes_text(s / 60)}"
                        for name, s in tally["projects"][:3] if name != "private")
        if top:
            lines.append(f"Mostly {top}.")
    if switches is not None:
        lines.append(f"{switches} window switch{'es' if switches != 1 else ''}.")
    n = sum(len(rows) for rows in commits.values())
    if n:
        lines.append(f"{n} commit{'s' if n != 1 else ''} in {', '.join(list(commits)[:3])}.")
    if parked_names:
        lines.append(f"Waited for you: {', '.join(parked_names[:4])} (back on their workspaces now).")
    return lines


# -- Hyprland ------------------------------------------------------------------------------------------
def hypr(kind, lua):
    """hyprctl dispatch|eval LUA; True when it said ok."""
    try:
        out = subprocess.run(["hyprctl", kind, lua], capture_output=True, text=True, timeout=3)
        return out.returncode == 0 and "ok" in out.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def window_arg(addr):
    if not ADDRESS.match(addr or ""):
        raise ValueError(f"not a window address: {addr!r}")
    return f"'address:{addr}'"


def tag(addr, on):
    return hypr("dispatch", f"hl.dsp.window.tag({{ tag = '{'+' if on else '-'}{TAG}', window = {window_arg(addr)} }})")


def move(addr, workspace, follow=False):
    if not WORKSPACE.match(workspace or ""):
        raise ValueError(f"not a workspace: {workspace!r}")
    return hypr("dispatch", f"hl.dsp.window.move({{ workspace = '{workspace}', "
                            f"follow = {'true' if follow else 'false'}, window = {window_arg(addr)} }})")


def focus_window(addr):
    return hypr("dispatch", f"hl.dsp.focus({{ window = {window_arg(addr)} }})")


def write_dim(on, pct):
    tmp = f"{DIM_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write(f"# focus-guard.py: lua/focusguard.lua dims the windows tagged {TAG}\n"
                     f"on={1 if on else 0}\nopacity={int(pct)}\n")
    os.replace(tmp, DIM_FILE)


def apply_dim(on, pct):
    write_dim(on, pct)
    return hypr("eval", 'require("lua.focusguard").apply()')


def makoctl(*args):
    try:
        return subprocess.run(["makoctl", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def automation_event(name):
    """automations.py event focus-start|focus-end (nothing when it is not running)."""
    if os.path.exists(AUTOMATIONS):
        spawn(sys.executable, AUTOMATIONS, "event", name)


def spawn(*argv):
    try:
        subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def notify(summary, body="", actions=(), urgency="normal", wait=None):
    """A notification; with actions, the picked key ("" when closed / timed out)."""
    return desk_common.notify(summary, body, app=APP, urgency=urgency, icon="emblem-default-symbolic",
                              actions=actions, timeout=wait if actions else 5)


def work_time():
    try:
        return bool(_module("workhours", "workhours.py").state()[0])
    except Exception:       # noqa: BLE001
        return False


def read_context():
    try:
        with open(CONTEXTS_STATE) as handle:
            data = json.load(handle)
        return (data.get("name") or "") if isinstance(data, dict) else ""
    except (OSError, ValueError):
        return ""


# -- the daemon -----------------------------------------------------------------------------------------
class Daemon:
    """The focus history (for noticing), the block in progress (tags, parked
    windows, the card) and the offer. Everything that reaches Hyprland,
    timers.py or a notification goes through a method a test can replace."""

    def __init__(self, values=None, clock=time.time):
        self.clock = clock
        self.values = values or read_settings()
        self.inbox = queue.Queue()          # (op, arg) from notification threads
        self.wake = None                    # a socket to poke the loop with
        self.history = []                   # [(t, group, distracting)]
        self.pending = None                 # (t, class, title) not yet DWELL_S
        self.watch_since = clock()
        self.last_offer = 0.0
        self.repos, self.repos_at = [], 0.0
        self.context = ""
        self.locked = False
        self.offset = suggest().slept_offset()
        self.block = None
        self.clients = {}                   # address -> class (while a block runs)
        self.titles = {}                    # address -> title (memory only, while a block runs)
        self.last_work = None               # the last non-distracting window focused (Back to work)
        self.overlay = None                 # (Popen, card, buffer)
        self.waiting = []                   # parked windows still to ask about
        self.timers_mtime = None
        self.watching = watch_on()          # the noticing switch as last seen (follow_switch)

    # -- facts ---------------------------------------------------------------------------
    def reload(self):
        old = self.values
        self.values = read_settings()
        if self.block and any(old.get(k) != self.values[k] for k in ("style", "dim_pct", "apps", "sites")):
            self.retag(reset=old.get("style") != self.values["style"])
            self.save_live()

    def repo_names(self, now):
        if now - self.repos_at > 600:
            self.repos_at = now
            try:
                self.repos = brief().repo_names()
            except Exception:       # noqa: BLE001
                self.repos = []
        return self.repos

    def is_private(self, cls, title):
        return suggest().is_private(cls, title)

    def event(self, line):
        name, _, data = line.partition(">>")
        now = self.clock()
        if name == "activewindow":
            cls, _, title = data.partition(",")
            self.focused(cls, title, now)
        elif name == "activewindowv2":
            addr = data.strip()
            addr = addr if addr.startswith("0x") else "0x" + addr
            if self.block and ADDRESS.match(addr) and not self.is_distracting(addr):
                self.last_work = addr
        elif name == "openwindow":
            parts = data.split(",", 3)
            if len(parts) == 4:
                self.opened("0x" + parts[0].removeprefix("0x"), parts[1], parts[2], parts[3])
        elif name == "windowtitlev2":
            addr, _, title = data.partition(",")
            self.retitled("0x" + addr.removeprefix("0x"), title)
        elif name == "closewindow":
            self.closed("0x" + data.strip().removeprefix("0x"))
        elif name == "configreloaded" and self.block:
            self.dim_rule()

    # -- noticing ------------------------------------------------------------------------------
    def focused(self, cls, title, now):
        self.settle(now)
        self.pending = (now, cls, title) if cls else None

    def settle(self, now):
        """The pending window, once it kept the focus DWELL_S, into the history
        as its group (and nothing else)."""
        if not self.pending or now - self.pending[0] < DWELL_S:
            return
        t, cls, title = self.pending
        self.pending = None
        if not watch_on() or self.block or self.on_break():
            return
        private = self.is_private(cls, title)
        apps, sites = items(self.values, "apps"), items(self.values, "sites")
        dis = not private and (distracting_app(cls, apps) or bool(site_of(cls, title, sites)))
        try:
            project_of = brief().project_of
        except Exception:       # noqa: BLE001
            project_of = None
        group = group_of(cls, "" if private else title, private, self.repo_names(now), self.context, project_of)
        if self.history and self.history[-1][1] == group:
            return
        self.history.append((t, group, dis))
        self.history = [h for h in self.history if h[0] > now - KEEP_S]

    def seed(self, now):
        """The last window_min from the activity history, so a fresh start
        (a login, a restart) does not need 20 minutes before it can tell."""
        if not watch_on():
            return
        window_s = number(self.values, "window_min") * 60
        try:
            b = brief()
            rows = b.read_activity(ACTIVITY) or []
            rows = [r for r in rows if r["t"] > now - window_s - 600]
            spans = b.periods(rows, now - window_s - 600, now, now)
        except Exception:       # noqa: BLE001
            return
        if not spans:
            return
        apps, sites = items(self.values, "apps"), items(self.values, "sites")
        for a, bnd, cls, title in spans:
            if bnd - a < DWELL_S:
                continue
            private = cls == "private"
            group = group_of(cls, title, private, self.repo_names(now), self.context, b.project_of)
            dis = not private and (distracting_app(cls, apps) or bool(site_of(cls, title, sites)))
            if not self.history or self.history[-1][1] != group:
                self.history.append((a, group, dis))
        if spans[0][0] <= now - window_s:
            self.watch_since = now - window_s

    def check_away(self, now):
        """Locked or asleep a while: the count starts again."""
        offset = suggest().slept_offset()
        slept, self.offset = offset - self.offset, offset
        locked = suggest().process_running("hyprlock")
        if slept > LOCK_GAP_S or (locked and not self.locked):
            self.forget(now)
        self.locked = locked

    def forget(self, now):
        self.history, self.pending, self.watch_since = [], None, now

    def numbers(self, now):
        window_s = number(self.values, "window_min") * 60
        out = scatter(self.history, now, window_s, self.values["sensitivity"])
        out["watching_s"] = int(now - self.watch_since)
        out["window_s"] = window_s
        return out

    def quiet_reason(self, now):
        if not watch_on():
            return "not watching (off on the Privacy page)"
        if self.block:
            return "in a focus block"
        if self.on_break():
            return "on a break"
        if self.locked:
            return "locked"
        if now - self.last_offer < number(self.values, "cooldown_min") * 60:
            return "offered a block not long ago"
        when = self.values["when"]
        if when != "always" and work_time() != (when == "work"):
            return "outside the hours it is set for"
        s = suggest()
        if s.dnd_on():
            return "do not disturb"
        if s.gamemode_on():
            return "gamemode"
        if s.fullscreen_mode(s.hyprctl_json("activewindow")):
            return "fullscreen"
        return ""

    def maybe_offer(self, now):
        n = self.numbers(now)
        if not n["scattered"] or n["watching_s"] < n["window_s"]:
            return None
        why = self.quiet_reason(now)
        if why:
            return None
        self.last_offer = now
        self.forget(now)
        add_stats(offered=1)
        minutes = timers().setting("focus_min")
        card = {"minutes": minutes, "switches": n["switches"], "groups": n["groups"],
                "window_min": n["window_s"] // 60}
        reply = suggest().ask_daemon({"op": "focus", "card": card}, timeout=2)
        if isinstance(reply, dict) and reply.get("taken"):
            log("offered a focus block (suggestions strip)")
            return "strip"
        threading.Thread(target=self.offer_notification, args=(card,), daemon=True).start()
        log("offered a focus block (notification)")
        return "notification"

    def offer_notification(self, card):
        picked = notify("Lots of switching lately",
                        f"{card['switches']} switches between {card['groups']} things in {card['window_min']} min. "
                        "A focus block dims the distractions and holds the notifications.",
                        [("start", f"Focus {card['minutes']} min"), ("later", "Not now")], wait=180)
        if picked == "start":
            self.post("start", {"minutes": card["minutes"], "suggested": True})

    def post(self, op, arg):
        self.inbox.put((op, arg))
        if self.wake is not None:
            try:
                self.wake.send(b"!")
            except OSError:
                pass

    # -- the block ------------------------------------------------------------------------------
    def focus_entries(self):
        return [t for t in timers().load()["timers"] if t.get("kind") == "focus"]

    def on_break(self):
        now = self.clock()
        try:
            return any(t.get("kind") == "break" and t.get("due", 0) > now for t in timers().load()["timers"])
        except Exception:       # noqa: BLE001
            return False

    def start(self, minutes=None, suggested=False):
        """A focus block (the socket's "start"): quiet, the timers.py round
        (with this block's flags), then begin()."""
        now = self.clock()
        t = timers()
        running = [e for e in self.focus_entries() if e.get("due", 0) > now]
        if running:
            return {"error": "a focus block is running already", "id": running[0]["id"]}
        try:
            minutes = int(minutes or t.setting("focus_min"))
        except (TypeError, ValueError):
            return {"error": "minutes is a number"}
        if not 1 <= minutes <= 240:
            return {"error": "minutes go from 1 to 240"}
        quiet, we_set, dnd = self.values["quiet"], "", False
        if quiet == "project":
            ctx_name = read_context()
            ctx = None
            if ctx_name:
                try:
                    c = _module("contexts", "contexts.py")
                    ctx = c.find(c.load()[0], ctx_name)
                except Exception:       # noqa: BLE001
                    ctx = None
            if ctx is None:
                quiet = "dnd"
            elif c.MODE not in (c.mako_modes() or []):
                we_set = "project" if c.focus_project(ctx) else ""
                if not we_set:
                    quiet = "dnd"
        if quiet == "dnd" and "do-not-disturb" not in makoctl("mode").split():
            makoctl("mode", "-a", "do-not-disturb")
            t.bell()
            dnd = True
        marked = False
        if quiet != "dnd" and self.values["digest"] == "on":
            spawn(sys.executable, NOTIFY_DIGEST, "mark")
            marked = True
        try:
            entry = t.schedule("focus", now + minutes * 60, "", minutes * 60, dnd=dnd,
                               nobreak=self.values["breaks"] == "off", guard=True)
        except (OSError, subprocess.SubprocessError) as exc:
            # systemd-run said no: undo the quiet set above (no round would ever
            # turn it off) and say so, instead of the error ending the daemon
            if dnd:
                makoctl("mode", "-r", "do-not-disturb")
            if we_set == "project":
                try:
                    c.focus_project_off()
                except Exception:       # noqa: BLE001
                    pass
            log(f"the focus round could not be armed: {exc.__class__.__name__}")
            return {"error": "the focus round's timer could not be armed (systemd-run)"}
        if suggested or now - self.last_offer < 600:
            add_stats(taken=1)
        self.begin(entry, quiet=quiet, we_set=we_set, marked=marked)
        return {"ok": True, "id": entry["id"], "minutes": minutes, "quiet": quiet}

    def begin(self, entry, quiet="timers", we_set="", marked=False, resumed=None):
        now = self.clock()
        self.block = resumed or {"id": entry["id"], "start": now, "due": entry["due"], "quiet": quiet,
                                 "we_set": we_set, "marked": marked, "tagged": {}, "parked": {},
                                 "allowed": [], "names": {}}
        self.block["due"] = entry["due"]
        self.forget(now)
        self.retag()
        self.save_live()
        if not resumed:
            log(f"focus block until {dt.datetime.fromtimestamp(entry['due']):%H:%M} (quiet: {quiet})")
            automation_event("focus-start")

    def save_live(self):
        if self.block is None:
            try:
                os.remove(LIVE)
            except OSError:
                pass
            return
        tmp = f"{LIVE}.{os.getpid()}.tmp"
        old = os.umask(0o077)
        try:
            with open(tmp, "w") as handle:
                json.dump(self.block, handle)
            os.replace(tmp, LIVE)
        finally:
            os.umask(old)

    def dim_rule(self):
        style = self.values["style"]
        apply_dim(bool(self.block) and style in ("dim", "both"), number(self.values, "dim_pct"))

    def wants_dim(self):
        return self.values["style"] in ("dim", "both")

    def wants_delay(self):
        return self.values["style"] in ("delay", "both")

    def is_distracting(self, addr):
        return bool(self.block) and addr in self.block["tagged"]

    def retag(self, reset=False):
        """Every open window against the lists: tag what is distracting,
        untag what no longer is (a block's start, a settings change; reset:
        the style changed, so every tag comes off first)."""
        if not self.block:
            return
        if reset:
            for addr in list(self.block["tagged"]):
                tag(addr, False)
            self.block["tagged"] = {}
        clients = suggest().hyprctl_json("clients") or []
        self.clients = {c.get("address"): c.get("class") or "" for c in clients if c.get("address")}
        self.titles = {c.get("address"): c.get("title") or "" for c in clients if c.get("address")}
        for c in clients:
            ws = (c.get("workspace") or {}).get("name") or ""
            if ws == PARK and c["address"] not in self.block["parked"]:
                self.block["parked"][c["address"]] = "?"        # left over: given back at the end
        for addr in list(self.clients):
            self.check_window(addr)
        for addr in [a for a in self.block["tagged"] if a not in self.clients]:
            del self.block["tagged"][addr]
        self.dim_rule()

    def why_distracting(self, addr):
        cls, title = self.clients.get(addr, ""), self.titles.get(addr, "")
        if self.is_private(cls, title):
            return None
        if distracting_app(cls, items(self.values, "apps")):
            return "app"
        site = site_of(cls, title, items(self.values, "sites"))
        return f"site:{site}" if site else None

    def check_window(self, addr, opened_ws=None):
        """One window against the lists. block["tagged"] holds every window
        found distracting (and why: "app" / "site:<word>"); the Hyprland tag
        only while the style dims. A new app window (opened_ws: where it
        opened) waits when the style delays; a browser landing on a site
        gets the card."""
        why = self.why_distracting(addr)
        was = self.block["tagged"].get(addr)
        if why != was:
            if self.wants_dim() and bool(why) != bool(was):
                tag(addr, bool(why))
            if why:
                self.block["tagged"][addr] = why
            else:
                self.block["tagged"].pop(addr, None)
        if not why or not self.wants_delay():
            return
        if why == "app" and opened_ws is not None and addr not in self.block["allowed"]:
            self.park(addr, suggest().app_name(self.clients.get(addr, "")), opened_ws)
        elif why.startswith("site:") and why != was and f"{addr}|{why}" not in self.block["allowed"]:
            self.ask_site(addr, why[5:])

    def opened(self, addr, workspace, cls, title):
        if not self.block or not ADDRESS.match(addr):
            return
        self.clients[addr], self.titles[addr] = cls, title
        self.check_window(addr, opened_ws=workspace)
        self.save_live()

    def retitled(self, addr, title):
        if not self.block or addr not in self.clients:
            return
        self.titles[addr] = title
        self.check_window(addr)
        self.save_live()

    def closed(self, addr):
        if not self.block:
            return
        self.clients.pop(addr, None)
        self.titles.pop(addr, None)
        self.block["tagged"].pop(addr, None)
        self.block["parked"].pop(addr, None)
        self.waiting = [w for w in self.waiting if w[1] != addr]
        self.save_live()

    def park(self, addr, name, ws):
        """A distracting app's new window: onto the hidden workspace, and
        the card asks (or, when one is up, it waits its turn). One opened
        on a special workspace (a scratchpad) is left where it is."""
        if not WORKSPACE.match(ws or "") or ws.startswith("special:") or addr in self.block["parked"]:
            return
        if not move(addr, PARK):
            return
        self.block["parked"][addr] = ws
        self.block["names"][addr] = name
        self.waiting.append(("app", addr, name))
        self.save_live()

    def ask_site(self, addr, site):
        if not any(w[1] == addr for w in self.waiting):
            self.waiting.append(("site", addr, site))

    def maybe_card(self):
        if self.overlay or not self.waiting or not self.block:
            return
        kind, addr, name = self.waiting.pop(0)
        if addr not in self.clients:
            return
        left = max(1, round((self.block["due"] - self.clock()) / 60))
        card = {"kind": kind, "addr": addr, "name": name if kind == "app" else name.capitalize(),
                "left_min": left, "delay_s": number(self.values, "delay_s")}
        self.show_overlay(card)

    def show_overlay(self, card):
        try:
            proc = subprocess.Popen([sys.executable, SELF, "overlay"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            proc.stdin.write(json.dumps(card).encode())
            proc.stdin.close()
        except OSError as exc:
            log(f"the card did not start: {exc}")
            return
        os.set_blocking(proc.stdout.fileno(), False)
        self.overlay = (proc, card, b"")

    def overlay_output(self):
        proc, card, buf = self.overlay
        try:
            chunk = proc.stdout.read() or b""
        except (OSError, ValueError):
            chunk = b""
        buf += chunk
        self.overlay = (proc, card, buf)
        if chunk and proc.poll() is None:
            return
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc.stdout.close()
        self.overlay = None
        result = ""
        for line in buf.decode("utf-8", "replace").splitlines():
            try:
                result = json.loads(line).get("result") or result
            except (ValueError, AttributeError):
                continue
        self.answered(card, result)

    def answered(self, card, result):
        if card.get("sample") or not self.block:
            return
        addr = card["addr"]
        if card["kind"] == "app":
            if result == "open" and addr in self.block["parked"]:
                ws = self.block["parked"].pop(addr)
                self.block["allowed"].append(addr)
                move(addr, self.home(ws), follow=True)
                focus_window(addr)
                add_stats(opened=1)
            else:
                add_stats(waited=1)
        elif card["kind"] == "site":
            why = self.block["tagged"].get(addr) or f"site:{card['name'].lower()}"
            if result == "keep":
                self.block["allowed"].append(f"{addr}|{why}")
                add_stats(opened=1)
            else:
                add_stats(waited=1)
                if result == "back" and self.last_work and self.last_work in self.clients:
                    focus_window(self.last_work)
        self.save_live()

    def active_workspace(self):
        ws = suggest().hyprctl_json("activeworkspace")
        name = ws.get("name") if isinstance(ws, dict) else None
        return name if name and WORKSPACE.match(name) else "1"

    def home(self, ws):
        """Where a parked window goes back to: the workspace it opened on,
        else (not known, a left-over) the one you are on."""
        return ws if WORKSPACE.match(ws or "") and not ws.startswith("special:") else self.active_workspace()

    def stop(self):
        """End the block now: timers.py's round (and a break) cancelled; the
        tick then sees it gone and ends it here."""
        t = timers()
        ids = [e["id"] for e in t.load()["timers"] if e.get("kind") in ("focus", "break")]
        for tid in ids:
            t.cancel(tid)
        if self.block:
            self.end("stopped")
        return {"ok": True, "cancelled": len(ids)}

    def end(self, reason):
        """Undo the block: tags, the dim rule, parked windows back, the quiet
        mode it set; then the stats, the digest, the summary, the event."""
        block, self.block = self.block, None
        now = self.clock()
        for addr in list(block["tagged"]):
            tag(addr, False)
        apply_dim(False, number(self.values, "dim_pct"))
        back = []
        for addr, ws in block["parked"].items():
            if move(addr, self.home(ws)):
                back.append(block.get("names", {}).get(addr) or "a window")
        if self.overlay:
            try:
                self.overlay[0].terminate()
            except OSError:
                pass
        self.waiting = []
        if block.get("we_set") == "project":
            try:
                _module("contexts", "contexts.py").focus_project_off()
            except Exception as exc:        # noqa: BLE001
                log(f"project focus could not be turned off: {exc}")
        minutes = max(0.0, (min(now, block["due"]) - block["start"]) / 60)
        if round(minutes) >= 1:
            add_stats(minutes=minutes, blocks=1)
        if block.get("marked"):
            spawn(sys.executable, NOTIFY_DIGEST)
        self.save_live()
        self.clients, self.titles = {}, {}
        self.forget(now)
        automation_event("focus-end")
        log(f"focus block {reason} after {minutes_text(minutes)}")
        if self.values["summary"] == "on" and round(minutes) >= 1:
            threading.Thread(target=self.summary, args=(block, now, reason, back), daemon=True).start()

    def summary(self, block, now, reason, back):
        """The "what you did" notification (in a thread: git and the history
        take a moment)."""
        t0, t1 = block["start"], min(now, block["due"])
        tally, switches, commits = None, None, {}
        try:
            b = brief()
            rows = b.read_activity(ACTIVITY)
            if rows is not None:
                inside = [r for r in rows if t0 - 3600 <= r["t"] < t1]
                tally = b.tally(b.periods(inside, t0, t1, now), b.repo_names())
                switches = sum(1 for r in inside if t0 <= r["t"] < t1)
            email = b.git_email()
            for name in b.repo_names():
                found = b.commits_in(os.path.join(b.PROJECTS, name), t0, t1, email)
                if found:
                    commits[name] = found
        except Exception as exc:        # noqa: BLE001 -- a shorter summary
            log(f"summary: {exc.__class__.__name__}")
        minutes = (t1 - t0) / 60
        lines = summary_lines(tally, switches, commits, back)
        head = f"Focus block {'done' if reason == 'done' else 'stopped'}: {minutes_text(minutes)}"
        actions = []
        if self.values["breaks"] == "off" or reason != "done":
            actions = [("again", f"Focus again ({timers().setting('focus_min')} min)"), ("ok", "OK")]
        picked = notify(head, "\n".join(lines) or "Nothing was logged (the activity history is off).",
                        actions, urgency="normal", wait=600)
        if picked == "again":
            self.post("start", {})

    # -- the loop's pieces ---------------------------------------------------------------------------
    def sync_block(self, now):
        """timers.json against the block: a new focus round is a block
        (begin), the block's round gone or due is its end."""
        try:
            mtime = os.stat(timers().STATE).st_mtime_ns
        except OSError:
            mtime = None
        if self.block and now >= self.block["due"]:
            self.end("done")
            return
        if mtime == self.timers_mtime:
            return
        self.timers_mtime = mtime
        entries = [e for e in self.focus_entries() if e.get("due", 0) > now]
        if self.block and not any(e["id"] == self.block["id"] for e in entries):
            self.end("stopped")
        elif not self.block and entries:
            self.begin(entries[0])

    def resume(self):
        """At the start: a block from before a restart, picked up again (or
        tidied away when its round is gone)."""
        try:
            with open(LIVE) as handle:
                old = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(old, dict) or "id" not in old:
            return
        now = self.clock()
        entry = next((e for e in self.focus_entries() if e["id"] == old["id"] and e.get("due", 0) > now), None)
        if entry:
            self.begin(entry, resumed=old)
            log("picked the focus block up again")
        else:
            self.block = old
            self.end("done" if now >= old.get("due", 0) else "stopped")

    def shutdown(self):
        """The service stops mid-block: give everything back, keep the
        record (a restart picks it up again)."""
        if not self.block:
            return
        for addr in list(self.block["tagged"]):
            tag(addr, False)
        apply_dim(False, number(self.values, "dim_pct"))
        for addr, ws in list(self.block["parked"].items()):
            move(addr, self.home(ws))
        self.block["tagged"], self.block["parked"] = {}, {}
        self.save_live()
        if self.overlay:
            try:
                self.overlay[0].terminate()
            except OSError:
                pass

    def follow_switch(self, now):
        """The noticing switch flipped while running: off forgets the
        history at once (nothing kept once you said no); on seeds it again."""
        on = watch_on()
        if on != self.watching:
            self.watching = on
            self.forget(now)
            if on:
                self.seed(now)

    def tick(self, now):
        self.follow_switch(now)
        self.check_away(now)
        self.context = read_context()
        self.settle(now)
        self.sync_block(now)
        if not self.block:
            self.maybe_offer(now)

    def status(self):
        now = self.clock()
        out = {"watching": watch_on(), "block": None, "numbers": self.numbers(now),
               "quiet": self.quiet_reason(now) if not self.block else "in a focus block",
               "last_offer": self.last_offer}
        if self.block:
            out["block"] = {"start": self.block["start"], "due": self.block["due"], "quiet": self.block["quiet"],
                            "dimmed": len(self.block["tagged"]), "waiting": len(self.block["parked"])}
        return out

    def request(self, msg):
        op = msg.get("op")
        if op == "start":
            return self.start(msg.get("minutes"), bool(msg.get("suggested")))
        if op == "stop":
            return self.stop()
        if op == "status":
            return self.status()
        if op == "reload":
            self.reload()
            return {"ok": True}
        if op == "sample":
            if self.overlay:
                return {"error": "a card is up"}
            kind = msg.get("kind") if msg.get("kind") in ("app", "site") else "app"
            self.show_overlay(sample_card(kind, number(self.values, "delay_s")))
            return {"ok": True}
        return {"error": f"no op {op!r}"}

    def drain(self):
        while True:
            try:
                op, arg = self.inbox.get_nowait()
            except queue.Empty:
                return
            if op == "start":
                reply = self.start(arg.get("minutes"), arg.get("suggested", False))
                if reply.get("error"):
                    log(reply["error"])


def sample_card(kind, delay_s):
    return {"kind": kind, "addr": "0x0000", "name": "Discord" if kind == "app" else "YouTube",
            "left_min": 18, "delay_s": delay_s, "sample": True}


def serve():
    """The loop: Hyprland's events, focus-guard.sock, the card's stdout, the
    notification threads' inbox, SIGTERM / SIGUSR1 (reload) and the tick."""
    s = suggest()
    wake_r, wake_w = socket.socketpair()
    wake_r.setblocking(False)
    wake_w.setblocking(False)
    flags = {"reload": False, "stop": False}

    def on_signal(signum, _frame):
        flags["stop" if signum == signal.SIGTERM else "reload"] = True
    signal.signal(signal.SIGUSR1, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    signal.set_wakeup_fd(wake_w.fileno())
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        server.bind(SOCK)
    finally:
        os.umask(old)
    server.listen(4)
    daemon = Daemon()
    daemon.wake = wake_w
    daemon.context = read_context()
    daemon.seed(daemon.clock())
    daemon.resume()
    log("running (noticing: " + ("on" if watch_on() else "off") + f", style {daemon.values['style']})")
    hypr_sock, buf, next_tick = None, b"", 0.0
    try:
        while not flags["stop"]:
            if hypr_sock is None:
                hypr_sock, buf = s.connect_events(HYPR_EVENTS), b""
            now = daemon.clock()
            waits = [next_tick - now, 2.0 if hypr_sock is None else TICK_S]
            if daemon.pending:
                waits.append(daemon.pending[0] + DWELL_S - now)
            if daemon.waiting and not daemon.overlay:
                waits.append(0.2)
            watch = [wake_r, server] + ([hypr_sock] if hypr_sock else []) + \
                ([daemon.overlay[0].stdout] if daemon.overlay else [])
            try:
                ready, _, _ = select.select(watch, [], [], max(0.05, min(waits)))
            except InterruptedError:
                ready = []
            if wake_r in ready:
                try:
                    while wake_r.recv(64):
                        pass
                except BlockingIOError:
                    pass
            if flags["reload"]:
                flags["reload"] = False
                daemon.reload()
            daemon.drain()
            if hypr_sock is not None and hypr_sock in ready:
                try:
                    chunk = hypr_sock.recv(65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    hypr_sock.close()
                    hypr_sock = None
                else:
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        daemon.event(line.decode("utf-8", "replace"))
            if server in ready:
                s.handle_client(server, daemon)
            if daemon.overlay and daemon.overlay[0].stdout in ready:
                daemon.overlay_output()
            now = daemon.clock()
            daemon.settle(now)
            if now >= next_tick:
                next_tick = now + TICK_S
                daemon.tick(now)
            daemon.maybe_card()
    finally:
        daemon.shutdown()
        try:
            os.unlink(SOCK)
        except OSError:
            pass


# -- the card ------------------------------------------------------------------------------------------
def overlay(render=None):
    """"Still want Discord?": a card in the middle of the focused screen.
    Not now / Back to work at once; Open it / Keep it after delay_s. Never
    takes the keyboard. Prints {"result": ...} and goes."""
    card = json.loads(sys.stdin.read() or "{}")
    if not card:
        return
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    import panelui
    panelui.load_css()
    said = {"done": False}

    def say(result):
        if not said["done"]:
            said["done"] = True
            print(json.dumps({"result": result}), flush=True)

    if render:
        win = Gtk.OffscreenWindow()
    else:
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell
        win = Gtk.Window()
        win.set_app_paintable(True)
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "waybar-panel")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        mon = suggest()._focused_monitor(Gdk)
        if mon:
            GtkLayerShell.set_monitor(win, mon)
    win.set_name("panel-window")
    site = card.get("kind") == "site"
    name = card.get("name") or "this"
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_name("panel")
    box.set_size_request(420, -1)
    win.add(box)
    line = Gtk.Box(spacing=12)
    box.pack_start(line, False, False, 0)
    icon = Gtk.Label(label=ICON)
    icon.get_style_context().add_class("ctl-icon")
    icon.set_valign(Gtk.Align.START)
    line.pack_start(icon, False, False, 0)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    line.pack_start(texts, True, True, 0)
    head = Gtk.Label(label=f"Still want {name}?", xalign=0)
    head.get_style_context().add_class("kb-heading")
    texts.pack_start(head, False, False, 0)
    left = card.get("left_min") or 0
    body_text = (f"You are in a focus block ({left} min left). "
                 + (f"{name} stays open; it is only a pause to choose." if site else
                    f"{name} is waiting out of sight; it comes back by itself when the block ends."))
    if card.get("sample"):
        body_text = "A sample: the buttons do nothing. " + body_text
    body = Gtk.Label(label=body_text, xalign=0)
    body.get_style_context().add_class("ctl-sub")
    body.set_line_wrap(True)
    body.set_max_width_chars(58)
    texts.pack_start(body, False, False, 0)
    row = Gtk.Box(spacing=6)
    row.set_halign(Gtk.Align.END)
    box.pack_start(row, False, False, 0)
    no = Gtk.Button(label="Back to work" if site else "Not now")
    yes_word = "Keep it" if site else "Open it"
    yes = Gtk.Button(label=f"{yes_word} ({card.get('delay_s', 10)})")
    yes.set_sensitive(False)
    for b in (no, yes):
        b.get_style_context().add_class("dev-pick")
        row.pack_start(b, False, False, 0)
    count = {"left": int(card.get("delay_s") or 10)}

    def quit_():
        Gtk.main_quit()
        return False

    def tick():
        count["left"] -= 1
        if count["left"] <= 0:
            yes.set_label(yes_word)
            yes.set_sensitive(True)
            return False
        yes.set_label(f"{yes_word} ({count['left']})")
        return True

    if render:
        win.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        pix = win.get_pixbuf()
        if pix:
            pix.savev(render, "png", [], [])
        return
    no.connect("clicked", lambda _b: (say("back" if site else "later"), quit_()))
    yes.connect("clicked", lambda _b: (say("keep" if site else "open"), quit_()))
    win.connect("delete-event", lambda *_a: quit_())
    signal.signal(signal.SIGTERM, lambda *_a: GLib.idle_add(quit_))
    GLib.timeout_add_seconds(1, tick)
    GLib.timeout_add_seconds(OVERLAY_WAIT_S, lambda: (say("later"), quit_())[1])
    win.show_all()
    Gtk.main()
    say("later")


# -- the command line -----------------------------------------------------------------------------------
def ask_daemon(msg, timeout=3.0):
    return suggest().ask_daemon(msg, timeout=timeout, path=SOCK)


def service_state():
    def ask(verb):
        try:
            return subprocess.run(["systemctl", "--user", verb, UNIT], capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return ask("is-enabled") == "enabled", ask("is-active") == "active"


def get_settings(today=None):
    values = read_settings()
    enabled, running = service_state()
    t = timers().settings()
    today = today or dt.date.today()
    live = ask_daemon({"op": "status"}, timeout=1.5) if running else None
    week = recent_stats(7, today)
    return {"on": running, "enabled": enabled, "values": values, "watching": watch_on(),
            "timers": {k: t[v] for k, v in TIMER_KEYS.items()}, "live": live,
            "today": week[-1], "week": week,
            "apps": items(values, "apps"), "sites": items(values, "sites"), "choices": CHOICES,
            "limits": {k: list(v) for k, v in LIMITS.items()}, "dim_rule": os.path.exists(
                os.path.expanduser("~/.config/hypr/lua/focusguard.lua"))}


def set_setting(args):
    if len(args) == 1 and args[0] in ("on", "off"):
        res = subprocess.run(["systemctl", "--user", "enable" if args[0] == "on" else "disable", "--now", UNIT],
                             capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            sys.exit(f"focus-guard: {res.stderr.strip() or 'systemctl failed'}")
        return
    if len(args) == 2 and args[0] == "detect" and args[1] in ("on", "off"):
        privacy().set_key("focus_watch", args[1])
        ask_daemon({"op": "reload"}, timeout=1)
        return
    if len(args) == 2 and args[0] in TIMER_KEYS:
        try:
            timers().set_setting(TIMER_KEYS[args[0]], args[1])
        except ValueError as err:
            sys.exit(f"focus-guard: {err}")
        return
    if len(args) != 2 or args[0] not in DEFAULTS:
        sys.exit("focus-guard: set on|off | detect on|off | set KEY VALUE (" + ", ".join(
            list(DEFAULTS) + list(TIMER_KEYS)) + ")")
    try:
        write_setting(args[0], args[1])
    except ValueError as err:
        sys.exit(f"focus-guard: {err}")
    ask_daemon({"op": "reload"}, timeout=1)


def edit_list(key, verb, word):
    values = read_settings()
    words = items(values, key)
    word = " ".join(word.lower().split())
    if verb == "add":
        if not LISTS[key].match(word):
            sys.exit(f"focus-guard: {word!r} is not a {'window class' if key == 'apps' else 'site word'}")
        if word not in words:
            words.append(word)
    elif verb == "remove":
        words = [w for w in words if w != word]
    else:
        sys.exit(f"focus-guard: {key} add|remove WORD")
    write_setting(key, ",".join(words))
    ask_daemon({"op": "reload"}, timeout=1)


def start_cli(args):
    minutes = next((int(a) for a in args if a.isdigit()), None)
    suggested = "--suggested" in args
    reply = ask_daemon({"op": "start", "minutes": minutes, "suggested": suggested}, timeout=10)
    if reply is None:           # not running: timers.py's own round
        t = timers()
        t.start_focus(minutes, guard=False)
        print("focus round started (focus guard is off: no dimming)")
        return
    if reply.get("error"):
        sys.exit(f"focus-guard: {reply['error']}")
    print(f"focus block: {reply['minutes']} min, quiet: {reply['quiet']}")


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "daemon":
        serve()
    elif cmd == "start":
        start_cli(args)
    elif cmd == "stop":
        reply = ask_daemon({"op": "stop"}, timeout=10)
        if reply is None:
            t = timers()
            for e in t.load()["timers"]:
                if e.get("kind") in ("focus", "break"):
                    t.cancel(e["id"])
    elif cmd == "toggle":
        now = time.time()
        running = any(e.get("kind") in ("focus", "break") and e.get("due", 0) > now
                      for e in timers().load()["timers"])
        main(["stop"] if running else ["start"])
        spawn(NOTIFY, "-a", APP, "-u", "low", "-t", "2500",
              "Focus block stopped" if running else "Focus block started")
    elif cmd == "status":
        reply = ask_daemon({"op": "status"}, timeout=2)
        if "--json" in args:
            print(json.dumps(reply))
        elif reply is None:
            print("focus guard: not running")
        else:
            b, n = reply.get("block"), reply["numbers"]
            print(("in a block until " + dt.datetime.fromtimestamp(b["due"]).strftime("%H:%M")
                   + f" ({b['quiet']}, {b['dimmed']} dimmed, {b['waiting']} waiting)") if b else
                  f"noticing: {'on' if reply['watching'] else 'off'}  quiet: {reply['quiet'] or 'no'}")
            print(f"last {n['window_s'] // 60} min: {n['switches']} switches ({n['weighted']} weighted, "
                  f"{n['need']} needed), {n['groups']} groups ({n['need_groups']} needed)")
    elif cmd == "check":
        reply = ask_daemon({"op": "status"}, timeout=2)
        n = (reply or {}).get("numbers")
        print(json.dumps(n) if "--json" in args else (n and f"{n}") or "focus guard: not running")
    elif cmd == "get":
        data = get_settings()
        if "--json" in args:
            print(json.dumps(data))
        else:
            v = data["values"]
            print(f"focus guard: {'on' if data['on'] else 'off'}  noticing: {'on' if data['watching'] else 'off'}")
            print("  " + "  ".join(f"{k}={v[k]}" for k in DEFAULTS if k not in LISTS))
            print(f"  apps: {', '.join(data['apps']) or '-'}\n  sites: {', '.join(data['sites']) or '-'}")
            print(f"  today: {minutes_text(data['today']['minutes'])} in {int(data['today']['blocks'])} blocks")
    elif cmd == "set":
        set_setting(args)
    elif cmd in LISTS and len(args) == 2:
        edit_list(cmd, args[0], args[1])
    elif cmd == "stats":
        days = next((int(a) for a in args if a.isdigit()), 7)
        rows = recent_stats(max(1, min(days, STATS_DAYS)))
        if "--json" in args:
            print(json.dumps(rows))
        else:
            for r in rows:
                print(f"{r['day']}  {minutes_text(r['minutes']):>12}  {int(r['blocks'])} blocks  "
                      f"offered {int(r['offered'])}, taken {int(r['taken'])}")
    elif cmd == "sample":
        kind = args[0] if args and args[0] in ("app", "site") else "app"
        if ask_daemon({"op": "sample", "kind": kind}) is None:
            proc = subprocess.Popen([sys.executable, SELF, "overlay"], stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, start_new_session=True)
            proc.stdin.write(json.dumps(sample_card(kind, number(read_settings(), "delay_s"))).encode())
            proc.stdin.close()
    elif cmd == "overlay":
        render = args[args.index("--render") + 1] if "--render" in args and len(args) > 1 else None
        overlay(render)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
