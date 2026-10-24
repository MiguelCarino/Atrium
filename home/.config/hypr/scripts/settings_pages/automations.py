"""Settings page: automations -- "when X, do Y" rules (automations.py,
followed by automations.service).

Top to bottom:

    YOUR RULES      each rule in words ("When Steam opens: turn Do Not
                    Disturb on"), when it last ran, a switch, Test (its
                    actions now) and Delete (asks first; a built-in rule
                    has no Delete, only its switch). A rule the loop guard
                    paused says so; switching it on again lifts the pause.
                    Rules the file has but that do not check out are listed
                    with the reason.
    IN PLAIN WORDS  a sentence -> the local "quick" model writes the rule
                    (automations.py add-from-text --json: checked strictly,
                    never a cloud model) -> a preview, in words and as JSON
                    -> Save or Discard. Nothing is saved before Save.
    PICK ONE        the same without a model: one event and its option, one
                    action and its value, a name -> Add.

Every control runs automations.py (list --json, enable, disable, delete,
add, add-from-text, test) in a thread and redraws from what it reports; the
page keeps nothing of its own, and automations.json stays the one place
the rules are (hand edits show up on the next refresh). The file, its
Open button and the watched event names sit in a Details fold up top.
"""
import json
import os
import subprocess
import time

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import GLib, Gtk, Pango  # noqa: F401,E402  (after common: it picks GTK 3)

PAGE = {"id": "automations", "title": "Automations", "icon": "", "group": "System", "order": 65, "parent": "startup", "tab": "Automations",
        "keywords": ["rules", "when", "trigger", "if this then that", "ifttt", "automatic", "automate",
                     "routines", "scenes", "on connect", "headphones", "wifi", "game starts", "app opens",
                     "schedule", "digest", "automatizaciones", "reglas"]}

AUTOMATIONS = os.path.join(HYPR, "automations.py")  # noqa: F405
RULES_FILE = os.path.expanduser("~/.config/hypr/automations.json")
BOLT, WARN, PAUSE, PEN = "", "", "", ""

# What the option / value entry asks for, by the catalog's kind.
OPTION_HINTS = {"class": "app class, e.g. steam or firefox", "name": "screen name, optional (DP-1, HDMI)",
                "device": "output name, optional (headphones, HDMI)", "ssid": "network name, optional",
                "at": "HH:MM", "days": "days, optional (weekdays, mon,wed)",
                # by event, where its option means something else than above
                "context-enter": "project name, optional (atlas)", "context-leave": "project name, optional"}
VALUE_HINTS = {"text": "", "two": "CARD PROFILE", "name": "session name"}
ACTION_HINTS = {"sound-output": "part of its name: headphones, HDMI", "notify": "the message",
                "shell": "a shell command", "open": "an app: firefox, org.gnome.Nautilus",
                "context": "a project context's name, or leave",
                "task": "a background task's id (Settings > Background tasks)",
                "focus": "minutes (25), or off to end the block"}


# -- words (pure: tests/test_automations.py) ------------------------------------------------
def last_ran(epoch, now=None):
    """"ran 5 min ago" / "ran yesterday 21:30" / "not run yet" (since the
    service started)."""
    if not epoch:
        return "not run yet"
    now = now if now is not None else time.time()
    delta = now - epoch
    if delta < 90:
        return "ran just now"
    if delta < 5400:
        return f"ran {int(delta // 60)} min ago"
    if delta < 86400 and time.localtime(epoch).tm_mday == time.localtime(now).tm_mday:
        return "ran today " + time.strftime("%H:%M", time.localtime(epoch))
    return "ran " + time.strftime("%a %d %b %H:%M", time.localtime(epoch))


def rule_sub(r, now=None):
    bits = [r["words"], last_ran(r.get("last"), now) if r["enabled"] else "off"]
    if r.get("builtin"):
        bits.append("built in")
    text = "\n".join(bits[:1]) + "\n" + "  ·  ".join(bits[1:])
    if r.get("paused"):
        text += f"\nPaused: {r['paused']} -- switch on to resume."
    return text


def picked_rule(name, event, option_key, option, action, value):
    """The rule the pickers describe (automations.py add checks it)."""
    when = {"event": event}
    if option_key and option.strip():
        when[option_key] = option.strip()
    act = {"action": action}
    if value.strip():
        act["value"] = value.strip()
    return {"name": name.strip() or "My rule", "enabled": True, "when": when, "do": [act]}


