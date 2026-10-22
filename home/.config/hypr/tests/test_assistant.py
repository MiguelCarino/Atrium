"""scripts/assistant.py (the desktop assistant): its settings, the tool
loop with a stubbed model (tool calls checked, results fed back, the step
limit, switched-off and unknown tools, a reply that is not JSON), the
arguments' checks, the actions that run at once or wait for Confirm (and
the confirm itself), read_file's rules (named files only, secrets, binary,
the size cap, secret lines), repo_changes on a scratch git repo,
look_at_screen with the capture and the vision model stubbed (the panel
steps aside, the screenshots go), the history (kept, pruned, forgotten,
never written at 0 days), the desktop-memory switch, the speak() hook, the
launcher's rows and the Settings page's helpers.

Hermetic: no model is asked (a stub answers), nothing captured, no action
run (voice-command.py's execute is a stub), state in helpers.py's scratch
XDG_STATE_HOME / XDG_RUNTIME_DIR."""
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import helpers

a = helpers.import_script("assistant.py")


class FakeWorld:
    def __init__(self, clients=()):
        self._clients = list(clients)

    def clients(self):
        return self._clients

    def monitors(self):
        return [{"activeWorkspace": {"id": 1, "name": "1"}}]

    def private(self):
        return set()

    def active(self):
        return {"address": "0x1"}

    def themes(self):
        return ["matrix", "aero"]

    def sessions(self):
        return []

    def contexts(self):
        return ["Atlas"]


def script(*replies):
    """A stub model: each call returns the next reply; the calls are kept."""
    calls = []
    replies = list(replies)

    def chat(messages, names):
        calls.append({"messages": [dict(m) for m in messages], "names": list(names)})
        reply = replies.pop(0) if replies else '{"tool": "answer", "answer": "out of replies"}'
        return reply if isinstance(reply, str) else json.dumps(reply)
    return chat, calls


def conf(**changes):
    return dict(a.DEFAULTS, **changes)


class Clean(unittest.TestCase):
    def setUp(self):
        for path in (a.SETTINGS, a.HISTORY):
            if os.path.exists(path):
                os.remove(path)
        a.clear()

    tearDown = setUp


class Settings(Clean):
    def test_defaults(self):
        c = a.settings()
        self.assertEqual((c["enabled"], c["model"], c["max_steps"], c["confirm"], c["history_days"]),
                         ("on", "auto", 6, "risky", 7))
        self.assertEqual(c["voice_reply"], "off")
        self.assertTrue(all(c[f"tool_{g}"] == "on" for g in a.TOOL_GROUPS))

    def test_set_and_refuse(self):
        self.assertEqual(a.set_setting("max_steps", "3"), 3)
        self.assertEqual(a.set_setting("history_days", "30"), 30)
        a.set_setting("tool_screen", "off")
        c = a.settings()
        self.assertEqual((c["max_steps"], c["history_days"], c["tool_screen"]), (3, 30, "off"))
        self.assertNotIn("look_at_screen", a.tools_on(c))
        for key, value in (("max_steps", "1"), ("max_steps", "x"), ("model", "opus"), ("history_days", "5"),
                           ("confirm", "never"), ("nope", "on"), ("tool_shell", "on")):
            with self.assertRaises(ValueError, msg=(key, value)):
                a.set_setting(key, value)

    def test_bad_file_falls_back(self):
        os.makedirs(a.DIR, exist_ok=True)
        with open(a.SETTINGS, "w") as handle:
            json.dump({"max_steps": 99, "model": "cloud", "confirm": "all"}, handle)
        c = a.settings()
        self.assertEqual((c["max_steps"], c["model"], c["confirm"]), (6, "auto", "all"))


