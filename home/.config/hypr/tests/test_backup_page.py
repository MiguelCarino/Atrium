"""Settings > Storage > Backup (settings_pages/backup.py): the pure helpers
that turn `backup.py status --json` into the page's lines. Needs GTK to
import, not a display; skipped without it."""
import unittest

import helpers  # noqa: F401  (scratch XDG dirs, scripts on sys.path)

try:
    from settings_pages import backup as page
except Exception as exc:                                 # noqa: BLE001
    page = None
    WHY = str(exc)


@unittest.skipIf(page is None, "settings_pages.backup not importable")
class BackupPage(unittest.TestCase):
    def test_summary_not_installed_or_not_set_up(self):
        self.assertEqual(page.summary_text({"installed": [], "configured": False}), "needs restic or kopia")
        self.assertEqual(page.summary_text({"installed": ["restic"], "configured": False}), "not set up yet")

    def test_summary_configured(self):
        data = {"configured": True, "installed": ["restic"], "last_ok_text": "5 h ago",
                "repo_size_text": "2.1 GB", "timer": {"enabled": True}, "state": {"ok": True, "last_run": 1}}
        self.assertEqual(page.summary_text(data), "last good backup 5 h ago  ·  repository 2.1 GB  ·  every day")
        data["state"] = {"ok": False, "last_run": 1}
        data["timer"] = {}
        self.assertTrue(page.summary_text(data).startswith("the last run FAILED"))
        self.assertTrue(page.summary_text(data).endswith("not scheduled"))

    def test_missing_names_the_package(self):
        self.assertEqual(page.missing_text({"installed": ["kopia"]}), "")
        self.assertIn("sudo dnf install restic", page.missing_text({"installed": [], "package": "restic"}))

    def test_last_run_text(self):
        self.assertEqual(page.last_run_text({}), "No backup has run yet.")
        self.assertIn("boom", page.last_run_text({"last_run": 1, "ok": False, "error": "boom"}))
        text = page.last_run_text({"last_run": 1, "ok": True, "added": 1_500_000, "files": 3, "duration": 9,
                                   "warning": "some files could not be read"})
        self.assertIn("added 1.5 MB", text)
        self.assertIn("3 files", text)
        self.assertIn("Note: some files", text)

    def test_password_kind_and_tilde(self):
        self.assertEqual(page.password_kind("file:~/.pw"), "file")
        self.assertEqual(page.password_kind("keyring"), "keyring")
        self.assertEqual(page.password_kind(None), "keyring")
        self.assertEqual(page.tilde("/home/u/Docs", "/home/u"), "~/Docs")
        self.assertEqual(page.tilde("/srv/x", "/home/u"), "/srv/x")


if __name__ == "__main__":
    unittest.main()
