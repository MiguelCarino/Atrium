"""railguard.py (the anti-freeze watchdog): settings clamped and kept, the
lists, who goes first (weights, protected names, games), the history and
the brief's lines, the limits written as drop-ins -- all on scratch files,
with a fake /proc where a process is needed and no systemctl."""
import json
import os
import time
import unittest
from unittest import mock

import helpers

rg = helpers.import_script("railguard.py")
rg.UNIT_DIR = os.path.join(helpers.SCRATCH, "systemd-railguard")
UID = os.getuid()


def fresh():
    for path in (rg.SETTINGS_FILE, rg.HISTORY_FILE, rg.COMMAND_MAX_FILE):
        if os.path.exists(path):
            os.remove(path)
    rg.load_settings()


class Settings(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_defaults_without_a_file(self):
        self.assertEqual(rg.read_settings(), rg.SETTINGS)

    def test_out_of_range_is_clamped_and_junk_ignored(self):
        os.makedirs(rg.STATE_DIR, exist_ok=True)
        with open(rg.SETTINGS_FILE, "w") as fh:
            json.dump({"vram_pct": 300, "ram_free_pct": "x", "ram": 0, "nope": 1,
                       "never_kill": ["obs", "", "obs", 7]}, fh)
        cur = rg.read_settings()
        self.assertEqual(cur["vram_pct"], 100.0)
        self.assertEqual(cur["ram_free_pct"], 4.0)
        self.assertIs(cur["ram"], False)
        self.assertEqual(cur["never_kill"], ["7", "obs"])
        self.assertNotIn("nope", cur)

    def test_set_checks_the_value(self):
        rg.set_key("vram_pct", "95")
        self.assertEqual(rg.read_settings()["vram_pct"], 95.0)
        rg.set_key("spare_games", "off")
        self.assertIs(rg.read_settings()["spare_games"], False)
        for key, value in (("vram_pct", "300"), ("spare_games", "maybe"), ("nope", "1"),
                           ("never_kill", "x")):
            with self.assertRaises(SystemExit):
                rg.set_key(key, value)

    def test_lists(self):
        rg.edit_list("add", "never_kill", "obs")
        rg.edit_list("add", "kill_first", "ollama")
        rg.edit_list("add", "kill_first", "ollama")
        self.assertEqual(rg.read_settings()["kill_first"], ["ollama"])
        rg.edit_list("remove", "never_kill", "obs")
        self.assertEqual(rg.read_settings()["never_kill"], [])
        with self.assertRaises(SystemExit):
            rg.edit_list("add", "kill_first", "kitty")        # protected

    def test_a_limit_is_applied(self):
        with mock.patch.object(rg.subprocess, "run") as run:
            rg.set_key("agents_gb", "16")
        with open(os.path.join(rg.UNIT_DIR, "agents.slice.d", "limits.conf")) as fh:
            conf = fh.read()
        self.assertIn("MemoryMax=16G", conf)
        self.assertIn("MemoryHigh=14G", conf)
        self.assertIn("CPUQuota=2000%", conf)
        with open(rg.COMMAND_MAX_FILE) as fh:
            self.assertEqual(fh.read().strip(), "16G")
        live = [c.args[0] for c in run.call_args_list if "set-property" in c.args[0]]
        self.assertTrue(any("agents.slice" in c and "MemoryMax=16G" in c for c in live))


class FakeProc:
    """A /proc with the given processes: {pid: (name, cgroup, rss kB, env)}."""

    def __init__(self, procs):
        self.procs = procs

    def open(self, path, mode="r", *a, **k):
        parts = path.split("/")
        if len(parts) == 4 and parts[1] == "proc" and parts[2].isdigit():
            pid, what = int(parts[2]), parts[3]
            if pid not in self.procs:
                raise FileNotFoundError(path)
            name, cgroup, rss, env = self.procs[pid]
            text = {"cgroup": f"0::{cgroup}\n",
                    "stat": f"{pid} ({name}) S 1 1 1 0 -1 0 0 0 0 0 10 5 0 0",
                    "status": f"Name:\t{name}\nVmRSS:\t{rss} kB\nVmSwap:\t0 kB\n"}.get(what)
            if what == "environ":
                import io
                return io.BytesIO(env)
            if text is None:
                raise FileNotFoundError(path)
            import io
            return io.StringIO(text)
        return open(path, mode, *a, **k)

    def stat(self, path):
        return mock.Mock(st_uid=UID)

    def listdir(self, path):
        return [str(p) for p in self.procs]


USER = "/user.slice/user-1000.slice/user@1000.service"
PROCS = {
    101: ("firefox", USER + "/app.slice/app-firefox.scope", 4_000_000, b"A=1\0"),
    102: ("cc1plus", USER + "/heavy.slice/run-1.scope", 2_500_000, b""),
    103: ("mpv", USER + "/session.slice/wayland-wm@hyprland.desktop.service", 6_000_000, b""),
    104: ("kitty", USER + "/session.slice/kitty-1.scope", 9_000_000, b""),
    105: ("Game.exe", USER + "/app.slice/app-steam.scope", 7_000_000, b"X=1\0SteamAppId=42\0"),
}


class Choosing(unittest.TestCase):
    def setUp(self):
        fresh()
        fake = FakeProc(PROCS)
        self.patches = [mock.patch("builtins.open", fake.open),
                        mock.patch.object(rg.os, "stat", fake.stat),
                        mock.patch.object(rg.os, "listdir", fake.listdir)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_protected_and_game(self):
        self.assertIsNone(rg.proc_info(104))
        game = rg.proc_info(105)
        self.assertTrue(game["game"])
        self.assertEqual(game["weight"], rg.GAME_WEIGHT)

    def test_a_build_goes_before_a_bigger_browser(self):
        # cc1plus 2.5 GB x2 = 5 > firefox 4 GB x1 > game 7 x0.5 > mpv 6 x0.5
        self.assertEqual(rg.biggest()["name"], "cc1plus")

    def test_kill_first_and_never_kill(self):
        rg.CFG["kill_first"] = ["mpv"]
        self.assertEqual(rg.biggest()["name"], "mpv")
        rg.CFG["never_kill"] = ["mpv", "cc1plus"]
        self.assertEqual(rg.biggest()["name"], "firefox")

    def test_games_count_full_with_spare_games_off(self):
        rg.CFG["spare_games"] = False
        self.assertEqual(rg.biggest()["name"], "Game.exe")


class History(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_record_and_brief(self):
        self.assertEqual(rg.brief_lines(), [])
        p = {"name": "cc1plus", "pid": 7, "cgroup": USER + "/heavy.slice/run-7.scope", "mem": 3 * 1024 ** 3}
        rg.record("memory", p, "2% RAM free")
        rg.record("game-vram", dict(p, name="Game.exe"), "VRAM 98% full")
        rg.record("agents", None, "asked")
        h = rg.history()
        self.assertEqual([e["kind"] for e in h], ["agents", "game-vram", "memory"])
        self.assertEqual(h[2]["unit"], "run-7.scope")
        self.assertEqual(h[2]["gb"], 3.0)
        lines = rg.brief_lines()
        self.assertIn("1 runaway ended", lines[0])
        self.assertIn("1 warning", lines[0])
        self.assertEqual(len(lines), 3)               # agents' stop is not news
        self.assertEqual(rg.brief_lines(time.time() + 2 * 86400), [])

    def test_trimmed(self):
        with mock.patch.object(rg, "HISTORY_KEEP", 5):
            for i in range(11):
                rg.record("stuck", None, str(i))
        self.assertEqual(len(rg.history(100)), 5)
        self.assertEqual(rg.history(1)[0]["why"], "10")


if __name__ == "__main__":
    unittest.main()
