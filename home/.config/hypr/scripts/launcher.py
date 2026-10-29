#!/usr/bin/env python3
"""App launcher and command palette for ALT+E: the best match as a big hero
card, everything else as a grid of tiles under it.

wofi cannot do this layout -- every row is the same icon-beside-label box and
the selected one cannot be given an area of its own -- so this replaces it for
apps only. wofi stays for the clipboard history (SUPER+V) and the window
switcher (SUPER+W).

    launcher.py          open it, or close it if it is already open
    launcher.py ">"      open it with the query pre-filled (">" = commands;
                         used by binds that want to land straight in a mode)
    launcher.py --daemon stay running, hidden (launcher.service): the two
                         above then only ask it to show / hide, over
                         $XDG_RUNTIME_DIR/launcher.sock -- on screen in ~30 ms
                         instead of ~280 (Python + GTK start, the app list),
                         with the place index loaded once, not per opening.
                         Its lists (apps, windows, clipboard, usage, commands,
                         browsers) are read again each time it shows, just
                         after it is up, and launcher.css is reloaded, so a
                         new app or theme needs no restart. Without the
                         daemon (not started, crashed) the plain commands
                         run a launcher of their own, as before.

Modes, by the first character typed:

    (none)  everything at once, in this order:
              * answers: arithmetic ("2^10", "17% of 340"); units ("10 km to
                mi", "100 F to C", "5 ft 3 in to cm"); currency, in about any
                phrasing -- "30 USD to MXN", "MXN to USD" (the rate both
                ways), "$30", "30usd", "1,500 pesos en dólares", "2.5k eur",
                "0.01 btc"; an amount alone goes to HOME_CURRENCIES, a code
                alone in CAPITALS ("USD") gives its rate (parse_currency);
                market quotes when you type a TICKER IN CAPITALS ("NVDA",
                "WALMEX", "BTC") or $ and a name ("$walmart") -- Enter
                copies an answer, opens a quote on Yahoo Finance;
              * airports: an IATA code in CAPITALS ("MEX", "TLC", "LAX"), or
                with the word ("mex airport", "aeropuerto tlc"), or a city
                and the word ("toluca airport", "aeropuertos cdmx": MEX
                and NLU, biggest first) -- Enter opens it in GNOME Maps,
                Shift+Enter flights from it on Google Flights; listed with
                the answers, since the query says what it wants;
              * the time: "time in tokyo", "tokyo time", "hora en madrid" (now
                there, its UTC offset, hours ahead of / behind you); and a
                time moved between places or zones: "3pm toluca to london",
                "15:00 tokyo", "9:30am EST in cdmx" (no "to": to here) --
                places from the place index, a few zone abbreviations
                (ZONE_ABBR); Enter copies the time;
              * weather: "weather paris", "clima toluca", "tokyo forecast" --
                now, and the next two days, from wttr.in (what the bar's
                pill uses) for the place's coordinates; asked only when one
                of those words is typed, in the background; Enter opens the
                full forecast;
              * dates: "today + 90 days", "dec 24 - 2 weeks", "hoy + 3 meses",
                "days until dec 24", "days since 2020-01-01", "days between
                1 jan and 1 mar", "week 42", "week", a date ("2026-12-24",
                "24/12/2026": day first) for its weekday and distance, a Unix
                time ("1792302307") -- English or Spanish words; Enter copies
                the ISO date;
              * tools: a colour ("#3ddc68", "#fff", "rgb(61, 220, 104)") as
                hex / rgb / hsl with a swatch; a number between bases
                ("0xff", "0b1010", "255 to hex", "bin 42"); "uuid";
                "password" / "password 24" / "contraseña" (secrets: random
                each time it is typed; a passphrase too, from
                /usr/share/dict/words if present) -- Enter copies;
              * apps;
              * places: a town or city's name ("toluca", "ixtlahuaca", "paris
                texas", "cdmx") as a map pin -- Enter opens it in GNOME Maps,
                Shift+Enter in Google Maps; from make-places.py's offline
                index of every place of 5,000+ people (GeoNames), so nothing
                typed goes online; right after the apps whose NAME starts
                with the query, so "steam" is still Steam first;
              * open windows (Enter switches to it); commands;
              * clipboard history entries containing the words (Enter copies);
              * files in ~ (plocate, a moment after you stop typing --
                Shift+Enter shows the file in Files instead of opening it);
              * emoji whose name has the words (Enter copies);
              * one "Search in <browser>" per installed web browser, the
                default first (a typed address -- "github.com/x" -- becomes
                "Open in <browser>"), then "Find in Maps" (GNOME Maps;
                Shift+Enter: Google Maps in the default browser).
            Text too long to be a query (a paste: over LONG_TEXT characters or
            more than one line) offers instead to save it as a text file, save
            and open it, or add it to the quick-note inbox
    >       commands: every toggle and tool of this desktop -- display, filters,
            animations, theme, recording, panels, updates, work hours...
    keys    keyboard shortcuts only ("keys screenshot", "keys super s";
            "keys" alone: all of them): every bind with a description, as the
            shortcuts panel (SUPER+F1) lists them, from `hyprctl binds -j`
            each time the launcher shows -- the keys on each row, Enter does
            what they do (launcher_shortcuts.py: the bind is looked up in
            lua/userbinds.lua's table and called, nothing is pressed for
            you). Without "keys" they still come up, named for what they do
            ("terminal", "fullscreen"), after the apps, windows, settings and
            commands. ("?" stays the AI's.)
    pw      passwords ("pw github"): the entries of your password manager
            with the words, through the Secret Service (KeePassXC with its
            Secret Service integration on, or GNOME Keyring, KWallet...; the
            row says which). Enter copies the password and clears the
            clipboard 30 s later if it still holds it; the secret is fetched
            by launcher_secrets.py in a process of its own, never by the
            launcher, and kept out of the clipboard history. No provider
            running, nothing shared or a locked database: one row saying so
            (Enter opens KeePassXC / asks the provider to unlock).
    =       calculator only. Enter copies the result.
    #       colour history (scripts/colorpick.sh). Enter copies the hex.
    :       emoji by name (":fire", ":thumbs"). Enter copies it.
    / ~     a path ("~/Doc", "/etc/hy"): what is in that folder and starts
            with the last part, folders first. Tab goes into the highlighted
            folder; Enter opens it in Files (a file: in its app); Shift+Enter
            a terminal there (a file: shown in Files).
    !       a shell command ("!htop", "!du -sh ~/Downloads"): Enter runs it in
            kitty, which stays open when it ends (the output stays readable);
            Shift+Enter runs it in the background, no terminal.
    ?       ask the AI ("?how do I resize a btrfs partition"): Enter asks it
            in the LLM chat window, llm-chat.py (its mascot animates while
            the model works) -- a local LM Studio model by default, no
            account needed. With Claude Code installed and a Claude model
            picked, Shift+Enter starts the interactive `claude` in kitty
            instead, in ~, and the tile under it, "Start a Claude Code
            session", does the same; without it there is no such tile.
            "?" alone offers the empty window ("LLM chat" in > commands
            too). Then:
              * "Ask <model> about the clipboard": the prompt (or "Explain
                this") and the clipboard -- its text in a fenced block, or,
                an image, saved under $XDG_RUNTIME_DIR/llm-launcher/ and
                attached to the message (llm-chat.py --image); "Ask <model>
                about the screen": grim takes the focused monitor there,
                half a second after the launcher has gone (so it is not in
                the shot), attached the same way, with the prompt (or
                "Explain what's on my screen"). A model needs vision to see
                them: the window says so when it has not. "?clip ..." /
                "?screen ..." put that one first, the word left out of the
                prompt;
              * past conversations: "?" alone, the 12 last used (any
                folder); with words, those whose first message or folder
                has them all -- the chat window's own, and Claude Code's
                with it installed. Enter goes on with it in the chat window
                (--resume, in its folder); a Claude Code one Shift+Enter
                `claude --resume` in kitty there. Claude Code's are read
                from the head of ~/.claude/projects/*/<id>.jsonl, again only
                when the file changes (claude_sessions).
            "?@<folder> question" runs all of it in that folder -- the
            window's --cwd (its tools' working directory), kitty -d
            ("?@~/Projects/atlas fix the build script"); its past
            conversations are the ones from there. While the folder is
            being typed ("?@~/Pro") its folders are offered as in path
            mode: Tab goes into one, Enter opens the chat there.
            A model's name as the first word picks the model for that
            question: "?gemma explain this", "?@~/proj glm fix x" -- a local
            LM Studio model's alias ("gemma-4-e4b") or the start of one,
            when only one starts so ("gemma", "glm"; "qwen3" is two, so it
            is a word of the prompt), server:<id> for the OpenAI-compatible
            server's, and with Claude Code installed Claude's aliases
            (fable, opus, sonnet, haiku) or a full id ("claude-opus-5-5").
            Any other first word is the prompt's ("?why opus" asks about
            opus). Without one, the default (llm.json, below). Every item's
            line says which ("· gemma-4-e4b (local)", "· opus"). A local
            model is readied by the chat window (LM Studio's server
            started, the model loaded: llm_models.py).
            "?models" (or "?model") lists them all: Enter makes one the
            default for ? and the chat window, Shift+Enter the one for ??.
            "?models <words>" only those with every word in the name, label
            or id, and last "Search downloads for <words>": Enter (or Tab)
            turns the box into "?get <words>".
    ?get    models to download ("?get qwen coder"; "?download ..." the same):
            GGUF repos on Hugging Face with the words, most downloaded
            first, lmstudio-community's (LM Studio's own quantizations)
            counted eightfold, so they come first when they are among them;
            the hero the best, "Open on Hugging Face" (its page) the tile
            after it. Each line: the variant that would be downloaded --
            Q4_K_M if the repo has it, else the next of QUANTS -- and its
            size (the real one for the top HF_SIZED, "~" a guess from the
            parameter count for the rest), the fit against this GPU's VRAM
            (gpu.py's main card; the RAM with no card or an integrated one)
            ("fits GPU": weights + ~1.5 GB of context; "partial offload":
            within VRAM + half the RAM; "too big"), parameters ("30.5B (A3B
            active)" for a mixture of experts), downloads, likes, last
            update; "installed: ?<alias>" (and a ✓) when its folder is in
            ~/.lmstudio/models, "downloading now" while it is. Enter
            downloads it in the background -- `llm_models.py get`, in a
            scope of its own, so a launcher restart does not end it: `lms
            get https://huggingface.co/<repo>@<variant> -y --gguf`, its
            progress one notification updated in place (once a second),
            then "Downloaded X -- type ?<alias> to use it" or lms's error,
            and the model cache refreshed (?models, the chat window's picker).
            One download per repo at a time (a lock file per repo).
            Shift+Enter: kitty running `lms get --select`, lms's own
            variant picker and progress bar. With less than the variant's
            size + 10 GB free on disk the line says so and Enter asks first.
            Searched HF_DELAY (0.5 s) after typing stops, in a thread, each
            query once a session.
    ??      a quick answer ("??how tall is mount fuji"): a few sentences from
            the quick model -- llm.json's "quick" (the first local model
            when that is not set and Claude Code is not installed);
            "??gemma 2+2" asks gemma this once -- streamed into the hero
            card, no window. A local or server model is asked directly
            (llm_chat_engine's stream(): plain chat, no tools); a Claude one
            through `claude -p` (no tools, no MCP). Asked 0.6 s after typing
            stops; a new question ends the old one, and so does closing the
            launcher. Enter copies the answer; Shift+Enter continues that
            conversation in the chat window, on the same model (a Claude
            run is a saved session, named so it stays out of the
            past-session list; a local one becomes a conversation of the
            window's own). The model and cost (Claude only) show under it
            when done, the error if it fails; while a local model loads, how
            far it is. The tile under it asks the chat window instead.

"Ask <model>" also comes up without the "?": for a query of two words or
more, or one with a "?" in it, just before the "Search in <browser>" items --
last, so it never takes the hero from an app or an answer -- and for a long
paste, as "Ask <model> about this" (the paste is the prompt). The prompt
goes to the chat window as one argv element, never through a shell.

Windows: "move <name> to <workspace>" (Shift+Enter: and follow it), "bring
<name>" (to this workspace), "close <name>" -- for each window whose class
or title has <name>; Spanish too: mover ... a 3, traer, cerrar.

Timers (timers.py, no prefix): "timer 5m tea", "10 min timer", "temporizador 1:30"
-- Enter starts it; "alarm 7:30", "alarma 6am", "wake me up at 7" -- Enter sets
it (the next time that time comes), "alarm 7:00 weekdays" / "daily" / "mon
wed fri" every time; "... then suspend" (lock, pause music, shutdown, or
"!command") does that at the end instead of ringing, 30 s after saying so;
"remind me in 40 min to call the lab", "remind at 15:30 check the queue",
"recuérdame en 10 min ..." -- a notification with your words; "focus" /
"pomodoro 50" -- a focus round in Do Not Disturb, then a break on its own;
"stopwatch" / "cronómetro" / "start counting" -- Enter starts it, then
pauses / resumes it, Shift+Enter stops it and copies the time. They ring with
the launcher closed (systemd user timers), come back after a reboot, and
count down in the bar (custom/timers). "timers" (or "alarm", "stopwatch"...
alone) lists what runs -- Enter cancels one, asked first -- and the calendar
alarms switch (an alarm 10 min before each event in your calendars).

Settings (no prefix): "volume 40" / "vol up" / "vol -5" / "volume mute", "mic off",
"output hdmi" (which device plays the sound), "brightness 70" / "brillo" /
"dim", "warmth 4000", "saturation 50" -- all screens, or one: "dim dp-2",
"brightness hdmi 60", "warmth lg 5000" (screen-color.py, in software; the
night light's warmth comes on top), "rate" / "rate dp-2 120" (refresh
rates), "accent #ff8800" (your own accent colour), "bluetooth on", "wifi off"
(network-settings.py, the Network page's backend: Bluetooth off is an rfkill
block too, so it stays off after a reboot). "volume 130" goes past 100 only
with over-amplification on (Settings > Sound, sound-settings.py boost; the
same limit as the volume keys), and says so when it stops at 100.

Settings pages (no prefix): one "Settings: <page>" for each page of the
Settings window whose title or keywords the words find -- "bluetooth",
"tap to click", "time zone", "hdr" -- with the keyword that found it; Enter
opens the window on that page (settings.py <page>). The same rules as the
window's own search box (settings_pages/_catalog.py), read from the pages'
sources, so a new page is found with no restart. "settings" alone lists
every page, "settings <words>" only those; in > mode they follow the
commands. Among the commands, the pages' backends: copy / save the system
report, over-amplification on / off, window blur / shadows / dimming and
the tiling layout, airplane mode, Keep awake, the power profile, quiet
hours, the clock's 12 / 24 hours, the default browser and terminal, the
magnifier and the other accessibility switches, loading the bar's changes,
password / printers / online accounts.

Emergency alerts (no prefix): "alerts" / "alertas" lists the sources for
your country -- earthquake early warning, tsunami, weather, civil protection
(emergency-alerts.py) -- Enter turns one on or off; "alerts place 40.4 -3.7
es" moves your place.

Ask your desktop (no prefix): "ask what was I working on yesterday at 3pm",
"ask find the PDF about invoices from last week" -- the local model searches
your files, clipboard and window history (ask-desktop.py); the answer comes
as a notification with buttons to open what it found. The word alone shows how it is
now and the likely changes; Enter does it.

Assistant (no prefix): "assistant" / "asistente" opens the desktop
assistant's chat (assistant.py), "assistant compare these two windows" asks
it; "ask …" / "pregunta …" offers it too, first or after Ask your desktop
as Settings > Assistant says.

Desktop memory (no prefix): "remember the link someone sent on Tuesday",
"recuerda el error de la terminal de ayer" -- desktop-memory.py recalls it
from what went past (window titles, copies, notifications, captions, screen
text) with its time; the answer is a notification with Open buttons for the
links and screenshots. With machines paired (peers.py), one more item per
machine asks ITS memory ("Remember on laptop: ..."), answered there.

Continue watching (no prefix): "continue" / "resume" / "watch" lists what
mpv was stopped in the middle of, newest first, from its resume files; any
3+ letters of a title find it too. Enter plays it from there.

Workspace sessions (no prefix, sessions.py): "sessions" / "sesión" lists
the saved ones -- Enter restores what is not open of it -- and "where was
I" (also "last session") the one from before this login; "save session
work" saves the windows open now as "work".

Project contexts (no prefix, contexts.py): "project" / "ctx" / "proyecto"
lists them -- Enter switches into one (its session, a terminal and the
editor on the repo, its preview, its notification filter), Shift+Enter saves
the windows open now as its layout; "project atlas" just that one, or "New
project: atlas" for a repo in your projects folder without a context yet; "leave
project" leaves the current one.

"kill <name>" / "end <name>" / "matar <name>" (no prefix) lists your own
processes whose name or command line has <name>, the biggest first, and
"all of them" for an app of many processes. Enter asks first -- the result
turns into one "really end ...?" line; Enter again ends it (SIGTERM),
Shift+Enter instead kills it outright (SIGKILL, also asked first); Esc
leaves it alone.

Commands are the COMMANDS table below: a name, a line under it, an icon and
the argv it runs -- the same scripts the binds and the bar run, so the
palette can never do something the rest of the desktop cannot. After them,
"Chat model: <name>" and "Quick model: <name>", one per model (the current
one ticked): Enter makes it the one for ? / ??. Then "Mascot: …", the chat
window's mascot switches (mascot_mood.py's mascot.json): the moods, random
only, what she reacts to, her reaction groups and reduce motion, each ticked
when on; Enter flips it (reduce motion: "Mascot: reduce motion" sets it
here, "Mascot: reduce motion follows the desktop" hands it back).

Models: llm_models.py has the list -- LM Studio's from `lms ls` (kept in
~/.cache/llm-models.json; asked again, in a thread, when the launcher opens
and the model folders have changed, never while typing), and Claude's when
Claude Code is installed -- and the two choices, in
~/.local/state/hypr/llm.json: "default" (for ? and the chat window) and
"quick" (for ??); a choice naming a Claude model without Claude Code
installed falls back to the first local one. The chat window's header has
the same list, and the server's models too.

Keys: type to filter, arrows to move (Down from the hero enters the tiles, Up
from the top row goes back), Enter launches, Esc closes. A click on a tile
launches it; a click anywhere off the card closes it. Tab: what else can be
done with the selected result, as a list in its place -- its Enter and
Shift+Enter, an app's own actions (New Private Window...), a file's "Open
with ...", Show in Files, Terminal here, Copy its path, Copy the file, a
window's Bring it here / Close it, and for anything Copy the text, Ask the
AI about it, Search the web; Tab or Esc goes back (item_actions). In path mode
Tab still goes into the highlighted folder.

What you pick is learned: each pick is counted under every beginning of what
was typed, so the next time those letters are typed it comes first ("s" ->
Steam, if Steam is what "s" was for). Counts fade over three weeks, so a new
habit wins. In ~/.cache/launcher-picks.json; an app's Tab list has "Forget
what I picked it for". Not for ? and ! queries (never the same twice).

The clipboard, while the box is empty: something just copied (seen for the
first time less than 10 minutes ago, and not used yet) puts up to three
suggestions first -- a link: open it, ask the AI about it; a file or a
path: the file; an error message: ask the AI about it; a long text: ask
the AI, save it; an amount, a unit, a date, a colour: its answer; an image:
ask the AI about it, save it to ~/Pictures/Clipboard; other text: search
the web for it. Typing anything puts the normal results back.

Web search goes through one engine for every browser (SEARCH_URL below):
a browser's own default engine cannot be asked for from outside it.
DuckDuckGo because of its !bangs -- "!g", "!yt lofi", "!w hyprland",
"!gh waybar", "!aw hyprland" -- the engine becomes a choice per search with no
table here to keep. Swap SEARCH_URL for Kagi, Google... if you prefer.

Unit conversions are qalc's (libqalculate: thousands of units). Currency
uses the exchange rates qalc downloads into ~/.local/share/qalculate
(rates.json: ~340 currencies and crypto, daily; refreshed in the background
when a day old), read directly -- the answer's line shows their date. They
can differ from the ECB's weekday reference rate by a fraction of a percent. qalc reads almost ANY word as
a unit ("firefox" is 0 bytes), so it only sees a number + unit + "to"/"in"
+ unit, or a number + currency code, and its answer is thrown away unless it
is in the unit asked for. A bare amount converts to HOME_CURRENCIES.

Quotes ask Yahoo Finance (no key; the same endpoints its site uses, so they
may change some day). Only capitals or a $ send anything: what you type for
apps and files never leaves the machine.

?get / ?download send their words to Hugging Face's public API (no key, no
account): one search for the most downloaded GGUF repos and one for
lmstudio-community's, side by side, then one file-list request for each of
the top HF_SIZED repos (their names, not what was typed). Nothing else in
? mode goes online on its own; "?models <words>" only reads the local list.

Files: `plocate` (its index is rebuilt daily by plocate-updatedb.timer, so a
file made today may be missing until tomorrow) on the base name, then only
what is under ~, outside hidden folders, with every typed word somewhere in
the path; GTK's recent files are searched too and come first.

Ranking: name prefix > word prefix in the name > substring in the name >
match in generic name / keywords / executable > letters in order (fuzzy).
With nothing typed, the most launched apps come first (counts kept in
~/.cache/launcher-usage.json), so the hero is the app you open most.

Looks: launcher.css next to this file. The compositor side: the screen
dimming behind it and the blur are the `wofi-glass` layer rule in
~/.config/hypr/lua/rules.lua, the pop-in is lua/display.lua's anim-launcher
rule (a fade in a still preset); both match this window's namespace.
"""

import json
import os
import sys


def _fast_request():
    """ALT+E with the daemon up: hand it the request and exit BEFORE the
    imports below -- GTK and the rest are ~115 ms that a toggle does not
    need. Only when run as a script (quicknote.py and clipboard.py import
    this file) and not as the daemon itself."""
    if __name__ != "__main__" or sys.argv[1:2] == ["--daemon"]:
        return
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "launcher.sock"))
        s.sendall(json.dumps({"text": sys.argv[1] if len(sys.argv) > 1 else ""}).encode())
    except OSError:
        return                  # no daemon: the full launcher below
    finally:
        s.close()
    sys.exit(0)


_fast_request()

import re  # noqa: E402
import shlex  # noqa: E402
import signal  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
CSS_FILE = os.path.join(HERE, "launcher.css")
PID_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "launcher.pid")
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "launcher.sock")
USAGE_FILE = os.path.expanduser("~/.cache/launcher-usage.json")
# The click-outside sheet the bar's popups use.
sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))

COLUMNS = 6
ROWS = 3                # visible tile rows; the rest scroll
MAX_TILES = 60
MAX_APPS = 30           # so files, windows and the browsers still fit after them
HERO_ICON = 96
TILE_ICON = 48
UNDER_UWSM = "UWSM_FINALIZE_VARNAMES" in os.environ
HYPR = os.path.join(os.path.expanduser("~"), ".config", "hypr", "scripts")
BAR = os.path.join(os.path.expanduser("~"), ".config", "waybar", "scripts")
PANEL = os.path.join(BAR, "panel.py")

# The desktop themes (~/.config/themes/, theme.py): one "Theme: <name>" command
# per theme folder, so a new theme shows up here without touching this file.
sys.path.insert(0, HYPR)
import theme as desktop_theme  # noqa: E402  (no GTK; reads a few small files)
import llm_models  # noqa: E402  (no GTK either: the model list and llm.json)
import timers  # noqa: E402  (no GTK: timers, alarms, the stopwatch -- systemd user timers)
import sessions as session_store  # noqa: E402  (no GTK: saved workspace sessions, sessions.py)
import contexts as context_store  # noqa: E402  (no GTK: project contexts, contexts.py)
import launcher_shortcuts  # noqa: E402  (no GTK: the keyboard shortcuts, from hyprctl binds -j)
import launcher_secrets  # noqa: E402  (no GTK until asked: passwords through the Secret Service)

from settings_pages import _catalog as settings_catalog  # noqa: E402  (no GTK: the Settings pages and their keywords)

SETTINGS = os.path.join(HYPR, "settings.py")
NETSET = os.path.join(HYPR, "network-settings.py")
SOUNDSET = os.path.join(HYPR, "sound-settings.py")
LOOK = os.path.join(HYPR, "window-look.py")
SYSINFO = os.path.join(HYPR, "system-info.py")
DEFAULT_APPS = os.path.join(HYPR, "default-apps.py")
IDLE = os.path.join(HYPR, "idle-settings.py")
A11Y = os.path.join(HYPR, "accessibility.py")
ACCOUNTS = os.path.join(HYPR, "accounts.py")
SESSIONS = os.path.join(HYPR, "sessions.py")
CONTEXTS = os.path.join(HYPR, "contexts.py")


def told(title, argv, then=None):
    """An argv that runs `argv` and then says how it went in a notification:
    what it printed (or, with `then`, what that second command prints -- for
    the scripts that are silent when they work), or its error line when it
    failed. For the backends' commands below, which print one line."""
    import shlex
    q = shlex.quote
    cmd = " ".join(q(a) for a in argv)
    report = f"out=$({' '.join(q(a) for a in then)} 2>&1); " if then else ""
    return ["sh", "-c", f"out=$({cmd} 2>&1) || {{ {q(NOTIFY)} -a Launcher -i dialog-warning {q(title)} \"$out\"; "
                        f"exit 1; }}; {report}{q(NOTIFY)} -a Launcher {q(title)} \"$out\""]


def warned(title, argv):
    """An argv that runs `argv` and says nothing when it works (it opens a
    window, which says it), but its error line in a notification when it
    fails -- "GNOME Settings is not installed" and the like."""
    import shlex
    cmd = " ".join(shlex.quote(a) for a in argv)
    return ["sh", "-c", f"out=$({cmd} 2>&1) || {shlex.quote(NOTIFY)} -a Launcher -i dialog-warning {shlex.quote(title)} \"$out\""]


