"""Settings page: the laptop's battery -- how it is doing, the battery
saver, the low-battery warnings and the charge limit. Only on a machine with
a battery of its own: PAGE's "needs": "battery" keeps it out of the sidebar,
the search and the launcher on a desktop (_catalog.present(), which asks
power_state.has_battery(): a wireless mouse's battery does not count).

Every control runs a command and the page redraws from what comes back, as
every page does (common.py):
  * battery-settings.py status / set -- one JSON with everything below, and
    the warnings and the saver's automatic switch (battery.json);
  * battery-saver.py on | off -- the saver itself, the same command the
    launcher and an automation rule run;
  * charge-limit.py set N -- the firmware's charge limit, through the root
    side in system/charge-limit/ (a polkit rule lets the session start
    charge-limit@N.service; no password). Without that root side installed
    the chips are greyed out and the page says how to install it, once:
    `sudo ./system/charge-limit/install.sh` from the Atrium folder. On an
    ASUS the firmware takes only 60 / 80 / 100 % (charge-limit.py "fixed"),
    and the page offers only those;
  * emergency-alerts.py set battery_poll -- shown only when an early-warning
    source that polls every few seconds is on (SASMEX, NAAD, P2PQuake): the
    one daemon that does NOT back off on battery unless told to, because an
    early warning is worth its seconds.

The summary at the top is live: every LIVE_S while the page is on screen it
reads the battery straight from sysfs (power_state.battery(), in this
process: no command started for it), so the draw and the time left move as
the load does. The rest only changes when something is clicked, or the page
is shown again.

The idle timings on battery (a shorter dim, screens off, suspend) are not
here but on Power & lock, where the plugged-in ones are: one place for all
the timings, linked from the foot of this page.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import power_state  # noqa: E402  (the live summary: sysfs reads, no fork)

PAGE = {"id": "battery", "title": "Battery", "icon": "", "group": "System", "order": 20, "parent": "power", "tab": "Battery",
        "needs": "battery",
        "keywords": ["battery saver", "saver", "low battery", "low power", "charge", "charging", "charge limit",
                     "stop charging", "charge threshold", "80 %", "health", "battery health", "wear",
                     "capacity", "cycles", "cycle count", "watts", "power draw", "time left",
                     "battery warning", "critical battery", "laptop", "batería",
                     "ahorro de batería", "carga"]}

BACKEND = os.path.join(HYPR, "battery-settings.py")  # noqa: F405  (HYPR: common)
SAVER = os.path.join(HYPR, "battery-saver.py")  # noqa: F405
CHARGE = os.path.join(HYPR, "charge-limit.py")  # noqa: F405
SETTINGS = os.path.join(HYPR, "settings.py")  # noqa: F405
INSTALL = "sudo ./system/charge-limit/install.sh"
LIVE_S = 5              # the summary's refresh while the page shows
WORN_PCT = 80           # health under this: say a charge limit would spare what is left
GLYPHS = ("", "", "", "", "")    # Font Awesome empty .. full
BOLT = ""
WHY = {"manual": "turned on by you", "auto": "turned on by itself: the battery ran low",
       "unplug": "turned on by itself: the charger came out", "rule": "turned on by an automation"}


# -- words (pure: the tests check them without a window) ----------------------------
def hm(minutes):
    """165 -> "2 h 45 min", 17 -> "17 min"; None for nothing usable (no
    rate yet, or a nonsense figure from a battery that is settling)."""
    if minutes is None or minutes <= 0 or minutes > 48 * 60:
        return None
    h, m = divmod(int(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{max(1, m)} min"


def glyph(bat):
    pct = (bat or {}).get("capacity") or 0
    g = GLYPHS[min(4, (pct + 12) // 25)]
    return f"{BOLT} {g}" if (bat or {}).get("status") == "Charging" else g


def summary(bat, plugged, limit=None):
    """(title, sub) of the charge row. LIMIT: the charge limit in use, so a
    battery held at 80 % on the charger says why it is not charging."""
    if not bat:
        return "No battery", "this machine reports none"
    pct, status, watts = bat.get("capacity"), bat.get("status"), bat.get("watts")
    title = f"{pct} %" if pct is not None else "Battery"
    bits = []
    if status == "Discharging" and plugged is not True:
        title += "  ·  on battery"
        left = hm(bat.get("minutes_left"))
        bits.append(f"{left} left" if left else "working out the time left")
        if watts:
            bits.append(f"drawing {watts:.1f} W")
    elif status == "Charging":
        title += "  ·  charging"
        full = hm(bat.get("minutes_to_full"))
        if full:
            bits.append(f"full in {full}")
        if watts:
            bits.append(f"{watts:.1f} W going in")
    elif status == "Full" or (pct is not None and pct >= 99):
        title += "  ·  full"
        bits.append("on the charger")
    else:
        title += "  ·  plugged in"
        if limit and limit < 100 and pct is not None and pct >= limit - 2:
            bits.append(f"held at the {limit} % charge limit")
        else:
            bits.append("not charging")
    return title, "  ·  ".join(bits)


def health_text(bat):
    """(title, sub) of the health row; None when the firmware says neither."""
    if not bat or (bat.get("health_pct") is None and bat.get("cycles") is None):
        return None
    health, cycles = bat.get("health_pct"), bat.get("cycles")
    title = f"Health {health} %" if health is not None else "Health"
    bits = []
    if health is not None:
        bits.append(f"holds {health} % of what it did new")
    if cycles is not None:
        bits.append(f"{cycles} charge cycle{'s' if cycles != 1 else ''}")
    if health is not None and health < WORN_PCT:
        bits.append("worn: a charge limit spares what is left")
    return title, "  ·  ".join(bits)


def saver_text(saver, settings):
    """The battery saver row's sub line."""
    if not saver:
        return "battery-saver.py is not installed"
    if saver.get("active"):
        since = saver.get("since")
        when = time.strftime("%H:%M", time.localtime(since)) if since else ""
        text = WHY.get(saver.get("why"), "on") + (f" at {when}" if when else "")
        if saver.get("why") in ("auto", "unplug", "rule"):
            text += "  ·  off again when plugged in"
        return text
    bits = []
    if saver.get("declined") and saver.get("on_battery"):
        bits.append("off by you: it stays off until the charger is plugged in")
    auto_at = (settings or {}).get("saver_auto_at")
    if auto_at:
        bits.append(f"turns on by itself at {auto_at} %")
    if (settings or {}).get("saver_on_unplug"):
        bits.append("and when unplugged" if auto_at else "turns on by itself when unplugged")
    return "  ·  ".join(bits) or "off  ·  only when you turn it on"


