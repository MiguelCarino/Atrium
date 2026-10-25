"""Settings page: the ambient desktop -- the look and the sound following the
time of day, the weather and focus blocks (ambient.py; its docstring has
what each output does and what it never does).

    STATUS        the master switch (ambient.service), the mood now and why,
                  what it is doing about it; a preview of any mood (a dry
                  run: nothing changes)
    LOOK          the wallpaper veil, the accent's warmth, the night light's
                  strength, calmer animations (when, how calm); how strong
    THEME         "theme follows ambience" (off as shipped) and a theme for
                  focus blocks
    SOUND         the notification sound's volume in focus / at night; the
                  soundscape (rain, cafe, brown noise, vinyl, the weather's or the
                  theme's), when, how loud
    SMART LIGHTS  off / Philips Hue / Home Assistant: finding them on the
                  network, pairing (Hue's button) or the address + token (Home
                  Assistant), the brightness per mood, lights off when away,
                  a dry-run try
    MORE          what counts as focus / away

Nothing is kept here: every control runs ambient.py (set, soundscape,
lights ...) and the page redraws from `ambient.py status --json`. The Home
Assistant token goes to ambient.py on stdin, never on a command line, and
the page never shows it back (only "saved").
"""
from .common import *  # noqa: F401,F403  (the shared helpers and paths; Gtk 3)

from gi.repository import GLib, Gtk  # noqa: E402,F401

import os  # noqa: E402

PAGE = {"id": "ambient", "title": "Ambient", "icon": "\uf185", "group": "Look", "order": 20, "parent": "theme", "tab": "Ambient",
        "keywords": ["ambience", "ambiente", "mood", "weather", "time of day", "soundscape", "rain sound",
                     "brown noise", "white noise", "cafe", "vinyl", "crackle", "focus music", "smart lights", "philips hue", "hue",
                     "home assistant", "luces", "lights", "scene", "warm", "calm animations",
                     "notification volume", "wallpaper dim", "tint"]}

AMBIENT = os.path.join(HYPR, "ambient.py")
SETTINGS = os.path.join(HYPR, "settings.py")

LOOK = [
    ("wallpaper", "\uf03e", "Veil the wallpaper",
     "warm in the evening, darker at night and in focus, grey on grey days"),
    ("accent", "\uf53f", "Warm the accent",
     "amber at night, bluer in a focus block"),
    ("nightlight", "\uf186", "Night light strength",
     "warmer late at night, cooler in a focus block"),
    ("animations", "\uf1ce", "Calmer animations", "slower, gentler moves, then back to your preset"),
]
SOUND = [
    ("notify", "\uf0f3", "Quieter notification sounds", "in a focus block and at night"),
    ("soundscape", "\uf001", "Soundscape", "rain, a cafe, brown noise or vinyl, played softly"),
]
MORE = [
    ("dnd_focus", "\uf140", "Do Not Disturb counts as focus", "not only a focus block"),
    ("away_lock", "\uf023", "A locked screen counts as away", "as well as Presence"),
]
MOOD_NAMES = {"day": "Day", "relax": "Evening", "focus": "Focus", "night": "Night", "away": "Away"}
STRENGTH = [("subtle", "Subtle"), ("medium", "Noticeable")]
ANIM_WHEN = [("focus", "In focus blocks"), ("night", "At night"), ("both", "Both")]
ANIM_STYLE = [("gentle", "Gentle"), ("still", "Fades only")]
KINDS = [("rain", "Rain"), ("cafe", "Cafe"), ("brown", "Brown noise"), ("vinyl", "Vinyl & rain"),
         ("weather", "Like the weather"), ("theme", "The theme's")]
SOUND_WHEN = [("focus", "Focus blocks"), ("relax", "Focus blocks and evenings")]
MUSIC = [("pause", "Quiet while music plays"), ("keep", "Even with music")]
PROVIDERS = [("off", "Off"), ("hue", "Philips Hue"), ("ha", "Home Assistant")]


