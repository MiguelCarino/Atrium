"""Settings page: background tasks -- small local jobs that run on their own
(tasks.py, followed by tasks.service): watch a build, a log, a unit, a page's
price; tidy a folder after you approve the plan; sum up a folder of logs.

Top to bottom:

    the switch      all background tasks on / off (tasks.py on|off: the daemon
                    idles while off), whether tasks.service runs, how many
                    tasks need you
    OPTIONS         the local model explains failures and sums up (explain),
                    a notification when a command succeeds (notify_ok), heavy
                    work waits for gamemode to end (gamemode_pause), web checks
                    allowed (web) and how often at most (url_min_minutes)
    YOUR TASKS      each task in words, its status and last run, what needs
                    you, what it may touch (its permissions, in a fold); Run, Stop (a
                    running command), Log (its own log, inline), a switch
                    (pause / resume), Delete (asks first). A tidy plan waiting
                    is listed with Approve / Discard; Undo puts the last
                    approved batch back; Open summary shows a folder summary
    IN PLAIN WORDS  a sentence -> the local "quick" model writes the task
                    (tasks.py add-from-text --json: checked strictly, a
                    command or address kept only when it is in the sentence,
                    never a cloud model) -> a preview with its permissions ->
                    Save or Discard. Nothing is saved before Save.
    BY HAND         a type, its options, a schedule, a name -> Add: the place
                    to type a command for watch-command.

Every control runs tasks.py in a thread and redraws from what it reports
(list --json); tasks.json stays the one place the tasks are (its path and
Open button are in the Details fold up top).
"""
import json
import os
import subprocess
import time

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import GLib, Gtk, Pango  # noqa: F401,E402  (after common: it picks GTK 3)

PAGE = {"id": "tasks", "title": "Background tasks", "icon": "\uf0ae", "group": "System", "order": 66, "parent": "startup", "tab": "Background tasks",
        "keywords": ["tasks", "agents", "background", "jobs", "watch build", "build failed", "log",
                     "price", "price drop", "web page", "tidy", "downloads", "organise", "organize",
                     "summarise", "summary", "monitor", "unit", "tareas", "agentes", "vigilar"]}

TASKS = os.path.join(HYPR, "tasks.py")  # noqa: F405
TASKS_FILE = os.path.expanduser("~/.config/hypr/tasks.json")
GEAR, WARN, PAUSE, PEN, BELL = "\uf013", "\uf071", "\uf04c", "\uf304", "\uf0f3"
TYPE_ICONS = {"watch-command": "\uf120", "watch-file": "\uf15c", "watch-unit": "\uf085",
              "watch-process": "\uf2db", "watch-url": "\uf0ac", "organise-folder": "\uf07c",
              "summarise-folder": "\uf03a"}
# The BY HAND picker's words for each type.
KIND_WORDS = {"watch-command": "Run a command and tell me if it fails",
              "watch-file": "Follow a log file and tell me about errors",
              "watch-unit": "Watch a systemd unit and tell me if it fails",
              "watch-url": "Check a web page for a change or a price",
              "organise-folder": "Tidy a folder (a plan you approve first)",
              "summarise-folder": "Sum up a folder of logs"}
OPTIONS = [("explain", "Explain with the local model",
            "Says why a job failed and sums up folders."),
           ("notify_ok", "Tell me when a command succeeds", "Not only when it fails."),
           ("gamemode_pause", "Wait for gamemode to end", "Heavy work waits while a game runs."),
           ("web", "Web checks", "Tasks may fetch the web pages they watch.")]
URL_MINUTES = [(5, "5 min"), (15, "15 min"), (30, "30 min"), (60, "1 hour")]


# -- words (pure: tests/test_tasks.py) -------------------------------------------------------
def when_text(epoch, now=None):
    if not epoch:
        return "has not run yet"
    now = now if now is not None else time.time()
    delta = now - epoch
    if delta < 90:
        return "ran just now"
    if delta < 5400:
        return f"ran {int(delta // 60)} min ago"
    if delta < 86400 and time.localtime(epoch).tm_mday == time.localtime(now).tm_mday:
        return "ran today " + time.strftime("%H:%M", time.localtime(epoch))
    return "ran " + time.strftime("%a %d %b %H:%M", time.localtime(epoch))


