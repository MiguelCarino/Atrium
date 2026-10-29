#!/usr/bin/env python3
"""Smart clipboard: when you copy something it recognises, a small card in
the corner offers one to three things to do with it -- open the map for an
address, the tracking page for a parcel number, pretty-print JSON, work out
a sum. Nothing happens unless you click; the card goes by itself.

    smart-clipboard.py hook          what smart-clipboard.service runs on every copy
                                     (wl-paste --type text --watch ...): the copy on
                                     stdin, CLIPBOARD_STATE in the environment
    smart-clipboard.py detect [TEXT] what it would offer for TEXT (else stdin), as
                                     JSON -- for trying the rules by hand
    smart-clipboard.py get [--json]  the settings: on/off, and each kind
    smart-clipboard.py set on|off    the whole thing (enable --now / disable --now
                                     the unit, like the clipboard history)
    smart-clipboard.py set KIND on|off   one kind (KINDS below)
    smart-clipboard.py toast         (internal) the card; its JSON on stdin

FAST RULES, NO MODEL. detect() is plain regular expressions and checksums
(a parcel number's check digit, a card's Luhn sum): nothing is sent
anywhere and no LLM runs to decide. Only "Ask about this error" uses the
local model, and only when clicked (screen-ask.py text, local only).

The copy has to BE the thing -- a whole-text match (a URL, an address, a
date) -- except for errors and stack traces, which are found by their
usual lines. A copied paragraph that merely contains a URL offers nothing.

NEVER ACTED ON, whatever is switched on (looks_secret(): no card is shown at
all, the copy is not even classified further):
    - copies the copying app marks as sensitive (CLIPBOARD_STATE=sensitive:
      KeePassXC and other password managers do), and copies made while a
      password manager, a private-browsing window or an app on the Privacy
      page's private list has the focus (activity-log.py's is_private, plus
      SECRET_APPS)
    - card numbers (Luhn), IBANs (mod 97), Mexican CLABEs (their check digit)
    - private keys, API tokens with a known shape (ghp_, sk-, AKIA..., JWTs,
      "Bearer ..."), links with a password in them (https://user:pw@host)
    - "password: ...", "token=...", '"api_key": ...' lines (quoted keys too)
    - one word of 10+ characters mixing three of lower / upper / digits /
      symbols: what a password looks like -- unless it plainly parses as one
      of the kinds (minified JSON, rgb(0,240,255), 2026-10-21T15:30, a sum)
    - paths into ~/.ssh, ~/.gnupg, keyrings, *.env (llm-worker.py's looks_secret)

QUIET (rate_ok()): at most one card every MIN_GAP_S, the same copy is never
offered twice within REPEAT_S, and none at all while Do Not Disturb or
gamemode is on. Our own copies (the pretty-printed JSON put back on the
clipboard) are remembered so they do not offer anything again.

SETTINGS: whether the service runs is the switch (Settings > Smart
clipboard, and a link on Settings > Privacy); each kind is a key in
~/.config/hypr/privacy.conf, "smartclip_<kind>=on|off" (privacy_settings.py
reads and writes that file; a missing key is the kind's default below).
Harmless kinds are on by default; URLs are off -- you copy links all the
time and "open it" is not worth a card each time.

THE CARD is a small GTK layer-shell window (panel.css's look) at the top
right of the focused screen, under the bar like mako's notifications.
mako draws no buttons of its own (it invokes the default action on a
click), so the card is ours: it never takes the keyboard, shows up to
three buttons and a x, stays while the pointer is on it, and is gone after
TOAST_S. A new copy replaces the card that is up.

LIVE SUGGESTIONS (suggest.py) can take the cards instead: with its service
running and its "clipboard" kind on, hook() hands the card (after every rule
above) to its socket and shows nothing itself; the strip shows it and runs
the buttons through run_action() here. No answer from the socket: our card.
"""
import ast
import datetime as dt
import hashlib
import importlib.util
import json
import math
import operator
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import privacy_settings  # noqa: E402  (privacy.conf: the per-kind switches)
import desk_common  # noqa: E402  (hypr_request: hyprctl over the socket)

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
STATE = os.path.join(RUNTIME, "smart-clipboard.json")
PID_FILE = os.path.join(RUNTIME, "smart-clipboard-toast.pid")
STRIP_SOCK = os.path.join(RUNTIME, "suggest.sock")     # Live suggestions (suggest.py) takes the cards
UNIT = "smart-clipboard.service"
SCREEN_ASK = os.path.join(HERE, "screen-ask.py")
PHONE = os.path.join(HERE, "phone.py")

MAX_BYTES = 200_000         # bigger copies are left alone (a JSON this size is still fine)
MAX_SHORT = 300             # the kinds that are one short thing (a URL, a number)
MIN_GAP_S = 3
REPEAT_S = 600
TOAST_S = 9
SEEN_KEEP = 200
STARTUP_S = 2               # the watcher's first call is the clipboard as it was

