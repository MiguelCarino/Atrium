#!/usr/bin/env python3
"""The mascot's mood: how she feels, what is around her, what she says.

    mascot_mood.py                    what she would feel and say right now,
                                      and every signal behind it
    mascot_mood.py --text "TEXT"      the word matcher's reading of TEXT
    mascot_mood.py --set K=on|off...  switch moods (enabled), random_only or
                                      a signal on or off (Settings below)

llm-chat.py keeps one Mood and asks it, every frame, for a View:

    mood = Mood()
    mood.refresh()                    re-read the surroundings (a worker
                                      thread, about once a minute: the
                                      calendar is a D-Bus round trip)
    mood.react(event, text=..., ...)  something happened in the conversation
    v = mood.view(state)              View(mood, scene, line)

`mood` is one of MOODS. `scene` is a frozenset of SCENES, the things drawn
around her. `line` is None or a topic tuple for the mascot to word:
("rain",), ("event", "Standup", 10), ("go_home", "18:05"), ... see TOPICS;
the mascot's say(topic) phrases it in its own voice (moe: Japanese and
English), and DEFAULT_LINES is the plain English for one without a say().

Where the mood comes from, strongest first:

  1. a reaction    a conversation event, for a few seconds: "thanks" -> shy,
                   a failing tool -> worried (twice in a row: frustrated),
                   success after errors -> relieved, a run past a minute ->
                   determined, a calendar event coming up -> a heads-up
  2. the talk      word matching on your prompts (counted double) and the
                   replies, a score that fades over minutes: happy or sad,
                   worried in between
  3. surroundings  late night -> sleepy, work hours -> focused, a birthday or
                   a holiday -> excited, a storm -> worried, the morning ->
                   happy
  4. chance        when nothing else has a say, a new mood every few minutes
                   (mostly calm)

While the model works (thinking, tool, writing) sleepy turns to focused: she
does not doze off on the job.

The surroundings are files the bar already keeps fresh -- no network calls
of its own: $XDG_RUNTIME_DIR/waybar-weather-raw.json (wttr.py: condition,
temperature, sunrise and sunset), waybar-sensors/gpu.hist and cpu.hist
(temperatures, the watch-mode history), waybar-player/state.json (music), plus
workhours.py's state() and holiday(), `gamemoded -s`, and Evolution's local
calendars through EDS (events in the next 15 minutes, birthdays today).

Settings: ~/.local/state/hypr/mascot.json, every key optional --

    {"enabled": true,
     "signals": {"talk": true, "weather": true, "time": true,
                 "calendar": true, "workhours": true, "pc": true,
                 "chance": true},
     "random_only": false}

a signal set to false is never read; random_only leaves chance alone;
enabled false is no mood at all (calm, no scenery, her plain lines). The
chat window's mascot menu and the launcher's "Mascot: …" commands write it
(save_settings); `mascot_mood.py --set weather=off random_only=on` too.
"""

import datetime as dt
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MOODS = ("calm", "happy", "excited", "shy", "curious", "focused", "worried", "sad", "sleepy")
SCENES = ("day", "night", "sun", "cloud", "rain", "storm", "snow", "fog", "hot", "cold",
          "music", "game", "party", "festive", "clock")
ACTIVE = ("thinking", "tool", "writing")

RUN = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
SETTINGS = os.path.join(STATE_DIR, "mascot.json")
SIGNALS = ("talk", "weather", "time", "calendar", "workhours", "pc", "chance")

WEATHER = os.path.join(RUN, "waybar-weather-raw.json")
GPU_HIST = os.path.join(RUN, "waybar-sensors", "gpu.hist")
CPU_HIST = os.path.join(RUN, "waybar-sensors", "cpu.hist")
PLAYER = os.path.join(RUN, "waybar-player", "state.json")

STALE_S = 3 * 3600      # weather older than this is not believed
SENSOR_STALE_S = 120    # the sensor history is only written in watch mode
PLAYER_STALE_S = 30
HOT_C, COLD_C = 30, 8   # outside, feels-like
GPU_HOT, CPU_HOT = 80, 85
EVENT_SOON_MIN = 15

