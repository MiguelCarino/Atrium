#!/usr/bin/env python3
"""Desktop memory: what went past on this computer, kept with the time it
happened, so you can ask "when did I last look at that dcmjs bug?", "what
link did someone send on Tuesday?", "what was that error in the terminal
yesterday?" -- "¿qué enlace me mandaron el martes?". Everything stays here.

    desktop-memory.py collect          what desktop-memory.timer runs every 5
                                       minutes: take in what is new from each
                                       source that is on, a screenshot when one
                                       is due, prune what is past its days
                                       (no embeddings: those wait for the
                                       hourly desktop-index.py update, which
                                       calls embed_hourly(), so LM Studio is
                                       not woken every 5 minutes)
    desktop-memory.py snap [--force]   one screenshot + OCR now (--force: even
                                       when the last one is recent; never when
                                       the screen source is off)
    desktop-memory.py embed            the embeddings of what has none, now
    desktop-memory.py search WORDS [--from ISO] [--to ISO] [--source S] [-k N] [--json]
                                       the best-matching memories; the time
                                       words in WORDS count too ("ayer", "last
                                       Tuesday at 3pm")
    desktop-memory.py recall [--notify] [--json] QUESTION
                                       the answer, written by the local model
                                       from the memories found (the launcher's
                                       "remember ..." / "recuerda ..." runs it
                                       with --notify: Open buttons for the
                                       links and screenshots it points to)
    desktop-memory.py when TEXT        the time range the words mean, and what
                                       is left to search for (to check the
                                       date words)
    desktop-memory.py status [--json]  per source: on / off, how many, since
                                       when, size; never what is in them
    desktop-memory.py apps [--json]    the apps with the most memories (Settings'
                                       "forget an app" picker)
    desktop-memory.py forget day DATE|today|yesterday
    desktop-memory.py forget app CLASS     its memories, and none from now on
                                           (privacy.conf memory_exclude)
    desktop-memory.py forget source SOURCE
    desktop-memory.py forget entry ID
    desktop-memory.py wipe             everything: the store, the screenshots'
                                       thumbnails, the captions log
    desktop-memory.py prune            drop what is older than the kept days now

THE SOURCES (privacy.conf memory_<source>, privacy_settings.py; Settings >
Privacy and Settings > Desktop memory switch them):

    activity        on   the window titles over time: activity-log.py's log,
                         one memory per stretch with a window focused (title
                         spinners and flicker merged; under MIN_ACTIVITY_S left
                         out). Its private windows are already "private" there
                         and are skipped. The whole log is taken in at the
                         first run (its times are exact).
    clipboard       on   new text copies in cliphist's history. cliphist keeps
                         no times, so a copy is stamped when a collect first
                         sees it ("copied between 14:05 and 14:10"); what was
                         copied before memory started is not taken in (the
                         clipboard is still searched live by ask-desktop.py).
    notifications   on   mako keeps its history in memory only and stamps no
                         time: each collect takes in the new ones (their ids
                         only grow), stamped like the copies. Low-urgency
                         toasts (volume, "screenshot saved") and Ask / memory's
                         own are left out.
    captions        OFF  the live captions' finished lines (voice.py writes them
                         to captions.jsonl only while this is on), as
                         paragraphs.
    screen          OFF  a screenshot of each screen every memory_screen_minutes
                         (15 as shipped): tesseract reads its text (screen-
                         actions.py's ocr(), Settings > Capture's languages),
                         and only that text and a small JPEG thumbnail are
                         kept -- the screenshot itself is in $XDG_RUNTIME_DIR
                         for the seconds the OCR takes. Not taken while the
                         screen is locked or its outputs are off, in game mode
                         or with a Steam game open, on battery, or for a screen
                         showing a private window (a password manager, a
                         private-browsing window, an app on Privacy's private
                         list -- smart-clipboard.py's private_focus) or nothing
                         at all. The same text as last time: not kept again.
                         Its own retention (memory_screen_keep_days, 7).

NEVER KEPT, whatever is on: anything looks_secret() flags -- smart-
clipboard.py's rules (card numbers, IBANs, CLABEs, private keys, API tokens,
"password: ..." lines, password-like words) -- and one-time codes ("your code
is 482913"). A copy or notification that trips it is dropped whole; for OCR
and captions the lines that trip it are dropped (a private key anywhere drops
the whole screenshot). Apps in memory_exclude (forget app) and activity's
private apps are skipped by every source.

TIME: every memory has a time (t, and t_end for a stretch). time_words()
reads the time words of a question, in English and Spanish: today / hoy,
yesterday / ayer, anteayer, last night / anoche, weekdays ("Tuesday", "el
martes pasado": the latest one before today), "last week" / "la semana
pasada", "this month", "3 days ago" / "hace 3 días", "the last 2 hours" /
"las últimas 2 horas", dates ("Oct 20", "20 de octubre", "2026-10-20",
"20/10": day first), and a time of day inside a day ("at 3pm", "a las 15:30",
"this morning", "en la tarde").

SEARCH: the time range first, then meaning + keywords inside it, mixed by
reciprocal rank fusion like desktop-index.py (whose embedding calls this
reuses: the same small local embedding model, never a chat model loaded for
it; no model -> keywords only). A question with no words left after its time
words ("what did I do yesterday?") gets that time's memories in order.
Activity hits for the same window are folded into one ("seen 5 times, last
Tue 14:32, 40 min in all").

ANSWERS (recall): the local model -- the "quick" setting, else "default"
(Settings > AI & models) -- through llm-worker.py's ready() / ask(): never a
cloud model, never in game mode or when it would not fit on the GPU. When it
cannot run, the answer is the list of what was found, still with its links.

STORE: $XDG_STATE_HOME/desktop-memory/ (mode 700): memory.sqlite3, thumbs/
<day>/, captions.jsonl. Forgotten days and the wipe leave a mark, so the
activity log or a captions line from before is not taken in again.
desktop-memory.service runs `collect` at nice 19 / idle I/O; the timer is
desktop-memory.timer. With the memory switch off nothing is collected (what
is kept stays until it is forgotten or ages out; the prune still runs), and
a source that is off takes in nothing of its time off when it is turned on
again (hold(): its cursor moves on while it is off).
"""
import array
import datetime
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
sys.path.insert(0, HERE)
import privacy_settings  # noqa: E402  (privacy.conf: the memory switches)
import desk_common  # noqa: E402  (hypr_request: hyprctl over the socket)

HOME = os.path.expanduser("~")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
DIR = os.path.join(STATE_HOME, "desktop-memory")
DB = os.path.join(DIR, "memory.sqlite3")
THUMBS = os.path.join(DIR, "thumbs")
CAPTIONS = os.path.join(DIR, "captions.jsonl")      # voice.py appends here (CAPTIONS_LOG)
ACTIVITY = os.path.join(STATE_HOME, "hypr", "activity.jsonl")

SOURCES = privacy_settings.MEMORY_SOURCES
SOURCE_NAMES = {"activity": "window", "clipboard": "copied", "notifications": "notification",
                "captions": "heard", "screen": "on screen"}
MIN_ACTIVITY_S = 20         # a window focused for less is not a memory
MERGE_GAP_S = 120           # the same window again within this: the same stretch
MAX_TEXT = 4000             # characters kept per memory
CLIP_PER_RUN = 60           # copies decoded per collect at most
NOTE_SKIP_APPS = {"ask your desktop", "desktop memory", "digest", "automations", "osd"}
CAPTION_GAP_S = 90          # caption lines further apart start a new paragraph
CAPTION_PARA = 1500
THUMB_W = 360               # px, the thumbnail's width
THUMB_Q = 55
EMBED_EVERY_S = 1800        # the embeddings at most this often (desktop-index's hourly run)
EMBED_RUSH = 300            # ... or sooner when this many wait
EMBED_START_S = 6 * 3600    # LM Studio started for them only when the last pass is this old (or a rush)
EMBED_BATCH = 32
K_DEFAULT = 12
RRF = 60
OTP = re.compile(r"(code|c[oó]digo|otp|verification|verificaci[oó]n|passcode|pin|2fa|one[- ]time|"
                 r"clave)\D{0,40}\b\d{4,8}\b|\b\d{4,8}\b\D{0,30}(is your|es tu|es su)", re.I)
