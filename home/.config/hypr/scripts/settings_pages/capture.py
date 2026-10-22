"""Settings page: screenshots, screen recording, the screen actions' OCR and
"Look it up", and gamemode with the game profiles.

Every choice is written through ~/.config/hypr/scripts/capture-settings.py
(its file, ~/.local/state/hypr/capture.conf, is the only place they are
kept) and read back from `capture-settings.py status` after each change. The
scripts doing the work read that file each time they run: screenshot.sh
(folder, format, also copy, OCR languages), record.sh (folder, sound, frame
rate, replay length), screen-actions.py (OCR languages, search engine) and
lua/gamemode.lua (what gamemode strips, the Steam hooks) -- so nothing needs
restarting, and a choice holds across a Hyprland reload and a re-login.

Two things belong to other scripts and are only shown and switched here:
SDR / HDR is record.sh's own (`record.sh sdr|hdr`), the game profiles are
game-profiles.py's (list, save, forget). Do Not Disturb while a game runs is
the Notifications page's, which this page links to rather than repeating.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402

PAGE = {"id": "capture", "title": "Screenshots & recording", "icon": "", "group": "Apps", "order": 30,
        "keywords": ["screenshot", "screen capture", "print screen", "hyprshot", "screenshot folder",
                     "jpeg", "webp", "png", "record", "recording", "screen recorder", "video",
                     "instant replay", "replay buffer", "shadowplay", "hdr recording", "microphone",
                     "frame rate", "fps", "ocr", "text recognition", "tesseract", "languages",
                     "look it up", "search engine", "google", "duckduckgo", "gamemode", "game mode",
                     "games", "steam", "game profiles", "blur", "gaps", "captura", "grabar"]}

CAPTURE = os.path.join(HYPR, "capture-settings.py")
RECORD = os.path.join(HYPR, "record.sh")
NOTIFY = os.path.join(HYPR, "notify-settings.py")
SETTINGS = os.path.join(HYPR, "settings.py")

FORMATS = [("png", "PNG"), ("jpg", "JPEG"), ("webp", "WebP")]
FORMAT_SUB = {"png": "lossless, the sharpest text; the biggest files",
              "jpg": "a fraction of the size, opens everywhere; fine detail softens a little",
              "webp": "smaller still at the same look; most apps and every browser open it"}
RANGES = [("sdr", "SDR"), ("hdr", "HDR")]
AUDIO = [("desktop", "Desktop sound"), ("both", "Desktop + microphone"), ("mic", "Microphone only"),
         ("none", "No sound")]
FPS = [("30", "30 fps"), ("60", "60 fps"), ("120", "120 fps"), ("144", "144 fps")]
REPLAY = ["15", "30", "60", "120", "300"]
REPLAY_MBIT = 80        # record.sh's replay bitrate (REPLAY_QUALITY): what the RAM estimate uses
# (key, icon, title, what switching it on does) -- lua/gamemode.lua's list
STRIP = [("gamemode_blur", "\uf0d0", "Turn blur off",
          "the frosted glass behind bars and popups, redrawn by the GPU every frame"),
         ("gamemode_shadow", "\uf042", "Turn shadows off", "the soft shadow under each window"),
         ("gamemode_rounding", "\uf096", "Square corners", "rounded corners are cut by a shader on every window"),
         ("gamemode_gaps", "\uf0db", "No gaps", "windows fill the screen edge to edge"),
         ("gamemode_borders", "\uf0c8", "Thin borders", "window borders go down to 1 pixel")]
# Tesseract's names for the languages someone is likeliest to want, for the
# "add one" hint; any other installed one shows up by its code.
LANG_NAMES = {"eng": "English", "spa": "Spanish", "fra": "French", "deu": "German", "ita": "Italian",
              "por": "Portuguese", "nld": "Dutch", "pol": "Polish", "rus": "Russian", "ukr": "Ukrainian",
              "jpn": "Japanese", "kor": "Korean", "chi_sim": "Chinese (simplified)",
              "chi_tra": "Chinese (traditional)", "ara": "Arabic", "hin": "Hindi", "tur": "Turkish",
              "swe": "Swedish", "cat": "Catalan", "ell": "Greek"}


def attempt(*cmd, timeout=20, env=None):
    """"" when the command worked, else its last stderr line -- the backend
    exits with a readable reason (a refused value, no running game). Called
    from background() only."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, **(env or {})))
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def home(path):
    h = os.path.expanduser("~")
    return "~" + path[len(h):] if path == h or path.startswith(h + "/") else path


