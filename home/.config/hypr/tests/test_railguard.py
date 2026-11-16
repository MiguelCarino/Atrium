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
    for path in (rg.SETTINGS_FILE, rg.HISTORY_FILE, rg.COMMAND_MAX_FILE, rg.PRESSURE_FILE):
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

    def test_the_ask_first_settings(self):
        cur = rg.read_settings()
        self.assertEqual(cur["managed_units"], ["cerberus-lmstudio.scope", "cerberus.service", "lmstudio.service"])
        self.assertEqual((cur["managed_grace_s"], cur["vram_hard_pct"]), (20, 99.5))
        os.makedirs(rg.STATE_DIR, exist_ok=True)
        with open(rg.SETTINGS_FILE, "w") as fh:
            json.dump({"managed_grace_s": 600, "vram_hard_pct": 12, "managed_units": "cerberus.service"}, fh)
        cur = rg.read_settings()
        self.assertEqual((cur["managed_grace_s"], cur["vram_hard_pct"]), (60, 80.0))
        self.assertEqual(cur["managed_units"], ["cerberus-lmstudio.scope", "cerberus.service", "lmstudio.service"])   # not a list
        with open(rg.SETTINGS_FILE, "w") as fh:
            json.dump({"managed_grace_s": 1, "managed_units": []}, fh)
        cur = rg.read_settings()
        self.assertEqual((cur["managed_grace_s"], cur["managed_units"]), (5, []))           # [] = never ask
        rg.set_key("managed_grace_s", "30")
        rg.set_key("vram_hard_pct", "99")
        self.assertEqual((rg.read_settings()["managed_grace_s"], rg.read_settings()["vram_hard_pct"]), (30, 99.0))
        for key, value in (("managed_grace_s", "4"), ("managed_grace_s", "61"), ("vram_hard_pct", "101"),
                           ("managed_units", "x.service")):
            with self.assertRaises(SystemExit):
                rg.set_key(key, value)

    def test_the_contract_fixture(self):
        """fixtures/railguard-settings-cases.json: each railguard.json and
        the settings railguard reads from it -- clamped into RANGES, numbers
        and numeric strings through float, bools by truthiness, vram_s and
        managed_grace_s truncated to int, vram_pct a float, a bad key alone
        falling back. Cerberus' reader (internal/railguard) must match it."""
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                               "railguard-settings-cases.json")) as fh:
            cases = json.load(fh)["cases"]
        self.assertGreaterEqual(len(cases), 8)
        os.makedirs(rg.STATE_DIR, exist_ok=True)
        for case in cases:
            with open(rg.SETTINGS_FILE, "w") as fh:
                fh.write(case["file"] if isinstance(case["file"], str) else json.dumps(case["file"]))
            cur = rg.read_settings()
            for key, want in case["want"].items():
                self.assertEqual(cur[key], want, f"{case['name']}: {key}")
                self.assertIs(type(cur[key]), type(want), f"{case['name']}: {key} type")

    def test_a_cerberus_session_command_weighs_as_an_agents(self):
        cg = USER + "/cerberus-sessions.slice/run-s1-c1.scope"
        fake = FakeProc({201: ("python3", cg, 1_000_000, b"")})
        with mock.patch("builtins.open", fake.open), mock.patch.object(rg.os, "stat", fake.stat):
            self.assertEqual(rg.proc_info(201)["weight"], rg.AGENT_WEIGHT)

    def test_managed_units_take_unit_names(self):
        rg.edit_list("add", "managed_units", "ollama.service")
        self.assertIn("ollama.service", rg.read_settings()["managed_units"])
        rg.edit_list("remove", "managed_units", "lmstudio.service")
        self.assertEqual(rg.read_settings()["managed_units"],
                         ["cerberus-lmstudio.scope", "cerberus.service", "ollama.service"])
        for bad in ("ollama", "../x.service", "a/b.scope"):
            with self.assertRaises(SystemExit):
                rg.edit_list("add", "managed_units", bad)

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
    """A /proc with the given processes: {pid: (name, cgroup, rss kB, env)},
    or (name, cgroup, rss kB, env, status lines) for a status of its own."""

    def __init__(self, procs):
        self.procs = procs

    def open(self, path, mode="r", *a, **k):
        parts = path.split("/")
        if len(parts) == 4 and parts[1] == "proc" and parts[2].isdigit():
            pid, what = int(parts[2]), parts[3]
            if pid not in self.procs:
                raise FileNotFoundError(path)
            name, cgroup, rss, env, *status = self.procs[pid]
            text = {"cgroup": f"0::{cgroup}\n",
                    "stat": f"{pid} ({name}) S 1 1 1 0 -1 0 0 0 0 0 10 5 0 0",
                    "status": (f"Name:\t{name}\nVmRSS:\t{rss} kB\n"
                               + (status[0] if status else "VmSwap:\t0 kB\n"))}.get(what)
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


