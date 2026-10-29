#!/usr/bin/env python3
"""Workspace sessions: save the windows you have open -- which app, its
folder or file where that can be known, workspace, monitor, size and
position, floating / fullscreen / pinned -- under a name, and bring them back.

    sessions.py save NAME           the windows open now, as NAME
    sessions.py restore NAME        open what NAME had that is not open now,
                                    each where it was (a notification counts)
    sessions.py restore NAME --dry-run   only say what that would start
    sessions.py list [--json]       the saved sessions (and the automatic one)
    sessions.py delete NAME
    sessions.py where-was-i         restore the last session before this login
    sessions.py autosave [--exit]   the automatic slot (sessions-autosave.timer,
                                    every 3 min; --exit from closed-windows.service's
                                    ExecStop and session-exit.sh)
    sessions.py offer [--delay S]   once per login (sessions-offer.service): a
                                    notification "pick up where you left off?"
                                    with a Restore button -- never on its own
    sessions.py set autosave|offer|games on|off
    sessions.py status --json       settings + sessions + the last session, for
                                    Settings > Workspace sessions

automations.py runs `sessions.py restore NAME`: keep that line as it is.

How a window becomes something to relaunch (capture(), shared with
closed-windows.py, which keeps one for every open window):

    terminals   kitty, COSMIC Terminal, foot, alacritty, wezterm, ghostty:
                the folder of the shell inside (/proc/<shell>/cwd; with
                several shells under one pid -- kitty --single-instance --
                a path in the title instead), and what runs in it when that
                is an interactive program from SAFE_RERUN (nvim, htop, ssh,
                tmux...). Anything else that was running (a build, a dnf,
                `git push`) is only noted, never run again: a shell opens in
                its folder.
    browsers    just reopened: they restore their own tabs and windows.
    editors     VS Code / VSCodium / Zed / ...: the folder or file on the
                command line, else reopened like a browser (they bring their
                last folders back themselves).
    file managers  the folder in the title (a path, or a folder of $HOME).
    mpv         the file and the second it was at, over its IPC socket
                (/tmp/mpvSockets/<pid>, mpv/scripts/mpvSockets.lua).
    Steam and games   skipped unless "games" is on (steam_app_* reopens
                through steam://rungameid/).
    the rest    the .desktop entry -- from the app's systemd scope (uwsm and
                Flatpak name it, app-Hyprland-<id>-*.scope /
                app-flatpak-<id>-*.scope), else by class, else by the
                executable -- else its command line.

Never captured: dialogs and pickers (TRANSIENT_*), scratchpads (special
workspaces), the bar's panels, and any command line that looks like it holds
a secret (SECRET_RE: --password, token=, a URL with user:pass@, ghp_... --
the app is then relaunched from its .desktop entry without arguments, or not
at all). Private windows (privacy.conf) are kept without their title.

Restore (restore_records(), also closed-windows.py reopen): windows whose
`key` is open now are skipped (a terminal in the same folder, the browser
when it runs at all); a window that shared its process with an earlier one
(a browser's second window) is not launched again but waited for. Each app
starts in a systemd scope of its own (uwsm app, as the launcher does), then
each new window is matched to a record by class, in the order they appear,
and put back with one `hyprctl eval` (place_lua(): this config takes Lua
dispatches, `hl.dispatch(hl.dsp.window.move({ ..., window = "address:..." }))`).
Floating windows get their size and their position relative to their
monitor; tiled ones only their workspace (the tiling order is not
restorable). Workspaces are not moved between monitors: workspace rules own
that.

Where things are ($XDG_STATE_HOME/hypr/sessions/): <name>.json per session
(the name URL-quoted), _auto.json (the automatic slot of this Hyprland
instance), _previous.json (the one before: when autosave sees a new instance
signature it moves _auto there first), settings.json.
"""
import fcntl
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desk_common  # noqa: E402  (atomic_write_json)

HOME = os.path.expanduser("~")
NOTIFY = os.path.expanduser("~/.config/hypr/scripts/notify")  # notify-send with the theme's mascot (mascot_notify.py)
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                         "hypr", "sessions")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LOCK = os.path.join(RUNTIME, "sessions.lock")
OFFERED = os.path.join(RUNTIME, "sessions-offered")
MPV_SOCKETS = "/tmp/mpvSockets"
AUTO, PREVIOUS = "_auto", "_previous"
DEFAULTS = {"autosave": True, "offer": True, "games": False}

WAIT_S = 30             # how long a restore waits for the windows it launched
FOLLOW_S = 8            # ... and for a browser's other windows once its first is up
OFFER_MAX_AGE = 4 * 86400   # an older "last session" is not offered after login
EXIT_GUARD_S = 600      # autosave --exit keeps a fuller slot this recent (see autosave())

