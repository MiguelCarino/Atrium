"""The launcher's keyboard shortcuts (scripts/launcher_shortcuts.py): the
rows made from a `hyprctl binds -j` reply, the words that find them, and the
Lua chunk that runs one -- all pure; nothing here reaches Hyprland."""
import unittest

import helpers

S = helpers.import_script("launcher_shortcuts.py")


def bind(key, mask, desc, **extra):
    return dict({"key": key, "modmask": mask, "description": desc, "submap": "", "mouse": False,
                 "dispatcher": "__lua", "arg": "1"}, **extra)


BINDS = [
    bind("Q", 8, "Apps: Terminal"),
    bind("S", 64, "Screenshots: Region to clipboard (no file)"),
    bind("S", 65, "Screenshots: Annotate region (satty)"),
    bind("left", 9, "Windows: Swap"),
    bind("Q", 8, "Apps: Terminal"),                         # the same one twice: listed once
    bind("X", 8, ""),                                       # no description: not a shortcut to list
    bind("escape", 0, "Resize: leave", submap="resize"),    # inside a submap
    bind("mouse:272", 8, "Windows: Move by dragging", mouse=True),
]


class Entries(unittest.TestCase):
    def test_described_binds_once_each(self):
        rows = S.entries(BINDS)
        self.assertEqual([r["desc"] for r in rows], ["Apps: Terminal", "Screenshots: Region to clipboard (no file)",
                                                     "Screenshots: Annotate region (satty)", "Windows: Swap"])

    def test_fields(self):
        row = S.entries(BINDS)[3]
        self.assertEqual(row["keys"], "ALT+SHIFT+LEFT")
        self.assertEqual(row["label"], "ALT + SHIFT + ←")
        self.assertEqual((row["section"], row["text"]), ("Windows", "Swap"))

    def test_junk_reply(self):
        self.assertEqual(S.entries(None), [])
        self.assertEqual(S.entries(["x", 3, {}]), [])


class Words(unittest.TestCase):
    def test_pretty_keys(self):
        self.assertEqual(S.pretty_keys("SUPER+Return"), "SUPER + Enter")
        self.assertEqual(S.pretty_keys("ALT+q"), "ALT + Q")
        self.assertEqual(S.pretty_keys(""), "")

    def test_wants_only(self):
        self.assertEqual(S.wants_only("keys super s"), "super s")
        self.assertEqual(S.wants_only("keys"), "")
        self.assertEqual(S.wants_only("  Shortcuts screen"), "screen")
        self.assertIsNone(S.wants_only("keyboard"))
        self.assertIsNone(S.wants_only("terminal"))

    def test_word_hits(self):
        term, region = S.entries(BINDS)[0], S.entries(BINDS)[1]
        self.assertTrue(S.word_hits(term, "alt"))
        self.assertTrue(S.word_hits(term, "q"))
        self.assertTrue(S.word_hits(term, "term"))
        self.assertTrue(S.word_hits(region, "shot"))      # 3+ letters anywhere
        self.assertFalse(S.word_hits(term, "t"))          # one letter: a key only
        self.assertFalse(S.word_hits(term, "super"))

    def test_matches_puts_the_exact_keys_first(self):
        rows = S.entries(BINDS)
        got = S.matches(rows, "super s")
        self.assertEqual([r["keys"] for r in got], ["SUPER+S", "SUPER+SHIFT+S"])
        self.assertEqual(len(S.matches(rows, "")), len(rows))
        self.assertEqual(S.matches(rows, "zzz"), [])


class Running(unittest.TestCase):
    def test_lua_quote(self):
        self.assertEqual(S.lua_quote('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')
        self.assertEqual(S.lua_quote("ñ →"), '"ñ →"')
        self.assertEqual(S.lua_quote("\x01"), '"\\001"')

    def test_run_lua_looks_the_bind_up(self):
        chunk = S.run_lua("ALT+Q", 'Apps: "Terminal"')
        self.assertIn('local want, desc = "ALT+Q", "Apps: \\"Terminal\\""', chunk)
        self.assertIn("userbinds", chunk)
        self.assertIn("hl.dispatch(e.dsp)", chunk)
        self.assertTrue(chunk.rstrip().endswith("return 'none'"))

    def test_spawn_argv_keeps_the_words_out_of_the_shell(self):
        entry = S.entries([bind("Q", 8, "Apps: $(rm -rf ~)")])[0]
        argv = S.spawn_argv(entry, "/x/notify", delay=0.1)
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertNotIn("rm -rf", argv[2])               # the script itself never holds the text
        self.assertEqual(argv[4:], ["0.1", S.run_lua("ALT+Q", "Apps: $(rm -rf ~)"), "/x/notify",
                                    "Apps: $(rm -rf ~)", "ALT + Q"])


if __name__ == "__main__":
    unittest.main()
