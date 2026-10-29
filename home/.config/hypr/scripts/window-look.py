#!/usr/bin/env python3
"""Your window look: overrides of the desktop theme's Hyprland look and
behaviour -- gaps, borders, corners, blur, shadow, dimming of the windows
you are not using, the tiling layout and where new windows go. The backend of
the Settings window's "Windows & workspaces" page, and usable from the
launcher and the keys the same way.

    window-look.py status              JSON: every key with yours, the theme's,
                                       what is in effect, and what Hyprland
                                       reports live (and whether gamemode is on)
    window-look.py get <key>           the value in effect, one line
    window-look.py set <key> <value>   yours from now on (checked and clamped;
                                       the theme's own value = no override)
    window-look.py toggle <key>        flip an on / off key (blur, shadow,
                                       dim_inactive, resize_on_border, snap)
    window-look.py cycle layout        dwindle -> master -> scrolling -> ...
    window-look.py unset <key>         back to the theme's
    window-look.py reset               all of them back: "Use the theme's look"
    window-look.py apply               apply the saved look again (after something
                                       else -- a script, `hyprctl keyword` --
                                       changed one of these options live)
    window-look.py keys                the keys, one per line, with their range
    window-look.py workspaces [--json] read only: the workspaces each monitor
                                       starts with (lua/rules.lua), the
                                       scratchpads (lua/binds.lua) and whether
                                       the overview and cube plugins are loaded

Values: numbers for the sizes; yes / no (on / off) for switches; 0-1 or a
percentage ("30%") for dim_strength and inactive_opacity; the names listed
by `keys` for the choices.

Where it lives. Each override is a hyprlook.<key> line in the display state
file, ~/.local/state/hypr/display.conf (format and the other readers:
~/.config/hypr/lua/shared.lua), next to the theme, the filter and the rest.
<key> is the theme's own hypr.<key> name (~/.config/themes/<name>/theme.conf),
and lua/display.lua lays the hyprlook.* lines over the theme at EVERY config
load before it applies the look -- so they survive a reload, gamemode OFF
(which is one) and a re-login, and they stay when you switch themes. This
script only writes the file (through display.py's own reader and writer, so
the two can never disagree about its format) and then asks Hyprland to
re-run that same Lua:

    hyprctl eval 'require("lua.display").apply()'

so nothing here sets a Hyprland option directly, and what you see after a
`set` is exactly what the next reload will give you.

Gamemode (ALT+SHIFT+G) strips gaps, borders, rounding, blur and shadow while
it is on, and display.lua leaves those alone until it is off: a `set` then
is saved and shows when gamemode ends. status says so ("gamemode": true).

Workspaces are read, never written: they are lua/rules.lua's
hl.workspace_rule lines (the monitors area owns those), the scratchpads are
binds in lua/binds.lua, and the overview (hyprview) and cube (hypr-cube)
plugins have no on / off setting -- lua/overview.lua and lua/cube.lua load the
plugin whenever its .so is in ~/.local/lib/hyprland/, so the only switch is
the require line in hyprland.lua (or deleting the .so). `workspaces` says
that rather than offering a switch that would not survive a reload.

Exit status 1 with the reason on stderr for an unknown key or a value that is
not one; prints nothing on success except for status / get / keys.
"""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
sys.path.insert(0, HERE)
import display  # noqa: E402  (the display state file's reader / writer, hypr_eval)
import theme  # noqa: E402  (the resolved theme.conf; no GTK, cheap to import)
import screens  # noqa: E402  (the primary screen and the screens' order)
import desk_common  # noqa: E402  (hypr_request: hyprctl over the socket)

PREFIX = "hyprlook."

