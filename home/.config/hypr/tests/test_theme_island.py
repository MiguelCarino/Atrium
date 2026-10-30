"""theme.py's orchard plumbing: the island hand-off (island_handoff: what
`set` does with island.* keys and the snapshot it keeps), the lint of the
newer keys (check_layout_keys), the bar's layout file (bar.conf) and the
workspace dots (theme-modules.json), the gtk_button_layout words -- and the
animation presets, which three files list and must agree on.

Hermetic: island.py is never run -- a FakeIsland answers `status --json`
and records every `set`, as the real one would change island.json -- and the
snapshot lives in the scratch XDG_STATE_HOME (helpers.py), patched per test
to its own folder. Nothing reaches systemd, waybar or the live state."""
import json
import os
import re
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import helpers

theme = helpers.import_script("theme.py", "theme")
island = helpers.import_script("island.py", "island")
display = helpers.import_script("display.py", "display")

ORCHARD = {"id": "orchard", "island.enabled": "yes", "island.style": "notch", "island.match_bar": "yes"}
PLAIN = {"id": "cyberpunk", "island.enabled": "", "island.style": "", "island.match_bar": ""}


class FakeIsland:
    """island.py as theme.py sees it through run(): status --json prints the
    settings, set KEY WORD changes them (and is recorded)."""

    def __init__(self, **settings):
        self.settings = {"enabled": True, "style": "theme", "match_bar": True, "monitor": ""}
        self.settings.update(settings)
        self.sets = []
        self.fail_status = False

    def __call__(self, cmd, timeout=10, **_kw):
        args = cmd[2:]                      # [python, island.py, ...]
        if args[:1] == ["status"]:
            if self.fail_status:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"settings": self.settings}), stderr="")
        if args[:1] == ["set"]:
            key, word = args[1], args[2]
            self.sets.append((key, word))
            self.settings[key] = word if key == "style" else word == "on"
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected island.py call {cmd}")