REACT_S = 9             # a reaction's hold
PERMISSION_HOLD_S = 600  # "permission": curious while the model waits for a yes (cut short by the answer)
TALK_HALF_LIFE = 300.0  # the talk score halves in five minutes
CHANCE_S = (180, 420)   # chance picks a new mood this often

View = namedtuple("View", "mood scene line")

# What each topic says when the mascot has no voice of its own: str.format
# with the topic's arguments ({0}, {1}).
DEFAULT_LINES = {
    "thanks": "you're welcome!",
    "worried": "oh no...",
    "frustrated": "again?! one more try...",
    "relieved": "phew, it works now!",
    "determined": "this one's long -- hang in there!",
    "proud": "done, and nicely too!",
    "sad": "sorry...",
    "happy": "yay!",
    "curious": "hmm, good question...",
    "rain": "it's raining -- take an umbrella",
    "storm": "a storm... stay inside!",
    "snow": "snow!",
    "fog": "foggy out there",
    "sun": "sunny today!",
    "hot": "it's hot... {0}",
    "cold": "brr, {0} outside",
    "gpu_hot": "the GPU is at {0}°C...",
    "cpu_hot": "the CPU is at {0}°C...",
    "music": "nice song~",
    "game": "game time!",
    "event": "{0} in {1} min",
    "event_now": "{0} is starting now!",
    "birthday": "it's {0}'s birthday!",
    "holiday": "today is {0}!",
    "go_home": "it's {0} -- work's over, go home",
    "bedtime": "it's {0}... go to bed",
    "morning": "good morning!",
    "lunch": "lunch time?",
    "weekend": "it's the weekend~",
}
TOPICS = tuple(DEFAULT_LINES)


def word(table, topic):
    """A topic in a mascot's words: table[topic name].format(*arguments),
    DEFAULT_LINES when the table lacks it."""
    fmt = table.get(topic[0]) or DEFAULT_LINES.get(topic[0], topic[0])
    try:
        return fmt.format(*topic[1:])
    except (IndexError, KeyError, ValueError):
        return fmt


def default_line(topic):
    return word({}, topic)


# --- word matching ------------------------------------------------------------
# English and Spanish, lower case. A phrase is matched as words (\b at both
# ends unless it starts/ends with punctuation); NEGATIVE goes first and its
# matches are cut out, so "not working" never also counts as "working".

THANKS = ("thanks", "thank you", "thx", "ty", "gracias", "arigato", "arigatou",
          "good girl", "good job", "well done", "cute", "kawaii", "love you", "te quiero")
POSITIVE = ("great", "awesome", "perfect", "nice", "love", "cool", "works", "worked",
            "working", "excellent", "amazing", "brilliant", "beautiful", "yay", "lol",
            "haha", "fixed", "solved", "success", "succeeded", "passes", "passed",
            "all tests pass", "done", "glad", "happy", "wonderful", "genial", "perfecto",
            "excelente", "chido", "padre", "funciona", "bien", "listo", "bonito",
            ":)", ":d", "<3", "♡", "❤", "🎉", "😊", "😄", "👍", "✨", "^^")
NEGATIVE = ("not working", "doesn't work", "does not work", "didn't work", "won't work",
            "no funciona", "not work", "broken", "broke", "wrong", "error", "errors",
            "fail", "failed", "fails", "failing", "failure", "bug", "buggy", "crash",
            "crashed", "crashes", "stuck", "ugh", "wtf", "damn", "hate", "terrible",
            "awful", "annoying", "useless", "worse", "worst", "sorry", "apologize",
            "unfortunately", "unable", "can't", "cannot", "couldn't", "problem",
            "issue", "mal", "falla", "roto", "error", "otra vez", "todavía", "sigue",
            "still", "again", "frustrat", ":(", "😠", "😡", "😢", "😭", "💀")
