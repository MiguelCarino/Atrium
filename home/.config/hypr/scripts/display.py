#!/usr/bin/env python3
"""Runtime display choices: HDR, SDR white, screen filter, animation preset,
wallpaper accent, desktop theme. One front for the display panel, the
launcher's commands and the key binds, so they can never disagree about what
is in effect.

    display.py status                  JSON: everything below, plus what is live
    display.py hdr <output>|auto on|off|toggle     auto: the primary if it has
                                              HDR, else the first that has
    display.py sdr-white <output> <nits>      SDR white inside HDR (80-480)
    display.py rate <output> <hz>|default     refresh rate, one the screen offers
                                              at its resolution (e.g. 144, 119.88)
    display.py resolution <output> <WxH>|default   a resolution the screen offers
                                              (the rate moves to the nearest one
                                              it offers there)
    display.py scale <output> <n>|default     e.g. 1, 1.25, 0.8 (see `scales`)
    display.py rotate <output> normal|90|180|270|flipped|flipped-90|...|default
    display.py position <output> left-of|right-of|above|below <other>
    display.py position <output> <X>x<Y>|default    exact, in logical pixels
    display.py mirror <output> <other>|off    show <other>'s picture
    display.py vrr <output> on|off|fullscreen|default   variable refresh rate
    display.py bitdepth <output> 8|10|default         colour depth
    display.py screen <output> on|off         use the screen or switch it off
                                              (never the last one in use)
    display.py primary <output>|default       the main screen: workspaces 1, 2,
                                              3 and 5, and the bar when it was
                                              on the old one (bar-settings.py)
    display.py resolutions|scales <output>    what it offers, one per line
    display.py restore <output> key=value...  set the stored keys back exactly
                                              (what "Undo" runs; with every
                                              value empty and --confirm, the
                                              panel's "Back to defaults")
    ... hdr / rate / resolution / scale / rotate / position / mirror / vrr /
        bitdepth / screen / restore
        with --confirm                        then ask "Keep this?" on every
                                              screen, undone after 15 s with no
                                              answer (display-confirm.py) --
                                              what the panel, launcher and keys
                                              use; scripts leave it out
    display.py filter <name>|off|toggle|cycle
    display.py anim <preset>|cycle
    display.py accent <#rrggbb>|off
    display.py theme <name>            the desktop theme (same as theme.py set)
    display.py filters | presets | themes   the names, one per line
    display.py bar                     JSON for the toolbox's Display row

The choices live in ~/.local/state/hypr/display.conf (format and readers:
~/.config/hypr/lua/shared.lua). This writes the file and then asks Hyprland to
re-run the Lua that reads it:

    hyprctl eval 'require("lua.display").apply()'     filter, animations, accent
    hyprctl eval 'require("lua.monitors").apply()'    HDR, SDR white, and the
                                                      screens' own keys below

so the code that applies a choice at a reload and the code that applies it now
is the same code. Nothing here talks to the compositor any other way.

The desktop theme is ~/.config/hypr/scripts/theme.py's: `theme` here only
hands over to it, and status/bar read it through the same module, so the
panel, the launcher and theme.py agree on the list and the current one.

The screens' own keys, one per output, each missing = "what the host file
says" (lua/monitors.lua lays them over lua/hosts/<host>.lua):

    rate.<o>=144.00  mode.<o>=1920x1080  scale.<o>=1.25  transform.<o>=1
    position.<o>=3440x0  mirror.<o>=DP-2  vrr.<o>=0|1|2  bitdepth.<o>=8|10
    disabled.<o>=on  and  primary=<o>

A placement like "right-of DP-2" is worked out here, from the live screens,
into an exact position: the file only ever holds X x Y.

"toggle" on filters flips between off and the last filter used, so SUPER+SHIFT+F
is one key for "my filter on / off" rather than a walk through the list.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme  # noqa: E402  (the desktop themes; no GTK, cheap to import)
import screens  # noqa: E402  (which screens: the host file's order, primary, HDR)

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "display.conf")
SHADERS = os.path.expanduser("~/.config/hypr/shaders")
NOTIFY = os.path.expanduser("~/.config/hypr/scripts/notify")  # notify-send with the theme's mascot (mascot_notify.py)
PRESETS = ["snappy", "smooth", "fancy", "calm", "spring"]   # lua/display.lua M.presets, theme.py PRESETS
HDR_CAPABLE = screens.hdr_capable()                # the host file's M.hdr_capable
SDR_WHITE_DEFAULT = 220                            # lua/monitors.lua
SDR_WHITE_RANGE = (80, 480)

LABELS = {
    "grayscale": "Grayscale", "reading": "Reading", "vibrance": "Vibrance",
    "protanopia": "Protanopia", "deuteranopia": "Deuteranopia",
    "tritanopia": "Tritanopia", "crt": "CRT",
}


def filters():
    try:
        names = sorted(f[:-5] for f in os.listdir(SHADERS) if f.endswith(".frag"))
    except OSError:
        return []
    # Everyday filters first, the colour-vision corrections after.
    order = ["grayscale", "reading", "vibrance", "crt"]
    return [n for n in order if n in names] + [n for n in names if n not in order]


def label(name):
    return LABELS.get(name, name.replace("-", " ").capitalize())


# -- state -------------------------------------------------------------------
def read_state():
    state = {}
    try:
        with open(STATE) as handle:
            for line in handle:
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
        for key in sorted(state):
            if state[key] != "":
                handle.write(f"{key}={state[key]}\n")
    os.replace(tmp, STATE)     # atomic: Lua may read it at any moment


def set_key(key, value):
    state = read_state()
    state[key] = value
    write_state(state)
    return state


# -- compositor --------------------------------------------------------------
def hypr_eval(code):
    try:
        out = subprocess.run(["hyprctl", "eval", code], capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"hyprctl failed: {exc}"
    text = (out.stdout + out.stderr).strip()
    return None if out.returncode == 0 and text in ("", "ok") else text


def apply_display():
    return hypr_eval('require("lua.display").apply()')


def apply_monitors():
    return hypr_eval('require("lua.monitors").apply()')


def reapply_colour():
    """A mode change can drop a screen's colour matrix: screen-color.py
    sends them all again."""
    subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen-color.py"), "apply"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def monitors():
    try:
        # "all": a screen switched off (disabled.<o>=on) is still listed,
        # with "disabled": true, so it can be switched back on.
        out = subprocess.run(["hyprctl", "monitors", "all", "-j"], capture_output=True,
                             text=True, timeout=2).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def refresh_bar():
    """The toolbox's Display row (custom/display; its number is
    bar_signals.py's "display") re-reads."""
    import bar_signals      # noqa: E402  (scripts/: on sys.path above)
    bar_signals.poke("display")


