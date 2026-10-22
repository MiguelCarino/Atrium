"""Settings page: the smart clipboard (smart-clipboard.py) and asking about
the screen (screen-ask.py).

    SMART CLIPBOARD        the switch (smart-clipboard.service), and each kind
                           of copy it recognises on / off, with an example;
                           what it never acts on
    ASK ABOUT THE SCREEN   which local vision model would answer now (and
                           why not, when none would), and buttons that start
                           it on a region or copy the text of one

Everything goes through `smart-clipboard.py get --json` / `set ...` and
`screen-ask.py which --json` (which loads nothing and starts nothing); the
page keeps nothing of its own.
"""
import os
import subprocess

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "smartclip", "title": "Smart clipboard", "icon": "", "group": "Apps", "order": 37,
        "keywords": ["clipboard suggestions", "copy actions", "portapapeles", "tracking number", "parcel",
                     "colour code", "color code", "pretty print json", "address map", "stack trace",
                     "ask about the screen", "vision model", "screenshot question", "ocr", "copy text",
                     "what is this error", "table to csv", "pregunta pantalla"]}

SMART = os.path.join(HYPR, "smart-clipboard.py")
SCREEN_ASK = os.path.join(HYPR, "screen-ask.py")
SETTINGS = os.path.join(HYPR, "settings.py")
ICONS = {"url": "", "email": "", "phone": "", "address": "", "colour": "",
         "path": "", "error": "", "tracking": "", "date": "", "math": "",
         "json": ""}
NEVER = ("Never for passwords or secrets: copies a password manager marks as sensitive, anything copied "
         "while a password manager or a private window has the focus, card numbers, IBANs, CLABEs, keys "
         "and tokens, and anything that looks like a password. Nothing is sent anywhere: fast rules on "
         "this computer decide, and nothing happens until you click.")


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.kind_switches = {}

        w.pack_start(heading("SMART CLIPBOARD"), False, False, 0)
        self.main_switch = self.switch(lambda on: self.act("set", "on" if on else "off"))
        grid, self.main_sub = row("", "Suggestions when you copy",
                                  "A small card offers one to three things to do with what you copied.",
                                  self.main_switch)
        w.pack_start(grid, False, False, 0)
        self.kinds_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        w.pack_start(self.kinds_box, False, False, 0)
        grid, _ = row("", "Passwords are left alone", NEVER)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Privacy", lambda: spawn(SETTINGS, "privacy"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("ASK ABOUT THE SCREEN"), False, False, 0)
        grid, self.model_sub = row("", "Ask a local vision model about part of the screen",
                                   "checking which model would answer…")
        w.pack_start(grid, False, False, 0)
        grid, _ = row("", "How",
                      "Pick a region (or the focused window), then type or say a question: \"what is this "
                      "error\", \"translate\", \"turn this table into CSV\". Also in the screen actions menu "
                      "(Ask about this). Screenshots are deleted when the card closes; the answer comes "
                      "from LM Studio on this computer only, never the cloud, and nothing is unloaded to "
                      "make room for it.")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Ask about a region", lambda: spawn(SCREEN_ASK, "region")),
                               link("Copy text from a region", lambda: spawn(SCREEN_ASK, "ocr", "region"))),
                     False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    def switch(self, on_change):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state: self.switched(on_change, state))
        return sw

    def switched(self, on_change, state):
        if not self.updating:
            on_change(state)
        return True             # the switch moves when refresh() says the setting did

    def act(self, *args):
        def work():
            try:
                res = subprocess.run([SMART, *args], capture_output=True, text=True, timeout=30)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        self.msg.set_text("")
        background(work, lambda err: (self.msg.set_text(err), self.refresh()))

    def refresh(self):
        background(lambda: run_json(SMART, "get", "--json"), self.show)
        background(lambda: run_json(SCREEN_ASK, "which", "--json", timeout=30), self.show_model)

    def show(self, data):
        if not data:
            self.msg.set_text("smart-clipboard.py did not answer (run it in a terminal to see why)")
            return
        self.updating = True
        try:
            self.main_switch.set_active(data["on"])
            self.main_switch.set_state(data["on"])
            sub = ("on: a card comes for the kinds switched on below" if data["on"] else
                   "off: copies are not looked at")
            if data["on"] != data["enabled"]:
                sub += "  ·  " + ("not started at login" if data["on"] else "starts again at the next login")
            self.main_sub.set_text(sub)
            if not self.kind_switches:
                for k in data["kinds"]:
                    sw = self.switch(lambda on, key=k["kind"]: self.act("set", key, "on" if on else "off"))
                    grid, _ = row(ICONS.get(k["kind"], ""), k["label"], k["example"], sw)
                    self.kind_switches[k["kind"]] = (sw, grid)
                    self.kinds_box.pack_start(grid, False, False, 0)
            for k in data["kinds"]:
                sw, grid = self.kind_switches[k["kind"]]
                sw.set_active(k["on"])
                sw.set_state(k["on"])
                grid.set_sensitive(data["on"])
        finally:
            self.updating = False
        self.widget.show_all()

    def show_model(self, data):
        if not data:
            self.model_sub.set_text("screen-ask.py did not answer")
        elif data.get("model"):
            name = data["model"].split("/")[-1]
            self.model_sub.set_text(f"{name} would answer now" + (" (already loaded)" if data.get("loaded")
                                                                    else " (loaded when you ask)"))
        else:
            vision = ", ".join(v.split("/")[-1] for v in data.get("vision") or [])
            self.model_sub.set_text(f"no model right now: {data.get('why')}"
                                    + (f"  ·  vision models: {vision}" if vision else ""))