APP_DIRS = [os.path.join(HOME, ".local/share/applications"),
            os.path.join(HOME, ".local/share/flatpak/exports/share/applications"),
            "/var/lib/flatpak/exports/share/applications"] + \
    [os.path.join(d, "applications") for d in
     (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]

TERMINALS = {"kitty": "kitty", "com.system76.cosmicterm": "cosmic-term", "foot": "foot",
             "footclient": "foot", "alacritty": "alacritty", "org.wezfurlong.wezterm": "wezterm",
             "com.mitchellh.ghostty": "ghostty"}
SHELLS = {"bash", "zsh", "fish", "sh", "dash", "nu", "xonsh", "ksh", "tcsh", "elvish"}
# Programs worth starting again in their terminal: interactive, and harmless
# to rerun. Anything else is only noted (the docstring).
SAFE_RERUN = {"vim", "nvim", "vi", "nano", "micro", "hx", "helix", "emacs", "kak", "htop", "btop",
              "top", "nvtop", "bpytop", "glances", "less", "man", "ssh", "mosh", "tmux", "screen",
              "zellij", "ranger", "yazi", "lf", "nnn", "mc", "ncdu", "claude", "ipython", "watch",
              "cmus", "ncmpcpp", "newsboat", "weechat", "irssi", "lazygit", "tig", "k9s", "nmtui",
              "pulsemixer", "alsamixer", "bluetuith", "cava", "neomutt", "mutt", "aerc", "bat"}
BROWSER_RE = re.compile(r"firefox|librewolf|zen|waterfox|floorp|chrome|chromium|brave|vivaldi|opera"
                        r"|microsoft-edge|epiphany|qutebrowser|mullvad|torbrowser", re.I)
EDITOR_RE = re.compile(r"^(code|code-oss|code-url-handler|vscodium|codium|com\.vscodium\.codium|cursor"
                       r"|dev\.zed\.zed(-preview)?|zed|com\.system76\.cosmicedit|org\.gnome\.texteditor"
                       r"|gedit|org\.gnome\.gedit|kate|org\.kde\.kate|sublime_text|jetbrains-.*)$", re.I)
FILES_RE = re.compile(r"^(org\.gnome\.nautilus|nautilus|com\.system76\.cosmicfiles|thunar|org\.xfce\.thunar"
                      r"|org\.kde\.dolphin|dolphin|nemo|pcmanfm(-qt)?)$", re.I)
MPV_RE = re.compile(r"^(mpv|io\.mpv\.mpv)$", re.I)
GAME_RE = re.compile(r"^(steam|steam_app_\d+|steamwebhelper|gamescope|lutris|net\.lutris\.lutris|heroic"
                     r"|com\.heroicgameslauncher\.hgl|steam_proton|.*\.exe)$", re.I)
TRANSIENT_CLASS = re.compile(r"^(|xdg-desktop-portal.*|hyprpolkitagent|polkit-.*|org\.kde\.polkit.*|lxpolkit"
                             r"|pinentry.*|gcr-prompter|org\.gnome\.keyring.*|hyprland-share-picker|wofi"
                             r"|rofi|fuzzel|tofi|walker|anyrun|ulauncher|nwg-.*|zenity|yad|kdialog|swappy"
                             r"|hyprpicker|org\.kde\.spectacle|flameshot|desktop\.pip)$", re.I)
# The same titles lua/rules.lua floats as file dialogs, plus picture-in-picture.
TRANSIENT_TITLE = re.compile(r"^(Open File|Open Files|Open Folder|Save File|Save As|Save Image|File Upload"
                             r"|Choose Files?|Select a File|Enter name of file to save to"
                             r"|Picture-in-Picture|Picture in picture|Authentication Required)", re.I)
SECRET_RE = re.compile(
    r"(^|[-_.?&/])(pass(word|wd|phrase)?|token|secret|api[-_]?key|access[-_]?key|private[-_]?key"
    r"|credentials?|bearer|auth[-_]?token|session[-_]?id|cookie)([-_=:]|$)"
    r"|://[^/@\s:]+:[^/@\s]+@"                  # a URL with user:password@
    r"|^(ghp_|gho_|ghs_|github_pat_|glpat-|xox[abp]-|sk-|AKIA|AIza)"
    r"|^-p\S", re.I)                            # mysql -pSECRET
LONG_TOKEN = re.compile(r"^[A-Za-z0-9_\-+=]{32,}$")


# -- Hyprland ------------------------------------------------------------------------
def hypr_dir():
    """$XDG_RUNTIME_DIR/hypr/<instance>, or None without Hyprland."""
    base = os.path.join(RUNTIME, "hypr")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        return os.path.join(base, sig)
    try:    # a service started before the variable reached systemd: the newest instance
        dirs = [os.path.join(base, d) for d in os.listdir(base)]
        dirs = [d for d in dirs if os.path.exists(os.path.join(d, ".socket.sock"))]
        return max(dirs, key=os.path.getmtime) if dirs else None
    except OSError:
        return None


def instance():
    path = hypr_dir()
    return os.path.basename(path) if path else ""


def hypr_json(what):
    """`hyprctl -j <what>` over Hyprland's request socket (well under a
    millisecond, no process), or None."""
    path = hypr_dir()
    if not path:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            sock.connect(os.path.join(path, ".socket.sock"))
            sock.sendall(b"j/" + what.encode())
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        return json.loads(data)
    except (OSError, ValueError):
        return None


def hypr_eval(lua):
    """Run Lua in Hyprland (`hyprctl eval`); True when it did not error."""
    try:
        out = subprocess.run(["hyprctl", "eval", lua], capture_output=True, text=True, timeout=5)
        return out.returncode == 0 and not out.stdout.startswith("error")
    except (OSError, subprocess.SubprocessError):
        return False


def lua_str(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


# -- processes -----------------------------------------------------------------------
def read(path, mode="r"):
    try:
        with open(path, mode) as handle:
            return handle.read()
    except (OSError, ValueError):
        return b"" if "b" in mode else ""


def cmdline(pid):
    raw = read(f"/proc/{pid}/cmdline", "rb")
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0")[:-1]] if raw else []


def proc_cwd(pid):
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def children(pid):
    kids = []
    try:
        for task in os.listdir(f"/proc/{pid}/task"):
            kids += [int(k) for k in read(f"/proc/{pid}/task/{task}/children").split()]
    except OSError:
        pass
    return kids


def exe_name(pid):
    try:
        return os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        argv = cmdline(pid)
        return os.path.basename(argv[0]) if argv else ""


def foreground(shell_pid):
    """The command running in the foreground of a shell's terminal, or None
    at the prompt: the terminal's foreground process group (tpgid)."""
    stat = read(f"/proc/{shell_pid}/stat")
    try:
        tpgid = int(stat.rsplit(")", 1)[1].split()[5])
    except (IndexError, ValueError):
        return None
    if tpgid <= 0 or tpgid == shell_pid:
        return None
    return cmdline(tpgid) or None


def scope_app(pid):
    """The desktop id from the systemd scope the app was started in:
    app-Hyprland-org.mozilla.firefox-3dddd4ba.scope (uwsm),
    app-flatpak-com.google.Chrome-431942825.scope (Flatpak)."""
    for line in read(f"/proc/{pid}/cgroup").splitlines():
        name = line.rsplit("/", 1)[-1]
        m = re.fullmatch(r"app-(?:flatpak-|[^-]+-)(.+?)(?:@[^.]*)?(?:-[0-9a-f]+)?\.(?:scope|service)", name)
        if m:
            return m[1].replace("\\x2d", "-")
    return None


def is_game_process(pid):
    env = read(f"/proc/{pid}/environ", "rb")
    return b"\0SteamAppId=" in env or b"\0SteamGameId=" in env or env.startswith(b"SteamAppId=")


def has_secret(argv):
    return any(SECRET_RE.search(a) or (LONG_TOKEN.match(a) and re.search(r"\d", a) and re.search(r"[A-Za-z]", a))
               for a in argv)


# -- .desktop entries ----------------------------------------------------------------
_INDEX = {"stamp": None}


def desktop_index():
    """{"ids": {lower id: entry}, "wmclass": {lower: entry}, "exe": {name: entry}}
    with entry = {"id", "name", "exec"}: every application entry in the XDG
    folders, the first found winning (as the launcher's). Read again only
    when a folder changes."""
    stamp = tuple(os.path.getmtime(d) if os.path.isdir(d) else 0 for d in APP_DIRS)
    if _INDEX["stamp"] == stamp:
        return _INDEX
    ids, wmclass, exes = {}, {}, {}
    for folder in APP_DIRS:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for fname in names:
            if not fname.endswith(".desktop") or fname[:-8].lower() in ids:
                continue
            keys, section = {}, None
            for line in read(os.path.join(folder, fname)).splitlines():
                if line.startswith("["):
                    section = line.strip()
                elif section == "[Desktop Entry]" and "=" in line:
                    k, _, v = line.partition("=")
                    keys.setdefault(k.strip(), v.strip())
            if keys.get("Type", "Application") != "Application" or keys.get("Hidden") == "true":
                continue
            entry = {"id": fname[:-8], "name": keys.get("Name", fname[:-8]), "exec": keys.get("Exec", "")}
            ids[fname[:-8].lower()] = entry
            if keys.get("StartupWMClass"):
                wmclass.setdefault(keys["StartupWMClass"].lower(), entry)
            try:
                first = shlex.split(entry["exec"])
            except ValueError:
                first = []
            while first and (first[0] == "env" or "=" in first[0]):
                first = first[1:]
            exe = os.path.basename(first[0]) if first else ""
            if exe and exe not in ("flatpak", "sh", "bash", "python3") and keys.get("NoDisplay") != "true":
                if exe == entry["id"] or exe not in exes:     # kitty.desktop, not kitty-open.desktop
                    exes[exe] = entry
    _INDEX.update(stamp=stamp, ids=ids, wmclass=wmclass, exe=exes)
    return _INDEX


def find_desktop(cls, pid=None, exe=None, index=None):
    """The .desktop entry for a window: the app's own scope when it names
    one that fits the class or executable (a program started from a
    terminal sits in the terminal's scope), else by class, else by the
    executable's name."""
    index = index or desktop_index()
    low = (cls or "").lower()
    if pid:
        sid = scope_app(pid)
        entry = index["ids"].get((sid or "").lower())
        if entry and low and (low in (entry["id"].lower(), entry["id"].lower().rsplit(".", 1)[-1])
                              or index["wmclass"].get(low) is entry
                              or (exe and index["exe"].get(exe) is entry)):
            return entry
    if low in index["ids"]:
        return index["ids"][low]
    if low in index["wmclass"]:
        return index["wmclass"][low]
    for key, entry in index["ids"].items():
        if low and key.rsplit(".", 1)[-1] == low:
            return entry
    return index["exe"].get(exe) if exe else None


# -- capture -------------------------------------------------------------------------
def title_path(title):
    """A folder named in a window title: "you@desktop:~/Projects — COSMIC
    Terminal", "/etc", or a folder of $HOME by its name ("Downloads")."""
    for m in re.finditer(r"(~(?:/[^\s—–|:]*)?|/[^\s—–|:]+)", title or ""):
        path = os.path.expanduser(m[1]).rstrip("/") or "/"
        if os.path.isdir(path):
            return path
    name = (title or "").split(" — ")[0].split(" - ")[0].strip()
    if name in ("Home", "Personal", "Carpeta personal"):
        return HOME
    if name and "/" not in name and os.path.isdir(os.path.join(HOME, name)):
        return os.path.join(HOME, name)
    return None


def terminal_launch(cls, pid, title):
    """(launch, key, note) for a terminal window."""
    term = TERMINALS[cls.lower()]
    shells = [k for k in children(pid) if os.path.basename((cmdline(k) or [""])[0]).lstrip("-") in SHELLS]
    shell = shells[0] if len(shells) == 1 else None
    cwd = (proc_cwd(shell) if shell else None) or title_path(title) or HOME
    cmd, note = (foreground(shell) if shell else None), ""
    if cmd and (os.path.basename(cmd[0]) not in SAFE_RERUN or has_secret(cmd)):
        note = "was running " + (os.path.basename(cmd[0]) if has_secret(cmd) else shlex.join(cmd))[:80] \
            + " (not started again)"
        cmd = None
    run = []
    if cmd:
        run = ["sh", "-c", shlex.join(cmd) + '; exec "${SHELL:-/bin/bash}"']
    argv = {"kitty": ["kitty", "--directory", cwd] + run,
            "cosmic-term": ["cosmic-term", "--working-directory", cwd],      # it has no -e
            "foot": ["foot", "-D", cwd] + run,
            "alacritty": ["alacritty", "--working-directory", cwd] + (["-e"] + run if run else []),
            "wezterm": ["wezterm", "start", "--cwd", cwd] + (["--"] + run if run else []),
            "ghostty": ["ghostty", f"--working-directory={cwd}"] + (["-e"] + run if run else [])}[term]
    if cmd and term == "cosmic-term":
        note, cmd = f"was running {shlex.join(cmd)[:80]} (COSMIC Terminal cannot start it)", None
    return ({"argv": argv, "cwd": cwd}, f"term|{cls.lower()}|{cwd}|{shlex.join(cmd) if cmd else ''}", note)


def mpv_state(pid):
    """(path, seconds) from mpv's IPC socket, or (None, None)."""
    path = os.path.join(MPV_SOCKETS, str(pid))
    if not os.path.exists(path):
        return None, None
    out = {}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            sock.connect(path)
            for rid, prop in ((1, "path"), (2, "time-pos")):
                sock.sendall(json.dumps({"command": ["get_property", prop], "request_id": rid}).encode() + b"\n")
            buf = b""
            while len(out) < 2:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("request_id") in (1, 2):
                        out[msg["request_id"]] = msg.get("data")
    except OSError:
        pass
    return out.get(1), out.get(2)


def path_args(argv):
    """The arguments of a command line that are existing files or folders."""
    return [a for a in argv[1:] if not a.startswith("-") and os.path.exists(a)]


def monitor_names(monitors):
    return {m.get("id"): m.get("name") for m in monitors or []}


def capture(client, monitors=(), settings=None, private=(), index=None):
    """(record, None) for a window that can be relaunched, (None, reason)
    for one that cannot or should not be (the docstring has the rules)."""
    settings = settings or DEFAULTS
    cls, title, pid = client.get("class") or "", client.get("title") or "", client.get("pid") or 0
    low = cls.lower()
    ws = (client.get("workspace") or {}).get("name") or ""
    if not client.get("mapped", True) or TRANSIENT_CLASS.match(cls) or TRANSIENT_TITLE.match(title):
        return None, "a dialog or picker"
    if ws.startswith("special"):
        return None, "a scratchpad"
    argv = cmdline(pid)
    if any("/.config/waybar/scripts/" in a for a in argv[:3]):
        return None, "a bar panel"
    exe = exe_name(pid)
    game = GAME_RE.match(cls) or is_game_process(pid)
    if game and not settings.get("games"):
        return None, "Steam / a game"
    entry = find_desktop(cls, pid, exe, index)
    launch, note, kind = None, "", "app"
    if low in TERMINALS:
        kind = "terminal"
        launch, key, note = terminal_launch(cls, pid, title)
    elif BROWSER_RE.search(low) and entry:
        kind, key = "browser", f"browser|{low}"
        launch = {"desktop": entry["id"]}
    elif game:
        kind, key = "game", f"game|{low}"
        m = re.fullmatch(r"steam_app_(\d+)", low)
        launch = {"argv": ["steam", f"steam://rungameid/{m[1]}"]} if m else \
            {"desktop": entry["id"]} if entry else None
    elif EDITOR_RE.match(cls) and entry:
        kind = "editor"
        paths = [] if has_secret(argv) else path_args(argv)
        launch = {"desktop": entry["id"], "args": paths[-1:]}
        key = f"editor|{low}|{paths[-1] if paths else ''}"
    elif FILES_RE.match(cls):
        kind = "files"
        folder = title_path(title) or HOME
        launch = {"desktop": entry["id"], "args": [folder]} if entry else {"argv": [exe or low, folder]}
        key = f"files|{low}|{folder}"
    elif MPV_RE.match(cls):
        kind = "mpv"
        path, pos = mpv_state(pid)
        if not path:
            paths = [] if has_secret(argv) else path_args(argv)
            path = paths[-1] if paths else None
        if path and has_secret([path]):
            path = None
        if not path:
            return None, "mpv with nothing to reopen"
        launch = {"argv": ["mpv"] + ([f"--start={int(pos)}"] if pos and pos > 5 else []) + [path]}
        key = f"mpv|{path}"
    else:
        key = f"app|{low}"
        # Found only by its executable (no class or scope says so), its own
        # command line wins when it has one: `kitty --class x cmd` is not kitty.desktop.
        by_exe = entry and find_desktop(cls, pid, None, index) is None
        if entry and not (by_exe and len(argv) > 1 and not has_secret(argv) and shutil.which(argv[0])):
            launch = {"desktop": entry["id"]}
        elif argv and not has_secret(argv) and shutil.which(argv[0]):
            launch, entry = {"argv": argv, "cwd": proc_cwd(pid)}, None
        else:
            return None, "a secret on its command line" if argv and has_secret(argv) else "no way to start it"
    if launch is None:
        return None, "no way to start it"
    mon_id = client.get("monitor")
    mon = next((m for m in monitors or [] if m.get("id") == mon_id), None)
    at, size = client.get("at") or [0, 0], client.get("size") or [0, 0]
    shown_private = low in private or re.search(r"keepassxc", low) or \
        re.search(r"private browsing|incognito|inprivate", title, re.I)
    record = {"class": cls, "app": entry["name"] if entry else cls, "title": "" if shown_private else title[:120],
              "kind": kind, "launch": launch, "key": key, "pid": pid,
              "workspace": ws, "monitor": mon.get("name") if mon else None,
              "rel": [at[0] - mon["x"], at[1] - mon["y"]] if mon else None, "size": size,
              "floating": bool(client.get("floating")), "fullscreen": client.get("fullscreen") or 0,
              "fullscreen_client": client.get("fullscreenClient") or 0, "pinned": bool(client.get("pinned"))}
    if note:
        record["note"] = note
    return record, None


def private_classes():
    try:
        import privacy_settings
        return set(privacy_settings.excluded(privacy_settings.load()))
    except Exception:       # noqa: BLE001 - privacy.conf unreadable: nothing extra is private
        return set()


def snapshot(clients=None, monitors=None, settings=None):
    """{"saved", "instance", "windows": [record...], "skipped": [[app, reason]...]}
    for the windows open now, in workspace order. A window that shares its
    process and launch with an earlier one (a browser's other windows) is
    marked "shared": launching the first brings it back."""
    clients = hypr_json("clients") if clients is None else clients
    monitors = hypr_json("monitors") if monitors is None else monitors
    settings = settings or load_settings()
    private, index = private_classes(), desktop_index()
    windows, skipped, seen = [], [], set()

    def order(c):
        ws = (c.get("workspace") or {}).get("id") or 0
        return (ws if ws > 0 else 10_000 - ws, (c.get("at") or [0, 0])[0], (c.get("at") or [0, 0])[1])
    for client in sorted(clients or [], key=order):
        rec, why = capture(client, monitors, settings, private, index)
        if rec is None:
            skipped.append([client.get("class") or "?", why])
            continue
        same = (rec["pid"], json.dumps(rec["launch"], sort_keys=True))
        if same in seen and rec["kind"] != "terminal":
            rec["shared"] = True
        seen.add(same)
        windows.append(rec)
    return {"saved": int(time.time()), "instance": instance(), "windows": windows, "skipped": skipped}


# -- storage -------------------------------------------------------------------------
def valid_name(name):
    return bool(name) and len(name) <= 40 and not name.startswith(("_", ".")) and "/" not in name \
        and name.strip() == name and name.isprintable()


def session_path(name):
    return os.path.join(STATE_DIR, urllib.parse.quote(name, safe=" ") + ".json")


def write_json(path, data):
    desk_common.atomic_write_json(path, data, indent=1)


def load_session(name):
    try:
        with open(session_path(name)) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) and isinstance(data.get("windows"), list) else None
    except (OSError, ValueError):
        return None


def sessions():
    """The saved sessions (not the automatic slots), newest first."""
    out = []
    try:
        names = os.listdir(STATE_DIR)
    except OSError:
        return out
    for fname in names:
        if fname.endswith(".json") and not fname.startswith(("_", ".")) and fname != "settings.json":
            name = urllib.parse.unquote(fname[:-5])
            data = load_session(name)
            if data:
                out.append(summary(name, data))
    return sorted(out, key=lambda s: -s["saved"])


def summary(name, data):
    apps = Counter(w.get("app") or w.get("class") for w in data["windows"] if not w.get("shared"))
    return {"name": name, "saved": data.get("saved", 0), "windows": len(data["windows"]),
            "apps": ", ".join(f"{n}× {a}" if n > 1 else a for a, n in apps.most_common())}


def load_settings():
    try:
        with open(os.path.join(STATE_DIR, "settings.json")) as handle:
            data = json.load(handle)
        return {**DEFAULTS, **{k: bool(v) for k, v in data.items() if k in DEFAULTS}}
    except (OSError, ValueError, AttributeError):
        return dict(DEFAULTS)


def save_settings(settings):
    write_json(os.path.join(STATE_DIR, "settings.json"), settings)


def last_session():
    """The automatic slot from before this Hyprland instance (the last
    logout or reboot), or None. _auto when no autosave has run in this
    instance yet, else _previous."""
    now = instance()
    for name in (AUTO, PREVIOUS):
        data = load_session(name)
        if data and data.get("instance") != now and data["windows"]:
            return data
    return None


def autosave(exit_mode=False):
    """The automatic slot. A new Hyprland instance moves the old one to
    _previous first (so where-was-i survives the first save after login).
    At exit apps are already closing: a save with fewer windows than one
    made in the last EXIT_GUARD_S is dropped, so a half-closed desktop does
    not replace the real one."""
    if not load_settings()["autosave"]:
        return 0
    clients = hypr_json("clients")
    if clients is None:
        return 1            # no Hyprland (the timer before login, or after it)
    snap = snapshot(clients)
    cur = load_session(AUTO)
    if cur and cur.get("instance") != snap["instance"]:
        if cur["windows"]:
            write_json(session_path(PREVIOUS), cur)
    elif cur and exit_mode and len(snap["windows"]) < len(cur["windows"]) \
            and time.time() - cur.get("saved", 0) < EXIT_GUARD_S:
        return 0
    write_json(session_path(AUTO), snap)
    return 0


# -- restore -------------------------------------------------------------------------
def in_scope(argv):
    """`argv` in a systemd scope of its own, as uwsm starts every app (so it
    does not live and die with closed-windows.service): launcher.py's
    in_scope()."""
    if shutil.which("uwsm"):
        return ["uwsm", "app", "--"] + argv
    if shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "--quiet", "--"] + argv
    return argv