URL = re.compile(r"https?://[^\s<>\"'`)\]]+")
MODEL_ROLES = ("quick", "default")
SYSTEM = ("You answer questions about what the user saw, copied, heard or did on their own computer, "
          "using ONLY the numbered memories given (each has its time). Answer briefly, in the language "
          "of the question. Say when it happened (day and time) and give the link or file exactly as "
          "written in the memory. Cite the memories you used like [2]. If none of them answers the "
          "question, say so plainly instead of guessing.")
OFF_TEXT = "Desktop memory is turned off (Settings > Privacy)."
APP = "Desktop memory"
NOTIFY_TAG = ["-a", APP, "-h", "string:x-canonical-private-synchronous:desktop-memory"]


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def index():
    return _module("desktop_index", "desktop-index.py")


def smartclip():
    return _module("smart_clipboard", "smart-clipboard.py")


# -- privacy ---------------------------------------------------------------------
def sources_on(conf=None):
    """The sources collected (and searched) now: empty with memory off."""
    conf = privacy_settings.load() if conf is None else conf
    return privacy_settings.memory_sources(conf)


def excluded_apps(conf):
    return set(privacy_settings.memory_excluded(conf))


def looks_secret(text):
    """smart-clipboard.py's rules, plus one-time codes. Unsure (the module
    did not load): secret."""
    if OTP.search(text or ""):
        return True
    try:
        return bool(smartclip().looks_secret(text))
    except Exception:       # noqa: BLE001
        return True


def scrub(text):
    """OCR / caption text without the lines that look secret; None when a
    private key or token is in it at all (the whole thing is dropped)."""
    try:
        if smartclip().TOKEN.search(text or ""):
            return None
    except Exception:       # noqa: BLE001
        return None
    keep = [line for line in (text or "").splitlines() if line.strip() and not looks_secret(line)]
    return "\n".join(keep)


def private_window(window, conf):
    """A password manager, a private-browsing window, an app on Privacy's
    private list or one forgotten here."""
    if (window.get("class") or "").lower() in excluded_apps(conf):
        return True
    try:
        return bool(smartclip().private_focus(window, conf))
    except Exception:       # noqa: BLE001
        return True


# -- words and times -----------------------------------------------------------------
def fold(text):
    """Lower case without accents: "Miércoles" -> "miercoles"."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


QSTOP = set(("what when where which who whom how did do does was were is are the a an of to in on at for "
             "from about and or my me i you someone somebody anyone last look looked looking see saw seen "
             "that this there those these thing something send sent link links copy copied open opened "
             "remember recall find show tell any again time ever just "
             "que cual cuando donde quien como el la los las un una unos unas de del en a al por para y o "
             "mi me yo alguien algo eso esa ese este esta aquel vi vimos ver mando mandaron envio enviaron "
             "copie copiado abri recuerda recuerdas recordar encuentra muestra dime ese vez "
             "morning afternoon evening manana tarde noche doing working work done haciendo hacia hice "
             "trabajando trabajaba estaba estuve hizo pasa paso happened happen").split())


def tokens(text):
    """desktop-index.py's words, folded (so "código" finds "codigo")."""
    return index().tokens(fold(text))


def query_terms(text):
    return [t for t in dict.fromkeys(tokens(text)) if t not in QSTOP]


WEEKDAYS = {"monday": 0, "lunes": 0, "tuesday": 1, "martes": 1, "wednesday": 2, "miercoles": 2,
            "thursday": 3, "jueves": 3, "friday": 4, "viernes": 4, "saturday": 5, "sabado": 5,
            "sunday": 6, "domingo": 6}
MONTHS = {"january": 1, "jan": 1, "enero": 1, "ene": 1, "february": 2, "feb": 2, "febrero": 2,
          "march": 3, "mar": 3, "marzo": 3, "april": 4, "apr": 4, "abril": 4, "abr": 4, "may": 5,
          "mayo": 5, "june": 6, "jun": 6, "junio": 6, "july": 7, "jul": 7, "julio": 7, "august": 8,
          "aug": 8, "agosto": 8, "ago": 8, "september": 9, "sep": 9, "sept": 9, "septiembre": 9,
          "setiembre": 9, "october": 10, "oct": 10, "octubre": 10, "november": 11, "nov": 11,
          "noviembre": 11, "december": 12, "dec": 12, "diciembre": 12, "dic": 12}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "un": 1, "una": 1, "uno": 1, "two": 2, "dos": 2, "three": 3,
                "tres": 3, "four": 4, "cuatro": 4, "five": 5, "cinco": 5, "six": 6, "seis": 6, "seven": 7,
                "siete": 7, "eight": 8, "ocho": 8, "nine": 9, "nueve": 9, "ten": 10, "diez": 10,
                "couple": 2, "few": 3, "par": 2, "unos": 3, "unas": 3}
UNITS = {"minute": 60, "minutes": 60, "min": 60, "mins": 60, "minuto": 60, "minutos": 60,
         "hour": 3600, "hours": 3600, "hora": 3600, "horas": 3600,
         "day": 86400, "days": 86400, "dia": 86400, "dias": 86400,
         "week": 7 * 86400, "weeks": 7 * 86400, "semana": 7 * 86400, "semanas": 7 * 86400,
         "month": 30 * 86400, "months": 30 * 86400, "mes": 30 * 86400, "meses": 30 * 86400}
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MO = "|".join(sorted(MONTHS, key=len, reverse=True))
_NUM = r"(\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"
_UNIT = "(" + "|".join(sorted(UNITS, key=len, reverse=True)) + ")"
# The parts of the day: (start hour, end hour; past 24 runs into the next day).
PARTS = {"morning": (5, 12), "manana": (5, 12), "afternoon": (12, 19), "tarde": (12, 19),
         "evening": (18, 24), "noche": (19, 28), "night": (19, 28)}


def _num(word):
    if not word:
        return 1
    return int(word) if word.isdigit() else NUMBER_WORDS.get(word, 1)


def _day(d):
    return datetime.datetime.combine(d, datetime.time())


def _date_or_none(y, m, d):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def _past_date(m, d, now, year=None):
    """A day-and-month with no year: this year's, or last year's when that
    is still to come."""
    if year:
        return _date_or_none(year, m, d)
    got = _date_or_none(now.year, m, d)
    if got and got > now.date():
        got = _date_or_none(now.year - 1, m, d)
    return got


def _day_rules(now):
    """(regex, fn(match) -> (start, end) or None), tried in order on the
    folded text; the first that matches sets the days."""
    today = _day(now.date())
    one = datetime.timedelta(days=1)

    def date_span(d):
        return (_day(d), _day(d) + one) if d else None

    def weekday(m):
        want = WEEKDAYS[m["wd"]]
        if m["this"] and want == now.weekday():
            return today, now
        back = (now.weekday() - want) % 7 or 7
        return today - back * one, today - (back - 1) * one

    def ago(m):
        n, unit = _num(m["n"]), UNITS[m["unit"]]
        mid = now - datetime.timedelta(seconds=n * unit)
        if unit >= 86400:
            if unit == 86400:
                return _day(mid.date()), _day(mid.date()) + one
            half = datetime.timedelta(seconds=unit / 2)
            return mid - half, min(mid + half, now)
        half = datetime.timedelta(seconds=max(unit * n / 4, 300 if unit == 60 else 1800))
        return mid - half, min(mid + half, now)

    def last_n(m):
        return now - datetime.timedelta(seconds=_num(m["n"]) * UNITS[m["unit"]]), now

    monday = today - now.weekday() * one
    first = today.replace(day=1)
    prev_first = (first - one).replace(day=1)
    return [
        (r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b",
         lambda m: date_span(_date_or_none(int(m["y"]), int(m["m"]), int(m["d"])))),
        (r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{2,4}))?\b",
         lambda m: date_span(_past_date(int(m["m"]), int(m["d"]), now,
                                        (int(m["y"]) + (2000 if len(m["y"]) == 2 else 0)) if m["y"] else None))),
        (rf"\b(?:(?:on|el)\s+)?(?P<d>\d{{1,2}})(?:st|nd|rd|th|o)?\s+(?:de\s+|of\s+)?(?P<mo>{_MO})\b\.?"
         rf"(?:,?\s+(?:de\s+)?(?P<y>\d{{4}}))?",
         lambda m: date_span(_past_date(MONTHS[m["mo"]], int(m["d"]), now, int(m["y"]) if m["y"] else None))),
        (rf"\b(?:on\s+)?(?P<mo>{_MO})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*(?:{_UNIT[1:-1]}|:))"
         rf"(?:,?\s+(?P<y>\d{{4}}))?",
         lambda m: date_span(_past_date(MONTHS[m["mo"]], int(m["d"]), now, int(m["y"]) if m["y"] else None))),
        (r"\b(?:the\s+)?day\s+before\s+yesterday\b|\bantea?yer\b|\bantier\b",
         lambda m: (today - 2 * one, today - one)),
        (r"\blast\s+night\b|\banoche\b",
         lambda m: (today - one + datetime.timedelta(hours=18), today + datetime.timedelta(hours=4))),
        (r"\byesterday\b|\bayer\b", lambda m: (today - one, today)),
        (r"\b(?:today|hoy)\b", lambda m: (today, now)),
        (rf"\b(?:(?P<this>this|este)\s+|(?:on|last|el|the)\s+)?(?:past\s+)?(?P<wd>{_WD})s?\b(?:\s+pasado)?",
         weekday),
        ("@ago", None),         # the alternative spellings: _alt_patterns()
        ("@last", None),
        (r"\blast\s+week\b|\b(?:la\s+)?semana\s+pasada\b", lambda m: (monday - 7 * one, monday)),
        (r"\bthis\s+week\b|\besta\s+semana\b", lambda m: (monday, now)),
        (r"\blast\s+month\b|\b(?:el\s+)?mes\s+pasado\b", lambda m: (prev_first, first)),
        (r"\bthis\s+month\b|\beste\s+mes\b", lambda m: (first, now)),
        (r"\blast\s+year\b|\b(?:el\s+)?ano\s+pasado\b",
         lambda m: (today.replace(year=now.year - 1, month=1, day=1), today.replace(month=1, day=1))),
    ], ago, last_n


