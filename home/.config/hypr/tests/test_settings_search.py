"""Searching the Settings pages: settings_pages/_catalog.py (the rules the
window's search box, `settings.py --list` / `settings.py <words>` and the
launcher's "Settings: <page>" items share), and the launcher's settings
items, its volume cap and its Bluetooth / Wi-Fi switch. Pages are read from
source text only; no GTK window is built and no command is run (the
launcher's spawn is stubbed and Items are never activated)."""
import json
import os
import re
import tempfile
import unittest

import helpers

from settings_pages import _catalog as C

L = helpers.import_script("launcher.py", "launcher")

PAGES = [
    {"id": "sound", "title": "Sound", "group": "Hardware", "order": 10,
     "keywords": ["audio", "sonido", "volume", "over-amplification"]},
    {"id": "network", "title": "Network & Bluetooth", "group": "Hardware", "order": 20,
     "keywords": ["wifi", "ip address", "airplane mode"]},
    {"id": "input", "title": "Keyboard, mouse & touchpad", "group": "Hardware", "order": 30,
     "keywords": ["tap to click", "layout", "teclado"]},
    {"id": "notifications", "title": "Notifications", "group": "System", "order": 20,
     "keywords": ["do not disturb", "notification sound"]},
    {"id": "region", "title": "Date, time & region", "group": "System", "order": 40,
     "keywords": ["time zone", "día"]},
]


def ids(pages):
    return [p["id"] for p in pages]


