#!/usr/bin/env python3
"""Project contexts: one key (or "project atlas" in the launcher) puts you
"in" a project -- its windows back, a terminal and the editor on its repo,
its local website preview, only its notifications -- and the bar says which.
Leaving (or entering another one) tidies that up again.

    contexts.py list [--json]          the contexts, the current one marked
    contexts.py enter NAME [--dry-run] switch into NAME (leaving the current
                                       one first); --dry-run: only say the steps
    contexts.py leave [--save|--no-save]   leave the current one
    contexts.py current [--json]       the context you are in ("" when none)
    contexts.py save NAME              the windows open now as NAME's layout
                                       (a workspace session called NAME)
    contexts.py new NAME --repo PATH [--focus none|dnd|project] [--enter]
    contexts.py set NAME KEY VALUE     change one option (KEYS below)
    contexts.py delete NAME            forget it (its saved session stays)
    contexts.py status --json          contexts + current + the repos without
                                       one, for Settings > Project contexts
    contexts.py pick                   a wofi list to choose one (a key)
    contexts.py bar                    one JSON line for waybar (custom/context)
    contexts.py ensure                 write mako's fragment if it is missing
                                       (mako.service ExecStartPre)

The contexts live in ~/.config/hypr/contexts.json, human-editable. No file
(a new desktop) just means no contexts yet: everything here still runs, the
bar pill stays hidden, and the first `new` (or Settings > Project contexts)
writes it:

    {"contexts": [
      {"name": "atlas", "repo": "~/Projects/atlas",
       "session": true, "terminal": true, "editor": true,
       "preview": "start", "focus": "project", "workspace": "3",
       "save_on_leave": false, "close_on_leave": false, "allow": ["Automations"]}
    ]}

KEYS (what each option does on enter / leave; DEFAULTS has the values a new
one starts with):

    repo            the folder (a repo in your projects folder, usually:
                    desktop_conf.py)
    session         enter: restore the workspace session named like the
                    context (sessions.py restore NAME), if one was saved --
                    what is open already is skipped, as always
    terminal        enter: a terminal in the repo (default-apps.py run
                    terminal --dir), unless one is open there already
    editor          enter: the editor on the repo folder (default-apps.py run
                    editor, or "editor_cmd" when set: "zed", "codium -n"),
                    unless an editor window has the folder open already
    preview         off | start | open: start the repo's local site
                    (waybar/scripts/repos.py preview, the git panel's
                    Preview), and "open" also opens it in the browser.
                    Leaving stops a preview this started, none other
    focus           none | dnd | project. dnd: Do Not Disturb on
                    (notify-settings.py dnd on). project: mako's
                    "project-focus" mode, in which only notifications that
                    name the project (in their summary or body), the apps in
                    "allow", this script's and the session restore's, and
                    urgent ones pop up -- the rest go quietly to the history
                    like in DND. Leaving undoes only what entering did: DND
                    that was on already stays on
    workspace       enter: go to this workspace first ("" = stay where you are)
    save_on_leave   leave: save the windows as the context's session first
    close_on_leave  leave: close the project's own windows -- terminals in
                    the repo with nothing running in them, editors and file
                    managers on it (never anything else; editors keep
                    their unsaved work themselves)
    allow           project focus: app names whose notifications still show

How the notification filter works. mako has modes and per-mode criteria
sections, and later sections win, so ~/.config/mako/generated/contexts
(written here for the context being entered) says: in project-focus mode,
invisible; then invisible=0 again for summary~ / body~ matching the name,
for each allowed app-name, and for urgency=critical. mako/config includes
that file BEFORE mako/sections, so Do Not Disturb's sections come later and
still win when both modes are on. Hidden ones stay in the history
(`makoctl restore`, the bell's panel), exactly as in DND. mako refuses its
whole config when an included file is missing, so `ensure` writes an empty
one at mako.service start (a drop-in), like notify-settings.py's.

Enter, in order: leave the current context; go to its workspace; open the
terminal and the editor and wait (a few seconds) for their windows -- so
the session restore that comes next cannot take them for its own windows of
the same class; then the session restore, detached (it notifies as it goes);
the preview; the focus; and last the bar (signal SIGNAL) and the
automations event (automations.py event context-enter NAME: rules can
react, and an automation's "context NAME" action enters one). Entering the
context you are in only opens what is missing and changes nothing else.

Where it is kept: the definitions in contexts.json (above); the current
context and what entering it turned on, in $XDG_RUNTIME_DIR/contexts.json --
a context lasts for a login, like mako's modes, which a new mako forgets.
Nothing here reads the screen, the clipboard or your activity: the saved
layout is sessions.py's, with its rules (private windows without titles,
no secrets from command lines).
"""
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sessions  # noqa: E402  (capture(), the saved sessions, hyprctl over the socket)

