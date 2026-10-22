#!/usr/bin/env python3
"""Privacy settings: what the desktop remembers about you, and who reads it
(Settings > Privacy, and the same commands for the search bar and the keys).

    privacy_settings.py status [--json]        everything below, as the page shows it
    privacy_settings.py activity on|off         the activity history (activity-log.service:
                                                enable --now / disable --now)
    privacy_settings.py activity keep <days>    how long it is kept (1..365), pruned now
    privacy_settings.py activity exclude <class>  log that app as "private" (the time only,
                                                no app name or title), past entries too
    privacy_settings.py activity include <class>  undo that (its past entries stay private)
    privacy_settings.py activity forget hour|day|all
    privacy_settings.py clipboard on|off        the clipboard history recorders
                                                (cliphist@text / cliphist@image)
    privacy_settings.py clipboard max <n>       how many copies cliphist keeps (10..5000)
    privacy_settings.py clipboard clear         wipe the clipboard history (cliphist wipe)
    privacy_settings.py ask on|off              "Ask your desktop" (ask-desktop.py)
    privacy_settings.py ask files|clipboard|activity on|off   what it may read
    privacy_settings.py ask index on|off        its search by meaning (desktop-index.py:
                                                off = not built, not searched; the index
                                                itself goes with `desktop-index.py clear`)
    privacy_settings.py recent on|off           GTK's "recently used files" list. OFF EMPTIES
                                                IT: every running GTK app clears the
                                                list when the setting goes false
    privacy_settings.py recent age <days>       forget entries older than that (-1 = never);
                                                the running GTK apps drop older ones at once
    privacy_settings.py recent clear            empty the list (recently-used.xbel)
    privacy_settings.py phone codes on|off      offer sign-in codes from the phone's
                                                notifications (phone.py; off as shipped)
    privacy_settings.py phone ask|screen on|off asking the desktop from the phone, and
                                                screen descriptions in its answers
                                                (phone-ask.py; both off as shipped)
    privacy_settings.py presence on|off         the webcam presence check (presence.py:
                                                set + enable --now / disable --now
                                                presence.service; off as shipped)
    privacy_settings.py gestures on|off         hand gestures to the webcam (gestures.py,
                                                inside presence.service; off as shipped)
    privacy_settings.py gaze on|off             which monitor you look at (the same)
    privacy_settings.py camera off              all three off at once: the camera is closed
                                                (Settings > Presence's switch)
    privacy_settings.py assistant memory on|off the assistant's conversations go into
                                                the desktop memory (assistant.py; off
                                                as shipped)
    privacy_settings.py focus watch on|off      focus guard follows which window has the
                                                focus to notice scattered switching
                                                (focus-guard.py; off as shipped)
    privacy_settings.py machines clipboard|memory on|off   share copies with the paired
                                                machines / let them ask this one's memory
                                                (peers.py; both off as shipped)
    privacy_settings.py memory on|off          desktop memory (desktop-memory.py) collects
    privacy_settings.py memory activity|clipboard|notifications|captions|screen on|off
    privacy_settings.py memory keep <days>      how long memories are kept (1..365)
    privacy_settings.py memory screen-keep <days>   the screenshots' text + thumbnails
    privacy_settings.py memory every <minutes>  a screenshot this often (5..240)
    privacy_settings.py memory include <class>  remember that app again (forget app
                                                is desktop-memory.py's)

Where each setting lives -- nothing is kept here, so each one survives a
Hyprland reload and a re-login by itself:

    activity / clipboard on|off  whether the user unit is enabled (systemd starts
                                 it at login through graphical-session.target)
    clipboard max                ~/.config/cliphist/config, "max-items N" (read by
                                 every `cliphist store`; the oldest copies over
                                 the limit go at the next copy)
    recent on|off, age           GSettings org.gnome.desktop.privacy
                                 remember-recent-files / recent-files-max-age:
                                 GTK apps read these (GDK maps them to
                                 gtk-recent-files-enabled / -max-age)
    the rest                     ~/.config/hypr/privacy.conf, key=value:

        activity_keep_days=30        read by activity-log.py at every prune
        activity_exclude=a,b         window classes, case-insensitive; re-read by
                                     activity-log.py whenever the file changes
        ask=on                       ask-desktop.py answers at all
        ask_files=on                 its search_files tool (plocate, the first
                                     lines of the top documents)
        ask_clipboard=on             its search_clipboard tool (cliphist)
        ask_activity=on              its search_activity tool (the activity history)
        ask_index=on                 its search_meaning tool and desktop-index.py's
                                     index of your documents (needs ask_files on too)
        phone_codes=off              phone.py's watcher reads the phone's notifications
                                     (KDE Connect) for sign-in codes and offers Copy;
                                     off as shipped (Settings > Devices, `phone.py
                                     codes on|off`, `privacy_settings.py phone codes on|off`)
        phone_ask=off                the paired phone may ask the desktop assistant and
                                     get the answer back (phone-ask.py; OFF as shipped;
                                     `phone-ask.py on|off` also sets up its quick questions)
        phone_ask_screen=off         such an answer may describe the screen (OFF as shipped)
        presence=off                 presence.py may open the webcam (1-2 frames a second,
                                     in memory only) to tell if you are at the desk;
                                     OFF as shipped. presence.service checks it too
        gestures=off                 gestures.py may read hands in those frames (8-15 a
        gaze=off                     second while on) / your head's turn, for which
                                     monitor; OFF as shipped. Either one keeps
                                     presence.service running (camera_wanted())
        assistant_memory=off         assistant.py adds each finished exchange (question
                                     and answer) to the desktop memory, as a
                                     "notifications" memory from the app "Assistant",
                                     so recall / search_memory find it; OFF as shipped
                                     (Settings > Assistant, `privacy_settings.py
                                     assistant memory on|off`)
        memory=on                    desktop-memory.py collects (and recall answers)
        memory_<source>=on|off       activity, clipboard, notifications: on; captions
                                     (voice.py writes them) and screen: OFF as shipped
        memory_keep_days=30          memories older than this are dropped
        memory_screen_keep_days=7    the screenshots' OCR text and thumbnails
        memory_screen_minutes=15     a screenshot (when that source is on) this often
        memory_exclude=a,b           apps forgotten in the memory and skipped from then on
        machines_clipboard=off       peers.py shares text copies with the paired machines
                                     (never secrets / private windows); OFF as shipped
        machines_memory=off          the paired machines may ask this one's desktop memory
                                     (the answer only); OFF as shipped (Settings > Machines,
                                     `privacy_settings.py machines clipboard|memory on|off`)
        focus_watch=off              focus-guard.py follows the focus (class and title, reduced
                                     at once to a project / app group, kept in memory only)
                                     to offer a focus block when you hop around; OFF as
                                     shipped (Settings > Focus, `focus-guard.py set detect`)

activity-log.py and ask-desktop.py import this module for the privacy.conf
part (load(), keep_days(), excluded(), ask_sources()); everything else they
did before is unchanged.

Built-in private windows, whatever privacy.conf says: KeePassXC, and any window
whose title says Private Browsing / Incognito / InPrivate (activity-log.py's
PRIVATE_CLASS / PRIVATE_TITLE). Copies that the copying app marks as sensitive
(KeePassXC does: CLIPBOARD_STATE=sensitive) are never stored by cliphist 0.6+.

`status` is read-only and never prints what is in the histories: only counts,
sizes and dates, which window classes are open (for the "private apps"
picker) and which apps are using the microphone / camera / location right now
(waybar/scripts/privacy.py, the bar's own indicators).
"""
import ast
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
CONF = os.path.join(CONFIG_HOME, "hypr", "privacy.conf")
CLIPHIST_CONF = os.path.join(CONFIG_HOME, "cliphist", "config")
RECENT = os.path.join(DATA_HOME, "recently-used.xbel")
ACTIVITY_LOG = os.path.join(HERE, "activity-log.py")
INDICATORS = os.path.join(HOME, ".config", "waybar", "scripts", "privacy.py")
WTTR = os.path.join(HOME, ".config", "waybar", "scripts", "wttr.py")
EMERGENCY = os.path.join(HERE, "emergency-alerts.py")
DESKTOP_INDEX = os.path.join(HERE, "desktop-index.py")
DESKTOP_MEMORY = os.path.join(HERE, "desktop-memory.py")
PRESENCE_UNIT = "presence.service"
NOTIFY = os.path.join(HERE, "notify-settings.py")
# The emergency-alerts sources whose download URL carries your coordinates
# (emergency-alerts.py: nws() asks api.weather.gov about ?point=lat,lon and
# emsc() asks seismicportal.eu with &lat=&lon=). Every other source is a
# whole feed (or a whole country / region) matched against your place on
# this computer. Keep in step if emergency-alerts.py gains a source.
SENDS_PLACE = {"nws": "the US weather service", "emsc": "EMSC"}

