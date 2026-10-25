"""timers.py's clock-card commands: pausing / resuming and editing an
alarm, countdowns to a date, the stopwatch's laps, and a ring answered from
the card (snooze / stop). Hermetic: timers.json and the ring files live in
helpers.py's scratch dirs, and arm() / systemctl() / makoctl() are stubbed
-- no systemd timer is armed or stopped, no notification is shown."""
import contextlib
import datetime as dt
import io
import json
import os
import threading
import time
import unittest

import helpers

timers = helpers.import_script("timers.py", "timers")


def quiet(argv):
    """timers.main(argv) with what it prints swallowed."""
    with contextlib.redirect_stdout(io.StringIO()):
        timers.main(argv)


class Base(unittest.TestCase):
    def setUp(self):
        for path in (timers.STATE,):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        os.makedirs(timers.RING_DIR, exist_ok=True)
        for name in os.listdir(timers.RING_DIR):
            os.remove(os.path.join(timers.RING_DIR, name))
        self.calls = []
        self._saved = {k: getattr(timers, k) for k in ("arm", "systemctl", "makoctl", "bell", "dnd_released")}
        timers.arm = lambda entry: self.calls.append(("arm", entry["id"], entry["due"]))
        timers.systemctl = lambda *a: self.calls.append(("systemctl",) + a) or 3     # 3: not active
        timers.makoctl = lambda *a: self.calls.append(("makoctl",) + a) or ""
        timers.bell = lambda: None
        timers.dnd_released = lambda: None

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(timers, k, v)

    def alarm(self, hm=(7, 30), days=None, label="gym"):
        when = timers.next_at(hm)
        return timers.start_alarm(when, label, None, days)

    def stops(self):
        return [c for c in self.calls if c[0] == "systemctl" and c[1] == "stop"]


