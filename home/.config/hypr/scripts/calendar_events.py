#!/usr/bin/env python3
"""Calendar events for the bar's calendar and clock cards, from local
sources only -- no accounts, nothing signed in to:

    calendar_events.py list [DAYS] [--json]   the events from today on
                                              (default 7 days)
    calendar_events.py upcoming [N] [--json]  the next N (default 3) still to
                                              come, one line each
    calendar_events.py day YYYY-MM-DD         that day's events
    calendar_events.py sources [--json]       where events come from, and
                                              whether each one answers
    calendar_events.py refresh                fetch the subscribed URLs now
    calendar_events.py remind                 arm a reminder for each ICS /
                                              khal event starting soon (run
                                              every 5 min, see below)

Where the events come from:

  ~/.config/hypr/calendars.conf   one source a line, # comments:
        ~/Calendars/work.ics                  a file
        ~/Calendars/                          every *.ics in a folder
        https://example.org/holidays.ics      a subscription (webcal://
                                              is read as https://)
        eds=off                               not Evolution's calendars
        khal=off                              not khal's
    A subscription is fetched with a 10-s timeout and cached in
    $XDG_CACHE_HOME/hypr/calendars/, then fetched again when the copy is
    older than 15 minutes (by `remind`, every 5 min, and by the calendar
    card while it is open). A fetch that fails keeps the old copy.
    $HYPR_CALENDARS_CONF points the file elsewhere (the tests).

  Evolution (evolution-data-server), when its GObject bindings are there:
    the enabled calendars GNOME Calendar and timers.py read -- their
    events are handed to the same parser as the files.

  khal, when ~/.config/khal/config exists: its calendars are vdir folders
    of .ics files (path = ...), read straight from disk, no khal run.

The parser is this file's own (no icalendar module): VEVENT with SUMMARY,
LOCATION, DTSTART / DTEND / DURATION -- in UTC (...Z), with a TZID, floating
or all-day (VALUE=DATE) -- RRULE with FREQ DAILY / WEEKLY / MONTHLY /
YEARLY, INTERVAL, COUNT, UNTIL, BYDAY (MO,WE / 2MO / -1FR), BYMONTHDAY and
BYMONTH; EXDATE; a RECURRENCE-ID moving or changing one occurrence; STATUS:
CANCELLED left out. What it does not know (BYSETPOS, BYWEEKNO, hourly
rules) is read as the plain rule, and every rule stops after a few
thousand steps.

Reminders: timers.py already arms an alarm cal_lead_min (Settings > Timers
& alarms, default 10 min) before each event in Evolution's calendars, every
5 min from timers-calendar.timer. `remind` does the same for the ICS files,
the subscriptions and khal -- the same alarm (timers.py schedule
"calendar"), the same lead time, the same on / off switch ("Calendar
alarms") -- run by a drop-in of timers-calendar.service, so no daemon of its
own. Each event rings once ($XDG_STATE_HOME/hypr/calendar-events.json keeps
which).
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

try:
    from zoneinfo import ZoneInfo, available_timezones
except ImportError:         # Python without zoneinfo: TZIDs read as local time
    ZoneInfo = None

    def available_timezones():
        return set()

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONF = os.environ.get("HYPR_CALENDARS_CONF") or os.path.join(CONFIG_HOME, "hypr", "calendars.conf")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "hypr", "calendars")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "calendar-events.json")
KHAL_CONF = os.path.join(CONFIG_HOME, "khal", "config")
FETCH_TIMEOUT_S = 10
REFRESH_S = 15 * 60         # a subscription is fetched again when older than this
AHEAD_MIN = 30              # remind looks this far ahead (more with a longer lead)
MAX_STEPS = 5000            # the most periods one RRULE is walked
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
UNTITLED = "(no title)"


# -- reading the text -------------------------------------------------------------------
def unfold(text):
    """iCalendar lines: CRLF or LF, a line starting with a space or a tab
    continues the one before (RFC 5545 3.1)."""
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        elif line:
            out.append(line)
    return out


def parse_line(line):
    """'DTSTART;TZID=Europe/Paris:20261028T090000' -> ("DTSTART",
    {"TZID": "Europe/Paris"}, "20261028T090000"). A colon inside a quoted
    parameter value does not end the name part."""
    quoted, cut = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            cut = i
            break
    if cut < 0:
        return None
    head, value = line[:cut], line[cut + 1:]
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    if not parts:
        return None
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.strip().upper()] = v.strip().strip('"')
    return parts[0].strip().upper(), params, value


def unescape(value):
    """TEXT values: \\n, \\, \\; \\\\ (RFC 5545 3.3.11)."""
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1] in "nN" else m[1], value)


def zone_for(tzid):
    """A ZoneInfo for a TZID, or None (then the time is read as local).
    Evolution writes "/freeassociation.sourceforge.net/Europe/Paris" and
    some exports "Europe/Paris" in quotes: the IANA name is found inside."""
    if not tzid or ZoneInfo is None:
        return None
    tzid = tzid.strip().strip('"')
    if tzid.upper() in ("UTC", "GMT", "Z", "ETC/UTC"):
        return dt.timezone.utc
    parts = [p for p in tzid.split("/") if p]
    for n in range(len(parts)):
        name = "/".join(parts[n:])
        try:
            return ZoneInfo(name)
        except (ValueError, KeyError, OSError):
            continue
    return None


def parse_when(value, params, local=None):
    """A DTSTART-like value -> (datetime or date, all_day). Timed values
    come back aware: UTC for ...Z, the TZID's zone, else `local` (floating
    time; default this computer's zone). None for what is not a date."""
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        try:
            return dt.datetime.strptime(value[:8], "%Y%m%d").date(), True
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{8})T(\d{4})(\d{2})?(Z?)", value)
    if not m:
        return None
    try:
        naive = dt.datetime.strptime(m[1] + m[2] + (m[3] or "00"), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if m[4]:
        return naive.replace(tzinfo=dt.timezone.utc), False
    zone = zone_for(params.get("TZID")) or local or local_zone()
    return naive.replace(tzinfo=zone), False


def local_zone():
    """This computer's zone, DST rules and all (a ZoneInfo from $TZ or the
    /etc/localtime link), so a floating weekly 09:00 stays 09:00 across a
    clock change; else the fixed offset of right now."""
    name = zone_name(os.environ.get("TZ", ""), _localtime_link())
    if name and ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except (ValueError, KeyError, OSError):
            pass
    return dt.datetime.now().astimezone().tzinfo


def _localtime_link():
    try:
        return os.readlink("/etc/localtime")
    except OSError:
        return ""


def zone_name(tz_env, link):
    """The IANA name from $TZ (":Europe/Paris" or "Europe/Paris") or else
    from the /etc/localtime link target (".../zoneinfo/Europe/Paris"); ""
    when neither names one."""
    tz_env = (tz_env or "").lstrip(":")
    if re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+)+|UTC", tz_env):
        return tz_env
    m = re.search(r"zoneinfo/(.+)$", link or "")
    return m[1] if m else ""


