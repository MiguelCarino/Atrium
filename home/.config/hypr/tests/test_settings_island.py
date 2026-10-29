"""Settings > Bar & toolbox > Island: the page's pure helpers (the screen
chips, the line under the master switch) and the page itself -- a switch
for the island and for every source, and every control a `island.py set`.

Hermetic: the page is built with its change() stubbed, so no island.py,
systemctl or hyprctl runs; skipped where GTK cannot be imported."""
import unittest

import helpers  # noqa: F401  (scratch XDG dirs, scripts/ on sys.path)


def status(**settings):
    conf = {"enabled": False, "monitor": "", "media": True, "timers": True, "record": True,
            "railguard": True, "notifications": True, "notify": False, "ongoing": False, "style": "notch",
            "match_bar": True}
    conf.update(settings)
    return {"settings": conf, "defaults": dict(conf), "service": "inactive", "enabled_unit": False,
            "running": False, "monitors": ["DP-1", "DP-2"], "sock": "/run/x/island.sock"}


class PageHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")           # settings.py does this before any page loads
            gi.require_version("Gdk", "3.0")
            from settings_pages import island as page            # needs GTK, not a display
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.island not importable: {exc}")
        cls.page = page

    def test_page_is_a_tab_of_the_bar(self):
        meta = self.page.PAGE
        self.assertEqual((meta["id"], meta["parent"], meta["tab"], meta["group"]), ("island", "bar", "Island", "Look"))
        self.assertTrue(meta["keywords"])
        for word in ("clock", "dnd", "hdr"):        # other pages' words (test_settings_search)
            self.assertNotIn(word, meta["keywords"])

    def test_screen_choices(self):
        self.assertEqual(self.page.screen_choices(status()),
                         [("", "Main screen"), ("focused", "Focused screen"), ("DP-1", "DP-1"), ("DP-2", "DP-2")])
        unplugged = self.page.screen_choices(status(monitor="HDMI-A-1"))
        self.assertEqual(unplugged[-1][0], "HDMI-A-1")              # the lit chip is always there
        self.assertIn("not connected", unplugged[-1][1])
        self.assertEqual(len(self.page.screen_choices(status(monitor="focused"))), 4)
        self.assertEqual(self.page.screen_choices({"settings": {}})[:2],
                         [("", "Main screen"), ("focused", "Focused screen")])

    def test_now_text(self):
        self.assertEqual(self.page.now_text(status()), "Off")
        on = dict(status(enabled=True), service="active")
        self.assertEqual(self.page.now_text(on), "On, on the main screen")
        self.assertEqual(self.page.now_text(dict(status(enabled=True, monitor="DP-1"), service="active")),
                         "On, on DP-1")
        self.assertEqual(self.page.now_text(dict(status(enabled=True, monitor="focused"), service="active")),
                         "On, following the focused screen")
        self.assertEqual(self.page.now_text(status(enabled=True)),
                         "On but not running: systemctl --user status island")

    def build(self):
        try:
            p = self.page.Page()
        except Exception as exc:                                    # noqa: BLE001
            self.skipTest(f"page not buildable here: {exc}")
        ran = []
        p.change = lambda *cmd, **_kw: (ran.append(cmd), True)[1]  # never a real island.py
        return p, ran

    def test_switches_for_everything(self):
        p, _ran = self.build()
        want = {"enabled", "ongoing", "match_bar"} | {key for key, *_ in self.page.SOURCES}
        self.assertEqual(set(p.switches), want)
        self.assertEqual({key for key, *_ in self.page.SOURCES},
                         {"media", "timers", "record", "railguard", "notifications", "notify"})

    def test_controls_run_island_set(self):
        p, ran = self.build()
        p.show(status(media=False))
        self.assertFalse(ran)                                       # drawing changes nothing
        self.assertFalse(p.switches["media"].get_active())
        self.assertTrue(p.switches["timers"].get_active())
        p.flip("notify", True)
        p.flip("enabled", False)
        p.screen.on_pick("focused")
        p.screen.on_pick("")
        self.assertEqual(ran, [(self.page.ISLAND, "set", "notify", "on"),
                               (self.page.ISLAND, "set", "enabled", "off"),
                               (self.page.ISLAND, "set", "monitor", "focused"),
                               (self.page.ISLAND, "set", "monitor", "auto")])

    def test_short_line_only_without_notifications(self):
        p, _ran = self.build()
        p.show(status())
        self.assertFalse(p.switches["notify"].get_sensitive())     # the island has them all
        self.assertTrue(p.switches["notifications"].get_active())   # on by default
        p.show(status(notifications=False))
        self.assertTrue(p.switches["notify"].get_sensitive())

    def test_popups_text(self):
        f = self.page.popups_text
        self.assertIn("in the island", f(dict(status(enabled=True), popups="island")))
        self.assertIn("has not taken", f(dict(status(enabled=True), service="active", popups="mako")))
        self.assertEqual(f(dict(status(notifications=False, enabled=True), service="active", popups="mako")),
                         "Notifications: mako's popups")
        self.assertEqual(f(status()), "Notifications: mako's popups")

    def test_not_running_row(self):
        p, ran = self.build()
        p.show(status(enabled=True))
        self.assertTrue(p.not_running.get_visible())
        p.show(dict(status(enabled=True), service="active"))
        self.assertFalse(p.not_running.get_visible())
        p.show(status())
        self.assertFalse(p.not_running.get_visible())


if __name__ == "__main__":
    unittest.main()
