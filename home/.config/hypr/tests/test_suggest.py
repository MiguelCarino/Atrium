"""Live suggestions (suggest.py): the settings, what it learns from your
clicks, which waiting suggestion goes first, the quiet rules, the git
reading for "draft a commit message", the resume card, the daemon's
hand-over from the smart clipboard, and the fixed action catalog.

Hermetic: suggest.conf / suggest-learn.json are helpers.py's scratch
XDG_STATE_HOME, the git repos are made in the scratch folder, makoctl /
hyprctl / the /proc scan are stubbed, no strip is ever shown (the strip's
process is a fake), no model is asked and nothing is copied."""
import json
import os
import socket
import subprocess
import threading
import time
import unittest
from unittest import mock

import helpers

suggest = helpers.import_script("suggest.py")
smart = helpers.import_script("smart-clipboard.py", "smart_clipboard")


def quiet_desktop(test):
    """No DND, no gamemode, no hyprctl, no hyprlock, no sleep."""
    for name, value in (("dnd_on", False), ("gamemode_on", False), ("hyprctl_json", None),
                        ("process_running", False)):
        patcher = mock.patch.object(suggest, name, return_value=value)
        patcher.start()
        test.addCleanup(patcher.stop)
    patcher = mock.patch.object(suggest, "slept_offset", return_value=0.0)
    patcher.start()
    test.addCleanup(patcher.stop)


def clean_files():
    for path in (suggest.CONF, suggest.LEARN):
        if os.path.exists(path):
            os.remove(path)


class Settings(unittest.TestCase):
    setUp = tearDown = staticmethod(clean_files)

    def test_shipped_conservative(self):
        v = suggest.read_settings()
        self.assertEqual(suggest.kinds_on(v), {"commit", "resume"})
        self.assertEqual((v["position"], v["gap_min"], v["show_s"]), ("bottom-right", "10", "15"))

    def test_set_and_read_back(self):
        suggest.write_setting("clipboard", "ON")
        suggest.write_setting("position", "top-center")
        suggest.write_setting("gap_min", "30")
        v = suggest.read_settings()
        self.assertIn("clipboard", suggest.kinds_on(v))
        self.assertEqual((v["position"], v["gap_min"]), ("top-center", "30"))
        suggest.write_setting("gap_min", "10")                  # back at the default: dropped from the file
        with open(suggest.CONF) as handle:
            self.assertNotIn("gap_min", handle.read())

    def test_refuses_bad_values(self):
        for key, value in (("position", "middle"), ("gap_min", "0"), ("gap_min", "ten"), ("commit", "yes"),
                           ("nope", "1")):
            with self.assertRaises(ValueError, msg=(key, value)):
                suggest.write_setting(key, value)
        self.assertFalse(os.path.exists(suggest.CONF))

    def test_hand_edit_falls_back(self):
        os.makedirs(os.path.dirname(suggest.CONF), exist_ok=True)
        with open(suggest.CONF, "w") as handle:
            handle.write("# x\ngap_min=abc\nshow_s=20\nposition=left\ngarbage\n meeting = on \n")
        v = suggest.read_settings()
        self.assertEqual((v["gap_min"], v["show_s"], v["position"], v["meeting"]), ("10", "20", "bottom-right", "on"))