def launch_argv(launch):
    if launch.get("desktop"):
        did = launch["desktop"] + ".desktop"
        if shutil.which("uwsm"):
            return ["uwsm", "app", "--", did] + launch.get("args", [])
        return ["gtk-launch", launch["desktop"]] + launch.get("args", [])
    return in_scope(launch["argv"])


def spawn(launch):
    cwd = launch.get("cwd")
    try:
        return subprocess.Popen(launch_argv(launch), cwd=cwd if cwd and os.path.isdir(cwd) else HOME,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True).pid
    except OSError:
        return None


def live_keys(clients, monitors):
    keys = Counter()
    private, index, settings = set(), desktop_index(), {"games": True}
    for c in clients or []:
        rec, _ = capture(c, monitors, settings, private, index)
        if rec:
            keys[rec["key"]] += 1
    return keys


def plan(records, clients, monitors, skip_open=True):
    """(to_launch, waits, skipped): the records to start, every record to
    wait for (with the ones a launch brings back by itself), and the ones
    left out because they are open already."""
    open_keys = live_keys(clients, monitors) if skip_open else Counter()
    launch, wait, skipped = [], [], []
    leader_skipped = {}
    for rec in records:
        lkey = json.dumps(rec["launch"], sort_keys=True)
        if rec.get("shared"):
            if leader_skipped.get(lkey, True):
                skipped.append(rec)
            else:
                wait.append(rec)
            continue
        if open_keys[rec["key"]] > 0:
            open_keys[rec["key"]] -= 1
            skipped.append(rec)
            leader_skipped[lkey] = True
            continue
        leader_skipped[lkey] = False
        launch.append(rec)
        wait.append(rec)
    return launch, wait, skipped


