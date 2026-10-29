#!/usr/bin/env python3
"""Audio panel — what the volume pill opens.

Two rows, output and microphone, each a mute button, the device's name and a
slider. Everything goes through wpctl against @DEFAULT_AUDIO_SINK@ and
@DEFAULT_AUDIO_SOURCE@, the same targets as the XF86Audio keys in
~/.config/hypr/lua/binds.lua and the pill's right/middle clicks, so all of
them always agree on which device they mean.

Sliders stop at 100%, or at 150% while over-amplification is on (Settings >
Sound, ~/.config/hypr/scripts/sound-settings.py boost). Past 100% PipeWire adds
software gain on top of the device's maximum -- distortion you did not ask for
unless you turned that on -- and the volume keys are capped the same way
(osd.py asks `sound-settings.py limit` for wpctl's -l). The panel asks for the
limit when it opens and again every LIMIT_EVERY_MS (2 s), reading the switch
from sound-settings.py's state file rather than starting it every time; the
volume it sets goes through `wpctl set-volume -l <limit>`, so even a slider
that is out of date cannot go past it. A mark at 100% shows where the gain
begins.

Moving the output slider unmutes it, like the volume-up key does. Dragging a
slider to hear the change and hearing nothing because a mute was left on is
the bug this avoids. The mic slider deliberately does not (see Audio.build).

While it is open the panel follows `pactl subscribe` (PipeWire's pulse
events, the same feed privacy.py's mic watcher uses): a volume key or
another app changing a level, a device plugged in, a new default -- each
is an event, and only then are the rows (and, for a device or default
change, the lists) read again, debounced over EVENT_SETTLE_MS. It used to
run wpctl twice a second and pw-dump every 2 s for as long as it was open,
changed or not. A row the pointer has touched in the last second is left
alone, or the refresh would yank the knob back to the old value mid-drag.
Without pactl it falls back to that old POLL_MS poll.

Under each slider is the list of devices of that kind, one radio-style row
each; the lit one is the current default. Clicking another runs
`wpctl set-default <id>` and the row above follows on its own, because it
only ever talks to @DEFAULT_AUDIO_SINK@ / @DEFAULT_AUDIO_SOURCE@. These are
plain buttons and not a GtkComboBox on purpose: a combo's dropdown is a popup
window, and popups in a keyboard-NONE layer-shell surface open in the wrong
place or not at all. With three devices a side, a flat list is also one click
instead of two.

The list comes from pw-dump, not wpctl status: wpctl status is a tree drawn
for humans (box-drawing characters, "*" for the default, names cut to fit),
pw-dump is JSON with every property. It costs ~20 ms and ~400 KB of JSON, so
the device lists are re-read only on a device or default change (or every
DEVICE_EVERY polls in the fallback poll).

"Mixer" opens pavucontrol for per-app levels and profiles (HDMI vs S/PDIF,
stereo vs surround) — the old left-click on the pill, which this panel replaces.

    audio_panel.py [x,y]   desktop position of the click that opened it
"""

import json
import os
import re
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.expanduser("~/.config/hypr/scripts/notify")  # notify-send with the theme's mascot (mascot_notify.py)
sys.path.insert(0, HERE)
import panelui  # noqa: E402

POLL_MS = 500               # the fallback poll, without pactl
HANDS_OFF = 1.0             # seconds after a user change before polling resumes
DEVICE_EVERY = 4            # fallback poll: re-read the device lists every 4th poll (2 s)
EVENT_SETTLE_MS = 80        # a burst of pulse events -> one refresh
LIMIT_EVERY_MS = 2000       # re-read the over-amplification switch (a file read, no fork)
# `pactl subscribe` lines worth a refresh: "Event 'change' on sink #56". Streams
# (sink-input, source-output) and clients change all the time during playback
# and move nothing on this panel.
EVENT = re.compile(r"Event '(\w+)' on (sink|source|server|card) #")