HOME = os.path.expanduser("~")
CONF = os.path.expanduser("~/.config/hypr/contexts.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
STATE = os.path.join(RUNTIME, "contexts.json")
LOCK = os.path.join(RUNTIME, "contexts.lock")
FRAGMENT = os.path.expanduser("~/.config/mako/generated/contexts")
REPOS = os.path.expanduser("~/.config/waybar/scripts/repos.py")
import desktop_conf  # noqa: E402

PROJECTS = desktop_conf.projects_dir()      # your projects folder (desktop.conf)
DEFAULT_APPS = os.path.join(HERE, "default-apps.py")
NOTIFY_SETTINGS = os.path.join(HERE, "notify-settings.py")
AUTOMATIONS = os.path.join(HERE, "automations.py")
SESSIONS = os.path.join(HERE, "sessions.py")
MODE = "project-focus"
SIGNAL = 24             # waybar's custom/context (21 is the toolbox bar's custom/awake)
APP = "Contexts"
ICON = ""         # diagram-project (Font Awesome solid)
WINDOW_WAIT_S = 6       # how long enter waits for the terminal's / editor's window
NAME_RE = re.compile(r"[\w][\w .-]{0,39}$")
RESERVED = {"leave", "off", "none"}         # automations' "context leave"
DEFAULTS = {"session": True, "terminal": True, "editor": True, "editor_cmd": "", "preview": "off",
            "focus": "project", "workspace": "", "save_on_leave": False, "close_on_leave": False,
            "allow": []}
CHOICES = {"preview": ("off", "start", "open"), "focus": ("none", "dnd", "project")}
BOOLS = ("session", "terminal", "editor", "save_on_leave", "close_on_leave")
DOC = ["Project contexts (contexts.py; Settings > Project contexts edits this file too).",
       "Each: name, repo, session, terminal, editor, editor_cmd, preview (off|start|open),",
       "focus (none|dnd|project), workspace, save_on_leave, close_on_leave, allow (app names).",
       "contexts.py's docstring says what each does. Keys starting with _ are ignored."]


# -- the definitions -------------------------------------------------------------------
def valid_name(name):
    return isinstance(name, str) and bool(NAME_RE.match(name)) and name.strip() == name \
        and name.lower() not in RESERVED and sessions.valid_name(name)


def short(path):
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + "/") else path


def tidy(ctx):
    """(context with every key, filled from DEFAULTS) or raise ValueError."""
    if not isinstance(ctx, dict):
        raise ValueError("a context is a JSON object")
    name = ctx.get("name")
    if not valid_name(name):
        raise ValueError(f"{name!r}: a name is 1-40 letters, digits, space . _ - (not leave/off/none)")
    repo = ctx.get("repo")
    if not isinstance(repo, str) or not repo.strip():
        raise ValueError(f"{name}: repo is a folder")
    out = {"name": name, "repo": short(os.path.abspath(os.path.expanduser(repo.strip())))}
    for key, default in DEFAULTS.items():
        value = ctx.get(key, default)
        if key in BOOLS and not isinstance(value, bool):
            raise ValueError(f"{name}: {key} is true or false")
        if key in CHOICES and value not in CHOICES[key]:
            raise ValueError(f"{name}: {key} is one of {', '.join(CHOICES[key])}")
        if key in ("workspace", "editor_cmd") and not isinstance(value, str):
            raise ValueError(f"{name}: {key} is text")
        if key == "workspace" and value and not re.fullmatch(r"-?\d+|[\w .-]{1,30}", value):
            raise ValueError(f"{name}: workspace is a number or a name")
        if key == "allow" and (not isinstance(value, list) or not all(isinstance(a, str) and a.strip()
                                                                      for a in value)):
            raise ValueError(f"{name}: allow is a list of app names")
        out[key] = [a.strip() for a in value] if key == "allow" else value
    return out


