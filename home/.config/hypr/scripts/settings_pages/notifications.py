"""Settings page: notifications -- Do Not Disturb now and by itself (quiet
hours, games, screen sharing), where popups go and how long they stay, the
theme sound, the history (notify-settings.py, auto-dnd.py, mako), and the
theme's mascot on them (mascot_notify.py).

Everything here is notify-settings.py: the page runs `status` to draw and
`set KEY VALUE` / `dnd on|off` to change, so the keys, the search bar and
this page always agree. mako keeps the choices in
~/.config/mako/generated/settings (notify-settings.py says why that file
and why there); auto-dnd.py reads the same saved settings for the quiet
hours and its two triggers. The one exception is "Digest when it ends": that
is automations.py's built-in rule dnd-digest (notify-digest.py), switched
with `automations.py enable|disable dnd-digest`. The mascot's three
switches are the other: mascot_notify.py status / set (mascot.json).

While the dynamic island takes the popups (island.json: enabled, and
"notifications" not off -- island.py), a line under POPUPS says so: the
timeouts and Do Not Disturb hold there too, the placement ones are mako's.
"""
import os
import subprocess

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import GLib, Gtk  # noqa: F401,E402  (after common: it picks GTK 3)

PAGE = {"id": "notifications", "title": "Notifications", "icon": "", "group": "System", "order": 10,
        "keywords": ["notificaciones", "do not disturb", "dnd", "quiet hours", "popups", "toasts", "mako",
                     "how long", "notification sound", "history", "games", "screen sharing", "urgent",
                     "digest", "missed", "summary", "mascot", "icon", "voice", "mascota"]}

NOTIFY = os.path.join(HYPR, "notify-settings.py")  # noqa: F405  (HYPR: common)
# notify-send with the theme's mascot (mascot_notify.py)
MASCOT_NOTIFY = os.path.join(HYPR, "notify")  # noqa: F405
MASCOT = os.path.join(HYPR, "mascot_notify.py")  # noqa: F405
MASCOT_SWITCHES = [("icon", "\uf118", "The mascot on notifications",
                    "the theme's little mascot as the icon; the app's own rides in its corner"),
                   ("toasts", "\uf0e7", "On quick toasts too",
                    "volume, keyboard layout, \"saved\" -- off: they keep their own icon"),
                   ("voice", "\uf075", "In its own voice",
                    "a first line in the mascot's words (railguard, urgent ones)")]
THEME_SOUND = os.path.join(HYPR, "theme-sound.sh")  # noqa: F405
AUTOMATIONS = os.path.join(HYPR, "automations.py")  # noqa: F405
DIGEST_RULE = "dnd-digest"
DIGEST_TEXT = "one summary of what you missed, written on this computer"
# The dynamic island (island.py) can take the popups over: its settings.
ISLAND_STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                            "hypr", "island.json")


def island_takes_popups(conf):
    """Whether island.json says the island shows the notifications (on,
    and "Show notifications in the island" -- on unless switched off)."""
    conf = conf if isinstance(conf, dict) else {}
    return bool(conf.get("enabled")) and conf.get("notifications", True) is not False


def island_note(conf):
    """The line under POPUPS while the island has them, else ""."""
    if not island_takes_popups(conf):
        return ""
    return ("The dynamic island shows them now, one at a time at the top (Settings > Bar > Island). "
            "How long they stay and Do Not Disturb apply there too; where, which screen, how many "
            "and stacking are for mako's popups, which come back when the island is off.")


