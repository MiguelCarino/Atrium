"""scripts/tasks.py: the tasks' strict checking, schedules and when they are
due, the permissions they show, the plain-words path with the model stubbed
(a command or address must be in the sentence), the web value readers
(selector, numbers, compare), the tidy plan / approve / undo inside a
scratch home, the watchers (a log file, a unit's readings, a command's exit),
the bar line, and Settings > Background tasks' pure helpers.

Hermetic: tasks.json is a scratch path (tasks.CONFIG), the state is
helpers.py's scratch XDG_STATE_HOME, HOME is a scratch folder for the tidy
tests, no model is asked (model_answer is stubbed), notify() and the bar
signal are stubbed, nothing is fetched (fetch is stubbed), and the only
command run is `sh -c "echo …; exit 3"` in the scratch folder."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

import helpers

T = helpers.import_script("tasks.py", "tasks")
T.notify = lambda *a, **k: None
T.signal_bar = lambda: None
T.log = lambda text: None
T.model_answer = lambda prompt, system, conf=None: (None, "stubbed")
T.gamemode_on = lambda: False


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tasks-test-")
        self.old = (T.CONFIG, T.STATE_DIR, T.HOME, T.DAEMON_STATE, T.POKES)
        T.CONFIG = os.path.join(self.dir, "tasks.json")
        T.STATE_DIR = os.path.join(self.dir, "state")
        T.HOME = os.path.join(self.dir, "home")
        T.DAEMON_STATE = os.path.join(self.dir, "daemon.json")
        T.POKES = os.path.join(self.dir, "pokes")
        os.makedirs(os.path.join(T.HOME, "Downloads"))
        os.makedirs(os.path.join(T.HOME, "logs"))

    def tearDown(self):
        T.CONFIG, T.STATE_DIR, T.HOME, T.DAEMON_STATE, T.POKES = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def home(self, *parts):
        return os.path.join(T.HOME, *parts)


class Schedules(Base):
    def test_parse_and_tidy(self):
        for text, tidy in (("every 30 minutes", "every 30m"), ("every 2h", "every 2h"), ("every 1 day", "every 1d"),
                           ("daily 8:05", "daily 08:05"), ("weekdays at 09:00", "weekdays 09:00"),
                           ("Mon,Thu 18:30", "mon,thu 18:30"), ("08:00", "daily 08:00"),
                           ("every day at 07:00", "daily 07:00"), ("watch", "watch"), ("on-event", "on-event")):
            self.assertEqual(T.schedule_text(T.parse_schedule(text)), tidy, text)

    def test_refuses(self):
        for bad in ("every 1m", "every 90d", "daily 25:00", "funday 08:00", "sometimes", ""):
            with self.assertRaises(ValueError, msg=bad):
                T.parse_schedule(bad)

    def test_due(self):
        now = time.mktime((2026, 10, 21, 9, 0, 0, 0, 0, -1))   # a Wednesday, 09:00
        every = {"schedule": "every 1h", "created": now - 7200}
        self.assertTrue(T.due(every, {}, now))                                  # never ran: now
        self.assertFalse(T.due(every, {"last_run": now - 600}, now))
        self.assertTrue(T.due(every, {"last_run": now - 3600}, now))
        at = {"schedule": "daily 08:00", "created": now - 86400 * 3}
        self.assertTrue(T.due(at, {"last_run": now - 86400}, now))              # 08:00 today passed
        self.assertFalse(T.due(at, {"last_run": now - 1800}, now))              # ran at 08:30
        self.assertFalse(T.due({"schedule": "daily 08:00", "created": now - 60}, {}, now))  # made after 08:00
        self.assertFalse(T.due({"schedule": "weekends 08:00", "created": now - 3600 * 30},
                               {}, now))                                         # Sat/Sun only
        once = {"schedule": "once", "created": now}
        self.assertTrue(T.due(once, {}, now))
        self.assertFalse(T.due(once, {"last_run": now - 5}, now))
        self.assertTrue(T.due(once, {"last_run": now - 50, "resumed": now - 5}, now))
        for kind in ("watch", "manual", "on-event"):
            self.assertFalse(T.due({"schedule": kind, "created": 0}, {}, now))


class Validate(Base):
    def test_good_task_is_tidied_with_defaults(self):
        tidy, problems = T.validate({"name": "Build", "type": "watch-command",
                                     "params": {"command": " make -j24 ", "cwd": self.home("logs")}})
        self.assertEqual(problems, [])
        self.assertEqual(tidy["params"], {"command": "make -j24", "cwd": "~/logs", "lines": 40})
        self.assertEqual(tidy["schedule"], "once")

    def test_strict(self):
        _, problems = T.validate({"type": "watch-command", "params": {"command": "x", "shell": True},
                                  "schedule": "watch", "extra": 1})
        text = " | ".join(problems)
        for bit in ("unknown key 'extra'", "no param 'shell'", "watch-command runs"):
            self.assertIn(bit, text)
        self.assertTrue(T.validate({"type": "rm-rf", "params": {}})[1])
        self.assertTrue(T.validate({"type": "watch-url", "params": {"url": "file:///etc/passwd"}})[1])
        self.assertTrue(T.validate({"type": "watch-url", "params": {"url": "https://a.b", "when": "drops"}})[1])
        self.assertTrue(T.validate({"type": "watch-url", "params": {"url": "https://a.b", "when": "below",
                                                                    "selector": ".p"}})[1])
        self.assertTrue(T.validate({"type": "watch-command", "params": {"command": "a\nb"}})[1])
        self.assertTrue(T.validate({"type": "watch-command", "params": {"command": "ls", "cwd": "/etc"}})[1])
        self.assertTrue(T.validate({"type": "summarise-folder", "params": {"folder": self.home("logs"),
                                                                           "pattern": "../*"}})[1])

    def test_tidy_folder_limits(self):
        ok = T.validate({"type": "organise-folder", "params": {"folder": self.home("Downloads")}})
        self.assertEqual(ok[1], [])
        self.assertEqual(ok[0]["schedule"], "daily 03:00")
        os.makedirs(self.home(".config"))
        os.makedirs(self.home("repo", ".git"))
        os.makedirs(self.home("repo", "sub"))
        for folder, why in ((T.HOME, "whole home"), (self.home(".config"), "hidden"),
                            (self.home("repo", "sub"), "git work tree"), ("/tmp", "inside your home")):
            _, problems = T.validate({"type": "organise-folder", "params": {"folder": folder}})
            self.assertTrue(any(why in p for p in problems), (folder, problems))

    def test_unit_names(self):
        tidy, _ = T.validate({"type": "watch-unit", "params": {"unit": "backup"}})
        self.assertEqual(tidy["params"]["unit"], "backup.service")
        self.assertTrue(T.validate({"type": "watch-unit", "params": {"unit": "a;rm -rf ~"}})[1])

    def test_permissions_and_words(self):
        tidy, _ = T.validate({"name": "Price", "type": "watch-url",
                              "params": {"url": "https://shop.example/x", "selector": ".price", "when": "drops"},
                              "schedule": "every 1h"})
        self.assertIn("shop.example", T.describe(tidy))
        self.assertIn("every hour", T.describe(tidy))
        self.assertTrue(any("fetches https://shop.example/x" in p for p in T.permissions(tidy)))
        cmd, _ = T.validate({"type": "watch-command", "params": {"command": "deploy --token=abc123secret"}})
        self.assertNotIn("abc123secret", " ".join(T.permissions(cmd)) + T.describe(cmd))


class Store(Base):
    def test_add_find_pause_delete(self):
        t = T.add({"name": "Tidy downloads", "type": "organise-folder", "params": {"folder": self.home("Downloads")}})
        self.assertEqual(t["id"], "tidy-downloads")
        t2 = T.add({"name": "Tidy downloads", "type": "organise-folder", "params": {"folder": self.home("Downloads")}})
        self.assertEqual(t2["id"], "tidy-downloads-2")
        good, bad = T.load()
        self.assertEqual((len(good), bad), (2, []))
        self.assertEqual(T.find(good, "tidy downloads")["id"], "tidy-downloads")
        T.set_enabled("tidy-downloads", False)
        self.assertFalse(T.find(T.load()[0], "tidy-downloads")["enabled"])
        with open(T.CONFIG) as handle:
            self.assertIn("_doc", json.load(handle))
        self.assertTrue(T.read_log("tidy-downloads"))
        self.assertTrue(T.remove("tidy-downloads"))
        self.assertFalse(os.path.exists(T.path_for("tidy-downloads", "log")))
        self.assertEqual(len(T.load()[0]), 1)
        with self.assertRaises(ValueError):
            T.add({"type": "watch-url", "params": {"url": "https://a.b"}, "schedule": "every 5m"})  # < 15 min

    def test_settings(self):
        self.assertEqual(T.settings(), T.DEFAULTS)
        T.set_setting("explain", "off")
        T.set_setting("url_min_minutes", "30")
        self.assertEqual((T.settings()["explain"], T.settings()["url_min_minutes"]), (False, 30))
        for key, value in (("explain", "maybe"), ("url_min_minutes", "1"), ("nope", "on")):
            with self.assertRaises(ValueError):
                T.set_setting(key, value)

    def test_bar_only_when_needed(self):
        self.assertEqual(T.bar_json()["text"], "")
        t = T.add({"type": "summarise-folder", "params": {"folder": self.home("logs")}})
        T.set_attention(t["id"], "it broke")
        bar = T.bar_json()
        self.assertIn("1", bar["text"])
        self.assertIn("it broke", bar["tooltip"])
        T.set_setting("enabled", "off")
        self.assertEqual(T.bar_json()["text"], "")

    def test_secrets_are_masked_in_logs(self):
        T.append_log("x", "curl -H 'Authorization: Bearer abcdefghijklmnop' https://u:pw@host/ password=hunter2")
        text = "".join(T.read_log("x"))
        for secret in ("abcdefghijklmnop", "hunter2", ":pw@"):
            self.assertNotIn(secret, text)


class FromText(Base):
    def answer(self, data):
        return lambda prompt: json.dumps(data)

    def test_url_task(self):
        t, why = T.from_text("check https://shop.example/item every hour and tell me if the price drops",
                             ask=self.answer({"name": "Price", "type": "watch-url",
                                              "params": {"url": "https://shop.example/item", "find": "the price",
                                                         "when": "drops"}, "schedule": "every 1h"}))
        self.assertIsNone(why)
        self.assertEqual(t["type"], "watch-url")
        self.assertEqual(t["source"], "text")

    def test_command_must_be_typed_by_you(self):
        said = "watch `make -j24` in ~/logs and tell me when it fails"
        t, why = T.from_text(said, ask=self.answer({"type": "watch-command",
                                                    "params": {"command": "make -j24", "cwd": self.home("logs")}}))
        self.assertIsNone(why, why)
        self.assertEqual(t["params"]["command"], "make -j24")
        t, why = T.from_text(said, ask=self.answer({"type": "watch-command",
                                                    "params": {"command": "make -j24 && rm -rf ~"}}))
        self.assertIsNone(t)
        self.assertIn("only when you typed it", why)

    def test_invented_address_and_bad_answers(self):
        t, why = T.from_text("tell me when the price of my GPU drops",
                             ask=self.answer({"type": "watch-url", "params": {"url": "https://evil.example",
                                                                              "find": "price", "when": "drops"}}))
        self.assertIsNone(t)
        self.assertIn("address", why)
        self.assertIn("cannot", T.from_text("x", ask=self.answer({"error": "no such thing"}))[1])
        self.assertIn("not a task", T.from_text("x", ask=lambda p: "sure!")[1])
        self.assertIn("does not check out", T.from_text("x", ask=self.answer({"type": "launch-missiles"}))[1])
        self.assertIn("watch-window", T.from_text("x", ask=self.answer({"type": "watch-process",
                                                                        "params": {"pid": 5}}))[1])

    def test_prompt_lists_the_catalog(self):
        prompt = T.model_prompt("hi")
        for kind in ("watch-command", "watch-url", "organise-folder", "summarise-folder"):
            self.assertIn(kind, prompt)
        self.assertNotIn("watch-process", prompt)


class Web(unittest.TestCase):
    PAGE = """<html><head><meta itemprop="price" content="1299.00"><script>var price = 1;</script></head>
    <body><div class="product main"><h1 id="t">GPU</h1><span class="price">$1,299.00</span></div>
    <div class="other"><span class="price">$5</span></div><br><p>Ships <b>today</b></p></body></html>"""

    def test_selectors(self):
        self.assertEqual(T.select(self.PAGE, ".price"), "$1,299.00")
        self.assertEqual(T.select(self.PAGE, "div.other span.price"), "$5")
        self.assertEqual(T.select(self.PAGE, "#t"), "GPU")
        self.assertEqual(T.select(self.PAGE, "meta[itemprop=price]"), "1299.00")
        self.assertEqual(T.select(self.PAGE, "p"), "Ships today")
        self.assertIsNone(T.select(self.PAGE, ".nothing"))
        with self.assertRaises(ValueError):
            T.parse_selector("a > b")
        self.assertNotIn("var price", T.page_text(self.PAGE))

    def test_numbers(self):
        for text, n in (("$1,299.00", 1299.0), ("1.299,50 €", 1299.5), ("12,5", 12.5), ("MXN 15 999", 15999.0),
                        ("1.234.567", 1234567.0), ("-3", -3.0), ("price: 42", 42.0), ("none", None)):
            self.assertEqual(T.parse_number(text), n, text)

    def test_compare(self):
        self.assertEqual(T.compare("drops", "$1,299", "$1,199")[0], True)
        self.assertEqual(T.compare("drops", "$1,199", "$1,299")[0], False)
        self.assertEqual(T.compare("drops", None, "$1,199")[0], False)             # first reading
        self.assertEqual(T.compare("rises", "1", "2")[0], True)
        self.assertEqual(T.compare("changes", "a", "b")[0], True)
        self.assertEqual(T.compare("changes", "a", "a")[0], False)
        self.assertEqual(T.compare("below", "1100", "999", 1000)[0], True)         # crossed
        self.assertEqual(T.compare("below", "990", "980", 1000)[0], False)         # already below: told once

    def test_redirects_stay_on_the_site(self):
        self.assertTrue(T.same_site("www.shop.mx", "shop.mx"))
        self.assertFalse(T.same_site("evil.example", "shop.mx"))
        handler = T.SameSiteRedirects("https://shop.mx/item")
        req = T.urllib.request.Request("https://shop.mx/item")
        with self.assertRaises(T.urllib.error.URLError):
            handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/x")
        with self.assertRaises(T.urllib.error.URLError):
            handler.redirect_request(req, None, 302, "Found", {}, "ftp://shop.mx/x")
        ok = handler.redirect_request(req, None, 302, "Found", {}, "/item?ref=1")
        self.assertEqual(ok.full_url, "https://shop.mx/item?ref=1")

    def test_read_value(self):
        self.assertEqual(T.read_value({"selector": ".price"}, self.PAGE), ("$1,299.00", None))
        self.assertEqual(T.read_value({"pattern": r"Ships (\w+)"}, self.PAGE), ("today", None))
        self.assertIsNone(T.read_value({"find": "the price"}, self.PAGE)[0])     # the model is stubbed off

    def test_job_url_tells_on_drop(self):
        told = []
        old = (T.fetch, T.notify, T.STATE_DIR)
        T.STATE_DIR = tempfile.mkdtemp()
        T.notify = lambda summary, body, **k: told.append(summary)
        try:
            task = {"id": "p", "name": "Price", "type": "watch-url",
                    "params": {"url": "https://x.example", "selector": ".price", "when": "drops"}}
            for price in ("$10", "$12", "$9"):
                T.fetch = lambda url, price=price: f'<span class="price">{price}</span>'
                T.job_url(task, T.DEFAULTS)
            self.assertEqual(len(told), 1)
            self.assertIn("dropped from 12 to 9", told[0])
            self.assertEqual(T.get_state("p")["last_value"], "$9")
        finally:
            shutil.rmtree(T.STATE_DIR, ignore_errors=True)
            T.fetch, T.notify, T.STATE_DIR = old


class Tidy(Base):
    def make(self, name, age_days=5, folder="Downloads"):
        path = self.home(folder, name)
        with open(path, "w") as handle:
            handle.write(name)
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
        return path

    def test_plan_approve_undo(self):
        for name in ("a.pdf", "b.PNG", "c.tar.gz", "unknown.xyz", ".hidden.pdf", "half.pdf.part"):
            self.make(name)
        self.make("new.pdf", age_days=0)
        os.makedirs(self.home("Downloads", "Documents"))
        self.make("a.pdf", folder="Downloads/Documents")       # a name clash: never overwritten
        task, _ = T.validate({"id": "tidy", "type": "organise-folder", "params": {"folder": self.home("Downloads")}})
        T.job_organise(task, T.DEFAULTS)
        plan = T.read_plan("tidy")
        moved = {os.path.basename(m["from"]): os.path.relpath(m["to"], self.home("Downloads")) for m in plan["moves"]}
        self.assertEqual(moved, {"a.pdf": "Documents/a (2).pdf", "b.PNG": "Images/b.PNG",
                                 "c.tar.gz": "Archives/c.tar.gz"})
        self.assertTrue(T.get_state("tidy")["attention"]["plan"])
        self.assertTrue(os.path.exists(self.home("Downloads", "a.pdf")))         # nothing moved yet

        n, problems = T.approve(task)
        self.assertEqual((n, problems), (3, []))
        self.assertTrue(os.path.exists(self.home("Downloads", "Images", "b.PNG")))
        self.assertTrue(os.path.exists(self.home("Downloads", "Documents", "a.pdf")))   # the old one untouched
        self.assertIsNone(T.read_plan("tidy"))
        self.assertNotIn("attention", T.get_state("tidy"))

        back, problems = T.undo(task)
        self.assertEqual((back, problems), (3, []))
        for name in ("a.pdf", "b.PNG", "c.tar.gz"):
            self.assertTrue(os.path.exists(self.home("Downloads", name)), name)
        self.assertFalse(T.has_undo("tidy"))

    def test_moves_never_leave_the_folder(self):
        src = self.make("x.pdf")
        with self.assertRaises(ValueError):
            T.safe_move(src, self.home("logs", "x.pdf"), self.home("Downloads"))
        with self.assertRaises(ValueError):
            T.safe_move(src, "/tmp/x.pdf", self.home("Downloads"))

    def test_by_month(self):
        self.make("a.xyz", age_days=40)
        moves = T.make_plan({"folder": self.home("Downloads"), "by": "month", "older_than_days": 1})
        self.assertRegex(os.path.basename(os.path.dirname(moves[0]["to"])), r"^\d{4}-\d{2}$")


class Summarise(Base):
    def test_plain_summary_without_the_model(self):
        with open(self.home("logs", "app.log"), "w") as handle:
            handle.write("ok\nWARNING slow\nERROR db down\nok\n")
        with open(self.home("logs", "skip.txt"), "w") as handle:
            handle.write("ERROR not matched by the pattern\n")
        task, _ = T.validate({"id": "s", "type": "summarise-folder", "params": {"folder": self.home("logs")}})
        T.job_summarise(task, T.DEFAULTS)
        with open(T.path_for("s", "report.txt")) as handle:
            report = handle.read()
        self.assertIn("app.log: 1 error lines, 1 warnings", report)
        self.assertIn("ERROR db down", report)
        self.assertNotIn("skip.txt", report)
        T.job_summarise(task, T.DEFAULTS)                          # nothing changed since
        self.assertEqual(T.get_state("s")["last_summary"], "nothing changed")


class Watchers(Base):
    def daemon(self, *tasks):
        d = T.Daemon()
        d.tasks = list(tasks)
        d.conf = dict(T.DEFAULTS)
        return d

    def test_file_alerts_once_on_new_error_lines(self):
        path = self.home("logs", "build.log")
        with open(path, "w") as handle:
            handle.write("old ERROR before watching\n")
        task, _ = T.validate({"id": "f", "type": "watch-file", "params": {"path": path}})
        d = self.daemon(task)
        d.check_file(task, 100)                                  # starts at the end
        self.assertTrue(d.jobs.empty())
        with open(path, "a") as handle:
            handle.write("compiling\nerror: undefined reference to foo\n")
        d.check_file(task, 101)
        d.check_file(task, 101 + T.SETTLE_S)
        self.assertEqual(d.jobs.qsize(), 1)
        tid, fn, args = d.jobs.get()
        fn(*args)
        st = T.get_state("f")
        self.assertIn("undefined reference", st["attention"]["text"])
        with open(path, "a") as handle:
            handle.write("error again\n")
        d.check_file(task, 110)
        d.check_file(task, 110 + T.SETTLE_S)
        self.assertTrue(d.jobs.empty())                          # within ALERT_GAP_S

    def test_unit_readings(self):
        a = {"ActiveState": "active", "Result": "success", "NRestarts": "0"}
        self.assertEqual(T.unit_failed(None, a), (False, ""))
        self.assertTrue(T.unit_failed(a, dict(a, ActiveState="failed", Result="exit-code"))[0])
        self.assertTrue(T.unit_failed(a, dict(a, NRestarts="1"))[0])
        self.assertFalse(T.unit_failed(a, a)[0])

    def test_command_exit_is_explained(self):
        task, _ = T.validate({"id": "c", "name": "Build", "type": "watch-command",
                              "params": {"command": "echo compiling; echo 'error: missing ;' ; exit 3",
                                         "cwd": self.home("logs")}})
        d = self.daemon(task)
        d.start(task, by="test")
        self.assertIn("c", d.running)
        d.running["c"][0].wait(10)
        d.reap(time.time())
        self.assertEqual(d.jobs.qsize(), 1)
        _, fn, args = d.jobs.get()
        fn(*args)
        st = T.get_state("c")
        self.assertEqual(st["last_result"], "failed")
        self.assertIn("exit 3", st["attention"]["text"])
        self.assertIn("error: missing ;", "".join(T.read_log("c")))

    def test_heavy_work_waits_for_gamemode(self):
        task, _ = T.validate({"id": "s", "type": "summarise-folder", "params": {"folder": self.home("logs")},
                              "schedule": "every 1h"})
        d = self.daemon(task)
        d.game = (time.time(), True)
        d.tick(time.time())
        self.assertTrue(d.jobs.empty())
        self.assertEqual(T.get_state("s")["status"], "waiting: gamemode")
        d.game = (time.time(), False)
        d.tick(time.time())
        self.assertEqual(d.jobs.qsize(), 1)

    def test_unit_failure_says_how(self):
        task, _ = T.validate({"id": "u", "type": "watch-unit", "params": {"unit": "backup"}})
        d = self.daemon(task)
        readings = iter([{"ActiveState": "active", "Result": "success", "NRestarts": "0"},
                         {"ActiveState": "failed", "Result": "exit-code", "NRestarts": "0"}])
        old = (T.unit_status, T.journal)
        T.unit_status, T.journal = lambda p: next(readings), lambda p: "boom: exit 1"
        try:
            d.check_unit(task, 1000)
            d.check_unit(task, 1000 + T.UNIT_POLL_S)
        finally:
            T.unit_status, T.journal = old
        _, fn, args = d.jobs.get_nowait()
        fn(*args)
        # The alert says what happened, not the "watching (failed)" status line.
        self.assertIn("backup.service failed (exit-code)", T.get_state("u")["attention"]["text"])

    def test_unit_name_is_never_an_option(self):
        for bad in ("-Hhost.service", "--user", "-x"):
            self.assertTrue(T.validate({"type": "watch-unit", "params": {"unit": bad}})[1], bad)

    def test_deleted_while_running_is_stopped_quietly(self):
        T.add({"id": "c", "type": "watch-command", "params": {"command": "sleep 30", "cwd": self.home()},
               "schedule": "manual"})
        task = T.find(T.load()[0], "c")
        d = self.daemon(task)
        d.start(task, by="test")
        proc = d.running["c"][0]
        told = []
        old = T.notify
        T.notify = lambda *a, **k: told.append(a)
        try:
            T.remove("c")
            d.mtime = -1                # tasks.json changed: reload() reads it again
            d.reload()
            self.assertIsNotNone(proc.wait(5))
            d.reap(time.time())
        finally:
            T.notify = old
        self.assertNotIn("c", d.running)
        self.assertEqual(told, [])
        self.assertFalse(os.path.exists(T.path_for("c", "json")))
        self.assertTrue(d.jobs.empty())

    def test_a_job_that_raises_is_not_rerun_every_tick(self):
        task, _ = T.validate({"id": "s", "type": "summarise-folder", "params": {"folder": self.home("logs")},
                              "schedule": "every 1h"})
        d = self.daemon(task)

        def boom(t, c):
            raise RuntimeError("disk on fire")
        d.jobs.put(("gone", boom, (task, d.conf)))          # a deleted task's job: skipped
        d.jobs.put(("s", boom, (task, d.conf)))
        threading.Thread(target=d.work, daemon=True).start()
        for _ in range(250):
            if T.get_state("s").get("last_result") and d.busy is None:
                break
            time.sleep(0.02)
        st = T.get_state("s")
        self.assertEqual(st["last_result"], "failed")
        self.assertFalse(T.due(task, st, time.time()))
        self.assertEqual(T.get_state("gone"), {})

    def test_restart_marks_interrupted_work(self):
        task, _ = T.validate({"id": "c", "type": "watch-command", "params": {"command": "make"},
                              "schedule": "once"})
        T.update_state("c", status="running", pid=12345)
        d = self.daemon(task)
        d.recover()
        st = T.get_state("c")
        self.assertNotIn("status", st)
        self.assertEqual(st["last_result"], "stopped")
        self.assertFalse(T.due(task, st, time.time()))     # a "once" command is not run again by itself

    def test_process_ending(self):
        task, _ = T.validate({"id": "p", "type": "watch-process", "params": {"pid": 4194300, "label": "x"}})
        T.add(dict(task, id="p"))
        d = self.daemon(task)
        d.check_process(task)
        self.assertEqual(T.get_state("p")["status"], "done")
        self.assertFalse(T.find(T.load()[0], "p")["enabled"])
        self.assertIsNotNone(T.proc_start(os.getpid()))


class SettingsPage(unittest.TestCase):
    def setUp(self):
        try:
            import settings_pages.tasks as page
        except Exception as err:        # no GTK on this machine
            self.skipTest(f"no GTK: {err}")
        self.page = page

    def test_words(self):
        now = time.time()
        self.assertEqual(self.page.when_text(None), "has not run yet")
        self.assertEqual(self.page.when_text(now - 30, now), "ran just now")
        row = {"words": "Do it -- every hour", "status": "idle", "runnable": True, "last_run": now - 600,
               "last_summary": "3 moves", "permissions": ["reads ~/x", "notifies you"]}
        sub = self.page.task_sub(row, now)
        self.assertIn("ran 10 min ago", sub)
        self.assertNotIn("May:", sub)                        # folded under the row instead
        self.assertEqual(self.page.task_may(row), "May: reads ~/x; notifies you")

    def test_hand_task(self):
        t = self.page.hand_task("watch-command", {"command": " make ", "cwd": "", "lines": ""}, "", "")
        self.assertEqual(t, {"name": "Watch command", "type": "watch-command", "params": {"command": "make"},
                             "enabled": True})
        self.assertEqual(self.page.hand_task("watch-url", {"url": "https://x"}, "every 1h", "P")["schedule"],
                         "every 1h")


if __name__ == "__main__":
    unittest.main()
