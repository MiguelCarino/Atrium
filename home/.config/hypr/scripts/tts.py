#!/usr/bin/env python3
"""Spoken replies: local text-to-speech (Piper), in Spanish and English.

    tts.py speak "TEXT" [--lang auto|es|en] [--feature brief|commands|selection] [--to FILE.wav] [--json]
                            say it (queued behind what is being said), or
                            with --to only write it to a WAV file: nothing
                            is played, no switch is asked (the tests, a
                            preview). --feature: whose words these are --
                            that feature's switch must be on (below)
    tts.py stop             stop talking now and forget what was queued
    tts.py selection        the text you highlighted (the primary selection,
                            read once, on the key press) said aloud; while it
                            is talking, the same key stops it. Not from a
                            private window (voice-command.py's is_private:
                            password managers, private browsing, Settings >
                            Privacy's private apps)
    tts.py test [--lang es|en] [TEXT] [--no-play] [--json]
                            Settings > Speech's Test button: a sample sentence
                            made into a file (timed: the real-time factor),
                            then played -- the one way to hear it whatever the
                            switches say, because a person clicked it.
                            --no-play: made and timed only
    tts.py bench [--json]   both voices, a long sentence each, made into tmpfs
                            files and timed; nothing played
    tts.py status [--json]  settings, voices, the engine, whether it may speak
                            now (and why not), what it is saying
    tts.py voices [--json]  installed voices per language, and the ones that
                            Settings offers to download
    tts.py download NAME    one voice from rhasspy/piper-voices (Hugging Face)
                            into VOICES -- the only thing that touches the
                            network, and only when asked
    tts.py set KEY VALUE    a setting (SETTINGS below)

FOR THE OTHER SCRIPTS -- import this file and call speak(text, lang=...,
feature=...): it checks, tidies the text and queues it, starts the speaker
when none is running and returns at once (True: queued; False: not, and
`last_reason` says why). Callers so far:
    brief.py         the morning brief read aloud (feature "brief")
    voice-command.py what a voice command did, said back (feature "commands")
    assistant.py     its speak() hook, when its own voice_reply is on (no
                     feature: that switch is assistant.py's)

WHEN IT STAYS SILENT (blocked(); a click on Test skips all but the engine):
    the master switch is off; the feature's switch is off (all OFF as
    shipped, but the selection key, which only reads when pressed: nothing
    talks until you say so); gamemode is on (lua/gamemode.lua's
    own test, through llm_models.py); and with quiet=on, Do Not Disturb
    (mako's mode) or the quiet hours (notify-settings.py's). Silent is not
    lost: every caller also shows its words as a notification. The drain asks
    again before each line, so a game or DND begun after a line was queued
    still silences it.

THE QUEUE, so lines never talk over each other: speak() writes one small
JSON file per line into $XDG_RUNTIME_DIR/tts/queue (tmpfs, 0700/0600, at
most MAX_QUEUE; the oldest go first when full) and starts `tts.py _drain` as
a transient user unit (systemd-run, SyslogIdentifier=tts, so it outlives a
caller that is itself a transient unit). One drain at a time (flock); it
loads the voices once, says every queued line in order and exits when the
queue is empty -- it lets go of the lock and looks once more before it
leaves, so a line queued in that instant is never stranded. The drain runs
under the venv's Python (Piper lives there); this file imports nothing from
it until it has to, so any script can import it with the system Python.

SPEAKING: Piper synthesises a sentence at a time (PiperVoice.synthesize) and
the samples go straight into one `pw-play --raw` per drain, so the first
sentence plays while the next one is made (~0.1-0.2 of real time on this
CPU: `tts.py bench`). Rate is Piper's length_scale (100/rate), volume
pw-play's stream volume. The text is tidied for the ear first (clean()):
code blocks dropped, markdown and markup stripped, a URL becomes "a link",
lines without a full stop get one (a pause), and it is cut at a sentence
end after max_chars. The language: the caller's, else the setting, else
guessed from the words (guess_lang(): ñ, ¿, ¡, accents and common short
words -- cheap, no model).

MEDIA while it speaks (duck=): "lower" turns every other playback stream
(pactl sink-inputs) down to duck_level % of itself and back after; "pause"
pauses the MPRIS players that were playing (playerctl) and resumes only
those; "off" leaves them. What was changed is written to
$XDG_RUNTIME_DIR/tts/ducked.json first, so a drain that dies still has its
changes undone by the next one or by `stop`.

PRIVACY: everything is local -- Piper on the CPU, no cloud voice, ever. The
text lives only in the tmpfs queue until it is said; the journal gets
lengths, languages and timings, never the words.

VOICES: VOICES/<name>.onnx (+ .onnx.json), names as in rhasspy/piper-voices
("es_MX-ald-medium", "en_US-lessac-medium" installed). Shipped choice:
es_MX-ald-medium and en_US-lessac-medium; CURATED are offered for download.

SETTINGS ($XDG_STATE_HOME/hypr/tts.conf, key=value; Settings > Speech):
    enabled         on | off (on)   the master switch
    voice_es, voice_en   an installed voice of that language
    language        auto | es | en  (auto) when a caller does not say
    rate            50..200 %  (100)    speed
    volume          10..100 %  (80)
    duck            off | lower | pause  (lower)
    duck_level      0..80 %   (25)  other sound while it speaks (lower)
    quiet           on | off (on)   silent in Do Not Disturb and quiet hours
    max_chars       100..3000 (800) longer text is cut at a sentence end
    speak_brief     on | off (off)  the morning brief, read aloud
    speak_commands  on | off (off)  voice commands answer by voice
    speak_selection on | off (on)   the "read the selection" key works (it
                                    reads only when pressed)
(The assistant's spoken answers are assistant.py's own voice_reply.)
"""
import datetime as dt
import fcntl
import html
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
THIS = os.path.abspath(__file__)
HOME_DIR = os.path.expanduser("~/.local/share/tts")
VENV_PY = os.path.join(HOME_DIR, "venv", "bin", "python")
VOICES = os.path.join(HOME_DIR, "voices")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
CONF = os.path.join(STATE_DIR, "tts.conf")
RUN_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "tts")
QUEUE = os.path.join(RUN_DIR, "queue")
LOCK = os.path.join(RUN_DIR, "drain.lock")
PIDFILE = os.path.join(RUN_DIR, "drain.pid")
DUCKED = os.path.join(RUN_DIR, "ducked.json")
LAST = os.path.join(RUN_DIR, "last.json")       # the last line's timings (no text)

