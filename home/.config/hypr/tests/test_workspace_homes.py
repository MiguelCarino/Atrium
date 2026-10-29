"""lua/workspaces.lua (under luajit): which workspace lives on which screen,
for any number of screens -- the list lua/rules.lua makes the workspace
rules from and lua/binds.lua's mainMod+n loops run over -- and this
machine's host file, read the way scripts/screens.py reads it."""
import json
import os
import re
import shutil
import subprocess
import unittest

import helpers

HYPR = os.path.dirname(helpers.SCRIPTS)
WORKSPACES_LUA = os.path.join(HYPR, "lua", "workspaces.lua")
HOST_LUA = os.path.join(HYPR, "lua", "hosts", "workstation.lua")

screens = helpers.import_script("screens.py")


def lua_list(items):
    return "{" + ", ".join(json.dumps(i) for i in items) + "}"


@unittest.skipUnless(shutil.which("luajit"), "luajit is not installed")
class Homes(unittest.TestCase):
    def homes(self, screen_list, primary="FIRST"):
        if primary == "FIRST":
            primary = screen_list[0] if screen_list else None
        lua = f"""
            local W = dofile({json.dumps(WORKSPACES_LUA)})
            local s = {lua_list(screen_list)}
            for _, h in ipairs(W.homes(s, {json.dumps(primary) if primary else "nil"})) do
                print(h.ws .. " " .. tostring(h.monitor) .. " " .. tostring(h.default) .. " " .. tostring(h.persistent))
            end
            print("last " .. W.last(s))
        """
        out = subprocess.run(["luajit", "-e", lua], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        rows, last = {}, None
        for line in out.stdout.splitlines():
            parts = line.split()
            if parts[0] == "last":
                last = int(parts[1])
            else:
                rows[int(parts[0])] = (None if parts[1] == "nil" else parts[1], parts[2] == "true",
                                       parts[3] == "true")
        return rows, last

    def test_three_screens_is_the_old_layout(self):
        rows, last = self.homes(["DP-1", "DP-2", "HDMI-A-1"])
        self.assertEqual(last, 6)
        self.assertEqual(sorted(rows), [1, 2, 3, 4, 5, 6])
        self.assertEqual(rows[1], ("DP-1", True, True))
        for ws in (2, 3, 5):
            self.assertEqual(rows[ws], ("DP-1", False, True))
        self.assertEqual(rows[4], ("DP-2", True, True))
        self.assertEqual(rows[6], ("HDMI-A-1", True, True))

    def test_a_fourth_screen_gets_seven_and_its_key(self):
        rows, last = self.homes(["DP-1", "DP-2", "HDMI-A-1", "DP-3"])
        self.assertEqual(last, 7)
        self.assertEqual(rows[7], ("DP-3", True, True))
        self.assertNotIn(8, rows)

    def test_every_keyed_workspace_has_a_home(self):
        for n in range(1, 8):
            names = [f"OUT-{i}" for i in range(n)]
            rows, last = self.homes(names)
            for ws in range(1, last + 1):
                self.assertIn(ws, rows, (n, ws))
                self.assertIsNotNone(rows[ws][0], (n, ws))
                self.assertTrue(rows[ws][2], (n, ws))
            self.assertEqual(set(rows), set(range(1, last + 1)), n)

    def test_fewer_screens_keep_four_and_six_on_the_primary(self):
        rows, last = self.homes(["DP-1"])
        self.assertEqual(last, 6)
        self.assertEqual(rows[4], ("DP-1", False, True))
        self.assertEqual(rows[6], ("DP-1", False, True))

    def test_another_primary_moves_only_the_primary_set(self):
        rows, _ = self.homes(["DP-1", "DP-2", "HDMI-A-1", "DP-3"], primary="DP-3")
        self.assertEqual(rows[1][0], "DP-3")
        self.assertEqual(rows[4][0], "DP-2")
        self.assertEqual(rows[7][0], "DP-3")

    def test_no_screen_known_declares_without_a_home(self):
        rows, last = self.homes([], primary=None)
        self.assertEqual(last, 6)
        self.assertTrue(all(mon is None and not default and persistent
                            for mon, default, persistent in rows.values()))

    def test_ten_is_the_last_key(self):
        _, last = self.homes([f"OUT-{i}" for i in range(9)])
        self.assertEqual(last, 10)

    def test_rules_lua_pins_say_what_homes_says(self):
        # lua/rules.lua writes the first six out as pin() calls (window-look.py
        # reads them); they must agree with homes() for one and three screens.
        look = helpers.import_script("window-look.py", "window_look")
        with open(os.path.join(HYPR, "lua", "rules.lua")) as handle:
            text = handle.read()
        for order in (["DP-1"], ["DP-1", "DP-2", "HDMI-A-1"]):
            parsed = {int(r["workspace"]): (r["monitor"], r["default"], r["persistent"])
                      for r in look.parse_workspace_rules(text, order[0], order)}
            rows, _ = self.homes(order)
            self.assertEqual(parsed, rows, order)


@unittest.skipUnless(os.path.exists(HOST_LUA), "no workstation host file here")
class HostFile(unittest.TestCase):
    def setUp(self):
        with open(HOST_LUA) as handle:
            self.text = handle.read()

    def test_workstation_lists_all_four_screens(self):
        profile = screens.parse_host(self.text)
        self.assertEqual(profile["screens"], ["DP-1", "DP-2", "HDMI-A-1", "DP-3"])
        self.assertEqual(profile["hdr_capable"], ["DP-1"])

    def test_every_listed_screen_has_a_block(self):
        for name in screens.parse_host(self.text)["screens"]:
            self.assertRegex(self.text, r'output\s*=\s*"' + re.escape(name) + '"', name)


if __name__ == "__main__":
    unittest.main()
