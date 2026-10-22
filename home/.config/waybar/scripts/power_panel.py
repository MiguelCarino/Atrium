#!/usr/bin/env python3
"""Power panel — what the power pill at the far right of the bar (and
SUPER+Escape) opens.

    header     who is logged in, on which machine, and how long it has been up
    tiles      Lock, Suspend, Log out, Reboot, Power off

Lock and Suspend fire on the first click: both come straight back with a
password, nothing is lost. Log out, Reboot and Power off end every program in
the session, so they take two clicks -- the first arms the tile (it turns
magenta and says "Click again to reboot"), the second fires it. An armed tile
disarms itself after ARM_SECONDS, and arming one tile disarms any other, so a
stray click left over from earlier can never complete a different action.

Why a second click and not a dialog: the panel takes no keyboard focus (see
panelui.place -- focus would be stolen from whatever is playing), so there is
no Enter/Esc to answer a dialog with, and a dialog on top of a popup on top of
the bar is two surfaces too many. The tile itself is the confirmation.

The confirm logic lives in Confirmer, which knows nothing about GTK: it is
handed a scheduler and the actions, so it can be unit-tested with fakes and
without anything ever being executed.

Every action closes the panel first. A lock screen or a suspend that comes
back to a stale popup still floating under the bar looks like a bug.

    power_panel.py [x,y]   desktop position of the click that opened it

POWER_PANEL_DRYRUN=1 in the environment turns every action into a print and a
notify-send -- for testing the panel on a live desktop without consequences.
"""

import getpass
import os
import socket
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402

ARM_SECONDS = 3
UPTIME_MS = 30000           # the header only shows minutes; no need to tick faster
DRYRUN = os.environ.get("POWER_PANEL_DRYRUN") == "1"

# (key, Font Awesome glyph, label, verb for "Click again to <verb>",
#  command, needs confirming). Glyphs as escapes, never literal PUA characters:
# an editor that cannot render them silently drops or mangles them.
#
# Log out runs ~/.config/hypr/scripts/session-exit.sh, the same script as
# SUPER+SHIFT+M: `uwsm stop` in the uwsm-managed session (which also stops the
# systemd services bound to the session), Hyprland's own exit otherwise. Not
# `loginctl terminate-session`: the compositor's exit lets Hyprland shut its
# clients down in order.
ACTIONS = [
    ("lock",     "\uf023", "Lock",      "lock",
     ["hyprlock"],                                  False),
    ("suspend",  "\uf186", "Suspend",   "suspend",
     ["systemctl", "suspend"],                      False),
    ("logout",   "\uf2f5", "Log out",   "log out",
     [os.path.expanduser("~/.config/hypr/scripts/session-exit.sh")], True),
    ("reboot",   "\uf2f9", "Reboot",    "reboot",
     ["systemctl", "reboot"],                       True),
    ("poweroff", "\uf011", "Power off", "power off",
     ["systemctl", "poweroff"],                     True),
]


# Runs "$@" and reports a non-zero exit (or a missing binary: sh prints
# "not found" and exits 127) with the last lines of its output. Only the tail:
# hyprlock logs a lot while the screen is locked.
REPORT_FAILURE = (
    'out=$("$@" 2>&1) || notify-send -u critical "Power panel" '
    '"$1 failed: $(printf %s "$out" | tail -n 3)"'
)


class Confirmer:
    """Two-click confirmation, independent of GTK.

        press(key) -> "fired" | "armed" | "ignored"

    schedule(seconds, callback) must return a handle that cancel(handle)
    accepts -- GLib.timeout_add_seconds / GLib.source_remove in the panel,
    fakes in the tests. on_change(key, armed) lets the view repaint a tile.

    Once anything has fired every later press is ignored: the panel is on its
    way out, and a double-click must not run `systemctl reboot` twice (or lock
    and then suspend on the way)."""

    def __init__(self, actions, confirm, schedule, cancel, on_change=None,
                 timeout=ARM_SECONDS):
        self.actions = actions          # key -> callable
        self.confirm = confirm          # set of keys that need two clicks
        self.schedule = schedule
        self.cancel = cancel
        self.on_change = on_change or (lambda key, armed: None)
        self.timeout = timeout
        self.armed = None
        self.timer = None
        self.fired = None

    def press(self, key):
        if self.fired is not None or key not in self.actions:
            return "ignored"
        if key in self.confirm and self.armed != key:
            self.disarm()               # a different tile was armed: drop it
            self.armed = key
            self.timer = self.schedule(self.timeout, self.expire)
            self.on_change(key, True)
            return "armed"
        # Either a one-click action, or the second click on the armed tile.
        self.disarm()
        self.fired = key
        self.actions[key]()
        return "fired"

    def disarm(self):
        if self.timer is not None:
            self.cancel(self.timer)
            self.timer = None
        if self.armed is not None:
            key, self.armed = self.armed, None
            self.on_change(key, False)

    def expire(self):
        """Timer callback. The timer is one-shot: return False so GLib drops
        the source, and forget the handle so disarm() does not remove a source
        that no longer exists (GLib warns about that)."""
        self.timer = None
        self.disarm()
        return False


