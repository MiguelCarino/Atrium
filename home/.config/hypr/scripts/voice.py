#!/usr/bin/env python3
"""Voice typing and live captions, on this machine's own graphics card
(faster-whisper; nothing leaves the computer).

    voice.py toggle                  start dictating, or stop and type it (the key)
    voice.py ptt start|stop          push-to-talk: the key's press and its release
    voice.py cancel                  stop dictating and throw the sound away
    voice.py command                 a voice COMMAND: start listening, again stop
                                     and do it (voice-command.py)
    voice.py command-ptt start|stop  the same, hold to talk
    voice.py captions on|off|toggle  live captions of what the computer plays
    voice.py unload                  put the model away now (frees the card)
    voice.py status [--json]         the daemon, the engine, the settings
    voice.py get [--json]            the settings
    voice.py set KEY VALUE           change one (the Settings page does this)
    voice.py transcribe FILE         a sound file to text, through the daemon
    voice.py selftest                espeak-ng says a sentence, it comes back as text
    voice.py bar                     the waybar module (custom/voice): a JSON
                                     line whenever the state changes, forever
    voice.py daemon                  the resident half (voice.service)
    voice.py worker | overlay        started by the daemon, not by hand

THREE PROCESSES, so nothing heavy stays resident:

    daemon   voice.service, system python, stdlib only (~15 MB). Owns the
             control socket ($XDG_RUNTIME_DIR/voice.sock), the microphone
             recorder, the captions loop, the state file the bar reads. The
             client commands above start it through systemd when it is not
             running, so it costs nothing at login.
    worker   the venv's python (~/.local/share/voice/venv) holding the
             faster-whisper model. Started on the first request, killed
             after `idle_min` minutes without one -- killing the process is
             the only way to give the card's memory back for sure. It talks
             JSON lines over its stdin / stdout; audio goes through a file in
             $XDG_RUNTIME_DIR (tmpfs, never on disk), deleted after.
    overlay  a GTK layer-shell strip at the bottom of the focused screen for
             the captions (namespace waybar-captions, so lua/rules.lua's
             waybar-glass rule frosts it). Click-through. Lives only while
             captions are on.

The CUDA libraries come from pip wheels (nvidia-cublas-cu12,
nvidia-cudnn-cu12) inside the venv; their lib/ folders go on the worker's
LD_LIBRARY_PATH when the daemon starts it -- the loader reads that variable
at process start, which is why the worker is its own process rather than a
module the daemon imports.

THE ENGINE, picked at every load (plan_engine(), pure, tested):

    device=cpu                              the CPU, `cpu_model` (int8)
    gamemode on (animations off, as         refused, politely -- unless
      lua/gamemode.lua tests it)              in_games=cpu: then the CPU
    the card has < model + MARGIN_MB free   the CPU, and a notification says
                                              why (device=cuda refuses instead)
    otherwise                               the card, `model`, int8_float16

The user's LM Studio model is never unloaded for this: the check is the
card's free memory (gpu.py's primary(), in-process: nothing forked), and
large-v3-turbo needs ~1.5 GB of it. faster-whisper's card engine is CUDA,
so only a card CUDA can drive counts (gpu_free_mb); any other card, or none,
is the CPU.

Dictation: pw-record from the default microphone, 16 kHz mono. It goes to
the window that was focused when it started (active_window()), and only to
it (may_type(), pure, tested): the focus is never moved to it -- that would
switch workspaces and spin the cube under the user -- and while another
window has the focus the phrases are held back, typed once the window is
focused again, or put on the clipboard at the end with a notification. A
popup panel or the toolbox is folded away first (close_panels()). Typing
waits RELEASE_S after the stop key and runs inside Hyprland's "dictation"
key mode (lua/userbinds.lua), where no shortcut but the dictation's own
works: a key still held cannot turn typed letters into shortcuts. Text
going into the same window soon after the last is joined to it with a space
(joined(), pure, tested). It is typed with wtype -- or pasted (wl-copy +
Ctrl+V), or only copied, as `output` says.

  live=on (the default)  each phrase is typed as soon as a pause of
                         LIVE_PAUSE_S ends it (the captions' cutter,
                         without drafts), while the next is spoken; the stop
                         types the rest. Not for push-to-talk: the held
                         SUPER+ALT would turn the letters into shortcuts.
  live=off, or ptt       into tmpfs, and on stop transcribed in one go
                         (beam 5, the silence trimmed by faster-whisper's VAD).

The recording is never kept.
MAX_RECORD_S stops a recording left running by itself (a push-to-talk key
whose release was lost).

Commands: the same recording and transcription (in command_language), but
the words are not typed: they go to voice-command.py, in a transient unit
(SyslogIdentifier=voice-command), through a file in tmpfs that it deletes
as it reads it -- it understands them with the local quick model, says
what it will do and does it (its docstring has the rest). `commands`,
`command_confirm` and `command_language` below are its settings.

Captions: pw-record from the default output's monitor (what you hear), cut
into rolling chunks by Captions (pure, tested): every STEP_S the current
phrase is transcribed again as a draft, and a pause of PAUSE_S (or MAX_S of
talking) makes it final. Silence is never sent to the model -- Whisper
"hears" a "Thank you." in silence -- and the usual silence phrases are
dropped (HALLUCINATIONS). translate=on gives English whatever is spoken
(Whisper's translate task). Final lines go to desktop memory's captions log
(remember_caption()) only while Settings > Privacy has that source on --
off as shipped; nothing of the captions is kept otherwise.

Settings, ~/.local/state/hypr/voice.conf (key=value, a missing key is its
default; DEFAULTS / CHOICES below say what each can be). The Settings page
(settings_pages/voice.py) writes them through `voice.py set`, which tells a
running daemon; a different model takes effect at the next load.
"""
import glob
import json
import math
import os
import signal
import socket
import subprocess
import sys
import threading
import queue
import time
from array import array

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desk_common  # noqa: E402  (notify: the notification, through scripts/notify)
SELF = os.path.abspath(__file__)
HOME = os.path.expanduser("~")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
SOCK = os.path.join(RUNTIME, "voice.sock")
STATE_FILE = os.path.join(RUNTIME, "voice.state")
WORK_DIR = os.path.join(RUNTIME, "voice")
CONF = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                    "hypr", "voice.conf")
DATA = os.path.join(HOME, ".local", "share", "voice")
VENV_PY = os.path.join(DATA, "venv", "bin", "python")
MODELS = os.path.join(DATA, "models")
SERVICE = "voice.service"

RATE = 16000                    # Whisper's own rate: no resampling in the worker
BYTES_PER_S = RATE * 2          # s16 mono
MAX_RECORD_S = 180
MAX_LIVE_S = 900                # live dictation types as it goes: a longer text is fine
MIN_RECORD_S = 0.4              # shorter than this is a key bounce, not speech
MARGIN_MB = 600                 # the card keeps this much free after loading
NOTIFY_TAG = "string:x-canonical-private-synchronous:voice"   # one bubble, replaced in place

DEFAULTS = {"model": "large-v3-turbo", "cpu_model": "small", "device": "auto", "language": "auto",
            "output": "type", "idle_min": "5", "in_games": "off", "translate": "off",
            "caption_size": "22", "caption_lines": "2",
            "commands": "on", "command_confirm": "off", "command_language": "auto", "live": "on",
            "memo_card": "on", "memo_text": "on"}
