"""capture-settings.py (Settings > Screenshots & recording): the key=value
file, the checks a value has to pass, the "Look it up" address, and the
page's small helpers. Everything writes into helpers.py's scratch
XDG_STATE_HOME; nothing runs hyprctl, record.sh or a recorder."""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import helpers

cap = helpers.import_script("capture-settings.py")


class Check(unittest.TestCase):
    def test_choices(self):
        self.assertEqual(cap.check("shot_format", " webp "), "webp")
        with self.assertRaises(ValueError):
            cap.check("shot_format", "gif")
        with self.assertRaises(ValueError):
            cap.check("replay_seconds", "45")
        with self.assertRaises(ValueError):
            cap.check("no_such_key", "on")

    def test_folders_keep_tilde_under_home(self):
        home = os.path.expanduser("~")
        self.assertEqual(cap.check("shot_dir", home + "/Pictures/Shots"), "~/Pictures/Shots")
        self.assertEqual(cap.check("rec_dir", "~/Videos/x/../Clips"), "~/Videos/Clips")
        self.assertEqual(cap.check("rec_dir", "/mnt/media/Clips"), "/mnt/media/Clips")
        with self.assertRaises(ValueError):
            cap.check("shot_dir", "")

    def test_folder_that_is_a_file(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises(ValueError):
                cap.check("shot_dir", f.name)

    def test_ocr_langs(self):
        self.assertEqual(cap.check("ocr_langs", "spa, eng spa"), "spa+eng")
        self.assertEqual(cap.check("ocr_langs", "chi_sim+eng"), "chi_sim+eng")
        for bad in ("", "+", "eng;rm"):
            with self.assertRaises(ValueError):
                cap.check("ocr_langs", bad)


class File(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(helpers.SCRATCH, "capture-test.conf")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_round_trip_keeps_only_known_keys_in_order(self):
        cap.write_kv({"search": "kagi", "stray": "x", "shot_copy": "off"}, self.path)
        with open(self.path) as f:
            lines = [l for l in f.read().splitlines() if not l.startswith("#")]
        self.assertEqual(lines, ["shot_copy=off", "search=kagi"])
        self.assertEqual(cap.read_kv(self.path), {"shot_copy": "off", "search": "kagi"})

    def test_read_kv_like_lua(self):
        with open(self.path, "w") as f:
            f.write("# c\n  shot_format = jpg  \nnot a line\ngamemode_blur=off\n")
        self.assertEqual(cap.read_kv(self.path), {"shot_format": "jpg", "gamemode_blur": "off"})

    def test_missing_file_is_empty(self):
        self.assertEqual(cap.read_kv(self.path), {})

    def test_values_refuse_bad_hand_edits(self):
        vals, bad = cap.values({"search": "nope", "rec_fps": "120", "ocr_langs": "eng;x"})
        self.assertEqual(vals["search"], "duckduckgo")
        self.assertEqual(vals["rec_fps"], "120")
        self.assertEqual(vals["ocr_langs"], "eng+spa")
        self.assertEqual(sorted(bad), ["ocr_langs", "search"])
        self.assertEqual(vals["gamemode_rounding"], "on")      # missing = default = old behaviour


class Commands(unittest.TestCase):
    def setUp(self):
        if os.path.exists(cap.CONF):
            os.remove(cap.CONF)

    def call(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            cap.main(list(argv))
        return out.getvalue().splitlines()

    def test_set_get_reset(self):
        self.assertTrue(cap.CONF.startswith(helpers.SCRATCH))   # never the real file
        self.call("set", "replay_seconds", "120")
        self.call("set", "shot_dir", "~/Pics")
        self.assertEqual(self.call("get", "replay_seconds", "shot_dir"),
                         ["120", os.path.expanduser("~/Pics")])
        self.call("reset", "replay_seconds")
        self.assertEqual(self.call("get", "replay_seconds"), ["30"])
        self.assertEqual(cap.read_kv(), {"shot_dir": "~/Pics"})

    def test_set_refused(self):
        with self.assertRaises(SystemExit) as cm:
            self.call("set", "rec_audio", "loud")
        self.assertIn("rec_audio is one of", str(cm.exception.code))
        self.assertFalse(os.path.exists(cap.CONF))


class Small(unittest.TestCase):
    def test_search_url(self):
        self.assertEqual(cap.search_url("  two\nwords ", "google"), "https://www.google.com/search?q=two%20words")
        self.assertTrue(cap.search_url("a&b", "unknown").startswith("https://duckduckgo.com/?q=a%26b"))

    def test_gamemode_on(self):
        self.assertTrue(cap.gamemode_on({"bool": False}))
        self.assertFalse(cap.gamemode_on({"int": 1}))
        self.assertIsNone(cap.gamemode_on({}))

    def test_shot_binds_follow(self):
        with tempfile.NamedTemporaryFile("w", suffix=".lua") as f:
            f.write('exec_cmd("hyprshot -m output -o " .. scrDir)\n')
            f.flush()
            self.assertFalse(cap.shot_binds_follow(f.name))
            f.write("screenshot.sh output\nscreenshot.sh region\nscreenshot.sh window\n")
            f.flush()
            self.assertTrue(cap.shot_binds_follow(f.name))
        self.assertFalse(cap.shot_binds_follow("/nonexistent/binds.lua"))


class PageHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import capture as page            # needs GTK, not a display
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.capture not importable: {exc}")
        cls.page = page

    def test_page_literal(self):
        self.assertEqual((self.page.PAGE["id"], self.page.PAGE["group"], self.page.PAGE["order"]),
                         ("capture", "Apps", 30))

    def test_seconds_and_ram(self):
        self.assertEqual([self.page.seconds_text(s) for s in ("15", "60", "90", "300")],
                         ["15 s", "1 min", "1 min 30 s", "5 min"])
        self.assertEqual(self.page.replay_ram(30), "about 300 MB")
        self.assertEqual(self.page.replay_ram(300), "about 3.0 GB")

    def test_toggle_lang_never_empties(self):
        self.assertEqual(self.page.toggle_lang("eng+spa", "spa"), "eng")
        self.assertEqual(self.page.toggle_lang("eng", "eng"), "eng")
        self.assertEqual(self.page.toggle_lang("eng", "jpn"), "eng+jpn")

    def test_profile_sub(self):
        self.assertEqual(self.page.profile_sub({}), "empty profile")
        self.assertEqual(self.page.profile_sub({"monitor": "DP-1", "rates": {"DP-1": "144.0"}, "volume": 40}),
                         "on DP-1  ·  DP-1 144 Hz  ·  volume 40 %")

    def test_forget_asks_first(self):
        """Forget only marks the profile; the command runs on "Yes, forget it"."""
        from gi.repository import Gtk
        if not Gtk.init_check(None)[0]:
            self.skipTest("no display for widgets")
        p = self.page.Page()
        p.data = {"profiles": {"123": {"name": "A game", "volume": 40}}}
        ran = []
        p.do = lambda *cmd, **_kw: ran.append(cmd)
        p.ask_forget("123")
        self.assertEqual((p.forgetting, ran), ("123", []))
        p.ask_forget(None)
        self.assertEqual((p.forgetting, ran), (None, []))
        p.ask_forget("123")
        p.forget("123")
        self.assertEqual((p.forgetting, ran), (None, [(self.page.GAMES, "forget", "123")]))


if __name__ == "__main__":
    unittest.main()