def place_lua(address, rec, monitors, current=None):
    """The Lua that puts a restored window back: its workspace, floating or
    tiled, size and position (relative to its monitor, kept on it), then
    fullscreen and pin. One `hyprctl eval`."""
    current = current or {}
    t = lua_str("address:" + address)
    lua = [f"local w = hl.get_window({t})", "if not w then return end"]
    ws = rec.get("workspace") or ""
    have = (current.get("workspace") or {}).get("name")
    if ws and not ws.startswith("special") and ws != have:
        sel = ws if re.fullmatch(r"-?\d+", ws) else "name:" + ws
        lua.append(f"hl.dispatch(hl.dsp.window.move({{ workspace = {lua_str(sel)}, follow = false, window = {t} }}))")
    if rec.get("floating"):
        if not current.get("floating"):
            lua.append(f'hl.dispatch(hl.dsp.window.float({{ action = "enable", window = {t} }}))')
        w, h = (rec.get("size") or [0, 0])[:2]
        mon = next((m for m in monitors or [] if m.get("name") == rec.get("monitor")), None)
        if w > 0 and h > 0:
            if mon:
                mw, mh = mon["width"] / (mon.get("scale") or 1), mon["height"] / (mon.get("scale") or 1)
                if (mon.get("transform") or 0) % 2:
                    mw, mh = mh, mw
                w, h = min(w, int(mw)), min(h, int(mh))
            lua.append(f"hl.dispatch(hl.dsp.window.resize({{ x = {int(w)}, y = {int(h)}, window = {t} }}))")
            if mon and rec.get("rel"):
                x = mon["x"] + max(0, min(rec["rel"][0], int(mw) - w))
                y = mon["y"] + max(0, min(rec["rel"][1], int(mh) - h))
                lua.append(f"hl.dispatch(hl.dsp.window.move({{ x = {int(x)}, y = {int(y)}, window = {t} }}))")
    elif current.get("floating"):
        lua.append(f'hl.dispatch(hl.dsp.window.float({{ action = "disable", window = {t} }}))')
    fs = int(rec.get("fullscreen") or 0)
    if fs and not current.get("fullscreen"):
        lua.append(f"hl.dispatch(hl.dsp.window.fullscreen_state({{ internal = {fs}, "
                   f"client = {int(rec.get('fullscreen_client') or fs)}, window = {t} }}))")
    if rec.get("pinned") and rec.get("floating") and not current.get("pinned"):
        lua.append(f"hl.dispatch(hl.dsp.window.pin({{ window = {t} }}))")
    return "\n".join(lua)


