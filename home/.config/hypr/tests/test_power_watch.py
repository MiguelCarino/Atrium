"""power-watch.py: the udevadm line parser and the non-blocking reader (fed
from a real pipe, a stand-in child printing udevadm's lines), plugged(),
the warn_at crossings, the notification text, and Watch.check() deciding
the plugged / unplugged / battery-low events, one warning per percentage
per discharge (critical at the lowest), the reset on plugging in, the
restart that does not warn again, power-state.json and the battery-saver
run -- plus serve()'s debounce / settle / fallback timing with a fake clock.

Hermetic: a fake power_supply tree per test (helpers.fake_power_supply),
every command goes to a recorder instead of being started, and the
battery-saver path is a scratch file. Nothing reaches automations, mako or
udev."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

import helpers

ps = helpers.import_script("power_state.py", "power_state")
pw = helpers.import_script("power-watch.py")

HEADER = ["monitor will print the received events for:",
          "UDEV - the event which udev sends out after rule processing", ""]


def uevent(name, action="change", stamp="12345.678901"):
    return (f"UDEV  [{stamp}] {action:<8} /devices/LNXSYSTM:00/LNXSYBUS:00/PNP0C0A:00/"
            f"power_supply/{name} (power_supply)")


class Recorder:
    """Stands in for subprocess.Popen: records (argv, env), finishes at once."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append((list(argv), env))
        return self

    def poll(self):
        return 0

    def events(self):
        return [(a[3], (e or {}).get("AUTOMATION_PERCENT")) for a, e in self.calls
                if len(a) > 3 and a[1].endswith("automations.py") and a[2] == "event"]

    def notifications(self):
        return [a for a, _ in self.calls if a[0].endswith("notify")]

    def savers(self):
        return [a for a, _ in self.calls if len(a) > 2 and a[1].endswith("battery-saver.py")]

    def clear(self):
        self.calls.clear()