class Args(unittest.TestCase):
    def test_types_and_choices(self):
        self.assertEqual(a.check_args("project", {"op": "CURRENT", "junk": 1}), {"op": "current"})
        with self.assertRaises(a.ToolError):
            a.check_args("project", {"op": "delete"})
        with self.assertRaises(a.ToolError):
            a.check_args("project", {})
        with self.assertRaises(a.ToolError):
            a.check_args("search_activity", {"start": "yesterday", "end": "2026-10-21T10:00"})
        self.assertEqual(a.check_args("search_meaning", {"query": "x", "k": 99})["k"], 15)
        self.assertEqual(a.check_args("look_at_screen", {"apps": "firefox and kitty"})["apps"], ["firefox", "kitty"])
        self.assertEqual(len(a.check_args("do_actions", {"actions": [{"action": "x"}] * 9})["actions"]), 6)
        with self.assertRaises(a.ToolError):
            a.check_args("shell", {"cmd": "rm -rf ~"})

    def test_parse_reply(self):
        self.assertEqual(a.parse_reply('{"tool": "timers", "args": {}}')["tool"], "timers")
        got = a.parse_reply("Sure! Here it is.")
        self.assertEqual((got["tool"], got["answer"]), ("answer", "Sure! Here it is."))
        self.assertEqual(a.parse_reply('x {"tool": "brief", "args": "no"} y')["args"], {})

    def test_step_lines_speak_both_languages(self):
        self.assertIn("Atlas", a.step_line("repo_changes", {"repo": "Atlas", "since": "today"}))
        self.assertTrue(a.step_line("timers", {}, "es").startswith("leí"))
        self.assertIn("09:00", a.step_line("search_activity", {"start": "2026-10-21T09:00",
                                                                "end": "2026-10-21T12:00"}))

    def test_prompt_lists_only_the_tools_that_are_on(self):
        import datetime
        c = conf(tool_files="off", tool_actions="off")
        text = a.system_prompt(c, "es", datetime.datetime(2026, 10, 21, 9, 0))
        self.assertNotIn("read_file", text)
        self.assertNotIn("ACTIONS for do_actions", text)
        self.assertIn("project(op: current|list|enter|leave", text)
        self.assertIn("yesterday", text)            # 09:00: lunch is still to come today
        self.assertIn("Spanish", text)


class Loop(Clean):
    def run_turn(self, *replies, **kw):
        chat, calls = script(*replies)
        steps = []
        turn = a.run_turn(kw.pop("question", "what is set?"), kw.pop("conf", conf(history_days=0)),
                          history=kw.pop("history", []), chat=chat, world=FakeWorld(),
                          on_step=lambda s: steps.append(s), **kw)
        return turn, calls, steps

    def test_tool_then_answer(self):
        with mock.patch.object(a, "script_json", return_value=[{"id": "t1", "label": "tea"}]):
            turn, calls, steps = self.run_turn({"tool": "timers", "args": {}},
                                               {"tool": "answer", "answer": "One timer: tea."})
        self.assertEqual(turn["answer"], "One timer: tea.")
        self.assertEqual([s["tool"] for s in turn["steps"]], ["timers"])
        self.assertTrue(turn["steps"][0]["ok"])
        self.assertEqual([s.get("running", False) for s in steps], [True, False])
        self.assertIn("Result of timers", calls[1]["messages"][-1]["content"])
        self.assertIn("tea", calls[1]["messages"][-1]["content"])
        self.assertIn("timers", calls[0]["names"])

    def test_switched_off_and_unknown_tools_are_refused_and_said(self):
        with mock.patch.object(a, "t_brief") as brief:
            turn, calls, _ = self.run_turn({"tool": "brief", "args": {}}, {"tool": "shell", "args": {"cmd": "ls"}},
                                           {"tool": "answer", "answer": "ok"},
                                           conf=conf(history_days=0, tool_brief="off"))
        brief.assert_not_called()
        self.assertEqual([s["ok"] for s in turn["steps"]], [False, False])
        self.assertIn("switched off", calls[1]["messages"][-1]["content"])
        self.assertIn("there is no tool", calls[2]["messages"][-1]["content"])

    def test_bad_arguments_are_refused_before_running(self):
        with mock.patch.object(a, "t_project") as project:
            turn, calls, _ = self.run_turn({"tool": "project", "args": {"op": "rm"}}, {"tool": "answer", "answer": "x"})
        project.assert_not_called()
        self.assertIn("op is one of", calls[1]["messages"][-1]["content"])

    def test_step_limit_forces_an_answer(self):
        with mock.patch.object(a, "script_json", return_value=[]):
            turn, calls, _ = self.run_turn(*([{"tool": "timers", "args": {}}] * 5),
                                           {"tool": "answer", "answer": "done looking"},
                                           conf=conf(history_days=0, max_steps=2))
        self.assertEqual(len(turn["steps"]), 2)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[-1]["names"], [])        # the schema allows only "answer" now
        self.assertIn("Now answer", calls[-1]["messages"][-1]["content"])

    def test_plain_text_reply_is_the_answer(self):
        turn, _, _ = self.run_turn("You have nothing set.")
        self.assertEqual(turn["answer"], "You have nothing set.")

    def test_off(self):
        turn, calls, _ = self.run_turn({"tool": "timers"}, conf=conf(enabled="off"))
        self.assertEqual(calls, [])
        self.assertIn("turned off", turn["answer"])

    def test_model_error_is_said(self):
        def chat(messages, names):
            raise OSError("connection refused")
        turn = a.run_turn("hola", conf(history_days=0), history=[], chat=chat, world=FakeWorld())
        self.assertIn("did not answer", turn["answer"])

    def test_history_goes_in_as_context(self):
        hist = [{"question": "q1", "answer": "a1", "t": time.time()}]
        _, calls, _ = self.run_turn({"tool": "answer", "answer": "a2"}, history=hist)
        texts = [m["content"] for m in calls[0]["messages"]]
        self.assertIn("q1", texts)
        self.assertTrue(any("a1" in t for t in texts))


