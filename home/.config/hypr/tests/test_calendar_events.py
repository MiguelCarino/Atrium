"""calendar_events.py: the ICS parser (unfolding, parameters, DTSTART in
UTC / TZID / floating / all-day, DURATION), the recurrence walker (DAILY /
WEEKLY / MONTHLY / YEARLY with INTERVAL, COUNT, UNTIL, BYDAY, BYMONTHDAY,
BYMONTH; EXDATE; RECURRENCE-ID), the day dots, the upcoming list, the
calendars.conf reader and the reminder bookkeeping.

Hermetic: no URL is fetched (fetch gets a fake opener), no Evolution or
khal is read (load_events(eds=False, khal=False) with a scratch conf), no
alarm is armed (remind's schedule is a fake)."""
import datetime as dt
import io
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

import helpers

ce = helpers.import_script("calendar_events.py")
UTC = dt.timezone.utc
MX = ZoneInfo("America/Mexico_City")
NY = ZoneInfo("America/New_York")


def cal(*events):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(
        "BEGIN:VEVENT\r\n" + body.strip().replace("\n", "\r\n") + "\r\nEND:VEVENT\r\n" for body in events
    ) + "END:VCALENDAR\r\n"


def occ_between(text, start, end, zone=UTC):
    return ce.occurrences(ce.parse_ics(text, local=zone), start, end, zone)


class Parse(unittest.TestCase):
    def test_unfold_and_escape(self):
        text = cal("UID:a\nSUMMARY:Long \n title\\, with comma\nLOCATION:Room 1\\nFloor 2\nDTSTART:20261028T150000Z")
        e = ce.parse_ics(text)[0]
        self.assertEqual(e["summary"], "Long title, with comma")
        self.assertEqual(e["location"], "Room 1\nFloor 2")

    def test_parse_line_quoted_colon(self):
        self.assertEqual(ce.parse_line('ATTENDEE;CN="A: B":mailto:x@y'),
                         ("ATTENDEE", {"CN": "A: B"}, "mailto:x@y"))
        self.assertIsNone(ce.parse_line("garbage"))

    def test_when_kinds(self):
        self.assertEqual(ce.parse_when("20261028T150000Z", {}),
                         (dt.datetime(2026, 10, 28, 15, tzinfo=UTC), False))
        when, all_day = ce.parse_when("20261028T090000", {"TZID": "America/New_York"})
        self.assertEqual((when.utcoffset(), all_day), (dt.timedelta(hours=-4), False))
        self.assertEqual(ce.parse_when("20261028", {"VALUE": "DATE"}), (dt.date(2026, 10, 28), True))
        floating, _ = ce.parse_when("20261028T0900", {}, local=MX)
        self.assertEqual((floating.hour, floating.tzinfo), (9, MX))
        self.assertIsNone(ce.parse_when("tomorrow", {}))

    def test_evolution_tzid(self):
        self.assertEqual(ce.zone_for("/freeassociation.sourceforge.net/Europe/Paris"), ZoneInfo("Europe/Paris"))
        self.assertIsNone(ce.zone_for("Not/AZone"))
        self.assertEqual(ce.zone_for("UTC"), UTC)

    def test_duration_and_defaults(self):
        self.assertEqual(ce.parse_duration("PT1H30M"), dt.timedelta(minutes=90))
        self.assertEqual(ce.parse_duration("P1W2D"), dt.timedelta(days=9))
        self.assertEqual(ce.parse_duration("-PT15M"), dt.timedelta(minutes=-15))
        self.assertIsNone(ce.parse_duration("P"))
        e = ce.parse_ics(cal("UID:d\nDTSTART:20261028T150000Z\nDURATION:PT45M"))[0]
        self.assertEqual(e["end"] - e["start"], dt.timedelta(minutes=45))
        a = ce.parse_ics(cal("UID:a\nDTSTART;VALUE=DATE:20261028"))[0]
        self.assertEqual((a["all_day"], a["end"]), (True, dt.date(2026, 10, 29)))

    def test_alarm_inside_event_is_skipped(self):
        text = cal("UID:x\nSUMMARY:Outer\nDTSTART:20261028T150000Z\nBEGIN:VALARM\nSUMMARY:Inner\n"
                   "TRIGGER:-PT5M\nEND:VALARM")
        events = ce.parse_ics(text)
        self.assertEqual([e["summary"] for e in events], ["Outer"])

    def test_no_dtstart_and_no_title(self):
        self.assertEqual(ce.parse_ics(cal("UID:x\nSUMMARY:none")), [])
        self.assertEqual(ce.parse_ics(cal("UID:x\nDTSTART:20261028T150000Z"))[0]["summary"], ce.UNTITLED)

    def test_rrule(self):
        r = ce.parse_rrule("FREQ=MONTHLY;INTERVAL=2;BYDAY=2MO,-1FR;COUNT=5;BYMONTH=1,13")
        self.assertEqual((r["freq"], r["interval"], r["count"], r["byday"], r["bymonth"]),
                         ("MONTHLY", 2, 5, [(2, 0), (-1, 4)], [1]))
        self.assertIsNone(ce.parse_rrule("FREQ=HOURLY"))


