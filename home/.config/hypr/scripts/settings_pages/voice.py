"""Settings page: voice typing and live captions (voice.py).

Everything goes through voice.py: `status --json` for what is going on (the
daemon, the engine, the card's free memory, gamemode) and the settings,
`set KEY VALUE` to change one, `captions on|off` for the switch. The page
keeps nothing of its own. The status is read in the background -- it runs
nvidia-smi and hyprctl -- so opening the page never waits on them.

"Try it" runs `voice.py selftest`: espeak-ng speaks a sentence in English
and one in Spanish into a file, and the page shows what came back and how
long it took. Nothing is recorded from the microphone for that.

Voice commands (voice-command.py): on / off, confirm everything, and their
language are voice.conf settings like the rest; "Show the plan" runs
`voice-command.py plan WORDS --json` on typed words -- understood and
checked, nothing done -- and shows the steps (plan_text()).
"""
import os

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "voice", "title": "Voice typing & captions", "icon": "\uf130", "group": "Apps", "order": 35, "parent": "ai", "tab": "Voice typing",
        "keywords": ["dictation", "dictado", "speech to text", "voz", "voice typing", "captions",
                     "subtitles", "subtítulos", "live captions", "whisper", "transcribe", "transcription",
                     "translate", "push to talk", "microphone typing", "voice commands",
                     "comandos de voz", "voice control", "control por voz", "speak to the desktop"]}

VOICE = os.path.join(HYPR, "voice.py")
COMMAND = os.path.join(HYPR, "voice-command.py")
# Font Awesome 6 Solid, as escapes (see audio_panel.py on why).
ICON_CC, ICON_CHIP, ICON_GLOBE, ICON_KEYBOARD = "\uf20a", "\uf2db", "\uf0ac", "\uf11c"
ICON_BOLT, ICON_CHECK = "\uf0e7", "\uf058"
LANGUAGES = [("auto", "Detect (Spanish / English)"), ("es", "Spanish"), ("en", "English")]
OUTPUTS = [("type", "Type it"), ("paste", "Paste it"), ("copy", "Clipboard only")]
DEVICES = [("auto", "Card, CPU if busy"), ("cuda", "Graphics card only"), ("cpu", "CPU only")]
IN_GAMES = [("off", "Pause it"), ("cpu", "Use the CPU")]


def engine_line(info):
    """The ENGINE row's sub line, from `voice.py status --json`."""
    if not info.get("installed"):
        return "Not installed (see Details)"
    w = info.get("worker")
    plan = info.get("plan") or [None, None, None, ""]
    free = info.get("gpu_free_mb")
    card = f"card: {free / 1024:.1f} GB free" if free is not None else "no NVIDIA card"
    if w:
        where = "graphics card" if w["device"] == "cuda" else "CPU"
        now = f"{w['model']} loaded on the {where}, unused for {w['idle_s'] // 60} min"
    elif plan[0]:
        where = "graphics card" if plan[0] == "cuda" else "CPU"
        now = f"Next use loads {plan[1]} on the {where}"
        if plan[0] == "cpu":
            now += f" ({plan[3]})"
    else:
        now = f"Paused: {plan[3]}"
    return f"{now}  ·  {card}"


def plan_text(data):
    """The "Show the plan" result, from `voice-command.py plan --json`."""
    if not isinstance(data, dict):
        return "voice-command.py did not answer"
    lines = [f"• {s['say']}" + (f"  (asks first: {s['confirm']})" if s.get("confirm") else "")
             for s in data.get("steps") or []]
    lines += [f"✗ {r}" for r in data.get("refused") or []]
    how = data.get("how") or "?"
    head = "Understood instantly" if how == "fast" else f"Understood by {how}" if how != "none" else "Not understood"
    return f"{head}:\n" + ("\n".join(lines) or "nothing to do")