class Scratch(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.snap = os.path.join(self.root, "island.before-theme.json")
        patcher = mock.patch.object(theme, "ISLAND_SNAPSHOT", self.snap)
        patcher.start()
        self.addCleanup(patcher.stop)

    def snapshot(self):
        with open(self.snap) as handle:
            return json.load(handle)


class Handoff(Scratch):
    def test_entering_saves_then_applies_in_order(self):
        fake = FakeIsland(enabled=False, style="theme", match_bar=False)
        calls = theme.island_handoff(ORCHARD, run=fake)
        # style, then match_bar, then enabled LAST (the service starts with the final look)
        self.assertEqual(calls, [("style", "notch"), ("match_bar", "on"), ("enabled", "on")])
        self.assertEqual(fake.sets, calls)
        snap = self.snapshot()
        self.assertEqual(snap["saved"], {"enabled": False, "style": "theme", "match_bar": False})
        self.assertEqual(snap["applied"], {"enabled": True, "style": "notch", "match_bar": True})
        self.assertEqual(snap["theme"], "orchard")

    def test_only_differing_keys_are_set(self):
        fake = FakeIsland()                 # on, theme, match_bar: the live machine's
        calls = theme.island_handoff(ORCHARD, run=fake)
        self.assertEqual(calls, [("style", "notch")])
        self.assertEqual(self.snapshot()["saved"], {"enabled": True, "style": "theme", "match_bar": True})

    def test_leaving_restores_and_drops_the_snapshot(self):
        fake = FakeIsland(enabled=False, style="island", match_bar=False)
        theme.island_handoff(ORCHARD, run=fake)
        fake.sets.clear()
        calls = theme.island_handoff(PLAIN, run=fake)
        # off goes first when it is the way back
        self.assertEqual(calls[0], ("enabled", "off"))
        self.assertEqual(sorted(calls), sorted([("enabled", "off"), ("style", "island"), ("match_bar", "off")]))
        self.assertEqual((fake.settings["enabled"], fake.settings["style"], fake.settings["match_bar"]),
                         (False, "island", False))
        self.assertFalse(os.path.exists(self.snap))

    def test_a_key_you_changed_meanwhile_stays_yours(self):
        fake = FakeIsland()
        theme.island_handoff(ORCHARD, run=fake)
        fake.settings["style"] = "island"  # picked in Settings while on orchard
        calls = theme.island_handoff(PLAIN, run=fake)
        self.assertNotIn("style", [k for k, _ in calls])
        self.assertEqual(fake.settings["style"], "island")
        self.assertFalse(os.path.exists(self.snap))

    def test_orchard_to_orchard_dark_keeps_the_first_snapshot(self):
        fake = FakeIsland(style="island")
        theme.island_handoff(ORCHARD, run=fake)
        dark = dict(ORCHARD, id="orchard-dark")
        calls = theme.island_handoff(dark, run=fake)
        self.assertEqual(calls, [])         # already notch / on / match_bar
        snap = self.snapshot()
        self.assertEqual(snap["saved"]["style"], "island")
        self.assertEqual(snap["theme"], "orchard-dark")
        theme.island_handoff(PLAIN, run=fake)
        self.assertEqual(fake.settings["style"], "island")

    def test_a_theme_that_sets_fewer_keys_gives_the_rest_back(self):
        fake = FakeIsland(enabled=False)
        theme.island_handoff(ORCHARD, run=fake)
        fake.sets.clear()
        theme.island_handoff({"id": "half", "island.style": "island"}, run=fake)
        self.assertIn(("enabled", "off"), fake.sets)
        self.assertIn(("style", "island"), fake.sets)
        snap = self.snapshot()
        self.assertEqual(set(snap["saved"]), {"style"})
        self.assertEqual(snap["saved"]["style"], "theme")

    def test_no_keys_no_snapshot_no_calls(self):
        fake = FakeIsland()
        fake.fail_status = True             # would fail loudly if it were asked at all
        self.assertEqual(theme.island_handoff(PLAIN, run=fake), [])
        self.assertEqual(fake.sets, [])
        self.assertFalse(os.path.exists(self.snap))

    def test_a_broken_island_py_is_skipped(self):
        fake = FakeIsland()
        fake.fail_status = True
        with mock.patch("sys.stderr"):
            self.assertEqual(theme.island_handoff(ORCHARD, run=fake), [])
        self.assertFalse(os.path.exists(self.snap))
        with mock.patch("sys.stderr"):
            self.assertEqual(theme.island_handoff(ORCHARD, run=lambda *a, **k: None), [])

    def test_wanted_normalises(self):
        self.assertEqual(theme.island_wanted(ORCHARD), {"style": "notch", "match_bar": True, "enabled": True})
        self.assertEqual(theme.island_wanted({"island.style": "bogus", "island.enabled": "maybe"}), {})
        self.assertEqual(theme.island_wanted(PLAIN), {})

    def test_cmd_set_hands_over_after_apply(self):
        order = []
        with mock.patch.object(theme, "exists", return_value=True), \
                mock.patch.object(theme, "load", return_value=dict(ORCHARD, anim="spring")), \
                mock.patch.object(theme, "read_state", return_value={"fade": "off", "theme": "orchard"}), \
                mock.patch.object(theme, "write_state"), \
                mock.patch.object(theme, "apply", side_effect=lambda c: order.append("apply") or []), \
                mock.patch.object(theme, "island_handoff", side_effect=lambda c: order.append("island")), \
                mock.patch.object(theme, "switch_sound", side_effect=lambda: order.append("sound")), \
                mock.patch.object(theme, "gtk4_restart", return_value=True):
            theme.cmd_set("orchard")
        self.assertEqual(order, ["apply", "island", "sound"])

    def test_apply_alone_never_touches_the_island(self):
        with mock.patch.object(theme, "island_handoff") as handoff, \
                mock.patch.object(theme, "write_generated", return_value=[]), \
                mock.patch.object(theme, "apply_gsettings"), mock.patch.object(theme, "apply_cursor"), \
                mock.patch.object(theme, "run"), mock.patch.object(theme, "wallpaper_matches", return_value=True):
            theme.apply(dict(ORCHARD))
        handoff.assert_not_called()

    def test_styles_agree_with_island_py(self):
        self.assertEqual(tuple(theme.ISLAND_STYLES), tuple(island.STYLES))

    def test_island_defaults_untouched(self):
        self.assertFalse(island.DEFAULTS["enabled"])
        self.assertEqual(island.DEFAULTS["style"], "notch")


class Lint(unittest.TestCase):
    GOOD = {"gtk_button_layout": "appmenu:close", "hypr.rounding_power": "2.6",
            "hypr.shadow_offset": "0 14", "hypr.shadow_color_inactive": "rgba(00000030)",
            "island.enabled": "yes", "island.style": "notch", "island.match_bar": "no",
            "bar.clock": "menubar", "bar.logo": "", "bar.workspaces": "dots"}

    def test_good_is_quiet(self):
        self.assertEqual(theme.check_layout_keys(self.GOOD), [])
        self.assertEqual(theme.check_layout_keys(dict(theme.DEFAULTS)), [])

    def test_bad_values_are_named(self):
        for key, bad in (("island.style", "bogus"), ("island.enabled", "maybe"), ("island.match_bar", "1"),
                         ("gtk_button_layout", "bad!"), ("gtk_button_layout", "close:min"),
                         ("gtk_button_layout", "close::"), ("hypr.rounding_power", "11"),
                         ("hypr.shadow_offset", "14"), ("hypr.shadow_color_inactive", "#000000"),
                         ("bar.clock", "left"), ("bar.workspaces", "pips"), ("bar.logo", "Orchard")):
            problems = theme.check_layout_keys(dict(self.GOOD, **{key: bad}))
            self.assertEqual(len(problems), 1, (key, bad, problems))
            self.assertIn(key, problems[0])

    def test_button_layouts(self):
        for ok in ("appmenu:close", "close,minimize,maximize:", ":close", "", "icon,spacer:minimize,close"):
            self.assertTrue(theme.button_layout_ok(ok), ok)
        for bad in ("bad!", "close:min", "a:b:c", "Close:"):
            self.assertFalse(theme.button_layout_ok(bad), bad)

    def test_new_keys_are_known(self):
        for key in ("island.enabled", "island.style", "island.match_bar", "bar.clock", "bar.logo",
                    "bar.workspaces", "gtk_button_layout", "hypr.rounding_power", "hypr.shadow_offset",
                    "hypr.shadow_color_inactive", "dock.start", "dock.magnify", "bar.network"):
            self.assertIn(key, theme.KNOWN, key)

    def test_cyberpunk_documents_every_new_key(self):
        own = theme.read_kv(os.path.join(theme.THEMES_DIR, "cyberpunk", "theme.conf")) or {}
        for key in ("island.enabled", "island.style", "island.match_bar", "bar.clock", "bar.logo",
                    "bar.workspaces", "gtk_button_layout", "hypr.rounding_power", "hypr.shadow_offset",
                    "hypr.shadow_color_inactive", "dock.start", "dock.magnify", "bar.network"):
            self.assertIn(key, own, key)
        self.assertEqual(own["gtk_button_layout"], theme.DEFAULTS["gtk_button_layout"])


class Bar(unittest.TestCase):
    def test_bar_text(self):
        text = theme.bar_text({"id": "orchard", "bar.clock": "menubar", "bar.logo": ""})
        self.assertIn("clock=menubar\n", text)
        self.assertIn("logo=\n", text)
        self.assertTrue(text.startswith("# GENERATED"))
        plain = theme.bar_text({"id": "cyberpunk"})
        self.assertIn("clock=\n", plain)
        self.assertIn("logo=\n", plain)
        self.assertIn("magnify=\n", plain)
        self.assertIn("magnify=yes\n", theme.bar_text({"id": "orchard", "dock.magnify": "yes"}))

    def test_vendor_colours(self):
        """The CPU / GPU pills' makers' colours: one hue per maker, the
        theme's lightness, a CPU shade apart from the GPU's."""
        def hue(c):
            _l, a, b = theme.oklab(c)
            return __import__("math").atan2(b, a)
        for t in ("cyberpunk", "win95", "orchard", "luna"):
            conf = theme.load(t)
            out = theme.vendor_colors(conf)
            self.assertEqual(set(out), {f"{p}_{m}" for p in ("cpu", "gpu") for m in ("amd", "nvidia", "intel")})
            for maker, base in theme.VENDOR_HUES.items():
                self.assertNotEqual(out[f"cpu_{maker}"], out[f"gpu_{maker}"], (t, maker))
                self.assertAlmostEqual(hue(out[f"gpu_{maker}"]), hue(base), delta=0.2)
                lo, hi = theme.VENDOR_L
                self.assertTrue(lo - 0.02 <= theme.oklab(out[f"gpu_{maker}"])[0] <= hi + 0.02, (t, maker))
        dark_text = theme.vendor_colors(theme.load("win95"))
        self.assertLess(theme.oklab(dark_text["cpu_amd"])[0], theme.oklab(dark_text["gpu_amd"])[0])
        light_text = theme.vendor_colors(theme.load("cyberpunk"))
        self.assertGreater(theme.oklab(light_text["cpu_amd"])[0], theme.oklab(light_text["gpu_amd"])[0])
        text = theme.colors_text(dict(theme.load("cyberpunk"), **{"color.gpu_amd": "#123456"}))
        self.assertIn("gpu_amd=#123456\n", text)                       # a theme's own shade wins
        self.assertIn("cpu_intel=#", text)

    def test_orchard_cpu_and_gpu_differ(self):
        for t in ("orchard", "orchard-dark"):
            conf = theme.load(t)
            self.assertNotEqual(conf["color.cpu"], conf["color.gpu"], t)

    def test_network_key(self):
        """bar.network: written to bar.conf as network=, which network.py
        reads; moe sets it, everything else leaves the usual pill."""
        self.assertIn("network=icon\n", theme.bar_text({"id": "moe", "bar.network": "icon"}))
        self.assertIn("network=\n", theme.bar_text({"id": "cyberpunk"}))
        for good in ("", "icon"):
            self.assertEqual(theme.check_layout_keys({"bar.network": good}), [], good)
        self.assertEqual(len(theme.check_layout_keys({"bar.network": "text"})), 1)

    def test_dock_keys(self):
        """dock.start and dock.magnify: what dock.py reads from bar.conf, and
        which themes set them (the orchard pair magnify, the dark one by
        inheriting it)."""
        for good in ("", "yes", "no"):
            self.assertEqual(theme.check_layout_keys({"dock.magnify": good}), [], good)
        bad = theme.check_layout_keys({"dock.magnify": "always"})
        self.assertEqual(len(bad), 1)
        self.assertIn("dock.magnify", bad[0])
        self.assertTrue(theme.check_layout_keys({"dock.start": "a much too long word"}))
        for name, magnify in (("orchard", "yes"), ("orchard-dark", "yes"), ("cyberpunk", ""), ("win95", "")):
            conf = theme.load(name, user=False, season="")
            self.assertEqual(conf.get("dock.magnify", ""), magnify, name)
            self.assertEqual(theme.check_layout_keys(conf), [], name)
        self.assertEqual(theme.load("win95", user=False, season="")["dock.start"], "Start")

    def test_write_generated_writes_bar_conf(self):
        written = {}
        gen = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, gen, True)
        with mock.patch.object(theme, "GEN", gen), mock.patch.object(theme, "write_if_changed",
                               side_effect=lambda p, t: written.__setitem__(p, t) or True), \
                mock.patch.object(theme, "write_terminals", return_value=[]), \
                mock.patch.object(theme, "fix_wofi_import", return_value=False), \
                mock.patch.object(theme, "generated_text", return_value=""):
            changed = theme.write_generated({"id": "orchard", "bar.clock": "menubar", "bar.logo": "x"})
        self.assertIn("bar", changed)
        self.assertEqual(theme.bar_conf(), os.path.join(theme.GEN, "bar.conf"))
        self.assertIn("clock=menubar", written[os.path.join(gen, "bar.conf")])

    def test_dots_and_numbers(self):
        dots = json.loads(theme.modules_text({"bar.workspaces": "dots", "lang": "en"}))["ext/workspaces"]
        self.assertEqual(dots["format"], "{icon}")
        self.assertEqual(dots["format-icons"], {"active": "●", "default": "○"})
        plain = json.loads(theme.modules_text({"lang": "en"}))["ext/workspaces"]
        self.assertEqual(plain, {"format": "{name}"})
        ja = json.loads(theme.modules_text({"bar.workspaces": "dots", "lang": "ja"}))["ext/workspaces"]
        self.assertEqual(ja["format-icons"]["1"], "一")       # the kanji win


class Presets(unittest.TestCase):
    def test_three_lists_agree(self):
        lua = open(os.path.join(os.path.dirname(helpers.SCRIPTS), "lua", "display.lua")).read()
        m = re.search(r"^M\.presets\s*=\s*\{([^}]*)\}", lua, re.M)
        self.assertIsNotNone(m)
        in_lua = re.findall(r'"([a-z]+)"', m.group(1))
        self.assertEqual(list(theme.PRESETS), in_lua)
        self.assertEqual(list(display.PRESETS), in_lua)
        self.assertIn("spring", in_lua)
        # every preset has a table, and spring's curves are defined
        for name in in_lua:
            self.assertRegex(lua, rf"\n    {name} = \{{")
        for curve in ("spring", "macEase", "macExit", "spaceSlide"):
            self.assertIn(f'hl.curve("{curve}"', lua)


if __name__ == "__main__":
    unittest.main()
