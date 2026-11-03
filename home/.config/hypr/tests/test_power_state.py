"""power_state.py: which supplies are the machine's own, on_battery /
ac_online / has_battery, the battery's numbers in both unit families
(charge + current, energy + power), the saver's state file, frugal()'s
cache and period(), and the battery settings with every key checked.

Hermetic: every test builds its own fake power_supply tree
(helpers.fake_power_supply) and passes it as root= or ATRIUM_POWER_SUPPLY;
helpers.py points ATRIUM_POWER_SUPPLY at a missing folder for the rest of
the run, so nothing here reads this machine's /sys."""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers

ps = helpers.import_script("power_state.py", "power_state")


class Tree(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ps-", dir=helpers.SCRATCH)
        self.root = os.path.join(self.dir, "power_supply")
        ps.reset_cache()

    def tree(self, **kw):
        return helpers.fake_power_supply(self.root, **kw)


class Desktop(Tree):
    def test_no_folder_is_a_desktop(self):
        missing = os.path.join(self.dir, "nothing")
        self.assertFalse(ps.has_battery(missing))
        self.assertFalse(ps.on_battery(missing))
        self.assertIsNone(ps.ac_online(missing))
        self.assertIsNone(ps.battery(missing))

    def test_default_test_env_is_a_desktop(self):
        """helpers.py's ATRIUM_POWER_SUPPLY: no battery for every other test."""
        self.assertFalse(ps.has_battery())
        self.assertFalse(ps.on_battery())
        self.assertFalse(ps.frugal(fresh=True))
        self.assertEqual(ps.period(1, 5), 1)

    def test_wireless_mouse_is_not_a_battery(self):
        self.tree(extra={"hidpp_battery_0": {"type": "Battery", "scope": "Device",
                                             "status": "Discharging", "capacity": 30}})
        self.assertFalse(ps.has_battery(self.root))
        self.assertFalse(ps.on_battery(self.root))
        self.assertIsNone(ps.battery(self.root))

    def test_empty_bay_is_not_a_battery(self):
        self.tree(battery={"present": 0})
        self.assertFalse(ps.has_battery(self.root))

    def test_desktop_with_mains_only(self):
        self.tree(ac=True)
        self.assertFalse(ps.has_battery(self.root))
        self.assertFalse(ps.on_battery(self.root))
        self.assertTrue(ps.ac_online(self.root))


class OnBattery(Tree):
    def test_unplugged_discharging(self):
        self.tree(battery={"status": "Discharging"}, ac=False)
        self.assertTrue(ps.has_battery(self.root))
        self.assertTrue(ps.on_battery(self.root))
        self.assertFalse(ps.ac_online(self.root))

    def test_charging(self):
        self.tree(battery={"status": "Charging"}, ac=True)
        self.assertFalse(ps.on_battery(self.root))
        self.assertTrue(ps.ac_online(self.root))

    def test_held_at_limit_on_charger(self):
        self.tree(battery={"status": "Not charging"}, ac=True)
        self.assertFalse(ps.on_battery(self.root))

    def test_discharging_but_mains_online_is_not_on_battery(self):
        """A heavy load on the charger, or the status lagging the plug."""
        self.tree(battery={"status": "Discharging"}, ac=True)
        self.assertFalse(ps.on_battery(self.root))

    def test_no_mains_entry_discharging(self):
        self.tree(battery={"status": "Discharging"})
        self.assertTrue(ps.on_battery(self.root))
        self.assertIsNone(ps.ac_online(self.root))

    def test_usb_supplies_count_only_without_mains(self):
        usb = {"ucsi-source-psy-USBC000:001": {"type": "USB", "scope": "System", "online": 1}}
        self.tree(battery={"status": "Charging"}, extra=usb)
        self.assertTrue(ps.ac_online(self.root))
        self.tree(ac=False)     # now there is a Mains supply: it decides
        self.assertFalse(ps.ac_online(self.root))

    def test_usb_device_scope_ignored(self):
        usb = {"phone": {"type": "USB", "scope": "Device", "online": 1}}
        self.tree(battery={"status": "Discharging"}, extra=usb)
        self.assertIsNone(ps.ac_online(self.root))

    def test_env_var_is_read_per_call(self):
        self.tree(battery={"status": "Discharging"}, ac=False)
        with mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": self.root}):
            self.assertTrue(ps.on_battery())
        self.assertFalse(ps.on_battery())


class Battery(Tree):
    def test_charge_units(self):
        """This ASUS: charge_* uAh, current_now uA, voltage_now uV."""
        self.tree(battery={"status": "Discharging", "capacity": 83, "current_now": 900000,
                           "voltage_now": 11978000, "charge_now": 2471000, "charge_full": 2978000,
                           "charge_full_design": 5260000, "cycle_count": 255}, ac=False)
        b = ps.battery(self.root)
        self.assertEqual(b["name"], "BATT")
        self.assertEqual(b["capacity"], 83)
        self.assertEqual(b["status"], "Discharging")
        self.assertAlmostEqual(b["watts"], 10.78, places=2)
        self.assertEqual(b["health_pct"], 57)
        self.assertEqual(b["cycles"], 255)
        self.assertEqual(b["charge_limit"], 100)
        self.assertTrue(b["charge_limit_supported"])
        self.assertEqual(b["minutes_left"], int(2471000 / 900000 * 60))
        self.assertIsNone(b["minutes_to_full"])
        self.assertEqual(set(b), {"name", "capacity", "status", "watts", "health_pct", "cycles",
                                  "charge_limit", "charge_limit_supported", "minutes_left",
                                  "minutes_to_full"})

    def test_energy_units(self):
        self.tree(battery={"status": "Charging", "capacity": 50, "current_now": None, "voltage_now": None,
                           "charge_now": None, "charge_full": None, "charge_full_design": None,
                           "power_now": 20000000, "energy_now": 25000000, "energy_full": 50000000,
                           "energy_full_design": 60000000, "cycle_count": None,
                           "charge_control_end_threshold": None})
        b = ps.battery(self.root)
        self.assertEqual(b["watts"], 20.0)
        self.assertEqual(b["health_pct"], 83)
        self.assertIsNone(b["cycles"])
        self.assertIsNone(b["charge_limit"])
        self.assertFalse(b["charge_limit_supported"])
        self.assertEqual(b["minutes_to_full"], 75)
        self.assertIsNone(b["minutes_left"])

    def test_negative_current_and_zero_rate(self):
        self.tree(battery={"current_now": -1000000})
        self.assertGreater(ps.battery(self.root)["watts"], 0)
        self.tree(battery={"current_now": 0})
        b = ps.battery(self.root)
        self.assertEqual(b["watts"], 0.0)
        self.assertIsNone(b["minutes_left"])

    def test_missing_rates(self):
        self.tree(battery={"current_now": None, "voltage_now": None})
        b = ps.battery(self.root)
        self.assertIsNone(b["watts"])
        self.assertIsNone(b["minutes_left"])

    def test_capacity_worked_out_when_missing(self):
        self.tree(battery={"capacity": None, "charge_now": 1500000, "charge_full": 3000000})
        self.assertEqual(ps.battery(self.root)["capacity"], 50)

    def test_capacity_clamped_and_garbage(self):
        self.tree(battery={"capacity": 104})
        self.assertEqual(ps.battery(self.root)["capacity"], 100)
        self.tree(battery={"cycle_count": "n/a"})
        self.assertIsNone(ps.battery(self.root)["cycles"])

    def test_first_battery_by_name(self):
        self.tree(extra={"BAT1": {"type": "Battery", "status": "Full", "capacity": 99},
                         "BAT0": {"type": "Battery", "status": "Discharging", "capacity": 40}})
        b = ps.battery(self.root)
        self.assertEqual((b["name"], b["capacity"]), ("BAT0", 40))
        self.assertTrue(ps.on_battery(self.root))    # any discharging battery, no mains


class Saver(Tree):
    def write(self, data):
        with open(ps.SAVER_STATE, "w") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))

    def tearDown(self):
        try:
            os.remove(ps.SAVER_STATE)
        except OSError:
            pass
        ps.reset_cache()

    def test_saver_file(self):
        self.assertFalse(ps.saver_active())
        self.write({"active": True, "why": "manual", "since": 1})
        self.assertTrue(ps.saver_active())
        self.write({"active": False, "why": "", "since": 0})
        self.assertFalse(ps.saver_active())
        self.write({"active": "yes"})
        self.assertFalse(ps.saver_active())
        self.write("[1, 2")
        self.assertFalse(ps.saver_active())
        self.write([True])
        self.assertFalse(ps.saver_active())

    def test_frugal_from_saver_on_a_desktop(self):
        self.write({"active": True, "why": "manual", "since": 1})
        self.assertTrue(ps.frugal(fresh=True))
        self.assertEqual(ps.period(1, 5), 5)

    def test_frugal_from_battery(self):
        self.tree(battery={"status": "Discharging"}, ac=False)
        with mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": self.root}):
            self.assertTrue(ps.frugal(fresh=True))
            self.assertEqual(ps.period(2.0, 10.0), 10.0)

    def test_frugal_is_cached(self):
        clock = [1000.0]
        with mock.patch.object(ps.time, "monotonic", lambda: clock[0]):
            self.assertFalse(ps.frugal())
            self.write({"active": True})
            clock[0] += ps.FRUGAL_TTL_S - 1
            self.assertFalse(ps.frugal())                   # still the cached answer
            with mock.patch.object(ps, "on_battery", side_effect=AssertionError("read sysfs")):
                ps.frugal()                                   # no sysfs read inside the TTL
            clock[0] += 2
            self.assertTrue(ps.frugal())                    # expired: read again
            self.write({"active": False})
            self.assertTrue(ps.frugal())
            self.assertFalse(ps.frugal(fresh=True))
            self.write({"active": True})
            ps.reset_cache()
            self.assertTrue(ps.frugal())


