#!/usr/bin/env python3
"""Media status for waybar.

MPRIS is the primary source now that mpv-mpris is installed, so mpv shows up in
playerctl alongside everything else. mpv's IPC socket is still used for the two
things MPRIS cannot answer:

  * whether the current file actually has a video stream (MPRIS has no such field)
  * grabbing a frame out of a *stream*, where there is no local file to read

and as a complete fallback if mpris.so ever fails to load.

Modes:
    player.py watch               continuous JSON for the bar pill: one line per
                                  change, driven by `playerctl --follow`
    player.py status              the same line, once, for a polled module
    player.py toggle|next|prev    playback control
    player.py seek <seconds>      jump to an absolute position
    player.py cycle next|prev     switch which player the pill and the panel
                                  follow (the pill's scroll wheel)
    player.py select <instance>   follow that one (the panel's source buttons)

The pill is short on purpose: an icon and "Playing" or "Paused", plus "2/3"
when more than one player is up. The title is in its tooltip and in the
preview panel, where there is room for it. With several players, the one
followed is the one you last switched to (SELECTED) while it is still there;
otherwise a playing one, preferring a real video player (mpv, vlc) over a
browser tab. Controls always go to the followed player's own MPRIS instance
(firefox.instance_1_265, not just "firefox"), so two browser windows can be
told apart.

The preview panel is started and stopped by panel.py, not from here. flyout.py
imports this file for state, frames and control, so the pill and the panel can
never disagree about what is playing.

Icons are Font Awesome 6 codepoints written as escapes: no Nerd Font is
installed here, and literal Private-Use characters do not survive copying.
"""

import ctypes
import glob
import json
import os
import re
import shutil
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

CACHE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-player")
THUMB = os.path.join(CACHE, "thumb.jpg")
STATE_CACHE = os.path.join(CACHE, "state.json")
SELECTED = os.path.join(CACHE, "selected")     # instance last switched to
# The panel asks for state on its own clock while the bar pill polls on waybar's,
# and both land on playerctl. One shared answer per tick is plenty.
STATE_TTL = 0.8
THUMB_WIDTH = 480

PLAYER_ICONS = {
    "mpv": "\uf008",       # film
    "firefox": "\uf269",   # brands: firefox
    "spotify": "\uf1bc",   # brands: spotify
    "vlc": "\uf03d",       # video
    "chromium": "\uf268",  # brands: chrome
    "chrome": "\uf268",
}
DEFAULT_ICON = "\uf001"    # music
PAUSE_ICON = "\uf04c"      # pause

VIDEO_EXT = re.compile(r"\.(mkv|mp4|avi|mov|webm|m4v|ts|flv|wmv|mpg|mpeg)$", re.I)
SCENE_TAG = re.compile(
    r"\b(\d{3,4}p|4k|2160p|bluray|blu-ray|brrip|bdrip|webrip|web-dl|webdl|hdtv|"
    r"dvdrip|remux|x264|x265|h264|h265|hevc|xvid|aac|ac3|dts|ddp?5|hdr|10bit|repack|proper)\b",
    re.I,
)


PREV_ICON = "\uf048"   # backward-step
PLAY_ICON = "\uf04b"   # play
PAUSE_BTN = "\uf04c"   # pause
NEXT_ICON = "\uf051"   # forward-step


def blank_state():
    return {
        "source": "", "socket": "", "title": "", "path": "", "url": "",
        "paused": True, "position": 0.0, "duration": 0.0,
        "is_video": False, "artist": "", "art": "",
        "player": "",               # MPRIS instance, e.g. firefox.instance_1_265
        "players": [],              # every player up: [{player, source, title, paused}]
    }


# --------------------------------------------------------------------------
# mpv IPC — enrichment and fallback
# --------------------------------------------------------------------------
def mpv_sockets():
    paths = sorted(glob.glob("/tmp/mpvSockets/*"))
    if os.path.exists("/tmp/mpvsocket"):
        paths.append("/tmp/mpvsocket")
    return [p for p in paths if os.path.exists(p)]