# Over-amplification (see the docstring): sound-settings.py keeps the switch in
# $XDG_STATE_HOME/hypr/sound.json as {"boost": true}; these are its limits.
SOUND_STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                           "hypr", "sound.json")
NORMAL_LIMIT, BOOST_LIMIT = 1.0, 1.5

# Font Awesome 6 Solid, written as escapes (see network.py on why). These used
# to be the literal glyphs, which look like empty strings in most editors and
# get lost the first time someone retypes the line.
ICON_SPEAKER = "\uf028"
ICON_SPEAKER_MUTED = "\uf6a9"
ICON_MIC = "\uf130"
ICON_MIC_MUTED = "\uf131"


def wpctl(*args):
    try:
        return subprocess.run(["wpctl", *args], capture_output=True, text=True,
                              timeout=2).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def read_volume(target):
    """(percent, muted) or None if the device is gone."""
    match = re.search(r"Volume:\s*([\d.]+)(\s*\[MUTED\])?", wpctl("get-volume", target))
    if not match:
        return None
    return round(float(match.group(1)) * 100), bool(match.group(2))


def read_name(target):
    """Fallback only (see Row.refresh): the nick first, the same short name
    the device list shows, then the long description."""
    out = wpctl("inspect", target)
    match = (re.search(r'node\.nick = "([^"]*)"', out)
             or re.search(r'node\.description = "([^"]*)"', out))
    return match.group(1) if match else "No device"


def volume_limit():
    """1.0, or 1.5 while over-amplification is on -- sound-settings.py's own
    reading of its state file (read_state, limit). A missing or broken file
    is "off", as there."""
    try:
        with open(SOUND_STATE) as handle:
            state = json.load(handle)
        return BOOST_LIMIT if isinstance(state, dict) and state.get("boost") else NORMAL_LIMIT
    except (OSError, ValueError):
        return NORMAL_LIMIT


def pw_dump():
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True,
                             timeout=2).stdout
        return json.loads(out) if out else []
    except (subprocess.SubprocessError, OSError, ValueError):
        return []


def kind_of(name, desc):
    """A few words for how the device is connected, from node.name (stable and
    machine-made: "alsa_output.usb-...analog-stereo-output",
    "alsa_output.pci-...hdmi-stereo") with the description as a fallback.
    The nick alone does not say this, and it is exactly what tells a monitor's
    own speakers (over HDMI) from the desk's USB DAC."""
    text = f"{name} {desc}".lower()
    bus = ("Bluetooth" if name.startswith("bluez") else
           "USB" if ".usb-" in name else "")
    port = ("HDMI" if "hdmi" in text else
            "DisplayPort" if "displayport" in text else
            "S/PDIF" if "iec958" in text else
            "Mono" if "mono" in text else
            "Analog" if "analog" in text else "")
    return " \u00b7 ".join(part for part in (bus, port) if part)


