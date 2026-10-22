"""llm-chat.py's live permissions, notifications and local-model unloading:
the Claude backend's stream-json control protocol (parsing a recorded run's
lines, the answers it is given), the session allow rules, the permission
card's summary, the notification decisions and the unload refusal while a
run is going. No claude, no lms, no notify-send: the GTK window is never
built (the Front methods under test run on a stand-in object). The native
engine's own tests are test_llm_chat_engine.py.

fixtures/claude-permission-{allow,deny}.jsonl are the lines of two real
runs (Claude Code 2.1.306, haiku, `touch made.txt` in a scratch folder,
answered allow / deny), trimmed to the events the window reads."""
import json
import os
import types
import unittest

import helpers

front = helpers.import_script("llm-chat.py")
mood = helpers.import_script("mascot_mood.py")

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def recorded(name):
    with open(os.path.join(FIXTURES, f"claude-permission-{name}.jsonl")) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def request_of(lines):
    return next(front.can_use_tool(ev) for ev in lines if ev.get("type") == "control_request")


class Protocol(unittest.TestCase):
    def test_recorded_request_is_read(self):
        req = request_of(recorded("allow"))
        self.assertEqual(req["tool"], "Bash")
        self.assertEqual(req["display"], "Bash")
        self.assertEqual(req["input"]["command"], "touch made.txt")
        self.assertEqual(req["id"], "f0d458ed-0e4a-4428-b188-fe95b2b95c67")
        self.assertEqual(req["tool_use_id"], "toolu_01HYRztWmWMLeBuSznP7d7vw")
        self.assertEqual(req["blocked"], "/tmp/scratch/work/made.txt")
        self.assertEqual([s["type"] for s in req["suggestions"]], ["addRules", "addDirectories", "setMode"])

    def test_other_lines_are_not_requests(self):
        for ev in recorded("allow"):
            if ev.get("type") != "control_request":
                self.assertIsNone(front.can_use_tool(ev))
        self.assertIsNone(front.can_use_tool({"type": "control_request", "request": {"subtype": "can_use_tool"}}))
        self.assertIsNone(front.can_use_tool({"type": "control_request", "request_id": "x",
                                              "request": {"subtype": "hook_callback"}}))
        self.assertIsNone(front.can_use_tool("not a dict"))

    def test_bad_fields_are_made_safe(self):
        req = front.can_use_tool({"type": "control_request", "request_id": 7, "request": {
            "subtype": "can_use_tool", "input": "oops", "permission_suggestions": ["x", None],
            "decision_reason": "\x1b[31mrisky\x1b[0m"}})
        self.assertEqual(req["id"], "7")
        self.assertEqual(req["tool"], "?")
        self.assertEqual(req["input"], {})
        self.assertEqual(req["suggestions"], [])
        self.assertEqual(req["reason"], "risky")

    def test_allow_is_what_the_real_run_accepted(self):
        req = request_of(recorded("allow"))
        self.assertEqual(front.allow_response(req["id"], req["input"]), {
            "type": "control_response", "response": {
                "subtype": "success", "request_id": req["id"],
                "response": {"behavior": "allow", "updatedInput": req["input"]}}})

    def test_deny_carries_the_note(self):
        plain = front.deny_response("r1")["response"]["response"]
        self.assertEqual(plain, {"behavior": "deny", "message": front.DENY_MESSAGE})
        noted = front.deny_response("r1", "  not in this folder  ")["response"]["response"]
        self.assertEqual(noted["behavior"], "deny")
        self.assertTrue(noted["message"].endswith(": not in this folder"))

    def test_error_answer(self):
        self.assertEqual(front.error_response("r9", "no")["response"],
                         {"subtype": "error", "request_id": "r9", "error": "no"})

    def test_recorded_deny_run_lists_the_denial(self):
        # The real run's result names the call the window said no to: the
        # window keeps its tool_use id so no retry is offered for it.
        lines = recorded("deny")
        req = request_of(lines)
        result = next(ev for ev in lines if ev.get("type") == "result")
        self.assertEqual([d["tool_use_id"] for d in result["permission_denials"]], [req["tool_use_id"]])
        tool_result = next(ev for ev in lines if ev.get("type") == "user")
        self.assertTrue(tool_result["message"]["content"][0]["is_error"])


