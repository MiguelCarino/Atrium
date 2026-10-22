#!/usr/bin/env python3
"""Live suggestions: a quiet strip in a corner of the screen that offers the
next step for what you are doing -- "draft a commit message" for a repo
whose changes have sat a while, "pick up where you left off" when you come
back to the desk. One click does it, one click (x) sends it away, and it
goes by itself after a few seconds. It never takes the keyboard.

    suggest.py daemon                 the service (suggest.service): watch, decide, show
    suggest.py get [--json]           the settings, each kind, what it has learned
    suggest.py set on|off             the whole thing (enable --now / disable --now the unit)
    suggest.py set KIND on|off        one kind (KINDS below)
    suggest.py set KEY VALUE          position, gap_min, show_s, away_min,
                                      commit_after_min, meeting_lead_min
    suggest.py snooze MIN|off|toggle  nothing for MIN minutes (1..480), or again now;
                                      toggle: an hour, or back on (the key; says which)
    suggest.py sample [KIND]          show what a card looks like (its buttons do nothing)
    suggest.py forget                 forget what it learned from your clicks
    suggest.py status [--json]        what the daemon is doing (never what a card says)
    suggest.py strip                  (internal) the card; its JSON on stdin
    suggest.py events MIN             (internal) calendar events within MIN minutes, as JSON

THE KINDS (the two quiet, useful ones on as shipped; the rest off):

    commit     a terminal or an editor on a git repo has the focus, and the
               repo's changes are older than commit_after_min and none
               changed in the last two minutes (you paused): "Draft a commit
               message". The click asks the local worker model (llm-worker.py:
               ready("worker") + ask(); local only, refuses in gamemode or when
               it would not fit on the GPU) with `git diff --stat` and the diff
               (size-capped, files that look secret left out by llm-worker's
               rule) and the last subjects for the repo's style; the draft
               comes up in the strip with Copy. It never commits.
    resume     you come back after away_min or more (the screen was locked --
               hyprlock -- or the machine slept): "Go back to <app>" puts the
               focus on the window you had before you left
    clipboard  the smart clipboard's cards come here instead of its own
               corner card (smart-clipboard.py hands them over through
               suggest.sock while this is on; its rules, kinds and secret
               filter are unchanged and its actions run as they would there)
    context    entering a project context (contexts.py): "Start a focus round"
    meeting    an event from your calendars (timers.py's reader, Evolution's
               enabled calendars) starts within meeting_lead_min: Do Not
               Disturb on, or open the calendar
    focus      focus guard (focus-guard.py, when its noticing is on) finds
               you hopping between unrelated windows: "Focus 25 min" starts
               its focus block. It hands the card over through suggest.sock
               ("focus" op) and shows a notification itself when this kind
               is off or the strip is not running

Not done: "a build failed in a terminal". COSMIC Terminal (the terminal
here) has no remote control to read an exit status from, and guessing from
titles is not cheap or reliable, so that kind is left out.

QUIET. At most one card is up. A card that is not from your own copy waits
gap_min after the last one. Nothing at all while a window is fullscreen,
gamemode is on (animations off: lua/gamemode.lua's own test), Do Not
Disturb is on, the screen is shared (Hyprland's screencast event), the
screen is locked, or a snooze runs; a card that is up goes when one of
those starts. A suggestion that cannot be shown in time is dropped, not
queued for later.

LEARNING (~/.local/state/hypr/suggest-learn.json, counts and times only):
per kind, how often a card was shown, used, sent away (x) and left to go by
itself. Sending one away rests the kind BASE_REST_S, doubling with each
one in a row (to MAX_REST_S); using one resets that. A card left alone
rests the kind IGNORED_REST_S (not a clipboard card: you copied to paste;
a clipboard card skips gap_min, but an x rests it like the others). When two suggestions wait at once, the kind
you use more (and dismiss less) goes first. `forget` (and the page's
button) starts over.

PRIVACY. Everything is local; no model runs until you click. A private
window (activity-log.py's is_private: KeePassXC, private browsing, the
apps on the Privacy page's private list) is never looked into -- no git,
no title -- and the window you return to is named without its title if it
was private. Window titles and copies are kept in memory only, never
written down or logged; the clipboard card's text reaches the strip
through its stdin, like smart-clipboard.py's own card.

ACTIONS are a fixed catalog (ACTIONS) checked against the card that offered
them: no shell, nothing built from what a model said. None is destructive.

THE STRIP is a GTK layer-shell window (panel.css's look, the "waybar-panel"
namespace so lua/rules.lua frosts it like the panels), in the corner the
Settings page picks, on the focused screen.

SETTINGS: whether suggest.service runs is the switch (Settings > Live
suggestions, and on Settings > Privacy); the rest is
~/.local/state/hypr/suggest.conf, key=value (DEFAULTS / LIMITS / CHOICES).
`set` tells a running daemon to read it again.
"""
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.abspath(__file__)
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
CONF = os.path.join(STATE_HOME, "hypr", "suggest.conf")
LEARN = os.path.join(STATE_HOME, "hypr", "suggest-learn.json")
SOCK = os.path.join(RUNTIME, "suggest.sock")
UNIT = "suggest.service"
CONTEXTS_STATE = os.path.join(RUNTIME, "contexts.json")
DEFAULT_APPS = os.path.join(HERE, "default-apps.py")
TIMERS = os.path.join(HERE, "timers.py")
NOTIFY_SETTINGS = os.path.join(HERE, "notify-settings.py")

TICK_S = 15                 # lock / sleep / context / the focused repo again
DWELL_S = 2.0               # a window has the focus this long before it counts
REPO_RECHECK_S = 120        # the focused repo's state, again, while it keeps the focus
REPO_REST_S = 2 * 3600      # the same repo is not offered again this soon (unless committed between)
PAUSE_S = 120               # commit: no change this recent (you are mid-edit)
MEETING_EVERY_S = 300
MEETING_TIMEOUT_S = 30      # the calendar reader runs on its own; killed when it takes longer
QUIET_RECHECK_S = 5         # DND / gamemode asked again no sooner than this while a card waits
RESUME_DELAY_S = 4          # after the unlock: let you settle first
EXPIRE = {"commit": 600, "resume": 180, "clipboard": 20, "context": 120, "meeting": 600}
BASE_REST_S = 30 * 60
MAX_REST_S = 24 * 3600
IGNORED_REST_S = 10 * 60
MAX_DIFF = 12_000           # characters of diff the model sees
MAX_FILES = 200
SAMPLE_ACTION = "noop"

