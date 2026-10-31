#!/usr/bin/env python3
"""Dock and taskbar: one engine, two layouts. "dock" is a floating card of
app icons at the bottom (or the left / right) of the screen, macOS-like;
"taskbar" is a full-width strip along the bottom, Windows-like: a start
button that opens the launcher (or a classic start menu), the workspace in
front, a button per app (or per window) with its icon and title, what is using the
camera, the microphone, the location or the screen, the system tray, the
weather, the network, the sound, the battery, a clock and the notifications.
Both show the pinned apps and every app that runs, grouped by app.

    dock.py daemon                 run it (dock.service); exits at once when
                                   it is switched off
    dock.py status [--json]        settings, service state, monitors, the
                                   pinned apps
    dock.py set KEY VALUE          one setting (below); on|off for switches
    dock.py set on|off             = set enabled on|off: enables and starts,
                                   or stops and disables, dock.service
    dock.py pin APP_ID             pin an app (a desktop id; ".desktop" may
                                   be left off); unpin APP_ID takes it off
    dock.py move APP_ID -1|+1      a pinned app one place left / right
    dock.py follow-theme           the theme's layout now, if follow_theme
                                   (theme.py runs it at every switch)

SETTINGS ($XDG_STATE_HOME/hypr/dock.json, or DOCK_SETTINGS=<path>;
Settings > Bar & toolbox > Dock & taskbar):

    enabled     on at all (false: the service is stopped)
    layout      "dock" or "taskbar"
    position    the dock's edge: "bottom", "left" or "right" (the taskbar
                is always at the bottom: the bar has the top)
    autohide    the dock only: "never" (it keeps its strip: windows stay
                clear of it), "overlap" (it steps away while a window
                covers it) or "always" (only while the pointer is on it).
                Hidden, it is a thin hot edge: touch the edge to bring it back
    icon_size   the dock's icons, 24-96 px (48); the taskbar's are 24
    monitors    "main" (the main screen, screens.py's primary: every window
                of every screen shows there) or "all" (one per screen, each
                showing the windows on its own screen)
    combine     the taskbar: one button per app (true) or one per window
    labels      the taskbar: the window titles beside the icons (true)
    tray        the taskbar: the system tray (true)
    clock       the taskbar: the clock (true); the dock with top_bar off:
                a time tile and a date tile (DOCK TILES below)
    weather     the taskbar: the weather, wttr.py's pill (true); the dock
                with top_bar off: a weather tile
    network     the taskbar: the network, network.py's pill (true)
    sound       the taskbar: the volume; scroll for louder / quieter,
                right-click mutes (true)
    workspaces  the taskbar: the workspace in front, after the start button
                (the bar's ext/workspaces); click: the window overview (true)
    notifications
                the taskbar: the bell, right of the clock; click the
                notifications panel, right-click Do Not Disturb (true)
    battery     the taskbar: the charge, while there is a battery (true)
    privacy     the taskbar, and the dock with top_bar off: what records the
                screen or uses the microphone, the camera or the location,
                only while something does (true; PILLS below)
    start_menu  the taskbar's start button: "launcher" (launcher.py, with a
                Power button at its foot while the taskbar runs) or
                "classic" (a cascading menu: the pinned apps, Programs by
                category, Files, Settings, Search, Run, Lock, Sleep, Shut
                down -- the power panel, which asks first)
    previews    hovering a running app lists its windows, with pictures (true)
    top_bar     the top bar at all while this runs (true). Off, the bar is
                not started (TOP BAR OFF below); only while enabled
    follow_theme
                a theme that names its layout sets it (false; THEME
                LAYOUT below)
    theme_saved your own enabled / layout / top_bar while a theme's is in
                place, put back after it (written by follow-theme, never by
                hand; null otherwise)
    magnify     the dock only: the icons under the pointer grow, macOS-like
                (EFFECTS below): "theme" (the theme's dock.magnify: orchard's
                yes), "on" or "off"
    pinned      the pinned apps' desktop ids, in order. Unset (a first start):
                the browser, the file manager and the terminal default-apps.py
                knows
    tile_order  the dock's tiles (DOCK TILES) as dragged: "time", "date",
                "sound", ... in order; unset, DOCK_TILE_ORDER's

WHERE IT ALL COMES FROM -- nothing polls; idle, the process sleeps in the
GLib loop:

    windows     Hyprland's events through hyprbus.py (openwindow,
                closewindow, activewindowv2, movewindowv2, windowtitlev2,
                workspacev2, fullscreen, urgent, monitors): each burst is
                one read of clients / monitors / workspaces over the request
                socket, debounced. Titles only matter with the taskbar's
                labels or a preview open, otherwise their events are dropped
    apps        notify_source.py's installed_apps() and variants(): a window
                is the installed app whose StartupWMClass, id, program or
                name matches its class (best first: the class, then the id);
                an app nobody installed still shows, with an icon named
                after its class (Steam games: steam_icon_<id>)
    tray        a StatusNotifierHost of its own, registered with the
                org.kde.StatusNotifierWatcher waybar-toolbox already runs
                (several hosts are allowed: the toolbox keeps its tray, and
                the watcher stays the toolbox's). Left click Activate,
                middle SecondaryActivate, right the item's com.canonical.
                dbusmenu as a menu (ContextMenu when it has none). Passive
                items are hidden, as waybar hides them
    clock       region.py's 12 / 24 hour and date preferences, without the
                seconds: one wake-up a minute; a ja theme's date as the top
                bar writes it, "10月30日(金)" (waybar/generated/lang)
    look        dock.css next to this file; it imports waybar/panel.css, so
                every theme's colours and fonts come along, and the theme's
                own dock.css last (every theme has one: its dock and its
                taskbar). The start button's word is the theme's dock.start
                (waybar/generated/bar.conf start=), its glyph bar.logo=,
                magnification the theme's dock.magnify (magnify=)

DOCK TILES: with the top bar off the dock stands in for it (the main
screen's dock, as the toolbox button). First an Apps button (the launcher,
or the classic menu as start_menu says). After the toolbox line, tiles a
little bigger than an icon (TILE_GROW), each as its setting says:
    submap        the key mode (SUPER+R's resize), only while one is on;
                  click: leave it
    workspaces    the one in front, "of N"; click: the window overview,
                  scroll: the next / previous one
    media         play / pause while something plays (player.py); click:
                  play / pause, right: next, middle: the media panel,
                  scroll: another player
    notifications the bell and the unread count; click: the panel,
                  right: Do Not Disturb
    language      the keyboard layout ("US"), and fcitx5's input method
                  when it is on one ("Mozc"); click: the language panel,
                  right: the next layout
    network       its glyph over the network's name; click: the network
                  panel, right: nmtui
    sound         the volume; click: the audio panel, scroll: louder /
                  quieter, right: mute, middle: mute the microphone
    battery       the charge, with the bolt while charging (while there is
                  a battery); click: Power & lock
    clock         the time, and the date as a calendar leaf (the weekday
                  over the day); click: the clock / calendar panel
    weather       its glyph over the temperature; click: the forecast,
                  right: wttr.in
What is on the dock is not in the toolbox card: they take the top bar's
matching pills (bar_takeover; the keyboard layout: card_pills), and the
card leaves out its Battery row with the battery tile (bar-settings.py
toolbox-config-path). With the top bar on they stay off: a dock theme's bar has them.
Every app's icon carries a badge with its unread notifications (dock layout,
notifications on), and files dropped on an app open with it.

CLICKS: an app that is not running starts (`uwsm app -- <id>`, like
notify_source.go_argv); one that is goes to its window (hl.dsp.focus by its
address, validated). Several windows: the most recent, and clicking again
while one of them has focus goes to the next. Hyprland has no minimize, so a
focused app stays as it is. Middle click: a new one (its "new-window" action
when the app has one). Right click: the app's own actions (the desktop
file's), New window, Pin / Unpin, Move left / right, Close window(s), and
these settings. Drag an app along the dock to move it: it swaps places with
each icon it passes as you go, and stays where you let go -- pinned apps
among the pinned, a running app among them to pin it there, running apps
among themselves (until the dock restarts). The tiles after the line are
dragged the same way, among themselves (tile_order). Files dragged from a file
manager onto an app open with it.

TOP BAR: what the taskbar shows leaves the top bar while it runs -- the date
and time (custom/day, custom/clock, custom/menuclock) with clock on, the
weather, the network, the sound (pulseaudio), the workspaces, the
notifications, the battery and the privacy pills (custom/recording, mic,
camera, location) with theirs, the power pill always, its menu being the
start button's now, and the keyboard layout (CARD_PILLS) always -- that one
into the toolbox card instead (bar-settings.py toolbox-config-path)
(bar_takeover). The dock takes the keyboard layout too, and the privacy
pills only with the top bar off (TOP BAR OFF), so they are never in the
closed toolbox card. waybar has no
way to hide a built-in module from outside, so the bar starts from another
config instead: its service runs waybar-main.sh, which asks bar-settings.py
config-path -- ~/.config/waybar/config itself, or generated/config-taskbar,
that file with those pills hidden. `dock.py set` restarts the bar when what
is taken over changes (switched on or off, the layout, one of those four).
The taskbar's buttons run the same scripts: network.py watch and `pactl
subscribe` (then `wpctl get-volume`) as long-lived watchers, started again
if they end; wttr.py every 30 min, sooner after a stale answer.

PILLS: the other buttons run the bar's scripts too, the same way: recording.py
watch and privacy.py watch mic|camera|location as watchers (each hidden while
its text is empty, as on the bar), notifications.py every NOTIFY_S and at
once on SIGUSR2 -- bar_signals.py poke("notifications") sends it here as
well, as waybar's pill had signal 14 -- and the battery from
/sys/class/power_supply every BATTERY_S (battery_text). The pill's JSON
"class" becomes a dock-is-<class> style class (dock.css: REC red, a mic in
use magenta ...). The workspace comes from the same Hyprland reads as the
windows (workspace_buttons): the focused screen's on the main bar, a
screen's own on its bar ("all"); a click toggles hyprview's window overview,
SUPER+D's (OVERVIEW_ARGV). A click
opens the bar's panel, which rises from the bottom when the click was in the
lower half of the screen (panelui.py). If the daemon is down while it is on,
those pills are on neither bar until it is back (dock.service restarts it).

TOP BAR OFF (top_bar off, bar_hidden): no top bar at all while this runs.
waybar.service has an ExecCondition (waybar/scripts/bar-wanted.sh, asking
bar-settings.py wanted) that skips the bar while bar_hidden says so AND
dock.service is active -- the setting alone never hides it, so a dock that is
not running leaves the bar where it was. What the taskbar does not take over
goes into the toolbox card instead (bar-settings.py toolbox-config-path: the
clock and the rest too, for the dock). Both ways back are automatic:
dock.service's ExecStopPost starts the bar whenever this stops (switched off,
a crash, `systemctl stop`), and the daemon, on starting, restarts a bar that
is running although it should not be -- a skipped condition is a bar that
stays stopped -- so after a crash and dock.service's own restart it goes
again. `dock.py set` restarts the bar when bar_hidden changes, as for what
the taskbar takes over; switching top_bar off while this is off is refused.

THEME LAYOUT: a theme may say what it looks best with -- dock.layout=
dock|taskbar and dock.top_bar=on|off in its theme.conf, written to
waybar/generated/bar.conf as layout= and top_bar= (Windows 95 and Luna: the
taskbar without the top bar; the Orchard themes: the dock). Nothing follows
it unless follow_theme is on: then `dock.py follow-theme` (theme.py, at every
switch; and switching follow_theme itself) applies it, after keeping your
own three settings in theme_saved; a theme that names none, or follow_theme
off, puts them back (theme_layout). Changing one of the three yourself makes
it yours: theme_saved goes, and the next theme leaves it be.

THE TOOLBOX: game mode, night light, Keep awake, shortcuts and the tray card
(waybar-toolbox, toolbox.sh) opens from a button here while this runs -- the
taskbar's between the tray and the clock, where the quick settings usually
are; the dock's after a line at its end -- with the top bar's sliders glyph,
on the main screen's bar only. The top bar's sliders pill goes meanwhile
(toolbox.sh status prints nothing), so the toolbox has one button. Where the
button is goes to $XDG_RUNTIME_DIR/dock-toolbox.json (TOOLBOX_BUTTON: this
pid, the screen, layout, edge, the bar's and the button's rectangles, the
strip reserved) whenever it moves, and toolbox_fit.py opens the card next to
it, from the bottom of the screen. The file goes when this stops. After a
(re)build -- switched on, another layout, edge, autohide or screen -- the
first position written runs `toolbox.sh refit`: the hidden toolbox is placed
and restarted then, once, and a click finds it ready; and `dock.py set off`
runs it too, so the card goes back under the top bar's pill, and pokes the
pill (signal 12) back.

PREVIEWS: hovering a running app opens a card with its windows' titles, and
their pictures: `grim -T <stableId>` -- Hyprland's client stableId IS the
window's ext-foreign-toplevel identifier (checked against grim), so the
picture is that window's own, wherever it is. Taken only on hover, in the
background, kept THUMB_TTL_S; a window grim cannot take keeps its title
only, silently. Click a card: that window; its x: closes it.

HOVER by hand: a layer surface's enter / leave events come in pairs with
its children's (each button has its own input window, the island's notes),
so a leave is only a hint: DEBOUNCED, then the pointer is asked of
Hyprland (cursorpos) and checked against the dock's rectangle (`layers`)
before anything hides.

It hides on a screen showing a fullscreen window, and while a game runs
(island.py's checks). Layer TOP; the taskbar and a dock that never hides
reserve their strip (exclusive zone, set from the card's size), a hiding
dock reserves nothing. Window moves without an event (a floating window
dragged over the dock) are noticed at the next event, not at once.

EFFECTS -- what moves, and what it costs:

    the room    the layer surface is bigger than the card: shelf_margins()
                reserves the card's shadow all round, and on the side away
                from the edge the height a grown or bouncing icon reaches
                (with magnification, along the dock too, the most the spread
                icons push out). Reserved once, so nothing resizes while it
                moves -- a layer surface that changes size moves. The input
                region is the card (fit_input), so the room round it lets
                clicks through to the windows under it
    the dock    Fx: each item's size eases toward a target (approach(), an
                exponential approach, TAU_*), on the frame clock through a
                tick callback that exists only while something moves. A
                hovered icon grows to HOVER_PEAK, a held one shrinks to
                PRESS_SCALE, a launching app hops (hop(), until its window
                comes or LAUNCH_S), landing the hop it is in. Drawn by hand
                (Bar.draw_frame / draw_items): every child under a cairo
                transform with its allocation untouched, the biggest last;
                icons are DockIcons, rendered by the icon theme at the pixel
                size they are drawn at (Icons, ICON_STEP apart, cached and
                warmed in idle time), so a grown icon is never a blown-up
                small one. The card is one picture (shelf_picture: GTK's
                own background, border and shadow, rendered once) -- a
                blurred box-shadow drawn every frame cost ~5 ms
    magnify     the dock only, on with the setting or the theme's
                dock.magnify: the icons near the pointer grow, 1 +
                (MAGNIFY_PEAK - 1) x a cosine falloff over MAGNIFY_RADIUS
                icons (magnify_scales), and spread along the dock with the
                point under the pointer kept under it (spread), so the icon
                under the pointer is the one a click gets; the card grows by
                their reach (spread_extents), split at its middle. While
                magnified the whole surface takes the pointer: a click on
                the part of an icon above the card reaches it (band_child).
                Pointer motion comes from the buttons' and the surface's
                motion events; a leave falls back only after GONE_MS
    stylesheet  hover, focus and the dots' coming and going ease in
                dock.css (transitions; three dots always there, .lit), the
                urgent wash pulses five times then holds, a launching app
                breathes on the taskbar
    Hyprland    lua/display.lua's layer rules: the dock and the taskbar
                slide in from their edge and out again (an auto-hiding dock
                stepping away), the previews pop in; the hot edge never
                animates
    reduce motion  GTK's gtk-enable-animations (Settings > Accessibility
                turns GNOME's enable-animations off): no Fx at all, no room
                for it, and GTK stops the stylesheet's transitions and
                animations itself. Watched: switching it rebuilds the bars
    cost        idle nothing (no tick, no timer). Measured in the harness
                (a 1600x900 75 Hz screen, a sweep across the dock): a
                magnified frame draws in ~1.4 ms (median), 2.7 ms (p95)

HARNESS ($DOCK_HARNESS=<json>, with DOCK_SETTINGS, DOCK_CSS and DOCK_GEN
pointing at a scratch dock.json, stylesheet and theme folder): a second
dock for previews and screenshots that never touches the session -- its
windows are the file's ("clients", "active", "urgent", "launching"), no
Hyprland events, no toolbox file, refit or pill poke, no pid file, no
exclusive zone and no input at all, on the OVERLAY layer above a "stage"
picture on "monitor". It drives Fx with made-up pointer moves ("hold" a
fraction along the dock, "sweep" seconds end to end, "hover" / "press" an
app, "preview" one, "drag" [from, to] one app to another's place and print
the result), and writes the frame timings to "stats" when it quits
("exit_s", or SIGTERM).
"""
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import notify_source  # noqa: E402  (variants, app_keys, installed_apps, go_argv)

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
SETTINGS_FILE = os.environ.get("DOCK_SETTINGS") or os.path.join(STATE_DIR, "dock.json")
PID_FILE = os.path.join(RUNTIME, "dock.pid")
DEFAULTS = {"enabled": False, "layout": "dock", "position": "bottom", "autohide": "never",
            "icon_size": 48, "monitors": "main", "combine": True, "labels": True, "tray": True,
            "clock": True, "weather": True, "network": True, "sound": True, "previews": True,
            "workspaces": True, "notifications": True, "battery": True, "privacy": True,
            "magnify": "theme", "start_menu": "launcher", "top_bar": True, "follow_theme": False,
            "theme_saved": None, "pinned": None, "tile_order": None}
CHOICES = {"layout": ("dock", "taskbar"), "position": ("bottom", "left", "right"),
           "autohide": ("never", "overlap", "always"), "monitors": ("main", "all"),
           "magnify": ("theme", "on", "off"), "start_menu": ("launcher", "classic")}
# The top bar's pills the taskbar stands in for (TOP BAR in the module
# docstring), per taskbar setting; None: whenever the taskbar is on.
TAKEOVER = (("clock", ("custom/day", "custom/clock", "custom/menuclock")),
            ("weather", ("custom/weather",)),
            ("network", ("custom/network",)),
            ("sound", ("pulseaudio",)),
            ("workspaces", ("ext/workspaces",)),
            ("notifications", ("custom/notifications",)),
            ("battery", ("battery",)),
            ("privacy", ("custom/recording", "custom/mic", "custom/camera", "custom/location")),
            (None, ("custom/power",)))
PRIVACY_PILLS = dict(TAKEOVER)["privacy"]
# The bar's pills that go to the toolbox card whenever this runs, either
# layout (bar-settings.py toolbox-config-path puts them there).
CARD_PILLS = ("hyprland/language",)
BAR_RESTART = os.path.expanduser("~/.config/waybar/scripts/bar-restart.sh")
BOOL_KEYS = tuple(k for k, v in DEFAULTS.items() if isinstance(v, bool))
ICON_MIN, ICON_MAX = 24, 96
TASKBAR_ICON = 24
TRAY_ICON = 18
TRUE_WORDS = ("on", "true", "1", "yes")
FALSE_WORDS = ("off", "false", "0", "no")
APP_ID = re.compile(r"^[A-Za-z0-9_.+-]{1,200}\.desktop$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]+$")
UNIT = "dock.service"
NAMESPACE = "waybar-dock"     # frosted by lua/rules.lua's waybar-glass rule
SEED_ROLES = ("browser", "files", "terminal")
DEFAULT_APPS = os.path.join(HERE, "default-apps.py")
LAUNCHER = os.path.join(HERE, "launcher.py")
SETTINGS_APP = os.path.join(HERE, "settings.py")
PANEL = os.path.expanduser("~/.config/waybar/scripts/panel.py")
TOOLBOX_SH = os.path.expanduser("~/.config/waybar/scripts/toolbox.sh")
TOOLBOX_BUTTON = os.path.join(RUNTIME, "dock-toolbox.json")
NETWORK_PY = os.path.expanduser("~/.config/waybar/scripts/network.py")
WTTR_PY = os.path.expanduser("~/.config/waybar/scripts/wttr.py")
DRAG_START_PX = 8             # this far along the dock with the button held: a drag, not a click
TILE_GROW = 8                 # the dock's tiles: this much bigger than an icon (size_tile)
# The dock's tiles with the top bar off (DOCK TILES in the docstring), in
# the order they stand after the line; the setting that shows each (None:
# always, shown while there is something to say). "clock" is two tiles.
DOCK_TILE_ORDER = ("submap", "workspaces", "media", "notifications", "language", "network", "sound",
                   "battery", "clock", "weather")
DOCK_TILE_SETTING = {"submap": None, "workspaces": "workspaces", "media": None,
                     "notifications": "notifications", "language": None, "network": "network",
                     "sound": "sound", "battery": "battery", "clock": "clock", "weather": "weather"}
# The top bar's pills a tile stands in for beyond TAKEOVER's.
DOCK_TAKES = {"submap": ("hyprland/submap",), "media": ("custom/player",)}
TILE_SHARES = {"apps": (0.50, 0.0), "time": (0.30, 0.18), "date": (0.18, 0.40),
               "weather": (0.38, 0.22), "workspaces": (0.42, 0.17), "submap": (0.32, 0.17),
               "media": (0.38, 0.16), "notifications": (0.36, 0.22), "battery": (0.36, 0.22),
               "language": (0.34, 0.17), "network": (0.36, 0.16), "sound": (0.36, 0.22)}
TILE_HIDDEN = ("weather", "media", "battery", "submap", "network")    # shown only with something to say (a battery)
SUBMAP_GLYPH = "\uf11c"       # Font Awesome keyboard
SUBMAP_RESET = ["hyprctl", "eval", 'hl.dispatch(hl.dsp.submap("reset"))']
# The tiles one by one ("clock" is "time" and "date"): what tile_order names.
TILE_NAMES = tuple(t for k in DOCK_TILE_ORDER for t in (("time", "date") if k == "clock" else (k,)))
STATUS_TILES = ("weather", "notifications", "battery", "media", "network", "sound")   # fed by set_status
LANGUAGE_S = 15               # the language tile asks fcitx5 again (it sends no event)
BADGE_MAX = 99
WEATHER_S = 1800              # the top bar's weather interval: wttr.in turns away eager clients
WEATHER_RETRY_S = 300         # after a stale answer (no network yet at login, say)
STATUS_RESTART_S = 5          # a watcher that died (network.py, pactl) starts again after
VOLUME_STEP = "5%"
NOTIFY_S = 30                 # the bar's notifications interval; SIGUSR2 is the signal
BATTERY_S = 30                # the bar's battery interval
POWER_SUPPLY = "/sys/class/power_supply"
WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
RECORDING_PY = os.path.join(WAYBAR_SCRIPTS, "recording.py")
PRIVACY_PY = os.path.join(WAYBAR_SCRIPTS, "privacy.py")
NOTIFICATIONS_PY = os.path.join(WAYBAR_SCRIPTS, "notifications.py")
PLAYER_PY = os.path.join(WAYBAR_SCRIPTS, "player.py")
RECORD_SH = os.path.join(HERE, "record.sh")
# The pills beyond the three below (PILLS in the module docstring), in the
# order they stand, left to right: the privacy cluster (before the tray),
# the battery (after the sound), the notifications (after the clock). The
# setting that shows each; the watchers' argv; what each mouse button runs.
PRIVACY_KEYS = ("recording", "mic", "camera", "location")
PILL_SETTING = {"recording": "privacy", "mic": "privacy", "camera": "privacy", "location": "privacy",
                "battery": "battery", "notifications": "notifications"}
PILL_WATCH = {"recording": [RECORDING_PY, "watch"], "mic": [PRIVACY_PY, "watch", "mic"],
              "camera": [PRIVACY_PY, "watch", "camera"], "location": [PRIVACY_PY, "watch", "location"],
              "media": [PLAYER_PY, "watch"]}     # the dock's media tile (DOCK TILES)


def in_terminal(cmd):
    return ["kitty", "-e", "sh", "-c", f"{cmd}; echo; printf 'press enter '; read x"]


