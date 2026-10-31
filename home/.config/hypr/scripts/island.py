#!/usr/bin/env python3
"""Dynamic island: a pill at the top centre of the main screen that shows up
when something happens -- the track that started playing (play / pause,
next), a timer in its last minute or ringing (Snooze / Stop), a screen
recording (a red dot and the time, Stop), Railguard's alerts with the
theme's mascot and -- "notifications", on by default -- every desktop
notification instead of mako's popups; and is gone again when nothing
does. Mako stays the notification server: the island never takes
org.freedesktop.Notifications, it only draws what mako keeps.

    island.py daemon                 run the island (island.service); exits
                                     at once when it is switched off
    island.py status [--json]        settings, service state, monitors
    island.py set KEY VALUE          one setting (below); on|off for switches
    island.py set on|off             = set enabled on|off: enables and starts,
                                     or stops and disables, island.service
    island.py test [notify|railguard]  a sample event, to check the look (notify:
                                     a real notification while notifications are on)

SETTINGS ($XDG_STATE_HOME/hypr/island.json; Settings > Bar & toolbox > Island):

    enabled     the island at all (false: the service is stopped, the
                desktop is exactly as without it)
    monitor     "" the main screen (screens.py's primary, the one with the
                bar), "focused" the focused one, or a connector ("DP-2");
                "auto" is "". A screen that is not there is the main one
    media, timers, record, railguard
                each source on / off (true)
    notifications
                every notification, from any app, shows in the island
                instead of a mako popup (true; NOTIFICATIONS below)
    notify      only with notifications off: a short line for each one
                sent through scripts/notify (false); mako shows them all
    style       its shape: "notch" (square on top where it meets the screen
                edge; the default), "island" (a capsule floating just under
                the edge) or "theme" (the desktop theme's panel card). The
                old "glass" and "outline" designs read as a notch with that
                colour / outline
    notch_color the notch's and the island's fill: "black" (the default),
                "theme" -- the desktop theme's accent (generated/accent.css,
                so a wallpaper-following accent too), darkened as far as it
                takes for the island's light text to read on it -- or
                "glass" (dark and see-through, with a faint frosted edge)
    outline     a 1 px edge in the theme's lit colour, on any design (false)
    match_bar   the bar's centre capsules (date, clock, weather, updates ...)
                take the island's design and width, so the island opens out
                of them, macOS-like (true); written as
                ~/.config/waybar/generated/island-bar.css, which style.css
                imports last (an empty one when off, or for "theme")
                With the top bar off (dock.py TOP BAR OFF) there is no centre
                to match: the daemon runs as if match_bar were off
                (effective), and the island keeps its own width.
    ongoing     keep the pill in the bar while music plays, a recording runs
                or a timer is in its last minute (false: it covers the bar's
                clock while it stays); off, it shows only when something
                changes and goes back up after a few seconds

WHERE IT ALL COMES FROM -- nothing polls; idle, the window is unmapped and
the process sleeps in the GLib loop:

    media       Playerctl (MPRIS), the player the bar follows
                ($XDG_RUNTIME_DIR/waybar-player/selected) or a playing one,
                mpv and vlc before a browser; playerctld is skipped
    timers      timers.json (a directory monitor: it is written by rename)
                and the ring files in $XDG_RUNTIME_DIR/hypr-timers/, read
                through timers.py; one wake-up when the next one enters its
                last minute
    recording   $XDG_RUNTIME_DIR/gsr-record.pid (record.sh), alive while its
                process is gpu-screen-recorder; its mtime is the start
    railguard   pushed by railguard.py and scripts/notify through
    notify      island_events.py: one datagram each on
                $XDG_RUNTIME_DIR/island.sock (gone while the island is off,
                so the senders return at once)
    notifications
                a D-Bus monitor on the session bus (below)

NOTIFICATIONS (island_notify.py has the pure half: the queue, timing,
what mako would have hidden, the Railguard twin):

  Where they come from: a second, dedicated session-bus connection that
  calls org.freedesktop.DBus.Monitoring.BecomeMonitor for the Notify calls,
  mako's replies to them (the id; matched by the caller and serial),
  NotificationClosed, and makoctl's mode / reload calls (Do Not Disturb
  going on or off: what is queued is looked at again, as mako re-reads its
  rules then). Who owns org.freedesktop.Notifications is watched on the
  ordinary connection: monitors are not told.
  Chosen over mako's on-notify hook + `makoctl list -j`: the hook is one
  setting that the sections, Do Not Disturb, project-focus and the theme
  sound all set already (a second user would fight them), it starts a
  process per notification, and the list has no expire timeout and no
  picture; the monitor sees every Notify as it happens, with its hints
  (urgency, image-path, image-data), costs nothing while idle and needs no
  polling. A monitor never sends: its filter drops every message before
  GDBus could answer one (the bus would cut it off).

  Popups: once the monitor is up, `makoctl mode -a island` (mako/island:
  invisible=1, default-timeout=0) hides mako's popups; mako still numbers,
  keeps (`makoctl list`), sounds and records (history, the bell) every
  one, and runs its actions. The mode goes again (`makoctl mode -r
  island`) when the setting goes off, the monitor is lost, the daemon
  quits -- and from island.service's ExecStopPost, after a crash too;
  WatchdogSec there ends a hung island the same way. A new mako (a
  restart) starts without the mode: the name watch adds it again. Modes
  are only ever added and removed, never set, so Do Not Disturb and
  project-focus stay as they are.

  What shows: what mako would have drawn (its own invisible= rules for
  the current modes, read from its config: Do Not Disturb holds them back,
  urgent ones break through as Settings > Notifications says), one at a
  time: critical first (dropped below the bar, until dismissed -- it
  steps aside for the waiting after STICKY_HOLD_S and comes back), then
  oldest first, each for its urgency's timeout (Settings > Notifications;
  an app's own expire timeout unless ignored), shorter while others wait
  ("+N"). Low ones stay a compact line. Hovering opens the card (icon or
  picture, app, summary, the body over several lines, the action buttons,
  "Go to <app>" / "Open <app>", dismiss) and stops the clock. Clicking it
  takes you to the sender's window (notify_source.py: by the caller's pid,
  learnt from the bus as it calls, else by name), then runs the default
  action like mako's popup did -- or, with none, closes it. Done ones are dismissed into mako's
  history (`makoctl dismiss -n ID`).

  Twins: Railguard's alert and its notification are one card (the
  notification, critical, with the mascot); scripts/notify's datagram is
  ignored while this is on (the bus brings the notification itself).

It hides in a fullscreen window (the island screen's workspace has one) and
while a game runs (a steam_app_* window, or a process with Steam's, Proton's,
Lutris' or Heroic's variables) -- except for notifications, which mako's
popups showed over both too (Settings > Notifications' "Do Not Disturb in
games" keeps a game quiet).

Like a notch, not a window: it hangs from the top edge of the screen inside
the bar's strip (over the bar's centre capsule while it shows, never under
the bar), so the compact pill never covers a window. Only an alert
(Railguard, a ringing timer) or the pointer on it drops it down below the
bar, and leaving it takes it back up. Layer OVERLAY, exclusive zone -1.

Clicks: left drops it down (on the dropped-down track: play / pause; on an
alert: gone; on a notification: its default action, else dismiss), middle
dismisses what shows, right opens Settings > Island. The card is the popup panels' (panel.css through panelui, in the
theme); ISLAND_CSS below adds the pill shape. lua/rules.lua frosts the
waybar-island layer (waybar-glass) and slides it in from the top.
"""
import json
import math
import os
import re
import socket
import stat
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import island_notify  # noqa: E402  (the notifications' pure half, stdlib only)
import notify_source  # noqa: E402  (where a notification came from: Go to / Open)
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
SOCK = os.path.join(RUNTIME, "island.sock")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
SETTINGS_FILE = os.path.join(STATE_DIR, "island.json")
DEFAULTS = {"enabled": False, "monitor": "", "media": True, "timers": True, "record": True,
            "railguard": True, "notifications": True, "notify": False, "ongoing": False,
            "style": "notch", "notch_color": "black", "outline": False, "match_bar": True}
STYLES = ("notch", "island", "theme")
SHAPES = ("notch", "island")   # ours: notch_color fills them, light text, the bar takes them
OLD_STYLES = {"glass": {"notch_color": "glass"}, "outline": {"outline": True}}   # now a notch with
NOTCH_COLORS = ("black", "theme", "glass")
BOOL_KEYS = tuple(k for k, v in DEFAULTS.items() if isinstance(v, bool))
MONITOR_NAME = re.compile(r"^[A-Za-z0-9-]{1,32}$")
TRUE_WORDS = ("on", "true", "1", "yes")
FALSE_WORDS = ("off", "false", "0", "no")
UNIT = "island.service"
NAMESPACE = "waybar-island"
LIMIT = 300                   # the longest string an event may carry

REC_PID = os.path.join(RUNTIME, "gsr-record.pid")
PROC = "/proc"
RING_DIR = os.path.join(RUNTIME, "hypr-timers")
TIMERS_FILE = "timers.json"
GEN_DIR = os.path.expanduser("~/.config/waybar/generated")
THEME_FILES = ("theme-panel.css", "accent.css")
ACCENT_CSS = os.path.join(GEN_DIR, "accent.css")
BLACK = "#000000"
GLASS = "alpha(#0b0b10, 0.62)"
FROST = "alpha(#ffffff, 0.14)"   # glass's own faint edge
LIT_EDGE = "@edge-lit"           # outline: the theme's lit edge (panel.css)
BAR_CSS = os.path.join(GEN_DIR, "island-bar.css")
BAR_CENTRE = ("#custom-day", "#custom-clock", "#custom-weather", "#custom-updates",
              "#custom-repos", "#custom-notifications")
GAME_ENV = (b"SteamAppId=", b"STEAM_COMPAT_APP_ID=", b"LUTRIS_GAME_UUID=", b"HEROIC_APP_NAME=")
STEAM_CLASS = re.compile(r"steam_app_\d+$")
SKIP_PLAYERS = ("playerctld",)
PREFER_PLAYERS = ("mpv", "vlc")
SELECTED = os.path.join(RUNTIME, "waybar-player", "selected")

# How long each thing shows expanded (ms), and the rest of the timing.
MEDIA_MS = 4000               # a new track, or play <-> pause
RAILGUARD_MS = 8000
NOTIFY_MS = 5000
RECORD_START_MS = 2500        # a recording that just started
RECORD_SAVED_MS = 2500        # "Recording saved" (or "stopped") after it stops
RECORD_MIN_S = 2              # shorter than this is a recorder that failed to start
TIMER_ENTER_MS = 3000         # a timer entering its last minute
TIMER_DONE_MS = 3000          # "<label> done": it left without ringing (`then`)
HOVER_LEAVE_MS = 600
SETTINGS_DEBOUNCE_MS = 100
FS_DEBOUNCE_MS = 150
THEME_DEBOUNCE_MS = 250
RECORD_RETRY_MS = 700         # the pid file can land before setsid's exec
ANIM_MS = 180
TIMER_WINDOW_S = 60
TIMER_RECHECK_S = 300         # the longest timer wait (suspend does not count)
RECONNECT_S = 2
HYPR_EVENTS = ("fullscreen", "workspacev2", "focusedmonv2", "activewindowv2", "movewindowv2",
               "openwindow", "closewindow", "monitoraddedv2", "monitorremoved")    # what on_hypr reads
POP_MS = 700                  # a new notification's pop (the island-pop animation)
PENDING_S = 10                # a Notify call waits this long for mako's reply (the id)
CALLER_PIDS_MAX = 256         # bus names remembered (their process chains); then start over
PID_ASK_MS = 250              # the bus's answer to "whose is this name", at most
IMAGE_MAX = 4 << 20           # image-data bigger than this is not decoded (bytes)

# Notifications (NOTIFICATIONS in the docstring)
MAKO_MODE = "island"          # mako/island: [mode=island] invisible=1
MAKO_CONFIG = "~/.config/mako/config"
NOTIFY_CONF = os.path.join(STATE_DIR, "notifications.json")    # Settings > Notifications
NOTIFY_SCRIPT = os.path.join(HERE, "notify")
NOTIF_NAME = "org.freedesktop.Notifications"
NOTIF_PATH = "/org/freedesktop/Notifications"
MAKO_IFACE = "fr.emersion.Mako"
MAKO_MODE_CALLS = ("SetMode", "SetModes", "Reload")
MODES_SETTLE_MS = 250         # after makoctl mode / reload, before reading the modes again

PRIORITY = ("record", "railguard", "timers", "notify", "media")
MOODS = ("calm", "alert", "relieved")

# Font Awesome 6 codepoints as escapes, like the bar scripts.
REC_DOT = "\uf111"            # circle
STOP_ICON = "\uf04d"          # stop
SAVED_ICON = "\uf00c"         # check
SNOOZE_ICON = "\uf017"        # clock
PLAY_ICON = "\uf04b"
PAUSE_ICON = "\uf04c"
NEXT_ICON = "\uf051"
SHIELD_ICON = "\uf3ed"        # shield-halved: Railguard
BELL_ICON = "\uf0f3"
CRITICAL_ICON = "\uf071"      # triangle-exclamation: a critical notification
CLOSE_ICON = "\uf00d"         # xmark: dismiss
TIMER_ICON = "\uf252"         # hourglass-half, when timers.py has none for the kind
MUSIC_ICON = "\uf001"
PLAYER_ICONS = {"mpv": "\uf008", "firefox": "\uf269", "spotify": "\uf1bc", "vlc": "\uf03d",
                "chromium": "\uf268", "chrome": "\uf268"}      # waybar/scripts/player.py's


# -- settings ------------------------------------------------------------------------------
def bool_value(text):
    if isinstance(text, bool):
        return text
    word = str(text).strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ValueError(text)