def parse_duration(text):
    """'PT1H30M', 'P1D', '-PT15M', 'P2W' -> timedelta, None if unreadable."""
    m = re.fullmatch(r"([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
                     (text or "").strip().upper())
    if not m or not any(m.groups()[1:]):
        return None
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    delta = dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return -delta if m[1] == "-" else delta


def parse_rrule(text):
    """'FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=10' -> a dict with freq,
    interval, count, until (raw text), byday [(n or None, weekday 0-6)],
    bymonthday [int], bymonth [int]. None when there is no FREQ this
    parser walks."""
    rule = {}
    for part in (text or "").split(";"):
        k, _, v = part.partition("=")
        rule[k.strip().upper()] = v.strip()
    freq = rule.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return None

    def ints(key):
        out = []
        for x in rule.get(key, "").split(","):
            try:
                out.append(int(x))
            except ValueError:
                pass
        return out
    byday = []
    for x in rule.get("BYDAY", "").split(","):
        m = re.fullmatch(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)", x.strip().upper())
        if m:
            byday.append((int(m[1]) if m[1] else None, WEEKDAYS.index(m[2])))
    try:
        interval = max(1, int(rule.get("INTERVAL") or 1))
    except ValueError:
        interval = 1
    try:
        count = int(rule["COUNT"]) if rule.get("COUNT") else None
    except ValueError:
        count = None
    return {"freq": freq, "interval": interval, "count": count, "until": rule.get("UNTIL") or None,
            "byday": byday, "bymonthday": ints("BYMONTHDAY"), "bymonth": [m for m in ints("BYMONTH") if 1 <= m <= 12]}