# Python's re refuses a group name used twice, so the two spellings of
# "N units ago" / "the last N units" are separate patterns sharing a handler.
def _alt_patterns():
    n = _NUM.replace("(", "(?P<n>", 1)
    u = _UNIT.replace("(", "(?P<unit>", 1)
    return {"ago": [rf"\b{n}\s+{u}\s+ago\b", rf"\bhace\s+(?:unos\s+|unas\s+)?(?:{n}\s+)?{u}\b"],
            "last": [rf"\b(?:in\s+)?(?:the\s+)?(?:last|past)\s+{n}\s+{u}\b",
                     rf"\b(?:en\s+)?(?:los|las)\s+ultim[oa]s\s+{n}\s+{u}\b"]}


CLOCK_RULE = re.compile(r"\b(?:at|around|a\s+las?|como\s+a\s+las?|sobre\s+las?|cerca\s+de\s+las?|"
                        r"hacia\s+las?)\s+(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>am|pm|a\.m\.|p\.m\.)?"
                        r"(?=\s*(?:$|[^\w\s]|(?:o'?clock|h|hrs?|horas?|in|on|de|del|y|and|en|el|la|yesterday|"
                        r"ayer|today|hoy|last|this|esta|este)\b))|"
                        r"\b(?P<h2>\d{1,2})(?::(?P<mi2>\d{2}))?\s*(?P<ap2>am|pm|a\.m\.|p\.m\.)(?!\w)")
PART_RULE = re.compile(r"\b(?:in\s+the\s+|this\s+|during\s+the\s+)?(?P<en>morning|afternoon|evening|night)\b|"
                       r"\b(?:esta|en\s+la|por\s+la|de\s+la|durante\s+la)\s+(?P<es>manana|tarde|noche)\b")


def time_words(text, now=None):
    """(start, end, rest) for the time words in `text` -- datetimes, and the
    text with them taken out (folded) -- or None when it has none."""
    now = now or datetime.datetime.now()
    q = fold(text)
    rules, ago, last_n = _day_rules(now)
    alt = _alt_patterns()
    span, cut = None, []
    for pattern, fn in rules:
        if fn is None:
            kind = pattern[1:]
            for p in alt[kind]:
                m = re.search(p, q)
                if m:
                    span = (ago if kind == "ago" else last_n)(m)
                    cut.append(m.span())
                    break
        else:
            m = re.search(pattern, q)
            if m and fn(m):
                span = fn(m)
                cut.append(m.span())
        if span:
            break
    # A time of day narrows one day (no day named: today, or yesterday when
    # that hour is still to come). Looked for in what the day words left.
    left = q
    for a, b in cut:
        left = left[:a] + " " * (b - a) + left[b:]
    m = CLOCK_RULE.search(left)
    part = PART_RULE.search(left)
    if m or part:
        if span is None:
            base = _day(now.date())
        elif span[1] - span[0] <= datetime.timedelta(days=1, hours=1):
            base = _day(span[0].date())
        else:
            base = None             # "last week at 3pm": the week it is
        cut += [x.span() for x in (m, part) if x]
        if base is not None and m:
            h, mi = int(m["h"] or m["h2"]), int(m["mi"] or m["mi2"] or 0)
            ap = (m["ap"] or m["ap2"] or "").replace(".", "")
            later = part and (part["en"] or part["es"]) not in ("morning", "manana")
            if (ap == "pm" or (not ap and later)) and h < 12:
                h += 12                     # "a las 3 de la tarde"
            elif (ap == "am" or (not ap and part)) and h == 12:
                h = 0
            elif not ap and not part and h < 7:
                h += 12                     # "at 3" means the afternoon
            if h < 24 and mi < 60:
                mid = base.replace(hour=h, minute=mi)
                if span is None and mid > now:
                    mid -= datetime.timedelta(days=1)
                span = (mid - datetime.timedelta(minutes=45), mid + datetime.timedelta(minutes=45))
        elif base is not None:
            lo, hi = PARTS[part["en"] or part["es"]]
            start = base + datetime.timedelta(hours=lo)
            if span is None and start > now:
                start -= datetime.timedelta(days=1)
            span = (start, start + datetime.timedelta(hours=hi - lo))
    if span is None:
        return None
    rest = q
    for a, b in sorted(cut, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    return span[0], min(span[1], now), " ".join(rest.split())


# -- the store ------------------------------------------------------------------------
SCHEMA = """
create table if not exists meta(key text primary key, value text);
create table if not exists entries(id integer primary key, t real, t_end real, source text, app text,
                                   title text, text text, url text, thumb text, approx text,
                                   key text unique, ntok integer, vec blob);
create index if not exists entries_t on entries(t);
create index if not exists entries_source on entries(source, t);
create table if not exists postings(term text, entry integer, tf integer, primary key(term, entry))
    without rowid;
create index if not exists postings_entry on postings(entry);
create table if not exists forgotten(kind text, value text, t0 real, t1 real);
"""


def connect(path=None):
    path = path or DB
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return con


def meta(con, key, value=None):
    if value is None:
        row = con.execute("select value from meta where key=?", (key,)).fetchone()
        return row[0] if row else None
    con.execute("insert or replace into meta values(?, ?)", (key, str(value)))


def blocked(con, t):
    """Inside a forgotten day, or before a wipe?"""
    return con.execute("select 1 from forgotten where kind in ('day', 'before') and ? >= t0 and ? < t1 limit 1",
                       (t, t)).fetchone() is not None


def add(con, source, t, text, app="", title="", key=None, t_end=None, url=None, thumb=None, approx=None):
    """One memory; False when it is already there (key) or inside a
    forgotten time."""
    if blocked(con, t):
        return False
    text = (text or "")[:MAX_TEXT]
    url = url or (URL.search(f"{title}\n{text}") or [None])[0]
    toks = tokens(f"{app} {title} {text}")
    try:
        cur = con.execute("insert into entries(t, t_end, source, app, title, text, url, thumb, approx, key, ntok)"
                          " values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (t, t_end if t_end is not None else t, source, app or "", title or "", text, url,
                           thumb, approx, key, len(toks)))
    except sqlite3.IntegrityError:
        return False
    tf = {}
    for w in toks:
        tf[w] = tf.get(w, 0) + 1
    con.executemany("insert into postings values(?, ?, ?)", [(w, cur.lastrowid, n) for w, n in tf.items()])
    return True


