#!/usr/bin/env python3
"""Automations: "when X, do Y" rules, followed by automations.service.

    automations.py run                    the daemon (automations.service)
    automations.py list [--json]          the rules, in words, with what they did last
    automations.py test RULE [--dry-run]  run RULE's actions now (--dry-run: only say them)
    automations.py enable|disable RULE    switch one on / off (enable also lifts a pause)
    automations.py delete RULE            remove one (built-in ones can only be switched off)
    automations.py add JSON               add a rule given as JSON (checked first)
    automations.py add-from-text "WORDS" [--yes|--json]
                                          the local "quick" model writes the rule from
                                          plain words; it is checked, shown, and saved
                                          only after you say yes (--yes: no question;
                                          --json: only print it, for Settings)
    automations.py check                  validate automations.json, exit 1 on problems
    automations.py catalog                JSON: the triggers and actions (Settings)
    automations.py event NAME             tell the daemon NAME happened (hypridle's
                                          idle-start / idle-end listener)

RULE is a rule's id or its name. The rules live in ~/.config/hypr/automations.json,
human-editable:

    {"rules": [
      {"id": "steam-headphones", "name": "Headphones for games", "enabled": true,
       "when": {"event": "game-start"},
       "do": [{"action": "sound-output", "value": "headphones"},
              {"action": "dnd", "value": "on"}],
       "cooldown": 10}
    ]}

"when" is one event and its options (EVENTS below says which; an option left
out matches anything); "do" is one to six actions, run in order; "cooldown"
(seconds, default 10) is how soon the rule may fire again. A file with a
broken rule keeps the rest working: the broken one is skipped, with the
reason in the journal and in `list`. Keys starting with "_" are ignored
(room for your own notes). The daemon re-reads the file when it changes.

Triggers, and where each comes from -- events where there are any, a cheap
poll where there are none, and nothing at all for a kind no enabled rule uses:

    app-open / app-close   Hyprland's event socket (openwindow / closewindow):
                           the FIRST window of a class matching "class" opening,
                           the LAST one closing -- an app, not every window
    game-start / game-end  the same socket: steam_app_* windows (the class
                           lua/gamemode.lua and auto-dnd.py key on); the end
                           waits RELEASE_S, as games go launcher -> game window
    monitor-added / -removed   the socket's monitoradded / monitorremoved
    audio-output           `pactl subscribe` (server change -> the default sink)
    wifi-connected / -disconnected   `nmcli monitor` -> the active Wi-Fi's name
    dnd-on / dnd-off       mako's D-Bus Modes property (`gdbus monitor`), with
                           a slow poll behind it
    idle-start / idle-end  a hypridle listener (IDLE_S of no input) that runs
                           `automations.py event idle-start|idle-end`
    presence-away / -back  presence.py (the webcam, opt-in, off as shipped) runs
                           `automations.py event presence-away|presence-back`
    time                   the clock, once a minute ("at" HH:MM, "days")
    work-start / work-end  workhours.py's state(), once a minute
    phone-connected / -disconnected   KDE Connect (phone.py), every PHONE_S
    context-enter / -leave project contexts (contexts.py runs `automations.py
                           event context-enter|context-leave NAME`; "name"
                           matches one project, left out: any)
    focus-start / -end     a focus block begins / ends (focus-guard.py runs
                           `automations.py event focus-start|focus-end`)

They fire on a CHANGE only: a game already running, a network already joined
when the daemon starts is the starting point, not an event. A time that
passed while the computer slept is not caught up.

Never a loop: a rule waits its cooldown before it can fire again; it cannot
be fired by what its own actions cause (the ECHO_S after they finish); and a
rule that fires more than STORM_MAX times in STORM_S anyway (two rules feeding
each other) is paused until `enable`, with a notification saying so. Actions
run one at a time in a worker thread, so a slow one never holds the events.

Actions (sibling scripts do the work; this only calls them):

    theme NAME          theme.py set NAME
    dnd on|off          notify-settings.py dnd on|off
    gamemode on|off     lua/gamemode.lua's set() through hyprctl eval
    sound-output DEV    sound-settings.py default: the first output whose name or
                        description contains DEV ("headphones", "HDMI")
    sound-profile "CARD PROFILE"   sound-settings.py profile CARD PROFILE
    nightlight on|off|auto         nightlight.sh
    notify TEXT         a notification
    shell CMD           sh -c CMD (2 min at most); AUTOMATION_RULE, _EVENT and
                        the event's details (AUTOMATION_CLASS, _SSID, ...) are
                        in its environment
    open APP            uwsm app -- APP (a .desktop id or a command), in a scope
                        of its own like any launched app
    session NAME        sessions.py restore NAME (workspace sessions)
    context NAME        contexts.py enter NAME (project contexts); "leave" leaves
    digest             notify-digest.py: what Do Not Disturb held back
    brief               brief.py auto --rule: the daily brief, once a day (its
                        morning settings say from when)
    journal             brief.py journal --notify: today's journal entry
    task NAME           tasks.py run NAME: a background task (its schedule
                        "on-event" means it waits for this; Settings >
                        Background tasks)
    focus N|off         focus-guard.py start N (a focus block of N minutes, 1-240;
                        "focus" alone: the usual length) or stop ("off")

Three rules are built in and ship on: "dnd-digest" (when Do Not Disturb
turns off, a digest of what arrived meanwhile -- notify-digest.py), switched
in Settings > Notifications; "daily-brief" (when you are back after being
away, the morning brief -- brief.py) and "end-of-day" (when work hours end,
the journal entry -- brief.py), switched in Settings > Daily brief & journal.
Built-in rules can be switched off, not deleted.
The daemon also marks the start of each Do Not Disturb stretch for the
digest (notify-digest.py mark), whatever the rules say.

What the daemon is doing -- each rule's last firing, the paused ones, what it
watches -- is in $XDG_RUNTIME_DIR/automations-state.json for `list` and the
Settings page (Settings > Automations). Log lines go to the journal:
journalctl --user -u automations.
"""
import collections
import datetime
import importlib.util
import json
import os
import queue
import re
import select
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
RULES = os.path.expanduser("~/.config/hypr/automations.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
CTL_SOCK = os.path.join(RUNTIME, "automations.sock")
STATE = os.path.join(RUNTIME, "automations-state.json")
WAYBAR = os.path.expanduser("~/.config/waybar/scripts")

COOLDOWN_S = 10         # a rule's default wait before it may fire again
ECHO_S = 3              # after its actions end, a rule ignores what they caused
STORM_MAX, STORM_S = 5, 120
RELEASE_S = 3           # the last game window closing: wait for the next one
RESCAN_S = 30           # Proton can set the class after mapping: no event for that
DND_POLL_S = 60         # behind mako's D-Bus signal, in case gdbus monitor misses one
PHONE_S = 60
IDLE_S = 300            # the hypridle listener's timeout (hypridle.conf)
SHELL_TIMEOUT = 120
MAX_ACTIONS = 6
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}$")
HM = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)$")
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_WORDS = {"every-day": "0123456", "everyday": "0123456", "daily": "0123456",
             "weekdays": "01234", "weekends": "56"}