def seconds_text(s):
    s = int(s)
    return f"{s} s" if s < 60 else (f"{s // 60} min" if s % 60 == 0 else f"{s // 60} min {s % 60} s")


def replay_ram(seconds, mbit=REPLAY_MBIT):
    """What a replay buffer of that length holds in RAM, in words."""
    mb = int(seconds) * mbit / 8
    return f"about {mb / 1000:.1f} GB" if mb >= 1000 else f"about {mb:.0f} MB"


def toggle_lang(chosen, lang):
    """The OCR languages with `lang` switched: added at the end, or taken
    out -- but never the last one, tesseract needs at least one."""
    langs = [l for l in chosen.split("+") if l]
    if lang in langs:
        if len(langs) > 1:
            langs.remove(lang)
    else:
        langs.append(lang)
    return "+".join(langs)


def lang_name(code):
    return LANG_NAMES.get(code, code)


def profile_sub(prof):
    """One line for a game profile: what it puts back when the game starts."""
    parts = []
    if prof.get("monitor"):
        parts.append(f"on {prof['monitor']}")
    for screen, hz in sorted((prof.get("rates") or {}).items()):
        try:
            parts.append(f"{screen} {float(hz):g} Hz")
        except (TypeError, ValueError):
            pass
    if "hdr" in prof:
        parts.append(f"HDR {prof['hdr']}")
    if "volume" in prof:
        parts.append(f"volume {prof['volume']} %")
    if prof.get("screens"):
        parts.append("brightness / warmth of " + ", ".join(sorted(prof["screens"])))
    return "  ·  ".join(parts) or "empty profile"


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        self.updating = False
        self.forgetting = None      # the appid whose Forget waits for a yes
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        # -- screenshots --
        w.pack_start(heading("SCREENSHOTS"), False, False, 0)
        self.folder_rows = {}
        self.folder_row(w, "shot_dir", "\uf07c", "Save screenshots in")
        grid, self.format_sub = row("\uf1c5", "File format", "")
        w.pack_start(grid, False, False, 0)
        self.format = self.make_chips(lambda k: self.set("shot_format", k))
        w.pack_start(self.format.widget, False, False, 0)
        self.switches = {}
        self.switch_row(w, "shot_copy", "\uf0ea", "Also copy to the clipboard",
                        "a shot that is saved goes on the clipboard too, ready to paste; SUPER+S always "
                        "copies only, without saving")
        self.binds_note = dp.label("", "ctl-sub")
        self.binds_note.set_line_wrap(True)
        self.binds_note.set_xalign(0)
        w.pack_start(self.binds_note, False, False, 0)
        keys = dp.label("ALT+S a screen  ·  ALT+SHIFT+S a region  ·  ALT+CTRL+S a window  ·  SUPER+S a region "
                        "to the clipboard only  ·  SUPER+SHIFT+S draw on a region  ·  SUPER+CTRL+S the window "
                        "framed for a README  ·  SUPER+O the text in a region", "ctl-sub")
        keys.set_line_wrap(True)
        keys.set_xalign(0)
        w.pack_start(keys, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- recording --
        w.pack_start(heading("SCREEN RECORDING"), False, False, 0)
        self.rec_row, self.rec_sub = row("\uf03d", "Recorder", "")
        w.pack_start(self.rec_row, False, False, 0)
        self.folder_row(w, "rec_dir", "\uf07c", "Save recordings and replays in")
        grid, self.range_sub = row("\uf185", "Dynamic range", "")
        w.pack_start(grid, False, False, 0)
        self.range = self.make_chips(self.set_range)
        w.pack_start(self.range.widget, False, False, 0)
        grid, self.audio_sub = row("\uf028", "Sound in recordings", "")
        w.pack_start(grid, False, False, 0)
        self.audio = self.make_chips(lambda k: self.set("rec_audio", k))
        w.pack_start(self.audio.widget, False, False, 0)
        grid, self.fps_sub = row("\uf008", "Frame rate", "")
        w.pack_start(grid, False, False, 0)
        self.fps = self.make_chips(lambda k: self.set("rec_fps", k))
        w.pack_start(self.fps.widget, False, False, 0)
        grid, self.replay_sub = row("\uf1da", "Instant replay keeps", "")
        w.pack_start(grid, False, False, 0)
        self.replay = self.make_chips(lambda k: self.set("replay_seconds", k))
        w.pack_start(self.replay.widget, False, False, 0)
        self.replay_links = Gtk.Box()
        w.pack_start(self.replay_links, False, False, 0)
        keys = dp.label("ALT+F9 record the screen (again to stop)  ·  ALT+SHIFT+F9 a region  ·  ALT+SHIFT+F10 "
                        "instant replay on / off  ·  ALT+F10 save the replay  ·  ALT+CTRL+F9 switch SDR / HDR",
                        "ctl-sub")
        keys.set_line_wrap(True)
        keys.set_xalign(0)
        w.pack_start(keys, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- screen actions --
        w.pack_start(heading("SCREEN ACTIONS"), False, False, 0)
        grid, self.ocr_sub = row("\uf1ab", "Languages to read", "")
        w.pack_start(grid, False, False, 0)
        self.langs = Gtk.FlowBox()
        self.langs.set_selection_mode(Gtk.SelectionMode.NONE)
        self.langs.set_column_spacing(4)
        self.langs.set_row_spacing(4)
        self.langs.set_max_children_per_line(7)
        self.langs.set_halign(Gtk.Align.START)
        self.langs.get_style_context().add_class("dev-list")
        w.pack_start(self.langs, False, False, 0)
        grid, self.search_sub = row("\uf002", "\"Look it up\" searches with", "")
        w.pack_start(grid, False, False, 0)
        self.search = self.make_chips(lambda k: self.set("search", k))
        w.pack_start(self.search.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- gamemode --
        w.pack_start(heading("GAME MODE"), False, False, 0)
        self.gm_row, self.gm_sub = row("\uf11b", "Game mode", "")
        w.pack_start(self.gm_row, False, False, 0)
        for key, icon, title, sub in STRIP:
            self.switch_row(w, key, icon, title, sub)
        self.switch_row(w, "gamemode_auto", "\uf144", "Turn on by itself for Steam games",
                        "on when a game's window opens, off again a few seconds after the last one closes -- "
                        "unless you pressed ALT+SHIFT+G in between, which always wins")
        self.switch_row(w, "gamemode_hide_steam", "\uf070", "Hide Steam while a game runs",
                        "the Steam windows step aside while you play and come back to workspace 5 after; "
                        "ALT+CTRL+G peeks at them")
        self.dnd_row, self.dnd_sub = row("\uf1f6", "Do Not Disturb while a game runs", "",
                                         link("Open Notifications", lambda: spawn(SETTINGS, "notifications")))
        w.pack_start(self.dnd_row, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("GAME PROFILES"), False, False, 0)
        intro = dp.label("Each Steam game can remember its own screen, refresh rates, HDR, volume and screen "
                         "brightness / warmth, and gets them back when it starts; when it closes, what it "
                         "changed is put back.", "ctl-sub")
        intro.set_line_wrap(True)
        intro.set_xalign(0)
        w.pack_start(intro, False, False, 0)
        self.games = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.games, False, False, 0)
        w.pack_start(links_row(link("Save for the running game", lambda: self.do(GAMES, "save"))),
                     False, False, 0)

    # -- building blocks -------------------------------------------------------------
    @staticmethod
    def make_chips(on_pick):
        """Chips on one line where they fit (see power.py's: a FlowBox packed
        at the start otherwise shrinks to one chip per line)."""
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(8)
        chips.widget.set_halign(Gtk.Align.START)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 8)))
        chips.set = set_items
        return chips

    def switch_row(self, box, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
        grid, sub_label = row(icon, title, sub, sw)
        self.switches[key] = sw
        box.pack_start(grid, False, False, 0)

    def folder_row(self, box, key, icon, title):
        """A folder: the path, a chooser to pick another, Open and Default."""
        chooser = Gtk.FileChooserButton.new(title, Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.set_width_chars(18)
        chooser.connect("file-set", lambda c, k=key: c.get_filename() and self.set(k, c.get_filename()))
        grid, sub = row(icon, title, "", chooser)
        box.pack_start(grid, False, False, 0)
        box.pack_start(links_row(link("Open the folder", lambda k=key: self.open_folder(k)),
                                 link("Back to the default", lambda k=key: self.do(CAPTURE, "reset", k))),
                       False, False, 0)
        self.folder_rows[key] = (chooser, sub)

    def open_folder(self, key):
        if self.data:
            path = self.data["folders"][key]
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                self.done(f"cannot make {home(path)}: {exc.strerror}")
                return
            spawn("xdg-open", path)

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd, env=None):
        background(lambda: attempt(*cmd, env=env), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def set(self, key, value):
        if not self.updating:
            self.do(CAPTURE, "set", key, value)

    def toggle(self, key, state):
        if not self.updating:
            self.set(key, "on" if state else "off")
        return True

    def set_range(self, key):
        if not self.updating:
            # REC_QUIET: the page shows the change; no bubble on top of it.
            self.do(RECORD, key, env={"REC_QUIET": "1"})

    def pick_lang(self, lang):
        if self.data and not self.updating:
            self.set("ocr_langs", toggle_lang(self.data["values"]["ocr_langs"], lang))

    def restart_replay(self):
        """Off and on again, so the buffer starts with the new length. What
        it held is dropped -- the button says so."""
        background(lambda: attempt(RECORD, "toggle-replay") or attempt(RECORD, "toggle-replay"), self.done)

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None:
            self.format_sub.set_text("checking…")
        background(lambda: (run_json(CAPTURE, "status", timeout=15), run_json(NOTIFY, "status", timeout=15)),
                   self.show)

    def show(self, result):
        data, notify = result
        if not data:
            self.format_sub.set_text("capture-settings.py did not answer")
            return
        self.data = data
        self.updating = True
        v, tools = data["values"], data["tools"]

        for key, (chooser, sub) in self.folder_rows.items():
            path = data["folders"][key]
            if chooser.get_filename() != path and os.path.isdir(path):
                chooser.set_filename(path)
            text = home(path) + ("" if data["folder_exists"][key] else "  ·  made with the first save")
            if v[key] == data["defaults"][key]:
                text += "  ·  the default"
            sub.set_text(text)
        self.format.set(FORMATS, v["shot_format"])
        fmt_sub = FORMAT_SUB[v["shot_format"]]
        if v["shot_format"] != "png":
            fmt_sub += "  ·  drawn-on shots (SUPER+SHIFT+S) stay PNG"
            if not tools["magick"]:
                fmt_sub += "  ·  needs ImageMagick (sudo dnf install ImageMagick); PNG until then"
        self.format_sub.set_text(fmt_sub)
        if data["shot_binds_follow"]:
            self.binds_note.set_text("")
            self.binds_note.hide()
        else:
            self.binds_note.set_text("!  The ALT+S keys still run hyprshot on their own, so they save PNG into "
                                     "~/Pictures/Screenshots and always copy too, whatever is set here; the "
                                     "SUPER keys follow these settings.")

        if not tools["gpu-screen-recorder"]:
            self.rec_sub.set_text("gpu-screen-recorder is not installed: sudo dnf install gpu-screen-recorder")
        else:
            running = [t for t, on in (("recording", data["recording"]), ("instant replay", data["replay"])) if on]
            self.rec_sub.set_text(("Running now: " + " and ".join(running) + ". Changes apply to the next one."
                                   if running else "Nothing is being recorded.")
                                  + "  ·  gpu-screen-recorder on the graphics card's encoder (NVENC)")
        self.range.set(RANGES, data["range"])
        hdr = data["hdr_screens"]
        self.range_sub.set_text(
            ("HEVC HDR10: only looks right in an HDR player on an HDR screen. " +
             (f"In HDR now: {', '.join(hdr)}; any other screen records in SDR."
              if hdr else "No screen is in HDR now, so recordings come out SDR until one is."))
            if data["range"] == "hdr" else
            "h264: plays in every browser, chat and phone; an HDR screen is tone-mapped down")
        self.audio.set(AUDIO, v["rec_audio"])
        self.audio_sub.set_text({"desktop": "what you hear, without the microphone",
                                 "both": "what you hear and the default microphone, mixed into one track",
                                 "mic": "only the default microphone (Sound page picks which one)",
                                 "none": "silent video"}[v["rec_audio"]])
        self.fps.set(FPS, v["rec_fps"])
        self.fps_sub.set_text("frames per second in recordings and the replay; above 60 only helps on a "
                              "screen that runs that fast, and the files grow with it")
        self.replay.set([(s, seconds_text(s)) for s in REPLAY], v["replay_seconds"])
        sub = (f"ALT+F10 saves the last {seconds_text(v['replay_seconds'])}; the buffer holds "
               f"{replay_ram(v['replay_seconds'])} of memory while it is on")
        clear(self.replay_links)
        if data["replay"]:
            sub += "  ·  it is on now, with the length it started with"
            self.replay_links.pack_start(links_row(
                link("Restart the replay (drops what it holds)", self.restart_replay),
                link("Turn the replay off", lambda: self.do(RECORD, "toggle-replay"))), True, True, 0)
        else:
            self.replay_links.pack_start(links_row(
                link("Turn the replay on", lambda: self.do(RECORD, "toggle-replay"))), True, True, 0)
        self.replay_sub.set_text(sub)

        self.draw_langs(data)
        self.search.set(sorted(data["engines"].items(), key=lambda kv: kv[0] != "duckduckgo"), v["search"])
        self.search_sub.set_text("SUPER+SHIFT+T reads a region, SUPER+ALT+T takes the selected text; \"Look "
                                 "it up\" opens this in the default browser")

        on = data["gamemode_on"]
        self.gm_sub.set_text(("ON now" if on else "off now" if on is not None else "state unknown") +
                             "  ·  ALT+SHIFT+G switches it  ·  animations always go off (that is how the "
                             "desktop knows gamemode is on); the ones below are yours to keep. A change "
                             "applies the next time it turns on.")
        for key, sw in self.switches.items():
            state = v[key] == "on"
            sw.set_state(state)
            sw.set_active(state)
        settings = (notify or {}).get("settings") or {}
        if "dnd_games" in settings:
            self.dnd_sub.set_text(("on: notifications wait until the game closes"
                                   if settings["dnd_games"] else "off: notifications show during games")
                                  + "  ·  set on the Notifications page")
        else:
            self.dnd_sub.set_text("set on the Notifications page")

        self.draw_profiles()
        if data["invalid"]:
            self.error.set_text("!  Not understood in capture.conf, so the default is used: " +
                                ", ".join(data["invalid"]))
            self.error.set_visible(True)
        self.widget.show_all()
        if data["shot_binds_follow"]:
            self.binds_note.hide()
        self.updating = False

    def draw_profiles(self):
        """The game profiles. Forget asks first: a profile is set up by hand
        while the game runs, and gone is gone (game-profiles.py keeps no copy)."""
        clear(self.games)
        profiles = (self.data or {}).get("profiles") or {}
        if not profiles:
            lab = dp.label("No profiles yet. While a game runs, set it up the way you like and press Save "
                           "below, or search \"Save game profile\".", "ctl-sub")
            lab.set_line_wrap(True)
            lab.set_xalign(0)
            self.games.pack_start(lab, False, False, 0)
        for appid, prof in sorted(profiles.items(), key=lambda kv: (kv[1].get("name") or kv[0]).lower()):
            if self.forgetting == appid:
                ask = Gtk.Box(spacing=8)
                ask.pack_start(link("Yes, forget it", lambda a=appid: self.forget(a)), False, False, 0)
                ask.pack_start(link("Cancel", lambda: self.ask_forget(None)), False, False, 0)
                grid, _ = row("\uf11b", prof.get("name") or appid,
                              "Forget this profile? The game then starts with whatever is set at the time.", ask)
            else:
                grid, _ = row("\uf11b", prof.get("name") or appid, profile_sub(prof),
                              link("Forget", lambda a=appid: self.ask_forget(a)))
            self.games.pack_start(grid, False, False, 0)
        self.games.show_all()

    def ask_forget(self, appid):
        self.forgetting = appid
        self.draw_profiles()

    def forget(self, appid):
        self.forgetting = None
        self.do(GAMES, "forget", appid)

    def draw_langs(self, data):
        for child in self.langs.get_children():
            self.langs.remove(child)
        have = data["tesseract"]
        chosen = data["values"]["ocr_langs"].split("+")
        if have is None:
            self.ocr_sub.set_text("tesseract is not installed: sudo dnf install tesseract "
                                  "tesseract-langpack-eng tesseract-langpack-spa")
            return
        for lang in sorted(set(have) | set(chosen), key=lambda l: (l not in chosen, lang_name(l))):
            b = Gtk.Button(label=lang_name(lang) + ("" if lang in have else "  (not installed)"))
            b.get_style_context().add_class("dev-pick")
            if lang in chosen:
                b.get_style_context().add_class("active")
            b.set_can_focus(False)
            b.connect("clicked", lambda _b, l=lang: self.pick_lang(l))
            self.langs.add(b)
        self.langs.set_min_children_per_line(max(1, min(len(set(have) | set(chosen)), 7)))
        missing = [l for l in chosen if l not in have]
        sub = ("the text in a region is read in " + " + ".join(lang_name(l) for l in chosen if l in have)
               if any(l in have for l in chosen) else "none of the chosen languages is installed")
        sub += " (SUPER+O, SUPER+SHIFT+T); fewer languages read faster and guess less"
        if missing:
            sub += ("  ·  to add " + ", ".join(lang_name(l) for l in missing) + ": sudo dnf install " +
                    " ".join(f"tesseract-langpack-{l}" for l in missing))
        else:
            sub += ("  ·  for another one: sudo dnf install tesseract-langpack-<code> (fra, deu, por, "
                    "jpn…), and it shows up here to pick")
        self.ocr_sub.set_text(sub)
        self.ocr_sub.set_selectable(True)