def drop(con, where, args=()):
    """Delete the memories matching an SQL condition, their words and
    their thumbnails. How many went."""
    rows = con.execute(f"select id, thumb from entries where {where}", args).fetchall()
    ids = [r[0] for r in rows]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        marks = ",".join("?" * len(part))
        con.execute(f"delete from postings where entry in ({marks})", part)
        con.execute(f"delete from entries where id in ({marks})", part)
    for _, thumb in rows:
        if thumb:
            try:
                os.unlink(thumb)
            except OSError:
                pass
    return len(ids)


def clock(t):
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M")


# -- the sources --------------------------------------------------------------------------
def norm_title(title):
    """A title without the spinners and counters terminals and chat apps put
    in front ("◑ Settings toolbox", "(3) Inbox"), for merging its flicker."""
    title = re.sub(r"^[^\w(]+|^\(\d+\)\s*", "", title or "")
    return " ".join(title.split())


def read_jsonl(path):
    rows = []
    try:
        with open(path) as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def activity_stretches(rows, after=float("-inf")):
    """[(start, end, class, title)] from activity-log rows: a row lasts until
    the next one; the same class and normalised title in a row is one
    stretch. The last row is still running and not returned; nor is
    anything starting at or before `after`."""
    out = []
    cur = None
    for i, row in enumerate(rows[:-1]):
        a, b = row.get("t", 0), rows[i + 1].get("t", 0)
        cls, title = row.get("class") or "", norm_title(row.get("title", ""))
        if cur and cur[2] == cls and cur[3] == title and a - cur[1] < MERGE_GAP_S:
            cur[1] = b
            continue
        if cur:
            out.append(tuple(cur))
        cur = [a, b, cls, title]
    if cur:
        out.append(tuple(cur))
    return [s for s in out if s[0] > after and s[2] not in ("", "private") and s[1] - s[0] >= MIN_ACTIVITY_S]


def hold(con, off, now):
    """The sources that are off take in nothing of their time off: their
    cursors move on (activity to now, the copies / notifications back to a
    first run with no backlog), and the captions not yet taken in go. Each
    is marked, so turning it on starts from when privacy.conf changed."""
    for source in off:
        meta(con, f"off_{source}", now)
    if "activity" in off:
        meta(con, "activity_upto", now)
    if "clipboard" in off:
        con.execute("delete from meta where key in ('clip_max_id', 'clip_checked')")
    if "notifications" in off:
        con.execute("delete from meta where key in ('notes_seen', 'notes_checked')")
    if "captions" in off:
        meta(con, "captions_upto", now)
        try:
            os.unlink(CAPTIONS)
        except OSError:
            pass


def resumed(con, source):
    """When `source` was off at the last collect: the time it was turned on
    (privacy.conf's last change, else now), the mark cleared. Else None."""
    if meta(con, f"off_{source}") is None:
        return None
    con.execute("delete from meta where key=?", (f"off_{source}",))
    try:
        return os.path.getmtime(privacy_settings.CONF)
    except (OSError, AttributeError):
        return time.time()


def ingest_activity(con, conf):
    rows = read_jsonl(ACTIVITY)
    upto = float(meta(con, "activity_upto") or 0)
    on_since = resumed(con, "activity")
    if on_since:
        upto = max(upto, on_since)
    skip = excluded_apps(conf)
    n = 0
    last = con.execute("select id, app, title, t_end from entries where source='activity' order by t desc "
                       "limit 1").fetchone()
    for a, b, cls, title in activity_stretches(rows, upto):
        upto = max(upto, a)
        if cls.lower() in skip or looks_secret(title):
            continue
        if last and last[1] == cls and last[2] == title and a - last[3] < MERGE_GAP_S:
            con.execute("update entries set t_end=? where id=?", (b, last[0]))
            last = (last[0], cls, title, b)
            continue
        if add(con, "activity", a, title, app=cls, title=title, key=f"activity:{a}", t_end=b):
            n += 1
            last = con.execute("select id, app, title, t_end from entries where key=?",
                               (f"activity:{a}",)).fetchone()
    meta(con, "activity_upto", upto)
    return n


