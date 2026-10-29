#!/usr/bin/env python3
"""How notifications behave: Do Not Disturb, quiet hours, auto-DND, where
popups go and how long they stay, the history (Settings > Notifications, the
search bar and the keys all run this).

    notify-settings.py [status]        everything below as one JSON object
    notify-settings.py dnd on|off|toggle
                                       Do Not Disturb now (mako's
                                       do-not-disturb mode, the same one
                                       ALT+SHIFT+D toggles)
    notify-settings.py set KEY VALUE   change one setting (keys below), save
                                       it, rewrite mako's fragment, reload
    notify-settings.py get [KEY]       the saved settings (or one) as JSON
    notify-settings.py reset           every setting back to its default
    notify-settings.py apply           rewrite the fragment and reload mako
    notify-settings.py ensure          write the fragment only if it is
                                       missing (mako.service ExecStartPre)
    notify-settings.py restore         bring back the last dismissed one
    notify-settings.py clear           dismiss all and empty the panel
                                       (notifications.py clear)

Keys (VALUE in brackets):
    anchor            where the stack sits [top-right top-center top-left
                      bottom-right bottom-center bottom-left center-right
                      center-left center]
    output            the screen [a monitor name such as DP-1, or "follow"
                      for the focused screen]
    timeout_normal    seconds a popup stays; 0 = until dismissed
    timeout_low       ... for low urgency (volume toasts and the like)
    timeout_critical  ... for urgent ones (0, the default: until dismissed)
    ignore_app_timeouts  [on|off] use these times even when the app asks
                      for its own
    max_visible       how many at once [1-20, or -1 for no limit]
    group             [on|off] stack repeats from one app into one popup
    max_history       how many dismissed ones mako keeps [0-500]
    critical_in_dnd   [on|off] urgent ones still pop up in Do Not Disturb
    dnd_games         [on|off] DND on by itself while a Steam game runs
    dnd_share         [on|off] ... while the screen is shared
    quiet             [on|off] quiet hours: DND on by itself every night
    quiet_from, quiet_to   [HH:MM] the quiet hours (may cross midnight)
    quiet_days        the days the quiet hours START on [every-day,
                      weekdays, weekends, or digits 0-6 with 0 = Monday]

Where it lives. The settings are one small JSON file,
$XDG_STATE_HOME/hypr/notifications.json, so they survive a Hyprland reload
and a re-login. Two things read it:

  * mako, through ~/.config/mako/generated/settings, which this writes. mako's
    config is layered -- mako/config (the base), then mako/sections (the
    criteria sections), then THIS fragment, then generated/theme (the desktop
    theme) -- and later lines win. A theme sets looks only (colours, font,
    borders), this fragment behaviour only (position, screen, timeouts,
    limits), so neither steps on the other: themes still win on looks,
    these win on behaviour, including over the base's [urgency=...]
    timeouts in mako/sections. generated/ is never in the dotfiles repo, so
    a mako.service drop-in runs `ensure` before mako starts: an include of a
    missing file makes mako refuse its whole config (tested).
  * auto-dnd.py (auto-dnd.service), which turns DND on and off by itself:
    during games and screen sharing (each one switchable here) and during
    the quiet hours. `set` wakes it with SIGUSR1 so a change counts at once.

A change is applied with `makoctl reload`; if mako rejects the new fragment
the old one is put back, so a bad value can never leave mako without a
config. The values are checked before they are written anyway.
"""
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import screens  # noqa: E402  (scripts/screens.py: the primary, DEFAULTS["output"])
import desk_common  # noqa: E402  (run: a command with a timeout)
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
CONF = os.path.join(STATE_DIR, "notifications.json")
FRAGMENT = os.path.expanduser("~/.config/mako/generated/settings")
WAYBAR_CONFIG = os.path.expanduser("~/.config/waybar/config")
# What auto-dnd.py says about itself (tmpfs): whether DND is on because it
# turned it on, and for which reasons -- so the page can say "on by itself".
AUTO_STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "auto-dnd.json")
NOTIFICATIONS = os.path.expanduser("~/.config/waybar/scripts/notifications.py")
THEME_SOUND = os.path.join(HERE, "theme-sound.sh")
MODE = "do-not-disturb"

ANCHORS = ["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left",
           "center-right", "center-left", "center"]
