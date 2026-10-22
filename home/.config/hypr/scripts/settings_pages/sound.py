"""Settings page: sound -- outputs, inputs, per-application volume, profiles
(sound-settings.py).

Everything is read from and written through sound-settings.py, which talks
to pactl; WirePlumber remembers the result (default devices, volumes, mutes,
application volumes, profiles), so the page keeps nothing. Its one switch of
its own, over-amplification, lives in sound-settings.py's state file and is
also what the volume keys (osd.py) read. Theme sounds are only shown here:
their switch is on the Notifications page (they are notification chimes),
so there is one place to change them.

Unlike most pages this one keeps itself current while it is on screen: a
volume key, an application starting to play or a headset connecting should
show up without leaving and re-entering the page. Every POLL_MS it re-reads
the status in the background, but only while the page is mapped -- the timer
stops itself the first tick the page is not showing, and refresh() starts it
again. The rows are not rebuilt on every poll: a section is rebuilt only when
the SET of devices / applications in it changes, otherwise each row just
takes the new values. A row the pointer touched in the last HANDS_OFF
seconds is left alone, or a poll would yank the knob back mid-drag (the
audio panel's rule, waybar/scripts/audio_panel.py).

The microphone test is a level meter fed by `sound-settings.py meter`, run
only while the "Test the microphone" link is on (it stops by itself after
METER_S, and when the page is left). The sound is measured, never kept.
"""
import json
import os
import shutil
import subprocess
import threading
import time

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "sound", "title": "Sound", "icon": "", "group": "Hardware", "order": 20,
        "keywords": ["audio", "sonido", "volume", "volumen", "speakers", "headphones", "headset", "output",
                     "input", "microphone", "mic", "app volume", "balance", "mute", "over-amplification",
                     "boost", "louder", "profile", "bluetooth audio", "test microphone"]}

SOUND = os.path.join(HYPR, "sound-settings.py")
SETTINGS = os.path.join(HYPR, "settings.py")
POLL_MS = 1500
HANDS_OFF = 1.5                 # seconds after a touch before a poll may move a row again
SLIDE_MS = 120                  # a slider sends its value once the drag pauses this long
METER_S = 20
BLAND_MEDIA = {"", "(null)", "playback", "audio stream", "audiostream", "output", "simple dsp"}
# Font Awesome 6 Solid, as escapes (see audio_panel.py on why).
ICON_SPEAKER, ICON_SPEAKER_MUTED = "", ""
ICON_MIC, ICON_MIC_MUTED = "", ""
ICON_APP, ICON_HEADPHONES, ICON_BOOST, ICON_BELL = "", "", "", ""


