"""shortcuts.py (Settings > Keyboard shortcuts) and lua/userbinds.lua: reading
and writing userbinds.conf, putting the live binds and the file together,
the change commands' rules, the key-capture helpers -- and userbinds.lua
itself, run by luajit against a stand-in `hl` table. Nothing reaches the
running Hyprland: hyprctl is stubbed, the file lives in the scratch state dir."""
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

import helpers

sc = helpers.import_script("shortcuts.py")
LUA = os.path.join(os.path.dirname(helpers.SCRIPTS), "lua", "userbinds.lua")


def live(key, modmask=0, desc="", submap="", mouse=False):
    return {"key": key, "modmask": modmask, "description": desc, "submap": submap, "mouse": mouse}


class Keys(unittest.TestCase):
    def test_canon_orders_and_upcases(self):
        self.assertEqual(sc.canon("shift + alt+q"), "ALT+SHIFT+Q")
        self.assertEqual(sc.canon("Win+Control+Return"), "SUPER+CTRL+RETURN")
        self.assertEqual(sc.canon("XF86AudioPlay"), "XF86AUDIOPLAY")
        self.assertEqual(sc.canon("SUPER+mouse:272"), "SUPER+MOUSE:272")

    def test_canon_refuses_junk(self):
        for bad in ("", "HYPER+Q", "SUPER+", "SUPER++", "SUPER+two words", None, 5):
            self.assertIsNone(sc.canon(bad), bad)

    def test_nice_keeps_xkb_spelling(self):
        self.assertEqual(sc.nice("shift+super+Return"), "SUPER+SHIFT+Return")
        self.assertEqual(sc.nice("alt+q"), "ALT+Q")

    def test_live_keys(self):
        self.assertEqual(sc.live_keys(live("q", 64 | 1)), "SUPER+SHIFT+Q")
        self.assertEqual(sc.live_keys(live("left", 4 | 8)), "CTRL+ALT+left")

    def test_keys_from_event(self):
        self.assertIsNone(sc.keys_from_event({"SUPER"}, "Super_L"))
        self.assertIsNone(sc.keys_from_event({"CTRL"}, "Control_R"))
        self.assertIsNone(sc.keys_from_event(set(), "ISO_Level3_Shift"))
        self.assertEqual(sc.keys_from_event({"SHIFT", "SUPER"}, "1"), "SUPER+SHIFT+1")
        self.assertEqual(sc.keys_from_event({"ALT"}, "q"), "ALT+Q")
        self.assertEqual(sc.keys_from_event(set(), "XF86AudioPlay"), "XF86AudioPlay")
        self.assertIsNone(sc.keys_from_event({"ALT"}, None))

    def test_app_safe(self):
        self.assertEqual(sc.app_safe("SUPER+Q"), "")
        self.assertEqual(sc.app_safe("F5"), "")
        self.assertIn("before any app", sc.app_safe("CTRL+C"))


class File(unittest.TestCase):
    def test_round_trip(self):
        over = sc.empty()
        over["off"]["ALT+U"] = "Navigation: Urgent"
        over["moves"]["ALT+T"] = ("SUPER+CTRL+ALT+F11", "Groups: Toggle\tgroup")
        over["adds"].append({"keys": "super+alt+k", "desc": "Custom: Notes", "cmd": "gedit\nnotes"})
        back = sc.parse(sc.dump(over))
        self.assertEqual(back["off"], {"ALT+U": "Navigation: Urgent"})
        self.assertEqual(back["moves"], {"ALT+T": ("SUPER+CTRL+ALT+F11", "Groups: Toggle group")})
        self.assertEqual(back["adds"], [{"keys": "SUPER+ALT+K", "desc": "Custom: Notes", "cmd": "gedit notes"}])

    def test_bad_lines_skipped(self):
        over = sc.parse("# c\nmove\tALT+T\nadd\tALT+K\tName\t\nnonsense\noff\tALT+U\n")
        self.assertEqual(over["off"], {"ALT+U": ""})
        self.assertEqual(over["moves"], {})
        self.assertEqual(over["adds"], [])

    def test_empty_save_removes_file(self):
        path = os.path.join(tempfile.mkdtemp(dir=os.environ["XDG_STATE_HOME"]), "u.conf")
        over = sc.empty()
        over["off"]["ALT+U"] = "x"
        sc.save(over, path)
        self.assertTrue(os.path.exists(path))
        sc.save(sc.empty(), path)
        self.assertFalse(os.path.exists(path))


