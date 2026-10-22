"""The LLM chat window's own engine (llm_chat_engine.py) and the window's
native backend, against a FAKE OpenAI-compatible server: a tiny
http.server on a random local port that answers /v1/chat/completions with
scripted server-sent events (a tool call, then an answer) and records what
it was sent. No LM Studio, no claude, no network beyond 127.0.0.1.

What is checked: the stream (text, reasoning in both forms, a tool call cut
into pieces), the tool loop and its permission questions (allow, deny with a
note that reaches the model, Plan refusing writes, Accept edits, Auto's
read-only commands), Folder access refusing a read (the tests' store has
nothing granted and never prompts), the no-tools fallback, cancelling,
the session files, the window's permission cards on a real (never shown)
window, and the desktop without Claude Code installed (PATH and HOME
without it)."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import helpers

import llm_chat_engine as engine     # noqa: E402  (plain imports: the window shares them)
import llm_models                   # noqa: E402


# -- the fake server ------------------------------------------------------------------------------
def sse(*chunks):
    """A scripted answer: SSE chunks (dicts), then [DONE]."""
    return ("sse", list(chunks))


def text_chunks(text, reasoning=None):
    out = [{"choices": [{"index": 0, "delta": {"role": "assistant"}}]}]
    if reasoning:
        out.append({"choices": [{"index": 0, "delta": {"reasoning_content": reasoning}}]})
    for i in range(0, len(text), 7):
        out.append({"choices": [{"index": 0, "delta": {"content": text[i:i + 7]}}]})
    out.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30}})
    return out


def call_chunks(name, args, cid="call_1"):
    """A tool call, its arguments cut in three pieces as servers send them."""
    raw = json.dumps(args)
    third = max(1, len(raw) // 3)
    out = [{"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "id": cid, "type": "function", "function": {"name": name, "arguments": raw[:third]}}]}}]}]
    for piece in (raw[third:2 * third], raw[2 * third:]):
        out.append({"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": piece}}]}}]})
    out.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
    return out


class FakeServer:
    def __init__(self, script, models=("fake-model",)):
        self.script, self.requests, self.models = list(script), [], list(models)
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.endswith("/models"):
                    self.reply(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in fake.models]})
                else:
                    self.reply(404, {"error": {"message": "no such route"}})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                fake.requests.append({"body": body, "auth": self.headers.get("authorization")})
                kind, data = fake.script.pop(0) if fake.script else sse(*text_chunks("(script ended)"))
                if kind == "error":
                    self.reply(data[0], {"error": {"message": data[1]}})
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for chunk in data:
                    if chunk == "hang":
                        time.sleep(30)
                        return
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")

            def reply(self, status, obj):
                raw = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        self.ep = {"kind": "server", "base": self.base, "key": "sk-test", "label": "fake"}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run_sync(ep, messages, answers=(), timeout=20, **kw):
    """A Run to its end in this thread: its events, the asks answered from
    `answers` ([(allow, note)] in order)."""
    events, done = [], threading.Event()
    answers = list(answers)
    box = []

    def emit(kind, data):
        events.append((kind, data))
        if kind == "ask":
            allow, note = answers.pop(0) if answers else (False, "")
            threading.Thread(target=lambda: box[0].answer(data["req"]["id"], allow, note), daemon=True).start()
        if kind == "done":
            done.set()
    run = engine.Run(ep, "fake-model", messages, emit, **kw)
    box.append(run)
    run.start()
    assert done.wait(timeout), "the run never ended"
    return run, events, dict(events)["done"]


def kinds(events, kind):
    return [d for k, d in events if k == kind]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=helpers.SCRATCH)
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.path.join(self.tmp.name, "work")
        os.makedirs(self.cwd)

    def server(self, *script, **kw):
        fake = FakeServer(script, **kw)
        self.addCleanup(fake.close)
        return fake


# -- the stream -----------------------------------------------------------------------------------
class Stream(Base):
    def test_text_reasoning_and_usage(self):
        fake = self.server(sse(*text_chunks("Hello <think>hidden musing</think>world.", reasoning="plan: greet")))
        _run, events, done = run_sync(fake.ep, [engine.user_message("hi")], cwd=self.cwd)
        self.assertTrue(done["ok"], done)
        self.assertEqual("".join(d["text"] for d in kinds(events, "text")), "Hello world.")
        self.assertEqual("".join(d["text"] for d in kinds(events, "reasoning")), "plan: greethidden musing")
        self.assertEqual(kinds(events, "usage")[-1], {"prompt": 120, "completion": 30})
        self.assertEqual(done["messages"][-1], {"role": "assistant", "content": "Hello world."})
        sent = fake.requests[0]
        self.assertEqual(sent["auth"], "Bearer sk-test")
        self.assertTrue(sent["body"]["stream"])
        self.assertEqual(sent["body"]["messages"][0]["role"], "system")
        self.assertIn("run_command", [t["function"]["name"] for t in sent["body"]["tools"]])

    def test_think_tag_cut_between_chunks(self):
        split = engine.ThinkSplitter()
        out = [split.feed(p) for p in ("a<th", "ink>x", "y</th", "ink>b")] + [split.flush()]
        self.assertEqual("".join(r for r, _ in out), "ab")
        self.assertEqual("".join(t for _, t in out), "xy")

    def test_server_models_and_errors(self):
        fake = self.server(models=("m-one", "m-two"))
        self.assertEqual(engine.server_models(fake.ep), ["m-one", "m-two"])
        bad = dict(fake.ep, base="http://127.0.0.1:9/v1")
        _run, _events, done = run_sync(bad, [engine.user_message("hi")], cwd=self.cwd)
        self.assertFalse(done["ok"])
        self.assertIn("could not reach", done["error"])
        self.assertEqual(done["messages"], [])          # a message nothing answered is not kept

    def test_image_refused_says_so(self):
        fake = self.server(("error", (400, "image input is not supported")))
        msg = engine.user_message("what is this", [{"media": "image/png", "data": b"\x89PNG"}])
        self.assertTrue(msg["content"][0]["image_url"]["url"].startswith("data:image/png;base64,"))
        _run, events, done = run_sync(fake.ep, [msg], cwd=self.cwd)
        self.assertIn("may not see images", done["error"])
        self.assertEqual(kinds(events, "no_tools"), [])     # a picture refused is not "no tools"
        self.assertEqual(done["messages"], [])


# -- tools and permissions ------------------------------------------------------------------------
class Tools(Base):
    def test_allowed_command_runs_and_its_output_goes_back(self):
        fake = self.server(sse(*call_chunks("run_command", {"command": "echo made > made.txt; echo ok"})),
                           sse(*text_chunks("Done: made.txt exists.")))
        _run, events, done = run_sync(fake.ep, [engine.user_message("make a file")], [(True, "")],
                                      cwd=self.cwd, mode="ask")
        self.assertTrue(done["ok"], done)
        req = kinds(events, "ask")[0]["req"]
        self.assertEqual((req["tool"], req["display"]), ("Bash", "run_command"))
        self.assertTrue(req["native"])
        self.assertTrue(os.path.exists(os.path.join(self.cwd, "made.txt")))
        tool_msg = fake.requests[1]["body"]["messages"][-1]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertEqual(tool_msg["tool_call_id"], "call_1")
        self.assertEqual(tool_msg["content"], "ok")
        self.assertEqual(kinds(events, "tool_done")[0]["is_error"], False)
        self.assertEqual(kinds(events, "pgid") and True, True)          # its own process group, for Esc

    def test_deny_note_reaches_the_model(self):
        fake = self.server(sse(*call_chunks("write_file", {"path": "x.txt", "content": "x"})),
                           sse(*text_chunks("Understood, I will not.")))
        _run, _events, done = run_sync(fake.ep, [engine.user_message("write x")], [(False, "not in this folder")],
                                       cwd=self.cwd)
        self.assertTrue(done["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.cwd, "x.txt")))
        self.assertEqual(fake.requests[1]["body"]["messages"][-1]["content"],
                         "The user denied this in the chat window: not in this folder")

    def test_plan_refuses_writes_without_asking(self):
        fake = self.server(sse(*call_chunks("edit_file", {"path": "a.txt", "old_string": "a", "new_string": "b"})),
                           sse(*text_chunks("Plan: change a to b.")))
        with open(os.path.join(self.cwd, "a.txt"), "w") as handle:
            handle.write("a")
        _run, events, done = run_sync(fake.ep, [engine.user_message("fix it")], cwd=self.cwd, mode="plan")
        self.assertEqual(kinds(events, "ask"), [])
        with open(os.path.join(self.cwd, "a.txt")) as handle:
            self.assertEqual(handle.read(), "a")
        offered = [t["function"]["name"] for t in fake.requests[0]["body"]["tools"]]
        self.assertEqual(sorted(offered), ["list_dir", "read_file", "search"])
        self.assertIn("plan mode", fake.requests[1]["body"]["messages"][-1]["content"])
        self.assertIn("PLAN MODE", fake.requests[0]["body"]["messages"][0]["content"])

    def test_accept_edits_inside_the_folder_only(self):
        fake = self.server(sse(*call_chunks("write_file", {"path": "in.txt", "content": "one\ntwo\n"})),
                           sse(*call_chunks("write_file", {"path": "/tmp/out-of-cwd.txt", "content": "x"}, "call_2")),
                           sse(*text_chunks("ok")))
        _run, events, _done = run_sync(fake.ep, [engine.user_message("write")], [(False, "")],
                                       cwd=self.cwd, mode="acceptEdits")
        with open(os.path.join(self.cwd, "in.txt")) as handle:
            self.assertEqual(handle.read(), "one\ntwo\n")
        asked = kinds(events, "ask")
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0]["req"]["input"]["file_path"], "/tmp/out-of-cwd.txt")

    def test_edit_needs_one_exact_match(self):
        path = os.path.join(self.cwd, "e.txt")
        with open(path, "w") as handle:
            handle.write("x x\n")
        ctx = engine.ToolContext(self.cwd)
        out, bad = engine.run_tool("edit_file", {"path": "e.txt", "old_string": "x", "new_string": "y"}, ctx)
        self.assertTrue(bad)
        self.assertIn("2 times", out)
        out, bad = engine.run_tool("edit_file", {"path": "e.txt", "old_string": "x", "new_string": "y",
                                                 "replace_all": True}, ctx)
        self.assertFalse(bad, out)
        with open(path) as handle:
            self.assertEqual(handle.read(), "y y\n")

    def test_folder_access_refuses_a_read(self):
        """The tests' Folder access store grants nothing and never prompts:
        a file outside the working directory is not read, and the model is
        told how it could be opened; a secret one is never read."""
        other = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(other)
        with open(os.path.join(other, "notes.txt"), "w") as handle:
            handle.write("private")
        with open(os.path.join(self.cwd, "here.txt"), "w") as handle:
            handle.write("visible")
        fake = self.server(sse(*call_chunks("read_file", {"path": os.path.join(other, "notes.txt")})),
                           sse(*call_chunks("read_file", {"path": "here.txt"}, "call_2")),
                           sse(*text_chunks("done")))
        _run, events, _done = run_sync(fake.ep, [engine.user_message("read them")], cwd=self.cwd,
                                       implied=[self.cwd], session=None, prompt=False)
        refused, allowed = kinds(events, "tool_done")
        self.assertTrue(refused["is_error"])
        self.assertIn("not open to the LLM chat window", refused["output"])
        self.assertNotIn("private", refused["output"])
        self.assertFalse(allowed["is_error"], allowed)
        self.assertIn("visible", allowed["output"])
        self.assertEqual(kinds(events, "ask"), [])      # reads never ask on a card
        ctx = engine.ToolContext(self.cwd, implied=[os.path.expanduser("~")])
        out, bad = engine.run_tool("read_file", {"path": "~/.ssh/id_rsa"}, ctx)
        self.assertTrue(bad)
        self.assertIn("never read", out)

    def test_no_tools_fallback(self):
        fake = self.server(("error", (400, "this model does not support tools")), sse(*text_chunks("plain answer")))
        _run, events, done = run_sync(fake.ep, [engine.user_message("hi")], cwd=self.cwd)
        self.assertTrue(done["ok"])
        self.assertFalse(done["tools"])
        self.assertEqual(len(kinds(events, "no_tools")), 1)
        self.assertIn("tools", fake.requests[0]["body"])
        self.assertNotIn("tools", fake.requests[1]["body"])

    def test_step_limit_ends_without_tools(self):
        script = [sse(*call_chunks("list_dir", {}, f"c{i}")) for i in range(3)] + [sse(*text_chunks("enough"))]
        fake = self.server(*script)
        _run, _events, done = run_sync(fake.ep, [engine.user_message("loop")], cwd=self.cwd,
                                       implied=[self.cwd], max_steps=2)
        self.assertTrue(done["ok"])
        self.assertNotIn("tools", fake.requests[2]["body"])
        self.assertIn("step limit", fake.requests[2]["body"]["messages"][-1]["content"])

    def test_cancel_while_asking(self):
        fake = self.server(sse(*call_chunks("run_command", {"command": "true"})))
        events, done = [], threading.Event()

        def emit(kind, data):
            events.append((kind, data))
            if kind == "ask":
                threading.Thread(target=run.cancel, daemon=True).start()
            if kind == "done":
                done.set()
        run = engine.Run(fake.ep, "fake-model", [engine.user_message("go")], emit, cwd=self.cwd)
        run.start()
        self.assertTrue(done.wait(10))
        result = dict(events)["done"]
        self.assertTrue(result["stopped"])
        self.assertFalse(result["ok"])

    def test_cancel_mid_stream_keeps_what_was_said(self):
        fake = self.server(sse({"choices": [{"index": 0, "delta": {"content": "Half an ans"}}]}, "hang"))
        events, done = [], threading.Event()

        def emit(kind, data):
            events.append((kind, data))
            if kind == "text":
                threading.Thread(target=run.cancel, daemon=True).start()
            if kind == "done":
                done.set()
        run = engine.Run(fake.ep, "fake-model", [engine.user_message("go")], emit, cwd=self.cwd)
        started = time.monotonic()
        run.start()
        self.assertTrue(done.wait(10))
        self.assertLess(time.monotonic() - started, 8)
        result = dict(events)["done"]
        self.assertTrue(result["stopped"])
        self.assertEqual(result["messages"][-1], {"role": "assistant", "content": "Half an ans"})


class Policy(unittest.TestCase):
    def test_modes(self):
        cwd = "/w"
        never = lambda path: False          # noqa: E731
        for mode in ("ask", "auto", "acceptEdits", "plan"):
            self.assertEqual(engine.policy(mode, "read_file", {"path": "x"}, cwd, never), "allow")
        self.assertEqual(engine.policy("ask", "run_command", {"command": "ls"}, cwd, lambda p: True), "ask")
        self.assertEqual(engine.policy("plan", "write_file", {"path": "x"}, cwd), "refuse")
        self.assertEqual(engine.policy("plan", "run_command", {"command": "ls"}, cwd), "refuse")
        self.assertEqual(engine.policy("acceptEdits", "edit_file", {"path": "a/b"}, cwd), "allow")
        self.assertEqual(engine.policy("acceptEdits", "edit_file", {"path": "/etc/x"}, cwd), "ask")
        self.assertEqual(engine.policy("acceptEdits", "run_command", {"command": "ls"}, cwd), "ask")
        self.assertEqual(engine.policy("auto", "run_command", {"command": "git status"}, cwd, lambda p: True), "allow")
        self.assertEqual(engine.policy("auto", "write_file", {"path": "x"}, cwd, lambda p: True), "ask")
        self.assertEqual(engine.policy("bypassPermissions", "run_command", {"command": "ls"}, cwd), "ask")

    def test_safe_commands(self):
        yes = lambda path: True             # noqa: E731
        for cmd in ("ls -la", "git status", "git log --oneline -5", "cat README.md", "grep -rn foo src",
                    "find . -name x.py", "wc -l a b"):
            self.assertTrue(engine.safe_command(cmd, "/w", yes), cmd)
        for cmd in ("rm -rf build", "ls; rm x", "cat a | sh", "echo x > f", "cat $HOME/.ssh/id_rsa",
                    "ls *", "git commit -m x", "git push", "find . -delete", "find . -exec rm {} +",
                    "sort -o out in", "git -c core.pager=sh log", "git diff --output=x", "date -s 10:00",
                    "python3 -c 1", "", "cat `id`", "ls $(pwd)", "ls\nrm x"):
            self.assertFalse(engine.safe_command(cmd, "/w", yes), cmd)
        self.assertFalse(engine.safe_command("ls", "/w", lambda path: False))       # the folder is not open
        self.assertFalse(engine.safe_command("cat /etc/shadow", "/w", lambda path: path == "/w"))


class Sessions(Base):
    def test_round_trip_without_pictures(self):
        folder = os.path.join(self.tmp.name, "sessions")
        sid = engine.new_session_id()
        self.assertTrue(engine.is_session_id(sid))
        msgs = [engine.user_message("look", [{"media": "image/png", "data": b"x"}]),
                {"role": "assistant", "content": "a cat"}]
        path = engine.save_session(sid, msgs, self.cwd, "gemma-4-e4b", folder)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        data = engine.load_session(sid, folder)
        self.assertNotIn("base64", json.dumps(data))
        self.assertEqual(engine.message_words(data["messages"][0]["content"]), "🖼 image\nlook")
        listed = engine.list_sessions(folder=folder)
        self.assertEqual([(i["id"], i["title"], i["kind"]) for i in listed], [(sid, "🖼 image look", "native")])
        self.assertTrue(engine.delete_session(path))
        self.assertFalse(engine.delete_session(os.path.join(folder, "../../etc/passwd.json")))


# -- the window ------------------------------------------------------------------------------------
class Window(Base):
    """The window's native backend on a real llm-chat Front, never shown
    (render=True: no notifications, no Folder access prompt, nothing
    saved), its GLib loop turned by hand until the reply ends."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.front = helpers.import_script("llm-chat.py")
            from gi.repository import GLib, Gtk
            if not Gtk.init_check(sys.argv)[0]:
                raise RuntimeError("no display")
        except Exception as exc:        # noqa: BLE001
            raise unittest.SkipTest(f"no GTK display: {exc}")
        cls.GLib = GLib

    def window(self, fake, mode="ask"):
        front = self.front
        settings = os.path.join(self.tmp.name, "llm.json")
        with open(settings, "w") as handle:
            json.dump({"server_url": fake.base}, handle)
        patches = [mock.patch.object(llm_models, "SETTINGS", settings),
                   mock.patch.object(llm_models, "stale", lambda: False),
                   mock.patch.object(front, "mascot_mood", None),
                   mock.patch.object(front, "PERMISSION", mode),
                   mock.patch.object(front, "FRONT_STATE", os.path.join(self.tmp.name, "llm-chat.json"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        win = front.Front("", self.cwd, None, llm_models.server_model("fake-model"), None, render=True)
        self.addCleanup(win.destroy)
        return win

    def turn(self, win, until, timeout=15):
        ctx = self.GLib.MainContext.default()
        end = time.monotonic() + timeout
        while not until() and time.monotonic() < end:
            ctx.iteration(False)
            time.sleep(0.005)
        self.assertTrue(until(), "the window never got there")

    def test_card_deny_then_session_rule(self):
        fake = self.server(sse(*call_chunks("run_command", {"command": "touch made.txt"})),
                           sse(*text_chunks("Not made, as you said.")),
                           sse(*call_chunks("run_command", {"command": "touch made.txt"}, "call_2")),
                           sse(*text_chunks("Made it.")),
                           sse(*call_chunks("run_command", {"command": "touch made.txt"}, "call_3")),
                           sse(*text_chunks("Made it again.")))
        win = self.window(fake)
        self.assertFalse(win.term_btn.get_visible())        # Claude Code's TUI: Claude models only
        win.send("make it")
        self.turn(win, lambda: win.cards)
        card = next(iter(win.cards.values()))
        self.assertIn("run_command", card.req["display"])
        self.assertFalse(card.answer("deny"))               # not armed yet: a key on its way does nothing
        card.armed = True
        card.note.set_text("not now")
        self.assertTrue(card.answer("deny"))
        self.turn(win, lambda: win.native is None)
        self.assertEqual(fake.requests[1]["body"]["messages"][-1]["content"],
                         "The user denied this in the chat window: not now")
        self.assertFalse(os.path.exists(os.path.join(self.cwd, "made.txt")))
        self.assertEqual(win.chat[-1], {"role": "assistant", "content": "Not made, as you said."})
        # Allow for this session: the next same command goes without a card.
        win.send("now do it")
        self.turn(win, lambda: win.cards)
        card = next(iter(win.cards.values()))
        card.armed = True
        # Running code takes two presses: the first only asks "Sure?".
        card.answer("session")
        self.assertFalse(card.done)
        self.assertIn("Sure?", card.buttons["session"].get_label())
        card.answer("session")                              # a double click: still not
        self.assertFalse(card.done)
        card.answer("once")                                 # the other button starts over
        self.assertEqual(card.buttons["session"].get_label(), "Allow for this session")
        self.assertIn("Sure?", card.buttons["once"].get_label())
        card.answer("session")
        card.confirming = ("session", time.monotonic() - 1)
        card.answer("session")
        self.turn(win, lambda: win.native is None)
        self.assertTrue(os.path.exists(os.path.join(self.cwd, "made.txt")))
        self.assertEqual(win.perm_rules[0]["content"], "touch made.txt")
        win.send("again")
        self.turn(win, lambda: win.native is None and len(fake.requests) == 6)
        self.assertEqual(win.cards, {})
        self.assertEqual(win.chat[-1]["content"], "Made it again.")
        # The conversation went on: every request held the earlier ones.
        self.assertGreater(len(fake.requests[-1]["body"]["messages"]), 8)

    def test_esc_stops_and_cards_expire(self):
        fake = self.server(sse(*call_chunks("write_file", {"path": "w.txt", "content": "w"})))
        win = self.window(fake)
        win.send("write")
        self.turn(win, lambda: win.cards)
        card = next(iter(win.cards.values()))
        win.stop()
        self.turn(win, lambda: win.native is None)
        self.assertTrue(card.done)
        self.assertFalse(os.path.exists(os.path.join(self.cwd, "w.txt")))
        self.assertEqual(win.state, "idle")


# -- no Claude Code installed ------------------------------------------------------------------------
NO_CLAUDE = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
home = os.environ["HOME"]
os.makedirs(os.path.join(home, ".cache"), exist_ok=True)
os.makedirs(os.path.join(home, ".local", "state", "hypr"), exist_ok=True)
with open(os.path.join(home, ".cache", "llm-models.json"), "w") as h:
    json.dump({"stamp": [], "models": [{"modelKey": "google/gemma-4-e4b", "displayName": "Gemma 4 E4B",
                                        "sizeBytes": 6e9, "vision": True}]}, h)
with open(os.path.join(home, ".local", "state", "hypr", "llm.json"), "w") as h:
    json.dump({"default": "opus", "quick": "haiku"}, h)
import llm_models
out = {"cli": llm_models.claude_cli(), "kinds": sorted({m.kind for m in llm_models.all_models()}),
       "opus": llm_models.resolve("opus"), "full_id": llm_models.resolve("claude-opus-5-5")}
model, why = llm_models.chosen_note("default")
out["default"], out["why"] = model.name, why
out["quick"] = llm_models.chosen("quick").name
out["quick_choice"] = llm_models.quick_choice()[0].name
out["vision"] = model.vision
import importlib.util
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(sys.argv[1], file))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
chat = load("llm_chat", "llm-chat.py")
choice, note = chat.pick_start_model(None)
out["window"] = [choice.name, choice.kind, chat.backend(choice), note]
L = load("launcher", "launcher.py")
items = L.ask_items("how tall is mount fuji")
out["ask"] = [(i.name, i.subtitle(), i.alt is not None) for i in items[:4]]
out["commands"] = [i.name for i in L.command_items() if i.name in ("LLM chat", "Claude Code session")]
out["quick_cmd"] = L.quick_model("how tall")[0].name
print(json.dumps(out, default=repr))
'''


class NoClaude(unittest.TestCase):
    """PATH and HOME without claude, $HYPR_CLAUDE_CLI unset: no Claude model
    anywhere, a default naming one falls back to the first local model and
    says so, and the launcher's ? works with that local model."""

    def test_desktop_without_claude_code(self):
        home = tempfile.mkdtemp(dir=helpers.SCRATCH, prefix="home-")
        env = {k: v for k, v in os.environ.items() if k != "HYPR_CLAUDE_CLI"}
        env.update(PATH="/usr/bin:/bin", HOME=home, XDG_STATE_HOME=os.path.join(home, ".local", "state"))
        res = subprocess.run([sys.executable, "-W", "ignore", "-c", NO_CLAUDE, helpers.SCRIPTS], env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stderr[-3000:])
        out = json.loads(res.stdout.strip().splitlines()[-1])
        self.assertIsNone(out["cli"])
        self.assertEqual(out["kinds"], ["local"])
        self.assertIsNone(out["opus"])
        self.assertIsNone(out["full_id"])
        self.assertEqual(out["default"], "gemma-4-e4b")
        self.assertIn("Claude Code is not installed", out["why"])
        self.assertEqual((out["quick"], out["quick_choice"]), ("gemma-4-e4b", "gemma-4-e4b"))
        self.assertTrue(out["vision"])
        self.assertEqual(out["window"][:3], ["gemma-4-e4b", "local", "native"])
        self.assertIn("Claude Code is not installed", out["window"][3])
        hero, *rest = out["ask"]
        self.assertEqual(hero[0], "Ask gemma-4-e4b: how tall is mount fuji")
        self.assertFalse(hero[2])                       # no Shift+Enter into claude
        for name, sub, _alt in out["ask"]:
            self.assertNotIn("claude", (name + sub).lower(), (name, sub))
        self.assertEqual(out["commands"], ["LLM chat"])
        self.assertEqual(out["quick_cmd"], "gemma-4-e4b")


if __name__ == "__main__":
    unittest.main()
