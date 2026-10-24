"""Settings page: Smart desktop -- every smart feature of this desktop on one
page, each a card with what it does, its real on/off switch, how it is
doing, its keys and a link to its own page.

    PRIVACY AT A GLANCE   camera, microphone and sound, screen, clipboard:
                          which features may use each one now (and what the
                          bar's indicators say is using the camera / mic this
                          moment), each with a one-click "turn that off", and
                          "Turn all off" per sense; links to Privacy and to
                          Folder access (which folders AI may read files in)
    ASSISTANT & VOICE     assistant, voice typing & captions, voice commands,
                          spoken replies
    AWARENESS             desktop memory, ask about the screen, presence,
                          gestures & gaze, live suggestions, smart clipboard
    WORK                  project contexts, focus guard, background tasks,
                          brief & journal, workspace sessions, automations,
                          notification digest
    DESKTOP               ambient desktop, desktop health, smart window
                          layout, picture-in-picture
    DEVICES & MODELS      phone handoff, ask from the phone, machines,
                          AI & models

The list, the reading and the switching are settings_pages/_smart.py's (no
GTK, tested): each card reads the same CLI its own page reads and its switch
runs the same command that page's switch runs, so they always agree. This
page only draws: the reading runs in a thread (_smart.gather, a few at a
time; KDE Connect's answers take ~2 s), never on the GTK thread; a switch
moves only when the feature's own answer says it did. An on-demand tool
(nothing runs until you press its key) has no switch, only its status.
"""
import os

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from . import _smart as smart

PAGE = {"id": "intelligence", "title": "Smart desktop", "icon": "", "group": "Smart", "order": 10, "tab": "Overview",
        "keywords": ["smart features", "funciones inteligentes", "inteligencia", "ai features", "ia",
                     "control panel", "panel de control", "hub", "overview", "resumen", "all features",
                     "assistant", "asistente", "voice typing", "dictation", "dictado", "captions", "subtitulos",
                     "voice commands", "comandos de voz", "spoken replies", "read aloud", "leer en voz alta",
                     "tts", "desktop memory", "memoria", "ask your desktop", "screen ask", "ask about the screen",
                     "preguntar pantalla", "presence", "presencia", "webcam", "camera", "camara", "gestures",
                     "gestos", "gaze", "mirada", "suggestions", "sugerencias", "smart clipboard",
                     "portapapeles", "smart layout", "window layout", "diseno de ventanas", "project contexts",
                     "proyectos", "contextos", "focus guard", "enfoque", "concentracion", "background tasks",
                     "tareas", "brief", "resumen diario", "journal", "diario", "workspace sessions", "sesiones",
                     "automations", "automatizaciones", "notification digest", "resumen de notificaciones",
                     "picture in picture", "pip", "ambient", "ambiente", "desktop health", "salud", "self healing",
                     "phone handoff", "telefono", "movil", "ask from the phone", "machines", "maquinas",
                     "kvm", "models", "modelos", "llm", "privacy at a glance", "privacidad", "microphone",
                     "microfono", "screen", "pantalla", "clipboard"]}

SETTINGS = os.path.join(HYPR, "settings.py")
WIDTH_CHARS = 40            # a card's text wraps here, so two cards sit side by side


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)
    lab.set_line_wrap(True)
    lab.set_max_width_chars(WIDTH_CHARS)
    lab.set_xalign(0)
    return lab


