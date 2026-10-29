#!/usr/bin/env python3
"""Print queue panel -- what the printer pill opens.

Every printer with its state (idle / printing / stopped) and any trouble it
reports (out of paper, ink low...), then the queue: each job with its
printer, owner, pages so far and age, and Hold / Release / Cancel. Below,
your last few finished jobs (printed, cancelled, failed). It follows CUPS
live while open (a look every POLL ms; the queue is on this machine, so a
look is cheap).

"Cancel all" cancels your own queued jobs -- two clicks (panelui.Armed: the
first says "Sure?"), since a cancelled job cannot be brought back; "Printer
settings" opens GNOME Settings > Printers (or CUPS's own page). The CUPS calls are
hypr/scripts/printing.py's.

    printing_panel.py [x,y]   desktop position of the click that opened it
"""

import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import panelui  # noqa: E402
import printing  # noqa: E402

WIDTH = 440
POLL = 1500             # ms
HISTORY = 5


label = panelui.label


def ago(stamp):
    if not stamp:
        return ""
    s = max(0, int(time.time() - stamp))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return time.strftime("%d %b", time.localtime(stamp))


class Printing(panelui.Panel):
    def build(self):
        self.drawn = None
        head = Gtk.Box(spacing=12)
        title = label("PRINTING", "kb-heading")
        title.set_hexpand(True)
        head.pack_start(title, True, True, 0)
        settings = Gtk.Button(label="Printer settings")
        settings.get_style_context().add_class("ctl-link")
        settings.connect("clicked", lambda _b: (printing.open_settings(), self.quit()))
        head.pack_end(settings, False, False, 0)
        self.card.pack_start(head, False, False, 0)

        self.card.set_size_request(WIDTH + 30, panelui.CARD_HEIGHT)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll.add(self.body)
        self.card.pack_start(scroll, True, True, 0)

        self.cancel_all = panelui.Armed("Cancel all", lambda: self.act(printing.cancel, "all"))
        self.cancel_all.set_halign(Gtk.Align.END)
        self.cancel_all.set_tooltip_text("Cancel every job of yours still in the queue (click twice)")
        self.card.pack_start(self.cancel_all, False, False, 0)
        self.refresh()

    def on_ready(self):
        GLib.timeout_add(POLL, self.refresh)

    def act(self, fn, *args):
        try:
            fn(*args)
        except Exception as exc:          # not your job, already gone, cupsd down
            self.error = str(exc) or exc.__class__.__name__
        self.drawn = None
        self.refresh()

    def refresh(self):
        state = printing.snapshot()
        done = printing.history(HISTORY)
        key = repr((state, done, getattr(self, "error", "")))
        if key == self.drawn:
            return True
        self.drawn = key
        for child in self.body.get_children():
            self.body.remove(child)
        if state.get("error"):
            self.body.pack_start(label(f"CUPS cannot be reached: {state['error']}", "ctl-sub"), False, False, 0)
        if getattr(self, "error", ""):
            self.body.pack_start(label(self.error, "ctl-sub"), False, False, 0)
            self.error = ""
        for name, p in sorted(state["printers"].items(), key=lambda kv: kv[0] != state.get("default")):
            self.body.pack_start(self.printer_row(name, p, name == state.get("default")), False, False, 0)
        if not state["printers"] and not state.get("error"):
            self.body.pack_start(label("no printers set up", "ctl-sub"), False, False, 0)

        self.body.pack_start(self.section("QUEUE"), False, False, 0)
        if not state["jobs"]:
            self.body.pack_start(label("nothing waiting to print", "ctl-sub"), False, False, 0)
        for job in state["jobs"]:
            self.body.pack_start(self.job_row(job), False, False, 0)
        self.cancel_all.set_sensitive(any(j["mine"] for j in state["jobs"]))

        if done:
            self.body.pack_start(self.section("RECENT"), False, False, 0)
            for job in done:
                self.body.pack_start(self.done_row(job), False, False, 0)
        self.body.show_all()
        return True

    def section(self, text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sep = Gtk.Separator()
        sep.get_style_context().add_class("ctl-sep")
        box.pack_start(sep, False, False, 4)
        box.pack_start(label(text, "sn-label"), False, False, 0)
        return box

    def printer_row(self, name, p, default):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        top = Gtk.Box(spacing=8)
        title = label(name + ("  ·  default" if default else ""), "sn-value")
        title.set_hexpand(True)
        top.pack_start(title, True, True, 0)
        state = printing.PRINTER_STATE.get(p["state"], "?")
        if not p["accepting"]:
            state += ", not accepting jobs"
        top.pack_end(label(state, "sn-label", 1.0), False, False, 0)
        box.pack_start(top, False, False, 0)
        words = [w for _, w in printing.troubles(p["reasons"])]
        sub = " · ".join(filter(None, [", ".join(words), p["message"]]))
        if sub:
            line = label(("⚠ " if printing.severe(p["reasons"]) or p["state"] == 5 else "") + sub, "ctl-sub")
            line.set_line_wrap(True)
            line.set_max_width_chars(56)
            box.pack_start(line, False, False, 0)
        box.get_style_context().add_class("dk-fs")
        box.set_size_request(WIDTH, -1)
        return box

    def job_row(self, job):
        box = Gtk.Box(spacing=8)
        box.get_style_context().add_class("dk-fs")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name = label(job["name"] or f"job {job['id']}", "sn-value")
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.set_max_width_chars(34)
        text.pack_start(name, False, False, 0)
        bits = [printing.JOB_STATE.get(job["state"], "?"), job["printer"]]
        if not job["mine"]:
            bits.append(job["user"])
        if job["pages"]:
            bits.append(printing.pages_text(job["pages"]) + " done")
        if job["kb"]:
            bits.append(f"{job['kb']} KB")
        bits.append(ago(job["created"]))
        bits += job["reasons"][:1] if job["state"] == printing.STOPPED else []
        sub = label(" · ".join(filter(None, bits)), "ctl-sub")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.set_max_width_chars(48)
        text.pack_start(sub, False, False, 0)
        text.set_hexpand(True)
        box.pack_start(text, True, True, 0)
        if job["mine"]:
            held = job["state"] == printing.HELD
            pause = Gtk.Button(label="Release" if held else "Hold")
            pause.get_style_context().add_class("dev-pick")
            pause.set_valign(Gtk.Align.CENTER)
            pause.set_tooltip_text("Print it now" if held else "Keep it in the queue without printing")
            pause.connect("clicked", lambda _b: self.act(printing.hold, job["id"], held))
            box.pack_start(pause, False, False, 0)
            stop = Gtk.Button(label="Cancel")
            stop.get_style_context().add_class("dev-pick")
            stop.set_valign(Gtk.Align.CENTER)
            stop.connect("clicked", lambda _b: self.act(printing.cancel, str(job["id"])))
            box.pack_start(stop, False, False, 0)
        box.set_size_request(WIDTH, -1)
        return box

    def done_row(self, job):
        box = Gtk.Box(spacing=8)
        box.get_style_context().add_class("dk-fs")
        name = label(job["name"] or f"job {job['id']}", "ctl-sub")
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.set_max_width_chars(30)
        name.set_hexpand(True)
        box.pack_start(name, True, True, 0)
        bits = [printing.JOB_STATE.get(job["state"], "?"), printing.pages_text(job["pages"]),
                ago(job["completed"] or job["created"])]
        box.pack_end(label(" · ".join(filter(None, bits)), "sn-label", 1.0), False, False, 0)
        box.set_size_request(WIDTH, -1)
        return box


if __name__ == "__main__":
    panelui.run(Printing)