def warn_text(warn_at, warned):
    if not warn_at:
        return "no warnings: the battery can run flat without a word"
    parts = ", ".join(f"{p} %" for p in warn_at)
    text = f"a notification at {parts}; the last one critical"
    if warned:
        text += f"  ·  given this time: {', '.join(f'{p} %' for p in warned)}"
    return text


def toggled(warn_at, pct):
    """warn_at with PCT added, or taken out when it is there (a chip's click)."""
    have = set(warn_at or [])
    have ^= {pct}
    return sorted(have, reverse=True)


def limit_caption(n):
    return "100 % (full)" if n == 100 else f"{n} %"


def limit_text(charge):
    """(sub line, chips usable) of the charge limit row."""
    if not charge:
        return "charge-limit.py is not installed", False
    if not charge.get("supported"):
        return "this battery cannot stop charging short of full", False
    limit = charge.get("limit")
    bits = [f"now {limit_caption(limit)}" if limit else "now: unknown"]
    if charge.get("fixed"):
        bits.append("this firmware takes only " + ", ".join(f"{c} %" for c in charge.get("choices") or []))
    if not charge.get("installed"):
        bits.append("needs the system part first (below)")
        return "  ·  ".join(bits), False
    if limit == 100:
        bits.append("a battery kept full on the charger wears fastest; 80 % spares it")
    return "  ·  ".join(bits), True


def early_text(early):
    names = ", ".join(n.split(" (")[0] for n in early.get("fast") or [])
    gap = early.get("battery_s", 15)
    if early.get("battery_poll"):
        return (f"{names}: every {gap} s on battery. Can lose up to {gap} s of a warning "
                "that may only give a minute.")
    return f"{names}: every few seconds, on battery too. On: every {gap} s on battery, a few mW saved."