class Card:
    """One feature: title and switch, the plain-words line, the status, its
    second switches, its keys beside Open settings."""

    def __init__(self, page, feature):
        self.page, self.f = page, feature
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.get_style_context().add_class("ctl-group")
        self.box.set_valign(Gtk.Align.START)
        top = Gtk.Box(spacing=8)
        icon = dp.label(feature["icon"], "ctl-icon", 0.5)
        top.pack_start(icon, False, False, 0)
        title = dp.label(feature["title"], "ctl-title")
        title.set_hexpand(True)
        top.pack_start(title, True, True, 0)
        self.switch = None
        if feature.get("switch"):
            self.switch = page.make_switch(lambda v: page.toggle(self, None, v))
            self.switch.set_valign(Gtk.Align.CENTER)
            top.pack_end(self.switch, False, False, 0)
        else:
            top.pack_end(dp.label("on demand", "ctl-sub"), False, False, 0)
        self.box.pack_start(top, False, False, 0)
        self.box.pack_start(wrapped(feature["line"]), False, False, 0)
        self.status = wrapped("○ reading…", "ctl-sub")
        self.box.pack_start(self.status, False, False, 0)
        self.extras_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.pack_start(self.extras_box, False, False, 0)
        self.extras = {}            # key -> (switch, label)
        foot = Gtk.Box(spacing=8)           # its keys and Open settings share one line
        self.keys = wrapped("", "ctl-sub")
        self.keys.set_max_width_chars(28)
        self.keys.set_hexpand(True)
        self.keys.set_valign(Gtk.Align.CENTER)
        self.keys.set_no_show_all(True)
        foot.pack_start(self.keys, True, True, 0)
        opener = link("Open settings", lambda: spawn(SETTINGS, feature["page"]))
        opener.set_valign(Gtk.Align.CENTER)
        foot.pack_end(opener, False, False, 0)
        self.box.pack_start(foot, False, False, 0)
        self.error = ""

    def show(self, st, keys):
        kind = st["kind"]
        self.status.get_style_context().remove_class("ctl-value")
        if kind == "running":
            self.status.get_style_context().add_class("ctl-value")
        text = f"{smart.KIND_GLYPH.get(kind, '·')} {st['text']}"
        if self.error:
            text += f"\n!  {self.error}"
        self.status.set_text(text)
        if self.switch is not None:
            self.switch.set_active(bool(st["on"]))
            self.switch.set_state(bool(st["on"]))
            self.switch.set_sensitive(bool(st["can_toggle"]))
        for key, caption, value, sensitive in st["extras"]:
            if key not in self.extras:
                sw = self.page.make_switch(lambda v, k=key: self.page.toggle(self, k, v))
                line = Gtk.Box(spacing=8)
                lab = wrapped(caption)
                lab.set_hexpand(True)
                line.pack_start(lab, True, True, 0)
                sw.set_valign(Gtk.Align.CENTER)
                line.pack_end(sw, False, False, 0)
                self.extras_box.pack_start(line, False, False, 0)
                self.extras[key] = (sw, lab)
            sw, lab = self.extras[key]
            sw.set_active(bool(value))
            sw.set_state(bool(value))
            sw.set_sensitive(bool(sensitive))
            lab.set_sensitive(bool(sensitive))
        self.keys.set_text("  ·  ".join(keys) if keys else "")
        self.keys.set_visible(bool(keys))

    def busy(self, words):
        self.status.get_style_context().remove_class("ctl-value")
        self.status.set_text(f"… {words}")
        if self.switch is not None:
            self.switch.set_sensitive(False)
        for sw, _lab in self.extras.values():
            sw.set_sensitive(False)


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.probes = {}
        self.states = {}
        self.generation = 0
        self.view = {}

        intro = dp.label("Every smart feature, on this computer only. No cloud.", "ctl-sub")
        intro.set_line_wrap(True)
        intro.set_xalign(0)
        w.pack_start(intro, False, False, 0)

        # -- privacy at a glance -------------------------------------------------------
        strip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        strip.get_style_context().add_class("ctl-group")
        strip.pack_start(heading("PRIVACY AT A GLANCE"), False, False, 0)
        self.senses = {}
        senses = Gtk.Grid(column_spacing=10, row_spacing=4, column_homogeneous=True)
        for i, sense in enumerate(smart.SENSES):         # two senses a line
            icon, title = smart.SENSE_TEXT[sense]
            all_off = link("Turn all off", lambda s=sense: self.all_off_sense(s))
            grid, sub = row(icon, title, "reading…", all_off)
            chips = Gtk.FlowBox()
            chips.set_selection_mode(Gtk.SelectionMode.NONE)
            chips.set_min_children_per_line(2)
            chips.set_max_children_per_line(2)
            chips.set_column_spacing(4)
            chips.set_row_spacing(4)
            chips.set_margin_start(16)          # under the row, a little in
            chips.set_halign(Gtk.Align.START)
            block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            block.pack_start(grid, False, False, 0)
            block.pack_start(chips, False, False, 0)
            senses.attach(block, i % 2, i // 2, 1, 1)
            self.senses[sense] = (sub, chips, all_off)
        strip.pack_start(senses, False, False, 0)
        foot = Gtk.Box(spacing=8)           # the hint and the links share one line
        note = dp.label("Click a chip to turn that one off.", "ctl-sub")
        note.set_xalign(0)
        foot.pack_start(note, True, True, 0)
        foot.pack_end(links_row(link("Folder access for AI", lambda: spawn(SETTINGS, "folders")),
                                link("Open Privacy", lambda: spawn(SETTINGS, "privacy"))), False, False, 0)
        strip.pack_start(foot, False, False, 0)
        w.pack_start(strip, False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        self.msg.set_xalign(0)
        self.msg.set_no_show_all(True)
        w.pack_start(self.msg, False, False, 0)

        # -- the cards, by group -------------------------------------------------------
        self.cards = {}
        for group in smart.GROUP_ORDER:
            w.pack_start(heading(group.upper()), False, False, 0)
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_homogeneous(True)
            flow.set_min_children_per_line(2)
            flow.set_max_children_per_line(2)
            flow.set_column_spacing(10)
            flow.set_row_spacing(0)
            for feature in smart.FEATURES:
                if feature["group"] == group:
                    card = Card(self, feature)
                    self.cards[feature["id"]] = card
                    flow.add(card.box)
            w.pack_start(flow, False, False, 0)

    # -- switches ------------------------------------------------------------------------
    def make_switch(self, on_change):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state: self.switched(on_change, state))
        return sw

    def switched(self, on_change, state):
        if not self.updating:
            on_change(state)
        return True             # the switch moves when the feature says it did

    def toggle(self, card, key, value):
        fid = card.f["id"]
        cmds = smart.switch_commands(fid, value) if key is None else smart.extra_commands(fid, key, value)
        card.error = ""
        card.busy("turning on" if value else "turning off")
        self.run_then_read(cmds, [fid], lambda err: setattr(card, "error", err))

    def run_then_read(self, cmds, feature_ids, on_error=None):
        """Run the commands, then read back only those features' probes (and
        the strip's), in the background; redraw everything from that."""
        names = smart.probes_of(feature_ids)

        def work():
            err = smart.execute(cmds)
            return err, smart.gather(names)

        def done(result):
            err, probes = result
            if on_error:
                on_error(err)
            elif err:
                self.msg.set_text(f"!  {err}")
                self.msg.show()
            self.probes.update(probes)
            self.draw()
        background(work, done)

    def off_item(self, off):
        self.msg.hide()
        ids = [fid for _l, o, fid in self.view_items() if o == off]
        self.run_then_read([off], [i for i in ids if i in smart.BY_ID] or ["memory"])

    def all_off_sense(self, sense):
        self.msg.hide()
        items = [(o, fid) for _l, o, fid in self.view[sense]["items"] if o]
        self.run_then_read([o for o, _f in items], [fid for _o, fid in items if fid in smart.BY_ID] or ["memory"])

    def view_items(self):
        return [item for entry in self.view.values() for item in entry["items"]]

    # -- reading -------------------------------------------------------------------------
    def refresh(self):
        self.generation += 1
        gen = self.generation
        background(smart.gather, lambda p: self.got(gen, p))

    def got(self, gen, probes):
        if gen != self.generation:
            return              # a newer refresh is on its way
        self.probes = probes
        self.draw()

    def draw(self):
        p = self.probes
        self.states = {f["id"]: smart.feature_state(f, p) for f in smart.FEATURES}
        binds = p.get("binds") or []
        self.updating = True
        try:
            for fid, card in self.cards.items():
                card.show(self.states[fid], smart.keys_for(card.f, binds))
            self.view = smart.privacy_view(self.states, p)
            for sense, (sub, chips, all_off) in self.senses.items():
                entry = self.view[sense]
                sub.set_text(smart.sense_summary(sense, entry))
                clear(chips)
                offable = 0
                for label_text, off, _fid in entry["items"]:
                    b = Gtk.Button(label=("✕  " if off else "") + label_text)
                    b.get_style_context().add_class("dev-pick")
                    b.get_style_context().add_class("chip")
                    b.set_can_focus(False)
                    if off:
                        offable += 1
                        b.set_tooltip_text("Turn this off")
                        b.connect("clicked", lambda _b, o=off: self.off_item(o))
                    else:
                        b.set_sensitive(False)
                    chips.add(b)
                all_off.set_visible(offable > 1)
                all_off.set_no_show_all(True)
        finally:
            self.updating = False
        self.widget.show_all()