# kind: (label for Settings, on by default, an example for the page)
KINDS = {
    "url": ("Links", False, "https://example.com/page?utm_source=x"),
    "email": ("Email addresses", True, "someone@example.com"),
    "phone": ("Phone numbers", True, "+52 55 1234 5678"),
    "address": ("Postal addresses", True, "Av. Reforma 222, Col. Juárez, 06600 CDMX"),
    "colour": ("Colour codes", True, "#00f0ff, rgb(0 240 255)"),
    "path": ("File paths", True, "~/Documents/report.pdf"),
    "error": ("Errors and stack traces", True, "Traceback (most recent call last): ..."),
    "tracking": ("Parcel tracking numbers", True, "1Z999AA10123456784 (UPS, USPS, FedEx, DHL, postal)"),
    "date": ("Dates and times", True, "21 Oct 2026 15:30, 2026-10-21, 21 de octubre"),
    "math": ("Sums", True, "12*(3+4)/2"),
    "json": ("JSON", True, '{"a": 1, "b": [2, 3]}'),
}

SECRET_APPS = re.compile(r"keepassxc|keepass|bitwarden|1password|enpass|seahorse|kwalletmanager|"
                         r"proton.?pass|lastpass|dashlane|keeper|gopass|qtpass|secrets", re.I)


# -- secrets: never acted on ---------------------------------------------------------------
TOKEN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|"
                   r"\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{20,}|\b[sr]k_(live|test)_[A-Za-z0-9]{10,}|"
                   r"\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{35}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}|"
                   r"\bglpat-[A-Za-z0-9_-]{20}|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.|"
                   r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}|^[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.I | re.M)
# the key may be quoted, as in JSON: {"password": "..."}
SECRET_WORD = re.compile(r"(pass(word|wd|phrase)?|pwd|contraseña|secret|token|api[_ -]?key|auth|"
                         r"authorization|private[_ -]?key|clave)[\"']?\s*[:=]", re.I)


def luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def iban_ok(text):
    s = text.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    moved = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def clabe_ok(digits):
    """A Mexican CLABE: 18 digits, the last a check over weights 3, 7, 1."""
    if len(digits) != 18:
        return False
    total = sum(int(d) * (3, 7, 1)[i % 3] % 10 for i, d in enumerate(digits[:17]))
    return (10 - total % 10) % 10 == int(digits[17])


