"""The desk pages' pure helpers: Notes inbox (parse / remove a line / the
sub line), Colour picker (the history file, the rgb / hsl forms, taking
one out), Window switcher (switcher_conf.py: the file, the checks, which
windows in which order; the page's lines), Work hours (chips, days, the
zone check, the typed start-end order, the state line), the on-screen
keyboard rows of Accessibility, and the capture page's encoder note. Also:
every new page's PAGE is literal (the launcher reads it from the source).

Hermetic: files are scratch paths; nothing runs colorpick.sh, workhours.py
or hyprctl."""
import os
import tempfile
import unittest

import helpers

sconf = helpers.import_script("switcher_conf.py")


def page(name):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    import importlib
    return importlib.import_module(f"settings_pages.{name}")


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.notes = page("notes")
            cls.colorpick = page("colorpick")
            cls.switcher = page("switcher")
            cls.workhours = page("workhours")
            cls.a11y = page("accessibility")
            cls.capture = page("capture")
        except Exception as exc:     # noqa: BLE001
            raise unittest.SkipTest(f"settings pages not importable: {exc}")

    def test_pages_are_literal_and_found(self):
        from settings_pages import _catalog as C
        pages = {p["id"]: p for p in C.read_pages()}
        for mod, pid, parent in ((self.notes, "notes", "capture"), (self.colorpick, "colorpick", "capture"),
                                 (self.switcher, "switcher", "windows"), (self.workhours, "workhours", "timers")):
            self.assertEqual(pages[pid], mod.PAGE)
            self.assertEqual(mod.PAGE.get("parent"), parent)
        self.assertEqual(C.resolve(list(pages.values()), "colour picker"), "colorpick")
        self.assertEqual(C.resolve(list(pages.values()), "on-screen keyboard"), "accessibility")

    # -- notes -------------------------------------------------------------------------
    def test_parse_inbox(self):
        home = os.path.expanduser("~")
        text = ("# Inbox\n\nQuick notes. Newest at the bottom.\n\n"
                "- 2026-10-28 02:14  (inbox created)\n"
                "- 2026-10-28 09:41  [memo](~/Documents/Memos/a.opus) what was said\n"
                "a hand-written line\n")
        notes = self.notes.parse_inbox(text)
        self.assertEqual([(n["index"], n["when"], n["text"]) for n in notes],
                         [(4, "2026-10-28 02:14", "(inbox created)"), (5, "2026-10-28 09:41", "what was said")])
        self.assertIsNone(notes[0]["memo"])
        self.assertEqual(notes[1]["memo"], os.path.join(home, "Documents/Memos/a.opus"))
        self.assertEqual(self.notes.note_sub(notes[1], "2026-10-28"), "voice memo  ·  today 09:41")
        self.assertEqual(self.notes.note_sub(notes[0], "2026-10-29"), "2026-10-28 02:14")

    def test_remove_note(self):
        text = "# Inbox\n- 2026-10-28 02:14  a\n- 2026-10-28 03:00  b\n"
        self.assertEqual(self.notes.remove_note(text, 2, "- 2026-10-28 03:00  b"),
                         "# Inbox\n- 2026-10-28 02:14  a\n")
        # The file moved on (a line added above): the same line still goes.
        moved = "# Inbox\n- new\n" + text.split("\n", 1)[1]
        self.assertEqual(self.notes.remove_note(moved, 1, "- 2026-10-28 02:14  a"),
                         "# Inbox\n- new\n- 2026-10-28 03:00  b\n")
        self.assertIsNone(self.notes.remove_note(text, 1, "- gone"))
        self.assertEqual(self.notes.short("a  b\nc"), "a b c")
        self.assertEqual(len(self.notes.short("x" * 300, 90)), 90)

    def test_inbox_write_round_trip(self):
        with tempfile.TemporaryDirectory(dir=helpers.SCRATCH) as d:
            path = os.path.join(d, "inbox.md")
            self.assertIsNone(self.notes.read_inbox(path))
            self.notes.write_inbox("- 2026-10-28 02:14  a\n", path)
            self.assertEqual(self.notes.read_inbox(path), "- 2026-10-28 02:14  a\n")

    # -- colour picker -----------------------------------------------------------------
    def test_colour_history(self):
        cp = self.colorpick
        colours = cp.read_history("#FF8000\nnot a colour\n#00aaff\n#ff8000\n")
        self.assertEqual(colours, ["#ff8000", "#00aaff"])
        self.assertEqual(cp.forms("#ff8000"), "rgb(255, 128, 0)  ·  hsl(30, 100%, 50%)")
        self.assertEqual(cp.without(colours, "#FF8000"), "#00aaff\n")
        self.assertIn("background='#00aaff'", cp.swatch_markup("#00aaff"))

    # -- window switcher ---------------------------------------------------------------
    def test_switcher_conf(self):
        with tempfile.TemporaryDirectory(dir=helpers.SCRATCH) as d:
            path = os.path.join(d, "switcher.conf")
            self.assertEqual(sconf.read_conf(path), {"scope": "all", "order": "recent", "special": "on", "lines": "15"})
            sconf.write_conf({"scope": "monitor", "order": "recent", "lines": "25"}, path)
            with open(path) as handle:
                self.assertNotIn("order=", handle.read())       # defaults are not written
            with open(path, "a") as handle:
                handle.write("lines=99\n")
            self.assertEqual(sconf.read_conf(path)["lines"], "25")
            self.assertEqual(sconf.read_conf(path)["scope"], "monitor")
        with self.assertRaises(ValueError):
            sconf.check("scope", "everything")
        with self.assertRaises(ValueError):
            sconf.check("colour", "red")

    def test_switcher_arrange(self):
        clients = [
            {"address": "a", "mapped": True, "focusHistoryID": 2, "monitor": 0, "workspace": {"id": 3, "name": "3"}},
            {"address": "b", "mapped": True, "focusHistoryID": 0, "monitor": 1, "workspace": {"id": 5, "name": "5"}},
            {"address": "c", "mapped": True, "focusHistoryID": 1, "monitor": 0,
             "workspace": {"id": -98, "name": "special:term"}},
            {"address": "d", "mapped": False, "focusHistoryID": 3, "monitor": 0, "workspace": {"id": 3, "name": "3"}},
        ]
        conf = dict(sconf.read_conf("/nonexistent"))
        addr = lambda cs: [c["address"] for c in cs]  # noqa: E731
        self.assertEqual(addr(sconf.arrange(clients, conf)), ["b", "c", "a"])
        self.assertEqual(addr(sconf.arrange(clients, dict(conf, order="workspace"))), ["a", "b", "c"])
        self.assertEqual(addr(sconf.arrange(clients, dict(conf, special="off"))), ["b", "a"])
        self.assertEqual(addr(sconf.arrange(clients, dict(conf, scope="workspace"), workspace_id=3)), ["a"])
        self.assertEqual(addr(sconf.arrange(clients, dict(conf, scope="monitor"), monitor_id=0)), ["c", "a"])
        self.assertEqual(sconf.lines(dict(conf, lines="20")), 20)
        self.assertFalse(sconf.wired("/nonexistent/window-switcher.py"))

    def test_switcher_page_lines(self):
        sw = self.switcher
        self.assertEqual(sw.choice_sub("lines", "20", "15"), "20 rows, then it scrolls")
        self.assertTrue(sw.choice_sub("scope", "all", "all").endswith("the default"))
        self.assertEqual({k for k, *_ in sw.CHOICES}, set(sconf.KEYS))

    # -- work hours --------------------------------------------------------------------
    def test_workhours_helpers(self):
        wh = self.workhours
        self.assertEqual(wh.clock_chips(["08:00", "09:00"], "08:30"),
                         [("08:00", "08:00"), ("08:30", "08:30"), ("09:00", "09:00")])
        self.assertEqual(wh.days_arg(["mon", "tue"], "sun"), "mon,tue,sun")
        self.assertEqual(wh.days_arg(["mon"], "mon"), "none")
        zones = {"America/New_York", "Europe/Lisbon"}
        self.assertEqual(wh.check_zone("", zones), "")
        self.assertEqual(wh.check_zone(" europe/lisbon ", zones), "Europe/Lisbon")
        with self.assertRaises(ValueError):
            wh.check_zone("Mars/Base", zones)
        self.assertEqual(wh.holiday_items(["mx"]), [("", "None"), ("mx", "Mexico")])
        self.assertEqual(wh.holiday_items(["zz"])[1], ("zz", "ZZ"))
        self.assertEqual(wh.minutes("7:45"), 465)
        self.assertIsNone(wh.minutes("25:00"))
        self.assertEqual(wh.custom_order("19:00", "23:00", "18:00"), (("end", "23:00"), ("start", "19:00")))
        self.assertEqual(wh.custom_order("7:45", "16:15", "18:00"), (("start", "7:45"), ("end", "16:15")))

    def test_workhours_state_text(self):
        wh = self.workhours
        self.assertTrue(wh.state_text({"enabled": False}).startswith("off"))
        work = {"enabled": True, "working": True, "until": 1000 + 3 * 3600 + 5 * 60, "start": "09:00",
                "end": "18:00", "days": ["mon", "tue", "wed", "thu", "fri"], "reason": ""}
        self.assertEqual(wh.state_text(work, now=1000), "work time, 3 h 05 min left  ·  09:00–18:00, Mon–Fri")
        free = dict(work, working=False, reason="weekend", days=["sat"])
        self.assertEqual(wh.state_text(free), "free now (weekend)  ·  09:00–18:00, Sat")

    # -- accessibility: the on-screen keyboard ----------------------------------------
    def test_osk_rows(self):
        a = self.a11y
        self.assertEqual(a.osk_sub(None), "osk.py did not answer")
        self.assertIn("not installed", a.osk_sub({"keyboard": None}))
        self.assertTrue(a.osk_sub({"keyboard": "wvkbd", "shown": True}).startswith("showing  ·  wvkbd"))
        self.assertNotIn("SUPER", a.osk_sub({"keyboard": "wvkbd", "shown": True}))     # no key bound yet
        self.assertIn("SUPER+CTRL+K", a.osk_sub({"keyboard": "wvkbd", "key": "SUPER+CTRL+K"}))
        self.assertIn("only squeekboard", a.osk_auto_sub({"keyboard": "wvkbd", "auto_supported": False}))
        self.assertTrue(a.osk_auto_sub({"keyboard": "squeekboard", "auto_supported": True,
                                        "settings": {"auto": "on"}}).startswith("on:"))

    # -- capture: the encoder note -----------------------------------------------------
    def test_encoder_note(self):
        c = self.capture
        self.assertEqual(c.encoder_note("auto"), "")
        self.assertIn("30 fps", c.encoder_note("cpu"))
        self.assertIn("does not read", c.encoder_note("auto", followed=False))
        self.assertIn("gamemode_shader", [k for k, *_ in c.STRIP])
        self.assertEqual([k for k, _ in c.ENCODERS], ["auto", "gpu", "cpu"])


