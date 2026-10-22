#!/usr/bin/env python3
"""Folder access: which folders the AI features may read files in. Before an
AI feature hands a file's CONTENTS to a model, the file's folder has to be
open to that feature; when it is not, the feature asks you, on the desktop:

    ┌ AI WANTS TO READ A FOLDER ───────────────────────────┐
    │ The assistant wants to read ~/Documents/taxes/2025    │
    │ The AI says: “to sum up the receipts you asked about” │
    │ Open:  [ ~/Documents/taxes/2025 ]  [ ~/Documents ]     │
    │        [Deny]   [Allow once]   [Always allow]         │
    └───────────────────────────────────────────────────────┘

Esc (or no answer in TIMEOUT_S, or no screen to ask on) is Deny. The focus
starts on Deny and the buttons only take a click or a key after ARM_S, so a
key that was already on its way into another window does not answer it.

Who asks ("who"): assistant (the chat panel and `assistant.py ask`), chat
(the LLM chat window's own tools, llm-chat.py), worker (llm-worker.py: the
local worker a coding agent calls over MCP), ask-desktop (the launcher's
"ask ..."), tasks (background tasks), phone (questions from the phone), or
all (a grant for every one of them).

A grant covers the folder and everything under it. The most specific rule
wins (a Deny on ~/Documents/taxes beats an Allow on ~/Documents), a Deny
beats an Allow on the same folder. "Allow once" lasts for that request only
(one question to the assistant, one call of the worker): it is never
written down. Whatever is granted, these are never read: paths that look
secret (~/.ssh, ~/.gnupg, keyrings, password stores, browser profiles,
cloud keys, *.env, id_rsa*, *.pem / *.key, names with secret / credential /
password / token) and the system's own folders (/proc, /sys, /dev, /run,
/boot). Symlinks are followed first: a link in an allowed folder that
points into another one needs that other one.

What counts as granted without a prompt (your own doing, not the model's):
  - a folder you typed yourself into the assistant's question ("sum up
    ~/notes/today.md"): open to the assistant for that question only
  - the folder a background task of yours works on (you set it up, or said
    yes to it): open to tasks while the task exists; a Deny here wins

The switch "ask" (on as shipped): off = the old behaviour, every folder that
is not secret may be read, except the ones you denied here.

    folder-access.py list [--json]          the grants, the denials, the switch
    folder-access.py allow PATH [--who X]   always allow (X = all by default)
    folder-access.py deny PATH [--who X]    never allow
    folder-access.py revoke PATH [--who X]  take back what was said about PATH
    folder-access.py check PATH [--who X]   allow / deny / ask, and why
    folder-access.py ask on|off             ask before AI reads a folder
    folder-access.py prompt --who X --reason TEXT [--timeout S] -- FOLDER...
                                            the prompt itself (what request()
                                            runs; prints the answer as JSON)
    folder-access.py render OUT.png         the prompt drawn off screen

The store: ~/.config/hypr/folder-access.json (yours: which of your folders
are open; mode 600). $HYPR_FOLDER_ACCESS points it at another file (the
tests do); $HYPR_FOLDER_ACCESS_NO_PROMPT=1 never shows a prompt (a request
that would ask is denied).
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
STORE = os.environ.get("HYPR_FOLDER_ACCESS") or os.path.join(CONFIG_HOME, "hypr", "folder-access.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LOCK_DIR = os.path.join(RUNTIME, "folder-access")
CLI = os.path.join(HERE, "folder-access.py")      # shown as ~/.config/hypr/scripts/folder-access.py
TIMEOUT_S = 60              # a prompt nobody answers is a Deny after this
ARM_S = 0.6                 # the prompt's buttons wait this long before they take a click
SHARE_S = 15                # an answer given this recently is reused by the requests that waited on it

WHO = {"assistant": "The assistant", "chat": "The LLM chat window", "worker": "The local worker (MCP)",
       "ask-desktop": "Ask your desktop",
       "tasks": "A background task", "phone": "A question from your phone", "all": "Every AI feature"}
WHO_SHORT = {"assistant": "the assistant", "chat": "the LLM chat window", "worker": "the local worker (MCP)",
             "ask-desktop": "Ask your desktop", "tasks": "background tasks", "phone": "the phone",
             "all": "all AI features"}
SYSTEM_ROOTS = ("/proc", "/sys", "/dev", "/run", "/boot")
# llm-worker.py's and voice-command.py's secret folders together.
SECRET_DIRS = (".ssh", ".gnupg", ".password-store", ".local/share/keyrings", ".local/share/kwalletd",
               ".mozilla", ".librewolf", ".thunderbird", ".config/google-chrome", ".config/chromium",
               ".config/BraveSoftware", ".config/vivaldi", ".config/microsoft-edge", ".var/app",
               ".config/keepassxc", ".pki", ".aws", ".kube", ".docker")
SECRET_NAME = re.compile(r"secret|credential|password|passwd|token|^id_(rsa|dsa|ecdsa|ed25519)|"
                         r"\.env$|^\.env|\.pem$|\.key$", re.I)
SECRET_FOLDER = re.compile(r"\.?(secrets?|credentials?|password-store|keyrings?)", re.I)

# The prompter: prompter(who, choices, reason, timeout) -> ("once"|"always"|"deny", folder)
# or None when it could not ask. The tests put a fake one here; None = the window.
PROMPTER = None


# -- paths -----------------------------------------------------------------------------------------
def tilde(path):
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + os.sep) else path


def real(path):
    """The absolute path with every symlink followed (~ is home)."""
    path = os.path.expanduser(str(path).strip())
    if not os.path.isabs(path):
        path = os.path.join(HOME, path)
    return os.path.realpath(path)


def under(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def folder_of(path):
    """The folder a file is in (a folder is its own), symlinks followed."""
    path = real(path)
    return path if os.path.isdir(path) else os.path.dirname(path)


def looks_secret(path):
    """In a secret folder, a folder named like one (secrets, credentials,
    .password-store), or a file with a secret-looking name (llm-worker.py's
    rule: the name only, so a repo called "password-tools" stays readable)."""
    path = real(path)
    if any(under(path, os.path.join(HOME, d)) for d in SECRET_DIRS):
        return True
    if any(SECRET_FOLDER.fullmatch(part) for part in path.split(os.sep)):
        return True
    return not os.path.isdir(path) and bool(SECRET_NAME.search(os.path.basename(path)))


def refused(path):
    """Why this is never read, whatever is granted (None = it may be)."""
    path = real(path)
    if path == "/" or any(under(path, r) for r in SYSTEM_ROOTS):
        return "a system folder: never read"
    if looks_secret(path):
        return "looks secret (keys, passwords, tokens, browser profiles): never read"
    return None


def choices(path):
    """The levels the prompt offers, most specific first: the file's folder,
    its parent, and the folder right under home it is in (~/Documents/taxes/2025,
    ~/Documents/taxes, ~/Documents) -- never / and never home unless the
    file is in home itself."""
    folder = folder_of(path)
    out = [folder]
    parent = os.path.dirname(folder)
    if parent not in ("/", HOME) and not refused(parent) and parent != folder:
        out.append(parent)
    if under(folder, HOME) and folder != HOME:
        top = os.path.join(HOME, os.path.relpath(folder, HOME).split(os.sep)[0])
        if top not in out:
            out.append(top)
    return out[:3]


# -- the store -----------------------------------------------------------------------------------
def load(path=None):
    try:
        with open(path or STORE) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = {"ask": data.get("ask", True) is not False}
    for kind in ("allow", "deny"):
        rows = data.get(kind) if isinstance(data.get(kind), list) else []
        out[kind] = [r for r in rows if isinstance(r, dict) and isinstance(r.get("path"), str)
                     and r.get("who") in WHO]
    return out


def save(data, path=None):
    path = path or STORE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-folder-access-")
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=1)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


@contextlib.contextmanager
def _store_lock():
    os.makedirs(LOCK_DIR, mode=0o700, exist_ok=True)
    with open(os.path.join(LOCK_DIR, "store.lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _check_who(who):
    if who not in WHO:
        raise ValueError(f"not a feature: {who!r} (one of {', '.join(WHO)})")


def _put(kind, folder, who, by, path=None):
    _check_who(who)
    folder = real(folder)
    why = refused(folder)
    if why:
        raise ValueError(f"{tilde(folder)}: {why}")
    with _store_lock():
        data = load(path)
        other = "deny" if kind == "allow" else "allow"
        data[other] = [r for r in data[other] if not (r["path"] == folder and r["who"] == who)]
        data[kind] = [r for r in data[kind] if not (r["path"] == folder and r["who"] == who)]
        data[kind].append({"path": folder, "who": who, "since": int(time.time()), "by": by})
        save(data, path)
    return folder


def grant(folder, who="all", by="settings", path=None):
    """Always allow `who` to read in `folder` (and under it). The folder as stored."""
    return _put("allow", folder, who, by, path)


def deny(folder, who="all", by="settings", path=None):
    """Never let `who` read in `folder` (and under it)."""
    return _put("deny", folder, who, by, path)


def revoke(folder, who=None, path=None):
    """Forget what was said about `folder` (for `who`, or for everyone):
    how many rules went."""
    folder = real(folder)
    with _store_lock():
        data = load(path)
        gone = 0
        for kind in ("allow", "deny"):
            keep = [r for r in data[kind] if not (r["path"] == folder and (who is None or r["who"] == who))]
            gone += len(data[kind]) - len(keep)
            data[kind] = keep
        if gone:
            save(data, path)
    return gone


def set_ask(on, path=None):
    with _store_lock():
        data = load(path)
        data["ask"] = bool(on)
        save(data, path)


def listing(path=None):
    """Everything as the Settings page shows it."""
    data = load(path)
    return {"ask": data["ask"], "store": path or STORE,
            "allow": sorted(data["allow"], key=lambda r: (r["path"], r["who"])),
            "deny": sorted(data["deny"], key=lambda r: (r["path"], r["who"])),
            "who": WHO_SHORT, "never": [tilde(os.path.join(HOME, d)) for d in SECRET_DIRS[:6]]}


# -- the decision -------------------------------------------------------------------------------
class Session:
    """What one request (a question, a worker call) was told: its "once"
    answers -- allowed and denied folders -- that are never written down,
    and the folders the user's own words opened (implied)."""

    def __init__(self, who, implied=()):
        _check_who(who)
        self.who = who
        self.allowed = {real(f) for f in implied}
        self.denied = set()


