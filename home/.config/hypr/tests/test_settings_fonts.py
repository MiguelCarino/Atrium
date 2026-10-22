"""font-settings.py's pure parts (Pango descriptions, Qt font strings, the
ini editor, the fontconfig file, fc-list parsing) and theme.py's user
layer. No gsettings, no files outside the scratch folder, no hyprctl."""
import os
import unittest

import helpers

fs = helpers.import_script("font-settings.py", "font_settings")
theme = helpers.import_script("theme.py", "theme")


class Desc(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(fs.parse_desc("Adwaita Sans 11"), ("Adwaita Sans", "", 11.0))
        self.assertEqual(fs.parse_desc("Cantarell Bold 10.5"), ("Cantarell", "Bold", 10.5))
        self.assertEqual(fs.parse_desc("Font 5, 11"), ("Font 5", "", 11.0))
        self.assertEqual(fs.parse_desc("Inter"), ("Inter", "", None))
        self.assertEqual(fs.parse_desc(""), ("", "", None))

    def test_make_round_trips(self):
        for fam, size in (("Adwaita Sans", 11), ("Font 5", 12), ("Noto Sans Black", 9.5)):
            desc = fs.make_desc(fam, size)
            got = fs.parse_desc(desc)
            self.assertEqual((got[0], got[2]), (fam, float(size)), desc)

    def test_make_plain(self):
        self.assertEqual(fs.make_desc("Inter", 11.0), "Inter 11")
        self.assertEqual(fs.make_desc("Cantarell", 10, "Bold"), "Cantarell, Bold 10")


class Qt(unittest.TestCase):
    def test_strings(self):
        self.assertEqual(fs.qt_font("Inter", 11, 5), '"Inter,11,-1,5,50,0,0,0,0,0"')
        self.assertEqual(fs.qt_font("Inter", 13.76, 6), '"Inter,14,-1,5,400,0,0,0,0,0,0,0,0,0,0,1"')
        self.assertEqual(fs.parse_qt_font(fs.qt_font("Fira Code", 10.5, 6)), ("Fira Code", 10.5))
        self.assertIsNone(fs.parse_qt_font(None))

    def test_ini_set_adds_and_removes(self):
        base = "[Appearance]\nstyle=Fusion\n"
        one = fs.ini_set(base, "Fonts", "general", '"A,11"')
        self.assertIn("[Fonts]\ngeneral=\"A,11\"", one)
        self.assertEqual(fs.ini_get(one, "Fonts", "general"), '"A,11"')
        self.assertEqual(fs.ini_get(one, "Appearance", "style"), "Fusion")
        two = fs.ini_set(one, "Fonts", "general", '"B,12"')
        self.assertEqual(two.count("general="), 1)
        self.assertEqual(fs.ini_get(two, "Fonts", "general"), '"B,12"')
        gone = fs.ini_set(two, "Fonts", "general", None)
        self.assertNotIn("[Fonts]", gone)
        self.assertEqual(gone.strip(), base.strip())

    def test_ini_section_in_the_middle(self):
        text = "[A]\nx=1\n\n[Fonts]\nfixed=f\n\n[B]\ny=2"
        out = fs.ini_set(text, "Fonts", "general", "g")
        self.assertEqual(fs.ini_get(out, "Fonts", "general"), "g")
        self.assertEqual(fs.ini_get(out, "B", "y"), "2")
        out = fs.ini_set(fs.ini_set(out, "Fonts", "general", None), "Fonts", "fixed", None)
        self.assertNotIn("Fonts", out)
        self.assertEqual(fs.ini_get(out, "B", "y"), "2")
        self.assertEqual(fs.ini_set(text, "Nope", "k", None), text)


class Fontconfig(unittest.TestCase):
    def test_round_trip(self):
        aliases = {"sans-serif": "Inter", "monospace": "Fira Code", "serif": "A & B"}
        text = fs.fontconfig_text(aliases, ("rgba", "full", "bgr"))
        self.assertNotIn("--", text.split("<fontconfig>")[0].split("<!--", 1)[1].split("-->")[0])
        self.assertEqual(fs.fontconfig_read(text), (aliases, ("rgba", "full", "bgr")))

    def test_nothing_is_no_file(self):
        self.assertIsNone(fs.fontconfig_text({}, None))
        self.assertIsNone(fs.fontconfig_text({"serif": None}, None))
        self.assertEqual(fs.fontconfig_read(None), ({}, None))

    def test_render_props(self):
        props = dict((n, v) for n, _, v in fs.render_props("none", "none", "rgb"))
        self.assertEqual((props["antialias"], props["hinting"], props["rgba"]), ("false", "false", "none"))
        props = dict((n, v) for n, _, v in fs.render_props("rgba", "slight", "vbgr"))
        self.assertEqual((props["rgba"], props["hintstyle"], props["lcdfilter"]), ("vbgr", "hintslight", "lcddefault"))
        props = dict((n, v) for n, _, v in fs.render_props("grayscale", "medium", "rgb"))
        self.assertEqual(props["rgba"], "none")


class Families(unittest.TestCase):
    TEXT = ("Inter||False|[100 900]\nFira Code|100|False|80\nFira Code|100|False|200\n"
            "Noto Color Emoji|100|True|80\nDroid Sans Japanese|90|False|80\n|100|False|80\n")

    def test_parse(self):
        got = fs.parse_families(self.TEXT)
        self.assertEqual(got["all"], ["Droid Sans Japanese", "Fira Code", "Inter", "Noto Color Emoji"])
        self.assertEqual(got["mono"], ["Droid Sans Japanese", "Fira Code"])
        self.assertEqual(got["bold"], ["Fira Code", "Inter"])

    def test_canonical(self):
        self.assertEqual(fs.canonical("fira code", ["Fira Code", "Inter"]), "Fira Code")
        self.assertIsNone(fs.canonical("Comic", ["Inter"]))

    def test_cosmic(self):
        self.assertEqual(fs.cosmic_family(fs.cosmic_font('Odd "Name"')), 'Odd "Name"')
        self.assertIsNone(fs.cosmic_family(None))

    def test_gvariant_str(self):
        self.assertEqual(fs.gvariant_str("'Adwaita Sans 11'"), "Adwaita Sans 11")
        self.assertEqual(fs.gvariant_str("1.25"), "1.25")


class UserLayer(unittest.TestCase):
    CONF = {"font": "Selawik, IBM Plex Sans", "font_mono": "IBM Plex Mono", "term.font": "Source Code Pro",
            "term.font_size": "14", "cursor_theme": "Adwaita"}

    def test_nothing_set_changes_nothing(self):
        conf = theme.user_layer(dict(self.CONF), {})
        for key, value in self.CONF.items():
            self.assertEqual(conf[key], value)
            self.assertEqual(conf[f"theme:{key}"], value)

    def test_overrides(self):
        state = {"font_user": "Inter", "font_mono_user": "IBM Plex Mono", "term_font_user": "Fira Code, X",
                 "term_font_size_user": "16", "cursor_theme_user": "Pop"}
        conf = theme.user_layer(dict(self.CONF), state)
        self.assertEqual(conf["font"], "Inter, Selawik, IBM Plex Sans")
        self.assertEqual(conf["font_mono"], "IBM Plex Mono")       # no duplicate
        self.assertEqual(conf["term.font"], "Fira Code")
        self.assertEqual(conf["term.font_size"], "16")
        self.assertEqual(conf["cursor_theme"], "Pop")
        self.assertEqual(conf["theme:font"], "Selawik, IBM Plex Sans")

    def test_bad_size_ignored(self):
        conf = theme.user_layer(dict(self.CONF), {"term_font_size_user": "99"})
        self.assertEqual(conf["term.font_size"], "14")

    def test_cursor_size(self):
        self.assertEqual(theme.cursor_size({}), "24")
        self.assertEqual(theme.cursor_size({"cursor_size": "32"}), "32")
        self.assertEqual(theme.cursor_size({"cursor_size": "4"}), "24")
        self.assertEqual(theme.cursor_size({"cursor_size": "big"}), "24")

    def test_state_is_scratch(self):
        self.assertTrue(theme.STATE.startswith(helpers.SCRATCH))
        self.assertTrue(os.environ["XDG_STATE_HOME"].startswith(helpers.SCRATCH))


class QtFollow(unittest.TestCase):
    """qt_follow() against scratch qt?ct files with gsettings stubbed: Qt
    gets a font whenever GTK would differ from Qt's own default -- a face
    picked, a size set on the stock face, or a scaling factor."""

    def setUp(self):
        self.dir = os.path.join(helpers.SCRATCH, "qtfollow")
        os.makedirs(self.dir, exist_ok=True)
        self.saved = (fs.QT_CONFS, fs.FONTCONFIG, fs.gs_user, fs.gs_all)
        fs.QT_CONFS = {6: os.path.join(self.dir, "qt6ct.conf")}
        fs.FONTCONFIG = os.path.join(self.dir, "50-desktop-fonts.conf")
        for path in (fs.FONTCONFIG,):
            if os.path.exists(path):
                os.remove(path)
        with open(fs.QT_CONFS[6], "w") as handle:
            handle.write("[Appearance]\nstyle=Fusion\n")
        self.user, self.gs = {}, {"font-name": "'Adwaita Sans 11'", "monospace-font-name": "'Adwaita Mono 11'",
                                  "text-scaling-factor": "1.0"}
        fs.gs_user = lambda: self.user
        fs.gs_all = lambda: self.gs

    def tearDown(self):
        fs.QT_CONFS, fs.FONTCONFIG, fs.gs_user, fs.gs_all = self.saved

    def qt(self):
        with open(fs.QT_CONFS[6]) as handle:
            text = handle.read()
        return fs.parse_qt_font(fs.ini_get(text, "Fonts", "general")), fs.parse_qt_font(fs.ini_get(text, "Fonts", "fixed"))

    def test_nothing_set_leaves_qt_alone(self):
        fs.qt_follow()
        self.assertEqual(self.qt(), (None, None))

    def test_size_on_the_stock_face(self):
        self.gs["font-name"] = "'Adwaita Sans 13'"
        self.user["font-name"] = self.gs["font-name"]
        fs.qt_follow()
        self.assertEqual(self.qt(), (("Adwaita Sans", 13.0), None))

    def test_scale_alone_sizes_both(self):
        self.gs["text-scaling-factor"] = "1.5"
        fs.qt_follow()
        self.assertEqual(self.qt(), (("Adwaita Sans", 16.5), ("Adwaita Mono", 16.5)))
        self.gs["text-scaling-factor"] = "1.0"
        fs.qt_follow()
        self.assertEqual(self.qt(), (None, None))


if __name__ == "__main__":
    unittest.main()
