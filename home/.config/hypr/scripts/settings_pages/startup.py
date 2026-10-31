"""Settings page: what starts with the session (startup.py).

Four lists, top to bottom in the order you are likely to touch them:

    Desktop services   the desktop's systemd user services (the bar, the
                       launcher, notifications, the clipboard, ...): what each
                       does, whether it runs and for how long, a switch for
                       "start at login" and a Restart. The essential ones wear
                       a lock instead of a switch -- turning the bar or the
                       idle lock off by a stray click is not a setting
                       anyone wants; startup.py disable <unit> --force does it
                       on purpose.
    Timers             the desktop's own timers (day / night theme, calendar
                       alarms, the dotfiles backup): when they run, the next
                       and the last run, a switch and "Run now".
    Apps at login      XDG autostart entries (/etc/xdg/autostart and
                       ~/.config/autostart): a switch for the ones that can
                       start here, the rest folded away with the reason
                       (GNOME-only, not installed, ...).
    Hyprland itself    the exec lines in lua/autostart.lua and the lua timers,
                       read-only: changing them is editing the config. Each
                       has a readable title (exec_title) over when it runs
                       (the command, file and comment on hover), and one
                       command run at two moments is one row.

Sub lines stay short (state, schedule); unit names, memory, owners and
commands are in each row's tooltip, the config file link in a Details fold.

Every control runs startup.py (enable / disable / restart / run / autostart
on|off) in a thread and then redraws from what it reports; the page keeps
nothing of its own. Switches survive a reload and a re-login because they
ARE systemd's enable links and the ~/.config/autostart overrides.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "startup", "title": "Startup & automations", "icon": "", "group": "System", "order": 60, "tab": "Startup",
        "keywords": ["autostart", "login", "startup apps", "start at login", "services", "systemd",
                     "background", "daemons", "timers", "boot", "inicio"]}

STARTUP = os.path.join(HYPR, "startup.py")
LOCK, GEAR, CLOCK, ROCKET, TERMINAL, WARN = "", "", "", "", "", ""


# -- words (pure: tests/test_settings_startup.py) -------------------------------------------
def duration(seconds):
    """3 min / 2 h / 4 days -- how long something has been running."""
    if seconds is None:
        return ""
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    if seconds < 172800:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} days"


def size(nbytes):
    if not nbytes:
        return ""
    return f"{nbytes / 1048576:.0f} MB" if nbytes < 1 << 30 else f"{nbytes / (1 << 30):.1f} GB"


def when(epoch, now=None):
    """A time near now in plain words: "21:30 (in 18 h)", "yesterday 21:30",
    "Mon 09:00"."""
    if not epoch:
        return ""
    now = now if now is not None else time.time()
    t, n = time.localtime(epoch), time.localtime(now)
    days = (time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)) -
            time.mktime((n.tm_year, n.tm_mon, n.tm_mday, 0, 0, 0, 0, 0, -1))) / 86400
    days = round(days)
    clock = time.strftime("%H:%M", t)
    day = ("" if days == 0 else "tomorrow " if days == 1 else "yesterday " if days == -1 else
           time.strftime("%a ", t) if abs(days) < 7 else time.strftime("%d %b ", t))
    delta = epoch - now
    rel = ""
    if 0 < delta < 86400:
        rel = f" (in {duration(int(delta))})"
    elif -86400 < delta <= 0:
        rel = f" ({duration(int(-delta))} ago)"
    return f"{day}{clock}{rel}"


def service_sub(s):
    """The grey line under a service: what it is doing, for how long, its
    restarts, and the last log line only when it is not running as it
    should."""
    bits = [s["state"] + (f" for {duration(s['since_s'])}" if s.get("since_s") is not None
                          and s["state"] == "running" else "")]
    if s.get("restarts"):
        bits.append(f"restarted {s['restarts']}×")
    if not s["enabled"]:
        bits.append("off at login")
    text = "  ·  ".join(b for b in bits if b)
    if s.get("log") and not s.get("ok", True):
        text += "\n" + short_why(s["log"], 70)
    return text


def service_tip(s):
    """The hover text of a service row: its unit, memory, owner, why it is
    essential, its last log line."""
    bits = [s["unit"], size(s.get("memory")), s["owner"]]
    text = "  ·  ".join(b for b in bits if b)
    if s.get("essential"):
        text += f"\nEssential: {s['essential']}"
    if s.get("log"):
        text += f"\nLast log: {s['log']}"
    return text


def timer_sub(t, now=None):
    bits = [t["schedule"]]
    if t["on"] and t.get("next"):
        bits.append("next " + when(t["next"], now))
    elif not t["on"]:
        bits.append("off")
    if t.get("job_running"):
        bits.append("running now")
    elif t.get("last"):
        result = t.get("job_result")
        bits.append("last " + when(t["last"], now) + ("" if result in ("", "success") else f" ({result})"))
    else:
        bits.append("not run yet")
    return "  ·  ".join(bits)


def timer_tip(t):
    """The hover text of a timer row: the job it runs, how it is switched,
    its note."""
    lines = []
    if t.get("job_title"):
        lines.append(f"Runs: {t['job_title']} ({t['job']})")
    if t.get("route"):
        lines.append(f"Switched through {t['route']}")
    if t.get("note"):
        lines.append(t["note"])
    return "\n".join(lines)


def autostart_sub(e):
    if e["on"]:
        state = "running" if e.get("running") else "not running now"
    else:
        state = e["reason"] or "off"
    if e.get("comment") and e["comment"] != e["name"]:
        return short_why(e["comment"], 50) + "  ·  " + state
    return state


def short_why(text, limit=180):
    """The first sentence or two of a comment block, for the sub line."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = cut.rfind(". ")
    return (cut[:stop + 1] if stop > 60 else cut.rsplit(" ", 1)[0] + "…")


