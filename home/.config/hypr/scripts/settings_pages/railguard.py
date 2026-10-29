"""Settings page: Railguard -- what keeps a runaway program from freezing
the desktop (railguard.py; its docstring explains the layers).

Top to bottom:

    NOW           RAM free, VRAM in use, what would go first; End the
                  runaway now (the panic key's action), Stop all agent
                  commands
    WATCH         RAM and VRAM on / off, how low RAM may get, how full VRAM
                  may get, spare games, a notification each time it acts
                  (the mascot on it: Settings > Notifications)
    LIMITS        one agent command, all of them, heavy builds (heavy.slice)
    EXCEPTIONS    never end / end first: process names, added and removed
    WHAT IT DID   the last actions (railguard.py history)

The page keeps nothing itself: every control runs railguard.py and redraws
from `railguard.py status --json`.
"""
import os
import time

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import Gtk  # noqa: E402  (after common: it picks GTK 3)

PAGE = {"id": "railguard", "title": "Railguard", "icon": "", "group": "System", "order": 25,
        "keywords": ["freeze", "frozen", "hang", "out of memory", "oom", "memory", "ram", "vram",
                     "gpu memory", "runaway", "kill", "panic", "watchdog", "limits", "agents",
                     "claude", "build", "compile", "games", "congelado", "memoria"]}

RAILGUARD = os.path.join(HYPR, "railguard.py")  # noqa: F405  (HYPR: common)
RAM_FREE = [2, 3, 4, 6, 8]
VRAM_FULL = [90, 95, 97, 99]
COMMAND_GB = [8, 12, 16, 24, 32]
AGENTS_GB = [12, 16, 20, 24, 28]
HEAVY_GB = [16, 20, 24, 28]
SWITCHES = [("ram", "", "Watch the memory",
             "Ends the biggest runaway before the desktop freezes."),
            ("vram", "", "Watch the GPU's memory",
             "Ends what fills it -- never the screen itself."),
            ("spare_games", "", "Spare games",
             "A game filling the GPU only gets a warning; something else goes."),
            ("notify", "", "Tell me when it acts",
             "A notification each time. Off: only the history below.")]
KIND_ICONS = {"memory": "", "vram": "", "panic": "", "game-vram": "",
              "stuck": "", "agents": ""}
LISTS = [("never_kill", "", "Never end", "Names railguard must leave alone (\"obs\", \"blender\")."),
         ("kill_first", "", "End first", "Names that go before anything else (\"ollama\").")]


# -- words (pure) ---------------------------------------------------------------------------------
def now_text(st):
    if not st.get("running"):
        return "The watchdog is not running: systemctl --user enable --now railguard"
    bits = [f"{st['ram_free_pct']:.0f}% of RAM free"]
    if st.get("vram_gb"):
        bits.append(f"VRAM {st['vram_gb'][0]:g} of {st['vram_gb'][1]:g} GB")
    out = "  ·  ".join(bits)
    f = st.get("first_to_go")
    if f:
        out += f"\nFirst to go if memory runs out: {f['name']} ({f['gb']:g} GB)"
    return out


def entry_title(e):
    return {"memory": "Ended a memory runaway", "vram": "Ended a GPU memory runaway",
            "panic": "Ended by the panic key", "game-vram": "Game filled the GPU (kept)",
            "stuck": "Memory ran short, nothing to end",
            "agents": "Stopped all agent commands"}.get(e.get("kind"), e.get("kind", "?"))


def entry_sub(e, now=None):
    now = now if now is not None else time.time()
    bits = []
    if e.get("name"):
        bits.append(f"{e['name']}, {e.get('vram_gb', e.get('gb', 0)):g} GB")
    if e.get("why"):
        bits.append(e["why"])
    bits.append(ago(int(now - e.get("time", now))))  # noqa: F405
    return "  ·  ".join(bits)


def call(*cmd, timeout=30):
    import subprocess
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr or done.stdout).strip()


