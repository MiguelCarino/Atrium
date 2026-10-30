"""The dynamic island (scripts/island.py): its settings (island.json:
defaults, hand edits, what `set` accepts, the systemctl it runs), status
--json's shape, and the pure logic the daemon is built on -- the clock,
the now-playing words, which player wins, when a timer shows, game and
full-screen detection, which screen, what comes first, the events it
accepts -- plus island_events.py's side of the socket (nothing to do when
the island is off).

Hermetic: island.json is in helpers.py's scratch XDG_STATE_HOME, the socket
in its scratch XDG_RUNTIME_DIR, ISLAND_DRY=1 keeps systemctl out (the two
tests that check the systemctl line run the CLI with a stand-in systemctl
first on PATH), and nothing here needs a display or gi."""
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import helpers

ISLAND_PY = os.path.join(helpers.SCRIPTS, "island.py")
isl = None
events = None


def setUpModule():
    global isl, events
    os.environ["ISLAND_DRY"] = "1"
    if not os.path.exists(ISLAND_PY):
        raise unittest.SkipTest("scripts/island.py is not there yet")
    isl = helpers.import_script("island.py")
    events = helpers.import_script("island_events.py")


def tearDownModule():
    os.environ.pop("ISLAND_DRY", None)


def clean():
    for path in (isl.SETTINGS_FILE,):
        if os.path.exists(path):
            os.remove(path)


def write_raw(text):
    os.makedirs(os.path.dirname(isl.SETTINGS_FILE), exist_ok=True)
    with open(isl.SETTINGS_FILE, "w") as handle:
        handle.write(text)


