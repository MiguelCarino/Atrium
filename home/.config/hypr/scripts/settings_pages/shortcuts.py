"""Settings page: every keyboard shortcut, and your own changes to them.

The list is what Hyprland has live (`hyprctl binds -j`), by the bind's
description ("Group: Action"), grouped like the shortcuts panel (SUPER+F1)
groups it. Any shortcut can go on other keys, be turned off, or go back to
its default; you can add shortcuts of your own that run a command or open an
app; Reset all undoes everything. Two shortcuts on the same keys are marked:
both fire, which is rarely what anyone wants.

Every change goes through ~/.config/hypr/scripts/shortcuts.py, which keeps
the changes in ~/.local/state/hypr/userbinds.conf (never in lua/binds.lua,
which stays the defaults) and has the running Hyprland re-read that file
through lua/userbinds.lua -- the same code that puts them back after a
reload or a re-login. The page then redraws from what Hyprland reports, so
a change it refused shows as refused, not as done.

"Press the new keys": a box that reads the next keys you press. While it is
open Hyprland is in its "keycapture" mode (shortcuts.py capture on), so the
keys reach this window instead of firing whatever shortcut is on them now;
the box turns it off again when it closes, after 15 seconds, or when the
window loses focus, and shortcuts.py's own watchdog turns it off after 20
seconds even if this window died. SUPER+Escape leaves it by hand.
"""
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import importlib.util  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

PAGE = {"id": "shortcuts", "title": "Keyboard shortcuts", "icon": "", "group": "Hardware", "order": 35,
        "keywords": ["keybinds", "keybindings", "hotkeys", "keys", "bind", "rebind", "shortcut", "custom shortcut",
                     "conflict", "super", "atajos", "teclado"]}

BACKEND = os.path.join(HYPR, "shortcuts.py")  # noqa: F405


