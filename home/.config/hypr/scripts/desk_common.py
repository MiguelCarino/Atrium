#!/usr/bin/env python3
"""Small helpers the desktop scripts share, so each stops keeping its own
copy: a notification, a JSON file written whole or not at all, a JSON file
read with a fallback, one Hyprland request without starting hyprctl, a
command run with a timeout, and the XDG folders.

Imported as a plain module (the name has no dash on purpose) after a script
puts its own folder on sys.path -- the same way they import screens.py; the
waybar scripts put ~/.config/hypr/scripts there. Standard library only, and
nothing happens at import time.

    notify(title, body="", *, app=, urgency=, icon=, expire=, hints=,
           replace_id=, print_id=, actions=, wait=, mood=, timeout=,
           background=)                  -> stdout of scripts/notify ("" on failure)
    notify_argv(...)                     -> that argv, for tests and odd callers
    atomic_write_json(path, obj, mode=None, *, indent=, ensure_ascii=, sort_keys=)
    read_json(path, default=None, *, typed=False)
    hypr_request(cmd, json=False, timeout=2) -> the reply (text or parsed), None on failure
    hypr_socket_dir()                    -> this Hyprland's runtime folder, or None
    run(argv, timeout=10, **kw)          -> CompletedProcess, None when it could not run
    state_dir(*parts) / runtime_dir(*parts)

Every helper swallows exactly what its docstring says and nothing more, so a
script that moves to it keeps the behaviour it had.
"""
import json as _json
import os
import socket
import subprocess
import threading

HERE = os.path.dirname(os.path.realpath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)


# -- folders -------------------------------------------------------------------------
def state_dir(*parts):
    """$XDG_STATE_HOME (or ~/.local/state), joined with PARTS."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, *parts)


def runtime_dir(*parts):
    """$XDG_RUNTIME_DIR (or /run/user/UID), joined with PARTS."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(base, *parts)


# -- JSON files ----------------------------------------------------------------------
def read_json(path, default=None, *, typed=False):
    """The parsed file, or DEFAULT when it is missing, unreadable or not
    JSON. typed=True: also DEFAULT when the data is not of DEFAULT's type
    (a list where a dict was expected, say)."""
    try:
        with open(path) as handle:
            data = _json.load(handle)
    except (OSError, ValueError):
        return default
    if typed and not isinstance(data, type(default)):
        return default
    return data