# A model server: 10 GB resident, nearly all of it the GGUF mapped from disk
# (RssFile, dropped by the kernel by itself); a script with 3 GB of its own.
MODEL = ("llama-server", USER + "/app.slice/lmstudio.service", 10_000_000, b"",
         "RssAnon:\t600000 kB\nRssFile:\t9400000 kB\nRssShmem:\t0 kB\nVmSwap:\t0 kB\nVmLck:\t0 kB\n")
HOG = ("python3", USER + "/app.slice/app-python.scope", 3_000_000, b"",
       "RssAnon:\t2900000 kB\nRssFile:\t100000 kB\nRssShmem:\t0 kB\nVmSwap:\t200000 kB\nVmLck:\t0 kB\n")
LOCKED = ("llama-server", USER + "/app.slice/lmstudio.service", 8_000_000, b"",
          "RssAnon:\t500000 kB\nRssFile:\t7500000 kB\nRssShmem:\t0 kB\nVmSwap:\t0 kB\nVmLck:\t7600000 kB\n")


class AnonymousMemory(unittest.TestCase):
    """RAM victims ranked by what ending them gives back, not VmRSS."""

    def use(self, procs):
        fake = FakeProc(procs)
        patches = [mock.patch("builtins.open", fake.open), mock.patch.object(rg.os, "stat", fake.stat),
                   mock.patch.object(rg.os, "listdir", fake.listdir)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def setUp(self):
        fresh()

    def test_mem_size(self):
        self.assertEqual(rg.mem_size({"VmRSS": 10, "RssAnon": 4, "RssShmem": 1, "VmSwap": 2}), 7 * 1024)
        self.assertEqual(rg.mem_size({"RssAnon": 4, "VmLck": 9, "VmSwap": 1}), 10 * 1024)   # locked counts
        self.assertEqual(rg.mem_size({"VmRSS": 10, "VmSwap": 2}), 12 * 1024)                # an old kernel

    def test_a_mapped_model_ranks_below_a_smaller_anonymous_hog(self):
        self.use({201: MODEL, 202: HOG})
        self.assertEqual(rg.proc_info(201)["mem"], 600_000 * 1024)
        self.assertEqual(rg.proc_info(202)["mem"], 3_100_000 * 1024)
        self.assertEqual(rg.biggest()["name"], "python3")

    def test_mlocked_weights_still_count(self):
        self.use({203: LOCKED, 202: HOG})
        self.assertEqual(rg.proc_info(203)["mem"], 7_600_000 * 1024)
        self.assertEqual(rg.biggest()["name"], "llama-server")

    def test_panic_and_status_use_the_same_size(self):
        self.use({201: MODEL, 202: HOG})
        with mock.patch.object(rg, "meminfo", return_value={"MemAvailable": 1, "MemTotal": 100}), \
                mock.patch.object(rg, "kill", return_value=True) as kill, \
                mock.patch.object(rg, "record") as record, mock.patch.object(rg, "notify"), \
                mock.patch.object(rg, "load_settings"):      # the fake open() is /proc only
            rg.panic()
        self.assertEqual(kill.call_args.args[0]["name"], "python3")
        self.assertEqual(record.call_args.args[1]["mem"], 3_100_000 * 1024)


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

    def test_the_ask_kinds(self):
        p = {"name": "llama-server", "pid": 9, "cgroup": USER + "/app.slice/cerberus.service", "mem": 1024 ** 3}
        rg.record("vram-asked", p, "VRAM 98% full; asked Cerberus to free 500 MiB within 20 s", vram_gb=18.0)
        rg.record("vram-shed", p, "VRAM 98% -> 92% within 6 s of asking", vram_gb=18.0)
        rg.record("vram-asked", p, "VRAM 98% full", vram_gb=18.0)
        rg.record("vram", p, "VRAM 98% full; asked first", vram_gb=18.0)
        h = rg.history()
        self.assertEqual([e["kind"] for e in h], ["vram", "vram-asked", "vram-shed", "vram-asked"])
        self.assertEqual((h[1]["unit"], h[1]["vram_gb"]), ("cerberus.service", 18.0))
        self.assertIn("asked Cerberus for VRAM", rg.describe(h[1]))
        self.assertIn("Cerberus freed VRAM", rg.describe(h[2]))
        lines = rg.brief_lines()
        self.assertIn("1 runaway ended", lines[0])
        self.assertIn("1 time an engine freed GPU memory when asked", lines[0])
        self.assertNotIn("warning", lines[0])                # an ask is not news by itself
        self.assertEqual(len(lines), 3)

    def test_trimmed(self):
        with mock.patch.object(rg, "HISTORY_KEEP", 5):
            for i in range(11):
                rg.record("stuck", None, str(i))
        self.assertEqual(len(rg.history(100)), 5)
        self.assertEqual(rg.history(1)[0]["why"], "10")


try:
    from settings_pages import railguard as page
except Exception as exc:                                 # noqa: BLE001  (no GTK here)
    page = None


@unittest.skipIf(page is None, "settings_pages.railguard not importable")
class SettingsPage(unittest.TestCase):
    def test_new_kinds_have_titles_and_icons(self):
        cerb = {"unit": "cerberus.service"}
        self.assertEqual(page.entry_title(dict(cerb, kind="vram-asked")), "Asked Cerberus to free GPU memory")
        self.assertIn("LM Studio freed", page.entry_title({"kind": "vram-shed", "unit": "lmstudio.service"}))
        self.assertEqual(page.entry_title({"kind": "vram", "why": "VRAM 98% full; asked first"}),
                         "Ended after asking for GPU memory")
        self.assertEqual(page.entry_title({"kind": "vram", "why": "VRAM 98% full"}), "Ended a GPU memory runaway")
        for kind in ("vram-asked", "vram-shed"):
            self.assertIn(kind, page.KIND_ICONS)
        self.assertIn("managed_units", [k for k, *_ in page.LISTS])
        self.assertEqual(page.engine("ollama.service"), "ollama")
        self.assertEqual(page.ENGINE_NAMES, rg.ENGINE_NAMES)

    def test_chips_stay_in_railguards_ranges(self):
        conf = {"managed_grace_s": 20, "vram_hard_pct": 99.5}
        items, cur = page.chips_for(page.GRACE_S, "managed_grace_s", conf, rg.RANGES, " s")
        self.assertEqual(cur, "20")
        self.assertEqual([k for k, _ in items], ["10", "20", "30", "60"])
        items, cur = page.chips_for(page.VRAM_HARD + [70, 120], "vram_hard_pct", conf, rg.RANGES, " %")
        self.assertEqual(([k for k, _ in items], cur), (["98", "99", "99.5"], "99.5"))
        self.assertNotIn(100, page.VRAM_HARD)        # not one MiB free: the card never reports it
        self.assertEqual(items[2][1], "99.5 %")
        for key, values in (("managed_grace_s", page.GRACE_S), ("vram_hard_pct", page.VRAM_HARD)):
            lo, hi = rg.RANGES[key]
            self.assertTrue(all(lo <= v <= hi for v in values), key)

    def test_no_line_the_card_cannot_reach(self):
        # a 24 GB NVIDIA card: used tops out at 98.1 % of the total
        self.assertEqual(page.line_values({"vram_usable_pct": 98.1}), [90, 95, 97])
        self.assertEqual(page.line_values({}), page.VRAM_FULL)

    def test_status_carries_the_ranges(self):
        with mock.patch.object(rg.subprocess, "run", return_value=mock.Mock(stdout="")), \
                mock.patch.object(rg, "gpu_card", return_value=None):
            st = rg.snapshot()
        self.assertEqual(st["ranges"]["managed_grace_s"], (5, 60))
        self.assertIn("managed_units", st["settings"])


if __name__ == "__main__":
    unittest.main()
