#!/usr/bin/env python3
"""Keyboard, mouse and touchpad settings: one front for Settings > Keyboard,
mouse & touchpad, the search bar and the terminal, so they can never disagree
about what is in effect.

    input-settings.py status              JSON: every setting (value, default,
                                          changed?), the layouts with their
                                          names and which one is active,
                                          whether there is a touchpad, the
                                          input methods, and what Hyprland
                                          reports live
    input-settings.py get <key>           one value
    input-settings.py set <key> <value>   one setting, checked, applied at once
    input-settings.py unset <key>         that one back to its default
    input-settings.py reset               every setting back to its default
    input-settings.py keys                the keys and what each accepts

    input-settings.py layout add <code>[(<variant>)]   e.g. de, us(intl)
    input-settings.py layout remove <code>[(<variant>)]
    input-settings.py layout up|down <code>[(<variant>)]   switching order
    input-settings.py layout next         switch to the next layout now
    input-settings.py layouts [words]     the system's xkb layouts and their
                                          variants, "code<TAB>name" per line,
                                          the ones matching every word
    input-settings.py options <group>     the xkb options of a group (switch,
                                          caps, compose), "option<TAB>name"
    input-settings.py switch-label        the layout-switch key as people say
                                          it ("Super+Space", or "no key"), for
                                          the bar's language menu

    input-settings.py apply               re-apply the saved settings

The settings live in ~/.local/state/hypr/input.conf (key=value, the format of
the display state -- ~/.config/hypr/lua/shared.lua). This writes the file and
then asks Hyprland to re-run the Lua that reads it at every config load:

    hyprctl eval 'require("lua.input").apply()'

so a change applies now through the same code that puts it back after a
reload, a gamemode OFF or a re-login. The DEFAULTS are lua/input.lua's own
table, read from that file (between its INPUT-DEFAULTS markers), so there is
one list of defaults, not two.

Layouts and xkb options are checked against the system's own list
(/usr/share/X11/xkb/rules/evdev.lst, what every layout picker reads): a name
xkb does not know would leave the keyboard on a fallback keymap, so it is
refused here instead. xkb holds at most four layouts at a time.

Keyboard layouts (xkb) and input methods (fcitx5: Japanese via Mozc) are two
different switches that stack -- lua/autostart.lua explains it. This script is
the first; fcitx5 keeps its own list (~/.config/fcitx5/profile), which status
only reports.
"""

import configparser
import contextlib
import fcntl
import html
import json
import os
import re
import subprocess
import sys

HYPR = os.path.expanduser("~/.config/hypr")
INPUT_LUA = os.path.join(HYPR, "lua", "input.lua")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "input.conf")
XKB_RULES = "/usr/share/X11/xkb/rules/evdev.lst"
FCITX_PROFILE = os.path.expanduser("~/.config/fcitx5/profile")
UDEV_DATA = "/run/udev/data"
MAX_LAYOUTS = 4                       # an xkb keymap has four groups