def list_devices(dump=None):
    """{"sink": [...], "source": [...]}, each a list of dicts with id, name
    (the short label), kind, desc and default, in a stable order.

    Monitors are skipped: PipeWire exposes every sink's "what is playing"
    tap as something you can record from, and a microphone list showing
    "Monitor of USB Audio CODEC" next to the real mics is a trap, not a
    choice. They are normally ports of the sink rather than nodes of their
    own, but virtual-sink tools (easyeffects, pw-loopback) do create real
    Audio/Source nodes named *.monitor, hence both checks.

    The short name is node.nick ("USB Audio CODEC", "Acme X22", "HD Webcam
    C525") rather than node.description ("AD102 High Definition Audio
    Controller Digital Stereo (HDMI) [Acme X22]"), which does not fit. Two
    devices with the same nick in one list (two identical USB DACs) fall back
    to the description so they can still be told apart.

    The default comes from the "default" metadata's default.audio.sink/source
    -- what WirePlumber is actually using -- not default.configured.*, which is
    what was last asked for and may name an unplugged device.

    "available" is False for a node whose sound card has nothing plugged into
    that jack. The motherboard's analog input (ALC1220) is the live example:
    PipeWire still lists it as a source, but `wpctl set-default` on it only
    changes default.configured.audio.source -- WirePlumber will not make an
    unplugged device the real default, so the click would appear to do
    nothing. ALSA cards report this per route (Route params on the Device);
    a node maps to its route through card.profile.device == route["device"].
    No active route for the node, or one with available == "no", means
    nothing is connected. "unknown" (USB devices without jack detection,
    S/PDIF) counts as available. A device with no Route params at all
    (non-ALSA) is assumed available."""
    if dump is None:
        dump = pw_dump()
    routes = {}                                 # device id -> Route params
    for obj in dump:
        if obj.get("type") == "PipeWire:Interface:Device":
            params = (obj.get("info") or {}).get("params") or {}
            if "Route" in params:
                routes[obj["id"]] = params["Route"] or []
    defaults = {}
    nodes = {"sink": [], "source": []}
    for obj in dump:
        if (obj.get("type") == "PipeWire:Interface:Metadata"
                and (obj.get("props") or {}).get("metadata.name") == "default"):
            for entry in obj.get("metadata") or []:
                value = entry.get("value")
                if isinstance(value, str):      # older PipeWire: a JSON string
                    try:
                        value = json.loads(value)
                    except ValueError:
                        value = {}
                if isinstance(value, dict) and entry.get("key") in (
                        "default.audio.sink", "default.audio.source"):
                    defaults[entry["key"].rsplit(".", 1)[1]] = value.get("name")
            continue
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = (obj.get("info") or {}).get("props") or {}
        side = {"Audio/Sink": "sink",
                "Audio/Source": "source"}.get(props.get("media.class"))
        name = props.get("node.name", "")
        if not side or name.endswith(".monitor") or props.get("stream.monitor"):
            continue
        desc = props.get("node.description") or name
        available = True
        card = props.get("device.id")
        if card in routes:
            route = next((r for r in routes[card]
                          if r.get("device") == props.get("card.profile.device")),
                         None)
            available = route is not None and route.get("available") != "no"
        nodes[side].append({
            "id": obj["id"],
            "node": name,
            "name": props.get("node.nick") or desc,
            "desc": desc,
            "kind": kind_of(name, desc),
            "available": available,
        })
    for side, devices in nodes.items():
        devices.sort(key=lambda d: (d["name"].lower(), d["id"]))
        names = [d["name"] for d in devices]
        for device in devices:
            if names.count(device["name"]) > 1:
                device["name"] = device["desc"]
            device["default"] = device["node"] == defaults.get(side)
            # "ALC1220 Analog · Analog" says it twice; keep only what the
            # nick does not already say.
            device["kind"] = " \u00b7 ".join(
                part for part in device["kind"].split(" \u00b7 ")
                if part.lower() not in device["name"].lower())
            if not device["available"]:
                device["kind"] = "unplugged"
    return nodes


def fire(*args):
    """Changes are fire-and-forget: a slider emits many values per second and
    waiting on each wpctl would make the knob stutter. A missing wpctl must
    not raise out of a GTK handler (the panel would stay up, dead)."""
    try:
        subprocess.Popen(["wpctl", *args], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        pass


def classify(line):
    """What a `pactl subscribe` line asks of the panel: "devices" (a device
    or the default came or went: lists and rows), "levels" (rows only), or
    None (nothing shown here)."""
    match = EVENT.search(line)
    if not match:
        return None
    what, facility = match.groups()
    if facility in ("server", "card") or what in ("new", "remove"):
        return "devices"
    return "levels"


def _die_with_parent():
    """Runs in the forked pactl before exec: it dies with the panel."""
    import ctypes
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, 15)     # PR_SET_PDEATHSIG, SIGTERM