class Notifier:
    """One notification, replaced in place as a restore goes on."""

    def __init__(self, enabled=True):
        self.enabled, self.id = enabled, None

    def __call__(self, summary_text, body="", urgency="low"):
        if not self.enabled:
            return
        cmd = [NOTIFY, "-a", "Sessions", "-i", "view-restore", "-u", urgency, "-p"]
        if self.id:
            cmd += ["-r", self.id]
        try:
            out = subprocess.run(cmd + [summary_text, body], capture_output=True, text=True, timeout=5).stdout
            self.id = out.strip().splitlines()[0] if out.strip() else self.id
        except (OSError, subprocess.SubprocessError, IndexError):
            pass


def restore_records(records, label="session", skip_open=True, notify=None, wait_s=WAIT_S,
                    sleep=time.sleep, clock=time.monotonic):
    """Start what `records` had and put each window back. Returns
    {"placed": [...], "missing": [...], "skipped": [...]} (records)."""
    notify = notify or Notifier(False)
    clients, monitors = hypr_json("clients") or [], hypr_json("monitors") or []
    to_launch, waits, skipped = plan(records, clients, monitors, skip_open)
    result = {"placed": [], "missing": [], "skipped": skipped}
    if not waits:
        return result
    before = {c.get("address") for c in clients}
    notify(f"Restoring {label}", f"opening {len(to_launch)} app{'s' * (len(to_launch) != 1)}…")
    for rec in to_launch:
        spawn(rec["launch"])
        sleep(0.15)
    pending, seen = list(waits), set(before)
    deadline = clock() + wait_s
    leaders_done_at = None
    while pending and clock() < deadline:
        sleep(0.25)
        now = hypr_json("clients") or []
        for client in now:
            addr = client.get("address")
            if addr in seen or not client.get("mapped", True):
                continue
            cls = (client.get("class") or "").lower()
            icls = (client.get("initialClass") or "").lower()
            rec = next((r for r in pending if r["class"].lower() in (cls, icls)), None)
            if rec is None:
                continue
            seen.add(addr)
            pending.remove(rec)
            hypr_eval(place_lua(addr, rec, monitors, client))
            result["placed"].append(rec)
            notify(f"Restoring {label}", f"{len(result['placed'])} of {len(waits)}: {rec['app']}")
        if not any(not r.get("shared") for r in pending):
            # Only a browser's other windows are left: they come with it, or
            # the browser was not set to restore them.
            leaders_done_at = leaders_done_at or clock()
            if clock() - leaders_done_at > FOLLOW_S:
                break
    result["missing"] = [r for r in pending if not r.get("shared")]
    return result


