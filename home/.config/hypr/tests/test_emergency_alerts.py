"""emergency-alerts.py's quieter poller: poll_outcome (a failure is logged
and saved only after FAIL_AFTER in a row), note_ok (last_ok to the runtime
file, throttled), and a poller loop that writes the state file only when
something changed.

Hermetic: the state and runtime files are helpers' scratch ones; the feed
is a stub; no network, no wpctl, no notification."""
import json
import os
import unittest
from unittest import mock

import helpers

ea = helpers.import_script("emergency-alerts.py")


class Outcome(unittest.TestCase):
    def test_success_with_nothing_saved_writes_nothing(self):
        self.assertEqual(ea.poll_outcome(0, "", ""), (0, False, None))

    def test_one_or_two_failures_are_quiet(self):
        self.assertEqual(ea.poll_outcome(0, "TimeoutError: timed out", ""), (1, False, None))
        self.assertEqual(ea.poll_outcome(1, "TimeoutError: timed out", ""), (2, False, None))

    def test_third_in_a_row_logged_and_saved(self):
        self.assertEqual(ea.poll_outcome(2, "TimeoutError: timed out", ""),
                         (3, True, "TimeoutError: timed out"))

    def test_then_quiet_until_the_hundredth(self):
        err = "TimeoutError: timed out"
        self.assertEqual(ea.poll_outcome(3, err, err), (4, False, None))
        self.assertEqual(ea.poll_outcome(99, err, err), (100, True, None))     # logged, same text: no write

    def test_recovery_logged_and_cleared(self):
        self.assertEqual(ea.poll_outcome(5, "", "TimeoutError: timed out"), (0, True, ""))

    def test_recovery_after_quiet_blip(self):
        self.assertEqual(ea.poll_outcome(2, "", ""), (0, False, None))


class Live(unittest.TestCase):
    def setUp(self):
        ea.LIVE_OK.clear()
        ea._LIVE_WRITTEN.clear()
        try:
            os.unlink(ea.LIVE)
        except OSError:
            pass

    def test_throttled(self):
        self.assertTrue(ea.LIVE.startswith(helpers.SCRATCH))
        ea.note_ok("sasmex", 1000.0)
        self.assertEqual(ea.load_live(), {"sasmex": 1000.0})
        ea.note_ok("sasmex", 1003.0)
        self.assertEqual(ea.load_live(), {"sasmex": 1000.0})     # not yet written again
        self.assertEqual(ea.LIVE_OK["sasmex"], 1003.0)          # but known in memory
        ea.note_ok("sasmex", 1000.0 + ea.LIVE_EVERY_S)
        self.assertEqual(ea.load_live(), {"sasmex": 1000.0 + ea.LIVE_EVERY_S})


class Poller(unittest.TestCase):
    """The loop, with a stub feed and time.sleep ending it after N polls."""

    def run_polls(self, results):
        feed = iter(results)

        def fetch(http, conf):
            r = next(feed)
            if isinstance(r, Exception):
                raise r
            return r

        polls = [0]

        def sleep(_s):
            polls[0] += 1
            if polls[0] >= len(results):
                raise StopIteration

        writes = []
        real = ea.update_state

        def counting(source, **values):
            writes.append(values)
            return real(source, **values)
        with mock.patch.dict(ea.SOURCES, {"stub": ("stub", ["XX"], "test", 3, True, fetch)}), \
                mock.patch.object(ea.time, "sleep", sleep), \
                mock.patch.object(ea, "update_state", counting), \
                mock.patch.object(ea, "act", lambda a, conf: None), \
                mock.patch("builtins.print"):
            with self.assertRaises(StopIteration):
                ea.poller("stub", {})
        return writes

    def setUp(self):
        try:
            os.unlink(ea.STATE)
        except OSError:
            pass

    def test_steady_polls_write_nothing(self):
        self.assertEqual(self.run_polls([[], [], [], [], []]), [])

    def test_quiet_timeouts_then_logged(self):
        t = TimeoutError("timed out")
        writes = self.run_polls([t, t, [], t, t, t, t])
        self.assertEqual(writes, [{"error": "TimeoutError: timed out"}])
        with open(ea.STATE) as fh:
            self.assertEqual(json.load(fh)["stub"]["error"], "TimeoutError: timed out")

    def test_new_alert_written_once(self):
        old = ea._alert("a1", 0, "old", "", "none")
        writes = self.run_polls([[old], [old], [old]])
        self.assertEqual(writes, [{"seen": ["a1"], "error": ""}])


if __name__ == "__main__":
    unittest.main()