# What each key accepts. "xkb:<prefixes>" is one option (or none) from those
# groups of the system's xkb option list. Ranges are what lua/input.lua
# clamps to, so a value accepted here is never quietly replaced there.
KEYS = {
    "layouts":                       ("layouts",),
    "switch":                        ("xkb", "grp"),
    "caps":                          ("xkb", "caps", "ctrl:nocaps", "ctrl:swapcaps"),
    "compose":                       ("xkb", "compose"),
    "xkb_extra":                     ("xkblist",),
    "repeat_rate":                   ("int", 1, 100),
    "repeat_delay":                  ("int", 100, 2000),
    "numlock":                       ("bool",),
    "sensitivity":                   ("float", -1.0, 1.0),
    "accel":                         ("choice", "adaptive", "flat"),
    "natural_scroll":                ("bool",),
    "left_handed":                   ("bool",),
    "scroll_factor":                 ("float", 0.1, 5.0),
    "middle_click_paste":            ("bool",),
    "hide_on_typing":                ("bool",),
    "follow_mouse":                  ("choice", "0", "1", "2"),
    "touchpad.natural_scroll":       ("bool",),
    "touchpad.tap_to_click":         ("bool",),
    "touchpad.disable_while_typing": ("bool",),
    "touchpad.clickfinger":          ("bool",),
    "touchpad.scroll_factor":        ("float", 0.1, 5.0),
}
# What Hyprland reports for each key, to show "live" next to "saved".
LIVE = {
    "repeat_rate": "input:repeat_rate", "repeat_delay": "input:repeat_delay",
    "sensitivity": "input:sensitivity", "accel": "input:accel_profile",
    "natural_scroll": "input:natural_scroll", "left_handed": "input:left_handed",
    "scroll_factor": "input:scroll_factor", "follow_mouse": "input:follow_mouse",
    "numlock": "input:numlock_by_default", "hide_on_typing": "cursor:hide_on_key_press",
    "middle_click_paste": "misc:middle_click_paste",
}
OPTION_GROUPS = {"switch": "switch", "caps": "caps", "compose": "compose"}
TRUE, FALSE = ("on", "yes", "true", "1"), ("off", "no", "false", "0")


