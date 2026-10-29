#!/usr/bin/env python3
"""Ambient desktop: the desktop's look and sound follow the time of day, the
weather and what you are doing -- a little warmer and dimmer in the evening,
calmer and quieter in a focus block, the lights (if you have smart ones)
along with it. Subtle on purpose: nudges over YOUR choices, never new ones;
the whole theme only changes if you ask for that too.

    ambient.py daemon                 the service (ambient.service)
    ambient.py status [--json]        the settings, what it sees now, the
                                      plan, what is applied (Settings > Ambient)
    ambient.py plan [--json] [--mood M]   what it WOULD do now, nothing applied
                                      (M = day | relax | focus | night | away)
    ambient.py tick [--dry-run]       a pass now (asks the daemon, like poke);
                                      --dry-run: one here that says, changes nothing
    ambient.py poke                   ask the daemon for a pass now
    ambient.py set on|off|toggle      the master switch (enables / disables
                                      the service; off puts every output back)
    ambient.py set KEY VALUE          a setting (DEFAULTS below)
    ambient.py soundscape now|stop|toggle   play the soundscape now whatever the
                                      mood (until stop or the end of the
                                      session) / back to the mood's choice
    ambient.py sounds make [KIND...]  render the soundscape loops (ffmpeg)
    ambient.py sounds render KIND OUT [SECONDS]   a short one to a file (tests:
                                      nothing is played)
    ambient.py lights discover [--json]           Hue bridges and Home
                                      Assistant on the LAN (mDNS + SSDP; no cloud)
    ambient.py lights hue pair IP [--wait S]      pair with a bridge: press its
                                      round button, then this (it retries S s)
    ambient.py lights hue groups [--json]         the bridge's rooms / zones
    ambient.py lights ha url URL                  Home Assistant's local address
    ambient.py lights ha token -                  its long-lived token, from stdin
    ambient.py lights ha test | entities [--json] check it / its lights and scenes
    ambient.py lights scene MOOD [--dry-run]      set the lights to MOOD's scene now
    ambient.py lights forget hue|ha               drop the pairing / the token
    ambient.py veil                   (internal) the wallpaper veil, one layer
                                      surface per screen

INPUTS (read every TICK_S; nothing here watches the screen, the camera, the
microphone or the clipboard -- they are other features' outputs, each behind
its own switch):

    time      the night light's schedule (nightlight.conf, through
              theme-schedule.py's boundaries(): night = its window, the last
              part of it after midnight "late"), the theme schedule's evening
              when it has one, and the sun (sunset from wttr.py's cached
              answer): after sunset and before the night is the evening
    weather   wttr.py's cache ($XDG_RUNTIME_DIR/waybar-weather-raw.json; no
              request of its own): its kind, from the bar's own KINDS table
    focus     a focus block running (timers.py's focus round, which
              focus-guard.py runs); optionally Do Not Disturb counts too
    away      presence.py's answer (only when that is on), and -- a setting --
              the screen being locked
    gamemode  holds everything (stops the soundscape)

From them ONE mood, strongest first: away > focus > night > relax (the
evening) > day; plan() turns the mood (and the weather) into a value per
output, and the daemon applies only what changed.

OUTPUTS (each one a switch; the master switch is off as shipped):

    wallpaper    a veil over the wallpaper: one transparent, click-through
                 layer surface per screen (BOTTOM layer: over hyprpaper and a
                 moving wallpaper, under every window), a few % of a warm
                 colour in the evening, darker at night, a cool grey on a
                 grey day, darker in a focus block. Never on a screen whose
                 moving wallpaper (wallpaper-motion.py) already follows the
                 time and the weather on its own. Clear by day = no process
    accent       the accent's warmth: theme-from-wallpaper.py lays tinted()
                 over whichever accent won (the wallpaper's, yours, the
                 theme's), so the bar, mako and the window border move
                 together -- a few degrees of hue towards amber at night,
                 towards blue in a focus block ($XDG_RUNTIME_DIR/ambient-accent.conf)
    nightlight   its strength: a signed Kelvin nudge nightlight.sh adds to the
                 SCHEDULE's temperature (a SUPER+N override is never nudged):
                 warmer late at night, a little cooler in a focus block
                 ($XDG_RUNTIME_DIR/nightlight/ambient)
    animations   calmer animations in focus blocks and / or at night:
                 lua/ambient.lua, gentle (slower, no overshoot) or still
                 (fades only); back to your preset afterwards. Never in
                 gamemode ($XDG_RUNTIME_DIR/ambient-anim.conf)
    notify       the notification sound's volume (theme-sound.sh reads
                 $XDG_RUNTIME_DIR/ambient-sound.conf): quieter in a focus
                 block and at night
    soundscape   rain, a cafe, brown noise or a record crackling over the
                 rain (vinyl), rendered HERE with ffmpeg
                 (~/.local/share/ambient/sounds, nothing downloaded) and
                 played by mpv --no-video at a low volume, during focus blocks
                 (and in the evening, if you want); paused while music plays.
                 sound_kind "weather" is rain on a rainy day, brown otherwise;
                 "theme" is the current theme's own (THEME_SOUND: lofi's
                 vinyl, orbit's brown cabin hum), the weather rule for a theme without one
    theme        "theme follows ambience": the theme schedule's pick for the
                 part of the day, and a theme of your own for focus blocks.
                 Off as shipped: the other outputs never switch the theme
    lights       Philips Hue (the bridge's local HTTP API, paired with its
                 button) or Home Assistant (its local URL and a long-lived
                 token) -- a scene per mood (brightness + warmth, or a Home
                 Assistant scene of yours), set when the mood CHANGES, so a
                 light you change by hand stays until the next change; away
                 can mean lights off. Off as shipped

Every output has a dry run: `plan`, `tick --dry-run` and `lights scene MOOD
--dry-run` say exactly what would be written, run or sent (a token as ***),
and AMBIENT_DRY=1 in the environment makes everything a dry run (the tests).

LOCAL ONLY: the lights' addresses must resolve to the LAN (a private, loopback
or link-local address -- a cloud relay URL is refused), every request goes
out without any proxy, discovery is mDNS (avahi-browse) and SSDP, never
Signify's discovery service. The Hue bridge's certificate is self-signed by
Signify, so HTTPS to it is unverified (LAN only); HTTP is the fallback.

SECRETS: the Hue username and the Home Assistant token live in
$XDG_STATE_HOME/hypr/ambient-secrets.json, mode 0600, written only by this
script; they never reach argv (the token comes on stdin), the log, the
status JSON or a dry run.

Settings: $XDG_STATE_HOME/hypr/ambient.conf (key=value; DEFAULTS / LIMITS /
CHOICES; a bad line is its default). Live state for the page:
$XDG_RUNTIME_DIR/ambient.json. Logs: journalctl --user -u ambient.
"""
import colorsys
import datetime as dt
import importlib.util
import ipaddress
import json
import os
import re
import select
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desk_common  # noqa: E402  (run: a command with a timeout)
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
SELF = os.path.abspath(__file__)
HOME = os.path.expanduser("~")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "ambient")
SOUNDS = os.path.join(DATA, "sounds")
CONF = os.path.join(STATE_HOME, "hypr", "ambient.conf")
SECRETS = os.path.join(STATE_HOME, "hypr", "ambient-secrets.json")
DISPLAY_CONF = os.path.join(STATE_HOME, "hypr", "display.conf")
TIMERS_STATE = os.path.join(STATE_HOME, "hypr", "timers.json")
LIVE = os.path.join(RUNTIME, "ambient.json")
PIDFILE = os.path.join(RUNTIME, "ambient.pid")
NOW_FILE = os.path.join(RUNTIME, "ambient-soundscape-now")     # `soundscape now`
VEIL_FILE = os.path.join(RUNTIME, "ambient-veil.json")         # read by `veil`
ACCENT_FILE = os.path.join(RUNTIME, "ambient-accent.conf")     # read by tinted()
ANIM_FILE = os.path.join(RUNTIME, "ambient-anim.conf")         # read by lua/ambient.lua
SOUND_FILE = os.path.join(RUNTIME, "ambient-sound.conf")       # read by theme-sound.sh
NIGHTLIGHT_FILE = os.path.join(RUNTIME, "nightlight", "ambient")   # read by nightlight.sh
WEATHER_RAW = os.path.join(RUNTIME, "waybar-weather-raw.json")
PRESENCE_LIVE = os.path.join(RUNTIME, "presence-state.json")
WAYBAR_SCRIPTS = os.path.join(HOME, ".config", "waybar", "scripts")
NIGHTLIGHT = os.path.join(HERE, "nightlight.sh")
THEME = os.path.join(HERE, "theme.py")
ACCENT = os.path.join(HERE, "theme-from-wallpaper.py")
UNIT = "ambient.service"
APP = "Ambient"