class Modes(unittest.TestCase):
    def test_start(self):
        self.assertEqual(front.start_permission("", None), front.PERM_DEFAULT)
        self.assertEqual(front.PERM_DEFAULT, "ask")
        self.assertEqual(front.start_permission("", "plan"), "plan")
        self.assertEqual(front.start_permission("", "nonsense"), "ask")
        self.assertEqual(front.start_permission("auto", "plan"), "auto")
        self.assertEqual(front.start_permission("default", "plan"), "ask")
        self.assertEqual(front.start_permission("manual", None), "ask")
        self.assertEqual(front.start_permission("bypassPermissions", None), "bypassPermissions")

    def test_cli_mode(self):
        self.assertEqual(front.perm_cli_mode("ask"), "default")
        self.assertEqual(front.perm_cli_mode("acceptEdits"), "acceptEdits")
        self.assertEqual(front.perm_cli_mode("dontAsk"), "dontAsk")
        self.assertEqual(front.perm_label("plan"), "Plan (read-only)")

    def test_argv(self):
        fake = types.SimpleNamespace(perm="ask", live_prompts=True, session_id="abc",
                                     spec=lambda: ([], {}))
        argv = front.Front.argv(fake, "claude")
        self.assertIn("--permission-prompt-tool", argv)
        self.assertEqual(argv[argv.index("--permission-prompt-tool") + 1], "stdio")
        self.assertEqual(argv[argv.index("--input-format") + 1], "stream-json")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "default")
        self.assertEqual(argv[argv.index("--resume") + 1], "abc")
        fake.live_prompts = False
        argv = front.Front.argv(fake, "claude", allow=["Bash(ls)"])
        self.assertNotIn("--permission-prompt-tool", argv)
        self.assertNotIn("--input-format", argv)
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "Bash(ls)")


def req(tool, data, suggestions=()):
    return {"id": "r", "tool": tool, "display": tool, "input": data, "suggestions": list(suggestions),
            "blocked": None, "reason": None, "tool_use_id": "t", "agent": None}


