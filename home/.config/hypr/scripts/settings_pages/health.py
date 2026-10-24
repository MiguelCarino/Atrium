"""Settings page: desktop health -- the self-healing nightly checkup
(health.py, run by tasks.py's built-in "health-checkup" task).

Top to bottom:

    NIGHTLY CHECKUP  the switch (the task on / off: `health.py set enabled`),
                     when it runs (`health.py set schedule "daily HH:MM"`),
                     whether tasks.service runs it; Run a checkup now, the
                     full report, Mark seen, Undo the last fixes
    FIX BY ITSELF    one switch per remedy of the fixed catalog (auto_*: off
                     as shipped -- off means proposed, with an Apply button
                     below; a short line each, health.py's words on hover),
                     and the sizes that count as "big" for a cache
                     and a log
    OPTIONS          the local model explains what is not known (explain, at
                     most explain_max a night), the system journal too
                     (system_journal), a notification after a checkup that
                     found something (notify), the Health section of the
                     morning brief (brief.py's sections)
    LAST CHECKUP     every finding: what, in its first sentence; the rest of
                     the words, by whom and the raw lines in its Details
                     fold, and Apply for a proposed fix --
                     it says exactly what it will do, and asks once more

The page keeps nothing itself: every control runs health.py (or brief.py)
and redraws from `health.py status`.
"""
import os
import subprocess
import time

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import GLib, Gtk, Pango  # noqa: F401,E402  (after common: it picks GTK 3)

PAGE = {"id": "health", "title": "Desktop health", "icon": "", "group": "System", "order": 82, "parent": "updates", "tab": "Health",
        "keywords": ["health", "self-healing", "self healing", "checkup", "check-up", "nightly", "doctor",
                     "journal", "errors", "crashes", "coredump", "failed services", "restart", "cache",
                     "pip cache", "shader cache", "logs", "rotate", "auto fix", "repair", "salud",
                     "diagnóstico", "reparar"]}

HEALTH = os.path.join(HYPR, "health.py")  # noqa: F405  (HYPR: common)
BRIEF = os.path.join(HYPR, "brief.py")  # noqa: F405
TIMES = ["02:00", "03:00", "03:30", "04:00", "05:00", "13:00"]
CACHE_GB = [1, 2, 5, 10, 20]
LOG_MB = [50, 100, 200, 500, 1000]
EXPLAIN_MAX = [3, 6, 10, 20]
LEVEL_ICONS = {"fail": "", "warn": "", "info": ""}
REMEDY_ICONS = {"restart-unit": "", "trash-cache": "", "rotate-log": "",
                "regen-config": ""}
OPTIONS = [("explain", "", "Explain with the local model",
            "Explains unknown errors; never a cloud model."),
           ("system_journal", "", "Read the system journal too",
            "System services and kernel errors, without sudo."),
           ("notify", "", "Tell me after a checkup",
            "When it fixed something, needs you, or found a new problem.")]
# The short line under each remedy's switch (health.py's full words are its tooltip).
REMEDY_SUBS = {"restart-unit": "Desktop services only, at most once a day each",
               "trash-cache": "To the trash, so it can be restored",
               "rotate-log": "The old copy is kept; nothing is lost",
               "regen-config": "Rewrites missing theme files"}


# -- words (pure: tests/test_health.py) ------------------------------------------------------------
def schedule_time(schedule):
    """"daily 03:30" -> "03:30"; anything else -> None (shown as it is)."""
    parts = (schedule or "").split()
    return parts[1] if len(parts) == 2 and parts[0] == "daily" else None


def task_text(data):
    """The switch row's sub line: when, and whether it can run at all."""
    t, d = data.get("task") or {}, data.get("tasks") or {}
    if not t.get("exists"):
        return "Not set up yet: switching it on makes the checkup task."
    when = t.get("schedule") or "?"
    bits = [f"Runs {('every day at ' + schedule_time(when)) if schedule_time(when) else when}"]
    if t.get("status"):
        bits.append(t["status"])
    text = "  ·  ".join(bits)
    if d and not d.get("enabled", True):
        text += "\nBackground tasks are switched off, so it does not run."
    elif d and not d.get("running", True):
        text += "\nThe tasks service is not running, so it does not run."
    return text


