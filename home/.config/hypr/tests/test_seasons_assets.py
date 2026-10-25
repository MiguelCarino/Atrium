"""The seasons theme's generated assets, headlessly: make-seasons-wallpaper.py
(every variant renders, deterministically, keeps the bar's top band dark and
under the PEAK cap, and field() holds a colour under its luminance ceiling)
and make-theme-sounds.py's kalimba recipe (the three events exist, every
note is at or below C5, and the seasons theme has no write() override, so
the other themes' files are untouched). Small frames into memory only: no
file is written, nothing reaches ~/Pictures or the theme folders."""
import re
import unittest

import numpy as np

import helpers

wall = helpers.import_script("make-seasons-wallpaper.py")
sounds = helpers.import_script("make-theme-sounds.py")

W, H = 960, 540             # tall enough that the sky's flat hold is the full 106 px


def wcag(img):
    a = np.asarray(img, np.float32) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722], np.float32), a


class Wallpapers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = {v: wall.render(W, H, v) for v in wall.VARIANTS}

    def test_twelve_three_per_season(self):
        self.assertEqual(len(wall.VARIANTS), 12)
        for s in wall.SEASONS:
            self.assertEqual(sum(v.startswith(s + "-") for v in wall.VARIANTS), 3, s)
        self.assertEqual(set(wall.SCENES), set(wall.VARIANTS))

    def test_top_band_dark(self):
        for v, img in self.frames.items():
            lum, rgb = wcag(img)
            top = slice(0, wall.TOP_BAND)
            self.assertLessEqual(float(lum[top].mean()), 0.03, v)
            self.assertLessEqual(float(rgb[top].max()), 0.27, v)

    def test_peak_and_light_area(self):
        for v, img in self.frames.items():
            lum, rgb = wcag(img)
            self.assertLessEqual(float(rgb.max()), wall.PEAK + 1.5 / 255, v)
            # the light accents together stay a small part of the frame
            self.assertLess(float((lum > 0.5).mean()), 0.06, v)

    def test_deterministic(self):
        again = wall.render(W, H, "winter-snowfall")
        self.assertEqual(again.tobytes(), self.frames["winter-snowfall"].tobytes())

    def test_portrait_renders(self):
        img = wall.render(360, 640, "spring-orchard")
        self.assertEqual(img.size, (360, 640))

    def test_field_cap(self):
        r, g, b, a = wall.field("#ffffff", wall.SNOW_LUM)
        self.assertLessEqual(wall.lum(np.array([r, g, b], np.float32) / 255), wall.SNOW_LUM + 0.01)
        self.assertEqual(wall.field("#101010", wall.SNOW_LUM)[:3], (16, 16, 16))   # dark: unchanged
        self.assertEqual(a, 255)


class Kalimba(unittest.TestCase):
    def test_recipe(self):
        rec = sounds.RECIPES["seasons"]
        self.assertEqual(set(rec), {"notify", "switch", "alarm"})
        self.assertNotIn("seasons", sounds.THEME_WRITE)      # write()'s defaults: no override
        for event, make in rec.items():
            x = make()
            self.assertGreater(len(x), sounds.RATE * 0.5, event)
            self.assertTrue(np.isfinite(x).all(), event)

    def test_notes_at_or_below_c5(self):
        """The recipe's MIDI numbers, read from its source line by line."""
        import inspect
        src = inspect.getsource(sounds)
        block = src[src.index('"seasons": {'):src.index("},", src.index('"seasons": {'))]
        notes = [int(n) for n in re.findall(r"\b(6\d|7\d)\b", block)]
        self.assertTrue(notes)
        self.assertLessEqual(max(notes), 72)

    def test_kalimba_shape(self):
        x = sounds.kalimba(sounds.note(62), 0.5)
        self.assertEqual(len(x), int(sounds.RATE * 0.5))
        self.assertLess(abs(x[-100:]).max(), abs(x).max() * 0.5)      # it decays


if __name__ == "__main__":
    unittest.main()