class SessionRules(unittest.TestCase):
    def test_from_the_cli_suggestion_but_only_for_the_session(self):
        rule, updated = front.session_rule(request_of(recorded("allow")))
        self.assertEqual(rule, {"tool": "Bash", "content": "touch made.txt"})
        self.assertEqual(updated, [{"type": "addRules", "rules": [{"toolName": "Bash",
                                                                   "ruleContent": "touch made.txt"}],
                                    "behavior": "allow", "destination": "session"}])

    def test_never_a_settings_file(self):
        for r in (request_of(recorded("allow")), req("Edit", {"file_path": "/p/a.py"}),
                  req("Read", {"file_path": "/x/y"}, [{"type": "addDirectories", "directories": ["/x"],
                                                       "destination": "localSettings"}]),
                  req("WebFetch", {"url": "https://a.b/c"}), req("Bash", {"command": "ls"})):
            for update in front.session_rule(r)[1]:
                self.assertEqual(update["destination"], "session")

    def test_fallbacks(self):
        self.assertEqual(front.session_rule(req("Bash", {"command": " make test "}))[0],
                         {"tool": "Bash", "content": "make test"})
        self.assertEqual(front.session_rule(req("Edit", {"file_path": "/proj/src/a.py"}))[0],
                         {"tool": "Edit", "content": "dir:/proj/src"})
        self.assertEqual(front.session_rule(req("Grep", {"pattern": "x", "path": "/proj"}))[0],
                         {"tool": "Grep", "content": "dir:/proj"})
        self.assertEqual(front.session_rule(req("Read", {"file_path": "/x/y"}, [
            {"type": "addDirectories", "directories": ["/x"], "destination": "session"}]))[0],
            {"tool": "Read", "content": "dir:/x"})
        self.assertEqual(front.session_rule(req("WebSearch", {"query": "q"}))[0],
                         {"tool": "WebSearch", "content": None})

    def test_a_suggestion_for_another_tool_is_not_taken(self):
        rule, _ = front.session_rule(req("Bash", {"command": "ls"}, [
            {"type": "addRules", "behavior": "allow", "rules": [{"toolName": "Read"}]}]))
        self.assertEqual(rule, {"tool": "Bash", "content": "ls"})

    def test_exact_and_prefix_commands(self):
        exact = {"tool": "Bash", "content": "touch made.txt"}
        self.assertTrue(front.rule_matches(exact, "Bash", {"command": "touch made.txt "}, "/w"))
        self.assertFalse(front.rule_matches(exact, "Bash", {"command": "touch made.txt other"}, "/w"))
        prefix = {"tool": "Bash", "content": "npm run:*"}
        self.assertTrue(front.rule_matches(prefix, "Bash", {"command": "npm run build"}, "/w"))
        self.assertTrue(front.rule_matches(prefix, "Bash", {"command": "npm run"}, "/w"))
        self.assertFalse(front.rule_matches(prefix, "Bash", {"command": "npm runner"}, "/w"))
        for joined in ("npm run x && rm -rf ~", "npm run x; curl evil", "npm run x | sh",
                       "npm run $(whoami)", "npm run x > /etc/passwd", "npm run `id`", "npm run a\nrm b"):
            self.assertFalse(front.rule_matches(prefix, "Bash", {"command": joined}, "/w"), joined)
        self.assertFalse(front.rule_matches(prefix, "Read", {"command": "npm run x"}, "/w"))

    def test_folders(self):
        rule = {"tool": "Edit", "content": "dir:/proj/src"}
        self.assertTrue(front.rule_matches(rule, "Edit", {"file_path": "/proj/src/deep/a.py"}, "/w"))
        self.assertTrue(front.rule_matches(rule, "Edit", {"file_path": "src/a.py"}, "/proj"))
        self.assertFalse(front.rule_matches(rule, "Edit", {"file_path": "/proj/src2/a.py"}, "/w"))
        self.assertFalse(front.rule_matches(rule, "Edit", {"file_path": "/proj/src/../../etc/x"}, "/w"))
        self.assertFalse(front.rule_matches(rule, "Write", {"file_path": "/proj/src/a.py"}, "/w"))
        self.assertFalse(front.rule_matches(rule, "Edit", {}, "/w"))

    def test_claude_code_path_patterns_and_domains(self):
        absolute = {"tool": "Read", "content": "//etc/hypr/**"}
        self.assertTrue(front.rule_matches(absolute, "Read", {"file_path": "/etc/hypr/a/b"}, "/w"))
        self.assertFalse(front.rule_matches(absolute, "Read", {"file_path": "/etc/hyprx"}, "/w"))
        relative = {"tool": "Edit", "content": "/docs/*.md"}
        self.assertTrue(front.rule_matches(relative, "Edit", {"file_path": "/w/docs/a.md"}, "/w"))
        self.assertFalse(front.rule_matches(relative, "Edit", {"file_path": "/w/docs/a.py"}, "/w"))
        domain = {"tool": "WebFetch", "content": "domain:example.com"}
        self.assertTrue(front.rule_matches(domain, "WebFetch", {"url": "https://docs.example.com/x"}, "/w"))
        self.assertFalse(front.rule_matches(domain, "WebFetch", {"url": "https://example.com.evil.io/"}, "/w"))
        self.assertFalse(front.rule_matches(domain, "WebFetch", {"url": "https://notexample.com/"}, "/w"))
        self.assertTrue(front.rule_matches({"tool": "WebSearch", "content": None}, "WebSearch", {}, "/w"))

    def test_words(self):
        self.assertEqual(front.rule_text({"tool": "Bash", "content": "npm run:*"}), "Bash(npm run:*)")
        self.assertEqual(front.rule_text({"tool": "WebSearch", "content": None}), "WebSearch (any)")
        self.assertTrue(front.rule_text({"tool": "Edit", "content": "dir:/x/y"}).startswith("Edit in "))