def put(switch, on):
    switch.set_active(on)
    switch.set_state(on)


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    lab.set_xalign(0)
    return lab


def sysrq_on():
    try:
        with open("/proc/sys/kernel/sysrq") as fh:
            v = int(fh.read().strip())
    except (OSError, ValueError):
        return False
    return v == 1 or v & 64 == 64


class Page:
    def __init__(self):
        self.updating = False
        self.data = None
        self.switches = {}
        self.list_boxes = {}
        self.entries = {}
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

        # -- now ----------------------------------------------------------------------------------
        w.pack_start(heading("NOW"), False, False, 0)  # noqa: F405
        self.now = wrapped("")
        w.pack_start(self.now, False, False, 0)
        w.pack_start(links_row(  # noqa: F405
            link("End the runaway now", lambda: self.change(RAILGUARD, "panic")),  # noqa: F405
            link("Stop all agent commands", lambda: self.change(RAILGUARD, "stop-agents"))),  # noqa: F405
            False, False, 0)
        w.pack_start(wrapped("The same as SUPER+CTRL+ALT+Escape. Agent sessions, terminals and "
                             "the screen are never ended."), False, False, 0)

        # -- watch --------------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("WATCH"), False, False, 0)  # noqa: F405
        for key, icon, title, sub in SWITCHES:
            w.pack_start(self.switch_row(key, icon, title, sub), False, False, 0)
        w.pack_start(dp.label("Act when free RAM is under", "ctl-sub"), False, False, 0)  # noqa: F405
        self.ram_chips = Chips(lambda k: self.change(RAILGUARD, "set", "ram_free_pct", k))  # noqa: F405
        self.ram_chips.widget.set_max_children_per_line(5)
        w.pack_start(self.ram_chips.widget, False, False, 0)
        w.pack_start(dp.label("Act when the GPU's memory is fuller than", "ctl-sub"), False, False, 0)  # noqa: F405
        self.vram_chips = Chips(lambda k: self.change(RAILGUARD, "set", "vram_pct", k))  # noqa: F405
        self.vram_chips.widget.set_max_children_per_line(4)
        w.pack_start(self.vram_chips.widget, False, False, 0)

        # -- limits -------------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("LIMITS"), False, False, 0)  # noqa: F405
        w.pack_start(wrapped("Past its limit only that job ends -- never the desktop or a session."),
                     False, False, 0)
        self.limit_chips = {}
        for key, words, values in (("agent_command_gb", "One command an agent runs", COMMAND_GB),
                                   ("agents_gb", "Everything agents run, together", AGENTS_GB),
                                   ("heavy_gb", "Builds you start (make, cargo, heavy …)", HEAVY_GB)):
            w.pack_start(dp.label(words, "ctl-sub"), False, False, 0)  # noqa: F405
            chips = Chips(lambda k, key=key: self.change(RAILGUARD, "set", key, k))  # noqa: F405
            chips.widget.set_max_children_per_line(5)
            chips.values = values
            self.limit_chips[key] = chips
            w.pack_start(chips.widget, False, False, 0)

        # -- exceptions ---------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("EXCEPTIONS"), False, False, 0)  # noqa: F405
        for key, icon, title, sub in LISTS:
            entry = Gtk.Entry()
            entry.set_placeholder_text("process name")
            entry.set_width_chars(16)
            entry.connect("activate", lambda e, k=key: self.add(k, e))
            self.entries[key] = entry
            grid, _sub = row(icon, title, sub, entry)  # noqa: F405
            w.pack_start(grid, False, False, 0)
            box = Gtk.FlowBox()
            box.set_selection_mode(Gtk.SelectionMode.NONE)
            box.set_max_children_per_line(6)
            box.set_column_spacing(4)
            self.list_boxes[key] = box
            w.pack_start(box, False, False, 0)

        # -- history ------------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("WHAT IT DID"), False, False, 0)  # noqa: F405
        self.history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.history_box, False, False, 0)

        self.more = details(label="Details")  # noqa: F405
        self.more_words = wrapped("")
        self.more_words.set_selectable(True)
        self.more.box.pack_start(self.more_words, False, False, 0)
        w.pack_start(self.more, False, False, 0)

    # -- building ---------------------------------------------------------------------------------
    def switch_row(self, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, on, k=key: self.flip(k, on))
        self.switches[key] = sw
        grid, sub_label = row(icon, title, sub, sw)  # noqa: F405
        return grid

    # -- changing things --------------------------------------------------------------------------
    def flip(self, key, on):
        if self.updating:
            return True
        return self.change(RAILGUARD, "set", key, "on" if on else "off")

    def add(self, key, entry):
        name = entry.get_text().strip()
        if name:
            entry.set_text("")
            self.change(RAILGUARD, "add", key, name)

    def change(self, *cmd, timeout=30):
        if self.updating:
            return True
        background(lambda: call(*cmd, timeout=timeout), self.changed)  # noqa: F405
        return True

    def changed(self, result):
        ok, why = result
        self.problem.set_text("" if ok else f"Not done: {why}")
        self.problem.set_visible(not ok)
        self.refresh()

    # -- drawing ------------------------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(RAILGUARD, "status", "--json", timeout=30), self.show)  # noqa: F405

    def show(self, st):
        if not st:
            self.problem.set_text("Could not read railguard's status")
            self.problem.set_tooltip_text(f"Try it in a terminal: {RAILGUARD} status")
            self.problem.set_visible(True)
            self.widget.show_all()
            return
        self.data = st
        conf = st["settings"]
        self.updating = True
        try:
            for key, *_ in SWITCHES:
                put(self.switches[key], conf[key])
            self.ram_chips.set([(str(n), f"{n} %") for n in sorted(set(RAM_FREE) | {int(conf["ram_free_pct"])})],
                               str(int(conf["ram_free_pct"])))
            self.vram_chips.set([(str(n), f"{n} %") for n in sorted(set(VRAM_FULL) | {int(conf["vram_pct"])})],
                                str(int(conf["vram_pct"])))
            for key, chips in self.limit_chips.items():
                chips.set([(str(n), f"{n} GB") for n in sorted(set(chips.values) | {int(conf[key])})],
                          str(int(conf[key])))
        finally:
            self.updating = False
        self.now.set_text(now_text(st))
        for key, box in self.list_boxes.items():
            clear(box)  # noqa: F405
            for name in conf[key]:
                b = link(f"{name}  ✕", lambda n=name, k=key: self.change(RAILGUARD, "remove", k, n))  # noqa: F405
                b.set_tooltip_text(f"Take {name} off the list")
                box.add(b)
        clear(self.history_box)  # noqa: F405
        hist = st.get("history") or []
        if not hist:
            self.history_box.pack_start(wrapped("Nothing yet -- it has not had to step in."), False, False, 0)
        for e in hist[:15]:
            grid, sub = row(KIND_ICONS.get(e.get("kind"), ""), entry_title(e), entry_sub(e))  # noqa: F405
            sub.set_selectable(True)
            self.history_box.pack_start(grid, False, False, 0)
        sysrq = ("Alt+SysRq+F (the kernel's own version, for when nothing on screen answers) is on."
                 if sysrq_on() else
                 "Alt+SysRq+F is OFF: run Atrium's system/railguard/install.sh once with sudo.")
        self.more_words.set_text(
            f"{sysrq}\n\nAgents' commands run in agents.slice (Claude Code's "
            "CLAUDE_CODE_SHELL_PREFIX = ~/.config/hypr/scripts/railguard-run); builds typed in a "
            "shell run in heavy.slice (railguard-shell.sh, sourced by ~/.bashrc; `heavy CMD` for "
            "anything else, `command make` to skip it).\n\n"
            f"Settings: ~/.local/state/hypr/railguard.json  ·  journal: journalctl --user -u railguard"
            f"\n{RAILGUARD} status shows everything in a terminal.")
        self.widget.show_all()
