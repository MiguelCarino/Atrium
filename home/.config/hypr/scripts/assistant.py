#!/usr/bin/env python3
"""The desktop assistant: a chat that knows this desktop. Ask it in Spanish
or English -- "what was I doing before lunch, reopen it", "compare these two
windows", "summarise the error on screen", "¿qué cambió hoy en atlas?" --
and the LOCAL model answers, looking things up and doing things only
through a fixed catalog of tools. Nothing leaves the machine.

    assistant.py open [--voice] [--ask TEXT]
                            show the chat (a layer-shell panel on the right
                            of the focused screen); --voice starts listening
                            at once, --ask asks at once. One window: a second
                            `open` shows the one that is there
    assistant.py toggle     show it, or hide it when it is showing (the key)
    assistant.py ask "TEXT" [--json] [--lang es|en]
                            one question without the window, for phone.py and
                            the other features: the answer printed (--json:
                            {"answer", "steps", "pending", "model", ...}). An
                            action that has to ask first is NOT done: it comes
                            back as "pending" with an id, for
    assistant.py confirm ID | cancel ID
                            a person said yes / no to it (it is checked again
                            against the desktop as it is now, then done)
    assistant.py history [--json] [-n N]   the kept conversation
    assistant.py clear      forget the whole conversation (file and window)
    assistant.py status [--json]   settings, tools, the model it would ask
                            (nothing loaded), history size -- for Settings
    assistant.py set KEY VALUE     one setting (SETTINGS below)
    assistant.py tools [--json]    the tool catalog
    assistant.py render OUT.png [QUESTION ANSWER]
                            the panel drawn off screen (no window, no grab)

THE TOOL LOOP (run_turn()). The model never gets a shell, a command line or
a function-calling API it could stretch: every reply is ONE JSON object,
held to a schema (LM Studio's response_format), {"tool": NAME, "args": {...}}
to use a tool or {"tool": "answer", "answer": "..."} to finish. NAME must be
in TOOLS and switched on (Settings > Assistant, per tool); the arguments are
checked here (types, choices, lengths: check_args()) before anything runs;
the result goes back to the model as text, clipped. At most `max_steps`
tools per question; then it must answer with what it has. Every step is
shown in the chat as it happens ("searched the desktop memory for …").

THE TOOLS, all of them other scripts' work, reused:

    memory     ask-desktop.py's searches: search_memory (desktop-memory.py),
               search_activity, search_files, search_clipboard, search_meaning
               -- through its call_search(), so Settings > Privacy's Ask and
               Desktop-memory switches decide what each may read; and
               ask_machine (peers.py recall: a paired computer's memory,
               answered there, only while one is paired)
    screen     look_at_screen: the focused window, the screen, or two or
               three windows side by side ("compare these"), captured with
               grim after screen-ask.py's private-window check (a password
               manager or a private-browsing window in it: refused) and read
               by screen-ask.py's vision model choice and ask(); or only the
               text (its ocr_text, tesseract first). The panel steps aside
               while the picture is taken; the PNGs live in tmpfs for seconds
    project    contexts.py: the current project and the list; entering or
               leaving one is an action (below)
    actions    do_actions: voice-command.py's CATALOG (theme, dnd, timers,
               launch an app, open a folder / link, move / close / fullscreen
               windows, workspaces, sessions, contexts, media, volume...)
               through its plan() -- every check and every "asks first" rule
               of voice commands -- and its execute(); its "search" is left
               out (the memory tools do that)
    windows    list_windows: hyprctl's windows and workspaces (a private
               window by its app only, never its title)
    sessions   sessions.py's saved sessions, the last one before this login
               ("where was I") and closed-windows.py's recently closed
               windows; restoring / reopening are actions
    timers     timers.py list: what is set
    brief      brief.py text: the morning brief's sections
    files      read_file: a text file the user named in the conversation (or
               a search just found), at most READ_MAX bytes; llm-worker.py's
               secret paths (~/.ssh, *.env, keys...) and voice-command.py's
               secret folders refused, lines that look like a key, a token or
               a password left out (smart-clipboard.py's rules); binary refused.
               FOLDER ACCESS (folder_access.py, Settings > Privacy > Folder
               access): the file's folder must be open to the assistant. When
               it is not, the tool waits while the desktop asks you ("The
               assistant wants to read ~/x -- <the model's `why`>": Deny /
               Allow once / Always allow); "Allow once" lasts for this
               question. A folder you typed yourself in this question (a
               path, ~/notes/today.md) counts as allowed for it. A question
               from the phone (who = phone) never prompts: its folders must
               be allowed for the phone beforehand, or it is told so. The
               searches' snippets / first lines of files come only from
               allowed folders (ask-desktop.py's call_search, same `who`)
    repos      repo_changes: one projects-folder repo's commits since today /
               yesterday / a week, its uncommitted files (waybar's repos.py
               status) -- git log / diff --stat with fixed arguments

ASKING FIRST. Actions follow voice-command.py's rules -- closing what you
cannot see, several windows, overwriting a session, the sound profile, a
name that fits several apps all ask -- and "confirm" = all makes every
action ask. Restoring a session ("where was I") always asks: it opens
windows. Closing a window and opening a link always ask here (ALWAYS_ASK):
the model wrote them, perhaps after reading text that told it to. An action that asks stops the tool loop; the chat shows
Confirm / Cancel and nothing runs without the Confirm click (the CLI hands
back a pending id instead). Done actions that can be taken back cheaply get
an Undo button (voice-command.py's undo_ops).

WHICH MODEL (pick_model(); Settings > Assistant):
    auto     the "default" model (Settings > AI & models) when LM Studio has
             it loaded already, else the "quick" one -- llm-worker.py's
             ready(): local only, never in gamemode, never one that would
             not fit on the card next to what is loaded (nothing is pushed
             off for it)
    default | quick | worker   that role's model, through ready() too
Never a cloud model: no local model, no answer (it says why).

THE CONVERSATION is kept in $XDG_STATE_HOME/hypr/assistant/history.jsonl
(mode 600): question, answer, the steps' one-line summaries -- never tool
results, pictures or file contents. `history_days` prunes it (0: nothing is
written, the chat lives only while the panel does); Forget / `clear` wipes
it. The last HISTORY_TURNS exchanges go to the model as context. It goes
into the desktop memory ONLY when Settings > Privacy's assistant_memory is
on (privacy_settings.py; OFF as shipped).

SPOKEN REPLIES: speak(text, lang) is the one call point. With voice_reply on
it hands the answer to a sibling TTS module -- scripts/tts.py (or speak.py)
with a speak(text, lang=...) function -- in a thread; with none installed it
does nothing.

VOICE IN: the microphone button (or `open --voice`) records with pw-record
into tmpfs until pressed again and hands the file to voice.py's daemon
(`transcribe`); the recording is deleted at once and the words land in the
box, to be checked and sent with Enter.

Settings ($XDG_STATE_HOME/hypr/assistant/settings.json; `set KEY VALUE`):
    enabled on|off          the assistant answers at all
    model auto|default|quick|worker
    max_steps 2..10         tools per question (6)
    confirm risky|all       which actions ask first (risky: voice commands' rules)
    history_days 0|1|7|30|90   how long the conversation is kept (7)
    voice_reply on|off      speak the answers (off; needs a TTS module)
    language auto|es|en     the answers' language (auto: the question's)
    launcher_ask assistant|desktop   what the launcher's "ask …" does first
    tool_<name> on|off      each tool group above (all on as shipped)
"""
import datetime
import fcntl
import importlib.util
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
DIR = os.path.join(STATE_HOME, "hypr", "assistant")
SETTINGS = os.path.join(DIR, "settings.json")
HISTORY = os.path.join(DIR, "history.jsonl")
RUN_DIR = os.path.join(RUNTIME, "assistant")
SOCK = os.path.join(RUN_DIR, "panel.sock")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desktop_conf  # noqa: E402

PROJECTS = desktop_conf.projects_dir()      # your projects folder (desktop.conf)
WAYBAR = os.path.join(HOME, ".config", "waybar", "scripts")

TOOL_GROUPS = ("memory", "screen", "project", "actions", "windows", "sessions", "timers", "brief", "files",
               "repos")
DEFAULTS = {"enabled": "on", "model": "auto", "max_steps": 6, "confirm": "risky", "history_days": 7,
            "voice_reply": "off", "language": "auto", "launcher_ask": "assistant",
            **{f"tool_{g}": "on" for g in TOOL_GROUPS}}
CHOICES = {"enabled": ("on", "off"), "model": ("auto", "default", "quick", "worker"),
           "confirm": ("risky", "all"), "history_days": (0, 1, 7, 30, 90), "voice_reply": ("on", "off"),
           "language": ("auto", "es", "en"), "launcher_ask": ("assistant", "desktop"),
           **{f"tool_{g}": ("on", "off") for g in TOOL_GROUPS}}
STEPS_RANGE = (2, 10)
HISTORY_TURNS = 6           # earlier exchanges the model sees
RESULT_CHARS = 6000         # a tool's result, as the model gets it
READ_MAX = 64 * 1024        # bytes of a file read_file hands over
MAX_TOKENS = 1200
PENDING_S = 600             # a pending action can be confirmed this long
MAX_RECORD_S = 60
IDLE_QUIT_S = 1800          # a hidden panel quits after this (the history stays)
PANEL_W = 460
NO_READ_ROOTS = ("/proc", "/sys", "/dev", "/run", "/boot")
LEFT_OUT = {"search"}       # voice-command actions the memory tools do better
# Actions that always ask here, though a spoken one does not: a person said
# a voice command, but the model writes these -- maybe after reading a page,
# a file or the clipboard that told it to. Closing loses unsaved work; a
# link the model wrote could carry what it read off the machine.
ALWAYS_ASK = {"close": "closes a window: unsaved work in it would be lost",
              "open-url": "opens a web address the assistant wrote"}

