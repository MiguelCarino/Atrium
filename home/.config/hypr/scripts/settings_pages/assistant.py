"""Settings page: the desktop assistant (assistant.py) -- on / off, which
local model answers, how many tools a question may use, the tools one by
one, what asks first, how long the conversation is kept (and Forget), the
Privacy switch that lets it into the desktop memory, spoken replies, and
what the launcher's "ask …" does first.

Everything is assistant.py's own settings (`assistant.py set KEY VALUE`,
read back with `assistant.py status --json`) except "Into the desktop
memory", which is Privacy's (`privacy_settings.py assistant memory on|off`).
The page keeps nothing itself: every control runs one of those and redraws
from what status says.
"""
import datetime
import os
import subprocess

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import GLib, Gtk  # noqa: F401,E402  (after common: it picks GTK 3)

PAGE = {"id": "assistant", "title": "Assistant", "icon": "", "group": "Apps", "order": 41,
        "keywords": ["assistant", "asistente", "chat", "ask", "pregunta", "local model", "ai", "ia",
                     "tools", "herramientas", "conversation", "history", "historial", "forget", "olvidar",
                     "voice reply", "speak", "confirm", "what was i doing", "compare windows"]}

ASSISTANT = os.path.join(HYPR, "assistant.py")  # noqa: F405  (HYPR: common)
PRIVACY = os.path.join(HYPR, "privacy_settings.py")  # noqa: F405
GROUP_ICONS = {"memory": "", "screen": "", "project": "", "actions": "",
               "windows": "", "sessions": "", "timers": "", "brief": "",
               "files": "", "repos": ""}
STEPS = [2, 3, 4, 6, 8, 10]
KEEP = [(0, "Not kept"), (1, "1 day"), (7, "7 days"), (30, "30 days"), (90, "90 days")]


# -- pure helpers (tests/test_assistant.py) ----------------------------------------------
def model_chips(roles):
    """(key, caption) for the model choice, naming each role's model now."""
    def name(role):
        r = (roles or {}).get(role) or {}
        if not r.get("name"):
            return role
        return r["name"] + ("" if r.get("local") else " -- not local: refused")
    return [("auto", "Automatic"), ("default", f"Default ({name('default')})"),
            ("quick", f"Quick ({name('quick')})"), ("worker", f"Worker ({name('worker')})")]


def history_text(history, days):
    """The line under the history choice: how much is kept now."""
    turns = (history or {}).get("turns") or 0
    if not days:
        return ("Nothing is written: the conversation lives only while the panel is open."
                + (f" {turns} older exchange(s) are still on disk until Forget." if turns else ""))
    if not turns:
        return f"Nothing kept yet. Exchanges older than {days} day(s) are dropped."
    since = datetime.datetime.fromtimestamp(history["since"]).strftime("%b %d %H:%M") if history.get("since") else "?"
    size = max(1, round((history.get("bytes") or 0) / 1024))
    return (f"{turns} exchange(s) kept since {since} ({size} KB, ~/.local/state/hypr/assistant). Only the "
            "words and the step lines: never pictures, file contents or tool results.")


def call(*cmd):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, (done.stderr or done.stdout).strip()


def put(switch, on):
    switch.set_active(on)
    switch.set_state(on)


def wrapped(text):
    lab = dp.label(text, "ctl-sub")  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    return lab