def load(path=None):
    """(contexts, problems): the good ones in file order, and a line per bad one."""
    try:
        with open(path or CONF) as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return [], []
    except (OSError, ValueError) as err:
        return [], [f"contexts.json: {err}"]
    good, bad, seen = [], [], set()
    for raw in (data.get("contexts") if isinstance(data, dict) else None) or []:
        try:
            ctx = tidy(raw)
        except ValueError as err:
            bad.append(str(err))
            continue
        if ctx["name"].lower() in seen:
            bad.append(f"{ctx['name']}: named twice (the first counts)")
            continue
        seen.add(ctx["name"].lower())
        good.append(ctx)
    return good, bad


def save_all(contexts, path=None):
    sessions.write_json(path or CONF, {"_doc": DOC, "contexts": contexts})


def find(contexts, name):
    want = (name or "").strip().lower()
    return next((c for c in contexts if c["name"].lower() == want), None)


def repo_path(ctx):
    return os.path.expanduser(ctx["repo"])


def coerce(key, value):
    """A CLI / Settings string for KEY -> its JSON value (tidy() checks it)."""
    if key in BOOLS:
        if value.lower() not in ("on", "off", "true", "false", "yes", "no", "1", "0"):
            raise ValueError(f"{key} is on or off")
        return value.lower() in ("on", "true", "yes", "1")
    if key == "allow":
        return [a.strip() for a in value.split(",") if a.strip()]
    if key in DEFAULTS or key == "repo":
        return value
    raise ValueError(f"no option {key!r} (they are: repo, {', '.join(DEFAULTS)})")


# -- the current one -------------------------------------------------------------------
def state():
    """{"name", "since", "repo", "preview", "dnd", "mode"} for the context
    you are in, or {}."""
    try:
        with open(STATE) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) and data.get("name") else {}
    except (OSError, ValueError):
        return {}


def write_state(data):
    if data:
        sessions.write_json(STATE, data)
    else:
        try:
            os.remove(STATE)
        except OSError:
            pass


# -- windows ---------------------------------------------------------------------------
def inside(path, repo):
    path, repo = (path or "").rstrip("/"), repo.rstrip("/")
    return bool(path) and (path == repo or path.startswith(repo + "/"))


def record_path(rec):
    """The folder or file a captured window is about (a terminal's folder,
    an editor's path, a file manager's folder), or ""."""
    launch = rec.get("launch") or {}
    if rec.get("kind") == "terminal":
        return launch.get("cwd") or ""
    if rec.get("kind") in ("editor", "files"):
        args = launch.get("args") or launch.get("argv", [])[1:]
        return args[-1] if args else ""
    return ""


def busy_terminal(rec):
    """A terminal running something (nvim, a build): not to be closed."""
    return rec.get("kind") == "terminal" and (bool(rec.get("note")) or rec.get("key", "").split("|")[-1] != "")


def has_window(records, kind, repo):
    return any(r.get("kind") == kind and inside(record_path(r), repo) for r in records)


def project_windows(pairs, repo):
    """The (address, record) pairs that belong to the project and may be
    closed: idle terminals in the repo, editors and file managers on it."""
    return [(addr, r) for addr, r in pairs
            if r.get("kind") in ("terminal", "editor", "files") and inside(record_path(r), repo)
            and not busy_terminal(r)]


def live(clients=None, monitors=None):
    """[(address, record)] for the windows open now (sessions.capture)."""
    clients = sessions.hypr_json("clients") if clients is None else clients
    monitors = sessions.hypr_json("monitors") if monitors is None else monitors
    index, out = sessions.desktop_index(), []
    for c in clients or []:
        rec, _ = sessions.capture(c, monitors or [], {"games": True}, (), index)
        if rec:
            out.append((c.get("address"), rec))
    return out