# The bar's on-click / on-click-right / on-click-middle for each, as argv.
PILL_CLICKS = {
    "recording": {1: [RECORD_SH, "click"], 3: [RECORD_SH, "stop-replay"]},
    "mic": {1: [PRIVACY_PY, "mic", "focus"], 3: ["pavucontrol", "-t", "2"],
            2: ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"]},
    "camera": {1: [PRIVACY_PY, "camera", "focus"], 3: in_terminal(f"{PRIVACY_PY} camera list")},
    "location": {1: in_terminal(f"{PRIVACY_PY} location list")},
    "notifications": {1: [sys.executable, PANEL, "toggle", "notifications"], 3: [NOTIFICATIONS_PY, "dnd"]},
    "battery": {},
}
BATTERY_GLYPHS = ("\uf244", "\uf243", "\uf242", "\uf241", "\uf240")   # Font Awesome empty .. full
CHARGING_GLYPH = "\uf0e7"
# The taskbar's status buttons, right to left after the toolbox: the panel a
# click opens, and the top bar's matching pill (TAKEOVER).
STATUS_KEYS = ("sound", "network", "weather")
STATUS_PANELS = {"sound": "audio", "network": "network", "weather": "weather"}
VOLUME_GLYPHS = ("\uf026", "\uf027", "\uf028")   # Font Awesome volume off / low / high, as the bar's
MUTED_GLYPH = "\uf6a9"      # Font Awesome volume-xmark: a speaker struck out (a lone X read as "remove")
# The classic start menu's Programs, by a desktop file's Categories: checked
# in this order (a "Game;Utility" app is a game), listed by title.
MENU_CATEGORIES = (("Games", "applications-games", ("Game",)),
                   ("Development", "applications-development", ("Development",)),
                   ("Graphics", "applications-graphics", ("Graphics",)),
                   ("Multimedia", "applications-multimedia", ("AudioVideo", "Audio", "Video")),
                   ("Internet", "applications-internet", ("Network",)),
                   ("Office", "applications-office", ("Office",)),
                   ("Education", "applications-science", ("Education", "Science")),
                   ("Settings", "preferences-desktop", ("Settings",)),
                   ("System", "applications-system", ("System",)),
                   ("Accessories", "applications-accessories", ("Utility",)))
MENU_OTHER = ("Other", "applications-other")
TOOLBOX_GLYPH = ""      # Font Awesome's sliders: the top bar's toolbox pill's own
# DOCK_CSS / DOCK_GEN: another stylesheet and another theme folder (bar.conf)
# -- the scratch harness's, to draw a theme that is not the one in use.
CSS_FILE = os.environ.get("DOCK_CSS") or os.path.join(HERE, "dock.css")
GEN_DIR = os.environ.get("DOCK_GEN") or os.path.expanduser("~/.config/waybar/generated")
HARNESS_ENV = "DOCK_HARNESS"  # HARNESS in the module docstring
THEME_FILES = ("theme-panel.css", "accent.css", "theme-dock.css", "bar.conf", "lang")
JA_WEEKDAYS = "月火水木金土日"     # Monday first, as clock.py's (the top bar's date)
START_GLYPH = ""        # Font Awesome's grid: the start button, unless the theme has a logo
CLOSE_GLYPH = ""

# timing (ms unless _S)
REFRESH_MS = 60               # a burst of window events -> one read
TITLE_MS = 250                # title changes (a terminal's prompt) -> one read
SETTINGS_DEBOUNCE_MS = 100
THEME_DEBOUNCE_MS = 250
PLACE_MS = 500                # a screen came or went: let GDK catch up first
LEAVE_MS = 450                # a leave, before the pointer is asked where it is
PREVIEW_OPEN_MS = 350
PREVIEW_CLOSE_MS = 350
LAUNCH_S = 8                  # the launching breath, at most
THUMB_TTL_S = 4
THUMB_W, THUMB_H = 220, 140
PREVIEW_MAX = 8               # windows in one preview card
MENU_WINDOWS = 10
RECONNECT_S = 2
DOCK_MARGIN = 8               # the floating dock's distance from its edge
EDGE_PX = 3                   # the hot edge of a hidden dock
GAP = 6                       # between the dock and its preview
SCREEN_EDGE = 8

# the effects (EFFECTS in the module docstring)
HOVER_PEAK = 1.12             # a hovered icon's size, magnification off
PRESS_SCALE = 0.90            # a held icon shrinks a little: the press
MAGNIFY_PEAK = 1.6            # the icon right under the pointer, magnifying
MAGNIFY_RADIUS = 2.5          # how far the growth reaches each way, in icons
TAU_HOVER_S = 0.08            # how fast a size follows its target (the time
TAU_MAGNIFY_S = 0.045         #   constant of an exponential approach)
SETTLE = 0.002                # closer than this to its target: there
HOP_S = 0.62                  # one launch bounce
HOP_FRAC = 0.35               # its height, a fraction of the icon size
GONE_MS = 80                  # a leave, before the magnified icons fall back
ICON_STEP = 4                 # px between the cached sizes of a growing icon
ICON_CACHE = 240              # rendered icon sizes kept, all apps together
SHADOW_PAD = 16               # room round the dock's card for its shadow
TASKBAR_PAD = 10              # room above the taskbar for its shadow / glow
FX_STATS = 4000               # frame timings kept for the harness
DOCK_EVENTS = ("openwindow", "closewindow", "activewindowv2", "movewindowv2", "windowtitlev2",
               "workspacev2", "focusedmonv2", "fullscreen", "urgent", "changefloatingmode",
               "activespecial", "monitoraddedv2", "monitorremoved", "renameworkspace", "submap",
               "activelayout")
WANTED_EVENTS = frozenset(n.encode() for n in DOCK_EVENTS)

# StatusNotifierItem / dbusmenu
WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
SNI = "org.kde.StatusNotifierItem"
SNI_PATH = "/StatusNotifierItem"
DBUSMENU = "com.canonical.dbusmenu"


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


def norm_app_id(text):
    """"org.gnome.Nautilus" -> "org.gnome.Nautilus.desktop"; None when it
    cannot be a desktop id."""
    text = str(text or "").strip()
    if text and not text.endswith(".desktop"):
        text += ".desktop"
    return text if APP_ID.match(text) else None


def clean_pinned(value):
    """A pinned list as stored: valid ids, each once, in order."""
    out = []
    for v in value if isinstance(value, (list, tuple)) else []:
        app_id = norm_app_id(v) if isinstance(v, str) else None
        if app_id and app_id not in out:
            out.append(app_id)
    return out


def read_settings():
    cur = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
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
        elif k in CHOICES:
            if isinstance(v, str) and v.strip().lower() in CHOICES[k]:
                cur[k] = v.strip().lower()
        elif k == "icon_size":
            try:
                cur[k] = max(ICON_MIN, min(ICON_MAX, int(v)))
            except (TypeError, ValueError, OverflowError):   # OverflowError: 1e999, Infinity
                pass
        elif k == "pinned":
            cur[k] = clean_pinned(v) if isinstance(v, list) else None
        elif k == "theme_saved":
            cur[k] = clean_saved(v)
        elif k == "tile_order":
            cur[k] = clean_tile_order(v)
    return cur


def clean_tile_order(value):
    """The dock tiles' order as dragged (tile_order): known tiles, each
    once; None for no order of its own."""
    if not isinstance(value, list):
        return None
    out = []
    for v in value:
        if v in TILE_NAMES and v not in out:
            out.append(v)
    return out


def ordered_tiles(names, saved):
    """The tiles to pack (names, in DOCK_TILE_ORDER's order) as tile_order
    has them; one it does not name goes after its neighbour in the default
    order (a tile switched on since the drag), or first."""
    out = [n for n in saved or [] if n in names]
    for i, n in enumerate(names):
        if n in out:
            continue
        before = next((m for m in reversed(names[:i]) if m in out), None)
        out.insert(out.index(before) + 1 if before else 0, n)
    return out


LAYOUT_KEYS = ("enabled", "layout", "top_bar")    # what a theme's layout sets (THEME LAYOUT)


def clean_saved(v):
    """theme_saved as written, or None when it is not whole."""
    if not isinstance(v, dict) or not isinstance(v.get("enabled"), bool) \
            or v.get("layout") not in CHOICES["layout"] or not isinstance(v.get("top_bar"), bool):
        return None
    return {k: v[k] for k in LAYOUT_KEYS}


def read_theme_layout(path=None):
    """{"layout", "top_bar"} from bar.conf (theme.py writes it from the
    theme's dock.layout= / dock.top_bar=); "" for what it does not say."""
    out = {"layout": "", "top_bar": ""}
    try:
        with open(path or os.path.join(GEN_DIR, "bar.conf")) as fh:
            for line in fh:
                k, sep, v = line.strip().partition("=")
                if sep and k in out:
                    out[k] = v.strip().lower()
    except OSError:
        pass
    return out


def theme_layout(cfg, theme):
    """The settings after following the theme (THEME LAYOUT): with
    follow_theme on and a theme that names a layout (dock / taskbar) or a top
    bar (on / off), those, the dock switched on for a layout, and your own
    three kept in theme_saved (once: a theme after a theme keeps the first
    ones); else your saved ones back. A top bar the theme turns off needs the
    dock on: alone it is left as it is."""
    new = dict(cfg)
    want = {}
    if cfg.get("follow_theme"):
        if theme.get("layout") in CHOICES["layout"]:
            want.update(enabled=True, layout=theme["layout"])
        if theme.get("top_bar") in ("on", "off"):
            if theme["top_bar"] == "on" or want.get("enabled", cfg.get("enabled")):
                want["top_bar"] = theme["top_bar"] == "on"
    if want:
        new["theme_saved"] = cfg.get("theme_saved") or {k: cfg[k] for k in LAYOUT_KEYS}
        new.update(want)
    elif cfg.get("theme_saved"):
        new.update(cfg["theme_saved"])
        new["theme_saved"] = None
    return new


def write_settings(d):
    os.makedirs(os.path.dirname(SETTINGS_FILE) or ".", exist_ok=True)
    tmp = f"{SETTINGS_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump({k: d.get(k, DEFAULTS[k]) for k in DEFAULTS}, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, SETTINGS_FILE)


def dock_only(cfg):
    """The dock with no top bar (DOCK TILES in the docstring)."""
    return bool(cfg.get("enabled")) and cfg.get("layout") != "taskbar" and bar_hidden(cfg)


def dock_tiles(cfg):
    """The dock's tiles (DOCK TILES in the docstring), DOCK_TILE_ORDER's
    as their settings say, only on the dock with the top bar off."""
    if not dock_only(cfg):
        return ()
    return tuple(k for k in DOCK_TILE_ORDER
                 if DOCK_TILE_SETTING[k] is None or cfg.get(DOCK_TILE_SETTING[k]))


def card_pills(cfg):
    """The bar's pills that go to the toolbox card while this runs
    (CARD_PILLS): none of them with the dock's language tile -- what is on
    the dock is not in the card."""
    return () if "language" in dock_tiles(cfg) else CARD_PILLS


def bar_takeover(cfg):
    """The top bar's pills to leave out while this runs as the taskbar, in
    TAKEOVER's order, then CARD_PILLS (the toolbox card's); for the dock
    with the top bar off the date, time and weather of its tiles
    (dock_tiles) and the privacy pills (the dock shows them then), and
    CARD_PILLS; [] when it is off."""
    if not cfg.get("enabled"):
        return []
    if cfg.get("layout") != "taskbar":
        tiles = dock_tiles(cfg)
        return ([name for key, names in TAKEOVER if key in tiles for name in names]
                + [name for key in tiles for name in DOCK_TAKES.get(key, ())]
                + (list(PRIVACY_PILLS) if bar_hidden(cfg) and cfg.get("privacy") else []) + list(CARD_PILLS))
    return [name for key, names in TAKEOVER if key is None or cfg.get(key) for name in names] + list(CARD_PILLS)


def bar_hidden(cfg):
    """No top bar at all (TOP BAR OFF in the docstring): switched on, with
    top_bar off. Whether the bar really goes also needs dock.service up
    (bar-settings.py wanted)."""
    return bool(cfg.get("enabled")) and not cfg.get("top_bar", True)


def unit_active(unit):
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit],
                              stdin=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restart_bar():
    """bar-restart.sh in the background: the top bar starts again from the
    config bar-settings.py config-path picks (TOP BAR in the docstring).
    Never fails a caller, never waits for the bar."""
    try:
        subprocess.Popen([BAR_RESTART], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def dry_env():
    """DOCK_DRY=1 (the tests): settings are written, systemd is left alone."""
    return os.environ.get("DOCK_DRY") == "1"


def switch_unit(on):
    cmd = ["systemctl", "--user", "enable" if on else "disable", "--now", UNIT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"dock.py: {' '.join(cmd)}: {exc}")
    if r.returncode != 0:
        raise SystemExit(f"dock.py: {' '.join(cmd)}: {(r.stderr or '').strip()}")


def set_key(key, value):
    if key not in DEFAULTS or key == "theme_saved":
        raise SystemExit(f"dock.py: no setting {key!r} (one of {', '.join(k for k in DEFAULTS if k != 'theme_saved')})")
    old = read_settings()
    cur = dict(old)
    if key in BOOL_KEYS:
        try:
            cur[key] = bool_value(value)
        except ValueError:
            raise SystemExit(f"dock.py: {key} is on or off")
    elif key in CHOICES:
        v = str(value).strip().lower()
        if v not in CHOICES[key]:
            raise SystemExit(f"dock.py: {key} is one of {', '.join(CHOICES[key])}")
        cur[key] = v
    elif key == "icon_size":
        try:
            v = int(str(value).strip().removesuffix("px"))
        except ValueError:
            raise SystemExit(f"dock.py: icon_size is a number of pixels, {ICON_MIN}-{ICON_MAX}")
        cur[key] = max(ICON_MIN, min(ICON_MAX, v))
    else:   # pinned: comma-separated desktop ids
        ids = [p for p in str(value).split(",") if p.strip()]
        bad = [p for p in ids if norm_app_id(p) is None]
        if bad:
            raise SystemExit(f"dock.py: not desktop ids: {', '.join(bad)}")
        cur[key] = clean_pinned(ids)
    if key == "top_bar" and not cur["top_bar"] and not cur["enabled"]:
        raise SystemExit("dock.py: the top bar can only go while the dock or the taskbar is on (dock.py set on)")
    if key in LAYOUT_KEYS and cur[key] != old[key]:
        cur["theme_saved"] = None       # yours now: the next theme leaves it be (THEME LAYOUT)
    if key == "follow_theme":
        cur = theme_layout(cur, read_theme_layout())
    return apply_settings(old, cur)


def follow_theme():
    """`dock.py follow-theme` (theme.py, at every switch): THEME LAYOUT."""
    old = read_settings()
    new = theme_layout(old, read_theme_layout())
    return apply_settings(old, new) if new != old else old


def apply_settings(old, cur):
    """Write cur, then what changing old to it takes: dock.service on or off,
    the toolbox placed again and its pill poked, the bar restarted when what
    it shows changes (one restart, however many keys changed)."""
    was_bar = (bar_takeover(old), bar_hidden(old))
    # Written first: a daemon that starts reads enabled=true, and one that
    # sees enabled=false in the file quits by itself.
    write_settings(cur)
    flipped = cur["enabled"] != old["enabled"]
    if flipped and not dry_env():
        switch_unit(cur["enabled"])
        if not cur["enabled"]:
            # The daemon is gone (disable --now waits for the stop) and took
            # its toolbox button file along: the card goes back under the
            # top bar's pill, placed now rather than at the next click. Here,
            # not in the daemon's way out: a process it started while
            # stopping would be killed with the rest of dock.service.
            toolbox_refit()
    if flipped:
        # The top bar's sliders pill re-reads whether the dock has the
        # toolbox button (toolbox.sh status): gone with a dock, back without.
        # Switched on, the daemon pokes it again once its button is there.
        poke_toolbox_pill()
    if (bar_takeover(cur), bar_hidden(cur)) != was_bar and not dry_env():
        restart_bar()
    return cur


def toolbox_refit():
    """`toolbox.sh refit`: the toolbox folded away and placed for where its
    button is now (a restart of the hidden waybar-toolbox when that moved
    it). Never fails a caller."""
    try:
        subprocess.run([TOOLBOX_SH, "refit"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass


def poke_toolbox_pill():
    """Signal 12 (bar_signals.py "toolbox"): custom/toolbox runs its status
    again. A no-op under HYPR_BAR_SIGNALS_OFF (the tests)."""
    try:
        import bar_signals
        bar_signals.poke("toolbox")
    except Exception:         # noqa: BLE001 - no bar: nothing to redraw
        pass


def change_pinned(op, app_id, delta=0):
    """pin / unpin / move on the stored list (the CLI, the menu, the page)."""
    want = norm_app_id(app_id)
    if want is None:
        raise SystemExit(f"dock.py: {app_id!r} is not a desktop id")
    cur = read_settings()
    pinned = list(cur["pinned"] or [])
    if op != "pin":
        want = pinned_match(pinned, want) or want
    if op == "pin":
        pinned = pin(pinned, want)
    elif op == "unpin":
        pinned = unpin(pinned, want)
    else:
        pinned = move_pin(pinned, want, delta)
    cur["pinned"] = pinned
    write_settings(cur)
    return cur


def systemctl_word(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args, UNIT], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def daemon_running(pidfile=None):
    """The daemon's pid file names a live dock.py."""
    try:
        with open(pidfile or PID_FILE) as fh:
            pid = int(fh.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return b"dock.py" in fh.read()
    except (OSError, ValueError):
        return False


def monitor_names():
    import desk_common
    mons = desk_common.hypr_request("monitors", json=True)
    return [m["name"] for m in mons if isinstance(m, dict) and m.get("name")] if isinstance(mons, list) else []


def status():
    if dry_env():
        service, enabled_unit = "dry", False
    else:
        service = systemctl_word("is-active") or "unknown"
        enabled_unit = systemctl_word("is-enabled") == "enabled"
    cfg = read_settings()
    try:
        apps = {a["id"]: a for a in notify_source.installed_apps()}
    except Exception:         # noqa: BLE001 - no Gio: ids without names
        apps = {}
    pinned = [{"id": i, "name": (apps.get(i) or {}).get("name") or i.removesuffix(".desktop"),
               "installed": i in apps} for i in cfg["pinned"] or []]
    return {"settings": cfg, "defaults": dict(DEFAULTS), "service": service,
            "enabled_unit": enabled_unit, "running": daemon_running(),
            "monitors": [] if dry_env() else monitor_names(), "pinned_apps": pinned,
            "file": SETTINGS_FILE}


def print_status(st):
    for k, v in st["settings"].items():
        if k == "pinned":
            v = ", ".join(p["name"] for p in st["pinned_apps"]) or ("-" if v is not None else "(not chosen yet)")
        elif k in BOOL_KEYS:
            v = "on" if v else "off"
        print(f"{k}: {v}")
    print(f"service: {st['service']}{' (enabled)' if st['enabled_unit'] else ''}")
    print(f"running: {'yes' if st['running'] else 'no'}")
    print(f"monitors: {', '.join(st['monitors']) or '-'}")
    print(f"file: {st['file']}")


# -- pure ----------------------------------------------------------------------------------
def pin(pinned, app_id):
    return list(pinned) + ([app_id] if app_id not in pinned else [])


def unpin(pinned, app_id):
    return [p for p in pinned if p != app_id]


def move_pin(pinned, app_id, delta):
    """One place left (-1) or right (+1); the ends stay the ends."""
    pinned = list(pinned)
    if app_id not in pinned:
        return pinned
    i = pinned.index(app_id)
    j = max(0, min(len(pinned) - 1, i + (1 if delta > 0 else -1 if delta < 0 else 0)))
    pinned.insert(j, pinned.pop(i))
    return pinned


def drag_result(pinned, order, seen):
    """A drag in the dock ended (Bar.drag_release): the pinned list and the
    running apps' order (update_order) for what it now shows. seen: its
    apps in their order on the dock, [(group, app_id, pinned now)] -- a
    running app moved among the pinned is pinned there by its desktop id
    (as it was, without one). Pinned apps the dock does not show (gone from
    the system) keep their places after the ones it does."""
    shown = [(g, a) for g, a, now in seen if now]
    new_pinned = []
    for group, app_id in shown:
        entry = group if group in pinned else app_id
        if not entry:
            return list(pinned), list(order)
        if entry not in new_pinned:
            new_pinned.append(entry)
    new_pinned += [p for p in pinned if p not in new_pinned and p not in {g for g, _a, _n in seen}]
    running = [g for g, _a, now in seen if not now]
    now_pinned = {g for g, _a, now in seen if now}
    new_order = running + [k for k in order if k not in running and k not in now_pinned]
    return new_pinned, new_order


def pinned_match(pinned, app_id):
    """The pinned id a short name means ("firefox" -> org.mozilla.firefox.desktop),
    when exactly one matches; None otherwise."""
    if app_id in pinned:
        return app_id
    want = notify_source.variants(app_id)
    hits = [p for p in pinned if notify_source.variants(p) & want]
    return hits[0] if len(hits) == 1 else None


def seed_pinned(found):
    """The first pinned list: what default-apps.py answered, in role order."""
    return clean_pinned([f for f in found if f])


def is_address(addr):
    return isinstance(addr, str) and bool(ADDRESS.match(addr))


def norm_address(data):
    """An event's address ("55d3a1b0", no 0x) as hyprctl writes it, or None."""
    data = (data or "").strip()
    if not data or not all(c in "0123456789abcdefABCDEFx" for c in data):
        return None
    return data if data.startswith("0x") else "0x" + data


# Fields in the order they say most: StartupWMClass is what an app tells
# the compositor its class is, the id often is the class (org.gnome.Nautilus),
# the program's name sometimes (kitty), the visible name last.
MATCH_FIELDS = ("wmclass", "id", "exec", "name")


def app_index(apps):
    """{name: (rank, app)} for matching windows to installed apps: every
    variant (notify_source.variants) of each field, the best-ranked app for
    each; hidden entries (NoDisplay) only when nothing visible says it."""
    index = {}
    for app in apps:
        if not app.get("id"):
            continue
        for rank, field in enumerate(MATCH_FIELDS):
            score = (rank + (len(MATCH_FIELDS) if app.get("hidden") else 0), notify_source.norm(app["id"]))
            for key in notify_source.variants(app.get(field)):
                if key not in index or score < index[key][0]:
                    index[key] = (score, app)
    return index


def window_app(client, index):
    """The installed app a window belongs to, or None."""
    best = None
    for key in notify_source.window_keys(client):
        hit = index.get(key)
        if hit and (best is None or hit[0] < best[0]):
            best = hit
    return best[1] if best else None


def window_class(client):
    return str(client.get("class") or client.get("initialClass") or "")


def group_key(client, app):
    return app["id"] if app else "class:" + (window_class(client).lower() or "?")


def icon_names(cls):
    """The icon a window with no installed app gets: its class's, then a
    Steam game's, then the generic one."""
    names = []
    for name in (cls, cls.lower(), cls.rsplit(".", 1)[-1].lower()):
        if name and name not in names:
            names.append(name)
    m = re.match(r"steam_app_(\d+)$", cls)
    if m:
        names.insert(0, f"steam_icon_{m.group(1)}")
    return names + ["application-x-executable"]


def window_entry(c):
    return {"address": c.get("address"), "title": str(c.get("title") or ""), "class": window_class(c),
            "stable_id": str(c.get("stableId") or ""), "focus": c.get("focusHistoryID", -1),
            "monitor": c.get("monitor"), "workspace": (c.get("workspace") or {}).get("name", ""),
            "size": list(c.get("size") or [0, 0])}


def live_clients(clients):
    """The windows that count: mapped, with an address, not a hidden tab."""
    return [c for c in clients or [] if isinstance(c, dict) and is_address(c.get("address"))
            and c.get("mapped", True) and not c.get("hidden")]


def update_order(order, clients, index):
    """The running apps' order: as they were, new ones at the end in the
    order their first window opened (hyprctl lists windows oldest first)."""
    keys = []
    for c in clients:
        k = group_key(c, window_app(c, index))
        if k not in keys:
            keys.append(k)
    return [k for k in order if k in keys] + [k for k in keys if k not in order]


def recent(windows):
    """The most recently focused window (focusHistoryID 0 = the focused)."""
    ranked = [w for w in windows if isinstance(w.get("focus"), int) and w["focus"] >= 0]
    return min(ranked, key=lambda w: w["focus"]) if ranked else (windows[0] if windows else None)


def build_items(pinned, clients, index, apps_by_id, order, *, monitor_id=None, combine=True,
                active=None, urgent=(), launching=()):
    """What the dock shows, in order: the pinned apps (running or not; one
    no longer installed is left out -- its windows, if any, show as an
    unknown app's), then the other running apps.
    combine=False (the taskbar's "never combine"): a button per window,
    each at its app's place. Each item:
        {key, group, app_id, name, class, pinned, windows (oldest first),
         focused, urgent, launching, title}"""
    groups = {}
    for c in live_clients(clients):
        if monitor_id is not None and c.get("monitor") != monitor_id:
            continue
        app = window_app(c, index)
        key = group_key(c, app)
        g = groups.setdefault(key, {"app": app, "class": window_class(c), "windows": []})
        g["windows"].append(window_entry(c))
    urgent = set(urgent)

    def make(key, app, group, is_pinned):
        windows = group["windows"] if group else []
        name = (app or {}).get("name") or (group or {}).get("class") or key.removesuffix(".desktop")
        base = {"group": key, "app_id": (app or {}).get("id"), "name": str(name),
                "class": (group or {}).get("class") or "", "pinned": is_pinned,
                "launching": key in launching and not windows}
        if combine or len(windows) <= 1:
            only = windows[0]["title"] if len(windows) == 1 else ""
            return [dict(base, key=key, windows=list(windows),
                         focused=any(w["address"] == active for w in windows),
                         urgent=any(w["address"] in urgent for w in windows),
                         title=only or str(name))]
        return [dict(base, key=f"{key}#{w['address']}", windows=[w], focused=w["address"] == active,
                     urgent=w["address"] in urgent, title=w["title"] or str(name),
                     pinned=is_pinned and i == 0)
                for i, w in enumerate(windows)]

    items, seen = [], set()
    for app_id in pinned or []:
        if app_id in seen:
            continue
        seen.add(app_id)
        app, group = apps_by_id.get(app_id), groups.get(app_id)
        if app is None and group is None:
            continue
        items += make(app_id, app or group["app"], group, True)
    rest = [k for k in order if k in groups and k not in seen]
    rest += [k for k in groups if k not in seen and k not in rest]
    for key in rest:
        items += make(key, groups[key]["app"], groups[key], False)
    return items


def click_action(item, active):
    """What a left click does: ("launch", app_id), ("focus", address) or None.
    Several windows: the most recent, then (one of them focused) the next one
    in the order they opened, so clicks go round them all."""
    windows = item.get("windows") or []
    if not windows:
        return ("launch", item["app_id"]) if item.get("app_id") else None
    addrs = [w["address"] for w in windows]
    if active in addrs:
        return ("focus", addrs[(addrs.index(active) + 1) % len(addrs)])
    return ("focus", recent(windows)["address"])


def focus_argv(address):
    """notify_source.go_argv's: hl.dsp.focus by a validated address."""
    return notify_source.go_argv({"kind": "window", "address": address}) if is_address(address) else None


def launch_argv(app_id, action=None, which=shutil.which):
    """uwsm app -- <id>[:<action>] (gtk-launch without uwsm; an action then
    needs Gio's launch_action instead: None)."""
    app_id = norm_app_id(app_id)
    if app_id is None or (action and not re.match(r"^[A-Za-z0-9_-]+$", action)):
        return None
    if which("uwsm"):
        return ["uwsm", "app", "--", f"{app_id}:{action}" if action else app_id]
    return None if action else ["gtk-launch", app_id]


def close_argv(address):
    """hl.dsp.window.close on that window -- only ever from a menu click."""
    if not is_address(address):
        return None
    return ["hyprctl", "eval", f"hl.dispatch(hl.dsp.window.close({{ window = 'address:{address}' }}))"]


def new_window_action(actions):
    """The app's own "new window" action id, if it has one."""
    for a in actions:
        if a.replace("_", "-").lower() in ("new-window", "newwindow", "new-empty-window"):
            return a
    return None


def logical_rect(mon):
    """(x, y, w, h) of a hyprctl monitor in layout coordinates."""
    import screens
    w, h = screens.logical_size(mon.get("width", 0), mon.get("height", 0), mon.get("scale") or 1,
                                mon.get("transform") or 0)
    return (mon.get("x", 0), mon.get("y", 0), w, h)


def intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def visible_workspaces(mon):
    out = {(mon.get("activeWorkspace") or {}).get("id")}
    special = (mon.get("specialWorkspace") or {}).get("id", 0)
    if special:
        out.add(special)
    return out - {None}


def overlapped(rect, clients, workspace_ids):
    """Whether a window on a shown workspace covers the dock's rectangle."""
    if not rect:
        return False
    for c in live_clients(clients):
        if (c.get("workspace") or {}).get("id") not in workspace_ids:
            continue
        at, size = c.get("at") or [0, 0], c.get("size") or [0, 0]
        if intersects(rect, (at[0], at[1], size[0], size[1])):
            return True
    return False


def should_hide(mode, hovered, held, overlap):
    if hovered or held or mode == "never":
        return False
    return True if mode == "always" else bool(overlap)


def inside(point, rect, slack=2):
    if not point or not rect:
        return False
    x, y = point
    return rect[0] - slack <= x < rect[0] + rect[2] + slack and rect[1] - slack <= y < rect[1] + rect[3] + slack


def toward_edge(rect, position, by):
    """The dock's rectangle stretched `by` px toward the screen edge it sits
    on. The floating dock stands DOCK_MARGIN off that edge and its hot edge
    is the last EDGE_PX: a pointer resting there is still "on the dock", or
    it would hide, map the edge under the pointer, show again, and so on."""
    if not rect:
        return rect
    x, y, w, h = rect
    if position == "left":
        return (x - by, y, w + by, h)
    if position == "right":
        return (x, y, w + by, h)
    return (x, y, w, h + by)


def read_events(lines):
    """socket2 lines -> what they ask of the dock:
        {"now": refresh soon, "titles": a title changed, "place": screens
         came or went, "game": a window opened or closed (look for a game
         again), "ops": [("active", addr|None) | ("urgent", addr|None)] in order,
         "submap": the key mode now ("" none), None when no event said,
         "layout": the keyboard layout changed}
    Only DOCK_EVENTS count. Without the hyprbus relay the dock reads
    Hyprland's socket2 itself, which sends every event: a title (v1
    windowtitle), a layer opening (a notification, the OSD, our own
    preview), a keyboard layout and the rest must not cost a refresh."""
    out = {"now": False, "titles": False, "place": False, "game": False, "ops": [], "submap": None,
           "layout": False}
    for line in lines:
        name, _, rest = line.partition(b">>")
        if name not in WANTED_EVENTS:
            continue
        rest = rest.decode(errors="replace")
        if name == b"activewindowv2":
            out["ops"].append(("active", norm_address(rest)))
            out["now"] = True
        elif name == b"urgent":
            out["ops"].append(("urgent", norm_address(rest)))
            out["now"] = True
        elif name == b"windowtitlev2":
            out["titles"] = True
        elif name in (b"monitoraddedv2", b"monitorremoved"):
            out["place"] = True
        elif name in (b"openwindow", b"closewindow"):
            out["game"] = out["now"] = True
        elif name == b"submap":         # a key mode: its name, "" when it ends
            out["submap"] = rest.strip()
        elif name == b"activelayout":   # another keyboard layout (the language tile)
            out["layout"] = True
        else:                     # fullscreen, workspacev2, focusedmonv2, movewindowv2, ...
            out["now"] = True
    return out


def layer_rect(layers, monitor, namespace, pid):
    """(x, y, w, h) of our layer surface on `monitor` from `hyprctl layers -j`."""
    levels = ((layers or {}).get(monitor) or {}).get("levels") or {}
    for surfaces in levels.values():
        for s in surfaces or []:
            if s.get("namespace") == namespace and s.get("pid") == pid:
                return (s.get("x", 0), s.get("y", 0), s.get("w", 0), s.get("h", 0))
    return None


def toolbox_record(pid, output, layout, position, monitor, bar, offset, size, reserved):
    """What TOOLBOX_BUTTON holds (toolbox_fit.py's live_dock reads it): the
    toolbox button's rectangle in layout coordinates, from the bar's (`bar`,
    as Hyprland reports its layer) and the button's `offset` inside it and
    `size`; `reserved` the exclusive strip the bar keeps (0: none)."""
    bx, by = bar[0] + offset[0], bar[1] + offset[1]
    return {"pid": pid, "output": output, "layout": layout, "position": position,
            "monitor": [int(v) for v in monitor], "bar": [int(v) for v in bar],
            "button": [int(bx), int(by), int(size[0]), int(size[1])], "reserved": max(0, int(reserved or 0))}


def preview_place(position, button, mon, size, gap=GAP, edge=SCREEN_EDGE):
    """Where the preview card goes, beside the hovered button: (anchors,
    margins), the anchors a subset of top / bottom / left / right and the
    margins from the screen's edges. button and mon are (x, y, w, h) in
    layout coordinates, size the card's (w, h)."""
    bx, by, bw, bh = button
    mx, my, mw, mh = mon
    pw, ph = size
    if position == "bottom":
        left = max(edge, min(mw - pw - edge, int(bx + bw / 2 - pw / 2 - mx)))
        return ("bottom", "left"), {"bottom": max(0, int(my + mh - by + gap)), "left": left}
    top = max(edge, min(mh - ph - edge, int(by + bh / 2 - ph / 2 - my)))
    if position == "left":
        return ("top", "left"), {"top": top, "left": max(0, int(bx + bw - mx + gap))}
    return ("top", "right"), {"top": top, "right": max(0, int(mx + mw - bx + gap))}


def thumb_scale(size, width=THUMB_W, height=THUMB_H):
    """grim's -s for a window of logical `size`: the picture fits the card."""
    w, h = (size or [0, 0])[:2]
    if w <= 0 or h <= 0:
        return 0.25
    return round(max(0.05, min(1.0, width / w, height / h)), 3)


def clock_text(moment, conf=None, language=None):
    """(time, date) for the taskbar: region.py's way of writing them, never
    the seconds (one wake-up a minute). A ja theme (waybar/generated/lang)
    writes the date as the top bar does, "10月30日(金)" (clock.py's
    menubar_text)."""
    import region
    conf = dict(conf or region.DEFAULTS, seconds="off")
    if language == "ja":
        weekday = JA_WEEKDAYS[moment.weekday()]
        return region.time_text(moment, conf), f"{moment.month}月{moment.day}日({weekday})"
    return region.time_text(moment, conf), region.date_text(moment, conf)


def leaf(markup):
    """A top bar pill's markup, "<glyph> words", -> (glyph, words) for a
    tile's two lines: split at the first space after the glyph; ("", "")
    for nothing."""
    text = (markup or "").strip()
    if not text:
        return "", ""
    if text.startswith("<"):            # a coloured glyph: <span ...>x</span> rest
        end = text.find("</span>")
        if end >= 0:
            end += len("</span>")
            return text[:end], text[end:].strip()
    head, _sep, tail = text.partition(" ")
    return head, tail.strip()


def workspace_leaf(buttons, workspaces):
    """The dock's workspaces tile: (the one in front, "of N"), from
    workspace_buttons and hyprctl workspaces; ("", "") for none."""
    if not buttons:
        return "", ""
    count = sum(1 for w in workspaces or [] if isinstance(w, dict) and isinstance(w.get("id"), int)
                and not isinstance(w.get("id"), bool) and w["id"] >= 1)
    return buttons[0][1], (f"of {count}" if count > 1 else "")


def badge_count(item, unread):
    """How many unread notifications are an app's (notifications.py unread:
    [[desktop entry, app name], ...]): the sender's desktop entry or name
    against the app's id, name and window class (notify_source.variants)."""
    mine = set()
    for word in (item.get("app_id"), item.get("name"), item.get("class")):
        if word:
            mine |= notify_source.variants(str(word))
    if not mine:
        return 0
    n = 0
    for entry, name in unread or []:
        theirs = (notify_source.variants(entry) if entry else set()) | \
                 (notify_source.variants(name) if name else set())
        if theirs & mine:
            n += 1
    return n


def open_with_argv(app_id, uris, which=shutil.which):
    """Files dropped on an app: `uwsm app -- <id> <uri>...` (gtk-launch
    without uwsm); None for no app or nothing usable."""
    uris = [u for u in uris or [] if isinstance(u, str) and re.match(r"^[a-z][a-z0-9+.-]*:", u)]
    base = launch_argv(app_id, which=which)
    if base is None or not uris:
        return None
    return base + uris


def day_leaf(moment, language=None):
    """The dock's date tile: (weekday, day), "SAT" and "31"; a ja theme's
    weekday as the top bar writes it, "土"."""
    if language == "ja":
        return JA_WEEKDAYS[moment.weekday()], str(moment.day)
    return moment.strftime("%a").upper(), str(moment.day)


def time_leaf(time_text):
    """The dock's time tile: (time, "AM"/"PM" or ""), "9:41 PM" ->
    ("9:41", "PM"): the clock big, a 12-hour clock's half of the day small."""
    head, _sep, tail = (time_text or "").strip().partition(" ")
    return head, tail.strip()


def weather_leaf(markup):
    """The dock's weather tile: wttr.py's pill markup, "<span ...>glyph</span>
    20°", -> (glyph markup, "20°"); ("", "") for nothing."""
    text = (markup or "").strip()
    if not text:
        return "", ""
    head, sep, tail = text.rpartition(" ")
    return (head, tail) if sep else (text, "")


def volume_text(out):
    """`wpctl get-volume` ("Volume: 0.45", "Volume: 0.45 [MUTED]") -> (text,
    tooltip) for the taskbar's sound button; None when it is not that."""
    m = re.match(r"\s*Volume:\s*([0-9.]+)(.*)", out or "")
    if not m:
        return None
    try:
        pct = round(float(m.group(1)) * 100)
    except ValueError:
        return None
    if "MUTED" in m.group(2):
        return MUTED_GLYPH, f"Muted ({pct}%)", "muted"
    glyph = VOLUME_GLYPHS[0 if pct == 0 else 1 if pct < 50 else 2]
    return f"{glyph} {pct}%", f"Volume {pct}%"


def pill_state(line):
    """pill_text's (markup, tooltip) and the pill's JSON "class" ("" without
    one): the PILLS' lines, whose class says how to colour them."""
    got = pill_text(line)
    if got is None:
        return None
    cls_ = json.loads(line).get("class")
    return got + (cls_ if isinstance(cls_, str) else "",)


def network_leaf(text, tip):
    """The dock's network tile: (its glyphs, "") from network.py's pill --
    the interface's glyph alone, no name or address under it (the tooltip
    keeps the details); the text itself when it has no glyph
    ("Disconnected")."""
    plain = re.sub(r"<[^>]*>", "", text or "")
    glyphs = "".join(ch for ch in plain if "\ue000" <= ch <= "\uf8ff")
    return (glyphs or plain.strip()), ""


def language_leaf(codes, index, method=""):
    """The dock's language tile: (the layout's code, "US", and the input
    method when fcitx5 is on one beyond the plain keyboard, "Mozc")."""
    code = codes[index] if isinstance(index, int) and 0 <= index < len(codes) else (codes[0] if codes else "")
    method = (method or "").strip()
    im = "" if not method or method.startswith("keyboard-") else method.replace("-", " ").title()
    return code.upper(), im


def battery_text(capacity, status):
    """A battery's sysfs capacity (0-100, None: no battery) and status
    ("Charging", "Discharging", "Full", ...) -> (text, tooltip, class), as
    the bar's battery module shows it: warning at 25 %, critical at 12 %
    while it runs down; ("", "", "") without a battery."""
    if capacity is None:
        return "", "", ""
    pct = max(0, min(100, int(capacity)))
    glyph = BATTERY_GLYPHS[min(4, (pct + 12) // 25)]
    charging = status in ("Charging", "Full", "Not charging")
    if status == "Charging":
        glyph = f"{CHARGING_GLYPH} {glyph}"
    state = ("charging" if status == "Charging" else "full" if charging
             else "critical" if pct <= 12 else "warning" if pct <= 25 else "")
    words = {"Charging": "charging", "Full": "full", "Not charging": "plugged in"}.get(status, "on battery")
    return f"{glyph} {pct}%", f"Battery {pct}% · {words}", state


def read_battery(root=POWER_SUPPLY):
    """(capacity, status) of the first battery under root, (None, "") with none."""
    try:
        names = sorted(n for n in os.listdir(root) if n.startswith("BAT"))
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(root, name, "capacity")) as fh:
                cap = int(fh.read().strip())
        except (OSError, ValueError):
            continue
        try:
            with open(os.path.join(root, name, "status")) as fh:
                status = fh.read().strip()
        except OSError:
            status = ""
        return cap, status
    return None, ""


def status_wanted(cfg):
    """The status buttons this runs, STATUS_KEYS' and the PILLS': the
    taskbar's by their settings; the dock's only the privacy ones and its
    weather tile, with the top bar off (bar_takeover, dock_tiles)."""
    if not cfg.get("enabled"):
        return set()
    if cfg.get("layout") != "taskbar":
        return ((set(PRIVACY_KEYS) if bar_hidden(cfg) and cfg.get("privacy") else set())
                | ((set(STATUS_TILES) - {"language"}) & set(dock_tiles(cfg))))
    return {k for k in STATUS_KEYS if cfg.get(k)} | {k for k, setting in PILL_SETTING.items() if cfg.get(setting)}


def workspace_buttons(monitors, monitor=None):
    """[(id, name)] for the taskbar's workspace button: the one in front --
    on the focused screen, or with monitor on that screen -- or [] when
    there is none to say (no such screen, a special workspace in front)."""
    for m in monitors or []:
        if (m.get("name") == monitor) if monitor is not None else m.get("focused"):
            ws = m.get("activeWorkspace") or {}
            wid = ws.get("id")
            if isinstance(wid, int) and not isinstance(wid, bool) and wid >= 1:
                return [(wid, str(ws.get("name") or wid))]
            return []
    return []


# The workspace button's click: hyprview's window overview, as SUPER+D
# (lua/overview.lua); nothing when the plugin is not loaded.
OVERVIEW_ARGV = ["hyprctl", "eval", "if hl.plugin.hyprview then hl.plugin.hyprview.toggle('') end"]


def pill_text(line):
    """One JSON line of a top bar script (network.py watch, wttr.py) ->
    (markup, tooltip); None when it is not one. Its text is pango markup
    already, as waybar takes it."""
    try:
        data = json.loads(line)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        return None
    tip = data.get("tooltip")
    return data["text"], tip if isinstance(tip, str) else ""


def menu_category(categories):
    """A desktop file's Categories ("GTK;Game;Utility;") -> the Programs
    submenu it goes in: (title, icon)."""
    have = {c for c in (categories or "").split(";") if c}
    for title, icon, keys in MENU_CATEGORIES:
        if have.intersection(keys):
            return title, icon
    return MENU_OTHER


def menu_programs(apps):
    """[(name, app_id, categories)] -> [((title, icon), [(name, app_id)])]:
    the classic menu's Programs, the submenus by title, the apps by name,
    each id once."""
    groups, seen = {}, set()
    for name, app_id, categories in apps:
        if not name or app_id in seen:
            continue
        seen.add(app_id)
        groups.setdefault(menu_category(categories), []).append((name, app_id))
    return [(cat, sorted(items, key=lambda a: a[0].casefold()))
            for cat, items in sorted(groups.items(), key=lambda kv: kv[0][0].casefold())]


def css_text(path=CSS_FILE):
    """dock.css with its imports made absolute, and an import whose file is
    not there (a theme.py older than the dock's generated copy) left out:
    GTK refuses a whole stylesheet over one missing import."""
    base = os.path.dirname(os.path.abspath(path))
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return ""

    def fix(m):
        target = os.path.normpath(os.path.join(base, m.group(1)))
        return f'@import url("file://{target}");' if os.path.exists(target) else "/* missing: " + m.group(1) + " */"
    return re.sub(r'@import url\("([^":]+)"\);', fix, text)


def parse_item(spec, sender=None):
    """A watcher's item string -> (bus name, object path): ":1.42/StatusNotifierItem",
    ":1.7/org/ayatana/NotificationItem/x" or a bare name (the default path)."""
    spec = str(spec or "")
    if spec.startswith("/"):
        return (sender or "", spec)
    if "/" in spec:
        i = spec.index("/")
        return spec[:i], spec[i:]
    return spec, SNI_PATH


def best_pixmap(pixmaps, size):
    """The IconPixmap entry nearest above `size` (else the largest):
    (w, h, bytes) or None."""
    good = []
    for p in pixmaps or []:
        try:
            w, h, data = int(p[0]), int(p[1]), bytes(p[2])
        except (TypeError, ValueError, IndexError):
            continue
        if w > 0 and h > 0 and len(data) >= w * h * 4:
            good.append((w, h, data))
    if not good:
        return None
    above = [p for p in good if p[0] >= size]
    return min(above, key=lambda p: p[0]) if above else max(good, key=lambda p: p[0])


def argb_to_rgba(data):
    """The spec's ARGB32 in network byte order -> GdkPixbuf's RGBA."""
    src = bytes(data)
    out = bytearray(len(src))
    out[0::4], out[1::4], out[2::4], out[3::4] = src[1::4], src[2::4], src[3::4], src[0::4]
    return bytes(out)


def tooltip_text(props):
    tip = props.get("ToolTip")
    if isinstance(tip, (list, tuple)) and len(tip) >= 4 and (tip[2] or tip[3]):
        title, body = str(tip[2] or ""), re.sub(r"<[^>]+>", "", str(tip[3] or ""))
        return (title + ("\n" + body if body and body != title else "")).strip()
    return str(props.get("Title") or props.get("Id") or "")


def menu_tree(layout):
    """dbusmenu's GetLayout (id, {props}, [children]) unpacked -> plain
    nodes {id, label, enabled, visible, separator, toggle, state, children}."""
    try:
        ident, props, children = layout
    except (TypeError, ValueError):
        return None
    props = props if isinstance(props, dict) else {}
    kids = [n for n in (menu_tree(c) for c in children or []) if n is not None]
    toggle = props.get("toggle-type") or ""
    return {"id": int(ident), "label": str(props.get("label") or ""),
            "enabled": bool(props.get("enabled", True)), "visible": bool(props.get("visible", True)),
            "separator": props.get("type") == "separator", "toggle": toggle if toggle in ("checkmark", "radio") else "",
            "state": props.get("toggle-state") == 1, "children": kids}


# -- the effects (pure; EFFECTS in the module docstring) ----------------------------------------
def motion_ok(enable_animations):
    """Whether anything here may move: reduce motion (Settings >
    Accessibility) turns GNOME's enable-animations off, which GTK reads as
    gtk-enable-animations; off, every effect below is off too (and GTK
    itself stops the stylesheet's transitions and animations)."""
    return bool(enable_animations)


def magnify_on(setting, theme_value, layout):
    """Magnification, for the dock only: the setting's on / off, or with
    "theme" the theme's dock.magnify (bar.conf magnify=)."""
    if layout != "dock":
        return False
    if setting in ("on", "off"):
        return setting == "on"
    return str(theme_value or "").strip().lower() in TRUE_WORDS


def falloff(distance, radius):
    """1 at the pointer, 0 at `radius` and beyond, along half a cosine --
    the hovered icon whole, its neighbours less and less, no edge where the
    growth stops."""
    if radius <= 0:
        return 0.0
    d = abs(distance) / radius
    return 0.0 if d >= 1 else 0.5 * (1 + math.cos(math.pi * d))


def magnify_scales(centers, pointer, slot, peak=MAGNIFY_PEAK, radius=MAGNIFY_RADIUS, fixed=()):
    """Each item's size (1 = as laid out) for a pointer at `pointer` along
    the dock: 1 + (peak - 1) x falloff(distance in icons). `slot` is one
    icon's length in px; the items in `fixed` (the lines) never grow; no
    pointer, nothing grows."""
    if pointer is None or slot <= 0:
        return [1.0] * len(centers)
    return [1.0 if i in fixed else 1 + (peak - 1) * falloff((c - pointer) / slot, radius)
            for i, c in enumerate(centers)]


def spread(starts, lengths, scales, pointer):
    """Where the items start once each is `scales` times its length, laid
    end to end with the gaps they had: the point under the pointer stays
    under it (so the icon under the pointer is still the one you click),
    and the rest move apart around it. No pointer: they grow from the
    first one's start."""
    if not starts:
        return []
    new, at = [], 0.0
    for i, (length, scale) in enumerate(zip(lengths, scales)):
        if i:
            at += max(0.0, starts[i] - (starts[i - 1] + lengths[i - 1]))
        new.append(at)
        at += length * scale
    if pointer is None:
        return [starts[0] + x for x in new]
    p = max(starts[0], min(starts[-1] + lengths[-1], pointer))
    k = next((i for i in range(len(starts)) if p < starts[i] + lengths[i]), len(starts) - 1)
    f = (p - starts[k]) / lengths[k] if lengths[k] else 0.0
    shift = p - (new[k] + f * lengths[k] * scales[k])
    return [x + shift for x in new]


def spread_extents(starts, lengths, scales, new_starts):
    """(before, after): how far the spread items reach past the first one's
    start and the last one's end -- the dock's card grows by as much."""
    if not starts:
        return (0.0, 0.0)
    before = starts[0] - new_starts[0]
    after = new_starts[-1] + lengths[-1] * scales[-1] - (starts[-1] + lengths[-1])
    return (max(0.0, before), max(0.0, after))


def spread_room(slot, peak=MAGNIFY_PEAK, radius=MAGNIFY_RADIUS):
    """The most the items can push past one end: all of the growth, when the
    pointer is on the first or the last icon."""
    k = int(math.ceil(radius))
    return int(math.ceil(slot * (peak - 1) * sum(falloff(i, radius) for i in range(-k, k + 1))))


def approach(current, target, dt, tau):
    """One frame of an exponential approach: `current` moves toward
    `target`, the same fraction of the way every `tau` seconds whatever the
    frame rate -- quick at first, settling softly, never overshooting."""
    if dt <= 0:
        return current
    if tau <= 0:
        return target
    return current + (target - current) * (1 - math.exp(-dt / tau))


def settle(current, target, eps=SETTLE):
    """(value, still moving): snapped to the target once within eps."""
    return (target, False) if abs(target - current) < eps else (current, True)


def hop(t, period=HOP_S):
    """The launch bounce's height (0-1) t seconds in: a parabola per hop,
    0 on the ground, 1 at the top halfway through, again and again."""
    if t <= 0 or period <= 0:
        return 0.0
    x = (t % period) / period
    return 4 * x * (1 - x)


def shelf_margins(layout, position, icon, magnify, motion):
    """The room round the dock's card (or above the taskbar's strip) inside
    its layer surface, {top, bottom, left, right} in px: the card's shadow,
    and on the side away from the screen's edge the height a grown, a
    bouncing or a magnified icon rises to -- reserved once, so nothing
    resizes while it moves (a layer surface that changes size moves). Along
    the dock, with magnification, the most the spread icons can push out."""
    if layout == "taskbar":
        return {"top": TASKBAR_PAD, "bottom": 0, "left": 0, "right": 0}
    tile = icon + 16                      # the button: the icon, its padding, the dots
    if motion:
        peak = MAGNIFY_PEAK if magnify else HOVER_PEAK
        rise = int(math.ceil(tile * (peak - 1) + icon * HOP_FRAC)) + 4
    else:
        rise = 0
    far = max(SHADOW_PAD, rise)
    side = SHADOW_PAD + (spread_room(tile) if (magnify and motion) else 0)
    edge = {"bottom": "bottom", "left": "left", "right": "right"}[position]
    away = {"bottom": "top", "left": "right", "right": "left"}[position]
    out = {"top": side, "bottom": side, "left": side, "right": side}
    out[edge], out[away] = DOCK_MARGIN, far
    return out


def icon_sizes(base, peak, step=ICON_STEP):
    """The pixel sizes a growing icon is rendered at (each from the icon
    theme, so it stays crisp): base, every `step` px up to base x peak."""
    top = int(math.ceil(base * max(1.0, peak)))
    sizes = list(range(base, top - 1, step)) + [top]
    return sorted(set(sizes))


def icon_pick(sizes, want):
    """The cached size nearest the size an icon is drawn at."""
    return min(sizes, key=lambda n: (abs(n - want), -n)) if sizes else int(round(want))


def sd_notify(message):
    import island
    return island.sd_notify(message)


def read_harness(env=None):
    """The scratch harness's file ($DOCK_HARNESS: HARNESS in the module
    docstring) as a dict, {} without one or when it is not JSON."""
    path = (env if env is not None else os.environ).get(HARNESS_ENV)
    if not path:
        return {}
    try:
        with open(path) as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


# -- the system ----------------------------------------------------------------------------
def default_app(role):
    try:
        r = subprocess.run([sys.executable, DEFAULT_APPS, "get", role], capture_output=True, text=True, timeout=8)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def daemon():
    cfg = read_settings()
    if not cfg["enabled"]:
        print("dock: switched off (dock.py set on)", flush=True)
        return 0
    import signal
    import threading
    from datetime import datetime

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango
    import cairo                    # the hidden dock's input region
    import desk_common
    import island                   # fullscreen / game checks, shared with the island
    import screens
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    try:
        import clock as barclock    # bar.conf: the theme's logo= and start=
    except Exception:               # noqa: BLE001
        barclock = None

    harness = read_harness()

    css = Gtk.CssProvider()

    def load_css():
        try:
            css.load_from_data(css_text().encode())
        except GLib.Error as exc:
            print(f"dock: dock.css: {exc}", file=sys.stderr, flush=True)

    def spawn(*cmd):
        if not cmd or cmd[0] is None:
            return
        try:
            proc = subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            print(f"dock: {cmd[0]}: {exc}", file=sys.stderr, flush=True)
            return
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, lambda *_: None)

    def hyprq(cmd):
        return desk_common.hypr_request(cmd, json=True)

    def edges(pos):
        return {"bottom": GtkLayerShell.Edge.BOTTOM, "top": GtkLayerShell.Edge.TOP,
                "left": GtkLayerShell.Edge.LEFT, "right": GtkLayerShell.Edge.RIGHT}[pos]

    def layer_window(win, namespace, layer, gdk_mon):
        win.set_app_paintable(True)
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, namespace)
        GtkLayerShell.set_layer(win, layer)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        if gdk_mon is not None:
            GtkLayerShell.set_monitor(win, gdk_mon)

    def cls(widget, name, on=True):
        ctx = widget.get_style_context()
        (ctx.add_class if on else ctx.remove_class)(name)

    try:                            # GLib 2.86 moved it; Gio's name still works, with a warning
        gi.require_version("GioUnix", "2.0")
        from gi.repository import GioUnix
        DesktopAppInfo = GioUnix.DesktopAppInfo
    except (ImportError, ValueError, AttributeError):
        DesktopAppInfo = Gio.DesktopAppInfo
    app_infos = {}

    def app_info(app_id):
        if app_id not in app_infos:
            try:
                app_infos[app_id] = DesktopAppInfo.new(app_id) if app_id else None
            except (TypeError, GLib.Error):
                app_infos[app_id] = None
        return app_infos[app_id]

    def gicon_for(item):
        info = app_info(item.get("app_id"))
        icon = info.get_icon() if info is not None else None
        return icon or Gio.ThemedIcon.new_from_names(icon_names(item.get("class") or ""))

    # -- the dock's icons: drawn, at every size crisp -----------------------------------------
    from collections import OrderedDict
    fallback_icon = Gio.ThemedIcon.new("application-x-executable")

    class Icons:
        """Rendered icons, (gicon, px, logical size) -> a cairo surface the
        icon theme drew at exactly px pixels: a growing icon is never a
        small picture blown up. Least recently used first out, ICON_CACHE
        in all; emptied when the icon theme changes."""

        def __init__(self):
            self.cache = OrderedDict()
            self.queue = []
            self.idle = None
            Gtk.IconTheme.get_default().connect("changed", lambda *_: self.clear())

        def clear(self):
            self.cache.clear()
            for bar in engine.bars.values():
                bar.queue_draw()

        def get(self, gicon, px, base):
            key = (gicon.to_string() or repr(gicon), px, base)
            surf = self.cache.get(key)
            if surf is not None:
                self.cache.move_to_end(key)
                return surf
            surf = self.render(gicon, px, base)
            self.cache[key] = surf
            while len(self.cache) > ICON_CACHE:
                self.cache.popitem(last=False)
            return surf

        @staticmethod
        def render(gicon, px, base):
            theme = Gtk.IconTheme.get_default()
            flags = Gtk.IconLookupFlags.FORCE_SIZE
            for g in (gicon, fallback_icon):
                try:
                    info = theme.lookup_by_gicon(g, px, flags)
                    pb = info.load_icon() if info is not None else None
                except GLib.Error:
                    pb = None
                if pb is not None:
                    surf = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
                    # Its logical size is the icon's (base): the cairo scale
                    # the dock draws it under makes it px pixels again.
                    surf.set_device_scale(px / base, px / base)
                    return surf
            return None

        def warm(self, gicon, sizes, base):
            """Render the sizes a hover will want, one per idle moment, so
            the first magnification never waits for the icon theme."""
            self.queue += [(gicon, px, base) for px in sizes]
            if self.idle is None:
                self.idle = GLib.idle_add(self.warm_one, priority=GLib.PRIORITY_LOW)

        def warm_one(self):
            if not self.queue:
                self.idle = None
                return False
            gicon, px, base = self.queue.pop(0)
            self.get(gicon, px, base)
            return True

    class DockIcon(Gtk.DrawingArea):
        """A dock button's icon: drawn from Icons at the pixel size it is
        shown at (the dock's scale for it, times the screen's), so a
        magnified or a pressed icon is as sharp as one at rest. Styled as
        .dock-icon: -gtk-icon-shadow, -gtk-icon-effect and opacity apply."""

        def __init__(self, bar):
            super().__init__()
            self.bar, self.gicon, self.size, self.sizes = bar, None, 0, []
            self.peak, self.factor = 1.0, 1
            cls(self, "dock-icon")
            self.connect("draw", self.on_draw)

        def set_icon(self, gicon, size, peak):
            self.gicon, self.size, self.peak = gicon, size, peak
            self.set_size_request(size, size)
            self.fit_sizes()
            self.queue_draw()

        def fit_sizes(self):
            """The pixel sizes to render at, for this screen's scale (known
            for sure only once it is drawn there)."""
            self.factor = self.get_scale_factor()
            self.sizes = icon_sizes(self.size * self.factor, max(1.0, self.peak))
            if self.peak > 1:
                icons.warm(self.gicon, self.sizes[1:], self.size)

        def on_draw(self, _w, cr):
            if self.gicon is None or not self.size:
                return False
            if self.get_scale_factor() != self.factor:
                self.fit_sizes()
            fx = self.bar.fx
            scale = fx.drawn_scale(self.get_parent().get_parent()) if fx is not None else 1.0
            px = icon_pick(self.sizes, self.size * scale * self.get_scale_factor())
            surf = icons.get(self.gicon, px, self.size)
            if surf is not None:
                a = self.get_allocation()
                Gtk.render_icon_surface(self.get_style_context(), cr, surf,
                                        (a.width - self.size) / 2, (a.height - self.size) / 2)
            return False

    # -- one app's button --------------------------------------------------------------------
    class ItemButton(Gtk.Button):
        def __init__(self, bar):
            super().__init__()
            self.bar, self.engine = bar, bar.engine
            self.item, self.icon_key = None, None
            self.set_relief(Gtk.ReliefStyle.NONE)
            self.set_can_focus(False)
            cls(self, "dock-item")
            taskbar = bar.layout == "taskbar"
            vertical = not taskbar and bar.position == "bottom"
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                          spacing=2)
            if taskbar:
                self.image = Gtk.Image()
                cls(self.image, "dock-icon")
            else:
                self.image = DockIcon(bar)
            # the dock's unread badge, over the icon's top corner (set_badge)
            self.badge = Gtk.Label()
            cls(self.badge, "dock-badge")
            self.badge.set_halign(Gtk.Align.END)
            self.badge.set_valign(Gtk.Align.START)
            self.badge.set_no_show_all(True)
            # the dock follows the pointer over its buttons (magnification)
            self.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
            self.dots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if vertical else Gtk.Orientation.VERTICAL,
                                spacing=0)
            self.dots.set_halign(Gtk.Align.CENTER)
            self.dots.set_valign(Gtk.Align.CENTER)
            cls(self.dots, "dock-dots")
            self.label = Gtk.Label(xalign=0)
            cls(self.label, "dock-label")
            from gi.repository import Pango
            self.label.set_ellipsize(Pango.EllipsizeMode.END)
            self.label.set_max_width_chars(22)
            self.label.set_width_chars(1)
            self.count = Gtk.Label()
            cls(self.count, "dock-count")
            if taskbar:
                box.pack_start(self.image, False, False, 0)
                box.pack_start(self.label, True, True, 0)
                box.pack_start(self.count, False, False, 0)
                self.label.set_no_show_all(True)
                self.count.set_no_show_all(True)
            else:
                art = Gtk.Overlay()
                art.add(self.image)
                art.add_overlay(self.badge)
                art.set_overlay_pass_through(self.badge, True)
                if bar.position == "right":
                    box.pack_start(self.dots, False, False, 0)
                    box.pack_start(art, False, False, 0)
                else:
                    box.pack_start(art, False, False, 0)
                    box.pack_start(self.dots, False, False, 0)
            self.add(box)
            self.connect("button-press-event", self.on_press)
            self.connect("button-release-event", self.on_release)
            self.connect("clicked", self.on_clicked)
            self.connect("enter-notify-event", lambda *_: (self.engine.hover(self), False)[1])
            self.connect("leave-notify-event", lambda *_: (self.engine.unhover(self), False)[1])
            # Moved along the dock with the button held: the dock's own drag
            # (Bar.drag_*: it swaps places with the icons it passes, live).
            # GTK's drag and drop only for files from a file manager, which
            # open with the app.
            self.suppress_click = False
            self.connect("motion-notify-event", lambda _w, ev: self.bar.drag_motion(self, ev))
            self.drag_dest_set(Gtk.DestDefaults.ALL,
                               [Gtk.TargetEntry.new("text/uri-list", Gtk.TargetFlags.OTHER_APP, 1)],
                               Gdk.DragAction.MOVE | Gdk.DragAction.COPY | Gdk.DragAction.LINK)
            self.connect("drag-data-received", self.on_drag_received)

        def set_item(self, item):
            self.item = item
            size = TASKBAR_ICON if self.bar.layout == "taskbar" else self.engine.cfg["icon_size"]
            key = (item.get("app_id"), item.get("class"), size)
            if key != self.icon_key:
                self.icon_key = key
                if self.bar.layout == "taskbar":
                    self.image.set_from_gicon(gicon_for(item), Gtk.IconSize.DIALOG)
                    self.image.set_pixel_size(size)
                else:
                    self.image.set_icon(gicon_for(item), size, self.bar.fx.peak if self.bar.fx else 1.0)
            running = bool(item["windows"])
            for name, on in (("running", running), ("focused", item["focused"]), ("urgent", item["urgent"]),
                             ("launching", item["launching"]), ("pinned", item["pinned"])):
                cls(self, name, on)
            if self.bar.fx is not None:
                # the dock bounces a launching app instead of the stylesheet's
                # breath (.bouncing turns that off)
                self.bar.fx.launching(self, item["launching"])
                cls(self, "bouncing", item["launching"])
            if self.bar.layout == "taskbar":
                show = self.engine.cfg["labels"]
                self.label.set_text(item["title"])
                self.label.set_visible(show)
                n = len(item["windows"])
                self.count.set_text(str(n))
                self.count.set_visible(n > 1)
            else:
                # Three dots always there, the ones that count .lit: a dot
                # that comes or goes is a class change, which the stylesheet
                # can ease (transition) -- a new widget would just appear.
                have = self.dots.get_children()
                for i in range(len(have), 3):
                    dot = Gtk.Box()
                    cls(dot, "dock-dot")
                    cls(dot, "first", i == 0)
                    dot.show()
                    self.dots.pack_start(dot, False, False, 0)
                want = min(3, len(item["windows"]))
                for i, dot in enumerate(self.dots.get_children()):
                    cls(dot, "lit", i < want)
            tip = None if (running and self.engine.cfg["previews"]) else item["title"]
            if self.bar.layout == "taskbar" and self.engine.cfg["labels"] and not running:
                tip = item["name"]
            self.set_tooltip_text(tip)

        def on_press(self, _w, event):
            if event.type != Gdk.EventType.BUTTON_PRESS:
                return True
            if event.button == 3:
                self.engine.item_menu(self, event)
                return True
            if event.button == 1:
                self.suppress_click = False
                self.bar.drag_press(self, event)
                if self.bar.fx is not None:
                    self.bar.fx.press(self)
            return False

        def on_release(self, _w, event):
            if event.button == 1:
                self.bar.drag_release(self)
            if self.bar.fx is not None:
                self.bar.fx.release(self)
            if event.button == 2:
                self.engine.new_window(self.item)
            return False

        def on_clicked(self, _w):
            if self.suppress_click:       # the release that ended a drag
                self.suppress_click = False
                return
            self.engine.click(self.item)

        def on_drag_received(self, _w, _ctx, _x, _y, data, info, _time):
            if self.item and info == 1:
                self.engine.open_files(self.item, data.get_uris() or [])

        def set_badge(self, n):
            """The unread notifications' count over the icon; none at 0."""
            self.badge.set_text(str(min(n, BADGE_MAX)) + ("+" if n > BADGE_MAX else ""))
            self.badge.set_visible(n > 0)

    # -- the dock's motion -------------------------------------------------------------------
    class Fx:
        """The dock's effects (EFFECTS in the module docstring), one per
        dock: each item's size eased toward a target by approach(), on the
        frame clock -- a tick callback that exists only while something
        moves, so a still dock costs nothing. The targets: magnification
        from the pointer (magnify), else the hovered icon a little bigger;
        a held one a little smaller; a launching one hops. Drawn by
        Bar.draw_frame / draw_items, each child under a cairo transform
        with its allocation untouched: nothing is laid out again, and the
        layer surface keeps its size (shelf_margins reserved the room)."""

        def __init__(self, bar, magnify):
            self.bar = bar
            self.magnify = magnify
            self.peak = MAGNIFY_PEAK if magnify else HOVER_PEAK
            self.tau = TAU_MAGNIFY_S if magnify else TAU_HOVER_S
            self.pointer = None        # along the dock, in the items box's px
            self.anchor = None         # the last pointer: the spread's still point
            self.hovered = None
            self.pressed = None
            self.hops = {}             # button -> [start s, end s or None]
            self.scale = {}            # child -> its size now (1 = as laid out)
            self.tick = None
            self.last = None
            self.now = GLib.get_monotonic_time() / 1e6
            self.expanded = False      # magnifying: the whole surface takes the pointer
            self.custom = False        # the last frame was drawn by hand
            self.drawn = {}            # child -> (scale, shift along, lift), as drawn
            self.extents = (0.0, 0.0)  # how far the card reaches past its ends
            self.gone = None
            self.t0 = 0.0
            self.stats = {"draw_ms": [], "frame_ms": []} if harness else None

        # what is there
        def horizontal(self):
            return self.bar.position == "bottom"

        def kids(self):
            return [c for c in self.bar.items.get_children() if c.get_visible()]

        def geometry(self, kids):
            """(starts, lengths, scalable) along the dock, in the items box."""
            ba = self.bar.items.get_allocation()
            horiz = self.horizontal()
            starts, lengths, scalable = [], [], []
            for c in kids:
                a = c.get_allocation()
                starts.append(float(a.x - ba.x) if horiz else float(a.y - ba.y))
                lengths.append(float(a.width if horiz else a.height))
                scalable.append(isinstance(c, ItemButton) or c is self.bar.toolbox
                                or any(c is t[0] for t in self.bar.tiles.values()))
            return starts, lengths, scalable

        def targets(self, kids):
            starts, lengths, scalable = self.geometry(kids)
            if self.magnify:
                tiles = sorted(l for l, sc in zip(lengths, scalable) if sc)
                slot = tiles[len(tiles) // 2] if tiles else 0
                centers = [a + l / 2 for a, l in zip(starts, lengths)]
                fixed = {i for i, sc in enumerate(scalable) if not sc}
                want = magnify_scales(centers, self.pointer, slot, self.peak, MAGNIFY_RADIUS, fixed)
            else:
                want = [self.peak if (c is self.hovered and sc) else 1.0 for c, sc in zip(kids, scalable)]
            return {c: w * (PRESS_SCALE if c is self.pressed else 1.0) for c, w in zip(kids, want)}

        def lift(self, child):
            got = self.hops.get(child)
            if not got or not isinstance(child, ItemButton):
                return 0.0
            return self.bar.engine.cfg["icon_size"] * HOP_FRAC * hop(self.now - got[0])

        def drawn_scale(self, child):
            return self.scale.get(child, 1.0)

        # the clock
        def kick(self):
            if self.tick is None and self.bar.get_mapped():
                self.last = None
                self.tick = self.bar.add_tick_callback(self.on_tick)

        def stop(self):
            if self.tick is not None:
                self.bar.remove_tick_callback(self.tick)
                self.tick = None

        def on_tick(self, _widget, clock):
            self.now = clock.get_frame_time() / 1e6
            dt = 1 / 60 if self.last is None else min(0.1, self.now - self.last)
            if self.stats is not None and self.last is not None and len(self.stats["frame_ms"]) < FX_STATS:
                self.stats["frame_ms"].append(round((self.now - self.last) * 1000, 3))
            self.last = self.now
            kids = self.kids()
            moving = False
            for child, target in self.targets(kids).items():
                cur, going = settle(approach(self.scale.get(child, 1.0), target, dt, self.tau), target)
                self.scale[child] = cur
                moving = moving or going
            self.scale = {c: v for c, v in self.scale.items() if c in kids and v != 1.0}
            for child, (start, end) in list(self.hops.items()):
                if child not in kids or (end is not None and self.now >= end):
                    del self.hops[child]
            moving = moving or bool(self.hops)
            self.bar.queue_draw()
            if not moving:
                self.tick, self.last = None, None
                if self.pointer is None and self.expanded:
                    self.expanded = False
                    self.bar.fit_input()
                return False
            return True

        # what moves it
        def point(self, along):
            if self.gone is not None:
                GLib.source_remove(self.gone)
                self.gone = None
            self.pointer = self.anchor = along
            if self.magnify and not self.expanded:
                self.expanded = True
                self.bar.fit_input()
            if self.magnify:
                self.kick()

        def leave(self):
            """The pointer left the dock -- or so a crossing event says: only
            after GONE_MS without a motion do the icons fall back, so a
            leave that pairs with an enter (a child's) costs nothing."""
            if not self.magnify or self.pointer is None or self.gone is not None:
                return

            def gone():
                self.gone = None
                self.pointer = None
                self.kick()
                return False
            self.gone = GLib.timeout_add(GONE_MS, gone)

        def hover(self, button, on):
            if on:
                self.hovered = button
            elif self.hovered is button:
                self.hovered = None
            if not self.magnify:
                self.kick()

        def press(self, button):
            self.pressed = button
            self.kick()

        def release(self, button):
            if self.pressed is not None:
                self.pressed = None
                self.kick()

        def launching(self, button, on):
            got = self.hops.get(button)
            if on and (got is None or got[1] is not None):
                self.hops[button] = [GLib.get_monotonic_time() / 1e6 if got is None else got[0], None]
                self.kick()
            elif not on and got is not None and got[1] is None:
                # land the hop it is in rather than drop out of the air
                start = got[0]
                n = max(1, math.ceil((GLib.get_monotonic_time() / 1e6 - start) / HOP_S))
                got[1] = start + n * HOP_S
                self.kick()

        def reset(self):
            """Hidden: everything back to rest, no clock."""
            self.stop()
            if self.gone is not None:
                GLib.source_remove(self.gone)
                self.gone = None
            self.pointer = self.anchor = self.hovered = self.pressed = None
            self.scale.clear()
            self.hops.clear()
            self.drawn, self.extents, self.expanded, self.custom = {}, (0.0, 0.0), False, False

        # drawing
        def compute(self):
            """The frame's layout -> whether it needs drawing by hand."""
            kids = self.kids()
            starts, lengths, scalable = self.geometry(kids)
            sc = [self.scale.get(c, 1.0) for c in kids]
            if self.magnify:
                new = spread(starts, lengths, sc, self.anchor)
                self.extents = spread_extents(starts, lengths, sc, new)
            else:
                new = [a + l * (1 - s) / 2 for a, l, s in zip(starts, lengths, sc)]
                self.extents = (0.0, 0.0)
            self.drawn = {}
            moved = False
            for i, c in enumerate(kids):
                shift = new[i] + lengths[i] * sc[i] / 2 - (starts[i] + lengths[i] / 2)
                lift = self.lift(c)
                self.drawn[c] = (sc[i], shift, lift)
                moved = moved or sc[i] != 1.0 or abs(shift) > 0.01 or lift > 0.01
            return moved

        def child_at(self, along):
            """The child drawn under a point along the dock (a click on the
            part of a magnified icon that sticks out of the card)."""
            ba = self.bar.items.get_allocation()
            horiz = self.horizontal()
            for c, (s, shift, _lift) in self.drawn.items():
                a = c.get_allocation()
                start, length = ((a.x - ba.x, a.width) if horiz else (a.y - ba.y, a.height))
                mid = start + length / 2 + shift
                if abs(along - mid) <= length * s / 2:
                    return c
            return None

    # -- one screen's dock or taskbar ---------------------------------------------------------
    class Bar(Gtk.Window):
        def __init__(self, engine, name, gdk_mon, main):
            super().__init__()
            self.engine, self.name, self.gdk_mon, self.main = engine, name, gdk_mon, main
            self.layout = engine.cfg["layout"]
            self.position = "bottom" if self.layout == "taskbar" else engine.cfg["position"]
            self.buttons = {}
            self.dragging = None         # the dock's own drag (drag_press .. drag_release)
            self.edge = None
            self.hovered = False
            self.hidden = False          # autohide: unmapped, the edge stands in
            self.suppressed = False      # fullscreen / a game
            self.rect = None             # (x, y, w, h), the last one Hyprland told
            self.zone = None
            self.magnify = engine.magnify() if self.layout == "dock" else False
            self.shelf_cache = None      # (key, picture): shelf_picture()
            self.style_serial = 0
            self.fx = Fx(self, self.magnify) if (self.layout == "dock" and engine.motion) else None
            self.set_name("dock-window")
            # the harness draws above its stage, on the overlay layer
            layer_window(self, NAMESPACE if self.layout == "dock" else "waybar-taskbar",
                         GtkLayerShell.Layer.OVERLAY if harness else GtkLayerShell.Layer.TOP, gdk_mon)
            edge = edges(self.position)
            GtkLayerShell.set_anchor(self, edge, True)
            if self.layout == "taskbar":
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
            # The surface holds the card and the room round it (shelf_margins:
            # its shadow, a grown icon), so it reaches the edge itself and
            # reserves its strip by hand, from the card's size (on_allocate).
            GtkLayerShell.set_exclusive_zone(self, 0)
            self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                            | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                            | Gdk.EventMask.BUTTON_RELEASE_MASK)
            self.connect("enter-notify-event", self.on_enter)
            self.connect("leave-notify-event", self.on_leave)
            self.connect("motion-notify-event", self.on_motion)
            self.connect("button-press-event", self.on_band_press)
            self.connect("button-release-event", self.on_band_release)
            self.connect("size-allocate", self.on_allocate)
            self.connect("realize", lambda *_: self.fit_input())
            self.connect("map-event", lambda *_: (engine.debounce(f"rect-{self.name}", 200, self.learn_rect), False)[1])
            self.build()
            self.edge = Edge(self) if self.layout == "dock" else None

        def build(self):
            sideways = self.position in ("left", "right")
            orient = Gtk.Orientation.VERTICAL if sideways else Gtk.Orientation.HORIZONTAL
            self.frame = Gtk.Box(orientation=orient, spacing=0)
            self.frame.set_name("dock")
            cls(self.frame, f"dock-layout-{self.layout}")
            cls(self.frame, f"dock-pos-{self.position}")
            cls(self.frame, "dock-magnify", self.magnify)
            room = shelf_margins(self.layout, self.position, self.engine.cfg["icon_size"], self.magnify,
                                 self.fx is not None)
            self.frame.set_margin_top(room["top"])
            self.frame.set_margin_bottom(room["bottom"])
            self.frame.set_margin_start(room["left"])
            self.frame.set_margin_end(room["right"])
            self.frame.set_valign(Gtk.Align.END if self.position == "bottom" else Gtk.Align.CENTER)
            self.add(self.frame)
            self.items = Gtk.Box(orientation=orient, spacing=0)
            if self.fx is not None:
                self.frame.connect("draw", self.draw_frame)
                self.frame.connect("style-updated", self.on_shelf_style)
                self.items.connect("draw", self.draw_items)
                for w in (self.frame, self.items):
                    w.connect("size-allocate", self.widen_clip)
            self.sep = Gtk.Box()
            cls(self.sep, "dock-sep")
            self.sep.set_no_show_all(True)
            self.tray_box = self.clock = self.start = self.toolbox = self.ws_box = None
            self.tiles = {}              # DOCK TILES: kind -> (button, box, top label, bottom label)
            self.lead = []               # before the apps in the items box (the Apps button)
            self.status = {}             # STATUS_KEYS and the PILLS -> (button, label)
            self.ws_key = None           # the workspace buttons drawn last (update_workspaces)
            wanted = status_wanted(self.engine.cfg)
            if self.layout == "taskbar":
                self.start = Gtk.Button()
                self.start.set_relief(Gtk.ReliefStyle.NONE)
                self.start.set_can_focus(False)
                cls(self.start, "dock-start")
                inner = Gtk.Box(spacing=0)
                self.start_glyph = Gtk.Label()
                cls(self.start_glyph, "dock-start-glyph")
                self.start_text = Gtk.Label()
                cls(self.start_text, "dock-start-text")
                self.start_text.set_no_show_all(True)
                inner.pack_start(self.start_glyph, False, False, 0)
                inner.pack_start(self.start_text, False, False, 0)
                self.start.add(inner)
                self.start.set_tooltip_text("Start")
                self.start.connect("clicked", lambda b: self.engine.open_start(b))
                self.frame.pack_start(self.start, False, False, 0)
                if self.engine.cfg["workspaces"]:
                    self.ws_box = Gtk.Box(spacing=0)
                    cls(self.ws_box, "dock-workspaces")
                    self.frame.pack_start(self.ws_box, False, False, 0)
                self.frame.pack_start(self.items, True, True, 0)
                if "notifications" in wanted:   # the far right, after the clock
                    self.frame.pack_end(self.make_status("notifications"), False, False, 0)
                if self.engine.cfg["clock"]:
                    self.clock = Gtk.Button()
                    self.clock.set_relief(Gtk.ReliefStyle.NONE)
                    self.clock.set_can_focus(False)
                    cls(self.clock, "dock-clock")
                    lines = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                    lines.set_valign(Gtk.Align.CENTER)
                    self.time_label, self.date_label = Gtk.Label(), Gtk.Label()
                    cls(self.time_label, "dock-time")
                    cls(self.date_label, "dock-date")
                    lines.pack_start(self.time_label, False, False, 0)
                    lines.pack_start(self.date_label, False, False, 0)
                    self.clock.add(lines)
                    self.clock.connect("clicked", lambda *_: spawn(sys.executable, PANEL, "toggle", "calendar"))
                    self.frame.pack_end(self.clock, False, False, 0)
                if self.main:       # between the tray and the clock (packed from the end)
                    self.frame.pack_end(self.make_toolbox(), False, False, 0)
                for key in ("battery",) + STATUS_KEYS:     # then battery, sound, network, weather, leftwards
                    if key in wanted:
                        self.frame.pack_end(self.make_status(key), False, False, 0)
                if self.engine.cfg["tray"] and self.main:
                    self.tray_box = Gtk.Box(spacing=0)
                    cls(self.tray_box, "dock-tray")
                    self.frame.pack_end(self.tray_box, False, False, 0)
                if wanted & set(PRIVACY_KEYS):      # what is in use, left of the tray
                    self.frame.pack_end(self.make_privacy(), False, False, 0)
                self.restyle_start()
            else:
                self.frame.pack_start(self.items, False, False, 0)
                if self.main and dock_only(self.engine.cfg):    # DOCK TILES: first, the Apps button
                    self.lead.append(self.make_tile("apps"))
                    self.items.pack_start(self.lead[-1], False, False, 0)
                if self.main:       # a line, then the button: the dock's last item
                    # in the items box, after every app (update() only ever
                    # moves the apps and the pinned line, at the front), so
                    # the effects move them with the rest
                    line = Gtk.Box()
                    cls(line, "dock-sep")
                    self.items.pack_start(line, False, False, 0)
                    names = [t for kind in dock_tiles(self.engine.cfg)    # DOCK TILES: before the toolbox,
                             for t in (("time", "date") if kind == "clock" else (kind,))]
                    for tile in ordered_tiles(names, self.engine.cfg.get("tile_order")):    # as dragged
                        self.items.pack_start(self.make_tile(tile), False, False, 0)
                    self.items.pack_start(self.make_toolbox(), False, False, 0)
                    self.toolbox.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
                if self.main and wanted & set(PRIVACY_KEYS):
                    # With the top bar off: what is in use, after the card's
                    # items -- outside them, so the effects leave it be.
                    self.frame.pack_start(self.make_privacy(), False, False, 0)
            self.items.pack_start(self.sep, False, False, 0)
            self.frame.show_all()

        def make_toolbox(self):
            """The toolbox button (THE TOOLBOX in the module docstring): the
            sliders glyph, `toolbox.sh toggle` on a click. On the dock it is
            as big as an app's button."""
            self.toolbox = Gtk.Button()
            self.toolbox.set_relief(Gtk.ReliefStyle.NONE)
            self.toolbox.set_can_focus(False)
            cls(self.toolbox, "dock-toolbox")
            self.toolbox_glyph = Gtk.Label(label=TOOLBOX_GLYPH)
            cls(self.toolbox_glyph, "dock-toolbox-glyph")
            self.toolbox.add(self.toolbox_glyph)
            self.toolbox.set_tooltip_text("Toolbox: game mode, night light, Keep awake, shortcuts, the tray")
            self.toolbox.connect("clicked", lambda *_: spawn(TOOLBOX_SH, "toggle"))
            self.size_toolbox()
            return self.toolbox

        def make_tile(self, kind):
            """A dock tile (DOCK TILES in the module docstring): two lines
            in an app icon's square, "dock-tile-<kind>"; what its clicks and
            its wheel do: tile_click, tile_scroll."""
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_can_focus(False)
            cls(btn, "dock-tile")
            cls(btn, f"dock-tile-{kind}")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.set_valign(Gtk.Align.CENTER)
            top, bottom = Gtk.Label(), Gtk.Label()
            cls(top, "dock-tile-top")
            cls(bottom, "dock-tile-bottom")
            box.pack_start(top, True, True, 0)
            box.pack_start(bottom, True, True, 0)
            btn.add(box)
            btn.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK
                           | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            btn.suppress_click = False
            btn.connect("clicked", lambda b: self.engine.tile_click(kind, 1, b)
                        if not self.unsuppress(b) else None)
            if kind != "apps":
                # Dragged along the dock: among the other tiles (drag_*), its
                # place kept in tile_order.
                btn.connect("button-press-event", lambda b, ev: ev.button == 1
                            and ev.type == Gdk.EventType.BUTTON_PRESS and self.drag_press(b, ev))
                btn.connect("motion-notify-event", lambda b, ev: self.drag_motion(b, ev))
                btn.connect("button-release-event", lambda b, ev: ev.button == 1 and self.drag_release(b))
            btn.connect("button-press-event", lambda b, ev: ev.button in (2, 3)
                        and ev.type == Gdk.EventType.BUTTON_PRESS and self.engine.tile_click(kind, ev.button, b))
            btn.connect("scroll-event", lambda _b, ev: self.engine.tile_scroll(kind, ev))
            self.tiles[kind] = (btn, box, top, bottom)
            self.size_tile(kind)
            if kind == "apps":
                top.set_text(START_GLYPH)
                bottom.set_visible(False)
                bottom.set_no_show_all(True)
                btn.set_tooltip_text("Apps")
            if kind in TILE_HIDDEN:
                # Hidden until there is something to say: out of the dock's
                # show_all, so its own lines are shown here, the button by
                # set_status / set_submap.
                box.show_all()
                btn.set_no_show_all(True)
                btn.set_visible(False)
            if kind in STATUS_TILES:
                self.set_status(kind, *(self.engine.status_text.get(kind) or ("", "")))
            elif kind == "language":
                self.set_language(self.engine.language)
            elif kind == "submap":
                self.set_submap(self.engine.submap)
            elif kind == "workspaces":
                self.update_ws_tile(self.engine.ws_now(self.name))
            return btn

        def set_language(self, got):
            if "language" not in self.tiles:
                return
            btn, _box, top, bottom = self.tiles["language"]
            code, im = got
            top.set_text(code or "\uf11c")
            bottom.set_text(im)
            bottom.set_visible(bool(im))
            btn.set_tooltip_text(f"Keyboard: {code}" + (f" · {im}" if im else "")
                                 + "\nclick: the layouts and input methods, right-click: the next layout")

        def set_submap(self, name):
            if "submap" not in self.tiles:
                return
            btn, _box, top, bottom = self.tiles["submap"]
            top.set_text(SUBMAP_GLYPH)
            bottom.set_text((name or "").capitalize())
            btn.set_tooltip_text(f"{(name or '').capitalize()} mode: Esc leaves it; click: leave it" if name else None)
            btn.set_visible(bool(name))

        def update_ws_tile(self, got):
            if "workspaces" not in self.tiles:
                return
            btn, _box, top, bottom = self.tiles["workspaces"]
            head, tail = got
            top.set_text(head)
            bottom.set_text(tail)
            bottom.set_visible(bool(tail))
            btn.set_tooltip_text(f"Workspace {head} {tail}".strip() + "\nclick: every window, scroll: the next one"
                                 if head else None)

        def size_tile(self, kind):
            """A tile's square and its two lines' sizes, from icon_size (as
            size_toolbox): the time's digits and the day big, the rest small.
            The square is TILE_GROW px past an icon's: a card of words reads
            smaller than a picture of the same size (dock.css takes the
            room back from the button's padding, so the dock stays as tall)."""
            _btn, box, top, bottom = self.tiles[kind]
            icon = self.engine.cfg["icon_size"] + TILE_GROW
            box.set_size_request(icon, icon)
            big = TILE_SHARES[kind]
            if kind == "media":             # "Playing 2/3" in a tile's width
                bottom.set_ellipsize(Pango.EllipsizeMode.END)
                bottom.set_max_width_chars(9)
            for label, share in ((top, big[0]), (bottom, big[1])):
                if not share:
                    continue
                attrs = Pango.AttrList()
                attrs.insert(Pango.attr_size_new_absolute(int(icon * share * Pango.SCALE)))
                label.set_attributes(attrs)

        def make_status(self, key):
            """A status button (TOP BAR in the module docstring): the top
            bar's pill's text, its panel on a click. Right click: the sound
            mutes, the weather opens wttr.in; the wheel on the sound sets
            the volume."""
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_can_focus(False)
            cls(btn, "dock-status")
            cls(btn, f"dock-{key}")
            label = Gtk.Label()
            cls(label, "dock-status-text")
            btn.add(label)
            btn.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            if key in PILL_CLICKS:
                btn.connect("button-press-event", lambda _b, ev: self.engine.pill_click(key, ev))
            else:
                btn.connect("clicked", lambda *_: spawn(sys.executable, PANEL, "toggle", STATUS_PANELS[key]))
                btn.connect("button-press-event", lambda _b, ev: self.engine.status_click(key, ev))
                btn.connect("scroll-event", lambda _b, ev: self.engine.status_scroll(key, ev))
            btn.set_no_show_all(True)
            self.status[key] = (btn, label)
            self.set_status(key, *(self.engine.status_text.get(key) or ("", "")))
            return btn

        def make_privacy(self):
            """The privacy cluster (PILLS): recording, mic, camera, location,
            each shown only while in use."""
            box = Gtk.Box(spacing=0)
            cls(box, "dock-privacy")
            for key in PRIVACY_KEYS:
                box.pack_start(self.make_status(key), False, False, 0)
            return box

        def set_status(self, key, text, tip, state=""):
            if key in self.tiles and key in STATUS_TILES:
                btn, _box, top, bottom = self.tiles[key]
                # the weather, the battery and the sound: the last word under
                # the glyphs ("<bolt> <battery> 97%"); the network: its glyph
                # alone; the rest: the first glyph over the words
                if key == "network":
                    glyph, words = network_leaf(text, tip)
                elif key == "sound" and state == "muted":
                    glyph, words = text, "Muted"     # the speaker struck out, and the word
                elif key in ("weather", "battery", "sound"):
                    glyph, words = weather_leaf(text)
                else:
                    glyph, words = leaf(text)
                top.set_markup(glyph)
                bottom.set_markup(words) if key == "weather" else bottom.set_text(re.sub(r"<[^>]*>", "", words))
                bottom.set_visible(bool(words))
                hint = {"media": "click: play / pause, right-click: next, middle: the media panel",
                        "sound": "click: the audio panel, scroll: louder / quieter, right-click: mute, "
                                 "middle: mute the microphone",
                        "network": "click: the network panel, right-click: nmtui"}.get(key)
                btn.set_tooltip_text("\n".join(t for t in (tip, hint) if t) or None)
                # (the battery's: whenever there is one, charging or not --
                # the card leaves its Battery row out for it)
                btn.set_visible(bool(glyph or words))
                ctx = btn.get_style_context()
                for name in ctx.list_classes():
                    if name.startswith("dock-is-"):
                        ctx.remove_class(name)
                if state and re.match(r"^[A-Za-z0-9_-]+$", state):
                    ctx.add_class(f"dock-is-{state}")
                if key == "media":
                    cls(btn, "dock-is-playing", words.startswith("Playing"))
            if key not in self.status:
                return
            btn, label = self.status[key]
            label.set_markup(text)
            btn.set_tooltip_text(tip or None)
            btn.set_visible(bool(text))
            label.set_visible(bool(text))
            ctx = btn.get_style_context()
            for name in ctx.list_classes():
                if name.startswith("dock-is-"):
                    ctx.remove_class(name)
            if state and re.match(r"^[A-Za-z0-9_-]+$", state):
                ctx.add_class(f"dock-is-{state}")

        def update_workspaces(self, buttons):
            """The workspace button (workspace_buttons), rebuilt only when it
            changes."""
            if self.ws_box is None or buttons == self.ws_key:
                return
            self.ws_key = buttons
            for child in self.ws_box.get_children():
                child.destroy()
            for _wid, name in buttons:
                b = Gtk.Button(label=name)
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.set_can_focus(False)
                cls(b, "dock-ws")
                b.set_tooltip_text(f"Workspace {name} -- click: every window (Super+D)")
                b.connect("clicked", lambda *_: spawn(*OVERVIEW_ARGV))
                self.ws_box.pack_start(b, False, False, 0)
            self.ws_box.show_all()

        def size_toolbox(self):
            if self.toolbox is None or self.layout != "dock":
                return
            icon = self.engine.cfg["icon_size"]
            self.toolbox_glyph.set_size_request(icon, icon)
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_size_new_absolute(int(icon * 0.5 * Pango.SCALE)))
            self.toolbox_glyph.set_attributes(attrs)

        def restyle_start(self):
            if self.start is None:
                return
            conf = self.engine.theme
            self.start_glyph.set_text(conf.get("logo") or START_GLYPH)
            word = conf.get("start") or ""
            self.start_text.set_text(word)
            self.start_text.set_visible(bool(word))

        def update(self, items):
            if self.dragging and self.dragging["on"]:
                return            # mid-drag: drag_release renders it all once the icon is let go
            keys = [it["key"] for it in items]
            for key in [k for k in self.buttons if k not in keys]:
                self.buttons.pop(key).destroy()
            # never-combine: a pinned app's windows all stand at its place,
            # only the first marked pinned -- they all count as pinned here
            pinned_groups = {it["group"] for it in items if it["pinned"]}
            pinned_n = sum(1 for it in items if it["group"] in pinned_groups)
            show_sep = self.layout == "dock" and 0 < pinned_n < len(items)
            pos = len(self.lead)
            for i, item in enumerate(items):
                if i == pinned_n and show_sep:
                    self.items.reorder_child(self.sep, pos)
                    pos += 1
                btn = self.buttons.get(item["key"])
                if btn is None:
                    btn = self.buttons[item["key"]] = ItemButton(self)
                    self.items.pack_start(btn, False, False, 0)
                    btn.show_all()
                btn.set_item(item)
                btn.set_badge(self.engine.badge_for(item) if self.layout == "dock" else 0)
                self.items.reorder_child(btn, pos)
                pos += 1
            self.sep.set_visible(show_sep)

        def set_clock(self, time_text, date_text, leaf=None):
            if self.clock is not None:
                self.time_label.set_text(time_text)
                self.date_label.set_text(date_text)
            if "time" in self.tiles:
                btn, _box, top, bottom = self.tiles["time"]
                head, half = time_leaf(time_text)
                top.set_text(head)
                bottom.set_text(half)
                bottom.set_visible(bool(half))
                btn.set_tooltip_text(f"{time_text}\n{date_text}")
            if "date" in self.tiles and leaf is not None:
                btn, _box, top, bottom = self.tiles["date"]
                top.set_text(leaf[0])
                bottom.set_text(leaf[1])
                btn.set_tooltip_text(date_text)

        def update_tray(self, tray):
            if self.tray_box is None:
                return
            have = {b.key: b for b in self.tray_box.get_children()}
            keys = [k for k, it in tray.items.items() if tray.shown(it)]
            for key, b in have.items():
                if key not in keys:
                    b.destroy()
            for i, key in enumerate(keys):
                b = have.get(key)
                if b is None:
                    b = TrayButton(tray, key)
                    self.tray_box.pack_start(b, False, False, 0)
                    b.show_all()
                b.refresh(tray.items[key])
                self.tray_box.reorder_child(b, i)

        # -- where it is, and the pointer ------------------------------------------------------
        def learn_rect(self):
            if not self.get_mapped():
                return
            rect = layer_rect(hyprq("layers"), self.name, GtkLayerShell.get_namespace(self), os.getpid())
            if rect:
                self.rect = rect
                if self.toolbox is not None:
                    self.engine.note_toolbox(self)

        def toolbox_record(self):
            """TOOLBOX_BUTTON's record for this bar's toolbox button, or None
            before Hyprland has told where the bar is."""
            mon = self.engine.monitor(self.name)
            got = self.toolbox.translate_coordinates(self, 0, 0) if self.toolbox is not None else None
            if mon is None or self.rect is None or not got:
                return None
            a = self.toolbox.get_allocation()
            # The strip the bar keeps from windows (and from the toolbox's
            # anchor edge): the taskbar's strip, a dock that never hides its
            # zone, a hiding dock none. The bar's rectangle is its card's,
            # not the room round it.
            return toolbox_record(os.getpid(), self.name, self.layout, self.position, logical_rect(mon),
                                  self.shelf_rect(), got[:2], (a.width, a.height), self.zone or 0)

        def shelf_rect(self):
            """The card (the taskbar's strip) in layout coordinates: Hyprland's
            rectangle of the surface, less the room round the card."""
            if self.rect is None:
                return None
            fa = self.frame.get_allocation()
            return (self.rect[0] + fa.x, self.rect[1] + fa.y, fa.width, fa.height)

        def hit_rect(self):
            """Where the pointer counts as on the bar: the card, or the whole
            surface while magnified icons stick out of it."""
            if self.fx is not None and self.fx.expanded:
                return self.rect
            return self.shelf_rect()

        def on_allocate(self, _w, alloc):
            fa = self.frame.get_allocation()
            thick = (fa.height if self.position == "bottom" else fa.width)
            if self.layout == "taskbar":
                zone = thick
            elif self.engine.cfg["autohide"] == "never":
                zone = thick + DOCK_MARGIN
            else:
                zone = 0
            if harness:
                zone = 0              # the harness never pushes a window aside
            if zone != self.zone:
                self.zone = zone
                GtkLayerShell.set_exclusive_zone(self, zone)
            self.fit_input()
            if self.edge is not None:
                self.edge.fit(fa)
            self.engine.debounce(f"rect-{self.name}", 200, self.learn_rect)

        def fit_input(self):
            """The pointer goes through the room round the card (it is there
            for a shadow and for icons that grow): the input region is the
            card, or the whole surface while magnified. The harness's takes
            no input at all."""
            win = self.get_window()
            if win is None:
                return
            if harness:
                win.input_shape_combine_region(cairo.Region(), 0, 0)
            elif self.fx is not None and self.fx.expanded:
                ta = self.get_allocation()
                win.input_shape_combine_region(
                    cairo.Region(cairo.RectangleInt(0, 0, max(1, ta.width), max(1, ta.height))), 0, 0)
            else:
                fa = self.frame.get_allocation()
                win.input_shape_combine_region(
                    cairo.Region(cairo.RectangleInt(fa.x, fa.y, max(1, fa.width), max(1, fa.height))), 0, 0)

        def on_shelf_style(self, *_):
            self.style_serial += 1
            self.shelf_cache = None

        def widen_clip(self, widget, _alloc):
            """The card and its items draw outside their allocations while
            the effects move them: their clip is the whole surface."""
            ta = self.get_allocation()
            clip = Gdk.Rectangle()
            clip.x, clip.y, clip.width, clip.height = 0, 0, ta.width, ta.height
            widget.set_clip(clip)

        def draw_frame(self, frame, cr):
            """While the effects move: the card from shelf_picture(), split
            at its middle and pulled apart by the spread icons' reach (the
            gap filled with its middle column, stretched), then its
            children. At rest: GTK's own drawing."""
            fx = self.fx
            fx.t0 = time.perf_counter()
            fx.custom = fx.compute()
            if not fx.custom:
                return False
            got = self.shelf_picture(frame)
            if got is None:
                return False
            pic, ox, oy, full_w, full_h = got
            before, after = (int(round(v)) for v in fx.extents)
            horiz = fx.horizontal()
            half = (full_w if horiz else full_h) // 2
            gap = before + after

            def part(dest, src):
                """One piece: the picture placed at `src`, clipped to `dest`."""
                cr.save()
                cr.rectangle(*dest)
                cr.clip()
                cr.set_source_surface(pic, *src)
                cr.paint()
                cr.restore()
            if horiz:
                part((ox - before, oy, half, full_h), (ox - before, oy))
                part((ox - before + half + gap, oy, full_w - half, full_h), (ox + after, oy))
            else:
                part((ox, oy - before, full_w, half), (ox, oy - before))
                part((ox, oy - before + half + gap, full_w, full_h - half), (ox, oy + after))
            if gap > 0:
                # the middle column (row), stretched over the gap
                cr.save()
                if horiz:
                    cr.rectangle(ox - before + half, oy, gap, full_h)
                    cr.clip()
                    cr.translate(ox - before + half, 0)
                    cr.scale(gap, 1)
                    cr.set_source_surface(pic, -half, oy)
                else:
                    cr.rectangle(ox, oy - before + half, full_w, gap)
                    cr.clip()
                    cr.translate(0, oy - before + half)
                    cr.scale(1, gap)
                    cr.set_source_surface(pic, ox, -half)
                cr.get_source().set_filter(cairo.FILTER_NEAREST)
                cr.paint()
                cr.restore()
            for child in frame.get_children():
                frame.propagate_draw(child, cr)
            return True

        def shelf_picture(self, frame):
            """The card as GTK draws it -- background, border, shadow, from
            the theme's rules -- rendered once into a picture with `pad` px
            round it for the shadow: a blurred box-shadow costs milliseconds
            a frame, the picture a copy. Kept until the card's size or style
            changes. (surface, x, y, w, h) -- where it goes and its size, in
            the card's coordinates -- or None before it is realized."""
            win = self.get_window()
            if win is None:
                return None
            a = frame.get_allocation()
            ctx = frame.get_style_context()
            m = ctx.get_margin(ctx.get_state())
            w, h = a.width - m.left - m.right, a.height - m.top - m.bottom
            pad = SHADOW_PAD + 8
            key = (w, h, m.left, m.top, self.get_scale_factor(), self.style_serial)
            if self.shelf_cache is not None and self.shelf_cache[0] == key:
                return self.shelf_cache[1]
            f = self.get_scale_factor()
            pic = win.create_similar_image_surface(cairo.FORMAT_ARGB32, (w + 2 * pad) * f, (h + 2 * pad) * f, f)
            pcr = cairo.Context(pic)
            Gtk.render_background(ctx, pcr, pad, pad, w, h)
            Gtk.render_frame(ctx, pcr, pad, pad, w, h)
            pic.flush()
            # where it goes in the card's coordinates: its CSS box, less the pad
            got = (pic, m.left - pad, m.top - pad, w + 2 * pad, h + 2 * pad)
            self.shelf_cache = (key, got)
            return got

        def draw_items(self, box, cr):
            """Each item under its transform: grown about its foot (the end
            at the screen's edge), moved along the dock, lifted by a hop;
            the biggest drawn last, on top."""
            fx = self.fx
            if not fx.custom:
                return False
            ba = box.get_allocation()
            for child, (s, shift, lift) in sorted(fx.drawn.items(), key=lambda kv: kv[1][0]):
                if child.get_parent() is not box or not child.get_visible():
                    continue
                a = child.get_allocation()
                x, y = a.x - ba.x, a.y - ba.y
                if self.position == "bottom":
                    ax, ay, dx, dy = x + a.width / 2, y + a.height, shift, -lift
                elif self.position == "left":
                    ax, ay, dx, dy = x, y + a.height / 2, lift, shift
                else:
                    ax, ay, dx, dy = x + a.width, y + a.height / 2, -lift, shift
                cr.save()
                cr.translate(ax + dx, ay + dy)
                cr.scale(s, s)
                cr.translate(-ax, -ay)
                box.propagate_draw(child, cr)
                cr.restore()
            if fx.stats is not None and len(fx.stats["draw_ms"]) < FX_STATS:
                fx.stats["draw_ms"].append(round((time.perf_counter() - fx.t0) * 1000, 3))
            return True

        # -- the dock's own drag (ItemButton: press, motion, release) --------------
        def drag_press(self, btn, event):
            """A press on an app or a tile: maybe the start of a drag
            (drag_motion). False: the press goes on to the button."""
            btn.suppress_click = False
            self.dragging = {"btn": btn, "start": self.along(event), "on": False,
                             "tile": not isinstance(btn, ItemButton)}
            return False

        @staticmethod
        def unsuppress(btn):
            """The click a drag's release brings: True once, to be ignored."""
            was, btn.suppress_click = btn.suppress_click, False
            return was

        def drag_motion(self, btn, event):
            """The button held and moving: past DRAG_START_PX it is a drag --
            the icon swaps places with each one it passes (drag_to)."""
            d = self.dragging
            if not d or d["btn"] is not btn or not event.state & Gdk.ModifierType.BUTTON1_MASK:
                return False
            at = self.along(event)
            if not d["on"]:
                item = getattr(btn, "item", None) or {}
                if abs(at - d["start"]) < DRAG_START_PX or item.get("key") != item.get("group"):
                    return False          # a click so far; or one window's button (never-combine)
                d["on"] = True
                if self.fx is not None:
                    self.fx.release(btn)
                self.engine.close_preview()
                cls(btn, "dragging", True)
            self.drag_to(btn, at)
            return True

        def drag_to(self, btn, at):
            """Put btn where the pointer is: in the place of the app under
            it. A pinned app stays among the pinned; a running one may go
            among them (pinned there when it is let go)."""
            ba = self.items.get_allocation()
            horiz = self.position == "bottom"
            kids = self.items.get_children()
            tiles = {t[0] for k, t in self.tiles.items() if k != "apps"}
            for c in kids:
                if c is btn or not c.get_visible():
                    continue
                if self.dragging and self.dragging["tile"]:
                    if c not in tiles:    # a tile among the tiles
                        continue
                    a = c.get_allocation()
                    start, length = (a.x - ba.x, a.width) if horiz else (a.y - ba.y, a.height)
                    if start <= at < start + length:
                        self.items.reorder_child(btn, kids.index(c))
                        return
                    continue
                if not isinstance(c, ItemButton) or not c.item:
                    continue
                if (btn.item or {}).get("pinned") and not c.item.get("pinned"):
                    continue
                a = c.get_allocation()
                start, length = (a.x - ba.x, a.width) if horiz else (a.y - ba.y, a.height)
                if start <= at < start + length:
                    # c's place: after it coming from the left, before it from
                    # the right (and so across the line, either way)
                    self.items.reorder_child(btn, kids.index(c))
                    return

        def drag_release(self, btn):
            """The drag ends: the order the dock shows now is kept
            (drag_result): the pinned list saved, the running apps' order
            remembered. The release's click does nothing."""
            d, self.dragging = self.dragging, None
            if not d or not d["on"] or d["btn"] is not btn:
                return
            cls(btn, "dragging", False)
            btn.suppress_click = True
            kids = self.items.get_children()
            if d["tile"]:
                where = {t[0]: k for k, t in self.tiles.items() if k != "apps"}
                self.engine.save_tile_order([where[c] for c in kids if c in where])
                return
            line = kids.index(self.sep) if self.sep.get_visible() else None
            seen = [(c.item["group"], c.item.get("app_id"),
                     (kids.index(c) < line) if line is not None else bool(c.item.get("pinned")))
                    for c in kids if isinstance(c, ItemButton) and c.item]
            pinned, order = drag_result(self.engine.pinned(), self.engine.order, seen)
            self.engine.order = order
            if pinned != self.engine.pinned():
                self.engine.save_pinned(pinned)
            else:
                self.engine.render()

        def along(self, event):
            """An event's point along the dock, in the items box's px (the
            event's own window is a button's, or the surface's)."""
            x, y = event.x, event.y
            win, top = event.window, self.get_window()
            while win is not None and win != top:
                dx, dy = win.get_position()
                x, y = x + dx, y + dy
                win = win.get_parent()
            ba = self.items.get_allocation()
            return (x - ba.x) if self.position == "bottom" else (y - ba.y)

        def on_motion(self, _w, event):
            # A press on a magnified icon's grown part (on_band_press) holds
            # the surface's window, not the button's: its drag moves here.
            if self.dragging is not None and event.window == self.get_window() \
                    and self.drag_motion(self.dragging["btn"], event):
                return True
            if self.fx is not None and self.fx.magnify:
                self.fx.point(self.along(event))
            return False

        def band_child(self, event):
            """A click on the surface itself, outside every button: the part
            of a magnified icon that sticks out of the card."""
            if self.fx is None or not self.fx.expanded or event.window != self.get_window():
                return None
            return self.fx.child_at(self.along(event))

        def on_band_press(self, _w, event):
            child = self.band_child(event)
            if isinstance(child, ItemButton) and event.type == Gdk.EventType.BUTTON_PRESS:
                if event.button == 3:
                    self.engine.item_menu(child, event)
                elif event.button == 1:
                    self.drag_press(child, event)     # the grown icon is dragged too
                    self.fx.press(child)
                return True
            if child is not None and event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS \
                    and any(child is t[0] for k, t in self.tiles.items() if k != "apps"):
                self.drag_press(child, event)         # a tile's grown part, likewise
                return True
            return False

        def on_band_release(self, _w, event):
            d = self.dragging
            if event.button == 1 and d is not None:
                if d["on"]:               # a drag that began on a grown icon: no click
                    self.drag_release(d["btn"])
                    if self.fx is not None:
                        self.fx.release(d["btn"])
                    return True
                self.dragging = None      # a band click, not a drag
            child = self.band_child(event)
            if self.fx is not None:
                self.fx.release(child)
            if isinstance(child, ItemButton):
                if event.button == 1:
                    self.engine.click(child.item)
                elif event.button == 2:
                    self.engine.new_window(child.item)
                return True
            if child is not None and child is self.toolbox and event.button == 1:
                spawn(TOOLBOX_SH, "toggle")
                return True
            if child is not None and event.button == 1 and any(child is t[0] for t in self.tiles.values()):
                child.clicked()           # a tile's grown part: its panel, as its own click
                return True
            return False

        def on_enter(self, _w, _event):
            self.engine.cancel(f"leave-{self.name}")
            self.hovered = True
            return False

        def on_leave(self, _w, event):
            if event.detail == Gdk.NotifyType.INFERIOR:
                return False          # onto a button of its own
            if self.fx is not None:
                self.fx.leave()
            self.engine.debounce(f"leave-{self.name}", LEAVE_MS, lambda: self.engine.check_leave(self))
            return False

        def apply_visibility(self):
            """Mapped or not: suppressed (fullscreen, a game) beats all; a
            hidden dock leaves its hot edge."""
            want = not self.suppressed and not self.hidden
            if want and not self.get_visible():
                self.show()
            elif not want and self.get_visible():
                if self.fx is not None:
                    self.fx.reset()
                    self.fit_input()
                self.hide()
            if self.edge is not None:
                edge_on = self.hidden and not self.suppressed
                if edge_on and not self.edge.get_visible():
                    self.edge.show()
                elif not edge_on and self.edge.get_visible():
                    self.edge.hide()

        def close(self):
            # A leave check or a rect lookup still pending is for this window,
            # not for the one that replaces it under the same name.
            if self.fx is not None:
                self.fx.reset()
            self.engine.cancel(f"leave-{self.name}")
            self.engine.cancel(f"rect-{self.name}")
            if self.edge is not None:
                self.edge.destroy()
            self.destroy()

    class Edge(Gtk.Window):
        """A hidden dock's stand-in: a thin, invisible strip at its edge;
        the pointer touching it brings the dock back."""

        def __init__(self, bar):
            super().__init__()
            self.bar = bar
            self.set_name("dock-edge-window")
            layer_window(self, "dock-edge", GtkLayerShell.Layer.TOP, bar.gdk_mon)
            GtkLayerShell.set_anchor(self, edges(bar.position), True)
            GtkLayerShell.set_exclusive_zone(self, 0)
            self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK)
            self.connect("enter-notify-event", lambda *_: (bar.engine.reveal(bar), False)[1])
            self.length = 240
            self.fit(None)

        def fit(self, alloc):
            if alloc is not None:
                self.length = max(120, alloc.width if self.bar.position == "bottom" else alloc.height)
            if self.bar.position == "bottom":
                self.set_size_request(self.length, EDGE_PX)
            else:
                self.set_size_request(EDGE_PX, self.length)

    # -- the window previews -------------------------------------------------------------------
    class Preview(Gtk.Window):
        def __init__(self, engine):
            super().__init__()
            self.engine = engine
            self.button = None
            self.bar = None
            self.cards = {}
            self.set_name("dock-preview-window")
            layer_window(self, "waybar-dock-preview", GtkLayerShell.Layer.OVERLAY, None)
            GtkLayerShell.set_exclusive_zone(self, -1)
            self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.connect("enter-notify-event", self.on_enter)
            self.connect("leave-notify-event", self.on_leave)
            self.connect("size-allocate", lambda *_: self.place())
            self.box = Gtk.Box(spacing=0)
            self.box.set_name("dock-preview")
            self.add(self.box)

        def on_enter(self, *_):
            self.engine.cancel("preview-close")
            return False

        def on_leave(self, _w, event):
            if event.detail != Gdk.NotifyType.INFERIOR:
                self.engine.debounce("preview-close", PREVIEW_CLOSE_MS, self.engine.check_preview)
            return False

        def open_for(self, button):
            item = button.item or {}
            windows = (item.get("windows") or [])[:PREVIEW_MAX]
            if not windows:
                self.close()
                return
            # A layer surface changes screen only while unmapped: hidden and
            # shown again for another screen's bar, only moved (its margins)
            # for another button on the same one -- so going along the dock
            # does not pop the card in again for every app.
            moved = self.bar is not None and button.bar.gdk_mon is not self.bar.gdk_mon
            self.button, self.bar = button, button.bar
            sideways = button.bar.position in ("left", "right")
            self.box.set_orientation(Gtk.Orientation.VERTICAL if sideways else Gtk.Orientation.HORIZONTAL)
            for child in self.box.get_children():
                child.destroy()
            self.cards = {}
            for w in windows:
                self.box.pack_start(self.card(w, item), False, False, 0)
            self.box.show_all()
            if moved and self.get_visible():
                self.hide()             # a layer surface changes screen only while unmapped
            GtkLayerShell.set_monitor(self, button.bar.gdk_mon)
            self.engine.held.add("preview")
            self.place()
            self.show()
            for w in windows:
                self.engine.thumb(w, lambda pb, a=w["address"]: self.set_thumb(a, pb))

        def card(self, w, item):
            card = Gtk.Button()
            card.set_relief(Gtk.ReliefStyle.NONE)
            card.set_can_focus(False)
            cls(card, "dock-card")
            cls(card, "focused", w["address"] == self.engine.active)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            top = Gtk.Box(spacing=0)
            from gi.repository import Pango
            title = Gtk.Label(label=w["title"] or item.get("name") or "", xalign=0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_max_width_chars(26)
            title.set_width_chars(1)
            title.set_size_request(THUMB_W - 30, -1)
            cls(title, "dock-card-title")
            close = Gtk.Button(label=CLOSE_GLYPH)
            close.set_relief(Gtk.ReliefStyle.NONE)
            close.set_can_focus(False)
            cls(close, "dock-card-close")
            close.set_tooltip_text("Close this window")
            close.connect("clicked", lambda *_: (spawn(*close_argv(w["address"]) or [None]), self.close()))
            close.connect("enter-notify-event", self.on_enter)
            top.pack_start(title, True, True, 0)
            top.pack_end(close, False, False, 0)
            col.pack_start(top, False, False, 0)
            thumb = Gtk.Image()
            cls(thumb, "dock-thumb")
            thumb.set_no_show_all(True)
            col.pack_start(thumb, False, False, 0)
            card.add(col)
            card.connect("clicked", lambda *_: (spawn(*focus_argv(w["address"]) or [None]), self.close()))
            card.connect("enter-notify-event", self.on_enter)
            self.cards[w["address"]] = thumb
            cached = self.engine.thumbs.get(w.get("stable_id"))
            if cached and cached[1] is not None:
                thumb.set_from_pixbuf(cached[1])
                thumb.show()
            return card

        def set_thumb(self, address, pb):
            thumb = self.cards.get(address)
            if thumb is not None and pb is not None and self.get_visible():
                thumb.set_from_pixbuf(pb)
                thumb.show()

        def button_rect(self):
            """(button rect, monitor rect) in layout coordinates, or None."""
            if self.button is None or self.bar is None:
                return None
            bar, mon = self.bar, self.engine.monitor(self.bar.name)
            if mon is None:
                return None
            mrect = logical_rect(mon)
            origin = bar.rect
            if origin is None:      # never measured: guess from the edge it is anchored to
                a = bar.get_allocation()
                if bar.position == "bottom":
                    origin = (mrect[0] + (mrect[2] - a.width) // 2, mrect[1] + mrect[3] - a.height, a.width, a.height)
                elif bar.position == "left":
                    origin = (mrect[0], mrect[1] + (mrect[3] - a.height) // 2, a.width, a.height)
                else:
                    origin = (mrect[0] + mrect[2] - a.width, mrect[1] + (mrect[3] - a.height) // 2, a.width, a.height)
            got = self.button.translate_coordinates(bar, 0, 0)
            ba = self.button.get_allocation()
            bx, by = (got[0], got[1]) if got else (0, 0)
            rect = (origin[0] + bx, origin[1] + by, ba.width, ba.height)
            if bar.fx is not None and bar.fx.magnify:
                # over the magnified icon, not over the button it grew from
                rise = int(ba.height * (MAGNIFY_PEAK - 1)) if bar.position == "bottom" else int(
                    ba.width * (MAGNIFY_PEAK - 1))
                x, y, w, h = rect
                rect = {"bottom": (x, y - rise, w, h + rise), "left": (x, y, w + rise, h),
                        "right": (x - rise, y, w + rise, h)}[bar.position]
            return rect, mrect

        def place(self):
            got = self.button_rect()
            if got is None:
                return
            button, mrect = got
            _min, nat = self.get_preferred_size()
            anchors, margins = preview_place(self.bar.position, button, mrect, (nat.width, nat.height))
            for name in ("top", "bottom", "left", "right"):
                GtkLayerShell.set_anchor(self, edges(name), name in anchors)
                GtkLayerShell.set_margin(self, edges(name), margins.get(name, 0))

        def close(self):
            self.engine.cancel("preview-open")
            self.engine.cancel("preview-close")
            self.button = None
            self.engine.held.discard("preview")
            if self.get_visible():
                self.hide()
            self.engine.autohide_all()

    # -- the tray: a StatusNotifierHost --------------------------------------------------------
    class TrayButton(Gtk.Button):
        def __init__(self, tray, key):
            super().__init__()
            self.tray, self.key = tray, key
            self.icon_key = None
            self.set_relief(Gtk.ReliefStyle.NONE)
            self.set_can_focus(False)
            cls(self, "dock-tray-item")
            self.image = Gtk.Image()
            self.add(self.image)
            self.connect("button-press-event", self.on_press)
            self.connect("scroll-event", self.on_scroll)
            self.add_events(Gdk.EventMask.SCROLL_MASK)

        def refresh(self, entry):
            props = entry["props"]
            attention = props.get("Status") == "NeedsAttention"
            cls(self, "attention", attention)
            name = (props.get("AttentionIconName") if attention else "") or props.get("IconName") or ""
            pixmaps = (props.get("AttentionIconPixmap") if attention else None) or props.get("IconPixmap")
            path = props.get("IconThemePath") or ""
            self.set_tooltip_text(tooltip_text(props) or None)
            # An app that rewrites its tooltip every second (a download's
            # speed) must not cost a new picture each time: the icon is
            # loaded again only when what it is made of changed.
            key = (name, path, tuple((len(p) > 2 and hash(bytes(p[2]))) for p in pixmaps or []))
            if key == self.icon_key:
                return
            self.icon_key = key
            theme = Gtk.IconTheme.get_default()
            if path and path not in self.tray.paths:
                self.tray.paths.add(path)
                theme.append_search_path(path)
            shown = False
            if name and (name.startswith("/") and os.path.exists(name)):
                try:
                    self.image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(name, TRAY_ICON, TRAY_ICON))
                    shown = True
                except GLib.Error:
                    pass
            elif name and theme.has_icon(name):
                self.image.set_from_icon_name(name, Gtk.IconSize.MENU)
                self.image.set_pixel_size(TRAY_ICON)
                shown = True
            if not shown:
                best = best_pixmap(pixmaps, TRAY_ICON)
                if best is not None:
                    w, h, data = best
                    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(argb_to_rgba(data[:w * h * 4])),
                                                         GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
                    if w != TRAY_ICON:
                        pb = pb.scale_simple(TRAY_ICON, max(1, h * TRAY_ICON // w), GdkPixbuf.InterpType.BILINEAR)
                    self.image.set_from_pixbuf(pb)
                    shown = True
            if not shown:
                self.image.set_from_icon_name("application-x-executable", Gtk.IconSize.MENU)
                self.image.set_pixel_size(TRAY_ICON)

        def on_press(self, _w, event):
            if event.type != Gdk.EventType.BUTTON_PRESS:
                return True
            entry = self.tray.items.get(self.key)
            if entry is None:
                return True
            if event.button == 1 and not entry["props"].get("ItemIsMenu"):
                self.tray.call(entry, "Activate", int(event.x_root), int(event.y_root),
                               fallback=lambda: self.tray.menu(entry, self, event.copy()))
            elif event.button == 2:
                self.tray.call(entry, "SecondaryActivate", int(event.x_root), int(event.y_root))
            else:
                self.tray.menu(entry, self, event.copy())
            return True

        def on_scroll(self, _w, event):
            entry = self.tray.items.get(self.key)
            if entry is None:
                return True
            _ok, _dx, dy = event.get_scroll_deltas()
            if event.direction == Gdk.ScrollDirection.UP:
                dy = -1
            elif event.direction == Gdk.ScrollDirection.DOWN:
                dy = 1
            if dy:
                self.tray.scroll(entry, int(-120 if dy < 0 else 120))
            return True

    def sni_props(variant):
        """GetAll's a{sv} -> a dict, the icon pictures (a(iiay)) read as
        bytes in one go: GLib's unpack() makes a Python object of every
        byte, which for an app that rewrites its tooltip every second (a
        download's speed) was a steady few % of a core. The tooltip's own
        picture is left out (tooltip_text reads its words only)."""
        out = {}

        def pixmaps(v):
            return [(p.get_child_value(0).get_int32(), p.get_child_value(1).get_int32(),
                     p.get_child_value(2).get_data_as_bytes().get_data())
                    for p in (v.get_child_value(j) for j in range(v.n_children()))]
        for i in range(variant.n_children()):
            entry = variant.get_child_value(i)
            key = entry.get_child_value(0).get_string()
            val = entry.get_child_value(1).get_variant()
            kind = val.get_type_string()
            if kind == "a(iiay)":
                out[key] = pixmaps(val)
            elif kind == "(sa(iiay)ss)":
                out[key] = (val.get_child_value(0).get_string(), [],
                            val.get_child_value(2).get_string(), val.get_child_value(3).get_string())
            else:
                out[key] = val.unpack()
        return out

    class Tray:
        def __init__(self, engine):
            self.engine = engine
            self.items = {}          # watcher's string -> {bus, path, props, sub}
            self.paths = set()
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.host = f"org.kde.StatusNotifierHost-{os.getpid()}-dock"
            self.own = Gio.bus_own_name_on_connection(self.bus, self.host, Gio.BusNameOwnerFlags.NONE, None, None)
            self.subs = [
                self.bus.signal_subscribe(None, WATCHER, "StatusNotifierItemRegistered", WATCHER_PATH, None,
                                          Gio.DBusSignalFlags.NONE, self.on_registered),
                self.bus.signal_subscribe(None, WATCHER, "StatusNotifierItemUnregistered", WATCHER_PATH, None,
                                          Gio.DBusSignalFlags.NONE, self.on_unregistered)]
            self.watch = Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                                          self.on_watcher, self.on_watcher_gone)

        def stop(self):
            for key in list(self.items):
                self.drop(key)
            for s in self.subs:
                self.bus.signal_unsubscribe(s)
            Gio.bus_unwatch_name(self.watch)
            Gio.bus_unown_name(self.own)

        @staticmethod
        def shown(entry):
            return entry["props"] and entry["props"].get("Status") != "Passive"

        def changed(self):
            for bar in self.engine.bars.values():
                bar.update_tray(self)

        def on_watcher(self, _conn, _name, _owner):
            self.bus.call(WATCHER, WATCHER_PATH, WATCHER, "RegisterStatusNotifierHost",
                          GLib.Variant("(s)", (self.host,)), None, Gio.DBusCallFlags.NONE, 3000, None,
                          lambda c, r: self.finish(c, r))
            self.bus.call(WATCHER, WATCHER_PATH, "org.freedesktop.DBus.Properties", "Get",
                          GLib.Variant("(ss)", (WATCHER, "RegisteredStatusNotifierItems")),
                          GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 3000, None, self.on_list)

        def on_watcher_gone(self, _conn, _name):
            for key in list(self.items):
                self.drop(key)
            self.changed()

        def finish(self, conn, res):
            try:
                return conn.call_finish(res)
            except GLib.Error as exc:
                print(f"dock: tray: {exc.message}", file=sys.stderr, flush=True)
                return None

        def on_list(self, conn, res):
            got = self.finish(conn, res)
            for spec in (got.unpack()[0] if got else []) or []:
                self.add(spec)

        def on_registered(self, _c, sender, _p, _i, _s, params):
            self.add(params.unpack()[0])

        def on_unregistered(self, _c, _sender, _p, _i, _s, params):
            spec = params.unpack()[0]
            if spec in self.items:
                self.drop(spec)
                self.changed()

        def add(self, spec):
            if spec in self.items:
                return
            bus, path = parse_item(spec)
            if not bus:
                return
            entry = {"bus": bus, "path": path, "props": {}, "key": spec}
            entry["sub"] = self.bus.signal_subscribe(bus, SNI, None, path, None, Gio.DBusSignalFlags.NONE,
                                                     lambda *_a, k=spec: self.engine.debounce(
                                                         f"tray-{k}", 100, lambda: self.fetch(k)))
            self.items[spec] = entry
            self.fetch(spec)

        def drop(self, spec):
            entry = self.items.pop(spec, None)
            if entry and entry.get("sub"):
                self.bus.signal_unsubscribe(entry["sub"])

        def fetch(self, spec):
            entry = self.items.get(spec)
            if entry is None:
                return

            def done(conn, res):
                got = self.finish(conn, res)
                if got is None or spec not in self.items:
                    return
                props = sni_props(got.get_child_value(0))
                if props == self.items[spec]["props"]:
                    return            # a signal that changed nothing we show: no redraw
                self.items[spec]["props"] = props
                self.changed()
            self.bus.call(entry["bus"], entry["path"], "org.freedesktop.DBus.Properties", "GetAll",
                          GLib.Variant("(s)", (SNI,)), GLib.VariantType("(a{sv})"),
                          Gio.DBusCallFlags.NONE, 3000, None, done)

        def call(self, entry, method, x, y, fallback=None):
            def done(conn, res):
                try:
                    conn.call_finish(res)
                except GLib.Error:
                    if fallback:
                        fallback()
            self.bus.call(entry["bus"], entry["path"], SNI, method, GLib.Variant("(ii)", (x, y)), None,
                          Gio.DBusCallFlags.NONE, 3000, None, done)

        def scroll(self, entry, delta):
            self.bus.call(entry["bus"], entry["path"], SNI, "Scroll", GLib.Variant("(is)", (delta, "vertical")),
                          None, Gio.DBusCallFlags.NONE, 3000, None, lambda c, r: self.finish(c, r))

        def menu(self, entry, button, event):
            path = entry["props"].get("Menu")
            if not path or path == "/":
                self.call(entry, "ContextMenu", int(event.x_root), int(event.y_root))
                return
            bus = entry["bus"]
            # AboutToShow first (some apps fill the menu then); its answer
            # does not matter, the layout comes after it either way.
            self.bus.call(bus, path, DBUSMENU, "AboutToShow", GLib.Variant("(i)", (0,)), None,
                          Gio.DBusCallFlags.NONE, 1000, None, lambda c, r: (self.finish(c, r), self.layout(
                              bus, path, button, event)))

        def layout(self, bus, path, button, event):
            def done(conn, res):
                got = self.finish(conn, res)
                tree = menu_tree(got.unpack()[1]) if got else None
                if not tree or not tree["children"]:
                    return
                menu = self.build(tree, bus, path)
                self.engine.popup(menu, button, event)
            self.bus.call(bus, path, DBUSMENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
                          GLib.VariantType("(u(ia{sv}av))"), Gio.DBusCallFlags.NONE, 3000, None, done)

        def build(self, node, bus, path):
            menu = Gtk.Menu()
            for child in node["children"]:
                if not child["visible"]:
                    continue
                if child["separator"]:
                    menu.append(Gtk.SeparatorMenuItem())
                    continue
                if child["toggle"]:
                    item = Gtk.CheckMenuItem.new_with_mnemonic(child["label"])
                    item.set_draw_as_radio(child["toggle"] == "radio")
                    item.set_active(child["state"])
                else:
                    item = Gtk.MenuItem.new_with_mnemonic(child["label"])
                item.set_sensitive(child["enabled"])
                if child["children"]:
                    item.set_submenu(self.build(child, bus, path))
                else:
                    item.connect("activate", lambda _i, i=child["id"]: self.clicked(bus, path, i))
                menu.append(item)
            menu.show_all()
            return menu

        def clicked(self, bus, path, ident):
            self.bus.call(bus, path, DBUSMENU, "Event",
                          GLib.Variant("(isvu)", (ident, "clicked", GLib.Variant("i", 0), int(time.time()))),
                          None, Gio.DBusCallFlags.NONE, 3000, None, lambda c, r: self.finish(c, r))

    # -- the engine: one for every screen ------------------------------------------------------
    class Engine:
        def __init__(self):
            self.cfg = cfg
            self.bars = {}
            self.ids = {}
            self.clients, self.monitors, self.workspaces = [], [], []
            self.active = None
            self.urgent = set()
            self.order = []
            self.unread = []              # notifications.py unread: the apps' badges
            self.submap = ""              # the key mode now (DOCK TILES' submap tile)
            self.language = ("", "")      # the language tile's (code, input method)
            self.launching = {}       # app id -> monotonic deadline
            self.held = set()         # a menu or the preview is open: the dock stays
            self.thumbs = {}          # stableId -> (monotonic, pixbuf or None)
            self.thumb_busy = set()
            self.events, self.events_buf = None, b""
            self.env_cache = {}
            self.game = False
            self.dirty_game = True
            self.tray = None
            self.status_text = {}     # STATUS_KEYS -> (markup, tooltip), the latest
            self.status_procs = {}    # "network" / "sound" -> its watcher (Gio.Subprocess)
            self.preview = Preview(self)
            self.keep = []            # Gio monitors (kept, or they are collected)
            self.toolbox_written = None   # the TOOLBOX_BUTTON record on disk
            self.toolbox_refit_due = True  # a new main bar: refit the toolbox once it is placed
            self.theme = self.read_theme()
            gtk_settings = Gtk.Settings.get_default()
            self.motion = motion_ok(gtk_settings.props.gtk_enable_animations)
            gtk_settings.connect("notify::gtk-enable-animations", lambda *_: self.on_motion_pref())
            self.load_apps()

        # the theme's keys and reduce motion (EFFECTS in the module docstring)
        @staticmethod
        def read_theme():
            """bar.conf (theme.py writes it): logo=, start=, magnify=."""
            if barclock is None:
                return {}
            try:
                return barclock.bar_style(os.path.join(GEN_DIR, "bar.conf"))
            except Exception:         # noqa: BLE001 - an unreadable file: the plain look
                return {}

        def magnify(self):
            return magnify_on(self.cfg["magnify"], self.theme.get("magnify"), self.cfg["layout"]) and self.motion

        def on_motion_pref(self):
            """Reduce motion switched: every bar again, with or without its
            effects (and the room they need)."""
            now = motion_ok(Gtk.Settings.get_default().props.gtk_enable_animations)
            if now != self.motion:
                self.motion = now
                self.rebuild()

        # the toolbox button's whereabouts (THE TOOLBOX in the module docstring)
        def note_toolbox(self, bar):
            """Write TOOLBOX_BUTTON when the button moved; the first time
            after a (re)build, `toolbox.sh refit` too, which also redraws the
            top bar's sliders pill (hidden now)."""
            if not self.live(bar) or not bar.main or harness:
                return                # the harness's toolbox button is only a picture
            rec = bar.toolbox_record()
            if rec is None:
                return
            if rec != self.toolbox_written:
                try:
                    tmp = f"{TOOLBOX_BUTTON}.{os.getpid()}.tmp"
                    with open(tmp, "w") as fh:
                        json.dump(rec, fh)
                    os.replace(tmp, TOOLBOX_BUTTON)
                    self.toolbox_written = rec
                except OSError as exc:
                    print(f"dock: {TOOLBOX_BUTTON}: {exc}", file=sys.stderr, flush=True)
                    return
            if self.toolbox_refit_due:
                self.toolbox_refit_due = False
                spawn(TOOLBOX_SH, "refit")

        def forget_toolbox(self):
            """On the way out: the button is gone, so is its file (only ours),
            and the top bar's pill comes back."""
            if harness:
                return
            try:
                with open(TOOLBOX_BUTTON) as fh:
                    mine = json.load(fh).get("pid") == os.getpid()
            except (OSError, ValueError, AttributeError):
                mine = False
            if mine:
                try:
                    os.unlink(TOOLBOX_BUTTON)
                except OSError:
                    pass
            poke_toolbox_pill()

        # timing
        def debounce(self, name, ms, fn):
            self.cancel(name)

            def fire():
                self.ids[name] = None
                fn()
                return False
            self.ids[name] = GLib.timeout_add(ms, fire)

        def cancel(self, name):
            if self.ids.get(name):
                GLib.source_remove(self.ids[name])
                self.ids[name] = None

        # apps
        def load_apps(self):
            notify_source._APPS = (None, 0.0)
            app_infos.clear()
            apps = notify_source.installed_apps()
            self.index = app_index(apps)
            self.by_id = {a["id"]: a for a in apps}

        def pinned(self):
            return list(self.cfg["pinned"] or [])

        def tile_click(self, kind, button, widget):
            """A dock tile's click (DOCK TILES); True: done with the event."""
            left = {"apps": lambda: self.open_start(widget),
                    "time": lambda: spawn(sys.executable, PANEL, "toggle", "clock"),
                    "date": lambda: spawn(sys.executable, PANEL, "toggle", "calendar"),
                    "weather": lambda: spawn(sys.executable, PANEL, "toggle", "weather"),
                    "workspaces": lambda: spawn(*OVERVIEW_ARGV),
                    "submap": lambda: spawn(*SUBMAP_RESET),
                    "media": lambda: spawn(PLAYER_PY, "toggle"),
                    "notifications": lambda: spawn(sys.executable, PANEL, "toggle", "notifications"),
                    "battery": lambda: spawn(sys.executable, SETTINGS_APP, "power"),
                    "language": lambda: spawn(sys.executable, PANEL, "toggle", "language"),
                    "network": lambda: spawn(sys.executable, PANEL, "toggle", "network"),
                    "sound": lambda: spawn(sys.executable, PANEL, "toggle", "audio")}
            other = {("weather", 3): lambda: spawn(WTTR_PY, "open"),
                     ("media", 3): lambda: spawn(PLAYER_PY, "next"),
                     ("media", 2): lambda: spawn(sys.executable, PANEL, "toggle", "flyout"),
                     ("notifications", 3): lambda: spawn(NOTIFICATIONS_PY, "dnd"),
                     ("language", 3): lambda: spawn("hyprctl", "switchxkblayout", "all", "next"),
                     ("network", 3): lambda: spawn("kitty", "-e", "nmtui"),
                     ("sound", 3): lambda: spawn("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"),
                     ("sound", 2): lambda: spawn("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle")}
            run = left.get(kind) if button == 1 else other.get((kind, button))
            if run is None:
                return False
            run()
            return True

        def tile_scroll(self, kind, event):
            """The wheel on a tile: the workspaces tile goes to the next or
            previous one, the media tile to another player."""
            if kind == "sound":
                return self.status_scroll("sound", event)
            if kind not in ("workspaces", "media"):
                return False
            if event.direction == Gdk.ScrollDirection.SMOOTH:
                _ok, _dx, dy = event.get_scroll_deltas()
                if abs(dy) < 0.5:
                    return True
                down = dy > 0
            elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
                down = event.direction == Gdk.ScrollDirection.DOWN
            else:
                return False
            if kind == "workspaces":
                spawn("hyprctl", "eval", f'hl.dispatch(hl.dsp.focus({{ workspace = "{"e+1" if down else "e-1"}" }}))')
            else:
                spawn(PLAYER_PY, "cycle", "next" if down else "prev")
            return True

        def ws_now(self, bar_name):
            """The workspaces tile's (number, "of N") for that bar."""
            return workspace_leaf(workspace_buttons(self.monitors, bar_name if self.cfg["monitors"] == "all"
                                                    else None), self.workspaces)

        def fetch_language(self, again=True):
            """The language tile's (code, input method): the main keyboard's
            layout (hyprctl devices, getoption input:kb_layout) and fcitx5's
            input method; again: every LANGUAGE_S while the tile is up
            (fcitx5 sends no event), Hyprland's activelayout at once."""
            if again:
                self.ids["language"] = None
            if "language" not in dock_tiles(self.cfg):
                return False
            got = {}

            def finish():
                codes = [c.strip() for c in str(got.get("layouts") or "").split(",") if c.strip()]
                leaf_ = language_leaf(codes, got.get("index", 0), got.get("im", ""))
                if leaf_ != self.language:
                    self.language = leaf_
                    for bar in self.bars.values():
                        bar.set_language(leaf_)

            def on_im(out):
                got["im"] = out.strip()
                finish()

            def on_option(out):
                try:
                    got["layouts"] = json.loads(out).get("str", "")
                except (ValueError, AttributeError):
                    got["layouts"] = ""
                self.run_text(["fcitx5-remote", "-n"], on_im)

            def on_devices(out):
                try:
                    kbs = json.loads(out).get("keyboards") or []
                except (ValueError, AttributeError):
                    kbs = []
                main = next((k for k in kbs if k.get("main")), kbs[0] if kbs else {})
                got["index"] = main.get("active_layout_index", 0)
                self.run_text(["hyprctl", "getoption", "input:kb_layout", "-j"], on_option)
            self.run_text(["hyprctl", "devices", "-j"], on_devices)
            if again:
                self.ids["language"] = GLib.timeout_add_seconds(LANGUAGE_S, self.fetch_language)
            return False

        def badges_wanted(self):
            return bool(self.cfg["enabled"]) and self.cfg["layout"] == "dock" and bool(self.cfg["notifications"])

        def badge_for(self, item):
            return badge_count(item, self.unread) if self.badges_wanted() else 0

        def fetch_badges(self):
            """notifications.py unread, every NOTIFY_S and on SIGUSR2
            (poll_now): the apps' badges."""
            self.ids["badges"] = None
            if not self.badges_wanted():
                if self.unread:
                    self.unread = []
                    self.render()
                return False

            def done(out):
                try:
                    got = json.loads(out.strip().splitlines()[-1]) if out.strip() else []
                except ValueError:
                    return
                if isinstance(got, list) and got != self.unread:
                    self.unread = [u for u in got if isinstance(u, list) and len(u) == 2]
                    self.render()
            self.run_text([NOTIFICATIONS_PY, "unread"], done)
            self.ids["badges"] = GLib.timeout_add_seconds(NOTIFY_S, self.fetch_badges)
            return False

        def open_files(self, item, uris):
            """Files dropped on an app's icon: open them with it."""
            argv = open_with_argv(item.get("app_id"), uris)
            if argv:
                spawn(*argv)

        def save_tile_order(self, order):
            """The dock's tiles as dragged (tile_order); nothing to redraw,
            they stand there already."""
            cur = read_settings()
            cur["tile_order"] = clean_tile_order(order)
            write_settings(cur)
            self.cfg = cur

        def save_pinned(self, pinned):
            cur = read_settings()
            cur["pinned"] = clean_pinned(pinned)
            write_settings(cur)
            self.cfg = cur
            self.render()

        def seed(self):
            def work():
                found = seed_pinned([default_app(r) for r in SEED_ROLES])
                GLib.idle_add(lambda: (self.save_pinned(found) if read_settings()["pinned"] is None else None,
                                       False)[1])
            threading.Thread(target=work, daemon=True).start()

        # screens
        def monitor(self, name):
            return next((m for m in self.monitors if m.get("name") == name), None)

        def place(self):
            """One bar on the main screen, or one on each: made, kept or
            closed to match the screens there are now."""
            mons = hyprq("monitors")
            if isinstance(mons, list):
                self.monitors = mons
            main = screens.primary(mons=self.monitors) or (self.monitors[0]["name"] if self.monitors else "")
            if not any(m.get("name") == main for m in self.monitors) and self.monitors:
                main = self.monitors[0]["name"]
            wanted = [m["name"] for m in self.monitors] if self.cfg["monitors"] == "all" else [main]
            if harness:
                wanted = [harness.get("monitor") or main]
                main = wanted[0]
            display = Gdk.Display.get_default()
            gdk = {}
            for i in range(display.get_n_monitors()):
                g = display.get_monitor(i)
                geo = g.get_geometry()
                for m in self.monitors:
                    if (m.get("x"), m.get("y")) == (geo.x, geo.y):
                        gdk[m["name"]] = g
            for name in list(self.bars):
                bar = self.bars[name]
                if name not in wanted or gdk.get(name) is not bar.gdk_mon or bar.main != (name == main):
                    self.bars.pop(name).close()
            for name in wanted:
                if name not in self.bars and name in gdk:
                    bar = self.bars[name] = Bar(self, name, gdk[name], name == main)
                    if bar.main:
                        self.toolbox_refit_due = True
                    if self.tray is not None:
                        bar.update_tray(self.tray)
            self.tick_clock(reschedule=False)
            self.refresh()

        def rebuild(self):
            self.preview.close()
            for name in list(self.bars):
                self.bars.pop(name).close()
            want_tray = self.cfg["layout"] == "taskbar" and self.cfg["tray"]
            if want_tray and self.tray is None:
                try:
                    self.tray = Tray(self)
                except GLib.Error as exc:
                    print(f"dock: no tray ({exc.message})", file=sys.stderr, flush=True)
            elif not want_tray and self.tray is not None:
                self.tray.stop()
                self.tray = None
            self.status_sources()
            self.place()

        # Hyprland
        def connect_events(self):
            self.ids["reconnect"] = None
            if harness:               # its windows are the harness file's, and still
                self.refresh()
                return False
            folder = desk_common.hypr_socket_dir()
            try:
                if not folder:
                    raise OSError("no Hyprland instance")
                import hyprbus
                s = hyprbus.connect(DOCK_EVENTS, direct=os.path.join(folder, ".socket2.sock"))
            except OSError:
                self.ids["reconnect"] = GLib.timeout_add_seconds(RECONNECT_S, self.connect_events)
                return False
            self.events, self.events_buf = s, b""
            GLib.io_add_watch(s.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_hypr)
            self.dirty_game = True
            self.refresh()
            return False

        def titles_matter(self):
            return (self.cfg["layout"] == "taskbar" and self.cfg["labels"]) or self.preview.get_visible()

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
            got = read_events(lines)
            if got["layout"]:
                self.debounce("layout", REFRESH_MS, lambda: self.fetch_language(again=False))
            if got["submap"] is not None and got["submap"] != self.submap:
                self.submap = got["submap"]
                for bar in self.bars.values():
                    bar.set_submap(self.submap)
            for op, addr in got["ops"]:
                if op == "active":
                    self.active = addr
                    self.urgent.discard(addr)
                elif addr and addr != self.active:
                    self.urgent.add(addr)
            if got["game"]:
                self.dirty_game = True
            if got["place"]:
                self.debounce("place", PLACE_MS, self.place)
            if got["now"]:
                self.debounce("refresh", REFRESH_MS, self.refresh)
            elif got["titles"] and self.titles_matter() and not self.ids.get("refresh"):
                self.debounce("refresh", TITLE_MS, self.refresh)
            return True

        def refresh(self):
            if harness:
                self.harness_refresh()
                return
            clients, monitors, workspaces = hyprq("clients"), hyprq("monitors"), hyprq("workspaces")
            if isinstance(clients, list):
                self.clients = live_clients(clients)
                addrs = {c["address"] for c in self.clients}
                self.urgent &= addrs
            if isinstance(monitors, list):
                self.monitors = monitors
            if isinstance(workspaces, list):
                self.workspaces = workspaces
            if self.dirty_game and isinstance(clients, list):
                self.dirty_game = False
                pids = {c.get("pid") for c in clients}
                self.env_cache = {p: e for p, e in self.env_cache.items() if p in pids}

                def env_of(pid):
                    if pid not in self.env_cache:
                        self.env_cache[pid] = island.read_environ(pid)
                    return self.env_cache[pid]
                self.game = island.game_running(clients, env_of)
            for bar in self.bars.values():
                bar.suppressed = self.game or island.monitor_hidden(self.monitors, self.workspaces, bar.name)
            self.order = update_order(self.order, self.clients, self.index)
            self.render()
            self.autohide_all()
            if self.preview.get_visible() and self.preview.button is not None:
                btn = self.preview.button
                if btn.get_parent() is None or not btn.item or not btn.item["windows"]:
                    self.preview.close()

        def harness_refresh(self):
            """The harness's made-up windows (HARNESS in the module docstring):
            no Hyprland read but the screens, nothing hidden."""
            mons = hyprq("monitors")
            if isinstance(mons, list):
                self.monitors = mons
            self.clients = live_clients(harness.get("clients"))
            self.active = harness.get("active")
            self.urgent = set(harness.get("urgent") or [])
            for app_id in harness.get("launching") or []:
                self.launching.setdefault(app_id, time.monotonic() + LAUNCH_S * 100)
            for bar in self.bars.values():
                bar.suppressed = False
            self.order = update_order(self.order, self.clients, self.index)
            self.render()
            self.autohide_all()

        def render(self):
            now = time.monotonic()
            self.launching = {k: t for k, t in self.launching.items() if t > now}
            for name, bar in self.bars.items():
                mon = self.monitor(name)
                mon_id = mon.get("id") if (mon and self.cfg["monitors"] == "all") else None
                combine = self.cfg["combine"] or bar.layout == "dock"
                bar.update(build_items(self.cfg["pinned"], self.clients, self.index, self.by_id, self.order,
                                       monitor_id=mon_id, combine=combine, active=self.active,
                                       urgent=self.urgent, launching=self.launching))
                bar.update_workspaces(workspace_buttons(
                    self.monitors, name if self.cfg["monitors"] == "all" else None))
                bar.update_ws_tile(self.ws_now(name))

        # autohide
        def autohide_all(self):
            for bar in self.bars.values():
                self.autohide(bar)

        def autohide(self, bar):
            if bar.layout != "dock":
                bar.hidden = False
            else:
                mon = self.monitor(bar.name)
                over = False
                if self.cfg["autohide"] == "overlap" and mon is not None:
                    over = overlapped(bar.shelf_rect(), self.clients, visible_workspaces(mon))
                bar.hidden = should_hide(self.cfg["autohide"], bar.hovered, bool(self.held), over)
            bar.apply_visibility()

        def live(self, bar):
            """Still the bar on its screen (not one closed and replaced)."""
            return self.bars.get(bar.name) is bar

        def reveal(self, bar):
            if not self.live(bar):
                return
            bar.hovered = True
            bar.hidden = False
            bar.apply_visibility()
            # The pointer may never enter the dock (it touched the edge and
            # went away): look again a moment later, by hand.
            self.debounce(f"leave-{bar.name}", LEAVE_MS * 3, lambda: self.check_leave(bar))

        def pointer(self):
            pos = hyprq("cursorpos")
            if isinstance(pos, dict) and "x" in pos:
                return (pos["x"], pos["y"])
            return None

        def check_leave(self, bar):
            if not self.live(bar):
                return
            if bar.get_mapped():
                bar.learn_rect()
            if inside(self.pointer(), toward_edge(bar.hit_rect(), bar.position, DOCK_MARGIN + EDGE_PX)):
                return              # still on it: a leave into a child, or a slip
            bar.hovered = False
            self.autohide(bar)

        # hover previews
        def hover(self, button):
            self.cancel("preview-close")
            if button.bar.fx is not None:
                button.bar.fx.hover(button, True)
            button.bar.hovered = True
            self.cancel(f"leave-{button.bar.name}")
            if not self.cfg["previews"] or not (button.item or {}).get("windows"):
                if self.preview.get_visible():
                    self.debounce("preview-close", PREVIEW_CLOSE_MS, self.check_preview)
                return
            if self.preview.get_visible():
                self.preview.open_for(button)
            else:
                self.debounce("preview-open", PREVIEW_OPEN_MS, lambda: self.preview.open_for(button)
                              if button.get_parent() is not None else None)

        def unhover(self, button):
            if button.bar.fx is not None:
                button.bar.fx.hover(button, False)
            self.cancel("preview-open")
            if self.preview.get_visible():
                self.debounce("preview-close", PREVIEW_CLOSE_MS, self.check_preview)

        def check_preview(self):
            """Close the preview unless the pointer is, by Hyprland's word, on
            it or on the button it is for."""
            pv = self.preview
            if not pv.get_visible() or pv.button is None:
                return
            point = self.pointer()
            rect = layer_rect(hyprq("layers"), pv.button.bar.name, "waybar-dock-preview", os.getpid())
            got = pv.button_rect()
            if inside(point, rect, slack=GAP) or (got and inside(point, got[0])):
                return
            self.preview.close()

        def close_preview(self):
            if self.preview.get_visible():
                self.preview.close()

        def thumb(self, w, done):
            """The window's picture, from the cache or a grim in the background;
            done(pixbuf) only when there is one."""
            sid = w.get("stable_id")
            if not sid or not re.match(r"^[0-9a-fA-F]+$", sid) or not shutil.which("grim"):
                return
            got = self.thumbs.get(sid)
            if got and time.monotonic() - got[0] < THUMB_TTL_S:
                if got[1] is not None:
                    done(got[1])
                return
            if sid in self.thumb_busy:
                return
            self.thumb_busy.add(sid)
            try:
                proc = Gio.Subprocess.new(["grim", "-T", sid, "-s", str(thumb_scale(w.get("size"))),
                                           "-t", "png", "-l", "1", "-"],
                                          Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
            except GLib.Error:
                self.thumb_busy.discard(sid)
                return

            def finished(p, res):
                self.thumb_busy.discard(sid)
                pb = None
                try:
                    ok, out, _err = p.communicate_finish(res)
                    if ok and p.get_successful() and out is not None and out.get_size():
                        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                        loader.write_bytes(out)
                        loader.close()
                        pb = loader.get_pixbuf()
                        if pb is not None and (pb.get_width() > THUMB_W or pb.get_height() > THUMB_H):
                            f = min(THUMB_W / pb.get_width(), THUMB_H / pb.get_height())
                            pb = pb.scale_simple(max(1, int(pb.get_width() * f)), max(1, int(pb.get_height() * f)),
                                                 GdkPixbuf.InterpType.BILINEAR)
                except GLib.Error:
                    pb = None
                if len(self.thumbs) > 64:
                    self.thumbs.clear()
                self.thumbs[sid] = (time.monotonic(), pb)
                if pb is not None:
                    done(pb)
            proc.communicate_async(None, None, finished)

        # clicks
        def click(self, item):
            if not item:
                return
            what = click_action(item, self.active)
            if what is None:
                return
            if what[0] == "launch":
                self.launch(item)
            else:
                self.close_preview()
                spawn(*(focus_argv(what[1]) or [None]))

        def launch(self, item, action=None):
            app_id = item.get("app_id")
            if not app_id:
                return
            argv = launch_argv(app_id, action)
            if argv:
                spawn(*argv)
            elif action:
                info = app_info(app_id)
                if info is not None:
                    info.launch_action(action, None)
            if not item.get("windows"):
                self.launching[item["group"]] = time.monotonic() + LAUNCH_S
                GLib.timeout_add_seconds(LAUNCH_S + 1, lambda: (self.render(), False)[1])
                self.render()

        def new_window(self, item):
            info = app_info((item or {}).get("app_id"))
            if info is None:
                return
            self.launch(item, new_window_action(info.list_actions()))

        def popup(self, menu, widget, event):
            self.held.add("menu")
            self.close_preview()

            def gone(*_):
                self.held.discard("menu")
                # A menu is made for each right click: destroy it once it
                # closes, or each one lives on. Idle, so the item clicked
                # (activated after the menu deactivates) still runs first.
                GLib.idle_add(lambda: (menu.destroy(), False)[1])
                for bar in self.bars.values():
                    self.debounce(f"leave-{bar.name}", LEAVE_MS, lambda b=bar: self.check_leave(b))
            menu.connect("deactivate", gone)
            menu.attach_to_widget(widget, None)
            pos = widget.get_toplevel().position if hasattr(widget.get_toplevel(), "position") else "bottom"
            gravity = {"bottom": (Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH), "left": (Gdk.Gravity.EAST, Gdk.Gravity.WEST),
                       "right": (Gdk.Gravity.WEST, Gdk.Gravity.EAST)}[pos]
            menu.popup_at_widget(widget, gravity[0], gravity[1], event)

        def item_menu(self, button, event):
            item = button.item or {}
            menu = Gtk.Menu()

            def add(label, fn, sensitive=True):
                mi = Gtk.MenuItem.new_with_label(label)
                mi.set_sensitive(sensitive)
                mi.connect("activate", lambda *_: fn())
                menu.append(mi)

            info = app_info(item.get("app_id"))
            if info is not None:
                for action in info.list_actions():
                    add(info.get_action_name(action) or action, lambda a=action: self.launch(item, a))
                if info.list_actions():
                    menu.append(Gtk.SeparatorMenuItem())
                add("New window" if item.get("windows") else f"Open {item['name']}",
                    lambda: self.new_window(item) if item.get("windows") else self.launch(item))
            windows = item.get("windows") or []
            if len(windows) > 1:
                for w in windows[:MENU_WINDOWS]:
                    add(cut(w["title"] or item["name"]), lambda a=w["address"]: spawn(*(focus_argv(a) or [None])))
                menu.append(Gtk.SeparatorMenuItem())
            app_id = item.get("app_id")
            if app_id:
                pinned = self.pinned()
                if app_id in pinned:
                    add("Unpin", lambda: self.save_pinned(unpin(self.pinned(), app_id)))
                    i = pinned.index(app_id)
                    add("Move left" if button.bar.position == "bottom" else "Move up",
                        lambda: self.save_pinned(move_pin(self.pinned(), app_id, -1)), i > 0)
                    add("Move right" if button.bar.position == "bottom" else "Move down",
                        lambda: self.save_pinned(move_pin(self.pinned(), app_id, 1)), i < len(pinned) - 1)
                else:
                    add("Pin", lambda: self.save_pinned(pin(self.pinned(), app_id)))
            if windows:
                menu.append(Gtk.SeparatorMenuItem())
                add("Close window" if len(windows) == 1 else f"Close all {len(windows)} windows",
                    lambda: [spawn(*(close_argv(w["address"]) or [None])) for w in windows])
            menu.append(Gtk.SeparatorMenuItem())
            add("Dock settings", lambda: spawn(sys.executable, SETTINGS_APP, "dock"))
            menu.show_all()
            self.popup(menu, button, event)

        # clock
        def tick_clock(self, reschedule=True):
            if not ((self.cfg["layout"] == "taskbar" and self.cfg["clock"]) or "clock" in dock_tiles(self.cfg)):
                self.cancel("clock")
                return False
            import region
            moment = datetime.now()
            language = barclock.lang() if barclock is not None else None
            t, d = clock_text(moment, region.prefs(), language)
            leaf = day_leaf(moment, language)
            for bar in self.bars.values():
                bar.set_clock(t, d, leaf)
            if reschedule or not self.ids.get("clock"):
                self.cancel("clock")
                self.ids["clock"] = GLib.timeout_add_seconds(max(1, 60 - moment.second), self.on_minute)
            return False

        def on_minute(self):
            self.ids["clock"] = None      # this source ends here: never keep a dead id
            self.tick_clock()
            return False

        # the status buttons (TOP BAR in the module docstring)
        def status_wanted(self):
            return status_wanted(self.cfg)

        def status_sources(self):
            """Start what the taskbar's status buttons need and stop the rest;
            called at each rebuild, so it only ever starts what is missing."""
            want = self.status_wanted()
            for key in [k for k in self.status_procs if k not in want]:
                self.status_procs.pop(key).force_exit()
            for key in [k for k in self.status_text if k not in want]:
                del self.status_text[key]
            if "weather" not in want:
                self.cancel("weather")
            if "network" in want and "network" not in self.status_procs:
                self.watch_lines("network", [NETWORK_PY, "watch", "--icon"],
                                 lambda line: self.set_status("network", pill_text(line)))
            if "sound" in want and "sound" not in self.status_procs:
                self.watch_lines("sound", ["pactl", "subscribe"], self.on_pactl)
                self.read_volume()
            if "weather" in want and not self.ids.get("weather") and not self.status_text.get("weather"):
                self.fetch_weather()
            for key, argv in PILL_WATCH.items():
                if key in want and key not in self.status_procs:
                    self.watch_lines(key, argv, lambda line, k=key: self.set_status(k, pill_state(line)))
            for key, fetch in (("notifications", self.fetch_notifications), ("battery", self.read_battery)):
                if key not in want:
                    self.cancel(key)
                elif not self.ids.get(key):
                    fetch()
            if self.badges_wanted() and not self.ids.get("badges"):
                self.fetch_badges()
            elif not self.badges_wanted():
                self.cancel("badges")
                self.unread = []
            if "language" in dock_tiles(self.cfg):
                if not self.ids.get("language"):
                    self.fetch_language()
            else:
                self.cancel("language")

        def watch_lines(self, key, argv, on_line):
            """argv's output, a line at a time, to on_line; started again
            STATUS_RESTART_S after it ends while its button is wanted."""
            try:
                proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE
                                          | Gio.SubprocessFlags.STDERR_SILENCE)
            except GLib.Error as exc:
                print(f"dock: {argv[0]}: {exc.message}", file=sys.stderr, flush=True)
                self.debounce(f"status-{key}", STATUS_RESTART_S * 1000, self.status_sources)
                return
            self.status_procs[key] = proc
            stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

            def got(src, res):
                try:
                    line, _n = src.read_line_finish_utf8(res)
                except GLib.Error:
                    line = None
                if self.status_procs.get(key) is not proc:
                    return            # stopped, or another one runs
                if line is None:      # it ended
                    del self.status_procs[key]
                    self.debounce(f"status-{key}", STATUS_RESTART_S * 1000, self.status_sources)
                    return
                on_line(line)
                src.read_line_async(GLib.PRIORITY_DEFAULT, None, got)
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, got)

        def run_text(self, argv, done):
            """argv's whole output to done(text) ("" when it could not run)."""
            try:
                proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE
                                          | Gio.SubprocessFlags.STDERR_SILENCE)
            except GLib.Error:
                done("")
                return

            def finished(p, res):
                try:
                    _ok, out, _err = p.communicate_utf8_finish(res)
                except GLib.Error:
                    out = ""
                done(out or "")
            proc.communicate_utf8_async(None, None, finished)

        def set_status(self, key, got):
            if got is None or key not in self.status_wanted():
                return
            self.status_text[key] = got
            for bar in self.bars.values():
                bar.set_status(key, *got)

        def on_pactl(self, line):
            # "Event 'change' on sink #56": the volume, a mute, another
            # default; never the apps' own streams (sink-input), which
            # change all the time something plays.
            if " on sink #" in line or " on server" in line:
                self.debounce("volume", 80, self.read_volume)

        def read_volume(self):
            self.run_text(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                          lambda out: self.set_status("sound", volume_text(out) or ("", "")))

        def fetch_weather(self):
            """wttr.py, as the top bar's pill ran it: every WEATHER_S, sooner
            after a stale answer."""
            self.ids["weather"] = None

            def done(out):
                lines = out.strip().splitlines()
                got = pill_text(lines[-1]) if lines else None
                self.set_status("weather", got)
                if "weather" in self.status_wanted() and not self.ids.get("weather"):
                    stale = got is None or '"stale"' in lines[-1]
                    self.ids["weather"] = GLib.timeout_add_seconds(
                        WEATHER_RETRY_S if stale else WEATHER_S, self.fetch_weather)
            self.run_text([WTTR_PY], done)
            return False

        def fetch_notifications(self):
            """notifications.py, as the bar's pill ran it: every NOTIFY_S,
            and at once on SIGUSR2 (poll_now)."""
            self.ids["notifications"] = None
            self.run_text([NOTIFICATIONS_PY], lambda out: self.set_status(
                "notifications", pill_state((out.strip().splitlines() or [""])[-1])))
            if "notifications" in self.status_wanted():
                self.ids["notifications"] = GLib.timeout_add_seconds(NOTIFY_S, self.fetch_notifications)
            return False

        def read_battery(self):
            self.ids["battery"] = None
            self.set_status("battery", battery_text(*read_battery()))
            if "battery" in self.status_wanted():
                self.ids["battery"] = GLib.timeout_add_seconds(BATTERY_S, self.read_battery)
            return False

        def poll_now(self):
            """SIGUSR2 (bar_signals.py poke): the notifications' count again."""
            if "notifications" in self.status_wanted():
                self.cancel("notifications")
                self.fetch_notifications()
            if self.badges_wanted():
                self.cancel("badges")
                self.fetch_badges()

        def pill_click(self, key, event):
            if event.type != Gdk.EventType.BUTTON_PRESS:
                return True         # a double click's second press: one click is one run
            argv = PILL_CLICKS.get(key, {}).get(event.button)
            if argv:
                spawn(*argv)
            return True

        def status_click(self, key, event):
            if event.button != 3:
                return False
            if key == "sound":
                spawn("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
            elif key == "weather":
                spawn(WTTR_PY, "open")
            elif key == "network":
                spawn("kitty", "-e", "nmtui")
            return True

        def status_scroll(self, key, event):
            if key != "sound":
                return False
            up = event.direction == Gdk.ScrollDirection.UP
            if event.direction == Gdk.ScrollDirection.SMOOTH:
                _ok, _dx, dy = event.get_scroll_deltas()
                if abs(dy) < 0.5:
                    return True
                up = dy < 0
            elif event.direction != Gdk.ScrollDirection.DOWN and not up:
                return True
            spawn("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@",
                  VOLUME_STEP + ("+" if up else "-"))
            return True

        # the start button: the launcher, or the classic menu (start_menu)
        def open_start(self, button):
            if self.cfg["start_menu"] == "classic":
                self.classic_menu(button, Gtk.get_current_event())
            else:
                spawn(sys.executable, LAUNCHER)

        def classic_menu(self, button, event):
            """A cascading menu above the start button: the pinned apps,
            Programs by category (menu_programs), Files, Settings, Search,
            Run, then Lock, Sleep and Shut down (the power panel, which asks
            before it logs out, restarts or powers off)."""
            menu = Gtk.Menu()
            cls(menu, "dock-start-menu")

            def entry(text, icon=None, action=None, sub=None, gicon=None):
                mi = Gtk.MenuItem()
                box = Gtk.Box(spacing=8)
                img = (Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.MENU) if gicon is not None
                       else Gtk.Image.new_from_icon_name(icon or "", Gtk.IconSize.MENU))
                box.pack_start(img, False, False, 0)
                box.pack_start(Gtk.Label(label=text, xalign=0), True, True, 0)
                mi.add(box)
                if sub is not None:
                    cls(sub, "dock-start-menu")   # its own window: no class comes down to it
                    mi.set_submenu(sub)
                if action is not None:
                    mi.connect("activate", lambda *_: action())
                return mi

            def app_entry(name, app_id, info):
                return entry(name, gicon=info.get_icon() if info is not None else fallback_icon,
                             action=lambda: spawn(*(launch_argv(app_id) or [None])))

            pinned = [(a, app_info(a)) for a in self.pinned()]
            pinned = [(a, i) for a, i in pinned if i is not None]
            for app_id, info in pinned:
                menu.append(app_entry(info.get_display_name(), app_id, info))
            if pinned:
                menu.append(Gtk.SeparatorMenuItem())
            apps = [(i.get_display_name(), i.get_id(), i.get_categories() or "")
                    for i in Gio.AppInfo.get_all() if i.should_show() and i.get_id()]
            programs = Gtk.Menu()
            for (title, icon), items in menu_programs(apps):
                sub = Gtk.Menu()
                for name, app_id in items:
                    sub.append(app_entry(name, app_id, app_info(app_id)))
                programs.append(entry(title, icon, sub=sub))
            menu.append(entry("Programs", "applications-all", sub=programs))
            menu.append(entry("Files", "system-file-manager",
                              lambda: spawn(sys.executable, DEFAULT_APPS, "run", "files")))
            menu.append(entry("Settings", "preferences-system", lambda: spawn(sys.executable, SETTINGS_APP)))
            menu.append(entry("Search…", "system-search", lambda: spawn(sys.executable, LAUNCHER)))
            menu.append(entry("Run…", "system-run", lambda: spawn(sys.executable, LAUNCHER, "!")))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(entry("Lock", "system-lock-screen", lambda: spawn("hyprlock")))
            menu.append(entry("Sleep", "system-suspend", lambda: spawn("systemctl", "suspend")))
            menu.append(entry("Shut down…", "system-shutdown",
                              lambda: spawn(sys.executable, PANEL, "toggle", "power")))
            menu.show_all()
            self.popup(menu, button, event)

        # files
        def watch(self, folder, handler):
            try:
                os.makedirs(folder, exist_ok=True)
                mon = Gio.File.new_for_path(folder).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            except (GLib.Error, OSError) as exc:
                print(f"dock: cannot watch {folder}: {exc}", file=sys.stderr, flush=True)
                return
            wanted = (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                      Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.RENAMED,
                      Gio.FileMonitorEvent.MOVED_IN)

            def changed(_m, gfile, other, event):
                if event in wanted:
                    handler({f.get_basename() for f in (gfile, other) if f is not None})
            mon.connect("changed", changed)
            self.keep.append(mon)

        def on_settings_dir(self, names):
            if os.path.basename(SETTINGS_FILE) in names:
                self.debounce("settings", SETTINGS_DEBOUNCE_MS, self.reload_settings)

        def on_theme(self, names):
            if names & set(THEME_FILES):
                self.debounce("theme", THEME_DEBOUNCE_MS, self.restyle)

        def restyle(self):
            load_css()
            was = self.magnify()
            self.theme = self.read_theme()
            if self.magnify() != was:
                self.rebuild()        # magnification reserves its own room
                return
            for bar in self.bars.values():
                bar.restyle_start()
            self.tick_clock(reschedule=False)     # a ja theme writes the date its way (lang)

        def reload_settings(self):
            new = read_settings()
            if not new["enabled"]:
                print("dock: switched off", flush=True)
                Gtk.main_quit()
                return
            old, self.cfg = self.cfg, new
            shape = ("layout", "position", "autohide", "monitors", "tray", "clock", "weather", "network",
                     "sound", "magnify", "workspaces", "notifications", "battery", "privacy", "top_bar")
            if any(old[k] != new[k] for k in shape):
                self.rebuild()
                return
            if old["icon_size"] != new["icon_size"]:
                self.rebuild()        # the room round the card follows the icons
                return
            self.render()
            self.autohide_all()

        def start(self):
            self.watch(os.path.dirname(SETTINGS_FILE), self.on_settings_dir)
            self.watch(GEN_DIR, self.on_theme)
            self.apps_monitor = Gio.AppInfoMonitor.get()
            self.apps_monitor.connect("changed", lambda *_: self.debounce(
                "apps", 1000, lambda: (self.load_apps(), self.render())))
            display = Gdk.Display.get_default()
            display.connect("monitor-added", lambda *_: self.debounce("place", PLACE_MS, self.place))
            display.connect("monitor-removed", lambda *_: self.debounce("place", PLACE_MS, self.place))
            if self.cfg["pinned"] is None:
                self.seed()
            self.rebuild()
            self.connect_events()

    # -- the scratch harness (HARNESS in the module docstring) -------------------------------
    def harness_stage(conf, engine):
        """A picture under the bar (the theme's wallpaper, or a flat colour),
        so a screenshot of it shows no window of yours and the blur has
        something to frost. Bottom of the harness's screen, no input."""
        bar = next(iter(engine.bars.values()), None)
        if bar is None:
            return None
        win = Gtk.Window()
        layer_window(win, "dock-harness-stage", GtkLayerShell.Layer.TOP, bar.gdk_mon)
        side = bar.position
        across = ("left", "right") if side == "bottom" else ("top", "bottom")
        for e in (side,) + across:
            GtkLayerShell.set_anchor(win, edges(e), True)
        GtkLayerShell.set_exclusive_zone(win, -1)
        geo = bar.gdk_mon.get_geometry()
        height = int(conf.get("stage_height") or 240) if side == "bottom" else geo.height
        win.set_size_request(-1 if side == "bottom" else 240, height if side == "bottom" else -1)
        pic = None
        try:
            if conf.get("stage"):
                full = GdkPixbuf.Pixbuf.new_from_file(conf["stage"])
                w = geo.width
                h = max(1, full.get_height() * w // max(1, full.get_width()))
                pic = full.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
        except GLib.Error:
            pic = None

        def draw(_w, cr):
            cr.set_source_rgb(0.2, 0.22, 0.26)
            cr.paint()
            if pic is not None:
                Gdk.cairo_set_source_pixbuf(cr, pic, 0, height - pic.get_height())
                cr.paint()
            return False
        win.connect("draw", draw)
        win.connect("realize", lambda w: w.get_window().input_shape_combine_region(cairo.Region(), 0, 0))
        win.show_all()
        return win

    def harness_drive(conf, engine):
        """Synthetic pointer moves, at 120 a second, through Fx.point -- the
        same call a real motion event makes: "hold" a fraction along the
        dock (0-1) from the start, "sweep" seconds of going end to end and
        back; then "exit_s" quits."""
        start = time.monotonic()
        state = {"phase": "wait"}

        def bars():
            return [b for b in engine.bars.values() if b.fx is not None]

        def at(frac):
            for b in bars():
                w = b.items.get_allocation().width if b.position == "bottom" else b.items.get_allocation().height
                b.fx.point(frac * w)

        def step():
            t = time.monotonic() - start - float(conf.get("delay_s") or 1.0)
            if t < 0:
                return True
            sweep = float(conf.get("sweep") or 0)
            if conf.get("hold") is not None and not sweep:
                at(float(conf["hold"]))
                return False
            if conf.get("hover") is not None:
                for b in engine.bars.values():
                    kids = [c for c in b.items.get_children() if isinstance(c, ItemButton)]
                    if b.fx is not None and kids:
                        b.fx.hover(kids[min(int(conf["hover"]), len(kids) - 1)], True)
                return False
            if sweep:
                if t > sweep:
                    for b in bars():
                        b.fx.leave()
                    return False
                phase = (t % 2.0) / 2.0
                at(phase * 2 if phase < 0.5 else 2 - phase * 2)
                return True
            return False
        GLib.timeout_add(8, step)
        if conf.get("press") is not None:
            def press():
                for b in engine.bars.values():
                    kids = [c for c in b.items.get_children() if isinstance(c, ItemButton)]
                    if b.fx is not None and kids:
                        b.fx.press(kids[min(int(conf["press"]), len(kids) - 1)])
                return False
            GLib.timeout_add(int(float(conf.get("delay_s") or 1.0) * 1000), press)
        if conf.get("selftest"):
            def selftest():
                """A real motion event's path (Bar.on_motion -> along) from
                a button's own input window: the dock must see the pointer
                where the button is."""
                for b in engine.bars.values():
                    kids = [c for c in b.items.get_children() if isinstance(c, ItemButton)]
                    if b.fx is None or not kids:
                        continue
                    btn = kids[1]
                    ev = Gdk.Event.new(Gdk.EventType.MOTION_NOTIFY)
                    ev.motion.window = btn.get_event_window()
                    ev.motion.x, ev.motion.y = 5.0, 5.0
                    b.on_motion(b, ev.motion)
                    a, ia = btn.get_allocation(), b.items.get_allocation()
                    want = (a.x - ia.x + 5) if b.position == "bottom" else (a.y - ia.y + 5)
                    print(f"selftest along={b.fx.pointer} want={want} expanded={b.fx.expanded}", flush=True)
                return False
            GLib.timeout_add(int(float(conf.get("delay_s") or 1.0) * 1000) + 200, selftest)
        if conf.get("drag") is not None:
            def drag():
                """A real drag's path, through the button's own handlers and
                input window (on_press, motion-notify -> Bar.drag_motion ->
                along, on_release): app "drag"[0] pressed, the pointer moved
                in steps to app [1]'s middle, let go; then the pinned list
                and the running order are printed."""
                src_i, dst_i = (int(n) for n in conf["drag"])
                for b in engine.bars.values():
                    kids = [c for c in b.items.get_children() if isinstance(c, ItemButton)]
                    if max(src_i, dst_i) >= len(kids):
                        continue
                    btn, dst = kids[src_i], kids[dst_i]
                    horiz = b.position == "bottom"

                    def pos(c):
                        a, ia = c.get_allocation(), b.items.get_allocation()
                        return (a.x - ia.x, a.width) if horiz else (a.y - ia.y, a.height)

                    def event(kind, along):
                        # What the handlers read of a real event; a Gdk.Event's
                        # "button" is its struct, not the button's number. The
                        # window is the button's own input window, as a real one.
                        from types import SimpleNamespace
                        local = along - pos(btn)[0]
                        x, y = (local, 5.0) if horiz else (5.0, local)
                        return SimpleNamespace(type=kind, button=1, x=x, y=y, window=btn.get_event_window(),
                                               state=Gdk.ModifierType.BUTTON1_MASK)
                    s0, l0 = pos(btn)
                    sd, ld = pos(dst)
                    start, end = s0 + l0 / 2, sd + ld / 2
                    btn.on_press(btn, event(Gdk.EventType.BUTTON_PRESS, start))
                    steps = 24
                    state = {"i": 0}

                    def move():
                        state["i"] += 1
                        at = start + (end - start) * state["i"] / steps
                        b.drag_motion(btn, event(Gdk.EventType.MOTION_NOTIFY, at))
                        if state["i"] < steps:
                            return True
                        btn.on_release(btn, event(Gdk.EventType.BUTTON_RELEASE, end))
                        btn.clicked()          # GTK's own click on the release: must do nothing
                        GLib.timeout_add(300, lambda: (print(
                            f"drag pinned={engine.pinned()} order={engine.order} "
                            f"shown={[c.item['group'] for c in b.items.get_children() if isinstance(c, ItemButton)]}",
                            flush=True), False)[1])
                        return False
                    GLib.timeout_add(20, move)     # the harness's pointer steps, not an animation
                    break
                return False
            GLib.timeout_add(int(float(conf.get("delay_s") or 1.0) * 1000), drag)
        if conf.get("preview") is not None:
            def preview():
                for b in engine.bars.values():
                    kids = [c for c in b.items.get_children()
                            if isinstance(c, ItemButton) and (c.item or {}).get("windows")]
                    if kids:
                        engine.preview.open_for(kids[min(int(conf["preview"]), len(kids) - 1)])
                return False
            GLib.timeout_add(int(float(conf.get("delay_s") or 1.0) * 1000), preview)
        if conf.get("exit_s"):
            GLib.timeout_add(int(float(conf["exit_s"]) * 1000), lambda: (Gtk.main_quit(), False)[1])

    def harness_report(conf, engine):
        """The frame timings, to conf["stats"] (JSON)."""
        if not conf.get("stats"):
            return
        out = {"rss_kb": 0, "bars": {}}
        try:
            with open("/proc/self/status") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        out["rss_kb"] = int(line.split()[1])
        except OSError:
            pass
        for name, bar in engine.bars.items():
            if bar.fx is not None:
                out["bars"][name] = bar.fx.stats
        try:
            with open(conf["stats"], "w") as fh:
                json.dump(out, fh)
        except OSError:
            pass

    def cut(text, n=60):
        text = " ".join(str(text or "").split())
        return text if len(text) <= n else text[:n - 1] + "…"

    if harness.get("icon_theme"):
        Gtk.Settings.get_default().props.gtk_icon_theme_name = harness["icon_theme"]
    if harness.get("reduced"):
        Gtk.Settings.get_default().props.gtk_enable_animations = False
    load_css()
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    icons = Icons()
    engine = Engine()
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ImportError, ValueError):
        signal_add = GLib.unix_signal_add
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (Gtk.main_quit(), False)[1])
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (engine.reload_settings(), True)[1])
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, lambda: (engine.poll_now(), True)[1])
    # dock.service's WatchdogSec: a ping from the main loop, so a dock that
    # hangs is restarted.
    try:
        watchdog_s = int(os.environ.get("WATCHDOG_USEC", "0")) / 2e6
    except ValueError:
        watchdog_s = 0
    if watchdog_s > 0:
        sd_notify("WATCHDOG=1")
        GLib.timeout_add_seconds(max(1, int(watchdog_s)), lambda: (sd_notify("WATCHDOG=1"), True)[1])
    if not harness:
        try:
            os.makedirs(RUNTIME, exist_ok=True)
            with open(PID_FILE, "w") as fh:
                fh.write(f"{os.getpid()}\n")
        except OSError:
            pass
        # Back after a crash (dock.service's ExecStopPost brought the bar
        # back meanwhile): the bar goes again, its restart now skipped by
        # bar-wanted.sh since this unit is active (TOP BAR OFF).
        if bar_hidden(cfg) and not dry_env() and unit_active("waybar.service"):
            restart_bar()
    stage = None
    try:
        engine.start()
        if harness:
            stage = harness_stage(harness, engine)
            harness_drive(harness, engine)
        Gtk.main()
    finally:
        if harness:
            harness_report(harness, engine)
            if stage is not None:
                stage.destroy()
        if engine.tray is not None:
            engine.tray.stop()
        engine.forget_toolbox()
        try:
            with open(PID_FILE) as fh:
                if fh.read().strip() == str(os.getpid()):
                    os.unlink(PID_FILE)
        except OSError:
            pass
    return 0


# -- CLI -----------------------------------------------------------------------------------
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
    elif cmd == "follow-theme" and len(args) == 1:
        follow_theme()
    elif cmd in ("pin", "unpin") and len(args) == 2:
        change_pinned(cmd, args[1])
    elif cmd == "move" and len(args) == 3 and args[2] in ("-1", "+1", "1", "left", "right", "up", "down"):
        change_pinned("move", args[1], -1 if args[2] in ("-1", "left", "up") else 1)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