# The tools the model may name: group (its switch), arguments (type, required,
# choices / max length), and the line the model reads.
TOOLS = {
    "search_memory": ("memory", {"query": ("str", True, 200), "start": ("time", False, None),
                                 "end": ("time", False, None),
                                 "source": ("str", False, ("activity", "clipboard", "notifications",
                                                           "captions", "screen"))},
                      "what went past with its time: window titles, copies, notifications, captions, "
                      "screen text, links. Time words in query work ('yesterday', 'el martes')"),
    "search_activity": ("memory", {"start": ("time", True, None), "end": ("time", True, None),
                                   "text": ("str", False, 100)},
                        "which windows had the focus between start and end (ISO local times): time per "
                        "app and per window title, a timeline. For 'what was I doing / working on'"),
    "search_files": ("memory", {"query": ("str", False, 120), "modified_after": ("time", False, None),
                                "modified_before": ("time", False, None), "extension": ("str", False, 10)},
                     "files in the home folder by name words and/or modification date"),
    "search_clipboard": ("memory", {"query": ("str", True, 120)}, "the clipboard history's text, newest first"),
    "search_meaning": ("memory", {"query": ("str", True, 200), "k": ("int", False, (1, 15))},
                       "passages INSIDE documents, notes and code about a topic, with their file"),
    "look_at_screen": ("screen", {"what": ("str", False, ("window", "screen", "windows")),
                                  "apps": ("list", False, 3), "question": ("str", False, 300),
                                  "text_only": ("bool", False, None)},
                       "look at the focused window (what=window), the whole screen (screen), or 2-3 "
                       "visible windows side by side (windows; apps = their app names, or leave it out "
                       "for the visible ones) and answer `question` about it; text_only=true copies the "
                       "text instead (OCR)"),
    "project": ("project", {"op": ("str", True, ("current", "list", "enter", "leave")),
                            "name": ("str", False, 60)},
                "project contexts: the current one, the list; enter NAME / leave (asks like any action)"),
    "do_actions": ("actions", {"actions": ("actions", True, 6)},
                   "do desktop actions from ACTIONS (below), in order"),
    "list_windows": ("windows", {}, "the open windows (app, title, workspace, which has the focus) and "
                                    "the workspaces"),
    "sessions": ("sessions", {"op": ("str", True, ("list", "closed", "where_was_i", "restore", "reopen_closed")),
                              "name": ("str", False, 64), "count": ("int", False, (1, 5))},
                 "saved window sessions (list), recently closed windows (closed); where_was_i restores "
                 "the windows from before this login, restore NAME a saved session, reopen_closed "
                 "COUNT the last closed windows"),
    "timers": ("timers", {}, "the timers, alarms and reminders that are set"),
    "brief": ("brief", {}, "today's brief: yesterday's work, repos with work in them, failed services, "
                           "weather, calendar, timers, unread notifications"),
    "read_file": ("files", {"path": ("str", True, 400), "why": ("str", False, 200)},
                  "read a text file the user named (or a search found); large files are cut. `why`: in a few "
                  "words why you need it -- shown to the user if they must allow its folder first"),
    "repo_changes": ("repos", {"repo": ("str", True, 80), "since": ("str", False, ("today", "yesterday", "week"))},
                     "what changed in a repo in the user's projects folder: its commits since today/yesterday/a week, and "
                     "its uncommitted files"),
    "ask_machine": ("memory", {"query": ("str", True, 300), "machine": ("str", False, 40)},
                    "ask the desktop memory of the user's OTHER computer (a paired machine; `machine` = its "
                    "name when there are several): its answer. Only when they ask about that computer"),
}
GROUP_TEXT = {   # the Settings page's lines, per switch
    "memory": ("Desktop memory and search", "what you did, saw, copied and the files you have -- Settings > "
               "Privacy's Ask and Desktop memory switches still decide each source"),
    "screen": ("Look at the screen", "the focused window, the screen or windows side by side, read by the local "
               "vision model; never a private window"),
    "project": ("Project contexts", "which project you are in; entering one is an action"),
    "actions": ("Desktop actions", "voice commands' catalog: theme, Do Not Disturb, timers, apps, folders, links, "
                "windows, workspaces, media; risky ones ask first"),
    "windows": ("Windows and workspaces", "what is open where (private windows by app only)"),
    "sessions": ("Sessions and closed windows", "saved sessions, where you left off, reopening closed windows "
                 "(restoring always asks)"),
    "timers": ("Timers and alarms", "what is set"),
    "brief": ("Daily brief", "yesterday's work, loose ends, today"),
    "files": ("Read a file you name", f"text only, at most {READ_MAX // 1024} KB, never key stores or secret files"),
    "repos": ("Repo changes", "commits and uncommitted files of a repo in your projects folder (no network)"),
}
TOOL_WORDS = {   # the step lines in the chat: (English, Spanish)
    "search_memory": ("searched the desktop memory for “{query}”", "busqué en la memoria del escritorio «{query}»"),
    "search_activity": ("looked at what had the focus {span}", "miré qué tuvo el foco {span}"),
    "search_files": ("looked for files {query}", "busqué archivos {query}"),
    "search_clipboard": ("searched the clipboard for “{query}”", "busqué en el portapapeles «{query}»"),
    "search_meaning": ("searched inside documents for “{query}”", "busqué dentro de documentos «{query}»"),
    "look_at_screen": ("looked at {what}", "miré {what}"),
    "project": ("project contexts: {op}", "contextos de proyecto: {op}"),
    "do_actions": ("planned {n} action(s)", "preparé {n} acción(es)"),
    "list_windows": ("listed the open windows", "listé las ventanas abiertas"),
    "sessions": ("sessions: {op}", "sesiones: {op}"),
    "timers": ("read the timers", "leí los temporizadores"),
    "brief": ("read today's brief", "leí el resumen del día"),
    "read_file": ("read {path}", "leí {path}"),
    "repo_changes": ("read {repo}'s changes ({since})", "leí los cambios de {repo} ({since})"),
    "ask_machine": ("asked the other machine's memory for “{query}”",
                    "pregunté a la memoria de la otra máquina «{query}»"),
}
WORDS = {
    "en": {"confirm": "Confirm", "cancel": "Cancel", "undo": "Undo", "done": "Done", "undone": "Undone",
           "cancelled": "Cancelled", "ask": "Do this?", "failed": "Some of it failed", "off": "The assistant "
           "is turned off (Settings > Assistant).", "expired": "That has expired: ask again.",
           "thinking": "thinking…", "no_model": "No local model can answer now",
           "waiting": "⏸ Not done yet: it waits for your Confirm."},
    "es": {"confirm": "Confirmar", "cancel": "Cancelar", "undo": "Deshacer", "done": "Hecho", "undone": "Deshecho",
           "cancelled": "Cancelado", "ask": "¿Hago esto?", "failed": "Algo falló", "off": "El asistente está "
           "apagado (Ajustes > Asistente).", "expired": "Eso caducó: pregunta de nuevo.",
           "thinking": "pensando…", "no_model": "Ningún modelo local puede responder ahora",
           "waiting": "⏸ Aún no se hizo: espera a que pulses Confirmar."},
}


def log(text):
    print(f"assistant: {text}", file=sys.stderr, flush=True)


def _module(name, filename, folder=HERE):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(folder, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def models():
    return _module("llm_models", "llm_models.py")


def worker():
    return _module("llm_worker", "llm-worker.py")


def vc():
    return _module("voice_command", "voice-command.py")


def ask_desktop():
    return _module("ask_desktop", "ask-desktop.py")


def screen_ask():
    return _module("screen_ask", "screen-ask.py")


def access():
    return _module("folder_access", "folder_access.py")


def privacy():
    return _module("privacy_settings", "privacy_settings.py")


def smartclip():
    return _module("smart_clipboard", "smart-clipboard.py")


# -- settings ------------------------------------------------------------------------------
def _coerce(key, value):
    """A setting's value checked and in its type; ValueError otherwise."""
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r}")
    if key == "max_steps":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValueError("max_steps is a number") from None
        if not STEPS_RANGE[0] <= n <= STEPS_RANGE[1]:
            raise ValueError(f"max_steps is {STEPS_RANGE[0]}..{STEPS_RANGE[1]}")
        return n
    if key == "history_days":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError("history_days is a number of days") from None
    if value not in CHOICES[key]:
        raise ValueError(f"{key} is one of {', '.join(map(str, CHOICES[key]))}")
    return value


def settings():
    """The settings, each one checked: a bad or missing value is its default."""
    try:
        with open(SETTINGS) as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        raw = {}
    out = dict(DEFAULTS)
    for key, value in (raw.items() if isinstance(raw, dict) else ()):
        try:
            out[key] = _coerce(key, value)
        except ValueError:
            pass
    return out


def set_setting(key, value):
    value = _coerce(key, value)
    conf = settings()
    conf[key] = value
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as handle:
        json.dump({k: v for k, v in conf.items() if v != DEFAULTS[k]}, handle, indent=2)
    os.replace(tmp, SETTINGS)
    if key == "history_days":
        prune()
    return value


def tools_on(conf):
    return [name for name, (group, _a, _h) in TOOLS.items() if conf.get(f"tool_{group}") == "on"
            and (name != "ask_machine" or machines_paired())]


def guess_language(text):
    return vc().guess_language(text)


# -- the conversation on disk ------------------------------------------------------------------
def read_history(path=None):
    path = path or HISTORY
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("question") is not None:
                    rows.append(row)
    except OSError:
        pass
    return rows


def _write_rows(rows, path=None):
    path = path or HISTORY
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".history-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def history_row(turn):
    """What of a turn is kept: the words and the step lines, nothing a tool read."""
    return {"id": turn["id"], "t": turn["t"], "lang": turn.get("lang", "en"), "question": turn["question"],
            "answer": turn.get("answer", ""), "steps": [s.get("line", "") for s in turn.get("steps", [])],
            "model": turn.get("model", "")}