# -- pure helpers (tests/test_ambient.py) ------------------------------------------------
def status_text(data):
    """The line under the master switch."""
    s, plan = data.get("settings") or {}, data.get("plan") or {}
    mood = MOOD_NAMES.get(plan.get("mood"), plan.get("mood", "?"))
    if s.get("enabled") != "on":
        return f"Off  ·  now it would be {mood}"
    if data.get("service") != "active":
        return "On, but not running"
    held = " -- held: gamemode" if (data.get("inputs") or {}).get("gamemode") else ""
    return f"{mood}: {plan.get('why', '')}{held}"


def lights_text(data):
    s, paired = data.get("settings") or {}, data.get("paired") or {}
    if s.get("lights") == "hue":
        if not s.get("hue_bridge"):
            return "No bridge yet: find it or type its address"
        return f"Bridge {s['hue_bridge']}: " + ("paired" if paired.get("hue") else
                                                 "not paired: press its button, then Pair")
    if s.get("lights") == "ha":
        missing = [n for n, ok in (("the address", s.get("ha_url")), ("a token", paired.get("ha")),
                                   ("lights or scenes", s.get("ha_lights") or s.get("ha_scenes"))) if not ok]
        return ("Needs " + ", ".join(missing)) if missing else f"{s['ha_url']}: ready"
    return "Off  ·  lights are never touched"