def read_settings():
    cur = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    old = None
    for k, v in (data if isinstance(data, dict) else {}).items():
        if k not in DEFAULTS:
            continue
        if k in BOOL_KEYS:
            if isinstance(v, (bool, int, float)):
                cur[k] = bool(v)
            elif isinstance(v, str):
                try:
                    cur[k] = bool_value(v)
                except ValueError:
                    pass
        elif k == "style":
            if isinstance(v, str) and v.strip() in STYLES:
                cur[k] = v.strip()
            elif isinstance(v, str) and v.strip() in OLD_STYLES:
                old = v.strip()
        elif k == "notch_color":
            if isinstance(v, str) and v.strip() in NOTCH_COLORS:
                cur[k] = v.strip()
        elif isinstance(v, str):
            cur[k] = v.strip()[:32]
    if old:                     # an island.json from before: what it meant
        cur["style"] = "notch"
        cur.update(OLD_STYLES[old])
    return cur


def write_settings(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = f"{SETTINGS_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump({k: d.get(k, DEFAULTS[k]) for k in DEFAULTS}, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, SETTINGS_FILE)


# -- the notch's colour (notch_color) ---------------------------------------------------------
ACCENT_LINE = re.compile(r"@define-color\s+cyan\s+(#[0-9a-fA-F]{6})\s*;")
TEXT_HI = (0xf4, 0xf4, 0xf6)  # the island's text (ISLAND_CSS, bar_css) ...
TEXT_LO = (0xa1, 0xa1, 0xaa)  # ... and its second line
MIN_HI, MIN_LO = 4.5, 3.0     # contrast each needs on the fill (WCAG AA, and AA-large)


def accent_hex(text):
    """The accent in an accent.css (theme.py / theme-from-wallpaper.py write
    `@define-color cyan #rrggbb;`; the last one wins, as in GTK), or None."""
    found = ACCENT_LINE.findall(text or "")
    return found[-1].lower() if found else None


def theme_accent(path=None):
    try:
        with open(path or ACCENT_CSS) as fh:
            return accent_hex(fh.read())
    except OSError:
        return None


def rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(hexcolor):
    """The colour, darkened toward black in 4% steps until the island's light
    text reads on it (MIN_HI / MIN_LO): a light accent (moe's pink, orchard's
    blue) keeps its hue and goes deep enough for white text."""
    c = rgb(hexcolor)
    for _ in range(26):
        if contrast(c, TEXT_HI) >= MIN_HI and contrast(c, TEXT_LO) >= MIN_LO:
            break
        c = tuple(int(v * 0.96) for v in c)
    return "#%02x%02x%02x" % c


def notch_fill(cfg, accent=None):
    """The fill of the notch and island designs: black, glass, or with
    notch_color "theme" the accent made readable (black when there is no
    accent to read)."""
    color = cfg.get("notch_color")
    if cfg.get("style") not in SHAPES or color == "black":
        return BLACK
    if color == "glass":
        return GLASS
    return readable(accent) if color == "theme" and accent else BLACK


def edge(cfg):
    """The 1 px edge round the design: the theme's lit one (outline), glass's
    frost, or None."""
    if cfg.get("outline"):
        return LIT_EDGE
    if cfg.get("style") in SHAPES and cfg.get("notch_color") == "glass":
        return FROST
    return None


def fill_css(cfg, accent=None):
    """The island's fill and edge, on top of ISLAND_CSS (which has the
    shapes): the notch and the theme's card hang from the screen edge, so
    no edge on top."""
    style = cfg.get("style")
    lines = []
    if style in SHAPES:
        lines.append(f"background-color: {notch_fill(cfg, accent)};")
    line = edge(cfg)
    lines.append(f"border: 1px solid {line};" if line else "border-color: transparent;")
    if style != "island":
        lines.append("border-top-width: 0;")
    return ("\n#panel.island.island-style-%s {\n    %s\n}\n" % (style, "\n    ".join(lines)))


def bar_look(cfg, accent=None):
    """The bar's centre group as the design: the same fill and edge as the
    island (fill_css). Its measured row (measure_spec) must be one known
    colour: the notch's top edge is the fill, or black under glass; the
    glass capsule gets a black inner line under its top edge."""
    fill = notch_fill(cfg, accent)
    line = edge(cfg)
    if cfg.get("style") == "island":
        out = [f"background-color: {fill};", "border-radius: 999px;", "margin: 4px 0 4px 0;"]
        if line:
            out.append(f"border: 1px solid {line};")
        if fill == GLASS:
            out.append(f"box-shadow: inset 0 1px 0 0 {BLACK};")
        return out
    out = [f"background-color: {fill};", "border-radius: 0 0 16px 16px;"]
    if line:
        top = BLACK if fill == GLASS else fill
        out += [f"border: 1px solid {line};", f"border-top: 1px solid {top};"]
    return out


def measure_spec(cfg, accent=None):
    """Where measure_notch reads the notch's width (bar_look): (the row
    under the screen's top edge, the colour of the run through the middle,
    px the run is short of the full width at each end -- the capsule's round
    ends above the row)."""
    fill = notch_fill(cfg, accent)
    if cfg.get("style") == "island":
        # the ends: measured on screen against the notch's width
        if fill == GLASS:           # always edged: its black inner line is the row under it
            return 5, BLACK, 13
        return (6, fill, 9) if edge(cfg) else (5, fill, 10)
    return 0, (BLACK if fill == GLASS else fill), 0


def bar_css(cfg, slot=False, accent=None):
    """The stylesheet for the bar's centre group: the island's design and
    width, or only a comment (off, match_bar off, the "theme" design -- the
    capsules are the theme's already). The capsules' state fills (updates
    piling up, a dirty repo, the UTC clock ...) become coloured text. The
    group keeps its natural width; `slot` (the media is tucked in it) adds
    the free end where the daemon draws the mini thumbnail."""
    head = "/* GENERATED by ~/.config/hypr/scripts/island.py (match_bar) -- do not edit. */\n"
    if not (cfg.get("enabled") and cfg.get("match_bar") and cfg.get("style") in SHAPES):
        return head
    look = bar_look(cfg, accent)
    pills = ",\n".join(BAR_CENTRE)
    hovers = ",\n".join(f"{p}:hover" for p in BAR_CENTRE)
    body = "\n    ".join(look)
    # Only the main bar's: the toolbox is a waybar too, with the same
    # stylesheet, and its empty centre box would show as a black notch.
    return (head + f"""
window#waybar.waybar-main .modules-center {{
    {body}
    padding: 0 {12 + (MINI_SLOT if slot else 0)}px 0 12px;
}}

{pills} {{
    margin-top: 0;
    margin-bottom: 0;
    border-radius: 0;
    background-color: transparent;
    background-image: none;
    border-color: transparent;
    box-shadow: none;
    color: #d4d4d8;
}}

{hovers} {{
    background-color: alpha(#ffffff, 0.08);
    border-color: transparent;
    box-shadow: none;
}}

#custom-weather {{
    margin-right: 0;
}}

/* where the two capsules met */
#custom-updates {{
    border-left-color: alpha(#ffffff, 0.16);
}}

#custom-day {{
    color: #a1a1aa;
}}

#custom-clock,
#custom-clock.local {{
    color: #f4f4f6;
}}

/* The states the capsules showed as fills read as coloured text on the
   dark island instead -- same meaning, no block of colour in the notch. */
#custom-clock.utc,
#custom-clock.epoch,
#custom-updates.many,
#custom-repos.dirty,
#custom-repos.unpushed {{
    background-color: transparent;
    background-image: none;
    border-color: transparent;
    text-shadow: none;
}}

#custom-clock.utc {{
    color: #b9a7ff;
}}

#custom-clock.epoch,
#custom-updates.many,
#custom-repos.dirty {{
    color: #f5c451;
}}

#custom-repos.unpushed {{
    color: #ff7a8f;
}}

#custom-updates.updated,
#custom-updates.error,
#custom-repos.clean,
#custom-weather.stale,
#custom-weather.unavailable,
#custom-notifications.dnd {{
    color: #71717a;
}}

/* A restart is due (updates.sh's class "reboot"): never dimmed, in the
   amber of the other "something to do" states -- the theme's own colour
   could be a dark one, made for a light bar. */
#custom-updates.reboot,
#custom-updates.updated.reboot,
#custom-updates.error.reboot {{
    border-color: transparent;
    color: #f5c451;
}}
""")


MINI_SLOT = 52                # the free end of the notch for the media's thumbnail (px)
NOTCH_DARK = 6                # the notch's top row is pure black: every channel at most this
NOTCH_NEAR = 16               # a coloured fill comes back a few steps off (the screen's colour management)
ISLAND_FALLBACK_W = 560       # before (or without) a measurement


CLOCK_CHECK_S = 60            # how often the clock's text length is looked at (no grim)


def notch_text_sig(read=None):
    """The lengths of the bar's clock and day texts (waybar clock.py's
    readings): what makes the notch wider or narrower minute to minute.
    None when they cannot be read. read(kind) -> text stands in for clock.py
    in the tests."""
    if read is None:
        try:
            waybar = os.path.expanduser("~/.config/waybar/scripts")
            if waybar not in sys.path:
                sys.path.insert(0, waybar)
            import clock as bar_clock
        except Exception:         # noqa: BLE001  (no waybar scripts: no signature)
            return None

        def read(kind):
            return bar_clock.reading(kind).get("text", "")
    try:
        return tuple(len(read(kind) or "") for kind in ("clock", "day"))
    except Exception:             # noqa: BLE001
        return None


def parse_ppm(data):
    """grim -t ppm: (width, height, RGB bytes) or None."""
    parts = data.split(maxsplit=4)
    if len(parts) < 5 or parts[0] != b"P6":
        return None
    try:
        w, h = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    pixels = parts[4]
    return (w, h, pixels) if len(pixels) >= w * h * 3 else None


def notch_half(row, width, dark=NOTCH_DARK, fill=(0, 0, 0), gap=0):
    """Half the width of the dark run through the middle of one RGB pixel
    row (the bar's top row: the notch, flat on top, and no text there).
    "Dark" is the notch's fill: black, or notch_color's colour (every channel
    within `dark` of it).
    waybar centres the group, so the smaller side is the true half -- a dark
    wallpaper beside one end cannot widen it. None when the middle is not
    dark (the notch is not there). The run goes on over at most `gap`
    other pixels when the fill comes back after them: the media's
    thumbnail, on the floating island's row at its right end."""
    def is_dark(x):
        i = 3 * x
        return max(abs(row[i + k] - fill[k]) for k in range(3)) <= dark
    mid = width // 2
    if width < 3 or not is_dark(mid):
        return None
    def end(step):
        x = mid
        while True:
            for k in range(1, gap + 2):
                if not 0 <= x + k * step < width:
                    return x
                if is_dark(x + k * step):
                    x += k * step
                    break
            else:
                return x
    return min(mid - end(-1), end(1) - mid) + 1


def write_bar_css(cfg, slot=False):
    """island-bar.css, when it changed (waybar re-reads its style on every
    write). Never under ISLAND_DRY: the tests use bar_css()."""
    if dry_env():
        return False
    text = bar_css(cfg, slot, theme_accent())
    try:
        with open(BAR_CSS) as fh:
            if fh.read() == text:
                return False
    except OSError:
        pass
    try:
        os.makedirs(GEN_DIR, exist_ok=True)
        tmp = f"{BAR_CSS}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, BAR_CSS)
    except OSError as exc:
        print(f"island.py: {BAR_CSS}: {exc}", file=sys.stderr, flush=True)
        return False
    tell_player()
    return True


def tell_player():
    """The bar's media pill hides while the island carries the media
    (player.py media_in_island); SIGUSR1 makes it re-decide now. Only the
    python process: waybar starts it through `sh -c`, and SIGUSR1 would end
    the shell (and with it the module) instead."""
    if dry_env():
        return
    subprocess.run(["pkill", "-USR1", "-f", r"^\S*python3?\S* \S*waybar/scripts/player\.py watch"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dry_env():
    """ISLAND_DRY=1 (the tests): settings are written, systemd is left alone."""
    return os.environ.get("ISLAND_DRY") == "1"


def switch_unit(on):
    """enable --now / disable --now island.service. Off stops the daemon,
    which removes its socket: the senders then return at once."""
    cmd = ["systemctl", "--user", "enable" if on else "disable", "--now", UNIT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"island.py: {' '.join(cmd)}: {exc}")
    if r.returncode != 0:
        raise SystemExit(f"island.py: {' '.join(cmd)}: {(r.stderr or '').strip()}")


def set_key(key, value):
    if key not in DEFAULTS:
        raise SystemExit(f"island.py: no setting {key!r} (one of {', '.join(DEFAULTS)})")
    cur = read_settings()
    if key in BOOL_KEYS:
        try:
            cur[key] = bool_value(value)
        except ValueError:
            raise SystemExit(f"island.py: {key} is on or off")
    elif key == "style":
        v = str(value).strip().lower()
        if v in OLD_STYLES:         # the old designs: a notch with their colour / outline
            cur.update(OLD_STYLES[v])
            v = "notch"
        if v not in STYLES:
            raise SystemExit(f"island.py: style is one of {', '.join(STYLES)}")
        cur[key] = v
    elif key == "notch_color":
        v = str(value).strip().lower()
        if v not in NOTCH_COLORS:
            raise SystemExit(f"island.py: notch_color is one of {', '.join(NOTCH_COLORS)}")
        cur[key] = v
    else:
        v = str(value).strip()
        v = "" if v == "auto" else v
        if v not in ("", "focused") and not MONITOR_NAME.match(v):
            raise SystemExit("island.py: monitor is auto, focused or a connector such as DP-2")
        cur[key] = v
    # Written first: a daemon that starts reads enabled=true, and one that
    # sees enabled=false in the file quits by itself.
    write_settings(cur)
    if not cur["enabled"]:
        # Off: the bar's centre goes back to the theme's. On, the daemon
        # writes it (it alone knows whether the media slot is wanted).
        write_bar_css(cur)
    if key == "enabled" and not dry_env():
        switch_unit(cur["enabled"])
    return cur


def systemctl_word(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args, UNIT], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def monitor_names():
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True,
                             timeout=3).stdout
        return [m["name"] for m in json.loads(out or "[]") if m.get("name")]
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        return []


def status():
    if dry_env():
        service, enabled_unit = "dry", False
    else:
        service = systemctl_word("is-active") or "unknown"
        enabled_unit = systemctl_word("is-enabled") == "enabled"
    try:
        running = stat.S_ISSOCK(os.stat(SOCK).st_mode)
    except OSError:
        running = False
    # where notifications show: "island" (mako's island mode is in), "mako"
    # (its popups), "" unknown (no mako, or the tests)
    modes = None if dry_env() else mako_modes()
    popups = "" if modes is None else ("island" if MAKO_MODE in modes else "mako")
    return {"settings": read_settings(), "defaults": dict(DEFAULTS), "service": service,
            "enabled_unit": enabled_unit, "running": running, "monitors": monitor_names(),
            "sock": SOCK, "popups": popups, "top_bar_off": top_bar_off()}


def print_status(st):
    for k, v in st["settings"].items():
        shown = ("on" if v else "off") if k in BOOL_KEYS else (v or "main screen")
        print(f"{k}: {shown}")
    print(f"service: {st['service']}{' (enabled)' if st['enabled_unit'] else ''}")
    print(f"running: {'yes' if st['running'] else 'no'}")
    print(f"monitors: {', '.join(st['monitors']) or '-'}")
    print(f"sock: {st['sock']}")
    print(f"notifications: {({'island': 'in the island', 'mako': 'mako popups'}).get(st['popups'], 'unknown')}")


# -- the pure parts of the daemon (no GTK: the tests import these) -------------------------
def capture(pidfile):
    """(started epoch, target) of the recording record.sh keeps in `pidfile`,
    or None when there is none or its process is not the recorder any more.
    A stale file is left where it is: record.sh owns it."""
    try:
        with open(pidfile) as fh:
            lines = fh.read().split("\n")
        started = os.stat(pidfile).st_mtime
    except OSError:
        return None
    pid = lines[0].strip()
    if not pid.isdigit():
        return None
    try:
        with open(os.path.join(PROC, pid, "comm")) as fh:
            comm = fh.read().strip()
    except OSError:
        return None
    if not comm.startswith("gpu-screen-reco"):     # comm is cut at 15 characters
        return None
    return started, (lines[2].strip() if len(lines) > 2 else "")


def recorder_alive(pid):
    """Is `pid` (a string of digits) still gpu-screen-recorder?"""
    try:
        with open(os.path.join(PROC, str(pid), "comm")) as fh:
            return fh.read().startswith("gpu-screen-reco")
    except OSError:
        return False


def record_outcome(act, now):
    """How the live recording `act` ended, once its pid file is gone:
    "saved" when the recorder has exited after a real run and left a
    non-empty file, "failed" for one that died in its first seconds (mako
    says why; the island shows nothing), else "stopped" -- record.sh's
    own toast tells "did not stop" and "failed" apart."""
    if now - act.get("started", now) < RECORD_MIN_S:
        return "failed"
    if act.get("pid") and recorder_alive(act["pid"]):
        return "stopped"
    try:
        if os.path.getsize(act.get("out") or "") > 0:
            return "saved"
    except OSError:
        pass
    return "stopped"


def clock(secs):
    """4:05, 1:02:03 (timers.py's)."""
    secs = max(0, int(secs))
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cut(text, n=48):
    """One line, at most n characters with the ellipsis."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def media_text(metadata):
    """(title, artist) from MPRIS metadata; a file's name when there is no
    title (mpv playing a file without tags)."""
    title = metadata.get("xesam:title") or ""
    artist = metadata.get("xesam:artist") or ""
    if isinstance(artist, (list, tuple)):
        artist = ", ".join(str(a) for a in artist if a)
    if not title and metadata.get("xesam:url"):
        path = urllib.parse.urlparse(str(metadata["xesam:url"])).path
        title = urllib.parse.unquote(os.path.basename(path.rstrip("/")))
    return cut(title), cut(artist)


def pick_player(names, statuses, selected):
    """The player the island follows: the bar's choice while it is there,
    else a playing one, else a paused one -- mpv and vlc before the rest."""
    names = [n for n in names if not any(s in n for s in SKIP_PLAYERS)]
    if selected and selected in names:
        return selected
    for want in ("Playing", "Paused"):
        found = [n for n in names if statuses.get(n) == want]
        if found:
            return sorted(found, key=lambda n: not n.startswith(PREFER_PLAYERS))[0]
    return None


def timer_activity(entries, rings, now, window_s=TIMER_WINDOW_S, names=None):
    """What the timers have to show: the first ringing one, else the first
    (timers.running() is soonest first) unpaused one due within window_s.
    rings is timers.ringing(), entries timers.running(); names is timers.NAMES,
    for a label when there is none."""
    names = names or {}

    def label(d):
        return d.get("label") or names.get(d.get("kind")) or d.get("kind") or ""

    if rings:
        r = rings[0]
        return {"kind": "ringing", "id": r.get("id"), "label": label(r), "tkind": r.get("kind")}
    for e in entries:
        if e.get("paused"):
            continue
        left = e.get("due", 0) - now
        if 0 <= left <= window_s:
            return {"kind": "ending", "id": e.get("id"), "label": label(e), "tkind": e.get("kind"),
                    "left": int(left)}
    return None


def next_timer_wake(entries, now, window_s=TIMER_WINDOW_S):
    """Seconds until the soonest unpaused, still-to-come entry enters its last
    window_s (0: one is in it already), or None when there is none."""
    dues = [e.get("due", 0) for e in entries if not e.get("paused") and e.get("due", 0) >= now]
    if not dues:
        return None
    return max(0.0, min(dues) - window_s - now)


def is_game_env(environ_bytes):
    return any(item.startswith(GAME_ENV) for item in environ_bytes.split(b"\0"))


def game_running(clients, env_of):
    """A game among Hyprland's clients: a Steam game's window class, or the
    game variables in its process' environment (railguard.py's GAME_ENV)."""
    for c in clients:
        if STEAM_CLASS.match(str(c.get("class") or "")):
            return True
        pid = c.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            continue
        try:
            if is_game_env(env_of(pid)):
                return True
        except Exception:      # noqa: BLE001 - a process that is gone, or not ours
            continue
    return False


def monitor_hidden(monitors, workspaces, name):
    """Whether the island's screen shows a fullscreen window: its active
    workspace has one, or its special workspace is open and has one."""
    mon = next((m for m in monitors if m.get("name") == name), None)
    if mon is None:
        return False
    full = {w.get("id") for w in workspaces if w.get("hasfullscreen")}
    if (mon.get("activeWorkspace") or {}).get("id") in full:
        return True
    special = (mon.get("specialWorkspace") or {}).get("id", 0)
    return bool(special) and special in full


def choose_monitor(setting, monitors):
    """The connector the setting names, if it is up; None means the main
    screen (the caller asks panelui.fallback_output())."""
    if setting == "focused":
        return next((m.get("name") for m in monitors if m.get("focused")), None)
    if setting and any(m.get("name") == setting for m in monitors):
        return setting
    return None


def drops(act):
    """Whether it drops down below the bar by itself: an alert or a ringing
    timer. Everything else stays in the bar's strip until hovered."""
    return act["src"] == "railguard" or (act["src"] == "timers" and act.get("kind") == "ringing") \
        or (act["src"] == "notify" and act.get("urgency") == "critical")


def rank(activities):
    return sorted(activities, key=lambda s: PRIORITY.index(s) if s in PRIORITY else len(PRIORITY))


def lead(vis):
    """rank(), except that a notification from the queue goes ahead of an
    activity that only sits in its compact pill (a recording's clock, a
    paused track): a notification is news, those are not. An expanded one
    (an alert, a ringing timer) keeps its place."""
    order = rank(vis)
    n = vis.get("notify")
    if n is not None and n.get("nid") is not None and order and order[0] != "notify" \
            and not vis[order[0]].get("expand"):
        order.remove("notify")
        order.insert(0, "notify")
    return order


def parse_event(datagram):
    """One island_events.py datagram, or None for anything else."""
    try:
        msg = json.loads(datagram)
    except (ValueError, TypeError):
        return None
    if not isinstance(msg, dict) or msg.get("src") not in ("railguard", "notify") \
            or msg.get("v") != 1:
        return None
    return {k: (v[:LIMIT] if isinstance(v, str) else v) for k, v in msg.items()}


# The activities: {src: {"src", "ongoing", "until", "expand", "key", ...}}.
# "until" is a time.monotonic() deadline: the end of the expanded view; a
# transient one (ongoing false) is removed then.
def expire(acts, now):
    """Apply the deadlines that passed: an ongoing activity collapses to the
    compact pill, a transient one goes. Changes acts in place."""
    for src in list(acts):
        a = acts[src]
        if a.get("until") is not None and a["until"] <= now + 0.01:
            if a.get("ongoing"):
                a["expand"], a["until"] = False, None
            else:
                del acts[src]
    return acts


def next_deadline(acts):
    dues = [a["until"] for a in acts.values() if a.get("until") is not None]
    return min(dues) if dues else None


def tucked(cfg):
    """The media lives in the notch as a mini thumbnail (hover: the full
    island): the island is on and its look is on the bar's centre."""
    return bool(cfg.get("enabled") and cfg.get("match_bar") and cfg.get("style") in SHAPES
                and cfg.get("media"))


def shown(acts, ongoing_on, dismissed, keep=()):
    """The activities that show: not dismissed, and with the ongoing pill
    switched off only while they are expanded."""
    out = {}
    for src, a in acts.items():
        if (src, a.get("key")) in dismissed:
            continue
        if a.get("ongoing") and not a.get("expand") and not ongoing_on and src not in keep:
            continue
        out[src] = a
    return out


def describe(act, now):
    """How one activity looks at `now` (epoch seconds, like a recording's
    start and a timer's due): {"cls", "glyph", "glyph_cls", "image"
    (("mascot", mood) / ("art", path) / None), "text" (the compact line),
    "title", "sub" (the expanded lines), "buttons" [(action, glyph,
    tooltip)], "clock" (it changes every second)}."""
    src = act["src"]
    v = {"cls": f"island-{src}", "glyph": "", "glyph_cls": "", "image": None, "text": "",
         "title": "", "sub": "", "buttons": [], "clock": False, "extra_cls": [], "app": "",
         "count": "", "body": False}
    if src == "record":
        v["cls"] = "island-rec"
        if act.get("phase") == "saved":
            v.update(glyph=SAVED_ICON, text="Recording saved", title="Recording saved",
                     sub=cut(act.get("target") or "", 60))
        elif act.get("phase") == "stopped":
            v.update(glyph=STOP_ICON, text="Recording stopped", title="Recording stopped",
                     sub=cut(act.get("target") or "", 60))
        else:
            elapsed = clock(now - act.get("started", now))
            target = act.get("target") or ""
            v.update(glyph=REC_DOT, glyph_cls="island-rec-dot", text=elapsed, clock=True,
                     title="Recording" + (f" · {cut(target, 40)}" if target else ""), sub=elapsed,
                     buttons=[("rec-stop", STOP_ICON, "Stop and save")])
    elif src == "railguard":
        v["cls"] = "island-alert"
        v.update(glyph=SHIELD_ICON, image=("mascot", act.get("mood") or "alert"),
                 text=cut(act.get("title"), 40), title=cut(act.get("title"), 52),
                 sub=cut(act.get("body"), 60))
    elif src == "notify" and act.get("nid") is not None:
        # one of the notifications queue's (island_notify.py)
        app, summary = act.get("app") or "", act.get("summary") or ""
        body = act.get("body") or ""
        urgency = act.get("urgency") or "normal"
        line = f"{app} · {summary}" if app and summary else (summary or app or cut(body, 40))
        btns = [(f"notif-action:{key}", label, label) for key, label in act.get("buttons") or []]
        if act.get("goto"):
            btns.append(("notif-goto", act["goto"], act["goto"]))
        btns.append(("notif-dismiss", CLOSE_ICON, "Dismiss"))
        v.update(glyph=CRITICAL_ICON if urgency == "critical" else BELL_ICON,
                 image=notify_image(act), text=cut(line, 60), title=summary or app,
                 app=app if summary else "", sub=body, body=True, buttons=btns,
                 extra_cls=[f"island-notify-{urgency}"],
                 count=f"+{act['waiting']}" if act.get("waiting") else "")
        v["image"] = notify_mascot(act, v["image"], mascot_prefs()) or v["image"]
    elif src == "notify":
        app, summary = act.get("app") or "", act.get("summary") or ""
        line = f"{app} · {summary}" if app and summary else (summary or app)
        v.update(glyph=BELL_ICON, text=cut(line, 40), title=cut(line, 52), sub=cut(act.get("body"), 60))
    elif src == "timers":
        v["cls"] = "island-timer"
        label = act.get("label") or ""
        v["glyph"] = act.get("icon") or TIMER_ICON
        if act.get("kind") == "ringing":
            v.update(text=cut(f"{label} · ringing", 40), title=cut(label, 52), sub="ringing",
                     buttons=[("timer-snooze", SNOOZE_ICON, "Snooze"), ("timer-stop", STOP_ICON, "Stop")])
        elif act.get("kind") == "done":
            v.update(text=cut(f"{label} done", 40), title=cut(f"{label} done", 52))
        else:
            left = clock(act.get("due", now) - now)
            v.update(text=f"{cut(label, 30)} {left}", title=cut(label, 52), sub=f"{left} left",
                     clock=True)
    elif src == "media":
        playing = act.get("status") == "Playing"
        art = act.get("art")
        v.update(glyph=act.get("icon") or MUSIC_ICON, image=("art", art) if art else None,
                 text=cut(act.get("title"), 40), title=cut(act.get("title"), 52),
                 sub=cut(act.get("artist"), 60),
                 buttons=[("play-pause", PAUSE_ICON if playing else PLAY_ICON,
                           "Pause" if playing else "Play"), ("next", NEXT_ICON, "Next")])
    return v


def art_path(url):
    """A local file:// cover only -- never a download."""
    if isinstance(url, str) and url.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
        if os.path.isfile(path):
            return path
    return None


def notify_image(act):
    """A notification's picture for set_image: the sender's image-data
    (("nid", id): the daemon decoded it), a picture file (("art", path)),
    an icon name (("icon", name)), or None."""
    if act.get("data"):
        return ("nid", act.get("nid"))
    icon = str(act.get("icon") or "")
    if icon.startswith("file://"):
        icon = urllib.parse.unquote(urllib.parse.urlparse(icon).path)
    if icon.startswith("/"):
        return ("art", icon) if os.path.isfile(icon) else None
    return ("icon", icon) if icon and re.match(r"^[\w.+-]{1,128}$", icon) else None


_PREFS = (None, None)


def mascot_prefs():
    """Settings > Mascot's notification switches (mascot_notify.settings(),
    read again only when mascot.json changes)."""
    global _PREFS
    import mascot_notify
    try:
        stamp = os.path.getmtime(mascot_notify.STATE)
    except OSError:
        stamp = 0
    if _PREFS[0] != stamp:
        _PREFS = (stamp, mascot_notify.settings())
    return _PREFS[1]


def notify_mascot(act, image, prefs):
    """The mascot on a notification's card, by mako's popups' rules
    (mascot_notify.py), so it is there from any app with the island on or
    off: ("mascot", (mood, badge)) -- badge the sender's own picture
    (notify_image()'s spec) for the corner, None for none -- or None to
    leave the card as it is: the mascot switched off, a low-urgency toast
    with toasts off, or the picture already the mascot (scripts/notify)."""
    import mascot_icons
    import mascot_notify
    urgency = act.get("urgency") or "normal"
    if not prefs.get("icon") or (urgency == "low" and not prefs.get("toasts")):
        return None
    if image and image[0] == "art" and image[1].startswith(mascot_icons.CACHE + os.sep):
        return None
    mood = act.get("mood") if act.get("mood") in MOODS else \
        ("alert" if urgency == "critical" else "calm")
    badge = image
    if badge and badge[0] == "icon" and badge[1].startswith(mascot_notify.GENERIC_ICONS):
        badge = None              # the mood says the same
    return ("mascot", (mood, badge))


def notify_act(item, waiting):
    """The "notify" activity for the queue's current item: critical ones
    drop below the bar by themselves (drops()); none of it has a deadline
    of its own -- the queue decides when it goes."""
    return {"nid": item["id"], "app": item.get("app"), "summary": item.get("summary"),
            "body": item.get("body"), "urgency": item.get("urgency"), "icon": item.get("icon"),
            "data": item.get("data"), "mood": item.get("mood"),
            "actions": list(item.get("actions") or []), "buttons": island_notify.buttons(item),
            "goto": notify_source.button_label(item.get("target")),
            "waiting": waiting, "ongoing": False, "until": None, "key": item["id"],
            "expand": item.get("urgency") == "critical"}


def read_notify_conf():
    """Settings > Notifications' saved choices (notifications.json; {} when
    there are none: island_notify has the same defaults)."""
    try:
        with open(NOTIFY_CONF) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def makoctl(*args, timeout=3):
    """makoctl's output, or None when it failed (no mako, say)."""
    try:
        r = subprocess.run(["makoctl", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def mako_modes():
    out = makoctl("mode")
    return out.split() if out is not None else None


def set_mako_mode(on):
    """Add or remove the island's mako mode -- only add / remove (-a / -r):
    the other modes (do-not-disturb, project-focus) are not ours. True
    when makoctl did it. Never under ISLAND_DRY."""
    if dry_env():
        return False
    return makoctl("mode", "-a" if on else "-r", MAKO_MODE) is not None


def sd_notify(message):
    """One line to systemd's $NOTIFY_SOCKET (the watchdog's ping); quietly
    nothing outside a service."""
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return False
    if path.startswith("@"):
        path = "\0" + path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(path)
            s.sendall(message.encode())
        return True
    except OSError:
        return False


def player_icon(name):
    for key, glyph in PLAYER_ICONS.items():
        if (name or "").startswith(key):
            return glyph
    return MUSIC_ICON


# -- Hyprland (stdlib) ---------------------------------------------------------------------
def hypr_dir():
    base = os.path.join(RUNTIME, "hypr")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        try:
            sig = sorted(os.listdir(base))[-1]
        except (OSError, IndexError):
            return None
    return os.path.join(base, sig)


def hypr_request(cmd):
    """One request on .socket.sock (fsstate.py's): what `hyprctl -j` does,
    minus a process. Raises OSError / ValueError."""
    folder = hypr_dir()
    if not folder:
        raise OSError("no Hyprland instance")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect(os.path.join(folder, ".socket.sock"))
        sock.sendall(cmd.encode())
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    finally:
        sock.close()
    return json.loads(b"".join(chunks))


def read_environ(pid):
    with open(os.path.join(PROC, str(pid), "environ"), "rb") as fh:
        return fh.read()


# -- the daemon ----------------------------------------------------------------------------
# BAR_H is the bar's strip (waybar's reserved 38 px): the compact pill fills
# exactly that, square on top where it meets the screen edge, like a notch.
BAR_H = 38
# The island is always exactly as wide as the notch (waybar's centre group,
# its natural width): the daemon measures it off the screen's top row
# (measure_notch) and sizes the pill, the dropped-down card and the mini
# thumbnail's window to it, so the island opens exactly over the notch.
ISLAND_CSS = """
#panel.island {
    margin: 0;
    padding: 0 18px;
    min-height: %dpx;
    border-top-width: 0;
    border-radius: 0 0 16px 16px;
}
#panel.island.island-expanded {
    padding: 12px 18px 12px 18px;
    border-radius: 0 0 22px 22px;
}""" % (BAR_H - 1) + """
/* -- the designs (island-style-*; style in island.json) ----------------- */
#panel.island.island-dark {
    background-color: #000000;
    background-image: none;
    border-color: transparent;
    box-shadow: none;
}
#panel.island.island-dark .island-text,
#panel.island.island-dark .island-title {
    color: #f4f4f6;
}
#panel.island.island-dark .island-glyph,
#panel.island.island-dark .island-sub,
#panel.island.island-dark .island-second {
    color: #a1a1aa;
}
#panel.island.island-dark button.ctl-icon {
    color: #f4f4f6;
    background-color: alpha(#ffffff, 0.10);
    background-image: none;
    border-color: transparent;
    box-shadow: none;
}
#panel.island.island-dark button.ctl-icon:hover {
    background-color: alpha(#ffffff, 0.20);
}
/* island: a capsule floating under the edge, inside the bar's strip */
#panel.island.island-style-island {
    margin-top: 4px;
    min-height: 30px;         /* the bar's capsules: BAR_H - 4 above - 4 below */
    border-radius: 999px;
}
#panel.island.island-style-island.island-expanded {
    border-radius: 26px;
}
/* the media's mini thumbnail in the notch's right slot */
.island-mini {
    margin: 0 14px 0 0;
    padding: 3px;
    min-width: 24px;
    min-height: 24px;
    border-radius: 7px;
    background-color: alpha(#ffffff, 0.10);
}
.island-mini label {
    color: #f4f4f6;
}
.island-mini.island-mini-paused {
    opacity: 0.55;
}
#panel.island.island-alert {
    border-color: @yellow;
}
#panel.island.island-rec {
    border-color: alpha(@red, 0.7);
}
.island-glyph {
    color: @text-dim;
    min-width: 16px;
}
.island-rec-dot {
    color: @red;
    animation: island-pulse 1.2s ease-in-out infinite;
}
@keyframes island-pulse {
    0%   { opacity: 1; }
    50%  { opacity: 0.35; }
    100% { opacity: 1; }
}
.island-text {
    color: @text;
}
.island-title {
    font-weight: bold;
    color: @text;
}
.island-sub {
    color: @text-dim;
}
.island-second {
    color: @text-dim;
    margin-left: 8px;
}
#panel.island button.ctl-icon {
    min-width: 30px;
    min-height: 30px;
}
/* -- notifications (island_notify.py's queue) --------------------------- */
#panel.island {
    transition: border-color 220ms ease-out, background-color 220ms ease-out;
}
.island-app {
    font-size: 0.85em;
    color: @text-dim;
}
#panel.island.island-dark .island-app {
    color: #a1a1aa;
}
.island-count {
    margin-left: 8px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 0.85em;
    color: #f4f4f6;
    background-color: alpha(#ffffff, 0.14);
}
#panel.island.island-notify-critical {
    border-color: @red;
}
#panel.island.island-notify-critical .island-glyph,
#panel.island.island-notify-critical .island-title {
    color: #ff6b81;
}
#panel.island.island-notify-low .island-text {
    opacity: 0.75;
}
/* an action's words on its button, not a glyph */
#panel.island button.ctl-icon.island-action {
    padding: 0 10px;
}
/* a new notification arrives: a short glow from the edge */
#panel.island.island-pop {
    animation: island-pop 700ms ease-out 1;
}
@keyframes island-pop {
    0%   { box-shadow: 0 0 0 0 alpha(@text, 0.45); }
    100% { box-shadow: 0 0 0 14px alpha(@text, 0); }
}
#panel.island.island-notify-critical.island-pop {
    animation: island-pop-critical 700ms ease-out 1;
}
@keyframes island-pop-critical {
    0%   { box-shadow: 0 0 0 0 alpha(@red, 0.6); }
    100% { box-shadow: 0 0 0 16px alpha(@red, 0); }
}
"""


def top_bar_off():
    """The dock or taskbar runs without the top bar (dock.py bar_hidden)."""
    try:
        import dock
        return dock.bar_hidden(dock.read_settings())
    except Exception:         # noqa: BLE001 - no dock: the bar is there
        return False


def effective(cfg, bar_off=None):
    """The settings the daemon works with: match_bar off while the top bar
    is (no centre to match, nothing to measure)."""
    off = top_bar_off() if bar_off is None else bar_off
    return dict(cfg, match_bar=False) if off and cfg.get("match_bar") else cfg


def daemon():
    cfg = effective(read_settings())
    if not cfg["enabled"]:
        print("island: switched off (island.py set on)", flush=True)
        return 0
    import signal

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango
    import cairo                    # the mini thumbnail's input region
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    sys.path.insert(0, HERE)
    import panelui
    try:
        import timers
    except Exception as exc:        # noqa: BLE001 - the island works without them
        print(f"island: no timers ({exc})", file=sys.stderr, flush=True)
        timers = None
    try:
        gi.require_version("Playerctl", "2.0")
        from gi.repository import Playerctl
    except (ImportError, ValueError) as exc:
        print(f"island: no Playerctl, media is off ({exc})", file=sys.stderr, flush=True)
        Playerctl = None

    island_css = Gtk.CssProvider()

    def load_css():
        panelui.load_css()
        try:
            island_css.load_from_data((ISLAND_CSS + fill_css(read_settings(), theme_accent())).encode())
        except GLib.Error as exc:
            print(f"island: ISLAND_CSS: {exc}", file=sys.stderr, flush=True)

    def spawn(*cmd):
        try:
            proc = subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError as exc:
            print(f"island: {cmd[0]}: {exc}", file=sys.stderr, flush=True)
            return
        # Reap it when it ends; otherwise it stays a zombie until the next Popen.
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, lambda *_: None)

    def later(ms, fn):
        """A one-shot GLib timeout calling fn()."""
        return GLib.timeout_add(max(0, int(ms)), lambda: (fn(), False)[1])

    image_hints = ("image-data", "image_data", "icon_data")     # the spec's order of preference

    def bus_event(msg, owner):
        """One monitored message as a plain tuple, read in GDBus' thread
        (no GTK there): ("call", (caller, serial), Notify's args),
        ("return", (caller, serial), id), ("closed", id), ("modes",) (mako
        was told to change its modes or reload) -- or None for anything
        else."""
        kind = msg.get_message_type()
        body = msg.get_body()
        sig = body.get_type_string() if body is not None else ""
        if kind == Gio.DBusMessageType.METHOD_CALL and msg.get_interface() == MAKO_IFACE:
            # makoctl mode -a / -r / -t, makoctl reload: what mako hides changes
            return ("modes",) if msg.get_member() in MAKO_MODE_CALLS else None
        if kind == Gio.DBusMessageType.METHOD_CALL:
            if msg.get_member() != "Notify" or sig != "(susssasa{sv}i)":
                return None
            hints, images = {}, {}
            hv = body.get_child_value(6)
            for i in range(hv.n_children()):
                entry = hv.get_child_value(i)
                key = entry.get_child_value(0).get_string()
                val = entry.get_child_value(1).get_variant()
                vt = val.get_type_string()
                if key in image_hints and vt == "(iiibiiay)":
                    data = val.get_child_value(6).get_data_as_bytes()
                    if data.get_size() <= IMAGE_MAX:
                        images[key] = tuple(val.get_child_value(j).unpack() for j in range(6)) + (data,)
                elif key == "urgency" and vt == "y":
                    hints[key] = val.get_byte()
                elif key in ("image-path", "image_path", "category", "desktop-entry") and vt == "s":
                    hints[key] = val.get_string()
            image = next((images[k] for k in image_hints if k in images), None)
            args = (body.get_child_value(0).get_string(), body.get_child_value(1).get_uint32(),
                    body.get_child_value(2).get_string(), body.get_child_value(3).get_string(),
                    body.get_child_value(4).get_string(), list(body.get_child_value(5).get_strv()),
                    hints, body.get_child_value(7).get_int32(), image)
            return ("call", (msg.get_sender(), msg.get_serial()), args)
        if kind == Gio.DBusMessageType.METHOD_RETURN:
            if sig != "(u)" or (owner and msg.get_sender() != owner):
                return None
            return ("return", (msg.get_destination(), msg.get_reply_serial()),
                    body.get_child_value(0).get_uint32())
        if kind == Gio.DBusMessageType.SIGNAL:
            if msg.get_member() == "NotificationClosed" and sig == "(uu)":
                return ("closed", body.get_child_value(0).get_uint32())
        return None

    class Island(Gtk.Window):
        def __init__(self):
            super().__init__()
            self.cfg = cfg
            self.acts = {}
            self.dismissed = set()
            self.hovering = False
            self.ids = {}             # name -> GLib source id (debounces, deadline, tick ...)
            self.suppressed = False
            self.dirty = True         # the fullscreen state needs a fresh look
            self.dirty_game = True    # and the game check (windows opened or closed)
            self.fullscreen = self.game = False
            self.env_cache = {}
            self.output = None
            self.pixbufs = {}
            self.players = {}         # instance -> Playerctl.Player
            self.media_seen = None    # (player, title, status) last seen: "did it change"
            self.media_ready = False  # the players there at start come in quietly
            self.record_tries = 0
            self.events = None
            self.events_buf = b""
            self.button_key = None
            self.monitors_keep = []   # the Gio monitors (kept, or they are collected)
            self.notch_w = None       # the notch's width, measured (measure_notch)
            self.slot = False         # the notch keeps the media thumbnail's end free
            # notifications (NOTIFICATIONS in the docstring)
            self.queue = []           # island_notify items
            self.seq = 0
            self.bus_mon = None       # the monitor connection
            self.bus_owner = None     # mako's unique name on the bus
            self.pending = {}         # (caller, serial) -> (Notify args, monotonic)
            self.caller_pids = {}     # bus name -> [pid, parent pid, ...] (learn_pid)
            self.notif_images = {}    # id -> GdkPixbuf (the sender's image-data)
            self.mode_on = False      # we added mako's island mode
            self.pop_nid = None       # the notification the pop animation is for
            self.pop_until = 0.0

            self.set_name("panel-window")
            self.set_app_paintable(True)
            visual = self.get_screen().get_rgba_visual()
            if visual:
                self.set_visual(visual)
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, NAMESPACE)
            # OVERLAY: above the bar, whose strip it hangs in. A fullscreen
            # window or a game unmaps it (check_suppressed), not the layer.
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 0)
            # -1: it ignores the bar's reserved strip (0 would push it below
            # the bar) and reserves none itself, so windows never move for it.
            GtkLayerShell.set_exclusive_zone(self, -1)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
            self.build()

        # -- widgets -----------------------------------------------------------------------
        def build(self):
            box = Gtk.EventBox()
            box.set_visible_window(False)
            box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                           | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            box.connect("button-press-event", self.on_press)
            box.connect("enter-notify-event", self.on_enter)
            box.connect("leave-notify-event", self.on_leave)
            self.add(box)
            self.outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            box.add(self.outer)
            self.card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            self.card.set_name("panel")
            self.card.get_style_context().add_class("island")
            self.outer.pack_start(self.card, True, True, 0)
            # The media's mini thumbnail: alone in a notch-wide, otherwise
            # see-through window, at the notch's right end; only it takes
            # the pointer (apply_input), so the bar's own pills stay
            # clickable around it.
            self.mini = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            self.mini.get_style_context().add_class("island-mini")
            self.mini.set_valign(Gtk.Align.CENTER)
            self.mini_image = Gtk.Image()
            self.mini_glyph = Gtk.Label()
            self.mini.pack_start(self.mini_image, True, True, 0)
            self.mini.pack_start(self.mini_glyph, True, True, 0)
            self.mini.connect("size-allocate", self.apply_input)
            self.outer.pack_end(self.mini, False, False, 0)
            self.mini.set_no_show_all(True)
            self.input_widget = None
            main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            main.set_valign(Gtk.Align.CENTER)       # the one line, mid-strip
            self.card.pack_start(main, True, True, 0)

            # compact: glyph or small picture, one line
            self.row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.glyph = Gtk.Label()
            self.glyph.get_style_context().add_class("island-glyph")
            self.small = Gtk.Image()
            self.text = Gtk.Label(xalign=0)
            self.text.get_style_context().add_class("island-text")
            for w in (self.glyph, self.small):
                self.row.pack_start(w, False, False, 0)
            self.row.pack_start(self.text, True, True, 0)   # takes the width, ends in "…"
            main.pack_start(self.row, False, False, 0)

            # expanded: picture, title and line, the buttons
            self.revealer = Gtk.Revealer()
            self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
            self.revealer.set_transition_duration(ANIM_MS)
            self.revealer.connect("notify::child-revealed", self.on_revealed)
            body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            self.big = Gtk.Image()
            self.big_glyph = Gtk.Label()
            self.big_glyph.get_style_context().add_class("ctl-icon")
            lines = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            lines.set_valign(Gtk.Align.CENTER)
            self.app_label = Gtk.Label(xalign=0)     # a notification's sender
            self.app_label.get_style_context().add_class("island-app")
            self.app_label.set_no_show_all(True)
            self.title = Gtk.Label(xalign=0)
            self.title.get_style_context().add_class("island-title")
            self.sub = Gtk.Label(xalign=0)
            self.sub.get_style_context().add_class("island-sub")
            lines.pack_start(self.app_label, False, False, 0)
            lines.pack_start(self.title, False, False, 0)
            lines.pack_start(self.sub, False, False, 0)
            # The island is as wide as the notch, never wider: a long title
            # ends in "…" (max-width-chars 1 keeps it from asking for more
            # than the width it is given).
            for label in (self.text, self.title, self.sub, self.app_label):
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.set_max_width_chars(1)
            self.buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self.buttons.set_valign(Gtk.Align.CENTER)
            body.pack_start(self.big, False, False, 0)
            body.pack_start(self.big_glyph, False, False, 0)
            body.pack_start(lines, True, True, 0)
            body.pack_end(self.buttons, False, False, 0)
            self.revealer.add(body)
            main.pack_start(self.revealer, False, False, 0)

            # what else is going on, at the right end: the next activity's
            # glyph, and right of it "+N" notifications waiting
            self.count_label = Gtk.Label()
            self.count_label.get_style_context().add_class("island-count")
            self.count_label.set_valign(Gtk.Align.CENTER)
            self.count_label.set_no_show_all(True)
            self.card.pack_end(self.count_label, False, False, 0)
            self.second_glyph = Gtk.Label()
            self.second_glyph.get_style_context().add_class("island-second")
            self.second_image = Gtk.Image()
            self.second_image.get_style_context().add_class("island-second")
            for w in (self.second_glyph, self.second_image):
                w.set_valign(Gtk.Align.CENTER)
                self.card.pack_end(w, False, False, 0)
            box.show_all()

        def pixbuf(self, kind, value, size):
            """A mascot (by mood) or a cover file at `size` px; None when it
            cannot be had. Cached until the theme changes."""
            try:
                stamp = os.path.getmtime(value) if kind == "art" else None
            except OSError:
                stamp = None
            if kind == "nid":         # a notification's image-data: decoded once, per id
                pb = self.notif_images.get(value)
                if pb is None:
                    return None
                w, h = pb.get_width(), pb.get_height()
                scale = size / max(w, h, 1)
                return pb.scale_simple(max(1, int(w * scale)), max(1, int(h * scale)),
                                       GdkPixbuf.InterpType.BILINEAR)
            key = (kind, value, size, stamp)
            if key not in self.pixbufs:
                pb = None
                try:
                    if kind == "icon":
                        theme = Gtk.IconTheme.get_default()
                        pb = theme.load_icon(value, size, Gtk.IconLookupFlags.FORCE_SIZE) \
                            if theme.has_icon(value) else None
                        self.pixbufs[key] = pb
                        return pb
                    if kind == "mascot":
                        import mascot_icons
                        mood, badge = value if isinstance(value, tuple) else (value, None)
                        mood = mood if mood in MOODS else "alert"
                        if badge and badge[0] == "nid":
                            return self.badged(mood, badge[1], size)
                        path = mascot_icons.icon(None, mood, badge[1] if badge else None)
                    else:
                        path = value
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
                except Exception as exc:      # noqa: BLE001 - no picture is not an error
                    print(f"island: {kind} picture: {exc}", file=sys.stderr, flush=True)
                if len(self.pixbufs) > 32:
                    self.pixbufs.clear()
                self.pixbufs[key] = pb
            return self.pixbufs[key]

        def badged(self, mood, nid, size):
            """The mascot with a notification's image-data in its corner
            (mascot_icons draws file and icon badges itself)."""
            base = self.pixbuf("mascot", mood, size)
            pic = self.pixbuf("nid", nid, max(1, size * 7 // 18))
            if base is None or pic is None:
                return base
            base = base.copy()
            w, h = pic.get_width(), pic.get_height()
            x, y = base.get_width() - w, base.get_height() - h
            pic.composite(base, x, y, w, h, x, y, 1, 1, GdkPixbuf.InterpType.BILINEAR, 255)
            return base

        def set_image(self, image, spec, size):
            pb = self.pixbuf(spec[0], spec[1], size) if spec else None
            if pb is not None:
                image.set_from_pixbuf(pb)
                image.show()
            else:
                image.clear()
                image.hide()
            return pb is not None

        def set_buttons(self, buttons):
            key = tuple(b[:2] for b in buttons)
            if key == self.button_key:
                return
            self.button_key = key
            have = self.buttons.get_children()
            if len(have) != len(buttons):
                # Rebuilt only when the count changes: play <-> pause just
                # relabels the button under the pointer.
                for child in have:
                    self.buttons.remove(child)
                have = []
                for _ in buttons:
                    b = Gtk.Button()
                    b.get_style_context().add_class("ctl-icon")
                    b.set_can_focus(False)
                    b.connect("clicked", lambda b_: self.act_on(b_.island_action))
                    # The buttons' input windows are siblings of the event
                    # box's, not children: moving onto one is a plain leave
                    # for the box, so the buttons keep the hover themselves.
                    b.connect("enter-notify-event", self.on_enter)
                    b.connect("leave-notify-event", self.on_leave)
                    self.buttons.pack_start(b, False, False, 0)
                    have.append(b)
            for b, (action, glyph, tip) in zip(have, buttons):
                b.island_action = action
                b.set_label(glyph)
                b.set_tooltip_text(tip)
                # a notification's action: words, not a glyph
                (b.get_style_context().add_class if action.startswith("notif-action:") or action == "notif-goto"
                 else b.get_style_context().remove_class)("island-action")
            self.buttons.show_all()

        # -- timing helpers ----------------------------------------------------------------
        def debounce(self, name, ms, fn):
            if self.ids.get(name):
                GLib.source_remove(self.ids[name])

            def fire():
                self.ids[name] = None
                fn()
                return False
            self.ids[name] = GLib.timeout_add(ms, fire)

        def cancel(self, name):
            if self.ids.get(name):
                GLib.source_remove(self.ids[name])
                self.ids[name] = None

        def schedule_deadline(self):
            self.cancel("deadline")
            due = next_deadline(self.acts)
            if due is None:
                return
            ms = max(0, (due - time.monotonic()) * 1000) + 5
            self.ids["deadline"] = later(ms, self.on_deadline)

        def on_deadline(self):
            self.ids["deadline"] = None
            expire(self.acts, time.monotonic())
            self.update()

        def update(self):
            """After any change to acts: deadlines, then the window."""
            self.schedule_deadline()
            self.render()

        def put(self, src, act, expand_ms=None):
            """Add or replace one activity; expand_ms expands it that long."""
            act["src"] = src
            act.setdefault("ongoing", False)
            act.setdefault("key", None)
            if expand_ms:
                act["expand"], act["until"] = True, time.monotonic() + expand_ms / 1000
            else:
                act.setdefault("expand", False)
                act.setdefault("until", None)
            self.acts[src] = act
            self.dismissed = {d for d in self.dismissed if d[0] != src or d[1] == act["key"]}

        # -- the window --------------------------------------------------------------------
        def check_suppressed(self):
            if not self.dirty:
                return self.suppressed
            self.dirty = False
            try:
                monitors = hypr_request("j/monitors")
                workspaces = hypr_request("j/workspaces")
                if self.output is None:
                    self.place(monitors)
                self.fullscreen = monitor_hidden(monitors, workspaces, self.output)
                if self.dirty_game:
                    self.dirty_game = False
                    clients = hypr_request("j/clients")
                    pids = {c.get("pid") for c in clients}
                    self.env_cache = {p: e for p, e in self.env_cache.items() if p in pids}

                    def env_of(pid):
                        if pid not in self.env_cache:
                            self.env_cache[pid] = read_environ(pid)
                        return self.env_cache[pid]
                    self.game = game_running(clients, env_of)
            except (OSError, ValueError):
                self.fullscreen = self.game = False
            self.suppressed = self.fullscreen or self.game
            return self.suppressed

        def render(self):
            vis = shown(self.acts, self.cfg["ongoing"], self.dismissed, self.keep())
            suppressed = bool(vis) and self.check_suppressed()
            if suppressed:
                # Expansions do not wait for the game to end; one with no
                # end (a ringing timer's buttons) stays for afterwards.
                for a in self.acts.values():
                    if a.get("ongoing") and a.get("expand") and a.get("until") is not None:
                        a["expand"], a["until"] = False, None
                # Notifications still show: mako's popups did, over full
                # screen and games alike (a game's quiet is Do Not Disturb).
                vis = {k: a for k, a in vis.items() if k == "notify" and a.get("nid") is not None}
            if not vis:
                self.cancel("tick")
                self.cancel("measure")
                self.hovering = False
                self.want_slot(False)
                self.hide()
                return
            order = lead(vis)
            prim = vis[order[0]]
            second = vis[order[1]] if len(order) > 1 else None
            self.want_slot("media" in vis and tucked(self.cfg))
            if not self.get_visible():
                self.measure_notch(redraw=False)
            if prim["src"] == "media" and tucked(self.cfg) and not self.hovering:
                self.render_mini(prim)
                return
            self.mini.hide()
            self.card.show()
            self.outer.set_size_request(-1, -1)
            self.set_input(None)
            expanded = self.dropped(prim)
            v = describe(prim, time.time())
            ctx = self.card.get_style_context()
            for c in ctx.list_classes():
                if c.startswith("island-"):
                    ctx.remove_class(c)
            ctx.add_class(v["cls"])
            for c in v["extra_cls"]:
                ctx.add_class(c)
            if prim.get("nid") is not None and prim["nid"] != self.pop_nid:
                # a notification that just came up: the pop, once
                self.pop_nid, self.pop_until = prim["nid"], time.monotonic() + POP_MS / 1000
                self.debounce("pop", POP_MS + 20, self.render)
            if prim.get("nid") is not None and time.monotonic() < self.pop_until:
                ctx.add_class("island-pop")
            style = self.cfg.get("style") or "notch"
            ctx.add_class(f"island-style-{style}")
            if style in SHAPES:
                ctx.add_class("island-dark")
            ctx.add_class("island-expanded" if expanded else "island-compact")

            self.glyph.set_text(v["glyph"])
            gctx = self.glyph.get_style_context()
            (gctx.add_class if v["glyph_cls"] else gctx.remove_class)("island-rec-dot")
            has_small = self.set_image(self.small, v["image"], 16)
            self.glyph.set_visible(bool(v["glyph"]) and not has_small)
            self.text.set_text(v["text"])
            self.row.set_visible(not expanded)

            has_big = self.set_image(self.big, v["image"], 40) if expanded else False
            self.big_glyph.set_text(v["glyph"])
            self.big_glyph.set_visible(expanded and not has_big and bool(v["glyph"]))
            bctx = self.big_glyph.get_style_context()
            (bctx.add_class if v["glyph_cls"] else bctx.remove_class)("island-rec-dot")
            self.title.set_text(v["title"])
            self.app_label.set_text(v["app"])
            self.app_label.set_visible(expanded and bool(v["app"]))
            self.sub.set_text(v["sub"])
            self.sub.set_visible(bool(v["sub"]))
            # A notification's body runs over a few lines -- more while the
            # pointer is on it; every other line stays one line.
            self.sub.set_line_wrap(v["body"])
            self.sub.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.sub.set_lines((6 if self.hovering else 2) if v["body"] else -1)
            self.count_label.set_text(v["count"])
            self.count_label.set_visible(bool(v["count"]))
            self.set_buttons(v["buttons"])
            self.buttons.set_visible(bool(v["buttons"]))
            self.card.set_size_request(self.island_w(), -1)   # = the notch, either way
            self.revealer.set_reveal_child(expanded)

            sv = describe(second, time.time()) if second else None
            if sv and sv["image"] and sv["image"][0] == "mascot":
                self.second_glyph.hide()
                self.set_image(self.second_image, sv["image"], 16)
            else:
                self.second_image.hide()
                self.second_glyph.set_text(sv["glyph"] if sv else "")
                self.second_glyph.set_visible(bool(sv and sv["glyph"]))
                sctx = self.second_glyph.get_style_context()
                (sctx.add_class if sv and sv["glyph_cls"] else sctx.remove_class)("island-rec-dot")

            if not self.get_visible():
                self.show()
            self.resize(1, 1)         # shrink to the content (a layer surface keeps its size)
            if v["clock"] and not self.ids.get("tick"):
                self.ids["tick"] = GLib.timeout_add_seconds(1, self.on_tick)
            elif not v["clock"]:
                self.cancel("tick")

        def render_mini(self, act):
            """The media as a mini thumbnail in the notch's right slot: the
            cover (or the player's glyph), dimmed while paused."""
            self.cancel("tick")
            self.card.hide()
            mctx = self.mini.get_style_context()
            paused = act.get("status") != "Playing"
            (mctx.add_class if paused else mctx.remove_class)("island-mini-paused")
            has_art = self.set_image(self.mini_image, ("art", act["art"]) if act.get("art") else None, 24)
            self.mini_glyph.set_text(PAUSE_ICON if paused and not has_art else (act.get("icon") or MUSIC_ICON))
            self.mini_glyph.set_visible(not has_art)
            self.mini.set_tooltip_text(" — ".join(x for x in (act.get("title"), act.get("artist")) if x))
            self.mini.show()
            self.outer.set_size_request(self.island_w(), BAR_H)
            if not self.ids.get("measure"):
                # The notch changes width with what it says. No grim on a
                # timer (each one is a screencopy, a visible blip on some
                # setups): the clock's text is checked once a minute, in
                # Python, and only a change of its length measures again.
                # The other changes come as events: the bar's css
                # (want_slot, reload_settings, on_theme), the theme
                # (restyle) and the screens (relook).
                self.clock_sig = notch_text_sig()
                self.ids["measure"] = GLib.timeout_add_seconds(CLOCK_CHECK_S, self.on_measure)
            if not self.get_visible():
                self.show()
            self.resize(1, 1)
            self.set_input(self.mini)

        def set_input(self, widget):
            self.input_widget = widget
            self.apply_input()

        def apply_input(self, *_):
            """Where the pointer counts: the mini thumbnail only, or (None)
            the whole window."""
            gw = self.get_window()
            if gw is None:
                return
            w = self.input_widget
            if w is None or not w.get_visible():
                # The whole window (None is refused here; the surface clips
                # a larger rectangle to itself).
                gw.input_shape_combine_region(cairo.Region(cairo.RectangleInt(0, 0, 1 << 14, 1 << 14)), 0, 0)
                return
            a = w.get_allocation()
            gw.input_shape_combine_region(
                cairo.Region(cairo.RectangleInt(a.x, a.y, a.width, a.height)), 0, 0)

        def island_w(self):
            return self.notch_w or ISLAND_FALLBACK_W

        def want_slot(self, on):
            """Keep the notch's right end free for the thumbnail (or give it
            back), then measure the notch again once waybar has redrawn."""
            if on == self.slot:
                return
            self.slot = on
            if write_bar_css(self.cfg, on):
                self.debounce("remeasure", 450, self.measure_notch)

        def on_measure(self):
            """Once a minute while the mini thumbnail shows: measure again
            only when the clock's text changed length (9:59 -> 10:00, a
            pinned zone, the day's name)."""
            sig = notch_text_sig()
            if sig != getattr(self, "clock_sig", None):
                self.clock_sig = sig
                self.debounce("remeasure", 450, self.measure_notch)
            if self.mini.get_visible() and self.get_visible():
                return True
            self.ids["measure"] = None
            return False

        def measure_notch(self, redraw=True):
            """The notch's width off the screen's top row: one grim of a
            1-px strip. The floating "island" capsule starts 4 px down and is
            round at the ends, so its row is lower and its ends are added."""
            if not tucked(dict(self.cfg, media=True)):
                return
            try:
                mon = next(m for m in hypr_request("j/monitors") if m.get("name") == self.output)
                scale = float(mon.get("scale") or 1)
                lw = int(round(mon["width"] / scale))
                row, colour, ends = measure_spec(self.cfg, theme_accent())
                r = subprocess.run(["grim", "-g", f"{mon['x']},{mon['y'] + row} {lw}x1", "-t", "ppm", "-"],
                                   capture_output=True, timeout=3)
                got = parse_ppm(r.stdout)
            except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
                return
            if not got:
                return
            width, _h, pixels = got
            half = notch_half(pixels, width, dark=NOTCH_DARK if colour == BLACK else NOTCH_NEAR,
                              fill=rgb(colour), gap=MINI_SLOT if row else 0)
            if half is None or half < 120 or half > width // 2 - 8:
                return
            half += ends          # the capsule's round ends, above the sampled row
            w = 2 * half
            if w != self.notch_w:
                self.notch_w = w
                if redraw and self.get_visible():
                    self.render()

        def keep(self):
            """The sources shown even with the ongoing pill off."""
            return ("media",) if tucked(self.cfg) else ()

        def on_tick(self):
            if not self.get_visible():
                self.ids["tick"] = None
                return False
            rec = self.acts.get("record")
            if rec and rec.get("phase") == "live" and not rec.get("stale") \
                    and capture(REC_PID) is None:
                # A recorder that crashed or was killed leaves its pid file
                # behind, so no file event comes: the clock notices instead.
                self.refresh_record()
                if not self.get_visible():
                    self.ids["tick"] = None
                    return False
            self.render()
            return bool(self.ids.get("tick"))

        def on_revealed(self, *_):
            if not self.revealer.get_child_revealed():
                self.resize(1, 1)

        def place(self, monitors=None):
            """The island's screen; moved (hide, set_monitor, show) when it
            changed -- a layer surface changes screen only while unmapped."""
            if monitors is None:
                try:
                    monitors = hypr_request("j/monitors")
                except (OSError, ValueError):
                    monitors = []
            name = choose_monitor(self.cfg["monitor"], monitors)
            if name is None:
                try:
                    name = panelui.fallback_output()
                except Exception:     # noqa: BLE001
                    name = None
            if name is None or (name == self.output and self.get_mapped()):
                return
            origin = next(((m.get("x"), m.get("y")) for m in monitors if m.get("name") == name), None)
            display = Gdk.Display.get_default()
            for i in range(display.get_n_monitors()):
                mon = display.get_monitor(i)
                geo = mon.get_geometry()
                if (geo.x, geo.y) == origin:
                    mapped = self.get_visible()
                    if mapped:
                        self.hide()
                    GtkLayerShell.set_monitor(self, mon)
                    self.output = name
                    self.dirty = True
                    if mapped:
                        self.render()
                    return
            if self.output is None:
                self.output = name

        # -- clicks ------------------------------------------------------------------------
        def primary(self):
            vis = shown(self.acts, self.cfg["ongoing"], self.dismissed, self.keep())
            return vis[lead(vis)[0]] if vis else None

        def dropped(self, prim):
            """Down below the bar: hovered, or an alert while it is new."""
            return bool(self.hovering or (prim.get("expand") and drops(prim)))

        def on_press(self, _w, event):
            if event.type != Gdk.EventType.BUTTON_PRESS:
                return True               # the second half of a double click
            prim = self.primary()
            if event.button == 3:
                spawn(sys.executable, os.path.join(HERE, "settings.py"), "island")
            elif event.button == 2:
                self.dismiss_all()
            elif event.button == 1 and prim is not None:
                if not self.dropped(prim):
                    self.hovering = True
                    self.render()
                elif prim["src"] == "media":
                    self.act_on("play-pause")
                elif prim.get("nid") is not None:
                    # take you to the sender, then what clicking mako's
                    # popup did: the default action (else just close it)
                    self.act_on("notif-click")
                elif prim["src"] in ("railguard", "notify"):
                    self.acts.pop(prim["src"], None)
                    self.update()
            return True

        def on_enter(self, _w, event):
            if event.detail == Gdk.NotifyType.INFERIOR:
                return False
            self.cancel("leave")
            if not self.hovering and self.primary() is not None:
                self.hovering = True
                if self.queue:
                    self.refresh_notify()     # the notification's clock stops
                self.render()
            return False

        def on_leave(self, _w, event):
            if event.detail == Gdk.NotifyType.INFERIOR:
                return False          # into a window of its own

            def collapse():
                self.hovering = False
                cur = self.acts.get("notify")
                if cur and cur.get("nid") is not None:
                    item = next((it for it in self.queue if it["id"] == cur["nid"]), None)
                    if item is not None:
                        island_notify.after_hover(
                            item, time.monotonic(),
                            island_notify.waiting_count(self.queue, item) > 0)
                    self.refresh_notify()
                self.render()
            self.debounce("leave", HOVER_LEAVE_MS, collapse)
            return False

        def dismiss_all(self):
            prim = self.primary()
            if prim is not None and prim.get("nid") is not None:
                self.act_on("notif-dismiss")  # a notification: that one, into the history
                return
            for src in list(self.acts):
                a = self.acts[src]
                if a.get("nid") is not None:
                    continue              # the queue's: dismissed one at a time
                if a.get("ongoing"):
                    self.dismissed.add((src, a.get("key")))
                    a["expand"], a["until"] = False, None
                else:
                    del self.acts[src]
            self.hovering = False
            self.update()

        def act_on(self, action):
            a_media = self.acts.get("media")
            a_timer = self.acts.get("timers")
            try:
                if action in ("play-pause", "next") and a_media:
                    player = self.players.get(a_media.get("player"))
                    if player is not None:
                        player.play_pause() if action == "play-pause" else player.next()
                elif action == "rec-stop":
                    spawn(os.path.join(HERE, "record.sh"), "stop")
                elif action in ("timer-snooze", "timer-stop") and a_timer:
                    spawn(sys.executable, os.path.join(HERE, "timers.py"),
                          action.split("-")[1], str(a_timer.get("id")))
                elif action.startswith("notif-"):
                    a_notif = self.acts.get("notify")
                    nid = a_notif.get("nid") if a_notif else None
                    if nid is None:
                        return
                    if action in ("notif-click", "notif-goto"):
                        item = next((it for it in self.queue if it["id"] == nid), None) or {}
                        argv = notify_source.go_argv(self.notif_target(item, fresh=True))
                        if argv:
                            spawn(*argv)
                        if action == "notif-click" and notify_source.has_default(item):
                            spawn("makoctl", "invoke", "-n", str(nid), "default")
                        else:
                            spawn("makoctl", "dismiss", "-n", str(nid))
                    elif action == "notif-dismiss":
                        spawn("makoctl", "dismiss", "-n", str(nid))
                    else:
                        # mako runs it (the app gets ActionInvoked) and
                        # closes it, as a click on its popup would
                        spawn("makoctl", "invoke", "-n", str(nid), action.split(":", 1)[1])
                    self.drop_notification(nid)
            except GLib.Error as exc:
                print(f"island: {action}: {exc}", file=sys.stderr, flush=True)

        # -- sources: the datagram socket --------------------------------------------------
        def on_event(self, ev):
            if ev["src"] == "railguard":
                if not self.cfg["railguard"]:
                    return
                mood = ev.get("mood") if ev.get("mood") in MOODS else "alert"
                title = str(ev.get("title") or "Railguard")
                twin = island_notify.railguard_twin(self.queue, title, time.monotonic()) \
                    if self.notifying() else None
                if twin is not None:
                    # its notification came first: that card shows it, with the mood
                    twin["mood"] = mood
                    self.refresh_notify()
                    return
                self.put("railguard", {"title": title, "body": str(ev.get("body") or ""),
                                       "mood": mood, "at": time.monotonic()},
                         RAILGUARD_MS)
            elif ev["src"] == "notify":
                if self.notifying():
                    return            # the bus brings the notification itself
                if not self.cfg["notify"] or ev.get("urgency") == "low":
                    return
                self.put("notify", {"app": str(ev.get("app") or ""),
                                    "summary": str(ev.get("summary") or ""),
                                    "body": str(ev.get("body") or "")}, NOTIFY_MS)
            self.update()

        # -- sources: notifications (the session bus) --------------------------------------
        def notifying(self):
            """Notifications are the island's now: the setting is on and
            mako's popups are off (our mode is in)."""
            return bool(self.cfg["notifications"] and self.mode_on)

        def connect_monitor(self):
            """A dedicated session-bus connection that becomes a monitor of
            the Notify traffic (the docstring's NOTIFICATIONS). Async only:
            the filter runs in GDBus' own thread."""
            self.ids["bus-retry"] = None
            if not self.cfg["notifications"] or self.bus_mon is not None:
                return False
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                try:
                    owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                          "org.freedesktop.DBus", "GetNameOwner",
                                          GLib.Variant("(s)", (NOTIF_NAME,)), GLib.VariantType.new("(s)"),
                                          Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                except GLib.Error:
                    owner = None      # no mako yet: watch_mako says when
                addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
                conn = Gio.DBusConnection.new_for_address_sync(
                    addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                    | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
            except GLib.Error as exc:
                print(f"island: no session bus monitor ({exc})", file=sys.stderr, flush=True)
                self.ids["bus-retry"] = GLib.timeout_add_seconds(RECONNECT_S * 5, self.connect_monitor)
                return False
            conn.set_exit_on_close(False)
            me = conn.get_unique_name()

            def bus_filter(_c, msg, incoming):
                # GDBus' thread. Our own call goes out, its answer comes in;
                # everything monitored is dropped here, so GDBus never
                # answers a monitored call (the bus would cut us off).
                if not incoming or msg.get_destination() == me:
                    return msg
                try:
                    ev = bus_event(msg, owner)
                except Exception as exc:  # noqa: BLE001 - one odd message is not the island's end
                    print(f"island: bus message: {exc}", file=sys.stderr, flush=True)
                    ev = None
                if ev is not None:
                    GLib.idle_add(lambda: (self.on_bus(conn, ev), False)[1])
                return None
            conn.add_filter(bus_filter)
            conn.connect("closed", self.on_bus_closed)
            rules = [f"type='method_call',interface='{NOTIF_NAME}',member='Notify'",
                     f"type='signal',interface='{NOTIF_NAME}',member='NotificationClosed'"]
            rules += [f"type='method_call',interface='{MAKO_IFACE}',member='{m}'"
                      for m in MAKO_MODE_CALLS]
            if owner:
                rules.append(f"type='method_return',sender='{owner}'")
            self.bus_mon, self.bus_owner = conn, owner

            def ready(c, res):
                try:
                    c.call_finish(res)
                except GLib.Error as exc:
                    print(f"island: BecomeMonitor: {exc}", file=sys.stderr, flush=True)
                    self.drop_monitor(retry=True)
                    return
                if c is self.bus_mon and owner:
                    self.take_popups()
            conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.Monitoring",
                      "BecomeMonitor", GLib.Variant("(asu)", (rules, 0)), None, Gio.DBusCallFlags.NONE,
                      5000, None, ready)
            return False

        def take_popups(self):
            """The monitor is up and mako is there: its popups off, ours on,
            and whatever it shows right now comes over."""
            if not self.cfg["notifications"]:
                return
            if not set_mako_mode(True):
                print("island: makoctl mode -a island failed; mako keeps its popups",
                      file=sys.stderr, flush=True)
                return
            self.mode_on = True
            try:
                listed = json.loads(makoctl("list", "-j") or "[]")
            except ValueError:
                listed = []
            have = {it["id"] for it in self.queue}
            for entry in listed if isinstance(listed, list) else []:
                if isinstance(entry, dict) and entry.get("id") and entry["id"] not in have:
                    self.admit(island_notify.from_mako(entry))
            self.refresh_notify()

        def give_back_popups(self):
            """Mako draws its own again; what the island still had shows
            there (mako re-reads its rules when a mode goes)."""
            if self.mode_on:
                set_mako_mode(False)
            self.mode_on = False
            self.queue.clear()
            self.notif_images.clear()
            self.pending.clear()
            if (self.acts.get("notify") or {}).get("nid") is not None:
                del self.acts["notify"]
            self.cancel("notify-wake")
            self.update()

        def drop_monitor(self, retry=False):
            conn, self.bus_mon = self.bus_mon, None
            if conn is not None and not conn.is_closed():
                try:
                    conn.close_sync(None)
                except GLib.Error:
                    pass
            self.give_back_popups()
            if retry and self.cfg["notifications"] and not self.ids.get("bus-retry"):
                self.ids["bus-retry"] = GLib.timeout_add_seconds(RECONNECT_S * 5, self.connect_monitor)

        def on_bus_closed(self, conn, _vanished, error):
            if conn is not self.bus_mon:
                return            # one we let go of ourselves
            print(f"island: bus monitor closed ({error.message if error else 'no reason'})",
                  file=sys.stderr, flush=True)
            self.drop_monitor(retry=True)

        def on_bus(self, conn, ev):
            if conn is not self.bus_mon:
                return
            kind = ev[0]
            now = time.monotonic()
            if kind == "call":
                self.pending = {k: v for k, v in self.pending.items() if now - v[1] < PENDING_S}
                self.pending[ev[1]] = (ev[2], now)
                self.learn_pid(ev[1][0])
            elif kind == "return":
                got = self.pending.pop(ev[1], None)
                if got is not None and self.mode_on:
                    self.notif_arrived(ev[2], got[0], ev[1][0])
            elif kind == "closed":
                if island_notify.remove(self.queue, ev[1]):
                    self.notif_images.pop(ev[1], None)
                    self.refresh_notify()
            elif kind == "modes" and self.queue:
                # Do Not Disturb went on or off (or a filter, a reload): what
                # mako would show now -- once mako has taken the call
                self.debounce("modes", MODES_SETTLE_MS, self.revisit_notify)

        def revisit_notify(self):
            modes = mako_modes()
            if modes is None or not self.queue:
                return
            if island_notify.revisit(self.queue, modes, island_notify.mako_rules(MAKO_CONFIG)):
                self.refresh_notify()

        def watch_mako(self):
            """Who owns org.freedesktop.Notifications, on the ordinary bus
            connection (a monitor is not told: dbus-broker does not pass the
            bus' own NameOwnerChanged to monitors -- tested)."""
            Gio.bus_watch_name(Gio.BusType.SESSION, NOTIF_NAME, Gio.BusNameWatcherFlags.NONE,
                               lambda _c, _n, owner: self.on_mako(owner),
                               lambda _c, _n: self.on_mako(None))

        def on_mako(self, owner):
            if owner == self.bus_owner:
                return            # the one the monitor already follows
            # mako restarted (or went): a new one has no island mode, and
            # its replies come from a new name -- start over.
            print(f"island: mako is {'now ' + owner if owner else 'gone'}", flush=True)
            self.mode_on = False          # that mako took the mode with it
            if self.bus_mon is not None:
                self.drop_monitor()
            self.bus_owner = owner
            if self.cfg["notifications"]:
                self.connect_monitor()

        def notif_arrived(self, nid, args, sender=None):
            app, _replaces, icon, summary, body, actions, hints, expire, image = args
            item = island_notify.from_notify(nid, app, icon, summary, body, actions, hints, expire)
            item["pids"] = self.caller_pids.get(sender) or []
            item["data"] = False
            if image is not None:
                w, h, stride, alpha, bps, _ch, data = image
                try:
                    self.notif_images[nid] = GdkPixbuf.Pixbuf.new_from_bytes(
                        data, GdkPixbuf.Colorspace.RGB, bool(alpha), bps, w, h, stride)
                    item["data"] = True
                except (GLib.Error, TypeError, ValueError) as exc:
                    print(f"island: image-data: {exc}", file=sys.stderr, flush=True)
            self.admit(item)

        def learn_pid(self, sender):
            """The caller's process and its parents, asked of the bus and
            read from /proc right at the call: notify-send waits for mako's
            reply and is gone a moment later, and with it the way to its
            terminal. Which window sent it: notify_source.find_window. One
            short bus round trip (PID_ASK_MS at most), once per caller."""
            if not sender or sender in self.caller_pids:
                return
            if len(self.caller_pids) > CALLER_PIDS_MAX:
                self.caller_pids.clear()
            self.caller_pids[sender] = []
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                pid = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                    "GetConnectionUnixProcessID", GLib.Variant("(s)", (sender,)),
                                    GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, PID_ASK_MS,
                                    None).unpack()[0]
            except GLib.Error:
                return
            self.caller_pids[sender] = notify_source.ancestors(pid, notify_source.ppid_of)

        def notif_target(self, item, fresh=False):
            """Where clicking the notification leads (notify_source.target),
            worked out once per item, again at the click (the window may
            have gone). None: nowhere."""
            if not item:
                return None
            if fresh or "target" not in item:
                try:
                    clients = hypr_request("j/clients")
                except (OSError, ValueError):
                    clients = []
                try:
                    item["target"] = notify_source.target(item, clients, notify_source.installed_apps(),
                                                          notify_source.ppid_of)
                except Exception as exc:      # never let a lookup break the queue
                    print(f"island: notification source: {exc}", file=sys.stderr, flush=True)
                    item["target"] = None
            return item["target"]

        def admit(self, item):
            """One notification into the queue: how long, whether mako would
            have shown it, whether it is the twin of a Railguard alert."""
            now = time.monotonic()
            item["dur"] = island_notify.duration(item, read_notify_conf())
            modes = mako_modes() or ["default"]
            item["visible"] = island_notify.mako_visible(item, modes,
                                                         island_notify.mako_rules(MAKO_CONFIG))
            rail = self.acts.get("railguard")
            if item["visible"] and island_notify.is_railguard_twin(item, rail, now):
                item["mood"] = rail.get("mood")
                del self.acts["railguard"]        # one card: the notification
            self.seq += 1
            island_notify.upsert(self.queue, item, now, self.seq)
            self.refresh_notify()

        def drop_notification(self, nid):
            island_notify.remove(self.queue, nid)
            self.notif_images.pop(nid, None)
            self.refresh_notify()

        def refresh_notify(self):
            """The queue's turn: what shows now, what goes to the history,
            when to look again."""
            self.cancel("notify-wake")
            now = time.monotonic()
            old = self.acts.get("notify")
            hovered = self.hovering and old is not None and old.get("nid") is not None
            cur, done, wake = island_notify.pick(self.queue, now, hovered)
            for nid in done:
                self.notif_images.pop(nid, None)
                spawn("makoctl", "dismiss", "-n", str(nid))
            if cur is None:
                if old is not None and old.get("nid") is not None:
                    del self.acts["notify"]
            else:
                self.notif_target(cur)
                self.put("notify", notify_act(cur, island_notify.waiting_count(self.queue, cur)))
            if wake is not None:
                def woke():
                    self.ids["notify-wake"] = None
                    self.refresh_notify()
                self.ids["notify-wake"] = later(max(0, (wake - now) * 1000) + 10, woke)
            self.update()

        # -- sources: timers ---------------------------------------------------------------
        def refresh_timers(self):
            if timers is None or not self.cfg["timers"]:
                if self.acts.pop("timers", None):
                    self.update()
                return
            wall = time.time()
            try:
                entries, rings = timers.running(), timers.ringing()
            except Exception as exc:  # noqa: BLE001 - a half-written file, say
                print(f"island: timers: {exc}", file=sys.stderr, flush=True)
                entries, rings = [], []
            self.schedule_timer_wake(entries, wall)
            got = timer_activity(entries, rings, wall, names=timers.NAMES)
            old = self.acts.get("timers")
            if got is None:
                if old and old.get("kind") == "ending" and wall >= old.get("due", 0) - 1:
                    self.put("timers", {"kind": "done", "label": old.get("label"),
                                        "icon": old.get("icon"), "id": old.get("id")}, TIMER_DONE_MS)
                elif old and old.get("kind") != "done":
                    del self.acts["timers"]
                else:
                    return
                self.update()
                return
            key = f"{got['kind']}:{got['id']}"
            due = next((e.get("due") for e in entries if e.get("id") == got["id"]), wall)
            fields = {"kind": got["kind"], "id": got["id"], "label": got["label"],
                      "icon": timers.ICONS.get(got["tkind"]) or TIMER_ICON, "due": due}
            if old and old.get("key") == key:
                old.update(fields)
            elif got["kind"] == "ringing":
                self.put("timers", dict(fields, ongoing=True, key=key, expand=True, until=None))
            else:
                self.put("timers", dict(fields, ongoing=True, key=key), TIMER_ENTER_MS)
            self.update()

        def schedule_timer_wake(self, entries, wall):
            """The one wake-up the timers need: when the next one enters its
            last minute, or (one is in it) just after it is due -- to see it
            ring or go. Every timers.json change makes it again."""
            self.cancel("timer-wake")
            wait = next_timer_wake(entries, wall)
            if wait is None:
                return
            if wait <= 0:
                soonest = min(e["due"] for e in entries
                              if not e.get("paused") and e.get("due", 0) >= wall)
                wait = soonest - wall + 2
            # Capped: the GLib clock stops in suspend, so a long wait is
            # worked out again from the wall clock now and then.
            secs = max(1, math.ceil(min(wait, TIMER_RECHECK_S)))

            def wake():
                self.ids["timer-wake"] = None
                self.refresh_timers()
                return False
            self.ids["timer-wake"] = GLib.timeout_add_seconds(secs, wake)

        # -- sources: the recording --------------------------------------------------------
        def refresh_record(self):
            if not self.cfg["record"]:
                if self.acts.pop("record", None):
                    self.update()
                return
            got = capture(REC_PID)
            old = self.acts.get("record")
            live = old is not None and old.get("phase") == "live"
            if got:
                self.record_tries = 0
                started, target = got
                if live:
                    old["target"] = target
                    self.render()
                    return
                try:
                    with open(REC_PID) as fh:
                        pid, out = (fh.read().split("\n") + ["", ""])[:2]
                except OSError:
                    pid = out = ""
                self.put("record", {"phase": "live", "started": started, "target": target,
                                    "pid": pid.strip(), "out": out.strip(),
                                    "ongoing": True, "key": started},
                         RECORD_START_MS)
            elif not live:
                if os.path.exists(REC_PID) and self.record_tries < 3:
                    # Written a moment before setsid became the recorder.
                    self.record_tries += 1
                    self.debounce("record-retry", RECORD_RETRY_MS, self.refresh_record)
                return
            elif os.path.exists(REC_PID) and not old.get("stale"):
                # The recorder is gone but its file is not: record.sh removes
                # it a moment after a stop. Look once more before calling it
                # a crash (a stale file stays until record.sh runs again).
                old["stale"] = True
                self.debounce("record-retry", RECORD_RETRY_MS, self.refresh_record)
                return
            else:
                how = "stopped" if old.get("stale") and os.path.exists(REC_PID) \
                    else record_outcome(old, time.time())
                if how == "failed":
                    del self.acts["record"]
                else:
                    self.put("record", {"phase": how, "target": old.get("target")},
                             RECORD_SAVED_MS)
            self.update()

        # -- sources: media ----------------------------------------------------------------
        def start_media(self):
            if Playerctl is None:
                return
            try:
                self.manager = Playerctl.PlayerManager()
            except GLib.Error as exc:
                print(f"island: Playerctl: {exc}", file=sys.stderr, flush=True)
                return
            self.manager.connect("name-appeared", lambda _m, name: self.add_player(name))
            self.manager.connect("player-vanished", self.on_player_vanished)
            for name in self.manager.props.player_names:
                self.add_player(name)
            self.media_ready = True
            self.refresh_media(quiet=True)

        def add_player(self, name):
            if any(s in name.name for s in SKIP_PLAYERS):
                return
            try:
                player = Playerctl.Player.new_from_name(name)
            except GLib.Error:
                return
            self.manager.manage_player(player)
            player.connect("playback-status", lambda *_: self.refresh_media())
            player.connect("metadata", lambda *_: self.refresh_media())
            self.players[name.instance] = player
            if self.media_ready:
                self.refresh_media()

        def on_player_vanished(self, _manager, player):
            for inst, p in list(self.players.items()):
                if p == player:
                    del self.players[inst]
            self.refresh_media()

        def refresh_media(self, quiet=False):
            if not self.cfg["media"]:
                self.media_seen = None
                if self.acts.pop("media", None):
                    self.update()
                return
            statuses, metas = {}, {}
            for inst, p in self.players.items():
                try:
                    statuses[inst] = p.props.playback_status.value_nick
                    meta = p.props.metadata
                    metas[inst] = (meta.unpack() if meta is not None else {}), p.props.player_name
                except (GLib.Error, AttributeError):
                    continue
            try:
                with open(SELECTED) as fh:
                    selected = fh.readline().strip() or None
            except OSError:
                selected = None
            inst = pick_player(list(statuses), statuses, selected)
            old = self.acts.get("media")
            if inst is None:
                self.media_seen = None
                if old:
                    del self.acts["media"]
                    self.update()
                return
            meta, pname = metas[inst]
            title, artist = media_text(meta)
            st = statuses[inst]
            seen = (inst, title, st)
            if seen == self.media_seen:
                return                # a metadata signal that changed nothing shown
            before, self.media_seen = self.media_seen, seen
            changed = before is None or before[:2] != seen[:2] or \
                {before[2], st} == {"Playing", "Paused"}
            playing = st == "Playing"
            mini = tucked(self.cfg)
            act = {"player": inst, "title": title or pname, "artist": artist, "status": st,
                   "art": art_path(meta.get("mpris:artUrl")), "icon": player_icon(pname),
                   # In the notch the thumbnail stays while paused, like the
                   # bar pill it replaces; and a change only updates it.
                   "ongoing": playing or mini, "key": title}
            if mini:
                if old is not None:
                    old.update({k: act[k] for k in ("player", "title", "artist", "status", "art", "icon",
                                                     "ongoing", "key")})
                else:
                    self.put("media", act)
                self.update()
                return
            if quiet:
                if playing:
                    self.put("media", act)
            elif changed and (playing or old is not None or before is None or before[1] != title):
                self.put("media", act, MEDIA_MS)
            elif old is not None:
                old.update({k: act[k] for k in ("player", "title", "artist", "status", "art", "icon",
                                                 "ongoing", "key")})
                if not playing and old.get("until") is None:
                    old["expand"], old["until"] = False, time.monotonic() + MEDIA_MS / 1000
            elif playing:
                self.put("media", act)
            self.update()

        # -- sources: Hyprland -------------------------------------------------------------
        def connect_events(self):
            self.ids["reconnect"] = None
            folder = hypr_dir()
            try:
                if not folder:
                    raise OSError("no Hyprland instance")
                import hyprbus      # the shared relay (only what on_hypr reads), or socket2 directly
                s = hyprbus.connect(HYPR_EVENTS, direct=os.path.join(folder, ".socket2.sock"))
            except OSError:
                self.ids["reconnect"] = GLib.timeout_add_seconds(RECONNECT_S, self.connect_events)
                return False
            self.events, self.events_buf = s, b""
            GLib.io_add_watch(s.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_hypr)
            self.dirty = self.dirty_game = True
            return False

        def on_hypr(self, _fd, cond):
            try:
                data = self.events.recv(65536) if cond & GLib.IO_IN else b""
            except OSError:
                data = b""
            if not data:
                self.events.close()
                self.events = None
                self.ids["reconnect"] = GLib.timeout_add_seconds(RECONNECT_S, self.connect_events)
                return False
            *lines, self.events_buf = (self.events_buf + data).split(b"\n")
            look = place = False
            for line in lines:
                if line.startswith((b"openwindow>>", b"closewindow>>")):
                    self.dirty_game = True
                name = line.split(b">>", 1)[0]
                if name in (b"fullscreen", b"workspacev2", b"focusedmonv2", b"activewindowv2",
                            b"movewindowv2", b"openwindow", b"closewindow", b"monitoraddedv2",
                            b"monitorremoved"):
                    look = True
                if name in (b"monitoraddedv2", b"monitorremoved") or \
                        (name == b"focusedmonv2" and self.cfg["monitor"] == "focused"):
                    place = True
            if look:
                self.dirty = True
                self.debounce("look", FS_DEBOUNCE_MS, lambda p=place: self.relook(p))
            return True

        def relook(self, place=False):
            if place:
                self.place()
                # A screen came or went: the bar (and its notch) may be laid
                # out again on another width.
                self.debounce("remeasure", 450, self.measure_notch)
            if self.acts:             # nothing to show: look again when there is
                self.render()

        # -- sources: files ----------------------------------------------------------------
        def watch(self, folder, handler):
            try:
                os.makedirs(folder, exist_ok=True)
                mon = Gio.File.new_for_path(folder).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None)
            except (GLib.Error, OSError) as exc:
                print(f"island: cannot watch {folder}: {exc}", file=sys.stderr, flush=True)
                return
            wanted = (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                      Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.RENAMED,
                      Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.MOVED_OUT)

            def changed(_m, gfile, other, event):
                if event in wanted:
                    names = {f.get_basename() for f in (gfile, other) if f is not None}
                    handler(names)
            mon.connect("changed", changed)
            self.monitors_keep.append(mon)

        def on_state(self, names):
            if TIMERS_FILE in names:
                self.debounce("timers", 50, self.refresh_timers)
            # dock.json too: the top bar switched off or on changes effective()
            if os.path.basename(SETTINGS_FILE) in names or "dock.json" in names:
                self.debounce("settings", SETTINGS_DEBOUNCE_MS, self.reload_settings)

        def on_rings(self, names):
            if any(n.startswith("ring-") and n.endswith(".json") for n in names):
                self.debounce("timers", 50, self.refresh_timers)

        def on_runtime(self, names):
            if os.path.basename(REC_PID) in names:
                self.record_tries = 0
                self.debounce("record", 50, self.refresh_record)

        def on_theme(self, names):
            if names & set(THEME_FILES):
                self.debounce("theme", THEME_DEBOUNCE_MS, self.restyle)
            if any(n.endswith(".css") for n in names):
                # The bar's look changed (a theme, Settings > Bar): its notch
                # may be wider or narrower now. After waybar's own reload.
                self.debounce("remeasure", 900, self.measure_notch)

        def restyle(self):
            load_css()
            # notch_color "theme": the bar's notch takes the new accent too
            if write_bar_css(self.cfg, self.slot):
                self.debounce("remeasure", 450, self.measure_notch)
            self.pixbufs.clear()      # the mascot is the theme's
            if self.get_visible():
                self.render()

        def reload_settings(self):
            new = effective(read_settings())
            if not new["enabled"]:
                print("island: switched off", flush=True)
                Gtk.main_quit()
                return
            old, self.cfg = self.cfg, new
            if old["match_bar"] and not new["match_bar"]:
                self.notch_w = None   # no bar's centre to be as wide as: island_w's own width
            if any(new[k] != old[k] for k in ("style", "notch_color", "outline")):
                load_css()
            if write_bar_css(new, self.slot):
                self.debounce("remeasure", 450, self.measure_notch)
            if not new["railguard"]:
                self.acts.pop("railguard", None)
            if not new["notify"] and (self.acts.get("notify") or {}).get("nid") is None:
                self.acts.pop("notify", None)     # the scripts/notify line, not the queue's
            if new["notifications"] != old["notifications"]:
                if new["notifications"]:
                    self.connect_monitor()
                else:
                    self.drop_monitor()
            if new["timers"] != old["timers"]:
                self.refresh_timers()
            if new["record"] != old["record"]:
                self.refresh_record()
            if new["media"] != old["media"]:
                self.media_seen = None
                self.refresh_media(quiet=True)
            if new["monitor"] != old["monitor"]:
                self.output = None
                self.place()
            self.update()

        def start(self):
            write_bar_css(self.cfg, self.slot)
            self.debounce("remeasure", 450, self.measure_notch)
            self.watch(STATE_DIR, self.on_state)
            self.watch(RING_DIR, self.on_rings)
            self.watch(RUNTIME, self.on_runtime)
            self.watch(GEN_DIR, self.on_theme)
            self.connect_events()
            self.place()
            self.start_media()
            self.refresh_timers()
            self.refresh_record()
            self.connect_monitor()
            self.watch_mako()
            self.update()

    load_css()
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), island_css,
                                             Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    island = Island()

    try:
        os.unlink(SOCK)
    except OSError:
        pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(SOCK)
    os.chmod(SOCK, 0o600)
    tell_player()                 # the socket is how player.py knows the island is up

    def on_sock(_fd, _cond):
        while True:               # every datagram, not just the newest
            try:
                data = sock.recv(8192, socket.MSG_DONTWAIT)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            ev = parse_event(data)
            if ev:
                island.on_event(ev)
        return True

    GLib.io_add_watch(sock.fileno(), GLib.IO_IN, on_sock)
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ImportError, ValueError):
        signal_add = GLib.unix_signal_add
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (Gtk.main_quit(), False)[1])
    # island.service's WatchdogSec: a ping from the main loop, so an island
    # that hangs is ended (and its ExecStopPost gives mako its popups back).
    try:
        watchdog_s = int(os.environ.get("WATCHDOG_USEC", "0")) / 2e6
    except ValueError:
        watchdog_s = 0
    if watchdog_s > 0:
        sd_notify("WATCHDOG=1")
        GLib.timeout_add_seconds(max(1, int(watchdog_s)), lambda: (sd_notify("WATCHDOG=1"), True)[1])
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (island.reload_settings(), True)[1])
    try:
        island.start()
        Gtk.main()
    finally:
        if island.mode_on:
            set_mako_mode(False)  # mako's popups back (ExecStopPost does it too)
        sock.close()
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        tell_player()             # the bar's pill takes the media back
    return 0


