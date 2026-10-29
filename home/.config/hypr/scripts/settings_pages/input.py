"""Settings page: keyboard layouts and typing, mouse, touchpad, focus.

Everything here goes through ~/.config/hypr/scripts/input-settings.py, which
saves the choice in ~/.local/state/hypr/input.conf and has Hyprland re-run
lua/input.lua -- the same Lua that applies the file at every config load, so
a choice made here survives a reload, gamemode OFF and a re-login. The page
redraws from `input-settings.py status` after every change: what you see is
what the script says is saved, and a line warns if Hyprland reports something
else.

The layout search reads the system's xkb list in-process (input-settings.py's
own parser, imported), since it runs on every keystroke and only reads.

Keyboard layouts (xkb: which letters the keys type) and input methods
(fcitx5: Japanese through Mozc) are separate switches that stack; the input
methods are only reported here, with links to fcitx5's own settings and the
bar's language menu.

Also here: when the pointer hides (still for N seconds; while typing), how
far a push on a screen edge jumps across a gap to the next screen
(lua/edgejump.lua), and the main modifier of the everyday keys (ALT or
SUPER: lua/shared.lua mainMod; changing it reloads Hyprland, and the page
lists the combinations SUPER would claim twice).
"""
import importlib.util
import os
import subprocess

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "input", "title": "Keyboard & mouse", "icon": "", "group": "Hardware", "order": 30, "tab": "Keyboard & mouse",
        "keywords": ["keyboard", "teclado", "keyboard layout", "language", "xkb", "key repeat", "caps lock",
                     "compose key", "numlock", "mouse", "raton", "pointer speed", "acceleration",
                     "sensitivity", "scrolling", "natural scrolling", "left handed", "touchpad",
                     "tap to click", "focus follows mouse", "input method", "fcitx", "japanese", "mozc",
                     "hide cursor", "hide pointer", "inactive cursor", "edge jump", "screen edge",
                     "main modifier", "mod key", "alt key", "super key", "mainmod"]}

INPUT = os.path.join(HYPR, "input-settings.py")

# The layout-switch keys most people pick, as chips; every other xkb switch
# is in the "Other key" list under them.
SWITCH_CHIPS = [("grp:win_space_toggle", "Super+Space"), ("grp:ctrl_shift_toggle", "Ctrl+Shift"),
                ("grp:shift_caps_toggle", "Shift+Caps Lock"), ("grp:shifts_toggle", "Both Shifts"),
                ("grp:caps_toggle", "Caps Lock"), ("grp:menu_toggle", "Menu key"), ("", "No key")]
CAPS_CHIPS = [("", "Caps Lock"), ("caps:escape", "Escape"), ("ctrl:nocaps", "Ctrl"),
              ("caps:backspace", "Backspace"), ("caps:swapescape", "Swap with Escape"), ("caps:none", "Nothing")]
# Right Alt is left out on purpose: on the Latin American and Spanish layouts
# it is AltGr, the key that types @ [ ] { } -- making it Compose loses those.
COMPOSE_CHIPS = [("", "None"), ("compose:menu", "Menu key"), ("compose:rctrl", "Right Ctrl"),
                 ("compose:rwin", "Right Super"), ("compose:sclk", "Scroll Lock"), ("compose:prsc", "PrtSc")]
ACCEL_CHIPS = [("adaptive", "Adaptive"), ("flat", "Flat")]
FOCUS_CHIPS = [("1", "Follows the mouse"), ("2", "Click; scroll follows the mouse"), ("0", "Click to focus")]
MOD_CHIPS = [("ALT", "Alt (default)"), ("SUPER", "Super")]
MOD_SUB = {"ALT": "Alt+Q terminal, Alt+1..9 workspaces, Alt+arrows focus... The Super keys "
                  "(session, screens, tools) stay on Super.",
           "SUPER": "Super+Q terminal, Super+1..9 workspaces... The keys that were already Super "
                    "keep Super too, so some combinations now do two things (below)."}
FOCUS_SUB = {"1": "The window under the pointer gets the keyboard.",
             "2": "A click focuses; the wheel scrolls whatever is under the pointer.",
             "0": "Only a click (or a key) focuses a window."}