def remember(turn, conf=None, path=None):
    """Append one finished turn (when history_days > 0), and into the
    desktop memory when Privacy allows it."""
    conf = conf or settings()
    prune(conf, path=path)      # the retention holds for the panel too, not only the CLI
    if conf["history_days"] > 0:
        path = path or HISTORY
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps(history_row(turn), ensure_ascii=False) + "\n")
    to_memory(turn)


def to_memory(turn):
    """The exchange as a desktop memory -- only with Privacy's
    assistant_memory on (and the memory on), secrets scrubbed."""
    try:
        ps = privacy()
        pconf = ps.load()
        # stored as a "notifications" memory: that source's switch has the last word too
        if not ps.assistant_memory_on(pconf) or "notifications" not in ps.memory_sources(pconf):
            return False
        dm = _module("desktop_memory", "desktop-memory.py")
        text = dm.scrub(f"{turn['question']}\n{turn.get('answer', '')}")
        if not text:
            return False
        title = (dm.scrub(turn["question"]) or "").split("\n")[0][:120]   # never the unscrubbed question
        con = dm.connect()
        try:
            dm.add(con, "notifications", turn["t"], text, app="Assistant", title=title,
                   key=f"assistant:{turn['id']}")
            con.commit()
        finally:
            con.close()
        return True
    except Exception as err:    # noqa: BLE001 -- the memory is extra; the answer stands
        log(f"not put in the desktop memory: {err}")
        return False


def prune(conf=None, now=None, path=None):
    """Drop the turns older than history_days (all of them at 0). How many went."""
    conf = conf or settings()
    path = path or HISTORY
    rows = read_history(path)
    if not rows:
        return 0
    days = conf["history_days"]
    cutoff = (now or time.time()) - days * 86400
    keep = [r for r in rows if days > 0 and (r.get("t") or 0) >= cutoff]
    if len(keep) != len(rows):
        if keep:
            _write_rows(keep, path)
        else:
            clear(path)
    return len(rows) - len(keep)


def clear(path=None):
    """Forget the conversation: the file, and the pending actions."""
    for p in (path or HISTORY,):
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        for name in os.listdir(RUN_DIR):
            if name.startswith("pending-"):
                os.remove(os.path.join(RUN_DIR, name))
    except OSError:
        pass


def context_messages(history, turns=HISTORY_TURNS):
    """The last exchanges as chat messages (the words only)."""
    out = []
    for row in history[-turns:]:
        if row.get("question") and row.get("answer"):
            out.append({"role": "user", "content": row["question"][:1500]})
            out.append({"role": "assistant", "content": json.dumps(
                {"tool": "answer", "answer": row["answer"][:1500]}, ensure_ascii=False)})
    return out


# -- checking what the model asked for ---------------------------------------------------------
class ToolError(ValueError):
    pass


def _time_ok(value):
    try:
        datetime.datetime.fromisoformat(str(value).replace("Z", ""))
        return True
    except ValueError:
        return False


def check_args(name, args):
    """The model's arguments for one tool, checked: unknown ones dropped,
    each in its type and limits. ToolError says what is wrong."""
    if name not in TOOLS:
        raise ToolError(f"there is no tool “{name}”")
    spec = TOOLS[name][1]
    if not isinstance(args, dict):
        args = {}
    out = {}
    for key, (kind, required, limit) in spec.items():
        value = args.get(key)
        if value in (None, "", []):
            if required:
                raise ToolError(f"{name} needs “{key}”")
            continue
        if kind == "str":
            if not isinstance(value, (str, int, float)):
                raise ToolError(f"{key} is text")
            value = " ".join(str(value).split())
            if isinstance(limit, tuple):
                if value.lower() not in limit:
                    raise ToolError(f"{key} is one of {', '.join(limit)}")
                value = value.lower()
            elif limit and len(value) > limit:
                value = value[:limit]
        elif kind == "time":
            if not isinstance(value, str) or not _time_ok(value):
                raise ToolError(f"{key} is an ISO local date-time like 2026-10-21T09:00")
        elif kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ToolError(f"{key} is a whole number") from None
            lo, hi = limit
            value = max(lo, min(hi, value))
        elif kind == "bool":
            value = value is True or str(value).lower() in ("true", "1", "yes")
        elif kind == "list":
            if isinstance(value, str):
                value = [v for v in re.split(r"\s*(?:,| and | y )\s*", value) if v]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ToolError(f"{key} is a list of names")
            value = [" ".join(v.split())[:60] for v in value if v.strip()][:limit]
        elif kind == "actions":
            if isinstance(value, dict):
                value = [value]
            if not isinstance(value, list) or not value:
                raise ToolError("actions is a list of {\"action\": NAME, ...}")
            value = [a for a in value if isinstance(a, dict)][:limit]
        out[key] = value
    return out


def parse_reply(text):
    """The model's reply -> {"tool", "args", "answer"}; a reply that is not
    JSON is taken as the answer itself (a model that forgot the format)."""
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    data = None
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return {"tool": "answer", "args": {}, "answer": text}
    tool = str(data.get("tool") or "answer").strip()
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    answer = data.get("answer")
    return {"tool": tool, "args": args, "answer": answer if isinstance(answer, str) else ""}


def reply_schema(names):
    return {"type": "json_schema", "json_schema": {"name": "step", "schema": {
        "type": "object",
        "properties": {"tool": {"type": "string", "enum": list(names) + ["answer"]},
                       "args": {"type": "object"},
                       "answer": {"type": "string"}},
        "required": ["tool"]}}}


# -- the step lines ------------------------------------------------------------------------------
def step_line(name, args, lang="en"):
    en, es = TOOL_WORDS.get(name, (name, name))
    template = es if lang == "es" else en
    what = {"window": ("the focused window", "la ventana activa"), "screen": ("the screen", "la pantalla"),
            "windows": ("the windows side by side", "las ventanas lado a lado")}
    words = {"query": args.get("query") or args.get("text") or "", "op": args.get("op", ""),
             "path": short_path(args.get("path", "")), "repo": args.get("repo", ""),
             "since": args.get("since", "today"), "n": len(args.get("actions") or []),
             "what": what.get(args.get("what") or "window", ("?", "?"))[lang == "es"]}
    if name == "search_activity":
        words["span"] = f"{_hm(args.get('start'))}–{_hm(args.get('end'))}"
    if name == "search_files":
        words["query"] = f"“{args['query']}”" if args.get("query") else ""
    if name == "look_at_screen" and args.get("apps"):
        words["what"] = ", ".join(args["apps"])
    try:
        return template.format(**words).replace("  ", " ").strip()
    except (KeyError, IndexError):
        return name


def _hm(value):
    try:
        return datetime.datetime.fromisoformat(str(value)).strftime("%a %H:%M")
    except ValueError:
        return str(value or "?")


def short_path(path):
    path = str(path or "")
    return "~" + path[len(HOME):] if path.startswith(HOME) else path


# -- the tools ---------------------------------------------------------------------------------
class Turn:
    """One question's run: what the tools may know about it, and what it left
    (pending actions, undo). `hooks`: {"hide": fn, "show": fn} the panel
    gives so it is not in the screenshots."""

    def __init__(self, question, lang, conf, world=None, hooks=None, user_texts=(), who="assistant"):
        self.question, self.lang, self.conf = question, lang, conf
        self.who = who      # folder_access.py's feature: "assistant", or "phone" for phone-ask.py
        # The folders this question names as a path, typed by the user: open
        # to the assistant for this question (never for the phone's).
        typed = access().typed_folders(question) if who == "assistant" else ()
        self.access = access().Session(who, typed)
        self.world = world
        self.hooks = hooks or {}
        self.user_texts = [question, *user_texts]
        self.seen_paths = set()
        self.pending = None
        self.undo = []
        self.done = []

    def get_world(self):
        if self.world is None:
            self.world = vc().World()
        return self.world


def memory_sources():
    """What ask-desktop.py's tools may read now (its ask() does the same)."""
    ad = ask_desktop()
    conf = privacy().load()
    sources = set(privacy().ask_sources(conf))
    if "files" in sources and ad.index_ready(conf):
        sources.add("index")
    if ad.memory_ready(conf):
        sources.add("memory")
    return sources


def t_memory(name, args, turn):
    result = ask_desktop().call_search(name, args, memory_sources(), who=turn.who, session=turn.access)
    if isinstance(result, dict):
        for f in result.get("files") or []:
            if isinstance(f, dict) and f.get("path"):
                turn.seen_paths.add(f["path"])
    return result


def visible_clients(world):
    """The mapped windows on a workspace shown on some screen, focused first."""
    shown = set()
    for m in world.monitors():
        for key in ("activeWorkspace", "specialWorkspace"):
            wid = (m.get(key) or {}).get("id")
            if wid:
                shown.add(wid)
    out = [c for c in world.clients() if (c.get("workspace") or {}).get("id") in shown and not c.get("hidden")
           and c.get("size") and c["size"][0] > 40]
    return sorted(out, key=lambda c: c.get("focusHistoryID", 99))


def pick_windows(apps, world):
    """The windows look_at_screen(what=windows) means: the ones each app name
    finds among the visible windows, else the 2-3 most recently focused."""
    shown = visible_clients(world)
    if not apps:
        return shown[:3] if len(shown) == 3 else shown[:2]
    out = []
    for app in apps:
        hits = [c for c in vc().match_windows(app, shown, world.private()) if c not in out]
        if not hits:
            raise ToolError(f"no visible window is “{app}” (only windows on a shown workspace can be looked at)")
        out.append(hits[0])
    return out


def grab(argv, png):
    return subprocess.run(argv + [png], capture_output=True, timeout=15).returncode == 0


