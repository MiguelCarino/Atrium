"""desk_common.py, the helpers the scripts share: the XDG folders, the JSON
read with a fallback and the all-or-nothing JSON write, run() with its
timeout, the notification argv and its failure handling, and the Hyprland
request over a socket (a real Unix socket served by a thread here, standing
in for Hyprland) with its hyprctl fallback.

Hermetic: every file and socket is in a scratch folder; the notifier and
hyprctl are stubbed through subprocess.run / subprocess.Popen."""
import json
import os
import socket
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import helpers

dc = helpers.import_script("desk_common.py")


class FakeHyprland:
    """A .socket.sock in FOLDER/hypr/SIG that answers each request from REPLIES
    (request text -> reply bytes) and records what it was asked."""

    def __init__(self, base, sig="testsig", replies=None, stall=False):
        self.folder = os.path.join(base, "hypr", sig)
        os.makedirs(self.folder, exist_ok=True)
        self.replies = replies or {}
        self.stall = stall
        self.asked = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(os.path.join(self.folder, ".socket.sock"))
        self.server.listen(4)
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        self.server.settimeout(0.2)
        while not self.done.is_set():
            try:
                conn, _ = self.server.accept()
            except OSError:
                continue
            with conn:
                request = conn.recv(65536).decode()
                self.asked.append(request)
                if self.stall:
                    self.done.wait(2)
                    continue
                conn.sendall(self.replies.get(request, b"unknown request"))

    def close(self):
        self.done.set()
        self.thread.join(2)
        self.server.close()


class Folders(unittest.TestCase):
    def test_state_dir_follows_xdg(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/x/state"}):
            self.assertEqual(dc.state_dir(), "/x/state")
            self.assertEqual(dc.state_dir("hypr", "a.json"), "/x/state/hypr/a.json")

    def test_state_dir_default_when_unset_or_empty(self):
        for env in ({}, {"XDG_STATE_HOME": ""}):
            with mock.patch.dict(os.environ, env, clear=False):
                if "XDG_STATE_HOME" not in env:
                    os.environ.pop("XDG_STATE_HOME", None)
                self.assertEqual(dc.state_dir("hypr"), os.path.expanduser("~/.local/state/hypr"))

    def test_runtime_dir(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/x/run"}):
            self.assertEqual(dc.runtime_dir("a"), "/x/run/a")
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": ""}):
            self.assertEqual(dc.runtime_dir(), f"/run/user/{os.getuid()}")


class JsonFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=helpers.SCRATCH)

    def test_read_json_missing_bad_and_good(self):
        path = os.path.join(self.tmp, "a.json")
        self.assertEqual(dc.read_json(path, {"d": 1}), {"d": 1})
        self.assertIsNone(dc.read_json(path))
        with open(path, "w") as handle:
            handle.write("{not json")
        self.assertEqual(dc.read_json(path, []), [])
        with open(path, "w") as handle:
            json.dump([1, 2], handle)
        self.assertEqual(dc.read_json(path, {}), [1, 2])          # untyped: whatever is there

    def test_read_json_typed(self):
        path = os.path.join(self.tmp, "b.json")
        with open(path, "w") as handle:
            json.dump([1, 2], handle)
        self.assertEqual(dc.read_json(path, {}, typed=True), {})
        self.assertEqual(dc.read_json(path, [], typed=True), [1, 2])

    def test_atomic_write_makes_folder_and_round_trips(self):
        path = os.path.join(self.tmp, "deep", "er", "c.json")
        dc.atomic_write_json(path, {"é": [1, 2]})
        with open(path) as handle:
            text = handle.read()
        self.assertEqual(text, json.dumps({"é": [1, 2]}))
        self.assertEqual(os.listdir(os.path.dirname(path)), ["c.json"])   # no temporary left

    def test_atomic_write_formatting_options(self):
        path = os.path.join(self.tmp, "d.json")
        dc.atomic_write_json(path, {"b": "é", "a": 1}, indent=1, ensure_ascii=False, sort_keys=True)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), json.dumps({"b": "é", "a": 1}, indent=1,
                                                       ensure_ascii=False, sort_keys=True))

    def test_atomic_write_mode(self):
        old = os.umask(0o022)
        try:
            plain = os.path.join(self.tmp, "plain.json")
            dc.atomic_write_json(plain, 1)
            self.assertEqual(stat.S_IMODE(os.stat(plain).st_mode), 0o644)   # like open(path, "w")
            private = os.path.join(self.tmp, "private.json")
            dc.atomic_write_json(private, 1, mode=0o600)
            self.assertEqual(stat.S_IMODE(os.stat(private).st_mode), 0o600)
        finally:
            os.umask(old)

    def test_atomic_write_failure_keeps_old_file_and_no_temporary(self):
        path = os.path.join(self.tmp, "e.json")
        dc.atomic_write_json(path, {"old": True})
        with self.assertRaises(TypeError):
            dc.atomic_write_json(path, {"bad": object()})
        self.assertEqual(dc.read_json(path), {"old": True})
        self.assertEqual(os.listdir(self.tmp), ["e.json"])

    def test_atomic_write_without_makedirs_raises(self):
        with self.assertRaises(OSError):
            dc.atomic_write_json(os.path.join(self.tmp, "nope", "f.json"), 1, makedirs=False)