def looks_like_password(word):
    if not 10 <= len(word) <= 128 or re.search(r"\s", word):
        return False
    if re.match(r"(https?://|www\.|file://|mailto:|tel:|~|/|\.{1,2}/|#)", word) or "@" in word:
        return False
    if _structured(word):       # minified JSON, rgb(0,240,255), 2026-10-21T15:30, a sum
        return False
    classes = sum(bool(re.search(p, word)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    return classes >= 3


def _structured(word):
    """A no-space word that is plainly one of the kinds (the parsers below),
    not a password: those mix digits and symbols too."""
    if word[:1] in "{[":
        try:
            return isinstance(json.loads(word), (dict, list))
        except ValueError:
            return False
    try:
        got = parse_date(word)
        return bool(parse_colour(word) or (got and not got[2]) or compute(word) is not None)
    except Exception:       # noqa: BLE001 -- unsure: let the password rule decide
        return False


def looks_secret(text):
    """Card numbers, IBANs, CLABEs, keys, tokens, password-like words or
    lines: the copy is not offered anything at all."""
    s = text.strip()
    digits = re.sub(r"[\s-]", "", s)
    if digits.isdigit():
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            return True
        if clabe_ok(digits):
            return True
    if iban_ok(s):
        return True
    if TOKEN.search(s) or SECRET_WORD.search(s):
        return True
    if "\n" not in s and looks_like_password(s):
        return True
    return False


def secret_path(path):
    """llm-worker.py's rule for files it may not read (~/.ssh, *.env, ...)."""
    try:
        return _module("llm_worker", "llm-worker.py").looks_secret(path)
    except Exception:       # noqa: BLE001 -- unknown: treat as secret
        return True


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


# -- the kinds ------------------------------------------------------------------------------
URL = re.compile(r"(https?://|www\.)[^\s<>\"']+$", re.I)
EMAIL = re.compile(r"(mailto:)?([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
HEX = re.compile(r"#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
FUNC = re.compile(r"(rgba?|hsla?)\(\s*([^)]*)\)$", re.I)
TRACKERS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid",
            "dclid", "msclkid", "mc_eid", "mc_cid", "igshid", "yclid", "_hsenc", "_hsmi", "ref_src")
ERROR_LINES = re.compile(
    r"Traceback \(most recent call last\)|^\s*File \".+\", line \d+|"
    r"^\s*(\w+\.)*\w*(Error|Exception)(: |$)|^\s+at [\w.$<>]+ ?\(.*:\d+(:\d+)?\)|"
    r"^\s+at .+:\d+:\d+$|panicked at|^error(\[E\d+\])?: |^npm ERR!|Segmentation fault|"
    r"Uncaught \w+|^FATAL|^fatal: |command not found$|No such file or directory|Permission denied$",
    re.M)
STREET = re.compile(r"\b(street|st\.|avenue|ave\.?|av\.|avenida|calle|blvd\.?|boulevard|road|rd\.|lane|"
                    r"ln\.|drive|dr\.|way|plaza|carretera|calzada|privada|col\.|colonia|c\.\s?p\.|"
                    r"cp \d{5}|zip|piso|depto\.?|int\.|ext\.|no\.\s?\d)", re.I)
MONTHS = {m: i + 1 for i, names in enumerate([
    ("jan", "january", "ene", "enero"), ("feb", "february", "febrero"), ("mar", "march", "marzo"),
    ("apr", "april", "abr", "abril"), ("may", "mayo"), ("jun", "june", "junio"),
    ("jul", "july", "julio"), ("aug", "august", "ago", "agosto"),
    ("sep", "sept", "september", "septiembre", "set", "setiembre"), ("oct", "october", "octubre"),
    ("nov", "november", "noviembre"), ("dec", "december", "dic", "diciembre")]) for m in names}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
TIME_RE = r"(?:(?:at|a las|@)\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|h|hrs)?"


class Found:
    """What detect() recognised: the kind, a title and body for the card,
    the actions [(id, label, arg)], and for colours the swatch."""

    def __init__(self, kind, title, body="", actions=(), swatch=None):
        self.kind, self.title, self.body = kind, title, body
        self.actions = list(actions)[:3]
        self.swatch = swatch

    def as_dict(self):
        return {"kind": self.kind, "title": self.title, "body": self.body,
                "actions": [list(a) for a in self.actions], "swatch": self.swatch}


def short(text, n=70):
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[:n - 1] + "…"


def clean_url(url):
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKERS and not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def as_url(s):
    if not URL.match(s):
        return None
    url = s if re.match(r"https?://", s, re.I) else "https://" + s
    actions = [("open", "Open", url)]
    clean = clean_url(url)
    if clean != url:
        actions.append(("copy", "Copy without trackers", clean))
    return Found("url", "Link copied", short(url), actions)


def as_email(s):
    m = EMAIL.fullmatch(s)
    if not m:
        return None
    return Found("email", "Email address", m[2], [("open", "Write an email", "mailto:" + m[2])])


def parse_colour(s):
    """(r, g, b, a) from #rgb[a] / #rrggbb[aa] / rgb[a]() / hsl[a](), or None."""
    m = HEX.fullmatch(s)
    if m:
        h = m[1]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return r, g, b, round(a, 3)
    m = FUNC.fullmatch(s)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m[2].strip()) if p]
    if len(parts) not in (3, 4):
        return None
    try:
        def num(p, scale):
            return float(p[:-1]) * scale / 100 if p.endswith("%") else float(p)
        a = num(parts[3], 1) if len(parts) == 4 else 1.0
        if m[1].lower().startswith("rgb"):
            r, g, b = (num(p, 255) for p in parts[:3])
        else:
            hue = float(re.sub(r"deg$", "", parts[0])) % 360
            sat, light = num(parts[1], 1), num(parts[2], 1)
            r, g, b = _hsl_to_rgb(hue, sat, light)
    except ValueError:
        return None
    if not all(0 <= v <= 255 for v in (r, g, b)) or not 0 <= a <= 1:
        return None
    return round(r), round(g), round(b), round(a, 3)


def _hsl_to_rgb(h, s, l):
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return (r + m) * 255, (g + m) * 255, (b + m) * 255


def hex_of(r, g, b, a=1.0):
    return f"#{r:02x}{g:02x}{b:02x}" + (f"{round(a * 255):02x}" if a < 1 else "")


def as_colour(s):
    rgba = parse_colour(s)
    if not rgba:
        return None
    r, g, b, a = rgba
    hexa = hex_of(r, g, b, a)
    rgb = f"rgb({r} {g} {b}" + (f" / {a:g})" if a < 1 else ")")
    other = ("copy", f"Copy as {rgb}", rgb) if s.startswith("#") else ("copy", f"Copy as {hexa}", hexa)
    return Found("colour", "Colour", f"{hexa}  ·  {rgb}", [other, ("pick", "Adjust in a picker", hexa)],
                 swatch=hexa[:7])


# parcel numbers: each with its own check, so a random number is not taken for one
def ups_ok(s):
    """1Z + 15 characters + a check digit (letters count as (ord-63) % 10)."""
    if not re.fullmatch(r"1Z[0-9A-Z]{16}", s):
        return False
    vals = [int(c) if c.isdigit() else (ord(c) - 63) % 10 for c in s[2:17]]
    total = sum(v * (2 if i % 2 else 1) for i, v in enumerate(vals))
    return (10 - total % 10) % 10 == int(s[17]) if s[17].isdigit() else False


def s10_ok(s):
    """The postal union's S10 (RR123456789MX): weights 8 6 4 2 3 5 9 7, mod 11."""
    m = re.fullmatch(r"[A-Z]{2}(\d{8})(\d)[A-Z]{2}", s)
    if not m:
        return False
    total = sum(int(d) * w for d, w in zip(m[1], (8, 6, 4, 2, 3, 5, 9, 7)))
    check = 11 - total % 11
    check = 5 if check == 11 else 0 if check == 10 else check
    return check == int(m[2])


def usps_ok(s):
    """IMpb: 20 or 22 digits starting 9[2-5], mod 10 with weights 3/1 from the right."""
    if not re.fullmatch(r"9[2-5]\d{18}(\d{2})?", s):
        return False
    body = s[:-1][::-1]
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == int(s[-1])


def fedex_ok(s):
    """FedEx Express 12 digits: weights 1 7 3 from the right, mod 11 mod 10."""
    if not re.fullmatch(r"\d{12}", s):
        return False
    body = s[:11][::-1]
    total = sum(int(d) * (1, 7, 3)[i % 3] for i, d in enumerate(body))
    return total % 11 % 10 == int(s[11])


TRACK_PAGES = {
    "UPS": "https://www.ups.com/track?tracknum={n}",
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={n}",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={n}",
    "DHL": "https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id={n}",
    "17TRACK": "https://t.17track.net/en#nums={n}",
}


def carrier_of(s):
    n = re.sub(r"\s", "", s).upper()
    if ups_ok(n):
        return "UPS", n
    if s10_ok(n):
        return ("USPS" if n.endswith("US") else "Postal (" + n[-2:] + ")"), n
    if usps_ok(n):
        return "USPS", n
    if re.fullmatch(r"JJD\d{18}|JD\d{18}", n):
        return "DHL", n
    if fedex_ok(n):
        return "FedEx", n
    return None, n


def as_tracking(s):
    carrier, n = carrier_of(s)
    if not carrier:
        return None
    actions = []
    if carrier in TRACK_PAGES:
        actions.append(("open", f"Track on {carrier}", TRACK_PAGES[carrier].format(n=n)))
    actions.append(("open", "Track on 17TRACK", TRACK_PAGES["17TRACK"].format(n=n)))
    return Found("tracking", f"{carrier.split(' ')[0]} tracking number", n, actions)


def as_path(s):
    if "\n" in s or len(s) > 4096:
        return None
    raw = s.strip("'\"")
    if raw.startswith("file://"):
        raw = urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
    if not re.match(r"(~|/|\.{1,2}/)", raw):
        return None
    path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.exists(path) or secret_path(path):
        return None
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    actions = [("open", "Open", path)]
    if not os.path.isdir(path):
        actions.append(("open", "Show the folder", folder))
    return Found("path", "Folder" if os.path.isdir(path) else "File", short(path), actions)


def as_error(s):
    lines = [l for l in s.splitlines() if l.strip()]
    hits = [l for l in lines if ERROR_LINES.search(l)]
    if not hits:
        return None
    strong = "Traceback" in s or len(hits) >= 2 or len(lines) <= 3
    if not strong:
        return None
    summary = next((l.strip() for l in reversed(lines) if re.search(r"(Error|Exception|error)\b", l)),
                   hits[-1].strip())
    return Found("error", "Error copied", short(summary, 110),
                 [("ask", "Ask the local model", ""), ("search", "Search the web", summary[:200])])


# dates
def _time_of(hour, minute, ampm):
    h, m = int(hour), int(minute or 0)
    ampm = (ampm or "").lower().replace(".", "")
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("time")
    return h, m


def parse_date(s, today=None):
    """(datetime, has_time, the words left over) when the copy is a date
    (and maybe a time) and little else, or None. Day-first for 21/10/2026,
    unless that cannot be a date."""
    today = today or dt.date.today()
    text = " ".join(s.split())
    if len(text) > 80 or "\n" in s.strip():
        return None
    pats = [
        (rf"(\d{{4}})-(\d{{1,2}})-(\d{{1,2}})(?:[T ]{TIME_RE})?", "ymd"),
        (rf"(\d{{1,2}})[/.](\d{{1,2}})[/.](\d{{2,4}})(?:,?\s+{TIME_RE})?", "dmy"),
        (rf"(\d{{1,2}})(?:\s+de)?\s+({MONTH_RE})\.?(?:,?\s+(?:de\s+)?(\d{{4}}))?(?:,?\s+{TIME_RE})?", "d_mon"),
        (rf"({MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?:,?\s+{TIME_RE})?", "mon_d"),
    ]
    for pat, shape in pats:
        m = re.search(rf"(?<![\w/.-]){pat}(?![\w/-])", text, re.I)
        if not m:
            continue
        g = m.groups()
        try:
            if shape == "ymd":
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
                tm = g[3:6]
            elif shape == "dmy":
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                y += 2000 if y < 100 else 0
                d, mo = (a, b) if a > 12 or b <= 12 else (b, a)
                tm = g[3:6]
            elif shape == "d_mon":
                d, mo = int(g[0]), MONTHS[g[1].lower()]
                y = int(g[2]) if g[2] else today.year
                tm = g[3:6]
            else:
                mo, d = MONTHS[g[0].lower()], int(g[1])
                y = int(g[2]) if g[2] else today.year
                tm = g[3:6]
            if tm[0] is not None and (tm[1] or tm[2]):
                h, mi = _time_of(*tm)
                has_time = True
            else:
                h = mi = 0
                has_time = False
                if tm[0] is not None:       # a bare number after the date: not a time
                    raise ValueError("bare")
            when = dt.datetime(y, mo, d, h, mi)
        except (ValueError, KeyError):
            continue
        rest = (text[:m.start()] + " " + text[m.end():]).strip(" ,.-–:;")
        if len(rest.split()) > 8:
            return None
        return when, has_time, " ".join(rest.split())
    return None


def as_date(s):
    got = parse_date(s)
    if not got:
        return None
    when, has_time, rest = got
    shown = f"{when:%a %d %b %Y, %H:%M}" if has_time else f"{when:%a %d %b %Y}"
    iso = when.isoformat(timespec="minutes") if has_time else when.date().isoformat()
    payload = json.dumps({"title": rest or "Reminder", "start": iso, "all_day": not has_time})
    return Found("date", "Date", shown + (f"  ·  {rest}" if rest else ""),
                 [("calendar", "Add to calendar", payload), ("copy", f"Copy as {iso}", iso)])


# sums: a small safe evaluator (ast), never eval()
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise ValueError("too big")
        return OPS[type(node.op)](left, right)
    raise ValueError("not a sum")


def compute(s):
    """The value of a plain sum ("12*(3+4)/2", "2^10", "1,250 × 3"), or None."""
    text = s.strip().rstrip("=").strip()
    if len(text) > 200 or not re.fullmatch(r"[\d\s.,+\-*/×÷x^%()]+", text):
        return None
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)        # thousands: 1,250
    text = text.replace("×", "*").replace("÷", "/").replace("^", "**")
    text = re.sub(r"(?<=[\d)\s])x(?=[\d(\s])", "*", text)
    if "," in text or not re.search(r"\d\s*(\*\*|[-+*/%])\s*[\d(.-]", text):
        return None
    if re.fullmatch(r"\d+\s*-\s*\d+", text):     # 555-1234, 10-20: a number or a range
        return None
    try:
        value = _eval(ast.parse(text, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError):
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        value = round(value, 10)
        if value.is_integer():
            value = int(value)
    return value


def as_math(s):
    value = compute(s)
    if value is None:
        return None
    shown = f"{value:,}" if isinstance(value, int) else f"{value:,.10g}"
    return Found("math", f"= {shown}", short(s.strip(), 80), [("copy", "Copy the result", str(value))])


PHONE_RE = re.compile(r"(tel:)?\+?[\d\s().-]{7,22}$")


def as_phone(s):
    if not PHONE_RE.fullmatch(s):
        return None
    digits = re.sub(r"\D", "", s)
    if not 7 <= len(digits) <= 15 or len(set(digits)) < 3:
        return None
    formatted = bool(re.search(r"\(\d{1,4}\)\s?\d|\d[\s.-]\d{2,4}[\s.-]\d{2,4}|^\d{3}[\s.-]\d{4}$", s))
    if not (s.lstrip("tel:").startswith("+") or formatted or len(digits) == 10):
        return None
    plain = ("+" if s.lstrip("tel:").startswith("+") else "") + digits
    actions = []
    if plain != s:
        actions.append(("copy", f"Copy as {plain}", plain))
    if _have("kdeconnect-cli"):
        actions.append(("phone", "Send to my phone", plain))
    actions.append(("search", "Look it up", plain))
    return Found("phone", "Phone number", s.strip(), actions)


def as_address(s):
    lines = [l.strip() for l in s.strip().splitlines() if l.strip()]
    flat = ", ".join(lines)
    if not 1 <= len(lines) <= 6 or len(flat) > 200 or "://" in flat or "@" in flat:
        return None
    if not (re.search(r"\d", flat) and STREET.search(flat)):
        return None
    if len(re.findall(r"[A-Za-zÀ-ÿ]{2,}", flat)) < 2:
        return None
    actions = [("open", "Open the map", "https://www.openstreetmap.org/search?query="
                + urllib.parse.quote(flat))]
    if _have("kdeconnect-cli"):
        actions.append(("phone", "Send to my phone", flat))
    return Found("address", "Address", short(flat, 110), actions)


def as_json(s):
    if not (s[:1] in "{[" and s[-1:] in "}]") or len(s) < 7:
        return None
    try:
        data = json.loads(s)
    except ValueError:
        return None
    if not data:
        return None
    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    compact = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    what = f"{len(data)} {'keys' if isinstance(data, dict) else 'items'}"
    actions = []
    if s != pretty:
        actions.append(("copy", "Copy pretty-printed", pretty))
    if s != compact:
        actions.append(("copy", "Copy on one line", compact))
    return Found("json", "JSON", what, actions) if actions else None


ORDER = (("json", as_json), ("error", as_error), ("url", as_url), ("email", as_email),
         ("colour", as_colour), ("tracking", as_tracking), ("path", as_path), ("date", as_date),
         ("phone", as_phone), ("math", as_math), ("address", as_address))
LONG_KINDS = ("json", "error", "address")


def detect(text):
    """The Found for a copy, or None (nothing recognised, or a secret)."""
    s = text.strip()
    if not s or looks_secret(s):
        return None
    for kind, rule in ORDER:
        if kind not in LONG_KINDS and (len(s) > MAX_SHORT or "\n" in s and kind not in ("date",)):
            continue
        found = rule(s)
        if found:
            return found
    return None


def _have(cmd):
    return any(os.access(os.path.join(d, cmd), os.X_OK) for d in os.environ.get("PATH", "").split(":") if d)


# -- settings ---------------------------------------------------------------------------------
def kinds_on(conf=None):
    conf = privacy_settings.load() if conf is None else conf
    return {k: privacy_settings.flag(conf.get(f"smartclip_{k}", "on" if KINDS[k][1] else "off")) for k in KINDS}


def service_state():
    """(enabled at login, running now) of the unit."""
    def ask(verb):
        try:
            return subprocess.run(["systemctl", "--user", verb, UNIT], capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return ask("is-enabled") == "enabled", ask("is-active") == "active"


def get_settings():
    enabled, active = service_state()
    on = kinds_on()
    return {"on": active, "enabled": enabled,
            "kinds": [{"kind": k, "label": label, "default": default, "example": example, "on": on[k]}
                      for k, (label, default, example) in KINDS.items()]}


def set_setting(args):
    if len(args) == 1 and args[0] in ("on", "off"):
        verb = ["enable", "--now"] if args[0] == "on" else ["disable", "--now"]
        out = subprocess.run(["systemctl", "--user", *verb, UNIT], capture_output=True, text=True, timeout=20)
        if out.returncode:
            sys.exit(f"smart-clipboard: systemctl failed: {out.stderr.strip()}")
    elif len(args) == 2 and args[0] in KINDS and args[1] in ("on", "off"):
        privacy_settings.set_key(f"smartclip_{args[0]}", args[1])
    else:
        sys.exit("smart-clipboard: set on|off, or set KIND on|off (" + ", ".join(KINDS) + ")")


# -- the quiet rules ----------------------------------------------------------------------------
def digest(text):
    return hashlib.sha256(text.strip().encode()).hexdigest()[:20]


def read_state(path=STATE):
    try:
        with open(path) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(state, path=STATE):
    tmp = f"{path}.{os.getpid()}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def rate_ok(state, key, now):
    """May a card be shown for the copy `key` now? Updates `state` if so.
    Our own copies ("own") never are."""
    seen = state.setdefault("seen", {})
    if key in state.get("own", []):
        return False
    if now - state.get("last", 0) < MIN_GAP_S:
        return False
    if now - seen.get(key, -REPEAT_S) < REPEAT_S:
        return False
    seen[key] = now
    if len(seen) > SEEN_KEEP:
        for old in sorted(seen, key=seen.get)[:len(seen) - SEEN_KEEP]:
            del seen[old]
    state["last"] = now
    return True


def remember_own(text, path=STATE):
    """A copy this script makes itself: the hook it triggers stays quiet."""
    state = read_state(path)
    own = state.get("own", [])[-9:]
    own.append(digest(text))
    state["own"] = own
    write_state(state, path)


# -- the hook ----------------------------------------------------------------------------------------
def hyprctl_json(*args):
    """`hyprctl ARGS -j`, parsed; None when Hyprland does not answer. Over the
    request socket (desk_common.hypr_request): no process."""
    return desk_common.hypr_request(args, json=True, timeout=2)


def private_focus(window=None, conf=None):
    """Was the copy made in a password manager, a private window or an app
    on the Privacy page's private list?"""
    window = hyprctl_json("activewindow") if window is None else window
    if not isinstance(window, dict):
        return False
    cls, title = window.get("class") or "", window.get("title") or ""
    if SECRET_APPS.search(cls):
        return True
    try:
        activity = _module("activity_log", "activity-log.py")
        conf = privacy_settings.load() if conf is None else conf
        return activity.is_private(cls, title, privacy_settings.excluded(conf))
    except Exception:       # noqa: BLE001 -- unsure: treat as private
        return True


def _watcher_age():
    """Seconds since the parent (wl-paste) started; large when unknown."""
    try:
        with open(f"/proc/{os.getppid()}/stat") as handle:
            start = int(handle.read().rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as handle:
            return float(handle.read().split()[0]) - start
    except (OSError, ValueError, IndexError):
        return 1e9


def quiet_now():
    """Do Not Disturb (mako's mode) or gamemode: no card."""
    try:
        modes = subprocess.run(["makoctl", "mode"], capture_output=True, text=True, timeout=2).stdout.split()
        if "do-not-disturb" in modes:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    answer = hyprctl_json("getoption", "animations:enabled")
    return isinstance(answer, dict) and (answer.get("bool") is False or answer.get("int") == 0)


def hook(stdin=None, env=None):
    """One copy. Returns the Found shown (or None) -- the toast itself runs
    as its own process, detached, so wl-paste is never held up."""
    env = os.environ if env is None else env
    if env.get("CLIPBOARD_STATE", "data") != "data":
        return None             # sensitive, cleared, or nothing
    if _watcher_age() < STARTUP_S:
        return None             # wl-paste --watch hands over what was there already: not a copy
    raw = (stdin or sys.stdin.buffer).read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES or b"\0" in raw[:4096]:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    conf = privacy_settings.load()
    found = detect(text)
    if not found or not kinds_on(conf)[found.kind]:
        return None
    if private_focus(conf=conf):
        return None
    state = read_state()
    if not rate_ok(state, digest(text), time.time()):
        return None
    if quiet_now():
        return None
    write_state(state)
    payload = found.as_dict() | {"text": text}
    if to_strip(payload):
        return found            # Live suggestions shows it in its strip: no card of ours
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "toast"], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    proc.stdin.write(json.dumps(payload).encode())      # stdin, not argv: argv is world-readable
    proc.stdin.close()
    return found


def to_strip(payload, path=None):
    """Hand the card to Live suggestions (suggest.py) when it runs with its
    "clipboard" kind on: True when it took it. Its socket is the user's own
    (0600, in the runtime dir); any trouble and our own card shows as before."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(path or STRIP_SOCK)
            sock.sendall(json.dumps({"op": "clipboard", "card": payload}).encode() + b"\n")
            reply = b""
            while not reply.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                reply += chunk
        return json.loads(reply or b"{}").get("taken") is True
    except (OSError, ValueError, AttributeError):
        return False


# -- doing it -------------------------------------------------------------------------------------
def copy(text):
    remember_own(text)
    subprocess.run(["wl-copy"], input=text.encode(), timeout=5)


def spawn(*argv, stdin_text=None):
    proc = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.PIPE if stdin_text else None,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if stdin_text:
        proc.stdin.write(stdin_text.encode())
        proc.stdin.close()


def search_url(text):
    try:
        return _module("capture_settings", "capture-settings.py").search_url(text)
    except Exception:       # noqa: BLE001
        return "https://duckduckgo.com/?q=" + urllib.parse.quote(text)


def run_action(action, arg, text):
    """Do what a card's button says. Returns a line to show, or "" to close."""
    if action == "open":
        spawn("xdg-open", arg)
    elif action == "copy":
        copy(arg)
        return "Copied."
    elif action == "search":
        spawn("xdg-open", search_url(arg))
    elif action == "ask":
        spawn(sys.executable, SCREEN_ASK, "text", "--ask",
              "What does this error mean, and how do I fix it? Be brief.", stdin_text=text)
    elif action == "phone":
        copy(arg)               # phone.py clip sends what is on the clipboard
        spawn(sys.executable, PHONE, "clip")
        return "Sent to the phone."
    elif action == "calendar":
        ev = json.loads(arg)
        start = dt.datetime.fromisoformat(ev["start"])
        end = start + (dt.timedelta(days=1) if ev["all_day"] else dt.timedelta(hours=1))
        try:
            line = _module("screen_actions", "screen-actions.py").add_event(
                {"title": ev["title"], "start": start, "end": end, "all_day": ev["all_day"]})
        except Exception as exc:    # noqa: BLE001 -- shown on the card
            return f"Could not add it: {exc.__class__.__name__}"
        return f"Event {line}."
    return ""


# -- the card -------------------------------------------------------------------------------------
def toast():
    data = json.loads(sys.stdin.read() or "{}")
    if not data:
        return
    _replace_running()
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    import panelui
    panelui.load_css()

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
    for edge, margin in ((GtkLayerShell.Edge.TOP, 44), (GtkLayerShell.Edge.RIGHT, 14)):
        GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_margin(win, edge, margin)
    mon = _focused_monitor(Gdk)
    if mon:
        GtkLayerShell.set_monitor(win, mon)

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    card.set_name("panel")
    card.set_size_request(340, -1)
    win.add(card)
    top = Gtk.Box(spacing=8)
    if data.get("swatch"):
        sw = Gtk.DrawingArea()
        sw.set_size_request(22, 22)
        rgba = Gdk.RGBA()
        rgba.parse(data["swatch"])

        def draw(_w, cr):
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1)
            cr.rectangle(0, 0, 22, 22)
            cr.fill()
        sw.connect("draw", draw)
        top.pack_start(sw, False, False, 0)
    head = Gtk.Label(label=data.get("title") or "", xalign=0)
    head.get_style_context().add_class("kb-heading")
    top.pack_start(head, True, True, 0)
    close = Gtk.Button(label="✕")
    close.get_style_context().add_class("ctl-link")
    close.connect("clicked", lambda _b: Gtk.main_quit())
    top.pack_end(close, False, False, 0)
    card.pack_start(top, False, False, 0)
    body = Gtk.Label(label=data.get("body") or "", xalign=0)
    body.get_style_context().add_class("ctl-sub")
    body.set_line_wrap(True)
    body.set_max_width_chars(44)
    card.pack_start(body, False, False, 0)
    row = Gtk.Box(spacing=6)
    card.pack_start(row, False, False, 0)

    timer = {"id": None}

    def arm(seconds=TOAST_S):
        if timer["id"]:
            GLib.source_remove(timer["id"])
        timer["id"] = GLib.timeout_add_seconds(seconds, lambda: (Gtk.main_quit(), False)[1])

    def clicked(action, arg):
        if action == "pick":
            win.hide()
            picked = _pick_colour(Gtk, Gdk, arg)
            if picked:
                copy(picked)
            Gtk.main_quit()
            return
        line = run_action(action, arg, data.get("text") or "")
        if line:
            body.set_text(line)
            for child in row.get_children():
                row.remove(child)
            arm(2)
        else:
            Gtk.main_quit()

    for action, label, arg in data.get("actions") or []:
        b = Gtk.Button(label=label)
        b.get_style_context().add_class("dev-pick")
        b.connect("clicked", lambda _b, a=action, g=arg: clicked(a, g))
        row.pack_start(b, False, False, 0)
    def hold(*_a):              # the pointer is on the card: it stays
        if timer["id"]:
            GLib.source_remove(timer["id"])
            timer["id"] = None
        return False

    def leave(_w, event):       # (onto a button inside it is not leaving)
        if event.detail != Gdk.NotifyType.INFERIOR:
            arm(4)
        return False

    win.connect("enter-notify-event", hold)
    win.connect("leave-notify-event", leave)
    win.connect("delete-event", Gtk.main_quit)
    signal.signal(signal.SIGTERM, lambda *_a: GLib.idle_add(Gtk.main_quit))
    win.show_all()
    arm()
    try:
        Gtk.main()
    finally:
        try:
            if _read_pid() == os.getpid():
                os.unlink(PID_FILE)
        except OSError:
            pass


def _read_pid():
    try:
        with open(PID_FILE) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def _replace_running():
    """One card at a time: the one up goes when the next comes."""
    pid = _read_pid()
    if pid and pid != os.getpid():
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                if b"smart-clipboard" in handle.read():
                    os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    with open(PID_FILE, "w") as handle:
        handle.write(str(os.getpid()))


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


def _pick_colour(Gtk, Gdk, start):
    """GTK's colour chooser opened on the copied colour; the hex picked, or None."""
    dialog = Gtk.ColorChooserDialog(title="Adjust the colour")
    dialog.set_use_alpha(False)
    rgba = Gdk.RGBA()
    if rgba.parse(start[:7]):
        dialog.set_rgba(rgba)
    dialog.set_property("show-editor", True)
    answer = dialog.run()
    picked = dialog.get_rgba()
    dialog.destroy()
    if answer != Gtk.ResponseType.OK:
        return None
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (picked.red, picked.green, picked.blue)))


# -- the command line -------------------------------------------------------------------------------
def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "hook":
        hook()
    elif cmd == "toast":
        toast()
    elif cmd == "detect":
        text = " ".join(args) if args else sys.stdin.read()
        if looks_secret(text.strip()):
            print(json.dumps({"secret": True}))
        else:
            found = detect(text)
            print(json.dumps(found.as_dict() if found else None, ensure_ascii=False))
    elif cmd == "get":
        data = get_settings()
        if "--json" in args:
            print(json.dumps(data))
        else:
            print(f"smart clipboard: {'on' if data['on'] else 'off'}"
                  f"{'' if data['on'] == data['enabled'] else ' (not as at login)'}")
            for k in data["kinds"]:
                print(f"  {k['kind']:<9} {'on ' if k['on'] else 'off'}  {k['label']}")
    elif cmd == "set":
        set_setting(args)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