def note(text):
    """A wrapped sub-styled paragraph (the details folds, the result lines)."""
    lab = dp.label(text, "ctl-sub")
    lab.set_line_wrap(True)
    lab.set_xalign(0)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.info = {}

        w.pack_start(heading("ENGINE"), False, False, 0)
        self.engine_row, self.engine_sub = row(ICON_CHIP, "Whisper, on this computer", "checking…",
                                              link("Put away now", self.unload))
        w.pack_start(self.engine_row, False, False, 0)
        w.pack_start(dp.label("Model on the graphics card", "ctl-sub"), False, False, 0)
        self.model = Chips(lambda key: self.set("model", key))
        w.pack_start(self.model.widget, False, False, 0)
        self.model_note = dp.label("", "ctl-sub")
        w.pack_start(self.model_note, False, False, 0)
        w.pack_start(dp.label("Where it runs", "ctl-sub"), False, False, 0)
        self.device = Chips(lambda key: self.set("device", key))
        w.pack_start(self.device.widget, False, False, 0)
        self.idle = Slider("idle_min", "Put the model away after unused",
                           1, 60, 1, " min", lambda key, value: self.set(key, value))
        w.pack_start(self.idle.widget, False, False, 0)
        more = details()
        more.box.pack_start(dp.label("Model on the CPU (when the card is busy, or set to CPU)", "ctl-sub"),
                            False, False, 0)
        self.cpu_model = Chips(lambda key: self.set("cpu_model", key))
        more.box.pack_start(self.cpu_model.widget, False, False, 0)
        more.box.pack_start(dp.label("During gamemode", "ctl-sub"), False, False, 0)
        self.in_games = Chips(lambda key: self.set("in_games", key))
        more.box.pack_start(self.in_games.widget, False, False, 0)
        self.engine_more = note("")
        more.box.pack_start(self.engine_more, False, False, 0)
        w.pack_start(more, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("VOICE TYPING"), False, False, 0)
        grid, _ = row(ICON_KEYBOARD, "SUPER+CTRL+V starts, again stops and types",
                      "Or hold SUPER+ALT+V to talk; the text goes to the cursor")
        w.pack_start(grid, False, False, 0)
        w.pack_start(dp.label("Language", "ctl-sub"), False, False, 0)
        self.language = Chips(lambda key: self.set("language", key))
        w.pack_start(self.language.widget, False, False, 0)
        w.pack_start(dp.label("The text", "ctl-sub"), False, False, 0)
        self.output = Chips(lambda key: self.set("output", key))
        w.pack_start(self.output.widget, False, False, 0)
        w.pack_start(details(note("Paste presses Ctrl+V, which terminals do not take (they want "
                                  "Ctrl+Shift+V): Type it works everywhere. For holding SUPER+ALT+V, let go "
                                  "of V first. The recording stays in memory and is deleted once it is text.")),
                     False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("LIVE CAPTIONS"), False, False, 0)
        self.captions = Gtk.Switch()
        self.captions.connect("state-set", self.on_captions)
        grid, self.captions_sub = row(ICON_CC, "Captions of what the computer plays",
                                      "SUPER+SHIFT+V · a strip at the bottom, click-through", self.captions)
        w.pack_start(grid, False, False, 0)
        self.translate = Gtk.Switch()
        self.translate.connect("state-set", lambda _s, state: self.switch("translate", state))
        grid, _ = row(ICON_GLOBE, "Translate to English",
                      "Captions in English, whatever is spoken", self.translate)
        w.pack_start(grid, False, False, 0)
        self.size = Slider("caption_size", "Caption text size", 14, 48, 1, " pt",
                           lambda key, value: self.set(key, value))
        w.pack_start(self.size.widget, False, False, 0)
        self.lines = Slider("caption_lines", "Lines kept on screen", 1, 4, 1, "",
                            lambda key, value: self.set(key, value))
        w.pack_start(self.lines.widget, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("VOICE COMMANDS"), False, False, 0)
        self.commands = Gtk.Switch()
        self.commands.connect("state-set", lambda _s, state: self.switch("commands", state))
        grid, _ = row(ICON_BOLT, "Do what I say",
                      "SUPER+CTRL+C listens, again does it (or hold SUPER+ALT+C)", self.commands)
        w.pack_start(grid, False, False, 0)
        self.confirm = Gtk.Switch()
        self.confirm.connect("state-set", lambda _s, state: self.switch("command_confirm", state))
        grid, _ = row(ICON_CHECK, "Confirm everything",
                      "Off: only risky or unclear commands ask first", self.confirm)
        w.pack_start(grid, False, False, 0)
        w.pack_start(dp.label("Language of commands", "ctl-sub"), False, False, 0)
        self.command_language = Chips(lambda key: self.set("command_language", key))
        w.pack_start(self.command_language.widget, False, False, 0)
        words = Gtk.Box(spacing=8)
        self.command_text = Gtk.Entry()
        self.command_text.set_placeholder_text("pon el navegador y la terminal lado a lado")
        self.command_text.set_hexpand(True)
        self.command_text.connect("activate", lambda _e: self.show_plan())
        words.pack_start(self.command_text, True, True, 0)
        words.pack_start(link("Show the plan", self.show_plan), False, False, 0)
        w.pack_start(words, False, False, 0)
        self.plan_sub = note("Type a command to see the plan; nothing is done")
        w.pack_start(self.plan_sub, False, False, 0)
        w.pack_start(details(note("Say things like \"Move Firefox to workspace 3\", \"no molestar durante una "
                                  "hora\", \"timer 10 minutes\". The local quick model understands it; a "
                                  "notification says what it will do, with Undo. Off, Confirm everything "
                                  "still asks before what closes, replaces or might be misheard.")),
                     False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("TRY IT"), False, False, 0)
        self.test_sub = note("A computer voice reads two sentences; the mic is not used")
        w.pack_start(self.test_sub, False, False, 0)
        w.pack_start(links_row(link("Run the test", self.selftest)), False, False, 0)

    # -- reading -----------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(VOICE, "status", "--json", timeout=20) or {}, self.show)

    def show(self, info):
        self.info = info
        s = info.get("settings") or {}
        if not s:
            self.engine_sub.set_text("voice.py did not answer")
            return
        notes = info.get("notes", {})
        choices = info.get("choices", {})
        self.updating = True
        self.engine_sub.set_text(engine_line(info))
        self.engine_more.set_text("Downloaded: " + (", ".join(info.get("models") or []) or "none")
                                  + ". Lives in ~/.local/share/voice/venv (pip install faster-whisper there).")
        self.model.set([(m, m) for m in choices.get("model", [])], s["model"])
        self.model_note.set_text(f"{s['model']}: {notes.get(s['model'], '')}")
        self.cpu_model.set([(m, m) for m in choices.get("cpu_model", [])], s["cpu_model"])
        self.device.set(DEVICES, s["device"])
        self.in_games.set(IN_GAMES, s["in_games"])
        self.language.set(LANGUAGES, s["language"])
        self.output.set(OUTPUTS, s["output"])
        self.idle.show(int(s["idle_min"]))
        self.size.show(int(s["caption_size"]))
        self.lines.show(int(s["caption_lines"]))
        self.translate.set_state(s["translate"] == "on")
        self.commands.set_state(s.get("commands", "on") == "on")
        self.confirm.set_state(s.get("command_confirm", "off") == "on")
        self.command_language.set(LANGUAGES, s.get("command_language", "auto"))
        self.captions.set_state(bool(info.get("captions")))
        self.widget.show_all()
        self.updating = False

    # -- changing ----------------------------------------------------------------------
    def set(self, key, value):
        if self.updating:
            return
        background(lambda: run(VOICE, "set", key, str(value)), lambda _r: self.refresh())

    def switch(self, key, state):
        if not self.updating:
            self.set(key, "on" if state else "off")
        return False

    def on_captions(self, _switch, state):
        if not self.updating:
            self.captions_sub.set_text("starting…" if state else "stopping…")
            background(lambda: run(VOICE, "captions", "on" if state else "off", timeout=120),
                       lambda _r: self.refresh())
        return False

    def unload(self):
        background(lambda: run(VOICE, "unload", timeout=20), lambda _r: self.refresh())

    def show_plan(self):
        text = self.command_text.get_text().strip()
        if not text:
            return
        self.plan_sub.set_text("Understanding…")
        background(lambda: run_json(COMMAND, "plan", text, "--json", timeout=180), self.show_plan_result)

    def show_plan_result(self, data):
        self.plan_sub.set_text(plan_text(data))

    def selftest(self):
        # selftest --json prints one object per line: read by hand, not run_json.
        self.test_sub.set_text("Running…")

        def work():
            lines = []
            for line in run(VOICE, "selftest", "--json", timeout=600).splitlines():
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    pass
            return lines

        background(work, self.show_results)

    def show_results(self, results):
        if not results:
            self.test_sub.set_text("The test did not run (is espeak-ng installed?)")
            return
        parts = []
        for r in results:
            if r.get("error"):
                parts.append(f"{r['said']}  →  {r['error']}")
            else:
                parts.append(f"“{r['said']}”  →  “{r.get('text', '')}”  ({r.get('language', '?')}, "
                             f"{r.get('audio_s', 0)} s of speech in {r.get('secs', 0)} s on "
                             f"{'the card' if r.get('device') == 'cuda' else 'the CPU'})")
        self.test_sub.set_text("\n".join(parts))
        self.refresh()