# The defaults are what mako/config and mako/sections say on their own, so
# a fragment written from them changes nothing. output: the primary screen
# (scripts/screens.py; "" -- the focused screen -- when nothing knows one).
DEFAULTS = {
    "anchor": "top-right",
    "output": screens.primary(),
    "timeout_normal": 5,
    "timeout_low": 3,
    "timeout_critical": 0,
    "ignore_app_timeouts": False,
    "max_visible": 5,
    "group": True,
    "max_history": 50,
    "critical_in_dnd": True,
    "dnd_games": True,
    "dnd_share": True,
    "quiet": False,
    "quiet_from": "23:00",
    "quiet_to": "07:00",
    "quiet_days": "0123456",
}
DAY_ALIASES = {"every-day": "0123456", "everyday": "0123456", "daily": "0123456",
               "weekdays": "01234", "weekends": "56"}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# The base's outer-margin (mako/config) leaves 44 px at the top for the bar.
# On a screen without the bar, popups anchored at the top would hang 44 px
# down for nothing, so the fragment narrows it to this there.
PLAIN_MARGIN = "14"


# -- values -------------------------------------------------------------------------
def parse_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "on", "yes", "true"):
        return True
    if text in ("0", "off", "no", "false"):
        return False
    raise ValueError(f"on or off, not {value!r}")


def parse_hm(value):
    """'7:05' / '07:05' / '7' -> minutes after midnight (ValueError if not)."""
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*", str(value))
    if not m:
        raise ValueError(f"a time like 23:00, not {value!r}")
    hours, minutes = int(m.group(1)), int(m.group(2) or 0)
    if hours > 23 or minutes > 59:
        raise ValueError(f"a time like 23:00, not {value!r}")
    return hours * 60 + minutes


def fmt_hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_days(value):
    text = str(value).strip().lower()
    text = DAY_ALIASES.get(text, text)
    if not text or not re.fullmatch(r"[0-6]+", text):
        raise ValueError(f"every-day, weekdays, weekends or digits 0-6 (0 = Monday), not {value!r}")
    return "".join(sorted(set(text)))


def parse_int(value, lo, hi):
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ValueError(f"a whole number, not {value!r}") from None
    if not lo <= number <= hi:
        raise ValueError(f"between {lo} and {hi}, not {number}")
    return number


def coerce(key, value):
    """The checked value for KEY, or ValueError saying what it should be."""
    key = key.replace("-", "_")
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r} (keys: {', '.join(DEFAULTS)})")
    if key == "anchor":
        value = str(value).strip().lower().replace("centre", "center")
        if value not in ANCHORS:
            raise ValueError(f"one of {', '.join(ANCHORS)}")
        return value
    if key == "output":
        value = str(value).strip()
        if value.lower() in ("", "follow", "focus", "focused", "any"):
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", value):
            raise ValueError(f"a monitor name such as DP-1, or follow, not {value!r}")
        return value
    if key.startswith("timeout_"):
        return parse_int(value, 0, 3600)
    if key == "max_visible":
        number = parse_int(value, -1, 20)
        if number == 0:
            raise ValueError("at least 1, or -1 for no limit")
        return number
    if key == "max_history":
        return parse_int(value, 0, 500)
    if key in ("quiet_from", "quiet_to"):
        return fmt_hm(parse_hm(value))
    if key == "quiet_days":
        return parse_days(value)
    return parse_bool(value)


def load():
    """The saved settings over the defaults. A broken or hand-mangled file
    falls back key by key: a bad value is replaced by its default."""
    conf = dict(DEFAULTS)
    try:
        with open(CONF) as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict):
        for key, value in saved.items():
            try:
                conf[key] = coerce(key, value)
            except ValueError:
                pass
    return conf


def save(conf):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({k: conf[k] for k in DEFAULTS}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, CONF)


# -- quiet hours --------------------------------------------------------------------
def quiet_now(conf, now):
    """True while the quiet hours run at `now` (a naive local datetime). The
    window belongs to the day it STARTS on: 23:00-07:00 with weekdays means
    Monday night to Saturday morning. from == to is an empty window."""
    if not conf.get("quiet"):
        return False
    start, end = parse_hm(conf["quiet_from"]), parse_hm(conf["quiet_to"])
    if start == end:
        return False
    days = conf["quiet_days"]
    minute = now.hour * 60 + now.minute
    today, yesterday = str(now.weekday()), str((now.weekday() - 1) % 7)
    if start < end:
        return today in days and start <= minute < end
    return (minute >= start and today in days) or (minute < end and yesterday in days)


