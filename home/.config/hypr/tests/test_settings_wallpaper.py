"""Settings > Wallpaper & lock screen: lock-screen.py's hyprlock.conf editing
(parse / change / render, on a copy of the real file's shape, never the file
itself) and wallpaper-slideshow.py's options and name-order picking. Pure
functions only: no hyprctl, no hyprlock, nothing written outside the
scratch folder."""
import os
import unittest

import helpers

lock = helpers.import_script("lock-screen.py")
slide = helpers.import_script("wallpaper-slideshow.py")

CONF = """\
# header comment, kept
$font_text    = Rajdhani SemiBold

background {
    monitor =
    path = screenshot
    blur_passes = 3
    blur_size = 8
    brightness = 0.35
}

input-field {
    monitor = DP-1
    placeholder_text = <span foreground="##00f0ff">ENTER</span>
}

# Clock
label {
    monitor = DP-1
    text = $TIME
    color = rgb(0, 240, 255)
}

# Date
label {
    monitor = DP-1
    text = cmd[update:60000] date +"%A // %d %B" | tr a-z A-Z
}

# Layout
label {
    monitor = DP-1
    text = $LAYOUT[US,LATAM]
}
"""


def edit(text, *commands):
    items = lock.parse(text)
    for command, *args in commands:
        lock.change(items, command, list(args))
    return lock.render(items)


class Parsing(unittest.TestCase):
    def test_round_trip_is_exact(self):
        self.assertEqual(lock.render(lock.parse(CONF)), CONF)

    def test_status(self):
        st = lock.status(lock.parse(CONF))
        self.assertEqual(st["background"], "screenshot")
        self.assertEqual(st["blur"], 3)
        self.assertEqual(st["dim"], 0.35)
        self.assertEqual(st["clock"], "24h")
        self.assertTrue(st["date"])
        self.assertTrue(st["layout"])
        self.assertFalse(st["user"])
        self.assertEqual(st["message"], "")
        self.assertEqual(st["screen"], "DP-1")

    def test_hash_escape_kept_in_values(self):
        field = lock.blocks(lock.parse(CONF), kind="input-field")[0]
        self.assertIn("##00f0ff", field.get("placeholder_text"))

    def test_trailing_comment_is_not_the_value(self):
        b = lock.parse("label {\n    text = $TIME  # the clock\n}\n")[0]
        self.assertEqual(b.get("text"), "$TIME")


class Editing(unittest.TestCase):
    def test_clock_12h_and_back(self):
        out = edit(CONF, ("clock", "12h"))
        self.assertIn("text = $TIME12\n", out)
        self.assertEqual(edit(out, ("clock", "24h")), CONF)

    def test_date_off_and_back_restores_the_block(self):
        out = edit(CONF, ("date", "off"))
        self.assertIn(lock.OFF + "label {", out)
        self.assertFalse(lock.status(lock.parse(out))["date"])
        self.assertTrue(lock.balanced(out))
        self.assertEqual(edit(out, ("date", "on")), CONF)

    def test_user_added_in_the_clock_style(self):
        out = edit(CONF, ("user", "on"))
        self.assertTrue(lock.status(lock.parse(out))["user"])
        user = lock.blocks(lock.parse(out), "user")[0]
        self.assertEqual(user.get("monitor"), "DP-1")
        self.assertEqual(user.get("color"), "rgb(0, 240, 255)")
        self.assertEqual(user.get("font_family"), "$font_text")
        self.assertTrue(lock.balanced(out))

    def test_message_escaped_and_read_back(self):
        text = "Call <me> #1 & thanks"
        out = edit(CONF, ("message", text))
        self.assertIn("text = Call &lt;me&gt; ##1 &amp; thanks\n", out)
        self.assertEqual(lock.status(lock.parse(out))["message"], text)
        cleared = edit(out, ("message", ""))
        self.assertEqual(lock.status(lock.parse(cleared))["message"], "")
        again = edit(cleared, ("message", "hi"))
        self.assertEqual(len(lock.blocks(lock.parse(again), "message")), 1)

    def test_message_never_runs_or_substitutes(self):
        # hyprlock runs a label whose text starts with cmd[ as a shell
        # command, and swaps $USER / hyprlang $variables in: a message must
        # show as typed instead.
        text = "cmd[update:1] echo $USER"
        out = edit(CONF, ("message", text))
        line = next(ln for ln in out.splitlines() if "md[update:1]" in ln)
        self.assertNotIn("$", line)
        self.assertNotIn("= cmd[", line)
        self.assertEqual(lock.status(lock.parse(out))["message"], text)

    def test_message_is_one_line(self):
        out = edit(CONF, ("message", "a\nb"))
        self.assertEqual(lock.status(lock.parse(out))["message"], "a b")

    def test_screen_every_and_back(self):
        out = edit(CONF, ("screen",))
        st = lock.status(lock.parse(out))
        self.assertEqual(st["screen"], "")
        self.assertEqual(edit(out, ("screen", "DP-1")), CONF)

    def test_blur_dim(self):
        out = edit(CONF, ("blur", "1"), ("dim", "0.7"))
        st = lock.status(lock.parse(out))
        self.assertEqual((st["blur"], st["dim"]), (1, 0.7))
        for bad in (("blur", "9"), ("dim", "3"), ("clock", "25h"), ("date", "maybe"), ("screen", "a b")):
            with self.assertRaises(ValueError):
                edit(CONF, bad)

    def test_colour(self):
        out = edit(CONF, ("background", "color", "#0a0c14"))
        st = lock.status(lock.parse(out))
        self.assertEqual(st["background"], "color")
        self.assertEqual(st["color"], "rgb(0a0c14)")
        with self.assertRaises(ValueError):
            edit(CONF, ("background", "color", "red; exec"))

    def test_wallpaper_copies_and_back(self):
        items = lock.parse(CONF)
        lock.set_background(items, "wallpaper", outputs=["DP-1", "DP-2", "HDMI-A-1"])
        out = lock.render(items)
        st = lock.status(lock.parse(out))
        self.assertEqual(st["background"], "wallpaper")
        self.assertEqual(st["copies"], ["DP-2", "HDMI-A-1"])
        self.assertEqual(st["path"], os.path.join(lock.LOCK_LINKS, "DP-1"))
        # Every block names its screen, so no screen gets two backgrounds.
        self.assertEqual([b.get("monitor") for b in lock.blocks(lock.parse(out), kind="background")],
                         ["DP-1", "DP-2", "HDMI-A-1"])
        # Settings made after are on the copies too, and a second switch to
        # wallpaper does not pile up copies.
        items = lock.parse(out)
        lock.change(items, "blur", ["1"])
        lock.set_background(items, "wallpaper", outputs=["DP-1", "DP-2", "HDMI-A-1"])
        self.assertEqual([b.get("blur_passes") for b in lock.blocks(items, kind="background")], ["1"] * 3)
        lock.change(items, "blur", ["3"])
        lock.change(items, "background", ["screenshot"])
        self.assertEqual(lock.render(items), CONF)

    def test_unbalanced_is_caught(self):
        self.assertFalse(lock.balanced("label {\n"))
        self.assertTrue(lock.balanced(CONF))


