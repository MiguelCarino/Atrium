"""A theme's layout (dock.layout= / dock.top_bar=, dock.py THEME LAYOUT):
theme.py checks the keys and writes them to bar.conf; the shipped presets;
and the island with no top bar (island.py effective)."""
import unittest

import helpers

theme = helpers.import_script("theme.py", "theme")
island = helpers.import_script("island.py")


class ThemeKeys(unittest.TestCase):
    def conf(self, **kw):
        return dict(theme.DEFAULTS, id="x", **{k.replace("_", ".", 1): v for k, v in kw.items()})

    def test_bar_conf_carries_them(self):
        text = theme.bar_text(self.conf(dock_layout="taskbar", dock_top_bar="off"))
        self.assertIn("\nlayout=taskbar\n", text)
        self.assertIn("\ntop_bar=off\n", text)
        plain = theme.bar_text(self.conf())
        self.assertIn("\nlayout=\n", plain)
        self.assertIn("\ntop_bar=\n", plain)

    def test_checked(self):
        self.assertEqual(theme.check_layout_keys(self.conf(dock_layout="taskbar", dock_top_bar="off")), [])
        bad = theme.check_layout_keys(self.conf(dock_layout="metro", dock_top_bar="maybe"))
        self.assertTrue(any("dock.layout" in p for p in bad))
        self.assertTrue(any("dock.top_bar" in p for p in bad))

    def test_presets(self):
        for name, want in (("win95", ("taskbar", "off")), ("luna", ("taskbar", "off")),
                           ("orchard", ("dock", "on")), ("orchard-dark", ("dock", "on")),
                           ("cyberpunk", ("", "")), ("matrix", ("", ""))):
            conf = theme.load(name, user=False)
            self.assertEqual((conf.get("dock.layout"), conf.get("dock.top_bar")), want, name)


class IslandWithoutBar(unittest.TestCase):
    def test_effective(self):
        cfg = dict(island.DEFAULTS, match_bar=True)
        self.assertFalse(island.effective(cfg, bar_off=True)["match_bar"])
        self.assertTrue(island.effective(cfg, bar_off=False)["match_bar"])
        self.assertIs(island.effective(dict(cfg, match_bar=False), bar_off=True)["match_bar"], False)
        self.assertTrue(cfg["match_bar"])                       # the settings themselves untouched
        self.assertFalse(island.tucked(island.effective(dict(cfg, enabled=True, media=True), bar_off=True)))



class FontFallback(unittest.TestCase):
    """theme.py font_rules: a theme's face keeps the one it replaces right
    after it, so a face that is not installed falls back to the shipped IBM
    Plex Sans, never to Font Awesome (its letters and ligatures drew words)."""
    def rules(self, swaps, css):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".css", dir=helpers.SCRATCH, delete=False) as fh:
            fh.write(css)
        try:
            return theme.font_rules([fh.name], swaps)
        finally:
            os.unlink(fh.name)

    def test_the_replaced_face_follows(self):
        css = '* { font-family: "IBM Plex Sans", "Font Awesome 6 Free Solid", sans-serif; }'
        got = self.rules([("IBM Plex Sans", "IBM Plex Mono")], css)
        self.assertIn('"IBM Plex Mono", "IBM Plex Sans", "Font Awesome 6 Free Solid"', got)
        listed = self.rules([("IBM Plex Sans", "Selawik, IBM Plex Sans")], css)
        self.assertIn('"Selawik", "IBM Plex Sans", "Font Awesome 6 Free Solid"', listed)   # named once
        self.assertEqual(listed.count("IBM Plex Sans"), 1)


if __name__ == "__main__":
    unittest.main()