class CaptureKeys(unittest.TestCase):
    def test_new_keys(self):
        cap = helpers.import_script("capture-settings.py")
        self.assertEqual(cap.check("rec_encoder", "cpu"), "cpu")
        self.assertEqual(cap.check("gamemode_shader", "off"), "off")
        with self.assertRaises(ValueError):
            cap.check("rec_encoder", "nvenc")
        vals, _bad = cap.values({})
        self.assertEqual((vals["rec_encoder"], vals["gamemode_shader"]), ("auto", "on"))
        self.assertEqual([cap.encoder_env(v) for v in ("auto", "gpu", "cpu")], ["", "gpu", "cpu"])
        self.assertFalse(cap.record_reads("rec_encoder", "/nonexistent/record.sh"))


class LockDate(unittest.TestCase):
    def test_date_template_follows_theme(self):
        lock = helpers.import_script("lock-screen.py")
        self.assertEqual(lock.date_format("$lock_date = %^A // %d %^B\n"), "$lock_date")
        self.assertEqual(lock.date_format("$font_text = Sans\n"), "%A, %d %B")
        items = lock.parse("$lock_date = %A\n")
        block = lock.add_block(items, "date")
        self.assertEqual(block.get("text"), 'cmd[update:60000] date +"$lock_date"')