def theme_items(themes):
    return [("", "None (leave it)")] + [(t, t.capitalize()) for t in themes]


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.switches = {}
        self.data = {}

        # STATUS
        w.pack_start(heading("STATUS"), False, False, 0)
        self.master = Gtk.Switch()
        self.master.connect("state-set", lambda _s, state: self.switch_master(state))
        grid, self.status = row("\uf185", "Follow the time, the weather and focus", "", self.master)
        w.pack_start(grid, False, False, 0)
        self.now = dp.label("", "ctl-sub")
        self.now.set_line_wrap(True)
        w.pack_start(details(self.now, label="What it is doing now"), False, False, 0)
        w.pack_start(dp.label("Preview a mood (changes nothing)", "ctl-sub"), False, False, 0)
        self.preview = Chips(self.show_preview, mark=False)
        w.pack_start(self.preview.widget, False, False, 0)
        self.preview_text = dp.label("", "ctl-sub")
        self.preview_text.set_line_wrap(True)
        w.pack_start(self.preview_text, False, False, 0)
        w.pack_start(links_row(link("Apply now", lambda: self.run(AMBIENT, "poke")),
                               link("Focus settings", lambda: spawn(SETTINGS, "focus")),
                               link("Presence", lambda: spawn(SETTINGS, "presence"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # LOOK
        w.pack_start(heading("LOOK"), False, False, 0)
        self.add_switches(LOOK)
        w.pack_start(dp.label("How strong", "ctl-sub"), False, False, 0)
        self.strength = Chips(lambda k: self.run(AMBIENT, "set", "strength", k))
        w.pack_start(self.strength.widget, False, False, 0)
        w.pack_start(dp.label("Calmer animations", "ctl-sub"), False, False, 0)
        self.anim_when = Chips(lambda k: self.run(AMBIENT, "set", "anim_when", k))
        w.pack_start(self.anim_when.widget, False, False, 0)
        self.anim_style = Chips(lambda k: self.run(AMBIENT, "set", "anim_style", k))
        w.pack_start(self.anim_style.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # THEME
        w.pack_start(heading("THEME"), False, False, 0)
        self.add_switches([("theme", "\uf1fc", "Theme follows ambience",
                            "day / evening / night themes, and the one below in focus")])
        w.pack_start(dp.label("Theme for focus blocks", "ctl-sub"), False, False, 0)
        self.focus_theme = Chips(lambda k: self.run(AMBIENT, "set", "focus_theme", k))
        w.pack_start(self.focus_theme.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # SOUND
        w.pack_start(heading("SOUND"), False, False, 0)
        self.add_switches(SOUND[:1])
        self.vol_focus = Slider("vol_focus", "Notification sound in a focus block", 0, 100, 5, " %", self.commit)
        self.vol_night = Slider("vol_night", "... and at night", 0, 100, 5, " %", self.commit)
        w.pack_start(self.vol_focus.widget, False, False, 0)
        w.pack_start(self.vol_night.widget, False, False, 0)
        self.add_switches(SOUND[1:])
        self.kind = Chips(lambda k: self.run(AMBIENT, "set", "sound_kind", k))
        w.pack_start(self.kind.widget, False, False, 0)
        self.sound_when = Chips(lambda k: self.run(AMBIENT, "set", "sound_when", k))
        w.pack_start(self.sound_when.widget, False, False, 0)
        self.music = Chips(lambda k: self.run(AMBIENT, "set", "sound_music", k))
        w.pack_start(self.music.widget, False, False, 0)
        self.sound_volume = Slider("sound_volume", "Soundscape volume", 5, 60, 1, " %", self.commit)
        w.pack_start(self.sound_volume.widget, False, False, 0)
        self.sound_sub = dp.label("", "ctl-sub")
        self.sound_sub.set_line_wrap(True)
        w.pack_start(self.sound_sub, False, False, 0)
        w.pack_start(links_row(link("Play now", lambda: self.run(AMBIENT, "soundscape", "now")),
                               link("Stop", lambda: self.run(AMBIENT, "soundscape", "stop")),
                               link("Make the sounds", lambda: self.run(AMBIENT, "sounds", "make"))),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # SMART LIGHTS
        w.pack_start(heading("SMART LIGHTS"), False, False, 0)
        self.provider = Chips(lambda k: self.run(AMBIENT, "set", "lights", k))
        w.pack_start(self.provider.widget, False, False, 0)
        self.lights_sub = dp.label("", "ctl-sub")
        self.lights_sub.set_line_wrap(True)
        w.pack_start(self.lights_sub, False, False, 0)
        w.pack_start(links_row(link("Find on my network", self.discover),
                               link("Pair the Hue bridge", self.pair),
                               link("Test Home Assistant", lambda: self.run(AMBIENT, "lights", "ha", "test",
                                                                            ok="Home Assistant answered")),
                               link("Try focus scene", self.try_scene)), False, False, 0)
        self.found = Chips(self.pick_found, mark=False)
        w.pack_start(self.found.widget, False, False, 0)
        self.groups = Chips(lambda k: self.run(AMBIENT, "set", "hue_group", k))
        w.pack_start(self.groups.widget, False, False, 0)

        self.entries = {}
        for key, icon, title, placeholder, secret in (
                ("hue_bridge", "\uf0eb", "Hue bridge address", "192.168.1.20", False),
                ("ha_url", "\uf015", "Home Assistant address", "http://homeassistant.local:8123", False),
                ("ha_token", "\uf084", "Home Assistant token", "a long-lived access token (your profile > Security)",
                 True),
                ("ha_lights", "\uf0eb", "Home Assistant lights", "light.desk, light.lamp", False),
                ("ha_scenes", "\uf03a", "Home Assistant scenes per mood (optional)",
                 "focus=scene.work, night=scene.sleep", False)):
            entry = Gtk.Entry()
            entry.set_placeholder_text(placeholder)
            entry.set_width_chars(36)
            if secret:
                entry.set_visibility(False)
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            entry.connect("activate", lambda _e, k=key: self.save_entry(k))
            box = Gtk.Box(spacing=6)
            box.pack_start(entry, True, True, 0)
            box.pack_start(link("Save", lambda k=key: self.save_entry(k)), False, False, 0)
            grid, _ = row(icon, title, "", box)
            self.entries[key] = (entry, grid)
            w.pack_start(grid, False, False, 0)

        self.light_sliders = {}
        for mood, caption in (("day", "Day"), ("relax", "Evening"), ("focus", "Focus"), ("night", "Night")):
            sl = Slider(f"light_{mood}", f"{caption} brightness", 1, 100, 1, " %", self.commit)
            self.light_sliders[mood] = sl
            w.pack_start(sl.widget, False, False, 0)
        self.add_switches([("lights_away", "\uf0eb", "Lights off when you are away",
                            "back on with the next mood")])
        w.pack_start(sep(), False, False, 0)

        # MORE
        w.pack_start(heading("MORE"), False, False, 0)
        self.add_switches(MORE)
        note = dp.label("What it reads: the clock and the night light's schedule, the weather the bar already "
                        "fetched, whether a focus block runs, Do Not Disturb, Presence's present / away (only "
                        "when you turned Presence on) and the lock screen. It never looks at the screen, the "
                        "camera, the microphone or the clipboard, sends nothing to the internet, and the lights' "
                        "addresses must be on your own network. The token is kept in a file only you can read.",
                        "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(details(note, label="What it reads"), False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    # -- building --------------------------------------------------------------------------
    def add_switches(self, specs):
        for key, icon, name, sub in specs:
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
            grid, _ = row(icon, name, sub, sw)
            self.switches[key] = sw
            self.widget.pack_start(grid, False, False, 0)

    # -- actions ---------------------------------------------------------------------------
    def run(self, *cmd, stdin=None, ok="", then=None):
        if self.updating:
            return

        def work():
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, input=stdin)
                if res.returncode == 0:
                    return ok, res.stdout
                return (res.stderr or res.stdout).strip().splitlines()[-1:] or ["failed"], ""
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc), ""

        def done(result):
            msg, out = result
            self.refresh()
            self.msg.set_text(msg if isinstance(msg, str) else msg[0])
            if then:
                then(out)
        background(work, done)

    def toggle(self, key, state):
        self.run(AMBIENT, "set", key, "on" if state else "off")
        return False

    def switch_master(self, state):
        self.run(AMBIENT, "set", "on" if state else "off")
        return True             # moves when the refresh says it did

    def commit(self, key, value):
        self.run(AMBIENT, "set", key, str(value))

    def show_preview(self, mood):
        def work():
            return run_json(AMBIENT, "plan", "--json", "--mood", mood) or {}
        background(work, lambda d: self.preview_text.set_text(
            "  ·  ".join((d.get("lines") or ["ambient.py did not answer"])[1:]) or "nothing to change"))

    def save_entry(self, key):
        entry, _ = self.entries[key]
        text = entry.get_text().strip()
        if key == "ha_token":
            entry.set_text("")
            self.run(AMBIENT, "lights", "ha", "token", "-", stdin=text + "\n", ok="token saved")
        elif key == "ha_url" and text:
            self.run(AMBIENT, "lights", "ha", "url", text, ok="saved")
        else:
            self.run(AMBIENT, "set", key, text, ok="saved")

    def discover(self):
        self.msg.set_text("Looking on your network...")

        def work():
            return run_json(AMBIENT, "lights", "discover", "--json", timeout=30) or {}

        def done(found):
            items = [(f"hue:{b['ip']}", f"Hue: {b['name']} ({b['ip']})") for b in found.get("hue", [])] + \
                [(f"ha:{h['url']}", f"Home Assistant: {h['name']}") for h in found.get("ha", [])]
            self.found.set(items, None)
            self.msg.set_text("Found: pick one." if items else
                              "Nothing found: type the address instead")
            self.widget.show_all()
        background(work, done)

    def pick_found(self, key):
        kind, _, value = key.partition(":")
        if kind == "hue":
            self.run(AMBIENT, "set", "lights", "hue", then=lambda _o: self.run(AMBIENT, "set", "hue_bridge", value))
        else:
            self.run(AMBIENT, "set", "lights", "ha", then=lambda _o: self.run(AMBIENT, "lights", "ha", "url", value))

    def pair(self):
        ip = (self.data.get("settings") or {}).get("hue_bridge") or self.entries["hue_bridge"][0].get_text().strip()
        if not ip:
            self.msg.set_text("First the bridge's address (Find on my network).")
            return
        self.msg.set_text("Press the round button on the bridge now -- waiting 30 s...")
        self.run(AMBIENT, "lights", "hue", "pair", ip, "--wait", "30", ok="Paired with the bridge.")

    def try_scene(self):
        self.run(AMBIENT, "lights", "scene", "focus", "--dry-run",
                 then=lambda out: self.msg.set_text(out.strip() or self.msg.get_text()))

    def load_groups(self):
        def work():
            return run_json(AMBIENT, "lights", "hue", "groups", "--json") or []
        background(work, lambda groups: (self.groups.set(
            [(g["id"], g["name"]) for g in groups] or [("0", "Every light")],
            (self.data.get("settings") or {}).get("hue_group", "0")), self.widget.show_all()))

    # -- drawing ---------------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(AMBIENT, "status", "--json") or {}, self.draw)

    def draw(self, data):
        if not data:
            self.msg.set_text("Ambient did not answer")
            return
        self.data = data
        self.updating = True
        try:
            s = data["settings"]
            on = s.get("enabled") == "on"
            self.master.set_state(on)
            self.master.set_active(on)
            self.status.set_text(status_text(data))
            self.now.set_text("  ·  ".join(data.get("lines", [])[1:]) if on else "")
            self.preview.set([(m, n) for m, n in MOOD_NAMES.items()], None)
            for key, sw in self.switches.items():
                sw.set_active(s.get(key) == "on")
            self.strength.set(STRENGTH, s["strength"])
            self.anim_when.set(ANIM_WHEN, s["anim_when"])
            self.anim_style.set(ANIM_STYLE, s["anim_style"])
            self.focus_theme.set(theme_items(data.get("themes") or []), s["focus_theme"])
            self.vol_focus.show(int(s["vol_focus"]))
            self.vol_night.show(int(s["vol_night"]))
            self.kind.set(KINDS, s["sound_kind"])
            self.sound_when.set(SOUND_WHEN, s["sound_when"])
            self.music.set(MUSIC, s["sound_music"])
            self.sound_volume.show(int(s["sound_volume"]))
            tools = data.get("tools") or {}
            made = [k for k, v in (data.get("sounds") or {}).items() if v]
            self.sound_sub.set_text(
                "Needs ffmpeg and mpv." if not (tools.get("ffmpeg") and tools.get("mpv")) else
                f"Made: {', '.join(made)}" if made else "Sounds are made the first time they play")
            self.provider.set(PROVIDERS, s["lights"])
            self.lights_sub.set_text(lights_text(data))
            kind = s["lights"]
            for key, (entry, grid) in self.entries.items():
                show = (kind == "hue" and key == "hue_bridge") or (kind == "ha" and key.startswith("ha_"))
                grid.set_no_show_all(not show)
                grid.set_visible(show)
                if show and key != "ha_token" and not entry.has_focus():
                    entry.set_text(s.get(key, ""))
                if key == "ha_token":
                    entry.set_placeholder_text("saved (type a new one to replace it)" if data["paired"].get("ha")
                                               else "a long-lived access token (your profile > Security)")
            for mood, sl in self.light_sliders.items():
                sl.widget.set_no_show_all(kind == "off")
                sl.widget.set_visible(kind != "off")
                sl.show(int(s[f"light_{mood}"]))
            self.groups.widget.set_no_show_all(kind != "hue" or not data["paired"].get("hue"))
            self.groups.widget.set_visible(kind == "hue" and data["paired"].get("hue"))
            if kind == "hue" and data["paired"].get("hue") and not self.groups.buttons:
                self.load_groups()
        finally:
            self.updating = False
        self.widget.show_all()
