"""The battery charge limit: the root helper (system/charge-limit/charge-limit)
and the session's charge-limit.py, plus the files that wire them together
(the two units, the polkit rule, both install scripts).

The helper: the number check (the instance name of charge-limit@N.service
lands there as is), snapping, which batteries count (no mouse, no empty
bay), writing the threshold and the saved file, firmware with fixed values
(learned once with evidence, then snapped up front), a transient failure
(retried, never learned), range firmware with a floor (Dell 55-100: the
floor, nothing learned), firmware that honours nothing or only 100 (nothing
saved, left charging to full), an asus-wmi ASUS (60/80/100 without probing;
"any" opts out), the start threshold moved out of the way and restored,
two batteries ending on one value, and apply at boot / resume (nothing
saved: nothing written; the switch appearing late or never; retrying, never
probing, never rewriting the saved limit or the choices). The session CLI:
status on a desktop and on a laptop, the saved file mirrored into
battery.json, the switch on a second battery, set refusing bad numbers / no
switch / no root side, set snapping before it asks, a failed start, and
runs end to end through the real helper.

Hermetic: a fake power_supply tree per test (helpers.fake_power_supply)
and a scratch /etc/atrium; firmware that refuses values is a stand-in for
write_threshold (a plain file takes anything); systemctl is never run --
the session's run= is a recorder, or a stand-in that calls the helper's
main() on the fake tree. Nothing here needs or uses root."""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(helpers.SCRIPTS))))
SYSTEM = os.path.join(REPO, "system", "charge-limit")
HELPER = os.path.join(SYSTEM, "charge-limit")

ps = helpers.import_script("power_state.py", "power_state")
cl = helpers.import_script("charge-limit.py")