def uptime_text():
    """'3d 4h', '5h 12m', '7m' -- /proc/uptime's first field is seconds."""
    try:
        with open("/proc/uptime") as handle:
            seconds = int(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return "unknown"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def user_text():
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = os.environ.get("USER", "?")
    return f"{user}@{socket.gethostname().split('.')[0]}"


def label(text, cls, xalign=0.0):
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


class Tile:
    """One big button: glyph over a caption. Armed, the caption becomes the
    confirmation prompt and the .armed class turns the tile magenta."""

    def __init__(self, key, glyph, caption, verb, danger, on_click):
        self.caption, self.verb = caption, verb
        self.button = Gtk.Button()
        self.button.set_relief(Gtk.ReliefStyle.NONE)
        self.button.set_can_focus(False)
        ctx = self.button.get_style_context()
        ctx.add_class("pw-tile")
        if danger:
            ctx.add_class("danger")     # magenta hover, so it reads as "careful"

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_valign(Gtk.Align.CENTER)
        self.glyph = label(glyph, "pw-glyph", 0.5)
        self.text = label(caption, "pw-label", 0.5)
        # Wraps rather than widening the tile: "Click again to power off" is
        # three times the width of "Lock", and the row must not jump.
        self.text.set_line_wrap(True)
        self.text.set_justify(Gtk.Justification.CENTER)
        self.text.set_max_width_chars(9)
        box.pack_start(self.glyph, False, False, 0)
        box.pack_start(self.text, False, False, 0)
        self.button.add(box)
        self.button.connect("clicked", lambda *_: on_click(key))

    def set_armed(self, armed):
        ctx = self.button.get_style_context()
        if armed:
            ctx.add_class("armed")
            self.text.set_text(f"Click again to {self.verb}")
        else:
            ctx.remove_class("armed")
            self.text.set_text(self.caption)


class Power(panelui.Panel):
    def setup(self):
        self.tiles = {}
        commands = {key: cmd for key, _g, _c, _v, cmd, _d in ACTIONS}
        self.confirmer = Confirmer(
            actions={key: (lambda k=key: self.run(k, commands[k])) for key in commands},
            confirm={key for key, *_rest, danger in ACTIONS if danger},
            schedule=GLib.timeout_add_seconds,
            cancel=GLib.source_remove,
            on_change=lambda key, armed: self.tiles[key].set_armed(armed))

    def build(self):
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        head.get_style_context().add_class("pw-header")
        head.pack_start(label("SESSION", "kb-heading"), False, False, 0)
        self.uptime = label("", "pw-uptime", 1.0)
        head.pack_end(self.uptime, False, False, 0)
        head.pack_end(label(user_text(), "pw-user", 1.0), False, False, 0)
        self.card.pack_start(head, False, False, 0)
        self.refresh_uptime()

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_homogeneous(True)       # equal tiles whatever the caption says
        for key, glyph, caption, verb, _cmd, danger in ACTIONS:
            tile = Tile(key, glyph, caption, verb, danger, self.confirmer.press)
            self.tiles[key] = tile
            row.pack_start(tile.button, True, True, 0)
        self.card.pack_start(row, False, False, 0)

    def on_ready(self):
        GLib.timeout_add(UPTIME_MS, self.refresh_uptime)

    def refresh_uptime(self):
        self.uptime.set_text(f"\uf017  up {uptime_text()}")   # clock glyph
        return True

    def run(self, key, cmd):
        """Hide first, then launch detached and quit. start_new_session: the
        command must outlive this process, which exits a moment later.

        The command runs under a small sh wrapper that waits for it and, if it
        fails, says so through mako. By then this panel is long gone, so
        without the wrapper a refused reboot/poweroff (a block-mode shutdown
        inhibitor, or a polkit prompt nobody can answer while no polkit agent
        runs) would just make the panel vanish with nothing happening."""
        self.hide()
        # Queued before anything that could raise, so the panel always exits
        # even if notify-send itself fails below.
        GLib.timeout_add(200, self.quit)
        try:
            if DRYRUN:
                print(f"power_panel: DRYRUN {key}: {' '.join(cmd)}", flush=True)
                subprocess.Popen(["notify-send", "Power panel (dry run)",
                                  f"Would run: {' '.join(cmd)}"],
                                 start_new_session=True)
                return
            subprocess.Popen(["sh", "-c", REPORT_FAILURE, "sh", *cmd],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            # sh missing is near impossible; still, say so rather than vanish.
            try:
                subprocess.Popen(["notify-send", "-u", "critical", "Power panel",
                                  f"{cmd[0]} failed: {exc}"], start_new_session=True)
            except OSError:
                pass

if __name__ == "__main__":
    panelui.run(Power)