class Run(unittest.TestCase):
    def test_real_command(self):
        done = dc.run(["sh", "-c", "echo hi; exit 3"], timeout=5)
        self.assertEqual((done.returncode, done.stdout), (3, "hi\n"))

    def test_missing_program_and_timeout_are_none(self):
        self.assertIsNone(dc.run(["/nonexistent/program"], timeout=5))
        self.assertIsNone(dc.run(["sleep", "5"], timeout=0.1))

    def test_keywords_pass_through(self):
        with mock.patch.object(subprocess, "run", return_value="r") as fake:
            self.assertEqual(dc.run(("a", "b"), timeout=3, env={"X": "1"}, text=False), "r")
        fake.assert_called_once_with(("a", "b"), timeout=3, env={"X": "1"}, text=False,
                                     capture_output=True)


class Notify(unittest.TestCase):
    def test_argv_minimal(self):
        self.assertEqual(dc.notify_argv("T"), [dc.NOTIFY, "T", ""])

    def test_argv_everything(self):
        argv = dc.notify_argv("T", "B", app="App", urgency="low", icon="ic", expire=2500,
                              hints=["string:x-canonical-private-synchronous:x"], replace_id=7,
                              print_id=True, actions={"open": "Open"}, mood="calm")
        self.assertEqual(argv, [dc.NOTIFY, "--mood", "calm", "-a", "App", "-u", "low", "-i", "ic",
                                "-t", "2500", "-h", "string:x-canonical-private-synchronous:x",
                                "-p", "-r", "7", "--wait", "-A", "open=Open", "T", "B"])

    def test_argv_action_pairs_and_plain_wait(self):
        self.assertEqual(dc.notify_argv("T", actions=[("a", "A"), ("b", "B")])[1:],
                         ["--wait", "-A", "a=A", "-A", "b=B", "T", ""])
        self.assertEqual(dc.notify_argv("T", wait=True)[1:], ["--wait", "T", ""])

    def test_dash_title_stays_text(self):
        # notify-send reads options only before the summary; the summary is last-but-one.
        self.assertEqual(dc.notify_argv("-u critical", "b")[-2:], ["-u critical", "b"])

    def test_returns_stripped_stdout(self):
        done = subprocess.CompletedProcess([], 0, "open\n", "")
        with mock.patch.object(subprocess, "run", return_value=done) as fake:
            self.assertEqual(dc.notify("T", actions={"open": "Open"}, timeout=None), "open")
        self.assertIsNone(fake.call_args.kwargs["timeout"])

    def test_failures_are_empty(self):
        for exc in (OSError("gone"), subprocess.TimeoutExpired("n", 5)):
            with mock.patch.object(subprocess, "run", side_effect=exc):
                self.assertEqual(dc.notify("T"), "")

    def test_background_popen(self):
        with mock.patch.object(subprocess, "Popen") as popen:
            self.assertEqual(dc.notify("T", "B", app="A", mood="calm", background=True), "")
        argv = popen.call_args.args[0]
        self.assertEqual(argv, [dc.NOTIFY, "--mood", "calm", "-a", "A", "T", "B"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        with mock.patch.object(subprocess, "Popen", side_effect=OSError):
            self.assertEqual(dc.notify("T", background=True), "")


class Hyprland(unittest.TestCase):
    def setUp(self):
        self.run_dir = tempfile.mkdtemp(dir="/tmp", prefix="dc-")   # short: AF_UNIX path limit
        self.env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.run_dir,
                                                "HYPRLAND_INSTANCE_SIGNATURE": "testsig"})
        self.env.start()
        self.fakes = []

    def tearDown(self):
        for fake in self.fakes:
            fake.close()
        self.env.stop()
        import shutil
        shutil.rmtree(self.run_dir, True)

    def hypr(self, **kw):
        fake = FakeHyprland(self.run_dir, **kw)
        self.fakes.append(fake)
        return fake

    def test_socket_dir_from_signature(self):
        self.assertEqual(dc.hypr_socket_dir(), os.path.join(self.run_dir, "hypr", "testsig"))

    def test_socket_dir_newest_without_signature(self):
        os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE")
        self.assertIsNone(dc.hypr_socket_dir())
        old = os.path.join(self.run_dir, "hypr", "old")
        new = os.path.join(self.run_dir, "hypr", "new")
        empty = os.path.join(self.run_dir, "hypr", "empty")
        for folder in (old, new, empty):
            os.makedirs(folder)
        for folder, when in ((old, 1000), (new, 2000)):
            open(os.path.join(folder, ".socket.sock"), "w").close()
            os.utime(folder, (when, when))
        os.utime(empty, (3000, 3000))
        self.assertEqual(dc.hypr_socket_dir(), new)

    def test_json_request_over_socket_starts_no_process(self):
        fake = self.hypr(replies={"j/clients": b'[{"class": "a"}]', "j/monitors all": b"[]"})
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("forked")):
            self.assertEqual(dc.hypr_request("clients", json=True), [{"class": "a"}])
            self.assertEqual(dc.hypr_request(["monitors", "all"], json=True), [])
        self.assertEqual(fake.asked, ["j/clients", "j/monitors all"])

    def test_text_request_and_bad_json(self):
        self.hypr(replies={"version": b"Hyprland 0.56", "j/broken": b"{nope"})
        self.assertEqual(dc.hypr_request("version"), "Hyprland 0.56")
        self.assertIsNone(dc.hypr_request("broken", json=True))
        self.assertIsNone(dc.hypr_request("unknownthing", json=True))   # "unknown request"

    def test_stalled_socket_is_none_without_hyprctl(self):
        self.hypr(stall=True)
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("forked")):
            self.assertIsNone(dc.hypr_request("clients", json=True, timeout=0.2))

    def test_falls_back_to_hyprctl_when_unreachable(self):
        done = subprocess.CompletedProcess([], 0, '{"int": 1}', "")
        with mock.patch.object(subprocess, "run", return_value=done) as fake:
            self.assertEqual(dc.hypr_request("getoption animations:enabled", json=True, timeout=3),
                             {"int": 1})
        self.assertEqual(fake.call_args.args[0], ["hyprctl", "getoption", "animations:enabled", "-j"])
        self.assertEqual(fake.call_args.kwargs["timeout"], 3)

    def test_fallback_failures_are_none(self):
        cases = (subprocess.CompletedProcess([], 1, "HYPRLAND_INSTANCE_SIGNATURE not set", ""),
                 subprocess.CompletedProcess([], 0, "", ""),
                 OSError("no hyprctl"))
        for case in cases:
            kw = {"side_effect": case} if isinstance(case, Exception) else {"return_value": case}
            with mock.patch.object(subprocess, "run", **kw):
                self.assertIsNone(dc.hypr_request("clients", json=True))

    def test_fallback_text_mode(self):
        done = subprocess.CompletedProcess([], 0, "ok\n", "")
        with mock.patch.object(subprocess, "run", return_value=done) as fake:
            self.assertEqual(dc.hypr_request("dispatch workspace 2"), "ok\n")
        self.assertEqual(fake.call_args.args[0], ["hyprctl", "dispatch", "workspace", "2"])


if __name__ == "__main__":
    unittest.main()