QUESTION = ("how", "what", "why", "where", "which", "who", "when", "can you", "could you",
            "cómo", "como", "qué", "que", "por qué", "dónde", "cuál")


def _phrase_re(words):
    parts = []
    for w in sorted(words, key=len, reverse=True):
        p = re.escape(w)
        if w[0].isalnum():
            p = r"\b" + p
        if w[-1].isalnum():
            p = p + r"\b"
        parts.append(p)
    return re.compile("|".join(parts), re.I)


_NEG = _phrase_re(NEGATIVE)
_POS = _phrase_re(POSITIVE)
_THANKS = _phrase_re(THANKS)
_Q = _phrase_re(QUESTION)


def read_text(text):
    """(score, thanks, question) for some text: score is in [-1, 1] -- the
    balance of positive and negative words, damped so one word is not a
    verdict; thanks and question are booleans."""
    text = (text or "").lower()[:8000]
    neg = len(_NEG.findall(text))
    rest = _NEG.sub(" ", text)
    thanks = bool(_THANKS.search(rest))
    pos = len(_POS.findall(rest)) + (1 if thanks else 0)
    question = text.rstrip().endswith("?") or bool(_Q.match(text.strip()))
    score = (pos - neg) / (abs(pos - neg) + 2.0) if pos != neg else 0.0
    return max(-1.0, min(1.0, score)), thanks, question


# --- surroundings ---------------------------------------------------------------

def read_settings():
    """mascot.json with every key filled in: {"enabled", "random_only",
    "signals": {name: bool}} -- the switches as set, before random_only."""
    try:
        with open(SETTINGS) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    signals = {k: True for k in SIGNALS}
    if isinstance(data.get("signals"), dict):
        signals.update({k: bool(v) for k, v in data["signals"].items() if k in signals})
    return {"enabled": bool(data.get("enabled", True)),
            "random_only": bool(data.get("random_only", False)),
            "signals": signals}


def save_settings(enabled=None, random_only=None, **signals):
    """Change some switches (signals by name: weather=False) and write
    mascot.json whole; returns read_settings() after."""
    cur = read_settings()
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if random_only is not None:
        cur["random_only"] = bool(random_only)
    for k, v in signals.items():
        if k not in SIGNALS:
            raise ValueError(f"no signal {k!r} (one of {', '.join(SIGNALS)})")
        cur["signals"][k] = bool(v)
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cur, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, SETTINGS)
    return cur


def load_settings():
    """The signals in effect: random_only leaves chance alone, and with the
    moods off none is read at all."""
    cur = read_settings()
    if not cur["enabled"]:
        return {k: False for k in SIGNALS}
    if cur["random_only"]:
        return {k: k == "chance" for k in SIGNALS}
    return cur["signals"]


def _json(path, max_age=None):
    try:
        if max_age is not None and time.time() - os.path.getmtime(path) > max_age:
            return None
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


WEATHER_KINDS = {
    "sun": {113}, "cloud": {116, 119, 122}, "fog": {143, 149, 248, 260},
    "rain": {176, 179, 182, 185, 263, 266, 281, 284, 293, 296, 299, 302, 305, 308, 311,
             314, 317, 350, 353, 356, 359, 362, 365, 374, 377},
    "storm": {200, 386, 389, 392},
    "snow": {227, 230, 320, 323, 326, 329, 332, 335, 338, 368, 371, 395},
}


def _clock(text, on):
    try:
        return dt.datetime.combine(on, dt.datetime.strptime(text.strip(), "%I:%M %p").time())
    except (ValueError, AttributeError):
        return None


