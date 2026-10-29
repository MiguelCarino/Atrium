#!/usr/bin/env python3
"""Bluetooth panel -- what the Bluetooth pill opens.

The adapter's power switch, then every paired device: its name, whether it
is connected, its battery when it reports one, a Connect / Disconnect
button and Forget (two clicks, panelui.Armed: a forgotten device has to be
paired again from scratch). "Pair new..." opens blueman-manager or GNOME
Settings' Bluetooth page, whichever is installed -- pairing needs a PIN or
a confirmation dialog, which is that program's job, not a bar card's.

Everything goes to BlueZ over D-Bus (Gio), asynchronously: a connect can
take ten seconds and the card must not freeze meanwhile. The row says
"Connecting..." while it runs; when it ends the card is redrawn from
BlueZ's own state, so a failure never leaves a row claiming a connection
that is not there -- BlueZ's error replaces the row's subtitle. The card
follows BlueZ's signals while open (a headset switched off shows at once).

No adapter, or bluetoothd not running: the card says so and offers nothing
that would fail.

    bluetooth_panel.py [x,y]   desktop position of the click that opened it
"""

import os
import shutil
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bluetooth as bt  # noqa: E402  (the pill's script: summarize, pair_command)
import panelui  # noqa: E402

label = panelui.label
WIDTH = 380
CALL_TIMEOUT_MS = 30000     # Connect waits for the device; give up after this


def device_sub(dev, busy="", error=""):
    """A device row's subtitle: what is happening to it now, else its
    state and battery."""
    if error:
        return error
    if busy:
        return busy
    bits = ["Connected" if dev["connected"] else "Not connected"]
    if dev.get("battery") is not None:
        bits.append(f"battery {dev['battery']}%")
    return " · ".join(bits)


def dbus_error_text(message):
    """The readable end of a GLib D-Bus error message ("GDBus.Error:org.
    bluez.Error.Failed: br-connection-page-timeout" -> "br-connection-page-
    timeout"); "Failed" when there is nothing to read."""
    return (message or "").strip().rsplit(": ", 1)[-1].strip() or "Failed"