CHOICES = {"model": ("large-v3-turbo", "large-v3", "medium", "small", "distil-large-v3"),
           "commands": ("on", "off"), "command_confirm": ("on", "off"),
           "command_language": ("auto", "es", "en"),
           "cpu_model": ("tiny", "base", "small", "medium"),
           "device": ("auto", "cuda", "cpu"),
           "language": ("auto", "es", "en"),
           "output": ("type", "paste", "copy"),
           "in_games": ("off", "cpu"),
           "translate": ("on", "off"), "live": ("on", "off"),
           "memo_card": ("on", "off"), "memo_text": ("on", "off")}
NUMBERS = {"idle_min": (1, 120), "caption_size": (14, 48), "caption_lines": (1, 4)}
# The card's memory each model takes in int8_float16, MB -- large-v3-turbo
# measured here (1.38-1.46 GB with a few transcriptions done), the rest from
# their sizes. distil-large-v3 is English only.
VRAM_MB = {"large-v3-turbo": 1500, "large-v3": 2900, "medium": 1600, "small": 700,
           "distil-large-v3": 1500, "base": 300, "tiny": 200}
MODEL_NOTES = {"large-v3-turbo": "best balance: near large-v3 accuracy, several times faster",
               "large-v3": "most accurate, slowest, twice the card memory",
               "medium": "older, multilingual",
               "small": "fast, less accurate",
               "distil-large-v3": "fast and accurate, ENGLISH ONLY",
               "tiny": "fastest, rough", "base": "very fast, rough"}

# Live dictation: a phrase is typed once this much quiet follows it.
LIVE_PAUSE_S = 0.8
LIVE_MAX_S = 20.0
JOIN_WITHIN_S = 120
RELEASE_S = 0.6                 # after the stop key: let go of it before anything is typed             # a new dictation into the same window within this: a space first
PANEL = os.path.expanduser("~/.config/waybar/scripts/panel.py")
TOOLBOX = os.path.expanduser("~/.config/waybar/scripts/toolbox.sh")

# Captions
STEP_S = 1.2                    # a new draft of the phrase this often
PAUSE_S = 0.7                   # this much quiet after speech ends the phrase
MAX_S = 9.0                     # a phrase longer than this is cut anyway
QUIET_RMS = 250                 # int16 RMS under which 100 ms is "quiet" (~-42 dBFS)
BLOCK = BYTES_PER_S // 10       # 100 ms
HIDE_AFTER_S = 7                # captions fade out after this long with nothing new
# What Whisper says over silence, music or noise -- dropped when it is all
# the chunk said.
HALLUCINATIONS = {"thank you.", "thank you", "thanks for watching!", "thanks for watching.", "you",
                  "gracias.", "gracias", "¡gracias!", "subtítulos realizados por la comunidad de amara.org",
                  "¡suscríbete!", "suscríbete al canal", "...", "bye.", "música", "[música]", "[music]",
                  "(música)", "subtitles by the amara.org community"}


# -- settings ------------------------------------------------------------------------
def read_settings(path=None):
    values = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep and key in DEFAULTS:
                    values[key] = value.strip()
    except OSError:
        pass
    for key, value in list(values.items()):        # a hand-edited bad value is the default
        if check_value(key, value) is None:
            values[key] = DEFAULTS[key]
    return values


def check_value(key, value):
    """The normalized value, or None when KEY cannot be VALUE."""
    value = str(value).strip().lower()
    if key in CHOICES:
        return value if value in CHOICES[key] else None
    if key in NUMBERS:
        lo, hi = NUMBERS[key]
        try:
            n = int(value)
        except ValueError:
            return None
        return str(n) if lo <= n <= hi else None
    return None


def write_setting(key, value, path=None):
    path = path or CONF
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key!r} (one of: {', '.join(DEFAULTS)})")
    norm = check_value(key, value)
    if norm is None:
        allowed = "|".join(CHOICES[key]) if key in CHOICES else "%d-%d" % NUMBERS[key]
        raise ValueError(f"{key} must be {allowed}")
    values = read_settings(path)
    values[key] = norm
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        # Only what differs from the default: the file stays a list of choices.
        handle.writelines(f"{k}={v}\n" for k, v in values.items() if v != DEFAULTS[k])
    os.replace(tmp, path)
    return norm


# -- the engine choice (pure) --------------------------------------------------------
def plan_engine(settings, free_mb, gaming):
    """(device, model, compute_type, why) -- device None means refused, and
    why says so. free_mb: the card's free memory, None without a card."""
    gpu_model, cpu_model = settings["model"], settings["cpu_model"]
    cpu = ("cpu", cpu_model, "int8")
    if settings["device"] == "cpu":
        return (*cpu, "the CPU, as set")
    if gaming:
        if settings["in_games"] == "cpu":
            return (*cpu, "gamemode is on: the CPU, so the game keeps the card")
        return None, None, None, "gamemode is on: voice is paused so the game keeps the card"
    need = VRAM_MB.get(gpu_model, 1500) + MARGIN_MB
    if free_mb is None:
        if settings["device"] == "cuda":
            return None, None, None, "no graphics card the engine can use (it needs CUDA)"
        return (*cpu, "no graphics card the engine can use: the CPU")
    if free_mb < need:
        why = f"the card has {free_mb / 1024:.1f} GB free, {gpu_model} needs {need / 1024:.1f}"
        if settings["device"] == "cuda":
            return None, None, None, why
        return (*cpu, why + ": the CPU for now")
    return "cuda", gpu_model, "int8_float16", "the graphics card"


def free_mb_of(card):
    """A gpu.py card -> its free memory in MiB, or None when the engine
    cannot use it: no card, a card CTranslate2's CUDA build cannot drive
    (only NVIDIA's can), or one that does not say its memory."""
    if not card or card.get("vendor") != "nvidia":
        return None
    used, total = card.get("vram_used"), card.get("vram_total")
    if used is None or total is None:
        return None
    return total - used


def gpu_free_mb():
    """The main card's free memory in MiB (free_mb_of), from gpu.py in this
    process -- NVML kept open, nothing forked -- None without one."""
    try:
        sys.path.insert(0, HERE)
        import gpu
        return free_mb_of(gpu.primary())
    except Exception:  # noqa: BLE001 -- no card info: the CPU
        return None


def gaming():
    """Gamemode is on: animations off, the test lua/gamemode.lua makes."""
    try:
        out = subprocess.run(["hyprctl", "getoption", "animations:enabled", "-j"],
                             capture_output=True, text=True, timeout=2).stdout
        option = json.loads(out)
        return option.get("int", option.get("bool", 1)) in (0, False)
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return False


def cuda_lib_dirs(venv=None):
    """The venv's nvidia-*-cu12 lib folders, for the worker's LD_LIBRARY_PATH."""
    root = venv or os.path.join(DATA, "venv")
    return sorted(glob.glob(os.path.join(root, "lib*", "python3*", "site-packages", "nvidia", "*", "lib")))


def cached_models(root=None):
    """Model names already downloaded (faster-whisper's Hugging Face repos
    are Systran/faster-whisper-<name> and mobiuslabsgmbh/...-<name>)."""
    names = set()
    for path in glob.glob(os.path.join(root or MODELS, "models--*")):
        repo = os.path.basename(path).split("--")[-1]
        for name in VRAM_MB:
            if repo.endswith(name):
                names.add(name)
    return sorted(names)