class Settings(unittest.TestCase):
    def setUp(self):
        try:
            os.remove(ps.SETTINGS_FILE)
        except OSError:
            pass

    tearDown = setUp

    def test_path_is_under_state_home(self):
        self.assertEqual(ps.SETTINGS_FILE, os.path.join(os.environ["XDG_STATE_HOME"], "hypr", "battery.json"))
        self.assertEqual(ps.SAVER_STATE, os.path.join(os.environ["XDG_RUNTIME_DIR"], "battery-saver.json"))
        self.assertEqual(ps.POWER_STATE, os.path.join(os.environ["XDG_RUNTIME_DIR"], "power-state.json"))

    def test_defaults(self):
        self.assertEqual(ps.load_settings(), {"warn_at": [20, 10, 5], "saver_auto_at": 20,
                                              "saver_on_unplug": False, "charge_limit": 100})

    def test_defaults_not_shared(self):
        ps.load_settings()["warn_at"].append(1)
        self.assertEqual(ps.DEFAULTS["warn_at"], [20, 10, 5])

    def test_round_trip_and_merge(self):
        saved = ps.save_settings({"warn_at": [5, 15, 15], "saver_on_unplug": True})
        self.assertEqual(saved["warn_at"], [15, 5])
        self.assertTrue(saved["saver_on_unplug"])
        again = ps.save_settings({"charge_limit": 80})
        self.assertEqual(again, {"warn_at": [15, 5], "saver_auto_at": 20,
                                 "saver_on_unplug": True, "charge_limit": 80})
        self.assertEqual(ps.load_settings(), again)
        with open(ps.SETTINGS_FILE) as handle:
            self.assertEqual(json.load(handle), again)

    def test_bad_values_keep_current(self):
        ps.save_settings({"charge_limit": 80, "warn_at": [30]})
        out = ps.save_settings({"charge_limit": 40, "warn_at": [0, 10], "saver_auto_at": True,
                                "saver_on_unplug": "yes", "bogus": 1})
        self.assertEqual(out["charge_limit"], 80)
        self.assertEqual(out["warn_at"], [30])
        self.assertEqual(out["saver_auto_at"], 20)
        self.assertFalse(out["saver_on_unplug"])
        self.assertNotIn("bogus", out)

    def test_empty_warn_list_allowed(self):
        self.assertEqual(ps.save_settings({"warn_at": []})["warn_at"], [])

    def test_hand_edited_file(self):
        os.makedirs(os.path.dirname(ps.SETTINGS_FILE), exist_ok=True)
        with open(ps.SETTINGS_FILE, "w") as handle:
            json.dump({"warn_at": "20", "saver_auto_at": 0, "charge_limit": 101}, handle)
        out = ps.load_settings()
        self.assertEqual(out["warn_at"], [20, 10, 5])
        self.assertEqual(out["saver_auto_at"], 0)
        self.assertEqual(out["charge_limit"], 100)
        with open(ps.SETTINGS_FILE, "w") as handle:
            handle.write("{not json")
        self.assertEqual(ps.load_settings(), ps.DEFAULTS)


class NoForks(unittest.TestCase):
    def test_no_subprocess(self):
        """Cheap enough for every tick: the module never starts a process."""
        with open(os.path.join(helpers.SCRIPTS, "power_state.py")) as handle:
            source = handle.read()
        self.assertNotIn("subprocess", source)
        self.assertNotIn("import gi", source)


if __name__ == "__main__":
    unittest.main()