# Every key the page and this script offer, in the page's order.
#   kind     int | frac | bool | choice
#   option   the Hyprland option status reads back live (hyprctl getoption)
#   default  only for keys no theme sets: what lua/display.lua LOOK_DEFAULTS
#            uses when nobody sets it (the test checks the two agree). The
#            theme keys always come from the base theme, cyberpunk.
#   strip    gamemode holds this one at its own value while it is on
KEYS = {
    "gaps_in":          {"kind": "int", "lo": 0, "hi": 40, "unit": "px", "option": "general:gaps_in",
                         "label": "Gaps between windows", "strip": True},
    "gaps_out":         {"kind": "int", "lo": 0, "hi": 60, "unit": "px", "option": "general:gaps_out",
                         "label": "Gaps at the screen edges", "strip": True},
    "border_size":      {"kind": "int", "lo": 0, "hi": 12, "unit": "px", "option": "general:border_size",
                         "label": "Border width", "strip": True},
    "rounding":         {"kind": "int", "lo": 0, "hi": 30, "unit": "px", "option": "decoration:rounding",
                         "label": "Corner rounding", "strip": True},
    "rounding_power":   {"kind": "int", "lo": 1, "hi": 10, "unit": "", "option": "decoration:rounding_power",
                         "label": "Corner shape", "default": "2"},
    "blur":             {"kind": "bool", "option": "decoration:blur:enabled",
                         "label": "Blur behind see-through windows and the bar", "strip": True},
    "blur_size":        {"kind": "int", "lo": 1, "hi": 20, "unit": "", "option": "decoration:blur:size",
                         "label": "Blur strength", "strip": True},
    "blur_passes":      {"kind": "int", "lo": 1, "hi": 6, "unit": "", "option": "decoration:blur:passes",
                         "label": "Blur passes (smoother, more GPU)", "strip": True},
    "shadow":           {"kind": "bool", "option": "decoration:shadow:enabled",
                         "label": "Window shadows", "strip": True},
    "shadow_range":     {"kind": "int", "lo": 1, "hi": 50, "unit": "px", "option": "decoration:shadow:range",
                         "label": "Shadow size", "strip": True},
    "dim_inactive":     {"kind": "bool", "option": "decoration:dim_inactive",
                         "label": "Dim the windows you are not using", "default": "no"},
    "dim_strength":     {"kind": "frac", "lo": 0.05, "hi": 0.9, "option": "decoration:dim_strength",
                         "label": "Dim strength", "default": "0.5"},
    "inactive_opacity": {"kind": "frac", "lo": 0.5, "hi": 1.0, "option": "decoration:inactive_opacity",
                         "label": "Opacity of the windows you are not using", "default": "1.0"},
    "layout":           {"kind": "choice", "choices": ["dwindle", "master", "scrolling"],
                         "option": "general:layout", "label": "Tiling layout", "default": "dwindle"},
    "force_split":      {"kind": "choice", "choices": ["0", "1", "2"], "option": "dwindle:force_split",
                         "label": "New windows (dwindle)", "default": "0",
                         "aliases": {"mouse": "0", "left": "1", "top": "1", "right": "2", "bottom": "2"}},
    "new_status":       {"kind": "choice", "choices": ["slave", "master", "inherit"], "option": "master:new_status",
                         "label": "New windows (master)", "default": "slave",
                         "aliases": {"stack": "slave"}},
    "orientation":      {"kind": "choice", "choices": ["left", "right", "top", "bottom", "center"],
                         "option": "master:orientation", "label": "Master side", "default": "left"},
    "resize_on_border": {"kind": "bool", "option": "general:resize_on_border",
                         "label": "Resize windows by dragging their border", "default": "no"},
    "snap":             {"kind": "bool", "option": "general:snap:enabled",
                         "label": "Floating windows snap to edges and each other", "default": "no"},
}
TRUE, FALSE = ("yes", "on", "true", "1"), ("no", "off", "false", "0")