# (name, subtitle, icon name, argv). Kept in one table on purpose: adding a
# tool to the desktop is one line here. The Settings window's pages are not
# here: settings_items() makes one "Settings: <page>" per page, from the
# pages themselves.
COMMANDS = [
    ("Settings", "every setting of this desktop, searchable  (SUPER+I; or type a page: \"settings sound\")",
     "preferences-system", [SETTINGS]),
    # Through python3, as welcome.service runs it (the file need not be
    # executable): a function, so it is not taken for an executable argv.
    ("Welcome", "the first-login card again: theme, screens, microphone, smart features, the two keys",
     "help-about", lambda: spawn([sys.executable, os.path.join(HYPR, "welcome.py")])),
    ("Display panel", "HDR, screen filter, animations, theme  (SUPER+ALT+D)", "video-display",
     [PANEL, "toggle", "display", "--at", "bar-right"]),
    # The main screen (display.py's primary(): Settings > Screens' choice, else
    # its default), looked up when it runs, not when the launcher started.
    ("HDR on / off", "the main screen  (SUPER+ALT+H)", "weather-clear",
     [sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import display; "
      "display.main(['hdr', display.primary(), 'toggle'])", HYPR]),
    ("Screen filter on / off", "the last filter used  (SUPER+SHIFT+F)", "applications-graphics",
     [os.path.join(HYPR, "display.py"), "filter", "toggle"]),
] + [
    (f"Filter: {label}", "screen shader", "applications-graphics", [os.path.join(HYPR, "display.py"), "filter", key])
    for key, label in (("off", "off"), ("grayscale", "Grayscale"), ("reading", "Reading"),
                       ("vibrance", "Vibrance"), ("crt", "CRT"), ("protanopia", "Protanopia"),
                       ("deuteranopia", "Deuteranopia"), ("tritanopia", "Tritanopia"))
] + [
    (f"Animations: {preset}", "animation preset", "preferences-desktop-display",
     [os.path.join(HYPR, "display.py"), "anim", preset])
    for preset in ("snappy", "smooth", "fancy", "calm", "spring")
] + [
    (f"Theme: {label}", "desktop theme: bar, panels, windows, wallpapers", "preferences-desktop-theme",
     [os.path.join(HYPR, "theme.py"), "set", name])
    for name, label in desktop_theme.themes()
] + [
    ("Theme by time of day: on", "your day and night themes, at the night light's times",
     "preferences-desktop-theme", [os.path.join(HYPR, "theme-schedule.py"), "on"]),
    ("Theme by time of day: off", "keep the theme you pick", "preferences-desktop-theme",
     [os.path.join(HYPR, "theme-schedule.py"), "off"]),
] + [
    (f"{part.capitalize()} theme: {label}", f"the theme the time-of-day schedule uses {when}",
     "preferences-desktop-theme", [os.path.join(HYPR, "theme-schedule.py"), part, name])
    for part, when in (("day", "by day"), ("evening", "in the evening"), ("night", "at night"))
    for name, label in desktop_theme.themes() + [("random", "Random (a different one each time)")]
] + [
    ("Evening theme: off", "no evening theme: the day theme runs until night", "preferences-desktop-theme",
     [os.path.join(HYPR, "theme-schedule.py"), "evening", "off"]),
    ("Theme sounds: on", "the theme's notification and switch sounds", "audio-volume-high",
     [os.path.join(HYPR, "theme-sound.sh"), "on"]),
    ("Theme sounds: off", "silent notifications", "audio-volume-muted",
     [os.path.join(HYPR, "theme-sound.sh"), "off"]),
    ("Theme fade: on", "cross-fade the screens when the theme changes", "preferences-desktop-theme",
     [os.path.join(HYPR, "theme.py"), "fade", "on"]),
    ("Theme fade: off", "switch themes at once", "preferences-desktop-theme",
     [os.path.join(HYPR, "theme.py"), "fade", "off"]),
    ("Save game profile", "remember this screen, rates, HDR, volume and brightness for the running game",
     "applications-games", [os.path.join(HYPR, "game-profiles.py"), "save"]),
    ("Living wallpaper: on", "the moving wallpaper follows CPU load, time of day and weather",
     "preferences-desktop-wallpaper", [os.path.join(HYPR, "wallpaper-motion.py"), "react", "on"]),
    ("Living wallpaper: off", "the moving wallpaper plays as made", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "wallpaper-motion.py"), "react", "off"]),
    ("Screen actions", "drag a box: copy its text, translate, look up, add to calendar  (SUPER+SHIFT+T)",
     "edit-find", [os.path.join(HYPR, "screen-actions.py"), "region"]),
    ("Desktop health check", "every service, timer and check; restarts what failed", "utilities-system-monitor",
     ["sh", "-c", f"{os.path.join(HYPR, 'doctor.py')} --fix >/dev/null; "
                  f"{shlex.quote(NOTIFY)} -a Doctor 'Desktop health' \"$({os.path.join(HYPR, 'doctor.py')} | tail -n 1)\"; "
                  f"{shlex.quote(sys.executable)} {os.path.join(HYPR, 'bar_signals.py')} poke doctor"]),
    ("Errors today", "the desktop's log: errors and warnings from today", "utilities-log-viewer",
     [os.path.expanduser("~/.config/waybar/scripts/panel.py"), "toggle", "logs"]),
    ("Snapshot now", "a system snapshot before you try something (snapper)", "document-save",
     [os.path.join(HYPR, "snapshots.py"), "create", "from the launcher"]),
    ("Restore the last working Hyprland config", "your edited files are kept in ~/.config/hypr/broken-<time>/",
     "edit-undo", [os.path.join(HYPR, "hypr-guard.py"), "restore"]),
    ("Eject USB drives", "unmount and power off every removable drive", "media-eject",
     [os.path.join(HYPR, "automount.py"), "eject", "all"]),
    ("Phone: ring", "find your phone (KDE Connect)", "phone", [os.path.join(HYPR, "phone.py"), "ring"]),
    ("Phone: send the clipboard", "KDE Connect", "phone", [os.path.join(HYPR, "phone.py"), "clip"]),
    ("Phone: open this page on the phone", "the page in the browser you used last, in the phone's browser",
     "phone", [os.path.join(HYPR, "phone.py"), "open"]),
    ("Phone: send a file", "pick files to send to the phone (KDE Connect)", "phone",
     [os.path.join(HYPR, "phone.py"), "file"]),
    ("Phone: send the copied files", "the files copied in Files (Ctrl+C there)", "phone",
     [os.path.join(HYPR, "phone.py"), "file", "--copied"]),
    ("Daily brief", "brief: where you left off, repos, failed services, updates, weather, calendar",
     "x-office-calendar", [os.path.join(HYPR, "brief.py"), "panel"]),
    ("Journal: write today's entry", "journal: what you worked on today, commits, loose ends (local model)",
     "accessories-text-editor", [os.path.join(HYPR, "brief.py"), "journal", "--notify"]),
    ("Journal: open today's entry", "journal in ~/Documents/Journal", "accessories-text-editor",
     [os.path.join(HYPR, "brief.py"), "open"]),
    ("Emergency alerts: drill", "the full alarm, clearly marked as a drill: red screens, siren, voice",
     "dialog-warning", [os.path.join(HYPR, "emergency-alerts.py"), "test"]),
    ("Emergency alerts: silent drill", "the red screens only, no sound", "dialog-warning",
     [os.path.join(HYPR, "emergency-alerts.py"), "test", "--quiet"]),
    ("Make terminal text readable", "less window glass, until the text reads well over any wallpaper",
     "preferences-desktop-theme", [os.path.join(HYPR, "theme.py"), "glass", "fix"]),
    ("Accent: the theme's (drop your own colour)", "type \"accent #ff8800\" to set one",
     "preferences-desktop-theme", [os.path.join(HYPR, "theme-from-wallpaper.py"), "custom", "off"]),
] + [
    ("Accent: follow the wallpaper", "accent from the main screen's wallpaper (if the theme allows)",
     "preferences-desktop-theme", [os.path.join(HYPR, "theme-from-wallpaper.py"), "on"]),
    ("Accent: the theme's own", "stop following the wallpaper", "preferences-desktop-theme",
     [os.path.join(HYPR, "theme-from-wallpaper.py"), "off"]),
    ("Next wallpaper", "all monitors", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "wallpaper-slideshow.py"), "next"]),
    ("Moving wallpaper on / off", "the theme's video wallpaper (matrix's rain)", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "wallpaper-slideshow.py"), "motion", "toggle"]),
    ("Render matrix rain", "make-matrix-rain.py --all (a few minutes)", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "make-matrix-rain.py"), "--all"]),
    ("Render Aero wallpapers", "make-aero-wallpaper.py --all (about 90 s)", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "make-aero-wallpaper.py"), "--all"]),
    ("Render Lo-fi wallpapers", "make-lofi-wallpaper.py --all (about 60 s)", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "make-lofi-wallpaper.py"), "--all"]),
    ("Render Luna wallpapers", "make-luna-wallpaper.py --all (about 90 s)", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "make-luna-wallpaper.py"), "--all"]),
    ("Render Orbit wallpapers", "make-orbit-wallpaper.py --all (space photographs)", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "make-orbit-wallpaper.py"), "--all"]),
    # Measured: --all took 1:25 for 48 frames on four screens, peaking near 550 MB.
    ("Render Seasons wallpapers", "make-seasons-wallpaper.py --all (about 90 s)", "preferences-desktop-wallpaper",
     [os.path.join(HYPR, "make-seasons-wallpaper.py"), "--all"]),
    # 25 originals, one per era of a modern desktop's wallpapers, every screen.
    ("Render Orchard wallpapers", "make-orchard-wallpaper.py --all (25 eras, several minutes)",
     "preferences-desktop-wallpaper", [os.path.join(HYPR, "make-orchard-wallpaper.py"), "--all"]),
    # The seasons theme's own season and hemisphere (theme.py season pin /
    # hemisphere): they re-apply at once if a seasonal theme is current, and
    # are kept for later otherwise.
    ("Season: follow the date", "theme.py season pin auto (seasonal themes)", "weather-few-clouds",
     [os.path.join(HYPR, "theme.py"), "season", "pin", "auto"]),
    ("Season: spring", "hold spring  (theme.py season pin spring)", "weather-few-clouds",
     [os.path.join(HYPR, "theme.py"), "season", "pin", "spring"]),
    ("Season: summer", "hold summer  (theme.py season pin summer)", "weather-clear",
     [os.path.join(HYPR, "theme.py"), "season", "pin", "summer"]),
    ("Season: autumn", "hold autumn  (theme.py season pin autumn)", "weather-overcast",
     [os.path.join(HYPR, "theme.py"), "season", "pin", "autumn"]),
    ("Season: winter", "hold winter  (theme.py season pin winter)", "weather-snow",
     [os.path.join(HYPR, "theme.py"), "season", "pin", "winter"]),
    ("Hemisphere: auto", "from the weather place, else the time zone  (theme.py season hemisphere auto)",
     "find-location", [os.path.join(HYPR, "theme.py"), "season", "hemisphere", "auto"]),
    ("Hemisphere: north", "theme.py season hemisphere north", "find-location",
     [os.path.join(HYPR, "theme.py"), "season", "hemisphere", "north"]),
    ("Hemisphere: south", "theme.py season hemisphere south", "find-location",
     [os.path.join(HYPR, "theme.py"), "season", "hemisphere", "south"]),
    ("Night light on / off", "until the next boundary  (SUPER+N)", "weather-clear-night",
     [os.path.join(HYPR, "nightlight.sh"), "toggle"]),
    ("Record monitor", "start / stop  (ALT+F9)", "media-record", [os.path.join(HYPR, "record.sh"), "monitor"]),
    ("Record region", "start / stop  (ALT+SHIFT+F9)", "media-record", [os.path.join(HYPR, "record.sh"), "region"]),
    ("Instant replay on / off", "(ALT+SHIFT+F10)", "media-record", [os.path.join(HYPR, "record.sh"), "toggle-replay"]),
    ("Record in SDR / HDR", "switch the range  (ALT+CTRL+F9)", "media-record",
     [os.path.join(HYPR, "record.sh"), "toggle-range"]),
    ("Pretty screenshot", "focused window, rounded + shadow  (SUPER+CTRL+S)", "applets-screenshooter",
     [os.path.join(HYPR, "screenshot.sh"), "pretty"]),
    ("Pretty screenshot of a region", "drag a region", "applets-screenshooter",
     [os.path.join(HYPR, "screenshot.sh"), "pretty", "region"]),
    ("Colour picker", "(SUPER+P)", "applications-graphics", [os.path.join(HYPR, "colorpick.sh")]),
    ("Quick note", "(SUPER+SHIFT+N)", "accessories-text-editor", [os.path.join(HYPR, "quicknote.py")]),
    ("Open notes inbox", "~/Documents/Notes/inbox.md", "document-open", [os.path.join(HYPR, "quicknote.py"), "open"]),
    ("Notifications", "history  (SUPER+ALT+N)", "preferences-system-notifications",
     [PANEL, "toggle", "notifications", "--at", "bar-right"]),
    ("Do Not Disturb on / off", "(ALT+SHIFT+D)", "preferences-system-notifications", [os.path.join(BAR, "notifications.py"), "dnd"]),
    ("CPU and memory", "load, RAM, swap and the biggest apps", "utilities-system-monitor",
     [PANEL, "toggle", "cpu", "--at", "bar-right"]),
    ("GPU", "load, VRAM and every app on the GPU", "utilities-system-monitor",
     [PANEL, "toggle", "gpu", "--at", "bar-right"]),
    ("Network", "connections and the apps using them", "network-wired",
     [PANEL, "toggle", "network", "--at", "bar-right"]),
    ("Bluetooth", "paired devices: connect, battery, pair new", "bluetooth-active",
     [PANEL, "toggle", "bluetooth", "--at", "bar-right"]),
    ("Repos", "uncommitted / unpushed work in your projects folder", "applications-development",
     [PANEL, "toggle", "repos", "--at", "bar-right"]),
    ("Disks and shader caches", "usage, clear Steam / driver caches", "drive-harddisk",
     [PANEL, "toggle", "disk", "--at", "bar-right"]),
    ("Sync dotfiles", "copy ~ -> repo, review, commit & push", "emblem-synchronizing",
     ["kitty", "-e", os.path.join(BAR, "dotfiles.py"), "sync"]),
    ("Upgrade the system", "snapshot, dnf, NVIDIA check, flatpak, firmware", "system-software-update",
     ["kitty", "-e", os.path.join(BAR, "safe-upgrade.sh")]),
    ("Work hours: day off today", "free until midnight", "appointment-soon",
     [os.path.join(HYPR, "workhours.py"), "off-today"]),
    ("Work hours: back on", "cancel day off", "appointment-soon", [os.path.join(HYPR, "workhours.py"), "on"]),
    ("Bar cost audit", "CPU and wakeups of every bar script, 30 s", "utilities-system-monitor",
     ["kitty", "-e", "sh", "-c", f"{os.path.join(BAR, 'bar-audit.py')} 30; printf '\\npress Enter '; read x"]),
    ("Shortcuts", "every key bind  (SUPER+F1)", "input-keyboard",
     [PANEL, "toggle", "keybinds", "--at", "bar-right"]),
    ("Lock", "(SUPER+ALT+L)", "system-lock-screen", ["hyprlock"]),
    # The Settings pages' backends: the same commands the pages run.
    ("Copy system info", "the whole About this computer report to the clipboard (no serials or MACs)",
     "help-about", told("System info", [SYSINFO, "copy"])),
    ("Save system report", "About this computer as a text file in ~/Documents", "help-about",
     told("System report saved", [SYSINFO, "save"])),
    ("Over-amplification: on", "volumes up to 150 % (sliders and volume keys)", "audio-volume-high",
     told("Over-amplification", [SOUNDSET, "boost", "on"], ["echo", "on: volumes go up to 150 %"])),
    ("Over-amplification: off", "volumes stop at 100 % (anything louder comes down)", "audio-volume-medium",
     told("Over-amplification", [SOUNDSET, "boost", "off"], ["echo", "off: volumes stop at 100 %"])),
    ("Window blur on / off", "the glass behind windows (your window look)", "preferences-system-windows",
     told("Window blur", [LOOK, "toggle", "blur"], [LOOK, "get", "blur"])),
    ("Window shadows on / off", "your window look", "preferences-system-windows",
     told("Window shadows", [LOOK, "toggle", "shadow"], [LOOK, "get", "shadow"])),
    ("Dim inactive windows on / off", "darken the windows you are not using", "preferences-system-windows",
     told("Dim inactive windows", [LOOK, "toggle", "dim_inactive"], [LOOK, "get", "dim_inactive"])),
    ("Tiling layout: next", "dwindle -> master -> scrolling", "preferences-system-windows",
     told("Tiling layout", [LOOK, "cycle", "layout"], [LOOK, "get", "layout"])),
] + [
    (f"Tiling layout: {label}", "where new windows go and how they share the screen", "preferences-system-windows",
     told("Tiling layout", [LOOK, "set", "layout", key], [LOOK, "get", "layout"]))
    for key, label in (("dwindle", "dwindle"), ("master", "master and stack"), ("scrolling", "scrolling columns"))
] + [
    ("Window look: the theme's", "drop your gaps / borders / blur / layout overrides", "preferences-system-windows",
     told("Window look", [LOOK, "reset"], ["echo", "back to the theme's look"])),
    ("Web browser", "your default browser (Settings > Default apps)", "web-browser",
     [DEFAULT_APPS, "run", "browser"]),
    ("Terminal", "your default terminal  (ALT+Q)", "utilities-terminal", [DEFAULT_APPS, "run", "terminal"]),
    ("Airplane mode on / off", "every radio (Wi-Fi, Bluetooth); the cable keeps working", "airplane-mode",
     told("Airplane mode", [NETSET, "airplane", "toggle"])),
    ("Keep awake: on", "nothing dims, locks or sleeps on idle until you turn it off", "caffeine-cup-full",
     told("Keep awake", [IDLE, "awake", "on"], ["echo", "on until you turn it off"])),
    ("Keep awake: off", "the idle timings again", "caffeine-cup-empty",
     told("Keep awake", [IDLE, "awake", "off"], ["echo", "off: the idle timings again"])),
] + [
    (f"Power profile: {label}", "powerprofilesctl", "preferences-system-power",
     told("Power profile", [IDLE, "profile", key], [IDLE, "profile"]))
    for key, label in (("performance", "performance"), ("balanced", "balanced"), ("power-saver", "power saver"))
] + [
    ("Check for updates", "the updates pill checks now (dnf, flatpak)", "system-software-update",
     [os.path.join(HYPR, "software-updates.py"), "check"]),
    ("Next keyboard layout", "(Super+Space by default)", "input-keyboard",
     [os.path.join(HYPR, "input-settings.py"), "layout", "next"]),
    ("Restore the last notification", "bring back the one just dismissed", "preferences-system-notifications",
     [os.path.join(HYPR, "notify-settings.py"), "restore"]),
    ("Quiet hours: on", "Do Not Disturb by itself every night (Settings > Notifications)",
     "preferences-system-notifications",
     told("Quiet hours", [os.path.join(HYPR, "notify-settings.py"), "set", "quiet", "on"],
          ["echo", "on: Do Not Disturb every night"])),
    ("Quiet hours: off", "no Do Not Disturb at night", "preferences-system-notifications",
     told("Quiet hours", [os.path.join(HYPR, "notify-settings.py"), "set", "quiet", "off"], ["echo", "off"])),
    ("Clock: 24 hours", "the bar's clock: 15:04", "preferences-system-time",
     [os.path.join(HYPR, "region.py"), "set", "clock", "24"]),
    ("Clock: 12 hours", "the bar's clock: 3:04 PM", "preferences-system-time",
     [os.path.join(HYPR, "region.py"), "set", "clock", "12"]),
    # Settings > Accessibility (accessibility.py): each prints the new state,
    # which the notification says.
    ("Magnifier: zoom in", "the screen around the pointer, a quarter more", "zoom-in",
     told("Magnifier", [A11Y, "zoom", "in"])),
    ("Magnifier: zoom out", "a quarter less", "zoom-out", told("Magnifier", [A11Y, "zoom", "out"])),
    ("Magnifier: off", "back to 1x", "zoom-original", told("Magnifier", [A11Y, "zoom", "reset"])),
    ("Screen reader on / off", "Orca, which reads the screen aloud", "preferences-desktop-accessibility",
     told("Screen reader", [A11Y, "reader", "toggle"])),
    ("High contrast on / off", "in GTK4 / libadwaita apps", "preferences-desktop-accessibility",
     told("High contrast", [A11Y, "contrast", "toggle"])),
    ("Reduce motion on / off", "calm animations, no moving wallpaper, no animations in apps",
     "preferences-desktop-accessibility", told("Reduce motion", [A11Y, "motion", "toggle"])),
    ("Reduce transparency on / off", "no window glass or blur, unfocused windows opaque",
     "preferences-desktop-accessibility", told("Reduce transparency", [A11Y, "transparency", "toggle"])),
    ("Visual alerts on / off", "the screens flash for a notification instead of a sound",
     "preferences-desktop-accessibility", told("Visual alerts", [A11Y, "alerts", "toggle"])),
    # Settings > Bar & toolbox, and Users, sharing & printers. bar-settings.py
    # apply is silent: it restarts the bar only when a config file is newer.
    ("Bar: load its changes", "restart the bar if its config changed since it started  (ALT+G restarts it)",
     "preferences-desktop",
     told("Bar", [os.path.join(HYPR, "bar-settings.py"), "apply"], ["echo", "the bar has every change"])),
    ("Change password", "passwd in your terminal (it asks for the old one there)", "dialog-password",
     warned("Change password", [ACCOUNTS, "password"])),
    ("Printers", "add a printer (GNOME's printer settings)", "printer", warned("Printers", [ACCOUNTS, "printers"])),
    ("Online accounts", "GNOME's Online Accounts", "goa-panel", warned("Online accounts", [ACCOUNTS, "online"])),
    # These two run a function, not an argv: ask_chat / claude_tui (below)
    # put the window in a scope of its own, outside launcher.service. The
    # second only with Claude Code installed (command_items).
    ("LLM chat", "the chat window, with the default model  (or type ?)", "internet-chat",
     lambda: ask_chat()),
    ("Claude Code session", "start an interactive claude in kitty, in ~  (Claude Code installed)",
     "utilities-terminal", lambda: claude_tui()),
]
CLAUDE_ONLY = ("Claude Code session",)      # COMMANDS offered only with the claude CLI
CHAT_COMMANDS = ("LLM chat",) + CLAUDE_ONLY  # found by "chat", "llm", "ai" too


def nth(n):
    """2 -> "2nd", 3 -> "3rd", 4 -> "4th", 11 -> "11th" (the focus round
    that gets the long break; settings_pages/timers.py says it the same way)."""
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# -- single instance: a second SUPER+E closes the open one ------------------
def close_running(marker=b"launcher.py"):
    """Shared with clipboard.py, which points PID_FILE at its own file."""
    try:
        with open(PID_FILE) as handle:
            pid = int(handle.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            if marker not in handle.read():
                return False
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ValueError):
        return False


# -- apps and ranking --------------------------------------------------------
def load_usage():
    try:
        with open(USAGE_FILE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def bump_usage(app_id):
    usage = load_usage()
    usage[app_id] = usage.get(app_id, 0) + 1
    try:
        os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
        with open(USAGE_FILE, "w") as handle:
            json.dump(usage, handle)
    except OSError:
        pass


class App:
    glyph = None                # set on items drawn as text (emoji), not icons

    def __init__(self, info):
        self.info = info
        self.id = info.get_id() or ""
        self.name = info.get_display_name() or info.get_name() or self.id
        self.generic = info.get_generic_name() or ""
        self.comment = info.get_description() or ""
        self.keywords = " ".join(info.get_keywords() or [])
        self.exe = os.path.basename(info.get_executable() or "")
        self.lname = self.name.lower()
        self.extra = " ".join((self.generic, self.keywords, self.exe)).lower()

    @property
    def key(self):
        return "app:" + self.id

    def subtitle(self):
        return self.generic or self.comment or self.exe

    def gicon(self):
        return self.info.get_icon() or Gio.ThemedIcon.new("application-x-executable")

    def run(self):
        launch(self)


class Item:
    """Anything in the palette that is not an app: a command, a calculator
    result, a colour, an emoji. Same face as App to the drawing code."""

    def __init__(self, name, sub, icon=None, run=None, glyph=None, extra="", alt=None, confirm=None):
        self.confirm = confirm  # a question: Enter shows it first, then runs on a second Enter
        self.complete = None    # path mode: what Tab puts in the box
        self.goto = None        # Enter puts this in the box instead of running (?models -> ?get)
        self.confirm_sub = None  # the confirm question's line (None: the kill one's)
        self.id = ""
        self.name, self.sub = name, sub
        self.icon, self.glyph, self._run = icon, glyph, run
        self.alt = alt          # Shift+Enter, where there is a second action
        self.row = False        # drawn as a full-width row, not a tile (clipboard text)
        self.key = "item:" + name   # what a pick of it is learned as (learned_order)
        self.lname = name.lower()
        self.extra = (sub + " " + extra).lower()

    def subtitle(self):
        return self.sub

    def gicon(self):
        if isinstance(self.icon, Gio.Icon):
            return self.icon
        if self.icon and os.path.isabs(self.icon):
            return Gio.FileIcon.new(Gio.File.new_for_path(self.icon))
        return Gio.ThemedIcon.new_with_default_fallbacks(self.icon or "system-run")

    def run(self):
        if self._run:
            self._run()


# -- children: started and left to run, but reaped ---------------------------------
# spawn() and launch() start things the launcher does not wait for. Each is
# a child of this process until it ends, and an ended child nobody waits for
# stays a <defunct> zombie -- under the resident launcher (launcher.service,
# up for days) they piled up (a remmina-file-wrapper was seen). So every
# such Popen is kept in _CHILDREN and reap() collects the ended ones: at
# each spawn, at each show, and every REAP_EVERY seconds while the GTK loop
# runs (start_reaper). Polling, not a SIGCHLD handler: a Python handler for
# SIGCHLD would replace GLib's own (GIO's app launching reaps through it),
# and GLib's signal sources cannot watch SIGCHLD. subprocess.run()'s
# children never come here: run() waits for them itself.
_CHILDREN = []
_CHILDREN_LOCK = threading.Lock()   # spawn() may run in a search thread while the loop reaps
REAP_EVERY = 5              # seconds


def remember(proc):
    """Keep a started Popen to be reaped once it ends; returns it."""
    if proc is not None:
        with _CHILDREN_LOCK:
            _CHILDREN.append(proc)
    reap()
    return proc


def reap():
    """Collect the children that have ended (Popen.poll() waits for one
    without blocking). Returns how many were collected."""
    with _CHILDREN_LOCK:
        done = [p for p in _CHILDREN if p.poll() is not None]
        for p in done:
            _CHILDREN.remove(p)
    return len(done)


def start_reaper():
    """reap() every REAP_EVERY seconds from the GTK loop, for as long as it runs."""
    GLib.timeout_add_seconds(REAP_EVERY, lambda: reap() >= 0)


def spawn(argv):
    """Start argv in a session of its own, not waited for (reaped later).
    Returns None, as it always has: callers use it inside GLib callbacks."""
    remember(subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True))


def copy(text):
    try:
        subprocess.run(["wl-copy"], input=text, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def command_items():
    claude = claude_cli() is not None
    return [Item(name, sub, icon, argv, extra=("chat llm ai" if name in CHAT_COMMANDS else "")
                 + (" claude" if name in CLAUDE_ONLY else ""))
            if callable(argv) else Item(name, sub, icon, (lambda a=argv: spawn(a)), extra=" ".join(argv[:2]))
            for name, sub, icon, argv in COMMANDS
            if claude or name not in CLAUDE_ONLY] + model_commands() + mascot_commands()


# -- calculator: arithmetic only, through the AST, never eval() --------------
import ast  # noqa: E402
import math  # noqa: E402
import operator  # noqa: E402

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_NAMES = {k: getattr(math, k) for k in ("pi", "e", "tau")}
_FUNCS = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "log", "log10", "log2",
                                        "exp", "floor", "ceil", "factorial", "radians", "degrees")}
_FUNCS.update(abs=abs, round=round)


def _calc(node):
    if isinstance(node, ast.Expression):
        return _calc(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _calc(node.left), _calc(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.operand))
    if isinstance(node, ast.Name) and node.id in _NAMES:
        return _NAMES[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS and not node.keywords):
        return _FUNCS[node.func.id](*[_calc(a) for a in node.args])
    raise ValueError("not arithmetic")


def calculate(text):
    """The value of an arithmetic expression, or None. Understands ^ as power,
    x as multiply between numbers, commas as thousands, and "N% of M"."""
    expr = text.strip().lower().replace(",", "").replace("^", "**").replace("×", "*")
    expr = re.sub(r"(\d)\s*x\s*(\d)", r"\1*\2", expr)
    expr = re.sub(r"([\d.]+)\s*%\s*of\s*", r"(\1/100)*", expr)
    if not expr or not re.search(r"\d", expr):
        return None
    try:
        value = _calc(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        value = round(value, 10)
        if value.is_integer() and abs(value) < 1e15:
            value = int(value)
    return value


def calc_item(text):
    value = calculate(text)
    if value is None or str(value) == text.strip():
        return None
    shown = f"{value:,}" if isinstance(value, int) else str(value)
    return Item(f"= {shown}", f"{text.strip()}   --   Enter copies {value}", "accessories-calculator",
                lambda v=str(value): copy(v))


# -- colours and emoji ---------------------------------------------------------
def colour_items():
    try:
        out = subprocess.run([os.path.join(HYPR, "colorpick.sh"), "history"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    swatches = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "colorpick")
    items = []
    for hexa in out.split():
        swatch = os.path.join(swatches, hexa.lstrip("#") + ".png")
        if not os.path.exists(swatch):
            try:
                subprocess.run(["magick", "-size", "64x64", f"xc:{hexa}", swatch],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass            # no swatch: the generic icon below
        r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
        items.append(Item(hexa, f"rgb({r}, {g}, {b})", swatch if os.path.exists(swatch) else "applications-graphics",
                          lambda h=hexa: spawn([os.path.join(HYPR, "colorpick.sh"), "copy", h])))
    if not items:
        items.append(Item("No colours yet", "pick one with SUPER+P", "applications-graphics",
                          lambda: spawn([os.path.join(HYPR, "colorpick.sh")])))
    return items


_EMOJI = None


def emoji_items(query):
    global _EMOJI
    import unicodedata
    if _EMOJI is None:
        _EMOJI = []
        for cp in list(range(0x1F300, 0x1FAFF)) + list(range(0x2600, 0x27C0)):
            try:
                _EMOJI.append((chr(cp), unicodedata.name(chr(cp)).lower()))
            except ValueError:
                pass
    words = query.lower().split()
    hits = [(ch, name) for ch, name in _EMOJI if all(w in name for w in words)]
    hits.sort(key=lambda h: (not any(h[1].startswith(w) for w in words), len(h[1])))
    return [Item(name.capitalize(), f"U+{ord(ch):04X}   --   Enter copies it", glyph=ch,
                 run=lambda c=ch: copy(c)) for ch, name in hits[:MAX_TILES + 1]]


# -- open windows --------------------------------------------------------------
def focus_window(address):
    # The Lua dispatcher: `dispatch focuswindow` is a syntax error under this
    # Lua config (window-switcher.py says more).
    spawn(["hyprctl", "dispatch", f"hl.dsp.focus({{ window = 'address:{address}' }})"])


def window_items():
    """Every mapped window, most recently focused first. Read once, when the
    launcher opens: nothing else can change them while it has the keyboard."""
    try:
        clients = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True,
                                            text=True, timeout=1).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    # A window's class is its .desktop id more often than not, in either case.
    by_id = {(i.get_id() or "").lower().removesuffix(".desktop"): i for i in Gio.AppInfo.get_all()}
    items = []
    for c in sorted((c for c in clients if c.get("mapped")), key=lambda c: c.get("focusHistoryID", 0)):
        cls = c.get("class") or ""
        info = by_id.get(cls.lower())
        app = info.get_display_name() if info else (cls.rsplit(".", 1)[-1] or "window")
        icon = (info.get_icon() if info else None) or Gio.ThemedIcon.new_with_default_fallbacks(
            cls.lower() or "window")
        ws = c.get("workspace", {}).get("name", "").removeprefix("special:")
        item = Item(c.get("title") or app, f"switch to it   --   {app}, workspace {ws}", icon,
                    lambda a=c["address"]: focus_window(a), extra=f"{cls} {app}")
        item.address, item.key = c["address"], "win:" + cls     # the title changes; the class not
        items.append(item)
    return items


def window_action(address, *actions):
    """Focus the window at `address`, then dispatch each Lua action on it
    (Hyprland's window actions work on the active window)."""
    lua = f"hl.dispatch(hl.dsp.focus({{ window = 'address:{address}' }}))"
    for act in actions:
        lua += f"; hl.dispatch({act})"
    spawn(["hyprctl", "eval", lua])


WINDOW_ACT_RE = re.compile(r"(move|mover|send|bring|traer|close|cerrar)\s+(.+?)"
                           r"(?:\s+(?:to|a|al|en)\s+(?:workspace\s+|ws\s+)?(\S+))?", re.I)


def window_action_items(text):
    """"move firefox to 3", "bring steam", "close kitty" -- for each window
    whose class or title has the name."""
    m = WINDOW_ACT_RE.fullmatch(text.strip())
    if not m:
        return []
    verb, want, ws = m[1].lower(), m[2].lower(), m[3]
    if verb in ("move", "mover", "send") and not ws:
        return []
    try:
        clients = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True,
                                            text=True, timeout=1).stdout)
        active_ws = json.loads(subprocess.run(["hyprctl", "activeworkspace", "-j"], capture_output=True,
                                              text=True, timeout=1).stdout).get("id")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    items = []
    for c in sorted(clients, key=lambda c: c.get("focusHistoryID", 0)):
        if not c.get("mapped") or not (want in (c.get("class") or "").lower() or want in (c.get("title") or "").lower()):
            continue
        addr, title = c["address"], (c.get("title") or c.get("class") or "window")[:60]
        where = c.get("workspace", {}).get("name", "?")
        if verb in ("move", "mover", "send"):
            go = f"hl.dsp.window.move({{ workspace = '{ws}', follow = false }})"
            follow = f"hl.dsp.window.move({{ workspace = '{ws}', follow = true }})"
            items.append(Item(f"Move to {ws}:  {title}", f"now on workspace {where}   --   Enter: send it, "
                              "Shift+Enter: send it and follow", "window-new",
                              lambda a=addr, g=go: window_action(a, g), alt=lambda a=addr, f=follow: window_action(a, f)))
        elif verb in ("bring", "traer"):
            here = f"hl.dsp.window.move({{ workspace = '{active_ws}', follow = true }})"
            items.append(Item(f"Bring here:  {title}", f"from workspace {where} to {active_ws}   --   Enter: bring it",
                              "window-new", lambda a=addr, h=here: window_action(a, h)))
        else:
            items.append(Item(f"Close:  {title}", f"workspace {where}   --   Enter: close it (it may ask to save)",
                              "window-close", lambda a=addr: window_action(a, "hl.dsp.window.close()")))
    return items or [Item(f"No window matches \u201c{want}\u201d", "nothing to do", "window-close")]


# -- files ---------------------------------------------------------------------
HOME = os.path.expanduser("~")
FILE_LIMIT = 12
FILE_SKIP = ("/node_modules/", "/__pycache__/", "/site-packages/", "/steamapps/")


def file_item(path):
    try:
        icon = Gio.File.new_for_path(path).query_info(
            "standard::icon", Gio.FileQueryInfoFlags.NONE, None).get_icon()
    except GLib.Error:
        icon = None
    where = os.path.dirname(path).replace(HOME, "~", 1)
    item = Item(os.path.basename(path), f"{where}   --   Shift+Enter: show in Files",
                icon or "text-x-generic", lambda p=path: spawn(["gio", "open", p]),
                alt=lambda p=path: spawn(["nautilus", "--select", p]))
    item.path, item.key = path, "file:" + path
    return item


def recent_files(words):
    """GTK's recently used files whose name has every word, newest first."""
    hits = []
    for info in Gtk.RecentManager.get_default().get_items():
        uri = info.get_uri()
        if not uri.startswith("file://") or not info.exists():
            continue
        name = info.get_display_name().lower()
        if all(w in name for w in words):
            hits.append((info.get_modified(), GLib.filename_from_uri(uri)[0]))
    return [path for _, path in sorted(hits, reverse=True)]


