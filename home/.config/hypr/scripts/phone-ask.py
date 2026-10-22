#!/usr/bin/env python3
"""Ask your desktop from the phone (KDE Connect): a question goes from the
paired phone to the desktop assistant (assistant.py, the LOCAL model), and
the answer comes back to the phone as a notification. Off as shipped.

    phone-ask.py on|off          the switch (privacy.conf phone_ask): on also
                                 puts the quick questions on the phone and
                                 starts the listener; off takes both away
    phone-ask.py preset NAME [--device ID]
                                 one quick question (what the phone's "Run
                                 command" entries run; PRESETS below)
    phone-ask.py ask [--device ID] [--source text|cli] [--dry-run] TEXT|-
                                 one question as if from the phone (- : read
                                 it from stdin; the listener does that).
                                 --dry-run: the answer printed, nothing sent
    phone-ask.py watch           the listener for shared text (phone-ask.service)
    phone-ask.py install | uninstall
                                 the quick questions into / out of KDE
                                 Connect's run-command list for the phone(s)
    phone-ask.py status [--json] for Settings > Devices
    phone-ask.py set KEY VALUE   one setting (SETTINGS below)
    phone-ask.py screen on|off   may a description of the screen go to the
                                 phone (privacy.conf phone_ask_screen; off)

HOW THE PHONE ASKS -- two ways, both only from a PAIRED device:

  quick questions   KDE Connect's "Run command" plugin. `install` writes them
                    into ~/.config/kdeconnect/<device>/kdeconnect_runcommand/
                    config (the same file KDE Connect's own settings write; a
                    command someone added there by hand is kept). On the
                    phone: KDE Connect > this computer > Run command, tap one.
                    kdeconnectd runs `phone-ask.py preset NAME --device ID`
                    (fixed words, nothing from the phone goes on that command
                    line) only for a paired device, and each entry is written
                    into that device's own folder.
  any question      share text from the phone that starts with the prefix
                    ("?" as shipped): select text or type it in any app >
                    Share > KDE Connect > this computer, e.g.
                    "? did the backup finish" / "? ¿qué hay en mi pantalla?".
                    KDE Connect has no "message the desktop" packet: a shared
                    text is put on the clipboard by kdeconnectd, which posts
                    its "Shared text from <phone> copied to clipboard"
                    notification (event textShareReceived). The listener
                    (`watch`) watches the session bus for that Notify call
                    (busctl monitor, matched to Notify only) and believes it
                    only when the caller is kdeconnectd's own process (its
                    PID owns org.kde.kdeconnect) and the event id says
                    textShareReceived -- the phone's MIRRORED notifications
                    (an SMS that reads "? lock") are a different event and
                    never count. The phone's name in the title must be a
                    paired device. Text without the prefix is an ordinary
                    share and left alone; a question taken is cleared off the
                    clipboard (when it is still there). A few words go
                    straight to a quick question: "? lock", "? pausa",
                    "? brief", "? pantalla"... (ALIASES).

THE ANSWER goes back with kdeconnect-cli: `--ping-msg` (a notification on
the phone; reply=ping, as shipped), `--share-text` (onto the phone's
clipboard, with KDE Connect's own note; reply=text) or both. At most
REPLY_MAX characters. A screenshot only ever goes with screenshots=on, and
then only the "what's on my screen" quick question sends one -- after
screen-ask.py's private-window check (a password manager or a private
browsing window on screen: no picture).

WHAT IT MAY DO (security):
  - only a paired device that is reachable now; `device` narrows it to one
  - the assistant gets the phone's question with confirm=all: every action
    it wants comes back PENDING, nothing runs on its own. Pending actions
    whose names are all in the allow-list (`allow`; as shipped media,
    volume, Do Not Disturb, timers, reminders, alarms) are then done; any
    other one -- closing windows, sessions, links, apps, the theme... -- is
    cancelled and the phone is told it needs the desktop. Nothing destructive
    runs from the phone unless you put its name in the allow-list.
  - the screen: the assistant's look_at_screen tool is switched off for the
    phone unless privacy.conf phone_ask_screen is on, and its desktop-memory
    search leaves out the remembered screen text (no_screen_memory); the
    "what's on my screen" quick question then answers in words only
    (screenshots=off)
  - files: the assistant reads a file's text for the phone only from a
    folder open to "phone" (folder_access.py, Settings > Privacy > Folder
    access); it never puts a prompt on the desktop for the phone (nobody
    may be at it) -- the answer says which folder to allow instead
  - quick questions are a fixed catalog (PRESETS); `presets` picks which are
    on the phone. "lock" runs `loginctl lock-session auto` (hypridle's lock_cmd),
    "pause" `playerctl -a pause`
  - at most `limit` questions per RATE_WINDOW_S (10 min), one at a time
  - the journal (identifier phone-ask) gets one line per question: device,
    quick question or free text (its length, never its words), the actions
    done / refused, rate-limit refusals. Never the answer, never the text.

Settings ($XDG_STATE_HOME/hypr/phone-ask/settings.json; `set KEY VALUE`):
    text_questions on|off   shared text with the prefix is a question (on)
    prefix ?|desk:|pc:      what such a text starts with (?)
    reply ping|text|both    how the answer goes back (ping)
    screenshots on|off      the screen question also sends a screenshot (off)
    limit 3|5|10|20         questions per 10 minutes (10)
    presets a,b,..          the quick questions on the phone (all of PRESETS)
    allow a,b,..            actions the phone may have done (ALLOW_DEFAULT)
    device ID|any           only this paired device (any)
The on/off switch and the screen permission are privacy.conf's (phone_ask,
phone_ask_screen: privacy_settings.py), next to the phone's sign-in codes.
"""
import fcntl
import html
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
DIR = os.path.join(STATE_HOME, "hypr", "phone-ask")
SETTINGS = os.path.join(DIR, "settings.json")
RUN_DIR = os.path.join(RUNTIME, "phone-ask")
RECENT = os.path.join(RUN_DIR, "recent.json")
BUSY = os.path.join(RUN_DIR, "busy.lock")
KDECONNECT = os.path.join(CONFIG_HOME, "kdeconnect")
UNIT = "phone-ask.service"
SELF = os.path.abspath(__file__)

