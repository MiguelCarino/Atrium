"""software-updates.py (Settings > Software updates): the parsing of what
updates.sh, dnf, needs-restarting, fwupd and safe-upgrade.sh report, and the
one write it makes -- the pill's check interval in the waybar config, done on
a scratch copy here."""
import json
import os
import unittest
from unittest import mock

import helpers

su = helpers.import_script("software-updates.py")

CONFIG = """{
    // the clock
    "custom/clock": {
        "interval": 60,
        "exec": "clock.py"
    },
    // Left: the updates panel. { braces in a comment outside the block }
    "custom/updates": {
        "tooltip": false,
        "format": "{}",
        "interval": 3600,
        "exec": "$HOME/.config/waybar/scripts/updates.sh",
        "signal": 8
    },
    "custom/weather": { "interval": 1800 }
}
"""


class Cache(unittest.TestCase):
    def test_parse(self):
        text = ("checked\t1700000000\nstatus\tok\npkg\tkernel-core.x86_64\t7.2.12-200.fc44\n"
                "pkg\tgst.x86_64\t1:1.28.8-1.fc44\nflatpak\torg.example.App\nflatpak\t\n")
        data = su.parse_cache(text)
        self.assertEqual(data["checked"], 1700000000)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["pkgs"], [("kernel-core.x86_64", "7.2.12-200.fc44"), ("gst.x86_64", "1:1.28.8-1.fc44")])
        self.assertEqual(data["flatpaks"], ["org.example.App"])

    def test_missing_and_error(self):
        self.assertIsNone(su.parse_cache(None))
        self.assertEqual(su.parse_cache("checked\tx\nstatus\terror\t1\n")["status"], "error")


class Security(unittest.TestCase):
    def test_nevra_key(self):
        self.assertEqual(su.nevra_key("PackageKit-command-not-found-1.4.0-1.fc44.x86_64"),
                         "PackageKit-command-not-found.x86_64")
        self.assertEqual(su.nevra_key("tzdata-2026a-1.fc44.noarch"), "tzdata.noarch")
        self.assertEqual(su.nevra_key("gst-1:1.2-3.fc44.x86_64"), "gst.x86_64")
        self.assertIsNone(su.nevra_key("garbage"))

    def test_worst_severity_wins(self):
        marks = su.security_marks([
            {"name": "A", "type": "security", "severity": "Low", "nevra": "foo-1-1.fc44.x86_64"},
            {"name": "B", "type": "security", "severity": "Important", "nevra": "foo-1.1-1.fc44.x86_64"},
            {"name": "C", "type": "security", "severity": "Moderate", "nevra": "foo-1.2-1.fc44.x86_64"},
            {"name": "D", "type": "bugfix", "severity": "None", "nevra": "bar-1-1.fc44.x86_64"},
            {"name": "E", "type": "security", "severity": "", "nevra": "baz-1-1.fc44.noarch"}])
        self.assertEqual(marks["foo.x86_64"], {"severity": "Important", "advisory": "B"})
        self.assertNotIn("bar.x86_64", marks)
        self.assertEqual(marks["baz.noarch"]["severity"], "None")
        self.assertEqual(su.security_marks(None), {})


class History(unittest.TestCase):
    ROWS = [{"id": 5, "command_line": "dnf install update-motd", "end_time": 50, "status": "Ok"},
            {"id": 4, "command_line": "dnf -y upgrade --refresh", "end_time": 40, "status": "Error"},
            {"id": 3, "command_line": "/usr/bin/dnf5 update --refresh", "end_time": 30, "status": "Ok"},
            {"id": 2, "command_line": "", "end_time": 20, "status": "Ok"}]

    def test_subcommand(self):
        self.assertEqual(su.dnf_subcommand("dnf -y upgrade --refresh"), "upgrade")
        self.assertEqual(su.dnf_subcommand("dnf install update-motd"), "install")
        self.assertEqual(su.dnf_subcommand(""), "")

    def test_last_update_skips_installs_and_failures(self):
        upd, other = su.last_update(self.ROWS)
        self.assertEqual(upd["id"], 3)
        self.assertEqual(other["id"], 5)
        self.assertEqual(su.last_update([]), (None, None))

    def test_describe(self):
        self.assertEqual(su.describe("dnf -y install --nogpgcheck --disablerepo=* "
                                     "/tmp/akmods.X/results/kmod-nvidia-7.2.11-200.fc44.x86_64-615.78.08-1.fc44.x86_64.rpm"),
                         "install kmod-nvidia (akmods)")
        self.assertEqual(su.describe("dnf update --refresh"), "update (everything)")
        self.assertEqual(su.describe("dnf upgrade firefox"), "upgrade firefox")
        self.assertEqual(su.describe(None), "PackageKit (Software)")