ACTIVITY_UNIT = "activity-log.service"
CLIP_UNITS = ["cliphist@text.service", "cliphist@image.service"]
SOURCES = ("files", "clipboard", "activity")
# Desktop memory's sources (desktop-memory.py): the invasive two OFF as shipped.
MEMORY_SOURCES = ("activity", "clipboard", "notifications", "captions", "screen")
DEFAULTS = {"activity_keep_days": "30", "activity_exclude": "", "ask": "on",
            "ask_files": "on", "ask_clipboard": "on", "ask_activity": "on", "ask_index": "on",
            "phone_codes": "off", "phone_ask": "off", "phone_ask_screen": "off",
            "presence": "off", "assistant_memory": "off",
            "gestures": "off", "gaze": "off", "focus_watch": "off",
            "memory": "on", "memory_activity": "on", "memory_clipboard": "on", "memory_notifications": "on",
            "memory_captions": "off", "memory_screen": "off", "memory_keep_days": "30",
            "memory_screen_keep_days": "7", "memory_screen_minutes": "15", "memory_exclude": "",
            "machines_clipboard": "off", "machines_memory": "off"}
MEMORY_KEEP_RANGE = (1, 365)
MEMORY_SCREEN_MINUTES = (5, 240)
KEEP_RANGE = (1, 365)
CLIP_RANGE = (10, 5000)
CLIP_DEFAULT = 750          # cliphist's own default when the config has no max-items
PRIVACY_GSCHEMA = "org.gnome.desktop.privacy"
EMPTY_XBEL = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<xbel version="1.0"\n'
              '      xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks"\n'
              '      xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info"\n'
              '>\n</xbel>\n')