def find_files(query):
    """Paths under ~ matching every word of `query`, best first. Slow-ish
    (~0.1 s): called from a thread."""
    words = query.lower().split()
    if len(query.strip()) < 3:
        return []
    try:
        out = subprocess.run(["plocate", "-i", "-b", "-0", "-l", "20000", max(words, key=len)],
                             capture_output=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    whole = query.strip().lower()
    scored = []
    for raw in out.split(b"\0"):
        path = raw.decode(errors="replace")
        if not path.startswith(HOME + "/") or any(skip in path for skip in FILE_SKIP):
            continue
        rel = path[len(HOME) + 1:]
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        low = rel.lower()
        if not all(w in low for w in words):
            continue
        base = os.path.basename(low)
        rank_ = (0 if base.startswith(whole) else 1 if whole in base else 2)
        scored.append((rank_, rel.count("/"), len(base), path))
    scored.sort()
    # The index is a day old at worst: drop what has gone since.
    return [p for *_, p in scored[:FILE_LIMIT * 2] if os.path.exists(p)][:FILE_LIMIT]


# -- long text: keep it ----------------------------------------------------------
LONG_TEXT = 50
SAVE_DIR = os.path.join(HOME, "Documents", "Notes", "saved")


def is_long(text):
    return len(text.strip()) > LONG_TEXT or "\n" in text.strip()


def save_text(text, open_after=False):
    """Write `text` to SAVE_DIR/<date>-<first words>.txt; notify or open it."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    slug = "-".join(re.findall(r"\w+", text.lower())[:6])[:48] or "text"
    stem = os.path.join(SAVE_DIR, time.strftime("%Y-%m-%d-%H%M-") + slug)
    path, n = stem + ".txt", 2
    while os.path.exists(path):
        path, n = f"{stem}-{n}.txt", n + 1
    with open(path, "w") as handle:
        handle.write(text.strip("\n") + "\n")
    if open_after:
        spawn(["gio", "open", path])
    else:
        spawn([NOTIFY, "-a", "Launcher", "-i", "document-save", "Saved",
               path.replace(HOME, "~", 1)])


def add_to_inbox(text):
    import quicknote        # here, not at the top: quicknote imports this file
    # One markdown list item: continuation lines indented under it.
    quicknote.append("\n  ".join(line.rstrip() for line in text.strip().splitlines()))
    spawn([NOTIFY, "-a", "Launcher", "-i", "accessories-text-editor", "Added to the notes inbox",
           quicknote.INBOX.replace(HOME, "~", 1)])


def long_text_items(text):
    body = text.strip()
    words, lines = len(body.split()), body.count("\n") + 1
    size = f"{words} words" + (f", {lines} lines" if lines > 1 else "")
    where = SAVE_DIR.replace(HOME, "~", 1)
    return [
        Item("Save as a text file", f"{size}   --   into {where}/", "document-save",
             lambda: save_text(body), alt=lambda: save_text(body, open_after=True)),
        Item("Save and open it", f"the same file, then open it in the editor", "document-open",
             lambda: save_text(body, open_after=True)),
        Item("Add to notes inbox", "~/Documents/Notes/inbox.md (the quick-note list)",
             "accessories-text-editor", lambda: add_to_inbox(body)),
    ]


# -- conversions (qalc) ------------------------------------------------------------
HOME_CURRENCIES = ["MXN", "USD"]     # where a bare "20 gbp" is converted to
RATES = os.path.join(HOME, ".local", "share", "qalculate", "rates.json")
CONVERT_RE = re.compile(r"^\s*(-?[\d.,]+\s*[^\d\s].*?)\s+(?:to|->|→|=)\s+(\S.*?)\s*$", re.I)
CONVERT_IN_RE = re.compile(r"^\s*(-?[\d.,]+\s*[^\d\s].*?)\s+in\s+(\S+)\s*$", re.I)
MONEY_RE = re.compile(r"^(?:[A-Z]{3}\s?|[A-Z]{0,3}[$€£¥₿₩₹₽])?-?[\d.,]+(?:E[−-]?\d+)?(?:\s?[A-Z]{3})?$")
# Single letters a launcher means as temperatures, not farads and coulombs.
TEMPERATURE = {"f": "°F", "c": "°C", "k": "K"}
_CURRENCIES = None


def currencies():
    """Codes qalc has a rate for (its rates.json), else the common ones."""
    global _CURRENCIES
    if _CURRENCIES is None:
        try:
            with open(RATES) as handle:
                _CURRENCIES = {c.upper() for c in json.load(handle).get("eur", {})} | {"EUR"}
        except (OSError, ValueError):
            _CURRENCIES = set("USD EUR MXN GBP JPY CAD CHF CNY BRL ARS COP CLP BTC ETH".split())
    return _CURRENCIES


def refresh_rates():
    """qalc's rates, again if a day old: in a thread, once per launcher."""
    try:
        if time.time() - os.path.getmtime(RATES) < 86400:
            return
    except OSError:
        pass

    def work():
        try:
            subprocess.run(["qalc", "-e", "-t", "1"], capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
    threading.Thread(target=work, daemon=True).start()


def unit(text):
    text = text.strip()
    return TEMPERATURE.get(text.lower(), text)


def qalc(expr, want):
    """qalc's answer to `expr`, or None unless it is in unit `want`."""
    try:
        done = subprocess.run(["qalc", "-t", "-s", "precision 7", expr], capture_output=True,
                              text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    answer = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""
    if done.returncode or not answer:
        return None
    if want.upper() in currencies():
        # Printed by symbol when it has one ("$26.90"), so the test is the
        # shape of an amount ("10 kittens to usd" is "27.18i μs·t²").
        if not MONEY_RE.match(answer):
            return None
        # Money in cents ("$26.65757" -> "$26.66"); under one, 4 figures.
        def cents(m):
            v = float(m[0].replace(",", ""))
            return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4g}"
        return re.sub(r"[\d.,]*\d", cents, answer, count=1)
    return answer if want.lower() in answer.lower() else None


def answer_item(answer, question):
    # The number alone is what gets pasted somewhere: "MXN 1849.273" -> 1849.273
    number = re.sub(r"[^\d.,\-eE+−]", " ", answer).split()
    value = number[0].replace("−", "-").replace(",", "") if number else answer
    return Item(f"= {answer}", f"{question}   --   Enter copies {value}", "accessories-calculator",
                lambda v=value: copy(v), alt=lambda a=answer: copy(a))


# -- currency ----------------------------------------------------------------------
# Read straight from qalc's rates file (refresh_rates keeps it a day fresh),
# not through qalc: no process per keystroke, any phrasing below, and the
# rate's date to show. Codes are lower-case keys there, valued per 1 EUR.
DOLLAR_SIGN = "usd"     # what a bare "$" means ("mxn" if "$30" should be pesos)
CURRENCY_WORDS = {
    "usd": "dollar dollars dólar dolar dólares dolares bucks us$ usd$",
    "mxn": "peso pesos mx$ mxn$",
    "eur": "euro euros €",
    "gbp": "pound pounds libra libras £",
    "jpy": "yen ¥",
    "cny": "yuan rmb renminbi",
    "krw": "won ₩",
    "inr": "rupee rupees rupia rupias ₹",
    "brl": "reais r$",
    "cad": "c$ ca$",
    "aud": "a$ au$",
    "chf": "franc francs franco francos",
    "btc": "bitcoin bitcoins ₿",
    "eth": "ether ethereum",
}
CURRENCY_PAIRS = {"pesos mexicanos": "mxn", "peso mexicano": "mxn", "canadian dollar": "cad",
                  "canadian dollars": "cad", "us dollar": "usd", "us dollars": "usd",
                  "dólares americanos": "usd", "dolares americanos": "usd"}
CONNECTORS = {"to", "in", "into", "as", "en", "a", "=", "->", "→", "=>"}
SYMBOLS = "$€£¥₩₹₿"
_RATES = (None, None, None)      # (mtime, date, {code: per EUR})


def rates():
    """(date, {code: units per 1 EUR}), re-read when qalc rewrites the file."""
    global _RATES
    try:
        mtime = os.path.getmtime(RATES)
        if mtime != _RATES[0]:
            with open(RATES) as handle:
                data = json.load(handle)
            table = {k.lower(): float(v) for k, v in data.get("eur", {}).items()}
            table["eur"] = 1.0
            _RATES = (mtime, data.get("date", ""), table)
    except (OSError, ValueError, TypeError):
        return "", {}
    return _RATES[1], _RATES[2]


def money(value):
    """1,234.56 -- or 4 significant figures under 1 (0.05408, 0.00001373)."""
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4g}"


def amount_text(value):
    """What was typed, as typed: 30, 1,500, 2.5 -- no .00 added."""
    return f"{value:,.0f}" if value == int(value) else f"{value:,.10g}"


def parse_currency(query):
    """(amount or None, from, to or None) in lower-case codes, or None.
    "30 usd to mxn", "MXN to USD", "$30", "30usd", "1,500 pesos en dólares",
    "2.5k eur", "dollars to pesos"; a lone currency (no amount, no second
    one) only as a code in CAPITALS ("USD"), so "real" or "won" typed as a
    search stays a search."""
    date, table = rates()
    if not table:
        return None
    words = {w: code for code, names in CURRENCY_WORDS.items() for w in names.split()}
    s = query.strip().lower()
    for pair, code in CURRENCY_PAIRS.items():
        s = s.replace(pair, f" {code} ")
    s = re.sub(rf"([{SYMBOLS}])", r" \1 ", s)                     # "$30" -> "$ 30"
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s)                       # "30usd" -> "30 usd"
    s = re.sub(r"\b(\d[\d,]*(?:\.\d+)?) ([km])\b", r"\1\2", s)   # "2.5 k" -> "2.5k"
    amount, codes, joined = None, [], False
    for tok in s.split():
        num = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?|\.\d+)([km]?)", tok)
        # The amount goes before its currency or right after it ("$30",
        # "30$", "usd 30"), never after the "to".
        if num and amount is None and len(codes) <= 1 and not joined:
            amount = float(num[1].replace(",", "")) * {"": 1, "k": 1e3, "m": 1e6}[num[2]]
        elif tok in CONNECTORS and len(codes) == 1:
            joined = True
        elif tok == "$":
            codes.append(DOLLAR_SIGN)
        elif tok in words:
            codes.append(words[tok])
        elif tok in table and (len(tok) == 3 or tok in ("usdt", "usdc")):
            codes.append(tok)
        else:
            return None
    if not codes or len(codes) > 2 or (len(codes) == 2 and codes[0] == codes[1]):
        return None
    if amount is None and len(codes) == 1 and query.strip().upper() != query.strip():
        return None
    if any(c not in table for c in codes):
        return None
    return amount, codes[0], codes[1] if len(codes) == 2 else None


def currency_items(text):
    parsed = parse_currency(text)
    if not parsed:
        return []
    amount, src, dst = parsed
    date, table = rates()
    homes = [h.lower() for h in HOME_CURRENCIES]
    targets = [dst] if dst else [h for h in homes if h != src]
    old = ""
    try:
        import datetime
        if (datetime.date.today() - datetime.date.fromisoformat(date)).days > 3:
            old = " (old: run qalc -e)"
    except ValueError:
        pass
    items = []
    for to in targets:
        rate = table[to] / table[src]
        value = (amount or 1) * rate
        line = f"{amount_text(amount or 1)} {src.upper()} = {money(value)} {to.upper()}"
        plain = money(value).replace(",", "")
        sub = (f"1 {src.upper()} = {money(rate)} {to.upper()}  ·  1 {to.upper()} = {money(1 / rate)} "
               f"{src.upper()}  ·  rates {date}{old}   --   Enter copies {plain}, Shift+Enter the line")
        items.append(Item(line, sub, "accessories-calculator",
                          lambda v=plain: copy(v), alt=lambda t=line: copy(t)))
        if dst and amount is None:
            # "MXN to USD": the rate, and the way back as the next tile.
            back = f"1 {to.upper()} = {money(1 / rate)} {src.upper()}"
            items.append(Item(back, f"the other way  ·  rates {date}{old}", "accessories-calculator",
                              lambda v=money(1 / rate).replace(",", ""): copy(v), alt=lambda t=back: copy(t)))
    return items


def conversion_items(text):
    query = text.strip()
    money_answer = currency_items(query)
    if money_answer:
        return money_answer
    match = CONVERT_RE.match(query) or CONVERT_IN_RE.match(query)
    if match:
        source, target = match.groups()
        # "100 f" -> "100 °F": the unit is whatever follows the number.
        source = re.sub(r"^(-?[\d.,]+)\s*([a-z])$", lambda m: f"{m[1]} {unit(m[2])}", source.strip(), flags=re.I)
        target = unit(target)
        answer = qalc(f"{source} to -{target}", target)
        return [answer_item(answer, query)] if answer else []
    return []


# -- market quotes (Yahoo Finance) --------------------------------------------------
TICKER_RE = re.compile(r"^\^?[A-Z][A-Z0-9]{1,5}([.\-=][A-Z0-9]{1,4})?$")
YAHOO_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
QUOTE_LIMIT = 4


def wants_quotes(text):
    """Capitals as typed ("NVDA", "WALMEX.MX", "^GSPC") or "$ name"."""
    query = text.strip()
    return bool(TICKER_RE.match(query)) or (query.startswith("$") and len(query) > 2)


def yahoo(url):
    request = urllib.request.Request(url, headers=YAHOO_UA)
    with urllib.request.urlopen(request, timeout=4) as answer:
        return json.load(answer)


def find_quotes(text):
    """[(symbol, name, exchange, price, currency, change %)], best first.
    Called from a thread."""
    query = text.strip().lstrip("$").strip()
    try:
        found = yahoo("https://query2.finance.yahoo.com/v1/finance/search?newsCount=0&quotesCount=6&q="
                      + urllib.parse.quote(query)).get("quotes", [])
    except (OSError, ValueError):
        return []
    out = []
    for hit in [h for h in found if h.get("symbol")][:QUOTE_LIMIT]:
        try:
            meta = yahoo(f"https://query1.finance.yahoo.com/v8/finance/chart/"
                         f"{urllib.parse.quote(hit['symbol'])}?range=1d&interval=1d")["chart"]["result"][0]["meta"]
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
        price, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose")
        change = (price - prev) / prev * 100 if price and prev else None
        out.append((hit["symbol"], hit.get("longname") or hit.get("shortname") or hit["symbol"],
                    hit.get("exchDisp") or meta.get("fullExchangeName", ""), price,
                    meta.get("currency", ""), change))
    return out


def quote_items(quotes, webs):
    items = []
    for symbol, name, exchange, price, currency, change in quotes:
        if price is None:
            continue
        move = "" if change is None else f"   {'▲' if change >= 0 else '▼'} {abs(change):.2f}%"
        url = f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}"
        items.append(Item(f"{symbol}   {price:,.2f} {currency}{move}",
                          f"{name}  ·  {exchange}   --   Enter: Yahoo Finance, Shift+Enter copies {price}",
                          "x-office-spreadsheet",
                          (lambda u=url: open_in(webs[0], u)) if webs else None,
                          extra=name, alt=lambda p=price: copy(str(p))))
    return items


# -- clipboard history (cliphist, as clipboard.py) ----------------------------------
CLIP_LIMIT = 6