def attempt(*cmd, timeout=30):
    """A backend command: "" when it worked, else its last stderr line."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    lines = (r.stderr or "").strip().splitlines()
    if not lines:
        # charge-limit.py and battery-saver.py say what failed in their JSON.
        try:
            import json
            got = json.loads(r.stdout or "null") or {}
            lines = [got.get("error") or "; ".join(got.get("errors") or [])]
        except (ValueError, AttributeError):
            lines = []
    return ([line for line in lines if line] or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        self.updating = False
        self.ticking = None
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        w.pack_start(heading("NOW"), False, False, 0)
        self.now_row, self.now_sub = row(GLYPHS[3], "", "checking…")
        self.now_icon = self.now_row.get_child_at(0, 0)
        self.now_title = self.now_row.get_child_at(1, 0)
        w.pack_start(self.now_row, False, False, 0)
        self.health_row, self.health_sub = row("", "Health", "")
        self.health_title = self.health_row.get_child_at(1, 0)
        w.pack_start(self.health_row, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("BATTERY SAVER"), False, False, 0)
        self.saver = Gtk.Switch()
        self.saver.connect("state-set", lambda _s, state: self.switch_saver(state))
        grid, self.saver_sub = row("", "Battery saver", "", self.saver)
        w.pack_start(grid, False, False, 0)
        what = dp.label("Blur, shadows and animations off, the moving wallpaper paused, the power saver "
                        "profile, and background checks less often.", "ctl-sub")
        what.set_line_wrap(True)
        w.pack_start(what, False, False, 0)
        grid, self.auto_sub = row("", "Turn on by itself at", "")
        w.pack_start(grid, False, False, 0)
        self.auto = self.make_chips(lambda k: self.set("saver_auto_at", k))
        w.pack_start(self.auto.widget, False, False, 0)
        self.unplug = Gtk.Switch()
        self.unplug.connect("state-set", lambda _s, state: self.toggle("saver_on_unplug", state))
        grid, _sub = row("", "Turn on when unplugged", "as soon as the charger comes out", self.unplug)
        w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("LOW BATTERY"), False, False, 0)
        grid, self.warn_sub = row("", "Warn me at", "")
        w.pack_start(grid, False, False, 0)
        self.warn = self.make_chips(self.pick_warning)
        w.pack_start(self.warn.widget, False, False, 0)
        self.warn_links = links_row(link("None", lambda: self.set("warn_at", "none")),
                                    link("20, 10 and 5 %", lambda: self.set("warn_at", "20,10,5")))
        w.pack_start(self.warn_links, False, False, 0)
        self.watch_note = dp.label("", "ctl-sub")
        self.watch_note.set_line_wrap(True)
        self.watch_note.set_selectable(True)
        self.watch_note.set_no_show_all(True)
        w.pack_start(self.watch_note, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("CHARGE LIMIT"), False, False, 0)
        grid, self.limit_sub = row("", "Stop charging at", "")
        w.pack_start(grid, False, False, 0)
        self.limit = self.make_chips(lambda k: self.do(CHARGE, "set", k, timeout=150))
        w.pack_start(self.limit.widget, False, False, 0)
        # Without the root side: how to install it, once (hidden otherwise).
        self.install = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        note = dp.label("The firmware's switch needs root, so the limit is set by a small system part that "
                        f"is installed once, from the Atrium folder: {INSTALL}", "ctl-sub")
        note.set_line_wrap(True)
        note.set_selectable(True)
        self.install.pack_start(note, False, False, 0)
        self.install_said = dp.label("", "ctl-sub")
        self.install.pack_start(self.install_said, False, False, 0)
        self.install.pack_start(links_row(link("Copy the command", self.copy_install)), False, False, 0)
        self.install.set_no_show_all(True)
        w.pack_start(self.install, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # Only with a fast early-warning source on (show() decides).
        self.early = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.early.pack_start(heading("EARTHQUAKE EARLY WARNING"), False, False, 0)
        self.early_switch = Gtk.Switch()
        self.early_switch.connect("state-set", lambda _s, state: self.switch_early(state))
        grid, self.early_sub = row("", "Check less often on battery", "", self.early_switch)
        self.early.pack_start(grid, False, False, 0)
        self.early.pack_start(sep(), False, False, 0)
        self.early.set_no_show_all(True)
        w.pack_start(self.early, False, False, 0)

        w.pack_start(heading("ON BATTERY"), False, False, 0)
        grid, _sub = row("", "Dim, screens off and sleep on battery",
                         "shorter idle timings for when the charger is out are set with the others",
                         link("Open Power & lock", lambda: spawn(SETTINGS, "power")))
        w.pack_start(grid, False, False, 0)
        self.more = dp.label("", "ctl-sub")
        self.more.set_line_wrap(True)
        self.more.set_selectable(True)
        w.pack_start(details(self.more), False, False, 0)

    # -- building blocks -------------------------------------------------------------
    @staticmethod
    def make_chips(on_pick):
        """Chips on one line where they fit (power.py's make_chips: a
        FlowBox at the start shrinks to one chip a line otherwise)."""
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(7)
        chips.widget.set_halign(Gtk.Align.START)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 7)))
        chips.set = set_items
        return chips

    @staticmethod
    def light(chips, keys):
        """Several chips lit at once (the warnings are a set, Chips lights
        one): the same class and check mark Chips gives its one."""
        for key, button in chips.buttons.items():
            style = button.get_style_context()
            on = key in keys
            (style.add_class if on else style.remove_class)("active")
            button.get_child().set_markup(("✓ " if on else "") + chips.captions[key])

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd, timeout=30):
        background(lambda: attempt(*cmd, timeout=timeout), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def set(self, key, value):
        if not self.updating:
            self.do(BACKEND, "set", key, str(value))

    def toggle(self, key, state):
        if not self.updating:
            self.set(key, "on" if state else "off")
        return True             # moves when the redraw says it did

    def switch_saver(self, state):
        if not self.updating:
            self.do(SAVER, "on" if state else "off")
        return True

    def switch_early(self, state):
        if not self.updating:
            self.do(EMERGENCY, "set", "battery_poll", "on" if state else "off")  # noqa: F405  (EMERGENCY: common)
        return True

    def pick_warning(self, key):
        if self.updating or not self.data:
            return
        new = toggled(self.data["settings"]["warn_at"], int(key))
        self.set("warn_at", ",".join(str(p) for p in new) or "none")

    def copy_install(self):
        try:
            spawn("wl-copy", INSTALL)
            self.install_said.set_text("copied: paste it in a terminal in the Atrium folder")
        except OSError:
            self.install_said.set_text(f"wl-copy is missing; type it: {INSTALL}")

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(BACKEND, "status", timeout=20), self.show)
        if self.ticking is None:
            self.ticking = GLib.timeout_add_seconds(LIVE_S, self.tick)

    def tick(self):
        """Every LIVE_S while the page shows; stops itself once it does not
        (refresh() starts it again)."""
        if not self.widget.get_mapped():
            self.ticking = None
            return False
        try:
            bat, plugged = power_state.battery(), power_state.plugged()
        except OSError:
            return True
        self.show_now(bat, plugged)
        return True

    def show_now(self, bat, plugged):
        limit = ((self.data or {}).get("charge") or {}).get("limit")
        title, sub = summary(bat, plugged, limit)
        self.now_icon.set_text(glyph(bat))
        self.now_title.set_text(title)
        self.now_sub.set_text(sub)
        health = health_text(bat)
        self.health_row.set_visible(health is not None)
        if health:
            self.health_title.set_text(health[0])
            self.health_sub.set_text(health[1])

    def show(self, data):
        if not data:
            self.now_sub.set_text("battery-settings.py did not answer")
            return
        self.data = data
        self.updating = True
        settings = data["settings"]
        self.widget.show_all()
        self.show_now(data.get("battery"), data.get("plugged"))

        saver = data.get("saver")
        self.saver.set_sensitive(saver is not None)
        active = bool((saver or {}).get("active"))
        self.saver.set_state(active)
        self.saver.set_active(active)
        self.saver_sub.set_text(saver_text(saver, settings))
        self.auto.set([(str(p), "Never" if not p else f"{p} %") for p in data["choices"]["saver_auto_at"]],
                      str(settings["saver_auto_at"]))
        self.auto_sub.set_text(f"on battery, at {settings['saver_auto_at']} % or below"
                               if settings["saver_auto_at"] else "never: only by hand or when unplugged")
        self.unplug.set_state(settings["saver_on_unplug"])
        self.unplug.set_active(settings["saver_on_unplug"])

        self.warn.set([(str(p), f"{p} %") for p in data["choices"]["warn_at"]], None)
        self.light(self.warn, {str(p) for p in settings["warn_at"]})
        self.warn_sub.set_text(warn_text(settings["warn_at"], data.get("warned")))
        if not data.get("watcher"):
            self.watch_note.set_text("!  The battery watcher has not run this login, so no warning comes: "
                                     "systemctl --user enable --now power-watch.service")
        self.watch_note.set_visible(not data.get("watcher"))

        charge = data.get("charge")
        sub, usable = limit_text(charge)
        self.limit_sub.set_text(sub)
        if charge and charge.get("supported"):
            self.limit.set([(str(c), limit_caption(c)) for c in charge.get("choices") or []],
                           str(charge.get("limit")))
            self.limit.widget.show()
        else:
            self.limit.set([], None)
            self.limit.widget.hide()
        self.limit.widget.set_sensitive(usable)
        need_install = bool(charge and charge.get("supported") and not charge.get("installed"))
        if need_install:
            for child in self.install.get_children():
                child.show_all()
        self.install.set_visible(need_install)

        early = data.get("early_warnings")
        if early:
            self.early_switch.set_state(bool(early.get("battery_poll")))
            self.early_switch.set_active(bool(early.get("battery_poll")))
            self.early_sub.set_text(early_text(early))
            for child in self.early.get_children():
                child.show_all()
        self.early.set_visible(bool(early))

        bat = data.get("battery") or {}
        more = [f"Battery {bat.get('name', '?')}: charge limit, saver and warnings are kept in "
                f"{power_state.SETTINGS_FILE.replace(os.path.expanduser('~'), '~')}",
                "The warnings and the saver's automatic switch come from power-watch.service, which "
                "sleeps until the kernel says the power changed."]
        if charge and charge.get("saved") is not None:
            more.append(f"The root side writes {charge['saved']} % again at every boot and resume "
                        "(charge-limit.service).")
        if saver and saver.get("gamemode"):
            more.append("Gamemode is on: while it is, the game keeps its own look.")
        self.more.set_text("\n".join(more))
        self.updating = False