BUS_NAME = "org.kde.kdeconnect"
TEXT_EVENT = "textShareReceived"        # kdeconnect's share plugin: shared text, on the clipboard
MONITOR = ["busctl", "--user", "monitor", "--json=short",
           "--match", "type=method_call,interface=org.freedesktop.Notifications,member=Notify"]
REPLY_MAX = 1500
QUESTION_MAX = 1000
RATE_WINDOW_S = 600
SHOT_KEEP_S = 120               # the screenshot file waits this long for the transfer, then goes
CMD_PREFIX = "hypr-desktop-ask-"   # our run-command keys (others' entries are kept)

# name: (the label on the phone, kind, the question for the assistant)
PRESETS = {
    "build": ("Did my build finish?", "assistant",
              "Did my build, test run or other long-running command finish, and did it pass? Look at the "
              "recent notifications and the terminal windows. Answer in one or two sentences."),
    "screen": ("What's on my screen?", "screen",
               "What is on my screen right now? Use look_at_screen with what=screen, then describe it in two "
               "or three sentences. Do not copy out any password, code or personal number you see."),
    "brief": ("Brief", "brief", ""),
    "lock": ("Lock the desktop", "lock", ""),
    "pause": ("Pause media", "pause", ""),
}
# Shared text that is only one of these words: that quick question.
ALIASES = {"build": "build", "compilacion": "build", "compilación": "build", "screen": "screen",
           "pantalla": "screen", "brief": "brief", "resumen": "brief", "lock": "lock", "bloquear": "lock",
           "bloquea": "lock", "pause": "pause", "pausa": "pause", "pausar": "pause"}
ALLOW_DEFAULT = ("media", "volume", "dnd", "dnd-for", "timer", "reminder", "alarm")
# Shown with a warning in Settings: what loses work or opens things.
RISKY = {"close": "closes windows", "session": "opens a session's windows", "session-save": "overwrites a session",
         "where-was-i": "opens windows", "open-url": "opens a link", "launch": "starts apps",
         "context": "switches the project", "gamemode": "changes game mode"}
PREFIXES = ("?", "desk:", "pc:")
DEFAULTS = {"text_questions": "on", "prefix": "?", "reply": "ping", "screenshots": "off", "limit": 10,
            "presets": ",".join(PRESETS), "allow": ",".join(ALLOW_DEFAULT), "device": "any"}
CHOICES = {"text_questions": ("on", "off"), "prefix": PREFIXES, "reply": ("ping", "text", "both"),
           "screenshots": ("on", "off"), "limit": (3, 5, 10, 20)}


def log(text):
    """One line in the journal (identifier phone-ask) -- never a question's
    words or an answer."""
    try:
        from systemd import journal
        journal.send(text, SYSLOG_IDENTIFIER="phone-ask")
    except Exception:       # noqa: BLE001 -- no python3-systemd: stderr (the unit's journal)
        print(f"phone-ask: {text}", file=sys.stderr, flush=True)


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def phone():
    return _module("phone", "phone.py")