# -- values (pure: no files, no Hyprland) ------------------------------------
def normalize(key, value):
    """The canonical text for `value` of `key` -- what goes into the state
    file and what status compares. Numbers are clamped into the key's range
    rather than refused (a slider or a key bind should never fail on an edge);
    words that are not a value raise ValueError."""
    spec = KEYS.get(key)
    if spec is None:
        raise ValueError(f"no key {key!r}; have: {', '.join(KEYS)}")
    text = str(value).strip().lower()
    kind = spec["kind"]
    if kind == "bool":
        if text in TRUE:
            return "yes"
        if text in FALSE:
            return "no"
        raise ValueError(f"{key}: yes or no, not {value!r}")
    if kind == "choice":
        text = spec.get("aliases", {}).get(text, text)
        if text not in spec["choices"]:
            raise ValueError(f"{key}: one of {', '.join(spec['choices'])}, not {value!r}")
        return text
    percent = text.endswith("%")
    try:
        number = float(text.rstrip("%").strip())
    except ValueError:
        raise ValueError(f"{key}: a number, not {value!r}") from None
    if kind == "int":
        return str(int(round(max(spec["lo"], min(spec["hi"], number)))))
    # frac: 0-1, or a percentage -- "30%", or a bare number above 1 ("30")
    if percent or number > 1:
        number /= 100
    return f"{max(spec['lo'], min(spec['hi'], number)):.2f}"


def theme_value(key, conf):
    """The theme's value for `key` (its hypr.<key>), canonical; the default
    when no theme in the chain sets it; "" when neither (left alone)."""
    raw = conf.get("hypr." + key, "") or KEYS[key].get("default", "")
    try:
        return normalize(key, raw) if raw != "" else ""
    except ValueError:
        return KEYS[key].get("default", "")


def overrides(state):
    """{key: canonical value} for the hyprlook.* lines of the state file this
    script knows (a hand-written hyprlook.<other> line is display.lua's
    business and is left in place, untouched)."""
    out = {}
    for key in KEYS:
        raw = state.get(PREFIX + key, "")
        if raw:
            try:
                out[key] = normalize(key, raw)
            except ValueError:
                pass
    return out


def changed_state(state, key, value, conf):
    """The state after setting `key` to `value` (None = back to the theme). A
    value equal to the theme's own is not an override: dropping it keeps the
    file to what you actually changed, and a later theme change then still
    reaches that key."""
    new = dict(state)
    want = None if value is None else normalize(key, value)
    if want is None or want == theme_value(key, conf):
        new.pop(PREFIX + key, None)
    else:
        new[PREFIX + key] = want
    return new


def reset_state(state):
    """Every hyprlook.* line gone -- also the hand-written ones: "Use the
    theme's look" means all of it."""
    return {k: v for k, v in state.items() if not k.startswith(PREFIX)}


def live_value(key, reply):
    """`hyprctl -j getoption` JSON -> the canonical value, or "" if unknown.
    Gaps come back as CSS ("8 8 8 8"); the first side is the one we set."""
    if not isinstance(reply, dict):
        return ""
    for field in ("int", "float", "str", "bool", "css", "custom"):
        if field in reply:
            raw = reply[field]
            if field == "bool":
                raw = "yes" if raw else "no"
            elif field == "css":
                raw = str(raw).split()[0] if str(raw).split() else ""
            elif field == "int" and KEYS[key]["kind"] == "bool":
                raw = "yes" if raw else "no"
            try:
                return normalize(key, raw)
            except ValueError:
                return ""
    return ""


def rows(state, conf, live=None, gamemode=False):
    """status's "keys" list: one dict per key, in KEYS order."""
    mine = overrides(state)
    out = []
    for key, spec in KEYS.items():
        theirs = theme_value(key, conf)
        row = {"key": key, "label": spec["label"], "kind": spec["kind"],
               "theme": theirs, "override": mine.get(key, ""),
               # "theme" when a theme in the chain sets it, "default" when
               # it is the plain config's value (LOOK_DEFAULTS)
               "from": "theme" if conf.get("hypr." + key, "") else "default",
               "value": mine.get(key, theirs),
               "live": (live or {}).get(key, ""),
               "held_by_gamemode": bool(gamemode and spec.get("strip"))}
        for field in ("lo", "hi", "unit", "choices"):
            if field in spec:
                row[field] = spec[field]
        out.append(row)
    return out


