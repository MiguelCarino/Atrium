"""Settings page: spoken replies -- the local text-to-speech (tts.py, Piper).

Everything goes through tts.py: `status --json` for the settings, the
installed voices, whether it may speak now (and why not) and whether it is
speaking; `set KEY VALUE` to change one; `stop`; `download NAME` for another
voice (the only network use, and only on a click). The assistant's own
switch is assistant.py's voice_reply (`assistant.py status --json` / `set`).
The page keeps nothing of its own; the status is read in the background.

"Play" runs `tts.py test --lang L [TEXT] --json`: the sentence is made into
a tmpfs file, timed (the line under it says how fast: the real-time
factor), then played through tts.py's queue -- a click is the one thing
that speaks whatever the switches say. The tests never press it; they
render with `tts.py speak --to FILE`.
"""
import os

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "speech", "title": "Spoken replies", "icon": "", "group": "Apps", "order": 36,
        "keywords": ["text to speech", "tts", "speech", "read aloud", "leer en voz alta", "voz", "hablar",
                     "piper", "voice reply", "respuestas habladas", "spoken brief", "speak", "narrator",
                     "lector", "voices", "voces"]}

TTS = os.path.join(HYPR, "tts.py")
ASSISTANT = os.path.join(HYPR, "assistant.py")
# Font Awesome 6 Solid, as escapes (see audio_panel.py on why).
ICON_SPEAK, ICON_SUN, ICON_MIC, ICON_COMMENT, ICON_MOON = "", "", "", "", ""
ICON_TEXT = ""
LANGUAGES = [("auto", "Detect (Spanish / English)"), ("es", "Spanish"), ("en", "English")]
DUCK = [("lower", "Turn other sound down"), ("pause", "Pause the player"), ("off", "Leave it")]
REGIONS = {"MX": "Mexico", "ES": "Spain", "AR": "Argentina", "US": "US", "GB": "UK"}


# -- pure helpers (tests/test_tts.py) ------------------------------------------------------
def voice_caption(name):
    """"es_MX-ald-medium" -> "ald · Mexico · medium"."""
    try:
        locale, speaker, quality = name.split("-", 2)
        region = REGIONS.get(locale.split("_")[1], locale.split("_")[1])
    except (ValueError, IndexError):
        return name
    return f"{speaker.replace('_', ' ')} · {region} · {quality.replace('_', ' ')}"


def engine_line(data):
    """The SPEECH row's sub line, from `tts.py status --json`."""
    if not isinstance(data, dict) or not data.get("settings"):
        return "tts.py did not answer"
    if not data.get("installed"):
        return ("Not installed: ~/.local/share/tts/venv is missing (python3 -m venv there, then "
                "pip install piper-tts).")
    voices = data.get("voices") or {}
    if not any(voices.values()):
        return "No voice yet: pick one under Voices to download it."
    if data.get("speaking"):
        now = "Speaking now" + (f", {data['queued']} more waiting" if data.get("queued") else "")
    elif data.get("blocked"):
        now = f"Silent now: {data['blocked']}"
    else:
        now = "Ready"
    return f"{now}  ·  Piper on the CPU, nothing leaves this computer  ·  " + \
        ", ".join(f"{len(v)} {k}" for k, v in voices.items()) + " voices"