APP_NAME = "Speech"                             # our pw-play stream: never ducked
MAX_QUEUE = 20
GAP_S = 0.25                                    # silence between two lines
ON_OFF = ("on", "off")
DEFAULTS = {"enabled": "on", "voice_es": "es_MX-ald-medium", "voice_en": "en_US-lessac-medium",
            "language": "auto", "rate": "100", "volume": "80", "duck": "lower", "duck_level": "25",
            "quiet": "on", "max_chars": "800", "speak_brief": "off", "speak_commands": "off",
            "speak_selection": "on"}
CHOICES = {"enabled": ON_OFF, "quiet": ON_OFF, "speak_brief": ON_OFF, "speak_commands": ON_OFF,
           "speak_selection": ON_OFF,
           "language": ("auto", "es", "en"), "duck": ("off", "lower", "pause")}
RANGES = {"rate": (50, 200), "volume": (10, 100), "duck_level": (0, 80), "max_chars": (100, 3000)}
FEATURES = {"brief": "speak_brief", "commands": "speak_commands", "selection": "speak_selection"}     # feature -> its switch
LANGS = ("es", "en")
VOICE_NAME = re.compile(r"(?P<lang>[a-z]{2})_[A-Z]{2}-[A-Za-z0-9_]+-(x_low|low|medium|high)")
CURATED = {     # offered for download in Settings (all in rhasspy/piper-voices)
    "es": ["es_MX-ald-medium", "es_MX-claude-high", "es_ES-davefx-medium", "es_ES-sharvard-medium",
           "es_AR-daniela-high"],
    "en": ["en_US-lessac-medium", "en_US-ryan-medium", "en_US-amy-medium", "en_GB-alba-medium",
           "en_GB-northern_english_male-medium"],
}
SAMPLES = {"es": "Hola. Así suena el escritorio cuando te habla: tranquilo, claro y sin prisa.",
           "en": "Hello. This is how the desktop sounds when it talks to you: calm, clear and unhurried."}