def decide(path, who, implied=(), session=None, store=None):
    """(verdict, why): verdict "allow", "deny" or "ask" for `who` reading
    `path`. `implied`: folders open to it by the user's own doing (a task's
    folder); `session`: its once answers."""
    _check_who(who)
    target = real(path)
    why = refused(target)
    if why:
        return "deny", why
    data = load(store)
    rules = []      # (length, is_deny, why)
    for kind in ("allow", "deny"):
        for r in data[kind]:
            if r["who"] in (who, "all") and under(target, r["path"]):
                rules.append((len(r["path"]), kind == "deny",
                              f"{'denied' if kind == 'deny' else 'allowed'}: {tilde(r['path'])} "
                              f"({WHO_SHORT[r['who']]})"))
    for f in implied:
        f = real(f)
        if under(target, f):
            rules.append((len(f), False, f"allowed: {tilde(f)} (yours)"))
    if session is not None:
        for f in session.allowed:
            if under(target, f):
                rules.append((len(f), False, f"allowed for now: {tilde(f)}"))
        for f in session.denied:
            if under(target, f):
                rules.append((len(f), True, f"you said no to {tilde(f)}"))
    if rules:
        _length, is_deny, why = max(rules, key=lambda r: (r[0], r[1]))
        return ("deny" if is_deny else "allow"), why
    if not data["ask"]:
        return "allow", "asking is off (Settings > Folder access)"
    return "ask", f"{tilde(folder_of(target))} is not open to {WHO_SHORT[who]} yet"