def parse_ics(text, local=None):
    """Every VEVENT of a calendar's text -> [event dict]: uid, summary,
    location, start, end (datetime or date), all_day, rrule (parse_rrule
    or None), exdates (set of starts), recurrence_id (start or None),
    status. Components inside a VEVENT (VALARM) are skipped."""
    events, cur, depth = [], None, 0
    for line in unfold(text):
        parsed = parse_line(line)
        if not parsed:
            continue
        name, params, value = parsed
        if name == "BEGIN":
            if value.strip().upper() == "VEVENT" and cur is None:
                cur, depth = {"exdates": set(), "params": {}}, 0
            elif cur is not None:
                depth += 1
            continue
        if name == "END":
            if cur is not None:
                if depth:
                    depth -= 1
                elif value.strip().upper() == "VEVENT":
                    event = finish(cur, local)
                    if event:
                        events.append(event)
                    cur = None
            continue
        if cur is None or depth:
            continue
        if name == "EXDATE":
            for v in value.split(","):
                when = parse_when(v, params, local)
                if when:
                    cur["exdates"].add(when[0])
        elif name in ("UID", "SUMMARY", "LOCATION", "DTSTART", "DTEND", "DURATION", "RRULE",
                      "RECURRENCE-ID", "STATUS"):
            cur[name] = value
            cur["params"][name] = params
    return events


def finish(raw, local=None):
    """A VEVENT's raw properties -> the event dict, or None without a
    usable DTSTART."""
    params = raw["params"]
    start = parse_when(raw.get("DTSTART", ""), params.get("DTSTART", {}), local)
    if not start:
        return None
    start, all_day = start
    end = None
    if raw.get("DTEND"):
        got = parse_when(raw["DTEND"], params.get("DTEND", {}), local)
        if got and got[1] == all_day:
            end = got[0]
    if end is None and raw.get("DURATION"):
        delta = parse_duration(raw["DURATION"])
        if delta is not None:
            end = start + delta
    if end is None or end < start:
        end = start + dt.timedelta(days=1) if all_day else start
    rid = None
    if raw.get("RECURRENCE-ID"):
        got = parse_when(raw["RECURRENCE-ID"], params.get("RECURRENCE-ID", {}), local)
        rid = got[0] if got else None
    return {"uid": raw.get("UID", "").strip(),
            "summary": unescape(raw.get("SUMMARY", "")).strip() or UNTITLED,
            "location": unescape(raw.get("LOCATION", "")).strip(),
            "start": start, "end": end, "all_day": all_day,
            "rrule": parse_rrule(raw.get("RRULE")) if raw.get("RRULE") else None,
            "exdates": raw["exdates"], "recurrence_id": rid,
            "status": raw.get("STATUS", "").strip().upper()}


# -- recurrence --------------------------------------------------------------------------
def nth_weekday(year, month, weekday, n):
    """The n-th (1..5, or -1..-5 from the end) `weekday` of a month, or None."""
    first = dt.date(year, month, 1)
    if n > 0:
        day = first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
        return day if day.month == month else None
    last = dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)
    day = last - dt.timedelta(days=(last.weekday() - weekday) % 7 + 7 * (-n - 1))
    return day if day.month == month else None


def month_days(year, month, rule, base_day):
    """The days of one month a MONTHLY / YEARLY rule falls on, sorted."""
    days = set()
    last = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)).day
    for n in rule["bymonthday"]:
        d = n if n > 0 else last + 1 + n
        if 1 <= d <= last:
            days.add(dt.date(year, month, d))
    for n, wd in rule["byday"]:
        if n:
            d = nth_weekday(year, month, wd, n)
            if d:
                days.add(d)
        else:                      # every such weekday of the month
            d = nth_weekday(year, month, wd, 1)
            while d and d.month == month:
                days.add(d)
                d += dt.timedelta(days=7)
    if not rule["bymonthday"] and not rule["byday"] and base_day <= last:
        days.add(dt.date(year, month, base_day))
    return sorted(days)


