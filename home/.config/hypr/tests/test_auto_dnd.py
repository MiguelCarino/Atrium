"""auto-dnd.py's screen-share hysteresis: ShareDebounce (a share counts only
after SHARE_ENGAGE_S, and for SHARE_GRACE_S after it ends), ToggleLimiter
(never back on within MIN_TOGGLE_S of turning it off), share_owner, and the
Watch driving both with a fake monotonic clock.

Hermetic: makoctl / hyprctl / waybar are stubbed; the clock is patched."""
import os
import tempfile
import unittest
from unittest import mock

import helpers

ad = helpers.import_script("auto-dnd.py")


def conf(**over):
    c = {"dnd_games": True, "dnd_share": True, "quiet": False,
         "quiet_from": "22:00", "quiet_to": "07:00", "quiet_days": "all"}
    c.update(over)
    return c


class Debounce(unittest.TestCase):
    def test_blip_never_counts(self):
        d = ad.ShareDebounce(engage_s=10, grace_s=20)
        self.assertFalse(d.event(True, 100.0))
        self.assertEqual(d.deadline(), 110.0)
        self.assertFalse(d.event(False, 100.8))
        self.assertFalse(d.active)
        self.assertIsNone(d.deadline())
        self.assertEqual(d.blips, 1)
        self.assertFalse(d.poll(200.0))

    def test_share_engages_after_engage_s(self):
        d = ad.ShareDebounce(engage_s=10, grace_s=20)
        d.event(True, 0.0)
        self.assertFalse(d.poll(9.9))
        self.assertTrue(d.poll(10.0))
        self.assertTrue(d.active)
        self.assertIsNone(d.deadline())        # running: nothing timed

    def test_grace_after_end(self):
        d = ad.ShareDebounce(engage_s=10, grace_s=20)
        d.event(True, 0.0)
        d.poll(10.0)
        self.assertFalse(d.event(False, 50.0))
        self.assertTrue(d.active)
        self.assertEqual(d.deadline(), 70.0)
        self.assertFalse(d.poll(69.0))
        self.assertTrue(d.poll(70.0))
        self.assertFalse(d.active)
        self.assertEqual(d.blips, 0)

    def test_new_share_inside_grace_keeps_it(self):
        d = ad.ShareDebounce(engage_s=10, grace_s=20)
        d.event(True, 0.0)
        d.poll(10.0)
        d.event(False, 50.0)
        d.event(True, 55.0)
        self.assertFalse(d.poll(80.0))
        self.assertTrue(d.active)

    def test_repeated_on_does_not_restart_the_clock(self):
        d = ad.ShareDebounce(engage_s=10, grace_s=20)
        d.event(True, 0.0)
        d.event(True, 8.0)
        self.assertTrue(d.poll(10.0))

    def test_flapping_pattern_never_engages(self):
        """The measured night: a <1 s share every 30 s."""
        d = ad.ShareDebounce()
        t = 0.0
        for _ in range(200):
            d.event(True, t)
            d.poll(t + 0.5)
            d.event(False, t + 0.9)
            t += 30
        self.assertFalse(d.active)
        self.assertEqual(d.blips, 200)


class Limiter(unittest.TestCase):
    def test_limits_turning_back_on(self):
        lim = ad.ToggleLimiter(min_s=30)
        self.assertTrue(lim.may_turn_on(0))
        self.assertIsNone(lim.on_after())
        lim.turned_off(100)
        self.assertFalse(lim.may_turn_on(110))
        self.assertEqual(lim.on_after(), 130)
        self.assertTrue(lim.may_turn_on(130))


class WatchShares(unittest.TestCase):
    """The Watch with mako, hyprctl and the clock stubbed."""

    def setUp(self):
        self.dnd = False
        self.log = []
        self.now = 1000.0

        def set_dnd(on, why):
            self.dnd = on
            self.log.append((on, why))
        self.patches = [mock.patch.object(ad, "games", lambda: 0),
                        mock.patch.object(ad, "dnd_on", lambda: self.dnd),
                        mock.patch.object(ad, "set_dnd", set_dnd),
                        mock.patch.object(ad, "focus_running", lambda: False),
                        mock.patch.object(ad, "share_owner", lambda: "grim (from island.py)"),
                        mock.patch.object(ad.time, "monotonic", lambda: self.now),
                        mock.patch("builtins.print")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def step(self, seconds):
        """Advance the clock, running due() at each deadline on the way."""
        end = self.now + seconds
        while True:
            due = self.w.next_due()
            if due is None or due > end:
                break
            self.now = max(self.now, due)
            self.w.due(self.now)
        self.now = end
        self.w.due(self.now)

    def test_blips_never_toggle(self):
        self.w = ad.Watch(conf())
        for _ in range(50):
            self.w.event("screencast>>1,monitor")
            self.step(0.8)
            self.w.event("screencast>>0,monitor")
            self.step(29.2)
        self.assertEqual(self.log, [])
        self.assertEqual(self.w.share_by, "grim (from island.py)")

    def test_long_share_on_then_off_after_grace(self):
        self.w = ad.Watch(conf())
        self.w.event("screencast>>1,monitor")
        self.step(9)
        self.assertFalse(self.dnd)
        self.step(1)
        self.assertEqual(self.log, [(True, "screen share")])
        self.step(300)
        self.w.event("screencast>>0,monitor")
        self.step(ad.SHARE_GRACE_S - 1)
        self.assertTrue(self.dnd)
        self.step(1 + ad.RELEASE_S)
        self.assertFalse(self.dnd)
        self.assertEqual(len(self.log), 2)

    def test_not_back_on_within_min_toggle(self):
        self.w = ad.Watch(conf())
        self.w.event("screencast>>1,monitor")
        self.step(ad.SHARE_ENGAGE_S)
        self.w.event("screencast>>0,monitor")
        self.step(ad.SHARE_GRACE_S + ad.RELEASE_S)
        self.assertFalse(self.dnd)
        off_at = self.now
        self.w.game = True                       # a game right after: held back
        self.w.update()
        self.assertFalse(self.dnd)
        self.assertEqual(self.w.next_due(), off_at + ad.MIN_TOGGLE_S)
        self.step(ad.MIN_TOGGLE_S)
        self.assertTrue(self.dnd)
        self.assertEqual(self.log[-1], (True, "game"))


class Owner(unittest.TestCase):
    def test_share_owner_reads_proc(self):
        with tempfile.TemporaryDirectory() as proc:
            def make(pid, comm, cmdline, ppid):
                os.makedirs(os.path.join(proc, str(pid)))
                with open(os.path.join(proc, str(pid), "comm"), "w") as fh:
                    fh.write(comm + "\n")
            make(10, "grim", b"", 9)
            make(11, "bash", b"", 1)
            with mock.patch.object(ad, "_ppid", lambda pid: 9), \
                    mock.patch.object(ad, "_proc_name", lambda pid: "island.py"):
                self.assertEqual(ad.share_owner(proc), "grim (from island.py)")

    def test_nothing_found(self):
        with tempfile.TemporaryDirectory() as proc:
            self.assertEqual(ad.share_owner(proc), "")


if __name__ == "__main__":
    unittest.main()