def check(path, who, implied=(), session=None, store=None):
    """"allow", "deny" or "ask" -- decide() without the why."""
    return decide(path, who, implied, session, store)[0]


def how_to_allow(folder, who):
    """The words a refusal ends with: where it is granted."""
    return (f"to open it: Settings > Privacy > Folder access, or run "
            f"`{tilde(CLI)} allow {tilde(folder)} --who {who}`")


def not_allowed(path, who, why=""):
    folder = folder_of(path)
    return (f"{tilde(folder)} is not open to {WHO_SHORT[who]}" + (f" ({why})" if why else "")
            + f": {how_to_allow(folder, who)}")


def _lock_path(folder):
    return os.path.join(LOCK_DIR, hashlib.sha1(folder.encode()).hexdigest()[:16])


def _recent_answer(key, who, target, since):
    """An answer the request that held the lock before this one gave, when
    it covers `target` and was given after `since` (this one started)."""
    try:
        with open(key + ".json") as handle:
            a = json.load(handle)
        if a["t"] >= since and time.time() - a["t"] < SHARE_S and a["who"] == who and under(target, a["folder"]):
            return a["decision"], a["folder"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def request(path, who, reason="", timeout=TIMEOUT_S, implied=(), session=None, prompt=True, store=None):
    """May `who` read `path`? (ok, why). Asks the user when the folder is
    not decided yet: blocks until they answer, at most `timeout` seconds
    (waiting for an earlier prompt about the same folder counts); no
    answer, no screen, or prompt=False = not allowed, and `why` says how
    to allow it. One prompt per folder at a time: a second request for the
    same folder waits for the first one's answer and takes it."""
    started = time.time()
    verdict, why = decide(path, who, implied, session, store)
    if verdict == "allow":
        return True, why
    if verdict == "deny":
        return False, (why if refused(path) else not_allowed(path, who, why))
    if not prompt:
        return False, not_allowed(path, who)
    target = real(path)
    levels = choices(target)
    key = _lock_path(levels[-1])        # the broadest level: all prompts about that area queue
    os.makedirs(LOCK_DIR, mode=0o700, exist_ok=True)
    deadline = started + timeout
    with open(key + ".lock", "w") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    return False, (f"{tilde(levels[0])} is not open to {WHO_SHORT[who]} and there was no "
                                   f"answer in time: " + how_to_allow(levels[0], who))
                time.sleep(0.1)
        # Decided while this one waited (Always allow, or an answer just given)?
        verdict, why = decide(target, who, implied, session, store)
        if verdict != "ask":
            return verdict == "allow", why if verdict == "allow" else not_allowed(target, who, why)
        shared = _recent_answer(key, who, target, started)
        if shared is None:
            prompter = PROMPTER or window_prompter
            try:
                got = prompter(who, levels, str(reason or "")[:300], max(1, int(deadline - time.time())))
            except Exception:       # noqa: BLE001 -- a prompt that breaks is a no
                got = None
            if not got:
                return False, (f"{tilde(levels[0])} is not open to {WHO_SHORT[who]} and the user could not "
                               f"be asked (no answer, or no screen to ask on): " + how_to_allow(levels[0], who))
            decision, chosen = got
            chosen = real(chosen)
            if decision not in ("once", "always", "deny") or not under(target, chosen) or chosen not in levels:
                decision, chosen = "deny", levels[0]
            try:
                with open(key + ".json", "w") as handle:
                    json.dump({"t": time.time(), "who": who, "folder": chosen, "decision": decision}, handle)
            except OSError:
                pass
        else:
            decision, chosen = shared
    if decision == "always":
        try:
            grant(chosen, who, by="prompt", path=store)
        except ValueError:
            decision = "once"
    if decision == "deny":
        if session is not None:
            session.denied.add(chosen)
        return False, f"the user said no to reading {tilde(chosen)}: do not ask again for it now"
    if session is not None:
        session.allowed.add(chosen)
    return True, f"allowed by the user: {tilde(chosen)}"


def typed_folders(text):
    """The folders the user's own words name as a path (~/x, /x): a file's
    folder, or the folder itself. For "a folder you typed counts"."""
    out = []
    for m in re.finditer(r"(?<![\w.])(~/[^\s\"'`<>|]*|/[^\s\"'`<>|]+)", str(text or "")):
        p = real(m.group(1).rstrip(".,;:!?)]}"))
        if os.path.exists(p) and not refused(p):
            out.append(p if os.path.isdir(p) else os.path.dirname(p))
    return out


# -- the prompt window ----------------------------------------------------------------------------
def window_prompter(who, levels, reason, timeout):
    """The prompt as its own process (the caller may be a GTK app, a server
    with no GTK, or a thread): its answer, or None."""
    if os.environ.get("HYPR_FOLDER_ACCESS_NO_PROMPT") or not os.environ.get("WAYLAND_DISPLAY"):
        return None
    argv = [sys.executable, os.path.abspath(__file__), "prompt", "--who", who, "--reason", reason,
            "--timeout", str(timeout), "--", *levels]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 10).stdout
        data = json.loads(out.strip().splitlines()[-1])
        return data["decision"], data["folder"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        return None


def prompt_main(who, levels, reason, timeout, render=None):
    """The card: who, the folder, the AI's reason, the level, Deny / Allow
    once / Always allow. Prints {"decision", "folder"}. render=OUT.png:
    drawn off screen into it instead."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango
    sys.path.insert(0, os.path.join(CONFIG_HOME, "waybar", "scripts"))
    import panelui
    panelui.load_css()
    answer = {"decision": "deny", "folder": levels[0]}

    def wrap(text, cls):
        lab = Gtk.Label(label=text, xalign=0)
        lab.get_style_context().add_class(cls)
        lab.set_line_wrap(True)
        lab.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lab.set_max_width_chars(56)
        return lab

    win = Gtk.OffscreenWindow() if render else Gtk.Window()
    win.set_name("panel-window")
    win.set_app_paintable(True)
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)
    if not render:
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "waybar-panel")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.ON_DEMAND)
        mon = _focused_monitor(Gdk)
        if mon:
            GtkLayerShell.set_monitor(win, mon)
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    card.set_name("panel")
    card.set_size_request(440, -1)
    win.add(card)
    head = Gtk.Label(label="AI WANTS TO READ A FOLDER", xalign=0)
    head.get_style_context().add_class("kb-heading")
    card.pack_start(head, False, False, 0)
    card.pack_start(wrap(f"{WHO.get(who, who)} wants to read the files in {tilde(levels[0])}", "ctl-title"),
                    False, False, 0)
    card.pack_start(wrap(f"The AI says: “{reason}”" if reason else "The AI gave no reason.", "ctl-sub"),
                    False, False, 0)
    card.pack_start(wrap("This is a request from a local AI model, not from you. It reads the files' text; "
                         "nothing leaves the computer. Secret files are never read.", "ctl-sub"), False, False, 0)
    level_buttons = []
    if len(levels) > 1:
        card.pack_start(wrap("Open which folder (and everything in it)?", "ctl-sub"), False, False, 0)
        row = Gtk.FlowBox()
        row.set_selection_mode(Gtk.SelectionMode.NONE)
        row.set_max_children_per_line(3)
        row.set_column_spacing(6)

        def pick(i):
            answer["folder"] = levels[i]
            for j, b in enumerate(level_buttons):
                (b.get_style_context().add_class if j == i else b.get_style_context().remove_class)("active")
        for i, level in enumerate(levels):
            b = Gtk.Button(label=tilde(level) + ("  (your whole home)" if level == HOME else ""))
            b.get_style_context().add_class("dev-pick")
            b.connect("clicked", lambda _b, i=i: pick(i))
            level_buttons.append(b)
            row.add(b)
        card.pack_start(row, False, False, 0)
        pick(0)
    count = wrap("", "ctl-sub")
    card.pack_start(count, False, False, 0)
    buttons = Gtk.Box(spacing=8)
    buttons.set_halign(Gtk.Align.END)
    armed = {"at": time.monotonic() + (0 if render else ARM_S)}

    def finish(decision):
        if time.monotonic() < armed["at"]:
            return
        answer["decision"] = decision
        Gtk.main_quit()
    made = {}
    for key, caption, tip in (("deny", "Deny", "Esc / D"), ("once", "Allow once", "O: only for this request"),
                              ("always", "Always allow", "A: remembered (Settings > Folder access)")):
        b = Gtk.Button(label=caption)
        b.get_style_context().add_class("dev-pick")
        b.set_tooltip_text(tip)
        b.connect("clicked", lambda _b, k=key: finish(k))
        buttons.pack_start(b, False, False, 0)
        made[key] = b
    made["deny"].get_style_context().add_class("active")
    card.pack_start(buttons, False, False, 0)
    card.pack_start(wrap("Esc / D deny · O allow once · A always · ←/→ the folder · "
                         f"no answer = deny · as {WHO_SHORT.get(who, who)} only", "ctl-sub"), False, False, 0)
    left = {"s": timeout}

    def tick():
        if left["s"] <= 0:
            armed["at"] = 0
            finish("deny")
            return False
        count.set_text(f"Denied by itself in {left['s']} s")
        left["s"] -= 1
        return True

    def on_key(_w, event):
        k = event.keyval
        if k in (Gdk.KEY_Escape, Gdk.KEY_d, Gdk.KEY_D):
            armed["at"] = 0
            finish("deny")
        elif k in (Gdk.KEY_o, Gdk.KEY_O):
            finish("once")
        elif k in (Gdk.KEY_a, Gdk.KEY_A):
            finish("always")
        elif k in (Gdk.KEY_Left, Gdk.KEY_Right) and level_buttons:
            i = levels.index(answer["folder"]) + (1 if k == Gdk.KEY_Right else -1)
            level_buttons[max(0, min(len(levels) - 1, i))].clicked()
        else:
            return False        # Tab / Enter / Space: the focused button, as usual
        return True
    win.connect("key-press-event", on_key)
    win.connect("delete-event", lambda *_a: (finish("deny"), True)[1])
    tick()
    win.show_all()
    made["deny"].grab_focus()
    if render:
        def snap():
            pix = win.get_pixbuf()
            if pix:
                pix.savev(render, "png", [], [])
            Gtk.main_quit()
            return False
        GLib.timeout_add(600, snap)
    else:
        GLib.timeout_add_seconds(1, tick)
    Gtk.main()
    return answer


def _focused_monitor(Gdk):
    """The screen with the focus (hyprctl), as GDK's monitor; None if unknown."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2).stdout
        origin = next(((m["x"], m["y"]) for m in json.loads(out or "[]") if m.get("focused")), None)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None
    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        mon = display.get_monitor(i)
        geo = mon.get_geometry()
        if (geo.x, geo.y) == origin:
            return mon
    return None


# -- the command line -----------------------------------------------------------------------------
def _option(args, flag, default=None):
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            value = args[i + 1]
            del args[i:i + 2]
            return value
    return default


def human(data):
    lines = [f"ask before AI reads a folder: {'on' if data['ask'] else 'off'}   ({data['store']})"]
    for kind in ("allow", "deny"):
        lines.append(f"{kind}:" + ("" if data[kind] else " nothing"))
        for r in data[kind]:
            when = time.strftime("%Y-%m-%d", time.localtime(r.get("since") or 0))
            lines.append(f"  {tilde(r['path'])}  ({WHO_SHORT[r['who']]}, since {when}, by {r.get('by', '?')})")
    return "\n".join(lines)


def main(argv):
    args = list(argv)
    cmd = args.pop(0) if args else "list"
    try:
        if cmd == "list":
            data = listing()
            print(json.dumps(data) if "--json" in args else human(data))
        elif cmd in ("allow", "deny", "revoke", "check") and args:
            who = _option(args, "--who", None if cmd == "revoke" else "all")
            path = " ".join(a for a in args if a != "--json")
            if cmd == "allow":
                print(f"allowed: {tilde(grant(path, who, by='cli'))} ({WHO_SHORT[who]})")
            elif cmd == "deny":
                print(f"denied: {tilde(deny(path, who, by='cli'))} ({WHO_SHORT[who]})")
            elif cmd == "revoke":
                n = revoke(path, who)
                print(f"{n} rule(s) taken back for {tilde(real(path))}")
                return 0 if n else 1
            else:
                verdict, why = decide(path, who)
                print(json.dumps({"verdict": verdict, "why": why}) if "--json" in argv else f"{verdict}: {why}")
                return 0 if verdict == "allow" else 1
        elif cmd == "ask" and args and args[0] in ("on", "off"):
            set_ask(args[0] == "on")
            print(f"ask before AI reads a folder: {args[0]}")
        elif cmd == "prompt" and "--" in args:
            i = args.index("--")
            levels, opts = [real(p) for p in args[i + 1:]], args[:i]
            if not levels:
                return 2
            who = _option(opts, "--who", "assistant")
            reason = _option(opts, "--reason", "")
            timeout = int(_option(opts, "--timeout", str(TIMEOUT_S)))
            print(json.dumps(prompt_main(who, levels, reason, timeout)))
        elif cmd == "render" and args:
            sample = os.path.join(HOME, "Documents", "taxes", "2025", "receipts.txt")
            prompt_main("assistant", choices(sample), "to add up the receipts you asked about", TIMEOUT_S,
                        render=args[0])
        else:
            print(__doc__.strip(), file=sys.stderr)
            return 2
    except ValueError as err:
        print(f"folder-access.py: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
