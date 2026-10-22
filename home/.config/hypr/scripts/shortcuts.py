#!/usr/bin/env python3
"""Keyboard shortcuts: every Hyprland bind, and your own changes to them --
one front for Settings > Keyboard shortcuts, the shortcuts panel (SUPER+F1),
the search bar and the terminal.

    shortcuts.py list [--json]            every shortcut: its keys, what it does
                                          (the bind's description), its group,
                                          whether you changed it, and which
                                          other shortcut shares its keys
    shortcuts.py find <keys>              what <keys> does now
    shortcuts.py move <keys> <new keys> [--replace] [--default]
                                          put a shortcut on other keys (<keys>
                                          is its keys now or its default ones);
                                          --replace turns off whatever already
                                          uses the new keys
    shortcuts.py off <keys> [--default]   turn a shortcut off
    shortcuts.py on <keys> [--replace]    turn it back on, on its default keys
                                          (refused with exit 3 when another
                                          shortcut has moved onto them;
                                          --replace turns that one off)
    shortcuts.py reset <keys> [--replace] one shortcut back to its default
                                          --default: <keys> are the shortcut's
                                          DEFAULT keys only, never its keys now
                                          (after a swap they can differ)
    shortcuts.py reset                    every change undone, your own
                                          shortcuts removed (Reset all)
    shortcuts.py add <keys> <command> [--name <name>] [--replace]
                                          a shortcut of your own that runs a
                                          shell command
    shortcuts.py add-app <keys> <app.desktop> [--name <name>] [--replace]
                                          a shortcut of your own that opens an app
    shortcuts.py remove <keys>            remove one of your own shortcuts
    shortcuts.py apply                    load the saved changes into the
                                          running Hyprland now
    shortcuts.py status [--json]          where the changes are kept, whether
                                          Hyprland has them loaded, and any
                                          problem it had with them
    shortcuts.py capture on|off           the "keycapture" mode: while it is on
                                          no shortcut fires, so a window can
                                          read the keys (the settings page's
                                          "press the new keys" box); a watchdog
                                          turns it off after 20 s whatever happens
    shortcuts.py launch <app.desktop>     open an app (what an add-app shortcut runs)

<keys> are written like the config writes them: SUPER+SHIFT+N, ALT+Q,
SUPER+CTRL+left, XF86AudioPlay -- modifiers in any order and any case.

The changes live in ~/.local/state/hypr/userbinds.conf (one per line, a TAB
between the fields), never in lua/binds.lua, which stays the defaults.
~/.config/hypr/lua/userbinds.lua reads the file at every config load (a
reload, a gamemode OFF, a re-login) and puts each bind on the keys it says;
this script writes the file and then has the running Hyprland re-read it:

    hyprctl eval 'userbinds.apply()'

so a change is live at once, through the same code that restores it after a
reload. What is live comes from `hyprctl binds -j` (keys, descriptions) and
`hyprctl repl 'return userbinds.report()'` (each bind's default keys); a
change that Hyprland has not picked up yet shows as "pending".
"""

import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys

STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
FILE = os.path.join(STATE_DIR, "userbinds.conf")
SELF = "~/.config/hypr/scripts/shortcuts.py"     # as a custom app shortcut runs it (sh expands ~)

