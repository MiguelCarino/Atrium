"""Theme previews (make-theme-previews.py) and Settings > Theme > Gallery
(settings_pages/themes.py): the colour resolver, the short descriptions,
a preview for EVERY installed theme made headlessly into the scratch cache
(helpers.py's XDG_CACHE_HOME, never ~/.cache), byte-for-byte the same twice,
remade only when an input changes, and the page built with its cards.
Nothing switches the live theme: the page's switch is never clicked."""
import os
import shutil
import tempfile
import unittest

import helpers

prev = helpers.import_script("make-theme-previews.py")
T = prev.T


class Colours(unittest.TestCase):
    def test_literals(self):
        self.assertEqual(prev.colour("#00f0ff", {}), (0, 240, 255, 255))
        self.assertEqual(prev.colour("#fff", {}), (255, 255, 255, 255))
        self.assertEqual(prev.colour("rgba(6, 8, 16, 0.5)", {}), (6, 8, 16, 128))
        self.assertEqual(prev.colour("rgb(100%, 0, 0)", {}), (255, 0, 0, 255))
        self.assertEqual(prev.colour("transparent", {}), (0, 0, 0, 0))

    def test_names_and_functions(self):
        names = {"cyan": "#00f0ff", "edge": "alpha(@cyan, 0.5)", "half": "mix(#000000, #ffffff, 0.5)",
                 "dark": "shade(#808080, 0.5)", "deep": "alpha(@edge, 0.5)"}
        self.assertEqual(prev.colour("@edge", names), (0, 240, 255, 128))
        self.assertEqual(prev.colour("@deep", names), (0, 240, 255, 64))
        self.assertEqual(prev.colour("@half", names), (128, 128, 128, 255))
        self.assertEqual(prev.colour("@dark", names), (64, 64, 64, 255))

    def test_unreadable_is_none_not_an_error(self):
        self.assertIsNone(prev.colour("@loop", {"loop": "@loop"}))
        self.assertIsNone(prev.colour("@missing", {}))
        self.assertIsNone(prev.colour("linear-gradient(red, blue)", {}))
        self.assertIsNone(prev.colour("#12345", {}))

    def test_split_args_top_level_only(self):
        self.assertEqual(prev.split_args("a, mix(b, c, 0.5), 0.3"), ["a", "mix(b, c, 0.5)", "0.3"])

    def test_last_definition_wins_and_comments_drop(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "x.css")
        with open(path, "w") as handle:
            handle.write("@define-color a #000000;\n/* @define-color a #ff0000; */\n@define-color a #ffffff;\n")
        self.assertEqual(prev.defines(path), [("a", "#000000"), ("a", "#ffffff")])

    def test_palette_accent_is_cyan(self):
        """accent= in theme.conf is @cyan (themes/README); every part has
        the names the drawing uses."""
        for name, _ in T.themes():
            accent = T.load(name, user=False).get("accent", "")
            for part in ("bar", "panel"):
                pal = prev.palette(name, part)
                for key in ("surface", "text", "edge", "cyan", "good", "good-fg", "green", "magenta"):
                    self.assertEqual(len(pal[key]), 4, (name, part, key))
                if T.HEX.match(accent) and part == "panel":
                    self.assertEqual(pal["cyan"], prev.hex_rgba(accent), name)

    def test_seasonal_palette_follows_the_season(self):
        """A seasonal theme's roles are written in its season's s-* names
        (season/<s>/palette.css): the preview reads that file, so surface,
        edge and green are the season's, not FALLBACK or the base neon; and
        the cache key moves with the season."""
        seasonal = [n for n, _ in T.themes() if T.seasonal(n)]
        if not seasonal:
            self.skipTest("no seasonal theme installed")
        name = seasonal[0]
        real = T.load
        self.addCleanup(setattr, T, "load", real)
        keys = set()
        for s in sorted(os.listdir(os.path.join(T.theme_dir(name), T.SEASON_DIR))):
            if not os.path.isfile(os.path.join(T.season_dir(name, s), "palette.css")):
                continue
            T.load = lambda n=None, user=True, season=None, s=s: real(n, user, s if n == name else season)
            own = dict(prev.defines(os.path.join(T.season_dir(name, s), "palette.css")))
            bar, panel = prev.palette(name, "bar"), prev.palette(name, "panel")
            for pal in (bar, panel):
                for key in ("surface", "edge", "green"):
                    self.assertNotEqual(pal[key], prev.FALLBACK[key], (s, key))
            if "s-rule" in own:
                self.assertEqual(bar["edge"], prev.colour(own["s-rule"], own), s)
            if "s-surface" in own:
                self.assertEqual(bar["surface"], prev.colour(own["s-surface"], own), s)
            files = prev.inputs(name)
            self.assertIn(os.path.join(T.season_dir(name, s), "palette.css"), files)
            self.assertIn(os.path.join(T.season_dir(name, s), "theme.conf"), files)
            keys.add(prev.key(name))
        self.assertGreater(len(keys), 1)

    def test_readable_picks_contrast(self):
        pal = {"text": (0, 0, 0, 255), "text-bright": (255, 255, 255, 255)}
        self.assertEqual(prev.readable((0, 0, 128, 255), (172, 172, 172, 255), pal), (255, 255, 255, 255))
        self.assertEqual(prev.readable((0, 240, 255, 255), (6, 8, 16, 255), pal), (0, 0, 0, 255))


