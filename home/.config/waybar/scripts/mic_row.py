#!/usr/bin/env python3
"""The toolbox card's Microphone row (custom/keybinds#mic in config-toolbox: the
name gives it the plain row's look in every theme; config-toolbox says why): the
default microphone's level, muted or not, and whether an app is listening.
Shown in the card while the top bar is off (bar-settings.py toolbox-config-
path, hypr/scripts/dock.py TOP BAR OFF); hidden otherwise, though Settings >
Bar & toolbox can show it for good.

    mic_row.py          one JSON line, then exit
    mic_row.py watch    a line whenever it changes, forever (no "interval")

The row: the microphone glyph (struck through while muted), "Microphone"
and the level; class "muted", "listening" (an app has it open: privacy.py's
mic_users, the bar's mic pill's own probe) or "on". Its clicks are in the
config: left mutes / unmutes, the wheel 5 % louder / quieter, right the
input devices in pavucontrol.

Event-driven like privacy.py's mic watcher: `pactl subscribe`, a source
change (the level, a mute) or a source-output (an app starting or stopping
to listen) or a new default (server), settled for DEBOUNCE, then one probe;
a line only when it differs from the last. Our own probes are `wpctl`
(PipeWire, not a pulse client) and privacy.py's `pactl list`, whose client
events are not listened to here, so they never echo.
"""
import json
import os
import re
import select
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import privacy  # noqa: E402  (mic_users: the bar's mic pill's probe)

MIC = ""          # Font Awesome microphone
MUTED = ""        # microphone-slash
# "Microphone" is also a Font Awesome icon name, and the card's font stack
# reaches Font Awesome first in some themes, whose ligature then draws the
# word as the icon (and "phone" too). A zero-width non-joiner between every
# letter breaks any ligature.
WORD = "\u200c".join("Microphone")
EVENTS = (b"on source", b"on source-output", b"on server")
DEBOUNCE = 0.15
RETRY_S = 2


def level(out):
    """`wpctl get-volume @DEFAULT_AUDIO_SOURCE@` ("Volume: 0.45 [MUTED]")
    -> (percent, muted), or None when it is not that."""
    m = re.match(r"\s*Volume:\s*([0-9.]+)(.*)", out or "")
    if not m:
        return None
    try:
        return round(float(m.group(1)) * 100), "MUTED" in m.group(2)
    except ValueError:
        return None


def row(got, users):
    """The JSON for a level (level()) and privacy.mic_users() -> dict."""
    if got is None:
        return {"text": f"{MUTED}   No {WORD.lower()}", "tooltip": "No microphone found", "class": "none"}
    pct, muted = got
    apps = ", ".join(dict.fromkeys(u["app"] for u in users))
    if muted:
        text, state = f"{MUTED}   {WORD} muted", "muted"
    else:
        text, state = f"{MIC}   {WORD} {pct}%", "listening" if users else "on"
    tip = f"Microphone {pct}%" + (" (muted)" if muted else "") + (f" · in use: {apps}" if apps else "")
    return {"text": text, "tooltip": tip + "\nclick: mute · wheel: level · right-click: devices",
            "class": state}


def probe():
    try:
        out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    try:
        users = privacy.mic_users()
    except Exception:         # noqa: BLE001 - a listener we cannot read is no row lost
        users = []
    return json.dumps(row(level(out), users))


def watch():
    last = None

    def emit():
        nonlocal last
        line = probe()
        if line != last:
            print(line, flush=True)
            last = line
    while True:
        emit()
        try:
            pactl = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        except OSError:
            time.sleep(RETRY_S * 5)
            continue
        try:
            fd = pactl.stdout.fileno()
            deadline = None
            while True:
                timeout = max(0.0, deadline - time.monotonic()) if deadline is not None else None
                ready, _, _ = select.select([fd], [], [], timeout)
                if ready:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break             # pactl ended: pipewire-pulse restarted
                    if deadline is None and any(e in chunk for e in EVENTS):
                        deadline = time.monotonic() + DEBOUNCE
                    continue
                deadline = None
                emit()
        finally:
            pactl.terminate()
            try:
                pactl.wait(timeout=2)
            except subprocess.SubprocessError:
                pactl.kill()
        time.sleep(RETRY_S)


def main():
    if sys.argv[1:2] == ["watch"]:
        signal.signal(signal.SIGTERM, privacy.exit_once)
        try:
            watch()
        except BrokenPipeError:
            pass
        return
    print(probe())


if __name__ == "__main__":
    main()
