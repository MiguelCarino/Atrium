"""The Smart desktop hub's brain, without GTK: every smart feature of this
desktop in one list, how to read each one's state cheaply, and the command
that really turns it on or off (Settings > Smart desktop,
settings_pages/intelligence.py, draws it; the tests import this module).

Nothing is kept here and no feature is reimplemented: each card reads the
same CLI its own Settings page reads (`suggest.py get --json`,
`presence.py status --json`, ...) and its switch runs the same command that
page's switch runs (`suggest.py set on|off`, `privacy_settings.py presence
on|off`, `systemctl --user enable --now automations.service`, ...). So the
hub, the feature's own page, the keys and the launcher always agree.

    PROBES      name -> the read-only command whose JSON a card reads. Two are
                in-process: "privacy" (privacy_settings.load(): privacy.conf,
                cached on its mtime) and "units" (one `systemctl --user show`
                for the units some cards are). gather(names) runs them in a
                small thread pool (POOL at a time, so a refresh is a couple of
                seconds even with KDE Connect's slow D-Bus, never a stampede of
                processes on a shared machine); a probe that fails or times out
                is None, and its card says "error" instead of guessing.
    FEATURES    one dict per card: id, group, title, icon, line (what it does,
                in plain words), page (the Settings page id "Open settings"
                goes to), probes, keys (description prefixes of its binds in
                `shortcuts.py list --json`, so a key moved in Settings >
                Keyboard shortcuts shows its new keys), and
                    state(p)       -> {"on", "kind", "text", "extras",
                                       "can_toggle", "uses"} (State below)
                    switch(on)     -> [argv, ...] the master switch, or None for
                                      an on-demand tool (nothing runs until its
                                      key is pressed, so there is nothing to
                                      switch: voice typing, ask about the
                                      screen, the mirror, project contexts,
                                      the models page)
                    extra(key, on) -> [argv, ...] for a card's second switches
    STATE       on          the master switch's state (None: on demand)
                kind        running / off / setup / error / demand -- the dot
                text        the status line
                extras      [(key, label, on, sensitive)]
                can_toggle  False when the switch cannot be used yet (Machines
                            before a machine is paired)
                uses        [(sense, label, off-argv or None)]: what this
                            feature is allowed to do with the camera,
                            microphone, screen or clipboard NOW (its switches
                            as they are), for the "Privacy at a glance" strip;
                            the argv turns exactly that off

privacy_view(features, p) folds every card's uses (plus the clipboard
history, which is the Privacy page's own) into the strip, sense by sense,
with what the bar's indicators say is using the camera / microphone right
now. Turning something off never asks: nothing is lost by it. Turning on is
the card's own switch, never the strip's.
"""
import json
import html
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HYPR = os.path.expanduser("~/.config/hypr/scripts")
WAYBAR = os.path.expanduser("~/.config/waybar/scripts")
if HYPR not in sys.path:
    sys.path.insert(0, HYPR)
import privacy_settings  # noqa: E402  (privacy.conf, no GTK)


def script(name):
    return os.path.join(HYPR, name)


ASSISTANT, VOICE, TTS, TASKS = script("assistant.py"), script("voice.py"), script("tts.py"), script("tasks.py")
HEALTH, SUGGEST, FOCUS, AMBIENT = (script("health.py"), script("suggest.py"), script("focus-guard.py"),
                                   script("ambient.py"))
GESTURES, PEERS, PHONE_ASK, PHONE = (script("gestures.py"), script("peers.py"), script("phone-ask.py"),
                                     script("phone.py"))
SMARTCLIP, LAYOUT, PRESENCE, SESSIONS = (script("smart-clipboard.py"), script("smartlayout.py"),
                                         script("presence.py"), script("sessions.py"))
CONTEXTS, PIP, AUTOMATIONS, SCREEN_ASK = (script("contexts.py"), script("pip.py"), script("automations.py"),
                                          script("screen-ask.py"))
PRIVACY, LLM_GPU, SHORTCUTS = script("privacy_settings.py"), script("llm-gpu.py"), script("shortcuts.py")
INDICATORS = os.path.join(WAYBAR, "privacy.py")

SENSES = ("camera", "mic", "screen", "clipboard")
SENSE_TEXT = {"camera": ("", "Camera"), "mic": ("", "Microphone and sound"),
              "screen": ("", "Screen"), "clipboard": ("", "Clipboard")}
KIND_GLYPH = {"running": "●", "off": "○", "setup": "◆", "error": "!", "demand": "◇"}
POOL = 6
GIB = 1024 ** 3
SEEN_S = 300          # a paired machine heard from this recently counts as online
TIMEOUT = 12
# Units some cards ARE (their switch is enable --now / disable --now).
UNITS = ("automations.service", "phone-handoff.service", "desktop-memory.timer", "smartlayout.service",
         "cliphist@text.service", "phone-ask.service")