def cliphist_lines():
    try:
        out = subprocess.run(["cliphist", "list"], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    lines = []
    for line in out.decode(errors="replace").splitlines():
        cid, _, preview = line.partition("\t")
        if cid.isdigit():
            lines.append((int(cid), line, preview))
    return lines


def cliphist_text(line):
    try:
        res = subprocess.run(["cliphist", "decode"], input=line.encode(), capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if b"\0" in res.stdout[:4096]:
        return None
    return res.stdout.decode(errors="replace")


def ingest_clipboard(con, conf, now, lines=None):
    lines = cliphist_lines() if lines is None else lines
    if lines is None:
        return 0
    newest = max((cid for cid, _, _ in lines), default=0)
    seen = meta(con, "clip_max_id")
    since = float(meta(con, "clip_checked") or now)
    meta(con, "clip_checked", now)
    if seen is None:                # the first run: from now on, no backlog
        meta(con, "clip_max_id", newest)
        return 0
    seen = int(seen)
    if newest < seen:               # the history was wiped: ids start again
        seen = 0
    n = 0
    for cid, line, preview in sorted(lines)[-CLIP_PER_RUN:]:
        if cid <= seen or preview.startswith("[[ binary data"):
            continue
        text = cliphist_text(line)
        if not text or not text.strip() or looks_secret(text):
            continue
        approx = f"copied between {clock(since)} and {clock(now)}" if now - since > 90 else None
        if add(con, "clipboard", now, text.strip(), key=f"clip:{cid}:{hashlib.sha1(text.encode()).hexdigest()[:12]}",
               approx=approx):
            n += 1
    meta(con, "clip_max_id", newest)
    return n


def mako(*args):
    try:
        out = subprocess.run(["makoctl", *args, "-j"], capture_output=True, text=True, timeout=5).stdout
        data = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    # mako 1.9+: a list; older: {"type": ..., "data": [[{"summary": {"data": ...}}]]}
    if isinstance(data, dict):
        rows = []
        for group in data.get("data") or []:
            for n in group:
                rows.append({k: (v.get("data") if isinstance(v, dict) else v) for k, v in n.items()})
        return rows
    return data if isinstance(data, list) else None


def note_key(n):
    body = f"{n.get('app_name')}\n{n.get('summary')}\n{n.get('body')}"
    return f"note:{n.get('id')}:{hashlib.sha1(body.encode()).hexdigest()[:12]}"


def ingest_notifications(con, conf, now, notes=None):
    if notes is None:
        shown, history = mako("list"), mako("history")
        if shown is None and history is None:
            return 0
        notes = (shown or []) + (history or [])
    seen = json.loads(meta(con, "notes_seen") or "null")
    since = float(meta(con, "notes_checked") or now)
    meta(con, "notes_checked", now)
    keys = [note_key(n) for n in notes]
    if seen is None:                # the first run: from now on, no backlog
        meta(con, "notes_seen", json.dumps(keys[-400:]))
        return 0
    seen = set(seen)
    skip = excluded_apps(conf)
    n_new = 0
    for n, key in zip(notes, keys):
        if key in seen:
            continue
        seen.add(key)
        app = n.get("app_name") or ""
        summary, body = n.get("summary") or "", re.sub(r"<[^>]+>", "", n.get("body") or "")
        urgency = n.get("urgency")
        if (app.lower() in NOTE_SKIP_APPS or app.lower() in skip or urgency in ("low", 0)
                or looks_secret(f"{summary}\n{body}")):
            continue
        approx = f"arrived between {clock(since)} and {clock(now)}" if now - since > 90 else None
        if add(con, "notifications", now, body or summary, app=app, title=summary, key=key, approx=approx):
            n_new += 1
    meta(con, "notes_seen", json.dumps(list(seen)[-400:]))
    return n_new


def caption_paragraphs(rows, after=0.0):
    """[(start, end, text)]: caption lines later than `after`, lines less
    than CAPTION_GAP_S apart joined (up to CAPTION_PARA characters)."""
    out, cur = [], None
    for row in rows:
        t, text = row.get("t", 0), (row.get("text") or "").strip()
        if t <= after or not text:
            continue
        if cur and t - cur[1] < CAPTION_GAP_S and len(cur[2]) + len(text) < CAPTION_PARA:
            cur[1], cur[2] = t, cur[2] + " " + text
            continue
        if cur:
            out.append(tuple(cur))
        cur = [t, t, text]
    if cur:
        out.append(tuple(cur))
    return out


def ingest_captions(con, conf, now):
    rows = sorted(read_jsonl(CAPTIONS), key=lambda r: r.get("t", 0))
    upto = float(meta(con, "captions_upto") or 0)
    # The last paragraph may still be growing: wait until it has been quiet.
    paras = [p for p in caption_paragraphs(rows, upto) if now - p[1] > CAPTION_GAP_S]
    n = 0
    for a, b, text in paras:
        upto = max(upto, b)
        text = scrub(text)
        if text and add(con, "captions", a, text, app="captions", key=f"captions:{a}", t_end=b):
            n += 1
    meta(con, "captions_upto", upto)
    # The log only holds what is still to be taken in: the raw lines (the
    # secret-looking ones too) do not wait there for their days to pass.
    rewrite_captions(lambda t: t > upto)
    return n


# -- screenshots ---------------------------------------------------------------------------
def hyprctl_json(*args):
    """`hyprctl ARGS -j`, parsed; None when Hyprland does not answer. Over the
    request socket (desk_common.hypr_request): no process."""
    return desk_common.hypr_request(args, json=True, timeout=3)


def locked():
    try:
        return subprocess.run(["pidof", "hyprlock"], capture_output=True, timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True


def screen_plan(monitors, clients, conf):
    """[(monitor, focused window or None)] to capture, and [why not] for the
    others: off, private window on it, nothing on it."""
    take, why = [], []
    for mon in monitors or []:
        if mon.get("disabled") or mon.get("dpmsStatus") is False:
            why.append(f"{mon.get('name')}: off")
            continue
        shown = {(mon.get(k) or {}).get("id") for k in ("activeWorkspace", "specialWorkspace")} - {None, 0}
        # Pinned windows (a PiP, a floating password prompt) show on every
        # workspace of their screen.
        wins = [c for c in clients or [] if ((c.get("workspace") or {}).get("id") in shown
                or (c.get("pinned") and c.get("monitor") == mon.get("id")))
                and not c.get("hidden") and c.get("mapped", True)]
        if not wins:
            why.append(f"{mon.get('name')}: nothing on it")
            continue
        private = [c for c in wins if private_window(c, conf)]
        if private:
            why.append(f"{mon.get('name')}: a private window")
            continue
        wins.sort(key=lambda c: c.get("focusHistoryID", 99))
        take.append((mon, wins[0]))
    return take, why


def screen_due(con, conf, now):
    last = float(meta(con, "screen_last") or 0)
    return now - last >= privacy_settings.memory_screen_minutes(conf) * 60


def make_thumb(png, out):
    from PIL import Image          # system python3-pillow
    with Image.open(png) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_W, THUMB_W * 4))
        os.makedirs(os.path.dirname(out), mode=0o700, exist_ok=True)
        im.save(out, "JPEG", quality=THUMB_Q, optimize=True)
    os.chmod(out, 0o600)


def ocr(png):
    """tesseract in Settings > Capture's languages (screen-actions.py), two
    threads at most."""
    os.environ.setdefault("OMP_THREAD_LIMIT", "2")
    try:
        return _module("screen_actions", "screen-actions.py").ocr(png)
    except Exception:       # noqa: BLE001 -- a broken helper: plain tesseract
        out = subprocess.run(["tesseract", png, "-", "-l", "eng+spa", "--psm", "3"], capture_output=True,
                             text=True, timeout=120).stdout
        return "\n".join(line.rstrip() for line in out.splitlines() if line.strip())


def snap(con, conf, now, force=False, log=lambda text: None):
    """Screenshots of the screens that may be taken: their OCR text and a
    thumbnail kept. A summary line."""
    if "screen" not in sources_on(conf):
        return "screen source off"
    if not force and not screen_due(con, conf, now):
        return "not due"
    if locked():
        return "screen locked"
    why = index().busy()
    if why:
        return why
    meta(con, "screen_last", now)
    take, skipped = screen_plan(hyprctl_json("monitors"), hyprctl_json("clients"), conf)
    kept = 0
    for mon, win in take:
        fd, png = tempfile.mkstemp(prefix="desktop-memory-", suffix=".png", dir=RUNTIME)
        os.close(fd)
        try:
            if subprocess.run(["grim", "-o", mon["name"], png], capture_output=True, timeout=20).returncode:
                skipped.append(f"{mon['name']}: grim failed")
                continue
            text = scrub(ocr(png))
            if text is None:
                skipped.append(f"{mon['name']}: a key or token on screen")
                continue
            digest = hashlib.sha1(" ".join(text.split()).encode()).hexdigest()
            if digest == meta(con, f"screen_hash_{mon['name']}") or len(text.split()) < 3:
                skipped.append(f"{mon['name']}: unchanged")
                continue
            meta(con, f"screen_hash_{mon['name']}", digest)
            stamp = datetime.datetime.fromtimestamp(now)
            thumb = os.path.join(THUMBS, f"{stamp:%Y-%m-%d}", f"{stamp:%H%M%S}-{mon['name']}.jpg")
            try:
                make_thumb(png, thumb)
            except Exception as exc:        # noqa: BLE001 -- no Pillow, a bad PNG: the text alone
                log(f"no thumbnail: {exc}")
                thumb = None
            if add(con, "screen", now, text, app=win.get("class") or "", title=win.get("title") or "",
                   key=f"screen:{now}:{mon['name']}", thumb=thumb):
                kept += 1
        finally:
            try:
                os.unlink(png)
            except OSError:
                pass
    return f"{kept} screenshot(s) kept" + (f"; skipped {', '.join(skipped)}" if skipped else "")


# -- embeddings ------------------------------------------------------------------------------
def doc_text(row):
    source, app, title, text = row
    return f"search_document: {SOURCE_NAMES.get(source, source)} {app}: {title}\n{text}"[:2000]


def embed_pending(con, log=lambda text: None, force=False, now=None):
    """Embeddings for the memories with none, with desktop-index.py's model
    and calls; never starts LM Studio for it. How many."""
    now = now or time.time()
    pending = con.execute("select count(*) from entries where vec is null").fetchone()[0]
    last = float(meta(con, "embedded_at") or 0)
    if not pending or (not force and now - last < EMBED_EVERY_S and pending < EMBED_RUSH):
        return 0
    di = index()
    model = di.embedding_model(start=False, log=log)
    if model is None:
        return 0
    if meta(con, "model") not in (None, model):
        con.execute("update entries set vec=null")
    meta(con, "model", model)
    count = 0
    while True:
        rows = con.execute("select id, source, app, title, text from entries where vec is null limit ?",
                           (EMBED_BATCH,)).fetchall()
        if not rows:
            break
        try:
            vecs = di.embed(model, [doc_text(r[1:]) for r in rows])
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            log(f"LM Studio failed: {exc}")
            break
        con.executemany("update entries set vec=? where id=?", [(v.tobytes(), r[0]) for v, r in zip(vecs, rows)])
        con.commit()
        count += len(rows)
    meta(con, "embedded_at", now)
    return count


def embed_hourly(log=lambda text: None, now=None):
    """desktop-index.py update's (the hourly timer's) pass over the memories:
    with LM Studio already up, the pending ones are embedded (EMBED_EVERY_S
    apart, sooner for a rush); with it down, it is started only when
    EMBED_START_S has gone by since the last pass, or a rush waits -- so the
    memories cost LM Studio a start a few times a day at most, not every
    5 minutes. How many were embedded (0 when the memory is off)."""
    now = now or time.time()
    if not sources_on(privacy_settings.load()):
        return 0
    con = connect()
    try:
        pending = con.execute("select count(*) from entries where vec is null").fetchone()[0]
        if not pending:
            return 0
        last = float(meta(con, "embedded_at") or 0)
        di = index()
        if di.server_models() is None:              # LM Studio is down
            if now - last < EMBED_START_S and pending < EMBED_RUSH:
                return 0
            if di.embedding_model(start=True, log=log) is None:
                return 0
        count = embed_pending(con, log, now=now)
        con.commit()
        return count
    finally:
        con.close()


# -- retention / forgetting -------------------------------------------------------------------
def prune(con, conf, now=None):
    now = now or time.time()
    gone = drop(con, "source != 'screen' and coalesce(t_end, t) < ?",
                (now - privacy_settings.memory_keep_days(conf) * 86400,))
    gone += drop(con, "source = 'screen' and t < ?", (now - privacy_settings.memory_screen_keep_days(conf) * 86400,))
    rewrite_captions(lambda t: t >= now - privacy_settings.memory_keep_days(conf) * 86400)
    con.execute("delete from forgotten where kind='day' and t1 < ?", (now - 400 * 86400,))
    # Thumbnails no memory points at (a snap that ran into a wipe or a
    # forget): gone once they are an hour old.
    known = {r[0] for r in con.execute("select thumb from entries where thumb is not null")}
    for root, _, files in os.walk(THUMBS):
        for name in files:
            path = os.path.join(root, name)
            try:
                if path not in known and os.path.getmtime(path) < now - 3600:
                    os.unlink(path)
            except OSError:
                pass
    for day in os.listdir(THUMBS) if os.path.isdir(THUMBS) else []:
        try:
            os.rmdir(os.path.join(THUMBS, day))        # only the empty ones go
        except OSError:
            pass
    return gone


def rewrite_captions(keep):
    rows = read_jsonl(CAPTIONS)
    if not rows:
        return
    if all(keep(r.get("t", 0)) for r in rows):
        return
    # voice.py appends a line at a time (open, write, close): the log is
    # moved aside first, so a line it writes meanwhile starts a new log
    # instead of being lost when the kept ones are written back.
    tmp = CAPTIONS + ".tmp"
    try:
        os.replace(CAPTIONS, tmp)
    except OSError:
        return
    kept = [r for r in read_jsonl(tmp) if keep(r.get("t", 0))]
    if kept:
        fd = os.open(CAPTIONS, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as handle:
            handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in kept)
    os.unlink(tmp)


def parse_day(text, now=None):
    now = now or datetime.datetime.now()
    word = fold(text).strip()
    if word in ("today", "hoy"):
        return now.date()
    if word in ("yesterday", "ayer"):
        return now.date() - datetime.timedelta(days=1)
    try:
        return datetime.date.fromisoformat(word)
    except ValueError:
        rng = time_words(word, now)
        if rng and rng[1] - rng[0] <= datetime.timedelta(days=1):
            return rng[0].date()
    return None


def forget_day(con, day):
    t0 = _day(day).timestamp()
    t1 = t0 + 86400
    n = drop(con, "t < ? and coalesce(t_end, t) >= ?", (t1, t0))
    # Forgetting today blocks what came before now, not the rest of the day.
    t1 = min(t1, time.time())
    con.execute("insert into forgotten values('day', ?, ?, ?)", (day.isoformat(), t0, t1))
    rewrite_captions(lambda t: not t0 <= t < t1)
    return n


def forget_app(con, cls):
    cls = privacy_settings.clean_class(cls)
    if not cls:
        return 0
    n = drop(con, "lower(app) = ?", (cls,))
    conf = privacy_settings.load()
    have = privacy_settings.memory_excluded_own(conf)
    if cls not in have:
        privacy_settings.set_key("memory_exclude", ",".join(have + [cls]))
    return n


def wipe():
    for path in (DB, DB + "-journal", DB + "-wal", DB + "-shm", CAPTIONS, CAPTIONS + ".tmp"):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    shutil.rmtree(THUMBS, ignore_errors=True)
    # A fresh store that knows where it starts: the activity log and the
    # clipboard / notifications from before are not taken in again.
    con = connect()
    try:
        now = time.time()
        con.execute("insert into forgotten values('before', 'wipe', 0, ?)", (now,))
        meta(con, "activity_upto", now)
        meta(con, "captions_upto", now)
        lines = cliphist_lines() or []
        meta(con, "clip_max_id", max((cid for cid, _, _ in lines), default=0))
        notes = (mako("list") or []) + (mako("history") or [])
        meta(con, "notes_seen", json.dumps([note_key(n) for n in notes]))
        con.commit()
    finally:
        con.close()


# -- searching -----------------------------------------------------------------------------
def _where(start, end, sources):
    clauses, args = [], []
    if start is not None:
        clauses.append("coalesce(e.t_end, e.t) >= ?")
        args.append(start)
    if end is not None:
        clauses.append("e.t <= ?")
        args.append(end)
    clauses.append(f"e.source in ({','.join('?' * len(sources))})")
    args += list(sources)
    return " and ".join(clauses), args


def bm25(con, terms, where, args, limit=80):
    n, total = con.execute(f"select count(*), coalesce(sum(ntok), 0) from entries e where {where}", args).fetchone()
    if not n or not terms:
        return []
    avg = total / n or 1.0
    scores = {}
    for term in terms:
        rows = con.execute(f"select p.entry, p.tf, e.ntok from postings p join entries e on e.id = p.entry "
                           f"where p.term = ? and {where}", [term] + args).fetchall()
        if not rows:
            continue
        idf = math.log(1 + (n - len(rows) + 0.5) / (len(rows) + 0.5))
        for eid, tf, dl in rows:
            scores[eid] = scores.get(eid, 0.0) + idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * (dl or avg) / avg))
    return sorted(scores.items(), key=lambda kv: -kv[1])[:limit]