# -- CLI -----------------------------------------------------------------------------------
def test_event(src):
    """A sample, through island_events like the real senders."""
    sys.path.insert(0, HERE)
    import island_events
    if src == "railguard":
        sent = island_events.railguard("Railguard: test", "This is how an alert looks on the island.",
                                       "alert")
    elif read_settings()["notifications"] and os.path.exists(SOCK):
        # a real notification: the island shows it the way it shows any
        try:
            r = subprocess.run([NOTIFY_SCRIPT, "-a", "island.py", "Island test",
                                "A notification, as the island shows it: hover it for the rest."],
                               capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"island.py: {NOTIFY_SCRIPT}: {exc}", file=sys.stderr)
            return 1
        return 0 if r.returncode == 0 else 1
    else:
        sent = island_events.notify("Island test", "A notification's summary, as the island shows it.",
                                    "island.py", "normal")
    if not sent:
        print("island.py: the island is not running (island.py set on)", file=sys.stderr)
        return 1
    if not read_settings()[src]:
        print(f"island.py: sent, but the island does not show {src} (island.py set {src} on)",
              file=sys.stderr)
    return 0


def main(argv):
    args = argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "daemon" and len(args) == 1:
        return daemon()
    if cmd == "status":
        st = status()
        if "--json" in args:
            print(json.dumps(st))
        else:
            print_status(st)
    elif cmd == "set" and len(args) == 3:
        set_key(args[1], args[2])
    elif cmd == "set" and len(args) == 2 and args[1].lower() in ("on", "off"):
        set_key("enabled", args[1].lower())
    elif cmd == "test" and len(args) <= 2 and (args[1:] or ["notify"])[0] in ("notify", "railguard"):
        return test_event((args[1:] or ["notify"])[0])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
