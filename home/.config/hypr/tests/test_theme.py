import unittest

import helpers

theme = helpers.import_script("theme.py", "theme")

# Hand-made confs, so the tests do not move when a theme file is edited.
DARK = {"id": "t", "glass": "60", "glass_default": "10",
        "term.background": "#000000", "term.foreground": "#3ddc68",
        "term.normal": "#000000 #e05050 #3ddc68 #d0d050 #5080e0 #c060c0 #50c0c0 #c0c0c0",
        "cosmic.background": "#000000", "cosmic.foreground": "#c8d4cb", "accent": "#3ddc68"}
LIGHT = dict(DARK, **{"cosmic.background": "#acacac", "cosmic.foreground": "#000000", "accent": "#000080"})


class Colour(unittest.TestCase):
    def test_contrast_extremes(self):
        self.assertAlmostEqual(theme.contrast([0, 0, 0], [1, 1, 1]), 21.0, places=1)
        self.assertAlmostEqual(theme.contrast([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]), 1.0)

    def test_contrast_is_symmetric(self):
        a, b = theme.hex_rgb("#3ddc68"), theme.hex_rgb("#202020")
        self.assertAlmostEqual(theme.contrast(a, b), theme.contrast(b, a))

    def test_mix(self):
        self.assertEqual(theme.mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(theme.mix("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(theme.mix("#000000", "#ffffff", 0.5), "#808080")

    def test_on_colour(self):
        self.assertEqual(theme.on_colour("#ffff00"), "#000000")
        self.assertEqual(theme.on_colour("#000080"), "#ffffff")


class Glass(unittest.TestCase):
    def test_readable_glass_reads_well(self):
        g = theme.readable_glass(DARK)
        self.assertLessEqual(g, 60)
        text, _ = theme.worst_case(DARK, g)
        self.assertGreaterEqual(text, theme.READABLE_TEXT)

    def test_readable_glass_is_the_most(self):
        g = theme.readable_glass(DARK)
        if g < 60:
            text, dimmest = theme.worst_case(DARK, g + 1)
            _, opaque = theme.worst_case(DARK, 0)
            need = min(theme.READABLE_COLOURS, opaque)
            self.assertTrue(text < theme.READABLE_TEXT or dimmest < need - 0.05)

    def test_already_readable_is_kept(self):
        conf = dict(DARK, glass="0")
        self.assertEqual(theme.readable_glass(conf), 0)


class Apps(unittest.TestCase):
    def test_app_colours(self):
        col = theme.app_colours(DARK)
        self.assertEqual((col["bg"], col["fg"], col["accent"], col["light"]),
                         ("#000000", "#c8d4cb", "#3ddc68", False))
        self.assertTrue(theme.app_colours(LIGHT)["light"])
        self.assertEqual(theme.app_colours(DARK, "#ff8800")["accent"], "#ff8800")

    def test_qt_scheme_has_21_roles_per_group(self):
        text = theme.qt_text(theme.app_colours(DARK))
        for group in ("active_colors", "disabled_colors", "inactive_colors"):
            line = next(l for l in text.splitlines() if l.startswith(group + "="))
            roles = line.split("=", 1)[1].split(", ")
            self.assertEqual(len(roles), 21, group)
            self.assertTrue(all(r.startswith("#ff") and len(r) == 9 for r in roles))
        self.assertIn("[ColorScheme]", text)
        self.assertIn(theme.MARK, text)

    def test_qt_highlight_is_the_accent(self):
        text = theme.qt_text(theme.app_colours(DARK, "#ff8800"))
        active = text.split("active_colors=")[1].splitlines()[0].split(", ")
        self.assertEqual(active[12], "#ffff8800")

    def test_firefox_css(self):
        css = theme.firefox_text(theme.app_colours(LIGHT))
        self.assertIn("--toolbar-field-focus-border-color: #000080 !important;", css)
        self.assertIn(":root, #navigator-toolbox {", css)
        self.assertEqual(css.count("{"), css.count("}"))


if __name__ == "__main__":
    unittest.main()
