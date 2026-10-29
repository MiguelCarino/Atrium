#!/usr/bin/env python3
"""Click-outside-to-close for the toolbox section.

The toolbox is a waybar, not a panelui.Panel, so it cannot carry its own
ClickCatcher. toolbox.sh starts this alongside it when it opens and kills it
when it folds away. The toolbox sits on the overlay layer and the catchers on
top, so the toolbox stays above them; a click that reaches a catcher missed it.

Moving on from the keyboard closes it too: a switch of workspace, of focused
window or of fullscreen (Hyprland's events, through hyprbus) means you are
somewhere else now, and a card left hanging over it is in the way. Clicking a
row of the card moves none of them.

    toolbox_dismiss.py
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panelui  # noqa: E402
from panelui import Gdk, GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import hyprbus  # noqa: E402  (the shared event relay, or socket2 directly)

TOOLBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbox.sh")
# Hyprland events that mean you went somewhere else.
ELSEWHERE = {"workspacev2", "activewindowv2", "fullscreen"}
ELSEWHERE_B = {name.encode() for name in ELSEWHERE}


dismissed = False


def dismiss():
    # Once only: a double click delivers a second press (and a 2BUTTON_PRESS)
    # before the loop exits, and every extra hide is another toggle of waybar.
    global dismissed
    if dismissed:
        return
    dismissed = True
    # toolbox.sh hide kills this process too; quit first so either order is fine.
    Gtk.main_quit()
    subprocess.Popen([TOOLBOX, "hide"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def on_event(sock, _cond):
    try:
        chunk = sock.recv(4096)
    except OSError:
        return False
    if not chunk:                       # the relay went away: clicks still close it
        return False
    if any(hyprbus.event_name(line) in ELSEWHERE_B
           for line in chunk.splitlines()):
        dismiss()
        return False
    return True


def main():
    display = Gdk.Display.get_default()
    catchers = [panelui.ClickCatcher(display.get_monitor(i), dismiss)
                for i in range(display.get_n_monitors())]
    try:
        sock = hyprbus.connect(ELSEWHERE)
        GLib.io_add_watch(sock.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP,
                          lambda _fd, cond: on_event(sock, cond))
    except OSError:
        sock = None                     # no Hyprland events: clicks still close it
    Gtk.main()
    del catchers


if __name__ == "__main__":
    main()