# -- planning (pure: tests/test_contexts.py) -------------------------------------------
def plan_enter(ctx, current, records, session_saved):
    """The steps entering `ctx` takes, as (step, detail) pairs, given the
    current context's state, the windows open now (records) and whether a
    session named like it was saved."""
    repo = repo_path(ctx)
    same = bool(current) and current.get("name", "").lower() == ctx["name"].lower()
    steps = []
    if current and not same:
        steps.append(("leave", current["name"]))
    if ctx["workspace"] and not same:
        steps.append(("workspace", ctx["workspace"]))
    if ctx["terminal"] and not has_window(records, "terminal", repo):
        steps.append(("terminal", repo))
    if ctx["editor"] and not has_window(records, "editor", repo):
        steps.append(("editor", ctx["editor_cmd"] or "default"))
    if ctx["session"] and session_saved:
        steps.append(("session", ctx["name"]))
    if ctx["preview"] != "off" and not (same and current.get("preview")):
        steps.append(("preview", ctx["preview"]))
    if ctx["focus"] != "none" and not same:
        steps.append(("focus", ctx["focus"]))
    if not same:
        steps.append(("announce", ctx["name"]))
    return steps


def plan_leave(ctx, current, save=None):
    """(step, detail) pairs for leaving: `save` None means the context's own
    save_on_leave."""
    steps = []
    if (ctx["save_on_leave"] if save is None and ctx else bool(save)) and ctx:
        steps.append(("save", ctx["name"]))
    if ctx and ctx["close_on_leave"]:
        steps.append(("close", repo_path(ctx)))
    if current.get("preview"):
        steps.append(("preview-stop", current["preview"]))
    if current.get("mode"):
        steps.append(("focus-off", "project"))
    if current.get("dnd"):
        steps.append(("focus-off", "dnd"))
    steps.append(("announce", current.get("name", "")))
    return steps


def ere_literal(text):
    """`text` as a POSIX ERE matching it as written, lower, UPPER or
    Capitalized (mako's regex has no ignore-case flag), quoted for a mako
    criteria value."""
    def esc(s):
        return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", s)
    forms = list(dict.fromkeys([text, text.lower(), text.upper(), text.capitalize()]))
    pattern = "(" + "|".join(esc(f) for f in forms) + ")"
    return '"' + pattern.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mako_quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_fragment(ctx=None):
    """mako/generated/contexts: the project-focus sections for `ctx` (None:
    only a comment, which leaves mako as it was)."""
    lines = ["# GENERATED by ~/.config/hypr/scripts/contexts.py -- do not edit. The notification",
             "# filter of the current project context (mode project-focus); included by mako/config",
             "# before mako/sections, so Do Not Disturb still wins when both are on."]
    if not ctx:
        return "\n".join(lines) + "\n"
    sound = "on-notify=exec ~/.config/hypr/scripts/theme-sound.sh notify"
    lines += ["", f"# {ctx['name']}: hide everything, then let the project's own through.",
              f"[mode={MODE}]", "invisible=1", "on-notify=none"]
    shown = [f"summary~={ere_literal(ctx['name'])}", f"body~={ere_literal(ctx['name'])}",
             "urgency=critical"]
    shown += [f"app-name={mako_quote(a)}" for a in [APP, "Sessions"] + ctx.get("allow", [])]
    for crit in shown:
        lines += ["", f"[mode={MODE} {crit}]", "invisible=0", sound]
    lines += ["", "# low urgency stays silent (mako/sections)", f"[mode={MODE} urgency=low]", "on-notify=none"]
    return "\n".join(lines) + "\n"


