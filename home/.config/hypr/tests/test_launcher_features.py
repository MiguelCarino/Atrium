"""launcher.py: the shortcut and password rows, the Welcome command, the
VRAM a model is weighed against (gpu.py's card, the RAM without one), the
child reaper and the bar signal -- with stand-ins for everything that would
reach Hyprland, the bus, the clipboard or a real card."""
import os
import subprocess
import sys
import unittest

import helpers

L = helpers.import_script("launcher.py", "launcher")


def bind(key, mask, desc):
    return {"key": key, "modmask": mask, "description": desc, "submap": "", "mouse": False}


BINDS = [bind("Q", 8, "Apps: Terminal"), bind("F", 8, "Windows: Fullscreen"),
         bind("S", 64, "Screenshots: Region to clipboard (no file)")]


class FakeApp:
    def __init__(self, name):
        self.name, self.lname, self.extra, self.id = name, name.lower(), "", name
        self.key = "app:" + name


class Shortcuts(unittest.TestCase):
    def setUp(self):
        self.items = L.shortcut_items(BINDS)

    def test_rows(self):
        self.assertEqual([i.name for i in self.items], ["Terminal", "Fullscreen", "Region to clipboard (no file)"])
        self.assertEqual(self.items[0].sub, "ALT + Q  ·  Apps shortcut")
        self.assertEqual(self.items[0].key, "keys:ALT+Q")

    def test_after_the_apps_without_a_prefix(self):
        found = L.results([FakeApp("Terminal Emulator")], [], "terminal", {}, shortcuts=self.items)
        names = [i.name for i in found]
        self.assertLess(names.index("Terminal Emulator"), names.index("Terminal"))

    def test_keys_are_not_matched_without_the_prefix(self):
        found = L.results([], [], "alt", {}, shortcuts=self.items)
        self.assertFalse([i for i in found if getattr(i, "entry", None)])

    def test_keys_prefix_lists_only_shortcuts(self):
        found = L.results([FakeApp("Terminal")], [], "keys alt", {}, shortcuts=self.items)
        self.assertEqual([i.name for i in found], ["Terminal", "Fullscreen"])
        self.assertTrue(all(getattr(i, "entry", None) for i in found))
        self.assertEqual(len(L.results([], [], "keys", {}, shortcuts=self.items)), 3)
        self.assertEqual(L.results([], [], "keys zzz", {}, shortcuts=self.items)[0].name,
                         "No shortcut has those words")

    def test_question_mark_stays_the_ai(self):
        found = L.results([], [], "?terminal", {}, shortcuts=self.items)
        self.assertFalse([i for i in found if getattr(i, "entry", None)])

    def test_enter_runs_the_bind_after_the_card(self):
        spawned = []
        saved, L.spawn = L.spawn, spawned.append
        try:
            self.items[1].run()
        finally:
            L.spawn = saved
        self.assertEqual(spawned[0][:2], ["sh", "-c"])
        self.assertIn('"ALT+F", "Windows: Fullscreen"', spawned[0][5])


class FakeIndex:
    def __init__(self, result):
        self.result = result
        self.forgot = 0

    def get(self):
        return self.result

    def forget(self):
        self.forgot += 1


def scan(state, items=(), locked=(), provider="KeePassXC"):
    return {"state": state, "provider": provider, "items": list(items), "locked": list(locked)}


ITEM = {"path": "/c/1/a", "label": "Mail", "attrs": {"UserName": "me"}, "text": "mail me"}