def t_look(args, turn):
    sa = screen_ask()
    if models()._gamemode_on():
        raise ToolError("gamemode is on: the graphics card belongs to the game")
    what = args.get("what") or ("windows" if args.get("apps") else "window")
    question = args.get("question") or turn.question
    pngs, labels = [], []
    hide, show = turn.hooks.get("hide"), turn.hooks.get("show")
    try:
        if hide:
            hide()
        if what == "windows":
            world = turn.get_world()
            wins = pick_windows(args.get("apps") or [], world)
            if not wins:
                raise ToolError("no window is showing")
            shown = sa.visible_workspaces(world.monitors())
            for c in wins:
                x, y = c["at"]
                w, h = c["size"]
                hidden = sa.private_in(world.clients(), (x, y, w, h), shown, sa._is_private)
                if hidden:
                    raise ToolError(f"{hidden[0]} is in that part of the screen: not captured")
                fd, png = tempfile.mkstemp(prefix="screen-ask-", suffix=".png", dir=RUNTIME)
                os.close(fd)
                pngs.append(png)
                if not grab(["grim", "-g", f"{x},{y} {w}x{h}"], png):
                    raise ToolError("grim could not take the screenshot")
                labels.append(vc().window_label(c, world.private()))
        else:
            png, why = sa.capture(what)
            if not png:
                raise ToolError(why or "nothing captured")
            pngs.append(png)
            labels.append("the screen" if what == "screen" else "the focused window")
    finally:
        if show:
            show()
    try:
        if args.get("text_only"):
            texts = []
            for png, label in zip(pngs, labels):
                text, how = sa.ocr_text(png)
                texts.append(f"[{label}, read by {how}]\n{text[:RESULT_CHARS // len(pngs)]}")
            return {"looked_at": labels, "text": "\n\n".join(texts)}
        key, why = sa.pick_model(lambda text: None, need_vision=True)
        if not key:
            raise ToolError(why)
        intro = (f"These are {len(pngs)} windows, in this order: {'; '.join(labels)}. " if len(pngs) > 1 else "")
        content = [{"type": "text", "text": intro + question}]
        content += [{"type": "image_url", "image_url": {"url": sa.image_url(p)}} for p in pngs]
        seen = sa.ask(key, [{"role": "user", "content": content}])
        return {"looked_at": labels, "vision_model": key.split("/")[-1], "seen": seen}
    finally:
        for p in pngs:
            sa._remove(p)


def script_json(name, *args, timeout=20):
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, name), *args], capture_output=True, text=True,
                             timeout=timeout).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def t_project(args, turn):
    op = args["op"]
    if op in ("enter", "leave"):
        if op == "enter" and not args.get("name"):
            raise ToolError("enter needs the project's name")
        return act([{"action": "context", "value": args["name"] if op == "enter" else "leave"}], turn)
    data = script_json("contexts.py", "list", "--json") or {}
    current = (data.get("current") or {}).get("name") or ""
    names = [c.get("name") for c in data.get("contexts") or [] if isinstance(c, dict)]
    if op == "current":
        return {"current": current or "none"}
    return {"current": current or "none", "projects": [
        {"name": c.get("name"), "repo": short_path(os.path.expanduser(c.get("repo") or ""))}
        for c in data.get("contexts") or [] if isinstance(c, dict)] if names else "none set up"}


def t_windows(args, turn):
    world = turn.get_world()
    private = world.private()
    active = (world.active() or {}).get("address")
    wins = []
    for c in world.clients():
        label = vc().window_label(c, private)
        wins.append({"window": label, "workspace": (c.get("workspace") or {}).get("name"),
                     **({"focused": True} if c.get("address") == active else {}),
                     **({"floating": True} if c.get("floating") else {})})
    shown = [(m.get("activeWorkspace") or {}).get("name") for m in world.monitors()]
    return {"windows": wins[:40], "workspaces_on_screen": [s for s in shown if s]}


def t_sessions(args, turn):
    op = args["op"]
    if op == "list":
        data = script_json("sessions.py", "list", "--json") or {}
        rows = [{k: s.get(k) for k in ("name", "windows", "apps")} for s in data.get("sessions") or []]
        last = data.get("last")
        return {"sessions": rows or "none saved", "last_session_before_this_login":
                {k: last.get(k) for k in ("windows", "apps", "saved") if k in last} if isinstance(last, dict)
                else "none"}
    if op == "closed":
        stack = script_json("closed-windows.py", "list", "--json", timeout=5)
        private = turn.get_world().private()
        out = []
        for item in stack if isinstance(stack, list) else []:
            rec = item.get("record") or {}
            label = vc().window_label({"class": rec.get("class"), "title": rec.get("title")}, private)
            out.append({"window": label, "workspace": rec.get("workspace"),
                        "closed": datetime.datetime.fromtimestamp(item.get("closed") or 0).strftime("%H:%M")})
        return {"recently_closed": out[:10] or "none"}
    if op == "where_was_i":
        return act([{"action": "where-was-i"}], turn)
    if op == "restore":
        if not args.get("name"):
            raise ToolError("restore needs the session's name")
        return act([{"action": "session", "value": args["name"]}], turn)
    return act([{"action": "reopen-closed", "count": args.get("count") or 1}], turn)


def t_timers(args, turn):
    data = script_json("timers.py", "list", "--json")
    return {"set": data if data else "nothing is set"}


def t_brief(args, turn):
    data = script_json("brief.py", "text", "--json", timeout=40)
    if not isinstance(data, list):
        raise ToolError("brief.py did not answer")
    return {s.get("title", s.get("id")): s.get("lines") for s in data if isinstance(s, dict)}


def resolve_path(text):
    path = os.path.expanduser(str(text).strip().strip("\"'"))
    if not os.path.isabs(path):
        path = os.path.join(HOME, path)
    return os.path.normpath(path)


def named(path, turn):
    """Did the user name this file (its path, its name, or its name without
    the extension, in their words) or did a tool of this turn find it?"""
    if path in turn.seen_paths:
        return True
    base = os.path.basename(path).lower()
    stem = os.path.splitext(base)[0]
    for text in turn.user_texts:
        low = str(text).lower()
        # the name as a word of its own ("notes.txt", not the "a" inside "what")
        if short_path(path).lower() in low or path.lower() in low \
                or (len(base) >= 3 and re.search(rf"(?<![\w.]){re.escape(base)}(?![\w])", low)) \
                or (len(stem) >= 3 and re.search(rf"\b{re.escape(stem)}\b", low)):
            return True
    return False


def secret_lines(text):
    """The text without the lines that look like a key, token or password
    (smart-clipboard.py's TOKEN / SECRET_WORD), and how many went."""
    sc = smartclip()
    keep, gone = [], 0
    for line in text.splitlines():
        if sc.TOKEN.search(line) or sc.SECRET_WORD.search(line):
            gone += 1
            continue
        keep.append(line)
    return "\n".join(keep), gone


def t_read(args, turn):
    path = resolve_path(args["path"])
    real = os.path.realpath(path)
    if any(real == r or real.startswith(r + os.sep) for r in NO_READ_ROOTS):
        raise ToolError("system folders are not read")
    if worker().looks_secret(real) or vc().looks_secret(real):
        raise ToolError("that looks like a secret file (keys, passwords, tokens, browser profiles): not read")
    if not os.path.isfile(real):
        raise ToolError(f"there is no file {short_path(path)}")
    if not named(path, turn) and not named(real, turn):
        raise ToolError("only a file the user named (or a search just found) is read: ask them which")
    reason = args.get("why") or f"to answer “{turn.question[:140]}”"
    if turn.hooks.get("asking"):
        turn.hooks["asking"](access().folder_of(real))
    ok, why = access().request(real, turn.who, reason, session=turn.access, prompt=turn.who != "phone")
    if not ok:
        raise ToolError(why)
    try:
        size = os.path.getsize(real)
        with open(real, "rb") as handle:
            raw = handle.read(READ_MAX)
    except OSError as err:
        raise ToolError(err.strerror or str(err)) from None
    if b"\0" in raw[:4096]:
        raise ToolError("a binary file: not read")
    text, gone = secret_lines(raw.decode("utf-8", errors="replace"))
    turn.seen_paths.add(real)
    out = {"path": short_path(real), "size_kb": round(size / 1024, 1), "text": text}
    if size > READ_MAX:
        out["note"] = f"only the first {READ_MAX // 1024} KB"
    if gone:
        out["left_out"] = f"{gone} line(s) that look like a key, token or password"
    return out