def weather(now):
    """{"kind", "night", "feels", "desc"} from wttr.py's raw cache, or None."""
    data = _json(WEATHER, STALE_S)
    try:
        cur = data["current_condition"][0]
        code = int(cur["weatherCode"])
    except (TypeError, KeyError, IndexError, ValueError):
        return None
    kind = next((k for k, codes in WEATHER_KINDS.items() if code in codes), "cloud")
    night = not (7 <= now.hour < 19)
    try:
        astro = data["weather"][0]["astronomy"][0]
        rise, down = _clock(astro["sunrise"], now.date()), _clock(astro["sunset"], now.date())
        if rise and down:
            night = not (rise <= now < down)
    except (KeyError, IndexError, TypeError):
        pass
    try:
        feels = int(cur.get("FeelsLikeC") or cur.get("temp_C"))
    except (TypeError, ValueError):
        feels = None
    desc = ((cur.get("weatherDesc") or [{}])[0].get("value") or "").strip()
    return {"kind": kind, "night": night, "feels": feels, "desc": desc}


def sensor_temp(path):
    """The last temperature in a sensor history ("epoch usage temp ..."), if
    it is fresh: the bar only writes it while its panel is watching."""
    try:
        if time.time() - os.path.getmtime(path) > SENSOR_STALE_S:
            return None
        with open(path) as fh:
            last = fh.read().strip().splitlines()[-1].split()
        return int(float(last[2]))
    except (OSError, IndexError, ValueError):
        return None


def music():
    state = _json(PLAYER, PLAYER_STALE_S)
    return isinstance(state, dict) and state.get("paused") is False