def load_helper():
    """The root helper as a module (its file name has no .py)."""
    loader = importlib.machinery.SourceFileLoader("charge_limit_root", HELPER)
    spec = importlib.util.spec_from_loader("charge_limit_root", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


root = load_helper()
root._real_write = root.write_threshold     # Firmware(only=...) passes other batteries to it


def read(path):
    with open(path) as handle:
        return handle.read()


class Scratch(unittest.TestCase):
    """A fresh fake power_supply tree and /etc/atrium for each test."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="charge-limit-", dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.sys = os.path.join(self.dir, "power_supply")
        self.etc = os.path.join(self.dir, "etc-atrium")
        self.logs = []
        # Not an ASUS unless a test says so (this laptop is one: the real
        # /sys/class/dmi must never decide a test), and no real waiting.
        self.vendor = os.path.join(self.dir, "sys_vendor")
        self.drivers = os.path.join(self.dir, "drivers")
        for module, name, value in ((root, "log", self.logs.append), (root, "RETRY_S", 0),
                                    (root, "DMI_VENDOR", self.vendor), (root, "PLATFORM_DRIVERS", self.drivers),
                                    (cl, "DMI_VENDOR", self.vendor), (cl, "PLATFORM_DRIVERS", self.drivers)):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def asus(self, vendor="ASUSTeK COMPUTER INC.", driver="asus-nb-wmi"):
        with open(self.vendor, "w") as handle:
            handle.write(vendor + "\n")
        os.makedirs(os.path.join(self.drivers, driver), exist_ok=True)

    def write_choices(self, text):
        os.makedirs(self.etc, exist_ok=True)
        with open(os.path.join(self.etc, "charge-limit-choices"), "w") as handle:
            handle.write(text)

    def start(self, name="BATT"):
        return self.threshold(name, "charge_control_start_threshold")

    def laptop(self, **battery):
        attrs = {"status": "Charging", "capacity": 70}
        attrs.update(battery)
        return helpers.fake_power_supply(self.sys, battery=attrs, ac=True)

    def threshold(self, name="BATT", attr="charge_control_end_threshold"):
        return int(read(os.path.join(self.sys, name, attr)))

    def saved(self):
        path = os.path.join(self.etc, "charge-limit")
        return read(path) if os.path.exists(path) else None


class Firmware:
    """Stands in for root.write_threshold: firmware that honours only
    ACCEPTS (refused values leave the file as it was), recording each try.
    FLAKY: that many end writes fail first, whatever the value (an
    embedded controller not ready yet: EIO). ONLY: the battery folders it
    applies to (others take anything)."""

    def __init__(self, accepts, flaky=0, only=None):
        self.accepts = set(accepts)
        self.flaky = flaky
        self.only = only
        self.tries = []

    def __call__(self, folder, value, name=root.END):
        if self.only is not None and os.path.basename(folder) not in self.only:
            return root.__dict__["_real_write"](folder, value, name)
        self.tries.append((name, value))
        if name == root.END and self.flaky:
            self.flaky -= 1
            return False
        if name == root.END and value not in self.accepts:
            return False
        with open(os.path.join(folder, name), "w") as handle:
            handle.write(f"{value}\n")
        return True

    def ends(self):
        return [v for n, v in self.tries if n == root.END]


# -- the root helper -----------------------------------------------------------------
class HelperNumbers(unittest.TestCase):
    def test_parse_limit(self):
        for text, want in (("80", 80), ("50", 50), ("100", 100), ("060", 60)):
            self.assertEqual(root.parse_limit(text), want, text)
        for text in ("49", "101", "0", "-80", "+80", "8 0", " 80", "80\n", "0x50", "80.0", "", "1000", "eighty",
                     "80;rm", "../80", None, 80):
            self.assertIsNone(root.parse_limit(text), repr(text))

    def test_snap(self):
        fixed = [60, 80, 100]
        self.assertEqual(root.snap(75, fixed), 80)
        self.assertEqual(root.snap(70, fixed), 60)     # a tie: the lower, for the battery
        self.assertEqual(root.snap(90, fixed), 80)
        self.assertEqual(root.snap(50, fixed), 60)
        self.assertEqual(root.snap(100, fixed), 100)
        self.assertEqual(root.snap(75, []), 75)
        self.assertEqual(root.snap(60, [80, 100]), 80)


class HelperBatteries(Scratch):
    def test_desktop_and_mouse(self):
        self.assertEqual(root.batteries(self.sys), [])          # no tree at all
        helpers.fake_power_supply(self.sys, ac=True, extra={
            "hidpp_battery_0": {"type": "Battery", "scope": "Device", "capacity": 50,
                                "charge_control_end_threshold": 100}})
        self.assertEqual(root.batteries(self.sys), [])

    def test_battery_without_switch(self):
        self.laptop(charge_control_end_threshold=None)
        self.assertEqual(root.batteries(self.sys), [])

    def test_laptop(self):
        self.laptop()
        self.assertEqual(root.batteries(self.sys), [os.path.join(self.sys, "BATT")])

    def test_write_threshold(self):
        self.laptop()
        folder = os.path.join(self.sys, "BATT")
        self.assertTrue(root.write_threshold(folder, 80))
        self.assertEqual(self.threshold(), 80)
        os.remove(os.path.join(folder, root.END))
        os.mkdir(os.path.join(folder, root.END))               # a write that fails (EISDIR, like EINVAL)
        self.assertFalse(root.write_threshold(folder, 80))


class HelperSet(Scratch):
    def test_free_firmware(self):
        self.laptop()
        self.assertEqual(root.set_limit(80, self.sys, self.etc), 80)
        self.assertEqual(self.threshold(), 80)
        self.assertEqual(self.saved(), "80\n")
        self.assertEqual(os.stat(os.path.join(self.etc, "charge-limit")).st_mode & 0o777, 0o644)
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))
        self.assertEqual(root.set_limit(75, self.sys, self.etc), 75)     # any value
        self.assertEqual(self.threshold(), 75)
        self.assertEqual(os.listdir(self.etc), ["charge-limit"])          # no temporary file left

    def test_desktop_does_nothing(self):
        helpers.fake_power_supply(self.sys, ac=True)
        self.assertIsNone(root.set_limit(80, self.sys, self.etc))
        self.assertIsNone(self.saved())

    def test_fixed_values_learned_then_snapped(self):
        self.laptop()
        fw = Firmware({60, 80, 100})
        with mock.patch.object(root, "write_threshold", fw):
            self.assertEqual(root.set_limit(75, self.sys, self.etc), 80)
            self.assertEqual(self.threshold(), 80)
            self.assertEqual(self.saved(), "80\n")
            self.assertEqual(read(os.path.join(self.etc, "charge-limit-choices")), "60 80 100\n")
            # Refused (and retried), probed, 70 between 60 and 80 refused
            # too (so: fixed values), back to full, then snapped.
            self.assertEqual(fw.ends(), [75, 75, 75, 60, 80, 100, 70, 100, 80])
            fw.tries.clear()
            self.assertEqual(root.set_limit(70, self.sys, self.etc), 60)
            self.assertEqual(fw.ends(), [60])                             # snapped up front: no probe
        self.assertEqual(root.read_choices(self.etc), [60, 80, 100])

    def test_two_value_firmware(self):
        self.laptop()
        with mock.patch.object(root, "write_threshold", Firmware({80, 100})):
            self.assertEqual(root.set_limit(60, self.sys, self.etc), 80)
        self.assertEqual(root.read_choices(self.etc), [80, 100])
        self.assertEqual(self.threshold(), 80)

    def test_firmware_honours_nothing(self):
        self.laptop()
        fw = Firmware(set())
        with mock.patch.object(root, "write_threshold", fw):
            self.assertIsNone(root.set_limit(80, self.sys, self.etc))
        self.assertIsNone(self.saved())
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))
        self.assertEqual(fw.ends()[-1], 100)                # the last try is "full", never a low limit
        self.assertTrue(any("honours none" in line for line in self.logs))

    def test_bad_choices_file_ignored(self):
        os.makedirs(self.etc)
        with open(os.path.join(self.etc, "charge-limit-choices"), "w") as handle:
            handle.write("abc 30 80 999\n")
        self.assertEqual(root.read_choices(self.etc), [80])

    def test_start_threshold_moved_out_of_the_way(self):
        self.laptop(charge_control_start_threshold=95)
        root.set_limit(80, self.sys, self.etc)
        self.assertEqual(self.threshold(attr="charge_control_start_threshold"), 75)
        self.assertEqual(self.threshold(), 80)
        helpers.fake_power_supply(self.sys, battery={"charge_control_start_threshold": 40})
        root.set_limit(90, self.sys, self.etc)
        self.assertEqual(self.threshold(attr="charge_control_start_threshold"), 40)   # not in the way: kept

    def test_transient_failure_is_retried_not_learned(self):
        self.laptop()
        fw = Firmware(range(0, 101), flaky=2)       # EIO twice, then fine
        with mock.patch.object(root, "write_threshold", fw):
            self.assertEqual(root.set_limit(75, self.sys, self.etc, sleep=lambda s: None), 75)
        self.assertEqual(fw.ends(), [75, 75, 75])
        self.assertEqual(self.saved(), "75\n")
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))

    def test_range_firmware_with_a_floor(self):
        """Dell-like 55-100: 50 refused, 60/80/100 work, and so does 70 --
        a range, not fixed values: the floor is used, nothing is learned."""
        self.laptop()
        with mock.patch.object(root, "write_threshold", Firmware(range(55, 101))):
            self.assertEqual(root.set_limit(50, self.sys, self.etc), 55)
            self.assertEqual(self.threshold(), 55)
            self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))
            self.assertEqual(root.set_limit(75, self.sys, self.etc), 75)      # not snapped to 80
        self.assertEqual(self.saved(), "75\n")
        self.assertTrue(any("below this firmware's minimum" in line for line in self.logs))

    def test_only_full_is_no_limit(self):
        self.laptop()
        with mock.patch.object(root, "write_threshold", Firmware({100})):
            self.assertIsNone(root.set_limit(80, self.sys, self.etc))
        self.assertEqual(self.threshold(), 100)
        self.assertIsNone(self.saved())
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))

    def test_asus_takes_60_80_100_without_probing(self):
        """asus-wmi reads back its own cache, so 75 would "work": snapped
        up front instead, and nothing is probed or learned."""
        self.laptop()
        self.asus()
        fw = Firmware(range(0, 101))
        with mock.patch.object(root, "write_threshold", fw):
            self.assertEqual(root.set_limit(75, self.sys, self.etc), 80)
        self.assertEqual(fw.ends(), [80])
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))
        self.write_choices("any\n")                              # the opt-out
        self.assertEqual(root.set_limit(75, self.sys, self.etc), 75)
        self.write_choices("80 100\n")                           # a file by hand wins
        self.assertEqual(root.set_limit(60, self.sys, self.etc), 80)

    def test_asus_detection(self):
        self.assertFalse(root.asus_wmi())
        self.asus(vendor="Dell Inc.")
        self.assertFalse(root.asus_wmi())                        # the driver alone is not enough
        self.asus(driver="asus-wmi")
        self.assertTrue(root.asus_wmi())
        shutil.rmtree(self.drivers)
        self.assertFalse(root.asus_wmi())                        # an ASUS without asus-wmi bound

    def test_start_threshold_restored_when_the_limit_goes_up(self):
        """ThinkPad out of the box: start 96, end 100. 80 moves the start to
        75; taking the limit off restores 96 (not "charge only below 75")."""
        self.laptop(charge_control_start_threshold=96)
        root.set_limit(80, self.sys, self.etc)
        self.assertEqual((self.start(), self.threshold()), (75, 80))
        root.set_limit(70, self.sys, self.etc)
        self.assertEqual((self.start(), self.threshold()), (65, 70))
        root.set_limit(100, self.sys, self.etc)
        self.assertEqual((self.start(), self.threshold()), (96, 100))
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-start")))    # nothing to remember

    def test_start_changed_elsewhere_counts_as_the_original(self):
        self.laptop(charge_control_start_threshold=96)
        root.set_limit(80, self.sys, self.etc)
        helpers.fake_power_supply(self.sys, battery={"charge_control_start_threshold": 50})   # TLP, say
        root.set_limit(100, self.sys, self.etc)
        self.assertEqual(self.start(), 50)

    def test_probe_leaves_the_start_alone(self):
        self.laptop(charge_control_start_threshold=70)
        with mock.patch.object(root, "write_threshold", Firmware({60, 80, 100})):
            self.assertEqual(root.set_limit(75, self.sys, self.etc), 80)
        self.assertEqual((self.start(), self.threshold()), (70, 80))

    def test_empty_bay_is_not_a_battery(self):
        self.laptop()
        helpers.fake_power_supply(self.sys, extra={"BAT1": {"type": "Battery", "present": 0,
                                                           "charge_control_end_threshold": 100}})
        self.assertEqual(root.batteries(self.sys), [os.path.join(self.sys, "BATT")])

    def test_two_batteries_end_on_the_same_value(self):
        """BATT takes 75; BAT1's firmware takes only 60/80/100: once that is
        learned, both are written with 80."""
        self.laptop()
        helpers.fake_power_supply(self.sys, extra={"BAT1": {"type": "Battery", "capacity": 50,
                                                           "charge_control_end_threshold": 100}})
        with mock.patch.object(root, "write_threshold", Firmware({60, 80, 100}, only={"BAT1"})):
            self.assertEqual(root.set_limit(75, self.sys, self.etc), 80)
        self.assertEqual((self.threshold("BATT"), self.threshold("BAT1")), (80, 80))

    def test_two_batteries(self):
        self.laptop()
        helpers.fake_power_supply(self.sys, extra={"BAT1": {"type": "Battery", "capacity": 50,
                                                           "charge_control_end_threshold": 100}})
        self.assertEqual(root.set_limit(60, self.sys, self.etc), 60)
        self.assertEqual(self.threshold("BATT"), 60)
        self.assertEqual(self.threshold("BAT1"), 60)


class HelperApply(Scratch):
    def save(self, text):
        os.makedirs(self.etc, exist_ok=True)
        with open(os.path.join(self.etc, "charge-limit"), "w") as handle:
            handle.write(text)

    def test_nothing_saved_writes_nothing(self):
        self.laptop(charge_control_end_threshold=100)
        with mock.patch.object(root, "write_threshold") as write:
            self.assertEqual(root.apply(self.sys, self.etc, sleep=lambda s: None), 0)
        write.assert_not_called()
        self.assertEqual(self.threshold(), 100)

    def test_garbage_saved_writes_nothing(self):
        self.laptop()
        self.save("eighty\n")
        self.assertEqual(root.apply(self.sys, self.etc, sleep=lambda s: None), 0)
        self.assertEqual(self.threshold(), 100)

    def test_saved_limit_written(self):
        self.laptop()
        self.save("80\n")
        self.assertEqual(root.apply(self.sys, self.etc, sleep=lambda s: None), 0)
        self.assertEqual(self.threshold(), 80)

    def test_switch_appears_late(self):
        self.save("60\n")
        naps = []

        def sleep(seconds):
            naps.append(seconds)
            if len(naps) == 3:          # the vendor driver hooks into the battery 3 s in
                self.laptop()
        self.assertEqual(root.apply(self.sys, self.etc, sleep=sleep), 0)
        self.assertEqual(len(naps), 3)
        self.assertEqual(self.threshold(), 60)

    def test_switch_never_appears(self):
        """Nothing to apply it to (battery swapped, driver not loaded): not a
        failure, so the unit does not show as failed at every boot."""
        self.save("60\n")
        naps = []
        self.assertEqual(root.apply(self.sys, self.etc, wait_s=5, sleep=naps.append), 0)
        self.assertEqual(len(naps), 5)
        self.assertTrue(any("nothing to apply it to" in line for line in self.logs))

    def test_transient_failure_after_resume(self):
        self.laptop()
        self.save("75\n")
        fw = Firmware(range(0, 101), flaky=3)
        with mock.patch.object(root, "write_threshold", fw):
            self.assertEqual(root.apply(self.sys, self.etc, sleep=lambda s: None), 0)
        self.assertEqual(self.threshold(), 75)
        self.assertEqual(self.saved(), "75\n")
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))

    def test_apply_never_probes_or_rewrites(self):
        """A refusal at boot: retried, then given up -- the saved limit and
        the choices stay as the user left them."""
        self.laptop()
        self.save("75\n")
        fw = Firmware({60, 80, 100})
        with mock.patch.object(root, "write_threshold", fw):
            self.assertEqual(root.apply(self.sys, self.etc, sleep=lambda s: None), 1)
        self.assertEqual(fw.ends(), [75] * root.APPLY_TRIES)
        self.assertEqual(self.saved(), "75\n")
        self.assertFalse(os.path.exists(os.path.join(self.etc, "charge-limit-choices")))

    def test_apply_snaps_on_asus(self):
        self.laptop()
        self.asus()
        self.save("75\n")
        self.assertEqual(root.apply(self.sys, self.etc, sleep=lambda s: None), 0)
        self.assertEqual(self.threshold(), 80)
        self.assertEqual(self.saved(), "75\n")                   # kept: snapped on the way only

    def test_main(self):
        self.laptop()
        sleep = lambda s: None  # noqa: E731
        self.assertEqual(root.main(["set", "80"], self.sys, self.etc, sleep), 0)
        self.assertEqual(self.threshold(), 80)
        for argv in (["set", "30"], ["set", "abc"], ["set"], ["set", "80", "90"], [], ["status"], ["apply", "x"]):
            self.assertEqual(root.main(argv, self.sys, self.etc, sleep), 2, argv)
        self.assertEqual(self.threshold(), 80)
        self.assertEqual(root.main(["apply"], self.sys, self.etc, sleep), 0)


# -- the files that wire it up ---------------------------------------------------------
class Wiring(unittest.TestCase):
    def rule_pattern(self):
        rule = read(os.path.join(SYSTEM, "50-atrium-charge-limit.rules"))
        js = re.search(r"/(\^charge-limit@.*?\$)/\.test", rule).group(1)
        return rule, re.compile(js.replace("$", r"\Z"))   # JS $ (no m flag) is the very end

    def test_polkit_rule(self):
        rule, pattern = self.rule_pattern()
        for n in range(50, 101):
            self.assertTrue(pattern.match(f"charge-limit@{n}.service"), n)
        for unit in ("charge-limit@49.service", "charge-limit@101.service", "charge-limit@8.service",
                     "charge-limit@080.service", "charge-limit@80.service\n", "charge-limit.service",
                     "charge-limit@80.timer", "xcharge-limit@80.service", "charge-limit@80x.service",
                     "charge-limit@-80.service", "charge-limit@80.service.d", "sshd.service"):
            self.assertIsNone(pattern.match(unit), repr(unit))
        for needed in ('action.lookup("verb") === "start"', "subject.local", "subject.active",
                       '"org.freedesktop.systemd1.manage-units"'):
            self.assertIn(needed, rule)

    def test_rule_and_helper_agree(self):
        """Whatever the rule lets through, the helper takes; nothing else."""
        _, pattern = self.rule_pattern()
        for n in list(range(0, 120)) + [999]:
            self.assertEqual(bool(pattern.match(f"charge-limit@{n}.service")), root.parse_limit(str(n)) is not None, n)

    def test_units(self):
        boot = read(os.path.join(SYSTEM, "charge-limit.service"))
        template = read(os.path.join(SYSTEM, "charge-limit@.service"))
        self.assertIn("ExecStart=/usr/local/libexec/charge-limit apply", boot)
        self.assertIn("ExecStart=/usr/local/libexec/charge-limit set %i", template)
        wanted = re.search(r"^WantedBy=(.*)$", boot, re.M).group(1).split()
        after = re.search(r"^After=(.*)$", boot, re.M).group(1).split()
        for target in ("multi-user.target", "suspend.target", "hibernate.target", "hybrid-sleep.target",
                       "suspend-then-hibernate.target"):
            self.assertIn(target, wanted)
            self.assertIn(target, after)
        for unit in (boot, template):
            self.assertIn("Type=oneshot", unit)
            self.assertIn("ConfigurationDirectory=atrium", unit)
            self.assertIn("ProtectSystem=strict", unit)
            self.assertNotRegex(unit, r"(?m)^ProtectKernelTunables=")   # would make /sys read-only
            self.assertNotRegex(unit, r"(?m)^RemainAfterExit=yes")      # each start must run again
        self.assertNotIn("[Install]", template)                          # started on demand, never enabled

    def test_install_scripts(self):
        sub = read(os.path.join(SYSTEM, "install.sh"))
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(SYSTEM, "install.sh")]).returncode, 0)
        check, first_install = sub.index("charge_control_end_threshold ]]"), sub.index("install -D")
        self.assertLess(check, first_install)            # no switch: exits before installing anything
        self.assertIn("nothing to do", sub[check:first_install])
        for f in ("charge-limit", "charge-limit.service", "charge-limit@.service", "50-atrium-charge-limit.rules"):
            self.assertIn(f'"$here/{f}"', sub)
        top = read(os.path.join(REPO, "install.sh"))
        line = top.index('run sudo "$REPO/system/charge-limit/install.sh"')
        gate = top.rindex("compgen -G '/sys/class/power_supply/*/charge_control_end_threshold'", 0, line)
        self.assertNotIn("\nfi\n", top[gate:line])                # a desktop: no sudo call at all
        # --limit is checked before anything else happens (it ends up in a
        # unit name), with the same digits as the polkit rule.
        self.assertLess(sub.index("(5[0-9]|[6-9][0-9]|100)"), sub.index("for bat in"))
        for argv in (["--limit"], ["--limit", "80%"], ["--limit", "abc"], ["--limit", "080"],
                     ["--limit", "49"], ["--bogus"]):
            out = subprocess.run(["bash", os.path.join(SYSTEM, "install.sh")] + argv,
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(out.returncode, 2, argv)
            self.assertIn("usage", out.stderr, argv)
        for f in ("charge-limit", "install.sh"):
            self.assertTrue(os.access(os.path.join(SYSTEM, f), os.X_OK), f)
        self.assertTrue(read(HELPER).startswith("#!/usr/bin/python3 -I\n"))    # isolated: no user site, no PYTHON*


# -- the session's charge-limit.py ----------------------------------------------------
class Session(Scratch):
    def setUp(self):
        super().setUp()
        for name, value in (("CONF_DIR", self.etc), ("SAVED_FILE", os.path.join(self.etc, "charge-limit")),
                            ("CHOICES_FILE", os.path.join(self.etc, "charge-limit-choices")),
                            ("UNIT_FILE", os.path.join(self.dir, "charge-limit@.service"))):
            patcher = mock.patch.object(cl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        if os.path.exists(ps.SETTINGS_FILE):
            os.remove(ps.SETTINGS_FILE)
        self.calls = []

    def install(self):
        with open(cl.UNIT_FILE, "w") as handle:
            handle.write("[Service]\n")

    def choices(self, text):
        os.makedirs(self.etc, exist_ok=True)
        with open(cl.CHOICES_FILE, "w") as handle:
            handle.write(text)

    def recorder(self, code=0, stderr=""):
        def run(argv, timeout=10, **kw):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, code, "", stderr)
        return run

    def through_helper(self):
        """systemctl start charge-limit@N.service, as systemd would run it:
        the root helper's main() with N, on the fake tree."""
        def run(argv, timeout=10, **kw):
            self.calls.append(argv)
            unit = re.fullmatch(r"charge-limit@(.*)\.service", argv[2]).group(1)
            code = root.main(["set", unit], self.sys, self.etc, sleep=lambda s: None)
            return subprocess.CompletedProcess(argv, code, "", "" if code == 0 else "Job failed")
        return run

    def test_status_desktop(self):
        s = cl.status()         # helpers.py: no power supplies at all
        self.assertEqual((s["supported"], s["limit"], s["saved"], s["choices"], s["fixed"], s["battery"]),
                         (False, None, None, [], False, None))
        self.assertEqual(s["setting"], 100)
        for key in ("supported", "installed", "limit", "saved", "choices", "fixed", "range", "battery", "setting"):
            self.assertIn(key, s)

    def test_status_laptop(self):
        self.laptop(charge_control_end_threshold=75)
        s = cl.status(self.sys)
        self.assertTrue(s["supported"])
        self.assertFalse(s["installed"])
        self.assertEqual(s["limit"], 75)
        self.assertEqual(s["choices"], [50, 60, 70, 75, 80, 90, 100])    # the presets, plus what is set
        self.assertFalse(s["fixed"])
        self.assertEqual(s["battery"]["name"], "BATT")
        self.choices("60 80 100\n")
        os.makedirs(self.etc, exist_ok=True)
        with open(cl.SAVED_FILE, "w") as handle:
            handle.write("80\n")
        s = cl.status(self.sys)
        self.assertEqual((s["choices"], s["fixed"], s["saved"]), ([60, 80, 100], True, 80))

    def test_status_mirrors_the_saved_limit(self):
        """/etc/atrium/charge-limit is the truth: install.sh --limit 80, or a
        lost battery.json, still ends with setting 80."""
        self.laptop(charge_control_end_threshold=80)
        os.makedirs(self.etc, exist_ok=True)
        with open(cl.SAVED_FILE, "w") as handle:
            handle.write("80\n")
        self.assertEqual(cl.status(self.sys)["setting"], 80)
        self.assertEqual(ps.load_settings()["charge_limit"], 80)

    def test_status_asus(self):
        self.laptop()
        self.asus()
        self.install()
        s = cl.status(self.sys)
        self.assertEqual((s["choices"], s["fixed"]), ([60, 80, 100], True))
        cl.set_limit("75", self.sys, run=self.recorder())
        self.assertEqual(self.calls[-1][2], "charge-limit@80.service")
        self.choices("any\n")
        s = cl.status(self.sys)
        self.assertEqual((s["choices"], s["fixed"]), (cl.PRESETS, False))

    def test_switch_on_the_second_battery(self):
        self.laptop(charge_control_end_threshold=None)
        # BATT (first by name, the one shown) has no switch; BATX has.
        helpers.fake_power_supply(self.sys, extra={"BATX": {"type": "Battery", "capacity": 50,
                                                           "charge_control_end_threshold": 90}})
        s = cl.status(self.sys)
        self.assertEqual((s["supported"], s["limit"], s["battery"]["name"]), (True, 90, "BATT"))

    def test_status_battery_without_switch(self):
        self.laptop(charge_control_end_threshold=None)
        s = cl.status(self.sys)
        self.assertEqual((s["supported"], s["choices"], s["limit"]), (False, [], None))

    def test_set_rejects_bad_numbers(self):
        self.laptop()
        self.install()
        for value in ("30", "101", "abc", "", "80%", True):
            code, result = cl.set_limit(value, self.sys, run=self.recorder())
            self.assertEqual(code, 2, value)
            self.assertFalse(result["ok"])
        self.assertEqual(self.calls, [])

    def test_set_without_switch(self):
        self.install()
        code, result = cl.set_limit("80", run=self.recorder())          # a desktop
        self.assertEqual(code, 1)
        self.assertIn("cannot stop charging", result["error"])
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(ps.SETTINGS_FILE))

    def test_set_without_root_side(self):
        self.laptop()
        code, result = cl.set_limit("80", self.sys, run=self.recorder())
        self.assertEqual(code, 1)
        self.assertIn("system/charge-limit/install.sh", result["error"])
        self.assertEqual(self.calls, [])

    def test_set_starts_the_unit(self):
        self.laptop()
        self.install()
        code, result = cl.set_limit("80", self.sys, run=self.recorder())
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [["systemctl", "start", "charge-limit@80.service"]])
        self.assertTrue(result["ok"])

    def test_set_snaps_before_asking(self):
        self.laptop()
        self.install()
        self.choices("60 80 100\n")
        cl.set_limit("75", self.sys, run=self.recorder())
        cl.set_limit("70", self.sys, run=self.recorder())
        self.assertEqual([c[2] for c in self.calls], ["charge-limit@80.service", "charge-limit@60.service"])

    def test_set_failure(self):
        self.laptop()
        self.install()
        code, result = cl.set_limit("80", self.sys, run=self.recorder(1, "Failed to start: Access denied\n"))
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "Failed to start: Access denied")
        self.assertFalse(os.path.exists(ps.SETTINGS_FILE))              # nothing mirrored
        code, result = cl.set_limit("80", self.sys, run=lambda *a, **k: None)     # no systemctl
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "systemctl failed")

    def test_end_to_end_mirrors_what_the_firmware_took(self):
        self.laptop()
        self.install()
        code, result = cl.set_limit("80", self.sys, run=self.through_helper())
        self.assertEqual(code, 0)
        self.assertEqual((result["limit"], result["saved"], result["setting"]), (80, 80, 80))
        self.assertEqual(ps.load_settings()["charge_limit"], 80)
        self.assertEqual(self.threshold(), 80)
        # Firmware with fixed values, met for the first time: the helper
        # learns them and snaps further than the session knew to.
        with mock.patch.object(root, "write_threshold", Firmware({60, 80, 100})):
            code, result = cl.set_limit("65", self.sys, run=self.through_helper())
        self.assertEqual(code, 0)
        self.assertEqual(self.calls[-1][2], "charge-limit@65.service")
        self.assertEqual((result["limit"], result["saved"], result["fixed"]), (60, 60, True))
        self.assertEqual(ps.load_settings()["charge_limit"], 60)
        # ... and from then on the session snaps itself.
        cl.set_limit("90", self.sys, run=self.through_helper())
        self.assertEqual(self.calls[-1][2], "charge-limit@80.service")

    def test_end_to_end_firmware_minimum(self):
        self.laptop()
        self.install()
        with mock.patch.object(root, "write_threshold", Firmware(range(55, 101))):
            code, result = cl.set_limit("50", self.sys, run=self.through_helper())
        self.assertEqual(code, 0)
        self.assertEqual((result["limit"], result["saved"], result["setting"], result["fixed"]), (55, 55, 55, False))

    def test_main_prints_json(self):
        self.laptop()
        with mock.patch("builtins.print") as printed:
            self.assertEqual(cl.main(["status"]), 0)
        json.loads(printed.call_args_list[0].args[0])
        with mock.patch("builtins.print") as printed:
            self.assertEqual(cl.main(["set", "20"]), 2)
        self.assertFalse(json.loads(printed.call_args_list[0].args[0])["ok"])
        with mock.patch("builtins.print"):
            self.assertEqual(cl.main([]), 2)
            self.assertEqual(cl.main(["set"]), 2)

    def test_status_command_runs(self):
        """The real script, as Settings runs it: JSON on stdout, on a desktop here."""
        out = subprocess.run([os.path.join(helpers.SCRIPTS, "charge-limit.py"), "status"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(json.loads(out.stdout)["supported"])


if __name__ == "__main__":
    unittest.main()