def read_island():
    try:
        import json
        with open(ISLAND_STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# The 3x3 chips are laid out like the screen: the stack goes where its chip is.
ANCHORS = [("top-left", "Top left"), ("top-center", "Top middle"), ("top-right", "Top right"),
           ("center-left", "Left"), ("center", "Middle"), ("center-right", "Right"),
           ("bottom-left", "Bottom left"), ("bottom-center", "Bottom middle"), ("bottom-right", "Bottom right")]
TIMEOUTS = {
    "timeout_normal": ("Normal", [3, 5, 8, 15, 30, 0]),
    "timeout_low": ("Low urgency (volume and such toasts)", [2, 3, 5, 10, 0]),
    "timeout_critical": ("Urgent (battery, disk full, alerts)", [15, 30, 60, 0]),
}
MAX_VISIBLE = [("1", "1"), ("3", "3"), ("5", "5"), ("8", "8"), ("-1", "No limit")]
# No "none": with max-history=0 what arrives in Do Not Disturb is simply lost.
HISTORY = [("10", "10"), ("20", "20"), ("50", "50"), ("100", "100"), ("200", "200")]
DAYS = [("0123456", "Every day"), ("01234", "Weekdays"), ("56", "Weekends")]


def order(number):
    """Sort key for the number chips: 0 ("until dismissed") and -1 ("no
    limit") are the largest, so they stay at the end."""
    return float("inf") if number <= 0 else number


def seconds_caption(seconds):
    return "Until dismissed" if seconds == 0 else f"{seconds} s"


def call(*cmd):
    """(ok, what went wrong) -- unlike run(), the error text too, so the page
    can show why notify-settings.py refused a value."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, (done.stderr or done.stdout).strip()


def chips_block(box, caption, chips, per_line=4):
    chips.widget.set_max_children_per_line(per_line)
    chips.widget.set_min_children_per_line(min(per_line, 3))
    box.pack_start(dp.label(caption, "ctl-sub"), False, False, 0)  # noqa: F405
    box.pack_start(chips.widget, False, False, 0)


def monitor_name(description):
    """'Acme Corporation Wide 34 5505810045741' -> without the serial
    number Hyprland appends (a last word with four or more digits in it)."""
    words = description.split()
    if len(words) > 1 and sum(c.isdigit() for c in words[-1]) >= 4:
        words = words[:-1]
    return " ".join(words)


def put(switch, on):
    """Show `on` on a switch. Both halves: state-set returns True (the switch
    waits for the system), so after a click that changed nothing -- mako
    down, a refused value -- `active` (where the knob sits) would still be
    the clicked position while `state` is the old one, and set_state() of
    an unchanged state alone does not move the knob back."""
    switch.set_active(on)
    switch.set_state(on)


def wrapped(text):
    lab = dp.label(text, "ctl-sub")  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    return lab


class Page:
    def __init__(self):
        self.updating = False
        self.data = None
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)
        # Its own line, not self.problem: draw() owns this one (shown while
        # mako is down, gone when it is back), changed() owns that one.
        self.mako_down = wrapped("!  Nothing pops up: mako is not running "
                                 "(systemctl --user restart mako starts it).")
        self.mako_down.set_no_show_all(True)
        w.pack_start(self.mako_down, False, False, 0)

        # -- now --------------------------------------------------------------
        w.pack_start(heading("DO NOT DISTURB"), False, False, 0)  # noqa: F405
        self.dnd = Gtk.Switch()
        self.dnd.connect("state-set", lambda _s, on: self.change(NOTIFY, "dnd", "on" if on else "off"))
        grid, self.dnd_sub = row("", "Do Not Disturb", "", self.dnd)  # noqa: F405
        w.pack_start(grid, False, False, 0)
        self.switches = {}
        w.pack_start(self.switch_row("critical_in_dnd", "", "Urgent ones break through",
                                     "battery, disk-full and emergency warnings still pop up"),
                     False, False, 0)
        self.digest = Gtk.Switch()
        self.digest.connect("state-set", lambda _s, on: self.change(
            AUTOMATIONS, "enable" if on else "disable", DIGEST_RULE))
        grid, self.digest_sub = row("\uf0ca", "Digest when it ends", DIGEST_TEXT, self.digest)  # noqa: F405
        w.pack_start(grid, False, False, 0)

        # -- by itself --------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("BY ITSELF"), False, False, 0)  # noqa: F405
        self.service_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.service_box, False, False, 0)
        quiet_row = self.switch_row("quiet", "", "Quiet hours", "")
        self.quiet_sub = quiet_row.sub_label
        w.pack_start(quiet_row, False, False, 0)
        hours = Gtk.Box(spacing=8)
        self.q_from, self.q_to = Gtk.Entry(), Gtk.Entry()
        for entry, hint in ((self.q_from, "23:00"), (self.q_to, "07:00")):
            entry.set_placeholder_text(hint)
            entry.set_width_chars(6)
            entry.connect("activate", lambda _e: self.save_hours())
        hours.pack_start(dp.label("from", "ctl-sub"), False, False, 0)  # noqa: F405
        hours.pack_start(self.q_from, False, False, 0)
        hours.pack_start(dp.label("to", "ctl-sub"), False, False, 0)  # noqa: F405
        hours.pack_start(self.q_to, False, False, 0)
        hours.pack_start(link("Save hours", self.save_hours), False, False, 0)  # noqa: F405
        w.pack_start(hours, False, False, 0)
        self.days = Chips(lambda key: key != "custom" and self.set("quiet_days", key))  # noqa: F405
        chips_block(w, "Days (when they start)", self.days)
        w.pack_start(self.switch_row("dnd_games", "", "While a game is running",
                                     "any Steam game"), False, False, 0)
        w.pack_start(self.switch_row("dnd_share", "", "While the screen is shared",
                                     "a call or OBS sharing your screen"), False, False, 0)
        w.pack_start(details(wrapped(
            "These never fight you: if Do Not Disturb is already on they leave it alone, and if you turn it "
            "off they wait until the reason is over. A focus round (timers) keeps it on until the round ends. "
            "Games are any steam_app_* window; screen sharing is the portal's.")), False, False, 0)

        # -- popups -----------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("POPUPS"), False, False, 0)  # noqa: F405
        self.island_note = wrapped("")
        self.island_note.set_no_show_all(True)
        w.pack_start(self.island_note, False, False, 0)
        self.anchor = Chips(lambda key: self.set("anchor", key))  # noqa: F405
        chips_block(w, "Where they appear", self.anchor, per_line=3)
        self.output = Chips(lambda key: self.set("output", key))  # noqa: F405
        chips_block(w, "On which screen", self.output)
        self.output_sub = wrapped("")
        w.pack_start(self.output_sub, False, False, 0)
        self.timeouts = {}
        w.pack_start(dp.label("How long they stay", "ctl-title"), False, False, 0)  # noqa: F405
        for key, (caption, _choices) in TIMEOUTS.items():
            chips = Chips(lambda value, k=key: self.set(k, value))  # noqa: F405
            chips_block(w, caption, chips, per_line=7)
            self.timeouts[key] = chips
        w.pack_start(self.switch_row("ignore_app_timeouts", "", "Use these times for every app",
                                     "even for apps that ask for their own time"), False, False, 0)
        self.max_visible = Chips(lambda key: self.set("max_visible", key))  # noqa: F405
        chips_block(w, "At most on screen at once", self.max_visible, per_line=6)
        w.pack_start(self.switch_row("group", "", "Stack repeats from one app",
                                     "one popup per app, \"(4 more)\""), False, False, 0)
        w.pack_start(links_row(link("Send a test notification", lambda: spawn(  # noqa: F405
            MASCOT_NOTIFY, "-a", "Settings", "Test notification",
            "This is where and how long they appear now."))), False, False, 0)

        # -- mascot -----------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("MASCOT"), False, False, 0)  # noqa: F405
        self.mascot_switches = {}
        for key, icon, title, sub in MASCOT_SWITCHES:
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, on, k=key: self.change(MASCOT, "set", k, "on" if on else "off"))
            self.mascot_switches[key] = sw
            grid, _ = row(icon, title, sub, sw)  # noqa: F405
            w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Show me", lambda: spawn(  # noqa: F405
            MASCOT_NOTIFY, "-a", "Settings", "--mood", "relieved", "--say", "proud", "The mascot",
            "How it looks on a notification with the current theme."))), False, False, 0)

        # -- sound ------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("SOUND"), False, False, 0)  # noqa: F405
        self.sound = Gtk.Switch()
        self.sound.connect("state-set", lambda _s, on: self.change(THEME_SOUND, "on" if on else "off"))
        grid, _ = row("", "Theme sounds", "chime for each notification; never in Do Not Disturb",  # noqa: F405
                      self.sound)
        w.pack_start(grid, False, False, 0)

        # -- history ----------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("HISTORY"), False, False, 0)  # noqa: F405
        grid, self.history_sub = row("", "History", "")  # noqa: F405
        w.pack_start(grid, False, False, 0)
        self.max_history = Chips(lambda key: self.set("max_history", key))  # noqa: F405
        chips_block(w, "How many to keep", self.max_history, per_line=5)
        self.clear_link = link("Clear all…", self.ask_clear)  # noqa: F405
        w.pack_start(links_row(link("Show history", lambda: spawn(PANEL, "toggle", "notifications")),  # noqa: F405
                               link("Bring back the last one", lambda: self.change(NOTIFY, "restore")),  # noqa: F405
                               self.clear_link), False, False, 0)
        # "Clear all" asks first: this box, hidden until then.
        self.confirm = Gtk.Box(spacing=8)
        self.confirm.set_halign(Gtk.Align.END)
        self.confirm_label = dp.label("", "ctl-sub")  # noqa: F405
        self.confirm.pack_start(self.confirm_label, False, False, 0)
        self.confirm.pack_start(link("Yes, clear them", self.do_clear), False, False, 0)  # noqa: F405
        self.confirm.pack_start(link("Cancel", self.hide_confirm), False, False, 0)  # noqa: F405
        self.confirm.set_no_show_all(True)
        w.pack_start(self.confirm, False, False, 0)
        w.pack_start(details(links_row(link("Back to the defaults",  # noqa: F405
                                            lambda: self.change(NOTIFY, "reset")))), False, False, 0)

    # -- building helpers ---------------------------------------------------------
    def switch_row(self, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, on, k=key: self.set(k, "on" if on else "off"))
        self.switches[key] = sw
        grid, sub_label = row(icon, title, sub, sw)  # noqa: F405
        grid.sub_label = sub_label    # a PyGObject wrapper takes attributes
        return grid

    # -- changing things ----------------------------------------------------------
    def set(self, key, value):
        return self.change(NOTIFY, "set", key, str(value))

    def change(self, *cmd):
        """Run it in the background, then redraw from what is true now. A
        switch's state-set returns True: the switch moves when refresh() says
        the setting really changed, not before."""
        if self.updating:
            return True
        background(lambda: call(*cmd), self.changed)  # noqa: F405
        return True

    def changed(self, result):
        ok, why = result
        self.show_problem("" if ok else why or "that did not work")
        self.refresh()

    def show_problem(self, text):
        self.problem.set_text(text)
        self.problem.set_visible(bool(text))

    def save_hours(self):
        start, end = self.q_from.get_text().strip(), self.q_to.get_text().strip()

        def work():
            for key, value in (("quiet_from", start), ("quiet_to", end)):
                ok, why = call(NOTIFY, "set", key, value)
                if not ok:
                    return ok, why
            return True, ""
        background(work, self.changed)  # noqa: F405

    def ask_clear(self):
        count = (self.data or {}).get("history", 0) + (self.data or {}).get("shown", 0)
        self.confirm_label.set_text(f"Dismiss what is on screen and empty the list ({count})?")
        # show_all() skips a no_show_all widget -- itself included -- so lift it first.
        self.confirm.set_no_show_all(False)
        self.confirm.show_all()

    def hide_confirm(self):
        self.confirm.hide()
        self.confirm.set_no_show_all(True)

    def do_clear(self):
        self.hide_confirm()
        self.change(NOTIFY, "clear")

    # -- drawing ------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(NOTIFY, "status"), self.show)  # noqa: F405
        background(lambda: run_json(AUTOMATIONS, "list", "--json"), self.show_digest)  # noqa: F405
        background(lambda: run_json(MASCOT, "status"), self.show_mascot)  # noqa: F405

    def show_mascot(self, data):
        """The mascot's switches: mascot.json's "notifications"."""
        self.updating = True
        try:
            for key, sw in self.mascot_switches.items():
                sw.set_sensitive(data is not None)
                put(sw, bool((data or {}).get(key)))
        finally:
            self.updating = False

    def show_digest(self, data):
        """The digest switch: automations.py's rule, and whether its daemon runs."""
        rule = next((r for r in (data or {}).get("rules", []) if r["id"] == DIGEST_RULE), None)
        self.digest.set_sensitive(rule is not None)
        self.updating = True
        try:
            put(self.digest, bool(rule and rule["enabled"]))
        finally:
            self.updating = False
        text = DIGEST_TEXT
        if rule is None:
            text = "automations.py did not answer: " + AUTOMATIONS
        elif rule["enabled"] and not data.get("running"):
            text = "off until Automations is running (Settings > Automations)"
        self.digest_sub.set_text(text)

    def show(self, data):
        if not data:
            self.show_problem("notify-settings.py did not answer")
            return
        self.data = data
        conf = data["settings"]
        self.updating = True
        try:
            self.draw(data, conf)
        finally:
            self.updating = False

    def draw(self, data, conf):
        self.mako_down.set_visible(not data["mako"])
        auto = data.get("auto") or {}
        put(self.dnd, data["dnd"])
        if data["dnd"] and auto.get("ours"):
            text = f"on by itself, for the {auto.get('reasons') or 'reason that started it'}"
        elif data["dnd"]:
            text = "on: popups held back" + (" (urgent ones still show)" if conf["critical_in_dnd"] else "")
        elif auto.get("declined") and auto.get("reasons"):
            text = f"off: you turned it off during the {auto['reasons']}"
        else:
            text = "off  ·  ALT+SHIFT+D or the bell in the bar"
        self.dnd_sub.set_text(text)
        for key, sw in self.switches.items():
            put(sw, bool(conf[key]))

        clear(self.service_box)  # noqa: F405
        if data["auto_dnd_service"] != "active":
            grid, _ = row("", "Not running: nothing below happens by itself",  # noqa: F405
                          f"its service is {data['auto_dnd_service']}",
                          link("Start it", lambda: self.change(  # noqa: F405
                              "systemctl", "--user", "enable", "--now", "auto-dnd.service")))
            self.service_box.pack_start(grid, False, False, 0)
            self.service_box.show_all()

        span = f"{conf['quiet_from']} to {conf['quiet_to']}, {data['quiet_days_text']}"
        if not conf["quiet"]:
            self.quiet_sub.set_text(f"off  ·  {span} when on")
        elif conf["quiet_from"] == conf["quiet_to"]:
            self.quiet_sub.set_text("from and to are the same time: never quiet")
        else:
            now = "Quiet now" if data["quiet_now"] else "Not now"
            change = f"; {'ends' if data['quiet_now'] else 'starts'} {data['quiet_change']}" if data["quiet_change"] else ""
            self.quiet_sub.set_text(f"{span}  ·  {now}{change}")
        if not self.q_from.has_focus():
            self.q_from.set_text(conf["quiet_from"])
        if not self.q_to.has_focus():
            self.q_to.set_text(conf["quiet_to"])
        days = list(DAYS)
        if conf["quiet_days"] not in dict(DAYS):
            days.append(("custom", f"Custom: {data['quiet_days_text']}"))
            self.days.set(days, "custom")
        else:
            self.days.set(days, conf["quiet_days"])

        self.anchor.set(ANCHORS, conf["anchor"])
        bars = data.get("bar_outputs") or []
        screens = [("", "Follow focus")] + [(o["name"], o["name"] + (" (the bar's)" if o["name"] in bars else ""))
                                            for o in data["outputs"]]
        if conf["output"] and conf["output"] not in [k for k, _ in screens]:
            screens.append((conf["output"], f"{conf['output']} (not connected)"))
        self.output.set(screens, conf["output"])
        if not conf["output"]:
            self.output_sub.set_text("on the screen you are working on")
        else:
            desc = next((monitor_name(o["description"]) for o in data["outputs"] if o["name"] == conf["output"]), "")
            note = ("" if conf["output"] in bars or not conf["anchor"].startswith("top")
                    else "  ·  no bar there, so less gap above")
            self.output_sub.set_text((desc or "not connected: on the focused screen meanwhile") + note)
        for key, (_caption, choices) in TIMEOUTS.items():
            values = choices if conf[key] in choices else sorted(choices + [conf[key]], key=order)
            items = [(str(s), seconds_caption(s)) for s in values]
            self.timeouts[key].set(items, str(conf[key]))
        self.max_visible.set(self.with_current(MAX_VISIBLE, conf["max_visible"]), str(conf["max_visible"]))
        self.max_history.set(self.with_current(HISTORY, conf["max_history"]), str(conf["max_history"]))

        put(self.sound, data["sounds"] != "off")
        kept = data["history"]
        shown = data["shown"]
        island = read_island()
        note = island_note(island)
        self.island_note.set_text(note)
        self.island_note.set_visible(bool(note))
        self.history_sub.set_text(
            f"{kept} in the list, {shown} {'in the island' if note else 'on screen'}  ·  " + (
                "emptied when you log out" if conf["max_history"] else "history is off"))
        self.widget.show_all()

    @staticmethod
    def with_current(items, value):
        """The chips, plus one for a value set elsewhere (the CLI) so it shows."""
        if str(value) in dict(items):
            return items
        return sorted(items + [(str(value), str(value))], key=lambda kv: order(int(kv[0])))