def atomic_write_json(path, obj, mode=None, *, indent=None, ensure_ascii=True, sort_keys=False,
                      makedirs=True):
    """Write OBJ as JSON to PATH whole or not at all: into a temporary file
    beside it, then renamed over it, so a reader never sees half a file.

    MODE is the new file's permission bits (as os.open takes them, so the
    umask still applies); None gives what open(path, "w") would. The parent
    folder is made first unless makedirs=False. Errors are raised, as
    open() would raise them; the temporary file is not left behind."""
    folder = os.path.dirname(path)
    if makedirs and folder:
        os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666 if mode is None else mode)
    try:
        with os.fdopen(fd, "w") as handle:
            _json.dump(obj, handle, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# -- commands ------------------------------------------------------------------------
def run(argv, timeout=10, **kw):
    """subprocess.run(ARGV) with its output captured as text and a timeout:
    the CompletedProcess, or None when the program is missing, could not
    start or ran past TIMEOUT. Other keywords go to subprocess.run (they
    may override capture_output / text)."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    try:
        return subprocess.run(argv, timeout=timeout, **kw)
    except (OSError, subprocess.SubprocessError):
        return None


# -- notifications -------------------------------------------------------------------
def _pairs(actions):
    """{key: label} or [(key, label), ...] -> [(key, label), ...]."""
    if isinstance(actions, dict):
        return list(actions.items())
    return [tuple(a) for a in actions or ()]


def notify_argv(title, body="", *, app=None, urgency=None, icon=None, expire=None, hints=(),
                replace_id=None, print_id=False, actions=(), wait=False, mood=None):
    """The scripts/notify argv (notify-send's options, plus --mood). With
    ACTIONS ({key: label} or pairs) it always waits, as notify-send must
    to print the picked key."""
    argv = [NOTIFY]
    if mood:
        argv += ["--mood", mood]
    if app:
        argv += ["-a", app]
    if urgency:
        argv += ["-u", urgency]
    if icon:
        argv += ["-i", icon]
    if expire is not None:
        argv += ["-t", str(expire)]
    for hint in hints or ():
        argv += ["-h", hint]
    if print_id:
        argv.append("-p")
    if replace_id:
        argv += ["-r", str(replace_id)]
    pairs = _pairs(actions)
    if wait or pairs:
        argv.append("--wait")
    for key, label in pairs:
        argv += ["-A", f"{key}={label}"]
    return argv + [str(title), str(body)]


def notify(title, body="", *, app=None, urgency=None, icon=None, expire=None, hints=(),
           replace_id=None, print_id=False, actions=(), wait=False, mood=None, timeout=5,
           background=False):
    """Send a notification through scripts/notify (the mascot's drop-in for
    notify-send). Returns its stdout stripped: the id with print_id, the
    picked action's key with ACTIONS / wait, else "" -- and "" whenever it
    could not run or ran past TIMEOUT (None: no limit). background=True
    starts it detached and returns "" at once (nothing to read back).
    Never raises for a missing or stuck notifier."""
    argv = notify_argv(title, body, app=app, urgency=urgency, icon=icon, expire=expire,
                       hints=hints, replace_id=replace_id, print_id=print_id, actions=actions,
                       wait=wait, mood=mood)
    if background:
        try:
            subprocess.Popen(argv, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        return ""
    done = run(argv, timeout=timeout)
    return (done.stdout or "").strip() if done is not None else ""


# -- Hyprland ------------------------------------------------------------------------
def hypr_socket_dir():
    """This Hyprland's folder under $XDG_RUNTIME_DIR/hypr: the one
    $HYPRLAND_INSTANCE_SIGNATURE names, else (a service started before the
    variable reached systemd) the newest one with a request socket, as
    hyprctl picks; None when there is none."""
    base = runtime_dir("hypr")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        return os.path.join(base, sig)
    try:
        dirs = [os.path.join(base, d) for d in os.listdir(base)]
        dirs = [d for d in dirs if os.path.exists(os.path.join(d, ".socket.sock"))]
        return max(dirs, key=os.path.getmtime) if dirs else None
    except OSError:
        return None


def _words(cmd):
    return cmd.split() if isinstance(cmd, str) else [str(c) for c in cmd]


def _parse(text, as_json):
    if not as_json:
        return text
    try:
        return _json.loads(text or "null")
    except ValueError:
        return None


class _Unreachable(Exception):
    """The request socket could not be connected to (not: it stopped answering)."""


def _socket_request(path, request, timeout):
    """One request on .socket.sock; the raw reply. _Unreachable when it
    cannot connect, OSError when the connection fails after that."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect(os.path.join(path, ".socket.sock"))
        except OSError as exc:
            raise _Unreachable(exc) from exc
        sock.sendall(request.encode())
        chunks = []
        while chunk := sock.recv(65536):   # Hyprland closes the connection after the reply
            chunks.append(chunk)
    return b"".join(chunks).decode(errors="replace")


def hypr_request(cmd, json=False, timeout=2):
    """`hyprctl [-j] CMD` over Hyprland's request socket -- well under a
    millisecond and no process. CMD is "clients", "monitors all",
    "getoption animations:enabled" ... (or its words as a list).

    json=True: the parsed reply (dict / list), None when it is not JSON.
    json=False: the reply's text. Either way None when Hyprland does not
    answer. The socket unreachable (no instance folder, connect refused),
    it falls back to running hyprctl itself once, which a nonzero exit or
    TIMEOUT also turns into None; a socket that connects and then stalls
    is None after TIMEOUT, with no second wait on hyprctl."""
    words = _words(cmd)
    path = hypr_socket_dir()
    if path:
        request = ("j/" if json else "") + " ".join(words)
        try:
            return _parse(_socket_request(path, request, timeout), json)
        except _Unreachable:
            pass
        except OSError:
            return None
    done = run(["hyprctl", *words, *(["-j"] if json else [])], timeout=timeout)
    if done is None or done.returncode != 0:
        return None
    return _parse(done.stdout, json)