class Bluetooth(panelui.Panel):
    def setup(self):
        self.bus = bt.system_bus()
        self.summary = {"adapter": None, "powered": False, "devices": []}
        self.busy = {}          # device path (or "power") -> "Connecting…" etc.
        self.errors = {}        # device path (or "power") -> last error
        self.drawn = None
        self.pending = 0
        self.subs = []

    def build(self):
        self.card.set_size_request(WIDTH + 30, -1)
        head = Gtk.Box(spacing=12)
        title = label("BLUETOOTH", "kb-heading")
        title.set_hexpand(True)
        head.pack_start(title, True, True, 0)
        self.pair = Gtk.Button(label="Pair new…")
        self.pair.get_style_context().add_class("ctl-link")
        self.pair.connect("clicked", self.on_pair)
        head.pack_end(self.pair, False, False, 0)
        self.card.pack_start(head, False, False, 0)

        power = Gtk.Grid()
        power.get_style_context().add_class("ctl-row")
        power.set_column_spacing(10)
        icon = label(bt.ICON, "ctl-icon", 0.5)
        icon.set_valign(Gtk.Align.CENTER)
        power.attach(icon, 0, 0, 1, 2)
        power.attach(label("Bluetooth", "ctl-title"), 1, 0, 1, 1)
        self.power_sub = label("", "ctl-sub")
        self.power_sub.set_hexpand(True)
        power.attach(self.power_sub, 1, 1, 1, 1)
        self.power = Gtk.Switch()
        self.power.set_valign(Gtk.Align.CENTER)
        self.power.connect("state-set", self.on_power)
        power.attach(self.power, 2, 0, 1, 2)
        self.power_row = power
        self.card.pack_start(power, False, False, 0)

        sep = Gtk.Separator()
        sep.get_style_context().add_class("ctl-sep")
        self.card.pack_start(sep, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.pack_start(self.body, False, False, 0)
        self.refresh()

    def on_ready(self):
        if self.bus is not None:
            for iface, member in ((bt.PROPS, "PropertiesChanged"), (bt.OBJMGR, "InterfacesAdded"),
                                  (bt.OBJMGR, "InterfacesRemoved")):
                self.subs.append(self.bus.signal_subscribe(
                    bt.BLUEZ, iface, member, None, None, Gio.DBusSignalFlags.NONE, self.soon))
        GLib.timeout_add_seconds(10, lambda: (self.refresh(), True)[1])    # safety net

    def soon(self, *_args):
        if not self.pending:
            self.pending = GLib.timeout_add(bt.DEBOUNCE_MS, self.refresh)

    # -- drawing --------------------------------------------------------------
    def refresh(self):
        """Ask BlueZ for its objects without waiting: the reply draws the
        card (draw). A synchronous call here would freeze the card -- and
        its Escape -- for as long as a busy bluetoothd takes to answer."""
        self.pending = 0
        if self.bus is None:
            self.draw(bt.summarize({}))
            return False
        self.bus.call(bt.BLUEZ, "/", bt.OBJMGR, "GetManagedObjects", None, None,
                      Gio.DBusCallFlags.NO_AUTO_START, 3000, None, self.got_objects)
        return False

    def got_objects(self, bus, result):
        try:
            objects = bus.call_finish(result).unpack()[0]
        except GLib.Error:              # bluetoothd not running
            objects = {}
        self.draw(bt.summarize(objects))

    def draw(self, summary):
        self.summary = summary
        key = repr((self.summary, self.busy, self.errors))
        if key == self.drawn:
            return False
        self.drawn = key
        s = self.summary
        have = s["adapter"] is not None
        self.power.handler_block_by_func(self.on_power)
        self.power.set_active(s["powered"])
        self.power.set_state(s["powered"])
        self.power.handler_unblock_by_func(self.on_power)
        self.power.set_sensitive(have and "power" not in self.busy)
        (self.power_row.get_style_context().add_class if s["powered"]
         else self.power_row.get_style_context().remove_class)("on")
        if not have:
            self.power_sub.set_text("No Bluetooth adapter (or bluetoothd is not running)")
        else:
            self.power_sub.set_text(self.errors.get("power") or self.busy.get("power")
                                    or ("On" if s["powered"] else "Off"))
        self.pair.set_sensitive(have and bt.pair_command(shutil.which) is not None)
        if bt.pair_command(shutil.which) is None:
            self.pair.set_tooltip_text("Install blueman (or GNOME Settings) to pair new devices")

        focus_path = getattr(self.get_focus(), "bt_path", None)
        for child in self.body.get_children():
            child.destroy()
        if have and not s["devices"]:
            self.body.pack_start(label("No paired devices. Pair one with “Pair new…”.", "ctl-sub"),
                                 False, False, 4)
        for dev in s["devices"]:
            self.body.pack_start(self.device_row(dev), False, False, 0)
        self.body.show_all()
        if focus_path:                       # keep the keyboard where it was
            for row in self.body.get_children():
                if not isinstance(row, Gtk.Container):
                    continue                 # the "No paired devices" line
                for child in row.get_children():
                    if getattr(child, "bt_path", None) == focus_path:
                        child.grab_focus()
                        break

    def device_row(self, dev):
        path = dev["path"]
        box = Gtk.Box(spacing=8)
        box.get_style_context().add_class("dk-fs")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name = label(dev["name"], "sn-value")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(28)
        text.pack_start(name, False, False, 0)
        sub = label(device_sub(dev, self.busy.get(path, ""), self.errors.get(path, "")), "ctl-sub")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.set_max_width_chars(36)
        text.pack_start(sub, False, False, 0)
        text.set_hexpand(True)
        box.pack_start(text, True, True, 0)

        act = Gtk.Button(label="Disconnect" if dev["connected"] else "Connect")
        act.get_style_context().add_class("dev-pick")
        act.set_valign(Gtk.Align.CENTER)
        act.bt_path = path
        act.set_sensitive(self.summary["powered"] and path not in self.busy)
        act.connect("clicked", lambda _b: self.connect_device(dev, not dev["connected"]))
        box.pack_start(act, False, False, 0)
        forget = panelui.Armed("Forget", lambda: self.forget(dev), cls="dev-pick")
        forget.set_valign(Gtk.Align.CENTER)
        forget.set_tooltip_text("Remove the pairing (click twice); it has to be paired again to use it")
        forget.set_sensitive(path not in self.busy)
        box.pack_start(forget, False, False, 0)
        box.set_size_request(WIDTH, -1)
        return box

    # -- actions --------------------------------------------------------------
    def call(self, key, busy_text, path, iface, method, args):
        """One BlueZ method, async; the row says busy_text until it returns."""
        if self.bus is None:
            return
        self.busy[key] = busy_text
        self.errors.pop(key, None)
        self.refresh()

        def done(bus, result):
            self.busy.pop(key, None)
            try:
                bus.call_finish(result)
            except GLib.Error as exc:
                self.errors[key] = dbus_error_text(exc.message)
            self.refresh()

        self.bus.call(bt.BLUEZ, path, iface, method, args, None, Gio.DBusCallFlags.NONE,
                      CALL_TIMEOUT_MS, None, done)

    def connect_device(self, dev, wanted):
        self.call(dev["path"], "Connecting…" if wanted else "Disconnecting…", dev["path"], bt.DEVICE,
                  "Connect" if wanted else "Disconnect", None)

    def forget(self, dev):
        adapter = self.summary.get("adapter")
        if adapter:
            self.call(dev["path"], "Forgetting…", adapter, bt.ADAPTER, "RemoveDevice",
                      GLib.Variant("(o)", (dev["path"],)))

    def on_power(self, _switch, wanted):
        adapter = self.summary.get("adapter")
        if adapter:
            self.call("power", "Turning on…" if wanted else "Turning off…", adapter, bt.PROPS, "Set",
                      GLib.Variant("(ssv)", (bt.ADAPTER, "Powered", GLib.Variant("b", wanted))))
        return True                     # redrawn from BlueZ, not from the click

    def on_pair(self, _button):
        cmd = bt.pair_command(shutil.which)
        if cmd:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            self.quit()


def main():
    panelui.run(Bluetooth)


if __name__ == "__main__":
    main()