BENCH = {"es": "Buenos días. Ayer trabajaste tres horas en Atlas y dejaste dos repositorios con cambios "
               "sin guardar. Hoy tienes una reunión a las diez y el clima será soleado por la tarde.",
         "en": "Good morning. Yesterday you spent three hours on Atlas and left two repositories with "
               "uncommitted work. There is a meeting at ten today, and the afternoon will be sunny."}
LINK_WORD = {"es": "un enlace", "en": "a link"}
ES_WORDS = {"el", "la", "los", "las", "de", "del", "que", "y", "en", "un", "una", "por", "para", "con",
            "es", "está", "no", "se", "lo", "su", "al", "como", "pero", "más", "hoy", "ayer", "hay",
            "tienes", "esto", "este", "esta", "muy", "también", "ya", "sí", "bien", "hola", "buenos"}
EN_WORDS = {"the", "and", "of", "to", "in", "is", "it", "you", "that", "for", "on", "with", "was",
            "are", "this", "be", "at", "have", "not", "your", "from", "there", "today", "yesterday",
            "what", "will", "can", "done", "hello", "good", "has"}

last_reason = ""            # why the last speak() did not queue anything


def log(text):
    print(f"tts: {text}", file=sys.stderr, flush=True)


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[name]
            raise
    return mod


def run(*cmd, timeout=5):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# -- settings ---------------------------------------------------------------------------
def settings(path=None):
    conf = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep and key.strip() in DEFAULTS:
                    try:
                        conf[key.strip()] = check_setting(key.strip(), value, installed=None)
                    except ValueError:
                        pass                # a bad line: the default
    except OSError:
        pass
    return conf


def check_setting(key, value, installed=True):
    """The value tidied, or ValueError saying why not. installed=None skips
    the "is that voice on disk" check (reading the file back)."""
    value = str(value).strip().removesuffix("%").strip()
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r} ({', '.join(DEFAULTS)})")
    if key in CHOICES:
        if value not in CHOICES[key]:
            raise ValueError(f"{key} is {' | '.join(CHOICES[key])}")
        return value
    if key in RANGES:
        lo, hi = RANGES[key]
        try:
            number = int(float(value))
        except ValueError:
            raise ValueError(f"{key} is a number, {lo}..{hi}") from None
        if not lo <= number <= hi:
            raise ValueError(f"{key} is {lo}..{hi}")
        return str(number)
    lang = key.removeprefix("voice_")           # voice_es / voice_en
    m = VOICE_NAME.fullmatch(value)
    if not m or m["lang"] != lang:
        raise ValueError(f"{key} is a {lang}_XX-name-quality voice name")
    if installed and not os.path.exists(voice_path(value)):
        raise ValueError(f"voice {value} is not installed (tts.py download {value})")
    return value


def set_setting(key, value, path=None):
    value = check_setting(key, value)
    conf = settings(path)
    conf[key] = value
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("# Spoken replies (tts.py; Settings > Speech)\n")
        handle.writelines(f"{k}={conf[k]}\n" for k in DEFAULTS)
    os.replace(tmp, path)
    return value


# -- voices -----------------------------------------------------------------------------------
def voice_path(name, folder=None):
    return os.path.join(folder or VOICES, f"{name}.onnx")


def installed_voices(folder=None):
    """{"es": [names], "en": [names]}: the .onnx files with their .json next to them."""
    out = {lang: [] for lang in LANGS}
    try:
        names = sorted(os.listdir(folder or VOICES))
    except OSError:
        names = []
    for f in names:
        m = VOICE_NAME.fullmatch(f.removesuffix(".onnx"))
        if f.endswith(".onnx") and m and m["lang"] in out and f + ".json" in names:
            out[m["lang"]].append(f.removesuffix(".onnx"))
    return out


def voice_for(lang, conf=None, folder=None):
    """The voice name to use for `lang`: the setting when installed, else the
    first installed of that language, else None."""
    conf = conf or settings()
    have = installed_voices(folder)[lang]
    want = conf.get(f"voice_{lang}")
    return want if want in have else (have[0] if have else None)


def engine_ready():
    return os.access(VENV_PY, os.X_OK) and any(installed_voices().values())


