#!/usr/bin/env python3
"""What Do Not Disturb held back, in one notification, when it ends.

    notify-digest.py              the digest of what arrived since the mark,
                                  as one notification; clicking it opens the
                                  notification panel (the bell's)
    notify-digest.py mark         the start of a Do Not Disturb stretch
    notify-digest.py --dry-run    print it instead (--plain: without the model)

Run by automations.py: it marks each time Do Not Disturb turns on, and its
built-in rule "dnd-digest" runs the digest when it turns off (Settings >
Notifications switches that rule; `automations.py disable dnd-digest` too).
Quiet hours, a game, a screen share, a focus round: any Do Not Disturb.

Where the notifications come from: mako, through the bar's notifications.py
(what the panel lists: `makoctl list` + `makoctl history`). mako keeps them
in memory only and stamps no time on them, but its ids only grow, so the
mark is the newest id when Do Not Disturb began ($XDG_RUNTIME_DIR/
notify-digest.json, with the time, for "for 2 h 10 min"); the digest is
everything with a bigger id. A mako restart starts the ids again: newest
below the mark means everything there is counts. No mark at all (the
daemon was not running) falls back to what the panel calls unread. mako
keeps max-history of them (50 unless Settings > Notifications says more):
a longer stretch loses the oldest, and then the count says "at least".

Low-urgency toasts (volume, theme, "screenshot saved") and this script's
own and automations' notifications are left out. Nothing left: nothing shown.

The words: the local "worker" model (Settings > AI & models), the way
llm-worker.py runs it -- its ready() and ask(): never a cloud model, never
while gamemode is on, never pushing another model off the GPU. With fewer
than AI_MIN notifications, or when the model cannot run or fails, the
digest is plain counts instead ("Slack 12, Mail 3, Firefox 1"), urgent ones
named -- still useful, and instant.
"""
import html
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WAYBAR = os.path.expanduser("~/.config/waybar/scripts")
PANEL = os.path.join(WAYBAR, "panel.py")
MARK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "notify-digest.json")
APP = "Digest"
SKIP_APPS = {APP, "Automations"}
AI_MIN = 4              # fewer than this: listed as they are, no model
MAX_LINES = 50          # into the prompt
LINE_CHARS = 220
ICON = "mail-unread-symbolic"

SYSTEM = ("You summarise the notifications someone missed while Do Not Disturb was on. Be brief and "
          "factual; never invent anything that is not in them.")


def _module(name, filename, folder=HERE):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(folder, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def notifications():
    return _module("notifications", "notifications.py", WAYBAR)


# -- the mark ------------------------------------------------------------------
def read_mark():
    try:
        with open(MARK) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) and isinstance(data.get("from_id"), int) else None
    except (OSError, ValueError):
        return None


def newest(items):
    return max((n.get("id", 0) for n in items), default=0)


def mark(fresh=True):
    """Remember where this Do Not Disturb stretch begins. fresh=False keeps a
    mark already there (automations.py restarted while it was on)."""
    if not fresh and read_mark():
        return
    data = {"from_id": newest(notifications().all_entries()), "since": time.time()}
    tmp = MARK + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, MARK)


def clear_mark():
    try:
        os.remove(MARK)
    except OSError:
        pass


# -- what was missed -------------------------------------------------------------
def missed(items, from_id):
    """The ones that count, oldest first: newer than from_id (all of them
    when mako restarted since: its newest is below the mark), not low
    urgency, not ours."""
    if newest(items) < from_id:
        from_id = 0
    out = [n for n in items if n.get("id", 0) > from_id and n.get("urgency") != "low"
           and app_of(n) not in SKIP_APPS]
    return sorted(out, key=lambda n: n.get("id", 0))


def app_of(n):
    return (n.get("app_name") or n.get("desktop_entry") or "Unknown").strip() or "Unknown"


def groups(items):
    """[(app, [notifications])], the busiest app first."""
    by = {}
    for n in items:
        by.setdefault(app_of(n), []).append(n)
    return sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))


def one_line(n):
    text = " ".join(f"{n.get('summary') or ''} — {n.get('body') or ''}".split()).strip(" —")
    return text[:LINE_CHARS - 1] + "…" if len(text) > LINE_CHARS else text


