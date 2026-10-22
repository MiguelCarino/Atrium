#!/usr/bin/env python3
"""Notification history panel -- what the bell opens (and SUPER+ALT+N).

Newest first: who sent it, the summary, the first lines of the body. A
notification still on screen is marked "on screen"; clicking it runs its
default action (what clicking the popup would have done). Clicking one from
the history copies its text to the clipboard instead -- mako cannot re-run an
action once a notification has expired, but the text is often the point (a
code, a path, a link).

The Do Not Disturb switch is mako's do-not-disturb mode, the same one
ALT+SHIFT+D toggles. "Clear" dismisses what is on screen and empties this
list: mako has no command to empty its history, so notifications.py keeps the
newest id cleared and the panel shows only what arrives after it.

    notifications_panel.py [x,y]   desktop position of the click that opened it
"""

import html
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import notifications  # noqa: E402

MAX_SHOWN = 50             # mako's max-history; the list scrolls
WIDTH = 440


def label(text, cls, xalign=0.0):
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


class Notifications(panelui.Panel):
    def build(self):
        self.updating = False
        head = Gtk.Grid(column_spacing=12)
        title = label("NOTIFICATIONS", "kb-heading")
        title.set_hexpand(True)
        head.attach(title, 0, 0, 1, 1)
        head.attach(label("Do Not Disturb", "ctl-sub", 1.0), 1, 0, 1, 1)
        self.dnd = Gtk.Switch()
        self.dnd.set_valign(Gtk.Align.CENTER)
        self.dnd.connect("state-set", self.on_dnd)
        head.attach(self.dnd, 2, 0, 1, 1)
        self.card.pack_start(head, False, False, 0)

        # The card has a fixed height (panelui.CARD_HEIGHT, the same as the
        # updates panel beside it on the bar) and the list scrolls inside it.
        # The height has to be set: in a layer-shell window sized to its
        # content, a ScrolledWindow asks for nothing and collapses to one row.
        self.card.set_size_request(WIDTH + 30, panelui.CARD_HEIGHT)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll.add(self.body)
        self.card.pack_start(scroll, True, True, 0)

        clear = Gtk.Button(label="Clear")
        clear.get_style_context().add_class("ctl-link")
        clear.set_halign(Gtk.Align.END)
        clear.set_tooltip_text("Dismiss what is on screen and empty this list")
        clear.connect("clicked", lambda _b: (notifications.clear(), self.refresh()))
        self.card.pack_start(clear, False, False, 0)
        self.refresh()

    def refresh(self):
        self.updating = True
        self.dnd.set_state(notifications.dnd_on())
        self.updating = False
        for child in self.body.get_children():
            self.body.remove(child)
        items = notifications.entries()
        notifications.mark_seen(items)       # the bell's count goes back to 0
        if not items:
            self.body.pack_start(label("nothing yet this session", "ctl-sub"), False, False, 0)
        for item in items[:MAX_SHOWN]:
            self.body.pack_start(self.row(item), False, False, 0)
        if len(items) > MAX_SHOWN:
            self.body.pack_start(label(f"... {len(items) - MAX_SHOWN} older", "ctl-sub"),
                                 False, False, 0)
        self.body.show_all()

    def row(self, item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        top = Gtk.Box(spacing=8)
        app = label(item.get("app_name") or "?", "sn-label")
        app.set_hexpand(True)
        top.pack_start(app, True, True, 0)
        if item["source"] == "shown":
            top.pack_end(label("on screen", "sn-label", 1.0), False, False, 0)
        box.pack_start(top, False, False, 0)

        # Senders may escape their text as markup (Firefox sends "&gt;");
        # mako decodes it on screen, so this does too.
        summary = label(html.unescape(item.get("summary") or ""), "sn-value")
        summary.set_ellipsize(Pango.EllipsizeMode.END)
        summary.set_max_width_chars(48)
        box.pack_start(summary, False, False, 0)
        body = html.unescape(item.get("body") or "").strip()
        if body:
            text = label(body, "ctl-sub")
            text.set_line_wrap(True)
            text.set_lines(2)
            text.set_ellipsize(Pango.EllipsizeMode.END)
            text.set_max_width_chars(56)
            box.pack_start(text, False, False, 0)

        button = Gtk.Button()
        button.add(box)
        button.set_size_request(WIDTH, -1)
        button.get_style_context().add_class("dk-fs")
        if item["source"] == "shown" and "default" in (item.get("actions") or {}):
            button.set_tooltip_text("Click: open it (its default action)")
            button.connect("clicked", lambda _b: self.invoke(item["id"]))
        else:
            button.set_tooltip_text("Click: copy its text")
            button.connect("clicked", lambda _b: self.copy(item))
        return button

    def invoke(self, nid):
        notifications.makoctl("invoke", "-n", str(nid), "default")
        self.quit()

    def copy(self, item):
        text = "\n".join(t for t in (item.get("summary"), item.get("body")) if t)
        try:
            subprocess.run(["wl-copy"], input=text, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
        self.quit()

    def on_dnd(self, _switch, _state):
        if not self.updating:
            subprocess.run([os.path.join(HERE, "notifications.py"), "dnd"])
            GLib.timeout_add(150, lambda: (self.refresh(), False)[1])
        return True


if __name__ == "__main__":
    panelui.run(Notifications)