def backend():
    """input-settings.py as a module, for its pure helpers (xkb list, search)."""
    spec = importlib.util.spec_from_file_location("input_settings", INPUT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(*args):
    """Run input-settings.py; "" when it worked, else what it said."""
    try:
        out = subprocess.run([INPUT, *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return "" if out.returncode == 0 else (out.stderr or out.stdout).strip().removeprefix("input-settings: ")


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)
    lab.set_line_wrap(True)
    lab.set_max_width_chars(90)
    return lab


class Page:
    def __init__(self):
        self.be = backend()
        self.updating = False
        self.status = {}
        self.switches = {}
        self.sliders = {}
        self.search_pending = None
        self.widget = page_box()
        w = self.widget
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

        # -- keyboard layouts ---------------------------------------------------
        w.pack_start(heading("KEYBOARD LAYOUTS"), False, False, 0)
        w.pack_start(wrapped("In switching order; the first is used at login (up to four)."), False, False, 0)
        self.layouts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.layouts, False, False, 0)
        add = Gtk.Box(spacing=8)
        self.search = Gtk.Entry()
        self.search.set_placeholder_text("Add a layout: language, country or code (german, colemak, de)")
        self.search.set_hexpand(True)
        self.search.connect("changed", lambda _e: self.search_soon())
        add.pack_start(self.search, True, True, 0)
        w.pack_start(add, False, False, 0)
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.results, False, False, 0)

        w.pack_start(dp.label("Switch layout with", "ctl-title"), False, False, 0)
        self.switch_chips = Chips(lambda key: self.set("switch", key))
        self.switch_chips.widget.set_max_children_per_line(7)
        w.pack_start(self.switch_chips.widget, False, False, 0)
        other = Gtk.Box(spacing=8)
        other.pack_start(dp.label("Other key", "ctl-sub"), False, False, 0)
        self.switch_combo = Gtk.ComboBoxText()
        for opt, name in self.be.options("switch"):
            self.switch_combo.append(opt, self.be.say_keys(name))
        self.switch_combo.connect("changed", self.on_switch_combo)
        other.pack_start(self.switch_combo, False, False, 0)
        w.pack_start(other, False, False, 0)
        self.switch_sub = wrapped("")
        w.pack_start(self.switch_sub, False, False, 0)
        w.pack_start(links_row(link("Switch layout now", lambda: self.do("layout", "next")),
                               link("Language menu", lambda: spawn(PANEL, "toggle", "language"))), False, False, 0)
        self.im_row, self.im_sub = row("", "Input methods (fcitx5)", "",
                                       link("Input method settings", lambda: spawn("fcitx5-configtool")))
        w.pack_start(self.im_row, False, False, 0)

        # -- typing -------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("TYPING"), False, False, 0)
        # Slider ends = the ranges input-settings.py accepts (and lua/input.lua
        # clamps to), so a value set from a terminal shows as itself, not as
        # the nearest end of a shorter slider.
        self.slider("repeat_delay", "Delay before a held key repeats", 100, 2000, 25, " ms")
        self.slider("repeat_rate", "Repeat speed", 1, 100, 1, " /s")
        self.try_entry = Gtk.Entry()
        self.try_entry.set_placeholder_text("Hold a key here to try the repeat")
        w.pack_start(self.try_entry, False, False, 0)
        self.switch_row("numlock", "", "Num Lock on at start",
                        "on at login and for each keyboard that connects")
        w.pack_start(dp.label("Caps Lock key", "ctl-title"), False, False, 0)
        self.caps_chips = Chips(lambda key: self.set("caps", key))
        self.caps_chips.widget.set_max_children_per_line(6)
        w.pack_start(self.caps_chips.widget, False, False, 0)
        w.pack_start(dp.label("Compose key", "ctl-title"), False, False, 0)
        self.compose_chips = Chips(lambda key: self.set("compose", key))
        self.compose_chips.widget.set_max_children_per_line(6)
        w.pack_start(self.compose_chips.widget, False, False, 0)
        w.pack_start(wrapped("Compose ' e types é, Compose o c types ©."), False, False, 0)

        # -- mouse ----------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("MOUSE"), False, False, 0)
        self.slider("sensitivity", "Pointer speed (0 is the mouse's own)", -100, 100, 5, "", scale=100)
        w.pack_start(dp.label("Acceleration", "ctl-title"), False, False, 0)
        self.accel_chips = Chips(lambda key: self.set("accel", key))
        w.pack_start(self.accel_chips.widget, False, False, 0)
        self.accel_sub = wrapped("")
        w.pack_start(self.accel_sub, False, False, 0)
        self.slider("scroll_factor", "Scroll speed", 10, 500, 10, " %", scale=100)
        self.switch_row("natural_scroll", "", "Natural scrolling",
                        "rolling down moves the page up, as on a phone")
        self.switch_row("left_handed", "", "Left-handed",
                        "swaps the left and right buttons")
        self.switch_row("middle_click_paste", "", "Middle-click paste",
                        "the middle button pastes the last selected text")
        self.switch_row("hide_on_typing", "", "Hide the pointer while typing",
                        "back as soon as the mouse moves")
        self.slider("hide_after", "Hide a still pointer after (0 = never)", 0, 60, 1, " s")
        self.slider("edge_reach", "Jump across gaps between screens up to (0 = never)", 0, 2000, 50, " px")
        w.pack_start(wrapped("Pushing the pointer against a screen edge with no screen right behind it "
                             "jumps it to the nearest screen across the gap, if that one is this close."),
                     False, False, 0)

        # -- touchpad (only when there is one) --------------------------------------
        self.touch = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.touch.set_no_show_all(True)
        w.pack_start(self.touch, False, False, 0)
        self.touch.pack_start(sep(), False, False, 0)
        self.touch.pack_start(heading("TOUCHPAD"), False, False, 0)
        self.switch_row("touchpad.tap_to_click", "", "Tap to click",
                        "one finger left-clicks, two right-click, three middle-click", self.touch)
        self.switch_row("touchpad.natural_scroll", "", "Natural scrolling",
                        "two fingers move the content, as on a phone", self.touch)
        self.switch_row("touchpad.disable_while_typing", "", "Off while typing",
                        "so a palm does not move the cursor", self.touch)
        self.switch_row("touchpad.clickfinger", "", "Click with fingers, not zones",
                        "two-finger press right-clicks, three middle-click", self.touch)
        self.slider("touchpad.scroll_factor", "Two-finger scroll speed", 10, 500, 10, " %", scale=100,
                    box=self.touch)
        self.no_touch = wrapped("No touchpad found.")
        w.pack_start(self.no_touch, False, False, 0)

        # -- focus ----------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("FOCUS"), False, False, 0)
        w.pack_start(dp.label("Which window gets the keyboard", "ctl-title"), False, False, 0)
        self.focus_chips = Chips(lambda key: self.set("follow_mouse", key))
        w.pack_start(self.focus_chips.widget, False, False, 0)
        self.focus_sub = wrapped("")
        w.pack_start(self.focus_sub, False, False, 0)

        # -- main modifier ----------------------------------------------------------
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("MAIN MODIFIER"), False, False, 0)
        w.pack_start(dp.label("The everyday keys use", "ctl-title"), False, False, 0)
        self.mod_chips = Chips(lambda key: self.set("main_mod", key))
        w.pack_start(self.mod_chips.widget, False, False, 0)
        self.mod_sub = wrapped("")
        w.pack_start(self.mod_sub, False, False, 0)
        self.mod_clash = wrapped("")
        w.pack_start(self.mod_clash, False, False, 0)

        # -- reset ----------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)
        # Reset asks once: it throws away every choice on this page at once
        # (layouts included), and there is no undo.
        self.reset_link = link("Reset all", self.ask_reset)
        self.reset_row, self.reset_sub = row("", "Back to the defaults", "", self.reset_link)
        w.pack_start(self.reset_row, False, False, 0)
        self.confirm = Gtk.Box(spacing=8)
        self.confirm.set_halign(Gtk.Align.END)
        self.confirm_label = dp.label("", "ctl-sub")
        self.confirm.pack_start(self.confirm_label, False, False, 0)
        self.confirm.pack_start(link("Yes, reset", self.do_reset), False, False, 0)
        self.confirm.pack_start(link("Cancel", self.hide_confirm), False, False, 0)
        self.confirm.set_no_show_all(True)
        w.pack_start(self.confirm, False, False, 0)
        self.state_file = wrapped("")
        w.pack_start(details(self.state_file), False, False, 0)

    # -- building blocks ------------------------------------------------------------
    def slider(self, key, caption, lo, hi, step, unit, scale=1, box=None):
        s = Slider(key, caption, lo, hi, step, unit,
                   lambda k, v: self.set(k, f"{v / scale:g}" if scale != 1 else str(v)))
        s.scale_by = scale
        self.sliders[key] = s
        (box or self.widget).pack_start(s.widget, False, False, 0)

    def switch_row(self, key, icon, title, sub, box=None):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state, k=key: self.on_switch(k, state))
        grid, _ = row(icon, title, sub, sw)
        self.switches[key] = sw
        (box or self.widget).pack_start(grid, False, False, 0)

    # -- doing --------------------------------------------------------------------------
    def do(self, *args):
        """input-settings.py <args> off the GTK thread, then redraw."""
        background(lambda: call(*args), self.after)

    def set(self, key, value):
        if not self.updating:
            self.do("set", key, value)

    def after(self, error):
        self.show_problem(error)
        self.refresh(keep_problem=bool(error))

    def on_switch(self, key, state):
        if not self.updating:
            self.set(key, "on" if state else "off")
        return True       # the switch moves when status says it did

    def on_switch_combo(self, combo):
        opt = combo.get_active_id()
        if not self.updating and opt:
            self.set("switch", opt)

    def ask_reset(self):
        changed = [k for k, v in self.status.get("settings", {}).items() if v["changed"]]
        if not changed:
            return
        self.confirm_label.set_text(f"Put {len(changed)} setting{'s' if len(changed) != 1 else ''} "
                                    "(layouts, keys, mouse, focus) back to the defaults?")
        self.confirm.set_no_show_all(False)
        self.confirm.show_all()

    def hide_confirm(self):
        self.confirm.hide()
        self.confirm.set_no_show_all(True)

    def do_reset(self):
        self.hide_confirm()
        self.do("reset")

    def show_problem(self, text):
        self.problem.set_text(text or "")
        (self.problem.show if text else self.problem.hide)()

    # -- layout search ------------------------------------------------------------------
    def search_soon(self):
        if self.search_pending:
            GLib.source_remove(self.search_pending)
        self.search_pending = GLib.timeout_add(150, self.show_results)

    def show_results(self):
        self.search_pending = None
        clear(self.results)
        words = self.search.get_text().split()
        if words:
            have = {lay["token"] for lay in self.status.get("layouts", [])}
            full = len(have) >= self.status.get("max_layouts", 4)
            hits = [h for h in self.be.search_layouts(words, limit=12) if h[0] not in have][:8]
            if not hits:
                self.results.pack_start(dp.label("No xkb layout matches that.", "ctl-sub"), False, False, 0)
            for tok, name in hits:
                button = link("Add", lambda t=tok: (self.search.set_text(""), self.do("layout", "add", t)))
                button.set_sensitive(not full)
                grid, _ = row("\uf067", name, tok + ("  ·  four layouts already: remove one first" if full else ""),
                              button)
                self.results.pack_start(grid, False, False, 0)
        self.results.show_all()
        return False

    # -- redraw ---------------------------------------------------------------------------
    def refresh(self, keep_problem=False):
        if not keep_problem:
            self.show_problem("")
        if not self.layouts.get_children():
            self.layouts.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
            self.layouts.show_all()
        background(lambda: run_json(INPUT, "status"), self.show)

    def show(self, st):
        if not st:
            self.show_problem("Could not read the settings: they may be out of date.")
            return
        self.status = st
        val = {k: v["value"] for k, v in st["settings"].items()}
        self.updating = True
        # layouts
        clear(self.layouts)
        n = len(st["layouts"])
        for i, lay in enumerate(st["layouts"]):
            buttons = []
            if not lay["active"]:
                buttons.append(link("Use now", lambda i=i: background(
                    lambda: run("hyprctl", "switchxkblayout", "all", str(i)), lambda _r: self.refresh())))
            if i > 0:
                buttons.append(link("Up", lambda t=lay["token"]: self.do("layout", "up", t)))
            if i < n - 1:
                buttons.append(link("Down", lambda t=lay["token"]: self.do("layout", "down", t)))
            if n > 1:
                buttons.append(link("Remove", lambda t=lay["token"]: self.do("layout", "remove", t)))
            sub = lay["token"] + ("  ·  typing in it now" if lay["active"] else "") + (
                "  ·  at login" if i == 0 else "")
            grid, _ = row("", lay["name"], sub, links_row(*buttons))
            self.layouts.pack_start(grid, False, False, 0)
        # switch key
        switch = val["switch"]
        chips = list(SWITCH_CHIPS)
        if switch not in dict(chips):
            chips.insert(-1, (switch, st.get("switch_label") or switch))
        self.switch_chips.set(chips, switch)
        self.switch_combo.set_active_id(switch or None)
        if not switch:
            self.switch_combo.set_active(-1)
        warn = st.get("switch_warning", "")
        self.switch_sub.set_text((
            (f"{st['switch_label']} switches to the next layout, in every app. " if st.get("switch_label") else "")
            + warn).strip())
        ims = st.get("input_methods") or []
        self.im_sub.set_text(("  ·  ".join(m["label"] + (" (on)" if m["active"] else "") for m in ims)
                              + "  ·  Super+Space reaches it after the last layout") if ims else "none set up")
        # typing
        for key, s in self.sliders.items():
            try:
                s.show(float(val[key]) * s.scale_by)
            except ValueError:
                pass
        for key, sw in self.switches.items():
            sw.set_active(val[key] == "on")
            sw.set_state(val[key] == "on")
        caps = list(CAPS_CHIPS)
        if val["caps"] not in dict(caps):
            caps.append((val["caps"], val["caps"]))
        self.caps_chips.set(caps, val["caps"])
        compose = list(COMPOSE_CHIPS)
        if val["compose"] not in dict(compose):
            compose.append((val["compose"], val["compose"]))
        self.compose_chips.set(compose, val["compose"])
        # mouse
        self.accel_chips.set(ACCEL_CHIPS, val["accel"])
        self.accel_sub.set_text("Faster movements carry the pointer further."
                                if val["accel"] == "adaptive" else
                                "The same distance at any speed (what many games want).")
        # touchpad
        if st.get("touchpad"):
            self.touch.set_no_show_all(False)
            self.touch.show_all()
            self.no_touch.hide()
        else:
            self.touch.hide()
            self.no_touch.show()
        # focus
        self.focus_chips.set(FOCUS_CHIPS, val["follow_mouse"])
        self.focus_sub.set_text(FOCUS_SUB.get(val["follow_mouse"], ""))
        # main modifier
        mod = val.get("main_mod", "ALT")
        self.mod_chips.set(MOD_CHIPS, mod)
        self.mod_sub.set_text(MOD_SUB.get(mod, "") + " Changing it reloads the desktop's config; "
                              "shortcuts you moved in Keyboard shortcuts keep the keys they were given.")
        clashes = st.get("main_mod_clashes") or []
        if clashes:
            shown = ", ".join(clashes[:12]) + (f" and {len(clashes) - 12} more" if len(clashes) > 12 else "")
            self.mod_clash.set_text(("Bound twice now: " if mod == "SUPER" else "With Super these would be bound twice: ")
                                    + shown + ".")
        else:
            self.mod_clash.set_text("")
        # reset
        changed = [k for k, v in st["settings"].items() if v["changed"]]
        self.reset_link.set_sensitive(bool(changed))
        self.reset_sub.set_text(f"{len(changed)} setting{'s' if len(changed) != 1 else ''} changed"
                                if changed else "everything is at its default")
        self.state_file.set_text(f"Saved in {st['state_file'].replace(os.path.expanduser('~'), '~')}")
        if not st.get("in_sync"):
            self.show_problem(f"Hyprland is using {st['live'].get('kb_layout')!r}, not the saved layouts: "
                              "any change here reapplies them.")
        self.layouts.show_all()
        self.updating = False