def cosine(con, qvec, where, args, limit=80):
    rows = con.execute(f"select e.id, e.vec from entries e where e.vec is not null and {where}", args).fetchall()
    scored = []
    for eid, blob in rows:
        v = array.array("f")
        v.frombytes(blob)
        scored.append((eid, sum(a * b for a, b in zip(v, qvec))))
    scored.sort(key=lambda kv: -kv[1])
    return [s for s in scored[:limit] if s[1] > 0.45]


def snippet(text, terms, size=320):
    flat = " ".join((text or "").split())
    low = fold(flat)
    at = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
    start = max(0, at - size // 3)
    return ("…" if start else "") + flat[start:start + size] + ("…" if start + size < len(flat) else "")


def describe(row, terms):
    eid, t, t_end, source, app, title, text, url, thumb, approx = row
    out = {"id": eid, "source": source, "when": datetime.datetime.fromtimestamp(t).strftime("%a %Y-%m-%d %H:%M"),
           "t": t, "app": app, "title": title[:200]}
    if t_end and t_end - t >= 60:
        out["until"] = clock(t_end)
        out["minutes"] = round((t_end - t) / 60)
    if approx:
        out["approx"] = approx
    if source != "activity" and text and text != title:
        out["text"] = snippet(text, terms)
    if url:
        out["url"] = url
    if thumb and os.path.exists(thumb):
        out["thumbnail"] = thumb
    return out


def fold_activity(results):
    """The same window seen many times is one result: its last time first,
    how often, and the time in all."""
    out, seen = [], {}
    for r in results:
        if r["source"] != "activity":
            out.append(r)
            continue
        key = (r["app"], r["title"])
        if key in seen:
            first = seen[key]
            first["times"] = first.get("times", 1) + 1
            first["minutes"] = first.get("minutes", 0) + r.get("minutes", 0)
            if r["t"] > first["t"]:
                first["last_seen"] = r["when"]
            continue
        seen[key] = r
        out.append(r)
    return out


LINK_WORDS = re.compile(r"\b(links?|urls?|enlaces?|ligas?|website|web|pagina|page|site|sitio)\b")
SOURCE_WORDS = {
    "clipboard": re.compile(r"\b(copied|copy|copie|copiaste|copiado|clipboard|portapapeles)\b"),
    "notifications": re.compile(r"\b(notifications?|notificacion(es)?|messages?|mensajes?|sent me|send me|"
                                r"mandaron|enviaron|me mando|me envio|someone sent|alguien)\b"),
    "captions": re.compile(r"\b(heard|hear|said|listened|escuche|oi|dijo|dijeron|call|llamada|meeting|"
                           r"reunion|junta|video)\b"),
    "screen": re.compile(r"\b(screen|pantalla|on screen|en pantalla)\b"),
}


def hints(query):
    """(wants a link, [sources the words point at]) -- "what link did
    someone send", "lo que escuché en la llamada"."""
    q = fold(query)
    return bool(LINK_WORDS.search(q)), [s for s, rx in SOURCE_WORDS.items() if rx.search(q)]


def search(query, start=None, end=None, sources=None, k=K_DEFAULT, con=None, use_model=True, conf=None):
    """{"results": [...], "mode": ..., "range": [start, end]} or {"note": ...}.
    start / end: epoch seconds or None; sources: limited to what is on."""
    conf = privacy_settings.load() if conf is None else conf
    allowed = sources_on(conf)
    if not privacy_settings.memory_on(conf):
        return {"note": OFF_TEXT, "off": True}
    sources = [s for s in SOURCES if s in allowed and (not sources or s in sources)]
    if not sources:
        return {"note": "every source of the desktop memory asked for is off (Settings > Privacy)"}
    own = con is None
    if own:
        if not os.path.exists(DB):
            return {"note": "the desktop memory is empty so far (it fills every 5 minutes)"}
        con = connect()
    try:
        where, args = _where(start, end, sources)
        want_link, pointed = hints(query)
        link = ""
        if want_link and con.execute(f"select 1 from entries e where {where} and e.url is not null limit 1",
                                     args).fetchone():
            link = " and e.url is not null"
            where += link
        terms = [t for t in query_terms(query) if not LINK_WORDS.fullmatch(t)]
        ranked_kw = bm25(con, terms, where, args) if terms else []
        ranked_sem = []
        # In game mode the GPU is the game's: not even the small embedding
        # model is loaded for a question (keywords only).
        if (terms and use_model and con.execute("select 1 from entries where vec is not null limit 1").fetchone()
                and index().busy() not in ("game mode is on", "a game is running")):
            di = index()
            model = di.embedding_model(start=False)
            if model:
                try:
                    ranked_sem = cosine(con, di.embed(model, [f"search_query: {query}"], timeout=30)[0], where, args)
                except (urllib.error.URLError, OSError, ValueError, KeyError):
                    ranked_sem = []
        cols = "e.id, e.t, e.t_end, e.source, e.app, e.title, e.text, e.url, e.thumb, e.approx"
        if not terms:
            # Nothing but time words: that time's memories, newest first,
            # the longer window stretches before the short ones.
            pointed = [s for s in pointed if s in sources]
            if pointed:
                narrow, nargs = _where(start, end, pointed)
                narrow += link
                if con.execute(f"select 1 from entries e where {narrow} limit 1", nargs).fetchone():
                    where, args = narrow, nargs
            # The longest window stretches and the newest of everything else.
            rows = con.execute(f"select {cols} from entries e where {where} and e.source != 'activity' "
                               f"order by e.t desc limit ?", args + [k]).fetchall()
            rows += con.execute(f"select {cols} from entries e where {where} and e.source = 'activity' "
                                f"order by coalesce(e.t_end, e.t) - e.t desc limit ?", args + [k * 2]).fetchall()
            results = fold_activity([describe(r, terms) for r in rows])
            results = sorted(results, key=lambda r: (r["source"] == "activity", -r["t"]))[:k]
            results.sort(key=lambda r: r["t"])
            return {"mode": "timeline", "results": results}
        fused = {}
        if pointed:
            boost = {eid for eid, in con.execute(
                f"select e.id from entries e where {where} and e.source in ({','.join('?' * len(pointed))})",
                args + pointed)}
            fused = {eid: 0.5 / RRF for eid, _ in ranked_sem + ranked_kw if eid in boost}
        for ranked in (ranked_sem, ranked_kw):
            for rank, (eid, _) in enumerate(ranked):
                fused[eid] = fused.get(eid, 0.0) + 1.0 / (RRF + rank)
        order = [eid for eid, _ in sorted(fused.items(), key=lambda kv: -kv[1])][:k * 4]
        results = []
        for eid in order:
            row = con.execute(f"select {cols} from entries e where e.id = ?", (eid,)).fetchone()
            if row:
                results.append(describe(row, terms))
        results = fold_activity(results)[:k]
        return {"mode": "meaning + keywords" if ranked_sem else "keywords only", "results": results}
    finally:
        if own:
            con.close()


def search_words(text, now=None, k=K_DEFAULT, sources=None, conf=None):
    """search() on a question as typed: its time words become the range."""
    now = now or datetime.datetime.now()
    rng = time_words(text, now)
    if rng:
        start, end, rest = rng
        res = search(rest, start.timestamp(), end.timestamp(), sources, k, conf=conf)
        res["range"] = [start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")]
        return res
    return search(text, None, None, sources, k, conf=conf)


# -- answering ------------------------------------------------------------------------------
def memory_lines(results):
    lines = []
    for i, r in enumerate(results, 1):
        when = r["when"] + (f"-{r['until']}" if r.get("until") else "")
        bits = [f"[{i}] {when}", SOURCE_NAMES.get(r["source"], r["source"])]
        if r.get("approx"):
            bits.append(f"({r['approx']})")
        if r.get("app"):
            bits.append(r["app"])
        if r.get("title"):
            bits.append(f"\"{r['title']}\"")
        if r.get("times", 1) > 1:
            bits.append(f"seen {r['times']} times, last {r.get('last_seen', r['when'])}"
                        + (f", {r['minutes']} min in all" if r.get("minutes") else ""))
        line = "  ".join(bits)
        if r.get("text"):
            line += f"\n    {r['text']}"
        if r.get("url"):
            line += f"\n    link: {r['url']}"
        if r.get("thumbnail"):
            line += f"\n    screenshot: {r['thumbnail']}"
        lines.append(line)
    return "\n".join(lines)


def links_of(results, answer=""):
    """What the answer's buttons open: the links and screenshots of the
    memories it cites ([2]), else of the top ones. [(label, target)]."""
    cited = [int(n) - 1 for n in re.findall(r"\[(\d+)\]", answer or "")]
    picked = [results[i] for i in dict.fromkeys(cited) if 0 <= i < len(results)] or results[:4]
    out = []
    for r in picked:
        if r.get("url"):
            host = re.sub(r"^https?://(www\.)?", "", r["url"]).split("/")[0]
            out.append((f"Open {host}"[:40], r["url"]))
        if r.get("thumbnail"):
            out.append((f"Show {r['when'][4:]}", r["thumbnail"]))
    return list(dict.fromkeys(out))[:3]


def plain_answer(results, why=None):
    if not results:
        return "Nothing in the desktop memory matches that."
    head = f"(no local model: {why})\n" if why else ""
    return head + memory_lines(results[:6])


def recall(question, now=None, worker=None):
    """(answer, results, links)."""
    now = now or datetime.datetime.now()
    conf = privacy_settings.load()
    if not privacy_settings.memory_on(conf):
        return OFF_TEXT, [], []
    res = search_words(question, now, conf=conf)
    if "note" in res:
        return res["note"].capitalize(), [], []
    results = res["results"]
    if not results:
        span = f" between {res['range'][0]} and {res['range'][1]}" if res.get("range") else ""
        return f"Nothing in the desktop memory matches that{span}.", [], []
    worker = worker or _module("llm_worker", "llm-worker.py")
    model, why = None, None
    for role in MODEL_ROLES:
        model, why = worker.ready(role)
        if model:
            break
    if model is None:
        return plain_answer(results, why), results, links_of(results)
    prompt = (f"Now is {now:%A %Y-%m-%d %H:%M}.\nQuestion: {question}\n"
              + (f"(searched between {res['range'][0]} and {res['range'][1]})\n" if res.get("range") else "")
              + f"\nMemories:\n{memory_lines(results)}")
    try:
        answer = worker.ask(model, prompt, SYSTEM, {"reasoning_effort": "none", "max_tokens": 700})
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        return plain_answer(results, f"the model failed: {exc}"), results, links_of(results)
    return answer or plain_answer(results), results, links_of(results, answer)


def notify_recall(question):
    # "--": a question starting with "-" is text, not one of notify-send's options.
    subprocess.run([NOTIFY, *NOTIFY_TAG, "-u", "low", "-t", "0", "--", "Remembering…", question],
                   capture_output=True, timeout=5)
    answer, results, links = recall(question)
    actions = [f"--action=open{i}={label}" for i, (label, _) in enumerate(links)]
    icon = next((target for _, target in links if target.endswith(".jpg")), "document-open-recent")
    try:
        out = subprocess.run([NOTIFY, *NOTIFY_TAG, "-t", "60000", "-i", icon, *actions,
                              *(["--wait"] if actions else []), "--", question, answer[:1500]],
                             capture_output=True, text=True, timeout=120).stdout.strip()
    except subprocess.TimeoutExpired:
        return
    if out.startswith("open") and out[4:].isdigit() and int(out[4:]) < len(links):
        subprocess.Popen(["gio", "open", links[int(out[4:])][1]], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -- collect / status -----------------------------------------------------------------------------
def be_gentle():
    index().be_gentle()


def collect(log=print, now=None, force_snap=False):
    now = now or time.time()
    conf = privacy_settings.load()
    con = connect()
    try:
        gone = prune(con, conf, now)
        con.commit()
        on = sources_on(conf)
        hold(con, [s for s in SOURCES if s not in on], now)
        for source in on - {"activity"}:
            con.execute("delete from meta where key=?", (f"off_{source}",))
        done = {}
        if "activity" in on:
            done["activity"] = ingest_activity(con, conf)
        if "clipboard" in on:
            done["clipboard"] = ingest_clipboard(con, conf, now)
        if "notifications" in on:
            done["notifications"] = ingest_notifications(con, conf, now)
        if "captions" in on:
            done["captions"] = ingest_captions(con, conf, now)
        con.commit()
        shot = snap(con, conf, now, force_snap, log) if "screen" in on else None
        con.commit()
        meta(con, "collected", now)
        con.commit()
    finally:
        con.close()
    line = ", ".join(f"{k} +{v}" for k, v in done.items()) or "every source is off"
    return line + (f"; screen: {shot}" if shot else "") + \
        (f"; {gone} past their days dropped" if gone else "")


def dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def status():
    conf = privacy_settings.load()
    on = sources_on(conf)
    out = {"on": privacy_settings.memory_on(conf), "path": DIR, "bytes": dir_size(DIR) if os.path.isdir(DIR) else 0,
           "thumbs_bytes": dir_size(THUMBS) if os.path.isdir(THUMBS) else 0,
           "keep_days": privacy_settings.memory_keep_days(conf),
           "screen_keep_days": privacy_settings.memory_screen_keep_days(conf),
           "screen_minutes": privacy_settings.memory_screen_minutes(conf),
           "exclude": privacy_settings.memory_excluded_own(conf),
           "sources": {s: {"on": s in on, "switch": privacy_settings.flag(conf.get(f"memory_{s}",
                                                                                   privacy_settings.DEFAULTS[f"memory_{s}"])),
                           "count": 0, "since": None, "newest": None} for s in SOURCES},
           "entries": 0, "embedded": 0, "model": None, "collected": None, "screen_last": None}
    if os.path.exists(DB):
        con = sqlite3.connect(DB, timeout=10)
        try:
            for source, n, lo, hi in con.execute("select source, count(*), min(t), max(t) from entries "
                                                 "group by source"):
                if source in out["sources"]:
                    out["sources"][source].update(count=n, since=lo, newest=hi)
            out["entries"], out["embedded"] = con.execute("select count(*), count(vec) from entries").fetchone()
            rows = dict(con.execute("select key, value from meta").fetchall())
            out["model"] = rows.get("model") if out["embedded"] else None
            out["collected"] = float(rows["collected"]) if rows.get("collected") else None
            out["screen_last"] = float(rows["screen_last"]) if rows.get("screen_last") else None
            out["forgotten_days"] = [r[0] for r in con.execute(
                "select value from forgotten where kind='day' order by t0 desc limit 10")]
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return out


def apps(limit=30):
    if not os.path.exists(DB):
        return []
    con = sqlite3.connect(DB, timeout=10)
    try:
        return [{"app": a, "count": n} for a, n in con.execute(
            "select lower(app), count(*) from entries where app != '' group by lower(app) "
            "order by count(*) desc limit ?", (limit,))]
    finally:
        con.close()


def human_status(s):
    def day(t):
        return datetime.datetime.fromtimestamp(t).strftime("%a %d %b %H:%M") if t else "-"
    lines = [f"desktop memory  {'on' if s['on'] else 'off (Settings > Privacy)'}, kept {s['keep_days']} days "
             f"(screenshots {s['screen_keep_days']}), {s['bytes'] / 1024 / 1024:.1f} MiB in {s['path']}"]
    for name, src in s["sources"].items():
        lines.append(f"  {name:<14} {'on ' if src['on'] else 'off'}  {src['count']:>6}  since {day(src['since'])}")
    lines.append(f"  embeddings     {s['embedded']} of {s['entries']} ({s['model'] or 'keywords only'})")
    lines.append(f"  last collect   {day(s['collected'])}")
    return "\n".join(lines)


# -- the command line -----------------------------------------------------------------------------
def option(args, name, cast=str, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            value = args[i + 1]
            del args[i:i + 2]
            return cast(value)
    return default


def iso(value):
    return datetime.datetime.fromisoformat(value).timestamp()


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, args = argv[0], list(argv[1:])
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if cmd == "collect":
        be_gentle()
        print(collect(log=lambda t: print(t, flush=True)))
    elif cmd == "snap":
        be_gentle()
        con = connect()
        try:
            print(snap(con, privacy_settings.load(), time.time(), "--force" in args, log=print))
            con.commit()
        finally:
            con.close()
    elif cmd == "embed":
        be_gentle()
        con = connect()
        try:
            print(f"{embed_pending(con, print, force=True)} embedded")
            con.commit()
        finally:
            con.close()
    elif cmd == "search":
        start, end = option(args, "--from", iso), option(args, "--to", iso)
        source = option(args, "--source")
        k = option(args, "-k", int, K_DEFAULT)
        words = " ".join(args).strip()
        if start or end:
            res = search(words, start, end, [source] if source else None, k)
        else:
            res = search_words(words, k=k, sources=[source] if source else None)
        if as_json:
            print(json.dumps(res, ensure_ascii=False))
        elif "note" in res:
            print(res["note"])
        else:
            print(f"({res['mode']}{', ' + ' to '.join(res['range']) if res.get('range') else ''})")
            print(memory_lines(res["results"]))
    elif cmd == "recall":
        question = " ".join(a for a in args if a != "--notify").strip()
        if not question:
            sys.exit("desktop-memory: recall what?")
        if "--notify" in args:
            notify_recall(question)
            return
        answer, results, links = recall(question)
        if as_json:
            print(json.dumps({"answer": answer, "links": [t for _, t in links], "results": results},
                             ensure_ascii=False))
        else:
            print(answer)
            for label, target in links:
                print(f"  {label}: {target}")
    elif cmd == "when":
        rng = time_words(" ".join(args))
        if as_json:
            print(json.dumps(rng and [rng[0].isoformat(), rng[1].isoformat(), rng[2]]))
        else:
            print("no time words" if not rng else f"{rng[0]:%a %Y-%m-%d %H:%M} -> {rng[1]:%a %Y-%m-%d %H:%M}"
                  f"   rest: {rng[2]!r}")
    elif cmd == "status":
        s = status()
        print(json.dumps(s) if as_json else human_status(s))
    elif cmd == "apps":
        rows = apps()
        print(json.dumps(rows) if as_json else "\n".join(f"{r['count']:>6}  {r['app']}" for r in rows))
    elif cmd == "forget" and len(args) == 2 and args[0] in ("day", "app", "source", "entry"):
        con = connect()
        try:
            if args[0] == "day":
                day = parse_day(args[1])
                if day is None:
                    sys.exit("desktop-memory: which day? (2026-10-20, today, yesterday, tuesday...)")
                n = forget_day(con, day)
            elif args[0] == "app":
                n = forget_app(con, args[1])
            elif args[0] == "source":
                if args[1] not in SOURCES:
                    sys.exit(f"desktop-memory: sources are {', '.join(SOURCES)}")
                n = drop(con, "source = ?", (args[1],))
            elif args[1].isdigit():
                n = drop(con, "id = ?", (int(args[1]),))
            else:
                sys.exit("desktop-memory: forget entry takes a memory's id (search --json shows them)")
            con.commit()
        finally:
            con.close()
        print(f"desktop-memory: {n} memories forgotten")
    elif cmd == "wipe":
        wipe()
        print("desktop-memory: everything is forgotten")
    elif cmd == "prune":
        con = connect()
        try:
            print(f"desktop-memory: {prune(con, privacy_settings.load())} dropped")
            con.commit()
        finally:
            con.close()
    else:
        sys.exit(f"desktop-memory: unknown command {cmd!r} (desktop-memory.py --help)")


if __name__ == "__main__":
    main(sys.argv[1:])
