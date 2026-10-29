"""doctor.py's reading of a wanted service (service_state): a daemon that
stopped is a failure, a oneshot, a RemainAfterExit unit that exited cleanly
and one whose condition said "not now" are not. And the backup line comes
from backup.py's saved state, absent when no backup is set up."""
import os
import unittest
from unittest import mock

import helpers

D = helpers.import_script("doctor.py", "doctor")


class ServiceState(unittest.TestCase):
    def test_running_and_failed(self):
        self.assertEqual(D.service_state({"ActiveState": "active", "SubState": "running"}), ("ok", "running"))
        self.assertEqual(D.service_state({"ActiveState": "failed", "Result": "exit-code"}),
                         ("fail", "failed (exit-code)"))

    def test_a_stopped_daemon_fails(self):
        level, text = D.service_state({"ActiveState": "inactive", "Type": "simple", "Result": "success",
                                       "RemainAfterExit": "no", "ConditionResult": "yes"})
        self.assertEqual((level, text), ("fail", "not running (inactive)"))

    def test_condition_not_met_is_ok(self):
        self.assertEqual(D.service_state({"ActiveState": "inactive", "Type": "simple",
                                          "ConditionResult": "no"})[0], "ok")

    def test_oneshot_and_remain_after_exit(self):
        self.assertEqual(D.service_state({"ActiveState": "inactive", "Type": "oneshot"})[0], "ok")
        self.assertEqual(D.service_state({"ActiveState": "inactive", "Type": "simple", "RemainAfterExit": "yes",
                                          "Result": "success"}), ("ok", "ran and exited"))
        self.assertEqual(D.service_state({"ActiveState": "inactive", "Type": "simple", "RemainAfterExit": "yes",
                                          "Result": "exit-code"})[0], "fail")
        self.assertEqual(D.service_state({"ActiveState": "active", "SubState": "exited"}), ("ok", "exited"))


class BackupLine(unittest.TestCase):
    def test_no_line_when_not_set_up(self):
        missing = os.path.join(helpers.SCRATCH, "config", "no-backup.conf")
        with mock.patch.dict(os.environ, {"HYPR_BACKUP_CONF": missing}):
            self.assertIsNone(D.check_backup())

    def test_the_saved_state_speaks(self):
        conf = os.path.join(helpers.SCRATCH, "config", "doctor-backup.conf")
        with open(conf, "w") as handle:
            handle.write("repo=/nowhere\n")
        with mock.patch.dict(os.environ, {"HYPR_BACKUP_CONF": conf}), \
                mock.patch("shutil.which", lambda name: "/usr/bin/" + name if name == "restic" else None):
            got = D.check_backup()
        self.assertEqual((got["name"], got["level"]), ("backup", "warn"))
        self.assertIn("no backup has run yet", got["text"])


if __name__ == "__main__":
    unittest.main()
