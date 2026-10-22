#!/usr/bin/env python3
"""Accessibility: the screen magnifier, the Orca screen reader, high contrast,
reduce motion, reduce transparency, visual alerts and the larger pointer. The
backend of the Settings window's "Accessibility" page, and usable from the
launcher's search bar and the keys the same way.

    accessibility.py status                    JSON: everything below, read back
                                               from where each one really lives
    accessibility.py zoom <factor>|in|out|reset   the magnifier around the pointer
                                               (1 = off, up to 10; in / out step
                                               by a quarter)
    accessibility.py reader on|off|toggle      Orca, the screen reader (speaks)
    accessibility.py contrast on|off|toggle    high contrast in GTK4 / libadwaita apps
    accessibility.py motion on|off|toggle      reduce motion: the "calm" animations,
                                               no moving wallpaper, its reactions off,
                                               no animations inside apps
    accessibility.py transparency on|off|toggle   reduce transparency: window glass
                                               0, no blur, unfocused windows opaque
    accessibility.py alerts on|off|toggle      visual alerts: theme sounds off, the
                                               screens flash for a notification instead
    accessibility.py alert                     what theme-sound.sh runs for a
                                               notification: a flash when visual
                                               alerts are on, nothing otherwise
    accessibility.py flash [<output>]          flash the screens once (all, or one)
    accessibility.py pointer <px>|default      pointer size (font-settings.py
                                               cursor-size; 24 is the default)
    accessibility.py login                     at login (lua/accessibility.lua):
                                               start Orca if it is switched on

Where each one lives -- nothing here is kept twice:
  * zoom: zoom=<factor> in ~/.local/state/hypr/accessibility.conf (this
    script's own key=value file, the format of lua/shared.lua), applied at
    every config load by lua/accessibility.lua -- so a reload, gamemode OFF
    and a re-login keep it -- and now through the same Lua:
        hyprctl eval 'require("lua.accessibility").apply()'
    Hyprland's cursor:zoom_factor magnifies the screen the pointer is on and
    follows the pointer.
  * reader / contrast / the apps' animations: GNOME's own gsettings keys
    (org.gnome.desktop.a11y.applications screen-reader-enabled,
    org.gnome.desktop.a11y.interface high-contrast, org.gnome.desktop.interface
    enable-animations and toolkit-accessibility), which apps read through the
    settings portal. Orca's own autostart entry is GNOME-only (OnlyShowIn), so
    `login` starts it here.
  * motion and transparency are made of other scripts' settings, each set
    through its own CLI: display.py anim, wallpaper-slideshow.py motion,
    wallpaper-motion.py react, theme.py glass, window-look.py set/unset. ON
    is read back from those (all of them at their accessible value), never
    from a flag of ours. What they were before is kept in accessibility.conf
    (before.*) only so that OFF can put exactly that back.
  * alerts: alerts=on in accessibility.conf plus theme-sound.sh off.

Sticky keys, slow keys and bounce keys do not exist in Hyprland 0.56: xkb's
AccessX lived in the X server, libxkbcommon does not implement it, and
Hyprland has no option for any of them (checked against its option list).
The GNOME keys (org.gnome.desktop.a11y.keyboard) are read by nothing here.
`status` says so, so the page can.

ACCESSIBILITY_DRYRUN=1 prints the commands that would change something
instead of running them (the tests and a careful first try use it).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
STATE = os.path.join(STATE_DIR, "accessibility.conf")
DISPLAY_STATE = os.path.join(STATE_DIR, "display.conf")       # display.py's; read only here

DISPLAY = os.path.join(HERE, "display.py")
THEME = os.path.join(HERE, "theme.py")
WINDOW_LOOK = os.path.join(HERE, "window-look.py")
FONTS = os.path.join(HERE, "font-settings.py")
SLIDESHOW = os.path.join(HERE, "wallpaper-slideshow.py")
MOTION = os.path.join(HERE, "wallpaper-motion.py")
THEME_SOUND = os.path.join(HERE, "theme-sound.sh")

ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 1.0, 10.0, 1.25
POINTER_DEFAULT = 24
FLASH_ALPHA, FLASH_MS = 0.35, 360          # how bright the flash starts, how long it fades
CALM = "calm"                               # lua/display.lua's motion-free preset

A11Y_APPS = "org.gnome.desktop.a11y.applications"
A11Y_IFACE = "org.gnome.desktop.a11y.interface"
IFACE = "org.gnome.desktop.interface"

DRYRUN = os.environ.get("ACCESSIBILITY_DRYRUN") == "1"


# -- the state file (key=value, sorted, written atomically) ----------------------------
def parse_kv(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def format_kv(values):
    return "".join(f"{k}={values[k]}\n" for k in sorted(values) if values[k] is not None)


def read_kv(path):
    try:
        with open(path) as handle:
            return parse_kv(handle.read())
    except OSError:
        return {}


def read_state():
    return read_kv(STATE)


def write_state(values):
    if DRYRUN:
        print(f"would write {STATE}: {values}")
        return
    if not values:
        # Nothing chosen: no file, which is the same as every default.
        try:
            os.remove(STATE)
        except FileNotFoundError:
            pass
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = f"{STATE}.tmp.{os.getpid()}"
    with open(tmp, "w") as handle:
        handle.write("# Settings > Accessibility (scripts/accessibility.py); read by lua/accessibility.lua\n")
        handle.write(format_kv(values))
    os.replace(tmp, STATE)


# -- running things ---------------------------------------------------------------------
def run(*cmd, timeout=15):
    """stdout of a read-only command, "" when it could not run."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def change(*cmd, timeout=30):
    """A command that changes something: "" when it worked, else its last
    stderr line. Dry run: only print it."""
    if DRYRUN:
        print("would run:", " ".join(cmd))
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def spawn(*cmd):
    if DRYRUN:
        print("would start:", " ".join(cmd))
        return
    subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def gget(schema, key):
    """A gsettings boolean; None when the schema is not installed."""
    out = run("gsettings", "get", schema, key)
    return {"true": True, "false": False}.get(out)