TICK_S = 30
WEATHER_STALE_S = 3 * 3600      # wttr.py refreshes every 30 min; older than this = no weather
PRESENCE_STALE_S = 120
HTTP_TIMEOUT_S = 4
LATE_UNTIL = 5                  # the night after midnight, until 05:00, is "late"
MOODS = ("day", "relax", "focus", "night", "away")
SOUND_KINDS = ("rain", "cafe", "brown", "vinyl")
# sound_kind "theme": the soundscape a theme prefers (display.conf theme=);
# a theme not named here gets the "weather" rule.
THEME_SOUND = {"lofi": "vinyl", "orbit": "brown"}
DARK_WEATHER = {"cloud", "fog", "showers", "rain", "heavy", "storm"}
RAINY_WEATHER = {"showers", "rain", "heavy", "storm"}
OUTPUTS = ("wallpaper", "accent", "nightlight", "animations", "notify", "soundscape", "theme", "lights")

DEFAULTS = {
    "enabled": "off",
    "strength": "subtle",
    "wallpaper": "on", "accent": "on", "nightlight": "on", "animations": "on", "notify": "on",
    "soundscape": "off", "theme": "off",
    "anim_when": "both", "anim_style": "gentle",
    "vol_focus": "30", "vol_night": "40",
    "sound_kind": "rain", "sound_when": "focus", "sound_volume": "20", "sound_music": "pause",
    "focus_theme": "",
    "dnd_focus": "off", "away_lock": "on",
    "lights": "off", "lights_away": "on",
    "light_day": "80", "light_relax": "60", "light_focus": "100", "light_night": "25",
    "hue_bridge": "", "hue_group": "0",
    "ha_url": "", "ha_lights": "", "ha_scenes": "",
}
LIMITS = {"vol_focus": (0, 100), "vol_night": (0, 100), "sound_volume": (5, 60),
          "light_day": (1, 100), "light_relax": (1, 100), "light_focus": (1, 100), "light_night": (1, 100)}
SWITCHES = ("enabled", "wallpaper", "accent", "nightlight", "animations", "notify", "soundscape", "theme",
            "dnd_focus", "away_lock", "lights_away")
CHOICES = {"strength": ("subtle", "medium"), "anim_when": ("focus", "night", "both"),
           "anim_style": ("gentle", "still"), "sound_kind": SOUND_KINDS + ("weather", "theme"),
           "sound_when": ("focus", "relax"), "sound_music": ("pause", "keep"),
           "lights": ("off", "hue", "ha"), **{k: ("on", "off") for k in SWITCHES}}
STRENGTH = {"subtle": 1.0, "medium": 1.6}

# The veil per mood: (r, g, b, alpha at "subtle"). A clear day is no veil.
VEIL = {"relax": (255, 150, 70, 0.05), "night": (40, 20, 0, 0.16), "late": (30, 12, 0, 0.24),
        "focus": (0, 0, 0, 0.10), "grey": (30, 40, 60, 0.05)}
VEIL_MAX = 0.4
# The accent: warmth -1 (cool) .. +1 (warm) per mood; how far along the hue
# arc towards amber / blue that goes at "subtle".
WARMTH = {"day": 0.0, "grey": -0.3, "relax": 0.5, "night": 0.8, "late": 1.0, "focus": -0.4, "away": 0.0}
WARM_HUE, COOL_HUE = 0.08, 0.58     # amber, a sky blue
ACCENT_ARC = 0.12
BASE_ACCENT = "#00f0ff"             # the base stylesheets' own @cyan (a theme without accent=)
NIGHTLIGHT_NUDGE = {"focus": 400, "late": -400}     # K, at "subtle"
KELVIN = {"day": 4000, "relax": 2700, "focus": 5000, "night": 2200}

HUE_DEVICE = "hypr_desktop#ambient"   # the Hue bridge's devicetype (app#device, 40 chars max)
ENTITY = re.compile(r"(light|scene)\.[a-z0-9_]{1,64}$")
IPV4 = re.compile(r"\d{1,3}(\.\d{1,3}){3}$")


def log(text):
    print(f"ambient: {text}", file=sys.stderr, flush=True)


def dry_env():
    return os.environ.get("AMBIENT_DRY") == "1"


def _module(name, filename, folder=HERE):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(folder, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[name]
            raise
    return mod


def schedule():
    """theme-schedule.py: the night light's boundaries, the evening pick,
    the period (no GTK)."""
    return _module("theme_schedule", "theme-schedule.py")


# -- settings --------------------------------------------------------------------------------
def check_value(key, value, strict=True):
    """The value, cleaned, or raise ValueError. strict=False (reading the
    file back) skips the DNS lookup of ha_url -- http() checks it again at
    every request anyway, and a tick must not wait on mDNS."""
    value = str(value).strip()
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r}")
    if key in CHOICES:
        if value not in CHOICES[key]:
            raise ValueError(f"{key}: {' | '.join(CHOICES[key])}")
    elif key in LIMITS:
        lo, hi = LIMITS[key]
        if not re.fullmatch(r"\d{1,3}", value) or not lo <= int(value) <= hi:
            raise ValueError(f"{key}: {lo}-{hi}")
        value = str(int(value))
    elif key == "hue_bridge":
        if value and not (IPV4.fullmatch(value) and private_ip(value)):
            raise ValueError("hue_bridge: the bridge's LAN address, e.g. 192.168.1.20")
    elif key == "hue_group":
        if not re.fullmatch(r"\d{1,4}", value):
            raise ValueError("hue_group: a group number (0 = every light)")
    elif key == "ha_url":
        if value:
            value = check_url(value, resolve=None if strict else (lambda *_a: [(0, 0, 0, "", ("10.0.0.1", 0))]))
    elif key == "ha_lights":
        items = [x.strip() for x in value.split(",") if x.strip()]
        if any(not ENTITY.fullmatch(x) or not x.startswith("light.") for x in items):
            raise ValueError("ha_lights: light entity ids, comma-separated (light.desk, light.lamp)")
        value = ",".join(items)
    elif key == "ha_scenes":
        pairs = parse_scenes(value)
        value = ",".join(f"{m}={s}" for m, s in pairs.items())
    elif key == "focus_theme":
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", value):
            raise ValueError("focus_theme: a theme's folder name, or empty")
    return value


def parse_scenes(text):
    """"focus=scene.work, night=scene.sleep" -> {mood: scene}; raises on a bad pair."""
    out = {}
    for part in (p.strip() for p in str(text).split(",")):
        if not part:
            continue
        mood, _, scene = (x.strip() for x in part.partition("="))
        if mood not in MOODS or not ENTITY.fullmatch(scene) or not scene.startswith("scene."):
            raise ValueError("ha_scenes: mood=scene.id pairs, e.g. focus=scene.work, night=scene.sleep")
        out[mood] = scene
    return out


def read_settings(path=None):
    out = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if not sep or key.startswith("#"):
                    continue
                try:
                    out[key.strip()] = check_value(key.strip(), value, strict=False)
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def write_setting(key, value, path=None):
    path = path or CONF
    value = check_value(key, value)
    values = read_settings(path)
    values[key] = value
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write("# ambient.py's settings (Settings > Ambient); a missing key is its default\n")
        handle.writelines(f"{k}={v}\n" for k, v in values.items() if v != DEFAULTS[k])
    os.replace(tmp, path)
    return value


