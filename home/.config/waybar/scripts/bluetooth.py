#!/usr/bin/env python3
"""Bluetooth pill (custom/bluetooth) and the BlueZ helpers its panel uses.

    bluetooth.py watch      JSON lines forever, for a module with no
                            "interval": a line only when the pill changes
    bluetooth.py once       one line and exit (to try it by hand)
    bluetooth.py status     what the panel reads, as JSON

Straight from BlueZ over D-Bus (Gio, no bluetoothctl): one GetManagedObjects
call gives the adapter, every known device and their batteries. The watcher
sleeps in a GLib main loop on BlueZ's own signals -- PropertiesChanged,
InterfacesAdded / Removed, bluetoothd coming and going -- and re-reads only
when one arrives (debounced: a connect is a burst of them), plus a safety
look every SAFETY seconds. No polling, no forks.

What the pill shows:

    no adapter, or bluetoothd not running       nothing (hidden)
    adapter off and nothing paired              nothing (hidden): a machine
                                                that never uses Bluetooth
                                                gets no pill for it
    adapter off, devices paired                 a dim glyph (.off)
    on, nothing connected                       the glyph (.on)
    on, devices connected                       the glyph, how many, and the
                                                lowest battery that reports
                                                one ("2 · 40%"); .low at or
                                                under LOW_BATTERY

Click: the Bluetooth panel (bluetooth_panel.py): power, each paired device
with connect / disconnect, Forget, and "Pair new..." (blueman-manager or
GNOME Settings, whichever is installed). With the pill hidden the panel is
still `panel.py toggle bluetooth`.
"""

import json
import sys

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
PROPS = "org.freedesktop.DBus.Properties"
OBJMGR = "org.freedesktop.DBus.ObjectManager"

ICON = ""          # Font Awesome: bluetooth-b (as the audio pill uses)
LOW_BATTERY = 20         # % at or under which the pill turns .low
SAFETY = 300             # s between looks without a signal
DEBOUNCE_MS = 300


# -- pure: what BlueZ says -> what the bar shows -------------------------------
def device_name(props):
    """What a person calls the device: its alias, else its name, else the
    address (an unnamed LE device)."""
    return props.get("Alias") or props.get("Name") or props.get("Address") or "?"


def summarize(objects):
    """GetManagedObjects (unpacked: {path: {interface: {prop: value}}}) ->
    {"adapter": path or None, "powered": bool, "devices": [...]}, devices
    being the paired or connected ones under that adapter, each
    {path, name, address, connected, paired, icon, battery (int or None)},
    connected first, then by name. The first adapter by path is the one
    (hci0 on almost every machine)."""
    adapters = sorted(p for p, ifs in objects.items() if ADAPTER in ifs)
    if not adapters:
        return {"adapter": None, "powered": False, "devices": []}
    adapter = adapters[0]
    devices = []
    for path, ifs in objects.items():
        dev = ifs.get(DEVICE)
        if dev is None or not path.startswith(adapter + "/"):
            continue
        if not (dev.get("Paired") or dev.get("Connected") or dev.get("Bonded")):
            continue
        battery = ifs.get(BATTERY, {}).get("Percentage")
        devices.append({"path": path, "name": device_name(dev), "address": dev.get("Address", ""),
                        "connected": bool(dev.get("Connected")), "paired": bool(dev.get("Paired")),
                        "icon": dev.get("Icon", ""),
                        "battery": int(battery) if battery is not None else None})
    devices.sort(key=lambda d: (not d["connected"], d["name"].lower()))
    return {"adapter": adapter, "powered": bool(objects[adapter][ADAPTER].get("Powered")),
            "devices": devices}


def pill(summary):
    """The module's JSON for a summarize() result (see the module doc)."""
    if not summary.get("adapter"):
        return {"text": "", "class": "absent"}
    devices = summary.get("devices", [])
    if not summary.get("powered"):
        if not devices:
            return {"text": "", "class": "off"}
        return {"text": ICON, "class": "off"}
    connected = [d for d in devices if d["connected"]]
    if not connected:
        return {"text": ICON, "class": "on"}
    batteries = [d["battery"] for d in connected if d["battery"] is not None]
    text = f"{ICON} {len(connected)}"
    cls = ["connected"]
    if batteries:
        low = min(batteries)
        text += f" · {low}%"
        if low <= LOW_BATTERY:
            cls.append("low")
    return {"text": text, "class": cls}


def pair_command(which):
    """The program behind "Pair new...": blueman's manager, else GNOME
    Settings' Bluetooth page, else None. which(name) is shutil.which."""
    if which("blueman-manager"):
        return ["blueman-manager"]
    if which("gnome-control-center"):
        return ["env", "XDG_CURRENT_DESKTOP=GNOME", "gnome-control-center", "bluetooth"]
    return None


# -- D-Bus -------------------------------------------------------------------
def _gio():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    return Gio, GLib


def system_bus():
    Gio, _GLib = _gio()
    try:
        return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except Exception:  # noqa: BLE001 - no system bus: no Bluetooth
        return None


def managed_objects(bus):
    """BlueZ's objects, unpacked; {} when bluetoothd is not there. Never
    starts it (NO_AUTO_START): a pill looking must not wake a daemon the
    owner switched off."""
    if bus is None:
        return {}
    Gio, _GLib = _gio()
    try:
        reply = bus.call_sync(BLUEZ, "/", OBJMGR, "GetManagedObjects", None, None,
                              Gio.DBusCallFlags.NO_AUTO_START, 3000, None)
        return reply.unpack()[0]
    except Exception:  # noqa: BLE001 - not running / not installed
        return {}


def status(bus=None):
    return summarize(managed_objects(bus or system_bus()))


def watch():
    Gio, GLib = _gio()
    bus = system_bus()
    state = {"last": None, "pending": 0}

    def emit():
        state["pending"] = 0
        try:
            line = json.dumps(pill(status(bus)))
        except Exception as exc:  # noqa: BLE001 - outlive one bad read
            line = json.dumps({"text": "", "class": "error", "tooltip": f"bluetooth.py: {exc}"})
        if line != state["last"]:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                loop.quit()
            state["last"] = line
        return False

    def poke(*_args):
        if not state["pending"]:
            state["pending"] = GLib.timeout_add(DEBOUNCE_MS, emit)

    loop = GLib.MainLoop()
    if bus is not None:
        for iface, member in ((PROPS, "PropertiesChanged"), (OBJMGR, "InterfacesAdded"),
                              (OBJMGR, "InterfacesRemoved")):
            bus.signal_subscribe(BLUEZ, iface, member, None, None, Gio.DBusSignalFlags.NONE, poke)
        Gio.bus_watch_name_on_connection(bus, BLUEZ, Gio.BusNameWatcherFlags.NONE,
                                         lambda *_: poke(), lambda *_: poke())
    GLib.timeout_add_seconds(SAFETY, lambda: (poke(), True)[1])
    emit()
    loop.run()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "watch":
        watch()
    elif cmd == "status":
        print(json.dumps(status()))
    else:
        print(json.dumps(pill(status())))


if __name__ == "__main__":
    main()