def gamemode():
    try:
        out = subprocess.run(["gamemoded", "-s"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "is active" in out


def work(now):
    """(working, end, holiday name, day off) from workhours.py."""
    try:
        import workhours
    except Exception:
        return False, None, None, False
    working, reason, end = workhours.state(now)
    return working, end, workhours.holiday(now.date()), reason.startswith(("weekend", "day off", "holiday"))


def _ical_when(t):
    """An ICalGLib.Time to (datetime in local time, all-day)."""
    if t is None or t.is_null_time():
        return None, False
    if t.is_date():
        return dt.datetime(t.get_year(), t.get_month(), t.get_day()), True
    naive = dt.datetime(t.get_year(), t.get_month(), t.get_day(),
                        t.get_hour(), t.get_minute(), t.get_second())
    if t.is_utc():
        return naive.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None), False
    tzid = t.get_tzid()
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return naive.replace(tzinfo=ZoneInfo(tzid.split("/", 3)[-1] if tzid.startswith("/") else tzid)) \
                .astimezone().replace(tzinfo=None), False
        except Exception:
            pass
    return naive, False


def _occurrences(comp, start, end):
    """The datetimes in [start, end) at which an ICalGLib.Component begins:
    its DTSTART, or each recurrence of its RRULE (yearly birthdays, weekly
    stand-ups); at most a few hundred steps per rule."""
    from gi.repository import ICalGLib
    # The RRULEs first: any other get_* on the component (get_dtstart too)
    # moves libical's one property cursor, and get_next_property would
    # start over -- forever.
    rules = []
    prop = comp.get_first_property(ICalGLib.PropertyKind.RRULE_PROPERTY)
    while prop is not None and len(rules) < 8:
        rules.append(prop.get_rrule())
        prop = comp.get_next_property(ICalGLib.PropertyKind.RRULE_PROPERTY)
    dtstart = comp.get_dtstart()
    first, all_day = _ical_when(dtstart)
    if first is None:
        return [], all_day
    if not rules:
        return ([first] if start <= first < end or (all_day and first.date() == start.date()) else []), all_day
    out = []
    for rule in rules:
        it = ICalGLib.RecurIterator.new(rule, dtstart)
        # Jump to a day before the window (time zones aside): a daily event
        # from years ago would otherwise run out of steps first. libical
        # refuses this for a rule with COUNT; those start from the top.
        try:
            it.set_start(ICalGLib.Time.new_from_string((start - dt.timedelta(days=1)).strftime(
                "%Y%m%d" if all_day else "%Y%m%dT%H%M%S")))
        except Exception:
            pass
        for _ in range(600):
            t = it.next()
            if t is None or t.is_null_time():
                break
            when, _ = _ical_when(t)
            if when >= end:
                break
            if start <= when or (all_day and when.date() == start.date()):
                out.append(when)
    return out, all_day


def calendar(now, sources=None):
    """Events from Evolution's enabled calendars: (minutes until the next
    timed event within EVENT_SOON_MIN, its summary) or None, and the names
    of today's birthdays. `sources` (tests): a list of iCalendar VEVENT
    strings, read instead of EDS."""
    start = now.replace(second=0, microsecond=0)
    end = start + dt.timedelta(minutes=EVENT_SOON_MIN + 1)
    day = dt.datetime.combine(now.date(), dt.time())
    soon, birthdays = None, []
    try:
        import gi
        gi.require_version("ICalGLib", "3.0")
        from gi.repository import ICalGLib
        comps = []
        if sources is not None:
            comps = [("test", ICalGLib.Component.new_from_string(s)) for s in sources]
        else:
            gi.require_version("ECal", "2.0")
            gi.require_version("EDataServer", "1.2")
            from gi.repository import ECal, EDataServer
            reg = EDataServer.SourceRegistry.new_sync(None)
            for src in reg.list_sources(EDataServer.SOURCE_EXTENSION_CALENDAR):
                if not src.get_enabled():
                    continue
                client = ECal.Client.connect_sync(src, ECal.ClientSourceType.EVENTS, 1, None)
                ok, objs = client.get_object_list_as_comps_sync("#t", None)
                for obj in objs or []:
                    comps.append((src.get_uid(), obj.get_icalcomponent()))
    except Exception as exc:
        print(f"mascot_mood: calendar unavailable ({exc})", file=sys.stderr)
        return None, []
    for uid, comp in comps:
        if comp is None:
            continue
        if comp.isa() == ICalGLib.ComponentKind.VCALENDAR_COMPONENT:
            inner = comp.get_first_component(ICalGLib.ComponentKind.VEVENT_COMPONENT)
            comp = inner or comp
        summary = (comp.get_summary() or "").strip() or "an event"
        try:
            when, all_day = _occurrences(comp, day, day + dt.timedelta(days=1))
        except Exception:
            continue
        cats = ""
        prop = comp.get_first_property(ICalGLib.PropertyKind.CATEGORIES_PROPERTY)
        if prop is not None:
            cats = (prop.get_categories() or "").lower()
        if all_day:
            if when and (uid == "birthdays" or "birthday" in cats or "birthday" in summary.lower()
                         or "cumpleaños" in summary.lower()):
                name = re.sub(r"(?i)^(birthday|cumpleaños)\s*(of|de)?\s*:?\s*|\s*'s birthday$", "", summary)
                birthdays.append(name.strip() or summary)
            continue
        for w in when:
            if start <= w < end:
                mins = int((w - now).total_seconds() // 60)
                if soon is None or mins < soon[0]:
                    soon = (max(0, mins), summary)
    return soon, birthdays


def surroundings(now=None, signals=None, cal_sources=None):
    """Everything outside the conversation, as a plain dict (see main())."""
    now = now or dt.datetime.now()
    signals = signals or load_settings()
    s = {"now": now, "hour": now.hour + now.minute / 60.0}
    if signals.get("weather"):
        s["weather"] = weather(now)
    if signals.get("pc"):
        s["gpu"] = sensor_temp(GPU_HIST)
        s["cpu"] = sensor_temp(CPU_HIST)
        s["music"] = music()
        s["game"] = gamemode()
    if signals.get("workhours") or signals.get("calendar"):
        s["working"], s["work_end"], s["holiday"], s["off"] = work(now)
    if signals.get("calendar"):
        s["event"], s["birthdays"] = calendar(now, cal_sources)
    return s


def scene_of(s, signals):
    """The SCENES tags for a surroundings dict."""
    out = set()
    w = s.get("weather")
    night = w["night"] if w else not (7 <= s["hour"] < 19)
    if signals.get("weather") or signals.get("time"):
        out.add("night" if night else "day")
    if w:
        if not (w["kind"] == "sun" and night):     # a clear night is just night
            out.add(w["kind"])
        if w["feels"] is not None and w["feels"] >= HOT_C:
            out.add("hot")
        if w["feels"] is not None and w["feels"] <= COLD_C:
            out.add("cold")
    if (s.get("gpu") or 0) >= GPU_HOT or (s.get("cpu") or 0) >= CPU_HOT:
        out.add("hot")
    if s.get("music"):
        out.add("music")
    if s.get("game"):
        out.add("game")
    if signals.get("calendar"):
        if s.get("birthdays"):
            out.add("party")
        if s.get("holiday"):
            out.add("festive")
        if s.get("event"):
            out.add("clock")
    return frozenset(out & set(SCENES))


# --- the engine ------------------------------------------------------------------

class Mood:
    """See the module docstring. Thread use: refresh() may run on a worker
    thread; it only swaps self._env (one assignment) when done."""

    def __init__(self, signals=None, clock=time.time, rng=None):
        self.signals = signals or load_settings()
        self.enabled = read_settings()["enabled"] if signals is None else True
        self.clock = clock
        self.rng = rng or random.Random()
        self._env = {"now": dt.datetime.now(), "hour": dt.datetime.now().hour}
        self._scene = frozenset()
        self._lock = threading.Lock()
        self.reaction = None        # (mood, until, topic)
        self.talk = 0.0             # [-1, 1]
        self.talk_at = 0.0
        self.errors_in_row = 0
        self.errors_this_run = 0
        self.run_started = None
        self.long_said = False
        self.chance = ("calm", 0.0)
        self.idle_topic = (None, 0.0)
        self.announced = set()      # events / days already given a heads-up
        self.refreshed = 0.0

    # -- inputs ------------------------------------------------------------

    def refresh(self, cal_sources=None):
        """Re-read the surroundings. Blocking (EDS, gamemoded): call it off
        the main loop. Returns True when the scene changed."""
        self.signals = load_settings()
        self.enabled = read_settings()["enabled"]
        env = surroundings(signals=self.signals, cal_sources=cal_sources)
        scene = scene_of(env, self.signals)
        with self._lock:
            changed = scene != self._scene
            self._env, self._scene = env, scene
            self.refreshed = self.clock()
        return changed

    def react(self, event, text=None, duration=None):
        """A conversation event: "prompt" (text: what you sent), "reply"
        (text: a finished reply), "tool_error", "tool_ok", "result_ok",
        "result_error" (duration: the run's seconds), "stopped", "tick"
        (a run is going: checks for the long-run reaction), "permission"
        (the model waits for a yes: curious until it is answered),
        "permission_allowed", "permission_denied"."""
        now = self.clock()
        talk_on = self.signals.get("talk", True)
        if event == "prompt":
            self.run_started, self.errors_this_run, self.long_said = now, 0, False
            if not talk_on:
                return
            score, thanks, question = read_text(text)
            self._nudge(score * 2.0)
            if thanks:
                self._react("shy", "thanks", now)
            elif score <= -0.3:
                self._react("worried", "worried", now)
            elif question:
                self._react("curious", None, now, hold=REACT_S / 2)
        elif event == "reply":
            if talk_on:
                score, _, _ = read_text(text)
                self._nudge(score)
        elif event == "tool_error":
            self.errors_in_row += 1
            self.errors_this_run += 1
            if talk_on:
                if self.errors_in_row >= 2:
                    self._react("worried", "frustrated", now)
                else:
                    self._react("worried", None, now, hold=REACT_S / 2)
                self._nudge(-0.15)
        elif event == "tool_ok":
            self.errors_in_row = 0
        elif event == "result_ok":
            if talk_on:
                if self.errors_this_run:
                    self._react("happy", "relieved", now)
                elif duration and duration > 60:
                    self._react("excited", "proud", now)
                else:
                    self._react("happy", None, now, hold=REACT_S / 2)
                self._nudge(0.2)
            self.run_started = None
        elif event == "result_error":
            if talk_on:
                self._react("sad", "sad", now)
                self._nudge(-0.4)
            self.run_started = None
        elif event == "stopped":
            self.run_started = None
        elif event == "permission":
            # Quiet (no line: the window's bubble asks), held until answered.
            self._react("curious", None, now, hold=PERMISSION_HOLD_S)
        elif event == "permission_allowed":
            self.reaction = None
            self._react("happy", None, now, hold=REACT_S / 2)
        elif event == "permission_denied":
            self.reaction = None
            self._react("calm", None, now, hold=REACT_S / 2)
        elif event == "tick":
            if talk_on and self.run_started and not self.long_said and now - self.run_started > 60:
                self.long_said = True
                self._react("focused", "determined", now)

    def _react(self, mood, topic, now, hold=REACT_S):
        # A quiet reaction (no line) does not cut a speaking one short: a
        # quick "done" right after "thanks" leaves her blushing, still
        # saying "you're welcome".
        if topic is None and self.reaction and self.reaction[2] and now < self.reaction[1]:
            return
        self.reaction = (mood, now + hold, (topic,) if topic else None)

    def _nudge(self, delta):
        self.talk = max(-1.0, min(1.0, self._talk_now() + delta * 0.5))
        self.talk_at = self.clock()

    def _talk_now(self):
        if not self.talk:
            return 0.0
        age = self.clock() - self.talk_at
        return self.talk * 0.5 ** (age / TALK_HALF_LIFE)

    # -- output --------------------------------------------------------------

    def view(self, state="idle"):
        if not self.enabled:
            return View("calm", frozenset(), None)
        now = self.clock()
        with self._lock:
            env, scene = self._env, self._scene
        mood, line = self._mood(state, env, now)
        if state in ACTIVE and mood == "sleepy":
            mood = "focused"
        return View(mood, scene, line)

    def _mood(self, state, env, now):
        sig = self.signals
        # 1. a reaction
        if self.reaction and now < self.reaction[1]:
            return self.reaction[0], self.reaction[2]
        self.reaction = None
        line = self._idle_line(env, now) if state == "idle" else None
        # A heads-up for an event, once: as a reaction, in any state.
        ev = env.get("event") if sig.get("calendar") else None
        if ev and ("event",) + ev[1:] not in self.announced:
            self.announced.add(("event",) + ev[1:])
            topic = ("event_now", ev[1]) if ev[0] <= 1 else ("event", ev[1], ev[0])
            self.reaction = ("worried" if ev[0] <= 5 else "curious", now + REACT_S * 2, topic)
            return self.reaction[0], topic
        # 2. the talk
        talk = self._talk_now() if sig.get("talk") else 0.0
        if talk >= 0.3:
            return ("excited" if talk >= 0.7 else "happy"), line
        if talk <= -0.5:
            return "sad", line
        if talk <= -0.2:
            return "worried", line
        # 3. surroundings
        amb = self._ambient_mood(env)
        if amb:
            return amb, line
        # 4. chance
        if sig.get("chance", True):
            return self._chance(env, now), line
        return "calm", line

    def _ambient_mood(self, env):
        sig = self.signals
        h = env.get("hour", 12)
        if sig.get("calendar") and (env.get("birthdays") or env.get("holiday")):
            return "excited"
        w = env.get("weather")
        if w and w["kind"] == "storm":
            return "worried"
        if sig.get("time") and (h >= 23.5 or h < 5.5):
            return "sleepy"
        if sig.get("workhours") and env.get("working"):
            return "focused"
        if sig.get("time") and 6 <= h < 9:
            return "happy"
        return None

    def _chance(self, env, now):
        mood, until = self.chance
        if now < until:
            return mood
        h = env.get("hour", 12)
        table = [("calm", 6), ("happy", 3), ("curious", 2), ("shy", 1), ("excited", 1),
                 ("sleepy", 3 if (h >= 22 or h < 7 or 14 <= h < 15.5) else 1)]
        total = sum(w for _, w in table)
        pick = self.rng.uniform(0, total)
        for name, wt in table:
            pick -= wt
            if pick <= 0:
                mood = name
                break
        self.chance = (mood, now + self.rng.uniform(*CHANCE_S))
        return mood

    def _idle_line(self, env, now):
        """What she says while idle: one topic, held for half a minute, then
        the next that applies -- or None (the mascot's own idle line) every
        other turn, so it does not nag."""
        topic, until = self.idle_topic
        if now < until:
            return topic
        options = self.topics(env)
        turn = int(now // 30)
        topic = options[(turn // 2) % len(options)] if options and turn % 2 == 0 else None
        self.idle_topic = (topic, now + 30)
        return topic

    def topics(self, env=None):
        """Every topic that applies right now, most pressing first."""
        env = env or self._env
        sig = self.signals
        now = env.get("now") or dt.datetime.now()
        h = env.get("hour", now.hour)
        out = []
        if sig.get("calendar"):
            ev = env.get("event")
            if ev:
                out.append(("event_now", ev[1]) if ev[0] <= 1 else ("event", ev[1], ev[0]))
            for name in env.get("birthdays") or []:
                out.append(("birthday", name))
            if env.get("holiday"):
                out.append(("holiday", env["holiday"]))
        if sig.get("workhours") and not env.get("working") and not env.get("off") \
                and now.weekday() < 5 and 18 <= h < 18.75:
            out.append(("go_home", now.strftime("%H:%M")))
        if sig.get("time"):
            if h >= 0.5 and h < 5:
                out.append(("bedtime", now.strftime("%H:%M")))
            elif 6 <= h < 9.5:
                out.append(("morning",))
            elif 13.5 <= h < 14.5 and now.weekday() < 5:
                out.append(("lunch",))
            if now.weekday() >= 5 and 9 <= h < 21:
                out.append(("weekend",))
        if sig.get("pc"):
            if (env.get("gpu") or 0) >= GPU_HOT:
                out.append(("gpu_hot", env["gpu"]))
            elif (env.get("cpu") or 0) >= CPU_HOT:
                out.append(("cpu_hot", env["cpu"]))
            if env.get("game"):
                out.append(("game",))
            elif env.get("music"):
                out.append(("music",))
        w = env.get("weather") if sig.get("weather") else None
        if w:
            if w["kind"] in ("rain", "storm", "snow", "fog"):
                out.append((w["kind"],))
            elif w["kind"] == "sun" and not w["night"]:
                out.append(("sun",))
            if w["feels"] is not None and w["feels"] >= HOT_C:
                out.append(("hot", f"{w['feels']}°C"))
            elif w["feels"] is not None and w["feels"] <= COLD_C:
                out.append(("cold", f"{w['feels']}°C"))
        return out


# --- CLI -------------------------------------------------------------------------

def main(argv):
    if argv[:1] == ["--text"]:
        text = " ".join(argv[1:])
        score, thanks, question = read_text(text)
        print(f"score {score:+.2f}  thanks {thanks}  question {question}")
        return 0
    if argv[:1] == ["--set"]:
        changes = {}
        for arg in argv[1:]:
            key, _, val = arg.partition("=")
            if val not in ("on", "off", "true", "false", "1", "0"):
                print(f"mascot_mood: {arg}: want KEY=on or KEY=off", file=sys.stderr)
                return 2
            changes[key] = val in ("on", "true", "1")
        try:
            cur = save_settings(**changes)
        except (TypeError, ValueError, OSError) as exc:
            print(f"mascot_mood: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(cur))
        return 0
    m = Mood()
    m.refresh()
    env = dict(m._env)
    env["now"] = env["now"].strftime("%Y-%m-%d %H:%M")
    if env.get("work_end"):
        env["work_end"] = env["work_end"].strftime("%H:%M")
    print("signals:", ", ".join(k for k, v in m.signals.items() if v) or "none")
    print("surroundings:", json.dumps(env, ensure_ascii=False, default=str))
    print("scene:", " ".join(sorted(m._scene)) or "-")
    v = m.view("idle")
    print("mood (idle):", v.mood, " (working):", m.view("tool").mood)
    print("topics:", "; ".join(default_line(t) for t in m.topics()) or "-")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
