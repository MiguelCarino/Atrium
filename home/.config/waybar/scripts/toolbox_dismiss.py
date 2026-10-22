#!/usr/bin/env python3
"""Click-outside-to-close for the toolbox section.

The toolbox is a waybar, not a panelui.Panel, so it cannot carry its own
ClickCatcher. toolbox.sh starts this alongside it when it opens and kills it
when it folds away. The toolbox sits on the overlay layer and the catchers on
top, so the toolbox stays above them; a click that reaches a catcher missed it.

    toolbox_dismiss.py
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panelui  # noqa: E402
from panelui import Gdk, Gtk  # noqa: E402

TOOLBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbox.sh")


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


def main():
    display = Gdk.Display.get_default()
    catchers = [panelui.ClickCatcher(display.get_monitor(i), dismiss)
                for i in range(display.get_n_monitors())]
    Gtk.main()
    del catchers


if __name__ == "__main__":
    main()