def sound(*args, timeout=10):
    """Run sound-settings.py; its error line (or "") back."""
    try:
        result = subprocess.run([SOUND, *map(str, args)], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return "" if result.returncode == 0 else (result.stderr or result.stdout).strip()


def balance_text(value):
    """-30 -> "L 30", 0 -> "centre", 25 -> "R 25"."""
    return "centre" if value == 0 else f"{'L' if value < 0 else 'R'} {abs(value)}"


class VolumeRow:
    """One device or application: a mute button, the name over a dim line,
    a slider with its percent, and room underneath for extras (port, move
    to). The same ctl-row grid as the audio panel's rows, so it looks the
    same in every theme; .muted dims it, .on lights the icon of the
    default device.

    on_volume(percent) / on_mute() are called by the row; update(...) is how
    the page tells it what the system says now."""

    def __init__(self, icons, on_volume, on_mute):
        self.icons = icons
        self.on_volume, self.on_mute = on_volume, on_mute
        self.touched = 0.0
        self.updating = False
        self.pending = None
        self.muted = False
        self.widget = Gtk.Grid()
        self.widget.get_style_context().add_class("ctl-row")
        self.widget.set_column_spacing(12)
        self.button = Gtk.Button(label=icons[0])
        self.button.get_style_context().add_class("ctl-icon")
        self.button.set_valign(Gtk.Align.CENTER)
        self.button.set_relief(Gtk.ReliefStyle.NONE)
        self.button.connect("clicked", self.clicked_mute)
        self.widget.attach(self.button, 0, 0, 1, 2)
        # Name and dim line share one box over the slider, so a long line
        # ellipsizes instead of widening a grid column -- every slider on the
        # page then ends at the same place.
        top = Gtk.Box(spacing=12)
        self.title = dp.label("", "ctl-title")
        self.title.set_ellipsize(3)             # Pango.EllipsizeMode.END
        self.title.set_max_width_chars(36)
        top.pack_start(self.title, False, False, 0)
        self.sub = dp.label("", "ctl-sub", 1.0)
        self.sub.set_ellipsize(3)
        top.pack_start(self.sub, True, True, 0)
        self.widget.attach(top, 1, 0, 2, 1)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.get_style_context().add_class("ctl-slider")
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.slid)
        self.widget.attach(self.scale, 1, 1, 1, 1)
        self.value = dp.label("", "ctl-value", 1.0)
        self.value.set_width_chars(5)
        self.widget.attach(self.value, 2, 1, 1, 1)
        self.extras = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.widget.attach(self.extras, 1, 2, 2, 1)

    def busy(self):
        return self.pending is not None or time.monotonic() - self.touched < HANDS_OFF

    def update(self, title, sub, volume, muted, cap, lit=False):
        self.title.set_text(title)
        self.title.set_tooltip_text(title)
        self.sub.set_text(sub)
        self.sub.set_tooltip_text(sub)
        style = self.widget.get_style_context()
        (style.add_class if lit else style.remove_class)("on")
        if self.busy():
            return
        self.updating = True
        self.scale.set_range(0, max(cap, volume))
        self.scale.set_value(volume)
        self.updating = False
        self.show(volume, muted)

    def show(self, volume, muted):
        self.muted = muted
        self.button.set_label(self.icons[1] if muted else self.icons[0])
        self.button.set_tooltip_text("Unmute" if muted else "Mute")
        self.value.set_text(f"{volume}%")
        style = self.widget.get_style_context()
        (style.add_class if muted else style.remove_class)("muted")

    def slid(self, scale):
        self.value.set_text(f"{int(scale.get_value())}%")
        if self.updating:
            return
        self.touched = time.monotonic()
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(SLIDE_MS, self.commit)

    def commit(self):
        self.pending = None
        self.touched = time.monotonic()
        self.on_volume(int(self.scale.get_value()))
        return False

    def clicked_mute(self, _button):
        self.touched = time.monotonic()
        self.show(int(self.scale.get_value()), not self.muted)
        self.on_mute()


class BalanceSlider(dp.Slider):
    """The display panel's Slider with "L 30 / centre / R 30" for a value."""

    touched = 0.0

    def show(self, value):
        # Right after a commit a poll may still carry the old value (the
        # change is on its way through pactl): leave the knob where it was let go.
        if time.monotonic() - self.touched >= HANDS_OFF:
            super().show(value)
        self.value.set_text(balance_text(int(self.scale.get_value())))

    def commit(self):
        self.touched = time.monotonic()
        return super().commit()

    def on_slide(self, scale):
        super().on_slide(scale)
        self.value.set_text(balance_text(int(scale.get_value())))


class Section:
    """A box of VolumeRows keyed by device name / stream index, rebuilt only
    when the keys change."""

    def __init__(self):
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.rows = {}
        self.signature = None

    def sync(self, keys, make):
        """make(key) -> VolumeRow for each key; returns {key: row}."""
        signature = tuple(keys)
        if signature != self.signature:
            self.signature = signature
            clear(self.widget)
            self.rows = {key: make(key) for key in keys}
            for key in keys:
                self.widget.pack_start(self.rows[key].widget, False, False, 0)
            self.widget.show_all()
        return self.rows