def report_summary(rep, when_text):
    if not rep:
        return "No checkup yet. Run one now, or wait for tonight's."
    s = rep["summary"]
    bits = []
    if s["problems"]:
        bits.append(f"{s['problems']} problem{'s' if s['problems'] != 1 else ''}")
    if s["fixed"]:
        bits.append(f"{s['fixed']} fixed")
    if s["proposed"]:
        bits.append(f"{s['proposed']} fix{'es' if s['proposed'] != 1 else ''} to approve")
    head = ", ".join(bits) or "nothing needs you"
    noise = f", {s['noise']} harmless lines hidden" if s.get("noise") else ""
    return f"{when_text}: {head} ({s['findings']} finding{'s' if s['findings'] != 1 else ''}{noise})."


def first_sentence(text, limit=80):
    """The opening sentence of a finding's words (or its first `limit`
    characters, cut at a word): the rest goes in the finding's fold."""
    text = " ".join(text.split())
    stop = text.find(". ")
    if 0 < stop < limit:
        return text[:stop + 1]
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def finding_sub(f):
    """A finding's first sentence and its fix's state."""
    out = first_sentence((f.get("words") or "").strip())
    rem = f.get("remedy") or {}
    if rem.get("status") == "applied":
        out += f"\nFixed: {rem.get('result', '')}"
    elif rem.get("status") == "failed":
        out += f"\nThe fix did not work: {rem.get('result', '')}"
    elif rem.get("status") == "proposed" and rem.get("note"):
        out += f"\nNot fixed by itself: {rem['note']}"
    return out


def finding_more(f):
    """What the fold under a finding says: its full words when the sub line
    cut them, and who wrote them."""
    words = (f.get("words") or "").strip()
    out = words if first_sentence(words) != " ".join(words.split()) else ""
    if f.get("by") and f["by"] != "catalog":
        out += ("\n" if out else "") + f"({f['by']})"
    return out


def toggled(current, section, on, order):
    chosen = set(filter(None, current.split(","))) - {section}
    if on:
        chosen.add(section)
    return ",".join(s for s in order if s in chosen)


def call(*cmd, timeout=30):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr or done.stdout).strip()


def put(switch, on):
    switch.set_active(on)
    switch.set_state(on)


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    lab.set_xalign(0)
    return lab