def gset(schema, key, value):
    return change("gsettings", "set", schema, key, "true" if value else "false")


def as_json(text):
    try:
        return json.loads(text or "null")
    except ValueError:
        return None


def fail(message):
    sys.exit(f"accessibility: {message}")


def onoff(arg, current):
    """on / off / toggle -> bool, or fail."""
    if arg == "toggle":
        return not current
    if arg in ("on", "off"):
        return arg == "on"
    fail(f"expected on, off or toggle, not {arg!r}")


# -- the magnifier ----------------------------------------------------------------------
def clamp_zoom(value):
    return round(min(ZOOM_MAX, max(ZOOM_MIN, value)), 2)


def next_zoom(current, arg):
    """The factor `zoom <arg>` leads to from `current`. in / out step by a
    quarter (x1.25), so each press feels the same at 1.5 as at 6; out snaps
    to 1 (off) rather than stopping at 1.02."""
    if arg == "reset":
        return ZOOM_MIN
    if arg == "in":
        return clamp_zoom(current * ZOOM_STEP)
    if arg == "out":
        new = current / ZOOM_STEP
        return ZOOM_MIN if new < 1.1 else clamp_zoom(new)
    try:
        value = float(arg.rstrip("x%"))
    except ValueError:
        fail(f"zoom: a factor 1-{ZOOM_MAX:g}, in, out or reset, not {arg!r}")
    if arg.endswith("%"):
        value /= 100
    return clamp_zoom(value)


def saved_zoom(state):
    try:
        return clamp_zoom(float(state.get("zoom", "1")))
    except ValueError:
        return ZOOM_MIN


def live_zoom():
    out = run("hyprctl", "getoption", "cursor:zoom_factor", "-j", timeout=3)
    data = as_json(out) or {}
    return data.get("float")