def mpv_get(sock_path, properties):
    """Fetch several properties over one connection. Returns {} on any failure."""
    result = {}
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.4)
        sock.connect(sock_path)
    except OSError:
        return {}

    with sock:
        pending = {}
        for i, prop in enumerate(properties, start=1):
            pending[i] = prop
            try:
                sock.sendall(json.dumps(
                    {"command": ["get_property", prop], "request_id": i}
                ).encode() + b"\n")
            except OSError:
                return {}

        buf = b""
        try:
            while pending:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    rid = msg.get("request_id")  # replies carry it, events do not
                    if rid in pending:
                        prop = pending.pop(rid)
                        if msg.get("error") == "success":
                            result[prop] = msg.get("data")
        except (OSError, socket.timeout):
            pass
    return result


def mpv_command(sock_path, command):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        sock.connect(sock_path)
    except OSError:
        return False
    with sock:
        try:
            sock.sendall(json.dumps({"command": command}).encode() + b"\n")
            sock.recv(4096)
        except (OSError, socket.timeout):
            return False
    return True


MPV_PROPS = ["media-title", "path", "pause", "time-pos", "duration",
             "video-format", "width", "metadata"]


def mpv_ipc_state():
    """Full state straight from IPC. Only reached when MPRIS gives us nothing."""
    candidates = []
    for sock_path in mpv_sockets():
        data = mpv_get(sock_path, MPV_PROPS)
        if not data.get("media-title"):
            continue
        state = blank_state()
        state.update({
            "source": "mpv",
            "socket": sock_path,
            "title": data.get("media-title") or "",
            "path": data.get("path") or "",
            "paused": bool(data.get("pause")),
            "position": data.get("time-pos") or 0,
            "duration": data.get("duration") or 0,
            "is_video": bool(data.get("video-format")) and bool(data.get("width")),
            "artist": (data.get("metadata") or {}).get("artist", ""),
        })
        candidates.append(state)
    if not candidates:
        return None
    for state in candidates:
        if not state["paused"]:
            return state
    return candidates[0]


def enrich_from_mpv(state):
    """MPRIS says nothing about whether a track carries video, so ask the
    matching mpv instance. Falls back to the file extension if IPC is gone."""
    for sock_path in mpv_sockets():
        data = mpv_get(sock_path, ["path", "video-format", "width", "duration"])
        if not data:
            # An mpv that was killed rather than quit leaves its socket behind.
            # Taking that one means is_video comes back false and the preview
            # silently falls back to artwork it does not have.
            continue
        path = data.get("path") or ""
        # Match socket to MPRIS entry by filename so several mpv windows do not
        # cross-contaminate each other's state.
        if state["path"] and path and \
                os.path.basename(path) != os.path.basename(state["path"]):
            continue
        state["socket"] = sock_path
        state["is_video"] = bool(data.get("video-format")) and bool(data.get("width"))
        if not state["duration"]:
            state["duration"] = data.get("duration") or 0
        return state
    state["is_video"] = bool(VIDEO_EXT.search(state["path"] or state["title"]))
    return state


# --------------------------------------------------------------------------
# MPRIS — primary
# --------------------------------------------------------------------------
FIELDS = ["playerName", "status", "title", "artist", "mpris:artUrl",
          "position", "mpris:length", "xesam:url", "playerInstance"]
SEP = "\x1f"