# -- defaults (lua/input.lua) ---------------------------------------------------
def parse_defaults(text):
    """The DEFAULTS table of lua/input.lua: {key: value}, from the lines
    between the INPUT-DEFAULTS markers."""
    inside, out = False, {}
    for line in text.splitlines():
        if "INPUT-DEFAULTS-BEGIN" in line:
            inside = True
        elif "INPUT-DEFAULTS-END" in line:
            break
        elif inside:
            m = re.match(r'\s*\["([^"]+)"\]\s*=\s*"([^"]*)"', line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def defaults():
    try:
        with open(INPUT_LUA) as handle:
            return parse_defaults(handle.read())
    except OSError:
        return {}


# -- state -----------------------------------------------------------------------
def read_state():
    state = {}
    try:
        with open(STATE) as handle:
            for line in handle:
                if line.lstrip().startswith("#"):
                    continue
                key, sep, value = line.partition("=")
                if sep:
                    state[key.strip()] = value.strip()
    except OSError:
        pass
    return state


def write_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("# Keyboard, mouse & touchpad (input-settings.py; read by ~/.config/hypr/lua/input.lua)\n")
        for key in sorted(state):
            handle.write(f"{key}={state[key]}\n")
    os.replace(tmp, STATE)     # atomic: Lua may read it at any moment


def effective(state=None, defs=None):
    """Every key: the saved value, or the default."""
    state = read_state() if state is None else state
    defs = defaults() if defs is None else defs
    return {key: state.get(key, defs.get(key, "")) for key in KEYS}


# -- the system's xkb list ---------------------------------------------------------
def parse_xkb(text):
    """evdev.lst -> {"layouts": {code: name}, "variants": {(code, variant): name},
    "options": {option: name}}."""
    out = {"layouts": {}, "variants": {}, "options": {}}
    section = None
    for line in text.splitlines():
        if line.startswith("!"):
            section = line[1:].strip()
            continue
        if not line.strip():
            continue
        code, _, desc = line.strip().partition(" ")
        desc = html.unescape(desc.strip())
        if section == "layout":
            out["layouts"].setdefault(code, desc)
        elif section == "variant":
            parent, _, name = desc.partition(":")
            out["variants"].setdefault((parent.strip(), code), name.strip())
        elif section == "option" and ":" in code:
            out["options"].setdefault(code, desc)
    return out


_XKB = None


def xkb():
    global _XKB
    if _XKB is None:
        try:
            with open(XKB_RULES) as handle:
                _XKB = parse_xkb(handle.read())
        except OSError:
            _XKB = {"layouts": {}, "variants": {}, "options": {}}
    return _XKB


def parse_layouts(spec):
    """ "us,latam(deadtilde)" -> [("us", ""), ("latam", "deadtilde")]."""
    out = []
    for tok in re.split(r"[,\s]+", spec or ""):
        if not tok:
            continue
        m = re.fullmatch(r"([\w-]+)\(([\w-]*)\)", tok)
        out.append((m.group(1), m.group(2)) if m else (tok, ""))
    return out


def format_layouts(pairs):
    return ",".join(f"{c}({v})" if v else c for c, v in pairs)


def layout_name(code, variant, cat=None):
    cat = cat or xkb()
    if variant:
        return cat["variants"].get((code, variant)) or f"{cat['layouts'].get(code, code)} ({variant})"
    return cat["layouts"].get(code, code)


def search_layouts(words, cat=None, limit=None):
    """[(token, name)] for every layout and variant whose code or name holds
    every word (case-insensitive); plain layouts first, then by name."""
    cat = cat or xkb()
    words = [w.lower() for w in words if w]
    rows = [(code, name, 0) for code, name in cat["layouts"].items()]
    rows += [(f"{c}({v})", name, 1) for (c, v), name in cat["variants"].items()]
    hits = [(tok, name, rank) for tok, name, rank in rows
            if all(w in tok.lower() or w in name.lower() for w in words)]
    # An exact code match ("de") first, then plain layouts, then variants.
    hits.sort(key=lambda r: (r[0].lower() not in words, r[2], r[1].lower()))
    hits = [(tok, name) for tok, name, _ in hits]
    return hits[:limit] if limit else hits


def options(group, cat=None):
    """[(option, name)] for a KEYS xkb group ("switch", "caps", "compose")."""
    cat = cat or xkb()
    spec = KEYS[group]
    prefixes = [p for p in spec[1:] if ":" not in p]
    singles = [p for p in spec[1:] if ":" in p]
    out = [(o, n) for o, n in cat["options"].items() if o.split(":")[0] in prefixes]
    out += [(o, cat["options"][o]) for o in singles if o in cat["options"]]
    if group == "switch":
        # Only the ones that SWITCH: grp:*_switch keys change layout only while
        # held, which reads as a bug when chosen by accident from a list.
        out = [(o, n) for o, n in out if not o.endswith("switch")]
    return out


def say_keys(name):
    """xkb's "Win+Space" as this desktop says it: "Super+Space"."""
    return re.sub(r"\bWin\b", "Super", name)


# Shortcuts that fight something already on this desktop.
def switch_warning(option):
    """A sentence when the layout-switch option collides with this desktop's
    own keys or takes a key away, else "". ALT is the main modifier
    (lua/shared.lua mainMod), so an Alt-based switch would also fire on every
    ALT+SHIFT+n bind; Ctrl+Space is fcitx5's input-method switch; Super is held
    for SUPER+Tab, SUPER+I...; a switch on a lone Shift or Ctrl turns that key
    into the switch, so it stops being Shift / Ctrl; and xkb fires Ctrl+Shift
    as soon as the second of the two goes down, so it also fires (and eats
    the Shift) during app shortcuts like Ctrl+Shift+T."""
    if not option:
        return "No key: switch from the language pill on the bar."
    name = option.split(":", 1)[-1]
    if name == "ctrl_space_toggle":
        return "Ctrl+Space is already the input method switch (Japanese): the two would fight."
    if name == "toggle" or re.search(r"(^|_)[lr]?alts?(_|$)", name):
        return ("ALT is this desktop's main modifier: layouts would also switch during ALT shortcuts "
                "such as ALT+SHIFT+1.")
    if re.search(r"(^|_)[lr]?win(_|$)", name) and name != "win_space_toggle":
        return "Super on its own would switch layout every time you start a SUPER shortcut."
    if name in ("lshift_toggle", "rshift_toggle"):
        return "That Shift key would stop typing capitals: it becomes only the layout switch."
    if name in ("lctrl_toggle", "rctrl_toggle", "ctrl_select"):
        return "That Ctrl key would stop working as Ctrl: it becomes only the layout switch."
    if re.fullmatch(r"([lr]?ctrl_[lr]?shift)_toggle(_bidir)?", name):
        return ("Ctrl+Shift app shortcuts (Ctrl+Shift+T, Ctrl+Shift+V in terminals) would also switch the "
                "layout, and can lose their Shift.")
    if name in ("caps_toggle", "caps_select"):
        return "Caps Lock stops locking capitals; Shift+Caps Lock does that instead."
    return ""


def key_clash(eff):
    """A sentence when the switch key is also the key picked for Caps Lock
    or Compose (both are xkb options on the same keymap: the last one wins,
    and which one that is is up to xkb), else ""."""
    name = (eff.get("switch") or "").split(":", 1)[-1]
    if not name:
        return ""
    words = set(name.split("_"))
    if eff.get("caps") and "caps" in words:
        return "Caps Lock is also given another job under Typing: pick one or the other."
    compose = (eff.get("compose") or "").split(":", 1)[-1]
    if compose and compose in words:
        return "That key is also the Compose key under Typing: pick one or the other."
    return ""


# -- checking a value -------------------------------------------------------------
def check(key, value, cat=None):
    """The value in the state file's own form, or ValueError with a sentence
    that says what is wrong."""
    if key not in KEYS:
        raise ValueError(f"no setting {key!r} (have: {', '.join(KEYS)})")
    spec, value = KEYS[key], str(value).strip()
    kind = spec[0]
    if kind == "bool":
        low = value.lower()
        if low in TRUE:
            return "on"
        if low in FALSE:
            return "off"
        raise ValueError(f"{key} is on or off")
    if kind in ("int", "float"):
        try:
            num = float(value)
        except ValueError:
            raise ValueError(f"{key} is a number from {spec[1]} to {spec[2]}") from None
        if not spec[1] <= num <= spec[2]:
            raise ValueError(f"{key} is from {spec[1]} to {spec[2]}")
        return str(int(round(num))) if kind == "int" else f"{round(num, 2):g}"
    if kind == "choice":
        if value not in spec[1:]:
            raise ValueError(f"{key} is one of {', '.join(spec[1:])}")
        return value
    cat = cat or xkb()
    if kind == "xkb":
        if value in ("", "none", "off"):
            return ""
        if value not in dict(options(key, cat)):
            raise ValueError(f"{value!r} is not one of the xkb options for {key} "
                             f"(input-settings.py options {key})")
        return value
    if kind == "xkblist":
        opts = [o for o in re.split(r"[,\s]+", value) if o]
        bad = [o for o in opts if o not in cat["options"]]
        if bad:
            raise ValueError(f"xkb does not know {', '.join(bad)}")
        return ",".join(opts)
    # layouts
    pairs = parse_layouts(value)
    if not pairs:
        raise ValueError("keep at least one keyboard layout")
    if len(pairs) > MAX_LAYOUTS:
        raise ValueError(f"xkb holds at most {MAX_LAYOUTS} layouts at a time")
    for code, variant in pairs:
        if code not in cat["layouts"]:
            raise ValueError(f"xkb has no layout {code!r} (input-settings.py layouts <words>)")
        if variant and (code, variant) not in cat["variants"]:
            raise ValueError(f"xkb has no variant {variant!r} of {code}")
    if len(set(pairs)) != len(pairs):
        raise ValueError("a layout is listed twice")
    return format_layouts(pairs)


def edit_layouts(spec, action, token):
    """The layouts string after add / remove / up / down of one token;
    ValueError when that cannot be done."""
    pairs = parse_layouts(spec)
    item = (parse_layouts(token) or [("", "")])[0]
    if action == "add":
        if item in pairs:
            raise ValueError(f"{token} is already there")
        if len(pairs) >= MAX_LAYOUTS:
            raise ValueError(f"xkb holds at most {MAX_LAYOUTS} layouts: remove one first")
        pairs.append(item)
        return format_layouts(pairs)
    if item not in pairs:
        raise ValueError(f"{token} is not one of the layouts ({format_layouts(pairs)})")
    i = pairs.index(item)
    if action == "remove":
        if len(pairs) == 1:
            raise ValueError("keep at least one keyboard layout")
        pairs.pop(i)
    elif action in ("up", "down"):
        j = i - 1 if action == "up" else i + 1
        if 0 <= j < len(pairs):
            pairs[i], pairs[j] = pairs[j], pairs[i]
    else:
        raise ValueError(f"layout {action}? (add, remove, up, down, next)")
    return format_layouts(pairs)


# -- compositor -------------------------------------------------------------------
def run(*cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def hypr_eval(code):
    try:
        out = subprocess.run(["hyprctl", "eval", code], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"hyprctl failed: {exc}"
    text = (out.stdout + out.stderr).strip()
    return None if out.returncode == 0 and text in ("", "ok") else text


def apply():
    return hypr_eval('require("lua.input").apply()')


def live_option(name):
    try:
        data = json.loads(run("hyprctl", "getoption", name, "-j") or "{}")
    except ValueError:
        return None
    for kind in ("int", "float", "str", "bool"):
        if kind in data:
            value = data[kind]
            return "" if value == "[[EMPTY]]" else value
    return None


def keyboards():
    """(active layout index, the active keymap's name) from the main keyboard,
    as the bar's language pill reads it."""
    try:
        boards = json.loads(run("hyprctl", "devices", "-j") or "{}").get("keyboards", [])
    except ValueError:
        boards = []
    main = next((k for k in boards if k.get("main")), boards[0] if boards else {})
    return main.get("active_layout_index", 0), main.get("active_keymap", "")


def has_touchpad():
    """True when udev tags any input device as a touchpad."""
    try:
        names = os.listdir(UDEV_DATA)
    except OSError:
        return False
    for name in names:
        if not name.startswith("c13:"):
            continue
        try:
            with open(os.path.join(UDEV_DATA, name)) as handle:
                if "E:ID_INPUT_TOUCHPAD=1" in handle.read():
                    return True
        except OSError:
            pass
    return False


def input_methods():
    """[(fcitx5 item, label)] from its profile, and the current one."""
    labels = {"keyboard-us": "Direct", "mozc": "Japanese (Mozc)"}
    profile = configparser.ConfigParser(interpolation=None)
    try:
        profile.read(FCITX_PROFILE)
    except configparser.Error:
        return [], ""
    items = [profile.get(s, "Name") for s in profile.sections()
             if s.startswith("Groups/0/Items/") and profile.has_option(s, "Name")]
    current = run("fcitx5-remote", "-n", timeout=2).strip()
    return [(i, labels.get(i, i)) for i in items], current


def status():
    defs, state = defaults(), read_state()
    eff = effective(state, defs)
    cat = xkb()
    active, keymap = keyboards()
    live = {key: live_option(opt) for key, opt in LIVE.items()}
    live_layout = live_option("input:kb_layout") or ""
    live_options = live_option("input:kb_options") or ""
    ims, im = input_methods()
    pairs = parse_layouts(eff["layouts"])
    switch_name = cat["options"].get(eff["switch"], "")
    return {
        "settings": {key: {"value": eff[key], "default": defs.get(key, ""), "changed": key in state}
                     for key in KEYS},
        "layouts": [{"token": format_layouts([p]), "code": p[0], "variant": p[1],
                     "name": layout_name(p[0], p[1], cat), "active": i == active}
                    for i, p in enumerate(pairs)],
        "max_layouts": MAX_LAYOUTS,
        "active_keymap": keymap,
        "switch_label": say_keys(switch_name) if switch_name else "",
        "switch_warning": " ".join(w for w in (switch_warning(eff["switch"]), key_clash(eff)) if w),
        "live": dict(live, kb_layout=live_layout, kb_options=live_options),
        # Saved and live disagree only when something other than this script
        # changed an option (a hand-run `hyprctl keyword`) or Hyprland refused one.
        "in_sync": live_layout == ",".join(c for c, _ in pairs),
        "touchpad": has_touchpad(),
        "input_methods": [{"name": n, "label": lab, "active": n == im} for n, lab in ims],
        "state_file": STATE,
    }


# -- commands ---------------------------------------------------------------------
@contextlib.contextmanager
def locked():
    """One writer at a time. Settings runs each control in its own thread,
    so two quick clicks are two of these processes at once: without the lock
    both read the file, each adds its key, and the second write loses the
    first one's. The lock file sits next to the state file."""
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + ".lock", "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def save(key, value):
    """One key (None = back to the default), written and applied. A value
    equal to the default is dropped rather than saved, so "changed" (and the
    page's count of changed settings) means "differs from the default"."""
    with locked():
        state = read_state()
        if value is None or value == defaults().get(key):
            state.pop(key, None)
        else:
            state[key] = value
        write_state(state)
        return apply()


def edit_saved_layouts(action, token):
    """layout add/remove/up/down, read and written under the lock."""
    with locked():
        new = check("layouts", edit_layouts(effective()["layouts"], action, token))
        state = read_state()
        if new == defaults().get("layouts"):
            state.pop("layouts", None)
        else:
            state["layouts"] = new
        write_state(state)
        return apply()


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "status":
            print(json.dumps(status(), indent=1, ensure_ascii=False))
        elif cmd == "get" and len(args) == 1:
            if args[0] not in KEYS:
                raise ValueError(f"no setting {args[0]!r}")
            print(effective()[args[0]])
        elif cmd == "set" and len(args) >= 1:
            err = save(args[0], check(args[0], " ".join(args[1:])))
            if err:
                print(f"saved, but Hyprland said: {err}", file=sys.stderr)
                return 1
        elif cmd == "unset" and len(args) == 1:
            if args[0] not in KEYS:
                raise ValueError(f"no setting {args[0]!r}")
            err = save(args[0], None)
            if err:
                print(f"Hyprland said: {err}", file=sys.stderr)
                return 1
        elif cmd == "reset":
            with locked():
                try:
                    os.remove(STATE)
                except FileNotFoundError:
                    pass
                err = apply()
            if err:
                print(f"Hyprland said: {err}", file=sys.stderr)
                return 1
        elif cmd == "keys":
            for key, spec in KEYS.items():
                print(f"{key}\t{' '.join(str(s) for s in spec)}")
        elif cmd == "layout" and args and args[0] == "next":
            run("hyprctl", "switchxkblayout", "all", "next")
        elif cmd == "layout" and len(args) == 2:
            err = edit_saved_layouts(args[0], args[1])
            if err:
                print(f"saved, but Hyprland said: {err}", file=sys.stderr)
                return 1
        elif cmd == "layouts":
            for tok, name in search_layouts(args):
                print(f"{tok}\t{name}")
        elif cmd == "options" and len(args) == 1 and args[0] in OPTION_GROUPS:
            for opt, name in options(args[0]):
                print(f"{opt}\t{name}")
        elif cmd == "switch-label":
            opt = effective()["switch"]
            print((say_keys(xkb()["options"].get(opt, "")) or opt) if opt else "no key")
        elif cmd == "apply":
            err = apply()
            if err:
                print(f"Hyprland said: {err}", file=sys.stderr)
                return 1
        else:
            print(__doc__.strip(), file=sys.stderr)
            return 2
    except ValueError as exc:
        print(f"input-settings: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