HEADER = ("# Privacy settings (scripts/privacy_settings.py; its docstring explains).\n"
          "# Settings > Privacy writes this; read by activity-log.py and ask-desktop.py.\n")


# -- privacy.conf ------------------------------------------------------------------
def parse_conf(text):
    """key=value lines over DEFAULTS; comments, blanks and junk are skipped."""
    conf = dict(DEFAULTS)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        conf[key.strip()] = value.strip()
    return conf


_cache = {"mtime": None, "conf": None}


def load(path=None):
    """privacy.conf as a dict (the defaults when it is missing). Cached on the
    file's mtime, so the activity-log daemon can call it on every write."""
    path = path or CONF
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return dict(DEFAULTS)
    if _cache["mtime"] == (path, mtime):
        return dict(_cache["conf"])
    try:
        with open(path) as handle:
            conf = parse_conf(handle.read())
    except OSError:
        return dict(DEFAULTS)
    _cache.update(mtime=(path, mtime), conf=conf)
    return dict(conf)


def save(conf, path=None):
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = HEADER + "".join(f"{k}={conf.get(k, v)}\n" for k, v in DEFAULTS.items())
    body += "".join(f"{k}={v}\n" for k, v in conf.items() if k not in DEFAULTS)
    write_atomic(path, body)


def set_key(key, value, path=None):
    conf = load(path)
    conf[key] = value
    save(conf, path)


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
        except OSError:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def flag(value):
    return str(value).strip().lower() in ("on", "1", "true", "yes")


def keep_days(conf):
    try:
        days = int(conf.get("activity_keep_days", DEFAULTS["activity_keep_days"]))
    except ValueError:
        days = int(DEFAULTS["activity_keep_days"])
    return max(KEEP_RANGE[0], min(KEEP_RANGE[1], days))


def excluded(conf):
    """The user's private window classes, lower-case, in the order added."""
    out = []
    for cls in (conf.get("activity_exclude") or "").split(","):
        cls = cls.strip().lower()
        if cls and cls not in out:
            out.append(cls)
    return out


def phone_codes_on(conf):
    """May phone.py's watcher look for sign-in codes in phone notifications?"""
    return flag(conf.get("phone_codes", DEFAULTS["phone_codes"]))


def phone_ask_on(conf):
    """May the paired phone ask the desktop assistant (phone-ask.py; OFF as shipped)?"""
    return flag(conf.get("phone_ask", DEFAULTS["phone_ask"]))


def phone_ask_screen_on(conf):
    """May an answer to the phone describe the screen (phone-ask.py; OFF as shipped)?"""
    return flag(conf.get("phone_ask_screen", DEFAULTS["phone_ask_screen"]))


def presence_on(conf):
    """May presence.py open the webcam (OFF as shipped)?"""
    return flag(conf.get("presence", DEFAULTS["presence"]))