def to_seconds(value):
    """playerctl reports position in seconds and mpris:length in microseconds,
    both as bare strings."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / 1e6 if number > 1e6 else number


def url_to_path(url):
    if url.startswith("file://"):
        return urllib.parse.unquote(urllib.parse.urlparse(url).path)
    return ""


def mpris_state():
    if not shutil.which("playerctl"):
        return None
    fmt = SEP.join("{{" + field + "}}" for field in FIELDS)
    try:
        out = subprocess.run(["playerctl", "-a", "metadata", "--format", fmt],
                             capture_output=True, text=True, timeout=2).stdout
    except (subprocess.SubprocessError, OSError):
        return None

    entries = []
    for line in out.splitlines():
        parts = line.split(SEP)
        if len(parts) < len(FIELDS) or not parts[2].strip():
            continue
        name, status, title, artist, art, pos, length, url = parts[:8]
        instance = parts[8] if len(parts) > 8 and parts[8] else name
        state = blank_state()
        state.update({
            "player": instance,
            "source": name.lower().split(".")[0],
            "title": title,
            "artist": artist,
            "art": art,
            "url": url,
            "path": url_to_path(url),
            "paused": status.lower() != "playing",
            "position": to_seconds(pos),
            "duration": to_seconds(length),
        })
        entries.append(state)
    if not entries:
        return None

    # Stable order for "2/3" and for the scroll wheel: by instance name.
    entries.sort(key=lambda e: e["player"])
    pinned = read_selected()
    chosen = next((e for e in entries if e["player"] == pinned), None)
    if chosen is None:
        playing = [e for e in entries if not e["paused"]]
        pool = playing or entries
        # A dedicated video player wins over a browser tab that happens to be
        # playing audio: it is the one with a frame worth previewing.
        chosen = next((e for e in pool if e["source"] in ("mpv", "vlc")), pool[0])
    chosen["players"] = [{"player": e["player"], "source": e["source"],
                          "title": clean_title(e["title"]), "paused": e["paused"]}
                         for e in entries]
    if chosen["source"] == "mpv":
        chosen = enrich_from_mpv(chosen)
    elif chosen["path"]:
        chosen["is_video"] = bool(VIDEO_EXT.search(chosen["path"]))
    return chosen


def read_selected():
    try:
        with open(SELECTED) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def select(instance):
    os.makedirs(CACHE, exist_ok=True)
    with open(SELECTED, "w") as handle:
        handle.write(instance)
    drop_cache()
    wake_watcher()


def cycle(step):
    state = current()
    players = (state or {}).get("players") or []
    if len(players) < 2:
        return
    names = [p["player"] for p in players]
    here = names.index(state["player"]) if state["player"] in names else 0
    select(names[(here + step) % len(names)])


def wake_watcher():
    """The pill's watcher only republishes when playerctl reports a change;
    switching players changes nothing in MPRIS, so it is told (SIGUSR1)."""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                args = handle.read().split(b"\0")
        except OSError:
            continue
        if any(a.endswith(b"player.py") for a in args) and b"watch" in args:
            try:
                os.kill(int(pid), signal.SIGUSR1)
            except OSError:
                pass


def current():
    """Cached for STATE_TTL: the panel's meta tick, its frame thread and the
    pill's heartbeat all want the same answer within the same moment, and each
    miss costs a full playerctl round trip."""
    try:
        if time.time() - os.path.getmtime(STATE_CACHE) < STATE_TTL:
            with open(STATE_CACHE) as handle:
                return json.load(handle)
    except (OSError, ValueError):
        pass

    state = mpris_state() or mpv_ipc_state()
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = STATE_CACHE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(state, handle)
        os.replace(tmp, STATE_CACHE)
    except OSError:
        pass
    return state


def drop_cache():
    """After a control action the cached paused flag is a lie."""
    try:
        os.remove(STATE_CACHE)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def clean_title(title):
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\s*[-–|]\s*(YouTube|Twitch|Vimeo)\s*$", "", title, flags=re.I)

    # mpv falls back to the bare filename when a file carries no metadata.
    if VIDEO_EXT.search(title):
        title = VIDEO_EXT.sub("", title)
        title = title.replace(".", " ").replace("_", " ")
        cut = SCENE_TAG.search(title)
        if cut and cut.start() > 0:
            title = title[: cut.start()]
        title = re.sub(r"\s+[-\[(].*$", "", title).strip(" -[](")
        title = re.sub(r"\s+(19|20)\d{2}$",
                       lambda m: f" ({m.group(0).strip()})", title)
        title = re.sub(r"\s+", " ", title).strip()
    return title


def ellipsize(text, limit):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def seek_stamp(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def hms(seconds):
    seconds = int(seconds or 0)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
_UNSET = object()


def emit_status(state=_UNSET):
    # A sentinel, not None: None is a real answer ("no player"), and treating
    # it as "not given" made every idle publish query the players twice.
    if state is _UNSET:
        state = current()
    if not state:
        print(json.dumps({"text": "", "tooltip": "", "class": "stopped"}),
              flush=True)
        return

    icon = PAUSE_ICON if state["paused"] else \
        PLAYER_ICONS.get(state["source"], DEFAULT_ICON)
    title = clean_title(state["title"])
    players = state.get("players") or []
    which = ""
    if len(players) > 1:
        names = [p["player"] for p in players]
        index = names.index(state["player"]) + 1 if state["player"] in names else 1
        which = f" {index}/{len(players)}"

    tooltip = [f"<b>{escape(title)}</b>"]
    if state["artist"]:
        tooltip.append(escape(state["artist"]))
    tooltip.append(
        f"{state['source']} · {'paused' if state['paused'] else 'playing'}")
    if state["duration"]:
        tooltip.append(f"{hms(state['position'])} / {hms(state['duration'])}")
    if len(players) > 1:
        tooltip.append("")
        for p in players:
            mark = "\u25b6" if p["player"] == state["player"] else "\u00a0\u00a0"
            tooltip.append(f"{mark} {escape(p['source'])}: {escape(ellipsize(p['title'], 40))}"
                           f"{' (paused)' if p['paused'] else ''}")
    tooltip.append("\n<i>click for the preview panel · middle: play/pause · "
                   "right: next" + (" · scroll: switch source" if len(players) > 1 else "")
                   + "</i>")

    classes = ["paused" if state["paused"] else "playing"]
    if state["is_video"]:
        classes.append("video")
    classes.append(state["source"] or "unknown")

    print(json.dumps({
        "text": f"{icon} {'Paused' if state['paused'] else 'Playing'}{which}",
        "tooltip": "\n".join(tooltip),
        "class": classes,
        "alt": state["source"],
    }), flush=True)


# --------------------------------------------------------------------------
# thumb
# --------------------------------------------------------------------------
def resize_inplace(path, width=THUMB_WIDTH):
    tool = shutil.which("magick") or shutil.which("convert")
    if not tool:
        return
    subprocess.run([tool, path, "-resize", f"{width}x", "-strip", path],
                   capture_output=True, timeout=8)


def grab_frame(state, dest):
    """mpv first: it is the only source that can be asked for the frame on
    screen *right now*, which is the whole point of the preview. Everything
    else — a stream with no local file, an mpv without an IPC socket — falls
    back to seeking the file on disk."""
    if state["socket"]:
        raw = os.path.join(CACHE, "raw.jpg")
        if mpv_command(state["socket"], ["screenshot-to-file", raw, "video"]):
            if os.path.exists(raw) and os.path.getsize(raw) > 0:
                shutil.move(raw, dest)
                resize_inplace(dest)
                forget_art(dest)
                return True

    path = state["path"]
    if path and os.path.exists(path) and shutil.which("ffmpegthumbnailer"):
        try:
            done = subprocess.run(
                ["ffmpegthumbnailer", "-i", path, "-o", dest,
                 "-s", str(THUMB_WIDTH), "-q", "8",
                 # hh:mm:ss, never a bare number: ffmpegthumbnailer reads
                 # "-t 62" as 62 *percent* of the file, which is where the
                 # unrelated-looking frames came from.
                 "-t", seek_stamp(state["position"])],
                capture_output=True, timeout=8)
            if done.returncode == 0 and os.path.getsize(dest) > 0:
                forget_art(dest)
                return True
        except (subprocess.SubprocessError, OSError):
            pass
    return False


YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def art_url(state):
    """Firefox publishes no mpris:artUrl, but a YouTube watch URL is enough to
    name the poster frame — the only preview a browser tab will ever give us."""
    if state["art"]:
        return state["art"]
    match = YT_ID.search(state["url"] or "")
    if match:
        return f"https://i.ytimg.com/vi/{match.group(1)}/hqdefault.jpg"
    return ""


def fetch_art(url, dest):
    if not url:
        return False
    if url.startswith("file://"):
        src = url_to_path(url)
        if not os.path.exists(src):
            return False
        shutil.copyfile(src, dest)
    elif url.startswith(("http://", "https://")):
        if not shutil.which("curl"):
            return False
        done = subprocess.run(
            ["curl", "-sfL", "--max-time", "6", "-o", dest, url],
            capture_output=True)
        if done.returncode != 0 or not os.path.exists(dest):
            return False
    else:
        return False
    resize_inplace(dest)
    return os.path.getsize(dest) > 0


def forget_art(dest):
    """The file now holds a video frame, so the key must stop claiming that it
    holds the artwork it was last downloaded for."""
    try:
        os.remove(dest + ".key")
    except OSError:
        pass


def cached_art(url, dest):
    """Cover art does not change between polls, so a re-download every 2s would
    be pure waste. The key file records what the file on disk actually holds."""
    key_file = dest + ".key"
    try:
        with open(key_file) as handle:
            if handle.read() == url and os.path.getsize(dest) > 0:
                return True
    except OSError:
        pass
    if not fetch_art(url, dest):
        return False
    try:
        with open(key_file, "w") as handle:
            handle.write(url)
    except OSError:
        pass
    return True



# --------------------------------------------------------------------------
# watch — the pill, event-driven
# --------------------------------------------------------------------------
EMIT_LOCK = threading.Lock()
HEARTBEAT = 5.0         # s: while something is PLAYING (the tooltip clock moves)
IDLE_HEARTBEAT = 60.0   # s: paused or nothing playing -- a safety re-check only
DEBOUNCE = 0.12

_playing = False                # what the last publish saw
_wake = threading.Event()       # set by publish() so the heartbeat re-paces


def publish():
    """One writer at a time: the reader thread and the heartbeat both print."""
    global _playing
    with EMIT_LOCK:
        try:
            state = current()
            emit_status(state)
        except BrokenPipeError:
            os._exit(0)
        playing = bool(state) and not state["paused"]
        if playing != _playing:
            _playing = playing
            _wake.set()


def heartbeat():
    """Nothing announces the passage of time, so while a track PLAYS the
    tooltip's clock would sit at whatever it said when it last changed; this
    refreshes it. Paused, or with no player at all, nothing moves, and
    playerctl --follow reports any change -- so then it only re-checks once a
    minute (it used to run playerctl every 5 s even with no players). A
    publish that flips playing/paused wakes it to switch pace at once."""
    while True:
        if _wake.wait(HEARTBEAT if _playing else IDLE_HEARTBEAT):
            _wake.clear()
            continue            # re-paced; the publish that woke us just printed
        drop_cache()
        publish()


def follow(proc):
    """Publish once per burst of playerctl lines. A track change prints
    several lines in a row (one per changed field, per player); each used to
    cost its own full re-query. Reads the raw fd with select, since a
    buffered reader can hold lines select() cannot see."""
    fd = proc.stdout.fileno()
    while True:
        ready, _, _ = select.select([fd], [], [])
        if not ready:
            continue
        if not os.read(fd, 65536):
            return              # playerctl exited
        # Keep swallowing until the stream has been quiet for DEBOUNCE.
        while select.select([fd], [], [], DEBOUNCE)[0]:
            if not os.read(fd, 65536):
                drop_cache()
                publish()
                return
        drop_cache()
        publish()


def _die_with_parent():
    """Runs in the forked child before exec (see watch)."""
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)


def watch():
    """playerctl --follow emits a line whenever any player changes anything:
    track, status, position after a seek. That is the whole point — pause now
    shows up in the bar the moment it happens instead of up to two seconds
    later, and the 30 processes a minute the old poll cost are gone."""
    publish()
    threading.Thread(target=heartbeat, daemon=True).start()
    # cycle/select: republish now. From a thread, not in the handler: the
    # handler runs on the main thread, which may be inside publish() holding
    # EMIT_LOCK already.
    signal.signal(signal.SIGUSR1, lambda *_: threading.Thread(
        target=lambda: (drop_cache(), publish()), daemon=True).start())

    fmt = SEP.join("{{" + field + "}}" for field in FIELDS)
    while True:
        try:
            # waybar gives PR_SET_PDEATHSIG only to its direct children (this
            # script). playerctl is a grandchild: without its own PDEATHSIG it
            # outlives a bar restart, reparented to pid 1 and blocked on D-Bus
            # forever, one orphan per restart. prctl(1 = PR_SET_PDEATHSIG)
            # makes it die with this process. Popen runs on the main thread, so
            # a worker thread exiting cannot fire it early (PDEATHSIG tracks the
            # thread that forked, not the process).
            proc = subprocess.Popen(
                ["playerctl", "-a", "--follow", "metadata", "--format", fmt],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                preexec_fn=_die_with_parent)
        except (OSError, subprocess.SubprocessError):
            time.sleep(5)
            continue

        # The lines themselves are ignored: each carries one player's fields,
        # while the pill has to pick between all of them and ask mpv about
        # video. follow() only uses them as "something changed".
        follow(proc)

        proc.wait()
        # playerctl --follow normally stays up with zero players and reports
        # when one appears; it only exits if it fails (D-Bus gone, say). Say
        # so, then wait rather than respawning in a tight loop.
        drop_cache()
        publish()
        time.sleep(2)


# --------------------------------------------------------------------------
# control
# --------------------------------------------------------------------------
MPV_ACTIONS = {"toggle": ["cycle", "pause"],
               "next": ["playlist-next"],
               "prev": ["playlist-prev"]}
MPRIS_ACTIONS = {"toggle": "play-pause", "next": "next", "prev": "previous"}


def do_control(action):
    state = current()
    drop_cache()
    if not state:
        return
    if shutil.which("playerctl") and state["source"]:
        done = subprocess.run(
            ["playerctl", "--player", state["player"] or state["source"], MPRIS_ACTIONS[action]],
            capture_output=True, timeout=2)
        if done.returncode == 0:
            return
    # MPRIS refused or is not there — go straight at mpv.
    if state["socket"]:
        mpv_command(state["socket"], MPV_ACTIONS[action])


def do_seek(seconds):
    """mpv first: an absolute IPC seek is exact, where playerctl rounds to the
    second and some players ignore it outright."""
    state = current()
    drop_cache()
    if not state:
        return
    if state["socket"] and mpv_command(state["socket"],
                                       ["seek", float(seconds), "absolute"]):
        return
    if shutil.which("playerctl") and state["source"]:
        subprocess.run(["playerctl", "--player", state["player"] or state["source"],
                        "position", str(int(seconds))],
                       capture_output=True, timeout=2)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        if mode == "watch":
            watch()
        elif mode == "seek":
            do_seek(float(sys.argv[2]) if len(sys.argv) > 2 else 0)
        elif mode == "cycle":
            cycle(-1 if sys.argv[2:3] == ["prev"] else 1)
        elif mode == "select" and len(sys.argv) > 2:
            select(sys.argv[2])
        elif mode in MPV_ACTIONS:
            do_control(mode)
        else:
            emit_status()
    except Exception as exc:  # never let waybar see a traceback
        if mode == "status":
            print(json.dumps({"text": "", "tooltip": f"player.py: {exc}",
                              "class": "error"}))


if __name__ == "__main__":
    main()