# -- settings ----------------------------------------------------------------------------------
class Settings(unittest.TestCase):
    setUp = tearDown = staticmethod(clean)

    def test_paths_are_scratch(self):
        self.assertTrue(isl.SETTINGS_FILE.startswith(helpers.SCRATCH))
        self.assertTrue(isl.SOCK.startswith(helpers.SCRATCH))
        self.assertEqual(os.path.basename(isl.SETTINGS_FILE), "island.json")
        self.assertEqual(os.path.basename(isl.SOCK), "island.sock")

    def test_defaults_ship_off(self):
        self.assertEqual(isl.DEFAULTS, {"enabled": False, "monitor": "", "media": True, "timers": True,
                                        "record": True, "railguard": True, "notifications": True,
                                        "notify": False, "ongoing": False,
                                        "style": "notch", "notch_color": "black", "outline": False,
                                        "match_bar": True})
        self.assertEqual(isl.read_settings(), isl.DEFAULTS)

    def test_broken_file_is_the_defaults(self):
        for text in ("{not json", "[1, 2]", "", "null"):
            write_raw(text)
            self.assertEqual(isl.read_settings(), isl.DEFAULTS, text)

    def test_hand_edit_is_cleaned(self):
        write_raw(json.dumps({"media": 0, "notify": 1, "bogus": "x", "monitor": "DP-2"}))
        s = isl.read_settings()
        self.assertNotIn("bogus", s)
        self.assertIs(s["media"], False)
        self.assertIs(s["notify"], True)
        self.assertEqual(set(s), set(isl.DEFAULTS))
        write_raw(json.dumps({"monitor": "D" * 50}))
        self.assertLessEqual(len(isl.read_settings()["monitor"]), 32)
        write_raw(json.dumps({"monitor": 7}))
        self.assertIsInstance(isl.read_settings()["monitor"], str)

    def test_write_is_atomic_and_round_trips(self):
        isl.write_settings(dict(isl.DEFAULTS, media=False, monitor="DP-2"))
        self.assertEqual(isl.read_settings()["media"], False)
        self.assertEqual(isl.read_settings()["monitor"], "DP-2")
        leftovers = [n for n in os.listdir(os.path.dirname(isl.SETTINGS_FILE)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        with open(isl.SETTINGS_FILE) as handle:
            self.assertIn('\n "', handle.read())                  # indent=1

    def test_bool_value(self):
        for text in ("on", "true", "1", "yes"):
            self.assertIs(isl.bool_value(text), True, text)
        for text in ("off", "false", "0", "no"):
            self.assertIs(isl.bool_value(text), False, text)
        for junk in ("maybe", "", "2"):
            with self.assertRaises(ValueError, msg=junk):
                isl.bool_value(junk)

    def test_set_key(self):
        self.assertIs(isl.set_key("media", "off")["media"], False)
        self.assertIs(isl.read_settings()["media"], False)
        self.assertIs(isl.set_key("notify", "yes")["notify"], True)
        self.assertEqual(isl.set_key("monitor", "HDMI-A-1")["monitor"], "HDMI-A-1")
        self.assertEqual(isl.set_key("monitor", "focused")["monitor"], "focused")
        self.assertEqual(isl.set_key("monitor", "auto")["monitor"], "")
        self.assertEqual(isl.set_key("monitor", "")["monitor"], "")

    def test_set_key_refuses_junk(self):
        for key, value in (("nope", "on"), ("media", "maybe"), ("monitor", "DP 1;rm"),
                           ("monitor", "x" * 33), ("monitor", "../x")):
            with self.assertRaises(SystemExit, msg=(key, value)):
                isl.set_key(key, value)
        self.assertFalse(os.path.exists(isl.SETTINGS_FILE))       # nothing written

    def test_dry_enable_never_runs_systemctl(self):
        self.assertTrue(isl.dry_env())
        with mock.patch.object(isl.subprocess, "run") as run:
            self.assertIs(isl.set_key("enabled", "on")["enabled"], True)
            self.assertIs(isl.set_key("enabled", "off")["enabled"], False)
        run.assert_not_called()


# -- the CLI, as a separate process (systemctl and hyprctl are stand-ins) ------------------------
class Cli(unittest.TestCase):
    def setUp(self):
        clean()
        self.bin = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.log = os.path.join(self.bin, "calls.log")
        for name in ("systemctl", "hyprctl"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as handle:
                handle.write(f'#!/bin/sh\necho "{name} $*" >> "{self.log}"\n'
                             '[ "$1" = "monitors" ] && echo "[]"\nexit 0\n')
            os.chmod(path, 0o755)

    tearDown = staticmethod(clean)

    def cli(self, *args, dry=True):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        env.pop("ISLAND_DRY", None)
        if dry:
            env["ISLAND_DRY"] = "1"
        else:
            # Not dry, write_bar_css runs for real -- and island.py's GEN_DIR
            # is ~/.config/waybar/generated (HOME-based, not XDG), so the scratch
            # settings' header-only island-bar.css used to land on the LIVE bar
            # and wipe the notch until the island next reloaded. A scratch HOME
            # keeps it in the sandbox.
            env["HOME"] = self.bin
        return subprocess.run([sys.executable, ISLAND_PY, *args], capture_output=True, text=True,
                              timeout=20, env=env)

    def calls(self):
        try:
            with open(self.log) as handle:
                return handle.read().splitlines()
        except OSError:
            return []

    def test_set_on_off_runs_systemctl(self):
        done = self.cli("set", "on", dry=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("systemctl --user enable --now island.service", self.calls())
        self.assertIs(isl.read_settings()["enabled"], True)
        done = self.cli("set", "enabled", "off", dry=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("systemctl --user disable --now island.service", self.calls())
        self.assertIs(isl.read_settings()["enabled"], False)

    def test_dry_set_on_writes_only(self):
        done = self.cli("set", "on")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIs(isl.read_settings()["enabled"], True)
        self.assertFalse([c for c in self.calls() if c.startswith("systemctl")])

    def test_other_keys_never_touch_systemd(self):
        done = self.cli("set", "media", "off", dry=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("systemctl") and "able" in c])

    def test_bad_set_fails_with_a_message(self):
        done = self.cli("set", "media", "maybe")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("island.py", done.stderr)
        self.assertNotEqual(self.cli("set", "nope", "on").returncode, 0)

    def test_status_json(self):
        done = self.cli("status", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        st = json.loads(done.stdout)
        self.assertEqual(set(st), {"settings", "defaults", "service", "enabled_unit", "running",
                                   "monitors", "sock", "popups"})
        self.assertEqual(set(st["settings"]), set(isl.DEFAULTS))
        self.assertEqual(st["defaults"], isl.DEFAULTS)
        self.assertEqual(st["service"], "dry")
        self.assertIs(st["enabled_unit"], False)
        self.assertIs(st["running"], False)
        self.assertIsInstance(st["monitors"], list)
        self.assertEqual(st["sock"], isl.SOCK)
        plain = self.cli("status")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertTrue(plain.stdout.strip())

    def test_import_does_not_load_gi(self):
        code = ("import importlib.util, sys\n"
                f"spec = importlib.util.spec_from_file_location('island', {ISLAND_PY!r})\n"
                "spec.loader.exec_module(importlib.util.module_from_spec(spec))\n"
                "print('gi' in sys.modules)\n")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                              env=dict(os.environ, ISLAND_DRY="1"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "False")

    def test_executable(self):
        # The settings page runs it by its path (run_json / call), not via python3.
        self.assertTrue(os.access(ISLAND_PY, os.X_OK), "chmod +x island.py")


class Status(unittest.TestCase):
    def test_shape_in_process(self):
        st = isl.status()
        self.assertEqual(set(st), {"settings", "defaults", "service", "enabled_unit", "running",
                                   "monitors", "sock", "popups"})
        self.assertEqual(st["service"], "dry")
        self.assertIs(st["enabled_unit"], False)
        self.assertIs(st["running"], os.path.exists(isl.SOCK) and stat.S_ISSOCK(os.stat(isl.SOCK).st_mode))
        self.assertTrue(all(isinstance(m, str) for m in st["monitors"]))


# -- pure logic ----------------------------------------------------------------------------------
class Words(unittest.TestCase):
    def test_clock(self):
        self.assertEqual([isl.clock(s) for s in (0, 5, 65, 599, 3600, 3723, -5)],
                         ["0:00", "0:05", "1:05", "9:59", "1:00:00", "1:02:03", "0:00"])

    def test_media_text(self):
        self.assertEqual(isl.media_text({"xesam:title": "Song", "xesam:artist": ["A", "B"]}), ("Song", "A, B"))
        self.assertEqual(isl.media_text({"xesam:title": "Song", "xesam:artist": "Solo"}), ("Song", "Solo"))
        self.assertEqual(isl.media_text({"xesam:url": "file:///music/track.mp3"})[0], "track.mp3")
        self.assertEqual(isl.media_text({}), ("", ""))
        self.assertEqual(isl.media_text({"xesam:title": "", "xesam:artist": []}), ("", ""))
        long = "x" * 80
        title, artist = isl.media_text({"xesam:title": long, "xesam:artist": [long]})
        for part in (title, artist):
            self.assertTrue(part.endswith("…"))
            self.assertLessEqual(len(part), 49)
            self.assertGreaterEqual(len(part), 40)


class Players(unittest.TestCase):
    def test_selected_wins(self):
        st = {"mpv": "Playing", "firefox.instance1": "Paused"}
        self.assertEqual(isl.pick_player(list(st), st, "firefox.instance1"), "firefox.instance1")

    def test_selected_that_is_gone_is_ignored(self):
        st = {"mpv": "Playing"}
        self.assertEqual(isl.pick_player(list(st), st, "spotify"), "mpv")

    def test_playing_beats_paused(self):
        st = {"mpv": "Paused", "firefox.instance1": "Playing"}
        self.assertEqual(isl.pick_player(list(st), st, None), "firefox.instance1")

    def test_mpv_before_a_browser(self):
        st = {"firefox.instance1": "Playing", "mpv": "Playing"}
        self.assertEqual(isl.pick_player(list(st), st, None), "mpv")
        st = {"chromium.instance2": "Paused", "vlc": "Paused"}
        self.assertEqual(isl.pick_player(list(st), st, None), "vlc")

    def test_playerctld_skipped(self):
        st = {"playerctld": "Playing", "firefox.instance1": "Paused"}
        self.assertEqual(isl.pick_player(list(st), st, None), "firefox.instance1")
        self.assertIsNone(isl.pick_player(["playerctld"], {"playerctld": "Playing"}, "playerctld"))

    def test_paused_fallback_and_none(self):
        st = {"firefox.instance1": "Paused", "spotify": "Stopped"}
        self.assertEqual(isl.pick_player(list(st), st, None), "firefox.instance1")
        self.assertIsNone(isl.pick_player(["spotify"], {"spotify": "Stopped"}, None))
        self.assertIsNone(isl.pick_player([], {}, None))


class Timers(unittest.TestCase):
    NOW = 1_000_000.0

    def entry(self, id_, left, kind="timer", label="tea", paused=False):
        return {"id": id_, "kind": kind, "label": label, "due": self.NOW + left, "paused": paused}

    def test_ringing_comes_first(self):
        a = isl.timer_activity([self.entry("1", 10)], [{"id": "9", "kind": "alarm", "label": "gym"}], self.NOW)
        self.assertEqual(a["kind"], "ringing")
        self.assertEqual((a["id"], a["label"], a["tkind"]), ("9", "gym", "alarm"))

    def test_the_last_minute(self):
        a = isl.timer_activity([self.entry("1", 300), self.entry("2", 42.7)], [], self.NOW)
        self.assertEqual((a["kind"], a["id"], a["left"], a["tkind"]), ("ending", "2", 42, "timer"))
        self.assertIsNone(isl.timer_activity([self.entry("1", 61)], [], self.NOW))
        self.assertEqual(isl.timer_activity([self.entry("1", 60)], [], self.NOW)["left"], 60)
        self.assertEqual(isl.timer_activity([self.entry("1", 120)], [], self.NOW, window_s=180)["id"], "1")

    def test_paused_and_past_due_skipped(self):
        self.assertIsNone(isl.timer_activity([self.entry("1", 20, paused=True)], [], self.NOW))
        self.assertIsNone(isl.timer_activity([self.entry("1", -5)], [], self.NOW))
        self.assertIsNone(isl.timer_activity([], [], self.NOW))

    def test_label_falls_back_to_the_kind_name(self):
        a = isl.timer_activity([self.entry("1", 20, kind="calendar", label="")], [], self.NOW,
                               names={"calendar": "event"})
        self.assertEqual(a["label"], "event")
        a = isl.timer_activity([self.entry("1", 20, kind="focus", label="")], [], self.NOW, names={})
        self.assertEqual(a["label"], "focus")

    def test_next_wake(self):
        self.assertIsNone(isl.next_timer_wake([], self.NOW, 60))
        self.assertIsNone(isl.next_timer_wake([self.entry("1", 300, paused=True)], self.NOW, 60))
        self.assertAlmostEqual(isl.next_timer_wake([self.entry("1", 300), self.entry("2", 200)], self.NOW, 60), 140)
        self.assertEqual(isl.next_timer_wake([self.entry("1", 30)], self.NOW, 60), 0)    # already inside


class Hiding(unittest.TestCase):
    MONS = [{"name": "DP-1", "focused": False, "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}},
            {"name": "DP-2", "focused": True, "activeWorkspace": {"id": 2}, "specialWorkspace": {"id": -98}}]

    def test_is_game_env(self):
        self.assertTrue(isl.is_game_env(b"PATH=/usr/bin\0SteamAppId=570\0HOME=/h\0"))
        self.assertTrue(isl.is_game_env(b"LUTRIS_GAME_UUID=abc\0"))
        self.assertTrue(isl.is_game_env(b"X=1\0HEROIC_APP_NAME=game"))
        self.assertTrue(isl.is_game_env(b"STEAM_COMPAT_APP_ID=1\0"))
        self.assertFalse(isl.is_game_env(b"PATH=/usr/bin\0NOT_SteamAppId=1\0"))
        self.assertFalse(isl.is_game_env(b""))

    def test_game_running(self):
        quiet = lambda pid: b"PATH=/usr/bin\0"                          # noqa: E731
        self.assertTrue(isl.game_running([{"class": "steam_app_1245620", "pid": 5}], quiet))
        self.assertFalse(isl.game_running([{"class": "steam", "pid": 5}, {"class": "firefox", "pid": 6}], quiet))
        self.assertTrue(isl.game_running([{"class": "game.exe", "pid": 7}],
                                         lambda pid: b"SteamAppId=1\0" if pid == 7 else b""))
        self.assertFalse(isl.game_running([], quiet))

    def test_env_of_failing_is_no_game(self):
        def gone(pid):
            raise OSError("no such process")
        self.assertFalse(isl.game_running([{"class": "firefox", "pid": 9}], gone))
        self.assertTrue(isl.game_running([{"class": "firefox", "pid": 9}, {"class": "steam_app_1", "pid": 3}], gone))

    def test_monitor_hidden(self):
        wss = [{"id": 1, "hasfullscreen": True}, {"id": 2, "hasfullscreen": False},
               {"id": -98, "hasfullscreen": False}]
        self.assertTrue(isl.monitor_hidden(self.MONS, wss, "DP-1"))
        self.assertFalse(isl.monitor_hidden(self.MONS, wss, "DP-2"))          # full screen elsewhere
        self.assertFalse(isl.monitor_hidden(self.MONS, wss, "HDMI-A-9"))      # unknown screen
        self.assertFalse(isl.monitor_hidden(self.MONS, [], "DP-1"))

    def test_special_workspace_full_screen(self):
        wss = [{"id": 1, "hasfullscreen": False}, {"id": 2, "hasfullscreen": False},
               {"id": -98, "hasfullscreen": True}]
        self.assertTrue(isl.monitor_hidden(self.MONS, wss, "DP-2"))
        self.assertFalse(isl.monitor_hidden(self.MONS, wss, "DP-1"))          # its special is 0: none open

    def test_choose_monitor(self):
        self.assertEqual(isl.choose_monitor("focused", self.MONS), "DP-2")
        self.assertEqual(isl.choose_monitor("DP-1", self.MONS), "DP-1")
        self.assertIsNone(isl.choose_monitor("", self.MONS))                  # the caller's main screen
        self.assertIsNone(isl.choose_monitor("HDMI-A-9", self.MONS))          # unplugged: main screen
        self.assertIsNone(isl.choose_monitor("focused", []))


class Ranking(unittest.TestCase):
    def test_priority(self):
        self.assertEqual(isl.PRIORITY, ("record", "railguard", "timers", "notify", "media"))
        acts = {src: {"src": src} for src in ("media", "notify", "timers", "railguard", "record")}
        self.assertEqual(isl.rank(acts), list(isl.PRIORITY))
        self.assertEqual(isl.rank({"media": {"src": "media"}, "railguard": {"src": "railguard"}}),
                         ["railguard", "media"])
        self.assertEqual(isl.rank({"timers": {"src": "timers"}, "notify": {"src": "notify"}}),
                         ["timers", "notify"])
        self.assertEqual(isl.rank({}), [])


class Events(unittest.TestCase):
    def dgram(self, **msg):
        return json.dumps(msg).encode()

    def test_good_events(self):
        e = isl.parse_event(self.dgram(v=1, src="notify", summary="Saved", body="x", app="record",
                                       urgency="normal"))
        self.assertEqual((e["src"], e["summary"], e["app"]), ("notify", "Saved", "record"))
        e = isl.parse_event(self.dgram(v=1, src="railguard", title="Ended", body="b", mood="alert"))
        self.assertEqual((e["src"], e["title"], e["mood"]), ("railguard", "Ended", "alert"))

    def test_junk_is_ignored(self):
        for raw in (b"", b"not json", b"\xff\xfe", b"[1, 2]", b'"text"', b"null",
                    self.dgram(v=1, src="mako", summary="x"),          # not a source it takes
                    self.dgram(v=2, src="notify", summary="x"),        # another version
                    self.dgram(src="notify", summary="x")):            # no version
            self.assertIsNone(isl.parse_event(raw), raw)

    def test_strings_are_cut(self):
        e = isl.parse_event(self.dgram(v=1, src="notify", summary="s" * 1000, body="b" * 400, app="a",
                                       urgency="normal"))
        self.assertEqual(len(e["summary"]), 300)
        self.assertEqual(len(e["body"]), 300)


class Capture(unittest.TestCase):
    """The recording's pid file: a live gpu-screen-recorder, its start
    (the file's mtime) and its target; anything else is no recording."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.pidfile = os.path.join(self.dir, "gsr-record.pid")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()

    def write(self, *lines):
        with open(self.pidfile, "w") as handle:
            handle.write("".join(f"{line}\n" for line in lines))

    def recorder(self):
        """A process whose comm is gpu-screen-reco: sleep, run as a link
        with gpu-screen-recorder's name."""
        link = os.path.join(self.dir, "gpu-screen-recorder")
        os.symlink("/usr/bin/sleep", link)
        p = subprocess.Popen([link, "30"])
        self.procs.append(p)
        return p.pid

    def test_live_recording(self):
        pid = self.recorder()
        self.write(pid, "/videos/a.mp4", "DP-1", "")
        os.utime(self.pidfile, (1_700_000_000, 1_700_000_000))
        self.assertEqual(isl.capture(self.pidfile), (1_700_000_000, "DP-1"))

    def test_target_is_optional(self):
        pid = self.recorder()
        self.write(pid)
        got = isl.capture(self.pidfile)
        self.assertIsNotNone(got)
        self.assertEqual(got[1], "")
        self.assertAlmostEqual(got[0], os.stat(self.pidfile).st_mtime)

    def test_someone_else_is_no_recording(self):
        self.write(os.getpid(), "/videos/a.mp4", "DP-1")             # python, not the recorder
        self.assertIsNone(isl.capture(self.pidfile))
        self.assertTrue(os.path.exists(self.pidfile))                  # never deleted

    def test_junk_and_missing(self):
        self.write("abc", "x", "y")
        self.assertIsNone(isl.capture(self.pidfile))
        self.write("")
        self.assertIsNone(isl.capture(self.pidfile))
        self.write("99999999")                                         # no such process
        self.assertIsNone(isl.capture(self.pidfile))
        self.assertIsNone(isl.capture(os.path.join(self.dir, "missing.pid")))

    def test_fake_proc(self):
        """The same check with /proc stubbed: only the comm decides."""
        self.write("4242", "/videos/a.mp4", "region")
        real_open = open

        def fake_open(path, *args, **kwargs):
            if str(path) == "/proc/4242/comm":
                return real_open(os.path.join(self.dir, "comm"), *args, **kwargs)
            return real_open(path, *args, **kwargs)
        with real_open(os.path.join(self.dir, "comm"), "w") as handle:
            handle.write("gpu-screen-reco\n")
        with mock.patch("builtins.open", fake_open):
            got = isl.capture(self.pidfile)
        if got is None:
            self.skipTest("capture() reads /proc some other way than open()")
        self.assertEqual(got[1], "region")

    def test_outcome(self):
        """How a recording ended, once its file is gone: saved only for a
        real run that left a non-empty file and a recorder that exited."""
        out = os.path.join(self.dir, "a.mp4")
        now = 1_700_000_100
        act = {"started": now - 60, "pid": "99999999", "out": out}
        self.assertEqual(isl.record_outcome(act, now), "stopped")       # no file
        with open(out, "w") as handle:
            handle.write("")
        self.assertEqual(isl.record_outcome(act, now), "stopped")       # empty file
        with open(out, "w") as handle:
            handle.write("data")
        self.assertEqual(isl.record_outcome(act, now), "saved")
        self.assertEqual(isl.record_outcome(dict(act, started=now - 0.5), now), "failed")
        alive = dict(act, pid=str(self.recorder()))                     # did not stop
        self.assertEqual(isl.record_outcome(alive, now), "stopped")


# -- island_events.py: the other end of the socket -----------------------------------------------
class Styles(unittest.TestCase):
    def setUp(self):
        if os.path.exists(isl.SETTINGS_FILE):
            os.remove(isl.SETTINGS_FILE)

    def test_style_is_checked(self):
        for style in isl.STYLES:
            self.assertEqual(isl.set_key("style", style)["style"], style)
        self.assertEqual(isl.set_key("style", " Island ")["style"], "island")
        with self.assertRaises(SystemExit):
            isl.set_key("style", "neon")
        self.assertEqual(isl.read_settings()["style"], "island")

    def test_the_old_designs_are_a_notch_with_their_colour_or_outline(self):
        got = isl.set_key("style", "glass")
        self.assertEqual((got["style"], got["notch_color"]), ("notch", "glass"))
        got = isl.set_key("style", "outline")
        self.assertEqual((got["style"], got["outline"]), ("notch", True))
        for old, want in (("glass", ("glass", False)), ("outline", ("black", True))):
            with open(isl.SETTINGS_FILE, "w") as fh:
                json.dump({"style": old, "notch_color": "black", "outline": False}, fh)
            got = isl.read_settings()
            self.assertEqual((got["style"], got["notch_color"], got["outline"]), ("notch",) + want, old)

    def test_outline_on_any_design(self):
        for style in isl.STYLES:
            cfg = dict(isl.DEFAULTS, enabled=True, style=style, outline=True)
            self.assertIn("border: 1px solid @edge-lit;", isl.fill_css(cfg), style)
            self.assertNotIn("@edge-lit", isl.fill_css(dict(cfg, outline=False)), style)
            if style in isl.SHAPES:
                self.assertIn("border: 1px solid @edge-lit;", isl.bar_css(cfg), style)
                self.assertNotIn("@edge-lit", isl.bar_css(dict(cfg, outline=False)), style)
        # the notch hangs from the edge: no line on top, and the bar's top
        # row (the one measured) stays the fill
        notch = dict(isl.DEFAULTS, enabled=True, outline=True)
        self.assertIn("border-top-width: 0;", isl.fill_css(notch))
        self.assertIn("border-top: 1px solid #000000;", isl.bar_css(notch))
        self.assertNotIn("border-top-width: 0;", isl.fill_css(dict(notch, style="island")))

    def test_a_bad_style_in_the_file_is_the_default(self):
        os.makedirs(isl.STATE_DIR, exist_ok=True)
        with open(isl.SETTINGS_FILE, "w") as fh:
            json.dump({"style": "neon"}, fh)
        self.assertEqual(isl.read_settings()["style"], "notch")

    def test_the_bar_matches_the_island(self):
        cfg = dict(isl.DEFAULTS, enabled=True)
        css = isl.bar_css(cfg)
        self.assertIn(".modules-center", css)
        self.assertIn("#000000", css)
        self.assertNotIn("min-width", css)                    # its natural width
        self.assertIn("#custom-updates.many", css)          # fills become text
        self.assertIn("border-radius: 999px", isl.bar_css(dict(cfg, style="island")))
        for off in (dict(cfg, enabled=False), dict(cfg, match_bar=False), dict(cfg, style="theme")):
            self.assertNotIn("{", isl.bar_css(off), off)     # a comment only

    def test_bar_css_is_never_written_in_tests(self):
        self.assertFalse(isl.write_bar_css(dict(isl.DEFAULTS, enabled=True)))

    def test_notch_color_is_checked(self):
        self.assertEqual(isl.read_settings()["notch_color"], "black")
        self.assertEqual(isl.set_key("notch_color", "glass")["notch_color"], "glass")
        self.assertEqual(isl.set_key("notch_color", " Theme ")["notch_color"], "theme")
        with self.assertRaises(SystemExit):
            isl.set_key("notch_color", "pink")
        self.assertEqual(isl.read_settings()["notch_color"], "theme")
        with open(isl.SETTINGS_FILE, "w") as fh:
            json.dump({"notch_color": "pink"}, fh)
        self.assertEqual(isl.read_settings()["notch_color"], "black")

    def test_accent_from_accent_css(self):
        text = "/* x */\n@define-color cyan #8C245F;\n@define-color cyan  #11aa22 ;\n"
        self.assertEqual(isl.accent_hex(text), "#11aa22")          # the last one, as GTK
        self.assertIsNone(isl.accent_hex("@define-color cyan alpha(#fff, 0.5);"))
        self.assertIsNone(isl.theme_accent("/nonexistent/accent.css"))

    def test_the_theme_colour_is_made_readable(self):
        for accent in ("#f78fb3", "#007aff", "#ffffff", "#00f0ff", "#8c245f", "#000000"):
            fill = isl.rgb(isl.readable(accent))
            self.assertGreaterEqual(isl.contrast(fill, isl.TEXT_HI), isl.MIN_HI, accent)
            self.assertGreaterEqual(isl.contrast(fill, isl.TEXT_LO), isl.MIN_LO, accent)
        self.assertEqual(isl.readable("#1a0a12"), "#1a0a12")       # dark already: as it is
        r, g, b = isl.rgb(isl.readable("#f78fb3"))
        self.assertTrue(r > b > g)                                  # still pink, only deeper

    def test_notch_fill(self):
        cfg = dict(isl.DEFAULTS, enabled=True, notch_color="theme")
        self.assertEqual(isl.notch_fill(dict(cfg, notch_color="black"), "#f78fb3"), "#000000")
        self.assertEqual(isl.notch_fill(cfg, None), "#000000")      # no accent to read
        self.assertEqual(isl.notch_fill(dict(cfg, style="theme"), "#f78fb3"), "#000000")
        fill = isl.notch_fill(cfg, "#f78fb3")
        self.assertNotEqual(fill, "#000000")
        self.assertEqual(isl.notch_fill(dict(cfg, style="island"), "#f78fb3"), fill)
        # the island and the bar's notch get the same fill
        self.assertIn(f"background-color: {fill};", isl.bar_css(cfg, accent="#f78fb3"))
        self.assertNotIn("#000000;", isl.bar_css(cfg, accent="#f78fb3").split("}")[0])
        self.assertIn(fill, isl.fill_css(cfg, "#f78fb3"))
        self.assertIn("island-style-notch", isl.fill_css(cfg, "#f78fb3"))
        self.assertIn("#000000", isl.fill_css(dict(cfg, notch_color="black"), "#f78fb3"))
        self.assertNotIn("background", isl.fill_css(dict(cfg, style="theme"), "#f78fb3"))

    def test_glass(self):
        cfg = dict(isl.DEFAULTS, enabled=True, notch_color="glass")
        for style in isl.SHAPES:
            c = dict(cfg, style=style)
            self.assertEqual(isl.notch_fill(c), isl.GLASS)
            self.assertIn(isl.GLASS, isl.fill_css(c))
            self.assertIn(isl.FROST, isl.fill_css(c))            # its frosted edge
            self.assertIn(isl.GLASS, isl.bar_css(c))
            self.assertIn("@edge-lit", isl.fill_css(dict(c, outline=True)))   # outline wins
        # the bar's measured row is black: the notch's top line, the
        # capsule's inner line
        self.assertIn("border-top: 1px solid #000000;", isl.bar_css(cfg))
        self.assertIn("box-shadow: inset 0 1px 0 0 #000000;", isl.bar_css(dict(cfg, style="island")))

    def test_the_measured_row(self):
        cfg = dict(isl.DEFAULTS, enabled=True)
        self.assertEqual(isl.measure_spec(cfg), (0, "#000000", 0))
        self.assertEqual(isl.measure_spec(dict(cfg, outline=True)), (0, "#000000", 0))
        self.assertEqual(isl.measure_spec(dict(cfg, notch_color="glass")), (0, "#000000", 0))
        fill = isl.readable("#f78fb3")
        self.assertEqual(isl.measure_spec(dict(cfg, notch_color="theme"), "#f78fb3"), (0, fill, 0))
        island = dict(cfg, style="island")
        self.assertEqual(isl.measure_spec(island), (5, "#000000", 10))
        self.assertEqual(isl.measure_spec(dict(island, outline=True)), (6, "#000000", 9))
        self.assertEqual(isl.measure_spec(dict(island, notch_color="glass")), (5, "#000000", 13))
        # every colour the measuring looks for is one rgb() reads
        for c in (cfg, dict(cfg, notch_color="glass"), dict(island, notch_color="glass")):
            isl.rgb(isl.measure_spec(c)[1])


class Tucked(unittest.TestCase):
    def test_media_tucks_into_the_notch_only_with_a_bar_look(self):
        on = dict(isl.DEFAULTS, enabled=True)
        self.assertTrue(isl.tucked(on))
        for off in (dict(on, enabled=False), dict(on, match_bar=False), dict(on, style="theme"),
                    dict(on, media=False)):
            self.assertFalse(isl.tucked(off), off)

    def test_kept_sources_show_with_the_ongoing_pill_off(self):
        acts = {"media": {"src": "media", "ongoing": True, "expand": False, "key": "t"}}
        self.assertEqual(isl.shown(acts, False, set()), {})
        self.assertIn("media", isl.shown(acts, False, set(), keep=("media",)))
        self.assertEqual(isl.shown(acts, False, {("media", "t")}, keep=("media",)), {})

    def test_the_bar_keeps_the_thumbnail_slot_only_with_media(self):
        cfg = dict(isl.DEFAULTS, enabled=True)
        self.assertIn(f"padding: 0 {12 + isl.MINI_SLOT}px 0 12px", isl.bar_css(cfg, slot=True))
        self.assertIn("padding: 0 12px 0 12px", isl.bar_css(cfg))


class NotchWidth(unittest.TestCase):
    @staticmethod
    def row(pixels):
        return bytes(c for px in pixels for c in px)

    def test_ppm(self):
        data = b"P6\n3 1\n255\n" + bytes(9)
        self.assertEqual(isl.parse_ppm(data), (3, 1, bytes(9)))
        self.assertIsNone(isl.parse_ppm(b"P5\n1 1\n255\n\x00"))
        self.assertIsNone(isl.parse_ppm(b"P6\n3 1\n255\n\x00"))   # cut short

    def test_the_dark_run_through_the_middle(self):
        wall, black = (120, 140, 200), (0, 0, 0)
        px = [wall] * 40 + [black] * 20 + [wall] * 40              # 100 px, notch 40..59
        self.assertEqual(isl.notch_half(self.row(px), 100), 10)

    def test_a_dark_wallpaper_on_one_side_does_not_widen_it(self):
        wall, black = (120, 140, 200), (0, 0, 0)
        px = [black] * 60 + [wall] * 40                              # dark all the way left
        px[50] = (5, 5, 5)
        self.assertEqual(isl.notch_half(self.row(px), 100), 10)

    def test_a_coloured_notch(self):
        wall, fill = (120, 140, 200), (90, 20, 50)
        px = [wall] * 40 + [fill] * 20 + [wall] * 40
        self.assertEqual(isl.notch_half(self.row(px), 100, fill=fill), 10)
        self.assertIsNone(isl.notch_half(self.row(px), 100))         # not black

    def test_the_thumbnail_on_the_row_is_bridged(self):
        wall, black, thumb = (120, 140, 200), (0, 0, 0), (26, 26, 26)
        px = [wall] * 20 + [black] * 45 + [thumb] * 10 + [black] * 5 + [wall] * 20   # 100 px
        self.assertEqual(isl.notch_half(self.row(px), 100), 15)
        self.assertEqual(isl.notch_half(self.row(px), 100, gap=12), 30)
        self.assertEqual(isl.notch_half(self.row(px), 100, gap=40), 30)    # never past the wall

    def test_no_notch(self):
        self.assertIsNone(isl.notch_half(self.row([(200, 200, 200)] * 50), 50))


class Drops(unittest.TestCase):
    def test_only_alerts_drop_below_the_bar(self):
        self.assertTrue(isl.drops({"src": "railguard"}))
        self.assertTrue(isl.drops({"src": "timers", "kind": "ringing"}))
        for act in ({"src": "timers", "kind": "ending"}, {"src": "media"},
                    {"src": "record"}, {"src": "notify"}):
            self.assertFalse(isl.drops(act), act)


class EventHelper(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.sock_path = os.path.join(self.dir, "island.sock")
        self.patch = mock.patch.object(events, "SOCK", self.sock_path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_off_is_a_quick_no(self):
        start = time.monotonic()
        self.assertFalse(events.notify("hello"))
        self.assertFalse(events.railguard("Ended", "x"))
        self.assertLess(time.monotonic() - start, 0.5)

    def test_stale_socket_file_is_a_quiet_no(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(self.sock_path)
        s.close()                                                      # the file stays, nobody listens
        self.assertTrue(os.path.exists(self.sock_path))
        self.assertFalse(events.notify("hello"))

    def test_what_it_sends_the_island_takes(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.bind(self.sock_path)
            s.settimeout(2)
            self.assertTrue(events.notify("Saved " + "x" * 500, "body", app="record", urgency="low"))
            self.assertTrue(events.railguard("Ended a runaway", "firefox, 9 GB", mood="relieved"))
            got = [isl.parse_event(s.recv(8192)) for _ in range(2)]
        self.assertEqual(got[0]["src"], "notify")
        self.assertEqual(len(got[0]["summary"]), 300)
        self.assertEqual(got[0]["urgency"], "low")
        self.assertEqual((got[1]["src"], got[1]["mood"]), ("railguard", "relieved"))


if __name__ == "__main__":
    unittest.main()