# kind: (label for Settings, on as shipped, what it does)
KINDS = {
    "commit": ("Draft a commit message", True,
               "A repo you are working in has changes that sat a while: a local model drafts the message "
               "from the diff when you click (it never commits)."),
    "resume": ("Pick up where you left off", True,
               "Back after the screen was locked or the computer slept: go back to the window you had."),
    "clipboard": ("Smart clipboard cards", False,
                  "What you copy (a link, an address, an error...) is offered here instead of the smart "
                  "clipboard's own card."),
    "context": ("Project contexts", False, "Entering a project context: start a focus round."),
    "meeting": ("Meetings soon", False,
                "An event from your calendars starts soon: Do Not Disturb, or open the calendar."),
    "focus": ("Scattered? A focus block", False,
              "Focus guard noticed a lot of switching between unrelated windows: start a focus block "
              "(only while its noticing is on, Settings > Focus)."),
}
PRIORITY = {"clipboard": 1.0, "meeting": 0.9, "resume": 0.8, "focus": 0.7, "commit": 0.6, "context": 0.5}
ICONS = {"commit": "\uf386", "resume": "\uf2ea", "clipboard": "\uf328", "context": "\uf542",
         "meeting": "\uf073", "focus": "\uf140"}
FOCUS_GUARD = os.path.join(HERE, "focus-guard.py")

POSITIONS = ("top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right")
DEFAULTS = {**{k: "on" if v[1] else "off" for k, v in KINDS.items()},
            "position": "bottom-right", "gap_min": "10", "show_s": "15", "away_min": "15",
            "commit_after_min": "20", "meeting_lead_min": "10"}
LIMITS = {"gap_min": (1, 120), "show_s": (5, 60), "away_min": (3, 240), "commit_after_min": (0, 240),
          "meeting_lead_min": (2, 60)}     # = the Settings page's sliders
CHOICES = {**{k: ("on", "off") for k in KINDS}, "position": POSITIONS}
ADDRESS = re.compile(r"0x[0-9a-f]{4,16}$")
SECRET_APPS = re.compile(r"keepassxc|keepass|bitwarden|1password|enpass|seahorse|kwalletmanager|"
                         r"proton.?pass|lastpass|dashlane|keeper|gopass|qtpass|secrets", re.I)
COMMIT_SYSTEM = ("You write git commit messages. Answer with the message only: a summary line of at most "
                 "72 characters in the imperative mood, then (only if it helps) a blank line and up to five "
                 "short lines starting with '- '. Describe what changed and why, from the diff; never "
                 "invent changes that are not in it. No quotes, no code fences, no sign-off lines.")


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def log(text):
    print(f"suggest: {text}", file=sys.stderr, flush=True)


# -- settings -------------------------------------------------------------------------------
def check_value(key, value):
    value = str(value).strip().lower()
    if key in CHOICES:
        return value if value in CHOICES[key] else None
    if key in LIMITS:
        try:
            n = int(value)
        except ValueError:
            return None
        lo, hi = LIMITS[key]
        return str(n) if lo <= n <= hi else None
    return None


def read_settings(path=None):
    values = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                key = key.strip()
                if sep and key in DEFAULTS and check_value(key, value) is not None:
                    values[key] = check_value(key, value)
    except OSError:
        pass
    return values


def write_setting(key, value, path=None):
    path = path or CONF
    norm = check_value(key, value) if key in DEFAULTS else None
    if norm is None:
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting {key!r} (one of: {', '.join(DEFAULTS)})")
        raise ValueError(f"{key} must be " + ("|".join(CHOICES[key]) if key in CHOICES else "%d-%d" % LIMITS[key]))
    values = read_settings(path)
    values[key] = norm
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as handle:
        handle.write("# Live suggestions (scripts/suggest.py; Settings > Live suggestions writes this).\n")
        handle.writelines(f"{k}={v}\n" for k, v in values.items() if v != DEFAULTS[k])
    os.replace(path + ".tmp", path)
    return norm


def kinds_on(values):
    return {k for k in KINDS if values.get(k) == "on"}


def number(values, key):
    return int(values.get(key, DEFAULTS[key]))