class Recur(unittest.TestCase):
    W = (dt.datetime(2026, 10, 1, tzinfo=UTC), dt.datetime(2026, 11, 1, tzinfo=UTC))

    def starts(self, body, window=None, zone=UTC):
        a, b = window or self.W
        return [o["start"] for o in occ_between(cal(body), a, b, zone)]

    def test_daily_count_interval(self):
        got = self.starts("UID:d\nDTSTART:20261001T080000Z\nRRULE:FREQ=DAILY;INTERVAL=3;COUNT=4")
        self.assertEqual([s.day for s in got], [1, 4, 7, 10])

    def test_weekly_byday_until(self):
        got = self.starts("UID:w\nDTSTART:20261005T090000Z\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261014T235959Z")
        self.assertEqual([s.day for s in got], [5, 7, 12, 14])

    def test_weekly_every_other(self):
        got = self.starts("UID:w\nDTSTART:20261001T090000Z\nRRULE:FREQ=WEEKLY;INTERVAL=2")
        self.assertEqual([s.day for s in got], [1, 15, 29])

    def test_monthly_nth_weekday_and_last(self):
        window = (dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 4, 1, tzinfo=UTC))
        got = self.starts("UID:m\nDTSTART:20260109T100000Z\nRRULE:FREQ=MONTHLY;BYDAY=-1FR", window)
        self.assertEqual([s.date() for s in got],
                         [dt.date(2026, 1, 30), dt.date(2026, 2, 27), dt.date(2026, 3, 27)])
        got = self.starts("UID:m2\nDTSTART:20260112T100000Z\nRRULE:FREQ=MONTHLY;BYDAY=2MO", window)
        self.assertEqual([s.day for s in got], [12, 9, 9])

    def test_monthly_31st_skips_short_months(self):
        window = (dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 6, 1, tzinfo=UTC))
        got = self.starts("UID:m\nDTSTART:20260131T100000Z\nRRULE:FREQ=MONTHLY", window)
        self.assertEqual([s.month for s in got], [1, 3, 5])

    def test_yearly_all_day_birthday_from_long_ago(self):
        window = (dt.datetime(2026, 3, 1, tzinfo=UTC), dt.datetime(2026, 4, 1, tzinfo=UTC))
        occs = occ_between(cal("UID:b\nSUMMARY:Birthday\nDTSTART;VALUE=DATE:19900314\nRRULE:FREQ=YEARLY"), *window)
        self.assertEqual([(o["start"], o["all_day"]) for o in occs], [(dt.date(2026, 3, 14), True)])

    def test_yearly_bymonth_byday(self):
        window = (dt.datetime(2026, 11, 1, tzinfo=UTC), dt.datetime(2026, 12, 1, tzinfo=UTC))
        got = self.starts("UID:t\nDTSTART;VALUE=DATE:20201126\nRRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=4TH", window)
        self.assertEqual(got, [dt.date(2026, 11, 26)])

    def test_exdate_and_tzid_across_dst(self):
        body = ("UID:s\nDTSTART;TZID=America/New_York:20261026T090000\nRRULE:FREQ=WEEKLY;COUNT=3\n"
                "EXDATE;TZID=America/New_York:20261102T090000")
        window = (dt.datetime(2026, 10, 20, tzinfo=UTC), dt.datetime(2026, 11, 20, tzinfo=UTC))
        got = self.starts(body, window, zone=NY)
        self.assertEqual([(s.month, s.day, s.hour) for s in got], [(10, 26, 9), (11, 9, 9)])
        # 09:00 New York stays 09:00 there: 13:00 UTC before the change, 14:00 after.
        self.assertEqual([s.astimezone(UTC).hour for s in got], [13, 14])

    def test_recurrence_id_moves_one(self):
        text = cal("UID:r\nSUMMARY:Standup\nDTSTART:20261005T090000Z\nDTEND:20261005T091500Z\n"
                   "RRULE:FREQ=DAILY;COUNT=3",
                   "UID:r\nSUMMARY:Standup (moved)\nRECURRENCE-ID:20261006T090000Z\n"
                   "DTSTART:20261006T110000Z\nDTEND:20261006T111500Z")
        occs = ce.occurrences(ce.parse_ics(text), *self.W, UTC)
        self.assertEqual([(o["start"].day, o["start"].hour, o["summary"]) for o in occs],
                         [(5, 9, "Standup"), (6, 11, "Standup (moved)"), (7, 9, "Standup")])

    def test_cancelled_left_out(self):
        self.assertEqual(self.starts("UID:c\nDTSTART:20261005T090000Z\nSTATUS:CANCELLED"), [])

    def test_window_skip_ahead_keeps_old_daily(self):
        window = (dt.datetime(2026, 10, 28, tzinfo=UTC), dt.datetime(2026, 10, 30, tzinfo=UTC))
        got = self.starts("UID:o\nDTSTART:20000101T070000Z\nRRULE:FREQ=DAILY", window)
        self.assertEqual([s.day for s in got], [28, 29])

    def test_multi_day_event_reaching_into_window(self):
        window = (dt.datetime(2026, 10, 10, tzinfo=UTC), dt.datetime(2026, 10, 11, tzinfo=UTC))
        occs = occ_between(cal("UID:t\nDTSTART;VALUE=DATE:20261008\nDTEND;VALUE=DATE:20261012"), *window)
        self.assertEqual(len(occs), 1)