def span(seconds):
    if seconds is None:
        return ""
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{max(1, minutes)} min"
    return f"{minutes // 60} h" + (f" {minutes % 60} min" if minutes % 60 else "")


def title(items, seconds, lost):
    count = f"{'at least ' if lost else ''}{len(items)} notification{'s' if len(items) != 1 else ''}"
    return f"While Do Not Disturb was on{f' ({span(seconds)})' if seconds else ''}: {count}"


def plain(items):
    """The digest without a model: counts per app, the urgent ones named;
    with only a few, each one as it is."""
    if len(items) < AI_MIN:
        return "\n".join(f"{app_of(n)}: {one_line(n)}" + (" (urgent)" if n.get("urgency") == "critical" else "")
                         for n in items)
    text = ", ".join(f"{app} {len(ns)}" for app, ns in groups(items))
    urgent = list(dict.fromkeys(f"{app_of(n)}: {one_line(n)[:80]}" for n in items
                                if n.get("urgency") == "critical"))     # the same alert twice: once
    if urgent:
        text += "\nUrgent: " + "; ".join(urgent[:3])
        if len(urgent) > 3:
            text += f" (+{len(urgent) - 3} more)"
    return text


def prompt_for(items):
    lines = [f"[{app_of(n)}]{' [critical]' if n.get('urgency') == 'critical' else ''} {one_line(n)}"
             for n in items[-MAX_LINES:]]
    return ("Write a digest of these notifications: at most 6 short lines, one per app, busiest app "
            "first. Each line: the app, how many, and what they were about in a few words. Begin a line "
            "with \"URGENT:\" when something in it looks time-sensitive or important (marked critical, "
            "a direct question or request to the reader, a failure or error, a security or login alert, "
            "a deadline or meeting soon). Plain text, no markdown, no preamble.\n\n" + "\n".join(lines))


def with_model(items):
    """(text, None) from the worker model, or (None, why not)."""
    worker = _module("llm_worker", "llm-worker.py")
    model, why = worker.ready("worker")
    if model is None:
        return None, why
    try:
        text = worker.ask(model, prompt_for(items), system=SYSTEM)
    except Exception as err:         # a timeout, the server gone: counts instead
        return None, f"{model.name} failed: {err}"
    text = text.replace("**", "").strip()
    return (text, None) if text else (None, f"{model.name} answered nothing")


def digest(items, use_model=True):
    """(body, how): how is the model's name line or "plain"."""
    if use_model and len(items) >= AI_MIN:
        text, why = with_model(items)
        if text:
            return text, "model"
        print(f"notify-digest: plain counts: {why}", file=sys.stderr, flush=True)
    return plain(items), "plain"


# -- showing it --------------------------------------------------------------------
def show(summary, body, how):
    """One notification; clicking it opens the panel (its default action). Waits
    for it to close, so run detached (automations.py runs this as a
    transient unit)."""
    note = "\n<i>summarised by the local model: check the panel</i>" if how == "model" else ""
    argv = ["notify-send", "-a", APP, "-i", ICON, "--wait",
            "-A", "default=Open notifications",
            summary, html.escape(body, quote=False) + note]
    try:
        picked = subprocess.run(argv, capture_output=True, text=True, timeout=3600).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    if picked == "default":
        subprocess.Popen([PANEL, "toggle", "notifications", "--at", "bar-right"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv):
    if argv[:1] == ["mark"]:
        mark()
        return 0
    m = read_mark()
    items = notifications().all_entries()
    if m:
        from_id, seconds = m["from_id"], time.time() - m.get("since", time.time())
    else:
        n = notifications()
        from_id, seconds = max(n.read_id(n.SEEN), n.read_id(n.CLEARED)), None
    got = missed(items, from_id)
    if "--dry-run" not in argv:
        clear_mark()        # this stretch is told; the next one gets a new mark
    if not got:
        print("notify-digest: nothing was missed", flush=True)
        return 0
    # The oldest one mako still has came after the first one of the stretch:
    # the history overflowed, so there were more than it can show.
    lost = 0 < from_id and min((n.get("id", 0) for n in items), default=0) > from_id + 1
    body, how = digest(got, use_model="--plain" not in argv)
    summary = title(got, seconds, lost)
    if "--dry-run" in argv:
        print(summary)
        print(body)
        return 0
    print(f"notify-digest: {len(got)} missed, {how}", flush=True)
    show(summary, body, how)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