class Passwords(unittest.TestCase):
    def test_prefix(self):
        self.assertTrue(L.wants_passwords("pw"))
        self.assertTrue(L.wants_passwords("pw mail"))
        self.assertFalse(L.wants_passwords("pwd"))
        self.assertFalse(L.wants_passwords("password"))

    def test_waiting_for_the_scan(self):
        self.assertIn("Looking", L.results([], [], "pw", {}, secrets=FakeIndex(None))[0].name)

    def test_no_provider_is_one_explaining_row(self):
        rows = L.results([], [], "pw mail", {}, secrets=FakeIndex(scan("none", provider="Secret Service")))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "Unlock KeePassXC / enable Secret Service integration")

    def test_nothing_shared(self):
        rows = L.password_items("", FakeIndex(scan("empty")))
        self.assertEqual([r.name for r in rows], ["Enable Secret Service integration"])

    def test_locked_offers_unlock(self):
        idx = FakeIndex(scan("locked", locked=["/c/1"]))
        rows = L.password_items("mail", idx)
        self.assertEqual([r.name for r in rows], ["Unlock KeePassXC"])
        spawned = []
        saved, L.spawn = L.spawn, spawned.append
        try:
            rows[0].run()
        finally:
            L.spawn = saved
        self.assertEqual(spawned[0][-2:], ["unlock", "/c/1"])
        self.assertEqual(idx.forgot, 1)

    def test_matches_copy_through_the_helper(self):
        rows = L.password_items("mail", FakeIndex(scan("ok", [ITEM], ["/c/2"])))
        self.assertEqual([r.name for r in rows], ["Mail", "Unlock 1 more in KeePassXC"])
        self.assertIsNone(rows[0].key)              # never learned in launcher-picks.json
        spawned = []
        saved, L.spawn = L.spawn, spawned.append
        try:
            rows[0].run()
        finally:
            L.spawn = saved
        self.assertEqual(spawned[0][-3:], ["copy", "/c/1/a", str(L.launcher_secrets.CLEAR_AFTER)])

    def test_no_keepassxc_installed_is_still_one_row(self):
        # PyGObject raises for a .desktop id that is not installed.
        self.assertIsNone(L.desktop_app("no-such-app-anywhere.desktop"))
        saved, L.KEEPASSXC_DESKTOP = L.KEEPASSXC_DESKTOP, "no-such-app-anywhere.desktop"
        try:
            rows = L.password_items("", FakeIndex(scan("none", provider="Secret Service")))
        finally:
            L.KEEPASSXC_DESKTOP = saved
        self.assertEqual(len(rows), 1)
        self.assertIn("not installed", rows[0].sub)

    def test_no_match(self):
        rows = L.password_items("bank", FakeIndex(scan("ok", [ITEM])))
        self.assertEqual(rows[0].name, "No password matches")

    def test_a_sensitive_copy_is_never_read_back(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "text/plain\nx-kde-passwordManagerHint\n", "")
        saved, L.subprocess.run = L.subprocess.run, run
        try:
            self.assertIsNone(L.read_clipboard())
        finally:
            L.subprocess.run = saved
        self.assertEqual(calls, [["wl-paste", "-l"]])


class Commands(unittest.TestCase):
    def test_welcome(self):
        row = next(c for c in L.COMMANDS if c[0] == "Welcome")
        self.assertTrue(callable(row[3]))
        spawned = []
        saved, L.spawn = L.spawn, spawned.append
        try:
            row[3]()
        finally:
            L.spawn = saved
        self.assertEqual(spawned, [[sys.executable, os.path.join(L.HYPR, "welcome.py")]])
        item = next(i for i in L.command_items() if i.name == "Welcome")
        self.assertNotIn("llm", item.extra)          # only the chat commands are found by "ai"

    def test_no_raw_signal_numbers(self):
        for name, _sub, _icon, argv in L.COMMANDS:
            if isinstance(argv, list):
                self.assertNotIn("RTMIN", " ".join(argv), name)
        health = next(c for c in L.COMMANDS if c[0] == "Desktop health check")
        self.assertIn("bar_signals.py poke doctor", health[3][2])


class Hardware(unittest.TestCase):
    def test_vram_from_the_card(self):
        self.assertEqual(L.vram_bytes({"vram_total": 24564}, 32e9), 24564 * 1024 ** 2)

    def test_no_card_or_integrated_is_the_ram(self):
        self.assertEqual(L.vram_bytes(None, 16e9), 16e9)
        self.assertEqual(L.vram_bytes({"vram_total": None, "discrete": False}, 16e9), 16e9)
        # An AMD APU reports its carve-out as VRAM: still the RAM.
        self.assertEqual(L.vram_bytes({"vendor": "amd", "vram_total": 512, "discrete": False}, 16e9), 16e9)

    def test_fit_before_hardware_is_known_uses_the_ram(self):
        saved = dict(L._HW)
        L._HW.clear()
        try:
            ram = L.ram_bytes()
            self.assertEqual(L.fit(ram / 4), "fits GPU")
            self.assertEqual(L.fit(ram * 4), "too big")
        finally:
            L._HW.update(saved)


class FakeProc:
    def __init__(self, done):
        self.done = done

    def poll(self):
        return 0 if self.done else None


class Reaper(unittest.TestCase):
    def setUp(self):
        self.saved = list(L._CHILDREN)
        L._CHILDREN.clear()

    def tearDown(self):
        L._CHILDREN[:] = self.saved

    def test_ended_children_are_collected(self):
        running = FakeProc(False)
        L.remember(running)
        L.remember(FakeProc(True))          # collected at once (remember reaps)
        self.assertEqual(L._CHILDREN, [running])
        running.done = True
        self.assertEqual(L.reap(), 1)
        self.assertEqual(L._CHILDREN, [])

    def test_spawn_is_reaped_for_real(self):
        L.spawn(["true"])
        proc = L._CHILDREN[-1]
        proc.wait(timeout=5)
        L.reap()
        self.assertNotIn(proc, L._CHILDREN)
        self.assertIsNone(L.spawn(["true"]))      # spawn returns None (GLib callbacks)


if __name__ == "__main__":
    unittest.main()