def task_sub(t, now=None):
    """The lines under a task's name."""
    first = t["words"]
    bits = [t["status"]]
    if t["runnable"] or t.get("last_run"):
        bits.append(when_text(t.get("last_run"), now))
    if t.get("last_summary"):
        bits.append(t["last_summary"])
    return f"{first}\n" + "  ·  ".join(bits)


def task_may(t):
    """What a task may touch (its permissions), for the fold under its row."""
    return "May: " + "; ".join(t["permissions"])


def hand_task(kind, values, schedule, name):
    """The task the BY HAND form describes (tasks.py add checks it): empty
    fields are left out, numbers stay text for the checker to read."""
    params = {k: v.strip() for k, v in values.items() if v.strip()}
    task = {"name": name.strip() or kind.replace("-", " ").capitalize(), "type": kind, "params": params,
            "enabled": True}
    if schedule.strip():
        task["schedule"] = schedule.strip()
    return task


def call(*cmd, timeout=60):
    """(ok, output or what went wrong)."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    if done.returncode == 0:
        return True, done.stdout
    lines = [l for l in (done.stderr or done.stdout).strip().splitlines() if l.strip()]
    return False, (lines[-1] if lines else f"exit status {done.returncode}").removeprefix("tasks: ")


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    return lab


def mono(text):
    lab = wrapped(text)
    lab.set_selectable(True)
    lab.override_font(Pango.FontDescription("monospace 9"))
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.updating = False
        self.busy = set()
        self.armed = ""             # the task whose Delete waits for a second click
        self.open_logs = {}         # task id -> its log lines, shown inline
        self.catalog = None
        self.preview = None         # the model's task waiting for Save
        self.fields = {}            # BY HAND: param -> entry

        self.master = Gtk.Switch()
        self.master.connect("state-set", lambda _s, new: self.set_option("enabled", new))
        self.summary, self.summary_sub = row(GEAR, "Background tasks", "checking…", self.master)  # noqa: F405
        w.pack_start(self.summary, False, False, 0)
        self.service_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.service_box, False, False, 0)
        w.pack_start(links_row(link("Check again", self.refresh)), False, False, 0)  # noqa: F405
        self.file_note = wrapped("")
        w.pack_start(details(self.file_note, links_row(  # noqa: F405
            link("Open tasks.json", lambda: spawn("xdg-open", TASKS_FILE)))), False, False, 0)  # noqa: F405
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        # -- options ------------------------------------------------------------------
        w.pack_start(heading("OPTIONS"), False, False, 0)  # noqa: F405
        self.switches = {}
        for key, title, sub in OPTIONS:
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, new, k=key: self.set_option(k, new))
            grid, _ = row(BELL if key == "notify_ok" else GEAR, title, sub, sw)  # noqa: F405
            self.switches[key] = sw
            w.pack_start(grid, False, False, 0)
        w.pack_start(wrapped("Web checks at most every"), False, False, 0)
        self.url_chips = Chips(lambda k: self.set_option("url_min_minutes", k))  # noqa: F405
        w.pack_start(self.url_chips.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        # -- the tasks ----------------------------------------------------------------
        w.pack_start(heading("YOUR TASKS"), False, False, 0)  # noqa: F405
        w.pack_start(wrapped("Each touches only what it may. SUPER+ALT+W in a terminal: watch the job there."),
                     False, False, 0)
        self.tasks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.tasks_box, False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        # -- plain words --------------------------------------------------------------
        w.pack_start(heading("IN PLAIN WORDS"), False, False, 0)  # noqa: F405
        w.pack_start(wrapped("Describe it; the local model drafts a task for you to check and save."),
                     False, False, 0)
        words = Gtk.Box(spacing=8)
        self.text = Gtk.Entry()
        self.text.set_placeholder_text("check https://… every hour and tell me if the price drops")
        self.text.set_hexpand(True)
        self.text.connect("activate", lambda _e: self.ask_model())
        words.pack_start(self.text, True, True, 0)
        words.pack_start(link("Write the task", self.ask_model), False, False, 0)  # noqa: F405
        w.pack_start(words, False, False, 0)
        self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.preview_box, False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        # -- by hand ------------------------------------------------------------------
        w.pack_start(heading("BY HAND"), False, False, 0)  # noqa: F405
        top = Gtk.Box(spacing=8)
        self.kind = Gtk.ComboBoxText()
        self.kind.connect("changed", lambda _c: self.kind_changed())
        cell = self.kind.get_cells()[0]
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        cell.set_property("width-chars", 40)
        top.pack_start(self.kind, False, False, 0)
        w.pack_start(top, False, False, 0)
        self.form = Gtk.Grid()
        self.form.set_row_spacing(6)
        self.form.set_column_spacing(8)
        w.pack_start(self.form, False, False, 0)
        self.hand_note = wrapped("")
        w.pack_start(self.hand_note, False, False, 0)
        w.pack_start(links_row(link("Add", self.add_hand)), False, False, 0)  # noqa: F405

        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

    # -- reading -----------------------------------------------------------------------
    def refresh(self):
        if not self.tasks_box.get_children():
            self.tasks_box.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)  # noqa: F405
            self.tasks_box.show_all()

        def work():
            data = run_json(TASKS, "list", "--json", timeout=20)  # noqa: F405
            cat = self.catalog or run_json(TASKS, "catalog", timeout=20)  # noqa: F405
            active = run("systemctl", "--user", "is-active", "tasks.service").strip()  # noqa: F405
            logs = {tid: run(TASKS, "logs", tid, "-n", "15", timeout=10) for tid in self.open_logs}  # noqa: F405
            return data, cat, active, logs
        background(work, self.show)  # noqa: F405

    def show(self, result):
        data, cat, active, logs = result
        self.open_logs.update(logs)
        if cat and not self.catalog:
            self.catalog = cat
            for t in cat["types"]:
                self.kind.append(t["type"], KIND_WORDS.get(t["type"], t["type"]))
            self.kind.set_active_id("watch-command")
        if not data:
            clear(self.tasks_box)  # noqa: F405
            self.summary_sub.set_text("Could not read the tasks")
            self.file_note.set_text(f"Try it in a terminal: {TASKS} list")
            self.widget.show_all()
            return
        self.updating = True
        try:
            self.draw(data, active)
        finally:
            self.updating = False

    def draw(self, data, active):
        conf, tasks = data["settings"], data["tasks"]
        need = sum(1 for t in tasks if t.get("attention"))
        self.master.set_state(conf["enabled"])
        for key, sw in self.switches.items():
            sw.set_state(bool(conf[key]))
            sw.set_sensitive(conf["enabled"])
        self.url_chips.set([(str(m), c) for m, c in URL_MINUTES], str(conf["url_min_minutes"]))
        self.summary_sub.set_text(
            (f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}" + (f", {need} need you" if need else "")
             if conf["enabled"] else "Off: nothing runs, nothing is watched")
            + ("  ·  gamemode: heavy work waits" if data.get("gamemode") and conf["gamemode_pause"] else ""))
        self.file_note.set_text(data["file"])
        clear(self.service_box)  # noqa: F405
        if active != "active":
            grid, _ = row(WARN, "Not running: no task runs",  # noqa: F405
                          f"The service is {active or 'unknown'}.",
                          link("Start it", lambda: self.act("service", "systemctl", "--user", "enable", "--now",  # noqa: F405
                                                            "tasks.service")))
            self.service_box.pack_start(grid, False, False, 0)
        clear(self.tasks_box)  # noqa: F405
        if not tasks and not data.get("broken"):
            self.tasks_box.pack_start(wrapped("No tasks yet: write one below, in plain words or by hand."),
                                      False, False, 0)
        now = time.time()
        for t in tasks:
            self.tasks_box.pack_start(self.task_row(t, now), False, False, 0)
        for b in data.get("broken", []):
            grid, _ = row(WARN, f"Not used: {b['task']}", "; ".join(b["problems"]) +  # noqa: F405
                          "\nFix it in tasks.json (Details, above).")
            self.tasks_box.pack_start(grid, False, False, 0)
        self.widget.show_all()

    def task_row(self, t, now):
        tid = t["id"]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        ends = []
        if t["runnable"]:
            if t["status"] == "running" and t["type"] == "watch-command":
                ends.append(link("Stop", lambda: self.act(tid, TASKS, "stop", tid)))  # noqa: F405
            else:
                ends.append(link("Run", lambda: self.act(tid, TASKS, "run", tid)))  # noqa: F405
                ends[-1].set_tooltip_text("Run it now")
        ends.append(link("Hide log" if tid in self.open_logs else "Log", lambda: self.toggle_log(tid)))  # noqa: F405
        armed = self.armed == tid
        ends.append(link("Click again to delete" if armed else "Delete…", lambda: self.delete(tid)))  # noqa: F405
        sw = Gtk.Switch()
        sw.set_state(t["enabled"])
        sw.set_sensitive(tid not in self.busy)
        sw.set_tooltip_text("On: it runs on its schedule. Off: paused")
        sw.connect("state-set", lambda _s, new: self.toggled(tid, new))
        right = Gtk.Box(spacing=8)
        for item in ends + [sw]:
            item.set_valign(Gtk.Align.CENTER)
            right.pack_start(item, False, False, 0)
        icon = WARN if t.get("attention") else PAUSE if not t["enabled"] else TYPE_ICONS.get(t["type"], GEAR)
        grid, _ = row(icon, t["name"], task_sub(t, now), right)  # noqa: F405
        box.pack_start(grid, False, False, 0)
        box.pack_start(details(wrapped(task_may(t)), label="What it may do"), False, False, 0)  # noqa: F405

        extra = []
        att = t.get("attention")
        if att and not att.get("plan"):
            extra.append((f"Needs you: {att['text']}", [("Seen", lambda: self.act(tid, TASKS, "seen", tid))]))  # noqa: F405
        if t.get("plan"):
            moves = t["plan"]["moves"]
            lines = "\n".join(f"{m['from']}  →  {m['to']}" for m in moves[:12])
            more = f"\n… and {len(moves) - 12} more" if len(moves) > 12 else ""
            extra.append((f"A tidy plan waits for your OK: {len(moves)} move{'s' if len(moves) != 1 else ''} "
                          "(nothing deleted; Undo puts them back)",
                          [("Approve", lambda: self.act(tid, TASKS, "approve", tid)),  # noqa: F405
                           ("Discard", lambda: self.act(tid, TASKS, "discard", tid))]))  # noqa: F405
            extra.append((None, lines + more))
        if t.get("undo"):
            extra.append(("", [("Undo the last tidy", lambda: self.act(tid, TASKS, "undo", tid))]))  # noqa: F405
        if t.get("report"):
            extra.append(("", [("Open summary", lambda: spawn("xdg-open", t["report"]))]))  # noqa: F405
        for text, buttons in extra:
            if text is None:
                box.pack_start(mono(buttons), False, False, 0)
                continue
            if text:
                box.pack_start(wrapped(text), False, False, 0)
            box.pack_start(links_row(*[link(c, fn) for c, fn in buttons]), False, False, 0)  # noqa: F405
        if tid in self.open_logs:
            box.pack_start(mono(self.open_logs[tid].rstrip() or "(no log yet)"), False, False, 0)
        return box

    # -- by hand -----------------------------------------------------------------------
    def kind_info(self):
        kid = self.kind.get_active_id()
        return next((t for t in (self.catalog or {}).get("types", []) if t["type"] == kid), None)

    def kind_changed(self):
        clear(self.form)  # noqa: F405
        self.fields = {}
        t = self.kind_info()
        if not t:
            return
        n = 0
        for p in t["params"]:
            if p["name"] == "pattern" and p["kind"] == "regex" and p["default"]:
                hint = "a pattern; empty: errors, failures, tracebacks"
            else:
                hint = p["hint"] + ("" if p["required"] else
                                    f" (default {p['default']})" if p["default"] not in (None, "") else
                                    " (optional)")
            entry = Gtk.Entry()
            entry.set_hexpand(True)
            entry.set_placeholder_text(hint)
            self.form.attach(dp.label(p["name"], "ctl-sub"), 0, n, 1, 1)  # noqa: F405
            self.form.attach(entry, 1, n, 1, 1)
            self.fields[p["name"]] = entry
            n += 1
        self.schedule = Gtk.Entry()
        self.schedule.set_hexpand(True)
        self.schedule.set_placeholder_text(f"default {t['schedule']}  ·  allowed: "
                                           + ", ".join({"every": "every 30m|2h|1d", "at": "daily|weekdays HH:MM",
                                                        "event": "on-event"}.get(k, k) for k in t["schedules"]))
        self.name = Gtk.Entry()
        self.name.set_placeholder_text("a name for it")
        for caption, widget in (("schedule", self.schedule), ("name", self.name)):
            self.form.attach(dp.label(caption, "ctl-sub"), 0, n, 1, 1)  # noqa: F405
            self.form.attach(widget, 1, n, 1, 1)
            n += 1
        self.hand_note.set_text("")
        self.form.show_all()

    def add_hand(self):
        t = self.kind_info()
        if not t:
            return
        task = hand_task(t["type"], {k: e.get_text() for k, e in self.fields.items()},
                         self.schedule.get_text(), self.name.get_text())
        self.hand_note.set_text("adding…")

        def done(result):
            ok, out = result
            self.hand_note.set_text(out.strip() if ok else f"Not added: {out}")
            if ok:
                self.kind_changed()
                self.hand_note.set_text(out.strip())
            self.refresh()
        background(lambda: call(TASKS, "add", json.dumps(task), "--settings"), done)  # noqa: F405

    # -- plain words -------------------------------------------------------------------
    def ask_model(self):
        text = self.text.get_text().strip()
        if not text:
            return
        self.show_preview(None, "asking the local model… (the first answer can take ~30 s)")

        def work():
            ok, out = call(TASKS, "add-from-text", "--json", text, timeout=300)
            try:
                return json.loads(out)
            except ValueError:
                return {"task": None, "error": out.strip() or "no answer"}
        background(work, lambda data: self.show_preview(data, ""))  # noqa: F405

    def show_preview(self, data, waiting):
        clear(self.preview_box)  # noqa: F405
        self.preview = (data or {}).get("task")
        if waiting:
            self.preview_box.pack_start(wrapped(waiting), False, False, 0)
        elif not self.preview:
            self.preview_box.pack_start(wrapped(f"No task: {(data or {}).get('error') or 'no answer'}"),
                                        False, False, 0)
        else:
            grid, _ = row(PEN, self.preview["name"], data["words"] + "\nMay: " +  # noqa: F405
                          "; ".join(data.get("permissions") or []))
            self.preview_box.pack_start(grid, False, False, 0)
            self.preview_box.pack_start(mono(json.dumps({k: v for k, v in self.preview.items()
                                                         if k not in ("id", "created")},
                                                        indent=2, ensure_ascii=False)), False, False, 0)
            if self.preview["type"] == "watch-command":
                self.preview_box.pack_start(wrapped("It runs a command: read it before saving."), False, False, 0)
            self.preview_box.pack_start(links_row(link("Save", self.save_preview),  # noqa: F405
                                                  link("Discard", self.discard)), False, False, 0)  # noqa: F405
        self.preview_box.show_all()

    def discard(self):
        self.preview = None
        clear(self.preview_box)  # noqa: F405

    def save_preview(self):
        task = self.preview
        if not task:
            return

        def done(result):
            ok, out = result
            clear(self.preview_box)  # noqa: F405
            self.preview = None
            self.preview_box.pack_start(wrapped(out.strip() if ok else f"Not saved: {out}"), False, False, 0)
            self.preview_box.show_all()
            if ok:
                self.text.set_text("")
            self.refresh()
        background(lambda: call(TASKS, "add", json.dumps(task)), done)  # noqa: F405

    # -- changing ----------------------------------------------------------------------
    def set_option(self, key, value):
        if self.updating:
            return True
        word = ("on" if value else "off") if isinstance(value, bool) else str(value)
        self.act(key, TASKS, "set", key, word)
        return True     # the switch moves when the redraw says it did

    def toggled(self, tid, state):
        if self.updating or tid in self.busy:
            return True
        self.busy.add(tid)
        self.act(tid, TASKS, "resume" if state else "pause", tid)
        return True

    def toggle_log(self, tid):
        if tid in self.open_logs:
            self.open_logs.pop(tid)
        else:
            self.open_logs[tid] = "loading…"
        self.refresh()

    def act(self, key, *cmd):
        self.summary_sub.set_text("working…")
        background(lambda: call(*cmd, timeout=180), lambda result: self.done(result, key))  # noqa: F405

    def done(self, result, key):
        ok, out = result
        self.busy.discard(key)
        self.problem.set_text("" if ok else f"Did not work: {out}")
        self.problem.set_visible(not ok)
        GLib.timeout_add(300, lambda: (self.refresh(), False)[1])

    def delete(self, tid):
        """First click arms, the second deletes; the arming lapses after 6 s."""
        if self.armed == tid:
            self.armed = ""
            self.open_logs.pop(tid, None)
            self.act(tid, TASKS, "delete", tid)
            return
        self.armed = tid
        self.refresh()
        GLib.timeout_add(6000, lambda: (self.disarm(tid), False)[1])

    def disarm(self, tid):
        if self.armed == tid:
            self.armed = ""
            self.refresh()
