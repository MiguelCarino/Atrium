"""Settings > Screen time (settings_pages/screentime.py): the pure helpers
behind its bars and lines. Needs GTK to import, not a display."""
import unittest

import helpers  # noqa: F401  (scratch XDG dirs, scripts on sys.path)

try:
    from settings_pages import screentime as page
except Exception:                                        # noqa: BLE001
    page = None


@unittest.skipIf(page is None, "settings_pages.screentime not importable")
class ScreenTimePage(unittest.TestCase):
    def test_scale(self):
        self.assertEqual(page.scale([0, 50, 100], 80), [0, 40, 80])
        self.assertEqual(page.scale([0, 0], 80), [0, 0])
        self.assertEqual(page.scale([1, 10000], 50), [1, 50])          # tiny but there: 1 px
        self.assertEqual(page.scale([], 50), [])

    def test_week_labels(self):
        self.assertEqual(page.week_labels([("2026-10-26", 0), ("2026-11-01", 5), ("bad", 0)]), ["Mon", "Sun", "?"])

    def test_choices_keeps_a_custom_value(self):
        self.assertEqual(page.choices(page.LENGTH, 5), page.LENGTH)
        self.assertEqual(page.choices(page.LENGTH, 7)[-1], ("7", "7 min"))

    def test_hm(self):
        self.assertEqual(page.hm(0), "0 min")
        self.assertEqual(page.hm(3700), "1 h 01")

    def test_counting_text(self):
        base = {"conf": {"count": "on"}, "service": "active"}
        self.assertIn("off", page.counting_text({"conf": {"count": "off"}}))
        self.assertIn("service is failed", page.counting_text(dict(base, service="failed")))
        self.assertIn("keyboard or mouse", page.counting_text(dict(base, idle_source="hypridle")))
        self.assertIn("only the lock", page.counting_text(dict(base, idle_source="lock only")))

    def test_live_text(self):
        self.assertEqual(page.live_text(None), "")
        text = page.live_text({"idle": False, "locked": False, "streak_s": 1800, "next_break_s": 1200})
        self.assertEqual(text, "now active  ·  30 min since your last break  ·  reminder in 20 min")
        self.assertTrue(page.live_text({"idle": True, "streak_s": 0, "next_break_s": 5}).startswith("now away"))


if __name__ == "__main__":
    unittest.main()