class Actions(Clean):
    def step(self, say, confirm=""):
        return {"action": "x", "say": say, "confirm": confirm, "ops": [("argv", ["true"])], "undo": None}

    def test_safe_actions_run_and_leave_an_undo(self):
        vc = a.vc()
        with mock.patch.object(a, "plan_actions", return_value=([self.step("go to workspace 2")], [])), \
                mock.patch.object(vc, "execute", return_value=([], [("lua", "back")])) as execute:
            chat, _ = script({"tool": "do_actions", "args": {"actions": [{"action": "workspace", "workspace": 2}]}},
                             {"tool": "answer", "answer": "Done."})
            turn = a.run_turn("ve al escritorio 2", conf(history_days=0), history=[], chat=chat, world=FakeWorld())
        execute.assert_called_once()
        self.assertEqual(turn["done"], ["go to workspace 2"])
        self.assertEqual(turn["undo"], [("lua", "back")])
        self.assertIsNone(turn["pending"])

    def test_risky_actions_wait_for_confirm(self):
        vc = a.vc()
        plan = ([self.step("close Firefox", "not on a workspace you can see")], [])
        with mock.patch.object(a, "plan_actions", return_value=plan), \
                mock.patch.object(vc, "execute", return_value=([], [])) as execute:
            chat, calls = script({"tool": "do_actions", "args": {"actions": [{"action": "close", "app": "firefox"}]}},
                                 {"tool": "do_actions", "args": {"actions": [{"action": "theme", "value": "aero"}]}},
                                 {"tool": "answer", "answer": "I closed Firefox."})
            turn = a.run_turn("close firefox", conf(history_days=0), history=[], chat=chat, world=FakeWorld())
            execute.assert_not_called()
            pending = turn["pending"]
            self.assertTrue(pending and pending["lines"][0].startswith("close Firefox"))
            self.assertIn("NOT DONE YET", calls[1]["messages"][-1]["content"])
            self.assertIn("already waiting", calls[2]["messages"][-1]["content"])     # no second plan
            self.assertIn("Not done yet", turn["answer"])           # whatever the model claimed
            self.assertTrue(os.path.exists(a._pending_path(pending["id"])))
            lines, problems, _undo = a.confirm(pending["id"], world=FakeWorld())
            execute.assert_called_once()
            self.assertEqual((lines, problems), (["close Firefox"], []))
        self.assertIsNone(a.confirm(pending["id"]))                  # one answer per plan
        with self.assertRaises(ValueError):
            a.confirm("../../etc/passwd")

    def test_expired_and_cancelled(self):
        a.save_pending({"id": "abcdef1234", "t": time.time() - a.PENDING_S - 5, "actions": []})
        self.assertIsNone(a.take_pending("abcdef1234"))
        a.save_pending({"id": "abcdef1235", "t": time.time(), "actions": []})
        self.assertIsNotNone(a.take_pending("abcdef1235"))
        self.assertFalse(os.path.exists(a._pending_path("abcdef1235")))

    def test_plan_actions_left_out_and_extra(self):
        vc = a.vc()
        with mock.patch.object(a, "script_json", return_value={"last": {"windows": 3}}), \
                mock.patch.object(vc, "plan", return_value=([self.step("pause")], [])):
            steps, refused = a.plan_actions([{"action": "search", "text": "x"}, {"action": "where-was-i"},
                                             {"action": "reopen-closed", "count": 9}, {"action": "media"}],
                                            FakeWorld())
        self.assertTrue(refused[0].startswith("search"))
        names = [s["action"] for s in steps]
        self.assertEqual(names, ["where-was-i", "reopen-closed", "x"])
        self.assertTrue(steps[0]["confirm"])                         # a restore always asks
        self.assertEqual(len(steps[1]["ops"]), 5)                    # at most five reopened
        self.assertTrue(all(s["confirm"] for s in steps))            # part refused: the rest asks
        with mock.patch.object(a, "script_json", return_value={"last": None}):
            steps, refused = a.plan_actions([{"action": "where-was-i"}], FakeWorld())
        self.assertEqual(steps, [])
        self.assertIn("no earlier session", refused[0])

    def test_confirm_all(self):
        vc = a.vc()
        with mock.patch.object(vc, "plan", return_value=([self.step("pause")], [])):
            steps, _ = a.plan_actions([{"action": "media", "value": "pause"}], FakeWorld(), confirm_all=True)
        self.assertEqual(steps[0]["confirm"], "confirm everything is on")