class DeviceList:
    """The radio-style device rows under a slider. One button per device: a
    dot (lit on the default), the short name, and a dim connection hint.

    The buttons are only rebuilt when the set of devices changes (plug,
    unplug, profile switch). A change of default just moves the "active"
    class, so a poll never destroys the button under the pointer between
    press and release -- which would eat the click."""

    def __init__(self, on_pick):
        self.on_pick = on_pick
        self.signature = None
        self.buttons = {}
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.widget.get_style_context().add_class("dev-list")
        # Panel.show_all() runs after build(); without this it would un-hide a
        # list that update() hid for having a single device.
        self.widget.set_no_show_all(True)

    def update(self, devices):
        signature = tuple((d["id"], d["name"], d["kind"], d["available"])
                          for d in devices)
        if signature != self.signature:
            self.signature = signature
            for child in self.widget.get_children():
                child.destroy()
            self.buttons = {d["id"]: self.make_button(d) for d in devices}
            # One device is not a choice; the name above already says which.
            if len(devices) > 1:
                for child in self.widget.get_children():
                    child.show_all()
                self.widget.show()
            else:
                self.widget.hide()
        for device in devices:
            style = self.buttons[device["id"]].get_style_context()
            (style.add_class if device["default"] else style.remove_class)("active")

    def make_button(self, device):
        button = Gtk.Button()
        button.get_style_context().add_class("dev-pick")
        button.set_relief(Gtk.ReliefStyle.NONE)
        box = Gtk.Box(spacing=8)
        # The dot is drawn by CSS (an empty box with a round border) because
        # Font Awesome Free Solid has a filled circle but no hollow one. A box,
        # not an empty label: a label is always at least a line of text tall,
        # which turns the circle into an oval.
        dot = Gtk.Box()
        dot.get_style_context().add_class("dev-dot")
        dot.set_valign(Gtk.Align.CENTER)
        box.pack_start(dot, False, False, 0)
        name = Gtk.Label(label=device["name"])
        name.get_style_context().add_class("dev-name")
        name.set_xalign(0)
        name.set_ellipsize(3)                   # Pango.EllipsizeMode.END
        name.set_max_width_chars(24)
        box.pack_start(name, True, True, 0)
        if device["kind"]:
            kind = Gtk.Label(label=device["kind"])
            kind.get_style_context().add_class("dev-kind")
            box.pack_end(kind, False, False, 0)
        button.add(box)
        button.connect("clicked", lambda _b: self.on_pick(device))
        # Shown, so the list matches pavucontrol and the jack is a reminder,
        # but not clickable: WirePlumber would ignore the pick (list_devices).
        if not device["available"]:
            button.get_style_context().add_class("unplugged")
            button.set_sensitive(False)
        self.widget.pack_start(button, False, False, 0)
        return button