def assistant():
    return _module("assistant", "assistant.py")


def privacy():
    return _module("privacy_settings", "privacy_settings.py")


def vc():
    return _module("voice_command", "voice-command.py")


# -- settings ------------------------------------------------------------------------------
def action_names():
    """Every action the assistant can plan (voice-command.py's CATALOG and the
    assistant's own two), the ones the allow-list may name."""
    try:
        a = assistant()
        names = [n for n in vc().CATALOG if n not in a.LEFT_OUT] + list(a.EXTRA_ACTIONS)
    except Exception:       # noqa: BLE001 -- a sibling mid-edit: the shipped list still checks
        names = list(ALLOW_DEFAULT) + list(RISKY)
    return list(dict.fromkeys(names))


def _coerce(key, value):
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r} (one of {', '.join(DEFAULTS)})")
    if key == "limit":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError("limit is a number") from None
    if key in CHOICES:
        if value not in CHOICES[key]:
            raise ValueError(f"{key} is one of {', '.join(map(str, CHOICES[key]))}")
        return value
    if key in ("presets", "allow"):
        items = [v.strip() for v in str(value or "").split(",") if v.strip() and v.strip() != "none"]
        known = list(PRESETS) if key == "presets" else action_names()
        bad = [v for v in items if v not in known]
        if bad:
            raise ValueError(f"unknown in {key}: {', '.join(bad)} (known: {', '.join(known)})")
        return ",".join(dict.fromkeys(items))
    if key == "device":
        value = str(value or "any").strip()
        if value != "any" and not re.fullmatch(r"[\w-]{4,80}", value):
            raise ValueError("device is a KDE Connect device id, or any")
        return value
    return value


def settings(path=None):
    try:
        with open(path or SETTINGS) as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        raw = {}
    out = dict(DEFAULTS)
    for key, value in (raw.items() if isinstance(raw, dict) else ()):
        try:
            out[key] = _coerce(key, value)
        except ValueError:
            if key in ("presets", "allow") and isinstance(value, str):
                # A name the catalog no longer knows (or a sibling mid-edit): only that
                # name goes -- never back to the defaults, which may allow MORE.
                known = set(PRESETS) if key == "presets" else set(action_names())
                out[key] = ",".join(v.strip() for v in value.split(",") if v.strip() in known)
    return out


def set_setting(key, value, path=None):
    path = path or SETTINGS
    value = _coerce(key, value)
    conf = settings(path)
    conf[key] = value
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path + ".tmp", "w") as handle:
        json.dump({k: v for k, v in conf.items() if v != DEFAULTS[k]}, handle, indent=2)
    os.replace(path + ".tmp", path)
    return value


def listed(conf, key):
    return [v for v in conf[key].split(",") if v]


def switches():
    """(on, screen): privacy.conf phone_ask / phone_ask_screen; off when it
    cannot be read (the shipped default)."""
    try:
        ps = privacy()
        conf = ps.load()
        return ps.phone_ask_on(conf), ps.phone_ask_screen_on(conf)
    except Exception:       # noqa: BLE001
        return False, False


