#!/usr/bin/env python3
"""Quick note (SUPER+SHIFT+N): a one-line box over everything; type, Enter, gone.

Each note is appended to a markdown inbox as one list item with the time:

    ~/Documents/Notes/inbox.md
    - 2026-10-17 12:50  call the supplier about the PSU

so it is greppable, diffable, and opens as a checklist in any markdown editor.
The last few notes show under the box, so you can see it took.

    quicknote.py          open it (again to close)
    quicknote.py open     open the inbox in the default editor instead

Keys: Enter saves and closes, Esc closes without saving, Ctrl+O opens the inbox.

Same window recipe as launcher.py (gtk-layer-shell, exclusive keyboard, the
click-outside sheet the bar's panels use) and the same stylesheet, so it looks
like the launcher's search box on its own.
"""

import datetime
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launcher  # noqa: E402  (close_running, focused_monitor, load_css, on_sigterm)

INBOX = os.path.expanduser("~/Documents/Notes/inbox.md")
PID_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "quicknote.pid")
RECENT = 3
WIDTH = 720


def recent_notes():
    try:
        with open(INBOX) as handle:
            lines = [line.rstrip("\n") for line in handle if line.startswith("- ")]
    except OSError:
        return []
    return lines[-RECENT:]


def append(text):
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    new = not os.path.exists(INBOX)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(INBOX, "a") as handle:
        if new:
            handle.write("# Inbox\n\nQuick notes (SUPER+SHIFT+N). Newest at the bottom.\n\n")
        handle.write(f"- {stamp}  {text}\n")


def open_inbox():
    if not os.path.exists(INBOX):
        append("(inbox created)")
    subprocess.Popen(["xdg-open", INBOX], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


class Note(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_name("launcher-window")
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        GtkLayerShell.init_for_window(self)
        # "launcher": the wofi-glass layer rule (pop-in, blur, dim behind) in
        # lua/rules.lua matches this namespace.
        GtkLayerShell.set_namespace(self, "launcher")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        monitor = launcher.focused_monitor(self.get_display())
        if monitor:
            GtkLayerShell.set_monitor(self, monitor)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.set_name("card")
        card.set_size_request(WIDTH, -1)
        self.add(card)

        self.entry = Gtk.Entry()
        self.entry.set_name("search")
        self.entry.set_placeholder_text("quick note")
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "document-edit-symbolic")
        self.entry.connect("activate", self.save)
        card.pack_start(self.entry, False, False, 0)

        # GTK3 hides an entry's placeholder once it has focus -- which this one
        # always does -- so the keys get a line of their own.
        hint = Gtk.Label(label="Enter saves  \u00b7  Esc cancels  \u00b7  Ctrl+O opens "
                               + INBOX.replace(os.path.expanduser("~"), "~"), xalign=0)
        hint.get_style_context().add_class("hero-hint")
        hint.set_margin_start(18)
        hint.set_margin_bottom(8)
        card.pack_start(hint, False, False, 0)

        for line in recent_notes():
            label = Gtk.Label(label=line[2:], xalign=0)
            label.get_style_context().add_class("hero-sub")
            label.set_ellipsize(3)              # Pango.EllipsizeMode.END
            label.set_margin_start(18)
            label.set_margin_end(18)
            label.set_margin_bottom(6)
            card.pack_start(label, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()
        self.entry.grab_focus()
        try:
            import panelui
            display = self.get_display()
            self.catchers = [panelui.ClickCatcher(display.get_monitor(i), Gtk.main_quit)
                             for i in range(display.get_n_monitors())]
        except Exception as exc:
            print(f"quicknote: no click-outside: {exc}", file=sys.stderr)

    def save(self, _entry):
        text = " ".join(self.entry.get_text().split())
        if text:
            append(text)
        Gtk.main_quit()

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()
            return True
        if event.keyval in (Gdk.KEY_o, Gdk.KEY_O) and event.state & Gdk.ModifierType.CONTROL_MASK:
            open_inbox()
            Gtk.main_quit()
            return True
        return False


def main():
    if sys.argv[1:2] == ["open"]:
        open_inbox()
        return
    launcher.PID_FILE = PID_FILE
    if launcher.close_running(b"quicknote.py"):
        return
    with open(PID_FILE, "w") as handle:
        handle.write(str(os.getpid()))
    launcher.on_sigterm(Gtk.main_quit)
    launcher.load_css()
    Note()
    try:
        Gtk.main()
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
