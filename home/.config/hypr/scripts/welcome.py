#!/usr/bin/env python3
"""Welcome: the one-time card on the first login after install -- pick a
theme, check the screens and the microphone, turn the smart features on or
off (and see whether they will find a local model), and learn the two keys
that find everything else. Settings has all of it afterwards; this only
puts the first five minutes in one place.

    welcome.py                  show it now (any time; the launcher's
                                "Welcome" runs this)
    welcome.py --first-login    what welcome.service runs: show it only when
                                the done-marker is missing, after a short wait
                                for the bar and the wallpaper
    welcome.py --done           write the done-marker (no window)
    welcome.py --reset          remove it: the next login shows the card again
    welcome.py --status         "done" or "pending"
    welcome.py --render OUT.png [seconds]
                                draw the card offscreen into a PNG (checking
                                it without putting anything on the screens)

The done-marker is $XDG_STATE_HOME/hypr/welcome-done (~/.local/state/hypr/
welcome-done). welcome.service (graphical-session.target, a oneshot-like
simple service) has ConditionPathExists=!%h/.local/state/hypr/welcome-done,
so once the marker is there systemd does not even start Python. "Don't show
this again" (on by default) writes it when the card closes; with it off the
card comes back at the next login.

THE CARD -- the panels' look (waybar/panel.css through panelui.load_css,
the classes settings_pages/common.py documents), a layer-shell surface in
the middle of the screen (no window rule needed; without gtk-layer-shell a
plain window), keyboard on demand, Esc closes it:

    THEME        a chip per theme (theme.py list), the current one lit; a
                 click runs `theme.py set NAME` and restyles the card too
    SCREENS      each screen at its mode, and a hint where it runs below the
                 fastest refresh rate it offers at that size (screen_lines);
                 "Open Screens" opens Settings on that page
    MICROPHONE   the default input's live level for 10 s (sound-settings.py
                 meter: nothing is recorded); "Open Sound"
    SMART        one switch for the everyday smart features (SMART_SET: the
                 assistant, live suggestions, the smart clipboard, the
                 learning window layout, session autosave, the nightly health
                 check -- never the camera, the screen or the microphone ones,
                 which stay off until turned on in Settings > Smart desktop);
                 the same commands that page's switches run (_smart.py).
                 Under it: whether LM Studio is installed and running, and
                 what fits this machine (model_advice: the graphics card's
                 memory from gpu.py, any vendor -- or the RAM when there is
                 no card). Without LM Studio the assistant, voice commands,
                 asking about the screen and the summaries do not answer;
                 everything else works.
    KEYS         SUPER+F1 lists every shortcut ("Show them" opens it),
                 SUPER+I is Settings, SUPER+CTRL+I the smart features.

Opening Settings (Screens, Sound, Smart desktop) moves the card under the
windows (the layer's BOTTOM), so the page is not hidden behind it; a click
on the card brings it back on top.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
MARKER = os.path.join(STATE_DIR, "welcome-done")
SETTINGS = os.path.join(HERE, "settings.py")
THEME = os.path.join(HERE, "theme.py")
SOUND = os.path.join(HERE, "sound-settings.py")
PANEL = os.path.expanduser("~/.config/waybar/scripts/panel.py")
APP_ID = "desktop.welcome"
METER_S = 10
FIRST_LOGIN_DELAY = 6       # s: let the bar, the wallpaper and mako come up first
# The everyday smart features the one switch turns on / off (ids in
# settings_pages/_smart.py FEATURES). Nothing that uses the camera, the
# microphone or the screen: those are opt-in, one by one.
SMART_SET = ("assistant", "suggestions", "smartclip", "layout", "sessions", "health")
NEEDS_MODEL = "the assistant, voice commands, asking about the screen and the summaries"

ICON_THEME, ICON_SCREEN, ICON_MIC, ICON_SMART, ICON_KEYS = "", "", "", "", ""


# -- the marker ------------------------------------------------------------------------------
def is_done():
    return os.path.exists(MARKER)


def mark_done():
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(MARKER, "w") as handle:
        handle.write(time.strftime("%Y-%m-%d %H:%M:%S\n"))


def reset():
    try:
        os.remove(MARKER)
    except FileNotFoundError:
        pass


# -- pure helpers (tests/test_welcome.py) ----------------------------------------------------
def _mode(text):
    """"3440x1440@180.00Hz" -> (3440, 1440, 180.0), None when it is not a mode."""
    try:
        size, rate = text.lower().removesuffix("hz").split("@")
        w, h = size.split("x")
        return int(w), int(h), float(rate)
    except ValueError:
        return None


def screen_lines(monitors):
    """hyprctl monitors -j -> [(name, line, hint)]: "3440x1440 at 144 Hz",
    and a hint when the same size offers a faster refresh rate (more than
    1 Hz faster: 59.94 vs 60 is not worth a word)."""
    out = []
    for m in monitors or []:
        if m.get("disabled"):
            continue
        w, h, rate = m.get("width", 0), m.get("height", 0), float(m.get("refreshRate") or 0)
        line = f"{w}x{h} at {rate:.0f} Hz"
        if m.get("scale") and abs(float(m["scale"]) - 1.0) > 0.01:
            line += f", scale {float(m['scale']):g}"
        best = max((r for mw, mh, r in filter(None, map(_mode, m.get("availableModes") or []))
                    if (mw, mh) == (w, h)), default=0.0)
        hint = f"can run at {best:.0f} Hz" if best > rate + 1 else ""
        out.append((m.get("name") or "?", line, hint))
    return out


def model_advice(card, ram_bytes):
    """One line on what local models suit this machine: the graphics card's
    own memory (any vendor) less ~2 GB for the desktop, else the RAM (an
    iGPU's carve-out is RAM too: discrete False)."""
    if card and card.get("discrete", True) and card.get("vram_total"):
        gb = card["vram_total"] / 1024
        room = max(gb - 2, 0)
        if room >= 4:
            return (f"{card['name']} has {gb:.0f} GB: models up to about {room:.0f} GB "
                    "run on the card (Settings > AI & models shows what fits).")
        return (f"{card['name']} has {gb:.0f} GB: small models (2-3 GB) fit on the card; "
                "bigger ones spill into RAM and answer slowly.")
    ram_gb = (ram_bytes or 0) / 2 ** 30
    return (f"No graphics card memory of its own: models run on the CPU and RAM ({ram_gb:.0f} GB), "
            "slowly -- pick small ones (2-4 GB), or leave the smart features off.")


def smart_summary(states):
    """{feature id: on (True/False/None)} -> (switch on?, "3 of 6 on")."""
    known = [v for v in states.values() if v is not None]
    n_on = sum(1 for v in known if v)
    return n_on * 2 >= len(SMART_SET) and n_on > 0, f"{n_on} of {len(SMART_SET)} on"


def lmstudio():
    """{"installed", "running"} without waking LM Studio (llm_models)."""
    try:
        sys.path.insert(0, HERE)
        import llm_models
        installed = os.path.exists(llm_models.LMS) or bool(shutil.which("lms"))
        running = bool(llm_models._daemon_running())
    except Exception:  # noqa: BLE001
        installed, running = bool(shutil.which("lms")), False
    return {"installed": installed, "running": running}


def ram_bytes():
    try:
        with open("/proc/meminfo") as handle:
            return int(handle.readline().split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 0


def main_card():
    try:
        sys.path.insert(0, HERE)
        import gpu
        return gpu.primary()
    except Exception:  # noqa: BLE001
        return None


def run(*argv, timeout=20):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def spawn(*argv):
    subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -- the card --------------------------------------------------------------------------------
def build(offscreen=False):
    """The window (GTK imported only here, so --done / --status and the tests
    need no display)."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    try:
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell
    except (ValueError, ImportError):
        GtkLayerShell = None
    sys.path.insert(0, HERE)
    from settings_pages import common   # noqa: E402  (also puts waybar/scripts on the path)
    import display_panel as dp          # noqa: E402
    import panelui                      # noqa: E402

    panelui.load_css()

    class Welcome(Gtk.Window if not offscreen else Gtk.OffscreenWindow):
        def __init__(self):
            super().__init__() if offscreen else super().__init__(title="Welcome")
            self.set_name("panel-window")
            self.meter_proc = None
            self.smart_busy = False
            self.layered = False
            if not offscreen:
                self.set_default_size(760, -1)
                self.connect("key-press-event", self.on_key)
                self.connect("destroy", self.on_destroy)
                self.connect("button-press-event", lambda *_: self.to_top())
                if GtkLayerShell is not None and GtkLayerShell.is_supported():
                    GtkLayerShell.init_for_window(self)
                    GtkLayerShell.set_namespace(self, "welcome")
                    GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
                    GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
                    GtkLayerShell.set_exclusive_zone(self, 0)
                    self.layered = True

            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.set_name("panel")
            outer.set_size_request(760, -1)
            # Fade in rather than pop: the card arrives just after login.
            self.reveal = Gtk.Revealer()
            self.reveal.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
            self.reveal.set_transition_duration(260)
            outer.pack_start(self.reveal, True, True, 0)
            body = common.page_box()
            body.set_margin_top(10)
            body.set_margin_bottom(10)
            # As tall as it needs, up to 90 % of the screen (a 768-line
            # laptop): beyond that it scrolls.
            self.body = body
            self.max_height = screen_height(Gdk) * 9 // 10
            self.scroll = Gtk.ScrolledWindow()
            self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.scroll.add(body)
            self.reveal.add(self.scroll)
            self.add(outer)

            title = dp.label("Welcome", "kb-heading")
            title.set_name("kb-title")
            body.pack_start(title, False, False, 0)
            intro = dp.label("A few things to set up now. All of it is in Settings (SUPER+I) "
                             "whenever you want it later.", "ctl-sub")
            intro.set_line_wrap(True)
            body.pack_start(intro, False, False, 0)

            # THEME
            body.pack_start(common.sep(), False, False, 0)
            body.pack_start(common.heading("THEME"), False, False, 0)
            self.themes = dp.Chips(self.pick_theme)
            body.pack_start(self.themes.widget, False, False, 0)
            self.theme_sub = dp.label("", "ctl-sub")
            body.pack_start(self.theme_sub, False, False, 0)

            # SCREENS
            body.pack_start(common.sep(), False, False, 0)
            body.pack_start(common.heading("SCREENS"), False, False, 0)
            self.screens_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            body.pack_start(self.screens_box, False, False, 0)
            body.pack_start(common.links_row(common.link("Open Screens", lambda: self.open_settings("screens"))),
                            False, False, 0)

            # MICROPHONE
            body.pack_start(common.sep(), False, False, 0)
            body.pack_start(common.heading("MICROPHONE"), False, False, 0)
            meter_row = Gtk.Box(spacing=12)
            self.meter_link = common.link("Test the microphone", self.toggle_meter)
            meter_row.pack_start(self.meter_link, False, False, 0)
            self.meter = Gtk.LevelBar.new_for_interval(0, 100)
            self.meter.get_style_context().add_class("dk-bar")
            self.meter.set_mode(Gtk.LevelBarMode.CONTINUOUS)
            for name in ("low", "high", "full"):
                self.meter.remove_offset_value(name)
            self.meter.set_hexpand(True)
            self.meter.set_valign(Gtk.Align.CENTER)
            meter_row.pack_start(self.meter, True, True, 0)
            meter_row.pack_start(common.link("Open Sound", lambda: self.open_settings("sound")), False, False, 0)
            body.pack_start(meter_row, False, False, 0)
            self.mic_sub = dp.label("Speak: the bar should reach the middle, not the end. Nothing is recorded.",
                                    "ctl-sub")
            self.mic_sub.set_line_wrap(True)
            body.pack_start(self.mic_sub, False, False, 0)

            # SMART
            body.pack_start(common.sep(), False, False, 0)
            body.pack_start(common.heading("SMART FEATURES"), False, False, 0)
            self.smart = Gtk.Switch()
            self.smart.set_sensitive(False)
            self.smart.connect("state-set", self.toggle_smart)
            grid, self.smart_sub = common.row(ICON_SMART, "Everyday smart features",
                                              "reading them...", self.smart)
            body.pack_start(grid, False, False, 0)
            self.model_sub = dp.label("", "ctl-sub")
            self.model_sub.set_line_wrap(True)
            self.model_sub.set_max_width_chars(80)
            body.pack_start(self.model_sub, False, False, 0)
            body.pack_start(common.links_row(
                common.link("Choose one by one", lambda: self.open_settings("intelligence")),
                common.link("AI & models", lambda: self.open_settings("ai"))), False, False, 0)

            # KEYS
            body.pack_start(common.sep(), False, False, 0)
            grid, _sub = common.row(ICON_KEYS, "SUPER+F1 lists every shortcut",
                                    "SUPER+I opens Settings, SUPER+CTRL+I the smart features, "
                                    "SUPER+E the launcher.",
                                    common.link("Show them", lambda: spawn(PANEL, "toggle", "keybinds")))
            body.pack_start(grid, False, False, 0)

            # the end
            body.pack_start(common.sep(), False, False, 0)
            end = Gtk.Box(spacing=12)
            self.again = Gtk.CheckButton(label="Don't show this again")
            self.again.set_active(True)
            self.again.get_style_context().add_class("ctl-sub")
            end.pack_start(self.again, False, False, 0)
            done = Gtk.Button(label="Done")
            done.get_style_context().add_class("dev-pick")
            done.get_style_context().add_class("chip")
            done.connect("clicked", lambda _b: self.close())
            end.pack_end(done, False, False, 0)
            body.pack_start(end, False, False, 0)

            self.refresh()

        # -- reading --------------------------------------------------------------------
        def refresh(self):
            def work():
                try:
                    sys.path.insert(0, HERE)
                    import theme as themes_mod
                    themes = [{"name": n, "label": label} for n, label in themes_mod.themes()]
                    current = themes_mod.current()
                except Exception:  # noqa: BLE001
                    themes, current = [], None
                try:
                    monitors = json.loads(run("hyprctl", "monitors", "-j") or "[]")
                except ValueError:
                    monitors = []
                return themes, current, monitors
            common.background(work, self.show_basics)
            common.background(self.read_smart, self.show_smart)

        def show_basics(self, result):
            themes, current, monitors = result
            self.themes.set([(t["name"], dp.theme_caption(t)) for t in themes], current)
            self.theme_sub.set_text("" if themes else "theme.py did not answer")
            common.clear(self.screens_box)
            lines = screen_lines(monitors)
            for name, line, hint in lines:
                grid, _sub = common.row(ICON_SCREEN, name, line + (f" -- {hint}" if hint else ""))
                self.screens_box.pack_start(grid, False, False, 0)
            if not lines:
                self.screens_box.pack_start(dp.label("No screens reported (hyprctl did not answer).",
                                                     "ctl-sub"), False, False, 0)
            self.screens_box.show_all()
            self.fit()
            self.reveal.set_reveal_child(True)

        def fit(self):
            """The scroller as tall as the card's content, at most max_height."""
            width = max(self.scroll.get_allocated_width(), 740)
            natural = self.body.get_preferred_height_for_width(width)[1]
            self.scroll.set_min_content_height(min(natural, self.max_height))

        @staticmethod
        def read_smart():
            states = {}
            try:
                from settings_pages import _smart
                p = _smart.gather(_smart.probes_of(SMART_SET))
                for fid in SMART_SET:
                    states[fid] = _smart.feature_state(_smart.BY_ID[fid], p).get("on")
            except Exception:  # noqa: BLE001
                states = dict.fromkeys(SMART_SET)
            return states, lmstudio(), main_card(), ram_bytes()

        def show_smart(self, result):
            states, lms, card, ram = result
            on, text = smart_summary(states)
            self.smart_busy = True
            self.smart.set_active(on)
            self.smart.set_state(on)
            self.smart_busy = False
            self.smart.set_sensitive(True)
            self.smart_sub.set_text(f"{text}. The camera, microphone and screen ones stay off.")
            if lms["running"]:
                where = "LM Studio is running."
            elif lms["installed"]:
                where = "LM Studio is installed (it starts when a feature asks)."
            else:
                where = (f"LM Studio is not installed (lmstudio.ai): {NEEDS_MODEL} need it; "
                         "everything else works without it.")
            self.model_sub.set_text(f"{where} {model_advice(card, ram)}")
            self.fit()

        # -- actions ----------------------------------------------------------------------
        def pick_theme(self, name):
            self.theme_sub.set_text(f"Switching to {name}...")

            def done(_out):
                panelui.load_css()
                self.refresh()
            common.background(lambda: run(THEME, "set", name, timeout=60), done)

        def toggle_smart(self, _switch, value):
            if self.smart_busy:
                return False
            self.smart.set_sensitive(False)
            self.smart_sub.set_text("turning them " + ("on..." if value else "off..."))

            def work():
                from settings_pages import _smart
                errors = []
                for fid in SMART_SET:
                    said = _smart.execute(_smart.switch_commands(fid, value))
                    if said:
                        errors.append(said)
                return errors

            def done(errors):
                self.smart.set_state(value)
                common.background(self.read_smart, self.show_smart)
                if errors:
                    self.smart_sub.set_text("Some did not switch: " + errors[0])
            common.background(work, done)
            return True

        def toggle_meter(self):
            if self.meter_proc:
                self.stop_meter()
                return
            try:
                status = json.loads(run(SOUND, "status", "--json") or "{}")
            except ValueError:
                status = {}
            mic = next((s for s in status.get("sources") or [] if s.get("default")), None)
            if not mic:
                self.mic_sub.set_text("No microphone found. Plug one in, or pick it in Settings > Sound.")
                return
            try:
                proc = subprocess.Popen([SOUND, "meter", mic["name"], str(METER_S)], stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)
            except OSError as exc:
                self.mic_sub.set_text(f"Could not start the meter: {exc}")
                return
            self.meter_proc = proc
            self.meter_link.set_label("Stop the test")
            self.mic_sub.set_text(f"Listening to {mic.get('label') or mic['name']} for {METER_S} s. "
                                  "Speak; nothing is recorded.")
            peak = [0]

            def read():
                for line in proc.stdout:
                    try:
                        level = int(line)
                    except ValueError:
                        continue
                    peak[0] = max(peak[0], level)
                    GLib.idle_add(self.show_level, proc, level)
                GLib.idle_add(self.meter_ended, proc, peak[0])
            threading.Thread(target=read, daemon=True).start()

        def show_level(self, proc, level):
            if proc is self.meter_proc:
                self.meter.set_value(level)
                style = self.meter.get_style_context()
                (style.add_class if level >= 95 else style.remove_class)("critical")
            return False

        def meter_ended(self, proc, peak):
            if proc is self.meter_proc:
                self.meter_proc = None
                self.meter.set_value(0)
                self.meter_link.set_label("Test the microphone")
                self.mic_sub.set_text(mic_verdict(peak))
            return False

        def stop_meter(self):
            proc, self.meter_proc = self.meter_proc, None
            if proc:
                proc.terminate()
            self.meter.set_value(0)
            self.meter_link.set_label("Test the microphone")

        def open_settings(self, page):
            spawn(SETTINGS, page)
            self.to_bottom()

        def to_bottom(self):
            if self.layered:
                GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
                GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        def to_top(self):
            if self.layered:
                GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
                GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
            return False

        def on_key(self, _w, event):
            if event.keyval == Gdk.KEY_Escape:
                self.close()
                return True
            return False

        def on_destroy(self, *_):
            self.stop_meter()
            if self.again.get_active():
                mark_done()
            Gtk.main_quit()

    return Welcome(), Gtk, GLib


def screen_height(Gdk):
    """The logical height of the screen the card opens on (the focused or
    primary one), 1080 when GDK cannot say."""
    try:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_workarea().height or 1080
    except Exception:  # noqa: BLE001
        return 1080


def mic_verdict(peak):
    """The line after a 10 s test, from its loudest moment (0-100)."""
    if peak <= 5:
        return "Nothing came through: is it muted, or is another input the default? (Open Sound)"
    if peak >= 95:
        return "It reached the end: too loud, it may clip. Lower the input volume in Settings > Sound."
    if peak < 35:
        return "Quiet: it works, but raise the input volume if people say you are hard to hear."
    return "Sounds right."


def show():
    win, Gtk, _GLib = build()
    win.show_all()
    win.present()
    Gtk.main()


def render(out, seconds=3.0):
    win, Gtk, GLib = build(offscreen=True)
    win.show_all()
    end = GLib.get_monotonic_time() + int(seconds * 1e6)
    while GLib.get_monotonic_time() < end:
        Gtk.main_iteration_do(False)
        if not Gtk.events_pending():
            GLib.usleep(20000)
    win.get_pixbuf().savev(out, "png", [], [])
    print(out)


def main(argv):
    if argv[:1] == ["--done"]:
        mark_done()
        return 0
    if argv[:1] == ["--reset"]:
        reset()
        return 0
    if argv[:1] == ["--status"]:
        print("done" if is_done() else "pending")
        return 0
    if argv[:1] == ["--render"] and len(argv) >= 2:
        render(argv[1], float(argv[2]) if len(argv) > 2 else 3.0)
        return 0
    if argv[:1] == ["--first-login"]:
        if is_done():
            return 0
        time.sleep(FIRST_LOGIN_DELAY)
        show()
        return 0
    if argv:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    show()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