def test_line(result):
    """Under the Play buttons, from `tts.py test --json`."""
    if not isinstance(result, dict):
        return "tts.py did not answer"
    if result.get("error"):
        return f"Not played: {result['error']}"
    rtf = result.get("rtf")
    speed = f"{1 / rtf:.0f}× faster than real time" if rtf else "?"
    played = "Playing" if result.get("played") else "Made (not played)"
    return (f"{played}: {voice_caption(result.get('voice', '?'))}. {result.get('audio_s', 0)} s of speech made "
            f"in {result.get('synth_s', 0)} s ({speed}; voice loaded in {result.get('load_s', 0)} s).")


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.data = {}

        w.pack_start(heading("SPEECH"), False, False, 0)
        self.enabled = Gtk.Switch()
        self.enabled.connect("state-set", lambda _s, state: self.switch("enabled", state))
        grid, self.engine_sub = row(ICON_SPEAK, "The desktop can talk", "checking…", self.enabled)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Stop talking", self.stop)), False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("WHAT SPEAKS"), False, False, 0)
        self.brief = Gtk.Switch()
        self.brief.connect("state-set", lambda _s, state: self.switch("speak_brief", state))
        grid, _ = row(ICON_SUN, "The morning brief, read aloud",
                      "When the daily brief comes up in the morning it is also said: a sentence per section.",
                      self.brief)
        w.pack_start(grid, False, False, 0)
        self.commands = Gtk.Switch()
        self.commands.connect("state-set", lambda _s, state: self.switch("speak_commands", state))
        grid, _ = row(ICON_MIC, "Voice commands answer by voice",
                      "What a voice command did, what it asks before doing, or why not -- in the language you "
                      "spoke.", self.commands)
        w.pack_start(grid, False, False, 0)
        self.assistant = Gtk.Switch()
        self.assistant.connect("state-set", self.on_assistant)
        grid, self.assistant_sub = row(ICON_COMMENT, "The assistant says its answers",
                                       "Its replies in the chat are also spoken (cut at a sentence end when "
                                       "long).", self.assistant)
        w.pack_start(grid, False, False, 0)
        self.selection = Gtk.Switch()
        self.selection.connect("state-set", lambda _s, state: self.switch("speak_selection", state))
        grid, _ = row(ICON_TEXT, "Read the selection aloud",
                      "SUPER+ALT+S says the text you highlighted, again stops it (SUPER+ALT+Q stops any "
                      "speech). Never from a password manager or a private window.", self.selection)
        w.pack_start(grid, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("VOICES"), False, False, 0)
        w.pack_start(label("Spanish", "ctl-sub"), False, False, 0)
        self.voice_es = Chips(lambda key: self.set("voice_es", key))
        w.pack_start(self.voice_es.widget, False, False, 0)
        w.pack_start(label("English", "ctl-sub"), False, False, 0)
        self.voice_en = Chips(lambda key: self.set("voice_en", key))
        w.pack_start(self.voice_en.widget, False, False, 0)
        w.pack_start(label("Get another voice (downloaded once from rhasspy/piper-voices, then local)",
                           "ctl-sub"), False, False, 0)
        self.more = Chips(self.download, mark=False)
        w.pack_start(self.more.widget, False, False, 0)
        self.more_sub = label("", "ctl-sub")
        w.pack_start(self.more_sub, False, False, 0)
        w.pack_start(label("Language when a feature does not say", "ctl-sub"), False, False, 0)
        self.language = Chips(lambda key: self.set("language", key))
        w.pack_start(self.language.widget, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("HOW IT SOUNDS"), False, False, 0)
        commit = lambda key, value: self.set(key, value)  # noqa: E731
        self.rate = Slider("rate", "Speed", 50, 200, 5, " %", commit)
        w.pack_start(self.rate.widget, False, False, 0)
        self.volume = Slider("volume", "Volume", 10, 100, 5, " %", commit)
        w.pack_start(self.volume.widget, False, False, 0)
        self.max_chars = Slider("max_chars", "Longest reply read out (longer ones stop at a sentence end)",
                                100, 3000, 50, " chars", commit)
        w.pack_start(self.max_chars.widget, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("WHILE IT SPEAKS"), False, False, 0)
        w.pack_start(label("Music and videos", "ctl-sub"), False, False, 0)
        self.duck = Chips(lambda key: self.set("duck", key))
        w.pack_start(self.duck.widget, False, False, 0)
        self.duck_level = Slider("duck_level", "Other sound turned down to", 0, 80, 5, " %", commit)
        w.pack_start(self.duck_level.widget, False, False, 0)
        self.quiet = Gtk.Switch()
        self.quiet.connect("state-set", lambda _s, state: self.switch("quiet", state))
        grid, _ = row(ICON_MOON, "Silent in Do Not Disturb and the quiet hours",
                      "Always silent in gamemode. Whatever is not said still shows as a notification.",
                      self.quiet)
        w.pack_start(grid, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("TEST"), False, False, 0)
        self.test_text = Gtk.Entry()
        self.test_text.set_placeholder_text("Type something to hear it, or leave empty for a sample")
        w.pack_start(self.test_text, False, False, 0)
        self.test_sub = label("Plays out loud with the voices above, even when the switches are off.",
                              "ctl-sub")
        self.test_sub.set_line_wrap(True)
        self.test_sub.set_xalign(0)
        w.pack_start(self.test_sub, False, False, 0)
        w.pack_start(links_row(link("Play in Spanish", lambda: self.test("es")),
                               link("Play in English", lambda: self.test("en")),
                               link("Stop", self.stop)), False, False, 0)

    # -- reading -----------------------------------------------------------------------
    def refresh(self):
        def work():
            data = run_json(TTS, "status", "--json", timeout=15) or {}
            helper = run_json(ASSISTANT, "status", "--json", timeout=20) or {}
            data["assistant"] = (helper.get("settings") or {}).get("voice_reply")
            return data
        background(work, self.show)

    def show(self, data):
        self.data = data
        s = data.get("settings") or {}
        self.engine_sub.set_text(engine_line(data))
        if not s:
            return
        self.updating = True
        self.enabled.set_state(s["enabled"] == "on")
        self.brief.set_state(s["speak_brief"] == "on")
        self.commands.set_state(s["speak_commands"] == "on")
        self.selection.set_state(s["speak_selection"] == "on")
        self.assistant.set_state(data.get("assistant") == "on")
        self.assistant.set_sensitive(data.get("assistant") in ("on", "off"))
        if data.get("assistant") not in ("on", "off"):
            self.assistant_sub.set_text("assistant.py did not answer.")
        voices = data.get("voices") or {}
        for lang, chips in (("es", self.voice_es), ("en", self.voice_en)):
            have = voices.get(lang) or []
            chips.set([(v, voice_caption(v)) for v in have] or [("", "none installed")], s[f"voice_{lang}"])
        curated = data.get("curated") or {}
        more = [(v, f"{'ES' if lang == 'es' else 'EN'} · {voice_caption(v)}") for lang in ("es", "en")
                for v in curated.get(lang, []) if v not in (voices.get(lang) or [])]
        self.more.set(more or [("", "all of them are here")], None)
        self.language.set(LANGUAGES, s["language"])
        self.rate.show(int(s["rate"]))
        self.volume.show(int(s["volume"]))
        self.max_chars.show(int(s["max_chars"]))
        self.duck.set(DUCK, s["duck"])
        self.duck_level.show(int(s["duck_level"]))
        self.duck_level.widget.set_sensitive(s["duck"] == "lower")
        self.quiet.set_state(s["quiet"] == "on")
        self.widget.show_all()
        self.updating = False

    # -- changing ----------------------------------------------------------------------
    def set(self, key, value):
        if self.updating or value == "":
            return
        background(lambda: run(TTS, "set", key, str(value)), lambda _r: self.refresh())

    def switch(self, key, state):
        if not self.updating:
            self.set(key, "on" if state else "off")
        return False

    def on_assistant(self, _switch, state):
        if not self.updating:
            background(lambda: run(ASSISTANT, "set", "voice_reply", "on" if state else "off", timeout=20),
                       lambda _r: self.refresh())
        return False

    def download(self, name):
        if not name:
            return
        self.more_sub.set_text(f"Downloading {name} (about 60 MB)…")
        background(lambda: run(TTS, "download", name, timeout=900) or "",
                   lambda out: (self.more_sub.set_text(out.strip() or f"{name} did not download"),
                                self.refresh()))

    def stop(self):
        background(lambda: run(TTS, "stop"), lambda _r: self.refresh())

    def test(self, lang):
        text = self.test_text.get_text().strip()
        self.test_sub.set_text("Making it… (the first line loads the voice: about a second)")
        argv = [TTS, "test", "--lang", lang, "--json"] + ([text] if text else [])
        background(lambda: run_json(*argv, timeout=120), lambda r: (self.test_sub.set_text(test_line(r)),
                                                                   self.refresh()))