def cmd_bar():
    state = read_state()
    filt = state.get("filter", "")
    hdr = [o for o in HDR_CAPABLE if state.get(f"hdr.{o}", "on") != "off"]
    conf = theme.load()
    lines = [f"Theme: {conf.get('name') or conf['id']}",
             f"HDR: {', '.join(hdr) if hdr else 'off'}",
             f"Filter: {label(filt) if filt else 'off'}",
             f"Animations: {state.get('anim', 'smooth')}",
             f"Accent: {state.get('accent') or 'from the theme'}"
             + ("" if theme.following(conf) else " (not following the wallpaper)"),
             "", "Click: display panel   Right-click: filter on / off"]
    print(json.dumps({"text": "\uf26c", "tooltip": "\n".join(lines),
                      "class": "on" if filt else "off"}))


def hz_label(rate):
    """"144.00" -> "144", "119.88" stays: what the panel and toasts show."""
    return f"{float(rate):.2f}".rstrip("0").rstrip(".")


def rates(mon):
    """The rates a screen offers at its current resolution, highest first,
    as the mode strings use them ("144.00", "119.88")."""
    res = f"{mon['width']}x{mon['height']}@"
    found = {m[len(res):-2] for m in mon.get("availableModes", []) if m.startswith(res)}
    return sorted(found, key=float, reverse=True)


def current_rate(mon):
    offered = rates(mon)
    if not offered:
        return f"{mon.get('refreshRate', 0):.2f}"
    return min(offered, key=lambda r: abs(float(r) - mon.get("refreshRate", 0)))


