#!/usr/bin/env python3
"""Voice memos: press, talk, press again -- the memo is saved as a small Opus
file, and written down as text by voice.py's local Whisper (nothing leaves
the computer), next to it and into the notes inbox.

    memo.py toggle            start a memo, or stop and save the one running
    memo.py start | stop
    memo.py status [--json]   recording or not, since when, the file
    memo.py folder            open ~/Documents/Memos
    memo.py last              play the newest memo (the default player)
    memo.py transcribe FILE   write FILE's text (FILE.txt + the inbox); run by
                              stop in the background, by hand to redo one

Where things go:

    ~/Documents/Memos/2026-10-28_09-41-12.opus   the sound (mono, 48 kb/s)
    ~/Documents/Memos/2026-10-28_09-41-12.txt    what was said
    ~/Documents/Notes/inbox.md                   one line per memo, beside
                                                 quicknote.py's notes:
        - 2026-10-28 09:41  [memo](~/Documents/Memos/...opus) what was said

The recorder is ffmpeg on PipeWire's pulse side (the default microphone).
Its pid file ($XDG_RUNTIME_DIR/memo.pid: pid / output / "memo") has the same
shape as record.sh's, so the capture pill (waybar recording.py) pulses red
while a memo runs and a click on it stops the memo. ffmpeg is stopped with
SIGINT, which makes it finish the file properly.

While it records, memo_card.py shows a card under the bar: the time, the
sound as bars, a Stop button and -- if Settings > Voice says so -- the
words as Whisper hears them. It closes itself when the memo ends; clicks
elsewhere leave it be. MEMO_CARD=0 (the tests) or memo_card=off: no card.

The text needs voice.py's engine (Settings > Voice). Without it, or in
gamemode, the memo is still saved; only its text is missing -- `memo.py
transcribe FILE` does it later.
"""
import datetime
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
PID_FILE = os.path.join(RUNTIME, "memo.pid")
MEMO_DIR = os.path.expanduser(os.environ.get("MEMO_DIR", "~/Documents/Memos"))
INBOX = os.path.expanduser(os.environ.get("MEMO_INBOX", "~/Documents/Notes/inbox.md"))  # = quicknote.py INBOX
# The pulse source: the default microphone. MEMO_SOURCE=@DEFAULT_MONITOR@
# records what the computer plays instead (how it is tried without talking).
SOURCE = os.environ.get("MEMO_SOURCE", "default")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desk_common  # noqa: E402  (notify: the notification, through scripts/notify)
VOICE = os.path.join(HERE, "voice.py")
CARD = os.path.join(HERE, "memo_card.py")   # the card under the bar while it records
VOICE_CONF = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                          "hypr", "voice.conf")         # = voice.py CONF (memo_card, memo_text)
RECORDER = "ffmpeg"                      # /proc/<pid>/comm of a live memo
STOP_WAIT_S = 5
MIN_BYTES = 2048                         # less is a memo that never got sound
TEXT_LIMIT = 400                         # the inbox line: the start of the text


# -- pure ----------------------------------------------------------------------------------
def memo_name(when):
    """The file name (no extension) for a memo started at `when`."""
    return when.strftime("%Y-%m-%d_%H-%M-%S")


def recorder_cmd(path):
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "pulse", "-i", SOURCE, "-ac", "1",
            "-c:a", "libopus", "-b:a", "48k", "-application", "voip", path]


def inbox_line(when, path, text):
    """One markdown list item, like quicknote.py's, linking the sound."""
    words = " ".join((text or "").split())
    if len(words) > TEXT_LIMIT:
        words = words[:TEXT_LIMIT - 1].rstrip() + "…"
    home = os.path.expanduser("~")
    shown = "~" + path[len(home):] if path.startswith(home + os.sep) else path
    return f"- {when.strftime('%Y-%m-%d %H:%M')}  [memo]({shown}) {words or '(no words heard)'}\n"


def read_pid(pidfile=PID_FILE):
    """(pid, output, started) for a live memo, else None. A file whose
    process is gone, or is no longer ffmpeg, counts as none."""
    try:
        started = os.stat(pidfile).st_mtime
        with open(pidfile) as fh:
            lines = fh.read().splitlines()
        pid = int(lines[0])
        with open(f"/proc/{pid}/comm") as fh:
            if fh.read().strip() != RECORDER:
                return None
    except (OSError, ValueError, IndexError):
        return None
    return pid, (lines[1] if len(lines) > 1 else ""), started


def newest(folder):
    """The newest memo's path in `folder`, or None."""
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".opus")]
    except OSError:
        return None
    return os.path.join(folder, max(names)) if names else None   # the names sort by time