class Row:
    def __init__(self, title, target, icon_on, icon_off, unmute_on_raise):
        self.target = target
        self.icon_on, self.icon_off = icon_on, icon_off
        self.unmute_on_raise = unmute_on_raise
        self.muted = False
        self.limit = NORMAL_LIMIT
        self.touched = 0.0
        self.updating = False

        self.widget = Gtk.Grid()
        self.widget.get_style_context().add_class("ctl-row")
        self.widget.set_column_spacing(12)

        self.button = Gtk.Button(label=icon_on)
        self.button.get_style_context().add_class("ctl-icon")
        self.button.set_valign(Gtk.Align.CENTER)
        self.button.connect("clicked", self.on_mute)
        self.widget.attach(self.button, 0, 0, 1, 2)

        self.title = Gtk.Label(label=title)
        self.title.get_style_context().add_class("ctl-title")
        self.title.set_xalign(0)
        self.widget.attach(self.title, 1, 0, 1, 1)

        self.device = Gtk.Label(label="")
        self.device.get_style_context().add_class("ctl-sub")
        self.device.set_xalign(1)
        self.device.set_ellipsize(3)            # Pango.EllipsizeMode.END
        self.device.set_max_width_chars(28)
        self.device.set_hexpand(True)
        self.widget.attach(self.device, 2, 0, 2, 1)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.get_style_context().add_class("ctl-slider")
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_size_request(240, -1)
        self.scale.connect("value-changed", self.on_slide)
        self.widget.attach(self.scale, 1, 1, 2, 1)

        self.value = Gtk.Label(label="")
        self.value.get_style_context().add_class("ctl-value")
        self.value.set_width_chars(4)
        self.value.set_xalign(1)
        self.widget.attach(self.value, 3, 1, 1, 1)

        # Under the slider, aligned with the title rather than the mute button.
        # Filled by Audio.refresh_devices; the Row itself never reads pw-dump.
        self.devices = DeviceList(self.on_pick)
        self.widget.attach(self.devices.widget, 1, 2, 3, 1)
        self.on_default_changed = None
        # The lit device's name, set by Audio.refresh_devices. The header shows
        # this rather than asking wpctl: the same string as the lit row below
        # (node.nick, "USB Audio CODEC"), where `wpctl inspect` gave the long
        # description ("PCM2902 Audio Codec Analog Stereo", cut off) and the two
        # did not look like the same device. It also saves a wpctl fork per row
        # on every 500 ms poll.
        self.default_name = None

    def set_limit(self, limit):
        """Stretch the slider to 150% (with a mark at 100%) or back to 100%."""
        if limit == self.limit:
            return
        self.limit = limit
        self.updating = True
        self.scale.set_range(0, round(limit * 100))
        self.scale.clear_marks()
        if limit > NORMAL_LIMIT:
            self.scale.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self.updating = False

    def on_pick(self, device):
        """Synchronous on purpose (wpctl returns in a few ms): reading the new
        default straight after a fire-and-forget would race it and show the
        old device until the next device poll."""
        try:
            subprocess.run(["wpctl", "set-default", str(device["id"])],
                           capture_output=True, timeout=2)
        except (subprocess.SubprocessError, OSError):
            pass
        self.touched = 0.0                      # a new device: no hands-off
        if self.on_default_changed:
            self.on_default_changed(device)

    def refresh(self, force=False):
        if not force and time.monotonic() - self.touched < HANDS_OFF:
            return
        state = read_volume(self.target)
        if state is None:
            self.device.set_text("No device")
        else:
            # A default the list does not show (none lit) still gets a name.
            self.device.set_text(self.default_name or read_name(self.target))
        # Not the whole grid: the device list lives in it too, and a default
        # that just vanished (USB DAC unplugged) is exactly when you need to
        # click another device.
        for part in (self.button, self.scale, self.value):
            part.set_sensitive(state is not None)
        if state is None:
            return
        percent, muted = state
        self.updating = True
        self.scale.set_value(min(percent, round(self.limit * 100)))
        self.updating = False
        self.show(percent, muted)

    def show(self, percent, muted):
        self.muted = muted
        self.button.set_label(self.icon_off if muted else self.icon_on)
        self.value.set_text(f"{percent}%")
        style = self.widget.get_style_context()
        (style.add_class if muted else style.remove_class)("muted")

    def on_slide(self, scale):
        if self.updating:
            return
        self.touched = time.monotonic()
        percent = int(scale.get_value())
        fire("set-volume", "-l", f"{self.limit:.2f}", self.target, f"{percent / 100:.2f}")
        if self.muted and self.unmute_on_raise:
            fire("set-mute", self.target, "0")
            self.show(percent, False)
        else:
            self.show(percent, self.muted)

    def on_mute(self, _button):
        self.touched = time.monotonic()
        fire("set-mute", self.target, "toggle")
        self.show(int(self.scale.get_value()), not self.muted)