# -- the screens' layout ---------------------------------------------------------
# Rotation names, in Hyprland's transform order (0-7): the four turns, then
# the same four mirrored left-to-right.
TRANSFORMS = ["normal", "90", "180", "270", "flipped", "flipped-90", "flipped-180", "flipped-270"]
# Scales worth offering; scales_for() keeps the ones that give the screen a
# whole number of logical pixels, which is what Hyprland insists on.
SCALE_CANDIDATES = [0.5, 0.6, 0.75, 0.8, 1, 1.2, 1.25, 4 / 3, 1.5, 1.6, 5 / 3, 1.75, 2, 2.4, 2.5, 3]
SIDES = ("left-of", "right-of", "above", "below")
PRIMARY_WORKSPACE = "1"
# The keys `screen-keys` covers: what one screen's Undo has to put back.
SCREEN_KEYS = ("mode", "rate", "scale", "transform", "position", "mirror", "vrr", "bitdepth", "disabled")


def resolutions(mon):
    """The resolutions a screen offers, biggest first, as "WxH"."""
    found = []
    for mode in mon.get("availableModes", []):
        res = mode.split("@")[0]
        if "x" in res and res not in found:
            found.append(res)
    return sorted(found, key=lambda r: (-int(r.split("x")[0]) * int(r.split("x")[1]), r))


def rates_at(mon, res):
    """The rates offered at one resolution, highest first ("144.00")."""
    found = {m.split("@")[1][:-2] for m in mon.get("availableModes", [])
             if m.startswith(res + "@") and m.endswith("Hz")}
    return sorted(found, key=float, reverse=True)


def nearest_rate(mon, res, hz):
    """The rate at `res` closest to `hz` (a mode change keeps the rate as
    near as it can), "" if the resolution offers none."""
    offered = rates_at(mon, res)
    return min(offered, key=lambda r: (abs(float(r) - float(hz)), -float(r))) if offered else ""


def scale_text(value):
    """1.333333 -> "1.333333", 1.25 -> "1.25", 1.0 -> "1": what the file and
    hl.monitor get (six places is what Hyprland itself prints)."""
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def scales_for(width, height, current=None):
    """The scales that give a whole number of logical pixels at this mode,
    smallest first, as scale_text strings; the current one always included."""
    out = [scale_text(s) for s in SCALE_CANDIDATES
           if abs(width / s - round(width / s)) < 0.01 and abs(height / s - round(height / s)) < 0.01]
    if current is not None and scale_text(current) not in out:
        out.append(scale_text(current))
    return sorted(set(out), key=float)


def logical_size(width, height, scale, transform):
    """How much of the desktop a screen covers: its mode divided by its scale,
    turned on its side for 90 / 270 (transform 1, 3, 5, 7)."""
    w, h = round(width / float(scale)), round(height / float(scale))
    return (h, w) if int(transform) % 2 else (w, h)


def place(side, size, other):
    """The exact position that puts a screen of logical `size` (w, h) on
    `side` of `other` ({x, y, w, h}), lined up with its top or left edge."""
    w, h = size
    x, y = {"left-of": (other["x"] - w, other["y"]),
            "right-of": (other["x"] + other["w"], other["y"]),
            "above": (other["x"], other["y"] - h),
            "below": (other["x"], other["y"] + other["h"])}[side]
    return f"{x}x{y}"


def transform_of(arg):
    """"90" / "flipped-270" / "3" -> 0-7, None if it is neither."""
    if arg in TRANSFORMS:
        return TRANSFORMS.index(arg)
    if arg.isdigit() and int(arg) < len(TRANSFORMS):
        return int(arg)
    return None


def bitdepth_of(mon):
    """10 when the screen scans out a 10-bit format (XBGR2101010...), else 8."""
    return 10 if "101010" in mon.get("currentFormat", "") else 8


def geometry(mon):
    """{x, y, w, h} in logical pixels, for place()."""
    w, h = logical_size(mon["width"], mon["height"], mon.get("scale", 1), mon.get("transform", 0))
    return {"x": mon["x"], "y": mon["y"], "w": w, "h": h}


def in_use(mons):
    """The screens showing a picture of their own: enabled, not a mirror."""
    return [m for m in mons if not m.get("disabled") and m.get("mirrorOf", "none") in ("none", "")]


def default_primary():
    """The primary when display.conf names none: the host file's first screen
    (lua/hosts/<host>.lua M.screens), or the live one at 0x0 -- screens.py,
    the same rule lua/monitors.lua's primary() uses."""
    return screens.default_primary()


def primary(state=None):
    return (state if state is not None else read_state()).get("primary") or default_primary()