class Build(unittest.TestCase):
    BINDS = [live("t", 64 | 4 | 8, "Groups: Toggle group"),         # moved here from ALT+T
             live("q", 8, "Apps: Terminal"),
             live("q", 8, "Tools: Something else"),                  # made outside userbinds: shares ALT+Q
             live("k", 64 | 8, "Custom: Notes"),
             live("left", 0, "", submap="resize"),
             live("escape", 64, "", submap="keycapture")]
    REPORT = [("ALT+T", "SUPER+CTRL+ALT+T", "Groups: Toggle group"),
              ("ALT+Q", "ALT+Q", "Apps: Terminal"),
              ("ALT+U", None, "Navigation: Urgent")]

    def over(self):
        o = sc.empty()
        o["moves"]["ALT+T"] = ("SUPER+CTRL+ALT+T", "Groups: Toggle group")
        o["off"]["ALT+U"] = "Navigation: Urgent"
        o["adds"].append({"keys": "SUPER+ALT+K", "desc": "Custom: Notes", "cmd": "gedit"})
        return o

    def by_desc(self, entries):
        return {e["desc"]: e for e in entries}

    def test_states(self):
        e = self.by_desc(sc.build(self.BINDS, self.REPORT, self.over()))
        self.assertEqual(e["Groups: Toggle group"]["state"], "moved")
        self.assertEqual(e["Groups: Toggle group"]["keys"], "SUPER+CTRL+ALT+T")
        self.assertFalse(e["Groups: Toggle group"]["pending"])
        self.assertEqual(e["Navigation: Urgent"]["state"], "off")
        self.assertEqual(e["Custom: Notes"]["state"], "custom")
        self.assertFalse(e["Custom: Notes"]["pending"])
        self.assertEqual(e["Tools: Something else"]["state"], "fixed")
        self.assertEqual(e[""]["state"], "mode")                 # the resize arrow; keycapture's own is hidden
        self.assertEqual(sum(1 for x in e.values() if x["submap"] == "keycapture"), 0)
        self.assertEqual(e["Groups: Toggle group"]["group"], "Groups")
        self.assertEqual(e["Groups: Toggle group"]["what"], "Toggle group")

    def test_conflicts(self):
        e = self.by_desc(sc.build(self.BINDS, self.REPORT, self.over()))
        self.assertEqual(e["Apps: Terminal"]["conflicts"], ["Tools: Something else"])
        self.assertEqual(e["Tools: Something else"]["conflicts"], ["Apps: Terminal"])
        self.assertEqual(e["Navigation: Urgent"]["conflicts"], [])

    def test_pending(self):
        o = self.over()
        o["off"]["ALT+Q"] = "Apps: Terminal"                     # asked for, not loaded yet
        e = self.by_desc(sc.build(self.BINDS, self.REPORT, o))
        self.assertTrue(e["Apps: Terminal"]["pending"])
        self.assertEqual(e["Apps: Terminal"]["wanted"], "off")

    def test_no_report(self):
        """Hyprland without userbinds loaded: everything is a default, the
        file's changes pending."""
        e = self.by_desc(sc.build(self.BINDS[1:2], None, {"off": {"ALT+Q": "x"}, "moves": {}, "adds": []}))
        self.assertEqual(e["Apps: Terminal"]["state"], "default")
        self.assertTrue(e["Apps: Terminal"]["pending"])