class Window(unittest.TestCase):
    """Front's control handling on a stand-in (no GTK window built)."""

    def stand_in(self, rules=()):
        sent, notes = [], []
        fake = types.SimpleNamespace(replaying=False, perm_rules=list(rules), cwd="/tmp/scratch/work",
                                     ui=dict(front.UI_EN), write_control=lambda obj: sent.append(obj) or True,
                                     note=notes.append)
        return fake, sent, notes

    def test_a_session_rule_answers_without_a_card(self):
        fake, sent, notes = self.stand_in([{"tool": "Bash", "content": "touch made.txt"}])
        ev = next(e for e in recorded("allow") if e.get("type") == "control_request")
        front.Front.handle_control(fake, ev)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["response"]["request_id"], ev["request_id"])
        self.assertEqual(sent[0]["response"]["response"]["behavior"], "allow")
        self.assertEqual(sent[0]["response"]["response"]["updatedInput"], ev["request"]["input"])
        self.assertIn("Bash(touch made.txt)", notes[0])

    def test_unknown_requests_get_an_error(self):
        fake, sent, _ = self.stand_in()
        front.Front.handle_control(fake, {"type": "control_request", "request_id": "h1",
                                          "request": {"subtype": "hook_callback"}})
        self.assertEqual(sent[0]["response"]["subtype"], "error")
        self.assertEqual(sent[0]["response"]["request_id"], "h1")


class Details(unittest.TestCase):
    def test_bash(self):
        head, details, warn = front.perm_details(request_of(recorded("allow")), "/tmp/scratch/work")
        self.assertEqual(head, "touch made.txt")
        self.assertEqual(details, ["Create empty file made.txt in working directory"])
        self.assertEqual(warn, [])

    def test_edit_diff_summary(self):
        head, details, warn = front.perm_details(
            req("Edit", {"file_path": "/w/a.txt", "old_string": "one\ntwo", "new_string": "one\n2\nthree"}), "/w")
        self.assertEqual(head, "/w/a.txt")
        self.assertEqual(details[0], "−2 +3 lines")
        self.assertIn("-two", details)
        self.assertIn("+three", details)
        self.assertEqual(warn, [])

    def test_write_new_or_replacing(self):
        folder = os.path.join(helpers.SCRATCH, "front-write")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "there.txt"), "w") as handle:
            handle.write("x")
        _h, details, _w = front.perm_details(req("Write", {"file_path": "there.txt", "content": "a\nb"}), folder)
        self.assertIn("replaces the file", details[0])
        _h, details, _w = front.perm_details(req("Write", {"file_path": "new.txt", "content": "a"}), folder)
        self.assertIn("a new file", details[0])

    def test_warnings(self):
        home = os.path.expanduser("~")
        _h, _d, warn = front.perm_details(req("Read", {"file_path": os.path.join(home, ".ssh", "id_rsa")}),
                                          "/tmp/scratch/work")
        self.assertTrue(any(w.startswith("outside the working directory") for w in warn))
        self.assertTrue(any(w.startswith("Folder access: looks secret") for w in warn), warn)
        r = req("Bash", {"command": "rm -rf build"})
        r["reason"] = "deletes files"
        self.assertIn("why it asks: deletes files", front.perm_details(r, "/w")[2])

    def test_plan(self):
        head, details, _w = front.perm_details(req("ExitPlanMode", {"plan": "1. a\n\n2. b"}), "/w")
        self.assertEqual(details, ["1. a", "2. b"])