# -- learning ---------------------------------------------------------------------------------
def load_learn(path=None):
    try:
        with open(path or LEARN) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_learn(learn, path=None):
    path = path or LEARN
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(learn, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def stats(learn, kind):
    st = learn.get(kind)
    base = {"shown": 0, "acted": 0, "dismissed": 0, "ignored": 0, "streak": 0, "until": 0}
    return {**base, **st} if isinstance(st, dict) else base


def rest_after(streak):
    """How long a kind rests after `streak` dismissals in a row."""
    return min(MAX_REST_S, BASE_REST_S * 2 ** max(0, streak - 1))


def record(learn, kind, outcome, now):
    """acted / dismissed / ignored: the counts, and how long the kind rests."""
    st = stats(learn, kind)
    st["shown"] += 1
    if outcome == "acted":
        st["acted"] += 1
        st["streak"], st["until"] = 0, 0
    elif outcome == "dismissed":
        st["dismissed"] += 1
        st["streak"] += 1
        st["until"] = now + rest_after(st["streak"])
    elif outcome == "ignored":
        st["ignored"] += 1
        if kind != "clipboard":     # a copy's card left alone: you copied to paste, not a "no"
            st["until"] = max(st["until"], now + IGNORED_REST_S)
    learn[kind] = st
    return st


def resting(learn, kind, now):
    return stats(learn, kind)["until"] > now


def score(learn, kind):
    """The kind's priority, scaled by how often you used it (Laplace: a new
    kind is at half its priority, one you always use tends to all of it)."""
    st = stats(learn, kind)
    return PRIORITY.get(kind, 0.5) * (st["acted"] + 1) / (st["acted"] + st["dismissed"] + 0.5 * st["ignored"] + 2)


def pick(pending, values, learn, now, last_shown, snooze_until=0):
    """The candidate to show now, or None. A clipboard card (your own copy)
    skips the gap; everything else waits gap_min after the last card. A
    kind resting after an x waits, the clipboard's too."""
    if now < snooze_until:
        return None
    on = kinds_on(values)
    gap = number(values, "gap_min") * 60
    best = None
    for cand in pending.values():
        kind = cand["kind"]
        if kind not in on or cand.get("expires", now + 1) < now or now < cand.get("not_before", 0):
            continue
        if (kind != "clipboard" and now - last_shown < gap) or resting(learn, kind, now):
            continue
        if best is None or score(learn, kind) > score(learn, best["kind"]):
            best = cand
    return best


# -- the desktop ------------------------------------------------------------------------------
def hyprctl_json(*args):
    try:
        out = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True, timeout=2).stdout
        return json.loads(out or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def socket_path():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.path.join(RUNTIME, "hypr")
    if not sig:
        try:
            sig = sorted(os.listdir(base))[-1]
        except (OSError, IndexError):
            return None
    return os.path.join(base, sig, ".socket2.sock")


def dnd_on():
    try:
        out = subprocess.run(["makoctl", "mode"], capture_output=True, text=True, timeout=2).stdout
        return "do-not-disturb" in out.split()
    except (OSError, subprocess.SubprocessError):
        return False


def fullscreen_mode(win):
    """Is this activewindow / client really fullscreen? Hyprland's mode is
    a bit set (1 maximized, 2 fullscreen); a maximized window is not."""
    try:
        return bool(int((win or {}).get("fullscreen") or 0) & 2)
    except (TypeError, ValueError):
        return bool((win or {}).get("fullscreen"))


def gamemode_on():
    answer = hyprctl_json("getoption", "animations:enabled")
    return isinstance(answer, dict) and (answer.get("bool") is False or answer.get("int") == 0)


def process_running(name, proc="/proc"):
    """Is a process called `name` running (its comm)? A /proc scan, no fork."""
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
            continue
    return False


def slept_offset():
    """CLOCK_BOOTTIME - CLOCK_MONOTONIC: grows by the time spent asleep."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()


def is_private(cls, title):
    """activity-log.py's rule (with the Privacy page's list) and password
    managers. Unsure counts as private."""
    if SECRET_APPS.search(cls or ""):
        return True
    try:
        privacy = _module("privacy_settings", "privacy_settings.py")
        activity = _module("activity_log", "activity-log.py")
        return activity.is_private(cls or "", title or "", privacy.excluded(privacy.load()))
    except Exception:       # noqa: BLE001
        return True


def app_name(cls):
    """A readable name for a window class: org.mozilla.firefox -> Firefox."""
    tail = (cls or "").split(".")[-1].replace("-", " ").replace("_", " ")
    return tail[:1].upper() + tail[1:] if tail else "the window"


def short(text, n=60):
    flat = " ".join((text or "").split())
    return flat if len(flat) <= n else flat[:n - 1] + "…"


def window_folder(client):
    """The folder a terminal / editor window is on, or None (other windows)."""
    sessions = _module("sessions", "sessions.py")
    cls, title, pid = client.get("class") or "", client.get("title") or "", client.get("pid") or 0
    if cls.lower() in sessions.TERMINALS:
        try:
            launch, _key, _note = sessions.terminal_launch(cls, pid, title)
            return launch.get("cwd")
        except Exception:   # noqa: BLE001 -- a window that went away under us
            return None
    if sessions.EDITOR_RE.match(cls):
        paths = sessions.path_args(sessions.cmdline(pid))
        path = paths[-1] if paths else sessions.title_path(title)
        if path and os.path.isfile(path):
            path = os.path.dirname(path)
        return path
    return None


# -- git ----------------------------------------------------------------------------------------
GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
           "GIT_LITERAL_PATHSPECS": "1"}     # a file called ":(glob)*" is a name, not a pattern


def git(repo, *args, timeout=4):
    """git's stdout, or None. GIT_OPTIONAL_LOCKS=0: a status from here never
    takes the index lock out from under a git you are running."""
    try:
        out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout,
                             env={**os.environ, **GIT_ENV})
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def repo_top(folder):
    if not folder or not os.path.isdir(folder):
        return None
    top = git(folder, "rev-parse", "--show-toplevel", timeout=2)
    return top.strip() if top and top.strip() else None


def repo_changes(repo):
    """(signature, oldest change, newest change, count) of the uncommitted
    changes (epoch seconds from the files' mtimes), or None when clean."""
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    if not out:
        return None
    entries = [e for e in out.split("\0") if e]
    paths, skip = [], False
    for entry in entries:
        if skip:                # a rename's second (source) path
            skip = False
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            skip = True
        paths.append(path)
    if not paths:
        return None
    times = []
    for path in paths[:MAX_FILES]:
        full = os.path.join(repo, path.rstrip("/"))
        for candidate_path in (full, os.path.dirname(full)):    # deleted: its folder changed then
            try:
                times.append(os.lstat(candidate_path).st_mtime)
                break
            except OSError:
                continue
    sig = hashlib.sha256(out.encode()).hexdigest()[:16]
    now = time.time()
    return sig, min(times) if times else now, max(times) if times else now, len(paths)


def commit_due(changes, now, after_s):
    """Have the changes sat long enough, and are you not in the middle of
    editing (nothing changed in the last PAUSE_S)?"""
    if not changes:
        return False
    _sig, oldest, newest, _n = changes
    return now - oldest >= after_s and now - newest >= PAUSE_S


def commit_material(repo, looks_secret):
    """(stat, diff, skipped, subjects) for the model: tracked changes against
    HEAD (staged and not), untracked names only, files that look secret
    left out entirely, the diff cut to MAX_DIFF."""
    has_head = git(repo, "rev-parse", "--verify", "-q", "HEAD", timeout=2) is not None
    base = ["HEAD"] if has_head else ["--cached"]
    names = [n for n in (git(repo, "diff", "--name-only", "-z", *base) or "").split("\0") if n]
    untracked = [n for n in (git(repo, "ls-files", "--others", "--exclude-standard", "-z") or "").split("\0") if n]
    safe = [n for n in names if not looks_secret(os.path.join(repo, n))][:MAX_FILES]
    skipped = [n for n in names + untracked if looks_secret(os.path.join(repo, n))]
    stat = git(repo, "diff", "--stat", "--no-color", *base, "--", *safe) if safe else ""
    diff = git(repo, "diff", "--no-color", "--no-ext-diff", "-U2", *base, "--", *safe) if safe else ""
    diff = diff or ""
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + f"\n[... {len(diff) - MAX_DIFF} more characters of diff cut ...]"
    new = [n for n in untracked if n not in skipped][:30]
    if new:
        stat = (stat or "") + "\nNew files (not yet added): " + ", ".join(new)
    subjects = [s for s in (git(repo, "log", "-6", "--format=%s", timeout=2) or "").splitlines() if s]
    return (stat or "").strip(), diff, skipped, subjects


def commit_prompt(repo, stat, diff, subjects):
    style = ("\n\nRecent commit subjects in this repo (match their style and language):\n"
             + "\n".join(f"- {s}" for s in subjects)) if subjects else ""
    return (f"Write the commit message for these changes in the repo {os.path.basename(repo)}."
            f"{style}\n\n=== git diff --stat ===\n{stat}\n\n=== git diff ===\n{diff}")


def clean_message(text):
    text = re.sub(r"^```\w*\n?|\n?```$", "", (text or "").strip()).strip()
    lines = [l.rstrip() for l in text.splitlines()
             if not re.match(r"(co-authored-by|signed-off-by|generated with)", l.strip(), re.I)]
    return "\n".join(lines).strip()


def draft_commit(repo):
    """(message, model name) or (None, why not). Blocking: the strip runs it
    in a thread."""
    worker = _module("llm_worker", "llm-worker.py")
    stat, diff, skipped, subjects = commit_material(repo, worker.looks_secret)
    if not stat and not diff:
        return None, "nothing to describe (only files that look secret, or no changes any more)"
    model, why = worker.ready("worker")
    if model is None:
        return None, why
    try:
        text = worker.ask(model, commit_prompt(repo, stat, diff, subjects), system=COMMIT_SYSTEM)
    except Exception as exc:    # noqa: BLE001 -- shown on the card
        return None, f"the model did not answer ({exc.__class__.__name__})"
    text = clean_message(text)
    if not text:
        return None, "the model gave an empty answer"
    who = model.name + (f"; {len(skipped)} file(s) that look secret left out" if skipped else "")
    return text, who


# -- the candidates -------------------------------------------------------------------------------
def candidate(kind, key, title, body, actions, now, **extra):
    return {"kind": kind, "key": key, "title": title, "body": body, "icon": ICONS.get(kind, ""),
            "actions": [list(a) for a in actions][:3], "expires": now + EXPIRE.get(kind, 300), **extra}


def commit_candidate(repo, changes, now):
    _sig, _oldest, _newest, n = changes
    name = os.path.basename(repo)
    return candidate("commit", f"commit:{repo}", f"{name}: {n} uncommitted change{'s' if n != 1 else ''}",
                     "A local model can draft the commit message from the diff.",
                     [("draft", "Draft a commit message", repo)], now, repo=repo)


def resume_candidate(away_s, last, still_open, focused_addr, now):
    """`last`: the window that had the focus before you left (address,
    class, title, private), or None."""
    mins = int(away_s // 60)
    span = f"{mins // 60} h {mins % 60} min" if mins >= 60 else f"{mins} min"
    actions, body = [], "Welcome back."
    if last and last.get("class"):
        app = app_name(last["class"])
        body = f"You were in {app}" + ("." if last.get("private") or not last.get("title")
                                        else f": {short(last['title'], 70)}")
        if still_open and last.get("address") and last["address"] != focused_addr:
            actions.append(("focus", f"Go back to {app}", last["address"]))
    actions.append(("focus_round", "Start a focus round", ""))
    return candidate("resume", "resume", f"Away {span}: pick up where you left off", body, actions, now,
                     not_before=now + RESUME_DELAY_S, expires=now + RESUME_DELAY_S + EXPIRE["resume"])


def context_candidate(name, now):
    return candidate("context", f"context:{name}", f"In {name}",
                     "A focus round keeps the notifications quiet while it runs.",
                     [("focus_round", "Start a focus round", "")], now)


def meeting_candidate(event, now):
    start = dt.datetime.fromtimestamp(event["start"])
    mins = max(0, round((event["start"] - now) / 60))
    return candidate("meeting", f"meeting:{event['key']}", f"{short(event['summary'], 50)} at {start:%H:%M}",
                     f"Starts in {mins} min.", [("dnd", "Do Not Disturb on", ""), ("calendar", "Open the calendar", "")],
                     now, expires=min(event["start"], now + EXPIRE["meeting"]))


def clipboard_candidate(card, now):
    """smart-clipboard.py's card as a candidate: its own actions, run by its
    own run_action (clip:<id>)."""
    actions = [(f"clip:{a[0]}", a[1], a[2]) for a in card.get("actions") or [] if len(a) == 3]
    return candidate("clipboard", "clipboard", card.get("title") or "Copied", card.get("body") or "",
                     actions, now, swatch=card.get("swatch"), text=card.get("text") or "",
                     clip_kind=card.get("kind"))


def focus_candidate(card, now):
    """focus-guard.py's offer: its numbers in words, one button."""
    try:
        minutes = max(1, min(240, int(card.get("minutes") or 25)))
        switches, groups, window = int(card.get("switches") or 0), int(card.get("groups") or 0), \
            int(card.get("window_min") or 20)
    except (TypeError, ValueError):
        minutes, switches, groups, window = 25, 0, 0, 20
    return candidate("focus", "focus", "Lots of switching lately",
                     f"{switches} switches between {groups} things in {window} min. A focus block dims the "
                     "distractions and holds the notifications.",
                     [("focus_block", f"Focus {minutes} min", str(minutes))], now)


SAMPLES = {
    "commit": lambda now: candidate("commit", "sample", "atlas: 3 uncommitted changes",
                                    "A local model can draft the commit message from the diff.",
                                    [(SAMPLE_ACTION, "Draft a commit message", "")], now),
    "resume": lambda now: candidate("resume", "sample", "Away 42 min: pick up where you left off",
                                    "You were in Firefox: Release notes draft",
                                    [(SAMPLE_ACTION, "Go back to Firefox", ""),
                                     (SAMPLE_ACTION, "Start a focus round", "")], now),
    "clipboard": lambda now: candidate("clipboard", "sample", "Colour", "#00f0ff  ·  rgb(0 240 255)",
                                       [(SAMPLE_ACTION, "Copy as rgb(0 240 255)", "")], now, swatch="#00f0ff"),
    "context": lambda now: candidate("context", "sample", "In atlas",
                                     "A focus round keeps the notifications quiet while it runs.",
                                     [(SAMPLE_ACTION, "Start a focus round", "")], now),
    "meeting": lambda now: candidate("meeting", "sample", "Team sync at 15:30", "Starts in 10 min.",
                                     [(SAMPLE_ACTION, "Do Not Disturb on", ""),
                                      (SAMPLE_ACTION, "Open the calendar", "")], now),
    "focus": lambda now: candidate("focus", "sample", "Lots of switching lately",
                                   "34 switches between 6 things in 20 min. A focus block dims the distractions "
                                   "and holds the notifications.", [(SAMPLE_ACTION, "Focus 25 min", "")], now),
}


# -- the daemon ----------------------------------------------------------------------------------------
class Daemon:
    """The facts (focus, fullscreen, share, lock, sleep, context) from the
    event socket and the tick, the waiting candidates, and the strip."""

    def __init__(self, values=None, learn=None, clock=time.time):
        self.clock = clock
        self.values = values or read_settings()
        self.learn = load_learn() if learn is None else learn
        self.pending = {}
        self.strip = None           # (Popen, candidate, buffer)
        self.last_shown = 0.0
        self.snooze_until = 0.0
        self.fullscreen = False
        self.sharing = False
        self.locked = False
        self.away_from = None
        self.offset = slept_offset()
        self.focus = None           # {"address", "class", "title", "private"} (memory only)
        self.before_away = None
        self.dwell = None           # (address, at)
        self.repo = None            # (top, next check)
        self.repos = {}             # top -> {"offered": t, "sig": ...}
        self.context = self._context_name()
        self.context_mtime = self._context_mtime()
        self.next_meeting = 0.0
        self.meetings_seen = set()
        self.meeting_proc = None    # (Popen, started) of the calendar reader
        self.quiet_recheck = 0.0

    # -- facts ---------------------------------------------------------------------------
    def reload(self):
        self.values = read_settings()
        self.learn = load_learn()
        if self.strip and self.strip[1]["kind"] not in kinds_on(self.values) and not self.strip[1].get("sample"):
            self.hide("kind switched off")

    def quiet_reason(self):
        """Why nothing may show now ("" when something may): the cheap facts
        first, the two that ask another process only when those pass."""
        if self.clock() < self.snooze_until:
            return "snoozed"
        if self.locked:
            return "locked"
        if self.fullscreen:
            return "fullscreen"
        if self.sharing:
            return "screen shared"
        if dnd_on():
            return "do not disturb"
        if gamemode_on():
            return "gamemode"
        return ""

    def event(self, line):
        name, _, data = line.partition(">>")
        now = self.clock()
        if name == "activewindowv2":
            addr = "0x" + data.strip() if data and not data.startswith("0x") else data.strip()
            self.dwell = (addr, now) if ADDRESS.match(addr or "") else None
        elif name == "fullscreen":
            # the event says 1 for a maximized window too: ask which (unsure: fullscreen)
            win = hyprctl_json("activewindow") if data.strip() == "1" else None
            self.fullscreen = data.strip() == "1" and (not isinstance(win, dict) or fullscreen_mode(win))
            if self.fullscreen:
                self.hide("fullscreen")
        elif name == "screencast":
            self.sharing = data.split(",")[0] == "1"
            if self.sharing:
                self.hide("screen shared")

    def settle_focus(self, now):
        """The window that kept the focus DWELL_S: remembered (for resume) and,
        when it is a terminal / editor on a repo, the repo looked at."""
        if not self.dwell or now - self.dwell[1] < DWELL_S:
            return
        self.dwell = None
        win = hyprctl_json("activewindow")
        if not isinstance(win, dict) or not win.get("address"):
            return
        cls, title = win.get("class") or "", win.get("title") or ""
        private = is_private(cls, title)
        self.focus = {"address": win["address"], "class": cls, "title": "" if private else title,
                      "private": private}
        self.fullscreen = fullscreen_mode(win)
        if private or "commit" not in kinds_on(self.values):
            self.repo = None
            return
        top = repo_top(window_folder(win))
        self.repo = (top, now) if top else None
        if top:
            self.check_repo(now)

    def check_repo(self, now):
        top = self.repo[0]
        self.repo = (top, now + REPO_RECHECK_S)
        changes = repo_changes(top)
        rec = self.repos.setdefault(top, {"offered": 0, "sig": ""})
        if not changes:
            self.repos[top] = {"offered": 0, "sig": ""}     # committed: may be offered again
            self.pending.pop(f"commit:{top}", None)
            return
        if now - rec["offered"] < REPO_REST_S or rec["sig"] == changes[0]:
            return
        if commit_due(changes, now, number(self.values, "commit_after_min") * 60):
            self.offer(commit_candidate(top, changes, now))

    def check_away(self, now):
        """Lock and sleep: when you leave (the focus is kept), when you come
        back (a resume card, if you were away long enough)."""
        offset = slept_offset()
        slept, self.offset = offset - self.offset, offset
        if slept > 60 and self.away_from is None:
            self.away_from = now - slept
            self.before_away = self.focus
        locked = process_running("hyprlock")
        if locked and not self.locked and self.away_from is None:
            self.away_from = now
            self.before_away = self.focus
        if locked and not self.locked:
            self.hide("locked")
        self.locked = locked
        if not locked and self.away_from is not None:
            away, self.away_from = now - self.away_from, None
            if away >= number(self.values, "away_min") * 60 and "resume" in kinds_on(self.values):
                last = self.before_away
                clients = hyprctl_json("clients") or []
                still = bool(last) and any(c.get("address") == last.get("address") for c in clients)
                win = hyprctl_json("activewindow")
                focused = win.get("address") if isinstance(win, dict) else None
                self.offer(resume_candidate(away, last, still, focused, now))

    def _context_mtime(self):
        try:
            return os.stat(CONTEXTS_STATE).st_mtime_ns
        except OSError:
            return None

    def _context_name(self):
        try:
            with open(CONTEXTS_STATE) as handle:
                data = json.load(handle)
            return (data.get("name") or "") if isinstance(data, dict) else ""
        except (OSError, ValueError):
            return ""

    def check_context(self, now):
        mtime = self._context_mtime()
        if mtime == self.context_mtime:
            return
        self.context_mtime = mtime
        name = self._context_name()
        if name and name != self.context and "context" in kinds_on(self.values):
            self.offer(context_candidate(name, now))
        self.context = name

    def check_meetings(self, now):
        """Start the calendar reader (its own process: Evolution can be slow,
        and the loop must keep answering the smart clipboard), and on a
        later tick take what it found."""
        if self.meeting_proc:
            proc, started = self.meeting_proc
            if proc.poll() is None:
                if now - started > MEETING_TIMEOUT_S:
                    proc.kill()
                    proc.wait()
                    self.meeting_proc = None
                return
            self.meeting_proc = None
            try:
                out, _err = proc.communicate(timeout=1)
                events = json.loads(out or "[]")
            except (OSError, subprocess.SubprocessError, ValueError):
                return
            self.take_meetings(events, now)
            return
        if "meeting" not in kinds_on(self.values) or now < self.next_meeting:
            return
        self.next_meeting = now + MEETING_EVERY_S
        lead = number(self.values, "meeting_lead_min")
        try:
            proc = subprocess.Popen([sys.executable, SELF, "events", str(lead)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return
        self.meeting_proc = (proc, now)

    def take_meetings(self, events, now):
        for ev in events if isinstance(events, list) else []:
            if isinstance(ev, dict) and ev.get("key") and ev["key"] not in self.meetings_seen:
                self.meetings_seen.add(ev["key"])
                self.offer(meeting_candidate(ev, now))

    def tick(self, now):
        self.check_away(now)
        self.check_context(now)
        if self.repo and now >= self.repo[1]:
            self.check_repo(now)
        self.check_meetings(now)
        for key in [k for k, c in self.pending.items() if c["expires"] < now]:
            del self.pending[key]

    # -- candidates and the strip --------------------------------------------------------------
    def offer(self, cand):
        if cand["kind"] in kinds_on(self.values):
            self.pending[cand["key"]] = cand

    def clipboard(self, card):
        """smart-clipboard.py's hand-over. True: the strip takes it (shown, or
        swallowed by the quiet rules, as the strip's own would be)."""
        if "clipboard" not in kinds_on(self.values):
            return False
        now = self.clock()
        if self.strip and b'"acted"' not in self.strip[2]:
            self.hide("a newer copy")   # (unless you are using that); not waited for: the reply is due now
        self.quiet_recheck = 0.0
        self.offer(clipboard_candidate(card, now))
        return True

    def maybe_show(self):
        now = self.clock()
        if self.strip or not self.pending:
            return
        cand = pick(self.pending, self.values, self.learn, now, self.last_shown, self.snooze_until)
        if cand is None or now < self.quiet_recheck:
            return
        reason = self.quiet_reason()
        if reason in ("do not disturb", "gamemode"):    # (makoctl / hyprctl: not every second while it waits)
            self.quiet_recheck = now + QUIET_RECHECK_S
        if reason:
            return
        del self.pending[cand["key"]]
        if cand["kind"] == "commit":
            changes = repo_changes(cand["repo"])
            if not changes:
                return
            self.repos[cand["repo"]] = {"offered": now, "sig": changes[0]}
        self.show(cand)

    def show(self, cand):
        payload = {"card": cand, "position": self.values["position"], "show_s": number(self.values, "show_s")}
        try:
            proc = subprocess.Popen([sys.executable, SELF, "strip"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            proc.stdin.write(json.dumps(payload).encode())      # stdin, not argv: argv is world-readable
            proc.stdin.close()
        except OSError as exc:
            log(f"the strip did not start: {exc}")
            return
        os.set_blocking(proc.stdout.fileno(), False)
        self.strip = (proc, cand, b"")
        if not cand.get("sample"):
            self.last_shown = self.clock()

    def hide(self, why=""):
        """The card goes without counting for or against its kind."""
        if not self.strip:
            return
        proc, cand, _buf = self.strip
        cand["hidden"] = True
        try:
            proc.terminate()
        except OSError:
            pass

    def end_now(self):
        """hide(), and wait for the strip to be gone (so a new one can come)."""
        if not self.strip:
            return
        self.hide()
        try:
            self.strip[0].wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.strip[0].kill()
        self.strip_output()

    def strip_output(self):
        """Read what the strip said; on its end, learn from it."""
        proc, cand, buf = self.strip
        try:
            chunk = proc.stdout.read() or b""
        except (OSError, ValueError):
            chunk = b""
        buf += chunk
        self.strip = (proc, cand, buf)
        if chunk and proc.poll() is None:
            return
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc.stdout.close()
        self.strip = None
        outcome = "ignored"
        for line in buf.decode("utf-8", "replace").splitlines():
            try:
                outcome = json.loads(line).get("result") or outcome
            except (ValueError, AttributeError):
                continue
        if cand.get("sample") or (cand.get("hidden") and outcome == "ignored"):
            return
        log(f"{cand['kind']} card: {outcome}")         # the kind only, never what it said
        if outcome in ("acted", "dismissed", "ignored"):
            record(self.learn, cand["kind"], outcome, self.clock())
            save_learn(self.learn)

    def status(self):
        return {"showing": self.strip[1]["kind"] if self.strip else None,
                "pending": sorted({c["kind"] for c in self.pending.values()}),
                "quiet": self.quiet_reason(), "snooze_until": self.snooze_until,
                "locked": self.locked, "fullscreen": self.fullscreen, "sharing": self.sharing}

    def request(self, msg):
        """One message on suggest.sock -> the reply."""
        op = msg.get("op")
        if op == "clipboard" and isinstance(msg.get("card"), dict):
            return {"taken": self.clipboard(msg["card"])}
        if op == "focus" and isinstance(msg.get("card"), dict):
            if "focus" not in kinds_on(self.values):
                return {"taken": False}
            self.offer(focus_candidate(msg["card"], self.clock()))
            return {"taken": True}
        if op == "reload":
            self.reload()
            return {"ok": True}
        if op == "status":
            return self.status()
        if op == "snooze":
            minutes = int(msg.get("minutes") or 0)
            self.snooze_until = self.clock() + minutes * 60 if minutes > 0 else 0.0
            if minutes > 0:
                self.hide("snoozed")
            return {"ok": True, "snooze_until": self.snooze_until}
        if op == "sample":
            kind = msg.get("kind") if msg.get("kind") in SAMPLES else "commit"
            self.end_now()
            cand = SAMPLES[kind](self.clock())
            cand["sample"] = True
            self.show(cand)
            return {"ok": True}
        return {"error": f"no op {op!r}"}


def serve():
    """The daemon's loop: Hyprland's event socket, suggest.sock, the strip's
    stdout, SIGUSR1/SIGTERM through a wake-up socket, and the tick."""
    wake_r, wake_w = socket.socketpair()
    wake_r.setblocking(False)
    wake_w.setblocking(False)
    flags = {"reload": False, "stop": False}

    def on_signal(signum, _frame):
        flags["stop" if signum == signal.SIGTERM else "reload"] = True
    signal.signal(signal.SIGUSR1, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    signal.set_wakeup_fd(wake_w.fileno())

    try:
        os.unlink(SOCK)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        server.bind(SOCK)
    finally:
        os.umask(old)
    server.listen(4)
    daemon = Daemon()
    win = hyprctl_json("activewindow")
    if isinstance(win, dict) and ADDRESS.match(win.get("address") or ""):
        daemon.dwell = (win["address"], 0.0)       # the window focused now, looked at first
    log("watching (kinds on: " + (", ".join(sorted(kinds_on(daemon.values))) or "none") + ")")
    hypr, buf, next_tick = None, b"", 0.0
    try:
        while not flags["stop"]:
            if hypr is None:
                hypr, buf = connect_events(), b""
            now = daemon.clock()
            waits = [next_tick - now, 2.0 if hypr is None else TICK_S]
            if daemon.dwell:
                waits.append(daemon.dwell[1] + DWELL_S - now)
            if daemon.pending and not daemon.strip:
                waits.append(1.0)
            watch = [wake_r, server] + ([hypr] if hypr else []) + ([daemon.strip[0].stdout] if daemon.strip else [])
            try:
                ready, _, _ = select.select(watch, [], [], max(0.05, min(waits)))
            except InterruptedError:
                ready = []
            if wake_r in ready:
                try:
                    while wake_r.recv(64):
                        pass
                except BlockingIOError:
                    pass
            if flags["reload"]:
                flags["reload"] = False
                daemon.reload()
            if hypr is not None and hypr in ready:
                try:
                    chunk = hypr.recv(65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    hypr.close()
                    hypr = None         # Hyprland restarted: reconnect
                else:
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        daemon.event(line.decode("utf-8", "replace"))
            if server in ready:
                handle_client(server, daemon)
            if daemon.strip and daemon.strip[0].stdout in ready:
                daemon.strip_output()
            now = daemon.clock()
            daemon.settle_focus(now)
            if now >= next_tick:
                next_tick = now + TICK_S
                daemon.tick(now)
            daemon.maybe_show()
    finally:
        daemon.hide("stopping")
        try:
            os.unlink(SOCK)
        except OSError:
            pass


def connect_events():
    """Hyprland's event socket, connected, or None (not up yet)."""
    path = socket_path()
    if not path:
        return None
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
    except OSError:
        sock.close()
        return None
    return sock


def handle_client(server, daemon):
    try:
        conn, _ = server.accept()
    except OSError:
        return
    with conn:
        conn.settimeout(1.0)
        data = b""
        try:
            while not data.endswith(b"\n") and len(data) < 400_000:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            msg = json.loads(data or b"{}")
            reply = daemon.request(msg) if isinstance(msg, dict) else {"error": "not an object"}
        except (OSError, ValueError, TypeError) as exc:
            reply = {"error": exc.__class__.__name__}
        try:
            conn.sendall(json.dumps(reply).encode() + b"\n")
        except OSError:
            pass


def ask_daemon(msg, timeout=1.0, path=None):
    """Send one message to the running daemon; its reply, or None."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(path or SOCK)
            sock.sendall(json.dumps(msg).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data or b"null")
    except (OSError, ValueError):
        return None


# -- the actions (the strip runs them) ------------------------------------------------------------------
def spawn(*argv):
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def copy_text(text):
    """wl-copy, marked as our own so the smart clipboard offers nothing for it."""
    try:
        _module("smart_clipboard", "smart-clipboard.py").remember_own(text)
    except Exception:       # noqa: BLE001 -- only a card too many
        pass
    subprocess.run(["wl-copy"], input=text.encode(), timeout=5)


def allowed(card, action, arg):
    """Is (action, arg) one the card offered? The strip only runs those."""
    return any(a[0] == action and a[2] == arg for a in card.get("actions") or [])


def run_action(card, action, arg):
    """One of the catalog's actions. Returns a line for the card, or "" to
    close it. "draft" is the strip's own (it needs the card)."""
    if action == SAMPLE_ACTION:
        return "This is a sample: nothing was done."
    if action == "focus":
        if not ADDRESS.match(arg or ""):
            return "Not a window."
        subprocess.run(["hyprctl", "dispatch", f"hl.dsp.focus({{ window = 'address:{arg}' }})"],
                       capture_output=True, timeout=3)
        return ""
    if action == "focus_round":
        spawn(sys.executable, TIMERS, "focus")
        return "Focus round started."
    if action == "focus_block":
        if not re.fullmatch(r"\d{1,3}", arg or "") or not 1 <= int(arg) <= 240:
            return "Not a length."
        spawn(sys.executable, FOCUS_GUARD, "start", arg, "--suggested")
        return "Focus block started."
    if action == "dnd":
        spawn(sys.executable, NOTIFY_SETTINGS, "dnd", "on")
        return "Do Not Disturb is on."
    if action == "calendar":
        spawn("gnome-calendar")
        return ""
    if action == "terminal":
        if not os.path.isdir(arg or ""):
            return "That folder is gone."
        spawn(sys.executable, DEFAULT_APPS, "run", "terminal", "--dir", arg)
        return ""
    if action.startswith("clip:"):
        clip = _module("smart_clipboard", "smart-clipboard.py")
        return clip.run_action(action[5:], arg, card.get("text") or "")
    return ""


# -- the strip ------------------------------------------------------------------------------------------
def strip():
    data = json.loads(sys.stdin.read() or "{}")
    card = data.get("card")
    if not card:
        return
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    import panelui
    panelui.load_css()
    said = {"done": False}

    def say(result, action=""):
        if not said["done"]:
            said["done"] = True
            print(json.dumps({"result": result, "action": action}), flush=True)

    win = Gtk.Window()
    win.set_name("panel-window")
    win.set_app_paintable(True)
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_namespace(win, "waybar-panel")
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    position = data.get("position") if data.get("position") in POSITIONS else DEFAULTS["position"]
    vertical, horizontal = position.split("-")
    edges = {"top": (GtkLayerShell.Edge.TOP, 44), "bottom": (GtkLayerShell.Edge.BOTTOM, 14),
             "left": (GtkLayerShell.Edge.LEFT, 14), "right": (GtkLayerShell.Edge.RIGHT, 14)}
    for name in (vertical, horizontal):
        if name in edges:
            edge, margin = edges[name]
            GtkLayerShell.set_anchor(win, edge, True)
            GtkLayerShell.set_margin(win, edge, margin)
    mon = _focused_monitor(Gdk)
    if mon:
        GtkLayerShell.set_monitor(win, mon)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_name("panel")
    box.set_size_request(380, -1)
    win.add(box)
    line = Gtk.Box(spacing=10)
    box.pack_start(line, False, False, 0)
    if card.get("swatch"):
        sw = Gtk.DrawingArea()
        sw.set_size_request(20, 20)
        rgba = Gdk.RGBA()
        rgba.parse(card["swatch"])

        def draw(_w, cr):
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1)
            cr.rectangle(0, 0, 20, 20)
            cr.fill()
        sw.connect("draw", draw)
        line.pack_start(sw, False, False, 0)
    elif card.get("icon"):
        icon = Gtk.Label(label=card["icon"])
        icon.get_style_context().add_class("ctl-icon")
        line.pack_start(icon, False, False, 0)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    line.pack_start(texts, True, True, 0)
    head = Gtk.Label(label=card.get("title") or "", xalign=0)
    head.get_style_context().add_class("kb-heading")
    head.set_line_wrap(True)
    head.set_max_width_chars(52)
    texts.pack_start(head, False, False, 0)
    body = Gtk.Label(label=card.get("body") or "", xalign=0)
    body.get_style_context().add_class("ctl-sub")
    body.set_line_wrap(True)
    body.set_max_width_chars(56)
    texts.pack_start(body, False, False, 0)
    close = Gtk.Button(label="✕")
    close.get_style_context().add_class("ctl-link")
    close.set_tooltip_text("Not now (it learns: fewer of these)")
    line.pack_end(close, False, False, 0)
    row = Gtk.Box(spacing=6)
    box.pack_start(row, False, False, 0)

    timer = {"id": None, "busy": False, "leave_s": 4}

    def quit_():
        Gtk.main_quit()
        return False

    def arm(seconds):
        if timer["id"]:
            GLib.source_remove(timer["id"])
        timer["id"] = GLib.timeout_add_seconds(seconds, lambda: (say("ignored"), quit_())[1])

    def buttons(items):
        for child in row.get_children():
            row.remove(child)
        for action, label, arg in items:
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("dev-pick")
            b.connect("clicked", lambda _b, a=action, g=arg: clicked(a, g))
            row.pack_start(b, False, False, 0)
        row.show_all()

    def show_draft(result):
        text, who = result
        timer["busy"] = False
        if text is None:
            head.set_text("No draft")
            body.set_text(who)
            buttons([])
            arm(8)
            return False
        head.set_text(f"Commit message (a draft by {who}: check it)")
        body.set_text(text)
        draft["text"] = text
        timer["leave_s"] = 30       # time to read it; the pointer going off it is no "no"
        buttons([("copy_draft", "Copy", ""), ("copy_terminal", "Copy and open a terminal there", "")])
        arm(90)
        return False

    draft = {"text": "", "repo": ""}

    def clicked(action, arg):
        if action == "copy_draft" or action == "copy_terminal":
            copy_text(draft["text"])
            if action == "copy_terminal" and os.path.isdir(draft["repo"]):
                spawn(sys.executable, DEFAULT_APPS, "run", "terminal", "--dir", draft["repo"])
            quit_()
            return
        if not allowed(card, action, arg):
            return
        if action != SAMPLE_ACTION:
            say("acted", action)
        if action == "draft":
            if repo_top(arg) is None:
                body.set_text("That repo is gone.")
                buttons([])
                arm(5)
                return
            draft["repo"] = arg
            timer["busy"] = True
            if timer["id"]:
                GLib.source_remove(timer["id"])
                timer["id"] = None
            body.set_text("Drafting with the local model… (the first one can take a minute while it loads)")
            buttons([])
            threading.Thread(target=lambda: GLib.idle_add(show_draft, draft_commit(arg)), daemon=True).start()
            return
        if action == "clip:pick":
            win.hide()
            clip = _module("smart_clipboard", "smart-clipboard.py")
            picked = clip._pick_colour(Gtk, Gdk, arg)
            if picked:
                copy_text(picked)
            quit_()
            return
        try:
            text = run_action(card, action, arg)
        except Exception as exc:    # noqa: BLE001 -- shown on the card
            text = f"That did not work ({exc.__class__.__name__})."
        if text:
            body.set_text(text)
            buttons([])
            arm(2)
        else:
            quit_()

    close.connect("clicked", lambda _b: (say("dismissed"), quit_()))
    buttons(card.get("actions") or [])

    def hold(*_a):              # the pointer is on the card: it stays
        if timer["id"]:
            GLib.source_remove(timer["id"])
            timer["id"] = None
        return False

    def leave(_w, event):       # (onto a button inside it is not leaving)
        if event.detail != Gdk.NotifyType.INFERIOR and not timer["busy"]:
            arm(timer["leave_s"])
        return False

    win.connect("enter-notify-event", hold)
    win.connect("leave-notify-event", leave)
    win.connect("delete-event", lambda *_a: quit_())
    signal.signal(signal.SIGTERM, lambda *_a: GLib.idle_add(quit_))
    win.show_all()
    arm(int(data.get("show_s") or DEFAULTS["show_s"]))
    Gtk.main()


def _focused_monitor(Gdk):
    monitors = hyprctl_json("monitors") or []
    origin = next(((m["x"], m["y"]) for m in monitors if m.get("focused")), None)
    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        mon = display.get_monitor(i)
        geo = mon.get_geometry()
        if (geo.x, geo.y) == origin:
            return mon
    return None


# -- the command line -------------------------------------------------------------------------------------
def service_state():
    """(enabled at login, running now) of the unit."""
    def ask(verb):
        try:
            return subprocess.run(["systemctl", "--user", verb, UNIT], capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return ask("is-enabled") == "enabled", ask("is-active") == "active"


def get_settings(now=None):
    now = time.time() if now is None else now
    enabled, active = service_state()
    values = read_settings()
    learn = load_learn()
    live = ask_daemon({"op": "status"}) if active else None
    kinds = []
    for k, (label, default, what) in KINDS.items():
        st = stats(learn, k)
        kinds.append({"kind": k, "label": label, "default": default, "what": what, "on": values[k] == "on",
                      "shown": st["shown"], "acted": st["acted"], "dismissed": st["dismissed"],
                      "ignored": st["ignored"], "resting_until": st["until"] if st["until"] > now else 0})
    return {"on": active, "enabled": enabled, "values": values, "kinds": kinds, "positions": list(POSITIONS),
            "limits": {k: list(v) for k, v in LIMITS.items()}, "live": live}


def set_setting(args):
    if len(args) == 1 and args[0] in ("on", "off"):
        verb = ["enable", "--now"] if args[0] == "on" else ["disable", "--now"]
        out = subprocess.run(["systemctl", "--user", *verb, UNIT], capture_output=True, text=True, timeout=20)
        if out.returncode:
            sys.exit(f"suggest: systemctl failed: {out.stderr.strip()}")
        return
    if len(args) != 2:
        sys.exit("suggest: set on|off, set KIND on|off, or set KEY VALUE (" + ", ".join(DEFAULTS) + ")")
    try:
        write_setting(args[0], args[1])
    except ValueError as exc:
        sys.exit(f"suggest: {exc}")
    ask_daemon({"op": "reload"})


def events(minutes):
    """Calendar events within `minutes`, as JSON (timers.py's reader; run as
    its own process so Evolution's libraries never load into the daemon)."""
    timers = _module("timers", "timers.py")
    out = []
    for start, summary, key in timers.upcoming_events(minutes):
        out.append({"start": start.timestamp(), "summary": summary, "key": key})
    return out


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "daemon":
        serve()
    elif cmd == "strip":
        strip()
    elif cmd == "get":
        data = get_settings()
        if "--json" in args:
            print(json.dumps(data))
        else:
            print(f"live suggestions: {'on' if data['on'] else 'off'}"
                  f"{'' if data['on'] == data['enabled'] else ' (not as at login)'}")
            for k in data["kinds"]:
                print(f"  {k['kind']:<9} {'on ' if k['on'] else 'off'}  {k['label']}  "
                      f"(shown {k['shown']}, used {k['acted']}, sent away {k['dismissed']})")
            print("  " + "  ".join(f"{key}={data['values'][key]}" for key in DEFAULTS if key not in KINDS))
    elif cmd == "set":
        set_setting(args)
    elif cmd == "snooze":
        if len(args) != 1 or not (args[0] in ("off", "toggle") or args[0].isdigit() and 1 <= int(args[0]) <= 480):
            sys.exit("suggest: snooze MINUTES (1..480) | off | toggle")
        minutes = 0 if args[0] == "off" else int(args[0]) if args[0].isdigit() else None
        if minutes is None:             # toggle (the key): an hour, or back on
            live = ask_daemon({"op": "status"}) or {}
            minutes = 0 if live.get("snooze_until", 0) > time.time() else 60
        reply = ask_daemon({"op": "snooze", "minutes": minutes})
        if reply is None:
            sys.exit("suggest: not running")
        if args[0] == "toggle":
            subprocess.run(["notify-send", "-a", "Live suggestions", "-u", "low", "-t", "2500",
                            "Suggestions paused for an hour" if minutes else "Suggestions back on"], timeout=5)
    elif cmd == "sample":
        kind = args[0] if args else "commit"
        if kind not in SAMPLES:
            sys.exit("suggest: sample " + "|".join(SAMPLES))
        if ask_daemon({"op": "sample", "kind": kind}, timeout=5) is None:
            cand = SAMPLES[kind](time.time())       # not running: the strip on its own
            cand["sample"] = True
            values = read_settings()
            proc = subprocess.Popen([sys.executable, SELF, "strip"], stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, start_new_session=True)
            proc.stdin.write(json.dumps({"card": cand, "position": values["position"],
                                         "show_s": number(values, "show_s")}).encode())
            proc.stdin.close()
    elif cmd == "forget":
        try:
            os.remove(LEARN)
        except OSError:
            pass
        ask_daemon({"op": "reload"})
    elif cmd == "status":
        reply = ask_daemon({"op": "status"})
        if "--json" in args:
            print(json.dumps(reply))
        elif reply is None:
            print("suggest: not running")
        else:
            print(f"showing: {reply['showing'] or '-'}  waiting: {', '.join(reply['pending']) or '-'}  "
                  f"quiet: {reply['quiet'] or 'no'}")
    elif cmd == "events":
        print(json.dumps(events(int(args[0]) if args and args[0].isdigit() else 10)))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