def notify(title, body="", urgency="low"):
    if os.environ.get("DISPLAY_QUIET"):
        print(f"{title}{': ' + body if body else ''}")
        return
    subprocess.run([NOTIFY, "-a", "Display", "-u", urgency, "-t", "2500",
                    "-h", "string:x-canonical-private-synchronous:display",
                    title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fail(message):
    if not os.environ.get("DISPLAY_QUIET"):     # quiet: stderr is the only word
        notify("Display", message, "critical")
    print(message, file=sys.stderr)
    sys.exit(1)


# -- commands ----------------------------------------------------------------
def cmd_status():
    print(json.dumps(status_data()))


def status_data():
    """What `status` prints, as a dict (desktopctl.py imports this)."""
    state = read_state()
    conf = theme.load()
    live = {m["name"]: m for m in monitors()}
    outputs = []
    for name, mon in sorted(live.items(), key=lambda kv: (kv[1]["x"], kv[1]["y"])):
        preset = mon.get("colorManagementPreset", "")
        outputs.append({
            "name": name,
            "description": mon.get("description", ""),
            "hdr_capable": name in HDR_CAPABLE,
            "hdr_wanted": state.get(f"hdr.{name}", "on") != "off" and name in HDR_CAPABLE,
            "hdr_live": preset.startswith("hdr"),
            "sdr_white": int(float(state.get(f"sdr_white.{name}", SDR_WHITE_DEFAULT))),
            "rate": current_rate(mon),
            "rates": rates(mon),
            "rate_chosen": state.get(f"rate.{name}", ""),   # "" = lua/monitors.lua's own
            **layout_info(name, mon, state, live),
        })
    return {
        "outputs": outputs,
        "primary": primary(state),
        "primary_live": primary(state) in live,
        "filter": state.get("filter", ""),
        "filter_last": state.get("filter_last", ""),
        "filters": [{"name": f, "label": label(f)} for f in filters()],
        "anim": state.get("anim", "smooth"),
        "presets": PRESETS,
        "accent": state.get("accent", ""),
        "accent_custom": state.get(f"accent_custom_{conf['id']}", ""),
        "theme_auto": state.get("theme_auto", "on") != "off",
        # The desktop theme (theme.py). accent_follow: whether this theme lets
        # the accent follow the wallpaper at all -- the panel greys the
        # switch out when it does not.
        "theme": conf["id"],
        "theme_label": conf.get("name") or conf["id"],
        "themes": [{"name": n, "label": lbl} for n, lbl in theme.themes()],
        "accent_follow": conf.get("accent_follow", "yes") == "yes",
        "crt_suggest": conf.get("crt_suggest", "no") == "yes",
    }


def layout_info(name, mon, state, live):
    """The Screens page's arrangement fields for one output: what it is now
    (live) and what was chosen (the display.conf keys, "" = the host file's)."""
    w, h = mon.get("width", 0), mon.get("height", 0)
    scale, transform = mon.get("scale", 1) or 1, mon.get("transform", 0)
    lw, lh = logical_size(w, h, scale, transform) if w and h else (0, 0)
    mirror_of = mon.get("mirrorOf", "none")
    return {
        "enabled": not mon.get("disabled", False),
        "focused": bool(mon.get("focused")),
        "primary": name == primary(state),
        "resolution": f"{w}x{h}",
        "resolutions": resolutions(mon),
        "scale": scale_text(scale),
        "scales": scales_for(w, h, scale) if w and h else [],
        "transform": transform,
        "rotation": TRANSFORMS[transform] if 0 <= transform < len(TRANSFORMS) else str(transform),
        "x": mon.get("x", 0), "y": mon.get("y", 0), "w": lw, "h": lh,
        "mirror_of": "" if mirror_of in ("none", "") else mirror_of,
        "vrr": bool(mon.get("vrr")),
        "bitdepth": bitdepth_of(mon),
        # Mirroring needs a screen with a picture of its own (not this one,
        # not one already mirroring it).
        "mirror_targets": [n for n, m in live.items() if n != name and not m.get("disabled")
                           and m.get("mirrorOf", "none") in ("none", "")],
        "chosen": {k: state.get(f"{k}.{name}", "") for k in SCREEN_KEYS},
    }


def hdr_screen(output):
    """"auto" (what SUPER+ALT+H sends, so the bind names no connector): the
    primary when it can do HDR, else the first screen that can; anything else
    is taken as a screen name."""
    if output != "auto":
        return output
    if not HDR_CAPABLE:
        fail("no screen has HDR here (the host file's M.hdr_capable is empty, or there is no host file)")
    p = primary()
    return p if p in HDR_CAPABLE else HDR_CAPABLE[0]


def cmd_hdr(output, mode, ask=False):
    output = hdr_screen(output)
    if output not in HDR_CAPABLE:
        fail(f"{output} has no HDR mode in this machine's host file (lua/hosts/<host>.lua)")
    state = read_state()
    on_now = state.get(f"hdr.{output}", "on") != "off"
    want = {"on": True, "off": False, "toggle": not on_now}.get(mode)
    if want is None:
        fail(f"hdr: on, off or toggle, not {mode!r}")
    set_key(f"hdr.{output}", "on" if want else "off")
    err = apply_monitors()
    if err:
        fail(err)
    reapply_colour()
    if ask and want != on_now:
        confirm(f"{output}: HDR {'on' if want else 'off'}", "hdr", output, "on" if on_now else "off")
    live = next((m for m in monitors() if m["name"] == output), {})
    is_hdr = live.get("colorManagementPreset", "").startswith("hdr")
    if want and not is_hdr:
        # The panel's own OSD decides whether the EDID offers HDR at all; see
        # the HDR notes in the host file (lua/hosts/<host>.lua).
        notify(f"HDR requested on {output}", "but it stayed SDR -- is HDR on in the monitor's own menu?",
               "normal")
    else:
        notify(f"{output}: HDR {'on' if want else 'off'}")


def cmd_sdr_white(output, nits):
    try:
        value = int(float(nits))
    except ValueError:
        fail(f"sdr-white: a number of nits, not {nits!r}")
    value = max(SDR_WHITE_RANGE[0], min(SDR_WHITE_RANGE[1], value))
    set_key(f"sdr_white.{output}", str(value))
    err = apply_monitors()
    if err:
        fail(err)


def confirm(what, *revert):
    """The "Keep this?" card, detached; it runs `revert` unless kept."""
    here = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([os.path.join(here, "display-confirm.py"), what,
                      os.path.join(here, "display.py"), *revert],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_rate(output, hz, ask=False):
    mon = next((m for m in monitors() if m["name"] == output), None)
    if mon is None:
        fail(f"rate: no screen {output!r}")
    before = read_state().get(f"rate.{output}", "") or "default"
    old_hz = hz_label(current_rate(mon))
    if hz == "default":
        set_key(f"rate.{output}", "")
    else:
        offered = rates(mon)
        match = [r for r in offered if abs(float(r) - float(hz)) < 0.005] if hz.replace(".", "", 1).isdigit() else []
        if not match:
            fail(f"{output} offers {', '.join(hz_label(r) for r in offered)} Hz at this resolution, not {hz}")
        set_key(f"rate.{output}", match[0])
    err = apply_monitors()
    if err:
        fail(err)
    reapply_colour()
    live = next((m for m in monitors() if m["name"] == output), mon)
    notify(f"{output}: {hz_label(current_rate(live))} Hz")
    if ask and hz_label(current_rate(live)) != old_hz:
        confirm(f"{output}: {old_hz} Hz -> {hz_label(current_rate(live))} Hz", "rate", output, before)


def live_screen(output, what):
    mons = monitors()
    mon = next((m for m in mons if m["name"] == output), None)
    if mon is None:
        names = ", ".join(m["name"] for m in mons)
        fail(f"{what}: no screen {output!r} (connected: {names or 'none'})")
    return mon, mons


def describe(mon):
    """"1920x1080 @ 60 Hz, 125%, 90" -- the toast after a change."""
    if mon.get("disabled"):
        return "off"
    bits = [f"{mon['width']}x{mon['height']} @ {hz_label(current_rate(mon))} Hz"]
    if mon.get("scale", 1) != 1:
        bits.append(f"{round(mon['scale'] * 100)}%")
    if mon.get("transform"):
        bits.append(TRANSFORMS[mon["transform"]])
    if mon.get("mirrorOf", "none") not in ("none", ""):
        bits.append(f"mirroring {mon['mirrorOf']}")
    return ", ".join(bits)


def change_screen(output, updates, what, ask=False):
    """Write one screen's keys (value "" = back to the host file's), re-run
    lua/monitors.lua, and with ask the "Keep this?" card, whose Undo is
    `restore` with every key as it was."""
    state = read_state()
    before = {k: state.get(f"{k}.{output}", "") for k in SCREEN_KEYS}
    for key, value in updates.items():
        state[f"{key}.{output}"] = value
    write_state(state)
    err = apply_monitors()
    if err:
        # Put the file back: a key Hyprland refused must not come back at
        # the next reload.
        for key in updates:
            state[f"{key}.{output}"] = before.get(key, "")
        write_state(state)
        apply_monitors()
        fail(err)
    reapply_colour()
    live = next((m for m in monitors() if m["name"] == output), None)
    notify(f"{output}: {what}", describe(live) if live else "")
    if ask and any(before.get(k, "") != v for k, v in updates.items()):
        confirm(f"{output}: {what}", "restore", output, *[f"{k}={v}" for k, v in before.items()])


def cmd_restore(output, pairs, ask=False):
    """Set the stored keys exactly. Without ask it is the "Keep this?" card's
    Undo (quiet, no new card); with ask it is the panel's "Back to defaults"
    (every key empty), which can blank a screen like any other change."""
    updates = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or key not in SCREEN_KEYS:
            fail(f"restore: key=value with a key from {', '.join(SCREEN_KEYS)}, not {pair!r}")
        updates[key] = value
    if ask:
        live_screen(output, "restore")
        what = "back to defaults" if not any(updates.values()) else "restored"
        return change_screen(output, updates, what, ask)
    state = read_state()
    for key, value in updates.items():
        state[f"{key}.{output}"] = value
    write_state(state)
    err = apply_monitors()
    if err:
        fail(err)
    reapply_colour()


def cmd_resolution(output, res, ask=False):
    mon, _ = live_screen(output, "resolution")
    if res == "default":
        # The host file's resolution and its rate with it: a rate chosen at
        # this resolution may not exist at that one.
        return change_screen(output, {"mode": "", "rate": ""}, "default resolution", ask)
    offered = resolutions(mon)
    if res not in offered:
        fail(f"{output} offers {', '.join(offered)}, not {res}")
    rate = nearest_rate(mon, res, mon.get("refreshRate", 60))
    change_screen(output, {"mode": res, "rate": rate}, f"{res} @ {hz_label(rate)} Hz", ask)


def cmd_scale(output, value, ask=False):
    mon, _ = live_screen(output, "scale")
    if value == "default":
        return change_screen(output, {"scale": ""}, "default scale", ask)
    try:
        wanted = float(value[:-1]) / 100 if value.endswith("%") else float(value)
    except ValueError:
        fail(f"scale: a number such as 1.25 (or 125%), not {value!r}")
    offered = scales_for(mon["width"], mon["height"])
    match = [s for s in offered if abs(float(s) - wanted) < 0.002]
    if not match:
        fail(f"{output} at {mon['width']}x{mon['height']} takes {', '.join(offered)}, not {value}")
    change_screen(output, {"scale": match[0]}, f"scale {round(float(match[0]) * 100)}%", ask)


def cmd_rotate(output, arg, ask=False):
    live_screen(output, "rotate")
    if arg == "default":
        return change_screen(output, {"transform": ""}, "default rotation", ask)
    value = transform_of(arg)
    if value is None:
        fail(f"rotate: {', '.join(TRANSFORMS)} or default, not {arg!r}")
    change_screen(output, {"transform": str(value)}, f"rotation {TRANSFORMS[value]}", ask)


def cmd_position(output, args, ask=False):
    mon, mons = live_screen(output, "position")
    if args == ["default"]:
        return change_screen(output, {"position": ""}, "default position", ask)
    if len(args) == 2 and args[0] in SIDES:
        other = next((m for m in in_use(mons) if m["name"] == args[1] and m["name"] != output), None)
        if other is None:
            fail(f"position: {args[1]!r} is not another screen in use")
        size = (geometry(mon)["w"], geometry(mon)["h"])
        pos = place(args[0], size, geometry(other))
        what = f"{args[0].replace('-', ' ')} {args[1]}"
    elif len(args) == 1 and parse_position(args[0]):
        pos, what = "%dx%d" % parse_position(args[0]), f"at {args[0]}"
    else:
        fail("position: left-of|right-of|above|below <screen>, <X>x<Y> or default")
    change_screen(output, {"position": pos}, what, ask)


def parse_position(text):
    """"3440x0" / "-1280x-200" -> (x, y), None if it is not one."""
    x, sep, y = text.partition("x")
    try:
        return (int(x), int(y)) if sep else None
    except ValueError:
        return None


def cmd_mirror(output, other, ask=False):
    _, mons = live_screen(output, "mirror")
    if other in ("off", "none", "default"):
        return change_screen(output, {"mirror": ""}, "mirror off", ask)
    target = next((m for m in in_use(mons) if m["name"] == other), None)
    if other == output or target is None:
        fail(f"mirror: {other!r} is not another screen with a picture of its own")
    mirrors = [m["name"] for m in mons if m.get("mirrorOf") == output]
    if mirrors:
        fail(f"{', '.join(mirrors)} already mirrors {output}; a mirror of a mirror shows nothing")
    change_screen(output, {"mirror": other}, f"mirroring {other}", ask)


def cmd_vrr(output, arg, ask=False):
    live_screen(output, "vrr")
    values = {"off": "0", "on": "1", "fullscreen": "2", "0": "0", "1": "1", "2": "2", "default": ""}
    if arg not in values:
        fail(f"vrr: on, off, fullscreen or default, not {arg!r}")
    words = {"0": "VRR off", "1": "VRR on", "2": "VRR in fullscreen", "": "default VRR"}
    change_screen(output, {"vrr": values[arg]}, words[values[arg]], ask)


def cmd_bitdepth(output, arg, ask=False):
    live_screen(output, "bitdepth")
    if arg not in ("8", "10", "default"):
        fail(f"bitdepth: 8, 10 or default, not {arg!r}")
    value = "" if arg == "default" else arg
    change_screen(output, {"bitdepth": value}, f"{arg}-bit colour" if value else "default colour depth", ask)


def cmd_screen(output, arg, ask=False):
    mon, mons = live_screen(output, "screen")
    if arg not in ("on", "off"):
        fail(f"screen: on or off, not {arg!r}")
    if arg == "off":
        others = [m for m in in_use(mons) if m["name"] != output]
        if not others:
            fail(f"{output} is the only screen in use; switch another one on first")
        mirrors = [m["name"] for m in mons if m.get("mirrorOf") == output]
        if mirrors:
            fail(f"{', '.join(mirrors)} mirrors {output}; stop that first")
    change_screen(output, {"disabled": "on" if arg == "off" else ""}, f"screen {arg}", ask)


def cmd_primary(output):
    state = read_state()
    default = default_primary()
    if output == "default":
        output = default
    elif output not in {m["name"] for m in monitors()} and output != default:
        fail(f"primary: no screen {output!r}")
    set_key("primary", "" if output == default else output)
    # Live: workspace 1 moves there now (if that screen is up). The config's
    # own readers of "primary" put it there again at every reload.
    mon = next((m for m in in_use(monitors()) if m["name"] == output), None)
    if mon is not None and (state.get("primary") or default) != output:
        hypr_dispatch(f'hl.dsp.workspace.move({{ workspace = {PRIMARY_WORKSPACE}, monitor = "{output}" }})')
    old = state.get("primary") or default
    if mon is not None and old != output and bar_output() == old:
        move_bar(output)
    notify(f"Primary screen: {output}", "" if mon else "not connected right now")


WAYBAR_CONFIG = os.path.expanduser("~/.config/waybar/config")
BAR_SETTINGS = os.path.expanduser("~/.config/hypr/scripts/bar-settings.py")


def bar_output():
    """The screen the bar's config puts it on ("output" in ~/.config/waybar/
    config), or None. Read with a pattern, not parsed: the file is JSONC."""
    try:
        with open(WAYBAR_CONFIG, encoding="utf-8") as f:
            m = re.search(r'^\s*"output"\s*:\s*"([^"]+)"', f.read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def move_bar(output):
    """The bar follows the primary screen when it was on the old one (a bar
    put elsewhere on purpose, Settings > Bar & toolbox, stays there).
    bar-settings.py moves the bar and the toolbox together and restarts the
    bar the safe way (bar-restart.sh, never SIGUSR2); detached, so this
    command does not wait on the restart."""
    try:
        subprocess.Popen(["sh", "-c", '"$0" screen "$1" && "$0" apply', BAR_SETTINGS, output],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def hypr_dispatch(lua):
    try:
        subprocess.run(["hyprctl", "dispatch", lua], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def cmd_filter(arg):
    names = filters()
    state = read_state()
    current = state.get("filter", "")
    if arg in ("off", "none", ""):
        new = ""
    elif arg == "toggle":
        new = "" if current else (state.get("filter_last") or (names[0] if names else ""))
    elif arg == "cycle":
        ring = [""] + names
        new = ring[(ring.index(current) + 1) % len(ring)] if current in ring else ""
    elif arg in names:
        new = arg
    else:
        fail(f"no filter {arg!r}; have: {', '.join(names)}")
    state["filter"] = new
    if new:
        state["filter_last"] = new
    write_state(state)
    err = apply_display()
    if err:
        fail(err)
    notify(f"Filter: {label(new) if new else 'off'}")


def cmd_anim(arg):
    current = read_state().get("anim", "smooth")
    if arg == "cycle":
        arg = PRESETS[(PRESETS.index(current) + 1) % len(PRESETS)] if current in PRESETS else "smooth"
    if arg not in PRESETS:
        fail(f"no preset {arg!r}; have: {', '.join(PRESETS)}")
    set_key("anim", arg)
    err = apply_display()
    if err:
        fail(err)
    notify(f"Animations: {arg}")


def cmd_accent(arg):
    if arg == "off":
        set_key("accent", "")
        # No reload any more: display.apply() sets the theme's whole border
        # gradient before it lays the accent over it, so an apply without an
        # accent IS the plain border. (It used to be a `hyprctl reload
        # config-only`, which also dropped gamemode.)
        err = apply_display()
        if err:
            fail(err)
        return
    if not (len(arg) == 7 and arg.startswith("#")):
        fail(f"accent: #rrggbb or off, not {arg!r}")
    set_key("accent", arg.lower())
    err = apply_display()
    if err:
        fail(err)


def main(argv):
    ask = "--confirm" in argv
    argv = [a for a in argv if a != "--confirm"]
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "status":
        cmd_status()
    elif cmd == "bar":
        cmd_bar()
        return
    elif cmd == "hdr" and len(args) == 2:
        cmd_hdr(*args, ask=ask)
    elif cmd == "sdr-white" and len(args) == 2:
        cmd_sdr_white(*args)
    elif cmd == "rate" and len(args) == 2:
        cmd_rate(*args, ask=ask)
    elif cmd == "resolution" and len(args) == 2:
        cmd_resolution(*args, ask=ask)
    elif cmd == "scale" and len(args) == 2:
        cmd_scale(*args, ask=ask)
    elif cmd == "rotate" and len(args) == 2:
        cmd_rotate(*args, ask=ask)
    elif cmd == "position" and len(args) in (2, 3):
        cmd_position(args[0], args[1:], ask=ask)
    elif cmd == "mirror" and len(args) == 2:
        cmd_mirror(*args, ask=ask)
    elif cmd == "vrr" and len(args) == 2:
        cmd_vrr(*args, ask=ask)
    elif cmd == "bitdepth" and len(args) == 2:
        cmd_bitdepth(*args, ask=ask)
    elif cmd == "screen" and len(args) == 2:
        cmd_screen(*args, ask=ask)
    elif cmd == "primary" and len(args) == 1:
        cmd_primary(args[0])
    elif cmd == "restore" and len(args) >= 2:
        cmd_restore(args[0], args[1:], ask=ask)
    elif cmd in ("resolutions", "scales") and len(args) == 1:
        mon, _ = live_screen(args[0], cmd)
        print("\n".join(resolutions(mon) if cmd == "resolutions"
                        else scales_for(mon["width"], mon["height"], mon.get("scale"))))
    elif cmd == "filter" and len(args) == 1:
        cmd_filter(args[0])
    elif cmd == "anim" and len(args) == 1:
        cmd_anim(args[0])
    elif cmd == "accent" and len(args) == 1:
        cmd_accent(args[0])
    elif cmd == "theme" and len(args) == 1:
        # theme.py does the whole switch (and signals the bar itself).
        os.execv(sys.executable, [sys.executable, os.path.join(os.path.dirname(
            os.path.abspath(__file__)), "theme.py"), "set", args[0]])
    elif cmd == "themes":
        print("\n".join(n for n, _ in theme.themes()))
    elif cmd == "filters":
        print("\n".join(filters()))
    elif cmd == "presets":
        print("\n".join(PRESETS))
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)
    if cmd in ("hdr", "filter", "anim", "accent", "primary"):
        refresh_bar()


if __name__ == "__main__":
    main(sys.argv[1:])