def clip_history():
    """[(cliphist line, one-line preview)] for the text entries, newest first."""
    try:
        out = subprocess.run(["cliphist", "list"], capture_output=True, text=True,
                             errors="replace", timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        _, _, preview = line.partition("\t")
        if preview and not preview.startswith("[[ binary data"):
            rows.append((line, " ".join(preview.split())))
    return rows


def clip_copy(line):
    try:
        data = subprocess.run(["cliphist", "decode"], input=line.encode(), capture_output=True,
                              timeout=3).stdout
        subprocess.run(["wl-copy"], input=data, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def clip_items(rows, text):
    words = [w for w in text.lower().split() if len(w) >= 2]
    if len(text.strip()) < 3 or not words:
        return []       # one letter is in every entry
    hits = [(line, preview) for line, preview in rows if all(w in preview.lower() for w in words)]
    items = [Item(preview[:300], f"clipboard history   --   Enter copies it ({len(preview)} characters)",
                  "edit-paste", lambda l=line: clip_copy(l)) for line, preview in hits[:CLIP_LIMIT]]
    for item in items:
        item.row = True
    return items


def inline_emoji(text):
    """A few emoji for the main search: names with a word STARTING with each
    typed word, so "fire" gives the flame, not every name that contains it."""
    words = text.lower().split()
    if len(text.strip()) < 3 or len(words) > 3:
        return []
    hits = [i for i in emoji_items(text)
            if all(any(n.startswith(w) for n in i.lname.split()) for w in words)]
    return hits[:6]


# -- places (make-places.py's offline GeoNames index) ------------------------------
PLACES = os.path.join(HOME, ".local", "share", "launcher", "places.tsv")
AIRPORTS = os.path.join(HOME, ".local", "share", "launcher", "airports.tsv")
AIRPORT_WORDS = {"airport", "airports", "aeropuerto", "aeropuertos", "aeroport", "aeroporto",
                 "flughafen", "aer", "aero"}
PLACE_LIMIT = 3
PLACE_PREFIX = 5        # chars before a query also matches the START of a name


def place_key(text):
    """make-places.py's norm(): lower case, accents off, punctuation -> spaces."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


class Places:
    """The index, loaded in a thread when the launcher opens (~0.5 s for
    70k places); `ready` is False until then, and a missing file just means
    no place suggestions."""

    def __init__(self, on_ready=None):
        self.on_ready = on_ready    # called (in the GTK thread) once loaded
        self.ready = False
        self.by_key = {}
        self.keys = []
        self.by_code = {}       # "MEX" -> airport row
        self.by_city = {}       # "mexico city" -> [airport rows]
        # After the window is up: the load holds Python's lock for ~0.5 s,
        # and started at once it pushed the launcher's first frame back by
        # about that much. A city typed in the first half second just shows
        # up a moment later.
        GLib.timeout_add(120, lambda: threading.Thread(target=self.load, daemon=True).start() and False)

    def load(self):
        import bisect  # noqa: F401  (used by prefix())
        by_key = {}
        try:
            with open(PLACES) as handle:
                for line in handle:
                    keys, name, state, country, pop, lat, lon, *tz = line.rstrip("\n").split("\t")
                    row = (name, state, country, int(pop or 0), lat, lon, tz[0] if tz else "")
                    for key in keys.split("|"):
                        by_key.setdefault(key, []).append(row)
        except (OSError, ValueError):
            return
        try:
            with open(AIRPORTS) as handle:
                for line in handle:
                    code, name, city, country, rank, lat, lon, keys = line.rstrip("\n").split("\t")
                    row = (code, name, city, country, int(rank), lat, lon)
                    self.by_code[code] = row
                    for key in keys.split("|"):
                        self.by_city.setdefault(key, []).append(row)
        except (OSError, ValueError):
            pass
        self.keys = sorted(by_key)
        self.by_key = by_key
        self.ready = True
        if self.on_ready:
            GLib.idle_add(lambda: self.on_ready() and False)

    def airports(self, text):
        """Airports the query asks for: a code in capitals, a code or a
        city with an airport word, biggest first. [] if it does not ask."""
        if not self.ready:
            return []
        raw = text.strip()
        if re.fullmatch(r"[A-Z]{3}", raw):
            return [self.by_code[raw]] if raw in self.by_code and raw.lower() not in rates()[1] else []
        words = place_key(raw).split()
        rest = [w for w in words if w not in AIRPORT_WORDS]
        if len(rest) == len(words) or not rest:
            return []
        rest = " ".join(rest)
        if len(rest) == 3 and rest.upper() in self.by_code:
            return [self.by_code[rest.upper()]]
        rows = list(self.by_city.get(rest, []))
        if not rows:
            # A place's other names: "cdmx airport" -> Mexico City's airports.
            for place in self.by_key.get(rest, [])[:3]:
                rows += self.by_city.get(place_key(place[0]), [])
        seen, out = set(), []
        for row in sorted(rows, key=lambda r: -r[4]):
            if row[0] not in seen:
                seen.add(row[0])
                out.append(row)
        return out[:6]

    def prefix(self, key):
        import bisect
        i = bisect.bisect_left(self.keys, key)
        rows = []
        while i < len(self.keys) and self.keys[i].startswith(key) and len(rows) < 400:
            rows += self.by_key[self.keys[i]]       # "springf" -> Springfield, while typing
            i += 1
        return rows

    def find(self, text):
        """Places for `text`, biggest first: an exact name, else "name
        qualifier" / "name, qualifier" (a state or country, from its start),
        else -- PLACE_PREFIX characters on -- names that START with it."""
        if not self.ready:
            return []
        query = place_key(text)
        if len(query) < 4:
            return []           # "san" is a town too -- and the start of every search
        rows = list(self.by_key.get(query, []))
        if not rows:
            words = query.split()
            for i in range(len(words) - 1, 0, -1):
                head, tail = " ".join(words[:i]), " ".join(words[i:])
                rows = [r for r in self.by_key.get(head, [])
                        if place_key(r[1]).startswith(tail) or place_key(r[2]).startswith(tail)]
                if rows:
                    break
        if not rows and len(query) >= PLACE_PREFIX:
            rows = self.prefix(query)
        seen, out = set(), []
        for row in sorted(rows, key=lambda r: -r[3]):
            if (row[0], row[1], row[2]) not in seen:
                seen.add((row[0], row[1], row[2]))
                out.append(row)
        return out[:PLACE_LIMIT]


def airport_items(text, places, webs):
    if places is None or is_long(text):
        return []
    maps = next((i for i in Gio.AppInfo.get_all_for_type("x-scheme-handler/geo")
                 if i.get_id() == "org.gnome.Maps.desktop"), None) or \
        Gio.AppInfo.get_default_for_type("x-scheme-handler/geo", False)
    kind = {3: "large airport", 2: "airport", 1: "small airport"}     # make-places.py: rank // 2
    items = []
    for code, name, city, country, rank, lat, lon in places.airports(text):
        flights = "https://www.google.com/travel/flights?q=" + urllib.parse.quote(f"flights from {code}")
        what = kind.get(rank // 2, "airport") + ("" if rank % 2 else ", no scheduled flights")
        items.append(Item(f"{code}  {name}",
                          f"{city}, {country}  ·  {what}   --   Enter: map, Shift+Enter: flights from {code}",
                          (maps.get_icon() if maps else None) or "find-location",
                          (lambda u=f"geo:{lat},{lon}": open_in(maps, u)) if maps else None,
                          alt=(lambda u=flights: open_in(webs[0], u)) if webs else None))
    return items


# -- time zones (the place index's zones, Python's zoneinfo) -------------------------
# The abbreviations people type. Ambiguous ones read the common way: CST is
# the US/Mexico Central time (America/Chicago and Mexico City agree in winter
# only -- Mexico dropped DST in 2022; "cdmx" or "chicago" is exact), IST
# India's.
ZONE_ABBR = {"utc": "UTC", "gmt": "UTC", "z": "UTC",
             "est": "America/New_York", "edt": "America/New_York", "et": "America/New_York",
             "cst": "America/Chicago", "cdt": "America/Chicago", "ct": "America/Chicago",
             "mst": "America/Denver", "mdt": "America/Denver", "mt": "America/Denver",
             "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles", "pt": "America/Los_Angeles",
             "cet": "Europe/Paris", "cest": "Europe/Paris", "bst": "Europe/London",
             "jst": "Asia/Tokyo", "kst": "Asia/Seoul", "ist": "Asia/Kolkata",
             "aest": "Australia/Sydney", "aedt": "Australia/Sydney"}
TIME_WORDS = {"time", "hora", "clock", "now"}
TIME_RE = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"


def zone_of(text, places):
    """(label, ZoneInfo) for a place or a zone abbreviation, or None."""
    from zoneinfo import ZoneInfo
    key = place_key(text)
    if key in ("here", "local", "aqui"):
        return "here", None
    if key in ZONE_ABBR:
        return key.upper(), ZoneInfo(ZONE_ABBR[key])
    if places is not None:
        for name, state, country, *_rest, tz in places.find(text)[:1]:
            if tz:
                return name, ZoneInfo(tz)
    return None


def clock(dt):
    return dt.strftime("%H:%M  %a %d %b").replace(" 0", " ")


def offset(dt):
    off = dt.utcoffset().total_seconds() / 3600
    return f"UTC{off:+g}".replace("+0", "+0")


def ahead(dt):
    """'3 h ahead of you' / 'same time as you'."""
    import datetime
    local = datetime.datetime.now().astimezone()
    diff = (dt.utcoffset() - local.utcoffset()).total_seconds() / 3600
    if diff == 0:
        return "same time as you"
    return f"{abs(diff):g} h {'ahead of' if diff > 0 else 'behind'} you"


def time_items(text, places):
    import datetime
    if text[:1] in "=>#:$!" or is_long(text):
        return []
    q = text.strip().lower()
    out = []
    # "time in tokyo", "tokyo time", "hora en madrid", "time cdmx"
    m = re.fullmatch(r"(?:time|hora|clock|now)\s+(?:in\s+|en\s+|at\s+)?(.+)", q) or \
        re.fullmatch(r"(.+?)\s+(?:time|hora|now)", q)
    if m:
        zone = zone_of(m[1], places)
        if zone and zone[1] is not None:
            label, tz = zone
            now = datetime.datetime.now(tz)
            out.append(Item(f"{label}  {clock(now)}", f"{tz.key}  ·  {offset(now)}  ·  {ahead(now)}"
                            f"   --   Enter copies {now:%H:%M}", "preferences-system-time",
                            lambda v=f"{now:%H:%M}": copy(v)))
        return out
    # "3pm toluca to london", "15:00 tokyo", "9:30am EST in cdmx"
    m = re.fullmatch(TIME_RE + r"\s+(.+?)(?:\s+(?:to|in|en|a|->)\s+(.+))?", q)
    if not m:
        return []
    hour, minute, ampm, src, dst = int(m[1]), int(m[2] or 0), (m[3] or "").replace(".", ""), m[4], m[5]
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return []
    if not ampm and not m[2]:
        return []           # "3 tokyo" is not a time; "3pm" or "15:00" is
    a, b = zone_of(src, places), zone_of(dst, places) if dst else ("here", None)
    if not a or not b or a[1] is None and b[1] is None:
        return []
    local = datetime.datetime.now().astimezone().tzinfo
    today = datetime.datetime.now(a[1] or local).date()
    start = datetime.datetime(today.year, today.month, today.day, hour, minute, tzinfo=a[1] or local)
    end = start.astimezone(b[1] or local)
    day = {0: "", 1: " (next day)", -1: " (day before)"}.get((end.date() - start.date()).days, "")
    line = f"{start:%H:%M} {a[0]} = {end:%H:%M} {b[0]}{day}"
    out.append(Item(line, f"{(a[1] or local)} {offset(start)}  ->  {(b[1] or local)} {offset(end)}"
                    f"   --   Enter copies {end:%H:%M}", "preferences-system-time",
                    lambda v=f"{end:%H:%M}": copy(v), alt=lambda t=line: copy(t)))
    return out


# -- weather (wttr.in, for a place from the index) ----------------------------------
WEATHER_RE = re.compile(r"(?:weather|clima|tiempo|forecast|pron[oó]stico)\s+(?:in\s+|en\s+|de\s+|for\s+)?(.+)"
                        r"|(.+?)\s+(?:weather|clima|forecast|pron[oó]stico)", re.I)
_WEATHER = {}           # place label -> (time, answer): 15 minutes


def wants_weather(text):
    return bool(WEATHER_RE.fullmatch(text.strip()))


def weather_items(text, places, webs):
    """Called from the slow-search thread: one wttr.in request, at most."""
    m = WEATHER_RE.fullmatch(text.strip())
    if not m or places is None:
        return []
    found = places.find(m[1] or m[2])
    if not found:
        return []
    name, state, country, _pop, lat, lon, _tz = found[0]
    label = ", ".join(x for x in (name, state, country) if x)
    cached = _WEATHER.get(label)
    if cached and time.time() - cached[0] < 900:
        data = cached[1]
    else:
        try:
            req = urllib.request.Request(f"https://wttr.in/{lat},{lon}?format=j1",
                                         headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=6) as answer:
                data = json.load(answer)
        except (OSError, ValueError):
            return [Item(f"Weather in {name}", "wttr.in did not answer -- try again in a moment",
                         "weather-severe-alert")]
        _WEATHER[label] = (time.time(), data)
    page = "https://wttr.in/" + urllib.parse.quote(f"{name}, {country}")
    run = (lambda: open_in(webs[0], page)) if webs else None
    try:
        now = data["current_condition"][0]
        days = data["weather"]
        desc = now["weatherDesc"][0]["value"].strip()
        today = days[0]
        items = [Item(f"{name}  {now['temp_C']}°C  {desc}",
                      f"feels {now['FeelsLikeC']}°  ·  wind {now['windspeedKmph']} km/h  ·  "
                      f"humidity {now['humidity']}%  ·  today {today['mintempC']}–{today['maxtempC']}°"
                      f"   --   Enter: full forecast", "weather-few-clouds", run)]
        for day in days[1:3]:
            when = time.strftime("%a %d", time.strptime(day["date"], "%Y-%m-%d"))
            noon = day["hourly"][min(4, len(day["hourly"]) - 1)]["weatherDesc"][0]["value"].strip()
            items.append(Item(f"{when}  {day['mintempC']}–{day['maxtempC']}°", f"{noon}  ·  {label}",
                              "weather-few-clouds", run))
        return items
    except (KeyError, IndexError, ValueError):
        return []


# -- dates --------------------------------------------------------------------------
MONTHS = {}
for _i, _names in enumerate(("jan january ene enero", "feb february febrero", "mar march marzo",
                             "apr april abr abril", "may mayo", "jun june junio", "jul july julio",
                             "aug august ago agosto", "sep sept september septiembre",
                             "oct october octubre", "nov november noviembre",
                             "dec december dic diciembre"), start=1):
    for _n in _names.split():
        MONTHS[_n] = _i
# Named days (this year's; "days until" moves a past one to next year).
NAMED_DATES = {"christmas": (12, 25), "xmas": (12, 25), "navidad": (12, 25), "nochebuena": (12, 24),
               "christmas eve": (12, 24), "new year": (1, 1), "new years": (1, 1), "ano nuevo": (1, 1),
               "new years eve": (12, 31), "fin de ano": (12, 31), "halloween": (10, 31),
               "dia de muertos": (11, 2), "dia de los muertos": (11, 2),
               "independencia": (9, 16), "16 septiembre": (9, 16), "valentines": (2, 14),
               "valentines day": (2, 14), "san valentin": (2, 14)}
UNITS = {"day": "days", "days": "days", "dia": "days", "dias": "days", "d": "days",
         "week": "weeks", "weeks": "weeks", "semana": "weeks", "semanas": "weeks", "w": "weeks",
         "month": "months", "months": "months", "mes": "months", "meses": "months",
         "year": "years", "years": "years", "ano": "years", "anos": "years", "y": "years"}


def parse_date(text):
    """A date in a few spellings, or None: today/hoy, tomorrow/mañana,
    yesterday/ayer, 2026-12-24, 24/12/2026 (day first), dec 24, 24 dec,
    24 de diciembre (de) 2026; a year left out is this one."""
    import datetime
    today = datetime.date.today()
    named = place_key(text)
    if named in NAMED_DATES:                    # before " de " goes: "dia de muertos"
        mo, d = NAMED_DATES[named]
        return datetime.date(today.year, mo, d)
    t = named.replace(" de ", " ").replace(" del ", " ")
    rel = {"today": 0, "hoy": 0, "now": 0, "tomorrow": 1, "manana": 1, "yesterday": -1, "ayer": -1}
    if t in rel:
        return today + datetime.timedelta(days=rel[t])
    m = re.fullmatch(r"(\d{4}) (\d{1,2}) (\d{1,2})", t)           # 2026-12-24
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.fullmatch(r"(\d{1,2}) (\d{1,2}) (\d{4})", t)        # 24/12/2026
        if m:
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
        else:
            m = re.fullmatch(r"([a-z]+) (\d{1,2})(?: (\d{4}))?", t) or \
                re.fullmatch(r"(\d{1,2}) ([a-z]+)(?: (\d{4}))?", t)
            if not m:
                return None
            a, b = m[1], m[2]
            month, d = (MONTHS.get(a), int(b)) if a.isalpha() else (MONTHS.get(b), int(a))
            if not month:
                return None
            y, mo = int(m[3]) if m[3] else today.year, month
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def shift(date, n, unit):
    import calendar
    import datetime
    if unit == "days":
        return date + datetime.timedelta(days=n)
    if unit == "weeks":
        return date + datetime.timedelta(weeks=n)
    months = n * (12 if unit == "years" else 1)
    y, m = divmod(date.month - 1 + months, 12)
    y += date.year
    return date.replace(year=y, month=m + 1, day=min(date.day, calendar.monthrange(y, m + 1)[1]))


def describe(date):
    import datetime
    days = (date - datetime.date.today()).days
    unit = lambda n: f"{n:,} day" + ("" if n == 1 else "s")  # noqa: E731
    when = "today" if days == 0 else f"in {unit(days)}" if days > 0 else f"{unit(-days)} ago"
    return f"{when}  ·  week {date.isocalendar()[1]}"


def date_item(date, question):
    iso = date.isoformat()
    return Item(date.strftime("%a %d %b %Y").replace(" 0", " "),
                f"{question}  ·  {describe(date)}   --   Enter copies {iso}", "x-office-calendar",
                lambda v=iso: copy(v))


def date_items(text):
    import datetime
    if text[:1] in "=>#:$!" or is_long(text):
        return []
    q = text.strip().lower()
    t = place_key(q)
    today = datetime.date.today()
    if re.fullmatch(r"1\d{9}", q):                                  # Unix time
        dt = datetime.datetime.fromtimestamp(int(q))
        return [Item(dt.strftime("%a %d %b %Y  %H:%M:%S").replace(" 0", " "),
                     f"Unix time {q}  ·  {describe(dt.date())}   --   Enter copies {dt.isoformat(' ')}",
                     "x-office-calendar", lambda v=dt.isoformat(" "): copy(v))]
    m = re.fullmatch(r"(?:week|semana)(?: (\d{1,2}))?(?: (\d{4}))?", t)
    if m:
        year = int(m[2]) if m[2] else today.year
        week = int(m[1]) if m[1] else today.isocalendar()[1]
        try:
            mon = datetime.date.fromisocalendar(year, week, 1)
        except ValueError:
            return []
        sun = mon + datetime.timedelta(days=6)
        return [Item(f"Week {week}:  {mon:%a %d %b} – {sun:%a %d %b %Y}".replace(" 0", " "),
                     f"ISO week {week} of {year}  ·  {describe(mon)}   --   Enter copies {mon.isoformat()}",
                     "x-office-calendar", lambda v=mon.isoformat(): copy(v))]
    m = re.fullmatch(r"(?:days? until|days? till|dias? hasta|cuantos dias para) (.+)", t)
    if m and parse_date(m[1]):
        date = parse_date(m[1])
        if date < today and not re.search(r"\d{4}", m[1]):
            date = date.replace(year=date.year + 1)                  # "dec 24" in late December
        return [date_item(date, f"{(date - today).days:,} days until")]
    m = re.fullmatch(r"(?:days? since|dias? desde) (.+)", t)
    if m and parse_date(m[1]):
        date = parse_date(m[1])
        return [date_item(date, f"{(today - date).days:,} days since")]
    m = re.fullmatch(r"(?:days? between|dias? entre) (.+?) (?:and|y) (.+)", t)
    if m and parse_date(m[1]) and parse_date(m[2]):
        a, b = parse_date(m[1]), parse_date(m[2])
        n = abs((b - a).days)
        return [Item(f"{n:,} days", f"{a:%d %b %Y} to {b:%d %b %Y}  ·  {n / 7:.1f} weeks   --   Enter copies {n}",
                     "x-office-calendar", lambda v=str(n): copy(v))]
    m = re.fullmatch(r"(.+?) ([+-]) (\d+) ([a-z]+)", q.replace("+", " + ").replace(" - ", " - ").replace("  ", " "))
    if m and parse_date(m[1]) and place_key(m[4]) in UNITS:
        n = int(m[3]) * (1 if m[2] == "+" else -1)
        return [date_item(shift(parse_date(m[1]), n, UNITS[place_key(m[4])]), q)]
    if re.search(r"\d", t) or t in ("today", "hoy", "tomorrow", "manana", "yesterday", "ayer") \
            or t in NAMED_DATES:
        date = parse_date(q)
        if date and not re.fullmatch(r"[a-z]+ \d{1,2}", t) or (date and t.split()[0] in MONTHS):
            return [date_item(date, q)]
    return []


# -- tools: colours, number bases, uuid, passwords -------------------------------------
def swatch(hexa):
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "colorpick", hexa.lstrip("#") + ".png")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            subprocess.run(["magick", "-size", "64x64", f"xc:{hexa}", path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass                # no swatch: the generic icon
    return path if os.path.exists(path) else "applications-graphics"


def colour_tool(q):
    import colorsys
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", q)
    if m:
        h = m[1] if len(m[1]) == 6 else "".join(c * 2 for c in m[1])
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    else:
        m = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)", q)
        if not m or max(int(x) for x in m.groups()) > 255:
            return []
        r, g, b = (int(x) for x in m.groups())
    hexa = f"#{r:02x}{g:02x}{b:02x}"
    hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    forms = [hexa, f"rgb({r}, {g}, {b})", f"hsl({hh * 360:.0f}, {ss * 100:.0f}%, {ll * 100:.0f}%)"]
    icon = swatch(hexa)
    return [Item(f, "colour  ·  " + "  ·  ".join(x for x in forms if x != f) + f"   --   Enter copies {f}",
                 icon, lambda v=f: copy(v)) for f in forms]


def base_tool(q):
    m = re.fullmatch(r"0x([0-9a-f]+)|0b([01]+)|0o([0-7]+)", q)
    value = None
    if m:
        value = int(m[0], 0)
    else:
        m = re.fullmatch(r"(\d+)\s+(?:to|in|en|a)\s+(hex|bin|oct|dec|binary|octal|decimal)", q) or \
            re.fullmatch(r"(hex|bin|oct|binary|octal)\s+(\d+)", q)
        if m:
            value = int(m[1] if m[1].isdigit() else m[2])
    if value is None:
        return []
    forms = [(f"{value:,}", str(value), "decimal"), (hex(value), hex(value), "hex"),
             (f"0b{value:b}", f"0b{value:b}", "binary"), (oct(value), oct(value), "octal")]
    return [Item(shown, f"{what}  ·  {q}   --   Enter copies {copied}", "accessories-calculator",
                 lambda v=copied: copy(v)) for shown, copied, what in forms]


_WORDS = None


def password_tool(q):
    import secrets
    import string
    m = re.fullmatch(r"(?:password|pass|pw|contrase(?:n|ñ)a)(?:\s+(\d{1,3}))?", q)
    if not m:
        return []
    n = max(8, min(128, int(m[1] or 20)))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+?"
    while True:     # at least one of each kind, or it is not the password asked for
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw)):
            break
    items = [Item(pw, f"random, {n} characters (letters, digits, symbols)   --   Enter copies it",
                  "dialog-password", lambda v=pw: copy(v))]
    global _WORDS
    if _WORDS is None:
        try:
            with open("/usr/share/dict/words") as handle:
                _WORDS = [w.strip().lower() for w in handle if re.fullmatch(r"[a-z]{4,8}", w.strip())]
        except OSError:
            _WORDS = []
    if _WORDS:
        phrase = "-".join(secrets.choice(_WORDS) for _ in range(5)) + f"-{secrets.randbelow(100)}"
        items.append(Item(phrase, "passphrase: 5 random words and a number   --   Enter copies it",
                          "dialog-password", lambda v=phrase: copy(v)))
    return items


def tool_items(text):
    import uuid
    if text[:1] in "=>:!" or is_long(text):
        return []
    q = text.strip().lower()
    if q in ("uuid", "guid"):
        u = str(uuid.uuid4())
        return [Item(u, "a random UUID (v4)   --   Enter copies it", "accessories-text-editor",
                     lambda v=u: copy(v))]
    return colour_tool(q) or base_tool(q) or password_tool(q)


# -- paths ------------------------------------------------------------------------------
PATH_LIMIT = 40


def path_items(text):
    """Entries of the folder typed so far that start with its last part:
    "~/Doc" -> ~/Documents/, "/etc/hy" -> /etc/hyprland... Folders first;
    dot-files only once a "." is typed."""
    full = os.path.expanduser(text)
    folder, part = os.path.split(full)
    folder = folder or "/"
    try:
        names = os.listdir(folder)
    except OSError:
        return [Item("No such folder", folder.replace(HOME, "~", 1), "dialog-warning")]
    show = lambda n: n.lower().startswith(part.lower()) and (part.startswith(".") or not n.startswith("."))  # noqa: E731
    rows = []
    for n in names:
        if show(n):
            path = os.path.join(folder, n)
            rows.append((not os.path.isdir(path), n.lower(), n, path))
    rows.sort()
    items = []
    if not part and os.path.isdir(full):
        # The folder itself first: Enter on "~/Downloads/" opens it.
        items.append(Item(os.path.basename(full.rstrip("/")) or "/", f"{full.replace(HOME, '~', 1)}   --   "
                          "Enter: open in Files, Shift+Enter: terminal here", "folder",
                          lambda p=full: spawn(["gio", "open", p]),
                          alt=lambda p=full: spawn(["kitty", "--directory", p])))
    for is_file, _low, n, path in rows[:PATH_LIMIT]:
        shown = path.replace(HOME, "~", 1)
        if is_file:
            item = file_item(path)
        else:
            item = Item(n + "/", f"{shown}   --   Tab: into it, Enter: open in Files, Shift+Enter: terminal here",
                        "folder", lambda p=path: spawn(["gio", "open", p]),
                        alt=lambda p=path: spawn(["kitty", "--directory", p]))
            item.complete = (text[:len(text) - len(part)] if part else text) + n + "/"
        items.append(item)
    return items or [Item("Nothing here starts with that", folder.replace(HOME, "~", 1), "folder")]


# -- running commands and ending processes --------------------------------------------
def run_items(cmd):
    if not cmd:
        return [Item("Run a command", "type it after the !: !htop, !du -sh ~/Downloads", "utilities-terminal")]
    term = ["kitty", "--hold", "sh", "-c", cmd]
    return [Item(f"Run:  {cmd}", "in kitty, kept open when it ends   --   Shift+Enter: in the background, "
                 "no terminal", "utilities-terminal", lambda: spawn(term),
                 alt=lambda: spawn(["sh", "-c", cmd]))]


# -- the LLM chat window (llm-chat.py), or Claude Code's TUI in kitty -----------------
LLM_CHAT = os.path.join(HYPR, "llm-chat.py")
CHAT_ICON = "internet-chat"     # the theme's chat bubble


def claude_cli():
    """The `claude` executable, or None when Claude Code is not installed
    (llm_models.claude_cli: $PATH, then ~/.local/bin -- a session started by
    systemd, launcher.service, need not have ~/.local/bin on its PATH)."""
    return llm_models.claude_cli()


def is_claude(model):
    """Does `model` (None: the default) run through Claude Code?"""
    model = model or llm_models.chosen("default")
    return model is not None and model.kind == "claude"


def tui_ok(model):
    """Shift+Enter's "Claude Code in kitty": a Claude model, claude installed."""
    return is_claude(model) and claude_cli() is not None


def prompt_arg(prompt):
    """`prompt` as one argv element neither argparse (the chat window) nor
    claude's option parser can take for a flag: "-v is broken?" gets a
    leading space, which both pass through as text."""
    return " " + prompt if prompt.startswith("-") else prompt


def in_scope(argv):
    """`argv` in a systemd scope of its own, as uwsm starts every app. A plain
    spawn() leaves the child in launcher.service's cgroup (setsid is a POSIX
    session, not a cgroup), and the unit's KillMode=control-group then ends
    it with the launcher: a `systemctl --user restart launcher`, or a crash
    and Restart=on-failure, would close every chat window, end a reply in
    the middle and take its commands and terminals along. Without uwsm,
    systemd-run makes the same kind of scope."""
    if shutil.which("uwsm"):
        return ["uwsm", "app", "--"] + argv
    if shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "--quiet", "--"] + argv
    return argv


def short(path):
    """~ for the home folder, as everywhere in this file's lines."""
    return path.replace(HOME, "~", 1) if path == HOME or path.startswith(HOME + "/") else path


def ask_chat(prompt="", cwd=None, resume=None, model=None, images=()):
    """The chat window: a new conversation (prompt, and pictures), or
    `resume` continued, in `cwd` (the window's own default, ~, without
    one), with `model` (an llm_models.Model; None: the window's default,
    llm.json's)."""
    spawn(in_scope(chat_argv(prompt, cwd, resume, model, images)))


def chat_argv(prompt="", cwd=None, resume=None, model=None, images=()):
    return (["python3", LLM_CHAT] + ([prompt_arg(prompt)] if prompt else [])
            + (["--cwd", cwd] if cwd else []) + (["--resume", resume] if resume else [])
            + (["--model", model.name] if model else [])
            + [a for path in images for a in ("--image", path)])


def tui_argv(prompt="", cwd=None, resume=None, model=None):
    """kitty running `claude` there (a Claude model, Claude Code installed;
    no model: llm.json's default). No shell is involved."""
    model = model or llm_models.chosen("default")
    tail = (["--resume", resume] if resume else []) + ([prompt_arg(prompt)] if prompt else [])
    head = ["kitty", "--class", "claude-tui", "-d", cwd or HOME]
    return head + [claude_cli() or "claude"] + llm_models.launch_spec(model) + tail


def claude_tui(prompt="", cwd=None, resume=None, model=None):
    if not tui_ok(model):
        notify("Claude Code's terminal UI is for a Claude model, with Claude Code installed")
        return
    spawn(in_scope(tui_argv(prompt, cwd, resume, model)))


def model_note(model):
    """"  ·  gemma-4-e4b (local)" for an item's line: the model typed, else
    the default."""
    model = model or llm_models.chosen("default")
    if model is None:
        return "  ·  no model (LM Studio has none)"
    return f"  ·  {model.name}" + {"local": "  (local)", "server": "  (server)"}.get(model.kind, "")


def asked(model):
    """Who an item asks: the model typed, else the default -- "Ask
    gemma-4-e4b: …", "Ask Opus: …" ("Claude" for Claude Code's own default,
    "the AI" with no model at all)."""
    model = model or llm_models.chosen("default")
    if model is None:
        return "the AI"
    if model.kind == "claude":
        return "Claude" if model.name == "default" else model.label
    return model.label if model.kind == "server" else model.name


def tui_hint(model):
    return "   --   Shift+Enter: Claude Code in kitty" if tui_ok(model) else ""


def chat_item(prompt, name=None, cwd=None, model=None):
    """One "Ask …" item: Enter the chat window (Shift+Enter Claude Code's
    TUI, for a Claude model with claude installed)."""
    shown = " ".join(prompt.split())
    return Item(name or f"Ask {asked(model)}: {shown}",
                f"in the LLM chat window, in {short(cwd or HOME)}{model_note(model)}{tui_hint(model)}",
                CHAT_ICON, lambda: ask_chat(prompt, cwd, model=model), extra="ask chat llm ai",
                alt=(lambda: claude_tui(prompt, cwd, model=model)) if tui_ok(model) else None)


def tui_session_items(prompt="", cwd=None, model=None):
    """"Start a Claude Code session": the interactive `claude` in kitty, in
    ~ (or the ?@ folder), with the prompt as its first message when there
    is one -- only for a Claude model, Claude Code installed; [] else."""
    if not tui_ok(model):
        return []
    shown = " ".join(prompt.split())
    return [Item(f"Start a Claude Code session: {shown}" if shown else "Start a Claude Code session",
                 f"the interactive claude in kitty, in {short(cwd or HOME)}{model_note(model)}",
                 "utilities-terminal", lambda: claude_tui(prompt, cwd, model=model), extra="claude")]


# Models: "?gemma why is my build slow" -- a model's name as the first word
# after ?, ?? or ?@folder picks it for that question (llm_models.split_model:
# an LM Studio model's alias or the unambiguous start of one, server:ID, and
# -- Claude Code installed -- Claude's aliases or a full claude-… id); any
# other first word is just the prompt's.
def set_model(key, model):
    try:
        llm_models.save_setting(key, model.name)
    except OSError as exc:
        notify(f"could not save {llm_models.SETTINGS}: {exc}")
        return
    notify(f"{'Quick answers now use' if key == 'quick' else 'The chat now uses'} {model.name}")


def models_view():
    """[(Model, is default, is quick)] in the registry's order."""
    models = llm_models.all_models()
    default, quick = llm_models.chosen("default", models), llm_models.chosen("quick", models)
    return [(m, m == default, m == quick) for m in models]


def model_commands():
    """"Chat model: X" and "Quick model: X" for > commands, the current one
    marked; Enter makes it the one."""
    out = []
    for key, title, what in (("default", "Chat model", "for ? and the chat window"),
                             ("quick", "Quick model", "for ?? quick answers")):
        for model, is_default, is_quick in models_view():
            if key == "quick" and model.ident is None:
                continue        # "no --model" is no answer to "which fast one"
            current = is_default if key == "default" else is_quick
            kind = "LM Studio, local" if model.local else "Claude Code"
            out.append(Item(f"{title}: {model.name}" + ("  ✓" if current else ""),
                            f"{'the one now' if current else 'Enter: use it'} {what}  ·  {kind}"
                            + (f"  ·  {model.detail}" if model.detail else ""),
                            "emblem-default" if current else CHAT_ICON,
                            lambda k=key, m=model: set_model(k, m),
                            extra=f"model llm ai chat {model.label}"))
    return out


MASCOT_SWITCHES = (("enabled", "moods"), ("random_only", "random moods only"),
                   ("talk", "reacts to the conversation"), ("weather", "reacts to the weather"),
                   ("time", "reacts to the time of day"),
                   ("calendar", "reacts to the calendar and holidays"),
                   ("workhours", "reacts to work hours"),
                   ("pc", "reacts to your PC (music, games, heat)"),
                   ("chance", "random mood changes"),
                   # mascot_mood.REACTION_GROUPS
                   ("greetings", "greetings (hello, welcome back, waking up)"),
                   ("notices", "notices your prompt (a picture, code, a long one)"),
                   ("feelings", "feelings (thanks, errors, a fix, a long run)"),
                   ("work", "reacts to the work (tests, commits, quick or busy runs)"),
                   ("stage", "reacts to clicks (pokes and pats)"),
                   # reduce_motion: the first sets it here, the second is "auto"
                   ("reduce_motion", "reduce motion"),
                   ("motion_auto", "reduce motion follows the desktop"))


def mascot_value(cur, key):
    """A MASCOT_SWITCHES key's state in mascot_mood.read_settings() terms:
    reduce_motion is the answer in effect (the desktop's while it follows
    it), motion_auto whether it follows."""
    import mascot_mood
    if key == "reduce_motion":
        return mascot_mood.reduced_motion(cur)
    if key == "motion_auto":
        return cur["reduce_motion"] == "auto"
    if key in cur["reactions"]:
        return cur["reactions"][key]
    return cur.get(key, cur["signals"].get(key))


def set_mascot(key, value, text):
    import mascot_mood
    try:
        if key == "motion_auto":
            # off: keep what the desktop says now, set here from then on
            mascot_mood.save_settings(reduce_motion="auto" if value else mascot_mood.reduced_motion())
        else:
            mascot_mood.save_settings(**{key: value})
    except (OSError, ValueError) as exc:
        notify(f"could not save the mascot settings: {exc}")
        return
    notify(f"Mascot: {text} {'on' if value else 'off'}")


def mascot_commands():
    """"Mascot: <switch>" for > commands, ticked when on; Enter flips it.
    An open chat window reads the change within a minute (its Ctrl+J menu
    at once)."""
    try:
        import mascot_mood
        cur = mascot_mood.read_settings()
    except Exception:
        return []
    out = []
    for key, text in MASCOT_SWITCHES:
        value = mascot_value(cur, key)
        out.append(Item(f"Mascot: {text}" + ("  ✓" if value else ""),
                        f"{'on' if value else 'off'}  ·  Enter: turn it {'off' if value else 'on'}"
                        "  ·  the chat window's mascot",
                        "emblem-default" if value else CHAT_ICON,
                        lambda k=key, v=not value, t=text: set_mascot(k, v, t),
                        extra="mascot mood chat"))
    return out


def model_items(query=""):
    """?models: every model (with words: those with them all in the name,
    label or id); Enter the default for ? and the chat window, Shift+Enter
    the quick one for ??. Last, an item that turns the box into ?get <words>."""
    items = []
    words = query.lower().split()
    for model, is_default, is_quick in models_view():
        if not all(w in f"{model.name} {model.label} {model.ident or ''}".lower() for w in words):
            continue
        marks = ", ".join(w for w, on in (("for ?", is_default), ("for ??", is_quick)) if on)
        kind = "LM Studio (local)" if model.local else "Claude Code"
        items.append(Item(model.name + (f"   ✓ {marks}" if marks else ""),
                          f"{kind}  ·  {model.label}" + (f"  ·  {model.detail}" if model.detail else "")
                          + "   --   Enter: the default, Shift+Enter: for ?? answers",
                          "emblem-default" if marks else CHAT_ICON,
                          lambda m=model: set_model("default", m),
                          alt=(lambda m=model: set_model("quick", m)) if model.ident else None,
                          extra="model llm ai"))
    if not words and not any(m.local for m, _, _ in models_view()):
        items.append(Item("No local models", "LM Studio's `lms ls` found none (or has not been "
                          "asked yet: it is, in the background, when the launcher opens)",
                          "dialog-information"))
    find = Item(f"Search downloads for {query}" if query else "Find models to download",
                "GGUF models on Hugging Face, downloaded with LM Studio   --   Enter (or Tab): "
                f"?get {query}".rstrip(), "folder-download", extra="model download")
    find.goto = find.complete = f"?get {query}" if query else "?get "
    return items + [find]


def refresh_models():
    """`lms ls` again in a thread when the model folders changed: a second
    or more of node, never in the way of typing."""
    if llm_models.stale():
        threading.Thread(target=llm_models.refresh, daemon=True).start()


# Downloads: "?get qwen coder" (or "?download ...") -- GGUF repos on Hugging
# Face for the words, most downloaded first, LM Studio's own lmstudio-community
# quantizations raised, downloaded with `lms get` (llm_models.get, in a scope
# of its own). Asked HF_DELAY ms after typing stops, in a thread (the
# Launcher's plan_hf), kept per query for the session in HF_CACHE; results()
# only draws what is there.
HF_API = "https://huggingface.co/api/models"
HF_DELAY = 500              # ms after the last key
HF_LIMIT = 24               # repos asked for
HF_PICKS = 6                # lmstudio-community repos asked for, alongside
HF_SIZED = 6                # top repos whose file sizes are asked (one request each)
HF_EXPAND = ("downloads", "likes", "lastModified", "tags", "gguf", "siblings")
HF_CACHE = {}               # query -> {"rows": [...], "error": str} (rows: dicts, ranked)
GET_WORDS = ("get", "download")
DISK_SPARE = 10e9           # bytes left free after a download, or Enter asks first
# The variant downloaded: the first of these the repo has (Q4_K_M: the usual
# best size for the quality), and its bits per weight, to guess a size
# before the real one is in.
QUANTS = (("Q4_K_M", 4.85), ("Q4_K_S", 4.6), ("IQ4_XS", 4.3), ("Q4_0", 4.55), ("Q5_K_M", 5.7),
          ("Q5_K_S", 5.55), ("Q6_K", 6.6), ("Q8_0", 8.5), ("Q3_K_L", 4.3), ("Q3_K_M", 3.9),
          ("IQ3_M", 3.7), ("Q2_K", 3.0), ("BF16", 16.0), ("F16", 16.0))
QUANT_RE = re.compile(r"(?:^|[-_.])(I?Q\d(?:_[A-Z0-9]{1,2})+|BF16|F16|F32)(?=$|[-_.])", re.I)
_HW = {}                    # "vram", "ram": bytes, asked once (in the search thread)


def hf_query(text):
    """The words after ?get / ?download, "" for none, None when it is not
    that mode. `text` is all that followed the ?."""
    first, _, rest = text.strip().partition(" ")
    return rest.strip() if first.lower() in GET_WORDS else None


def ram_bytes():
    """MemTotal from /proc/meminfo, in bytes (32 GB if it cannot be read)."""
    try:
        with open("/proc/meminfo") as handle:
            return int(handle.readline().split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 32e9


def vram_bytes(card, ram):
    """The memory a model can be loaded into on the GPU, from gpu.py's
    primary() card: its vram_total (MiB); no card, or an integrated one
    (vram_total None, or an AMD APU's small carve-out with discrete False:
    it shares the RAM) -> the RAM itself."""
    card = card or {}
    total = card.get("vram_total")
    return total * 1024 ** 2 if total and card.get("discrete") is not False else ram


def hardware():
    """{"vram", "ram"} in bytes: gpu.py's main card (any maker; in-process,
    nothing forked), /proc/meminfo. Blocking once (~50 ms): the search thread."""
    if not _HW:
        ram = ram_bytes()
        try:
            import gpu
            card = gpu.primary()
        except Exception:  # noqa: BLE001 -- no card info is the no-card answer
            card = None
        _HW.update(vram=vram_bytes(card, ram), ram=ram)
    return _HW


def quant_of(path):
    """"Q4_K_M" for ".../Model-Q4_K_M-00001-of-00002.gguf", None for a file
    that is no model's weights (mmproj, imatrix) or names no quantization."""
    base = os.path.basename(path)
    if not base.lower().endswith(".gguf") or re.search(r"mmproj|imatrix", base, re.I):
        return None
    hits = QUANT_RE.findall(split_base(base))
    return hits[-1].upper() if hits else None


def split_base(path):
    """A file's name without .gguf and a split's "-00001-of-00003": one
    name for all the parts of one file."""
    return re.sub(r"-\d{5}-of-\d{5}$", "", os.path.basename(path)[:-5])


def hf_get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "launcher.py (hyprland desktop)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def hf_row(repo):
    """One search answer, cut down to what an item needs."""
    files = [s.get("rfilename", "") for s in repo.get("siblings") or []]
    quants = {q for q in map(quant_of, files) if q}
    variant = next((q for q, _ in QUANTS if q in quants), None)
    params = (repo.get("gguf") or {}).get("total") or 0
    if not params:              # "Qwen2.5-7B-Instruct-GGUF": the name's own count
        hit = re.search(r"(?:^|[-_])(\d+(?:\.\d+)?)[Bb](?:[-_]|$)", repo["id"].split("/")[-1])
        params = float(hit.group(1)) * 1e9 if hit else 0
    bpw = dict(QUANTS).get(variant)
    return {"id": repo["id"], "downloads": repo.get("downloads") or 0, "likes": repo.get("likes") or 0,
            "modified": repo.get("lastModified") or "", "params": params, "variant": variant,
            "guess": params * bpw / 8 if params and bpw else 0, "size": 0,
            "moe": (re.search(r"[-_](A\d+(?:\.\d+)?B)(?:[-_]|$)", repo["id"], re.I) or [None, None])[1],
            "pick": repo["id"].lower().startswith("lmstudio-community/"),
            "gguf": any(f.lower().endswith(".gguf") for f in files)}


def hf_rank(rows):
    """Most downloaded first, a lmstudio-community repo counted as eight
    times its downloads (LM Studio's own, tested quantizations of the
    model), repos without a .gguf file or a known variant last."""
    def weight(row):
        return row["downloads"] * (8 if row["pick"] else 1) * (1 if row["gguf"] else 0.01) \
            * (1 if row["variant"] else 0.2)
    return sorted(rows, key=weight, reverse=True)


def hf_search(query, on_update=lambda: None):
    """Ask Hugging Face for `query` and fill HF_CACHE[query]; then the file
    sizes of the top HF_SIZED (in parallel), on_update() after each phase.
    Blocking (~0.2 s + ~0.2 s): a thread. Two requests for the search --
    the most downloaded GGUF repos, and lmstudio-community's -- side by side."""
    expand = "".join(f"&expand[]={e}" for e in HF_EXPAND)
    base = f"{HF_API}?search={urllib.parse.quote(query)}&filter=gguf&sort=downloads{expand}"
    answers, errors = {}, []

    def ask(key, url):
        try:
            answers[key] = hf_get(url)
        except (OSError, ValueError) as exc:
            errors.append(str(getattr(exc, "reason", exc)))

    threads = [threading.Thread(target=ask, args=("all", f"{base}&limit={HF_LIMIT}")),
               threading.Thread(target=ask, args=("picks", f"{base}&limit={HF_PICKS}&author=lmstudio-community"))]
    for t in threads:
        t.start()
    hardware()
    for t in threads:
        t.join()
    if "all" not in answers:
        HF_CACHE[query] = {"rows": [], "error": errors[0] if errors else "no answer"}
        on_update()
        return HF_CACHE[query]
    seen, rows = set(), []
    for repo in answers.get("picks", []) + answers["all"]:
        if isinstance(repo, dict) and repo.get("id") and repo["id"] not in seen:
            seen.add(repo["id"])
            rows.append(hf_row(repo))
    entry = HF_CACHE[query] = {"rows": hf_rank(rows), "error": ""}
    on_update()

    def size(row):
        try:
            tree = hf_get(f"{HF_API}/{row['id']}/tree/main?recursive=true")
            sets = {}           # one file, or its split parts, per name: some repos have two
            for f in tree:      # of a variant (with / without MTP, single / split)
                if isinstance(f, dict) and f.get("type") == "file" and \
                        quant_of(f.get("path", "")) == row["variant"]:
                    key = os.path.dirname(f["path"]) + "/" + split_base(f["path"]) \
                        + ("#split" if re.search(r"-\d{5}-of-\d{5}\.gguf$", f["path"]) else "")
                    sets[key] = sets.get(key, 0) + (f.get("size") or 0)
            row["size"] = max(sets.values(), default=0)    # the biggest: disk and VRAM erring safe
        except (OSError, ValueError):
            pass
    threads = [threading.Thread(target=size, args=(row,)) for row in entry["rows"][:HF_SIZED]
               if row["variant"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if threads:
        on_update()
    return entry


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def count(n):
    for size, unit in ((1e6, "M"), (1e3, "k")):
        if n >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + unit
    return str(n)


def fit(size):
    """vs this machine: the weights plus ~1.5 GB of context in VRAM, or
    split with system RAM (half of it), or not at all."""
    if not _HW:
        ram = ram_bytes()
    hw = _HW or {"vram": ram, "ram": ram}      # before hardware() has run: as if no card
    if size + 1.5e9 <= hw["vram"]:
        return "fits GPU"
    if size <= hw["vram"] + hw["ram"] / 2:
        return "partial offload"
    return "too big"


def start_download(repo, variant):
    """llm_models.py get, detached (in_scope): a launcher restart leaves it be."""
    if llm_models.downloading(repo):
        spawn([NOTIFY, "-a", "LM Studio", "-i", "dialog-information", "Already downloading",
               f"{repo} is being downloaded already"])
        return
    spawn(in_scope(["python3", os.path.join(HYPR, "llm_models.py"), "get", repo] + ([variant] if variant else [])))


def select_download(repo):
    spawn(in_scope(["kitty", "--class", "lms-get", "python3", os.path.join(HYPR, "llm_models.py"),
                    "select", repo]))


def open_url(url):
    spawn(["xdg-open", url])


def hf_item(row, installed, free):
    """One repo: the variant and its size first (the hero's line is cut
    after ~60 characters), then the fit, the counts, the age."""
    repo, variant = row["id"], row["variant"]
    size = row["size"] or row["guess"]
    bits = []
    if llm_models.downloading(repo):
        bits.append("downloading now")
    if installed is not None:
        bits.append(f"installed: ?{installed.name}" if installed else "installed")
    if variant:
        bits.append(f"{variant} {('' if row['size'] else '~') + gb(size)}" if size else variant)
    else:
        bits.append("lms picks the file")
    if size:
        bits.append(fit(size))
    if row["params"]:
        bits.append(f"{row['params'] / 1e9:.1f}".rstrip("0").rstrip(".") + "B"
                    + (f" ({row['moe']} active)" if row["moe"] else ""))
    bits.append(f"{count(row['downloads'])} downloads")
    bits.append(f"{count(row['likes'])} likes")
    try:
        import datetime
        stamp = datetime.datetime.fromisoformat(row["modified"].replace("Z", "+00:00")).timestamp()
        bits.append("updated " + ago(time.time() - stamp))
    except ValueError:
        pass
    if row["pick"]:
        bits.append("LM Studio's own")
    low_disk = bool(size) and free < size + DISK_SPARE
    if low_disk:
        bits.append(f"only {gb(free)} free on disk")
    # The model first, the uploader after: a tile shows ~2 x 16 characters, and
    # "lmstudio-community/..." filled them with the author. "-GGUF" is noise
    # here (every result is one).
    author, _, name = repo.partition("/")
    name = re.sub(r"[-_.]?gguf$", "", name, flags=re.I) or name
    item = Item(f"{name}  ·  {author}" + ("  ✓" if installed is not None else ""),
                "  ·  ".join(bits) + "   --   Enter: download"
                + (f" {variant}" if variant else "") + ", Shift+Enter: choose the variant in kitty",
                "folder-download", lambda: start_download(repo, variant), extra="model download",
                alt=lambda: select_download(repo),
                confirm=(f"Only {gb(free)} free -- download {gb(size)} of {repo} anyway?"
                         if low_disk else None))
    item.confirm_sub = "Enter: yes, download it  ·  Shift+Enter: choose the variant in kitty  ·  Esc: no"
    return item


def get_items(query):
    """?get <query>: the repos found (the hero the best), "Open on Hugging
    Face" for the hero right after it."""
    if len(query) < 2:
        return [Item("Find models to download", "type a name after ?get: ?get qwen coder   --   GGUF "
                     "repos on Hugging Face, downloaded with LM Studio (lms get)", "folder-download")]
    entry = HF_CACHE.get(query)
    if entry is None:
        return [Item(f"Searching Hugging Face for “{query}”…", "GGUF models, most downloaded first",
                     "folder-download")]
    if entry["error"]:
        return [Item("Hugging Face did not answer", f"{entry['error']}   --   Enter: search on its site",
                     "dialog-warning", lambda: open_url(f"https://huggingface.co/models?search="
                                                        f"{urllib.parse.quote(query)}&library=gguf"))]
    if not entry["rows"]:
        return [Item(f"No GGUF models for “{query}”", "Hugging Face has no GGUF repo with these words",
                     "dialog-information")]
    have = llm_models.installed_repos()
    models = llm_models.local_models()
    try:
        free = shutil.disk_usage(llm_models.LMS_MODELS if os.path.isdir(llm_models.LMS_MODELS) else HOME).free
    except OSError:
        free = float("inf")
    items = []
    for row in entry["rows"]:
        installed = (llm_models.model_for_repo(row["id"], models) or False) \
            if row["id"].lower() in have else None
        items.append(hf_item(row, installed, free))
    top = entry["rows"][0]["id"]
    items.insert(1, Item("Open on Hugging Face", f"{top}'s page, in the browser", "web-browser",
                         lambda: open_url(f"https://huggingface.co/{top}"), extra="model"))
    return items


# Past sessions: the chat window's own conversations (llm_chat_engine's
# session files, $XDG_STATE_HOME/hypr/llm-chat/sessions) and -- Claude Code
# installed -- Claude Code's: one JSONL file each, ~/.claude/projects/<cwd
# with / as ->/<session id>.jsonl, appended to as it goes (so its mtime is
# when it was last used). Its head has the first user prompt and the cwd;
# that is all that is read -- 256 KB of it at most, since some of these files
# are 100 MB -- and only again when the mtime moves.
PROJECTS = os.path.join(HOME, ".claude", "projects")
SESSION_LIMIT = 12
SESSION_SCAN = 300          # newest files looked at, for a filter that matches few
SESSION_HEAD = 256 * 1024
QUICK_TITLE = "launcher: quick answer"      # ?? runs' -n: kept out of the list
_SESSIONS = {}              # path -> (mtime, (prompt, cwd) or None)
# Not a prompt someone typed: slash commands and their output, background
# task reports, the summary a compacted session starts with.
NOT_PROMPTS = ("<command-", "<local-command", "<task-notification", "<system-reminder",
               "<bash-", "Caveat:", "This session is being continued")


def chat_engine():
    """llm_chat_engine.py (no GTK), imported on first use."""
    import llm_chat_engine
    return llm_chat_engine


def session_head(path):
    """(first real prompt, cwd) of a Claude Code session file, or None: a
    session with no prompt in its head, a ?? quick answer, a folder that is
    gone."""
    try:
        with open(path, "rb") as handle:
            lines = handle.read(SESSION_HEAD).split(b"\n")
    except OSError:
        return None
    title = None
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue            # the cut-off last line, or a blank
        kind = entry.get("type")
        if kind == "custom-title":
            title = entry.get("customTitle")
            if title == QUICK_TITLE:
                return None
            continue
        if kind != "user" or entry.get("isSidechain") or entry.get("isMeta"):
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, list):   # [text, image...]; a tool_result has no text
            content = " ".join(b.get("text", "") for b in content
                               if isinstance(b, dict) and b.get("type") == "text")
        text = (content or "").strip() if isinstance(content, str) else ""
        if not text or text.startswith(NOT_PROMPTS):
            continue
        cwd = entry.get("cwd") or ""
        if not os.path.isdir(cwd):
            return None         # `claude --resume` there would find nothing
        prompt = " ".join(re.sub(r"<[^>]{1,40}>", " ", text).split())   # <pasted_content>
        return (title or prompt or text[:80], cwd)
    return None


def claude_sessions(words=(), cwd=None):
    """Claude Code's sessions (none without claude installed): [(mtime,
    session id, prompt, cwd, "claude")], newest first, SESSION_LIMIT of
    them, the ones with every word in the prompt or the folder (and, with
    `cwd`, run there)."""
    if claude_cli() is None:
        return []
    try:
        files = [(f.stat().st_mtime, f.path) for d in os.scandir(PROJECTS) if d.is_dir()
                 for f in os.scandir(d.path) if f.name.endswith(".jsonl") and f.is_file()]
    except OSError:
        return []
    files.sort(reverse=True)
    out = []
    for mtime, path in files[:SESSION_SCAN]:
        cached = _SESSIONS.get(path)
        if not cached or cached[0] != mtime:
            cached = _SESSIONS[path] = (mtime, session_head(path))
        if not cached[1]:
            continue
        prompt, where = cached[1]
        hay = (prompt + " " + short(where)).lower()
        if (cwd and where != cwd) or not all(w in hay for w in words):
            continue
        out.append((mtime, os.path.basename(path)[:-6], prompt, where, "claude"))
        if len(out) >= SESSION_LIMIT:
            break
    return out


def chat_sessions(words=(), cwd=None):
    """The chat window's own conversations, as claude_sessions has them
    (kind "native")."""
    try:
        found = chat_engine().list_sessions(SESSION_SCAN)
    except Exception:       # noqa: BLE001 -- a broken file must not cost the ? mode
        return []
    out = []
    for info in found:
        where = info.get("cwd") or HOME
        hay = (info["title"] + " " + short(where)).lower()
        if (cwd and where != cwd) or not all(w in hay for w in words):
            continue
        out.append((info["mtime"], info["id"], info["title"], where, "native"))
        if len(out) >= SESSION_LIMIT:
            break
    return out


def ago(seconds):
    for size, unit in ((7 * 86400, "week"), (86400, "day"), (3600, "h"), (60, "min")):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {unit}{'s' if n > 1 and unit in ('week', 'day') else ''} ago"
    return "just now"


def past_session_items(words=(), cwd=None, model=None):
    """Past conversations to pick up again, newest first: Enter in the chat
    window, in the session's own folder (with `model`, when one was typed
    and it fits the session's kind); a Claude Code one also Shift+Enter
    `claude --resume` in kitty there, where Claude Code looks for it."""
    now = time.time()
    found = sorted(chat_sessions(words, cwd) + claude_sessions(words, cwd), reverse=True)[:SESSION_LIMIT]
    out = []
    for mtime, sid, prompt, where, kind in found:
        use = model if model is not None and (model.kind == "claude") == (kind == "claude") else None
        tui = kind == "claude" and claude_cli() is not None
        out.append(Item(prompt if len(prompt) <= 90 else prompt[:89] + "…",
                        f"{ago(now - mtime)}  ·  {short(where)}{model_note(use) if use else ''}"
                        f"{'  ·  Claude Code' if kind == 'claude' else ''}   --   Enter: go on in the chat window"
                        + (", Shift+Enter: in kitty" if tui else ""), "document-open-recent",
                        lambda s=sid, c=where, m=use: ask_chat(cwd=c, resume=s, model=m), extra="chat session",
                        alt=(lambda s=sid, c=where, m=use: spawn(in_scope(tui_argv(cwd=c, resume=s, model=m))))
                        if tui else None))
    return out


# The clipboard and the screen: what is on them goes in with the prompt --
# text in a fenced block, a picture as a file under SHOT_DIR attached to the
# first message (llm-chat.py --image), which every vision model can see.
SHOT_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "llm-launcher")
CLIP_MAX = 100_000          # characters: one argv element may be 128 KB at most
CLIP_PROMPT = "Explain this"
SCREEN_PROMPT = "Explain what's on my screen"


def notify(text):
    spawn([NOTIFY, "-a", "LLM chat", "-i", CHAT_ICON, "LLM chat", text])


def clipboard_prompt(prompt):
    """(prompt, [image path]): `prompt` with the clipboard -- its text in a
    fenced block, or an image saved as a file to attach. None when there is
    nothing on it."""
    try:
        types = subprocess.run(["wl-paste", "-l"], capture_output=True, text=True,
                               timeout=2).stdout.split()
        image = "image/png" if "image/png" in types else \
            next((t for t in types if t.startswith("image/")), None)
        if image:
            data = subprocess.run(["wl-paste", "-n", "-t", image], capture_output=True,
                                  timeout=3).stdout
            ext = image.split("/")[1].split("+")[0].replace("jpeg", "jpg")
            os.makedirs(SHOT_DIR, exist_ok=True)
            path = os.path.join(SHOT_DIR, f"clipboard-{int(time.time())}.{ext}")
            with open(path, "wb") as handle:
                handle.write(data)
            return (prompt, [path]) if data else None
        text = subprocess.run(["wl-paste", "-n"], capture_output=True, text=True,
                              timeout=2).stdout[:CLIP_MAX]
    except (OSError, subprocess.SubprocessError):
        return None
    if not text.strip():
        return None
    fence = "```"
    while fence in text:        # a block of code with ``` in it: a longer fence
        fence += "`"
    return f"{prompt}\n\n{fence}\n{text}\n{fence}", []


def ask_about_clipboard(prompt, cwd, tui=False, model=None):
    found = clipboard_prompt(prompt or CLIP_PROMPT)
    if found is None:
        notify("The clipboard is empty")
        return
    full, images = found
    if tui and tui_ok(model):
        # Claude Code reads a picture with its Read tool: the path in the words.
        claude_tui(full + "".join(f"\n\nLook at the image at {p}" for p in images), cwd, model=model)
    else:
        ask_chat(full, cwd, model=model, images=images)


def ask_about_screen(prompt, cwd, tui=False, model=None):
    """grim the focused monitor, then ask. In a shell started now that waits
    first: run() comes before the launcher hides, and the shot must not have
    it in -- its fade-out included (the layer rule's popin, ~0.2 s)."""
    try:
        mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True,
                                         text=True, timeout=1).stdout)
        output = next(m["name"] for m in mons if m.get("focused"))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration):
        output = None
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f"screen-{time.strftime('%Y%m%d-%H%M%S')}.png")
    words = prompt or SCREEN_PROMPT
    if tui and tui_ok(model):
        then = tui_argv(f"Look at the screenshot at {path}: {words}", cwd, model=model)
    else:
        then = chat_argv(words, cwd, model=model, images=[path])
    # $1 the monitor ("" for all of them), $2 the file, the rest the command.
    shot = ('sleep 0.5; grim ${1:+-o "$1"} "$2" || { ' + shlex.quote(NOTIFY) + ' -a "LLM chat" "LLM chat" '
            '"grim could not take the screenshot"; exit 1; }; shift 2; exec "$@"')
    spawn(in_scope(["sh", "-c", shot, "sh", output or "", path] + then))