def assistant_memory_on(conf):
    """May assistant.py put its conversations into the desktop memory (OFF
    as shipped)? Only while the memory itself is on, too."""
    return flag(conf.get("assistant_memory", DEFAULTS["assistant_memory"])) and memory_on(conf)


def gestures_on(conf):
    """May gestures.py read hand gestures in the webcam frames (OFF as shipped)?"""
    return flag(conf.get("gestures", DEFAULTS["gestures"]))


def gaze_on(conf):
    """May gestures.py work out which monitor you look at (OFF as shipped)?"""
    return flag(conf.get("gaze", DEFAULTS["gaze"]))


def machines_clipboard_on(conf):
    """May peers.py send text copies to the paired machines, and put theirs
    on this clipboard (OFF as shipped)?"""
    return flag(conf.get("machines_clipboard", DEFAULTS["machines_clipboard"]))


def machines_memory_on(conf):
    """May the paired machines ask this one's desktop memory (peers.py; the
    answer only, read-only; OFF as shipped)?"""
    return flag(conf.get("machines_memory", DEFAULTS["machines_memory"]))


def camera_wanted(conf):
    """Presence, gestures or gaze: any of them keeps presence.service (the
    camera's one owner) running."""
    return presence_on(conf) or gestures_on(conf) or gaze_on(conf)


def focus_watch_on(conf):
    """May focus-guard.py follow which window has the focus, to notice
    scattered switching (OFF as shipped)?"""
    return flag(conf.get("focus_watch", DEFAULTS["focus_watch"]))


def ask_on(conf):
    return flag(conf.get("ask", "on"))


def ask_sources(conf):
    """The sources Ask your desktop may read: a subset of SOURCES (empty when
    Ask itself is off)."""
    if not ask_on(conf):
        return set()
    return {s for s in SOURCES if flag(conf.get(f"ask_{s}", "on"))}


def memory_on(conf):
    """Desktop memory collects and answers at all."""
    return flag(conf.get("memory", DEFAULTS["memory"]))


def memory_sources(conf):
    """The desktop memory sources that are on: a subset of MEMORY_SOURCES
    (empty when the memory itself is off)."""
    if not memory_on(conf):
        return set()
    return {s for s in MEMORY_SOURCES if flag(conf.get(f"memory_{s}", DEFAULTS[f"memory_{s}"]))}


def _int(conf, key, lo, hi):
    try:
        n = int(conf.get(key, DEFAULTS[key]))
    except ValueError:
        n = int(DEFAULTS[key])
    return max(lo, min(hi, n))


def memory_keep_days(conf):
    return _int(conf, "memory_keep_days", *MEMORY_KEEP_RANGE)


def memory_screen_keep_days(conf):
    return _int(conf, "memory_screen_keep_days", *MEMORY_KEEP_RANGE)


def memory_screen_minutes(conf):
    return _int(conf, "memory_screen_minutes", *MEMORY_SCREEN_MINUTES)


def memory_excluded_own(conf):
    """The apps forgotten in the desktop memory (memory_exclude), lower-case."""
    out = []
    for cls in (conf.get("memory_exclude") or "").split(","):
        cls = cls.strip().lower()
        if cls and cls not in out:
            out.append(cls)
    return out


def memory_excluded(conf):
    """Every app the desktop memory skips: its own list and activity's
    private apps."""
    return list(dict.fromkeys(memory_excluded_own(conf) + excluded(conf)))


def clean_class(text):
    """A window class as typed: trimmed, lower-case; no commas (the list
    separator) or newlines. '' when nothing usable is left."""
    return re.sub(r"[,\s]+", "", text or "").lower()[:120]


# -- cliphist's config ------------------------------------------------------------
def cliphist_max(text):
    m = re.search(r"^[ \t]*max-items[ \t]+(\d+)[ \t]*$", text, re.M)
    return int(m[1]) if m else None


def set_cliphist_max(text, n):
    """The config text with max-items set to n: the line replaced where it
    is (and the "newest N" in the comment above it kept in step), or added."""
    if re.search(r"^[ \t]*max-items[ \t]+\d+[ \t]*$", text, re.M):
        old = cliphist_max(text)
        text = re.sub(r"^[ \t]*max-items[ \t]+\d+[ \t]*$", f"max-items {n}", text, count=1, flags=re.M)
        if old is not None:
            text = re.sub(rf"\bnewest {old}\b", f"newest {n}", text)
    else:
        text = (text.rstrip("\n") + "\n" if text.strip() else "") + f"max-items {n}\n"
    return text