def result_text(result):
    placed, missing, skipped = (len(result[k]) for k in ("placed", "missing", "skipped"))
    parts = [f"{placed} window{'s' * (placed != 1)} back"]
    if skipped:
        parts.append(f"{skipped} already open")
    if missing:
        parts.append("no window from " + ", ".join(sorted({r["app"] for r in result["missing"]})))
    notes = [f"{r['app']}: {r['note']}" for r in result["placed"] if r.get("note")]
    return "  ·  ".join(parts) + ("\n" + "\n".join(notes[:4]) if notes else "")


def restore(data, label, notify=True):
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            Notifier(notify)("A session is already being restored", "", "normal")
            return 1
        note = Notifier(notify)
        result = restore_records(data["windows"], label, notify=note)
        text = result_text(result)
        if not result["placed"] and not result["missing"]:
            note(f"{label[:1].upper()}{label[1:]}: nothing to open", "everything in it is open already")
        else:
            note(f"Restored {label}", text, "normal" if result["missing"] else "low")
        print(text)
        return 0


# -- after login ---------------------------------------------------------------------
def last_focus(before):
    """The app that had the focus last before `before` (epoch), from
    activity-log.py's log (its tail only), as "Firefox — title"; "" when
    unknown or private."""
    path = os.path.join(os.path.dirname(STATE_DIR), "activity.jsonl")
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, os.path.getsize(path) - 65536))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("t", 0) <= before + 60 and row.get("class") and row.get("class") != "private":
            return f"{row['class']} — {row.get('title', '')}"[:80]
    return ""