def context_items(prompt, cwd, model=None):
    where = short(cwd or HOME) + model_note(model)
    tui = "   --   Shift+Enter: Claude Code in kitty" if tui_ok(model) else ""
    return [Item(f"Ask {asked(model)} about the clipboard",
                 f"{prompt or CLIP_PROMPT}  + the clipboard (text or image), in {where}{tui}", "edit-paste",
                 lambda: ask_about_clipboard(prompt, cwd, model=model), extra="ask chat clip",
                 alt=(lambda: ask_about_clipboard(prompt, cwd, tui=True, model=model)) if tui else None),
            Item(f"Ask {asked(model)} about the screen",
                 f"{prompt or SCREEN_PROMPT}  + a screenshot of this monitor, in {where}{tui}", "camera-photo",
                 lambda: ask_about_screen(prompt, cwd, model=model), extra="ask chat screen",
                 alt=(lambda: ask_about_screen(prompt, cwd, tui=True, model=model)) if tui else None)]


CLIP_WORDS = ("clip", "clipboard")
SCREEN_WORDS = ("screen", "screenshot")


def folder_items(where):
    """?@<folder> while the folder is being typed: path mode's folders, with
    the chat window for the Enter keys and "?@" kept on what Tab puts in the
    box."""
    where = where or "~/"
    path = os.path.expanduser(where)
    items = []
    tui = tui_ok(None)
    if os.path.isdir(path):
        here = os.path.abspath(path)
        item = Item(f"Chat in {short(here)}", "Enter: the chat window there"
                    + (", Shift+Enter: Claude Code in kitty" if tui else "")
                    + "   --   then type a space and the question", CHAT_ICON,
                    lambda: ask_chat(cwd=here), alt=(lambda: claude_tui(cwd=here)) if tui else None)
        item.complete = "?@" + (where + " " if where.endswith("/") else where + "/")
        items.append(item)
    for found in path_items(where):
        if not found.complete:
            continue            # path mode's "this folder", files and warnings
        full = os.path.abspath(os.path.expanduser(found.complete))
        item = Item(found.name, f"{short(full)}   --   Tab: into it, Enter: the chat here"
                    + (", Shift+Enter: Claude Code in kitty here" if tui else ""), "folder",
                    lambda p=full: ask_chat(cwd=p), alt=(lambda p=full: claude_tui(cwd=p)) if tui else None)
        item.complete = "?@" + found.complete
        items.append(item)
    return items or [Item("No such folder", f"{where}   --   ?@ takes a folder: ?@~/Projects/atlas "
                          "fix the build script", "dialog-warning")]


def ask_items(text):
    """The "?" mode, `text` what follows the ?: the prompt for the chat
    window (the hero; a Claude Code session in kitty as the tile under it,
    for a Claude model with claude installed), the clipboard and screen
    items, and past conversations -- the recent ones, or those with the
    prompt's words. "@<folder>" first runs it all there."""
    text = text.lstrip()
    cwd = None
    if text.startswith("@"):
        where, space, rest = re.match(r"@(\S*)(\s*)(.*)", text, re.S).groups()
        if not space:
            return folder_items(where)
        cwd = os.path.abspath(os.path.expanduser(where))
        if not os.path.isdir(cwd):
            return [Item("No such folder", f"{where}   --   ?@ takes a folder: ?@~/Projects/atlas "
                         "fix the build script", "dialog-warning")]
        text = rest
    elif hf_query(text) is not None:     # "?get qwen coder": downloads
        return get_items(hf_query(text))
    elif text.strip().lower() == "model" or text.strip().partition(" ")[0].lower() == "models":
        return model_items(text.strip().partition(" ")[2].strip())
    model, text = llm_models.split_model(text)      # "?gemma why ...": that model
    prompt = text.strip()
    if not prompt:
        return [Item(f"LLM chat ({model.name})" if model else "LLM chat",
                     f"type a question after the ?: ?how do I resize a btrfs partition   "
                     f"--   Enter: the chat window, empty, in {short(cwd or HOME)}{model_note(model)}",
                     CHAT_ICON, lambda: ask_chat(cwd=cwd, model=model),
                     alt=(lambda: claude_tui(cwd=cwd, model=model)) if tui_ok(model) else None)] \
            + tui_session_items(cwd=cwd, model=model) + context_items("", cwd, model) \
            + past_session_items(cwd=cwd, model=model)
    first, _, after = prompt.partition(" ")
    context = context_items(after.strip() if first.lower() in CLIP_WORDS + SCREEN_WORDS else prompt,
                            cwd, model)
    lead = []
    if first.lower() in CLIP_WORDS:     # "?clip what does this error mean"
        lead = [context.pop(0)]
    elif first.lower() in SCREEN_WORDS:
        lead = [context.pop(1)]
    return lead + [chat_item(prompt, cwd=cwd, model=model)] + tui_session_items(prompt, cwd, model) \
        + context + past_session_items(prompt.lower().split(), cwd, model)


# Quick answers: "??question" -- a few sentences from a small, fast model,
# streamed into the hero card; no window. The Launcher runs it (QuickAnswer
# below), a moment after typing stops; results() only draws what it has.
QUICK_DELAY = 600           # ms after the last key
QUICK_SYSTEM = ("You answer from a desktop search bar. Answer in at most 3 short sentences, "
                "plain text: no markdown, no lists, no headings.")
QUICK_TOKENS = 400


def quick_model(raw):
    """(Model or None, question) for what follows the ??: a model word first
    picks it, else llm.json's "quick" (haiku unless set -- the first local
    model without Claude Code)."""
    model, question = llm_models.split_model(raw)
    return model or llm_models.chosen("quick"), question.strip()


def quick_argv(model):
    # A Claude model: claude -p. --tools "": no built-in tools;
    # --strict-mcp-config with no --mcp-config: no MCP servers either (and a
    # faster start). The session is kept (no --no-session-persistence) so
    # Shift+Enter can --resume it in the chat window; -n names it, and the
    # past-session list leaves those out.
    return [claude_cli() or "claude", "-p"] + llm_models.launch_spec(model) + [
        "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--tools", "",
        "--strict-mcp-config", "--append-system-prompt", QUICK_SYSTEM, "-n", QUICK_TITLE]


class QuickAnswer:
    """One ?? run, in the background, `on_update` called on every new piece
    of text; kill() ends it. `key` is all that followed the ??, model word
    included. A local or server model is asked directly (llm_chat_engine's
    stream(), in a thread, the text handed to the GTK loop; a local one is
    readied first -- llm_models.ensure_local, `status` says how far); a
    Claude model through `claude -p` (stream-json read off the GLib loop,
    io_add_watch, never a blocking read; kill() ends it and its children)."""

    def __init__(self, key, on_update):
        self.key, self.on_update = key, on_update
        self.choice, self.question = quick_model(key)
        self.text, self.error, self.status, self.note = "", "", "", ""
        self.done = self.killed = False
        self.model = self.session = None
        self.cost = None
        self.buffer, self.other = b"", []
        self.watch = 0
        self.proc = None
        self.holder = {}            # the native stream's socket and cancel flag
        if self.choice is None:
            self.done, self.error = True, "no model: LM Studio has none (?get to download one)"
        elif self.choice.local:
            self.status = f"waking LM Studio for {self.choice.name}…"
            threading.Thread(target=self.prepare, daemon=True).start()
        else:
            self.start()

    def prepare(self):
        def say(text):
            GLib.idle_add(self.set_status, text)
        # The "quick" setting (no model typed after the ??) gives way to
        # haiku when it would not fit on the card next to what is loaded,
        # or a game is on -- with Claude Code installed: quick_choice says why.
        if llm_models.split_model(self.key)[0] is None:
            choice, why = llm_models.quick_choice(self.choice)
            if not choice.local:
                GLib.idle_add(self.fell_back, choice, why)
                return
        ok, why = llm_models.ensure_local(self.choice, say)
        GLib.idle_add(self.prepared, ok, why)

    def fell_back(self, choice, why):
        if not self.killed:
            self.choice, self.note, self.status = choice, why, ""
            self.start()
            self.on_update()
        return False

    def set_status(self, text):
        if not self.killed and not self.proc and not self.holder.get("started"):
            self.status = text
            self.on_update()
        return False

    def prepared(self, ok, why):
        if self.killed:
            return False
        if ok:
            self.status = ""
            self.start()
        else:
            self.done, self.error = True, why
        self.on_update()
        return False

    def start(self):
        if self.choice.kind == "claude":
            self.start_claude()
        else:
            self.start_native()

    # -- a local or server model: the chat engine's stream
    def start_native(self):
        engine = chat_engine()
        ep = engine.endpoint("server" if self.choice.kind == "server" else "local")
        if ep is None:
            self.done, self.error = True, "no OpenAI-compatible server is set (Settings > AI & models)"
            return
        self.holder["started"] = True
        self.model = self.choice.name
        body = {"model": self.choice.ident, "max_tokens": QUICK_TOKENS, "temperature": 0.3,
                "messages": [{"role": "system", "content": QUICK_SYSTEM},
                             {"role": "user", "content": self.question}]}

        def work():
            split, error = engine.ThinkSplitter(), ""
            try:
                for chunk in engine.stream(ep, body, self.holder):
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if isinstance(piece, str) and piece:
                            words = split.feed(piece)[0]
                            if words:
                                GLib.idle_add(self.add_text, words)
                words = split.flush()[0]
                if words:
                    GLib.idle_add(self.add_text, words)
            except engine.Cancelled:
                return
            except engine.ServerError as exc:
                error = exc.message
            except Exception as exc:        # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            GLib.idle_add(self.native_done, error)

        threading.Thread(target=work, daemon=True).start()

    def add_text(self, words):
        if not self.killed:
            self.text += words
            self.on_update()
        return False

    def native_done(self, error):
        if self.killed:
            return False
        self.done = True
        self.error = error[:200] if error else ("" if self.text.strip() else "the model said nothing")
        self.on_update()
        return False

    def continue_native(self):
        """Shift+Enter: the question and its answer as a conversation of the
        chat window (a session file of its own), opened there to go on."""
        engine = chat_engine()
        sid = engine.new_session_id()
        try:
            engine.save_session(sid, [{"role": "user", "content": self.question},
                                      {"role": "assistant", "content": self.text.strip()}], HOME, self.choice.name)
        except OSError as exc:
            notify(f"could not save the conversation: {exc}")
            return
        ask_chat(cwd=HOME, resume=sid, model=self.choice)

    # -- a Claude model: claude -p
    def start_claude(self):
        if claude_cli() is None:
            self.done, self.error = True, "Claude Code is not installed: ask a local model (??gemma …)"
            return
        try:
            self.proc = subprocess.Popen(quick_argv(self.choice), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HOME,
                                         start_new_session=True)
        except OSError as exc:
            self.proc, self.done, self.error = None, True, str(exc)
            return
        try:
            self.proc.stdin.write(self.question.encode())    # stdin: never parsed as a flag
            self.proc.stdin.close()
        except OSError:
            pass
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.watch = GLib.io_add_watch(self.proc.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                                       GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_output)

    def on_output(self, fd, cond):
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            return True
        except OSError:
            chunk = b""
        if chunk:
            self.buffer += chunk
            *lines, self.buffer = self.buffer.split(b"\n")
            for line in lines:
                self.event(line)
            self.on_update()
            return True
        self.watch = 0
        self.finish()
        return False

    def event(self, line):
        try:
            entry = json.loads(line)
        except ValueError:
            if line.strip():
                self.other.append(line.decode(errors="replace").strip())    # stderr
            return
        kind = entry.get("type")
        if kind == "stream_event":
            delta = entry.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta":
                self.text += delta.get("text", "")
        elif kind == "system" and entry.get("subtype") == "init":
            self.session = entry.get("session_id")
            self.model = entry.get("model")
        elif kind == "assistant":
            self.model = entry.get("message", {}).get("model") or self.model
            if not self.text:   # no partial messages came: the whole text at once
                self.text = "".join(b.get("text", "") for b in entry["message"].get("content", [])
                                    if b.get("type") == "text")
        elif kind == "result":
            self.session = entry.get("session_id") or self.session
            self.cost = entry.get("total_cost_usd")
            if entry.get("is_error") or entry.get("subtype") != "success":
                self.error = str(entry.get("result") or ", ".join(entry.get("errors") or [])
                                 or entry.get("subtype"))

    def finish(self):
        if self.buffer:
            self.event(self.buffer)
            self.buffer = b""
        try:
            # stdout closed: claude is exiting, a few ms at most -- still,
            # this is the GTK loop, so not forever.
            code = self.proc.wait(timeout=2) if self.proc else 0
        except subprocess.TimeoutExpired:
            self.kill()
            code = -1
        self.done = True
        if not self.error and (code or not self.text):
            self.error = (self.other[-1] if self.other else f"claude exited with {code}")[:200]
        self.on_update()

    def kill(self):
        self.killed = True
        self.holder["cancel"] = True
        sock = self.holder.get("sock")
        if sock is not None:
            try:
                sock.shutdown(2)        # socket.SHUT_RDWR: the stream's read ends
            except OSError:
                pass
        if self.watch:
            GLib.source_remove(self.watch)
            self.watch = 0
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except OSError:
                pass
            threading.Thread(target=self.proc.wait, daemon=True).start()   # no zombie


def quick_items(raw, quick=None):
    """The ?? mode, `raw` what follows it: the answer as the hero, as far as
    it has come (`quick`, the QuickAnswer for this text, or None while
    waiting for the debounce), then the question for the chat window --
    with the model the ?? named, if it named one."""
    model, question = quick_model(raw)
    named = llm_models.split_model(raw)[0]
    if not question:
        return [Item("Quick answer", "type a question after the ??: ??how tall is mount fuji, "
                     "??gemma how tall is mount fuji   --   "
                     f"a few sentences from {model.name if model else 'the quick model'}, right here",
                     CHAT_ICON)]
    full = chat_item(question, model=named)
    if quick is None or quick.key != raw or not (quick.text or quick.done):
        waiting = quick.status if quick is not None and quick.key == raw and quick.status \
            else f"asking {model.name if model else 'the model'}…"
        item = Item("…", f"{waiting}   --   Shift+Enter: the chat window instead",
                    CHAT_ICON, alt=full._run)
    elif quick.done and quick.error:   # its "text" then is the error again, from <synthetic>
        item = Item("No answer", f"{quick.choice.name if quick.choice else 'no model'}: {quick.error}"
                    "   --   Shift+Enter: the chat window", "dialog-warning", alt=full._run)
    else:
        text = quick.text.strip()
        model = quick.choice            # haiku, when the quick model gave way to it
        note = f"  ({quick.note})" if quick.note else ""
        where = {"local": "  (local)", "server": "  (server)"}.get(model.kind, "")
        if not quick.done:
            sub = f"{quick.model or model.name}, answering…{note}"
        else:
            cost = f"  ·  ${quick.cost:.4f}" if quick.cost is not None and model.kind == "claude" else ""
            sub = f"{quick.model or model.name}{where}{cost}{note}"
        # The conversation goes on in the chat window on the model it was
        # asked of: a Claude one as its Claude Code session, any other as a
        # conversation of the window's own.
        if model.kind != "claude":
            resume = quick.continue_native if quick.done else full._run
        elif quick.session:
            resume = (lambda s=quick.session, m=model: ask_chat(cwd=HOME, resume=s, model=m))
        else:
            resume = full._run
        item = Item(text, f"{sub}   --   Enter: copy, Shift+Enter: continue in the chat window",
                    CHAT_ICON, lambda: copy(text), alt=resume)
    item.answer = True
    return [item, full]


def wants_ask(text):
    """Offer "Ask …" in the default mode: two words or more, or a "?" -- a
    question, not an app name. Not for an address ("x.com/?q=")."""
    query = text.strip()
    if not query or len(query) > MAX_QUERY or as_url(query):
        return False
    return len(query.split()) >= 2 or "?" in query


def my_processes():
    """[(pid, name, cmdline, rss bytes)] of this user's processes."""
    uid, out = os.getuid(), []
    page = os.sysconf("SC_PAGE_SIZE")
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            with open(f"/proc/{pid}/comm") as handle:
                name = handle.read().strip()
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmd = handle.read().replace(b"\0", b" ").decode(errors="replace").strip()
            with open(f"/proc/{pid}/statm") as handle:
                rss = int(handle.read().split()[1]) * page
        except (OSError, ValueError, IndexError):
            continue
        if cmd:                     # kernel threads have none
            out.append((int(pid), name, cmd, rss))
    return out


def end_process(pids, force):
    import signal as sig
    for pid in pids:
        try:
            os.kill(pid, sig.SIGKILL if force else sig.SIGTERM)
        except OSError:
            pass


# -- timers, alarms, reminders, focus, the stopwatch (timers.py) --------------------------
TIMER_RE = re.compile(r"(?:set (?:a |un )?)?(?:timer|temporizador|countdown)(?: (?:for|de|por))? (.+)")
TIMER_AFTER_RE = re.compile(r"(.+?) (?:timer|temporizador)((?: (?:then|and then|luego|y luego|despues) .+)?)")
ALARM_RE = re.compile(r"(?:set (?:an? |una )?)?(?:alarm|alarma|wake me(?: up)?|despiertame)"
                      r"(?: (?:at|for|a las|a la|para las))? (.+)")
