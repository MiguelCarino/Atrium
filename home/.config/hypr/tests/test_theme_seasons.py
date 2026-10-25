"""theme.py's seasonal themes: the season from the date and the hemisphere,
the overlay load() lays on, the palette and additions in the generated files,
mako's section-wise merge, season-check and the season folder's lint.

Hermetic: every test runs against a scratch themes folder (a minimal
cyberpunk, a plain theme and a fake seasonal one) and a scratch generated
folder, never ~/.config/themes or the live waybar/generated; the place
lookups are stubbed, so no region.conf or weather cache is read."""
import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers

theme = helpers.import_script("theme.py", "theme")

PALETTE = "@define-color s-surface #101010;\n@define-color s-text #eeeeee;\n"
PLAIN_WAYBAR = "#clock { color: @text; }\n"
SEASON_CONF = {
    "spring": "accent=#f4a8d0\nicon_theme=Seasons-Spring\ncolor.cpu=#f4a8d0\n",
    "summer": "accent=#5ccfd6\n",
    "autumn": "accent=#ee9a62\n",
    "winter": "accent=#8ccaf2\nterm.cursor=#8ccaf2\n",
}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


class Scratch(unittest.TestCase):
    """A scratch themes folder and generated folder for each test."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="theme-seasons-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.themes = os.path.join(self.root, "themes")
        self.gen = os.path.join(self.root, "generated")
        os.makedirs(self.gen)
        for name, value in (("THEMES_DIR", self.themes), ("GEN", self.gen),
                            ("SEASON_FILE", os.path.join(self.gen, "season")),
                            ("MPV_BASE", os.path.join(self.themes, "mpv-base.conf"))):
            patcher = mock.patch.object(theme, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # No place lookups and no HYPR_SEASON from the environment running
        # the tests: each test says what it wants.
        patcher = mock.patch.object(theme, "place_latitudes", return_value=(None, None))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("HYPR_SEASON", None)
        write(os.path.join(self.themes, "cyberpunk", "theme.conf"), "name=Cyberpunk\norder=10\n")
        write(os.path.join(self.themes, "plain", "theme.conf"), "name=Plain\naccent=#123456\n")
        write(os.path.join(self.themes, "plain", "waybar.css"), PLAIN_WAYBAR)
        self.make_seasonal("almanac")

    def make_seasonal(self, name):
        base = os.path.join(self.themes, name)
        write(os.path.join(base, "theme.conf"),
              "name=Almanac\naccent=#ee9a62\nfont=Alegreya Sans, IBM Plex Sans\nhypr.rounding=10\n")
        write(os.path.join(base, "waybar.css"), "#clock { color: @s-text; }\n")
        write(os.path.join(base, "mako"), "border-size=2\n[urgency=critical]\nborder-color=#ff0000\n")
        write(os.path.join(base, "kitty.conf"), "tab_bar_style separator\n")
        write(os.path.join(base, "prompt.sh"), "PROMPT_GLYPH='*'\n")
        write(os.path.join(base, "mpv.conf"), "osd-font=Alegreya Sans\n")
        for s, conf in SEASON_CONF.items():
            folder = os.path.join(base, "season", s)
            write(os.path.join(folder, "theme.conf"), conf)
            write(os.path.join(folder, "palette.css"), PALETTE.replace("#101010", f"#1010{len(s):02d}"))
        return base

    def season_file(self, s, filename, text):
        write(os.path.join(self.themes, "almanac", "season", s, filename), text)


class SeasonFor(unittest.TestCase):
    NORTH = ["winter", "winter", "spring", "spring", "spring", "summer",
             "summer", "summer", "autumn", "autumn", "autumn", "winter"]
    SOUTH = ["summer", "summer", "autumn", "autumn", "autumn", "winter",
             "winter", "winter", "spring", "spring", "spring", "summer"]

    def test_every_month_both_hemispheres(self):
        for month in range(1, 13):
            self.assertEqual(theme.season_for(month, "north"), self.NORTH[month - 1], month)
            self.assertEqual(theme.season_for(month, "south"), self.SOUTH[month - 1], month)

    def test_named_cases(self):
        self.assertEqual(theme.season_for(1, "north"), "winter")
        self.assertEqual(theme.season_for(1, "south"), "summer")
        self.assertEqual(theme.season_for(6, "south"), "winter")
        self.assertEqual(theme.season_for(10, "north"), "autumn")
        self.assertEqual(theme.season_for(10, "south"), "spring")

    def test_next_season(self):
        self.assertEqual(theme.next_season(datetime.date(2026, 10, 24), "north"),
                         ("winter", datetime.date(2026, 12, 1)))
        self.assertEqual(theme.next_season(datetime.date(2026, 12, 31), "north"),
                         ("spring", datetime.date(2027, 3, 1)))
        self.assertEqual(theme.next_season(datetime.date(2026, 10, 24), "south"),
                         ("summer", datetime.date(2026, 12, 1)))


class Hemisphere(unittest.TestCase):
    def test_setting_beats_both_latitudes(self):
        self.assertEqual(theme.hemisphere_from("south", 40.0, 40.0), ("south", "setting"))
        self.assertEqual(theme.hemisphere_from("north", -25.0, -25.0), ("north", "setting"))

    def test_weather_beats_zone(self):
        self.assertEqual(theme.hemisphere_from("auto", -20.0, 30.0), ("south", "weather"))
        self.assertEqual(theme.hemisphere_from("auto", 30.0, -20.0), ("north", "weather"))

    def test_zone_alone(self):
        self.assertEqual(theme.hemisphere_from("auto", None, -40.0), ("south", "time zone"))

    def test_nothing_is_north_by_default(self):
        self.assertEqual(theme.hemisphere_from("auto", None, None), ("north", "default"))

    def test_latitude_zero_is_north(self):
        self.assertEqual(theme.hemisphere_from("auto", 0.0, -10.0), ("north", "weather"))

    def test_bogus_setting_is_auto(self):
        self.assertEqual(theme.hemisphere_from("sideways", None, -5.0), ("south", "time zone"))
        self.assertEqual(theme.hemisphere_from("", None, None), ("north", "default"))


class Season(Scratch):
    OCT = datetime.date(2026, 10, 24)

    def test_date_decides_by_default(self):
        self.assertEqual(theme.season("almanac", self.OCT, {}), "autumn")
        self.assertEqual(theme.season("almanac", self.OCT, {"season_hemisphere": "south"}), "spring")

    def test_pin_beats_the_date(self):
        self.assertEqual(theme.season("almanac", self.OCT, {"season_pin": "winter"}), "winter")
        # "auto" or junk is no pin.
        self.assertEqual(theme.season("almanac", self.OCT, {"season_pin": "auto"}), "autumn")

    def test_env_beats_the_pin(self):
        os.environ["HYPR_SEASON"] = "summer"
        self.assertEqual(theme.season("almanac", self.OCT, {"season_pin": "winter"}), "summer")
        os.environ["HYPR_SEASON"] = "monsoon"     # not a season: ignored
        self.assertEqual(theme.season("almanac", self.OCT, {"season_pin": "winter"}), "winter")

    def test_non_seasonal_theme_has_no_season(self):
        os.environ["HYPR_SEASON"] = "summer"
        self.assertEqual(theme.season("plain", self.OCT, {}), "")
        self.assertFalse(theme.seasonal("plain"))
        self.assertTrue(theme.seasonal("almanac"))

    def test_status_never_carries_a_place(self):
        with mock.patch.object(theme, "place_latitudes", return_value=(-20.0, 30.0)):
            status = theme.season_status("almanac", self.OCT, {})
        self.assertEqual(status["season"], "spring")
        self.assertEqual((status["hemisphere"], status["source"]), ("south", "weather"))
        self.assertEqual(status["next"], {"season": "summer", "date": "2026-12-01"})
        self.assertNotIn("20", repr(status).replace("2026", ""))
        self.assertNotIn("30.0", repr(status))
        self.assertEqual(theme.season_line(status),
                         "almanac: spring (south, from the weather place; next: summer on 2026-12-01)")

    def test_status_when_pinned_and_when_not_seasonal(self):
        status = theme.season_status("almanac", self.OCT, {"season_pin": "winter"})
        self.assertEqual((status["season"], status["pin"], status["next"]), ("winter", "winter", None))
        self.assertIn("pinned to winter", theme.season_line(status))
        self.assertEqual(theme.season_line(theme.season_status("plain", self.OCT, {})), "plain: not seasonal")


class Load(Scratch):
    def test_overlay_keys_merge(self):
        conf = theme.load("almanac", user=False, season="spring")
        self.assertEqual(conf["season"], "spring")
        self.assertEqual(conf["accent"], "#f4a8d0")
        self.assertEqual(conf["icon_theme"], "Seasons-Spring")
        self.assertEqual(conf["color.cpu"], "#f4a8d0")
        self.assertEqual(conf["hypr.rounding"], "10")         # the theme's own, kept

    def test_forbidden_keys_are_ignored(self):
        self.season_file("winter", "theme.conf", SEASON_CONF["winter"] + "hypr.rounding=0\nfont=Comic Sans\n")
        conf = theme.load("almanac", user=False, season="winter")
        self.assertEqual(conf["accent"], "#8ccaf2")
        self.assertEqual(conf["hypr.rounding"], "10")
        self.assertEqual(conf["font"], "Alegreya Sans, IBM Plex Sans")

    def test_empty_season_is_the_plain_chain(self):
        conf = theme.load("almanac", user=False, season="")
        self.assertEqual(conf["season"], "")
        self.assertEqual(conf["accent"], "#ee9a62")

    def test_default_follows_season(self):
        os.environ["HYPR_SEASON"] = "summer"
        self.assertEqual(theme.load("almanac", user=False)["accent"], "#5ccfd6")

    def test_every_conf_has_the_key(self):
        self.assertEqual(theme.load("plain", user=False)["season"], "")
        # A season forced on a theme without one gives nothing.
        self.assertEqual(theme.load("plain", user=False, season="winter")["season"], "")


class Generated(Scratch):
    def test_palette_after_fonts_before_theme_css(self):
        conf = theme.load("almanac", user=False, season="autumn")
        text = theme.generated_text("waybar.css", conf)
        self.assertIn("from theme 'almanac' season 'autumn'", text.splitlines()[0])
        fonts = text.index("font=Alegreya Sans")
        palette = text.index("@define-color s-surface #101006;")
        rules = text.index("#clock { color: @s-text; }")
        self.assertLess(fonts, palette)
        self.assertLess(palette, rules)
        self.assertIn("season=autumn: ~/.config/themes/almanac/season/autumn/palette.css", text)

    def test_no_palette_in_gtk4(self):
        conf = theme.load("almanac", user=False, season="autumn")
        self.assertNotIn("s-surface", theme.generated_text("gtk4.css", conf))

    def test_season_addition_comes_last(self):
        self.season_file("winter", "waybar.css", "#custom-clock { border-color: @s-text; }\n")
        conf = theme.load("almanac", user=False, season="winter")
        text = theme.generated_text("waybar.css", conf)
        self.assertLess(text.index("#clock { color: @s-text; }"), text.index("/* season=winter: ~/.config/themes/almanac/season/winter/waybar.css */"))
        self.assertTrue(text.rstrip().endswith("#custom-clock { border-color: @s-text; }"))

    def test_non_seasonal_output_is_unchanged(self):
        """A theme's files read exactly the same with the season machinery
        there: the plain theme's outputs before and after it gains a season
        folder (read with season=""), and none mentions a season."""
        conf = theme.load("plain", user=False)
        before = {t: theme.generated_text(t, conf) for t in theme.TARGETS}
        before.update(kitty=theme.kitty_text(conf), prompt=theme.prompt_text(conf), mpv=theme.mpv_text(conf))
        self.assertTrue(before["waybar.css"].endswith("\n" + PLAIN_WAYBAR))
        for text in before.values():
            self.assertNotIn("season", text)
        write(os.path.join(self.themes, "plain", "season", "winter", "waybar.css"), "#x { color: red; }\n")
        conf = theme.load("plain", user=False, season="")
        after = {t: theme.generated_text(t, conf) for t in theme.TARGETS}
        after.update(kitty=theme.kitty_text(conf), prompt=theme.prompt_text(conf), mpv=theme.mpv_text(conf))
        self.assertEqual(before, after)

    def test_mako_is_merged_by_section(self):
        self.season_file("spring", "mako", "background-color=#141c17f2\n[urgency=low]\ntext-color=#a9b8ad\n")
        conf = theme.load("almanac", user=False, season="spring")
        lines = theme.generated_text("mako", conf).splitlines()
        bg = lines.index("background-color=#141c17f2")
        crit = lines.index("[urgency=critical]")
        self.assertLess(lines.index("border-size=2"), bg)
        self.assertLess(bg, crit)                       # the season's global is still global
        self.assertLess(crit, lines.index("[urgency=low]"))

    def test_kitty_prompt_mpv_append_the_season(self):
        self.season_file("summer", "kitty.conf", "active_tab_background #5ccfd6\n")
        self.season_file("summer", "prompt.sh", "PROMPT_GLYPH='o'\n")
        self.season_file("summer", "mpv.conf", "script-opts-append=uosc-color=foreground=5ccfd6\n")
        write(theme.MPV_BASE, "osd-bar=no\n")
        conf = theme.load("almanac", user=False, season="summer")
        kitty, prompt, mpv = theme.kitty_text(conf), theme.prompt_text(conf), theme.mpv_text(conf)
        self.assertLess(kitty.index("tab_bar_style separator"), kitty.index("active_tab_background #5ccfd6"))
        self.assertLess(prompt.index("PROMPT_GLYPH='*'"), prompt.index("PROMPT_GLYPH='o'"))
        self.assertLess(mpv.index("osd-bar=no"), mpv.index("osd-font=Alegreya Sans"))
        self.assertLess(mpv.index("osd-font=Alegreya Sans"), mpv.index("uosc-color=foreground=5ccfd6"))
        self.assertIn("# season=summer: ~/.config/themes/almanac/season/summer/prompt.sh", prompt)


class MakoMerge(unittest.TestCase):
    def test_order(self):
        base = "a=1\n[urgency=low]\nb=2\n"
        extra = "c=3\n[urgency=critical]\nd=4\n"
        self.assertEqual(theme.mako_merge(base, extra),
                         "a=1\nc=3\n[urgency=low]\nb=2\n[urgency=critical]\nd=4\n")

    def test_base_ending_in_a_section_cannot_swallow_globals(self):
        base = "font=X 11\n[urgency=critical]\nborder-color=#ff0000"      # no final newline
        merged = theme.mako_merge(base, "background-color=#000000ff\n")
        self.assertLess(merged.index("background-color"), merged.index("[urgency=critical]"))

    def test_nothing_to_merge_is_the_base(self):
        self.assertEqual(theme.mako_merge("a=1\n[x]\n", ""), "a=1\n[x]\n")


class SeasonCheck(Scratch):
    def setUp(self):
        super().setUp()
        self.applied = []
        self.notes = []
        for name, stub in (("current", lambda: self.current),
                           ("apply", lambda conf, quiet=False: self.applied.append(conf["season"]) or []),
                           ("gtk4_restart", lambda changed, title: False),
                           ("notify", lambda title, body="": self.notes.append((title, body))),
                           ("switch_sound", lambda: None),
                           ("run", lambda cmd, timeout=10, **kw: self.hyprctl)):
            patcher = mock.patch.object(theme, name, stub)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.current = "almanac"
        self.hyprctl = mock.Mock(stdout='[{"class": "kitty"}]')
        os.environ["HYPR_SEASON"] = "winter"

    def record(self, s):
        write(theme.SEASON_FILE, s + "\n")

    def test_due_truth_table(self):
        self.assertTrue(theme.season_due("", "winter"))
        self.assertTrue(theme.season_due("autumn", "winter"))
        self.assertFalse(theme.season_due("winter", "winter"))
        self.assertFalse(theme.season_due("winter", ""))
        self.assertFalse(theme.season_due("", ""))

    def test_non_seasonal_theme_does_nothing(self):
        self.current = "plain"
        self.assertFalse(theme.cmd_season_check())
        self.assertEqual(self.applied, [])

    def test_already_recorded_does_nothing(self):
        self.record("winter")
        self.assertFalse(theme.cmd_season_check())
        self.assertEqual(self.applied, [])

    def test_applies_once_on_a_change(self):
        self.record("autumn")
        self.assertTrue(theme.cmd_season_check())
        self.assertEqual(self.applied, ["winter"])
        self.assertEqual(self.notes[0][0], "Seasons: winter")

    def test_a_game_holds_it(self):
        self.record("autumn")
        self.hyprctl = mock.Mock(stdout='[{"class": "steam_app_1234"}]')
        self.assertFalse(theme.cmd_season_check())
        self.assertEqual(self.applied, [])

    def test_force_ignores_the_record_and_the_game(self):
        self.record("winter")
        self.hyprctl = mock.Mock(stdout='[{"class": "steam_app_1234"}]')
        self.assertTrue(theme.cmd_season_check(force=True))
        self.assertEqual(self.applied, ["winter"])

    def test_write_generated_records_the_season(self):
        with mock.patch.object(theme, "write_terminals", return_value=[]), \
                mock.patch.object(theme, "fix_wofi_import", return_value=False), \
                mock.patch.dict(theme.TARGETS, {k: (os.path.join(self.gen, k), *v[1:])
                                                for k, v in theme.TARGETS.items()}), \
                mock.patch.object(theme, "COLORS", os.path.join(self.gen, "colors.conf")), \
                mock.patch.object(theme, "LANG_FILE", os.path.join(self.gen, "lang")), \
                mock.patch.object(theme, "MODULES", os.path.join(self.gen, "modules.json")):
            changed = theme.write_generated(theme.load("almanac", user=False, season="spring"))
            self.assertIn("season", changed)
            self.assertEqual(theme.read_season_record(), "spring")
            changed = theme.write_generated(theme.load("almanac", user=False, season="spring"))
            self.assertNotIn("season", changed)


class CheckSeasons(Scratch):
    def test_a_complete_folder_is_clean(self):
        self.assertEqual(theme.check_seasons("almanac"), [])

    def test_missing_season_folder(self):
        shutil.rmtree(os.path.join(self.themes, "almanac", "season", "summer"))
        self.assertEqual(theme.check_seasons("almanac"), ["season/summer/: missing (every season needs a folder)"])

    def test_stray_hypr_lua(self):
        self.season_file("winter", "hypr.lua", "return {}\n")
        problems = theme.check_seasons("almanac")
        self.assertEqual(len(problems), 1)
        self.assertIn("season/winter/hypr.lua: never read", problems[0])
        self.assertIn("lua/display.lua", problems[0])

    def test_missing_palette(self):
        os.remove(os.path.join(self.themes, "almanac", "season", "autumn", "palette.css"))
        problems = theme.check_seasons("almanac")
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("season/autumn/palette.css: missing"))

    def test_forbidden_and_unknown_keys(self):
        self.season_file("spring", "theme.conf", SEASON_CONF["spring"] + "hypr.rounding=0\nfont=X\nbogus=1\n")
        problems = theme.check_seasons("almanac")
        self.assertIn("season/spring/theme.conf: unknown key 'bogus'", problems)
        self.assertTrue(any("hypr.rounding is ignored" in p and "lua/display.lua" in p for p in problems))
        self.assertTrue(any("font is ignored" in p and "panel" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