# event -> ({option: kind}, words). Kinds: regex, text, hm, days.
EVENTS = {
    "app-open": ({"class": "regex"}, "{class} opens"),
    "app-close": ({"class": "regex"}, "the last {class} window closes"),
    "game-start": ({}, "a Steam game starts"),
    "game-end": ({}, "the Steam game ends"),
    "monitor-added": ({"name": "text"}, "a screen{name? matching} is connected"),
    "monitor-removed": ({"name": "text"}, "a screen{name? matching} is disconnected"),
    "audio-output": ({"device": "text"}, "the sound output changes{device? to}"),
    "wifi-connected": ({"ssid": "text"}, "Wi-Fi connects{ssid? to}"),
    "wifi-disconnected": ({"ssid": "text"}, "Wi-Fi disconnects{ssid? from}"),
    "dnd-on": ({}, "Do Not Disturb turns on"),
    "dnd-off": ({}, "Do Not Disturb turns off"),
    "idle-start": ({}, f"you have been away {IDLE_S // 60} min"),
    "idle-end": ({}, "you are back after being away"),
    "presence-away": ({}, "the camera sees you leave the desk"),
    "presence-back": ({}, "the camera sees you back at the desk"),
    "time": ({"at": "hm", "days": "days"}, "it is {at}{days? on}"),
    "work-start": ({}, "work hours begin"),
    "work-end": ({}, "work hours end"),
    "phone-connected": ({}, "the phone is reachable"),
    "phone-disconnected": ({}, "the phone goes out of reach"),
    "context-enter": ({"name": "text"}, "you switch into a project{name? called}"),
    "context-leave": ({"name": "text"}, "you leave a project{name? called}"),
    "focus-start": ({}, "a focus block begins"),
    "focus-end": ({}, "a focus block ends"),
}
REQUIRED = {"app-open": ("class",), "app-close": ("class",), "time": ("at",)}
# The events that only arrive as `automations.py event NAME` (no options).
POKED = ("idle-start", "idle-end", "presence-away", "presence-back", "focus-start", "focus-end")

# action -> (value kind, words). Kinds: None (no value), on-off, on-off-auto, text, two, theme, name.
ACTIONS = {
    "theme": ("theme", "switch the theme to {value}"),
    "dnd": ("on-off", "turn Do Not Disturb {value}"),
    "gamemode": ("on-off", "turn gamemode {value}"),
    "sound-output": ("text", "play sound through {value}"),
    "sound-profile": ("two", "set the sound profile {value}"),
    "nightlight": ("on-off-auto", "night light {value}"),
    "notify": ("text", "notify “{value}”"),
    "shell": ("text", "run `{value}`"),
    "open": ("text", "open {value}"),
    "session": ("name", "restore the workspace session “{value}”"),
    "context": ("name", "project context: {value}"),
    "digest": (None, "show a digest of the notifications Do Not Disturb held back"),
    "brief": (None, "show the daily brief (once a day)"),
    "journal": (None, "write today's journal entry"),
    "task": ("name", "run the background task “{value}”"),
    "focus": ("text", "focus block: {value} (minutes, or off)"),
}
FOCUS_VALUE = re.compile(r"(?:focus\s*)?(\d{1,3})?\s*(?:m|min|mins|minutes|minutos)?$|off|stop|end", re.I)

BUILTIN = [
    {"id": "dnd-digest", "name": "Digest after Do Not Disturb", "enabled": True, "builtin": True,
     "when": {"event": "dnd-off"}, "do": [{"action": "digest"}]},
    {"id": "daily-brief", "name": "Morning brief", "enabled": True, "builtin": True,
     "when": {"event": "idle-end"}, "do": [{"action": "brief"}]},
    {"id": "end-of-day", "name": "End-of-day journal", "enabled": True, "builtin": True,
     "when": {"event": "work-end"}, "do": [{"action": "journal"}]},
]

DOC = [
    "Automations: when an event happens, run actions. automations.py's docstring has everything;",
    "`automations.py catalog` lists the events and actions, `automations.py check` validates this file.",
    "A rule: {id, name, enabled, when: {event, ...options}, do: [{action, value}], cooldown (s, default 10)}.",
    "Keys starting with _ are ignored. Settings > Automations edits this file too.",
]


def doc_lines():
    """The "_doc" at the top of automations.json: DOC, and what can go in a rule."""
    events = ", ".join(e + (f" ({', '.join(o)})" if o else "") for e, (o, _) in EVENTS.items())
    actions = ", ".join(a + {None: "", "on-off": " on|off", "on-off-auto": " on|off|auto", "two": " \"CARD PROFILE\"",
                             "theme": " NAME", "name": " NAME"}.get(kind, " TEXT")
                        for a, (kind, _) in ACTIONS.items())
    return DOC + [f"Events (options): {events}.", f"Actions (value): {actions}."]


def log(text):
    print(f"automations: {text}", flush=True)


