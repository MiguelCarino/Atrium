import unittest

import helpers

sc = helpers.import_script("screen-color.py")


class Kelvin(unittest.TestCase):
    def test_6500_is_exactly_neutral(self):
        self.assertEqual(sc.kelvin_rgb(6500), (1.0, 1.0, 1.0))

    def test_warmer_drops_blue_more_than_green(self):
        r, g, b = sc.kelvin_rgb(3000)
        self.assertEqual(r, 1.0)
        self.assertLess(b, g)
        self.assertLess(g, 1.0)

    def test_never_above_one(self):
        for k in (1000, 2500, 4000, 6000, 6500, 9000):
            self.assertTrue(all(0 <= c <= 1 for c in sc.kelvin_rgb(k)), k)


class Matrix(unittest.TestCase):
    def test_neutral_is_identity(self):
        m = sc.matrix(dict(sc.NEUTRAL), 0)
        self.assertEqual([round(v, 6) for v in m], [1, 0, 0, 0, 1, 0, 0, 0, 1])

    def test_brightness_scales_the_diagonal(self):
        m = sc.matrix(dict(sc.NEUTRAL, brightness=50), 0)
        self.assertAlmostEqual(m[0], 0.5)
        self.assertAlmostEqual(m[4], 0.5)
        self.assertAlmostEqual(m[8], 0.5)

    def test_no_negative_entries(self):
        # the CTM protocol rejects values below 0 (invalid_matrix)
        for sat in (0, 30, 100):
            for night in (0, 2500):
                m = sc.matrix(dict(sc.NEUTRAL, saturation=sat, warmth=3000, red=80), night)
                self.assertTrue(all(v >= 0 for v in m), (sat, night))

    def test_zero_saturation_rows_are_luma(self):
        m = sc.matrix(dict(sc.NEUTRAL, saturation=0), 0)
        for row in range(3):
            self.assertEqual([round(v, 4) for v in m[row * 3:row * 3 + 3]], [round(x, 4) for x in sc.LUMA])

    def test_night_light_multiplies_with_own_warmth(self):
        own = sc.matrix(dict(sc.NEUTRAL, warmth=4000), 0)
        both = sc.matrix(dict(sc.NEUTRAL, warmth=4000), 4000)
        self.assertLess(both[8], own[8])


class Settings(unittest.TestCase):
    def test_layering(self):
        data = {"screens": {"*": {"brightness": 70}, "DP-1": {"warmth": 5000}}, "night": 0}
        dp1 = sc.settings_for(data, "DP-1")
        self.assertEqual((dp1["brightness"], dp1["warmth"]), (70, 5000))
        other = sc.settings_for(data, "HDMI-A-1")
        self.assertEqual((other["brightness"], other["warmth"]), (70, 6500))

    def test_own_beats_all(self):
        data = {"screens": {"*": {"brightness": 70}, "DP-2": {"brightness": 40}}, "night": 0}
        self.assertEqual(sc.settings_for(data, "DP-2")["brightness"], 40)

    def test_state_is_scratch(self):
        self.assertTrue(sc.STATE.startswith(helpers.SCRATCH))


if __name__ == "__main__":
    unittest.main()
