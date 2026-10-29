"""Settings page: local AI models (LM Studio) and the graphics card's memory
-- what is on the card and who put it there, the loaded and installed
models with a "Fits?" for each, which model does what (the chat window, ??
quick answers, a worker), the context and slots a model is loaded with,
and whether a game clears the card.

Everything goes through two scripts; the page reads them back after every
change:

    llm-gpu.py status --json     the card (gpu.py), lms ps, the installed
                                 models with the fit calculator's verdict,
                                 the gamemode switches (llm-gpu.conf)
    llm-gpu.py load | unload | set ...
    llm_models.py set KEY VALUE  the roles, the context and the slots
                                 (llm.json, which the launcher and the
                                 chat window read)
    llm_models.py refresh        lms ls again, when a model was added or
                                 deleted since the list was kept
    llm-limits.py status --json  LM Studio's RAM / CPU limits, and its use
                                 against them, inside lmstudio.service or not
    llm-limits.py set | adopt    a limit (written to the unit's drop-in and
                                 set live); a daemon started outside the
                                 unit restarted inside it
    llm-bench.py run             the benchmark ("Run again": through
                                 systemd-run --user, unit llm-bench, so the
                                 page never waits on it); its results are
                                 read from llm-bench.json

Load refuses a model that would not fit next to what is on the card now;
the page then asks before loading it anyway. Nothing here starts LM Studio
except a Load (and Restart under the limits, which restarts one already
running).
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import llm_models  # noqa: E402  (hypr/scripts, on the path via settings.py; no GTK)

PAGE = {"id": "ai", "title": "AI & assistant", "icon": "", "group": "Apps", "order": 25, "tab": "Models",
        "keywords": ["llm", "ai", "model", "models", "gpu", "vram", "graphics memory", "lm studio", "local",
                     "llm chat", "chat window", "chat notifications", "ollama", "llama.cpp", "vllm", "openai",
                     "server", "api key", "gemma", "qwen", "glm", "claude", "context", "quick answers",
                     "inteligencia"]}

LLM_GPU = os.path.join(HYPR, "llm-gpu.py")
LLM_MODELS = os.path.join(HYPR, "llm_models.py")     # not executable: run with python3
SETTINGS = os.path.join(HYPR, "settings.py")
LLM_BENCH = os.path.join(HYPR, "llm-bench.py")
LLM_LIMITS = os.path.join(HYPR, "llm-limits.py")
RAM_STEPS = [8, 12, 16, 20, 24]
CPU_STEPS = [25, 50, 75]
BENCH_UNIT = "llm-bench"
CONTEXTS = [16384, 24576, 32768, 49152, 65536, 131072]
SLOTS = [1, 2, 4]
ROLES = [("default", "", "The chat window and ? asks",
          "the LLM chat window and the launcher's \"?question\""),
         ("quick", "", "?? quick answers",
          "a few sentences in the launcher"),
         ("worker", "", "Worker",
          "bulk text jobs for coding agents; never pushes other models off")]
ROLES_MORE = ("?? quick answers: a local model here gives way to haiku (with Claude Code installed) when it "
              "would not fit on the card next to what is loaded, or while a game runs. Worker: the local "
              "worker a coding agent hands bulk text jobs to over MCP (llm-worker.py).")
VERDICT_CLASS = {"fits": "", "tight": "warning", "won't fit": "critical"}


# llm-chat.py's own state file: its notifications toggle ("notify", on
# unless set off; the open window reads it at each notification).
FRONT_STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                           "hypr", "llm-chat.json")


def front_notify(path=None):
    try:
        with open(path or FRONT_STATE) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return True
    return not (isinstance(data, dict) and data.get("notify") is False)


def set_front_notify(on, path=None):
    """Only the "notify" key changes: the rest is the window's (corner,
    permissions)."""
    path = path or FRONT_STATE
    try:
        with open(path) as handle:
            data = json.load(handle)
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["notify"] = bool(on)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def gbs(n):
    return f"{(n or 0) / 1e9:.1f} GB"


def k(tokens):
    return f"{(tokens or 0) // 1024}k"


def minutes(seconds):
    if seconds is None:
        return "stays loaded"
    if seconds < 90:
        return f"unloads in {seconds} s if unused"
    return f"unloads in {seconds // 60} min if unused"


def loaded_sub(m, default_parallel=4):
    slots = m.get("parallel")
    bits = [gbs(m["size"]), f"{k(m.get('context'))} context" if m.get("context") else "",
            f"{slots} slots" if slots else "", m.get("status") or "", minutes(m.get("ttl_left"))]
    return "  ·  ".join(b for b in bits if b)


def installed_sub(m, ctx):
    bits = [m.get("params"), m.get("quant"), gbs(m["size"]), "tool use" if m.get("tools") else "no tool use",
            f"up to {k(m['max_context'])} context" if m.get("max_context") else ""]
    return "  ·  ".join(b for b in bits if b)


def fit_text(m):
    f = m.get("fit")
    if not f:
        return "?"
    if f["verdict"] == "won't fit":
        return f"won't fit: needs {gbs(f['need'])} of {gbs(f['room'])} (slow)"
    return f"{f['text']}: {gbs(f['need'])} of {gbs(f['room'])}"


def role_choices(current, installed):
    """[(name, caption)] for a role's dropdown: the Claude names (only with
    Claude Code installed), the installed local models, and the current one
    if it is neither (a model deleted since, or Claude's without it)."""
    out = [(m.name, f"{m.label} (Claude)") for m in llm_models.CLAUDE] if llm_models.claude_available() else []
    out += [(m["alias"], f"{m['alias']} (local, {gbs(m['size'])})") for m in installed]
    if current and current not in [n for n, _ in out]:
        claude = current in [m.name for m in llm_models.CLAUDE] or current.startswith("claude-")
        out.append((current, f"{current} (Claude Code is not installed)" if claude else
                    f"{current} (the server's)" if current.startswith(llm_models.SERVER_PREFIX) else
                    f"{current} (not installed)"))
    return out


def context_chips(current):
    return [(str(c), k(c)) for c in sorted(set(CONTEXTS) | {current})]


def slot_chips(current, default_parallel):
    values = sorted(set(SLOTS) | ({current} if current else set()))
    return [("auto", f"LM Studio's ({default_parallel})")] + [(str(s), str(s)) for s in values]


def ram_chips(current, default, total):
    """[(key, caption)] for the RAM limit: none, the steps that fit in this
    machine's RAM, the default and the current one."""
    values = {v for v in RAM_STEPS if v <= total} | {default} | ({current} if current else set())
    return [("0", "no limit")] + [(str(v), f"{v} GB" + (" (half)" if v == default else ""))
                                  for v in sorted(values)]


def cpu_chips(current, cpus):
    values = set(CPU_STEPS) | ({current} if current else set())
    return [("0", "no limit")] + [(str(v), f"{v} %  ({max(1, round(v * cpus / 100))} threads)")
                                  for v in sorted(values)]


def limits_line(s):
    """The live line under the limits: where LM Studio runs, its memory and
    CPU against them."""
    lim = s["limits"]
    if not s["unit"]:
        return "No limits: LM Studio's service is not installed"
    if s["where"] == "none":
        return "LM Studio is not running; it starts inside these limits"
    use = s.get("usage") or {}
    cpu = f", CPU {use['cpu_pct']:.0f} %" if use.get("cpu_pct") is not None else ""
    if s["where"] == "outside":
        who = "the LM Studio app" if s["app"] else "a terminal `lms` or the app"
        return (f"!  Running outside the limits (started by {who}): {gbs_gib(use.get('current'))} "
                f"in use{cpu}" + ("" if s["app"] else " -- restart it under them in Details"))
    limit = f" of {lim['ram_limit_gb']} GB" if lim["ram_limit_gb"] else ""
    text = f"Using {gbs_gib(use.get('current'))}{limit}{cpu}"
    if s.get("oom_kills"):
        text += f"  !  The RAM limit ended a model {s['oom_kills']} time(s)"
    if lim["llm_low_priority"] and (s.get("nice") or 0) < 10:
        text += "  ·  low priority from the next start"
    elif not lim["llm_low_priority"] and (s.get("nice") or 0) > 0:
        text += "  ·  normal priority from the next start"
    return text


def gbs_gib(n):
    return f"{(n or 0) / 1024 ** 3:.1f} GB"


def _bench_module():
    spec = importlib.util.spec_from_file_location("llm_bench", LLM_BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    llm_bench = _bench_module()     # no GTK, no lms at import: its table and results file
except (OSError, SyntaxError, ImportError):
    llm_bench = None

ROLE_TITLES = {role: title for role, _icon, title, _sub in ROLES}
ROLE_ICONS = {role: icon for role, icon, _title, _sub in ROLES}


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_bench():
    """(results, running): llm-bench.json and whether a run is going on now
    (its pid alive, or the systemd unit active). Blocking: background()."""
    data = llm_bench.read_results() if llm_bench else {}
    unit = run("systemctl", "--user", "is-active", BENCH_UNIT, timeout=5).strip() in ("active", "activating")
    going = data.get("running") or {}
    return data, unit or pid_alive(going.get("pid"))


def bench_when(data, now=None):
    """"run 2 h ago, took 31 min (quick)" for the results, or ""."""
    if not data.get("time"):
        return ""
    now = time.time() if now is None else now
    took = data.get("took_s")
    return (f"run {ago(int(now - data['time']))}" + (f", took {took // 60} min" if took else "")
            + (" (quick)" if data.get("quick") else ""))


def attempt(*cmd, timeout=180):
    """(ok, message): its own complaint from stderr when it failed."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)
    lab.set_line_wrap(True)
    return lab


def bar(pct, lvl=""):
    """The disk panel's usage bar, as on the Storage page."""
    b = Gtk.LevelBar.new_for_interval(0, 100)
    b.set_mode(Gtk.LevelBarMode.CONTINUOUS)
    for offset in ("low", "high", "full"):
        b.remove_offset_value(offset)
    b.set_value(max(0, min(100, pct)))
    style = b.get_style_context()
    style.add_class("dk-bar")
    if lvl:
        style.add_class(lvl)
    b.set_hexpand(True)
    b.set_valign(Gtk.Align.CENTER)
    return b


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        self.updating = False
        self.refreshed_list = False
        # The last command's complaint, and (for a refused Load) the button
        # that loads anyway; until the next command.
        self.message_box = Gtk.Box(spacing=8)
        self.message_box.set_no_show_all(True)
        w.pack_start(self.message_box, False, False, 0)

        w.pack_start(heading("GRAPHICS CARD"), False, False, 0)
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.card, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("LOADED MODELS"), False, False, 0)
        self.loaded = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.loaded, False, False, 0)
        self.unload_all = link("Unload all", lambda: self.do(LLM_GPU, "unload", "--all"))
        w.pack_start(links_row(self.unload_all), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("INSTALLED MODELS"), False, False, 0)
        self.installed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.installed, False, False, 0)
        w.pack_start(links_row(link("Look for new models", self.relist)), False, False, 0)
        w.pack_start(details(wrapped("\"Fits?\" is the model, its KV cache for the context below, 0.5 GB of "
                                     "working space and 2 GB kept for the desktop, against the card's memory; a "
                                     "model that does not fit is loaded partly into RAM by LM Studio, and every "
                                     "answer is slow. The cache is worked out from the model file's own header."),
                             links_row(link("Open the models folder", lambda: spawn(
                                 "xdg-open", llm_models.LMS_MODELS)))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WHICH MODEL DOES WHAT"), False, False, 0)
        self.roles = {}
        for role, icon, title, sub in ROLES:
            combo = Gtk.ComboBoxText()
            combo.connect("changed", lambda c, r=role: self.pick_role(r, c))
            grid, _ = row(icon, title, sub, combo)
            self.roles[role] = combo
            w.pack_start(grid, False, False, 0)
        w.pack_start(details(wrapped(ROLES_MORE)), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("CONTEXT AND SLOTS"), False, False, 0)
        grid, self.ctx_sub = row("", "Context", "")
        w.pack_start(grid, False, False, 0)
        self.ctx = self.make_chips(lambda key: None if self.updating else
                                   self.do("python3", LLM_MODELS, "set", "context", key))
        w.pack_start(self.ctx.widget, False, False, 0)
        grid, self.slot_sub = row("", "Slots", "")
        w.pack_start(grid, False, False, 0)
        self.slots = self.make_chips(lambda key: None if self.updating else
                                     self.do("python3", LLM_MODELS, "set", "parallel", key))
        w.pack_start(self.slots.widget, False, False, 0)
        w.pack_start(details(wrapped(
            "Context is what a local model is loaded with for the chat window and the rest; LM Studio's own "
            "default, 8k, is too small for a chat with tools. It is used the next time a model is loaded (one "
            "loaded already with at least this much is used as it is). More context, more of the card for "
            "the KV cache. Slots are answers at once (the chat, the assistant, background calls) sharing one "
            "pool of context: each is sure of its share, and one alone can use it all.")), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("LIMITS"), False, False, 0)
        self.limits = None
        grid, self.ram_sub = row("\uf538", "RAM limit", "")
        w.pack_start(grid, False, False, 0)
        self.ram = self.make_chips(lambda key: self.set_limit("ram_limit_gb", key))
        w.pack_start(self.ram.widget, False, False, 0)
        grid, self.cpu_sub = row("\uf3fd", "CPU limit", "")
        w.pack_start(grid, False, False, 0)
        self.cpu = self.make_chips(lambda key: self.set_limit("cpu_limit_pct", key))
        w.pack_start(self.cpu.widget, False, False, 0)
        self.low = Gtk.Switch()
        self.low.connect("state-set", lambda _s, state: self.switched_low(state))
        grid, _ = row("\uf06c", "Give way to the desktop",
                      "low priority for LM Studio, so the desktop stays smooth", self.low)
        w.pack_start(grid, False, False, 0)
        self.limits_live = wrapped("checking…")
        w.pack_start(self.limits_live, False, False, 0)
        self.adopt = link("Restart under the limits", lambda: self.do(
            LLM_LIMITS, "adopt", busy="restarting LM Studio under the limits…"))
        self.adopt.set_no_show_all(True)
        w.pack_start(details(wrapped(
            "The RAM limit covers LM Studio and its models together: past it, the model is ended and its load "
            "says so, instead of the whole desktop freezing while memory runs out. A model on the card needs "
            "far less RAM than its size; one that spills to RAM needs most of it. The CPU limit is the most it "
            "may use at once, even when the rest is idle (it matters for a model partly in RAM). Low priority "
            "is CPU and disk weight 20 of 100, nice 10. Use counts file cache it can drop. Restart under the "
            "limits shows when LM Studio was started outside lmstudio.service (the models are unloaded, and "
            "load again when asked for)."), links_row(self.adopt)), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("GAMES"), False, False, 0)
        self.switches = {}
        for key, icon, title, sub in (
                ("unload_for_games", "", "Unload the models when gamemode turns on",
                 "frees the card for ALT+SHIFT+G or a Steam game"),
                ("reload_after_games", "", "Load them again when it turns off",
                 "off: they load the next time they are asked for")):
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.switched(k, state))
            grid, _sub = row(icon, title, sub, sw)
            self.switches[key] = sw
            w.pack_start(grid, False, False, 0)
        self.games = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.games, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("BENCHMARK"), False, False, 0)
        self.bench = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.bench, False, False, 0)
        self.bench_run = link("Run again", self.run_bench)
        w.pack_start(links_row(self.bench_run), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("LLM CHAT WINDOW"), False, False, 0)
        self.front_notify = Gtk.Switch()
        self.front_notify.set_active(front_notify())
        self.front_notify.connect("state-set", lambda _s, state: set_front_notify(state) and False)
        grid, _ = row("\uf0f3", "Notify when the chat is in the background",
                      "finished answers, and permissions it waits for", self.front_notify)
        w.pack_start(grid, False, False, 0)
        # One more OpenAI-compatible server next to LM Studio: its models in
        # the chat window's picker (Ctrl+M). Saved on Enter or on leaving the
        # box, in llm.json (with a key: mode 600) -- in this process, so the
        # key never shows in a process list.
        conf = llm_models.settings()
        self.server_url = Gtk.Entry()
        self.server_url.set_width_chars(34)
        self.server_url.set_placeholder_text("http://localhost:11434/v1")
        self.server_url.set_text(conf.get("server_url") or "")
        grid, _ = row("\uf233", "OpenAI-compatible server",
                      "Ollama, llama.cpp, vLLM or a remote one; empty: none", self.server_url)
        w.pack_start(grid, False, False, 0)
        self.server_key = Gtk.Entry()
        self.server_key.set_width_chars(34)
        self.server_key.set_visibility(False)
        self.server_key.set_placeholder_text("•••• (set)" if conf.get("server_key") else "none")
        grid, _ = row("\uf084", "Its API key",
                      "only if the server wants one; \"none\" removes it", self.server_key)
        w.pack_start(grid, False, False, 0)
        for entry, key in ((self.server_url, "server_url"), (self.server_key, "server_key")):
            entry.connect("activate", lambda e, k=key: self.save_server(k, e))
            entry.connect("focus-out-event", lambda e, _ev, k=key: self.save_server(k, e))
        w.pack_start(details(wrapped(
            "Notifications come when the chat is in the background: a finished or failed answer, and a "
            "permission the model is waiting for (that one even in Do Not Disturb). The window's permission "
            "mode -- Ask me, Auto, Accept edits, Plan -- is its Ctrl+P menu. The server's models show in the "
            "chat window's model menu (Ctrl+M) next to LM Studio's: Ollama is http://localhost:11434/v1, "
            "llama.cpp's llama-server http://localhost:8080/v1. The key is kept in llm.json (yours only) and "
            "sent to that server only, as a Bearer token; $LLM_SERVER_KEY wins over it.")), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("ASK YOUR DESKTOP"), False, False, 0)
        w.pack_start(wrapped("The launcher's \"ask ...\" answers about your files and activity, locally"),
                     False, False, 0)
        w.pack_start(links_row(link("Open Privacy", lambda: spawn(SETTINGS, "privacy"))), False, False, 0)

    # -- building blocks -------------------------------------------------------------
    @staticmethod
    def make_chips(on_pick):
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(7)
        chips.widget.set_halign(Gtk.Align.START)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 7)))
        chips.set = set_items
        return chips

    def say(self, text, action=None):
        """The message line at the top; `action` an extra (caption, fn)."""
        clear(self.message_box)
        if text:
            self.message_box.pack_start(wrapped(text), True, True, 0)
            if action:
                self.message_box.pack_start(link(action[0], action[1]), False, False, 0)
            self.message_box.show_all()
        self.message_box.set_visible(bool(text))

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd, busy=""):
        if busy:
            self.say(busy)
        background(lambda: attempt(*cmd), lambda result: self.done(result, cmd))

    def done(self, result, cmd):
        ok, text = result
        if not ok and cmd[1:2] == ("load",) and "spill" in text:
            self.say(f"!  {text}", ("Load anyway", lambda: self.do(
                *cmd, "--force", busy=f"loading {cmd[2]} anyway…")))
        else:
            self.say("" if ok else f"!  {text}")
        self.refresh()

    def load(self, alias):
        self.do(LLM_GPU, "load", alias, busy=f"loading {alias}… (a big model takes up to a minute)")

    def save_server(self, key, entry):
        """server_url / server_key from its box (a key box left empty keeps
        the key there is). The message line says what happened."""
        value = entry.get_text().strip()
        if key == "server_key" and not value:
            return False
        if key == "server_url" and value == (llm_models.settings().get("server_url") or ""):
            return False
        try:
            llm_models.set_option(key, value or "none")
        except (ValueError, OSError) as exc:
            self.say(f"!  {exc}")
            return False
        if key == "server_key":
            entry.set_text("")
            entry.set_placeholder_text("none" if value == "none" else "•••• (set)")
            self.say("API key removed" if value == "none" else "API key saved (llm.json, yours only)")
        else:
            self.say(f"server: {value}" if value else "no server: LM Studio only")
        return False

    def pick_role(self, role, combo):
        name = combo.get_active_id()
        if self.updating or not name or not self.data or name == self.data["roles"].get(role):
            return
        self.do("python3", LLM_MODELS, "set", role, name)

    def switched(self, key, state):
        if not self.updating:
            self.do(LLM_GPU, "set", key, "on" if state else "off")
        return True             # the switch moves when refresh() says the setting did

    def set_limit(self, key, value):
        if not self.updating:
            self.do(LLM_LIMITS, "set", key, value)

    def switched_low(self, state):
        if not self.updating:
            self.do(LLM_LIMITS, "set", "llm_low_priority", "on" if state else "off")
        return True             # moves when refresh() says the setting did

    def relist(self):
        self.say("looking for models (lms ls)…")
        background(lambda: attempt("python3", LLM_MODELS, "refresh", timeout=90),
                   lambda result: self.done(result, ("refresh",)))

    def run_bench(self):
        self.bench_run.set_sensitive(False)
        self.say("starting the benchmark…")
        background(lambda: attempt("systemd-run", "--user", "--quiet", "--collect", f"--unit={BENCH_UNIT}",
                                   "--description=LM Studio benchmark", "python3", LLM_BENCH, "run", timeout=20),
                   self.bench_started)

    def bench_started(self, result):
        ok, text = result
        self.say("benchmark started: up to ~45 min, the card is busy meanwhile" if ok else f"!  {text}")
        background(read_bench, self.show_bench)

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None and not self.card.get_children():
            self.card.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
            self.card.show_all()
        background(lambda: run_json(LLM_GPU, "status", "--json", timeout=60), self.show)
        background(lambda: run_json(LLM_LIMITS, "status", "--json", timeout=20), self.show_limits)
        background(read_bench, self.show_bench)

    def show(self, data):
        if not data:
            clear(self.card)
            self.card.pack_start(dp.label("llm-gpu.py did not answer", "ctl-sub"), False, False, 0)
            self.card.show_all()
            return
        self.data = data
        self.updating = True
        self.show_card(data)
        self.show_loaded(data)
        self.show_installed(data)
        for role, combo in self.roles.items():
            current = data["roles"].get(role)
            combo.remove_all()
            for name, caption in role_choices(current, data["installed"]):
                combo.append(name, caption)
            combo.set_active_id(current)
        ctx, par = data["context"], data["parallel"]
        self.ctx.set(context_chips(ctx), str(ctx))
        self.ctx_sub.set_text(f"{k(ctx)} tokens for local models, from the next load")
        self.slots.set(slot_chips(par, data["default_parallel"]), str(par) if par else "auto")
        slots = par or data["default_parallel"]
        text = f"{slots} answers at once, {k(data['per_slot'])} each for sure"
        if data["slot_warning"]:
            text += "  !  " + data["slot_warning"][0].upper() + data["slot_warning"][1:] + "."
        self.slot_sub.set_text(text)
        for key, sw in self.switches.items():
            on = data["settings"][key] == "on"
            sw.set_state(on)
            sw.set_active(on)
        self.show_games(data)
        self.updating = False
        if data.get("stale") and not self.refreshed_list:
            self.refreshed_list = True      # once per window: a folder lms cannot list stays stale
            self.relist()

    def show_limits(self, s):
        if not s:
            self.limits_live.set_text("llm-limits.py did not answer")
            return
        self.limits = s
        lim, mach, dflt = s["limits"], s["machine"], s["defaults"]
        self.updating = True
        self.ram.set(ram_chips(lim["ram_limit_gb"], dflt["ram_limit_gb"], mach["ram_gb"]),
                     str(lim["ram_limit_gb"]))
        self.ram_sub.set_text(
            (f"{lim['ram_limit_gb']} GB" if lim["ram_limit_gb"] else "No limit") + f" of "
            f"{mach['ram_gb']:.0f} GB for LM Studio and its models")
        self.cpu.set(cpu_chips(lim["cpu_limit_pct"], mach["cpus"]), str(lim["cpu_limit_pct"]))
        self.cpu_sub.set_text(
            (f"{lim['cpu_limit_pct']} % of all {mach['cpus']} threads" if lim["cpu_limit_pct"] else
             "No limit") + " for LM Studio")
        on = bool(lim["llm_low_priority"])
        self.low.set_state(on)
        self.low.set_active(on)
        self.updating = False
        self.limits_live.set_text(limits_line(s))
        self.adopt.set_visible(s["where"] == "outside" and not s["app"] and s["unit"])

    def show_card(self, data):
        clear(self.card)
        card = data.get("gpu")
        if not card:
            self.card.pack_start(wrapped("No graphics card found, or its driver is not loaded "
                                         "(gpu.py could not read the card)"), False, False, 0)
            self.card.show_all()
            return
        pct = round(100 * card["used"] / card["total"]) if card["total"] else 0
        level = "critical" if pct >= 95 else "warning" if pct >= 85 else ""
        grid, _ = row("", card["name"], f"{gbs(card['used'])} of {gbs(card['total'])} in use, "
                      f"{gbs(card['total'] - card['used'])} free", dp.label(f"{pct} %", "ctl-value"))
        grid.attach(bar(pct, level), 1, 2, 2, 1)
        self.card.pack_start(grid, False, False, 0)
        if card["procs"]:
            procs = details(label="Programs on the card")
            self.card.pack_start(procs, False, False, 0)
        for p in card["procs"]:
            line = Gtk.Box(spacing=10)
            name = dp.label(p["name"], "ctl-title" if p.get("lmstudio") else "ctl-sub")
            name.set_ellipsize(3)       # Pango.EllipsizeMode.END
            line.pack_start(name, True, True, 0)
            line.pack_start(dp.label(gbs(p["used"]), "ctl-value"), False, False, 0)
            procs.box.pack_start(line, False, False, 0)
        if card["procs"]:
            procs.box.pack_start(wrapped("Programs drawing on screen (the desktop itself, games) use the card "
                                         "too, and are not all listed."), False, False, 0)
        self.card.show_all()

    def show_loaded(self, data):
        clear(self.loaded)
        if not data["running"]:
            self.loaded.pack_start(wrapped("none: LM Studio is not running"), False, False, 0)
        elif not data["loaded"]:
            self.loaded.pack_start(wrapped("none loaded"), False, False, 0)
        for m in data["loaded"]:
            grid, _ = row("", m["alias"], loaded_sub(m, data["default_parallel"]),
                          link("Unload", lambda a=m["identifier"]: self.do(LLM_GPU, "unload", a)))
            self.loaded.pack_start(grid, False, False, 0)
        self.unload_all.set_sensitive(bool(data["loaded"]))
        self.loaded.show_all()

    def show_installed(self, data):
        clear(self.installed)
        if not data["installed"]:
            self.installed.pack_start(wrapped("none yet: the launcher's ?get downloads one from Hugging Face"),
                                      False, False, 0)
        for m in data["installed"]:
            verdict = (m.get("fit") or {}).get("verdict", "")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            action = dp.label("loaded", "ctl-value") if m["loaded"] else link("Load", lambda a=m["alias"]:
                                                                             self.load(a))
            grid, _ = row("" if verdict == "fits" else "", f"{m['alias']}  ({m['label']})",
                          installed_sub(m, data["context"]), action)
            box.pack_start(grid, False, False, 0)
            fit = wrapped(f"Fits?  {fit_text(m)}", "ctl-sub")
            fit.set_margin_start(36)
            box.pack_start(fit, False, False, 0)
            self.installed.pack_start(box, False, False, 0)
        self.installed.show_all()

    def show_games(self, data):
        clear(self.games)
        left = data.get("unloaded")
        if left:
            names = ", ".join(m["modelKey"].split("/")[-1] for m in left["models"])
            when = "unloaded for the game that is on now" if not left.get("game_over") else \
                "unloaded for the last game"
            grid, _ = row("", when.capitalize(), names)
            self.games.pack_start(grid, False, False, 0)
            buttons = []
            for m in left["models"]:
                model = llm_models.resolve(m["modelKey"], prefix=False)
                if model is not None:
                    buttons.append(link(f"Load {model.name} again", lambda a=model.name: self.load(a)))
            if buttons:
                self.games.pack_start(links_row(*buttons), False, False, 0)
        self.games.show_all()

    def show_bench(self, result):
        data, going = result
        clear(self.bench)
        self.bench_run.set_sensitive(not going and llm_bench is not None)
        self.bench_run.set_label("running…" if going else "Run again")
        if going:
            names = ", ".join((data.get("running") or {}).get("models") or [])
            self.bench.pack_start(wrapped("Running now" + (f" ({names})" if names else "")
                                          + "; below is the last finished run"), False, False, 0)
        if not data.get("runs"):
            self.bench.pack_start(wrapped("No benchmark yet"), False, False, 0)
            self.bench.pack_start(details(wrapped(
                "\"Run again\" loads every installed model at 16k, 32k and 64k context (and 64k with 4 slots), "
                "times reading an 8k prompt and writing 256 tokens, and checks a tool call.")), False, False, 0)
            self.bench.show_all()
            return
        self.bench.pack_start(wrapped(bench_when(data).capitalize()), False, False, 0)
        full = details(wrapped("VRAM is what the model took on the card, pred what the calculator above said "
                               "it would; pp is reading the prompt, gen writing, x4 four answers at once "
                               "together."), label="Full results")
        grid = Gtk.Grid(column_spacing=12, row_spacing=1)
        grid.set_margin_start(6)
        heads = llm_bench.HEAD
        for col, text in enumerate(heads[:-1]):
            grid.attach(dp.label(text, "sn-label", 0.0 if col == 0 else 1.0), col, 0, 1, 1)
        for i, cells in enumerate(llm_bench.table_rows(data), start=1):
            for col, text in enumerate(cells[:-1]):
                cell = dp.label(text, "sn-value" if col == 0 else "ctl-sub", 0.0 if col == 0 else 1.0)
                if cells[-1]:
                    cell.set_tooltip_text(cells[-1])
                grid.attach(cell, col, i, 1, 1)
            note = dp.label(cells[-1], "ctl-sub")
            note.set_ellipsize(3)       # Pango.EllipsizeMode.END
            note.set_max_width_chars(34)
            note.set_tooltip_text(cells[-1] or None)
            grid.attach(note, len(heads) - 1, i, 1, 1)
        full.box.pack_start(grid, False, False, 0)
        calc = data.get("calculator") or {}
        if calc.get("n"):
            full.box.pack_start(wrapped(
                f"The calculator was off by {calc['mean_gb']:+.1f} GB on average (measured less predicted, "
                f"{calc['n']} loads): " + ", ".join(f"{a} {e:+.1f}" for a, e in calc["per_model"].items())),
                False, False, 0)
        for role, rec in (data.get("recommend") or {}).items():
            title = ROLE_TITLES.get(role, role) + ": " + (rec.get("model") or "none")
            grid, _ = row(ROLE_ICONS.get(role, ""), title, rec.get("why") or "")
            self.bench.pack_start(grid, False, False, 0)
        self.bench.pack_start(wrapped("Suggestions only; pick models above"), False, False, 0)
        self.bench.pack_start(full, False, False, 0)
        self.bench.show_all()