def git(path, *args, timeout=15):
    try:
        done = subprocess.run(["git", "-C", path, "--no-optional-locks", *args], capture_output=True, text=True,
                              timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        return done.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


SINCE = {"today": ("midnight", None), "yesterday": ("yesterday.midnight", "midnight"), "week": ("1.week.ago", None)}


def t_repo(args, turn, root=None):
    root = root or PROJECTS
    try:
        names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n, ".git")))
    except OSError:
        names = []
    try:
        name = vc().match_name(args["repo"], names, "repo in your projects folder")
    except vc().Refused as err:
        raise ToolError(str(err)) from None
    path = os.path.join(root, name)
    since = args.get("since") or "today"
    after, before = SINCE[since]
    span = [f"--since={after}"] + ([f"--until={before}"] if before else [])
    commits = git(path, "log", *span, "--no-color", "--date=format:%a %H:%M", "--format=%h %ad %s",
                  "--shortstat", "-n", "40")
    dirty = git(path, "status", "--short")
    diff = git(path, "diff", "--stat", "--no-color", "HEAD")
    lines = [line for line in commits.splitlines() if line.strip()]
    return {"repo": name, "since": since, "commits": "\n".join(lines)[:RESULT_CHARS // 2] or "no commits",
            "uncommitted": (dirty.strip()[:1500] or "nothing") + ("\n" + diff.strip()[-1200:] if diff.strip() else "")}


EXTRA_ACTIONS = {   # the assistant's own, besides voice-command.py's CATALOG
    "where-was-i": ("restore the windows from before this login", "restaurar las ventanas de antes de este inicio"),
    "reopen-closed": ("reopen the last {n} closed window(s)", "reabrir las últimas {n} ventanas cerradas"),
}


def extra_step(act_, lang):
    name = act_["action"]
    en, es = EXTRA_ACTIONS[name]
    if name == "where-was-i":
        data = script_json("sessions.py", "list", "--json") or {}
        if not data.get("last"):
            raise vc().Refused("there is no earlier session to go back to yet")
        return {"action": name, "say": es if lang == "es" else en, "confirm": "it opens several windows",
                "ops": [("detach", vc().py("sessions.py", "where-was-i"))], "undo": None}
    try:
        n = max(1, min(5, int(act_.get("count") or 1)))
    except (TypeError, ValueError):
        n = 1
    return {"action": name, "say": (es if lang == "es" else en).format(n=n), "confirm": "",
            "ops": [("argv", vc().py("closed-windows.py", "reopen")) for _ in range(n)], "undo": None}


def plan_actions(actions, world, lang="en", confirm_all=False):
    """(steps, refused): voice-command.py's plan() for its CATALOG, the
    assistant's two own actions beside it, the same asking rules."""
    v = vc()
    steps, refused = [], []
    for a in (actions or [])[:v.MAX_ACTIONS]:
        name = a.get("action") if isinstance(a, dict) else None
        if name in LEFT_OUT:
            refused.append(f"{name}: use the search tools instead")
        elif name in EXTRA_ACTIONS:
            try:
                steps.append(extra_step(a, lang))
            except v.Refused as err:
                refused.append(f"{name}: {err}")
        else:
            got, why = v.plan([a], world, lang)
            steps += got
            refused += why
    for step in steps:
        if step["action"] in ALWAYS_ASK and not step["confirm"]:
            step["confirm"] = ALWAYS_ASK[step["action"]]
        elif confirm_all and not step["confirm"]:
            step["confirm"] = "confirm everything is on"
        elif refused and not step["confirm"]:
            step["confirm"] = "part of it could not be done"
    return steps, refused


def act(actions, turn):
    """Plan; run at once when nothing asks first, else leave it pending."""
    v = vc()
    if turn.pending is not None:
        raise ToolError("other actions are already waiting for the user's Confirm: answer now, they can ask again "
                        "after")
    world = turn.get_world()
    steps, refused = plan_actions(actions, world, turn.lang, turn.conf["confirm"] == "all")
    if not steps:
        return {"done": "nothing", "refused": refused or ["no action"]}
    if any(s["confirm"] for s in steps):
        turn.pending = {"id": uuid.uuid4().hex[:10], "t": time.time(), "lang": turn.lang, "actions": actions,
                        "lines": [s["say"] + (f"  ({s['confirm']})" if s["confirm"] else "") for s in steps],
                        "refused": refused}
        return {"status": "NOT DONE YET: it waits for the user to press Confirm. Do not say it is done; say "
                          "what will happen when they confirm",
                "would_do": turn.pending["lines"], "refused": refused}
    problems, undo = v.execute(steps, world)
    turn.undo = undo + turn.undo
    turn.done += [s["say"] for s in steps]
    return {"done": [s["say"] for s in steps], "problems": problems, "refused": refused}


def t_actions(args, turn):
    return act(args["actions"], turn)


PEERS = os.path.join(HERE, "peers.py")
PEERS_CONF = os.path.join(os.path.dirname(HERE), "peers.json")


def machines_paired():
    """Is a machine paired and sharing on (peers.py)? Without one the
    ask_machine tool is not offered at all."""
    try:
        with open(PEERS_CONF) as handle:
            conf = json.load(handle)
        return bool(conf.get("enabled") and conf.get("peers"))
    except (OSError, ValueError, AttributeError):
        return False


def t_machine(name, args, turn):
    """ask_machine: peers.py recall -- the other machine answers from its own
    memory, if it shares it (Settings > Machines there); read-only."""
    argv = [sys.executable, PEERS, "recall", "--json"] + (["--to", args["machine"]] if args.get("machine") else []) \
        + ["--", args["query"]]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=200)
        data = json.loads(r.stdout or "null") or {}
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ToolError("the other machine did not answer") from None
    if r.returncode or not data.get("ok"):
        raise ToolError(data.get("why") or "the other machine did not answer")
    return {"machine": (data.get("me") or {}).get("name"), "answer": data.get("answer"),
            "links": data.get("links") or []}


RUN = {"search_memory": t_memory, "search_activity": t_memory, "search_files": t_memory,
       "search_clipboard": t_memory, "search_meaning": t_memory, "ask_machine": t_machine}


def call_tool(name, args, turn):
    """One checked tool call -> its result (a dict), or an "error" one."""
    if name not in TOOLS:
        return {"error": f"there is no tool “{name}”: use only the TOOLS listed"}
    if name not in tools_on(turn.conf):
        return {"error": f"the tool {name} is switched off (Settings > Assistant): say so"}
    try:
        args = check_args(name, args)
        if name in RUN:
            return RUN[name](name, args, turn)
        return {"look_at_screen": t_look, "project": t_project, "do_actions": t_actions,
                "list_windows": t_windows, "sessions": t_sessions, "timers": t_timers, "brief": t_brief,
                "read_file": t_read, "repo_changes": t_repo}[name](args, turn)
    except ToolError as err:
        return {"error": str(err)}
    except Exception as err:    # noqa: BLE001 -- a tool that breaks costs that step only
        log(f"{name} failed: {type(err).__name__}: {err}")
        return {"error": f"{name} failed ({type(err).__name__})"}


# -- the model -----------------------------------------------------------------------------------
def pick_model(conf, status=lambda text: None):
    """(Model, None) ready to ask, or (None, why). Local only (module docstring)."""
    w = worker()
    choice = conf["model"]
    if choice == "auto":
        try:
            if not models()._gamemode_on():
                big = vc().loaded_default()
                if big is not None:
                    return big, None
        except Exception:   # noqa: BLE001 -- LM Studio not there: ready() says why
            pass
        choice = "quick"
    status(f"getting the {choice} model ready…")
    model, why = w.ready(choice)
    return model, (why or "").removesuffix(": do the job yourself") or None


def arg_sig(key, kind, required, limit):
    """One argument as the prompt shows it: "op: current|list", "start?: ISO time"."""
    if isinstance(limit, tuple):
        shape = f"{limit[0]}-{limit[1]}" if kind == "int" else "|".join(limit)
    else:
        shape = {"time": "ISO time", "int": "number", "bool": "true|false", "list": "[names]",
                 "actions": "[{action, ...}]"}.get(kind, "text")
    return f"{key}{'' if required else '?'}: {shape}"


EXAMPLES = [
    ("what changed in atlas today?", {"tool": "repo_changes", "args": {"repo": "atlas", "since": "today"}}),
    ("put the theme to matrix", {"tool": "do_actions", "args": {"actions": [{"action": "theme", "value": "matrix"}]}}),
    ("which project am I in?", {"tool": "project", "args": {"op": "current"}}),
    ("compare these two windows", {"tool": "look_at_screen", "args": {"what": "windows",
                                                                     "question": "Compare these two windows."}}),
    ("summarise the error on screen", {"tool": "look_at_screen", "args": {"what": "window",
                                                                         "question": "Summarise the error."}}),
    ("(after a result that says enough)", {"tool": "answer", "answer": "You were in atlas from 09:10 to 12:40."}),
]


def system_prompt(conf, lang, now, world=None):
    names = tools_on(conf)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tools = "\n".join(f"  {n}({', '.join(arg_sig(k, *spec) for k, spec in TOOLS[n][1].items())}): "
                      f"{TOOLS[n][2]}" for n in names)
    v = vc()
    acts = ""
    if "do_actions" in names:
        acts = ("\nACTIONS for do_actions ({\"actions\": [{\"action\": NAME, ...arguments}]}):\n" +
                "\n".join(f"  {a}: {v.ARG_HELP[a]}" for a in v.CATALOG if a not in LEFT_OUT))
        if world is not None:
            try:
                acts += (f"\nTHEMES: {', '.join(world.themes()) or 'none'}\nSESSIONS: "
                         f"{', '.join(world.sessions()) or 'none'}\nPROJECTS: {', '.join(world.contexts()) or 'none'}")
            except Exception:   # noqa: BLE001 -- the prompt goes without the names
                pass
    language = {"es": "Answer in Spanish.", "en": "Answer in English."}.get(
        conf["language"], "Answer in the language of the user's last message (Spanish or English).")
    return (
        "You are the desktop assistant of this Linux (Hyprland) computer. You look things up and act ONLY "
        "through the tools below; you cannot run commands or code. Reply with ONE JSON object each time: "
        "{\"tool\": NAME, \"args\": {...}} to use a tool, or {\"tool\": \"answer\", \"answer\": \"...\"} when "
        "you can answer. Use tools instead of guessing; one tool per reply; after a result, either use "
        "another tool or answer. Never claim you did something a tool result does not say was done. "
        "When an action is waiting for the user's Confirm click, say what will happen when they confirm. "
        f"{language} Be brief and concrete; plain text, short lists.\n"
        f"Now: {now:%A %Y-%m-%d %H:%M} local time. Yesterday: {day - datetime.timedelta(days=1):%Y-%m-%d}. "
        f"'Before lunch' means 08:00-13:30 of {'today' if now.hour >= 13 else 'yesterday (it is not lunch time yet today)'}; "
        "'this morning' 06:00-12:00. Give times to tools as ISO local date-times (2026-10-21T09:00).\n"
        "To 'reopen' what the user was doing: find it (search_activity / search_memory), then act on it -- "
        "launch the app, open-folder for a repo or folder, open-url for a page, context for a project, "
        "sessions for windows that were closed. To see, read or compare what is IN windows or on the screen, "
        "use look_at_screen; do_actions only changes things.\n"
        f"TOOLS (arguments go in \"args\"; ? = optional):\n{tools}{acts}\nEXAMPLES:\n"
        + "\n".join(f"  {said} -> {json.dumps(reply, ensure_ascii=False)}" for said, reply in EXAMPLES
                     if reply["tool"] in names + ["answer"]))


