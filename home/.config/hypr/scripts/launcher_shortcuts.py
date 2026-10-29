#!/usr/bin/env python3
"""Keyboard shortcuts in the launcher (launcher.py): type what a shortcut
does -- "terminal", "fullscreen", "screenshot" -- and its row shows the keys
it is on; Enter does what the keys would have done.

The list is the one the shortcuts panel (SUPER+F1, waybar's
keybinds_panel.py) shows: every `hyprctl binds -j` entry with a
description ("Section: what it does"), outside the submaps, read again each
time the launcher shows -- so a shortcut you moved (Settings > Keyboard
shortcuts) is listed on its new keys. Mouse drags (move / resize with the
mouse) are left out: there is nothing to run without the pointer.

Running one. Every bind in this config is a Lua function or a dispatcher
object (lua/binds.lua through hl.bind), which `hyprctl binds -j` reports as
"__lua" with a number, not as something hyprctl can dispatch. But
lua/userbinds.lua keeps every bind it made in userbinds.binds ({keys now,
dispatcher, options}), so run_lua() asks Hyprland, through `hyprctl repl`,
for the bind on these keys with this description and calls it: the
function, or hl.dispatch() of the dispatcher. Nothing is pressed and no key
is faked. A shortcut of your own (Settings > Keyboard shortcuts > Add) is
not in that table; its row is still listed, and Enter says it cannot run it
from here.

    launcher_shortcuts.py [words]   the shortcuts the launcher would offer
                                    for the words (all of them without),
                                    for checking from a terminal

Pure parts (tests/test_launcher_shortcuts.py): entries(), pretty_keys(),
lua_quote(), run_lua(), wants_only(), word_hits(), matches(),
spawn_argv().
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shortcuts  # noqa: E402  (canon / live_keys: one spelling of keys for the whole desktop)

PREFIXES = ("keys ", "keys:", "shortcut ", "shortcuts ")     # what lists ONLY the shortcuts
ALONE = ("keys", "shortcut", "shortcuts", "atajos")          # the word alone: every one

KEY_GLYPHS = {"left": "←", "right": "→", "up": "↑", "down": "↓", "Return": "Enter",
              "escape": "Esc", "Escape": "Esc", "space": "Space", "Print": "PrtSc",
              "period": ".", "comma": ",", "slash": "/", "minus": "-", "equal": "=",
              "grave": "`", "mouse_down": "Wheel down", "mouse_up": "Wheel up",
              "Tab": "Tab", "BackSpace": "Backspace", "Delete": "Del"}


def entries(binds):
    """`hyprctl binds -j` -> [{keys, label, section, text, desc}], in config
    order, one per (keys, description). keys is canon()'s spelling
    ("SUPER+SHIFT+LEFT"), what run_lua() looks the bind up by; label is
    for people ("SUPER + SHIFT + ←")."""
    out, seen = [], set()
    for b in binds or ():
        if not isinstance(b, dict):
            continue
        desc = (b.get("description") or "").strip()
        if not desc or b.get("submap") or b.get("mouse"):
            continue
        live = shortcuts.live_keys(b)
        keys = shortcuts.canon(live)
        if not keys or (keys, desc) in seen:
            continue
        seen.add((keys, desc))
        section, text = shortcuts.group_of(desc)
        out.append({"keys": keys, "label": pretty_keys(live), "section": section,
                    "text": text, "desc": desc})
    return out


def pretty_keys(keys):
    """"SUPER+SHIFT+left" -> "SUPER + SHIFT + ←": the key as people say it."""
    parts = [p for p in (keys or "").split("+") if p]
    if not parts:
        return keys or ""
    key = parts[-1]
    key = KEY_GLYPHS.get(key, key.upper() if len(key) == 1 else key)
    return " + ".join(parts[:-1] + [key])


def lua_quote(text):
    """A Lua string literal for text (any bytes of it; never through a shell)."""
    out = []
    for ch in str(text):
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\{ord(ch):03d}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def run_lua(keys, desc):
    """The `hyprctl repl` chunk that runs the bind on `keys` (canon spelling)
    with description `desc`: userbinds.binds holds each bind's keys now and
    its dispatcher (see the docstring). Returns "ran" or "none"."""
    return ("local want, desc = " + lua_quote(keys) + ", " + lua_quote(desc) + "\n"
            "local U = userbinds\n"
            "if not U or not U.binds then return 'none' end\n"
            "for _, e in ipairs(U.binds) do\n"
            "  if e.now and U.canon(e.now) == want and e.opts and e.opts.description == desc then\n"
            "    if type(e.dsp) == 'function' then e.dsp() else hl.dispatch(e.dsp) end\n"
            "    return 'ran'\n"
            "  end\n"
            "end\n"
            "return 'none'")


def wants_only(text):
    """"keys term" -> "term", "keys" -> "": the words when the query asks for
    shortcuts only; None when it does not."""
    low = (text or "").lstrip().lower()
    if low.strip() in ALONE:
        return ""
    for p in PREFIXES:
        if low.startswith(p):
            return low[len(p):].strip()
    return None


def word_hits(entry, word):
    """Does one typed word find this shortcut? A key or modifier by its name
    ("super", "s", "left"; a single letter only so), a word of the description by its start ("scr"),
    and three letters or more anywhere in it ("shot")."""
    word = word.lower()
    keys = [k.lower() for k in entry["keys"].split("+")]
    if word in keys or word in ("ctrl", "control") and "ctrl" in keys:
        return True
    if len(word) == 1:
        return False        # "s" is the S key, not every word that starts with s
    desc = entry["desc"].lower()
    if any(w.startswith(word) for w in desc.replace(":", " ").split()):
        return True
    return len(word) >= 3 and word in desc


def matches(items, words):
    """The entries every word finds (word_hits): "term", "super q",
    "screenshot region". Exactly the keys typed ("super s") first."""
    words = (words or "").lower().split()
    found = [e for e in items if all(word_hits(e, w) for w in words)]
    typed = set(words)
    found.sort(key=lambda e: {k.lower() for k in e["keys"].split("+")} != typed)
    return found


def read_binds(timeout=2):
    try:
        out = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True,
                             timeout=timeout).stdout
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return data if isinstance(data, list) else []


def run(entry):
    """Run it now (the launcher spawns the same chunk after it has gone:
    spawn_argv). True when Hyprland found the bind."""
    try:
        r = subprocess.run(["hyprctl", "repl", run_lua(entry["keys"], entry["desc"])],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() == "ran"


def spawn_argv(entry, notify, delay=0.2):
    """What the launcher runs on Enter: wait `delay` s (its card gone, the
    keyboard back with the window the shortcut acts on), run the bind, and
    say so in a notification when Hyprland had no such bind to run (one of
    your own shortcuts, or the config reloaded meanwhile)."""
    return ["sh", "-c", 'sleep "$1"; out=$(hyprctl repl "$2" 2>&1); [ "$out" = ran ] || '
            '"$3" -a Launcher -i dialog-warning "Shortcut not run" "$4 -- press $5 instead"',
            "sh", str(delay), run_lua(entry["keys"], entry["desc"]), notify, entry["desc"], entry["label"]]


def main(argv):
    for e in matches(entries(read_binds()), " ".join(argv)):
        print(f"{e['label']:<28} {e['desc']}")


if __name__ == "__main__":
    main(sys.argv[1:])
