"""The launcher's typed settings: brightness / warmth / saturation per
screen, refresh rates, accent colours. The status they read is stubbed; no
command is run (Items are only built, never activated)."""
import json
import unittest

import helpers

L = helpers.import_script("launcher.py", "launcher")

SCREENS = {
    "screens": [
        {"name": "HDMI-A-1", "description": "NVA Nova P22", "brightness": 100, "warmth": 6500,
         "saturation": 100, "red": 100, "green": 100, "blue": 100},
        {"name": "DP-2", "description": "Orion Electronics ORION WIDE", "brightness": 80, "warmth": 6500,
         "saturation": 100, "red": 100, "green": 100, "blue": 100},
        {"name": "DP-1", "description": "Zenith Corporation Z35", "brightness": 100, "warmth": 5000,
         "saturation": 100, "red": 100, "green": 100, "blue": 100},
    ],
    "all": {"brightness": 100, "warmth": 6500, "saturation": 100, "red": 100, "green": 100, "blue": 100},
    "night": 0, "running": True,
    "ranges": {"brightness": [20, 100], "warmth": [1000, 6500], "saturation": [0, 100],
               "red": [50, 100], "green": [50, 100], "blue": [50, 100]},
}
OUTPUTS = {"outputs": [
    {"name": "DP-2", "description": "Orion Electronics ORION WIDE", "rate": "144.00",
     "rates": ["144.00", "120.00", "119.88", "59.94"]},
    {"name": "DP-1", "description": "Zenith Corporation Z35", "rate": "180.00",
     "rates": ["180.00", "144.00", "60.00"]},
]}


def names(items):
    return [i.name for i in items]


class Screens(unittest.TestCase):
    def setUp(self):
        self._status = L.screen_status
        L.screen_status = lambda: json.loads(json.dumps(SCREENS))

    def tearDown(self):
        L.screen_status = self._status

    def test_value_for_all(self):
        self.assertEqual(names(L.screen_items("brightness 70")), ["Brightness  70%  (all screens)"])

    def test_screen_by_connector_and_brand(self):
        self.assertEqual(names(L.screen_items("brightness hdmi 60")), ["Brightness  60%  (HDMI-A-1)"])
        self.assertEqual(names(L.screen_items("saturation 50 zenith")), ["Saturation  50%  (DP-1)"])

    def test_value_and_screen_in_either_order(self):
        self.assertEqual(names(L.screen_items("warmth orion 4000")), names(L.screen_items("warmth 4000 orion")))

    def test_dim_is_30_below_now(self):
        self.assertEqual(names(L.screen_items("dim dp-2")), ["Brightness  50%  (DP-2)"])

    def test_clamped_to_range(self):
        self.assertEqual(names(L.screen_items("brightness 5")), ["Brightness  20%  (all screens)"])

    def test_relative(self):
        self.assertEqual(names(L.screen_items("brightness dp-2 up")), ["Brightness  90%  (DP-2)"])

    def test_word_alone_offers_picks_but_not_now(self):
        got = names(L.screen_items("warmth zenith"))
        self.assertIn("Warmth  6500K  (DP-1)", got)
        self.assertNotIn("Warmth  5000K  (DP-1)", got)

    def test_unknown_or_ambiguous_screen_is_nothing(self):
        self.assertEqual(L.screen_items("brightness foo"), [])
        self.assertEqual(L.screen_items("brightness dp"), [])      # DP-1 and DP-2

    def test_not_a_setting(self):
        self.assertEqual(L.screen_items("firefox"), [])


class Rates(unittest.TestCase):
    def setUp(self):
        self._run = L.run_quiet
        L.run_quiet = lambda argv, timeout=2: json.dumps(OUTPUTS)

    def tearDown(self):
        L.run_quiet = self._run

    def test_every_screen_now(self):
        self.assertEqual(names(L.rate_items("rate")), ["DP-2  144 Hz  (now)", "DP-1  180 Hz  (now)"])

    def test_one_screen_lists_its_rates(self):
        self.assertEqual(names(L.rate_items("rate dp-2")),
                         ["DP-2  144 Hz  (now)", "DP-2  120 Hz", "DP-2  119.88 Hz", "DP-2  59.94 Hz"])

    def test_straight_to_a_rate(self):
        self.assertEqual(names(L.rate_items("refresh rate zenith 144")), ["DP-1  144 Hz"])

    def test_current_rate_has_no_action(self):
        now = L.rate_items("rate dp-1 180")[0]
        self.assertIsNone(now._run)

    def test_unknown_screen(self):
        self.assertEqual(L.rate_items("rate foo"), [])


class Accent(unittest.TestCase):
    def test_hex_with_and_without_hash(self):
        self.assertEqual(names(L.accent_items("accent #ff8800")), ["Accent: #ff8800"])
        self.assertEqual(names(L.accent_items("accent 3ddc68")), ["Accent: #3ddc68"])

    def test_not_a_colour(self):
        self.assertEqual(L.accent_items("accent orange"), [])
        self.assertEqual(L.accent_items("accent #ff88"), [])


class Ask(unittest.TestCase):
    """"?question" asks it. A second def context_items (the project
    contexts') once shadowed the ? mode's, so every question raised and the
    box kept showing what was there before -- the clipboard's suggestion."""

    def test_question_is_the_hero(self):
        items = L.ask_items("How is the weather today")
        self.assertTrue(items[0].name.endswith(": How is the weather today"), items[0].name)
        self.assertIn("about the clipboard", " ".join(i.name for i in items[1:]))

    def test_clip_word_puts_the_clipboard_first(self):
        self.assertIn("about the clipboard", L.ask_items("clip what is this")[0].name)

    def test_names_are_not_shadowed(self):
        import ast
        with open(L.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        self.assertEqual(sorted({n for n in names if names.count(n) > 1}), [])



class PausedTimerTitle(unittest.TestCase):
    """The timers list counts down to when each one rings; a paused alarm
    won't ring, so its title says "paused" instead of a time left."""

    def test_titles(self):
        import time
        now = time.time()
        entries = [{"id": "a", "kind": "timer", "label": "tea", "due": now + 125},
                   {"id": "b", "kind": "alarm", "label": "gym", "due": now + 3600, "paused": True}]
        saved = L.timers
        L.timers = type("T", (), {"running": staticmethod(lambda: entries), "NAMES": saved.NAMES,
                                  "clock": staticmethod(saved.clock), "days_text": staticmethod(saved.days_text),
                                  "describe": staticmethod(lambda t, _n: t["label"]),
                                  "cancel": staticmethod(lambda _i: None)})
        try:
            titles = [i.name for i in L.running_timer_items()]
        finally:
            L.timers = saved
        self.assertTrue(titles[0].startswith("tea  ") and titles[0].endswith(" left"), titles[0])
        self.assertEqual(titles[1], "gym  paused")


if __name__ == "__main__":
    unittest.main()