def make_chat(model):
    """chat(messages, names) -> the model's reply text: llm-worker.py's ask()
    with the whole conversation and the step schema."""
    def chat(messages, names):
        return worker().ask(model, "", "", extra={
            "messages": messages, "temperature": 0.2, "max_tokens": MAX_TOKENS, "reasoning_effort": "none",
            "response_format": reply_schema(names)})
    return chat


# -- one question ------------------------------------------------------------------------------------
def run_turn(question, conf=None, lang=None, history=None, chat=None, world=None, hooks=None,
             on_step=None, status=lambda text: None, now=None, who="assistant"):
    """The whole tool loop for one question. Returns the turn as a dict
    ({"id", "t", "question", "lang", "answer", "steps", "pending", "done",
    "model", "seconds"}) and, under "undo", the ops that take back what was
    done (not kept on disk). `chat`: tests hand in a stub (messages, names)
    -> text; `on_step(step)` hears each step as it happens. `who`: whose
    folder access counts (folder_access.py): "phone" for phone-ask.py."""
    conf = conf or settings()
    question = " ".join(str(question or "").split())[:4000]
    lang = lang if lang in ("es", "en") else (conf["language"] if conf["language"] in ("es", "en")
                                               else guess_language(question))
    started = time.time()
    out = {"id": uuid.uuid4().hex[:12], "t": started, "question": question, "lang": lang, "answer": "",
           "steps": [], "pending": None, "done": [], "model": "", "undo": []}
    if conf["enabled"] != "on":
        out["answer"] = WORDS[lang]["off"]
        return out
    if not question:
        return out
    history = read_history() if history is None else history
    model_name = "stub"
    if chat is None:
        model, why = pick_model(conf, status)
        if model is None:
            out["answer"] = f"{WORDS[lang]['no_model']}: {why}"
            return out
        chat, model_name = make_chat(model), model.name
    out["model"] = model_name
    turn = Turn(question, lang, conf, world, hooks, [r.get("question", "") for r in history[-HISTORY_TURNS:]], who)
    names = tools_on(conf)
    messages = [{"role": "system", "content": system_prompt(conf, lang, now or datetime.datetime.now(),
                                                            turn.get_world() if "do_actions" in names else None)}]
    messages += context_messages(history)
    messages.append({"role": "user", "content": question})
    answer = None
    for step_no in range(conf["max_steps"] + 1):
        last = step_no == conf["max_steps"]
        if last:
            messages.append({"role": "user", "content": "Now answer the user with what you have: "
                             "{\"tool\": \"answer\", \"answer\": \"...\"}."})
        status(f"{model_name} · {WORDS[lang]['thinking']}")
        try:
            reply = chat(messages, [] if last else names)
        except Exception as err:    # noqa: BLE001 -- the server, a timeout: said in the chat
            answer = f"The local model did not answer ({type(err).__name__}: {err})"
            break
        got = parse_reply(reply)
        if got["tool"] == "answer" or last:
            answer = got["answer"] or (reply if got["tool"] == "answer" else "")
            break
        step = {"tool": got["tool"], "args": got["args"]}
        try:
            step["line"] = step_line(got["tool"], check_args(got["tool"], got["args"]), lang)
        except ToolError:
            step["line"] = step_line(got["tool"], {}, lang) if got["tool"] in TOOLS else f"✗ {got['tool']}"
        if on_step:
            on_step(dict(step, running=True))
        result = call_tool(got["tool"], got["args"], turn)
        step["ok"] = "error" not in result
        if not step["ok"]:
            step["line"] += f" ✗ {result['error']}"
        out["steps"].append(step)
        if on_step:
            on_step(step)
        log(f"step {step_no + 1}: {got['tool']} -> {'ok' if step['ok'] else result['error']}")
        messages.append({"role": "assistant", "content": json.dumps({"tool": got["tool"], "args": got["args"]},
                                                                    ensure_ascii=False)})
        messages.append({"role": "user", "content": f"Result of {got['tool']}:\n"
                         + json.dumps(result, ensure_ascii=False, default=str)[:RESULT_CHARS]})
    answer = re.sub(r"<think>.*?</think>", "", answer or "", flags=re.S).strip()
    if turn.pending:        # whatever the model said: nothing of it is done before the click
        answer = (answer + "\n\n" if answer else "") + WORDS[lang]["waiting"]
    out.update(answer=answer or "(no answer)", pending=turn.pending, done=turn.done, undo=turn.undo,
               seconds=round(time.time() - started, 1))
    if turn.pending:
        save_pending(turn.pending)
    return out


# -- pending actions (asked first) -----------------------------------------------------------------
def _pending_path(pid):
    if not re.fullmatch(r"[0-9a-f]{6,32}", str(pid or "")):
        raise ValueError("not a pending id")
    return os.path.join(RUN_DIR, f"pending-{pid}.json")


def save_pending(pending):
    os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
    for name in os.listdir(RUN_DIR):        # the ones nobody answered, gone once expired
        path = os.path.join(RUN_DIR, name)
        try:
            if name.startswith("pending-") and time.time() - os.path.getmtime(path) > PENDING_S:
                os.remove(path)
        except OSError:
            pass
    with open(_pending_path(pending["id"]), "w") as handle:
        json.dump(pending, handle, ensure_ascii=False)


def take_pending(pid):
    """The pending plan, removed (one answer per plan); None when it is
    unknown or expired."""
    path = _pending_path(pid)
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if time.time() - (data.get("t") or 0) > PENDING_S:
        return None
    return data


def confirm(pid, world=None):
    """The user said yes: checked again against the desktop as it is now,
    then done -- every step, the asking ones too. (lines done, problems,
    undo ops), or None when the plan expired."""
    data = take_pending(pid)
    if data is None:
        return None
    world = world or vc().World()
    steps, refused = plan_actions(data["actions"], world, data.get("lang", "en"))
    problems, undo = vc().execute(steps, world)
    log(f"confirmed {pid}: {len(steps)} step(s)" + (f", problems: {'; '.join(problems)}" if problems else ""))
    return [s["say"] for s in steps], problems + [f"not done: {r}" for r in refused], undo


def undo(ops):
    return [p for p in (vc().run_op(tuple(op)) for op in ops) if p]


# -- spoken replies --------------------------------------------------------------------------------
def speak(text, lang="en", conf=None):
    """THE spoken-reply hook: hands `text` to a TTS module when voice_reply is
    on and one is installed (scripts/tts.py or speak.py, with speak(text,
    lang=...)); otherwise nothing. Never blocks: a thread. True when handed over."""
    conf = conf or settings()
    if conf["voice_reply"] != "on" or not (text or "").strip():
        return False
    fn = tts_function()
    if fn is None:
        return False

    def go():
        try:
            try:
                fn(text, lang=lang)
            except TypeError:
                fn(text)
        except Exception as err:    # noqa: BLE001 -- a voice that fails costs nothing else
            log(f"speak failed: {err}")
    threading.Thread(target=go, daemon=True).start()
    return True


def tts_function():
    for filename in ("tts.py", "speak.py"):
        if os.path.exists(os.path.join(HERE, filename)):
            try:
                fn = getattr(_module(filename[:-3] + "_hook", filename), "speak", None)
            except Exception:       # noqa: BLE001 -- a broken sibling: no voice
                fn = None
            if callable(fn):
                return fn
    return None


# -- the CLI's one question --------------------------------------------------------------------------
def ask_cli(question, lang=None, as_json=False):
    conf = settings()
    prune(conf)
    turn = run_turn(question, conf, lang)
    if conf["enabled"] == "on" and turn["question"]:
        remember(turn, conf)
    public = {k: v for k, v in turn.items() if k != "undo"}
    public["steps"] = [{"tool": s["tool"], "line": s["line"], "ok": s.get("ok", False)} for s in turn["steps"]]
    if as_json:
        print(json.dumps(public, ensure_ascii=False))
        return
    for s in public["steps"]:
        print(f"  · {s['line']}")
    print(turn["answer"])
    if turn["pending"]:
        print("\n" + "\n".join(f"  • {line}" for line in turn["pending"]["lines"]))
        print(f"  assistant.py confirm {turn['pending']['id']}   (or cancel)")


def status_data():
    conf = settings()
    rows = read_history()
    lm = models()
    roles = {}
    for role in ("default", "quick", "worker"):
        try:
            m = lm.chosen(role)
            roles[role] = {"name": m.name, "local": m.local}
        except Exception:   # noqa: BLE001
            roles[role] = {"name": "?", "local": False}
    try:
        ps = privacy()
        pconf = ps.load()
        mem = {"assistant_memory": ps.flag(pconf.get("assistant_memory", "off")), "memory_on": ps.memory_on(pconf)}
    except Exception:       # noqa: BLE001
        mem = {"assistant_memory": False, "memory_on": False}
    return {"settings": conf, "roles": roles, "tools": {g: {"title": GROUP_TEXT[g][0], "sub": GROUP_TEXT[g][1],
                                                              "tools": [n for n, t in TOOLS.items() if t[0] == g]}
                                                          for g in TOOL_GROUPS},
            "history": {"turns": len(rows), "since": rows[0]["t"] if rows else None,
                        "bytes": os.path.getsize(HISTORY) if os.path.exists(HISTORY) else 0},
            "tts": tts_function() is not None, "privacy": mem, "running": panel_running()}


# -- the panel ---------------------------------------------------------------------------------------
def panel_running():
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(SOCK)
            s.sendall(b'{"cmd": "ping"}\n')
            return s.recv(64).startswith(b"ok")
    except OSError:
        return False


