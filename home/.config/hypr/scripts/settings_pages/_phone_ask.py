"""Settings > Devices, the "ASK FROM THE PHONE" section: phone-ask.py's
options (asking the desktop assistant from the paired phone over KDE
Connect). Not a page of its own (no PAGE): devices.py packs `Section().widget`
under its phone handoff and calls refresh() with the page.

Everything is phone-ask.py's (`phone-ask.py set KEY VALUE`, `on|off`,
`screen on|off`, read back with `phone-ask.py status --json`); the on/off
switch and the screen permission live in privacy.conf (phone_ask,
phone_ask_screen), both OFF as shipped. The section keeps nothing itself.
"""
import os
import subprocess

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import GLib, Gtk  # noqa: F401,E402

PHONE_ASK = os.path.join(HYPR, "phone-ask.py")  # noqa: F405
REPLY = [("ping", "A notification"), ("text", "Text on its clipboard"), ("both", "Both")]


# -- pure helpers (tests/test_phone_ask.py) ----------------------------------------------
def how_text(data):
    """The lines under the switch: what the phone can do now, and how."""
    if not data:
        return "phone-ask.py status did not answer."
    conf = data["settings"]
    devs = data.get("devices") or []
    if not devs:
        return "No phone paired (see Phone above)."
    if not data["on"]:
        return "Off: the phone cannot ask anything."
    lines = []
    for d in devs:
        if not d["chosen"]:
            continue
        got = ", ".join(data["presets"].get(n, n) for n in d["installed"]) or "none"
        lines.append(f"{d['name']} ({'here' if d['reachable'] else 'away'}): {got}")
    lines.append("On the phone: KDE Connect > Run command.")
    if conf["text_questions"] == "on":
        lines.append(f"Or share text starting with “{conf['prefix']}”."
                     + ("" if data["listener"] else "  The listener (phone-ask.service) is not running."))
    return "\n".join(lines)


def action_caption(name, risky):
    return f"{name} (risky)" if name in (risky or {}) else name


def toggled(current, key, on):
    """The comma list with `key` added or taken out, order kept."""
    items = [v for v in (current or "").split(",") if v]
    if on and key not in items:
        items.append(key)
    if not on:
        items = [v for v in items if v != key]
    return ",".join(items) or "none"


def call(*cmd):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, (done.stderr or done.stdout).strip()


def wrapped(text):
    lab = dp.label(text, "ctl-sub")  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    return lab


class Toggles:
    """A wrapping row of chips, any number lit (dev-pick + .active)."""

    def __init__(self, on_toggle):
        self.on_toggle = on_toggle
        self.widget = Gtk.FlowBox()
        self.widget.set_selection_mode(Gtk.SelectionMode.NONE)
        self.widget.set_max_children_per_line(5)
        self.widget.set_column_spacing(4)
        self.widget.set_row_spacing(4)
        self.buttons = {}
        self.active = set()

    def set(self, items, active, tips=None):
        if list(self.buttons) != [k for k, _ in items]:
            for child in self.widget.get_children():
                self.widget.remove(child)
            self.buttons = {}
            for key, caption in items:
                b = Gtk.Button(label=caption)
                for cls in ("dev-pick", "chip"):
                    b.get_style_context().add_class(cls)
                b.set_can_focus(False)
                if tips and key in tips:
                    b.set_tooltip_text(tips[key])
                b.connect("clicked", lambda _b, k=key: self.on_toggle(k, k not in self.active))
                self.buttons[key] = b
                self.widget.add(b)
            self.widget.show_all()
        self.active = set(active)
        for key, b in self.buttons.items():
            ctx = b.get_style_context()
            (ctx.add_class if key in self.active else ctx.remove_class)("active")


