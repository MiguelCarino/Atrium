"""Settings > Bar & toolbox > Dock & taskbar: the page's pure helpers (the
line under the master switch, the icon-size chips, the pinned rows) and the
page itself -- a switch for every on / off key, and every control a
`dock.py set / move / unpin`.

Hermetic: the page is built with its change() stubbed, so no dock.py,
systemctl or hyprctl runs; skipped where GTK cannot be imported."""
import unittest

import helpers  # noqa: F401  (scratch XDG dirs, scripts/ on sys.path)


def status(**settings):
    conf = {"enabled": False, "layout": "dock", "position": "bottom", "autohide": "never", "icon_size": 48,
            "monitors": "main", "combine": True, "labels": True, "tray": True, "clock": True, "previews": True,
            "magnify": "theme", "pinned": ["kitty.desktop", "gone.desktop"]}
    conf.update(settings)
    return {"settings": conf, "defaults": dict(conf), "service": "inactive", "enabled_unit": False,
            "running": False, "monitors": ["DP-1", "DP-2"], "file": "/x/dock.json",
            "pinned_apps": [{"id": "kitty.desktop", "name": "kitty", "installed": True},
                            {"id": "gone.desktop", "name": "gone", "installed": False}]}


class PageHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import dock as page
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.dock not importable: {exc}")
        cls.page = page

    def test_page_is_a_tab_of_the_bar(self):
        meta = self.page.PAGE
        self.assertEqual((meta["id"], meta["parent"], meta["tab"], meta["group"]),
                         ("dock", "bar", "Dock & taskbar", "Look"))
        for word in ("clock", "dnd", "hdr", "dynamic island"):     # other pages' words
            self.assertNotIn(word, meta["keywords"])

    def test_found_by_search(self):
        from settings_pages import _catalog as C
        pages = C.read_pages()
        for words in ("taskbar", "dock", "system tray", "pinned apps", "no top bar", "disable top bar"):
            self.assertEqual(C.resolve(pages, words), "dock", words)
        self.assertEqual(C.host_of(pages, "dock"), "bar")

    def test_now_text(self):
        self.assertEqual(self.page.now_text(status()), "Off")
        self.assertEqual(self.page.now_text(dict(status(enabled=True), service="active")),
                         "On: a dock, on the main screen")
        self.assertEqual(self.page.now_text(dict(status(enabled=True, layout="taskbar", monitors="all"),
                                                 service="active")), "On: a taskbar, on every screen")
        self.assertIn("not running", self.page.now_text(status(enabled=True)))
        self.assertEqual(self.page.now_text(dict(status(enabled=True, top_bar=False), service="active")),
                         "On: a dock, on the main screen; no top bar")

    def test_modes(self):
        off, dock, task = status(), status(enabled=True), status(enabled=True, layout="taskbar")
        self.assertEqual([self.page.mode_of(x["settings"]) for x in (off, dock, task)],
                         ["none", "dock", "taskbar"])
        mc = self.page.mode_commands
        self.assertEqual(mc("dock", off["settings"]), [("set", "on")])
        self.assertEqual(mc("taskbar", off["settings"]), [("set", "layout", "taskbar"), ("set", "on")])
        self.assertEqual(mc("taskbar", dock["settings"]), [("set", "layout", "taskbar")])
        self.assertEqual(mc("none", task["settings"]), [("set", "off")])
        self.assertEqual(mc("dock", dock["settings"]), [])
        self.assertEqual(mc("none", off["settings"]), [])

    def test_size_choices(self):
        self.assertIn(("48", "48 px"), self.page.size_choices(48))
        self.assertIn(("44", "44 px"), self.page.size_choices(44))     # the lit chip is always there

    def test_pinned_rows(self):
        rows = self.page.pinned_rows(status())
        self.assertEqual(rows[0], ("kitty.desktop", "kitty", True, False))
        self.assertIn("not installed", rows[1][1])
        self.assertTrue(rows[1][3])
        self.assertEqual(self.page.pinned_rows({}), [])

    def build(self):
        try:
            p = self.page.Page()
        except Exception as exc:                                    # noqa: BLE001
            self.skipTest(f"page not buildable here: {exc}")
        ran = []
        p.change = lambda *cmd, **_kw: (ran.append(cmd), True)[1]  # never a real dock.py
        return p, ran

    def test_switches_for_everything(self):
        p, _ran = self.build()
        self.assertEqual(set(p.switches), {"previews", "top_bar"} | {k for k, *_ in self.page.TASKBAR})

    def test_controls_run_dock_set(self):
        p, ran = self.build()
        p.show(status(layout="taskbar"))                            # off: both sections dim
        self.assertFalse(p.dock_box.get_sensitive() or p.task_box.get_sensitive())
        self.assertFalse(p.top_bar.get_sensitive())                 # the bar can only go with one of them
        p.show(status(enabled=True, layout="taskbar"))
        self.assertFalse(ran)                                       # drawing changes nothing
        self.assertFalse(p.dock_box.get_sensitive())
        self.assertTrue(p.task_box.get_sensitive())
        self.assertTrue(p.top_bar.get_sensitive())
        p.switches["top_bar"].set_state(False)
        p.switches["top_bar"].emit("state-set", False)
        self.assertEqual(ran[-1][1:], ("set", "top_bar", "off"))
        p.switches["combine"].set_state(False)
        p.switches["combine"].emit("state-set", False)
        self.assertEqual(ran[-1][1:], ("set", "combine", "off"))
        many = []
        p.change_all = lambda cmds, **_kw: (many.append(cmds), True)[1]
        p.mode.on_pick("dock")
        self.assertEqual([c[1:] for c in many[-1]], [("set", "layout", "dock")])
        p.mode.on_pick("taskbar")                                   # the lit one: nothing
        self.assertEqual(len(many), 1)
        p.mode.on_pick("none")
        self.assertEqual([c[1:] for c in many[-1]], [("set", "off")])
        p.size.on_pick("64")
        self.assertEqual(ran[-1][1:], ("set", "icon_size", "64"))
        p.magnify.on_pick("off")
        self.assertEqual(ran[-1][1:], ("set", "magnify", "off"))
        self.assertEqual(len(p.pinned.get_children()), 2)


if __name__ == "__main__":
    unittest.main()