def send_panel(msg):
    """Hand a command to the running panel; False when there is none."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(SOCK)
            s.sendall(json.dumps(msg).encode() + b"\n")
            return s.recv(64).startswith(b"ok")
    except OSError:
        return False


def panel_lock():
    """The one-panel lock (flock on RUN_DIR/panel.lock, held while this
    process lives): the open file, or None when another panel holds it --
    two `open`s at once (a double press) must not make two panels."""
    os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
    handle = open(os.path.join(RUN_DIR, "panel.lock"), "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    _LOCKS.append(handle)
    return handle


_LOCKS = []


def panel_main(show=True, voice=False, question=None, render=None):
    """The chat panel. render=(out.png, [(question, answer)]): drawn off
    screen into out.png instead (no layer surface, no socket, no grab)."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango
    sys.path.insert(0, WAYBAR)
    import panelui

    class Panel(Gtk.OffscreenWindow if render else Gtk.Window):
        def __init__(self):
            super().__init__()
            self.conf = settings()
            self.history = read_history() if self.conf["history_days"] > 0 else []
            self.session = []           # this panel's turns when nothing is kept on disk
            self.busy = False
            self.rec = self.rec_path = None
            self.hidden_at = None
            self.recall = None
            self.set_name("panel-window")
            self.set_app_paintable(True)
            visual = self.get_screen().get_rgba_visual()
            if visual:
                self.set_visual(visual)
            if not render:
                GtkLayerShell.init_for_window(self)
                GtkLayerShell.set_namespace(self, "waybar-panel")
                GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
                GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
                for edge in (GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM):
                    GtkLayerShell.set_anchor(self, edge, True)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 12)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 52)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 12)
                mon = smartclip()._focused_monitor(Gdk)
                if mon:
                    GtkLayerShell.set_monitor(self, mon)
            self.connect("key-press-event", self.on_key)
            self.connect("delete-event", lambda *_a: self.quit())

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.set_name("panel")
            card.set_size_request(PANEL_W, 640 if render else -1)
            self.add(card)
            top = Gtk.Box(spacing=6)
            heading = Gtk.Label(label="ASSISTANT", xalign=0)
            heading.get_style_context().add_class("kb-heading")
            top.pack_start(heading, True, True, 0)
            top.pack_end(self.button("\uf00d", self.hide_panel, "Hide (Esc)"), False, False, 0)
            top.pack_end(self.button("\uf013", lambda: subprocess.Popen(
                [sys.executable, os.path.join(HERE, "settings.py"), "assistant"], start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), "Settings > Assistant"), False, False, 0)
            top.pack_end(self.button("Forget", self.forget, "Forget the whole conversation"), False, False, 0)
            card.pack_start(top, False, False, 0)
            self.model_line = self.sub(self.model_text())
            card.pack_start(self.model_line, False, False, 0)

            self.log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            self.log_box.set_margin_end(10)
            self.scroll = Gtk.ScrolledWindow()
            self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.scroll.add(self.log_box)
            card.pack_start(self.scroll, True, True, 0)

            self.status = self.sub("")
            card.pack_start(self.status, False, False, 0)
            line = Gtk.Box(spacing=6)
            self.entry = Gtk.Entry()
            self.entry.set_placeholder_text("Ask, or tell it what to do…  (Enter)")
            self.entry.connect("activate", lambda e: self.ask(e.get_text()))
            line.pack_start(self.entry, True, True, 0)
            self.mic = None
            if shutil.which("pw-record"):
                self.mic = self.button("\uf130", self.toggle_mic, "Say it (press again to stop) · Ctrl+M")
                line.pack_start(self.mic, False, False, 0)
            line.pack_start(self.button("\uf1d8", lambda: self.ask(self.entry.get_text()), "Ask (Enter)"),
                            False, False, 0)
            card.pack_start(line, False, False, 0)
            card.pack_start(self.sub("Enter asks · Esc hides · ↑ the last question · Ctrl+M the microphone · "
                                     "local model only"), False, False, 0)
            for row in (render[1] if render else self.history[-HISTORY_TURNS:]):
                if render:
                    q, a = row
                    row = {"question": q, "answer": a, "steps": ["searched the desktop memory for “lunch”",
                                                                 "looked at the focused window"]}
                parts = self.add_turn(row, kept=True)
            if render:      # the last one as if it asked first: the Confirm row's look
                self.offer(parts, {"lang": "en", "answer": "", "undo": [], "pending": {
                    "id": "0" * 10, "lines": ["open the folder ~/Projects/atlas", "open Firefox"]}})
            self.entry.grab_focus()
            if not render:
                self.listen()
                GLib.timeout_add_seconds(60, self.idle_check)
            if question:
                GLib.idle_add(lambda: (self.ask(question), False)[1])
            if voice and self.mic:
                GLib.idle_add(lambda: (self.toggle_mic(), False)[1])

        # -- pieces --
        def sub(self, text):
            lab = Gtk.Label(label=text, xalign=0)
            lab.get_style_context().add_class("ctl-sub")
            lab.set_line_wrap(True)
            lab.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lab.set_max_width_chars(58)
            return lab

        def button(self, caption, action, tip=None):
            b = Gtk.Button(label=caption)
            b.get_style_context().add_class("dev-pick")
            b.connect("clicked", lambda _b: action())
            if tip:
                b.set_tooltip_text(tip)
            return b

        def model_text(self):
            names = {"auto": "the big model when it is loaded, else the quick one", "default": "the default model",
                     "quick": "the quick model", "worker": "the worker model"}
            kept = (f"kept {self.conf['history_days']} day(s)" if self.conf["history_days"]
                    else "not kept after this panel closes")
            off = "" if self.conf["enabled"] == "on" else "TURNED OFF · "
            return f"{off}Local only: {names[self.conf['model']]} · conversation {kept}"

        def add_turn(self, row, kept=False):
            """One exchange in the log; returns its widgets for the live updates."""
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            q = Gtk.Label(label="› " + row["question"], xalign=0)
            q.get_style_context().add_class("ctl-title")
            q.set_line_wrap(True)
            q.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            q.set_max_width_chars(58)
            q.set_selectable(True)
            box.pack_start(q, False, False, 0)
            steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.pack_start(steps, False, False, 0)
            for line in row.get("steps") or []:
                steps.pack_start(self.sub("· " + line), False, False, 0)
            answer = Gtk.Label(label=row.get("answer", ""), xalign=0, yalign=0)
            answer.set_selectable(True)
            answer.set_line_wrap(True)
            answer.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            answer.set_max_width_chars(58)
            box.pack_start(answer, False, False, 0)
            buttons = Gtk.Box(spacing=6)
            box.pack_start(buttons, False, False, 0)
            self.log_box.pack_start(box, False, False, 0)
            box.show_all()
            parts = {"box": box, "steps": steps, "answer": answer, "buttons": buttons, "running": None}
            self.scroll_down()
            return parts

        def scroll_down(self):
            def go():
                adj = self.scroll.get_vadjustment()
                adj.set_value(adj.get_upper())
                return False
            GLib.timeout_add(60, go)

        def say(self, text):
            GLib.idle_add(self.status.set_text, text)

        # -- asking --
        def ask(self, question):
            question = (question or "").strip()
            if not question or self.busy:
                return
            self.busy = True
            self.recall = question
            self.entry.set_text("")
            self.conf = settings()
            parts = self.add_turn({"question": question, "answer": "…"})
            history = self.history + self.session

            def on_step(step):
                GLib.idle_add(self.show_step, parts, step)

            def work():
                return run_turn(question, self.conf, history=history, hooks={
                    "hide": self.step_aside, "show": self.come_back,
                    "asking": lambda folder: self.say(f"Waiting for your answer: may the assistant read "
                                                      f"{short_path(folder)}? (Esc on the prompt denies)")},
                                on_step=on_step, status=self.say)

            def done(turn, exc):
                self.busy = False
                if exc:
                    parts["answer"].set_text(f"Could not answer: {exc}")
                    self.status.set_text("")
                    return
                parts["answer"].set_text(turn["answer"])
                self.status.set_text(f"{turn['model']} · {turn.get('seconds', 0)} s · local" if turn["model"] else "")
                row = history_row(turn)
                if self.conf["history_days"] > 0:
                    self.history.append(row)
                else:
                    self.session.append(row)
                if turn["question"] and self.conf["enabled"] == "on":
                    threading.Thread(target=remember, args=(turn, self.conf), daemon=True).start()
                self.offer(parts, turn)
                speak(turn["answer"], turn["lang"], self.conf)
                self.scroll_down()
                self.entry.grab_focus()
            self.in_thread(work, done)

        def show_step(self, parts, step):
            if step.get("running"):
                parts["running"] = self.sub("· " + step["line"] + " …")
                parts["steps"].pack_start(parts["running"], False, False, 0)
                parts["running"].show()
            elif parts["running"] is not None:
                parts["running"].set_text("· " + step["line"])
                parts["running"] = None
            self.scroll_down()
            return False

        def offer(self, parts, turn):
            w = WORDS[turn["lang"]]
            box = parts["buttons"]
            if turn["pending"]:
                for line in turn["pending"]["lines"]:
                    parts["steps"].pack_start(self.sub("→ " + line), False, False, 0)
                pid = turn["pending"]["id"]
                box.pack_start(self.button(w["confirm"], lambda: self.decide(parts, pid, True, w)), False, False, 0)
                box.pack_start(self.button(w["cancel"], lambda: self.decide(parts, pid, False, w)), False, False, 0)
            elif turn["undo"]:
                ops = turn["undo"]
                box.pack_start(self.button(w["undo"], lambda: self.take_back(parts, ops, w)), False, False, 0)
            box.pack_start(self.button("Copy", lambda: subprocess.run(["wl-copy"], input=turn["answer"], text=True)),
                           False, False, 0)
            parts["box"].show_all()

        def decide(self, parts, pid, yes, w):
            for child in parts["buttons"].get_children():
                child.set_sensitive(False)
            if not yes:
                try:
                    take_pending(pid)
                except ValueError:
                    pass
                parts["steps"].pack_start(self.sub(w["cancelled"]), False, False, 0)
                parts["box"].show_all()
                return

            def done(result, exc):
                if exc or result is None:
                    text = w["expired"] if result is None and not exc else f"{w['failed']}: {exc}"
                else:
                    lines, problems, ops = result
                    text = w["done"] + ": " + "; ".join(lines) + ("" if not problems else "\n✗ " + "\n✗ ".join(problems))
                    if ops and not problems:
                        parts["buttons"].pack_start(self.button(w["undo"], lambda: self.take_back(parts, ops, w)),
                                                    False, False, 0)
                parts["steps"].pack_start(self.sub(text), False, False, 0)
                parts["box"].show_all()
            self.in_thread(lambda: confirm(pid), done)

        def take_back(self, parts, ops, w):
            for child in parts["buttons"].get_children():
                if child.get_label() == w["undo"]:
                    child.set_sensitive(False)

            def done(problems, exc):
                text = w["undone"] if not (exc or problems) else f"{w['failed']}: {exc or problems[0]}"
                parts["steps"].pack_start(self.sub(text), False, False, 0)
                parts["box"].show_all()
            self.in_thread(lambda: undo(ops), done)

        def forget(self):
            clear()
            self.history, self.session = [], []
            for child in self.log_box.get_children():
                self.log_box.remove(child)
            self.status.set_text("Forgotten: the conversation is gone from this computer.")

        def in_thread(self, work, done):
            def run():
                try:
                    result = work()
                    GLib.idle_add(done, result, None)
                except Exception as exc:    # noqa: BLE001 -- shown in the panel
                    GLib.idle_add(done, None, exc)
            threading.Thread(target=run, daemon=True).start()

        # -- out of the screenshots --
        def step_aside(self):
            ev = threading.Event()

            def go():
                self.stepped_aside = self.get_visible()     # hidden by the user meanwhile: stays hidden
                self.hide()
                ev.set()
                return False
            GLib.idle_add(go)
            ev.wait(3)
            time.sleep(0.35)        # the compositor draws the screen without the panel

        def come_back(self):
            GLib.idle_add(lambda: (getattr(self, "stepped_aside", False) and self.show(), False)[1])

        # -- the microphone (voice.py's daemon transcribes) --
        def toggle_mic(self):
            if self.rec:
                self.stop_mic()
                return
            # a spoken answer still going would be recorded as the question:
            # talking over it stops it (tts.py's stop(); nothing when idle)
            try:
                _module("tts_hook", "tts.py").stop()
            except Exception:       # noqa: BLE001 -- no TTS module: nothing to stop
                pass
            os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
            fd, self.rec_path = tempfile.mkstemp(prefix="rec-", suffix=".raw", dir=RUN_DIR)
            self.rec = subprocess.Popen(["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16",
                                         "--raw", "-P", '{ media.name="Assistant" }', "-"],
                                        stdout=fd, stderr=subprocess.DEVNULL)
            os.close(fd)
            self.mic.get_style_context().add_class("active")
            self.status.set_text("listening… press the microphone again to stop")
            rec = self.rec
            GLib.timeout_add_seconds(MAX_RECORD_S, lambda: (self.rec is rec and self.stop_mic(), False)[1])

        def stop_mic(self, keep=True):
            proc, path, self.rec = self.rec, self.rec_path, None
            if not proc:
                return
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.kill()
            self.mic.get_style_context().remove_class("active")
            if not keep:
                _remove(path)
                return
            self.status.set_text("transcribing…")

            def work():
                try:
                    return _module("voice_client", "voice.py").request({"cmd": "transcribe", "path": path},
                                                                        timeout=180)
                finally:
                    _remove(path)

            def done(answer, exc):
                answer = answer or {}
                said = (answer.get("text") or "").strip()
                if exc or answer.get("error") or not said:
                    self.status.set_text(f"voice: {exc or answer.get('error') or 'heard nothing'}")
                    return
                self.status.set_text("")
                self.entry.set_text(said)
                self.entry.set_position(-1)
                self.entry.grab_focus()
            self.in_thread(work, done)

        # -- showing, hiding, the socket --
        def on_key(self, _w, event):
            ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
            if event.keyval == Gdk.KEY_Escape:
                self.hide_panel()
                return True
            if event.keyval == Gdk.KEY_Up and not self.entry.get_text() and self.recall:
                self.entry.set_text(self.recall)
                self.entry.set_position(-1)
                return True
            if ctrl and event.keyval in (Gdk.KEY_m, Gdk.KEY_M) and self.mic:
                self.toggle_mic()
                return True
            return False

        def hide_panel(self):
            self.stop_mic(keep=False)
            self.hide()
            self.hidden_at = time.time()

        def show_panel(self):
            self.hidden_at = None
            self.conf = settings()
            self.model_line.set_text(self.model_text())
            self.show()
            self.present()
            self.entry.grab_focus()

        def idle_check(self):
            if self.hidden_at and time.time() - self.hidden_at > IDLE_QUIT_S and not self.busy:
                self.quit()
                return False
            return True

        def listen(self):
            os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
            try:
                os.unlink(SOCK)
            except OSError:
                pass
            self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server.bind(SOCK)
            os.chmod(SOCK, 0o600)
            self.server.listen(4)
            GLib.io_add_watch(self.server.fileno(), GLib.IO_IN, self.on_client)

        def on_client(self, *_a):
            conn, _ = self.server.accept()
            with conn:
                conn.settimeout(2)
                try:
                    msg = json.loads(conn.recv(65536).decode() or "{}")
                except (OSError, ValueError):
                    msg = {}
                cmd = msg.get("cmd")
                if cmd == "toggle" and self.get_visible():
                    self.hide_panel()
                elif cmd in ("show", "toggle"):
                    self.show_panel()
                    if isinstance(msg.get("ask"), str) and msg["ask"]:
                        self.ask(msg["ask"])
                    if msg.get("voice") and self.mic and not self.rec:
                        self.toggle_mic()
                elif cmd == "clear":
                    self.forget()
                try:
                    conn.sendall(b"ok\n")
                except OSError:
                    pass
            return True

        def quit(self):
            self.stop_mic(keep=False)
            try:
                os.unlink(SOCK)
            except OSError:
                pass
            if self.conf["history_days"] <= 0:
                self.session = []
            Gtk.main_quit()

    panelui.load_css()
    panel = Panel()
    signal.signal(signal.SIGTERM, lambda *_a: GLib.idle_add(panel.quit))
    if render:
        panel.show_all()
        for _ in range(60):
            while Gtk.events_pending():
                Gtk.main_iteration()
            time.sleep(0.02)
        panel.get_pixbuf().savev(render[0], "png", [], [])
        return
    if show:
        panel.show_all()
    Gtk.main()