def next_change(conf, now):
    """When quiet_now() next flips, or None if it never will (off, or an
    empty window). Only the from / to minutes of the coming eight days can
    be such a moment, so those are the candidates."""
    if not conf.get("quiet"):
        return None
    current = quiet_now(conf, now)
    base = now.replace(second=0, microsecond=0)
    candidates = []
    for offset in range(9):
        day = (base + datetime.timedelta(days=offset)).replace(hour=0, minute=0)
        for key in ("quiet_from", "quiet_to"):
            at = day + datetime.timedelta(minutes=parse_hm(conf[key]))
            if at > now:
                candidates.append(at)
    for at in sorted(candidates):
        if quiet_now(conf, at) != current:
            return at
    return None


def describe_days(days):
    for name, value in (("every day", "0123456"), ("weekdays", "01234"), ("weekends", "56")):
        if days == value:
            return name
    return ", ".join(DAY_NAMES[int(d)] for d in days)


# -- mako ---------------------------------------------------------------------------
def bar_outputs(path=None):
    """The screens a bar sits on (waybar/config's "output" lines)."""
    try:
        with open(path or WAYBAR_CONFIG) as fh:
            return sorted(set(re.findall(r'"output"\s*:\s*"([^"]+)"', fh.read())))
    except OSError:
        return []


def render_fragment(conf, bars):
    """mako/generated/settings for `conf`. Global lines first: once a
    [section] opens, every later line of the file belongs to it."""
    ms = lambda seconds: str(seconds * 1000)  # noqa: E731
    lines = [
        "# GENERATED by ~/.config/hypr/scripts/notify-settings.py -- do not edit;",
        "# change it in Settings > Notifications or with `notify-settings.py set`.",
        "# Source: $XDG_STATE_HOME/hypr/notifications.json. Included by mako/config",
        "# after mako/sections and before the theme: behaviour only, no looks.",
        f"anchor={conf['anchor']}",
        f"output={conf['output']}",
        f"max-visible={conf['max_visible']}",
        f"default-timeout={ms(conf['timeout_normal'])}",
        f"ignore-timeout={1 if conf['ignore_app_timeouts'] else 0}",
        f"group-by={'app-name' if conf['group'] else ''}",
        f"max-history={conf['max_history']}",
    ]
    if conf["anchor"].startswith("top") and conf["output"] and conf["output"] not in bars:
        lines += ["# no bar on this screen: no room left for one at the top",
                  f"outer-margin={PLAIN_MARGIN}"]
    lines += ["", "[urgency=low]", f"default-timeout={ms(conf['timeout_low'])}",
              "", "[urgency=critical]", f"default-timeout={ms(conf['timeout_critical'])}"]
    if not conf["critical_in_dnd"]:
        lines += ["", "# Do Not Disturb means silent, urgent ones included (still kept in the history).",
                  "[mode=do-not-disturb urgency=critical]", "invisible=1"]
    return "\n".join(lines) + "\n"


def run(*cmd, timeout=5):
    """The CompletedProcess, None when it could not run or timed out."""
    return desk_common.run(cmd, timeout=timeout)


def makoctl(*args):
    result = run("makoctl", *args, timeout=3)
    return result.stdout if result else ""


def mako_running():
    result = run("makoctl", "mode", timeout=3)
    return bool(result and result.returncode == 0)


def write_fragment(text):
    os.makedirs(os.path.dirname(FRAGMENT), exist_ok=True)
    tmp = FRAGMENT + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, FRAGMENT)


def apply(conf, reload=True):
    """Write the fragment; reload mako; put the old one back if mako says no.
    Returns None, or mako's complaint."""
    try:
        with open(FRAGMENT) as fh:
            old = fh.read()
    except OSError:
        old = None
    text = render_fragment(conf, bar_outputs())
    if text == old and not reload:
        return None
    write_fragment(text)
    if not reload or not mako_running():
        return None
    result = run("makoctl", "reload", timeout=5)
    if result is not None and result.returncode == 0:
        return None
    complaint = ((result.stderr or result.stdout).strip() if result else "makoctl did not answer") or "rejected"
    if old is not None:
        write_fragment(old)
        run("makoctl", "reload", timeout=5)
    return complaint


def ensure():
    """The fragment if it is missing (from the saved settings), nothing else."""
    if not os.path.exists(FRAGMENT):
        apply(load(), reload=False)