# -- the system --------------------------------------------------------------
def theme_conf():
    return theme.load()


def getoption(option):
    try:
        out = subprocess.run(["hyprctl", "-j", "getoption", option], capture_output=True,
                             text=True, timeout=2).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def live_values():
    return {key: live_value(key, getoption(spec["option"])) for key, spec in KEYS.items()}


def gamemode_on():
    reply = getoption("animations:enabled")
    return isinstance(reply, dict) and reply.get("bool", reply.get("int", 1)) in (False, 0)


def save_and_apply(state):
    display.write_state(state)
    err = display.apply_display()
    if err:
        fail(f"window look saved, but Hyprland said: {err}")


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def notify(title):
    """Only for the keys / launcher commands (toggle, cycle, reset); quiet
    with DISPLAY_QUIET, like display.py."""
    if os.environ.get("DISPLAY_QUIET"):
        print(title)
        return
    subprocess.run([NOTIFY, "-a", "Display", "-u", "low", "-t", "2000",
                    "-h", "string:x-canonical-private-synchronous:window-look", title],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -- workspaces (read only) ---------------------------------------------------
HYPR_DIR = os.path.dirname(HERE)
RULES_LUA = os.path.join(HYPR_DIR, "lua", "rules.lua")
BINDS_LUA = os.path.join(HYPR_DIR, "lua", "binds.lua")
INDEX_LUA = os.path.join(HYPR_DIR, "hyprland.lua")
PLUGIN_DIR = os.path.expanduser("~/.local/lib/hyprland")
# The two workspace plugins: their Lua module, .so, and plugin name in
# `hyprctl plugin list`, plus what the page calls them and their keys.
PLUGINS = [
    {"id": "overview", "module": "lua.overview", "so": "hyprview.so", "plugin": "hyprview",
     "title": "Window overview", "keys": "SUPER+D (this workspace), SUPER+SHIFT+D (all of them)",
     "build": "scripts/hyprview-build.sh"},
    {"id": "cube", "module": "lua.cube", "so": "hypr-cube.so", "plugin": "hypr-cube",
     "title": "Workspace cube", "keys": "ALT+wheel spins it, ALT+CTRL+drag turns it by hand",
     "build": "scripts/hypr-cube-build.sh"},
]


def read_text(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def lua_code(text):
    """The Lua with its -- line comments removed. A "--" inside a string
    ("kitty --class ...") is not a comment, so each line is scanned with
    the quotes tracked."""
    out = []
    for line in text.splitlines():
        quote, cut = None, len(line)
        for i, ch in enumerate(line):
            if quote:
                if ch == quote and line[i - 1] != "\\":
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif line.startswith("--", i):
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def screen_expr(expr, primary, order):
    """A monitor as lua/rules.lua writes it -> a name, or "" for none. A
    quoted name is itself; the variables are its roles: P the primary,
    second / third the host file's second and third screen (order); "a or b"
    is the first of them that is known."""
    roles = {"P": primary, "second": order[1] if len(order) > 1 else "",
             "third": order[2] if len(order) > 2 else ""}
    for part in expr.split(" or "):
        part = part.strip()
        name = part.strip('"') if part.startswith('"') else roles.get(part, primary if part else "")
        if name:
            return name
    return ""


def parse_workspace_rules(text, primary=None, order=None):
    """[{workspace, monitor, default, persistent}] from the uncommented
    hl.workspace_rule({ ... }) calls and lua/rules.lua's pin("N", screen,
    default) calls, in file order. Only for when Hyprland does not answer
    (workspaces_status() asks it first): a monitor given as a Lua variable is
    resolved by its role (screen_expr) -- P the primary (`monitor = P`,
    require("lua.monitors").primary()), second / third the host file's."""
    primary = screens.primary() if primary is None else primary
    order = screens.order([]) if order is None else order
    code = lua_code(text)
    found = []
    for at, body in ((m.start(), m.group(1)) for m in
                     re.finditer(r"hl\.workspace_rule\(\s*\{(.*?)\}\s*\)", code, re.S)):
        fields = dict(re.findall(r'(\w+)\s*=\s*("[^"]*"|true|false|\d+|[A-Za-z_]\w*)', body))
        if "workspace" not in fields or not fields["workspace"].startswith('"'):
            continue        # pin()'s own call, `workspace = ws`: its callers are read below
        mon = fields.get("monitor", "")
        found.append((at, {"workspace": fields["workspace"].strip('"'),
                           "monitor": screen_expr(mon, primary, order) if mon else "",
                           "default": fields.get("default") == "true",
                           "persistent": fields.get("persistent") == "true"}))
    for m in re.finditer(r'\bpin\(\s*"(\w+)"\s*,\s*([^,)]+?)\s*(?:,\s*([^)]*?)\s*)?\)', code):
        mon = screen_expr(m.group(2), primary, order)
        default = (m.group(3) or "").strip()
        if default.endswith("~= nil"):      # pin("4", second or P, second ~= nil)
            default = bool(screen_expr(default[:-len("~= nil")].strip(), "", order))
        else:
            default = default == "true"
        found.append((m.start(), {"workspace": m.group(1), "monitor": mon,
                                  "default": bool(mon) and default, "persistent": True}))
    # Every screen past the third: lua/rules.lua's `for n = 4, #SCREENS`
    # loop, pin(W.slot(n), SCREENS[n], true) -- generated, so not in the file
    # as pin() calls; generated_pins() says the same from the screens' order.
    loop = re.search(r"\bW\.slot\(", code)
    if loop:
        found += [(loop.start(), rule) for rule in generated_pins(order)]
    return [rule for _, rule in sorted(found, key=lambda pair: pair[0])]


def slot(n):
    """lua/workspaces.lua's M.slot: the workspace the n-th screen (n >= 2)
    gets as its own -- 4, 6, then n + 3 (the fourth screen's is 7)."""
    return {2: 4, 3: 6}.get(n, n + 3)


def last_workspace(count):
    """lua/workspaces.lua's M.last: the highest workspace a key reaches with
    `count` screens -- 6, or the last screen's own from the fourth on; 10 at
    most (the 0 key)."""
    return min(slot(count) if count >= 4 else 6, 10)


def generated_pins(order):
    """The pins lua/rules.lua makes in its loop for the 4th screen on:
    [{workspace, monitor, default, persistent}] -- workspace slot(n) on the
    n-th screen of `order`, its default, while it is a key's (last_workspace)."""
    top = last_workspace(len(order))
    return [{"workspace": str(slot(n)), "monitor": order[n - 1], "default": True, "persistent": True}
            for n in range(4, len(order) + 1) if slot(n) <= top]


def live_workspace_rules(reply):
    """hyprctl workspacerules -j -> the parse_workspace_rules() shape."""
    return [{"workspace": str(r.get("workspaceString", "")), "monitor": r.get("monitor", "") or "",
             "default": bool(r.get("default")), "persistent": bool(r.get("persistent"))}
            for r in reply if isinstance(r, dict) and r.get("workspaceString")]


def key_name(expr, main_mod):
    """'mainMod .. "+grave"' -> "ALT+`"; '"SUPER+Return"' -> "SUPER+Return"."""
    text = "".join(main_mod if part.strip() == "mainMod" else part.strip().strip('"')
                   for part in expr.split(".."))
    return text.replace("grave", "`")


def parse_scratchpads(text, main_mod="ALT"):
    """[{name, key, title}] for each bind that shows a special workspace:
    toggle_special("name") or the per-app scratchpad("name", ...) helper."""
    found = []
    code = lua_code(text)
    for match in re.finditer(r'hl\.bind\(([^,]+),\s*(?:hl\.dsp\.workspace\.toggle_special\("([\w-]+)"\)'
                             r'|scratchpad\("([\w-]+)")', code):
        tail = code[match.end():match.end() + 400]
        desc = re.search(r'description\s*=\s*"([^"]*)"', tail)
        # "Scratchpads: Toggle scratchpad" -> "Toggle scratchpad" -> "Scratchpad"
        title = (desc.group(1) if desc else "").split(":", 1)[-1].strip()
        title = title.removeprefix("Toggle ").capitalize() if title.startswith("Toggle ") else title
        found.append({"name": match.group(2) or match.group(3),
                      "key": key_name(match.group(1), main_mod), "title": title})
    return found


def required(module, index_text):
    """Is require("lua.x") an uncommented line of hyprland.lua?"""
    return re.search(r'require\(\s*"' + re.escape(module) + r'"\s*\)', lua_code(index_text)) is not None


def hyprctl_json(*args):
    """`hyprctl ARGS -j`, parsed; None when Hyprland does not answer. Over the
    request socket (desk_common.hypr_request): no process."""
    return desk_common.hypr_request(args, json=True, timeout=3)


def workspaces_data(rules_text, binds_text, index_text, monitors, workspaces, plugins, built,
                    main_mod="ALT", primary=None, live_rules=None):
    """The `workspaces --json` document (pure: the tests feed it canned
    files and hyprctl replies). monitors / workspaces / plugins: hyprctl's
    JSON lists, or None when Hyprland did not answer; built: the .so names
    present. live_rules: hyprctl workspacerules -j -- what Hyprland obeys,
    used over the file when it answered."""
    if isinstance(live_rules, list) and live_rules:
        rules = live_workspace_rules(live_rules)
    else:
        rules = parse_workspace_rules(rules_text, primary)
    connected = [m.get("name") for m in monitors or []]
    names = list(dict.fromkeys([r["monitor"] for r in rules if r["monitor"]] + connected))
    live = {str(w.get("id")): w for w in workspaces or []}
    per_monitor = []
    for name in names:
        mine = [r for r in rules if r["monitor"] == name]
        per_monitor.append({
            "monitor": name, "connected": name in connected if monitors is not None else None,
            "workspaces": [r["workspace"] for r in mine],
            "default": next((r["workspace"] for r in mine if r["default"]), ""),
            "windows": sum(live.get(r["workspace"], {}).get("windows", 0) for r in mine)})
    pads = parse_scratchpads(binds_text, main_mod)
    special = {w.get("name", ""): w.get("windows", 0) for w in workspaces or []
               if str(w.get("name", "")).startswith("special:")}
    for pad in pads:
        pad["windows"] = special.get("special:" + pad["name"], 0)
    loaded = {p.get("name") for p in plugins or []}
    plug = [{"id": p["id"], "title": p["title"], "keys": p["keys"], "build": p["build"],
             "required": required(p["module"], index_text), "built": p["so"] in built,
             "loaded": (p["plugin"] in loaded) if plugins is not None else None}
            for p in PLUGINS]
    return {"monitors": per_monitor, "scratchpads": pads, "plugins": plug,
            "unplaced": [r["workspace"] for r in rules if not r["monitor"]]}


def pick_main_mod(value):
    """lua/shared.lua's rule for input.conf's main_mod: ALT or SUPER (any
    case), anything else (or nothing) ALT."""
    value = (value or "").strip().upper()
    return value if value in ("ALT", "SUPER") else "ALT"


def main_mod():
    """The main modifier lua/shared.lua binds with (mainMod): the one
    input-settings.py saved (its effective(): the saved value or the
    default). It is no longer a literal in shared.lua to be read off, so
    the file is not asked. ALT when input-settings.py cannot be read."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("input_settings", os.path.join(HERE, "input-settings.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return pick_main_mod(mod.effective().get("main_mod"))
    except Exception:  # noqa: BLE001
        return "ALT"


def workspaces_status():
    try:
        built = set(os.listdir(PLUGIN_DIR))
    except OSError:
        built = set()
    # The everyday keys' modifier, for the binds written as mainMod .. "+x".
    # The rules Hyprland holds now; the file (with the primary screen from
    # screens.py, for the rules that say `monitor = P`) only when it does
    # not answer.
    return workspaces_data(read_text(RULES_LUA), read_text(BINDS_LUA), read_text(INDEX_LUA),
                           hyprctl_json("monitors"), hyprctl_json("workspaces"),
                           hyprctl_json("plugin", "list"), built, main_mod(),
                           None, hyprctl_json("workspacerules"))


def print_workspaces(data):
    for m in data["monitors"]:
        state = "" if m["connected"] in (True, None) else "  (not connected)"
        print(f"{m['monitor']:10} workspaces {', '.join(m['workspaces']) or '-'}"
              f"  ·  starts on {m['default'] or '?'}{state}")
    for p in data["scratchpads"]:
        print(f"scratchpad {p['name']:8} {p['key']:14} {p['title']}  ({p['windows']} window(s))")
    for p in data["plugins"]:
        state = ("loaded" if p["loaded"] else "not loaded" if p["loaded"] is False else "?")
        print(f"{p['title']:16} {state}  ·  {'in' if p['required'] else 'NOT in'} hyprland.lua  ·  "
              f"{'built' if p['built'] else 'not built (' + p['build'] + ')'}")


# -- commands ----------------------------------------------------------------
def status_data():
    conf = theme_conf()
    gm = gamemode_on()
    return {"theme": conf.get("id", ""), "theme_label": conf.get("name") or conf.get("id", ""),
            "gamemode": gm, "keys": rows(display.read_state(), conf, live_values(), gm)}


def cmd_set(key, value):
    try:
        new = changed_state(display.read_state(), key, value, theme_conf())
    except ValueError as exc:
        fail(str(exc))
    save_and_apply(new)


def effective(key):
    conf = theme_conf()
    return overrides(display.read_state()).get(key, theme_value(key, conf))


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "status" and not args:
        print(json.dumps(status_data()))
    elif cmd == "get" and len(args) == 1:
        if args[0] not in KEYS:
            fail(f"no key {args[0]!r}; have: {', '.join(KEYS)}")
        print(effective(args[0]))
    elif cmd == "set" and len(args) == 2:
        cmd_set(*args)
    elif cmd == "unset" and len(args) == 1:
        if args[0] not in KEYS:
            fail(f"no key {args[0]!r}; have: {', '.join(KEYS)}")
        cmd_set(args[0], None)
    elif cmd == "toggle" and len(args) == 1:
        key = args[0]
        if KEYS.get(key, {}).get("kind") != "bool":
            fail(f"toggle: one of {', '.join(k for k, s in KEYS.items() if s['kind'] == 'bool')}")
        new = "no" if effective(key) == "yes" else "yes"
        cmd_set(key, new)
        notify(f"{KEYS[key]['label']}: {'on' if new == 'yes' else 'off'}")
    elif cmd == "cycle" and args == ["layout"]:
        ring = KEYS["layout"]["choices"]
        now = effective("layout")
        new = ring[(ring.index(now) + 1) % len(ring)] if now in ring else ring[0]
        cmd_set("layout", new)
        notify(f"Tiling layout: {new}")
    elif cmd == "apply" and not args:
        err = display.apply_display()
        if err:
            fail(err)
    elif cmd == "reset" and not args:
        save_and_apply(reset_state(display.read_state()))
        notify("Windows: the theme's look")
    elif cmd == "workspaces" and args in ([], ["--json"]):
        data = workspaces_status()
        print(json.dumps(data)) if args else print_workspaces(data)
    elif cmd == "keys" and not args:
        for key, spec in KEYS.items():
            if spec["kind"] in ("int", "frac"):
                rng = f"{spec['lo']}-{spec['hi']}{spec.get('unit', '')}"
            elif spec["kind"] == "bool":
                rng = "yes|no"
            else:
                rng = "|".join(spec["choices"])
            print(f"{key:18} {rng:30} {spec['label']}")
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