def _remove(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


# -- the command line ------------------------------------------------------------------------------
def option(rest, flag):
    if flag in rest:
        i = rest.index(flag)
        if i + 1 < len(rest):
            value = rest[i + 1]
            del rest[i:i + 2]
            return value
    return None


def human_status(data):
    conf = data["settings"]
    lines = [f"assistant: {conf['enabled']} · model {conf['model']} · {conf['max_steps']} steps · confirm "
             f"{conf['confirm']} · history {conf['history_days']} day(s) ({data['history']['turns']} kept) · "
             f"voice reply {conf['voice_reply']}{'' if data['tts'] else ' (no TTS module)'}"]
    for g in TOOL_GROUPS:
        lines.append(f"  {conf['tool_' + g]:3} {g:9} {', '.join(data['tools'][g]['tools'])}")
    return "\n".join(lines)


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], list(argv[1:])
    as_json = "--json" in rest
    rest = [r for r in rest if r != "--json"]
    if cmd in ("open", "toggle"):
        voice = "--voice" in rest
        question = option(rest, "--ask")
        msg = {"cmd": "show" if cmd == "open" else "toggle", "voice": voice, "ask": question}
        if send_panel(msg):
            return
        lock = panel_lock()
        if lock is None:        # another one is starting (a double press): hand it this once it listens
            for _ in range(50):
                time.sleep(0.1)
                if send_panel(msg):
                    return
            sys.exit("assistant: another panel is starting but does not answer")
        panel_main(voice=voice, question=question)
    elif cmd == "ask" and rest:
        lang = option(rest, "--lang")
        ask_cli(" ".join(rest), lang, as_json)
    elif cmd in ("confirm", "cancel") and len(rest) == 1:
        try:
            if cmd == "cancel":
                print("cancelled" if take_pending(rest[0]) else "nothing pending under that id")
                return
            result = confirm(rest[0])
        except ValueError as err:
            sys.exit(f"assistant: {err}")
        if result is None:
            sys.exit("assistant: nothing pending under that id (or it expired)")
        lines, problems, _undo = result
        print(json.dumps({"done": lines, "problems": problems}, ensure_ascii=False) if as_json
              else "\n".join([f"done: {line}" for line in lines] + [f"✗ {p}" for p in problems]))
    elif cmd == "history":
        n = int(option(rest, "-n") or 20)
        rows = read_history()[-n:]
        if as_json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            for r in rows:
                print(f"[{datetime.datetime.fromtimestamp(r['t']):%Y-%m-%d %H:%M}] {r['question']}\n  {r['answer']}")
    elif cmd == "clear":
        clear()
        send_panel({"cmd": "clear"})
        print("the conversation is forgotten")
    elif cmd == "status":
        prune()
        data = status_data()
        print(json.dumps(data, ensure_ascii=False) if as_json else human_status(data))
    elif cmd == "set" and len(rest) == 2:
        try:
            print(set_setting(rest[0], rest[1]))
        except ValueError as err:
            sys.exit(f"assistant: {err}")
    elif cmd == "tools":
        if as_json:
            print(json.dumps({n: {"group": g, "args": list(a), "help": h} for n, (g, a, h) in TOOLS.items()}))
        else:
            for n, (g, a, h) in TOOLS.items():
                print(f"{n:17} [{g}] {h}")
    elif cmd == "render" and rest:
        pairs = [(rest[1], " ".join(rest[2:]))] if len(rest) >= 3 else [
            ("what was I doing before lunch?", "You were in atlas: VS Code on ~/Projects/atlas and Firefox on "
             "localhost:8000 (09:10–12:40). Reopen it?")]
        panel_main(render=(rest[0], pairs))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