class Reboot(unittest.TestCase):
    def test_needs_restarting(self):
        out = "Core libraries or services have been updated since boot-up:\n  * glibc\n  * systemd\n\nReboot is required"
        self.assertEqual(su.reboot_verdict(1, out, "k1", "k1"), {"needed": True, "reasons": ["glibc", "systemd"]})
        self.assertEqual(su.reboot_verdict(0, "", "k1", "k1"), {"needed": False, "reasons": []})
        self.assertIsNone(su.reboot_verdict(127, "", "k1", "k1")["needed"])

    def test_new_kernel_means_reboot(self):
        v = su.reboot_verdict(0, "", "7.2.12", "7.2.11")
        self.assertTrue(v["needed"])
        self.assertIn("7.2.12", v["reasons"][0])

    def test_nvidia(self):
        self.assertEqual(su.nvidia_verdict(None, None), "none")
        self.assertEqual(su.nvidia_verdict("615.78.08", None), "missing")
        self.assertEqual(su.nvidia_verdict("615.78.08", "610.1"), "mismatch")
        self.assertEqual(su.nvidia_verdict("615.78.08", "615.78.08"), "ok")

    def test_record(self):
        rec = su.parse_record("finished\t1700\nnvidia\tmissing\nreboot\tunsafe\nmodule\t\n")
        self.assertEqual(rec, {"finished": 1700, "nvidia": "missing", "reboot": "unsafe", "module": ""})
        self.assertIsNone(su.parse_record("nvidia\tok\n"))
        self.assertIsNone(su.parse_record(None))


class Interval(unittest.TestCase):
    def test_get(self):
        self.assertEqual(su.get_interval(CONFIG), 3600)
        self.assertIsNone(su.get_interval("{}"))
        self.assertEqual(su.get_interval('{"custom/updates": {"exec": "x"}}'), "once")

    def test_set_touches_only_the_pill(self):
        new = su.set_interval(CONFIG, 21600)
        self.assertEqual(su.get_interval(new), 21600)
        self.assertEqual(new.replace('"interval": 21600', '"interval": 3600'), CONFIG)
        once = su.set_interval(CONFIG, "once")
        self.assertIn('"interval": "once"', once)
        self.assertEqual(su.get_interval(once), "once")
        self.assertEqual(su.get_interval(su.set_interval(once, 3600)), 3600)

    def test_set_adds_a_missing_interval(self):
        text = '{\n    "custom/updates": {\n        "exec": "x"\n    }\n}\n'
        new = su.set_interval(text, 10800)
        self.assertEqual(su.get_interval(new), 10800)
        json.loads(new)
        with self.assertRaises(ValueError):
            su.set_interval("{}", 3600)

    def test_names(self):
        self.assertEqual(su.interval_value("6h"), 21600)
        self.assertEqual(su.interval_value("login"), "once")
        self.assertEqual(su.interval_value("once"), "once")
        self.assertEqual(su.interval_name(86400), "24h")
        self.assertEqual(su.interval_name("once"), "login")
        self.assertEqual(su.interval_name(5400), "90 min")
        with self.assertRaises(ValueError):
            su.interval_value("5m")

    def test_write_on_a_scratch_config_never_reloads(self):
        path = os.path.join(helpers.SCRATCH, "waybar-config")
        with open(path, "w") as handle:
            handle.write(CONFIG)
        os.chmod(path, 0o755)
        with mock.patch.object(su, "WAYBAR_CONFIG", path), \
                mock.patch.dict(os.environ, {"SOFTWARE_UPDATES_WAYBAR_CONFIG": path}), \
                mock.patch.object(su, "run") as run:
            self.assertEqual(su.write_interval("12h"), 43200)
            run.assert_not_called()
        with open(path) as handle:
            self.assertEqual(su.get_interval(handle.read()), 43200)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o755)

    def test_live_config_restarts_the_bar_never_sigusr2(self):
        """The live path (here pointed at a scratch file, with the scratch env
        var unset and run() mocked) restarts the bar with bar-restart.sh when
        waybar.service is up -- never `systemctl reload` (SIGUSR2 can abort
        waybar 0.15) -- and leaves a stopped bar stopped."""
        path = os.path.join(helpers.SCRATCH, "waybar-config-live")
        for active, expect_restart in ((0, True), (3, False)):
            with open(path, "w") as handle:
                handle.write(CONFIG)
            env = {k: v for k, v in os.environ.items() if k != "SOFTWARE_UPDATES_WAYBAR_CONFIG"}
            with mock.patch.object(su, "WAYBAR_CONFIG", path), mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(su, "run", return_value=(active, "")) as run:
                su.write_interval("6h")
            calls = [c.args for c in run.call_args_list]
            self.assertFalse(any("reload" in c for c in calls))
            self.assertEqual((su.BAR_RESTART,) in calls, expect_restart)

    def test_the_real_config_parses(self):
        """Read only: the live waybar config has the block this edits."""
        path = os.path.expanduser("~/.config/waybar/config")
        if not os.path.exists(path):
            self.skipTest("no waybar config")
        with open(path) as handle:
            text = handle.read()
        self.assertIsNotNone(su.get_interval(text))
        self.assertEqual(len(su.set_interval(text, 7200)) - len(text),
                         len("7200") - len(str(su.get_interval(text)).replace("once", '"once"')))


class Firmware(unittest.TestCase):
    def test_parse(self):
        text = json.dumps({"Devices": [{"Name": "SSD", "Vendor": "X", "Version": "1.0",
                                        "Releases": [{"Version": "1.1", "Summary": "Firmware for SSD"}]},
                                       {"Name": "Mouse", "Version": "2"}]})
        self.assertEqual(su.parse_firmware(text), [
            {"device": "SSD", "vendor": "X", "current": "1.0", "new": "1.1", "summary": "Firmware for SSD"},
            {"device": "Mouse", "vendor": "", "current": "2", "new": "", "summary": ""}])
        self.assertEqual(su.parse_firmware('{"Devices": []}'), [])
        self.assertEqual(su.parse_firmware("not json"), [])


if __name__ == "__main__":
    unittest.main()