class Page:
    def __init__(self):
        self.data = None
        self.polling = False
        self.loading = False
        self.meter_proc = None
        self.updating = False
        self.widget = page_box()
        w = self.widget

        w.pack_start(heading("OUTPUT"), False, False, 0)
        w.pack_start(dp.label("Play sound through", "ctl-sub"), False, False, 0)
        self.sink_pick = Chips(lambda name: self.act("default", name))
        w.pack_start(self.sink_pick.widget, False, False, 0)
        self.sinks = Section()
        w.pack_start(self.sinks.widget, False, False, 0)
        self.balance = BalanceSlider("balance", "Balance of the output in use", -100, 100, 1, "", self.set_balance)
        w.pack_start(self.balance.widget, False, False, 0)
        self.ports_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.ports_box.set_no_show_all(True)
        self.ports_box.pack_start(dp.label("Connector", "ctl-sub"), False, False, 0)
        self.ports = Chips(lambda port: self.act("port", self.default("sinks")["name"], port))
        self.ports_box.pack_start(self.ports.widget, False, False, 0)
        w.pack_start(self.ports_box, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("INPUT"), False, False, 0)
        w.pack_start(dp.label("Record from", "ctl-sub"), False, False, 0)
        self.source_pick = Chips(lambda name: self.act("default", name))
        w.pack_start(self.source_pick.widget, False, False, 0)
        self.sources = Section()
        w.pack_start(self.sources.widget, False, False, 0)
        meter_row = Gtk.Box(spacing=12)
        self.meter_link = link("Test the microphone", self.toggle_meter)
        meter_row.pack_start(self.meter_link, False, False, 0)
        self.meter = Gtk.LevelBar.new_for_interval(0, 100)
        self.meter.get_style_context().add_class("dk-bar")
        self.meter.set_mode(Gtk.LevelBarMode.CONTINUOUS)
        # The "low" / "high" offsets GTK adds would colour a quiet room as a
        # warning; the bar is one colour, peaks near the top are .critical.
        for name in ("low", "high", "full"):
            self.meter.remove_offset_value(name)
        self.meter.set_hexpand(True)
        self.meter.set_valign(Gtk.Align.CENTER)
        meter_row.pack_start(self.meter, True, True, 0)
        w.pack_start(meter_row, False, False, 0)
        self.meter_sub = dp.label("Speak: the bar should move well into the middle without touching the end. "
                                  "Nothing is recorded.", "ctl-sub")
        self.meter_sub.set_line_wrap(True)
        w.pack_start(self.meter_sub, False, False, 0)
        self.recording = dp.label("", "ctl-sub")
        self.recording.set_line_wrap(True)
        w.pack_start(self.recording, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("APPLICATIONS"), False, False, 0)
        self.apps_note = dp.label("", "ctl-sub")
        self.apps_note.set_line_wrap(True)
        w.pack_start(self.apps_note, False, False, 0)
        self.apps = Section()
        w.pack_start(self.apps.widget, False, False, 0)

        # Bluetooth gets its own heading when a device is connected; the
        # wired cards' profiles are folded away (rarely touched, and "Off"
        # is one of them).
        self.bt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.bt_box, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("OPTIONS"), False, False, 0)
        self.boost = Gtk.Switch()
        self.boost.connect("state-set", self.toggle_boost)
        grid, self.boost_sub = row(ICON_BOOST, "Over-amplification", "", self.boost)
        w.pack_start(grid, False, False, 0)
        # Shown, not switched: the one switch is on the Notifications page.
        grid, self.sounds_sub = row(ICON_BELL, "Theme sounds", "",
                                    link("Open Notifications", lambda: spawn(SETTINGS, "notifications")))
        w.pack_start(grid, False, False, 0)
        note = dp.label("Timers and alarms always ring, with the theme's own alarm sound when it has one. "
                        "Emergency alerts unmute and raise the output by themselves and ignore Do Not "
                        "Disturb. Both play on the output in use, so pick the device you will hear.",
                        "ctl-sub")
        note.set_line_wrap(True)
        w.pack_start(note, False, False, 0)

        self.cards = Gtk.Expander(label="Sound cards and profiles")
        self.cards.get_style_context().add_class("ctl-sub")
        self.cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.cards.add(self.cards_box)
        w.pack_start(self.cards, False, False, 0)
        self.cards_sig = None

        w.pack_start(sep(), False, False, 0)
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        self.error_from_load = False
        w.pack_start(self.error, False, False, 0)
        foot = dp.label("WirePlumber remembers every change here (devices, volumes, application levels, "
                        "profiles) across reloads and logins. The volume keys change the output in use.",
                        "ctl-sub")
        foot.set_line_wrap(True)
        w.pack_start(foot, False, False, 0)
        links = [link("Full mixer (pavucontrol)", lambda: spawn("pavucontrol"))]
        if shutil.which("blueman-manager"):     # pairing lives there, when it is installed
            links.append(link("Bluetooth devices", lambda: spawn("blueman-manager")))
        w.pack_start(links_row(*links), False, False, 0)
        self.widget.connect("unmap", lambda _w: self.stop_meter())

    # -- reading ------------------------------------------------------------------------
    def refresh(self):
        self.load()
        if not self.polling:
            self.polling = True
            GLib.timeout_add(POLL_MS, self.tick)

    def tick(self):
        if not self.widget.get_mapped():
            self.polling = False
            return False
        self.load()
        return True

    def load(self):
        if self.loading:
            return
        self.loading = True
        background(lambda: run_json(SOUND, "status", "--json"), self.show)

    def default(self, key):
        return next((d for d in (self.data or {}).get(key, []) if d["default"]), None)

    # -- drawing ------------------------------------------------------------------------
    def show(self, data):
        self.loading = False
        if not data:
            self.error.set_text("sound-settings.py did not answer: is PipeWire running? "
                                "(systemctl --user status pipewire-pulse)")
            self.error.show()
            self.error_from_load = True
            return
        # Only the "did not answer" line goes away with a good read: a failed
        # change stays up until the next change works (the redraw right after
        # it would otherwise hide it before it could be read).
        if self.error_from_load:
            self.error.hide()
            self.error_from_load = False
        self.data = data
        cap = round(data["limit"] * 100)
        self.updating = True
        self.show_devices(data["sinks"], self.sink_pick, self.sinks, (ICON_SPEAKER, ICON_SPEAKER_MUTED), cap)
        self.show_devices(data["sources"], self.source_pick, self.sources, (ICON_MIC, ICON_MIC_MUTED), cap)
        out = self.default("sinks")
        stereo = out and any("left" in c for c in out["channels"]) and any("right" in c for c in out["channels"])
        self.balance.widget.set_visible(bool(stereo))
        if stereo:
            self.balance.show(out["balance"])
        ports = [p for p in (out or {}).get("ports", []) if p["available"]]
        if out and len(ports) > 1:
            self.ports.set([(p["name"], p["desc"]) for p in ports], out["port"])
            self.ports_box.show_all()
        else:
            self.ports_box.hide()
        mic = self.default("sources")
        self.meter_link.set_sensitive(bool(mic))
        self.recording.set_text("Using the microphone now: " + ", ".join(data["recording"])
                                if data["recording"] else "No application is using the microphone.")
        self.show_apps(data["apps"], data["sinks"], cap)
        self.show_cards(data["cards"])
        self.boost.set_state(data["boost"])
        self.boost_sub.set_text(
            "On: sliders and volume keys go up to 150 %, software gain on top of the device's maximum. "
            "Loud sound past 100 % distorts. Off brings anything above 100 % back down."
            if data["boost"] else "Let volumes go past 100 % (up to 150 %) for quiet recordings or weak "
            "speakers. Off: sliders and volume keys stop at 100 %.")
        self.sounds_sub.set_text(("On" if data["theme_sounds"] != "off" else "Off")
                                 + ": the desktop theme's notification and theme-switch sounds (silent for "
                                 "low urgency and during Do Not Disturb). Switched on the Notifications page.")
        self.updating = False

    def show_devices(self, devices, pick, section, icons, cap):
        pick.set([(d["name"], d["label"]) for d in devices],
                 next((d["name"] for d in devices if d["default"]), None))
        for d in devices:                   # WirePlumber would ignore the pick (audio_panel.list_devices)
            pick.buttons[d["name"]].set_sensitive(d["available"])
            pick.buttons[d["name"]].set_tooltip_text(d["desc"])
        rows = section.sync([d["name"] for d in devices], lambda name: VolumeRow(
            icons, lambda v, n=name: self.act("volume", n, v), lambda n=name: self.act("mute", n, "toggle")))
        for d in devices:
            parts = [d["kind"]] if d["kind"] else []
            if d["default"]:
                parts.append("in use")
            if d["balance"]:
                parts.append(f"balance {balance_text(d['balance'])}")
            rows[d["name"]].update(d["label"], "  ·  ".join(parts), d["volume"], d["mute"], cap, d["default"])
        if not devices:
            clear(section.widget)
            section.signature = None
            section.widget.pack_start(dp.label("None found.", "ctl-sub"), False, False, 0)
            section.widget.show_all()

    def show_apps(self, apps, sinks, cap):
        self.apps_note.set_text("Nothing is playing right now. Applications show up here while they play, "
                                "each with its own volume and output." if not apps else
                                "Each application's own level, on top of the output's. WirePlumber "
                                "remembers it for the next time that application plays.")
        # Keyed by the sink and the outputs offered too, so moving a stream or
        # an output coming / going rebuilds its "Play on" chips.
        offered = tuple(s["name"] for s in sinks if s["available"])
        rows = self.apps.sync([(a["index"], a["sink"], offered) for a in apps],
                              lambda key: self.make_app_row(key, sinks))
        for a in apps:
            # media.name is often a placeholder ("(null)", "playback"); only a
            # real title says something the name does not.
            media = "" if a["media"].lower() in BLAND_MEDIA or a["media"] == a["name"] else a["media"][:60]
            sub = "  ·  ".join(p for p in (media,
                                           "paused" if a["paused"] else "",
                                           f"on {a['sink_label']}" if len(sinks) > 1 else "") if p)
            rows[(a["index"], a["sink"], offered)].update(a["name"], sub, a["volume"], a["mute"], cap)

    def make_app_row(self, key, sinks):
        index, current, _offered = key
        r = VolumeRow((ICON_APP, ICON_SPEAKER_MUTED), lambda v: self.act("app", "volume", index, v),
                      lambda: self.act("app", "mute", index, "toggle"))
        if len(sinks) > 1:
            chips = Chips(lambda name: self.act("app", "move", index, name))
            chips.set([(s["name"], s["label"]) for s in sinks if s["available"]], current)
            r.extras.pack_start(chips.widget, False, False, 0)
        return r

    def show_cards(self, cards):
        signature = json.dumps(cards, sort_keys=True)
        if signature == self.cards_sig:
            return
        self.cards_sig = signature
        clear(self.bt_box)
        clear(self.cards_box)
        bt = [c for c in cards if c["bluetooth"]]
        if bt:
            self.bt_box.pack_start(sep(), False, False, 0)
            self.bt_box.pack_start(heading("BLUETOOTH AUDIO"), False, False, 0)
            note = dp.label("High quality (A2DP) is for listening and has no microphone. Headset (HFP) "
                            "turns the microphone on, at phone-call quality for both directions.", "ctl-sub")
            note.set_line_wrap(True)
            self.bt_box.pack_start(note, False, False, 0)
        for card in cards:
            box = self.bt_box if card["bluetooth"] else self.cards_box
            active = next((p["label"] for p in card["profiles"] if p["name"] == card["active"]), card["active"])
            grid, _ = row(ICON_HEADPHONES if card["bluetooth"] else "", card["label"], f"now: {active}")
            box.pack_start(grid, False, False, 0)
            profiles = [p for p in card["profiles"] if p["available"] or p["name"] == card["active"]]
            # "Off" last: it is a choice, not the one you want next to the others.
            profiles.sort(key=lambda p: (p["name"] == "off", -p["priority"]))
            chips = Chips(lambda name, c=card["name"]: self.act("profile", c, name))
            chips.set([(p["name"], p["label"]) for p in profiles], card["active"])
            box.pack_start(chips.widget, False, False, 0)
        if not cards:
            self.cards_box.pack_start(dp.label("No sound cards found.", "ctl-sub"), False, False, 0)
        self.bt_box.show_all()
        self.cards_box.show_all()

    # -- changing -----------------------------------------------------------------------
    def act(self, *args):
        """Run one sound-settings.py command off the GTK thread, then redraw
        from what PipeWire now says. A failure is shown under the page."""
        if self.updating:
            return

        def done(err):
            if err:
                self.error.set_text(f"Could not do that: {err.splitlines()[-1][:160]}")
                self.error.show()
                self.error_from_load = False
            elif not self.error_from_load:
                self.error.hide()
            self.load()
        background(lambda: sound(*args), done)

    def set_balance(self, _key, value):
        out = self.default("sinks")
        if out and not self.updating:
            self.act("balance", out["name"], value)

    def toggle_boost(self, _switch, state):
        if not self.updating:
            self.act("boost", "on" if state else "off")
        return False

    # -- the microphone test ------------------------------------------------------------
    def toggle_meter(self):
        if self.meter_proc:
            self.stop_meter()
            return
        mic = self.default("sources")
        if not mic:
            return
        try:
            proc = subprocess.Popen([SOUND, "meter", mic["name"], str(METER_S)], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True)
        except OSError as exc:
            self.meter_sub.set_text(f"Could not start the meter: {exc}")
            return
        self.meter_proc = proc
        self.meter_link.set_label("Stop the test")
        self.meter_sub.set_text(f"Listening to {mic['label']} for {METER_S} s. Speak: the bar should move "
                                "well into the middle without touching the end. Nothing is recorded.")

        def read():
            for line in proc.stdout:
                try:
                    level = int(line)
                except ValueError:
                    continue
                GLib.idle_add(self.show_level, proc, level)
            GLib.idle_add(self.meter_ended, proc)
        threading.Thread(target=read, daemon=True).start()

    def show_level(self, proc, level):
        if proc is self.meter_proc:
            self.meter.set_value(level)
            style = self.meter.get_style_context()
            (style.add_class if level >= 95 else style.remove_class)("critical")
        return False

    def meter_ended(self, proc):
        if proc is self.meter_proc:
            self.meter_proc = None
            self.meter.set_value(0)
            self.meter_link.set_label("Test the microphone")
        return False

    def stop_meter(self):
        proc, self.meter_proc = self.meter_proc, None
        if proc:
            proc.terminate()
        self.meter.set_value(0)
        self.meter_link.set_label("Test the microphone")