def on(values, key):
    return values.get(key) == "on"


# -- secrets (0600, never logged) ----------------------------------------------------------------
def read_secrets(path=None):
    try:
        with open(path or SECRETS) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_secret(key, value, path=None):
    path = path or SECRETS
    data = read_secrets(path)
    if value:
        data[key] = value
    else:
        data.pop(key, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def redact(text, secrets=None):
    """Any secret that might be in `text`, as ***."""
    for value in (secrets if secrets is not None else read_secrets()).values():
        if isinstance(value, str) and len(value) >= 6:
            text = text.replace(value, "***")
    return text


# -- local only ------------------------------------------------------------------------------
def private_ip(addr):
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local) and not ip.is_multicast


def resolves_local(host, resolve=None):
    """Every address `host` resolves to is on the LAN (or it IS a LAN address)."""
    if private_ip(host.strip("[]")):
        return True
    try:
        infos = (resolve or socket.getaddrinfo)(host, None)
    except (OSError, UnicodeError):
        return False
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(private_ip(a) for a in addrs)


def check_url(value, resolve=None):
    """Home Assistant's address: http(s)://host[:port], a LAN host only."""
    value = value.strip().rstrip("/")
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/") \
            or parts.query or parts.username:
        raise ValueError("ha_url: http://homeassistant.local:8123 or http://192.168.1.10:8123")
    if not resolves_local(parts.hostname, resolve):
        raise ValueError("ha_url: that address is not on your network (local only: no cloud relay)")
    return value


NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DRY_LOG = []        # what a dry run would have sent: (method, url, body)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header
    (the Home Assistant token) to wherever a 3xx points -- off the LAN too,
    past the local-only check. A 3xx comes back as its status instead."""
    def redirect_request(self, *_args, **_kwargs):
        return None


def http(method, url, body=None, headers=None, insecure=False, dry=False, opener=None):
    """(status, parsed JSON or None). LAN only (checked here again), no proxy;
    `insecure` = an unverified TLS context (the Hue bridge's own cert). A dry
    run records the request and sends nothing."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if not resolves_local(host):
        raise ValueError(f"refusing a non-local address: {host}")
    data = json.dumps(body).encode() if body is not None else None
    if dry or dry_env():
        DRY_LOG.append((method, url, body))
        return 0, None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json",
                                                                         **(headers or {})})
    handlers = [urllib.request.ProxyHandler({}), NoRedirect()]
    if insecure and url.startswith("https:"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = opener or urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read(2_000_000)
            status = resp.status
    except urllib.error.HTTPError as exc:
        with exc:
            raw, status = exc.read(200_000), exc.code
    try:
        return status, json.loads(raw or b"null")
    except ValueError:
        return status, None


# -- inputs ----------------------------------------------------------------------------------
def _json(path, max_age=None, now=None):
    try:
        if max_age is not None and (now or time.time()) - os.path.getmtime(path) > max_age:
            return None
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def weather_kinds():
    try:
        sys.path.insert(0, WAYBAR_SCRIPTS)
        from wttr import KINDS          # the bar's own table, so both agree
        return KINDS
    except Exception:  # noqa: BLE001 -- the bar's module failing must not stop this
        return {}
    finally:
        if sys.path and sys.path[0] == WAYBAR_SCRIPTS:
            sys.path.pop(0)


def weather(data, kinds=None):
    """(kind, sunrise, sunset) from wttr.py's answer; sunrise / sunset as
    datetime.time or None."""
    try:
        code = int(data["current_condition"][0]["weatherCode"])
    except (TypeError, KeyError, IndexError, ValueError):
        return None, None, None
    kinds = kinds if kinds is not None else weather_kinds()
    kind = next((k for k, codes in kinds.items() if code in codes), "cloud")
    rise = down = None
    try:
        astro = data["weather"][0]["astronomy"][0]
        rise = dt.datetime.strptime(astro["sunrise"].strip(), "%I:%M %p").time()
        down = dt.datetime.strptime(astro["sunset"].strip(), "%I:%M %p").time()
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        pass
    return kind, rise, down


def part_of_day(now, night_start, night_end, evening_from=None, sunset=None):
    """day | evening | night | late. night = the night light's window; late =
    the part of it from midnight to LATE_UNTIL; evening = from the earlier of
    sunset and the theme schedule's evening until the night."""
    minutes = now.hour * 60 + now.minute
    s, e = night_start[0] * 60 + night_start[1], night_end[0] * 60 + night_end[1]
    in_night = (s <= minutes < e) if s < e else (minutes >= s or minutes < e)
    if in_night:
        return "late" if minutes < LATE_UNTIL * 60 else "night"
    starts = [t for t in (evening_from, sunset) if t is not None]
    if starts:
        begin = min(h * 60 + m for h, m in ((t.hour, t.minute) if isinstance(t, dt.time) else t for t in starts))
        if begin <= minutes < (s if s > begin else 24 * 60):
            return "evening"
    return "day"


def focus_running(now=None, path=None):
    now = now or time.time()
    data = _json(path or TIMERS_STATE) or {}
    return any(t.get("kind") == "focus" and t.get("due", 0) > now for t in data.get("timers") or []
               if isinstance(t, dict))


def run(*cmd, timeout=3):
    """The CompletedProcess, None when it could not run or timed out."""
    return desk_common.run(cmd, timeout=timeout)


def dnd_on():
    out = run("makoctl", "mode")
    return bool(out and "do-not-disturb" in out.stdout.split())


def gamemode_on():
    out = run("hyprctl", "getoption", "animations:enabled", "-j")
    try:
        answer = json.loads(out.stdout) if out else None
    except ValueError:
        return False
    return isinstance(answer, dict) and (answer.get("bool") is False or answer.get("int") == 0)


def process_running(name, proc="/proc"):
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm")) as handle:
                if handle.read().strip() == name:
                    return True
        except OSError:
            pass
    return False


def music_playing():
    out = run("playerctl", "-a", "status")
    return bool(out and "Playing" in out.stdout.split())


def observe(now=None, values=None):
    """Everything plan() needs, read now."""
    values = values or read_settings()
    now = now or dt.datetime.now()
    sched = schedule()
    try:
        night_start, night_end = sched.boundaries()
    except Exception:  # noqa: BLE001
        night_start, night_end = (20, 0), (7, 0)
    evening = None
    try:
        p = sched.picks()
        if p.get("evening"):
            evening = sched.evening_start()
    except Exception:  # noqa: BLE001
        pass
    kind, _rise, sunset = weather(_json(WEATHER_RAW, WEATHER_STALE_S))
    presence = _json(PRESENCE_LIVE, PRESENCE_STALE_S) or {}
    away = presence.get("state") == "away"
    locked = process_running("hyprlock")
    dnd = dnd_on()
    return {"part": part_of_day(now, night_start, night_end, evening, sunset),
            "weather": kind, "theme": current_theme(), "focus": focus_running(), "dnd": dnd,
            "away": away or (locked and on(values, "away_lock")), "locked": locked,
            "presence": presence.get("state") or "", "gamemode": gamemode_on(),
            "music": (on(values, "soundscape") or os.path.exists(NOW_FILE)) and values["sound_music"] == "pause"
            and music_playing(),
            "soundscape_now": os.path.exists(NOW_FILE)}


def current_theme():
    """display.conf's theme= (the theme the desktop is in), or "" without one."""
    try:
        with open(DISPLAY_CONF) as handle:
            for line in handle:
                key, _, value = line.partition("=")
                if key.strip() == "theme":
                    return value.strip()
    except OSError:
        pass
    return ""


def mood_of(inputs, values):
    """(mood, why)."""
    if inputs.get("away"):
        return "away", "you are away" if inputs.get("presence") == "away" else "the screen is locked"
    if inputs.get("focus"):
        return "focus", "a focus block is running"
    if inputs.get("dnd") and on(values, "dnd_focus"):
        return "focus", "Do Not Disturb is on"
    part = inputs.get("part")
    if part in ("night", "late"):
        return "night", "late at night" if part == "late" else "the night light's hours"
    if part == "evening":
        return "relax", "the evening"
    return "day", "the day"


# -- the plan --------------------------------------------------------------------------------
def look_key(mood, inputs):
    """Which row of VEIL / WARMTH: the mood, with night split into late, and
    a grey day (dark weather) as its own."""
    if mood == "night" and inputs.get("part") == "late":
        return "late"
    if mood == "day" and inputs.get("weather") in DARK_WEATHER:
        return "grey"
    if mood == "away":
        return {"late": "late", "night": "night", "evening": "relax"}.get(inputs.get("part"), "day")
    return mood


def plan(inputs, values, mood=None, themes=None):
    """{output: value or None}: None = this output is off (leave it / put
    it back). Pure: the tests drive it."""
    mood, why = (mood, "previewing") if mood else mood_of(inputs, values)
    k = STRENGTH.get(values["strength"], 1.0)
    key = look_key(mood, inputs)
    out = {"mood": mood, "why": why}

    if on(values, "wallpaper"):
        r, g, b, a = VEIL.get(key, (0, 0, 0, 0.0))
        out["wallpaper"] = [r, g, b, round(min(VEIL_MAX, a * k), 3)]
    if on(values, "accent"):
        out["accent"] = round(max(-1.0, min(1.0, WARMTH.get(key, 0.0))), 2)
    if on(values, "nightlight"):
        nudge = NIGHTLIGHT_NUDGE.get("late" if key == "late" else mood, 0)
        out["nightlight"] = int(round(nudge * k / 50.0) * 50)
    if on(values, "animations"):
        when = values["anim_when"]
        calm = (mood == "focus" and when in ("focus", "both")) or (mood == "night" and when in ("night", "both"))
        out["animations"] = (2 if values["anim_style"] == "still" else 1) if calm else 0
    if on(values, "notify"):
        out["notify"] = int(values["vol_focus"]) if mood == "focus" else \
            int(values["vol_night"]) if mood == "night" else 100
    if on(values, "soundscape") or inputs.get("soundscape_now"):
        wanted = inputs.get("soundscape_now") or mood == "focus" or (mood == "relax" and values["sound_when"] == "relax")
        held = inputs.get("gamemode") or mood == "away" or \
            (inputs.get("music") and values["sound_music"] == "pause")
        kind = values["sound_kind"]
        if kind == "theme":
            kind = THEME_SOUND.get(inputs.get("theme") or "", "weather")
        if kind == "weather":
            kind = "rain" if inputs.get("weather") in RAINY_WEATHER else "brown"
        out["soundscape"] = {"kind": kind, "volume": int(values["sound_volume"])} if wanted and not held else ""
    if on(values, "theme"):
        out["theme"] = theme_for(mood, inputs, values, themes)
    if values["lights"] != "off":
        out["lights"] = scene_for(mood, inputs, values)
    return out


def theme_for(mood, inputs, values, themes=None):
    """The theme to be in, or "" for "leave it": the focus theme in a block,
    else the theme schedule's pick for the part of the day."""
    if mood == "away":
        return ""
    if mood == "focus" and values["focus_theme"]:
        return values["focus_theme"] if themes is None or values["focus_theme"] in themes else ""
    try:
        picks = schedule().picks()
    except Exception:  # noqa: BLE001
        return ""
    part = {"late": "night", "night": "night", "evening": "evening"}.get(inputs.get("part"), "day")
    pick = picks.get(part) or (picks.get("day") if part == "evening" else "")
    return "" if pick in ("", "random") else pick


def scene_for(mood, inputs, values):
    """{"on": bool, "bri": %, "kelvin": K, "scene": HA scene or ""}, or None
    for "leave the lights alone"."""
    if mood == "away":
        return {"on": False} if on(values, "lights_away") else None
    scenes = {}
    try:
        scenes = parse_scenes(values.get("ha_scenes", ""))
    except ValueError:
        pass
    bri = int(values.get(f"light_{mood}", DEFAULTS.get(f"light_{mood}", "80")))
    if mood == "day" and inputs.get("weather") in DARK_WEATHER:
        bri = min(100, bri + 10)            # a grey day: a little more light
    return {"on": True, "bri": bri, "kelvin": KELVIN.get(mood, 4000), "scene": scenes.get(mood, "")}


def describe(p):
    """The plan as lines for people (the page, `plan`)."""
    lines = [f"mood: {p['mood']} ({p['why']})"]
    if "wallpaper" in p:
        r, g, b, a = p["wallpaper"]
        lines.append(f"wallpaper: clear" if a <= 0 else f"wallpaper: veil #{r:02x}{g:02x}{b:02x} at {a:.0%}")
    if "accent" in p:
        w = p["accent"]
        lines.append("accent: as it is" if not w else f"accent: {'warmer' if w > 0 else 'cooler'} ({w:+.1f})")
    if "nightlight" in p:
        n = p["nightlight"]
        lines.append("night light: as scheduled" if not n else f"night light: {n:+d} K when it is on")
    if "animations" in p:
        lines.append(("animations: your preset", "animations: gentler", "animations: fades only")[p["animations"]])
    if "notify" in p:
        lines.append(f"notification sound: {p['notify']}%")
    if "soundscape" in p:
        s = p["soundscape"]
        lines.append(f"soundscape: {s['kind']} at {s['volume']}%" if s else "soundscape: silent")
    if "theme" in p:
        lines.append(f"theme: {p['theme']}" if p["theme"] else "theme: left alone")
    if "lights" in p:
        s = p["lights"]
        lines.append("lights: left alone" if s is None else "lights: off" if not s.get("on") else
                     f"lights: {s['scene']}" if s.get("scene") else f"lights: {s['bri']}% at {s['kelvin']} K")
    return lines


# -- outputs: the small ones (files the others read) ---------------------------------------------
def write_file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def tinted(accent, path=None):
    """`accent` (#rrggbb) with the ambient warmth laid over it -- what
    theme-from-wallpaper.py writes. Unchanged when ambient's accent is off."""
    try:
        with open(path or ACCENT_FILE) as handle:
            kv = dict(line.strip().split("=", 1) for line in handle if "=" in line)
        warmth, arc = float(kv.get("warmth", 0)), float(kv.get("arc", ACCENT_ARC))
    except (OSError, ValueError):
        return accent
    if not warmth or not accent or not re.fullmatch(r"#[0-9a-fA-F]{6}", accent or ""):
        return accent
    r, g, b = (int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    f = min(1.0, abs(warmth)) * arc
    target = WARM_HUE if warmth > 0 else COOL_HUE
    d = ((target - h + 0.5) % 1.0) - 0.5          # the short way round
    h = (h + d * f) % 1.0 if s > 0.05 else h       # subtle: at most ~13 degrees
    if warmth > 0:
        v *= 1 - 0.5 * f                          # a little dimmer when warm
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


class Applier:
    """Applies a plan, output by output, only what changed since the last
    time. dry=True: say it, do nothing. Each step appends a line to
    self.done; errors go to self.errors (no secret in either)."""

    def __init__(self, dry=False):
        self.dry = dry or dry_env()
        self.applied = {}
        self.veil = None            # Popen of `ambient.py veil`
        self.sound = None           # Popen of mpv
        self.sound_key = None
        self.done, self.errors = [], []

    def say(self, text):
        self.done.append(("DRY " if self.dry else "") + text)

    def cmd(self, *argv):
        self.say("run " + " ".join(os.path.basename(a) if a.startswith(HERE) else a for a in argv))
        if not self.dry:
            out = run(*argv, timeout=30)
            if out is None or out.returncode != 0:
                self.errors.append(f"{os.path.basename(argv[0])} failed")

    def apply(self, p, values, hold=False):
        """hold (gamemode): only stop the soundscape; leave the rest."""
        self.done, self.errors = [], []
        if hold:
            self.soundscape("")
            return self.done
        if self.applied.get("strength", values.get("strength")) != values.get("strength"):
            self.applied.pop("accent", None)        # the same warmth, a new arc: tint again
        self.applied["strength"] = values.get("strength")
        for name in OUTPUTS:
            want = p.get(name)
            if name not in p:
                want = None             # off: put it back
            if name == "lights":
                # only on a mood CHANGE (a light changed by hand stays); a
                # failed send is tried again next pass
                if want is not None and self.applied.get("lights_mood") != p["mood"] and self.lights(want, values):
                    self.applied["lights_mood"] = p["mood"]
                continue
            if name != "soundscape" and self.applied.get(name, "unset") == want:
                continue            # the soundscape keeps its own (and restarts a dead mpv)
            getattr(self, name)(want)
            self.applied[name] = want
        return self.done

    # each output: want None = off / back to normal
    def wallpaper(self, want):
        a = want[3] if want else 0
        if a <= 0:
            if self.veil or self.applied.get("wallpaper"):
                self.say("wallpaper veil: off")
            self.stop_veil()
            return
        if self.dry:
            self.say(f"wallpaper veil: rgba{tuple(want)}")
            return
        write_file(VEIL_FILE, json.dumps({"rgba": want}))
        if self.veil and self.veil.poll() is None:
            self.say(f"wallpaper veil: rgba{tuple(want)}")
            self.veil.send_signal(signal.SIGUSR1)
            return
        self.veil_skip = motion_outputs()
        mons = monitor_names()
        if mons and not set(mons) - self.veil_skip:
            self.say("wallpaper veil: none needed (every screen's moving wallpaper follows the light itself)")
            return
        self.say(f"wallpaper veil: rgba{tuple(want)}")
        self.veil = subprocess.Popen([sys.executable, SELF, "veil"])

    def check_veil(self):
        """Each pass while a veil is up: a moving wallpaper started or
        stopped (a theme switch) -> a new veil with the right screens."""
        want = self.applied.get("wallpaper")
        if self.dry or not want or want[3] <= 0:
            return
        if self.veil and self.veil.poll() is not None:
            self.veil = None
            self.applied.pop("wallpaper", None)          # it died: start it again this pass
        elif motion_outputs() != getattr(self, "veil_skip", set()):
            self.stop_veil()
            self.applied.pop("wallpaper", None)

    def stop_veil(self):
        if self.dry:
            return
        if self.veil and self.veil.poll() is None:
            self.veil.terminate()
            try:
                self.veil.wait(3)
            except subprocess.TimeoutExpired:
                self.veil.kill()
        self.veil = None
        remove(VEIL_FILE)

    def accent(self, want):
        self.say(f"accent warmth: {want or 0:+.2f}")
        if self.dry:
            self.say("run theme-from-wallpaper.py refresh")
            return
        if want:
            write_file(ACCENT_FILE, f"# ambient.py: theme-from-wallpaper.py tints the accent by this\n"
                                    f"warmth={want}\narc={ACCENT_ARC * STRENGTH.get(read_settings()['strength'], 1):.3f}\n")
        else:
            remove(ACCENT_FILE)
        self.cmd(sys.executable, ACCENT, "refresh")

    def nightlight(self, want):
        self.say(f"night light nudge: {want or 0:+d} K")
        if not self.dry:
            if want:
                write_file(NIGHTLIGHT_FILE, f"{int(want)}\n")
            else:
                remove(NIGHTLIGHT_FILE)
        self.cmd(NIGHTLIGHT, "auto")

    def animations(self, want):
        level = int(want or 0)
        last = self.applied.get("animations")
        if level == 0 and not last and anim_level() == 0:
            return                  # never calmed in this Lua state: nothing to undo
        if level != last:
            self.say(f"animations: level {level}")
        if self.dry:
            return
        write_file(ANIM_FILE, f"# ambient.py: lua/ambient.lua (0 = your preset)\nlevel={level}\n")
        out = run("hyprctl", "eval", 'require("lua.ambient").apply()')
        if out is None or out.returncode != 0:
            self.errors.append("hyprctl eval lua.ambient failed")

    def notify(self, want):
        self.say(f"notification sound: {want if want is not None else 100}%")
        if self.dry:
            return
        if want is None or want >= 100:
            remove(SOUND_FILE)
        else:
            write_file(SOUND_FILE, f"# ambient.py: theme-sound.sh plays notifications at this volume\nvolume={int(want)}\n")

    def soundscape(self, want):
        key = (want["kind"], want["volume"]) if want else None
        if key == self.sound_key and (not key or (self.sound and self.sound.poll() is None) or self.dry):
            return
        if self.sound and self.sound.poll() is None:
            self.sound.terminate()
            try:
                self.sound.wait(3)
            except subprocess.TimeoutExpired:
                self.sound.kill()
        self.sound, self.sound_key = None, key
        if not want:
            self.say("soundscape: stop")
            return
        path = sound_path(want["kind"])
        self.say(f"soundscape: {want['kind']} at {want['volume']}%")
        if self.dry:
            return
        if not os.path.exists(path) and not make_sound(want["kind"]):
            self.errors.append(f"could not render the {want['kind']} soundscape (ffmpeg)")
            return
        self.sound = subprocess.Popen(mpv_argv(path, want["volume"]), stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)

    def theme(self, want):
        if not want:
            return
        current = run(sys.executable, THEME, "current")
        if current is not None and current.stdout.strip() == want:
            return
        self.cmd(sys.executable, THEME, "set", want)

    def lights(self, want, values):
        try:
            for line in lights_apply(want, values, dry=self.dry):
                self.say(line)
            return True
        except (OSError, ValueError, urllib.error.URLError) as exc:
            self.errors.append(redact(f"lights: {exc}"))
            return False

    def reset(self):
        """Everything back to normal (the master switch off, the service
        stopping). The lights stay as they are."""
        p = {"mood": "day", "why": "off"}
        self.apply(p, read_settings())
        self.stop_veil()
        self.soundscape("")


def anim_level(path=None):
    try:
        with open(path or ANIM_FILE) as handle:
            m = re.search(r"^level=(\d)$", handle.read(), re.M)
        return int(m[1]) if m else 0
    except OSError:
        return 0


def mpv_argv(path, volume):
    # --no-config: none of your mpv.conf (its skin, MPRIS scripts, a
    # resume-playback file); a fixed client name for the volume mixer.
    return ["mpv", "--no-config", "--no-video", "--no-terminal", "--really-quiet", "--loop-file=inf",
            "--audio-client-name=Ambient soundscape", f"--volume={int(volume)}", "--", path]


# -- the soundscapes (rendered here, nothing downloaded) ---------------------------------------
SOUND_SECONDS = 120
LOOP_XFADE_S = 4
# One noise source per recipe -> a mono filter chain (anoisesrc colours:
# brown = a deep rumble, pink = rain's hiss). Rendered a little longer than
# the loop, and the end cross-faded into the start (equal power), so mpv's
# --loop-file has no seam to hear.
RECIPES = {
    "brown": ("anoisesrc=color=brown:sample_rate=48000:amplitude=0.9:seed=7:d={d}",
              "lowpass=f=700,volume=2.2"),
    "rain": ("anoisesrc=color=pink:sample_rate=48000:amplitude=0.7:seed=11:d={d}",
             "highpass=f=350,lowpass=f=8000,tremolo=f=0.13:d=0.18,"
             "aecho=0.6:0.4:43|71:0.25|0.18,volume=1.4"),
    # the rain again, a little quieter, under VINYL_EXTRA's crackle
    "vinyl": ("anoisesrc=color=pink:sample_rate=48000:amplitude=0.7:seed=11:d={d}",
              "highpass=f=350,lowpass=f=8000,tremolo=f=0.13:d=0.18,"
              "aecho=0.6:0.4:43|71:0.25|0.18,volume=1.4,volume=0.9"),
    # A room murmur: brown rumble, two bands of pink noise pulsing at speech's
    # syllable rate, and now and then a cup (two short decaying sines).
    "cafe": ("anoisesrc=color=pink:sample_rate=48000:amplitude=0.6:seed=5:d={d}",
             "bandpass=f=900:width_type=h:w=1400,tremolo=f=4.1:d=0.55,tremolo=f=0.7:d=0.3,volume=1.2"),
}
CAFE_EXTRA = ("anoisesrc=color=brown:sample_rate=48000:amplitude=0.6:seed=9:d={d},lowpass=f=500,volume=1.5[room];"
              "aevalsrc='0.12*sin(2*PI*3150*t)*exp(-38*mod(t,7.3))*lt(mod(t,7.3),0.2)"
              "+0.08*sin(2*PI*2420*t)*exp(-30*mod(t+2.9,11.7))*lt(mod(t+2.9,11.7),0.25)'"
              ":s=48000:d={d}[cups];")
# A record over the rain: the rain chain a little quieter (RECIPES "vinyl"),
# and the crackle -- a sparse random tick (about 34 a second, each one sample
# of random size and sign), kept out of the rumble and the hiss by a band
# 1.2-6 kHz, and swelling a touch once a turn: 0.555 Hz is 33 1/3 rpm.
VINYL_EXTRA = ("aevalsrc='0.5*gt(random(0),0.9993)*(random(1)-0.5)':s=48000:d={d},"
               "highpass=f=1200,lowpass=f=6000,tremolo=f=0.555:d=0.08[crackle];")


def sound_path(kind):
    return os.path.join(SOUNDS, f"{kind}.ogg")


def sound_graph(kind, seconds):
    """The ffmpeg -filter_complex for `kind`, `seconds` long and seamless."""
    total, x = seconds + LOOP_XFADE_S, LOOP_XFADE_S
    src, chain = RECIPES[kind]
    head = f"{src.format(d=total)},{chain}"
    if kind == "cafe":
        head = (CAFE_EXTRA.format(d=total) + f"{src.format(d=total)},{chain}[talk];"
                "[talk][room][cups]amix=inputs=3:normalize=0")
    elif kind == "vinyl":
        head = (VINYL_EXTRA.format(d=total) + f"{src.format(d=total)},{chain}[rain];"
                "[rain][crackle]amix=inputs=2:normalize=0")
    # loudnorm: every kind at the same loudness (-26 LUFS), so the volume
    # slider means the same for each; then back to 48 kHz (loudnorm works at 192).
    return (f"{head},loudnorm=I=-26:TP=-6:LRA=11,aresample=48000,asplit=3[a][b][c];"
            f"[a]atrim=0:{x},asetpts=PTS-STARTPTS,afade=t=in:d={x}:curve=qsin[h];"
            f"[b]atrim={seconds}:{total},asetpts=PTS-STARTPTS,afade=t=out:d={x}:curve=qsin[t];"
            f"[h][t]amix=inputs=2:normalize=0[j];"
            f"[c]atrim={x}:{seconds},asetpts=PTS-STARTPTS[m];"
            f"[j][m]concat=n=2:v=0:a=1,aformat=channel_layouts=stereo[out]")


def make_sound(kind, out=None, seconds=SOUND_SECONDS):
    if kind not in RECIPES or not shutil.which("ffmpeg"):
        return False
    out = out or sound_path(kind)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = f"{out}.{os.getpid()}.part.ogg"
    res = run("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
              "-filter_complex", sound_graph(kind, seconds), "-map", "[out]",
              "-c:a", "libopus", "-b:a", "64k", tmp, timeout=300)
    if res is None or res.returncode != 0 or not os.path.exists(tmp):
        remove(tmp)
        return False
    os.replace(tmp, out)
    return True


# -- lights ------------------------------------------------------------------------------------
def hue_base(values, secrets):
    ip, user = values.get("hue_bridge"), secrets.get("hue_user")
    if not ip or not user:
        raise ValueError("Hue is not paired (Settings > Ambient > Smart lights)")
    return ip, user


def hue_request(method, ip, path, body=None, dry=False):
    """The bridge's v1 API: HTTPS (its self-signed cert, unverified -- LAN
    only), HTTP if that fails."""
    last = None
    for scheme in ("https", "http"):
        try:
            return http(method, f"{scheme}://{ip}{path}", body, insecure=True, dry=dry)
        except (OSError, urllib.error.URLError) as exc:
            last = exc
    raise last


def hue_body(scene):
    if not scene.get("on"):
        return {"on": False, "transitiontime": 20}
    mirek = max(153, min(500, round(1_000_000 / scene["kelvin"])))
    return {"on": True, "bri": max(1, min(254, round(scene["bri"] * 2.54))), "ct": mirek, "transitiontime": 20}


def ha_calls(scene, values):
    """[(service path, body)] for Home Assistant."""
    if scene.get("scene"):
        return [("/api/services/scene/turn_on", {"entity_id": scene["scene"]})]
    lights = [x for x in values.get("ha_lights", "").split(",") if x]
    if not lights:
        raise ValueError("Home Assistant: no lights chosen (Settings > Ambient > Smart lights)")
    if not scene.get("on"):
        return [("/api/services/light/turn_off", {"entity_id": lights, "transition": 2})]
    return [("/api/services/light/turn_on", {"entity_id": lights, "brightness_pct": scene["bri"],
                                              "color_temp_kelvin": scene["kelvin"], "transition": 2})]


def lights_apply(scene, values, dry=False, secrets=None):
    """Send one scene to the provider; yields a line per request."""
    secrets = secrets if secrets is not None else read_secrets()
    provider = values.get("lights")
    if provider == "hue":
        ip, user = hue_base(values, secrets)
        status, answer = hue_request("PUT", ip, f"/api/{user}/groups/{values.get('hue_group', '0')}/action",
                                     hue_body(scene), dry=dry)
        if not dry and not dry_env() and (status != 200 or (isinstance(answer, list) and
                                                            any("error" in a for a in answer))):
            raise ValueError(f"the Hue bridge said {status}")
        yield f"{'DRY ' if dry or dry_env() else ''}hue {ip} group {values.get('hue_group', '0')}: " + \
            json.dumps(hue_body(scene))
    elif provider == "ha":
        url, token = values.get("ha_url"), secrets.get("ha_token")
        if not url or not token:
            raise ValueError("Home Assistant needs its address and a token (Settings > Ambient)")
        for path, body in ha_calls(scene, values):
            status, _ = http("POST", url + path, body, headers={"Authorization": f"Bearer {token}"}, dry=dry)
            if not dry and not dry_env() and status not in (200, 201):
                raise ValueError(f"Home Assistant said {status} for {path}")
            yield f"{'DRY ' if dry or dry_env() else ''}home assistant {path}: {json.dumps(body)}"


def hue_pair(ip, wait=30, sleep=time.sleep, clock=time.monotonic):
    """The username, once the bridge's button has been pressed (it answers
    error 101 until then). Raises on anything else."""
    if not (IPV4.fullmatch(ip) and private_ip(ip)):
        raise ValueError("a LAN address, e.g. 192.168.1.20")
    end = clock() + wait
    while True:
        status, answer = hue_request("POST", ip, "/api", {"devicetype": HUE_DEVICE})
        item = answer[0] if isinstance(answer, list) and answer else {}
        if "success" in item and item["success"].get("username"):
            return item["success"]["username"]
        err = (item.get("error") or {})
        if err.get("type") != 101:
            raise ValueError(f"the bridge said: {err.get('description') or status}")
        if clock() >= end:
            raise TimeoutError("the bridge's button was not pressed in time")
        sleep(2)


def avahi(service, timeout=6):
    """[(name, address, port, txt)] from avahi-browse (mDNS on the LAN)."""
    out = run("avahi-browse", "-rpt", "-k", service, timeout=timeout)
    found = []
    for line in (out.stdout if out else "").splitlines():
        f = line.split(";")
        if len(f) >= 10 and f[0] == "=" and f[2] == "IPv4" and private_ip(f[7]):
            found.append((f[3].replace("\\032", " "), f[7], int(f[8] or 0), f[9]))
    return found


def ssdp_hue(timeout=3.0):
    """Hue bridges answering an SSDP M-SEARCH (the bridges say IpBridge /
    hue-bridgeid in their reply)."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
           "MX: 2\r\nST: ssdp:all\r\n\r\n").encode()
    found = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        sock.sendto(msg, ("239.255.255.250", 1900))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, (addr, _port) = sock.recvfrom(2048)
            except socket.timeout:
                continue
            text = data.decode("latin-1")
            if ("IpBridge" in text or "hue-bridgeid" in text.lower()) and private_ip(addr):
                found.add(addr)
        sock.close()
    except OSError:
        pass
    return sorted(found)


def discover():
    hue = {addr: name for name, addr, _p, _t in avahi("_hue._tcp")}
    for addr in ssdp_hue():
        hue.setdefault(addr, "Hue bridge")
    ha = {f"http://{addr}:{port or 8123}": name for name, addr, port, _t in avahi("_home-assistant._tcp")}
    return {"hue": [{"ip": ip, "name": name} for ip, name in sorted(hue.items())],
            "ha": [{"url": url, "name": name} for url, name in sorted(ha.items())]}


def ha_get(path, values=None, secrets=None):
    values = values or read_settings()
    secrets = secrets if secrets is not None else read_secrets()
    if not values.get("ha_url") or not secrets.get("ha_token"):
        raise ValueError("Home Assistant needs its address and a token")
    return http("GET", values["ha_url"] + path, headers={"Authorization": f"Bearer {secrets['ha_token']}"})


# -- the veil (a GTK process of its own, only while there is one) -------------------------------
def motion_outputs():
    """Screens a moving wallpaper plays on (it follows the light itself)."""
    out = run("pgrep", "-af", "wallpaper-motion.py")
    names = set()
    for line in (out.stdout if out else "").splitlines():
        parts = line.split()       # pid python .../wallpaper-motion.py OUTPUT VIDEO
        if len(parts) == 5 and "python" in parts[1] and parts[2].endswith("/wallpaper-motion.py") \
                and re.fullmatch(r"[A-Za-z]+-[A-Za-z0-9-]+", parts[3]):
            names.add(parts[3])
    return names


def monitor_names():
    try:
        return [m["name"] for m in json.loads(run("hyprctl", "monitors", "-j").stdout)]
    except (AttributeError, ValueError, KeyError, TypeError):
        return []


def veil():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    import cairo
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

    state = {"rgba": (0, 0, 0, 0.0)}
    windows = []

    def load():
        data = _json(VEIL_FILE) or {}
        rgba = data.get("rgba") or [0, 0, 0, 0]
        state["rgba"] = (rgba[0] / 255, rgba[1] / 255, rgba[2] / 255, max(0.0, min(VEIL_MAX, float(rgba[3]))))
        for w in windows:
            w.queue_draw()

    def draw(_w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*state["rgba"])
        cr.paint()
        return False

    try:
        mons = json.loads(run("hyprctl", "monitors", "-j").stdout)
    except (AttributeError, ValueError):
        mons = []
    skip = set() if "--all" in sys.argv else motion_outputs()     # --all: the live test
    keep = {(m["x"], m["y"]) for m in mons if m.get("name") not in skip}
    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        mon = display.get_monitor(i)
        geo = mon.get_geometry()
        if mons and (geo.x, geo.y) not in keep:
            continue
        win = Gtk.Window()
        win.set_app_paintable(True)
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "ambient-veil")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_monitor(win, mon)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_exclusive_zone(win, -1)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        win.connect("draw", draw)
        win.show_all()
        win.input_shape_combine_region(cairo.Region())      # every click goes through
        windows.append(win)
    if not windows:
        return                  # every screen has a moving wallpaper: nothing to veil
    load()
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ImportError, ValueError):
        signal_add = GLib.unix_signal_add
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (load(), True)[1])
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (Gtk.main_quit(), False)[1])
    Gtk.main()


# -- the daemon ---------------------------------------------------------------------------------
def hypr_events():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.path.join(RUNTIME, "hypr")
    if not sig:
        try:
            sig = sorted(os.listdir(base))[-1]
        except (OSError, IndexError):
            return None
    import hyprbus      # the shared relay (only reloads), or socket2 directly
    try:
        return hyprbus.connect({"configreloaded"}, direct=os.path.join(base, sig, ".socket2.sock"))
    except OSError:
        return None


def write_live(data):
    try:
        write_file(LIVE, json.dumps(data))
    except OSError:
        pass


def serve():
    write_file(PIDFILE, f"{os.getpid()}\n")
    applier = Applier()
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_w, False)
    signal.set_wakeup_fd(wake_w)
    flags = {"stop": False}
    signal.signal(signal.SIGUSR1, lambda *_: None)
    signal.signal(signal.SIGTERM, lambda *_: flags.update(stop=True))
    signal.signal(signal.SIGINT, lambda *_: flags.update(stop=True))
    events, buf = hypr_events(), b""
    display_mtime = None
    last_errors = set()
    log("started")
    while not flags["stop"]:
        values = read_settings()
        if not on(values, "enabled"):
            log("switched off")
            break
        try:
            inputs = observe(values=values)
            p = plan(inputs, values)
            try:
                m = os.path.getmtime(DISPLAY_CONF)
            except OSError:
                m = None
            if m != display_mtime:      # display.py re-applied the preset: ours again
                display_mtime = m
                applier.applied.pop("animations", None)
            applier.check_veil()
            done = applier.apply(p, values, hold=inputs["gamemode"])
            for line in done:
                log(line)
            for err in applier.errors:
                if err not in last_errors:      # an unpaired bridge: once, not every pass
                    log(err)
            last_errors = set(applier.errors)
            write_live({"time": time.time(), "inputs": inputs, "plan": p, "lines": describe(p),
                        "errors": applier.errors[-5:], "hold": inputs["gamemode"]})
        except Exception as exc:  # noqa: BLE001 -- one bad pass must not end the service
            log(redact(f"pass failed: {exc!r}"))
        fds = [wake_r] + ([events] if events else [])
        deadline = time.monotonic() + TICK_S
        while not flags["stop"]:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                ready, _, _ = select.select(fds, [], [], left)
            except InterruptedError:
                continue
            if wake_r in ready:
                os.read(wake_r, 512)
                break                   # a poke (SIGUSR1) or a stop: a pass now
            if events in ready:
                try:
                    chunk = events.recv(65536)
                except OSError:
                    chunk = b""         # Hyprland went away: reconnect below
                if not chunk:
                    events = None
                    fds = [wake_r]
                    continue
                buf += chunk
                lines = buf.split(b"\n")
                buf = lines.pop()
                if any(line.startswith(b"configreloaded>>") for line in lines):
                    applier.applied.pop("animations", None)   # a reload: fresh Lua, our calm is gone
                    break
        if events is None:
            events = hypr_events()
    applier.reset()
    for line in applier.done:
        log(line)
    remove(PIDFILE)
    remove(LIVE)
    log("stopped")


def daemon_pid(proc="/proc"):
    """The running daemon's pid, or None. The pid file can outlive a killed
    daemon and its pid be reused, so the process must really be us: a stray
    SIGUSR1 would end an unrelated process (its default action)."""
    try:
        with open(PIDFILE) as handle:
            pid = int(handle.read().strip())
        with open(os.path.join(proc, str(pid), "cmdline"), "rb") as handle:
            argv = handle.read().split(b"\0")
    except (OSError, ValueError):
        return None
    if any(a.endswith(b"/ambient.py") or a == b"ambient.py" for a in argv) and b"daemon" in argv:
        return pid
    return None


def poke():
    pid = daemon_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGUSR1)
        return True
    except OSError:
        return False


def systemctl(*args):
    return run("systemctl", "--user", *args, timeout=20)


def service_state():
    out = systemctl("is-active", UNIT)
    return out.stdout.strip() if out else "unknown"


def set_master(state, dry=False):
    write_setting("enabled", state)
    if dry or dry_env():
        return
    if state == "on":
        systemctl("enable", "--now", UNIT)
    else:
        was_running = daemon_pid() is not None
        systemctl("disable", "--now", UNIT)
        if not was_running:
            Applier().reset()       # the service was not running to do it (its stop resets)


def status_data(now=None):
    values = read_settings()
    inputs = observe(now, values)
    p = plan(inputs, values)
    secrets = read_secrets()
    try:
        themes = [n for n, _ in _module("theme", "theme.py").themes()]
    except Exception:  # noqa: BLE001
        themes = []
    return {"settings": values, "service": service_state(), "inputs": inputs, "plan": p, "lines": describe(p),
            "live": _json(LIVE), "themes": themes,
            "paired": {"hue": bool(secrets.get("hue_user")), "ha": bool(secrets.get("ha_token"))},
            "sounds": {k: os.path.exists(sound_path(k)) for k in SOUND_KINDS},
            "tools": {"ffmpeg": bool(shutil.which("ffmpeg")), "mpv": bool(shutil.which("mpv")),
                      "avahi": bool(shutil.which("avahi-browse"))}}


def soundscape_cmd(arg):
    if arg == "toggle":
        arg = "stop" if os.path.exists(NOW_FILE) else "now"
    if arg == "now":
        write_file(NOW_FILE, "1\n")
    elif arg == "stop":
        remove(NOW_FILE)
    else:
        sys.exit("soundscape now|stop|toggle")
    if not poke():
        # not left behind: it would start a soundscape out of the blue the
        # next time the master switch goes on
        remove(NOW_FILE)
        sys.exit("ambient: the service is not running (Settings > Ambient switches it on)")


def lights_cli(args):
    values = read_settings()
    if args[:1] == ["discover"]:
        found = discover()
        print(json.dumps(found) if "--json" in args else
              "\n".join([f"hue  {b['ip']}  {b['name']}" for b in found["hue"]] +
                        [f"ha   {h['url']}  {h['name']}" for h in found["ha"]]) or "nothing found")
    elif args[:2] == ["hue", "pair"] and len(args) >= 3:
        wait = int(args[args.index("--wait") + 1]) if "--wait" in args else 30
        user = hue_pair(args[2], wait=max(1, min(120, wait)))
        write_setting("hue_bridge", args[2])
        write_secret("hue_user", user)
        print("paired")
    elif args[:2] == ["hue", "groups"]:
        ip, user = hue_base(values, read_secrets())
        _status, answer = hue_request("GET", ip, f"/api/{user}/groups")
        groups = [{"id": "0", "name": "Every light"}] + \
            [{"id": k, "name": v.get("name", k), "type": v.get("type", "")}
             for k, v in (answer or {}).items() if isinstance(v, dict)]
        print(json.dumps(groups) if "--json" in args else "\n".join(f"{g['id']}  {g['name']}" for g in groups))
    elif args[:2] == ["ha", "url"] and len(args) == 3:
        print(write_setting("ha_url", args[2]))
    elif args[:3] == ["ha", "token", "-"]:
        token = sys.stdin.readline().strip()
        if token and not re.fullmatch(r"[A-Za-z0-9._-]{20,1024}", token):
            sys.exit("that does not look like a long-lived token")
        write_secret("ha_token", token)
        print("saved" if token else "removed")
    elif args[:2] == ["ha", "test"]:
        status, answer = ha_get("/api/")
        ok = status == 200 and isinstance(answer, dict) and "message" in answer
        print("Home Assistant answered" if ok else f"Home Assistant said {status}")
        sys.exit(0 if ok else 1)
    elif args[:2] == ["ha", "entities"]:
        _status, answer = ha_get("/api/states")
        items = [{"id": s["entity_id"], "name": (s.get("attributes") or {}).get("friendly_name", s["entity_id"])}
                 for s in answer or [] if isinstance(s, dict) and ENTITY.fullmatch(s.get("entity_id", ""))]
        print(json.dumps(items) if "--json" in args else "\n".join(f"{i['id']}  {i['name']}" for i in items))
    elif args[:1] == ["scene"] and len(args) >= 2 and args[1] in MOODS:
        if values["lights"] == "off":
            sys.exit("smart lights are off (Settings > Ambient)")
        inputs = {"part": "day", "weather": None}
        scene = scene_for(args[1], inputs, values) or {"on": False}
        for line in lights_apply(scene, values, dry="--dry-run" in args):
            print(line)
    elif args[:1] == ["forget"] and args[1:2] in (["hue"], ["ha"]):
        write_secret("hue_user" if args[1] == "hue" else "ha_token", "")
        print("forgotten")
    else:
        sys.exit(__doc__)


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("status", [])
    try:
        if cmd == "daemon":
            serve()
        elif cmd == "veil":
            veil()
        elif cmd == "status":
            data = status_data()
            if "--json" in args:
                print(json.dumps(data))
            else:
                print(f"ambient: {data['settings']['enabled']} (service {data['service']})")
                print("\n".join("  " + line for line in data["lines"]))
        elif cmd == "plan":
            values = read_settings()
            mood = args[args.index("--mood") + 1] if "--mood" in args else None
            if mood is not None and mood not in MOODS:
                sys.exit(f"--mood {' | '.join(MOODS)}")
            p = plan(observe(values=values), values, mood=mood)
            print(json.dumps({"plan": p, "lines": describe(p)}) if "--json" in args else "\n".join(describe(p)))
        elif cmd == "tick" and "--dry-run" not in args and not dry_env():
            # a real pass belongs to the daemon: run here, the veil and mpv
            # would be children of this short-lived process, orphaned (never
            # stopped) and doubled next to the daemon's own
            if not poke():
                sys.exit("ambient: the service is not running (tick --dry-run says what it would do)")
        elif cmd == "tick":
            values = read_settings()
            inputs = observe(values=values)
            applier = Applier(dry="--dry-run" in args)
            for line in applier.apply(plan(inputs, values), values, hold=inputs["gamemode"]) + applier.errors:
                print(line)
        elif cmd == "poke":
            sys.exit(0 if poke() else 1)
        elif cmd == "set" and len(args) == 1 and args[0] in ("on", "off", "toggle"):
            state = args[0] if args[0] != "toggle" else ("off" if on(read_settings(), "enabled") else "on")
            set_master(state)
            if args[0] == "toggle" and not dry_env():       # the key: say what it did
                run(NOTIFY, "-a", APP, "-h", "string:x-canonical-private-synchronous:ambient",
                    "-t", "2000", f"Ambient desktop {state}")
        elif cmd == "set" and len(args) == 2 and args[0] == "enabled":
            set_master(check_value("enabled", args[1]))     # the service along with it
        elif cmd == "set" and len(args) == 2:
            print(write_setting(args[0], args[1]))
            poke()
        elif cmd == "soundscape" and len(args) == 1:
            soundscape_cmd(args[0])
        elif cmd == "sounds" and args[:1] == ["make"]:
            for kind in args[1:] or SOUND_KINDS:
                print(f"{kind}: {'ok' if make_sound(kind) else 'failed'}")
        elif cmd == "sounds" and args[:1] == ["render"] and len(args) >= 3 and args[1] in RECIPES:
            ok = make_sound(args[1], out=args[2], seconds=int(args[3]) if len(args) > 3 else 20)
            sys.exit(0 if ok else 1)
        elif cmd == "lights" and args:
            lights_cli(args)
        else:
            sys.exit(__doc__)
    except (ValueError, TimeoutError, OSError, urllib.error.URLError) as exc:
        sys.exit(f"ambient: {redact(str(exc))}")


if __name__ == "__main__":
    main(sys.argv[1:])