# -- doing -----------------------------------------------------------------------------
def run(*cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def spawn(argv, cwd=None):
    try:
        subprocess.Popen(argv, cwd=cwd or HOME, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def notify(summary, body="", urgency="low"):
    run("notify-send", "-a", APP, "-i", "folder-open", "-u", urgency, summary, body, timeout=5)


def bar_signal():
    run("pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar", timeout=3)


def automation_event(event, name):
    """automations.py event context-enter|context-leave NAME (nothing when
    the daemon is not running). Waited for, not spawned: run from a
    transient unit (an automation's "context" action), a child left behind
    dies with the unit before it has said anything."""
    if os.path.exists(AUTOMATIONS):
        run(sys.executable, AUTOMATIONS, "event", event, name, timeout=5)


def unit(argv):
    """`argv` as a transient service of its own, so it outlives this run
    (automations.py's unit())."""
    return ["systemd-run", "--user", "--quiet", "--collect", "--"] + argv if shutil.which("systemd-run") else argv


def write_fragment(text):
    os.makedirs(os.path.dirname(FRAGMENT), exist_ok=True)
    tmp = f"{FRAGMENT}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, FRAGMENT)


def mako_modes():
    out = run("makoctl", "mode", timeout=3)
    return out.stdout.split() if out and out.returncode == 0 else None


def focus_project(ctx):
    """Write the filter for `ctx`, reload mako, turn the mode on. True when
    mako took it; on a rejected config the empty fragment goes back."""
    write_fragment(render_fragment(ctx))
    done = run("makoctl", "reload", timeout=5)
    if not done or done.returncode != 0:
        write_fragment(render_fragment(None))
        run("makoctl", "reload", timeout=5)
        return False
    run("makoctl", "mode", "-a", MODE, timeout=3)
    return MODE in (mako_modes() or [])


def focus_project_off():
    run("makoctl", "mode", "-r", MODE, timeout=3)
    write_fragment(render_fragment(None))
    run("makoctl", "reload", timeout=5)


def dnd(on):
    return run(sys.executable, NOTIFY_SETTINGS, "dnd", "on" if on else "off", timeout=10)


def dnd_now():
    return "do-not-disturb" in (mako_modes() or [])


def wait_windows(before, count, timeout=WINDOW_WAIT_S, sleep=time.sleep, clock=time.monotonic):
    """Wait until `count` new windows (not in `before`) are mapped."""
    deadline = clock() + timeout
    while count > 0 and clock() < deadline:
        sleep(0.25)
        now = {c.get("address") for c in sessions.hypr_json("clients") or [] if c.get("mapped", True)}
        if len(now - before) >= count:
            return True
    return count <= 0


def editor_argv(ctx):
    repo = repo_path(ctx)
    if ctx["editor_cmd"]:
        import shlex
        try:
            return sessions.in_scope(shlex.split(ctx["editor_cmd"]) + [repo])
        except ValueError:
            return None
    return sessions.in_scope([sys.executable, DEFAULT_APPS, "run", "editor", repo])


def repos_module():
    import importlib.util
    mod = sys.modules.get("repos")
    if mod is None:
        spec = importlib.util.spec_from_file_location("repos", REPOS)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, os.path.dirname(REPOS))
        spec.loader.exec_module(mod)
        sys.modules["repos"] = mod
    return mod


def close_window(address):
    return sessions.hypr_eval(
        f"hl.dispatch(hl.dsp.window.close({{ window = {sessions.lua_str('address:' + address)} }}))")


@contextlib.contextmanager
def busy(timeout=30, sleep=time.sleep):
    """One enter / leave / delete at a time (a double key press, the bar and
    an automation together): the second waits for the first, so it does not
    see a half-written state, leave twice or open a second terminal. Taken
    in main() and pick() only -- enter() calls leave(), and a second flock on
    the same file from this process would wait for itself."""
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("another contexts.py is still switching")
                sleep(0.2)
        yield
    finally:
        os.close(fd)        # closing drops the lock


def leave(save=None, quiet=False):
    """Leave the current context; returns what was done, in words."""
    current = state()
    if not current:
        return []
    ctx = find(load()[0], current["name"])
    said = []
    for step, detail in plan_leave(ctx, current, save):
        if step == "save" and sessions.hypr_json("monitors") is not None:
            data = sessions.snapshot()
            sessions.write_json(sessions.session_path(detail), data)
            said.append(f"layout saved ({len(data['windows'])} windows)")
        elif step == "close":
            gone = [r["app"] for addr, r in project_windows(live(), detail) if close_window(addr)]
            if gone:
                said.append(f"closed {len(gone)} window{'s' * (len(gone) != 1)}")
        elif step == "preview-stop":
            try:
                repos_module().preview_stop(detail)
                said.append("preview stopped")
            except Exception:       # noqa: BLE001 - repos.py broken: the preview just runs out (2 h)
                pass
        elif step == "focus-off" and detail == "project":
            focus_project_off()
        elif step == "focus-off" and detail == "dnd":
            dnd(False)
            said.append("Do Not Disturb off")
    write_state({})
    bar_signal()
    automation_event("context-leave", current["name"])
    if not quiet:
        notify(f"Left {current['name']}", "  ·  ".join(said))
    return said


def enter(name, dry=False):
    """Switch into context `name`. Returns (exit code, the steps)."""
    contexts, _ = load()
    ctx = find(contexts, name)
    if ctx is None:
        return f"contexts: no context called {name!r} (contexts.py list)", []
    repo = repo_path(ctx)
    if not os.path.isdir(repo):
        return f"contexts: {ctx['repo']} is not a folder", []
    current = state()
    records = [r for _, r in live()]
    steps = plan_enter(ctx, current, records, sessions.load_session(ctx["name"]) is not None)
    if dry:
        return 0, steps
    same = bool(current) and current.get("name", "").lower() == ctx["name"].lower()
    new_state = dict(current) if same else {"name": ctx["name"], "repo": ctx["repo"], "since": int(time.time())}
    said, before, launched = [], {c.get("address") for c in sessions.hypr_json("clients") or []}, 0
    for step, detail in steps:
        if step == "leave":
            leave(quiet=True)
        elif step == "workspace":
            sel = detail if re.fullmatch(r"-?\d+", detail) else "name:" + detail
            sessions.hypr_eval(f"hl.dispatch(hl.dsp.focus({{ workspace = {sessions.lua_str(sel)} }}))")
        elif step == "terminal":
            if spawn(sessions.in_scope([sys.executable, DEFAULT_APPS, "run", "terminal", "--dir", repo]), repo):
                launched += 1
                said.append("terminal")
        elif step == "editor":
            argv = editor_argv(ctx)
            if argv and spawn(argv, repo):
                launched += 1
                said.append("editor")
        elif step == "session":
            if launched:        # first their windows, so the restore does not take them for its own
                wait_windows(before, launched)
            spawn(unit([sys.executable, SESSIONS, "restore", detail]))
            said.append("its session")
        elif step == "preview":
            try:
                mod = repos_module()
                # one running already (the git panel's) is not ours: leaving must not stop it
                ran = bool(getattr(mod, "previewing", lambda _p: "")(repo))
                ok, url = mod.preview(repo)
            except Exception as err:    # noqa: BLE001 - say it, go on with the rest
                ok, url, ran = False, str(err), True
            if ok:
                if not ran:
                    new_state["preview"] = repo
                said.append(f"preview {url}")
                if detail == "open":
                    spawn(sessions.in_scope(["xdg-open", url]))
            else:
                said.append(f"no preview ({url})")
        elif step == "focus" and detail == "dnd":
            if not dnd_now():
                dnd(True)
                new_state["dnd"] = True
            said.append("Do Not Disturb")
        elif step == "focus" and detail == "project":
            if focus_project(ctx):
                new_state["mode"] = MODE
                said.append("only its notifications")
            else:
                said.append("no notification filter (mako did not take it)")
    write_state(new_state)
    bar_signal()
    if not same:
        automation_event("context-enter", ctx["name"])
    notify(f"Project {ctx['name']}" if not same else f"Still in {ctx['name']}",
           (short(repo) + ("  ·  " + ", ".join(said) if said else "")) if said or not same
           else "everything is open already")
    return 0, steps


def save_layout(name):
    contexts, _ = load()
    ctx = find(contexts, name)
    if ctx is None:
        return f"contexts: no context called {name!r}"
    if sessions.hypr_json("monitors") is None:
        return "contexts: Hyprland is not running"
    data = sessions.snapshot()
    sessions.write_json(sessions.session_path(ctx["name"]), data)
    print(f"Saved {len(data['windows'])} windows as {ctx['name']}'s layout")
    return 0


def new(name, repo, focus=None):
    contexts, _ = load()
    if find(contexts, name):
        raise ValueError(f"there is a context called {name!r} already")
    if not os.path.isdir(os.path.expanduser(repo)):
        raise ValueError(f"{repo} is not a folder")
    ctx = tidy({"name": name, "repo": repo} | ({"focus": focus} if focus else {}))
    if not ctx["editor_cmd"] and ctx["preview"] == "off":
        try:
            if repos_module().site_dir(repo_path(ctx)):
                ctx["preview"] = "start"     # it has a site: previewing it is likely wanted
        except Exception:    # noqa: BLE001
            pass
    save_all([*contexts, ctx])
    return ctx


def set_option(name, key, value):
    contexts, _ = load()
    ctx = find(contexts, name)
    if ctx is None:
        raise ValueError(f"no context called {name!r}")
    if key == "name":
        if find(contexts, value) and value.lower() != name.lower():
            raise ValueError(f"there is a context called {value!r} already")
    updated = tidy(ctx | {key: coerce(key, value) if key != "name" else value})
    save_all([updated if c is ctx else c for c in contexts])
    if key == "name" and updated["name"] != ctx["name"]:
        # its layout is the session of its name, and the state names it: both follow
        old, now = sessions.session_path(ctx["name"]), sessions.session_path(updated["name"])
        if os.path.exists(old) and not os.path.exists(now):
            os.replace(old, now)
        current = state()
        if current.get("name", "").lower() == ctx["name"].lower():
            write_state(current | {"name": updated["name"]})
    return updated


def delete(name):
    contexts, _ = load()
    ctx = find(contexts, name)
    if ctx is None:
        raise ValueError(f"no context called {name!r}")
    if state().get("name", "").lower() == ctx["name"].lower():
        leave(save=False, quiet=True)
    save_all([c for c in contexts if c is not ctx])


def free_repos(contexts):
    """The repos in your projects folder that have no context yet."""
    taken = {repo_path(c).rstrip("/") for c in contexts}
    try:
        names = sorted(os.listdir(PROJECTS), key=str.lower)
    except OSError:
        return []
    return [os.path.join(PROJECTS, n) for n in names
            if os.path.isdir(os.path.join(PROJECTS, n, ".git")) and os.path.join(PROJECTS, n) not in taken]


def status():
    contexts, problems = load()
    now = state()
    names = {s["name"].lower(): s for s in sessions.sessions()}
    rows = []
    for c in contexts:
        s = names.get(c["name"].lower())
        rows.append(c | {"current": now.get("name", "").lower() == c["name"].lower(),
                         "layout": {"windows": s["windows"], "saved": s["saved"], "apps": s["apps"]} if s else None,
                         "exists": os.path.isdir(repo_path(c))})
    return {"contexts": rows, "current": now, "problems": problems,
            "repos": [short(p) for p in free_repos(contexts)],
            # the folder those repos come from (Settings > Project contexts sets it)
            "projects": short(PROJECTS), "projects_full": PROJECTS,
            "projects_set": bool(desktop_conf.load().get("projects"))}


# -- the bar and the picker ------------------------------------------------------------
def bar_json(current, now=None):
    if not current:
        return {"text": "", "tooltip": "", "class": "none"}
    mins = int(((now or time.time()) - current.get("since", now or time.time())) // 60)
    on = [w for k, w in (("preview", "preview running"), ("mode", "only its notifications"),
                         ("dnd", "Do Not Disturb")) if current.get(k)]
    tip = (f"Project {current['name']}  ·  {current.get('repo', '')}\n"
           f"for {mins // 60} h {mins % 60:02d} min" + (f"  ·  {', '.join(on)}" if on else "")
           + "\nClick: switch project  ·  right-click: leave it")
    return {"text": f"{ICON} {current['name']}", "tooltip": tip, "class": "active"}


def pick_lines(contexts, current):
    lines = []
    if current:
        lines.append(f"leave    {current['name']}")
    for c in contexts:
        mark = "●" if current and c["name"].lower() == current["name"].lower() else " "
        lines.append(f"{mark} {c['name']:<20} {c['repo']}")
    for p in free_repos(contexts)[:40]:
        lines.append(f"+ {os.path.basename(p):<20} new project from {short(p)}")
    return lines


def picked(line, contexts):
    """('enter', name) / ('leave', None) / ('new', repo path) / None."""
    # the raw line: a project's starts with its mark ("●" or " "), so one
    # called "leave me" is not the leave line
    line = line.rstrip("\n")
    if line.startswith("leave "):
        return ("leave", None)
    if line.startswith("+ "):
        name = line[2:].split()[0]
        path = os.path.join(PROJECTS, name)
        return ("new", path) if os.path.isdir(path) else None
    rest = line[2:] if line[:1] in ("●", " ") else line
    rest = rest.strip()
    # the longest name the line starts with ("a  b" before "a"), padded or not
    hits = [c for c in contexts if rest == c["name"] or rest.startswith(c["name"] + " ")]
    ctx = max(hits, key=lambda c: len(c["name"]), default=None)
    return ("enter", ctx["name"]) if ctx else None


def pick():
    contexts, _ = load()
    lines = pick_lines(contexts, state())
    try:
        choice = subprocess.run(["wofi", "--dmenu", "--insensitive", "--prompt", "project", "--width", "760",
                                 "--lines", str(min(len(lines), 14) + 1)], input="\n".join(lines),
                                capture_output=True, text=True, timeout=300).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 0
    what = picked(choice, contexts) if choice else None
    if what is None:
        return 0
    try:
        with busy():
            if what[0] == "leave":
                leave()
            elif what[0] == "new":
                base = os.path.basename(what[1])
                name = base if valid_name(base) else re.sub(r"[^\w .-]", "-", base)[:40]
                try:
                    code = enter(new(name, what[1])["name"])[0]
                except ValueError as err:
                    code = str(err)
                if code:
                    notify("No new project", str(code), "normal")
            else:
                code = enter(what[1])[0]
                if code:
                    notify("Could not enter the project", str(code), "normal")
    except TimeoutError as err:
        notify("Projects busy", str(err), "normal")
    return 0


# -- CLI -------------------------------------------------------------------------------
def main(argv):
    """command(), under busy() for the verbs that switch (see busy())."""
    cmd, args = (argv[0] if argv else "list"), argv[1:]
    if cmd in ("enter", "leave", "delete", "new") and "--dry-run" not in args:
        try:
            with busy():
                return command(argv)
        except TimeoutError as err:
            return f"contexts: {err}"
    return command(argv)


def command(argv):
    cmd, args = (argv[0] if argv else "list"), argv[1:]
    if cmd == "list":
        contexts, problems = load()
        now = state().get("name", "").lower()
        if "--json" in args:
            print(json.dumps({"contexts": contexts, "current": state(), "problems": problems}))
            return 0
        for c in contexts:
            print(f"{'*' if c['name'].lower() == now else ' '} {c['name']:<20} {c['repo']:<28} "
                  f"focus {c['focus']}, preview {c['preview']}")
        for p in problems:
            print(f"BROKEN  {p}")
        if not contexts:
            print(f"no contexts yet: contexts.py new NAME --repo {desktop_conf.tilde(PROJECTS)}/NAME")
    elif cmd == "enter" and args:
        name = " ".join(a for a in args if a != "--dry-run")
        code, steps = enter(name, dry="--dry-run" in args)
        if "--dry-run" in args:
            for step, detail in steps:
                print(f"{step:<10} {detail}")
        elif code:      # the launcher, the bar and a key show no stderr: say it
            notify("Could not enter the project", str(code).removeprefix("contexts: "), "normal")
        return code
    elif cmd == "leave":
        if not state():
            print("not in a project")
            return 0
        said = leave(save=True if "--save" in args else False if "--no-save" in args else None)
        print("left" + (": " + ", ".join(said) if said else ""))
    elif cmd == "current":
        now = state()
        print(json.dumps(now) if "--json" in args else now.get("name", ""))
    elif cmd == "save" and args:
        return save_layout(" ".join(args))
    elif cmd == "new" and args and "--repo" in args[:-1]:
        words, flags, rest = [], {}, list(args)
        while rest:
            word = rest.pop(0)
            if word in ("--repo", "--focus") and rest:
                flags[word] = rest.pop(0)
            elif word != "--enter":
                words.append(word)
        try:
            ctx = new(" ".join(words), flags["--repo"], flags.get("--focus"))
        except ValueError as err:
            return f"contexts: {err}"
        print(f"added {ctx['name']} ({ctx['repo']})")
        if "--enter" in args:
            return enter(ctx["name"])[0]
    elif cmd == "set" and len(args) == 3:
        try:
            set_option(*args)
        except ValueError as err:
            return f"contexts: {err}"
        if state().get("name", "").lower() == args[0].lower():
            bar_signal()
    elif cmd == "delete" and args:
        try:
            delete(" ".join(args))
        except ValueError as err:
            return f"contexts: {err}"
    elif cmd == "status":
        print(json.dumps(status()))
    elif cmd == "pick":
        return pick()
    elif cmd == "bar":
        print(json.dumps(bar_json(state())))
    elif cmd == "ensure":
        # missing, or a filter left from a login that ended inside a project
        # (the state is in $XDG_RUNTIME_DIR and went with it): empty again
        if not os.path.exists(FRAGMENT) or not state():
            write_fragment(render_fragment(None))
    else:
        print(__doc__.split("\n\n")[1])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