class Notifications(unittest.TestCase):
    def test_decisions(self):
        decide = front.notify_decision
        # Focused or switched off: never.
        for event in ("done", "failed", "permission"):
            self.assertIsNone(decide(event, focused=True, dnd=False, enabled=True))
            self.assertIsNone(decide(event, focused=False, dnd=False, enabled=False))
        # In the background.
        self.assertEqual(decide("done", focused=False, dnd=False, enabled=True), "normal")
        self.assertEqual(decide("failed", focused=False, dnd=False, enabled=True), "normal")
        self.assertEqual(decide("permission", focused=False, dnd=False, enabled=True), "critical")
        # Do Not Disturb: only a waiting permission goes through.
        self.assertIsNone(decide("done", focused=False, dnd=True, enabled=True))
        self.assertIsNone(decide("failed", focused=False, dnd=True, enabled=True))
        self.assertEqual(decide("permission", focused=False, dnd=True, enabled=True), "critical")

    def test_toggle_in_the_state_file(self):
        try:
            os.remove(front.FRONT_STATE)
        except OSError:
            pass
        self.assertTrue(front.notify_enabled())
        front.write_front_state(notify=False, corner=True)
        self.assertFalse(front.notify_enabled())
        front.write_front_state(notify=True)
        self.assertTrue(front.notify_enabled())
        self.assertTrue(front.read_front_state()["corner"])

    def test_old_settings_are_copied_once(self):
        """claude-front.json (the window's name before) becomes llm-chat.json
        once; the old file stays, a later run copies nothing again."""
        from unittest import mock
        folder = os.path.join(helpers.SCRATCH, "migrate")
        os.makedirs(folder, exist_ok=True)
        old, new = os.path.join(folder, "claude-front.json"), os.path.join(folder, "llm-chat.json")
        with open(old, "w") as handle:
            json.dump({"corner": True, "permissions": "acceptEdits", "junk": 1}, handle)
        with mock.patch.object(front, "OLD_STATE", old), mock.patch.object(front, "FRONT_STATE", new):
            self.assertTrue(front.migrate_state())
            self.assertEqual(front.read_front_state(), {"corner": True, "permissions": "acceptEdits"})
            self.assertTrue(os.path.exists(old))
            front.write_front_state(permissions="plan")
            self.assertFalse(front.migrate_state())
            self.assertEqual(front.read_front_state()["permissions"], "plan")

    def test_settings_page_writes_only_its_key(self):
        from settings_pages import ai as page
        path = os.path.join(helpers.SCRATCH, "front-settings.json")
        self.assertTrue(page.front_notify(path))                 # no file: on
        with open(path, "w") as handle:
            json.dump({"corner": True, "permissions": "plan"}, handle)
        self.assertTrue(page.set_front_notify(False, path))
        self.assertFalse(page.front_notify(path))
        with open(path) as handle:
            self.assertEqual(json.load(handle), {"corner": True, "permissions": "plan", "notify": False})
        self.assertEqual(page.FRONT_STATE, front.FRONT_STATE)    # the window's own file

    def test_first_line(self):
        self.assertEqual(front.first_line("\n## Done\n\nmore"), "Done")
        self.assertEqual(front.first_line("```py\nx\n```"), "x")
        self.assertEqual(front.first_line("- **made** `made.txt`"), "made made.txt")
        self.assertEqual(front.first_line(""), "")


