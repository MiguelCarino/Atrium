"""Settings page: Windows & workspaces -- your overrides of the desktop
theme's window look and behaviour (scripts/window-look.py).

Every control is one `window-look.py set <key> <value>`: the script writes
hyprlook.<key> into the display state file and re-runs lua/display.lua's
apply, which lays your values over the theme's at every config load -- so a
change here survives a reload, gamemode OFF and a re-login, and stays when
you switch themes. Moving a control back to the theme's own value, or the
row's "Theme's" link, removes the override; "Use the theme's look" removes
all of them. The page then redraws from `window-look.py status`, which also
reads every option back from Hyprland, so what it shows is what is in
effect, not what it asked for.

What is NOT here, on purpose, because another page owns it: focus follows
the mouse (Input), the animations (Effects -- the workspace slide has no
setting of its own, it comes with the animation preset), the border colours
and the accent (Theme). The ELSEWHERE links open those pages.

WORKSPACES is read only, from `window-look.py workspaces --json`: the
workspaces each monitor starts with (lua/rules.lua's workspace rules), the
scratchpads (special workspaces, lua/binds.lua) and whether the overview and
cube plugins are loaded. None of those has a setting to switch: they are
config lines, and the plugins load whenever they are built (the page says how
to turn one off).
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402

PAGE = {"id": "windows", "title": "Windows", "icon": "\uf2d2", "group": "Look", "order": 40, "tab": "Windows & workspaces",
        "keywords": ["window", "ventanas", "gaps", "borders", "border size", "rounded corners", "rounding",
                     "blur", "shadow", "dim inactive", "inactive opacity", "transparency", "tiling", "layout",
                     "dwindle", "master", "scrolling", "new windows", "resize", "snap", "workspaces"]}

LOOK = os.path.join(HYPR, "window-look.py")
SETTINGS = os.path.join(HYPR, "settings.py")

# One window-look.py command at a time. Each one reads the state file,
# changes its line and writes the file back, so two at once (two switches
# flipped quickly, a slider settling while a chip is clicked) would each
# write the file without the other's change, and one would be lost.
CALLS = threading.Lock()
# How long "Use the theme's look" waits for its second click.
CONFIRM_S = 4

# Captions for the choice keys' chips (window-look.py KEYS has the values).
CHOICES = {
    "layout": [("dwindle", "Dwindle"), ("master", "Master and stack"), ("scrolling", "Scrolling columns")],
    "force_split": [("0", "Beside the mouse"), ("1", "Left / above"), ("2", "Right / below")],
    "new_status": [("slave", "Into the stack"), ("master", "As the new master"), ("inherit", "Like the focused one")],
    "orientation": [("left", "Left"), ("right", "Right"), ("top", "Top"), ("bottom", "Bottom"), ("center", "Centre")],
}
LAYOUT_TEXT = {
    "dwindle": "New windows split the focused one  ·  ALT+R flips a split",
    "master": "One big master window, the others stacked beside it",
    "scrolling": "Windows are columns; the workspace scrolls sideways",
}
# Row icons (Font Awesome 6) for the on / off keys.
ICONS = {"blur": "\uf043", "shadow": "\uf5fd", "dim_inactive": "\uf186",
         "resize_on_border": "\uf424", "snap": "\uf076"}


def shown(row):
    """A value as the page writes it: "8 px", "50%", "on"."""
    v = row.get("value", "")
    if row["kind"] == "bool":
        return "on" if v == "yes" else "off"
    if row["kind"] == "frac":
        try:
            return f"{round(float(v) * 100)}%"
        except ValueError:
            return v
    if row["kind"] == "choice":
        return dict(CHOICES.get(row["key"], [])).get(v, v)
    return f"{v} {row.get('unit', '')}".strip()


def theirs(row):
    return shown(dict(row, value=row["theme"]))


def plural(n, word):
    return f"{n} {word}{'s' if n != 1 else ''}"


def workspace_lines(data):
    """`window-look.py workspaces --json` -> [(icon, title, sub)] rows: one
    per monitor, one for the scratchpads, one per plugin."""
    lines = []
    for m in data.get("monitors", []):
        ws = m.get("workspaces") or []
        sub = (f"{plural(len(ws), 'workspace')}: {', '.join(ws)}" if ws else "no workspaces of its own")
        if m.get("default"):
            sub += f"  ·  starts on {m['default']}"
        if m.get("connected") is False:
            sub += "  ·  not connected now"
        lines.append(("\uf108", m["monitor"], sub))
    if data.get("unplaced"):
        lines.append(("\uf108", "Any monitor", "workspaces " + ", ".join(data["unplaced"])))
    pads = data.get("scratchpads") or []
    if pads:
        sub = "  ·  ".join(f"{p['key']} {p['title'].lower() or p['name']}"
                           + (f" ({plural(p['windows'], 'window')})" if p.get("windows") else "")
                           for p in pads)
        lines.append(("\uf2d0", "Scratchpads", sub))
    for p in data.get("plugins") or []:
        if p.get("loaded"):
            state = "on"
        elif not p.get("built"):
            state = f"off: not built (run {p['build']})"
        elif not p.get("required"):
            state = "off: turned off in hyprland.lua"
        elif p.get("loaded") is None:
            state = "Hyprland did not say"
        else:
            state = f"off: not loaded (rebuild: {p['build']})"
        lines.append(("\uf009" if p["id"] == "overview" else "\uf1b2", p["title"], f"{state}  ·  {p['keys']}"))
    return lines


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.error = ""           # what window-look.py said when a command failed
        self.confirm = None       # the GLib source while the reset waits for its second click
        self.rows = {}            # key -> the last status row
        self.sliders, self.switches, self.chips, self.subs, self.resets = {}, {}, {}, {}, {}

        w.pack_start(heading("YOUR WINDOW LOOK"), False, False, 0)
        self.summary_row, self.summary = row("\uf53f", "Window look", "checking…")
        w.pack_start(self.summary_row, False, False, 0)
        self.note = dp.label("", "ctl-sub")
        self.note.set_line_wrap(True)
        w.pack_start(self.note, False, False, 0)
        self.reset_all = link("Use the theme's look", self.on_reset)
        w.pack_start(links_row(link("Apply again", lambda: self.call("apply")), self.reset_all),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("GAPS AND BORDERS"), False, False, 0)
        for key, caption in (("gaps_in", "Gaps between windows"), ("gaps_out", "Gaps at the screen edges"),
                             ("border_size", "Border width"), ("rounding", "Corner rounding"),
                             ("rounding_power", "Corner shape (higher is squarer)")):
            w.pack_start(self.slider(key, caption), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("BLUR AND SHADOWS"), False, False, 0)
        w.pack_start(self.switch("blur", "Blur", "frosted glass behind see-through windows"), False, False, 0)
        w.pack_start(self.slider("blur_size", "Blur strength"), False, False, 0)
        w.pack_start(self.slider("blur_passes", "Blur passes (smoother, more GPU)"),
                     False, False, 0)
        w.pack_start(self.switch("shadow", "Shadows", "a soft shadow around windows"),
                     False, False, 0)
        w.pack_start(self.slider("shadow_range", "Shadow size"), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WINDOWS YOU ARE NOT USING"), False, False, 0)
        w.pack_start(self.switch("dim_inactive", "Dim them", "so the focused window stands out"),
                     False, False, 0)
        w.pack_start(self.slider("dim_strength", "How much to dim"), False, False, 0)
        w.pack_start(self.slider("inactive_opacity", "Opacity"),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("TILING"), False, False, 0)
        w.pack_start(self.choice("layout", "Layout"), False, False, 0)
        self.layout_text = dp.label("", "ctl-sub")
        self.layout_text.set_line_wrap(True)
        w.pack_start(self.layout_text, False, False, 0)
        self.dwindle_box = self.choice("force_split", "Where a new window goes")
        w.pack_start(self.dwindle_box, False, False, 0)
        self.master_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.master_box.pack_start(self.choice("new_status", "Where a new window goes"), False, False, 0)
        self.master_box.pack_start(self.choice("orientation", "Which side the master sits on"), False, False, 0)
        w.pack_start(self.master_box, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("MOVING AND RESIZING"), False, False, 0)
        w.pack_start(self.switch("resize_on_border", "Resize by dragging a border",
                                 "grab a window's edge, no key held"), False, False, 0)
        w.pack_start(self.switch("snap", "Snap floating windows",
                                 "to screen edges and each other"), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WORKSPACES"), False, False, 0)
        self.workspaces = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.workspaces, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("ELSEWHERE"), False, False, 0)
        hint = dp.label("Focus follows mouse: Input  ·  animations: Effects  ·  border colours: Theme", "ctl-sub")
        hint.set_line_wrap(True)
        w.pack_start(hint, False, False, 0)
        w.pack_start(links_row(link("Open Input", lambda: spawn(SETTINGS, "input")),
                               link("Open Effects", lambda: spawn(SETTINGS, "effects")),
                               link("Open Theme", lambda: spawn(SETTINGS, "theme"))), False, False, 0)

    # -- the controls ---------------------------------------------------------------
    def reset_link(self, key):
        """The row's "Theme's" link, shown only while the row is yours."""
        b = link("Theme's", lambda: self.call("unset", key))
        b.set_no_show_all(True)
        self.resets[key] = b
        return b

    def sub_line(self, key, extra=None):
        box = Gtk.Box(spacing=8)
        sub = dp.label("", "ctl-sub")
        sub.set_hexpand(True)
        sub.set_line_wrap(True)
        self.subs[key] = sub
        box.pack_start(sub, True, True, 0)
        box.pack_start(self.reset_link(key), False, False, 0)
        return box

    def slider(self, key, caption):
        lo, hi, unit = self.range_of(key)
        s = Slider(key, caption, lo, hi, 1, unit, self.on_slide)
        self.sliders[key] = s
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.pack_start(s.widget, False, False, 0)
        box.pack_start(self.sub_line(key), False, False, 0)
        return box

    @staticmethod
    def range_of(key):
        # Same ranges as window-look.py KEYS; percentages for the fractions.
        return {"gaps_in": (0, 40, " px"), "gaps_out": (0, 60, " px"), "border_size": (0, 12, " px"),
                "rounding": (0, 30, " px"), "rounding_power": (1, 10, ""), "blur_size": (1, 20, ""),
                "blur_passes": (1, 6, ""), "shadow_range": (1, 50, " px"), "dim_strength": (5, 90, "%"),
                "inactive_opacity": (50, 100, "%")}[key]

    def switch(self, key, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state, k=key: self.on_switch(k, state))
        self.switches[key] = sw
        end = Gtk.Box(spacing=8)
        end.pack_start(self.reset_link(key), False, False, 0)
        end.pack_start(sw, False, False, 0)
        grid, sub_label = row(ICONS.get(key, ""), title, sub, end)
        self.subs[key] = sub_label
        sub_label.base = sub
        return grid

    def choice(self, key, caption):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(dp.label(caption, "ctl-sub"), False, False, 0)
        chips = Chips(lambda value, k=key: self.call("set", k, value))
        chips.set(CHOICES[key], "")
        self.chips[key] = chips
        box.pack_start(chips.widget, False, False, 0)
        box.pack_start(self.sub_line(key), False, False, 0)
        return box

    # -- talking to window-look.py ---------------------------------------------------
    def on_slide(self, key, value):
        kind = self.rows.get(key, {}).get("kind")
        self.call("set", key, f"{value}%" if kind == "frac" else str(value))

    def on_switch(self, key, state):
        if not self.updating:
            self.call("set", key, "yes" if state else "no")
        return True       # the switch moves when the redraw says it is on

    def on_reset(self):
        """"Use the theme's look" throws away every change of yours at once,
        so it takes a second click within a few seconds; with nothing of
        yours to lose it goes straight through."""
        mine = [r for r in self.rows.values() if r.get("override")]
        if not mine or self.confirm is not None:
            self.cancel_confirm()
            self.call("reset")
            return
        n = len(mine)
        self.reset_all.set_label(f"Undo {n} change{'s' if n != 1 else ''}? Click again")
        self.confirm = GLib.timeout_add_seconds(CONFIRM_S, self.cancel_confirm)

    def cancel_confirm(self):
        if self.confirm is not None:
            GLib.source_remove(self.confirm)
            self.confirm = None
        self.reset_all.set_label("Use the theme's look")
        return False

    def call(self, *args):
        """One window-look.py command in a thread (it re-runs the Lua through
        hyprctl, ~100 ms), then a redraw from what it reports. A command that
        fails says why on stderr (a value it refused, or Hyprland's own
        complaint); that goes into the note instead of being lost."""
        self.note.set_text("applying…")
        self.note.set_visible(True)

        def work():
            with CALLS:
                try:
                    out = subprocess.run([LOOK, *args], capture_output=True, text=True, timeout=10)
                except (OSError, subprocess.SubprocessError) as exc:
                    return f"window-look.py did not run: {exc}"
                if out.returncode != 0:
                    return (out.stderr.strip().splitlines() or ["window-look.py failed"])[-1]
                return ""

        def done(error):
            self.error = error
            self.refresh()
        background(work, done)

    def refresh(self):
        background(lambda: run_json(LOOK, "status", timeout=10), self.show)
        background(lambda: run_json(LOOK, "workspaces", "--json", timeout=10), self.show_workspaces)

    def show_workspaces(self, data):
        """Read only: what each monitor starts with, the scratchpads, the
        two plugins. Nothing here is a switch (see the module docstring)."""
        box = self.workspaces
        clear(box)
        if not data:
            box.pack_start(dp.label("Workspaces did not answer", "ctl-sub"), False, False, 0)
            box.show_all()
            return
        for line in workspace_lines(data):
            grid, _ = row(*line)
            box.pack_start(grid, False, False, 0)
        note = dp.label("Which workspaces live on which monitor is set in lua/rules.lua (hl.workspace_rule); "
                        "1, 2, 3 and 5 follow the primary screen, which you choose on Screens. "
                        "The scratchpad keys are in lua/binds.lua. The plugins have no switch: they load "
                        "whenever they are built, and are turned off by commenting out their require line in "
                        "hyprland.lua (or deleting the .so in ~/.local/lib/hyprland). A Hyprland update needs "
                        "them rebuilt. Scratchpads are overlays on any monitor; the key shows and hides one. "
                        "The workspace slide comes with the animation preset in Effects (Calm cross-fades).",
                        "ctl-sub")
        note.set_line_wrap(True)
        box.pack_start(details(note), False, False, 0)
        box.show_all()

    def show(self, data):
        if not data:
            self.summary.set_text("Window settings did not answer (is Hyprland running?)")
            self.note.set_text("")
            return
        self.rows = {r["key"]: r for r in data["keys"]}
        mine = [r for r in data["keys"] if r["override"]]
        self.summary.set_text(f"Theme: {data['theme_label']}  ·  "
                              + (f"{len(mine)} change{'s' if len(mine) != 1 else ''} of yours on top: "
                                 + ", ".join(r["label"].lower() for r in mine[:4])
                                 + ("…" if len(mine) > 4 else "")
                                 if mine else "no changes of yours"))
        notes = []
        if data.get("gamemode"):
            notes.insert(0, "Gamemode is on: effects are off until it ends (ALT+SHIFT+G).")
        off = [r for r in data["keys"] if r["live"] and r["live"] != r["value"] and not r["held_by_gamemode"]]
        if off:
            notes.append("Not in effect yet: " + ", ".join(r["label"].lower() for r in off)
                         + "  ·  Apply again puts yours back.")
        if self.error:
            notes.insert(0, f"That did not work: {self.error}")
            self.error = ""       # said once; the next redraw is clean
        self.note.set_text("  ".join(notes))
        self.note.set_visible(bool(notes))
        self.updating = True
        for key, r in self.rows.items():
            self.show_row(key, r)
        layout = self.rows.get("layout", {}).get("value", "dwindle")
        self.layout_text.set_text(LAYOUT_TEXT.get(layout, ""))
        self.dwindle_box.set_visible(layout == "dwindle")
        self.master_box.set_visible(layout == "master")
        self.updating = False

    def show_row(self, key, r):
        if key in self.sliders:
            try:
                v = float(r["value"])
            except ValueError:
                v = 0
            self.sliders[key].show(round(v * 100) if r["kind"] == "frac" else v)
        if key in self.switches:
            # set_active too: a click moves the knob (active) before the
            # command has run, and set_state alone does not move it back
            # when the command failed and the state never changed.
            on = r["value"] == "yes"
            self.switches[key].set_active(on)
            self.switches[key].set_state(on)
        if key in self.chips:
            self.chips[key].set(CHOICES[key], r["value"])
        sub = self.subs.get(key)
        if sub is not None:
            origin = "the theme's" if r.get("from") == "theme" else "the default"
            text = (f"yours  ·  {origin}: {theirs(r)}" if r["override"]
                    else "from the theme" if r.get("from") == "theme" else "the default")
            if r["held_by_gamemode"]:
                text += "  ·  off while gamemode is on"
            base = getattr(sub, "base", "")
            sub.set_text(f"{base}  ·  {text}" if base else text)
        self.resets[key].set_visible(bool(r["override"]))