class Changes(unittest.TestCase):
    def setUp(self):
        self.entries = sc.build(Build.BINDS, Build.REPORT, Build().over())
        self.over = Build().over()
        known = mock.patch.object(sc, "keysym_known", lambda key: key.lower() != "nosuchkey")
        known.start()
        self.addCleanup(known.stop)

    def test_move_and_back(self):
        sc.do_move(self.over, self.entries, "ALT+Q", "SUPER+F9")
        self.assertEqual(self.over["moves"]["ALT+Q"][0], "SUPER+F9")
        sc.do_move(self.over, self.entries, "ALT+Q", "alt+q")       # its default again: no entry left
        self.assertNotIn("ALT+Q", self.over["moves"])

    def test_move_into_taken_keys(self):
        with self.assertRaises(sc.Refused) as cm:
            sc.do_move(self.over, self.entries, "ALT+U", "SUPER+CTRL+ALT+T")
        self.assertEqual(cm.exception.code, 3)
        sc.do_move(self.over, self.entries, "ALT+U", "SUPER+CTRL+ALT+T", replace=True)
        self.assertIn("ALT+T", self.over["off"])                    # the one there was turned off
        self.assertEqual(self.over["moves"]["ALT+U"][0], "SUPER+CTRL+ALT+T")
        self.assertNotIn("ALT+U", self.over["off"])

    def test_refusals(self):
        for keys, new in (("ALT+Q", "SUPER+Escape"), ("ALT+Q", "SUPER+nosuchkey"), ("ALT+Q", "SUPER+"),
                          ("SUPER+F1", "SUPER+F9")):
            with self.assertRaises(sc.Refused):
                sc.do_move(self.over, self.entries, keys, new)

    def test_moved_one_found_by_either_keys(self):
        sc.do_off(self.over, self.entries, "SUPER+CTRL+ALT+T")      # its keys now
        self.assertIn("ALT+T", self.over["off"])
        sc.do_reset(self.over, self.entries, "ALT+T")               # its default keys
        self.assertNotIn("ALT+T", self.over["off"])
        self.assertNotIn("ALT+T", self.over["moves"])

    def test_add_and_remove(self):
        msg = sc.do_add(self.over, self.entries, "super+alt+n", "foot", "Terminal two")
        self.assertIn("SUPER+ALT+N", msg)
        self.assertEqual(self.over["adds"][-1], {"keys": "SUPER+ALT+N", "desc": "Custom: Terminal two",
                                                 "cmd": "foot"})
        # Same keys as one of your own: replaced, no refusal.
        sc.do_add(self.over, self.entries, "SUPER+ALT+K", "kate", "")
        self.assertEqual([a["cmd"] for a in self.over["adds"] if a["keys"] == "SUPER+ALT+K"], ["kate"])
        with self.assertRaises(sc.Refused):
            sc.do_add(self.over, self.entries, "ALT+Q", "foot", "")  # a default is there
        sc.do_remove(self.over, "SUPER+ALT+N")
        with self.assertRaises(sc.Refused):
            sc.do_remove(self.over, "SUPER+ALT+N")


    def swapped(self):
        """ALT+U moved onto ALT+Q while the terminal (default ALT+Q) moved
        to SUPER+F9: ALT+Q is the urgent one's keys now, the terminal's default."""
        sc.do_move(self.over, self.entries, "ALT+Q", "SUPER+F9")
        self.over["off"].pop("ALT+U")
        self.over["moves"]["ALT+U"] = ("ALT+Q", "Navigation: Urgent")
        report = [(d, {"ALT+Q": "SUPER+F9", "ALT+U": "ALT+Q"}.get(d, n), desc) for d, n, desc in Build.REPORT]
        binds = [dict(b) for b in Build.BINDS if b["description"] != "Tools: Something else"]
        for b in binds:
            if b["description"] == "Apps: Terminal":
                b.update(key="F9", modmask=64)
            elif b["description"] == "Navigation: Urgent":
                b.update(key="q", modmask=8)
        return sc.build(binds, report, self.over)

    def test_default_flag_names_the_default_keys_only(self):
        entries = self.swapped()
        sc.do_off(self.over, entries, "ALT+Q", by_default=True)
        self.assertIn("ALT+Q", self.over["off"])                    # the terminal
        self.assertIn("ALT+U", self.over["moves"])                  # the urgent one untouched
        over2 = self.over = Build().over()
        entries = self.swapped()
        sc.do_off(over2, entries, "ALT+Q")                          # without: its keys NOW
        self.assertIn("ALT+U", over2["off"])

    def test_reset_onto_keys_taken_meanwhile(self):
        entries = self.swapped()
        with self.assertRaises(sc.Refused) as cm:
            sc.do_reset(self.over, entries, "ALT+Q", by_default=True)
        self.assertEqual(cm.exception.code, 3)
        self.assertIn("ALT+Q", self.over["moves"])                  # nothing changed
        sc.do_reset(self.over, entries, "ALT+Q", by_default=True, replace=True)
        self.assertNotIn("ALT+Q", self.over["moves"])
        self.assertIn("ALT+U", self.over["off"])                    # the one there turned off
        with self.assertRaises(sc.Refused):                         # a move back to default too
            sc.do_move(Build().over(), entries, "ALT+Q", "ALT+Q", by_default=True)


class Capture(unittest.TestCase):
    def test_watchdog_only_acts_on_its_own_token(self):
        calls = []

        def fake(*args, **_kw):
            calls.append(args)
            return 0, "keycapture\n" if args == ("submap",) else ""
        with mock.patch.object(sc, "hyprctl", fake), mock.patch.object(sc, "CAPTURE_LIMIT", 0), \
                mock.patch.object(sc, "CAPTURE_TOKEN", os.path.join(os.environ["XDG_RUNTIME_DIR"], "kc")):
            with open(sc.CAPTURE_TOKEN, "w") as f:
                f.write("newer")
            sc.capture_watchdog("old")
            self.assertEqual(calls, [])
            sc.capture_watchdog("newer")
            self.assertIn(("dispatch", 'hl.dsp.submap("reset")'), calls)
            self.assertFalse(os.path.exists(sc.CAPTURE_TOKEN))