class Page:
    def __init__(self):
        self.updating = False
        self.data = None
        self.switches = {}
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

        w.pack_start(heading("DESKTOP ASSISTANT"), False, False, 0)  # noqa: F405
        w.pack_start(self.switch_row("enabled", "", "Assistant",
                                     "A chat that knows this desktop: it searches what you did, looks at the "
                                     "screen, reads a file you name and does desktop actions -- only through "
                                     "the tools below, with the LOCAL model. Nothing leaves the computer."),
                     False, False, 0)
        w.pack_start(links_row(link("Open the assistant", lambda: spawn(ASSISTANT, "open")),  # noqa: F405
                               link("AI & models", lambda: spawn(os.path.join(HYPR, "settings.py"), "ai"))),  # noqa: F405
                     False, False, 0)

        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("MODEL"), False, False, 0)  # noqa: F405
        self.model = Chips(lambda k: self.change(ASSISTANT, "set", "model", k))  # noqa: F405
        self.model.widget.set_max_children_per_line(2)
        w.pack_start(self.model.widget, False, False, 0)
        w.pack_start(wrapped("Automatic: the big default model when LM Studio has it loaded already, else the "
                             "quick one. Never a cloud model, never in gamemode, never one that would not fit on "
                             "the graphics card next to what is loaded -- it then says why instead."),
                     False, False, 0)
        w.pack_start(dp.label("Tools per question (each step shows in the chat)", "ctl-sub"), False, False, 0)  # noqa: F405
        self.steps = Chips(lambda k: self.change(ASSISTANT, "set", "max_steps", str(k)))  # noqa: F405
        self.steps.widget.set_max_children_per_line(6)
        w.pack_start(self.steps.widget, False, False, 0)

        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("TOOLS IT MAY USE"), False, False, 0)  # noqa: F405
        self.tool_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.tool_box, False, False, 0)

        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("ASKING FIRST"), False, False, 0)  # noqa: F405
        self.confirm = Chips(lambda k: self.change(ASSISTANT, "set", "confirm", k))  # noqa: F405
        self.confirm.widget.set_max_children_per_line(2)
        w.pack_start(self.confirm.widget, False, False, 0)
        w.pack_start(wrapped("Risky actions follow voice commands' rules: several windows, overwriting a session, "
                             "an app name that fits several apps. Restoring a session, closing any window and "
                             "opening a link always ask. Nothing that asks runs without your Confirm click."),
                     False, False, 0)

        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("CONVERSATION"), False, False, 0)  # noqa: F405
        self.keep = Chips(lambda k: self.change(ASSISTANT, "set", "history_days", str(k)))  # noqa: F405
        self.keep.widget.set_max_children_per_line(5)
        w.pack_start(self.keep.widget, False, False, 0)
        self.history_line = wrapped("")
        w.pack_start(self.history_line, False, False, 0)
        w.pack_start(self.switch_row("privacy:memory", "", "Into the desktop memory",
                                     "Each exchange also becomes a desktop memory (from the app \"Assistant\"), so "
                                     "\"remember …\" finds it. Off as shipped; needs Desktop memory and its "
                                     "Notifications source on (Privacy)."),
                     False, False, 0)
        w.pack_start(links_row(link("Forget the whole conversation", self.forget)), False, False, 0)  # noqa: F405

        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("VOICE AND LANGUAGE"), False, False, 0)  # noqa: F405
        self.voice_row = self.switch_row("voice_reply", "", "Speak the replies",
                                         "The answers read out loud by the desktop's text-to-speech voice.")
        w.pack_start(self.voice_row, False, False, 0)
        w.pack_start(dp.label("Answer in", "ctl-sub"), False, False, 0)  # noqa: F405
        self.language = Chips(lambda k: self.change(ASSISTANT, "set", "language", k))  # noqa: F405
        w.pack_start(self.language.widget, False, False, 0)
        w.pack_start(wrapped("Voice in: the microphone button in the chat (or `assistant.py open --voice`) -- voice "
                             "typing's own Whisper transcribes it (Voice typing & captions); the recording is "
                             "deleted at once."), False, False, 0)

        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("LAUNCHER"), False, False, 0)  # noqa: F405
        w.pack_start(dp.label("\"ask …\" / \"pregunta …\" goes first to", "ctl-sub"), False, False, 0)  # noqa: F405
        self.launcher = Chips(lambda k: self.change(ASSISTANT, "set", "launcher_ask", k))  # noqa: F405
        self.launcher.widget.set_max_children_per_line(2)
        w.pack_start(self.launcher.widget, False, False, 0)
        w.pack_start(wrapped("The other one is the second row. \"assistant\" / \"asistente\" alone opens the chat."),
                     False, False, 0)

    # -- building ----------------------------------------------------------------------
    def switch_row(self, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, on, k=key: self.flip(k, on))
        self.switches[key] = sw
        grid, sub_label = row(icon, title, sub, sw)  # noqa: F405
        grid.sub_label = sub_label
        return grid

    # -- changing things -----------------------------------------------------------------
    def flip(self, key, on):
        if key == "privacy:memory":
            return self.change(PRIVACY, "assistant", "memory", "on" if on else "off")
        return self.change(ASSISTANT, "set", key, "on" if on else "off")

    def forget(self):
        background(lambda: call(ASSISTANT, "clear"), self.changed)  # noqa: F405

    def change(self, *cmd):
        if self.updating:
            return True
        background(lambda: call(*cmd), self.changed)  # noqa: F405
        return True

    def changed(self, result):
        ok, why = result
        self.problem.set_text("" if ok else f"Not changed: {why}")
        self.problem.set_visible(not ok)
        self.refresh()

    # -- drawing ---------------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(ASSISTANT, "status", "--json", timeout=20), self.show)  # noqa: F405

    def show(self, data):
        if not data:
            self.problem.set_text("assistant.py status did not answer.")
            self.problem.set_visible(True)
            return
        self.data = data
        conf = data["settings"]
        self.updating = True
        try:
            put(self.switches["enabled"], conf["enabled"] == "on")
            put(self.switches["voice_reply"], conf["voice_reply"] == "on")
            put(self.switches["privacy:memory"], bool(data["privacy"]["assistant_memory"]))
            self.switches["privacy:memory"].set_sensitive(bool(data["privacy"]["memory_on"]))
            self.model.set(model_chips(data.get("roles")), conf["model"])
            self.steps.set([(n, str(n)) for n in sorted(set(STEPS) | {conf["max_steps"]})], conf["max_steps"])
            self.confirm.set([("risky", "Only risky actions"), ("all", "Every action")], conf["confirm"])
            self.keep.set(KEEP, conf["history_days"])
            self.language.set([("auto", "The question's language"), ("es", "Español"), ("en", "English")],
                              conf["language"])
            self.launcher.set([("assistant", "The assistant (chat)"), ("desktop", "Ask your desktop (notification)")],
                              conf["launcher_ask"])
            self.draw_tools(data)
        finally:
            self.updating = False
        self.history_line.set_text(history_text(data.get("history"), conf["history_days"]))
        self.voice_row.sub_label.set_text(
            "The answers read out loud by the desktop's text-to-speech voice. " +
            ("" if data.get("tts") else "No text-to-speech voice is installed yet: until one is, this does nothing."))
        self.widget.show_all()

    def draw_tools(self, data):
        conf = data["settings"]
        if not self.tool_box.get_children():
            for gid, info in data["tools"].items():
                grid = self.switch_row(f"tool_{gid}", GROUP_ICONS.get(gid, ""), info["title"], info["sub"])
                self.tool_box.pack_start(grid, False, False, 0)
        for gid in data["tools"]:
            put(self.switches[f"tool_{gid}"], conf[f"tool_{gid}"] == "on")
