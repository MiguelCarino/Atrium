#!/usr/bin/env python3
"""The mascot in the desktop's notifications. scripts/notify is a drop-in
for notify-send that every desktop script calls instead: same arguments,
same output (-p's id, --wait's action), then notify-send itself does the
sending -- this only changes the icon and, voice on, the words.

    notify [--mood M] [--say TOPIC[|ARG...]] NOTIFY-SEND ARGS...
    mascot_notify.py status         the switches, as JSON
    mascot_notify.py set KEY on|off icon, toasts, voice (mascot.json)

What it does, by Settings (mascot_mood.py's mascot.json "notifications"):

    icon    on: the current theme's little mascot (mascot_icons.py) is the
            icon; the app's own icon, when it gave one, rides small in the
            corner (a timer still shows its alarm clock). Generic icons
            (dialog-warning, dialog-information, ...) are dropped instead:
            the mascot's mood says the same. Off: nothing changes.
    toasts  off: low-urgency toasts (volume, keyboard layout, "saved")
            keep their own icon -- they come and go too fast to need a face.
    voice   on: the first line of the body is the mascot's, in its own
            voice: --say TOPIC (a mascot_mood topic, ARGs for its {0} {1}),
            else its "worried" line on critical ones and "relieved" with
            --mood relieved. Ships off.

--mood is calm, alert or relieved (mascot_icons.MOODS); unset: alert for
-u critical, else calm. Anything going wrong here (no Pillow, a broken
theme) sends the notification unchanged: a notification is never lost for
the sake of a face.

    argv(args, mood=None, say=None) -> the notify-send argv, in Python
    send(summary, body="", ..., mood=, say=) -> subprocess.Popen

Both also hand the summary to the dynamic island (island_events.py), which
costs nothing when the island is off; Railguard's own go there directly.
With "notifications in the island" on, the island ignores this copy: it
sees the notification itself on the bus (with mako's id), so nothing shows
twice; the copy is only for the short line when that is off.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "mascot.json")
DEFAULTS = {"icon": True, "toasts": False, "voice": False}      # mascot_mood.NOTIFY_DEFAULTS
# notify-send options that take a value (the rest are flags)
WITH_VALUE = {"-u", "--urgency", "-t", "--expire-time", "-a", "--app-name", "-i", "--icon",
              "-n", "--app-icon", "-c", "--category", "-h", "--hint", "-A", "--action",
              "-r", "--replace-id", "--id-fd", "--selected-action-fd",
              "--activation-token-fd"}
GENERIC_ICONS = ("dialog-", "emblem-", "notification", "info", "error", "warning", "important")


def settings():
    """mascot.json's notification switches (read here, not through
    mascot_mood, so a plain notification does not pay for importing it)."""
    cur = dict(DEFAULTS)
    try:
        with open(STATE) as fh:
            data = json.load(fh).get("notifications")
        if isinstance(data, dict):
            cur.update({k: bool(v) for k, v in data.items() if k in cur})
    except (OSError, ValueError, AttributeError):
        pass
    return cur


def parse(args):
    """notify-send's arguments as (options [(flag, value|None)], positionals)."""
    opts, pos, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("--") and "=" in a:
            k, v = a.split("=", 1)
            opts.append((k, v))
        elif a in WITH_VALUE and i + 1 < len(args):
            opts.append((a, args[i + 1]))
            i += 1
        elif a.startswith("-") and len(a) > 2 and a[:2] in WITH_VALUE and not a.startswith("--"):
            opts.append((a[:2], a[2:]))        # -ucritical
        elif a.startswith("-") and a != "-":
            opts.append((a, None))
        else:
            pos.append(a)
        i += 1
    return opts, pos


def get(opts, *names):
    for k, v in reversed(opts):
        if k in names:
            return v
    return None