class Page:
    def __init__(self):
        self.updating = False
        self.busy = False
        self.data = None
        self.brief = None
        self.switches = {}
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

        # -- the checkup ------------------------------------------------------------------------
        w.pack_start(heading("NIGHTLY CHECKUP"), False, False, 0)  # noqa: F405
        self.task_row = self.switch_row(
            "enabled", "", "Check the desktop every night",
            "Fixes what it knows how to, explains the rest.")
        w.pack_start(self.task_row, False, False, 0)
        w.pack_start(dp.label("At", "ctl-sub"), False, False, 0)  # noqa: F405
        self.time_chips = Chips(lambda k: self.change(HEALTH, "set", "schedule", f"daily {k}"))  # noqa: F405
        self.time_chips.widget.set_max_children_per_line(6)
        w.pack_start(self.time_chips.widget, False, False, 0)
        self.run_link = link("Run a checkup now", self.run_now)  # noqa: F405
        self.undo_link = link("Undo the last fixes", lambda: self.change(HEALTH, "undo", timeout=180))  # noqa: F405
        self.undo_link.set_no_show_all(True)
        w.pack_start(links_row(self.run_link,  # noqa: F405
                               link("Full report", self.open_report),  # noqa: F405
                               link("Mark seen", lambda: self.change(HEALTH, "dismiss")),  # noqa: F405
                               self.undo_link), False, False, 0)

        # -- the remedies -----------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("FIX BY ITSELF"), False, False, 0)  # noqa: F405
        w.pack_start(wrapped("Undoable, never sudo. Off: proposed for you to apply below."), False, False, 0)
        self.remedy_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.remedy_box, False, False, 0)
        w.pack_start(dp.label("A cache counts as big over", "ctl-sub"), False, False, 0)  # noqa: F405
        self.cache_chips = Chips(lambda k: self.change(HEALTH, "set", "cache_gb", k))  # noqa: F405
        self.cache_chips.widget.set_max_children_per_line(5)
        w.pack_start(self.cache_chips.widget, False, False, 0)
        w.pack_start(dp.label("A desktop log counts as big over", "ctl-sub"), False, False, 0)  # noqa: F405
        self.log_chips = Chips(lambda k: self.change(HEALTH, "set", "log_mb", k))  # noqa: F405
        self.log_chips.widget.set_max_children_per_line(5)
        w.pack_start(self.log_chips.widget, False, False, 0)

        # -- options ----------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("OPTIONS"), False, False, 0)  # noqa: F405
        for key, icon, title, sub in OPTIONS:
            w.pack_start(self.switch_row(key, icon, title, sub), False, False, 0)
        w.pack_start(dp.label("At most this many explanations a night", "ctl-sub"), False, False, 0)  # noqa: F405
        self.max_chips = Chips(lambda k: self.change(HEALTH, "set", "explain_max", k))  # noqa: F405
        self.max_chips.widget.set_max_children_per_line(4)
        w.pack_start(self.max_chips.widget, False, False, 0)
        w.pack_start(self.switch_row("brief", "", "In the morning brief",
                                     "A Health section in the daily brief."), False, False, 0)

        # -- the last report --------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("LAST CHECKUP"), False, False, 0)  # noqa: F405
        self.summary = wrapped("")
        w.pack_start(self.summary, False, False, 0)
        self.findings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.findings_box, False, False, 0)

    # -- building ---------------------------------------------------------------------------------
    def switch_row(self, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, on, k=key: self.flip(k, on))
        self.switches[key] = sw
        grid, sub_label = row(icon, title, sub, sw)  # noqa: F405
        grid.sub_label = sub_label
        return grid

    def open_report(self):
        path = (self.data or {}).get("report_file")
        if path and os.path.exists(path):
            spawn("xdg-open", path)  # noqa: F405

    # -- changing things --------------------------------------------------------------------------
    def flip(self, key, on):
        if self.updating:
            return True
        if key == "brief":
            if not self.brief:
                return True
            new = toggled(self.brief["settings"]["sections"], "health", on, self.brief["sections"])
            return self.change(BRIEF, "set", "sections", new)
        return self.change(HEALTH, "set", key, "on" if on else "off")

    def change(self, *cmd, timeout=30):
        if self.updating:
            return True
        background(lambda: call(*cmd, timeout=timeout), self.changed)  # noqa: F405
        return True

    def changed(self, result):
        ok, why = result
        self.problem.set_text("" if ok else f"Not done: {why}")
        self.problem.set_visible(not ok)
        self.refresh()

    def run_now(self):
        if self.busy:
            return
        self.busy = True
        self.run_link.set_label("Checking… (a minute or two)")

        def done(result):
            self.busy = False
            self.run_link.set_label("Run a checkup now")
            self.changed(result)
        background(lambda: call(HEALTH, "run", "--by", "asked", "--summary", timeout=1800), done)  # noqa: F405

    def apply(self, f):
        rem = f["remedy"]
        dialog = Gtk.MessageDialog(transient_for=self.widget.get_toplevel(), modal=True,
                                   message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=rem["label"] + "?")
        words = self.data["remedies"].get(rem["type"], {}).get("words", "")
        if rem.get("note"):         # why it was not done by itself (a sensor, a restart that did not help)
            words += f"\n\nNote: {rem['note']}."
        dialog.format_secondary_text(words)
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK:
            self.change(HEALTH, "fix", f["id"], timeout=300)

    # -- drawing ------------------------------------------------------------------------------------
    def refresh(self):
        def work():
            return run_json(HEALTH, "status", timeout=30), run_json(BRIEF, "status", timeout=20)  # noqa: F405
        background(work, self.show)  # noqa: F405

    def show(self, result):
        data, brief = result
        if not data:
            self.problem.set_text("Could not read the health status")
            self.problem.set_tooltip_text(f"Try it in a terminal: {HEALTH} status")
            self.problem.set_visible(True)
            self.widget.show_all()
            return
        self.data, self.brief = data, brief
        conf = data["settings"]
        self.updating = True
        try:
            put(self.switches["enabled"], data["task"]["enabled"])
            for key, *_ in OPTIONS:
                put(self.switches[key], conf[key])
            if brief:
                put(self.switches["brief"], "health" in brief["settings"]["sections"].split(","))
            self.switches["brief"].set_sensitive(bool(brief))
            current = schedule_time(data["task"].get("schedule")) or ""
            self.time_chips.set([(t, t) for t in sorted(set(TIMES) | ({current} if current else set()))],
                                current)
            self.cache_chips.set([(str(n), f"{n} GB") for n in sorted(set(CACHE_GB) | {conf["cache_gb"]})],
                                 str(conf["cache_gb"]))
            self.log_chips.set([(str(n), f"{n} MB") for n in sorted(set(LOG_MB) | {conf["log_mb"]})],
                               str(conf["log_mb"]))
            self.max_chips.set([(str(n), str(n)) for n in sorted(set(EXPLAIN_MAX) | {conf["explain_max"]})],
                               str(conf["explain_max"]))
            self.draw_remedies(data)
        finally:
            self.updating = False
        self.task_row.sub_label.set_text(task_text(data))
        self.undo_link.set_visible(bool(data.get("undo")))
        rep = data.get("report") or {}
        when = ago(int(time.time() - rep["at"])) if rep else ""  # noqa: F405
        self.summary.set_text(report_summary(rep, f"Checked {when}" + (f" ({rep.get('by')})" if rep else "")))
        self.draw_findings(rep)
        self.widget.show_all()

    def draw_remedies(self, data):
        if not self.remedy_box.get_children():
            for rid, r in data["remedies"].items():
                self.remedy_box.pack_start(self.switch_row(r["setting"], REMEDY_ICONS.get(rid, ""),
                                                           r["title"], REMEDY_SUBS.get(rid, r["words"])),
                                           False, False, 0)
                self.remedy_box.get_children()[-1].set_tooltip_text(r["words"])
        for r in data["remedies"].values():
            put(self.switches[r["setting"]], data["settings"][r["setting"]])

    def draw_findings(self, rep):
        clear(self.findings_box)  # noqa: F405
        for f in (rep.get("findings") or [])[:40]:
            rem = f.get("remedy") or {}
            button = None
            if rem.get("status") in ("proposed", "failed"):
                button = link("Apply", lambda f=f: self.apply(f))  # noqa: F405
                button.set_tooltip_text(rem["label"])
            title = f["title"] + (f"  ×{f['count']}" if f.get("count", 1) > 1 else "")
            grid, sub = row(LEVEL_ICONS.get(f["level"], ""), title, finding_sub(f), button)  # noqa: F405
            sub.set_selectable(True)
            self.findings_box.pack_start(grid, False, False, 0)
            if rem.get("status") in ("proposed", "failed"):
                self.findings_box.pack_start(wrapped(f"Fix: {rem['label']}"), False, False, 0)
            more = finding_more(f)
            if more or f.get("raw"):
                fold = details(label=f"Details ({len(f['raw'])} line{'s' if len(f['raw']) != 1 else ''})" if f.get("raw") else "Details")  # noqa: F405
                if more:
                    words = wrapped(more)
                    words.set_selectable(True)
                    fold.box.pack_start(words, False, False, 0)
                if f.get("raw"):
                    raw = wrapped("\n".join(f["raw"]))
                    raw.set_selectable(True)
                    raw.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                    raw.get_style_context().add_class("monospace")
                    fold.box.pack_start(raw, False, False, 0)
                self.findings_box.pack_start(fold, False, False, 0)