@unittest.skipUnless(shutil.which("luajit"), "luajit is not installed")
class UserbindsLua(unittest.TestCase):
    """lua/userbinds.lua against a stand-in hl: what it binds where."""
    HARNESS = textwrap.dedent("""
        local made = {}
        local function bind(keys, dsp, opts)
            if keys == "SUPER+BADKEY" then return nil end
            local kb = { keys = keys, opts = opts }
            function kb:remove() self.removed = true end
            made[#made + 1] = kb
            return kb
        end
        hl = { bind = bind, dsp = { exec_cmd = function(c) return "exec:" .. c end,
                                    submap = function(s) return "submap:" .. s end },
               define_submap = function(name, fn) fn() end }
        package.path = arg[1] .. "/?.lua;" .. package.path
        local UB = require("userbinds")
        hl.bind("ALT+Q", "term", { description = "Apps: Terminal" })
        hl.bind("ALT+T", "group", { description = "Groups: Toggle group" })
        hl.bind("ALT+U", "urgent", { description = "Navigation: Urgent" })
        hl.bind("ALT+W", "files", { description = "Apps: Files" })
        hl.define_submap("resize", function() hl.bind("left", "r", {}) end)
        UB.finish()
        for _, kb in ipairs(made) do
            if not kb.removed then print(kb.keys, kb.opts and kb.opts.description or "") end
        end
        print("--")
        print(UB.report())
    """)

    def run_lua(self, conf):
        state = tempfile.mkdtemp(dir=os.environ["XDG_STATE_HOME"])
        os.makedirs(os.path.join(state, "hypr"))
        with open(os.path.join(state, "hypr", "userbinds.conf"), "w") as f:
            f.write(conf)
        lua_dir = tempfile.mkdtemp(dir=os.environ["XDG_STATE_HOME"])
        shutil.copy(LUA, os.path.join(lua_dir, "userbinds.lua"))
        script = os.path.join(lua_dir, "h.lua")
        with open(script, "w") as f:
            f.write(self.HARNESS)
        env = dict(os.environ, XDG_STATE_HOME=state)
        r = subprocess.run(["luajit", script, lua_dir], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        made, report = r.stdout.split("--\n")
        return made.splitlines(), report.splitlines()

    def test_moves_offs_adds(self):
        made, report = self.run_lua("off\tALT+U\tNavigation: Urgent\n"
                                    "move\talt+t\tSUPER+CTRL+ALT+T\tGroups: Toggle group\n"
                                    "move\tALT+W\tSUPER+BADKEY\tApps: Files\n"
                                    "add\tSUPER+ALT+K\tCustom: Notes\tgedit\n"
                                    "garbage line\n")
        self.assertIn("ALT+Q\tApps: Terminal", made)
        self.assertIn("SUPER+CTRL+ALT+T\tGroups: Toggle group", made)
        self.assertFalse(any(m.startswith("ALT+U") for m in made))
        self.assertIn("ALT+W\tApps: Files", made)                  # refused keys: back on its own
        self.assertIn("SUPER+ALT+K\tCustom: Notes", made)
        self.assertIn("left\t", made)                              # submap binds untouched
        self.assertIn("SUPER+Escape\t", made)                      # the way out of keycapture
        self.assertIn("bind\tALT+U\t-\tNavigation: Urgent", report)
        self.assertIn("bind\tALT+T\tSUPER+CTRL+ALT+T\tGroups: Toggle group", report)
        self.assertTrue(any(line.startswith("error\t") and "SUPER+BADKEY" in line for line in report))
        self.assertTrue(any(line.startswith("error\t") and "garbage" in line for line in report))
        # The report parses as the Python side expects.
        with mock.patch.object(sc, "hyprctl", lambda *a, **k: (0, "\n".join(report))):
            rep, errors = sc.live_report()
        self.assertIn(("ALT+U", None, "Navigation: Urgent"), rep)
        self.assertEqual(len(errors), 2)

    def test_canon_agrees_with_python(self):
        made, _report = self.run_lua("off\tshift+alt+Q\t\n"      # no such bind: nothing turned off
                                     "off\tALT+\t\n")              # no key: skipped, not "ALT"
        self.assertIn("ALT+Q\tApps: Terminal", made)
        self.assertEqual(len([m for m in made if m.startswith("ALT+")]), 4)
        self.assertEqual(sc.canon("shift+alt+Q"), "ALT+SHIFT+Q")


if __name__ == "__main__":
    unittest.main()