# -- KDE Connect's run-command list (QSettings INI) -------------------------------------------
def ini_unescape(value):
    """A QSettings INI value as text: "quoted" with \\" \\\\ \\n \\t \\xHH."""
    value = value.strip()
    if not (len(value) >= 2 and value[0] == value[-1] == '"'):
        return value
    out, i, body = [], 0, value[1:-1]
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n == "x":
                m = re.match(r"[0-9a-fA-F]{1,4}", body[i + 2:])
                if m:
                    out.append(chr(int(m[0], 16)))
                    i += 2 + len(m[0])
                    continue
            out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def ini_escape(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_commands(path):
    """{key: {"name", "command"}} from a kdeconnect_runcommand config; {} when
    there is none or it cannot be read."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return {}
    section = ""
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            section = s
        elif section == "[General]" and s.startswith("commands="):
            raw = ini_unescape(s[len("commands="):])
            m = re.fullmatch(r"@ByteArray\((.*)\)", raw, re.S)
            try:
                data = json.loads(m[1] if m else raw)
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def write_commands(path, commands):
    """The `commands` line rewritten, everything else in the file kept."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = []
    value = "commands=" + ini_escape("@ByteArray(" + json.dumps(commands, separators=(",", ":")) + ")")
    out, section, done = [], "", False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if section == "[General]" and not done:
                out.append(value)
                done = True
            section = s
        if section == "[General]" and s.startswith("commands="):
            if not done:
                out.append(value)
                done = True
            continue
        out.append(line)
    if not done:
        if "[General]" not in [x.strip() for x in out]:
            out = ["[General]", value] + ([""] + out if out else [])
        else:
            out.append(value)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    os.replace(path + ".tmp", path)


def commands_path(device_id):
    return os.path.join(KDECONNECT, device_id, "kdeconnect_runcommand", "config")


def preset_entries(device_id, names):
    """Our run-command entries for one device: fixed words only."""
    py = shlex.quote(sys.executable or "/usr/bin/python3")
    return {CMD_PREFIX + n: {"name": PRESETS[n][0],
                             "command": f"{py} {shlex.quote(SELF)} preset {n} --device {shlex.quote(device_id)}"}
            for n in names if n in PRESETS}


def merged(existing, ours):
    """Someone else's commands kept, ours replaced."""
    out = {k: v for k, v in existing.items() if not k.startswith(CMD_PREFIX)}
    out.update(ours)
    return out


def target_devices(conf):
    """The paired devices the quick questions go to."""
    try:
        paired = phone().devices()
    except Exception:       # noqa: BLE001 -- kdeconnect-cli missing
        paired = []
    return [d for d in paired if conf["device"] in ("any", d["id"])]


def install(conf=None, devices=None):
    conf = conf or settings()
    devices = target_devices(conf) if devices is None else devices
    done = []
    for d in devices:
        path = commands_path(d["id"])
        write_commands(path, merged(read_commands(path), preset_entries(d["id"], listed(conf, "presets"))))
        done.append(d["name"])
    return done


def uninstall(devices=None):
    """Our entries out of every paired device's list (also a device no longer
    chosen)."""
    try:
        devices = phone().devices() if devices is None else devices
    except Exception:       # noqa: BLE001
        devices = []
    ids = {d["id"] for d in devices}
    if os.path.isdir(KDECONNECT):
        ids |= {n for n in os.listdir(KDECONNECT) if os.path.isdir(os.path.join(KDECONNECT, n, "kdeconnect_runcommand"))}
    for dev in ids:
        path = commands_path(dev)
        cmds = read_commands(path)
        if any(k.startswith(CMD_PREFIX) for k in cmds):
            write_commands(path, merged(cmds, {}))


def installed(device_id):
    return sorted(k[len(CMD_PREFIX):] for k in read_commands(commands_path(device_id)) if k.startswith(CMD_PREFIX))


# -- who is asking --------------------------------------------------------------------------
def trusted(device_id, conf, paired=None):
    """(device, None) when `device_id` is a paired, reachable device the
    settings allow; (None, why) otherwise."""
    paired = phone().devices() if paired is None else paired
    dev = next((d for d in paired if d["id"] == device_id), None)
    if dev is None:
        return None, "not a paired device"
    if conf["device"] not in ("any", dev["id"]):
        return None, "not the device chosen in Settings"
    if not dev["reachable"]:
        return None, "not reachable now"
    return dev, None


def rate_ok(conf, now=None, path=None):
    """Counts this question; False when over `limit` per RATE_WINDOW_S."""
    path = path or RECENT
    now = now or time.time()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            times = [t for t in json.loads(handle.read() or "[]") if now - t < RATE_WINDOW_S]
        except ValueError:
            times = []
        ok = len(times) < conf["limit"]
        if ok:
            times.append(now)
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(times))
    return ok