class PauseResume(Base):
    def test_pause_keeps_the_entry_and_stops_its_timer(self):
        a = self.alarm(days=(0, 2, 4))
        timers.pause(a["id"])
        entry = timers.find(timers.load(), a["id"])
        self.assertTrue(entry["paused"])
        self.assertEqual(entry["hm"], "07:30")
        self.assertIn(("systemctl", "stop", f"hypr-timer-{a['id']}.timer", f"hypr-timer-{a['id']}.service"),
                      self.calls)

    def test_paused_one_off_remembers_its_time_of_day(self):
        a = self.alarm(hm=(6, 5), label="")
        timers.pause(a["id"])
        self.assertEqual(timers.find(timers.load(), a["id"])["hm"], "06:05")

    def test_paused_is_listed_last_and_said(self):
        a = self.alarm(days=(0, 1, 2, 3, 4, 5, 6))
        b = self.alarm(hm=(23, 59), label="late")
        timers.pause(a["id"])
        items = timers.running()
        self.assertEqual([t["id"] for t in items], [b["id"], a["id"]])
        now = time.time()
        self.assertIn("paused · 07:30", timers.describe(items[-1], now))
        self.assertIn("at ", timers.describe(items[0], now))

    def test_bar_pill_skips_a_paused_alarm(self):
        a = self.alarm(days=tuple(range(7)))
        timers.pause(a["id"])
        line = json.loads(timers.bar_line())
        self.assertEqual(line["class"], "idle")
        self.assertIn("paused", line["tooltip"])

    def test_paused_one_off_survives_its_time_passing(self):
        a = self.alarm(label="old")
        timers.pause(a["id"])
        data = timers.load()
        timers.find(data, a["id"])["due"] = time.time() - 86400      # a day after its time
        timers.save(data)
        self.assertEqual([t["id"] for t in timers.running()], [a["id"]])
        self.assertGreater(timers.running()[0]["due"], time.time())   # shown as its next 07:30
        timers.start_timer(60, "tea")                                 # schedule() prunes, but not this
        self.assertIsNotNone(timers.find(timers.load(), a["id"]))

    def test_restore_does_not_arm_a_paused_one(self):
        a = self.alarm(days=(0, 2, 4))
        timers.pause(a["id"])
        self.calls.clear()
        timers.restore()
        self.assertFalse([c for c in self.calls if c[0] == "arm"])
        self.assertTrue(timers.find(timers.load(), a["id"])["paused"])

    def test_fire_ignores_a_paused_one(self):
        a = self.alarm()
        timers.pause(a["id"])
        asked = []
        saved, timers.ask = timers.ask, lambda *a, **k: asked.append(a) or ""
        try:
            timers.fire(a["id"])
        finally:
            timers.ask = saved
        self.assertEqual(asked, [])
        self.assertIsNotNone(timers.find(timers.load(), a["id"]))

    def test_resume_arms_its_next_time(self):
        a = self.alarm(days=(0, 2, 4))
        timers.pause(a["id"])
        self.calls.clear()
        entry = timers.resume(a["id"])
        self.assertNotIn("paused", timers.find(timers.load(), a["id"]))
        arms = [c for c in self.calls if c[0] == "arm"]
        self.assertEqual(len(arms), 1)
        self.assertEqual(dt.datetime.fromtimestamp(entry["due"]).weekday() in (0, 2, 4), True)

    def test_only_alarms(self):
        t = timers.start_timer(60, "tea")
        with self.assertRaises(ValueError):
            timers.pause(t["id"])
        with self.assertRaises(ValueError):
            timers.resume("nope")


    def test_resume_a_countdown_alarm_after_its_moment(self):
        """Paused past its date, a countdown's alarm has nothing to ring:
        resume drops it and turns its countdown's bell off, instead of
        arming an OnCalendar in the past (kept() then dropped it silently)."""
        when = dt.datetime.now().replace(microsecond=0) + dt.timedelta(days=2)
        c = timers.countdown_add(when, "trip", alarm=True)
        timers.pause(c["alarm"])
        data = timers.load()
        timers.find(data, c["alarm"])["due"] = time.time() - 3600       # the date went by, paused
        timers.save(data)
        self.calls.clear()
        with self.assertRaises(ValueError):
            timers.resume(c["alarm"])
        self.assertEqual([x for x in self.calls if x[0] == "arm"], [])
        self.assertIsNone(timers.find(timers.load(), c["alarm"]))
        self.assertIsNone(timers.countdowns()[0]["alarm"])
        with self.assertRaises(SystemExit):                                # the CLI says so
            quiet(["resume", c["alarm"]])

    def test_list_says_paused(self):
        a = self.alarm(label="gym")
        timers.pause(a["id"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            timers.main(["list"])
        line = next(l for l in out.getvalue().splitlines() if l.startswith(a["id"]))
        self.assertEqual(line.split()[2], "paused")


class NextDue(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 20, 10, 0)                  # a Tuesday

    def test_one_off(self):
        later = {"due": dt.datetime(2026, 10, 20, 11, 0).timestamp(), "hm": "11:00"}
        self.assertEqual(timers.next_due(later, self.NOW), later["due"])
        gone = {"due": dt.datetime(2026, 10, 18, 7, 30).timestamp(), "hm": "07:30"}
        self.assertEqual(timers.next_due(gone, self.NOW), dt.datetime(2026, 10, 21, 7, 30).timestamp())

    def test_repeating_and_countdown(self):
        rep = {"due": 0, "hm": "07:30", "repeat": "Sat,Sun", "days": [5, 6]}
        self.assertEqual(timers.next_due(rep, self.NOW), dt.datetime(2026, 10, 24, 7, 30).timestamp())
        cd = {"due": dt.datetime(2026, 10, 1).timestamp(), "countdown": "c1"}
        self.assertEqual(timers.next_due(cd, self.NOW), cd["due"])          # its date, not a time of day

    def test_hm_of(self):
        self.assertEqual(timers.hm_of({"hm": "06:05"}), (6, 5))
        self.assertEqual(timers.hm_of({"due": dt.datetime(2026, 1, 1, 19, 45).timestamp()}), (19, 45))


class Edit(Base):
    def test_time_keeps_label_and_repeat(self):
        a = self.alarm(days=(0, 2, 4))
        self.calls.clear()
        new = timers.edit_alarm(a["id"], hm=(8, 15))
        self.assertNotEqual(new["id"], a["id"])
        self.assertEqual((new["hm"], new["label"], new["days"]), ("08:15", "gym", [0, 2, 4]))
        self.assertEqual(new["repeat"], "Mon,Wed,Fri")
        kinds = [c[0] for c in self.calls]
        self.assertLess(kinds.index("arm"), kinds.index("systemctl"))      # armed first, then the old stopped
        self.assertIsNone(timers.find(timers.load(), a["id"]))
        self.assertEqual(len(timers.load()["timers"]), 1)

    def test_repeat_to_once_and_label(self):
        a = self.alarm(days=(0, 1, 2, 3, 4))
        new = timers.edit_alarm(a["id"], days=None, label="  dentist  ")
        self.assertNotIn("repeat", new)
        self.assertEqual(new["label"], "dentist")
        self.assertEqual(new["hm"], "07:30")
        again = timers.edit_alarm(new["id"], days=(5, 6), label="")
        self.assertEqual((again["days"], again["label"]), ([5, 6], ""))
        self.assertIn(dt.datetime.fromtimestamp(again["due"]).weekday(), (5, 6))

    def test_paused_stays_paused(self):
        a = self.alarm()
        timers.pause(a["id"])
        self.calls.clear()
        new = timers.edit_alarm(a["id"], hm=(9, 0))
        self.assertTrue(new["paused"])
        self.assertFalse([c for c in self.calls if c[0] == "arm"])

    def test_refusals(self):
        with self.assertRaises(ValueError):
            timers.edit_alarm("nope", hm=(7, 0))
        c = timers.countdown_add(dt.datetime.now() + dt.timedelta(days=3), "trip", alarm=True)
        with self.assertRaises(ValueError):
            timers.edit_alarm(c["alarm"], hm=(7, 0))

    def test_parse_edit(self):
        K = timers.KEEP
        self.assertEqual(timers.parse_edit(["7:30"]), ((7, 30), K, K))
        self.assertEqual(timers.parse_edit(["7:30", "once"]), ((7, 30), None, K))
        self.assertEqual(timers.parse_edit(["7am", "weekdays", "--", "wake", "up"]),
                         ((7, 0), (0, 1, 2, 3, 4), "wake up"))
        self.assertEqual(timers.parse_edit(["19:45", "--"]), ((19, 45), K, ""))
        self.assertEqual(timers.parse_edit(["6:00", "mon", "fri"])[1], (0, 4))
        for bad in (["tea"], ["7:30", "tea"], []):
            with self.assertRaises(ValueError):
                timers.parse_edit(bad)

    def test_cli(self):
        a = self.alarm()
        quiet(["edit", a["id"], "8:00", "daily", "--", "run"])
        (entry,) = timers.load()["timers"]
        self.assertEqual((entry["hm"], entry["label"], entry["days"]), ("08:00", "run", list(range(7))))
        quiet(["pause", entry["id"]])
        self.assertTrue(timers.load()["timers"][0]["paused"])
        quiet(["resume", entry["id"]])
        self.assertNotIn("paused", timers.load()["timers"][0])
        with self.assertRaises(SystemExit):
            quiet(["pause", "nope"])


class AlarmWords(Base):
    """`alarm` as the clock card sends it: TIME [REPEAT] -- LABEL. The
    label is never read as a "then" action or a repeat."""
    NOW = dt.datetime(2026, 10, 20, 6, 0)                   # a Tuesday

    def test_label_after_the_separator_is_literal(self):
        P = timers.parse_alarm
        when, days, label, then = P(["07:00", "--", "take", "meds", "then", "sleep"], self.NOW)
        self.assertEqual((when.hour, days, label, then), (7, None, "take meds then sleep", None))
        self.assertEqual(P(["07:00", "--", "x", "then", "!rm", "foo"], self.NOW)[2:], ("x then !rm foo", None))
        self.assertEqual(P(["07:00", "--", "mon", "review"], self.NOW)[1:3], (None, "mon review"))
        self.assertEqual(P(["07:00", "weekdays", "--", "wake", "up"], self.NOW)[1:3], (tuple(range(5)), "wake up"))
        self.assertEqual(P(["19:45", "--"], self.NOW)[2], "")
        self.assertIsNone(P(["--", "7:00"], self.NOW)[0])                 # the time must come before it

    def test_without_the_separator_reads_as_before(self):
        P = timers.parse_alarm
        self.assertEqual(P(["7:30", "gym", "then", "sleep"], self.NOW)[2:], ("gym", "suspend"))
        self.assertEqual(P(["7:30", "mon", "fri", "review"], self.NOW)[1:3], ((0, 4), "review"))

    def test_cli(self):
        quiet(["alarm", "07:00", "--", "take", "meds", "then", "sleep"])
        (a,) = timers.load()["timers"]
        self.assertEqual((a["label"], a.get("then"), a.get("repeat")), ("take meds then sleep", None, None))


class Countdowns(Base):
    def test_parse_date(self):
        P = timers.parse_date
        self.assertEqual(P("2027-01-01 00:00 New Year"), (dt.datetime(2027, 1, 1), "New Year"))
        self.assertEqual(P("2027-01-01 New Year"), (dt.datetime(2027, 1, 1), "New Year"))
        self.assertEqual(P("2026-12-24 7pm dinner"), (dt.datetime(2026, 12, 24, 19), "dinner"))
        self.assertEqual(P("2026-12-24T18:30"), (dt.datetime(2026, 12, 24, 18, 30), ""))
        self.assertEqual(P("2026-02-30 x"), (None, "2026-02-30 x"))
        self.assertEqual(P("tomorrow"), (None, "tomorrow"))

    def test_until_text(self):
        U = timers.until_text
        self.assertEqual(U(412 * 86400 + 3 * 3600 + 59), "412 d 3 h")
        self.assertEqual(U(2 * 86400), "2 d")
        self.assertEqual(U(3 * 3600 + 20 * 60), "3 h 20 min")
        self.assertEqual(U(3600), "1 h")
        self.assertEqual(U(12 * 60 + 5), "12 min")
        self.assertEqual(U(45), "45 s")
        self.assertEqual(U(-30), "now")
        self.assertEqual(U(-3600), "passed")

    def test_add_list_remove(self):
        when = dt.datetime.now().replace(microsecond=0) + dt.timedelta(days=10)
        c = timers.countdown_add(when, " New  Year ")
        self.assertEqual((c["label"], c["alarm"]), ("New Year", None))
        self.assertEqual([x["id"] for x in timers.countdowns()], [c["id"]])
        timers.countdown_remove(c["id"])
        self.assertEqual(timers.countdowns(), [])
        with self.assertRaises(ValueError):
            timers.countdown_add(dt.datetime.now() - dt.timedelta(minutes=1), "gone")

    def test_alarm_on_off(self):
        when = dt.datetime.now().replace(microsecond=0) + dt.timedelta(days=2)
        c = timers.countdown_add(when, "trip", alarm=True)
        alarm = timers.find(timers.load(), c["alarm"])
        self.assertEqual((alarm["kind"], alarm["due"], alarm["countdown"]), ("alarm", when.timestamp(), c["id"]))
        self.assertTrue(timers.countdown_armed(c))
        timers.countdown_alarm(c["id"], False)
        self.assertIsNone(timers.find(timers.load(), c["alarm"]))
        self.assertFalse(timers.countdown_armed(timers.countdowns()[0]))
        timers.countdown_alarm(c["id"], True)
        c2 = timers.countdowns()[0]
        self.assertTrue(timers.countdown_armed(c2))
        timers.countdown_remove(c["id"])                    # takes its alarm with it
        self.assertEqual(timers.load()["timers"], [])

    def test_cli(self):
        quiet(["countdown", "add", "2099-01-01", "--alarm", "New", "Century"])
        (c,) = timers.countdowns()
        self.assertEqual((c["label"], c["at"]), ("New Century", dt.datetime(2099, 1, 1).timestamp()))
        self.assertTrue(timers.countdown_armed(c))
        with self.assertRaises(SystemExit):
            quiet(["countdown", "add", "soon"])
        quiet(["countdown", "remove", c["id"]])
        self.assertEqual(timers.countdowns(), [])


class CountdownWords(Base):
    def test_label_after_the_separator_is_literal(self):
        quiet(["countdown", "add", "2099-01-01", "--", "5:00", "shift"])
        (c,) = timers.countdowns()
        self.assertEqual((c["label"], c["at"]), ("5:00 shift", dt.datetime(2099, 1, 1).timestamp()))
        self.assertFalse(timers.countdown_armed(c))
        quiet(["countdown", "remove", c["id"]])
        quiet(["countdown", "add", "2099-01-01", "--", "no", "--alarm", "here"])
        (c,) = timers.countdowns()
        self.assertEqual(c["label"], "no --alarm here")
        self.assertFalse(timers.countdown_armed(c))                       # a label word is no flag
        quiet(["countdown", "remove", c["id"]])
        quiet(["countdown", "add", "--alarm", "2099-01-01", "18:00", "--", "party"])
        (c,) = timers.countdowns()
        self.assertEqual((c["label"], c["at"]), ("party", dt.datetime(2099, 1, 1, 18).timestamp()))
        self.assertTrue(timers.countdown_armed(c))


class StateLock(Base):
    def test_reentrant_in_one_process(self):
        """countdown_alarm calls schedule() / cancel() between its own load
        and save: a nested locked() must not wait for itself."""
        with timers.locked():
            with timers.locked():
                timers.stopwatch_do("start")
        self.assertIsNotNone(timers.stopwatch())
        self.assertEqual(timers._lock_fd, [None, 0])                       # released at the outer end

    def test_save_uses_its_own_tmp(self):
        seen = []
        real = timers.os.replace
        timers.os.replace = lambda a, b: seen.append(a) or real(a, b)
        try:
            timers.save({"timers": [], "stopwatch": None})
        finally:
            timers.os.replace = real
        self.assertEqual(seen, [f"{timers.STATE}.{os.getpid()}.tmp"])

    def test_two_threads_lose_no_update(self):
        """Laps taken from two threads at once (the launcher daemon's
        threads share the flock; the RLock orders them): every one kept."""
        clock, lock = [1000.0], threading.Lock()

        def tick():                     # a second later on every read: no two laps the same moment
            with lock:
                clock[0] += 1
                return clock[0]
        saved, timers.time.time = timers.time.time, tick
        try:
            timers.stopwatch_do("start")

            def lap():
                timers.stopwatch_do("lap")
            threads = [threading.Thread(target=lap) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            timers.time.time = saved
        self.assertEqual(len(timers.laps()), 8)


class Laps(Base):
    def test_laps_persist_and_reset_clears(self):
        clock = [1000.0]
        saved, timers.time.time = timers.time.time, lambda: clock[0]
        try:
            self.assertIsNone(timers.stopwatch_do("lap"))           # nothing has run
            timers.stopwatch_do("start")
            clock[0] = 1010.0
            self.assertEqual(timers.stopwatch_do("lap"), 10.0)
            clock[0] = 1030.5
            timers.stopwatch_do("lap")
            timers.stopwatch_do("pause")
            clock[0] = 1100.0
            self.assertIsNone(timers.stopwatch_do("lap"))           # paused: the same moment again
            self.assertEqual(timers.laps(), [10.0, 30.5])
            timers.stopwatch_do("start")                            # laps survive pause / resume
            self.assertEqual(timers.laps(), [10.0, 30.5])
            timers.stopwatch_do("reset")
            self.assertEqual(timers.laps(), [])
        finally:
            timers.time.time = saved

    def test_lap_rows(self):
        self.assertEqual(timers.lap_rows([10.0, 30.5, 31.0]), [(3, 0.5, 31.0), (2, 20.5, 30.5), (1, 10.0, 10.0)])
        self.assertEqual(timers.lap_rows([]), [])


class Ringing(Base):
    def ring(self, tid="42", pid=None, since=None):
        timers.ring_start({"id": tid, "kind": "alarm", "label": "wake"}, 300)
        if pid is not None or since is not None:
            path = timers.ring_path(tid)
            with open(path) as handle:
                data = json.load(handle)
            data.update({k: v for k, v in (("pid", pid), ("since", since)) if v is not None})
            with open(path, "w") as handle:
                json.dump(data, handle)

    def test_listed_while_its_process_lives(self):
        self.ring()
        (r,) = timers.ringing()
        self.assertEqual((r["id"], r["label"], r["snooze"]), ("42", "wake", 300))
        timers.ring_end("42")
        self.assertEqual(timers.ringing(), [])

    def test_stale_files_are_dropped(self):
        self.ring("1", pid=2 ** 22 + 12345)          # no such process
        self.ring("2", since=time.time() - timers.RING_S - 60)
        self.assertEqual(timers.ringing(), [])
        self.assertFalse(os.path.exists(timers.ring_path("1")))

    def test_pick(self):
        self.assertFalse(timers.ring_pick("42", "stop"))         # nothing rings
        self.ring()
        self.assertTrue(timers.ring_pick("42", "snooze"))
        self.assertEqual(timers.read_pick("42"), "snooze")
        with self.assertRaises(ValueError):
            timers.ring_pick("42", "explode")
        with self.assertRaises(SystemExit):
            quiet(["stop", "7"])

    def test_a_new_ring_clears_an_old_pick(self):
        """A pick left behind (the ring ended between ring_pick's check and
        its write) must not answer the next ring of the same id -- a
        repeating alarm keeps its id day after day."""
        os.makedirs(timers.RING_DIR, exist_ok=True)
        with open(timers.ring_path("42", "pick"), "w") as handle:
            handle.write("stop")
        self.ring()
        self.assertEqual(timers.read_pick("42"), "")

    def test_orphan_picks_are_swept(self):
        with open(timers.ring_path("9", "pick"), "w") as handle:
            handle.write("snooze")
        writing = timers.ring_path("8", "pick") + ".123.tmp"             # ring_pick mid-write: left
        with open(writing, "w") as handle:
            handle.write("stop")
        self.ring()                                                       # 42 rings, with no pick
        self.assertEqual([r["id"] for r in timers.ringing()], ["42"])
        self.assertFalse(os.path.exists(timers.ring_path("9", "pick")))
        self.assertTrue(os.path.exists(writing))

    def test_bar_says_ringing(self):
        self.ring()
        line = json.loads(timers.bar_line())
        self.assertEqual(line["class"], "ringing")
        self.assertIn("wake", line["text"])


class FakeNotify:
    """notify-send -p --wait: prints its id, then (maybe) an action, then
    sits until it ends or is killed."""
    def __init__(self, lines, ends=False):
        r, self.w = os.pipe()
        self.stdout = os.fdopen(r)
        os.write(self.w, "".join(f"{l}\n" for l in lines).encode())
        self.killed = False
        if ends:
            self.close()

    def close(self):
        if self.w is not None:
            os.close(self.w)
            self.w = None

    def poll(self):
        return 0 if self.w is None else None

    def kill(self):
        self.killed = True
        self.close()


class WaitPick(Base):
    def setUp(self):
        super().setUp()
        self.saved_popen, self.saved_poll = timers.subprocess.Popen, timers.RING_POLL_S
        timers.RING_POLL_S = 0.02

    def tearDown(self):
        timers.subprocess.Popen, timers.RING_POLL_S = self.saved_popen, self.saved_poll
        super().tearDown()

    def run_with(self, proc, argv_seen=None):
        def popen(argv, **_kw):
            if argv_seen is not None:
                argv_seen.extend(argv)
            return proc
        timers.subprocess.Popen = popen
        return timers.wait_pick(["notify-send", "-A", "stop=Stop", "Alarm", "07:30"], "42", 5)

    def test_card_pick_dismisses_the_notification(self):
        proc = FakeNotify(["17"])
        threading.Timer(0.1, lambda: timers.ring_pick("42", "snooze")).start()
        self.ring_running()
        argv = []
        self.assertEqual(self.run_with(proc, argv), "snooze")
        self.assertTrue(proc.killed)
        self.assertIn(("makoctl", "dismiss", "-n", "17"), self.calls)
        self.assertIn("-p", argv)

    def test_timeout_leaves_the_notification(self):
        """Nobody answered in time: notify-send is stopped, but the toast
        stays -- the only trace that it rang."""
        proc = FakeNotify(["17"])
        self.ring_running()

        def popen(argv, **_kw):
            return proc
        timers.subprocess.Popen = popen
        self.assertEqual(timers.wait_pick(["notify-send", "Alarm", "07:30"], "42", 0.1), "")
        self.assertTrue(proc.killed)
        self.assertFalse([c for c in self.calls if c[:2] == ("makoctl", "dismiss")])

    def test_notification_button(self):
        proc = FakeNotify(["17", "stop"])
        self.assertEqual(self.run_with(proc), "stop")
        self.assertTrue(proc.killed)

    def test_closed(self):
        proc = FakeNotify(["17"], ends=True)
        self.assertEqual(self.run_with(proc), "")
        self.assertFalse(proc.killed)

    def ring_running(self):
        timers.ring_start({"id": "42", "kind": "alarm", "label": ""}, 300)


if __name__ == "__main__":
    unittest.main()