class About(unittest.TestCase):
    def test_tidy(self):
        self.assertEqual(prev.tidy("Luna: an original homage to the era. More text", "luna", "Luna"),
                         "An original homage to the era")
        # a colon that is not the theme's name stays
        self.assertEqual(prev.tidy("phosphor green on black: a terminal", "matrix", "Matrix"),
                         "Phosphor green on black: a terminal")
        self.assertEqual(prev.tidy("Lo-fi: a study room at dusk -- a rainy window", "lofi", "Lo-fi"),
                         "A study room at dusk")
        self.assertEqual(prev.tidy("Windows 95 is 3.5 inches. x", "w", "W"), "Windows 95 is 3.5 inches")
        long = prev.tidy("word " * 40, "x", "X")
        self.assertLessEqual(len(long), prev.ABOUT_MAX)
        self.assertTrue(long.endswith("…"))

    def test_readme_paragraph(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "README")
        with open(path, "w") as handle:
            handle.write("Intro\n\n    alpha/       Alpha: first line\n                 goes on. Rest\n"
                         "    beta/        Beta: other\n")
        self.assertEqual(prev.readme_text("alpha", path), "Alpha: first line goes on. Rest")
        self.assertEqual(prev.readme_text("beta", path), "Beta: other")
        self.assertEqual(prev.readme_text("gamma", path), "")

    def test_every_theme_has_one(self):
        for name, _ in T.themes():
            text = prev.about(name)
            self.assertTrue(text, name)
            self.assertLessEqual(len(text), prev.ABOUT_MAX, name)