MODS = [(64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT")]
KEY_NAMES = {"equal": "=", "minus": "-", "plus": "+", "kp_add": "keypad +", "kp_subtract": "keypad -",
             "mouse_up": "scroll up", "mouse_down": "scroll down"}
ZOOM_WHAT = [("zoom in", "zooms in"), ("zoom out", "zooms out"), ("zoom off", "turns zoom off"),
             ("zoom reset", "turns zoom off")]


def zoom_binds(binds):
    """[{keys, what}] for every bind (hyprctl binds -j) whose description
    names a zoom ("Accessibility: Zoom in" / "Zoom out" / "Zoom off", as
    lua/binds.lua describes them), so the page names the keys as they really
    are. By description because a Lua bind's arg is only a function id."""
    found = []
    for b in binds or []:
        desc = str(b.get("description", "")).lower()
        what = next((said for words, said in ZOOM_WHAT if words in desc), None)
        if not what:
            continue
        mods = [name for bit, name in MODS if b.get("modmask", 0) & bit]
        key = str(b.get("key", ""))
        found.append({"keys": " + ".join(mods + [KEY_NAMES.get(key.lower(), key)]), "what": what})
    return found


def apply_lua():
    return change("hyprctl", "eval", 'require("lua.accessibility").apply()', timeout=5)


def cmd_zoom(arg):
    state = read_state()
    new = next_zoom(saved_zoom(state), arg)
    if new == ZOOM_MIN:
        state.pop("zoom", None)
    else:
        state["zoom"] = f"{new:g}"
    write_state(state)
    err = apply_lua()
    if err:
        fail(f"saved, but Hyprland did not take it: {err}")
    print(f"{new:g}")


# -- the screen reader ------------------------------------------------------------------
def orca_running():
    return bool(run("pgrep", "-x", "orca", timeout=3))


def stop_orca(wait=2.0):
    """Ask Orca to quit, and make sure it did. Orca catches SIGTERM but does
    not always act on it (seen here: still running after a plain pkill), so
    after `wait` seconds it is killed outright -- the switch saying off while
    Orca keeps talking would be worse."""
    err = change("pkill", "-x", "orca")
    if err or DRYRUN:
        return err
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not orca_running():
            return ""
        time.sleep(0.1)
    change("pkill", "-KILL", "-x", "orca")
    time.sleep(0.2)
    return "Orca would not stop" if orca_running() else ""


def cmd_reader(arg):
    want = onoff(arg, bool(gget(A11Y_APPS, "screen-reader-enabled")))
    if want and not shutil.which("orca"):
        fail("Orca is not installed: sudo dnf install orca")
    state = read_state()
    errors = []
    if want:
        # Apps only expose their contents to a screen reader when asked to:
        # GTK3 and Chromium-based ones look at toolkit-accessibility. What it
        # was before is kept so that turning the reader off puts it back.
        if "before.toolkit" not in state:
            state["before.toolkit"] = "on" if gget(IFACE, "toolkit-accessibility") else "off"
            write_state(state)
        errors += [gset(IFACE, "toolkit-accessibility", True), gset(A11Y_APPS, "screen-reader-enabled", True)]
        if not orca_running():
            spawn("orca", "--replace")
    else:
        errors.append(gset(A11Y_APPS, "screen-reader-enabled", False))
        if "before.toolkit" in state:
            errors.append(gset(IFACE, "toolkit-accessibility", state.pop("before.toolkit") == "on"))
            write_state(state)
        if orca_running():
            errors.append(stop_orca())
    errors = [e for e in errors if e]
    if errors:
        fail(errors[0])
    print("on" if want else "off")


def cmd_login():
    """Orca's autostart entry is for GNOME and friends only, so the reader
    switch would otherwise not survive a re-login."""
    if gget(A11Y_APPS, "screen-reader-enabled") and shutil.which("orca") and not orca_running():
        spawn("orca", "--replace")


# -- reduce motion ----------------------------------------------------------------------
def motion_parts():
    """What reduce motion is made of, as it is now."""
    disp = as_json(run(DISPLAY, "status")) or {}
    react = as_json(run(MOTION, "react", "status")) or {}
    wall = as_json(run(SLIDESHOW, "motion")) or {}
    return {"anim": disp.get("anim"), "wallpaper": wall.get("on"), "react": react.get("on"),
            "apps": gget(IFACE, "enable-animations")}


def motion_reduced(parts):
    """On when every part is at its still value; a part that could not be
    read (None) does not count against it."""
    return (parts.get("anim") in (CALM, None) and parts.get("wallpaper") is not True
            and parts.get("react") is not True and parts.get("apps") is not True)


def motion_plan(want, parts, state):
    """(commands, new state) for reduce motion ON (want) or OFF. ON keeps what
    each part was in before.* the first time; OFF puts those back (or the
    desktop's defaults when nothing was kept: smooth, moving wallpaper and
    reactions on, apps animated)."""
    state = dict(state)
    cmds = []
    if want:
        for key, value in (("anim", parts.get("anim")), ("wallpaper", parts.get("wallpaper")),
                           ("react", parts.get("react")), ("apps", parts.get("apps"))):
            if f"before.{key}" not in state and value is not None:
                state[f"before.{key}"] = value if key == "anim" else ("on" if value else "off")
        if parts.get("anim") != CALM:
            cmds.append([DISPLAY, "anim", CALM])
        if parts.get("wallpaper"):
            cmds.append([SLIDESHOW, "motion", "off"])
        if parts.get("react"):
            cmds.append([MOTION, "react", "off"])
        if parts.get("apps"):
            cmds.append(["gsettings", "set", IFACE, "enable-animations", "false"])
    else:
        anim = state.pop("before.anim", "smooth")
        anim = "smooth" if anim == CALM else anim
        wall = state.pop("before.wallpaper", "on") == "on"
        react = state.pop("before.react", "on") == "on"
        apps = state.pop("before.apps", "on") == "on"
        if parts.get("anim") == CALM:
            cmds.append([DISPLAY, "anim", anim])
        if wall and parts.get("wallpaper") is False:
            cmds.append([SLIDESHOW, "motion", "on"])
        if react and parts.get("react") is False:
            cmds.append([MOTION, "react", "on"])
        if apps and parts.get("apps") is False:
            cmds.append(["gsettings", "set", IFACE, "enable-animations", "true"])
    return cmds, state


# -- reduce transparency ----------------------------------------------------------------
def look_keys():
    data = as_json(run(WINDOW_LOOK, "status")) or {}
    return {k["key"]: k for k in data.get("keys", []) if k.get("key") in ("blur", "inactive_opacity")}


def transparency_parts():
    glass = as_json(run(THEME, "glass")) or {}
    keys = look_keys()
    theme = glass.get("theme")
    own = read_kv(DISPLAY_STATE).get(f"glass_{theme}") if theme else None
    return {"theme": theme, "glass": glass.get("glass"), "glass_default": glass.get("default"),
            "glass_own": own,
            "blur": (keys.get("blur") or {}).get("value"),
            "blur_own": (keys.get("blur") or {}).get("override") or "",
            "inactive_opacity": (keys.get("inactive_opacity") or {}).get("value"),
            "inactive_own": (keys.get("inactive_opacity") or {}).get("override") or ""}


def opaque(value):
    try:
        return float(value) >= 1.0
    except (TypeError, ValueError):
        return True


def transparency_reduced(parts):
    return parts.get("glass") == 0 and parts.get("blur") in ("no", None) and opaque(parts.get("inactive_opacity"))


def transparency_plan(want, parts, state):
    """(commands, new state), like motion_plan. "Before" is what YOU had
    set: a number for the glass or "default" (the theme's own), and the
    window-look override or "" (the theme's, so OFF unsets it rather than
    pinning today's theme value)."""
    state = dict(state)
    cmds = []
    if want:
        if "before.glass" not in state:
            state["before.glass"] = parts.get("glass_own") or "default"
            state["before.glass_theme"] = parts.get("theme") or ""
            state["before.blur"] = parts.get("blur_own") or ""
            state["before.inactive_opacity"] = parts.get("inactive_own") or ""
        if parts.get("glass") != 0:
            cmds.append([THEME, "glass", "0"])
        if parts.get("blur") != "no":
            cmds.append([WINDOW_LOOK, "set", "blur", "no"])
        if not opaque(parts.get("inactive_opacity")):
            cmds.append([WINDOW_LOOK, "set", "inactive_opacity", "1.0"])
    else:
        glass = state.pop("before.glass", "default")
        glass_theme = state.pop("before.glass_theme", "")
        blur = state.pop("before.blur", "")
        inactive = state.pop("before.inactive_opacity", "")
        # The glass is per theme: after a theme switch the kept number belongs
        # to another theme, so this one goes back to its own default.
        if glass_theme and glass_theme != parts.get("theme"):
            glass = "default"
        if parts.get("glass") == 0:
            cmds.append([THEME, "glass", glass])
        if parts.get("blur") == "no":
            cmds.append([WINDOW_LOOK, "set", "blur", blur] if blur else [WINDOW_LOOK, "unset", "blur"])
        # Only when it is still the 1.0 ON pinned (an opacity you chose since stays).
        own = parts.get("inactive_own")
        if own and opaque(own) and own != inactive:
            cmds.append([WINDOW_LOOK, "set", "inactive_opacity", inactive] if inactive
                        else [WINDOW_LOOK, "unset", "inactive_opacity"])
    return cmds, state


def run_plan(cmds, state):
    """Keep the "before" values first (so a failure half way can still be
    undone), then each command; the first complaint, or ""."""
    write_state(state)
    for cmd in cmds:
        err = change(*cmd)
        if err:
            return err
    return ""


def cmd_motion(arg):
    parts = motion_parts()
    want = onoff(arg, motion_reduced(parts))
    err = run_plan(*motion_plan(want, parts, read_state()))
    if err:
        fail(err)
    print("on" if want else "off")


def cmd_transparency(arg):
    parts = transparency_parts()
    want = onoff(arg, transparency_reduced(parts))
    err = run_plan(*transparency_plan(want, parts, read_state()))
    if err:
        fail(err)
    print("on" if want else "off")


# -- visual alerts ----------------------------------------------------------------------
def alerts_wired(text):
    """Whether theme-sound.sh hands notifications to `accessibility.py
    alert` (its notify branch has to, since mako only runs that script)."""
    return any("accessibility.py" in line and "alert" in line and not line.lstrip().startswith("#")
               for line in text.splitlines())


def theme_sound_text():
    try:
        with open(THEME_SOUND) as handle:
            return handle.read()
    except OSError:
        return ""


def cmd_alerts(arg):
    state = read_state()
    want = onoff(arg, state.get("alerts") == "on")
    if want:
        if "before.sounds" not in state:
            state["before.sounds"] = run(THEME_SOUND, "status") or "on"
        state["alerts"] = "on"
    else:
        state.pop("alerts", None)
    sounds = "off" if want else state.pop("before.sounds", "on")
    write_state(state)
    err = change(THEME_SOUND, sounds)
    if err:
        fail(err)
    print("on" if want else "off")


def cmd_alert():
    if read_state().get("alerts") == "on":
        spawn(sys.executable, os.path.abspath(__file__), "flash")


def flash(output=None):
    """A white veil over every screen (or one), fading out in FLASH_MS: an
    OVERLAY layer surface that takes no input and no focus, so it can never
    eat a click or a key. lua/accessibility.lua turns the layer animation off
    for it, so the fade is this one."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    import cairo
    from gi.repository import GLib, Gtk, GtkLayerShell

    display = Gtk.Window().get_display()
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    if output:
        mons = as_json(run("hyprctl", "monitors", "-j", timeout=3)) or []
        want = next((m for m in mons if m.get("name") == output), None)
        if want is None:
            fail(f"no output {output!r}")
        # GDK names monitors by model, not connector: match by position, as
        # wallpaper-motion.py and launcher.py do.
        monitors = [m for m in monitors if (m.get_geometry().x, m.get_geometry().y) == (want["x"], want["y"])]
    start = GLib.get_monotonic_time()
    windows = []

    def draw(_area, cr):
        t = (GLib.get_monotonic_time() - start) / 1000 / FLASH_MS
        cr.set_source_rgba(1, 1, 1, max(0.0, FLASH_ALPHA * (1 - t)))
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        return False

    for mon in monitors:
        win = Gtk.Window()
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "a11y-flash")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(win, mon)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_exclusive_zone(win, -1)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        win.set_app_paintable(True)
        area = Gtk.DrawingArea()
        area.connect("draw", draw)
        win.add(area)
        win.connect("realize", lambda w: w.input_shape_combine_region(cairo.Region()))
        win.show_all()
        windows.append(area)

    def tick():
        for area in windows:
            area.queue_draw()
        if GLib.get_monotonic_time() - start > FLASH_MS * 1000:
            Gtk.main_quit()
            return False
        return True

    GLib.timeout_add(16, tick)
    GLib.timeout_add(FLASH_MS * 4, Gtk.main_quit)       # never outlive a stalled frame
    Gtk.main()


# -- the pointer ------------------------------------------------------------------------
def cmd_pointer(arg):
    size = str(POINTER_DEFAULT) if arg == "default" else arg
    if not size.isdigit() or not 8 <= int(size) <= 256:
        fail("pointer: a size in pixels, 8-256, or default")
    err = change(FONTS, "cursor-size", size)
    if err:
        fail(err)
    print(size)


# -- status -----------------------------------------------------------------------------
KEYS_NOTE = ("Hyprland 0.56 has no sticky keys, slow keys or bounce keys: they were AccessX, a feature of "
             "the X server that libxkbcommon (what Wayland compositors use) never took over, and Hyprland "
             "has no option for them.")


def status():
    state = read_state()
    with ThreadPoolExecutor(max_workers=8) as pool:
        motion = pool.submit(motion_parts)
        transp = pool.submit(transparency_parts)
        fonts = pool.submit(lambda: as_json(run(FONTS, "status")) or {})
        disp = pool.submit(lambda: as_json(run(DISPLAY, "status")) or {})
        zoom_live = pool.submit(live_zoom)
        binds = pool.submit(lambda: as_json(run("hyprctl", "binds", "-j", timeout=3)))
        reader = pool.submit(lambda: (gget(A11Y_APPS, "screen-reader-enabled"), orca_running(),
                                      gget(IFACE, "toolkit-accessibility")))
        contrast = pool.submit(gget, A11Y_IFACE, "high-contrast")
        sounds = pool.submit(run, THEME_SOUND, "status")
    m, t, f, d = motion.result(), transp.result(), fonts.result(), disp.result()
    enabled, running, toolkit = reader.result()
    filt = d.get("filter") or ""
    labels = {x.get("name"): x.get("label") for x in d.get("filters", [])}
    cursor = f.get("cursor") or {}
    return {
        "zoom": {"factor": saved_zoom(state), "live": zoom_live.result(), "min": ZOOM_MIN, "max": ZOOM_MAX,
                 "keys": zoom_binds(binds.result())},
        "reader": {"installed": bool(shutil.which("orca")), "enabled": bool(enabled), "running": running,
                   "toolkit": toolkit},
        "contrast": contrast.result(),
        "motion": {"on": motion_reduced(m), **m},
        "transparency": {"on": transparency_reduced(t), **t},
        "alerts": {"on": state.get("alerts") == "on", "sounds": sounds.result() or "on",
                   "wired": alerts_wired(theme_sound_text())},
        "pointer": {"size": cursor.get("size"), "theme": cursor.get("now")},
        "text_scale": f.get("scale"),
        "filter": {"name": filt, "label": labels.get(filt, filt)},
        "keys": {"sticky": False, "slow": False, "bounce": False, "note": KEYS_NOTE},
    }


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    simple = {"zoom": cmd_zoom, "reader": cmd_reader, "motion": cmd_motion, "transparency": cmd_transparency,
              "alerts": cmd_alerts, "pointer": cmd_pointer}
    if cmd == "status":
        print(json.dumps(status()))
    elif cmd in simple and len(args) == 1:
        simple[cmd](args[0])
    elif cmd == "contrast" and len(args) == 1:
        want = onoff(args[0], bool(gget(A11Y_IFACE, "high-contrast")))
        err = gset(A11Y_IFACE, "high-contrast", want)
        if err:
            fail(err)
        print("on" if want else "off")
    elif cmd == "alert" and not args:
        cmd_alert()
    elif cmd == "flash" and len(args) <= 1:
        flash(args[0] if args else None)
    elif cmd == "login" and not args:
        cmd_login()
    else:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