class Days(unittest.TestCase):
    def test_dots_and_day_list(self):
        text = cal("UID:a\nSUMMARY:Trip\nDTSTART;VALUE=DATE:20261008\nDTEND;VALUE=DATE:20261010",
                   "UID:b\nSUMMARY:Late\nDTSTART:20261012T220000Z\nDTEND:20261013T010000Z",
                   "UID:c\nSUMMARY:Ends at midnight\nDTSTART:20261015T200000Z\nDTEND:20261016T000000Z")
        occs = occ_between(text, dt.datetime(2026, 10, 1, tzinfo=UTC), dt.datetime(2026, 11, 1, tzinfo=UTC))
        days = ce.days_with_events(occs)
        self.assertEqual(sorted(d.day for d in days), [8, 9, 12, 13, 15])
        self.assertEqual([o["summary"] for o in ce.on_day(occs, dt.date(2026, 10, 13))], ["Late"])
        late = ce.on_day(occs, dt.date(2026, 10, 13))[0]
        self.assertEqual(ce.time_text(late, dt.date(2026, 10, 13)), "until 01:00")
        self.assertEqual(ce.time_text(late, dt.date(2026, 10, 12)), "from 22:00")
        midnight = ce.on_day(occs, dt.date(2026, 10, 15))[0]
        self.assertEqual(ce.time_text(midnight, dt.date(2026, 10, 15)), "20:00–00:00")

    def test_upcoming_and_when_text(self):
        text = cal("UID:a\nSUMMARY:Past\nDTSTART:20261028T080000Z\nDTEND:20261028T090000Z",
                   "UID:b\nSUMMARY:Running\nDTSTART:20261028T113000Z\nDTEND:20261028T130000Z",
                   "UID:c\nSUMMARY:Later\nDTSTART:20261028T160000Z",
                   "UID:d\nSUMMARY:Holiday\nDTSTART;VALUE=DATE:20261029",
                   "UID:e\nSUMMARY:Far\nDTSTART:20261105T100000Z")
        now = dt.datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
        occs = occ_between(text, now.replace(hour=0), now + dt.timedelta(days=30))
        nxt = ce.upcoming(occs, now, 3)
        self.assertEqual([o["summary"] for o in nxt], ["Running", "Later", "Holiday"])
        self.assertEqual([ce.when_text(o, now) for o in nxt],
                         ["now (until 13:00)", "today 16:00", "tomorrow, all day"])
        self.assertEqual(ce.time_text(nxt[1], twelve=True), "4:00 PM")


class Conf(unittest.TestCase):
    def test_read_conf_and_sources(self):
        with tempfile.TemporaryDirectory(dir=helpers.SCRATCH) as d:
            ics = os.path.join(d, "a.ics")
            with open(ics, "w") as handle:
                handle.write(cal("UID:1\nSUMMARY:From file\nDTSTART:20261028T150000Z"))
            conf = os.path.join(d, "calendars.conf")
            with open(conf, "w") as handle:
                handle.write(f"# mine\n{ics}\n{d}/\nwebcal://example.invalid/x.ics\neds=off\nKHAL = off\n")
            sources, options = ce.read_conf(conf)
            self.assertEqual(sources, [ics, d + "/", "webcal://example.invalid/x.ics"])
            self.assertEqual(options, {"eds": "off", "khal": "off"})
            self.assertTrue(ce.is_url(sources[2]))
            self.assertEqual(ce.fetch_url(sources[2]), "https://example.invalid/x.ics")
            events = ce.load_events(eds=False, conf=conf, khal=False)
            # The file twice (by itself and through its folder); the URL has no cache yet.
            self.assertEqual([e["summary"] for e in events], ["From file", "From file"])

    def test_fetch_keeps_old_copy_on_failure(self):
        src = "https://example.invalid/cal.ics"

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        good = cal("UID:1\nDTSTART:20261028T150000Z").encode()
        self.assertEqual(ce.fetch(src, opener=lambda req, timeout: Resp(good)), "")
        self.assertFalse(ce.stale(ce.cache_path(src)))

        def boom(req, timeout):
            raise OSError("offline")
        self.assertEqual(ce.fetch(src, opener=boom), "offline")
        self.assertIn("not a calendar", ce.fetch(src, opener=lambda req, timeout: Resp(b"<html>")))
        with open(ce.cache_path(src), "rb") as handle:
            self.assertEqual(handle.read(), good)

    def test_khal_paths(self):
        with tempfile.TemporaryDirectory(dir=helpers.SCRATCH) as d:
            os.makedirs(os.path.join(d, "cals", "home"))
            os.makedirs(os.path.join(d, "cals", "work"))
            conf = os.path.join(d, "config")
            with open(conf, "w") as handle:
                handle.write(f"[calendars]\n[[all]]\npath = {d}/cals/*\ntype = discover\n")
            self.assertEqual([os.path.basename(p) for p in ce.khal_paths(conf)], ["home", "work"])
        self.assertEqual(ce.khal_paths("/nonexistent/khal"), [])