class Learning(unittest.TestCase):
    def test_dismissals_rest_longer_each_time(self):
        learn, now = {}, 1000.0
        st = suggest.record(learn, "commit", "dismissed", now)
        self.assertEqual(st["until"], now + suggest.BASE_REST_S)
        st = suggest.record(learn, "commit", "dismissed", now)
        self.assertEqual(st["until"], now + 2 * suggest.BASE_REST_S)
        for _ in range(10):
            st = suggest.record(learn, "commit", "dismissed", now)
        self.assertEqual(st["until"], now + suggest.MAX_REST_S)
        self.assertTrue(suggest.resting(learn, "commit", now + 10))
        st = suggest.record(learn, "commit", "acted", now)
        self.assertEqual((st["streak"], st["until"], st["shown"], st["acted"]), (0, 0, 13, 1))
        self.assertFalse(suggest.resting(learn, "commit", now))

    def test_ignored_rests_a_little(self):
        learn = {}
        st = suggest.record(learn, "resume", "ignored", 0)
        self.assertEqual((st["ignored"], st["streak"], st["until"]), (1, 0, suggest.IGNORED_REST_S))

    def test_score_follows_use(self):
        learn = {}
        fresh = suggest.score(learn, "commit")
        suggest.record(learn, "commit", "acted", 0)
        self.assertGreater(suggest.score(learn, "commit"), fresh)
        for _ in range(3):
            suggest.record(learn, "context", "dismissed", 0)
        self.assertLess(suggest.score(learn, "context"), suggest.score({}, "context"))

    def test_junk_file_is_empty(self):
        os.makedirs(os.path.dirname(suggest.LEARN), exist_ok=True)
        with open(suggest.LEARN, "w") as handle:
            handle.write("[1, 2")
        self.assertEqual(suggest.load_learn(), {})
        self.assertEqual(suggest.stats({"commit": "x"}, "commit")["shown"], 0)
        os.remove(suggest.LEARN)


class Picking(unittest.TestCase):
    def setUp(self):
        self.values = dict(suggest.DEFAULTS, clipboard="on", context="on")
        self.now = 10_000.0

    def cand(self, kind, **extra):
        return suggest.candidate(kind, f"{kind}:x", "t", "b", [("noop", "x", "")], self.now, **extra)

    def test_gap_and_own_copies(self):
        pending = {"a": self.cand("commit")}
        recent = self.now - 60
        self.assertIsNone(suggest.pick(pending, self.values, {}, self.now, recent))
        self.assertIs(suggest.pick(pending, self.values, {}, self.now, self.now - 3600), pending["a"])
        pending["b"] = self.cand("clipboard")
        self.assertIs(suggest.pick(pending, self.values, {}, self.now, recent), pending["b"])

    def test_off_resting_expired_waiting_snoozed(self):
        old = self.now - 3600
        self.assertIsNone(suggest.pick({"a": self.cand("meeting")}, self.values, {}, self.now, old))   # off
        learn = {}
        suggest.record(learn, "commit", "dismissed", self.now)
        self.assertIsNone(suggest.pick({"a": self.cand("commit")}, self.values, learn, self.now + 5, old))
        gone = self.cand("commit", expires=self.now - 1)
        self.assertIsNone(suggest.pick({"a": gone}, self.values, {}, self.now, old))
        later = self.cand("resume", not_before=self.now + 4)
        self.assertIsNone(suggest.pick({"a": later}, self.values, {}, self.now, old))
        self.assertIs(suggest.pick({"a": later}, self.values, {}, self.now + 5, old), later)
        self.assertIsNone(suggest.pick({"a": self.cand("commit")}, self.values, {}, self.now, old,
                                       snooze_until=self.now + 60))

    def test_more_used_kind_first(self):
        learn = {}
        for _ in range(4):
            suggest.record(learn, "resume", "dismissed", 0)
        for _ in range(4):
            suggest.record(learn, "context", "acted", 0)
        pending = {"r": self.cand("resume"), "c": self.cand("context")}
        self.assertEqual(suggest.pick(pending, self.values, learn, self.now, 0)["kind"], "context")


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"})