def candidate_days(rule, first, skip_to=None):
    """The days a rule may fall on, in order, from DTSTART's day `first`
    (a generator; days before `first` are never given). skip_to: a day
    the caller does not need anything before -- the walk jumps near it
    when the rule has no COUNT (which has to be counted from the start)."""
    step = rule["interval"]
    freq = rule["freq"]
    jump = 0
    if skip_to and rule["count"] is None and skip_to > first:
        if freq == "DAILY":
            jump = max(0, (skip_to - first).days // step - 1)
        elif freq == "WEEKLY":
            jump = max(0, (skip_to - first).days // (7 * step) - 1)
        elif freq == "MONTHLY":
            months = (skip_to.year - first.year) * 12 + skip_to.month - first.month
            jump = max(0, months // step - 1)
        else:
            jump = max(0, (skip_to.year - first.year) // step - 1)
    wanted_wd = {wd for _n, wd in rule["byday"]}
    for k in range(jump, jump + MAX_STEPS):
        if freq == "DAILY":
            day = first + dt.timedelta(days=k * step)
            if (not wanted_wd or day.weekday() in wanted_wd) and \
                    (not rule["bymonth"] or day.month in rule["bymonth"]):
                yield day
        elif freq == "WEEKLY":
            week = first - dt.timedelta(days=first.weekday()) + dt.timedelta(weeks=k * step)
            for wd in sorted(wanted_wd or {first.weekday()}):
                day = week + dt.timedelta(days=wd)
                if day >= first:
                    yield day
        elif freq == "MONTHLY":
            index = first.month - 1 + k * step
            year, month = first.year + index // 12, index % 12 + 1
            if rule["bymonth"] and month not in rule["bymonth"]:
                continue
            for day in month_days(year, month, rule, first.day):
                if day >= first:
                    yield day
        else:
            year = first.year + k * step
            months = rule["bymonth"] or [first.month]
            for month in sorted(months):
                if rule["byday"] or rule["bymonthday"]:
                    days = month_days(year, month, rule, first.day)
                else:
                    days = [dt.date(year, month, first.day)] if _valid(year, month, first.day) else []
                for day in days:
                    if day >= first:
                        yield day


def _valid(year, month, day):
    try:
        dt.date(year, month, day)
        return True
    except ValueError:
        return False


def until_of(rule, start):
    """The rule's UNTIL as something comparable with occurrence starts of
    `start`'s kind (a date, or an aware datetime), or None."""
    if not rule.get("until"):
        return None
    got = parse_when(rule["until"], {}, start.tzinfo if isinstance(start, dt.datetime) else None)
    if not got:
        return None
    until = got[0]
    if isinstance(start, dt.datetime):
        if not isinstance(until, dt.datetime):
            until = dt.datetime.combine(until, dt.time(23, 59, 59), start.tzinfo)
        return until
    return until.date() if isinstance(until, dt.datetime) else until


def starts(event, window_end, window_start=None):
    """The start of each occurrence of an event, in order, up to (not
    including) window_end -- datetimes in the event's own zone (so a weekly
    09:00 stays 09:00 across a DST change) or dates for all-day ones.
    EXDATEs left out; COUNT counts them, as RFC 5545 says."""
    first = event["start"]
    rule = event.get("rrule")
    if not rule:
        return [first] if _before(first, window_end) else []
    all_day = not isinstance(first, dt.datetime)
    tod = None if all_day else first.timetz()
    until = until_of(rule, first)
    skip = None
    if window_start is not None:
        skip = window_start if isinstance(window_start, dt.date) and not isinstance(window_start, dt.datetime) \
            else window_start.date()
        skip -= dt.timedelta(days=2)
    out, n = [], 0
    first_day = first if all_day else first.date()
    for day in candidate_days(rule, first_day, skip):
        when = day if all_day else dt.datetime.combine(day, tod.replace(tzinfo=None), first.tzinfo)
        if not _before(when, window_end):
            break
        if until is not None and when > until:
            break
        n += 1
        if rule["count"] is not None and n > rule["count"]:
            break
        if when not in event["exdates"] and not _excluded(when, event["exdates"]):
            out.append(when)
    return out


def _before(when, end):
    """when < end, a date against a datetime compared on the day."""
    if isinstance(when, dt.datetime) and not isinstance(end, dt.datetime):
        return when.date() < end
    if not isinstance(when, dt.datetime) and isinstance(end, dt.datetime):
        return when < end.date() or (when == end.date() and not _midnight(end))
    return when < end


def _midnight(moment):
    """Is a datetime exactly 00:00:00 on its own clock?"""
    return (moment.hour, moment.minute, moment.second, moment.microsecond) == (0, 0, 0, 0)


def _excluded(when, exdates):
    """An EXDATE given in another zone (or as a date) still drops the
    occurrence at the same instant (or on that day)."""
    for ex in exdates:
        if isinstance(ex, dt.datetime) and isinstance(when, dt.datetime):
            if ex == when:
                return True
        elif not isinstance(ex, dt.datetime) and not isinstance(when, dt.datetime):
            if ex == when:
                return True
        elif not isinstance(ex, dt.datetime) and isinstance(when, dt.datetime):
            if ex == when.date():
                return True
    return False


# -- occurrences in a window -------------------------------------------------------------
def to_local(when, zone):
    """An occurrence start/end as shown: timed ones in `zone`, dates as they are."""
    return when.astimezone(zone) if isinstance(when, dt.datetime) else when


def occurrences(events, start, end, zone=None):
    """Every occurrence overlapping [start, end) -- aware datetimes in
    `zone` (default this computer's) -- sorted, all-day ones first on
    their day. Each: {summary, location, start, end, all_day, uid, source}.
    A RECURRENCE-ID event replaces the occurrence it names."""
    zone = zone or local_zone()
    overrides = {}
    for e in events:
        if e.get("recurrence_id") is not None and e.get("uid"):
            overrides.setdefault(e["uid"], {})[e["recurrence_id"]] = e
    out = []
    for e in events:
        if e.get("recurrence_id") is not None:
            continue                  # placed through its master below (or alone)
        if e.get("status") == "CANCELLED":
            continue
        moved = overrides.get(e.get("uid"), {})
        length = e["end"] - e["start"]
        for s in starts(e, end + dt.timedelta(days=1), start - _slack(e)):
            if s in moved:
                continue              # the override is placed below
            out.append(_occ(e, s, s + length, zone))
    for uid, by_rid in overrides.items():
        for e in by_rid.values():
            if e.get("status") != "CANCELLED":
                out.append(_occ(e, e["start"], e["end"], zone))
    lo, hi = start.astimezone(zone), end.astimezone(zone)
    kept = [o for o in out if _overlaps(o, lo, hi)]
    kept.sort(key=lambda o: (_sort_day(o), not o["all_day"], _sort_time(o), o["summary"].lower()))
    return kept


def _slack(e):
    """How far before the window an occurrence may start and still reach
    into it (its own length), plus a day for zones."""
    return (e["end"] - e["start"]) + dt.timedelta(days=1)


def _occ(e, s, end, zone):
    return {"summary": e["summary"], "location": e.get("location", ""), "start": to_local(s, zone),
            "end": to_local(end, zone), "all_day": e["all_day"], "uid": e.get("uid", ""),
            "source": e.get("source", "")}


def _overlaps(o, lo, hi):
    if o["all_day"]:
        return o["start"] < hi.date() + dt.timedelta(days=0 if _midnight(hi) else 1) \
            and o["end"] > lo.date()
    if o["end"] == o["start"]:
        return lo <= o["start"] < hi
    return o["start"] < hi and o["end"] > lo


def _sort_day(o):
    return o["start"] if o["all_day"] else o["start"].date()


def _sort_time(o):
    return dt.time(0) if o["all_day"] else o["start"].timetz().replace(tzinfo=None)


def days_with_events(occs):
    """The set of dates any occurrence covers: an all-day event its days
    (end exclusive), a timed one each day from its start to its end (an
    end at midnight does not count that day)."""
    out = set()
    for o in occs:
        if o["all_day"]:
            d, last = o["start"], max(o["start"], o["end"] - dt.timedelta(days=1))
        else:
            d = o["start"].date()
            end = o["end"]
            last = end.date() if not _midnight(end) or end.date() == d \
                else end.date() - dt.timedelta(days=1)
        for _ in range(400):
            if d > last:
                break
            out.add(d)
            d += dt.timedelta(days=1)
    return out


def on_day(occs, day):
    """The occurrences that touch `day` (multi-day ones on each of theirs)."""
    return [o for o in occs if day in days_with_events([o])]


def upcoming(occs, now, n=3):
    """The next n occurrences not over yet at `now` (timed: still to start
    or running; all-day: today or later), in order."""
    out = []
    for o in occs:
        if o["all_day"]:
            if o["end"] > now.date():
                out.append(o)
        elif o["end"] > now or o["start"] >= now:
            out.append(o)
    out.sort(key=lambda o: (o["start"] if not o["all_day"]
                            else dt.datetime.combine(o["start"], dt.time(0), now.tzinfo)))
    return out[:n]


def time_text(o, day=None, twelve=False):
    """'All day', '09:30–10:00', 'from 22:00' / 'until 01:00' for a
    multi-day timed one seen from `day`."""
    if o["all_day"]:
        return "All day"

    def hm(t):
        return t.strftime("%I:%M %p").lstrip("0") if twelve else t.strftime("%H:%M")
    s, e = o["start"], o["end"]
    if day is not None and s.date() < day:
        return f"until {hm(e)}" if e.date() == day else "All day"
    if day is not None and e.date() > day and not (e.date() == day + dt.timedelta(days=1) and _midnight(e)):
        return f"from {hm(s)}"
    return hm(s) if e == s else f"{hm(s)}–{hm(e)}"


def when_text(o, now, twelve=False):
    """For the upcoming list: 'today 14:00', 'tomorrow, all day',
    'Fri 31 Oct 09:00', 'now (until 15:00)'."""
    d = o["start"] if o["all_day"] else o["start"].date()
    today = now.date()
    if not o["all_day"] and o["start"] <= now < o["end"]:
        return f"now (until {time_text(dict(o, start=o['end']), twelve=twelve)})"
    word = "today" if d == today else "tomorrow" if d == today + dt.timedelta(days=1) \
        else d.strftime("%a %d %b")
    if o["all_day"]:
        return f"{word}, all day"
    return f"{word} {time_text(dict(o, end=o['start']), twelve=twelve)}"


# -- the sources -------------------------------------------------------------------------
def read_conf(path=None):
    """calendars.conf -> (sources [str], options {key: value}). Lines with
    key=value where key is a word and the line is no URL are options."""
    sources, options = [], {}
    try:
        with open(path or CONF) as handle:
            lines = handle.read().splitlines()
    except OSError:
        return sources, options
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z_]+)\s*=\s*(\S*)", line)
        if m and "://" not in line:
            options[m[1].lower()] = m[2].lower()
            continue
        sources.append(line)
    return sources, options


def is_url(source):
    return bool(re.match(r"(https?|webcal)://", source, re.I))


def source_label(source):
    """A source as it may be shown on screen: a subscription's host only
    ("https://calendar.example.org/…"), since a private calendar's URL
    often carries its secret token in the path or the query; anything else
    as it is."""
    m = re.match(r"((?:https?|webcal)://)(?:[^/?#@]*@)?([^/?#]*)(.*)$", source or "", re.I)
    if not m:
        return source or ""
    # user:password@ is dropped with the path
    return m[1] + m[2] + ("/\u2026" if m[3] else "")


def fetch_url(source):
    """webcal:// is https://."""
    return re.sub(r"^webcal://", "https://", source, flags=re.I)


def cache_path(source):
    return os.path.join(CACHE_DIR, hashlib.sha1(source.encode()).hexdigest()[:16] + ".ics")


def stale(path, now=None, max_age=REFRESH_S):
    try:
        return (now or time.time()) - os.stat(path).st_mtime > max_age
    except OSError:
        return True


def fetch(source, timeout=FETCH_TIMEOUT_S, opener=None):
    """Fetch one subscription into its cache file; "" on success, else why
    (the old copy is kept)."""
    opener = opener or urllib.request.urlopen
    try:
        req = urllib.request.Request(fetch_url(source), headers={"User-Agent": "calendar_events.py"})
        with opener(req, timeout=timeout) as resp:
            data = resp.read(8 * 1024 * 1024)
    except Exception as exc:      # noqa: BLE001  (offline, DNS, HTTP error, timeout)
        return str(exc) or exc.__class__.__name__
    if b"BEGIN:VCALENDAR" not in data[:4096].upper():
        return "not a calendar (no BEGIN:VCALENDAR)"
    path = cache_path(source)
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)
    return ""


def refresh(sources=None, force=False):
    """Fetch the subscriptions whose copy is stale (all with force).
    {source: "" or why} for the ones tried."""
    if sources is None:
        sources = read_conf()[0]
    out = {}
    for s in sources:
        if is_url(s) and (force or stale(cache_path(s))):
            out[s] = fetch(s)
    return out


def files_of(source):
    """The .ics files a file / folder source names."""
    path = os.path.expanduser(source)
    if os.path.isdir(path):
        try:
            return sorted(os.path.join(path, n) for n in os.listdir(path) if n.lower().endswith(".ics"))
        except OSError:
            return []
    return [path] if os.path.isfile(path) else []


def khal_paths(path=KHAL_CONF):
    """The vdir folders in khal's config (path = ... under [calendars]);
    globs like ~/.calendars/* expanded."""
    import glob
    try:
        with open(path) as handle:
            text = handle.read()
    except OSError:
        return []
    out = []
    for m in re.finditer(r"^\s*path\s*=\s*(.+?)\s*$", text, re.M):
        for p in sorted(glob.glob(os.path.expanduser(m[1]))) or [os.path.expanduser(m[1])]:
            if os.path.isdir(p):
                out.append(p)
    return out


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def eds_texts():
    """Evolution's enabled calendars as iCalendar texts [(source name,
    text)]; [] without evolution-data-server's bindings or when it does
    not answer. Slow on the first call (it may start the calendar
    factory): never on the GTK thread."""
    try:
        import gi
        gi.require_version("ECal", "2.0")
        gi.require_version("EDataServer", "1.2")
        from gi.repository import ECal, EDataServer
    except (ImportError, ValueError):
        return []
    out = []
    try:
        reg = EDataServer.SourceRegistry.new_sync(None)
        for src in reg.list_sources(EDataServer.SOURCE_EXTENSION_CALENDAR):
            if not src.get_enabled():
                continue
            try:
                client = ECal.Client.connect_sync(src, ECal.ClientSourceType.EVENTS, 2, None)
                _ok, objs = client.get_object_list_as_comps_sync("#t", None)
            except Exception:     # noqa: BLE001  (an account that is offline)
                continue
            parts = []
            for obj in objs or []:
                try:
                    parts.append(obj.get_icalcomponent().as_ical_string())
                except Exception:  # noqa: BLE001
                    continue
            if parts:
                out.append((src.get_display_name() or src.get_uid(), "\n".join(parts)))
    except Exception:             # noqa: BLE001  (no D-Bus, no registry)
        return []
    return out


def eds_available():
    try:
        import gi
        gi.require_version("ECal", "2.0")
        gi.require_version("EDataServer", "1.2")
        return True
    except (ImportError, ValueError):
        return False


def load_events(eds=None, conf=None, khal=None):
    """Every event from every source, each tagged with "source". eds:
    True / False, None = calendars.conf's eds= (on unless "off"); the same
    for khal. Subscriptions are read from their cache (refresh() fetches)."""
    sources, options = read_conf(conf)
    if eds is None:
        eds = options.get("eds", "on") != "off"
    if khal is None:
        khal = options.get("khal", "on") != "off"
    events = []

    def add(text, name):
        for e in parse_ics(text):
            e["source"] = name
            events.append(e)
    for s in sources:
        if is_url(s):
            add(read_text(cache_path(s)), s)
        else:
            for f in files_of(s):
                add(read_text(f), s)
    if khal:
        for folder in khal_paths():
            for f in files_of(folder):
                add(read_text(f), "khal")
    if eds:
        for name, text in eds_texts():
            add(text, f"evolution: {name}")
    return events


def sources_status():
    """[{source, kind, ok, note}] for `sources` and Settings."""
    sources, options = read_conf()
    out = []
    for s in sources:
        if is_url(s):
            path = cache_path(s)
            age = None if stale(path, max_age=10 ** 9) else int(time.time() - os.stat(path).st_mtime)
            out.append({"source": s, "kind": "url", "ok": age is not None,
                        "note": "not fetched yet" if age is None else f"fetched {age // 60} min ago"})
        else:
            files = files_of(s)
            out.append({"source": s, "kind": "file", "ok": bool(files),
                        "note": f"{len(files)} file(s)" if files else "not found"})
    if options.get("khal", "on") != "off":
        for p in khal_paths():
            out.append({"source": p, "kind": "khal", "ok": True, "note": f"{len(files_of(p))} file(s)"})
    out.append({"source": "evolution-data-server", "kind": "eds",
                "ok": eds_available() and options.get("eds", "on") != "off",
                "note": "off in calendars.conf" if options.get("eds", "on") == "off"
                else ("" if eds_available() else "not installed (evolution-data-server)")})
    return out


# -- reminders ---------------------------------------------------------------------------
def read_state(path=None):
    try:
        with open(path or STATE) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(data, path=None):
    path = path or STATE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


def event_key(o):
    return f"{o.get('uid') or o['summary']}@{o['start']:%Y%m%dT%H%M}"


def due_reminders(occs, now, lead_min, ahead_min, seen):
    """[(due epoch, occurrence, key)] for timed occurrences starting within
    ahead_min of now that have no reminder yet (`seen` keys). A reminder
    whose lead time has passed is due in 5 s (the event has not begun)."""
    out = []
    end = now + dt.timedelta(minutes=ahead_min)
    for o in occs:
        if o["all_day"] or not (now <= o["start"] < end):
            continue
        key = event_key(o)
        if key in seen:
            continue
        due = max(now.timestamp() + 5, o["start"].timestamp() - lead_min * 60)
        out.append((due, o, key))
    return out


def prune_seen(seen, now, days=2):
    """Keys for events more than `days` ago are dropped."""
    cutoff = (now - dt.timedelta(days=days)).strftime("%Y%m%d")
    return [k for k in seen if k.rsplit("@", 1)[-1][:8] >= cutoff]


def remind(now=None, schedule=None):
    """Arm a timers.py "calendar" alarm for each ICS / subscription / khal
    event starting soon (not Evolution's: timers.py rings for those). Off
    with timers.py's calendar alarms; their lead time. Returns how many
    were armed."""
    sources, options = read_conf()
    if not sources and not khal_paths():
        return 0
    sys.path.insert(0, HERE)
    import timers
    if not timers.calendar_on():
        return 0
    lead = timers.setting("cal_lead_min")
    ahead = max(AHEAD_MIN, lead + 10)
    refresh(sources)
    now = now or dt.datetime.now().astimezone()
    occs = occurrences(load_events(eds=False), now - dt.timedelta(hours=1), now + dt.timedelta(minutes=ahead))
    state = read_state()
    seen = set(state.get("seen", []))
    schedule = schedule or timers.schedule
    armed = 0
    for due, o, key in due_reminders(occs, now, lead, ahead, seen):
        seen.add(key)
        title = o["summary"] + (f"  ·  {o['location']}" if o.get("location") else "")
        schedule("calendar", due, title, event_at=o["start"].timestamp())
        armed += 1
    state["seen"] = prune_seen(sorted(seen), now)
    write_state(state)
    return armed


# -- the command line --------------------------------------------------------------------
def as_json(o):
    return {"summary": o["summary"], "location": o["location"], "all_day": o["all_day"],
            "start": o["start"].isoformat(), "end": o["end"].isoformat(),
            "source": source_label(o["source"])}     # no private URL token in the output


def window(days, now=None):
    now = now or dt.datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + dt.timedelta(days=days)


def main(argv):
    want_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    cmd = argv[0] if argv else "upcoming"
    now = dt.datetime.now().astimezone()
    if cmd in ("list", "upcoming", "day"):
        if cmd == "day":
            try:
                day = dt.date.fromisoformat(argv[1])
            except (IndexError, ValueError):
                sys.exit("calendar_events.py day YYYY-MM-DD")
            start = dt.datetime.combine(day, dt.time(0), now.tzinfo)
            occs = on_day(occurrences(load_events(), start, start + dt.timedelta(days=1)), day)
        else:
            n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else (7 if cmd == "list" else 3)
            start, end = window(n if cmd == "list" else 60, now)
            occs = occurrences(load_events(), start, end)
            if cmd == "upcoming":
                occs = upcoming(occs, now, n)
        if want_json:
            print(json.dumps([as_json(o) for o in occs]))
        else:
            for o in occs:
                print(f"{when_text(o, now):<24} {o['summary']}" + (f"  ({o['location']})" if o["location"] else ""))
    elif cmd == "sources":
        st = sources_status()
        if want_json:
            print(json.dumps({"conf": CONF, "sources": st}))
        else:
            for s in st:
                print(f"{'ok ' if s['ok'] else '-- '} {s['kind']:<5} {s['source']}  {s['note']}")
    elif cmd == "refresh":
        for s, why in refresh(force=True).items():
            print(f"{s}: {why or 'ok'}")
    elif cmd == "remind":
        try:
            n = remind()
        except Exception as exc:  # noqa: BLE001  (a reminder run must never fail the unit)
            print(f"calendar_events.py: {exc}", file=sys.stderr)
            return
        if n:
            print(f"calendar_events.py: {n} reminder(s) armed")
    else:
        sys.exit(__doc__.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
