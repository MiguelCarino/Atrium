"""welcome.py (the first-login card): the done-marker in the scratch state
folder, the screens' refresh hints from hyprctl's JSON, the model advice
for a card of any vendor / no card, the smart switch's summary, the mic
test's verdict, and the unit's condition. No window is opened."""
import contextlib
import io
import os
import unittest

import helpers

w = helpers.import_script("welcome.py")
UNIT = os.path.expanduser("~/.config/systemd/user/welcome.service")


class Marker(unittest.TestCase):
    def test_done_and_reset(self):
        self.assertTrue(w.MARKER.startswith(helpers.SCRATCH))     # never the real one
        w.reset()
        self.assertFalse(w.is_done())
        self.assertEqual(w.main(["--done"]), 0)
        self.assertTrue(w.is_done())
        self.assertEqual(w.main(["--first-login"]), 0)            # done: returns at once, no window
        w.reset()
        self.assertFalse(w.is_done())

    def test_unknown_argument(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(w.main(["--nope"]), 2)

    def test_unit_waits_for_the_marker(self):
        with open(UNIT) as handle:
            unit = handle.read()
        self.assertIn("ConditionPathExists=!%h/.local/state/hypr/welcome-done", unit)
        self.assertIn("welcome.py --first-login", unit)


class Screens(unittest.TestCase):
    MON = {"name": "DP-1", "width": 3440, "height": 1440, "refreshRate": 143.99, "scale": 1.0,
           "availableModes": ["3440x1440@60.00Hz", "3440x1440@180.00Hz", "3440x1440@144.00Hz",
                              "1920x1080@240.00Hz", "junk"]}

    def test_faster_mode_at_the_same_size(self):
        ((name, line, hint),) = w.screen_lines([self.MON])
        self.assertEqual((name, line), ("DP-1", "3440x1440 at 144 Hz"))
        self.assertEqual(hint, "can run at 180 Hz")       # 240 Hz is another size: not offered

    def test_at_its_best_and_scaled(self):
        mon = dict(self.MON, refreshRate=180.0, scale=1.5)
        ((_name, line, hint),) = w.screen_lines([mon])
        self.assertEqual(line, "3440x1440 at 180 Hz, scale 1.5")
        self.assertEqual(hint, "")

    def test_ntsc_rates_are_not_a_hint(self):
        mon = dict(self.MON, width=1920, height=1080, refreshRate=59.94,
                   availableModes=["1920x1080@60.00Hz", "1920x1080@59.94Hz"])
        self.assertEqual(w.screen_lines([mon])[0][2], "")

    def test_disabled_and_none(self):
        self.assertEqual(w.screen_lines([dict(self.MON, disabled=True)]), [])
        self.assertEqual(w.screen_lines(None), [])


class Advice(unittest.TestCase):
    def test_any_vendor_card(self):
        for name in ("NVIDIA GeForce RTX 4070", "AMD Radeon RX 7800 XT", "Intel Arc A770"):
            text = w.model_advice({"name": name, "vram_total": 16384}, 32 * 2 ** 30)
            self.assertIn(name, text)
            self.assertIn("about 14 GB", text)

    def test_small_card(self):
        self.assertIn("small models", w.model_advice({"name": "GTX 1050", "vram_total": 4096}, 0))

    def test_no_card_or_igpu(self):
        for card in (None, {"name": "Intel UHD", "vram_total": None}):
            text = w.model_advice(card, 16 * 2 ** 30)
            self.assertIn("CPU and RAM (16 GB)", text)


class Smart(unittest.TestCase):
    def test_summary(self):
        ids = w.SMART_SET
        self.assertEqual(w.smart_summary(dict.fromkeys(ids, True)), (True, f"{len(ids)} of {len(ids)} on"))
        self.assertEqual(w.smart_summary(dict.fromkeys(ids, False))[0], False)
        self.assertEqual(w.smart_summary(dict.fromkeys(ids))[0], False)        # nothing answered
        half = {fid: i % 2 == 0 for i, fid in enumerate(ids)}
        self.assertTrue(w.smart_summary(half)[0])

    def test_no_privacy_sensitive_feature_in_the_set(self):
        for fid in ("presence", "gestures", "memory", "voice", "screen-ask", "phone-ask", "machines"):
            self.assertNotIn(fid, w.SMART_SET)

    def test_the_set_exists_in_the_hub(self):
        from settings_pages import _smart
        for fid in w.SMART_SET:
            self.assertIn(fid, _smart.BY_ID)
            self.assertIsNotNone(_smart.BY_ID[fid].get("switch"), fid)


class Mic(unittest.TestCase):
    def test_verdicts(self):
        self.assertIn("Nothing came through", w.mic_verdict(0))
        self.assertIn("too loud", w.mic_verdict(99))
        self.assertIn("Quiet", w.mic_verdict(20))
        self.assertEqual(w.mic_verdict(60), "Sounds right.")


if __name__ == "__main__":
    unittest.main()
