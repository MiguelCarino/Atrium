"""backup.py: the settings file, the restic / kopia commands and their
environment (the password never on a command line), reading their JSON,
and the age / health rules doctor.py and brief.py show.

Hermetic: HYPR_BACKUP_CONF and the state file point at a scratch folder;
nothing runs restic, kopia, secret-tool or systemctl (sh() is replaced
where a function would call it)."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers

B = helpers.import_script("backup.py")
NOW = 1_800_000_000
DAY = 86400


class Conf(unittest.TestCase):
    def test_defaults_when_empty(self):
        conf = B.parse_conf("")
        self.assertEqual(conf["engine"], "auto")
        self.assertEqual(conf["include"], B.DEFAULT_INCLUDE)
        self.assertEqual(conf["exclude"], B.DEFAULT_EXCLUDE)
        self.assertEqual((conf["keep_daily"], conf["keep_weekly"], conf["keep_monthly"]), (7, 4, 6))

    def test_round_trip(self):
        conf = B.parse_conf("repo=/mnt/disk/backup\ninclude=~/Work\nexclude=*.iso\nkeep_daily=3\n")
        self.assertEqual(B.parse_conf(B.render_conf(conf)), conf)
        self.assertEqual(conf["include"], ["~/Work"])
        self.assertEqual(conf["keep_daily"], 3)

    def test_empty_lists_stay_empty(self):
        conf = dict(B.parse_conf(""), include=[], exclude=[])
        again = B.parse_conf(B.render_conf(conf))
        self.assertEqual((again["include"], again["exclude"]), ([], []))

    def test_bad_values_ignored(self):
        conf = B.parse_conf("engine=borg\nkeep_daily=lots\nwhat=ever\n")
        self.assertEqual((conf["engine"], conf["keep_daily"]), ("auto", 7))

    def test_check_setting(self):
        self.assertEqual(B.check_setting("keep_weekly", "8"), 8)
        self.assertEqual(B.check_setting("password", "file:~/.pw"), "file:~/.pw")
        for key, value in (("engine", "borg"), ("password", "hunter2"), ("keep_daily", "-1"), ("colour", "x")):
            with self.assertRaises(ValueError):
                B.check_setting(key, value)

    def test_edit_list(self):
        self.assertEqual(B.edit_list(["a", "b"], "add", "a"), ["b", "a"])
        self.assertEqual(B.edit_list(["a", "b"], "remove", "a"), ["b"])
        self.assertEqual(B.edit_list(["a"], "add", "  "), ["a"])


class Repo(unittest.TestCase):
    def test_local_or_not(self):
        self.assertTrue(B.is_local("/mnt/disk/backup"))
        self.assertTrue(B.is_local("~/backup"))
        self.assertTrue(B.is_local("local:/srv/b"))
        for url in ("sftp:me@nas:/b", "rest:https://h/", "s3:s3.amazonaws.com/b", "b2:bucket:p"):
            self.assertFalse(B.is_local(url), url)
        self.assertEqual(B.local_path("~/b", "/home/u"), "/home/u/b")
        self.assertEqual(B.local_path("local:/srv/b"), "/srv/b")
        self.assertIsNone(B.local_path("sftp:nas:/b"))

    def test_pick_engine(self):
        self.assertEqual(B.pick_engine({"engine": "auto"}, ["restic", "kopia"]), "restic")
        self.assertEqual(B.pick_engine({"engine": "auto"}, ["kopia"]), "kopia")
        self.assertEqual(B.pick_engine({"engine": "kopia"}, ["restic", "kopia"]), "kopia")
        self.assertIsNone(B.pick_engine({"engine": "kopia"}, ["restic"]))
        self.assertIsNone(B.pick_engine({"engine": "auto"}, []))

    def test_problems_name_the_package(self):
        probs = B.problems(B.parse_conf(""), [])
        self.assertIn("sudo dnf install restic", probs[0])
        self.assertIn("no repository chosen yet", probs)

    def test_problems_ready(self):
        conf = B.parse_conf("repo=/b\n")
        self.assertEqual(B.problems(conf, ["restic"], password_ok=True), [])
        self.assertIn("no password stored for this repository yet",
                      B.problems(conf, ["restic"], password_ok=False))

    def test_kopia_wants_a_folder(self):
        conf = B.parse_conf("engine=kopia\nrepo=sftp:nas:/b\n")
        self.assertTrue(any("folder only" in p for p in B.problems(conf, ["kopia"])))

    def test_password_file_mode(self):
        self.assertEqual(B.password_file_problem(0o100600), "")
        self.assertIn("chmod 600", B.password_file_problem(0o100644))
        self.assertIn("does not exist", B.password_file_problem(None))
        conf = B.parse_conf("repo=/b\npassword=file:~/.pw\n")
        self.assertTrue(any("chmod" in p for p in B.problems(conf, ["restic"], file_mode=0o100640)))


class Commands(unittest.TestCase):
    def test_restic_env_keyring(self):
        conf = B.parse_conf("repo=sftp:nas:/backup\n")
        env = B.engine_env("restic", conf, {"RESTIC_PASSWORD": "leak", "PATH": "/usr/bin"})
        self.assertEqual(env["RESTIC_REPOSITORY"], "sftp:nas:/backup")
        self.assertNotIn("RESTIC_PASSWORD", env)
        self.assertEqual(env["RESTIC_PASSWORD_COMMAND"],
                         "secret-tool lookup service hypr-backup repo sftp:nas:/backup")
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_restic_env_file(self):
        conf = B.parse_conf("repo=/b\npassword=file:/etc/pw\n")
        env = B.engine_env("restic", conf, {"RESTIC_PASSWORD_COMMAND": "x"})
        self.assertEqual(env["RESTIC_PASSWORD_FILE"], "/etc/pw")
        self.assertNotIn("RESTIC_PASSWORD_COMMAND", env)

    def test_kopia_env_has_the_password_only_there(self):
        env = B.engine_env("kopia", B.parse_conf("repo=/b\n"), {}, password="s3cret")
        self.assertEqual(env["KOPIA_PASSWORD"], "s3cret")

    def test_backup_argv_only_existing_paths(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home)
        os.mkdir(os.path.join(home, "Documents"))
        conf = B.parse_conf("include=~/Documents\ninclude=~/Gone\nexclude=~/.cache\nexclude=*.iso\n")
        argv = B.backup_argv("restic", conf, home)
        self.assertEqual(argv[:3], ["restic", "backup", "--json"])
        self.assertEqual(argv[-1], os.path.join(home, "Documents"))
        self.assertNotIn(os.path.join(home, "Gone"), argv)
        self.assertIn(os.path.join(home, ".cache"), argv)
        self.assertIn("*.iso", argv)
        self.assertFalse(any("pass" in a.lower() and "=" in a for a in argv))

    def test_forget_argv(self):
        argv = B.forget_argv("restic", B.parse_conf("keep_weekly=0\n"))
        self.assertIn("--prune", argv)
        self.assertEqual(argv[argv.index("--keep-daily") + 1], "7")
        self.assertNotIn("--keep-weekly", argv)
        self.assertIsNone(B.forget_argv("restic", B.parse_conf("keep_daily=0\nkeep_weekly=0\nkeep_monthly=0\n")))
        kopia = B.forget_argv("kopia", B.parse_conf("exclude=*.iso\n"))
        self.assertIn("--add-ignore", kopia)
        self.assertTrue(kopia[1].startswith("--config-file="))

    def test_init_argv(self):
        self.assertEqual(B.init_argv("restic", {}), ["restic", "init"])
        self.assertIn("--path=/b", B.init_argv("kopia", {"repo": "/b"}))


class Answers(unittest.TestCase):
    def test_restic_summary(self):
        out = "\n".join([json.dumps({"message_type": "status", "percent_done": 0.5}),
                         "not json",
                         json.dumps({"message_type": "summary", "data_added": 1234, "total_bytes_processed": 99,
                                     "total_files_processed": 7, "snapshot_id": "abcd"})])
        self.assertEqual(B.parse_summary("restic", out),
                         {"added": 1234, "processed": 99, "files": 7, "snapshot": "abcd"})
        self.assertEqual(B.parse_summary("restic", "")["added"], None)

    def test_kopia_summary(self):
        out = json.dumps([{"id": "k1", "rootEntry": {"summ": {"size": 10, "files": 2}}},
                          {"id": "k2", "rootEntry": {"summ": {"size": 5, "files": 1}}}])
        got = B.parse_summary("kopia", out)
        self.assertEqual((got["processed"], got["files"], got["snapshot"]), (15, 3, "k2"))

    def test_snapshots_newest_first(self):
        out = json.dumps([{"short_id": "aa", "time": "2026-10-01T10:00:00Z", "paths": ["/h"], "hostname": "pc"},
                          {"id": "bbbbbbbbbbbb", "time": "2026-10-03T10:00:00Z", "paths": [], "hostname": "pc"}])
        snaps = B.parse_snapshots("restic", out)
        self.assertEqual([s["id"] for s in snaps], ["bbbbbbbb", "aa"])
        self.assertEqual(B.parse_snapshots("restic", "garbage"), [])
        k = B.parse_snapshots("kopia", json.dumps([{"id": "123456789", "startTime": "2026",
                                                    "source": {"path": "/h", "host": "pc"}}]))
        self.assertEqual(k, [{"id": "12345678", "time": "2026", "paths": ["/h"], "host": "pc"}])

    def test_stats(self):
        self.assertEqual(B.parse_stats('{"total_size": 42}'), 42)
        self.assertIsNone(B.parse_stats("nope"))

    def test_last_error_prefers_fatal(self):
        self.assertEqual(B.last_error("reading\nFatal: wrong password or no key found\n"),
                         "Fatal: wrong password or no key found")
        self.assertEqual(B.last_error(""), "it stopped without saying why")


class Health(unittest.TestCase):
    def test_not_configured_says_nothing(self):
        self.assertIsNone(B.health({}, False, NOW))
        self.assertEqual(B.brief_text({"ok": False, "last_run": NOW}, False, NOW), [])

    def test_fresh_is_ok(self):
        level, text = B.health({"last_ok": NOW - 3600, "last_run": NOW - 3600, "ok": True,
                                "repo_size": 2_500_000_000}, True, NOW)
        self.assertEqual(level, "ok")
        self.assertIn("2.5 GB", text)
        self.assertEqual(B.brief_text({"last_ok": NOW - 3600, "ok": True, "last_run": NOW}, True, NOW), [])

    def test_week_old_warns(self):
        level, text = B.health({"last_ok": NOW - 8 * DAY, "last_run": NOW - 8 * DAY, "ok": True}, True, NOW)
        self.assertEqual((level, text), ("warn", "no backup for 8 days"))
        self.assertIn("8 days ago", B.brief_text({"last_ok": NOW - 8 * DAY, "ok": True}, True, NOW)[0])

    def test_failed_run_warns_with_reason(self):
        state = {"last_ok": NOW - 2 * DAY, "last_run": NOW - 60, "ok": False, "error": "Fatal: no key"}
        level, text = B.health(state, True, NOW)
        self.assertEqual(level, "warn")
        self.assertIn("Fatal: no key", text)
        self.assertIn("Backup failed", B.brief_text(state, True, NOW)[0])

    def test_never_run(self):
        self.assertEqual(B.health({}, True, NOW)[0], "warn")
        self.assertIn("not run yet", B.brief_text({}, True, NOW)[0])

    def test_stale_due_once_a_day(self):
        old = {"last_ok": NOW - 8 * DAY}
        self.assertTrue(B.stale_due(old, NOW))
        self.assertFalse(B.stale_due(dict(old, stale_notified=NOW - 3600), NOW))
        self.assertTrue(B.stale_due(dict(old, stale_notified=NOW - DAY), NOW))
        self.assertFalse(B.stale_due({"last_ok": NOW - DAY}, NOW))
        self.assertTrue(B.stale_due({"since": NOW - 9 * DAY}, NOW))       # set up, never worked

    def test_texts(self):
        self.assertEqual(B.human(None), "")
        self.assertEqual(B.human(1500), "2 KB")
        self.assertEqual(B.age_text(None), "never")
        self.assertEqual(B.age_text(120), "2 min ago")
        self.assertEqual(B.age_text(3 * DAY), "3 days ago")

    def test_restore_hint_never_holds_a_password(self):
        text = B.restore_hint("restic", B.parse_conf("repo=/mnt/b\n"), "2026-10-28")
        self.assertIn("restic restore latest --target ~/Restored-2026-10-28", text)
        self.assertIn("RESTIC_PASSWORD_COMMAND", text)
        self.assertIn("kopia", B.restore_hint("kopia", B.parse_conf("repo=/b\n"), "x"))


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        repo = os.path.join(self.dir, "repo")
        os.mkdir(repo)
        self.conf = os.path.join(self.dir, "backup.conf")
        with open(self.conf, "w") as handle:
            handle.write(f"repo={repo}\ninclude={self.dir}\n")
        patches = [mock.patch.object(B, "CONF", self.conf),
                   mock.patch.object(B, "STATE_DIR", self.dir),
                   mock.patch.object(B, "STATE", os.path.join(self.dir, "state.json")),
                   mock.patch.object(B, "LOCK", os.path.join(self.dir, ".lock")),
                   mock.patch.object(B, "installed", lambda: ["restic"]),
                   mock.patch.object(B, "password_stored", lambda repo: True),
                   mock.patch.object(B, "notify", lambda *a, **k: self.toasts.append(a))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.toasts, self.calls = [], []

    def fake_sh(self, answers):
        def sh(argv, env=None, timeout=None, stdin=None):
            self.calls.append((argv, env))
            return answers.get(argv[1], (0, "", ""))
        return mock.patch.object(B, "sh", sh)

    def test_success_writes_the_state(self):
        summary = json.dumps({"message_type": "summary", "data_added": 10, "snapshot_id": "s1"})
        with self.fake_sh({"backup": (0, summary, ""), "stats": (0, '{"total_size": 500}', "")}):
            self.assertEqual(B.run_backup(), 0)
        state = B.load_state()
        self.assertTrue(state["ok"])
        self.assertEqual((state["added"], state["snapshot"], state["repo_size"]), (10, "s1", 500))
        self.assertEqual([c[0][1] for c in self.calls], ["backup", "forget", "stats"])
        self.assertIn("RESTIC_PASSWORD_COMMAND", self.calls[0][1])
        self.assertEqual(self.toasts, [])

    def test_failure_notifies(self):
        with self.fake_sh({"backup": (1, "", "Fatal: wrong password or no key found")}):
            self.assertEqual(B.run_backup(), 1)
        self.assertFalse(B.load_state()["ok"])
        self.assertEqual(self.toasts[0][0], "Backup failed")
        self.assertIn("wrong password", self.toasts[0][1])

    def test_missing_drive_fails_without_running_restic(self):
        os.rmdir(os.path.join(self.dir, "repo"))
        with self.fake_sh({}):
            self.assertEqual(B.run_backup(), 1)
        self.assertEqual(self.calls, [])
        self.assertIn("not there", B.load_state()["error"])

    def test_timer_does_nothing_when_not_set_up(self):
        with open(self.conf, "w") as handle:
            handle.write("")
        with self.fake_sh({}):
            self.assertEqual(B.run_backup(timer=True), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(B.load_state(), {})

    def test_partial_read_is_still_a_backup(self):
        with self.fake_sh({"backup": (3, "", "error: open /x: permission denied")}):
            self.assertEqual(B.run_backup(), 0)
        state = B.load_state()
        self.assertTrue(state["ok"])
        self.assertIn("could not be read", state["warning"])

    def test_kopia_sets_its_policy_before_the_snapshot(self):
        """kopia thins and ignores by its policy as it snapshots, so the
        policy goes first (a first snapshot would otherwise skip the excludes)."""
        with open(self.conf, "a") as handle:
            handle.write("engine=kopia\npassword=keyring\n")
        order = []

        def sh(argv, env=None, timeout=None, stdin=None):
            order.append(argv[2] if argv[0] == "kopia" else argv[0])
            return 0, "", ""
        with mock.patch.object(B, "installed", lambda: ["kopia"]), mock.patch.object(B, "sh", sh):
            self.assertEqual(B.run_backup(), 0)
        kopia_steps = [step for step in order if step in ("repository", "policy", "snapshot")]
        self.assertEqual(kopia_steps, ["repository", "policy", "snapshot"])


if __name__ == "__main__":
    unittest.main()