def when(epoch):
    days = (time.localtime().tm_yday - time.localtime(epoch).tm_yday) % 366
    day = "today" if days == 0 else "yesterday" if days == 1 else time.strftime("%a %d %b", time.localtime(epoch))
    return f"{day} {time.strftime('%H:%M', time.localtime(epoch))}"


def offer(delay=20):
    """After login, once: "pick up where you left off?" with a Restore
    button. Nothing happens without the click."""
    if not load_settings()["offer"]:
        return 0
    time.sleep(delay)
    sig = instance()
    if not sig or read(OFFERED).strip() == sig:
        return 0
    with open(OFFERED, "w") as handle:
        handle.write(sig)
    data = last_session()
    if not data or time.time() - data.get("saved", 0) > OFFER_MAX_AGE:
        return 0
    _, waits, _ = plan(data["windows"], hypr_json("clients") or [], hypr_json("monitors") or [])
    if not waits:
        return 0
    info = summary("last", data)
    focus = last_focus(data.get("saved", 0))
    body = f"{info['windows']} windows from {when(data.get('saved', 0))}: {info['apps']}" + \
        (f"\nlast thing in focus: {focus}" if focus else "")
    try:
        out = subprocess.run([NOTIFY, "-a", "Sessions", "-i", "view-restore", "-t", "60000", "--wait",
                              "--action=restore=Restore", "--action=no=Not now",
                              "Pick up where you left off?", body],
                             capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    if "restore" in out.split():
        return restore(data, "your last session")
    return 0


# -- CLI -----------------------------------------------------------------------------
def say(text):
    """Print, and a notification too when there is no terminal to print to
    (the launcher, the Settings page)."""
    print(text)
    if not sys.stdout.isatty():
        Notifier()("Sessions", text)


def status():
    data = last_session()
    return {"settings": load_settings(), "sessions": sessions(),
            "last": summary("last", data) if data else None}


def main(argv):
    cmd, args = (argv[0] if argv else ""), argv[1:]
    if cmd == "save" and len(args) == 1:
        if not valid_name(args[0]):
            sys.exit("sessions: a name is 1-40 characters, no '/', not starting with _ or .")
        if hypr_json("monitors") is None:
            sys.exit("sessions: Hyprland is not running")
        snap = snapshot()
        write_json(session_path(args[0]), snap)
        skipped = Counter(why for _, why in snap["skipped"])
        say(f"Saved \"{args[0]}\": {len(snap['windows'])} windows"
            + (" (left out: " + ", ".join(f"{n}× {w}" for w, n in skipped.items()) + ")" if skipped else ""))
    elif cmd == "restore" and args and args[1:] in ([], ["--dry-run"]):
        data = load_session(args[0])
        if not data:
            sys.exit(f"sessions: no session called {args[0]!r}")
        if "--dry-run" in args:
            to_launch, waits, skipped = plan(data["windows"], hypr_json("clients") or [], hypr_json("monitors") or [])
            for verb, recs in (("start", to_launch), ("comes with its app", [r for r in waits if r.get("shared")]),
                               ("open already", skipped)):
                for r in recs:
                    print(f"{verb:<19} ws {r['workspace']:<4} {r['app']}  {shlex.join(launch_argv(r['launch']))}"
                          if verb == "start" else f"{verb:<19} ws {r['workspace']:<4} {r['app']}")
            return
        sys.exit(restore(data, f"\u201c{args[0]}\u201d"))
    elif cmd == "where-was-i":
        data = last_session()
        if not data:
            say("No earlier session to go back to yet")
            return
        sys.exit(restore(data, "your last session"))
    elif cmd == "delete" and len(args) == 1:
        try:
            os.remove(session_path(args[0]))
        except OSError:
            sys.exit(f"sessions: no session called {args[0]!r}")
    elif cmd == "list":
        rows, last = sessions(), last_session()
        if "--json" in args:
            print(json.dumps({"sessions": rows, "last": summary("last", last) if last else None}))
            return
        for s in rows:
            print(f"{s['name']:<20} {s['windows']:>3} windows  {when(s['saved'])}  {s['apps']}")
        if last:
            print(f"{'(last session)':<20} {len(last['windows']):>3} windows  {when(last['saved'])}"
                  f"  -- sessions.py where-was-i")
        if not rows and not last:
            print("no sessions saved yet: sessions.py save NAME")
    elif cmd == "autosave":
        sys.exit(autosave("--exit" in args))
    elif cmd == "offer":
        delay = float(args[args.index("--delay") + 1]) if "--delay" in args[:-1] else 20
        sys.exit(offer(delay))
    elif cmd == "set" and len(args) == 2 and args[0] in DEFAULTS and args[1] in ("on", "off"):
        settings = load_settings()
        settings[args[0]] = args[1] == "on"
        save_settings(settings)
    elif cmd == "status":
        print(json.dumps(status()))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
