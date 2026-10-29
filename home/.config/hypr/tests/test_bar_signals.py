"""bar_signals.py, the one table of the bar's signal numbers, against the
waybar configs that use them; and the pure helpers of the bar's push model:
phone.py's D-Bus answers and pill, automount.py's mountinfo fast path and
click plan, clock.py's tick and redraw rules, network.py's /proc parsers,
recording.py's inotify names, wttr.py's retry backoff, audio_panel.py's
pactl event filter, toolbox_awake.py's expiry redraw.

Hermetic: poke() is given a fake /proc and a fake kill; the one real
signal (the HYPR_BAR_SIGNALS_OFF test) goes to this test process itself,
and nothing here starts a process or touches D-Bus."""
import importlib.util
import json
import os
import re
import shutil
import signal
import struct
import sys
import tempfile
import unittest
from datetime import date

import helpers

bs = helpers.import_script("bar_signals.py")
phone = helpers.import_script("phone.py")
automount = helpers.import_script("automount.py")

WAYBAR = os.path.join(os.path.dirname(os.path.dirname(helpers.SCRIPTS)), "waybar")
WAYBAR_SCRIPTS = os.path.join(WAYBAR, "scripts")


def load_waybar(name):
    spec = importlib.util.spec_from_file_location(f"{name}_bs", os.path.join(WAYBAR_SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    if WAYBAR_SCRIPTS not in sys.path:
        sys.path.insert(0, WAYBAR_SCRIPTS)
    spec.loader.exec_module(module)
    return module


def jsonc(text):
    """waybar's JSONC: // comments outside strings, trailing commas."""
    out, i, in_str = [], 0, False
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


class Table(unittest.TestCase):
    def test_configs_agree_with_the_table(self):
        by_module = {}
        for name, (number, bar, modules, _who) in bs.SIGNALS.items():
            for module in modules:
                by_module.setdefault(module, set()).add((number, bar))
        for filename, bar in (("config", "main"), ("config-toolbox", "toolbox")):
            with open(os.path.join(WAYBAR, filename)) as handle:
                bars = jsonc(handle.read())
            for module, conf in bars[0].items():
                if isinstance(conf, dict) and "signal" in conf:
                    self.assertIn((conf["signal"], bar), by_module.get(module, set()),
                                  f"{filename}: {module} has signal {conf['signal']}, not in bar_signals.py")

    def test_one_number_one_set_of_modules(self):
        seen = {}
        for name, (number, bar, modules, _who) in bs.SIGNALS.items():
            self.assertTrue(bs.LOWEST <= number <= bs.HIGHEST, name)
            self.assertEqual(seen.setdefault(number, (bar, modules)), (bar, modules), name)

    def test_free_numbers(self):
        free = bs.free_numbers()
        self.assertNotIn(20, free)
        self.assertIn(23, free)
        self.assertEqual(bs.signal_number("logo"), bs.signal_number("day"))
        with self.assertRaises(KeyError):
            bs.signal_number("nope")


class Poke(unittest.TestCase):
    def setUp(self):
        self.proc = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.proc, True)

    def fake(self, pid, comm, cmdline, caught):
        folder = os.path.join(self.proc, str(pid))
        os.makedirs(folder)
        with open(os.path.join(folder, "comm"), "w") as handle:
            handle.write(comm + "\n")
        with open(os.path.join(folder, "cmdline"), "wb") as handle:
            handle.write(cmdline.replace(" ", "\0").encode() + b"\0")
        mask = 0
        for signum in caught:
            mask |= 1 << (signum - 1)
        with open(os.path.join(folder, "status"), "w") as handle:
            handle.write(f"Name:\t{comm}\nSigCgt:\t{mask:016x}\n")

    def test_signals_only_the_right_bar_and_only_a_ready_one(self):
        rt = signal.SIGRTMIN
        self.fake(100, "waybar", "/usr/bin/waybar", [rt + 20, rt + 11])
        self.fake(200, "waybar", "/usr/bin/waybar -c /x/config-toolbox", [rt + 11, rt + 21])
        self.fake(300, "waybar", "/usr/bin/waybar", [])          # still starting: no handlers
        self.fake(400, "python3", "python3 waybar", [rt + 20])
        sent = []
        n = bs.poke("phone", "nightlight", proc=self.proc, kill=lambda pid, sig: sent.append((pid, sig)))
        self.assertEqual(sorted(sent), [(100, rt + 20), (200, rt + 11)])
        self.assertEqual(n, 2)

    def test_off_switch_spares_the_live_bar(self):
        """HYPR_BAR_SIGNALS_OFF=1: the real os.kill is never reached. The
        "waybar" in the fake /proc is this test process itself, with a
        handler of its own, so even a failure signals nothing else."""
        signum = signal.SIGRTMIN + 20
        got = []
        old_handler = signal.signal(signum, lambda *_: got.append(1))
        self.addCleanup(signal.signal, signum, old_handler)
        self.fake(os.getpid(), "waybar", "/usr/bin/waybar", [signum])
        old = os.environ.get("HYPR_BAR_SIGNALS_OFF")
        self.addCleanup(lambda: os.environ.pop("HYPR_BAR_SIGNALS_OFF", None) if old is None
                        else os.environ.__setitem__("HYPR_BAR_SIGNALS_OFF", old))
        os.environ["HYPR_BAR_SIGNALS_OFF"] = "1"
        self.assertEqual(bs.poke("phone", proc=self.proc), 0)
        self.assertEqual(got, [])
        # A kill passed in is used regardless (the other tests' fakes).
        self.assertEqual(bs.poke("phone", proc=self.proc, kill=lambda p, s: None), 1)
        os.environ["HYPR_BAR_SIGNALS_OFF"] = "0"
        self.assertEqual(bs.poke("phone", proc=self.proc), 1)
        self.assertEqual(got, [1])

    def test_number_cli_takes_several(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            bs.main(["number", "toolbox", "awake", "nightlight"])
        self.assertEqual(out.getvalue().split(), ["12", "21", "11"])

    def test_catches(self):
        self.assertTrue(bs.catches("SigCgt:\t0000000000000200\n", 10))
        self.assertFalse(bs.catches("SigCgt:\t0000000000000200\n", 11))
        self.assertFalse(bs.catches("Name: x\n", 10))


class Phone(unittest.TestCase):
    def test_battery_reading(self):
        self.assertEqual(phone.battery_reading({"charge": {"type": "i", "data": 81},
                                                "isCharging": {"type": "b", "data": True}}), (81, True))
        self.assertEqual(phone.battery_reading({"charge": {"type": "i", "data": -1}}), (None, False))
        self.assertEqual(phone.battery_reading(None), (None, False))

    def test_pill(self):
        self.assertEqual(phone.bar_json(None, None, False)["text"], "")
        got = phone.bar_json({"id": "a", "name": "Pixel"}, 15, False)
        self.assertEqual(got["class"], "low")
        self.assertIn("15%", got["text"])
        self.assertIn("Middle-click: ring it", got["tooltip"])
        self.assertNotIn("Click: ring", got["tooltip"])
        self.assertEqual(phone.bar_json({"id": "a", "name": "P"}, None, True)["class"], "charging")

    def test_device_names_from_busctl(self):
        calls = []

        def fake_run(*args, timeout=10):
            calls.append(args)
            return json.dumps({"type": "a{ss}", "data": [{"abc": "Pixel"}]})
        saved = phone.run
        phone.run = fake_run
        try:
            self.assertEqual(phone.phone(autostart=False), {"id": "abc", "name": "Pixel", "reachable": True})
        finally:
            phone.run = saved
        self.assertIn("--auto-start=no", calls[0])
        self.assertEqual(calls[0][-3:], ("bb", "true", "true"))


class Drives(unittest.TestCase):
    INFO = ("36 25 8:17 / /run/media/me/MY\\040STICK rw - vfat /dev/sdb1 rw\n"
            "37 25 8:33 / /run/media/me/Backup rw - ext4 /dev/sdc1 rw\n"
            "1 0 8:1 / / rw - btrfs /dev/nvme0n1p2 rw\n"
            "2 1 0:5 / /run/media/other/X rw - vfat /dev/sdd1 rw\n")

    def test_media_mounts(self):
        self.assertEqual(automount.media_mounts(self.INFO, "/run/media/me"),
                         ["/run/media/me/MY STICK", "/run/media/me/Backup"])
        self.assertEqual(automount.media_mounts("1 0 8:1 / / rw - btrfs x rw\n", "/run/media/me"), [])
        # The shared home (/media) is its own prefix; /run/media is not in it.
        self.assertEqual(automount.media_mounts(self.INFO, "/media"), [])
        self.assertEqual(automount.media_mounts("5 1 8:1 / /media/STICK rw - vfat x rw\n", "/media"),
                         ["/media/STICK"])

    def test_click_plan_never_ejects_everything(self):
        one = [{"mount": "/run/media/me/A", "label": "A"}]
        two = one + [{"mount": "/run/media/me/B", "label": "B"}]
        self.assertEqual(automount.click_plan(one, "left"), ("open", "/run/media/me/A"))
        self.assertEqual(automount.click_plan(one, "right"), ("eject", "/run/media/me/A"))
        self.assertEqual(automount.click_plan(two, "right"), ("open", "/run/media/me"))
        self.assertEqual(automount.click_plan([], "right"), ("none", ""))

    def test_bar_without_gi(self):
        self.assertEqual(automount.bar_json([]), {"text": "", "class": "none"})
        self.assertIn("eject it", automount.bar_json([{"mount": "/m/A", "label": "A"}])["tooltip"])


class Clock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clock = load_waybar("clock")

    def test_tick_step(self):
        c = self.clock
        self.assertEqual(c.tick_step("local", {"seconds": "on"}, {}), 1)
        self.assertEqual(c.tick_step("local", {"seconds": "off"}, {}), 60)
        self.assertEqual(c.tick_step("epoch", {"seconds": "off"}, {}), 1)
        self.assertEqual(c.tick_step("local", {"seconds": "on"}, {"clock": "menubar"}), 60)

    def test_sleep_for(self):
        c = self.clock
        self.assertAlmostEqual(c.sleep_for(100.25, 1), 0.755)
        self.assertEqual(c.sleep_for(120.0, 60), c.MAX_SLEEP)     # capped
        self.assertAlmostEqual(c.sleep_for(178.0, 60), 2.005)

    def test_due_signals(self):
        c = self.clock
        d1, d2 = date(2026, 10, 27), date(2026, 10, 28)
        self.assertFalse(c.due_signals(None, (d1, "23:59"), True))
        self.assertTrue(c.due_signals((d1, "23:59"), (d2, "00:00"), False))
        self.assertFalse(c.due_signals((d1, "10:00"), (d1, "10:01"), False))
        self.assertTrue(c.due_signals((d1, "10:00"), (d1, "10:01"), True))
        self.assertFalse(c.due_signals((d1, "10:00"), (d1, "10:00"), True))

    def test_no_tooltip_built(self):
        got = self.clock.reading("clock", {})
        self.assertEqual(set(got), {"text", "class"})


class Network(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.net = load_waybar("network")

    def test_route_table(self):
        text = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                "wlp6s0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
                "enp7s0\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
                "enp7s0\t0000A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n")
        self.assertEqual(self.net.parse_route_table(text), ("enp7s0", "192.168.0.1"))
        self.assertEqual(self.net.parse_route_table("Iface\n"), (None, None))

    def test_ipv6_default(self):
        line = ("00000000000000000000000000000000 00 00000000000000000000000000000000 00 "
                "fe800000000000000000000000000001 00000400 00000001 00000000 00000003 enp7s0\n")
        self.assertEqual(self.net.parse_ipv6_default(line), "enp7s0")

    def test_pill(self):
        net = self.net
        self.assertEqual(net.pill(None, "")["class"], "disconnected")
        self.assertEqual(net.pill("enp7s0", "10.0.0.2/24")["text"], "10.0.0.2/24 \U0001f310")
        self.assertIn("(96%)", net.pill("wlp6s0", "", "-52 dBm", wifi=True)["text"])
        self.assertNotIn("tooltip", net.pill("enp7s0", "10.0.0.2/24"))

    def test_back_online(self):
        net = self.net
        self.assertTrue(net.back_online({"class": "disconnected"}, {"class": "connected"}))
        self.assertFalse(net.back_online(None, {"class": "connected"}))
        self.assertFalse(net.back_online({"class": "connected"}, {"class": "connected"}))


class Recording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rec = load_waybar("recording")

    def test_event_names(self):
        H = self.rec.PidFiles.HEADER
        data = H.pack(1, 0x100, 0, 16) + b"gsr-record.pid\0\0" + H.pack(1, 0x200, 0, 0)
        self.assertEqual(self.rec.PidFiles.names(data), ["gsr-record.pid", ""])

    def test_wait_wakes_on_a_pid_file(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, folder, True)
        files = self.rec.PidFiles(folder)
        if files.fd < 0:
            self.skipTest("no inotify here")
        open(os.path.join(folder, "unrelated"), "w").close()
        self.assertFalse(files.wait(0.1))
        open(os.path.join(folder, "gsr-replay.pid"), "w").close()
        self.assertTrue(files.wait(1.0))

    def test_fresh_pid_file_rechecks_soon(self):
        """A pid file written a moment ago may name a recorder that has not
        exec'd yet: re-read in FRESH_TICK, not after the idle minute."""
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, folder, True)
        rec = self.rec
        self.assertEqual(rec.next_wait(60.0, run=folder), 60.0)
        path = os.path.join(folder, "gsr-record.pid")
        open(path, "w").close()
        now = os.stat(path).st_mtime
        self.assertEqual(rec.next_wait(60.0, now + 1, folder), rec.FRESH_TICK)
        self.assertEqual(rec.next_wait(0.1, now + 1, folder), 0.1)
        self.assertEqual(rec.next_wait(60.0, now + rec.FRESH_S + 1, folder), 60.0)
        open(os.path.join(folder, "unrelated.pid"), "w").close()
        self.assertEqual(rec.next_wait(5.0, now + rec.FRESH_S + 1, folder), 5.0)

    def test_no_tooltips(self):
        self.assertEqual(set(self.rec.status()), {"text", "class"})
        self.assertEqual(set(self.rec.capture_status()), {"text", "class"})


class Weather(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wttr = load_waybar("wttr")

    def test_backoff(self):
        w = self.wttr
        self.assertEqual([w.retry_after(n) for n in (1, 2, 3, 9)], [60, 120, 300, 300])

    def test_fail_count(self):
        w = self.wttr
        saved = w.FAILS
        w.FAILS = os.path.join(helpers.SCRATCH, "weather.fails")
        try:
            self.assertEqual(w.failures(), 0)
            self.assertEqual(w.failures("+1"), 1)
            self.assertEqual(w.failures("+1"), 2)
            self.assertEqual(w.failures("reset"), 0)
            self.assertFalse(os.path.exists(w.FAILS))
        finally:
            w.FAILS = saved


class AudioEvents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ap = load_waybar("audio_panel")
        except Exception as exc:     # no GTK / panelui here
            raise unittest.SkipTest(f"audio_panel not importable: {exc}")

    def test_classify(self):
        c = self.ap.classify
        self.assertEqual(c("Event 'change' on sink #56"), "levels")
        self.assertEqual(c("Event 'change' on source #57"), "levels")
        self.assertEqual(c("Event 'new' on sink #90"), "devices")
        self.assertEqual(c("Event 'change' on server #0"), "devices")
        self.assertEqual(c("Event 'change' on card #40"), "devices")
        self.assertIsNone(c("Event 'change' on sink-input #120"))
        self.assertIsNone(c("Event 'new' on client #300"))

    def test_fire_survives_a_missing_wpctl(self):
        saved = self.ap.subprocess.Popen

        def boom(*_a, **_k):
            raise FileNotFoundError("wpctl")
        self.ap.subprocess.Popen = boom
        try:
            self.ap.fire("set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")      # no exception
        finally:
            self.ap.subprocess.Popen = saved


class AwakeExpiry(unittest.TestCase):
    def test_redraw_delay(self):
        aw = load_waybar("toolbox_awake")
        self.assertEqual(aw.redraw_delay(1000.0, 400.0), 602)
        self.assertIsNone(aw.redraw_delay(None, 400.0))
        self.assertIsNone(aw.redraw_delay(300.0, 400.0))


if __name__ == "__main__":
    unittest.main()