# -- text out (pure argv builders + one runner) --------------------------------------
def output_argvs(text, mode):
    """The commands that put TEXT where the cursor is."""
    if mode == "copy":
        return [["wl-copy", "--", text]]
    if mode == "paste":
        return [["wl-copy", "--", text], ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]]
    return [["wtype", "--", text]]


def command_argv(path, language=None, note=None):
    """voice-command.py on a transcript file, as a transient unit whose log
    lines are tagged voice-command."""
    argv = ["systemd-run", "--user", "--quiet", "--collect", "-p", "SyslogIdentifier=voice-command",
            "--", sys.executable, os.path.join(HERE, "voice-command.py"), "run", path]
    if language in ("es", "en"):
        argv += ["--lang", language]
    if note:
        argv += ["--replace", str(note)]
    return argv


def deliver(text, mode):
    for argv in output_argvs(text, mode):
        try:
            subprocess.run(argv, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return False
        if argv[0] == "wl-copy":
            time.sleep(0.05)            # the clipboard offer is up before Ctrl+V
    return True


def joined(text, last, address, now):
    """TEXT as it should be typed after LAST = (address, time, text) of the
    previous phrase: a space between them when it goes into the same window
    soon after and neither side already has one (nor TEXT starts with
    punctuation that hugs the word before)."""
    text = text.strip()
    if not text or not last:
        return text
    prev_addr, prev_time, prev_text = last
    if prev_addr != address or now - prev_time > JOIN_WITHIN_S or not prev_text:
        return text
    if prev_text[-1].isspace() or text[0] in ",.;:!?)]}…":
        return text
    return " " + text


def active_window():
    """{address, class, xwayland} of the focused window, {} for none."""
    try:
        info = json.loads(subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True,
                                         text=True, timeout=2).stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    return info if isinstance(info, dict) and info.get("address") else {}


def close_panels():
    """A popup panel or the toolbox holds the keyboard while it is open
    (clicking the bar to stop opens nothing, but one may be up): fold them
    away so the keys reach the window under them."""
    for argv in ([PANEL, "close-all"], [TOOLBOX, "hide"]):
        try:
            subprocess.run(argv, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass


def submap(name):
    """Hyprland's key mode: "dictation" (userbinds.lua) has no shortcuts but
    the dictation's own, so letters typed while a key is still held stay
    letters; "reset" back -- but only out of ours, never out of another
    mode (keycapture) something else turned on."""
    if name == "reset":
        expr = 'if hl.get_current_submap() == "dictation" then hl.dispatch(hl.dsp.submap("reset")) end'
    else:
        expr = f'hl.dispatch(hl.dsp.submap("{name}"))'
    try:
        subprocess.run(["hyprctl", "eval", expr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def may_type(target, active):
    """Type only into the window the dictation started in, and only while it
    has the focus: never move the focus to it (that switches workspaces) and
    never type into whatever else is focused. No window at the start (an
    empty workspace): wherever the focus is then."""
    want = (target or {}).get("address")
    return not want or (active or {}).get("address") == want


def clean_text(segments):
    """Joined text of [{"text", "no_speech"}] segments, the silence phrases
    dropped."""
    parts = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text or seg.get("no_speech", 0) > 0.6:
            continue
        parts.append(text)
    text = " ".join(parts).strip()
    return "" if text.lower() in HALLUCINATIONS else text


# -- captions chunking (pure) ---------------------------------------------------------
def rms(block):
    samples = array("h")
    samples.frombytes(block[:len(block) - len(block) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class Captions:
    """Cuts a stream of 16 kHz s16 sound into phrases. feed(data) returns
    the work to do: ("draft", pcm) -- transcribe and show as the phrase so
    far; ("final", pcm) -- the phrase is over, transcribe and keep it. Quiet
    stretches are never handed out, and are trimmed so the buffer does not
    grow while nobody talks."""

    def __init__(self, step=STEP_S, pause=PAUSE_S, max_s=MAX_S, quiet=QUIET_RMS):
        self.step, self.pause, self.max_s, self.quiet = step, pause, max_s, quiet
        self.buf = bytearray()
        self.loud = []               # per 100 ms block of buf: above the quiet line?
        self.carry = b""
        self.since_draft = 0.0

    def feed(self, data):
        out = []
        data = self.carry + data
        cut = len(data) - len(data) % BLOCK
        self.carry = data[cut:]
        for i in range(0, cut, BLOCK):
            block = data[i:i + BLOCK]
            self.buf += block
            self.loud.append(rms(block) >= self.quiet)
            self.since_draft += 0.1
            work = self._after_block()
            if work:
                out.append(work)
        return out

    def _after_block(self):
        seconds = len(self.loud) / 10
        if not any(self.loud):
            if seconds > 1.0:            # nobody talking: keep only the last 0.3 s
                self._keep_last(3)
            return None
        tail = int(self.pause * 10)
        if seconds >= self.max_s or (len(self.loud) > tail and not any(self.loud[-tail:])):
            pcm = bytes(self.buf)
            self._keep_last(0)
            self.since_draft = 0.0
            return ("final", pcm)
        if self.since_draft >= self.step:
            self.since_draft = 0.0
            return ("draft", bytes(self.buf))
        return None

    def _keep_last(self, blocks):
        if blocks:
            self.buf = self.buf[-blocks * BLOCK:]
            self.loud = self.loud[-blocks:]
        else:
            self.buf, self.loud = bytearray(), []


# -- the bar (custom/voice) ------------------------------------------------------------
ICON_MIC = ""
ICON_WAIT = ""            # spinner
ICON_CC = ""              # closed-captioning


def read_state(path=None):
    """The daemon's state file, or {} when there is no live daemon."""
    try:
        with open(path or STATE_FILE) as handle:
            state = json.load(handle)
        os.kill(int(state.get("pid", 0)), 0)
        return state
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def bar_status(state, now=None):
    now = now or time.time()
    what = state.get("state", "idle")
    engine = state.get("engine") or "not loaded"
    keys = "SUPER+H stop  ·  SUPER+ALT+V hold to talk  ·  SUPER+SHIFT+V captions"
    if what == "recording" and state.get("mode") == "command":
        secs = int(now - state.get("since", now))
        return {"text": f"{ICON_MIC} {secs // 60}:{secs % 60:02d}", "class": "recording",
                "tooltip": f"Listening for a command -- say it, then stop\nEngine: {engine}\n\n"
                           "Click: stop and do it  ·  Right-click: cancel"}
    if what == "recording":
        secs = int(now - state.get("since", now))
        return {"text": f"{ICON_MIC} {secs // 60}:{secs % 60:02d}", "class": "recording",
                "tooltip": f"Dictating -- speak, then stop to type it\nEngine: {engine}\n\n"
                           f"Click: stop and type  ·  Right-click: cancel\n{keys}"}
    if what in ("transcribing", "loading"):
        word = "Loading the model" if what == "loading" else "Transcribing"
        return {"text": f"{ICON_WAIT} {word.split()[0]}", "class": "busy",
                "tooltip": f"{word}…\nEngine: {engine}"}
    if state.get("captions"):
        return {"text": ICON_CC, "class": "captions",
                "tooltip": f"Live captions on{' (to English)' if state.get('translate') else ''}\n"
                           f"Engine: {engine}\n\nClick: captions off"}
    return {"text": "", "class": "idle", "tooltip": ""}


IN_CLOSE_WRITE, IN_MOVED_TO, IN_DELETE = 0x8, 0x80, 0x200
BAR_IDLE_WATCHED_S = 60      # idle, inotify on: a look this often anyway
BAR_IDLE_POLL_S = 2          # idle, no inotify: a poll this often
BAR_CAPTIONS_S = 5           # captions on: a daemon that dies writes nothing, so look this often


def state_watch(folder=None):
    """An inotify fd on the state file's folder (non-blocking), or None
    where inotify is not to be had -- the bar then polls."""
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            return None
        if libc.inotify_add_watch(fd, (folder or RUNTIME).encode(), IN_CLOSE_WRITE | IN_MOVED_TO | IN_DELETE) < 0:
            os.close(fd)
            return None
        return fd
    except (OSError, AttributeError):
        return None


def watch_names(data):
    """The file names in a read() of inotify events."""
    names, i = [], 0
    while i + 16 <= len(data):
        length = int.from_bytes(data[i + 12:i + 16], sys.byteorder)
        names.append(data[i + 16:i + 16 + length].rstrip(b"\0").decode("utf-8", "replace"))
        i += 16 + length
    return names


def bar_wait(state, now, watched):
    """How long the bar's loop may sleep -- pure, for the tests. Recording:
    to the clock's next whole second; loading/transcribing: a second;
    captions on: BAR_CAPTIONS_S (a crashed daemon writes no state); idle:
    nothing changes by itself, so with inotify it only wakes for a
    state-file change (or BAR_IDLE_WATCHED_S), without it every
    BAR_IDLE_POLL_S. It used to wake 2-4 times a second all day."""
    what = state.get("state") if state and state.get("pid") else "idle"
    if what == "recording":
        return 1.0 - ((now - state.get("since", now)) % 1.0) + 0.02
    if what in ("transcribing", "loading"):
        return 1.0
    if state and state.get("pid") and state.get("captions"):
        return BAR_CAPTIONS_S if watched else BAR_IDLE_POLL_S    # the CC icon must not outlive a crash
    return BAR_IDLE_WATCHED_S if watched else BAR_IDLE_POLL_S


def bar():
    import select
    last = None
    fd = state_watch(os.path.dirname(STATE_FILE))
    name = os.path.basename(STATE_FILE)
    while True:
        state = read_state()
        status = bar_status(state)
        if status != last:
            print(json.dumps(status), flush=True)
            last = status
        wait = bar_wait(state, time.time(), fd is not None)
        if fd is None:
            time.sleep(wait)
            continue
        # Woken by any change in the runtime folder: only ours counts.
        end = time.monotonic() + wait
        while True:
            left = end - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                break
            try:
                if name in watch_names(os.read(fd, 65536)):
                    break
            except BlockingIOError:
                pass


# -- client ---------------------------------------------------------------------------
def request(msg, timeout=120, start=True):
    """Send MSG to the daemon, its JSON answer back; start voice.service if
    it is down."""
    for attempt in range(2):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(SOCK)
                s.sendall(json.dumps(msg).encode() + b"\n")
                data = b""
                while not data.endswith(b"\n"):
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            return json.loads(data or b"{}")
        except (OSError, ValueError):
            if not start or attempt:
                return {"error": "the voice daemon is not running"}
            subprocess.run(["systemctl", "--user", "start", SERVICE], capture_output=True, timeout=15)
            for _ in range(30):
                if os.path.exists(SOCK):
                    break
                time.sleep(0.1)
    return {"error": "the voice daemon did not start (journalctl --user -u voice)"}


CAPTIONS_LOG = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                            "desktop-memory", "captions.jsonl")


def remember_caption(text, path=None):
    """A final caption line into desktop-memory.py's captions log, only when
    privacy.conf has memory and memory_captions on (re-read each time: the
    switch counts at once). Never raises; True when written."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import privacy_settings
        if "captions" not in privacy_settings.memory_sources(privacy_settings.load()):
            return False
        path = path or CAPTIONS_LOG
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as handle:
            handle.write(json.dumps({"t": round(time.time(), 1), "text": text}, ensure_ascii=False) + "\n")
        return True
    except Exception:       # noqa: BLE001 -- the captions must not stop for this
        return False


def notify(title, body="", replace=None, timeout=2500, urgency="normal"):
    """notify-send; the id back, for replacing the same bubble later."""
    out = desk_common.notify(title, body, app="Voice", icon="audio-input-microphone", urgency=urgency,
                             expire=timeout, hints=[NOTIFY_TAG], print_id=True, replace_id=replace,
                             timeout=5)
    return out or replace


# -- daemon ---------------------------------------------------------------------------
def end_proc(proc, grace=3):
    """terminate, wait `grace` s, then kill -- and always wait at the end, so
    the child is reaped (a captions run once left pw-record and the overlay
    as zombies of this daemon for hours)."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(grace)
    except subprocess.TimeoutExpired:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(grace)
    except (OSError, subprocess.SubprocessError):
        pass


class Worker:
    """The venv python holding the model, one request at a time."""

    def __init__(self, device, model, compute):
        self.device, self.model, self.compute = device, model, compute
        env = dict(os.environ, HF_HUB_DISABLE_TELEMETRY="1", PYTHONUNBUFFERED="1",
                   LD_LIBRARY_PATH=":".join(cuda_lib_dirs() + [os.environ.get("LD_LIBRARY_PATH", "")]).rstrip(":"))
        self.proc = subprocess.Popen([VENV_PY, SELF, "worker", device, model, compute],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
        self.lock = threading.Lock()
        self.used = time.time()
        self.ready = None            # the load's answer, once read

    def wait_ready(self):
        with self.lock:
            if self.ready is None:
                line = self.proc.stdout.readline()
                try:
                    self.ready = json.loads(line)
                except ValueError:
                    self.ready = {"error": "the engine stopped while loading (journalctl --user -u voice)"}
            return self.ready

    def ask(self, msg):
        ready = self.wait_ready()
        if ready.get("error"):
            return ready
        with self.lock:
            self.used = time.time()
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
                answer = json.loads(self.proc.stdout.readline())
            except (OSError, ValueError):
                answer = {"error": "the engine stopped (journalctl --user -u voice)"}
            self.used = time.time()
            return answer

    def alive(self):
        return self.proc.poll() is None

    def stop(self):
        end_proc(self.proc, 5)


class Daemon:
    def __init__(self):
        self.lock = threading.RLock()
        self.worker = None
        self.state = "idle"
        self.since = time.time()
        self.rec = None              # the pw-record process while dictating
        self.rec_path = None
        self.rec_ptt = False
        self.rec_mode = "dictate"    # or "command": the words go to voice-command.py
        self.stopped_at = 0.0
        self.note = None             # the notification id of this dictation
        self.target = {}             # the window focused when the dictation started
        self.last_typed = None       # (address, time, text) of the last phrase typed
        self.held = []               # phrases waiting for the window to be focused again
        self.told_held = False
        self.started_at = 0.0
        self.live = None             # (reader thread, phrase queue, typer thread) while live
        self.captions = None         # the captions thread's stop event
        self.overlay = None
        self.write_state()

    # state ---------------------------------------------------------------------
    def set_state(self, state):
        self.state, self.since = state, time.time()
        self.write_state()

    def write_state(self):
        w = self.worker
        state = {"pid": os.getpid(), "state": self.state, "since": self.since, "mode": self.rec_mode,
                 "captions": self.captions is not None, "translate": read_settings()["translate"] == "on",
                 "engine": f"{w.model} on the {'graphics card' if w.device == 'cuda' else 'CPU'}"
                           if w and w.alive() else None}
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(state, handle)
        os.replace(tmp, STATE_FILE)

    # the engine ----------------------------------------------------------------
    def engine(self):
        """The running worker, started (or swapped) as plan_engine says; a
        (None, why) refusal otherwise."""
        with self.lock:
            settings = read_settings()
            is_gaming = gaming()
            w = self.worker
            if w and w.alive():
                # Keep it while it is still what plan_engine would pick: the
                # same model, and not on the card under gamemode. A CPU model
                # loaded because the card was full is kept until the card
                # has room again.
                if w.device == "cuda":
                    if not is_gaming and settings["device"] != "cpu" and settings["model"] == w.model:
                        return w, None
                elif settings["cpu_model"] == w.model:
                    if plan_engine(settings, gpu_free_mb(), is_gaming)[0] == "cpu":
                        return w, None
                self.unload()
            if not os.path.exists(VENV_PY):
                return None, f"the engine is not installed ({VENV_PY} missing)"
            device, model, compute, why = plan_engine(settings, gpu_free_mb(), is_gaming)
            if device is None:
                return None, why
            if device == "cpu" and settings["device"] != "cpu":
                notify("Voice: using the CPU", why, timeout=4000)
            if model not in cached_models():
                notify("Voice: downloading the model", f"{model}, once -- this takes a minute", timeout=8000)
            self.worker = Worker(device, model, compute)
            self.write_state()
            return self.worker, None

    def unload(self):
        with self.lock:
            if self.worker:
                self.worker.stop()
                self.worker = None
                self.write_state()

    def idle_loop(self):
        while True:
            time.sleep(20)
            w = self.worker
            limit = int(read_settings()["idle_min"]) * 60
            if w and self.captions is None and self.state == "idle" and time.time() - w.used > limit:
                self.unload()
            elif w and w.device == "cuda" and self.state == "idle" and gaming():
                # Gamemode came on with the model on the card: give it back
                # now, not at the idle limit (captions stop at their next
                # phrase, refused by engine()).
                self.unload()
            elif w and not w.alive():
                self.worker = None
                self.write_state()

    def transcribe(self, path, task="transcribe", beam=5, vad=True, language=None):
        worker, why = self.engine()
        if not worker:
            return {"error": why}
        language = language or read_settings()["language"]
        return worker.ask({"path": path, "language": None if language == "auto" else language,
                           "task": task, "beam": beam, "vad": vad})

    # dictation -----------------------------------------------------------------
    def start(self, ptt=False, mode="dictate"):
        with self.lock:
            if self.rec:
                return {"state": "recording"}
            settings = read_settings()
            if mode == "command" and settings["commands"] != "on":
                notify("Voice commands are off", "Settings > Voice turns them on.")
                return {"error": "commands off"}
            if gaming() and settings["in_games"] != "cpu" and settings["device"] != "cpu":
                notify("Voice typing is paused in gamemode",
                       "The game keeps the graphics card. Settings > Voice can use the CPU instead.")
                return {"error": "gamemode"}
            os.makedirs(WORK_DIR, mode=0o700, exist_ok=True)
            # One file per recording: the last one may still be being transcribed (and is
            # deleted after), so a new recording never shares its file.
            self.rec_path = os.path.join(WORK_DIR, f"dictation-{os.getpid()}-{time.time_ns()}.raw")
            self.target = active_window() if mode == "dictate" else {}
            self.held, self.told_held, self.started_at = [], False, time.time()
            # Live: each phrase typed as soon as a pause ends it. Not while a
            # push-to-talk key is held -- its SUPER+ALT would turn the typed
            # letters into shortcuts.
            live = mode == "dictate" and not ptt and settings["live"] == "on"
            argv = ["pw-record", "--rate", str(RATE), "--channels", "1",
                    "--format", "s16", "--raw", "-P", '{ media.name="Voice typing" }', "-"]
            if live:
                self.rec = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                phrases = queue.Queue()
                reader = threading.Thread(target=self._live_read, args=(self.rec, phrases), daemon=True)
                typer = threading.Thread(target=self._live_type, args=(phrases, settings["output"]), daemon=True)
                self.live = (reader, phrases, typer)
                self.live_count = 0
                reader.start()
                typer.start()
            else:
                out = open(self.rec_path, "wb")
                self.rec = subprocess.Popen(argv, stdout=out, stderr=subprocess.DEVNULL)
                out.close()
            self.rec_ptt = ptt
            self.rec_mode = mode
            self.set_state("recording")
            where = self.target.get("class") or "the focused window"
            if mode == "command":
                stop_key = "let go of the key" if ptt else "the same key again"
                self.note = notify("Listening for a command…", f"Say it; {stop_key} to do it.", timeout=0)
            elif live:
                self.note = notify("Dictating…", f"Into {where}, a phrase at each pause. "
                                   "SUPER+H again to finish.", timeout=0)
            else:
                stop_key = "let go of the key" if ptt else "SUPER+H again"
                self.note = notify("Listening…", f"Speak; {stop_key} to type it into {where}.", timeout=0)
            started = self.rec
            threading.Thread(target=self._cap, args=(started,), daemon=True).start()
        # Warm the engine up while the person talks: by the stop it is loaded.
        threading.Thread(target=self._warm, daemon=True).start()
        return {"state": "recording"}

    def _warm(self):
        worker, _why = self.engine()
        if worker:
            worker.wait_ready()
            self.write_state()

    def _cap(self, proc):
        try:
            proc.wait(MAX_LIVE_S if self.live else MAX_RECORD_S)
        except subprocess.TimeoutExpired:
            if self.rec is proc:
                self.stop()

    def stop(self, cancel=False):
        with self.lock:
            proc, path = self.rec, self.rec_path
            if not proc:
                return {"state": self.state}
            self.rec = None
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                end_proc(proc, 2)
            self.stopped_at = time.time()
            live, self.live = self.live, None
        if live:
            return self._live_finish(live, cancel)
        with self.lock:
            size = os.path.getsize(path) if os.path.exists(path) else 0
            if cancel or size < MIN_RECORD_S * BYTES_PER_S:
                if os.path.exists(path):
                    os.unlink(path)
                self.set_state("idle")
                notify("Dictation cancelled" if cancel else "Nothing recorded", replace=self.note, timeout=1200)
                return {"state": "idle"}
            loaded = self.worker is not None and self.worker.ready is not None
            self.set_state("transcribing" if loaded else "loading")
            command = self.rec_mode == "command"
        notify("Transcribing…", replace=self.note, timeout=0)
        try:
            language = read_settings()["command_language"] if command else None
            answer = self.transcribe(path, language=language if language != "auto" else None)
        finally:
            if os.path.exists(path):
                os.unlink(path)
        text = answer.get("text", "")
        if answer.get("error"):
            notify("Voice typing failed", answer["error"], replace=self.note, urgency="critical", timeout=6000)
        elif not text:
            notify("Heard nothing", "No words in that recording.", replace=self.note, timeout=1500)
        elif command:
            self.hand_off(text, answer.get("language"))
        else:
            mode = read_settings()["output"]
            self.type_text(text, mode)
            if self.leftover():
                text = ""
        if text and not answer.get("error") and not command:
            done = {"type": "Typed", "paste": "Pasted", "copy": "Copied to the clipboard"}[mode]
            notify(done, f"{text[:160]}\n{answer.get('language', '?')} · {answer.get('audio_s', 0):.1f} s of "
                         f"speech in {answer.get('secs', 0):.2f} s", replace=self.note, timeout=2500)
        with self.lock:
            # A new recording may have started while this one was transcribed:
            # its mode stays (a command reset to "dictate" would be typed).
            if not self.rec:
                self.set_state("idle")
                self.rec_mode = "dictate"
        return {"state": "idle", **answer}

    # live dictation ------------------------------------------------------------
    def type_text(self, text, mode):
        """TEXT into the dictation's window, joined to the phrase before --
        or held back while another window has the focus (may_type), to go
        in once the window is focused again, or onto the clipboard at the end."""
        if self.stopped_at and self.stopped_at >= self.started_at:
            wait = RELEASE_S - (time.time() - self.stopped_at)
            if wait > 0:
                time.sleep(wait)
        if mode == "copy":                  # the clipboard is no window: nothing to guard
            return bool(text.strip()) and deliver(text.strip(), mode)
        close_panels()
        self.held.append(text.strip())
        active = active_window()
        if not may_type(self.target, active):
            if not self.told_held:
                self.told_held = True
                where = self.target.get("class") or "the window you started in"
                notify("Dictation waiting", f"Go back to {where} and it types there; "
                       "it never types into another window.", replace=self.note, timeout=0)
            return False
        address = self.target.get("address") or active.get("address")
        now = time.time()
        text = joined(" ".join(t for t in self.held if t), self.last_typed, address, now)
        self.held = []
        if not text:
            return False
        submap("dictation")
        try:
            ok = deliver(text, mode)
        finally:
            submap("reset")
        if ok:
            self.last_typed = (address, now, text)
        return ok

    def leftover(self):
        """At the end: what could not be typed (the window was never focused
        again) goes onto the clipboard, and a notification says so."""
        text = " ".join(t for t in self.held if t)
        self.held = []
        if not text:
            return False
        deliver(text, "copy")
        where = self.target.get("class") or "the window you started in"
        notify("Not typed: on the clipboard", f"{where} did not have the focus. "
               f"Paste it where it goes.\n{text[:160]}", replace=self.note, timeout=6000)
        return True

    def _live_read(self, proc, phrases):
        """The microphone, cut at pauses (the captions' cutter, without
        drafts): each phrase onto the queue; the rest at the end."""
        cut = Captions(step=10 ** 9, pause=LIVE_PAUSE_S, max_s=LIVE_MAX_S)
        while True:
            data = proc.stdout.read1(BLOCK * 2)
            if not data:
                break
            for _kind, pcm in cut.feed(data):
                phrases.put(pcm)
        if any(cut.loud):
            phrases.put(bytes(cut.buf))
        phrases.put(None)

    def _live_type(self, phrases, mode):
        """Phrases off the queue, one at a time: written down and typed."""
        chunk = os.path.join(WORK_DIR, f"live-{time.time_ns()}.raw")
        failed = False
        try:
            while True:
                pcm = phrases.get()
                if pcm is None:
                    break
                if failed:
                    continue
                with open(chunk, "wb") as handle:
                    handle.write(pcm)
                answer = self.transcribe(chunk)
                if answer.get("error"):
                    failed = True
                    notify("Voice typing failed", answer["error"], replace=self.note,
                           urgency="critical", timeout=6000)
                    continue
                text = answer.get("text", "")
                if text:
                    self.type_text(text, mode)
                    self.live_count += 1
        finally:
            if os.path.exists(chunk):
                os.unlink(chunk)

    def _live_finish(self, live, cancel):
        reader, phrases, typer = live
        if cancel:
            # What is still queued is thrown away; what was typed stays typed.
            while True:
                try:
                    phrases.get_nowait()
                except queue.Empty:
                    break
            phrases.put(None)
        with self.lock:
            self.set_state("transcribing")
        notify("Finishing…", replace=self.note, timeout=0)
        reader.join(10)
        typer.join(120)
        clipboard = False
        if not cancel and self.held:
            # Phrases held back while another window had the focus: in now if
            # it is back, else onto the clipboard (leftover() says so).
            if may_type(self.target, active_window()):
                self.type_text("", read_settings()["output"])
            clipboard = self.leftover()
        if clipboard:
            pass
        elif cancel:
            notify("Dictation cancelled", replace=self.note, timeout=1200)
        elif self.live_count:
            notify("Typed", f"{self.live_count} phrase{'s' if self.live_count != 1 else ''} into "
                   f"{self.target.get('class') or 'the focused window'}", replace=self.note, timeout=1500)
        else:
            notify("Heard nothing", "No words in that recording.", replace=self.note, timeout=1500)
        with self.lock:
            if not self.rec:
                self.set_state("idle")
                self.rec_mode = "dictate"
        return {"state": "idle", "phrases": self.live_count}

    def hand_off(self, text, language=None):
        """The words of a command to voice-command.py: through a file in
        tmpfs (not argv, which `systemctl status` and the journal would
        show), in a transient unit so a long Confirm / Undo wait never
        holds this daemon, and the journal has it under voice-command."""
        os.makedirs(WORK_DIR, mode=0o700, exist_ok=True)
        path = os.path.join(WORK_DIR, f"command-{time.time_ns()}.txt")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        argv = command_argv(path, language, self.note)
        try:        # systemd-run returns once the unit is started, not when it is done
            done = subprocess.run(argv, capture_output=True, text=True, timeout=15)
            problem = ((done.stderr or done.stdout).strip()[-200:] or f"exit {done.returncode}") \
                if done.returncode else ""
        except (OSError, subprocess.SubprocessError) as exc:
            problem = str(exc)
        if problem:     # it never started: the words must not stay behind in tmpfs
            if os.path.exists(path):
                os.unlink(path)
            notify("Voice command failed", problem, replace=self.note, urgency="critical", timeout=6000)

    # captions ------------------------------------------------------------------
    def captions_on(self, source=None):
        with self.lock:
            if self.captions is not None:
                return {"captions": True}
            worker, why = self.engine()
            if not worker:
                notify("Live captions are off", why)
                return {"error": why}
            stop = threading.Event()
            self.captions = stop
            self.write_state()
        threading.Thread(target=self._captions, args=(stop, source), daemon=True).start()
        return {"captions": True}

    def captions_off(self):
        with self.lock:
            if self.captions is not None:
                self.captions.set()
                self.captions = None
            self.write_state()
        return {"captions": False}

    def _show(self, lines):
        settings = read_settings()
        try:
            self.overlay.stdin.write(json.dumps({"lines": lines, "size": int(settings["caption_size"])}) + "\n")
            self.overlay.stdin.flush()
        except (OSError, AttributeError, ValueError):
            pass

    def _captions(self, stop, source=None):
        """The captions loop: sound in, phrases out to the overlay. SOURCE
        (a raw 16 kHz s16 file) stands in for the speakers in tests."""
        if source:
            rec = subprocess.Popen(["cat", source], stdout=subprocess.PIPE)
        else:
            rec = subprocess.Popen(["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16",
                                    "--raw", "-P", '{ stream.capture.sink=true media.name="Live captions" }', "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.overlay = subprocess.Popen([sys.executable, SELF, "overlay"], stdin=subprocess.PIPE, text=True)
        cut = Captions()
        final, last_text = [], time.time()
        os.makedirs(WORK_DIR, mode=0o700, exist_ok=True)
        chunk_path = os.path.join(WORK_DIR, "caption.raw")
        try:
            while not stop.is_set():
                data = rec.stdout.read1(BLOCK * 2)
                if not data:
                    break
                if source:                       # a file plays at the speed it was spoken
                    time.sleep(len(data) / BYTES_PER_S)
                for kind, pcm in cut.feed(data):
                    settings = read_settings()
                    with open(chunk_path, "wb") as handle:
                        handle.write(pcm)
                    answer = self.transcribe(chunk_path, task="translate" if settings["translate"] == "on"
                                             else "transcribe", beam=1, vad=False)
                    if answer.get("error"):          # gamemode came on, the engine died...
                        notify("Live captions stopped", answer["error"])
                        stop.set()
                        break
                    text = answer.get("text", "")
                    if not text:
                        continue
                    keep = int(settings["caption_lines"])
                    if kind == "final":
                        remember_caption(text)
                        final = (final + [text])[-keep:]
                        self._show(final)
                    else:
                        self._show((final + [text])[-keep:])
                    last_text = time.time()
                if final and time.time() - last_text > HIDE_AFTER_S:
                    final = []
                    self._show([])
        finally:
            end_proc(rec)
            if self.overlay:
                overlay, self.overlay = self.overlay, None
                try:
                    overlay.stdin.close()       # its read loop ends on EOF
                except OSError:
                    pass
                end_proc(overlay)
            if os.path.exists(chunk_path):
                os.unlink(chunk_path)
            with self.lock:
                if self.captions is stop:
                    self.captions = None
                self.write_state()

    # the socket ----------------------------------------------------------------
    def handle(self, msg):
        cmd = msg.get("cmd")
        if cmd == "toggle":
            return self.stop() if self.rec else self.start()
        if cmd == "ptt-start":
            return self.start(ptt=True)
        if cmd == "ptt-stop":
            return self.stop() if self.rec and self.rec_ptt else {"state": self.state}
        if cmd == "command":
            return self.stop() if self.rec else self.start(mode="command")
        if cmd == "command-ptt-start":
            return self.start(ptt=True, mode="command")
        if cmd == "command-ptt-stop":
            return self.stop() if self.rec and self.rec_ptt else {"state": self.state}
        if cmd == "stop":
            return self.stop()
        if cmd == "cancel":
            return self.stop(cancel=True)
        if cmd == "captions":
            want = msg.get("on")
            if want is None:
                want = self.captions is None
            return self.captions_on(msg.get("source")) if want else self.captions_off()
        if cmd == "transcribe":
            return self.transcribe(msg["path"], task=msg.get("task", "transcribe"))
        if cmd == "unload":
            self.unload()
            return {"unloaded": True}
        if cmd == "reload":
            self.write_state()
            return {"ok": True}
        if cmd == "status":
            w = self.worker
            return {"state": self.state, "captions": self.captions is not None,
                    "worker": {"device": w.device, "model": w.model, "pid": w.proc.pid,
                               "idle_s": int(time.time() - w.used),
                               "ready": bool(w.ready and not w.ready.get("error"))} if w and w.alive() else None}
        return {"error": f"unknown command {cmd!r}"}

    def serve(self):
        os.makedirs(WORK_DIR, mode=0o700, exist_ok=True)
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCK)
        os.chmod(SOCK, 0o600)
        server.listen(8)
        threading.Thread(target=self.idle_loop, daemon=True).start()

        def one(conn):
            with conn:
                try:
                    data = b""
                    while not data.endswith(b"\n"):
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        data += chunk
                    answer = self.handle(json.loads(data or b"{}"))
                except Exception as exc:          # one bad request never takes the daemon down
                    answer = {"error": f"{type(exc).__name__}: {exc}"}
                try:
                    conn.sendall(json.dumps(answer).encode() + b"\n")
                except OSError:
                    pass

        while True:
            conn, _ = server.accept()
            threading.Thread(target=one, args=(conn,), daemon=True).start()

    def shutdown(self, *_):
        if self.rec:
            self.rec.kill()
        self.captions_off()
        if self.overlay:
            self.overlay.terminate()
        self.unload()
        for path in (SOCK, STATE_FILE):
            try:
                os.unlink(path)
            except OSError:
                pass
        for path in glob.glob(os.path.join(WORK_DIR, "*.raw")):
            os.unlink(path)
        os._exit(0)


def daemon():
    d = Daemon()
    signal.signal(signal.SIGTERM, d.shutdown)
    signal.signal(signal.SIGINT, d.shutdown)
    d.serve()


# -- worker (the venv's python) -------------------------------------------------------
def load_audio(path):
    """float32 samples at 16 kHz from a .raw (s16 mono) or a .wav file."""
    import numpy as np
    if path.endswith(".raw"):
        with open(path, "rb") as handle:
            data = handle.read()
        return np.frombuffer(data[:len(data) - len(data) % 2], np.int16).astype(np.float32) / 32768
    import wave
    with wave.open(path) as w:
        if w.getsampwidth() != 2:
            raise ValueError("16-bit WAV only")
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1)
        if w.getframerate() != RATE:
            n = int(len(pcm) * RATE / w.getframerate())
            pcm = np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)
        return pcm


def worker(device, model, compute):
    out = sys.stdout
    sys.stdout = sys.stderr            # library chatter goes to the journal, not the pipe
    t0 = time.time()
    try:
        from faster_whisper import WhisperModel
        kwargs = {"device": device, "compute_type": compute, "download_root": MODELS}
        if device == "cpu":
            kwargs["cpu_threads"] = min(8, os.cpu_count() or 4)
        try:
            whisper = WhisperModel(model, local_files_only=True, **kwargs)
        except Exception:                  # not downloaded yet
            whisper = WhisperModel(model, **kwargs)
    except Exception as exc:
        print(json.dumps({"error": f"could not load {model} on {device}: {exc}"}), file=out, flush=True)
        return
    try:                                   # one second of silence: the card's kernels are built now, not
        import numpy as np                 # on the first real request (0.6 s -> 0.15 s for that one)
        list(whisper.transcribe(np.zeros(RATE, np.float32), beam_size=1, language="en")[0])
    except Exception:
        pass
    print(json.dumps({"ready": True, "device": device, "model": model, "load_s": round(time.time() - t0, 2)}),
          file=out, flush=True)
    for line in sys.stdin:
        try:
            msg = json.loads(line)
            audio = load_audio(msg["path"])
            t = time.time()
            segments, info = whisper.transcribe(audio, language=msg.get("language"), task=msg.get("task", "transcribe"),
                                                beam_size=msg.get("beam", 5), vad_filter=msg.get("vad", True),
                                                condition_on_previous_text=False)
            segs = [{"text": s.text, "no_speech": s.no_speech_prob} for s in segments]
            answer = {"text": clean_text(segs), "language": info.language, "audio_s": round(len(audio) / RATE, 2),
                      "secs": round(time.time() - t, 3), "device": device, "model": model}
        except Exception as exc:
            answer = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(answer), file=out, flush=True)


# -- overlay (GTK, the captions strip) ------------------------------------------------
def overlay():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    import cairo
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    import panelui

    panelui.load_css()
    win = Gtk.Window()
    win.set_name("panel-window")
    win.set_app_paintable(True)
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_namespace(win, "waybar-captions")
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.BOTTOM, True)
    GtkLayerShell.set_margin(win, GtkLayerShell.Edge.BOTTOM, 90)
    GtkLayerShell.set_exclusive_zone(win, -1)
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    width = 900
    try:                               # the focused screen, as osd.py picks it
        mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True,
                                         timeout=2).stdout)
        focused = next(m for m in mons if m.get("focused"))
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            geo = display.get_monitor(i).get_geometry()
            if (geo.x, geo.y) == (focused["x"], focused["y"]):
                GtkLayerShell.set_monitor(win, display.get_monitor(i))
                # A fixed width, half the screen (a wrapping label alone
                # shrinks the card to one word a line).
                width = max(600, min(1400, geo.width // 2))
    except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
        pass
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    card.set_name("panel")
    win.add(card)
    text = Gtk.Label()
    text.set_line_wrap(True)
    text.set_size_request(width, -1)
    text.set_justify(Gtk.Justification.CENTER)
    text.get_style_context().add_class("ctl-title")
    card.pack_start(text, True, True, 0)
    win.connect("realize", lambda w: w.input_shape_combine_region(cairo.Region()))   # click-through
    card.show_all()

    pending = [b""]

    def on_input(fd, _cond):
        # os.read, not readline: a buffered reader can sit on a second line
        # with no new event coming to wake us for it.
        data = os.read(fd, 65536)
        if not data:
            Gtk.main_quit()
            return False
        *lines, pending[0] = (pending[0] + data).split(b"\n")
        for line in lines[-1:]:          # only the newest matters
            try:
                show(json.loads(line))
            except ValueError:
                pass
        return True

    def show(msg):
        lines = msg.get("lines") or []
        if not lines:
            win.hide()
            return
        size = int(msg.get("size", 22))
        older = "".join(f"<span alpha='65%'>{GLib.markup_escape_text(t)}</span>\n" for t in lines[:-1])
        text.set_markup(f"<span size='{size * 1024}'>{older}{GLib.markup_escape_text(lines[-1])}</span>")
        win.show()

    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, on_input)
    Gtk.main()


# -- commands -------------------------------------------------------------------------
def status_info():
    settings = read_settings()
    state = read_state()
    daemon_status = request({"cmd": "status"}, timeout=5, start=False) if state else None
    return {"daemon": bool(state), "state": state.get("state", "off"), "captions": bool(state.get("captions")),
            "worker": (daemon_status or {}).get("worker"), "installed": os.path.exists(VENV_PY),
            "cuda_libs": bool(cuda_lib_dirs()), "models": cached_models(), "gpu_free_mb": gpu_free_mb(),
            "gaming": gaming(), "settings": settings, "plan": list(plan_engine(settings, gpu_free_mb(), gaming())),
            "notes": MODEL_NOTES, "choices": {k: list(v) for k, v in CHOICES.items()}, "numbers": NUMBERS}


def selftest():
    """espeak-ng speaks a sentence into a file; it comes back as text."""
    os.makedirs(WORK_DIR, mode=0o700, exist_ok=True)
    results = []
    for lang, sentence in (("en-us", "The quick brown fox jumps over the lazy dog."),
                           ("es", "Mañana vamos a la playa con mis amigos.")):
        wav = os.path.join(WORK_DIR, f"selftest-{lang}.wav")
        subprocess.run(["espeak-ng", "-v", lang, "-s", "150", "-w", wav, sentence], check=True, timeout=60)
        t = time.time()
        answer = request({"cmd": "transcribe", "path": wav}, timeout=600)
        os.unlink(wav)
        results.append({"said": sentence, **answer, "round_trip_s": round(time.time() - t, 2)})
    return results


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    as_json = "--json" in rest
    if cmd == "daemon":
        daemon()
    elif cmd == "worker" and len(rest) == 3:
        worker(*rest)
    elif cmd == "overlay":
        overlay()
    elif cmd == "bar":
        try:
            bar()
        except (BrokenPipeError, KeyboardInterrupt):
            pass
    elif cmd == "bar-click":                 # left click on the pill
        state = read_state()
        if state.get("state") == "recording":
            request({"cmd": "stop"})
        elif state.get("captions"):
            request({"cmd": "captions", "on": False})
    elif cmd in ("toggle", "stop", "cancel", "unload"):
        answer = request({"cmd": cmd}, timeout=600)
        if answer.get("error") and answer["error"] != "gamemode":
            sys.exit(answer["error"])
    elif cmd == "ptt" and rest in (["start"], ["stop"]):
        request({"cmd": f"ptt-{rest[0]}"}, timeout=600)
    elif cmd == "command" and not rest:
        answer = request({"cmd": "command"}, timeout=600)
        if answer.get("error") and answer["error"] not in ("gamemode", "commands off"):
            sys.exit(answer["error"])
    elif cmd == "command-ptt" and rest in (["start"], ["stop"]):
        request({"cmd": f"command-ptt-{rest[0]}"}, timeout=600)
    elif cmd == "captions" and rest[:1] and rest[0] in ("on", "off", "toggle"):
        msg = {"cmd": "captions", "on": {"on": True, "off": False}.get(rest[0])}
        if "--source" in rest:                # a raw 16 kHz s16 file instead of the speakers (tests)
            msg["source"] = os.path.abspath(rest[rest.index("--source") + 1])
        answer = request(msg, timeout=600)
        if answer.get("error"):
            sys.exit(answer["error"])
    elif cmd == "transcribe" and rest:
        answer = request({"cmd": "transcribe", "path": os.path.abspath(rest[0])}, timeout=600)
        print(json.dumps(answer) if as_json else answer.get("text") or answer.get("error", ""))
    elif cmd == "selftest":
        for r in selftest():
            print(json.dumps(r, ensure_ascii=False) if as_json else
                  f"said:  {r['said']}\nheard: {r.get('text') or r.get('error')}\n"
                  f"       {r.get('language', '?')}, {r.get('audio_s', 0)} s of sound in {r.get('secs', 0)} s "
                  f"({r.get('model', '?')} on {r.get('device', '?')}; {r['round_trip_s']} s round trip)")
    elif cmd == "status":
        info = status_info()
        if as_json:
            print(json.dumps(info))
        else:
            w = info["worker"]
            print(f"daemon: {'running, ' + info['state'] if info['daemon'] else 'not running'}"
                  f"{', captions on' if info['captions'] else ''}")
            print(f"engine: {w['model'] + ' on ' + w['device'] if w else 'not loaded'}")
            print(f"installed: {info['installed']}  CUDA libraries: {info['cuda_libs']}  "
                  f"downloaded: {', '.join(info['models']) or 'none'}")
            print(f"card free: {info['gpu_free_mb']} MB  gamemode: {info['gaming']}")
            print(f"next load: {info['plan'][1]} on {info['plan'][0]} ({info['plan'][3]})")
    elif cmd == "get":
        settings = read_settings()
        print(json.dumps(settings) if as_json else "\n".join(f"{k}={v}" for k, v in settings.items()))
    elif cmd == "set" and len(rest) == 2:
        try:
            write_setting(*rest)
        except ValueError as exc:
            sys.exit(str(exc))
        request({"cmd": "reload"}, timeout=5, start=False)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