REMIND_RE = re.compile(r"(?:remind(?: me)?|reminder|recuerdame|recordatorio)"
                       r" (in|en|at|a las|a la|para las) (.+)")
FOCUS_RE = re.compile(r"(?:focus|pomodoro|enfoque|concentrar(?:me)?)(?: (\d{1,3})(?: ?(?:m|min|mins|minutes|minutos))?)?")
WATCH_WORDS = ("stopwatch", "cronometro", "start counting", "count up", "contar", "start stopwatch",
               "start the stopwatch", "iniciar cronometro")
LIST_WORDS = ("timer", "timers", "temporizador", "temporizadores", "alarm", "alarms", "alarma",
              "alarmas", "countdown", "stopwatch", "cronometro", "reminders", "recordatorios",
              "remind", "reminder", "calendar alarms")
KIND_ICON = {"alarm": "alarm", "calendar": "x-office-calendar", "reminder": "emblem-important"}


def timer_notify(text):
    spawn([NOTIFY, "-a", "Timer", "-t", "3000", "-i", "alarm-symbolic", text])


def at_text(epoch):
    return time.strftime("%H:%M", time.localtime(epoch))


def start_timer(secs, label, then):
    t = timers.start_timer(secs, label, then)
    timer_notify(f"{timers.span(secs)} timer{' · ' + label if label else ''} -- "
                 f"{'ends' if then else 'rings'} at {at_text(t['due'])}"
                 + (f", {timers.then_text(then)}" if then else ""))


def start_alarm(when, label, then, days):
    t = timers.start_alarm(when, label, then, days)
    timer_notify(f"Alarm at {at_text(t['due'])}" + (f", {timers.days_text(days)}" if days else "")
                 + (f" · {label}" if label else ""))


def start_reminder(due, msg):
    timers.start_reminder(due, msg)
    timer_notify(f"Reminder at {at_text(due)}: {msg}")


def stopwatch_items():
    sw = timers.stopwatch()
    if sw is None:
        return [Item("Start the stopwatch", "counts up in the bar  ·  Enter starts it",
                     "preferences-system-time", lambda: timers.stopwatch_do("start"))]
    secs, going = sw
    reset = (lambda v=timers.clock(secs): (copy(v), timers.stopwatch_do("reset")))
    if going:
        return [Item(f"Stopwatch  {timers.clock(secs)}",
                     "running  ·  Enter pauses  ·  Shift+Enter stops it and copies the time",
                     "preferences-system-time", lambda: timers.stopwatch_do("pause"), alt=reset)]
    return [Item(f"Stopwatch  {timers.clock(secs)}  (paused)",
                 "Enter resumes  ·  Shift+Enter resets it and copies the time",
                 "preferences-system-time", lambda: timers.stopwatch_do("start"), alt=reset)]


def running_timer_items():
    now = time.time()
    out = []
    for t in timers.running():
        what = t["label"] or timers.NAMES[t["kind"]]
        # A paused alarm won't ring, so a countdown to its next time would
        # mislead; the subtitle (describe) already says "paused · 07:30".
        left = "paused" if t.get("paused") else timers.clock(t["due"] - now) + " left"
        out.append(Item(f"{what}  {left}",
                        f"{timers.describe(t, now)}  ·  Enter cancels it",
                        KIND_ICON.get(t["kind"], "preferences-system-time"),
                        lambda i=t["id"]: timers.cancel(i),
                        confirm=f"Cancel {what}" + (f" ({timers.days_text(t['days'])})" if t.get("repeat") else "") + "?"))
    if len(out) > 1:
        out.append(Item("Cancel all timers and alarms", f"{len(out)} running", "edit-clear-all",
                        lambda: timers.cancel("all"), confirm=f"Cancel all {len(out)}?"))
    for item in out:
        item.confirm_sub = "Enter: yes, cancel it  ·  Esc: no"
    return out


def calendar_item():
    on = timers.calendar_on()
    return Item(f"Calendar alarms: {'on' if on else 'off'}",
                f"an alarm {timers.CAL_LEAD_MIN} min before each event in your calendars  ·  "
                f"Enter turns them {'off' if on else 'on'}", "x-office-calendar",
                lambda: timers.calendar_switch(not on))


def timer_items(text):
    """"timer 5m tea [then suspend]", "10 min timer", "alarm 7:30
    [weekdays] [then ...]", "remind me in 40 min to call the lab", "remind
    15:30 check the queue", "focus" / "pomodoro 50", "stopwatch" /
    "cronómetro"; "timers" (or any of those words alone) lists what runs,
    Enter cancels one."""
    if text[:1] in "=>#:$!?/~" or is_long(text):
        return []
    q = " ".join(text.strip().split())
    low = timers.fold(q)        # accents off, same length: q[-n:] is the typed words
    k = place_key(q)
    out = []
    m = TIMER_RE.fullmatch(low) or TIMER_AFTER_RE.fullmatch(low)
    if m:
        rest, then = timers.parse_then(q[len(q) - len(m[1]):] if m.re is TIMER_RE else m[1] + (m[2] or ""))
        secs, label = timers.parse_duration(rest)
        if secs:
            due = time.strftime("%H:%M:%S", time.localtime(time.time() + secs))
            out.append(Item(f"Timer  {timers.clock(secs)}" + (f"  ·  {label}" if label else ""),
                            f"{timers.span(secs)}, {'ends' if then else 'rings'} at about {due}"
                            + (f", {timers.then_text(then)}" if then else "") + "  ·  Enter starts it",
                            "preferences-system-time", lambda s=secs, l=label, t=then: start_timer(s, l, t)))
    m = ALARM_RE.fullmatch(low)
    if m:
        rest, then = timers.parse_then(q[len(q) - len(m[1]):])
        if re.match(r"\d{1,2}(?:\s|$)", rest):         # "alarma 7 diario": a bare hour
            rest = re.sub(r"^(\d{1,2})", r"\1:00", rest)
        when, rest = timers.parse_clock(rest)
        if when:
            days, label = timers.parse_repeat(rest)
            first = timers.next_at((when.hour, when.minute), days) if days else when
            left = timers.span(int(first.timestamp() - time.time()) // 60 * 60 + 60)
            out.append(Item(f"Alarm  {first:%H:%M}" + (f"  ·  {timers.days_text(days)}" if days else "")
                            + (f"  ·  {label}" if label else ""),
                            (f"{timers.days_text(days)}, first " if days else "")
                            + f"{first:%A} at {first:%H:%M}, in {left}"
                            + (f", {timers.then_text(then)}" if then else "") + "  ·  Enter sets it",
                            "alarm", lambda w=when, l=label, t=then, d=days: start_alarm(w, l, t, d)))
        elif m[1].startswith(("in ", "en ")):          # "alarm in 20 min": a timer
            secs, label = timers.parse_duration(rest[3:])
            if secs:
                out.append(Item(f"Timer  {timers.clock(secs)}" + (f"  ·  {label}" if label else ""),
                                f"{timers.span(secs)}  ·  Enter starts it", "preferences-system-time",
                                lambda s=secs, l=label, t=then: start_timer(s, l, t)))
    m = REMIND_RE.fullmatch(low)
    if m:
        tail = q[len(q) - len(m[2]):]
        if m[1] in ("in", "en"):
            secs, msg = timers.parse_duration(tail)
            due = time.time() + secs if secs else None
        else:
            when, msg = timers.parse_clock(tail)
            due = when.timestamp() if when else None
        msg = re.sub(r"^(?:to|que|de)\s+", "", msg, flags=re.I)
        if due and msg:
            out.append(Item(f"Remind me: {msg}", f"at {at_text(due)}  ·  Enter sets it",
                            "emblem-important", lambda d=due, s=msg: start_reminder(d, s)))
    m = FOCUS_RE.fullmatch(k)
    if m:
        mins = int(m[1]) if m[1] else timers.FOCUS_MIN
        n = timers.rounds_today()
        out.append(Item(f"Focus  {mins} min",
                        f"Do Not Disturb on, then a {timers.BREAK_MIN} min break "
                        f"(every {nth(timers.LONG_EVERY)}: {timers.LONG_BREAK_MIN})"
                        + (f"  ·  {n} round{'s' if n > 1 else ''} today" if n else "") + "  ·  Enter starts it",
                        "preferences-system-time", lambda v=mins: timers.start_focus(v)))
    if k in WATCH_WORDS:
        out += stopwatch_items()
    if k in LIST_WORDS or out:
        out += running_timer_items()
        if k in LIST_WORDS and k not in WATCH_WORDS and timers.stopwatch() is not None:
            out += stopwatch_items()
        if k in LIST_WORDS:
            out.append(calendar_item())
    return out


def kill_items(text):
    m = re.fullmatch(r"(?:kill|end|matar|terminar)\s+(.+)", text.strip(), re.I)
    if not m:
        return []
    want = m[1].strip().lower()

    def names(proc):
        # Its process name, its program, and for an interpreter its script:
        # never the whole command line, or every shell whose arguments
        # merely mention the word would be offered up.
        argv = proc[2].split()
        out = {proc[1].lower(), os.path.basename(argv[0]).lower()}
        if re.match(r"(python[\d.]*|sh|bash|zsh|node|perl|ruby|gjs)$", os.path.basename(argv[0])):
            for arg in argv[1:]:
                if not arg.startswith("-"):
                    out.add(os.path.basename(arg).lower())
                    break
        return out

    procs = [p for p in my_processes() if any(want in n for n in names(p))]
    if not procs:
        return [Item(f"No process of yours matches \u201c{want}\u201d", "nothing to end", "process-stop")]
    procs.sort(key=lambda p: -p[3])
    gb = lambda n: f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"  # noqa: E731
    items = []
    if len(procs) > 1:
        pids = [p[0] for p in procs]
        total = sum(p[3] for p in procs)
        items.append(Item(f"End all {len(procs)} \u201c{want}\u201d processes", f"{gb(total)} together   --   "
                          "Enter: end them (asks first), Shift+Enter: kill outright", "process-stop",
                          lambda: end_process(pids, False), alt=lambda: end_process(pids, True),
                          confirm=f"Really end all {len(procs)} \u201c{want}\u201d processes?"))
    for pid, name, cmd, rss in procs[:10]:
        items.append(Item(f"{name}  (pid {pid})", f"{gb(rss)}  ·  {cmd[:70]}   --   Enter: end it (asks first), "
                          "Shift+Enter: kill outright", "process-stop",
                          lambda p=pid: end_process([p], False), alt=lambda p=pid: end_process([p], True),
                          confirm=f"Really end {name} (pid {pid})?"))
    return items


# -- settings typed in the box: "volume 40", "brightness 70", "bluetooth on" --

VOLUME_RE = re.compile(r"(?:vol|volume|volumen|sound|sonido)(?: (up|down|sube|subir|baja|bajar|mute|unmute"
                       r"|silencio|[+-]?\d{1,3}))?")
MIC_RE = re.compile(r"(?:mic|micro|microphone|microfono)(?: (on|off|mute|unmute|silencio))?")
OUTPUT_RE = re.compile(r"(?:output|audio output|salida|salida de audio|speakers?|headphones?|audifonos)(?: (.+))?")
# "brightness 70", "dim dp-2", "warmth 4000 hdmi", "saturation lg 50": the
# value and the screen in either order, the screen by connector or a word of
# its name; no screen = all of them.
SCREEN_RE = re.compile(r"(brightness|brillo|dim|warmth|warm|calidez|saturation|saturacion)((?: \S+){0,2})")
RADIO_RE = re.compile(r"(bluetooth|bt|wi-?fi|wlan)(?: (on|off|encender|apagar|encendido|apagado))?")
UP_WORDS, DOWN_WORDS = ("up", "sube", "subir"), ("down", "baja", "bajar")
ON_WORDS = ("on", "unmute", "encender", "encendido")
VOLUME_STEP = 10
SCREEN_COLOR = os.path.join(HYPR, "screen-color.py")
RATE_RE = re.compile(r"(?:refresh rate|refresh|rate|hz|frecuencia|tasa de refresco)((?: \S+){0,2})")
SCREEN_KEYS = {"brightness": "brightness", "brillo": "brightness", "dim": "brightness",
               "warmth": "warmth", "warm": "warmth", "calidez": "warmth",
               "saturation": "saturation", "saturacion": "saturation"}
SCREEN_STEPS = {"brightness": 10, "warmth": 500, "saturation": 25}
SCREEN_PICKS = {"brightness": (100, 80, 60, 40), "warmth": (6500, 5000, 4000, 3000),
                "saturation": (100, 75, 50, 0)}
SCREEN_UNITS = {"brightness": "%", "warmth": "K", "saturation": "%"}


def run_quiet(argv, timeout=2):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def volume_of(target):
    """(percent, muted) of @DEFAULT_AUDIO_SINK@ / _SOURCE@, or (None, False)."""
    m = re.search(r"Volume: ([\d.]+)( \[MUTED\])?", run_quiet(["wpctl", "get-volume", target]))
    return (round(float(m[1]) * 100), bool(m[2])) if m else (None, False)


def sinks():
    """[(id, name, is_default)] from `wpctl status`'s Audio > Sinks."""
    out, inside = [], False
    for line in run_quiet(["wpctl", "status"]).splitlines():
        if "Sinks:" in line:
            inside = True
        elif inside:
            m = re.match(r"[\s│├└─]*(\*)?\s*(\d+)\.\s+(.+?)\s*(?:\[vol:.*)?$", line)
            if not m:
                break
            out.append((m[2], m[3], bool(m[1])))
    return out


def volume_cap():
    """How loud "volume N" may go, in percent: 150 with over-amplification on
    in Settings > Sound (sound-settings.py boost), else 100. Read from its
    state file, as osd.py's volume keys do, so typing stays one process."""
    state = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "hypr", "sound.json")
    try:
        with open(state) as handle:
            return 150 if json.load(handle).get("boost") else 100
    except (OSError, ValueError, AttributeError):
        return 100


def set_volume(pct):
    cap = volume_cap()
    pct = max(0, min(cap, pct))
    spawn(["sh", "-c", f"wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; "
                       f"wpctl set-volume -l {cap / 100:.1f} @DEFAULT_AUDIO_SINK@ {pct / 100:.2f}; "
                       f"{os.path.join(HYPR, 'osd.py')} show volume"])


def screen_status():
    try:
        return json.loads(run_quiet([SCREEN_COLOR, "status"], timeout=3))
    except ValueError:
        return None


def screen_items(k):
    """Brightness / warmth / saturation, all screens or one (screen-color.py)."""
    m = SCREEN_RE.fullmatch(k)
    if not m:
        return []
    key = SCREEN_KEYS[m[1]]
    st = screen_status()
    if not st or not st["screens"]:
        return []
    value, screen = None, None
    for word in m[2].split():
        if word in UP_WORDS or word in DOWN_WORDS or re.fullmatch(r"[+-]?\d{1,4}", word):
            value = word
            continue
        found = [sc for sc in st["screens"] if word == sc["name"].lower()
                 or word in sc["name"].lower() or word in sc["description"].lower().split()]
        if len(found) != 1:
            return []
        screen = found[0]
    lo, hi = st["ranges"][key]
    unit = SCREEN_UNITS[key]
    now = screen[key] if screen else st["all"][key]
    if m[1] == "dim" and value is None:
        value = str(now - 30)
    if value and (value in UP_WORDS or value in DOWN_WORDS or value[0] in "+-"):
        step = int(value) if value[0] in "+-" else SCREEN_STEPS[key] * (1 if value in UP_WORDS else -1)
        value = str(now + step)
    where = screen["name"] if screen else "all screens"
    others = "  ·  ".join(f"{sc['name']} {sc[key]}{unit}" for sc in st["screens"])
    sub = f"{where}  ·  now {others}  ·  Enter sets it"
    target = screen["name"] if screen else "all"
    picks = [max(lo, min(hi, int(value)))] if value else [p for p in SCREEN_PICKS[key] if p != now]
    icon = "display-brightness" if key == "brightness" else "preferences-color"
    return [Item(f"{key.capitalize()}  {p}{unit}  ({where})", sub, icon,
                 lambda p=p: spawn(["sh", "-c", f"{SCREEN_COLOR} set {target} {key} {p}"
                                    + (f"; {os.path.join(HYPR, 'osd.py')} show brightness"
                                       + ("" if target == "all" else f" {p} {target}")
                                       if key == "brightness" else "")])) for p in picks]


def radio(kind, on):
    """Bluetooth / Wi-Fi on or off through network-settings.py, the Network
    page's own backend: its Bluetooth "off" is rfkill-aware (a soft block as
    well as BlueZ's power, so it stays off after a reboot; "on" unblocks
    first). Its error line goes to a notification."""
    word = "on" if on else "off"
    argv = [NETSET, "bt", "power", word] if kind == "bluetooth" else [NETSET, "wifi", word]
    label = "Bluetooth" if kind == "bluetooth" else "Wi-Fi"
    spawn(told(label, argv))


def radio_state(kind):
    """Whether the radio is on, as network-settings.py reports it (Bluetooth:
    powered and not blocked)."""
    if kind == "bluetooth":
        try:
            bt = json.loads(run_quiet([NETSET, "bt", "status"], timeout=3) or "{}")
        except ValueError:
            bt = {}
        return bool(bt.get("powered")) and not bt.get("blocked")
    return run_quiet(["nmcli", "radio", "wifi"]).strip() == "enabled"


def rate_items(k):
    """"rate", "rate dp-2", "refresh rate dp-1 144": the screens' refresh
    rates (display.py rate); Enter switches."""
    m = RATE_RE.fullmatch(k)
    if not m:
        return []
    try:
        outputs = json.loads(run_quiet([os.path.join(HYPR, "display.py"), "status"], timeout=3))["outputs"]
    except (ValueError, KeyError):
        return []
    want, picked = None, outputs
    for word in m[1].split():
        if re.fullmatch(r"\d{2,3}(?:\.\d{1,2})?", word):
            want = float(word)
            continue
        picked = [o for o in outputs if word == o["name"].lower() or word in o["name"].lower()
                  or word in o["description"].lower().split()]
        if len(picked) != 1:
            return []
    hz = lambda r: f"{float(r):.2f}".rstrip("0").rstrip(".")
    out = []
    for o in picked:
        if want is None and len(picked) > 1:
            offered = [o["rate"]]           # every screen: just what each runs at
        else:
            offered = [r for r in o["rates"] if want is None or abs(float(r) - want) < 0.005]
        for r in offered:
            now = r == o["rate"]
            out.append(Item(f"{o['name']}  {hz(r)} Hz" + ("  (now)" if now else ""),
                            f"{o['description']}  ·  offers {', '.join(hz(x) for x in o['rates'])} Hz"
                            + ("" if now else "  ·  Enter switches"), "video-display",
                            None if now else (lambda n=o["name"], r=r: spawn([os.path.join(HYPR, "display.py"),
                                                                             "rate", n, r, "--confirm"]))))
    return out


ACCENT_RE = re.compile(r"(?:accent|acento|color de acento) #?([0-9a-f]{6})")


def accent_items(k):
    """"accent #ff8800": your own accent colour for the current theme."""
    m = ACCENT_RE.fullmatch(k)
    if not m:
        return []
    colour = "#" + m[1]
    return [Item(f"Accent: {colour}", f"your own accent for {desktop_theme.current()}  ·  Enter sets it",
                 "preferences-desktop-theme",
                 lambda: spawn([os.path.join(HYPR, "theme-from-wallpaper.py"), "custom", colour]),
                 glyph=None)]


EMERGENCY = os.path.join(HYPR, "emergency-alerts.py")
EMERGENCY_RE = re.compile(r"(?:emergency|emergency alerts?|alerts?|alertas?|alerta sismica|sismo|earthquake)"
                          r"(?: (?:place|lugar) (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)(?: ([a-z]{2}))?)?")


def emergency_items(k):
    """"alerts" / "alertas" / "emergency": the emergency-alert sources for
    your country (emergency-alerts.py), Enter turns one on or off; "alerts
    place 40.4 -3.7 es" moves your place (and country)."""
    m = EMERGENCY_RE.fullmatch(k)
    if not m:
        return []
    if m[1]:
        args = [EMERGENCY, "place", m[1], m[2]] + ([m[3].upper()] if m[3] else [])
        return [Item(f"Emergency alerts: set my place to {m[1]}, {m[2]}" + (f" ({m[3].upper()})" if m[3] else ""),
                     "the sources switch to that country's defaults  ·  Enter sets it", "mark-location",
                     lambda: spawn(args))]
    try:
        info = json.loads(run_quiet([EMERGENCY, "sources", "--json"], timeout=3))
    except ValueError:
        return []
    items = []
    for src in info["sources"]:
        word = "on" if src["on"] else "off"
        items.append(Item(f"{src['name']}: {word}", f"{src['kind']}  ·  {info['country']}  ·  Enter turns it "
                          + ("off" if src["on"] else "on"), "dialog-warning",
                          lambda s=src: spawn([EMERGENCY, "disable" if s["on"] else "enable", s["id"]])))
    return items


ASK_DESKTOP = os.path.join(HYPR, "ask-desktop.py")
ASK_RE = re.compile(r"(?:ask|pregunta|preguntar) (.{6,})")
# "remember ..." / "recuerda ..." (not "recuérdame", a reminder: timers' REMIND_RE)
DESKTOP_MEMORY = os.path.join(HYPR, "desktop-memory.py")
MEMORY_RE = re.compile(r"(?:remember|recuerda|recuerdas|¿recuerdas)\s+(.{4,})", re.I)
PEERS = os.path.join(HYPR, "peers.py")
PEERS_CONF = os.path.join(os.path.dirname(HYPR), "peers.json")


def paired_machines():
    """The paired machines' (id, name) from peers.json (peers.py), while
    sharing is on: read from the file, no network while typing."""
    try:
        with open(PEERS_CONF) as handle:
            conf = json.load(handle)
        return [(p["id"], p.get("name") or p["id"][:8]) for p in conf.get("peers") or []] \
            if conf.get("enabled") else []
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def ask_desktop_items(text):
    """"ask what was I working on yesterday at 3pm", "ask find the pdf about
    invoices from last week": your files, clipboard and window history, read
    by the local model (ask-desktop.py); the answer comes as a notification
    with Open buttons for the files it found."""
    mem = MEMORY_RE.fullmatch(text.strip())
    if mem:
        question = mem[1]
        return [Item(f"Remember: {question}", "the desktop memory (windows, copies, notifications, captions, "
                     "screen text, with their times), answered by the local model  ·  Enter asks",
                     "document-open-recent", lambda: spawn([DESKTOP_MEMORY, "recall", "--notify", question]))] + \
            [Item(f"Remember on {name}: {question}", f"{name}'s desktop memory, answered there (only when it "
                  "shares it: Settings > Machines there)  ·  Enter asks", "computer",
                  lambda pid=pid: spawn([PEERS, "recall", "--to", pid, "--notify", question]))
             for pid, name in paired_machines()]
    chat = ASSISTANT_RE.fullmatch(text.strip())
    if chat:
        return assistant_items(chat[1])
    m = ASK_RE.fullmatch(text.strip())
    if not m:
        return []
    question = m[1]
    items = [Item(f"Ask your desktop: {question}", "files, clipboard and window history, "
                  "answered by the local model  ·  Enter asks (the answer comes as a notification)",
                  "system-search", lambda: spawn([ASK_DESKTOP, "--notify", question]))]
    on, first = assistant_choice()
    if on:
        chat_items = assistant_items(question)
        items = chat_items + items if first == "assistant" else items + chat_items
    return items


# The desktop assistant (assistant.py): "assistant" / "asistente" alone opens
# its chat, with words it asks them; "ask …" offers it too, first or second
# as Settings > Assistant says (launcher_ask).
ASSISTANT = os.path.join(HYPR, "assistant.py")
ASSISTANT_RE = re.compile(r"(?:assistant|asistente)(?:\s+(.{2,}))?", re.I)
ASSISTANT_CONF = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                              "hypr", "assistant", "settings.json")


def assistant_choice():
    """(on, "assistant" | "desktop"): assistant.py's enabled / launcher_ask,
    read from its settings file (no import: the launcher starts fast)."""
    try:
        with open(ASSISTANT_CONF) as handle:
            conf = json.load(handle)
    except (OSError, ValueError):
        conf = {}
    if not isinstance(conf, dict):
        conf = {}
    return conf.get("enabled", "on") != "off", conf.get("launcher_ask", "assistant")


def assistant_items(question):
    if not assistant_choice()[0]:
        return []
    if not question:
        return [Item("Assistant", "the chat that knows this desktop: memory, screen, windows, actions -- the "
                     "local model only  ·  Enter opens it", "dialog-information",
                     lambda: spawn([ASSISTANT, "open"]))]
    return [Item(f"Ask the assistant: {question}", "a chat that can look things up and act (risky actions ask "
                 "first), local model only  ·  Enter opens it and asks", "dialog-information",
                 lambda: spawn([ASSISTANT, "open", "--ask", question]))]


SETTINGS_WORDS = ("settings", "setting", "preferences", "ajustes", "configuracion")
SETTINGS_ICONS = {"screens": "video-display", "theme": "preferences-desktop-theme",
                  "effects": "applications-graphics", "fonts": "preferences-desktop-font",
                  "windows": "preferences-system-windows", "apps": "preferences-desktop-default-applications",
                  "sound": "preferences-desktop-sound", "network": "preferences-system-network",
                  "input": "input-keyboard", "devices": "drive-removable-media", "alerts": "dialog-warning",
                  "privacy": "preferences-system-privacy", "startup": "system-run",
                  "notifications": "preferences-system-notifications", "system": "utilities-system-monitor",
                  "power": "preferences-system-power", "region": "preferences-system-time",
                  "updates": "system-software-update", "about": "help-about",
                  "accessibility": "preferences-desktop-accessibility",
                  "wallpaper": "preferences-desktop-wallpaper", "shortcuts": "input-keyboard",
                  "bar": "preferences-desktop", "timers": "alarm-clock", "capture": "applets-screenshooter",
                  "accounts": "system-users", "storage": "drive-harddisk"}


def settings_items(text, explicit=False):
    """"Settings: <page>" for each page of the Settings window the words find
    -- its title and the keywords the page declares (PAGE["keywords"]),
    by the window's own search rules (settings_pages/_catalog.py), best first.
    Enter opens the window on that page. "settings" / "ajustes" before the
    words ("settings sound") is left out of the search, and alone lists every
    page; `explicit` (the > mode) does the same without the word. Pages are
    read from their sources, again only when one changes, so a new page shows
    up with no restart."""
    query = text.strip()
    first, _, rest = query.partition(" ")
    if settings_catalog.fold(first) in SETTINGS_WORDS:
        query, explicit = rest.strip(), True
    pages = settings_catalog.read_pages()
    if query:
        if len(query) < 2 and not explicit:
            return []
        pages = settings_catalog.search(pages, query)
    elif not explicit:
        return []
    items = []
    for page in pages:
        why = settings_catalog.hint(page, query) if query else ""
        about = ", ".join((page.get("keywords") or [])[:4])
        sub = (f"“{why}”  ·  " if why else "") + f"{page.get('group', '')}" + (f": {about}" if about else "")
        icon = Gio.ThemedIcon.new_from_names([SETTINGS_ICONS.get(page["id"], "preferences-system"),
                                               "preferences-system"])
        items.append(Item(f"Settings: {page['title']}", sub, icon,
                          lambda k=page["id"]: spawn([SETTINGS, k]),
                          extra=" ".join(page.get("keywords") or [])))
    return items