def read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


# -- the recently-used list -------------------------------------------------------
def xbel_count(text):
    """How many files the recently-used.xbel text lists (0 if unreadable)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return 0
    return sum(1 for el in root if el.tag == "bookmark")


# -- what is happening right now ---------------------------------------------------
def screen_shared(nodes):
    """True when a portal screen share is running: xdg-desktop-portal-
    hyprland's PipeWire video source exists while something streams from it.
    `nodes` is pw-dump's JSON; None when it could not be read."""
    if nodes is None:
        return None
    for obj in nodes:
        info = obj.get("info") or {}
        props = info.get("props") or {}
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        name = " ".join(str(props.get(k, "")) for k in ("node.name", "application.name",
                                                        "application.process.binary"))
        if props.get("media.class") == "Video/Source" and ("xdph" in name.lower() or "portal" in name.lower()):
            return True
    return False


def unit_states(units):
    """{unit: (ActiveState, UnitFileState)} in one systemctl call."""
    out = run("systemctl", "--user", "show", "-p", "Id", "-p", "ActiveState", "-p", "UnitFileState", *units)
    states, cur = {}, {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if cur.get("Id"):
                states[cur["Id"]] = (cur.get("ActiveState", "?"), cur.get("UnitFileState", "?"))
            cur = {}
            continue
        key, _, value = line.partition("=")
        cur[key] = value
    for u in units:
        states.setdefault(u, ("?", "?"))
    return states


def run(*cmd, timeout=10, env=None, input=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                              input=input).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def run_ok(*cmd, timeout=20):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return res.returncode == 0, (res.stderr or res.stdout).strip()


def gsettings_get(key):
    out = run("gsettings", "get", PRIVACY_GSCHEMA, key).strip()
    return out.split()[-1] if out else None


def weather_place():
    """What wttr.py asks wttr.in about: its LOCATION, as wttr.py itself
    works it out (Settings > Region's region.conf, or its default), by
    importing it in a child process -- the import fetches nothing, and this
    stays right whatever wttr.py reads the place from. "" means wttr.in
    goes by the internet address; None that wttr.py could not be read."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import wttr; "
            "print(repr(getattr(wttr, 'LOCATION', None)))")
    out = run(sys.executable, "-c", code, os.path.dirname(WTTR), timeout=5).strip()
    try:
        value = ast.literal_eval(out.splitlines()[-1]) if out else None
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


def indicator(kind):
    """The bar's privacy indicator for mic / camera / location: [app names]
    using it now, or None when the probe failed."""
    out = run(INDICATORS, kind, timeout=6).strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else None
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("class") == "error":
        return None
    if data.get("class") != "active":
        return []
    return [a for a in (data.get("alt") or "").split(",") if a] or ["an app"]


def open_classes():
    try:
        clients = json.loads(run("hyprctl", "clients", "-j", timeout=3) or "[]")
    except ValueError:
        return []
    return sorted({(c.get("class") or "").lower() for c in clients if c.get("class")})


def status():
    conf = load()
    units = unit_states([ACTIVITY_UNIT, *CLIP_UNITS])
    try:
        info = json.loads(run(sys.executable, ACTIVITY_LOG, "info", "--json") or "{}")
    except ValueError:
        info = {}
    act_state, act_file = units[ACTIVITY_UNIT]
    clip_conf = read(CLIPHIST_CONF)
    clip_items = None
    if any(units[u][0] == "active" for u in CLIP_UNITS) or os.path.exists(cliphist_db()):
        listing = run("cliphist", "list", timeout=8)
        clip_items = listing.count("\n")
    version = cliphist_version()
    try:
        nodes = json.loads(run("pw-dump", timeout=6) or "null")
    except ValueError:
        nodes = None
    remember = gsettings_get("remember-recent-files")
    age = gsettings_get("recent-files-max-age")
    alerts = {}
    try:
        alerts = json.loads(run(EMERGENCY, "config") or "{}")
    except ValueError:
        pass
    sent_place = alerts_sent_place()
    try:
        share_dnd = json.loads(run(NOTIFY, "get", "dnd_share", timeout=5) or "null")
    except ValueError:
        share_dnd = None
    return {
        "conf": CONF,
        "activity": {
            "service": act_state, "enabled": act_file == "enabled", "keep_days": keep_days(conf),
            "exclude": excluded(conf), "entries": info.get("entries"), "since": info.get("since"),
            "bytes": info.get("bytes"), "path": info.get("path")},
        "clipboard": {
            "services": {u: units[u][0] for u in CLIP_UNITS},
            "on": all(units[u][0] == "active" for u in CLIP_UNITS),
            "enabled": all(units[u][1] == "enabled" for u in CLIP_UNITS),
            "max_items": cliphist_max(clip_conf) or CLIP_DEFAULT, "items": clip_items,
            "db_bytes": size(cliphist_db()), "version": version,
            "skips_sensitive": version is not None and version_at_least(version, (0, 6))},
        "ask": {"on": ask_on(conf), "sources": {s: flag(conf.get(f"ask_{s}", "on")) for s in SOURCES},
                "index": flag(conf.get("ask_index", "on"))},
        "index": index_status(),
        "memory": memory_status(conf),
        "recent": {"on": remember == "true" if remember else None,
                   "max_age": int(age) if age and age.lstrip("-").isdigit() else None,
                   "items": xbel_count(read(RECENT)) if os.path.exists(RECENT) else 0, "path": RECENT},
        "live": {"screen": screen_shared(nodes), "mic": indicator("mic"), "camera": indicator("camera"),
                 "location": indicator("location"),
                 "share_dnd": share_dnd if isinstance(share_dnd, bool) else None},
        "location": {"weather": weather_place(),
                     "alerts": dict({k: alerts.get(k) for k in ("lat", "lon", "country")}, sent_place=sent_place)
                     if alerts else None},
        "presence": {"on": presence_on(conf), "service": unit_states([PRESENCE_UNIT])[PRESENCE_UNIT][0],
                     "gestures": gestures_on(conf), "gaze": gaze_on(conf)},
        "focus": {"watch": focus_watch_on(conf)},
        "windows": open_classes(),
    }


def memory_status(conf):
    """The memory switches, with desktop-memory.py status --json's counts
    and sizes under "store" (None when it did not answer)."""
    try:
        store = json.loads(run(sys.executable, DESKTOP_MEMORY, "status", "--json", timeout=15) or "null")
    except ValueError:
        store = None
    return {"on": memory_on(conf),
            "sources": {s: flag(conf.get(f"memory_{s}", DEFAULTS[f"memory_{s}"])) for s in MEMORY_SOURCES},
            "store": store if isinstance(store, dict) else None}


def index_status():
    """desktop-index.py status --json (counts and sizes only), None when it
    did not answer."""
    try:
        data = json.loads(run(sys.executable, DESKTOP_INDEX, "status", "--json", timeout=15) or "null")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def alerts_sent_place():
    """Who among the emergency-alerts sources that are on is sent your
    coordinates (SENDS_PLACE names), [] when none is, None when
    emergency-alerts.py did not answer."""
    try:
        data = json.loads(run(EMERGENCY, "sources", "--json") or "null")
        on = [s["id"] for s in data["sources"] if s.get("on")]
    except (ValueError, KeyError, TypeError):
        return None
    return [SENDS_PLACE[s] for s in on if s in SENDS_PLACE]


def cliphist_version():
    """cliphist's version ("0.7.0"), or None. `cliphist version` prints
    "version<TAB>0.7.0" and its paths -- to stderr."""
    try:
        res = subprocess.run(["cliphist", "version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^version\s+(\S+)", res.stdout + res.stderr, re.M)
    return m[1] if m else None


def cliphist_db():
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
    return os.path.join(cache, "cliphist", "db")


def size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def version_at_least(text, want):
    nums = tuple(int(n) for n in re.findall(r"\d+", text)[:len(want)])
    return nums >= want


# -- the commands -----------------------------------------------------------------
def number(text, lo, hi, what):
    try:
        n = int(text)
    except (TypeError, ValueError):
        sys.exit(f"privacy: {what} is a whole number, {lo}..{hi}")
    if not lo <= n <= hi:
        sys.exit(f"privacy: {what} goes from {lo} to {hi}")
    return n


def switch(units, on):
    ok, why = run_ok("systemctl", "--user", "enable" if on else "disable", "--now", *units)
    if not ok:
        sys.exit(f"privacy: systemctl failed: {why}")


def cmd_activity(args):
    what = args[0] if args else ""
    if what in ("on", "off"):
        switch([ACTIVITY_UNIT], what == "on")
    elif what == "keep" and len(args) > 1:
        set_key("activity_keep_days", str(number(args[1], *KEEP_RANGE, "days")))
        run(sys.executable, ACTIVITY_LOG, "prune")
    elif what in ("exclude", "include") and len(args) > 1:
        cls = clean_class(args[1])
        if not cls:
            sys.exit("privacy: which window class? (hyprctl clients shows them)")
        conf = load()
        classes = [c for c in excluded(conf) if c != cls] + ([cls] if what == "exclude" else [])
        conf["activity_exclude"] = ",".join(classes)
        save(conf)
        if what == "exclude":
            run(sys.executable, ACTIVITY_LOG, "hide", cls)
    elif what == "forget" and len(args) > 1 and args[1] in ("hour", "day", "all"):
        ok, why = run_ok(sys.executable, ACTIVITY_LOG, "forget", args[1])
        if not ok:
            sys.exit(f"privacy: {why}")
    else:
        sys.exit("privacy: activity on|off|keep <days>|exclude <class>|include <class>|forget hour|day|all")


def cmd_clipboard(args):
    what = args[0] if args else ""
    if what in ("on", "off"):
        switch(CLIP_UNITS, what == "on")
    elif what == "max" and len(args) > 1:
        n = number(args[1], *CLIP_RANGE, "the number of copies")
        os.makedirs(os.path.dirname(CLIPHIST_CONF), exist_ok=True)
        write_atomic(CLIPHIST_CONF, set_cliphist_max(read(CLIPHIST_CONF), n))
    elif what == "clear":
        ok, why = run_ok("cliphist", "wipe")
        if not ok:
            sys.exit(f"privacy: cliphist wipe failed: {why}")
    else:
        sys.exit("privacy: clipboard on|off|max <n>|clear")


def cmd_ask(args):
    if len(args) == 1 and args[0] in ("on", "off"):
        set_key("ask", args[0])
    elif len(args) == 2 and args[0] in (*SOURCES, "index") and args[1] in ("on", "off"):
        set_key(f"ask_{args[0]}", args[1])
    else:
        sys.exit("privacy: ask on|off, or ask files|clipboard|activity|index on|off")


def cmd_memory(args):
    what = args[0] if args else ""
    if len(args) == 1 and what in ("on", "off"):
        set_key("memory", what)
    elif len(args) == 2 and what in MEMORY_SOURCES and args[1] in ("on", "off"):
        set_key(f"memory_{what}", args[1])
    elif len(args) == 2 and what in ("keep", "screen-keep"):
        key = "memory_keep_days" if what == "keep" else "memory_screen_keep_days"
        set_key(key, str(number(args[1], *MEMORY_KEEP_RANGE, "days")))
        run(sys.executable, DESKTOP_MEMORY, "prune", timeout=60)
    elif len(args) == 2 and what == "every":
        set_key("memory_screen_minutes", str(number(args[1], *MEMORY_SCREEN_MINUTES, "minutes")))
    elif len(args) == 2 and what == "include":
        conf = load()
        conf["memory_exclude"] = ",".join(c for c in memory_excluded_own(conf) if c != clean_class(args[1]))
        save(conf)
    else:
        sys.exit("privacy: memory on|off, memory <source> on|off (" + "|".join(MEMORY_SOURCES)
                 + "), memory keep|screen-keep <days>, memory every <minutes>, memory include <class>")


def cmd_recent(args):
    what = args[0] if args else ""
    if what in ("on", "off"):
        ok, why = run_ok("gsettings", "set", PRIVACY_GSCHEMA, "remember-recent-files",
                         "true" if what == "on" else "false")
    elif what == "age" and len(args) > 1:
        days = -1 if args[1] in ("-1", "never", "forever") else number(args[1], 0, 3650, "days")
        ok, why = run_ok("gsettings", "set", PRIVACY_GSCHEMA, "recent-files-max-age", str(days))
    elif what == "clear":
        clear_recent()
        ok, why = True, ""
    else:
        sys.exit("privacy: recent on|off|age <days>|clear")
    if not ok:
        sys.exit(f"privacy: gsettings failed: {why}")


def cmd_presence(on):
    """presence=on|off, then the service follows: on starts it (it opens the
    camera only while an action needs it), off stops it -- the camera is
    released as it exits. The key is written first (the service reads it
    when it starts, and stops by itself within seconds of it going off);
    a failed start puts it back to off."""
    cmd_camera("presence", on)


def cmd_camera(key, on):
    """presence / gestures / gaze = on|off; the service runs while any of
    them is on (gestures.py works inside presence.py: one camera owner)."""
    set_key(key, "on" if on else "off")
    want = camera_wanted(load())
    ok, why = run_ok("systemctl", "--user", "enable" if want else "disable", "--now", PRESENCE_UNIT)
    if not ok:
        if on:
            set_key(key, "off")
        sys.exit(f"privacy: systemctl failed: {why}")


def cmd_camera_off():
    """presence, gestures and gaze off in one write, and the service stopped:
    nothing is left that may open the camera."""
    conf = load()
    for key in ("presence", "gestures", "gaze"):
        conf[key] = "off"
    save(conf)
    ok, why = run_ok("systemctl", "--user", "disable", "--now", PRESENCE_UNIT)
    if not ok:
        sys.exit(f"privacy: systemctl failed: {why}")


def clear_recent(path=None):
    """An empty list in place of recently-used.xbel (the apps that have it
    open watch the file and reload it). Nothing to do when there is none."""
    path = path or RECENT
    if os.path.exists(path):
        write_atomic(path, EMPTY_XBEL)


def human_status(data):
    a, c, k, r = data["activity"], data["clipboard"], data["ask"], data["recent"]
    since = (datetime.datetime.fromtimestamp(a["since"]).strftime("%Y-%m-%d %H:%M")
             if a.get("since") else "-")
    lines = [
        f"activity history  {a['service']}, {'enabled' if a['enabled'] else 'not enabled'} at login, "
        f"kept {a['keep_days']} days, {a.get('entries') or 0} entries since {since}",
        f"  private apps    keepassxc, private/incognito windows{', ' if a['exclude'] else ''}"
        + ", ".join(a["exclude"]),
        f"clipboard         {'recording' if c['on'] else 'off'}, keeps {c['max_items']}, "
        f"{c['items'] if c['items'] is not None else '?'} saved",
        f"ask your desktop  {'on' if k['on'] else 'off'}: "
        + ", ".join(f"{s} {'on' if v else 'off'}" for s, v in k["sources"].items())
        + f", search index {'on' if k.get('index', True) else 'off'}",
        f"recent files      {'remembered' if r['on'] else 'off'}, max age "
        f"{'forever' if r['max_age'] in (None, -1) else str(r['max_age']) + ' days'}, {r['items']} listed",
    ]
    m = data.get("memory")
    if m:
        lines.append(f"desktop memory    {'on' if m['on'] else 'off'}: "
                     + ", ".join(f"{s} {'on' if v else 'off'}" for s, v in m["sources"].items()))
    return "\n".join(lines)


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, args = argv[0], argv[1:]
    if cmd == "status":
        data = status()
        print(json.dumps(data, ensure_ascii=False) if "--json" in args else human_status(data))
    elif cmd == "activity":
        cmd_activity(args)
    elif cmd == "clipboard":
        cmd_clipboard(args)
    elif cmd == "ask":
        cmd_ask(args)
    elif cmd == "recent":
        cmd_recent(args)
    elif cmd == "memory":
        cmd_memory(args)
    elif cmd == "phone" and len(args) == 2 and args[0] == "codes" and args[1] in ("on", "off"):
        set_key("phone_codes", args[1])
    elif cmd == "phone" and len(args) == 2 and args[0] in ("ask", "screen") and args[1] in ("on", "off"):
        # phone-ask.py on|off also installs / removes the quick questions and the listener
        set_key("phone_ask" if args[0] == "ask" else "phone_ask_screen", args[1])
    elif cmd == "presence" and len(args) == 1 and args[0] in ("on", "off"):
        cmd_presence(args[0] == "on")
    elif cmd in ("gestures", "gaze") and len(args) == 1 and args[0] in ("on", "off"):
        cmd_camera(cmd, args[0] == "on")
    elif cmd == "camera" and args == ["off"]:
        cmd_camera_off()
    elif cmd == "assistant" and len(args) == 2 and args[0] == "memory" and args[1] in ("on", "off"):
        set_key("assistant_memory", args[1])
    elif cmd == "focus" and len(args) == 2 and args[0] == "watch" and args[1] in ("on", "off"):
        set_key("focus_watch", args[1])     # focus-guard.py re-reads privacy.conf on its next window
    elif cmd == "machines" and len(args) == 2 and args[0] in ("clipboard", "memory") and args[1] in ("on", "off"):
        set_key(f"machines_{args[0]}", args[1])     # peers.py reads it at each copy / question
    else:
        sys.exit(f"privacy: unknown command {cmd!r} (privacy_settings.py --help)")


if __name__ == "__main__":
    main(sys.argv[1:])