# Friendly titles for the exec lines, by the program they run (the command
# itself goes on the line under the title).
EXEC_TITLES = {
    "fcitx5": "Input method (fcitx5)",
    "plugins-check.sh": "Plugin check after a Hyprland update",
    "nightlight.sh": "Night light schedule",
    "hyprpaper": "Wallpaper",
    "wallpaper-slideshow.py": "Wallpaper slideshow",
    "waybar": "The bar",
    "hypridle": "Idle lock and screen off",
    "mako": "Notifications",
    "cliphist": "Clipboard history",
    "hyprpolkitagent": "Password prompts (polkit agent)",
}


def exec_program(cmd):
    """The program an exec line runs: "python3 ~/x/foo.py watch" -> "foo.py",
    "wl-paste --watch cliphist store" -> "cliphist"."""
    words = cmd.split()
    if not words:
        return ""
    if "--watch" in words and words.index("--watch") + 1 < len(words):
        return os.path.basename(words[words.index("--watch") + 1])
    if words[0] in ("python3", "python", "bash", "sh") and len(words) > 1:
        return os.path.basename(words[1])
    if words[:2] == ["systemctl", "--user"] and len(words) > 3:
        return words[3]
    return os.path.basename(words[0])


def exec_title(cmd):
    """A readable title for an exec line: EXEC_TITLES, else the program's
    name without its extension, dashes as spaces ("Workspace tint")."""
    prog = exec_program(cmd)
    if prog in EXEC_TITLES:
        return EXEC_TITLES[prog]
    name = prog.rsplit(".", 1)[0] if prog.endswith((".py", ".sh")) else prog
    return name.replace("-", " ").replace("_", " ").capitalize() or cmd


def merge_exec(rows):
    """The exec rows with the same command from the same file folded into
    one (nightlight.sh auto runs 3 s after a load AND every 5 min: one row,
    "3 s after every config load, and every 5 min"). Order is kept."""
    merged, seen = [], {}
    for r in rows:
        key = (r["cmd"], r["file"], r.get("fallback"))
        if key in seen:
            first = seen[key]
            if r["when"] not in first["when"]:
                first["when"] += ", and " + r["when"]
            first["running"] = first["running"] or r["running"]
            if r.get("why") and r["why"] != first.get("why") and not first.get("why"):
                first["why"] = r["why"]
            continue
        seen[key] = dict(r)
        merged.append(seen[key])
    return merged