def _backend():
    """scripts/shortcuts.py as a module, for its pure helpers and gather()
    (reading only: every change runs it as a command, see attempt())."""
    spec = importlib.util.spec_from_file_location("shortcuts_backend", BACKEND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sc = _backend()

try:
    # The shortcuts panel's reading order, so the page and SUPER+F1 agree.
    import keybinds_panel as _kp  # noqa: E402  (waybar/scripts, on the path via common)
    SECTION_ORDER = _kp.SECTION_ORDER
    KEY_NAMES = _kp.KEY_NAMES
except Exception:  # noqa: BLE001 -- the page works without it, in a plainer order
    SECTION_ORDER, KEY_NAMES = [], {}

CAPTURE_SECONDS = 15
FILTERS = [("all", "All"), ("changed", "Changed"), ("shared", "Shared keys"), ("off", "Turned off")]


def attempt(*args, timeout=20):
    """Run shortcuts.py; (exit code, its message). Exit 3 means "those keys
    are taken" (the message names by what). Called from background() only."""
    try:
        r = subprocess.run([BACKEND, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"shortcuts.py: {exc}"
    text = (r.stdout if r.returncode == 0 else r.stderr).strip()
    return r.returncode, (text.splitlines() or [""])[-1]


def caps(keys):
    """SUPER+SHIFT+Return -> ["Super", "Shift", "Enter"], the key caps shown."""
    parts = keys.split("+")
    mods = [m.capitalize() if m.isupper() else m for m in parts[:-1]]
    key = parts[-1] if parts else keys
    return mods + [KEY_NAMES.get(key, key.upper() if len(key) == 1 else key)]


def section_key(group):
    return (-1 if group == "Custom" else SECTION_ORDER.index(group) if group in SECTION_ORDER else len(SECTION_ORDER),
            group.endswith(" mode"), group == "Other", group)


def matches(entry, query):
    """Every typed word somewhere in the keys, the group or the action."""
    hay = " ".join([entry["keys"], " ".join(caps(entry["keys"])), entry["desc"], entry.get("cmd") or "",
                    entry["default"] or ""]).casefold()
    return all(word in hay for word in query.casefold().split())


def shown_by(entry, which):
    if which == "changed":
        return entry["state"] in ("moved", "off", "custom") or entry["pending"]
    if which == "shared":
        return bool(entry["conflicts"])
    if which == "off":
        return entry["state"] == "off"
    return True


def entry_sub(e):
    """The grey line under a shortcut: what is special about it."""
    bits = []
    if e["state"] == "moved":
        bits.append(f"moved here from {sc.nice(e['default'])}")
    elif e["state"] == "off":
        bits.append(f"turned off (its keys were {sc.nice(e['default'])})")
    elif e["state"] == "custom":
        bits.append(f"yours: runs {e['cmd']}")
    elif e["state"] == "mode":
        bits.append(f"only inside the {e['submap']} mode")
    elif e["state"] == "fixed":
        bits.append("made outside the shortcut list, so it can't be changed here")
    if e["mouse"]:
        bits.append("a mouse button: hold the keys and press it")
    if e["pending"]:
        bits.append("not loaded into Hyprland yet" + (f" (wanted: {e['wanted']})" if e.get("wanted") else ""))
    if e["conflicts"]:
        bits.append("!  these keys also do: " + "; ".join(e["conflicts"]) + " -- both fire")
    return "  ·  ".join(bits)


def mode_key_title(e):
    """A key inside a mode has no description of its own (the resize mode's
    arrows, Esc, Enter): say what such keys usually do there."""
    if not e["submap"]:
        return "(no description)"
    key = e["keys"].split("+")[-1].lower()
    if key in ("escape", "return"):
        return "Leave the mode"
    if key in ("left", "right", "up", "down"):
        return f"{e['submap'].capitalize()} ({KEY_NAMES.get(key, key)})"
    return "A key inside the mode"


class KeyCapture:
    """The "press the new keys" box: a popover under the button that opened
    it. on_keys(keys) when you confirm. Hyprland's keycapture mode is on
    while it is open (see the module docstring)."""

    def __init__(self, button, title, on_keys, occupied):
        self.on_keys, self.occupied = on_keys, occupied
        self.keys, self.handlers, self.timer = None, [], None
        self.pop = Gtk.Popover.new(button)
        self.pop.set_position(Gtk.PositionType.BOTTOM)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(10)
        box.pack_start(dp.label(title, "ctl-title"), False, False, 0)  # noqa: F405
        self.shown = dp.label("Press the new keys now…", "kb-heading")  # noqa: F405
        box.pack_start(self.shown, False, False, 0)
        self.note = dp.label(f"Every shortcut is paused while this is open (at most {CAPTURE_SECONDS} s). "  # noqa: F405
                             "Esc on its own cancels.", "ctl-sub")
        self.note.set_line_wrap(True)
        self.note.set_max_width_chars(48)
        box.pack_start(self.note, False, False, 0)
        self.use = Gtk.Button(label="Use these keys")
        self.use.get_style_context().add_class("dev-pick")
        self.use.set_sensitive(False)
        self.use.connect("clicked", lambda _b: self.confirm())
        box.pack_start(links_row(self.use, link("Cancel", self.pop.popdown)), False, False, 0)  # noqa: F405
        self.pop.add(box)
        self.pop.connect("closed", lambda _p: self.stop())

    def open(self):
        self.pop.show_all()
        self.pop.popup()
        top = self.pop.get_toplevel()
        self.handlers = [(top, top.connect("key-press-event", self.on_key)),
                         (top, top.connect("focus-out-event", lambda *_: (self.pop.popdown(), False)[1]))]
        self.timer = GLib.timeout_add_seconds(CAPTURE_SECONDS, lambda: (self.pop.popdown(), False)[1])
        background(lambda: attempt("capture", "on"), lambda _r: None)  # noqa: F405

    def stop(self):
        for widget, hid in self.handlers:
            widget.disconnect(hid)
        self.handlers = []
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        background(lambda: attempt("capture", "off"), lambda _r: None)  # noqa: F405

    def on_key(self, _w, event):
        state = event.state
        mods = set()
        if state & (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK):
            mods.add("SUPER")
        if state & Gdk.ModifierType.CONTROL_MASK:
            mods.add("CTRL")
        if state & Gdk.ModifierType.MOD1_MASK:
            mods.add("ALT")
        if state & Gdk.ModifierType.SHIFT_MASK:
            mods.add("SHIFT")
        # The key as it is without Shift ("1", not "exclam"): that is how
        # Hyprland matches a bind.
        keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
        found = keymap.translate_keyboard_state(event.hardware_keycode, 0, event.group)
        name = Gdk.keyval_name(found[1] if found and found[0] else event.keyval)
        if name == "Escape" and not mods:
            self.pop.popdown()
            return True
        keys = sc.keys_from_event(mods, name)
        if keys is None:
            return True                     # only modifiers so far
        self.keys = keys
        self.shown.set_text("  +  ".join(caps(keys)))
        notes = []
        taken = self.occupied(keys)
        if taken:
            notes.append("Already used by: " + "; ".join(taken) + ". Using them turns that off.")
        warn = sc.app_safe(keys)
        if warn:
            notes.append(warn + ".")
        if sc.canon(keys) == "SUPER+ESCAPE":
            notes, self.keys = ["SUPER+Escape is kept free: it is the way out of this mode."], None
        self.note.set_text(" ".join(notes) or "Free. Press other keys to try again.")
        self.use.set_sensitive(self.keys is not None)
        return True

    def confirm(self):
        keys = self.keys
        self.pop.popdown()
        if keys:
            self.on_keys(keys)


class Page:
    def __init__(self):
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.entries, self.rows, self.headings, self.sig = [], [], {}, None
        self.filter, self.new_keys, self.reset_armed = "all", None, None

        self.error = dp.label("", "ctl-sub")  # noqa: F405
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        w.pack_start(heading("YOUR CHANGES"), False, False, 0)  # noqa: F405
        grid, self.status_sub = row("", "Changed shortcuts", "checking…")  # noqa: F405
        w.pack_start(grid, False, False, 0)
        self.problems = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.problems, False, False, 0)
        self.reset_btn = link("Reset all", self.reset_all)  # noqa: F405
        self.load_btn = link("Load into Hyprland now", lambda: self.do("apply"))  # noqa: F405
        w.pack_start(links_row(self.load_btn,  # noqa: F405
                               link("Open the file", self.open_file),  # noqa: F405
                               link("Shortcuts panel", lambda: spawn(os.path.join(WAYBAR, "keybinds_panel.py"))),  # noqa: F405
                               self.reset_btn), False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        w.pack_start(heading("ADD A SHORTCUT OF YOUR OWN"), False, False, 0)  # noqa: F405
        w.pack_start(self.add_form(), False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        w.pack_start(heading("EVERY SHORTCUT"), False, False, 0)  # noqa: F405
        top = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search by keys or by what they do (e.g. \"super q\", \"screenshot\")")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", lambda _e: self.apply_filter())
        top.pack_start(self.search, True, True, 0)
        w.pack_start(top, False, False, 0)
        self.chips = Chips(self.pick_filter)  # noqa: F405
        self.chips.widget.set_max_children_per_line(4)
        self.chips.widget.set_min_children_per_line(4)
        self.chips.widget.set_halign(Gtk.Align.START)
        w.pack_start(self.chips.widget, False, False, 0)
        self.count = dp.label("", "ctl-sub")  # noqa: F405
        w.pack_start(self.count, False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.list, False, False, 0)

    # -- the add form ----------------------------------------------------------------
    def add_form(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hint = dp.label("Pick what it does, give it a name, press its keys. Keys with Super or Alt in them "  # noqa: F405
                        "are safest: anything else is taken from every app.", "ctl-sub")
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        self.kind = "app"
        self.kind_chips = Chips(self.pick_kind)  # noqa: F405
        self.kind_chips.widget.set_min_children_per_line(2)
        self.kind_chips.widget.set_halign(Gtk.Align.START)
        self.kind_chips.set([("app", "Open an app"), ("cmd", "Run a command")], self.kind)
        box.pack_start(self.kind_chips.widget, False, False, 0)

        self.app_combo = Gtk.ComboBoxText()
        self.apps_loaded = False
        self.cmd_entry = Gtk.Entry()
        self.cmd_entry.set_placeholder_text("a shell command, e.g.  firefox --private-window")
        self.cmd_entry.set_no_show_all(True)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_placeholder_text("its name in the list (optional)")
        line = Gtk.Box(spacing=8)
        line.pack_start(self.app_combo, True, True, 0)
        line.pack_start(self.cmd_entry, True, True, 0)
        line.pack_start(self.name_entry, True, True, 0)
        box.pack_start(line, False, False, 0)

        self.keys_btn = Gtk.Button(label="Press the keys…")
        self.keys_btn.get_style_context().add_class("dev-pick")
        self.keys_btn.connect("clicked", lambda b: KeyCapture(
            b, "The keys for your new shortcut", self.got_new_keys, self.occupied).open())
        self.add_btn = Gtk.Button(label="Add")
        self.add_btn.get_style_context().add_class("dev-pick")
        self.add_btn.connect("clicked", lambda _b: self.add())
        keys_line = Gtk.Box(spacing=8)
        keys_line.pack_start(self.keys_btn, False, False, 0)
        keys_line.pack_end(self.add_btn, False, False, 0)
        box.pack_start(keys_line, False, False, 0)
        return box

    def fill_apps(self):
        """Every app the launcher would list, by name; filled the first time
        the page is shown (reading the .desktop files is done in the
        background, so the page never waits for it)."""
        if self.apps_loaded:
            return
        self.apps_loaded = True
        self.app_combo.append("", "Pick the app…")
        self.app_combo.set_active_id("")

        def work():
            apps = [(a.get_id(), a.get_display_name()) for a in Gio.AppInfo.get_all()
                    if a.should_show() and a.get_id()]
            return sorted(apps, key=lambda a: a[1].casefold())

        def fill(apps):
            for app_id, name in apps:
                self.app_combo.append(app_id, name)
        background(work, fill)  # noqa: F405

    def pick_kind(self, kind):
        self.kind = kind
        self.kind_chips.set([("app", "Open an app"), ("cmd", "Run a command")], kind)
        self.app_combo.set_visible(kind == "app")
        self.cmd_entry.set_visible(kind == "cmd")

    def got_new_keys(self, keys):
        self.new_keys = keys
        self.keys_btn.set_label("Keys: " + " + ".join(caps(keys)) + "  (change)")

    def add(self):
        if not self.new_keys:
            self.show_error("Press the keys for it first (the \"Press the keys…\" button).")
            return
        name = self.name_entry.get_text().strip()
        if self.kind == "app":
            app = self.app_combo.get_active_id()
            if not app:
                self.show_error("Pick the app it opens first.")
                return
            args = ["add-app", self.new_keys, app, "--name", name or "Open " + self.app_combo.get_active_text()]
        else:
            cmd = self.cmd_entry.get_text().strip()
            if not cmd:
                self.show_error("Type the command it runs first.")
                return
            args = ["add", self.new_keys, cmd] + (["--name", name] if name else [])
        if self.occupied(self.new_keys):
            args.append("--replace")        # the capture box said what it turns off

        def after(result):
            if result[0] == 0:
                self.new_keys = None
                self.keys_btn.set_label("Press the keys…")
                self.name_entry.set_text("")
                self.cmd_entry.set_text("")
            self.done(result)
        background(lambda: attempt(*args), after)  # noqa: F405

    # -- actions ---------------------------------------------------------------------
    def occupied(self, keys):
        """What already fires on these keys (outside a mode)."""
        return [e["desc"] or e["keys"] for e in sc.occupants(self.entries, keys)]

    def do(self, *args):
        background(lambda: attempt(*args), self.done)  # noqa: F405

    def done(self, result):
        code, text = result
        self.show_error(text if code else "")
        self.refresh()

    def show_error(self, text):
        self.error.set_text(f"!  {text}" if text else "")
        self.error.set_visible(bool(text))

    def change(self, e, keys):
        # --default: e["default"] names this shortcut by its default keys
        # only -- after a swap they can be the keys another one is on now.
        args = ["move", e["default"], keys, "--default"]
        if self.occupied_by_others(e, keys):
            args.append("--replace")
        self.do(*args)

    def occupied_by_others(self, e, keys):
        return [o for o in sc.occupants(self.entries, keys) if o is not e]

    def change_custom(self, e, keys):
        """Your own shortcut on other keys: added on the new ones, then
        removed from the old ones (one command each, in order)."""
        name = e["desc"]
        args = ["add", keys, e["cmd"], "--name", name]
        if self.occupied_by_others(e, keys):
            args.append("--replace")

        def work():
            first = attempt(*args)
            if first[0] != 0 or sc.canon(keys) == sc.canon(e["keys"]):
                return first
            return attempt("remove", e["keys"])
        background(work, self.done)  # noqa: F405

    def remove_custom(self, button, e):
        """Two clicks too: removing one of your own shortcuts loses the
        command you typed for it."""
        if getattr(button, "armed", None):
            GLib.source_remove(button.armed)
            button.armed = None
            self.do("remove", e["keys"])
            return
        button.set_label("Click again to remove")

        def disarm():
            button.armed = None
            button.set_label("Remove")
            return False
        button.armed = GLib.timeout_add_seconds(4, disarm)

    def reset_all(self):
        """Two clicks, like the power buttons: Reset all throws away every
        change and every shortcut of your own."""
        if self.reset_armed:
            GLib.source_remove(self.reset_armed)
            self.reset_armed = None
            self.reset_btn.set_label("Reset all")
            self.do("reset")
            return
        self.reset_btn.set_label("Click again to reset all")
        self.reset_armed = GLib.timeout_add_seconds(4, self.disarm)

    def disarm(self):
        self.reset_armed = None
        self.reset_btn.set_label("Reset all")
        return False

    def open_file(self):
        if os.path.exists(sc.FILE):
            spawn("xdg-open", sc.FILE)  # noqa: F405
        else:
            self.show_error("No changes yet, so there is no file: it appears with the first one.")

    def pick_filter(self, which):
        self.filter = which
        self.apply_filter()

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        self.fill_apps()
        self.pick_kind(self.kind)

        def work():
            entries, ok, loaded, errors = sc.gather()
            return entries, ok, loaded, errors, sc.load()
        background(work, self.show)  # noqa: F405

    def show(self, result):
        entries, ok, loaded, errors, over = result
        if not ok:
            self.status_sub.set_text("hyprctl did not answer, so the shortcuts can't be read (is Hyprland running?)")
            return
        self.entries = entries
        n_moved, n_off, n_own = len(over["moves"]), len(over["off"]), len(over["adds"])
        pending = sum(1 for e in entries if e["pending"])
        if n_moved or n_off or n_own:
            bits = [f"{n} {what}" for n, what in ((n_moved, "on other keys"), (n_off, "turned off"),
                                                   (n_own, "of your own")) if n]
            sub = ", ".join(bits) + f"  ·  kept in {sc.FILE.replace(os.path.expanduser('~'), '~')}"
        else:
            sub = "none: every shortcut is on its default keys (lua/binds.lua)"
        if not loaded:
            sub += ("  ·  Hyprland has not loaded the module that applies them (lua/userbinds.lua) yet; it "
                    "does at the next reload or login")
        elif pending:
            sub += f"  ·  {pending} not loaded into Hyprland yet"
        self.status_sub.set_text(sub)
        self.load_btn.set_visible(loaded and pending > 0)
        self.reset_btn.set_sensitive(bool(n_moved or n_off or n_own))
        clear(self.problems)  # noqa: F405
        for err in errors:
            lab = dp.label(f"!  {err}", "ctl-sub")  # noqa: F405
            lab.set_line_wrap(True)
            self.problems.pack_start(lab, False, False, 0)
        self.problems.show_all()

        counts = {key: sum(1 for e in entries if shown_by(e, key)) for key, _ in FILTERS}
        self.chips.set([(key, f"{text} ({counts[key]})" if key != "all" else f"{text} ({len(entries)})")
                        for key, text in FILTERS], self.filter)
        # Rebuilt only when something changed: a redraw after a click keeps
        # the scroll position and the search.
        sig = repr([(e["keys"], e["state"], e["pending"], e["desc"], e["conflicts"]) for e in entries])
        if sig != self.sig:
            self.sig = sig
            self.build_rows(entries)
        self.apply_filter()

    def build_rows(self, entries):
        clear(self.list)  # noqa: F405
        self.rows, self.headings = [], {}
        groups = {}
        for e in entries:
            # A mode's own keys (the resize mode's arrows) under the mode's
            # name, not lost in "Other".
            if e["submap"]:
                e["group"] = f"{e['submap'].capitalize()} mode"
            groups.setdefault(e["group"], []).append(e)
        for group in sorted(groups, key=section_key):
            head = heading(group.upper())  # noqa: F405
            self.list.pack_start(head, False, False, 0)
            self.headings[group] = head
            for e in sorted(groups[group], key=lambda e: (e["what"].casefold(), e["keys"])):
                widget = self.entry_row(e)
                self.list.pack_start(widget, False, False, 0)
                self.rows.append((e, widget))
        self.list.show_all()

    def entry_row(self, e):
        grid = Gtk.Grid()
        grid.get_style_context().add_class("ctl-row")
        grid.set_column_spacing(12)
        keycaps = Gtk.Box(spacing=3)
        keycaps.set_size_request(230, -1)
        keycaps.set_valign(Gtk.Align.CENTER)
        for part in caps(e["keys"]):
            cap = Gtk.Label(label=part)
            cap.get_style_context().add_class("kb-cap")
            keycaps.pack_start(cap, False, False, 0)
        if e["state"] == "off":
            keycaps.set_opacity(0.4)
        grid.attach(keycaps, 0, 0, 1, 2)
        title = e["what"] or e["desc"] or mode_key_title(e)
        grid.attach(dp.label(title, "ctl-title"), 1, 0, 1, 1)  # noqa: F405
        sub = dp.label(entry_sub(e), "ctl-sub")  # noqa: F405
        sub.set_hexpand(True)
        sub.set_line_wrap(True)
        sub.set_max_width_chars(60)
        grid.attach(sub, 1, 1, 1, 1)

        buttons = Gtk.Box(spacing=4)
        buttons.set_valign(Gtk.Align.CENTER)
        if e["state"] in ("default", "moved", "off"):
            if not e["mouse"]:
                change = link("Change", lambda: None)  # noqa: F405
                change.connect("clicked", lambda b, e=e: KeyCapture(
                    b, f"New keys for \"{title}\"", lambda keys: self.change(e, keys),
                    lambda keys: [d for d in (o["desc"] or o["keys"] for o in self.occupied_by_others(e, keys))]
                ).open())
                buttons.pack_start(change, False, False, 0)
            if e["state"] == "off":
                buttons.pack_start(link("Turn on", lambda e=e: self.do("on", e["default"], "--default")), False, False, 0)  # noqa: F405
            else:
                buttons.pack_start(link("Off", lambda e=e: self.do("off", e["default"], "--default")), False, False, 0)  # noqa: F405
            if e["state"] == "moved":
                buttons.pack_start(link("Reset", lambda e=e: self.do("reset", e["default"], "--default")), False, False, 0)  # noqa: F405
        elif e["state"] == "custom":
            change = link("Change keys", lambda: None)  # noqa: F405
            change.connect("clicked", lambda b, e=e: KeyCapture(
                b, f"New keys for \"{title}\"", lambda keys: self.change_custom(e, keys),
                lambda keys: [o["desc"] or o["keys"] for o in self.occupied_by_others(e, keys)]).open())
            buttons.pack_start(change, False, False, 0)
            remove = link("Remove", lambda: None)  # noqa: F405
            remove.connect("clicked", lambda b, e=e: self.remove_custom(b, e))
            buttons.pack_start(remove, False, False, 0)
        grid.attach(buttons, 2, 0, 1, 2)
        return grid

    def apply_filter(self):
        query = self.search.get_text().strip()
        visible_groups, n = set(), 0
        for e, widget in self.rows:
            show = shown_by(e, self.filter) and (not query or matches(e, query))
            widget.set_visible(show)
            if show:
                visible_groups.add(e["group"])
                n += 1
        for group, head in self.headings.items():
            head.set_visible(group in visible_groups)
        shared = sum(1 for e in self.entries if e["conflicts"])
        text = f"{n} shown"
        if shared:
            text += f"  ·  {shared} share their keys with another shortcut (marked with !)"
        self.count.set_text(text if self.rows else "")
