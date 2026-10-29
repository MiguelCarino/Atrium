"""mascot_notify.py and mascot_icons.py (the mascot in notifications):
notify-send's arguments kept, the icon swapped by the switches, generic
icons dropped and an app's own kept as a badge, the voice line, a failure
falling back to the plain notification; every theme's sprite well formed
and rendered at its size."""
import json
import os
import unittest
from unittest import mock

import helpers

import mascot_notify as mn  # noqa: E402  (scripts/ is on the path: helpers)
import mascot_icons as mi  # noqa: E402


def switches(**on):
    os.makedirs(os.path.dirname(mn.STATE), exist_ok=True)
    with open(mn.STATE, "w") as fh:
        json.dump({"notifications": on}, fh)


def icon_of(argv):
    return argv[argv.index("-i") + 1] if "-i" in argv else None


class Arguments(unittest.TestCase):
    def setUp(self):
        switches()
        self.icon = mock.patch.object(mi, "icon", side_effect=lambda t, m, b: f"/c/{m}|{b}.png")
        self.icon.start()

    def tearDown(self):
        self.icon.stop()

    def test_parse(self):
        opts, pos = mn.parse(["-a", "Timer", "--urgency=critical", "-p", "-t", "5", "Tea", "ready"])
        self.assertEqual(pos, ["Tea", "ready"])
        self.assertEqual(mn.get(opts, "-u", "--urgency"), "critical")
        self.assertIn(("-p", None), opts)

    def test_mascot_with_the_apps_icon_as_badge(self):
        argv = mn.argv(["-a", "Timer", "-i", "alarm-symbolic", "--wait", "Tea", "is ready"])
        self.assertEqual(argv[0], "notify-send")
        self.assertEqual(icon_of(argv), "/c/calm|alarm-symbolic.png")
        self.assertEqual(argv[-3:], ["--", "Tea", "is ready"])
        self.assertIn("--wait", argv)

    def test_generic_icon_dropped_and_critical_is_alert(self):
        argv = mn.argv(["-u", "critical", "-i", "dialog-warning", "Oops"])
        self.assertEqual(icon_of(argv), "/c/alert|None.png")
        self.assertEqual(argv.count("-i"), 1)

    def test_mood_given(self):
        self.assertEqual(icon_of(mn.argv(["Done"], mood="relieved")), "/c/relieved|None.png")

    def test_toasts_left_alone_unless_asked(self):
        args = ["-u", "low", "-t", "1200", "Layout", "us"]
        self.assertEqual(mn.argv(args), ["notify-send", *args])
        switches(toasts=True)
        self.assertIsNotNone(icon_of(mn.argv(args)))

    def test_icon_off_changes_nothing(self):
        switches(icon=False)
        args = ["-i", "phone", "Hi"]
        self.assertEqual(icon_of(mn.argv(args)), "phone")

    def test_voice(self):
        switches(voice=True)
        with mock.patch.object(mn, "voice_line", return_value="phew & done") as voice:
            argv = mn.argv(["Railguard", "cc1plus held 14 GB"], mood="relieved", say=("rg_memory", "cc1plus"))
        voice.assert_called_once_with(("rg_memory", "cc1plus"))
        self.assertEqual(argv[-1], "<i>phew &amp; done</i>\ncc1plus held 14 GB")
        with mock.patch.object(mn, "voice_line", return_value=None):
            self.assertEqual(mn.argv(["Plain"])[-1], "Plain")      # calm: no line

    def test_a_failure_sends_it_plain(self):
        with mock.patch.object(mi, "icon", side_effect=OSError("no pillow")):
            self.assertEqual(mn.argv(["-u", "critical", "X"]), ["notify-send", "-u", "critical", "X"])

    def test_drop_in_takes_its_options_anywhere(self):
        with mock.patch.object(mn.os, "execvp") as ex:
            mn.drop_in(["-a", "Railguard", "--mood", "relieved", "--say", "rg_panic|mpv", "T", "--", "--mood"])
        argv = ex.call_args.args[1]
        self.assertEqual(icon_of(argv), "/c/relieved|None.png")
        self.assertEqual(argv[-1], "--mood")                        # after -- it is text


class Sprites(unittest.TestCase):
    def test_every_theme(self):
        import mascots
        self.assertEqual(set(mi.SPRITES), set(mascots.MODULES))
        for theme, make in mi.SPRITES.items():
            palette, rows = make()
            self.assertEqual(len(rows), 16, theme)
            for r in rows:
                self.assertEqual(len(r), 16, theme)
                self.assertTrue(set(r) <= set(palette) | {"."}, f"{theme}: {set(r) - set(palette)}")

    def test_rendered_and_cached(self):
        path = mi.icon("orbit", "alert")
        self.assertTrue(path.startswith(mi.CACHE))
        from PIL import Image
        self.assertEqual(Image.open(path).size, (mi.GRID * mi.SCALE,) * 2)
        self.assertEqual(mi.icon("orbit", "alert"), path)
        self.assertIn("moe-calm", mi.icon("no-such-theme", "no-such-mood"))


class Voices(unittest.TestCase):
    def test_every_mascot_says_railguards_topics(self):
        import importlib
        import mascot_mood
        import mascots
        for theme, module in mascots.MODULES.items():
            lines = importlib.import_module(module).TOPIC_LINES
            for topic in ("rg_memory", "rg_vram", "rg_game_vram", "rg_panic", "rg_stuck", "rg_agents"):
                self.assertIn(topic, lines, f"{theme} has no {topic}")
                said = mascot_mood.word(lines, (topic, "proc"))
                self.assertNotIn("{", said, theme)

    def test_settings_survive_a_mascot_save(self):
        import mascot_mood
        mascot_mood.save_settings(notifications={"voice": True})
        mascot_mood.save_settings(weather=False)
        self.assertTrue(mascot_mood.read_settings()["notifications"]["voice"])
        with self.assertRaises(ValueError):
            mascot_mood.save_settings(notifications={"nope": True})


if __name__ == "__main__":
    unittest.main()
