"""The daemons that back off on battery (power_state.period), and the ones
that wake for a file instead of a clock (file_wake.py).

Every loop here asks power_state.period(normal, battery) for its pace, again
each time round; the tests stub period() (it is one shared module: the
scripts all `import power_state` from the scripts folder) and check each
loop asks it with its own two numbers and then sleeps what it was told.
The few that must NOT back off are pinned too: railguard's RAM watch (1 s,
always), a focus block's tick, the emergency early warnings unless
battery_poll is on, and the island's clock (it only ticks while it shows
seconds). The last class runs the real power_state against a fake
power_supply tree: a desktop gets every normal pace, an unplugged laptop
every battery one.

Hermetic: helpers.py points HOME's state / runtime folders and
ATRIUM_POWER_SUPPLY at a scratch folder; nothing here reads /sys or starts a
service."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import helpers

rg = helpers.import_script("railguard.py")
timers = helpers.import_script("timers.py", "timers")
tasks = helpers.import_script("tasks.py", "tasks")
gpu = helpers.import_script("gpu.py")
SL = helpers.import_script("smartlayout.py")
FG = helpers.import_script("focus-guard.py", "focus_guard")
suggest = helpers.import_script("suggest.py")
ST = helpers.import_script("screentime.py")
A = helpers.import_script("ambient.py")
ea = helpers.import_script("emergency-alerts.py")
ps = rg.power_state                  # the one module every script imported
import file_wake  # noqa: E402  (the scripts put their folder on sys.path)

CPU_USAGE = os.path.join(os.path.dirname(helpers.SCRIPTS), "..", "waybar", "scripts", "cpu_usage.sh")


class Asked:
    """A stand-in for power_state.period: records each (normal, battery)
    and answers the battery value when `battery`, else the normal one."""

    def __init__(self, battery=False):
        self.battery, self.calls = battery, []

    def __call__(self, normal, battery_s):
        self.calls.append((normal, battery_s))
        return battery_s if self.battery else normal


def stub(battery=False):
    asked = Asked(battery)
    return asked, mock.patch.object(ps, "period", asked)


class SharedModule(unittest.TestCase):
    def test_every_script_uses_the_same_power_state(self):
        for mod in (rg, tasks, SL, FG, suggest, ST, A, ea):
            self.assertIs(mod.power_state, ps, mod.__name__)


# -- file_wake ------------------------------------------------------------------------------
class FileWake(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wake-", dir=helpers.SCRATCH)

    def write_later(self, name, delay=0.1, rename=True):
        def go():
            time.sleep(delay)
            path = os.path.join(self.dir, name)
            if rename:
                with open(path + ".tmp", "w") as handle:
                    handle.write("{}")
                os.replace(path + ".tmp", path)
            else:
                with open(path, "w") as handle:
                    handle.write("{}")
        t = threading.Thread(target=go)
        t.start()
        return t

    def test_a_rename_of_the_watched_name_wakes_it(self):
        w = file_wake.Watch({self.dir: {"timers.json"}})
        self.assertTrue(w.ok)
        t = self.write_later("timers.json")
        start = time.monotonic()
        self.assertTrue(w.wait(5))
        self.assertLess(time.monotonic() - start, 2)
        t.join()
        w.close()

    def test_other_names_do_not(self):
        w = file_wake.Watch({self.dir: {"timers.json"}})
        t = self.write_later("other.json", rename=False)
        self.assertFalse(w.wait(0.4))
        t.join()
        w.close()

    def test_none_is_any_name_and_a_missing_folder_is_made(self):
        folder = os.path.join(self.dir, "not-yet")
        w = file_wake.Watch({folder: None})
        self.assertTrue(os.path.isdir(folder))
        self.dir = folder
        t = self.write_later("poke.run", rename=False)
        self.assertTrue(w.wait(5))
        t.join()
        w.close()

    def test_a_renamed_mask_ignores_writes_in_place_next_door(self):
        """file_wake.RENAMED: an append to a neighbour (activity.jsonl) never
        wakes it; the rename of the watched name still does."""
        w = file_wake.Watch({self.dir: {"timers.json"}}, masks={self.dir: file_wake.RENAMED})
        with open(os.path.join(self.dir, "activity.jsonl"), "a") as handle:
            handle.write("{}\n")
        self.assertEqual(w.drain(), set())
        r, _, _ = __import__("select").select([w.fileno()], [], [], 0.05)
        self.assertEqual(r, [])                     # not even woken
        t = self.write_later("timers.json")
        self.assertTrue(w.wait(5))
        t.join()
        w.close()

    def test_drain_names_what_changed(self):
        w = file_wake.Watch({self.dir: None})
        with open(os.path.join(self.dir, "a.run"), "w"):
            pass
        time.sleep(0.05)
        self.assertEqual(w.drain(), {"a.run"})
        w.close()

    def test_an_overflow_counts_as_a_change(self):
        """IN_Q_OVERFLOW (wd -1): something was lost, so look again."""
        w = file_wake.Watch({self.dir: {"timers.json"}})
        raw = (-1).to_bytes(4, sys.byteorder, signed=True) + file_wake.IN_Q_OVERFLOW.to_bytes(4, sys.byteorder) \
            + bytes(8)
        self.assertEqual(w._matters(raw), {file_wake.ANY})
        w.close()

    def test_a_folder_removed_and_made_again_is_watched_again(self):
        folder = os.path.join(self.dir, "rings")
        w = file_wake.Watch({folder: None})
        shutil.rmtree(folder)
        self.assertTrue(w.wait(5))                  # the folder going: a fresh look
        self.assertTrue(w.ok)
        self.assertTrue(os.path.isdir(folder))      # made again, and watched
        self.dir = folder
        t = self.write_later("ring-1.json")
        self.assertTrue(w.wait(5))
        t.join()
        w.close()

    def test_a_watch_that_cannot_come_back_closes_so_callers_fall_back(self):
        folder = os.path.join(self.dir, "gone")
        w = file_wake.Watch({folder: None})
        with mock.patch.object(w, "_add", return_value=-1):
            shutil.rmtree(folder)
            self.assertTrue(w.wait(5))
        self.assertFalse(w.ok)                      # timers' bar: back to 1 s

    def test_without_inotify_it_only_sleeps(self):
        w = file_wake.Watch({self.dir: None})
        w.close()
        self.assertFalse(w.ok)
        with mock.patch.object(file_wake.time, "sleep") as sleep:
            self.assertFalse(w.wait(3))
        sleep.assert_called_once_with(3.0)


# -- railguard ------------------------------------------------------------------------------
class Railguard(unittest.TestCase):
    def test_gpu_pace_asks_period(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(rg.gpu_every(), rg.GPU_BATTERY_S)
        self.assertEqual(asked.calls, [(rg.GPU_EVERY, rg.GPU_BATTERY_S)])

    def run_daemon(self, battery, ticks=30):
        """The loop for TICKS seconds of a fake clock: [(when, gap)] of the
        GPU checks, and every sleep it asked."""
        clock = [1000.0]
        sleeps, checks = [], []

        def sleep(s):
            sleeps.append(s)
            if len(sleeps) > ticks:
                raise KeyboardInterrupt
            clock[0] += s
        asked, patch = stub(battery)
        with patch, mock.patch.object(rg.time, "sleep", sleep), \
                mock.patch.object(rg.time, "monotonic", lambda: clock[0]), \
                mock.patch.object(rg, "gpu_card", return_value={"name": "card", "source": "test"}), \
                mock.patch.object(rg, "check_vram", lambda state, every: checks.append((clock[0], every))), \
                mock.patch.object(rg, "check_ram") as ram, \
                mock.patch.object(rg, "load_settings"), mock.patch.object(rg, "log"), \
                mock.patch.dict(rg.CFG, {"ram": True, "vram": True}):
            with self.assertRaises(KeyboardInterrupt):
                rg.daemon()
        return sleeps, checks, ram, asked

    def test_on_battery_the_gpu_is_checked_every_9_s(self):
        sleeps, checks, ram, asked = self.run_daemon(battery=True)
        gaps = [b[0] - a[0] for a, b in zip(checks, checks[1:])]
        self.assertTrue(gaps and all(g == rg.GPU_BATTERY_S for g in gaps), gaps)
        self.assertTrue(all(c == (rg.GPU_EVERY, rg.GPU_BATTERY_S) for c in asked.calls))
        # the gap handed to check_vram is the time since the previous check
        self.assertEqual([e for _, e in checks[1:]], gaps)

    def test_the_ram_watch_stays_at_one_second_on_battery(self):
        sleeps, _checks, ram, _asked = self.run_daemon(battery=True)
        self.assertTrue(all(s == rg.TICK == 1.0 for s in sleeps))
        self.assertEqual(ram.call_count, len(sleeps) - 1)

    def test_on_mains_it_is_as_before(self):
        _sleeps, checks, _ram, _asked = self.run_daemon(battery=False)
        gaps = [b[0] - a[0] for a, b in zip(checks, checks[1:])]
        self.assertTrue(gaps and all(g == rg.GPU_EVERY for g in gaps), gaps)

    def test_vram_s_is_counted_in_seconds(self):
        """Full for vram_s means the same at 3 s or 9 s a sample."""
        card = {"name": "x"}
        with mock.patch.dict(rg.CFG, {"vram_pct": 97.0, "vram_s": 12}), \
                mock.patch.object(rg, "gpu_card", return_value=card), \
                mock.patch.object(rg, "gpu_memory", return_value=(990, 1000)), \
                mock.patch.object(rg, "gpu_processes", return_value={}) as procs, \
                mock.patch.object(rg, "notify"):
            state = {"psi": 0, "vram": 0, "quiet": 0.0}
            rg.check_vram(state, 9)
            procs.assert_not_called()               # 9 s full: not yet
            self.assertEqual(state["vram"], 9)
            rg.check_vram(state, 9)
            procs.assert_called_once()              # 18 s: acts
            state = {"psi": 0, "vram": 0, "quiet": 0.0}
            procs.reset_mock()
            for _ in range(3):
                rg.check_vram(state, 3)
            procs.assert_not_called()               # 9 s at 3 s a sample
            rg.check_vram(state, 3)
            procs.assert_called_once()              # 12 s

    def test_a_single_reading_never_acts_at_the_slow_pace(self):
        """vram_s 4-9 at 9 s a sample: the first full reading alone would
        meet it; a brief spike must not cost a process, so it waits for a
        second reading in a row."""
        with mock.patch.dict(rg.CFG, {"vram_pct": 97.0, "vram_s": 6}), \
                mock.patch.object(rg, "gpu_card", return_value={"name": "x"}), \
                mock.patch.object(rg, "gpu_memory", side_effect=[(990, 1000), (100, 1000), (990, 1000),
                                                                 (990, 1000)]), \
                mock.patch.object(rg, "gpu_processes", return_value={}) as procs, \
                mock.patch.object(rg, "notify"):
            state = {"psi": 0, "vram": 0, "vram_n": 0, "quiet": 0.0}
            rg.check_vram(state, 9)
            procs.assert_not_called()               # one full reading: a spike, maybe
            rg.check_vram(state, 9)
            self.assertEqual((state["vram"], state["vram_n"]), (0, 0))    # it passed
            rg.check_vram(state, 9)
            procs.assert_not_called()
            rg.check_vram(state, 9)
            procs.assert_called_once()              # two in a row: acts

    def test_the_readings_rule_changes_nothing_on_mains(self):
        # vram_s 3 acted on one 3 s reading before, and still does
        self.assertEqual([rg.vram_readings(v) for v in (3, 4, 6, 12, 120)], [1, 2, 2, 2, 2])


# -- timers' bar -------------------------------------------------------------------------------
class TimersBar(unittest.TestCase):
    def setUp(self):
        self.saved = None
        if os.path.exists(timers.STATE):
            with open(timers.STATE) as handle:
                self.saved = handle.read()
        shutil.rmtree(timers.RING_DIR, ignore_errors=True)

    def tearDown(self):
        if self.saved is None:
            try:
                os.remove(timers.STATE)
            except OSError:
                pass
        else:
            with open(timers.STATE, "w") as handle:
                handle.write(self.saved)

    def state(self, items=(), stopwatch=None):
        timers.save({"timers": list(items), "stopwatch": stopwatch})
        return timers.bar_state()

    def timer(self, due, **extra):
        return dict({"id": "t1", "kind": "timer", "label": "tea", "due": due}, **extra)

    def test_nothing_set_does_not_count(self):
        st = self.state()
        self.assertFalse(st["counting"])
        self.assertIsNone(st["next_change"])
        self.assertEqual(json.loads(st["line"])["class"], "idle")

    def test_a_countdown_within_the_day_counts(self):
        self.assertTrue(self.state([self.timer(time.time() + 300)])["counting"])

    def test_a_running_stopwatch_counts_a_paused_one_does_not(self):
        self.assertTrue(self.state(stopwatch={"start": time.time() - 10, "acc": 0.0})["counting"])
        self.assertFalse(self.state(stopwatch={"start": None, "acc": 42.0})["counting"])

    def test_a_far_timer_is_a_next_change(self):
        due = time.time() + 2 * 86400
        st = self.state([self.timer(due, kind="alarm")])
        self.assertFalse(st["counting"])
        self.assertAlmostEqual(st["next_change"], due - 86400, places=3)

    def test_a_shown_pill_with_a_far_countdown_in_its_tooltip_counts(self):
        st = self.state([self.timer(time.time() + 2 * 86400, kind="alarm")],
                        stopwatch={"start": None, "acc": 42.0})
        self.assertTrue(st["counting"])

    def test_a_paused_alarm_never_counts(self):
        st = self.state([self.timer(time.time() + 300, paused=True, hm="07:30")])
        self.assertFalse(st["counting"])
        self.assertIsNone(st["next_change"])

    def test_bar_wait(self):
        now = 1_000_000.25          # 40.25 s into a minute
        counting = {"counting": True, "next_change": None}
        idle = {"counting": False, "next_change": None}
        self.assertAlmostEqual(timers.bar_wait(counting, now, True), 0.77)
        self.assertAlmostEqual(timers.bar_wait(idle, now, True), 60 - 40.25 + 0.02)
        self.assertAlmostEqual(timers.bar_wait(idle, now, False), 0.77)        # no inotify: as before
        soon = {"counting": False, "next_change": now + 5}
        self.assertAlmostEqual(timers.bar_wait(soon, now, True), 5.02)

    def test_the_watch_sleeps_on_its_watcher(self):
        class Watcher:
            ok = True

            def __init__(self):
                self.waits = []

            def wait(self, seconds):
                self.waits.append(seconds)
                if len(self.waits) >= 2:
                    raise KeyboardInterrupt
                return True
        timers.save({"timers": [], "stopwatch": None})
        w = Watcher()
        with mock.patch("builtins.print") as out, self.assertRaises(KeyboardInterrupt):
            timers.bar(True, watcher=w)
        self.assertTrue(all(s > 1.0 for s in w.waits), w.waits)     # idle: a minute, not a second
        self.assertEqual(out.call_count, 1)                          # the same line is not printed twice

    def test_a_new_timer_wakes_the_real_watch(self):
        timers.save({"timers": [], "stopwatch": None})
        w = file_wake.Watch({os.path.dirname(timers.STATE): {os.path.basename(timers.STATE)},
                             timers.RING_DIR: None})
        self.assertTrue(w.ok)
        threading.Timer(0.1, lambda: timers.save({"timers": [self.timer(time.time() + 300)],
                                                  "stopwatch": None})).start()
        self.assertTrue(w.wait(5))
        w.close()


# -- island: it already ticks only while it shows seconds -------------------------------------
class IslandClock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["ISLAND_DRY"] = "1"
        cls.isl = helpers.import_script("island.py")

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("ISLAND_DRY", None)

    def test_only_the_recording_and_a_timers_last_minute_tick(self):
        now = time.time()
        d = self.isl.describe
        self.assertTrue(d({"src": "record", "phase": "live", "started": now - 5}, now)["clock"])
        self.assertTrue(d({"src": "timers", "kind": "countdown", "due": now + 30, "label": "tea"}, now)["clock"])
        for act in ({"src": "record", "phase": "saved"}, {"src": "timers", "kind": "ringing", "label": "x"},
                    {"src": "media", "status": "Playing", "title": "song"},
                    {"src": "notify", "app": "a", "summary": "b"},
                    {"src": "railguard", "title": "t", "body": "b"}):
            self.assertFalse(d(act, now)["clock"], act)


# -- tasks -----------------------------------------------------------------------------------
class Tasks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tasks-backoff-", dir=helpers.SCRATCH)
        self.old = (tasks.CONFIG, tasks.STATE_DIR, tasks.DAEMON_STATE, tasks.POKES, tasks.log)
        tasks.CONFIG = os.path.join(self.dir, "tasks.json")
        tasks.STATE_DIR = os.path.join(self.dir, "state")
        tasks.DAEMON_STATE = os.path.join(self.dir, "daemon.json")
        tasks.POKES = os.path.join(self.dir, "pokes")
        tasks.log = lambda text: None
        os.makedirs(tasks.STATE_DIR)

    def tearDown(self):
        tasks.CONFIG, tasks.STATE_DIR, tasks.DAEMON_STATE, tasks.POKES, tasks.log = self.old

    def test_tick_asks_period(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(tasks.tick_s(), 5)
        self.assertEqual(asked.calls, [(tasks.TICK_S, tasks.TICK_BATTERY_S)])

    def test_the_loop_waits_on_its_watch_for_the_pace(self):
        made = {}

        class Waker:
            ok = True

            def __init__(self, folders):
                made["folders"], self.waits = folders, []
                made["waker"] = self

            def wait(self, seconds):
                self.waits.append(seconds)
                d.stop = True
                return False

            def close(self):
                pass
        d = tasks.Daemon()
        asked, patch = stub(battery=True)
        old = signal.getsignal(signal.SIGTERM)
        try:
            with patch, mock.patch.object(tasks.file_wake, "Watch", Waker), \
                    mock.patch.object(tasks.threading, "Thread"):
                d.run()
        finally:
            signal.signal(signal.SIGTERM, old)
        self.assertEqual(made["waker"].waits, [tasks.TICK_BATTERY_S])
        self.assertIn(tasks.POKES, made["folders"])                 # Run / Stop answered at once
        self.assertEqual(made["folders"][os.path.dirname(tasks.CONFIG)], {"tasks.json"})
        self.assertIn((tasks.TICK_S, tasks.TICK_BATTERY_S), asked.calls)

    def test_daemon_state_says_the_pace_and_is_not_rewritten_unchanged(self):
        d = tasks.Daemon()
        d.pace = 5
        d.write_state()
        with open(tasks.DAEMON_STATE) as handle:
            self.assertEqual(json.load(handle)["tick_s"], 5)
        with mock.patch.object(tasks.os, "replace") as replace:
            d.write_state()
        replace.assert_not_called()

    def test_update_state_skips_a_write_that_changes_nothing(self):
        tasks.update_state("t1", status="watching")
        with mock.patch.object(tasks.os, "replace") as replace:
            st = tasks.update_state("t1", status="watching")
        replace.assert_not_called()
        self.assertEqual(st, {"status": "watching"})
        tasks.update_state("t1", status="waiting")
        self.assertEqual(tasks.get_state("t1"), {"status": "waiting"})

    def test_update_state_still_creates_a_missing_file(self):
        tasks.update_state("t2")
        self.assertTrue(os.path.exists(tasks.path_for("t2", "json")))


# -- gpu.py stream / cpu_usage.sh ---------------------------------------------------------------
class GpuStream(unittest.TestCase):
    def test_gap_asks_period(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(gpu.stream_gap(5.0), 15.0)
        self.assertEqual(asked.calls, [(5.0, 15.0)])

    def test_the_stream_sleeps_the_gap(self):
        card = {"pci": "0000:01:00.0", "source": "nvml", "vendor": "nvidia", "util": 10, "temp": 50,
                "vram_used": 100, "vram_total": 1000, "power": 20, "fan": 30}
        slept = []

        def sleep(s):
            slept.append(s)
            raise KeyboardInterrupt
        asked, patch = stub(battery=True)
        with patch, mock.patch.object(gpu, "gpus", return_value=[card]), \
                mock.patch.object(gpu, "display_card", return_value=card), \
                mock.patch.object(gpu, "shown_card", return_value=(card, "display")), \
                mock.patch.object(gpu.time, "sleep", sleep), mock.patch("builtins.print"):
            with self.assertRaises(KeyboardInterrupt):
                gpu.stream(5.0)
        self.assertEqual(slept, [15.0])


class CpuUsage(unittest.TestCase):
    """cpu_usage.sh's pace: power_state.on_battery()'s rule read from sysfs
    with bash builtins, and the saver's battery-saver.json."""

    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="cpu-run-", dir=helpers.SCRATCH)
        self.supply = os.path.join(tempfile.mkdtemp(prefix="cpu-ps-", dir=helpers.SCRATCH), "power_supply")
        os.makedirs(self.supply)

    def period(self):
        env = dict(os.environ, XDG_RUNTIME_DIR=self.run_dir, ATRIUM_POWER_SUPPLY=self.supply)
        out = subprocess.run(["bash", CPU_USAGE, "period"], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def write(self, name, data):
        with open(os.path.join(self.run_dir, name), "w") as handle:
            json.dump(data, handle)

    def test_a_desktop_is_five_seconds(self):
        self.assertEqual(self.period(), "5")
        os.rmdir(self.supply)                       # no power_supply folder at all
        self.assertEqual(self.period(), "5")

    def test_unplugged_is_fifteen_plugged_in_five(self):
        helpers.fake_power_supply(self.supply, battery={"status": "Discharging"}, ac=False)
        self.assertEqual(self.period(), "15")
        helpers.fake_power_supply(self.supply, battery={"status": "Charging"}, ac=True)
        self.assertEqual(self.period(), "5")
        # some firmware leaves Discharging with the charger in: Mains online wins
        helpers.fake_power_supply(self.supply, battery={"status": "Discharging"}, ac=True)
        self.assertEqual(self.period(), "5")

    def test_a_stale_power_state_file_is_not_believed(self):
        """power-watch.py stopped while unplugged: its file says on_battery,
        sysfs says plugged in -- the pill follows sysfs, as gpu.py does."""
        helpers.fake_power_supply(self.supply, battery={"status": "Charging"}, ac=True)
        self.write("power-state.json", {"has_battery": True, "on_battery": True, "ac_online": False})
        self.assertEqual(self.period(), "5")

    def test_a_mouse_battery_or_an_empty_bay_is_not_the_machine(self):
        helpers.fake_power_supply(self.supply, extra={
            "hidpp_battery_0": {"type": "Battery", "scope": "Device", "status": "Discharging"},
            "BAT1": {"type": "Battery", "present": 0, "status": "Discharging"}})
        self.assertEqual(self.period(), "5")

    def test_the_saver_is_fifteen_too(self):
        helpers.fake_power_supply(self.supply, battery={"status": "Charging"}, ac=True)
        self.write("battery-saver.json", {"active": True, "why": "manual", "since": 1})
        self.assertEqual(self.period(), "15")
        self.write("battery-saver.json", {"active": False, "why": "", "since": 0})
        self.assertEqual(self.period(), "5")

    def test_watch_mode_naps_the_period(self):
        with open(CPU_USAGE) as handle:
            text = handle.read()
        loop = text[text.index("    while :; do"):]
        self.assertIn('period gap\n        nap "$gap"', loop)
        self.assertNotIn("nap 5", loop)


# -- the event-driven daemons' ticks ------------------------------------------------------------
class SmartLayout(unittest.TestCase):
    def test_the_refresh_backs_off(self):
        clock = [100.0]
        t = SL.Tracker(clock=lambda: clock[0], wall=lambda: 1.7e9, store=lambda: None,
                       dispatch=lambda lua: True, exclude=lambda: [])
        t.last_refresh = 100.0
        asked, patch = stub(battery=True)
        with patch, mock.patch.object(t, "refresh") as refresh:
            self.assertAlmostEqual(t.wait(), SL.POLL_BATTERY_S)
            clock[0] += SL.POLL_S
            t.tick(clients=[], monitors=[])
            refresh.assert_not_called()             # 5 s: not yet, on battery
            clock[0] += SL.POLL_BATTERY_S - SL.POLL_S
            t.tick(clients=[], monitors=[])
            refresh.assert_called_once()
        self.assertTrue(all(c == (SL.POLL_S, SL.POLL_BATTERY_S) for c in asked.calls))

    def test_status_says_the_pace(self):
        with mock.patch.object(SL, "read_store", return_value=SL.empty()):
            self.assertEqual(SL.status()["poll_s"], SL.POLL_S)


class FocusGuard(unittest.TestCase):
    def test_outside_a_block_it_backs_off(self):
        daemon = mock.Mock(block=None)
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(FG.tick_s(daemon), FG.TICK_BATTERY_S)
        self.assertEqual(asked.calls, [(FG.TICK_S, FG.TICK_BATTERY_S)])

    def test_a_block_keeps_its_pace(self):
        daemon = mock.Mock(block={"id": "f1", "due": 0})
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(FG.tick_s(daemon), FG.TICK_S)


class Suggest(unittest.TestCase):
    def test_tick_asks_period(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(suggest.tick_s(), suggest.TICK_BATTERY_S)
        self.assertEqual(asked.calls, [(suggest.TICK_S, suggest.TICK_BATTERY_S)])

    def test_an_event_while_locked_pulls_the_tick_in(self):
        d = mock.Mock(locked=True, away_from=None)
        self.assertEqual(suggest.nudge(d, True, 100.0, 140.0, 0.0), (100.0, 100.0))
        # at most every NUDGE_S
        self.assertEqual(suggest.nudge(d, True, 101.0, 140.0, 100.0), (140.0, 100.0))
        d = mock.Mock(locked=False, away_from=50.0)          # back from a suspend, not locked
        self.assertEqual(suggest.nudge(d, True, 100.0, 140.0, 0.0)[0], 100.0)

    def test_no_nudge_while_here_or_without_events(self):
        here = mock.Mock(locked=False, away_from=None)
        self.assertEqual(suggest.nudge(here, True, 100.0, 140.0, 0.0), (140.0, 0.0))
        self.assertEqual(suggest.nudge(here, True, 100.0, 140.0, 0.0, slept=30.0), (140.0, 0.0))
        locked = mock.Mock(locked=True, away_from=None)
        self.assertEqual(suggest.nudge(locked, False, 100.0, 140.0, 0.0), (140.0, 0.0))

    def test_a_suspend_no_tick_saw_still_pulls_the_tick_in(self):
        """The lid: hypridle locked and suspended before any tick saw the
        lock (locked False, away_from None); the first event after the
        resume, with the sleep in slept_offset(), brings the tick now."""
        d = mock.Mock(locked=False, away_from=None)
        self.assertEqual(suggest.nudge(d, True, 100.0, 140.0, 0.0, slept=3600.0), (100.0, 100.0))

    def test_locked_or_away_keeps_the_mains_tick(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(suggest.tick_s(mock.Mock(locked=True, away_from=None)), suggest.TICK_S)
            self.assertEqual(suggest.tick_s(mock.Mock(locked=False, away_from=10.0)), suggest.TICK_S)
            self.assertEqual(suggest.tick_s(mock.Mock(locked=False, away_from=None)), suggest.TICK_BATTERY_S)


class ScreenTime(unittest.TestCase):
    def test_tick_asks_period(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(ST.tick_s(), ST.TICK_BATTERY_S)
        self.assertEqual(asked.calls, [(ST.TICK_S, ST.TICK_BATTERY_S)])

    def test_a_battery_tick_is_never_taken_for_a_suspend(self):
        self.assertLess(ST.TICK_BATTERY_S + 10, ST.MAX_GAP_S)


class Ambient(unittest.TestCase):
    def test_tick_asks_period(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(A.tick_s(), A.TICK_BATTERY_S)
        self.assertEqual(asked.calls, [(A.TICK_S, A.TICK_BATTERY_S)])


class Dock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DOCK_DRY"] = "1"
        # its own copy: test_dock imports dock.py with its scratch settings path
        cls.D = helpers.import_script("dock.py", "dock_backoff")

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("DOCK_DRY", None)

    def test_the_polls_ask_period(self):
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(self.D.language_s(), 60)
            self.assertEqual(self.D.notify_s(), 60)
        self.assertEqual(asked.calls, [(self.D.LANGUAGE_S, self.D.LANGUAGE_BATTERY_S),
                                       (self.D.NOTIFY_S, self.D.NOTIFY_BATTERY_S)])
        self.assertIs(self.D.power_state, ps)


class EmergencyAlerts(unittest.TestCase):
    def test_off_as_shipped_and_the_early_warning_keeps_3_s(self):
        self.assertEqual(ea.DEFAULTS["battery_poll"], "off")
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(ea.poll_gap(3, dict(ea.DEFAULTS)), 3)
        self.assertEqual(asked.calls, [])              # not even asked

    def test_battery_poll_on_slows_the_fast_ones_on_battery(self):
        conf = dict(ea.DEFAULTS, battery_poll="on")
        asked, patch = stub(battery=True)
        with patch:
            self.assertEqual(ea.poll_gap(3, conf), ea.BATTERY_POLL_S)
            self.assertEqual(ea.poll_gap(5, conf), ea.BATTERY_POLL_S)
            self.assertEqual(ea.poll_gap(60, conf), 60)          # the slow ones never change
        self.assertEqual(asked.calls, [(3, 15), (5, 15)])
        asked, patch = stub(battery=False)
        with patch:
            self.assertEqual(ea.poll_gap(3, conf), 3)            # plugged in: as before

    def test_the_poller_sleeps_the_gap(self):
        conf = dict(ea.DEFAULTS, battery_poll="true")
        slept = []

        def sleep(s):
            slept.append(s)
            raise KeyboardInterrupt
        asked, patch = stub(battery=True)
        fake = ("SASMEX", ["MX"], "early warning", 3, True, lambda http, c: [])
        with patch, mock.patch.dict(ea.SOURCES, {"sasmex": fake}), \
                mock.patch.object(ea, "load_state", return_value={}), \
                mock.patch.object(ea, "note_ok"), mock.patch.object(ea.time, "sleep", sleep):
            with self.assertRaises(KeyboardInterrupt):
                ea.poller("sasmex", conf)
        self.assertEqual(slept, [ea.BATTERY_POLL_S])


# -- the serve() loops: the pace reaches the wait ---------------------------------------------
class Stop(BaseException):
    """Ends a serve() loop from a fake select (BaseException: the loops'
    own `except Exception` must not swallow it)."""


class FakeSelect:
    """select.select that records each (fds, timeout) and answers from
    ANSWERS (a list of ready-lists, or a callable(fds, timeout)); past the
    last answer it raises Stop."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def select(self, r, w, x, timeout=None):
        self.calls.append((list(r), timeout))
        if not self.answers:
            raise Stop
        answer = self.answers.pop(0)
        return (answer(r, timeout) if callable(answer) else answer), [], []


class Loops(unittest.TestCase):
    """Each daemon's real loop, run a turn or two with a fake select: the
    timeout it waits is the stubbed period()'s answer, not a constant."""

    def setUp(self):
        import warnings
        self.enterContext(warnings.catch_warnings())     # left last: after the collect below
        warnings.simplefilter("ignore", ResourceWarning)
        saved = {n: signal.getsignal(n) for n in (signal.SIGUSR1, signal.SIGTERM, signal.SIGINT)}

        def restore():
            signal.set_wakeup_fd(-1)
            for n, h in saved.items():
                signal.signal(n, h)
            # the loops' own sockets (their wake pair, the bound control
            # socket) are left open by the Stop: collect them quietly
            import gc
            gc.collect()
        self.addCleanup(restore)

    def test_screentime_waits_its_tick(self):
        fake = FakeSelect()
        asked, patch = stub(battery=True)
        with patch, mock.patch.object(ST, "select", fake), \
                mock.patch.object(ST, "load_conf", return_value=dict(ST.load_conf(), count="on")), \
                mock.patch.object(ST, "connect_events", return_value=None), \
                mock.patch.object(ST, "current_app", return_value=""), mock.patch("builtins.print"):
            with self.assertRaises(Stop):
                ST.serve()
        self.assertEqual(fake.calls[0][1], ST.TICK_BATTERY_S)
        self.assertIn((ST.TICK_S, ST.TICK_BATTERY_S), asked.calls)

    def test_smartlayout_waits_its_refresh(self):
        clock = [100.0]
        t = SL.Tracker(clock=lambda: clock[0], wall=lambda: 1.7e9, store=lambda: None,
                       dispatch=lambda lua: True, exclude=lambda: [])
        t.last_refresh = 100.0
        a, b = __import__("socket").socketpair()
        self.addCleanup(b.close)
        fake = FakeSelect()
        asked, patch = stub(battery=True)
        with patch, mock.patch.object(SL, "select", fake), mock.patch.object(SL, "Tracker", return_value=t), \
                mock.patch.object(t, "refresh"), mock.patch.object(t, "keep_votes"), \
                mock.patch.object(SL, "load_votes", return_value={}), mock.patch.object(SL, "log"), \
                mock.patch.object(SL.sessions, "hypr_dir", return_value=os.path.join(helpers.SCRATCH, "sig")), \
                mock.patch.object(SL.hyprbus, "connect", return_value=a):
            with self.assertRaises(Stop):
                SL.serve()
        self.assertAlmostEqual(fake.calls[0][1], SL.POLL_BATTERY_S)

    def fake_daemon(self, clock, **attrs):
        d = mock.Mock(locked=False, away_from=None, offset=0.0, dwell=None, pending={}, strip=None,
                      values={}, block=None, waiting=False, overlay=None)
        d.clock = lambda: clock[0]
        for k, v in attrs.items():
            setattr(d, k, v)
        return d

    def test_suggest_waits_its_tick_and_the_mains_one_while_locked(self):
        for locked, want in ((False, suggest.TICK_BATTERY_S), (True, suggest.TICK_S)):
            clock = [1000.0]
            d = self.fake_daemon(clock, locked=locked)
            a, b = __import__("socket").socketpair()
            fake = FakeSelect([])           # turn 1: nothing; the tick runs, then the wait
            asked, patch = stub(battery=True)
            with patch, mock.patch.object(suggest, "select", fake), \
                    mock.patch.object(suggest, "Daemon", return_value=d), \
                    mock.patch.object(suggest, "hyprctl_json", return_value=None), \
                    mock.patch.object(suggest, "connect_events", return_value=a), \
                    mock.patch.object(suggest, "log"):
                with self.assertRaises(Stop):
                    suggest.serve()
            a.close()
            b.close()
            d.tick.assert_called_once()
            self.assertAlmostEqual(fake.calls[1][1], want, msg=f"locked={locked}")

    def test_focus_guard_waits_its_tick_and_a_new_block_gets_its_pace_at_once(self):
        clock = [1000.0]
        d = self.fake_daemon(clock, values={"style": "card"})
        d.tick.side_effect = lambda now: setattr(d, "block", {"id": "f1", "due": now + 600})
        a, b = __import__("socket").socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        fake_s = mock.Mock()
        fake_s.connect_events.return_value = a
        fake = FakeSelect([])
        asked, patch = stub(battery=True)
        with patch, mock.patch.object(FG, "select", fake), mock.patch.object(FG, "Daemon", return_value=d), \
                mock.patch.object(FG, "suggest", return_value=fake_s), \
                mock.patch.object(FG, "read_context", return_value=None), \
                mock.patch.object(FG, "watch_on", return_value=False), mock.patch.object(FG, "log"):
            with self.assertRaises(Stop):
                FG.serve()
        # turn 1's tick ran outside a block (15 s on battery), then a block
        # began: turn 2 waits the block's 5 s, not the 15 s already set
        self.assertIn((FG.TICK_S, FG.TICK_BATTERY_S), asked.calls)
        self.assertAlmostEqual(fake.calls[1][1], FG.TICK_S)

    # ambient ------------------------------------------------------------------------------
    class FakeApplier:
        def __init__(self, sound_key=None):
            self.applied, self.errors, self.done = {}, [], []
            self.sound_key = sound_key

        def check_veil(self):
            pass

        def apply(self, *_a, **_k):
            return []

        def reset(self):
            pass

    def run_ambient(self, fake, observe, applier=None, **extra):
        asked, patch = stub(battery=True)
        lives = []
        patches = [patch, mock.patch.object(A, "select", fake),
                   mock.patch.object(A, "read_settings", return_value=dict(A.DEFAULTS, enabled="on")),
                   mock.patch.object(A, "observe", side_effect=observe),
                   mock.patch.object(A, "plan", return_value={"theme": "night"}),
                   mock.patch.object(A, "describe", return_value=[]),
                   mock.patch.object(A, "Applier", return_value=applier or self.FakeApplier()),
                   mock.patch.object(A, "hypr_events", return_value=extra.pop("events", None)),
                   mock.patch.object(A, "write_live", side_effect=lambda d: lives.append(dict(d))),
                   mock.patch.object(A, "log")]
        patches += [mock.patch.object(A, k, v) for k, v in extra.items()]
        for p in patches:
            p.start()
        try:
            with self.assertRaises(Stop):
                A.serve()
        finally:
            for p in reversed(patches):
                p.stop()
        return asked, lives

    def test_ambient_waits_its_tick(self):
        fake = FakeSelect()
        asked, _ = self.run_ambient(fake, [{"gamemode": False}])
        self.assertAlmostEqual(fake.calls[0][1], A.TICK_BATTERY_S, delta=1)
        self.assertIn((A.TICK_S, A.TICK_BATTERY_S), asked.calls)

    def test_ambient_keeps_ambient_json_fresh_through_a_failed_pass(self):
        """theme-schedule.py trusts the pick only while ambient.json is
        fresh: a failed pass still rewrites it (same plan, new time)."""
        _, lives = self.run_ambient(FakeSelect(), [{"gamemode": False}, RuntimeError("makoctl hung"), Stop()],
                                    tick_s=lambda: 0.0)
        self.assertEqual(len(lives), 2)
        self.assertEqual(lives[0]["plan"], lives[1]["plan"])
        self.assertGreaterEqual(lives[1]["time"], lives[0]["time"])

    def test_ambient_heartbeat_when_a_wait_ran_long(self):
        _, lives = self.run_ambient(FakeSelect(), [{"gamemode": False}, Stop()], tick_s=lambda: 0.0,
                                    LIVE_HEARTBEAT_S=-1)
        self.assertEqual(len(lives), 2)             # the pass, then the heartbeat before the next

    def test_ambient_keeps_its_file_watches_when_hyprland_goes(self):
        a, b = __import__("socket").socketpair()
        b.close()                                   # Hyprland went away: recv gives b""
        self.addCleanup(a.close)
        fake = FakeSelect(lambda r, t: [a])
        self.run_ambient(fake, [{"gamemode": False}], events=a)
        first, second = fake.calls[0][0], fake.calls[1][0]
        self.assertIn(a, first)
        self.assertNotIn(a, second)
        self.assertEqual(len(second), len(first) - 1)     # wake pipe and focus watch kept

    def test_ambient_watches_gamemode_only_while_a_soundscape_plays(self):
        fake = FakeSelect()
        self.run_ambient(fake, [{"gamemode": False}], applier=self.FakeApplier())
        quiet = len(fake.calls[0][0])
        fake = FakeSelect()
        self.run_ambient(fake, [{"gamemode": False}], applier=self.FakeApplier(sound_key="rain"))
        self.assertEqual(len(fake.calls[0][0]), quiet + 1)

    def test_a_game_turning_gamemode_on_runs_a_pass_at_once(self):
        """A soundscape plays; gamemode.lua writes hypr-gamemode-auto: the
        hold (the soundscape stops) comes now, not up to 90 s later."""
        import select as real
        flag = os.path.join(A.RUNTIME, "hypr-gamemode-auto")
        self.addCleanup(lambda: os.path.exists(flag) and os.remove(flag))

        def real_wait(r, t):
            with open(flag, "w") as handle:
                handle.write("auto")
            return real.select(r, [], [], 5)[0]
        fake = FakeSelect(real_wait)
        start = time.monotonic()
        observe = [{"gamemode": False}, {"gamemode": True}]
        self.run_ambient(fake, observe, applier=self.FakeApplier(sound_key="rain"))
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(len(fake.calls), 2)        # the first wait ended in a pass, then waited again


class DockTimers(unittest.TestCase):
    """dock.py's polls are GLib timers inside its GTK window, which these
    tests do not build: pin that each timer is armed with the pace helper,
    not the constant, so a refactor cannot drop it unnoticed."""

    def test_the_timers_use_the_pace_helpers(self):
        with open(os.path.join(helpers.SCRIPTS, "dock.py")) as handle:
            text = handle.read()
        self.assertIn('self.ids["language"] = GLib.timeout_add_seconds(language_s(), self.fetch_language)', text)
        self.assertIn('self.ids["badges"] = GLib.timeout_add_seconds(notify_s(), self.fetch_badges)', text)
        self.assertIn('GLib.timeout_add_seconds(notify_s(), self.fetch_notifications)', text)
        for const in ("LANGUAGE_S", "NOTIFY_S"):
            self.assertNotIn(f"timeout_add_seconds({const},", text)


# -- the real power_state: a desktop sees no change ---------------------------------------------
class RealPowerState(unittest.TestCase):
    def setUp(self):
        ps.reset_cache()
        self.addCleanup(ps.reset_cache)

    def paces(self):
        ps.reset_cache()
        return [rg.gpu_every(), tasks.tick_s(), gpu.stream_gap(5.0), suggest.tick_s(), ST.tick_s(),
                A.tick_s(), FG.tick_s(mock.Mock(block=None)),
                ea.poll_gap(3, dict(ea.DEFAULTS, battery_poll="on"))]

    def test_a_desktop_keeps_every_normal_pace(self):
        self.assertEqual(self.paces(), [3, 2, 5.0, 15, 30, 30, 5, 3])

    def test_an_unplugged_laptop_gets_every_battery_pace(self):
        root = helpers.fake_power_supply(tempfile.mkdtemp(prefix="ps-", dir=helpers.SCRATCH),
                                         battery={"status": "Discharging"}, ac=False)
        with mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": root}):
            self.assertEqual(self.paces(), [9, 5, 15.0, 45, 90, 90, 15, 15])
            helpers.fake_power_supply(root, battery={"status": "Charging"}, ac=True)
            self.assertEqual(self.paces(), [3, 2, 5.0, 15, 30, 30, 5, 3])


if __name__ == "__main__":
    unittest.main()