# -- the words ------------------------------------------------------------------------------------
def guess_lang(text, default="en"):
    """"es" or "en" from the words alone: ñ ¿ ¡ say Spanish outright; else
    common short words and accented letters are counted."""
    low = str(text).lower()
    if re.search(r"[ñ¿¡]", low):
        return "es"
    words = re.findall(r"[a-záéíóúü]+", low)
    es = sum(w in ES_WORDS for w in words) + 2 * sum(bool(re.search(r"[áéíóú]", w)) for w in words)
    en = sum(w in EN_WORDS for w in words)
    if es == en:
        return default if default in LANGS else "en"
    return "es" if es > en else "en"


def pick_lang(text, lang=None, conf=None):
    conf = conf or settings()
    if lang in LANGS:
        return lang
    if conf["language"] in LANGS:
        return conf["language"]
    return guess_lang(text)


def clean(text, lang="en", limit=800):
    """Text tidied for the ear (the docstring's SPEAKING)."""
    text = html.unescape(str(text or ""))
    text = re.sub(r"```.*?(```|$)", " ", text, flags=re.S)         # code blocks are not read out
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)        # [words](url): the words
    text = re.sub(r"https?://\S+", LINK_WORD.get(lang, "a link"), text)
    text = re.sub(r"<[^>]+>", " ", text)                             # pango / html markup
    text = re.sub(r"[*_#>|~=]{1,}|^\s*[-•✗✓]\s+", " ", text, flags=re.M)
    lines = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            lines.append(line if line[-1] in ".!?:;…," else line + ".")
    text = " ".join(lines)
    if not re.search(r"\w", text):
        return ""               # "…", "?", "---": Piper makes no sound of it, so nothing to say
    if len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "…"
    return text.strip()


# -- may it speak now? -------------------------------------------------------------------------------
def gamemode_on():
    try:
        return bool(_module("llm_models", "llm_models.py")._gamemode_on())
    except Exception:       # noqa: BLE001 -- unknown: not in a game
        return False


def dnd_on():
    return "do-not-disturb" in (run("makoctl", "mode", timeout=2) or "").split()


def quiet_hours(now=None):
    try:
        ns = _module("notify_settings", "notify-settings.py")
        return bool(ns.quiet_now(ns.load(), now or dt.datetime.now()))
    except Exception:       # noqa: BLE001
        return False


def blocked(feature=None, conf=None, now=None):
    """Why it must stay silent now ("" = it may speak). Cheapest checks
    first: a switched-off feature never runs hyprctl or makoctl."""
    conf = conf or settings()
    if feature != "test":
        if conf["enabled"] != "on":
            return "speech is off (Settings > Speech)"
        key = FEATURES.get(feature)
        if key and conf[key] != "on":
            return f"spoken {feature} is off (Settings > Speech)"
        if gamemode_on():
            return "gamemode is on"
        if conf["quiet"] == "on":
            if dnd_on():
                return "Do Not Disturb is on"
            if quiet_hours(now):
                return "quiet hours"
    if not engine_ready():
        return "Piper is not installed (~/.local/share/tts)"
    return ""


# -- the queue -----------------------------------------------------------------------------------------
def _private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)


def enqueue(item):
    """One line into the queue (oldest dropped past MAX_QUEUE). The file's path."""
    _private_dir(QUEUE)
    path = os.path.join(QUEUE, f"{time.time_ns()}-{os.getpid()}.json")
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(item, handle, ensure_ascii=False)
    os.replace(tmp, path)
    for old in queued()[:-MAX_QUEUE]:
        _discard(old)
    return path


def _discard(path):
    """A queued line dropped unsaid -- with the Test button's tmpfs WAV, if it has one."""
    try:
        with open(path, encoding="utf-8") as handle:
            item = json.load(handle)
        wav = item.get("wav") if isinstance(item, dict) else None
        if wav and os.path.dirname(os.path.abspath(wav)) == os.path.abspath(RUN_DIR):
            _unlink(wav)
    except (OSError, ValueError):
        pass
    _unlink(path)


def queued():
    try:
        return sorted(os.path.join(QUEUE, f) for f in os.listdir(QUEUE) if f.endswith(".json"))
    except OSError:
        return []


def take():
    """The oldest queued line (read and deleted), or None."""
    for path in queued():
        try:
            with open(path, encoding="utf-8") as handle:
                item = json.load(handle)
        except (OSError, ValueError):
            item = None
        _unlink(path)
        if isinstance(item, dict):
            return item
    return None


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def drain_argv():
    """The speaker as a transient unit (outlives the caller's own unit)."""
    env = [f"--setenv={k}={os.environ[k]}" for k in ("XDG_RUNTIME_DIR", "XDG_STATE_HOME") if os.environ.get(k)]
    if shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--quiet", "--collect", "-p", "SyslogIdentifier=tts", *env, "--",
                VENV_PY, THIS, "_drain"]
    return [VENV_PY, THIS, "_drain"]