def call(*cmd, timeout=60):
    """(ok, output or what went wrong)."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    if done.returncode == 0:
        return True, done.stdout
    lines = [l for l in (done.stderr or done.stdout).strip().splitlines() if l.strip()]
    return False, (lines[-1] if lines else f"exit status {done.returncode}").removeprefix("automations: ")


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.updating = False
        self.busy = set()
        self.armed = ""             # the rule whose Delete waits for a second click
        self.catalog = None
        self.preview = None         # the model's rule waiting for Save
        self.option_key = None      # the event option the "When" entry fills

        self.summary, self.summary_sub = row(BOLT, "Automations", "checking…")  # noqa: F405
        w.pack_start(self.summary, False, False, 0)
        self.service_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.service_box, False, False, 0)
        w.pack_start(links_row(link("Check again", self.refresh)), False, False, 0)  # noqa: F405
        self.file_note = wrapped("")
        w.pack_start(details(self.file_note, links_row(  # noqa: F405
            link("Open automations.json", lambda: spawn("xdg-open", RULES_FILE)))), False, False, 0)  # noqa: F405
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        w.pack_start(heading("YOUR RULES"), False, False, 0)  # noqa: F405
        w.pack_start(wrapped("Each fires on a change; one that repeats too fast pauses itself."), False, False, 0)
        self.rules_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.rules_box, False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        # -- plain words ------------------------------------------------------------
        w.pack_start(heading("IN PLAIN WORDS"), False, False, 0)  # noqa: F405
        w.pack_start(wrapped("Describe it; the local model drafts a rule for you to check and save."),
                     False, False, 0)
        words = Gtk.Box(spacing=8)
        self.text = Gtk.Entry()
        self.text.set_placeholder_text("when I open Steam, turn on Do Not Disturb")
        self.text.set_hexpand(True)
        self.text.connect("activate", lambda _e: self.ask_model())
        words.pack_start(self.text, True, True, 0)
        words.pack_start(link("Write the rule", self.ask_model), False, False, 0)  # noqa: F405
        w.pack_start(words, False, False, 0)
        self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.preview_box, False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        # -- pickers ----------------------------------------------------------------
        w.pack_start(heading("PICK ONE"), False, False, 0)  # noqa: F405
        grid = Gtk.Grid()
        grid.set_row_spacing(6)
        grid.set_column_spacing(8)
        self.event = Gtk.ComboBoxText()
        self.event.connect("changed", lambda _c: self.event_changed())
        self.option = Gtk.Entry()
        self.option.set_hexpand(True)
        self.action = Gtk.ComboBoxText()
        self.action.connect("changed", lambda _c: self.action_changed())
        self.value = Gtk.ComboBoxText.new_with_entry()
        self.value.set_hexpand(True)
        for combo in (self.event, self.action):
            # Sized by their longest item otherwise, which squeezes the entries beside them.
            cell = combo.get_cells()[0]
            cell.set_property("ellipsize", Pango.EllipsizeMode.END)
            cell.set_property("width-chars", 30)
        self.name = Gtk.Entry()
        self.name.set_placeholder_text("a name for it")
        for n, (caption, left, right) in enumerate((("When", self.event, self.option),
                                                     ("Do", self.action, self.value),
                                                     ("Called", self.name, None))):
            grid.attach(dp.label(caption, "ctl-sub"), 0, n, 1, 1)  # noqa: F405
            grid.attach(left, 1, n, 1, 1)
            if right is not None:
                grid.attach(right, 2, n, 1, 1)
        w.pack_start(grid, False, False, 0)
        self.pick_note = wrapped("")
        w.pack_start(self.pick_note, False, False, 0)
        w.pack_start(links_row(link("Add", self.add_picked)), False, False, 0)  # noqa: F405

        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

    # -- reading -----------------------------------------------------------------------
    def refresh(self):
        if not self.rules_box.get_children():
            self.rules_box.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)  # noqa: F405
            self.rules_box.show_all()

        def work():
            data = run_json(AUTOMATIONS, "list", "--json", timeout=20)  # noqa: F405
            cat = self.catalog or run_json(AUTOMATIONS, "catalog", timeout=20)  # noqa: F405
            active = run("systemctl", "--user", "is-active", "automations.service").strip()  # noqa: F405
            return data, cat, active
        background(work, self.show)  # noqa: F405

    def show(self, result):
        data, cat, active = result
        if cat and not self.catalog:
            self.catalog = cat
            self.fill_pickers()
        if not data:
            clear(self.rules_box)  # noqa: F405
            self.summary_sub.set_text("Could not read the rules")
            self.file_note.set_text(f"Try it in a terminal: {AUTOMATIONS} list")
            self.widget.show_all()
            return
        self.updating = True
        try:
            self.draw(data, active)
        finally:
            self.updating = False

    def draw(self, data, active):
        rules = data["rules"]
        on = sum(1 for r in rules if r["enabled"])
        watching = ", ".join(data.get("watching") or []) or "nothing"
        self.summary_sub.set_text(f"{on} of {len(rules)} rule{'s' if len(rules) != 1 else ''} on")
        self.file_note.set_text(f"Watching: {watching}\n{data['file']}")
        clear(self.service_box)  # noqa: F405
        if active != "active":
            grid, _ = row(WARN, "Not running: no rule fires",  # noqa: F405
                          f"The service is {active or 'unknown'}.",
                          link("Start it", lambda: self.act("service", "systemctl", "--user", "enable", "--now",  # noqa: F405
                                                            "automations.service")))
            self.service_box.pack_start(grid, False, False, 0)
        clear(self.rules_box)  # noqa: F405
        now = time.time()
        for r in rules:
            sw = Gtk.Switch()
            sw.set_state(r["enabled"] and not r.get("paused"))
            sw.set_sensitive(r["id"] not in self.busy)
            sw.connect("state-set", lambda _s, new, rid=r["id"]: self.toggled(rid, new))
            ends = [link("Test", lambda rid=r["id"]: self.act(rid, AUTOMATIONS, "test", rid))]  # noqa: F405
            ends[0].set_tooltip_text("Run its actions now, as if it had fired")
            if not r.get("builtin"):
                armed = self.armed == r["id"]
                ends.append(link("Click again to delete" if armed else "Delete…",  # noqa: F405
                                 lambda rid=r["id"]: self.delete(rid)))
            box = Gtk.Box(spacing=8)
            for item in ends + [sw]:
                item.set_valign(Gtk.Align.CENTER)
                box.pack_start(item, False, False, 0)
            icon = PAUSE if r.get("paused") else BOLT
            grid, _ = row(icon, r["name"], rule_sub(r, now), box)  # noqa: F405
            self.rules_box.pack_start(grid, False, False, 0)
        for b in data.get("broken", []):
            grid, _ = row(WARN, f"Not used: {b['rule']}", "; ".join(b["problems"]) +  # noqa: F405
                          "\nFix it in automations.json (Details, above).")
            self.rules_box.pack_start(grid, False, False, 0)
        self.widget.show_all()

    # -- pickers -----------------------------------------------------------------------
    def fill_pickers(self):
        for e in self.catalog["events"]:
            self.event.append(e["event"], e["words"].replace("…", "[app]" if e["event"].startswith("app")
                                                             else "[time]"))
        for a in self.catalog["actions"]:
            self.action.append(a["action"], a["words"])
        self.event.set_active_id("app-open")
        self.action.set_active_id("dnd")

    def event_info(self):
        eid = self.event.get_active_id()
        return next((e for e in (self.catalog or {}).get("events", []) if e["event"] == eid), None)

    def event_changed(self):
        e = self.event_info()
        opts = e["options"] if e else []
        self.option.set_sensitive(bool(opts))
        self.option.set_text("")
        # The pickers take one option: the required one, else the first.
        key = (e["required"] or opts or [None])[0] if e else None
        self.option.set_placeholder_text((OPTION_HINTS.get(e["event"]) or OPTION_HINTS.get(key, ""))
                                         if key else "no option")
        self.option_key = key

    def action_changed(self):
        aid = self.action.get_active_id()
        a = next((x for x in (self.catalog or {}).get("actions", []) if x["action"] == aid), None)
        kind = a["value"] if a else None
        self.value.remove_all()
        entry = self.value.get_child()
        entry.set_text("")
        choices = {"on-off": ["on", "off"], "on-off-auto": ["on", "off", "auto"],
                   "theme": self.catalog.get("themes", []) if self.catalog else []}.get(kind, [])
        for c in choices:
            self.value.append(c, c)
        if choices:
            self.value.set_active(0)
        self.value.set_sensitive(kind is not None)
        entry.set_placeholder_text(ACTION_HINTS.get(aid) or VALUE_HINTS.get(kind, "") if kind else "no value")

    def add_picked(self):
        rule = picked_rule(self.name.get_text(), self.event.get_active_id() or "",
                           self.option_key, self.option.get_text(),
                           self.action.get_active_id() or "", self.value.get_child().get_text())
        self.pick_note.set_text("adding…")

        def done(result):
            ok, out = result
            self.pick_note.set_text(out.strip() if ok else f"Not added: {out}")
            if ok:
                self.name.set_text("")
                self.option.set_text("")
            self.refresh()
        background(lambda: call(AUTOMATIONS, "add", json.dumps(rule)), done)  # noqa: F405

    # -- plain words -------------------------------------------------------------------
    def ask_model(self):
        text = self.text.get_text().strip()
        if not text:
            return
        self.show_preview(None, "asking the local model… (the first answer can take ~30 s)")

        def work():
            ok, out = call(AUTOMATIONS, "add-from-text", "--json", text, timeout=300)
            try:
                return json.loads(out)
            except ValueError:
                return {"rule": None, "error": out.strip() or "no answer"}
        background(work, lambda data: self.show_preview(data, ""))  # noqa: F405

    def show_preview(self, data, waiting):
        clear(self.preview_box)  # noqa: F405
        self.preview = (data or {}).get("rule")
        if waiting:
            self.preview_box.pack_start(wrapped(waiting), False, False, 0)
        elif not self.preview:
            self.preview_box.pack_start(wrapped(f"No rule: {(data or {}).get('error') or 'no answer'}"),
                                        False, False, 0)
        else:
            grid, _ = row(PEN, self.preview["name"], data["words"])  # noqa: F405
            self.preview_box.pack_start(grid, False, False, 0)
            code = wrapped(json.dumps({k: v for k, v in self.preview.items() if k != "id"}, indent=2,
                                      ensure_ascii=False))
            code.set_selectable(True)
            code.override_font(Pango.FontDescription("monospace 9"))
            self.preview_box.pack_start(code, False, False, 0)
            if any(a["action"] in ("shell", "open") for a in self.preview["do"]):
                self.preview_box.pack_start(wrapped("It runs a command: read it before saving."), False, False, 0)
            self.preview_box.pack_start(links_row(link("Save", self.save_preview),  # noqa: F405
                                                  link("Discard", self.discard)), False, False, 0)  # noqa: F405
        self.preview_box.show_all()

    def discard(self):
        self.preview = None
        clear(self.preview_box)  # noqa: F405

    def save_preview(self):
        rule = self.preview
        if not rule:
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
        background(lambda: call(AUTOMATIONS, "add", json.dumps(rule)), done)  # noqa: F405

    # -- changing ----------------------------------------------------------------------
    def toggled(self, rid, state):
        if self.updating or rid in self.busy:
            return True
        self.busy.add(rid)
        background(lambda: call(AUTOMATIONS, "enable" if state else "disable", rid),  # noqa: F405
                   lambda result: self.done(result, rid))
        return True     # the switch moves when the redraw says it did

    def act(self, key, *cmd):
        self.summary_sub.set_text("working…")
        background(lambda: call(*cmd, timeout=180), lambda result: self.done(result, key))  # noqa: F405

    def done(self, result, key):
        ok, out = result
        self.busy.discard(key)
        self.problem.set_text("" if ok else f"Did not work: {out}")
        self.problem.set_visible(not ok)
        GLib.timeout_add(300, lambda: (self.refresh(), False)[1])

    def delete(self, rid):
        """First click arms, the second deletes; the arming lapses after 6 s."""
        if self.armed == rid:
            self.armed = ""
            self.act(rid, AUTOMATIONS, "delete", rid)
            return
        self.armed = rid
        self.refresh()
        GLib.timeout_add(6000, lambda: (self.disarm(rid), False)[1])

    def disarm(self, rid):
        if self.armed == rid:
            self.armed = ""
            self.refresh()