PROBES = {
    "assistant": [ASSISTANT, "status", "--json"],
    "voice": [VOICE, "status", "--json"],
    "tts": [TTS, "status", "--json"],
    "tasks": [TASKS, "status", "--json"],
    "health": [HEALTH, "status", "--json"],
    "suggest": [SUGGEST, "get", "--json"],
    "focus": [FOCUS, "get", "--json"],
    "ambient": [AMBIENT, "status", "--json"],
    "gestures": [GESTURES, "status", "--json"],
    "peers": [PEERS, "status", "--json"],
    "phoneask": [PHONE_ASK, "status", "--json"],
    "phone": [PHONE, "status", "--json"],
    "smartclip": [SMARTCLIP, "get", "--json"],
    "layout": [LAYOUT, "status", "--json"],
    "presence": [PRESENCE, "status", "--json"],
    "sessions": [SESSIONS, "status", "--json"],
    "contexts": [CONTEXTS, "list", "--json"],
    "automations": [AUTOMATIONS, "list", "--json"],
    "pip": [PIP, "status", "--json"],
    "screenask": [SCREEN_ASK, "which", "--json"],
    "llm": [LLM_GPU, "status", "--json"],
    "binds": [SHORTCUTS, "list", "--json"],
    "mic_now": [INDICATORS, "mic"],
    "camera_now": [INDICATORS, "camera"],
}
ALWAYS = ("privacy", "units", "binds", "mic_now", "camera_now")   # re-read with every card


# -- reading -------------------------------------------------------------------------------
def run_json(argv, timeout=TIMEOUT):
    """A probe's JSON, or None when it fails, times out or prints no JSON.
    `null` (pip.py status with no mirror) comes back as {"none": True}, so
    "answered: nothing" and "did not answer" stay apart."""
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        data = json.loads(res.stdout or "")
    except ValueError:
        return None
    return {"none": True} if data is None else data


def parse_units(text):
    """`systemctl --user show -p Id -p ActiveState -p UnitFileState A B ...`
    -> {unit: {"active": ..., "enabled": ...}}."""
    out, cur = {}, {}
    for line in (text + "\n\n").splitlines():
        if not line.strip():
            if cur.get("Id"):
                out[cur["Id"]] = {"active": cur.get("ActiveState", ""), "enabled": cur.get("UnitFileState", "")}
            cur = {}
            continue
        key, _, value = line.partition("=")
        cur[key] = value
    return out