# xkb modifier bits as `hyprctl binds -j` reports them in "modmask". The four
# that the config uses, in the order canon() prints them; the rest (Caps,
# NumLock...) are named so a bind with one still prints, but such a bind is
# not one userbinds.lua can move.
MOD_BITS = [(64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT"),
            (2, "CAPS"), (16, "MOD2"), (32, "MOD3"), (128, "MOD5")]
MOD_ALIAS = {"SUPER": "SUPER", "WIN": "SUPER", "LOGO": "SUPER", "MOD4": "SUPER", "META": "SUPER",
             "CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "MOD1": "ALT", "SHIFT": "SHIFT"}
MOD_ORDER = ["SUPER", "CTRL", "ALT", "SHIFT"]
# A key name as xkb spells it (q, F12, Return, XF86AudioPlay, bracketleft),
# a mouse button (mouse:272), the wheel (mouse_down) or a raw keycode (code:10).
KEY_RE = re.compile(r"^(?:[A-Za-z0-9_]+|mouse:\d+|code:\d+|[!-~])$")


# -- keys ----------------------------------------------------------------------------
def canon(keys):
    """"alt + shift+q" -> "ALT+SHIFT+Q": modifiers in one order, upper case,
    so the same keys always compare equal. lua/userbinds.lua canon() does
    exactly this. None for keys it cannot read."""
    if not isinstance(keys, str):
        return None
    parts = [p.strip() for p in keys.split("+") if p.strip()]
    # "SUPER+" has no key at all (and SUPER++ would be the + key, which xkb
    # spells "plus"): without this the modifier would be taken for the key.
    if keys.rstrip().endswith("+"):
        return None
    if not parts:
        return None
    key = parts.pop()
    mods = set()
    for m in parts:
        alias = MOD_ALIAS.get(m.upper())
        if not alias:
            return None
        mods.add(alias)
    if not KEY_RE.match(key):
        return None
    return "+".join([m for m in MOD_ORDER if m in mods] + [key.upper()])


def nice(keys):
    """How the page and the file write keys: canon()'s modifiers, the key as
    xkb spells it (a single letter upper case): "SUPER+SHIFT+Return"."""
    if canon(keys) is None:
        return keys
    parts = [p.strip() for p in keys.split("+") if p.strip()]
    key = parts.pop()
    mods = {MOD_ALIAS[m.upper()] for m in parts}
    key = key.upper() if len(key) == 1 else key
    return "+".join([m for m in MOD_ORDER if m in mods] + [key])


def live_keys(bind):
    """A `hyprctl binds -j` entry's keys: "SUPER+SHIFT+left"."""
    key = bind.get("key") or (f"code:{bind['keycode']}" if bind.get("keycode") else "?")
    mask = bind.get("modmask", 0)
    mods = [name for bit, name in MOD_BITS if mask & bit]
    return "+".join(mods + [key.upper() if len(key) == 1 else key])


def live_canon(bind):
    return live_keys(bind).upper()


# Keys that are only modifiers: pressing one alone is not a shortcut yet,
# the capture box waits for the key that goes with it.
MODIFIER_KEYS = re.compile(r"^(Super|Hyper|Meta|Control|Alt|Shift|ISO_Level\d|Caps|Num)_?(L|R|Lock|Shift)?$")


def keys_from_event(mods, keyname):
    """What the capture box makes of a key press: mods is the set of held
    modifiers ("SUPER", "CTRL", "ALT", "SHIFT"), keyname the key as xkb names
    it WITHOUT shift (GTK's keyval at level 0: "1", not "exclam" -- Hyprland
    matches binds the same way). "SUPER+SHIFT+Return"; None while only
    modifiers are held or for a key that has no name."""
    if not keyname or MODIFIER_KEYS.match(keyname):
        return None
    keys = "+".join([m for m in MOD_ORDER if m in mods] + [keyname])
    return nice(keys) if canon(keys) else None


def app_safe(keys):
    """A warning when Hyprland would take these keys from every app (no Super
    or Alt on them, and not a function or media key), else ""."""
    c = canon(keys) or ""
    mods, key = c.split("+")[:-1], c.split("+")[-1]
    if "SUPER" in mods or "ALT" in mods or re.match(r"^(F\d+|XF86.*|MOUSE.*|PRINT)$", key):
        return ""
    return (f"{nice(keys)} has no Super or Alt in it: Hyprland will take it before any app sees it "
            f"(typing or an app's own shortcut on those keys stops working)")


# -- the file ------------------------------------------------------------------------------
def empty():
    return {"off": {}, "moves": {}, "adds": []}


def parse(text):
    """userbinds.conf -> {"off": {CANON: desc}, "moves": {CANON: (to, desc)},
    "adds": [{"keys", "desc", "cmd"}]}. Lines it cannot read are skipped,
    as lua/userbinds.lua skips them."""
    over = empty()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        f = line.rstrip("\r").split("\t")
        kind, a = f[0], canon(f[1]) if len(f) > 1 else None
        if kind == "off" and a:
            over["off"][a] = f[2] if len(f) > 2 else ""
        elif kind == "move" and a and len(f) > 2 and canon(f[2]):
            over["moves"][a] = (nice(f[2]), f[3] if len(f) > 3 else "")
        elif kind == "add" and a and len(f) > 3 and f[3].strip():
            over["adds"].append({"keys": nice(f[1]), "desc": f[2], "cmd": f[3]})
    return over


def clean(text):
    """No TABs or line breaks in a field: they are the file's separators."""
    return " ".join(str(text).replace("\t", " ").splitlines()).strip()


def dump(over):
    lines = ["# Your keyboard shortcut changes: Settings > Keyboard shortcuts, or",
             "# ~/.config/hypr/scripts/shortcuts.py. Read by ~/.config/hypr/lua/userbinds.lua.",
             "# off <keys> <what>  |  move <default keys> <new keys> <what>  |  add <keys> <name> <command>",
             "# (TAB between fields). Delete this file to undo every change."]
    for a, desc in sorted(over["off"].items()):
        lines.append("\t".join(["off", a, clean(desc)]))
    for a, (to, desc) in sorted(over["moves"].items()):
        lines.append("\t".join(["move", a, nice(to), clean(desc)]))
    for add in over["adds"]:
        lines.append("\t".join(["add", nice(add["keys"]), clean(add["desc"]), clean(add["cmd"])]))
    return "\n".join(lines) + "\n"


def load(path=None):
    try:
        with open(path or FILE) as handle:
            return parse(handle.read())
    except OSError:
        return empty()


def save(over, path=None):
    path = path or FILE
    if not over["off"] and not over["moves"] and not over["adds"]:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as handle:
        handle.write(dump(over))
    os.replace(tmp, path)


@contextlib.contextmanager
def locked():
    """One writer at a time (the page and a terminal at once)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, ".userbinds.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


# -- what is live -------------------------------------------------------------------------
def hyprctl(*args, timeout=5):
    try:
        r = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout


def live_binds():
    rc, out = hyprctl("binds", "-j")
    try:
        data = json.loads(out) if rc == 0 else None
    except ValueError:
        data = None
    return data if isinstance(data, list) else None


def live_report():
    """userbinds.report() from the running config: [(default, now|None,
    desc)], the errors -- or (None, []) when Hyprland has no userbinds (it
    was not reloaded since lua/userbinds.lua arrived, or it failed)."""
    rc, out = hyprctl("repl", "return userbinds and userbinds.report() or '__none__'")
    if rc != 0 or out.strip() in ("__none__", "nil") or out.startswith("error"):
        return None, []
    rep, errors = [], []
    for line in out.splitlines():
        f = line.split("\t")
        if f[0] == "bind" and len(f) >= 4:
            rep.append((f[1], None if f[2] == "-" else f[2], f[3]))
        elif f[0] == "error" and len(f) >= 2:
            errors.append(f[1])
    return rep, errors


def group_of(desc):
    section, _, text = (desc or "").partition(": ")
    return (section, text) if text else ("Other", desc or "")


def build(binds, report, over):
    """Every shortcut as a dict, from what is live (binds: `hyprctl binds
    -j`; report: userbinds.report(), or None) and what the file asks for:

        keys      the keys it is on now (its default keys when it is off)
        default   its keys in the config (None for one of your own)
        state     "default", "moved", "off", "custom", "mode" (inside a
                  submap: only live in that mode) or "fixed" (made outside
                  userbinds.lua: shown, not changeable)
        pending   the file asks for something Hyprland has not loaded yet
        group, what, desc, submap, mouse, cmd (custom), conflicts [desc]
    Pure: the tests feed it made-up input."""
    binds = binds or []
    out = []
    # Live binds still to be explained: the report's ones are taken out first.
    rest = list(binds)

    def take(keys, desc):
        for i, b in enumerate(rest):
            if not b.get("submap") and live_canon(b) == keys and (b.get("description") or "") == desc:
                return rest.pop(i)
        return None

    if report is not None:
        for default, now, desc in report:
            b = take(now, desc) if now else None
            if now is None:
                state = "off"
            elif now != default:
                state = "moved"
            else:
                state = "default"
            want = ("off" if default in over["off"] else
                    canon(over["moves"][default][0]) if default in over["moves"] else default)
            have = "off" if now is None else now
            # Keys as Hyprland spells them (SUPER+Return, not SUPER+RETURN)
            # when the live bind was found, else as the file wrote them.
            if b:
                shown = live_keys(b)
            elif now and default in over["moves"] and canon(over["moves"][default][0]) == now:
                shown = over["moves"][default][0]
            else:
                shown = now or default
            out.append({"keys": shown, "default": default, "state": state,
                        "pending": want != have, "desc": desc, "submap": "",
                        "mouse": bool(b and b.get("mouse")) or "MOUSE" in (now or default),
                        "wanted": None if want == have else want})
    for add in over["adds"]:
        b = take(canon(add["keys"]), add["desc"])
        out.append({"keys": nice(add["keys"]), "default": None, "state": "custom", "pending": b is None,
                    "desc": add["desc"], "submap": "", "mouse": False, "cmd": add["cmd"], "wanted": None})
    for b in rest:
        if b.get("submap") == "keycapture":          # userbinds.lua's own way out, not a shortcut
            continue
        desc = b.get("description") or ""
        if b.get("submap"):
            state = "mode"
        else:
            state = "default" if report is None else "fixed"
        default = live_canon(b)
        entry = {"keys": live_keys(b), "default": default, "state": state, "pending": False, "desc": desc,
                 "submap": b.get("submap") or "", "mouse": bool(b.get("mouse")), "wanted": None}
        if report is None and not b.get("submap"):
            # No report: the binds are taken as defaults and the file's
            # changes as not loaded yet.
            want = ("off" if default in over["off"] else
                    canon(over["moves"][default][0]) if default in over["moves"] else default)
            if want != default:
                entry.update(pending=True, wanted=want)
        out.append(entry)
    # Shared keys: two live shortcuts in the same place both fire.
    where = {}
    for e in out:
        if e["state"] != "off" and not (e["pending"] and e["state"] == "custom"):
            where.setdefault((e["submap"], canon(e["keys"]) or e["keys"].upper()), []).append(e)
    for e in out:
        e["group"], e["what"] = group_of(e["desc"])
        if e["state"] == "custom" and e["group"] == "Other":
            e["group"] = "Custom"
        e["conflicts"] = []
        if e["state"] != "off":
            e["conflicts"] = [o["desc"] or o["keys"] for o in where.get((e["submap"], canon(e["keys"]) or
                                                                          e["keys"].upper()), []) if o is not e]
    return out


def gather():
    binds = live_binds()
    report, errors = live_report() if binds is not None else (None, [])
    return build(binds, report, load()), binds is not None, report is not None, errors


# -- changing -----------------------------------------------------------------------------
class Refused(Exception):
    """A change that was not made, with the reason; exit 1 (3 for keys in use)."""

    def __init__(self, text, code=1):
        super().__init__(text)
        self.code = code


def editable(entries, keys, by_default=False):
    """The changeable shortcut on <keys> (its keys now, or its default ones).
    by_default (--default): <keys> are its DEFAULT keys and nothing else --
    what the settings page sends, because after a swap the keys one shortcut
    is on now can be another one's default (the window switcher moved off
    SUPER+W and the overview moved onto it: "off SUPER+W" alone means the
    overview, "off SUPER+W --default" the switcher)."""
    c = canon(keys)
    if c is None:
        raise Refused(f"can't read the keys {keys!r} (write them like SUPER+SHIFT+N)")
    tries = (lambda e: canon(e["keys"]) == c and e["state"] != "off",
             lambda e: e["default"] == c)
    for match in tries[1:] if by_default else tries:
        found = [e for e in entries if e["state"] in ("default", "moved", "off") and match(e)]
        if found:
            return found[0]
    other = [e for e in entries if canon(e["keys"]) == c]
    if other and other[0]["state"] == "custom":
        raise Refused(f"{nice(keys)} is one of your own shortcuts: use remove, or add it again")
    if other:
        raise Refused(f"{nice(keys)} ({other[0]['desc']}) is not one this can change")
    raise Refused(f"no shortcut on {nice(keys)}")


def occupants(entries, keys, exclude=None):
    c = canon(keys)
    return [e for e in entries if e is not exclude and not e["submap"] and e["state"] != "off"
            and canon(e["keys"]) == c]


def make_room(over, entries, keys, exclude, replace):
    """Free <keys> for a shortcut: refuse (code 3) when something uses them,
    or with replace turn those off / remove your own one there."""
    taken = occupants(entries, keys, exclude)
    if not taken:
        return []
    names = ", ".join(e["desc"] or e["keys"] for e in taken)
    if not replace:
        raise Refused(f"{nice(keys)} is already: {names}", 3)
    for e in taken:
        if e["state"] == "custom":
            over["adds"] = [a for a in over["adds"] if canon(a["keys"]) != canon(keys)]
        elif e["state"] in ("default", "moved"):
            over["moves"].pop(e["default"], None)
            over["off"][e["default"]] = e["desc"]
        else:
            raise Refused(f"{nice(keys)} is {names}, which can't be turned off here")
    return taken


def keysym_known(key):
    """Does Hyprland know this key name? It asks xkb the same way
    (case-insensitively), plus its own mouse and keycode names. An unknown
    name is a config error in Hyprland, so it must never reach the file.
    True when libxkbcommon cannot be asked (nothing better to go on)."""
    if re.match(r"^(mouse:\d+|mouse_(up|down|left|right)|code:\d+)$", key, re.I):
        return True
    try:
        import ctypes
        lib = ctypes.CDLL("libxkbcommon.so.0")
    except OSError:
        return True
    lookup = lib.xkb_keysym_from_name
    lookup.restype, lookup.argtypes = ctypes.c_uint32, [ctypes.c_char_p, ctypes.c_int]
    return lookup(key.encode(), 1) != 0       # 1 = XKB_KEYSYM_CASE_INSENSITIVE


def check_new(keys):
    c = canon(keys)
    if c is None:
        raise Refused(f"can't read the keys {keys!r} (write them like SUPER+SHIFT+N)")
    key = nice(keys).split("+")[-1]
    if not keysym_known(key):
        raise Refused(f"{key!r} is not a key name Hyprland knows (xkb names: q, F12, Return, left, "
                      f"bracketleft, XF86AudioPlay)")
    if c in ("SUPER+ESCAPE",):
        raise Refused("SUPER+Escape is kept free: it is the way out of the key-capture mode")
    return nice(keys)


def do_move(over, entries, keys, new, replace=False, by_default=False):
    e = editable(entries, keys, by_default)
    new = check_new(new)
    if canon(new) == e["default"]:
        if not (e["state"] == "default" and not e["pending"]):
            make_room(over, entries, new, e, replace)       # the reset rule, see do_reset
        over["moves"].pop(e["default"], None)
        over["off"].pop(e["default"], None)
        return f"{e['desc'] or new}: back on {new}"
    taken = make_room(over, entries, new, e, replace)
    over["off"].pop(e["default"], None)
    over["moves"][e["default"]] = (new, e["desc"])
    msg = f"{e['desc'] or e['default']}: now {new}"
    if taken:
        msg += " (turned off: " + ", ".join(t["desc"] for t in taken) + ")"
    warn = app_safe(new)
    return msg + (f". Note: {warn}" if warn else "")


def do_off(over, entries, keys, by_default=False):
    e = editable(entries, keys, by_default)
    over["moves"].pop(e["default"], None)
    over["off"][e["default"]] = e["desc"]
    return f"{e['desc'] or e['default']}: off"


def do_reset(over, entries, keys, by_default=False, replace=False):
    e = editable(entries, keys, by_default)
    # Back on its default keys -- unless something else has moved onto them
    # meanwhile: then both would fire, so it is refused (code 3) like a move
    # onto taken keys, or with replace that other one is turned off.
    if not (e["state"] == "default" and not e["pending"]):
        make_room(over, entries, e["default"], e, replace)
    over["moves"].pop(e["default"], None)
    over["off"].pop(e["default"], None)
    return f"{e['desc'] or e['default']}: back on {nice(e['default'])}"


def do_add(over, entries, keys, cmd, name, replace=False):
    keys = check_new(keys)
    cmd = clean(cmd)
    if not cmd:
        raise Refused("a shortcut of your own needs a command to run")
    name = clean(name) or cmd
    desc = name if ": " in name else f"Custom: {name}"
    mine = [a for a in over["adds"] if canon(a["keys"]) == canon(keys)]
    others = [e for e in occupants(entries, keys) if not (e["state"] == "custom" and mine)]
    if others:
        make_room(over, others, keys, None, replace)
    over["adds"] = [a for a in over["adds"] if canon(a["keys"]) != canon(keys)]
    over["adds"].append({"keys": keys, "desc": desc, "cmd": cmd})
    warn = app_safe(keys)
    return f"{keys}: {name}" + (f". Note: {warn}" if warn else "")


def do_remove(over, keys):
    c = canon(keys)
    before = len(over["adds"])
    over["adds"] = [a for a in over["adds"] if canon(a["keys"]) != c]
    if len(over["adds"]) == before:
        raise Refused(f"none of your own shortcuts is on {nice(keys) if c else keys}")
    return f"{nice(keys)}: removed"


def apply():
    """Have the running Hyprland re-read the file. "" when it did, else why not."""
    rc, out = hyprctl("eval", "userbinds.apply()")
    if rc == 0:
        return ""
    if "userbinds" in out and "nil" in out:
        return "saved; Hyprland picks it up at its next reload (it has not loaded lua/userbinds.lua yet)"
    return "saved, but Hyprland did not take it: " + (out.strip().splitlines() or ["no answer"])[-1]


def change(fn, *args):
    """Read the file, let fn change it, save, apply -- under the lock."""
    with locked():
        over = load()
        entries, _ok, _rep, _errors = gather()
        msg = fn(over, entries, *args)
        save(over)
    problem = apply()
    return msg + (f" -- {problem}" if problem else "")


CAPTURE_TOKEN = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "hypr-keycapture")
CAPTURE_LIMIT = 20      # seconds; the page gives up after 15 on its own


def capture(on):
    """The keycapture submap on or off. Turning it on also starts a
    watchdog: if whoever turned it on never turns it off again (the settings
    window crashed, was killed), no shortcut would fire until SUPER+Escape --
    so after CAPTURE_LIMIT seconds the watchdog turns it off itself, unless
    it was turned off (or on again, with a new token) in the meantime."""
    rc, out = hyprctl("dispatch", f'hl.dsp.submap("{"keycapture" if on else "reset"}")')
    if rc != 0:
        print(f"hyprctl: {out.strip()}", file=sys.stderr)
        return 1
    if on:
        token = f"{os.getpid()}-{os.urandom(4).hex()}"
        with open(CAPTURE_TOKEN, "w") as handle:
            handle.write(token)
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "capture-watchdog", token],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        with contextlib.suppress(OSError):
            os.remove(CAPTURE_TOKEN)
    print(f"key capture {'on' if on else 'off'}")
    return 0


def capture_watchdog(token):
    import time
    time.sleep(CAPTURE_LIMIT)
    try:
        with open(CAPTURE_TOKEN) as handle:
            if handle.read().strip() != token:
                return 0        # turned off, or on again by someone newer
    except OSError:
        return 0
    rc, out = hyprctl("submap")
    if out.strip() == "keycapture":
        hyprctl("dispatch", 'hl.dsp.submap("reset")')
    with contextlib.suppress(OSError):
        os.remove(CAPTURE_TOKEN)
    return 0


def launch(app_id):
    """Open an app by its desktop id, the way the launcher does: as its own
    systemd scope under uwsm, plainly with gtk-launch otherwise."""
    app_id = app_id if app_id.endswith(".desktop") else app_id + ".desktop"
    if "UWSM_FINALIZE_VARNAMES" in os.environ or os.environ.get("XDG_SESSION_DESKTOP", "").startswith("uwsm"):
        os.execvp("uwsm", ["uwsm", "app", "--", app_id])
    os.execvp("gtk-launch", ["gtk-launch", app_id.removesuffix(".desktop")])


# -- the command line ---------------------------------------------------------------------
def print_list(entries):
    for e in sorted(entries, key=lambda e: (e["group"], e["what"])):
        tag = {"moved": f"  (default {nice(e['default'])})", "off": "  (off)", "custom": "  (yours)",
               "mode": f"  (in {e['submap']} mode)"}.get(e["state"], "")
        tag += "  [pending]" if e["pending"] else ""
        tag += ("  !! also: " + "; ".join(e["conflicts"])) if e["conflicts"] else ""
        print(f"{e['keys']:<28} {e['desc'] or '(no description)'}{tag}")


def main(argv):
    flags = {a for a in argv if a.startswith("--") and a in ("--json", "--replace", "--default")}
    args = [a for a in argv if a not in flags]
    name = ""
    if "--name" in args:
        i = args.index("--name")
        name = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    cmd, rest = (args[0], args[1:]) if args else ("list", [])
    replace = "--replace" in flags
    by_default = "--default" in flags
    try:
        if cmd == "list":
            entries, ok, rep, _errors = gather()
            if not ok:
                print("hyprctl did not answer (is Hyprland running?)", file=sys.stderr)
                return 1
            if "--json" in flags:
                json.dump(entries, sys.stdout)
                print()
            else:
                print_list(entries)
            return 0
        if cmd == "find" and len(rest) == 1:
            entries = gather()[0]
            on = [e for e in entries if canon(e["keys"]) == canon(rest[0]) and e["state"] != "off"]
            print("; ".join(e["desc"] or "(no description)" for e in on) or f"nothing on {nice(rest[0])}")
            return 0
        if cmd == "status":
            entries, ok, rep, errors = gather()
            over = load()
            if "--json" in flags:
                json.dump({"file": FILE, "hyprland": ok, "loaded": rep is not None, "errors": errors,
                           "off": len(over["off"]), "moved": len(over["moves"]), "custom": len(over["adds"]),
                           "pending": sum(1 for e in entries if e["pending"])}, sys.stdout)
                print()
                return 0
            print(f"file: {FILE} ({len(over['off'])} off, {len(over['moves'])} moved, "
                  f"{len(over['adds'])} of your own)")
            print("hyprland: " + ("not answering" if not ok else "changes loaded" if rep is not None
                                  else "has not loaded lua/userbinds.lua yet (next reload)"))
            pending = [e for e in entries if e["pending"]]
            if pending:
                print(f"pending: {len(pending)} (shortcuts.py apply)")
            for err in errors:
                print("problem: " + err)
            return 0
        if cmd == "move" and len(rest) == 2:
            print(change(do_move, rest[0], rest[1], replace, by_default))
        elif cmd == "off" and len(rest) == 1:
            print(change(do_off, rest[0], by_default))
        elif cmd in ("on", "reset") and len(rest) == 1:
            print(change(do_reset, rest[0], by_default, replace))
        elif cmd == "reset" and not rest:
            with locked():
                save(empty())
            problem = apply()
            print("every shortcut back to its default, your own removed" + (f" -- {problem}" if problem else ""))
        elif cmd == "add" and len(rest) >= 2:
            print(change(do_add, rest[0], " ".join(rest[1:]), name, replace))
        elif cmd == "add-app" and len(rest) == 2:
            app = rest[1] if rest[1].endswith(".desktop") else rest[1] + ".desktop"
            if not re.match(r"^[\w.+-]+\.desktop$", app):
                raise Refused(f"{rest[1]!r} is not a desktop id (like firefox.desktop)")
            print(change(do_add, rest[0], f"{SELF} launch {app}", name or f"Open {app.removesuffix('.desktop')}",
                         replace))
        elif cmd == "remove" and len(rest) == 1:
            print(change(lambda over, _entries, k: do_remove(over, k), rest[0]))
        elif cmd == "apply":
            problem = apply()
            print(problem or "loaded")
            return 1 if problem else 0
        elif cmd == "capture" and rest in (["on"], ["off"]):
            return capture(rest[0] == "on")
        elif cmd == "capture-watchdog" and len(rest) == 1:
            return capture_watchdog(rest[0])
        elif cmd == "launch" and len(rest) == 1:
            launch(rest[0])
        else:
            print(__doc__.strip(), file=sys.stderr)
            return 2
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