class SlideshowOptions(unittest.TestCase):
    def test_defaults_and_clamping(self):
        self.assertEqual(slide.options_from({}), {"interval": slide.INTERVAL, "auto": True, "shuffle": True})
        self.assertEqual(slide.options_from({"interval": "5"})["interval"], 60)
        self.assertEqual(slide.options_from({"interval": "junk"})["interval"], slide.INTERVAL)
        self.assertFalse(slide.options_from({"auto": "off"})["auto"])

    def test_save_load(self):
        old = slide.OPTIONS
        slide.OPTIONS = os.path.join(helpers.SCRATCH, "state", "hypr", "wallpaper-slideshow.conf")
        try:
            slide.save_options({"interval": 900, "auto": False, "shuffle": False})
            self.assertEqual(slide.load_options(), {"interval": 900, "auto": False, "shuffle": False})
        finally:
            slide.OPTIONS = old

    def test_switch_value(self):
        self.assertTrue(slide.switch_value("toggle", False))
        self.assertFalse(slide.switch_value("off", True))
        with self.assertRaises(ValueError):
            slide.switch_value("maybe", True)

    def test_name_order(self):
        pool = ["/w/a.png", "/w/b.png", "/w/c.png"]
        self.assertEqual(slide.next_in_order(pool, "/w/a.png"), "/w/b.png")
        self.assertEqual(slide.next_in_order(pool, "/w/c.png"), "/w/a.png")
        self.assertEqual(slide.next_in_order(pool, "/other/b.png"), "/w/c.png")   # by name
        self.assertEqual(slide.next_in_order(pool, "/w/bb.png"), "/w/c.png")      # gone: the next after it
        self.assertEqual(slide.next_in_order(pool, ""), "/w/a.png")
        self.assertIsNone(slide.next_in_order([], "/w/a.png"))

    def test_lock_link(self):
        old = slide.LOCK_LINKS
        slide.LOCK_LINKS = os.path.join(helpers.SCRATCH, "cache", "lock")
        try:
            target = os.path.join(helpers.SCRATCH, "pic.png")
            open(target, "w").close()
            slide.link_for_lock("DP-9", target)
            slide.link_for_lock("DP-9", target)         # replacing works
            self.assertEqual(os.readlink(os.path.join(slide.LOCK_LINKS, "DP-9")), target)
        finally:
            slide.LOCK_LINKS = old


if __name__ == "__main__":
    unittest.main()