class Unload(unittest.TestCase):
    def stand_in(self, busy):
        calls = {"note": [], "button": [], "start": []}
        fake = types.SimpleNamespace(
            busy=lambda: busy, unloading=None, note=calls["note"].append,
            model_pop=types.SimpleNamespace(popdown=lambda: None),
            loaded_name=lambda key: {"qwen/qwen3": "qwen"}.get(key, key),
            stop_unload_button=lambda key, name: calls["button"].append((key, name)),
            start_unload=lambda key, name: calls["start"].append((key, name)))
        return fake, calls

    def test_refused_while_a_run_is_going(self):
        fake, calls = self.stand_in(busy=True)
        self.assertFalse(front.Front.request_unload(fake, "qwen/qwen3"))
        self.assertEqual(calls["start"], [])
        self.assertIn("stop it first", calls["note"][0])
        self.assertEqual(calls["button"], [("qwen/qwen3", "qwen")])

    def test_goes_when_idle(self):
        fake, calls = self.stand_in(busy=False)
        self.assertTrue(front.Front.request_unload(fake, "--all"))
        self.assertEqual(calls["start"], [("--all", "every local model")])
        self.assertEqual(calls["note"], [])

    def test_one_at_a_time(self):
        fake, calls = self.stand_in(busy=False)
        fake.unloading = "qwen"
        self.assertFalse(front.Front.request_unload(fake, "--all"))
        self.assertEqual(calls["start"], [])

    def test_pure_refusal(self):
        self.assertIsNone(front.unload_refusal(False, "qwen"))
        self.assertIn("Esc", front.unload_refusal(True, "qwen"))

    def test_freed_and_ttl_words(self):
        gib = 2**30
        self.assertEqual(front.freed_text({"vram": 12 * gib, "ram": 4 * gib}, {"vram": 2 * gib, "ram": 5 * gib}),
                         "freed 10.0 GB of graphics memory, 1.0 GB of RAM")
        self.assertEqual(front.freed_text({"vram": None, "ram": None}, {"vram": None, "ram": None}), "")
        self.assertEqual(front.ttl_text(None), "stays loaded")
        self.assertEqual(front.ttl_text(30), "unloads after 1 min idle")
        self.assertEqual(front.ttl_text(2820), "unloads after 47 min idle")
        self.assertEqual(front.ttl_text(5400), "unloads after 1.5 h idle")

    def test_loaded_state_counts_down_from_the_look(self):
        model = types.SimpleNamespace(local=True, ident="qwen/qwen3")
        fake = types.SimpleNamespace(loaded={"qwen/qwen3": {"ident": "qwen3", "ttl": 3000}},
                                     loaded_at=front.time.monotonic() - 600)
        self.assertEqual(front.Front.local_state(fake, model), "loaded · unloads after 40 min idle")
        fake.loaded = {}
        self.assertEqual(front.Front.local_state(fake, model), "not loaded")
        fake.loaded_at = None
        self.assertIsNone(front.Front.local_state(fake, model))
        self.assertIsNone(front.Front.local_state(fake, types.SimpleNamespace(local=False, ident="opus")))


class Mood(unittest.TestCase):
    def test_permission_reactions(self):
        m = mood.Mood()
        m.react("permission")
        self.assertEqual(m.reaction[0], "curious")
        self.assertGreater(m.reaction[1] - m.clock(), 60)       # held while it waits
        m.react("permission_allowed")
        self.assertEqual(m.reaction[0], "happy")
        m.react("permission")
        m.react("permission_denied")
        self.assertEqual(m.reaction[0], "calm")


class Words(unittest.TestCase):
    def test_every_theme_has_every_word(self):
        keys = set(front.UI_EN)
        self.assertLessEqual({k for k in front.UI_JA if k.startswith(("perm_", "n_", "unload"))}, keys)
        for key in ("perm_title", "perm_once", "perm_session", "perm_deny", "perm_note", "perm_keys",
                    "perm_bubble", "n_done", "n_perm", "unload", "unload_all"):
            self.assertIn(key, front.UI_JA, key)
        for theme in ("moe", "cyberpunk", "matrix", "win95", "aero"):
            ui = front.ui_strings(theme, conf={"lang": "ja" if theme == "moe" else "en"})
            for key in keys:
                self.assertIn(key, ui)
            ui["perm_title"].format(tool="Bash")
            ui["unload"].format(model="qwen")


if __name__ == "__main__":
    unittest.main()
