"""The laptop panel's brightness through its kernel backlight: backlight.py
(which screen, the curve, the writers), screen-color.py's brightness / dim /
migration / status / matrices for a backlit screen, and osd.py's read-back.

Everything runs on a fake sysfs tree in the scratch folder: a DRM folder
with card1-eDP-1 (backlit) and card1-DP-1 (an external monitor), and a
backlight folder with amdgpu_bl1 whose device link points at the eDP
connector, as on the real machine. HYPR_DRM_DIR / HYPR_BACKLIGHT_DIR point
there for each test and back afterwards (helpers.py leaves HYPR_DRM_DIR at
a folder that is not there, so every other test sees a desktop). The fake
`brightness` file is writable, so the writes land in it without a process;
subprocess.run is made to fail the test should anything try to fork
busctl or brightnessctl anyway (except where a test hands in its own run=,
or makes the panel unwritable on purpose: a read-only brightness file and a
run that fails, which is logind refusing with no brightnessctl).
"""
import json
import os
import shutil
import struct
import tempfile
import time
import unittest
from unittest import mock

import helpers

import backlight

sc = helpers.import_script("screen-color.py")
osd = helpers.import_script("osd.py")

MAX = 65535


def put(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(f"{value}\n")


class Tree:
    """A fake /sys/class/drm + /sys/class/backlight."""

    def __init__(self, connectors=("eDP-1", "DP-1"), lights=None, disconnected=()):
        self.root = tempfile.mkdtemp(dir=helpers.SCRATCH, prefix="sysfs-")
        self.drm = os.path.join(self.root, "drm")
        self.bl = os.path.join(self.root, "backlight")
        os.makedirs(self.drm)
        os.makedirs(self.bl)
        for name in connectors:
            put(os.path.join(self.drm, f"card1-{name}", "status"), "connected")
        for name in disconnected:
            put(os.path.join(self.drm, f"card1-{name}", "status"), "disconnected")
        if lights is None:
            lights = {"amdgpu_bl1": {"link": "card1-eDP-1", "max": MAX, "level": MAX, "type": "raw"}}
        for dev, spec in lights.items():
            self.light(dev, **spec)

    def light(self, dev, link, max=MAX, level=MAX, type="raw", actual=None):
        base = os.path.join(self.bl, dev)
        put(os.path.join(base, "max_brightness"), max)
        put(os.path.join(base, "brightness"), level)
        put(os.path.join(base, "actual_brightness"), level if actual is None else actual)
        put(os.path.join(base, "type"), type)
        target = os.path.join(self.drm, link) if link.startswith("card") else os.path.join(self.root, "pci", link)
        os.makedirs(target, exist_ok=True)
        os.symlink(target, os.path.join(base, "device"))

    def level(self, dev="amdgpu_bl1"):
        with open(os.path.join(self.bl, dev, "brightness")) as handle:
            return int(handle.read())

    def set_level(self, value, dev="amdgpu_bl1", actual=None):
        put(os.path.join(self.bl, dev, "brightness"), value)
        put(os.path.join(self.bl, dev, "actual_brightness"), value if actual is None else actual)


class TreeCase(unittest.TestCase):
    tree_args = {}

    def setUp(self):
        self.tree = Tree(**self.tree_args)
        self.env = mock.patch.dict(os.environ, {"HYPR_DRM_DIR": self.tree.drm,
                                                "HYPR_BACKLIGHT_DIR": self.tree.bl})
        self.env.start()
        self.nofork = mock.patch.object(backlight.subprocess, "run",
                                        side_effect=AssertionError("a test tried to fork"))
        self.nofork.start()
        self.remove_marks()

    def tearDown(self):
        self.nofork.stop()
        self.env.stop()
        self.remove_marks()
        shutil.rmtree(self.tree.root, True)

    @staticmethod
    def remove_marks():
        try:
            os.remove(backlight.marks_file())
        except OSError:
            pass

    def unwritable_panel(self):
        """No udev rule, logind refusing, no brightnessctl: every write fails."""
        path = os.path.join(self.tree.bl, "amdgpu_bl1", "brightness")
        os.chmod(path, 0o444)
        if os.access(path, os.W_OK):
            self.skipTest("running as root: every file is writable")
        self.nofork.stop()
        self.nofork = mock.patch.object(backlight.subprocess, "run", return_value=mock.Mock(returncode=1))
        self.nofork.start()

    def writable_again(self):
        os.chmod(os.path.join(self.tree.bl, "amdgpu_bl1", "brightness"), 0o644)


# -- backlight.py ---------------------------------------------------------------------
class Mapping(TreeCase):
    def test_connector_from_the_device_link(self):
        self.assertEqual(backlight.screens(), {"eDP-1": "amdgpu_bl1"})
        self.assertEqual(backlight.find("edp-1"), "amdgpu_bl1")
        self.assertIsNone(backlight.find("DP-1"))

    def test_desktop_has_none(self):
        empty = Tree(connectors=("DP-1", "HDMI-A-1"), lights={})
        self.assertEqual(backlight.screens(empty.drm, empty.bl), {})

    def test_default_drm_folder_of_the_tests_is_empty(self):
        # helpers.py's HYPR_DRM_DIR: this laptop's panel is invisible to every other test
        with mock.patch.dict(os.environ, {"HYPR_DRM_DIR": os.path.join(helpers.SCRATCH, "no-drm")}):
            os.environ.pop("HYPR_BACKLIGHT_DIR")
            self.assertEqual(backlight.screens(), {})

    def test_firmware_backlight_goes_to_the_one_panel(self):
        t = Tree(lights={"acpi_video0": {"link": "LNXVIDEO:00", "type": "firmware", "max": 15, "level": 15}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {"eDP-1": "acpi_video0"})

    def test_firmware_preferred_over_platform(self):
        t = Tree(lights={"acpi_video0": {"link": "LNXVIDEO:00", "type": "firmware", "max": 15},
                         "asus_screenpad": {"link": "asus-nb-wmi", "type": "platform", "max": 255}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {"eDP-1": "acpi_video0"})

    def test_linked_backlight_wins_over_loose_ones(self):
        t = Tree(lights={"amdgpu_bl1": {"link": "card1-eDP-1"},
                         "acpi_video0": {"link": "LNXVIDEO:00", "type": "firmware", "max": 15}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {"eDP-1": "amdgpu_bl1"})

    def test_loose_backlight_not_guessed_without_a_single_panel(self):
        t = Tree(connectors=("DP-1",), lights={"acpi_video0": {"link": "LNXVIDEO:00", "type": "firmware"}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {})
        t = Tree(connectors=("eDP-1", "eDP-2", "DP-1"),
                 lights={"acpi_video0": {"link": "LNXVIDEO:00", "type": "firmware"}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {})

    def test_disconnected_connector_is_no_panel(self):
        # a mini-PC with an unused eDP connector and a loose acpi_video0: a desktop
        t = Tree(connectors=("DP-1",), disconnected=("eDP-1",),
                 lights={"acpi_video0": {"link": "LNXVIDEO:00", "type": "firmware"}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {})
        t = Tree(connectors=("DP-1",), disconnected=("eDP-1",),
                 lights={"amdgpu_bl0": {"link": "card1-eDP-1"}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {})
        self.assertEqual(backlight.connectors(t.drm), {"DP-1": "card1-DP-1"})

    def test_zero_range_is_ignored(self):
        t = Tree(lights={"broken": {"link": "card1-eDP-1", "max": 0, "level": 0}})
        self.assertEqual(backlight.screens(t.drm, t.bl), {})


class Curve(unittest.TestCase):
    def test_ends(self):
        for top in (10, 255, 1000, MAX):
            self.assertEqual(backlight.to_raw(100, top), top)
            self.assertGreaterEqual(backlight.to_raw(20, top), 1)
            self.assertEqual(backlight.to_raw(20, top), backlight.min_raw(top))
            self.assertEqual(backlight.to_percent(top, top), 100)

    def test_never_zero_even_below_the_floor(self):
        self.assertEqual(backlight.to_raw(0, MAX), backlight.min_raw(MAX))
        self.assertEqual(backlight.to_raw(-50, 10), 1)

    def test_monotonic(self):
        values = [backlight.to_raw(p, MAX) for p in range(20, 101)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(set(values)), len(values))

    def test_round_trip_is_exact_on_a_fine_backlight(self):
        for top in (MAX, 4096):
            for p in range(20, 101):
                self.assertEqual(backlight.to_percent(backlight.to_raw(p, top), top), p, (top, p))

    def test_perceptual_middle(self):
        # half way up the keys is about a quarter of the light, not half
        self.assertLess(backlight.to_raw(60, MAX), MAX * 0.3)
        self.assertGreater(backlight.to_raw(60, MAX), MAX * 0.2)

    def test_dark_firmware_level_reads_the_floor(self):
        self.assertEqual(backlight.to_percent(0, MAX), 20)

    def test_coarse_step_always_moves(self):
        top = 10
        current = backlight.to_raw(60, top)
        up = backlight.stepped(current, top, 65, +5)
        down = backlight.stepped(current, top, 55, -5)
        self.assertGreater(up, current)
        self.assertLess(down, current)
        self.assertEqual(backlight.stepped(top, top, 105, +5), top)          # stays at the top
        self.assertEqual(backlight.stepped(1, top, 15, -5), 1)               # and at the floor
        self.assertEqual(backlight.stepped(current, top, 60, 0), current)    # absolute: no nudge

    def test_down_never_lifts_a_level_below_the_floor(self):
        for current in (0, 1):
            self.assertEqual(backlight.stepped(current, MAX, 15, -5), current)
        self.assertEqual(backlight.stepped(0, 10, 15, -5), 0)
        # ... while up from there goes up
        self.assertGreater(backlight.stepped(0, MAX, 25, +5), 0)

    def test_up_never_lowers(self):
        # a level between two curve points: the rounded target can be below it
        top = 10
        for current in range(0, top + 1):
            for start in range(20, 101, 5):
                self.assertGreaterEqual(backlight.stepped(current, top, start + 5, +5), current)
                self.assertLessEqual(backlight.stepped(current, top, start - 5, -5), current)


class Levels(TreeCase):
    def test_reads_brightness(self):
        self.tree.set_level(backlight.to_raw(70, MAX))
        self.assertEqual(backlight.percent("amdgpu_bl1"), 70)

    def test_small_hardware_rounding_is_ignored(self):
        # this laptop: brightness 65535, actual_brightness 64736
        self.tree.set_level(MAX, actual=64736)
        self.assertEqual(backlight.level("amdgpu_bl1"), (MAX, MAX))

    def test_raw_backlight_ignores_actual_brightness(self):
        # amdgpu with ABM on (tuned's balanced-battery / powersave): the
        # hardware reports well below what was asked, long after the write
        self.tree.set_level(60000, actual=45000)
        path = os.path.join(self.tree.bl, "amdgpu_bl1", "brightness")
        os.utime(path, (0, os.stat(path).st_mtime - 3600))
        self.assertEqual(backlight.level("amdgpu_bl1"), (60000, MAX))
        self.assertEqual(backlight.percent("amdgpu_bl1"), backlight.to_percent(60000, MAX))

    def test_up_with_abm_rises(self):
        self.tree.set_level(60000, actual=45000)
        self.assertGreater(backlight.set_percent("amdgpu_bl1", backlight.percent("amdgpu_bl1") + 5, step=5),
                           60000)
        self.assertGreater(self.tree.level(), 60000)

    def test_firmware_change_seen_through_actual(self):
        t = Tree(lights={"acpi_video0": {"link": "LNXVIDEO:00", "type": "firmware", "max": 100, "level": 100}})
        t.set_level(100, dev="acpi_video0", actual=40)
        self.assertEqual(backlight.level("acpi_video0", root=t.bl), (40, 100))
        t.set_level(100, dev="acpi_video0", actual=98)          # rounding
        self.assertEqual(backlight.level("acpi_video0", root=t.bl), (100, 100))

    def test_missing_device(self):
        self.assertEqual(backlight.level("nope"), (None, None))
        self.assertIsNone(backlight.percent("nope"))


class Writers(TreeCase):
    def calls(self, codes):
        seen = []

        def run(argv, **_kw):
            seen.append(argv)
            code = codes.pop(0)
            if isinstance(code, Exception):
                raise code
            return mock.Mock(returncode=code)
        return seen, run

    def test_writable_file_needs_no_process(self):
        seen, run = self.calls([])
        self.assertEqual(backlight.write("amdgpu_bl1", 1234, run=run), "sysfs")
        self.assertEqual(self.tree.level(), 1234)
        self.assertEqual(seen, [])

    def read_only(self):
        path = os.path.join(self.tree.bl, "amdgpu_bl1", "brightness")
        os.chmod(path, 0o444)
        if os.access(path, os.W_OK):
            self.skipTest("running as root: every file is writable")

    def test_logind_when_root_owns_the_file(self):
        self.read_only()
        seen, run = self.calls([0])
        self.assertEqual(backlight.write("amdgpu_bl1", 4321, run=run), "logind")
        self.assertEqual(seen, [["busctl", "call", "org.freedesktop.login1",
                                 "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session",
                                 "SetBrightness", "ssu", "backlight", "amdgpu_bl1", "4321"]])

    def test_brightnessctl_when_logind_refuses_or_busctl_is_missing(self):
        self.read_only()
        for first in (1, FileNotFoundError("busctl")):
            seen, run = self.calls([first, 0])
            self.assertEqual(backlight.write("amdgpu_bl1", 99, run=run), "brightnessctl")
            self.assertEqual(seen[1], ["brightnessctl", "--quiet", "-d", "amdgpu_bl1", "set", "99"])

    def test_nothing_works(self):
        self.read_only()
        _seen, run = self.calls([1, FileNotFoundError("brightnessctl"), 1, 1])
        self.assertIsNone(backlight.write("amdgpu_bl1", 99, run=run))
        self.assertIsNone(backlight.set_percent("amdgpu_bl1", 50, run=run))

    def test_unwritable_is_marked_and_retried_later(self):
        self.read_only()
        _seen, run = self.calls([1, 1])
        backlight.write("amdgpu_bl1", 99, run=run)
        self.assertIn("amdgpu_bl1", backlight.unwritable())
        self.assertEqual(backlight.driven(), {})                       # software for now
        self.assertEqual(backlight.driven(retry=True), {})            # ... not tried again at once
        self.assertEqual(backlight.screens(), {"eDP-1": "amdgpu_bl1"})
        with mock.patch.object(backlight.time, "time", return_value=time.time() + backlight.RETRY_S + 1):
            self.assertEqual(backlight.driven(retry=True), {"eDP-1": "amdgpu_bl1"})
        self.assertFalse(backlight.status_data()["eDP-1"]["writable"])
        _seen, run = self.calls([0])
        self.assertEqual(backlight.write("amdgpu_bl1", 99, run=run), "logind")
        self.assertEqual(backlight.unwritable(), {})
        self.assertFalse(os.path.exists(backlight.marks_file()))
        self.assertEqual(backlight.driven(), {"eDP-1": "amdgpu_bl1"})

    def test_a_working_write_writes_no_marks_file(self):
        backlight.write("amdgpu_bl1", 99)
        self.assertFalse(os.path.exists(backlight.marks_file()))

    def test_set_percent_from_a_base(self):
        self.tree.set_level(5000)
        self.assertEqual(backlight.set_percent("amdgpu_bl1", 75, step=5, base=backlight.to_raw(70, MAX)),
                         backlight.to_raw(75, MAX))

    def test_lock_is_exclusive(self):
        import fcntl
        with backlight.locked():
            with open(os.path.join(backlight.runtime(), "backlight.lock")) as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(os.path.join(backlight.runtime(), "backlight.lock")) as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)        # free again

    def test_set_percent_skips_a_write_that_changes_nothing(self):
        seen, run = self.calls([])
        self.assertEqual(backlight.set_percent("amdgpu_bl1", 100, run=run), MAX)
        self.assertEqual(seen, [])

    def test_status_data(self):
        self.tree.set_level(backlight.to_raw(40, MAX))
        self.assertEqual(backlight.status_data(), {"eDP-1": {
            "device": "amdgpu_bl1", "raw": backlight.to_raw(40, MAX), "max": MAX, "percent": 40, "type": "raw",
            "writable": True}})


# -- screen-color.py ------------------------------------------------------------------
class ScreenColorCase(TreeCase):
    monitors = [{"name": "eDP-1", "description": "built-in"}, {"name": "DP-1", "description": "external"}]

    def setUp(self):
        super().setUp()
        for path in (sc.STATE, sc.DIMFILE, sc.BACKLIGHT_DIM):
            self.assertTrue(path.startswith(helpers.SCRATCH))
            self.addCleanup(self.remove, path)
            self.remove(path)
        self.pokes = []
        for name, fake in (("poke", lambda: self.pokes.append(1)), ("monitors", lambda: list(self.monitors))):
            patcher = mock.patch.object(sc, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def saved(self):
        try:
            with open(sc.STATE) as handle:
                return json.load(handle)
        except OSError:
            return None

    def write_state(self, data):
        data.setdefault("night", 0)
        sc.save(data)


class Brightness(ScreenColorCase):
    def test_backlit_screen_drives_the_backlight(self):
        sc.set_values("eDP-1", ["brightness", "60"])
        self.assertEqual(self.tree.level(), backlight.to_raw(60, MAX))
        self.assertNotIn("eDP-1", self.saved()["screens"])
        self.assertEqual(self.pokes, [])               # no matrix changed

    def test_relative_steps_read_the_current_level(self):
        self.tree.set_level(backlight.to_raw(50, MAX))
        sc.set_values("edp-1", ["brightness", "-5"])
        self.assertEqual(backlight.percent("amdgpu_bl1"), 45)
        self.tree.set_level(backlight.to_raw(80, MAX))      # moved elsewhere (Fn keys)
        sc.set_values("eDP-1", ["brightness", "+5"])
        self.assertEqual(backlight.percent("amdgpu_bl1"), 85)

    def test_floor(self):
        sc.set_values("eDP-1", ["brightness", "5"])
        self.assertEqual(self.tree.level(), backlight.min_raw(MAX))
        self.assertGreater(self.tree.level(), 0)

    def test_external_stays_software(self):
        sc.set_values("DP-1", ["brightness", "60"])
        self.assertEqual(self.saved()["screens"]["DP-1"], {"brightness": 60})
        self.assertEqual(self.tree.level(), MAX)
        self.assertEqual(self.pokes, [1])

    def test_all_moves_both(self):
        sc.set_values("all", ["brightness", "-10"])
        self.assertEqual(backlight.percent("amdgpu_bl1"), 90)
        data = self.saved()
        self.assertEqual(sc.settings_for(data, "DP-1")["brightness"], 90)
        self.assertNotIn("brightness", data["screens"].get("eDP-1", {}))

    def test_other_keys_stay_in_the_matrix(self):
        sc.set_values("eDP-1", ["warmth", "5000", "brightness", "70"])
        self.assertEqual(self.saved()["screens"]["eDP-1"], {"warmth": 5000})
        self.assertEqual(backlight.percent("amdgpu_bl1"), 70)
        self.assertEqual(self.pokes, [1])

    def test_unwritable_panel_falls_back_to_software(self):
        self.tree.set_level(30000)
        self.unwritable_panel()
        with mock.patch("sys.stderr"):
            sc.set_values("eDP-1", ["brightness", "-10"])
        self.assertEqual(self.tree.level(), 30000)
        self.assertEqual(self.saved()["screens"]["eDP-1"], {"brightness": 90})
        self.assertEqual(self.pokes, [1])
        # the next press (within RETRY_S) goes straight to software, no write tried
        backlight.subprocess.run.reset_mock()
        sc.set_values("eDP-1", ["brightness", "-10"])
        backlight.subprocess.run.assert_not_called()
        self.assertEqual(self.saved()["screens"]["eDP-1"], {"brightness": 80})
        data = sc.status_data()
        self.assertEqual(data["hardware"], [])
        self.assertEqual(data["unwritable"], ["amdgpu_bl1"])
        self.assertEqual({s["name"]: s["brightness"] for s in data["screens"]}["eDP-1"], 80)

    def test_unreadable_backlight_says_so(self):
        os.remove(os.path.join(self.tree.bl, "amdgpu_bl1", "brightness"))
        with mock.patch("sys.stderr") as err:
            sc.set_values("eDP-1", ["brightness", "+5"])
        self.assertTrue(err.write.called)

    def test_lid_closed_panel_can_still_be_named(self):
        self.monitors = [{"name": "DP-1"}]
        sc.set_values("eDP-1", ["brightness", "40"])
        self.assertEqual(backlight.percent("amdgpu_bl1"), 40)


class Matrices(ScreenColorCase):
    def sent(self, data):
        client = sc.Client.__new__(sc.Client)
        client.ctm = 99
        client.outputs = {1: {"id": 10, "name": "eDP-1"}, 2: {"id": 11, "name": "DP-1"}}
        out = {}

        def send(obj, opcode, payload=b""):
            if opcode == 0:
                oid, *values = struct.unpack("=I9i", payload)
                out[oid] = [v / 256 for v in values]
        client.send = send
        with mock.patch("builtins.print"):
            client.apply(data)
        return out

    def test_backlit_matrix_ignores_brightness_and_dim(self):
        with open(sc.DIMFILE, "w") as handle:
            handle.write("40")
        m = self.sent({"screens": {"*": {"brightness": 50}}, "night": 0})
        self.assertEqual(m[10][0], 1.0)                 # eDP-1: the backlight's job
        self.assertAlmostEqual(m[11][0], 0.2, places=2)  # DP-1: 50 % x dim 40 %

    def test_backlit_matrix_keeps_its_colour(self):
        m = self.sent({"screens": {"eDP-1": {"warmth": 3000}}, "night": 0})
        self.assertLess(m[10][8], 1.0)

    def test_unwritable_backlight_is_software_again(self):
        backlight.mark("amdgpu_bl1", True)
        with open(sc.DIMFILE, "w") as handle:
            handle.write("40")
        m = self.sent({"screens": {"*": {"brightness": 50}}, "night": 0})
        self.assertAlmostEqual(m[10][0], 0.2, places=2)  # eDP-1 dims in the matrix, as before


class Dim(ScreenColorCase):
    def test_dim_and_back_exactly(self):
        start = 41234
        self.tree.set_level(start)
        sc.set_dim("40")
        dimmed = self.tree.level()
        self.assertEqual(dimmed, round(start * 0.4 ** backlight.GAMMA))
        self.assertEqual(sc.dim_factor(), 0.4)          # the external screen's matrix dim
        sc.set_dim("off")
        self.assertEqual(self.tree.level(), start)
        self.assertFalse(os.path.exists(sc.BACKLIGHT_DIM))

    def test_never_dims_to_zero(self):
        self.tree.set_level(backlight.min_raw(MAX) + 10)
        sc.set_dim("5")
        self.assertEqual(self.tree.level(), backlight.min_raw(MAX))

    def test_dim_again_keeps_the_level_before_the_first(self):
        self.tree.set_level(30000)
        sc.set_dim("60")
        sc.set_dim("20")
        self.assertEqual(self.tree.level(), round(30000 * 0.2 ** backlight.GAMMA))
        sc.set_dim("off")
        self.assertEqual(self.tree.level(), 30000)

    def test_moved_while_dimmed_is_not_undone(self):
        self.tree.set_level(30000)
        sc.set_dim("40")
        self.tree.set_level(20000)              # firmware hotkey during the dim
        sc.set_dim("off")
        self.assertEqual(self.tree.level(), 20000)

    def test_key_press_while_dimmed_wins(self):
        self.tree.set_level(30000)
        sc.set_dim("40")
        sc.set_values("eDP-1", ["brightness", "+5"])
        chosen = self.tree.level()
        sc.set_dim("off")
        self.assertEqual(self.tree.level(), chosen)

    def test_waking_key_steps_from_before_the_dim_in_either_order(self):
        # the key that ends the idle runs `set` and hypridle's `dim off` at once
        start = backlight.to_raw(80, MAX)
        want = backlight.to_raw(85, MAX)
        for first, second in ((lambda: sc.set_values("eDP-1", ["brightness", "+5"]), lambda: sc.set_dim("off")),
                              (lambda: sc.set_dim("off"), lambda: sc.set_values("eDP-1", ["brightness", "+5"]))):
            self.tree.set_level(start)
            sc.set_dim("40")
            self.assertLess(self.tree.level(), start)
            first()
            second()
            self.assertEqual(self.tree.level(), want)
            self.assertFalse(os.path.exists(sc.BACKLIGHT_DIM))

    def test_waking_key_down_steps_from_before_the_dim(self):
        self.tree.set_level(backlight.to_raw(80, MAX))
        sc.set_dim("40")
        sc.set_values("eDP-1", ["brightness", "-5"])
        self.assertEqual(self.tree.level(), backlight.to_raw(75, MAX))

    def test_set_and_dim_hold_the_lock(self):
        held = []
        real = backlight.locked

        def recording():
            held.append(1)
            return real()
        with mock.patch.object(backlight, "locked", recording):
            self.tree.set_level(30000)
            sc.set_values("eDP-1", ["brightness", "+5"])
            sc.set_dim("40")
            sc.set_dim("off")
        self.assertEqual(held, [1, 1, 1])

    def test_dim_record_survives_logout(self):
        self.assertTrue(sc.BACKLIGHT_DIM.startswith(os.environ["XDG_STATE_HOME"]))

    def test_lost_session_restores_at_the_next_start(self):
        self.tree.set_level(30000)
        sc.set_dim("40")
        os.remove(sc.DIMFILE)                   # logged out mid-dim: the runtime folder is gone
        with backlight.locked():
            sc.recover_dim()
        self.assertEqual(self.tree.level(), 30000)
        self.assertFalse(os.path.exists(sc.BACKLIGHT_DIM))

    def test_restart_while_dimmed_is_left_alone(self):
        self.tree.set_level(30000)
        sc.set_dim("40")
        dimmed = self.tree.level()
        with backlight.locked():
            sc.recover_dim()                    # the daemon restarted, the dim is still on
        self.assertEqual(self.tree.level(), dimmed)
        self.assertTrue(os.path.exists(sc.BACKLIGHT_DIM))

    def test_stale_record_of_a_moved_backlight_is_dropped(self):
        self.tree.set_level(30000)
        sc.set_dim("40")
        os.remove(sc.DIMFILE)
        self.tree.set_level(12345)              # moved since (another session, the firmware)
        with backlight.locked():
            sc.recover_dim()
        self.assertEqual(self.tree.level(), 12345)
        self.assertFalse(os.path.exists(sc.BACKLIGHT_DIM))

    def test_failed_restore_keeps_the_record(self):
        self.tree.set_level(30000)
        sc.set_dim("40")
        self.unwritable_panel()
        with mock.patch("sys.stderr"):
            sc.set_dim("off")
        self.assertEqual(sc.dim_saved()["amdgpu_bl1"]["saved"], 30000)
        self.writable_again()
        backlight.mark("amdgpu_bl1", False)
        os.remove(sc.DIMFILE) if os.path.exists(sc.DIMFILE) else None
        with backlight.locked():
            sc.recover_dim()
        self.assertEqual(self.tree.level(), 30000)

    def test_failed_dim_records_nothing_and_the_matrix_dims(self):
        self.tree.set_level(30000)
        self.unwritable_panel()
        with mock.patch("sys.stderr"):
            sc.set_dim("40")
        self.assertEqual(self.tree.level(), 30000)
        self.assertEqual(sc.dim_saved(), {})
        self.assertIn("amdgpu_bl1", backlight.unwritable())     # Client.apply: software dim
        self.assertEqual(self.pokes, [1])

    def test_off_without_a_dim_touches_nothing(self):
        self.tree.set_level(30000)
        sc.set_dim("off")
        self.assertEqual(self.tree.level(), 30000)
        self.assertEqual(self.pokes, [])

    def test_status_shows_the_saved_level(self):
        self.tree.set_level(30000)
        sc.set_dim("40")
        self.assertEqual(sc.status_data()["dimmed_from"], {"amdgpu_bl1": 30000})


class Migration(ScreenColorCase):
    def test_own_software_brightness_becomes_the_backlight_once(self):
        self.write_state({"screens": {"eDP-1": {"brightness": 60, "warmth": 5000}}})
        self.assertTrue(sc.migrate(sc.load()))
        self.assertEqual(backlight.percent("amdgpu_bl1"), 60)
        data = self.saved()
        self.assertEqual(data["screens"]["eDP-1"], {"warmth": 5000})
        self.assertEqual(data["hardware"], ["eDP-1"])
        self.tree.set_level(MAX)
        self.assertFalse(sc.migrate(sc.load()))         # once
        self.assertEqual(self.tree.level(), MAX)

    def test_inherited_all_default(self):
        self.write_state({"screens": {"*": {"brightness": 50}}})
        sc.migrate(sc.load())
        self.assertEqual(backlight.percent("amdgpu_bl1"), 50)
        self.assertEqual(self.saved()["screens"]["*"], {"brightness": 50})   # externals keep it

    def test_full_brightness_leaves_the_backlight(self):
        self.tree.set_level(20000)
        self.write_state({"screens": {"eDP-1": {"warmth": 5000}}})
        sc.migrate(sc.load())
        self.assertEqual(self.tree.level(), 20000)
        self.assertEqual(self.saved()["hardware"], ["eDP-1"])

    def test_first_key_press_migrates(self):
        self.write_state({"screens": {"eDP-1": {"brightness": 60}}})
        sc.set_values("eDP-1", ["brightness", "+5"])
        self.assertEqual(backlight.percent("amdgpu_bl1"), 65)
        self.assertNotIn("eDP-1", self.saved()["screens"])

    def test_failed_write_keeps_the_saved_brightness(self):
        self.write_state({"screens": {"eDP-1": {"brightness": 60}, "*": {"brightness": 95}}})
        self.unwritable_panel()
        with mock.patch("sys.stderr"):
            self.assertFalse(sc.migrate(sc.load()))
        data = self.saved()
        self.assertEqual(data["screens"]["eDP-1"], {"brightness": 60})
        self.assertNotIn("hardware", data)
        self.assertIn("amdgpu_bl1", backlight.unwritable())
        # the next command after RETRY_S, with the write working again, moves it
        self.writable_again()
        with mock.patch.object(backlight.time, "time", return_value=time.time() + backlight.RETRY_S + 1):
            sc.set_values("DP-1", ["warmth", "5000"])
        self.assertEqual(backlight.percent("amdgpu_bl1"), 60)
        data = self.saved()
        self.assertNotIn("eDP-1", {k for k, v in data["screens"].items() if "brightness" in v} - {"*"})
        self.assertEqual(data["hardware"], ["eDP-1"])
        self.assertEqual(backlight.unwritable(), {})

    def test_reset_all_does_not_migrate_again(self):
        self.write_state({"screens": {"eDP-1": {"brightness": 60}}})
        sc.migrate(sc.load())
        data = sc.load()
        data["screens"] = {}
        sc.save(data)
        self.assertEqual(sc.load()["hardware"], ["eDP-1"])


class Status(ScreenColorCase):
    def test_hardware_screens(self):
        self.tree.set_level(backlight.to_raw(70, MAX))
        self.write_state({"screens": {"DP-1": {"brightness": 40}}, "hardware": ["eDP-1"]})
        data = sc.status_data()
        screens = {s["name"]: s for s in data["screens"]}
        self.assertTrue(screens["eDP-1"]["hardware"])
        self.assertEqual(screens["eDP-1"]["backlight"], "amdgpu_bl1")
        self.assertEqual(screens["eDP-1"]["brightness"], 70)
        self.assertTrue(screens["eDP-1"]["neutral"])     # the matrix is neutral
        self.assertFalse(screens["DP-1"]["hardware"])
        self.assertEqual(screens["DP-1"]["brightness"], 40)
        self.assertEqual(data["hardware"], ["eDP-1"])
        self.assertEqual(data["backlight"]["eDP-1"]["percent"], 70)
        json.dumps(data)


class Desktop(ScreenColorCase):
    """No backlight: everything as before, and the file is never rewritten."""
    monitors = [{"name": "DP-1"}, {"name": "HDMI-A-1"}]

    def setUp(self):
        super().setUp()
        empty = Tree(connectors=("DP-1", "HDMI-A-1"), lights={})
        os.environ["HYPR_DRM_DIR"], os.environ["HYPR_BACKLIGHT_DIR"] = empty.drm, empty.bl

    def test_no_migration_no_file(self):
        self.assertFalse(sc.migrate(sc.load()))
        self.assertIsNone(self.saved())

    def test_brightness_is_software(self):
        sc.set_values("all", ["brightness", "70"])
        self.assertEqual(self.saved()["screens"]["*"], {"brightness": 70})
        self.assertEqual(self.pokes, [1])
        data = sc.status_data()
        self.assertEqual(data["hardware"], [])
        self.assertFalse(any(s["hardware"] for s in data["screens"]))

    def test_all_steps_every_screen_once(self):
        # "*" is stepped first; a screen inheriting it must not step from the new value
        sc.set_values("all", ["brightness", "-10"])
        data = self.saved()
        self.assertEqual([sc.settings_for(data, n)["brightness"] for n in ("*", "DP-1", "HDMI-A-1")],
                         [90, 90, 90])

    def test_dim_is_the_matrix_only(self):
        sc.set_dim("40")
        self.assertFalse(os.path.exists(sc.BACKLIGHT_DIM))
        sc.set_dim("off")
        self.assertEqual(self.pokes, [1, 1])


# -- osd.py ---------------------------------------------------------------------------
class OsdReadBack(ScreenColorCase):
    def test_named_backlit_screen(self):
        self.tree.set_level(backlight.to_raw(35, MAX))
        self.assertEqual(osd.read_brightness("eDP-1"), 35)

    def test_all_on_the_focused_backlit_screen(self):
        self.tree.set_level(backlight.to_raw(35, MAX))
        with mock.patch.object(osd, "focused_screen", lambda mons=None: "eDP-1"):
            self.assertEqual(osd.read_brightness(None), 35)

    def test_all_on_an_external_screen_is_the_software_default(self):
        self.tree.set_level(backlight.to_raw(35, MAX))
        self.write_state({"screens": {"*": {"brightness": 80}}})
        with mock.patch.object(osd, "SCREEN_STATE", sc.STATE), \
                mock.patch.object(osd, "focused_screen", lambda mons=None: "DP-1"):
            self.assertEqual(osd.read_brightness(None), 80)
            self.assertEqual(osd.read_brightness("DP-1"), 80)

    def test_desktop_never_asks_hyprctl(self):
        empty = Tree(connectors=("DP-1",), lights={})
        os.environ["HYPR_DRM_DIR"], os.environ["HYPR_BACKLIGHT_DIR"] = empty.drm, empty.bl
        with mock.patch.object(osd, "hypr_monitors", side_effect=AssertionError("hyprctl asked")):
            self.assertEqual(osd.read_brightness(None), 100)

    def test_focused_screen_from_the_answer_already_there(self):
        # one hyprctl per press: the pill's placement and the read share it
        self.tree.set_level(backlight.to_raw(35, MAX))
        mons = [{"name": "DP-1", "x": 0, "y": 0}, {"name": "eDP-1", "x": 1920, "y": 0, "focused": True}]
        with mock.patch.object(osd, "hypr_monitors", side_effect=AssertionError("hyprctl asked twice")):
            self.assertEqual(osd.read_brightness(None, mons), 35)
            self.assertEqual(osd.screen_origin(None, mons), (1920, 0))
            self.assertEqual(osd.screen_origin("DP-1", mons), (0, 0))

    def test_unwritable_panel_shows_its_software_brightness(self):
        self.tree.set_level(backlight.to_raw(35, MAX))
        backlight.mark("amdgpu_bl1", True)
        self.write_state({"screens": {"eDP-1": {"brightness": 70}}})
        with mock.patch.object(osd, "SCREEN_STATE", sc.STATE):
            self.assertEqual(osd.read_brightness("eDP-1"), 70)


if __name__ == "__main__":
    unittest.main()