def own_unit(cgroup_text=None):
    """The systemd unit this Settings window runs inside, from
    /proc/self/cgroup ("0::/user.slice/.../waybar-toolbox.service" ->
    "waybar-toolbox.service"), or "" for a scope / no unit. Opened from the
    toolbox, Settings is a child of waybar-toolbox.service, so restarting that
    unit closes this very window; the Restart button asks first then.
    (waybar.service no longer takes the toolbox along: the toolbox runs
    without the top bar too, scripts/dock.py TOP BAR OFF.)"""
    if cgroup_text is None:
        try:
            with open("/proc/self/cgroup") as handle:
                cgroup_text = handle.read()
        except OSError:
            return ""
    for line in cgroup_text.splitlines():
        if line.startswith("0::"):
            leaf = line[3:].rstrip("/").rsplit("/", 1)[-1]
            return leaf if leaf.endswith(".service") else ""
    return ""


def hits_me(s, me):
    """Does restarting service row `s` restart the unit `me` too?"""
    return bool(me) and (s["unit"] == me or me in s.get("parts", []))


def call(*cmd, timeout=40):
    """Run a startup.py command: "" when it worked, else what it said (its
    stderr's last line), so the page can show why a switch did not move."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if done.returncode == 0:
        return ""
    lines = [l.strip() for l in done.stderr.splitlines() if l.strip()]
    return (lines[-1] if lines else f"exit status {done.returncode}").removeprefix("startup.py: ")


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)
    lab.set_line_wrap(True)
    lab.set_max_width_chars(90)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.summary, self.summary_sub = row(ROCKET, "Startup & background", "checking…")
        w.pack_start(self.summary, False, False, 0)
        w.pack_start(links_row(link("Check again", self.refresh)), False, False, 0)
        w.pack_start(sep(), False, False, 0)
        self.sections = {}
        for key, title, note in (
                ("services", "DESKTOP SERVICES",
                 "Start at login, restart if they crash. A lock marks essential ones."),
                ("timers", "TIMERS",
                 "Jobs that run on a schedule while you are logged in."),
                ("autostart", "APPS AT LOGIN",
                 "Off here means off in Hyprland only."),
                ("exec", "STARTED BY HYPRLAND",
                 "Read-only: lines in the Hyprland config."),
                ("other", "THE REST OF THE SESSION",
                 "Fedora's own background services, shown for reference.")):
            w.pack_start(heading(title), False, False, 0)
            w.pack_start(wrapped(note), False, False, 0)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            w.pack_start(box, False, False, 0)
            if key != "other":
                w.pack_start(sep(), False, False, 0)
            self.sections[key] = box
        self.updating = False
        self.busy = set()
        self.error = ""          # the last command's complaint, shown once in the summary
        self.armed = ""          # the unit whose "Restart (closes Settings)" waits for a second click
        self.me = own_unit()

    # -- reading --------------------------------------------------------------------------
    def refresh(self):
        for box in self.sections.values():
            if not box.get_children():
                box.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
                box.show_all()
        background(lambda: run_json(STARTUP, "list", "--json", timeout=30), self.show)

    def later(self, ms=900):
        GLib.timeout_add(ms, lambda: (self.refresh(), False)[1])

    def show(self, data):
        if not data:
            for box in self.sections.values():
                clear(box)
            self.summary_sub.set_text("Could not read the startup list")
            self.summary_sub.set_tooltip_text(f"Try it in a terminal: {STARTUP} list")
            self.widget.show_all()
            return
        self.updating = True
        svc, tim, auto = data["services"], data["timers"], data["autostart"]
        running = sum(1 for s in svc if s["state"] == "running")
        bad = [s for s in svc if not s["ok"]]
        apps_on = sum(1 for e in auto if e["on"])
        summary = (f"{running} services running  ·  {sum(1 for t in tim if t['on'])} of {len(tim)} timers on  ·  "
                   f"{apps_on} login app{'s' if apps_on != 1 else ''}")
        if bad:
            summary += f"\n{len(bad)} not running as expected (top of the list)"
        if self.error:
            summary += f"\nDid not work: {self.error}"
            self.error = ""
        self.summary_sub.set_text(summary)
        self.show_services(svc)
        self.show_timers(tim, data.get("other", {}))
        self.show_autostart(auto)
        self.show_exec(data["exec"], data.get("uwsm", True))
        self.show_other(data.get("other", {}))
        self.widget.show_all()
        self.updating = False

    def end_widget(self, *items):
        box = Gtk.Box(spacing=8)
        for item in items:
            if item is not None:
                item.set_valign(Gtk.Align.CENTER)
                box.pack_start(item, False, False, 0)
        return box

    def switch(self, state, on_toggle, key):
        sw = Gtk.Switch()
        sw.set_state(state)
        sw.set_sensitive(key not in self.busy)
        sw.connect("state-set", lambda _s, new: self.toggled(key, new, on_toggle))
        return sw

    def show_services(self, rows):
        box = self.sections["services"]
        clear(box)
        rows = sorted(rows, key=lambda s: (s["ok"], not s["essential"], s["title"].lower()))
        for s in rows:
            if s["essential"] and s["enabled"]:
                lock = dp.label(LOCK, "ctl-value", 0.5)
                lock.set_tooltip_text(f"Essential: {s['essential']}.\nOn purpose, from a terminal: "
                                      f"startup.py disable {s['unit']} --force")
                control = lock
            else:
                control = self.switch(s["enabled"], lambda on, u=s["unit"]: call(
                    STARTUP, "enable" if on else "disable", u), s["unit"])
            restart = None
            if not s["oneshot"]:
                if hits_me(s, self.me):
                    armed = self.armed == s["unit"]
                    restart = link("Click again: this closes Settings" if armed else "Restart…",
                                   lambda u=s["unit"]: self.confirm_restart(u))
                    restart.set_tooltip_text(f"This Settings window runs inside {self.me} (it was opened from "
                                             "the toolbox), so the restart closes it too.")
                else:
                    restart = link("Restart", lambda u=s["unit"]: self.act(u, STARTUP, "restart", u))
            icon = WARN if not s["ok"] else (LOCK if s["essential"] else GEAR)
            grid, _ = row(icon, s["title"], service_sub(s), self.end_widget(restart, control))
            grid.set_tooltip_text(service_tip(s))
            box.pack_start(grid, False, False, 0)

    def show_timers(self, rows, other):
        box = self.sections["timers"]
        clear(box)
        now = time.time()
        for t in rows:
            control = self.switch(t["on"], lambda on, u=t["unit"]: call(
                STARTUP, "enable" if on else "disable", u), t["unit"])
            run_now = link("Run now", lambda u=t["unit"]: self.act(u, STARTUP, "run", u))
            grid, _ = row(CLOCK, t["title"], timer_sub(t, now), self.end_widget(run_now, control))
            if timer_tip(t):
                grid.set_tooltip_text(timer_tip(t))
            box.pack_start(grid, False, False, 0)
        alarms = other.get("alarms", 0)
        if alarms:
            box.pack_start(dp.label(f"Plus {alarms} clock timer{'s' if alarms != 1 else ''} / alarm"
                                    f"{'s' if alarms != 1 else ''} you set.", "ctl-sub"), False, False, 0)

    def show_autostart(self, rows):
        box = self.sections["autostart"]
        clear(box)
        usable = [e for e in rows if e["switchable"]]
        rest = [e for e in rows if not e["switchable"]]
        if not usable:
            box.pack_start(dp.label("No autostart apps can start in Hyprland.", "ctl-sub"), False, False, 0)
        for e in usable:
            control = self.switch(e["on"], lambda on, i=e["id"]: call(
                STARTUP, "autostart", "on" if on else "off", i), e["id"])
            grid, _ = row(ROCKET, e["name"], autostart_sub(e), control)
            grid.set_tooltip_text(f"{e['id']}  ·  {e['where']}")
            box.pack_start(grid, False, False, 0)
        if rest:
            exp = Gtk.Expander(label=f"Not for this desktop ({len(rest)})")
            exp.get_style_context().add_class("ctl-sub")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.set_margin_start(12)
            for e in rest:
                inner.pack_start(wrapped(f"{e['name']}  ·  {e['reason']}  ·  {e['id']}"), False, False, 0)
            exp.add(inner)
            box.pack_start(exp, False, False, 0)

    def show_exec(self, rows, uwsm):
        box = self.sections["exec"]
        clear(box)
        for r in merge_exec([r for r in rows if not r["fallback"]]):
            state = "running now" if r["running"] else "not running now"
            grid, _ = row(TERMINAL, exec_title(r["cmd"]), f"{r['when']}  ·  {state}")
            tip = f"{r['cmd']}\n{r['file']}" + (f"\n{short_why(r['why'])}" if r["why"] else "")
            grid.set_tooltip_text(tip)
            box.pack_start(grid, False, False, 0)
        fold = details(links_row(link("Open lua/autostart.lua", lambda: spawn(
            "xdg-open", os.path.expanduser("~/.config/hypr/lua/autostart.lua")))))
        fallback = [r["cmd"] for r in rows if r["fallback"]]
        if fallback:
            names = ", ".join(dict.fromkeys(exec_title(c).lower() for c in fallback))
            sub = (f"{len(fallback)} commands: {names}.  " +
                   ("Not used now: this session runs under uwsm, so the services above start them."
                    if uwsm else "IN USE NOW: this is a plain Hyprland session (no uwsm), so the services above "
                    "do not run and these do -- without restarts if one crashes."))
            grid, _ = row(TERMINAL, "Fallback daemons (plain Hyprland session only)", sub)
            # in use only without uwsm: then it matters and stays on the page
            (fold.box.pack_start if uwsm else box.pack_start)(grid, False, False, 0)
        box.pack_start(fold, False, False, 0)

    def show_other(self, other):
        box = self.sections["other"]
        clear(box)
        svcs = other.get("services", [])
        timers = other.get("timers", [])
        exp = Gtk.Expander(label=f"{len(svcs)} services running, {len(timers)} timers")
        exp.get_style_context().add_class("ctl-sub")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        inner.set_margin_start(12)
        for s in svcs:
            text = s["description"] if s["description"] and s["description"] != s["unit"] else ""
            inner.pack_start(wrapped(f"{s['unit']}" + (f"  ·  {text}" if text else "")), False, False, 0)
        for t in timers:
            inner.pack_start(wrapped(f"{t}  ·  timer"), False, False, 0)
        exp.add(inner)
        box.pack_start(exp, False, False, 0)

    # -- changing -------------------------------------------------------------------------
    def toggled(self, key, state, on_toggle):
        if self.updating or key in self.busy:
            return True
        self.busy.add(key)
        self.summary_sub.set_text("switching " + key + " " + ("on" if state else "off") + "…")
        background(lambda: on_toggle(state), lambda err: self.done(err, key, 300))
        return True     # the switch moves when the redraw says it did

    def act(self, key, *cmd):
        self.summary_sub.set_text(f"{cmd[1] if len(cmd) > 1 else ''} {key}…")
        background(lambda: call(*cmd), lambda err: self.done(err, None, 1200))

    def done(self, err, key, ms):
        self.busy.discard(key)
        self.error = err or ""
        self.later(ms)

    def confirm_restart(self, unit):
        """First click arms, second click restarts (and closes this window);
        the arming lapses after 6 s."""
        if self.armed == unit:
            self.armed = ""
            self.act(unit, STARTUP, "restart", unit)
            return
        self.armed = unit
        self.refresh()
        GLib.timeout_add(6000, lambda: (self.disarm(unit), False)[1])

    def disarm(self, unit):
        if self.armed == unit:
            self.armed = ""
            self.refresh()