def _module(name, filename, folder=HERE):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(folder, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def run(*cmd, timeout=10, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# -- the rules: checking -----------------------------------------------------
def parse_days(text):
    """"mon,wed" / "weekdays" / "every-day" -> "02" style digit string (0 = Monday);
    ValueError for a word that is not a day."""
    text = str(text).strip().lower()
    if text in DAY_WORDS:
        return DAY_WORDS[text]
    out = set()
    for word in re.split(r"[\s,]+", text):
        if not word:
            continue
        if word[:3] not in DAY_NAMES:
            raise ValueError(f"{word!r} is not a day")
        out.add(str(DAY_NAMES.index(word[:3])))
    if not out:
        raise ValueError("no days")
    return "".join(sorted(out))


def days_text(digits):
    for word, value in (("every day", "0123456"), ("weekdays", "01234"), ("weekends", "56")):
        if digits == value:
            return word
    return ", ".join(DAY_NAMES[int(d)].capitalize() for d in digits)


def check_option(kind, value):
    """The option's value, tidied; ValueError says why not."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be non-empty text")
    value = value.strip()
    if len(value) > 120:
        raise ValueError("is longer than 120 characters")
    if kind == "regex":
        try:
            re.compile(value)
        except re.error as err:
            raise ValueError(f"is not a valid pattern ({err})") from None
    elif kind == "hm":
        m = HM.match(value)
        if not m:
            raise ValueError("must be HH:MM (24 h)")
        value = f"{int(m.group(1)):02d}:{m.group(2)}"
    elif kind == "days":
        value = ",".join(DAY_NAMES[int(d)] for d in parse_days(value))
    return value


def check_value(kind, value):
    """An action's value, tidied; ValueError says why not."""
    if kind is None:
        if value not in (None, ""):
            raise ValueError("takes no value")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("needs a value")
    value = value.strip()
    if kind in ("on-off", "on-off-auto"):
        allowed = ("on", "off") + (("auto",) if kind == "on-off-auto" else ())
        if value.lower() not in allowed:
            raise ValueError(f"is {' or '.join(allowed)}")
        return value.lower()
    if kind == "two":
        if len(value.split()) != 2:
            raise ValueError("is \"CARD PROFILE\" (sound-settings.py status names them)")
    elif kind == "name":
        if not re.fullmatch(r"[\w .-]{1,64}", value):
            raise ValueError("is a session name (letters, digits, space . _ -)")
    elif kind == "theme":
        names = theme_names()
        if names and value not in names:
            raise ValueError(f"is one of the themes: {', '.join(names)}")
    if len(value) > 500:
        raise ValueError("is longer than 500 characters")
    return value


def theme_names():
    try:
        return [n for n, _ in _module("theme", "theme.py").themes()]
    except Exception:       # theme.py broken must not break the rules
        return []


def validate(rule):
    """(tidied rule, []) or (None, [problems]). Strict: unknown keys, events,
    actions and options are problems, not ignored."""
    problems = []
    if not isinstance(rule, dict):
        return None, ["a rule is a JSON object"]
    out = {}
    allowed = {"id", "name", "enabled", "when", "do", "cooldown", "builtin"}
    for key in rule:
        if key not in allowed and not key.startswith("_"):
            problems.append(f"unknown key {key!r}")
    rid = rule.get("id")
    if rid is not None and (not isinstance(rid, str) or not ID.match(rid)):
        problems.append("id is lowercase letters, digits and dashes (up to 48)")
    out["id"] = rid
    name = rule.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        problems.append("name is plain text, 1 to 80 characters")
    else:
        out["name"] = name.strip()
    enabled = rule.get("enabled", True)
    if not isinstance(enabled, bool):
        problems.append("enabled is true or false")
    out["enabled"] = enabled is True
    if rule.get("builtin"):
        out["builtin"] = True
    cooldown = rule.get("cooldown", COOLDOWN_S)
    if not isinstance(cooldown, int) or isinstance(cooldown, bool) or not 0 <= cooldown <= 86400:
        problems.append("cooldown is whole seconds, 0 to 86400")
    elif cooldown != COOLDOWN_S:
        out["cooldown"] = cooldown

    when = rule.get("when")
    if not isinstance(when, dict) or when.get("event") not in EVENTS:
        problems.append(f"when.event is one of: {', '.join(EVENTS)}")
    else:
        event = when["event"]
        options, _ = EVENTS[event]
        tidy = {"event": event}
        for key, value in when.items():
            if key == "event" or key.startswith("_"):
                continue
            if key not in options:
                problems.append(f"{event} has no option {key!r}" +
                                (f" (it takes {', '.join(options)})" if options else " (it takes none)"))
                continue
            try:
                tidy[key] = check_option(options[key], value)
            except ValueError as err:
                problems.append(f"when.{key} {err}")
        for key in REQUIRED.get(event, ()):
            if key not in when:
                problems.append(f"{event} needs when.{key}")
        out["when"] = tidy

    do = rule.get("do")
    if not isinstance(do, list) or not 1 <= len(do) <= MAX_ACTIONS:
        problems.append(f"do is a list of 1 to {MAX_ACTIONS} actions")
    else:
        out["do"] = []
        for n, act in enumerate(do, 1):
            if not isinstance(act, dict) or act.get("action") not in ACTIONS:
                problems.append(f"do #{n}: action is one of: {', '.join(ACTIONS)}")
                continue
            extra = set(act) - {"action", "value"}
            if any(not k.startswith("_") for k in extra):
                problems.append(f"do #{n}: only action and value")
                continue
            try:
                value = check_value(ACTIONS[act["action"]][0], act.get("value"))
                if act["action"] == "focus" and action_argv({"action": "focus", "value": value})[0] is None:
                    raise ValueError("is minutes (1-240) or off")
            except ValueError as err:
                problems.append(f"do #{n} ({act['action']}): the value {err}")
                continue
            out["do"].append({"action": act["action"]} | ({"value": value} if value is not None else {}))
    return (None, problems) if problems else (out, [])


# -- the rules: the file ------------------------------------------------------
def slug(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "rule"
    rid, n = base, 2
    while rid in taken:
        rid, n = f"{base}-{n}", n + 1
    return rid


def read_file(path=None):
    """The file's raw rules list ([] when missing), or ValueError when it is
    not JSON at all."""
    path = path or RULES
    try:
        with open(path) as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except OSError as err:
        raise ValueError(str(err)) from None
    except ValueError as err:
        raise ValueError(f"{path} is not valid JSON: {err}") from None
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise ValueError(f"{path} has no \"rules\" list")
    return rules


def load(path=None):
    """(good rules, [(id or #n, problems)]). The built-in rules are always
    there: one missing from the file comes back as it ships."""
    try:
        raw = read_file(path)
    except ValueError as err:
        return [dict(r) for r in BUILTIN], [("file", [str(err)])]
    good, bad, seen = [], [], set()
    for n, rule in enumerate(raw, 1):
        tidy, problems = validate(rule)
        label = (rule.get("id") or rule.get("name") or f"#{n}") if isinstance(rule, dict) else f"#{n}"
        if tidy and (not tidy["id"] or tidy["id"] in seen):
            problems = ["id is missing or used twice"]
        if problems:
            bad.append((label, problems))
            continue
        seen.add(tidy["id"])
        good.append(tidy)
    good[0:0] = [dict(b) for b in BUILTIN if b["id"] not in seen]     # in BUILTIN's order
    return good, bad


def save(rules, path=None):
    """Write the rules back (atomically), keeping any "_" notes at the top."""
    path = path or RULES
    try:
        with open(path) as handle:
            old = json.load(handle)
        notes = {k: v for k, v in old.items() if k.startswith("_")} if isinstance(old, dict) else {}
    except (OSError, ValueError):
        notes = {}
    notes["_doc"] = doc_lines()       # ours: rewritten on every save, your own "_" notes kept
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump({**notes, "rules": rules}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)
    poke("reload")


def ensure_file(path=None):
    """First run: the file with the built-in rules, so there is something to read and edit."""
    path = path or RULES
    if not os.path.exists(path):
        save([dict(b) for b in BUILTIN], path)


def find(rules, word):
    word = word.strip().lower()
    return next((r for r in rules if r["id"] == word), None) or \
        next((r for r in rules if r.get("name", "").lower() == word), None)


# -- the rules: in words ------------------------------------------------------
def describe_when(when):
    _, words = EVENTS[when["event"]]

    def fill(m):
        key, joiner = m.group(1), m.group(2)
        value = when.get(key)
        if key == "days":
            value = days_text(parse_days(value)) if value else ""
        if joiner is None:
            return str(value or "\u2026")
        return f" {joiner} {value}" if value else ""
    return re.sub(r"\{(\w+)(?:\? (\w+))?\}", fill, words)


def describe_action(act):
    _, words = ACTIONS[act["action"]]
    return words.replace("{value}", str(act.get("value", "")))


def describe(rule):
    """"When Do Not Disturb turns off: show a digest of ..." """
    text = describe_when(rule["when"])
    return f"When {text}: " + ", then ".join(describe_action(a) for a in rule["do"])


# -- doing --------------------------------------------------------------------
def scope(argv):
    """`argv` in a systemd scope of its own (as launcher.py starts apps), so a
    restart of this service does not take an app it opened along."""
    return ["uwsm", "app", "--"] + argv if os.path.exists("/usr/bin/uwsm") else \
        ["systemd-run", "--user", "--scope", "--quiet", "--"] + argv


def unit(argv):
    """`argv` as a transient service: it outlives this daemon and does not
    hold the worker (the digest waits on its notification)."""
    return ["systemd-run", "--user", "--quiet", "--collect", "--"] + argv


def sink_matching(word):
    """The first output (pactl sink name) whose name or description has `word` in it."""
    try:
        sinks = json.loads(run("pactl", "-f", "json", "list", "sinks") or "[]")
    except ValueError:
        sinks = []
    word = word.lower()
    for s in sinks:
        if word in s.get("name", "").lower() or word in s.get("description", "").lower():
            return s["name"]
    return None


def action_argv(act):
    """(argv, how): how is "wait" (run, wait up to the timeout), "detach"
    (start and move on); argv None with how = why it cannot run."""
    name, value = act["action"], act.get("value", "")
    if name == "theme":
        return [sys.executable, os.path.join(HERE, "theme.py"), "set", value], "wait"
    if name == "dnd":
        return [sys.executable, os.path.join(HERE, "notify-settings.py"), "dnd", value], "wait"
    if name == "gamemode":
        why = "automation"
        return ["hyprctl", "eval", f'require("lua.gamemode").set({"true" if value == "on" else "false"}, "{why}")'], "wait"
    if name == "sound-output":
        sink = sink_matching(value)
        if not sink:
            return None, f"no sound output matches {value!r}"
        return [sys.executable, os.path.join(HERE, "sound-settings.py"), "default", sink], "wait"
    if name == "sound-profile":
        card, profile = value.split()
        return [sys.executable, os.path.join(HERE, "sound-settings.py"), "profile", card, profile], "wait"
    if name == "nightlight":
        return [os.path.join(HERE, "nightlight.sh"), value], "wait"
    if name == "notify":
        return [NOTIFY, "-a", "Automations", "-i", "system-run-symbolic", "Automation", value], "wait"
    if name == "shell":
        return ["sh", "-c", value], "wait"
    if name == "open":
        try:
            return scope(shlex.split(value)), "detach"
        except ValueError as err:
            return None, f"cannot read {value!r}: {err}"
    if name == "session":
        path = os.path.join(HERE, "sessions.py")
        if not os.path.exists(path):
            return None, "sessions.py is not there (workspace sessions)"
        return unit([sys.executable, path, "restore", value]), "wait"
    if name == "context":
        path = os.path.join(HERE, "contexts.py")
        if not os.path.exists(path):
            return None, "contexts.py is not there (project contexts)"
        verb = ["leave"] if value.lower() == "leave" else ["enter", value]
        return unit([sys.executable, path] + verb), "wait"
    if name == "digest":
        return unit([sys.executable, os.path.join(HERE, "notify-digest.py")]), "wait"
    if name == "focus":
        path = os.path.join(HERE, "focus-guard.py")
        if not os.path.exists(path):
            return None, "focus-guard.py is not there (focus guard)"
        m = FOCUS_VALUE.fullmatch((value or "").strip())
        if not m:
            return None, f"focus takes minutes (1-240) or off, not {value!r}"
        if m.group(0).lower() in ("off", "stop", "end"):
            return [sys.executable, path, "stop"], "wait"
        minutes = m.group(1)
        if minutes and not 1 <= int(minutes) <= 240:
            return None, "focus minutes go from 1 to 240"
        return [sys.executable, path, "start"] + ([minutes] if minutes else []), "wait"
    if name == "task":
        path = os.path.join(HERE, "tasks.py")
        if not os.path.exists(path):
            return None, "tasks.py is not there (background tasks)"
        return [sys.executable, path, "run", value], "wait"
    if name in ("brief", "journal"):
        # Transient units: the brief may wait for an unlock, the journal for
        # the local model -- longer than SHELL_TIMEOUT, and not the worker's.
        path = os.path.join(HERE, "brief.py")
        if not os.path.exists(path):
            return None, "brief.py is not there (daily brief & journal)"
        return unit([sys.executable, path] + (["auto", "--rule"] if name == "brief" else
                                              ["journal", "--notify"])), "wait"
    return None, f"no action {name!r}"


def facts_env(rule, event, facts):
    env = dict(os.environ, AUTOMATION_RULE=rule["id"], AUTOMATION_EVENT=event)
    for key, value in facts.items():
        if isinstance(value, (str, int)):
            env[f"AUTOMATION_{key.upper()}"] = str(value)
    return env


def do_actions(rule, event="test", facts=None):
    """Run the rule's actions in order; a failing one is logged and the
    rest still run. Returns the problems ([] when all went)."""
    problems = []
    env = facts_env(rule, event, facts or {})
    for act in rule["do"]:
        argv, how = action_argv(act)
        if argv is None:
            problems.append(f"{act['action']}: {how}")
            continue
        try:
            if how == "detach":
                subprocess.Popen(argv, env=env, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                continue
            done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=SHELL_TIMEOUT)
            if done.returncode != 0:
                tail = (done.stderr or done.stdout).strip().splitlines()
                problems.append(f"{act['action']}: exit {done.returncode}" + (f" ({tail[-1][:160]})" if tail else ""))
        except subprocess.TimeoutExpired:
            problems.append(f"{act['action']}: still running after {SHELL_TIMEOUT} s, stopped")
        except OSError as err:
            problems.append(f"{act['action']}: {err}")
    return problems


# -- deciding -----------------------------------------------------------------
def matches(rule, event, facts):
    """Does `event` with `facts` fire `rule`? (Its options; enabled-ness and
    the loop guards are the Engine's.)"""
    when = rule["when"]
    if when["event"] != event:
        return False
    if event in ("app-open", "app-close"):
        pattern = when["class"]

        def hit(cls):
            try:
                return bool(re.fullmatch(pattern, cls or "", re.I))
            except re.error:
                return False
        # An app, not a window: only the first one in / the last one out.
        return hit(facts.get("class")) and not any(hit(c) for c in facts.get("others", ()))
    if event in ("monitor-added", "monitor-removed"):
        word = when.get("name", "").lower()
        return not word or word in facts.get("name", "").lower() or word in facts.get("description", "").lower()
    if event == "audio-output":
        word = when.get("device", "").lower()
        return not word or word in facts.get("name", "").lower() or word in facts.get("description", "").lower()
    if event in ("wifi-connected", "wifi-disconnected"):
        return not when.get("ssid") or when["ssid"].casefold() == facts.get("ssid", "").casefold()
    if event in ("context-enter", "context-leave"):
        return not when.get("name") or when["name"].casefold() == facts.get("name", "").casefold()
    if event == "time":
        if facts.get("at") != when["at"]:
            return False
        return not when.get("days") or str(facts.get("weekday")) in parse_days(when["days"])
    return True


class Engine:
    """Which rules an event fires, with the loop guards (see the top). The
    clock and the runner are passed in, so the tests can drive it."""

    def __init__(self, rules, runner, clock=time.monotonic):
        self.rules = rules
        self.runner = runner        # runner(rule, event, facts): queue its actions
        self.clock = clock
        self.last = {}              # id -> when it last fired (clock)
        self.recent = collections.defaultdict(collections.deque)
        self.paused = {}            # id -> why
        self.echo_until = {}        # id -> its own actions' echo ends (inf while they run)
        self.fired_at = {}          # id -> epoch, for `list`

    def set_rules(self, rules):
        self.rules = rules

    def needs(self):
        return {r["when"]["event"] for r in self.rules if r["enabled"]}

    def emit(self, event, **facts):
        fired = []
        now = self.clock()
        for rule in self.rules:
            rid = rule["id"]
            if not rule["enabled"] or rid in self.paused or not matches(rule, event, facts):
                continue
            if now < self.echo_until.get(rid, 0):
                log(f"{rid}: not fired by its own actions ({event})")
                continue
            if now < self.last.get(rid, -1e18) + rule.get("cooldown", COOLDOWN_S):
                continue
            stamps = self.recent[rid]
            while stamps and stamps[0] < now - STORM_S:
                stamps.popleft()
            if len(stamps) >= STORM_MAX:
                self.paused[rid] = f"fired {STORM_MAX} times in {STORM_S // 60} min"
                log(f"{rid}: paused, {self.paused[rid]} (a loop?): `automations.py enable {rid}` resumes it")
                notify("Automation paused",
                       f"“{rule['name']}” fired {STORM_MAX} times in {STORM_S // 60} minutes, "
                       "which looks like a loop. Settings > Automations turns it back on.")
                continue
            stamps.append(now)
            self.last[rid] = now
            self.echo_until[rid] = float("inf")
            self.fired_at[rid] = time.time()
            fired.append(rid)
            shown = {k: v for k, v in facts.items() if k != "others"}
            log(f"{rid}: {event}{(' ' + json.dumps(shown, default=str)) if shown else ''} -> "
                + ", ".join(describe_action(a) for a in rule["do"]))
            self.runner(rule, event, facts)
        return fired

    def finished(self, rid):
        """The worker is done with `rid`'s actions: its echo window starts."""
        self.echo_until[rid] = self.clock() + ECHO_S

    def resume(self, rid):
        self.paused.pop(rid, None)
        self.recent.pop(rid, None)


def notify(summary, body):
    run(NOTIFY, "-a", "Automations", "-i", "system-run-symbolic", summary, body, timeout=5)


# -- watching: Hyprland ---------------------------------------------------------
def hypr_socket():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.path.join(RUNTIME, "hypr")
    if not sig:
        try:
            sig = sorted(os.listdir(base), key=lambda d: os.path.getmtime(os.path.join(base, d)))[-1]
        except (OSError, IndexError):
            return None
    return os.path.join(base, sig, ".socket2.sock")


def clients():
    """{address without 0x: class} of the open windows."""
    try:
        data = json.loads(run("hyprctl", "clients", "-j", timeout=3) or "[]")
    except ValueError:
        return {}
    return {c.get("address", "").removeprefix("0x"): c.get("class", "") for c in data}


def monitors():
    try:
        data = json.loads(run("hyprctl", "monitors", "all", "-j", timeout=3) or "[]")
    except ValueError:
        return {}
    return {m.get("name", ""): m.get("description", "") for m in data}


def is_game(cls):
    return (cls or "").startswith("steam_app_")


class Windows:
    """The open windows' classes, kept from the event socket, and the game
    windows among them."""

    def __init__(self, engine, known=None):
        self.engine = engine
        self.classes = dict(known or {})
        self.screens = {}
        self.game = any(is_game(c) for c in self.classes.values())
        self.game_release = None     # when to say the game ended (clock)

    def others(self, addr):
        return [c for a, c in self.classes.items() if a != addr]

    def event(self, line, clock=time.monotonic):
        name, _, data = line.partition(">>")
        if name == "openwindow":
            addr, _ws, cls, *_ = (data.split(",", 3) + ["", "", ""])[:4]
            self.engine.emit("app-open", **{"class": cls, "others": self.others(addr)})
            self.classes[addr] = cls
            self.games_changed(clock)
        elif name == "closewindow":
            cls = self.classes.pop(data, None)
            if cls is not None:
                self.engine.emit("app-close", **{"class": cls, "others": list(self.classes.values())})
            self.games_changed(clock)
        elif name == "monitoradded":
            self.screens = monitors()
            self.engine.emit("monitor-added", name=data, description=self.screens.get(data, ""))
        elif name == "monitorremoved":
            self.engine.emit("monitor-removed", name=data, description=self.screens.pop(data, ""))

    def rescan(self, clock=time.monotonic):
        """The windows again (a Proton game's class set after mapping)."""
        fresh = clients()
        if fresh or not self.classes:
            self.classes = fresh
        self.games_changed(clock)

    def games_changed(self, clock=time.monotonic):
        now_game = any(is_game(c) for c in self.classes.values())
        if now_game:
            self.game_release = None
            if not self.game:
                self.game = True
                appid = next(c for c in self.classes.values() if is_game(c)).removeprefix("steam_app_")
                self.engine.emit("game-start", appid=appid)
        elif self.game and self.game_release is None:
            self.game_release = clock() + RELEASE_S

    def tick(self, clock=time.monotonic):
        if self.game_release is not None and clock() >= self.game_release:
            self.game_release = None
            if not any(is_game(c) for c in self.classes.values()):
                self.game = False
                self.engine.emit("game-end")


# -- watching: the rest -----------------------------------------------------------
def dnd_now():
    return "do-not-disturb" in run("makoctl", "mode", timeout=3).split()


def wifi_now():
    """The active Wi-Fi connection's name ("" for none)."""
    for line in run("nmcli", "-t", "-f", "TYPE,NAME", "connection", "show", "--active", timeout=5).splitlines():
        kind, _, name = line.partition(":")
        if kind == "802-11-wireless":
            return name.replace("\\:", ":")
    return ""


def sink_now():
    name = run("pactl", "get-default-sink", timeout=3).strip()
    desc = ""
    try:
        for s in json.loads(run("pactl", "-f", "json", "list", "sinks", timeout=5) or "[]"):
            if s.get("name") == name:
                desc = s.get("description", "")
    except ValueError:
        pass
    return name, desc


def phone_now():
    try:
        p = _module("phone", "phone.py").phone()
    except Exception:       # no KDE Connect is no phone
        p = None
    return p["name"] if p else ""


def working_now(now=None):
    try:
        return bool(_module("workhours", "workhours.py").state(now)[0])
    except Exception:
        return False


def digest_mark(fresh=True):
    """The start of a Do Not Disturb stretch, for notify-digest.py (fresh=False:
    keep a mark already there -- this daemon restarted mid-stretch)."""
    try:
        _module("notify_digest", "notify-digest.py").mark(fresh)
    except Exception as err:     # the digest is extra; never the daemon's end
        log(f"digest mark failed: {err}")


class Stream:
    """A long-running line-printing command (gdbus monitor, nmcli monitor,
    pactl subscribe) whose lines say "look again"; restarted when it dies."""

    def __init__(self, name, argv):
        self.name, self.argv = name, argv
        self.proc, self.buf, self.retry_at = None, b"", 0.0

    def start(self):
        if self.proc or time.monotonic() < self.retry_at:
            return
        try:
            self.proc = subprocess.Popen(self.argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL)
            os.set_blocking(self.proc.stdout.fileno(), False)
        except OSError as err:
            log(f"{self.name}: cannot start ({err})")
            self.proc, self.retry_at = None, time.monotonic() + 60

    def stop(self):
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            self.proc = None

    def fileno(self):
        return self.proc.stdout.fileno()

    def read(self):
        """The new lines; [] and a restart later when the command ended."""
        try:
            chunk = os.read(self.fileno(), 65536)
        except BlockingIOError:
            return []
        if not chunk:
            self.stop()
            self.retry_at = time.monotonic() + 5
            return []
        self.buf += chunk
        *lines, self.buf = self.buf.split(b"\n")
        return [l.decode("utf-8", "replace") for l in lines]


class Daemon:
    """The event loop: Hyprland's socket, the control socket, the streams
    the rules need, and the minute / poll timers."""

    def __init__(self):
        self.jobs = queue.Queue()
        self.engine = Engine([], self.queue_job)
        self.bad = []
        self.mtime = None
        self.windows = None
        self.state = {"dnd": None, "wifi": None, "sink": None, "phone": None, "work": None}
        self.streams = {
            "dnd": Stream("mako", ["gdbus", "monitor", "--session", "--dest", "org.freedesktop.Notifications",
                                   "--object-path", "/fr/emersion/Mako"]),
            "wifi": Stream("nmcli", ["nmcli", "monitor"]),
            "sink": Stream("pactl", ["pactl", "subscribe"]),
        }
        self.pending = {}           # stream key -> when to look again (debounce)
        self.next_poll = {}
        self.minute = None
        self.hypr = None
        self.hypr_buf = b""
        threading.Thread(target=self.worker, daemon=True).start()

    # -- the rules
    def reload(self, force=False):
        try:
            mtime = os.path.getmtime(RULES)
        except OSError:
            mtime = None
        if mtime == self.mtime and not force:
            return
        self.mtime = mtime
        rules, self.bad = load()
        self.engine.set_rules(rules)
        for label, problems in self.bad:
            log(f"rule {label} skipped: {'; '.join(problems)}")
        log(f"{sum(r['enabled'] for r in rules)} of {len(rules)} rules on; watching: "
            + (", ".join(sorted(self.engine.needs())) or "nothing"))
        self.write_state()

    def needs(self, *events):
        return bool(self.engine.needs() & set(events))

    # -- the worker
    def queue_job(self, rule, event, facts):
        self.jobs.put((rule, event, facts))
        self.write_state()

    def worker(self):
        while True:
            rule, event, facts = self.jobs.get()
            try:
                problems = do_actions(rule, event, facts)
            except Exception as err:     # one bad action must not end the worker
                problems = [str(err)]
            for p in problems:
                log(f"{rule['id']}: {p}")
            self.engine.finished(rule["id"])

    def write_state(self):
        state = {"pid": os.getpid(), "fired": self.engine.fired_at, "paused": self.engine.paused,
                 "watching": sorted(self.engine.needs()),
                 "broken": [{"rule": l, "problems": p} for l, p in self.bad]}
        try:
            tmp = STATE + ".tmp"
            with open(tmp, "w") as handle:
                json.dump(state, handle)
            os.replace(tmp, STATE)
        except OSError:
            pass

    # -- the facts that are not events
    def look(self, key, first=False):
        """Read one fact again; a change is an event (not on the first read)."""
        if key == "dnd":
            value = dnd_now()
        elif key == "wifi":
            value = wifi_now()
        elif key == "sink":
            value = sink_now()
        elif key == "phone":
            value = phone_now()
        else:
            value = working_now()
        old, self.state[key] = self.state[key], value
        if first or old is None or old == value:
            if key == "dnd" and value and first:
                digest_mark(fresh=False)    # started in DND: from the mark, or from now
            return
        if key == "dnd":
            if value:
                digest_mark()
            self.engine.emit("dnd-on" if value else "dnd-off")
        elif key == "wifi":
            if old:
                self.engine.emit("wifi-disconnected", ssid=old)
            if value:
                self.engine.emit("wifi-connected", ssid=value)
        elif key == "sink":
            self.engine.emit("audio-output", name=value[0], description=value[1])
        elif key == "phone":
            self.engine.emit("phone-connected" if value else "phone-disconnected", name=value or old)
        elif key == "work":
            self.engine.emit("work-start" if value else "work-end")

    def sync_sources(self):
        """Start what the rules now need, stop what they no longer do."""
        wanted = {"dnd": True,      # always: the digest's mark (see the top)
                  "wifi": self.needs("wifi-connected", "wifi-disconnected"),
                  "sink": self.needs("audio-output")}
        for key, stream in self.streams.items():
            if wanted[key]:
                if self.state[key] is None:
                    self.look(key, first=True)
                stream.start()
            else:
                stream.stop()
                self.state[key] = None
        for key, events in (("phone", ("phone-connected", "phone-disconnected")),
                            ("work", ("work-start", "work-end"))):
            if self.needs(*events) and self.state[key] is None:
                self.look(key, first=True)
            elif not self.needs(*events):
                self.state[key] = None

    def stream_line(self, key, line):
        if key == "dnd" and "Modes" not in line:
            return              # a notification coming or going, not a mode
        if key == "sink" and "on server" not in line:
            return              # streams and devices; the default is a server change
        self.pending.setdefault(key, time.monotonic() + (0.3 if key == "dnd" else 1.5))

    # -- the clock
    def tick(self):
        now = time.monotonic()
        for key, at in list(self.pending.items()):
            if now >= at:
                del self.pending[key]
                self.look(key)
        if self.windows:
            self.windows.tick()
        for key, every in (("dnd", DND_POLL_S), ("phone", PHONE_S), ("rescan", RESCAN_S)):
            if now < self.next_poll.get(key, 0):
                continue
            self.next_poll[key] = now + every
            if key == "phone" and self.state["phone"] is not None:
                self.look("phone")
            elif key == "dnd" and self.state["dnd"] is not None:
                self.look("dnd")
            elif key == "rescan" and self.windows and self.needs("game-start", "game-end"):
                self.windows.rescan()
        wall = datetime.datetime.now()
        stamp = wall.strftime("%Y-%m-%d %H:%M")
        if stamp != self.minute:
            first, self.minute = self.minute is None, stamp
            if not first:
                self.engine.emit("time", at=wall.strftime("%H:%M"), weekday=wall.weekday())
            if self.state["work"] is not None:
                self.look("work")

    def wait(self):
        """Seconds to the next timed thing."""
        now = time.monotonic()
        times = [now + 15]          # the file's mtime, at least this often
        times += self.pending.values()
        times += [t for k, t in self.next_poll.items()]
        if self.windows and self.windows.game_release:
            times.append(self.windows.game_release)
        if self.needs("time", "work-start", "work-end"):
            wall = datetime.datetime.now()
            times.append(now + 60 - wall.second - wall.microsecond / 1e6 + 0.05)
        return max(0.0, min(times) - now)

    # -- the sockets
    def connect_hypr(self):
        path = hypr_socket()
        if not path:
            return
        import hyprbus      # the shared relay (only what Windows.event reads), or socket2 directly
        try:
            sock = hyprbus.connect({"openwindow", "closewindow", "monitoradded", "monitorremoved"},
                                   direct=path)
        except OSError:
            return
        self.hypr, self.hypr_buf = sock, b""
        log(f"following Hyprland's events ({os.path.basename(os.path.dirname(path))[:12]}…)")
        self.windows = Windows(self.engine, clients())
        self.windows.screens = monitors()

    def read_hypr(self):
        chunk = self.hypr.recv(65536)
        if not chunk:
            self.hypr.close()
            self.hypr = None        # Hyprland restarted: reconnect
            return
        self.hypr_buf += chunk
        *lines, self.hypr_buf = self.hypr_buf.split(b"\n")
        for line in lines:
            self.windows.event(line.decode("utf-8", "replace"))

    def control(self, msg):
        word, _, arg = msg.partition(" ")
        if word == "reload":
            self.reload(force=True)
            self.sync_sources()
        elif word == "resume":
            self.engine.resume(arg)
            self.write_state()
        elif word == "event" and arg in POKED:
            self.engine.emit(arg)
        elif word == "event" and arg.split(" ", 1)[0] in ("context-enter", "context-leave"):
            event, _, name = arg.partition(" ")
            self.engine.emit(event, name=name)

    def main(self):
        ensure_file()
        try:
            os.unlink(CTL_SOCK)
        except OSError:
            pass
        ctl = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        ctl.bind(CTL_SOCK)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        self.reload(force=True)
        self.sync_sources()
        self.tick()
        while True:
            if self.hypr is None:
                self.connect_hypr()
            fds = [ctl] + ([self.hypr] if self.hypr else [])
            live = {s.fileno(): k for k, s in self.streams.items() if s.proc}
            ready, _, _ = select.select(fds + list(live), [], [], self.wait() if self.hypr else min(2, self.wait()))
            for r in ready:
                if r is ctl:
                    self.control(ctl.recv(4096).decode("utf-8", "replace"))
                elif r is self.hypr:
                    self.read_hypr()
                elif r in live:
                    key = live[r]
                    for line in self.streams[key].read():
                        self.stream_line(key, line)
            self.reload()
            self.sync_sources()
            self.tick()


def poke(msg):
    """A word to the running daemon (reload, resume ID, event NAME); nothing
    when it is not running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(msg.encode(), CTL_SOCK)
        return True
    except OSError:
        return False


def daemon_state():
    try:
        with open(STATE) as handle:
            data = json.load(handle)
        os.kill(data.get("pid", 0), 0)
        return data
    except (OSError, ValueError, TypeError):
        return {}


# -- plain words -> a rule (the local "quick" model) ----------------------------------
SYSTEM = ("You turn a sentence about desktop automation into ONE rule, as JSON. Use only the events, "
          "options and actions listed; never invent others. If the sentence asks for something the list "
          "cannot do, answer {\"error\": \"why\"}.")
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "when": {"type": "object"},
        "do": {"type": "array", "items": {"type": "object"}},
        "error": {"type": "string"},
    },
}


def catalog():
    """The events and actions with their options, for the model and Settings."""
    return {
        "events": [{"event": e, "options": list(opts), "required": list(REQUIRED.get(e, ())),
                    "words": describe_when({"event": e})} for e, (opts, _) in EVENTS.items()],
        "actions": [{"action": a, "value": kind, "words": words.replace("{value}", "…")}
                    for a, (kind, words) in ACTIONS.items()],
        "themes": theme_names(),
    }


def model_prompt(text):
    cat = catalog()
    events = "\n".join(f"  {e['event']}" + (f" (options: {', '.join(e['options'])}"
                                           + (f"; required: {', '.join(e['required'])}" if e["required"] else "")
                                           + ")" if e["options"] else "") + f": {e['words']}"
                       for e in cat["events"])
    kinds = {"on-off": "on|off", "on-off-auto": "on|off|auto", "text": "text", "two": "\"CARD PROFILE\"",
             "theme": "|".join(cat["themes"]) or "a theme name", "name": "a session name", None: "no value"}
    actions = "\n".join(f"  {a['action']} (value: {kinds[a['value']]}): {a['words']}" for a in cat["actions"])
    return (f"Events (\"when\": {{\"event\": NAME, ...options}}). Options: class is a regular expression for "
            f"the window class, lowercase app names like firefox, steam, kitty, org.gnome.nautilus; at is HH:MM "
            f"24 h; days is like mon,tue or weekdays / weekends:\n{events}\n\n"
            f"Actions (\"do\": [{{\"action\": NAME, \"value\": ...}}], at most {MAX_ACTIONS}):\n{actions}\n\n"
            "Answer with {\"name\": a short title, \"when\": {...}, \"do\": [...]}.\n"
            "Example: \"when I open steam turn on do not disturb\" -> "
            "{\"name\": \"Quiet for Steam\", \"when\": {\"event\": \"app-open\", \"class\": \"steam\"}, "
            "\"do\": [{\"action\": \"dnd\", \"value\": \"on\"}]}\n\n"
            f"Sentence: {text}")


def from_text(text, ask=None):
    """(rule, None) or (None, why): the quick model's rule for `text`,
    validated strictly. Local only: no cloud model is ever asked."""
    worker = _module("llm_worker", "llm-worker.py")
    if ask is None:
        model, why = worker.ready("quick")
        if model is None:
            return None, f"the local model cannot run now: {why.removesuffix(': do the job yourself')}"

        def ask(prompt):
            return worker.ask(model, prompt, system=SYSTEM, extra={
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "rule", "schema": SCHEMA}}})
    try:
        answer = ask(model_prompt(text))
    except Exception as err:        # the server, the network, a timeout
        return None, f"the local model did not answer ({err})"
    m = re.search(r"\{.*\}", answer or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return None, "the model's answer was not a rule"
    if data.get("error"):
        return None, f"the model says it cannot: {data['error']}"
    rule = {"name": data.get("name"), "enabled": True, "when": data.get("when"), "do": data.get("do")}
    tidy, problems = validate(rule)
    if problems:
        return None, "the model's rule does not check out: " + "; ".join(problems)
    return tidy, None


def add(rule):
    """Validate and append; returns the saved rule (with its id)."""
    rule = dict(rule)
    rule.pop("builtin", None)
    tidy, problems = validate(rule)
    if problems:
        raise ValueError("; ".join(problems))
    raw = read_file()
    taken = {r.get("id") for r in raw if isinstance(r, dict)} | {b["id"] for b in BUILTIN}
    if not tidy["id"] or tidy["id"] in taken:
        tidy["id"] = slug(tidy["name"], taken)
    raw.append(tidy)
    save(raw)
    return tidy


def update_raw(rid, change):
    """Apply change(raw rule) to the file's rule `rid` (a built-in one missing
    from the file is written in first). False when there is none."""
    raw = read_file()
    good, _ = load()
    rule = find(good, rid)
    if rule is None:
        return False
    target = next((r for r in raw if isinstance(r, dict) and r.get("id") == rule["id"]), None)
    if target is None:
        target = dict(rule)
        raw.insert(0, target)
    if change(target, raw) is not False:
        save(raw)
    return True


# -- the command line -------------------------------------------------------------
def rows():
    good, bad = load()
    state = daemon_state()
    out = []
    for r in good:
        fired = state.get("fired", {}).get(r["id"])
        out.append({**r, "words": describe(r), "last": fired, "paused": state.get("paused", {}).get(r["id"])})
    return {"rules": out, "broken": [{"rule": l, "problems": p} for l, p in bad],
            "running": bool(state), "watching": state.get("watching", []), "file": RULES}


def main(argv):
    cmd = argv[0] if argv else "list"
    args = argv[1:]
    if cmd == "run":
        Daemon().main()
    elif cmd == "list":
        data = rows()
        if "--json" in args:
            print(json.dumps(data))
            return 0
        for r in data["rules"]:
            mark = "on " if r["enabled"] else "off"
            extra = f"  [paused: {r['paused']}]" if r["paused"] else ""
            last = f"  (last {time.strftime('%a %H:%M', time.localtime(r['last']))})" if r["last"] else ""
            print(f"{mark}  {r['id']:<22} {r['words']}{last}{extra}")
        for b in data["broken"]:
            print(f"BROKEN  {b['rule']}: {'; '.join(b['problems'])}")
        if not data["running"]:
            print("(the daemon is not running: systemctl --user enable --now automations.service)")
    elif cmd == "catalog":
        print(json.dumps(catalog()))
    elif cmd == "check":
        good, bad = load()
        for label, problems in bad:
            print(f"{label}: {'; '.join(problems)}")
        print(f"{len(good)} rules check out" + (f", {len(bad)} do not" if bad else ""))
        return 1 if bad else 0
    elif cmd == "test" and args:
        rule = find(load()[0], args[0])
        if rule is None:
            return f"automations: no rule {args[0]!r}"
        print(describe(rule))
        if "--dry-run" in args:
            for a in rule["do"]:
                argv_, how = action_argv(a)
                print("  " + (shlex.join(argv_) if argv_ else f"cannot: {how}"))
            return 0
        problems = do_actions(rule)
        for p in problems:
            print(f"  did not work: {p}")
        return 1 if problems else 0
    elif cmd in ("enable", "disable") and args:
        on = cmd == "enable"
        if not update_raw(args[0], lambda r, _raw: r.__setitem__("enabled", on)):
            return f"automations: no rule {args[0]!r}"
        if on:
            poke("resume " + find(load()[0], args[0])["id"])
    elif cmd == "delete" and args:
        rule = find(load()[0], args[0])
        if rule is None:
            return f"automations: no rule {args[0]!r}"
        if rule.get("builtin"):
            return f"automations: {rule['id']} is built in: disable it instead"
        update_raw(rule["id"], lambda r, raw: raw.remove(r))
    elif cmd == "add" and args:
        try:
            rule = add(json.loads(args[0]))
        except ValueError as err:
            return f"automations: {err}"
        print(f"added {rule['id']}: {describe(rule)}")
    elif cmd == "add-from-text" and args:
        text = " ".join(a for a in args if not a.startswith("--"))
        rule, why = from_text(text)
        if "--json" in args:
            print(json.dumps({"rule": rule, "words": describe(rule) if rule else "", "error": why}))
            return 0 if rule else 1
        if rule is None:
            return f"automations: {why}"
        print(describe(rule))
        print(json.dumps(rule, indent=2, ensure_ascii=False))
        if "--yes" not in args:
            if not sys.stdin.isatty():
                return "automations: not saved (no terminal to ask on; --yes saves without asking)"
            if input("Save this rule? [y/N] ").strip().lower() not in ("y", "yes", "s", "si", "sí"):
                print("not saved")
                return 0
        print(f"added {add(rule)['id']}")
    elif cmd == "event" and args:
        if args[0] in ("context-enter", "context-leave") and len(args) > 1:
            poke(f"event {args[0]} {' '.join(args[1:])}")
            return 0
        if args[0] not in POKED:
            return ("automations: event is idle-start, idle-end, presence-away, presence-back, "
                    "focus-start, focus-end, or context-enter|context-leave NAME")
        poke("event " + args[0])
    else:
        print(__doc__.split("\n\n")[1])
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ValueError as err:       # automations.json not readable: say so, change nothing
        sys.exit(f"automations: {err}")
