"""Settings page: the daily brief and the end-of-day journal (brief.py).

The two switches are automations.py's built-in rules -- "daily-brief" (when
you are back after being away) and "end-of-day" (when work hours end) --
switched with `automations.py enable|disable`; everything else is brief.py's
own settings, `brief.py set KEY VALUE`, read back with `brief.py status`.
The page keeps nothing itself: every control runs one of those and redraws
from what status says.
"""
import os
import subprocess

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import GLib, Gtk  # noqa: F401,E402  (after common: it picks GTK 3)

PAGE = {"id": "brief", "title": "Daily brief & journal", "icon": "", "group": "Apps", "order": 22,
        "keywords": ["brief", "morning", "good morning", "resumen", "journal", "diario", "end of day",
                     "time sheet", "timesheet", "work log", "what did i do", "yesterday", "where was i",
                     "commits"]}

BRIEF = os.path.join(HYPR, "brief.py")  # noqa: F405  (HYPR: common)
AUTOMATIONS = os.path.join(HYPR, "automations.py")  # noqa: F405
WORKHOURS = os.path.join(HYPR, "workhours.py")  # noqa: F405
AFTER = ["04:00", "05:00", "06:00", "07:00", "08:00"]
AT = ["07:00", "07:30", "08:00", "08:30", "09:00", "10:00"]
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SECTION_ICONS = {"yesterday": "", "repos": "", "units": "", "health": "\uf0f1", "updates": "",
                 "weather": "", "calendar": "", "timers": "", "notifications": ""}
SECTION_SUBS = {
    "yesterday": "the last day's time by project and app, the window you ended on, the last session",
    "repos": "repos in your projects folder with uncommitted, new or unpushed work (no fetch)",
    "units": "failed systemd services and timers, yours and the system's",
    "health": "the nightly checkup: what it fixed, what waits for your OK, problems explained "
              "(Settings > Desktop health)",
    "updates": "what the updates pill last found",
    "weather": "today, from the bar's last forecast",
    "calendar": "today's events still to come (Evolution's calendars)",
    "timers": "alarms, timers and reminders still to ring today",
    "notifications": "what came in that you have not opened",
}


# -- pure helpers (tests/test_brief.py) ------------------------------------------------
def clock_chips(options, current):
    """(key, caption) chips for "HH:MM" times, plus current, in order."""
    return [(t, t) for t in sorted(set(options) | {current})]


def toggled(current, section, on, order):
    """The sections setting with one section switched, in the brief's order."""
    chosen = set(filter(None, current.split(","))) - {section}
    if on:
        chosen.add(section)
    return ",".join(s for s in order if s in chosen)


def workhours_text(work):
    """When end-of-day comes, in words, from brief.py status's "workhours"."""
    if not work or not work.get("days"):
        return ("Work hours are off or have no days set, so work-end never comes: write it from the launcher "
                "(\"journal\") or add a time rule with the journal action in Automations.")
    days = work["days"]
    if days == list(range(5)):
        when = "weekdays"
    elif days == list(range(7)):
        when = "every day"
    else:
        when = ", ".join(DAY_NAMES[d] for d in days)
    return f"At the end of work hours: {work['end']}, {when} (Timers & alarms sets them), skipping holidays."


def call(*cmd):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, (done.stderr or done.stdout).strip()