class IslandSig(unittest.TestCase):
    def test_notch_text_sig(self):
        island = helpers.import_script("island.py")
        texts = {"clock": "9:59 PM", "day": "Wed 28"}
        self.assertEqual(island.notch_text_sig(lambda k: texts[k]), (7, 6))
        texts["clock"] = "10:00 PM"
        self.assertEqual(island.notch_text_sig(lambda k: texts[k]), (8, 6))

        def broken(_k):
            raise OSError("no clock")
        self.assertIsNone(island.notch_text_sig(broken))


class SwitchWarning(unittest.TestCase):
    def test_default_is_effective_main_mod(self):
        ins = helpers.import_script("input-settings.py")
        old = ins.effective
        self.addCleanup(setattr, ins, "effective", old)
        ins.effective = lambda *a, **k: {"main_mod": "SUPER"}
        self.assertIn("SUPER+ALT+L", ins.switch_warning("grp:alt_shift_toggle"))
        ins.effective = lambda *a, **k: {"main_mod": "ALT"}
        self.assertIn("ALT+SHIFT+1", ins.switch_warning("grp:alt_shift_toggle"))


class NightLightGamemode(unittest.TestCase):
    def run_nl(self, gamemode, capture_conf=None):
        import subprocess
        d = tempfile.mkdtemp(dir=helpers.SCRATCH)
        env = dict(os.environ, NL_STATE_DIR=d, NL_CONF=os.path.join(d, "nl.conf"), NL_DRY="1",
                   NL_BACKEND="shader", NL_GAMEMODE=gamemode, NL_NOW="1800000000", TZ="UTC",
                   XDG_STATE_HOME=d)
        if capture_conf:
            os.makedirs(os.path.join(d, "hypr"), exist_ok=True)
            with open(os.path.join(d, "hypr", "capture.conf"), "w") as handle:
                handle.write(capture_conf)
        script = os.path.join(helpers.SCRIPTS, "nightlight.sh")
        r = subprocess.run([script, "on", "4000"], capture_output=True, text=True, env=env, timeout=10)
        return r.stdout + r.stderr

    def test_shader_held_in_gamemode(self):
        self.assertIn("DRY hold on 4000 via shader", self.run_nl("1"))
        self.assertIn("DRY apply on 4000 via shader", self.run_nl("0"))
        # gamemode_shader=off: gamemode keeps the filter, so night light may too.
        self.assertIn("DRY apply on 4000 via shader", self.run_nl("1", "gamemode_shader=off\n"))


if __name__ == "__main__":
    unittest.main()