class Audio(panelui.Panel):
    def build(self):
        self.rows = [
            Row("Output", "@DEFAULT_AUDIO_SINK@", ICON_SPEAKER, ICON_SPEAKER_MUTED,
                unmute_on_raise=True),
            # The mic is NOT unmuted by moving its slider. Muting a mic is a
            # privacy decision; nudging a level should never quietly undo it.
            Row("Microphone", "@DEFAULT_AUDIO_SOURCE@", ICON_MIC, ICON_MIC_MUTED,
                unmute_on_raise=False),
        ]
        self.sides = ("sink", "source")         # same order as self.rows
        for row in self.rows:
            row.on_default_changed = self.refresh_all
            self.card.pack_start(row.widget, False, False, 0)
        self.ticks = 0
        self.refresh_limit()
        # Devices first: they give each row the name it shows (Row.refresh).
        self.refresh_devices()
        for row in self.rows:
            row.refresh(force=True)

        mixer = Gtk.Button(label="Mixer")
        mixer.get_style_context().add_class("ctl-link")
        mixer.set_halign(Gtk.Align.END)
        mixer.connect("clicked", self.open_mixer)
        self.card.pack_start(mixer, False, False, 0)

    def on_ready(self):
        self.pending = None
        GLib.timeout_add(LIMIT_EVERY_MS, self.tick_limit)
        if not self.subscribe():
            GLib.timeout_add(POLL_MS, self.poll)

    def subscribe(self):
        """Follow `pactl subscribe`; False when it cannot be started."""
        try:
            self.events = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                           preexec_fn=_die_with_parent)
        except OSError:
            return False
        GLib.io_add_watch(self.events.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                          GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                          self.on_events)
        return True

    def on_events(self, fd, condition):
        data = os.read(fd, 65536) if condition & GLib.IOCondition.IN else b""
        if not data:
            # pipewire-pulse went away: back to the poll for the rest of
            # this (short-lived) panel.
            GLib.timeout_add(POLL_MS, self.poll)
            return False
        kinds = {classify(line) for line in data.decode(errors="replace").splitlines()}
        if "devices" in kinds:
            self.pending = "devices"
        elif "levels" in kinds and self.pending is None:
            self.pending = "levels"
        else:
            return True
        GLib.timeout_add(EVENT_SETTLE_MS, self.apply_events)
        return True

    def apply_events(self):
        pending, self.pending = self.pending, None
        if pending == "devices":
            self.refresh_devices()              # first: it names the rows
        if pending:
            for row in self.rows:
                row.refresh()
        return False

    def tick_limit(self):
        self.refresh_limit()
        return True

    def poll(self):
        self.ticks += 1
        if self.ticks % DEVICE_EVERY == 0:
            self.refresh_limit()
            self.refresh_devices()              # first: it names the rows
        for row in self.rows:
            row.refresh()
        return True

    def refresh_limit(self):
        limit = volume_limit()
        for row in self.rows:
            row.set_limit(limit)

    def refresh_devices(self):
        devices = list_devices()
        for side, row in zip(self.sides, self.rows):
            row.devices.update(devices[side])
            row.default_name = next(
                (d["name"] for d in devices[side] if d["default"]), None)
        return devices

    def refresh_all(self, picked):
        """After a click on a device the slider, mute state, name and lit dot
        all change at once. WirePlumber can apply the new default a beat after
        wpctl returns, so look once more shortly after -- and if by then the
        pick still has not taken, say so rather than leave a click that
        silently did nothing (a device that lost its jack between polls)."""
        self.refresh_once()
        GLib.timeout_add(300, self.confirm_pick, picked)

    def refresh_once(self):
        devices = self.refresh_devices()        # first: it names the rows
        for row in self.rows:
            row.refresh(force=True)
        return devices

    def confirm_pick(self, picked):
        devices = self.refresh_once()
        current = [d for side in devices.values() for d in side
                   if d["id"] == picked["id"]]
        if current and not current[0]["default"]:
            try:
                subprocess.Popen(
                    [NOTIFY, "-a", "Audio", "Device not switched",
                     f"WirePlumber kept the old default; {picked['desc']} "
                     "may have nothing plugged in."],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
        return False

    def open_mixer(self, _button):
        try:
            subprocess.Popen(["pavucontrol"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            # Not installed: say so instead of a dead button (and the
            # panel stays put, so the sliders are still there).
            try:
                subprocess.Popen([NOTIFY, "-a", "Audio", "No mixer installed",
                                  "pavucontrol is not installed (sudo dnf install pavucontrol)."],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
            return
        self.quit()


def main():
    panelui.run(Audio)


if __name__ == "__main__":
    main()