def put(switch, on):
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
        self.switches = {}
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

        # -- the morning brief ---------------------------------------------------------
        w.pack_start(heading("MORNING BRIEF"), False, False, 0)  # noqa: F405
        w.pack_start(self.switch_row("rule:daily-brief", "", "Show a brief each morning",
                                     "Once a day: what you were in the middle of, loose ends and the day "
                                     "ahead, as a notification -- click it for all of it. Everything is "
                                     "read on this computer."), False, False, 0)
        self.mode = Chips(lambda k: self.change(BRIEF, "set", "morning", k))  # noqa: F405
        self.mode.widget.set_max_children_per_line(2)
        w.pack_start(dp.label("When", "ctl-sub"), False, False, 0)  # noqa: F405
        w.pack_start(self.mode.widget, False, False, 0)
        self.time_caption = dp.label("", "ctl-sub")  # noqa: F405
        w.pack_start(self.time_caption, False, False, 0)
        self.time_chips = Chips(lambda k: self.change(BRIEF, "set", self.time_key(), k))  # noqa: F405
        self.time_chips.widget.set_max_children_per_line(6)
        w.pack_start(self.time_chips.widget, False, False, 0)
        w.pack_start(links_row(link("Show the brief now", lambda: spawn(BRIEF, "show"))),  # noqa: F405
                     False, False, 0)

        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("IN THE BRIEF"), False, False, 0)  # noqa: F405
        self.section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.section_box, False, False, 0)

        # -- the journal ---------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("END-OF-DAY JOURNAL"), False, False, 0)  # noqa: F405
        self.journal_row = self.switch_row(
            "rule:end-of-day", "", "Write a journal entry when work ends",
            "What you worked on (time per project and app), today's commits across your projects folder and the loose "
            "ends, summed up by the local model -- plain when it cannot run. Notes you add to the file "
            "are kept when it is written again.")
        w.pack_start(self.journal_row, False, False, 0)
        w.pack_start(self.switch_row("titles", "", "Window titles in the journal",
                                     "Off: projects and apps only. The journal outlives the activity "
                                     "history's kept days, and titles can say a lot."), False, False, 0)
        w.pack_start(self.switch_row("model", "", "Summary by the local model",
                                     "The worker model (AI & models), never a cloud one; skipped in "
                                     "gamemode or when the GPU is full."), False, False, 0)
        w.pack_start(self.switch_row("timesheet", "", "Draft time sheet",
                                     "A CSV next to each entry: project, hours to the quarter -- a draft "
                                     "from focus time, to check."), False, False, 0)
        self.where = wrapped("")
        w.pack_start(self.where, False, False, 0)
        w.pack_start(links_row(link("Write today's entry now", lambda: spawn(BRIEF, "journal", "--notify")),  # noqa: F405
                               link("Open today's", lambda: spawn(BRIEF, "open")),  # noqa: F405
                               link("Journal folder", lambda: self.open_folder())), False, False, 0)  # noqa: F405

    # -- building ----------------------------------------------------------------------
    def switch_row(self, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, on, k=key: self.flip(k, on))
        self.switches[key] = sw
        grid, sub_label = row(icon, title, sub, sw)  # noqa: F405
        grid.sub_label = sub_label
        return grid

    def time_key(self):
        return "at" if (self.data or {}).get("settings", {}).get("morning") == "time" else "after"

    def open_folder(self):
        folder = (self.data or {}).get("journal_dir")
        if folder:
            os.makedirs(folder, exist_ok=True)
            spawn("xdg-open", folder)  # noqa: F405

    # -- changing things -----------------------------------------------------------------
    def flip(self, key, on):
        if key.startswith("rule:"):
            return self.change(AUTOMATIONS, "enable" if on else "disable", key[5:])
        if key.startswith("section:"):
            current = self.data["settings"]["sections"] if self.data else ""
            return self.change(BRIEF, "set", "sections", toggled(current, key[8:], on, self.data["sections"]))
        return self.change(BRIEF, "set", key, "on" if on else "off")

    def change(self, *cmd):
        if self.updating:
            return True
        background(lambda: call(*cmd), self.changed)  # noqa: F405
        return True

    def changed(self, result):
        ok, why = result
        self.problem.set_text("" if ok else f"Not changed: {why}")
        self.problem.set_visible(not ok)
        self.refresh()

    # -- drawing ---------------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(BRIEF, "status", timeout=20), self.show)  # noqa: F405

    def show(self, data):
        if not data:
            self.problem.set_text("brief.py status did not answer.")
            self.problem.set_visible(True)
            return
        self.data = data
        conf = data["settings"]
        self.updating = True
        try:
            put(self.switches["rule:daily-brief"], data["rules"]["brief"])
            put(self.switches["rule:end-of-day"], data["rules"]["journal"])
            for key in ("titles", "model", "timesheet"):
                put(self.switches[key], conf[key] == "on")
            self.mode.set([("unlock", "The first time I am back after"), ("time", "At a set time")],
                          conf["morning"])
            if conf["morning"] == "time":
                self.time_caption.set_text("At (or the first time you are back after it):")
                self.time_chips.set(clock_chips(AT, conf["at"]), conf["at"])
            else:
                self.time_caption.set_text("Not before (a login counts as coming back):")
                self.time_chips.set(clock_chips(AFTER, conf["after"]), conf["after"])
            self.draw_sections(data)
        finally:
            self.updating = False
        self.journal_row.sub_label.set_text(
            "What you worked on (time per project and app), today's commits across your projects folder and the loose ends, "
            "summed up by the local model -- plain when it cannot run. " + workhours_text(data.get("workhours")))
        folder = data["journal_dir"].replace(os.path.expanduser("~"), "~")
        today = "today's is written" if data.get("journal_today") else "none for today yet"
        self.where.set_text(f"Entries go to {folder}/YYYY-MM-DD.md ({today}). Anything outside the "
                            "generated part of a file is yours and kept.")
        self.widget.show_all()

    def draw_sections(self, data):
        chosen = set(data["settings"]["sections"].split(","))
        if not self.section_box.get_children():
            for sid in data["sections"]:
                grid = self.switch_row(f"section:{sid}", SECTION_ICONS.get(sid, ""),
                                       data["titles"].get(sid, sid), SECTION_SUBS.get(sid, ""))
                self.section_box.pack_start(grid, False, False, 0)
        for sid in data["sections"]:
            put(self.switches[f"section:{sid}"], sid in chosen)