def bell():
    """Redraw the bar's notification bell (bar_signals.py "notifications")."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import bar_signals
        return bar_signals.poke("notifications")
    except Exception:       # noqa: BLE001 - no bar: nothing to redraw
        return 0


def poke_auto_dnd():
    """Wake auto-dnd.py so it re-reads the settings now, not in 30 s. Only
    when it runs: SIGUSR1 to a process without the handler would end it."""
    active = run("systemctl", "--user", "is-active", "--quiet", "auto-dnd.service")
    if active is not None and active.returncode == 0:
        run("systemctl", "--user", "kill", "--signal=USR1", "auto-dnd.service")


def dnd_on():
    return MODE in makoctl("mode").split()


def set_dnd(how):
    on = {"on": True, "off": False, "toggle": not dnd_on()}.get(how)
    if on is None:
        raise ValueError("on, off or toggle")
    makoctl("mode", "-a" if on else "-r", MODE)
    bell()
    poke_auto_dnd()
    # makoctl says nothing useful when mako is down; ask what mode it is in
    # now, so the page (and a key) learn it did not happen instead of "on".
    if dnd_on() != on:
        raise RuntimeError("mako did not take it (is it running?)")
    return on


def listed():
    """{"history": n, "shown": n}: what the bell's panel lists, i.e. since its
    last "Clear" (notifications.py list) -- mako cannot empty its history, so
    the panel's Clear hides what came before and this counts the same way."""
    result = run(NOTIFICATIONS, "list", timeout=5)
    try:
        items = json.loads(result.stdout if result else "[]")
    except ValueError:
        items = []
    return {source: sum(1 for n in items if n.get("source") == source) for source in ("history", "shown")}


def outputs():
    result = run("hyprctl", "monitors", "-j", timeout=3)
    try:
        return [{"name": m["name"], "description": m.get("description", "")}
                for m in json.loads(result.stdout if result else "[]")]
    except (ValueError, KeyError, TypeError):
        return []


def auto_state():
    try:
        with open(AUTO_STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def status():
    conf = load()
    now = datetime.datetime.now()
    change = next_change(conf, now)
    service = run("systemctl", "--user", "is-active", "auto-dnd.service")
    sounds = run(THEME_SOUND, "status")
    counts = listed()
    return {
        "dnd": dnd_on(),
        "mako": mako_running(),
        "settings": conf,
        "defaults": DEFAULTS,
        "quiet_now": quiet_now(conf, now),
        "quiet_change": change.strftime("%a %H:%M") if change else None,
        "quiet_days_text": describe_days(conf["quiet_days"]),
        "auto_dnd_service": (service.stdout.strip() if service else "") or "unknown",
        "auto": auto_state(),
        "history": counts["history"],
        "shown": counts["shown"],
        "sounds": (sounds.stdout.strip() if sounds else "") or "on",
        "outputs": outputs(),
        "bar_outputs": bar_outputs(),
        "fragment": os.path.exists(FRAGMENT),
    }


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    args = argv[2:]
    if cmd == "status":
        print(json.dumps(status(), indent=1))
    elif cmd == "get":
        conf = load()
        print(json.dumps(conf[args[0].replace("-", "_")] if args and args[0].replace("-", "_") in conf else conf))
    elif cmd == "set" and len(args) == 2:
        conf = load()
        try:
            key = args[0].replace("-", "_")
            conf[key] = coerce(key, args[1])
        except ValueError as err:
            sys.exit(f"notify-settings: {args[0]}: {err}")
        save(conf)
        complaint = apply(conf)
        if key.startswith(("dnd_", "quiet")):
            poke_auto_dnd()
        if complaint:
            sys.exit(f"notify-settings: mako rejected the change, the old settings stay: {complaint}")
    elif cmd == "reset":
        save(dict(DEFAULTS))
        complaint = apply(dict(DEFAULTS))
        poke_auto_dnd()
        if complaint:
            sys.exit(f"notify-settings: mako rejected the defaults: {complaint}")
    elif cmd == "apply":
        complaint = apply(load())
        if complaint:
            sys.exit(f"notify-settings: mako rejected the fragment, the old one stays: {complaint}")
    elif cmd == "ensure":
        ensure()
    elif cmd == "dnd" and len(args) == 1:
        try:
            print("on" if set_dnd(args[0]) else "off")
        except (ValueError, RuntimeError) as err:
            sys.exit(f"notify-settings: dnd: {err}")
    elif cmd == "restore":
        makoctl("restore")
        bell()
    elif cmd == "clear":
        run(NOTIFICATIONS, "clear")
    else:
        print(__doc__.split("Where it lives")[0].rstrip())
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