class Reminders(unittest.TestCase):
    def test_due_reminders(self):
        now = dt.datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
        text = cal("UID:a\nSUMMARY:Soon\nDTSTART:20261028T121500Z",
                   "UID:b\nSUMMARY:Very soon\nDTSTART:20261028T120500Z",
                   "UID:c\nSUMMARY:Later\nDTSTART:20261028T140000Z",
                   "UID:d\nSUMMARY:All day\nDTSTART;VALUE=DATE:20261028")
        occs = occ_between(text, now - dt.timedelta(hours=1), now + dt.timedelta(minutes=30))
        due = ce.due_reminders(occs, now, 10, 30, set())
        self.assertEqual([(o["summary"], round(t - now.timestamp())) for t, o, _k in due],
                         [("Very soon", 5), ("Soon", 300)])
        seen = {k for _t, _o, k in due}
        self.assertEqual(ce.due_reminders(occs, now, 10, 30, seen), [])
        self.assertEqual(ce.prune_seen(["a@20261020T0900", "b@20261027T0900"], now), ["b@20261027T0900"])

    def test_remind_arms_once(self):
        with tempfile.TemporaryDirectory(dir=helpers.SCRATCH) as d:
            now = dt.datetime.now(UTC).replace(second=0, microsecond=0) + dt.timedelta(minutes=20)
            ics = os.path.join(d, "a.ics")
            with open(ics, "w") as handle:
                handle.write(cal(f"UID:r\nSUMMARY:Call\nLOCATION:Room 2\nDTSTART:{now:%Y%m%dT%H%M%SZ}"))
            conf = os.path.join(d, "calendars.conf")
            with open(conf, "w") as handle:
                handle.write(f"{ics}\n")
            old = ce.CONF
            ce.CONF = conf
            self.addCleanup(setattr, ce, "CONF", old)
            armed = []
            sched = lambda kind, due, label, **kw: armed.append((kind, label))   # noqa: E731
            ce.remind(schedule=sched)
            ce.remind(schedule=sched)
            self.assertEqual(armed, [("calendar", "Call  ·  Room 2")])


class LocalZone(unittest.TestCase):
    def test_source_label_hides_url_secrets(self):
        self.assertEqual(ce.source_label("https://cal.example.org/private-abc/basic.ics?token=x"),
                         "https://cal.example.org/\u2026")
        self.assertEqual(ce.source_label("webcal://user:pw@cal.example.org/a.ics"), "webcal://cal.example.org/\u2026")
        self.assertEqual(ce.source_label("https://cal.example.org"), "https://cal.example.org")
        self.assertEqual(ce.source_label("~/Calendars/a.ics"), "~/Calendars/a.ics")

    def test_zone_name(self):
        self.assertEqual(ce.zone_name(":Europe/Paris", ""), "Europe/Paris")
        self.assertEqual(ce.zone_name("", "../usr/share/zoneinfo/America/New_York"), "America/New_York")
        self.assertEqual(ce.zone_name("CST6CDT", "/usr/share/zoneinfo/Asia/Tokyo"), "Asia/Tokyo")
        self.assertEqual(ce.zone_name("", ""), "")

    def test_local_zone_keeps_dst(self):
        # A ZoneInfo (not a fixed offset): 09:00 floating in January and
        # July has two different UTC offsets in a DST zone.
        old = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        try:
            z = ce.local_zone()
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
        jan = dt.datetime(2026, 1, 5, 9, tzinfo=z).utcoffset()
        jul = dt.datetime(2026, 7, 6, 9, tzinfo=z).utcoffset()
        self.assertNotEqual(jan, jul)


if __name__ == "__main__":
    unittest.main()