def read_units():
    try:
        res = subprocess.run(["systemctl", "--user", "show", "-p", "Id", "-p", "ActiveState", "-p",
                              "UnitFileState", *UNITS], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_units(res.stdout)


def probe(name):
    if name == "privacy":
        return privacy_settings.load()
    if name == "units":
        return read_units()
    return run_json(PROBES[name])


def gather(names=None):
    """{probe: result} for these probes (every one when None) plus ALWAYS,
    POOL at a time. Run it off the GTK thread."""
    wanted = sorted(set(names if names is not None else list(PROBES) + ["privacy", "units"]) | set(ALWAYS))
    with ThreadPoolExecutor(max_workers=POOL) as pool:
        return dict(zip(wanted, pool.map(probe, wanted)))


def probes_of(feature_ids):
    return sorted({n for f in FEATURES if f["id"] in feature_ids for n in f["probes"]})


# -- small helpers -------------------------------------------------------------------------
def on(value):
    return value is True or str(value).strip().lower() in ("on", "1", "true", "yes")


def onoff(value):
    return "on" if value else "off"


def unit(p, name):
    return ((p.get("units") or {}).get(name)) or {}


def unit_switch(name, value):
    return [["systemctl", "--user", "enable" if value else "disable", "--now", name]]


def state(on_=None, kind="off", text="", extras=None, can_toggle=True, uses=None):
    return {"on": on_, "kind": kind, "text": text, "extras": extras or [], "can_toggle": can_toggle,
            "uses": uses or []}


def no_answer(what):
    return state(None, "error", f"{what} did not answer (run it in a terminal to see why)", can_toggle=False)


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def keys_for(feature, binds):
    """The live keys of a feature: every bind whose description starts with
    one of its prefixes, in shortcuts.py's order, turned-off ones and the
    release half of a hold-to-talk left out."""
    out = []
    for b in binds or []:
        desc = b.get("desc") or ""
        if b.get("state") == "off" or desc.endswith("(release)") or b.get("submap"):
            continue
        if any(desc.startswith(prefix) for prefix in feature.get("keys", ())) and b.get("keys") not in out:
            out.append(b["keys"])
    return out


# -- the cards' states, one function each --------------------------------------------------
def st_assistant(p):
    d = p.get("assistant")
    if not d:
        return no_answer("assistant.py")
    s = d.get("settings") or {}
    is_on = s.get("enabled", "on") != "off"
    if not is_on:
        return state(False, "off", "off: its key only says it is turned off")
    model = s.get("model", "auto")
    role = (d.get("roles") or {}).get("default" if model == "auto" else model) or {}
    text = "on: answers with " + (role.get("name") or "the local model") + (" (automatic)" if model == "auto" else "")
    uses = []
    if on(s.get("tool_screen", "on")):
        uses.append(("screen", "Assistant: looks at the screen when you ask it to",
                     [ASSISTANT, "set", "tool_screen", "off"]))
    return state(True, "demand", text, uses=uses)


def st_voice(p):
    d = p.get("voice")
    if not d:
        return no_answer("voice.py")
    if not d.get("installed", True):
        return state(bool(d.get("captions")), "setup", "needs setup: the speech model is not installed "
                     "(Settings > Voice typing)")
    uses, busy = [], d.get("state") not in (None, "", "idle", "off")
    if d.get("state") == "recording":
        uses.append(("mic", "Voice typing: dictating now", [VOICE, "cancel"]))
    if d.get("captions"):
        uses.append(("mic", "Live captions: listening to what the computer plays", [VOICE, "captions", "off"]))
    if d.get("captions"):
        text, kind = "captions on" + (", dictating now" if busy else ""), "running"
    elif busy:
        text, kind = f"{d.get('state')} now", "running"
    else:
        text, kind = "ready: dictation listens only while you hold or press its key; captions off", "demand"
    return state(bool(d.get("captions")), kind, text, uses=uses)


def st_voice_commands(p):
    d = p.get("voice")
    if not d:
        return no_answer("voice.py")
    s = d.get("settings") or {}
    is_on = on(s.get("commands", "on"))
    extras = [("confirm", "Ask before doing anything", on(s.get("command_confirm", "off")), is_on)]
    if not is_on:
        return state(False, "off", "off: the command key does nothing", extras)
    return state(True, "demand", "on: press the key, say it in Spanish or English", extras,
                 uses=[("mic", "Voice commands: only while you press their key", [VOICE, "set", "commands", "off"])])


def st_tts(p):
    d = p.get("tts")
    if not d:
        return no_answer("tts.py")
    s = d.get("settings") or {}
    is_on = on(s.get("enabled", "on"))
    if not is_on:
        return state(False, "off", "off: nothing is read aloud")
    if not d.get("installed", True):
        return state(True, "setup", "needs setup: no voice installed (Settings > Spoken replies)")
    what = [w for k, w in (("speak_brief", "the brief"), ("speak_commands", "voice commands' answers"),
                           ("speak_selection", "the highlighted text")) if on(s.get(k))]
    text = ("speaking now" if d.get("speaking") else "on: reads " + (", ".join(what) if what else "nothing yet"))
    if d.get("blocked"):
        text += f"  ·  quiet now: {d['blocked']}"
    return state(True, "running" if d.get("speaking") else "demand", text)


def st_phone_ask(p):
    d = p.get("phoneask")
    if not d:
        return no_answer("phone-ask.py")
    is_on = bool(d.get("on"))
    extras = [("screen", "Answers may describe the screen", bool(d.get("screen")), is_on)]
    if not is_on:
        return state(False, "off", "off: questions from the phone are not answered", extras)
    uses = [("screen", "Ask from the phone: describing the screen", [PHONE_ASK, "screen", "off"])] \
        if d.get("screen") else []
    if not d.get("devices"):
        return state(True, "setup", "needs setup: pair a phone in KDE Connect", extras, uses=uses)
    if not d.get("listener"):
        return state(True, "error", "on, but its listener is not running (phone-ask.service)", extras, uses=uses)
    reach = [x["name"] for x in d["devices"] if x.get("reachable")]
    return state(True, "running", "listening" + (f" to {', '.join(reach)}" if reach else ": no phone in reach now"),
                 extras, uses=uses)


def st_memory(p):
    conf = p.get("privacy")
    if conf is None:
        return no_answer("privacy.conf")
    is_on = on(conf.get("memory"))
    ask = on(conf.get("ask"))
    extras = [("ask", "Ask your desktop (search bar \"remember ...\")", ask, True)]
    uses = []
    if ask and on(conf.get("ask_clipboard")):
        uses.append(("clipboard", "Ask your desktop: searches the clipboard history",
                     [PRIVACY, "ask", "clipboard", "off"]))
    if not is_on:
        return state(False, "off", "off: nothing new is remembered", extras, uses=uses)
    names = {"activity": "window titles", "clipboard": "copies", "notifications": "notifications",
             "captions": "captions", "screen": "screenshots"}
    sources = [names[s] for s in privacy_settings.MEMORY_SOURCES if on(conf.get(f"memory_{s}"))]
    if on(conf.get("memory_screen")):
        uses.append(("screen", "Desktop memory: a screenshot's text every "
                     f"{conf.get('memory_screen_minutes', '15')} min", [PRIVACY, "memory", "screen", "off"]))
    if on(conf.get("memory_clipboard")):
        uses.append(("clipboard", "Desktop memory: keeps text copies", [PRIVACY, "memory", "clipboard", "off"]))
    timer = unit(p, "desktop-memory.timer").get("active")
    text = "remembering " + (", ".join(sources) if sources else "nothing (every source is off)")
    text += f"  ·  kept {conf.get('memory_keep_days', '30')} days"
    if timer and timer != "active":
        return state(True, "error", text + "  ·  its timer is " + timer, extras, uses=uses)
    return state(True, "running", text, extras, uses=uses)


def st_screen_ask(p):
    d = p.get("screenask")
    if not d:
        return no_answer("screen-ask.py")
    if not d.get("model"):
        return state(None, "setup", "needs setup: " + (d.get("why") or "no local vision model in LM Studio"))
    return state(None, "demand", f"ready: {d['model'].split('/')[-1]} answers" +
                 (" (loaded)" if d.get("loaded") else " (loaded when you ask)"))


def st_presence(p):
    d = p.get("presence")
    if not d:
        return no_answer("presence.py")
    is_on = bool(d.get("on"))
    if not all((d.get("installed") or {}).values()):
        return state(is_on, "setup", "needs setup: the face detector is not installed (Settings > Presence)")
    if not is_on:
        return state(False, "off", "off: the camera is never opened")
    uses = [("camera", "Presence: looks 1-2 times a second (in memory only)", [PRIVACY, "presence", "off"])]
    svc = d.get("service", "")
    if svc != "active":
        return state(True, "error", f"on, but presence.service is {svc or 'not running'}", uses=uses)
    live = d.get("live") or {}
    text = "watching" + (f": {live['state']}" if isinstance(live, dict) and live.get("state") else "")
    return state(True, "running", text, uses=uses)


def st_gestures(p):
    d = p.get("gestures")
    if not d:
        return no_answer("gestures.py")
    sw = d.get("switches") or {}
    g, z = bool(sw.get("gestures")), bool(sw.get("gaze"))
    extras = [("gaze", "Gaze: focus follows the monitor you look at", z, True)]
    uses = []
    if g:
        uses.append(("camera", "Hand gestures", [PRIVACY, "gestures", "off"]))
    if z:
        uses.append(("camera", "Gaze (which monitor you look at)", [PRIVACY, "gaze", "off"]))
    if not all((d.get("installed") or {}).values()):
        return state(g, "setup", "needs setup: the hand models are not installed (Settings > Gestures & gaze)",
                     extras, uses=uses)
    if not (g or z):
        return state(False, "off", "off: the camera is never opened for them", extras)
    if d.get("service") != "active":
        return state(g, "error", f"on, but presence.service is {d.get('service') or 'not running'}"
                     + (f": {d['why']}" if d.get("why") else ""), extras, uses=uses)
    return state(g, "running", "watching for " + " and ".join(w for w, v in (("gestures", g), ("gaze", z)) if v),
                 extras, uses=uses)


def st_suggest(p):
    d = p.get("suggest")
    if not d:
        return no_answer("suggest.py")
    is_on = bool(d.get("on"))
    kinds = [k["label"] for k in d.get("kinds") or [] if k.get("on")]
    if not is_on:
        return state(False, "off", "off: nothing is offered")
    uses = []
    if on((d.get("values") or {}).get("clipboard")):
        uses.append(("clipboard", "Live suggestions: what you copy", [SUGGEST, "set", "clipboard", "off"]))
    text = f"on: {plural(len(kinds), 'kind')} ({', '.join(kinds).lower()})" if kinds else "on, but every kind is off"
    if d.get("on") != d.get("enabled"):
        text += "  ·  not started at login"
    return state(True, "running", text, uses=uses)


def st_smartclip(p):
    d = p.get("smartclip")
    if not d:
        return no_answer("smart-clipboard.py")
    if not d.get("on"):
        return state(False, "off", "off: copies are left alone")
    n = sum(1 for k in d.get("kinds") or [] if k.get("on"))
    return state(True, "running", f"on: recognises {plural(n, 'kind')} of copy",
                 uses=[("clipboard", "Smart clipboard: looks at each copy", [SMARTCLIP, "set", "off"])])


LAYOUT_MODE = {"off": "off", "learn": "learning where you put apps (not placing them)",
               "on": "learning and placing apps when they open"}


def st_layout(p):
    d = p.get("layout")
    if not d:
        return no_answer("smartlayout.py")
    mode = (d.get("settings") or {}).get("mode", "learn")
    extras = [("place", "Put new windows where they usually go", mode == "on", mode != "off")]
    if mode == "off":
        return state(False, "off", "off: nothing is learned or moved", extras)
    n = len(d.get("apps") or [])
    text = f"{LAYOUT_MODE.get(mode, mode)}  ·  {plural(n, 'app')} learned"
    svc = unit(p, "smartlayout.service").get("active")
    if svc and svc != "active":
        return state(True, "error", text + f"  ·  smartlayout.service is {svc}", extras)
    return state(True, "running", text, extras)


def st_contexts(p):
    d = p.get("contexts")
    if not d:
        return no_answer("contexts.py")
    names = [c["name"] for c in d.get("contexts") or []]
    cur = (d.get("current") or {}).get("name") if isinstance(d.get("current"), dict) else d.get("current")
    if cur:
        return state(None, "running", f"in {cur} now")
    if not names:
        return state(None, "setup", "needs setup: make a context for a repo")
    return state(None, "demand", f"{plural(len(names), 'context')} ({', '.join(names[:4])}); in none now")


def st_focus(p):
    d = p.get("focus")
    if not d:
        return no_answer("focus-guard.py")
    conf = p.get("privacy") or {}
    is_on = bool(d.get("on"))
    watch = on(conf.get("focus_watch"))
    extras = [("detect", "Offer a block when I am scattered", watch, is_on)]
    if not is_on:
        return state(False, "off", "off: no focus blocks of its own", extras)
    block = (d.get("live") or {}).get("block")
    if block:
        return state(True, "running", "in a focus block now", extras)
    return state(True, "running" if watch else "demand",
                 "on, noticing" if watch else "on: runs the blocks you start", extras)


def st_tasks(p):
    d = p.get("tasks")
    if not d:
        return no_answer("tasks.py")
    is_on = bool((d.get("settings") or {}).get("enabled"))
    if not is_on:
        return state(False, "off", "off: the daemon idles, nothing is watched")
    daemon = d.get("daemon") or {}
    if not daemon.get("pid"):
        return state(True, "error", "on, but tasks.service is not running")
    running = len(daemon.get("running") or [])
    text = f"on: {plural(running, 'job')} running" if running else "on: waiting for work"
    if d.get("attention"):
        text += f"  ·  {plural(d['attention'], 'task')} need{'s' if d['attention'] == 1 else ''} a look"
    if daemon.get("gamemode"):
        text += "  ·  paused for a game"
    return state(True, "running", text)


def rule(p, rid):
    for r in (p.get("automations") or {}).get("rules") or []:
        if r.get("id") == rid:
            return r
    return None


def st_brief(p):
    d = p.get("automations")
    if not d:
        return no_answer("automations.py")
    brief, journal = rule(p, "daily-brief"), rule(p, "end-of-day")
    b, j = bool(brief and brief["enabled"]), bool(journal and journal["enabled"])
    extras = [("journal", "Write the journal when work hours end", j, True)]
    if not (b or j):
        return state(False, "off", "off: no brief in the morning, no journal", extras)
    text = " and ".join(w for w, v in (("morning brief", b), ("end-of-day journal", j)) if v) + " on"
    if not d.get("running"):
        return state(b, "error", text + ", but automations.service is not running", extras)
    return state(b, "running", text, extras)


def st_sessions(p):
    d = p.get("sessions")
    if not d:
        return no_answer("sessions.py")
    s = d.get("settings") or {}
    auto = bool(s.get("autosave"))
    extras = [("offer", "Offer to restore after login", bool(s.get("offer")), True)]
    n = len(d.get("sessions") or [])
    text = (f"saving every few minutes  ·  {plural(n, 'saved session')}" if auto
            else f"off: no automatic save  ·  {plural(n, 'saved session')}")
    return state(auto, "running" if auto else "off", text, extras)


def st_automations(p):
    d = p.get("automations")
    u = unit(p, "automations.service")
    if not d:
        return no_answer("automations.py")
    is_on = u.get("enabled", "") in ("enabled", "static") or u.get("active") == "active"
    rules = d.get("rules") or []
    n_on = sum(1 for r in rules if r.get("enabled") and not r.get("paused"))
    if not is_on:
        return state(False, "off", f"off: no rule runs (the brief, the journal and the digest neither)  ·  "
                     f"{plural(len(rules), 'rule')}")
    text = f"{n_on} of {plural(len(rules), 'rule')} on"
    if d.get("broken"):
        text += f"  ·  {plural(len(d['broken']), 'rule')} with a problem"
    if u.get("active") != "active":
        return state(True, "error", text + f"  ·  automations.service is {u.get('active') or 'stopped'}")
    return state(True, "error" if d.get("broken") else "running", text)


def st_digest(p):
    d = p.get("automations")
    if not d:
        return no_answer("automations.py")
    r = rule(p, "dnd-digest")
    if not r:
        return state(None, "setup", "needs setup: automations.json has no dnd-digest rule", can_toggle=False)
    if not r["enabled"]:
        return state(False, "off", "off: Do Not Disturb ends quietly")
    return state(True, "running" if d.get("running") else "error",
                 "on: one summary when Do Not Disturb ends" if d.get("running")
                 else "on, but automations.service is not running")


def st_pip(p):
    d = p.get("pip")
    if d is None:
        return no_answer("pip.py")
    if d.get("none") or not d.get("mode"):
        return state(None, "demand", "no mirror up: press its key on a window or a region")
    return state(None, "running", f"mirroring a {d['mode']}: {d.get('title', '')}".rstrip(": "),
                 uses=[("screen", f"Picture-in-picture: mirroring a {d['mode']}", [PIP, "close"])])


def st_ambient(p):
    d = p.get("ambient")
    if not d:
        return no_answer("ambient.py")
    is_on = on((d.get("settings") or {}).get("enabled"))
    svc = d.get("service", "")
    if not is_on:
        return state(False, "off", "off: the desktop looks as you set it")
    if svc != "active":
        return state(True, "error", f"on, but ambient.service is {svc or 'not running'}")
    mood = (d.get("plan") or {}).get("mood") if isinstance(d.get("plan"), dict) else None
    return state(True, "running", "following time, weather and focus" + (f": {mood}" if mood else ""))


def st_health(p):
    d = p.get("health")
    if not d:
        return no_answer("health.py")
    task = d.get("task") or {}
    if not task.get("exists"):
        return state(False, "setup", "needs setup: the nightly checkup task is missing (Settings > Desktop health)")
    findings = (d.get("report") or {}).get("findings") or []
    bad = sum(1 for f in findings if f.get("level") in ("fail", "warn"))
    last = f"  ·  last checkup: {plural(bad, 'thing')} to look at" if d.get("report") else ""
    if not task.get("enabled"):
        return state(False, "off", "off: no nightly checkup" + last)
    if not (d.get("tasks") or {}).get("enabled", True):
        return state(True, "error", "on, but Background tasks is off, so the checkup never runs")
    return state(True, "error" if task.get("last_result") not in (None, "ok") else "running",
                 f"checks every night ({task.get('schedule', 'daily')})" + last)


def st_phone(p):
    d = p.get("phone")
    u = unit(p, "phone-handoff.service")
    is_on = u.get("enabled") == "enabled" or u.get("active") == "active"
    if not d:
        return state(is_on, "error", "phone.py did not answer (run it in a terminal to see why)")
    extras = [("codes", "Offer sign-in codes from the phone's notifications", bool(d.get("codes")), is_on)]
    if not d.get("kdeconnect"):
        return state(is_on, "setup", "needs setup: KDE Connect is not installed (Settings > Devices)", extras)
    if not is_on:
        return state(False, "off", "off: nothing from the phone is followed", extras)
    if u.get("active") != "active":
        return state(True, "error", f"on, but phone-handoff.service is {u.get('active') or 'stopped'}", extras)
    return state(True, "running", f"on: {d['phone']} in reach" if d.get("phone") else "on: no phone in reach now",
                 extras)


def st_machines(p):
    d = p.get("peers")
    if not d:
        return no_answer("peers.py")
    conf = p.get("privacy") or {}
    is_on, peers = bool(d.get("enabled")), d.get("peers") or []
    kvm = d.get("kvm") or {}
    extras = [("kvm", "Shared keyboard and mouse", bool(kvm.get("on")), is_on and bool(kvm.get("installed")))]
    uses = []
    if is_on and on(conf.get("machines_clipboard")):
        uses.append(("clipboard", "Machines: copies go to the paired machines",
                     [PRIVACY, "machines", "clipboard", "off"]))
    if not peers:
        return state(is_on, "setup", "needs setup: pair a machine first (Settings > Machines)", extras,
                     can_toggle=is_on, uses=uses)
    if not is_on:
        return state(False, "off", f"off  ·  {plural(len(peers), 'machine')} paired", extras)
    svc = str(d.get("service", ""))
    if not svc.startswith("active"):
        return state(True, "error", f"on, but peers.service is {svc or 'stopped'}", extras, uses=uses)
    now = time.time()
    up = [x.get("name", "?") for x in peers if x.get("seen") and now - x["seen"] < SEEN_S]
    return state(True, "running", f"{plural(len(peers), 'machine')} paired" + (f", {', '.join(up)} online" if up else ""),
                 extras, uses=uses)


def st_ai(p):
    d = p.get("llm")
    if not d:
        return no_answer("llm-gpu.py")
    gpu = d.get("gpu") or {}
    card = (f"  ·  card {gpu['used'] / GIB:.0f} of {gpu['total'] / GIB:.0f} GB used"
            if gpu.get("total") else "")
    if not d.get("running"):
        return state(None, "off", "LM Studio is not running: the smart features wait or fall back" + card)
    loaded = [m.get("alias") or m.get("key", "?").split("/")[-1] for m in d.get("loaded") or []]
    return state(None, "running" if loaded else "demand",
                 ("loaded: " + ", ".join(loaded) if loaded else "no model loaded: loaded when one is needed") + card)


# -- the cards' switches ---------------------------------------------------------------------
def extra_phone_ask(key, value):
    return [[PHONE_ASK, "screen", onoff(value)]]


def extra_layout(key, value):
    return [[LAYOUT, "set", "mode", "on" if value else "learn"]]


FEATURES = [
    # Assistant & voice
    {"id": "assistant", "group": "Assistant & voice", "title": "Desktop assistant", "icon": "",
     "line": "A chat that knows this desktop: ask in Spanish or English, the local model answers.",
     "page": "assistant", "probes": ["assistant"], "keys": ["Assistant:"], "state": st_assistant,
     "switch": lambda v: [[ASSISTANT, "set", "enabled", onoff(v)]]},
    {"id": "voice", "group": "Assistant & voice", "title": "Voice typing & live captions", "icon": "",
     "line": "Dictate into any window; captions of what the computer plays. The switch is the captions.",
     "page": "voice", "probes": ["voice"], "keys": ["Tools: Voice typing", "Tools: Live captions"],
     "state": st_voice, "switch": lambda v: [[VOICE, "captions", onoff(v)]]},
    {"id": "voice-commands", "group": "Assistant & voice", "title": "Voice commands", "icon": "",
     "line": "Say what the desktop should do; it says what it understood, then does it.",
     "page": "voice", "probes": ["voice"], "keys": ["Tools: Voice command"], "state": st_voice_commands,
     "switch": lambda v: [[VOICE, "set", "commands", onoff(v)]],
     "extra": lambda k, v: [[VOICE, "set", "command_confirm", onoff(v)]]},
    {"id": "speech", "group": "Assistant & voice", "title": "Spoken replies", "icon": "",
     "line": "Reads the brief, answers and the highlighted text aloud, in a local voice.",
     "page": "speech", "probes": ["tts"], "keys": ["Speech:"], "state": st_tts,
     "switch": lambda v: [[TTS, "set", "enabled", onoff(v)]]},
    # Awareness
    {"id": "memory", "group": "Awareness", "title": "Desktop memory", "icon": "",
     "line": "Remembers what went past -- windows, copies, notifications -- so you can ask for it again.",
     "page": "memory", "probes": ["privacy", "units"], "keys": ["Tools: Desktop memory"], "state": st_memory,
     "switch": lambda v: [[PRIVACY, "memory", onoff(v)]],
     "extra": lambda k, v: [[PRIVACY, "ask", onoff(v)]]},
    {"id": "screen-ask", "group": "Awareness", "title": "Ask about the screen", "icon": "",
     "line": "Point at a region or a window and ask what it is; a local vision model answers.",
     "page": "smartclip", "probes": ["screenask"], "keys": ["Screen: Ask a local vision model"],
     "state": st_screen_ask, "switch": None},
    {"id": "presence", "group": "Awareness", "title": "Presence", "icon": "",
     "line": "The webcam tells whether you are at the desk: lock when you go, wake when you are back.",
     "page": "presence", "probes": ["presence"], "keys": ["Privacy: Pause / resume presence"],
     "state": st_presence, "switch": lambda v: [[PRIVACY, "presence", onoff(v)]]},
    {"id": "gestures", "group": "Awareness", "title": "Gestures & gaze", "icon": "",
     "line": "Hand gestures to the webcam, and focus that follows the monitor you look at.",
     "page": "gestures", "probes": ["gestures"], "keys": ["Camera:"], "state": st_gestures,
     "switch": lambda v: [[PRIVACY, "gestures", onoff(v)]],
     "extra": lambda k, v: [[PRIVACY, "gaze", onoff(v)]]},
    {"id": "suggestions", "group": "Awareness", "title": "Live suggestions", "icon": "",
     "line": "A quiet strip offers the next step -- a commit message, where you left off.",
     "page": "suggestions", "probes": ["suggest"], "keys": ["Suggestions:"], "state": st_suggest,
     "switch": lambda v: [[SUGGEST, "set", onoff(v)]]},
    {"id": "smartclip", "group": "Awareness", "title": "Smart clipboard", "icon": "",
     "line": "Copy an address, a parcel number or JSON: a small card offers what to do with it.",
     "page": "smartclip", "probes": ["smartclip"], "keys": [], "state": st_smartclip,
     "switch": lambda v: [[SMARTCLIP, "set", onoff(v)]]},
    {"id": "layout", "group": "Awareness", "title": "Smart window layout", "icon": "",
     "line": "Learns where you put each app and can put it there when it opens.",
     "page": "layout", "probes": ["layout", "units"], "keys": ["Windows: Arrange this workspace"],
     "state": st_layout, "switch": lambda v: [[LAYOUT, "set", "mode", "learn" if v else "off"]],
     "extra": extra_layout},
    # Work
    {"id": "contexts", "group": "Work", "title": "Project contexts", "icon": "",
     "line": "One key puts you in a project: its windows, terminal, editor and only its notifications.",
     "page": "contexts", "probes": ["contexts"], "keys": ["Projects:"], "state": st_contexts, "switch": None},
    {"id": "focus", "group": "Work", "title": "Focus guard", "icon": "",
     "line": "Focus blocks that quiet notifications and dim distractions, and notice when you are scattered.",
     "page": "focus", "probes": ["focus", "privacy"], "keys": ["Focus:"], "state": st_focus,
     "switch": lambda v: [[FOCUS, "set", onoff(v)]],
     "extra": lambda k, v: [[FOCUS, "set", "detect", onoff(v)]]},
    {"id": "tasks", "group": "Work", "title": "Background tasks", "icon": "",
     "line": "Jobs that watch and wait for you: a build to finish, a page to change, a nightly check.",
     "page": "tasks", "probes": ["tasks"], "keys": ["Tasks:"], "state": st_tasks,
     "switch": lambda v: [[TASKS, onoff(v)]]},
    {"id": "brief", "group": "Work", "title": "Daily brief & journal", "icon": "",
     "line": "What you need to start the day when you sit down; a journal entry when work ends.",
     "page": "brief", "probes": ["automations"], "keys": ["Tools: Daily brief", "Tools: Write today's journal"],
     "state": st_brief, "switch": lambda v: [[AUTOMATIONS, "enable" if v else "disable", "daily-brief"]],
     "extra": lambda k, v: [[AUTOMATIONS, "enable" if v else "disable", "end-of-day"]]},
    {"id": "sessions", "group": "Work", "title": "Workspace sessions", "icon": "",
     "line": "Saves the open windows every few minutes and brings them back after a login.",
     "page": "sessions", "probes": ["sessions"],
     "keys": ["Windows: Restore the last session", "Windows: Reopen the last closed window"],
     "state": st_sessions, "switch": lambda v: [[SESSIONS, "set", "autosave", onoff(v)]],
     "extra": lambda k, v: [[SESSIONS, "set", "offer", onoff(v)]]},
    {"id": "automations", "group": "Work", "title": "Automations", "icon": "",
     "line": "\"When X, do Y\" rules: headphones for games, Do Not Disturb in a meeting.",
     "page": "automations", "probes": ["automations", "units"], "keys": [], "state": st_automations,
     "switch": lambda v: unit_switch("automations.service", v)},
    {"id": "digest", "group": "Work", "title": "Notification digest", "icon": "",
     "line": "What Do Not Disturb held back, in one notification when it ends.",
     "page": "notifications", "probes": ["automations"], "keys": ["Notifications: Do not disturb"],
     "state": st_digest, "switch": lambda v: [[AUTOMATIONS, "enable" if v else "disable", "dnd-digest"]]},
    {"id": "pip", "group": "Work", "title": "Picture-in-picture", "icon": "",
     "line": "A small always-on-top live copy of a window or a piece of the screen.",
     "page": "pip", "probes": ["pip"], "keys": ["Windows: Live mirror"], "state": st_pip, "switch": None},
    # Environment
    {"id": "ambient", "group": "Environment", "title": "Ambient desktop", "icon": "",
     "line": "The wallpaper, accent, night light and sound follow the time, the weather and your focus.",
     "page": "ambient", "probes": ["ambient"], "keys": ["Ambient:"], "state": st_ambient,
     "switch": lambda v: [[AMBIENT, "set", onoff(v)]]},
    {"id": "health", "group": "Environment", "title": "Desktop health", "icon": "",
     "line": "A checkup every night: what failed, in plain words, and fixes for you to approve.",
     "page": "health", "probes": ["health"], "keys": ["Health:"], "state": st_health,
     "switch": lambda v: [[HEALTH, "set", "enabled", onoff(v)]]},
    # Devices
    {"id": "phone", "group": "Devices", "title": "Phone handoff", "icon": "",
     "line": "Pages and files go to the phone; what the phone shares lands here (KDE Connect).",
     "page": "devices", "probes": ["phone", "units"], "keys": ["Phone:"], "state": st_phone,
     "switch": lambda v: unit_switch("phone-handoff.service", v),
     "extra": lambda k, v: [[PHONE, "codes", onoff(v)]]},
    {"id": "phone-ask", "group": "Devices", "title": "Ask from the phone", "icon": "",
     "line": "Send the desktop a question from the phone; the answer comes back to it.",
     "page": "devices", "probes": ["phoneask"], "keys": [], "state": st_phone_ask,
     "switch": lambda v: [[PHONE_ASK, onoff(v)]], "extra": extra_phone_ask},
    {"id": "machines", "group": "Devices", "title": "Machines", "icon": "",
     "line": "Several computers as one desktop: send windows, share copies, one keyboard and mouse.",
     "page": "machines", "probes": ["peers", "privacy"], "keys": ["Machines:"], "state": st_machines,
     "switch": lambda v: [[PEERS, "set", "enabled", onoff(v)]],
     "extra": lambda k, v: [[PEERS, "kvm", onoff(v)]]},
    # Models
    {"id": "ai", "group": "Models", "title": "AI & models", "icon": "",
     "line": "The local models every feature above uses, and what is on the graphics card. Never the cloud.",
     "page": "ai", "probes": ["llm"], "keys": [], "state": st_ai, "switch": None},
]
GROUP_ORDER = ["Assistant & voice", "Awareness", "Work", "Environment", "Devices", "Models"]
BY_ID = {f["id"]: f for f in FEATURES}


def feature_state(feature, p):
    """A card's state; a state function that trips over an odd answer is an
    error on that card, never a broken page."""
    try:
        return feature["state"](p)
    except Exception as exc:  # noqa: BLE001  (one card, not the page)
        return state(None, "error", f"could not read it: {type(exc).__name__}: {exc}", can_toggle=False)


def switch_commands(feature_id, value):
    f = BY_ID[feature_id]
    return f["switch"](value) if f.get("switch") else []


def extra_commands(feature_id, key, value):
    f = BY_ID[feature_id]
    return f["extra"](key, value) if f.get("extra") else []


def execute(commands, timeout=60):
    """Run a card's commands in order (argv lists, never a shell): "" when
    all of them worked, else what the first failing one said."""
    for argv in commands:
        try:
            res = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{os.path.basename(argv[0])}: {exc}"
        if res.returncode != 0:
            said = (res.stderr or res.stdout).strip().splitlines()
            return f"{os.path.basename(argv[0])}: " + (said[-1] if said else f"exit {res.returncode}")
    return ""


# -- privacy at a glance ---------------------------------------------------------------------
def now_using(indicator):
    """What the bar's indicator says is using the camera / microphone now:
    its tooltip lines, or [] while idle."""
    if not indicator or indicator.get("class") in (None, "", "idle"):
        return []
    # The tooltip is Pango markup made for the bar: drop the tags, unescape
    # the names, and leave out its "click to focus" hint (not clickable here).
    text = re.sub(r"<[^>]+>", "", indicator.get("tooltip") or "")
    lines = [html.unescape(ln.strip()) for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln != "click to focus the app"]
    return lines[1:] if len(lines) > 1 else (lines or ["in use"])


def privacy_view(states, p):
    """{sense: {"items": [(label, off_argv or None, feature id)], "now": [...]}}
    from the cards' states (feature id -> state) and the probes; the
    clipboard history is added here because it is the Privacy page's."""
    view = {s: {"items": [], "now": []} for s in SENSES}
    for f in FEATURES:
        st = states.get(f["id"])
        for sense, label, off in (st or {}).get("uses") or []:
            if sense in view:
                view[sense]["items"].append((label, off, f["id"]))
    clip = unit(p, "cliphist@text.service")
    if clip.get("active") == "active" or clip.get("enabled") == "enabled":
        view["clipboard"]["items"].insert(0, ("Clipboard history (cliphist)", [PRIVACY, "clipboard", "off"],
                                              "privacy"))
    view["camera"]["now"] = now_using(p.get("camera_now"))
    view["mic"]["now"] = now_using(p.get("mic_now"))
    return view


def sense_summary(sense, entry):
    """The line under a sense in the strip."""
    items, now = entry["items"], entry["now"]
    if now:
        head = "in use now: " + ", ".join(now)
    elif not items:
        return "nothing here may use it on its own"
    else:
        head = "not in use now" if sense in ("camera", "mic") else ""
    may = f"{plural(len(items), 'feature')} may use it" if items else "no smart feature may use it"
    return "  ·  ".join(x for x in (head, may) if x)
