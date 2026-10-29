#!/usr/bin/env python3
"""Reboot card, and the RESTART section of the updates card.

The bar has no reboot pill of its own any more: a restart being due shows as
a badge on the updates pill (updates.sh), whose card (updates_panel.py)
embeds RestartSection below. `panel.py toggle reboot` still opens this card
on its own, for anything that wants the restart part alone.

Why a reboot is due (reboot_needed.py's reasons: a newer kernel installed,
or libraries and services updated since boot), the command that does it,
and two buttons: "Check again" (needs-restarting now, not from the cache)
and "Reboot now" -- panelui.Armed, so the first click only says "Sure?" and
a second one within a few seconds runs `systemctl reboot`. Nothing here
reboots without those two clicks; save your work first, the card says so.

    reboot_panel.py [x,y]   desktop position of the click that opened it
"""

import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import panelui  # noqa: E402
import reboot_needed  # noqa: E402

label = panelui.label
WIDTH = 380
REBOOT = ["systemctl", "reboot"]
# The pill that shows a restart is due: the updates pill's badge (updates.sh
# asks reboot_needed.py on every run), so a new answer redraws that one.
BADGE_SIGNAL = "updates"


def explain(st):
    """The card's lines for a reboot_needed.status() answer. With no
    needs-restarting answer yet (checked_at None: the card's first draw,
    before its first check returns) nothing is said about the tool -- not
    asked is not the same as not installed."""
    lines = list(st.get("reasons") or []) or ["Nothing is waiting for a reboot."]
    if st.get("checked_at") is None:
        lines.append("Checking for updated libraries and services…")
    elif not st.get("checker"):
        lines.append("needs-restarting (dnf-utils) is not installed: only the kernel is checked.")
    return lines


class RestartSection(Gtk.Box):
    """The card's body as a widget of its own, so the updates card
    (updates_panel.py, its RESTART section) shows exactly this one: the
    reasons, the hint with the command, Check again and the two-click
    Reboot now. `heading` is the section's title; `quit` closes whichever
    card holds it once the reboot is handed to systemd.

    The first draw is reboot_needed's cached answer (status(run=False): a
    stat and a read, never needs-restarting), and only when there is no
    answer at all is it asked -- in a thread, like Check again. Either way
    the bar's restart badge is redrawn afterwards: it is the updates pill's
    now (bar_signals.py "updates")."""

    def __init__(self, heading, quit):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.quit = quit
        self.pack_start(label(heading, "kb-heading"), False, False, 0)
        self.lines = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.pack_start(self.lines, False, False, 4)
        hint = label("Restarting applies them. Save your work first.\n"
                     f"Command:  {' '.join(REBOOT)}", "ctl-sub")
        hint.set_line_wrap(True)
        hint.set_max_width_chars(52)
        hint.set_selectable(True)
        hint.set_can_focus(False)
        self.pack_start(hint, False, False, 4)

        row = Gtk.Box(spacing=8)
        self.check = Gtk.Button(label="Check again")
        self.check.get_style_context().add_class("ctl-link")
        self.check.connect("clicked", self.on_check)
        row.pack_start(self.check, False, False, 0)
        self.reboot = panelui.Armed("Reboot now", self.on_reboot, sure="Sure? Click to reboot")
        self.reboot.set_tooltip_text("Click twice: the first asks, the second restarts the machine")
        row.pack_end(self.reboot, False, False, 0)
        self.pack_start(row, False, False, 0)
        st = reboot_needed.status(run=False)
        self.show_status(st)
        if st.get("checked_at") is None:
            self.on_check(None)         # never asked yet: ask, off the GTK thread

    def show_status(self, st):
        for child in self.lines.get_children():
            child.destroy()
        for line in explain(st):
            item = label(line, "sn-value")
            item.set_line_wrap(True)
            item.set_max_width_chars(52)
            self.lines.pack_start(item, False, False, 0)
        self.lines.show_all()

    def on_check(self, _button):
        self.check.set_sensitive(False)
        self.check.set_label("Checking…")

        def work():
            st = reboot_needed.status(force=True)
            GLib.idle_add(self.checked, st)
        threading.Thread(target=work, daemon=True).start()

    def checked(self, st):
        self.check.set_sensitive(True)
        self.check.set_label("Check again")
        self.show_status(st)
        try:
            import bar_signals
            bar_signals.poke(BADGE_SIGNAL)
        except Exception:  # noqa: BLE001 - no bar: nothing to redraw
            pass
        return False

    def on_reboot(self):
        # The owner's second click: hand it to systemd and get out of the way.
        subprocess.Popen(REBOOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        self.quit()


class Reboot(panelui.Panel):
    def build(self):
        self.card.set_size_request(WIDTH + 30, -1)
        self.card.pack_start(RestartSection("REBOOT NEEDED", self.quit), False, False, 0)


def main():
    panelui.run(Reboot)


if __name__ == "__main__":
    main()