def clock(secs):
    secs = max(0, int(secs))
    return f"{secs // 60}:{secs % 60:02d}"


# -- doing ---------------------------------------------------------------------------------
def notify(title, body="", urgency="normal", mood=None):
    desk_common.notify(title, body, app="Voice memo", urgency=urgency, mood=mood, background=True)


def start():
    if read_pid():
        return 0
    os.makedirs(MEMO_DIR, exist_ok=True)
    path = os.path.join(MEMO_DIR, memo_name(datetime.datetime.now()) + ".opus")
    try:
        proc = subprocess.Popen(recorder_cmd(path), start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except OSError as exc:
        notify("Voice memo did not start", str(exc), "critical", "alert")
        return 1
    tmp = PID_FILE + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(f"{proc.pid}\n{path}\nmemo\n")
    os.replace(tmp, PID_FILE)
    time.sleep(0.4)
    if proc.poll() is not None:
        # No microphone, pulse not there ...: ffmpeg is gone at once.
        os.unlink(PID_FILE)
        notify("Voice memo did not start", "No microphone answered (ffmpeg -f pulse).",
               "critical", "alert")
        return 1
    if card_wanted():
        try:
            subprocess.Popen([sys.executable, CARD], start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return 0


def card_wanted():
    """Settings > Voice, "Card while recording" (voice.conf memo_card)."""
    try:
        with open(VOICE_CONF) as fh:
            for line in fh:
                if line.strip() == "memo_card=off":
                    return False
    except OSError:
        pass
    return os.environ.get("MEMO_CARD", "1") != "0"


def stop():
    live = read_pid()
    if not live:
        try:
            os.unlink(PID_FILE)           # a stale one
        except OSError:
            pass
        return 0
    pid, path, started = live
    try:
        os.kill(pid, signal.SIGINT)      # ffmpeg writes the end of the file
    except OSError:
        pass
    deadline = time.time() + STOP_WAIT_S
    while time.time() < deadline and read_pid():
        time.sleep(0.1)
    if read_pid():
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if size < MIN_BYTES:
        notify("Voice memo was empty", "Nothing was recorded.", "normal", "alert")
        try:
            os.unlink(path)
        except OSError:
            pass
        return 1
    notify("Voice memo saved", f"{os.path.basename(path)} · {clock(time.time() - started)}\n"
           "Writing it down…", "low", "relieved")
    # The text, in the background: Whisper can take a moment.
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "transcribe", path],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


def transcribe(path):
    path = os.path.abspath(path)
    # voice.py's engine reads WAV only: a 16 kHz mono copy (Whisper's own
    # rate) for the length of the job.
    wav = os.path.join(RUNTIME, f"memo-{os.getpid()}.wav")
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-i", path, "-ar", "16000", "-ac", "1", wav],
                       check=True, capture_output=True, timeout=120)
        r = subprocess.run([sys.executable, VOICE, "transcribe", wav, "--json"],
                           capture_output=True, text=True, timeout=900)
        answer = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        answer = {"error": str(exc)}
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass
    text = (answer.get("text") or "").strip()
    if answer.get("error") and not text:
        notify("Memo saved without text", f"{answer['error']}\nLater: memo.py transcribe {path}",
               "normal", "alert")
        text = ""
    else:
        with open(os.path.splitext(path)[0] + ".txt", "w") as fh:
            fh.write(text + "\n")
    try:
        when = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        when = datetime.datetime.now()
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    with open(INBOX, "a") as fh:
        fh.write(inbox_line(when, path, text))
    if text:
        notify("Memo written down", text if len(text) < 200 else text[:199] + "…", "low")
    return 0


def status(as_json):
    live = read_pid()
    info = {"recording": bool(live), "file": live[1] if live else "",
            "elapsed": int(time.time() - live[2]) if live else 0, "folder": MEMO_DIR}
    if as_json:
        print(json.dumps(info))
    elif live:
        print(f"recording {clock(info['elapsed'])}  {info['file']}")
    else:
        print("idle")
    return 0


def main(argv):
    cmd = argv[0] if argv else "toggle"
    if cmd == "toggle":
        return stop() if read_pid() else start()
    if cmd == "start":
        return start()
    if cmd == "stop":
        return stop()
    if cmd == "status":
        return status("--json" in argv)
    if cmd == "folder":
        os.makedirs(MEMO_DIR, exist_ok=True)
        subprocess.Popen(["xdg-open", MEMO_DIR], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    if cmd == "last":
        path = newest(MEMO_DIR)
        if path is None:
            notify("No voice memos yet", "SUPER+CTRL+N records one.")
            return 1
        subprocess.Popen(["xdg-open", path], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    if cmd == "transcribe" and len(argv) > 1:
        return transcribe(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
