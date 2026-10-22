"""Settings page: idle timings and screen lock (hypridle.conf), Keep awake, the
power profile, and Lock / Suspend / Log out / Restart / Shut down.

Everything goes through ~/.config/hypr/scripts/idle-settings.py, which writes
hypridle.conf (the only place the timings are kept) and restarts hypridle; the
page reads `idle-settings.py status` back after every change. The session
buttons are the power panel's own (waybar/scripts/power_panel.py): the same
commands, tiles and two-click Confirmer, so the bar's power menu and this page
can never disagree about what "Log out" runs. Here every one of them takes two
clicks, Lock and Suspend too: a settings window is somewhere you click around,
and a stray click should not put the computer to sleep. POWER_PANEL_DRYRUN=1
turns them into notifications, as in the panel.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import power_panel as pp  # noqa: E402  (waybar/scripts, on the path via common)

PAGE = {"id": "power", "title": "Power & screen lock", "icon": "", "group": "System", "order": 20,
        "keywords": ["idle", "dim", "lock", "screen lock", "lock screen", "screens off", "timeout", "suspend",
                     "sleep", "keep awake", "caffeine", "power profile", "performance", "power saver",
                     "balanced", "power button", "lid", "log out", "restart", "reboot", "shut down", "apagar",
                     "session"]}

IDLE = os.path.join(HYPR, "idle-settings.py")
SCREEN_COLOR = os.path.join(HYPR, "screen-color.py")

# (key, icon, title, what it does, choices in seconds; 0 = never). A value in
# hypridle.conf that is none of these (a hand edit) gets a chip of its own.
TIMINGS = [
    ("dim", "", "Dim the screens", "after this long without input, every screen goes darker until you "
     "move the mouse or press a key", [0, 120, 300, 600, 900]),
    ("lock", "", "Lock the screen", "after this long without input; SUPER+ALT+L locks at once",
     [0, 300, 600, 900, 1800, 3600]),
    ("screens_off", "", "Turn the screens off", "after this long without input; any input wakes them",
     [0, 300, 600, 900, 1800, 3600]),
    ("suspend", "", "Suspend", "put the computer to sleep after this long without input; downloads, "
     "games and anything running stop until it wakes", [0, 1800, 3600, 7200, 10800]),
]
AFTER_LOCK = [0, 10, 30, 60, 300]
GRACE = [0, 3, 5, 10, 30]
DIM_LEVEL = [20, 40, 60]
AWAKE = [("off", "Off"), ("60", "1 hour"), ("180", "3 hours"), ("on", "Until I turn it off")]
PROFILE_TEXT = {"power-saver": "Power saver", "balanced": "Balanced", "performance": "Performance"}
PROFILE_SUB = {"power-saver": "quieter and cooler, the CPU holds back",
               "balanced": "fast when there is work, frugal when idle",
               "performance": "the CPU runs at full speed sooner; more heat and fan noise"}
POWER_KEY = [("poweroff", "Shut down"), ("suspend", "Suspend"), ("lock", "Lock"), ("ignore", "Nothing")]


def dur(s):
    """600 -> "10 min", 630 -> "10½ min", 0 -> "Never"."""
    if not s:
        return "Never"
    if s < 60:
        return f"{s} s"
    if s % 3600 == 0:
        return f"{s // 3600} h"
    if s % 60 == 30:
        return f"{s // 60}½ min"
    if s % 60:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 60} min"


def choices(options, current):
    """(key, caption) chips for a list of seconds, plus the current value when
    it is not one of them, kept in order."""
    values = sorted(set(options) | {current}, key=lambda s: (s != 0, s))
    return [(str(s), dur(s)) for s in values]


def attempt(*cmd, timeout=20):
    """Run one of the backend commands; "" when it worked, else what it said
    on stderr (its own readable message: idle-settings.py exits with one), so
    the page can show why a click did nothing -- a refused profile switch, a
    hypridle that would not restart. Called from background() only."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def power_key_command(action):
    """The root step for changing what the power button does: a logind drop-in,
    then logind re-reads its config (HUP; a restart would end the session)."""
    return ("sudo mkdir -p /etc/systemd/logind.conf.d && printf '[Login]\\nHandlePowerKey=%s\\n' "
            f"{action} | sudo tee /etc/systemd/logind.conf.d/50-power-key.conf >/dev/null && "
            "sudo systemctl kill -s HUP systemd-logind")


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        # The last command that failed, shown at the top until the next one
        # works; set by done(), drawn by show().
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        w.pack_start(heading("WHEN YOU STEP AWAY"), False, False, 0)
        self.chips, self.subs = {}, {}
        for key, icon, title, sub, _opts in TIMINGS:
            grid, self.subs[key] = row(icon, title, sub)
            w.pack_start(grid, False, False, 0)
            self.chips[key] = self.make_chips(lambda k, key=key: self.set(key, f"{k}s" if k != "0" else "never"))
            w.pack_start(self.chips[key].widget, False, False, 0)
            if key == "dim":
                self.dim_level = self.make_chips(lambda k: self.set("dim_level", k))
                w.pack_start(self.dim_level.widget, False, False, 0)
        self.problems = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.problems, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SCREEN LOCK"), False, False, 0)
        grid, self.after_sub = row("", "Screens off after locking",
                                   "how soon the screens go dark once the lock is up, however it was locked")
        w.pack_start(grid, False, False, 0)
        self.after_lock = self.make_chips(lambda k: self.set("off_after_lock", f"{k}s" if k != "0" else "never"))
        w.pack_start(self.after_lock.widget, False, False, 0)
        grid, self.grace_sub = row("", "Grace period after an idle lock", "")
        w.pack_start(grid, False, False, 0)
        self.grace = self.make_chips(lambda k: self.set("grace", k))
        w.pack_start(self.grace.widget, False, False, 0)
        self.switches = {}
        for key, icon, title, sub in (
                ("lock_before_sleep", "", "Lock before sleep",
                 "lock the screen just before the computer suspends, so it wakes onto the lock screen"),
                ("password_on_wake", "", "Ask for the password when the screens wake",
                 "turning the screens off on idle locks first, even before the lock timeout")):
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
            grid, sub_label = row(icon, title, sub, sw)
            self.switches[key] = (sw, sub_label, sub)
            w.pack_start(grid, False, False, 0)
        self.idle_row, self.idle_sub = row("", "hypridle", "")
        w.pack_start(self.idle_row, False, False, 0)
        w.pack_start(links_row(link("Open hypridle.conf", lambda: spawn("xdg-open", os.path.expanduser(
                                   "~/.config/hypr/hypridle.conf"))),
                               link("Restart hypridle", lambda: self.do("systemctl", "--user", "restart",
                                                                        "hypridle.service"))),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("KEEP AWAKE"), False, False, 0)
        grid, self.awake_sub = row("", "Keep awake", "")
        w.pack_start(grid, False, False, 0)
        self.awake = self.make_chips(self.set_awake)
        w.pack_start(self.awake.widget, False, False, 0)
        self.holders = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.holders, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("POWER PROFILE"), False, False, 0)
        grid, self.profile_sub = row("", "Power profile", "")
        w.pack_start(grid, False, False, 0)
        self.profile = self.make_chips(self.set_profile)
        w.pack_start(self.profile.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("POWER BUTTON AND SLEEP"), False, False, 0)
        grid, self.key_sub = row("", "The power button", "")
        w.pack_start(grid, False, False, 0)
        self.power_key = self.make_chips(self.copy_power_key)
        w.pack_start(self.power_key.widget, False, False, 0)
        self.sleep_row, self.sleep_sub = row("", "Sleep", "")
        w.pack_start(self.sleep_row, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SESSION"), False, False, 0)
        self.session = self.session_tiles()
        w.pack_start(self.session, False, False, 0)
        hint = dp.label("Every button takes two clicks: the first turns it into \"Click again to ...\", which "
                        f"goes back after {pp.ARM_SECONDS} seconds. Log out, Restart and Shut down end every "
                        "open program.", "ctl-sub")
        hint.set_line_wrap(True)
        w.pack_start(hint, False, False, 0)
        self.updating = False

    # -- building blocks -------------------------------------------------------------
    @staticmethod
    def make_chips(on_pick):
        """Chips on one line where they fit. A FlowBox packed at the start
        shrinks to its narrowest layout -- one chip per line -- unless told
        how many a line holds at least, so set() keeps that at the count."""
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(7)
        chips.widget.set_halign(Gtk.Align.START)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 7)))
        chips.set = set_items
        return chips

    def session_tiles(self):
        """The power panel's tiles and Confirmer. Every key needs confirming
        here (see the module docstring). After firing, the Confirmer is
        re-armed for the next time: in the panel it never needs to be, since
        the panel quits, but this window outlives a lock or a suspend."""
        box = Gtk.Box(spacing=8)
        box.set_homogeneous(True)
        self.tiles = {}
        commands = {key: cmd for key, _g, _c, _v, cmd, _d in pp.ACTIONS}
        captions = {"reboot": ("Restart", "restart"), "poweroff": ("Shut down", "shut down"),
                    "lock": ("Lock now", "lock")}
        self.confirmer = pp.Confirmer(
            actions={key: (lambda k=key: self.fire(k, commands[k])) for key in commands},
            confirm=set(commands), schedule=GLib.timeout_add_seconds, cancel=GLib.source_remove,
            on_change=lambda key, armed: self.tiles[key].set_armed(armed))
        for key, glyph, caption, verb, _cmd, danger in pp.ACTIONS:
            caption, verb = captions.get(key, (caption, verb))
            tile = pp.Tile(key, glyph, caption, verb, danger, self.confirmer.press)
            self.tiles[key] = tile
            box.pack_start(tile.button, True, True, 0)
        return box

    def fire(self, key, cmd):
        """Same wrapper as the panel: detached, and a failure (a refused
        reboot, hyprlock missing) is reported through a notification."""
        self.confirmer.fired = None
        if pp.DRYRUN:
            spawn("notify-send", "Settings (dry run)", f"Would run: {' '.join(cmd)}")
            return
        spawn("sh", "-c", pp.REPORT_FAILURE, "sh", *cmd)

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd):
        """Every control: the command in the background, then redraw from
        what the system reports, with its complaint on top if it failed."""
        background(lambda: attempt(*cmd), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def set(self, key, value):
        if self.updating:
            return
        self.do(IDLE, "set", key, value)

    def toggle(self, key, state):
        if not self.updating:
            self.set(key, "on" if state else "off")
        return True

    def set_awake(self, key):
        args = {"off": ["off"], "on": ["on"]}.get(key, ["on", key])
        self.do(IDLE, "awake", *args)

    def set_profile(self, name):
        self.do(IDLE, "profile", name)

    def copy_power_key(self, action):
        try:
            spawn("wl-copy", power_key_command(action))     # wl-copy forks and holds it itself
        except OSError:
            self.key_sub.set_text("wl-copy is missing, so here it is to copy by hand: "
                                  + power_key_command(action))
            self.key_sub.set_selectable(True)
            return
        self.key_sub.set_text(f"Copied the command that makes it \"{dict(POWER_KEY)[action]}\". It needs "
                              "root: paste it into a terminal and enter your password.")

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None:
            self.subs["dim"].set_text("checking…")
        background(lambda: run_json(IDLE, "status", timeout=15), self.show)

    def show(self, data):
        if not data:
            self.subs["dim"].set_text("idle-settings.py did not answer")
            return
        self.data = data
        self.updating = True
        v = data["values"]
        for key, _icon, _title, sub, opts in TIMINGS:
            self.chips[key].set(choices(opts, v[key]), str(v[key]))
            self.subs[key].set_text(sub)
        self.dim_level.set([(str(n), f"to {n} %") for n in sorted(set(DIM_LEVEL) | {v["dim_level"]})],
                           str(v["dim_level"]))
        self.dim_level.widget.set_visible(bool(v["dim"]))
        if v["dim"]:
            self.subs["dim"].set_text(f"every screen goes down to {v['dim_level']} % of its brightness (in "
                                      "software, on top of yours) until you move the mouse or press a key")
            if not data.get("dim_ready"):
                self.subs["dim"].set_text(self.subs["dim"].get_text() + "  ·  needs the screen colour service "
                                          "restarted once to know how (it happens at the next login, or: "
                                          "systemctl --user restart screen-color)")
        if v["lock"] and v["screens_off"] and v["off_after_lock"] and v["screens_off"] == v["lock"] + v["off_after_lock"]:
            self.subs["screens_off"].set_text(f"{dur(v['off_after_lock'])} after the idle lock, and it moves with "
                                              "the lock and with \"Screens off after locking\"  ·  any input "
                                              "wakes them, onto the lock screen")
        if v["suspend"]:
            self.subs["suspend"].set_text(TIMINGS[3][3] + "  ·  the computer never sleeps on its own otherwise "
                                          "(logind's IdleAction is " + str(data["logind"].get("IdleAction")) + ")")
        clear(self.problems)
        for p in data["problems"]:
            lab = dp.label(f"!  {p[0].upper()}{p[1:]}.", "ctl-sub")
            lab.set_line_wrap(True)
            self.problems.pack_start(lab, False, False, 0)
        self.problems.show_all()

        self.after_lock.set(choices(AFTER_LOCK, v["off_after_lock"]), str(v["off_after_lock"]))
        self.grace.set([(str(s), "None" if not s else f"{s} s") for s in sorted(set(GRACE) | {v["grace"]})],
                       str(v["grace"]))
        self.grace_sub.set_text(
            (f"input in the first {v['grace']} s after an idle lock unlocks without the password, so nudging the "
             "mouse as it fades in costs nothing; locks by hand and before sleep always ask"
             if v["grace"] else "an idle lock asks for the password at once")
            if v["lock"] else "only for the idle lock, which is off: set \"Lock the screen\" to a time first")
        # Kept only in the lock listener, so with no idle lock there is
        # nowhere to write it: greyed out rather than a click that does nothing.
        self.grace.widget.set_sensitive(bool(v["lock"]))
        for key, (sw, sub_label, sub) in self.switches.items():
            sw.set_state(v[key])
            sw.set_active(v[key])
        pw_sub = self.switches["password_on_wake"][2]
        # Lives in the screens-off listener: with that at Never the switch
        # has nothing to change (same reasoning as the grace chips).
        self.switches["password_on_wake"][0].set_sensitive(bool(v["screens_off"]) or v["password_on_wake"])
        if not v["screens_off"]:
            pw_sub = "only when the screens turn off on idle, which is set to Never above"
        elif v["lock"] and v["lock"] <= v["screens_off"]:
            pw_sub += "  ·  the screen is already locked by the time they go off"
        self.switches["password_on_wake"][1].set_text(pw_sub)

        hyp = data["hypridle"]
        state = (f"running since {hyp['since'] or '?'}" if hyp["state"] == "active" else
                 f"NOT running ({hyp['state'] or 'unknown'}): nothing happens on idle until it is -- Restart hypridle")
        sub = f"{state}  ·  timings live in {data['conf'].replace(os.path.expanduser('~'), '~')}"
        if data["kept"]:
            sub += f"  ·  {len(data['kept'])} listener{'s' if len(data['kept']) != 1 else ''} of your own kept as is"
        if hyp["ignores_systemd_inhibit"]:
            sub += "  ·  ignore_systemd_inhibit is on, so Keep awake below cannot hold it off"
        self.idle_sub.set_text(sub)

        aw = data["awake"]
        key = "off" if not aw["on"] else ("on" if not aw["until"] else str(aw.get("minutes")))
        self.awake.set(AWAKE, key)
        if aw["on"] and aw["until"]:
            self.awake_sub.set_text(f"on until {time.strftime('%H:%M', time.localtime(aw['until']))}: nothing dims, "
                                    "locks, turns off or sleeps on idle")
        elif aw["on"]:
            self.awake_sub.set_text("on until you turn it off or log out: nothing dims, locks, turns off or "
                                    "sleeps on idle")
        else:
            self.awake_sub.set_text("hold off everything above for a while -- a long read, a download, a "
                                    "presentation. Suspend from the power menu still works")
        clear(self.holders)
        others = [h for h in data["holders"] if h["who"] != "Keep awake"]
        lines = [f"Also keeping the screens awake now: {h['who']} ({h['why']})" for h in others[:6]]
        lines.append("A fullscreen window and Steam games hold it off too. The toolbox's Keep awake row is "
                     "this same switch, so flipping either one changes both.")
        for text in lines:
            lab = dp.label(text, "ctl-sub")
            lab.set_line_wrap(True)
            self.holders.pack_start(lab, False, False, 0)
        self.holders.show_all()

        prof = data["profile"]
        if prof["profiles"]:
            self.profile.set([(p, PROFILE_TEXT.get(p, p)) for p in prof["profiles"]], prof["active"])
            bits = [PROFILE_SUB.get(prof["active"], prof["active"] or "?")]
            if prof.get("cpu_watts") is not None:
                bits.append(f"CPU drawing {prof['cpu_watts']:.0f} W now")
            if prof.get("epp"):
                bits.append(f"CPU energy preference: {prof['epp'].replace('_', ' ')}")
            if prof.get("degraded"):
                bits.append(f"held back: {prof['degraded']}")
            bits.append("kept across restarts by the profile service")
            self.profile_sub.set_text("  ·  ".join(bits))
        else:
            self.profile.set([], None)
            self.profile_sub.set_text("No power profile service answered (net.hadess.PowerProfiles). On Fedora "
                                      "it is tuned-ppd: sudo dnf install tuned-ppd && sudo systemctl enable "
                                      "--now tuned-ppd")

        lg = data["logind"]
        current = lg.get("HandlePowerKey")
        self.power_key.set(POWER_KEY, current)
        self.key_sub.set_text(f"pressing it: {dict(POWER_KEY).get(current, current or '?')}  ·  changing it "
                              "needs root: pick one to copy the command, then run it in a terminal")
        mode = {"deep": "deep sleep (S3): almost no power, a few seconds to wake",
                "s2idle": "light sleep (s2idle): wakes fast, draws more"}.get(lg.get("mem_sleep"), lg.get("mem_sleep"))
        # None: systemctl did not say (no such unit -- no NVIDIA driver), which
        # is not the same as "off".
        nv = {"enabled": "NVIDIA's suspend helpers are on, so the card keeps its memory across sleep",
              None: None}.get(lg.get("nvidia_suspend"),
                              "NVIDIA's suspend helpers are off: sudo systemctl enable nvidia-suspend nvidia-resume")
        self.sleep_sub.set_text("  ·  ".join(filter(None, [mode or "sleep mode unknown", nv,
                                                            f"the suspend key: {lg.get('HandleSuspendKey') or '?'}"])))
        self.widget.show_all()
        self.dim_level.widget.set_visible(bool(v["dim"]))
        if not prof["profiles"]:
            self.profile.widget.hide()
        self.updating = False