def start_drain():
    try:
        subprocess.Popen(drain_argv(), start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError as err:
        log(f"could not start the speaker: {err}")
        return False


def speak(text, lang="auto", feature=None, force=False, conf=None):
    """THE call point for other scripts (the docstring's FOR THE OTHER
    SCRIPTS). True: queued and the speaker is on it."""
    global last_reason
    conf = conf or settings()
    last_reason = blocked("test" if force else feature, conf)
    if last_reason:
        log(f"not spoken ({feature or 'speech'}): {last_reason}")
        return False
    lang = pick_lang(text, lang, conf)
    text = clean(text, lang, int(conf["max_chars"]))
    if not text:
        last_reason = "nothing to say"
        return False
    enqueue({"text": text, "lang": lang, "feature": feature or ""})
    return start_drain()


def speaking_pid():
    """The drain's pid while one runs (checked against /proc), or None."""
    try:
        with open(PIDFILE) as handle:
            pid = int(handle.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            argv = handle.read().split(b"\0")
        if b"_drain" in argv and any(a.endswith(b"tts.py") for a in argv):     # not a reused pid
            return pid
    except (OSError, ValueError):
        pass
    return None


def stop():
    """Quiet now: the queue emptied, the drain told to stop (it puts the
    media back), leftovers of a dead one undone."""
    for path in queued():
        _discard(path)
    pid = speaking_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pid = None
    if not pid:
        restore_duck()
    return bool(pid)


# -- other sound while it speaks ------------------------------------------------------------------------------
def sink_inputs():
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True,
                             timeout=5).stdout
        data = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return data if isinstance(data, list) else []


def playing_players():
    names = (run("playerctl", "-l") or "").split()
    return [p for p in names if (run("playerctl", "-p", p, "status") or "").strip() == "Playing"]


def duck_plan(conf, inputs, players):
    """What duck() would change -- pure, for the tests. {"how": ..., ...}."""
    how = conf["duck"]
    if how == "pause":
        return {"how": "pause", "players": list(players)}
    if how == "lower":
        level = int(conf["duck_level"]) / 100
        change = {}
        for s in inputs:
            props = s.get("properties") or {}
            if props.get("application.name") == APP_NAME or s.get("corked"):
                continue
            was = [int(v.get("value", 0)) for v in (s.get("volume") or {}).values()]
            if was:
                change[str(s["index"])] = {"was": was, "now": [int(v * level) for v in was]}
        return {"how": "lower", "inputs": change}
    return {"how": "off"}


def duck(conf):
    plan = duck_plan(conf, sink_inputs() if conf["duck"] == "lower" else [],
                     playing_players() if conf["duck"] == "pause" else [])
    if plan["how"] == "off" or not (plan.get("players") or plan.get("inputs")):
        return plan
    _private_dir(RUN_DIR)
    with open(DUCKED, "w") as handle:      # first: a drain that dies is undone by the next
        json.dump(plan, handle)
    for p in plan.get("players", []):
        run("playerctl", "-p", p, "pause")
    for idx, v in plan.get("inputs", {}).items():
        run("pactl", "set-sink-input-volume", idx, *map(str, v["now"]))
    return plan


def restore_duck():
    try:
        with open(DUCKED) as handle:
            plan = json.load(handle)
    except (OSError, ValueError):
        return False
    _unlink(DUCKED)
    for p in plan.get("players", []):
        run("playerctl", "-p", p, "play")
    for idx, v in plan.get("inputs", {}).items():
        run("pactl", "set-sink-input-volume", idx, *map(str, v["was"]))     # a stream that ended: fails, fine
    return True


# -- making sound (the venv's Python only) -----------------------------------------------------------------
def syn_config(conf):
    from piper import SynthesisConfig   # noqa: PLC0415 -- the venv only
    return SynthesisConfig(length_scale=round(100 / int(conf["rate"]), 3))


def load_voice(name):
    from piper import PiperVoice        # noqa: PLC0415
    return PiperVoice.load(voice_path(name))


def player_argv(rate, conf):
    return ["pw-play", "--raw", "--rate", str(rate), "--channels", "1", "--format", "s16",
            "--volume", f"{int(conf['volume']) / 100:.2f}", "--media-role", "Notification",
            "-P", f'{{ application.name = "{APP_NAME}" media.name = "Spoken reply" }}', "-"]


def render(text, lang, out, conf=None, voice=None):
    """`text` into the WAV file `out`, timed -- nothing is played. Returns
    {"voice", "chars", "audio_s", "synth_s", "rtf"}."""
    conf = conf or settings()
    name = voice_for(lang, conf)
    if not name:
        raise RuntimeError(f"no {lang} voice installed")
    t0 = time.monotonic()
    voice = voice or load_voice(name)
    load_s = time.monotonic() - t0
    t1 = time.monotonic()
    with wave.open(out, "wb") as wav:
        voice.synthesize_wav(text, wav, syn_config=syn_config(conf))
    synth_s = time.monotonic() - t1
    with wave.open(out, "rb") as wav:
        audio_s = wav.getnframes() / wav.getframerate()
    return {"voice": name, "lang": lang, "chars": len(text), "audio_s": round(audio_s, 2),
            "load_s": round(load_s, 2), "synth_s": round(synth_s, 2),
            "rtf": round(synth_s / audio_s, 3) if audio_s else None}


class Speaker:
    """The drain's voice: voices loaded once, one pw-play fed raw samples."""

    def __init__(self, conf):
        self.conf = conf
        self.voices = {}
        self.player = None
        self.rate = None
        self.stopped = False
        self.ducked = False

    def stop(self, *_):
        self.stopped = True
        if self.player:
            try:
                self.player.kill()
            except OSError:
                pass

    def open_player(self, rate):
        if self.player and self.rate == rate and self.player.poll() is None:
            return
        self.close_player()
        self.player = subprocess.Popen(player_argv(rate, self.conf), stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.rate = rate

    def close_player(self):
        """Wait for what was written to be heard, then let pw-play go."""
        if self.player:
            try:
                self.player.stdin.close()
                self.player.wait(timeout=600)
            except (OSError, subprocess.SubprocessError, ValueError):
                self.player.kill()
            self.player = None

    def write(self, data):
        self.player.stdin.write(data)

    def say(self, item):
        if not self.ducked:
            duck(self.conf)
            self.ducked = True
        lang = item.get("lang") if item.get("lang") in LANGS else "en"
        t0, audio_s = time.monotonic(), 0.0
        try:
            if item.get("wav"):
                with wave.open(item["wav"], "rb") as wav:
                    self.open_player(wav.getframerate())
                    data = wav.readframes(wav.getnframes())
                    audio_s = wav.getnframes() / wav.getframerate()
                self.write(data)
                _unlink(item["wav"])
                name = item.get("voice", "?")
            else:
                name = voice_for(lang, self.conf)
                if not name:
                    log(f"no {lang} voice installed")
                    return
                if name not in self.voices:
                    self.voices[name] = load_voice(name)
                for chunk in self.voices[name].synthesize(item.get("text", ""), syn_config(self.conf)):
                    if self.stopped:
                        return
                    self.open_player(chunk.sample_rate)
                    self.write(chunk.audio_int16_bytes)
                    audio_s += len(chunk.audio_int16_bytes) / 2 / chunk.sample_rate
            if self.player and self.rate:   # no chunk at all (nothing sayable): no player to pause
                self.write(b"\0\0" * int(self.rate * GAP_S))
        except Exception as err:    # noqa: BLE001 -- a broken pipe, a bad voice file: this line only
            if not self.stopped:
                log(f"playback failed: {type(err).__name__}")
            return
        made = time.monotonic() - t0
        log(f"said {len(item.get('text', ''))} chars ({lang}, {name}, {item.get('feature') or 'speech'}): "
            f"{audio_s:.1f} s of speech")
        try:
            with open(LAST, "w") as handle:
                json.dump({"at": time.time(), "lang": lang, "voice": name, "audio_s": round(audio_s, 2),
                           "feature": item.get("feature") or ""}, handle)
        except OSError:
            pass
        return made

    def finish(self):
        self.close_player()
        if self.ducked:
            restore_duck()
            self.ducked = False


def _try_lock(handle):
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def drain():
    """Say every queued line, one drain at a time (the docstring's THE QUEUE)."""
    _private_dir(RUN_DIR)
    handle = open(LOCK, "w")    # noqa: SIM115 -- held for the whole run
    if not _try_lock(handle):
        return "another drain is speaking"
    restore_duck()                  # a dead drain's leftovers
    with open(PIDFILE, "w") as pf:
        pf.write(str(os.getpid()))
    speaker = Speaker(settings())
    signal.signal(signal.SIGTERM, speaker.stop)
    signal.signal(signal.SIGINT, speaker.stop)
    held = True                     # the lock: only its holder may touch ducked.json
    try:
        while True:
            while not speaker.stopped:
                item = take()
                if item is None:
                    break
                why = blocked(item.get("feature") or None)    # a game or DND begun since it was queued
                if why:
                    log(f"not spoken ({item.get('feature') or 'speech'}): {why}")
                    if item.get("wav"):
                        _unlink(item["wav"])
                    continue
                speaker.say(item)
            speaker.finish()
            fcntl.flock(handle, fcntl.LOCK_UN)
            held = False
            if speaker.stopped or not queued() or not _try_lock(handle):
                break               # (a new drain that took the lock in between says the rest)
            held = True
    finally:
        if speaker.player:          # an error mid-line: no pw-play left behind
            speaker.player.kill()
        if held:                    # else another drain may have ducked: its to undo
            restore_duck()
        if speaking_pid() == os.getpid():
            _unlink(PIDFILE)
        if speaker.stopped:
            for path in queued():
                _discard(path)
        handle.close()
    return "stopped" if speaker.stopped else "done"


def read_selection():
    """speak_selection's text: the primary selection, or ("", why not)."""
    try:
        vc = _module("voice_command", "voice-command.py")
        client = vc.hypr_json("activewindow") or {}
        if vc.is_private(client, vc.private_classes()):
            return "", "a private window"
    except Exception:       # noqa: BLE001 -- cannot tell: do not read it
        return "", "the focused window could not be checked"
    text = run("wl-paste", "--primary", "--no-newline", "--type", "text/plain", timeout=3) or ""
    return text.strip(), "" if text.strip() else "nothing is selected"


def speak_selection():
    """The key: read the highlighted text, or stop when already talking."""
    if speaking_pid():
        stop()
        return "stopped"
    text, why = read_selection()
    if text and speak(text, "auto", "selection"):
        return f"reading {len(text)} characters"
    why = why or last_reason
    run(NOTIFY, "-a", APP_NAME, "-i", "audio-speakers", "-t", "3000", "Not read aloud", why)
    return f"not read: {why}"


# -- status, for Settings ------------------------------------------------------------------------------
def last_said():
    try:
        with open(LAST) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def status():
    conf = settings()
    return {"settings": conf, "voices": installed_voices(), "curated": CURATED,
            "installed": os.access(VENV_PY, os.X_OK), "ready": engine_ready(),
            "blocked": blocked(None, conf), "speaking": speaking_pid() is not None,
            "queued": len(queued()), "last": last_said(), "ranges": RANGES, "choices": CHOICES}


# -- the command line -----------------------------------------------------------------------------------------
def in_venv(argv):
    """Piper is in the venv: run this same command there instead."""
    try:
        import piper  # noqa: F401,PLC0415
        return
    except ImportError:
        pass
    if not os.access(VENV_PY, os.X_OK):
        sys.exit("tts: Piper is not installed (python3 -m venv ~/.local/share/tts/venv && "
                 "~/.local/share/tts/venv/bin/pip install piper-tts)")
    os.execv(VENV_PY, [VENV_PY, THIS, *argv])


def option(rest, flag):
    if flag in rest:
        i = rest.index(flag)
        if i + 1 < len(rest):
            value = rest[i + 1]
            del rest[i:i + 2]
            return value
    return None


def tmp_wav(tag):
    _private_dir(RUN_DIR)
    return os.path.join(RUN_DIR, f"{tag}-{time.time_ns()}.wav")


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], list(argv[1:])
    as_json = "--json" in rest
    no_play = "--no-play" in rest
    rest = [r for r in rest if r not in ("--json", "--no-play")]
    lang = option(rest, "--lang")
    if lang not in (None, "auto", *LANGS):
        sys.exit("tts: --lang is auto, es or en")
    if cmd in ("speak", "say") and rest:
        out = option(rest, "--to")
        feature = option(rest, "--feature")
        text = " ".join(rest)
        if out:                             # only a file: nothing is played, no switch asked
            in_venv(argv)
            conf = settings()
            lang = pick_lang(text, lang, conf)
            result = render(clean(text, lang, int(conf["max_chars"])), lang, out, conf)
            print(json.dumps(result) if as_json else f"{out}: {result['audio_s']} s of speech in "
                  f"{result['synth_s']} s (real-time factor {result['rtf']})")
            return
        ok = speak(text, lang or "auto", feature)
        if as_json:
            print(json.dumps({"queued": ok, "reason": last_reason}))
        elif not ok:
            sys.exit(f"tts: not spoken: {last_reason}")
    elif cmd == "stop":
        print("stopped" if stop() else "nothing was being said")
    elif cmd == "selection":
        print(speak_selection())
    elif cmd == "test":
        in_venv(argv)
        conf = settings()
        lang = lang if lang in LANGS else pick_lang(" ".join(rest) or SAMPLES["es"], None, conf)
        text = clean(" ".join(rest) or SAMPLES[lang], lang, int(conf["max_chars"]))
        why = blocked("test", conf)
        if why:
            result = {"error": why}
        else:
            out = tmp_wav("test")
            result = render(text, lang, out, conf)
            if no_play:
                _unlink(out)
            else:                           # played by the drain, in turn, like any line
                enqueue({"wav": out, "lang": lang, "voice": result["voice"], "feature": "test"})
                result["played"] = start_drain()
        print(json.dumps(result) if as_json else json.dumps(result, indent=1))
    elif cmd == "bench":
        in_venv(argv)
        conf = settings()
        results = []
        for code in LANGS:
            out = tmp_wav("bench")
            try:
                results.append(render(BENCH[code], code, out, conf))
            except Exception as err:        # noqa: BLE001 -- one voice missing: say so, go on
                results.append({"lang": code, "error": str(err)})
            finally:
                _unlink(out)
        if as_json:
            print(json.dumps(results))
        else:
            for r in results:
                print(f"{r['lang']}: " + (r["error"] if "error" in r else
                      f"{r['voice']}: {r['audio_s']} s of speech made in {r['synth_s']} s "
                      f"(real-time factor {r['rtf']}; voice loaded in {r['load_s']} s)"))
    elif cmd == "_drain":
        in_venv(argv)
        log(drain())
    elif cmd == "status":
        data = status()
        if as_json:
            print(json.dumps(data, ensure_ascii=False))
        else:
            s = data["settings"]
            print(f"speech {s['enabled']}; {'ready' if data['ready'] else 'not installed'}; "
                  f"{'speaking' if data['speaking'] else 'quiet'}; queued {data['queued']}")
            print(f"voices: es {s['voice_es']}, en {s['voice_en']}; rate {s['rate']} %, volume {s['volume']} %, "
                  f"duck {s['duck']}")
            print(f"brief {s['speak_brief']}, commands {s['speak_commands']}; now: "
                  f"{data['blocked'] or 'may speak'}")
    elif cmd == "voices":
        data = {"installed": installed_voices(), "curated": CURATED}
        if as_json:
            print(json.dumps(data))
        else:
            for code in LANGS:
                print(f"{code}: " + ", ".join(data["installed"][code]) + "   (more: " +
                      ", ".join(v for v in CURATED[code] if v not in data["installed"][code]) + ")")
    elif cmd == "download" and len(rest) == 1:
        name = rest[0]
        if not VOICE_NAME.fullmatch(name) or VOICE_NAME.fullmatch(name)["lang"] not in LANGS:
            sys.exit("tts: a voice name like es_MX-ald-medium (Spanish or English)")
        in_venv(argv)
        os.makedirs(VOICES, exist_ok=True)
        done = subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", VOICES, name],
                              capture_output=True, text=True, timeout=900)
        if name not in installed_voices()[VOICE_NAME.fullmatch(name)["lang"]]:
            sys.exit(f"tts: {name} did not download: {(done.stderr or '').strip()[-200:]}")
        print(f"downloaded {name}")
    elif cmd == "set" and len(rest) == 2:
        try:
            print(set_setting(rest[0], rest[1]))
        except ValueError as err:
            sys.exit(f"tts: {err}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
