#!/usr/bin/env python3
"""The bar and its toolbox: which pills it shows and in what order, which
screen it is on, how often the slow pills look again -- the backend of
Settings > Bar & toolbox, usable from a terminal or a key as well.

    bar-settings.py status                   JSON: everything below, as it is now
    bar-settings.py hide <module>            take a pill off the bar (or a row off
    bar-settings.py show <module>            the toolbox) / put it back where it was
    bar-settings.py move <module> up|down|first|last
                                             reorder within its own side
    bar-settings.py screen <output>          put the bar (and the toolbox, which
                                             drops down under it) on DP-2, ...
    bar-settings.py interval <module> <seconds>
                                             how often updates / weather / repos
                                             run again (custom/updates ...)
    bar-settings.py config-path              the config the bar starts from (its
                                             service runs waybar-main.sh, which asks):
                                             the file itself, or with the taskbar on
                                             a copy without the pills it stands in for
    bar-settings.py wanted                   "on" or "off": whether the bar starts at
                                             all (off: the dock's top_bar is off and
                                             dock.service is up; bar-wanted.sh asks)
    bar-settings.py toolbox-config-path      the config the toolbox starts from
                                             (toolbox-main.sh): a copy of config-
                                             toolbox laid out as a grid, which also
                                             holds the bar's pills: the keyboard
                                             layout while the dock or taskbar runs,
                                             with the bar off every pill nothing
                                             else shows
    bar-settings.py check                    parse both files; exit 1 on an error
    bar-settings.py apply                    restart the bar if a file is newer than
                                             the running bar (bar-restart.sh)
    bar-settings.py restart                  restart the bar whether or not anything
                                             changed (the page's Restart the bar, ALT+G)

<module> is the name waybar uses: "custom/weather", "hyprland/window",
"tray". Changes are written at once and take effect at the next bar restart:
`apply`, ALT+G, or the Settings page, which applies a moment after the last
click. Several changes therefore cost one restart.

The two files are the only place any of this is kept: ~/.config/waybar/config
(the bar) and ~/.config/waybar/config-toolbox (the toolbox card, a second
waybar). They are JSONC full of comments that explain the choices made in
them, so they are never parsed and dumped again -- that would throw every
comment away. Each change edits only the lines it is about, in place:

  - A hidden pill stays in its list as a comment,
        // hidden by Settings: "custom/phone"
    so it keeps its place and its own settings block, and `show` turns the
    line back into an entry. A hand edit can do the same.
  - The commas of a list are worked out again (only the entries that are
    shown carry one, the last one none), since JSON allows no trailing comma.
  - Comment lines inside a list travel with the entry below them.

Before writing, the new text is parsed and compared with the old file parsed
and changed the intended way: if anything else would differ, nothing is
written. The file before each write is kept as
$XDG_STATE_HOME/hypr/waybar-<config|config-toolbox>.prev.

One pill cannot be hidden here: custom/toolbox, the only way to open the
toolbox from the bar. (It hides by itself while the dock or the taskbar runs,
hypr/scripts/dock.py: their own toolbox button opens the card then.) (Its rows can all go: Settings, Display, Shortcuts and Night light
have keys of their own.) The bar and the toolbox always go on the same screen,
since the toolbox card drops down under the bar's sliders pill; after a
screen change toolbox_fit.py sizes the card for the new screen's width.

With the taskbar on (hypr/scripts/dock.py), the bar does not start from
~/.config/waybar/config itself but from generated/config-taskbar: the same
text with the pills the taskbar shows instead (the date and time, the
weather, the network, the sound, the power pill: dock.py bar_takeover())
hidden the way `hide` hides them. It is made again at every bar start
(config-path), so the file here stays the only one to edit, and dock.py
restarts the bar when what the taskbar takes over changes. Any problem
making it, and the bar starts from the file itself.

With the top bar off (dock.py's top_bar, TOP BAR OFF there), waybar.service
is skipped by its ExecCondition (waybar/scripts/bar-wanted.sh -> `wanted`),
and the toolbox starts from generated/config-toolbox-nobar instead: the
card with the bar's pills on top (card_lines): every one the bar shows that
the taskbar does not take over, in the bar's order -- the meters a line of
their own, the rest PILLS_PER_LINE to a line -- but CARD_NEVER, each with its settings block copied
from ~/.config/waybar/config. So hide / show / move here decide the card's
pills as they do the bar's; `status` says where each pill is (where_of). Made again at every toolbox start
(toolbox-config-path), so hide / show / move here still decide what is in it;
any problem making it, and the toolbox starts from config-toolbox itself.
The card's Microphone and Battery rows (custom/keybinds#mic and #battery,
hidden in config-toolbox; OFF_ROWS) are shown in that copy too, the bar's
battery pill left out for that row (OFF_SKIP), the CPU, GPU and disk
meters (METERS) are the first line of the bar's pills, on their own, and
the tray ends the last line (OFF_TAIL) instead of being a row of its own. bar_signals.py pokes a pill in the toolbox waybar too once
it is there.

While the dock or the taskbar runs, with the bar on as well, the keyboard
layout (dock.py CARD_PILLS) leaves the bar and is the card's only added row:
generated/config-toolbox-dock, made the same way.

Restarting goes through waybar/scripts/bar-restart.sh (systemctl restart of
waybar.service and waybar-toolbox.service), never SIGUSR2, which crashes
waybar 0.15 (bar-restart.sh says why).
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys

WAYBAR = os.path.expanduser("~/.config/waybar")
BAR = os.path.join(WAYBAR, "config")
TOOLBOX = os.path.join(WAYBAR, "config-toolbox")
RESTART = os.path.join(WAYBAR, "scripts", "bar-restart.sh")
FIT = os.path.join(WAYBAR, "scripts", "toolbox_fit.py")
TASKBAR_VARIANT = os.path.join(WAYBAR, "generated", "config-taskbar")
NOBAR_TOOLBOX = os.path.join(WAYBAR, "generated", "config-toolbox-nobar")
DOCK_TOOLBOX = os.path.join(WAYBAR, "generated", "config-toolbox-dock")
GRID_TOOLBOX = os.path.join(WAYBAR, "generated", "config-toolbox-grid")
# The card as a grid (grid_variant): its plain rows GRID_COLUMNS to a line,
# in order; a row that is a group already (the bar's pills) and the tray keep
# a line of their own, full width.
GRID_COLUMNS = 2
GRID_WIDE = ("tray",)
MIC_ROW = "custom/keybinds#mic"            # the card's Microphone row, shown with the bar off
BATTERY_ROW = "custom/keybinds#battery"    # its Battery row (time left), shown with the bar off
OFF_ROWS = (MIC_ROW, BATTERY_ROW)
# With the bar off: the pills the Battery row stands in for (the card's
# battery pill, a meter only), and the meters that get a line of their own,
# first among the bar's pills.
OFF_SKIP = ("battery",)
METERS = ("custom/cpu", "custom/gpu", "custom/disk")
# ... and the tray (background apps): at the end of the last pill line, its
# icons pills among pills, not a row of its own for one or two icons.
OFF_TAIL = ("tray",)
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")

SIDES = ("modules-left", "modules-center", "modules-right")
CARD = "group/card"                  # the toolbox's one group; its "modules" are the rows
KEEP = {"custom/toolbox": "it is the only way to open the toolbox"}

# The pills that run a script on a timer, and how often they may: the
# weather comes from wttr.in, which turns away clients that ask too often;
# the others are a dnf / flatpak query and a walk over your projects folder.
INTERVALS = {
    "custom/updates": {"title": "Software updates", "choices": [1800, 3600, 7200, 21600], "min": 600},
    "custom/weather": {"title": "Weather", "choices": [900, 1800, 3600, 7200], "min": 600},
    "custom/repos": {"title": "Git repositories", "choices": [120, 300, 600, 1800], "min": 60},
}

# (icon, title, what it is) per module, for the page and `status`. A module
# that is not here is listed by its waybar name.
MODULES = {
    "ext/workspaces": ("", "Workspaces", "a pill per workspace, on every screen; click one to go there"),
    "hyprland/submap": ("", "Key mode", "shows while a key mode (a submap) is on"),
    "hyprland/language": ("", "Keyboard layout", "the layout in use; click to switch"),
    "hyprland/window": ("", "Window title", "the focused window, on whichever screen"),
    "custom/logo": ("\uf192", "Logo", "a theme's glyph first on the bar (bar.logo=); click: the power menu"),
    "custom/menuclock": ("\uf017", "Menu-bar clock",
                         "the date and time at the far right, in a theme with bar.clock=menubar"),
    "custom/day": ("", "Date", "click: the calendar"),
    "custom/clock": ("", "Time", "click: local, UTC, epoch"),
    "custom/weather": ("", "Weather", "click: the forecast"),
    "custom/updates": ("", "Software updates",
                       "how many are waiting, and a restart when one is due; click: the updates panel"),
    "custom/repos": ("", "Git repositories", "coloured by uncommitted or unpushed work in your projects folder"),
    "custom/notifications": ("", "Notifications", "the bell; struck through in Do Not Disturb"),
    "custom/doctor": ("", "Desktop health", "only there while a service or check has failed"),
    "custom/tasks": ("\uf0ae", "Background tasks", "only there while a task needs you (a failure, a plan to approve)"),
    "custom/workhours": ("", "Work hours", "time left, during work hours only"),
    "custom/timers": ("", "Timers & alarms", "the soonest timer or the stopwatch, while one runs"),
    "custom/recording": ("", "Recording", "REC / REPLAY while the screen is being recorded"),
    "custom/capture": ("", "Screenshots & recording", "click: the capture panel"),
    "custom/player": ("", "Media", "what is playing; click: the preview panel"),
    "custom/drives": ("", "USB drives", "while one is mounted; right-click ejects"),
    "custom/phone": ("", "Phone", "its battery while KDE Connect reaches it"),
    "custom/mic": ("", "Microphone in use", "which app is listening; hidden, nothing on the bar says so"),
    "custom/camera": ("", "Camera in use", "which app has the camera; hidden, nothing on the bar says so"),
    "custom/location": ("", "Location in use", "which app asked where you are"),
    "privacy": ("", "Screen sharing", "while something is sharing a screen"),
    "custom/cpu": ("", "CPU", "load; click: graphs and the busiest processes"),
    "custom/gpu": ("", "GPU", "load; click: graphs and the apps on the GPU"),
    "custom/disk": ("", "Disk space", "warns when any disk is getting full"),
    "custom/network": ("", "Network", "connection and speed; click: the network panel"),
    "pulseaudio": ("", "Volume", "output and mic levels; click: the audio panel"),
    "custom/toolbox": ("", "Toolbox button",
                       "opens the toolbox card below (the dock or taskbar has it instead while on)"),
    "custom/power": ("", "Power menu", "lock, suspend, log out... (SUPER+Escape works without it;"
                     " hidden by a theme whose logo opens it)"),
    # The toolbox card's rows.
    "custom/keybinds#mic": ("\uf130", "Microphone",
                      "level and mute, lit while an app listens; shown by itself while the top bar is off"),
    "custom/keybinds#battery": ("\uf240", "Battery",
                      "the charge and the time left; shown by itself while the top bar is off"),
    "custom/settings": ("", "Settings", "this window (SUPER+I works without it)"),
    "custom/fsstate": ("", "Game mode", "split fullscreen: the app or the window thinks it is fullscreen"),
    "custom/nightlight": ("", "Night light", "warmer screens; same as SUPER+N"),
    "custom/awake": ("", "Keep awake", "the same switch as Settings > Power; right-click: for an hour"),
    "idle_inhibitor": ("", "Keep awake (waybar's own)", "a separate inhibitor only the bar knows about"),
    "custom/display": ("", "Display", "the display panel; same as SUPER+ALT+D"),
    "custom/keybinds": ("", "Shortcuts", "the shortcuts panel; same as SUPER+F1"),
    "tray": ("", "Tray", "background apps' icons. Hidden, apps that need a tray may refuse to start "
             "minimised or lose their icon until it is back"),
}

# With the top bar off the card takes the bar's pills (card_lines), but not
# these: the window title (the taskbar's labels have it), the logo (the
# start button is that), Keep awake (the card's own row is the same switch)
# and the sliders pill itself.
CARD_NEVER = frozenset({"hyprland/window", "custom/logo", "custom/keepawake", "custom/toolbox"})
# Most pills print nothing most of the time (a timer, a capture, a phone:
# only while there is one), and waybar hides an empty one, so a line is cut
# by what could show, not by what does -- and a cut line left the tray (which
# ends the last one, OFF_TAIL) alone on a line of empty pills. So in practice
# one line: the few that show sit together. When more show, toolbox_fit.py
# measures the card again and it widens; the tiles under it fill the new
# width ("expand").
PILLS_PER_LINE = 24

HIDDEN_RE = re.compile(r'^(\s*)//\s*hidden(?: by Settings)?:\s*"([^"]+)"\s*,?\s*(//.*)?$')
ENTRY_RE = re.compile(r'^(\s*)"([^"]+)"\s*(,?)\s*(//.*)?$')


# --------------------------------- reading JSONC ---------------------------------

def strip_comments(text):
    """JSONC -> JSON: // and /* */ comments go, strings are left alone (an
    exec line holds "//" in a URL, or an escaped quote)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            out.append(" ")
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse(text):
    """The file's value (waybar's configs are a list of bars, or one bar):
    the first bar, as a dict. ValueError with the line if it does not parse."""
    try:
        value = json.loads(strip_comments(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"line {exc.lineno}: {exc.msg}") from None
    if isinstance(value, list):
        value = value[0] if value and isinstance(value[0], dict) else None
    if not isinstance(value, dict):
        raise ValueError("not a waybar config (no bar object)")
    return value


# --------------------------------- the lists ---------------------------------

def find_list(lines, key, inside=None):
    """(start, end) line indexes of a list written one entry per line:
    lines[start] is `"key": [`, lines[end] is its `]`. With inside, the list
    is the first one of that name after the line `"inside": {` (the
    toolbox's group/card "modules"). ValueError when it is not there, or is
    written on one line (then there is nothing to edit in place)."""
    begin = 0
    if inside:
        heads = [i for i, l in enumerate(lines) if re.match(rf'^\s*"{re.escape(inside)}"\s*:\s*\{{', l)]
        if len(heads) != 1:
            raise ValueError(f'no single "{inside}" block')
        begin = heads[0] + 1
    for i in range(begin, len(lines)):
        if re.match(rf'^\s*"{re.escape(key)}"\s*:\s*\[\s*(//.*)?$', lines[i]):
            for j in range(i + 1, len(lines)):
                if re.match(r"^\s*\]\s*,?\s*(//.*)?$", lines[j]):
                    return i, j
            break
        if re.match(rf'^\s*"{re.escape(key)}"\s*:\s*\[.*\]', lines[i]):
            raise ValueError(f'"{key}" is written on one line; put one entry per line to edit it here')
        if inside and re.match(r"^\s*\}", lines[i]):
            break
    raise ValueError(f'no "{key}" list' + (f' in "{inside}"' if inside else ""))


def read_items(lines, start, end):
    """The entries of a list: [{"name", "shown", "indent", "comment", "above"}]
    -- comment is an end-of-line comment on the entry, above the comment and
    blank lines just above it -- plus the lines after the last one."""
    items, above = [], []
    for line in lines[start + 1:end]:
        hidden = HIDDEN_RE.match(line)
        entry = None if hidden else ENTRY_RE.match(line)
        if hidden:
            items.append({"name": hidden.group(2), "shown": False, "indent": hidden.group(1),
                          "comment": hidden.group(3) or "", "above": above})
        elif entry:
            items.append({"name": entry.group(2), "shown": True, "indent": entry.group(1),
                          "comment": entry.group(4) or "", "above": above})
        elif line.strip() == "" or line.strip().startswith("//"):
            above.append(line)
            continue
        else:
            raise ValueError(f"cannot read this list line: {line.strip()!r}")
        above = []
    return items, above


def write_items(items, tail):
    """The lines between `[` and `]` for these entries (see read_items)."""
    last_shown = max((i for i, it in enumerate(items) if it["shown"]), default=-1)
    out = []
    for i, it in enumerate(items):
        out += it["above"]
        if it["shown"]:
            line = f'{it["indent"]}"{it["name"]}"' + ("," if i < last_shown else "")
            out.append(line + (f" {it['comment']}" if it["comment"] else ""))
        else:
            # An entry's own end-of-line comment stays on it while hidden.
            out.append(f'{it["indent"]}// hidden by Settings: "{it["name"]}"'
                       + (f" {it['comment']}" if it["comment"] else ""))
    return out + tail


def lists_of(text, toolbox=False):
    """{list key: [items]} of one file: the three sides of the bar, or the
    toolbox card's rows (under the key "card")."""
    lines = text.split("\n")
    if toolbox:
        start, end = find_list(lines, "modules", inside=CARD)
        return {"card": read_items(lines, start, end)[0]}
    out = {}
    for side in SIDES:
        try:
            start, end = find_list(lines, side)
        except ValueError:
            continue                 # a bar may have no centre at all
        out[side] = read_items(lines, start, end)[0]
    return out


def edit_list(text, name, change, toolbox=False):
    """Apply change(items, index) to the list holding `name` (in place) and
    return the new text. ValueError if the module is in no list."""
    lines = text.split("\n")
    places = [("modules", CARD)] if toolbox else [(side, None) for side in SIDES]
    for key, inside in places:
        try:
            start, end = find_list(lines, key, inside)
        except ValueError:
            continue
        items, tail = read_items(lines, start, end)
        index = next((i for i, it in enumerate(items) if it["name"] == name), None)
        if index is None:
            continue
        change(items, index)
        lines[start + 1:end] = write_items(items, tail)
        return "\n".join(lines)
    raise ValueError(f"{name} is not on the {'toolbox' if toolbox else 'bar'}")


def set_shown(text, name, shown, toolbox=False):
    def change(items, index):
        items[index]["shown"] = shown
    return edit_list(text, name, change, toolbox)


def move(text, name, where, toolbox=False):
    def change(items, index):
        target = {"up": index - 1, "down": index + 1, "first": 0, "last": len(items) - 1}[where]
        target = max(0, min(len(items) - 1, target))
        item = items.pop(index)
        # A comment above an entry is about that entry, so it moves with it
        # (read_items keeps it as the entry's "above").
        items.insert(target, item)
    if where not in ("up", "down", "first", "last"):
        raise ValueError("move: up, down, first or last")
    return edit_list(text, name, change, toolbox)


# --------------------------------- single values ---------------------------------

def block_range(lines, name):
    """(start, end) of the `"name": {` block (a module's settings), by
    counting braces outside strings and comments."""
    for i, line in enumerate(lines):
        if re.match(rf'^\s*"{re.escape(name)}"\s*:\s*\{{', line):
            depth = 0
            for j in range(i, len(lines)):
                code = strip_comments(lines[j])
                code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
                depth += code.count("{") - code.count("}")
                if depth <= 0:
                    return i, j
            break
    raise ValueError(f'no "{name}" block')


def set_interval(text, name, seconds):
    """The `"interval": N` line of a module's block, with the number changed."""
    lines = text.split("\n")
    start, end = block_range(lines, name)
    for i in range(start + 1, end):
        m = re.match(r'^(\s*"interval"\s*:\s*)(\d+)(\s*,?\s*(//.*)?)$', lines[i])
        if m:
            lines[i] = f"{m.group(1)}{int(seconds)}{m.group(3)}"
            return "\n".join(lines)
    raise ValueError(f"{name} has no numeric interval to change")


def set_output(text, output):
    """The bar's own `"output": "X"` line (the first one, at the bar's top
    level -- a module never has one)."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*"output"\s*:\s*)"[^"]*"(\s*,?\s*(//.*)?)$', line)
        if m:
            lines[i] = f'{m.group(1)}"{output}"{m.group(2)}'
            return "\n".join(lines)
    raise ValueError('no "output": "..." line (a list of screens is not edited here)')


def interval_of(bar, name):
    value = (bar.get(name) or {}).get("interval")
    return value if isinstance(value, int) else None


def expect_change(old, new, mutate):
    """Is new (text) exactly old (text) with mutate(old parsed) applied? The
    guard against an edit that touched more than it meant to."""
    want = parse(old)
    mutate(want)
    got = parse(new)
    if got != want:
        raise ValueError("the edit would change more than intended; nothing written")


def card_of(bar):
    return bar.setdefault(CARD, {}).setdefault("modules", [])


def shown_after(old_text, new_text, toolbox):
    """For the guard: the parsed lists after a show / hide / move are the
    shown names of the edited text, everything else as before."""
    lists = lists_of(new_text, toolbox)

    def mutate(bar):
        for key, items in lists.items():
            target = card_of(bar) if key == "card" else bar.setdefault(key, [])
            target[:] = [it["name"] for it in items if it["shown"]]
    return mutate


# --------------------------------- files ---------------------------------

def read(path):
    with open(path) as handle:
        return handle.read()


def write(path, text):
    """Atomically, keeping the old file as .prev in the state folder."""
    os.makedirs(STATE, exist_ok=True)
    shutil.copy2(path, os.path.join(STATE, f"waybar-{os.path.basename(path)}.prev"))
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w") as handle:
        handle.write(text)
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def change_file(path, edit, mutate_for):
    """Read, edit, check, write -- under a lock, so two quick clicks (two
    processes) cannot both edit the old text and lose one change."""
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "bar-settings.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old = read(path)
        new = edit(old)
        if new == old:
            return False
        expect_change(old, new, mutate_for(old, new))
        write(path, new)
        return True


def which_file(name):
    """(path, toolbox?) of the file that lists this module."""
    for path, toolbox in ((BAR, False), (TOOLBOX, True)):
        try:
            for items in lists_of(read(path), toolbox).values():
                if any(it["name"] == name for it in items):
                    return path, toolbox
        except (OSError, ValueError):
            continue
    raise ValueError(f"{name} is not on the bar or in the toolbox")


# --------------------------------- the system ---------------------------------

def run(*cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def started(unit):
    """When a user unit last started (unix seconds, to the microsecond), None
    if it is not running. Asked over D-Bus because `systemctl show` gives
    whole seconds, and a change written in the same second as a restart
    would then look applied."""
    path = "/org/freedesktop/systemd1/unit/" + "".join(
        c if c.isalnum() else f"_{ord(c):02x}" for c in unit)
    out = run("busctl", "--user", "get-property", "org.freedesktop.systemd1", path,
              "org.freedesktop.systemd1.Unit", "ActiveEnterTimestamp", "ActiveState").split("\n")
    try:
        if out[1].strip() != 's "active"':
            return None
        return int(out[0].split()[1]) / 1e6
    except (IndexError, ValueError):
        return None


def pending(bar_started, toolbox_started, mtimes, bar_off=False):
    """Is either file newer than the waybar that reads it? With the bar off
    (bar_off) its file is read by the toolbox, which holds its pills."""
    bar_reader = toolbox_started if bar_off else bar_started
    return any(since is not None and mtime is not None and mtime > since
               for since, mtime in ((bar_reader, mtimes.get("bar")), (toolbox_started, mtimes.get("toolbox"))))


def screens():
    out = []
    try:
        monitors = json.loads(run("hyprctl", "monitors", "all", "-j") or "[]")
    except ValueError:
        monitors = []
    for m in monitors:
        out.append({"name": m.get("name"), "description": m.get("description", ""),
                    "width": m.get("width"), "height": m.get("height"),
                    "disabled": bool(m.get("disabled")), "dpms": m.get("dpmsStatus", True)})
    return out


def describe(name):
    icon, title, what = MODULES.get(name, ("", name, ""))
    return {"name": name, "icon": icon, "title": title, "what": what, "keep": KEEP.get(name)}


def status():
    out = {"bar": None, "toolbox": None, "problems": []}
    mtimes = {}
    for key, path, toolbox in (("bar", BAR, False), ("toolbox", TOOLBOX, True)):
        try:
            text = read(path)
            bar = parse(text)
            lists = lists_of(text, toolbox)
            mtimes[key] = os.path.getmtime(path)
        except (OSError, ValueError) as exc:
            out["problems"].append(f"{path.replace(os.path.expanduser('~'), '~')}: {exc}")
            continue
        view = dock_view()
        out[key] = {"path": path, "output": bar.get("output"),
                    "lists": {k: [dict(describe(it["name"]), shown=it["shown"],
                                       **({} if toolbox else {"where": where_of(it["name"], it["shown"], view),
                                                              "dock_key": view["keys"].get(it["name"]),
                                                              "card_never": it["name"] in CARD_NEVER}))
                                  for it in items]
                              for k, items in lists.items()}}
        if not toolbox:
            out["dock"] = view
        if not toolbox:
            out["intervals"] = [dict(INTERVALS[n], module=n, seconds=interval_of(bar, n))
                                for n in INTERVALS if n in bar]
    bar_started, toolbox_started = started("waybar.service"), started("waybar-toolbox.service")
    off = not bar_wanted()
    out["top_bar"] = "off" if off else "on"
    out["running"] = {"bar": bar_started, "toolbox": toolbox_started}
    out["pending"] = pending(bar_started, toolbox_started, mtimes, off)
    out["screens"] = screens()
    if out["bar"] and out["toolbox"] and out["bar"]["output"] != out["toolbox"]["output"]:
        out["problems"].append(f"the bar is on {out['bar']['output']} but the toolbox on "
                               f"{out['toolbox']['output']}: it drops down under the bar, so pick a screen "
                               "below to put both on one")
    return out


def apply():
    """Restart the bar if a file changed since it started. bar-restart.sh
    runs one restart at a time and quietly skips a second one; so after it
    returns, check again and go once more if a change slipped in meanwhile."""
    for _ in range(2):
        mtimes = {}
        for key, path in (("bar", BAR), ("toolbox", TOOLBOX)):
            try:
                mtimes[key] = os.path.getmtime(path)
            except OSError:
                pass
        if not pending(started("waybar.service"), started("waybar-toolbox.service"), mtimes,
                       not bar_wanted()):
            return 0
        r = subprocess.run([RESTART], capture_output=True, text=True, timeout=30)
        if r.returncode:
            sys.exit("bar-settings: the bar did not come back up -- see journalctl --user -u waybar")
    return 0


def restart():
    """Restart the bar now, changed or not: Restart the bar on the page is
    also how to bring back a bar that has gone, or one stuck on a screen
    that was asleep when it started."""
    r = subprocess.run([RESTART], capture_output=True, text=True, timeout=30)
    if r.returncode:
        sys.exit("bar-settings: the bar did not come back up -- see journalctl --user -u waybar")
    return 0


def taskbar_variant(text, names):
    """The bar's text with these pills hidden (set_shown); a name in no list
    is skipped. Checked like a hide: anything else that would differ is a
    ValueError."""
    new = text
    for name in names:
        try:
            new = set_shown(new, name, False)
        except ValueError:
            continue
    want = parse(text)
    for name in names:
        for side in SIDES:
            if name in (want.get(side) or []):
                want[side] = [n for n in want[side] if n != name]
    if parse(new) != want:
        raise ValueError("the taskbar variant changes more than its pills")
    return new


def taken_by_taskbar():
    """dock.py's bar_takeover() for its settings now; [] without it."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dock
        return dock.bar_takeover(dock.read_settings())
    except Exception:         # noqa: BLE001 - no dock: the bar as it is
        return []


def config_path():
    """The file the bar starts from (waybar-main.sh): BAR, or TASKBAR_VARIANT
    written fresh when the taskbar takes pills over. Never raises: whatever
    goes wrong, the bar starts from BAR."""
    names = taken_by_taskbar()
    if not names:
        return BAR
    try:
        text = taskbar_variant(read(BAR), names)
        os.makedirs(os.path.dirname(TASKBAR_VARIANT), exist_ok=True)
        tmp = f"{TASKBAR_VARIANT}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, TASKBAR_VARIANT)
        return TASKBAR_VARIANT
    except (OSError, ValueError) as exc:
        print(f"bar-settings: the bar as it is, not the taskbar's: {exc}", file=sys.stderr)
        return BAR


def bar_wanted():
    """Whether the top bar starts at all: no only while dock.py says the bar
    goes (bar_hidden) and dock.service is up -- so a dock that is not running
    never leaves the screen without either. Never raises: yes on any doubt."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dock
        if not dock.bar_hidden(dock.read_settings()):
            return True
        return run("systemctl", "--user", "is-active", "dock.service").strip() != "active"
    except Exception:         # noqa: BLE001 - no dock: the bar
        return True


def card_lines(bar_text, skip, only=None, first=()):
    """[(group, [pills])]: the bar's shown pills for the card, in the bar's
    order, packed PILLS_PER_LINE to a line across its sides (most pills
    print nothing most of the time, and a line per side left a card of
    ragged one-pill lines); skip (the taskbar's) and
    CARD_NEVER left out, and with only just those. The shown ones of first
    (METERS) make a line of their own ahead of the rest, in the bar's order."""
    lists = lists_of(bar_text)
    wanted = [it["name"] for side in SIDES for it in lists.get(side) or [] if it["shown"]
              and it["name"] not in skip and it["name"] not in CARD_NEVER and (only is None or it["name"] in only)]
    head = [n for n in wanted if n in first]
    rest = [n for n in wanted if n not in head]
    lines = ([head] if head else []) + [rest[i:i + PILLS_PER_LINE] for i in range(0, len(rest), PILLS_PER_LINE)]
    return [(f"group/pills-{n}", names) for n, names in enumerate(lines, 1)]


def dock_view():
    """What the dock or taskbar does to the bar's pills, for `status` and
    where_of: {"enabled", "layout", "top_bar", "taken" (bar_takeover),
    "card" (CARD_PILLS), "keys" (pill -> the dock setting that shows it on
    the taskbar)}. Off on any trouble."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dock
        cfg = dock.read_settings()
        keys = {name: key for key, names in dock.TAKEOVER if key for name in names}
        return {"enabled": bool(cfg.get("enabled")), "layout": cfg.get("layout"),
                "top_bar": bool(cfg.get("top_bar", True)), "taken": dock.bar_takeover(cfg),
                "card": list(dock.CARD_PILLS), "keys": keys,
                "settings": {k: cfg.get(k) for k in set(keys.values())}}
    except Exception:         # noqa: BLE001 - no dock: the bar as it is
        return {"enabled": False, "layout": None, "top_bar": True, "taken": [], "card": [], "keys": {},
                "settings": {}}


def where_of(name, shown, view):
    """Where a bar pill is now: "hidden" (hidden here, or with the top bar
    off one of CARD_NEVER), "toolbox", "taskbar" or "dock" (it took it), or
    "bar"."""
    if not shown:
        return "hidden"
    if view["enabled"] and name in view["card"]:
        return "toolbox"
    if name in view["taken"]:
        return "dock" if view["layout"] == "dock" else "taskbar"
    if view["enabled"] and not view["top_bar"]:
        return "hidden" if name in CARD_NEVER else "toolbox"
    return "bar"


def toolbox_variant(text, bar_text, skip, only=None, first=(), then=()):
    """The toolbox's text with the bar's pills added (card_lines): their
    rows first in the card, the groups and each pill's settings block (as
    the bar has it, comments and all) right after the "name" line, so every
    inserted block ends in a comma and nothing else is touched. skip: the
    pills the taskbar takes over; only, when given, the only pills to add.
    then: the card's own rows (the tray) to move to the end of the last
    pill line, out of the card's list.
    Checked like an edit: anything else that would differ is a ValueError;
    with no pill to add it is the text itself."""
    bar = parse(bar_text)
    rows = card_lines(bar_text, skip, only, first)
    if not rows:
        return text
    then = [n for n in then if n in card_of(parse(text))]
    rows[-1] = (rows[-1][0], rows[-1][1] + then)
    bar_lines = bar_text.split("\n")
    added = []
    for group, names in rows:
        added += ["    " + json.dumps(group) + ": {",
                  '        "orientation": "horizontal",',
                  '        "modules": [' + ", ".join(json.dumps(n) for n in names) + "]",
                  "    },"]
        for name in names:
            if name in then:
                continue              # the card's own: its block is there already
            try:
                start, end = block_range(bar_lines, name)
            except ValueError:
                continue              # waybar's defaults: the bar has no block either
            block = bar_lines[start:end + 1]
            m = re.match(r"^(\s*\})\s*,?\s*(//.*)?$", block[-1])
            if not m:
                raise ValueError(f"cannot copy the {name} block")
            added += block[:-1] + [m.group(1) + ","]
    lines = text.split("\n")
    name_at = [i for i, l in enumerate(lines) if re.match(r'^\s*"name"\s*:\s*"[^"]*"\s*,\s*(//.*)?$', l)]
    if len(name_at) != 1:
        raise ValueError('the toolbox has no single "name" line to add the pills after')
    lines[name_at[0] + 1:name_at[0] + 1] = added
    start, end = find_list(lines, "modules", inside=CARD)
    items, tail = read_items(lines, start, end)
    indent = items[0]["indent"] if items else " " * 12
    items = [it for it in items if it["name"] not in then]
    items[:0] = [{"name": group, "shown": True, "indent": indent, "comment": "", "above": []}
                 for group, _names in rows]
    lines[start + 1:end] = write_items(items, tail)
    new = "\n".join(lines)
    want = parse(text)
    card_of(want)[:] = [group for group, _names in rows] + [n for n in card_of(want) if n not in then]
    for group, names in rows:
        want[group] = {"orientation": "horizontal", "modules": names}
        for name in names:
            if name in bar and name not in then:
                want[name] = bar[name]
    if parse(new) != want:
        raise ValueError("the toolbox variant changes more than its pills")
    return new


def card_pills():
    """dock.py CARD_PILLS: the bar's pills the card holds while the dock or
    the taskbar runs; () without it."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dock
        return tuple(dock.CARD_PILLS)
    except Exception:         # noqa: BLE001 - no dock: nothing moves
        return ()


def show_off_rows(text, rows=OFF_ROWS):
    """The toolbox's text with its Microphone and Battery rows (OFF_ROWS)
    shown (the bar is off); each as it is when already shown or gone from
    the card."""
    for name in rows:
        try:
            text = set_shown(text, name, True, toolbox=True)
        except ValueError:
            pass
    return text


def grid_variant(text):
    """The toolbox's text with its card's shown rows laid out as a grid: each
    run of plain rows cut into horizontal "group/grid-N" lines of
    GRID_COLUMNS, defined right after the "name" line (as toolbox_variant
    adds its groups); groups and GRID_WIDE rows stay lines of their own. The
    card list then holds only what is shown. Checked like an edit; a card
    with nothing to pair is the text itself."""
    lines = text.split("\n")
    start, end = find_list(lines, "modules", inside=CARD)
    items, tail = read_items(lines, start, end)
    shown = [it for it in items if it["shown"]]
    out, lines_of, run_ = [], [], []

    def flush():
        for i in range(0, len(run_), GRID_COLUMNS):
            chunk = run_[i:i + GRID_COLUMNS]
            if len(chunk) == 1:
                out.append(chunk[0])
                continue
            name = f"group/grid-{len(lines_of) + 1}"
            lines_of.append((name, chunk))
            out.append(name)
        run_.clear()
    for it in shown:
        if it["name"].startswith("group/") or it["name"] in GRID_WIDE:
            flush()
            out.append(it["name"])
        else:
            run_.append(it["name"])
    flush()
    if not lines_of:
        return text
    indent = shown[0]["indent"]
    lines[start + 1:end] = write_items([{"name": n, "shown": True, "indent": indent, "comment": "", "above": []}
                                        for n in out], tail)
    name_at = [i for i, l in enumerate(lines) if re.match(r'^\s*"name"\s*:\s*"[^"]*"\s*,\s*(//.*)?$', l)]
    if len(name_at) != 1:
        raise ValueError('the toolbox has no single "name" line to add the grid after')
    lines[name_at[0] + 1:name_at[0] + 1] = [
        "    " + json.dumps(name) + ': { "orientation": "horizontal", "modules": ' + json.dumps(chunk) + " },"
        for name, chunk in lines_of]
    new = "\n".join(lines)
    want = parse(text)
    card_of(want)[:] = out
    for name, chunk in lines_of:
        want[name] = {"orientation": "horizontal", "modules": chunk}
    if parse(new) != want:
        raise ValueError("the grid changes more than the card's layout")
    return new


def toolbox_config_path():
    """The file the toolbox starts from (toolbox-main.sh), written fresh, the
    card always a grid (grid_variant): with the top bar off NOBAR_TOOLBOX,
    the bar's pills (the meters first) and the Microphone and Battery rows added; with the bar on but the
    dock or taskbar running DOCK_TOOLBOX, the keyboard layout added
    (CARD_PILLS); else GRID_TOOLBOX. Never raises: whatever goes wrong, the
    toolbox starts from TOOLBOX, the card a column."""
    off = not bar_wanted()
    taken = set(taken_by_taskbar())
    card = set(card_pills()) & taken
    path = NOBAR_TOOLBOX if off else DOCK_TOOLBOX if card else GRID_TOOLBOX
    try:
        text = read(TOOLBOX)
        if off:
            text = show_off_rows(text)
            text = toolbox_variant(text, read(BAR), (taken - card) | set(OFF_SKIP), first=METERS, then=OFF_TAIL)
        elif card:
            text = toolbox_variant(text, read(BAR), taken - card, only=card)
        text = grid_variant(text)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
        return path
    except (OSError, ValueError) as exc:
        print(f"bar-settings: the toolbox as it is, without the bar's pills: {exc}", file=sys.stderr)
        return TOOLBOX


def check():
    bad = 0
    for path, toolbox in ((BAR, False), (TOOLBOX, True)):
        try:
            text = read(path)
            parse(text)
            lists_of(text, toolbox)
            print(f"ok    {path}")
        except (OSError, ValueError) as exc:
            print(f"error {path}: {exc}")
            bad += 1
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    try:
        if cmd == "status":
            print(json.dumps(status(), indent=1))
        elif cmd == "config-path":
            print(config_path())
        elif cmd == "toolbox-config-path":
            print(toolbox_config_path())
        elif cmd == "wanted":
            print("on" if bar_wanted() else "off")
        elif cmd in ("show", "hide") and len(args) == 2:
            name = args[1]
            if cmd == "hide" and name in KEEP:
                raise ValueError(f"{name} stays: {KEEP[name]}")
            path, toolbox = which_file(name)
            change_file(path, lambda t: set_shown(t, name, cmd == "show", toolbox),
                        lambda o, n: shown_after(o, n, toolbox))
        elif cmd == "move" and len(args) == 3:
            name = args[1]
            path, toolbox = which_file(name)
            change_file(path, lambda t: move(t, name, args[2], toolbox), lambda o, n: shown_after(o, n, toolbox))
        elif cmd == "screen" and len(args) == 2:
            output = args[1]
            known = [s["name"] for s in screens()]
            if known and output not in known:
                raise ValueError(f"no screen {output} (have: {', '.join(known)})")
            for path in (BAR, TOOLBOX):
                change_file(path, lambda t: set_output(t, output),
                            lambda o, n: (lambda bar: bar.__setitem__("output", output)))
            # The toolbox card's width is worked out from the screen's.
            subprocess.run([FIT], capture_output=True, timeout=10)
        elif cmd == "interval" and len(args) == 3:
            name, seconds = args[1], int(args[2])
            if name not in INTERVALS:
                raise ValueError(f"only {', '.join(INTERVALS)}")
            if seconds < INTERVALS[name]["min"]:
                raise ValueError(f"{name} every {INTERVALS[name]['min']} s at the most often")
            change_file(BAR, lambda t: set_interval(t, name, seconds),
                        lambda o, n: (lambda bar: bar[name].__setitem__("interval", seconds)))
        elif cmd == "check":
            sys.exit(check())
        elif cmd == "apply":
            sys.exit(apply())
        elif cmd == "restart":
            sys.exit(restart())
        else:
            sys.exit(__doc__)
    except ValueError as exc:
        sys.exit(f"bar-settings: {exc}")


if __name__ == "__main__":
    main()