def busy_lock():
    """One question at a time: the held lock file, or None when another one runs."""
    os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
    handle = open(BUSY, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


# -- the answer, back to the phone --------------------------------------------------------------
def clip_reply(text):
    text = (text or "").strip()
    return text if len(text) <= REPLY_MAX else text[:REPLY_MAX - 1].rstrip() + "…"


def send_reply(dev, text, conf):
    """Over kdeconnect-cli; True when the phone took it."""
    p = phone()
    text = clip_reply(text)
    ok = True
    if conf["reply"] in ("ping", "both"):
        ok = p.run(p.CLI, "-d", dev["id"], "--ping-msg", text, timeout=15) is not None and ok
    if conf["reply"] in ("text", "both"):
        ok = p.run(p.CLI, "-d", dev["id"], "--share-text", text, timeout=15) is not None and ok
    return ok


def send_file(dev, path):
    p = phone()
    return p.run(p.CLI, "-d", dev["id"], "--share", path, timeout=60) is not None


# -- the work -------------------------------------------------------------------------------------
def phone_conf(base, screen_ok, allowed):
    """The assistant's own settings, held tighter for a question from the
    phone: every action asks (pending, judged here), no screen unless
    allowed, no action tool at all when nothing is allowed."""
    conf = dict(base)
    conf["confirm"] = "all"
    if not screen_ok:
        conf["tool_screen"] = "off"
    if not allowed:
        conf["tool_actions"] = "off"
    return conf


def no_screen_memory(search):
    """assistant.py's search_memory tool without the desktop memory's screen
    text (OCR rows and their thumbnails): with phone_ask_screen off, "what
    was on my screen a minute ago" must not reach the phone that way either."""
    def run(name, args, turn):
        if (args or {}).get("source") == "screen":
            return {"note": "the screen is not described to the phone (Settings > Devices > Ask from the "
                            "phone): say so"}
        res = search(name, args, turn)
        if isinstance(res, dict) and isinstance(res.get("memories"), list):
            rows = [r for r in res["memories"] if not (isinstance(r, dict) and r.get("source") == "screen")]
            res = dict(res, memories=rows, files=[{"path": r.get("url") or r.get("thumbnail")} for r in rows
                                                  if isinstance(r, dict) and (r.get("url") or r.get("thumbnail"))])
        return res
    return run


def judge_pending(pending, allowed):
    """(ok, blocked names): may the phone have this plan done?"""
    names = [a.get("action") if isinstance(a, dict) else None for a in (pending or {}).get("actions") or []]
    blocked = [str(n) for n in names if n not in allowed]
    return (bool(names) and not blocked), blocked


def ask_assistant(question, screen_ok, allowed, dry_run=False):
    """(answer text, actions done, actions refused) from assistant.py's tool loop."""
    a = assistant()
    base = a.settings()
    if base["enabled"] != "on":
        return "The assistant is switched off on the desktop (Settings > Assistant).", [], []
    conf = phone_conf(base, screen_ok, allowed)
    tools = getattr(a, "RUN", None)     # this process only (`ask` / `preset` run on their own)
    memory = tools.get("search_memory") if isinstance(tools, dict) else None
    if memory and not screen_ok:
        tools["search_memory"] = no_screen_memory(memory)
    try:
        turn = a.run_turn(question, conf, who="phone")     # folder access: the phone's own grants
    finally:
        if memory:
            tools["search_memory"] = memory
    if turn["question"] and not dry_run:     # into the assistant's conversation, like `assistant.py ask`
        try:
            a.remember({k: v for k, v in turn.items() if k != "undo"}, conf)
        except OSError:
            pass
    answer = turn["answer"] or ""
    waiting = a.WORDS.get(turn.get("lang", "en"), a.WORDS["en"]).get("waiting", "")
    if waiting:
        answer = answer.replace(waiting, "").strip()
    done, refused = list(turn.get("done") or []), []
    pending = turn.get("pending")
    if pending:
        ok, blocked = judge_pending(pending, allowed)
        if ok and not dry_run:
            result = a.confirm(pending["id"])
            if result is None:
                answer += "\n(The action expired before it could be done.)"
            else:       # the model's words were "when you confirm…": what happened instead
                lines, problems, _undo = result
                done += lines
                answer = "Done: " + "; ".join(lines) + (f"\nProblems: {'; '.join(problems)}" if problems else "")
        else:
            a.take_pending(pending["id"])
            refused = blocked
            answer += ("\nNot done from the phone: " + ", ".join(blocked) + " -- that needs the desktop, or its "
                       "name in Settings > Devices > Ask from the phone > Allowed actions." if blocked
                       else "\n(Dry run: " + "; ".join(pending.get("lines") or []) + " -- not done.)" if dry_run
                       else "\n(Nothing was done.)")
    return answer.strip(), done, refused


def do_lock(dry_run=False):
    if subprocess.run(["pidof", "hyprlock"], capture_output=True).returncode == 0:
        return "The desktop is already locked."
    if dry_run:
        return "Would lock the desktop (dry run)."
    # "auto", not the bare command: kdeconnectd (and so a run-command) lives in
    # user@.service, outside any login session -- logind's "self" fails there,
    # "auto" falls back to this user's graphical session.
    ok = subprocess.run(["loginctl", "lock-session", "auto"], capture_output=True).returncode == 0
    return "Locked the desktop." if ok else "Could not lock the desktop (loginctl lock-session failed)."


def do_pause(dry_run=False):
    try:
        out = subprocess.run(["playerctl", "-a", "status"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return "playerctl is not installed: nothing paused."
    playing = out.split().count("Playing")
    if not playing:
        return "Nothing was playing."
    if not dry_run:
        subprocess.run(["playerctl", "-a", "pause"], capture_output=True, timeout=5)
    return f"Paused {playing} player(s)." + (" (dry run)" if dry_run else "")


def do_brief():
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, "brief.py"), "text"], capture_output=True,
                             text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or "The brief had nothing to say."


def screenshot(dev, dry_run=False):
    """The screen to the phone (screenshots=on), after screen-ask.py's
    private-window check. A line for the reply."""
    sa = _module("screen_ask", "screen-ask.py")
    png, why = sa.capture("screen")
    if not png:
        return f"No screenshot: {why or 'nothing captured'}."
    if dry_run:
        sa._remove(png)
        return "Would send a screenshot (dry run)."
    ok = send_file(dev, png)
    # The transfer reads the file after kdeconnect-cli returns: removed a bit later.
    threading.Timer(SHOT_KEEP_S, sa._remove, args=(png,)).start()
    return "Screenshot sent." if ok else "The phone did not take the screenshot."


def answer_for(kind, question, conf, screen_ok, dev=None, dry_run=False):
    """(answer, done, refused) for one question; `kind` a preset kind or "assistant"."""
    allowed = listed(conf, "allow")
    if kind == "lock":
        return do_lock(dry_run), ["lock"], []
    if kind == "pause":
        return do_pause(dry_run), ["pause media"], []
    if kind == "brief":
        return do_brief(), [], []
    if kind == "screen":
        if not screen_ok:
            return ("Describing the screen to the phone is off (Settings > Devices > Ask from the phone).",
                    [], ["screen"])
        text, done, refused = ask_assistant(question, True, [], dry_run)
        if conf["screenshots"] == "on" and dev is not None:
            text += "\n" + screenshot(dev, dry_run)
        return text, done, refused
    return ask_assistant(question, screen_ok, allowed, dry_run)


def handle(device_id, kind, question, source, dry_run=False, conf=None):
    """Everything for one question from the phone: checks, the answer, the
    reply, the journal line. Returns (exit code, the reply text)."""
    conf = conf or settings()
    on, screen_ok = switches()
    what = f"quick question {source}" if source.startswith("preset:") else f"{source} question ({len(question)} chars)"
    if not on and not dry_run:      # a dry run is asked here, at the desk: the switch is the phone's
        log(f"refused a {what}: asking from the phone is off")
        return 3, "Asking from the phone is off on the desktop (Settings > Devices)."
    dev, why = (trusted(device_id, conf) if device_id else (None, "no device given"))
    if dev is None and not dry_run:
        log(f"refused a {what} from {device_id or '?'}: {why}")
        return 3, f"Refused: {why}."
    name = dev["name"] if dev else "(dry run)"
    if not dry_run and not rate_ok(conf):
        log(f"refused a {what} from {name}: over {conf['limit']} per {RATE_WINDOW_S // 60} min")
        send_reply(dev, f"Too many questions: at most {conf['limit']} per {RATE_WINDOW_S // 60} minutes.", conf)
        return 4, ""
    lock = busy_lock()
    if lock is None:
        log(f"refused a {what} from {name}: another question is still running")
        if dev and not dry_run:
            send_reply(dev, "Still working on the last question.", conf)
        return 4, ""
    try:
        started = time.time()
        try:
            text, done, refused = answer_for(kind, question, conf, screen_ok, dev, dry_run)
        except Exception as err:    # noqa: BLE001 -- the phone hears that it failed, not silence
            log(f"a {what} from {name} failed: {type(err).__name__}")
            text, done, refused = f"The desktop could not answer ({type(err).__name__}).", [], []
        sent = dry_run or send_reply(dev, text, conf)
        log(f"{what} from {name}: answered in {time.time() - started:.0f} s"
            + (f", done: {', '.join(done)}" if done else "") + (f", refused: {', '.join(refused)}" if refused else "")
            + ("" if sent else ", the reply did not reach the phone") + (" (dry run)" if dry_run else ""))
        return 0, text
    finally:
        lock.close()


def route(text, conf):
    """(kind, question) for a shared text after its prefix: an ALIASES word
    -> that quick question (when it is on), else the assistant."""
    word = text.strip().strip("¿?¡!.").strip().lower()
    preset = ALIASES.get(word)
    if preset and preset in listed(conf, "presets"):
        return PRESETS[preset][1], PRESETS[preset][2]
    return "assistant", text.strip()


def strip_prefix(text, prefix):
    """The question in a shared text, or None when it is an ordinary share."""
    text = (text or "").strip()
    if not text.lower().startswith(prefix.lower()):
        return None
    q = text[len(prefix):].strip()
    return q[:QUESTION_MAX] if q else None


# -- the listener --------------------------------------------------------------------------------
def plain(body):
    """A notification body as text (kdeconnectd's may carry markup)."""
    return html.unescape(re.sub(r"<[^>]+>", "", body or "")).strip()


def shared_text_event(msg, kde_pid, pid_of):
    """From one busctl JSON message: (title, body) when it is kdeconnectd's
    own "text shared" notification, else None. kde_pid() is kdeconnectd's
    PID, pid_of(sender) a bus connection's."""
    if msg.get("member") != "Notify" or msg.get("interface") != "org.freedesktop.Notifications":
        return None
    data = (msg.get("payload") or {}).get("data") or []
    if len(data) < 7 or not isinstance(data[6], dict):
        return None
    hints = {k: (v.get("data") if isinstance(v, dict) else v) for k, v in data[6].items()}
    if hints.get("x-kde-eventId") != TEXT_EVENT:
        return None
    if hints.get("x-kde-appname") not in (None, "kdeconnect"):
        return None
    pid = kde_pid()
    if not pid or pid_of(msg.get("sender")) != pid:
        return None
    return str(data[3] or ""), plain(str(data[4] or ""))


def device_in_title(title, paired):
    """The paired device whose name is in the notification's title (the
    longest such name), or None."""
    hits = [d for d in paired if d["name"] and d["name"] in title]
    if not hits:
        return None
    best = max(hits, key=lambda d: len(d["name"]))
    # Two names that are not one inside the other ("Shared" and "Tab" in "Shared
    # text from Tab..."): which one sent it is a guess -- refused, not guessed.
    return best if all(d["name"] in best["name"] for d in hits) else None


def die_with_parent():
    """busctl goes when the listener does (PR_SET_PDEATHSIG), not at its next line."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:       # noqa: BLE001 -- then it ends at its next write to the closed pipe
        pass


class Listener:
    """phone-ask.py watch: busctl's Notify calls -> a question per matching
    shared text (in its own process: `ask -`), see the docstring."""

    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, method, sig, args):
        try:
            reply = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                       method, self.GLib.Variant(sig, args), None,
                                       self.Gio.DBusCallFlags.NONE, 2000, None)
            return reply.unpack()[0]
        except Exception:       # noqa: BLE001 -- gone already
            return None

    def pid_of(self, sender):
        return self.call("GetConnectionUnixProcessID", "(s)", (sender,)) if sender else None

    def kde_pid(self):
        owner = self.call("GetNameOwner", "(s)", (BUS_NAME,))
        return self.pid_of(owner) if owner else None

    def take(self, title, body):
        conf = settings()
        if conf["text_questions"] != "on" or not switches()[0]:
            return
        clip = ""
        question = strip_prefix(body, conf["prefix"])
        if question is None:        # the body may be cut short: the clipboard has the whole text
            clip = phone().clipboard_text()
            question = strip_prefix(clip, conf["prefix"])
        if question is None:
            return                  # an ordinary share
        try:
            dev = device_in_title(title, phone().devices())
        except Exception:       # noqa: BLE001
            dev = None
        if dev is None:
            log("refused a shared-text question: the sender is not a paired device")
            return
        if (clip or phone().clipboard_text()).strip().lower().startswith(conf["prefix"].lower()):
            phone().run("wl-copy", "--clear", timeout=5)    # the question off the clipboard
        kind, q = route(question, conf)
        argv = [sys.executable, SELF, "ask", "--device", dev["id"], "--source", "text"]
        if kind != "assistant":
            argv = [sys.executable, SELF, "preset", next(n for n, p in PRESETS.items() if p[1] == kind),
                    "--device", dev["id"]]
        proc = subprocess.Popen(argv + (["-"] if kind == "assistant" else []), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, start_new_session=True, text=True)
        try:
            proc.communicate(q if kind == "assistant" else "", timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()

    def run(self):
        while True:
            try:
                proc = subprocess.Popen(MONITOR, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                        preexec_fn=die_with_parent)
            except OSError as err:
                log(f"busctl is missing ({err}): not listening")
                return
            log("listening for questions shared from the phone")
            for line in proc.stdout:
                if '"x-kde-eventId"' not in line:   # most notifications: not even parsed
                    continue
                try:
                    got = shared_text_event(json.loads(line), self.kde_pid, self.pid_of)
                except ValueError:
                    continue
                if got:
                    threading.Thread(target=self.take, args=got, daemon=True).start()
            proc.wait()
            log(f"busctl monitor ended ({proc.returncode}); again in 5 s")
            time.sleep(5)


# -- on / off, status --------------------------------------------------------------------------------
def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=20)


def apply(conf=None):
    """Make the world match the switches: the quick questions on the phone and
    the listener, both only while it is on."""
    conf = conf or settings()
    on, _screen = switches()
    uninstall()             # also from a device no longer chosen
    if on:
        install(conf)
    if on and conf["text_questions"] == "on":
        systemctl("enable", "--now", UNIT)
    else:
        systemctl("disable", "--now", UNIT)


def status():
    conf = settings()
    on, screen_ok = switches()
    try:
        paired = phone().devices()
    except Exception:       # noqa: BLE001
        paired = []
    unit = (systemctl("is-active", UNIT).stdout or "").strip()
    devs = [{"id": d["id"], "name": d["name"], "reachable": d["reachable"], "chosen": conf["device"] in ("any", d["id"]),
             "installed": installed(d["id"])} for d in paired]
    return {"on": on, "screen": screen_ok, "settings": conf, "listener": unit == "active", "devices": devs,
            "presets": {n: p[0] for n, p in PRESETS.items()}, "actions": action_names(), "risky": RISKY,
            "allow_default": list(ALLOW_DEFAULT), "prefixes": list(PREFIXES), "limits": list(CHOICES["limit"])}


def human_status(data):
    conf = data["settings"]
    lines = [f"asking from the phone: {'on' if data['on'] else 'off'}  (screen descriptions "
             f"{'allowed' if data['screen'] else 'off'}, screenshots {conf['screenshots']})",
             f"shared text with “{conf['prefix']}”: {conf['text_questions']}, listener "
             f"{'running' if data['listener'] else 'stopped'}",
             f"reply: {conf['reply']}  ·  at most {conf['limit']} per 10 min  ·  device: {conf['device']}",
             f"allowed actions: {conf['allow'] or 'none'}"]
    for d in data["devices"]:
        lines.append(f"  {d['name']} ({'reachable' if d['reachable'] else 'away'}): quick questions "
                     f"{', '.join(d['installed']) or 'none'}")
    return "\n".join(lines)


def option(rest, flag):
    if flag in rest:
        i = rest.index(flag)
        if i + 1 < len(rest):
            value = rest[i + 1]
            del rest[i:i + 2]
            return value
    return None


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], list(argv[1:])
    as_json = "--json" in rest
    dry = "--dry-run" in rest
    rest = [r for r in rest if r not in ("--json", "--dry-run")]
    device = option(rest, "--device")
    source = option(rest, "--source") or "cli"
    if cmd in ("on", "off"):
        privacy().set_key("phone_ask", cmd)
        apply()
        print(f"asking from the phone: {cmd}")
    elif cmd == "screen" and rest[:1] in (["on"], ["off"]):
        privacy().set_key("phone_ask_screen", rest[0])
    elif cmd == "preset" and len(rest) == 1:
        name = rest[0]
        conf = settings()
        if name not in PRESETS:
            sys.exit(f"phone-ask: no quick question {name!r} ({', '.join(PRESETS)})")
        if name not in listed(conf, "presets"):
            log(f"refused quick question {name}: switched off in Settings")
            sys.exit(3)
        code, text = handle(device, PRESETS[name][1], PRESETS[name][2], f"preset:{name}", dry, conf)
        if dry or not device:
            print(text)
        sys.exit(code)
    elif cmd == "ask" and rest:
        text = sys.stdin.read() if rest == ["-"] else " ".join(rest)
        text = " ".join(text.split())[:QUESTION_MAX]
        if not text:
            sys.exit("phone-ask: no question")
        code, answer = handle(device, "assistant", text, source if source in ("text", "cli") else "cli", dry)
        if dry or not device:
            print(answer)
        sys.exit(code)
    elif cmd == "watch":
        Listener().run()
    elif cmd == "install":
        print("quick questions on: " + (", ".join(install()) or "no paired device"))
    elif cmd == "uninstall":
        uninstall()
    elif cmd == "status":
        data = status()
        print(json.dumps(data, ensure_ascii=False) if as_json else human_status(data))
    elif cmd == "set" and len(rest) == 2:
        try:
            value = set_setting(rest[0], rest[1])
        except ValueError as err:
            sys.exit(f"phone-ask: {err}")
        if rest[0] in ("presets", "device", "text_questions"):
            apply()
        print(value)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