class Previews(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp(dir=os.environ["XDG_CACHE_HOME"])
        self.addCleanup(shutil.rmtree, self.cache, True)

    def test_cache_is_scratch(self):
        self.assertTrue(prev.CACHE.startswith(os.environ["XDG_CACHE_HOME"]))

    def test_every_installed_theme(self):
        """A preview for each theme theme.py lists, the right size,
        carrying its key, and not a blank picture."""
        for name, _ in T.themes():
            path = prev.preview(name, self.cache)
            self.assertEqual(path, os.path.join(self.cache, f"{name}.png"))
            with prev.Image.open(path) as im:
                self.assertEqual(im.size, prev.SIZE, name)
                self.assertEqual(im.text.get(prev.KEY_CHUNK), prev.key(name), name)
                lo, hi = zip(*im.convert("RGB").getextrema())
                self.assertGreater(max(hi) - min(lo), 40, name)
            self.assertFalse(prev.stale(name, self.cache), name)

    def test_deterministic(self):
        name = T.themes()[0][0]
        other = tempfile.mkdtemp(dir=os.environ["XDG_CACHE_HOME"])
        self.addCleanup(shutil.rmtree, other, True)
        with open(prev.preview(name, self.cache), "rb") as a, open(prev.preview(name, other), "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_lazy_until_an_input_changes(self):
        name = T.themes()[0][0]
        path = prev.preview(name, self.cache)
        stamp = os.stat(path).st_mtime_ns
        self.assertEqual(prev.preview(name, self.cache), path)
        self.assertEqual(os.stat(path).st_mtime_ns, stamp)         # fresh: not rewritten
        real = prev.key
        self.addCleanup(setattr, prev, "key", real)
        prev.key = lambda *a, **k: "changed"                       # a theme file was edited
        self.assertTrue(prev.stale(name, self.cache))
        prev.preview(name, self.cache)
        self.assertEqual(prev.cached_key(path), "changed")

    def test_no_wallpaper_falls_back_to_gradient(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        name = T.themes()[0][0]
        self.assertIsNone(prev.wallpaper(name, "DP-1", empty))
        img = prev.render(name, "DP-1", empty)
        self.assertEqual(img.size, prev.SIZE)
        # never a light field (HDR, themes/README): the gradient's corner is dark
        self.assertLess(prev.luminance(img.getpixel((2, img.height - 2))), 0.5)

    def test_first_wallpaper_by_name(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        os.makedirs(os.path.join(folder, "DP-1"))
        prefix = T.load("cyberpunk", user=False)["wallpaper_prefix"]
        for n in (f"{prefix}b.png", f"{prefix}a.jpg", f"{prefix}0.mp4", "other.png"):
            open(os.path.join(folder, "DP-1", n), "w").close()
        self.assertEqual(os.path.basename(prev.wallpaper("cyberpunk", "DP-1", folder)), f"{prefix}a.jpg")


class GalleryPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")           # settings.py does this before any page loads
            gi.require_version("Gdk", "3.0")
            from settings_pages import themes as page            # needs GTK, not a display
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.themes not importable: {exc}")
        cls.page = page

    def test_page_literal_is_a_theme_tab(self):
        from settings_pages import _catalog
        meta = next(p for p in _catalog.read_pages() if p["id"] == "themes")
        self.assertEqual((meta["parent"], meta["tab"], meta["group"]), ("theme", "Gallery", "Look"))
        self.assertIn(("themes", "Gallery"), _catalog.tabs(_catalog.read_pages(), "theme"))

    def test_shown_size_fits_two_cards_in_the_window(self):
        # 360x180 previews shown at 290 wide, same aspect; never scaled up
        self.assertEqual(self.page.shown_size((360, 180)), (290, 145))
        self.assertEqual(self.page.shown_size((200, 100)), (200, 100))
        self.assertEqual(self.page.shown_size((360, 180), 180), (180, 90))
        # two cards (picture + ~24 px of pick padding and flowboxchild) and the
        # 8 px spacing inside the ~670 px the 1000 px window leaves the page
        w, _h = self.page.shown_size(self.page.previews.SIZE)
        self.assertLessEqual(2 * (w + 24) + 8, 670)

    def test_current_card_has_its_own_class(self):
        from gi.repository import Gtk
        if not Gtk.init_check(None)[0]:
            self.skipTest("no display for widgets")
        p = self.page.Page()
        button, _image, _title = p.card({"name": "x", "label": "X", "about": "", "current": True})
        # panel.css draws button.dev-pick.theme-card.active as a ring, not a fill
        self.assertTrue(button.get_style_context().has_class("theme-card"))

    def test_rows_and_texts(self):
        rows = self.page.card_rows([("a", "Alpha"), ("b", "B & co")], "b", lambda n: n.upper())
        self.assertEqual([r["current"] for r in rows], [False, True])
        self.assertEqual(rows[0]["about"], "A")
        self.assertEqual(self.page.title_markup(rows[1]), "✓ B &amp; co")
        self.assertEqual(self.page.title_markup(rows[0]), "Alpha")
        self.assertEqual(self.page.status_text(rows), "Now: B & co. Click a theme to switch to it.")
        self.assertEqual(self.page.status_text(rows, "Alpha"), "Switching to Alpha…")

    def test_season_caption_and_choices(self):
        auto = {"theme": "seasons", "seasonal": True, "season": "autumn", "hemisphere": "north",
                "source": "weather", "pin": "", "next": {"season": "winter", "date": "2026-12-01"}}
        self.assertEqual(self.page.season_caption(auto),
                         "Autumn · northern hemisphere, from the weather place · winter from 1 Dec")
        self.assertEqual(self.page.season_choices(auto), ("auto", "auto"))
        held = dict(auto, hemisphere="south", source="setting", pin="winter", season="winter", next=None)
        self.assertEqual(self.page.season_caption(held), "Winter · southern hemisphere, set by you · pinned")
        self.assertEqual(self.page.season_choices(held), ("south", "winter"))
        # not seasonal: no row at all
        plain = {"theme": "matrix", "seasonal": False, "season": "", "hemisphere": "", "source": "",
                 "pin": "", "next": None}
        self.assertEqual(self.page.season_caption(plain), "")
        self.assertEqual(self.page.season_caption(None), "")
        # a broken next date still gives the head
        self.assertEqual(self.page.season_caption(dict(auto, next={"season": "winter", "date": ""})),
                         "Autumn · northern hemisphere, from the weather place")
        # the selectors' ids are the ones theme.py season accepts
        self.assertEqual([k for k, _ in self.page.SEASON_CHOICES][1:], list(T.SEASONS))
        self.assertEqual([k for k, _ in self.page.HEMI_CHOICES][1:], list(T.HEMISPHERES))

    def test_season_row_shows_only_for_a_seasonal_theme(self):
        from gi.repository import Gtk
        if not Gtk.init_check(None)[0]:
            self.skipTest("no display for widgets")
        p = self.page.Page()
        ran = []
        p.pick_season = lambda verb, value: ran.append((verb, value))   # never a real theme.py
        p.show_season({"theme": "seasons", "seasonal": True, "season": "spring", "hemisphere": "south",
                       "source": "setting", "pin": "spring", "next": None})
        self.assertTrue(p.season_row.get_visible())
        self.assertEqual((p.hemi.get_active_id(), p.season.get_active_id()), ("south", "spring"))
        self.assertIn("pinned", p.season_sub.get_text())
        p.show_season({"theme": "matrix", "seasonal": False})
        self.assertFalse(p.season_row.get_visible())

    def test_builds_with_a_card_per_theme(self):
        from gi.repository import Gtk
        if not Gtk.init_check(None)[0]:
            self.skipTest("no display for widgets")
        p = self.page.Page()
        themes = T.themes()
        current = themes[-1][0]
        p.draw(self.page.card_rows(themes, current, prev.about))
        self.assertEqual(list(p.cards), [n for n, _ in themes])
        for name, (button, image, title) in p.cards.items():
            self.assertEqual(button.get_style_context().has_class("active"), name == current)
            self.assertEqual(title.get_text().startswith("✓"), name == current)
        cache = tempfile.mkdtemp(dir=os.environ["XDG_CACHE_HOME"])
        self.addCleanup(shutil.rmtree, cache, True)
        p.show_preview(themes[0][0], prev.preview(themes[0][0], cache))
        self.assertIsNotNone(p.cards[themes[0][0]][1].get_pixbuf())
        p.show_preview("no-such-theme", None)                      # ignored, no error


if __name__ == "__main__":
    unittest.main()
