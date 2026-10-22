"""scripts/folder_access.py: which folders the AI features may read, and
each place that asks it (llm-worker.py, assistant.py's read_file and the
searches it shares with ask-desktop.py, tasks.py, phone-ask.py).

Every test has its own store; no real prompt is ever shown (helpers.py sets
HYPR_FOLDER_ACCESS_NO_PROMPT, and the tests that need an answer hand in a
fake prompter)."""
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import helpers

import folder_access as fa  # noqa: E402  (helpers put scripts/ on the path)

worker = helpers.import_script("llm-worker.py", "llm_worker")
a = helpers.import_script("assistant.py")
ask = helpers.import_script("ask-desktop.py")
tasks = helpers.import_script("tasks.py")
phone_ask = helpers.import_script("phone-ask.py")


class Prompter:
    """A fake prompt: answers `decision` for the level `pick` (0 = the
    file's folder), counts the calls, can take its time."""

    def __init__(self, decision="once", pick=0, delay=0.0):
        self.decision, self.pick, self.delay = decision, pick, delay
        self.calls = []

    def __call__(self, who, levels, reason, timeout):
        self.calls.append((who, list(levels), reason))
        time.sleep(self.delay)
        if self.decision is None:
            return None
        return self.decision, levels[min(self.pick, len(levels) - 1)]


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(dir=helpers.SCRATCH))
        # The real window is never shown, even if helpers.py's switch were missing.
        for name, value in (("STORE", os.path.join(self.dir, "folder-access.json")), ("PROMPTER", None),
                            ("window_prompter", lambda *args: None)):
            patcher = mock.patch.object(fa, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def file(self, rel, text="hello\n"):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def prompter(self, *args, **kw):
        p = Prompter(*args, **kw)
        patcher = mock.patch.object(fa, "PROMPTER", p)
        patcher.start()
        self.addCleanup(patcher.stop)
        return p


class Policy(Scratch):
    def test_nothing_granted_asks(self):
        self.assertEqual(fa.check(self.file("docs/a.txt"), "assistant"), "ask")

    def test_a_grant_covers_its_subfolders_only(self):
        fa.grant(os.path.join(self.dir, "docs"), "assistant")
        self.assertEqual(fa.check(self.file("docs/deep/er/a.txt"), "assistant"), "allow")
        self.assertEqual(fa.check(self.file("docsx/a.txt"), "assistant"), "ask")      # not a prefix match
        self.assertEqual(fa.check(self.file("other/a.txt"), "assistant"), "ask")

    def test_symlink_out_of_an_allowed_folder_needs_the_target(self):
        fa.grant(os.path.join(self.dir, "open"), "all")
        target = self.file("closed/notes.txt")
        os.makedirs(os.path.join(self.dir, "open"), exist_ok=True)
        link = os.path.join(self.dir, "open", "notes.txt")
        os.symlink(target, link)
        self.assertEqual(fa.check(link, "assistant"), "ask")
        os.symlink(os.path.join(self.dir, "closed"), os.path.join(self.dir, "open", "dir"))
        self.assertEqual(fa.check(os.path.join(self.dir, "open", "dir", "notes.txt"), "assistant"), "ask")

    def test_secret_and_system_paths_stay_refused_even_when_granted(self):
        fa.grant(self.dir, "all")
        for name in ("id_rsa", "prod.env", "api-token.txt", "server.key", "secrets/plain.txt"):
            verdict, why = fa.decide(self.file(name), "assistant")
            self.assertEqual(verdict, "deny", name)
        self.assertEqual(fa.check(os.path.expanduser("~/.ssh/config"), "assistant"), "deny")
        self.assertEqual(fa.check("/proc/self/environ", "worker"), "deny")
        with self.assertRaises(ValueError):
            fa.grant(os.path.expanduser("~/.ssh"), "all")
        with self.assertRaises(ValueError):
            fa.grant("/", "all")
        with mock.patch.object(fa, "PROMPTER", lambda *a: self.fail("a secret is never asked about")):
            self.assertFalse(fa.request(self.file("x.pem"), "worker")[0])

    def test_a_secret_word_in_a_folder_name_does_not_block_the_folder(self):
        readme = self.file("password-tools/README.md")
        fa.grant(os.path.join(self.dir, "password-tools"), "all")       # a repo called that
        self.assertEqual(fa.check(readme, "worker"), "allow")

    def test_grants_are_per_feature(self):
        path = self.file("docs/a.txt")
        fa.grant(os.path.join(self.dir, "docs"), "assistant")
        self.assertEqual(fa.check(path, "assistant"), "allow")
        self.assertEqual(fa.check(path, "worker"), "ask")
        fa.grant(os.path.join(self.dir, "docs"), "all")
        self.assertEqual(fa.check(path, "worker"), "allow")
        with self.assertRaises(ValueError):
            fa.check(path, "nobody")

    def test_most_specific_rule_wins_and_deny_wins_a_tie(self):
        fa.grant(self.dir, "all")
        fa.deny(os.path.join(self.dir, "taxes"), "all")
        self.assertEqual(fa.check(self.file("taxes/2025/r.txt"), "assistant"), "deny")
        self.assertEqual(fa.check(self.file("notes/r.txt"), "assistant"), "allow")
        fa.grant(os.path.join(self.dir, "taxes", "2025"), "assistant")
        self.assertEqual(fa.check(self.file("taxes/2025/r.txt"), "assistant"), "allow")
        fa.deny(os.path.join(self.dir, "taxes", "2025"), "all")      # same folder: the deny
        self.assertEqual(fa.check(self.file("taxes/2025/r.txt"), "assistant"), "deny")

    def test_revoke(self):
        fa.grant(self.dir, "assistant")
        fa.grant(self.dir, "worker")
        self.assertEqual(fa.revoke(self.dir, "worker"), 1)
        self.assertEqual(fa.check(self.file("a.txt"), "assistant"), "allow")
        self.assertEqual(fa.revoke(self.dir), 1)
        self.assertEqual(fa.check(self.file("a.txt"), "assistant"), "ask")

    def test_asking_off_is_the_old_behaviour_but_denials_stay(self):
        fa.set_ask(False)
        self.assertEqual(fa.check(self.file("a.txt"), "worker"), "allow")
        self.assertEqual(fa.check(self.file("id_rsa"), "worker"), "deny")
        fa.deny(os.path.join(self.dir, "no"), "worker")
        self.assertEqual(fa.check(self.file("no/a.txt"), "worker"), "deny")

    def test_store_is_private_and_a_broken_one_is_empty(self):
        fa.grant(self.dir, "all")
        self.assertEqual(os.stat(fa.STORE).st_mode & 0o777, 0o600)
        with open(fa.STORE, "w") as handle:
            handle.write("{not json")
        self.assertEqual(fa.load(), {"ask": True, "allow": [], "deny": []})

    def test_levels_offered(self):
        home = fa.HOME
        self.assertEqual(fa.choices(os.path.join(home, "Documents", "taxes", "2025", "r.pdf")),
                         [os.path.join(home, "Documents", "taxes", "2025"), os.path.join(home, "Documents", "taxes"),
                          os.path.join(home, "Documents")])
        self.assertEqual(fa.choices(os.path.join(home, "Documents", "r.pdf")), [os.path.join(home, "Documents")])
        self.assertNotIn("/", fa.choices("/tmp/x.txt"))

    def test_typed_folders(self):
        path = self.file("notes/today.md")
        self.assertEqual(fa.typed_folders(f"sum up {path}, please"), [os.path.dirname(path)])
        self.assertEqual(fa.typed_folders(f"what is in {os.path.dirname(path)}?"), [os.path.dirname(path)])
        self.assertEqual(fa.typed_folders("read ~/.ssh/id_rsa"), [])
        self.assertEqual(fa.typed_folders("no path here"), [])


class Requests(Scratch):
    def test_once_lasts_for_the_session_only(self):
        p = self.prompter("once")
        path = self.file("docs/a.txt")
        session = fa.Session("assistant")
        self.assertTrue(fa.request(path, "assistant", "to sum it up", session=session)[0])
        self.assertTrue(fa.request(self.file("docs/b.txt"), "assistant", session=session)[0])
        self.assertEqual(len(p.calls), 1)                           # the same folder: asked once
        self.assertEqual(p.calls[0][0], "assistant")
        self.assertEqual(p.calls[0][2], "to sum it up")
        self.assertEqual(fa.load()["allow"], [])                    # never written down
        self.assertTrue(fa.request(path, "assistant", session=fa.Session("assistant"))[0])
        self.assertEqual(len(p.calls), 2)                           # a new question asks again

    def test_always_is_stored_at_the_level_picked(self):
        self.prompter("always", pick=1)
        path = self.file("docs/2025/a.txt")
        self.assertTrue(fa.request(path, "worker")[0])
        rows = fa.load()["allow"]
        self.assertEqual([(r["path"], r["who"], r["by"]) for r in rows],
                         [(os.path.join(self.dir, "docs"), "worker", "prompt")])
        self.assertEqual(fa.check(self.file("docs/other/b.txt"), "worker"), "allow")

    def test_deny_in_the_prompt_is_remembered_for_the_session(self):
        p = self.prompter("deny")
        session = fa.Session("worker")
        ok, why = fa.request(self.file("d/a.txt"), "worker", session=session)
        self.assertFalse(ok)
        self.assertIn("said no", why)
        self.assertFalse(fa.request(self.file("d/b.txt"), "worker", session=session)[0])
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(fa.load()["deny"], [])                     # a prompt's Deny is not stored

    def test_no_answer_no_screen_or_timeout_is_deny_and_says_how(self):
        self.prompter(None)
        ok, why = fa.request(self.file("d/a.txt"), "worker")
        self.assertFalse(ok)
        self.assertIn("folder-access.py allow", why)
        self.assertIn("--who worker", why)
        with mock.patch.object(fa, "PROMPTER", None):                # the window, but no prompt allowed here
            self.assertFalse(fa.request(self.file("d/a.txt"), "worker")[0])

    def test_waiting_for_the_lock_counts_toward_the_timeout(self):
        path = self.file("d/a.txt")
        key = fa._lock_path(fa.choices(path)[-1])
        os.makedirs(fa.LOCK_DIR, exist_ok=True)
        with open(key + ".lock", "w") as held:
            fa.fcntl.flock(held, fa.fcntl.LOCK_EX)
            p = self.prompter("once")
            started = time.time()
            ok, why = fa.request(path, "worker", timeout=0.4)
        self.assertFalse(ok)
        self.assertLess(time.time() - started, 2)
        self.assertEqual(p.calls, [])
        self.assertIn("no answer in time", why)

    def test_prompt_false_never_asks(self):
        self.prompter("always")
        ok, why = fa.request(self.file("d/a.txt"), "phone", prompt=False)
        self.assertFalse(ok)
        self.assertEqual(fa.PROMPTER.calls, [])
        self.assertIn("not open to the phone", why)

    def test_concurrent_requests_for_one_folder_do_not_stack(self):
        p = self.prompter("once", delay=0.3)
        results = []

        def go(name):
            results.append(fa.request(self.file(f"d/{name}.txt"), "worker", session=fa.Session("worker"))[0])
        threads = [threading.Thread(target=go, args=(n,)) for n in ("a", "b", "c")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(results, [True, True, True])
        self.assertEqual(len(p.calls), 1)       # the others took the first one's answer

    def test_cli(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(fa.main(["allow", os.path.join(self.dir, "x"), "--who", "worker"]), 0)
            self.assertEqual(fa.main(["check", self.file("x/a.txt"), "--who", "worker"]), 0)
            self.assertEqual(fa.main(["check", self.file("x/a.txt"), "--who", "assistant"]), 1)
            self.assertEqual(fa.main(["revoke", os.path.join(self.dir, "x")]), 0)
            self.assertEqual(fa.main(["allow", "~/.gnupg"]), 2)
            self.assertEqual(fa.main(["ask", "off"]), 0)
        self.assertFalse(fa.load()["ask"])


class FakeModel:
    name = "fake-worker"


class Worker(Scratch):
    def setUp(self):
        super().setUp()
        for name, value in (("ready", lambda role="worker": (FakeModel(), None)),
                            ("ask", lambda model, prompt, **kw: "summary")):
            patcher = mock.patch.object(worker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_folder_not_open_is_an_error_that_says_how(self):
        text, err = worker.run({"task": "summarise", "files": [self.file("logs/a.log")]})
        self.assertTrue(err)
        self.assertIn("folder access needed", text)
        self.assertIn(f"folder-access.py allow {os.path.join(self.dir, 'logs')} --who worker", text)

    def test_one_prompt_per_folder_per_call_with_its_reason(self):
        p = self.prompter("once")
        text, err = worker.run({"task": "summarise", "reason": "to find the failing test",
                                "files": [self.file("logs/a.log"), self.file("logs/b.log")]})
        self.assertFalse(err, text)
        self.assertIn("summary", text)
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(p.calls[0][:1] + p.calls[0][2:], ("worker", "to find the failing test"))
        worker.run({"task": "again", "files": [self.file("logs/a.log")]})
        self.assertEqual(len(p.calls), 2)       # once = that call only

    def test_granted_folder_reads_without_asking_and_secret_never(self):
        fa.grant(os.path.join(self.dir, "logs"), "worker")
        self.prompter("always")
        text, err = worker.run({"task": "t", "files": [self.file("logs/a.log"), self.file("logs/prod.env")]})
        self.assertFalse(err)
        self.assertIn("prod.env", text.split("Skipped:")[1])
        self.assertEqual(fa.PROMPTER.calls, [])


class Assistant(Scratch):
    def turn(self, said, who="assistant", hooks=None):
        conf = dict(a.DEFAULTS, **{f"tool_{g}": "on" for g in a.TOOL_GROUPS})
        return a.Turn(said, "en", conf, world=object(), hooks=hooks, who=who)

    def test_named_file_in_a_closed_folder_asks_and_no_is_an_error(self):
        path = self.file("docs/notes.txt")
        with self.assertRaises(a.ToolError) as cm:
            a.t_read({"path": path}, self.turn("summarise notes.txt"))
        self.assertIn("not open to the assistant", str(cm.exception))

    def test_allow_once_reads_and_the_reason_is_shown(self):
        p = self.prompter("once")
        asked = []
        path = self.file("docs/notes.txt", "line one\n")
        turn = self.turn("summarise notes.txt", hooks={"asking": asked.append})
        out = a.t_read({"path": path, "why": "you asked for a summary"}, turn)
        self.assertIn("line one", out["text"])
        self.assertEqual(p.calls[0][2], "you asked for a summary")
        self.assertEqual(asked, [os.path.dirname(path)])
        a.t_read({"path": path}, turn)
        self.assertEqual(len(p.calls), 1)       # the same question: not again

    def test_a_path_the_user_typed_counts(self):
        self.prompter(None)
        path = self.file("docs/notes.txt", "typed\n")
        self.assertIn("typed", a.t_read({"path": path}, self.turn(f"what is in {path}"))["text"])

    def test_the_phone_never_prompts(self):
        path = self.file("docs/notes.txt")
        with mock.patch.object(fa, "PROMPTER", lambda *x: self.fail("no prompt for the phone")):
            with self.assertRaises(a.ToolError) as cm:
                a.t_read({"path": path}, self.turn(f"read {path}", who="phone"))     # typed: still not
        self.assertIn("not open to the phone", str(cm.exception))
        fa.grant(os.path.join(self.dir, "docs"), "phone")
        self.assertIn("hello", a.t_read({"path": path}, self.turn("read notes.txt", who="phone"))["text"])

    def test_run_turn_passes_who(self):
        with mock.patch.object(a, "Turn", side_effect=RuntimeError("stop")) as made:
            with self.assertRaises(RuntimeError):
                a.run_turn("hi", dict(a.DEFAULTS), history=[], chat=lambda m, n: "", world=object(), who="phone")
        self.assertEqual(made.call_args[0][-1], "phone")


class Searches(Scratch):
    def test_snippets_only_from_open_folders(self):
        shown, hidden = self.file("open/a.md"), self.file("closed/b.md")
        fa.grant(os.path.join(self.dir, "open"), "assistant")
        res = {"mode": "keyword", "results": [{"path": shown, "modified": "x", "snippet": "visible"},
                                              {"path": hidden, "modified": "x", "snippet": "secret plan"}]}
        with mock.patch.object(ask.desktop_index, "search", return_value=res):
            out = ask.call_search("search_meaning", {"query": "plan"}, {"index"}, who="assistant")
        self.assertEqual(out["files"][0]["snippet"], "visible")
        self.assertNotIn("snippet", out["files"][1])
        self.assertIn(os.path.join(self.dir, "closed"), out["withheld"])
        with mock.patch.object(ask.desktop_index, "search", return_value=res):     # ask-desktop has no grant
            out = ask.call_search("search_meaning", {"query": "plan"}, {"index"})
        self.assertTrue(all("snippet" not in f for f in out["files"]))

    def test_search_files_peeks_only_where_allowed(self):
        path = self.file("closed/report.txt", "the first lines")
        with mock.patch.object(ask, "BROWSE_DIRS", [os.path.join(self.dir, "closed")]), \
                mock.patch.object(ask, "visible", lambda p: True):      # the scratch is not under home
            with mock.patch.object(ask, "peek", side_effect=AssertionError("must not read")):
                rows = ask.search_files(may_read=lambda p: False)
            self.assertEqual([r["path"] for r in rows["files"]], [path])
            self.assertNotIn("text", rows["files"][0])
            out = ask.call_search("search_files", {}, {"files"})
            self.assertNotIn("text", out["files"][0])
            fa.grant(os.path.join(self.dir, "closed"), "ask-desktop")
            out = ask.call_search("search_files", {}, {"files"})
            self.assertEqual(out["files"][0]["text"], "the first lines")
        self.assertTrue(ask.content_allowed(path))


class Tasks(Scratch):
    def test_the_task_folder_counts_unless_denied(self):
        log = self.file("logs/app.log", "ERROR boom\n")
        self.assertTrue(tasks.ai_may_read(log, os.path.join(self.dir, "logs"))[0])
        fa.deny(os.path.join(self.dir, "logs"), "tasks")
        ok, why = tasks.ai_may_read(log, os.path.join(self.dir, "logs"))
        self.assertFalse(ok)
        self.assertIn("Folder access", why)

    def test_explain_without_the_model_when_denied(self):
        log = self.file("logs/app.log", "ERROR boom\n")
        fa.deny(os.path.join(self.dir, "logs"), "all")
        with mock.patch.object(tasks, "model_answer", side_effect=AssertionError("no model")):
            cause, by = tasks.explain("a problem", "ok\nERROR boom\n", {"explain": True}, read_from=log)
        self.assertIn("ERROR boom", cause)
        self.assertTrue(by.startswith("plain lines"))
        with mock.patch.object(tasks, "model_answer", return_value=("the cause", "fake")):
            fa.revoke(os.path.join(self.dir, "logs"))
            self.assertEqual(tasks.explain("x", "ERROR", {"explain": True}, read_from=log), ("the cause", "fake"))


class Phone(unittest.TestCase):
    def test_the_phone_asks_as_the_phone(self):
        a_mod = phone_ask.assistant()
        turn = {"question": "", "answer": "fine", "pending": None, "done": [], "lang": "en"}
        with mock.patch.object(a_mod, "settings", return_value=dict(a_mod.DEFAULTS)), \
                mock.patch.object(a_mod, "run_turn", return_value=turn) as run:
            phone_ask.ask_assistant("read my notes", True, [], dry_run=True)
        self.assertEqual(run.call_args.kwargs.get("who"), "phone")


if __name__ == "__main__":
    unittest.main()