class Words(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(C.fold("Wi-Fi"), "wifi")
        self.assertEqual(C.fold("Día"), "dia")
        self.assertEqual(C.words("Keyboard, mouse & touchpad"), ["keyboard", "mouse", "touchpad"])


class Search(unittest.TestCase):
    def test_title_and_keywords(self):
        self.assertEqual(ids(C.search(PAGES, "blue")), ["network"])
        self.assertEqual(ids(C.search(PAGES, "tap to click")), ["input"])
        self.assertEqual(ids(C.search(PAGES, "WI-FI")), ["network"])
        self.assertEqual(ids(C.search(PAGES, "dia")), ["region"])

    def test_title_beats_keyword(self):
        # "notification sound" is a keyword of Notifications; Sound is the title.
        self.assertEqual(ids(C.search(PAGES, "sound")), ["sound", "notifications"])

    def test_every_word_must_match(self):
        self.assertEqual(C.search(PAGES, "sound zebra"), [])
        self.assertEqual(C.search(PAGES, "nothing like it"), [])

    def test_empty_query_scores_all(self):
        self.assertEqual(len(C.search(PAGES, "")), len(PAGES))

    def test_hint_only_when_title_does_not_say_it(self):
        self.assertEqual(C.hint(PAGES[2], "tap"), "tap to click")
        self.assertEqual(C.hint(PAGES[1], "bluetooth"), "")

    def test_resolve(self):
        self.assertEqual(C.resolve(PAGES, "region"), "region")
        self.assertEqual(C.resolve(PAGES, "time zone"), "region")
        self.assertIsNone(C.resolve(PAGES, "zebra"))
        self.assertIsNone(C.resolve(PAGES, ""))

    def test_sort_key_groups_then_order(self):
        pages = sorted(PAGES, key=C.sort_key, reverse=True)
        self.assertEqual(ids(sorted(pages, key=C.sort_key)), ["sound", "network", "input", "notifications", "region"])


class ReadingSources(unittest.TestCase):
    def test_page_of_multiline_literal(self):
        src = ('import os\n'
               'PAGE = {"id": "x", "title": "X", "group": "Look",\n'
               '        "keywords": ["one", "two"]}\n'
               'class Page: pass\n')
        self.assertEqual(C.page_of(src)["keywords"], ["one", "two"])

    def test_page_of_not_literal_or_missing(self):
        self.assertIsNone(C.page_of('PAGE = {"id": NAME, "title": "X"}\n'))
        self.assertIsNone(C.page_of('print("no page")\n'))
        self.assertIsNone(C.page_of('PAGE = {"title": "no id"}\n'))

    def test_read_pages_skips_helpers_and_rereads_on_change(self):
        with tempfile.TemporaryDirectory() as folder:
            def write(name, text):
                with open(os.path.join(folder, name), "w") as handle:
                    handle.write(text)
            write("common.py", 'PAGE = {"id": "no", "title": "No"}\n')
            write("_private.py", 'PAGE = {"id": "no2", "title": "No"}\n')
            write("a.py", 'PAGE = {"id": "a", "title": "A", "group": "System"}\n')
            self.assertEqual(ids(C.read_pages(folder, builtin=False)), ["a"])
            write("a.py", 'PAGE = {"id": "a", "title": "Renamed", "group": "System"}\n')
            os.utime(os.path.join(folder, "a.py"), ns=(1, 1))     # a different mtime for sure
            self.assertEqual(C.read_pages(folder, builtin=False)[0]["title"], "Renamed")

    def test_real_pages_are_literal_and_have_keywords(self):
        """Every page in settings_pages/ is readable from source (the launcher
        depends on it) and declares keywords; ids are unique."""
        pages = C.read_pages()
        folder = os.path.join(helpers.SCRIPTS, "settings_pages")
        files = [n for n in os.listdir(folder) if n.endswith(".py") and not n.startswith("_") and n != "common.py"]
        self.assertEqual(len(pages), len(files) + len(C.BUILTIN))
        self.assertEqual(len(set(ids(pages))), len(pages))
        for page in pages:
            self.assertIn(page.get("group"), C.GROUPS, page["id"])
        # "keywords" is optional in the contract (common.py), but every page
        # declares them -- a page nobody can search for by what is on it is
        # only found by its title. Keep it that way for new pages too.
        for page in pages:
            self.assertTrue(page.get("keywords"), f"{page['id']} has no keywords")

    def test_real_pages_found_by_their_words(self):
        pages = C.read_pages()
        for words, page in (("bluetooth", "network"), ("tap to click", "input"), ("hdr", "screens"),
                            ("time zone", "region"), ("sonido", "sound"), ("dnd", "notifications"),
                            ("dark mode", "theme"), ("keybinds", "shortcuts")):
            self.assertEqual(C.resolve(pages, words), page, words)

    def test_tabs_follow_their_page(self):
        pages = C.read_pages()
        order = [p["id"] for p in pages]
        self.assertEqual(order[order.index("ai") + 1:order.index("ai") + 3], ["voice", "speech"])
        self.assertEqual(C.host_of(pages, "voice"), "ai")
        self.assertEqual(C.host_of(pages, "ai"), "ai")
        self.assertEqual(C.tabs(pages, "theme")[:2], [("theme", "Theme"), ("ambient", "Ambient")])
        self.assertEqual(C.tabs(pages, "about"), [])
        top = [p for p in pages if not p.get("parent")]
        self.assertLessEqual(len(top), 26)

    def test_a_parent_that_is_gone_makes_an_ordinary_page(self):
        pages = C.arrange([{"id": "a", "title": "A", "group": "Look"},
                           {"id": "b", "title": "B", "group": "Look", "parent": "zzz"}])
        self.assertEqual(C.host_of(pages, "b"), "b")
        self.assertEqual(C.tabs(pages, "a"), [])


class LauncherSettings(unittest.TestCase):
    def setUp(self):
        self.spawned = []
        self._spawn = L.spawn
        L.spawn = lambda argv: self.spawned.append(argv)

    def tearDown(self):
        L.spawn = self._spawn

    def test_one_item_per_matching_page(self):
        items = L.settings_items("tap to click")
        self.assertEqual([i.name for i in items], ["Settings: Keyboard & mouse"])
        self.assertIn("tap to click", items[0].sub)
        items[0].run()
        self.assertEqual(self.spawned, [[L.SETTINGS, "input"]])

    def test_settings_word_lists_every_page(self):
        everything = L.settings_items("settings")
        self.assertEqual(len(everything), len(C.read_pages()))
        self.assertEqual([i.name for i in L.settings_items("ajustes sonido")][:1], ["Settings: Sound"])

    def test_short_or_unknown_words_add_nothing(self):
        self.assertEqual(L.settings_items("s"), [])
        self.assertEqual(L.settings_items("zzqx"), [])

    def test_backend_commands_exist(self):
        """Every script the commands list runs (the Settings backends among
        them, also inside a told() shell line) exists and is executable."""
        found = 0
        for name, _sub, _icon, argv in L.COMMANDS:
            if not isinstance(argv, list):
                continue
            for path in re.findall(re.escape(helpers.SCRIPTS) + r"/[\w.-]+\.(?:py|sh)", " ".join(argv)):
                found += 1
                self.assertTrue(os.access(path, os.X_OK), f"{name}: {path}")
        self.assertGreater(found, 20)

    def test_accessibility_and_backend_entries(self):
        names = [c[0] for c in L.COMMANDS]
        for want in ("Magnifier: zoom in", "Over-amplification: on", "Copy system info", "Web browser",
                     "Window blur on / off", "Bar: load its changes"):
            self.assertIn(want, names)


    def test_window_openers_say_when_they_fail(self):
        """Printers / Online accounts / Change password open a window; when
        accounts.py cannot (GNOME Settings missing) its error line must
        reach a notification, not vanish."""
        by_name = {c[0]: c[3] for c in L.COMMANDS}
        for name in ("Change password", "Printers", "Online accounts"):
            argv = by_name[name]
            self.assertEqual(argv[:2], ["sh", "-c"], name)
            self.assertIn("notify-send", argv[2])
            self.assertIn("accounts.py", argv[2])


class VolumeAndRadio(unittest.TestCase):
    def setUp(self):
        self.state = os.path.join(os.environ["XDG_STATE_HOME"], "hypr", "sound.json")
        os.makedirs(os.path.dirname(self.state), exist_ok=True)
        self.spawned = []
        self._spawn = L.spawn
        L.spawn = lambda argv: self.spawned.append(argv)

    def tearDown(self):
        L.spawn = self._spawn
        if os.path.exists(self.state):
            os.remove(self.state)

    def test_cap_follows_boost(self):
        self.assertEqual(L.volume_cap(), 100)
        with open(self.state, "w") as handle:
            json.dump({"boost": True}, handle)
        self.assertEqual(L.volume_cap(), 150)
        L.set_volume(140)
        self.assertIn("-l 1.5", self.spawned[-1][2])
        self.assertIn("1.40", self.spawned[-1][2])

    def test_without_boost_stops_at_100(self):
        L.set_volume(140)
        self.assertIn("-l 1.0", self.spawned[-1][2])
        self.assertIn(" 1.00", self.spawned[-1][2])

    def test_bluetooth_goes_through_network_settings(self):
        L.radio("bluetooth", False)
        script = self.spawned[-1][2]
        self.assertIn("network-settings.py", script)
        self.assertIn("bt power off", script)
        L.radio("wifi", True)
        self.assertIn("wifi on", self.spawned[-1][2])


if __name__ == "__main__":
    unittest.main()