def setting_items(text):
    """"volume 40" / "vol up" / "volume mute", "mic off", "output hdmi",
    "brightness 70" / "dim dp-2" / "warmth 4000", "bluetooth on", "wifi off": Enter does it. The
    word alone shows how it is now and the likely changes."""
    if text[:1] in "=>#:$!?/~" or "\n" in text.strip():
        return []
    if is_long(text):
        return ask_desktop_items(text)  # a question may be long; nothing else here is
    k = " ".join(timers.fold(text).replace("%", " ").split())
    out = []
    m = VOLUME_RE.fullmatch(k)
    if m:
        now, muted = volume_of("@DEFAULT_AUDIO_SINK@")
        if now is None:
            return []
        state = "muted" if muted else f"{now}%"
        arg = m[1]
        if arg in UP_WORDS or arg in DOWN_WORDS or (arg and arg[0] in "+-"):
            step = int(arg) if arg[0] in "+-" else (VOLUME_STEP if arg in UP_WORDS else -VOLUME_STEP)
            arg = str(now + step)
        cap = volume_cap()
        if arg and arg.isdigit():
            pct = max(0, min(cap, int(arg)))
            # Over 100 only with over-amplification on; say why it stopped.
            why = "  ·  over 100 % needs over-amplification (Settings > Sound)" if int(arg) > cap == 100 else ""
            out.append(Item(f"Volume  {pct}%", f"now {state}  ·  Enter sets it{why}", "audio-volume-high",
                            lambda p=pct: set_volume(p)))
        elif arg in ("mute", "silencio", "unmute") or arg is None:
            out.append(Item("Unmute" if muted else "Mute", f"volume {state}  ·  Enter "
                            + ("unmutes" if muted else "mutes"), "audio-volume-muted",
                            lambda: spawn(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])))
            if arg is None:
                out += [Item(f"Volume  {p}%", f"now {state}  ·  Enter sets it", "audio-volume-high",
                             lambda p=p: set_volume(p)) for p in (25, 50, 75, 100, 125, 150) if p != now and p <= cap]
    m = MIC_RE.fullmatch(k)
    if m:
        now, muted = volume_of("@DEFAULT_AUDIO_SOURCE@")
        want = None if not m[1] else m[1] in ON_WORDS
        if now is not None and want != (not muted):
            out.append(Item("Microphone on" if muted else "Microphone off",
                            f"now {'muted' if muted else 'on'}  ·  Enter switches it", "audio-input-microphone",
                            lambda: spawn(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"])))
        elif now is not None:
            out.append(Item(f"Microphone is already {'on' if want else 'muted'}", "nothing to do",
                            "audio-input-microphone"))
    m = OUTPUT_RE.fullmatch(k)
    if m:
        want = m[1] or ""
        for sid, name, default in sinks():
            if all(w in name.lower() for w in want.split()):
                out.append(Item(f"Sound out of: {name}", "playing here now" if default else "Enter switches to it",
                                "audio-speakers", None if default else
                                (lambda s=sid: spawn(["wpctl", "set-default", s]))))
    out += screen_items(k)
    out += rate_items(k)
    out += accent_items(k)
    out += emergency_items(k)
    out += ask_desktop_items(text)      # the typed text, not k: keep case and accents
    m = RADIO_RE.fullmatch(k)
    if m:
        kind = "bluetooth" if m[1] in ("bluetooth", "bt") else "wifi"
        label = "Bluetooth" if kind == "bluetooth" else "Wi-Fi"
        on = radio_state(kind)
        want = (not on) if not m[2] else m[2] in ON_WORDS
        if want == on:
            out.append(Item(f"{label} is already {'on' if on else 'off'}", "nothing to do",
                            "bluetooth" if kind == "bluetooth" else "network-wireless"))
        else:
            out.append(Item(f"{label} {'on' if want else 'off'}", f"now {'on' if on else 'off'}  ·  Enter switches it",
                            "bluetooth" if kind == "bluetooth" else "network-wireless",
                            lambda w=want: radio(kind, w)))
    return out


# -- "continue watching": what mpv stopped in the middle of --------------------

WATCH_LATER = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                           "mpv", "watch_later")
RESUME_WORDS = ("continue", "continue watching", "resume", "watch", "seguir", "seguir viendo", "continuar")
RESUME_SKIP = ("/Wallpapers/",)     # the old mpvpaper wallpapers left resume files too
RESUME_MIN_S = 30                   # stopped earlier than this: not worth resuming
RESUME_LIMIT = 8
_RESUME = (0.0, [])                 # (when read, [(mtime, path or URL, seconds)])


def resume_entries():
    """mpv's resume files, newest first. mpv.conf has
    write-filename-in-watch-later-config, so each names its file on the first
    line; older ones are only an MD5 of the path, matched against GTK's
    recently used files. Read again at most every 5 s."""
    global _RESUME
    if time.time() - _RESUME[0] < 5:
        return _RESUME[1]
    import hashlib
    recent, rows = None, []
    try:
        names = os.listdir(WATCH_LATER)
    except OSError:
        names = []
    for name in names:
        path = os.path.join(WATCH_LATER, name)
        try:
            mtime = os.path.getmtime(path)
            with open(path, encoding="utf-8", errors="replace") as handle:
                head = handle.read(4096)
        except OSError:
            continue
        start = re.search(r"^start=([\d.]+)", head, re.M)
        if head.startswith("# redirect entry") or not start or float(start[1]) < RESUME_MIN_S:
            continue
        where = head.split("\n", 1)[0][2:] if head.startswith("# ") else None
        if where is None:
            if recent is None:
                recent = {}
                for info in Gtk.RecentManager.get_default().get_items():
                    if info.get_uri().startswith("file://"):
                        p = GLib.filename_from_uri(info.get_uri())[0]
                        recent[hashlib.md5(p.encode()).hexdigest().upper()] = p
            where = recent.get(name)
        if not where or any(s in where for s in RESUME_SKIP) \
                or ("://" not in where and not os.path.exists(where)):
            continue
        rows.append((mtime, where, float(start[1])))
    rows.sort(reverse=True)
    _RESUME = (time.time(), rows)
    return rows


def resume_item(mtime, where, start):
    url = "://" in where
    name = urllib.parse.unquote(where.rstrip("/").rsplit("/", 1)[-1]) or where
    if not url:
        name = os.path.splitext(name)[0]
    place = urllib.parse.urlparse(where).netloc if url else short(os.path.dirname(where))
    item = Item(f"Continue: {name}", f"from {timers.clock(start)}  ·  {ago(time.time() - mtime)}  ·  {place}",
                "media-playback-start", lambda w=where: spawn(in_scope(["mpv", w])),
                alt=None if url else (lambda w=where: spawn(["nautilus", "--select", w])))
    item.key = "watch:" + where
    if not url:
        item.path = where
    return item


SESSION_WORDS = ("session", "sessions", "sesion", "sesiones", "workspace session", "workspace sessions")
SAVE_SESSION_RE = re.compile(r"(?:save|guardar)\s+(?:the\s+|la\s+)?(?:session|sesi[oó]n)\s+(?:as\s+|como\s+)?(.+)",
                             re.I)
WHERE_WORDS = ("where was i", "donde estaba", "donde me quede", "last session", "ultima sesion")


def session_items(text):
    """Workspace sessions (sessions.py): "session(s)" / "sesión" lists the
    saved ones and the last one before this login, "session <words>" the
    ones named so -- Enter restores; "save session <name>" saves the windows
    open now; "where was I" restores the last session."""
    if text[:1] in "=>#:$!?/~" or is_long(text):
        return []
    q = " ".join(text.strip().split())
    m = SAVE_SESSION_RE.fullmatch(q)
    if m:
        name = m[1].strip()
        if not session_store.valid_name(name):
            return []
        return [Item(f"Save session: {name}", "the windows open now -- apps, folders, workspaces, places  ·  "
                     "Enter saves", "document-save", lambda n=name: spawn([SESSIONS, "save", n]))]
    k = place_key(q)
    out = []
    if k in WHERE_WORDS or k in SESSION_WORDS:
        last = session_store.last_session()
        if last:
            info = session_store.summary("last", last)
            out.append(Item("Where was I: restore the last session",
                            f"{info['windows']} windows from {session_store.when(info['saved'])}  ·  {info['apps']}",
                            "view-restore", lambda: spawn([SESSIONS, "where-was-i"])))
    words = k.split()
    two = " ".join(words[:2]) in SESSION_WORDS
    if words and (two or words[0] in SESSION_WORDS):
        rest = " ".join(words[2:] if two else words[1:])
        for s in session_store.sessions():
            if rest in place_key(s["name"]):
                out.append(Item(f"Session: {s['name']}", f"{s['windows']} windows  ·  {s['apps']}  ·  "
                                "Enter restores what is not open", "view-restore",
                                lambda n=s["name"]: spawn([SESSIONS, "restore", n])))
        if not rest:
            hint = Item("Save session: <name>", "the windows open now under a name  ·  Enter, then type it",
                        "document-save")
            hint.goto = "save session "
            out.append(hint)
    return out


CONTEXT_WORDS = ("project", "projects", "proyecto", "proyectos", "ctx", "context", "contexts", "contexto",
                 "contextos")
LEAVE_CONTEXT = ("leave project", "leave context", "salir del proyecto", "dejar proyecto", "ctx leave")


def project_items(text):
    """Project contexts (contexts.py): "project" / "ctx" / "proyecto" lists
    them -- Enter switches into one, Shift+Enter saves the windows open now
    as its layout -- and "Leave project <name>" when you are in one;
    "project <words>" only those named so, and a repo in your projects folder with
    that name and no context yet as "New project" (Enter makes it, with the
    defaults, and enters it); "leave project" leaves."""
    if text[:1] in "=>#:$!?/~" or is_long(text):
        return []
    k = place_key(text)
    words = k.split()
    if k not in LEAVE_CONTEXT and (not words or words[0] not in CONTEXT_WORDS):
        return []       # every keystroke comes here: read nothing for other text
    current = context_store.state()
    leave = Item(f"Leave project {current.get('name', '')}", "stop its preview, its notification filter, "
                 "clear the bar  ·  Enter leaves", "go-previous",
                 lambda: spawn([CONTEXTS, "leave"])) if current else None
    if k in LEAVE_CONTEXT:
        return [leave] if leave else []
    if not words or words[0] not in CONTEXT_WORDS:
        return []
    rest = " ".join(words[1:])
    contexts, _ = context_store.load()
    out = [leave] if leave and not rest else []
    for c in contexts:
        if rest and rest not in place_key(c["name"]):
            continue
        on = [w for w, yes in (("terminal", c["terminal"]), ("editor", c["editor"]),
                               ("its session", c["session"]), ("preview", c["preview"] != "off"),
                               ("only its notifications", c["focus"] == "project"),
                               ("Do Not Disturb", c["focus"] == "dnd")) if yes]
        here = current.get("name", "").lower() == c["name"].lower()
        out.append(Item(f"Project: {c['name']}" + ("  (you are in it)" if here else ""),
                        f"{c['repo']}  ·  {', '.join(on) or 'nothing to open'}  ·  "
                        "Shift+Enter saves the open windows as its layout", "folder-open",
                        lambda n=c["name"]: spawn([CONTEXTS, "enter", n]),
                        alt=lambda n=c["name"]: spawn([CONTEXTS, "save", n])))
    if rest and not any(rest == place_key(c["name"]) for c in contexts):
        for path in context_store.free_repos(contexts):
            name = os.path.basename(path)
            if place_key(name).startswith(rest) and context_store.valid_name(name):
                out.append(Item(f"New project: {name}", f"{context_store.short(path)}  ·  a context with the "
                                "defaults (Settings > Project contexts changes them)  ·  Enter makes it and "
                                "enters it", "folder-new",
                                lambda n=name, p=path: spawn([CONTEXTS, "new", n, "--repo", p, "--enter"])))
                if len(out) >= 6:
                    break
    return out


def resume_items(text):
    """(answers, matches): every unfinished video for "continue" / "resume"
    / "watch"; otherwise the ones whose name has every typed word."""
    if text[:1] in "=>#:$!?/~" or is_long(text):
        return [], []
    k = place_key(text)
    if not k:
        return [], []
    if k in RESUME_WORDS:
        return [resume_item(*row) for row in resume_entries()[:RESUME_LIMIT]], []
    if len(k) < 3:
        return [], []
    words = k.split()
    return [], [resume_item(*row) for row in resume_entries()
                if all(w in place_key(row[1].rsplit("/", 1)[-1]) for w in words)][:3]


def place_items(text, places, webs):
    if places is None or text[:1] in "=>#:$!" or is_long(text):
        return []
    # GNOME Maps by name: the system's geo: default here is a web handler
    # (cartes-geo-handler), and a pin should open in the map app.
    maps = next((i for i in Gio.AppInfo.get_all_for_type("x-scheme-handler/geo")
                 if i.get_id() == "org.gnome.Maps.desktop"), None) or \
        Gio.AppInfo.get_default_for_type("x-scheme-handler/geo", False)
    items = []
    for name, state, country, pop, lat, lon, _tz in places.find(text):
        where = ", ".join(x for x in (state, country) if x and x != name)
        label = ", ".join(x for x in (name, state, country) if x)
        gmaps = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(label)
        run = (lambda u=f"geo:{lat},{lon}": open_in(maps, u)) if maps else \
              ((lambda u=gmaps: open_in(webs[0], u)) if webs else None)
        items.append(Item(name, f"{where}  ·  {pop:,} people   --   Enter: map, Shift+Enter: Google Maps",
                          (maps.get_icon() if maps else None) or "find-location", run,
                          extra=label, alt=(lambda u=gmaps: open_in(webs[0], u)) if webs else None))
    return items


# -- maps -----------------------------------------------------------------------
def maps_items(text, webs):
    query = text.strip()
    if len(query) < 3 or len(query) > MAX_QUERY:
        return []
    gmaps = "https://www.google.com/maps/search/" + urllib.parse.quote(query)
    maps = Gio.AppInfo.get_default_for_type("x-scheme-handler/maps", False)
    if maps:
        return [Item(f"Find in {maps.get_display_name()}", f"places: {query}   --   Shift+Enter: Google Maps",
                     maps.get_icon(), lambda: open_in(maps, "maps:q=" + urllib.parse.quote(query)),
                     alt=(lambda: open_in(webs[0], gmaps)) if webs else None)]
    return [Item("Find on Google Maps", f"places: {query}", "find-location",
                 (lambda: open_in(webs[0], gmaps)) if webs else None)] if webs else []


# -- the web -------------------------------------------------------------------
SEARCH_NAME = "DuckDuckGo"
SEARCH_URL = "https://duckduckgo.com/?q={}"
MAX_QUERY = 400         # longer than this is text to keep, not to search for
URL_RE = re.compile(r"^(https?://\S+|(localhost|[\w-]+(\.[\w-]+)+)(:\d+)?([/?#]\S*)?)$", re.I)


# Shorter tile labels than the .desktop names ("Web" says nothing on a tile).
BROWSER_NAMES = {"org.gnome.Epiphany.desktop": "Epiphany", "chromium-browser.desktop": "Chromium",
                 "com.kagi.OrionGtk.desktop": "Orion"}


def browsers():
    """Installed web browsers: the default one, then the other https
    handlers, then any other app filed under WebBrowser (Orion's flatpak
    registers no MIME types at all)."""
    default = Gio.AppInfo.get_default_for_type("x-scheme-handler/https", False)
    candidates = ([default] + list(Gio.AppInfo.get_all_for_type("x-scheme-handler/https"))
                  + sorted(Gio.AppInfo.get_all(), key=lambda i: (i.get_display_name() or "").lower()))
    out, seen = [], set()
    for info in candidates:
        if not info or info.get_id() in seen or not info.should_show():
            continue
        if "WebBrowser" not in (getattr(info, "get_categories", lambda: "")() or "").split(";"):
            continue
        seen.add(info.get_id())
        out.append(info)
    return out


def as_url(text):
    """`text` as an address to open, or None. "github.com/x" yes; "v1.2" and
    "2.5" no (the last part has to be letters, 2+)."""
    text = text.strip()
    if not URL_RE.match(text):
        return None
    if text.lower().startswith(("http://", "https://")):
        return text
    host = re.split(r"[/:?#]", text, 1)[0]
    tld = host.rsplit(".", 1)[-1]
    if host != "localhost" and not (tld.isalpha() and len(tld) >= 2):
        return None
    return ("http://" if host == "localhost" else "https://") + text


def open_in(info, uri):
    if not info.supports_uris():
        # No %u in its Exec= (Orion's flatpak): the address goes on the end
        # of its command line, which is what a browser takes it as anyway.
        import shlex
        spawn(shlex.split(info.get_commandline() or "") + [uri])
    elif UNDER_UWSM and info.get_id():
        spawn(["uwsm", "app", "--", info.get_id(), uri])
    else:
        info.launch_uris([uri], Gdk.Display.get_default().get_app_launch_context())


def web_items(text, infos):
    query = text.strip()
    if not query or len(query) > MAX_QUERY:
        return []
    url = as_url(query)
    target = url or SEARCH_URL.format(urllib.parse.quote_plus(query))
    items = []
    for i, info in enumerate(infos):
        name = BROWSER_NAMES.get(info.get_id()) or info.get_display_name() or info.get_name()
        verb = "Open in" if url else "Search in"
        sub = url if url else f"{SEARCH_NAME}: {query}"
        items.append(Item(f"{verb} {name}", sub + ("   (default browser)" if i == 0 else ""),
                          info.get_icon(), lambda inf=info: open_in(inf, target)))
    return items


def all_apps():
    seen, apps = set(), []
    for info in Gio.AppInfo.get_all():
        if not hasattr(info, "get_keywords") or not info.should_show():
            continue
        app = App(info)
        if app.id in seen:
            continue
        seen.add(app.id)
        apps.append(app)
    return apps


def fuzzy(needle, hay):
    pos = 0
    for ch in needle:
        pos = hay.find(ch, pos) + 1
        if not pos:
            return False
    return True


def score(app, query):
    """Higher is better; None means no match."""
    if app.lname.startswith(query):
        return 500 - len(app.lname)
    if any(word.startswith(query) for word in app.lname.split()):
        return 400 - len(app.lname)
    if query in app.lname:
        return 300 - app.lname.index(query)
    if query in app.extra:
        return 200
    if fuzzy(query, app.lname):
        return 100 - len(app.lname)
    return None


def rank(apps, query, usage):
    query = query.strip().lower()
    if not query:
        return sorted(apps, key=lambda a: (-usage.get(a.id, 0), a.lname))
    hits = [(score(a, query), a) for a in apps]
    hits = [(s, a) for s, a in hits if s is not None]
    hits.sort(key=lambda sa: (-sa[0], -usage.get(sa[1].id, 0), sa[1].lname))
    return [a for _, a in hits]


# -- keyboard shortcuts (launcher_shortcuts.py) ------------------------------------------
SHORTCUT_ICON = "input-keyboard"


def shortcut_items(binds=None):
    """One Item per shortcut with a description (`hyprctl binds -j`, or the
    `binds` given): named for what it does, its keys and section under it.
    Enter runs the bind after the card has gone (spawn_argv). Matched on
    the name and the section only -- not the keys, or "alt" would bring up
    every ALT shortcut among the apps; "keys alt" does that (shortcut_matches)."""
    found = launcher_shortcuts.entries(launcher_shortcuts.read_binds() if binds is None else binds)
    out = []
    for e in found:
        item = Item(e["text"], f"{e['label']}  ·  {e['section']} shortcut", SHORTCUT_ICON,
                    (lambda e=e: spawn(launcher_shortcuts.spawn_argv(e, NOTIFY))))
        item.extra = f"{e['section']} shortcut".lower()
        item.key = "keys:" + e["keys"]
        item.entry = e
        out.append(item)
    return out


def shortcut_matches(shortcuts, words):
    """"keys <words>": the shortcuts every word finds (launcher_shortcuts.
    matches: keys by name, the description by its words), exactly the keys
    typed first; all of them for none."""
    shortcuts = list(shortcuts)
    if not words.strip():
        return shortcuts or [Item("No shortcuts", "Hyprland gave no binds (hyprctl binds -j)", SHORTCUT_ICON)]
    hits = launcher_shortcuts.matches([i.entry for i in shortcuts], words)
    by_entry = {id(i.entry): i for i in shortcuts}
    return [by_entry[id(e)] for e in hits] or \
        [Item("No shortcut has those words", "try fewer words, or the keys: \"keys super s\"", SHORTCUT_ICON)]


# -- passwords (launcher_secrets.py) ---------------------------------------------------
PASSWORD_ICON = "dialog-password"
KEEPASSXC_DESKTOP = "org.keepassxc.KeePassXC.desktop"


def desktop_app(desktop_id):
    """The installed app with this .desktop id, or None. (PyGObject raises
    TypeError "constructor returned NULL" for one that is not installed,
    instead of giving None.)"""
    try:
        return Gio.DesktopAppInfo.new(desktop_id)
    except (TypeError, GLib.Error):
        return None


def wants_passwords(text):
    """"pw" or "pw <words>" (not "pwd", nor "password": that one makes one)."""
    low = text.lower()
    return low.strip() == "pw" or low.startswith("pw ")


def copy_password(path):
    """Enter on a password row: launcher_secrets.py fetches the secret, copies
    it and clears it after CLEAR_AFTER s, in a process of its own (it may
    first wait for the provider's "allow access?" and it outlives the card)
    -- so the secret never passes through the launcher at all."""
    spawn(launcher_secrets.copy_argv(path))


def unlock_passwords(index, paths):
    index.forget()
    spawn(launcher_secrets.unlock_argv(paths))


def password_items(words, index):
    """"pw <words>": the matching entries of the Secret Service provider, or
    one row that says why there are none (nothing running, nothing shared,
    locked) and, where it can, does something about it on Enter."""
    got = index.get() if index else None
    if got is None:
        return [Item("Looking in your password manager…", "the Secret Service (org.freedesktop.secrets)",
                     PASSWORD_ICON)]
    provider, state = got["provider"], got["state"]
    if state in ("none", "error"):
        app = desktop_app(KEEPASSXC_DESKTOP)
        why = ("no password manager answers on the Secret Service" if state == "none"
               else f"{provider} did not answer ({got.get('error', 'error')})")
        return [Item("Unlock KeePassXC / enable Secret Service integration",
                     f"{why}: start KeePassXC with Tools > Settings > Secret Service Integration on"
                     + ("  ·  Enter opens KeePassXC" if app else "  (KeePassXC is not installed; "
                        "any Secret Service provider works)"),
                     PASSWORD_ICON, (lambda: launch(App(app))) if app else None)]
    if state == "empty":
        return [Item("Enable Secret Service integration",
                     f"{provider} shares no passwords: in KeePassXC, Database > Database settings > "
                     "Secret Service Integration, pick the group to expose", PASSWORD_ICON)]
    out = []
    for row in launcher_secrets.search(got["items"], words):
        label = row["label"] or "(no name)"
        item = Item(label, launcher_secrets.subtitle(row, provider), PASSWORD_ICON,
                    (lambda p=row["path"]: copy_password(p)))
        item.key = None         # never learned: no password names in launcher-picks.json
        out.append(item)
    if got["locked"]:
        n = len(got["locked"])
        unlock = Item(f"Unlock {provider}" if state == "locked" else f"Unlock {n} more in {provider}",
                      f"{n} locked {'collection' if n == 1 else 'collections'}  ·  Enter asks {provider} "
                      "to unlock (its own window)", "changes-allow",
                      (lambda paths=list(got["locked"]): unlock_passwords(index, paths)))
        unlock.key = None
        out.append(unlock)
    if not out:
        out = [Item("No password matches", f"nothing in {provider} has those words", PASSWORD_ICON)]
        out[0].key = None
    return out


def results(apps, commands, text, usage, windows=(), files=(), webs=(), clips=(), quotes=(),
            places=None, quick=None, shortcuts=(), secrets=None):
    """Everything the box should show for what is typed, best first.
    `files` and `quotes` are the slow searches' items for this text (they
    arrive later, from a thread); `webs` the installed browsers; `clips` the
    clipboard history rows; `quick` the ?? answer's QuickAnswer, if any;
    `shortcuts` shortcut_items(); `secrets` the launcher_secrets.Index."""
    mode, rest = (text[:1], text[1:].strip()) if text[:1] in "=>#:!" else ("", text)
    if mode == "!":
        return run_items(rest)
    if text[:2] == "??":
        return quick_items(text[2:].strip(), quick)
    if text[:1] == "?":
        return ask_items(text[1:])
    # text[:1] AND: "" is "in" every string, so an empty box was path mode.
    if text[:1] and text[:1] in "/~":
        return path_items(text)
    only = launcher_shortcuts.wants_only(text)
    if only is not None:
        return shortcut_matches(shortcuts, only)
    if wants_passwords(text):
        return password_items(text.strip()[2:].strip(), secrets)
    if mode == ">":
        return rank(commands, rest, {}) + settings_items(rest, explicit=True) if rest else commands
    if mode == "=":
        item = calc_item(rest) if rest else None
        return [item] if item else [Item("Calculator", "type an expression: 2^10, 17% of 340, sqrt(2)",
                                         "accessories-calculator")]
    if mode == "#":
        # A whole colour typed ("#3ddc68", "#fff"): its hex / rgb / hsl
        # first, then the history entries that match.
        items = colour_items()
        return colour_tool(text.strip().lower()) + \
            ([i for i in items if rest.lower() in i.lname] if rest else items)
    if mode == ":":
        return emoji_items(rest) if rest else [Item("Emoji", "type a name: fire, heart, thumbs up", glyph="\U0001F642")]
    if is_long(text):
        # A paste, not a query: nothing would match it anyway.
        return long_text_items(text) + [chat_item(text.strip(), f"Ask {asked(None)} about this")] \
            + web_items(text, webs)
    watching, watched = resume_items(text)
    answers = (timer_items(text) + session_items(text) + project_items(text) + setting_items(text) + watching + kill_items(text) + window_action_items(text) + conversion_items(text) + time_items(text, places) + date_items(text)
               + tool_items(text)
               + airport_items(text, places, webs) + list(quotes))
    out = rank(apps, text, usage)
    if text.strip():
        out = out[:MAX_APPS]
    if answers or calc_item(text):
        clips = ()      # "100 f to c": every word is in some old clipboard entry
    elif text.strip():
        # A place goes after the apps whose name or one of its words STARTS
        # with the query (score > 300: "steam" is Steam, "setti" Qt5
        # Settings, not a town), before the weaker matches.
        query = text.strip().lower()
        strong = 0
        while strong < len(out) and (score(out[strong], query) or 0) > 300:
            strong += 1
        out = out[:strong] + place_items(text, places, webs) + out[strong:]
    if len(text.strip()) >= 2:
        # Windows and commands join the app results, after the apps that
        # match as well: "record" finds the recorder commands, "firefox"
        # still opens Firefox, then the Firefox window that is already open.
        # Word and substring matches only (score >= 200): fuzzy letter-order
        # matches are fine among apps, but noise in a list of commands.
        query = text.strip().lower()
        out += [w for w in rank(list(windows), text, {}) if (score(w, query) or 0) >= 200]
        # The Settings pages before the commands: "bluetooth" is the page
        # first, then "Airplane mode on / off" and the like.
        out += settings_items(text)
        out += [c for c in rank(commands, text, {}) if (score(c, query) or 0) >= 200]
        # The shortcuts after the commands: "terminal" is the app first, its
        # keys further down ("ALT + Q  ·  Apps shortcut").
        out += [k for k in rank(list(shortcuts), text, {}) if (score(k, query) or 0) >= 200]
        out += clip_items(clips, text)
    shown = {w.path for w in watched if getattr(w, "path", None)}
    out += watched + [f for f in files if getattr(f, "path", None) not in shown]
    if not answers:
        out += inline_emoji(text)
    out += ([chat_item(text.strip())] if wants_ask(text) else []) \
        + web_items(text, webs) + maps_items(text, webs)
    item = calc_item(text)
    return ([item] if item else []) + answers + out


def launch(app):
    bump_usage(app.id)
    if UNDER_UWSM and app.id:
        # Its own systemd scope in the session, like every uwsm-launched app.
        remember(subprocess.Popen(["uwsm", "app", "--", app.id], start_new_session=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    else:
        app.info.launch([], Gdk.Display.get_default().get_app_launch_context())


# -- learning what you pick ------------------------------------------------------------
# Every pick is counted under each beginning of what was typed ("s", "st",
# "ste" for Steam picked after "ste"), so the next time those letters are
# typed it comes first. Counts fade with PICK_HALF_LIFE; a stale habit
# gives way to a new one.
PICKS_FILE = os.path.expanduser("~/.cache/launcher-picks.json")
PICK_HALF_LIFE = 21 * 86400
PICK_PREFIX_MAX = 24        # longer queries are remembered by their first 24 letters
PICK_KEEP = 6               # results remembered per beginning
PICK_TABLES = 4000          # beginnings kept (the least recently used go)
PICK_MIN = 0.6              # a weight this high moves a result to the front


def pick_query(text):
    """What a pick is filed under, or None (a prompt, a command line or a
    paste is never the same twice)."""
    q = " ".join(text.lower().split())
    if not q or q[:1] in "?!" or is_long(text):
        return None
    return q[:PICK_PREFIX_MAX]


def load_picks():
    try:
        with open(PICKS_FILE) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def pick_weight(entry, now):
    count, last = entry
    return count * 0.5 ** ((now - last) / PICK_HALF_LIFE)


def record_pick(picks, text, key):
    q = pick_query(text)
    if q is None or not key:
        return
    now = time.time()
    for n in range(1, len(q) + 1):
        table = picks.setdefault(q[:n], {})
        count = pick_weight(table[key], now) if key in table else 0.0
        table[key] = [count + 1, now]
        if len(table) > PICK_KEEP:
            weakest = min(table, key=lambda k: pick_weight(table[k], now))
            del table[weakest]
    if len(picks) > PICK_TABLES:
        newest = lambda p: max((e[1] for e in picks[p].values()), default=0)     # noqa: E731
        for p in sorted(picks, key=newest)[:len(picks) - PICK_TABLES]:
            del picks[p]
    save_picks(picks)


def save_picks(picks):
    try:
        os.makedirs(os.path.dirname(PICKS_FILE), exist_ok=True)
        tmp = PICKS_FILE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(picks, handle, separators=(",", ":"))
        os.replace(tmp, PICKS_FILE)
    except OSError:
        pass


def forget_pick(picks, key):
    for table in picks.values():
        table.pop(key, None)
    save_picks(picks)


def learned_order(found, text, picks, apps=()):
    """`found` with what was picked before for these letters moved to the
    front, the most picked first; an app picked before but not in `found`
    (cut off by MAX_APPS) is brought back. The rest keep their order."""
    q = pick_query(text)
    table = picks.get(q) if q else None
    if not table:
        return found
    now = time.time()
    weights = {k: pick_weight(e, now) for k, e in table.items()}
    weights = {k: w for k, w in weights.items() if w >= PICK_MIN}
    if not weights:
        return found
    have = {getattr(i, "key", None) for i in found}
    extra = [a for a in apps if a.key in weights and a.key not in have]
    learned = [i for i in list(found) + extra if getattr(i, "key", None) in weights]
    learned.sort(key=lambda i: -weights[i.key])
    seen = set()
    front = []
    for i in learned:
        if i.key not in seen:
            seen.add(i.key)
            front.append(i)
    return front + [i for i in found if getattr(i, "key", None) not in seen]


# -- the clipboard, when the box is empty ------------------------------------------------
CLIP_FRESH_S = 600          # a copy is offered for 10 min after the launcher first sees it
CLIP_READ_MAX = 20000
ERROR_RE = re.compile(r"Traceback \(most recent|(?<![\w-])(?:error|exception|fatal|panic|failed|"
                      r"segmentation fault|denied|not found)\b", re.I)


def read_clipboard():
    """("image", mime) or ("text", text) or None -- what is on the
    clipboard now."""
    try:
        types = subprocess.run(["wl-paste", "-l"], capture_output=True, text=True,
                               timeout=1).stdout.split()
        if "x-kde-passwordManagerHint" in types:
            return None     # a password (wl-copy --sensitive: "pw" Enter): never shown back
        image = next((t for t in types if t.startswith("image/")), None)
        if image:
            return "image", image
        if not any(t.startswith("text/") or t in ("UTF8_STRING", "STRING", "TEXT") for t in types):
            return None
        out = subprocess.run(["wl-paste", "-n", "-t", "text/uri-list" if "text/uri-list" in types else "text"],
                             capture_output=True, timeout=1).stdout[:CLIP_READ_MAX]
        text = out.decode("utf-8", "replace")
        return ("text", text) if text.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def save_clip_image(mime):
    folder = os.path.join(HOME, "Pictures", "Clipboard")
    os.makedirs(folder, exist_ok=True)
    ext = mime.split("/")[1].split("+")[0].replace("jpeg", "jpg")
    path = os.path.join(folder, time.strftime(f"clipboard-%Y%m%d-%H%M%S.{ext}"))
    with open(path, "wb") as handle:
        subprocess.run(["wl-paste", "-n", "-t", mime], stdout=handle, timeout=5)
    spawn([NOTIFY, "-a", "Launcher", "-i", "image-x-generic", "Image saved", path.replace(HOME, "~", 1)])


def clip_paths(text):
    """The existing files a copy names: file:// lines (a copy in Files) or
    a path typed out ("~/Downloads/x.pdf", "/etc/hosts")."""
    out = []
    for line in text.strip().splitlines()[:20]:
        line = line.strip()
        if line.startswith("file://"):
            line = urllib.parse.unquote(urllib.parse.urlparse(line).path)
        elif not line.startswith(("/", "~/")):
            return []
        line = os.path.expanduser(line)
        if not os.path.exists(line):
            return []
        out.append(line)
    return out


def clip_suggestions(kind, value, webs, places):
    """A few things to do with what was just copied, best first."""
    if kind == "image":
        return [Item(f"Ask {asked(None)} about the copied image", "what it shows" + tui_hint(None),
                     CHAT_ICON, lambda: ask_about_clipboard(CLIP_PROMPT, None),
                     alt=(lambda: ask_about_clipboard(CLIP_PROMPT, None, tui=True)) if tui_ok(None) else None),
                Item("Save the copied image", "into ~/Pictures/Clipboard/", "image-x-generic",
                     lambda m=value: save_clip_image(m))]
    text = value.strip()
    paths = clip_paths(text)
    if paths:
        return [file_item(p) for p in paths[:3]]
    if as_url(text) and "\n" not in text:
        return web_items(text, webs)[:1] + [Item(f"Ask {asked(None)} about this link", text, CHAT_ICON,
                                                 lambda: ask_chat(f"Look at {text} and tell me what it is about"))]
    if ERROR_RE.search(text) and (len(text) > 30 or "\n" in text):
        return [Item(f"Ask {asked(None)} about this error", " ".join(text.split())[:90], CHAT_ICON,
                     lambda: ask_about_clipboard("Explain this error and how to fix it", None),
                     alt=(lambda: ask_about_clipboard("Explain this error and how to fix it", None, tui=True))
                     if tui_ok(None) else None)]
    if is_long(text):
        return [Item(f"Ask {asked(None)} about the copied text", " ".join(text.split())[:90], CHAT_ICON,
                     lambda: ask_about_clipboard(CLIP_PROMPT, None))] + long_text_items(text)[:2]
    answers = (conversion_items(text) + time_items(text, places) + date_items(text) + tool_items(text))
    calc = calc_item(text)
    if calc or answers:
        return ([calc] if calc else []) + answers[:2]
    return web_items(text, webs)[:1]


# -- Tab: what else can be done with a result ---------------------------------------------
def alt_label(item):
    """What Shift+Enter does, from the item's own line ("Shift+Enter: show
    in Files"), or a plain name for it."""
    m = re.search(r"Shift\+Enter:?\s*([^·\-–—]+)", item.subtitle() or "")
    return m[1].strip().rstrip(",") if m else "the other action (Shift+Enter)"


def bring_window(address):
    try:
        here = json.loads(subprocess.run(["hyprctl", "activeworkspace", "-j"], capture_output=True,
                                         text=True, timeout=1).stdout).get("id")
    except (OSError, subprocess.SubprocessError, ValueError):
        return
    window_action(address, f"hl.dsp.window.move({{ workspace = '{here}', follow = true }})")


def ask_about(name, sub):
    ask_chat(f"Tell me about this: {name}" + (f" ({sub})" if sub else ""))


def item_actions(item, launcher):
    """The actions list Tab shows for `item`: its own Enter and Shift+Enter,
    then what fits its kind -- an app's own actions (New Window...), a
    file's "Open with", a window's "Close" -- then copy, ask the AI, search."""
    name, sub = item.name, item.subtitle() or ""
    acts = [Item(f"{name}", "Enter: what Enter does here", item.gicon() if not item.glyph else None,
                 item.run, glyph=item.glyph)]
    if getattr(item, "alt", None) and not getattr(item, "path", None):     # a file's: Show in Files, below
        label = alt_label(item)
        acts.append(Item(label[:1].upper() + label[1:], "Shift+Enter does this too", "go-next", item.alt))
    if isinstance(item, App):
        info = item.info
        ctx = Gdk.Display.get_default().get_app_launch_context()
        for act in (info.list_actions() if hasattr(info, "list_actions") else []):
            acts.append(Item(info.get_action_name(act), f"{name}'s own action", info.get_icon(),
                             lambda a=act: info.launch_action(a, ctx)))
        if info.get_commandline():
            acts.append(Item("Copy its command", info.get_commandline(), "edit-copy",
                             lambda c=info.get_commandline(): copy(c)))
        if getattr(info, "get_filename", None) and info.get_filename():
            acts.append(Item("Show its .desktop file", info.get_filename().replace(HOME, "~", 1),
                             "document-open", lambda f=info.get_filename(): spawn(["nautilus", "--select", f])))
        acts.append(Item("Forget what I picked it for", "it stops jumping to the front", "edit-clear",
                         lambda k=item.key: forget_pick(launcher.picks, k)))
    path = getattr(item, "path", None)
    if path:
        folder = os.path.dirname(path)
        try:
            ctype = Gio.File.new_for_path(path).query_info(
                "standard::content-type", Gio.FileQueryInfoFlags.NONE, None).get_content_type()
        except GLib.Error:
            ctype = None
        default = Gio.AppInfo.get_default_for_type(ctype, False) if ctype else None
        for info in (Gio.AppInfo.get_all_for_type(ctype) if ctype else [])[:6]:
            if default and info.get_id() == default.get_id():
                continue
            acts.append(Item(f"Open with {info.get_display_name()}", short(path), info.get_icon(),
                             lambda i=info: i.launch([Gio.File.new_for_path(path)], None)))
        acts += [Item("Show in Files", short(folder), "system-file-manager",
                      lambda: spawn(["nautilus", "--select", path])),
                 Item("Terminal here", short(folder), "utilities-terminal",
                      lambda: spawn(["kitty", "--directory", folder])),
                 Item("Copy its path", short(path), "edit-copy", lambda: copy(path)),
                 Item("Copy the file", "to paste in Files, a chat, an email", "edit-copy",
                      lambda: subprocess.run(["wl-copy", "-t", "text/uri-list"],
                                             input=Gio.File.new_for_path(path).get_uri() + "\r\n",
                                             text=True, timeout=3)),
                 Item(f"Ask {asked(None)} about this file", short(path), CHAT_ICON,
                      lambda: ask_chat(f"Look at the file {path} and tell me what it is", cwd=folder))]
    address = getattr(item, "address", None)
    if address:
        acts += [Item("Bring it here", "to this workspace", "window-new", lambda: bring_window(address)),
                 Item("Close it", "it may ask to save", "window-close",
                      lambda: window_action(address, "hl.dsp.window.close()"))]
    if not isinstance(item, App) and not path:
        acts.append(Item("Copy the text", name, "edit-copy", lambda: copy(name)))
    if not path:
        acts.append(Item(f"Ask {asked(None)} about it", f"{name}" + (f" · {sub}" if sub else ""), CHAT_ICON,
                         lambda: ask_about(name, sub)))
        acts += [w for w in web_items(name, launcher.browsers)[:1]]
    for act in acts:
        act.key = None          # an action is learned as the result it came from
    return acts


# -- the window ----------------------------------------------------------------
def focused_monitor(display):
    """The monitor Hyprland has focus on, matched to GDK by layout position
    (GDK names monitors by model, never by connector)."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True,
                             text=True, timeout=1).stdout
        for mon in json.loads(out):
            if mon.get("focused"):
                for i in range(display.get_n_monitors()):
                    box = display.get_monitor(i).get_geometry()
                    if (box.x, box.y) == (mon["x"], mon["y"]):
                        return display.get_monitor(i)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        pass
    return None


PLACEHOLDER = {
    "en": "apps, windows, files, the web     > commands   = calc   # colours   : emoji   ? ask AI   ?? quick   ?get models",
    # "search apps, files, the web ♡ ... commands, calculator, colours, emoji, ask the AI, quick answers, models"
    "ja": "アプリ・ファイル・ウェブをさがす ♡     > コマンド   = 計算   # 色   : 絵文字   ? AIにきく   ?? 即答   ?get モデル",
}


# A theme's own wording of the hint, over its language's. orbit: a console
# command line (the same keys, in the flight-console's capitals). orchard:
# one word, as a modern desktop's search field says it -- the prefixes still
# work, they are just not spelled out over the big light field.
THEME_PLACEHOLDER = {
    "orbit": "▸ apps, windows, files, the web     > CMD   = CALC   # COLOUR   : EMOJI   ? ASK AI   ?? QUICK   ?get MODELS",
    "orchard": "Search",
    "orchard-dark": "Search",
}


def placeholder():
    """The search box's hint: the theme's own (THEME_PLACEHOLDER), else in
    the desktop theme's language (lang=)."""
    try:
        own = THEME_PLACEHOLDER.get(desktop_theme.current())
        return own or PLACEHOLDER.get(desktop_theme.get("lang"), PLACEHOLDER["en"])
    except (OSError, ValueError):
        return PLACEHOLDER["en"]


def styled(widget, *classes):
    for cls in classes:
        widget.get_style_context().add_class(cls)
    return widget


def app_icon(app, size):
    if app.glyph:
        # Emoji: drawn as text, at about the icon's size.
        label = Gtk.Label()
        label.set_markup(f"<span size='{int(size * 0.75)}pt'>{app.glyph}</span>")
        return label
    image = Gtk.Image.new_from_gicon(app.gicon(), Gtk.IconSize.DIALOG)
    image.set_pixel_size(size)
    return image


class Launcher(Gtk.Window):
    def __init__(self, resident=False):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.resident = resident
        self.catchers = []
        self.apps = all_apps()
        self.commands = command_items()
        self.shortcuts = shortcut_items()
        self.secrets = launcher_secrets.Index(on_ready=lambda: GLib.idle_add(self.secrets_read))
        self.windows = window_items()
        self.browsers = browsers()
        # Typed a city before the index was in: show it now, not at the next key.
        self.places = Places(on_ready=lambda: self.refresh(keep_selection=True))
        self.clips = clip_history()
        self.usage = load_usage()
        self.picks = load_picks()
        self.clip_items = []        # what to do with a fresh copy, shown while the box is empty
        self.clip_seen = {}         # a copy's hash -> when the launcher first saw it
        self.clip_used = set()
        self.actions_back = None    # Tab's actions list is up: (results, selected) to go back to
        refresh_rates()
        refresh_models()
        self.files = []             # slow search results for self.files_for
        self.quotes = []
        self.files_for = None
        self.search_gen = 0         # the newest file search; older answers are dropped
        self.search_timer = 0
        self.quick = None           # the ?? answer (QuickAnswer) being shown / streamed
        self.quick_timer = 0
        self.hf_timer = 0           # ?get: the Hugging Face search waiting for typing to stop
        self.hf_asking = set()      # queries being searched now
        self.results = []
        self.selected = 0           # 0 = hero, 1.. = tiles
        self.launched = False

        self.set_name("launcher-window")
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "launcher")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        monitor = focused_monitor(self.get_display())
        if monitor:
            GtkLayerShell.set_monitor(self, monitor)

        card = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "card")
        card.set_name("card")
        self.add(card)

        self.entry = Gtk.Entry()
        self.entry.set_name("search")
        self.entry.set_placeholder_text(placeholder())
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY,
                                           "system-search-symbolic")
        self.entry.connect("changed", lambda _e: self.on_changed())
        self.entry.connect("activate", lambda _e: self.activate(self.selected))
        card.pack_start(self.entry, False, False, 0)

        # Hero: the best match, big.
        self.hero = styled(Gtk.EventBox(), "hero")
        self.hero.set_name("hero")
        self.hero.connect("button-release-event", lambda *_: self.activate(0))
        hero_row = Gtk.Box(spacing=22)
        # On the row, not as CSS padding: GTK3 ignores padding on an EventBox.
        hero_row.set_margin_top(16)
        hero_row.set_margin_bottom(16)
        hero_row.set_margin_start(24)
        hero_row.set_margin_end(22)
        self.hero_icon = Gtk.Image()
        hero_row.pack_start(self.hero_icon, False, False, 0)
        self.hero_glyph = Gtk.Label()
        self.hero_glyph.set_no_show_all(True)
        hero_row.pack_start(self.hero_glyph, False, False, 0)
        hero_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hero_text.set_valign(Gtk.Align.CENTER)
        self.hero_name = styled(Gtk.Label(xalign=0), "hero-name")
        self.hero_name.set_ellipsize(Pango.EllipsizeMode.END)
        self.hero_name.set_no_show_all(True)        # shown, or not, by show_results
        # A ?? answer instead of the name: sentences, wrapped, in the
        # clipboard picker's hero text style (every theme has it).
        self.hero_answer = styled(Gtk.Label(xalign=0, yalign=0), "clip-hero-text")
        self.hero_answer.set_line_wrap(True)
        self.hero_answer.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.hero_answer.set_lines(7)
        self.hero_answer.set_ellipsize(Pango.EllipsizeMode.END)
        self.hero_answer.set_max_width_chars(72)
        self.hero_answer.set_no_show_all(True)
        self.hero_sub = styled(Gtk.Label(xalign=0), "hero-sub")
        self.hero_sub.set_ellipsize(Pango.EllipsizeMode.END)
        self.hero_sub.set_max_width_chars(60)
        hero_text.pack_start(self.hero_name, False, False, 0)
        hero_text.pack_start(self.hero_answer, False, False, 0)
        hero_text.pack_start(self.hero_sub, False, False, 0)
        hero_row.pack_start(hero_text, True, True, 0)
        self.hero_hint = styled(Gtk.Label(label="ENTER ↵"), "hero-hint")
        self.hero_hint.set_valign(Gtk.Align.CENTER)
        hero_row.pack_end(self.hero_hint, False, False, 0)
        self.hero.add(hero_row)
        card.pack_start(self.hero, False, False, 0)

        self.empty = styled(Gtk.Label(label="nothing matches"), "empty")
        self.empty.set_no_show_all(True)
        card.pack_start(self.empty, False, False, 0)

        # Everything else, in order: runs of tiles, and full-width rows for
        # the results that read better as a line (clipboard text).
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.list.set_name("tiles")
        self.list.set_valign(Gtk.Align.START)
        scroll = Gtk.ScrolledWindow()
        scroll.set_name("tiles-scroll")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(True)
        scroll.set_can_focus(False)
        scroll.add(self.list)
        self.scroll = scroll
        card.pack_start(scroll, True, True, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)
        self.refresh()
        if not resident:
            self.show_all()
            self.entry.grab_focus()
            self.make_catchers()
            self.check_clipboard()

    def make_catchers(self):
        # Under the card, over everything else: a click there missed it.
        try:
            import panelui
            display = self.get_display()
            self.catchers = [panelui.ClickCatcher(display.get_monitor(i), self.close)
                             for i in range(display.get_n_monitors())]
        except Exception as exc:        # the launcher still works without it
            print(f"launcher: no click-outside: {exc}", file=sys.stderr)
            self.catchers = []

    # -- resident (--daemon) -------------------------------------------------------
    def show_launcher(self, text=""):
        load_css()                      # a theme switch since the last time
        self.entry.set_placeholder_text(placeholder())
        monitor = focused_monitor(self.get_display())
        if monitor:
            GtkLayerShell.set_monitor(self, monitor)
        self.launched = False
        self.files, self.quotes, self.files_for = [], [], None
        self.stop_quick()
        self.entry.set_text(text)       # refresh()es through on_changed
        self.show_all()
        # Not grab_focus(): it selects the text, and the first key typed after
        # `launcher.py ">"` replaced the ">".
        self.entry.grab_focus_without_selecting()
        self.entry.set_position(-1)
        self.make_catchers()
        # The lists, fresh -- after the frame is up, not before it.
        GLib.idle_add(self.reload_lists)

    def reload_lists(self):
        if not self.get_visible():
            return False
        reap()
        self.apps = all_apps()
        self.commands = command_items()
        self.shortcuts = shortcut_items()
        self.windows = window_items()
        self.browsers = browsers()
        self.clips = clip_history()
        self.usage = load_usage()
        self.picks = load_picks()
        refresh_rates()
        refresh_models()
        self.refresh(keep_selection=True)
        self.check_clipboard()
        return False

    # -- the clipboard, offered while the box is empty --------------------------------
    def check_clipboard(self):
        """Read it in a thread (wl-paste: two forks), after the frame is up."""
        self.clip_items = []

        def work():
            got = read_clipboard()
            GLib.idle_add(self.clipboard_read, got)
        threading.Thread(target=work, daemon=True).start()

    def clipboard_read(self, got):
        if got is None or (self.resident and not self.get_visible()):
            return False
        import hashlib
        h = hashlib.sha1(f"{got[0]}\0{got[1]}".encode("utf-8", "replace")).hexdigest()
        first = self.clip_seen.setdefault(h, time.time())
        if h in self.clip_used or time.time() - first > CLIP_FRESH_S:
            return False
        items = clip_suggestions(got[0], got[1], self.browsers, self.places)[:3]
        for item in items:
            item.sub = "from the clipboard  ·  " + item.sub
            item.clip_hash = h
            item.key = None
        self.clip_items = items
        if not self.entry.get_text().strip():
            self.refresh(keep_selection=True)
        return False

    def secrets_read(self):
        """The password index landed (launcher_secrets.Index, its thread):
        redraw if "pw" is still what is typed."""
        if self.get_visible() and wants_passwords(self.entry.get_text()):
            self.refresh(keep_selection=True)
        return False

    def hide_launcher(self):
        for catcher in self.catchers:
            catcher.destroy()
        self.catchers = []
        self.hide()
        self.secrets.forget()      # the next "pw" asks again: locked since, or unlocked
        if self.search_timer:
            GLib.source_remove(self.search_timer)
            self.search_timer = 0
        if self.hf_timer:
            GLib.source_remove(self.hf_timer)
            self.hf_timer = 0
        self.stop_quick()

    def request(self, text):
        """What `launcher.py [text]` sends the daemon: toggle, or switch the
        query if it is open and a different one was asked for (">" bind)."""
        if not self.get_visible():
            self.show_launcher(text)
        elif text and text != self.entry.get_text():
            self.entry.set_text(text)
            self.entry.set_position(-1)
        else:
            self.hide_launcher()

    # -- results ---------------------------------------------------------------
    def on_changed(self):
        self.refresh()
        # Files a moment after typing stops, in a thread: plocate takes
        # ~0.1 s, too long to block a keystroke.
        if self.search_timer:
            GLib.source_remove(self.search_timer)
        self.search_timer = GLib.timeout_add(120, self.start_file_search)
        self.plan_quick()
        self.plan_hf()

    # -- ?get: the Hugging Face search ---------------------------------------------
    def plan_hf(self):
        """?get <words>: search HF_DELAY ms after the last key, never per
        keystroke, and a query once a session (HF_CACHE)."""
        if self.hf_timer:
            GLib.source_remove(self.hf_timer)
            self.hf_timer = 0
        text = self.entry.get_text()
        query = hf_query(text[1:]) if text[:1] == "?" and text[:2] != "??" else None
        if query and len(query) >= 2 and query not in HF_CACHE and query not in self.hf_asking:
            self.hf_timer = GLib.timeout_add(HF_DELAY, self.start_hf, query)

    def start_hf(self, query):
        self.hf_timer = 0
        self.hf_asking.add(query)

        def work():
            try:
                hf_search(query, lambda: GLib.idle_add(self.hf_found, query))
            finally:
                self.hf_asking.discard(query)

        threading.Thread(target=work, daemon=True).start()
        return False

    def hf_found(self, query):
        text = self.entry.get_text()
        if self.get_visible() and text[:1] == "?" and hf_query(text[1:]) == query:
            self.refresh(keep_selection=True)
        return False

    # -- ?? quick answers --------------------------------------------------------
    def plan_quick(self):
        """A ?? question: ask it QUICK_DELAY ms after the last key, as the
        file search waits for typing to stop -- never once per keystroke.
        A different question (or none) ends the run for the old one."""
        text = self.entry.get_text()
        raw = text[2:].strip() if text[:2] == "??" else ""
        if self.quick and self.quick.key == raw:
            return                      # a key that changed nothing asked (a space)
        self.stop_quick()
        if raw and quick_model(raw)[1]:     # "??opus" alone asks nothing yet
            self.quick_timer = GLib.timeout_add(QUICK_DELAY, self.start_quick, raw)

    def start_quick(self, raw):
        self.quick_timer = 0
        if self.get_visible() or not self.resident:
            quick = QuickAnswer(raw, lambda: self.quick_update(quick))
            self.quick = quick
            self.refresh(keep_selection=True)   # a model that could not start: its error
        return False

    def quick_update(self, quick):
        if quick is self.quick:         # not a run killed since
            self.refresh(keep_selection=True)

    def stop_quick(self):
        if self.quick_timer:
            GLib.source_remove(self.quick_timer)
            self.quick_timer = 0
        if self.quick:
            self.quick.kill()
            self.quick = None

    def start_file_search(self):
        self.search_timer = 0
        text = self.entry.get_text()
        self.search_gen += 1
        gen = self.search_gen
        if text[:1] in "=>#:!/~?" or is_long(text) or len(text.strip()) < 2:
            return False
        words = text.lower().split()
        recent = recent_files(words)[:FILE_LIMIT] if len(text.strip()) >= 3 else []

        def work():
            quotes = quote_items(find_quotes(text), self.browsers) if wants_quotes(text) else []
            if wants_weather(text):
                quotes = weather_items(text, self.places, self.browsers) + quotes
            paths = list(dict.fromkeys(recent + find_files(text)))[:FILE_LIMIT]
            items = [file_item(p) for p in paths]
            GLib.idle_add(self.files_found, gen, text, items, quotes)

        threading.Thread(target=work, daemon=True).start()
        return False

    def files_found(self, gen, text, items, quotes):
        if gen == self.search_gen and text == self.entry.get_text():
            self.files, self.quotes, self.files_for = items, quotes, text
            self.refresh(keep_selection=True)
        return False

    def refresh(self, keep_selection=False):
        text = self.entry.get_text()
        mine = self.files_for == text
        self.actions_back = None
        try:
            found = results(self.apps, self.commands, text, self.usage, self.windows,
                            self.files if mine else [], self.browsers, self.clips,
                            self.quotes if mine else [], self.places, self.quick,
                            shortcuts=self.shortcuts, secrets=self.secrets)
            found = learned_order(found, text, self.picks, self.apps)
        except Exception as exc:
            # A bug in one mode must not leave the box showing what was there
            # before (Enter would then run that, not what was typed): say so.
            import traceback
            traceback.print_exc()
            found = [Item("The launcher hit a bug with this text",
                          f"{type(exc).__name__}: {exc}   --   details: journalctl --user -u launcher",
                          "dialog-error")]
        if not text.strip():
            found = self.clip_items + found
        self.results = found[:MAX_TILES + 1]
        if not keep_selection or self.selected >= len(self.results):
            self.selected = 0
        self.show_results()

    def show_results(self):
        """Draw self.results: the hero and the tiles."""
        has = bool(self.results)
        self.hero.set_visible(has)
        self.empty.set_visible(not has)
        if has:
            top = self.results[0]
            if top.glyph:
                self.hero_icon.clear()
                self.hero_glyph.set_markup(f"<span size='{int(HERO_ICON * 0.7)}pt'>{top.glyph}</span>")
                self.hero_glyph.show()
                self.hero_icon.hide()
            else:
                self.hero_glyph.hide()
                self.hero_icon.show()
                self.hero_icon.set_from_gicon(top.gicon(), Gtk.IconSize.DIALOG)
                self.hero_icon.set_pixel_size(HERO_ICON)
            answer = getattr(top, "answer", False)
            self.hero_name.set_visible(not answer)
            self.hero_answer.set_visible(answer)
            (self.hero_answer if answer else self.hero_name).set_text(top.name)
            self.hero_sub.set_text(top.subtitle())
        for child in self.list.get_children():
            child.destroy()
        self.tiles, grid = [], None
        for index, app in enumerate(self.results[1:], start=1):
            if getattr(app, "row", False):
                grid = None
                self.tiles.append(self.make_row(app, index))
                continue
            if grid is None:
                grid = self.make_grid()
            self.tiles.append(self.make_tile(app, index, grid))
        self.list.show_all()
        self.paint_selection()

    def make_grid(self):
        grid = Gtk.FlowBox()
        grid.set_min_children_per_line(COLUMNS)
        grid.set_max_children_per_line(COLUMNS)
        grid.set_homogeneous(True)
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_valign(Gtk.Align.START)
        grid.set_can_focus(False)
        self.list.pack_start(grid, False, False, 0)
        return grid

    def make_row(self, app, index):
        box = Gtk.Box(spacing=12)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_margin_top(7)
        box.set_margin_bottom(7)
        box.pack_start(app_icon(app, 20), False, False, 0)
        name = styled(Gtk.Label(label=app.name, xalign=0), "clip-text")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_single_line_mode(True)
        box.pack_start(name, True, True, 0)
        tile = styled(Gtk.EventBox(), "tile", "clip-row")
        tile.add(box)
        tile.set_tooltip_text(app.subtitle())
        tile.connect("button-release-event", lambda *_: self.activate(index))
        tile.connect("enter-notify-event", lambda *_: self.hover(index))
        for side in ("start", "end", "top", "bottom"):
            getattr(tile, f"set_margin_{side}")(4 if side in ("start", "end") else 3)
        self.list.pack_start(tile, False, False, 0)
        return tile

    def where(self, index):
        """(x, y, width, height) of a tile or row inside the list."""
        tile = self.tiles[index - 1]
        alloc = tile.get_allocation()
        x, y = tile.translate_coordinates(self.list, 0, 0) or (alloc.x, alloc.y)
        return x, y, alloc.width, alloc.height

    def step(self, down):
        """The tile or row straight above or below the selected one: on the
        nearest line in that direction, the one closest across."""
        x, y, w, h = self.where(self.selected)
        middle = x + w / 2
        best = None
        for index in range(1, len(self.tiles) + 1):
            ox, oy, ow, oh = self.where(index)
            if (oy >= y + h) if down else (oy + oh <= y):
                score = (abs(oy - y), abs(ox + ow / 2 - middle))
                if best is None or score < best[0]:
                    best = (score, index)
        return best[1] if best else None

    def make_tile(self, app, index, grid):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.pack_start(app_icon(app, TILE_ICON), False, False, 0)
        name = styled(Gtk.Label(label=app.name), "tile-name")
        name.set_justify(Gtk.Justification.CENTER)
        name.set_line_wrap(True)
        name.set_lines(2)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(12)
        box.pack_start(name, False, False, 0)
        tile = styled(Gtk.EventBox(), "tile")
        tile.add(box)
        tile.set_tooltip_text(app.subtitle())
        tile.connect("button-release-event", lambda *_: self.activate(index))
        tile.connect("enter-notify-event", lambda *_: self.hover(index))
        child = Gtk.FlowBoxChild()
        child.set_can_focus(False)
        child.add(tile)
        grid.add(child)
        return tile

    def paint_selection(self):
        hero_style = self.hero.get_style_context()
        (hero_style.add_class if self.selected == 0 else hero_style.remove_class)("selected")
        for index, tile in enumerate(self.tiles, start=1):
            style = tile.get_style_context()
            (style.add_class if index == self.selected else style.remove_class)("selected")
        if self.selected:
            self.scroll_to(self.selected)

    def scroll_to(self, index):
        _x, y, _w, height = self.where(index)
        adj = self.scroll.get_vadjustment()
        if y < adj.get_value():
            adj.set_value(y)
        elif y + height > adj.get_value() + adj.get_page_size():
            adj.set_value(y + height - adj.get_page_size())

    def hover(self, index):
        self.selected = index
        self.paint_selection()

    # -- keys ------------------------------------------------------------------
    def on_key(self, _widget, event):
        key = event.keyval
        n = len(self.results)
        if self.actions_back is not None and key in (Gdk.KEY_Escape, Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.close_actions()        # back to the results, the same one selected
            return True
        if key == Gdk.KEY_Escape:
            self.close()
            return True
        if not n:
            return False
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and event.state & Gdk.ModifierType.SHIFT_MASK:
            self.activate(self.selected, alt=True)
            return True
        complete = getattr(self.results[self.selected], "complete", None)
        if key == Gdk.KEY_Tab and complete:
            # A folder in path mode: Tab goes into it, as in a shell.
            self.entry.set_text(complete)
            self.entry.set_position(-1)
            return True
        if key == Gdk.KEY_Tab and self.actions_back is None:
            self.open_actions(self.selected)
            return True
        sel = self.selected
        if key in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            sel = 1 if sel == 0 else (self.step(True) or sel)
        elif key in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            sel = 0 if sel == 0 else (self.step(False) or 0)
        elif key == Gdk.KEY_Right and sel > 0:
            sel += 1
        elif key == Gdk.KEY_Left and sel > 0:
            sel -= 1
        elif key == Gdk.KEY_ISO_Left_Tab:
            return True                 # not out of the box
        else:
            return False                # typing goes to the entry
        self.selected = max(0, min(sel, n - 1))
        self.paint_selection()
        return True

    # -- actions ---------------------------------------------------------------
    def open_actions(self, index):
        """Tab: the selected result's actions, in place of the results (the
        hero the first); Tab or Esc goes back, typing too."""
        if index >= len(self.results):
            return
        item = self.results[index]
        acts = item_actions(item, self)
        for act in acts:
            act.parent = item
        acts[0].sub = f"actions for this  ·  Tab or Esc: back"
        self.actions_back = (self.results, index)
        self.results = acts[:MAX_TILES + 1]
        self.selected = 0
        self.show_results()

    def close_actions(self):
        self.results, self.selected = self.actions_back
        self.actions_back = None
        self.show_results()

    def activate(self, index, alt=False):
        if self.launched or index >= len(self.results):
            return
        item = self.results[index]
        learned = getattr(item, "parent", item)
        if getattr(learned, "key", None):
            record_pick(self.picks, self.entry.get_text(), learned.key)
        if getattr(item, "clip_hash", None):
            self.clip_used.add(item.clip_hash)
        if getattr(item, "goto", None):
            # Another query, not an action: "Search downloads for x" -> "?get x".
            self.entry.set_text(item.goto)
            self.entry.set_position(-1)
            return
        if getattr(item, "confirm", None):
            # Ask first: the results become the question alone; its Enter /
            # Shift+Enter does what this one's would have.
            run, force = item._run, item.alt
            question = Item(item.confirm, getattr(item, "confirm_sub", None)
                            or "Enter: yes, end it  ·  Shift+Enter: kill it outright  ·  Esc: no",
                            "dialog-warning", run, alt=force)
            question.key = None
            self.results = [question]
            self.selected = 0
            self.show_results()
            return
        self.launched = True            # a double click must not launch twice
        if alt and getattr(item, "alt", None):
            item.alt()
        else:
            item.run()
        self.close()

    def close(self):
        if self.resident:
            self.hide_launcher()
        else:
            Gtk.main_quit()


def on_sigterm(callback):
    """GLib's handler, not signal.signal: Python handlers only run between
    bytecodes, and Gtk.main() blocks in C until an event arrives."""
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, callback)
    except (ValueError, ImportError):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, callback)