class Section:
    def __init__(self):
        self.updating = False
        self.data = None
        self.switches = {}
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        w = self.widget
        w.pack_start(heading("ASK FROM THE PHONE"), False, False, 0)  # noqa: F405
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)
        w.pack_start(self.switch_row("on", "\uf10b", "Answer questions from the phone",
                                     "the local assistant answers, back on the phone"), False, False, 0)
        self.how = wrapped("")
        w.pack_start(self.how, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        w.pack_start(self.body, False, False, 0)
        b = self.body

        b.pack_start(dp.label("Quick questions on the phone", "ctl-sub"), False, False, 0)  # noqa: F405
        self.presets = Toggles(lambda k, on: self.change("set", "presets", toggled(self.conf("presets"), k, on)))
        b.pack_start(self.presets.widget, False, False, 0)
        b.pack_start(self.switch_row("text_questions", "\uf27a", "Any question as shared text",
                                     "shared text starting with the prefix below"), False, False, 0)
        self.prefix = Chips(lambda k: self.change("set", "prefix", k))  # noqa: F405
        b.pack_start(self.prefix.widget, False, False, 0)

        b.pack_start(dp.label("The answer comes back as", "ctl-sub"), False, False, 0)  # noqa: F405
        self.reply = Chips(lambda k: self.change("set", "reply", k))  # noqa: F405
        self.reply.widget.set_max_children_per_line(3)
        b.pack_start(self.reply.widget, False, False, 0)

        b.pack_start(self.switch_row("screen", "\uf108", "May describe the screen",
                                     "in words, by the local model  ·  never private windows"),
                     False, False, 0)
        self.shots_row = self.switch_row("screenshots", "\uf030", "Also send a screenshot",
                                         "the picture goes with the answer")
        b.pack_start(self.shots_row, False, False, 0)

        b.pack_start(dp.label("Actions the phone may run", "ctl-sub"), False, False, 0)  # noqa: F405
        self.allow = Toggles(lambda k, on: self.change("set", "allow", toggled(self.conf("allow"), k, on)))
        b.pack_start(self.allow.widget, False, False, 0)

        b.pack_start(dp.label("Questions per 10 minutes", "ctl-sub"), False, False, 0)  # noqa: F405
        self.limit = Chips(lambda k: self.change("set", "limit", str(k)))  # noqa: F405
        self.limit.widget.set_max_children_per_line(4)
        b.pack_start(self.limit.widget, False, False, 0)
        b.pack_start(dp.label("Which phone may ask", "ctl-sub"), False, False, 0)  # noqa: F405
        self.device = Chips(lambda k: self.change("set", "device", k))  # noqa: F405
        b.pack_start(self.device.widget, False, False, 0)
        b.pack_start(details(  # noqa: F405
            wrapped("An answer runs only if all its actions are lit; \"risky\" ones open or close windows, "
                    "links or apps. Each question is logged in the journal, never its words."),
            links_row(link("Put the quick questions on the phone again",  # noqa: F405
                           lambda: self.change("install")))), False, False, 0)

    def switch_row(self, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, on, k=key: self.flip(k, on))
        self.switches[key] = sw
        grid, _sub = row(icon, title, sub, sw)  # noqa: F405
        return grid

    def conf(self, key):
        return ((self.data or {}).get("settings") or {}).get(key, "")

    # -- changing things ---------------------------------------------------------------------
    def flip(self, key, on):
        word = "on" if on else "off"
        if key == "on":
            return self.change(word)
        if key == "screen":
            return self.change("screen", word)
        return self.change("set", key, word)

    def change(self, *args):
        if self.updating:
            return True
        background(lambda: call(PHONE_ASK, *args), self.changed)  # noqa: F405
        return True

    def changed(self, result):
        ok, why = result
        self.problem.set_text("" if ok else f"Not changed: {why}")
        self.problem.set_visible(not ok)
        self.refresh()

    # -- drawing -----------------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(PHONE_ASK, "status", "--json", timeout=30), self.show)  # noqa: F405

    def show(self, data):
        self.data = data
        self.how.set_text(how_text(data))
        if not data:
            self.body.set_sensitive(False)
            return
        conf = data["settings"]
        self.updating = True
        try:
            for key, on in (("on", data["on"]), ("screen", data["screen"]),
                            ("text_questions", conf["text_questions"] == "on"),
                            ("screenshots", conf["screenshots"] == "on")):
                self.switches[key].set_active(on)
                self.switches[key].set_state(on)
            self.presets.set(list(data["presets"].items()), [v for v in conf["presets"].split(",") if v])
            self.prefix.set([(p, f"starts with  {p}") for p in data["prefixes"]], conf["prefix"])
            self.reply.set(REPLY, conf["reply"])
            self.allow.set([(n, action_caption(n, data["risky"])) for n in data["actions"]],
                           [v for v in conf["allow"].split(",") if v], data["risky"])
            self.limit.set([(n, str(n)) for n in data["limits"]], conf["limit"])
            self.device.set([("any", "Any paired phone")] + [(d["id"], d["name"]) for d in data["devices"]],
                            conf["device"])
        finally:
            self.updating = False
        self.body.set_sensitive(bool(data["on"]))
        self.shots_row.set_sensitive(bool(data["screen"]))
        self.widget.show_all()