class Git(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = os.path.join(helpers.SCRATCH, "repo-suggest")
        os.makedirs(cls.repo, exist_ok=True)
        git(cls.repo, "init", "-q")
        for name, text in (("a.py", "x = 1\n"), (".env", "KEY=1\n")):
            with open(os.path.join(cls.repo, name), "w") as handle:
                handle.write(text)
        git(cls.repo, "add", "-A")
        git(cls.repo, "commit", "-q", "-m", "Add the first files")
        cls.repo = os.path.realpath(cls.repo)

    def write(self, name, text, age=0):
        path = os.path.join(self.repo, name)
        with open(path, "w") as handle:
            handle.write(text)
        t = time.time() - age
        os.utime(path, (t, t))

    def tearDown(self):
        git(self.repo, "checkout", "-q", "--", ".")
        git(self.repo, "clean", "-qfd")

    def test_clean_repo(self):
        self.assertEqual(suggest.repo_top(os.path.join(self.repo)), self.repo)
        self.assertIsNone(suggest.repo_changes(self.repo))
        self.assertIsNone(suggest.repo_top(helpers.SCRATCH + "/nowhere"))

    def test_due_only_after_a_pause(self):
        self.write("a.py", "x = 2\n", age=3600)
        changes = suggest.repo_changes(self.repo)
        self.assertEqual(changes[3], 1)
        self.assertTrue(suggest.commit_due(changes, time.time(), 20 * 60))
        self.assertFalse(suggest.commit_due(changes, time.time(), 2 * 3600))       # not old enough
        self.write("b.txt", "new\n", age=10)                                       # you are mid-edit
        changes = suggest.repo_changes(self.repo)
        self.assertEqual(changes[3], 2)
        self.assertFalse(suggest.commit_due(changes, time.time(), 20 * 60))

    def test_deleted_file_ages_by_its_folder(self):
        os.remove(os.path.join(self.repo, "a.py"))
        old = time.time() - 3600
        os.utime(self.repo, (old, old))
        changes = suggest.repo_changes(self.repo)
        self.assertEqual(changes[3], 1)
        self.assertTrue(suggest.commit_due(changes, time.time(), 20 * 60))

    def test_material_leaves_secrets_out_and_caps(self):
        self.write("a.py", "".join(f"line_{i} = {i}\n" for i in range(4000)))
        self.write(".env", "KEY=hunter2\n")
        self.write("new.txt", "hello\n")
        worker = suggest._module("llm_worker", "llm-worker.py")     # the copy suggest.py uses
        stat, diff, skipped, subjects = suggest.commit_material(self.repo, worker.looks_secret)
        self.assertNotIn("hunter2", diff)
        self.assertEqual(skipped, [".env"])
        self.assertIn("a.py", stat)
        self.assertIn("new.txt", stat)
        self.assertLessEqual(len(diff), suggest.MAX_DIFF + 100)
        self.assertEqual(subjects, ["Add the first files"])
        prompt = suggest.commit_prompt(self.repo, stat, diff, subjects)
        self.assertIn("- Add the first files", prompt)

    def test_draft_refuses_without_model(self):
        self.write("a.py", "x = 3\n")
        worker = suggest._module("llm_worker", "llm-worker.py")     # the copy suggest.py uses
        with mock.patch.object(worker, "ready", return_value=(None, "gamemode is on")), \
                mock.patch.object(worker, "ask") as ask:
            self.assertEqual(suggest.draft_commit(self.repo), (None, "gamemode is on"))
        ask.assert_not_called()

    def test_draft_cleans_the_answer(self):
        self.write("a.py", "x = 3\n")
        worker = suggest._module("llm_worker", "llm-worker.py")     # the copy suggest.py uses
        model = mock.Mock()
        model.name = "gemma"
        answer = "```\nChange x to 3\n\n- tidy\nCo-Authored-By: Someone <a@b>\n```"
        with mock.patch.object(worker, "ready", return_value=(model, None)), \
                mock.patch.object(worker, "ask", return_value=answer):
            self.assertEqual(suggest.draft_commit(self.repo), ("Change x to 3\n\n- tidy", "gemma"))


class Cards(unittest.TestCase):
    def test_resume_card(self):
        last = {"address": "0xabc123", "class": "org.mozilla.firefox", "title": "Notes", "private": False}
        card = suggest.resume_candidate(42 * 60, last, True, "0xdef456", 0)
        self.assertEqual(card["title"], "Away 42 min: pick up where you left off")
        self.assertIn("Firefox: Notes", card["body"])
        self.assertEqual(card["actions"][0], ["focus", "Go back to Firefox", "0xabc123"])
        self.assertEqual(card["not_before"], suggest.RESUME_DELAY_S)
        private = dict(last, title="", private=True)
        card = suggest.resume_candidate(3 * 3600 + 60, private, False, None, 0)
        self.assertEqual(card["body"], "You were in Firefox.")
        self.assertEqual([a[0] for a in card["actions"]], ["focus_round"])
        self.assertIn("3 h 1 min", card["title"])

    def test_clipboard_card_keeps_its_actions(self):
        card = suggest.clipboard_candidate({"kind": "colour", "title": "Colour", "body": "#fff",
                                            "actions": [["copy", "Copy as rgb", "rgb(255 255 255)"], ["bad"]],
                                            "swatch": "#ffffff", "text": "#fff"}, 0)
        self.assertEqual(card["actions"], [["clip:copy", "Copy as rgb", "rgb(255 255 255)"]])
        self.assertEqual((card["swatch"], card["text"]), ("#ffffff", "#fff"))

    def test_actions_are_the_catalog(self):
        card = {"actions": [["focus", "Go back", "0xabc123"]]}
        self.assertTrue(suggest.allowed(card, "focus", "0xabc123"))
        self.assertFalse(suggest.allowed(card, "focus", "0xdead00"))
        self.assertFalse(suggest.allowed(card, "terminal", "/"))
        with mock.patch.object(suggest.subprocess, "run") as run:
            self.assertEqual(suggest.run_action(card, "focus", "0x1; rm -rf ~"), "Not a window.")
            run.assert_not_called()
        self.assertEqual(suggest.run_action(card, "nothing-like-it", ""), "")
        self.assertIn("sample", suggest.run_action(card, suggest.SAMPLE_ACTION, ""))

    def test_samples(self):
        for kind in suggest.KINDS:
            card = suggest.SAMPLES[kind](0)
            self.assertEqual(card["kind"], kind)
            self.assertTrue(all(a[0] == suggest.SAMPLE_ACTION for a in card["actions"]))

    def test_private_and_names(self):
        self.assertTrue(suggest.is_private("org.keepassxc.KeePassXC", "x"))
        self.assertTrue(suggest.is_private("firefox", "Mozilla Firefox Private Browsing"))
        self.assertFalse(suggest.is_private("kitty", "~/Projects"))
        self.assertEqual(suggest.app_name("com.system76.CosmicTerm"), "CosmicTerm")
        self.assertEqual(suggest.app_name(""), "the window")


class FakeStrip:
    """A strip process that has said `lines` and ended."""

    def __init__(self, *lines):
        self.r, w = os.pipe()
        os.write(w, b"".join(json.dumps(line).encode() + b"\n" for line in lines))
        os.close(w)
        self.stdout = os.fdopen(self.r, "rb")
        os.set_blocking(self.r, False)
        self.terminated = False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        pass


class DaemonTests(unittest.TestCase):
    def setUp(self):
        clean_files()
        quiet_desktop(self)
        self.clock = [100_000.0]
        self.daemon = suggest.Daemon(values=dict(suggest.DEFAULTS), learn={}, clock=lambda: self.clock[0])
        save = mock.patch.object(suggest, "save_learn")
        save.start()
        self.addCleanup(save.stop)
        self.shown = []
        show = mock.patch.object(suggest.Daemon, "show", lambda d, cand: self.shown.append(cand))
        show.start()
        self.addCleanup(show.stop)

    def test_quiet_rules(self):
        d = self.daemon
        self.assertEqual(d.quiet_reason(), "")
        d.event("fullscreen>>1")
        self.assertEqual(d.quiet_reason(), "fullscreen")
        d.event("fullscreen>>0")
        d.event("screencast>>1,0")
        self.assertEqual(d.quiet_reason(), "screen shared")
        d.event("screencast>>0,0")
        with mock.patch.object(suggest, "dnd_on", return_value=True):
            self.assertEqual(d.quiet_reason(), "do not disturb")
        with mock.patch.object(suggest, "gamemode_on", return_value=True):
            self.assertEqual(d.quiet_reason(), "gamemode")
        d.request({"op": "snooze", "minutes": 5})
        self.assertEqual(d.quiet_reason(), "snoozed")
        d.request({"op": "snooze", "minutes": 0})
        self.assertEqual(d.quiet_reason(), "")

    def test_nothing_shows_while_quiet(self):
        d = self.daemon
        d.offer(suggest.SAMPLES["resume"](self.clock[0]))
        d.fullscreen = True
        d.maybe_show()
        self.assertEqual(self.shown, [])
        d.fullscreen = False
        d.maybe_show()
        self.assertEqual(len(self.shown), 1)

    def test_resume_after_lock(self):
        d = self.daemon
        d.focus = {"address": "0xabc123", "class": "kitty", "title": "~/Projects", "private": False}
        with mock.patch.object(suggest, "process_running", return_value=True):
            d.check_away(self.clock[0])
        self.assertTrue(d.locked)
        self.assertEqual(d.quiet_reason(), "locked")
        self.clock[0] += 20 * 60
        clients = [{"address": "0xabc123"}]
        with mock.patch.object(suggest, "hyprctl_json", side_effect=lambda *a: clients if a == ("clients",) else None):
            d.check_away(self.clock[0])
        card = d.pending["resume"]
        self.assertEqual(card["actions"][0], ["focus", "Go back to Kitty", "0xabc123"])

    def test_short_lock_and_sleep(self):
        d = self.daemon
        with mock.patch.object(suggest, "process_running", return_value=True):
            d.check_away(self.clock[0])
        self.clock[0] += 60
        d.check_away(self.clock[0])
        self.assertEqual(d.pending, {})                 # away a minute: nothing
        with mock.patch.object(suggest, "slept_offset", return_value=3600.0):
            d.check_away(self.clock[0])                 # an hour asleep, no lock
        self.assertIn("resume", d.pending)

    def test_resume_off(self):
        d = self.daemon
        d.values["resume"] = "off"
        with mock.patch.object(suggest, "slept_offset", return_value=3600.0):
            d.check_away(self.clock[0])
        self.assertEqual(d.pending, {})

    def test_clipboard_hand_over(self):
        d = self.daemon
        card = {"kind": "url", "title": "Link copied", "body": "x", "actions": [["open", "Open", "https://x"]],
                "text": "https://x"}
        self.assertEqual(d.request({"op": "clipboard", "card": card}), {"taken": False})     # off as shipped
        d.values["clipboard"] = "on"
        self.assertEqual(d.request({"op": "clipboard", "card": card}), {"taken": True})
        self.assertEqual(d.pending["clipboard"]["actions"], [["clip:open", "Open", "https://x"]])
        d.last_shown = self.clock[0]                    # a card a moment ago: your copy does not wait
        d.maybe_show()
        self.assertEqual(self.shown[-1]["kind"], "clipboard")

    def test_learns_from_the_strip(self):
        d = self.daemon
        cand = suggest.SAMPLES["commit"](self.clock[0])
        d.strip = (FakeStrip({"result": "dismissed", "action": ""}), cand, b"")
        d.strip_output()
        self.assertIsNone(d.strip)
        self.assertEqual(suggest.stats(d.learn, "commit")["dismissed"], 1)
        d.strip = (FakeStrip(), dict(cand, hidden=True), b"")       # hidden by the quiet rules: no count
        d.strip_output()
        self.assertEqual(suggest.stats(d.learn, "commit")["shown"], 1)
        d.strip = (FakeStrip({"result": "acted", "action": "draft"}), dict(cand, sample=True), b"")
        d.strip_output()                                              # a sample never counts
        self.assertEqual(suggest.stats(d.learn, "commit")["acted"], 0)

    def test_fullscreen_hides_the_card(self):
        d = self.daemon
        fake = FakeStrip()
        d.strip = (fake, suggest.SAMPLES["resume"](0), b"")
        d.event("fullscreen>>1")
        self.assertTrue(fake.terminated)
        fake.stdout.close()

    def test_context_enter(self):
        d = self.daemon
        d.values["context"] = "on"
        with open(suggest.CONTEXTS_STATE, "w") as handle:
            json.dump({"name": "Atlas"}, handle)
        try:
            d.check_context(self.clock[0])
        finally:
            os.remove(suggest.CONTEXTS_STATE)
        self.assertEqual(d.pending["context:Atlas"]["title"], "In Atlas")

    def test_commit_offered_once_per_change_set(self):
        d = self.daemon
        changes = ("sig1", self.clock[0] - 7200, self.clock[0] - 600, 2)
        d.repo = ("/r/x", 0)
        with mock.patch.object(suggest, "repo_changes", return_value=changes):
            d.check_repo(self.clock[0])
            self.assertIn("commit:/r/x", d.pending)
            d.maybe_show()
            self.assertEqual(self.shown[-1]["key"], "commit:/r/x")
            self.clock[0] += suggest.REPO_REST_S + 1
            d.check_repo(self.clock[0])                  # same changes: not again
        self.assertNotIn("commit:/r/x", d.pending)
        with mock.patch.object(suggest, "repo_changes", return_value=None):
            d.check_repo(self.clock[0])                  # committed
        self.assertEqual(d.repos["/r/x"]["offered"], 0)

    def test_status_says_no_content(self):
        d = self.daemon
        d.offer(suggest.clipboard_candidate({"title": "secret?", "text": "hunter2"}, self.clock[0]))
        d.values["clipboard"] = "on"
        d.offer(suggest.clipboard_candidate({"title": "secret?", "text": "hunter2"}, self.clock[0]))
        self.assertNotIn("hunter2", json.dumps(d.status()))
        self.assertEqual(d.request({"op": "nope"}), {"error": "no op 'nope'"})


class ReviewFixes(unittest.TestCase):
    """What the review found: a maximized window is not fullscreen, the
    hand-over never waits on the old card, the calendar reader never blocks
    the loop, DND / gamemode are not asked every second, an x rests the
    clipboard kind too."""

    setUp = DaemonTests.setUp

    def test_maximized_is_not_fullscreen(self):
        d = self.daemon
        with mock.patch.object(suggest, "hyprctl_json", return_value={"fullscreen": 1}):
            d.event("fullscreen>>1")
        self.assertFalse(d.fullscreen)
        with mock.patch.object(suggest, "hyprctl_json", return_value={"fullscreen": 2}):
            d.event("fullscreen>>1")
        self.assertTrue(d.fullscreen)
        d.event("fullscreen>>0")
        self.assertFalse(d.fullscreen)
        self.assertTrue(suggest.fullscreen_mode({"fullscreen": 3}))
        self.assertFalse(suggest.fullscreen_mode({"fullscreen": 0}))

    def test_hand_over_does_not_wait_for_the_old_card(self):
        d = self.daemon
        d.values["clipboard"] = "on"
        fake = FakeStrip()
        fake.wait = mock.Mock(side_effect=AssertionError("waited on the old card"))
        d.strip = (fake, suggest.SAMPLES["commit"](0), b"")
        card = {"kind": "url", "title": "Link", "actions": [["open", "Open", "https://x"]], "text": "https://x"}
        self.assertEqual(d.request({"op": "clipboard", "card": card}), {"taken": True})
        self.assertTrue(fake.terminated)
        self.assertIn("clipboard", d.pending)
        fake.stdout.close()

    def test_an_x_rests_the_clipboard_kind_but_leaving_it_does_not(self):
        learn, now = {}, 1000.0
        suggest.record(learn, "clipboard", "ignored", now)
        self.assertFalse(suggest.resting(learn, "clipboard", now + 1))
        suggest.record(learn, "clipboard", "dismissed", now)
        values = dict(suggest.DEFAULTS, clipboard="on")
        cand = suggest.candidate("clipboard", "clipboard", "t", "b", [], now)
        self.assertIsNone(suggest.pick({"c": cand}, values, learn, now + 1, 0))

    def test_dnd_asked_at_most_every_few_seconds(self):
        d = self.daemon
        d.offer(suggest.SAMPLES["resume"](self.clock[0]))
        with mock.patch.object(suggest, "dnd_on", return_value=True) as dnd:
            d.maybe_show()
            d.maybe_show()
            self.assertEqual(dnd.call_count, 1)
            self.clock[0] += suggest.QUIET_RECHECK_S
            d.maybe_show()
            self.assertEqual(dnd.call_count, 2)
        self.assertEqual(self.shown, [])

    def test_calendar_reader_never_blocks(self):
        d = self.daemon
        d.values["meeting"] = "on"
        start = self.clock[0] + 300

        class Reader:
            def __init__(self):
                self.done = False

            def poll(self):
                return 0 if self.done else None

            def communicate(self, timeout=None):
                return json.dumps([{"start": start, "summary": "Sync", "key": "k1"}]), ""

            def kill(self):
                pass

            def wait(self):
                return 0
        reader = Reader()
        with mock.patch.object(suggest.subprocess, "Popen", return_value=reader) as popen, \
                mock.patch.object(suggest.subprocess, "run", side_effect=AssertionError("waited")):
            d.check_meetings(self.clock[0])
            self.assertEqual(popen.call_count, 1)
            d.check_meetings(self.clock[0] + 15)        # still reading: nothing, no second reader
            self.assertEqual((popen.call_count, d.pending), (1, {}))
            reader.done = True
            d.check_meetings(self.clock[0] + 30)
        self.assertIn("meeting:k1", d.pending)
        self.assertIsNone(d.meeting_proc)

    def test_slow_calendar_reader_is_killed(self):
        d = self.daemon
        d.values["meeting"] = "on"
        reader = mock.Mock()
        reader.poll.return_value = None
        with mock.patch.object(suggest.subprocess, "Popen", return_value=reader):
            d.check_meetings(self.clock[0])
            d.check_meetings(self.clock[0] + suggest.MEETING_TIMEOUT_S + 1)
        reader.kill.assert_called_once()
        self.assertIsNone(d.meeting_proc)

    def test_literal_pathspecs(self):
        self.assertEqual(suggest.GIT_ENV["GIT_LITERAL_PATHSPECS"], "1")


class SmartClipboardHandOver(unittest.TestCase):
    def test_no_daemon_means_own_card(self):
        self.assertFalse(smart.to_strip({"kind": "url"}, path=os.path.join(helpers.SCRATCH, "none.sock")))

    def test_daemon_takes_it(self):
        path = os.path.join(helpers.SCRATCH, "suggest-test.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        got = {}

        def answer():
            conn, _ = server.accept()
            with conn:
                got["msg"] = json.loads(conn.recv(65536))
                conn.sendall(b'{"taken": true}\n')
        thread = threading.Thread(target=answer)
        thread.start()
        try:
            self.assertTrue(smart.to_strip({"kind": "url", "text": "https://x"}, path=path))
        finally:
            thread.join(2)
            server.close()
            os.remove(path)
        self.assertEqual(got["msg"]["op"], "clipboard")
        self.assertEqual(got["msg"]["card"]["text"], "https://x")

    def test_ask_daemon_without_one(self):
        self.assertIsNone(suggest.ask_daemon({"op": "status"}, path=os.path.join(helpers.SCRATCH, "none.sock")))


if __name__ == "__main__":
    unittest.main()