_PROVIDER = None


def load_css():
    """(Re)load launcher.css. One provider, re-read on every call: the
    resident launcher calls this each time it shows, so a theme switch's
    generated stylesheets apply without a restart."""
    global _PROVIDER
    first = _PROVIDER is None
    if first:
        _PROVIDER = Gtk.CssProvider()
    try:
        _PROVIDER.load_from_path(CSS_FILE)
        if first:
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), _PROVIDER, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    except GLib.Error as exc:
        print(f"launcher: {CSS_FILE}: {exc}", file=sys.stderr)


def ask_daemon(text):
    """Hand `launcher.py [text]` to a running --daemon. False if none."""
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(SOCK)
        s.sendall(json.dumps({"text": text}).encode())
        return True
    except OSError:
        return False
    finally:
        s.close()


def run_daemon():
    import socket
    try:
        os.remove(SOCK)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK)
    server.listen(4)
    on_sigterm(Gtk.main_quit)
    load_css()
    win = Launcher(resident=True)

    def on_request(_fd, _cond):
        conn, _ = server.accept()
        try:
            conn.settimeout(1)
            data = conn.recv(65536)
            win.request(json.loads(data or b"{}").get("text", ""))
        except (OSError, ValueError):
            pass
        finally:
            conn.close()
        return True

    GLib.io_add_watch(server.fileno(), GLib.IO_IN, on_request)
    start_reaper()
    try:
        Gtk.main()
    finally:
        server.close()
        try:
            os.remove(SOCK)
        except OSError:
            pass


def main():
    if sys.argv[1:] == ["--daemon"]:
        run_daemon()
        return
    if ask_daemon(sys.argv[1] if len(sys.argv) > 1 else ""):
        return
    if close_running():
        return
    with open(PID_FILE, "w") as handle:
        handle.write(str(os.getpid()))
    on_sigterm(Gtk.main_quit)
    load_css()
    start_reaper()
    win = Launcher()
    if len(sys.argv) > 1:
        win.entry.set_text(sys.argv[1])
        win.entry.set_position(-1)
    try:
        Gtk.main()
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