def voice_line(say):
    """The current mascot's words for a topic tuple, or None."""
    try:
        sys.path.insert(0, HERE)
        import importlib
        import mascot_mood
        import mascots
        import theme as desktop
        mod = importlib.import_module(mascots.MODULES.get(desktop.current(), "moe_mascot"))
        return mascot_mood.word(getattr(mod, "TOPIC_LINES", {}), tuple(say))
    except Exception:
        return None


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def argv(args, mood=None, say=None):
    """The notify-send argv for these notify-send args, the mascot added."""
    plain = ["notify-send", *args]
    try:
        s = settings()
        opts, pos = parse(list(args))
        urgency = (get(opts, "-u", "--urgency") or "normal").lower()
        if urgency == "low" and not s["toasts"]:
            return plain
        mood = mood or ("alert" if urgency == "critical" else "calm")
        out_opts = [(k, v) for k, v in opts if k not in ("-i", "--icon")]
        if s["icon"]:
            given = get(opts, "-i", "--icon")
            badge = None if not given or given.startswith(GENERIC_ICONS) else given
            sys.path.insert(0, HERE)
            import mascot_icons
            out_opts.append(("-i", mascot_icons.icon(None, mood, badge)))
        else:
            out_opts = opts
        if s["voice"]:
            topic = say or {"alert": ("worried",), "relieved": ("relieved",)}.get(mood)
            line = voice_line(topic) if topic else None
            if line:
                summary = pos[0] if pos else ""
                body = pos[1] if len(pos) > 1 else ""
                pos = [summary, f"<i>{_escape(line)}</i>" + (f"\n{body}" if body else "")] + pos[2:]
        flat = []
        for k, v in out_opts:
            flat += [k] if v is None else [k, v]
        return ["notify-send", *flat, "--", *pos] if pos else ["notify-send", *flat]
    except Exception:
        return plain


def island_hook(summary, body, app, urgency):
    """A copy for the dynamic island (a no-op when it is off); mako still
    shows the notification either way."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import island_events
        island_events.notify(summary, body, app, urgency)
    except Exception:
        pass


def send(summary, body="", app=None, urgency=None, icon=None, timeout=None,
         mood=None, say=None, extra=()):
    """One notification, the mascot added; the Popen (stdout piped when
    extra asks for -p or --wait output)."""
    args = []
    if app:
        args += ["-a", app]
    if urgency:
        args += ["-u", urgency]
    if icon:
        args += ["-i", icon]
    if timeout is not None:
        args += ["-t", str(timeout)]
    args += list(extra) + [summary] + ([body] if body else [])
    if app != "Railguard":                  # railguard.py sends its own
        island_hook(summary, body, app, urgency)
    return subprocess.Popen(argv(args, mood, say), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def drop_in(args):
    """scripts/notify: take out our two options (anywhere before the
    summary), then exec notify-send."""
    mood = say = None
    rest, i = [], 0
    while i < len(args):
        if args[i] == "--":
            rest += args[i:]
            break
        if args[i] in ("--mood", "--say") and i + 1 < len(args):
            if args[i] == "--mood":
                mood = args[i + 1]
            else:
                say = tuple(args[i + 1].split("|"))
            i += 2
            continue
        rest.append(args[i])
        i += 1
    cmd = argv(rest, mood, say)
    try:
        opts, pos = parse(rest)
        app = get(opts, "-a", "--app-name")
        if app != "Railguard":              # railguard.py sends its own
            island_hook(pos[0] if pos else "", pos[1] if len(pos) > 1 else "",
                        app, get(opts, "-u", "--urgency"))
    except Exception:
        pass
    os.execvp(cmd[0], cmd)


def main(argv_):
    args = argv_[1:]
    if args[:1] == ["status"]:
        print(json.dumps(settings()))
    elif args[:1] == ["set"] and len(args) == 3 and args[1] in DEFAULTS and args[2] in ("on", "off"):
        sys.path.insert(0, HERE)
        import mascot_mood
        mascot_mood.save_settings(notifications={args[1]: args[2] == "on"})
        print(json.dumps(settings()))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