class Parse(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(pw.parse_uevent(uevent("BATT")), "BATT")
        self.assertEqual(pw.parse_uevent(uevent("ACAD", "add")), "ACAD")
        self.assertEqual(pw.parse_uevent(uevent("ucsi-source-psy-USBC000:001")), "ucsi-source-psy-USBC000:001")
        for line in HEADER + ["KERNEL[1.0] change /devices/x/power_supply/BATT (power_supply)",
                              "UDEV  [1.0] change   /devices/x/input/event3 (input)",
                              "UDEV  [1.0] change   /devices/x/BATT (power_supply)",
                              "garbage", "   "]:
            self.assertIsNone(pw.parse_uevent(line), line)


class MonitorPipe(unittest.TestCase):
    """The reader against a real child on a real pipe."""

    def run_child(self, script):
        mon = pw.Monitor([sys.executable, "-c", script])
        mon.start()
        self.assertIsNotNone(mon.proc)
        lines, deadline = [], time.monotonic() + 5
        while mon.proc and time.monotonic() < deadline:
            import select
            ready, _, _ = select.select([mon], [], [], 1)
            if ready:
                lines += mon.read()
        mon.stop()
        return mon, lines

    def test_lines_and_partial_lines(self):
        script = ("import sys,time\n"
                  f"sys.stdout.write({chr(10).join(HEADER)!r} + '\\n'); sys.stdout.flush()\n"
                  f"line = {uevent('BATT')!r}\n"
                  "sys.stdout.write(line[:20]); sys.stdout.flush(); time.sleep(0.2)\n"
                  "sys.stdout.write(line[20:] + '\\n'); sys.stdout.flush()\n"
                  f"print({uevent('ACAD')!r}, flush=True)\n")
        mon, lines = self.run_child(script)
        names = [n for n in map(pw.parse_uevent, lines) if n]
        self.assertEqual(names, ["BATT", "ACAD"])
        self.assertIsNone(mon.proc)                 # it ended: stopped
        self.assertGreater(mon.retry_at, 0)         # ...and to be restarted later

    def test_restart_waits(self):
        clock = [100.0]
        mon = pw.Monitor([sys.executable, "-c", "pass"], clock=lambda: clock[0])
        mon.start()
        mon.proc.wait()
        while mon.proc:
            mon.read()
        self.assertEqual(mon.retry_at, 100.0 + pw.RESTART_S)
        mon.start()
        self.assertIsNone(mon.proc)                 # too soon
        clock[0] += pw.RESTART_S
        mon.start()
        self.assertIsNotNone(mon.proc)
        mon.stop()

    def test_missing_program(self):
        mon = pw.Monitor(["/nonexistent/udevadm"])
        with mock.patch.object(pw, "log"):
            mon.start()
        self.assertIsNone(mon.proc)
        self.assertEqual(mon.read(), [])

    def test_os_pipe_buffering(self):
        """read() keeps a half line until its newline arrives."""
        r, w = os.pipe()
        os.set_blocking(r, False)
        mon = pw.Monitor()
        mon.proc = mock.Mock(stdout=mock.Mock(fileno=lambda: r))
        self.assertEqual(mon.read(), [])            # nothing yet: BlockingIOError
        os.write(w, uevent("BATT")[:30].encode())
        self.assertEqual(mon.read(), [])
        os.write(w, (uevent("BATT")[30:] + "\n" + uevent("ACAD")[:5]).encode())
        self.assertEqual(mon.read(), [uevent("BATT")])
        os.write(w, (uevent("ACAD")[5:] + "\n").encode())
        self.assertEqual(mon.read(), [uevent("ACAD")])
        os.close(w)
        os.close(r)


class Pure(unittest.TestCase):
    def test_crossed(self):
        self.assertEqual(pw.crossed(25, [20, 10, 5], set()), [])
        self.assertEqual(pw.crossed(20, [20, 10, 5], set()), [20])
        self.assertEqual(pw.crossed(15, [20, 10, 5], {20}), [])
        self.assertEqual(pw.crossed(4, [20, 10, 5], {20}), [10, 5])
        self.assertEqual(pw.crossed(4, [], set()), [])

    def test_plugged(self):
        self.assertTrue(pw.plugged({"ac_online": True, "battery": {"status": "Discharging"}}))
        self.assertFalse(pw.plugged({"ac_online": False, "battery": None}))
        self.assertFalse(pw.plugged({"ac_online": None, "battery": {"status": "Discharging"}}))
        self.assertTrue(pw.plugged({"ac_online": None, "battery": {"status": "Not charging"}}))
        self.assertIsNone(pw.plugged({"ac_online": None, "battery": {"status": "Unknown"}}))
        self.assertIsNone(pw.plugged({"ac_online": None, "battery": None}))

    def test_duration_and_text(self):
        self.assertEqual(pw.duration(45), "45 min")
        self.assertEqual(pw.duration(125), "2 h 5 min")
        self.assertEqual(pw.duration(120), "2 h")
        title, body = pw.warning(9, 25, False)
        self.assertEqual(title, "Battery low: 9%")
        self.assertIn("About 25 min left", body)
        self.assertIn("soon", body)
        _, body = pw.warning(4, None, True)
        self.assertNotIn("left", body)
        self.assertIn("now", body)


class WatchBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pw-", dir=helpers.SCRATCH)
        self.root = os.path.join(self.dir, "power_supply")
        self.saver = os.path.join(self.dir, "battery-saver.py")
        with open(self.saver, "w") as handle:
            handle.write("# stand-in\n")
        self.rec = Recorder()
        for path in (ps.POWER_STATE, ps.SETTINGS_FILE):
            try:
                os.remove(path)
            except OSError:
                pass
        self.watch = self.new_watch()

    def new_watch(self):
        return pw.Watch(spawn=self.rec, root=self.root, saver=self.saver, now=lambda: 1700000000)

    def tree(self, **kw):
        helpers.fake_power_supply(self.root, **kw)

    def state(self):
        with open(ps.POWER_STATE) as handle:
            return json.load(handle)


class Transitions(WatchBase):
    def test_startup_is_not_an_event(self):
        self.tree(battery={"status": "Discharging", "capacity": 80}, ac=False)
        self.assertEqual(self.watch.check(), ["battery-saver auto"])
        self.assertEqual(self.rec.events(), [])

    def test_unplug_and_plug(self):
        self.tree(battery={"status": "Charging", "capacity": 80}, ac=True)
        self.watch.check()
        self.rec.clear()
        self.tree(battery={"status": "Discharging"}, ac=False)
        self.assertEqual(self.watch.check(), ["power-unplugged", "battery-saver auto"])
        self.assertEqual(self.rec.events(), [("power-unplugged", None)])
        self.rec.clear()
        self.tree(battery={"status": "Charging"}, ac=True)
        self.watch.check()
        self.assertEqual(self.rec.events(), [("power-plugged", None)])

    def test_charger_first_then_status(self):
        """ACAD goes offline before BATT says Discharging: one event, from the charger."""
        self.tree(battery={"status": "Not charging", "capacity": 80}, ac=True)
        self.watch.check()
        self.tree(ac=False)
        self.watch.check()
        self.tree(battery={"status": "Discharging"})
        self.watch.check()
        self.assertEqual(self.rec.events(), [("power-unplugged", None)])

    def test_no_change_no_saver_run(self):
        self.tree(battery={"status": "Discharging", "capacity": 80}, ac=False)
        self.watch.check()
        self.rec.clear()
        self.tree(battery={"current_now": 1200000})      # only the watts moved
        self.assertEqual(self.watch.check(), [])
        self.assertEqual(self.rec.savers(), [])
        self.tree(battery={"capacity": 79})
        self.assertEqual(self.watch.check(), ["battery-saver auto"])

    def test_no_saver_script(self):
        os.remove(self.saver)
        self.tree(battery={"status": "Discharging", "capacity": 80}, ac=False)
        self.assertEqual(self.watch.check(), [])
        self.assertEqual(self.rec.calls, [])

    def test_saver_argv(self):
        self.tree(battery={"status": "Discharging", "capacity": 80}, ac=False)
        self.watch.check()
        self.assertEqual(self.rec.savers(), [[sys.executable, self.saver, "auto"]])


class Desktop(WatchBase):
    def test_desktop_does_nothing(self):
        """No supplies at all: one state file saying so, nothing started, ever."""
        os.remove(self.saver)
        self.assertEqual(self.watch.check(), [])
        self.assertEqual(self.watch.check(), [])
        self.assertEqual(self.rec.calls, [])
        st = self.state()
        self.assertEqual((st["has_battery"], st["on_battery"], st["ac_online"], st["battery"]),
                         (False, False, None, None))
        self.assertEqual(self.watch.poll_s(), pw.IDLE_POLL_S)

    def test_desktop_with_mouse(self):
        self.tree(extra={"hidpp_battery_0": {"type": "Battery", "scope": "Device",
                                             "status": "Discharging", "capacity": 3}})
        self.watch.check()
        self.assertEqual(self.rec.events(), [])
        self.assertEqual(self.rec.notifications(), [])

    def test_laptop_polls_every_minute(self):
        self.tree(battery={"status": "Charging"}, ac=True)
        self.watch.check()
        self.assertEqual(self.watch.poll_s(), pw.POLL_S)


class Warnings(WatchBase):
    def drain(self, *levels):
        out = []
        for level in levels:
            self.tree(battery={"status": "Discharging", "capacity": level}, ac=False)
            out.append(self.watch.check())
        return out

    def test_each_threshold_once(self):
        self.drain(30, 21, 20, 19, 18, 11, 10, 9, 6, 5, 4, 3)
        self.assertEqual(self.rec.events(), [("battery-low", "20"), ("battery-low", "10"), ("battery-low", "5")])
        notes = self.rec.notifications()
        self.assertEqual(len(notes), 3)
        self.assertEqual([n[n.index("-u") + 1] for n in notes], ["normal", "normal", "critical"])
        self.assertIn("--mood", notes[2])
        self.assertEqual(notes[0][-2], "Battery low: 20%")
        self.assertEqual(self.state()["warned"], [20, 10, 5])

    def test_time_left_in_notification(self):
        self.tree(battery={"status": "Discharging", "capacity": 10, "charge_now": 300000,
                           "current_now": 900000}, ac=False)
        self.watch.check()
        self.assertIn("About 20 min left", self.rec.notifications()[0][-1])

    def test_unplug_below_thresholds_warns_once(self):
        self.tree(battery={"status": "Charging", "capacity": 8}, ac=True)
        self.watch.check()
        self.tree(battery={"status": "Discharging"}, ac=False)
        self.watch.check()
        self.assertEqual(self.rec.events(), [("power-unplugged", None), ("battery-low", "10")])
        self.assertEqual(len(self.rec.notifications()), 1)
        self.drain(7, 6, 5)
        self.assertEqual(self.rec.events()[-1], ("battery-low", "5"))
        self.assertEqual(len(self.rec.notifications()), 2)

    def test_plugging_in_resets(self):
        self.drain(20)
        self.tree(battery={"status": "Charging", "capacity": 21}, ac=True)
        self.watch.check()
        self.assertEqual(self.watch.warned, set())
        self.drain(20)
        self.assertEqual([e for e in self.rec.events() if e[0] == "battery-low"],
                         [("battery-low", "20"), ("battery-low", "20")])

    def test_no_warnings_while_charging(self):
        self.tree(battery={"status": "Charging", "capacity": 3}, ac=True)
        self.watch.check()
        self.assertEqual(self.rec.notifications(), [])

    def test_custom_thresholds(self):
        ps.save_settings({"warn_at": [50, 15]})
        self.drain(60, 50, 16, 15)
        self.assertEqual(self.rec.events(), [("battery-low", "50"), ("battery-low", "15")])
        crit = [n[n.index("-u") + 1] for n in self.rec.notifications()]
        self.assertEqual(crit, ["normal", "critical"])

    def test_no_thresholds(self):
        ps.save_settings({"warn_at": []})
        self.drain(30, 5, 1)
        self.assertEqual(self.rec.notifications(), [])

    def test_env_carries_percent(self):
        self.drain(20)
        (argv, env), = [c for c in self.rec.calls if c[0][-1:] == ["battery-low"]]
        self.assertEqual(argv[:3], [sys.executable, pw.AUTOMATIONS, "event"])
        self.assertEqual(env["AUTOMATION_PERCENT"], "20")
        self.assertIn("PATH", env)                  # the session's environment, plus the fact

    def test_restart_does_not_warn_again(self):
        self.drain(19)
        self.watch = self.new_watch()
        self.watch.restore()
        self.rec.clear()
        self.drain(18)
        self.assertEqual(self.rec.notifications(), [])
        self.drain(10)
        self.assertEqual(self.rec.events(), [("battery-low", "10")])

    def test_restart_after_plugging_in_starts_fresh(self):
        self.drain(19)
        self.tree(battery={"status": "Charging"}, ac=True)
        self.watch.check()
        self.watch = self.new_watch()
        self.watch.restore()
        self.assertEqual(self.watch.warned, set())

    def test_state_file(self):
        self.drain(42)
        st = self.state()
        self.assertTrue(st["on_battery"])
        self.assertFalse(st["ac_online"])
        self.assertEqual(st["battery"]["capacity"], 42)
        self.assertEqual(st["updated"], 1700000000)
        self.assertEqual(st["warned"], [])

    def test_spawn_failure_is_logged_not_raised(self):
        def broken(argv, env=None):
            raise OSError("no python")
        self.watch.spawn = broken
        with mock.patch.object(pw, "log") as log:
            self.drain(5)
        self.assertTrue(log.called)


class Serve(WatchBase):
    """serve() with a fake clock and a fake select."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pw, "log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_loop(self, script, until):
        """SCRIPT: [(at, [lines])] uevent bursts. Returns the clock times of the checks."""
        clock = [0.0]
        checks = []
        real_check = self.watch.check

        def check():
            checks.append(round(clock[0], 2))
            return real_check()
        self.watch.check = check
        mon = mock.Mock(proc=True, retry_at=0.0)
        pending = list(script)
        mon.read = lambda: pending.pop(0)[1] if pending and pending[0][0] <= clock[0] + 1e-9 else []

        def wait(fds, w, x, timeout):
            nxt = pending[0][0] if pending else float("inf")
            if nxt <= clock[0] + timeout:
                clock[0] = max(clock[0], nxt)
                return [mon], [], []
            clock[0] = min(clock[0] + timeout, until)    # the loop ends at UNTIL, not past it
            return [], [], []
        pw.serve(self.watch, mon, clock=lambda: clock[0], wait=wait, running=lambda: clock[0] < until)
        return checks

    def test_burst_is_one_check_then_settle(self):
        self.tree(battery={"status": "Charging"}, ac=True)
        checks = self.run_loop([(10.0, [uevent("ACAD")]), (10.1, [uevent("BATT")]),
                                (10.2, [uevent("ucsi-source-psy-USBC000:001")])], until=20)
        self.assertEqual(checks, [0.0, 10.0 + pw.DEBOUNCE_S, 10.0 + pw.DEBOUNCE_S + pw.SETTLE_S])

    def test_header_lines_do_not_check(self):
        self.tree(battery={"status": "Charging"}, ac=True)
        checks = self.run_loop([(1.0, HEADER)], until=30)
        self.assertEqual(checks, [0.0])

    def test_fallback_poll(self):
        self.tree(battery={"status": "Discharging"}, ac=False)
        checks = self.run_loop([], until=pw.POLL_S * 3 + 1)
        self.assertEqual(checks, [0.0, pw.POLL_S, pw.POLL_S * 2, pw.POLL_S * 3])

    def test_desktop_sleeps_long(self):
        os.remove(self.saver)
        checks = self.run_loop([], until=pw.IDLE_POLL_S + 1)
        self.assertEqual(checks, [0.0, pw.IDLE_POLL_S])

    def test_unplug_through_the_loop(self):
        """A uevent at 5 s whose burst unplugged the charger: one event."""
        self.tree(battery={"status": "Charging", "capacity": 50}, ac=True)
        clock, fired = [0.0], []
        mon = mock.Mock(proc=True, retry_at=0.0)

        def wait(fds, w, x, timeout):
            if not fired and clock[0] + timeout >= 5.0:
                clock[0] = 5.0
                fired.append(1)
                self.tree(battery={"status": "Discharging"}, ac=False)
                return [mon], [], []
            clock[0] += timeout
            return [], [], []
        mon.read = lambda: [uevent("ACAD")]
        pw.serve(self.watch, mon, clock=lambda: clock[0], wait=wait, running=lambda: clock[0] < 10)
        self.assertEqual(self.rec.events(), [("power-unplugged", None)])


class StatusCli(WatchBase):
    def test_status_json(self):
        self.tree(battery={"status": "Discharging", "capacity": 19}, ac=False)
        self.watch.check()
        with mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": self.root}):
            out = pw.status()
        json.dumps(out)
        self.assertTrue(out["on_battery"])
        self.assertFalse(out["plugged"])
        self.assertEqual(out["battery"]["capacity"], 19)
        self.assertEqual(out["warned"], [20])
        self.assertEqual(out["daemon"]["warned"], [20])
        self.assertEqual(out["settings"], ps.load_settings())
        self.assertIn("frugal", out)
        self.assertIn("saver_active", out)
        ps.reset_cache()

    def test_status_desktop_subprocess(self):
        """The real CLI, as a child (it inherits helpers.py's scratch env)."""
        import subprocess
        out = subprocess.run([sys.executable, os.path.join(helpers.SCRIPTS, "power-watch.py"), "status"],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertFalse(data["has_battery"])
        self.assertFalse(data["on_battery"])
        self.assertIsNone(data["battery"])

    def test_usage(self):
        with mock.patch("builtins.print"):
            self.assertEqual(pw.main([]), 2)


class Unit(unittest.TestCase):
    def test_service_and_enabled(self):
        conf = os.path.dirname(os.path.dirname(helpers.SCRIPTS))
        with open(os.path.join(conf, "systemd", "user", "power-watch.service")) as handle:
            text = handle.read()
        self.assertIn("power-watch.py daemon", text)
        self.assertIn("WantedBy=graphical-session.target", text)
        units = os.path.join(os.path.dirname(os.path.dirname(conf)), "packages", "units.txt")
        with open(units) as handle:
            self.assertIn("power-watch.service", handle.read().split())


if __name__ == "__main__":
    unittest.main()