class ReadFile(Clean):
    """read_file's own rules, in a folder open to the assistant (folder
    access itself: test_folder_access.py)."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        fa = a.access()
        patcher = mock.patch.object(fa, "STORE", os.path.join(self.dir, ".folder-access.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        fa.grant(self.dir, "assistant")
        self.path = os.path.join(self.dir, "notes.txt")
        with open(self.path, "w") as handle:
            handle.write("line one\napi_key = sk-abcdefabcdefabcdefabcdef1234\npassword: hunter22\nline four\n")

    def turn(self, said):
        return a.Turn(said, "en", conf(), FakeWorld())

    def test_named_file_is_read_without_secret_lines(self):
        out = a.t_read({"path": self.path}, self.turn("summarise notes.txt please"))
        self.assertIn("line one", out["text"])
        self.assertIn("line four", out["text"])
        self.assertNotIn("hunter22", out["text"])
        self.assertIn("left_out", out)

    def test_unnamed_file_is_refused(self):
        with self.assertRaises(a.ToolError):
            a.t_read({"path": self.path}, self.turn("what is on screen"))
        turn = self.turn("what did I write")
        turn.seen_paths.add(self.path)                               # a search found it: allowed
        self.assertIn("line one", a.t_read({"path": self.path}, turn)["text"])

    def test_secret_system_binary_and_big(self):
        with self.assertRaises(a.ToolError):
            a.t_read({"path": "~/.ssh/id_ed25519"}, self.turn("read id_ed25519"))
        with self.assertRaises(a.ToolError):
            a.t_read({"path": "/proc/self/environ"}, self.turn("read environ"))
        env = os.path.join(self.dir, "prod.env")
        open(env, "w").write("X=1")
        with self.assertRaises(a.ToolError):
            a.t_read({"path": env}, self.turn("read prod.env"))
        binary = os.path.join(self.dir, "blob.dat")
        open(binary, "wb").write(b"\0\1\2" * 10)
        with self.assertRaises(a.ToolError):
            a.t_read({"path": binary}, self.turn("read blob.dat"))
        big = os.path.join(self.dir, "big.log")
        open(big, "w").write("x" * (a.READ_MAX * 3))
        out = a.t_read({"path": big}, self.turn("read big.log"))
        self.assertEqual(len(out["text"]), a.READ_MAX)
        self.assertIn("note", out)


class Repo(unittest.TestCase):
    def test_changes_of_a_scratch_repo(self):
        root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        repo = os.path.join(root, "Atlas")
        os.makedirs(repo)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null")
        for argv in (["git", "init", "-q"], ["git", "commit", "-q", "--allow-empty", "-m", "Clinical maths moved"]):
            subprocess.run(argv, cwd=repo, env=env, check=True, capture_output=True)
        open(os.path.join(repo, "new.js"), "w").write("x")
        turn = a.Turn("what changed in atlas today", "en", conf(), FakeWorld())
        out = a.t_repo({"repo": "atlas"}, turn, root=root)
        self.assertEqual(out["repo"], "Atlas")
        self.assertIn("Clinical maths moved", out["commits"])
        self.assertIn("new.js", out["uncommitted"])
        with self.assertRaises(a.ToolError):
            a.t_repo({"repo": "nothing-like-it"}, turn, root=root)


class Look(unittest.TestCase):
    def test_windows_side_by_side(self):
        sa = types.SimpleNamespace()
        made, removed, seen = [], [], {}
        sa.visible_workspaces = lambda monitors: {1}
        sa.private_in = lambda clients, rect, shown, is_private: []
        sa._is_private = lambda c: False
        sa.pick_model = lambda status, need_vision=True: ("google/gemma-4-e4b", None)
        sa.image_url = lambda p: "data:" + p

        def ask(key, messages):
            seen["content"] = messages[0]["content"]
            return "B worked, A failed."
        sa.ask = ask
        sa._remove = removed.append
        clients = [{"address": "0x1", "class": "kitty", "title": "A", "workspace": {"id": 1}, "at": [0, 0],
                    "size": [800, 600], "focusHistoryID": 1},
                   {"address": "0x2", "class": "foot", "title": "B", "workspace": {"id": 1}, "at": [800, 0],
                    "size": [800, 600], "focusHistoryID": 0},
                   {"address": "0x3", "class": "mpv", "title": "C", "workspace": {"id": 5}, "at": [0, 0],
                    "size": [800, 600], "focusHistoryID": 2}]
        steps = []
        turn = a.Turn("compare these two windows", "en", conf(), FakeWorld(clients),
                      hooks={"hide": lambda: steps.append("hide"), "show": lambda: steps.append("show")})
        with mock.patch.object(a, "screen_ask", return_value=sa), \
                mock.patch.object(a.models(), "_gamemode_on", return_value=False), \
                mock.patch.object(a, "grab", side_effect=lambda argv, png: made.append(argv) or True):
            out = a.t_look({"what": "windows"}, turn)
        self.assertEqual(steps, ["hide", "show"])
        self.assertEqual([m[-1] for m in made], ["800,0 800x600", "0,0 800x600"])     # focused first, ws 5 not
        self.assertEqual(len(removed), 2)
        self.assertEqual(out["seen"], "B worked, A failed.")
        self.assertEqual(len([c for c in seen["content"] if c["type"] == "image_url"]), 2)

    def test_private_and_gamemode_refused(self):
        sa = types.SimpleNamespace(capture=lambda mode: (None, "KeePassXC is private: not captured"),
                                   _remove=lambda p: None)
        turn = a.Turn("what is this", "en", conf(), FakeWorld())
        with mock.patch.object(a, "screen_ask", return_value=sa), \
                mock.patch.object(a.models(), "_gamemode_on", return_value=False):
            with self.assertRaisesRegex(a.ToolError, "private"):
                a.t_look({"what": "window"}, turn)
        with mock.patch.object(a, "screen_ask", return_value=sa), \
                mock.patch.object(a.models(), "_gamemode_on", return_value=True):
            with self.assertRaisesRegex(a.ToolError, "gamemode"):
                a.t_look({"what": "window"}, turn)


class History(Clean):
    def turn(self, q="hola", t=None):
        return {"id": "x" + str(t or 0), "t": t or time.time(), "question": q, "answer": "hi", "lang": "es",
                "steps": [{"line": "read the timers", "tool": "timers", "args": {"secret": "no"}}]}

    def test_kept_pruned_forgotten(self):
        with mock.patch.object(a, "to_memory") as mem:
            a.remember(self.turn(), conf())
            a.remember(self.turn("old", time.time() - 10 * 86400), conf())
        self.assertEqual(mem.call_count, 2)
        rows = a.read_history()
        self.assertEqual([r["question"] for r in rows], ["hola", "old"])
        self.assertEqual(rows[0]["steps"], ["read the timers"])      # the line only, not the args
        self.assertEqual(oct(os.stat(a.HISTORY).st_mode & 0o777), "0o600")
        self.assertEqual(a.prune(conf(history_days=7)), 1)
        self.assertEqual([r["question"] for r in a.read_history()], ["hola"])
        a.clear()
        self.assertEqual(a.read_history(), [])

    def test_nothing_written_at_zero_days(self):
        with mock.patch.object(a, "to_memory"):
            a.remember(self.turn(), conf(history_days=0))
        self.assertFalse(os.path.exists(a.HISTORY))

    def test_memory_only_with_the_privacy_switch(self):
        ps = a.privacy()
        with mock.patch.object(ps, "load", return_value=dict(ps.DEFAULTS)):
            self.assertFalse(a.to_memory(self.turn()))               # off as shipped
        self.assertEqual(ps.DEFAULTS["assistant_memory"], "off")
        self.assertFalse(ps.assistant_memory_on(dict(ps.DEFAULTS, assistant_memory="on", memory="off")))
        self.assertTrue(ps.assistant_memory_on(dict(ps.DEFAULTS, assistant_memory="on")))


class Speak(unittest.TestCase):
    def test_hook(self):
        self.assertFalse(a.speak("hola", "es", conf()))              # voice_reply off
        with mock.patch.object(a, "tts_function", return_value=None):
            self.assertFalse(a.speak("hola", "es", conf(voice_reply="on")))
        said = []
        with mock.patch.object(a, "tts_function", return_value=lambda text, lang=None: said.append((text, lang))):
            self.assertTrue(a.speak("hola", "es", conf(voice_reply="on")))
            for _ in range(50):
                if said:
                    break
                time.sleep(0.02)
        self.assertEqual(said, [("hola", "es")])


class Launcher(unittest.TestCase):
    def test_rows(self):
        L = helpers.import_script("launcher.py", "launcher")
        with mock.patch.object(L, "assistant_choice", return_value=(True, "assistant")):
            names = [i.name for i in L.ask_desktop_items("ask what changed in Atlas today")]
            self.assertEqual(names[0], "Ask the assistant: what changed in Atlas today")
            self.assertEqual(names[1], "Ask your desktop: what changed in Atlas today")
            self.assertEqual([i.name for i in L.ask_desktop_items("asistente")], ["Assistant"])
        with mock.patch.object(L, "assistant_choice", return_value=(True, "desktop")):
            self.assertTrue(L.ask_desktop_items("pregunta qué hice ayer")[0].name.startswith("Ask your desktop"))
        with mock.patch.object(L, "assistant_choice", return_value=(False, "assistant")):
            self.assertEqual(len(L.ask_desktop_items("ask what changed today")), 1)
            self.assertEqual(L.ask_desktop_items("assistant"), [])


class Page(unittest.TestCase):
    def test_helpers(self):
        try:
            from settings_pages import assistant as page            # needs GTK, not a display
        except Exception as exc:    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.assistant not importable: {exc}")
        chips = page.model_chips({"default": {"name": "qwen3.8-27b", "local": True},
                                  "quick": {"name": "haiku", "local": False}})
        self.assertEqual([k for k, _ in chips], ["auto", "default", "quick", "worker"])
        self.assertIn("qwen3.8-27b", chips[1][1])
        self.assertIn("not local", chips[2][1])
        self.assertIn("only while the panel", page.history_text({"turns": 0}, 0))
        self.assertIn("3 exchange", page.history_text({"turns": 3, "since": time.time(), "bytes": 2048}, 7))


class ReviewFixes(Clean):
    """What the adversarial review found: the model-written close / open-url
    always ask, a one-letter file name is not "named", the retention holds
    for the panel's remember() too, the memory follows its notifications
    switch and never keeps the unscrubbed question as the title, one panel
    lock, expired pending plans go."""

    def step(self, action):
        return {"action": action, "say": action, "confirm": "", "ops": [], "undo": None}

    def test_close_and_open_url_always_ask(self):
        vc = a.vc()
        with mock.patch.object(vc, "plan", side_effect=lambda acts, world, lang: (
                [self.step(acts[0]["action"])], [])):
            steps, _ = a.plan_actions([{"action": "close"}, {"action": "open-url", "text": "example.com"},
                                       {"action": "media", "value": "pause"}], FakeWorld())
        self.assertTrue(steps[0]["confirm"] and steps[1]["confirm"])
        self.assertEqual(steps[2]["confirm"], "")

    def test_short_name_is_not_named(self):
        d = tempfile.mkdtemp(dir=helpers.SCRATCH)
        path = os.path.join(d, "a")
        with open(path, "w") as handle:
            handle.write("hello")
        with self.assertRaises(a.ToolError):
            a.t_read({"path": path}, a.Turn("what is a good name", "en", conf(), FakeWorld()))
        self.assertTrue(a.named(path, a.Turn(f"read {path}", "en", conf(), FakeWorld())))

    def test_remember_prunes(self):
        with mock.patch.object(a, "to_memory"):
            a._write_rows([{"id": "old", "t": time.time() - 30 * 86400, "question": "old", "answer": "x"}])
            a.remember({"id": "new", "t": time.time(), "question": "new", "answer": "y"}, conf(history_days=7))
        self.assertEqual([r["question"] for r in a.read_history()], ["new"])

    def test_memory_follows_notifications_switch_and_scrubs_title(self):
        ps = a.privacy()
        added = {}
        dm = types.SimpleNamespace(
            scrub=lambda text: "\n".join(line for line in text.splitlines() if "hunter2" not in line),
            connect=mock.MagicMock(), add=lambda con, source, t, text, **kw: added.update(kw, text=text))
        turn = {"id": "1", "t": time.time(), "question": "password hunter2\nwhat now", "answer": "ok"}
        on = dict(ps.DEFAULTS, assistant_memory="on")
        with mock.patch.object(ps, "load", return_value=dict(on, memory_notifications="off")), \
                mock.patch.dict(sys.modules, {"desktop_memory": dm}):
            self.assertFalse(a.to_memory(turn))
        self.assertEqual(added, {})
        with mock.patch.object(ps, "load", return_value=on), \
                mock.patch.dict(sys.modules, {"desktop_memory": dm}):
            self.assertTrue(a.to_memory(turn))
        self.assertNotIn("hunter2", added["title"] + added["text"])

    def test_one_panel_lock(self):
        first = a.panel_lock()
        self.assertIsNotNone(first)
        here = os.path.dirname(os.path.abspath(__file__))
        child = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {here!r}); import helpers; "
                                f"a = helpers.import_script('assistant.py'); a.RUN_DIR = {a.RUN_DIR!r}; "
                                "print(a.panel_lock() is None)"],
                               capture_output=True, text=True, env=os.environ)
        a._LOCKS.remove(first)
        first.close()
        self.assertEqual(child.stdout.strip().splitlines()[-1:], ["True"], child.stderr)

    def test_expired_pending_files_go(self):
        a.save_pending({"id": "abcdef9999", "t": time.time(), "actions": []})
        old = a._pending_path("abcdef9999")
        os.utime(old, (time.time() - a.PENDING_S - 5,) * 2)
        a.save_pending({"id": "abcdef8888", "t": time.time(), "actions": []})
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(a._pending_path("abcdef8888")))


if __name__ == "__main__":
    unittest.main()
